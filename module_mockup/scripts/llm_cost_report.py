"""Summarize LLM token usage and cost from output/llm_usage.jsonl.

  python scripts/llm_cost_report.py [--run-id ID]   (default: the most recent run_id)
Writes output/llm_cost_report.json.
"""
import argparse, json
from collections import defaultdict
import llm_config as C
from common import OUTPUT, dump_json

DESCRIPTOR_BATCHES = 13     # 518 tickers / 40 per batch -> one-time stage-0 cost extrapolation


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--run-id", default=None)
    a = ap.parse_args()
    rows = [json.loads(l) for l in open(C.USAGE_LOG, encoding="utf-8") if l.strip()]
    run = a.run_id or rows[-1]["run_id"]
    rows = [r for r in rows if r["run_id"] == run]
    per = defaultdict(lambda: {"calls": 0, "prompt_tokens": 0, "cached_tokens": 0, "completion_tokens": 0, "reasoning_tokens": 0, "cost_usd": 0.0, "elapsed_s": 0.0})
    for r in rows:
        p = per[r["stage"]]; p["calls"] += 1
        for k in ("prompt_tokens", "cached_tokens", "completion_tokens", "reasoning_tokens", "elapsed_s"): p[k] += r[k] or 0
        p["cost_usd"] += r["cost_usd"] or 0
    total = {k: sum(p[k] for p in per.values()) for k in ("calls", "prompt_tokens", "cached_tokens", "completion_tokens", "reasoning_tokens", "cost_usd", "elapsed_s")}
    pipeline = {k: v for k, v in per.items() if not k.startswith("00_")}
    pipe_cost = sum(p["cost_usd"] for p in pipeline.values())
    desc = per.get("00_descriptor")
    desc_full = round(desc["cost_usd"] / desc["calls"] * DESCRIPTOR_BATCHES, 4) if desc else None

    print(f"run_id={run} model={rows[0]['model'] if rows else C.MODEL}")
    print(f"{'stage':<16}{'calls':>6}{'in':>9}{'cached':>8}{'out':>8}{'reason':>8}{'cost$':>10}{'sec':>7}")
    for s, p in sorted(per.items()):
        print(f"{s:<16}{p['calls']:>6}{p['prompt_tokens']:>9}{p['cached_tokens']:>8}{p['completion_tokens']:>8}{p['reasoning_tokens']:>8}{p['cost_usd']:>10.4f}{p['elapsed_s']:>7.0f}")
    print(f"{'TOTAL':<16}{total['calls']:>6}{total['prompt_tokens']:>9}{total['cached_tokens']:>8}{total['completion_tokens']:>8}{total['reasoning_tokens']:>8}{total['cost_usd']:>10.4f}{total['elapsed_s']:>7.0f}")
    print(f"per-request pipeline cost (stages 01-06): ${pipe_cost:.4f}" + (f" | one-time descriptor (x{DESCRIPTOR_BATCHES} batches est.): ${desc_full}" if desc_full is not None else ""))
    dump_json({"run_id": run, "model": C.MODEL, "pricing_usd_per_1m": C.PRICING_USD_PER_1M.get(C.MODEL), "per_stage": per,
               "total": total, "pipeline_cost_usd": round(pipe_cost, 6), "descriptor_full_build_est_usd": desc_full},
              OUTPUT / "llm_cost_report.json")


if __name__ == "__main__":
    main()
