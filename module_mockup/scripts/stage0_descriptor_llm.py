"""
Stage 0 (LLM #0, optional, offline): generate Korean one-line summaries + keywords for the descriptor.

in : descriptor (+ RAW/info_snapshot.json longBusinessSummary when available)
out: data/processed/descriptor_llm_overrides.json  -> then re-run build_descriptor.py to merge
Stub mode: stubs/00_descriptor.example.json (covers a few tickers); others are left untouched.
"""
import argparse
from common import RAW, PROCESSED, load_json, dump_json
from descriptor import load_descriptor
from llm import load_prompts, call_llm

BATCH = 40


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--limit", type=int, default=None, help="only first N tickers (for stub testing)")
    a = ap.parse_args()
    desc = load_descriptor()
    info = {r["ticker"]: r for r in load_json(RAW / "info_snapshot.json")} if (RAW / "info_snapshot.json").exists() else {}
    tickers = sorted(desc["companies"])[: a.limit]
    batches = [tickers[i:i + BATCH] for i in range(0, len(tickers), BATCH)]
    results = {}
    for bi, b in enumerate(batches, 1):
        block = "\n".join(f"{t} | {desc['companies'][t]['name']} | {desc['companies'][t]['gics']['sub_industry']['name']} | "
                          f"{((info.get(t) or {}).get('longBusinessSummary') or '')[:400]}" for t in b)
        system, user = load_prompts("00_descriptor", batch_index=bi, batch_total=len(batches), batch_size=len(b), companies_block=block)
        ans = call_llm("00_descriptor", system, user, batch=bi)
        results.update({r["ticker"]: r for r in ans["results"] if r["ticker"] in b})
    dump_json({"results": list(results.values())}, PROCESSED / "descriptor_llm_overrides.json")
    print(f"[stage0] {len(results)} overrides -> data/processed/descriptor_llm_overrides.json (re-run build_descriptor.py to merge)")


if __name__ == "__main__":
    main()
