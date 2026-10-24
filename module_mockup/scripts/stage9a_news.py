"""
Stage 9a: news evidence windows for every construction date (walk-forward rebalances + forward as_of).

in : output/07_backtest_spec.json (rebalance window, re-selected tickers), output/05_selection.json (current tickers),
     input/02_backtest_request*.jsonc, optional input/news_web_evidence.<name>.json (web-search records for windows the DB lacks)
out: output/09a_news_evidence.json  {windows: {date: {tickers: {t: [evidence_id...]}, n_articles, n_tickers_with_news, enough, origin_counts}}, all_evidence: {id: record}}
"""
import argparse, datetime as dt
import pandas as pd
from common import INPUT, OUTPUT, load_json, load_jsonc, dump_json
from portfolio import trading_days
from backtest_engine import rebalance_dates
import portfolio_config as PC
from news_db import fetch_news, to_records


def window_records(tickers, d, web):
    start, end = d - dt.timedelta(days=PC.NEWS_WINDOW_DAYS), d
    df = fetch_news(tickers, start, end)
    recs = to_records(df, "db") if len(df) else []
    for r in web.get(str(d), []):          # web-search records: only for this window's tickers and dates (DB records come first)
        if r["ticker"] in tickers and start <= dt.date.fromisoformat(r["published_at"]) < end:
            recs.append({**r, "origin": "web_search"})
    return recs, (start, end)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--backtest-request", default=str(INPUT / "02_backtest_request.jsonc"))
    ap.add_argument("--web-evidence", default=None, help="json with {date: [records]} from web search for windows without DB news")
    ap.add_argument("--out", default=str(OUTPUT / "09a_news_evidence.json"))
    a = ap.parse_args()
    bt_req = load_jsonc(a.backtest_request)
    spec, sel, req = load_json(OUTPUT / "07_backtest_spec.json"), load_json(OUTPUT / "05_selection.json"), load_json(OUTPUT / "01_request.json")
    web = load_json(a.web_evidence) if a.web_evidence else {}
    as_of, end = dt.date.fromisoformat(spec["period"]["as_of"]), dt.date.fromisoformat(spec["period"]["end"])
    cal = trading_days(as_of, end, spec["benchmark"])
    dates = {}
    if bt_req.get("walkforward", {}).get("enabled"):
        for d in rebalance_dates(spec["rebalance_rule"], cal, as_of): dates[d.date()] = ("walkforward", spec["selection"]["tickers"])
    if bt_req.get("forward_construction", {}).get("enabled"):
        fwd = bt_req["forward_construction"].get("as_of") or req["derived"]["price_data_end"]
        dates[dt.date.fromisoformat(str(fwd))] = ("forward", [s["ticker"] for s in sel["selected"]])
    windows, all_ev = {}, {}
    for d, (kind, tickers) in sorted(dates.items()):
        recs, (ws, we) = window_records(tickers, d, web)
        by_t = {}
        for r in recs:
            all_ev[r["evidence_id"]] = r; by_t.setdefault(r["ticker"], []).append(r["evidence_id"])
        n_t = sum(1 for t in tickers if by_t.get(t))
        windows[str(d)] = {"kind": kind, "window": [str(ws), str(we)], "tickers": {t: by_t.get(t, []) for t in tickers}, "n_articles": len(recs),
                           "n_tickers_with_news": n_t, "enough": n_t >= PC.MIN_NEWS_TICKERS,
                           "origin_counts": {o: sum(1 for r in recs if r["origin"] == o) for o in {"db", "web_search"}}}
        print(f"[stage9a] {d} ({kind}) window {ws}..{we}: articles={len(recs)} tickers_with_news={n_t}/{len(tickers)} enough={n_t >= PC.MIN_NEWS_TICKERS} origins={windows[str(d)]['origin_counts']}")
    dump_json({"request_id": spec["request_id"], "stage": "09a_news_evidence", "window_days": PC.NEWS_WINDOW_DAYS, "per_ticker": PC.NEWS_PER_TICKER,
               "min_tickers": PC.MIN_NEWS_TICKERS, "windows": windows, "all_evidence": all_ev}, a.out)
    print(f"[stage9a] ok -> {a.out}  evidence={len(all_ev)}")


if __name__ == "__main__":
    main()
