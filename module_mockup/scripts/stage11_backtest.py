"""
Stage 11: bt backtest of every target portfolio (5 BL + 4 templates) and the benchmark.

in : output/10_target_portfolios.json, 08_market_model.json, 02_intent.json, 01_request.json, price caches
out: output/11_backtest_results.json  (+ output/11_daily_panel.parquet)
"""
import argparse, datetime as dt, hashlib
import numpy as np
import pandas as pd
import pyarrow.parquet as pq
import bt as btlib
from common import OUTPUT, RAW, load_json, dump_json
from descriptor import load_descriptor
from portfolio import trading_days
import backtest_config as BC
import backtest_metrics as M
from backtest_engine import (load_price_panel, rebalance_dates, contribution_dates, run_static_portfolio, extract_raw, xirr)
from schemas import BacktestResults

TO_DATE_KEYS = ["total_return", "cagr", "ann_vol", "sharpe", "sortino", "max_drawdown", "calmar", "excess_cagr", "beta",
                "information_ratio", "irr_annual", "positive_months_ratio", "active_return_vs_baseline"]


def _f(x, n=6):
    return M._r(x, n)


def slice_raw(raw, d):
    return {"id": raw["id"], "index": raw["index"][:d], "values": raw["values"][:d], "flows": raw["flows"][:d],
            "security_weights": raw["security_weights"][:d], "positions": raw["positions"][:d], "turnover": raw["turnover"][:d],
            "transactions": raw["transactions"][raw["transactions"]["Date"] <= d]}


def flat_to_date(res, n_days):
    m, mo = res["metrics"], res["money"]
    out = {"total_return": m["return"]["total_return"], "cagr": m["return"]["cagr"], "ann_vol": m["risk"]["ann_vol"],
           "sharpe": m["risk_adjusted"]["sharpe"], "sortino": m["risk_adjusted"]["sortino"], "max_drawdown": m["risk"]["max_drawdown"],
           "calmar": m["risk_adjusted"]["calmar"], "excess_cagr": m["vs_benchmark"]["excess_cagr"], "beta": m["vs_benchmark"]["beta"],
           "information_ratio": m["vs_benchmark"]["information_ratio"], "irr_annual": mo["irr_annual"],
           "positive_months_ratio": m["return"]["positive_months_ratio"],
           "active_return_vs_baseline": (m["vs_baseline"] or {}).get("active_return"), "reliable": n_days >= BC.TRADING_DAYS}
    return out


def build_checkpoints(raw, bench_raw, panel, targets, sectors, cp_dates, rb_set, last, cfg_metrics, views, implied, as_of, end):
    sw, pos, tx, tv = raw["security_weights"], raw["positions"], raw["transactions"], raw["turnover"]
    idx, values, flows = raw["index"], raw["values"], raw["flows"]
    cols = [c for c in targets if c in sw.columns]
    contrib = flows.copy(); contrib.iloc[0] = 0.0
    cum_contrib = contrib.cumsum()
    r_assets = panel[cols].pct_change().reindex(sw.index).fillna(0.0)
    tgt = pd.Series(targets)[cols]
    out, prev = [], None
    for seq, d in enumerate(cp_dates):
        kind = "closing" if d == last and d not in rb_set else ("rebalance" if d in rb_set else "monthly")
        pos_d = sw.index.get_loc(d)
        before = sw.iloc[pos_d - 1][cols] if pos_d > 0 else None
        after = sw.loc[d][cols]
        seg = sw.loc[prev:d] if prev is not None else sw.loc[:d]
        seg_r = r_assets.loc[seg.index]
        if prev is not None:
            seg_w, seg_r2 = seg.iloc[:-0 or None], seg_r
            per_contrib = (seg[cols].shift(1) * seg_r[cols]).loc[seg.index > prev].sum()
            per_ret = panel.loc[d, cols] / panel.loc[prev, cols] - 1
        else:
            per_contrib = pd.Series(0.0, index=cols); per_ret = pd.Series(0.0, index=cols)
        hold = [{"ticker": c, "shares_after": _f(pos.loc[d, c], 4), "price": _f(panel.loc[d, c], 4),
                 "value_usd": _f(pos.loc[d, c] * panel.loc[d, c], 2),
                 "weight_before": _f(before[c]) if before is not None else None, "weight_after": _f(after[c]),
                 "period_return": _f(per_ret[c]), "period_contribution": _f(per_contrib[c])} for c in cols]
        txd = tx[tx["Date"] == d]
        trades = [{"ticker": r.Security, "side": "buy" if r.quantity > 0 else "sell", "shares": _f(abs(r.quantity), 4),
                   "price": _f(r.price, 4), "value_usd": _f(abs(r.quantity) * r.price, 2)} for r in txd.itertuples()]
        comm = float(sum(t["value_usd"] for t in trades) * BC.COMMISSION_BPS / 1e4)
        drift = None
        if prev is not None:
            between = sw.loc[prev:d][cols].iloc[1:-1] if pos_d - sw.index.get_loc(prev) > 1 else sw.loc[[d]][cols] * 0
            sec_between = pd.DataFrame({s: between[[c for c in cols if sectors[c] == s]].sum(axis=1) for s in set(sectors[c] for c in cols)})
            sec_tgt = pd.Series({s: tgt[[c for c in cols if sectors[c] == s]].sum() for s in sec_between.columns})
            drift = {"max_weight_drift": _f((between - tgt).abs().max().max()) if len(between) else 0.0,
                     "max_sector_drift": _f((sec_between - sec_tgt).abs().max().max()) if len(between) else 0.0,
                     "breaches": sorted({f"stock_cap:{c}" for c in cols if (between[c] > cfg_metrics["max_stock"] * (1 + BC.DRIFT_TOLERANCE)).any()}
                                        | {f"sector_cap:{s}" for s in sec_between.columns if (sec_between[s] > cfg_metrics["max_sector"] * (1 + BC.DRIFT_TOLERANCE)).any()})}
        money = {"value_usd": _f(values[d], 2), "cumulative_contributions_usd": _f(cum_contrib[d], 2),
                 "net_invested_usd": _f(flows[:d].sum(), 2), "profit_usd": _f(values[d] - flows[:d].sum(), 2),
                 "benchmark_value_usd": _f(bench_raw["values"].get(d, np.nan), 2)}
        since_last = None
        if prev is not None:
            seg_idx = idx.loc[prev:d]; seg_b = bench_raw["index"].loc[prev:d]; rr = M.daily_returns(seg_idx)
            best, worst = per_ret.idxmax(), per_ret.idxmin()
            since_last = {"return": _f(seg_idx.iloc[-1] / seg_idx.iloc[0] - 1), "benchmark_return": _f(seg_b.iloc[-1] / seg_b.iloc[0] - 1),
                          "excess": _f((seg_idx.iloc[-1] / seg_idx.iloc[0]) - (seg_b.iloc[-1] / seg_b.iloc[0])),
                          "max_drawdown": _f(M.drawdown_series(seg_idx).min()), "ann_vol": _f(M.ann_vol(rr)) if len(rr) > 1 else None,
                          "best": {"ticker": best, "return": _f(per_ret[best])}, "worst": {"ticker": worst, "return": _f(per_ret[worst])}}
        n_days = pos_d
        to_date, vd = None, []
        if n_days >= 5:
            sub = M.compute_all(slice_raw(raw, d), bench_raw["index"][:d], panel[:d], targets, sectors, cfg_metrics["rb"], cfg_metrics["rf"],
                                cfg_metrics["target_return"], cfg_metrics["max_stock"], cfg_metrics["max_sector"], xirr,
                                baseline_idx=cfg_metrics["baseline_idx"][:d] if cfg_metrics["baseline_idx"] is not None else None,
                                views=views, implied=implied, as_of=as_of, end=d)
            to_date = flat_to_date(sub, n_days); vd = sub["view_diagnostics"]
        out.append({"seq": seq, "date": str(d.date()), "kind": kind, "n_trading_days_to_date": int(n_days),
                    "weights": {"target": {c: _f(tgt[c]) for c in cols}, "before": {c: _f(before[c]) for c in cols} if before is not None else None,
                                "after": {c: _f(after[c]) for c in cols},
                                "cash_before": _f(1 - before.sum()) if before is not None else None, "cash_after": _f(1 - after.sum())},
                    "drift": drift, "holdings": hold, "trades": trades, "turnover": _f(tv.get(d, np.nan)), "commission_usd": _f(comm, 2),
                    "money": money, "since_last": since_last, "to_date": to_date, "view_diagnostics_to_date": vd})
        prev = d
    return out


def build_events(raw, rb_dates, contrib_dates, checkpoints):
    idx = raw["index"]; dd = M.drawdown_series(idx); ev = []
    crossed, peak_val = set(), idx.iloc[0]
    for d, v in dd.items():
        if v == 0:
            if crossed:
                ev.append({"date": str(d.date()), "type": "new_high", "message_ko": "낙폭을 회복해 신고가 갱신"}); crossed = set()
            continue
        for lvl in BC.EVENT_DRAWDOWN_LEVELS:
            if v <= lvl and lvl not in crossed:
                crossed.add(lvl); ev.append({"date": str(d.date()), "type": f"drawdown_{int(abs(lvl) * 100)}", "message_ko": f"고점 대비 {lvl:.0%} 하락"})
    ev += [{"date": str(d.date()), "type": "rebalance", "message_ko": "리밸런싱"} for d in rb_dates]
    ev += [{"date": str(d.date()), "type": "contribution", "message_ko": "월 적립"} for d in contrib_dates]
    for cp in checkpoints:
        for b in (cp.get("drift") or {}).get("breaches", []):
            ev.append({"date": cp["date"], "type": "cap_breach", "message_ko": f"리밸런싱 전 제약 이탈: {b}"})
    return sorted(ev, key=lambda e: e["date"])


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--targets", default=str(OUTPUT / "10_target_portfolios.json"))
    ap.add_argument("--out", default=str(OUTPUT / "11_backtest_results.json"))
    a = ap.parse_args()
    targets = load_json(a.targets); spec = targets["backtest_spec"]
    intent, req, mm = load_json(OUTPUT / "02_intent.json"), load_json(OUTPUT / "01_request.json"), load_json(OUTPUT / "08_market_model.json")
    desc = load_descriptor()
    as_of, end = pd.Timestamp(spec["period"]["as_of"]), pd.Timestamp(spec["period"]["end"])
    bench = spec["benchmark"]; tickers = spec["selection"]["tickers"]
    cal = trading_days(as_of, end, bench)
    panel = load_price_panel(tickers, bench, as_of, end)
    rb = rebalance_dates(spec["rebalance_rule"], cal, as_of); rb_set = set(rb)
    cap = spec["capital"]
    cd = contribution_dates(cal, as_of, end, cap["contribution_day"]) if cap["include_contributions"] and cap["monthly_contribution_usd"] > 0 else []
    amount = cap["monthly_contribution_usd"] if cd else 0.0
    sectors = {t: desc["companies"][t]["gics"]["sector"]["name"] for t in tickers}; sectors[bench] = "Benchmark"
    cons = req["constraints"]; rf = BC.RISK_FREE_RATE
    target_return = intent["validation_criteria"]["target_annual_return"]
    last = panel.index[-1]
    cp_dates = sorted(set(rb) | {last} | (set(panel.resample("ME").last().index.intersection(panel.index)) if BC.CHECKPOINT_FREQ == "monthly" else set()))
    warnings = []

    def run(pid, weights):
        b, res = run_static_portfolio(pid, weights, panel, cap["initial_amount_usd"], rb, cd, amount)
        return extract_raw(b, res, as_of)

    print(f"[stage11] as_of={as_of.date()} end={end.date()} days={len(panel)} rebalances={len(rb)} contributions={len(cd)}x{amount:.0f} bench={bench}", flush=True)
    bench_raw = run(f"benchmark_{bench}", {bench: 1.0})
    runs = {}
    for p in targets["portfolios"] + targets["templates"]:
        runs[p["id"]] = run(p["id"], p["weights"])
    baseline_id = targets["baseline"]["id"]
    baseline_idx = runs[baseline_id]["index"]

    def block(p, raw, kind, bidx):
        views = p.get("views_applied") if kind == "black_litterman" else None
        cfg_m = {"rb": rb, "rf": rf, "target_return": target_return, "max_stock": cons["max_weight_per_stock"],
                 "max_sector": cons["max_weight_per_sector"], "baseline_idx": bidx}
        res = M.compute_all(raw, bench_raw["index"], panel, p["weights"], sectors, rb, rf, target_return, cons["max_weight_per_stock"],
                            cons["max_weight_per_sector"], xirr, baseline_idx=bidx, views=views, implied=mm["implied_returns"], as_of=as_of, end=end)
        cps = build_checkpoints(raw, bench_raw, panel, p["weights"], sectors, cp_dates, rb_set, last, cfg_m, views, mm["implied_returns"], as_of, end)
        m = res["metrics"]
        hits = [v["hit"] for v in res["view_diagnostics"]]
        headline = {"final_value_usd": res["money"]["final_value_usd"], "cagr": m["return"]["cagr"], "excess_cagr": m["vs_benchmark"]["excess_cagr"],
                    "max_drawdown": m["risk"]["max_drawdown"], "sharpe": m["risk_adjusted"]["sharpe"],
                    "view_hit_ratio": _f(np.mean(hits)) if hits else None}
        contrib = raw["flows"].copy(); contrib.iloc[0] = 0.0
        ledger = [{"date": str(d.date()), "amount_usd": _f(v, 2), "value_before_usd": _f(raw["values"].shift(1).get(d, np.nan), 2)} for d, v in contrib[contrib > 0].items()]
        dd = M.drawdown_series(raw["index"])
        return {"id": p["id"], "kind": kind, "name_ko": p.get("name_ko", p["id"]), "title_ko": p.get("title_ko"), "portfolio_view": p.get("portfolio_view"),
                "target_weights": p["weights"], "headline": headline, "metrics": m, "money": res["money"],
                "series": {"index": [_f(x, 4) for x in raw["index"]], "value_usd": [_f(x, 2) for x in raw["values"]], "drawdown": [_f(x, 5) for x in dd]},
                "monthly_returns": res["monthly_returns"], "yearly_returns": res["yearly_returns"], "checkpoints": cps,
                "contribution_ledger": ledger, "events": build_events(raw, rb, cd, cps),
                "ticker_contribution": res["ticker_contribution"], "ticker_total_return": res["ticker_total_return"], "view_diagnostics": res["view_diagnostics"]}

    bench_block = block({"id": bench_raw["id"], "name_ko": f"{bench} 매수보유 (동일 적립)", "weights": {bench: 1.0}}, bench_raw, "benchmark", None)
    blocks = []
    for p in targets["portfolios"]:
        blocks.append(block(p, runs[p["id"]], "black_litterman", baseline_idx)); print(f"         {p['id']:<14} done", flush=True)
    for p in targets["templates"]:
        blocks.append(block(p, runs[p["id"]], "template", None if p["id"] == baseline_id else baseline_idx)); print(f"         {p['id']:<14} done", flush=True)

    ranking = sorted([{"id": b["id"], "kind": b["kind"], "sharpe": b["headline"]["sharpe"], "cagr": b["headline"]["cagr"], "max_drawdown": b["headline"]["max_drawdown"],
                       "final_value_usd": b["headline"]["final_value_usd"], "excess_cagr": b["headline"]["excess_cagr"]} for b in blocks],
                     key=lambda r: -(r["sharpe"] if r["sharpe"] is not None else -9))
    meta = pq.read_metadata(RAW / "prices.parquet")
    repro = {"engine_config": {k: getattr(BC, k) for k in dir(BC) if k.isupper()}, "bt_version": btlib.__version__,
             "prices_file": {"rows": meta.num_rows, "last_date": str(panel.index[-1].date())},
             "targets_sha256": hashlib.sha256(open(a.targets, "rb").read()).hexdigest()[:16]}
    out = BacktestResults(request_id=targets["request_id"], period={**spec["period"], "trading_days": int(len(panel))},
                          engine={"library": f"bt {btlib.__version__}", "prices": "adj_close (dividends reinvested)", "commission_bps": BC.COMMISSION_BPS,
                                  "fractional_shares": not BC.INTEGER_POSITIONS, "risk_free_rate": rf,
                                  "contributions": f"monthly flow invested at target weights, first trading day on/after day {cap['contribution_day']}",
                                  "n_contributions": len(cd), "contribution_usd": amount, "rebalance_rule": spec["rebalance_rule"], "checkpoint_freq": BC.CHECKPOINT_FREQ},
                          series_dates=[str(d.date()) for d in panel.index], benchmark=bench_block, portfolios=blocks, ranking=ranking,
                          reproducibility=repro, warnings=warnings)
    path = dump_json(out.model_dump(mode="json"), a.out)
    if BC.SAVE_DAILY_PANEL:
        rows = []
        for raw in [bench_raw, *runs.values()]:
            df = pd.DataFrame({"portfolio_id": raw["id"], "date": raw["index"].index, "index": raw["index"].values, "value_usd": raw["values"].values,
                               "drawdown": M.drawdown_series(raw["index"]).values})
            rows.append(pd.concat([df.reset_index(drop=True), raw["security_weights"].reset_index(drop=True).add_prefix("w_")], axis=1))
        pd.concat(rows, ignore_index=True).to_parquet(OUTPUT / "11_daily_panel.parquet", index=False)
    print(f"[stage11] ok -> {path} ({path.stat().st_size / 1e6:.2f} MB)")
    print(f"         {'id':<20}{'cagr':>8}{'vol':>8}{'sharpe':>8}{'mdd':>8}{'excess':>8}{'final$':>10}{'irr':>8}{'hit':>6}")
    for b in [bench_block, *blocks]:
        h, mo = b["headline"], b["money"]
        print(f"         {b['id']:<20}{h['cagr']:>8.3f}{b['metrics']['risk']['ann_vol']:>8.3f}{h['sharpe'] or 0:>8.2f}{h['max_drawdown']:>8.3f}"
              f"{(h['excess_cagr'] or 0):>8.3f}{mo['final_value_usd']:>10,.0f}{mo['irr_annual'] or 0:>8.3f}{'' if h['view_hit_ratio'] is None else h['view_hit_ratio']:>6}")


if __name__ == "__main__":
    main()
