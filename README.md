# 데이터 크롤러 및 DB

미국(S&P 500, Nasdaq-100)과 한국(KOSPI200) 종목의 가격·환율·재무·뉴스·공시를 실제 API 로 받아 정규화·교차검증한 뒤
DB(AWS Lightsail PostgreSQL, 서울)에 쌓음. 매일 수집은 GitHub Actions, 긴 백필은 PC 에서 돌림.
테이블은 `docs/DB_설계.md`, 수집 규칙은 `docs/수집작업.md`, 데이터 API 는 `docs/인스턴스_API.md`.

## 0. DB 데이터 현황 (2026-10-17 기준)

| 분야 | 시장 | 출처 | 기간 | 양 |
|---|---|---|---|---|
| 가격 | 한국 | 종가 KIS (빈 날 yfinance), 수정종가 yfinance (빈 날 KIS) | 1999-10-13 ~ 2026-10-15 | 1,004,212행, 202종목 |
| 가격 | 미국 | Alpaca (2016-01~), 그 전·빈 날 yfinance, Tiingo 표본 검증 | 1999-10-13 ~ 2026-10-16 | 3,037,126행, 520종목 |
| 환율 USD/KRW | | yfinance KRW=X (2003-12~), 빈 날 FRED | 1999-10-13 ~ 2026-10-16 | 7,005일 |
| 재무 | 한국 | DART (2015 사업연도~), KIS_FIN 연간 (2004~2014) | 기간 끝 2004 ~ 2026-06 | 165,442행, 200종목 |
| 재무 | 미국 | SEC EDGAR, 종류주식 4종목 주식 수 yfinance | 기간 끝 2005-03 ~ 2026-10 | 296,286행, 518종목 |
| 주식분할 | 둘 다 | yfinance | 1962 ~ 2026 | 1,738행 |
| 가치평가 (PER 등) | 한국 | 가격 + 재무로 계산 | 1999-10 ~ 2026-10-15, PER 2004-08~ | 998,204행 |
| 가치평가 (PER 등) | 미국 | 가격 + 재무로 계산 | 1999-10 ~ 2026-10-16, PER 2009-08~ | 3,023,197행 |
| 뉴스 | 한국 | Google RSS (2005-10~), 네이버 (2020-05~, 대부분 2026년) | 2005-10 ~ 2026-10-17 | 1,355,995건 |
| 뉴스 | 미국 | FNSPID (2009-04~2015), Alpaca/Benzinga (2015-12~), Google RSS (2016-10~), NewsAPI (2026-09~) | 2009-04 ~ 2026-10-17 | 3,276,202건 |
| 공시 | 한국 | DART | 2000-02 ~ 2026-10-15 | 377,670건, 201종목 |
| 공시 | 미국 | SEC EDGAR | 2000-01 ~ 2026-10-17 | 328,833건, 518종목 |
| 구성종목·분류 | 둘 다 | KRX 파일, stockanalysis(NDX), 위키백과(S&P 500), GICS 는 kr_gics.csv·위키백과 | 스냅샷 2026-10-04 | KOSPI200 201, S&P 500 503, NDX 101 |

- 대상은 지금 구성종목(한국 201, 미국 518) + ETF 3개. 과거 편출·상장폐지 종목이 없어 생존 편향이 있음.
- 빈 곳: 한국 2004년 전 재무, 2015년 전 분기·배당·주식 수. 미국 2009년 전 뉴스.
- 연도별 세부와 `coverage_report.py` 원문은 `docs/데이터_현황.md`. 다시 뽑기: `python backend/scripts/coverage_report.py` (읽기 전용).

## 1. 구조

```
role-a-server/
├─ backend/                 백엔드 (파이썬 패키지 backend)
│  ├─ adapters/             수집 어댑터 (base·factory·real) + crawlers/ (출처별 API 클라이언트)
│  ├─ db/                   저장소: 테이블 정의(tables)·SQL(sql)·읽기(readers)·open_repository
│  ├─ collectors/           출처별 수집: common(설정·시간 예산·이어받기 기록), prices·financials·news
│  │                        (각 update=매일·backfill=첫 수집, financials/supplements=분할·주식 수),
│  │                        constituents (구성종목), disclosures (공시)
│  ├─ pipeline/             수집 뒤 가공: 정규화·품질·교차검증·가치평가·GICS
│  ├─ jobs/                 실행 묶음: daily (매일 갱신, GitHub Actions)·backfill (첫 수집, PC)
│  ├─ schemas/              도메인 스키마 + PriceFrame 계약 검사
│  ├─ api/                  데이터 API (FastAPI, backend.api.app:app)
│  ├─ core/                 공통 설정(config)·경로(paths)
│  ├─ scripts/              얇은 실행 스크립트 (백필·점검·계정·마이그레이션 등)
│  ├─ tests/                테스트
│  ├─ data/config/          구성종목·분류 CSV        data/reference/  GICS 분류표
│  └─ deploy/               서버 설정 (systemd, Caddy)
├─ frontend/                프론트엔드 (아직 비어 있음)
├─ docs/                    문서 (DB 설계·ERD·DB 사용·API·수집 작업·데이터 현황)
└─ _local/                  푸시 안 함 (개인 문서, 일회성·안 쓰는 코드. .gitignore)
```

수집 흐름:

```
price_adapter() / financial_adapter() / news_adapter()        ← adapters/factory.py : 출처 이름으로 어댑터 만들기
   ▼
adapters/real.py    YFinancePriceAdapter, KisPriceAdapter, DartFinancialAdapter 등
   │  (adapters/base.py 의 RetryingFetcher 상속 → 재시도·요청 간격·실패 기록)
   ▼
adapters/crawlers/*_client.py  → 실제 API
   ▼
pipeline/normalizer.py → pipeline/quality.py → db/ (PostgreSQL·SQLite)
   ▲
collectors/*/update.py ← jobs/daily.py  (매일 갱신: 가격·구성종목·재무·뉴스·공시를 주기마다, 나눠서 이어 받기)
   ├ pipeline/verify.py     (출처 간 교차검증: CONSENSUS·MISMATCH, 가격 수집 끝에 이어서)
   └ pipeline/valuation.py  (일별 PER·PBR·ROE·배당수익률, 남은 시간에 증분)
   ▲
.github/workflows/collect.yml  (GitHub Actions 예약 실행: python -m backend.jobs.daily)
```

| 구성 | 하는 일 |
|---|---|
| 크롤러 `adapters/crawlers/` | API 를 부르고 응답을 해석 (출처마다 다름) |
| 어댑터 `adapters/real.py` | 크롤러 결과를 공통 형식(`RawPriceBatch` 등)으로 맞춤 |
| 어댑터 고르기 `adapters/factory.py` | 출처 이름으로 어댑터를 만듦 |
| 공통 부모 `adapters/base.py` | 재시도(1·2·4초), 배치 나누기, 요청 간격, 실패 기록 |
| 수집 `collectors/`, 묶음 `jobs/daily.py` | 무엇을 얼마나 받을지. PC·GitHub Actions·인스턴스 어디서든 같은 명령 |
| 예약 실행 `.github/workflows/collect.yml` | 언제 부를지만 적음 |

## 2. 설치 (Windows PowerShell, 처음 한 번)

Python 3.11 이상 (GitHub Actions 는 3.13). 이 폴더(`role-a-server`)에서 실행.

```powershell
py -3.13 -m venv .venv      # 3.11 만 있으면 py -3.11
.\.venv\Scripts\Activate.ps1
python -m pip install -e ".[dev,real,postgres,api]"
python -m pytest
```

- `-e .` 로 설치하면 어느 폴더에서든 `import backend` 가 됨. 스크립트·`python -m backend...` 는 저장소 루트에서 실행 (`.env` 를 루트에서 읽음).
- `[real]` 은 yfinance.
- `[postgres]` 는 psycopg 3 (`psycopg[binary]`, 주소는 `postgresql+psycopg://`). SQLite 만 쓰면 빼도 됨.
- `[api]` 는 데이터 API (FastAPI, uvicorn). 인스턴스에서만 필요 (`docs/인스턴스_API.md`). 빼면 `test_api.py` 를 건너뜀.
- 테스트는 실제 API 를 부르지 않음. PostgreSQL 테스트는 `MYFINSIGHT_TEST_PG_URL` 이 있을 때만 돌고 없으면 건너뜀.
- `Activate.ps1` 에서 "스크립트를 실행할 수 없습니다" 오류가 나면 `Set-ExecutionPolicy -Scope CurrentUser RemoteSigned` 를 한 번 실행.

## 3. 실제 API 로 받아 보기

1. `.env.example` 을 복사해 `.env` 를 만들고 가진 키를 채움: `copy .env.example .env`
2. 키가 읽히는지 확인 (값은 앞 3글자만 보임): `python backend/scripts/try_adapters.py env`
3. 모든 출처와 위키백과 구성종목 표를 조금씩 불러 봄. 키가 없는 출처는 건너뜀: `python backend/scripts/try_adapters.py smoke`
4. 원하는 것만 불러 보기:

```powershell
python backend/scripts/try_adapters.py price --source TIINGO --keys MSFT BRK-B
python backend/scripts/try_adapters.py price --keys 005930.KS KRW=X          # yfinance
python backend/scripts/try_adapters.py financial --source DART --keys 005930 --start 2025-01-01
python backend/scripts/try_adapters.py news --source NAVER_NEWS --keys 삼성전자
```

코드에서는 `price_adapter("TIINGO")` 처럼 출처 이름으로 어댑터를 만듦 (없으면 yfinance).

### 긴 백필 (PC → Lightsail, 처음 한 번)

재무 12년·일별 가치평가(`valuation_daily`)·뉴스 최대치는 GitHub Actions 의 짧은 실행으로는 못 채우므로 PC 에서 한 번 돌림.
자세한 시간·요청 수는 `docs/수집작업.md` 6절.

```powershell
pip install -e ".[real,postgres]"
python backend/scripts/migrate_v2.py            # 없는 새 테이블 확인만
python backend/scripts/migrate_v2.py --apply    # 만들기 (있는 데이터는 그대로)
python backend/scripts/backfill.py --max-minutes 600     # 끊겨도 같은 명령으로 이어서
python backend/scripts/coverage_report.py       # 결과 (읽기 전용 보고서)
```

**`.env` 는 비밀번호와 같음.** `.gitignore` 에 넣어 둠. 깃허브·메신저로 보내지 말고, 폴더를 줄 때도 `.env` 는 빼고 줌.
