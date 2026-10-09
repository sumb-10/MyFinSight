"""
Stage 5: quantitative screen on theme-passed tickers -> final stock list (no LLM).

in : output/04_tagging.json, output/02_intent.json, output/01_request.json, price/fundamental caches
out: output/05_selection.json

Selection: drop metric-missing -> keep must_include -> sort by metric/direction ->
           per-sector cap = floor(max_weight_per_sector * n) -> take n = target
           (n = max(min, passed) if fewer pass; warning if below min).
"""
import argparse, math, datetime as dt
from collections import Counter
from common import OUTPUT, load_json, dump_json
from descriptor import load_descriptor
from metrics import METRICS
from schemas import Selection


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--tagging", default=str(OUTPUT / "04_tagging.json"))
    ap.add_argument("--intent", default=str(OUTPUT / "02_intent.json"))
    ap.add_argument("--normalized", default=str(OUTPUT / "01_request.json"))
    ap.add_argument("--out", default=str(OUTPUT / "05_selection.json"))
    ap.add_argument("--as-of", default=None, help="override screen.as_of (YYYY-MM-DD), e.g. for backtest re-selection")
    args = ap.parse_args()

    tag, intent, req = load_json(args.tagging), load_json(args.intent), load_json(args.normalized)
    desc = load_descriptor()
    cons = req["constraints"]
    scr = intent["screen"]
    as_of = dt.date.fromisoformat(args.as_of or scr["as_of"])
    metric, direction = scr["metric"], scr["direction"]
    nh = cons["num_holdings"]
    forced = set(cons["must_include_tickers"])
    conf = {r["ticker"]: r["confidence"] for r in tag["tagged"]}
    tickers = list(tag["passed_tickers"])
    warnings, rejected = [], []

    values = METRICS[metric](tickers, as_of)
    pool = []
    for t in tickers:
        if t in values.index and math.isfinite(values[t]):
            pool.append((t, float(values[t])))
        else:
            reason = "metric_missing" + (" (eps<=0 or <4 quarters)" if metric == "pe_ttm" else "")
            if t in forced:
                warnings.append(f"must_include {t}: {reason}, kept with metric=nan")
                pool.append((t, float("nan")))
            else:
                rejected.append({"ticker": t, "reason": reason, "metric_value": None})

    n_pass = len(pool)
    n = nh["target"] if n_pass >= nh["target"] else max(nh["min"], n_pass)
    if n_pass < nh["target"]:
        warnings.append(f"only {n_pass} tickers have {metric}; target {nh['target']} -> selecting {min(n, n_pass)}")
    if n_pass < nh["min"]:
        warnings.append(f"below num_holdings.min={nh['min']} -> validation stage should fail this run")
    sector_cap = max(1, math.floor(cons["max_weight_per_sector"] * n))

    pool.sort(key=lambda x: (x[0] not in forced, (x[1] if direction == "asc" else -x[1]) if math.isfinite(x[1]) else float("inf")))
    selected, sec_count = [], Counter()
    for rank_src, (t, v) in enumerate(pool, 1):
        c = desc["companies"][t]
        sc, sn = c["gics"]["sector"]["code"], c["gics"]["sector"]["name"]
        if len(selected) >= n:
            rejected.append({"ticker": t, "reason": "rank_beyond_n", "metric_value": v}); continue
        if sec_count[sc] >= sector_cap and t not in forced:
            rejected.append({"ticker": t, "reason": f"sector_cap({sn}>{sector_cap})", "metric_value": v}); continue
        sec_count[sc] += 1
        selected.append({"ticker": t, "name": c["name"], "sector": sn, "sector_code": sc, "rank": len(selected) + 1,
                         "metric_name": metric, "metric_value": v if math.isfinite(v) else float("nan"),
                         "theme_confidence": conf.get(t), "forced": t in forced})

    if len(selected) < n:
        capped = sum(1 for r in rejected if r["reason"].startswith("sector_cap"))
        warnings.append(f"selected {len(selected)} < n={n}: {capped} tickers blocked by sector cap "
                        f"(max_weight_per_sector={cons['max_weight_per_sector']} -> {sector_cap}/sector)")
    out = Selection(request_id=req["request_id"], selected=selected, rejected=rejected,
                    summary={"as_of": str(as_of), "metric": metric, "direction": direction,
                             "n_candidates": len(tag["tagged"]), "n_tagged": len(tickers), "n_with_metric": n_pass,
                             "n_target": nh["target"], "n_selected": len(selected), "sector_cap": sector_cap,
                             "sector_counts": {desc["companies"][s["ticker"]]["gics"]["sector"]["name"]: k
                                               for s in selected for k in [sec_count[s["sector_code"]]]}},
                    warnings=warnings)
    dump_json(out.model_dump(mode="json"), args.out)
    print(f"[stage5] ok -> {args.out}\n         metric={metric} {direction} passed={n_pass} selected={len(selected)} sector_cap={sector_cap}")
    for s in selected: print(f"         {s['rank']:>2} {s['ticker']:<6} {s['metric_value']:>9.3f}  {s['sector']}")
    for w in warnings: print("         !", w)


if __name__ == "__main__":
    main()
