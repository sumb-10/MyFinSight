"""
Stage 7: user confirmation + backtest window -> backtest spec (and re-selection at the window start).

in : input/02_backtest_request.jsonc, output/01_request.json, 02_intent.json, 04_tagging.json, 05_selection.json
out: output/07_backtest_spec.json
     (+ 07_request_bt.json, 07_candidates_bt.json, 07_tagging_bt.json, 07_selection_bt.json when reselecting)

Re-selection re-runs only the deterministic stages (3 retrieve, 5 screen) at as_of = backtest start,
reusing the LLM outputs (02 themes, 04 tagging) which do not depend on the date.
"""
import argparse, datetime as dt, subprocess, sys
from pathlib import Path
import pandas as pd
import pyarrow.parquet as pq
from common import INPUT, OUTPUT, RAW, load_jsonc, load_json, dump_json
from descriptor import load_descriptor
from portfolio import trading_days
from stage1_normalize import fx_rate_on
from schemas import BacktestRequest, BacktestSpec
import portfolio_config as PC

HERE = Path(__file__).resolve().parent
MIN_HISTORY_DAYS = 400


def first_dates(tickers):
    t = pq.read_table(RAW / "prices.parquet", columns=["date", "ticker"], filters=[("ticker", "in", list(tickers))]).to_pandas()
    return t.groupby("ticker")["date"].min()


def run(script, *args):
    cmd = [sys.executable, str(HERE / script), *map(str, args)]
    print("  $", script, " ".join(map(str, args)), flush=True)
    subprocess.run(cmd, check=True)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--backtest-request", default=str(INPUT / "02_backtest_request.jsonc"))
    ap.add_argument("--out", default=str(OUTPUT / "07_backtest_spec.json"))
    ap.add_argument("--fx-rate-bt", type=float, default=None, help="manual KRW per USD at the backtest start (fallback)")
    a = ap.parse_args()

    bt_req = BacktestRequest.model_validate(load_jsonc(a.backtest_request))
    req, intent = load_json(OUTPUT / "01_request.json"), load_json(OUTPUT / "02_intent.json")
    tagging, sel = load_json(OUTPUT / "04_tagging.json"), load_json(OUTPUT / "05_selection.json")
    desc = load_descriptor()
    warnings = []
    if bt_req.request_id != req["request_id"]:
        warnings.append(f"request_id mismatch: {bt_req.request_id} vs {req['request_id']}")
    if not bt_req.confirmation.selection_confirmed:
        raise SystemExit("[stage7] selection not confirmed by user -> stop")

    # ── window & calendar ──
    d0, d1 = dt.date.fromisoformat(req["derived"]["price_data_start"]), dt.date.fromisoformat(req["derived"]["price_data_end"])
    bw = bt_req.backtest
    if not (d0 <= bw.start_date < bw.end_date <= d1):
        raise SystemExit(f"[stage7] backtest window {bw.start_date}..{bw.end_date} outside data {d0}..{d1}")
    bench = bw.benchmark or req["risk"]["benchmark"]
    cal = trading_days(bw.start_date, bw.end_date, bench="SPY")
    as_of = cal[0].date()
    if (pd.Timestamp(as_of) - pd.Timestamp(d0)).days < PC.LOOKBACK_DAYS * 1.45:
        warnings.append(f"less than {PC.LOOKBACK_DAYS} trading days of history before as_of for the covariance window")

    # ── selection at as_of ──
    added = [t for t in bt_req.confirmation.added_tickers if t in desc["companies"]]
    bad = sorted(set(bt_req.confirmation.added_tickers) - set(added))
    if bad: warnings.append(f"added_tickers not in universe ignored: {bad}")
    removed = set(bt_req.confirmation.removed_tickers)

    if bw.reselect_at_start:
        req_bt = dict(req)
        req_bt["constraints"] = dict(req["constraints"])
        req_bt["constraints"]["must_include_tickers"] = sorted(set(req["constraints"]["must_include_tickers"]) | set(added))
        req_bt["constraints"]["exclude_tickers"] = sorted(set(req["constraints"]["exclude_tickers"]) | removed)
        dump_json(req_bt, OUTPUT / "07_request_bt.json")
        run("stage3_retrieve.py", "--as-of", as_of, "--normalized", OUTPUT / "07_request_bt.json", "--out", OUTPUT / "07_candidates_bt.json")
        cand_bt = {c["ticker"] for c in load_json(OUTPUT / "07_candidates_bt.json")["candidates"]}
        tag_bt = dict(tagging)
        tag_bt["passed_tickers"] = sorted((set(tagging["passed_tickers"]) & cand_bt | set(added)) - removed)
        tag_bt["warnings"] = tagging.get("warnings", []) + [f"re-selection at {as_of}: passed ∩ candidates_bt = {len(tag_bt['passed_tickers'])}"]
        dump_json(tag_bt, OUTPUT / "07_tagging_bt.json")
        run("stage5_screen.py", "--as-of", as_of, "--normalized", OUTPUT / "07_request_bt.json",
            "--tagging", OUTPUT / "07_tagging_bt.json", "--out", OUTPUT / "07_selection_bt.json")
        sel_bt = load_json(OUTPUT / "07_selection_bt.json")
        source, rows = "reselected_at_start", sel_bt["selected"]
        warnings += [f"stage5@{as_of}: {w}" for w in sel_bt["warnings"]]
    else:
        source, rows = "original", [r for r in sel["selected"] if r["ticker"] not in removed]
        fd = first_dates([r["ticker"] for r in rows])
        keep = []
        for r in rows:
            if (pd.Timestamp(as_of) - fd[r["ticker"]]).days < MIN_HISTORY_DAYS:
                warnings.append(f"{r['ticker']} dropped: insufficient history before {as_of} (listed {fd[r['ticker']].date()})")
            else:
                keep.append(r)
        rows = keep
        for i, t in enumerate(added):
            c = desc["companies"][t]
            rows.append({"ticker": t, "name": c["name"], "sector": c["gics"]["sector"]["name"], "rank": len(rows) + 1, "metric_value": float("nan")})
        warnings.append("original selection used at an earlier date: selection look-ahead bias present")

    tickers = [r["ticker"] for r in rows]
    orig = [r["ticker"] for r in sel["selected"]]
    # ── capital converted at the BACKTEST start date (not the request's start_date) ──
    c = req["capital"]
    if c["currency"] == "USD":
        rate, fx_date, fx_src = 1.0, as_of, "none"
    else:
        rate, fx_date, fx_src = fx_rate_on(f"{c['currency']}=X", as_of, a.fx_rate_bt)
    init_usd, monthly_usd = round(c["initial_amount"] / rate, 2), round(c["monthly_contribution"] / rate, 2)
    if abs(init_usd - req["derived"]["initial_amount_usd"]) / init_usd > 0.02:
        warnings.append(f"capital re-converted at {fx_date} FX {rate:.2f}: {init_usd:,.0f} USD vs request-date {req['derived']['initial_amount_usd']:,.0f} USD")
    spec = BacktestSpec(
        request_id=req["request_id"],
        period={"start": bw.start_date, "end": bw.end_date, "as_of": as_of, "trading_days": int(len(cal))},
        capital={"initial_amount_usd": init_usd, "monthly_contribution_usd": monthly_usd if bw.include_contributions else 0.0,
                 "contribution_day": c["contribution_day"], "include_contributions": bw.include_contributions,
                 "currency": c["currency"], "initial_amount_krw": c["initial_amount"] if c["currency"] == "KRW" else None,
                 "monthly_contribution_krw": c["monthly_contribution"] if c["currency"] == "KRW" else None,
                 "fx_rate": rate, "fx_date": fx_date, "fx_source": fx_src},
        rebalance_rule=req["derived"]["rebalance_rule"], benchmark=bench,
        selection={"source": source, "metric": sel["summary"]["metric"], "tickers": tickers,
                   "table": [{"ticker": r["ticker"], "name": r["name"], "sector": r["sector"], "rank": r["rank"], "metric_value": r["metric_value"]} for r in rows],
                   "diff_vs_original": {"added": sorted(set(tickers) - set(orig)), "removed": sorted(set(orig) - set(tickers))},
                   "infeasibility": (sel_bt.get("infeasibility") if bw.reselect_at_start else sel.get("infeasibility")),
                   "sector_overflow": (sel_bt["summary"].get("sector_overflow") if bw.reselect_at_start else sel["summary"].get("sector_overflow"))},
        warnings=warnings)
    dump_json(spec.model_dump(mode="json"), a.out)
    print(f"[stage7] ok -> {a.out}\n         window {bw.start_date}..{bw.end_date} as_of={as_of} trading_days={len(cal)} benchmark={bench} "
          f"capital={init_usd:,.0f} USD @ FX {rate:.2f} ({fx_src}, {fx_date})")
    print(f"         selection({source}) n={len(tickers)}: {tickers}")
    print(f"         diff vs original: +{spec.selection.diff_vs_original['added']} -{spec.selection.diff_vs_original['removed']}")
    for w in warnings: print("         !", w)


if __name__ == "__main__":
    main()
