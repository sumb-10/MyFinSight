"""
Stage 4 (LLM #2, batched): classify each candidate against the themes.

in : output/03_candidates.json, output/02_intent.json
out: output/04_tagging.json ; prompts in output/prompts/04_classify_b<i>.md
Stub mode: stubs/04_tagging.example.json holds {"results": [...]} for all candidates; each batch
takes the subset for its tickers (missing tickers -> warning, treated as unclassified).
"""
import argparse
from common import OUTPUT, load_json, dump_json
from llm import load_prompts, call_llm
from schemas import Tagging, TagResult

BATCH = 40


def themes_block(themes):
    return "\n".join(f"- `{t['id']}` **{t['label_ko']}**: {t['description_ko']}" for t in themes)


def exclude_block(rules):
    return "\n".join(f"- `{r['theme']}`: 키워드 {', '.join(r['keywords'])}" for r in rules) or "- 없음"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--candidates", default=str(OUTPUT / "03_candidates.json"))
    ap.add_argument("--intent", default=str(OUTPUT / "02_intent.json"))
    ap.add_argument("--out", default=str(OUTPUT / "04_tagging.json"))
    args = ap.parse_args()

    cand, intent = load_json(args.candidates), load_json(args.intent)
    themes = intent["interpretation"]["themes"]
    theme_ids = {t["id"] for t in themes}
    min_conf = intent["screen"]["theme_filter"]["min_confidence"]
    rows = cand["candidates"]
    batches = [rows[i:i + BATCH] for i in range(0, len(rows), BATCH)]

    warnings, results = [], {}
    for bi, batch in enumerate(batches, 1):
        block = "\n".join(f"{x['ticker']} | {x['name']} | {x['gics']['sub_industry']['name']} | {x['company_summary']}" for x in batch)
        system, user = load_prompts("04_classify", batch_index=bi, batch_total=len(batches), batch_size=len(batch),
                                    themes_block=themes_block(themes),
                                    exclude_block=exclude_block(intent.get("exclude_theme_rules", [])),
                                    candidates_block=block)
        ans = call_llm("04_classify", system, user, batch=bi, stub_file=None)
        want = {x["ticker"] for x in batch}
        got = {r["ticker"]: r for r in ans["results"] if r["ticker"] in want}
        extra = {r["ticker"] for r in ans["results"]} - want
        if extra and len(batches) == 1:
            warnings.append(f"batch {bi}: LLM returned tickers not in batch {sorted(extra)}")
        for t in want - set(got):
            warnings.append(f"batch {bi}: no classification for {t} -> treated as not in theme")
            got[t] = {"ticker": t, "in_theme": False, "themes": [], "confidence": 0.0,
                      "reason_ko": "LLM 응답 누락", "excluded_theme": None}
        results.update(got)

    tagged, excluded = [], []
    for x in rows:
        r = TagResult.model_validate(results[x["ticker"]])
        bad = [t for t in r.themes if t not in theme_ids]
        if bad:
            warnings.append(f"{r.ticker}: unknown theme ids {bad} removed")
            r.themes = [t for t in r.themes if t in theme_ids]
        if x["forced"] and not r.in_theme:
            warnings.append(f"{r.ticker}: must_include but not in theme -> kept (forced)")
        (excluded if r.excluded_theme else tagged).append(r)
    passed = [r.ticker for r in tagged if (r.in_theme and r.confidence >= min_conf)
              or any(x["ticker"] == r.ticker and x["forced"] for x in rows)]

    out = Tagging(request_id=cand["request_id"], min_confidence=min_conf, tagged=tagged,
                  excluded_by_theme=excluded, passed_tickers=passed, batches=len(batches), warnings=warnings)
    dump_json(out.model_dump(mode="json"), args.out)
    print(f"[stage4] ok -> {args.out}\n         batches={len(batches)} tagged={len(tagged)} "
          f"excluded={len(excluded)} passed(conf>={min_conf})={len(passed)}")
    for w in warnings: print("         !", w)


if __name__ == "__main__":
    main()
