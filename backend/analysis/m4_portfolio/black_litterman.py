"""M4-04 Black-Litterman 타겟. 뷰 세트마다 기준 비중(prior)에 뷰를 결합해 비중 하나."""

from __future__ import annotations

from typing import Any

import numpy as np

from backend.analysis.m4_portfolio import math as P
from backend.analysis.m4_portfolio.market_model import sector_lists
from backend.analysis.schemas.portfolio import Portfolio
from backend.analysis.settings import AnalysisSettings
from backend.pipeline.descriptor import Descriptor


def view_summary(v: dict[str, Any]) -> str:
    legs = "+".join(v["long"]) + (f" > {'+'.join(v['short'])}" if v.get("short") else "")
    kind = "상대" if v["type"] == "relative" else "절대"
    return f"[{kind}] {legs} {v['expected_return_annual']:+.0%}/년 (신뢰 {v['confidence']:.2f}) — {v.get('rationale_ko', '')}"


def build_bl(
    mm: dict[str, Any],
    base: dict[str, Any],
    view_sets: list[dict[str, Any]],
    req: dict[str, Any],
    intent: dict[str, Any],
    desc: Descriptor,
    settings: AnalysisSettings,
    *,
    id_prefix: str = "bl",
    name_prefix: str = "BL 타겟",
) -> tuple[list[dict[str, Any]], list[str], dict[str, Any]]:
    ps = settings.portfolio
    tk = mm["tickers"]
    cov = np.array(mm["cov"])
    pi = np.array([mm["implied_returns"][t] for t in tk])
    delta, tau = mm["delta"], mm["tau"]
    cons = req["constraints"]
    max_stock, max_sector = cons["max_weight_per_stock"], cons["max_weight_per_sector"]
    max_tilt = intent["news_tilt"]["max_tilt_per_stock"]
    sec_code, sec_name = sector_lists(desc, tk)
    bp = next(p for p in base["portfolios"] if p["id"] == base["chosen_baseline"])
    wb = np.array([bp["weights"][t] for t in tk])
    total = float(wb.sum())  # 기준 비중의 투자 총액 (상한 용량·현금 비율 반영)
    sec_names = dict(zip(sec_code, sec_name, strict=True))

    def label(x: str) -> str:
        if ":" not in x:
            return x
        kind, val = x.split(":", 1)
        if kind == "upper":
            return f"tilt_or_stock_cap:{tk[int(val)]}"
        if kind == "lower":
            return f"tilt_floor:{tk[int(val)]}"
        if kind == "sector_cap":
            return f"sector_cap:{sec_names.get(val, val)}"
        return x

    ports: list[dict[str, Any]] = []
    warnings: list[str] = []
    for k, s in enumerate(view_sets, 1):
        Pm, Q, C = P.build_PQ(s["views"], tk)
        mu, cov_bl = P.black_litterman(cov, pi, Pm, Q, C, tau)
        w, active = P.optimize_utility(mu, cov_bl, delta, wb, max_stock, max_sector, sec_code, max_tilt, total, min_weight=ps.min_weight)
        d = w - wb
        pv = s.get("narrative_ko", "") + "\n" + "\n".join("- " + view_summary(v) for v in s["views"])
        ports.append(Portfolio(
            id=f"{id_prefix}_{k:02d}", kind="black_litterman", name_ko=f"{name_prefix} {k}: {s.get('title_ko', '')}",
            rule_ko="Black-Litterman (기준 비중 prior + 뉴스 근거 뷰)", scenario_id=s.get("scenario_id", f"set{k}"), title_ko=s.get("title_ko"),
            portfolio_view=pv,
            views_applied=[{"summary_ko": view_summary(v), "type": v["type"], "long": v["long"], "short": v.get("short", []),
                            "expected_return_annual": v["expected_return_annual"], "confidence": v["confidence"],
                            "rationale_ko": v.get("rationale_ko", ""), "evidence_type": v.get("evidence_type", "news"),
                            "evidence_ids": v.get("evidence_ids", [])} for v in s["views"]],
            weights={t: round(float(x), 6) for t, x in zip(tk, w, strict=True)}, cash_weight=round(1 - float(w.sum()), 6),
            delta_vs_baseline={t: round(float(x), 6) for t, x in zip(tk, d, strict=True)},
            posterior_returns={t: round(float(x), 6) for t, x in zip(tk, mu, strict=True)},
            ex_ante=P.ex_ante_stats(w, mu, cov_bl), sector_weights=P.sector_weights(w, sec_name), active_constraints=[label(x) for x in active],
        ).model_dump(mode="json"))  # fmt: skip
    params = {"tau": tau, "delta": delta, "omega_method": ps.omega_method, "lookback_days": ps.lookback_days, "max_tilt_per_stock": max_tilt,
              "shrinkage": mm["shrinkage"], "max_weight_per_stock": max_stock, "max_weight_per_sector": max_sector,
              "min_cash_ratio": cons.get("min_cash_ratio", 0), "information_cutoff": "t-1"}  # fmt: skip
    return ports, warnings, params
