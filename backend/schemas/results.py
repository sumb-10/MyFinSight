"""M00-02 전략 실행 결과·검증·백테스트 스키마 (명세서 그대로 옮긴 임시본)."""

from __future__ import annotations

from datetime import date
from typing import Literal

from pydantic import BaseModel, ConfigDict


class TickerSignal(BaseModel):
    """근거용 수치 (M03-01/M03-02 가 채움)."""

    model_config = ConfigDict(extra="forbid")

    ticker: str
    metric_name: str
    value: float
    rank: int | None = None
    universe_size: int


class WeightSet(BaseModel):
    """M03-04 출력."""

    model_config = ConfigDict(extra="forbid")

    as_of: date
    spec_hash: str
    weights: dict[str, float]  # 합 1.0
    pre_cap_weights: dict[str, float]  # 상한 적용 전 (근거용)
    signals: list[TickerSignal]
    selected: list[str]


class ValidationIssue(BaseModel):
    model_config = ConfigDict(extra="forbid")

    code: str
    field: str | None = None
    message: str


class ValidationResult(BaseModel):
    model_config = ConfigDict(extra="forbid")

    ok: bool
    issues: list[ValidationIssue] = []


class CalcConditions(BaseModel):
    """FR12, Report 「계산 조건」."""

    model_config = ConfigDict(extra="forbid")

    start: date
    end: date
    rebalance: str
    benchmark: str
    cost_bps: float
    risk_free_annual: float
    base_currency: Literal["USD"] = "USD"
    initial_capital_usd: float
    fx_rate_krw_per_usd: float
    fx_as_of: date


class RebalanceRecord(BaseModel):
    model_config = ConfigDict(extra="forbid")

    date: date
    weights: dict[str, float]
    turnover: float
    cost_usd: float


class BacktestResult(BaseModel):
    """M05-01 출력 (시계열은 dict 로 직렬화)."""

    model_config = ConfigDict(extra="forbid")

    conditions: CalcConditions
    spec_hash: str
    equity_curve: dict[date, float]  # 전략 평가액(USD)
    benchmark_curve: dict[date, float]
    rebalances: list[RebalanceRecord]


class PerformanceMetrics(BaseModel):
    """M05-02 출력 (비율은 소수: 0.152 = 15.2%)."""

    model_config = ConfigDict(extra="forbid")

    total_return: float
    cagr: float
    ann_volatility: float
    sharpe: float
    mdd: float
    mdd_peak: date
    mdd_trough: date


class MetricsBundle(BaseModel):
    model_config = ConfigDict(extra="forbid")

    strategy: PerformanceMetrics
    benchmark: PerformanceMetrics
    excess_total_return: float
    excess_cagr: float
