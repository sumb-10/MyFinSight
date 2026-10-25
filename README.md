# MyFinSight

내 투자 조건과 말로 적은 투자 아이디어를 받아서, 종목을 고르고, 비중을 정하고, 과거 데이터로 성과와 위험을 계산해 리포트로 보여 주는 프로그램입니다. 실제 매매는 하지 않습니다.

**처음 켜는 방법은 [howtouse.md](howtouse.md)를 보세요.** 설계 문서는 `docs/`에 있습니다.

## 세 부분

| 부분 | 폴더 | 하는 일 |
| --- | --- | --- |
| 데이터 수집기와 DB | `backend/` (`adapters`, `collectors`, `pipeline`, `db`, `jobs`) | 미국(S&P 500, NASDAQ-100)과 한국(KOSPI200) 종목의 가격·환율·재무·뉴스·공시를 매일 받아 팀 데이터베이스(PostgreSQL)에 쌓습니다 |
| 분석 서비스 | `backend/analysis/` | 요청 확정(보충 질문) → 종목 선정 → 포트폴리오 구성 → 백테스트 → 조건 검증 → 리포트. 서버(API)와 일꾼(worker)으로 나뉩니다 |
| 화면 | `Front/` | 브라우저 화면(React). 프로필, 아이디어 입력, 질문, 조건 확인, 진행 상황, 리포트 |

흐름을 한 줄로 쓰면 이렇습니다.

```
화면(:5173) ──/api/v1──▶ 서버(:8001) ──줄 세우기──▶ 일꾼 ──읽기──▶ 팀 DB (가격·뉴스·재무)
                                                      └──쓰기──▶ 팀 DB (실행 기록·결과·리포트)
```

## 원칙 (왜 이렇게 만들었나)

- 숫자는 모두 코드가 계산합니다. LLM(언어 모델)은 아이디어 해석, 부족한 조건 질문, 회사 분류, 뉴스 의견, 설명 문장만 씁니다.
- 분석에 쓰는 자료는 팀 DB에서만 읽습니다. 분석 중에 인터넷 검색이나 다른 사이트 호출을 하지 않습니다.
- 기준일 이후 자료는 쓰지 못하게 코드로 막습니다. 리밸런싱 날의 비중은 그 전날까지 자료로 계산하고 그날 종가로 샀다고 봅니다.
- 리포트 문장의 숫자와 인용은 결과값·DB와 대조합니다. 맞지 않으면 리포트를 내지 않습니다.
- 같은 조건이면 같은 결과가 나오도록 LLM 응답을 저장해 다시 씁니다.
- 분석은 사용자가 조건을 확인하고 "분석 시작"을 누른 뒤에만 시작합니다.

## 폴더

```
MyFinSight/
├─ howtouse.md             켜는 방법, 쓰는 순서, 자주 생기는 문제
├─ backend/
│  ├─ analysis/            분석 서비스 (아래 표). 자세한 구조는 backend/analysis/README.md
│  ├─ adapters/ collectors/ pipeline/ jobs/   데이터 수집기 (아래 "데이터 수집기와 DB")
│  ├─ db/                  DB 테이블 정의와 읽기·쓰기 (analysis_readers.py 는 분석용 읽기)
│  ├─ api/                 데이터 조회 API (수집기 쪽, 분석 서비스와 별개)
│  ├─ schemas/ core/ scripts/ tests/ data/ deploy/
├─ Front/                  화면. 구조는 Front/README.md
├─ module_mockup/          초기 실험 코드 (동결, 참고용)
├─ docs/                   설계보고서, 모듈 명세, DB 설계, 데이터 현황, TODO.md
├─ data/                   로컬 저장 (프로필·요청·실행 목록). 깃에 안 올라감
└─ output/                 실행별 중간 결과. 깃에 안 올라감
```

`backend/analysis/` 안의 모듈은 설계보고서의 일곱 모듈과 같습니다.

| 모듈 | 폴더 | 한 줄 설명 |
| --- | --- | --- |
| 1 사용자·요청 | `m1_request/` | 프로필 저장, 요청 조립, 입력 검사, 보충 질문 대화 |
| 2 금융 데이터 | `m2_data/` | DB에서 가격·환율·재무·뉴스·공시 읽기, 기준일 보호, 품질 검사, 종목 사전 |
| 3 종목 선정 | `m3_selection/` | 아이디어 해석 → 후보 검색 → 분류 → 지표로 순위 → 회사별 근거 |
| 4 포트폴리오 | `m4_portfolio/` | 비중 4가지 방식, 공시·뉴스 근거 의견(공시가 주 근거), Black-Litterman, 공통 함수 `construct()` |
| 5 백테스트·리포트 | `m5_backtest_report/` | 과거 성과 계산, 조건 검증, 결과 묶기, 요약 대시보드 + 7부분 리포트(문서 v2), 인용 검사 |
| 6 모의투자 | `m6_tracking/` | 가상 자본으로 리포트 전략을 따라가며 평가·리밸런싱 |
| 7 화면 | `Front/` | React 화면 |
| 공통 | `executor/`, `api/`, `common/` | 단계 실행기(의존이 끝난 단계는 동시에)와 줄 세우기, 서버 API, 설정·LLM 호출·저장·경고 카탈로그 |

## 빠른 시작

```bash
source ~/.venvs/myfinsight/bin/activate
pip install -e ".[analysis,dev,postgres]"
cp .env.example .env            # DB 주소, (실제 LLM을 쓸 때) OPENAI_API_KEY 채우기
python backend/scripts/build_descriptor.py --universe ALL   # 종목 사전 (한 번)

uvicorn backend.analysis.api.app:app --port 8001            # 창 1 서버
python -m backend.analysis.executor.worker                   # 창 2 일꾼
cd Front && nvm use && pnpm install && pnpm dev              # 창 3 화면 → http://localhost:5173
```

더 자세한 설명과 문제 해결은 [howtouse.md](howtouse.md).

## 테스트

```bash
python -m pytest backend/tests/analysis -q     # 분석 서비스 (가짜 DB, LLM 호출 없음)
python -m pytest backend/tests -q              # 전체
cd Front && pnpm typecheck && pnpm build       # 화면
```

## 진행 상황

남은 일과 결정 사항은 [docs/TODO.md](docs/TODO.md)에, 라운드별 변경 기록은 [docs/updates/](docs/updates/)에 있습니다. 2026-10-25 라운드 4: 경고를 "행동이 필요한 것만" 보이게 정리, 공시 사건을 뉴스보다 앞선 근거로 연결, 단계·리밸런싱일 병렬 실행, 요약 대시보드가 있는 리포트 화면. 2026-10-24 기준으로 일곱 모듈이 모두 동작합니다: 프로필 → 아이디어 → 보충 질문 → 조건 확인 → 실행 → 리포트, 리포트에서 이어지는 조건 수정 요청(원안과 비교)과 모의투자(가상 자본 추적). 실제 팀 DB와 실제 LLM으로 끝까지 확인했고, 시나리오 실행 결과는 `docs/mvp/scenario_runs/`, 요구사항 점검표는 `docs/mvp/requirements_check.md`, 보고서 초안은 `docs/최종보고서_초안.md`에 있습니다.

---

# 데이터 수집기와 DB

아래는 수집기(역할 A) 설명입니다. 테이블은 `docs/DB_설계.md`, 수집 규칙은 `docs/수집작업.md`, 데이터 API는 `docs/인스턴스_API.md`.

미국(S&P 500, Nasdaq-100)과 한국(KOSPI200) 종목의 가격·환율·재무·뉴스·공시를 실제 API로 받아 정리하고 서로 비교해 확인한 뒤 DB(AWS Lightsail PostgreSQL, 서울)에 쌓습니다. 매일 수집은 GitHub Actions, 오래 걸리는 과거 자료 채우기는 PC에서 돌립니다.

## DB 데이터 현황 (2026-10-17 기준)

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
| 구성종목·분류 | 둘 다 | KRX 파일, stockanalysis(NDX), 위키백과(S&P 500), GICS는 kr_gics.csv·위키백과 | 스냅샷 2026-10-04 | KOSPI200 201, S&P 500 503, NDX 101 |

- 대상은 지금 구성종목(한국 201, 미국 518) + ETF 3개. 과거에 빠진 종목이나 상장폐지 종목은 없어서, 과거 구간을 돌리면 실제보다 좋게 나올 수 있습니다(생존 편향).
- 빈 곳: 한국 2004년 전 재무, 2015년 전 분기·배당·주식 수. 미국 2009년 전 뉴스.
- 연도별 세부와 보고서 원문은 `docs/데이터_현황.md`. 다시 뽑기: `python backend/scripts/coverage_report.py` (읽기만 함).

## 수집기 구조

```
backend/
├─ adapters/             수집 어댑터 (base·factory·real) + crawlers/ (출처별 API 클라이언트)
├─ db/                   저장소: 테이블 정의(tables)·SQL(sql)·읽기(readers, analysis_readers)·open_repository
├─ collectors/           출처별 수집: prices·financials·news·constituents·disclosures (update=매일, backfill=첫 수집)
├─ pipeline/             수집 뒤 가공: 정규화·품질·교차검증·가치평가·GICS·종목 사전(descriptor)
├─ jobs/                 실행 묶음: daily (매일, GitHub Actions)·backfill (첫 수집, PC)
├─ schemas/              데이터 모양 정의와 검사
├─ api/                  데이터 API (FastAPI, backend.api.app:app) — 분석 서비스 API 와 별개
├─ scripts/              실행 스크립트 (백필·점검·계정·마이그레이션·종목 사전)
├─ data/config/          구성종목·분류 CSV        data/reference/  GICS 분류표
└─ deploy/               서버 설정 (systemd, Caddy) — myfinsight-api·myfinsight-worker 유닛
```

수집 흐름:

```
adapters/factory.py (출처 이름 → 어댑터) → adapters/real.py → adapters/crawlers/*_client.py (실제 API)
   → pipeline/normalizer.py → pipeline/quality.py → db/ (PostgreSQL·SQLite)
collectors/*/update.py ← jobs/daily.py (매일 갱신: 가격·구성종목·재무·뉴스·공시)
   ├ pipeline/verify.py     출처 간 교차검증
   └ pipeline/valuation.py  일별 PER·PBR·ROE·배당수익률
.github/workflows/collect.yml  예약 실행 (python -m backend.jobs.daily)
```

## 수집기 설치 (Windows PowerShell, 처음 한 번)

Python 3.11 이상 (GitHub Actions는 3.13). 저장소 루트에서 실행합니다.

```powershell
py -3.13 -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -e ".[dev,real,postgres,api]"
python -m pytest
```

- `[real]`은 yfinance, `[postgres]`는 psycopg 3, `[api]`는 데이터 API(FastAPI, uvicorn), `[analysis]`는 분석 서비스.
- 테스트는 실제 API를 부르지 않습니다. PostgreSQL 테스트는 `MYFINSIGHT_TEST_PG_URL`이 있을 때만 돕니다.
- `Activate.ps1`에서 "스크립트를 실행할 수 없습니다"가 나오면 `Set-ExecutionPolicy -Scope CurrentUser RemoteSigned`를 한 번 실행합니다.

## 실제 API로 받아 보기

1. `.env.example`을 복사해 `.env`를 만들고 가진 키를 채웁니다: `copy .env.example .env`
2. 키가 읽히는지 확인(값은 앞 3글자만 보임): `python backend/scripts/try_adapters.py env`
3. 모든 출처를 조금씩 불러 봅니다. 키가 없는 출처는 건너뜁니다: `python backend/scripts/try_adapters.py smoke`
4. 원하는 것만:

```powershell
python backend/scripts/try_adapters.py price --source TIINGO --keys MSFT BRK-B
python backend/scripts/try_adapters.py price --keys 005930.KS KRW=X          # yfinance
python backend/scripts/try_adapters.py financial --source DART --keys 005930 --start 2025-01-01
python backend/scripts/try_adapters.py news --source NAVER_NEWS --keys 삼성전자
```

### 긴 백필 (PC → Lightsail, 처음 한 번)

재무 12년·일별 가치평가·뉴스 최대치는 GitHub Actions의 짧은 실행으로는 못 채우므로 PC에서 한 번 돌립니다. 시간·요청 수는 `docs/수집작업.md` 6절.

```powershell
pip install -e ".[real,postgres]"
python backend/scripts/migrate_v2.py            # 없는 새 테이블 확인만
python backend/scripts/migrate_v2.py --apply    # 만들기 (있는 데이터는 그대로)
python backend/scripts/backfill.py --max-minutes 600     # 끊겨도 같은 명령으로 이어서
python backend/scripts/coverage_report.py       # 결과 (읽기 전용 보고서)
```

**`.env`는 비밀번호와 같습니다.** `.gitignore`에 들어 있습니다. 깃허브·메신저로 보내지 말고, 폴더를 줄 때도 `.env`는 빼고 줍니다.
