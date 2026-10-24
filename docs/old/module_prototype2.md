# MyFinSight 모듈 명세 (서비스 사양)

**표기:** 🤖 LLM 호출 · 🛠 구현됨(mock-up에 있음) · 🔧 부분 구현(변경할 것을 명시) · 📄 문서만(미구현) · 🔶 팀 확인 필요

# 1. 전체 구조

## 1.1 모듈 목록

| Module | ID | 모듈 | 상태 | 핵심 파일 · 저장소 |
| --- | --- | --- | --- | --- |
| 0 공통 | M0-01 | 설정·경로·자격 증명 | 🛠 | `common.py` `portfolio_config.py` `backtest_config.py` `llm_config.py` `.env` |
| 0 공통 | M0-02 | 데이터 계약·스키마 | 🔧 | `schemas.py` + DB 테이블 매핑 |
| 0 공통 | M0-03 | LLM 호출기 🤖 | 🛠 | `llm.py` `prompts/` `stubs/` `output/llm_*` |
| 0 공통 | M0-04 | DB·로컬 저장 접근 계층 | 🔧 | `news_db.py` → `db.py`(DB 읽기·쓰기) + `store.py`(로컬 JSON 저장소 `store/`) |
| 0 공통 | M0-05 | 실행기·실행 기록 | 🔧 | `run_pipeline.py` + 작업 큐(단일 워커), DB `run_step`, `store/data/runs.json` |
| 0 공통 | M0-06 | 서비스 API | 📄 | 화면 ↔ 백엔드 계약 |
| 1 사용자·이력·컨텍스트 | M1-01 | 프로필 관리 | 📄 | `store/data/profile.json` |
| 1 | M1-02 | 요청 조립·검증·보충 질문 🤖 | 🔧 | `stage1_normalize.py` + M3-01, `store/data/requests/` |
| 1 | M1-03 | 실행 이력·컨텍스트 저장소 | 📄 | DB `run_artifact` `report` + `store/data/requests/` `runs.json` |
| 1 | M1-04 | 수정 요청 처리 🤖 | 📄 | M1-02·M3-01 재사용 |
| 2 금융 데이터 | M2-01 | 수집 배치 (팀 DB 담당) | 📄 외부 | 팀 수집기 → DB, `fetch_log` (mock-up의 `fetch_data.py`는 개발용) |
| 2 | M2-02 | 시장 데이터 조회·품질 판정 | 🔧 | `metrics.py` `backtest_engine.py` 조회 함수 → M0-04 |
| 2 | M2-03 | 유니버스 디스크립터 (🤖 선택) | 🔧 | `build_descriptor.py` `descriptor.py` `stage0_descriptor_llm.py` |
| 2 | M2-04 | 뉴스 근거 조회 | 🔧 | `news_db.py` |
| 3 종목 선정·전략 생성 | M3-01 | 의도 해석기 🤖 | 🔧 | `stage2_intent.py` `prompts/02_intent` |
| 3 | M3-02 | 후보 검색기 | 🛠 | `stage3_retrieve.py` |
| 3 | M3-03 | 후보 분류기 🤖 | 🛠 | `stage4_classify.py` `prompts/04_classify` |
| 3 | M3-04 | 정량 스크린·선정기 | 🛠 | `stage5_screen.py` `metrics.py` |
| 3 | M3-05 | 종목별 근거 서술기 🤖 | 🔧 | `stage6_explain.py` `prompts/06_explain` |
| 4 포트폴리오 구성 | M4-01 | 구성 사양·기준일 확정 | 🔧 | `stage7_confirm.py` |
| 4 | M4-02 | 시장모형·템플릿 비중 | 🛠 | `stage8_baseline.py` `portfolio.py` |
| 4 | M4-03 | 뉴스 근거 창·뷰 생성기 🤖 | 🔧 | `stage9a_news.py` `stage9_views.py` `prompts/09_views_news` |
| 4 | M4-04 | Black-Litterman 타겟 | 🛠 | `stage10_black_litterman.py` `portfolio.py` |
| 4 | M4-05 | 날짜별 구성 함수 | 🔧 | `stage10w_walkforward.py` `stage10f_forward.py` → `construct()` |
| 5 백테스트·검증·결과 종합 | M5-01 | 백테스트 시뮬레이터 | 🛠 | `stage11_backtest.py` `backtest_engine.py` |
| 5 | M5-02 | 성과 지표 계산기 | 🛠 | `backtest_metrics.py` |
| 5 | M5-03 | 규칙 검증·추천기 | 🛠 | `stage12_validate.py` |
| 5 | M5-04 | 결과 통합·비교 | 🔧 | `stage13_collect.py`, DB `run_artifact` |
| 5 | M5-05 | 리포트 문서 생성기 🤖 | 🔧 | `stage14_report.py` `report_blocks.py` `prompts/14a_interpret` `14b_narrate`, DB `report` |
| 6 tracking | M6-01 | 트래킹 시작·등록 | 📄 | `store/data/paper/<paper_id>/portfolio.json` |
| 6 | M6-02 | 일일 갱신기 | 📄 | `store/data/paper/<paper_id>/snapshots.jsonl` |
| 6 | M6-03 | 리밸런싱 실행기 | 📄 | M4-05 재사용, `store/data/paper/<paper_id>/rebalances.jsonl` |
| 6 | M6-04 | 트래킹 결과 제공 | 📄 | M0-06 응답 객체 |
| 7 화면 | M7-01 | 화면 구조·내비게이션 | 📄 | React |
| 7 | M7-02 | 프로필 화면 | 📄 | ↔ M1-01 |
| 7 | M7-03 | 분석 요청 화면 | 📄 | ↔ M1-02, M0-05 |
| 7 | M7-04 | 리포트 화면 | 📄 | ↔ M5-05 |
| 7 | M7-05 | 모의투자 화면 | 📄 | ↔ Module6 |
| 7 | M7-06 | 수정·비교 화면 | 📄 | ↔ M1-04, M5-04 |

## 1.2 사용자 여정과 실행 흐름

```
[상시]   M2-01 수집 배치가 DB를 매일 갱신(가격·환율·재무·구성종목·뉴스) → M2-03 디스크립터 주기 갱신
[프로필] M7-02 최초 프로필 설정 → M1-01 저장 (1회, 이후 수정 가능. 수정해도 과거 리포트는 그대로)
[요청]   M7-03 홈: 자연어 아이디어 입력 → M1-02 요청 조립(프로필 + 아이디어 + 이번 조건) → HARD 검증
         → M3-01 의도 해석 🤖 (M1-03 컨텍스트 패키지 포함) → 부족·충돌·모호 항목이 있으면 보충 질문(한 번에 1개, 최대 5회)
         → 조건 확인 화면 → 사용자가 「분석 시작」을 누른 뒤에만 실행
[분석]   M0-05 실행기(run_id 발급, 단계 상태를 DB run_step에 기록, 취소 가능)
         Module3  M3-02 후보 검색 → M3-03 후보 분류 🤖 → M3-04 스크린·선정 → M3-05 종목별 근거 🤖
         Module4  M4-01 구성 사양(분석 기준일·백테스트 창·시작일 재선정·자본 환율)
                  → M4-05 구성 함수 [M4-02 시장모형·템플릿 → M4-03 뉴스 근거·뷰 🤖 → M4-04 BL]
                    를 ① 백테스트 시작일 ② walk-forward 리밸런싱일마다 ③ 분석 기준일("현재 구성")에 호출
         Module5  M5-01 백테스트(M5-02 지표) → M5-03 규칙 검증·추천·대안 → M5-04 결과 통합 → M5-05 리포트 문서 🤖
                  → M1-03 이력 저장(요청·결과·리포트)
[리포트] M7-04 리포트 상세 → 재분석(M1-03) | 수정 요청(M1-04 → 수정안 분석 → M5-04 비교 → M7-06) | 모의투자 시작
[추적]   M7-05 시작 확인 → M6-01 등록 → 매일 M6-02 갱신(DB 가격) → 리밸런싱일 M6-03(M4-05 재실행 → 새 타겟 적용)
         → M6-04 결과 → M7-05 목록·상세
(모든 단계: M0-02 스키마로 검증한 뒤 output/NN_*.json 저장. 경고는 warnings에 쌓여 결과 통합·리포트까지 전달. 복구 불가면 중단, 리포트 미생성)
```

## 1.3 데이터 흐름

| 데이터 | 만드는 모듈 | 저장 | 쓰는 모듈 |
| --- | --- | --- | --- |
| 시장 데이터(가격·환율·재무·구성종목·뉴스) | M2-01 (수집 배치) | DB `price_daily` `fx_daily` `financials` `index_constituent` `assets` `news` | M2-02, M2-04, Module3~6 |
| 디스크립터(GICS 태그·키워드·요약) | M2-03 | `data/processed/*_descriptor.json` (+ 버전) | M3-01, M3-02, M5-05 |
| 프로필 | M1-01 | `store/data/profile.json` (버전 이력) | M1-02, M7-02 |
| 분석 요청(아이디어·질문답변·이번 조건·기준 리포트) | M1-02, M1-04 | `store/data/requests/<request_id>.json` + `01_request.json` | Module3, M1-03 |
| 의도·후보·분류·선정·근거 | Module3 | `02~06_*.json` | Module4, M5-04, M5-05 |
| 구성 사양·시장모형·뷰·타겟·날짜별 구성 | Module4 | `07~10_*.json` `09a` `10w` `10f` | Module5, M6-01, M6-03 |
| 백테스트·검증 | M5-01~03 | `11_*.json` `12_*.json` `11_daily_panel.parquet` | M5-04 |
| 결과 통합 | M5-04 | `13_results.json` + DB `run_artifact` | M5-05, M1-03, M5-04(비교), M6-01 |
| 리포트 문서 | M5-05 | `14_report.json` + DB `report` (불변) | M7-04, M7-06 |
| 수정안 비교 | M5-04 | `store/data/comparisons/<comparison_id>.json` | M7-06 |
| 실행 상태 | M0-05 | DB `run_step` + `store/data/runs.json`(색인·큐 상태) | M7-03 진행 화면, M0-06 |
| 트래킹 | Module6 | `store/data/paper/<paper_id>/` (`portfolio.json`, `snapshots.jsonl`, `rebalances.jsonl`) | M7-05 |
| LLM 사용량 | M0-03 | `output/llm_usage.jsonl` | M5-04(비용 요약) |

## 1.4 요구사항 추적표

| 요구사항 | 내용 | 모듈 |
| --- | --- | --- |
| R1 | 프로필 관리: 프로필 1개, 입력 검증, 저장·수정, 과거 결과 보존 (FR01) | M1-01, M7-02 |
| R2 | 아이디어 통합: 저장 조건 활용, 부족·충돌 항목 질문, 이번 조건 확인 | M1-02, M3-01, M7-03 |
| R3 | 실제 자료 근거: 자료명·발표일·기준일·관련 사실 (FR04, FR26) | M2-01~04, M3-05, M4-03 |
| R4 | 실행 가능한 전략: 선정·비중·제약·리밸런싱 규칙 설명 (FR08) | M3-04, M4-02, M4-04, M5-05 |
| R5 | 검증 결과만 제공: 비중·조건·수치 일치 검사, 실패 결과 차단 (FR09, FR25) | M0-02, M5-03, M5-05 |
| R6 | 과거 평가: 수익·위험·비교지수·계산 조건 (FR11, FR12) | M5-01, M5-02, M4-01 |
| R7, R8 | 리포트 본문과 근거·출처 연결 (FR14, FR26) | M5-05, M3-05, M7-04 |
| R9 | 실행 기록: 단계별 상태와 결과 요약 (FR24) | M0-05, M7-03 |
| R10 | 수정 요청: 기준 전략, 변경 확인, 별도 수정안·비교 결과 | M1-04, M5-04, M7-06 |
| R11 | 모의투자: 명시적 활성화, 가상 성과와 추적 상태 | M6-01~04, M7-05 |
| R12 | 진행 상태 표시 | M0-05, M0-06, M7-03 |
| R13 | (기획에서 제외된 항목) | – |

# 2. 공통 제약과 데이터 계약

## 2.1 공통 제약 (모든 모듈)

| ID | 제약 |
| --- | --- |
| C-01 | Python 3.13(백엔드), React(화면). 주요 의존성: pandas, numpy, pyarrow, pydantic v2, bt, scipy, scikit-learn, sqlalchemy + psycopg, openai. 버전 범위는 `pyproject.toml`에 고정 🔶 |
| C-02 | **DB 단일 원천:** 시장 데이터·뉴스는 팀 PostgreSQL에서만 읽는다. 읽기 계정과 쓰기 계정을 분리하고, 분석 단계는 읽기 계정만 쓴다. 로컬 parquet는 성능용 캐시이며 DB와 다를 때 DB가 맞다 |
| C-03 | 단계 사이의 데이터는 `output/<run_id>/NN_*.json` 파일로 주고받고, 쓰기 전에 `schemas.py` 모델로 검증한다. 결과 통합과 리포트는 DB(`run_artifact`·`report`)에, 프로필·요청·트래킹·비교 결과는 **로컬 JSON 저장소** `module_mockup/store/data/`(git 제외, 부록 H)에 저장한다 |
| C-04 | **결정론:** LLM 외에는 난수를 쓰지 않는다. LLM은 프롬프트 해시 캐시로 같은 입력이면 같은 답을 재사용한다. 리포트는 생성 후 불변이며 재분석은 새 run을 만든다 |
| C-05 | **통화:** 기준 통화는 USD. 한국 종목의 KRW 가격은 해당 거래일 환율로 USD 환산한 값으로 계산한다(🔶K16). 입력·표시는 KRW 가능. 환율은 기준일의 `USD/KRW` 종가이며 "1 USD = X KRW"와 기준일을 함께 표시한다. 백테스트 초기자본은 창 시작일 환율로 환산한다 |
| C-06 | **선견 금지:** 기준일 `as_of`의 선정·추정·뷰에는 `as_of` 이전 데이터만 쓴다. 뉴스 뷰는 기준일 직전 14일 헤드라인만 근거로 쓴다. 뉴스 없이 만든 뷰는 `hindsight_risk`로 표시하고 리포트에 적는다 |
| C-07 | **LLM 역할 한정:** LLM은 해석·분류·뷰 가설·서술만 한다. 종목을 직접 고르지 않고, 계산에 쓰이는 숫자를 만들지 않으며, 존재하지 않는 자료·제목·URL을 만들지 않는다. 출력은 JSON으로 받아 스키마 검증·범위 클리핑을 거치고 실패하면 오류를 되먹여 1회 재시도한다. 근거를 요구하는 출력(뷰·종목 근거)은 근거 id를 인용해야 한다 |
| C-08 | **수치 생성 금지:** 리포트·근거 문단의 모든 숫자는 결과 통합 파일의 값이어야 한다. M5-05가 문단의 숫자를 결과값 집합과 대조해 없는 숫자는 경고로 남기고, 경고가 있으면 리포트를 "검증 실패"로 표시한다(R5) |
| C-09 | **자격 증명:** API 키·DB 접속 정보는 저장소 루트 `.env`(git 제외)와 배포 환경 변수에만 둔다. 코드·출력·로그·DB 저장값에 비밀값을 쓰지 않는다 |
| C-10 | **오류·경고:** 복구 불가면 단계가 예외로 중단되고 실행기가 run을 FAILED로 기록하며 리포트를 만들지 않는다. 복구 가능한 문제(종목 제외, 값 클리핑, 뉴스 부족, 데이터 보간 등)는 그 단계의 `warnings`에 기록해 결과 통합·리포트 「전제와 한계」까지 전달한다. 실패를 성공처럼 보이게 하지 않는다 |
| C-11 | **설정·테스트:** 파라미터는 설정 모듈에서만 바꾼다(단계 스크립트에 상수 금지). `pytest tests -q`는 산출물의 불변식을 네트워크·LLM 없이 검사하며 머지 전 통과해야 한다 |
| C-12 | **사용자 언어:** 화면·리포트는 한국어. 금지 표현: 데모·샘플·mock·임시·추후 구현·JSON·스키마 같은 내부 용어, "보장합니다"·"확실히" 같은 단정. 위험은 경고 배너가 아니라 본문 문단으로 설명한다. 투자 권유 표현 금지 |

## 2.2 데이터 계약

**(a) DB 읽기 테이블** (팀 DB `myfinsight`, 읽기 계정. 컬럼명은 DB 정의를 따르고 아래는 모듈이 기대하는 최소 필드)

시장 범위는 **미국(S&P 500, NASDAQ 100)과 한국(KOSPI 200)** 이다. 종목은 `market`(US·KR)과 가격 통화(USD·KRW)를 갖고, 두 시장이 섞인 계산은 모두 USD로 환산해 한다(C-05).

| 테이블 | 키 | 최소 필드 | 갱신 |
| --- | --- | --- | --- |
| `assets` | `asset_id` (`US-<ticker>` · `KR-<종목코드>`) | ticker, name, market(US·KR), currency(USD·KRW), yfinance_symbol | 구성종목 변경 시 |
| `index_constituent` | (index_code ∈ SP500·NDX·KOSPI200, snapshot_date, ticker) | name, sector, industry | 정기 변경일(미국 분기, KOSPI 200 6·12월) + 수시 |
| `price_daily` | (asset_id, date) | open, high, low, close, adj_close, volume (종목 통화: US는 USD, KR은 KRW) | 시장별 매 거래일 마감 후 |
| `fx_daily` | (pair, date) | rate (1 USD당 KRW) | 매일 |
| `financials` | (asset_id, period_end, statement, item) | value, 보고일 | 분기 |
| `news` | `news_id` | asset_id, source, url, title, content, publisher, published_at(UTC), language(en·ko) | 수 시간마다 |

**(b) DB 쓰기 테이블** (쓰기 계정. 팀 DB에 이미 있는 3개만 쓴다. K1 결정: 신규 테이블은 만들지 않는다)

| 테이블 | 키 | 내용 |
| --- | --- | --- |
| `run_artifact` | run_id | request_id, created_at, 결과 통합 JSON, 파라미터 스냅샷, LLM 사용량 |
| `run_step` | (run_id, step) | status, started_at, ended_at, summary, error_code, error_message |
| `report` | report_id (= run_id) | created_at, 리포트 문서 JSON(불변), 전략명, 요청 요약, 분석 기준일 |

**(b′) 로컬 JSON 저장소** (`module_mockup/store/`. 스키마는 `store/schemas/*.schema.json`에 두고 git에 포함, 실제 데이터 `store/data/`는 git 제외. 상세는 부록 H)

| 파일 | 스키마 | 내용 |
| --- | --- | --- |
| `data/profile.json` | `profile.schema.json` | 프로필 1개 + 버전 이력(진단 성향·최종 성향·변경 여부, 부록 A 필드) |
| `data/requests/<request_id>.json` | `analysis_request.schema.json` | 아이디어, mode(`new`·`rerun`·`revision`), 기준 리포트, 질문·답변, 확정된 요청(effective_request), 상태, run_id |
| `data/runs.json` | `run_index.schema.json` | run 색인: request_id, 큐·실행 상태, output 디렉터리, report_id, 시각 |
| `data/paper/<paper_id>/portfolio.json` | `paper_portfolio.schema.json` | 트래킹 객체: 기준 리포트·전략, 시작일, 가상 자본, 적립·리밸런싱 규칙, 시작 비중, 현재 보유, 상태 |
| `data/paper/<paper_id>/snapshots.jsonl` | `paper_snapshot.schema.json` | 날짜당 1줄: 평가액, 비중, 낙폭, 수익률, 비교지수, 상태 |
| `data/paper/<paper_id>/rebalances.jsonl` | `rebalance_record.schema.json` | 리밸런싱당 1줄: 목표·적용 비중, 거래, 수수료, 뷰·근거 요약, fallback |
| `data/comparisons/<comparison_id>.json` | `revision_comparison.schema.json` | 원안·수정안 비교: 조건·종목·비중·규칙 변화, 같은 조건 성과표 |

**(c) 단계 JSON 계약:** 모든 파일에 `request_id`, `stage`, `warnings: list[str]`. 날짜 `YYYY-MM-DD`, 비율은 소수(0.152 = 15.2%), 금액은 USD 실수. 파일 이름과 내용은 부록 B.

**(d) 기준일 용어**

| 용어 | 정의 |
| --- | --- |
| 분석 기준일 (`as_of`) | 요청 시각 기준 DB의 최신 거래일(두 시장이 섞이면 둘 다 마감된 가장 최근 날짜). 선정·"현재 구성"·환율의 기준 |
| 백테스트 창 | `[분석 기준일 − N년, 분석 기준일]`. N은 사용자가 지정(`horizon.backtest_years`), 기본 3년(K2). 시작일에 종목을 다시 선정한다 |
| 리밸런싱일 | 리밸런싱 규칙 `{count, unit}`로 계산. `2w` = 10거래일 × count, `1m`·`1q`·`6m`·`1y` = 해당 기간 첫 거래일. 창의 마지막 날은 제외 |
| 트래킹 시작일 | 사용자가 정한 날짜(기본 오늘). 시작 비중은 기준 리포트의 타겟 |
| 데이터 마감 | DB가 마지막으로 갱신한 거래일. 트래킹 화면에 항상 표시 |

# 3. 모듈별 상세 명세

모듈마다 같은 순서로 적는다: 한 줄 설명 · 상태 · 요구사항 · Input · Process · Output · 성공·평가 기준 · 제약 · 오류·경고.

## Module0 공통

### M0-01 설정·경로·자격 증명

- **한 줄 설명:** 경로·파라미터·모델·자격 증명을 한곳에 모은다.
- **상태:** 🛠
- **Input:** 환경 변수(`MYFINSIGHT_DATA` 캐시 위치, `MYFINSIGHT_LLM` stub|api, `MYFINSIGHT_RUN_ID`), `.env`(`OPENAI_API_KEY`, `NEWS_DB_*` 읽기 계정, 쓰기 계정 🔶)
- **Process:** `common.py`(경로, JSONC 로더, `.env` 로더), `portfolio_config.py`(추정 창 756거래일, 종목당 최소 252수익률, Ledoit-Wolf 수축, τ, 위험회피 δ 모드와 성향 배수, 최소 비중 1%, 뷰 수익률 범위, 템플릿 4개, 뉴스 창 14일·종목당 10건·최소 종목 수), `backtest_config.py`(수수료 bp, 소수 주식, 무위험수익률, 거래일 252, 드리프트 허용치, 체크포인트 빈도, 낙폭 이벤트 수준, 변동성 밴드), `llm_config.py`(모델, 토큰 한도, 재시도, 단가)
- **Output:** 모듈 상수. 전체 스냅샷이 결과 통합의 `parameters`에 실려 리포트 「분석 조건」에 나온다
- **성공·평가 기준:** 설정값 변경이 리포트 「분석 조건」에 반영된다 / `.env`가 없으면 stub 모드만 동작하고 api·DB 단계는 명확한 메시지로 실패
- **제약:** C-09, C-11

### M0-02 데이터 계약·스키마

- **한 줄 설명:** 단계 JSON과 DB 저장 객체의 형식을 Pydantic으로 못 박는다.
- **상태:** 🔧 — 현재 단계 JSON 모델만 있음 → DB 저장 객체 모델(UserProfile 서비스판, AnalysisRequest, Question, PaperPortfolio, PaperSnapshot, RebalanceRecord, RevisionComparison)과 테이블 매핑 추가
- **요구사항:** R5
- **Process:** 핵심 모델과 검증 규칙
    - `UserRequest`: `profile`·`capital`·`horizon`·`risk`·`constraints`·`strategy_preference`·`natural_language`(부록 A). HARD 규칙: `num_holdings.min ≤ target ≤ max`, `max_weight_per_stock × num_holdings.min ≥ 1`, `max_weight_per_sector ≥ max_weight_per_stock`, `must_include ≤ num_holdings.max`, 포함·제외 종목 충돌 금지, 리밸런싱 `{count ≥ 0, unit ∈ 2w|1m|1q|6m|1y}`
    - `IntentSpec`: 테마의 GICS 코드는 2/4/6/8자리, 템플릿-지표 고정표(`low_per`→`pe_ttm`↑, `quality`→`roe_ttm`↓, `momentum`→`return_12m_1m`↓, `low_volatility`→`vol_60d`↑, `high_dividend`→`dividend_yield_ttm`↓), 신규 `questions`
    - `Portfolio`: 비중 + 현금 = 1 ± 1e-4, 음수 금지. `View`: 상대 뷰는 short 필수, 절대 뷰는 short 금지, 양쪽 같은 종목 금지, `evidence_ids`
    - `BacktestResults`: 모든 시계열 길이 = `series_dates`. `Check`: level hard|soft|info, status pass|warn|fail|info
    - `ResultsBundle`: 백테스트 포트폴리오 id = 정적 타겟 ∪ walk-forward, 원화 환산표가 전부를 덮음. `ReportDoc`: 블록 타입 집합, KPI·시리즈 id 참조, nav = sections
    - 신규(로컬 저장소 객체, 부록 H의 JSON Schema와 1:1): `ProfileStore`, `AnalysisRequest`, `Question{field, kind: missing|conflict|ambiguous, question_ko, options, priority}`, `RunIndex`, `PaperPortfolio`, `PaperSnapshot`, `RebalanceRecord`, `RevisionComparison`
- **성공·평가 기준:** 모든 산출물이 해당 모델로 다시 읽힌다 / 위반 입력은 가장 이른 단계에서 거부
- **제약:** 스키마 변경 시 그 필드를 읽는 단계·프롬프트·화면을 함께 고친다

### M0-03 LLM 호출기 🤖

- **한 줄 설명:** 모든 LLM 호출이 지나가는 문. 프롬프트 렌더링, stub/api 전환, 캐시, 재시도, 사용량 기록.
- **상태:** 🛠
- **Input:** `load_prompts(stage_dir, **vars)`(`prompts/<stage>/system_prompt.md`·`user_prompt.md`의 `{{변수}}` 치환), `call_llm(stage, system, user, batch=None, validator=None)`
- **Process**
    1. 렌더링된 프롬프트를 `output/<run_id>/prompts/`에 저장
    2. stub 모드: `stubs/<stage>.example.json` 반환(개발·테스트용). api 모드: 설정 모델(추론 모델이면 temperature 생략, JSON 객체 응답), 단계별 출력 토큰 한도, 타임아웃, 연결·속도제한 오류 재시도
    3. 캐시: `sha256(model + stage + system + user)` → `output/llm_cache/`. 컨텍스트 패키지가 바뀌면 키도 바뀐다
    4. 검증·재시도: JSON 파싱 실패 또는 `validator` 예외 → 오류 문장을 덧붙여 1회 재호출, 다시 실패하면 단계 실패
    5. 사용량: 호출마다 `llm_usage.jsonl` 한 줄(run_id, stage, 토큰·캐시 토큰·추론 토큰, 비용, 시간), 원문은 `llm_raw/`
- **Output:** 파싱된 JSON dict
- **성공·평가 기준:** stub 모드에서 API 키 없이 전 파이프라인이 돈다 / 같은 run을 두 번 돌리면 두 번째는 전부 캐시 / 요청당 비용은 사용량 로그로 집계만 한다(K10: 상한 없음)
- **제약:** 모델명·단가는 `llm_config.py`에서만. 분석은 M0-05 작업 큐가 하나씩 실행하므로 동시 호출 제한은 두지 않는다

### M0-04 DB·로컬 저장 접근 계층

- **한 줄 설명:** DB 조회·저장 함수와 로컬 JSON 저장소 함수를 한곳에 두어 다른 모듈이 SQL·파일 경로를 모르게 한다.
- **상태:** 🔧 — 현재 `news_db.py`(읽기 전용 뉴스) → `db.py`로 확장: 읽기 엔진(reader)과 쓰기 엔진(writer) 분리, 시장 데이터 조회 함수, DB 저장 함수 + 신규 `store.py`: 로컬 JSON 저장소(`store/data/`) 읽기·쓰기와 스키마 검증
- **Input:** `.env`의 접속 정보, 쿼리 파라미터(종목·기간·기준일)
- **Process**
    - 읽기: `prices_panel(tickers, start, end)`, `fx_on_or_before(pair, date)`, `financials_asof(tickers, as_of)`, `constituents_latest(index)`, `news_window(tickers, start, end, languages, per_ticker)`. 결과는 pandas DataFrame, 종목 표기는 yfinance식 티커로 통일(`asset_id` ↔ ticker 변환)
    - DB 쓰기: `save_run(run_artifact)`, `save_step`, `save_report`. 트랜잭션 단위는 호출 1회
    - 로컬 저장소(`store.py`): `load_profile`/`save_profile`, `save_request`/`load_request`, `update_run_index`, `save_paper`, `append_snapshot`, `append_rebalance`, `save_comparison`. 쓰기 전에 `store/schemas/*.schema.json`으로 검증하고, 임시 파일에 쓴 뒤 이름을 바꾸는 원자적 쓰기. JSONL 파일은 줄 추가만(수정 금지). 쓰기 주체는 작업 큐 워커와 화면 요청 처리기뿐
    - 캐시: 종목×기간 parquet를 `MYFINSIGHT_DATA` 아래에 두고 DB 최신 날짜가 바뀌면 무효화
- **Output:** DataFrame 또는 저장된 키
- **성공·평가 기준:** 분석 단계에서 쓰기 엔진을 import하지 않는다(코드 리뷰) / 연결 실패 시 즉시 명확한 오류 / 비밀값이 로그에 없음 / 로컬 저장소의 모든 파일이 스키마를 통과하고, 중단된 쓰기가 깨진 파일을 남기지 않는다
- **제약:** C-02, C-09. DB 방언 의존 SQL 최소화

### M0-05 실행기·실행 기록

- **한 줄 설명:** 요청 하나를 run으로 만들어 단계를 순서대로 돌리고, 상태를 기록·제공하며, 실패하면 리포트를 만들지 않는다.
- **상태:** 🔧 — 현재 `run_pipeline.py`(CLI, subprocess 순차 실행, 콘솔 로그) → 서비스 오케스트레이터: 단계 함수 직접 호출, `run_step` 기록, 취소 플래그, 진행 상태 조회, 재접속 복구
- **요구사항:** R9, R12
- **Input:** 확정된 요청(`analysis_request`), 실행 옵션(LLM 모드, 뉴스 사용 여부)
- **Process**
    1. `run_id` 발급, `output/<run_id>/` 생성, `run_step` STARTED
    2. 단계 호출 순서: Module3(02→03→04→05→06) → Module4(07→08/09/10, 09a, 10w, 10f) → Module5(11→12→13→14). 각 단계는 `(run_dir, 설정) -> 산출물 경로`를 반환하고 예외를 그대로 던진다
    3. 상태: QUEUED·STARTED·SUCCESS·PARTIAL(경고 있음)·FAILED(+오류 코드·메시지)·CANCELLED. 화면에는 5묶음으로 보여 준다: 조건·자료 확인 → 후보·규칙 구성 → 전략 검증 → 백테스트 → 리포트 구성·정합성 검사
    4. 취소: 단계 경계마다 취소 플래그를 확인하고 중단. 앱을 닫아도 서버 run은 계속되며, 재접속 시 마지막 상태를 보여 준다(자동 재개는 하지 않음)
    5. 완료: 결과 통합·리포트를 DB에 저장한 뒤에만 SUCCESS
    6. 실행 방식(K11): **작업 큐(FIFO, 단일 워커)**. 확정된 요청은 `store/data/runs.json`에 QUEUED로 들어가고, 워커가 하나씩 꺼내 CLI 파이프라인(`run_pipeline.py`)을 순차 실행한다. 동시에 두 run이 돌지 않으므로 LLM·DB 부하가 예측 가능하다. 대기 순번은 진행 화면에 표시
- **Output:** run 상태 객체(단계별 상태·요약·소요 시간), 산출물 경로
- **성공·평가 기준:** 실패 run에 리포트가 없다 / 각 단계의 상태가 실제 실행과 일치 / 취소 후 산출물이 부분 상태로 남지 않는다(run 디렉터리 표시)
- **제약:** 비즈니스 로직 금지(순서·상태·오류 정책만)

### M0-06 서비스 API

- **한 줄 설명:** 화면과 백엔드 사이의 요청·응답 계약.
- **상태:** 📄
- **요구사항:** R12 (전 화면의 데이터 공급)
- **Process:** 책임 목록(`Front/docs/04 §8` 기준). 실제 URL·형식은 구현 시 확정 🔶
    
    
    | 책임 | 요청 | 응답 |
    | --- | --- | --- |
    | 프로필 조회·저장 | 프로필 필드 | 검증 결과·저장 버전 |
    | 조건 준비·질문 | 아이디어, 이번 조건 변경분, (기준 리포트 id) | 다음 질문 1개 또는 조건 확인 데이터 |
    | 실행·취소·진행 상태 | request_id / run_id | run 상태 객체 |
    | 리포트 목록·조회 | (report_id) | 목록 행 / 리포트 문서 JSON |
    | 모의투자 활성화·조회·갱신 | report_id·시작 조건 / paper_id | 트래킹 객체, 스냅샷, 재조정 기록 |
    | 수정안 비교 | base_report_id, 수정 요청 | 변경 조건 초안 → 비교 결과 |
- **성공·평가 기준:** 모든 응답에 오류 코드·메시지가 있고 실패를 성공으로 위장하지 않는다 / 화면 용어는 내부 용어(JSON·스키마)를 노출하지 않는다
- **제약:** 단일 사용자이므로 인증은 없지만 배포 시 접근 제한(네트워크·토큰) 🔶

## Module1 사용자 정보·이전 실행 데이터·컨텍스트 관리

### M1-01 프로필 관리

- **한 줄 설명:** 사용자 프로필 하나를 저장·수정하고, 분석마다 그 시점의 버전을 묶는다.
- **상태:** 📄
- **요구사항:** R1
- **Input:** 화면 입력(부록 A의 `profile`·`capital`·`horizon`·`risk`·`constraints`·`strategy_preference`), 간이 진단 답변
- **Process**
    1. 필수 항목: 투자 가능 금액, 투자기간, 투자성향, 손실 감내 수준. 나머지는 기본값
    2. 투자성향은 간이 진단 결과(`risk_type_computed`)와 사용자가 고른 최종 값(`risk_tolerance`)을 따로 저장하고, 다르면 확인을 받아 `overridden` 표시
    3. 저장 전 M0-02 HARD 규칙 검증(상한 × 최소 종목 수 ≥ 1 등). 위반은 항목별로 모아 한 번에 보여 준다
    4. 저장은 새 버전(version +1). 과거 리포트는 그때의 버전을 참조하므로 바뀌지 않는다
- **Output:** `store/data/profile.json`(버전 이력 포함, 스키마 `profile.schema.json`)
- **성공·평가 기준:** 프로필 수정 후 과거 리포트의 조건 표시가 그대로다 / 규칙 위반은 저장되지 않고 사유가 보인다
- **제약:** 프로필은 1개. 로그인·계정 없음

### M1-02 요청 조립·검증·보충 질문 🤖

- **한 줄 설명:** 프로필과 자연어 아이디어로 이번 분석 요청을 만들고, HARD 검증과 보충 질문을 거쳐 조건을 확정한다.
- **상태:** 🔧 — 현재 `stage1_normalize.py`가 JSONC 파일을 읽어 검증·파생값 계산 → 서비스에서는 프로필(최신 버전) + 아이디어 + 이번 조건 변경분을 합쳐 같은 검증·파생값 계산을 하고, M3-01의 `questions`로 보충 질문 루프를 돈다
- **요구사항:** R2
- **Input:** `user_profile`(최신 또는 지정 버전), 아이디어 원문, 이번 분석에서 바꾼 조건, mode(`new`·`rerun`·`revision`), (기준 리포트 id), M1-03 컨텍스트 패키지
- **Process**
    1. 요청 객체 조립 → `UserRequest` HARD 검증. 위반은 질문이 아니라 즉시 수정 요구
    2. 파생값: 분석 기준일(DB 최신 거래일), 환율(`fx_on_or_before`), USD 환산액, 리밸런싱 규칙(`2w`는 10거래일 × count, 그 외 달력), 데이터 범위
    3. M3-01 의도 해석 1차 호출(컨텍스트 포함) → `questions` 중 우선순위 1개를 화면에 → 답변을 요청에 반영 → 재검증·재해석. 한 번에 한 항목, 최대 5회. 5회 후에도 미확정이면 분석을 중단하고 사유를 보여 준다
    4. 조건 확인 데이터: 기본 조건(프로필), 이번 분석 값, 변경 항목, 지원되는 제약. 사용자가 「분석 시작」을 누르면 `store/data/requests/<request_id>.json` 저장(상태 `confirmed`) + `01_request.json` 기록 → M0-05 큐에 등록
- **Output:** `store/data/requests/<request_id>.json`(`analysis_request.schema.json`), `01_request.json`(`NormalizedRequest`)
- **성공·평가 기준:** 질문은 부족·충돌·모호 항목에만 나오고 5회를 넘지 않는다 / 확정 전에는 어떤 분석 단계도 실행되지 않는다 / 같은 프로필·아이디어·답변이면 같은 요청
- **제약:** 입력 파일을 수정하지 않는다. [SOFT] 항목 해석은 M3-01에 맡긴다
- **오류·경고:** HARD 위반 → 화면 수정 요구. 환율·데이터 범위 조회 실패 → 중단

### M1-03 실행 이력·컨텍스트 저장소

- **한 줄 설명:** 요청·결과·리포트·트래킹을 연결해 저장하고, 재분석과 LLM 컨텍스트 패키지를 제공한다.
- **상태:** 📄
- **요구사항:** R1, R2, R7
- **Input:** 로컬 요청 파일(`store/data/requests/`), run 색인(`store/data/runs.json`), DB `run_artifact`(결과 통합)·`report`, 트래킹 파일(`store/data/paper/`)
- **Process**
    1. 저장: run 완료 시 요청 ↔ run ↔ 리포트 ↔ (트래킹) 연결. 리포트는 불변
    2. 목록 조회: 전략명, 원래 요청 요약, 분석 기준일, 작성일, 상태(검증 통과·주의·실패), 트래킹 여부
    3. 같은 조건 재분석(`rerun`): 기준 리포트의 요청을 복제하되 분석 기준일을 오늘로 바꾸고 원본은 보존. 화면에 "최신 자료로 다시 분석"임을 기준일과 함께 표시
    4. 컨텍스트 패키지(LLM 입력용): 최근 요청 k개의 요약(아이디어·테마·템플릿·결과 상태), 질문·답변 목록, 기준 리포트의 종합 판단·전략 사양·검증 결과 요약, 사용자가 이전에 거부·수정한 항목. 토큰 상한 안에서 오래된 것부터 요약·생략. M3-01과 M1-04 프롬프트의 `{{context}}`에 들어간다(C-07의 "숫자 생성 금지"는 그대로 적용)
- **Output:** 목록 행, 재분석 요청, 컨텍스트 패키지(dict)
- **성공·평가 기준:** 프로필 수정·재분석 후에도 과거 리포트가 그대로다 / 컨텍스트 패키지에 비밀값·원문 전체가 들어가지 않는다 / 패키지 유무가 캐시 키에 반영된다
- **제약:** 컨텍스트는 해석을 돕는 참고일 뿐 조건을 바꾸지 않는다. 조건 변경은 항상 사용자 확인을 거친다

### M1-04 수정 요청 처리 🤖

- **한 줄 설명:** 기준 리포트에 대한 자연어 수정 요청을 변경 조건으로 바꾸고, 사용자 확인 후 수정안 분석을 만든다.
- **상태:** 📄
- **요구사항:** R10
- **Input:** 기준 리포트 id, 수정 요청 원문, M1-03 컨텍스트 패키지, 프롬프트 `prompts/02_intent` 변형(수정 모드)
- **Process**
    1. LLM이 변경 조건 초안을 만든다: 어떤 필드를 어떤 값으로, 사유, 바꾸지 않는 것. 조건 필드 밖의 요구(예: 특정 종목 강제)는 `must_include`·`exclude` 같은 지원 제약으로만 옮기고, 지원하지 않으면 "반영 불가"로 표시
    2. HARD 검증 → 「변경 조건 확인」 화면(원안 조건 vs 제안 변경) → 필요하면 보충 질문(M1-02 루프) → 「수정안 분석하기」
    3. 수정안 요청 생성: mode `revision`, `base_report_id`, 백테스트 창·자본·비교지수·리밸런싱 규칙은 원안과 **동일하게 강제**(비교 공정성). 그 외 조건만 변경
    4. M0-05 실행 → M5-04가 원안과 수정안의 비교 결과를 만든다
- **Output:** 변경 조건 초안, 수정안 요청 파일(`store/data/requests/`, mode `revision`)
- **성공·평가 기준:** 수정안의 백테스트 조건이 원안과 같다(검사) / 변경 항목이 모두 사용자 확인을 거쳤다 / 원안 리포트는 그대로
- **제약:** 수정안은 별도 리포트·run이며 원안을 덮어쓰지 않는다

## Module2 금융 데이터 관리

### M2-01 수집 배치 (팀 DB 담당)

- **한 줄 설명:** 가격·환율·재무·구성종목·뉴스를 팀 DB에 채우는 수집기. **이 프로젝트의 분석 코드는 수집하지 않고 DB만 읽는다**(K3). 여기에는 분석 쪽이 DB에 기대하는 계약만 적는다.
- **상태:** 📄 외부 — 팀 DB 수집기가 담당. mock-up의 `fetch_data.py`·`fetch_fundamentals.py`는 개발용 로컬 캐시 도구로만 남긴다
- **요구사항:** R3
- **기대 계약(DB가 보장해야 하는 것)**
    1. 대상 시장: 미국(S&P 500·NASDAQ 100)과 한국(KOSPI 200). 주기: 가격은 시장별 거래일 마감 후, 환율 매일, 재무 분기(보고일 기준), 구성종목은 정기 변경일(미국 3·6·9·12월 셋째 금요일, KOSPI 200 6·12월) + 수시 변경, 뉴스는 수 시간마다(미국 영어, 한국 한국어 소스)
    2. 키 중복은 값이 다를 때만 갱신(upsert). 수집 결과는 `fetch_log`(소스·대상·기간·상태·시각·오류)에 누적되어 분석 쪽이 "데이터 마감"과 결측 사유를 읽을 수 있다
    3. 티커 표기는 미국은 yfinance식(`BRK-B`), 한국은 6자리 종목코드. `assets.asset_id`(`US-`·`KR-` 접두)로 매핑
    4. 원본 값을 가공해 저장하지 않는다(배당 반영 `adj_close`는 소스 제공값). 날짜 단위로 커밋해 읽기 중 일관성이 깨지지 않는다
- **Output:** DB 읽기 테이블 6개, `fetch_log`
- **성공·평가 기준(분석 쪽 검사):** 거래일 다음 날 아침 가격·환율이 DB에 있다 / 구성종목 행 수가 지수 범위 안(S&P 500 495~510, NASDAQ-100 98~105, KOSPI 200 195~205) / `fetch_log`의 최신 성공 날짜 = 화면의 "데이터 마감"
- **제약:** 분석 코드에서 외부 소스(yfinance 등)를 직접 호출하지 않는다. DB에 없는 데이터는 "없음"으로 처리하고 보충 수집을 시도하지 않는다

### M2-02 시장 데이터 조회·품질 판정

- **한 줄 설명:** 기준일을 넘지 않는 가격·환율·재무·구성종목을 DB에서 읽고, 결측·부족 종목을 걸러낸다.
- **상태:** 🔧 — 현재 yfinance parquet 읽기 함수가 여러 스크립트에 흩어져 있음(`metrics.py`, `backtest_engine.py`, `stage1_normalize.py`, `stage3_retrieve.py`) → M0-04의 DB 조회 함수로 통일(K3)하고 품질 판정을 추가
- **요구사항:** R3, R6
- **Input:** 종목, 기간 또는 기준일, 필수 종목(비교지수·`must_include`), 설정(커버리지 95%, 최대 보간 1거래일)
- **Process**
    1. 가격 패널: `adj_close`(수익률·백테스트)와 `close`(시가총액·주가 지표). 한국 종목은 거래일 환율로 USD 환산. 미국·한국 종목이 섞이면 두 시장 거래일의 **합집합**을 달력으로 쓰고, 한쪽 시장의 휴장일은 직전 종가를 유지(`HOLIDAY_HOLD`, 결측 보간과 구분해 기록하며 품질 판정에서 제외) 🔶K16
    2. 품질: 종목별 커버리지 = 유효 거래일 / 기대 거래일. 연속 1거래일 결측만 직전값으로 채우고 기록(`FILLED`). 커버리지 < 95% 또는 2일 이상 연속 결측은 제외(`EXCLUDED`, 사유)
    3. 필수 종목이 제외되면 중단. 사용 가능 종목이 0이면 중단
    4. 기준일 조회: 기준일 전 400달력일 이상 이력(선정), 추정 창 안 252수익률 이상(시장모형) 같은 단계별 요구는 호출자가 넘기고 여기서 판정
- **Output:** DataFrame(결측 없음) + 품질 보고(종목별 상태·사유)
- **성공·평가 기준:** 출력에 NaN 없음 / 경계값(0.95 통과, 0.9499 제외) / 제외 사유가 결과 통합 `warnings`와 리포트 「전제와 한계」에 나온다
- **제약:** 값 생성 금지(C-08). 기준일 이후 데이터를 돌려주지 않는다(C-06)

### M2-03 유니버스 디스크립터 (🤖 선택)

- **한 줄 설명:** 종목마다 GICS 4단계 태그·키워드·한 줄 소개를 붙인 사전을 만들어, LLM에 종목 표를 주지 않고도 테마→종목 검색이 되게 한다.
- **상태:** 🔧 — 현재 미국 종목만(S&P 500 ∪ NASDAQ 100) → 소스를 DB `index_constituent`·`assets`로 바꾸고 KOSPI 200 종목(KRX 업종 → GICS 매핑)을 추가, 버전·생성일 기록
- **요구사항:** R3, R4
- **Input:** 구성종목(DB), GICS 분류표(`data/reference/gics_taxonomy.json`: 세부산업 × 섹터·산업그룹·산업·세부산업 코드), 사업 설명(재무 스냅샷), 선택 LLM #0 결과
- **Process**
    1. 섹터·산업명을 GICS 코드(2/4/6/8자리)로 정규화. 한국 종목은 KRX 업종 분류를 GICS로 옮기는 매핑표가 필요하다 🔶K17
    2. 한 줄 소개 우선순위: LLM #0 한국어 요약 > 소스 사업 설명 첫 문장 > 규칙("회사명 — 세부산업"). 출처를 종목별로 기록
    3. 헬퍼: `filter_by_gics(codes)`(코드 접두 일치), `search_keywords(words)`(단어 경계 일치), `sector_name_to_code`, `parents_of`
    4. 갱신·버전(K4 결정): 구성종목 스냅샷(`index_constituent.snapshot_date`)이 바뀔 때마다 재생성하고 **스냅샷 날짜별 버전을 보관**한다. 과거 기준일의 선정(M4-01 시작일 재선정)에는 기준일 이전 가장 최근 스냅샷 버전을 쓴다. 보관된 가장 오래된 스냅샷보다 앞선 기준일은 그 가장 오래된 버전을 쓰고, 리포트 「전제와 한계」에 "당시 구성종목 미확보(생존 편향 가능)"를 적는다
- **Output:** `data/processed/<universe>_descriptor.json`(+ 버전·생성일, 종목별 `market`·통화 필드)
- **성공·평가 기준:** 모든 종목에 4단계 코드·이름 / 요약 출처가 리포트 선정표에 표시 / 버전이 결과 통합에 기록
- **제약:** 스냅샷 이력이 없는 기간에는 생존 편향이 남으며 리포트에 명시한다. 버전 교체는 분석 중간에 일어나지 않는다(run 시작 시 고정)

### M2-04 뉴스 근거 조회

- **한 줄 설명:** 종목·기간으로 헤드라인을 읽어 뷰와 근거 서술이 인용할 수 있는 근거 레코드로 만든다.
- **상태:** 🔧 — 현재 `news_db.fetch_news`가 미국 종목·영어만 조회 → 시장별 언어(US en, KR ko) 조회와 출처 패널 필드 변환 추가
- **요구사항:** R3, R8
- **Input:** 종목, 창 `[start, end)`, 언어(미국 종목 en, 한국 종목 ko 기본), 종목당 최대 건수
- **Process:** `news` ⋈ `assets`로 조회 → 제목 소문자 중복 제거 → 최신순 종목당 N건 → 레코드 `{evidence_id: "ev<news_id>", ticker, published_at, source, publisher, title, excerpt, url, origin: "db"}`. 출처 패널용 필드: 문서명(title), 발행기관(publisher), 발표일, 발췌(excerpt), 원문 링크(url)
- **Output:** 근거 레코드 목록
- **성공·평가 기준:** 모든 레코드의 `published_at`이 창 안 / 존재하지 않는 제목·URL이 없다(DB 값 그대로) / 비밀값이 산출물에 없다
- **제약:** 읽기 전용. 본문이 짧은 소스는 헤드라인 수준 근거임을 리포트에 표시. 한국어 뉴스를 포함하며(K5), DB에 소스·언어가 추가되면 설정만 바꿔 따른다

## Module3 종목 선정·전략 생성

> 원칙: LLM은 **해석(M3-01)·분류(M3-03)·서술(M3-05)** 만 한다. 후보를 찾는 것(M3-02)과 순위를 매겨 고르는 것(M3-04)은 코드가 한다. 같은 입력이면 같은 종목이 나오고, 왜 뽑혔는지 지표값으로 설명할 수 있다.
> 

### M3-01 의도 해석기 🤖

- **한 줄 설명:** 자연어 아이디어와 [SOFT] 항목을 "어떤 산업(GICS 코드·키워드)을, 어떤 템플릿으로, 어떤 위험 기준으로" 고를지 기계가 읽을 수 있는 `IntentSpec`으로 바꾸고, 부족·충돌·모호 항목을 질문으로 뽑는다.
- **상태:** 🔧 — 현재 `stage2_intent.py` → 입력에 컨텍스트 패키지 `{{context}}`, 출력에 `questions` 추가, 수정 모드 프롬프트 변형
- **요구사항:** R2, R4
- **Input:** `01_request.json`, 아이디어 원문, GICS 분류 트리(섹터→산업그룹→산업→세부산업, 코드·이름·종목 수. 종목 표는 주지 않는다), 컨텍스트 패키지, 프롬프트 `prompts/02_intent/`
- **Process**
    1. LLM 출력: `interpretation`(요약, 테마 ≥ 1: id·설명·`gics_codes`·`keywords`·`example_tickers`, 스타일 힌트, 상충 항목과 해결), `exclude_theme_rules`, `screen`(템플릿·지표·방향·기준일·테마 신뢰도 하한·`select_top_n`), `risk_params`(실효 최대낙폭 — `loss_reaction`이 `sell`이면 낮춤, 변동성 선호), `news_tilt`(뷰 신뢰도 상한, 종목당 최대 조정폭), `validation_criteria`, `report_settings`, 신규 `questions`
    2. 검증: 코드 자릿수, 템플릿-지표 일치, 테마 ≥ 1. 유니버스에 없는 예시 티커는 경고 후 제거
    3. `questions`가 비어 있으면 조건 확인으로, 있으면 M1-02가 1개씩 묻는다
- **Output:** `02_intent.json`
- **성공·평가 기준:** 테마가 GICS 코드·키워드로 표현된다 / 사용자가 고른 템플릿·HARD 값은 바꾸지 않는다 / 스키마 위반은 1회 재시도로 복구
- **제약:** 티커는 예시로만, 검색은 코드·키워드로(C-07). 컨텍스트는 해석 참고용이며 조건을 바꾸면 `questions`로 되묻는다

### M3-02 후보 검색기

- **한 줄 설명:** `IntentSpec`의 코드·키워드로 디스크립터를 뒤져 후보를 만들고 HARD 필터를 건다.
- **상태:** 🛠 — 가격·시가총액·거래대금 조회만 M2-02로 교체
- **요구사항:** R4
- **Input:** `02_intent.json`, `01_request.json`, 디스크립터, 기준일(`as_of`, 재선정 시 백테스트 시작일)
- **Process**
    1. 테마별 매칭 합집합: `gics_match`(8자리 코드가 선택 코드로 시작), `keyword_match`(이름·키워드·요약 단어 단위 일치, 키워드로만 걸린 종목은 서로 다른 키워드 2개 이상), `example_match`. 근거를 `matched_by`·`matched_keywords`에 기록
    2. HARD 필터: `exclude_tickers`·`exclude_sectors`·`exclude_theme_rules`·`asset_types`·`min_market_cap_usd`(발행주식수 × 기준일 종가, 한국 종목은 USD 환산)·`min_avg_daily_volume_usd`(기준일 전 60거래일)·가격 이력 400달력일 이상. `must_include_tickers`는 강제 포함
    3. 후보 < 목표 종목 수면 코드를 한 단계 위로 넓혀 1회 재검색. 상한(120) 초과면 매칭 규칙 수 → 거래대금 순으로 자른다
- **Output:** `03_candidates.json`(후보, 제외 사유, 깔때기 통계)
- **성공·평가 기준:** 약한 키워드 매칭만으로 들어온 후보 없음 / 같은 입력 → 같은 후보 / 제외 사유가 리포트 깔때기에 표시
- **제약:** 순수 코드. 과거 기준일에는 기준일 이전 최신 디스크립터 버전을 쓴다(M2-03, K4)

### M3-03 후보 분류기 🤖

- **한 줄 설명:** 후보 하나하나가 테마에 해당하는지, 제외 테마에 걸리는지 LLM이 40개씩 판정한다.
- **상태:** 🛠
- **요구사항:** R4
- **Input:** `03_candidates.json`, `02_intent.json`, 프롬프트 `prompts/04_classify/`
- **Process:** 배치마다 후보 표(티커·이름·GICS·요약·매칭 키워드)와 테마 설명 → `results[{ticker, in_theme, themes, confidence, reason_ko, excluded_theme}]` → 통과 = `in_theme` ∧ `confidence ≥ 하한` ∧ 제외 테마 없음. 응답에 없는 티커는 경고 후 미통과
- **Output:** `04_tagging.json`(`tagged`, `excluded_by_theme`, `passed_tickers`, `batches`)
- **성공·평가 기준:** 모든 후보에 판정 / 사유가 리포트 선정표에 그대로 노출돼도 투자 권유 표현이 없다
- **제약:** 배치 순서와 무관한 판정을 프롬프트에 명시

### M3-04 정량 스크린·선정기

- **한 줄 설명:** 테마를 통과한 종목에 템플릿 지표로 순위를 매기고 종목 수·섹터 상한을 지키며 최종 종목을 고른 뒤, 전략 사양을 확정한다.
- **상태:** 🛠 — 지표 계산의 데이터 조회만 M2-02로 교체
- **요구사항:** R4
- **Input:** `04_tagging.json`, `02_intent.json`, `01_request.json`, 기준일
- **Process**
    1. 지표(모두 기준일 이전 데이터): `return_12m_1m` = P(t−21거래일)/P(t−252거래일) − 1, `vol_60d`(60거래일 일수익률 표준편차 연환산), `pe_ttm` = 주가 / 최근 4분기 EPS 합(EPS ≤ 0이면 결측), `roe_ttm`, `dividend_yield_ttm`
    2. 결측 종목 제외(`must_include`는 유지 + 경고) → 지표·방향으로 정렬
    3. 섹터 상한을 종목 수 선호로 변환: 섹터당 선호 수 = ⌊`max_weight_per_sector` × n⌋. 1차 선호 수까지, 2차 미룬 종목으로 채움. 용량 검사 Σ_섹터 min(k × 종목상한, 섹터상한) < 1이면 `infeasibility`(사유·선택지) 기록
    4. n = `num_holdings.target`(부족하면 max(min, 통과 수), min 미만이면 경고)
    5. 전략 사양(StrategySpec) 확정: 템플릿·지표·종목 수·기준 비중 규칙·리밸런싱 규칙·제약·비교지수 — 리포트 「구성과 운용」이 이 사양을 그대로 설명한다
- **Output:** `05_selection.json`(선정 표: 티커·이름·섹터·순위·지표값·테마 신뢰도·강제 여부, 거절 사유, 깔때기, `infeasibility`), 전략 사양
- **성공·평가 기준:** 선정 수가 min~max 안, 상한 용량 ≥ 1 / 같은 기준일이면 같은 결과
- **제약:** 제외는 선정 전에 끝나 있다. 섹터 상한이 1.0이면 섹터 선호를 적용하지 않는다
- **오류·경고:** 통과 종목 0개 → 중단

### M3-05 종목별 근거 서술기 🤖

- **한 줄 설명:** 선정된 종목마다 DB 근거(뉴스·재무·선정 지표)를 인용해 "왜 이 종목인가"를 2~4문단으로 쓴다.
- **상태:** 🔧 — 현재 `stage6_explain.py`는 선택 단계이고 근거 인용이 없음 → 필수 단계로, 근거 레코드 입력과 번호 인용 출력 추가
- **요구사항:** R3, R7, R8
- **Input:** `05_selection.json`, `04_tagging.json`, 종목별 근거: 뉴스 헤드라인(M2-04, 기준일 직전 창), 재무 지표 값(M2-02), 선정 지표값·순위, 프롬프트 `prompts/06_explain/`
- **Process**
    1. 종목마다 근거 목록을 번호(`evidence_id`)와 함께 제시. LLM은 "DB 기록 → 확인 가능한 사실 → 분석적 해석 → 투자 의미 → 선정과의 연결" 사슬로 서술하고 문장마다 인용 번호를 붙인다
    2. 자료가 부족한 종목은 주장을 줄이거나 "지표 기준 선정"만 쓴다. LLM 일반 지식이나 가격 변동만으로 사업 경쟁력을 주장하지 않는다
    3. 검증: 인용 id 실존, 숫자 대조(C-08), 금지 표현
- **Output:** `06_selection_explained.json`(종목별 문단·인용 목록)
- **성공·평가 기준:** 모든 문단의 숫자가 결과값과 일치 / 모든 인용 id가 실존 / 자료 없는 종목에 사실 주장이 없다
- **제약:** 정성 자료를 사후에 끼워 넣어 선정 이유로 쓰지 않는다(선정은 M3-04 지표가 결정)

## Module4 포트폴리오 구성

> 원칙: 구성 수학은 `portfolio.py`에 있고 M4-05의 `construct()` 하나로 호출한다. 백테스트 시작일 구성, walk-forward 리밸런싱, 분석 기준일의 "현재 구성", 트래킹 리밸런싱이 모두 같은 함수를 쓰므로 "보여 준 것 = 실행한 것"이 구조로 보장된다.
> 

### M4-01 구성 사양·기준일 확정

- **한 줄 설명:** 분석 기준일·백테스트 창·시작일 재선정·자본 환율·비교지수·뷰 설정을 확정한다.
- **상태:** 🔧 — 현재 `stage7_confirm.py`가 사용자 작성 백테스트 요청 파일을 읽음 → 서비스에서는 기준일과 창을 규칙으로 정하고 사용자 확인(제거·추가 종목)은 조건 확인 단계로 흡수
- **요구사항:** R6
- **Input:** `01/02/04/05` 산출물, 데이터 마감일, 요청의 `horizon.backtest_years`(사용자 지정, 기본 3년, K2), 설정(뷰 세트 수·세트당 뷰 수, walk-forward 사용)
- **Process**
    1. 분석 기준일 = DB 최신 거래일. 백테스트 창 = `[기준일 − N년, 기준일]`, 창이 데이터 범위 밖이면 데이터 시작으로 당기고 경고. 거래일은 비교지수 달력
    2. 시작일 재선정: 날짜에 의존하지 않는 LLM 결과(02 테마, 04 분류)는 재사용하고 결정적 단계만 `as_of = 시작일`로 다시 실행(M3-02 → M3-04). 원래 선정과의 차이를 기록
    3. 초기자본·월 적립을 시작일 환율로 환산(`capital.fx_rate/fx_date/fx_source`). 비교지수 = 요청의 `benchmark`
    4. 리밸런싱일 목록(2.2(d)) 생성
- **Output:** `07_backtest_spec.json`(`period`, `capital`, `rebalance_rule`, `benchmark`, `selection`(출처·종목·표·차이·`infeasibility`))
- **성공·평가 기준:** 창·기준일·환율 출처가 리포트 「분석 조건」에 나온다 / 재선정 차이가 표로 보인다
- **제약:** 재선정은 종목만 바꾸고 테마 해석은 바꾸지 않는다

### M4-02 시장모형·템플릿 비중

- **한 줄 설명:** 기준일 이전 수익률로 공분산·시가총액 비중·내재 기대수익률을 추정하고 규칙 템플릿 4개의 비중을 만든다.
- **상태:** 🛠 — 데이터 조회만 M2-02로 교체
- **요구사항:** R4
- **Input:** 종목, 기준일, 요청(상한·성향·기준 비중 규칙), 디스크립터(섹터). 함수 `build_market_model(tickers, as_of, req, …)`
- **Process**
    1. 추정 창: 기준일 전 756거래일 일수익률. 창 안 252개 미만 종목은 제외 + 경고
    2. 공분산 Σ: Ledoit-Wolf 수축. 연변동성·상관 저장
    3. 시가총액 비중 ≈ 발행주식수 × 기준일 종가(한국 종목은 USD 환산; 근사, 한계 표시)
    4. 위험회피 δ: 시장 내재(비교지수 초과수익 평균 / 분산, 같은 창) × 성향 배수. 내재 기대수익률 π = δ Σ w_기준. τ 설정값
    5. 템플릿: 동일비중, 시가총액비중, 역변동성(1/σ 정규화), 최소분산(제약 포함 최적화). 공통 제약: 종목 상한, 섹터 상한, 최소 비중 1%, 상한 초과분 비례 재배분(반복 상한). 섹터 상한 1.0이면 제약 생략
    6. 사전 통계(기대수익·변동성·Sharpe·유효 종목 수), 섹터 비중. 리포트용 계산 상세: 측정 변동성 → 상한 적용 전 비중 → 상한 적용·재배분 → 최종 비중
- **Output:** `08_market_model.json`, `08_baseline_portfolios.json`(`chosen_baseline` = 요청의 `baseline_weighting`)
- **성공·평가 기준:** 모든 템플릿 비중 합 1, 각 비중 ∈ [1%, 종목상한], 섹터 합 ≤ 섹터상한 / `portfolio.py` 자체 검증 통과
- **제약:** C-06

### M4-03 뉴스 근거 창·뷰 생성기 🤖

- **한 줄 설명:** 구성 날짜 직전 14일 헤드라인을 근거로, Black-Litterman에 넣을 "어느 종목이 얼마나 더/덜 오를 것 같은가"(뷰)를 LLM이 쓰고 코드가 검증한다.
- **상태:** 🔧 — 현재 정적 뷰(`prompts/09_views`, 뉴스 없음)와 뉴스 뷰(`prompts/09_views_news`) 두 경로, 창 계산은 `stage9a_news.py` → 뉴스 뷰를 기본 경로로, 창 계산을 이 모듈 안으로, 웹 검색 보충 제거(DB만)
- **요구사항:** R3, R4
- **Input:** 종목 표(이름·섹터·연변동성·내재수익률·기준 비중), 테마 요약, `news_tilt.max_view_confidence`, 세트 수·세트당 뷰 수, 구성 날짜 d. 함수 `generate_views(tickers, as_of, mm, base_weights, intent, n_sets, per_set, max_conf, evidence)`
- **Process**
    1. 근거 창 `[d − 14일, d)` → M2-04로 조회 → 종목별 근거 id. `enough` = 뉴스 있는 종목 ≥ 최소 종목 수(설정)
    2. `enough`면 LLM 호출. 출력 `sets[{scenario_id, title_ko, narrative_ko, views[…]}]`, 뷰 = `absolute`(종목 X의 연 기대수익 r) | `relative`(long 바스켓이 short 바스켓을 연 r만큼 앞섬), `confidence`, `horizon_months`, `rationale_ko`, `evidence_type: "news"`, `evidence_ids`
    3. 가드레일(코드): 표에 없는 티커·중복 뷰 삭제, confidence를 [하한, 상한]으로 클리핑, 기대수익을 설정 범위로 클리핑, 근거 id 실존 검사(없으면 뷰 삭제), 뉴스 없는 종목의 절대 뷰 삭제, 근거 1건이면 confidence ≤ 0.3, 세트당 뷰 수 절단
    4. `enough`가 아니면 뷰 없이 기준 비중을 쓰고 `fallback` 표시. 플레이스홀더 뷰(뉴스 없이 LLM 기억으로 쓴 뷰)는 쓰지 않는다(K6)
    5. 프롬프트 규칙: 헤드라인은 사건의 존재만 알려 준다, 기사에 없는 숫자 금지, 기준일 이후 정보 금지, 반대 방향 헤드라인이 섞이면 confidence 낮춤, 일정·컨퍼런스 공지처럼 정보가 없는 헤드라인은 LLM이 판단해 뷰에 반영하지 않는다(K7, 코드로 강제하지 않음)
- **Output:** 날짜별 뷰 세트 + 근거 창 요약(`n_articles`, `n_tickers_with_news`, `enough`)
- **성공·평가 기준:** 모든 뷰가 스키마 통과, 근거 id 전부 실존 / 근거 날짜가 모두 창 안 / 뉴스 없는 종목에 절대 뷰 없음
- **제약:** 뷰는 가설이지 예측이 아니다. 신뢰도 상한을 넘지 못한다. 분석 기준일 이후 뉴스는 어떤 호출에도 들어가지 않는다

### M4-04 Black-Litterman 타겟

- **한 줄 설명:** 기준 비중(내재수익률)에 뷰를 섞어 사후 기대수익률을 구하고, 상한과 조정폭 안에서 효용을 최대화한 타겟 비중을 세트마다 만든다.
- **상태:** 🛠
- **요구사항:** R4
- **Input:** 시장모형, 기준 포트폴리오, 뷰 세트, 요청(상한), `news_tilt.max_tilt_per_stock`. 함수 `build_bl(mm, base, view_sets, req, intent, …)`
- **Process**
    1. 뷰 → P(선택 행렬), Q(기대수익). 절대 뷰는 종목 한 줄, 상대 뷰는 long(+)·short(−)
    2. Ω(뷰 불확실성): He-Litterman 신뢰도 방식 Ω_kk = (1/c_k − 1)·p_k(τΣ)p_kᵀ
    3. 사후 기대수익률 μ_BL = [(τΣ)⁻¹ + PᵀΩ⁻¹P]⁻¹ [(τΣ)⁻¹π + PᵀΩ⁻¹Q]
    4. 최적화(SLSQP): max μ_BLᵀw − (δ/2)wᵀΣw, 제약 Σw = 1, 1% ≤ w_i ≤ 종목상한, 섹터 합 ≤ 섹터상한, |w_i − w_기준,i| ≤ `max_tilt_per_stock`
    5. 기록: 시나리오 제목·서술, 적용된 뷰(근거 id), 기준 대비 변화량, 사후 수익률, 활성 제약, 사전 통계
- **Output:** `10_target_portfolios.json`(BL n개 + 템플릿 4개 + 구성 사양 + 파라미터) — 백테스트의 입력
- **성공·평가 기준:** 상한·최소 비중·조정폭 제약 만족 / 뷰가 없으면 기준 비중으로 수렴(자체 검증) / 뷰 방향대로 비중이 움직인다
- **제약:** 롱 온리, 레버리지·현금 없음(현금 혼합은 M5-03 대안으로만). 뷰가 모두 삭제된 세트는 기준 비중 + 경고

### M4-05 날짜별 구성 함수

- **한 줄 설명:** "종목·날짜·근거"를 받아 시장모형 → 뷰 → BL을 한 번에 수행하는 함수. 백테스트·현재 구성·트래킹 리밸런싱이 모두 이 함수를 쓴다.
- **상태:** 🔧 — 현재 `stage10w_walkforward.py`(리밸런싱일마다)와 `stage10f_forward.py`(최신 날짜)가 각자 `build_market_model → generate_views → build_bl`을 조합 → `construct(tickers, as_of, req, intent, settings) -> {templates, bl_portfolios, views, evidence_summary, warnings}` 하나로 묶고 두 스크립트와 M6-03이 호출
- **요구사항:** R4, R11 (FR10 표시=실행)
- **Input:** 종목, 구성 날짜, 요청·의도, 설정(세트 수, fallback 정책)
- **Process**
    - 호출처 ①: 백테스트 시작일 — 정적 타겟(세트 n개) → `10_target_portfolios.json`
    - 호출처 ②: walk-forward — 리밸런싱일마다 세트 1개 → 날짜별 비중 경로 `wf_<template>`·`wf_bl_news`, `views_by_date`, `fallback_dates` → `10w_target_paths.json`
    - 호출처 ③: 분석 기준일 "현재 구성" — 현재 선정 종목, 세트 n개, 배분 금액(USD·KRW) → `10f_forward_portfolios.json`(백테스트 없음, 리포트 「구성과 운용」과 트래킹 시작 비중의 원천)
    - 호출처 ④: 트래킹 리밸런싱일(M6-03) — 세트 1개, 결과를 `rebalance_record`에
- **Output:** 위 산출물. 각 결과에 구성 근거(뷰·근거 id·조정폭·fallback 여부) 포함
- **성공·평가 기준:** 날짜별 비중 합 1·최소 1%·조정폭 ≤ 설정 / 뉴스 부족 날짜는 기준 비중과 같다 / 네 호출처가 같은 함수를 쓴다(코드 리뷰)
- **제약:** 종목 재선정은 하지 않고 비중만 갱신한다(K8). 날짜마다 LLM 1회(캐시)

## Module5 백테스트·검증·결과 종합

### M5-01 백테스트 시뮬레이터

- **한 줄 설명:** 타겟 포트폴리오(정적 + walk-forward)와 비교지수를 같은 기간·같은 적립으로 돌리고 리밸런싱마다 체크포인트를 남긴다.
- **상태:** 🛠 — 가격 패널 조회만 M2-02로 교체
- **요구사항:** R6
- **Input:** `10_target_portfolios.json`, `10w_target_paths.json`, 시장모형, 요청, 가격 패널
- **Process**
    1. 패널: 종목 + 비교지수(사용자 지정 + 보조 지수; 한국 종목이 포함되면 KOSPI 200 지수 또는 추종 ETF를 보조 지수로 추가 🔶)의 `adj_close`. 달력·환산은 M2-02 패널 규칙(시장 합집합, USD)을 따른다
    2. 리밸런싱일(2.2(d)), 적립일(매월 `contribution_day` 이후 첫 거래일). 창의 마지막 날은 리밸런싱 없음
    3. 정적 포트폴리오: 리밸런싱일마다 타겟 비중 복원. 동적(`wf_*`): 날짜별 타겟 적용. 적립금은 들어온 날 타겟 비중으로 즉시 매수. 수수료(bp), 소수 주식, 종가 체결
    4. 비교지수: 같은 시작일·초기자본·적립으로 매수 후 보유. 상대 지표와 R3는 사용자 비교지수 기준
    5. 포트폴리오마다 M5-02 지표 + 체크포인트(리밸런싱일 + 종료일): 비중 before/after/target, 보유·거래·회전율·수수료, 구간 성과, 누적 지표, 뷰 진단. 적립 원장, 낙폭 이벤트, 종목별 기여, 뷰 적중(기대 vs 실현)
    6. 창이 252거래일 미만이면 `annualized_reliable: false`, 헤드라인에 기간 수익률 포함
- **Output:** `11_backtest_results.json`(기간·엔진·`series_dates`·비교지수·포트폴리오별 headline·metrics·money·series·monthly/yearly·checkpoints·ranking), `11_daily_panel.parquet`
- **성공·평가 기준:** 마지막 체크포인트가 closing이고 누적 지표 = 최종 지표, 구간 성과가 연쇄 / 비용 0 동일비중 = 손계산(자체 검증) / 같은 입력 2회 = 같은 결과
- **제약:** 공매도·레버리지·세금·슬리피지 없음. 배당은 `adj_close`로 반영된 것으로 간주. 리포트는 "과거 가상 성과이며 미래를 보장하지 않는다"를 고정 문구로 둔다

### M5-02 성과 지표 계산기

- **한 줄 설명:** 평가액 시계열에서 수익·위험·위험조정·비교지수 대비·구성·거래·안정성 지표를 한 정의로 계산한다(전체 기간과 체크포인트가 같은 함수).
- **상태:** 🛠
- **요구사항:** R6
- **Process(정의):** 일수익률 r_t = V_t/V_{t−1} − 1 · `return`: total_return, cagr, best/worst month · `risk`: ann_vol = std(r)×√252, downside_deviation, max_drawdown(고점·저점·회복일), worst_day, skew, kurtosis · `risk_adjusted`: sharpe = (CAGR − r_f)/ann_vol, sortino, calmar · `vs_benchmark`: excess_cagr, beta, alpha, correlation, tracking_error, information_ratio, up/down capture, months_outperformed_ratio · `vs_baseline`: 기준 템플릿 대비 active return/risk · `composition`: effective_n, HHI, 상위 3종목 기여, 평균 섹터 비중, 최대 드리프트, 상한 위반 · `trading`: 리밸런싱 횟수, 평균 회전율, 수수료 합 · `stability`: 12개월 롤링 · `money`: 납입 합계, 최종 평가액, 이익, XIRR, 최대 손실·최악 12개월 손실 · 월별·연도별 수익률
- **Output:** dict(11단계에 그대로 포함)
- **성공·평가 기준:** 자체 검증(지수 자신과 비교하면 beta 1, tracking error 0) / 변동성 0이면 Sharpe는 None(0이나 무한대로 대체하지 않음)
- **제약:** 반올림 금지(표시 단계에서만). 창이 1년 미만이면 연환산 값은 "참고"

### M5-03 규칙 검증·추천기

- **한 줄 설명:** 백테스트 결과를 사용자 기준 R1~R8로 판정하고, 통과한 것 중 Sharpe 최고를 추천하며, 추천이 없으면 현금 혼합 대안을 만든다.
- **상태:** 🛠
- **요구사항:** R5
- **Input:** `11_backtest_results.json`, 타겟, `02_intent.json`(실효 최대낙폭·검증 기준), `01_request.json`(상한·종목 수), 설정(변동성 밴드, 드리프트 허용치)
- **Process**
    1. 규칙(hard → pass/fail, soft → pass/warn, 창 < 252거래일이면 R2·R7은 info)
    
    | 규칙 | 항목 | 수준 | 판정 |
    | --- | --- | --- | --- |
    | R1 | 최대낙폭 | hard | MDD ≤ 실효 허용 낙폭 |
    | R2 | 목표수익 | soft/info | CAGR ≥ 목표 연수익률 |
    | R3 | 비교지수 대비 | soft | 초과 CAGR > 0 |
    | R4 | 종목 상한(리밸런싱일) | hard | 최대 종목 비중 ≤ 상한 + 0.1%p |
    | R5 | 섹터 상한(리밸런싱일) | hard | 최대 섹터 비중 ≤ 상한 |
    | R6 | 종목 수 | hard | 보유 종목 ≥ 최소 종목 수 |
    | R7 | 변동성 적합 | soft/info | 연변동성 ≤ 성향 밴드 |
    | R8 | 데이터 무결성 | hard | 시계열 길이·리밸런싱 횟수가 기대값 |
    1. 포트폴리오 상태 = fail 하나라도 있으면 fail, warn 있으면 warn, 아니면 pass
    2. 추천: fail 없는 포트폴리오 중 Sharpe 최고(동률이면 MDD 작은 것) + 사유 + 기준 템플릿 대비 차이. 없으면 추천 없음 + 규칙별 실패 수
    3. 현금 혼합 대안: 선택 포트폴리오에 현금(수익 0)을 섞어 MDD가 허용치 안에 드는 최소 현금 비율을 찾고 M5-01로 실제 백테스트
- **Output:** `12_validation.json`(기준, 포트폴리오별 판정, 비교표, 추천, 대안, 요약)
- **성공·평가 기준:** 추천 포트폴리오에 fail이 없다 / 추천이 없으면 리포트가 "추천 없음"과 대안을 그대로 보여 준다(숨기지 않음)
- **제약:** 검사만 하고 값을 고치지 않는다. 손실 감내 수준을 손절 조건으로 표현하지 않는다

### M5-04 결과 통합·비교

- **한 줄 설명:** 모든 산출물을 값을 바꾸지 않고 한 파일로 모아 DB에 저장하고, 수정안이면 원안과의 비교 결과를 만든다.
- **상태:** 🔧 — 현재 `stage13_collect.py`(파일 통합) → DB `run_artifact` 저장과 `RevisionComparison` 생성 추가
- **요구사항:** R5, R10
- **Input:** `01~12` 산출물, `09a/10w/10f`, `llm_usage.jsonl`, 설정 스냅샷, (수정안이면) 원안 `run_artifact`
- **Process**
    1. 통합: `request`, `intent`, `selection`(깔때기·선정표·근거), `portfolio`(모형·기준·뷰·타겟·뉴스 근거·walk-forward·현재 구성), `backtest`, `validation`, `money_krw`(기준일 환율·백테스트 환율), `llm_usage`, `sources`, `parameters`, `warnings`(단계 태그). `ResultsBundle` 검증 → `13_results.json` + DB
    2. 비교(수정안): `RevisionComparison{base_run, revised_run, 조건 변화, 종목 변화(추가·제외·유지), 비중·규칙 변화, 같은 조건의 성과·위험 표(수익·CAGR·변동성·Sharpe·MDD·비교지수 차이), 장점·불리한 점(🤖 선택, 숫자 대조)}`. 원안과 창이 다르면 비교를 만들지 않고 사유를 남긴다. 결과는 `store/data/comparisons/<comparison_id>.json`
- **Output:** `13_results.json`, DB `run_artifact`, (수정안) `store/data/comparisons/<comparison_id>.json`
- **성공·평가 기준:** 시계열 길이 일치·포트폴리오 id 집합 일치·원화표 완전(스키마) / 비교표의 두 열이 같은 창·자본·비교지수
- **제약:** 계산·반올림 금지(원화 환산 곱셈만 허용). 기간이 다른 지표를 나란히 두고 공정한 비교라고 쓰지 않는다

### M5-05 리포트 문서 생성기 🤖

- **한 줄 설명:** 결과 통합 파일에서 표·차트·KPI는 코드로, 해석·서술은 LLM으로 만들어 화면이 그대로 그릴 수 있는 블록 문서로 묶고, 서술의 숫자를 결과값과 대조한다.
- **상태:** 🔧 — 현재 `stage14_report.py`·`report_blocks.py`가 mock-up용 섹션 구성 → `Front/docs/03 §4`의 7섹션으로 재배치, 출처 패널 데이터·종목별 근거(M3-05)·비교 결과 블록 추가, DB `report` 저장
- **요구사항:** R5, R7, R8
- **Input:** `13_results.json`, `06_selection_explained.json`, 프롬프트 `prompts/14a_interpret/`(해석), `prompts/14b_narrate/`(서술), 설명 수준(`report_settings.explanation_level`)
- **Process**
    1. 선택 포트폴리오 = 추천(없으면 기준 템플릿, "추천 없음" 명시). `report_blocks.py`가 사실 요약(facts)과 블록을 만든다: KPI(창이 1년 미만이면 기간 수익률 라벨), 요청·조건 표, 깔때기, 선정표, 기준·템플릿·BL 비중표·도넛, 계산 상세(변동성 → 상한 전 → 상한 적용·재배분 → 최종), 누적수익·낙폭 차트, 체크포인트, 검증 규칙표·요약표, 추천·대안 카드, walk-forward 표(날짜별 뉴스 건수·뷰·비중 변화·근거), 현재 구성(시나리오·도넛·배분 금액), 출처 패널 데이터(번호 ↔ 근거 레코드), 분석 조건·실행 기록, 용어집
    2. LLM #5a 해석기(사실 요약 + 창 길이 플래그): 성과·위험 적합·검증·뷰 적중·다음 행동·뉴스 효과 문단과 자체 평가(`intent_fit`, `logic_consistency`, 의견)
    3. LLM #5b 서술기(해석 결과 + 사실, 설명 수준): 종합 투자 판단(3~5문단), 요청 해석, 산업·시장 분석, 구성 설명, 전제·재검토 조건, 현재 구성 설명, 용어 풀이
    4. 검증: 문단의 모든 숫자(%, %p, USD, 원, 일, 개, 회, 종목, 배)가 결과값 집합에 있어야 함(없으면 경고 → 리포트 상태 "검증 실패"), 금지 표현(C-12), 인용 번호 실존, `ReportDoc` 스키마
    5. 섹션(고정 순서, 하나로 이어진 페이지 + 섹션 이동 메뉴): ① 종합 투자 판단 ② 산업과 시장 분석 ③ 기업별 투자 근거(M3-05 문단 + 선정표·깔때기) ④ 포트폴리오 구성과 운용(배분표·도넛·계산 상세·현재 구성·리밸런싱 규칙) ⑤ 과거 성과와 해석(KPI·차트·체크포인트·walk-forward·검증·추천·대안) ⑥ 판단의 전제와 재검토 조건(한계·경고·편향·재검토 트리거) ⑦ 참고자료와 분석 조건(출처 패널·적용 조건·실행 기록·용어집)
- **Output:** `14_report.json`(헤더·KPI·nav·sections[blocks]·datasets·assessment·sources·parameters·warnings·status), DB `report`. 블록 타입: paragraphs, kpis, table, donut, line, area, bar, funnel, callout, cards, checkpoints, glossary, evidence. 표 열은 형식 태그(`pct`·`usd`·`krw`·`text`·`url`)만 붙이고 반올림은 화면이 한다
- **성공·평가 기준:** 섹션 7개 모두 존재 / 숫자 대조 경고 0, 금지 표현 0 / 과거 MDD가 손실 감내 수준보다 크면 그 차이가 본문에 있다 / 기간 안에 회복하지 못한 낙폭을 회복했다고 쓰지 않는다
- **제약:** LLM에는 숫자를 "사실 목록"으로 주고 새 숫자를 만들지 말라고 명시. 위험은 경고 배너가 아니라 본문. 리포트는 생성 후 불변

## Module6 포트폴리오 tracking (모의투자)

> 상태: 📄 전부. 기준 리포트의 전략을 가상 자본으로 사용자가 정한 날부터 추적한다. 실제 주문·자동매매는 범위 밖이다. 데이터는 DB(M2-01이 매일 갱신)만 쓴다.
> 

### M6-01 트래킹 시작·등록

- **한 줄 설명:** 리포트의 전략 하나를 골라 시작일·가상 자본을 확인받고 추적 객체를 만든다.
- **상태:** 📄
- **요구사항:** R11
- **Input:** 기준 리포트 id, 전략 id(추천 또는 사용자가 고른 포트폴리오), 시작일(기본 = 오늘), 가상 초기 자본·통화, 적립 규칙(요청의 월 적립 그대로 또는 끔), 리밸런싱 규칙(요청의 규칙 그대로)
- **Process**
    1. 「모의투자 시작 확인」 화면에서 기준 리포트·전략·시작일·자본·통화·구성·규칙을 보여 주고 명시적 확인을 받는다
    2. 시작 비중 = 기준 리포트의 "현재 구성"(M4-05 ③) 중 선택 전략의 타겟. 시작일이 분석 기준일보다 뒤면 시작일에 M4-05를 다시 호출해 새 타겟을 만든다(K9)
    3. 시작일 종가로 매수(소수 주식, 수수료 bp) → 첫 스냅샷 저장. 같은 리포트·전략을 여러 번 활성화할 수 있고 각각 별도 `paper_id`를 받는다(K9)
    4. 시작 자격·중지·재개(K9): 리포트가 존재하면 재접속 후에도 언제든 시작할 수 있다. 중지(`stopped`)하면 갱신·리밸런싱을 멈추고 보유를 그대로 둔다. 재개하면 중지 기간은 스냅샷 없이 비워 두고 재개일부터 갱신하며, 중지 중 지나간 리밸런싱일은 건너뛴다(기록에 남김)
- **Output:** `store/data/paper/<paper_id>/portfolio.json`(status `active`), `snapshots.jsonl` 첫 줄
- **성공·평가 기준:** 시작이 과거 리포트·백테스트를 덮어쓰지 않는다 / 시작 비중이 리포트에 표시된 비중과 같다
- **제약:** 시작일은 데이터 마감 이후일 수 없다. 추적 시작 전에는 어떤 갱신도 하지 않는다

### M6-02 일일 갱신기

- **한 줄 설명:** DB에 새 거래일 가격이 들어올 때마다 평가액·비중·낙폭·수익률을 계산해 스냅샷을 쌓는다.
- **상태:** 📄
- **요구사항:** R11
- **Input:** 활성 `paper_portfolio`, 마지막 스냅샷, DB `price_daily`·`fx_daily`(M2-02)
- **Process**
    1. 트리거: M2-01 가격 적재 완료 후(또는 사용자의 「새로고침」). 마지막 스냅샷 날짜 다음 거래일부터 데이터 마감까지 순서대로
    2. 날짜마다: 보유 수량 × 종가 = 평가액, 비중, 고점 대비 낙폭, 시작 이후 수익률, 적립일이면 적립금 매수(시작 규칙), 비교지수를 같은 자본·적립으로 함께 계산
    3. 지표는 M5-02와 같은 정의(시작 이후 구간만). 연환산 값은 추적 기간이 1년 미만이면 "참고"
    4. 데이터가 아직 없으면 스냅샷을 만들지 않고 상태 `delayed`(마지막 성공 기준일 표시). 품질 판정에서 종목이 제외되면 경고와 함께 직전값 유지 금지(해당 날짜 보류)
- **Output:** `store/data/paper/<paper_id>/snapshots.jsonl`(날짜당 1줄 추가)
- **성공·평가 기준:** 스냅샷이 거래일마다 하나씩 빠짐없이 / 비교지수와 같은 자본·적립 / 갱신 지연이 화면에 "마지막 기준일"로 드러난다
- **제약:** 앱이 닫혀 있는 동안의 갱신은 서버 배치가 하며, 화면은 약속하지 않는다. "실시간"이라 쓰지 않는다

### M6-03 리밸런싱 실행기

- **한 줄 설명:** 리밸런싱 규칙으로 계산한 날짜가 오면 Module4를 다시 돌려 새 타겟으로 조정하고 기록한다.
- **상태:** 📄
- **요구사항:** R4, R11
- **Input:** 활성 `paper_portfolio`, 리밸런싱 규칙(2.2(d)), 당일 가격, M4-05 `construct`
- **Process**
    1. 리밸런싱일 판정: 시작일 기준으로 규칙(`2w` = 10거래일마다, 달력 단위는 기간 첫 거래일) 계산. 데이터 마감이 그 날짜를 지난 뒤에만 실행
    2. 새 타겟: `construct(종목, 리밸런싱일, …)` — 시장모형 재추정 + 직전 14일 DB 뉴스 뷰 + BL(세트 1개). 뉴스 부족이면 기준 비중 + fallback 표시. 종목은 유지, 비중만 갱신(K8)
    3. 적용: 리밸런싱일 종가로 현재 비중 → 타겟 비중, 거래·회전율·수수료 기록. 적용 비중은 소수 주식·수수료 때문에 타겟과 약간 다를 수 있으므로 둘 다 저장
    4. 기록: `rebalance_record{date, target_weights, applied_weights, trades, commission, 뷰·근거 요약, fallback}`
- **Output:** `rebalances.jsonl` 1줄 추가, `portfolio.json`의 현재 보유·현금 갱신
- **성공·평가 기준:** 리밸런싱 횟수 = 규칙 기대값 / 타겟이 상한·조정폭 제약을 만족 / 뷰 근거가 리밸런싱일 이전 뉴스뿐
- **제약:** 사용자 조건(상한·종목 수·규칙)은 시작 시점 값을 고정해 쓴다(프로필이 바뀌어도 추적 중 변경 없음). 자동 매매 트리거나 임의 임계값을 만들지 않는다

### M6-04 트래킹 결과 제공

- **한 줄 설명:** 목록·상세 화면이 그릴 수 있는 형태로 추적 결과를 만든다.
- **상태:** 📄
- **요구사항:** R11
- **Input:** `store/data/paper/<paper_id>/`의 `portfolio.json`·`snapshots.jsonl`·`rebalances.jsonl`, 기준 리포트(백테스트 결과)
- **Process**
    1. 목록 행: 전략명, 시작일, 최신 기준일, 가상 초기·현재 가치, 시작 이후 수익률, 같은 기간 비교지수와 차이(%p), 갱신 상태. 시작일이 다른 전략끼리 순위를 매기거나 합산하지 않는다
    2. 상세: 「추적 시작 이후 성과」와 「과거 백테스트」를 분리해 제공(하나의 연속 곡선으로 합치지 않음). 구성표는 시작 비중·현재 비중·목표 비중·리밸런싱 시 적용 비중을 구분. 재조정 기록(날짜·목표·적용·근거 요약). 낙폭 이벤트(설정 수준 통과)는 정보 표시용이며 매매 트리거가 아니다
    3. 상태: `ok`·`delayed`(마지막 성공 기준일)·`stopped`(중지일, 재개 가능)
- **Output:** M0-06 응답 객체(목록·상세)
- **성공·평가 기준:** 상세의 모든 숫자가 스냅샷·기록 값과 같다(재계산 없음) / 백테스트와 추적 곡선이 분리되어 있다
- **제약:** 표시 반올림은 화면에서(부록 D)

## Module7 사용자 화면 구성 (React)

> 상태: 📄 전부. 화면 목록과 흐름은 `Front/docs/02-screens-and-flows.md`를 따르고, 디자인은 새로 한다. 현재 `Front/` 구현은 참고하지 않는다. 화면은 M0-06 API만 호출하고 계산하지 않는다.
> 

### M7-01 화면 구조·내비게이션

- **한 줄 설명:** 공통 레이아웃과 이동 규칙.
- **Process:** 데스크톱 고정 사이드바(목적지: `홈`, `투자 프로필`, `분석 리포트`, `모의투자`) + 중앙 콘텐츠. 수정 요청·출처·계산 상세는 오른쪽 패널로 열고, 닫으면 원래 위치·초점으로 복귀. 분석·리포트·모의투자 상세는 개별 식별자로 라우팅(새로고침·공유 가능). 브라우저 저장은 임시 상태(열린 탭·초안)만, 원천은 DB
- **성공·평가 기준:** 모든 화면이 새로고침 후 같은 상태로 열린다 / 내부 용어(JSON·스키마·stub)가 화면에 없다

### M7-02 프로필 화면 (↔ M1-01)

- **화면:** 「최초 프로필 설정」(투자금·기간, 투자성향 질문, 손실 감내 수준, 관심산업·선호·제약 → 진단 → 조건 입력 → 저장 → 홈), 「프로필 요약·수정」(최종 성향, 산출 성향과 변경 여부, 투자조건 → 수정 → 검증 → 저장)
- **규칙:** 필수 4항목 없이는 저장 불가. HARD 위반은 항목 옆에 사유. 투자성향 진단값과 최종 선택이 다르면 확인. 저장 후 "과거 리포트는 바뀌지 않는다"를 알림

### M7-03 분석 요청 화면 (↔ M1-02, M0-05)

- **화면:** 「홈」(자연어 아이디어 입력, 적용할 저장 조건 요약, 이번 분석 조건 변경), 「보충 질문」(한 번에 1개, 최대 5회, 답변 → 재검사), 「조건 확인」(기본 조건·이번 값·변경 항목·지원 제약 → 조건 수정 또는 「분석 시작」), 「분석 진행」(5묶음 단계의 실제 상태·완료 내용, 취소, 실패 시 복구 안내, 재접속 시 마지막 상태)
- **규칙:** 「분석 시작」 전에는 분석이 돌지 않는다. 진행 화면은 실제 `run_step`만 보여 주고 가짜 진행률을 만들지 않는다. 앱을 닫아도 자동 재개하지 않는다

### M7-04 리포트 화면 (↔ M5-05)

- **화면:** 「리포트 목록」(전략명·원래 요청 요약·분석 기준일·작성일·상태·트래킹 여부), 「리포트 상세」(섹션 7개를 하나로 이어진 페이지 + 섹션 이동 메뉴; 블록 타입별 렌더러; 번호 인용 → 출처 패널(문서명·발행기관·발표일·발췌·연결된 주장·원문 링크); 계산 상세 패널; 진입: 「출처 확인」「같은 조건으로 재분석」「조건 수정」「모의투자 시작」)
- **규칙:** 숫자 형식은 부록 D. 핵심 분석은 패널 없이 본문만으로 읽힌다. 검증 실패 리포트는 열리지 않고 사유만 보여 준다(R5). 경고 배너·반복 주의 박스 없음

### M7-05 모의투자 화면 (↔ Module6)

- **화면:** 「모의투자 시작 확인」(기준 리포트·전략·시작일·가상 자본·통화·구성·규칙 → 확인), 「모의투자 목록」(M6-04 목록 행), 「모의투자 상세」(추적 이후 성과 / 과거 백테스트 분리 표시, 현재 구성표(시작·현재·목표·적용), 운용 규칙·재조정 기록, 갱신 주기와 마지막 기준일, 「원본 리포트」「수정·재분석」 진입)
- **규칙:** "갱신 지연"이면 마지막 성공 기준일과 「새로고침」. 시작일이 다른 전략을 순위·합산하지 않는다. "실시간" 표현 금지

### M7-06 수정·비교 화면 (↔ M1-04, M5-04)

- **화면:** 「수정 패널」(기준 전략·현재 조건·자연어 수정 요청 → 원안과 제안 변경 → 「변경 확인」 → 보충 질문 → 「수정안 분석하기」), 「비교 결과」(조건·종목·비중·규칙 변화, 같은 조건의 성과·위험 표, 장점·불리한 점 → 「신규 리포트」「신규 모의투자 시작 확인」)
- **규칙:** 변경 항목은 모두 사용자 확인 후 반영. 비교표의 두 열이 같은 창·자본·비교지수임을 표시. 원안은 그대로 남는다

## 부록

### 부록 A. 입력 스키마 (요청 필드)

[HARD] = 규칙 검증(M0-02), 위반 시 수정 요구. [SOFT] = LLM 해석(M3-01). 값 예시는 두지 않는다.

| 그룹 | 필드 | 타입·범위 | 구분 | 용도 |
| --- | --- | --- | --- | --- |
| profile | age_band | 20s·30s·40s·50s·60s+ | SOFT | 기간·위험 수용력 참고 |
| profile | investment_experience | none·beginner·intermediate·advanced | SOFT | 설명 난이도 |
| profile | financial_knowledge | basic·intermediate·expert | SOFT | 용어 설명 여부 |
| profile | investable_ratio_of_assets | 0~1 | SOFT | 보수적 보정 |
| capital | initial_amount, currency | > 0, KRW·USD | HARD | 배분 금액·백테스트 초기자본 |
| capital | monthly_contribution, contribution_day | ≥ 0, 1~28 | HARD | 적립 |
| horizon | start_date | 날짜(서비스에서는 분석 기준일로 대체) | HARD | 기준일 |
| horizon | target_years, purpose | > 0, wealth_growth·income·capital_preservation·retirement | SOFT | 지표 선택·설명 |
| horizon | backtest_years | 정수 ≥ 1, 기본 3 | HARD | 백테스트 창 길이(K2) |
| risk | risk_tolerance | conservative·moderate·aggressive | SOFT | δ 배수·변동성 밴드 |
| risk | max_drawdown_tolerance | 0~1 | HARD | R1 기준 |
| risk | loss_reaction | sell·hold·buy_more | SOFT | 실효 허용 낙폭 보정 |
| risk | target_annual_return, benchmark | 실수, 티커 | SOFT / HARD | R2·R3 기준 |
| constraints | universe, asset_types | SP500·NASDAQ100·KOSPI200 (복수 선택) / stock·etf | HARD | 후보 범위 |
| constraints | num_holdings {target, min, max} | min ≤ target ≤ max | HARD | 종목 수 |
| constraints | max_weight_per_stock, max_weight_per_sector | 0~1, 섹터 ≥ 종목 | HARD | 상한 |
| constraints | min_cash_ratio | 0~1 | HARD | 현금 |
| constraints | exclude_tickers, exclude_sectors, exclude_themes, must_include_tickers | 목록 | HARD | 포함·제외 |
| constraints | rebalance {count, unit} | count ≥ 0, unit ∈ 2w·1m·1q·6m·1y | HARD | 리밸런싱 규칙 |
| constraints | allow_leverage, allow_short | bool(현재 false만 지원) | HARD | – |
| constraints | min_market_cap_usd, min_avg_daily_volume_usd | ≥ 0 | HARD | 유동성·규모 |
| strategy_preference | template | low_per·quality·momentum·low_volatility·high_dividend | HARD | 스크린 지표 |
| strategy_preference | baseline_weighting | equal_weight·market_cap·inverse_volatility·min_variance | HARD | 기준 비중 |
| strategy_preference | use_news_tilt | bool | HARD | BL 사용 |
| natural_language | idea, language | 문자열(≥ 5자), 언어 코드 | SOFT | 테마 해석 |

구성 설정(사용자 입력이 아니라 M4-01이 정함): 시작일 재선정 여부(기본 참), 뷰 세트 수·세트당 뷰 수, walk-forward(세트 1개), 현재 구성(기준일).

### 부록 B. 단계 산출물과 DB 저장

| 산출물 | 모듈 | 내용 | 저장소 |
| --- | --- | --- | --- |
| `01_request.json` | M1-02 | 요청 + 파생값 | `store/data/requests/<request_id>.json` |
| `02_intent.json` | M3-01 | 테마·스크린·위험 파라미터·뉴스 틸트·검증 기준·질문 | – |
| `03_candidates.json` | M3-02 | 후보·근거·제외 사유·깔때기 | – |
| `04_tagging.json` | M3-03 | 후보별 판정·신뢰도·사유 | – |
| `05_selection.json` | M3-04 | 최종 종목·순위·지표값·거절 사유·infeasibility·전략 사양 | – |
| `06_selection_explained.json` | M3-05 | 종목별 근거 문단·인용 | – |
| `07_backtest_spec.json` | M4-01 | 기준일·창·자본·리밸런싱·비교지수·재선정 | – |
| `08_market_model.json` `08_baseline_portfolios.json` | M4-02 | Σ·상관·변동성·시총비중·δ·π, 템플릿 4개 | – |
| `09_views.json` `09a_news_evidence.json` | M4-03 | 뷰 세트, 날짜별 근거 창 | – |
| `10_target_portfolios.json` `10w_target_paths.json` `10f_forward_portfolios.json` | M4-04, M4-05 | 정적 타겟, 날짜별 비중 경로, 현재 구성 | – |
| `11_backtest_results.json` `11_daily_panel.parquet` | M5-01, M5-02 | 포트폴리오·비교지수별 지표·시계열·체크포인트 | – |
| `12_validation.json` | M5-03 | 판정·비교표·추천·대안 | – |
| `13_results.json` | M5-04 | 전부 통합 (+ 비교 결과) | DB `run_artifact`; 비교는 `store/data/comparisons/` |
| `14_report.json` | M5-05 | 리포트 문서(블록) | DB `report` |
| `prompts/` `llm_raw/` `llm_cache/` `llm_usage.jsonl` | M0-03 | 프롬프트·원문·캐시·사용량 | – |
| 실행 상태 | M0-05 | 단계별 상태·큐 순번 | DB `run_step` + `store/data/runs.json` |
| 트래킹 | Module6 | 추적 객체·스냅샷·재조정 | `store/data/paper/<paper_id>/` |

### 부록 C. LLM 호출 목록

| # | 모듈 | 프롬프트 | LLM에 주는 것 | 돌려받는 것 | 코드 검증 |
| --- | --- | --- | --- | --- | --- |
| 0 | M2-03 (선택, 배치) | `00_descriptor` | 종목 이름·GICS·사업 설명 | 한국어 요약·키워드 | 스키마 |
| 1 | M3-01 / M1-02 | `02_intent` (+ 컨텍스트) | 요청·아이디어·GICS 트리·컨텍스트 패키지 | `IntentSpec` + `questions` | 코드 자릿수, 템플릿-지표 일치, 테마 ≥ 1 |
| 1′ | M1-04 | `02_intent` 수정 모드 | 기준 리포트 요약·수정 요청·컨텍스트 | 변경 조건 초안 | HARD 규칙, 지원 제약만 |
| 2 | M3-03 | `04_classify` | 후보 40개 표·테마 설명 | 후보별 판정·신뢰도·사유 | 형식, 누락 티커 |
| 3 | M3-05 | `06_explain` | 종목별 근거 목록(뉴스·재무·지표) | 종목별 문단·인용 | 인용 실존, 숫자 대조, 금지 표현 |
| 4 | M4-03 (M4-05 호출처마다) | `09_views_news` | 종목 표·테마 요약·뉴스 근거 목록 | 시나리오 세트·뷰 | 티커·중복·신뢰도·수익률 범위·근거 실존·뉴스 없는 절대 뷰 삭제 |
| 5a | M5-05 | `14a_interpret` | 사실 요약·창 길이 플래그 | 해석 문단·자체 평가 | 숫자 대조, 금지 표현 |
| 5b | M5-05 | `14b_narrate` | 사실 요약·해석·설명 수준 | 서술 문단·용어 풀이 | 숫자 대조, 금지 표현 |
| 6 | M5-04 (선택) | `15_compare` 🔶 | 원안·수정안 비교표 | 장점·불리한 점 | 숫자 대조 |

모든 호출은 M0-03을 거친다(캐시·재시도·사용량). 요청당 비용은 사용량 로그로 집계만 한다(K10: 상한 없음).

### 부록 D. 오류·경고 정책, 진행 상태, 표시 규칙

**오류·경고**

| 상황 | 처리 |
| --- | --- |
| 요청 HARD 위반, 보충 질문 5회 초과 | 분석 시작 전 차단, 화면에 사유 |
| 환율·데이터 범위 없음, 필수 종목 데이터 제외, 통과 종목 0개, LLM 재시도 후 실패, 스키마 실패, 숫자 대조 경고 | run FAILED, 리포트 없음, 실패 단계·사유 표시 |
| 유니버스 밖 예시 티커, 지표 결측 종목, 모형 창 부족 종목, 뷰 클리핑·삭제, 뉴스 부족(fallback), 창 clamp, 짧은 창(R2·R7 info), 데이터 보간, 대안 생략 | 계속 + 단계 `warnings` → 결과 통합 → 리포트 「전제와 한계」 |
| 추천 없음 | 계속. "추천 없음"과 현금 혼합 대안을 그대로 표시 |
| 트래킹 데이터 지연 | 상태 `delayed`, 마지막 성공 기준일 표시, 새로고침 |

**진행 상태(run_step → 화면 5묶음):** 조건·자료 확인(M1-02, M2-02) → 후보·규칙 구성(M3-02~05, M4-01~05) → 전략 검증(M5-03) → 백테스트(M5-01) → 리포트 구성·정합성 검사(M5-04, M5-05). 상태: 진행·부분 완료(경고)·취소·실패·중단 후 재접속.

**표시 규칙(화면·리포트 공통, 표시 단계에서만 반올림, ROUND_HALF_UP):** 수익률·비율·Sharpe·USD 소수 둘째 자리(수익률은 필요 시 +·− 부호), 비중 소수 첫째 자리, 원화 정수·천 단위 쉼표, 날짜 `YYYY-MM-DD`, 수익률 차이는 %p, 환율 "1 USD = X KRW (기준일)". 계산 불가 값은 사유와 함께 표시하고 0·무한대로 대체하지 않는다.

### 부록 E. 구현 현황과 전환 작업

| 상태 | 모듈 |
| --- | --- |
| 🛠 구현됨 | M0-01, M0-03, M3-02, M3-03, M3-04, M4-02, M4-04, M5-01, M5-02, M5-03 |
| 🔧 부분(변경 명시) | M0-02 저장 객체 모델 · M0-04 DB 쓰기·로컬 저장소(`store.py`) · M0-05 작업 큐·run_step · M1-02 질문 루프 · M2-02 조회 통일·품질 판정·혼합 시장 달력 · M2-03 KOSPI 200 디스크립터 · M2-04 한국어 뉴스 · M3-01 컨텍스트·questions · M3-05 근거 인용 · M4-01 기준일 규칙 · M4-03 뉴스 기본 경로 · M4-05 `construct()` 통합 · M5-04 DB 저장·비교 · M5-05 7섹션·출처 패널 |
| 📄 문서만 | M0-06, M1-01, M1-03, M1-04, M2-01(외부), M6-01~04, M7-01~06 |

mock-up → 서비스 전환 순서(제안): ① M0-04 DB 계층 + M2-02 조회 통일(분석이 DB로 돌게) → ② M0-05 작업 큐 + M0-02 저장 모델 + 로컬 저장소 `store/`(M0-04) + M5-04 DB 저장(run·리포트가 DB에, 요청·트래킹이 로컬에 남게) → ③ M1-01~03 + M0-06 + M7-02~04(프로필·요청·리포트 화면) → ④ M4-05 `construct()` + M4-03 뉴스 기본 경로 + M3-05 근거 인용 + M5-05 7섹션 → ⑤ Module6 + M7-05 → ⑥ M1-04 + M7-06. 개발·검수에는 `build_notebook.py`(결과 통합 파일 → 노트북)와 stub 모드를 계속 쓴다.

### 부록 F. 결정 기록과 남은 항목

**결정됨 (2026-10-10)**

| # | 항목 | 결정 | 반영 위치 |
| --- | --- | --- | --- |
| K1 | 신규 저장 테이블 | DB에 만들지 않는다. 프로필·요청·run 색인·트래킹·비교는 로컬 JSON 저장소(`module_mockup/store/`)에 두고 스키마는 이 문서(부록 H)와 `store/schemas/`가 정의한다 | 2.2(b′), M0-04, 부록 H |
| K2 | 백테스트 창 길이 | 사용자가 지정, 기본 3년 (`horizon.backtest_years`) | 2.2(d), M4-01, 부록 A |
| K3 | 데이터 수집 | 팀 DB에서만 가져온다. 분석 코드는 외부 소스를 호출하지 않는다 | M2-01, M2-02 |
| K4 | 생존 편향 | 디스크립터를 구성종목 스냅샷 날짜별로 보관하고, 과거 기준일에는 기준일 이전 최신 버전을 쓴다. 이력이 없는 기간은 한계로 표시 | M2-03, M3-02 |
| K5 | 뉴스 언어 | 한국어 뉴스 포함. DB에 소스가 추가되면 설정으로 따른다 | M2-04 |
| K6 | 뉴스 부족 시 뷰 | 플레이스홀더 뷰를 쓰지 않는다. 기준 비중(fallback)만 | M4-03 |
| K7 | 저정보 헤드라인 | LLM 판단으로 뷰에서 제외(프롬프트 규칙), 코드 강제 없음 | M4-03 |
| K8 | 리밸런싱 시 재선정 | 비중만 갱신, 종목 유지 | M4-05, M6-03 |
| K9 | 트래킹 정책 | 시작일 > 기준일이면 시작일에 재구성, 같은 전략의 중복 활성화 허용(별도 paper_id), 재접속 후에도 시작 가능, 중지·재개 지원(중지 기간은 비워 둠) | M6-01, M6-04 |
| K10 | LLM 비용 | 상한 없이 사용량 로그만 남긴다 | M0-03 |
| K11 | 분석 실행 방식 | 작업 큐(FIFO, 단일 워커)가 CLI 파이프라인을 순차 실행 | M0-05 |
| K12 | 재무 템플릿 기간 | 현 상태 유지(DB 재무 범위 안에서만 as-of 계산) | M3-04 |
| K13 | 무위험수익률 | 현 상태 유지(설정 상수) | M0-01, M5-02 |
| K14 | 산업그룹 상한 | 현 상태 유지(섹터 상한만) | M3-04, M4-02 |
| K15 | 접근 제한 | 현 상태 유지(단일 사용자, 인증 없음) | M0-06 |

**남은 항목 🔶**

| # | 항목 | 현재 | 고려 사항 |
| --- | --- | --- | --- |
| K16 | 미국·한국 혼합 시장 처리 | 달력 합집합 + 휴장일 직전 종가 유지, 거래일 환율로 USD 환산 | 교집합 달력 대안, 환산 시점(종가 vs 익일), 시차(한국 마감이 미국보다 먼저), 한국 거래 가정(소수 주식 불가·거래세) 반영 여부 |
| K17 | KRX 업종 → GICS 매핑 | 없음 | 한국 종목을 GICS 트리에 넣기 위한 매핑표 작성·검수 |

### 부록 G. 용어 풀이

- **유니버스:** 후보가 될 수 있는 종목 전체. S&P 500·NASDAQ 100(미국)과 KOSPI 200(한국) 구성종목의 합집합.
- **GICS:** 글로벌 산업분류 기준. 섹터 → 산업그룹 → 산업 → 세부산업 4단계, 코드 2/4/6/8자리. 테마를 종목으로 바꾸는 공통 언어.
- **디스크립터:** 종목별 GICS 태그·키워드·한 줄 소개 사전. LLM에 종목 표를 주지 않기 위한 장치.
- **템플릿 스크린:** 지표 하나로 순위를 매겨 고르는 규칙(모멘텀 = 최근 1개월을 뺀 12개월 수익률, 저변동성, 저PER, 고배당, 퀄리티).
- **기준 비중·템플릿:** 동일비중(1/N), 시가총액비중, 역변동성(변동성이 낮을수록 더), 최소분산(전체 변동성 최소화).
- **Ledoit-Wolf 수축:** 표본 공분산의 추정 오차를 줄이려고 구조화된 행렬 쪽으로 당기는 방법.
- **내재 기대수익률 π, 위험회피 δ:** "시장이 지금 이 비중을 들고 있으려면 각 종목에 이만큼의 기대수익을 전제해야 한다"는 역산값. δ는 위험 1단위를 피하려고 포기하는 수익.
- **Black-Litterman(BL):** π에 뷰를 섞어 기대수익률을 갱신하고 그걸로 비중을 다시 푸는 방법. 뷰가 약하면 기준 비중 근처, 강하면 더 움직인다.
- **뷰(view):** 절대 뷰 "종목 X는 연 +r%", 상대 뷰 "X가 Y보다 연 +r%". 신뢰도가 Ω(불확실성)를 결정.
- **walk-forward:** 리밸런싱 날짜마다 그 시점까지의 정보로만 모형·뷰를 다시 만드는 방식. 미래 정보가 섞이지 않는다.
- **체크포인트:** 리밸런싱 날짜(와 종료일)마다 비중·보유·거래·그때까지의 지표를 저장한 스냅샷.
- **MDD(최대낙폭):** 고점 대비 가장 크게 떨어진 비율. **Sharpe:** (수익률 − 무위험수익률)/변동성. **XIRR:** 적립 시점을 반영한 연수익률.
- **현금 혼합안:** 포트폴리오에 현금을 섞어 낙폭을 허용치 안으로 들이는 대안(현금 수익 0 가정).
- **모의투자(tracking):** 실제 주문 없이 가상 자본으로 전략을 시작일부터 따라가며 성과를 기록하는 것.
- **컨텍스트 패키지:** 이전 요청·질문답변·기준 리포트 요약을 LLM 프롬프트에 넣기 위해 토큰 상한 안에서 정리한 묶음.
- **stub:** LLM이 돌려줬을 답을 저장해 둔 파일. 개발·테스트에서 API 없이 파이프라인을 돌릴 때 쓴다.

### 부록 H. 로컬 JSON 저장소 (`module_mockup/store/`)

K1 결정에 따라 DB에 없는 저장 객체는 로컬 JSON으로 둔다. 구조와 규칙:

```
module_mockup/store/
  README.md                 구조·규칙 설명 (git 포함)
  schemas/                  JSON Schema draft 2020-12 (git 포함) — 아래 7개
  data/                     실제 사용자 데이터 (git 제외: module_mockup/.gitignore의 store/data/*)
    profile.json
    requests/<request_id>.json
    runs.json
    paper/<paper_id>/portfolio.json · snapshots.jsonl · rebalances.jsonl
    comparisons/<comparison_id>.json
```

| 스키마 | 파일 | 핵심 필드 |
| --- | --- | --- |
| `profile.schema.json` | `profile.json` | `schema_version`, `profile_id`, `current_version`, `versions[]{version, created_at, risk_type_computed, risk_type_overridden, profile, capital, horizon(backtest_years 포함), risk, constraints, strategy_preference}` |
| `analysis_request.schema.json` | `requests/<id>.json` | `request_id`, `created_at`, `mode`, `base_report_id`, `profile_version`, `idea`, `language`, `overrides`, `questions[]{seq, field, kind, question_ko, options, answer, answered_at}`, `effective_request`, `status(draft·confirmed·cancelled)`, `confirmed_at`, `run_id` |
| `run_index.schema.json` | `runs.json` | `runs[]{run_id, request_id, status(queued·running·success·partial·failed·cancelled), queued_at, started_at, finished_at, output_dir, report_id, error_code, error_message}` |
| `paper_portfolio.schema.json` | `paper/<id>/portfolio.json` | `paper_id`, `report_id`, `run_id`, `strategy_id`, `name_ko`, `start_date`, `initial_capital{amount, currency, usd, fx_rate, fx_date}`, `contribution{enabled, monthly_amount, day}`, `rebalance_rule{count, unit}`, `constraints_snapshot`, `tickers[]`, `start_weights`, `state{holdings{ticker: shares}, cash_usd, last_snapshot_date}`, `status`, `created_at`, `stopped_at`, `resumed_at`, `history[]` |
| `paper_snapshot.schema.json` | `paper/<id>/snapshots.jsonl` (1줄 = 1객체) | `date`, `value_usd`, `cash_usd`, `weights`, `drawdown`, `return_since_start`, `contribution_usd`, `benchmark_value_usd`, `fx_rate`, `status(ok·delayed·hold)` |
| `rebalance_record.schema.json` | `paper/<id>/rebalances.jsonl` | `date`, `seq`, `before_weights`, `target_weights`, `applied_weights`, `trades[]{ticker, side, shares, price, value_usd}`, `commission_usd`, `turnover`, `views[]{summary_ko, evidence_ids}`, `evidence_window{start, end, n_articles, n_tickers_with_news}`, `fallback`, `skipped`, `warnings[]` |
| `revision_comparison.schema.json` | `comparisons/<id>.json` | `comparison_id`, `base_run_id`, `revised_run_id`, `base_report_id`, `revised_report_id`, `created_at`, `same_window`, `condition_changes[]{field, before, after}`, `ticker_changes{added, removed, kept}`, `weight_changes{ticker: {before, after}}`, `rule_changes[]`, `performance_table[]{metric, base, revised, diff}`, `pros_cons_ko`, `warnings[]` |

규칙: ① 모든 파일에 `schema_version`(정수)을 두고 스키마가 바뀌면 올린다 ② 쓰기는 M0-04 `store.py`만 하며 스키마 검증 → 임시 파일 → 이름 바꾸기 순서로 원자적으로 쓴다 ③ `.jsonl`은 줄 추가만 하고 과거 줄을 고치지 않는다 ④ ID 형식: `request_id` = `req_<YYYYMMDD>_<HHMMSS>_<4hex>`, `run_id` = `run_<YYYYMMDD>_<HHMMSS>`, `paper_id` = `paper_<YYYYMMDD>_<4hex>`, `comparison_id` = `cmp_<base_run_id>__<revised_run_id>` ⑤ `store/data/`는 백업 대상이며 git·Drive에 올리지 않는다 ⑥ 날짜는 `YYYY-MM-DD`, 시각은 ISO 8601(시간대 포함), 금액은 USD 실수, 비중은 소수.