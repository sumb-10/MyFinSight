"""M5-01 백테스트 실행 (stage11 포팅). 타겟 포트폴리오(BL + 템플릿 + walk-forward + 낙폭 맞춤안)와 비교지수를 같은 기간·자본·적립으로 돌린다.

낙폭 맞춤안(dd_match_*)은 여기서 정식 후보로 만든다 (라운드 5, `build_matched_blocks`). 현금 혼합안(검증 단계 대안)은 없어졌다.
"""

from __future__ import annotations

import hashlib
import json
from typing import Any

import numpy as np
import pandas as pd

import bt as btlib

from backend.analysis.m2_data import descriptor as D
from backend.analysis.m2_data.market_data import MarketData
from backend.analysis.m2_data.quality import report_summary
from backend.analysis.m5_backtest_report import backtest_metrics as M
from backend.analysis.m5_backtest_report import matched as MX
from backend.analysis.m5_backtest_report.backtest_engine import (
    contribution_dates,
    extract_raw,
    rebalance_dates,
    run_dynamic_portfolio,
    run_static_portfolio,
    xirr,
)
from backend.analysis.schemas.backtest import BacktestResults
from backend.analysis.settings import AnalysisSettings
from backend.pipeline.descriptor import Descriptor


def _f(x, n=6):
    return M._r(x, n)


def slice_raw(raw, d):
    return {"id": raw["id"], "index": raw["index"][:d], "values": raw["values"][:d], "flows": raw["flows"][:d],
            "security_weights": raw["security_weights"][:d], "positions": raw["positions"][:d], "turnover": raw["turnover"][:d],
            "transactions": raw["transactions"][raw["transactions"]["Date"] <= d]}  # fmt: skip


def flat_to_date(res, n_days, td):
    m, mo = res["metrics"], res["money"]
    return {"total_return": m["return"]["total_return"], "cagr": m["return"]["cagr"], "ann_vol": m["risk"]["ann_vol"],
            "sharpe": m["risk_adjusted"]["sharpe"], "sortino": m["risk_adjusted"]["sortino"], "max_drawdown": m["risk"]["max_drawdown"],
            "calmar": m["risk_adjusted"]["calmar"], "excess_cagr": m["vs_benchmark"]["excess_cagr"], "beta": m["vs_benchmark"]["beta"],
            "information_ratio": m["vs_benchmark"]["information_ratio"], "irr_annual": mo["irr_annual"],
            "positive_months_ratio": m["return"]["positive_months_ratio"],
            "active_return_vs_baseline": (m["vs_baseline"] or {}).get("active_return"), "reliable": n_days >= td}  # fmt: skip


def build_checkpoints(raw, bench_raw, panel, targets, sectors, cp_dates, rb_set, last, cfg, views, implied, as_of, end, settings, targets_by_date=None):
    bs = settings.backtest
    sw, pos, tx, tv = raw["security_weights"], raw["positions"], raw["transactions"], raw["turnover"]
    idx, values, flows = raw["index"], raw["values"], raw["flows"]
    cols = [c for c in targets if c in sw.columns]
    contrib = flows.copy()
    contrib.iloc[0] = 0.0
    cum_contrib = contrib.cumsum()
    r_assets = panel[cols].pct_change().reindex(sw.index).fillna(0.0)
    tbd = {pd.Timestamp(k): v for k, v in (targets_by_date or {}).items()}
    out, prev = [], None
    for seq, d in enumerate(cp_dates):
        if tbd:
            past = [k for k in sorted(tbd) if k <= d]
            tgt = pd.Series({c: tbd[past[-1]].get(c, 0.0) for c in cols}) if past else pd.Series(targets)[cols]
        else:
            tgt = pd.Series(targets)[cols]
        kind = "rebalance" if d in rb_set else ("closing" if d == last else "monthly")
        pos_d = sw.index.get_loc(d)
        before = sw.iloc[pos_d - 1][cols] if pos_d > 0 else None
        after = sw.loc[d][cols]
        if prev is not None:
            seg = sw.loc[prev:d]
            seg_r = r_assets.loc[seg.index]
            per_contrib = (seg[cols].shift(1) * seg_r[cols]).loc[seg.index > prev].sum()
            per_ret = panel.loc[d, cols] / panel.loc[prev, cols] - 1
        else:
            per_contrib = pd.Series(0.0, index=cols)
            per_ret = pd.Series(0.0, index=cols)
        hold = [{"ticker": c, "shares_after": _f(pos.loc[d, c], 4), "price": _f(panel.loc[d, c], 4), "value_usd": _f(pos.loc[d, c] * panel.loc[d, c], 2),
                 "weight_before": _f(before[c]) if before is not None else None, "weight_after": _f(after[c]),
                 "period_return": _f(per_ret[c]), "period_contribution": _f(per_contrib[c])} for c in cols]  # fmt: skip
        txd = tx[tx["Date"] == d]
        trades = [{"ticker": r.Security, "side": "buy" if r.quantity > 0 else "sell", "shares": _f(abs(r.quantity), 4),
                   "price": _f(r.price, 4), "value_usd": _f(abs(r.quantity) * r.price, 2)} for r in txd.itertuples()]  # fmt: skip
        comm = float(sum(t["value_usd"] for t in trades) * bs.commission_bps / 1e4)
        drift = None
        if prev is not None:
            between = sw.loc[prev:d][cols].iloc[1:-1] if pos_d - sw.index.get_loc(prev) > 1 else sw.loc[[d]][cols] * 0
            sec_between = pd.DataFrame({s: between[[c for c in cols if sectors[c] == s]].sum(axis=1) for s in {sectors[c] for c in cols}})
            sec_tgt = pd.Series({s: tgt[[c for c in cols if sectors[c] == s]].sum() for s in sec_between.columns})
            drift = {"max_weight_drift": _f((between - tgt).abs().max().max()) if len(between) else 0.0,
                     "max_sector_drift": _f((sec_between - sec_tgt).abs().max().max()) if len(between) else 0.0,
                     "breaches": sorted({f"stock_cap:{c}" for c in cols if (between[c] > cfg["max_stock"] * (1 + bs.drift_tolerance)).any()}
                                        | {f"sector_cap:{s}" for s in sec_between.columns if (sec_between[s] > cfg["max_sector"] * (1 + bs.drift_tolerance)).any()})}  # fmt: skip
        money = {"value_usd": _f(values[d], 2), "cumulative_contributions_usd": _f(cum_contrib[d], 2), "net_invested_usd": _f(flows[:d].sum(), 2),
                 "profit_usd": _f(values[d] - flows[:d].sum(), 2), "benchmark_value_usd": _f(bench_raw["values"].get(d, np.nan), 2)}  # fmt: skip
        since_last = None
        if prev is not None:
            seg_idx = idx.loc[prev:d]
            seg_b = bench_raw["index"].loc[prev:d]
            rr = M.daily_returns(seg_idx)
            best, worst = per_ret.idxmax(), per_ret.idxmin()
            since_last = {"return": _f(seg_idx.iloc[-1] / seg_idx.iloc[0] - 1), "benchmark_return": _f(seg_b.iloc[-1] / seg_b.iloc[0] - 1),
                          "excess": _f((seg_idx.iloc[-1] / seg_idx.iloc[0]) - (seg_b.iloc[-1] / seg_b.iloc[0])),
                          "max_drawdown": _f(M.drawdown_series(seg_idx).min()), "ann_vol": _f(M.ann_vol(rr, bs.trading_days)) if len(rr) > 1 else None,
                          "best": {"ticker": best, "return": _f(per_ret[best])}, "worst": {"ticker": worst, "return": _f(per_ret[worst])}}  # fmt: skip
        n_days = pos_d
        to_date, vd = None, []
        if n_days >= 5:
            # 라운드 4 S8: 전체 지표(compute_all)를 다시 계산하지 않고 체크포인트 요약 13개 값만 (같은 식, 같은 값)
            to_date = M.compute_to_date(idx[:d], values[:d], flows[:d], bench_raw["index"][:d], cfg["rf"], xirr, bs,
                                        baseline_idx=cfg["baseline_idx"][:d] if cfg["baseline_idx"] is not None else None)  # fmt: skip
            to_date["reliable"] = n_days >= bs.trading_days
            if views and bs.checkpoint_view_diagnostics:
                vd = M.view_diagnostics(views, panel[:d], as_of, d, implied or {}, bs.view_horizon_days)
        out.append({"seq": seq, "date": str(d.date()), "kind": kind, "n_trading_days_to_date": int(n_days),
                    "weights": {"target": {c: _f(tgt[c]) for c in cols}, "before": {c: _f(before[c]) for c in cols} if before is not None else None,
                                "after": {c: _f(after[c]) for c in cols}, "cash_before": _f(1 - before.sum()) if before is not None else None,
                                "cash_after": _f(1 - after.sum())},
                    "drift": drift, "holdings": hold, "trades": trades, "turnover": _f(tv.get(d, np.nan)), "commission_usd": _f(comm, 2),
                    "money": money, "since_last": since_last, "to_date": to_date, "view_diagnostics_to_date": vd})  # fmt: skip
        prev = d
    return out


def build_events(raw, rb_dates, contrib_dates, checkpoints, settings):
    idx = raw["index"]
    dd = M.drawdown_series(idx)
    ev = []
    crossed: set = set()
    for d, v in dd.items():
        if v == 0:
            if crossed:
                ev.append({"date": str(d.date()), "type": "new_high", "message_ko": "낙폭을 회복해 신고가 갱신"})
                crossed = set()
            continue
        for lvl in settings.backtest.event_drawdown_levels:
            if v <= lvl and lvl not in crossed:
                crossed.add(lvl)
                ev.append({"date": str(d.date()), "type": f"drawdown_{int(abs(lvl) * 100)}", "message_ko": f"고점 대비 {lvl:.0%} 하락"})
    ev += [{"date": str(d.date()), "type": "rebalance", "message_ko": "리밸런싱"} for d in rb_dates]
    ev += [{"date": str(d.date()), "type": "contribution", "message_ko": "월 적립"} for d in contrib_dates]
    for cp in checkpoints:
        for b in (cp.get("drift") or {}).get("breaches", []):
            ev.append({"date": cp["date"], "type": "cap_breach", "message_ko": f"리밸런싱 전 제약 이탈: {b}"})
    return sorted(ev, key=lambda e: e["date"])


# ───────────────────────── reusable pieces ─────────────────────────
def prepare(md: MarketData, spec: dict[str, Any], req: dict[str, Any], intent: dict[str, Any], mm: dict[str, Any], desc: Descriptor, settings: AnalysisSettings,
            baseline_id: str) -> dict[str, Any]:  # fmt: skip
    """백테스트 실행에 필요한 것 전부: 달력, 품질 통과 패널(USD), 리밸런싱·적립일, 섹터."""
    as_of, end = pd.Timestamp(spec["period"]["as_of"]), pd.Timestamp(spec["period"]["end"])
    bench = spec["benchmark"]
    tickers = list(spec["selection"]["tickers"])
    benches = [bench] + [b for b in spec.get("extra_benchmarks", []) if b != bench and b in md.assets]
    view = md.view(end.date())
    markets = sorted({md.market_of(t) for t in tickers} | {md.market_of(b) for b in benches})
    cal = view.trading_days(as_of.date(), end.date(), markets=markets)
    panel, quality = view.panel(tickers, as_of.date(), end.date(), required=benches, benchmarks=benches)
    excluded = [t for t in tickers if t not in panel.columns]
    usable = [t for t in tickers if t in panel.columns]
    panel = panel.reindex(cal).ffill()
    rb = rebalance_dates(spec["rebalance_rule"], cal, as_of, settings.backtest)
    cap = spec["capital"]
    cd = contribution_dates(cal, as_of, end, cap["contribution_day"]) if cap["include_contributions"] and cap["monthly_contribution_usd"] > 0 else []
    sectors = {t: D.gics_model(desc.by_ticker(t) or {"gics": {}}).sector.name or "Unknown" for t in usable}
    for b in benches:
        sectors[b] = "Benchmark"
    last = panel.index[-1]
    cp_dates = sorted(set(rb) | {last} | (set(panel.resample("ME").last().index.intersection(panel.index)) if settings.backtest.checkpoint_freq == "monthly" else set()))
    return {"spec": spec, "req": req, "intent": intent, "mm": mm, "as_of": as_of, "end": end, "bench": bench, "benches": benches, "tickers": usable,
            "excluded": excluded, "quality": report_summary(quality), "cal": cal, "panel": panel, "rb": rb, "rb_set": set(rb), "cd": cd,
            "amount": cap["monthly_contribution_usd"] if cd else 0.0, "cap": cap, "sectors": sectors, "cons": req["constraints"],
            "rf": settings.backtest.risk_free_rate, "target_return": intent["validation_criteria"]["target_annual_return"], "last": last,
            "cp_dates": cp_dates, "baseline_id": baseline_id, "settings": settings}  # fmt: skip


def _usable_weights(ctx, weights: dict[str, float]) -> dict[str, float]:
    """패널에 없는(품질 제외) 종목을 빼고 다시 1 로 맞춘다."""
    w = {t: x for t, x in weights.items() if t in ctx["panel"].columns}
    s = sum(w.values())
    tot = sum(weights.values())
    return {t: x / s * tot for t, x in w.items()} if s > 0 and abs(s - tot) > 1e-9 else w


def run_raw(ctx, pid, weights):
    w = _usable_weights(ctx, weights)
    b, res = run_static_portfolio(pid, w, ctx["panel"], ctx["cap"]["initial_amount_usd"], ctx["rb"], ctx["cd"], ctx["amount"], ctx["settings"].backtest)
    return extract_raw(b, res, ctx["as_of"])


def run_raw_dynamic(ctx, pid, weights_by_date):
    wbd = {d: _usable_weights(ctx, w) for d, w in weights_by_date.items()}
    b, res = run_dynamic_portfolio(pid, wbd, ctx["panel"], ctx["cap"]["initial_amount_usd"], ctx["cd"], ctx["amount"], ctx["settings"].backtest)
    return extract_raw(b, res, ctx["as_of"])


def walkforward_view_diagnostics(views_by_date, panel, end, implied_by_date, implied_start, horizon_days):
    """walk-forward 뷰 진단: 리밸런싱일 d 의 뷰는 d 부터, 그날의 시장모형 implied 로 판정한다 (예전에는 모두 시작일 기준 → 잘못된 적중률)."""
    out = []
    for d in sorted(views_by_date):
        vs = views_by_date[d]
        if not vs:
            continue
        implied = (implied_by_date or {}).get(d) or implied_start or {}
        for x in M.view_diagnostics(vs, panel, pd.Timestamp(d), end, implied, horizon_days):
            out.append({"as_of": d, **x})
    return out


def evaluate(ctx, p, raw, kind, bench_raw, baseline_idx, *, implied_by_date=None):
    s = ctx["settings"]
    views = p.get("views_applied") if kind == "black_litterman" else None
    weights = _usable_weights(ctx, p["weights"])
    cfg = {"rb": ctx["rb"], "rf": ctx["rf"], "target_return": ctx["target_return"], "max_stock": ctx["cons"]["max_weight_per_stock"],
           "max_sector": ctx["cons"]["max_weight_per_sector"], "baseline_idx": baseline_idx}  # fmt: skip
    implied = ctx["mm"]["implied_returns"]
    wf_vd = None
    if views and p.get("views_by_date"):  # walk-forward: 날짜별 진단으로 바꾸고 시작일 기준 진단은 끈다
        wf_vd = walkforward_view_diagnostics(p["views_by_date"], ctx["panel"], ctx["end"], implied_by_date, implied, s.backtest.view_horizon_days)
        views = None
    res = M.compute_all(raw, bench_raw["index"], ctx["panel"], weights, ctx["sectors"], ctx["rb"], ctx["rf"], ctx["target_return"],
                        cfg["max_stock"], cfg["max_sector"], xirr, s.backtest, baseline_idx=baseline_idx, views=views, implied=implied,
                        as_of=ctx["as_of"], end=ctx["end"])  # fmt: skip
    if wf_vd is not None:
        res["view_diagnostics"] = wf_vd
    nxt: list[dict[str, Any]] = []
    if kind == "black_litterman":  # 라운드 5: 뷰를 세운 날부터 다음 리밸런싱일까지의 적중 (뷰가 실제로 비중을 바꾼 기간)
        vbd = p.get("views_by_date") or ({str(ctx["as_of"].date()): p.get("views_applied") or []} if p.get("views_applied") else {})
        nxt = M.view_diagnostics_next_window(vbd, ctx["panel"], ctx["rb"], ctx["end"], implied_by_date, implied)
    cps = build_checkpoints(raw, bench_raw, ctx["panel"], weights, ctx["sectors"], ctx["cp_dates"], ctx["rb_set"], ctx["last"], cfg, views, implied,
                            ctx["as_of"], ctx["end"], s, targets_by_date=p.get("weights_by_date"))  # fmt: skip
    m = res["metrics"]
    hits = [v["hit"] for v in res["view_diagnostics"]]
    headline = {"final_value_usd": res["money"]["final_value_usd"], "cagr": m["return"]["cagr"], "period_return": m["return"]["total_return"],
                "excess_cagr": m["vs_benchmark"]["excess_cagr"], "max_drawdown": m["risk"]["max_drawdown"], "sharpe": m["risk_adjusted"]["sharpe"],
                "view_hit_ratio": _f(np.mean(hits)) if hits else None, "view_hit_ratio_next_rb": _f(np.mean([v["hit"] for v in nxt])) if nxt else None,
                "annualized_reliable": len(raw["index"]) - 1 >= s.backtest.min_annualize_days}  # fmt: skip
    contrib = raw["flows"].copy()
    contrib.iloc[0] = 0.0
    ledger = [{"date": str(d.date()), "amount_usd": _f(v, 2), "value_before_usd": _f(raw["values"].shift(1).get(d, np.nan), 2)} for d, v in contrib[contrib > 0].items()]
    dd = M.drawdown_series(raw["index"])
    return {"id": p["id"], "kind": kind, "mode": "walkforward" if p.get("weights_by_date") else "static", "name_ko": p.get("name_ko", p["id"]),
            "title_ko": p.get("title_ko"), "portfolio_view": p.get("portfolio_view"), "target_weights": weights, "weights_by_date": p.get("weights_by_date"),
            "views_by_date": p.get("views_by_date"), "fallback_dates": p.get("fallback_dates"), "headline": headline, "metrics": m, "money": res["money"],
            "series": {"index": [_f(x, 4) for x in raw["index"]], "value_usd": [_f(x, 2) for x in raw["values"]], "drawdown": [_f(x, 5) for x in dd]},
            "monthly_returns": res["monthly_returns"], "yearly_returns": res["yearly_returns"], "checkpoints": cps,
            "contribution_ledger": ledger, "events": build_events(raw, ctx["rb"], ctx["cd"], cps, s),
            "ticker_contribution": res["ticker_contribution"], "ticker_total_return": res["ticker_total_return"], "view_diagnostics": res["view_diagnostics"],
            "view_diagnostics_next_rb": nxt}  # fmt: skip


def build_matched_blocks(ctx, targets, wf, runs, blocks, primary_raw, baseline_idx, intent, implied_by_date):
    """낙폭 맞춤안 (라운드 5): 기준 비중 템플릿(정적) 과 wf_bl_news(walk-forward) 를 기준으로, 실제 일정에서 MDD ≤ 목표가 되는 현금 비율을 찾아 정식 후보로 넣는다.
    목표 = intent.risk_params.effective_max_drawdown (허용 낙폭 × 성향 보정). 기준이 이미 목표 안이면 만들지 않는다."""
    rp = intent.get("risk_params") or {}
    target = float(rp.get("effective_max_drawdown") or ctx["req"]["risk"]["max_drawdown_tolerance"])
    out, new_runs, warns = [], {}, []
    bases: list[tuple[str, dict[str, Any], str]] = []
    base_id = ctx["baseline_id"]
    tpl = next((t for t in targets["templates"] + targets["portfolios"] if t["id"] == base_id), None)
    if tpl is not None:
        bases.append(("static", tpl, tpl.get("name_ko") or MX_NAMES.get(base_id, base_id)))
    if wf:
        bl = next((x for x in wf["portfolios"] if x["id"] == "wf_bl_news"), None)
        if bl is not None and bl.get("weights_by_date"):
            bases.append(("dynamic", bl, MX.BASE_LABEL_BL))
    for mode, base, label in bases:
        bid = base["id"]
        braw = runs.get(bid)
        if braw is None:
            continue
        base_mdd = float(M.drawdown_series(braw["index"]).min())
        if base_mdd >= -target:
            warns.append(f"matched variant skipped for {bid}: max drawdown {abs(base_mdd):.1%} already within target {target:.1%}")
            continue
        pid = f"dd_match_{bid}"
        if mode == "static":
            def run_fn(c, _w=base["weights"], _pid=pid):
                return run_raw(ctx, _pid, MX.scale_weights(_w, c))
        else:
            def run_fn(c, _wbd=base["weights_by_date"], _pid=pid):
                return run_raw_dynamic(ctx, _pid, {d: MX.scale_weights(w, c) for d, w in _wbd.items()})
        seed = MX.seed_cash_ratio(braw["index"], target)
        c, raw, n = MX.solve_cash_ratio(run_fn, seed, target)
        if c is None:
            warns.append(f"matched variant skipped for {bid}: no cash ratio up to {MX.MAX_CASH:.0%} brings max drawdown within {target:.1%} ({n} runs)")
            continue
        weights = MX.scale_weights(base["weights"], c)
        inv = float(sum(weights.values()))
        p = {"id": pid, "name_ko": MX.matched_name(label, inv), "weights": weights}
        if mode == "dynamic":
            p["weights_by_date"] = {d: MX.scale_weights(w, c) for d, w in base["weights_by_date"].items()}
            p["fallback_dates"] = base.get("fallback_dates")
        block = evaluate(ctx, p, raw, "matched", primary_raw, baseline_idx, implied_by_date=implied_by_date)
        block.update({"base_id": bid, "cash_ratio": c, "cash_ratio_total": round(1 - inv, 6), "match_target": target, "solver_runs": n})
        out.append(block)
        new_runs[pid] = raw
    return out, new_runs, warns


MX_NAMES = {"equal_weight": "동일비중", "market_cap": "시가총액비중", "inverse_volatility": "역변동성비중", "min_variance": "최소분산"}


def run_backtest(md: MarketData, targets: dict[str, Any], req: dict[str, Any], intent: dict[str, Any], mm: dict[str, Any], desc: Descriptor,
                 settings: AnalysisSettings, walkforward: dict[str, Any] | None = None) -> tuple[dict[str, Any], dict[str, Any], pd.DataFrame]:  # fmt: skip
    """(BacktestResults dict, ctx, daily panel)."""
    spec = targets["backtest_spec"]
    ctx = prepare(md, spec, req, intent, mm, desc, settings, targets["baseline"]["id"])
    warnings: list[str] = []
    if ctx["excluded"]:
        warnings.append(f"excluded by data quality (weights renormalized): {ctx['excluded']}")
    bench_raws = {b: run_raw(ctx, f"benchmark_{b}", {b: 1.0}) for b in ctx["benches"]}
    primary_raw = bench_raws[ctx["bench"]]
    runs = {p["id"]: run_raw(ctx, p["id"], p["weights"]) for p in targets["portfolios"] + targets["templates"]}
    baseline_idx = runs[ctx["baseline_id"]]["index"]
    wf = walkforward if walkforward and walkforward.get("request_id") == targets["request_id"] else None
    if wf:
        for p in wf["portfolios"]:
            p["weights"] = p["weights_by_date"][max(p["weights_by_date"])]
            runs[p["id"]] = run_raw_dynamic(ctx, p["id"], p["weights_by_date"])
    bench_blocks = [evaluate(ctx, {"id": r["id"], "name_ko": f"{b} 매수보유 (동일 적립)", "weights": {b: 1.0}}, r, "benchmark", primary_raw, None)
                    for b, r in bench_raws.items()]  # fmt: skip
    blocks = []
    for p in targets["portfolios"]:
        blocks.append(evaluate(ctx, p, runs[p["id"]], "black_litterman", primary_raw, baseline_idx))
    for p in targets["templates"]:
        blocks.append(evaluate(ctx, p, runs[p["id"]], "template", primary_raw, None if p["id"] == ctx["baseline_id"] else baseline_idx))
    implied_by_date = {d: (m.get("implied_returns") or {}) for d, m in ((wf or {}).get("market_models_by_date") or {}).items()}
    for p in wf["portfolios"] if wf else []:
        if p["kind"] == "black_litterman":
            p["views_applied"] = [v for d in sorted(p["views_by_date"]) for v in p["views_by_date"][d]]
        blocks.append(evaluate(ctx, p, runs[p["id"]], p["kind"], primary_raw, baseline_idx, implied_by_date=implied_by_date))
    matched_blocks, matched_runs, matched_warns = build_matched_blocks(ctx, targets, wf, runs, blocks, primary_raw, baseline_idx, intent, implied_by_date)
    blocks += matched_blocks
    runs.update(matched_runs)
    warnings += matched_warns
    ranking = sorted([{"id": b["id"], "kind": b["kind"], "sharpe": b["headline"]["sharpe"], "cagr": b["headline"]["cagr"], "max_drawdown": b["headline"]["max_drawdown"],
                       "final_value_usd": b["headline"]["final_value_usd"], "excess_cagr": b["headline"]["excess_cagr"]} for b in blocks],
                     key=lambda r: -(r["sharpe"] if r["sharpe"] is not None else -9))  # fmt: skip
    bs = settings.backtest
    n_days = int(len(ctx["panel"]))
    repro = {"engine_config": {k: v for k, v in settings.snapshot()["backtest"].items()}, "bt_version": btlib.__version__,
             "panel": {"rows": n_days, "last_date": str(ctx["panel"].index[-1].date()), "tickers": list(ctx["panel"].columns)},
             "targets_sha256": hashlib.sha256(json.dumps(targets, sort_keys=True, default=str).encode()).hexdigest()[:16]}  # fmt: skip
    out = BacktestResults(
        request_id=targets["request_id"],
        period={**spec["period"], "trading_days": n_days, "window_days": n_days - 1, "annualized_reliable": n_days - 1 >= bs.min_annualize_days},
        mode="static_weights" + (" + walkforward" if wf else ""),
        engine={"library": f"bt {btlib.__version__}", "prices": "adj_close USD (dividends reinvested; KRW converted at daily FX)",
                "commission_bps": bs.commission_bps, "fractional_shares": not bs.integer_positions, "risk_free_rate": ctx["rf"],
                "contributions": f"monthly flow invested at target weights, first trading day on/after day {ctx['cap']['contribution_day']}",
                "n_contributions": len(ctx["cd"]), "contribution_usd": ctx["amount"], "rebalance_rule": spec["rebalance_rule"],
                "checkpoint_freq": bs.checkpoint_freq, "capital_fx": {k: ctx["cap"].get(k) for k in ["currency", "fx_rate", "fx_date", "fx_source"]},
                "benchmarks": ctx["benches"], "execution_rule": spec.get("execution_rule"), "calendar": "union of market trading days (holidays carry the previous close)"},
        series_dates=[str(d.date()) for d in ctx["panel"].index], benchmark=bench_blocks[0], benchmarks=bench_blocks, portfolios=blocks,
        ranking=ranking, reproducibility=repro, data_quality=ctx["quality"], warnings=warnings,
    )  # fmt: skip
    rows = []
    for raw in [*bench_raws.values(), *runs.values()]:
        df = pd.DataFrame({"portfolio_id": raw["id"], "date": raw["index"].index, "index": raw["index"].values, "value_usd": raw["values"].values,
                           "drawdown": M.drawdown_series(raw["index"]).values})  # fmt: skip
        rows.append(pd.concat([df.reset_index(drop=True), raw["security_weights"].reset_index(drop=True).add_prefix("w_")], axis=1))
    daily = pd.concat(rows, ignore_index=True)
    return out.model_dump(mode="json"), ctx, daily
