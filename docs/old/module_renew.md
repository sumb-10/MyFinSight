# MyFinSight 모듈 명세 & 분배 (현 구현 반영판)

<aside>
📌

**범위:** 사용자 요청(JSONC 1개) → LLM 의도 해석 → 코드 후보 검색 → LLM 후보 분류 → 코드 정량 스크린 → 포트폴리오 구성(규칙 템플릿 4개 + Black-Litterman 시나리오 5개, 뉴스 근거 뷰) → bt 백테스트 → 규칙 검증·추천 → 결과 통합 JSON → 리포트 JSON(LLM 해석·서술) → 노트북

**기준:** `module_mockup/` 구현 (2026-10-10, branch `module_mock_up`, PR #1). 원본 `docs/modules.md`(v1, 2026-10-02)는 "LLM 없이 고정 Spec" 가정으로 쓴 것이라, 지금 돌아가는 코드에 맞게 다시 썼다. 원본의 모듈 중 하나의 스크립트로 합쳐진 것은 합쳤고, 새로 생긴 단계는 추가했다.

**모듈 ID:** M{기능 2자리}-{순번 2자리}. 00 = 공통 기반, 01 = F1 … 08 = F8. 원본에서 범위 밖이었던 F7(LLM)은 공통 기반 M00-03과 각 단계 안의 LLM 모듈로 흡수했다. LLM을 호출하는 모듈은 이름 뒤에 🤖, 팀 확인이 필요한 항목은 🔶.

</aside>

# 0. 원본(v1)과 달라진 점 — 먼저 읽기

| 구간 | 원본 v1 (LLM 없음) | 현 구현 |
| --- | --- | --- |
| 입력 | `profile.json` + 고정 `spec.json` 두 파일 | **요청 JSONC 한 파일**(프로필·자금·기간·위험·HARD 제약·템플릿 선택·자연어 아이디어)과 **백테스트 요청 JSONC**(확인·기간·뷰 수·walk-forward·현재 구성). 주석에 [HARD]/[SOFT]를 표시해 어느 값이 기계 검증이고 어느 값이 LLM 해석인지 구분 |
| 전략 생성 | 사람이 `selection.rule`(fixed_list / low_vol / momentum)과 `weighting.rule`을 직접 지정 | **자연어 아이디어를 LLM이 테마(GICS 코드·키워드)로 해석** → 코드가 후보 검색 → LLM이 후보를 테마에 맞는지 분류 → 코드가 템플릿 지표(모멘텀 등)로 순위를 매겨 선정. **LLM은 종목을 직접 고르지 않고, 숫자도 만들지 않는다** |
| Universe | 지수 구성종목 스냅샷 + `industry_map.toml`(관심산업→GICS industry 수동 매핑) | **유니버스 디스크립터**: 518종목(S&P 500 ∪ NASDAQ 100) 각각에 GICS 4단계 태그·키워드·한 줄 소개를 미리 붙인 JSON. LLM에는 종목 표 대신 **GICS 분류 트리**만 보여 준다 |
| 비중 결정 | 규칙 2개(동일, 역변동성) + 종목 상한 | **템플릿 4개**(동일·시가총액·역변동성·최소분산) 위에 **Black-Litterman**으로 LLM 뷰(시나리오 5세트 × 뷰 4개)를 얹은 타겟 5개. 종목·섹터 상한, 기준 대비 종목당 ±5%p 이내 조정 |
| 뉴스 반영 | 없음 | 팀 뉴스 DB(PostgreSQL) 헤드라인을 근거로 뷰를 만드는 변형. 리밸런싱마다 직전 2주 뉴스로 뷰를 다시 만드는 **walk-forward**, 최신 가격·뉴스로 "지금 구성한다면"을 만드는 **현재 구성** |
| 백테스트 | 자체 pandas 시뮬레이터, 분기 리밸런싱만, 편도 10bp | **bt 라이브러리**, 리밸런싱 단위 2w/1m/1q/6m/1y × 횟수, 월 적립, 수수료 5bp, 소수 주식, 무위험수익률 4%. 포트폴리오 9개(+walk-forward 5개)와 비교지수 SPY·QQQ·XLV를 **같은 조건으로 동시에** 돌리고 리밸런싱마다 체크포인트 저장 |
| 검증 | Spec 정적 검증, 비중 동적 검증, Report 일치성 검사 (모듈 3개) | **Pydantic 스키마**가 모든 단계 경계를 검증(입력·비중 합·시계열 길이 등) + **규칙 검증 R1~R8**로 사용자 기준 통과 여부 판정·추천·현금 혼합 대안 + 리포트 **숫자 대조(audit)** + pytest |
| 리포트 | 템플릿 문장으로 만든 Markdown | **13_results.json**(모든 결과를 하나로) → **14_report.json**(표·차트·KPI는 코드, 해석·서술은 LLM, 블록 모델) → **노트북**으로 확인. React 화면(15단계)은 선택 |
| 저장소 | SQLite Repository 인터페이스 | yfinance 결과를 **parquet 캐시**(`~/.myfinsight/data/raw`)에, 뉴스는 **팀 PostgreSQL(읽기 전용)** 에서 조회. 자격 증명은 `.env` |
| 실행 | `python -m myfinsight run` | `run_pipeline.py --stop-at N --from N`, LLM 모드 `stub`/`api` 전환, 프롬프트 캐시·토큰 비용 리포트 |

# 1. 전체 모듈 목록

| F | ID | 모듈 | 스크립트 | 단계 output |
| --- | --- | --- | --- | --- |
| 공통 | M00-01 | 설정·경로 | `common.py` `portfolio_config.py` `backtest_config.py` `.env` | – |
| 공통 | M00-02 | 단계 스키마 (Pydantic) | `schemas.py` | – |
| 공통 | M00-03 | LLM 호출기 🤖 | `llm.py` `llm_config.py` `prompts/` `stubs/` | `output/prompts/` `llm_usage.jsonl` |
| F1 | M01-01 | 요청 정규화·검증기 | `stage1_normalize.py` | `01_request.json` |
| F2 | M02-01 | 시장 데이터 수집·캐시 | `fetch_data.py` `fetch_fundamentals.py` | `~/.myfinsight/data/raw/*` |
| F2 | M02-02 | 유니버스 디스크립터 생성기 (🤖 선택) | `build_descriptor.py` `descriptor.py` `stage0_descriptor_llm.py` | `data/processed/sp500_nasdaq100_descriptor.json` |
| F3 | M03-01 | 의도 해석기 🤖 | `stage2_intent.py` | `02_intent.json` |
| F3 | M03-02 | 후보 검색기 | `stage3_retrieve.py` | `03_candidates.json` |
| F3 | M03-03 | 후보 분류기 🤖 | `stage4_classify.py` | `04_tagging.json` |
| F3 | M03-04 | 정량 스크린·선정기 (🤖 근거 서술 선택) | `stage5_screen.py` `metrics.py` (`stage6_explain.py`) | `05_selection.json` (`06_selection_explained.json`) |
| F4 | M04-01 | 백테스트 사양·재선정 | `stage7_confirm.py` | `07_backtest_spec.json` |
| F4 | M04-02 | 시장모형·템플릿 비중 | `stage8_baseline.py` `portfolio.py` | `08_market_model.json` `08_baseline_portfolios.json` |
| F4 | M04-03 | 뷰 생성기 🤖 | `stage9_views.py` | `09_views.json` |
| F4 | M04-04 | Black-Litterman 타겟 | `stage10_black_litterman.py` `portfolio.py` | `10_target_portfolios.json` |
| F4 | M04-05 | 뉴스 근거 수집기 | `news_db.py` `stage9a_news.py` `db_probe.py` | `09a_news_evidence.json` |
| F4 | M04-06 | 뉴스 반영 구성기 (walk-forward·현재 구성) 🤖 | `stage10w_walkforward.py` `stage10f_forward.py` | `10w_target_paths.json` `10f_forward_portfolios.json` |
| F5 | M05-01 | 백테스트 시뮬레이터 | `stage11_backtest.py` `backtest_engine.py` | `11_backtest_results.json` `11_daily_panel.parquet` |
| F5 | M05-02 | 성과 지표 계산기 | `backtest_metrics.py` | (11 안에 포함) |
| F5 | M05-03 | 규칙 검증·추천기 | `stage12_validate.py` | `12_validation.json` |
| F6 | M06-01 | 결과 통합기 | `stage13_collect.py` | `13_results.json` |
| F6 | M06-02 | 리포트 문서 생성기 🤖 | `stage14_report.py` `report_blocks.py` | `14_report.json` |
| F6 | M06-03 | 결과 노트북 | `build_notebook.py` | `notebooks/results_overview.ipynb` |
| F8 | M08-01 | 파이프라인 실행기·실행 기록 | `run_pipeline.py` `llm_cost_report.py` | 콘솔 로그, 비용 리포트 |
| F8 | M08-02 | 테스트·자체 검증 | `tests/test_pipeline.py` + 각 모듈 `_selftest` | pytest 결과 |

원본 대비 합친 것: 가격 수집 어댑터·정규화기·Repository·구성종목 수집기(M02-01~05) → **M02-01 하나**(parquet 캐시가 Repository 역할). 종목 선정·비중·제약 규칙·전략 실행기(M03-01~04) → **M03-04(선정)와 M04-02/04(비중)** 로 분리 재배치. Spec 정적·비중 동적·일치성 검사기(M04-01~03) → **M00-02 스키마 + M05-03 규칙 검증 + M06-02 안의 숫자 대조**. 무위험수익률 제공자(M05-03) → `backtest_config.RISK_FREE_RATE` 상수(M00-01). 근거 생성기·Report 조립기(M06-01/02) → **M06-02**. 실행 기록기·파이프라인 실행기(M08-01/02) → **M08-01**.

## 실행 흐름

```
[1회]  M02-01 데이터 수집 (가격 15년·재무·환율) → M02-02 디스크립터 생성
run_pipeline.py --request <01.jsonc> --backtest-request <02.jsonc> [--news --web-evidence <json>] --stop-at 14
 1. M01-01 요청 정규화 (01) → M03-01 의도 해석 🤖 (02) → M03-02 후보 검색 (03) → M03-03 후보 분류 🤖 (04) → M03-04 스크린·선정 (05, 선택 06 🤖)
 2. M04-01 백테스트 사양·재선정 (07) → M04-02 시장모형·템플릿 (08) → M04-03 뷰 생성 🤖 (09) → M04-04 BL 타겟 (10)
    [--news] M04-05 뉴스 근거 창 (09a) → M04-06 walk-forward 🤖 (10w) · 현재 구성 🤖 (10f)
 3. M05-01 백테스트 (11, 지표는 M05-02) → M05-03 규칙 검증·추천·대안 (12)
 4. M06-01 결과 통합 (13) → M06-02 리포트 문서 🤖 (14) → M06-03 노트북 (build_notebook.py)
 (모든 단계: M00-02 스키마로 검증한 뒤 output/NN_*.json 저장. 경고는 warnings 에 쌓여 13·14 까지 전달. 복구 불가면 SystemExit 로 중단)
```

## 디렉터리 구조 (실제)

```
MyFinSight/
  .env                      OPENAI_API_KEY, NEWS_DB_* (git 제외, .env.example 참고)
  docs/                     이 문서
  module_mockup/
    input/                  01_user_request.*.jsonc, 02_backtest_request.*.jsonc, news_web_evidence.*.json
    prompts/<stage>/        system_prompt.md + user_prompt.md ({{변수}} 템플릿)
    stubs/<stage>.example.json   LLM 기대 응답 (stub 모드)
    scripts/                단계 스크립트 + common.py, schemas.py, llm.py, llm_config.py, portfolio.py, portfolio_config.py,
                            backtest_engine.py, backtest_metrics.py, backtest_config.py, metrics.py, descriptor.py, report_blocks.py
    data/reference/         gics_taxonomy.json (GICS 163 세부산업 × 4단계)
    data/processed/         sp500_nasdaq100_descriptor.json (디스크립터)
    output/                 단계별 JSON, prompts/, llm_raw/, llm_cache/, llm_usage.jsonl (git 제외)
    notebooks/              results_overview.ipynb
    tests/                  test_pipeline.py
~/.venvs/myfinsight/        Python 3.13 가상환경 (저장소 밖)
~/.myfinsight/data/raw/     prices.parquet, benchmarks.parquet, fx_KRWX.parquet, info_snapshot.json, statements_*.parquet, dividends.parquet, news_cache/
```

## 추적표 (모듈 → 원본 FR)

원본 요구사항 번호를 그대로 쓴다. LLM 모듈은 원본 범위 밖(F7)이었으므로 FR 번호를 새로 붙여야 한다 🔶.

| 모듈 | FR | 비고 |
| --- | --- | --- |
| M01-01 | FR01 | 투자조건 입력·검증 |
| M02-01, M02-02 | FR04, FR05 | 데이터 수집·출처 기록, 데이터 부족 종목 제외 |
| M03-01, M03-03, M04-03, M06-02(LLM 부분), M00-03 | F7 (FR 🔶) | 자연어 해석·분류·뷰·서술 |
| M03-02, M03-04, M04-01 | FR08 | 종목 선정 규칙 |
| M04-02, M04-04, M04-05, M04-06 | FR08, FR10 | 비중 결정, 표시=실행(같은 함수로 기준일·백테스트 비중 생성) |
| M00-02, M05-03 | FR09, FR25 | 스키마·규칙 검증, 불일치 차단 |
| M05-01, M05-02, M00-01 | FR11, FR12 | 백테스트, 계산 조건 기록 |
| M06-01, M06-02, M06-03 | FR14, FR26 | 리포트, 수치 근거·출처 |
| M08-01, M08-02 | FR24, FR25 | 실행 기록, 오류 시 중단 |

# 2. 모듈별 상세 명세

## 공통 제약 (모든 모듈)

| ID | 제약 |
| --- | --- |
| C-01 | Python **3.13**(x86_64, `~/.venvs/myfinsight`). 주요 의존성: pandas, numpy, pyarrow, pydantic v2, yfinance, bt, scipy, scikit-learn, sqlalchemy + psycopg, openai, nbconvert |
| C-02 | 단계 사이의 데이터는 **`output/NN_*.json` 파일**로만 주고받는다. 쓰기 전에 `schemas.py`의 해당 모델로 검증한다(검증 실패 = 그 단계 실패). 가격·재무는 parquet 캐시(「파일 계약」) |
| C-03 | **결정론:** LLM 외에는 난수를 쓰지 않는다. LLM은 stub 모드면 완전 결정적이고, api 모드는 프롬프트 해시 캐시(`output/llm_cache/`) 덕에 같은 입력이면 재실행 결과가 같다 |
| C-04 | **통화:** 계산은 USD. 원화 금액은 표시용이며 기준일의 `KRW=X` 종가로 환산하고 환율·기준일·출처를 함께 기록한다. 백테스트 초기자본은 창 시작일 환율로 다시 환산한다 |
| C-05 | **선견 금지:** 기준일 `as_of`의 선정·추정에는 `as_of` 이전 데이터만 쓴다. 뉴스 뷰는 기준일 직전 14일 헤드라인만 근거로 쓰고, 뉴스 없는 정적 뷰는 `hindsight_risk: true`로 표시한다 |
| C-06 | **LLM 역할 한정:** LLM은 종목을 직접 고르지 않고(분류·해석만), 계산에 쓰이는 숫자를 만들지 않는다. LLM 출력은 JSON으로 받아 스키마 검증·범위 클리핑을 거치고, 실패하면 오류 메시지를 되먹여 **1회 재시도**한다 |
| C-07 | **수치 생성 금지:** 리포트 서술의 모든 숫자는 `13_results.json`에 있는 값이어야 한다. M06-02가 서술 속 숫자를 결과값 집합과 대조해 없는 숫자는 경고로 남긴다 |
| C-08 | **자격 증명:** `OPENAI_API_KEY`, `NEWS_DB_*`는 저장소 루트 `.env`(git 제외)에만 둔다. 코드·출력·로그에 비밀번호를 쓰지 않는다. 뉴스 DB는 읽기 전용 계정으로만 접속한다 |
| C-09 | **오류:** 복구 불가면 `SystemExit("[stageN] 사유")`로 중단하고 `run_pipeline.py`가 그대로 멈춘다. 복구 가능한 문제(종목 제외, 값 클리핑, stub 불일치 등)는 그 단계 JSON의 `warnings`에 기록해 13·14단계까지 전달한다 |
| C-10 | **설정 분리:** 경로는 `common.py`, 모델·단가·토큰 한도는 `llm_config.py`, 구성 파라미터는 `portfolio_config.py`, 백테스트·검증 파라미터는 `backtest_config.py`. 단계 스크립트에 상수를 박지 않는다 |
| C-11 | **테스트:** `pytest tests -q`는 `output/`의 현재 산출물로 불변식을 검사한다(네트워크·LLM 호출 없음). `MYFINSIGHT_TEST_RUN=1`이면 전체 파이프라인을 다시 돌린다 |
| C-12 | **환경:** 가상환경·데이터 캐시·저장소는 Google Drive 밖(로컬)에 둔다. Drive 안에서는 Python·git이 멈춘다 |

### 파일 계약

- **단계 JSON:** 모든 파일에 `request_id`, `stage`, `warnings: list[str]`가 있다. 날짜는 `YYYY-MM-DD`, 비율은 소수(0.152 = 15.2%), 금액은 USD 실수.
- **가격 캐시** `prices.parquet`: 긴 표(long) 형식 `date, ticker, open, high, low, close, adj_close, volume`. 518종목, 약 15년. `benchmarks.parquet`도 같은 형식(SPY, QQQ, XLV, IWM, ^GSPC, ^NDX). 백테스트·지표는 `adj_close`(배당 재투자 반영)를 쓴다.
- **환율** `fx_KRWX.parquet`: `date, close`(1 USD당 KRW).
- **재무** `info_snapshot.json`(종목별 현재 시점 약 60개 필드: sharesOutstanding, marketCap, longBusinessSummary …), `statements_quarterly.parquet` / `statements_annual.parquet`(`ticker, period_end, statement, item, value`), `dividends.parquet`.
- **디스크립터** `sp500_nasdaq100_descriptor.json`: `companies[ticker] = {name, indices, gics{sector, industry_group, industry, sub_industry: {code, name}}, keywords, company_summary, sources}` + `taxonomy_counts`.

## 공통 기반 (M00)

### M00-01 설정·경로

- **한 줄 설명:** 경로·파라미터·자격 증명을 한곳에 모아 두는 모듈.
- **Input:** 환경변수 `MYFINSIGHT_DATA`(데이터 캐시 위치, 기본 `~/.myfinsight/data`), `MYFINSIGHT_LLM`(stub|api), `MYFINSIGHT_RUN_ID`, 루트 `.env`
- **Process:** `common.py`가 `ROOT/INPUT/OUTPUT/PROMPTS/STUBS/REFERENCE/PROCESSED/RAW/DESCRIPTOR_PATH`를 정의하고 `load_jsonc`(주석 제거), `load_json/dump_json`, `render_template`, `load_dotenv`(따옴표·인라인 주석 제거)를 제공. `portfolio_config.py`: 추정 창 756거래일, 종목당 최소 252수익률, Ledoit-Wolf 수축, τ=0.05, 위험회피 δ 모드 `market_implied`(성향 배수 보수 1.5 / 중립 1.0 / 공격 0.7), 최소 비중 1%, 뷰 수익률 범위(절대 −50%~+100%, 상대 0~+50%), 템플릿 4개, 뉴스 창 14일·종목당 10건·최소 3종목. `backtest_config.py`: 수수료 5bp, 소수 주식 허용, 무위험 4%, 거래일 252, 드리프트 허용 25%, 2주=10거래일, 체크포인트 = 리밸런싱일 + 종료일, 낙폭 이벤트 −10%/−20%, 변동성 밴드(low 15% / medium 30% / high 무제한)
- **Output:** 모듈 상수 (다른 스크립트가 import)
- **성공·평가 기준:** 설정값이 `13_results.json`의 `parameters`에 그대로 실려 리포트 「분석 조건」표에 나온다 / `.env`가 없거나 키가 없으면 api 모드·뉴스 단계만 실패하고 stub 모드는 동작
- **제약:** 비밀값은 `.env`에만(C-08). 값을 바꾸면 재실행 결과가 달라지므로 변경 시 PR 설명에 남긴다

### M00-02 단계 스키마 (Pydantic)

- **한 줄 설명:** 모든 단계의 출력 형식을 코드로 못 박아, 다음 단계(와 LLM stub)가 안심하고 읽게 하는 계약.
- **Input / Output:** 없음 (각 단계가 import해 쓰기 직전에 검증)
- **Process:** `schemas.py`에 단계별 모델을 둔다. 핵심 모델과 검증 규칙:
    - `UserRequest`(01 입력): `Profile`, `Capital`, `Horizon`, `Risk`, `Constraints`, `StrategyPreference`, `NaturalLanguage`. **HARD 규칙** — `num_holdings.min ≤ target ≤ max`, `max_weight_per_stock × num_holdings.min ≥ 1`(비중 합 1 가능), `max_weight_per_sector ≥ max_weight_per_stock`, `must_include ≤ num_holdings.max`, 포함·제외 종목 충돌 금지. 리밸런싱은 `{count, unit ∈ 2w|1m|1q|6m|1y}`
    - `NormalizedRequest` = 요청 + `Derived`(기준일, 환율·날짜, USD 환산액, 리밸런싱 규칙, 가격 데이터 범위)
    - `IntentSpec`(02): `Theme.gics_codes`는 2/4/6/8자리 숫자만, `Screen.metric/direction`은 템플릿별 고정표 `TEMPLATE_METRICS`(low_per→pe_ttm↑, quality→roe_ttm↓, momentum→return_12m_1m↓, low_volatility→vol_60d↑, high_dividend→dividend_yield_ttm↓)와 일치해야 함
    - `Candidates`(03), `Tagging`(04), `Selection`(05, `infeasibility` 선택), `BacktestRequest`(02 백테스트 요청: 시작일 < 종료일), `BacktestSpec`(07)
    - `MarketModel`(08), `Portfolio`(비중 + 현금 = 1 ± 1e-4, 음수 금지), `View`(상대 뷰는 short 필수, 절대 뷰는 short 금지, 양쪽에 같은 종목 금지, `evidence_ids`), `Views`, `TargetPortfolios`(10)
    - `PortfolioResult`·`BacktestResults`(11: 모든 시계열 길이 = `series_dates` 길이), `Checkpoint`
    - `Check`(level hard|soft|info, status pass|warn|fail|info), `Validation`(12)
    - `ResultsBundle`(13: 백테스트 포트폴리오 id 집합 = 정적 타겟 ∪ walk-forward, 원화 환산표가 포트폴리오·비교지수·대안을 모두 덮음), `ReportDoc`(14: 블록 타입 집합, KPI id·시리즈 id 참조 무결성, nav = sections)
- **성공·평가 기준:** 모든 `output/*.json`이 해당 모델로 다시 읽힌다(테스트 `test_results_bundle_and_report`) / 잘못된 입력(예: 종목 상한 5% × 최소 10종목)은 01단계에서 바로 거부
- **제약:** 스키마를 바꾸면 그 필드를 읽는 단계·프롬프트·노트북을 함께 고친다. stub 파일도 새 스키마를 통과해야 한다

### M00-03 LLM 호출기 🤖

- **한 줄 설명:** 모든 LLM 호출이 지나가는 단 하나의 문. 프롬프트 렌더링, stub/api 전환, 캐시, 재시도, 비용 기록을 맡는다.
- **Input:** `load_prompts(stage_dir, **vars)` → `prompts/<stage>/system_prompt.md`, `user_prompt.md`의 `{{변수}}` 치환. `call_llm(stage, system, user, batch=None, stub_file=None, validator=None)`
- **Process**
    1. 렌더링된 프롬프트를 항상 `output/prompts/<stage>[_b<i>].md`로 저장(검토용)
    2. **stub 모드**(기본): `stubs/<stage>.example.json` 반환. 배치 단계는 자기 티커 부분집합만 꺼내 쓰고, 없는 티커는 경고 후 "미분류"
    3. **api 모드**(`MYFINSIGHT_LLM=api`): OpenAI chat completions, 모델 `gpt-6-luna`(추론 모델이라 temperature 생략, `response_format=json_object`), 단계별 출력 토큰 한도(기본 8000, 00·04·09 6000, 14b 10000), 타임아웃 180초, 연결·속도제한 오류는 15초 간격 3회 재시도
    4. **캐시:** `sha256(model + stage + system + user)` → `output/llm_cache/<key>.json`. 같은 프롬프트는 호출하지 않는다(`MYFINSIGHT_LLM_CACHE=0`으로 끔)
    5. **검증·재시도:** JSON 파싱 실패 또는 `validator` 예외 → 그 오류 문장을 사용자 메시지로 덧붙여 **1회** 다시 호출. 그래도 실패하면 단계 실패
    6. **기록:** `output/llm_usage.jsonl`에 호출마다 한 줄(run_id, stage, 토큰·캐시 토큰·추론 토큰, 비용 USD, 소요 시간, finish_reason), 원문 응답은 `output/llm_raw/`
- **Output:** 파싱된 JSON dict
- **성공·평가 기준:** stub 모드에서 전 파이프라인이 API 키 없이 끝까지 돈다 / api 모드 요청 1건(02+04+06) ≈ $0.008, 리포트(14a+14b) ≈ $0.012, 뉴스 시나리오 전체 ≈ $0.03 / 같은 run을 두 번 돌리면 두 번째는 전부 cache hit
- **제약:** 모델명·단가는 `llm_config.py`에서만 바꾼다. 프롬프트는 "JSON 객체 하나만, 코드블록 없이"를 요구하고 출력 스키마 예시를 포함한다
- **오류:** 키 없음 → `SystemExit`(api 모드만), 재시도 후 실패 → 단계 중단

## F1 사용자 투자조건 관리

### M01-01 요청 정규화·검증기

- **한 줄 설명:** 사람이 쓴 JSONC 요청을 읽어 HARD 규칙을 검사하고, 이후 단계가 쓸 파생값(환율·USD 금액·리밸런싱 규칙·데이터 범위)을 붙인다.
- **FR:** FR01
- **Input:** `input/01_user_request.*.jsonc`(부록 A), 가격 캐시(데이터 범위), 환율 캐시, 선택 `--fx-rate`
- **Process**
    1. `load_jsonc` → `UserRequest` 검증(M00-02의 HARD 규칙). 위반 시 Pydantic 오류 메시지와 함께 중단
    2. 기준일 `as_of = horizon.start_date`. 환율: 캐시(7일 이내) → yfinance `KRW=X` → `--fx-rate` 수동값(출처 `manual_placeholder`로 표시)
    3. `initial_amount_usd`, `monthly_contribution_usd` 환산. 리밸런싱 규칙: `2w`는 `trading_days = 10 × count`, 나머지는 달력 기준(`month_start` 등). `count = 0`이면 "매수 후 보유"
    4. 가격 데이터 시작·끝 날짜 기록
- **Output:** `01_request.json`(`NormalizedRequest`)
- **성공·평가 기준:** 예시 요청 2개(AI, 헬스케어) 통과 / 상한 불가능·포함-제외 충돌 입력은 중단 / `derived.fx_source`가 리포트에 표시됨
- **제약:** 입력 파일을 수정하지 않는다. [SOFT] 항목은 여기서 해석하지 않고 그대로 넘긴다
- **오류:** 스키마 위반 → 중단, 환율 조회 실패 + 수동값 없음 → 중단

## F2 금융 데이터 관리

### M02-01 시장 데이터 수집·캐시

- **한 줄 설명:** yfinance에서 유니버스 가격 15년치·비교지수·환율·재무를 한 번 받아 로컬 parquet로 보관한다(원본의 어댑터·정규화·Repository·구성종목 수집기를 합친 것).
- **FR:** FR04, FR05
- **Input:** Wikipedia 구성종목 목록 페이지(S&P 500, NASDAQ-100), yfinance, `--years 15`, `--workers`
- **Process**
    1. `fetch_data.py`: 두 지수 구성종목 합집합(518종목) → `universe.json`(티커, 이름, 지수, 섹터·산업). NASDAQ 전용 15종목은 ICB 분류라 GICS로 수동 매핑. 티커 표기는 yfinance식(`BRK-B`)
    2. 일별 OHLCV를 배치로 내려받아 `prices.parquet`, 비교지수 6개는 `benchmarks.parquet`, 환율은 `fx_KRWX.parquet`
    3. `fetch_fundamentals.py`: 종목별 `info` 스냅샷, 분기 5개·연간 4개 재무제표, 배당 이력. Yahoo 429(요청 제한)가 나면 120초 × 최대 6회 대기, 종목별 pickle 캐시로 이어받기. 실패 종목은 `fundamentals_log.json`
    4. 가격 데이터가 짧은 종목은 여기서 제외하지 않고 **쓰는 쪽**이 판정한다(M03-02: 기준일 전 400일 이상, M04-02: 추정 창 안 252수익률 이상)
- **Output:** 「파일 계약」의 캐시 파일들(`~/.myfinsight/data/raw/`)
- **성공·평가 기준:** 518/518 종목 재무 수집 완료 / 재실행 시 캐시가 있으면 네트워크 호출 없음 / 환율·가격 범위가 `01_request.json`에 기록됨
- **제약:** 네트워크 호출은 이 모듈(과 M01-01의 환율 보충, M04-05의 DB 조회)에서만. 원본 응답을 가공해 저장하되 열 이름을 바꾸지 않는다. 캐시는 git·Drive 밖
- **알려진 한계:** 구성종목은 **현재 시점 스냅샷**이라 과거 백테스트에 생존 편향이 있다(리포트 「전제와 한계」에 고정 문구). yfinance 재무는 분기 5개까지라 `low_per`·`quality` 템플릿은 최근 약 4년만 as-of 계산 가능 🔶K6

### M02-02 유니버스 디스크립터 생성기 (🤖 선택)

- **한 줄 설명:** 종목마다 GICS 4단계 태그·키워드·한 줄 소개를 붙인 사전을 미리 만들어, LLM에 종목 표를 넘기지 않고도 테마→종목 검색이 되게 한다.
- **FR:** FR04 (F7 보조)
- **Input:** `universe.json`, `info_snapshot.json`(longBusinessSummary), `data/reference/gics_taxonomy.json`(Wikipedia GICS 163 세부산업 × 섹터·산업그룹·산업·세부산업 코드, `--refresh-taxonomy`로 갱신), 선택 `descriptor_llm_overrides.json`
- **Process**
    1. 종목의 섹터·산업명을 GICS 코드(2/4/6/8자리)로 정규화
    2. 한 줄 소개 우선순위: **LLM #0 결과**(`stage0_descriptor_llm.py`, 오프라인·선택, 한국어 요약 + 키워드) > yfinance 사업 설명 첫 문장 > 규칙("회사명 — 세부산업")
    3. 키워드: LLM 결과 또는 GICS 이름에서 뽑은 구절
    4. `descriptor.py` 헬퍼: `filter_by_gics(codes)`(코드 접두 일치), `search_keywords(words)`(단어 경계 일치), `sector_name_to_code`, `parents_of`(한 단계 위 코드)
- **Output:** `data/processed/sp500_nasdaq100_descriptor.json`(git 포함)
- **성공·평가 기준:** 518종목 전부 4단계 코드·이름 보유 / `taxonomy_counts`가 섹터 11·산업그룹 25·산업 74 범위 안 / 요약 출처(`sources.summary`)가 종목별로 남아 리포트 선정표에 표시
- **제약:** 디스크립터도 현재 시점 스냅샷(생존 편향). 규칙 기반 요약만 있는 종목은 키워드 오탐이 많으므로 M03-03(LLM 분류)이 걸러야 한다

## F3 자연어 전략 생성·종목 선정

> 공통: LLM이 하는 일은 **해석(02)과 분류(04)** 뿐이다. 후보를 찾는 것(03)과 순위를 매겨 고르는 것(05)은 코드가 한다. 그래서 같은 입력이면 같은 종목이 나오고, 왜 뽑혔는지 지표값으로 설명할 수 있다.

### M03-01 의도 해석기 🤖 (LLM #1)

- **한 줄 설명:** 자연어 아이디어와 [SOFT] 항목을 읽고, "어떤 산업(GICS 코드·키워드)의, 어떤 템플릿으로, 어떤 위험 기준으로" 고를지 기계가 읽을 수 있는 `IntentSpec`으로 바꾼다.
- **FR:** F7 🔶
- **Input:** `01_request.json`, 원본 JSONC 텍스트(주석 포함, [SOFT] 해석 힌트), 디스크립터에서 만든 **GICS 분류 트리**(섹터→산업그룹→산업→세부산업, 코드·이름·종목 수. 종목 표는 주지 않는다), 프롬프트 `prompts/02_intent/`
- **Process**
    1. 프롬프트 렌더링 → `call_llm("02_intent", validator=_check)`
    2. LLM 출력: `interpretation`(요약, 테마 ≥ 1: id·설명·`gics_codes`·`keywords`·`example_tickers`, 스타일 힌트, 상충 항목과 해결), `exclude_theme_rules`(제외 테마의 코드·키워드), `screen`(템플릿·지표·방향·기준일·테마 신뢰도 하한 0.5·`select_top_n`), `risk_params`(실효 최대낙폭 — `loss_reaction = sell`이면 낮춤, 변동성 선호), `news_tilt`(뷰 신뢰도 상한, 종목당 최대 조정폭), `validation_criteria`, `report_settings`
    3. `IntentSpec` 검증(코드 자릿수, 템플릿-지표 일치). 유니버스에 없는 예시 티커는 경고 후 제거(예: NVO)
- **Output:** `02_intent.json`
- **성공·평가 기준:** AI·헬스케어 요청에서 테마가 GICS 코드로 표현됨(AI: 반도체 453010·IT서비스 451020…, 헬스케어: 제약 35202010·바이오 35201010·의료장비 35101010·헬스케어 서비스 351020xx) / 스키마 위반 시 1회 재시도로 복구 / 비용 ≈ $0.003
- **제약:** LLM은 티커를 "예시"로만 줄 수 있고 검색은 코드·키워드로 한다(C-06). 템플릿은 사용자가 고른 값을 바꾸지 않는다
- **오류:** 재시도 후에도 스키마 실패 → 중단

### M03-02 후보 검색기

- **한 줄 설명:** `IntentSpec`의 코드·키워드로 디스크립터를 뒤져 후보 120개 이하를 만들고 HARD 필터를 적용한다(원본 Universe 구성기).
- **FR:** FR08
- **Input:** `02_intent.json`, `01_request.json`, 디스크립터, 가격 캐시, `info_snapshot.json`, 선택 `--as-of`(백테스트 재선정용)
- **Process**
    1. 테마별 매칭 → 합집합. `gics_match`(8자리 코드가 선택 코드로 시작), `keyword_match`(이름·키워드·요약에 단어 단위 일치; **키워드로만** 걸린 종목은 서로 다른 키워드 2개 이상), `example_match`(LLM 예시 티커). 매칭 근거를 `matched_by`, `matched_keywords`에 남김
    2. HARD 필터: `exclude_tickers`, `exclude_sectors`, `exclude_theme_rules`(코드·키워드), `asset_types`, `min_market_cap_usd`(발행주식수 × 기준일 종가. 스냅샷 없으면 경고 후 생략), `min_avg_daily_volume_usd`(기준일 전 60거래일 평균), 기준일 전 **400일 이상** 가격 이력. `must_include_tickers`는 `forced`로 강제 포함
    3. 후보 수 < 목표 종목 수면 각 코드를 한 단계 위로 넓혀 1회 재검색. 120개 초과면 매칭 규칙 수 → 거래대금 순으로 자름
- **Output:** `03_candidates.json`(후보, 제외 목록과 사유, 통계: 깔때기 숫자)
- **성공·평가 기준:** 약한 키워드 매칭(1개)만으로 들어온 후보가 없다(테스트 `test_candidates_no_weak_keyword_hits`) / 같은 입력 → 같은 후보 / 제외 사유가 리포트 깔때기에 표시
- **제약:** 순수 코드. 디스크립터가 현재 스냅샷이므로 과거 기준일(`--as-of`)에도 같은 종목 집합을 쓴다(생존 편향, 한계로 표시)

### M03-03 후보 분류기 🤖 (LLM #2)

- **한 줄 설명:** 후보 하나하나가 정말 사용자의 테마에 해당하는지, 제외 테마(담배·도박 등)에 걸리는지 LLM이 40개씩 묶어 판정한다.
- **FR:** F7 🔶
- **Input:** `03_candidates.json`, `02_intent.json`, 프롬프트 `prompts/04_classify/`
- **Process**
    1. 후보를 40개 배치로 나눠 배치마다 호출(배치 번호·총수·종목 표: 티커·이름·GICS·요약·매칭 키워드 + 테마 설명)
    2. LLM 출력 `results[{ticker, in_theme, themes, confidence 0~1, reason_ko, excluded_theme}]`
    3. 통과 조건: `in_theme` 이고 `confidence ≥ screen.theme_filter.min_confidence`(0.5) 이고 `excluded_theme` 없음. 응답에 없는 티커는 경고 후 미통과
- **Output:** `04_tagging.json`(`tagged`, `excluded_by_theme`, `passed_tickers`, `batches`)
- **성공·평가 기준:** 모든 후보에 판정이 있다(누락은 경고로 보임) / stub 모드에서 후보가 바뀌어도 중단하지 않는다 / 비용 ≈ $0.003 per 40개
- **제약:** 배치 안의 종목 순서와 무관하게 판정하도록 프롬프트에 명시. 사유(`reason_ko`)는 리포트 선정표에 그대로 노출되므로 투자 권유 표현 금지

### M03-04 정량 스크린·선정기 (🤖 근거 서술 선택, LLM #3)

- **한 줄 설명:** 테마를 통과한 종목에 템플릿 지표를 계산해 순위를 매기고, 종목 수·섹터 상한을 지키며 최종 종목을 고른다(원본의 선정 규칙 + 제약 적용 규칙).
- **FR:** FR08
- **Input:** `04_tagging.json`, `02_intent.json`, `01_request.json`, 가격·재무 캐시, 선택 `--as-of`
- **Process**
    1. 지표(`metrics.py`, 모두 `as_of` 이전 데이터만): `return_12m_1m` = P(t−21거래일)/P(t−252) − 1(최근 1개월 제외 12개월 수익률), `vol_60d`(60거래일 일수익률 표준편차 연환산), `pe_ttm` = 주가 / 최근 4분기 희석 EPS 합(EPS ≤ 0이면 결측), `roe_ttm`, `dividend_yield_ttm`
    2. 지표 결측 종목 제외(`must_include`는 결측이어도 유지 + 경고) → 지표·방향으로 정렬
    3. **섹터 상한을 종목 수 선호로 변환:** 섹터당 선호 종목 수 = ⌊`max_weight_per_sector` × n⌋. 1차로 섹터별 선호 수까지 뽑고, 2차로 미룬 종목(`overflow`)으로 채움. **용량 검사:** Σ_섹터 min(k_섹터 × 종목상한, 섹터상한) < 1이면 비중 합 1이 불가능 → `infeasibility`(사유, 선택지) 기록
    4. n = `num_holdings.target`(통과 종목이 부족하면 max(min, 통과 수), min 미만이면 경고)
    5. 선택 6단계: 선정 종목별 한국어 근거를 LLM이 작성(`--explain`, stub 없음 → api 전용)
- **Output:** `05_selection.json`(`selected`: 티커·이름·섹터·순위·지표값·테마 신뢰도·강제 여부, `rejected` + 사유, `summary`(깔때기·`sector_overflow`), `infeasibility`), 선택 `06_selection_explained.json`
- **성공·평가 기준:** 선정 수가 min~max 안, 상한 용량 ≥ 1(테스트 `test_selection_constraints`) / 헬스케어 예시: 후보 42 → 분류 통과 30 → 지표 보유 30 → 선정 15 / 같은 `as_of`면 같은 결과
- **제약:** 제외는 선정 **전**(03단계)에 끝나 있다. 섹터 상한이 1.0(단일 섹터 허용)이면 섹터 선호를 적용하지 않는다
- **오류:** 통과 종목 0개 → 중단

## F4 포트폴리오 구성

> 공통: 구성 수학은 전부 `portfolio.py`에 있고(`python scripts/portfolio.py`로 자체 검증), 08·10·10w·10f가 같은 함수를 부른다. 그래서 백테스트 시작일 구성과 "지금 구성" 구성이 같은 규칙으로 만들어진다(FR10 표시=실행).

### M04-01 백테스트 사양·재선정

- **한 줄 설명:** 사용자 확인과 백테스트 기간을 받아, 백테스트 **시작일 기준**으로 종목을 다시 고르고(선견 금지) 자본·리밸런싱·비교지수를 확정한다.
- **FR:** FR08, FR12
- **Input:** `input/02_backtest_request.*.jsonc`(부록 A: `confirmation`, `backtest{start_date, end_date, reselect_at_start, benchmark, include_contributions}`, `views{n_sets, views_per_set}`, `walkforward`, `forward_construction`), `01/02/04/05` 출력, 선택 `--fx-rate-bt`
- **Process**
    1. 종료일이 가격 데이터 끝보다 늦으면 데이터 끝으로 당기고 경고. 창이 데이터 범위 밖이면 중단. 거래일 수는 SPY 달력으로 센다
    2. `reselect_at_start`면 날짜에 의존하지 않는 LLM 결과(02 테마, 04 분류)는 재사용하고, 결정적 단계만 `as_of = start_date`로 다시 실행: `stage3_retrieve.py --as-of` → `stage5_screen.py --as-of`(산출물 `07_*_bt.json`). 원래 선정과의 차이(`diff_vs_original`)를 기록
    3. 사용자 확인의 `removed/added_tickers` 반영. `benchmark`가 null이면 요청의 비교지수(SPY)
    4. 초기자본·월 적립을 **시작일 환율**로 다시 환산(`capital.fx_rate/fx_date/fx_source`)
- **Output:** `07_backtest_spec.json`(`period`, `capital`, `rebalance_rule`, `benchmark`, `selection`(출처·지표·종목·표·차이·infeasibility·sector_overflow))
- **성공·평가 기준:** 헬스케어 예시: 10/8 선정 15종목 vs 9/8 재선정 15종목이 일부 다름(10/8의 VTRS·DXCM ↔ 9/8의 UNH·ELV)이 표로 보임 / 종료일 clamp 경고가 리포트까지 전달
- **제약:** 재선정은 종목만 바꾸고 테마 해석은 바꾸지 않는다(분류 LLM 재호출 없음 🔶K7)

### M04-02 시장모형·템플릿 비중

- **한 줄 설명:** 기준일 이전 3년 수익률로 공분산·시가총액 비중·내재 기대수익률을 추정하고, 규칙 템플릿 4개의 비중을 만든다.
- **FR:** FR08, FR10
- **Input:** `07_backtest_spec.json`(종목·기준일), `01_request.json`(상한·성향), `02_intent.json`, 디스크립터(섹터), 가격·`info_snapshot`. 함수형 진입점 `build_market_model(tickers, as_of, req, …)`(10w·10f가 재사용)
- **Process**
    1. 추정 창: 기준일 전 **756거래일** 일수익률. 창 안에 252개 미만인 종목은 모형에서 제외 + 경고
    2. 공분산 Σ: **Ledoit-Wolf 수축**(표본 공분산을 구조화 행렬 쪽으로 당겨 추정 오차를 줄임), 연변동성·상관 함께 저장
    3. 시가총액 비중 ≈ 현재 발행주식수 × 기준일 종가(근사, 한계로 표시)
    4. 위험회피계수 δ: **시장 내재** = SPY 초과수익 평균 / 분산(같은 창) × 성향 배수(보수 1.5 / 중립 1.0 / 공격 0.7). 내재 기대수익률 π = δ Σ w_기준(기준 = 사용자가 고른 `baseline_weighting`, 기본 동일비중), τ = 0.05
    5. 템플릿 4개: 동일비중, 시가총액비중, 역변동성(1/σ 정규화), 최소분산(제약 포함 최적화). 공통 제약: 종목 상한, 섹터 상한, **최소 비중 1%**(종목 수 유지), 상한 초과분을 나머지에 비례 재분배(최대 50회). 섹터 상한이 1.0이면 제약을 걸지 않음(최적화기 호환)
    6. 사전(ex-ante) 통계: 기대수익·변동성·Sharpe·유효 종목 수, 섹터 비중
- **Output:** `08_market_model.json`, `08_baseline_portfolios.json`(`chosen_baseline`, 템플릿 4개)
- **성공·평가 기준:** 모든 템플릿 비중 합 1, 각 비중 ∈ [1%, 종목상한], 섹터 합 ≤ 섹터상한(테스트 `test_target_portfolios_constraints`) / `portfolio.py` 자체 검증 통과 / 단일 섹터(헬스케어, 섹터상한 1.0)에서도 최적화가 수렴
- **제약:** `as_of` 이후 데이터 사용 금지. 시총 비중은 근사이므로 리포트에 명시

### M04-03 뷰 생성기 🤖 (LLM #4)

- **한 줄 설명:** Black-Litterman에 넣을 "어느 종목이 얼마나 더/덜 오를 것 같은가"(뷰)를 시나리오 5세트 × 4개로 LLM이 쓰고, 코드가 범위를 검증·클리핑한다.
- **FR:** F7 🔶
- **Input:** `07/08` 출력(종목 표: 이름·섹터·연변동성·내재수익률·기준 비중), `02_intent.json`(테마 요약, `news_tilt.max_view_confidence`), 백테스트 요청의 `views{n_sets, views_per_set}`, 프롬프트 `prompts/09_views/`(정적) 또는 `prompts/09_views_news/`(뉴스 근거). 함수형 진입점 `generate_views(tickers, as_of, mm, base_weights, intent, n_sets, per_set, max_conf, evidence=None, …)`
- **Process**
    1. LLM 출력 `sets[{scenario_id, title_ko, narrative_ko, views[…]}]`. 뷰 = `absolute`(종목 X의 연 기대수익 r) 또는 `relative`(long 바스켓이 short 바스켓을 연 r만큼 앞섬), `confidence`, `horizon_months`, `rationale_ko`, `evidence_type`, `evidence_ids`
    2. **가드레일(코드):** 표에 없는 티커 → 뷰 삭제, 중복 뷰 삭제, confidence를 [0.1, 상한]으로 클리핑, 기대수익을 범위(절대 −50%~+100%, 상대 0~+50%)로 클리핑, 세트당 뷰 수 초과분 절단, 세트 수 불일치 경고
    3. **뉴스 변형 추가 규칙:** 뷰마다 `evidence_ids` ≥ 1이고 전부 실존해야 함(없으면 삭제), 뉴스 없는 종목의 절대 뷰 삭제, 근거 1건이면 confidence ≤ 0.3, 헤드라인에 없는 숫자 금지, 기준일 이후 정보 금지, `origin`(db / web_search) 구분 인용
    4. 정적 뷰는 `hindsight_risk: true`(뉴스 없이 LLM 기억으로 쓴 뷰라 사후 정보가 섞일 수 있음)
- **Output:** `09_views.json`(정적), 또는 10w·10f가 날짜별로 받는 세트
- **성공·평가 기준:** 모든 뷰가 `View` 스키마 통과 / 뉴스 뷰는 전부 근거 id 인용(테스트 `test_news_stages_if_present`) / 비용 ≈ $0.002 per 호출
- **제약:** 뷰는 "방향과 크기의 가설"이지 예측이 아니며, 신뢰도 상한(`max_view_confidence`)을 넘지 못한다. 저정보 헤드라인(실적 발표일 공지 등)으로 절대 뷰를 만드는 사례가 관찰됨 🔶K2

### M04-04 Black-Litterman 타겟

- **한 줄 설명:** 기준 비중(내재수익률)에 뷰를 섞어 사후 기대수익률을 구하고, 상한과 조정폭 제약 안에서 효용을 최대화한 타겟 비중을 세트마다 하나씩 만든다.
- **FR:** FR08, FR10
- **Input:** `08` 두 파일, `09_views.json`, `07/01/02`. 함수형 진입점 `build_bl(mm, base, view_sets, req, intent, …)`
- **Process**
    1. 뷰 → P(선택 행렬), Q(기대수익 벡터). 절대 뷰는 종목 한 줄, 상대 뷰는 long 양(+)·short 음(−) 비중
    2. Ω(뷰 불확실성): **He-Litterman 신뢰도 방식** Ω_kk = (1/c_k − 1)·p_k(τΣ)p_kᵀ. 신뢰도가 높을수록 Ω가 작아 뷰가 강하게 반영
    3. 사후 기대수익률 μ_BL = [(τΣ)⁻¹ + PᵀΩ⁻¹P]⁻¹ [(τΣ)⁻¹π + PᵀΩ⁻¹Q]
    4. 최적화(SLSQP): max μ_BLᵀw − (δ/2)wᵀΣw, 제약 Σw = 1, 1% ≤ w_i ≤ 종목상한, 섹터 합 ≤ 섹터상한, **|w_i − w_기준,i| ≤ `max_tilt_per_stock`(0.05)**. 기준 비중은 합 1로 정규화 후 사용
    5. 포트폴리오마다 시나리오 제목·서술, 적용된 뷰(근거 id 포함), 기준 대비 변화량, 사후 수익률, 활성 제약, 사전 통계 기록
- **Output:** `10_target_portfolios.json`(BL 5개 + 템플릿 4개 + `backtest_spec` + `parameters`(τ, δ, Ω 방식, 조정폭, 상한, 최소 비중) + 기준 포트폴리오) — **백테스트의 유일한 입력**
- **성공·평가 기준:** 모든 타겟이 상한·최소 비중·조정폭 제약을 만족(테스트) / `portfolio.py` 자체 검증: 뷰 방향대로 비중이 움직이고, 뷰가 없으면 기준 비중으로 수렴 / 헬스케어 예시 BL 조정폭 최대 5%p
- **제약:** 롱 온리, 레버리지·현금 없음(현금 혼합은 M05-03의 대안으로만). 뷰가 모두 삭제된 세트는 기준 비중 + 경고

### M04-05 뉴스 근거 수집기

- **한 줄 설명:** 구성 날짜마다 직전 14일 헤드라인을 팀 DB(와 필요하면 웹 검색 보충 파일)에서 모아, 뷰가 인용할 수 있는 근거 id 목록으로 만든다.
- **FR:** FR04, FR26
- **Input:** `.env`의 `NEWS_DB_*`(호스트·reader 계정·비밀번호, DB `myfinsight`, SSL), `07_backtest_spec.json`(리밸런싱 날짜·재선정 종목), `05_selection.json`(현재 종목), 백테스트 요청(walk-forward·현재 구성 플래그), 선택 `--web-evidence input/news_web_evidence.*.json`
- **Process**
    1. `news_db.py`: SQLAlchemy 읽기 전용 엔진. `fetch_news(tickers, start, end, languages=("en",), per_ticker=10)` — `news JOIN assets`(`market='US'`, `asset_id='US-<ticker>'`), 제목 소문자 중복 제거, 최신순 종목당 10건, 결과를 `RAW/news_cache/<hash>.parquet`에 캐시. 레코드 `{evidence_id: "ev<news_id>", ticker, published_at, source, publisher, title, url, origin: "db"}`
    2. `db_probe.py`: 연결·테이블 확인(비밀번호는 출력에서 가림)
    3. `stage9a_news.py`: 날짜 목록 = walk-forward 리밸런싱일(07의 규칙으로 계산) + 현재 구성 기준일(가격 데이터 끝). 창 `[d − 14일, d)`. 웹 검색 보충 레코드(`origin: "web_search"`, 날짜·URL·제목이 실제 기사인 것만)를 같은 창·종목에 합침
    4. 창마다 `n_articles`, `n_tickers_with_news`, `enough = 뉴스 있는 종목 ≥ MIN_NEWS_TICKERS(3)`, `origin_counts`
- **Output:** `09a_news_evidence.json`(`windows{date: {kind, window, tickers{t: [id…]}, n_articles, n_tickers_with_news, enough, origin_counts}}`, `all_evidence{id: 레코드}`)
- **성공·평가 기준:** 모든 근거의 `published_at`이 창 안(테스트) / 헬스케어 예시: 9/8 창 웹 9건, 9/22 창 웹 3건, 10/6 창 DB 147건, 10/8 창 DB 148건 / 비밀번호가 어떤 산출물에도 없음
- **제약:** DB는 읽기만(C-08). 팀 DB는 헤드라인 위주(본문 중앙값 85자)이고 2026-09-27 이후만 있다 🔶K3. 웹 보충 파일은 사람이 검증한 실제 기사만 넣는다(지어내지 않음)

### M04-06 뉴스 반영 구성기 (walk-forward·현재 구성) 🤖

- **한 줄 설명:** (10w) 리밸런싱 날짜마다 시장모형·템플릿·뉴스 뷰·BL을 **그 날짜 기준으로 다시** 계산해 날짜별 비중 경로를 만들고, (10f) 가장 최근 가격·뉴스로 "지금 구성한다면"을 만든다.
- **FR:** FR08, FR10, F7 🔶
- **Input:** `07/01/02` 출력, `09a_news_evidence.json`, 백테스트 요청(`walkforward{view_sets=1, views_per_set=4}`, `forward_construction{as_of}`), M04-02~04의 함수들
- **Process (10w)** 날짜 d마다: `build_market_model(재선정 종목, d)` → 템플릿 4개(`wf_<template>`) → 창이 `enough`면 `generate_views(evidence, stage_tag=09n_wf_<d>)` → `build_bl(id_prefix=wf_bl_<d>)` → `wf_bl_news.weights_by_date[d]`, `views_by_date[d]`. 부족하면 기준 비중 사용 + `fallback_dates`에 기록
- **Process (10f)** 기준일 = `as_of` 또는 가격 데이터 끝. 종목 = **현재 선정(05)**. 창은 09a의 forward 창. 뷰 5세트 → BL 5개(`fwd_bl_*`) + 템플릿 4개. 배분 금액(USD·KRW, 기준일 환율). 백테스트 없음
- **Output:** `10w_target_paths.json`(`dates`, 포트폴리오 5개: `weights_by_date`, `views_by_date`, `fallback_dates`), `10f_forward_portfolios.json`
- **성공·평가 기준:** 날짜별 비중 합 1·최소 1%·조정폭 ≤ 5%p / 뉴스 부족 날짜는 비중 = 동일비중(테스트) / 헬스케어 예시: 9/8·9/22는 근거가 적어 조정 ≤ 1.5%p, 10/6은 5%p(HUM −5.0, DGX +4.6, LH −3.7, MCK +2.9)
- **제약:** 종목 재선정은 하지 않는다(비중만 갱신) 🔶K7. 날짜마다 LLM 1회 호출(캐시됨)

## F5 백테스트·검증

### M05-01 백테스트 시뮬레이터

- **한 줄 설명:** 타겟 포트폴리오 9개(+walk-forward 5개)와 비교지수 3개를 같은 기간·같은 적립으로 bt 라이브러리에 돌리고, 리밸런싱마다 체크포인트를 남긴다.
- **FR:** FR11, FR12
- **Input:** `10_target_portfolios.json`(종목·비중·`backtest_spec`), `10w_target_paths.json`(같은 `request_id`일 때만), `08/02/01`, 가격 캐시
- **Process**
    1. `backtest_engine.load_price_panel`: 종목 + 비교지수(SPY + QQQ·XLV)의 `adj_close`를 SPY 거래일에 맞춰 정렬, 창 = `period.start ~ end`
    2. 리밸런싱일: 규칙(`2w` = 10거래일마다, 달력 단위는 월초 등)으로 계산, **종료일 당일은 리밸런싱하지 않음**. 적립일: 매월 `contribution_day` 이후 첫 거래일
    3. 정적 포트폴리오: 리밸런싱일마다 같은 타겟 비중으로 복원(bt algos). 동적(`wf_*`): `RunOnDate + WeighTarget`으로 날짜별 타겟 표를 적용. 적립금(`ContributeOnDates`)은 들어온 날 바로 타겟 비중으로 매수. 수수료 5bp, 소수 주식 허용, 체결은 종가
    4. bt가 시작 전날에 붙이는 가짜 "전액 현금" 행은 제거하고 지수를 100으로 다시 맞춤
    5. 비교지수: 같은 시작일·초기자본·적립으로 매수 후 보유. 상대 지표와 R3는 사용자 비교지수(SPY) 기준
    6. 포트폴리오마다 M05-02로 전체 기간 지표 + 체크포인트(리밸런싱일 + 종료일)마다 비중 before/after/target, 보유·거래·회전율·수수료, 구간 성과 `since_last`, 누적 `to_date`, 뷰 진단. 적립 원장, 낙폭 이벤트(−10%/−20%), 종목별 기여도, 뷰 적중(12개월 실현 vs 기대)
    7. 창이 252거래일 미만이면 `annualized_reliable: false`, 헤드라인에 `period_return`(기간 수익률) 포함
- **Output:** `11_backtest_results.json`(`period`, `engine`, `series_dates`, `benchmark`, `benchmarks[]`, `portfolios[]`(headline·metrics·money·series·monthly/yearly·checkpoints·…), `ranking`, `reproducibility`), `11_daily_panel.parquet`
- **성공·평가 기준:** 마지막 체크포인트는 `closing`이고 `to_date` = 최종 지표, `since_last`가 연쇄로 이어짐, 마지막 날 리밸런싱 없음(테스트 `test_backtest_invariants`) / `backtest_engine.py` 자체 검증(비용 0 동일비중 = 손계산) / 같은 입력 2회 = 같은 결과
- **제약:** 공매도·레버리지 없음, 세금·슬리피지 없음, 배당은 `adj_close`로 반영된 것으로 간주. 포트폴리오가 늘어도 같은 패널·같은 날짜를 공유해야 한다(13단계 길이 검사)

### M05-02 성과 지표 계산기

- **한 줄 설명:** 평가액 시계열에서 수익·위험·위험조정·비교지수 대비·구성·거래·안정성 지표를 한 정의로 계산한다(전체 기간과 체크포인트 `to_date`가 같은 함수).
- **FR:** FR11
- **Input:** `raw`(지수·평가액·현금흐름·비중·거래), 비교지수 지수, 가격 패널, 타겟, 섹터, 리밸런싱일, 무위험수익률(4%), 목표수익률, 상한
- **Process (정의):** 일수익률 r_t = V_t/V_{t−1} − 1. `return`: total_return, cagr, best/worst month. `risk`: ann_vol = std(r)×√252, downside_deviation, max_drawdown(고점·저점·회복일 포함), worst_day, skew, kurtosis. `risk_adjusted`: sharpe = (CAGR − r_f)/ann_vol, sortino = (CAGR − r_f)/하방편차, calmar = CAGR/|MDD|. `vs_benchmark`: excess_cagr, beta, alpha_ann, correlation, tracking_error, information_ratio, up/down capture, months_outperformed_ratio. `vs_baseline`: 기준 템플릿 대비 active return/risk/IR. `composition`: effective_n, HHI, 상위 3종목 기여 비중, 평균 섹터 비중, 최대 비중·섹터 드리프트, 상한 위반(breaches). `trading`: 리밸런싱 횟수, 평균 회전율, 수수료 합. `stability`: 12개월 롤링 지표. `money`: 납입 합계, 최종 평가액, 이익, XIRR(적립 포함 연수익률), 최대 손실·최악 12개월 손실(USD). 월별·연도별 수익률
- **Output:** dict(11단계 `metrics`, `money`, `monthly_returns`, `yearly_returns`에 그대로 들어감)
- **성공·평가 기준:** 자체 검증(`python scripts/backtest_metrics.py`): 지수 자신과 비교하면 beta = 1, tracking_error = 0, up_capture = 1 / 변동성 0이면 Sharpe는 None(예외 아님)
- **제약:** 반올림 금지(표시는 M06-02·노트북). 창이 1년 미만이면 CAGR·Sharpe 등 연환산 값은 "참고"로만 쓴다(M05-03·M06-02가 플래그를 읽음)

### M05-03 규칙 검증·추천기

- **한 줄 설명:** 백테스트 결과를 사용자 기준(낙폭·목표수익·상한·종목 수 등) R1~R8로 판정하고, 통과한 것 중 Sharpe 최고를 추천하며, 추천이 없으면 현금 혼합 대안을 만든다.
- **FR:** FR09, FR25
- **Input:** `11_backtest_results.json`, `10_target_portfolios.json`, `02_intent.json`(`risk_params.effective_max_drawdown`, `validation_criteria`), `01_request.json`(상한·종목 수), 디스크립터(섹터), 선택 `--max-drawdown`, `--no-alternatives`
- **Process**
    1. 규칙(level → status: hard는 pass/fail, soft는 pass/warn, 창 < 252거래일이면 R2·R7은 **info**(판정 제외, 참고))

    | 규칙 | 항목 | 수준 | 판정 |
    | --- | --- | --- | --- |
    | R1 | 최대낙폭 | hard | MDD ≤ 실효 허용 낙폭 |
    | R2 | 목표수익 | soft/info | CAGR ≥ 목표 연수익률 |
    | R3 | 비교지수 대비 | soft | 초과 CAGR > 0 (SPY 기준) |
    | R4 | 종목 상한(리밸런싱일) | hard | 리밸런싱일 최대 종목 비중 ≤ 상한 + 0.1%p |
    | R5 | 섹터 상한(리밸런싱일) | hard | 리밸런싱일 최대 섹터 비중 ≤ 상한 |
    | R6 | 종목 수 | hard | 보유 종목 ≥ `num_holdings.min` |
    | R7 | 변동성 적합 | soft/info | 연변동성 ≤ 성향 밴드(low 15% / medium 30% / high 무제한) |
    | R8 | 데이터 무결성 | hard | 시계열 길이 = 거래일 수, 리밸런싱 횟수 = 기대값 |

    2. 포트폴리오 상태 = fail이 하나라도 있으면 fail, warn 있으면 warn, 아니면 pass. 비교표에는 비교지수·대안도 포함
    3. 추천: fail 없는 포트폴리오 중 Sharpe 최고(동률이면 MDD 작은 것) + 한국어 사유 + 기준 템플릿 대비 차이. 없으면 `recommended = null` + 규칙별 실패 수 경고
    4. **현금 혼합 대안:** 선택 포트폴리오(추천 또는 기준)에 현금(수익 0)을 섞어 MDD가 허용치 안에 들어오는 최소 현금 비율을 찾고, M05-01의 `prepare/run_raw/evaluate`로 실제 백테스트해 `alternatives`에 넣는다. 이미 허용치 안이면 생략 + 경고
- **Output:** `12_validation.json`(`criteria`, `results[{id, status, checks[]}]`, `comparison_table`, `recommended`, `alternatives`, `summary{n_pass, n_warn, n_fail}`)
- **성공·평가 기준:** AI 예시: 전 포트폴리오 MDD ≈ 28~31% > 25% → 전부 fail, 추천 없음, 현금 15% 혼합안이 통과(실제 발견, 버그 아님) / 헬스케어 예시(23거래일): R1 전부 통과, R3 전부 warn, R2·R7 info → bl_01 추천(상태 warn) / 테스트 `test_validation_and_alternative`
- **제약:** 검사만 하고 값을 고치지 않는다. 기준은 `02_intent`·`01_request`·`backtest_config`에서만 읽는다

## F6 분석 결과 제공

### M06-01 결과 통합기

- **한 줄 설명:** 01~12 산출물과 설정·LLM 사용량·출처·경고를 **값을 바꾸지 않고** 한 파일로 모은다. 이후 리포트·노트북·DB 저장의 유일한 입력.
- **FR:** FR14, FR12
- **Input:** `output/01~12*.json`, `09a/10w/10f`(같은 `request_id`일 때만), `llm_usage.jsonl`, 설정 모듈, 디스크립터(선정표의 요약·출처)
- **Process:** `request`, `intent`, `selection`(깔때기·선정표·거절 사유), `portfolio{market_model, baseline, views, targets, news_evidence, walkforward, forward}`, `backtest`, `validation`, `money_krw`(기준일 환율 + 백테스트 환율, 포트폴리오·비교지수·대안별 원화 평가액), `llm_usage`(단계별 토큰·비용 합), `sources`(yfinance, Wikipedia GICS·구성종목, 팀 뉴스 DB, 웹 검색 …), `parameters`(세 설정 모듈 스냅샷), `warnings`(단계 태그 붙여 전부 수집). `ResultsBundle` 검증
- **Output:** `13_results.json`(약 1~2 MB)
- **성공·평가 기준:** 시계열 길이 일치, 포트폴리오 id = 타겟 ∪ walk-forward, 원화표가 전부 덮음(스키마) / 노트북과 리포트가 이 파일만 읽어 동작
- **제약:** 계산·반올림 금지(원화 환산 곱셈만 허용). 파일 하나에 다 들어가야 하므로 일별 패널은 넣지 않고 parquet로 둔다

### M06-02 리포트 문서 생성기 🤖 (LLM #5a 해석, #5b 서술)

- **한 줄 설명:** `13_results.json`에서 표·차트·KPI·체크포인트는 **코드**로, 해석·서술·용어 풀이는 **LLM**으로 만들어 렌더링용 블록 문서로 묶고, 서술 속 숫자를 결과값과 대조한다(원본의 근거 생성기 + Report 조립기 + 일치성 검사기).
- **FR:** FR14, FR26, FR25
- **Input:** `13_results.json`, 프롬프트 `prompts/14a_interpret/`, `prompts/14b_narrate/`, 선택 `--update-stubs`
- **Process**
    1. 선택 포트폴리오 = 추천(없으면 기준 템플릿). `report_blocks.py`가 사실(facts) 요약과 블록 생성: KPI 6개(창이 1년 미만이면 기간 수익률 라벨), 요청·제약·SOFT 해석표, 깔때기, 선정표, 기준·템플릿·BL 비중표와 도넛, 누적수익(line)·낙폭(area)·막대, 체크포인트, 검증 규칙표·전체 요약표, 추천 카드, 현금 혼합안 카드, infeasibility 콜아웃, walk-forward(날짜별 뉴스 건수·뷰·비중 변화·근거표 with url), 현재 구성(시나리오 카드·도넛·배분 금액), 출처·분석 조건·실행 요약·용어집
    2. **LLM #5a 해석기**(사실 요약 + 창 길이 플래그 입력): `performance_ko`, `risk_fit_ko`, `validation_ko`, `view_review_ko`, `next_actions_ko`, `news_ko`, `assessment{intent_fit, logic_consistency, comments_ko}`
    3. **LLM #5b 서술기**(초보자 눈높이, 해석 결과 + 사실 입력): `overview_ko`, `request_interpretation_ko`, `selection_ko`, `construction_ko`, `assumptions_ko`, `reconsideration_ko`, `forward_ko`, `glossary`
    4. **숫자 대조(audit):** 서술 문단의 모든 숫자(%, %p, USD, 원, 일, 개, 회, 종목, 배)를 결과값 집합과 비교해 없는 숫자는 경고. 금지어(샘플, stub, mock, JSON, 보장합니다, 확실히 …) 검사
    5. 섹션: 한눈에 보기 → 요청 해석 → 종목 선정 과정 → 포트폴리오 구성 → 과거 적용 결과 → [뉴스가 바꾼 것(walk-forward)] → 검증과 추천 → [지금 구성한다면] → 전제와 한계 → 참고자료와 분석 조건. `ReportDoc` 검증
- **Output:** `14_report.json`(헤더·KPI·nav·sections[blocks]·datasets(시계열)·assessment·sources·parameters·warnings). 블록 타입: paragraphs, kpis, table, donut, line, area, bar, funnel, callout, cards, checkpoints, glossary. 표 열에는 표시 형식(`pct`, `usd`, `krw`, `text`, `url`)만 붙이고 반올림은 렌더러가 한다
- **성공·평가 기준:** 섹션 ≥ 8(뉴스 시나리오 10), 숫자 대조 경고 0, 금지어 0 / `assessment`가 결과와 모순되지 않음(헬스케어 예시 intent_fit 0.55, logic 0.82) / 비용 ≈ $0.012
- **제약:** LLM에는 숫자를 "사실 목록"으로 주고 새 숫자를 만들지 말라고 명시(C-07). 투자 권유 표현 금지. stub 갱신은 `--update-stubs`일 때만

### M06-03 결과 노트북

- **한 줄 설명:** `13_results.json` 하나를 읽어 요청→의도→선정→구성→백테스트→검증→walk-forward→현재 구성→비용·경고를 표와 그래프로 보여 주는 노트북. **현재 결과 확인의 기본 경로**(React 화면은 선택).
- **FR:** FR14
- **Input:** `13_results.json`(env `MYFINSIGHT_RESULTS`로 경로 변경 가능)
- **Process:** `build_notebook.py`가 셀을 생성하고 로컬 임시 폴더에서 nbconvert로 실행한 뒤 `notebooks/results_overview.ipynb`로 복사(`--no-exec`면 실행 생략). 섹션 1~7(6b walk-forward: 뉴스 표·뷰·근거·비중 히트맵, 6c 현재 구성: 시나리오 표·도넛·배분)
- **Output:** 실행 결과가 포함된 `.ipynb`(약 1.5 MB)
- **성공·평가 기준:** 셀 오류 0 / 노트북의 숫자 = 결과 파일의 숫자(재계산 없음)
- **제약:** 결과 파일을 수정하지 않는다. 그래프는 matplotlib(의존성 최소)

## F8 분석 실행 관리

### M08-01 파이프라인 실행기·실행 기록

- **한 줄 설명:** 단계 스크립트를 순서대로 부르고, 어디서부터 어디까지 돌릴지·LLM 모드·뉴스 단계 포함 여부를 정하며, 실행 기록(프롬프트·사용량·경고)을 남긴다(원본 실행기 + 기록기).
- **FR:** FR24, FR25
- **Input:** `run_pipeline.py --request <01.jsonc> --backtest-request <02.jsonc> [--stop-at N] [--from N] [--news] [--web-evidence <json>] [--fx-rate] [--explain]`, env `MYFINSIGHT_LLM`, `MYFINSIGHT_RUN_ID`
- **Process**
    1. 디스크립터 존재 확인(없으면 안내 후 종료). run_id 발급(`run_YYYYMMDD_HHMMSS`)
    2. 단계 번호 표(`STAGE_NO`; 9a·10w·10f는 10번 그룹)에 따라 `--from ≤ n ≤ --stop-at`인 스크립트만 subprocess로 실행. 하나라도 실패하면 즉시 중단(`CalledProcessError`)
    3. 7~14단계는 백테스트 요청 파일을 받는다. `--news`면 9a·10w·10f를 10단계 뒤에 끼운다. 15단계(Front 퍼블리시)는 선택이며 기본 실행에서 제외
    4. 실행 기록: 각 단계의 콘솔 로그(`[stageN] ok -> 파일` + 핵심 숫자), `output/prompts/`(실제 프롬프트), `llm_usage.jsonl`·`llm_raw/`·`llm_cache/`, 각 JSON의 `warnings`. api 모드면 끝에 `llm_cost_report.py --run-id`로 단계별 토큰·비용 표
- **Output:** 종료 코드 0/1, `output/*`, 비용 리포트
- **성공·평가 기준:** `--stop-at 14`로 stub 모드 전체 실행 성공 / `--from 8 --stop-at 14`처럼 중간 재실행 시 앞 산출물 재사용 / 실패 단계와 사유가 마지막 로그 줄에 보임
- **제약:** 비즈니스 로직 금지(순서·인자·오류 전파만). 긴 실행은 백그라운드 + 로그 파일로

### M08-02 테스트·자체 검증

- **한 줄 설명:** 현재 `output/` 산출물로 파이프라인 불변식을 검사하는 pytest와, 수학 모듈의 자체 검증.
- **FR:** FR25
- **Input:** `output/*.json`, 선택 `MYFINSIGHT_TEST_RUN=1`(전체 재실행 후 검사)
- **Process:** `tests/test_pipeline.py` 8개 — `test_selftests`(portfolio·backtest_engine·backtest_metrics 자체 검증), `test_selection_constraints`(종목 수 범위·상한 용량), `test_candidates_no_weak_keyword_hits`, `test_target_portfolios_constraints`(합 1·최소 1%·상한·조정폭), `test_backtest_invariants`(closing 체크포인트·마지막 날 리밸런싱 없음·since_last 연쇄·to_date = 최종), `test_news_stages_if_present`(근거 날짜 창 안·뉴스 뷰 인용·fallback = 기준), `test_validation_and_alternative`, `test_results_bundle_and_report`(섹션 수·KPI 라벨·스키마 재검증)
- **Output:** pytest 결과(현재 8 passed, 약 30초)
- **성공·평가 기준:** PR 전 전부 통과 / 네트워크·LLM 호출 없음
- **제약:** 테스트는 산출물의 **구조·제약**을 검사하지 수익률 값을 고정하지 않는다(데이터가 갱신되면 값이 바뀌므로)

## 부록

### 부록 A. 예시 입력

**`input/01_user_request.healthcare.jsonc`** (요약. 실제 파일은 항목마다 주석과 [HARD]/[SOFT] 표시가 있다)

```jsonc
{
  "request_id": "req_2026-10-10_hc1",
  "profile":  { "age_band": "20s", "investment_experience": "beginner", "financial_knowledge": "basic", "investable_ratio_of_assets": 0.3 },   // [SOFT] 설명 수준·보정
  "capital":  { "initial_amount": 10000000, "currency": "KRW", "monthly_contribution": 500000, "contribution_day": 25 },                     // [HARD]
  "horizon":  { "start_date": "2026-10-08", "target_years": 3, "purpose": "wealth_growth" },                                                 // start_date = 기준일 [HARD]
  "risk":     { "risk_tolerance": "moderate", "max_drawdown_tolerance": 0.25, "loss_reaction": "hold", "target_annual_return": 0.12, "benchmark": "SPY" },
  "constraints": {                                                                                                                           // 전부 [HARD]
    "universe": ["SP500", "NASDAQ100"], "asset_types": ["stock", "etf"],
    "num_holdings": { "target": 15, "min": 10, "max": 20 },
    "max_weight_per_stock": 0.15, "max_weight_per_sector": 1.0, "min_cash_ratio": 0.0,
    "exclude_tickers": [], "exclude_sectors": [], "exclude_themes": ["tobacco", "gambling"], "must_include_tickers": [],
    "rebalance": { "count": 1, "unit": "2w" },                       // unit: 2w | 1m | 1q | 6m | 1y, count 0 = 리밸런싱 없음
    "allow_leverage": false, "allow_short": false,
    "min_market_cap_usd": 20000000000, "min_avg_daily_volume_usd": 50000000
  },
  "strategy_preference": { "template": "momentum", "baseline_weighting": "equal_weight", "use_news_tilt": true },
  "natural_language": { "idea": "헬스케어 쪽에 투자하고 싶어요. 비만·당뇨 치료제, 의료기기, 헬스케어 서비스처럼 … 소형 바이오는 빼 주세요.", "language": "ko" }
}
```

**`input/02_backtest_request.healthcare.jsonc`**

```jsonc
{
  "request_id": "req_2026-10-10_hc1",
  "confirmation": { "selection_confirmed": true, "removed_tickers": [], "added_tickers": [] },
  "backtest": { "start_date": "2026-09-08", "end_date": "2026-10-08", "reselect_at_start": true, "benchmark": null, "include_contributions": true },
  "views": { "n_sets": 5, "views_per_set": 4 },                          // 정적 BL 시나리오
  "walkforward": { "enabled": true, "view_sets": 1, "views_per_set": 4 },  // 리밸런싱마다 뉴스 뷰 1세트
  "forward_construction": { "enabled": true, "as_of": null }             // null = 가격 데이터 마지막 날
}
```

**`input/news_web_evidence.healthcare.json`** (DB에 뉴스가 없는 창을 보충. 날짜별 레코드 목록, 실제 기사만)

```json
{ "2026-09-08": [ { "evidence_id": "web001", "ticker": "LLY", "published_at": "2026-08-27", "source": "WEB_SEARCH",
                    "publisher": "Managed Healthcare Executive", "title": "Zepbound linked to lower healthcare costs …", "url": "https://…" } ] }
```

### 부록 B. 단계별 출력 파일

| 파일 | 만든 모듈 | 핵심 내용 |
| --- | --- | --- |
| `01_request.json` | M01-01 | 요청 + `derived`(기준일·환율·USD 금액·리밸런싱 규칙·데이터 범위) |
| `02_intent.json` | M03-01 | 테마(GICS 코드·키워드)·스크린·위험 파라미터·뉴스 틸트·검증 기준 |
| `03_candidates.json` | M03-02 | 후보 ≤ 120, 매칭 근거, 제외 사유, 깔때기 통계 |
| `04_tagging.json` | M03-03 | 후보별 테마 판정·신뢰도·사유, 통과 티커 |
| `05_selection.json` (`06_selection_explained.json`) | M03-04 | 최종 종목·순위·지표값, 거절 사유, infeasibility |
| `07_backtest_spec.json` (+ `07_*_bt.json`) | M04-01 | 기간·자본(시작일 환율)·리밸런싱·비교지수·재선정 종목 |
| `08_market_model.json`, `08_baseline_portfolios.json` | M04-02 | Σ·상관·변동성·시총비중·δ·π, 템플릿 4개 |
| `09_views.json` | M04-03 | 시나리오 5세트 × 뷰 4개 |
| `10_target_portfolios.json` | M04-04 | BL 5개 + 템플릿 4개 + 사양 + 파라미터 (백테스트 입력) |
| `09a_news_evidence.json` | M04-05 | 날짜별 뉴스 창·근거 id·충분 여부, 근거 사전 |
| `10w_target_paths.json`, `10f_forward_portfolios.json` | M04-06 | 날짜별 비중 경로·뷰, 현재 구성 9개 |
| `11_backtest_results.json`, `11_daily_panel.parquet` | M05-01/02 | 포트폴리오·비교지수별 headline·metrics·money·series·checkpoints |
| `12_validation.json` | M05-03 | R1~R8 판정, 비교표, 추천, 현금 혼합안 |
| `13_results.json` | M06-01 | 전부 통합 (리포트·노트북 입력) |
| `14_report.json` | M06-02 | 블록 모델 리포트 (섹션·KPI·datasets·assessment) |
| `notebooks/results_overview.ipynb` | M06-03 | 실행된 노트북 |
| `output/prompts/`, `llm_raw/`, `llm_cache/`, `llm_usage.jsonl` | M00-03 | 실제 프롬프트, 원문 응답, 캐시, 토큰·비용 |

### 부록 C. LLM 호출 목록

| # | 모듈 | 프롬프트 폴더 | LLM에 주는 것 | LLM이 돌려주는 것 | 코드가 검증하는 것 | 실측 비용 |
| --- | --- | --- | --- | --- | --- | --- |
| 0 | M02-02 (선택, 오프라인) | `00_descriptor` | 종목 이름·GICS·사업 설명 | 한국어 한 줄 요약·키워드 | 스키마 | 1회 ≈ $0.04 |
| 1 | M03-01 | `02_intent` | 요청 JSONC 원문 + GICS 트리 | `IntentSpec` | 코드 자릿수, 템플릿-지표 일치, 테마 ≥ 1 | ≈ $0.003 |
| 2 | M03-03 | `04_classify` | 후보 40개 표 + 테마 설명 | 후보별 in_theme·confidence·사유 | 결과 리스트 형식, 누락 티커 경고 | ≈ $0.003 / 배치 |
| 3 | M03-04 (선택) | `06_explain` | 선정 종목·지표·태깅 사유 | 종목별 한국어 근거 | 스키마 | ≈ $0.002 |
| 4 | M04-03, M04-06 | `09_views` / `09_views_news` | 종목 표(변동성·내재수익률·기준 비중) + 테마 요약 (+ 뉴스 근거 목록) | 시나리오 세트·뷰 | 티커 존재, 중복, 신뢰도·수익률 범위 클리핑, 근거 id 실존, 뉴스 없는 절대 뷰 삭제 | ≈ $0.002 / 호출 |
| 5a | M06-02 | `14a_interpret` | 사실 요약(성과·검증·뷰 적중·walk-forward·창 길이 플래그) | 해석 문단들 + assessment | 숫자 대조, 금지어 | ≈ $0.004 |
| 5b | M06-02 | `14b_narrate` | 사실 요약 + 5a 결과 + 설명 수준 | 서술 문단들 + 용어집 | 숫자 대조, 금지어 | ≈ $0.008 |

모든 호출은 M00-03을 거친다(캐시·재시도·기록). 전체 파이프라인 1회(뉴스 시나리오 포함) ≈ $0.03.

### 부록 D. 경고·중단 정책과 표시 규칙

| 상황 | 처리 |
| --- | --- |
| 입력 HARD 규칙 위반, 환율 없음, 백테스트 창이 데이터 밖, 통과 종목 0개, LLM 재시도 후 실패, 스키마 검증 실패 | **중단**(`SystemExit`), 이후 산출물 없음 |
| 유니버스에 없는 예시 티커, 지표 결측 종목, 모형 창 부족 종목, 뷰 클리핑·삭제, stub 불일치, 종료일 clamp, 뉴스 부족 날짜(fallback), 짧은 창(R2·R7 info), 대안 생략 | **계속** + 해당 단계 `warnings` → 13단계 `warnings[{stage, message}]` → 리포트 「전제와 한계」·노트북 7절 |
| 추천 없음(전부 fail) | 계속. `recommended = null`, 현금 혼합안 제공, 리포트는 기준 템플릿을 "선택"으로 표시 |

표시 규칙: 결과 파일의 값은 소수·USD 실수 그대로 두고, 표 열의 형식 태그(`pct` 소수 둘째 자리 %, `usd` 소수 둘째 자리, `krw` 정수 쉼표, `text`, `url`)에 따라 렌더러(노트북·Front)가 반올림한다. 서술에 들어간 숫자는 결과값과 같아야 한다(C-07).

### 부록 E. 구현 현황과 다음 단계

**끝난 것 (2026-10-10)**
- 시나리오 1 "AI 반도체·클라우드" (요청 `01_user_request.example.jsonc`, 백테스트 2023-04-03 ~ 2026-04-01, 분기 리밸런싱): stub·api 모드 모두 완주. 전 포트폴리오 CAGR 29~36%, MDD 28~31% > 허용 25% → 추천 없음, 현금 15% 혼합안 통과
- 시나리오 2 "헬스케어 + 뉴스" (2026-09-08 ~ 10-08, 2주 리밸런싱 9/8·9/22·10/6, 팀 DB + 웹 보충 근거, walk-forward, 10/8 현재 구성): api 모드 완주. 23거래일 창이라 연환산은 참고, 뉴스 반영 포트폴리오 −0.27% vs 동일비중 −0.58% vs XLV +1.00%
- pytest 8/8, 노트북 26셀 오류 0, PR #1(`module_mock_up` → `main`)

**다음 단계 후보**
1. 산업그룹 상한(`max_weight_per_industry_group`) — 단일 섹터 테마에서 분산 확보 🔶K1
2. 뉴스 뷰 프롬프트 조이기(저정보 헤드라인의 절대 뷰 금지) 🔶K2, 뷰 대조군(뉴스 없는 BL vs 뉴스 BL) 실험
3. walk-forward에서 종목 재선정까지 포함 🔶K7
4. 과거 구성종목 스냅샷 확보로 생존 편향 완화 🔶K4
5. `13_results.json`의 DB 저장 스키마와 서비스(LangGraph·React) 연결 🔶K8·K9

### 부록 F. 결정 필요 목록 🔶

| # | 항목 | 현재 값·상태 | 고려 사항 |
| --- | --- | --- | --- |
| K1 | 섹터 상한 vs 산업그룹 상한 | 섹터 상한만(헬스케어는 1.0으로 완화) | 단일 섹터 테마는 섹터 상한이 의미 없음. 산업그룹(장비·서비스 vs 제약·바이오) 상한 추가 여부 |
| K2 | 저정보 헤드라인 처리 | 프롬프트 규칙만(근거 1건이면 confidence ≤ 0.3) | 실적 발표일 공지로 +21% 절대 뷰가 생성된 사례. 일정·컨퍼런스 공지는 절대 뷰 금지로 명시할지 |
| K3 | 뉴스 창·최소 종목 수 | 14일, 종목당 10건, 최소 3종목 | DB는 2026-09-27 이후만 있음. 기간 확대 후 재검토 |
| K4 | 생존 편향 | 현재 구성종목·디스크립터 스냅샷 사용 | 과거 지수 구성 이력을 확보할지, 리포트 한계 문구로만 둘지 |
| K5 | 무위험수익률 | 상수 4% | 국채금리 시계열로 교체 여부 |
| K6 | 재무 템플릿 기간 | yfinance 분기 5개 → 약 4년 | `low_per`·`quality` 장기 백테스트에는 다른 재무 데이터 소스 필요 |
| K7 | walk-forward 재선정 | 비중만 갱신 | 리밸런싱마다 03·05 재실행(분류는 재사용) 여부 |
| K8 | React 렌더링 | `stage15_publish.py` + `Front/src/pipeline/` 보류 | 파일럿은 노트북. 서비스 단계에서 다시 결정 |
| K9 | 결과 저장 | 파일(`13_results.json`) | 팀 DB에 결과 테이블을 둘지, 스키마는 `ResultsBundle` 기준 |
| K10 | LLM 비용 상한 | 요청당 ≈ $0.03 | 모델 변경·배치 크기·캐시 정책 |

### 부록 G. 용어 풀이 (처음 보는 사람용)

- **GICS:** 글로벌 산업분류 기준. 섹터(11) → 산업그룹(25) → 산업(74) → 세부산업(163)의 4단계, 코드 2/4/6/8자리. 테마를 종목으로 바꾸는 공통 언어로 쓴다.
- **디스크립터:** 종목별 GICS 태그·키워드·한 줄 소개를 모아 둔 사전. LLM에 종목 표를 주지 않기 위한 장치.
- **템플릿 스크린:** 정해진 지표 하나로 순위를 매겨 고르는 규칙(모멘텀 = 최근 1개월을 뺀 12개월 수익률, 저변동성, 저PER, 고배당, 퀄리티).
- **기준 비중(baseline)과 템플릿:** 동일비중(1/N), 시가총액비중, 역변동성(변동성이 낮을수록 더), 최소분산(전체 변동성을 최소화).
- **Ledoit-Wolf 수축:** 표본 공분산이 종목 수에 비해 데이터가 적을 때 추정 오차를 줄이려고 구조화된 행렬 쪽으로 "당기는" 방법.
- **내재 기대수익률 π, 위험회피 δ:** "시장(기준 비중)이 지금 이 비중을 들고 있으려면 각 종목에 이만큼의 기대수익을 전제해야 한다"는 역산값. δ는 위험 1단위를 피하려고 포기하는 수익.
- **Black-Litterman(BL):** π에 "뷰"를 섞어 기대수익률을 갱신하고 그걸로 비중을 다시 푸는 방법. 뷰가 약하면 기준 비중 근처, 강하면 더 많이 움직인다.
- **뷰(view):** 절대 뷰 "LLY는 연 +15%", 상대 뷰 "LLY가 MRK보다 연 +5%". 신뢰도(confidence)가 Ω(불확실성)를 결정.
- **walk-forward:** 리밸런싱 날짜마다 그 시점까지의 정보로만 모형·뷰를 다시 만드는 방식. 미래 정보가 섞이지 않는다.
- **체크포인트:** 리밸런싱 날짜(와 종료일)마다 비중·보유·거래·그때까지의 지표를 저장한 스냅샷.
- **MDD(최대낙폭):** 고점 대비 가장 크게 떨어진 비율. **Sharpe:** (수익률 − 무위험수익률)/변동성. **XIRR:** 적립 시점을 반영한 연수익률.
- **현금 혼합안:** 포트폴리오에 현금을 섞어 낙폭을 허용치 안으로 들이는 대안(현금 수익 0 가정).
- **stub:** LLM이 돌려줬을 답을 저장해 둔 파일. API 없이 파이프라인을 돌릴 때 쓴다.

# 3. 분배

| 묶음 | 담당자 | 모듈 | 성격 | 작업량 |
| --- | --- | --- | --- | --- |
| **A. 데이터·공통 기반** | (미정) | M00-01 설정, M00-02 스키마, M02-01 데이터 수집·캐시, M02-02 디스크립터 | 외부 데이터, 스키마 관리, 생존 편향 대응(K4) | ●●●○ |
| **B. 자연어 전략·종목 선정** | (미정) | M00-03 LLM 호출기, M01-01 요청 정규화, M03-01 의도 해석 🤖, M03-02 후보 검색, M03-03 후보 분류 🤖, M03-04 스크린·선정 | 프롬프트·검증 규칙·분류 품질 | ●●●● |
| **C. 포트폴리오 구성** | (미정) | M04-01 사양·재선정, M04-02 시장모형·템플릿, M04-03 뷰 생성 🤖, M04-04 BL, M04-05 뉴스 근거, M04-06 walk-forward·현재 구성 🤖 | 최적화 수학, 뉴스 DB, 뷰 프롬프트(K2) | ●●●● |
| **D. 백테스트·검증·결과** | (미정) | M05-01 백테스트, M05-02 지표, M05-03 규칙 검증, M06-01 결과 통합, M06-02 리포트 🤖, M06-03 노트북, M08-01 실행기, M08-02 테스트 | 계산 정확도, 리포트 품질, 통합 테스트 | ●●●● (통합 책임 포함) |

## 이렇게 묶은 이유

- B에 LLM 호출기(M00-03)를 둠: LLM 호출이 가장 많은 묶음(02·04·06)이라 프롬프트·검증·비용을 한 사람이 보는 편이 낫다. 09·14 프롬프트는 C·D가 쓰되 호출 계층 변경은 B에 요청
- C에 뉴스 근거 수집기(M04-05)를 둠: 쓰는 쪽(10w·10f)이 C이고 DB 스키마 변화에 같이 대응해야 한다
- D가 스키마 변경의 "검수자": 결과 통합(M06-01)·리포트가 모든 필드를 읽으므로, A가 관리하는 `schemas.py` 변경은 D의 테스트를 통과해야 머지
- 대안: C가 무거우면 M04-01(사양·재선정)을 B로 옮긴다(03·05 재실행이라 B 코드와 가깝다)

## 묶음 사이 연결 (먼저 합의할 계약)

```
A ── parquet 캐시·디스크립터·schemas.py ──▶ B, C, D
B ── 05_selection.json (+ 02_intent.json) ──▶ C
C ── 10_target_portfolios.json (+ 10w/10f) ──▶ D
D ── 13_results.json → 14_report.json / 노트북 ──▶ 사용자
모두 ── 단계 JSON 계약(부록 B), warnings 전달 규칙(부록 D)
```

## 진행 순서

1. 공통: `schemas.py`와 설정 3개를 읽고 바꿀 필드를 먼저 합의. 예시 입력 2개와 `output/` 산출물이 있으므로 각자 자기 단계만 바꿔도 `--from N --stop-at M`으로 바로 확인 가능
2. 각 묶음의 다음 단계(부록 E): A는 K4, B는 분류 품질·K2 프롬프트, C는 K1·K7, D는 K5·K9와 테스트 확장
3. 머지 전 `pytest tests -q`와 stub 모드 전체 실행(`run_pipeline.py --stop-at 14`)을 통과

# 4. 역할별 안내

<aside>
💡

모든 담당자는 먼저 「2. 공통 제약」과 「파일 계약」, 그리고 M00-02 스키마를 읽고 시작한다. 모듈 상세는 2절을 보고(중복 기재 안 함), 여기에는 역할별로 먼저 볼 것과 인터페이스만 적는다.

</aside>

## A. 데이터·공통 기반

- **담당 모듈:** M00-01, M00-02, M02-01, M02-02
- **제공:** parquet 캐시(파일 계약), 디스크립터, `schemas.py`, 설정 상수 / **사용:** 없음(최상류)
- **먼저 볼 파일:** `scripts/common.py`, `scripts/schemas.py`, `scripts/fetch_data.py`, `scripts/build_descriptor.py`
- **팁:** Yahoo 429가 나면 `fetch_fundamentals.py`는 그냥 다시 실행하면 이어받는다. 디스크립터를 바꾸면 03·04 결과가 바뀌므로 B에 알린다

## B. 자연어 전략·종목 선정

- **담당 모듈:** M00-03, M01-01, M03-01~04
- **제공:** `01_request.json`, `02_intent.json`, `05_selection.json` / **사용:** 디스크립터·가격 캐시(A)
- **먼저 볼 파일:** `scripts/llm.py`, `prompts/02_intent/`, `prompts/04_classify/`, `scripts/stage3_retrieve.py`, `scripts/stage5_screen.py`
- **팁:** 프롬프트를 바꾸면 캐시 키가 바뀌어 다시 과금된다. stub 모드로 형식을 먼저 맞추고 api 모드는 `--stop-at 5`로 짧게 확인(≈ $0.01)

## C. 포트폴리오 구성

- **담당 모듈:** M04-01~06
- **제공:** `07_backtest_spec.json`, `10_target_portfolios.json`, `10w/10f` / **사용:** `05_selection.json`·`02_intent.json`(B), 가격·`info_snapshot`(A), 뉴스 DB
- **먼저 볼 파일:** `scripts/portfolio.py`(`python scripts/portfolio.py`로 자체 검증), `scripts/portfolio_config.py`, `prompts/09_views_news/`, `scripts/stage10w_walkforward.py`
- **팁:** 수학을 바꾸면 08·10·10w·10f가 모두 영향받는다. 자체 검증(뷰 방향·제약·수렴)을 먼저 통과시킨다. DB 연결은 `db_probe.py`로 확인

## D. 백테스트·검증·결과

- **담당 모듈:** M05-01~03, M06-01~03, M08-01~02
- **제공:** `11~14` 산출물, 노트북, 테스트 / **사용:** `10_target_portfolios.json`(C), 가격 캐시(A), 모든 단계의 `warnings`
- **먼저 볼 파일:** `scripts/backtest_engine.py`, `scripts/backtest_metrics.py`, `scripts/stage12_validate.py`, `scripts/report_blocks.py`, `prompts/14a_interpret/`, `tests/test_pipeline.py`
- **팁:** bt는 시작 전날에 가짜 현금 행을 붙인다(`extract_raw`가 제거). 리포트 서술에 새 숫자가 필요하면 LLM에 "사실 목록"으로 먼저 넣어야 숫자 대조를 통과한다
