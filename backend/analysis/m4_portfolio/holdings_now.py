"""분석 기준일 구성 = 백테스트에서 그대로 꺼낸 보유 종목·비중 (2026-11-19 사용자 결정).

원래 의도: 백테스트 시작일에 종목을 고르고, 그 종목을 유지하며 리밸런싱한다. 분석 기준일에 종목을 다시 고르지 않는다.
분석 기준일 비중은 '직전 리밸런싱의 목표 비중' (분석 기준일이 리밸런싱일이면 그날 비중):
- 시작일 비중으로 되돌리는 구성(정적): 리밸런싱마다 시작일 목표 비중으로 되돌리므로 시작일 목표 비중 그대로
- 워크포워드 구성: weights_by_date 중 분석 기준일 이하의 마지막 날짜(리밸런싱일)의 비중
- 낙폭 맞춤안 등 현금을 섞은 구성: 그 구성의 비중(주식 + 현금) 그대로
리밸런싱 뒤 주가 움직임으로 바뀐 실제 비중(그날 계좌 모양)은 쓰지 않는다 — 새로 투자를 시작하는 사람이 살 비중은 정해 둔 목표 비중이다.
"""

from __future__ import annotations

import datetime as dt
from typing import Any


def _d(x: Any) -> str:
    return str(x)[:10]


def target_on(p: dict[str, Any], as_of: str | dt.date) -> tuple[dict[str, float], str | None]:
    """구성 하나의 분석 기준일 목표 비중과 그 비중을 정한 리밸런싱일. 워크포워드면 as_of 이하 마지막 날짜, 아니면 시작일 목표 비중."""
    day = _d(as_of)
    wbd = p.get("weights_by_date") or {}
    if wbd:
        dates = sorted(d for d in wbd if _d(d) <= day)
        if dates:
            return {t: float(w) for t, w in wbd[dates[-1]].items() if float(w) > 1e-9}, _d(dates[-1])
    w = p.get("target_weights") or p.get("weights") or {}
    return {t: float(x) for t, x in w.items() if float(x) > 1e-9}, None


def holdings_now(portfolios: list[dict[str, Any]], as_of: str | dt.date, start: str | dt.date) -> dict[str, dict[str, Any]]:
    """백테스트 구성마다 {weights, cash_weight, rebalance_date, mode, name_ko}. rebalance_date 는 비중을 정한 날(정적 구성은 시작일)."""
    out: dict[str, dict[str, Any]] = {}
    for p in portfolios:
        if not p.get("id"):
            continue
        w, day = target_on(p, as_of)
        if not w:
            continue
        out[p["id"]] = {"weights": w, "cash_weight": round(max(0.0, 1.0 - sum(w.values())), 6),
                        "rebalance_date": day or _d(start), "mode": "walkforward" if day else "static",
                        "name_ko": p.get("name_ko") or p["id"], "kind": p.get("kind")}  # fmt: skip
    return out
