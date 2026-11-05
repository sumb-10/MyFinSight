"""M4-04 Black-Litterman 타겟. 뷰 세트마다 기준 비중(prior)에 뷰를 결합해 비중 하나."""

from __future__ import annotations

from typing import Any

import numpy as np

from backend.analysis.m4_portfolio import math as P
from backend.analysis.m4_portfolio.market_model import sector_lists
from backend.analysis.schemas.portfolio import Portfolio
from backend.analysis.settings import AnalysisSettings
from backend.pipeline.descriptor import Descriptor


STRENGTH_KO = {"weak": "약", "medium": "중", "strong": "강"}


def view_summary(v: dict[str, Any]) -> str:
    """뷰 한 줄. 방향·강도가 있으면 '사전 기대 → 뷰' 를 같이 써서 비중이 왜 움직였는지 보이게 한다 (C1)."""
    legs = "+".join(v["long"]) + (f" > {'+'.join(v['short'])}" if v.get("short") else "")
    kind = "상대" if v["type"] == "relative" else "절대"
    if v.get("prior_return") is None or not v.get("direction"):
        return f"[{kind}] {legs} {v['expected_return_annual']:+.0%}/년 (신뢰 {v['confidence']:.2f}) — {v.get('rationale_ko', '')}"
    st = STRENGTH_KO.get(v.get("strength") or "", "")
    if v["type"] == "relative":
        shift = (float(v["expected_return_annual"]) - float(v["prior_return"])) * 100
        head = (f"[{kind}] {legs} ({st}) — 기대 차이를 {'+'.join(v['long'])} 쪽으로 {shift:+.1f}%p "
                f"(사전 {v['prior_return']:+.1%} → 뷰 {v['expected_return_annual']:+.1%}/년)")
    else:
        arrow = "오름" if v["direction"] == "up" else "내림"
        head = f"[{kind}] {legs} {arrow}({st}) — 사전 기대 {v['prior_return']:+.1%} → 뷰 {v['expected_return_annual']:+.1%}/년"
    return f"{head} (신뢰 {v['confidence']:.2f}) — {v.get('rationale_ko', '')}"


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
    # 반올림된 종목 비중의 합은 상한 용량을 초과할 수 있으므로 원래 투자 총액을 쓴다.
    total = float(mm.get("invested_total", 1.0 - bp["cash_weight"]))
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
        if kind == "view_hold":
            return f"view_direction_hold:{tk[int(val)]}"
        return x

    ports: list[dict[str, Any]] = []
    warnings: list[str] = []
    for k, s in enumerate(view_sets, 1):
        Pm, Q, C = P.build_PQ(s["views"], tk)
        mu, _cov_post = P.black_litterman(cov, pi, Pm, Q, C, tau)
        # 효용 최적화는 사전 공분산 Σ 로 (Module4 §BL: max μ_BL'w − δ/2 w'Σw). 사후 공분산(Σ+M)을 쓰면 뷰 신뢰도가 0 이어도
        # 기준 비중으로 돌아오지 않고 최소분산 쪽으로 쏠린다 (π 는 Σ 로 역최적화했으므로).
        # 뷰 방향을 거스르는 비중 이동은 막는다 (026: 섹터 예산이 묶여 'AVGO 오름' 날 AVGO 비중이 크게 줄었다 — Q-001 과 같은 증상, 다른 원인)
        w, active = P.optimize_utility(mu, cov, delta, wb, max_stock, max_sector, sec_code, max_tilt, total, min_weight=ps.min_weight,
                                       view_dir=P.view_directions(s["views"], tk))  # fmt: skip
        failed = any(x.startswith("optimizer_failed") for x in active)
        if failed:  # 기준 비중 그대로: 뷰를 반영한 것처럼 보이는 설명·사후 수익을 남기지 않는다
            mu = pi.copy()
            warnings.append(f"set {k}: BL optimizer failed, baseline weights kept ({next(x for x in active if x.startswith('optimizer_failed'))})")
        d = w - wb
        w_out, cash_out = P.weights_out(tk, w)
        pv = ("뉴스 뷰 비중 최적화가 수렴하지 않아 기준 비중을 유지했습니다 (뷰 미반영)." if failed
              else s.get("narrative_ko", "") + "\n" + "\n".join("- " + view_summary(v) for v in s["views"]))
        ports.append(Portfolio(
            id=f"{id_prefix}_{k:02d}", kind="black_litterman",
            name_ko=f"{name_prefix} {k}: {s.get('title_ko', '')}" + (" (뷰 미반영)" if failed else ""),
            rule_ko="Black-Litterman (기준 비중 prior + 뉴스 근거 뷰)", scenario_id=s.get("scenario_id", f"set{k}"), title_ko=s.get("title_ko"),
            portfolio_view=pv,
            views_applied=[] if failed else [{"summary_ko": view_summary(v), "type": v["type"], "long": v["long"], "short": v.get("short", []),
                            "direction": v.get("direction"), "strength": v.get("strength"), "prior_return": v.get("prior_return"),
                            "expected_return_annual": v["expected_return_annual"], "confidence": v["confidence"],
                            "rationale_ko": v.get("rationale_ko", ""), "evidence_type": v.get("evidence_type", "news"),
                            "evidence_ids": v.get("evidence_ids", [])} for v in s["views"]],
            weights=w_out, cash_weight=cash_out,
            delta_vs_baseline={t: round(float(x), 6) for t, x in zip(tk, d, strict=True)},
            posterior_returns={t: round(float(x), 6) for t, x in zip(tk, mu, strict=True)},
            ex_ante=P.ex_ante_stats(w, mu, cov), sector_weights=P.sector_weights(w, sec_name), active_constraints=[label(x) for x in active],
        ).model_dump(mode="json"))  # fmt: skip
    params = {"tau": tau, "delta": delta, "omega_method": ps.omega_method, "lookback_days": ps.lookback_days, "max_tilt_per_stock": max_tilt,
              "shrinkage": mm["shrinkage"], "max_weight_per_stock": max_stock, "max_weight_per_sector": max_sector,
              "min_cash_ratio": cons.get("min_cash_ratio", 0), "information_cutoff": "t-1"}  # fmt: skip
    return ports, warnings, params
