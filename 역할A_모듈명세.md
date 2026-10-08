# 역할 A 모듈 명세 (F2 금융 데이터 관리)

「MyFinSight 프로토타입 모듈 명세 & 분배」의 역할 A 부분(M02-01~M02-05)을 실제 구현 기준으로 다시 씀.
M02-06(교차검증)은 추가 모듈. 형식은 원 명세와 같게 FR · Input · Process · Output · 성공·평가 기준 · 제약 · 오류 순.

- 코드: `src/myfinsight/data/` (모듈), `src/myfinsight/schemas/` (공통 스키마)
- 원 명세 대비 추가한 것은 **(추가)** 로 표시함. 추가 이유는 각 절에 적음
- DB 칸 설명은 7절

## 1. 범위

| 항목 | 내용 |
|---|---|
| 시장 | 미국(S&P 500, Nasdaq-100), 한국(KOSPI 200) (추가: 한국) |
| 데이터 | 일별 가격·환율 (명세) / 재무·뉴스 (추가: 확장 단계 테이블) |
| 출처 | 가격: KIS, Alpaca, yfinance, Tiingo / 환율: yfinance / 재무: DART, SEC EDGAR / 뉴스: 네이버, NewsAPI, Google News RSS / 구성종목: 위키백과, KRX 표 |
| DB | PostgreSQL 기본(AWS Lightsail, 서울). 같은 코드로 SQLite 교체 가능 (테스트·혼자 개발) |
| 출처 원칙 | 공식 API 를 주 출처로, yfinance 는 보완·교차검증용 |

## 2. 전체 흐름

```
외부 출처 (KIS·Alpaca·yfinance·Tiingo·DART·SEC EDGAR·뉴스)
   │
   ▼
M02-01 수집 어댑터 ──▶ M02-02 정규화 ──▶ M02-04 Repository / DB ◀── M02-05 구성종목 (저장)
                                             │        ▲
                                       읽기  ▼        │ CONSENSUS 저장
                                       M02-06 교차검증 (추가)
                                             │
                                서비스가 읽은 뒤 판정
                                             ▼
                                   M02-03 품질 판정 ──▶ 분석용 PriceFrame (결측 없음) ──▶ Strategy / Backtest
```

두 갈래로 돎.

| 갈래 | 언제 | 순서 |
|---|---|---|
| 정기 수집 (추가) | GitHub Actions 예약 실행 (`jobs.py`) | M02-05 → M02-01 → M02-02 → M02-04 저장 → M02-06 교차검증 |
| 백테스트 실행 (명세 0-2 흐름 3번) | M08-02 파이프라인이 부름 | M02-04 캐시 확인 → (없으면) M02-01 → M02-02 → M02-04 → M02-04 조회 → M02-03 판정 |

- 품질 판정(M02-03)은 DB 저장 단계가 아니라 **백테스트 직전**에 함. 판정 기준이 Backtest 기간·Benchmark·필수 종목에 따라 달라서임.
- 교차검증(M02-06)은 저장된 값을 읽어 비교하고 결과를 다시 저장함. M02-03 은 그 결과(MISMATCH 날 수)를 경고로만 받음.
- 백테스트용 연결 함수: `price_loader.load_prices` (M02-01·02·04 공개 함수만 이어 붙인 것).

## 3. 공통 스키마 (M00-02 중 역할 A 부분)

파일: `schemas/market.py` (명세 M00-02), `schemas/market_ext.py` (추가: 재무·뉴스·종목 마스터).
모든 모델은 `extra="forbid"` (모르는 칸이 오면 오류).

### 3-1. 시장 데이터 (명세 + 추가 칸)

| 모델 | 쓰는 곳 | 칸 |
|---|---|---|
| `IndexCode` | M02-05 | `SP500`, `NDX`, `KOSPI200`(추가) |
| `DataStatus` | M02-03 | `OK`, `FILLED`, `EXCLUDED` |
| `RawPriceBatch` | M02-01 출력 | `source`, `requested_tickers`, `start`, `end`, `fetched_at`(UTC), `payload`(원본), `failed_tickers`(티커 → 사유) |
| `PriceBar` | M02-02 출력 행 | `ticker`, `date`, `adj_close`(>0), `volume`(≥0, 선택), `currency`(`USD`·`KRW`(추가)), `source`, `fetched_at` / 추가: `open`·`high`·`low`·`close`(선택, >0) |
| `FxRate` | M02-02 출력 | `pair`(=`USDKRW`), `date`, `rate`(>0), `source`, `fetched_at` |
| `PriceMeta` | PriceFrame 과 함께 | `source`, `as_of`, `fetched_at`, `tickers` / 추가: `currency`(기본 `USD`) |
| `TickerQuality` | M02-03 | `ticker`, `coverage`, `filled_days`, `status`, `reason`, `is_required` / 추가: `mismatch_days`(기본 0) |
| `DataQualityReport` | M02-03 출력 | `as_of`, `expected_days`, `items`, `usable_tickers`, `excluded`(티커 → 사유) / 추가: `warnings` |
| `IndexConstituent` | M02-05 출력 행 | `index_code`, `ticker`, `name`, `sector`, `industry`, `snapshot_date`, `source`, `fetched_at` |

- PriceFrame 계약(명세 0-4)은 그대로: index = 날짜, columns = 티커(yfinance 표기), values = float64 수정종가. 결측은 NaN, M02-03 통과 뒤에는 결측 없음.
- 추가 규칙: 한 PriceFrame 은 한 통화만 담음 (`PriceMeta.currency`). 한국 종목 값은 원 단위.
- 티커 표기는 yfinance 기준: `AAPL`, `BRK-B`, `005930.KS`, `000660.KS`. `normalize_ticker` 가 `BRK.B` → `BRK-B` 로 맞춤.

### 3-2. 확장 모델 (추가)

| 모델 | 쓰는 곳 | 칸 |
|---|---|---|
| `RawFinancialBatch` | 재무 어댑터 출력 | `source`, `requested_keys`(DART 고유번호·CIK), `start`, `end`(공시일 기준), `fetched_at`, `payload`, `failed_keys` |
| `RawNewsBatch` | 뉴스 어댑터 출력 | `source`, `requested_keys`(검색어), `start`, `end`(발행일 기준), `fetched_at`, `payload`, `failed_keys` |
| `AssetInfo` | 종목 마스터 (`assets`) | 7-2 와 같음 |
| `FinancialRow` | 재무 한 행 (`financials`) | 7-8 과 같음 |
| `NewsRow` | 기사 한 건 (`news`) | 7-9 와 같음 |

모양은 `RawPriceBatch` 와 같게 맞춤. 키가 티커가 아닐 수 있어(고유번호·CIK·검색어) 이름만 `requested_keys` / `failed_keys`.

## 4. 설정 (AppConfig.data · 수집 설정)

| 설정 | 기본값 | 쓰는 모듈 |
|---|---|---|
| `retry_max` | 3 | M02-01 재시도 횟수 |
| `retry_backoff_sec` | 1.0 | M02-01 재시도 대기 기준 |
| `fx_symbol` | `KRW=X` | M02-01·02 환율 심볼 |
| `coverage_threshold` | 0.95 | M02-03 커버리지 기준 |
| `max_fill_days` | 1 | M02-03 직전값 채우기 최대 연속 일수 |
| `cache_max_age_days` | 1 | M02-04 `needs_fetch` (직전 거래일까지 있으면 캐시 사용) |
| `PRICE_PRIORITY_US` / `PRICE_PRIORITY_KR` (추가, `.env`) | `ALPACA,TIINGO,YFINANCE` / `YFINANCE,KIS` | M02-04 출처 고르기, M02-06 기준값 |
| `BACKFILL_YEARS`, `FIN_YEARS`, `FIN_REFRESH_DAYS`, `NEWS_*` (추가, `.env`) | 1, 1, 7, 6절 | 정기 수집 |

## 5. 모듈

### M02-01 가격 수집 어댑터

- **FR**: FR04
- **Input**: `tickers: list[str]`, `start: date`, `end: date`, `AppConfig.data`
- **Process**
  1. 인터페이스 `PriceSourceAdapter.fetch(tickers, start, end) -> RawPriceBatch`. 구현체 4개 (아래 표).
  2. 공통 부모 `RetryingFetcher` 가 배치 분할·재시도·요청 간격을 맡음. 구현체는 한 번 요청(`_fetch_batch_once`)만 구현.
  3. 재시도: 실패한 티커만 최대 `retry_max` 회. k 번째 재시도 전 대기 = `retry_backoff_sec × 2^(k-1)`.
  4. 재시도 뒤에도 실패한 티커는 `failed_tickers` 에 사유와 함께 기록 (예외로 멈추지 않음). 정상 응답인데 데이터가 없으면 사유 `요청 기간에 데이터 없음`, 다시 요청 안 함.
  5. 요청 간 최소 간격(`min_interval_sec`)을 출처별로 둠 (요청 제한 대비).
  6. 환율(`fx_symbol`)은 yfinance 어댑터가 같은 방식으로 받음.
  7. 묶음 요청을 주는 출처(Alpaca, yfinance)는 여러 종목을 한 번에 요청하고, 빠진 종목만 한 종목씩 다시 요청함.
  8. (추가) 같은 부모를 쓰는 재무·뉴스 어댑터 5개. 출력만 `RawFinancialBatch` / `RawNewsBatch`.
- **payload 형식** (M02-01 → M02-02 약속)

  ```
  {"<티커>": [{"date": "2026-09-30", "adj_close": 123.45, "volume": 1000000,
              "open": ..., "high": ..., "low": ..., "close": ..., "currency": "USD"}, ...]}
  ```

  키는 요청 표기 그대로. 빈 값·0 이하 값도 원본대로 둠 (제거는 M02-02). `open`~`currency` 는 출처가 주면 붙음.

- **구현체**

  | 어댑터 | `source` | 키 | 묶음 | 간격(초) | 수정종가 | API 키 |
  |---|---|---|---|---|---|---|
  | `KisPriceAdapter` | KIS | 6자리 종목코드 | 1 | 0.1 | 분할 반영, 배당 미반영 | 필요 |
  | `AlpacaPriceAdapter` | ALPACA | 미국 티커 (`BRK.B`) | 50 | 0.3 | 분할+배당 | 필요 |
  | `YFinancePriceAdapter` | YFINANCE | yfinance 표기, `KRW=X` | 20 | 0.5 | 분할+배당 (`auto_adjust=False` 의 Adj Close) | 불필요 |
  | `TiingoPriceAdapter` | TIINGO | 미국 티커 | 1 | 0 | 분할+배당 (`adjClose`) | 필요 |
  | `DartFinancialAdapter` (추가) | DART | 고유번호 8자리 (6자리 종목코드도 됨) | 1 | 0 (크롤러 0.4) | - | 필요 |
  | `SecFinancialAdapter` (추가) | SEC_EDGAR | CIK (티커도 됨) | 1 | 0.15 | - | 키 없음, `SEC_USER_AGENT`(이름 이메일) 필요 |
  | `NaverNewsAdapter` (추가) | NAVER_NEWS | 한국어 검색어 | 1 | 0 | - | 필요 |
  | `NewsApiAdapter` (추가) | NEWSAPI | 영어 검색어 | 1 | 0 | - | 필요 |
  | `GoogleNewsRssAdapter` (추가) | GOOGLE_RSS | 검색어 (한국어·영어) | 1 | 0 | - | 불필요 |

  - 종가(`close`)는 모든 출처가 분할만 보정한 값으로 맞춤 (Tiingo 원본 close 는 무보정이라 splitFactor 로 직접 보정).
  - 고르기: `adapters/factory.py` 의 `price_adapter(source)`, `financial_adapter(source)`, `news_adapter(source)`. 팀원 코드는 이것만 씀.
- **Output**: `RawPriceBatch` (원본 payload 보존, `source` = 출처 이름 대문자, `fetched_at` UTC)
- **성공·평가 기준**: 가짜 크롤러로 재시도 횟수·대기 시간 테스트 / 전체 실패 때도 `RawPriceBatch` 를 돌려주고 `failed_tickers` 에 전부 기록 / 묶음 요청에서 빠진 종목만 다시 요청 / 실제 호출 스모크 테스트(`scripts/try_adapters.py`, 수동)
- **제약**: 네트워크 호출은 이 모듈(크롤러 포함)에서만. 원본 가공 금지(가공은 M02-02). API 키는 `.env` 에서만 읽음
- **오류**: 설정 오류만 `DataSourceError`. API 키가 없으면 `DATA_SOURCE_CONFIG` 로 바로 멈춤 (재시도 안 함). 그 밖의 오류는 해당 티커만 실패 목록에 남김

### M02-02 데이터 정규화기

- **FR**: FR04
- **Input**: `RawPriceBatch` (추가: `RawFinancialBatch`, `RawNewsBatch`)
- **Process**
  1. `normalize(batch, fx_symbol)`: 원본 → `PriceBar` 목록. `fx_symbol` 데이터는 `FxRate(USDKRW)` 목록으로 따로 바꿈.
  2. 티커 정규화(대문자, `.` → `-`, `.KS`·`.KQ` 유지), 날짜를 `date` 로, `source`·`fetched_at` 복사.
  3. 통화: 행에 `currency` 가 있으면 그것, 없으면 `.KS`·`.KQ` 는 KRW, 나머지 USD (추가: KRW).
  4. 행 버리기 (사유별로 셈):

     | 사유 | 조건 |
     |---|---|
     | `invalid_price` | `adj_close` 가 비었거나 NaN·숫자 아님·0 이하 |
     | `invalid_date` | 날짜를 읽을 수 없음 |
     | `unsupported_currency` | USD·KRW 가 아님 |
     | `duplicate` | 같은 (티커, 날짜) 가 이미 있음 (`BRK.B` 와 `BRK-B` 를 둘 다 요청 등) |

     `open`·`high`·`low`·`close` 가 잘못된 값이면 행은 두고 그 칸만 비움.
  5. `to_price_frame(bars, currency=)` → `(PriceFrame, PriceMeta)`. `PriceMeta.source` = 출처 이름들을 `+` 로 이음, `fetched_at` = 가장 오래된 수집 시각.
  6. (추가) `normalize_financials(batch, key_to_asset)` → `FinancialRow` 목록. 모르는 종목, 값·공시일 없는 행 버림.
  7. (추가) `normalize_news(batch, query_to_asset)` → `NewsRow` 목록. 제목·주소·발행 시각 없는 기사 버림, 같은 (종목, url) 은 한 건.
  8. (추가) 종목 ID: `asset_id_for` (`005930.KS` → `KR-005930`, `BRK-B` → `US-BRK-B`), `default_asset` (종목 마스터 기본 행).
- **Output**: `NormalizeResult` (`bars`, `fx`, `dropped`, `dropped_by_reason`, `dropped_by_ticker`), 필요 시 `(PriceFrame, PriceMeta)`
- **성공·평가 기준**: 같은 원본이면 같은 결과 / 버린 행 수를 반환값에 포함 / PriceFrame 계약 검사 함수(`contracts.price_frame_problems`) 통과
- **제약**: 보간·제외 판단 금지(M02-03 몫). 순수 함수(I/O 없음)
- **오류**: `DataQualityError` — 통화가 섞임 `DATA_MIXED_CURRENCY`, 빈 목록·같은 (티커, 날짜) 중복 `DATA_INVALID_BARS`

### M02-03 데이터 품질 판정기

- **FR**: FR05 / 업무 규칙 부록 A-3
- **Input**: PriceFrame(결측 포함), `required_tickers` (Benchmark + Spec 고정 목록 종목), `expected_calendar` (Benchmark 거래일, `benchmark_calendar(prices, "SPY")`), `AppConfig.data` / (추가) `mismatch_days` (티커 → MISMATCH 거래일 수, `load_prices` 요약에서)
- **Process**
  1. 기대 거래일 = `expected_calendar`. 그 밖의 날짜 행은 버림.
  2. 커버리지 = 값이 있는 거래일 수 / 기대 거래일 수 (채우기 전 값 기준).
  3. 연속 결측이 `max_fill_days`(1일) 이하면 직전값으로 채움 → `FILLED`, 채운 일수 기록.
  4. `EXCLUDED`: 커버리지 < `coverage_threshold`, 연속 결측 2일 이상, 또는 첫 거래일부터 결측(채울 직전값 없음). 사유를 모두 적음.
  5. 필수 종목이 `EXCLUDED` 면 `DATA_REQUIRED_MISSING`. 사용 가능 종목이 0개면 `DATA_NO_USABLE_TICKER`.
  6. (추가) `mismatch_days` 를 주면 종목별 `mismatch_days` 를 적고, 사용 가능 종목이면 `report.warnings` 에 Report 한계 문장을 남김. 판정(OK·FILLED·EXCLUDED)은 안 바꿈. 값은 이미 CONSENSUS 로 보정돼 있음.
- **Output**: `DataQualityReport` + 결측 없는 PriceFrame (사용 가능 종목만, 행 = `expected_calendar`)
- **성공·평가 기준**: 경계값(커버리지 0.95 정확히 = 통과, 0.9499 = 제외) / 2일 연속 결측 제외 / Benchmark 결측 시 예외 / 출력 PriceFrame 에 NaN 없음
- **제약**: 값 생성 금지(C-07). 채우기는 직전 거래일 값 복사만. 판정 기준은 설정에서만 읽음
- **오류**: `DataQualityError` (`DATA_REQUIRED_MISSING`, `DATA_NO_USABLE_TICKER`). `details["report"]` 에 판정 결과(JSON)를 담아 실행 기록에 남김
- **위치**: DB 저장 단계가 아니라 백테스트 직전 (M08-02 흐름 3번). DB 에는 판정 결과를 저장하지 않음

### M02-04 시장 데이터 Repository

- **FR**: FR04 (출처·기준시점·수집시각과 함께 저장)
- **Input / Output (인터페이스)**: `MarketDataRepository` (명세 13개 그대로)

  | 메서드 | 하는 일 |
  |---|---|
  | `upsert_prices(bars) -> int` | 가격 저장, 반영 행 수 |
  | `get_prices(tickers, start, end) -> (DataFrame, PriceMeta)` | PriceFrame 계약 모양으로 조회 |
  | `covered_range(ticker)` | 저장된 첫·마지막 날짜 |
  | `upsert_fx(rates)` / `get_fx_on_or_before(d)` | 환율 저장·조회 |
  | `save_run_artifact(run_id, profile, spec, universe, config)` | 재현용 실행 입력 |
  | `save_constituents(rows)` / `latest_constituents(index)` | 구성종목 스냅샷 |
  | `log_fetch(source, target, start, end, status, fetched_at, error)` | 수집 시도 기록 |
  | `save_step(rec)` / `get_steps(run_id)` | 실행 단계 기록 |
  | `save_report(report)` / `get_report(run_id)` | Report |
  | `needs_fetch(ticker, start, end)` | 캐시 판단 헬퍼 |

  (추가) `ExtendedRepository`: `upsert_assets` / `get_assets` / `asset_key_map`, `upsert_financials` / `get_financials_as_of`, `upsert_news` / `get_news` / `prune_news`, `covered_ranges` / `tickers_needing_fetch` / `log_fetches` / `fetch_attempts` (정기 수집용, 여러 종목 한 번에), `pending_verification` / `price_rows` / `save_verification` / `mismatch_days` / `reset_verification` (M02-06용), `add_extra_tickers` / `extra_tickers` (서비스 요청 종목).
- **Process**
  1. SQLAlchemy Core 로 `SqlRepository` 하나를 구현. PostgreSQL·SQLite 가 같은 코드로 돎. 열기: `open_repository()` (`.env` 의 `DATABASE_URL`). 테이블이 없으면 만들고 `data_sources` 기본 행을 넣음.
  2. 같은 자연키로 다시 받으면: 값이 다르면 갱신(교차검증 표시를 비워 다시 검증), 같으면 건너뜀. 소수 끝자리 차이(상대 1e-9)는 같은 값으로 봄. 수집 시각만 다르면 건너뜀.
  3. 비교할 기존 행은 입력과 같은 종목·날짜 범위·출처만 읽음. 새 행은 여러 행을 한 문장으로 INSERT (원격 DB 왕복 줄임).
  4. 가격·구성종목 저장 때 `assets` 에 없는 종목은 기본 행을 자동 생성.
  5. `get_prices` 출처 고르기: 같은 (티커, 날짜)에 출처가 여럿이면 CONSENSUS → 통화별 우선순위(USD `ALPACA → TIINGO → YFINANCE`, KRW `YFINANCE → KIS`) → 수집 시각이 늦은 행 → 출처 이름 순.
  6. `needs_fetch`: 저장 범위가 요청 범위를 덮고 마지막 저장일 ≥ 직전 거래일이면 False.
  7. `get_financials_as_of(asset_id, as_of)`: `disclosed_at ≤ as_of` 인 값만, (지표, 출처, 연결구분)별 가장 최근 기간 (선견 금지 C-06).
- **Output**: 위 메서드 반환값. 테이블 구조는 7절
- **성공·평가 기준**: 같은 데이터 두 번 upsert 시 두 번째 반영 0행 / 범위 조회 결과가 PriceFrame 계약 충족 / `needs_fetch` 경계 테스트 / 인메모리 SQLite 와 PostgreSQL 에서 같은 테스트 통과 / 부록 B 테이블·칸 이름 유지 테스트
- **제약**: C-10. 다른 모듈은 SQL·테이블명을 모름 (팀원 직접 조회는 읽기 전용 `reader` 계정, `팀원_DB_사용.md`). 방언 문법(`ON CONFLICT` 등)을 쓰지 않음. 시각은 UTC (C-05)
- **오류**: `RepositoryError` (`REPO_WRITE_FAILED` / `REPO_READ_FAILED`). 통화가 다른 종목을 한 PriceFrame 으로 요청하면 `REPO_READ_FAILED`

### M02-05 지수 구성종목 수집기

- **FR**: FR04 / 결정로그 Universe 항목
- **Input**: `AppConfig.universe.indices` (수집은 `UNIVERSE_INDICES`, 기본 `SP500,NDX,KOSPI200`), 오늘 날짜, M02-04
- **Process**
  1. 인터페이스 `ConstituentSource.fetch(index) -> list[IndexConstituent]`. 지수별 출처는 `RoutedConstituentSource` 가 나눔.
  2. 갱신 필요: 최신 스냅샷이 없거나, 스냅샷 날짜 < 직전 정기 변경일.
     - SP500·NDX: 3·6·9·12월 셋째 금요일 (명세)
     - KOSPI200 (추가): 6·12월 둘째 목요일(선물·옵션 만기일) 다음 날
  3. 결과 검사: 행 수(SP500 495~510, NDX 98~105, KOSPI200 198~202), 티커 중복 없음, sector·industry 비어 있지 않음, sector 는 GICS 11개 섹터 이름 중 하나.
  4. 통과하면 오늘 날짜를 `snapshot_date` 로 저장. 실패하면 기존 스냅샷 유지 + 경고(가장 최근 스냅샷 날짜를 Report 한계에 표시). 기존 스냅샷도 없으면 오류.
  5. 수집 시도는 성공·실패 모두 `fetch_log` 에 남김.
- **Output**: 지수별 `IndexRefresh` (`status` = `REFRESHED` 새로 저장 / `UP_TO_DATE` 받지 않음 / `KEPT_OLD` 실패해 기존 유지, `snapshot_date`, `rows` = 최신 `list[IndexConstituent]`, `warnings`)
- **출처 기록란**

  | 지수 | 출처 | URL / 파일 | 갱신 방법 |
  |---|---|---|---|
  | SP500 | 위키백과 영문판 구성종목 표 (GICS Sector·Sub-Industry 포함) | https://en.wikipedia.org/wiki/List_of_S%26P_500_companies | 정기 변경일 뒤 첫 실행 때 표를 다시 읽음 |
  | NDX | 고정 파일 `config/ndx.csv` (위키백과 표가 ICB 분류라 GICS 는 S&P 500 표·`config/gics_overrides.csv` 로 붙임) | https://en.wikipedia.org/wiki/Nasdaq-100 (만들 때) | 파일을 다시 만들어 바꿈 |
  | KOSPI200 | 한국거래소 정보데이터시스템 지수구성종목 표 → `scripts/make_kospi200_csv.py` → `config/kospi200.csv` (무료 공식 API 없음) | KRX 정보데이터시스템 | 6·12월 정기 변경 뒤 파일을 다시 만듦 |

  - industry: GICS Sub-Industry 이름. KOSPI200 은 Yahoo 섹터를 GICS 11개 섹터 이름으로 바꾸고, 산업은 Yahoo 산업 이름 (GICS 와 다를 수 있음). 빈 칸은 `config/gics_overrides.csv`.
  - 프로젝트 기간(~2026-12-15) 안에 KOSPI200 정기 변경(12월)이 없어 고정 파일로 충분.
- **성공·평가 기준**: 정기 변경일 계산(2026-09-18 = 9월 셋째 금요일) / 행 수 범위 위반 시 저장 안 함 / 가짜 출처로 갱신·미갱신 분기
- **제약**: 정기 변경 사이의 수시 변경은 반영하지 않음 (한계로 기록). 섹터·산업은 GICS 명칭 기준
- **오류**: 기존 스냅샷도 없이 수집 실패 → `DataSourceError(DATA_CONSTITUENTS_UNAVAILABLE)`

### M02-06 출처 간 교차검증 (추가)

- **FR**: FR04 (출처·기준시점 보존) 보강. 명세에 없는 모듈
- **Input**: M02-04 에 저장된 출처별 가격 행 (아직 검증 안 된 (티커, 날짜), 또는 다시 계산할 기간)
- **Process**
  1. `verify_step(repo)`: `verify_status` 가 빈 (티커, 날짜)를 2,000개씩 읽음 (`pending_verification` → `price_rows`).
  2. 비교 값
     - 종가 `close` (분할만 보정, 모든 출처 같은 기준): 허용 **0.5%**
     - 수정종가 `adj_close` (분할+배당): 허용 **1%**. KIS 는 수정주가가 배당 미반영이라 비교에서 뺌
  3. 기준값 = 출처들 값의 중앙값. 출처가 2개면 통화별 우선순위에서 앞선 출처 값 (중앙값=평균이면 편차가 반으로 보이기 때문).
  4. 출처가 1개: 그 행 `verify_status = SINGLE`. CONSENSUS 행은 만들지 않음 (있으면 지움).
  5. 출처가 2개 이상: `source = 'CONSENSUS'` 행 저장 (`adj_close`·`close` = 기준값, `volume` = 중앙값, `source_count`, 최대 편차, `VERIFIED`/`MISMATCH`, `outlier_sources`). 출처별 행에는 편차(`dev_pct`·`adj_dev_pct`, %)와 `VERIFIED`/`MISMATCH`.
  6. CONSENSUS 행과 출처별 표시는 한 트랜잭션으로 저장 (`save_verification`).
  7. 수집으로 값이 바뀐 행은 M02-04 가 표시를 비우므로 다음 실행 때 다시 검증됨.
  8. `reverify(repo, start, end)`: 기간 표시를 지우고 다시 계산 (허용 오차를 바꿨을 때).
- **Output**: `VerifyResult` (`done`, `counts` = keys·consensus_rows·verified·mismatch·single, `mismatches` 목록). DB 에는 CONSENSUS 행과 표시 칸.
- **쓰는 곳**: `get_prices` 가 CONSENSUS 를 먼저 고름 / `mismatch_days` 가 M02-03 경고로 감
- **성공·평가 기준**: 기준값·허용 오차 경계 / KIS 수정종가 제외 / SINGLE 처리 / 값이 바뀐 행 재검증 / 기간 다시 계산 (SQLite·PostgreSQL)
- **제약**: 수집·품질 판정과 따로 둠. DB 는 M02-04 메서드로만. 값을 새로 만들지 않음 (기준값은 실제 출처 값 중에서 나옴)
- **오류**: 저장 실패는 `RepositoryError`. 시간 예산이 끝나면 `done = False` 로 멈추고 다음 실행이 이어 받음

## 6. 정기 수집 (추가, `jobs.py`)

M02-01~06 을 서버에서 예약 실행하는 층. 명세 모듈이 아니라 운영용.

| 작업 | 하는 일 |
|---|---|
| `prices` | 출처(줄)별로 처음이면 백필(`BACKFILL_YEARS`), 이후엔 최근 10일 증분. 끝에 M02-06 |
| `meta` | M02-05 구성종목, 재무(DART·SEC, 받은 지 `FIN_REFRESH_DAYS` 지난 종목만) |
| `news` | 뉴스 줄별 하루 한도(네이버 200, Google RSS 한국 200·미국 200, NewsAPI 90), 종목당 하루 5건, 365일 지난 기사 삭제 |
| `verify` | M02-06 만 |

가격 줄: KIS(한국 주), Alpaca(미국 주), yfinance(전체 보완 + 환율), Tiingo(미국 표본 75종목/주).

| 예약 (KST) | 내용 |
|---|---|
| 평일 16:37 | 한국 가격 (KIS + yfinance) |
| 화~토 07:37 | 미국 가격 (Alpaca + 환율, Alpaca 가 못 받은 종목은 yfinance 로 대신) |
| 토 10:13 | 미국 보조 출처 (yfinance 전체 + Tiingo 75종목) + 교차검증 |
| 매일 06:13 | 구성종목·재무 |
| 매일 07:23 | 뉴스 |

- 같은 종목이 3번 연속 실패하면 그 줄에서 뺌. 진행 상황은 DB(`price_daily` 범위 + `fetch_log`)에 남아 다음 실행이 이어 받음.
- 수집 대상 = 구성종목 + 벤치마크(`SPY`, `QQQ`, `069500.KS`) + `EXTRA_TICKERS` + `extra_ticker` 테이블.
- 서비스 API(`api.py`)가 DB 에 없는 종목을 받으면 즉시 수집해 `extra_ticker` 에 올림 (하루 10종목). 종류는 공식 API(DART·KIS·Tiingo) 먼저, yfinance 보완으로 판단 (`asset_kind.py`).

## 7. DB 테이블

12개 = 부록 B 7개 + 추가 5개. 정의: `repository/tables.py`. PostgreSQL 타입 기준 (SQLite 는 같은 뜻의 타입).
시각 칸(`timestamptz`)은 모두 UTC. `source` 칸은 모두 `data_sources.source_name` 을 가리킴.

| 테이블 | 근거 | 내용 | 키 |
|---|---|---|---|
| `data_sources` | 추가 | 출처 목록 | `source_id` (`source_name` 고유) |
| `assets` | 추가 | 종목 마스터 | `asset_id` |
| `fetch_log` | 부록 B | 수집 시도 기록 | `id` |
| `price_daily` | 부록 B | 일별 가격 (출처별 행) | `(ticker, date, source)` |
| `fx_daily` | 부록 B | 환율 | `(pair, date, source)` |
| `index_constituent` | 부록 B | 구성종목 스냅샷 | `(index_code, snapshot_date, ticker)` |
| `financials` | 추가 | 재무 지표 | `financial_id` (`asset_id, source, period, fs_div, metric` 고유) |
| `news` | 추가 | 기사 | `news_id` (`asset_id, url_hash` 고유) |
| `extra_ticker` | 추가 | 서비스 요청으로 늘어난 수집 종목 | `ticker` |
| `run_step` | 부록 B | 실행 단계 기록 (M08-01) | `(run_id, step)` |
| `run_artifact` | 부록 B | 재현용 실행 입력 (M08-02) | `run_id` |
| `report` | 부록 B | Report (M06-02) | `run_id` |

### 7-1. `data_sources` (추가)

| 칸 | 타입 | 제약 | 설명 |
|---|---|---|---|
| `source_id` | integer | PK, 자동 증가 | |
| `source_name` | varchar(40) | NOT NULL, 고유 | 출처 이름 (다른 테이블의 `source`) |
| `type` | varchar(10) | NOT NULL | `QUANT`(정량) / `QUAL`(뉴스) / `META`(구성종목) |
| `provides` | varchar(80) | | 저장하는 테이블 |
| `description` | text | | 설명 |
| `last_success_at` | timestamptz | | 최근 성공 시각 (수집 기록 때 갱신) |
| `last_failure_at` | timestamptz | | 최근 실패 시각 |

기본 행 12개: YFINANCE, KIS, DART, TIINGO, ALPACA, SEC_EDGAR (QUANT) / NAVER_NEWS, GOOGLE_RSS, NEWSAPI (QUAL) / CONSENSUS (QUANT, 교차검증 기준값 행) / WIKIPEDIA, KRX (META). 처음 보는 출처는 자동 등록.

### 7-2. `assets` (추가)

| 칸 | 타입 | 제약 | 설명 |
|---|---|---|---|
| `asset_id` | varchar(32) | PK | 종목 ID. `KR-005930`, `US-AAPL`, `US-BRK-B` |
| `ticker` | varchar(20) | NOT NULL | 시장 안 코드 (`005930`, `AAPL`, `BRK-B`) |
| `name` | varchar(200) | | 종목 이름 |
| `market` | varchar(10) | NOT NULL | `KOSPI` / `KOSDAQ` / `US` |
| `asset_type` | varchar(10) | NOT NULL, 기본 `STOCK` | `STOCK` / `ETF` / `INDEX` |
| `currency` | varchar(3) | NOT NULL | `KRW` / `USD` |
| `yfinance_symbol` | varchar(20) | NOT NULL, 고유 | yfinance 표기 = `price_daily.ticker` = PriceFrame 열 이름 |
| `dart_corp_code` | varchar(8) | | DART 고유번호 (한국) |
| `sec_cik` | varchar(10) | | SEC CIK (미국) |
| `kis_ticker` | varchar(10) | | KIS 종목코드 (한국, 6자리) |
| `tiingo_symbol` | varchar(20) | | Tiingo 표기 (미국) |
| `alpaca_symbol` | varchar(20) | | Alpaca 표기 (미국, `BRK.B`) |
| `created_at` | timestamptz | NOT NULL | 처음 만든 시각 |
| `updated_at` | timestamptz | NOT NULL | 마지막 갱신 시각 |

- 고유: `(market, ticker)`.
- 처음 들어올 때 `default_asset` 이 시장·통화·출처 코드를 채움. DART 고유번호·CIK 는 재무 수집 때 채움.
- `asset_type`:
  - 기본 `STOCK`. `.env` 의 `BENCHMARK_TICKERS`(현재 `SPY`, `QQQ`, `069500.KS`)와 `ETF_TICKERS` 는 가격 수집 때 `ETF` 로 맞춤.
  - 서비스 요청으로 들어온 종목: 한국은 DART 상장사 → KIS 상품 기본정보 → yfinance, 미국은 `^` 시작 = `INDEX` → Tiingo 지원 종목표 → yfinance 순으로 판단.
  - 전략 대상은 `asset_type = 'STOCK'`.

### 7-3. `fetch_log` (부록 B + 추가 칸)

| 칸 | 타입 | 제약 | 설명 |
|---|---|---|---|
| `id` | bigint | PK, 자동 증가 | |
| `source` | varchar(40) | NOT NULL, FK | 출처 |
| `target` | varchar(100) | NOT NULL | 대상: 티커·검색어·`constituents:SP500` 등 |
| `start_date` | date | | 요청 시작일 |
| `end_date` | date | | 요청 끝일 |
| `status` | varchar(10) | NOT NULL | `SUCCESS` / `FAILED` / `PARTIAL` |
| `fetched_at` | timestamptz | NOT NULL | 수집 시각 |
| `error` | text | | 실패 사유 |
| `fetched_count` | integer | | (추가) 받은 행 수 |
| `inserted_count` | integer | | (추가) 새로 저장·갱신한 행 수 |

인덱스: `(target, fetched_at)`. 정기 수집이 이 표로 출처별 최근 성공·연속 실패를 판단함.

### 7-4. `price_daily` (부록 B + 추가 칸)

| 칸 | 타입 | 제약 | 설명 |
|---|---|---|---|
| `ticker` | varchar(20) | PK | yfinance 표기 |
| `date` | date | PK | 거래일 |
| `adj_close` | double | NOT NULL, > 0 | 수정종가 (분할+배당. KIS 는 분할만) |
| `volume` | bigint | | 거래량 |
| `currency` | varchar(3) | NOT NULL, 기본 `USD` | `USD` / `KRW`(추가 값) |
| `source` | varchar(40) | PK, FK | 출처. 교차검증 기준값은 `CONSENSUS` |
| `fetched_at` | timestamptz | NOT NULL | 수집 시각 |
| `asset_id` | varchar(32) | NOT NULL, FK → assets | (추가) 종목 |
| `open`, `high`, `low` | double | | (추가) 시가·고가·저가 |
| `close` | double | | (추가) 종가 (분할만 보정, 배당 미반영). 교차검증 주 비교 값 |
| `source_count` | integer | | (추가) CONSENSUS 행: 비교한 출처 수 |
| `dev_pct` | double | | (추가) 종가 편차(%). 출처 행 = 기준값 대비, CONSENSUS 행 = 최대 편차 |
| `adj_dev_pct` | double | | (추가) 수정종가 편차(%) |
| `verify_status` | varchar(10) | | (추가) `VERIFIED` / `MISMATCH` / `SINGLE`. 비어 있으면 검증 전 |
| `outlier_sources` | jsonb | | (추가) CONSENSUS 행: 허용 오차를 넘은 출처 목록 |
| `fetch_log_id` | bigint | FK → fetch_log | (추가) 수집 기록 연결 |

- 인덱스: `(ticker, date)`, 부분 인덱스 `idx_price_unverified` (`verify_status IS NULL` 인 행만, 교차검증 대기 찾기).
- 같은 (티커, 날짜)에 출처별로 여러 행이 있음. 하나만 고르는 규칙은 M02-04 Process 5.

### 7-5. `fx_daily` (부록 B)

| 칸 | 타입 | 제약 | 설명 |
|---|---|---|---|
| `pair` | varchar(6) | PK | `USDKRW` |
| `date` | date | PK | 날짜 |
| `rate` | double | NOT NULL, > 0 | 1달러당 원 |
| `source` | varchar(40) | PK, FK | 출처 (`YFINANCE`, 심볼 `KRW=X`) |
| `fetched_at` | timestamptz | NOT NULL | 수집 시각 |

### 7-6. `index_constituent` (부록 B + 추가 칸)

| 칸 | 타입 | 제약 | 설명 |
|---|---|---|---|
| `index_code` | varchar(10) | PK | `SP500` / `NDX` / `KOSPI200`(추가 값) |
| `snapshot_date` | date | PK | 스냅샷 날짜 (검사 통과 후 저장한 날) |
| `ticker` | varchar(20) | PK | yfinance 표기 |
| `name` | varchar(200) | | 종목 이름 |
| `sector` | varchar(60) | NOT NULL | GICS 섹터 (11개 중 하나) |
| `industry` | varchar(100) | NOT NULL | GICS Sub-Industry (KOSPI200 은 Yahoo 산업) |
| `source` | text | NOT NULL | 출처 이름 + URL |
| `fetched_at` | timestamptz | NOT NULL | 수집 시각 |
| `asset_id` | varchar(32) | NOT NULL, FK → assets | (추가) 종목 |

최신 구성 = 지수별 `max(snapshot_date)` 행들.

### 7-7. `extra_ticker` (추가)

| 칸 | 타입 | 제약 | 설명 |
|---|---|---|---|
| `ticker` | varchar(20) | PK | yfinance 표기 |
| `asset_id` | varchar(32) | NOT NULL, FK → assets | 종목 |
| `added_by` | varchar(20) | NOT NULL | 추가한 곳 (`API`) |
| `added_at` | timestamptz | NOT NULL | 추가 시각 |

정기 수집 대상에 들어가 다음 실행부터 모든 출처로 백필·증분. `.env` 의 `EXTRA_TICKERS` 는 사람이 정하는 목록, 이 표는 요청으로 쌓이는 목록.

### 7-8. `financials` (추가)

| 칸 | 타입 | 제약 | 설명 |
|---|---|---|---|
| `financial_id` | bigint | PK, 자동 증가 | |
| `asset_id` | varchar(32) | NOT NULL, FK → assets | 종목 |
| `source` | varchar(40) | NOT NULL, FK | `DART` / `SEC_EDGAR` |
| `period` | varchar(20) | NOT NULL | 기간 키. DART `2025_11011`(연도_보고서코드), SEC `FY2025`, SEC 스냅샷은 수집일 |
| `fs_div` | varchar(5) | NOT NULL, 기본 `-` | DART `CFS`(연결) / `OFS`(별도), SEC `-` |
| `metric` | varchar(60) | NOT NULL | 지표 이름 (아래 표) |
| `value` | double | NOT NULL | 값 |
| `unit` | varchar(10) | | `KRW` / `USD` / `주` |
| `fiscal_year` | integer | | 사업연도 |
| `report_code` | varchar(20) | | DART `11011` 사업 / `11012` 반기 / `11013` 1분기 / `11014` 3분기, SEC `10-K` / `SNAPSHOT` |
| `period_end` | date | | 기간 끝일 (DART 당기 기준일, SEC 회계기간 끝) |
| `disclosed_at` | date | NOT NULL | 공시일. 이 날 이후에만 백테스트에 씀 (C-06 선견 금지) |
| `rcept_no` | varchar(30) | | 공시 접수번호 (DART rcept_no, SEC accession) |
| `verification_status` | varchar(12) | | 예비 칸 (`VERIFIED`/`MISMATCH`/`UNVERIFIED`). 현재 비어 있음 |
| `metadata_json` | jsonb | | 예비 칸. 현재 비어 있음 |
| `fetched_at` | timestamptz | NOT NULL | 수집 시각 |
| `fetch_log_id` | bigint | FK → fetch_log | 수집 기록 연결 |

- 고유: `(asset_id, source, period, fs_div, metric)`. 인덱스: `(asset_id, disclosed_at)`.
- 지표

  | 출처 | 지표 (`metric`) | 기간 |
  |---|---|---|
  | DART (`fnlttSinglAcnt` 주요계정, `account_nm` 그대로) | 유동자산, 비유동자산, 자산총계, 유동부채, 비유동부채, 부채총계, 자본금, 이익잉여금, 자본총계, 매출액, 영업이익, 법인세차감전 순이익, 당기순이익 등 | 사업·반기·1분기·3분기 보고서, 연결·별도 각각 |
  | SEC EDGAR (companyfacts) | 매출액, 영업이익, 당기순이익, 자산총계, 부채총계, 자본총계, EPS(희석) | 연간 (10-K) |
  | SEC EDGAR 스냅샷 (`report_code = SNAPSHOT`) | EPS(TTM), 순이익(TTM), 자본총계(최근), 발행주식수, BPS | 수집일 기준 최신 |

- DART 데이터는 2015년 공시부터 있음. DART 공시일 = 접수번호 앞 8자리.

### 7-9. `news` (추가)

| 칸 | 타입 | 제약 | 설명 |
|---|---|---|---|
| `news_id` | bigint | PK, 자동 증가 | |
| `asset_id` | varchar(32) | NOT NULL, FK → assets | 종목 |
| `source` | varchar(40) | NOT NULL, FK | `NAVER_NEWS` / `NEWSAPI` / `GOOGLE_RSS` |
| `url` | text | NOT NULL | 기사 주소 |
| `url_hash` | varchar(64) | NOT NULL | url SHA-256 (중복 판단 키. Google RSS 주소가 수 KB 라 인덱스 한도를 넘어서) |
| `title` | text | NOT NULL | 제목 |
| `content` | text | | 요약·본문 일부 (출처가 주는 만큼) |
| `publisher` | varchar(200) | | 언론사 |
| `published_at` | timestamptz | NOT NULL | 발행 시각 |
| `language` | varchar(5) | | `ko` / `en` |
| `query` | varchar(200) | | 검색어 |
| `content_hash` | varchar(64) | NOT NULL | url + 제목 SHA-256 |
| `metadata_json` | jsonb | | 출처별 부가 정보 |
| `fetched_at` | timestamptz | NOT NULL | 수집 시각 |
| `fetch_log_id` | bigint | FK → fetch_log | 수집 기록 연결 |

- 고유: `(asset_id, url_hash)`. 인덱스: `(asset_id, published_at)`.
- 보관 365일 (`NEWS_KEEP_DAYS`), 지난 기사는 뉴스 수집 때 삭제.

### 7-10. `run_step` (부록 B)

| 칸 | 타입 | 제약 | 설명 |
|---|---|---|---|
| `run_id` | varchar(40) | PK | 실행 ID |
| `step` | varchar(40) | PK | 단계 이름 |
| `status` | varchar(10) | NOT NULL | 단계 상태 |
| `started_at` | timestamptz | NOT NULL | 시작 |
| `ended_at` | timestamptz | | 끝 |
| `summary` | text | | 요약 |
| `sources_json` | jsonb | | 쓴 출처 |
| `error_code` | varchar(60) | | 오류 코드 |
| `error_message` | text | | 오류 메시지 |

### 7-11. `run_artifact` (부록 B)

| 칸 | 타입 | 제약 | 설명 |
|---|---|---|---|
| `run_id` | varchar(40) | PK | 실행 ID |
| `created_at` | timestamptz | NOT NULL | 만든 시각 |
| `profile_json` | jsonb | NOT NULL | UserProfile |
| `spec_json` | jsonb | NOT NULL | StrategySpec |
| `spec_hash` | varchar(64) | NOT NULL | Spec SHA-256 |
| `universe_json` | jsonb | NOT NULL | UniverseResult |
| `config_json` | jsonb | NOT NULL | AppConfig |

### 7-12. `report` (부록 B + 추가 칸)

| 칸 | 타입 | 제약 | 설명 |
|---|---|---|---|
| `run_id` | varchar(40) | PK, FK → run_artifact | 실행 ID |
| `created_at` | timestamptz | NOT NULL | 만든 시각 |
| `data_json` | jsonb | NOT NULL | ReportData |
| `text_markdown` | text | NOT NULL | Report 본문 |
| `display_values_json` | jsonb | NOT NULL | (추가) `Report.display_values` (M04-03 일치성 검사용 표시 문자열) |

## 8. 오류 코드 (역할 A)

| 예외 | code | 언제 |
|---|---|---|
| `DataSourceError` | `DATA_SOURCE_UNAVAILABLE` | 어댑터 설정 오류 |
| `DataSourceError` | `DATA_SOURCE_CONFIG` | `.env` 에 API 키 없음 |
| `DataSourceError` | `DATA_CONSTITUENTS_UNAVAILABLE` | 구성종목 수집 실패 + 기존 스냅샷 없음 |
| `DataQualityError` | `DATA_REQUIRED_MISSING` | 필수 종목(Benchmark 등)이 EXCLUDED |
| `DataQualityError` | `DATA_NO_USABLE_TICKER` | 사용 가능 종목 0개 |
| `DataQualityError` | `DATA_MIXED_CURRENCY` | 한 PriceFrame 에 통화가 섞임 |
| `DataQualityError` | `DATA_INVALID_BARS` | 빈 목록·(티커, 날짜) 중복 |
| `DataQualityError` | `DATA_INVALID_INPUT` | 기대 거래일 목록이 빔, 판정 뒤에도 결측이 남음 |
| `RepositoryError` | `REPO_WRITE_FAILED` / `REPO_READ_FAILED` | DB 쓰기·읽기 실패, 통화 섞인 조회 |

## 9. 다른 역할과의 약속

- 가격은 `get_prices` 또는 `load_prices` 로 받음. 한 번에 한 통화.
- 품질 판정(M02-03)은 백테스트를 돌리는 쪽(M08-02)이 기간·Benchmark·필수 종목을 정해서 부름.
- 재무는 `get_financials_as_of(asset_id, as_of)` 로만 받음 (공시일 기준).
- 전략 대상은 `asset_type = 'STOCK'`, 벤치마크는 ETF 행.
- 직접 SQL 조회가 필요하면 `reader` 계정 (`팀원_DB_사용.md`).
