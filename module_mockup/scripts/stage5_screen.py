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
    max_stock, max_sector = cons["max_weight_per_stock"], cons["max_weight_per_sector"]
    investable = 1.0 - cons["min_cash_ratio"]
    sector_cap = max(1, math.floor(max_sector * n))          # preferred max NAMES per sector (diversification), not the hard limit

    def capacity(counts):
        """Max total weight that can be placed with per-stock and per-sector caps (weights are set later in stage 8)."""
        return sum(min(k * max_stock, max_sector) for k in counts.values())

    pool.sort(key=lambda x: (x[0] not in forced, (x[1] if direction == "asc" else -x[1]) if math.isfinite(x[1]) else float("inf")))
    selected, sec_count, deferred, overflow = [], Counter(), [], []
    sector_of = lambda t: (desc["companies"][t]["gics"]["sector"]["code"], desc["companies"][t]["gics"]["sector"]["name"])
    for t, v in pool:                                          # pass 1: rank order with the per-sector name preference
        sc, sn = sector_of(t)
        if len(selected) >= n:
            rejected.append({"ticker": t, "reason": "rank_beyond_n", "metric_value": v}); continue
        if sec_count[sc] >= sector_cap and t not in forced:
            deferred.append((t, v)); continue
        sec_count[sc] += 1
        selected.append({"ticker": t, "name": desc["companies"][t]["name"], "sector": sn, "sector_code": sc, "rank": len(selected) + 1,
                         "metric_name": metric, "metric_value": v if math.isfinite(v) else float("nan"), "theme_confidence": conf.get(t), "forced": t in forced})
    for t, v in deferred:                                      # pass 2: fill the remaining slots from the deferred names (weights get squeezed by the sector cap)
        sc, sn = sector_of(t)
        if len(selected) >= n:
            rejected.append({"ticker": t, "reason": "rank_beyond_n", "metric_value": v}); continue
        sec_count[sc] += 1; overflow.append(t)
        selected.append({"ticker": t, "name": desc["companies"][t]["name"], "sector": sn, "sector_code": sc, "rank": len(selected) + 1,
                         "metric_name": metric, "metric_value": v if math.isfinite(v) else float("nan"), "theme_confidence": conf.get(t), "forced": t in forced})
    cap_now = capacity(sec_count)
    infeasibility, sector_overflow = None, None
    if cap_now < investable - 1e-9:                            # even squeezing cannot place all the money within the caps
        sec_names = {s["sector_code"]: s["sector"] for s in selected}
        needed = next((round(c / 100, 2) for c in range(int(max_sector * 100), 101, 5) if sum(min(k * max_stock, c / 100) for k in sec_count.values()) >= investable), None)
        infeasibility = {"reason": "weight_capacity", "target": nh["target"], "n_selected": len(selected), "capacity": round(cap_now, 4), "required": investable,
                         "sector_cap": max_sector, "stock_cap": max_stock, "sector_counts": {sec_names[c]: k for c, k in sec_count.items()}, "cap_needed_for_target": needed,
                         "options_ko": [f"섹터 상한을 {needed:.0%} 로 올리기" if needed else "섹터 상한 완화로도 해결 불가", "종목당 상한을 올리기", "테마를 넓혀 다른 섹터 후보를 늘리기"]}
        warnings.append(f"weight capacity {cap_now:.2f} < {investable:.2f}: caps cannot absorb the capital with these sectors (cap needed {needed})")
    if overflow:
        top_sec = Counter(sector_of(t)[1] for t in overflow).most_common(1)[0][0]
        k = sum(1 for s_ in selected if s_["sector"] == top_sec)
        sector_overflow = {"count_preference": sector_cap, "tickers": overflow, "sector": top_sec, "n_in_sector": k,
                           "note_ko": f"{top_sec} 종목이 {k}개로 섹터 상한 {max_sector:.0%}를 나눠 갖습니다(동일비중 기준 약 {max_sector / k:.1%}씩). 상위 순위 종목을 빼지 않기 위해 종목 수 대신 비중으로 상한을 지킵니다."}
        warnings.append(f"sector name preference ({sector_cap}/sector) exceeded for {len(overflow)} tickers {overflow}; sector cap is enforced by weights in stage 8")
    if len(selected) < n:
        warnings.append(f"selected {len(selected)} < n={n}: not enough passed tickers")
    out = Selection(request_id=req["request_id"], selected=selected, rejected=rejected, infeasibility=infeasibility,
                    summary={"as_of": str(as_of), "metric": metric, "direction": direction,
                             "n_candidates": len(tag["tagged"]), "n_tagged": len(tickers), "n_with_metric": n_pass,
                             "n_target": nh["target"], "n_selected": len(selected), "sector_cap": sector_cap, "weight_capacity": round(cap_now, 4), "sector_overflow": sector_overflow,
                             "sector_counts": {desc["companies"][s["ticker"]]["gics"]["sector"]["name"]: k
                                               for s in selected for k in [sec_count[s["sector_code"]]]}},
                    warnings=warnings)
    dump_json(out.model_dump(mode="json"), args.out)
    print(f"[stage5] ok -> {args.out}\n         metric={metric} {direction} passed={n_pass} selected={len(selected)} sector_name_pref={sector_cap} capacity={cap_now:.2f} overflow={overflow}")
    for s in selected: print(f"         {s['rank']:>2} {s['ticker']:<6} {s['metric_value']:>9.3f}  {s['sector']}")
    for w in warnings: print("         !", w)


if __name__ == "__main__":
    main()
