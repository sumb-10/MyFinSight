"""시장모형·비중·뷰·타겟 (Module4)."""

from __future__ import annotations

from datetime import date
from typing import Literal

from pydantic import BaseModel, Field, model_validator


class MarketModel(BaseModel):
    request_id: str
    stage: str = "08_market_model"
    as_of: date
    lookback: dict
    tickers: list[str]
    ann_vol: dict[str, float]
    corr: list[list[float]]
    cov: list[list[float]]
    cap_weights: dict[str, float]
    delta: float
    delta_source: str = "fixed"
    delta_market: float | None = None
    delta_multiplier: float | None = None
    delta_window: dict | None = None
    delta_dd_multiplier: float | None = None  # 허용 낙폭 배수 (라운드 5)
    delta_tolerance: float | None = None
    tau: float
    baseline_id: str
    implied_returns: dict[str, float]
    shrinkage: dict
    notes: list[str] = []


class ExAnte(BaseModel):
    exp_return: float
    vol: float
    sharpe: float
    effective_n: float


class Portfolio(BaseModel):
    id: str
    kind: Literal["template", "black_litterman"]
    name_ko: str
    rule_ko: str = ""
    weights: dict[str, float]
    cash_weight: float = 0.0
    ex_ante: ExAnte
    sector_weights: dict[str, float]
    constraints_applied: list[str] = []
    # black-litterman extras
    scenario_id: str | None = None
    title_ko: str | None = None
    portfolio_view: str | None = None
    views_applied: list[dict] = []
    delta_vs_baseline: dict[str, float] = {}
    posterior_returns: dict[str, float] = {}
    active_constraints: list[str] = []

    @model_validator(mode="after")
    def _sums(self) -> Portfolio:
        tot = sum(self.weights.values()) + self.cash_weight
        if abs(tot - 1) > 1e-4:
            raise ValueError(f"portfolio {self.id}: weights + cash = {tot:.6f}, expected 1")
        if self.weights and min(self.weights.values()) < -1e-9:
            raise ValueError(f"portfolio {self.id}: negative weight")
        return self


class BaselinePortfolios(BaseModel):
    request_id: str
    stage: str = "08_baseline_portfolios"
    as_of: date
    chosen_baseline: str
    portfolios: list[Portfolio]


class View(BaseModel):
    type: Literal["absolute", "relative"]
    long: list[str] = Field(min_length=1)
    short: list[str] = []
    expected_return_annual: float
    confidence: float = Field(gt=0, le=1)
    horizon_months: int = Field(ge=1, le=60, default=12)
    rationale_ko: str
    evidence_type: str = "news"  # news 만 허용 (K6: 플레이스홀더 뷰 없음)
    evidence_ids: list[str] = Field(min_length=1)

    @model_validator(mode="after")
    def _shape(self) -> View:
        if self.type == "relative" and not self.short:
            raise ValueError("relative view needs a short leg")
        if self.type == "absolute" and self.short:
            raise ValueError("absolute view must not have a short leg")
        if set(self.long) & set(self.short):
            raise ValueError("a ticker cannot be in both legs")
        return self


class ViewSet(BaseModel):
    scenario_id: str
    title_ko: str
    narrative_ko: str
    views: list[View] = Field(min_length=1)


class Views(BaseModel):
    request_id: str
    stage: str = "09_views"
    as_of: date
    window: dict | None = None  # {"start": ..., "end": ..., "n_items": ..., "n_tickers": ...}
    max_view_confidence: float
    sets: list[ViewSet] = []
    fallback: bool = False  # 뉴스 부족 등으로 뷰를 만들지 않음 -> 기준 비중 사용
    fallback_reason_ko: str | None = None
    warnings: list[str] = []


class TargetPortfolios(BaseModel):
    request_id: str
    stage: str = "10_target_portfolios"
    as_of: date
    backtest_spec: dict
    parameters: dict
    baseline: dict
    portfolios: list[Portfolio]
    templates: list[Portfolio]
    notes_ko: list[str] = []
    warnings: list[str] = []
