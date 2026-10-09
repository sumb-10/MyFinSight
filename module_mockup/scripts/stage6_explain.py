"""
Stage 6 (LLM #3, optional): write Korean rationale for the selected stocks.

in : output/05_selection.json, output/04_tagging.json, output/02_intent.json
out: output/06_selection_explained.json ; prompt in output/prompts/06_explain.md
Stub mode needs stubs/06_explain.example.json (not provided by default -> the prompt is still saved).
"""
import argparse
from common import OUTPUT, load_json, dump_json
from llm import load_prompts, call_llm


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default=str(OUTPUT / "06_selection_explained.json"))
    a = ap.parse_args()
    sel, tag, intent = load_json(OUTPUT / "05_selection.json"), load_json(OUTPUT / "04_tagging.json"), load_json(OUTPUT / "02_intent.json")
    reason = {r["ticker"]: r["reason_ko"] for r in tag["tagged"]}
    block = "\n".join(f"{s['rank']} | {s['ticker']} | {s['name']} | {s['sector']} | {s['metric_value']:.3f} | "
                      f"{s['theme_confidence']} | {reason.get(s['ticker'], '')}" for s in sel["selected"])
    system, user = load_prompts("06_explain", summary_ko=intent["interpretation"]["summary_ko"],
                                explanation_level=intent["report_settings"]["explanation_level"],
                                metric=sel["summary"]["metric"], direction=sel["summary"]["direction"],
                                as_of=sel["summary"]["as_of"], selected_block=block,
                                warnings_block="\n".join(f"- {w}" for w in sel["warnings"]) or "- 없음")
    ans = call_llm("06_explain", system, user)
    out = {"request_id": sel["request_id"], "stage": "06_selection_explained", **ans}
    dump_json(out, a.out)
    print(f"[stage6] ok -> {a.out}")


if __name__ == "__main__":
    main()
