"""
Stage 2 (LLM #1): interpret the request into an IntentSpec (themes -> GICS codes/keywords, params).

in : output/01_request.json, input/*.jsonc (raw text with comments for the prompt), descriptor (GICS tree)
out: output/02_intent.json ; rendered prompt in output/prompts/02_intent.md
LLM answer comes from stubs/02_intent.example.json unless MYFINSIGHT_LLM=api.
"""
import argparse
from pathlib import Path
from common import INPUT, OUTPUT, load_json, dump_json
from descriptor import load_descriptor, render_tree
from llm import load_prompts, call_llm
from schemas import IntentSpec, TEMPLATE_METRICS


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--request", default=str(INPUT / "01_user_request.example.jsonc"))
    ap.add_argument("--normalized", default=str(OUTPUT / "01_request.json"))
    ap.add_argument("--out", default=str(OUTPUT / "02_intent.json"))
    args = ap.parse_args()

    req = load_json(args.normalized)
    desc = load_descriptor()
    system, user = load_prompts("02_intent",
                                user_request_jsonc=Path(args.request).read_text(encoding="utf-8").strip(),
                                as_of=req["derived"]["as_of"],
                                initial_amount_usd=f"{req['derived']['initial_amount_usd']:,.0f}",
                                gics_tree=render_tree(desc))
    ans = call_llm("02_intent", system, user)

    # ── code-side guardrails on the LLM answer ──
    warnings = []
    known = {c for lvl in desc["taxonomy_counts"].values() for c in lvl}
    universe = set(desc["companies"])
    for th in ans["interpretation"]["themes"] + ans.get("exclude_theme_rules", []):
        bad = [c for c in th["gics_codes"] if c not in known]
        if bad:
            warnings.append(f"theme {th.get('id', th.get('theme'))}: dropped unknown GICS codes {bad}")
            th["gics_codes"] = [c for c in th["gics_codes"] if c in known]
        if "example_tickers" in th:
            out = [t for t in th["example_tickers"] if t not in universe]
            if out:
                warnings.append(f"theme {th['id']}: dropped tickers outside universe {out}")
                th["example_tickers"] = [t for t in th["example_tickers"] if t in universe]
    ans["request_id"] = req["request_id"]
    sp, cons = req["strategy_preference"], req["constraints"]
    metric, direction = TEMPLATE_METRICS[sp["template"]]
    forced = {"template": sp["template"], "metric": metric, "direction": direction,
              "as_of": req["derived"]["as_of"], "select_top_n": cons["num_holdings"]["target"]}
    for k, v in forced.items():
        if ans["screen"].get(k) != v:
            warnings.append(f"screen.{k}: LLM gave {ans['screen'].get(k)!r}, enforced {v!r}")
            ans["screen"][k] = v
    ans["news_tilt"]["enabled"] = sp["use_news_tilt"]
    ans["warnings"] = warnings

    spec = IntentSpec.model_validate(ans)
    dump_json(spec.model_dump(mode="json"), args.out)
    print(f"[stage2] ok -> {args.out}\n         themes={[t.id for t in spec.interpretation.themes]} "
          f"codes={sum(len(t.gics_codes) for t in spec.interpretation.themes)} warnings={len(warnings)}")
    for w in warnings: print("         !", w)


if __name__ == "__main__":
    main()
