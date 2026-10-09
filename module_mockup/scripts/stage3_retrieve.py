"""
Stage 3: retrieve candidate tickers from the descriptor using the IntentSpec (no LLM).

in : output/02_intent.json, output/01_request.json, descriptor, RAW/prices.parquet
out: output/03_candidates.json

Rules (per theme, then union):
  gics_match     company code8 starts with any selected GICS code
  keyword_match  theme keyword found in name / keywords / company_summary
  example_match  LLM example ticker in universe
Hard filters: exclude_tickers, exclude_sectors, exclude_theme_rules (gics + keywords), asset_types,
              min_market_cap_usd (needs sharesOutstanding from info_snapshot; skipped with a warning if absent),
              min_avg_daily_volume_usd (60 trading days before as_of), price history >= MIN_HISTORY_DAYS before as_of.
Size: cap at MAX_CANDIDATES (rank by #rules matched, then ADV); if < target, widen each code one level up (once).
"""
import argparse, datetime as dt
from collections import Counter, defaultdict
import pandas as pd
import pyarrow.parquet as pq
import pyarrow.compute as pc
from common import OUTPUT, RAW, load_json, dump_json
from descriptor import load_descriptor, filter_by_gics, search_keywords, sector_name_to_code, parents_of
from schemas import Candidates

MAX_CANDIDATES = 120
MIN_HISTORY_DAYS = 400      # calendar days of prices required before as_of (covers 12m metrics)
ADV_WINDOW = 60             # trading days


def load_prices(tickers, start, end):
    t = pq.read_table(RAW / "prices.parquet", columns=["date", "ticker", "close", "volume"],
                      filters=[("ticker", "in", list(tickers)), ("date", ">=", pd.Timestamp(start)),
                               ("date", "<=", pd.Timestamp(end))])
    return t.to_pandas()


def first_dates(tickers):
    t = pq.read_table(RAW / "prices.parquet", columns=["date", "ticker"],
                      filters=[("ticker", "in", list(tickers))]).to_pandas()
    return t.groupby("ticker")["date"].min()


def collect(desc, themes):
    """ticker -> {matched_by:set, matched_themes:set}"""
    hits = defaultdict(lambda: {"matched_by": set(), "matched_themes": set()})
    for th in themes:
        for t in filter_by_gics(desc, th["gics_codes"]):
            hits[t]["matched_by"].add("gics_match"); hits[t]["matched_themes"].add(th["id"])
        for t in search_keywords(desc, th["keywords"]):
            hits[t]["matched_by"].add("keyword_match"); hits[t]["matched_themes"].add(th["id"])
        for t in th["example_tickers"]:
            if t in desc["companies"]:
                hits[t]["matched_by"].add("example_match"); hits[t]["matched_themes"].add(th["id"])
    return hits


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--intent", default=str(OUTPUT / "02_intent.json"))
    ap.add_argument("--normalized", default=str(OUTPUT / "01_request.json"))
    ap.add_argument("--out", default=str(OUTPUT / "03_candidates.json"))
    ap.add_argument("--as-of", default=None, help="override screen.as_of (YYYY-MM-DD), e.g. for backtest re-selection")
    args = ap.parse_args()

    intent, req = load_json(args.intent), load_json(args.normalized)
    desc = load_descriptor()
    cons = req["constraints"]
    as_of = dt.date.fromisoformat(args.as_of or intent["screen"]["as_of"])
    target = cons["num_holdings"]["target"]
    warnings, filtered, stats = [], [], {"by_rule": Counter(), "by_filter": Counter()}

    themes = intent["interpretation"]["themes"]
    hits = collect(desc, themes)
    if len(hits) < target:
        widened = []
        for th in themes:
            th = dict(th); th["gics_codes"] = sorted({p[0] for c in th["gics_codes"] for p in [parents_of(c)] if p} | set(th["gics_codes"]))
            widened.append(th)
        hits = collect(desc, widened)
        warnings.append(f"fewer than target after matching; widened GICS codes one level up -> {len(hits)}")
    for t in cons["must_include_tickers"]:
        if t in desc["companies"]:
            hits[t]["matched_by"].add("must_include"); hits[t]["matched_themes"].add("must_include")
        else:
            warnings.append(f"must_include ticker {t} not in universe")
    for h in hits.values():
        for r in h["matched_by"]: stats["by_rule"][r] += 1

    # ── hard filters ──
    sec_code = sector_name_to_code(desc)
    excl_sectors = set()
    for s in cons["exclude_sectors"]:
        if s in sec_code: excl_sectors.add(sec_code[s])
        else: warnings.append(f"exclude_sectors: unknown sector name {s!r}")
    excl_rules = intent.get("exclude_theme_rules", [])
    excl_by_rule = {}
    for r in excl_rules:
        for t in filter_by_gics(desc, r["gics_codes"]): excl_by_rule[t] = f"exclude_theme:{r['theme']}(gics)"
        for t in search_keywords(desc, r["keywords"]): excl_by_rule.setdefault(t, f"exclude_theme:{r['theme']}(keyword)")

    def drop(t, reason):
        filtered.append({"ticker": t, "reason": reason}); stats["by_filter"][reason.split("(")[0]] += 1

    kept = {}
    for t, h in hits.items():
        c = desc["companies"][t]
        forced = "must_include" in h["matched_by"]
        if forced:
            kept[t] = h; continue
        if t in set(cons["exclude_tickers"]): drop(t, "exclude_tickers"); continue
        if c["gics"]["sector"]["code"] in excl_sectors: drop(t, "exclude_sectors"); continue
        if t in excl_by_rule: drop(t, excl_by_rule[t]); continue
        if "stock" not in cons["asset_types"]: drop(t, "asset_types"); continue   # universe is stocks only
        kept[t] = h

    # price-based filters
    fd = first_dates(kept.keys())
    px = load_prices(kept.keys(), as_of - dt.timedelta(days=ADV_WINDOW * 2), as_of)
    px["dollar_vol"] = px["close"] * px["volume"]
    adv = px.sort_values("date").groupby("ticker").tail(ADV_WINDOW).groupby("ticker")["dollar_vol"].mean()
    last_close = px.sort_values("date").groupby("ticker")["close"].last()
    info_p = RAW / "info_snapshot.json"
    shares = {r["ticker"]: r.get("sharesOutstanding") for r in load_json(info_p)} if info_p.exists() else None
    if shares is None and cons["min_market_cap_usd"] > 0:
        warnings.append("min_market_cap_usd not applied: info_snapshot.json (sharesOutstanding) not available yet")

    cands = []
    for t, h in kept.items():
        c = desc["companies"][t]
        forced = "must_include" in h["matched_by"]
        if t not in fd.index or (pd.Timestamp(as_of) - fd[t]).days < MIN_HISTORY_DAYS:
            if not forced: drop(t, "insufficient_price_history"); continue
            warnings.append(f"must_include {t}: insufficient price history, kept anyway")
        a = float(adv.get(t, float("nan")))
        if not forced and (pd.isna(a) or a < cons["min_avg_daily_volume_usd"]):
            drop(t, "min_avg_daily_volume_usd"); continue
        mcap = None
        if shares and shares.get(t) and t in last_close.index:
            mcap = float(shares[t]) * float(last_close[t])
            if not forced and mcap < cons["min_market_cap_usd"]:
                drop(t, "min_market_cap_usd"); continue
        cands.append({"ticker": t, "name": c["name"], "gics": c["gics"], "company_summary": c["company_summary"],
                      "market_cap_usd": mcap, "adv_usd": None if pd.isna(a) else round(a, 0),
                      "matched_by": sorted(h["matched_by"]), "matched_themes": sorted(h["matched_themes"]),
                      "forced": forced})

    if len(cands) > MAX_CANDIDATES:
        cands.sort(key=lambda x: (x["forced"], len(x["matched_by"]), x["adv_usd"] or 0), reverse=True)
        for x in cands[MAX_CANDIDATES:]: drop(x["ticker"], "candidate_cap")
        cands = cands[:MAX_CANDIDATES]
        warnings.append(f"candidate cap {MAX_CANDIDATES} applied")
    if len(cands) < target:
        warnings.append(f"only {len(cands)} candidates for target {target}")
    cands.sort(key=lambda x: x["ticker"])

    out = Candidates(request_id=req["request_id"], as_of=as_of, candidates=cands, filtered_out=filtered,
                     stats={"n_matched": len(hits), "n_candidates": len(cands), "n_filtered": len(filtered),
                            "by_rule": dict(stats["by_rule"]), "by_filter": dict(stats["by_filter"]),
                            "by_theme": dict(Counter(th for x in cands for th in x["matched_themes"]))},
                     warnings=warnings)
    dump_json(out.model_dump(mode="json"), args.out)
    print(f"[stage3] ok -> {args.out}\n         matched={len(hits)} candidates={len(cands)} filtered={len(filtered)}")
    print(f"         by_rule={dict(stats['by_rule'])}\n         by_filter={dict(stats['by_filter'])}")
    for w in warnings: print("         !", w)


if __name__ == "__main__":
    main()
