"""분석 설정 한 곳 (module_mockup 의 portfolio_config·backtest_config·llm_config 통합).

- 상수는 dataclass 기본값. 실행마다 `AnalysisSettings.load()` 가 .env(환경변수)로 일부를 덮는다.
- 실행에 쓴 설정 전체는 `snapshot()` 으로 run_artifact.params 에 저장한다 (재현성, 요구 14).
- .env 읽기는 수집기와 같은 backend.adapters.crawlers.config.get 을 쓴다 (MYFINSIGHT_ENV / .env 파일).
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any, Literal

from backend.adapters.crawlers import config as env

LlmMode = Literal["stub", "api"]


@dataclass(frozen=True)
class MarketSettings:
    markets: tuple[str, ...] = ("US", "KR")  # 처음부터 미국 + 한국 (결정 D3)
    universes: tuple[str, ...] = ("SP500", "NASDAQ100", "KOSPI200")
    primary_benchmark_default: str = "SPY"
    kr_benchmark: str = "069500.KS"  # 한국 비중이 있으면 보조 지수로 자동 추가
    extra_benchmarks: tuple[str, ...] = ("QQQ",)
    calendar: Literal["union"] = "union"  # 혼합 시장 달력 = 거래일 합집합, 휴장일은 직전 종가 유지 (K16 1차)
    coverage_threshold: float = 0.95  # 품질 판정: 커버리지 0.95 통과, 0.9499 제외
    max_fill_days: int = 1  # 1거래일 결측만 직전값 채움, 2일 이상 연속 결측은 제외
    valuation_max_staleness_days: int = 10
    descriptor_universe: str = "ALL"
    descriptor_dir: str | None = None  # None -> backend/data/processed (build_descriptor.py 산출물)
    # 재무 지표(PER·ROE·배당) 자료가 시작되는 날 (docs/데이터_현황.md). 저PER·퀄리티·고배당 백테스트는 이 날 이후만 가능
    valuation_data_start: dict[str, str] = field(default_factory=lambda: {"US": "2010-04-01", "KR": "2005-06-01"})  # 자료가 "있는" 날이 아니라 종목 수가 충분해지는 날 (미국 PER 168종목, 한국 97종목)
    valuation_templates: tuple[str, ...] = ("low_per", "quality", "high_dividend")


@dataclass(frozen=True)
class PortfolioSettings:
    lookback_days: int = 756
    min_history_days_for_model: int = 252
    shrinkage: Literal["ledoit_wolf", "none"] = "ledoit_wolf"
    tau: float = 0.05
    risk_aversion: dict[str, float] = field(
        default_factory=lambda: {"conservative": 4.0, "moderate": 2.5, "aggressive": 1.5}
    )
    risk_aversion_mode: Literal["fixed", "market_implied"] = "market_implied"
    risk_aversion_mult: dict[str, float] = field(
        default_factory=lambda: {"conservative": 1.5, "moderate": 1.0, "aggressive": 0.7}
    )
    delta_floor: float = 1.5  # 급락이 추정 창에 들어가 δ가 지나치게 작아지는 문제 (MVP 결함 6)
    # 라운드 5: 허용 낙폭이 작을수록 δ(위험회피)를 키운다 — δ × clip(ref_tol / 허용 낙폭, 범위). 20% 가 기준(배수 1)
    delta_dd_ref_tol: float = 0.20
    delta_dd_mult_range: tuple[float, float] = (0.75, 1.5)
    min_weight: float = 0.01
    omega_method: str = "he_litterman_confidence"
    confidence_floor: float = 0.1
    abs_return_range: tuple[float, float] = (-0.5, 1.0)
    rel_return_range: tuple[float, float] = (0.0, 0.5)
    templates: tuple[str, ...] = ("equal_weight", "market_cap", "inverse_volatility", "min_variance")
    template_names_ko: dict[str, tuple[str, str]] = field(
        default_factory=lambda: {
            "equal_weight": ("동일비중", "모든 종목에 같은 비중 1/N"),
            "market_cap": ("시가총액비중", "시가총액에 비례한 비중 (지수 방식)"),
            "inverse_volatility": ("역변동성비중", "변동성이 낮은 종목에 더 큰 비중 (1/σ 정규화)"),
            "min_variance": ("최소분산", "포트폴리오 분산을 최소화하는 비중 (제약 포함 최적화)"),
        }
    )
    max_iter: int = 50
    # 정보 마감·체결 (결정 D4): 구성일 d 의 추정은 d 이전 자료만, 체결은 d 종가
    estimation_strict_before: bool = True


@dataclass(frozen=True)
class NewsSettings:
    window_days: int = 14  # 근거 창 [d - 14일, d)
    per_ticker: int = 10
    min_tickers: int = 3  # 뉴스가 이 수 미만의 종목에만 있으면 뷰를 만들지 않고 기준 비중 (K6)
    languages: tuple[str, ...] = ("en", "ko")  # 한국어 뉴스 포함 (K5)
    view_sets_at_start: int = 5
    view_sets_at_rebalance: int = 1
    views_per_set: int = 4


@dataclass(frozen=True)
class DisclosureSettings:
    """공시 사건을 뷰·근거로 쓰는 규칙 (라운드 4). 공시는 사건의 종류·시점만 알려 주므로 뉴스보다 긴 창을 쓰고, 공시만 근거인 뷰는 신뢰도를 낮게 묶는다."""

    enabled: bool = True
    window_days: int = 45  # 뷰(09)용 공시 창 [d−45, d). 사건이 드물어 14일이면 40% 종목만, 45일이면 약 80%
    summary_days: int = 90  # 06 기업 근거·14c 시장 분석용 사건 요약 창
    per_ticker: int = 8
    count_toward_min_tickers: bool = True  # 뉴스가 없어도 공시가 있으면 "근거 있는 종목" 으로 센다
    disclosure_only_max_confidence: float = 0.25  # 공시만 인용한 뷰의 신뢰도 상한
    include_amendments: bool = False
    event_types: tuple[str, ...] = (
        "earnings", "executive_change", "material_agreement", "agreement_termination", "buyback", "dividend", "merger_split", "merger_registration",
        "acquisition_disposition", "securities_offering", "capital_change", "control_change", "litigation", "rumor_response", "capex", "restructuring",
        "impairment", "bankruptcy", "restatement", "delisting_notice", "debt_acceleration", "auditor_change", "production_change", "tender_offer",
        "fair_disclosure", "cybersecurity",
    )
    # 90일 요약 건수에만 넣는 정기·절차 공시 (뷰 근거 아님)
    summary_extra_event_types: tuple[str, ...] = ("quarterly_report", "annual_report", "semiannual_report", "investor_relations", "reg_fd", "other_event", "voluntary_disclosure")
    # 명시 제외: derivative_offering(증권사 ELS 잡음 7.3만), offering_document, major_holder, proxy, related_party, shareholder_meeting, exhibits_only


@dataclass(frozen=True)
class BacktestSettings:
    commission_bps: float = 5
    integer_positions: bool = False
    risk_free_rate: float = 0.04
    trading_days: int = 252
    drift_tolerance: float = 0.25
    rebalance_trading_days: dict[str, int] = field(default_factory=lambda: {"2w": 10})
    checkpoint_freq: Literal["rebalance", "monthly"] = "rebalance"
    event_drawdown_levels: tuple[float, ...] = (-0.10, -0.20)
    save_daily_panel: bool = True
    view_horizon_days: int = 365
    vol_bands: dict[str, float] = field(default_factory=lambda: {"low": 0.15, "medium": 0.30, "high": 9.99})  # 비교지수 변동성이 없을 때의 절대 상한 (예비)
    # 변동성 규칙은 비교지수 대비 배수로 본다 (라운드 4 피드백): 안정 1.0배, 중립 1.3배, 적극은 상한 없음(정보만)
    vol_multipliers: dict[str, float | None] = field(default_factory=lambda: {"low": 1.0, "medium": 1.3, "high": None})
    target_window_min_ratio: float = 0.5  # 목표수익 규칙: 투자기간 길이의 모든 과거 구간 중 목표를 넘은 비율이 이 값 이상이면 통과
    min_invested_ratio: float = 0.9  # 투자 비율 정보 규칙: 상한 때문에 현금이 이보다 많이 남으면 알린다
    default_backtest_years: float = 3.0  # K2
    min_annualize_days: int = 378  # 라운드 5: 1.5년 미만 창은 연환산 KPI 대신 기간 수익률, R2/R7 은 참고
    min_invested_for_recommendation: float = 0.5  # 기준 구성의 투자 비율이 이보다 낮으면 결론 라벨 '구성 불충분'
    dd_excess_bucket: float = 0.05  # 추천 순위: 허용 낙폭 초과분을 이 단위(5%p) 구간으로 감점
    checkpoint_view_diagnostics: bool = False  # 체크포인트마다 뷰 진단을 다시 계산 (화면 미사용 → 기본 끔. 켜면 11 단계가 느려진다)


@dataclass(frozen=True)
class LlmSettings:
    mode: LlmMode = "stub"
    provider: str = "openai"
    model: str = "gpt-6-luna"
    temperature: float | None = None
    max_output_tokens: int = 8000
    reasoning_effort: str | None = None
    response_format_json: bool = True
    stage_overrides: dict[str, dict[str, Any]] = field(
        default_factory=lambda: {
            "04_classify": {"max_output_tokens": 6000},
            "09_views_news": {"max_output_tokens": 8000},  # 현재 구성은 세트 5×뷰 4 라 JSON 이 길다 (잘리면 두 배로 재시도)
            "14a_interpret": {"max_output_tokens": 8000},
            "14b_narrate": {"max_output_tokens": 10000},
        }
    )
    max_output_tokens_ceiling: int = 16000  # 잘린 응답 재시도 때 올릴 수 있는 상한
    timeout_s: int = 180
    retries: int = 3
    retry_backoff_max_s: int = 60  # 지수 백오프 상한 (지터 포함)
    max_concurrency: int = 4  # 동시 LLM 호출 상한 (리밸런싱 뷰·분류 배치·리포트 호출이 공유). env ANALYSIS_LLM_CONCURRENCY
    retry_backoff_s: int = 15
    cache: bool = True
    api_key_env: str = "OPENAI_API_KEY"
    pricing_usd_per_1m: dict[str, dict[str, float]] = field(
        default_factory=lambda: {
            "gpt-6-luna": {"input": 0.10, "cached_input": 0.01, "cache_write": 0.125, "output": 0.50},
        }
    )


@dataclass(frozen=True)
class SelectionSettings:
    """후보 검색 상한 (라운드 5). 넓은 테마(섹터 ≥ broad_theme_min_sectors 또는 GICS 없음)에서는 거래대금 대신 선정 지표 순으로 상한을 자른다."""

    max_candidates: int = 120
    broad_theme_min_sectors: int = 6
    metric_prefilter: bool = True


@dataclass(frozen=True)
class DialogSettings:
    max_questions: int = 5  # 설계보고서 요구 2: 1회 1항목, 최대 5회 (설정으로 조정)
    max_proposals_per_turn: int = 3
    # 코드 규칙 질문: 테마가 한 섹터에 몰려 있는데 섹터 상한이 그보다 작으면(현금이 크게 남음) 분석 전에 묻는다
    ask_sector_cap_conflict: bool = True
    # LLM 이 질문할 수 있는 필드 (SOFT 필드·기본값 필드). HARD 필드 중 값이 있는 것은 묻지 않는다.
    askable_fields: tuple[str, ...] = (
        "natural_language.idea",
        "strategy_preference.template",
        "strategy_preference.baseline_weighting",
        "strategy_preference.use_news_tilt",
        "constraints.universe",
        "constraints.num_holdings.target",
        "constraints.num_holdings",  # 실행 전 점검 질문: 후보 부족 시 종목 수 전체를 한 번에

        "constraints.exclude_sectors",
        "constraints.exclude_themes",
        "constraints.exclude_tickers",
        "constraints.must_include_tickers",
        "constraints.rebalance",
        "constraints.max_weight_per_stock",
        "constraints.max_weight_per_sector",
        "constraints.min_cash_ratio",
        "risk.benchmark",
        "risk.target_annual_return",
        "risk.max_drawdown_tolerance",
        "horizon.backtest_years",
        "horizon.start_date",  # 과거 특정 기간을 보고 싶을 때 (예: 2006~2016): 기준일 = 백테스트 끝
        "horizon",  # {start_date, backtest_years} 를 한 질문으로 (부분 갱신)
        "horizon.purpose",
        "capital.monthly_contribution",
    )


@dataclass(frozen=True)
class ReportSettings:
    sections: tuple[str, ...] = (
        "verdict",
        "market",
        "companies",
        "construction",
        "performance",
        "assumptions",
        "references",
    )
    strict_numbers: bool = False  # 숫자 대조 불일치를 오류로 (기본 경고)
    banned_phrases: tuple[str, ...] = ("보장", "확실한 수익", "무위험", "반드시 오른다", "손실 없음")
    max_series_points: int = 600  # 문서 시계열이 이보다 길면 stride 표본 + 첫/끝·최대낙폭 고점·저점 고정 (전체 해상도는 /reports/{id}/series)


@dataclass(frozen=True)
class ExecutorSettings:
    """병렬 실행 (라운드 4, 결정 R2 "병렬 실행만"). 결과값은 순차 실행과 같고 시간만 줄인다. env ANALYSIS_PARALLEL=0 이면 전부 순차."""

    max_parallel_stages: int = 3  # 의존이 끝난 단계 묶음(웨이브)을 동시에: 06·07·10f / 10·10w
    walkforward_workers: int = 0  # 10w 리밸런싱일 동시 처리 수 (0 = llm.max_concurrency)
    classify_workers: int = 0  # 04 분류 배치 동시 처리 수 (0 = llm.max_concurrency)
    parallel_report_calls: bool = True  # 14a(해석) ∥ 14c(시장) 동시 호출, 재시도는 오류 낸 호출만
    progress_min_interval_s: float = 1.5  # 긴 단계 "i/n" 진행 표시 최소 간격


@dataclass(frozen=True)
class TrackingSettings:
    """모의투자 (Module6)."""

    refresh_interval_s: int = 3600  # 일꾼이 한가할 때 진행 중인 모의투자를 이 간격으로 갱신
    refresh_on_worker_idle: bool = True


@dataclass(frozen=True)
class AnalysisSettings:
    market: MarketSettings = field(default_factory=MarketSettings)
    portfolio: PortfolioSettings = field(default_factory=PortfolioSettings)
    news: NewsSettings = field(default_factory=NewsSettings)
    backtest: BacktestSettings = field(default_factory=BacktestSettings)
    llm: LlmSettings = field(default_factory=LlmSettings)
    dialog: DialogSettings = field(default_factory=DialogSettings)
    selection: SelectionSettings = field(default_factory=SelectionSettings)
    report: ReportSettings = field(default_factory=ReportSettings)
    tracking: TrackingSettings = field(default_factory=TrackingSettings)
    disclosures: DisclosureSettings = field(default_factory=DisclosureSettings)
    executor: ExecutorSettings = field(default_factory=ExecutorSettings)
    pipeline_version: str = "analysis-1.0"

    @classmethod
    def load(cls, **overrides: Any) -> AnalysisSettings:
        """기본값 + .env(MYFINSIGHT_LLM, ANALYSIS_MAX_QUESTIONS, ANALYSIS_LLM_MODEL) + 명시 덮어쓰기.

        LLM 모드: MYFINSIGHT_LLM 이 있으면 그 값, 없으면 OPENAI_API_KEY 가 있을 때 api, 아니면 stub(연습)."""
        s = cls()
        llm_kw: dict[str, Any] = {}
        mode = env.get("MYFINSIGHT_LLM")
        if mode in ("stub", "api"):
            llm_kw["mode"] = mode
        elif env.get(s.llm.api_key_env):
            llm_kw["mode"] = "api"  # 모드를 안 적었어도 API 키가 있으면 실제 LLM (연습 모드는 MYFINSIGHT_LLM=stub 로 명시)
        model = env.get("ANALYSIS_LLM_MODEL")
        if model:
            llm_kw["model"] = model
        if env.get("MYFINSIGHT_LLM_CACHE") == "0":
            llm_kw["cache"] = False
        conc = env.get("ANALYSIS_LLM_CONCURRENCY")
        if conc.isdigit() and int(conc) >= 1:
            llm_kw["max_concurrency"] = int(conc)
        if llm_kw:
            s = replace_settings(s, llm=replace_settings(s.llm, **llm_kw))
        mq = env.get("ANALYSIS_MAX_QUESTIONS")
        if mq.isdigit():
            s = replace_settings(s, dialog=replace_settings(s.dialog, max_questions=int(mq)))
        ddir = env.get("ANALYSIS_DESCRIPTOR_DIR")
        if ddir:
            s = replace_settings(s, market=replace_settings(s.market, descriptor_dir=ddir))
        if env.get("ANALYSIS_PARALLEL") == "0":  # 디버깅·결정론 확인용: 전부 순차
            s = replace_settings(s, executor=ExecutorSettings(max_parallel_stages=1, walkforward_workers=1, classify_workers=1, parallel_report_calls=False))
        mps = env.get("ANALYSIS_MAX_PARALLEL_STAGES")
        if mps.isdigit() and int(mps) >= 1:
            s = replace_settings(s, executor=replace_settings(s.executor, max_parallel_stages=int(mps)))
        mk = env.get("ANALYSIS_MARKETS")
        if mk:
            s = replace_settings(s, market=replace_settings(s.market, markets=tuple(x.strip() for x in mk.split(",") if x.strip())))
        if overrides:
            s = replace_settings(s, **overrides)
        return s

    def snapshot(self) -> dict[str, Any]:
        """run_artifact.params 에 넣는 전체 설정 (JSON 직렬화 가능)."""
        d = asdict(self)
        d["llm"].pop("api_key_env", None)
        return d


def replace_settings(obj: Any, **changes: Any) -> Any:
    from dataclasses import replace

    return replace(obj, **changes)
