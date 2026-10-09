"""Pydantic schemas for every stage boundary of the mock-up pipeline.

Each stage validates its output with the matching model before writing it, so the JSON files
in output/ are guaranteed to be consumable by the next stage (and by the LLM stubs).
"""
from __future__ import annotations
from datetime import date
from typing import Literal, Optional
from pydantic import BaseModel, Field, model_validator, field_validator

RebalanceUnit = Literal["2w", "1m", "1q", "6m", "1y"]
Template = Literal["low_per", "quality", "momentum", "low_volatility", "high_dividend"]
Weighting = Literal["equal_weight", "market_cap", "inverse_volatility", "min_variance"]
RiskTolerance = Literal["conservative", "moderate", "aggressive"]

TEMPLATE_METRICS: dict[str, tuple[str, str]] = {
    # template -> (metric, direction)
    "low_per": ("pe_ttm", "asc"),
    "quality": ("roe_ttm", "desc"),
    "momentum": ("return_12m_1m", "desc"),
    "low_volatility": ("vol_60d", "asc"),
    "high_dividend": ("dividend_yield_ttm", "desc"),
}


# ───────────────────────── stage 0/1: user request ─────────────────────────
class Profile(BaseModel):
    user_id: str
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
    start_date: date
    target_years: float = Field(gt=0)
    purpose: Literal["wealth_growth", "income", "capital_preservation", "retirement"]


class Risk(BaseModel):
    risk_tolerance: RiskTolerance
    max_drawdown_tolerance: float = Field(gt=0, le=1)
    loss_reaction: Literal["sell", "hold", "buy_more"]
    target_annual_return: float
    benchmark: str


class NumHoldings(BaseModel):
    target: int = Field(ge=1)
    min: int = Field(ge=1)
    max: int = Field(ge=1)

    @model_validator(mode="after")
    def _order(self):
        if not (self.min <= self.target <= self.max):
            raise ValueError(f"num_holdings must satisfy min <= target <= max, got {self.min}/{self.target}/{self.max}")
        return self


class Rebalance(BaseModel):
    count: int = Field(ge=0, description="0 = no rebalancing")
    unit: RebalanceUnit


class Constraints(BaseModel):
    universe: list[Literal["SP500", "NASDAQ100"]] = Field(min_length=1)
    asset_types: list[Literal["stock", "etf"]] = Field(min_length=1)
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
    def _feasible(self):
        # equal weight with the fewest allowed holdings must still respect the per-stock cap
        if self.max_weight_per_stock * self.num_holdings.min < 1 - 1e-9:
            raise ValueError("max_weight_per_stock x num_holdings.min < 1: weights cannot sum to 1")
        if self.max_weight_per_sector < self.max_weight_per_stock:
            raise ValueError("max_weight_per_sector must be >= max_weight_per_stock")
        if len(self.must_include_tickers) > self.num_holdings.max:
            raise ValueError("more must_include_tickers than num_holdings.max")
        clash = set(self.must_include_tickers) & set(self.exclude_tickers)
        if clash:
            raise ValueError(f"tickers both included and excluded: {sorted(clash)}")
        return self


class StrategyPreference(BaseModel):
    template: Template
    baseline_weighting: Weighting
    use_news_tilt: bool = False


class NaturalLanguage(BaseModel):
    idea: str = Field(min_length=5)
    language: str = "ko"


class UserRequest(BaseModel):
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
    trading_days: Optional[int] = None          # for 2w: every N trading days
    calendar: Optional[Literal["month_start", "quarter_start", "half_year_start", "year_start"]] = None


class Derived(BaseModel):
    as_of: date
    fx_pair: str
    fx_rate: float = Field(gt=0, description="KRW per USD at fx_date (1.0 if currency is USD)")
    fx_date: date
    initial_amount_usd: float
    monthly_contribution_usd: float
    rebalance_rule: RebalanceRule
    price_data_start: date
    price_data_end: date


class NormalizedRequest(UserRequest):
    stage: str = "01_request"
    derived: Derived


# ───────────────────────── stage 2: intent (LLM #1) ─────────────────────────
def _check_gics_codes(codes: list[str]) -> list[str]:
    for c in codes:
        if not (c.isdigit() and len(c) in (2, 4, 6, 8)):
            raise ValueError(f"GICS code must be 2/4/6/8 digits, got {c!r}")
    return codes


class Theme(BaseModel):
    id: str = Field(pattern=r"^[a-z0-9_]+$")
    label_ko: str
    description_ko: str
    gics_codes: list[str] = []
    keywords: list[str] = []
    example_tickers: list[str] = []
    _v = field_validator("gics_codes")(_check_gics_codes)


class ExcludeThemeRule(BaseModel):
    theme: str
    gics_codes: list[str] = []
    keywords: list[str] = []
    _v = field_validator("gics_codes")(_check_gics_codes)


class Conflict(BaseModel):
    field: str
    issue_ko: str
    resolution_ko: str


class Interpretation(BaseModel):
    summary_ko: str
    themes: list[Theme] = Field(min_length=1)
    style_hints: list[str] = []
    conflicts: list[Conflict] = []


class ThemeFilter(BaseModel):
    min_confidence: float = Field(ge=0, le=1, default=0.5)


class Screen(BaseModel):
    template: Template
    metric: str
    direction: Literal["asc", "desc"]
    as_of: date
    theme_filter: ThemeFilter = ThemeFilter()
    select_top_n: int = Field(ge=1)

    @model_validator(mode="after")
    def _metric_matches_template(self):
        m, d = TEMPLATE_METRICS[self.template]
        if (self.metric, self.direction) != (m, d):
            raise ValueError(f"template {self.template} requires metric={m}, direction={d}")
        return self


class RiskParams(BaseModel):
    risk_tolerance: RiskTolerance
    effective_max_drawdown: float = Field(gt=0, le=1)
    volatility_preference: Literal["low", "medium", "high"]
    notes_ko: str = ""


class NewsTilt(BaseModel):
    enabled: bool
    max_view_confidence: float = Field(ge=0, le=1)
    max_tilt_per_stock: float = Field(ge=0, le=1)


class ValidationCriteria(BaseModel):
    benchmark: str
    max_drawdown: float
    target_annual_return: float
    horizon_years: float


class ReportSettings(BaseModel):
    language: str = "ko"
    explanation_level: Literal["beginner", "intermediate", "expert"]


class IntentSpec(BaseModel):
    request_id: str
    stage: str = "02_intent"
    spec_version: str = "1.0"
    interpretation: Interpretation
    exclude_theme_rules: list[ExcludeThemeRule] = []
    screen: Screen
    risk_params: RiskParams
    news_tilt: NewsTilt
    validation_criteria: ValidationCriteria
    report_settings: ReportSettings
    warnings: list[str] = []


# ───────────────────────── descriptor / stage 3: candidates ─────────────────────────
class GicsLevel(BaseModel):
    code: str
    name: str


class Gics(BaseModel):
    sector: GicsLevel
    industry_group: GicsLevel
    industry: GicsLevel
    sub_industry: GicsLevel


class Company(BaseModel):
    name: str
    indices: list[str]
    gics: Gics
    keywords: list[str] = []
    company_summary: str
    sources: dict[str, str] = {}


class Descriptor(BaseModel):
    meta: dict
    taxonomy_counts: dict[str, dict[str, int]]
    companies: dict[str, Company]


class Candidate(BaseModel):
    ticker: str
    name: str
    gics: Gics
    company_summary: str
    market_cap_usd: Optional[float] = None
    adv_usd: Optional[float] = None
    matched_by: list[str]
    matched_themes: list[str]
    forced: bool = False


class FilteredOut(BaseModel):
    ticker: str
    reason: str


class Candidates(BaseModel):
    request_id: str
    stage: str = "03_candidates"
    as_of: date
    candidates: list[Candidate]
    filtered_out: list[FilteredOut] = []
    stats: dict
    warnings: list[str] = []


# ───────────────────────── stage 4: tagging (LLM #2) ─────────────────────────
class TagResult(BaseModel):
    ticker: str
    in_theme: bool
    themes: list[str] = []
    confidence: float = Field(ge=0, le=1)
    reason_ko: str
    excluded_theme: Optional[str] = None


class Tagging(BaseModel):
    request_id: str
    stage: str = "04_tagging"
    min_confidence: float
    tagged: list[TagResult]
    excluded_by_theme: list[TagResult] = []
    passed_tickers: list[str]
    batches: int
    warnings: list[str] = []


# ───────────────────────── stage 5: selection ─────────────────────────
class Selected(BaseModel):
    ticker: str
    name: str
    sector: str
    sector_code: str
    rank: int
    metric_name: str
    metric_value: float
    theme_confidence: Optional[float] = None
    forced: bool = False


class Rejected(BaseModel):
    ticker: str
    reason: str
    metric_value: Optional[float] = None


class Selection(BaseModel):
    request_id: str
    stage: str = "05_selection"
    selected: list[Selected]
    rejected: list[Rejected] = []
    summary: dict
    warnings: list[str] = []


# ───────────────────────── stage 7: backtest request / spec ─────────────────────────
class Confirmation(BaseModel):
    selection_confirmed: bool
    removed_tickers: list[str] = []
    added_tickers: list[str] = []


class BacktestWindow(BaseModel):
    start_date: date
    end_date: date
    reselect_at_start: bool = True
    benchmark: Optional[str] = None
    include_contributions: bool = True

    @model_validator(mode="after")
    def _order(self):
        if self.start_date >= self.end_date:
            raise ValueError("backtest.start_date must be before end_date")
        return self


class ViewsConfig(BaseModel):
    n_sets: int = Field(ge=1, le=10, default=5)
    views_per_set: int = Field(ge=1, le=8, default=4)


class BacktestRequest(BaseModel):
    request_id: str
    confirmation: Confirmation
    backtest: BacktestWindow
    views: ViewsConfig = ViewsConfig()


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


class BacktestSpec(BaseModel):
    request_id: str
    stage: str = "07_backtest_spec"
    period: Period
    capital: CapitalSpec
    rebalance_rule: RebalanceRule
    benchmark: str
    selection: SelectionSpec
    warnings: list[str] = []


# ───────────────────────── stage 8/10: market model, portfolios ─────────────────────────
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
    scenario_id: Optional[str] = None
    title_ko: Optional[str] = None
    portfolio_view: Optional[str] = None
    views_applied: list[dict] = []
    delta_vs_baseline: dict[str, float] = {}
    posterior_returns: dict[str, float] = {}
    active_constraints: list[str] = []

    @model_validator(mode="after")
    def _sums(self):
        tot = sum(self.weights.values()) + self.cash_weight
        if abs(tot - 1) > 1e-4:
            raise ValueError(f"portfolio {self.id}: weights + cash = {tot:.6f}, expected 1")
        if min(self.weights.values()) < -1e-9:
            raise ValueError(f"portfolio {self.id}: negative weight")
        return self


class BaselinePortfolios(BaseModel):
    request_id: str
    stage: str = "08_baseline_portfolios"
    as_of: date
    chosen_baseline: str
    portfolios: list[Portfolio]


# ───────────────────────── stage 9: views (LLM #4) ─────────────────────────
class View(BaseModel):
    type: Literal["absolute", "relative"]
    long: list[str] = Field(min_length=1)
    short: list[str] = []
    expected_return_annual: float
    confidence: float = Field(gt=0, le=1)
    horizon_months: int = Field(ge=1, le=60, default=12)
    rationale_ko: str
    evidence_type: str = "llm_placeholder"

    @model_validator(mode="after")
    def _shape(self):
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
    hindsight_risk: bool = True
    max_view_confidence: float
    sets: list[ViewSet] = Field(min_length=1)
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


# ───────────────────────── stage 11: backtest results ─────────────────────────
class CheckpointWeights(BaseModel):
    target: dict[str, float]
    before: Optional[dict[str, float]] = None
    after: dict[str, float]
    cash_before: Optional[float] = None
    cash_after: float


class Checkpoint(BaseModel):
    seq: int
    date: date
    kind: Literal["rebalance", "closing", "monthly"]
    n_trading_days_to_date: int
    weights: CheckpointWeights
    drift: Optional[dict] = None
    holdings: list[dict]
    trades: list[dict] = []
    turnover: Optional[float] = None
    commission_usd: float = 0.0
    money: dict
    since_last: Optional[dict] = None
    to_date: Optional[dict] = None
    view_diagnostics_to_date: list[dict] = []


class PortfolioResult(BaseModel):
    id: str
    kind: Literal["black_litterman", "template", "benchmark"]
    name_ko: str
    title_ko: Optional[str] = None
    portfolio_view: Optional[str] = None
    target_weights: dict[str, float]
    headline: dict
    metrics: dict
    money: dict
    series: dict[str, list]
    monthly_returns: list[dict]
    yearly_returns: dict[str, Optional[float]]
    checkpoints: list[Checkpoint]
    contribution_ledger: list[dict] = []
    events: list[dict] = []
    ticker_contribution: dict[str, Optional[float]] = {}
    ticker_total_return: dict[str, Optional[float]] = {}
    view_diagnostics: list[dict] = []

    @model_validator(mode="after")
    def _lengths(self):
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
    portfolios: list[PortfolioResult]
    ranking: list[dict]
    reproducibility: dict
    warnings: list[str] = []

    @model_validator(mode="after")
    def _aligned(self):
        n = len(self.series_dates)
        for p in [self.benchmark, *self.portfolios]:
            for k, v in p.series.items():
                if len(v) != n:
                    raise ValueError(f"{p.id}.series.{k} length {len(v)} != {n}")
        return self


# ───────────────────────── stage 12: validation ─────────────────────────
class Check(BaseModel):
    rule: str
    name_ko: str
    level: Literal["hard", "soft"]
    status: Literal["pass", "warn", "fail"]
    value: Optional[float] = None
    threshold: Optional[float] = None
    message_ko: str


class ValidationResult(BaseModel):
    id: str
    kind: str
    status: Literal["pass", "warn", "fail"]
    checks: list[Check]
    n_fail: int
    n_warn: int


class Validation(BaseModel):
    request_id: str
    stage: str = "12_validation"
    criteria: dict
    results: list[ValidationResult]
    comparison_table: list[dict]
    recommended: Optional[dict] = None
    summary: dict
    warnings: list[str] = []


# ───────────────────────── stage 13: consolidated results ─────────────────────────
class ResultsBundle(BaseModel):
    request_id: str
    stage: str = "13_results"
    generated_at: str
    pipeline_version: str
    request: dict
    intent: dict
    selection: dict
    portfolio: dict
    backtest: dict
    validation: dict
    money_krw: dict
    llm_usage: dict
    sources: list[dict]
    parameters: dict
    warnings: list[dict] = []

    @model_validator(mode="after")
    def _consistency(self):
        n = len(self.backtest["series_dates"])
        for p in [self.backtest["benchmark"], *self.backtest["portfolios"]]:
            for k, v in p["series"].items():
                if len(v) != n:
                    raise ValueError(f"backtest.{p['id']}.series.{k} length {len(v)} != {n}")
        ids = {p["id"] for p in self.backtest["portfolios"]}
        if ids != {t["id"] for t in self.portfolio["targets"]["portfolios"] + self.portfolio["targets"]["templates"]}:
            raise ValueError("backtest portfolios != target portfolios")
        if set(self.money_krw["by_portfolio"]) != ids | {self.backtest["benchmark"]["id"]}:
            raise ValueError("money_krw.by_portfolio must cover every portfolio and the benchmark")
        return self


# ───────────────────────── stage 14: report document (block model) ─────────────────────────
BLOCK_TYPES = {"paragraphs", "kpis", "table", "donut", "line", "area", "bar", "funnel", "callout", "cards", "checkpoints", "glossary"}


class Section(BaseModel):
    id: str
    title_ko: str
    blocks: list[dict] = Field(min_length=1)

    @field_validator("blocks")
    @classmethod
    def _types(cls, v):
        for b in v:
            if b.get("type") not in BLOCK_TYPES:
                raise ValueError(f"unknown block type {b.get('type')!r}")
        return v


class ReportDoc(BaseModel):
    request_id: str
    stage: str = "14_report"
    generated_at: str
    source: str
    header: dict
    kpis: list[dict]
    nav: list[dict]
    sections: list[Section] = Field(min_length=1)
    datasets: dict
    assessment: dict
    sources: list[dict]
    parameters: dict
    warnings: list[str] = []

    @model_validator(mode="after")
    def _refs(self):
        n = len(self.datasets["dates"])
        for sid, s in self.datasets["series"].items():
            for k in ("index", "value_usd", "drawdown"):
                if k in s and len(s[k]) != n:
                    raise ValueError(f"datasets.series.{sid}.{k} length {len(s[k])} != {n}")
        kpi_ids = {k["id"] for k in self.kpis}
        for sec in self.sections:
            for b in sec.blocks:
                if b["type"] == "kpis" and not set(b["ids"]) <= kpi_ids:
                    raise ValueError(f"section {sec.id}: unknown kpi ids {set(b['ids']) - kpi_ids}")
                if b["type"] in ("line", "area") and not set(b["series_ids"]) <= set(self.datasets["series"]):
                    raise ValueError(f"section {sec.id}: unknown series ids")
        if {s.id for s in self.sections} != {n_["id"] for n_ in self.nav}:
            raise ValueError("nav ids must match section ids")
        return self
