# DB 설계 (M02-04)

근거: 새 데이터 계약 「module_prototype2」 2.2절(데이터 계약)·M2-01(수집 배치), Module2.md 3절.
그 전 근거였던 명세 「MyFinSight 프로토타입 모듈 명세 & 분배」 M02-04, 부록 B, C-05·C-06·C-10 중
계약과 겹치지 않는 부분(출처 관리, 교차검증, UTC 등)은 그대로 따름.
코드: `backend/db/` (`tables.py` 테이블 정의, `sql.py` 구현).

분석 코드는 DB 를 읽기 계정으로 읽고(계약 읽기 테이블 6개 + `fetch_log` + 파생 `valuation_daily` + 참조 `gics_taxonomy` + 공시 `disclosures`), 실행 기록 3개만 쓰기 계정으로 씀.
두 계정(`myfinsight_read`·`myfinsight_write`)은 2026-10-17 운영 DB 에 아직 없음 (계정은 마스터 `myfinsight` 와 팀원 `reader` 뿐, 만드는 법은 0-3절 5번).
분석 코드는 수집하지 않음 (K3). 이 저장소(역할 A 수집기)는 계약 테이블이 늘 맞게 채워지도록 책임짐.

## 0. 새 데이터 계약(module_prototype2) 대응

계약은 "컬럼명은 DB 정의를 따르고 아래는 모듈이 기대하는 최소 필드" 라서, 키와 최소 필드는 계약대로 두고
필요한 칸만 더 붙였음.

### 0-1. 계약 테이블 ↔ 우리 테이블

| 계약 테이블 | 계약 키 / 최소 필드 | 우리 테이블·칸 | 비고 |
|---|---|---|---|
| `assets` | `asset_id` (`US-<ticker>`·`KR-<6자리>`) / ticker, name, market(US·KR), currency(USD·KRW), yfinance_symbol | `assets` 같은 이름 | `market` 은 `US`·`KR` 만. 거래소는 새 칸 `exchange` (KOSPI·KOSDAQ, 미국은 아직 비움). 출처별 코드(`dart_corp_code`, `sec_cik`, `kis_ticker` …)·`asset_type` 은 추가 칸. GICS 4단계 코드·출처, KSIC, 사업 설명 칸 (4-7) |
| `index_constituent` | (`index_code` ∈ SP500·NDX·KOSPI200, `snapshot_date`, `ticker`) / name, sector, industry | `index_constituent` | `ticker`: 미국 yfinance 표기(`BRK-B`), 한국 6자리 코드(`005930`). `asset_id` 로 assets 와 연결. `sector`·`industry` 는 GICS 섹터·세부산업 영문 이름, 추가 칸 `gics_sub_industry_code` (그 스냅샷 당시 세부산업 8자리) |
| `price_daily` | (`asset_id`, `date`) / open, high, low, close, adj_close, volume (종목 통화) | `price_daily` (발행 테이블) | 출처별 원본 `price_daily_source` 에서 키마다 우선순위 1위 출처의 원본 값을 그대로 실음 (종가·OHLCV 와 수정종가는 출처 순서가 따로, 4-2). 추가 칸: `ticker`(yfinance 표기), `currency`, `source`(종가를 실은 출처), `adj_close_source`(수정종가를 실은 출처), `verify_status`, `fetched_at`, `updated_at` |
| `fx_daily` | (`pair`, `date`) / rate (1 USD 당 KRW) | `fx_daily` | 키를 (`pair`, `date`) 로 바꿈 (전에는 + `source`). `source`·`fetched_at` 은 일반 칸 |
| `financials` | (`asset_id`, `period_end`, `statement`, `item`) / value, 보고일 | `financials` (발행 테이블) | `item` = 지표 이름, `statement` = IS·BS·CF·ETC, 보고일 = `report_date` (공시일). 추가 칸: `unit`, `source`, `fs_div`, `period`, `updated_at`. 출처별 원본은 `financials_source` |
| `news` | `news_id` / asset_id, source, url, title, content, publisher, published_at(UTC), language(en·ko) | `news` 그대로 | 중복 판단 `url_hash` 등은 추가 칸 |
| `fetch_log` | 소스·대상·기간·상태·시각·오류 | `fetch_log` 그대로 (`source`, `target`, `start_date`·`end_date`, `status`, `fetched_at`, `error`) | 최신 SUCCESS 의 날짜 = 화면의 "데이터 마감" |
| `run_artifact` (쓰기) | `run_id` / request_id, created_at, 결과 통합 JSON, 파라미터 스냅샷, LLM 사용량 | `run_artifact`: `request_id`, `created_at`, `results_json`, `params_json`, `llm_usage_json` | 예전 칸(profile·spec·universe·config)은 `run_artifact_v1` 로 보관 |
| `run_step` (쓰기) | (`run_id`, `step`) / status, started_at, ended_at, summary, error_code, error_message | `run_step` | status ∈ QUEUED·STARTED·SUCCESS·PARTIAL·FAILED·CANCELLED (DB CHECK). `started_at` 은 QUEUED 때 비어 있을 수 있음 |
| `report` (쓰기) | `report_id` (= run_id) / created_at, 리포트 문서 JSON(불변), 전략명, 요청 요약, 분석 기준일 | `report`: `report_id`(→ run_artifact), `created_at`, `doc_json`, `strategy_name`, `request_summary`, `as_of` | 같은 `report_id` 로 다시 저장하면 거부 (불변) |

계약 밖 수집기 내부 테이블: `price_daily_source`, `financials_source` (출처별 원본·교차검증), `data_sources`, `extra_ticker`.
읽기 계정은 이 표들을 읽지 못함 (`backend/scripts/make_db_roles.py`).
계약 밖 파생 테이블 `valuation_daily` (일별 PER·PBR·ROE·배당수익률, 4-6) 와 참조 테이블 `gics_taxonomy` (GICS 분류표, 4-7) 는 읽기 계정이 읽을 수 있음.
`gics_taxonomy` 는 서비스 테이블이 아니라 `backend/data/reference/gics_taxonomy.json` 을 그대로 실은 참조 데이터 (K1: 서비스용 새 테이블을 만들지 않음, 사전 파일은 `backend/data/processed/`).

### 0-2. 수집기 규칙 (M2-01)

| 계약 | 구현 |
|---|---|
| 키가 같으면 값이 다를 때만 갱신 | 원본·발행 테이블 모두 "읽어서 비교 → 새 행 INSERT, 값이 다른 행만 UPDATE" (`_upsert`). 발행 테이블은 원본에서 바뀐 키만 다시 고르고, 고른 값이 그대로면 행을 다시 쓰지 않음 (`updated_at` 도 그대로) |
| 날짜 단위로 커밋 (읽는 중 일관성) | 한 번의 저장(출처 한 곳의 종목 묶음, 같은 기간)이 원본 저장 + 발행을 한 트랜잭션으로 함. 분석 쪽은 커밋된 묶음만 봄 |
| 원본 값을 가공하지 않음 (`adj_close` 는 소스 제공값) | 계약 `price_daily` 는 출처 행 하나를 그대로 실음. 교차검증 중앙값(CONSENSUS)은 원본 테이블의 내부 기록으로만 두고 계약 테이블에 싣지 않음 (전에는 `get_prices` 가 CONSENSUS 를 먼저 골랐음) |
| 구성종목 행 수 (SP500 495~510, NDX 98~105, KOSPI200 195~205) | `constituents.ROW_BOUNDS`. 범위 밖 스냅샷은 저장하지 않고 `fetch_log` 에 FAILED + 이유 (`constituents:<지수>`), 기존 스냅샷 유지 |
| 티커 표기 (미국 yfinance식, 한국 6자리) | `index_constituent.ticker`, `assets.ticker`. 코드 안에서는 계속 yfinance 표기(`005930.KS`)로 주고받고 `latest_constituents` 도 yfinance 표기로 돌려줌 |
| `fetch_log` 누적 | 모든 수집 시도(성공·실패)를 한 줄씩 |

### 0-3. Lightsail 운영 DB 옮기기 (주인이 할 일)

예전(v1) 스키마 DB 는 새 코드가 열지 않음 (`open_repository` 가 "migrate_v2 먼저" 오류). 순서:

1. GitHub Actions `collect` 예약 실행과 인스턴스 데이터 API 를 잠시 멈춤 (옮기는 동안 표 잠금).
2. 서버(또는 `.env` 에 마스터 계정 `DATABASE_URL` 이 있는 PC)에서 새 코드로 `pip install -e ".[postgres]"` (psycopg 3).
3. 확인만: `python backend/scripts/migrate_v2.py` → 계획과 행 수, 멈춤 사유(예: `fx_daily` 같은 날짜 중복)를 봄. 아무것도 안 바꿈.
4. 실행: `python backend/scripts/migrate_v2.py --apply` → 한 트랜잭션. 실패하면 전부 되돌아감. 지우는 행 없음.
   - `price_daily` → `price_daily_source`, `financials` → `financials_source` (제약·인덱스·시퀀스 이름도 바꿈)
   - `run_step`·`run_artifact`·`report` → `*_v1` (예전 실행 기록 보관)
   - `assets.exchange` 추가, `market` KOSPI·KOSDAQ → KR
   - `fx_daily` 기본키 (pair, date)
   - KOSPI200 구성종목 티커 `005930.KS` → `005930`
   - 새 테이블을 만들고 계약 `price_daily`·`financials` 를 원본에서 채움 (종목 20개씩)
5. 계정: `MYFINSIGHT_READ_PASSWORD=… MYFINSIGHT_WRITE_PASSWORD=… python backend/scripts/make_db_roles.py` 로 SQL 을 먼저 보고,
   `--apply` 로 실행. 읽기 계정 `myfinsight_read`, 쓰기 계정 `myfinsight_write` (이름은 `--reader`·`--writer`).
6. `python backend/scripts/check_db.py` 로 테이블 18개 확인 후 Actions·API 다시 켬. GitHub Actions 는 Python 3.13 + psycopg 로 돎.

이미 v2 로 옮긴 DB 에 새 테이블(`valuation_daily`)만 더할 때: `python backend/scripts/migrate_v2.py` (없는 테이블을 보여 줌, 바꾸지 않음)
→ `python backend/scripts/migrate_v2.py --apply` (없는 테이블만 만듦, 있는 데이터는 그대로) → `make_db_roles.py --apply` 다시 (읽기 권한).

v3 DB 에 v4 GICS 칸을 더할 때 (같은 스크립트, 같은 순서):
1. `python backend/scripts/migrate_v2.py` → `- assets: 칸 추가 gics_sector_code, …`, `- index_constituent: 칸 추가 gics_sub_industry_code`,
   `- gics_taxonomy: 분류표 파일과 다른 행 273개` 가 보이면 정상. 아무것도 안 바꿈.
2. `python backend/scripts/migrate_v2.py --apply` → 한 트랜잭션으로 NULL 허용 칸 추가 (`ALTER TABLE … ADD COLUMN`, 기본값 없음, 기존 행 그대로),
   `gics_taxonomy` 만들고 273행 채움. 다시 돌리면 "할 일 없음" (멱등). 분류표 파일을 고친 뒤 돌리면 바뀐 행만 고침.
3. `make_db_roles.py --apply` 다시 (읽기 계정에 `gics_taxonomy` SELECT).
4. `python backend/scripts/backfill.py --what gics` (종목별 GICS·KSIC·사업 설명 채움), `python backend/scripts/build_descriptor.py` (사전 파일).
옮기기 전에는 새 코드가 DB 를 열지 않음 (`open_repository` 가 "DB 에 새 칸이 없음 … migrate_v2" 오류, 테이블도 만들지 않음).

## 1. 범위

| 항목 | 내용 |
|---|---|
| 테이블 | 계약 읽기 6개 + `fetch_log` + 계약 쓰기 3개 + 수집기 내부 5개 + 파생 1개 + 참조 1개(`gics_taxonomy`) + 공시 1개(`disclosures`) = 18개 (옮긴 DB 에는 `*_v1` 보관 테이블이 더 있음) |
| DB | PostgreSQL 기본 (AWS Lightsail, 서울). 드라이버 psycopg 3 (`postgresql+psycopg://`, 명세 C-01). 같은 코드로 SQLite 교체 가능 (테스트·혼자 개발) |
| 시장 | 미국 S&P 500, Nasdaq-100, 한국 KOSPI 200 |
| 같은 키로 다시 받았을 때 | 값이 다르면 갱신, 같으면 건너뜀 (원본·발행 모두) |
| 저장소 메서드 | 명세 M02-04 메서드 (실행 기록 3개는 계약 모양으로 바뀜) + `needs_fetch`. 추가 테이블용 메서드는 따로 둠 (6절) |

## 2. 테이블 18개

| 테이블 | 묶음 | 하는 일 |
|---|---|---|
| `assets` | 계약 읽기 | 종목 마스터, 시장(US·KR)·거래소·통화, 출처별 종목 코드 |
| `index_constituent` | 계약 읽기 | 지수 구성종목 스냅샷 (M02-05) |
| `price_daily` | 계약 읽기 | 일별 가격, (종목, 날짜) 마다 한 행 (발행) |
| `fx_daily` | 계약 읽기 | USD/KRW 환율, 날짜마다 한 값 |
| `financials` | 계약 읽기 | 재무 지표, (종목, 기간 끝, 재무제표, 항목) 마다 한 행 (발행) |
| `news` | 계약 읽기 | 종목별 뉴스 + 사실 표시 칸 5개 (보도자료·제목에 종목명·같은 기사 묶음·첫 보도·쓸 수 있는 첫 거래일, 4-8) |
| `fetch_log` | 계약 읽기 | 수집 시도 기록 (누적, 데이터 마감) |
| `run_artifact` | 계약 쓰기 | 실행 산출물: 결과 통합 JSON, 파라미터, LLM 사용량 |
| `run_step` | 계약 쓰기 | 실행 단계 상태 |
| `report` | 계약 쓰기 | 리포트 문서 (불변) |
| `price_daily_source` | 수집기 내부 | 출처별 원본 가격 + 교차검증 (CONSENSUS 행 포함) |
| `financials_source` | 수집기 내부 | 출처별 원본 재무 지표와 공시일 |
| `fx_daily_source` | 수집기 내부 | 출처별 원본 환율 (YFINANCE `KRW=X`, FRED `DEXKOUS`). `fx_daily` 는 날짜마다 우선순위 출처 하나를 고름 |
| `data_sources` | 수집기 내부 | 출처 목록과 출처별 최근 성공·실패 시각 |
| `extra_ticker` | 수집기 내부 | 서비스 요청으로 늘어난 수집 대상 종목 |
| `valuation_daily` | 파생 (읽기) | `price_daily` + `financials` 로 계산한 일별 시가총액·PER·PBR·ROE·배당수익률 (4-6) |
| `disclosures` | 추가 (읽기) | 공시 목록: 미국 SEC EDGAR (8-K·10-Q·10-K 등), 한국 DART. 2000년부터, 유형(`event_type`)·쓸 수 있는 첫 거래일 (4-9) |
| `gics_taxonomy` | 참조 (읽기) | GICS 분류표 (2023-03 개편판: 섹터 11·산업그룹 25·산업 74·세부산업 163), 영문·한국어 이름, 상위 코드 (4-7) |

## 3. 수집기 내부 테이블을 둔 이유

| 테이블 | 이유 |
|---|---|
| `price_daily_source` | 가격 출처가 4곳(KIS, Alpaca, yfinance, Tiingo). 출처마다 받은 값을 그대로 남겨야 증분·백필 진행(출처별 저장 범위)과 교차검증을 할 수 있음. 키 (`ticker`, `date`, `source`), 예전 `price_daily` 칸 그대로 |
| `financials_source` | 재무 출처 DART·SEC EDGAR (+ 한국 2004~2014 연간 KIS_FIN, 분할 YFINANCE, 종류주식 주식수 YFINANCE_SHARES), 연결·별도 구분, 같은 지표의 보고서별 값. 키 (`asset_id`, `source`, `period`, `fs_div`, `metric`), 예전 `financials` 그대로 |
| `data_sources` | 출처가 21개 (2026-10-17: 가격 4, 환율 FRED, 재무 DART·SEC_EDGAR·KIS_FIN·YFINANCE_SHARES, 뉴스 5(FNSPID 포함), 검증 CONSENSUS, 구성종목 WIKIPEDIA·KRX·KRX_FILE·NDX_FILE, 가치평가 1, GICS 분류 1). 모든 `source` 칸이 이 표의 `source_name` 을 가리킴 (값은 이름 문자열). 출처별 최근 성공·실패 시각, 종류(QUANT·QUAL·META) |
| `extra_ticker` | 데이터 API `/prices` 에서 지수 밖 종목을 처음 요청하면 받아 저장하고 여기에 올림. 정기 수집(`jobs.universe`)이 다음 실행부터 모든 출처로 백필·증분. 칸: `ticker`(yfinance 표기), `asset_id`, `added_by`, `added_at` |

## 4. 칸

### 4-1. `price_daily_source` (출처별 원본)

| 칸 | 내용 |
|---|---|
| `ticker`, `date`, `source` (키) | yfinance 표기(`MSFT`, `BRK-B`, `005930.KS`), 날짜, 출처 |
| `adj_close`, `volume`, `currency`, `open`·`high`·`low`·`close` | 출처가 준 값 그대로. 수정종가는 배당 반영 방식이 출처마다 달라 종가를 따로 둠 (교차검증 기준) |
| `asset_id` (→ assets) | 종목 마스터 연결 |
| `source_count`, `dev_pct`, `adj_dev_pct`, `verify_status`, `outlier_sources` | 교차검증. 같은 날 출처별 값의 중앙값을 `source = 'CONSENSUS'` 행으로, 출처별 편차(종가 0.5%, 수정종가 1% 초과 = MISMATCH)를 기록. 출처 1개면 SINGLE. 계산은 `data/verify.py` |
| `fetched_at`, `fetch_log_id` | 수집 시각, 수집 기록 연결 |

### 4-2. `price_daily` (계약, 발행)

| 칸 | 내용 |
|---|---|
| `asset_id`, `date` (키) | 계약 키 |
| `open`, `high`, `low`, `close`, `adj_close`, `volume`, `currency` | 고른 출처 행의 값 그대로 (종목 통화: 미국 USD, 한국 KRW). `adj_close > 0` |
| `ticker` | yfinance 표기 (편의용, = `assets.yfinance_symbol`) |
| `source` | 종가·OHLCV·거래량을 실은 출처 (`ALPACA`, `KIS`, `YFINANCE` …) |
| `adj_close_source` | 수정종가를 실은 출처 (한국은 대부분 `YFINANCE`, yfinance 가 없는 날만 `KIS`) |
| `verify_status` | 그 키의 CONSENSUS 행 상태(VERIFIED·MISMATCH), 없으면 고른 행의 상태(SINGLE 또는 아직 검증 전 빈칸) |
| `fetched_at`, `updated_at` | 고른 행의 수집 시각, 이 행 값이 마지막으로 바뀐 시각 |

고르는 순서: 통화별 출처 우선순위 → 수집 시각이 늦은 행 → 출처 이름 순. CONSENSUS 는 고르지 않음.
종가·OHLCV·거래량(`source`)과 수정종가(`adj_close_source`)는 순서를 따로 둠 (`backend/db/sql.py` `DEFAULT_CLOSE_PRIORITY`·`DEFAULT_PRICE_PRIORITY`):

| 통화 | 종가·OHLCV·거래량 | 수정종가 |
|---|---|---|
| USD | `ALPACA → TIINGO → YFINANCE` | 같음 |
| KRW | `KIS → YFINANCE` (거래소 공식 API 먼저) | `YFINANCE → KIS` (KIS 수정주가는 배당 미반영) |

수정종가 순서는 `.env` 의 `PRICE_PRIORITY_US`·`PRICE_PRIORITY_KR` 로 바꿈 (바꾼 뒤 기존 행에도 반영하려면 `python backend/scripts/migrate_v2.py --apply --republish`).

### 4-3. `financials` (계약, 발행)

| 칸 | 내용 |
|---|---|
| `asset_id`, `period_end`, `statement`, `item` (키) | `item` = `financials_source.metric` (매출액, 자산총계, EPS(TTM) …), `statement` = `sql.STATEMENT_OF_ITEM` 표로 IS(손익)·BS(재무상태)·CF(현금흐름), 표에 없으면 ETC (발행주식수, BPS 등) |
| `value`, `unit` | 값과 단위 |
| `report_date` | 보고일 = 공시일(`disclosed_at`). 분석 쪽은 `report_date <= as_of` 인 값만 씀 (선견 금지) |
| `source`, `fs_div`, `period` | 고른 원본 행의 출처, 연결구분(CFS·OFS·-), 출처 기간 이름(`2025_11011`, `FY2025`) |
| `updated_at` | 이 행 값이 마지막으로 바뀐 시각 |

고르는 순서 (같은 키 후보가 여럿일 때): ① 시장별 출처 우선순위 (한국 DART, 미국 SEC_EDGAR 먼저) ② 연결(CFS) → 별도(OFS) → `-`
③ 가장 이른 공시일 ④ 기간 이름·출처 이름. `period_end` 가 없는 원본 행은 키를 만들 수 없어 싣지 않음.
한계: 정정 공시가 원본 키(출처·기간·연결구분·지표)가 같으면 원본 행을 덮어써서 값과 공시일이 함께 바뀜.
선견은 없지만 정정 전 값은 남지 않음 (열린 항목).

재무 항목 (`financials.item`, 출처 원본 `financials_source.metric`):

| 묶음 | 항목 | 출처 |
|---|---|---|
| 연간·누적 손익 | 매출액, 영업이익, 당기순이익, 지배주주순이익(한국, 있을 때), EPS(희석) | DART 주요계정, SEC 10-K |
| 한국 2004~2014 연간 | 매출액, 영업이익, 당기순이익, 자산·부채·자본총계 (연결), EPS·BPS (현재 주식 기준) | KIS 국내주식 연간 재무 (`source KIS_FIN`, collectors/financials/kis_history.py). 공시일 = 그 해 DART 사업보고서 최초 접수일 (`데이터_현황.md` 3절) |
| 분기(3개월) 손익 | 매출액(분기), 영업이익(분기), 당기순이익(분기), 지배주주순이익(분기), EPS(희석·분기) | SEC 10-Q 3개월 값(4분기 = 연간 − 9개월), DART 분기·반기·3분기 보고서 3개월 값(4분기 = 연간 − 9개월 누적) |
| 누적 손익 | 매출액(누적) 등 `(누적)` | DART 반기·3분기 보고서 누적 값 |
| 재무상태 | 자산총계, 부채총계, 자본총계 | 분기말·사업연도말 |
| 주식 수 | 발행주식수, 자기주식수, 유통주식수 | DART stockTotqySttus (보통주), SEC dei:EntityCommonStockSharesOutstanding (기간 `S<기준일>`). SEC 에 최근 값이 없는 종류주식 4종목(BRK-B·V·STZ·ERIE)은 yfinance (`YFINANCE_SHARES`) |
| 배당 | 주당배당금, 주당배당금(분기), 배당금총액 | DART alotMatter (사업보고서), SEC DividendsPerShareDeclared |
| 분할 | 주식분할 (비율) | yfinance 분할 이력 (`source YFINANCE`, 기간 `SPLIT<날짜>`) |

`(분기)`·`(누적)` 은 `statement` 를 정할 때 떼고 봄 (매출액(분기) → IS). 기간 이름: DART `2024_11013`, SEC `FY2024`·`Q2024-03-31`.

### 4-6. `valuation_daily` (파생, 읽기 계정 허용)

| 칸 | 내용 |
|---|---|
| `asset_id`, `date` (키) | 종목, 거래일 (`price_daily` 에 있는 날만) |
| `ticker`, `currency`, `close` | 그날 `price_daily` 의 yfinance 표기·통화·종가 (분할 보정된 값) |
| `split_factor` | 그날의 실제 종가 = `close × split_factor` (그 뒤 분할이 없으면 1) |
| `shares_outstanding`, `shares_as_of` | 그날 기준 주식 수(분할 반영)와 그 공시 기준일 |
| `market_cap` | 실제 종가 × 주식 수 (종목 통화) |
| `net_income_ttm`, `eps_ttm`, `per` | 최근 4분기 순이익 합, 주당 순이익(close 기준), 시가총액 ÷ 순이익 (순이익 ≤ 0 이면 NULL) |
| `bps`, `pbr` | 주당 자본, 시가총액 ÷ 자본총계 |
| `roe_ttm` | 순이익 TTM ÷ 평균 자본 |
| `dps_ttm`, `dividend_yield` | 최근 12개월 주당배당금, 배당수익률 (비율) |
| `fin_period_end`, `fin_disclosed_at` | 쓴 순이익의 마지막 분기 끝, 그 공시일 (선견 확인용, 늘 `<= date`) |
| `method` | 계산 방법 메모 (예: `NI=Q4;SH=유통주식수;DPS=Q4`, 분기 사슬이 끊기면 `NI=FY`, 한국 2004~2015 `PER=EPS@KIS_FIN;PBR=BPS@KIS_FIN`) |
| `updated_at` | 이 행 값이 마지막으로 바뀐 시각 (값이 같으면 다시 쓰지 않음) |

인덱스 `idx_valuation_daily_date (date)`. 계산 규칙·갱신 방식은 `수집작업.md` 5절, 코드 `data/valuation.py`.

### 4-7. GICS 칸 (v4)

`gics_taxonomy` (참조, 키 `code`):

| 칸 | 내용 |
|---|---|
| `code` | 2자리 섹터, 4자리 산업그룹, 6자리 산업, 8자리 세부산업 |
| `level` | 1~4 (CHECK) |
| `name_en`, `name_ko` | 영문 공식 이름, 한국어 이름 (프로젝트 번역, 공식 한국어 명칭 아님) |
| `parent_code` | 바로 위 단계 코드 (섹터는 NULL). 늘 내 코드의 앞부분 |
| `updated_at` | 행이 바뀐 시각 |

원본은 `backend/data/reference/gics_taxonomy.json` (저장소에 포함, 2023-03-17 시행판). 저장소를 열 때 테이블이 비어 있으면 채우고,
파일을 고친 뒤에는 `migrate_v2.py --apply` 또는 GICS 단계(`jobs meta`, `backfill --what gics`)가 바뀐 행만 맞춤.

`assets` 추가 칸 (모두 NULL 허용):

| 칸 | 내용 |
|---|---|
| `gics_sector_code`, `gics_industry_group_code`, `gics_industry_code`, `gics_sub_industry_code` | GICS 4단계 코드 (2·4·6·8자리). 섹터만 아는 종목은 섹터 코드만 |
| `gics_sub_industry` | 세부산업 영문 이름 (조회 편의) |
| `gics_source` | 어디서 정했는지: `WIKIPEDIA_SP500`, `OVERRIDE`(backend/data/config/gics_overrides.csv), `NDX_FILE`, `KR_MAP_REVIEWED`·`KR_MAP_DRAFT`(backend/data/config/kr_gics.csv 의 reviewed), `KR_MAP_KSIC_AUTO`(DART KSIC → backend/data/config/ksic_to_gics.csv), `CONSTITUENT_<지수>`, `YAHOO_FALLBACK`(섹터만) |
| `gics_updated_at` | GICS 값이 마지막으로 바뀐 시각 |
| `ksic_code` | DART 기업개황 `induty_code` (한국 종목, 표준산업분류) |
| `business_summary`, `business_summary_source` | 사업 설명 원문(yfinance `longBusinessSummary` 등)과 출처. 사전의 소개 문장 재료 |

정하는 순서와 규칙은 `수집작업.md` 7절. 이번 실행에서 못 정해도 저장된 값은 지우지 않음.
ETF·지수(`asset_type` ≠ STOCK)는 대상 아님.

`index_constituent.gics_sub_industry_code`: 그 스냅샷 행의 세부산업 이름(`industry`)을 분류표로 푼 코드. 이름이 분류표에 없으면
코드 없이 저장하고 `fetch_log` PARTIAL + 경고로 알림. 예전 스냅샷(한국 Yahoo 이름)은 GICS 단계가 종목의 GICS 로 이름·코드를 고침.
과거 기준일의 분류가 필요하면 이 칸(당시 분류)을 쓰고, 없을 때만 `assets` 의 현재 분류를 씀 (사전의 `gics_asof`).

### 4-8. `news` 사실 표시 칸 (v5)

전략과 상관없이 누가 봐도 같은 결과인 표시만 둠 (감성·쓸모 판단은 전략 쪽). 규칙은 `backend/pipeline/news_labels.py`
(버전 `news-v1`). 새 기사는 `upsert_news` 가 저장할 때 채우고, 규칙을 바꾸면 `backend/scripts/label_news.py --apply --all` 로 다시 계산.

| 칸 | 내용 |
|---|---|
| `is_press_release` | 기업 보도자료 (어느 회사든). 언론사가 PR Newswire·Business Wire·GlobeNewswire·뉴스와이어·"… Newsroom" 이거나, 언론사·주소가 회사 도메인(samsung.com, news.samsung.com) |
| `title_has_name` | 제목에 종목 이름(Inc.·(주) 등을 뗀 것)·검색어·별칭(네이버·삼전 등)이 있거나, 미국 티커가 `(AAPL)`·`$AAPL`·3글자 이상 대문자 단어로 있음. 관련 없는 기사를 거르는 데 씀 |
| `story_id` | 같은 종목·같은 날(시장 현지)·제목 앞 40글자(정규화)가 같은 기사 묶음. 전재·같은 보도자료를 묶는 수준 (매체마다 제목을 바꾼 기사는 따로) |
| `is_first_report` | 묶음에서 가장 먼저 발행된 기사 (같은 시각이면 `news_id` 순). 나중에 더 이른 기사가 들어오면 바뀜 |
| `available_on` | 쓸 수 있는 첫 거래일. 평일 장 시작(KR 09:00, US 09:30 현지) 전이면 그날, 아니면 다음 평일. 날짜만 오는 기사(Google RSS 는 태평양 자정, FNSPID 일부는 UTC 자정)는 그날 끝에 나왔다고 보고 계산 (선견 방지). 휴장일은 따로 보지 않음 |

인덱스 `idx_news_asset_story (asset_id, story_id)`. 2026-10-17 기준 전체 463만 건 모두 채움 (2026-10-15 계산: 보도자료 1.2%, 제목에 종목명 50%
(네이버 26%, Google RSS 52%), 첫 보도 98%).

### 4-9. `disclosures` (v5)

| 칸 | 내용 |
|---|---|
| `disclosure_id` | 자동 번호 |
| `asset_id`, `source`, `filing_id` (유일) | 종목, `SEC_EDGAR`·`DART`, 공시 번호 (SEC accession no. / DART rcept_no). 한 공시가 여러 종목에 걸리면 종목마다 한 행 |
| `form`, `items`, `title` | 양식 (8-K, 10-Q / DART 보고서 종류), 8-K Item 번호 (`2.02,9.01`), 제목 |
| `filed_at` | 접수 시각 (SEC 는 접수 시각, DART 는 날짜만 있어 그날 0시 서울) |
| `available_on` | 쓸 수 있는 첫 거래일. SEC: 동부 시각 평일 09:30 전 접수면 그날, 아니면 다음 평일. DART: 장중인지 몰라 다음 평일 (보수적) |
| `is_amendment` | 정정 공시 (8-K/A, [기재정정]) |
| `url` | 원문 링크 |
| `event_type`, `rule_version` | 유형 (`backend/collectors/disclosures/categories.py`)과 규칙 버전. SEC 는 8-K Item 으로 (2004-08-23 전 옛 Item 체계는 `sec-old-…`), DART 는 보고서 이름 키워드로. 규칙을 바꾸면 `backend/scripts/reclassify_disclosures.py` |
| `fetched_at`, `fetch_log_id` | 수집 기록 |

인덱스 `idx_disclosures_asset_available (asset_id, available_on)`. 2026-10-17 기준 SEC 32.9만 건(518종목), DART 37.8만 건(201종목), 2000년부터.
자주 나오는 유형: SEC `major_holder`(지분 보고)·`earnings`(Item 2.02)·`quarterly_report`·`executive_change`·`material_agreement`,
DART `derivative_offering`(파생결합증권)·`major_holder`·`related_party`·`earnings`·`buyback`·`dividend`·`rumor_response`(조회공시 답변).

### 4-4. 그 밖의 칸

- `assets.exchange`: 한국은 yfinance 접미사로 채움 (`.KS` KOSPI, `.KQ` KOSDAQ). 미국 거래소는 출처마다 표기가 달라 아직 비움.
- `index_constituent.asset_id` (→ assets): 구성종목과 가격을 같은 종목으로 묶음. `source` 칸은 출처 이름 + URL 글자라 FK 아님.
- `fetch_log.fetched_count`·`inserted_count`: 받은 행 수, 새로 저장·갱신한 행 수. 기록할 때 `data_sources.last_success_at`·`last_failure_at` 도 갱신.
- `run_step.status` 는 DB CHECK 제약으로 6가지 값만 받음. `financials.statement` 도 CHECK (IS·BS·CF·ETC), `gics_taxonomy.level` 도 CHECK (1~4).

### 4-5. 타입

| 대상 | 이 구현 | 이유 |
|---|---|---|
| `*_json` 칸 | PostgreSQL `jsonb`, SQLite JSON 문자열 | PostgreSQL 에서 JSON 안을 SQL 로 조회 가능 |
| 시각 칸 | PostgreSQL `timestamptz`, SQLite 는 UTC 로 바꿔 저장 | C-05 (UTC) |
| `volume` | BIGINT | PostgreSQL INTEGER 는 32bit |
| 가격·값 칸 | double precision | |
| `fetch_log.id`, `news.news_id` | BIGINT 자동 증가 (SQLite 는 INTEGER) | |

## 5. 공통 스키마(M00-02)에 더한 것

| 항목 | 더한 것 | 이유 |
|---|---|---|
| `IndexCode` | `KOSPI200` | 한국 지수 |
| `IndexConstituent.gics_sub_industry_code` | 선택 칸 (기본 None) | 스냅샷 당시 GICS 세부산업 코드 |
| `PriceBar.currency` | `"USD"` 에 `"KRW"` 추가 | 한국 종목 가격을 원 단위로 저장 |
| `PriceBar.open`·`high`·`low`·`close` | 선택 칸 (기본 None) | 출처 간 종가 교차검증, 계약 OHLC |
| `TickerQuality.mismatch_days`, `DataQualityReport.warnings` | 새 칸 | 교차검증 MISMATCH 를 품질 판정에 경고로만 전달 |
| `PriceMeta.currency` | 새 칸 (기본 `"USD"`) | 한 PriceFrame 은 한 통화만 담음 |
| `AssetInfo` | `market: Literal["US", "KR"]`, `exchange` | 계약 market 값 |
| `StepRecord` / `StepStatus` | 계약 run_step 모양: status 6가지, `started_at` 선택, `sources` 칸 뺌 | 계약 run_step 에 없는 칸 |
| `AssetInfo`, `FinancialRow`, `NewsRow` | 새 모델 (`schemas/market_ext.py`) | assets·financials_source·news 에 넣는 행 |

`schemas/profile.py`·`spec.py`·`report.py` 는 저장소에서 더 쓰지 않음 (실행 기록은 dict 로 저장). 다른 코드가 쓰는 동안 그대로 둠.

## 6. 규칙

| 규칙 | 내용 |
|---|---|
| 같은 키로 다시 받음 | 원본 값(`adj_close`, `volume`, `currency`, 시가·고가·저가·종가)이 다르면 갱신하고 교차검증 표시를 비움, 같으면 건너뜀. 수집 시각만 다르면 건너뜀. 배당·분할 때 과거 수정종가가 바뀌므로 갱신이 필요함 |
| 발행 | 원본을 저장한 같은 트랜잭션에서 바뀐 키만 계약 테이블에 다시 고름 (`_publish_prices`, `_publish_financials`). 교차검증 저장(`save_verification`)·초기화(`reset_verification`) 때도 `verify_status` 를 맞춤. PostgreSQL 은 발행 단계를 `pg_advisory_xact_lock` 으로 한 번에 하나씩 돌려, 출처 줄이 동시에 저장해도 순위가 낮은 값이 덮어쓰지 않음 |
| 키 | 계약 테이블은 0-1 표대로. `price_daily_source` (`ticker`, `date`, `source`), `financials_source` (`asset_id`, `source`, `period`, `fs_div`, `metric`), `news` 중복 판단 (`asset_id`, `url_hash`) |
| 출처 이름 | 대문자로 맞춤 (`yfinance` → `YFINANCE`). 처음 보는 출처는 data_sources 에 자동 추가 |
| 환율 | 출처별 원본은 `fx_daily_source` (YFINANCE, FRED). `fx_daily` 는 날짜마다 우선순위 출처 하나 |
| 통화 | 한 PriceFrame 은 한 통화. 미국·한국을 섞어 요청하면 오류 (`REPO_READ_FAILED`). 시장별로 나눠 요청 |
| 새 종목 | 가격·구성종목 저장 때 assets 에 없는 종목은 기본 행 자동 생성 (`market` US·KR, 한국은 `exchange` 도). 재무·뉴스는 assets 에 먼저 있어야 함 |
| 종목 종류 | `assets.asset_type` = STOCK / ETF / INDEX. `BENCHMARK_TICKERS`·`ETF_TICKERS` 는 prices 실행 때 ETF 로 맞춤. 전략 쪽은 `WHERE asset_type = 'STOCK'` 으로 ETF 를 뺌 |
| 구성종목 정기 변경일 | SP500·NDX: 3·6·9·12월 셋째 금요일. KOSPI200: 6·12월 둘째 목요일(선물·옵션 만기일) 다음 날 |
| 교차검증 | 종가 0.5%, 수정종가 1% (KIS 수정종가는 배당 미반영이라 비교 안 함). 기준값 = 중앙값, 출처 2개면 우선순위 앞 출처. 자세한 건 `수집작업.md` 3절 |
| 실행 기록 | `save_run_artifact(run_id, request_id, results, params, llm_usage=None)` (같은 run_id 면 바꿈), `save_step(StepRecord)`, `save_report(report_id, doc, strategy_name=, request_summary=, as_of=)` 는 run_artifact 가 있어야 하고 이미 있으면 거부 (불변) |
| upsert 방식 | 읽어서 비교 → INSERT / UPDATE. `ON CONFLICT` 같은 방언 문법을 안 써서 PostgreSQL·SQLite 가 같은 코드로 돎 |

추가 메서드 (추가 테이블용): `upsert_assets` / `get_assets`, `upsert_financials` / `get_financials_as_of` (출처별 원본을 공시일 기준으로, API·디버그용),
`upsert_news` (사실 표시 채움, 4-8) / `get_news`, `upsert_disclosures`, `source_status`, `fetch_history`, `get_run_artifact`, `add_extra_tickers` / `extra_tickers`, `publish_all` (원본으로 계약 테이블 전체 채우기, `migrate_v2` 가 씀).
서버 수집 작업용 (`collectors/`·`jobs/daily.py`): `covered_ranges` / `tickers_needing_fetch` (원본 저장 범위, 출처별), `fetch_attempts`, `prune_news`.
GICS 용: `sync_gics_taxonomy`, `gics_taxonomy_rows`, `asset_profiles`, `update_asset_profiles` (바뀐 칸만), `constituent_snapshots`, `constituent_gics_gaps`, `update_constituent_gics`.
읽기 전용 조회 (`repository/readers.py`, 읽기 계정으로도 됨): `readonly_engine`, `descriptor_inputs`.
긴 백필·가치평가용: `fetch_targets_done`, `count_fetches`, `job_lock` (PostgreSQL 세션 잠금, 백필 둘이 겹치지 않게), `valuation_assets`, `price_last_dates`, `valuation_last_dates`, `valuation_changes`, `valuation_inputs`, `upsert_valuation`.
PostgreSQL 에서는 `upsert_prices`(출처마다)·`upsert_financials`·`upsert_news`·`upsert_valuation` 이 테이블별 `pg_advisory_xact_lock` 을 잡아 정기 수집과 백필이 같은 키를 동시에 넣지 않음. 새 종목을 assets 에 자동으로 넣을 때도 `assets` 잠금을 잡고 다시 확인함 (잠금 순서: assets → 원본 → 발행).
교차검증용 (`verify.py`): `mismatch_days`, `pending_verification` (부분 인덱스 `idx_price_source_unverified`), `price_rows`, `save_verification`, `reset_verification`.

## 7. 다른 역할에 미치는 영향

- 분석 쪽은 계약 테이블 6개 + `fetch_log` 를 읽기 계정으로 읽음. 원본(`*_source`)·`data_sources` 는 읽지 않음.
- `get_prices` 값이 CONSENSUS 중앙값이 아니라 우선순위 출처의 원본 값이 됨 (계약: 가공하지 않음). 불일치는 `verify_status`·`mismatch_days` 경고로만.
- `assets.market` 이 `KOSPI`·`KOSDAQ` 대신 `KR`. 거래소가 필요하면 `exchange`.
- KOSPI200 구성종목 `ticker` 가 6자리 코드. yfinance 표기는 `assets.yfinance_symbol` (조인 `asset_id`).
- 실행 기록 메서드 모양이 바뀜 (6절). 예전 실행 기록은 `run_*_v1`·`report_v1` 에 남아 있음.
- 분석 쪽은 종목의 GICS 를 `assets.gics_*` (현재) 또는 `index_constituent.gics_sub_industry_code` (스냅샷 당시) 로, 이름·상위 분류를 `gics_taxonomy` 로 읽음. 종목 검색용 사전은 DB 가 아니라 `backend/data/processed/<universe>_descriptor_<날짜>.json` (`backend/scripts/build_descriptor.py`).
- 공시는 `disclosures` 를 `available_on <= 기준일` 로 읽음. 뉴스도 `available_on` 으로 자르면 선견이 없음. 관련 기사만 쓰려면 `title_has_name`, 보도자료를 빼려면 `NOT is_press_release`, 중복을 빼려면 `is_first_report` (4-8).
- 금융 섹터(GICS 40)는 매출액·영업이익 항목이 없는 것이 정상 (`coverage_report.py` 가 '해당 없음' 으로 셈).
- M3-04 의 `pe_ttm`·`roe_ttm`·`dividend_yield_ttm` 은 `financials` 로 직접 계산하는 대신 `valuation_daily` 의 `per`·`roe_ttm`·`dividend_yield` 를 `date <= as_of` 로 읽어도 됨 (공시일 기준이라 선견 없음). 직접 계산하려면 분기 항목 `당기순이익(분기)` 등을 쓰면 됨.

## 8. 연결

`.env`:

| 모드 | 설정 | 쓰는 곳 |
|---|---|---|
| AWS Lightsail PostgreSQL | `DATABASE_URL=postgresql://myfinsight:비번@엔드포인트:5432/myfinsight?sslmode=require` | 팀 공용 데이터 (수집·인스턴스). 코드가 `postgresql+psycopg://` 로 바꿔 씀 |
| 같은 DB, 분석 쪽 | 읽기 `myfinsight_read`, 쓰기 `myfinsight_write` (`backend/scripts/make_db_roles.py`, 아직 만들지 않음) | 분석 모듈 |
| 같은 DB, 팀원 조회 | `reader` (`backend/scripts/make_reader.py`, 모든 테이블 SELECT) | 팀원 (`팀원_DB_사용.md`) |
| SQLite | `DATABASE_URL` 비움 → `data/myfinsight.db` | 설치 없이 바로 (테스트·혼자 개발) |

PostgreSQL 은 추가 설치 필요: `pip install -e .[postgres]` (psycopg 3). 연결 확인은 `python backend/scripts/check_db.py`.
테스트는 인메모리 SQLite 로 돌고, `MYFINSIGHT_TEST_PG_URL=postgresql+psycopg://…` 을 주면 PostgreSQL 에서도 한 번 더 돎 (README 7절).
