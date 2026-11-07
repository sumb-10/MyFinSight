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
# 날짜별(walk-forward) BL 이라고 이름에 적는다 (047: '뉴스 반영 BL 기준 맞춤안' 이 같은 뉴스 BL 인 정적 선택안 bl_03 을 바탕으로 한 것처럼 읽혔다)
BASE_LABEL_BL = "walk-forward 뉴스 뷰 BL"


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
                     max_bumps: int = 3, max_cash: float = MAX_CASH) -> tuple[float | None, dict[str, Any] | None, int]:  # fmt: skip
    """실제 일정으로 돌린 MDD 가 목표 안에 들어오는 현금 비율. (c, raw, 실행 횟수). 못 찾으면 (None, None, n).

    씨앗 주변 [seed−0.10, seed+0.15] 에서 이분 탐색 → 0.5%p 올림 → 검증, 목표를 넘으면 +bump 씩 최대 max_bumps 회.
    적립이 있으면 MDD 가 c 에 완전히 단조가 아닐 수 있어 마지막 검증을 반드시 거친다.
    max_cash: 현금 비율 상한 (주식 비중 하한에서 계산, 정책 결정 2). 이 안에서 못 맞추면 None.
    """
    n = 0
    cap = min(MAX_CASH, max_cash)
    if cap < 0:
        return None, None, n
    lo, hi = min(max(0.0, seed - 0.10), cap), min(cap, seed + 0.15)
    raw_hi = run_fn(hi)
    n += 1
    while _mdd(raw_hi) < -target and hi < cap - 1e-9:
        hi = min(cap, hi + 0.10)
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
    if _mdd(raw) < -target or c > cap + 1e-9:
        return None, None, n
    return round(c, 4), raw, n


def scale_weights(w: dict[str, float], c: float) -> dict[str, float]:
    return {t: round(float(x) * (1 - c), 6) for t, x in w.items()}


def _pct1(p: float) -> str:
    """0.1 단위로 반올림한 퍼센트 값 → '98.5%' / 정수면 '77%'."""
    return f"{int(round(p))}%" if abs(p - round(p)) < 1e-9 else f"{p:.1f}%"


def share_pct(x: float) -> str:
    """비중 → '98.5%' (정수에서 0.05%p 안이면 '77%'). 015: 0.985 를 '99%' 로 적어 같은 리포트의 98.5% 와 달랐다."""
    return _pct1(round(float(x) * 100, 1))


def stock_cash_ko(invested: float) -> str:
    """'주식 98.5% + 현금 1.5%' (정수 근처면 '주식 77% + 현금 23%'). 현금은 100 − 주식을 같은 자리수로 (따로 반올림하면 '주식 24% + 현금 77%' 처럼 합이 어긋날 수 있다)."""
    stock = round(float(invested) * 100, 1)
    return f"주식 {_pct1(stock)} + 현금 {_pct1(round(100 - stock, 1))}"


def matched_name(base_label: str, invested: float) -> str:
    """총 투자 비중으로 적는다 (기준 구성에 현금이 있어도 합이 100%). 정수가 아니면 소수 한 자리 (015: 98.5% 를 '주식 99% + 현금 1%' 로 적었다)."""
    return f"낙폭 맞춤안 ({stock_cash_ko(invested)}, {base_label} 기준)"
