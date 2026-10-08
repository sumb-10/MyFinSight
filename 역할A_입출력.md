# 역할 A 입출력 정리

역할 A 가 **받는 것**과 **내보내는 것**만 모은 문서. 모듈 내부 처리는 `역할A_모듈명세.md`.
모델 이름은 공통 스키마(M00-02, `schemas/`) 기준.

## 1. 한눈에

```
            설정(C)  ·  요청(D 파이프라인)  ·  기록·Report(D)  ·  외부 출처
                                   │
                                   ▼
                          ┌─────────────────┐
                          │   역할 A 데이터    │
                          │  M02-01 ~ M02-06 │
                          └─────────────────┘
                                   │
     ┌───────────────┬─────────────┼───────────────┬──────────────────┐
     ▼               ▼             ▼               ▼                  ▼
 B 구성종목      B·C 가격표      C 환율        D 품질 보고·저장      서비스·팀원 (추가)
```

| 방향 | 상대 | 내용 |
|---|---|---|
| 받음 | C (M00-01 설정) | `AppConfig.data`, `AppConfig.universe.indices` |
| 받음 | D (M08-02 파이프라인) | 종목·기간 요청, 필수 종목, 기대 거래일 |
| 받음 | D (M08-01·M06-02·M08-02) | 저장할 실행 기록·Report·재현 입력 |
| 받음 | 외부 출처 | API 응답 (KIS·Alpaca·yfinance·Tiingo·DART·SEC·뉴스·구성종목 표) |
| 내보냄 | B (M03-05) | 지수별 최신 구성종목 |
| 내보냄 | B·C (M03-04, M05-01) | 결측 없는 PriceFrame + PriceMeta |
| 내보냄 | C (M05-01) | USD/KRW 환율 |
| 내보냄 | D (M06-02 한계, M08-01) | DataQualityReport (제외 종목·사유·경고), 저장된 기록·Report 조회 |
| 내보냄 | 서비스·팀원 (추가) | 데이터 API, 읽기 전용 DB, 재무·뉴스 |

## 2. 받는 것

### 2-1. 설정 (C, M00-01)

| 값 | 기본 | 쓰는 곳 |
|---|---|---|
| `AppConfig.data.retry_max` | 3 | M02-01 재시도 |
| `AppConfig.data.retry_backoff_sec` | 1.0 | M02-01 재시도 대기 |
| `AppConfig.data.fx_symbol` | `KRW=X` | M02-01·02 환율 |
| `AppConfig.data.coverage_threshold` | 0.95 | M02-03 |
| `AppConfig.data.max_fill_days` | 1 | M02-03 |
| `AppConfig.data.cache_max_age_days` | 1 | M02-04 캐시 판단 |
| `AppConfig.universe.indices` | `SP500`, `NDX` (+`KOSPI200` 추가) | M02-05 |

API 키·DB 주소는 `.env` 에서만 읽음 (설정 모델 밖).

### 2-2. 요청 (D, M08-02 파이프라인)

| 단계 (표준 이름) | A 가 받는 것 | 부르는 함수 |
|---|---|---|
| `constituents` | 지수 목록, 오늘 날짜 | `ConstituentCollector.update(indices, today)` |
| `fetch_prices` | `tickers: list[str]`, `start: date`, `end: date` (기간 = 시작일 − 최대 lookback ~ 끝일) | `load_prices(tickers, start, end, adapter=, repository=)` |
| `data_quality` | PriceFrame(결측 포함), `required_tickers` (Benchmark + Spec 고정 목록), `expected_calendar` (Benchmark 거래일), `AppConfig.data`, `mismatch_days` (추가) | `assess_quality(prices, required, calendar, config.data, mismatch_days=)` |

- 티커는 yfinance 표기 (`AAPL`, `BRK-B`, `005930.KS`). `BRK.B` 처럼 줘도 A 가 맞춤.
- 미국·한국 종목은 따로 요청 (한 PriceFrame = 한 통화).

### 2-3. 저장 요청 (D)

| 보내는 모듈 | 받는 것 | 메서드 | 테이블 |
|---|---|---|---|
| M08-02 | `run_id`, `UserProfile`, `StrategySpec`, `UniverseResult`, `AppConfig` | `save_run_artifact(...)` | `run_artifact` |
| M08-01 | `StepRecord` | `save_step(rec)` | `run_step` |
| M06-02 (M04-03 통과 후) | `Report` | `save_report(report)` | `report` |

### 2-4. 외부 출처

| 데이터 | 출처 (주 → 보조) | 키 |
|---|---|---|
| 미국 가격 | Alpaca → Tiingo → yfinance | Alpaca·Tiingo 필요 |
| 한국 가격 | KIS, yfinance (수정종가는 yfinance 우선) | KIS 필요 |
| 환율 USD/KRW | yfinance (`KRW=X`) | 불필요 |
| 재무 | DART (한국), SEC EDGAR (미국) | DART 필요, SEC 는 User-Agent |
| 뉴스 | 네이버 (한국), NewsAPI (미국), Google News RSS (둘 다) | 네이버·NewsAPI 필요 |
| 구성종목 | 위키백과 (S&P 500), 고정 파일 (NDX, KOSPI200 ← KRX 표) | 불필요 |

## 3. 내보내는 것

### 3-1. 구성종목 → B (M03-05 Universe 구성기)

| 함수 | 반환 |
|---|---|
| `ConstituentCollector.update(indices, today)` | `{IndexCode: IndexRefresh}` |
| `repo.latest_constituents(index)` | `list[IndexConstituent]` |

- `IndexConstituent`: `index_code`, `ticker`, `name`, `sector`(GICS 11개 중 하나), `industry`(GICS Sub-Industry), `snapshot_date`, `source`(출처 이름+URL), `fetched_at`
- `IndexRefresh`: `status` (`REFRESHED` / `UP_TO_DATE` / `KEPT_OLD`), `snapshot_date`, `rows`, `warnings` (갱신 실패 시 Report 한계 문장)

### 3-2. 가격표 → B·C (M03-04 전략 실행기, M05-01 Backtest)

`load_prices` 가 주고, `assess_quality` 를 거쳐 결측이 없어진 표.

| 이름 | 모양 |
|---|---|
| PriceFrame (명세 0-4) | `pd.DataFrame`. index = 거래일(`expected_calendar`), columns = 사용 가능 티커(오름차순), values = float64 수정종가. M02-03 뒤에는 NaN 없음 |
| `PriceMeta` | `source`(출처들을 `+` 로 이음, 예 `CONSENSUS+YFINANCE`), `as_of`, `fetched_at`(가장 오래된 수집 시각), `tickers`, `currency`(추가: `USD`/`KRW`) |
| `PriceLoadSummary` (실행 기록용) | `requested`, `cached`, `fetched`, `failed`(티커 → 사유), `stored_rows`, `dropped_rows`, `dropped_by_reason`, `mismatch_days`(추가) |

- 수정종가 = 분할+배당 반영. 같은 날 출처가 여럿이면 교차검증 기준값(CONSENSUS) → 출처 우선순위 순으로 고른 값.
- 한국 표는 원 단위. 원화 환산은 C 가 3-3 환율로.

### 3-3. 환율 → C (M05-01)

| 함수 | 반환 |
|---|---|
| `repo.get_fx_on_or_before(d)` | `FxRate` (`pair`=`USDKRW`, `date`, `rate`=1달러당 원, `source`, `fetched_at`) 또는 `None` |

### 3-4. 품질 판정 결과 → D (M06-02 Report 한계, M08-01 기록)

| 이름 | 칸 |
|---|---|
| `DataQualityReport` | `as_of`, `expected_days`, `items`(종목별 `TickerQuality`), `usable_tickers`, `excluded`(티커 → 사유), `warnings`(추가: 출처 간 가격 불일치 문장) |
| `TickerQuality` | `ticker`, `coverage`, `filled_days`, `status`(`OK`/`FILLED`/`EXCLUDED`), `reason`, `is_required`, `mismatch_days`(추가) |

- Report `limitation` 에 `excluded` (명세) 와 `warnings` (추가) 를 씀.
- 구성종목 갱신 실패 경고는 3-1 `IndexRefresh.warnings`.

### 3-5. 저장된 기록 조회 → D

| 메서드 | 반환 |
|---|---|
| `get_steps(run_id)` | `list[StepRecord]` |
| `get_report(run_id)` | `Report` 또는 `None` |
| `get_run_artifact(run_id)` (추가) | 재현 입력 |

### 3-6. 재무·뉴스 → B (확장, 추가)

| 메서드 | 반환 |
|---|---|
| `repo.get_financials_as_of(asset_id, as_of, metrics=None)` | `list[FinancialRow]`. `disclosed_at ≤ as_of` 값만 (선견 금지), (지표, 출처, 연결구분)별 최신 기간 |
| `repo.get_news(asset_id, start, end)` | `list[NewsRow]` |
| `repo.get_assets(symbols)` | `list[AssetInfo]` (종목 ID·시장·`asset_type`·출처별 코드) |

`asset_id` = `KR-005930`, `US-AAPL`. 지표 이름·칸은 `역할A_모듈명세.md` 7-8.

### 3-7. 서비스·팀원 (추가)

| 통로 | 내용 | 문서 |
|---|---|---|
| 데이터 API (`api.py`) | `GET /assets`, `/prices`, `/fx`, `/financials/{ticker}`, `/news/{ticker}`. DB 에 없는 종목은 즉시 받아 저장 (하루 10종목) | `api.py` |
| 읽기 전용 DB (`reader`) | 팀원 코드가 SQL·pandas 로 직접 읽음 | `팀원_DB_사용.md` |

## 4. A 가 던지는 오류

부르는 쪽이 `code` 로 구분해 처리함.

| 언제 (부르는 함수) | 예외 · code | 부르는 쪽 처리 |
|---|---|---|
| 구성종목 실패 + 기존 스냅샷 없음 (`update`) | `DataSourceError` · `DATA_CONSTITUENTS_UNAVAILABLE` | 실행 중단 |
| API 키 없음 (어댑터) | `DataSourceError` · `DATA_SOURCE_CONFIG` | 실행 중단, `.env` 확인 |
| 필수 종목 제외 (`assess_quality`) | `DataQualityError` · `DATA_REQUIRED_MISSING` | 실행 중단 (UC-C 2b·2c) |
| 사용 가능 종목 0개 (`assess_quality`) | `DataQualityError` · `DATA_NO_USABLE_TICKER` | 실행 중단 |
| 통화 섞인 요청 (`get_prices`, `to_price_frame`) | `RepositoryError` · `REPO_READ_FAILED` / `DataQualityError` · `DATA_MIXED_CURRENCY` | 시장별로 나눠 요청 |
| DB 읽기·쓰기 실패 | `RepositoryError` · `REPO_READ_FAILED` / `REPO_WRITE_FAILED` | 실행 중단 (기록 실패는 경고만, M08-01) |

- 일부 종목을 못 받은 건 오류가 아님: `PriceLoadSummary.failed` 에 남고 PriceFrame 에선 NaN 열 → M02-03 이 `EXCLUDED` 로 처리.
