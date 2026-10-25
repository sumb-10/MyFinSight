"""M4-02 시장모형·템플릿 비중. 구성일 d 의 추정은 d 이전 자료만 쓴다 (view.adj_close 기본 strict_before)."""

from __future__ import annotations

import datetime as dt
from typing import Any

import numpy as np

from backend.analysis.m2_data import descriptor as D
from backend.analysis.m2_data.market_data import MarketDataView
from backend.analysis.m4_portfolio import math as P
from backend.analysis.schemas.portfolio import BaselinePortfolios, MarketModel
from backend.analysis.settings import AnalysisSettings
from backend.pipeline.descriptor import Descriptor


def drawdown_delta_multiplier(dd_tol: float, ps) -> float:
    """허용 낙폭 → δ 배수: clip(ref_tol / 허용 낙폭, 범위). 허용 20% 면 1.0, 10% 면 1.5(상한), 40% 면 0.75(하한)."""
    lo, hi = ps.delta_dd_mult_range
    if not dd_tol or dd_tol <= 0:
        return 1.0
    return round(min(hi, max(lo, ps.delta_dd_ref_tol / float(dd_tol))), 4)


def sector_lists(desc: Descriptor, tickers: list[str]) -> tuple[list[str], list[str]]:
    codes, names = [], []
    for t in tickers:
        g = D.gics_model(desc.by_ticker(t) or {"gics": {}})
        codes.append(g.sector.code or "unknown")
        names.append(g.sector.name or "Unknown")
    return codes, names


def build_market_model(
    view: MarketDataView,
    tickers: list[str],
    req: dict[str, Any],
    desc: Descriptor,
    settings: AnalysisSettings,
    *,
    request_id: str | None = None,
    benchmark: str | None = None,
) -> tuple[dict[str, Any], dict[str, Any]]:
    """(MarketModel dict, BaselinePortfolios dict) at view.as_of. 템플릿 4종 비중 포함."""
    ps = settings.portfolio
    cons = req["constraints"]
    as_of = view.as_of
    notes: list[str] = []
    warnings: list[str] = []
    start = as_of - dt.timedelta(days=int(ps.lookback_days * 1.6) + 30)
    px = view.adj_close(tickers, start)  # strict_before: < as_of
    mm = P.estimate_market_model(px, tickers, lookback_days=ps.lookback_days, min_history_days=ps.min_history_days_for_model, shrinkage=ps.shrinkage)
    tk = mm["tickers"]
    if mm["dropped"]:
        warnings.append(f"dropped from model (insufficient returns in window): {mm['dropped']}")
    sec_code, sec_name = sector_lists(desc, tk)
    mcap = view.market_cap_usd(tk)
    missing_mc = [t for t in tk if t not in mcap]
    if missing_mc:
        notes.append(f"market cap missing for {missing_mc}: treated as 0 in market_cap weights")
    capw = P.cap_weights(tk, mcap)
    notes.append("cap_weights use valuation_daily market_cap (shares × close) as of the day before construction, USD converted")
    tol = req["risk"]["risk_tolerance"]
    dd_tol = float(req["risk"].get("max_drawdown_tolerance") or ps.delta_dd_ref_tol)
    dd_mult = drawdown_delta_multiplier(dd_tol, ps)  # 라운드 5: 허용 낙폭이 작을수록 위험회피 ↑ (낙폭을 합격 기준 대신 구성 입력으로)
    bench = benchmark or req["risk"].get("benchmark") or settings.market.primary_benchmark_default
    if ps.risk_aversion_mode == "market_implied":
        bpx = view.adj_close([bench], start)[bench]
        d_mkt, d_win = P.market_implied_delta(bpx, lookback_days=ps.lookback_days, rf=settings.backtest.risk_free_rate)
        mult = ps.risk_aversion_mult[tol]
        delta = round(max(ps.delta_floor, min(d_mkt * mult * dd_mult, 8.0)), 4)
        delta_meta = {"delta_source": "market_implied", "delta_market": round(d_mkt, 4), "delta_multiplier": mult, "delta_window": d_win,
                      "delta_dd_multiplier": dd_mult, "delta_tolerance": dd_tol}  # fmt: skip
        notes.append(f"delta = market-implied {d_mkt:.2f} ({bench}, {d_win['start']}~{d_win['end']}) × {mult} ({tol}) × {dd_mult} (drawdown tolerance {dd_tol:.0%}) = {delta} (floor {ps.delta_floor}, cap 8)")
    else:
        delta = round(max(ps.delta_floor, min(ps.risk_aversion[tol] * dd_mult, 8.0)), 4)
        delta_meta = {"delta_source": "fixed", "delta_dd_multiplier": dd_mult, "delta_tolerance": dd_tol}
    total = 1.0 - cons.get("min_cash_ratio", 0)
    max_stock, max_sector = cons["max_weight_per_stock"], cons["max_weight_per_sector"]
    capacity = P.weight_capacity(sec_code, max_stock, max_sector)
    if capacity < total - 1e-9:
        warnings.append(f"caps allow at most {capacity:.0%} invested (stock {max_stock:.0%}, sector {max_sector:.0%}, {len(tk)} names): "
                        f"{total - capacity:.0%} kept as cash; relax the caps or widen the theme to invest fully")  # fmt: skip
        total = round(capacity - 1e-6, 6)
    baseline_id = req["strategy_preference"]["baseline_weighting"]
    sec_names = dict(zip(sec_code, sec_name, strict=True))

    def label(c: str) -> str:
        if ":" not in c:
            return c
        kind, val = c.split(":", 1)
        if kind in ("stock_cap", "min_weight"):
            return f"{kind}:{tk[int(val)]}"
        if kind == "sector_cap":
            return f"sector_cap:{sec_names.get(val, val)}"
        return c

    weights, applied_by = {}, {}
    for tpl in ps.templates:
        w, applied = P.template_weights(tpl, mm["cov"], mm["ann_vol"], capw, max_stock, max_sector, sec_code, total,
                                        min_weight=ps.min_weight, max_iter=ps.max_iter)  # fmt: skip
        weights[tpl], applied_by[tpl] = w, applied
    pi = P.implied_returns(mm["cov"], weights[baseline_id], delta)
    ports = []
    for tpl in ps.templates:
        w = weights[tpl]
        name_ko, rule_ko = ps.template_names_ko[tpl]
        ports.append({
            "id": tpl, "kind": "template", "name_ko": name_ko, "rule_ko": rule_ko,
            "weights": {t: round(float(x), 6) for t, x in zip(tk, w, strict=True)}, "cash_weight": round(1 - float(w.sum()), 6),
            "ex_ante": P.ex_ante_stats(w, pi, mm["cov"]), "sector_weights": P.sector_weights(w, sec_name),
            "constraints_applied": [label(c) for c in applied_by[tpl]],
        })  # fmt: skip
    rid = request_id or req["request_id"]
    model = MarketModel(
        request_id=rid, as_of=as_of, lookback={**mm["window"], "requested_days": ps.lookback_days, "information_cutoff": "t-1"},
        tickers=tk, ann_vol={t: round(float(v), 6) for t, v in zip(tk, mm["ann_vol"], strict=True)},
        corr=np.round(mm["corr"], 6).tolist(), cov=np.round(mm["cov"], 8).tolist(),
        cap_weights={t: round(float(x), 6) for t, x in zip(tk, capw, strict=True)}, delta=delta, tau=ps.tau, **delta_meta,
        baseline_id=baseline_id, implied_returns={t: round(float(x), 6) for t, x in zip(tk, pi, strict=True)},
        shrinkage=mm["shrinkage"], notes=notes + warnings,
    )  # fmt: skip
    model_d = model.model_dump(mode="json")
    model_d["invested_total"] = total
    model_d["weight_capacity"] = round(capacity, 6)
    base = BaselinePortfolios(request_id=rid, as_of=as_of, chosen_baseline=baseline_id, portfolios=ports)
    return model_d, base.model_dump(mode="json")
