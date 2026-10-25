"""사용자 요청 (Module1 §4, 부록 A). [HARD] 필드는 여기서 검증, [SOFT] 필드는 LLM 이 해석한다."""

from __future__ import annotations

from datetime import date
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

RebalanceUnit = Literal["2w", "1m", "1q", "6m", "1y"]
Template = Literal["low_per", "quality", "momentum", "low_volatility", "high_dividend"]
Weighting = Literal["equal_weight", "market_cap", "inverse_volatility", "min_variance"]
RiskTolerance = Literal["conservative", "moderate", "aggressive"]
Universe = Literal["SP500", "NASDAQ100", "KOSPI200"]

TEMPLATE_METRICS: dict[str, tuple[str, str]] = {
    # template -> (metric, direction)
    "low_per": ("pe_ttm", "asc"),
    "quality": ("roe_ttm", "desc"),
    "momentum": ("return_12m_1m", "desc"),
    "low_volatility": ("vol_60d", "asc"),
    "high_dividend": ("dividend_yield_ttm", "desc"),
}

# 유니버스 -> 시장 (혼합 시장 처리·통화 분리에 사용)
UNIVERSE_MARKET: dict[str, str] = {"SP500": "US", "NASDAQ100": "US", "KOSPI200": "KR"}


class Profile(BaseModel):
    user_id: str = "default"
    age_band: Literal["20s", "30s", "40s", "50s", "60s+"]
    investment_experience: Literal["none", "beginner", "intermediate", "advanced"]
    financial_knowledge: Literal["basic", "intermediate", "expert"]
    investable_ratio_of_assets: float = Field(ge=0, le=1)


class Capital(BaseModel):
    initial_amount: float = Field(gt=0)
    currency: Literal["KRW", "USD"]
    trading_currency: Literal["USD"] = "USD"
    monthly_contribution: float = Field(ge=0, default=0)
    contribution_day: int = Field(ge=1, le=28, default=25)


class Horizon(BaseModel):
    start_date: date | None = None  # 분석 기준일(as_of). 요청 조립 때 derive 가 채운다
    target_years: float = Field(ge=1, le=10)  # 설계 범위 1~10년 (라운드 5: 0.5년 저장이 통과하던 문제)
    purpose: Literal["wealth_growth", "income", "capital_preservation", "retirement"]
    backtest_years: float = Field(ge=1, le=20, default=3.0)  # K2: 사용자 지정, 기본 3년


class Risk(BaseModel):
    risk_tolerance: RiskTolerance
    max_drawdown_tolerance: float = Field(gt=0, le=1)
    loss_reaction: Literal["sell", "hold", "buy_more"]
    target_annual_return: float
    benchmark: str = "SPY"


class NumHoldings(BaseModel):
    target: int = Field(ge=1)
    min: int = Field(ge=1)
    max: int = Field(ge=1)

    @model_validator(mode="after")
    def _order(self) -> NumHoldings:
        if not (self.min <= self.target <= self.max):
            raise ValueError(
                f"num_holdings must satisfy min <= target <= max, got {self.min}/{self.target}/{self.max}"
            )
        return self


class Rebalance(BaseModel):
    count: int = Field(ge=0, description="0 = no rebalancing (buy and hold)")
    unit: RebalanceUnit


class Constraints(BaseModel):
    universe: list[Universe] = Field(min_length=1)
    asset_types: list[Literal["stock", "etf"]] = Field(min_length=1, default_factory=lambda: ["stock"])
    num_holdings: NumHoldings
    max_weight_per_stock: float = Field(gt=0, le=1)
    max_weight_per_sector: float = Field(gt=0, le=1)
    min_cash_ratio: float = Field(ge=0, lt=1, default=0)
    exclude_tickers: list[str] = []
    exclude_sectors: list[str] = []
    exclude_themes: list[str] = []
    must_include_tickers: list[str] = []
    rebalance: Rebalance
    allow_leverage: bool = False
    allow_short: bool = False
    min_market_cap_usd: float = Field(ge=0, default=0)
    min_avg_daily_volume_usd: float = Field(ge=0, default=0)

    @model_validator(mode="after")
    def _feasible(self) -> Constraints:
        # the fewest allowed holdings at the per-stock cap must still be able to hold 1 - cash
        invested = 1 - self.min_cash_ratio
        if self.max_weight_per_stock * self.num_holdings.min < invested - 1e-9:
            raise ValueError(
                "max_weight_per_stock x num_holdings.min < 1 - min_cash_ratio: weights cannot sum up"
            )
        if self.max_weight_per_sector < self.max_weight_per_stock:
            raise ValueError("max_weight_per_sector must be >= max_weight_per_stock")
        if len(self.must_include_tickers) > self.num_holdings.max:
            raise ValueError("more must_include_tickers than num_holdings.max")
        clash = set(self.must_include_tickers) & set(self.exclude_tickers)
        if clash:
            raise ValueError(f"tickers both included and excluded: {sorted(clash)}")
        if self.allow_leverage or self.allow_short:
            raise ValueError("leverage and short selling are not supported")
        return self

    def markets(self) -> list[str]:
        return sorted({UNIVERSE_MARKET[u] for u in self.universe})


class StrategyPreference(BaseModel):
    template: Template
    baseline_weighting: Weighting
    use_news_tilt: bool = True


class NaturalLanguage(BaseModel):
    idea: str = Field(min_length=5)
    language: str = "ko"


class UserRequest(BaseModel):
    model_config = ConfigDict(extra="ignore")

    request_id: str
    created_at: str
    profile: Profile
    capital: Capital
    horizon: Horizon
    risk: Risk
    constraints: Constraints
    strategy_preference: StrategyPreference
    natural_language: NaturalLanguage


class RebalanceRule(BaseModel):
    count: int
    unit: RebalanceUnit
    enabled: bool
    description_ko: str
    trading_days: int | None = None  # for 2w: every N trading days
    calendar: Literal["month_start", "quarter_start", "half_year_start", "year_start"] | None = None


class Derived(BaseModel):
    as_of: date
    fx_pair: str = "USDKRW"
    fx_rate: float = Field(gt=0, description="KRW per USD at fx_date (1.0 if currency is USD)")
    fx_date: date
    fx_source: str = "db"
    initial_amount_usd: float
    monthly_contribution_usd: float
    rebalance_rule: RebalanceRule
    price_data_start: date
    price_data_end: date
    backtest_start: date
    backtest_end: date
    markets: list[str]
    warnings: list[str] = []
    # 백테스트 시작일 환율 (라운드 4 피드백): 백테스트의 초기 투자금·적립은 이 환율로 환산한다. 기준일 환율(fx_rate)은 '현재 구성' 배분액에 쓴다.
    backtest_fx_rate: float | None = None
    backtest_fx_date: date | None = None
    initial_amount_usd_at_backtest_start: float | None = None
    monthly_contribution_usd_at_backtest_start: float | None = None


class NormalizedRequest(UserRequest):
    stage: str = "01_request"
    derived: Derived
