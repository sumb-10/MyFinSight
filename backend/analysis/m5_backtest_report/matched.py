"""낙폭 맞춤안 (dd_match_*) — 기준 포트폴리오의 주식 비중을 (1−c) 로 줄이고 나머지 c 를 현금(수익 0)으로 두어,
**실제 리밸런싱 일정**으로 돌린 최대낙폭이 목표(낙폭 맞춤 목표 = 허용 낙폭 × 성향 보정) 안에 들어오는 정식 후보.

라운드 5: 예전 '현금 혼합안'(검증 단계의 사후 대안)은 일별 리밸런싱 가정으로 현금 비율을 풀어 실제 일정에서는 목표를 넘기기도 했다.
여기서는 폐형식 값을 씨앗으로만 쓰고, 실제 일정으로 돌린 결과로 이분 탐색한다. 백테스트 실행 함수는 호출자(backtest.py)가 넘긴다 (순환 import 방지).
"""

from __future__ import annotations

import math
from collections.abc import Callable
from typing import Any

import pandas as pd

from backend.analysis.m5_backtest_report import backtest_metrics as M

MAX_CASH = 0.95
BASE_LABEL_BL = "뉴스 반영 BL"


def seed_cash_ratio(index_values, target: float) -> float:
    """일별 리밸런싱 가정의 폐형식 씨앗: 현금 비율 c ∈ [0, MAX_CASH] 중 MDD ≤ 목표가 되는 최소값 (현금 수익 0)."""
    idx = pd.Series(list(index_values), dtype=float)
    r = idx.pct_change().fillna(0.0)

    def mdd(c: float) -> float:
        return float(M.drawdown_series((1 + (1 - c) * r).cumprod()).min())

    if mdd(0.0) >= -target:
        return 0.0
    lo, hi = 0.0, MAX_CASH
    for _ in range(40):
        mid = (lo + hi) / 2
        if mdd(mid) >= -target:
            hi = mid
        else:
            lo = mid
    return round(hi, 4)


def _mdd(raw: dict[str, Any]) -> float:
    return float(M.drawdown_series(raw["index"]).min())


def solve_cash_ratio(run_fn: Callable[[float], dict[str, Any]], seed: float, target: float, *, iters: int = 6, bump: float = 0.01,
                     max_bumps: int = 3) -> tuple[float | None, dict[str, Any] | None, int]:  # fmt: skip
    """실제 일정으로 돌린 MDD 가 목표 안에 들어오는 현금 비율. (c, raw, 실행 횟수). 못 찾으면 (None, None, n).

    씨앗 주변 [seed−0.10, seed+0.15] 에서 이분 탐색 → 0.5%p 올림 → 검증, 목표를 넘으면 +bump 씩 최대 max_bumps 회.
    적립이 있으면 MDD 가 c 에 완전히 단조가 아닐 수 있어 마지막 검증을 반드시 거친다.
    """
    n = 0
    lo, hi = max(0.0, seed - 0.10), min(MAX_CASH, seed + 0.15)
    raw_hi = run_fn(hi)
    n += 1
    while _mdd(raw_hi) < -target and hi < MAX_CASH - 1e-9:
        hi = min(MAX_CASH, hi + 0.10)
        raw_hi = run_fn(hi)
        n += 1
    if _mdd(raw_hi) < -target:
        return None, None, n
    for _ in range(iters):
        mid = (lo + hi) / 2
        raw_mid = run_fn(mid)
        n += 1
        if _mdd(raw_mid) >= -target:
            hi, raw_hi = mid, raw_mid
        else:
            lo = mid
    c = math.ceil(hi * 200 - 1e-9) / 200  # 0.5%p 단위로 올림
    raw = raw_hi
    if abs(c - hi) > 1e-12:
        raw = run_fn(c)
        n += 1
    for _ in range(max_bumps):
        if _mdd(raw) >= -target:
            break
        c = round(c + bump, 4)
        raw = run_fn(c)
        n += 1
    if _mdd(raw) < -target or c > MAX_CASH + 1e-9:
        return None, None, n
    return round(c, 4), raw, n


def scale_weights(w: dict[str, float], c: float) -> dict[str, float]:
    return {t: round(float(x) * (1 - c), 6) for t, x in w.items()}


def matched_name(base_label: str, invested: float) -> str:
    """총 투자 비중으로 적는다 (기준 구성에 현금이 있어도 합이 100%)."""
    return f"낙폭 맞춤안 (주식 {invested:.0%} + 현금 {1 - invested:.0%}, {base_label} 기준)"
