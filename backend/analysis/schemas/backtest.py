"""백테스트 사양(M4-01)과 결과(M5-01·02)."""

from __future__ import annotations

from datetime import date
from typing import Literal

from pydantic import BaseModel, Field, model_validator

from backend.analysis.schemas.request import RebalanceRule


class Confirmation(BaseModel):
    selection_confirmed: bool = True
    removed_tickers: list[str] = []
    added_tickers: list[str] = []


class BacktestWindow(BaseModel):
    start_date: date
    end_date: date
    reselect_at_start: bool = True
    benchmark: str | None = None
    include_contributions: bool = True

    @model_validator(mode="after")
    def _order(self) -> BacktestWindow:
        if self.start_date >= self.end_date:
            raise ValueError("backtest.start_date must be before end_date")
        return self


class ViewsConfig(BaseModel):
    n_sets: int = Field(ge=1, le=10, default=5)
    views_per_set: int = Field(ge=1, le=8, default=4)


class WalkforwardConfig(BaseModel):
    enabled: bool = True
    view_sets: int = Field(ge=1, le=5, default=1)
    views_per_set: int = Field(ge=1, le=8, default=4)


class ForwardConfig(BaseModel):
    enabled: bool = True
    as_of: date | None = None  # None -> 분석 기준일


class BacktestRequest(BaseModel):
    request_id: str
    confirmation: Confirmation = Confirmation()
    backtest: BacktestWindow
    views: ViewsConfig = ViewsConfig()
    walkforward: WalkforwardConfig = WalkforwardConfig()
    forward_construction: ForwardConfig = ForwardConfig()


class Period(BaseModel):
    start: date
    end: date
    as_of: date
    trading_days: int


class CapitalSpec(BaseModel):
    initial_amount_usd: float
    monthly_contribution_usd: float
    contribution_day: int
    include_contributions: bool
    currency: str | None = None
    initial_amount_krw: float | None = None
    monthly_contribution_krw: float | None = None
    fx_rate: float | None = None  # KRW per USD used for THIS backtest (at the window start)
    fx_date: date | None = None
    fx_source: str | None = None


class SelectionRow(BaseModel):
    ticker: str
    name: str
    sector: str
    rank: int
    metric_value: float


class SelectionSpec(BaseModel):
    source: Literal["reselected_at_start", "original"]
    metric: str
    tickers: list[str] = Field(min_length=1)
    table: list[SelectionRow]
    diff_vs_original: dict[str, list[str]]
    infeasibility: dict | None = None
    sector_overflow: dict | None = None


class BacktestSpec(BaseModel):
    request_id: str
    stage: str = "07_backtest_spec"
    period: Period
    capital: CapitalSpec
    rebalance_rule: RebalanceRule
    benchmark: str
    extra_benchmarks: list[str] = []
    execution_rule: dict = Field(
        default_factory=lambda: {
            "information_cutoff": "t-1",
            "execution_price": "t close",
            "description_ko": "리밸런싱일 t 의 비중은 t−1 까지의 가격·뉴스로 계산하고 t 종가로 체결한다.",
        }
    )
    selection: SelectionSpec
    warnings: list[str] = []


class CheckpointWeights(BaseModel):
    target: dict[str, float]
    before: dict[str, float] | None = None
    after: dict[str, float]
    cash_before: float | None = None
    cash_after: float


class Checkpoint(BaseModel):
    seq: int
    date: date
    kind: Literal["rebalance", "closing", "monthly"]
    n_trading_days_to_date: int
    weights: CheckpointWeights
    drift: dict | None = None
    holdings: list[dict]
    trades: list[dict] = []
    turnover: float | None = None
    commission_usd: float = 0.0
    money: dict
    since_last: dict | None = None
    to_date: dict | None = None
    view_diagnostics_to_date: list[dict] = []


class PortfolioResult(BaseModel):
    id: str
    kind: Literal["black_litterman", "template", "benchmark", "alternative", "matched"]  # matched = 낙폭 맞춤안 (라운드 5)
    mode: str = "static"
    base_id: str | None = None  # matched: 기준 포트폴리오 id
    cash_ratio: float | None = None  # matched: 기준 비중에 곱한 (1−c) 의 c
    cash_ratio_total: float | None = None  # matched: 총 현금 비중 (1 − 투자 비중)
    match_target: float | None = None  # matched: 맞춘 낙폭 목표
    solver_runs: int | None = None
    weights_by_date: dict | None = None
    views_by_date: dict | None = None
    fallback_dates: list | None = None
    name_ko: str
    title_ko: str | None = None
    portfolio_view: str | None = None
    target_weights: dict[str, float]
    headline: dict
    metrics: dict
    money: dict
    series: dict[str, list]
    monthly_returns: list[dict]
    yearly_returns: dict[str, float | None]
    checkpoints: list[Checkpoint]
    contribution_ledger: list[dict] = []
    events: list[dict] = []
    ticker_contribution: dict[str, float | None] = {}
    ticker_total_return: dict[str, float | None] = {}
    view_diagnostics: list[dict] = []
    view_diagnostics_next_rb: list[dict] = []  # 뷰를 세운 날부터 다음 리밸런싱일까지의 적중 (라운드 5)

    @model_validator(mode="after")
    def _lengths(self) -> PortfolioResult:
        n = {k: len(v) for k, v in self.series.items()}
        if len(set(n.values())) != 1:
            raise ValueError(f"portfolio {self.id}: series lengths differ {n}")
        return self


class BacktestResults(BaseModel):
    request_id: str
    stage: str = "11_backtest_results"
    mode: str = "static_weights"
    period: dict
    engine: dict
    series_dates: list[str]
    benchmark: PortfolioResult
    benchmarks: list[PortfolioResult] = []
    portfolios: list[PortfolioResult]
    ranking: list[dict]
    reproducibility: dict
    data_quality: dict | None = None
    warnings: list[str] = []

    @model_validator(mode="after")
    def _aligned(self) -> BacktestResults:
        n = len(self.series_dates)
        for p in [self.benchmark, *self.benchmarks, *self.portfolios]:
            for k, v in p.series.items():
                if len(v) != n:
                    raise ValueError(f"{p.id}.series.{k} length {len(v)} != {n}")
        return self
