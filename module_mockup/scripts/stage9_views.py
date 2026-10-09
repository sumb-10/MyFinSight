"""
Stage 9 (LLM #4): generate Black-Litterman views, n_sets scenarios x views_per_set.

in : output/07_backtest_spec.json, 08_market_model.json, 08_baseline_portfolios.json, 02_intent.json, input/02_backtest_request.jsonc
out: output/09_views.json ; prompt in output/prompts/09_views.md
"""
import argparse, datetime as dt
import numpy as np
import pandas as pd
from common import INPUT, OUTPUT, load_json, load_jsonc, dump_json
from descriptor import load_descriptor
from llm import load_prompts, call_llm
import portfolio as P
import portfolio_config as PC
from schemas import Views


def trailing_12m_return(tickers, as_of):
    px = P.load_adj_close(tickers, pd.Timestamp(as_of) - pd.Timedelta(days=380), pd.Timestamp(as_of) - pd.Timedelta(days=1))
    return (px.iloc[-1] / px.iloc[0] - 1).to_dict()


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--backtest-request", default=str(INPUT / "02_backtest_request.jsonc"))
    ap.add_argument("--out", default=str(OUTPUT / "09_views.json"))
    a = ap.parse_args()
    bt_req = load_jsonc(a.backtest_request)
    spec, mm, base, intent = (load_json(OUTPUT / f) for f in ["07_backtest_spec.json", "08_market_model.json", "08_baseline_portfolios.json", "02_intent.json"])
    desc = load_descriptor()
    as_of = dt.date.fromisoformat(mm["as_of"])
    tk = mm["tickers"]
    n_sets, per_set = bt_req["views"]["n_sets"], bt_req["views"]["views_per_set"]
    max_conf = intent["news_tilt"]["max_view_confidence"]
    wb = next(p for p in base["portfolios"] if p["id"] == base["chosen_baseline"])["weights"]
    r12 = trailing_12m_return(tk, as_of)

    rows = []
    for t in tk:
        c = desc["companies"][t]
        rows.append(f"{t} | {c['name']} | {c['gics']['sector']['name']} | {c['company_summary'][:120]} | "
                    f"{r12.get(t, float('nan')):+.1%} | {mm['ann_vol'][t]:.1%} | {mm['cap_weights'][t]:.1%} | {wb[t]:.1%} | {mm['implied_returns'][t]:+.1%}")
    themes_block = "\n".join(f"- {th['id']}: {th['label_ko']} — {th['description_ko']}" for th in intent["interpretation"]["themes"])
    system, user = load_prompts("09_views", as_of=as_of, summary_ko=intent["interpretation"]["summary_ko"], themes_block=themes_block,
                                stocks_block="\n".join(rows), n_sets=n_sets, views_per_set=per_set, max_conf=max_conf,
                                abs_range=f"{PC.ABS_RETURN_RANGE[0]:+.0%} ~ {PC.ABS_RETURN_RANGE[1]:+.0%}",
                                rel_range=f"{PC.REL_RETURN_RANGE[0]:+.0%} ~ {PC.REL_RETURN_RANGE[1]:+.0%}")
    system = system.replace("{{as_of}}", str(as_of)).replace("{{max_conf}}", str(max_conf)).replace("{{n_sets}}", str(n_sets)) \
                   .replace("{{views_per_set}}", str(per_set)).replace("{{abs_range}}", f"{PC.ABS_RETURN_RANGE[0]:+.0%} ~ {PC.ABS_RETURN_RANGE[1]:+.0%}") \
                   .replace("{{rel_range}}", f"{PC.REL_RETURN_RANGE[0]:+.0%} ~ {PC.REL_RETURN_RANGE[1]:+.0%}")
    ans = call_llm("09_views", system, user, validator=lambda a: (_ for _ in ()).throw(AssertionError("sets must be a non-empty list")) if not (isinstance(a.get("sets"), list) and a["sets"]) else None)

    # ── guardrails ──
    warnings, sets, known = [], [], set(tk)
    for s in ans.get("sets", []):
        seen, views = set(), []
        for v in s.get("views", []):
            bad = [x for x in v.get("long", []) + v.get("short", []) if x not in known]
            if bad:
                warnings.append(f"{s.get('scenario_id')}: view dropped, unknown tickers {bad}"); continue
            key = (tuple(sorted(v["long"])), tuple(sorted(v.get("short", []))))
            if key in seen:
                warnings.append(f"{s.get('scenario_id')}: duplicate view {key} dropped"); continue
            seen.add(key)
            c = float(v["confidence"])
            if not (PC.CONFIDENCE_FLOOR <= c <= max_conf):
                warnings.append(f"{s.get('scenario_id')}: confidence {c} clipped to [{PC.CONFIDENCE_FLOOR}, {max_conf}]")
                v["confidence"] = min(max(c, PC.CONFIDENCE_FLOOR), max_conf)
            lo, hi = PC.ABS_RETURN_RANGE if v["type"] == "absolute" else PC.REL_RETURN_RANGE
            r = float(v["expected_return_annual"])
            if not (lo <= r <= hi):
                warnings.append(f"{s.get('scenario_id')}: return {r} clipped to [{lo}, {hi}]"); v["expected_return_annual"] = min(max(r, lo), hi)
            v.setdefault("evidence_type", "llm_placeholder"); v.setdefault("horizon_months", 12)
            views.append(v)
        if len(views) > per_set:
            warnings.append(f"{s.get('scenario_id')}: {len(views)} views, truncated to {per_set}"); views = views[:per_set]
        if views:
            sets.append({**s, "views": views})
    if len(sets) != n_sets:
        warnings.append(f"{len(sets)} sets returned, expected {n_sets}")
    out = Views(request_id=spec["request_id"], as_of=as_of, hindsight_risk=True, max_view_confidence=max_conf, sets=sets, warnings=warnings)
    dump_json(out.model_dump(mode="json"), a.out)
    print(f"[stage9] ok -> {a.out}\n         sets={len(sets)} views={[len(s.views) for s in out.sets]} max_conf={max_conf}")
    for s in out.sets: print(f"         - {s.scenario_id}: {s.title_ko} | " + "; ".join(f"{v.type[:3]} {'+'.join(v.long)}{'>' + '+'.join(v.short) if v.short else ''} {v.expected_return_annual:+.0%}@{v.confidence}" for v in s.views))
    for w in warnings: print("         !", w)


if __name__ == "__main__":
    main()
