# 역할 A 데이터 서버 (M02-01 ~ M02-05 + 서버 수집)

MyFinSight 역할 A 모듈 5개: 수집 어댑터(M02-01), 정규화기(M02-02), 품질 판정기(M02-03), 저장소(M02-04, PostgreSQL 기본·SQLite 교체 가능), 구성종목 수집기(M02-05).
역할 A 크롤러 9개로 실제 API 를 불러 받고, 정규화·품질 판정 후 DB 에 저장함. `.env` 에 API 키와 DB 접속 정보 필요.
대상 시장: 미국(S&P 500, Nasdaq-100)과 한국(KOSPI200).
데이터 흐름과 사용법은 8절, DB 테이블(부록 B 7개 + 추가 5개)은 `역할A_모듈명세.md` 7절, 파일별 설명은 `파일설명.md` 참고.
DB 는 AWS Lightsail PostgreSQL(서울), 주기 수집은 역할 A 의 GitHub Actions. 팀원은 읽기 전용 계정으로 읽음 (`팀원_DB_사용.md`). 받고 내보내는 것은 `역할A_입출력.md`.

## 1. 구조

```
price_adapter() / financial_adapter() / news_adapter()        ← adapters/factory.py : 출처 이름으로 어댑터 만들기
   ▼
adapters/real.py    YFinancePriceAdapter, KisPriceAdapter, DartFinancialAdapter 등 9개
   │  (adapters/base.py 의 RetryingFetcher 상속 → 재시도·요청 간격·실패 기록)
   ▼
crawlers/*_client.py  (역할 A 원본 크롤러) → 실제 API
   ▼
normalizer.py → quality.py → repository/ (PostgreSQL·SQLite)
   ▲
jobs.py  (서버 수집 작업: 가격·구성종목·재무·뉴스를 주기마다, 나눠서 이어 받기)
   └ verify.py (출처 간 교차검증: CONSENSUS·MISMATCH, 가격 수집 끝에 이어서)
   ▲
.github/workflows/collect.yml  (GitHub Actions 예약 실행: python -m myfinsight.data.jobs)
```

| 구성 | 하는 일 |
|---|---|
| 크롤러 `crawlers/` | API 를 부르고 응답을 해석 (출처마다 다름). 원본 9개를 앱 없이 돌게 정리 |
| 어댑터 `adapters/real.py` | 크롤러 결과를 명세 형식(`RawPriceBatch` 등)으로 맞춤 |
| 어댑터 고르기 `adapters/factory.py` | 팀원은 이것만 쓰면 됨 |
| 공통 부모 `adapters/base.py` | 재시도(1·2·4초), 배치 나누기, 요청 간격, 실패 기록 |
| 수집 작업 `data/jobs.py` | 무엇을 얼마나 받을지. PC·GitHub Actions·인스턴스 어디서든 같은 명령 |
| 예약 실행 `.github/workflows/collect.yml` | 언제 부를지만 적음 (역할 A 개인 저장소에서 돎) |

## 2. 설치 (Windows PowerShell, 처음 한 번)

Python 3.11 필요. 이 폴더(`role-a-server`)에서 실행.

```powershell
py -3.11 -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -e ".[dev,real,postgres,api]"
python -m pytest
```

`181 passed, 50 skipped` 가 나오면 준비 끝 (건너뛴 50개는 PostgreSQL 테스트, 7절 참고). `[postgres]` 없이 설치하면 몇 개 더 건너뜀.
- `-e .` 로 설치하면 어느 폴더에서든 `import myfinsight` 가 됨.
- `[real]` 은 yfinance.
- `[postgres]` 는 pg8000. SQLite 만 쓰면 빼도 됨.
- `[api]` 는 데이터 API (FastAPI, uvicorn). 인스턴스에서만 필요. 빼면 `test_api.py` 를 건너뜀.
- `Activate.ps1` 에서 "스크립트를 실행할 수 없습니다" 오류가 나면 `Set-ExecutionPolicy -Scope CurrentUser RemoteSigned` 를 한 번 실행.

## 3. 실제 API 로 받아 보기

1. `.env.example` 을 복사해 `.env` 를 만들고 가진 키를 채움: `copy .env.example .env`
2. 키가 읽히는지 확인 (값은 앞 3글자만 보임): `python scripts/try_adapters.py env`
3. 9곳과 위키백과 구성종목 표를 조금씩 불러 봄. 키가 없는 출처는 건너뜀: `python scripts/try_adapters.py smoke`
4. 원하는 것만 불러 보기:

```powershell
python scripts/try_adapters.py price --source TIINGO --keys MSFT BRK-B
python scripts/try_adapters.py price --keys 005930.KS KRW=X          # yfinance
python scripts/try_adapters.py financial --source DART --keys 005930 --start 2025-01-01
python scripts/try_adapters.py news --source NAVER_NEWS --keys 삼성전자
```

코드에서는 `price_adapter("TIINGO")` 처럼 출처 이름으로 어댑터를 만듦 (없으면 yfinance).
**`.env` 는 비밀번호와 같음.** `.gitignore` 에 넣어 둠. 깃허브·메신저로 보내지 말고, 팀원에게 폴더를 줄 때도 `.env` 는 빼고 줌.

## 4. 출처별 어댑터

| 출처 | 어댑터 | 키(`fetch` 의 첫 인자) | `.env` | 참고 |
|---|---|---|---|---|
| yfinance | `YFinancePriceAdapter` | `MSFT`, `BRK-B`, `005930.KS`, `KRW=X` | 없음 | `.KS` 가 비면 `.KQ` 로 다시 조회 |
| 한국투자증권 | `KisPriceAdapter` | `005930` (6자리) | `KIS_APP_KEY`, `KIS_APP_SECRET`, `KIS_ENV` | 국내만. close = adj_close. 토큰은 `.cache` 에 저장 |
| Tiingo | `TiingoPriceAdapter` | `MSFT`, `BRK-B` | `TIINGO_API_KEY` | 미국만. close 는 분할만, adj_close 는 분할+배당 보정 |
| Alpaca | `AlpacaPriceAdapter` | `MSFT`, `BRK.B` | `ALPACA_API_KEY_ID`, `ALPACA_API_SECRET_KEY`, `ALPACA_FEED` | 미국만. 종료일은 어제까지. sip 거부 시 iex |
| DART | `DartFinancialAdapter` | 고유번호 8자리 또는 종목코드 6자리 | `DART_API_KEY` | 공시일(접수번호 앞 8자리) 기준으로 거름 |
| SEC EDGAR | `SecFinancialAdapter` | CIK 숫자 또는 티커 | `SEC_USER_AGENT` | 10-K 연간 + SNAPSHOT(EPS TTM 등). `include_snapshot=False` 로 끔 |
| 네이버 뉴스 | `NaverNewsAdapter` | 한국어 검색어 | `NAVER_CLIENT_ID`, `NAVER_CLIENT_SECRET`, `NAVER_API` | 최신순 100건 중 기간 안의 것 |
| NewsAPI | `NewsApiAdapter` | 영어 검색어 | `NEWSAPI_KEY` | 무료 플랜은 최근 1개월 |
| Google News RSS | `GoogleNewsRssAdapter` | 검색어 | 없음 | 미국 종목은 `lang="en", country="US"` |

동작 규칙 (`base.py`):
- 어댑터는 키 하나를 요청 한 번으로 보냄 (`batch_size=1`). 재시도와 요청 간격이 키마다 적용됨.
- 실패하면 1초, 2초, 4초 기다리며 최대 3번 더 시도. 끝까지 안 되면 `failed_tickers`(재무·뉴스는 `failed_keys`)에 사유를 남기고 다른 키는 계속 받음.
- `.env` 에 키가 없으면 재시도 없이 바로 `MissingApiKeyError` 로 멈춤. 오류 메시지에 빠진 키 이름이 나옴.
- 요청 간격 기본값: yfinance 0.5초, Alpaca 0.3초, SEC 0.15초(초당 10회 제한), KIS 0.1초. `min_interval_sec=` 로 바꿀 수 있음.

## 5. 출력 모양

```python
# 가격 RawPriceBatch.payload
{"MSFT": [{"date": "2026-09-30", "open": 1.0, "high": 1.0, "low": 1.0, "close": 1.0,
           "adj_close": 1.0, "volume": 123, "currency": "USD"}, ...]}
# OHLC 를 안 주는 출처는 date·adj_close·volume 만 있음

# 재무 RawFinancialBatch.payload
{"00126380": [{"period": "2025_11011", "fs_div": "CFS", "metric": "매출액", "value": 3.0e14,
               "unit": "KRW", "fiscal_year": 2025, "report_code": "11011", "period_end": "2025-12-31",
               "disclosed_at": "2026-03-10", "rcept_no": "20260310000123"}, ...]}

# 뉴스 RawNewsBatch.payload
{"삼성전자": [{"url": "...", "title": "...", "description": "...", "publisher": None,
             "published_at": "2026-09-29T00:00:00Z", "language": "ko"}, ...]}
```

날짜는 문자열(`YYYY-MM-DD`), 발행 시각은 UTC. SEC 지표 이름은 DART 와 같은 한국어(매출액, 영업이익 …)라 두 출처를 같은 칸에서 비교할 수 있음.

## 6. 원본 크롤러에서 바뀐 점

원본 9개의 API 호출·해석 코드는 그대로 두고 아래만 바꿈.

| 바뀐 것 | 이유 |
|---|---|
| `from app import config` → `crawlers/config.py` | 원본 앱 없이 돌게 함. `.env` 를 읽고, 키가 없으면 `MissingApiKeyError` |
| `app.collectors.base` 의 `http_session`, `num`, `to_date`, `rfc822`, `strip_html` → `crawlers/common.py` | 원본 base.py 가 없어 같은 이름으로 다시 만듦 |
| `collect()` (DB 저장 + `run_and_record`) 뺌 | DB 저장은 M02-04 Repository 몫. 행 만드는 부분만 `price_rows()` / `financial_rows()` / `news_rows()` 로 남김 |
| KIS·DART·SEC 캐시 경로를 함수로 | 모듈을 불러올 때가 아니라 쓸 때 `.env` 를 읽게 함 |
| yfinance 를 늦게 import | yfinance 를 안 쓰는 출처만 쓸 때는 설치가 없어도 됨 |
| yfinance·KIS 지표 스냅샷(PER·PBR 등) | 가격 어댑터 범위 밖이라 `snapshot()` 함수로 따로 남김 |
| `SkipSource` (해외 종목은 KIS 건너뛰기 등) | 어댑터는 종목 정보를 모르므로, 맞지 않는 키는 실패 목록에 사유와 함께 남김 |

## 7. 테스트

```powershell
python -m pytest -v
```

| 파일 | 확인하는 것 |
|---|---|
| `test_adapter_base.py` (11) | 어댑터 공통 부모의 재시도·대기·배치·요청 간격 |
| `test_real_adapters.py` (19) | 크롤러 해석(분할 보정, 페이지 넘기기, sip→iex, KIS 토큰 캐시 등)과 출처별 어댑터 행 모양 |
| `test_factory.py` (2) | 출처 이름으로 어댑터 고르기 |
| `test_normalizer.py` (19) | M02-02 행 제거·사유별 개수, 시가·종가 담기, 티커 정규화, 원화 종목·통화 섞임 거부, 환율 분리, 재무·뉴스 정규화, PriceFrame 계약 |
| `test_quality.py` (12) | M02-03 커버리지 경계(0.95 통과·0.9499 제외), 2일 연속 결측 제외, 필수 종목 예외, 출력 NaN 없음, MISMATCH 는 경고만 |
| `test_repository.py` (18 × 2 + 1) | M02-04 부록 B 테이블·칸 이름 유지, 두 번째 upsert 0행, 값이 다르면 UPDATE, CONSENSUS 우선, 한국 종목·assets, 재무·뉴스, 환율·구성종목·이력·실행 기록·Report, 캐시 흐름, DB 주소 고르기 (SQLite·PostgreSQL 각각) |
| `test_verify.py` (5 + 7 × 2) | 교차검증: 중앙값 기준값, 허용 오차 경계, 출처 2개면 우선순위 출처 기준, KIS 수정종가 제외, 출처 1개 SINGLE, 값이 바뀌면 재검증, 기간 다시 계산, 시간 예산, 시가·종가 저장 |
| `test_api.py` (6) | 데이터 API: 저장값 조회(수집 안 함), 없는 종목 즉시 수집·`extra_ticker` 등록·다음 수집 대상 포함, 하루 한도 429, 토큰, 종목 종류·지수 거르기 |
| `test_copy_sqlite_to_pg.py` (1, PostgreSQL 만) | SQLite → PostgreSQL 복사: 모든 테이블 행 수, 다시 돌려도 그대로, 쉼표·따옴표·줄바꿈 글자, 자동 번호 이어짐 |
| `test_jobs.py` (11 × 2 + 1) | 서버 수집 작업: 모든 출처 수집과 primary 우선(KIS 6자리 코드 → `005930.KS`), Tiingo 표본 순환, 백필을 나눠 이어 받기, 증분은 최근 10일만, 3번 실패 종목 제외, 늦은 상장 종목 재요청 안 함, 시간 예산, 한국·미국 따로 묶기, 재무 저장·신선도, 뉴스 상한·순환·삭제, 설정 읽기 |
| `test_server_config.py` (11) | DB 주소 변환(`postgresql://`, `sslmode`), 연결 풀 설정, `MYFINSIGHT_ENV` 우선순위, 가격 출처 우선순위 설정, 여러 티커 캐시 판단 |
| `test_kospi200_file.py` (5) | KOSPI200 파일: KRX 표 변환(코드 6자리·Yahoo→GICS 섹터), 파일 읽기, 지수별 출처 나누기, 12월 전 재수집 안 함 |
| `test_constituents.py` (24) | M02-05 정기 변경일(SP500·NDX 2026-09-18, KOSPI200 6·12월), 행 수 위반 시 저장 안 함, 갱신·미갱신·실패 분기, 위키백과 표 해석(표 id 가 없으면 머리글로 찾기) |

테스트는 실제 API 를 부르지 않음 (C-11). 크롤러 테스트는 HTTP 응답을 끼우고(`tests/stub_http.py`), 나머지는 테스트 안에서 만든 작은 데이터(`tests/helpers.py`)를 씀. 실제 API 확인은 `scripts/try_adapters.py smoke` 로 함.

`test_repository.py`·`test_jobs.py`·`test_verify.py` 는 SQLite 와 PostgreSQL 두 번 돎. PostgreSQL 쪽은 `MYFINSIGHT_TEST_PG_URL` 이 있을 때만 돌고 없으면 건너뜀. 테스트 DB 의 테이블을 지우고 다시 만드니 빈 테스트용 DB 를 씀.

```powershell
$env:MYFINSIGHT_TEST_PG_URL = "postgresql+pg8000://postgres:비밀번호@localhost:5432/myfinsight_test"
python -m pytest     # 207 passed
```

## 8. 정규화·품질·저장·구성종목 (M02-02 ~ M02-05)

### 흐름 (명세 0-2 의 3번)

```
price_adapter().fetch()         M02-01  RawPriceBatch (원본)
   → normalize()                M02-02  PriceBar·FxRate 목록, 버린 행 수
   → repo.upsert_prices/fx()    M02-04  DB 저장 (값이 같으면 건너뜀, 다르면 UPDATE)
   → repo.get_prices()          M02-04  PriceFrame (결측은 NaN)
   → assess_quality()           M02-03  DataQualityReport + 결측 없는 PriceFrame
```

`load_prices()` (`data/price_loader.py`) 가 앞의 네 단계를 캐시 우선으로 이어 줌. 저장소에 최신 데이터가 있는 티커는 다시 받지 않음.

```python
from datetime import date
from myfinsight.config import DataSettings
from myfinsight.data.adapters.factory import price_adapter
from myfinsight.data.price_loader import load_prices
from myfinsight.data.quality import assess_quality, benchmark_calendar
from myfinsight.data.repository import open_repository

settings = DataSettings()
repo = open_repository()                           # .env 의 DATABASE_URL, 테스트는 open_repository("sqlite://")
prices, meta, summary = load_prices(
    ["SPY", "MSFT", "NVDA"], date(2021, 9, 30), date(2026, 9, 30),
    adapter=price_adapter(), repository=repo, fx_symbol=settings.fx_symbol,
)
report, clean = assess_quality(prices, ["SPY"], benchmark_calendar(prices, "SPY"), settings)
fx = repo.get_fx_on_or_before(date(2026, 9, 30))   # 원화 환산용 USD/KRW
```

### M02-02 정규화기 (`data/normalizer.py`)

- 티커: 대문자, `.` → `-` (`BRK.B` → `BRK-B`). `.KS`·`.KQ` 접미사는 유지.
- 버리는 행과 사유: `invalid_price`(빈 값·NaN·0 이하), `invalid_date`, `unsupported_currency`(USD·KRW 아님), `duplicate`. `.KS`·`.KQ` 는 KRW, 나머지는 USD.
- `NormalizeResult.dropped` 에 버린 행 수, `dropped_by_reason`·`dropped_by_ticker` 에 내역.
- 환율 심볼(`KRW=X`) 행은 `FxRate(USDKRW)` 로 따로 나옴.
- 원본에 시가·고가·저가·종가가 있으면 PriceBar 에 담음 (교차검증용, 없거나 잘못된 값이면 None).
- 한국 종목도 PriceBar 로 들어감 (`currency="KRW"`). PriceFrame 하나에는 통화 하나만: 섞이면 `DATA_MIXED_CURRENCY`. `to_price_frame(bars, currency="KRW")` 로 골라 씀.
- 재무·뉴스: `normalize_financials`, `normalize_news` 가 `FinancialRow`·`NewsRow` 로 바꿈.

### M02-03 품질 판정기 (`data/quality.py`)

- 커버리지 = 값 있는 거래일 / 기대 거래일. `coverage_threshold` 미만이면 제외 (0.95 는 통과).
- 연속 결측이 `max_fill_days`(기본 1) 이하면 직전값으로 채움 → `FILLED`. 넘으면 제외.
- 첫 거래일부터 결측이면 채울 직전값이 없어 제외.
- 필수 종목 제외 → `DATA_REQUIRED_MISSING`, 남은 종목 0개 → `DATA_NO_USABLE_TICKER`. 예외 `details["report"]` 에 판정 결과가 들어 있음.
- (추가) 교차검증 결과는 경고만: `assess_quality(..., mismatch_days=summary.mismatch_days)` 로 넘기면 종목별 `mismatch_days` 와 `report.warnings`(Report 한계 문장)가 채워짐. 판정(OK·FILLED·EXCLUDED)은 바뀌지 않음.

### M02-04 저장소 (`data/repository/`)

- `MarketDataRepository` 인터페이스(명세 13개 + `needs_fetch`)와 `SqlRepository` (SQLAlchemy Core, 부록 B 테이블 7개 + 추가 5개). PostgreSQL·SQLite 같은 코드로 돎. 테이블 설명은 `역할A_모듈명세.md` 7절.
- DB 고르기 (`.env`): `DATABASE_URL` 에 Lightsail 주소(`postgresql://…?sslmode=require`), 비면 SQLite `data/myfinsight.db`. 연결 확인은 `python scripts/check_db.py`.
- 종목은 `assets` (예 `US-MSFT`, `KR-005930`), 출처는 `data_sources` (대문자 `YFINANCE`, `KIS` 등). 모르는 종목·출처는 저장할 때 자동 등록.
- 확장 메서드: `upsert_assets`/`get_assets`, `upsert_financials`/`get_financials_as_of`(공시일 기준, 미래 정보 차단), `upsert_news`/`get_news`, `source_status`. 수집 작업용: `covered_ranges`/`tickers_needing_fetch`(여러 티커 한 번에), `fetch_attempts`(출처·대상별 최근 성공·실패 횟수), `prune_news`(보관 기간 지난 기사 삭제). 교차검증용: `pending_verification`, `price_rows`, `save_verification`, `reset_verification`.
- upsert 는 읽어서 비교한 뒤 새 행 INSERT, 값이 다른 행만 UPDATE. 수집 시각만 다르면 건너뜀 → 같은 데이터 두 번째 저장은 0행.
- `get_prices` 는 요청 티커를 모두 열로 줌 (저장 값이 없으면 NaN 열). 같은 날 출처가 여럿이면 CONSENSUS → 통화별 출처 우선순위(미국 Alpaca → Tiingo → yfinance, 한국 yfinance → KIS) → 수집 시각이 늦은 값 순.
- `needs_fetch`: 저장 범위가 요청 범위를 덮고 마지막 저장일 ≥ 직전 평일이면 False. 시작일이 휴장일이어도 되게 시작 쪽은 4일 여유. 미국 공휴일은 고려하지 않음.
- 부록 B 에 더한 테이블·칸은 `역할A_모듈명세.md` 7절 (추가) 표시.
- 오류는 `RepositoryError` (`REPO_WRITE_FAILED` / `REPO_READ_FAILED`).

### M02-06 교차검증 (추가, `data/verify.py`)

- 같은 (종목, 날짜) 의 출처별 값을 비교해 CONSENSUS 행과 출처별 VERIFIED / MISMATCH / SINGLE 을 저장.
- 종가 허용 0.5%, 수정종가 허용 1% (KIS 수정종가는 배당 미반영이라 제외). 기준값은 중앙값, 출처가 2개면 우선순위 앞 출처.
- 수집과 품질 판정(M02-03)과 따로 둠. 저장소 메서드로만 DB 에 닿음 (C-10).

### M02-05 구성종목 수집기 (`data/constituents.py`, `data/constituent_source.py`)

- 갱신 판단: 최신 스냅샷 날짜 < 직전 정기 변경일이면 수집. SP500·NDX 는 3·6·9·12월 셋째 금요일, KOSPI200 은 6·12월 둘째 목요일 다음 날. `force=True` 면 항상.
- 결과 검사: 행 수(SP500 495~510, NDX 98~105, KOSPI200 198~202), 티커 중복, sector·industry 빈 칸, GICS 섹터 이름.
- Nasdaq-100 도 고정 파일 `config/ndx.csv` 를 읽음. 위키백과 Nasdaq-100 문서에서 구성종목 표가 빠져서(2026-10) stockanalysis.com 의 Nasdaq-100 목록(2026-10-04, 101종목)을 `scripts/make_constituents_csv.py --index NDX` 로 바꿔 넣어 둠.
- KOSPI200 은 고정 파일 `config/kospi200.csv` 를 읽음 (`FileConstituentSource`). 무료 공식 API 가 없어 KRX 에서 내려받은 표를 `scripts/make_kospi200_csv.py` 로 바꿔 둠. 정기 변경이 6·12월이라 12월까지는 같은 목록. 수집 작업은 `default_constituent_source()` 로 KOSPI200 → 파일, 나머지 → 위키백과.
- 통과하면 오늘 날짜로 저장. 실패하면 기존 스냅샷을 쓰고 `warnings` 에 Report 한계용 문장을 남김. 기존 스냅샷도 없으면 `DATA_CONSTITUENTS_UNAVAILABLE`.
- 출처 `WikipediaConstituentSource`:

| 항목 | 내용 |
|---|---|
| 출처 | 위키백과 영문판 구성종목 표 |
| URL | https://en.wikipedia.org/wiki/List_of_S%26P_500_companies , https://en.wikipedia.org/wiki/Nasdaq-100 |
| 갱신 방법 | 정기 변경일 이후 첫 실행 때 표를 다시 읽음 |
| 확인일 | 2026-10-03 (표 열 구성 확인. 실제 수집은 `try_adapters.py constituents` 로 확인 필요) |

- 출처 `FileConstituentSource` (KOSPI200):

| 항목 | 내용 |
|---|---|
| 출처 | 한국거래소 정보데이터시스템 지수구성종목 (코스피 200) 내려받기 → `config/kospi200.csv` |
| URL | https://data.krx.co.kr (지수 → 주가지수 → 지수구성종목) |
| 갱신 방법 | 원본 `config/kospi200_krx.csv` (2026-10-05 내려받음) → `python scripts/make_kospi200_csv.py --as-of 2026-10-05`. 6·12월 정기 변경 뒤 원본을 바꾸고 다시 실행 |
| 확인일 | 파일 첫 줄에 기준일·만든 날이 남음 |

- KOSPI200 sector 는 yfinance(Yahoo) 섹터를 GICS 11개 섹터 이름으로 바꾼 것, industry 는 Yahoo 산업 이름 (GICS Sub-Industry 와 이름이 다를 수 있음). 못 찾은 종목은 `config/gics_overrides.csv` 에 추가.

- S&P 500 표는 GICS Sector·Sub-Industry 를 줌. `industry` 칸에는 Sub-Industry 이름을 넣음 (예 `Semiconductors`, `Application Software`).
- Nasdaq-100 표는 ICB 분류라서 GICS 는 S&P 500 표에서 같은 티커로 찾고, 없으면 `config/gics_overrides.csv` 에서 찾음. 둘 다 없으면 검사에서 걸려 저장 안 됨. 경고에 나온 티커를 이 파일에 한 줄씩 추가하면 됨.

### 임시 스키마

`schemas/` (M00-02, 담당 D) 와 `config.py` (M00-01, 담당 C) 는 명세서를 그대로 옮긴 임시본. 확정본이 나오면 교체함. `config.py` 는 모델만 있고 파일 읽기 함수는 없음.
