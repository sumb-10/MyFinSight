# module_mockup

MyFinSight 파이프라인 단계별 모듈 실험. **각 단계의 output JSON이 다음 단계의 input** 이 된다.
LLM 단계는 프롬프트 템플릿 + 기대 출력 예시(stub)로 대체하고, 나머지는 전부 코드로 실제 동작한다.

## 환경

가상환경과 데이터 캐시는 **Google Drive 폴더 밖**에 둔다 (Drive 안에 두면 파일 스트리밍 때문에 Python 이 멈춤).

```bash
python3 -m venv ~/.venvs/myfinsight
~/.venvs/myfinsight/bin/pip install yfinance pandas numpy bt lxml pyarrow requests pydantic
export P=~/.venvs/myfinsight/bin/python
```

데이터 캐시 위치: `~/.myfinsight/data/raw/` (env `MYFINSIGHT_DATA` 로 변경 가능). 코드·입력·프롬프트·stub·디스크립터만 이 폴더(git)에 둔다.

## 폴더

| 경로 | 내용 |
|---|---|
| `input/` | 사용자 요청 예시 (`*.jsonc`, 주석으로 항목 설명과 [HARD]/[SOFT] 구분) |
| `prompts/<stage>/` | LLM 단계별 `system_prompt.md` + `user_prompt.md` 템플릿 |
| `stubs/<stage>.example.json` | 그 LLM 이 반환했을 기대 출력 (stub 모드에서 그대로 사용) |
| `scripts/` | 단계 스크립트. `common.py`(경로·JSONC 로더) `schemas.py`(Pydantic) `llm.py`(LLM 교체 지점) `descriptor.py` `metrics.py` |
| `data/reference/gics_taxonomy.json` | GICS 163 세부산업 × 4단계 (Wikipedia 파싱) |
| `data/processed/sp500_nasdaq100_descriptor.json` | 유니버스 디스크립터: 종목별 GICS 태그·키워드·한 줄 소개 |
| `output/<run_id>/` | 실행별 산출물: 단계 JSON, `inputs/`(입력 사본), `run_meta.json`, `prompts/`(렌더링된 프롬프트), `llm_raw/`, `llm_cost_report.json`. `output/latest` 는 최근 실행 링크, `output/llm_cache/`·`output/llm_usage.jsonl` 은 실행 간 공유 (모두 git 제외) |
| `store/` | 로컬 JSON 저장소: `schemas/`(JSON Schema, git 포함), `data/`(프로필·요청·run 색인·트래킹, git 제외). `data/runs.json` 에 실행 목록이 쌓인다 |

## 파이프라인

```
[데이터]  fetch_data.py (가격 15년)  fetch_fundamentals.py (재무·info)  build_descriptor.py (디스크립터)
[요청]    01 정규화·검증 ─▶ 02 의도 해석 (LLM#1) ─▶ 03 후보 검색 ─▶ 04 후보 분류 (LLM#2, 배치) ─▶ 05 정량 스크린·선정 ─▶ (06 근거 서술, LLM#3)
[구성]    07 확인·백테스트 사양·재선정 ─▶ 08 시장모형·베이스라인 템플릿 ─▶ 09 뷰 생성 (LLM#4) ─▶ 10 Black-Litterman 타겟
[뉴스]    9a 뉴스 근거(팀 DB + 웹 검색 보충) ─▶ 10w walk-forward(리밸런싱마다 뉴스 뷰 → BL) ─▶ 10f 현재 구성(최신 가격·뉴스)   ※ `--news`
[검증]    11 bt 백테스트 (정적 9개 + walk-forward 5개 + 벤치마크 SPY·QQQ·XLV, 체크포인트) ─▶ 12 규칙 검증·추천
[리포트]  13 결과 통합 (13_results.json) ─▶ 14 리포트 문서 (LLM#5a 해석 + #5b 서술 → 14_report.json) ─▶ notebooks/results_overview.ipynb (결과 확인)   ※ 15 Front 퍼블리시는 선택
```

| 단계 | 스크립트 | LLM | input → output |
|---|---|---|---|
| D | `build_descriptor.py` (+ `stage0_descriptor_llm.py` 선택) | #0 선택 | universe.json, GICS 표 → 디스크립터 |
| 1 | `stage1_normalize.py` | – | `input/*.jsonc` → `01_request.json` (환율·USD 환산·리밸런싱 규칙) |
| 2 | `stage2_intent.py` | #1 | 01 + GICS 트리 → `02_intent.json` (테마→GICS 코드·키워드, SOFT 해석) |
| 3 | `stage3_retrieve.py` | – | 02 + 디스크립터 + 가격 → `03_candidates.json` (후보 ≤120, 하드 필터) |
| 4 | `stage4_classify.py` | #2 (40개/배치) | 03 → `04_tagging.json` (테마 해당 여부·신뢰도) |
| 5 | `stage5_screen.py` | – | 04 + 지표 → `05_selection.json` (**최종 종목**) |
| 6 | `stage6_explain.py` | #3 선택 | 05 → `06_selection_explained.json` |
| 7 | `stage7_confirm.py` | – | `input/02_backtest_request.jsonc` + 01·02·04·05 → `07_backtest_spec.json` (기간·자본·리밸런싱·백테스트 시작일 기준 재선정) |
| 8 | `stage8_baseline.py` | – | 07 + 가격 → `08_market_model.json`(Σ, 시총비중, 내재수익률 π) + `08_baseline_portfolios.json`(equal_weight·market_cap·inverse_volatility·min_variance) |
| 9 | `stage9_views.py` | #4 | 07·08·02 → `09_views.json` (시나리오 5세트 × 뷰 4개, 절대/상대) |
| 10 | `stage10_black_litterman.py` | – | 08·09 → `10_target_portfolios.json` (**BL 타겟 5개 + 템플릿 4개 + backtest_spec** = 백테스트 입력) |
| 9a | `stage9a_news.py` (`news_db.py`) | – | 팀 DB(PostgreSQL `myfinsight`, `.env` NEWS_DB_*) 뉴스 헤드라인 → `09a_news_evidence.json` (구성일별 직전 14일 창, 종목당 10건, 웹 검색 보충은 `--web-evidence`) |
| 10w | `stage10w_walkforward.py` | #4 (날짜마다) | 리밸런싱일마다 시장모형 재추정 + 뉴스 근거 뷰(`prompts/09_views_news`) + BL → `10w_target_paths.json` (날짜별 비중) |
| 10f | `stage10f_forward.py` | #4 | 최신 가격·뉴스로 "지금 구성한다면" → `10f_forward_portfolios.json` (백테스트 없음) |
| 11 | `stage11_backtest.py` | – | 10 + 가격 → `11_backtest_results.json` (포트폴리오별 headline·metrics·money·일별 series·리밸런싱 체크포인트·적립 원장·이벤트·뷰 진단) + `11_daily_panel.parquet` |
| 12 | `stage12_validate.py` | – | 11·02·01 → `12_validation.json` (R1~R8 pass/warn/fail, 비교표, 추천 포트폴리오) |
| 13 | `stage13_collect.py` | – | 01~12 전체 → `13_results.json` (**모든 결과를 하나로 모은 파일**; 이후 단계·DB 저장·재분석의 유일한 입력) |
| 14 | `stage14_report.py` (+ `report_blocks.py`) | #5a 해석, #5b 서술 | 13 → `14_report.json` (렌더링용 블록 모델: KPI·표·도넛·누적수익·낙폭·막대·깔때기·카드·체크포인트·용어집 + 초보자용 서술) |
| NB | `build_notebook.py` | – | 13 → `notebooks/results_overview.ipynb` (요청·선정·구성·백테스트·검증·walk-forward·현재 구성·비용을 한 파일에서 확인; **결과 확인의 기본 경로**) |
| 15 | `stage15_publish.py` (선택) | – | 14 → `Front/public/pipeline/report.json` (Front `#/pipeline` 화면용. 현재는 사용하지 않음) |

## 실행

```bash
$P scripts/fetch_data.py --years 15          # 1회. 가격·유니버스 → ~/.myfinsight/data/raw
$P scripts/fetch_fundamentals.py             # 1회. 재무제표·info·배당 (Yahoo 429 시 나중에 재실행, 종목별 캐시로 이어받음)
$P scripts/build_descriptor.py               # 1회. 디스크립터 생성 (재무 수집 후 다시 실행하면 사업 설명이 채워짐)

$P scripts/run_pipeline.py --request input/01_user_request.example.jsonc      # 1~5단계, stub 모드 (기본, API 호출 없음)
$P scripts/run_pipeline.py --stop-at 14                                      # 1~14단계 (7~14 는 input/02_backtest_request.jsonc 사용) -> output/run_example_<일시>/
$P scripts/run_pipeline.py --request input/01_user_request.<name>.jsonc --backtest-request input/02_backtest_request.<name>.jsonc --run-id run_<name>_x   # 실행 id 지정
MYFINSIGHT_LLM=api $P scripts/run_pipeline.py --request input/01_user_request.healthcare.jsonc --backtest-request input/02_backtest_request.healthcare.jsonc --news --web-evidence input/news_web_evidence.healthcare.json --stop-at 14   # 헬스케어 + 뉴스 시나리오 (9a·10w·10f 포함)
$P scripts/build_notebook.py [--run-id run_x]                                # output/<run_id>/13_results.json → notebooks/<run_id>.ipynb (기본: output/latest)
MYFINSIGHT_DATA=~/.myfinsight/data_db $P scripts/db_sync.py                   # 팀 DB → 캐시 동기화 (가격·환율·발행주식수; 비교지수는 yfinance 캐시 사본). 이후 같은 MYFINSIGHT_DATA 로 파이프라인 실행
$P scripts/db_probe.py                                                       # 팀 뉴스 DB 연결 점검 (읽기 전용)
MYFINSIGHT_LLM=api $P scripts/stage14_report.py                              # 리포트 서술을 gpt-6-luna 로 새로 생성 (같은 입력이면 llm_cache 재사용)
$P scripts/run_pipeline.py --from 11 --stop-at 14                            # 중간부터 재실행 (앞 단계 output 재사용)
$P scripts/backtest_engine.py && $P scripts/backtest_metrics.py              # 백테스트 엔진·지표 자체 검증
$P -m pytest tests -q                                                        # 불변식 테스트 (output/latest 또는 MYFINSIGHT_RUN_ID 기준; MYFINSIGHT_TEST_RUN=1 이면 전체 재실행)
$P scripts/stage12_validate.py --max-drawdown 0.30                           # 검증 기준을 바꿔 다시 판정 (백테스트 재실행 없음)
$P scripts/portfolio.py                                                      # 포트폴리오 수학 자체 검증 (BL 수렴·뷰 방향·제약)
MYFINSIGHT_LLM=api $P scripts/run_pipeline.py --explain                      # 실제 LLM 호출 + 비용 리포트
$P scripts/llm_cost_report.py                                                # 마지막 실행의 토큰·비용 요약
```

결과 확인은 `notebooks/results_overview.ipynb` 로 한다(`build_notebook.py` 가 13_results.json 을 읽어 생성·실행). Front 렌더링(`stage15_publish.py` → `#/pipeline`)은 선택 사항이며 현재 파일럿에서는 쓰지 않는다.

LLM 설정은 `scripts/llm_config.py` 한 곳(모델명·생성 옵션·단가·.env 위치)에서 바꾼다. 모드는 `MYFINSIGHT_LLM=stub|api`. API 모드는 호출마다 `output/llm_usage.jsonl` 에 토큰·비용을 기록하고 원문 응답을 `output/llm_raw/` 에 남기며, 같은 프롬프트는 `output/llm_cache/` 에서 재사용한다(`MYFINSIGHT_LLM_CACHE=0` 으로 끔). 응답이 깨지거나 검증에 실패하면 오류를 되먹여 1회 재시도한다. 14단계 stub 갱신은 `--update-stubs` 를 줄 때만 한다.

포트폴리오 설정(추정 윈도 756일, Ledoit-Wolf 수축, τ=0.05, 위험회피 δ, 뷰 수익률 범위, 템플릿 목록)은 `scripts/portfolio_config.py`, 백테스트 설정(거래비용 5bp, 소수 주식, 무위험수익률 4%, 체크포인트 빈도, 드리프트 허용치, 변동성 밴드)은 `scripts/backtest_config.py` 에 있다.

11단계 출력 구조: 포트폴리오마다 `headline`(KPI 6개) / `metrics`(return·risk·risk_adjusted·vs_benchmark·vs_baseline·composition·trading·stability) / `money`(적립 포함 평가금액·XIRR) / `series`(일별 지수·평가금액·낙폭, 날짜 축은 `series_dates` 공통) / `checkpoints`(리밸런싱일마다 비중 before·after·target, 보유 종목, 거래, 구간 성과 `since_last`, 누적 지표 `to_date`) / `contribution_ledger` / `events` / `view_diagnostics`.

## 알려진 한계

- 디스크립터와 유니버스는 현재 시점 스냅샷이라 과거 백테스트에 생존 편향이 있다.
- yfinance 재무제표는 분기 5개까지라 `low_per`/`quality` 는 최근 4년 범위에서만 as-of 계산이 가능하다.
- 사업 설명이 규칙 기반("회사명 — 세부산업")인 동안은 키워드 매칭 오탐이 많다. 4단계 분류 LLM 이 걸러내며, 재무 수집·LLM#0 실행 후 개선된다.
- 9단계(정적) 뷰는 뉴스 데이터 없이 LLM 이 만든 플레이스홀더라 기준일 이후 정보가 섞일 수 있다(`hindsight_risk: true`). `--news` 경로(9a·10w·10f)는 구성일 직전 14일 헤드라인만 근거로 쓰고 뷰마다 `evidence_ids` 를 요구하지만, 팀 DB 뉴스는 2026-09-27 이후만 있어 그 이전 창은 웹 검색 근거(`input/news_web_evidence.*.json`, `origin: web_search`)로 보충했다. 시총 비중은 현재 발행주식수 × 과거 종가의 근사치다.
- 12단계는 추천이 없을 때 중심 포트폴리오에 현금을 섞어 과거 최대낙폭이 허용치에 들어오는 "현금 혼합안"을 계산해 `alternatives` 로 제공한다(현금 수익 0 가정). 11단계는 사용자 비교지수(SPY) 외에 QQQ·XLV 도 같은 적립으로 돌려 `benchmarks` 에 담는다(상대 지표·R3 는 SPY 기준). 백테스트 창이 252 거래일 미만이면 연환산 지표는 `annualized_reliable: false` 로 표시되고 R2·R7 은 `info`(참고) 판정이 된다. 5단계는 섹터 상한 때문에 목표 종목 수를 못 채우면 `infeasibility` 로 사유와 선택지를 남긴다. 백테스트 초기자본은 구성일 환율로 다시 환산한다(`backtest_spec.capital.fx_*`). 위험회피 δ 는 기본 `market_implied`(SPY 내재 δ × 성향 배수).
- 10단계 타겟 비중은 구성일 기준 정적이며 11단계가 리밸런싱마다 같은 비중을 복원한다. `--news` 경로의 10w 는 리밸런싱마다 시장모형·뉴스 뷰·BL 을 다시 계산한 날짜별 비중(`wf_*`)을 쓰지만, 종목 재선정은 하지 않는다(walk-forward 재선정 미구현). 뉴스가 `MIN_NEWS_TICKERS` 미만인 날짜는 기준 비중으로 두고 `fallback_dates` 에 남긴다.
- 백테스트는 adj_close(배당 재투자)·거래비용 5bp·소수 주식 가정이며 세금·슬리피지는 없다. 시총 비중 템플릿은 현재 발행주식수 기준 근사다.

> **2026-10-24 이후**: 이 폴더는 실험 기록으로 동결됐다. 서비스 구현은 `backend/analysis/`(일곱 모듈 패키지, Repository 직결, 대화형 요청 확정, 큐·워커·API·7섹션 리포트)로 옮겼다. 자세한 구조는 `backend/analysis/README.md`, 남은 계획은 `docs/TODO.md`.
