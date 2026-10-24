# MyFinSight 프로토타입 모듈 명세 & 분배

<aside>
📌

**범위:** LLM 없이 고정 Profile·고정 Spec → Universe 필터 → 가격 수집 → 전략 실행 → Backtest → 텍스트 Report(근거 포함)

**추적:** UC → R → FR → F → 모듈. 원본: 프로젝트 문서 `claude/모듈명세_프로토타입.md` (v1, 2026-10-02)

**모듈 ID:** M{기능번호 2자리}-{순번 2자리}. 00 = 공통 기반, 01 = F1 … 08 = F8 (F7은 프로토타입 범위 밖). 🔶 = 팀 확인 필요

</aside>

# 1. 전체 모듈 목록

| F | ID | 모듈 | FR |
| --- | --- | --- | --- |
| 공통 | M00-01 | 설정 (Config) | FR12 |
| 공통 | M00-02 | 도메인 스키마 + 공통 오류 | 전체 |
| F1 | M01-01 | Profile 로더·검증기 | FR01 |
| F2 | M02-01 | 가격 수집 어댑터 | FR04 |
| F2 | M02-02 | 데이터 정규화기 | FR04 |
| F2 | M02-03 | 데이터 품질 판정기 | FR05 |
| F2 | M02-04 | 시장 데이터 Repository | FR04 |
| F2 | M02-05 | 지수 구성종목 수집기 | FR04 |
| F3 | M03-01 | 종목 선정 규칙 | FR08 |
| F3 | M03-02 | 비중 결정 규칙 | FR08 |
| F3 | M03-03 | 제약 적용 규칙 | FR08 |
| F3 | M03-04 | 전략 실행기 (Mapper) | FR08, FR10 |
| F3 | M03-05 | Universe 구성기 | FR08 |
| F4 | M04-01 | Spec 정적 검증기 | FR09 |
| F4 | M04-02 | 비중 동적 검증기 | FR09 |
| F4 | M04-03 | 일치성 검사기 | FR10, FR25 |
| F5 | M05-01 | Backtest 시뮬레이터 | FR11, FR12 |
| F5 | M05-02 | 성과 지표 계산기 | FR11 |
| F5 | M05-03 | 무위험수익률 제공자 | FR12 |
| F6 | M06-01 | 근거 생성기 | FR26 |
| F6 | M06-02 | Report 조립기 | FR14 |
| F8 | M08-01 | 실행 기록기 (Run Logger) | FR24 |
| F8 | M08-02 | 파이프라인 실행기 | FR24, FR25 |

## 실행 흐름

```
M08-02 시작 (run_id 발급, M08-01 기록 시작)
 1. M00-01 설정 로드 → M01-01 Profile 로드·검증 → Spec 파일 로드 → M04-01 Spec 정적 검증
 2. M02-05 구성종목 스냅샷 확인(분기 갱신 필요 시 수집) → M03-05 Universe 필터링
 3. M02-01 가격 수집(M02-04 캐시 우선) → M02-02 정규화 → M02-04 저장 → M02-03 품질 판정(제외 목록)
 4. M03-04 기준일 비중 산출(M03-01→M03-03→M03-02→M03-03) → M04-02 동적 검증
 5. M05-01 Backtest(리밸런싱마다 M03-04·M04-02 호출, M05-03 무위험수익률) → M05-02 지표
 6. M06-01 근거 생성 → M06-02 Report 조립 → M04-03 일치성 검사 → Report 저장·출력
 (모든 단계: M08-02가 M08-01로 시작·종료·성공/실패 기록, 필수 실패 시 중단)
```

## 권장 디렉터리 구조

```
myfinsight/
  config/            config.toml, industry_map.toml
  inputs/            profile.json, spec.json
  src/myfinsight/
    config.py        # M00-01
    schemas/         # M00-02 (profile.py, spec.py, market.py, results.py, report.py, runlog.py, errors.py)
    profile/         # M01-01
    data/            # M02-01 adapters/, M02-02 normalizer.py, M02-03 quality.py, M02-04 repository/, M02-05 constituents.py
    strategy/        # M03-01 selection.py, M03-02 weighting.py, M03-03 constraints.py, M03-04 executor.py, M03-05 universe.py
    validation/      # M04-01 spec_validator.py, M04-02 weight_validator.py, M04-03 consistency.py
    backtest/        # M05-01 simulator.py, M05-02 metrics.py, M05-03 riskfree.py
    report/          # M06-01 evidence.py, M06-02 assembler.py, templates/
    runtime/         # M08-01 runlog.py, M08-02 pipeline.py, cli.py
  tests/             # 모듈별 단위 테스트 + 통합 테스트(네트워크 없음)
```

## 추적표 (모듈 → FR → R → UC)

| 모듈 | FR | R | UC |
| --- | --- | --- | --- |
| M01-01 | FR01 | R1 | UC001 |
| M02-01, M02-02, M02-04, M02-05 | FR04 | R3 | UC-C 1~2 |
| M02-03 | FR05 | R3 | UC-C 2 |
| M03-01~M03-04, M03-05 | FR08 (M03-04: +FR10) | R4 | UC-C 3·5·7 |
| M04-01, M04-02 | FR09 | R5 | UC-C 6·7 |
| M04-03 | FR10, FR25 | R5 | UC-C 10 |
| M05-01, M05-02, M05-03, M00-01 | FR11, FR12 | R6 | UC-C 8 |
| M06-02 | FR14 | R7 | UC003 |
| M06-01 | FR26 | R8 | UC003 |
| M08-01, M08-02 | FR24 (M08-02: +FR25) | R9 | UC003, UC-C |

# 2. 모듈별 상세 명세

## 공통 제약 (모든 모듈)

| ID | 제약 |
| --- | --- |
| C-01 | Python **3.11**. 의존성은 `pyproject.toml`에 버전 범위 고정 (예: pydantic>=2.6,<3 / pandas>=2.1,<3 / numpy>=1.26,<2.1 / yfinance 최신 고정 / SQLAlchemy>=2.0,<2.1 / pytest) |
| C-02 | 모든 모듈 간 데이터는 **M00-02 스키마**로만 주고받는다. 예외: 가격 행렬은 0-4의 「PriceFrame 계약」을 따르는 pandas DataFrame |
| C-03 | **결정론**: 난수 사용 금지. 동순위는 티커 오름차순으로 정렬. 같은 입력(Spec·데이터·설정)이면 결과가 비트 단위까지는 아니어도 소수 6자리까지 동일 |
| C-04 | **통화**: 계산은 USD. 원화는 표시용으로만 M00-01의 환율 심볼(KRW=X) 기준일 값으로 환산하고 환율·기준일을 함께 표시 |
| C-05 | **날짜·시각**: 거래일은 `date`(미국 동부 거래소 기준일). 기록 시각(fetched_at, started_at 등)은 UTC `datetime`(ISO 8601) |
| C-06 | **선견 금지**: 날짜 t의 비중 계산에는 t-1 거래일 종가까지의 데이터만 쓴다 |
| C-07 | **수치 생성 금지(FR05)**: Report·근거의 모든 수치는 계산 결과나 저장 데이터에서만 가져온다. 결측 보간은 연속 1거래일 직전값 채우기만 허용 |
| C-08 | **LLM 미사용**: 프로토타입에서 어떤 모듈도 LLM을 호출하지 않는다. 생성 코드 실행 금지(C005) |
| C-09 | **오류**: 모든 실패는 M00-02의 `MyFinSightError` 하위 예외로 던지고 `code`를 붙인다(부록 C). 모듈 내부에서 예외를 삼키고 성공처럼 반환하지 않는다 |
| C-10 | **저장소 독립**: DB 접근은 M02-04 Repository 인터페이스로만 한다. SQL을 다른 모듈에 쓰지 않는다 (PostgreSQL 교체 대비) |
| C-11 | **네트워크 격리 테스트**: 단위·통합 테스트는 네트워크 없이 돈다. 외부 호출 모듈(M02-01, M02-05)은 가짜(Fake) 구현을 함께 제공한다 |
| C-12 | **로깅**: 표준 `logging` 사용, print 금지(CLI 출력 제외). 사용자용 실행 기록은 M08-01 |
| C-13 | 코드 스타일: 타입 힌트 필수, `ruff` 통과, 공개 함수 docstring |

### 0-4. PriceFrame 계약 (pandas)

- index: `DatetimeIndex`(tz 없음, 거래일, 오름차순, 중복 없음), name=`date`
- columns: 티커 문자열(yfinance 표기, 예 `BRK-B`), 정렬
- values: `float64` 수정종가(USD). 결측은 `NaN`(M02-03 이후에는 결측 없음)
- 함께 전달하는 메타: `PriceMeta`(M00-02) — 출처, 기준일, 수집시각

## 공통 기반 (M00)

### M00-01 설정 (Config)

- **FR:** FR12 (계산 조건을 설정으로 정의·기록)
- **Input:** `config/config.toml`, `config/industry_map.toml` (경로는 CLI 인자 또는 기본값). 환경변수 `MYFINSIGHT_*`로 개별 값 덮어쓰기 허용
- **Process:** 파일 읽기 → `AppConfig`(Pydantic) 검증 → 읽기 전용 객체로 반환
- **Output:** `AppConfig`
- **스키마**
    
    ```python
    class BacktestSettings(BaseModel):
        period_years: int = Field(5, ge=1, le=20)
        rebalance: Literal["Q"] = "Q"                 # 프로토타입은 분기만
        rebalance_anchor: Literal["first_trading_day"] = "first_trading_day"  # 🔶K2
        benchmark: str = "SPY"
        allowed_benchmarks: list[str] = ["SPY", "QQQ"]
        cost_bps: float = Field(10.0, ge=0, le=200)   # 편도 0.1% = 10bp
        trading_days_per_year: int = 252
    
    class RiskFreeSettings(BaseModel):
        provider: Literal["fixed"] = "fixed"          # 추후 "treasury"
        annual_rate: float = Field(0.0, ge=0, le=0.2) # 🔶K1 팀이 값 결정
    
    class DataSettings(BaseModel):
        db_url: str = "sqlite:///data/myfinsight.db"
        price_source: Literal["yfinance"] = "yfinance"
        fx_symbol: str = "KRW=X"                      # USD/KRW
        coverage_threshold: float = Field(0.95, gt=0, le=1)
        max_fill_days: int = Field(1, ge=0, le=1)
        retry_max: int = Field(3, ge=0, le=10)        # M02-01 재시도 기본값
        retry_backoff_sec: float = 1.0                # 1, 2, 4초…
        cache_max_age_days: int = 1                   # 마지막 거래일 데이터가 있으면 재수집 안 함
    
    class UniverseSettings(BaseModel):
        indices: list[Literal["SP500", "NDX"]] = ["SP500", "NDX"]
        max_size: int = Field(60, ge=5, le=200)       # 🔶K5
        industry_map_path: str = "config/industry_map.toml"
    
    class AppConfig(BaseModel):
        model_config = ConfigDict(frozen=True)
        backtest: BacktestSettings
        risk_free: RiskFreeSettings
        data: DataSettings
        universe: UniverseSettings
        industry_map: dict[str, list[str]]            # 관심산업 → GICS industry 목록 (🔶K3)
    ```
    
- **성공·평가 기준:** 기본값만으로 로드 성공 / 범위 밖 값(예: cost_bps=-1)은 `ConfigError` / 같은 파일이면 같은 객체(동등성) / 로드된 설정 전체를 Report의 「계산 조건」에 그대로 출력할 수 있음
- **제약:** 실행 중 변경 불가(frozen). 비밀값(API 키)은 프로토타입에 없음
- **오류:** `CONFIG_INVALID`, `CONFIG_NOT_FOUND`

### M00-02 도메인 스키마 + 공통 오류

- **FR:** 전체 (모듈 간 계약)
- **Input / Output:** 없음 (다른 모듈이 import)
- **Process:** Pydantic v2 모델과 Enum, 예외 클래스 정의. 모든 모델 `model_config = ConfigDict(extra="forbid")`
- **스키마**
    
    ```python
    # ---------- Enum ----------
    class RiskType(str, Enum):           # 금융권 5단계 (UC001)
        STABLE = "안정형"; STABLE_SEEKING = "안정추구형"; NEUTRAL = "위험중립형"
        ACTIVE = "적극투자형"; AGGRESSIVE = "공격투자형"
    
    class SelectionRule(str, Enum):  FIXED_LIST = "fixed_list"; LOW_VOL_TOP_N = "low_volatility_top_n"; MOMENTUM_TOP_N = "momentum_top_n"
    class WeightingRule(str, Enum):  EQUAL = "equal"; INVERSE_VOL = "inverse_volatility"
    class StepStatus(str, Enum):     STARTED="STARTED"; SUCCESS="SUCCESS"; PARTIAL="PARTIAL"; FAILED="FAILED"; SKIPPED="SKIPPED"
    class DataStatus(str, Enum):     OK="OK"; FILLED="FILLED"; EXCLUDED="EXCLUDED"
    class IndexCode(str, Enum):      SP500="SP500"; NDX="NDX"
    
    # ---------- Profile (UC001, 부록 A-1) ----------
    class ProfileConstraints(BaseModel):
        exclude_tickers: list[str] = []
        max_weight_all: float = Field(1.0, ge=0.05, le=1.0)
        max_weight_per_ticker: dict[str, float] = {}       # 값 0~1
        allow_etf: bool = False
    
    class UserProfile(BaseModel):
        profile_id: str
        investment_amount_krw: int = Field(gt=0)
        horizon_months: int = Field(ge=12, le=120)
        risk_type_computed: RiskType
        risk_type: RiskType                                 # 최종(사용자 변경 가능)
        risk_type_overridden: bool
        loss_tolerance_pct: float = Field(gt=0, le=100)     # 예: 30 → -30%까지 감내
        interest_industries: list[str] = []                 # industry_map 키
        preferences: list[str] = []                         # 성장/가치/배당/대형주
        memo: str | None = None
        constraints: ProfileConstraints = ProfileConstraints()
        market: Literal["US"] = "US"
    
    # ---------- Strategy Spec (FR08) ----------
    class SelectionSpec(BaseModel):
        rule: SelectionRule
        params: dict[str, Any] = {}       # fixed_list: {"tickers":[...]} / top_n: {"n":5,"lookback_days":252[,"skip_days":21]}
    
    class WeightingSpec(BaseModel):
        rule: WeightingRule
        params: dict[str, Any] = {}       # inverse_volatility: {"lookback_days":252}
    
    class ConstraintSpec(BaseModel):
        exclude_tickers: list[str] = []
        max_weight_all: float = Field(1.0, gt=0, le=1.0)
        max_weight_per_ticker: dict[str, float] = {}
    
    class UniverseSpec(BaseModel):
        mode: Literal["dynamic", "fixed"] = "dynamic"  # dynamic: M03-05 / fixed: tickers 그대로
        tickers: list[str] = []
    
    class StrategySpec(BaseModel):
        spec_id: str
        name: str
        version: int = 1
        universe: UniverseSpec
        selection: SelectionSpec
        weighting: WeightingSpec
        constraints: ConstraintSpec
        rebalance: Literal["Q"] = "Q"
        period_years: int = Field(ge=1, le=20)
        benchmark: str
        def spec_hash(self) -> str: ...   # 정렬된 JSON의 SHA-256 (FR10 일치 확인용)
    
    # ---------- 시장 데이터 ----------
    class RawPriceBatch(BaseModel):          # M02-01 출력 (원본 보존)
        source: str; requested_tickers: list[str]; start: date; end: date
        fetched_at: datetime; payload: dict[str, Any]   # 원본 응답(JSON 직렬화 가능 형태)
        failed_tickers: dict[str, str] = {}             # 티커 → 실패 사유
    
    class PriceBar(BaseModel):               # M02-02 출력 행
        ticker: str; date: date; adj_close: float = Field(gt=0); volume: int | None = Field(None, ge=0)
        currency: Literal["USD"] = "USD"; source: str; fetched_at: datetime
    
    class FxRate(BaseModel):                 # 환율 (USD/KRW), M02-02가 fx_symbol 데이터를 변환
        pair: Literal["USDKRW"] = "USDKRW"; date: date; rate: float = Field(gt=0); source: str; fetched_at: datetime
    
    class PriceMeta(BaseModel):              # PriceFrame과 함께 전달
        source: str; as_of: date; fetched_at: datetime; tickers: list[str]
    
    class TickerQuality(BaseModel):
        ticker: str; coverage: float; filled_days: int; status: DataStatus; reason: str | None = None
        is_required: bool                    # Benchmark 또는 고정 목록(사용자 지목)
    
    class DataQualityReport(BaseModel):      # M02-03 출력
        as_of: date; expected_days: int; items: list[TickerQuality]
        usable_tickers: list[str]; excluded: dict[str, str]   # 티커 → 사유
    
    class IndexConstituent(BaseModel):       # M02-05
        index_code: IndexCode; ticker: str; name: str; sector: str; industry: str
        snapshot_date: date; source: str; fetched_at: datetime
    
    class UniverseResult(BaseModel):         # M03-05 출력
        tickers: list[str]; snapshot_dates: dict[IndexCode, date]
        criteria: dict[str, Any]; excluded: dict[str, str]; source: str
    
    # ---------- 전략 실행 결과 ----------
    class TickerSignal(BaseModel):           # 근거용 수치 (M03-01/M03-02가 채움)
        ticker: str; metric_name: str; value: float; rank: int | None = None; universe_size: int
    
    class WeightSet(BaseModel):              # M03-04 출력
        as_of: date; spec_hash: str
        weights: dict[str, float]            # 합 1.0
        pre_cap_weights: dict[str, float]    # 상한 적용 전 (근거용)
        signals: list[TickerSignal]
        selected: list[str]
    
    class ValidationIssue(BaseModel):  code: str; field: str | None = None; message: str
    class ValidationResult(BaseModel): ok: bool; issues: list[ValidationIssue] = []
    
    # ---------- Backtest ----------
    class CalcConditions(BaseModel):         # FR12, Report 「계산 조건」
        start: date; end: date; rebalance: str; benchmark: str; cost_bps: float
        risk_free_annual: float; base_currency: Literal["USD"] = "USD"
        initial_capital_usd: float; fx_rate_krw_per_usd: float; fx_as_of: date
    
    class RebalanceRecord(BaseModel):
        date: date; weights: dict[str, float]; turnover: float; cost_usd: float
    
    class BacktestResult(BaseModel):         # M05-01 출력 (시계열은 list로 직렬화)
        conditions: CalcConditions; spec_hash: str
        equity_curve: dict[date, float]      # 전략 평가액(USD)
        benchmark_curve: dict[date, float]
        rebalances: list[RebalanceRecord]
    
    class PerformanceMetrics(BaseModel):     # M05-02 출력 (비율은 소수: 0.152 = 15.2%)
        total_return: float; cagr: float; ann_volatility: float; sharpe: float
        mdd: float; mdd_peak: date; mdd_trough: date
    
    class MetricsBundle(BaseModel):
        strategy: PerformanceMetrics; benchmark: PerformanceMetrics
        excess_total_return: float; excess_cagr: float
    
    # ---------- 근거·Report ----------
    class EvidenceItem(BaseModel):           # M06-01
        subject: str                         # 티커 또는 "portfolio"/"universe"
        kind: Literal["universe", "selection", "weight", "cap", "metric", "limitation"]
        statement: str                       # 템플릿으로 만든 문장
        values: dict[str, float | str]       # 문장에 들어간 수치 원본
        source: str; as_of: date
    
    class AllocationRow(BaseModel):
        ticker: str; name: str | None; weight: float; amount_usd: float; amount_krw: int
    
    class ReportData(BaseModel):             # M06-02가 텍스트로 렌더링하는 구조 데이터
        run_id: str; created_at: datetime; profile: UserProfile; spec: StrategySpec; spec_hash: str
        allocation_as_of: date; allocation: list[AllocationRow]
        metrics: MetricsBundle; conditions: CalcConditions
        evidence: list[EvidenceItem]; limitations: list[str]; process_summary: list["StepRecord"]
    
    class Report(BaseModel):
        data: ReportData; text_markdown: str
        display_values: dict[str, str]       # 필드 경로 → 텍스트에 표시된 문자열 (M04-03 CONSIST_TEXT용)
    # ReportData는 StepRecord를 전방 참조하므로 모듈 끝에서 ReportData.model_rebuild() 호출
    
    # ---------- 실행 기록 ----------
    class StepRecord(BaseModel):             # M08-01
        run_id: str; step: str; status: StepStatus
        started_at: datetime; ended_at: datetime | None = None
        summary: str | None = None; sources: list[str] = []
        error_code: str | None = None; error_message: str | None = None
    
    # ---------- 공통 오류 ----------
    class MyFinSightError(Exception):
        code: str = "UNKNOWN"; recoverable: bool = False
        def __init__(self, message: str, *, code: str | None = None, details: dict | None = None): ...
    class ConfigError(MyFinSightError): ...
    class InputError(MyFinSightError): ...        # Profile/Spec 파일
    class DataSourceError(MyFinSightError): ...   # 외부 조회 실패
    class DataQualityError(MyFinSightError): ...  # 필수 데이터 실패
    class SpecValidationError(MyFinSightError): ...
    class WeightValidationError(MyFinSightError): ...
    class StrategyError(MyFinSightError): ...     # 규칙 실행 불가(예: 상한 불가능)
    class BacktestError(MyFinSightError): ...
    class ConsistencyError(MyFinSightError): ...
    class RepositoryError(MyFinSightError): ...
    ```
    
- **성공·평가 기준:** 모든 모델이 JSON 직렬화·역직렬화 왕복 시 동일 / `extra="forbid"`로 오타 필드 거부 / 예시 profile.json·spec.json(부록 A)이 검증 통과
- **제약:** 스키마 변경 시 버전 메모를 남기고 영향 모듈을 함께 수정. 모듈은 스키마를 상속·확장하지 않고 그대로 사용

## F1 사용자 투자조건 관리

### M01-01 Profile 로더·검증기

- **FR:** FR01 (프로토타입: 고정 파일 불러오기·검증만) / UC001 9단계 업무 규칙(부록 A-2)
- **Input:** `inputs/profile.json` 경로, `AppConfig`(industry_map 키 확인용), 지원 종목 집합(선택: 최신 구성종목 티커 집합, 없으면 종목 존재 검사 생략하고 경고)
- **Process**
    1. JSON 읽기 → `UserProfile` 스키마 검증
    2. 업무 규칙 검사 (모두 모아서 한 번에 보고)
        - `PROFILE_INDUSTRY_UNKNOWN`: interest_industries가 industry_map 키에 없음
        - `PROFILE_CAP_ORDER`: 종목별 상한 > 전체 공통 상한
        - `PROFILE_CAP_CONFLICT`: 같은 종목이 제외 목록과 종목별 상한에 동시 존재
        - `PROFILE_TICKER_UNKNOWN`: 제약조건 종목이 지원 종목 집합에 없음
        - `PROFILE_RISK_FLAG`: risk_type ≠ risk_type_computed인데 risk_type_overridden=false (불일치)
    3. 티커 표기 정규화(대문자, `.`→`-`)
- **Output:** `UserProfile`(정규화된 사본) 또는 `InputError(code=PROFILE_INVALID, details={issues})`
- **성공·평가 기준:** 부록 A 예시 통과 / 위 규칙별 위반 케이스 각 1개 이상 테스트에서 정확한 code 반환 / 위반이 여러 개면 전부 보고
- **제약:** 파일을 수정하지 않음. 금액은 원화 정수

## F2 금융 데이터 관리

### M02-01 가격 수집 어댑터

- **FR:** FR04
- **Input:** `tickers: list[str]`, `start: date`, `end: date`, `AppConfig.data`
- **Process**
    1. 인터페이스 `PriceSourceAdapter.fetch(tickers, start, end) -> RawPriceBatch` 정의, 구현체 `YFinanceAdapter`
    2. 수정종가·거래량 요청 (yfinance: `auto_adjust=False`의 `Adj Close`, `Volume`)
    3. 배치 단위 요청(기본 50종목), 실패한 배치·티커는 재시도: 최대 `retry_max`회, 대기 `retry_backoff_sec × 2^(시도-1)`
    4. 재시도 후에도 실패한 티커는 `failed_tickers`에 사유와 함께 기록 (예외로 중단하지 않음)
    5. 환율(`fx_symbol`)도 같은 방식으로 수집
- **Output:** `RawPriceBatch` (원본 payload 보존, 출처 `"yfinance"`, fetched_at UTC)
- **성공·평가 기준:** Fake 어댑터로 재시도 횟수·대기 로직 테스트 / 전체 실패 시에도 `RawPriceBatch` 반환하고 `failed_tickers`에 전부 기록 / 실제 호출 스모크 테스트(수동)에서 SPY 5년치 수집 성공
- **제약:** 네트워크 호출은 이 모듈에서만. 원본 가공 금지(가공은 M02-02). 요청 간 최소 간격 설정 가능(요청 제한 대비)
- **오류:** 어댑터 자체 설정 오류만 `DataSourceError(DATA_SOURCE_UNAVAILABLE)`

### M02-02 데이터 정규화기

- **FR:** FR04
- **Input:** `RawPriceBatch`
- **Process:** 원본 → `PriceBar` 목록 (fx_symbol 데이터는 `FxRate` 목록으로 따로 변환) (티커 정규화, 날짜 `date` 변환, adj_close ≤ 0 또는 NaN 행 제거, 통화 USD 확인, source·fetched_at 복사) → PriceFrame 변환 함수 제공 `to_price_frame(bars) -> (DataFrame, PriceMeta)`
- **Output:** `list[PriceBar]`, `list[FxRate]`, 필요 시 `(PriceFrame, PriceMeta)`
- **성공·평가 기준:** 같은 원본이면 같은 결과 / 제거된 행 수를 반환값에 포함 / PriceFrame 계약(0-4) 검사 함수 통과
- **제약:** 보간·제외 판단 금지(M02-03 역할). 순수 함수(I/O 없음)

### M02-03 데이터 품질 판정기

- **FR:** FR05 / 업무 규칙 부록 A-3
- **Input:** PriceFrame(결측 포함), `required_tickers`(Benchmark + Spec 고정 목록 종목), `expected_calendar`(Benchmark의 거래일 목록), `AppConfig.data`
- **Process**
    1. 티커별 커버리지 = 유효 값이 있는 거래일 수 / 기대 거래일 수 (기간 = Backtest 기간 + 최대 lookback)
    2. 연속 1거래일 결측만 직전값으로 채움(`max_fill_days`), 채운 일수 기록 → `FILLED`
    3. 커버리지 < `coverage_threshold` 또는 2일 이상 연속 결측 → `EXCLUDED`(사유 기록)
    4. `EXCLUDED`인 티커가 `required_tickers`에 있으면 `DataQualityError(DATA_REQUIRED_MISSING)` (UC-C 2b·2c)
    5. 사용 가능 종목이 0개면 `DataQualityError(DATA_NO_USABLE_TICKER)`
- **Output:** `DataQualityReport` + 결측이 없는 PriceFrame(사용 가능 종목만)
- **성공·평가 기준:** 경계값 테스트(커버리지 0.95 정확히 = 통과, 0.9499 = 제외) / 2일 연속 결측 제외 / Benchmark 결측 시 예외 / 출력 PriceFrame에 NaN 없음
- **제약:** 값 생성 금지(C-07). 판정 기준은 설정에서만 읽음

### M02-04 시장 데이터 Repository

- **FR:** FR04 (출처·기준시점·수집시각과 함께 저장)
- **Input / Output (인터페이스)**
    
    ```python
    class MarketDataRepository(Protocol):
        def upsert_prices(self, bars: list[PriceBar]) -> int: ...                    # 반영 행 수
        def get_prices(self, tickers: list[str], start: date, end: date) -> tuple[pd.DataFrame, PriceMeta]: ...
        def covered_range(self, ticker: str) -> tuple[date, date] | None: ...
        def upsert_fx(self, rates: list[FxRate]) -> int: ...
        def get_fx_on_or_before(self, d: date) -> FxRate | None: ...
        def save_run_artifact(self, run_id: str, profile: UserProfile, spec: StrategySpec,
                              universe: UniverseResult, config: AppConfig) -> None: ...      # 재현용
        def save_constituents(self, rows: list[IndexConstituent]) -> None: ...
        def latest_constituents(self, index: IndexCode) -> list[IndexConstituent]: ...
        def log_fetch(self, source: str, target: str, start: date | None, end: date | None,
                      status: str, fetched_at: datetime, error: str | None) -> None: ...
        def save_step(self, rec: StepRecord) -> None: ...
        def get_steps(self, run_id: str) -> list[StepRecord]: ...
        def save_report(self, report: Report) -> None: ...
        def get_report(self, run_id: str) -> Report | None: ...
    ```
    
- **Process:** SQLAlchemy Core로 `SqliteRepository` 구현 (부록 B DDL). 자연키가 같은 행은 값이 다를 때만 갱신(upsert), 같으면 건너뜀. 캐시 판단 헬퍼 `needs_fetch(ticker, start, end)`: 저장 범위가 요청 범위를 덮고, 마지막 저장일이 직전 거래일 이상이면 False
- **성공·평가 기준:** 같은 데이터 두 번 upsert 시 두 번째 반영 0행 / 범위 조회 결과가 PriceFrame 계약 충족 / `needs_fetch` 경계 테스트 / 인메모리 SQLite로 전체 테스트 통과
- **제약:** C-10. 다른 모듈은 SQL·테이블명 모름. PostgreSQL 구현체를 같은 인터페이스로 추가할 수 있게 SQL 방언 의존 최소화 (upsert는 방언별 분기 허용)
- **오류:** `RepositoryError(REPO_WRITE_FAILED / REPO_READ_FAILED)`

### M02-05 지수 구성종목 수집기

- **FR:** FR04 / 결정로그 Universe 항목
- **Input:** `AppConfig.universe.indices`, 오늘 날짜, M02-04
- **Process**
    1. 인터페이스 `ConstituentSource.fetch(index) -> list[IndexConstituent]`. **출처는 구현자가 선택하고 명세(이 절)에 기록** (예: 공개 목록 페이지, ETF 보유 종목 파일 등). 출처명과 URL을 `source`에 저장
    2. 갱신 필요 판단: 최신 스냅샷 날짜 < 「직전 정기 변경일」이면 수집. 정기 변경일 = 3·6·9·12월 셋째 금요일 (Nasdaq-100도 같은 기준 사용)
    3. 결과 검사: SP500 행 수 495~510, NDX 98~105 (보통주 다중 클래스 고려), 티커 중복 없음, sector·industry 비어 있지 않음
    4. 통과하면 오늘 날짜를 snapshot_date로 M02-04에 저장. 실패하면 기존 스냅샷 유지 + 경고(가장 최근 스냅샷 날짜를 Report 한계에 표시)
- **Output:** 최신 `list[IndexConstituent]` (지수별)
- **성공·평가 기준:** 정기 변경일 계산 테스트(예: 2026-09-18이 9월 셋째 금요일) / 행 수 범위 위반 시 저장 안 함 / Fake 소스로 갱신·미갱신 분기 테스트
- **제약:** 정기 변경 사이의 수시 변경은 반영하지 않음(한계로 기록). 섹터·산업 분류는 GICS 명칭 기준으로 통일 🔶K3
- **출처 기록란 (구현자 작성):** `출처: ____ / URL: ____ / 갱신 방법: ____ / 확인일: ____`

## F3 투자전략 구성

> 공통: M03-01~M03-03은 **순수 함수**(I/O 없음). 입력 PriceFrame은 「as_of 전 거래일까지」로 잘라서 받는다(C-06). 함수 등록은 M03-04의 레지스트리에서만.
> 

### M03-01 종목 선정 규칙

- **FR:** FR08
- **Input:** `candidates: list[str]`, `prices: PriceFrame`(as_of 전일까지), `params: dict`
- **Process (규칙별)**
    
    
    | 규칙 | params (기본값 / 허용 범위) | 계산 |
    | --- | --- | --- |
    | `fixed_list` | `tickers` (1~30개) | candidates와 무관하게 지정 목록 반환. 목록 중 데이터 없는 종목이 있으면 `StrategyError(STRATEGY_FIXED_TICKER_MISSING)` |
    | `low_volatility_top_n` | `n`=5 (1~30), `lookback_days`=252 (20~756) | 일간수익률 표준편차(ddof=1) × √252 → 오름차순 상위 n |
    | `momentum_top_n` | `n`=5 (1~30), `lookback_days`=252 (60~756), `skip_days`=21 (0~63) | 가격(t−skip)/가격(t−lookback) − 1 → 내림차순 상위 n |
    - 동순위: 티커 오름차순. lookback 기간 데이터가 부족한 종목은 후보에서 빼고 사유 기록
    - candidates 수 < n이면 있는 만큼 선택하고 `PARTIAL` 사유 기록 (0개면 `STRATEGY_EMPTY_SELECTION`)
- **Output:** `SelectionResult(selected: list[str], signals: list[TickerSignal], dropped: dict[str,str])` — signals에는 모든 후보의 지표값과 순위(근거용)
- **성공·평가 기준:** 손계산 예제(종목 4개, 30일)와 지표값 소수 6자리 일치 / 동순위 정렬 테스트 / 데이터 부족 종목 제외 테스트
- **제약:** C-03, C-06

### M03-02 비중 결정 규칙

- **FR:** FR08
- **Input:** `selected: list[str]`, `prices: PriceFrame`(as_of 전일까지), `params`
- **Process**
    
    
    | 규칙 | params | 계산 |
    | --- | --- | --- |
    | `equal` | 없음 | wᵢ = 1/n |
    | `inverse_volatility` | `lookback_days`=252 (20~756) | σᵢ = 연환산 변동성, wᵢ = (1/σᵢ) / Σ(1/σⱼ). σᵢ ≤ 1e-8이면 `STRATEGY_ZERO_VOL` |
- **Output:** `dict[str, float]` (합 1.0) + 근거용 `list[TickerSignal]`
- **성공·평가 기준:** 합 = 1 (오차 1e-9) / 손계산 예제 일치 / 종목 1개면 100%
- **제약:** 음수 비중 금지(롱 온리)

### M03-03 제약 적용 규칙

- **FR:** FR08 (사용자 제약 반영)
- **Input:** 두 가지 함수
    - `apply_exclusions(tickers, exclude) -> (list[str], dict[제외티커, 사유])`
    - `apply_caps(weights, max_all, per_ticker) -> dict[str,float]`
- **Process (apply_caps)**
    1. 종목별 상한 cᵢ = min(max_all, per_ticker.get(i, max_all))
    2. 실현 가능성: Σcᵢ < 1이면 `StrategyError(STRATEGY_CAP_INFEASIBLE)` (예: 3종목 × 25% < 100%)
    3. 반복: 상한 초과 종목을 cᵢ로 고정 → 남은 비중(1 − 고정 합)을 고정되지 않은 종목에 **기존 비중 비례**로 재분배 → 초과가 없을 때까지 (최대 n회)
- **Output:** 상한 적용 후 비중 (합 1.0)
- **성공·평가 기준:** 예제 [0.5, 0.3, 0.2], 상한 0.4 → [0.4, 0.36, 0.24] / 불가능 케이스 예외 / 재분배 후에도 모든 wᵢ ≤ cᵢ + 1e-9
- **제약:** 제외는 선정 **전**에 적용(제외 종목이 순위 계산에도 들어가지 않음)

### M03-04 전략 실행기 (Mapper)

- **FR:** FR08, FR10 (같은 함수로 기준일 비중과 Backtest 비중을 만들어 표시=실행을 구조적으로 보장)
- **Input:** `StrategySpec`(M04-01 통과), `universe: list[str]`, `prices: PriceFrame`(M02-03 통과), `as_of: date`
- **Process**
    1. 레지스트리: `SELECTION_REGISTRY: dict[SelectionRule, Callable]`, `WEIGHTING_REGISTRY: dict[WeightingRule, Callable]` (이름 → M03-01·M03-02 함수). 등록되지 않은 이름은 `STRATEGY_UNKNOWN_RULE`
    2. prices를 as_of 전 거래일까지 자름
    3. 후보 = (universe.mode=fixed ? spec.universe.tickers : 입력 universe) → `apply_exclusions`(Spec 제외 목록. Profile 제외가 Spec에 포함되어 있음은 M04-01이 보장)
    4. 선정(M03-01) → 비중(M03-02) → `apply_caps`(M03-03)
    5. `WeightSet` 생성 (spec_hash, pre_cap_weights, signals 포함)
- **Output:** `WeightSet`
- **성공·평가 기준:** 같은 입력 → 같은 WeightSet / 고정 목록 + 동일 비중 예제 / 레지스트리에 없는 규칙 예외 / M05-01이 이 함수만 호출해서 비중을 얻는지 코드 리뷰로 확인
- **제약:** Spec에 없는 파라미터 무시 금지(M04-01에서 거부). 규칙 함수 직접 호출은 이 모듈만

### M03-05 Universe 구성기

- **FR:** FR08 (규칙 기반 후보 탐색, UC-C 3단계의 LLM 없는 버전)
- **Input:** 지수별 최신 `list[IndexConstituent]`(M02-05/M02-04), `UserProfile`, `StrategySpec`, `AppConfig.universe`, `industry_map`
- **Process**
    1. spec.universe.mode=fixed면 그 목록 그대로 반환(필터 생략, criteria에 "fixed" 기록)
    2. 두 지수 합집합, 티커 중복 제거(이름·분류는 SP500 우선)
    3. 관심산업 필터: Profile.interest_industries → industry_map으로 GICS industry 목록 변환 → 해당 종목만. 관심산업이 비어 있으면 필터 생략
    4. 제외: Profile·Spec 제외 종목, `allow_etf=false`면 ETF(구성종목에는 원래 없음, 안전장치)
    5. 크기 제한: `max_size` 초과 시 티커 오름차순으로 자름. 이 기준은 임의적이라 🔶K5 (구성종목 스키마에 시가총액·지수 비중 필드를 추가해 큰 순으로 자를지)
    6. 결과가 0개면 `StrategyError(UNIVERSE_EMPTY)` (UC-C 3a), 사유에 사용된 필터 명시
- **Output:** `UniverseResult` (tickers, 스냅샷 날짜, 적용 기준, 제외 사유, 출처)
- **성공·평가 기준:** Fake 구성종목(20개)으로 산업 필터·제외·크기 제한 테스트 / 같은 스냅샷 + 같은 Profile → 같은 결과 / 결과가 M08-01 실행 기록에 저장되어 재실행 시 재사용 가능
- **제약:** 선견 편향·생존 편향 존재 → M06-02 한계 항목에 반드시 표시

## F4 분석·전략 검증

### M04-01 Spec 정적 검증기

- **FR:** FR09 (정적), UC-C 6단계
- **Input:** `StrategySpec`(스키마 통과), `UserProfile`, `AppConfig`
- **Process:** 아래 규칙을 모두 검사해 이슈를 모아 반환 (첫 오류에서 멈추지 않음)
    
    
    | code | 검사 |
    | --- | --- |
    | `SPEC_UNKNOWN_RULE` | selection·weighting 규칙이 M03-04 레지스트리에 있는가 |
    | `SPEC_PARAM_MISSING` / `SPEC_PARAM_RANGE` / `SPEC_PARAM_UNKNOWN` | 규칙별 필수 파라미터·허용 범위(M03-01·M03-02 표)·모르는 파라미터 |
    | `SPEC_CAP_RANGE` | max_weight_all ∈ (0,1], 종목별 상한 ∈ [0,1] |
    | `SPEC_CAP_ORDER` | 종목별 상한 ≤ 전체 상한 |
    | `SPEC_CONSTRAINT_CONFLICT` | 제외 종목 ∩ 종목별 상한 ≠ ∅, 또는 fixed_list ∩ 제외 종목 ≠ ∅ |
    | `SPEC_PROFILE_VIOLATION` | Spec 제약이 Profile보다 느슨함: Spec 전체 상한 > Profile 전체 상한, Profile 종목별 상한보다 큰 Spec 값, Profile 제외 종목이 Spec 제외에 없음 |
    | `SPEC_CAP_INFEASIBLE` | 선정 개수 n(또는 fixed_list 길이) × 전체 상한 < 1 |
    | `SPEC_BENCHMARK` | benchmark ∈ allowed_benchmarks |
    | `SPEC_PERIOD` | period_years ∈ [1, 20] |
- **Output:** `ValidationResult`. 실패 시 M08-02가 `SpecValidationError`로 중단 (프로토타입은 고정 Spec이라 재생성 없음, UC-C 6a의 재생성은 LLM 단계에서)
- **성공·평가 기준:** 규칙마다 위반 예제 1개 이상 → 정확한 code / 부록 A 예시 Spec 통과 / 사전에 삽입한 Profile 제약 위반 탐지율 100% (0928 F4 목표 95% 이상 충족)
- **제약:** Spec을 수정하지 않음(자동 보정 금지)

### M04-02 비중 동적 검증기

- **FR:** FR09 (동적), UC-C 7단계
- **Input:** `WeightSet`, `StrategySpec`, universe 목록
- **Process:** 검사 code
    - `WEIGHT_SUM`: |Σw − 1| ≤ 1e-6
    - `WEIGHT_NEGATIVE`: 모든 w ≥ 0
    - `WEIGHT_CAP`: wᵢ ≤ cᵢ + 1e-9
    - `WEIGHT_EXCLUDED`: 제외 종목 비중 = 0 (목록에 없음)
    - `WEIGHT_OUTSIDE_UNIVERSE`: 모든 종목 ∈ universe(또는 fixed 목록)
    - `WEIGHT_EMPTY`: 종목 수 ≥ 1
- **Output:** `ValidationResult` (실패 시 호출자가 `WeightValidationError`)
- **성공·평가 기준:** 각 code별 위반 예제 탐지 / M05-01의 **모든 리밸런싱 시점**과 기준일 비중에 적용됨
- **제약:** 순수 함수

### M04-03 일치성 검사기

- **FR:** FR10 (표시=실행), FR25 (Report 수치 불일치 차단)
- **Input:** `ReportData`, 실행에 쓰인 `StrategySpec`·`WeightSet`(기준일)·`BacktestResult`·`MetricsBundle`, 렌더링된 `text_markdown`
- **Process**
    1. `CONSIST_SPEC`: ReportData.spec_hash == 실행 Spec 해시 == BacktestResult.spec_hash
    2. `CONSIST_WEIGHTS`: Report 배분표 비중 == 기준일 WeightSet (종목 집합 동일, 값 오차 ≤ 1e-6)
    3. `CONSIST_AMOUNT`: amount_usd = weight × initial_capital_usd, amount_krw = round(amount_usd × fx) (±1원)
    4. `CONSIST_METRICS`: ReportData.metrics == 계산된 MetricsBundle (필드별 오차 ≤ 1e-9)
    5. `CONSIST_TEXT`: 텍스트에 표시된 주요 수치(비중, 지표)가 ReportData 값을 표시 규칙(부록 D)으로 반올림한 문자열과 같은지 — 렌더러가 표시값 목록을 함께 반환하고 이를 대조
    6. `CONSIST_EVIDENCE`: 모든 EvidenceItem에 source·as_of 존재, values의 수치가 signals·metrics 원본과 같음
- **Output:** `ValidationResult`. 실패 시 M08-02가 Report를 저장·출력하지 않고 `ConsistencyError`로 실패 처리
- **성공·평가 기준:** 각 항목별로 일부러 값을 바꾼 ReportData를 넣었을 때 100% 탐지 / 정상 실행에서는 오탐 0
- **제약:** 검사만 하고 값을 고치지 않음

## F5 백테스트 및 성과 평가

### M05-01 Backtest 시뮬레이터

- **FR:** FR11, FR12
- **Input:** `StrategySpec`, `universe`, PriceFrame(M02-03 통과, 기간 = 시작일 − 최대 lookback ~ 종료일), Benchmark 가격 Series, `CalcConditions` 생성용 값(설정, 무위험수익률(M05-03), 투자금 원화, 환율·기준일)
- **Process**
    1. 기간: end = 데이터의 마지막 거래일, start = end − period_years년 이후 첫 거래일
    2. 초기자본 USD = investment_amount_krw / fx_rate(fx_as_of = end 이하 가장 최근 환율일)
    3. 리밸런싱일 = start + 각 분기(1·4·7·10월) **첫 거래일** 🔶K2
    4. 각 리밸런싱일 t: M03-04로 WeightSet(as_of=t) → M04-02 검증 → 목표 비중으로 조정. 회전율 = Σ|w_target − w_drift|, 비용 = 회전율 × cost_bps/10,000 × 평가액 (첫 매수도 회전율 1.0으로 비용 반영)
    5. 리밸런싱 사이: 보유 수량 고정(비중은 가격에 따라 변함), 매일 평가액 = Σ수량 × 수정종가
    6. 체결 가정: 리밸런싱일 **종가**에 체결(신호는 전일 종가까지, C-06)
    7. Benchmark: 같은 start·초기자본으로 매수 후 보유, 첫 매수 비용 동일 적용
- **Output:** `BacktestResult` (일별 평가액, Benchmark 곡선, 리밸런싱 기록, CalcConditions)
- **성공·평가 기준**
    - 손계산 예제: 2종목·10거래일·리밸런싱 1회 → 평가액 소수 6자리 일치
    - 비용 0이면 동일 비중 buy&hold 결과가 단순 계산과 일치
    - 같은 입력 2회 실행 결과 동일(재현율 100%, 0928 F5 목표)
    - 리밸런싱마다 M04-02 통과 기록
- **제약:** 구현은 pandas/NumPy 기준. vectorbt 사용 시에도 위 손계산 예제를 통과해야 함 🔶K4. 공매도·레버리지·현금 보유 없음(항상 100% 투자). 배당은 수정종가로 반영된 것으로 간주

### M05-02 성과 지표 계산기

- **FR:** FR11
- **Input:** 평가액 Series(전략·Benchmark), 무위험수익률(연), `trading_days_per_year`
- **Process (정의)**
    - 일간수익률 rₜ = Vₜ/Vₜ₋₁ − 1
    - 누적수익률 = V_T / V_0 − 1
    - CAGR = (V_T / V_0)^(1/Y) − 1, Y = (마지막일 − 시작일).days / 365.25 🔶K6
    - 연환산 변동성 = std(r, ddof=1) × √252
    - Sharpe = (mean(r) − r_f,일) / std(r, ddof=1) × √252, r_f,일 = (1 + r_f)^(1/252) − 1
    - MDD = minₜ(Vₜ / maxₛ≤ₜ Vₛ − 1), 고점일·저점일 함께
    - 초과 누적수익률 = 전략 누적 − BM 누적, 초과 CAGR = 전략 CAGR − BM CAGR
- **Output:** `MetricsBundle`
- **성공·평가 기준:** 알려진 시계열(예: 매일 +1% 10일)로 각 지표 손계산 일치 / 변동성 0이면 Sharpe 계산 대신 `METRIC_UNDEFINED` 표시(예외 아님) / 6개 필수 지표 산출 성공률 100%
- **제약:** 순수 함수. 반올림 금지(표시 반올림은 M06-02)

### M05-03 무위험수익률 제공자

- **FR:** FR12
- **Input:** `AppConfig.risk_free`, 기간(start, end)
- **Process:** 인터페이스 `RiskFreeProvider.annual_rate(start, end) -> float`. 구현체 `FixedRateProvider`(config 값 반환). 추후 `TreasuryRateProvider`(국채금리 조회, 기간 평균) 추가
- **Output:** 연 무위험수익률(소수) + 출처 문자열(예: `"config:fixed"`)
- **성공·평가 기준:** config 값 변경이 Report 계산 조건과 Sharpe에 반영 / 다른 모듈 수정 없이 구현체 교체 가능(인터페이스 테스트)
- **제약:** 값의 출처를 Report 「계산 조건」에 표시

## F6 분석 결과 제공

### M06-01 근거 생성기

- **FR:** FR26 (수치 근거 + 출처·기준시점), FR05
- **Input:** `UniverseResult`, 기준일 `WeightSet`, `DataQualityReport`, `MetricsBundle`, `UserProfile`, `PriceMeta`
- **Process:** 아래 템플릿으로 `EvidenceItem` 생성 (문장의 모든 숫자는 values에 원본 저장, 표시는 부록 D 규칙)
    
    
    | kind | 템플릿 (예) |
    | --- | --- |
    | universe | "S&P 500·Nasdaq-100 구성종목({snapshot_date} 기준) 중 관심산업 {industries}에 해당하는 {k}개 종목을 후보로 사용했습니다." |
    | selection (저변동성) | "{ticker}: 최근 {lookback}거래일 연환산 변동성 {vol}, 후보 {N}개 중 {rank}위 → 저변동성 상위 {n}개에 포함" |
    | selection (모멘텀) | "{ticker}: {lookback}거래일 수익률(최근 {skip}일 제외) {mom}, 후보 {N}개 중 {rank}위" |
    | selection (고정 목록) | "{ticker}: 전략에 지정된 종목" |
    | weight | "{ticker}: {rule_name} 방식으로 {w}" |
    | cap | "{ticker}: 상한 {cap} 적용으로 {w_before} → {w_after}" |
    | metric | "Backtest 기간 최대낙폭 {mdd}는 투자성향의 손실 감내 수준 -{loss_tol}% {이내이다/를 초과한다}" |
    | limitation | 데이터 부족으로 제외된 종목과 사유 (M02-03 excluded) |
    - 모든 항목에 `source`(예: "yfinance 수정종가", 구성종목 출처)와 `as_of` 부착
- **Output:** `list[EvidenceItem]`
- **성공·평가 기준:** 선정된 모든 종목에 selection·weight 근거 1개 이상 / 모든 항목 source·as_of 존재(표시율 100%, 0928 F6 목표) / values의 수치가 원본과 일치(M04-03에서 확인)
- **제약:** 템플릿 외 문장 생성 금지(LLM 미사용). 투자 권유 표현("사세요", "유망") 금지

### M06-02 Report 조립기

- **FR:** FR14 / UC003 데이터 정의(부록 B)
- **Input:** `run_id`, `UserProfile`, `StrategySpec`, 기준일 `WeightSet`, `BacktestResult`, `MetricsBundle`, `list[EvidenceItem]`, `UniverseResult`, `DataQualityReport`, `list[StepRecord]`(M08-01), 종목명 사전(구성종목)
- **Process**
    1. `ReportData` 생성: 배분표 = 기준일 비중 × 초기자본(USD·원화), 한계 목록 자동 구성
        - 고정: "Backtest 결과는 과거 데이터 기반 가상 성과이며 미래 수익을 보장하지 않습니다"(C008)
        - 고정: "현재 지수 구성종목으로 과거를 계산하므로 생존·선견 편향이 있습니다"
        - 조건부: 데이터 부족 제외 종목, 구성종목 스냅샷이 직전 정기 변경일보다 오래됨, 정기 변경 사이 수시 변경 미반영
    2. Markdown 렌더링 (프로토타입 섹션 순서, 부록 B 번호):
        
        `1 요약 → 2 투자조건 → 3 Portfolio 구성(표) → 4 전략 규칙 → 5 구성 근거 → 7 Backtest 성과(표, BM 대비) → 8 Risk(MDD vs 손실 감내) → 10 계산 조건 → 11 한계·주의 → 12 분석 과정 요약`
        
        (6 기업·시장 정보, 9 LLM 해석은 프로토타입 제외 — 9는 템플릿 한 줄 요약으로 대체 가능)
        
    3. 렌더러는 텍스트와 함께 「표시값 목록」(필드 경로 → 표시 문자열)을 반환 (M04-03 CONSIST_TEXT용)
    4. 저장하지 않고 `Report`만 반환. 저장(M02-04, `outputs/report_{run_id}.md`)은 **M04-03 통과 후 M08-02가** 수행
- **Output:** `Report`
- **성공·평가 기준:** 프로토타입 필수 섹션 10개 모두 존재(표시율 100%) / 같은 ReportData → 같은 텍스트 / 원화 금액 합 = 투자금(반올림 오차 종목 수 원 이내)
- **제약:** 숫자 표시는 부록 D 규칙만 사용. 계산 금지(값은 입력에서만, 단 금액 = 비중 × 자본 곱셈은 허용하고 M04-03이 검증)

## F8 분석 실행 관리

### M08-01 실행 기록기 (Run Logger)

- **FR:** FR24, R9
- **Input:** `run_id`, 단계 이름, 상태·요약·출처·오류
- **Process (API)**
    
    ```python
    class RunLogger:
        def __init__(self, run_id: str, repo: MarketDataRepository): ...
        @contextmanager
        def step(self, name: str) -> Iterator["StepHandle"]: ...   # 진입 시 STARTED 기록, 정상 종료 SUCCESS, 예외 시 FAILED(+code, message) 후 예외 재전파
        # StepHandle.set_summary(text), add_source(name), mark_partial(reason)
        def records(self) -> list[StepRecord]: ...
        def summary_lines(self) -> list[str]: ...                  # Report 12번 섹션용 "데이터 조회: 성공 (52/55, 3개 제외)" 형태
    ```
    
    - 단계 이름 표준: `load_profile`, `validate_spec`, `constituents`, `universe`, `fetch_prices`, `data_quality`, `compute_weights`, `validate_weights`, `backtest`, `metrics`, `evidence`, `report`, `consistency`
- **Output:** `StepRecord` 저장(M02-04), 요약 문자열
- **성공·평가 기준:** 정상 실행 후 표준 단계 13개 기록 조회 가능 / 예외 발생 단계는 FAILED + code 기록, 이후 단계는 기록 없음 / 기록 실패가 분석 자체를 실패시키지 않음(기록 실패는 logging 경고)
- **제약:** 흐름 제어 금지(기록만). 시각은 UTC

### M08-02 파이프라인 실행기

- **FR:** FR24, FR25 (오류 시 중단·차단), 추후 LangGraph Orchestrator로 교체
- **Input:** CLI `python -m myfinsight run --profile inputs/profile.json --spec inputs/spec.json [--config config/config.toml] [--refresh-constituents]`
- **Process**
    1. run_id 발급(`YYYYMMDD-HHMMSS-<6자리 해시>`), RunLogger 생성
    2. 0-2 실행 흐름 순서로 각 모듈 호출, 각 호출을 `logger.step()`으로 감쌈
    3. 오류 처리 정책
        
        
        | 상황 | 처리 |
        | --- | --- |
        | 일부 종목 데이터 제외(M02-03 EXCLUDED, 필수 아님) | 계속, 단계 PARTIAL, 한계에 기록 |
        | 필수 데이터 실패, Universe 0개, Spec·비중 검증 실패, Backtest 오류, 일치성 실패 | **중단**, Report 미생성, 실패 요약 출력 |
        | 구성종목 갱신 실패(기존 스냅샷 있음) | 계속, 경고·한계 기록 |
    4. Universe 확정 직후 `save_run_artifact`로 입력·Universe·설정 저장(재현용)
    5. M04-03 통과 시에만 Report 저장, Report 경로와 요약 지표를 콘솔에 출력
- **Output:** 종료 코드 `0`(성공) / `1`(분석 실패: 사유 출력) / `2`(입력·설정 오류), Report 파일, 실행 기록
- **성공·평가 기준:** 부록 A 입력으로 끝까지 실행되어 Report 생성(통합 테스트는 Fake 어댑터) / 각 중단 조건별 종료 코드 1과 실패 단계·사유 출력 / 명령 한 줄로 실행
- **제약:** 비즈니스 로직 금지(호출 순서·오류 정책만). 단계 함수는 모듈 공개 API만 사용

## 부록

### 부록 A. 예시 입력

**config/config.toml**

```toml
[backtest]
period_years = 5
rebalance = "Q"
rebalance_anchor = "first_trading_day"
benchmark = "SPY"
allowed_benchmarks = ["SPY", "QQQ"]
cost_bps = 10.0
trading_days_per_year = 252

[risk_free]
provider = "fixed"
annual_rate = 0.0   # 🔶K1

[data]
db_url = "sqlite:///data/myfinsight.db"
price_source = "yfinance"
fx_symbol = "KRW=X"
coverage_threshold = 0.95
max_fill_days = 1
retry_max = 3
retry_backoff_sec = 1.0
cache_max_age_days = 1

[universe]
indices = ["SP500", "NDX"]
max_size = 60
industry_map_path = "config/industry_map.toml"
```

**config/industry_map.toml** (🔶K3 — 관심산업 → GICS industry)

```toml
"반도체" = ["Semiconductors", "Semiconductor Materials & Equipment"]
"클라우드" = ["Software", "IT Services"]
"AI" = ["Semiconductors", "Software", "Interactive Media & Services", "IT Services"]
"인터넷" = ["Interactive Media & Services", "Broadline Retail"]
```

**inputs/profile.json**

```json
{
  "profile_id": "demo-001",
  "investment_amount_krw": 30000000,
  "horizon_months": 36,
  "risk_type_computed": "위험중립형",
  "risk_type": "위험중립형",
  "risk_type_overridden": false,
  "loss_tolerance_pct": 30,
  "interest_industries": ["AI", "반도체", "클라우드"],
  "preferences": ["성장"],
  "memo": null,
  "constraints": {
    "exclude_tickers": [],
    "max_weight_all": 0.25,
    "max_weight_per_ticker": {"NVDA": 0.15},
    "allow_etf": false
  },
  "market": "US"
}
```

**inputs/spec.json**

```json
{
  "spec_id": "demo-lowvol-ivol",
  "name": "AI 관련 저변동성 5종목, 변동성 역가중",
  "version": 1,
  "universe": {"mode": "dynamic", "tickers": []},
  "selection": {"rule": "low_volatility_top_n", "params": {"n": 5, "lookback_days": 252}},
  "weighting": {"rule": "inverse_volatility", "params": {"lookback_days": 252}},
  "constraints": {"exclude_tickers": [], "max_weight_all": 0.25, "max_weight_per_ticker": {"NVDA": 0.15}},
  "rebalance": "Q",
  "period_years": 5,
  "benchmark": "SPY"
}
```

### 부록 B. SQLite DDL (M02-04)

```sql
CREATE TABLE price_daily (
  ticker TEXT NOT NULL, date DATE NOT NULL, adj_close REAL NOT NULL CHECK (adj_close > 0),
  volume INTEGER, currency TEXT NOT NULL DEFAULT 'USD',
  source TEXT NOT NULL, fetched_at TIMESTAMP NOT NULL,
  PRIMARY KEY (ticker, date, source)
);
CREATE TABLE fx_daily (
  pair TEXT NOT NULL, date DATE NOT NULL, rate REAL NOT NULL CHECK (rate > 0),
  source TEXT NOT NULL, fetched_at TIMESTAMP NOT NULL, PRIMARY KEY (pair, date, source)
);
CREATE TABLE index_constituent (
  index_code TEXT NOT NULL, snapshot_date DATE NOT NULL, ticker TEXT NOT NULL,
  name TEXT, sector TEXT NOT NULL, industry TEXT NOT NULL,
  source TEXT NOT NULL, fetched_at TIMESTAMP NOT NULL,
  PRIMARY KEY (index_code, snapshot_date, ticker)
);
CREATE TABLE fetch_log (
  id INTEGER PRIMARY KEY AUTOINCREMENT, source TEXT NOT NULL, target TEXT NOT NULL,
  start_date DATE, end_date DATE, status TEXT NOT NULL, fetched_at TIMESTAMP NOT NULL, error TEXT
);
CREATE TABLE run_step (
  run_id TEXT NOT NULL, step TEXT NOT NULL, status TEXT NOT NULL,
  started_at TIMESTAMP NOT NULL, ended_at TIMESTAMP, summary TEXT, sources_json TEXT,
  error_code TEXT, error_message TEXT, PRIMARY KEY (run_id, step)
);
CREATE TABLE run_artifact (            -- 재현용: 실행에 쓴 입력·Universe·Spec 해시
  run_id TEXT PRIMARY KEY, created_at TIMESTAMP NOT NULL, profile_json TEXT NOT NULL,
  spec_json TEXT NOT NULL, spec_hash TEXT NOT NULL, universe_json TEXT NOT NULL, config_json TEXT NOT NULL
);
CREATE TABLE report (
  run_id TEXT PRIMARY KEY REFERENCES run_artifact(run_id),
  created_at TIMESTAMP NOT NULL, data_json TEXT NOT NULL, text_markdown TEXT NOT NULL
);
CREATE INDEX idx_price_ticker_date ON price_daily(ticker, date);
```

> 0928 PPT DB 설계 대비: 수정종가·통화 추가, volume 정수(SQLite INTEGER = 64bit), 수집 이력은 덮어쓰지 않고 fetch_log에 누적, 실행·Report 테이블 추가. Financial·News 테이블은 프로토타입 범위 밖
> 

### 부록 C. 오류 코드 (요약)

| 접두어 | 모듈 | 예 |
| --- | --- | --- |
| CONFIG_ | M00-01 | CONFIG_INVALID |
| PROFILE_ | M01-01 | PROFILE_CAP_ORDER |
| DATA_ | M02-01~M02-03, M02-05 | DATA_REQUIRED_MISSING, DATA_NO_USABLE_TICKER |
| REPO_ | M02-04 | REPO_WRITE_FAILED |
| STRATEGY_ / UNIVERSE_ | M03-01~M03-05 | STRATEGY_CAP_INFEASIBLE, UNIVERSE_EMPTY |
| SPEC_ | M04-01 | SPEC_PROFILE_VIOLATION |
| WEIGHT_ | M04-02 | WEIGHT_SUM |
| CONSIST_ | M04-03 | CONSIST_WEIGHTS |
| BACKTEST_ / METRIC_ | M05-01, M05-02 | METRIC_UNDEFINED |

### 부록 D. 표시 규칙 (M06-01·M06-02·M04-03 공통)

- 비율(%): 소수 둘째 자리 (`15.23%`), 부호 있는 값은 `+`/`-` 표시
- 비중: 소수 첫째 자리 (`21.4%`)
- 원화: 원 단위 정수, 천 단위 쉼표 (`7,500,000원`) / 달러: 소수 둘째 자리 (`$5,432.10`)
- Sharpe: 소수 둘째 자리 / 날짜: `YYYY-MM-DD`
- 반올림: 사사오입(ROUND_HALF_UP)

### 부록 E. 구현 순서 (마일스톤)

| 단계 | 모듈 | 완료 확인 |
| --- | --- | --- |
| MS1 걷는 골격 | M00-01, M00-02, M02-01, M02-02, M02-04, M03-01(fixed_list), M03-02(equal), M03-04, M05-01, M05-02, M06-02(최소), M08-02(최소) | 고정 5종목 + SPY, 동일 비중 → 지표가 찍힌 Report |
| MS2 규칙·검증 | M02-03, M03-01~M03-03 전체, M04-01, M04-02, M05-03, M01-01 | 예시 Spec(저변동성·역가중·상한)으로 Report, 위반 Spec 차단 |
| MS3 Universe·근거·기록 | M02-05, M03-05, M06-01, M06-02 전체, M04-03, M08-01, M08-02 전체 | 예시 Profile로 동적 Universe → 근거·한계·과정 요약이 있는 Report, 일치성 검사 통과 |

### 부록 G. 결정 필요 목록 🔶

| # | 항목 | 현재 기본값 | 고려 사항 |
| --- | --- | --- | --- |
| K1 | 무위험수익률 값 | 0.0 (config) | 0이면 Sharpe가 높게 나옴. 팀이 값(예: 최근 미국 3개월 국채금리)을 정해 config에 입력 |
| K2 | 리밸런싱 기준일 | 분기 첫 거래일 | 분기 마지막 거래일로 할 수도 있음 |
| K3 | 관심산업 → GICS 매핑 | 부록 A 예시 | "AI"는 GICS 분류에 없어 여러 산업의 합으로 정의함 |
| K4 | Backtest 구현 | pandas/NumPy 기준 | 기술스택의 vectorbt 사용 여부 (사용해도 손계산 예제 통과 필수) |
| K5 | Universe 크기 제한 방식 | 60개, 티커 오름차순 | 시가총액·지수 비중 필드를 추가해 큰 순으로 자르는 편이 합리적 |
| K6 | CAGR 연수 계산 | 달력일 / 365.25 | 거래일 수 / 252도 가능 |

# 3. 분배

| 묶음 | 담당자 | 모듈 | 성격 | 작업량 |
| --- | --- | --- | --- | --- |
| **A. 데이터** | (미정) | M02-01 가격 수집 어댑터, M02-02 데이터 정규화기, M02-03 데이터 품질 판정기, M02-04 시장 데이터 Repository, M02-05 지수 구성종목 수집기 | 외부 API, DB, 데이터 품질 | ●●●● (구성종목 출처 조사가 변수) |
| **B. 전략·검증** | (미정) | M03-01 종목 선정 규칙, M03-02 비중 결정 규칙, M03-03 제약 적용 규칙, M03-04 전략 실행기 (Mapper), M03-05 Universe 구성기, M04-01 Spec 정적 검증기, M04-02 비중 동적 검증기, M01-01 Profile 로더·검증기 | 규칙 함수, 검증 규칙 (순수 함수 위주) | ●●●○ (개수는 많지만 하나하나 작음) |
| **C. 백테스트** | (미정) | M05-01 Backtest 시뮬레이터, M05-02 성과 지표 계산기, M05-03 무위험수익률 제공자, M00-01 설정 (Config) | 계산 정확도 (손계산 테스트) | ●●●○ (시뮬레이터가 가장 까다로움) |
| **D. 결과·통합** | (미정) | M06-01 근거 생성기, M06-02 Report 조립기, M04-03 일치성 검사기, M08-01 실행 기록기 (Run Logger), M08-02 파이프라인 실행기, M00-02 도메인 스키마 + 공통 오류 | 전체 연결, 통합 테스트, 스키마 관리 | ●●●● (통합 책임 포함) |

## 이렇게 묶은 이유

- B에 Spec·비중 검증(M04-01, M04-02)과 Profile 검증(M01-01)을 함께 둠: 검증 규칙은 전략 규칙의 파라미터·상한을 그대로 알아야 해서 같은 사람이 맡아야 어긋나지 않음
- D에 일치성 검사(M04-03)를 둠: Report 데이터를 검사하므로 Report를 만드는 사람이 함께 맡음
- C에 설정(M00-01)을 둠: 설정값 대부분이 Backtest 계산 조건(기간, 비용, 무위험수익률)
- D가 스키마(M00-02)를 관리: 모든 묶음이 쓰는 계약이라 통합 담당이 변경 요청을 받아 관리. D는 팀장 또는 전체 흐름을 잘 아는 사람 추천
- 대안: A 부담을 줄이려면 M02-05(구성종목 수집)·M03-05(Universe 구성기)를 묶어 B로 이동 (B가 무거워짐)

## 묶음 사이 연결 (먼저 합의할 인터페이스)

```
A ──PriceFrame·PriceMeta·구성종목──▶ B, C
B ──WeightSet (M03-04)──────────────▶ C
C ──BacktestResult·MetricsBundle────▶ D
A ──Repository (실행 기록·Report 저장)─▶ D
모두 ── M00-02 스키마 (D 관리)
```

## 진행 순서

1. 1주차 (모두 함께): M00-02 스키마와 M00-01 설정 확정. A는 가짜 가격 데이터(작은 CSV)를 먼저 만들어 공유 → B·C가 실제 수집 모듈을 기다리지 않고 개발
2. MS1 걷는 골격: A 가격 수집·저장, B 고정 목록·동일 비중, C 시뮬레이터·지표, D 최소 Report·파이프라인 → 한 번 끝까지 연결
3. MS2 규칙·검증, MS3 Universe·근거·기록: 각 묶음이 나머지 모듈을 채우고 D가 통합 테스트 (상세: 2. 모듈별 상세 명세 → 부록 E)

# 4. 역할별 모듈 명세

<aside>
💡

모든 담당자는 먼저 「2. 모듈별 상세 명세 → 공통 제약」과 「M00-02 도메인 스키마」를 읽고 시작

</aside>

## A. 데이터 — 담당: (미정)

- **담당 모듈:** M02-01, M02-02, M02-03, M02-04, M02-05
- **인터페이스:** 제공: PriceFrame·PriceMeta(0-4 계약), IndexConstituent, Repository 인터페이스(실행 기록·Report 저장 포함) / 사용: M00-02 스키마, M00-01 설정
- **팁:** 1주차에 가짜 가격 CSV와 Fake 어댑터를 먼저 공유

### M02-01 가격 수집 어댑터

- **FR:** FR04
- **Input:** `tickers: list[str]`, `start: date`, `end: date`, `AppConfig.data`
- **Process**
    1. 인터페이스 `PriceSourceAdapter.fetch(tickers, start, end) -> RawPriceBatch` 정의, 구현체 `YFinanceAdapter`
    2. 수정종가·거래량 요청 (yfinance: `auto_adjust=False`의 `Adj Close`, `Volume`)
    3. 배치 단위 요청(기본 50종목), 실패한 배치·티커는 재시도: 최대 `retry_max`회, 대기 `retry_backoff_sec × 2^(시도-1)`
    4. 재시도 후에도 실패한 티커는 `failed_tickers`에 사유와 함께 기록 (예외로 중단하지 않음)
    5. 환율(`fx_symbol`)도 같은 방식으로 수집
- **Output:** `RawPriceBatch` (원본 payload 보존, 출처 `"yfinance"`, fetched_at UTC)
- **성공·평가 기준:** Fake 어댑터로 재시도 횟수·대기 로직 테스트 / 전체 실패 시에도 `RawPriceBatch` 반환하고 `failed_tickers`에 전부 기록 / 실제 호출 스모크 테스트(수동)에서 SPY 5년치 수집 성공
- **제약:** 네트워크 호출은 이 모듈에서만. 원본 가공 금지(가공은 M02-02). 요청 간 최소 간격 설정 가능(요청 제한 대비)
- **오류:** 어댑터 자체 설정 오류만 `DataSourceError(DATA_SOURCE_UNAVAILABLE)`

### M02-02 데이터 정규화기

- **FR:** FR04
- **Input:** `RawPriceBatch`
- **Process:** 원본 → `PriceBar` 목록 (fx_symbol 데이터는 `FxRate` 목록으로 따로 변환) (티커 정규화, 날짜 `date` 변환, adj_close ≤ 0 또는 NaN 행 제거, 통화 USD 확인, source·fetched_at 복사) → PriceFrame 변환 함수 제공 `to_price_frame(bars) -> (DataFrame, PriceMeta)`
- **Output:** `list[PriceBar]`, `list[FxRate]`, 필요 시 `(PriceFrame, PriceMeta)`
- **성공·평가 기준:** 같은 원본이면 같은 결과 / 제거된 행 수를 반환값에 포함 / PriceFrame 계약(0-4) 검사 함수 통과
- **제약:** 보간·제외 판단 금지(M02-03 역할). 순수 함수(I/O 없음)

### M02-03 데이터 품질 판정기

- **FR:** FR05 / 업무 규칙 부록 A-3
- **Input:** PriceFrame(결측 포함), `required_tickers`(Benchmark + Spec 고정 목록 종목), `expected_calendar`(Benchmark의 거래일 목록), `AppConfig.data`
- **Process**
    1. 티커별 커버리지 = 유효 값이 있는 거래일 수 / 기대 거래일 수 (기간 = Backtest 기간 + 최대 lookback)
    2. 연속 1거래일 결측만 직전값으로 채움(`max_fill_days`), 채운 일수 기록 → `FILLED`
    3. 커버리지 < `coverage_threshold` 또는 2일 이상 연속 결측 → `EXCLUDED`(사유 기록)
    4. `EXCLUDED`인 티커가 `required_tickers`에 있으면 `DataQualityError(DATA_REQUIRED_MISSING)` (UC-C 2b·2c)
    5. 사용 가능 종목이 0개면 `DataQualityError(DATA_NO_USABLE_TICKER)`
- **Output:** `DataQualityReport` + 결측이 없는 PriceFrame(사용 가능 종목만)
- **성공·평가 기준:** 경계값 테스트(커버리지 0.95 정확히 = 통과, 0.9499 = 제외) / 2일 연속 결측 제외 / Benchmark 결측 시 예외 / 출력 PriceFrame에 NaN 없음
- **제약:** 값 생성 금지(C-07). 판정 기준은 설정에서만 읽음

### M02-04 시장 데이터 Repository

- **FR:** FR04 (출처·기준시점·수집시각과 함께 저장)
- **Input / Output (인터페이스)**
    
    ```python
    class MarketDataRepository(Protocol):
        def upsert_prices(self, bars: list[PriceBar]) -> int: ...                    # 반영 행 수
        def get_prices(self, tickers: list[str], start: date, end: date) -> tuple[pd.DataFrame, PriceMeta]: ...
        def covered_range(self, ticker: str) -> tuple[date, date] | None: ...
        def upsert_fx(self, rates: list[FxRate]) -> int: ...
        def get_fx_on_or_before(self, d: date) -> FxRate | None: ...
        def save_run_artifact(self, run_id: str, profile: UserProfile, spec: StrategySpec,
                              universe: UniverseResult, config: AppConfig) -> None: ...      # 재현용
        def save_constituents(self, rows: list[IndexConstituent]) -> None: ...
        def latest_constituents(self, index: IndexCode) -> list[IndexConstituent]: ...
        def log_fetch(self, source: str, target: str, start: date | None, end: date | None,
                      status: str, fetched_at: datetime, error: str | None) -> None: ...
        def save_step(self, rec: StepRecord) -> None: ...
        def get_steps(self, run_id: str) -> list[StepRecord]: ...
        def save_report(self, report: Report) -> None: ...
        def get_report(self, run_id: str) -> Report | None: ...
    ```
    
- **Process:** SQLAlchemy Core로 `SqliteRepository` 구현 (부록 B DDL). 자연키가 같은 행은 값이 다를 때만 갱신(upsert), 같으면 건너뜀. 캐시 판단 헬퍼 `needs_fetch(ticker, start, end)`: 저장 범위가 요청 범위를 덮고, 마지막 저장일이 직전 거래일 이상이면 False
- **성공·평가 기준:** 같은 데이터 두 번 upsert 시 두 번째 반영 0행 / 범위 조회 결과가 PriceFrame 계약 충족 / `needs_fetch` 경계 테스트 / 인메모리 SQLite로 전체 테스트 통과
- **제약:** C-10. 다른 모듈은 SQL·테이블명 모름. PostgreSQL 구현체를 같은 인터페이스로 추가할 수 있게 SQL 방언 의존 최소화 (upsert는 방언별 분기 허용)
- **오류:** `RepositoryError(REPO_WRITE_FAILED / REPO_READ_FAILED)`

### M02-05 지수 구성종목 수집기

- **FR:** FR04 / 결정로그 Universe 항목
- **Input:** `AppConfig.universe.indices`, 오늘 날짜, M02-04
- **Process**
    1. 인터페이스 `ConstituentSource.fetch(index) -> list[IndexConstituent]`. **출처는 구현자가 선택하고 명세(이 절)에 기록** (예: 공개 목록 페이지, ETF 보유 종목 파일 등). 출처명과 URL을 `source`에 저장
    2. 갱신 필요 판단: 최신 스냅샷 날짜 < 「직전 정기 변경일」이면 수집. 정기 변경일 = 3·6·9·12월 셋째 금요일 (Nasdaq-100도 같은 기준 사용)
    3. 결과 검사: SP500 행 수 495~510, NDX 98~105 (보통주 다중 클래스 고려), 티커 중복 없음, sector·industry 비어 있지 않음
    4. 통과하면 오늘 날짜를 snapshot_date로 M02-04에 저장. 실패하면 기존 스냅샷 유지 + 경고(가장 최근 스냅샷 날짜를 Report 한계에 표시)
- **Output:** 최신 `list[IndexConstituent]` (지수별)
- **성공·평가 기준:** 정기 변경일 계산 테스트(예: 2026-09-18이 9월 셋째 금요일) / 행 수 범위 위반 시 저장 안 함 / Fake 소스로 갱신·미갱신 분기 테스트
- **제약:** 정기 변경 사이의 수시 변경은 반영하지 않음(한계로 기록). 섹터·산업 분류는 GICS 명칭 기준으로 통일 🔶K3
- **출처 기록란 (구현자 작성):** `출처: ____ / URL: ____ / 갱신 방법: ____ / 확인일: ____`

## B. 전략·검증 — 담당: (미정)

- **담당 모듈:** M03-01, M03-02, M03-03, M03-04, M03-05, M04-01, M04-02, M01-01
- **인터페이스:** 제공: WeightSet(M03-04), ValidationResult, UniverseResult / 사용: PriceFrame(A), IndexConstituent(A), M00-02 스키마
- **팁:** M03-01~03은 순수 함수라 가짜 가격 데이터만으로 개발·테스트 가능

### M03-01 종목 선정 규칙

- **FR:** FR08
- **Input:** `candidates: list[str]`, `prices: PriceFrame`(as_of 전일까지), `params: dict`
- **Process (규칙별)**
    
    
    | 규칙 | params (기본값 / 허용 범위) | 계산 |
    | --- | --- | --- |
    | `fixed_list` | `tickers` (1~30개) | candidates와 무관하게 지정 목록 반환. 목록 중 데이터 없는 종목이 있으면 `StrategyError(STRATEGY_FIXED_TICKER_MISSING)` |
    | `low_volatility_top_n` | `n`=5 (1~30), `lookback_days`=252 (20~756) | 일간수익률 표준편차(ddof=1) × √252 → 오름차순 상위 n |
    | `momentum_top_n` | `n`=5 (1~30), `lookback_days`=252 (60~756), `skip_days`=21 (0~63) | 가격(t−skip)/가격(t−lookback) − 1 → 내림차순 상위 n |
    - 동순위: 티커 오름차순. lookback 기간 데이터가 부족한 종목은 후보에서 빼고 사유 기록
    - candidates 수 < n이면 있는 만큼 선택하고 `PARTIAL` 사유 기록 (0개면 `STRATEGY_EMPTY_SELECTION`)
- **Output:** `SelectionResult(selected: list[str], signals: list[TickerSignal], dropped: dict[str,str])` — signals에는 모든 후보의 지표값과 순위(근거용)
- **성공·평가 기준:** 손계산 예제(종목 4개, 30일)와 지표값 소수 6자리 일치 / 동순위 정렬 테스트 / 데이터 부족 종목 제외 테스트
- **제약:** C-03, C-06

### M03-02 비중 결정 규칙

- **FR:** FR08
- **Input:** `selected: list[str]`, `prices: PriceFrame`(as_of 전일까지), `params`
- **Process**
    
    
    | 규칙 | params | 계산 |
    | --- | --- | --- |
    | `equal` | 없음 | wᵢ = 1/n |
    | `inverse_volatility` | `lookback_days`=252 (20~756) | σᵢ = 연환산 변동성, wᵢ = (1/σᵢ) / Σ(1/σⱼ). σᵢ ≤ 1e-8이면 `STRATEGY_ZERO_VOL` |
- **Output:** `dict[str, float]` (합 1.0) + 근거용 `list[TickerSignal]`
- **성공·평가 기준:** 합 = 1 (오차 1e-9) / 손계산 예제 일치 / 종목 1개면 100%
- **제약:** 음수 비중 금지(롱 온리)

### M03-03 제약 적용 규칙

- **FR:** FR08 (사용자 제약 반영)
- **Input:** 두 가지 함수
    - `apply_exclusions(tickers, exclude) -> (list[str], dict[제외티커, 사유])`
    - `apply_caps(weights, max_all, per_ticker) -> dict[str,float]`
- **Process (apply_caps)**
    1. 종목별 상한 cᵢ = min(max_all, per_ticker.get(i, max_all))
    2. 실현 가능성: Σcᵢ < 1이면 `StrategyError(STRATEGY_CAP_INFEASIBLE)` (예: 3종목 × 25% < 100%)
    3. 반복: 상한 초과 종목을 cᵢ로 고정 → 남은 비중(1 − 고정 합)을 고정되지 않은 종목에 **기존 비중 비례**로 재분배 → 초과가 없을 때까지 (최대 n회)
- **Output:** 상한 적용 후 비중 (합 1.0)
- **성공·평가 기준:** 예제 [0.5, 0.3, 0.2], 상한 0.4 → [0.4, 0.36, 0.24] / 불가능 케이스 예외 / 재분배 후에도 모든 wᵢ ≤ cᵢ + 1e-9
- **제약:** 제외는 선정 **전**에 적용(제외 종목이 순위 계산에도 들어가지 않음)

### M03-04 전략 실행기 (Mapper)

- **FR:** FR08, FR10 (같은 함수로 기준일 비중과 Backtest 비중을 만들어 표시=실행을 구조적으로 보장)
- **Input:** `StrategySpec`(M04-01 통과), `universe: list[str]`, `prices: PriceFrame`(M02-03 통과), `as_of: date`
- **Process**
    1. 레지스트리: `SELECTION_REGISTRY: dict[SelectionRule, Callable]`, `WEIGHTING_REGISTRY: dict[WeightingRule, Callable]` (이름 → M03-01·M03-02 함수). 등록되지 않은 이름은 `STRATEGY_UNKNOWN_RULE`
    2. prices를 as_of 전 거래일까지 자름
    3. 후보 = (universe.mode=fixed ? spec.universe.tickers : 입력 universe) → `apply_exclusions`(Spec 제외 목록. Profile 제외가 Spec에 포함되어 있음은 M04-01이 보장)
    4. 선정(M03-01) → 비중(M03-02) → `apply_caps`(M03-03)
    5. `WeightSet` 생성 (spec_hash, pre_cap_weights, signals 포함)
- **Output:** `WeightSet`
- **성공·평가 기준:** 같은 입력 → 같은 WeightSet / 고정 목록 + 동일 비중 예제 / 레지스트리에 없는 규칙 예외 / M05-01이 이 함수만 호출해서 비중을 얻는지 코드 리뷰로 확인
- **제약:** Spec에 없는 파라미터 무시 금지(M04-01에서 거부). 규칙 함수 직접 호출은 이 모듈만

### M03-05 Universe 구성기

- **FR:** FR08 (규칙 기반 후보 탐색, UC-C 3단계의 LLM 없는 버전)
- **Input:** 지수별 최신 `list[IndexConstituent]`(M02-05/M02-04), `UserProfile`, `StrategySpec`, `AppConfig.universe`, `industry_map`
- **Process**
    1. spec.universe.mode=fixed면 그 목록 그대로 반환(필터 생략, criteria에 "fixed" 기록)
    2. 두 지수 합집합, 티커 중복 제거(이름·분류는 SP500 우선)
    3. 관심산업 필터: Profile.interest_industries → industry_map으로 GICS industry 목록 변환 → 해당 종목만. 관심산업이 비어 있으면 필터 생략
    4. 제외: Profile·Spec 제외 종목, `allow_etf=false`면 ETF(구성종목에는 원래 없음, 안전장치)
    5. 크기 제한: `max_size` 초과 시 티커 오름차순으로 자름. 이 기준은 임의적이라 🔶K5 (구성종목 스키마에 시가총액·지수 비중 필드를 추가해 큰 순으로 자를지)
    6. 결과가 0개면 `StrategyError(UNIVERSE_EMPTY)` (UC-C 3a), 사유에 사용된 필터 명시
- **Output:** `UniverseResult` (tickers, 스냅샷 날짜, 적용 기준, 제외 사유, 출처)
- **성공·평가 기준:** Fake 구성종목(20개)으로 산업 필터·제외·크기 제한 테스트 / 같은 스냅샷 + 같은 Profile → 같은 결과 / 결과가 M08-01 실행 기록에 저장되어 재실행 시 재사용 가능
- **제약:** 선견 편향·생존 편향 존재 → M06-02 한계 항목에 반드시 표시

### M04-01 Spec 정적 검증기

- **FR:** FR09 (정적), UC-C 6단계
- **Input:** `StrategySpec`(스키마 통과), `UserProfile`, `AppConfig`
- **Process:** 아래 규칙을 모두 검사해 이슈를 모아 반환 (첫 오류에서 멈추지 않음)
    
    
    | code | 검사 |
    | --- | --- |
    | `SPEC_UNKNOWN_RULE` | selection·weighting 규칙이 M03-04 레지스트리에 있는가 |
    | `SPEC_PARAM_MISSING` / `SPEC_PARAM_RANGE` / `SPEC_PARAM_UNKNOWN` | 규칙별 필수 파라미터·허용 범위(M03-01·M03-02 표)·모르는 파라미터 |
    | `SPEC_CAP_RANGE` | max_weight_all ∈ (0,1], 종목별 상한 ∈ [0,1] |
    | `SPEC_CAP_ORDER` | 종목별 상한 ≤ 전체 상한 |
    | `SPEC_CONSTRAINT_CONFLICT` | 제외 종목 ∩ 종목별 상한 ≠ ∅, 또는 fixed_list ∩ 제외 종목 ≠ ∅ |
    | `SPEC_PROFILE_VIOLATION` | Spec 제약이 Profile보다 느슨함: Spec 전체 상한 > Profile 전체 상한, Profile 종목별 상한보다 큰 Spec 값, Profile 제외 종목이 Spec 제외에 없음 |
    | `SPEC_CAP_INFEASIBLE` | 선정 개수 n(또는 fixed_list 길이) × 전체 상한 < 1 |
    | `SPEC_BENCHMARK` | benchmark ∈ allowed_benchmarks |
    | `SPEC_PERIOD` | period_years ∈ [1, 20] |
- **Output:** `ValidationResult`. 실패 시 M08-02가 `SpecValidationError`로 중단 (프로토타입은 고정 Spec이라 재생성 없음, UC-C 6a의 재생성은 LLM 단계에서)
- **성공·평가 기준:** 규칙마다 위반 예제 1개 이상 → 정확한 code / 부록 A 예시 Spec 통과 / 사전에 삽입한 Profile 제약 위반 탐지율 100% (0928 F4 목표 95% 이상 충족)
- **제약:** Spec을 수정하지 않음(자동 보정 금지)

### M04-02 비중 동적 검증기

- **FR:** FR09 (동적), UC-C 7단계
- **Input:** `WeightSet`, `StrategySpec`, universe 목록
- **Process:** 검사 code
    - `WEIGHT_SUM`: |Σw − 1| ≤ 1e-6
    - `WEIGHT_NEGATIVE`: 모든 w ≥ 0
    - `WEIGHT_CAP`: wᵢ ≤ cᵢ + 1e-9
    - `WEIGHT_EXCLUDED`: 제외 종목 비중 = 0 (목록에 없음)
    - `WEIGHT_OUTSIDE_UNIVERSE`: 모든 종목 ∈ universe(또는 fixed 목록)
    - `WEIGHT_EMPTY`: 종목 수 ≥ 1
- **Output:** `ValidationResult` (실패 시 호출자가 `WeightValidationError`)
- **성공·평가 기준:** 각 code별 위반 예제 탐지 / M05-01의 **모든 리밸런싱 시점**과 기준일 비중에 적용됨
- **제약:** 순수 함수

### M01-01 Profile 로더·검증기

- **FR:** FR01 (프로토타입: 고정 파일 불러오기·검증만) / UC001 9단계 업무 규칙(부록 A-2)
- **Input:** `inputs/profile.json` 경로, `AppConfig`(industry_map 키 확인용), 지원 종목 집합(선택: 최신 구성종목 티커 집합, 없으면 종목 존재 검사 생략하고 경고)
- **Process**
    1. JSON 읽기 → `UserProfile` 스키마 검증
    2. 업무 규칙 검사 (모두 모아서 한 번에 보고)
        - `PROFILE_INDUSTRY_UNKNOWN`: interest_industries가 industry_map 키에 없음
        - `PROFILE_CAP_ORDER`: 종목별 상한 > 전체 공통 상한
        - `PROFILE_CAP_CONFLICT`: 같은 종목이 제외 목록과 종목별 상한에 동시 존재
        - `PROFILE_TICKER_UNKNOWN`: 제약조건 종목이 지원 종목 집합에 없음
        - `PROFILE_RISK_FLAG`: risk_type ≠ risk_type_computed인데 risk_type_overridden=false (불일치)
    3. 티커 표기 정규화(대문자, `.`→`-`)
- **Output:** `UserProfile`(정규화된 사본) 또는 `InputError(code=PROFILE_INVALID, details={issues})`
- **성공·평가 기준:** 부록 A 예시 통과 / 위 규칙별 위반 케이스 각 1개 이상 테스트에서 정확한 code 반환 / 위반이 여러 개면 전부 보고
- **제약:** 파일을 수정하지 않음. 금액은 원화 정수

## C. 백테스트 — 담당: (미정)

- **담당 모듈:** M05-01, M05-02, M05-03, M00-01
- **인터페이스:** 제공: BacktestResult, MetricsBundle, AppConfig / 사용: WeightSet 생성 함수(B의 M03-04), 비중 검증(B의 M04-02), PriceFrame(A)
- **팁:** M05-01은 처음엔 고정 비중 함수로 개발하고 MS2에서 M03-04로 교체

### M05-01 Backtest 시뮬레이터

- **FR:** FR11, FR12
- **Input:** `StrategySpec`, `universe`, PriceFrame(M02-03 통과, 기간 = 시작일 − 최대 lookback ~ 종료일), Benchmark 가격 Series, `CalcConditions` 생성용 값(설정, 무위험수익률(M05-03), 투자금 원화, 환율·기준일)
- **Process**
    1. 기간: end = 데이터의 마지막 거래일, start = end − period_years년 이후 첫 거래일
    2. 초기자본 USD = investment_amount_krw / fx_rate(fx_as_of = end 이하 가장 최근 환율일)
    3. 리밸런싱일 = start + 각 분기(1·4·7·10월) **첫 거래일** 🔶K2
    4. 각 리밸런싱일 t: M03-04로 WeightSet(as_of=t) → M04-02 검증 → 목표 비중으로 조정. 회전율 = Σ|w_target − w_drift|, 비용 = 회전율 × cost_bps/10,000 × 평가액 (첫 매수도 회전율 1.0으로 비용 반영)
    5. 리밸런싱 사이: 보유 수량 고정(비중은 가격에 따라 변함), 매일 평가액 = Σ수량 × 수정종가
    6. 체결 가정: 리밸런싱일 **종가**에 체결(신호는 전일 종가까지, C-06)
    7. Benchmark: 같은 start·초기자본으로 매수 후 보유, 첫 매수 비용 동일 적용
- **Output:** `BacktestResult` (일별 평가액, Benchmark 곡선, 리밸런싱 기록, CalcConditions)
- **성공·평가 기준**
    - 손계산 예제: 2종목·10거래일·리밸런싱 1회 → 평가액 소수 6자리 일치
    - 비용 0이면 동일 비중 buy&hold 결과가 단순 계산과 일치
    - 같은 입력 2회 실행 결과 동일(재현율 100%, 0928 F5 목표)
    - 리밸런싱마다 M04-02 통과 기록
- **제약:** 구현은 pandas/NumPy 기준. vectorbt 사용 시에도 위 손계산 예제를 통과해야 함 🔶K4. 공매도·레버리지·현금 보유 없음(항상 100% 투자). 배당은 수정종가로 반영된 것으로 간주

### M05-02 성과 지표 계산기

- **FR:** FR11
- **Input:** 평가액 Series(전략·Benchmark), 무위험수익률(연), `trading_days_per_year`
- **Process (정의)**
    - 일간수익률 rₜ = Vₜ/Vₜ₋₁ − 1
    - 누적수익률 = V_T / V_0 − 1
    - CAGR = (V_T / V_0)^(1/Y) − 1, Y = (마지막일 − 시작일).days / 365.25 🔶K6
    - 연환산 변동성 = std(r, ddof=1) × √252
    - Sharpe = (mean(r) − r_f,일) / std(r, ddof=1) × √252, r_f,일 = (1 + r_f)^(1/252) − 1
    - MDD = minₜ(Vₜ / maxₛ≤ₜ Vₛ − 1), 고점일·저점일 함께
    - 초과 누적수익률 = 전략 누적 − BM 누적, 초과 CAGR = 전략 CAGR − BM CAGR
- **Output:** `MetricsBundle`
- **성공·평가 기준:** 알려진 시계열(예: 매일 +1% 10일)로 각 지표 손계산 일치 / 변동성 0이면 Sharpe 계산 대신 `METRIC_UNDEFINED` 표시(예외 아님) / 6개 필수 지표 산출 성공률 100%
- **제약:** 순수 함수. 반올림 금지(표시 반올림은 M06-02)

### M05-03 무위험수익률 제공자

- **FR:** FR12
- **Input:** `AppConfig.risk_free`, 기간(start, end)
- **Process:** 인터페이스 `RiskFreeProvider.annual_rate(start, end) -> float`. 구현체 `FixedRateProvider`(config 값 반환). 추후 `TreasuryRateProvider`(국채금리 조회, 기간 평균) 추가
- **Output:** 연 무위험수익률(소수) + 출처 문자열(예: `"config:fixed"`)
- **성공·평가 기준:** config 값 변경이 Report 계산 조건과 Sharpe에 반영 / 다른 모듈 수정 없이 구현체 교체 가능(인터페이스 테스트)
- **제약:** 값의 출처를 Report 「계산 조건」에 표시

### M00-01 설정 (Config)

- **FR:** FR12 (계산 조건을 설정으로 정의·기록)
- **Input:** `config/config.toml`, `config/industry_map.toml` (경로는 CLI 인자 또는 기본값). 환경변수 `MYFINSIGHT_*`로 개별 값 덮어쓰기 허용
- **Process:** 파일 읽기 → `AppConfig`(Pydantic) 검증 → 읽기 전용 객체로 반환
- **Output:** `AppConfig`
- **스키마:** 「2. 모듈별 상세 명세 → 공통 기반 → M00-01」의 코드 블록과 「부록 A config.toml」 참고
- **성공·평가 기준:** 기본값만으로 로드 성공 / 범위 밖 값(예: cost_bps=-1)은 `ConfigError` / 같은 파일이면 같은 객체(동등성) / 로드된 설정 전체를 Report의 「계산 조건」에 그대로 출력할 수 있음
- **제약:** 실행 중 변경 불가(frozen). 비밀값(API 키)은 프로토타입에 없음
- **오류:** `CONFIG_INVALID`, `CONFIG_NOT_FOUND`

## D. 결과·통합 — 담당: (미정)

- **담당 모듈:** M06-01, M06-02, M04-03, M08-01, M08-02, M00-02
- **인터페이스:** 제공: Report, StepRecord, 파이프라인(CLI), 스키마 관리 / 사용: 모든 묶음의 출력, Repository(A)
- **팁:** 통합 테스트(Fake 어댑터로 끝까지 실행)와 스키마 변경 공지를 책임

### M06-01 근거 생성기

- **FR:** FR26 (수치 근거 + 출처·기준시점), FR05
- **Input:** `UniverseResult`, 기준일 `WeightSet`, `DataQualityReport`, `MetricsBundle`, `UserProfile`, `PriceMeta`
- **Process:** 아래 템플릿으로 `EvidenceItem` 생성 (문장의 모든 숫자는 values에 원본 저장, 표시는 부록 D 규칙)
    
    
    | kind | 템플릿 (예) |
    | --- | --- |
    | universe | "S&P 500·Nasdaq-100 구성종목({snapshot_date} 기준) 중 관심산업 {industries}에 해당하는 {k}개 종목을 후보로 사용했습니다." |
    | selection (저변동성) | "{ticker}: 최근 {lookback}거래일 연환산 변동성 {vol}, 후보 {N}개 중 {rank}위 → 저변동성 상위 {n}개에 포함" |
    | selection (모멘텀) | "{ticker}: {lookback}거래일 수익률(최근 {skip}일 제외) {mom}, 후보 {N}개 중 {rank}위" |
    | selection (고정 목록) | "{ticker}: 전략에 지정된 종목" |
    | weight | "{ticker}: {rule_name} 방식으로 {w}" |
    | cap | "{ticker}: 상한 {cap} 적용으로 {w_before} → {w_after}" |
    | metric | "Backtest 기간 최대낙폭 {mdd}는 투자성향의 손실 감내 수준 -{loss_tol}% {이내이다/를 초과한다}" |
    | limitation | 데이터 부족으로 제외된 종목과 사유 (M02-03 excluded) |
    - 모든 항목에 `source`(예: "yfinance 수정종가", 구성종목 출처)와 `as_of` 부착
- **Output:** `list[EvidenceItem]`
- **성공·평가 기준:** 선정된 모든 종목에 selection·weight 근거 1개 이상 / 모든 항목 source·as_of 존재(표시율 100%, 0928 F6 목표) / values의 수치가 원본과 일치(M04-03에서 확인)
- **제약:** 템플릿 외 문장 생성 금지(LLM 미사용). 투자 권유 표현("사세요", "유망") 금지

### M06-02 Report 조립기

- **FR:** FR14 / UC003 데이터 정의(부록 B)
- **Input:** `run_id`, `UserProfile`, `StrategySpec`, 기준일 `WeightSet`, `BacktestResult`, `MetricsBundle`, `list[EvidenceItem]`, `UniverseResult`, `DataQualityReport`, `list[StepRecord]`(M08-01), 종목명 사전(구성종목)
- **Process**
    1. `ReportData` 생성: 배분표 = 기준일 비중 × 초기자본(USD·원화), 한계 목록 자동 구성
        - 고정: "Backtest 결과는 과거 데이터 기반 가상 성과이며 미래 수익을 보장하지 않습니다"(C008)
        - 고정: "현재 지수 구성종목으로 과거를 계산하므로 생존·선견 편향이 있습니다"
        - 조건부: 데이터 부족 제외 종목, 구성종목 스냅샷이 직전 정기 변경일보다 오래됨, 정기 변경 사이 수시 변경 미반영
    2. Markdown 렌더링 (프로토타입 섹션 순서, 부록 B 번호):
        
        `1 요약 → 2 투자조건 → 3 Portfolio 구성(표) → 4 전략 규칙 → 5 구성 근거 → 7 Backtest 성과(표, BM 대비) → 8 Risk(MDD vs 손실 감내) → 10 계산 조건 → 11 한계·주의 → 12 분석 과정 요약`
        
        (6 기업·시장 정보, 9 LLM 해석은 프로토타입 제외 — 9는 템플릿 한 줄 요약으로 대체 가능)
        
    3. 렌더러는 텍스트와 함께 「표시값 목록」(필드 경로 → 표시 문자열)을 반환 (M04-03 CONSIST_TEXT용)
    4. 저장하지 않고 `Report`만 반환. 저장(M02-04, `outputs/report_{run_id}.md`)은 **M04-03 통과 후 M08-02가** 수행
- **Output:** `Report`
- **성공·평가 기준:** 프로토타입 필수 섹션 10개 모두 존재(표시율 100%) / 같은 ReportData → 같은 텍스트 / 원화 금액 합 = 투자금(반올림 오차 종목 수 원 이내)
- **제약:** 숫자 표시는 부록 D 규칙만 사용. 계산 금지(값은 입력에서만, 단 금액 = 비중 × 자본 곱셈은 허용하고 M04-03이 검증)

### M04-03 일치성 검사기

- **FR:** FR10 (표시=실행), FR25 (Report 수치 불일치 차단)
- **Input:** `ReportData`, 실행에 쓰인 `StrategySpec`·`WeightSet`(기준일)·`BacktestResult`·`MetricsBundle`, 렌더링된 `text_markdown`
- **Process**
    1. `CONSIST_SPEC`: ReportData.spec_hash == 실행 Spec 해시 == BacktestResult.spec_hash
    2. `CONSIST_WEIGHTS`: Report 배분표 비중 == 기준일 WeightSet (종목 집합 동일, 값 오차 ≤ 1e-6)
    3. `CONSIST_AMOUNT`: amount_usd = weight × initial_capital_usd, amount_krw = round(amount_usd × fx) (±1원)
    4. `CONSIST_METRICS`: ReportData.metrics == 계산된 MetricsBundle (필드별 오차 ≤ 1e-9)
    5. `CONSIST_TEXT`: 텍스트에 표시된 주요 수치(비중, 지표)가 ReportData 값을 표시 규칙(부록 D)으로 반올림한 문자열과 같은지 — 렌더러가 표시값 목록을 함께 반환하고 이를 대조
    6. `CONSIST_EVIDENCE`: 모든 EvidenceItem에 source·as_of 존재, values의 수치가 signals·metrics 원본과 같음
- **Output:** `ValidationResult`. 실패 시 M08-02가 Report를 저장·출력하지 않고 `ConsistencyError`로 실패 처리
- **성공·평가 기준:** 각 항목별로 일부러 값을 바꾼 ReportData를 넣었을 때 100% 탐지 / 정상 실행에서는 오탐 0
- **제약:** 검사만 하고 값을 고치지 않음

### M08-01 실행 기록기 (Run Logger)

- **FR:** FR24, R9
- **Input:** `run_id`, 단계 이름, 상태·요약·출처·오류
- **Process (API)**
    
    ```python
    class RunLogger:
        def __init__(self, run_id: str, repo: MarketDataRepository): ...
        @contextmanager
        def step(self, name: str) -> Iterator["StepHandle"]: ...   # 진입 시 STARTED 기록, 정상 종료 SUCCESS, 예외 시 FAILED(+code, message) 후 예외 재전파
        # StepHandle.set_summary(text), add_source(name), mark_partial(reason)
        def records(self) -> list[StepRecord]: ...
        def summary_lines(self) -> list[str]: ...                  # Report 12번 섹션용 "데이터 조회: 성공 (52/55, 3개 제외)" 형태
    ```
    
    - 단계 이름 표준: `load_profile`, `validate_spec`, `constituents`, `universe`, `fetch_prices`, `data_quality`, `compute_weights`, `validate_weights`, `backtest`, `metrics`, `evidence`, `report`, `consistency`
- **Output:** `StepRecord` 저장(M02-04), 요약 문자열
- **성공·평가 기준:** 정상 실행 후 표준 단계 13개 기록 조회 가능 / 예외 발생 단계는 FAILED + code 기록, 이후 단계는 기록 없음 / 기록 실패가 분석 자체를 실패시키지 않음(기록 실패는 logging 경고)
- **제약:** 흐름 제어 금지(기록만). 시각은 UTC

### M08-02 파이프라인 실행기

- **FR:** FR24, FR25 (오류 시 중단·차단), 추후 LangGraph Orchestrator로 교체
- **Input:** CLI `python -m myfinsight run --profile inputs/profile.json --spec inputs/spec.json [--config config/config.toml] [--refresh-constituents]`
- **Process**
    1. run_id 발급(`YYYYMMDD-HHMMSS-<6자리 해시>`), RunLogger 생성
    2. 0-2 실행 흐름 순서로 각 모듈 호출, 각 호출을 `logger.step()`으로 감쌈
    3. 오류 처리 정책
        
        
        | 상황 | 처리 |
        | --- | --- |
        | 일부 종목 데이터 제외(M02-03 EXCLUDED, 필수 아님) | 계속, 단계 PARTIAL, 한계에 기록 |
        | 필수 데이터 실패, Universe 0개, Spec·비중 검증 실패, Backtest 오류, 일치성 실패 | **중단**, Report 미생성, 실패 요약 출력 |
        | 구성종목 갱신 실패(기존 스냅샷 있음) | 계속, 경고·한계 기록 |
    4. Universe 확정 직후 `save_run_artifact`로 입력·Universe·설정 저장(재현용)
    5. M04-03 통과 시에만 Report 저장, Report 경로와 요약 지표를 콘솔에 출력
- **Output:** 종료 코드 `0`(성공) / `1`(분석 실패: 사유 출력) / `2`(입력·설정 오류), Report 파일, 실행 기록
- **성공·평가 기준:** 부록 A 입력으로 끝까지 실행되어 Report 생성(통합 테스트는 Fake 어댑터) / 각 중단 조건별 종료 코드 1과 실패 단계·사유 출력 / 명령 한 줄로 실행
- **제약:** 비즈니스 로직 금지(호출 순서·오류 정책만). 단계 함수는 모듈 공개 API만 사용

### M00-02 도메인 스키마 + 공통 오류

- **FR:** 전체 (모듈 간 계약)
- **Input / Output:** 없음 (다른 모듈이 import)
- **Process:** Pydantic v2 모델과 Enum, 예외 클래스 정의. 모든 모델 `model_config = ConfigDict(extra="forbid")`
- **스키마:** 코드 전문은 「2. 모듈별 상세 명세 → 공통 기반 → M00-02」 토글 참고 (중복 방지를 위해 여기서는 생략, 담당자 D가 단일 원본 관리)
    - Enum: RiskType(금융권 5단계), SelectionRule, WeightingRule, StepStatus, DataStatus, IndexCode
    - Profile: ProfileConstraints, UserProfile / Spec: SelectionSpec, WeightingSpec, ConstraintSpec, UniverseSpec, StrategySpec(+spec_hash)
    - 시장 데이터: RawPriceBatch, PriceBar, FxRate, PriceMeta, TickerQuality, DataQualityReport, IndexConstituent, UniverseResult
    - 전략·검증: TickerSignal, WeightSet, ValidationIssue, ValidationResult
    - Backtest: CalcConditions, RebalanceRecord, BacktestResult, PerformanceMetrics, MetricsBundle
    - 근거·Report: EvidenceItem, AllocationRow, ReportData, Report(+display_values) / 실행 기록: StepRecord
    - 오류: MyFinSightError 하위 ConfigError, InputError, DataSourceError, DataQualityError, SpecValidationError, WeightValidationError, StrategyError, BacktestError, ConsistencyError, RepositoryError
- **성공·평가 기준:** 모든 모델이 JSON 직렬화·역직렬화 왕복 시 동일 / `extra="forbid"`로 오타 필드 거부 / 예시 profile.json·spec.json(부록 A)이 검증 통과
- **제약:** 스키마 변경 시 버전 메모를 남기고 영향 모듈을 함께 수정. 모듈은 스키마를 상속·확장하지 않고 그대로 사용