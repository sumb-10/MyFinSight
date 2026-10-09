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
| `output/` | 단계별 산출물 + `output/prompts/` 에 실제 렌더링된 프롬프트 (git 제외) |

## 파이프라인

```
[데이터]  fetch_data.py (가격 15년)  fetch_fundamentals.py (재무·info)  build_descriptor.py (디스크립터)
[요청]    01 정규화·검증 ─▶ 02 의도 해석 (LLM#1) ─▶ 03 후보 검색 ─▶ 04 후보 분류 (LLM#2, 배치) ─▶ 05 정량 스크린·선정 ─▶ (06 근거 서술, LLM#3)
[구성]    07 확인·백테스트 사양·재선정 ─▶ 08 시장모형·베이스라인 템플릿 ─▶ 09 뷰 생성 (LLM#4) ─▶ 10 Black-Litterman 타겟
[검증]    11 bt 백테스트 (9개 포트폴리오 + 벤치마크, 체크포인트) ─▶ 12 규칙 검증·추천
[리포트]  13 결과 통합 (13_results.json) ─▶ 14 리포트 문서 (LLM#5a 해석 + #5b 서술 → 14_report.json) ─▶ 15 퍼블리시 (Front/public/pipeline/report.json) ─▶ Front #/pipeline 화면
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
| 11 | `stage11_backtest.py` | – | 10 + 가격 → `11_backtest_results.json` (포트폴리오별 headline·metrics·money·일별 series·리밸런싱 체크포인트·적립 원장·이벤트·뷰 진단) + `11_daily_panel.parquet` |
| 12 | `stage12_validate.py` | – | 11·02·01 → `12_validation.json` (R1~R8 pass/warn/fail, 비교표, 추천 포트폴리오) |
| 13 | `stage13_collect.py` | – | 01~12 전체 → `13_results.json` (**모든 결과를 하나로 모은 파일**; 이후 단계·DB 저장·재분석의 유일한 입력) |
| 14 | `stage14_report.py` (+ `report_blocks.py`) | #5a 해석, #5b 서술 | 13 → `14_report.json` (렌더링용 블록 모델: KPI·표·도넛·누적수익·낙폭·막대·깔때기·카드·체크포인트·용어집 + 초보자용 서술) |
| 15 | `stage15_publish.py` | – | 14 → `Front/public/pipeline/report.json` (Front 의 `#/pipeline` 화면이 읽음) |

## 실행

```bash
$P scripts/fetch_data.py --years 15          # 1회. 가격·유니버스 → ~/.myfinsight/data/raw
$P scripts/fetch_fundamentals.py             # 1회. 재무제표·info·배당 (Yahoo 429 시 나중에 재실행, 종목별 캐시로 이어받음)
$P scripts/build_descriptor.py               # 1회. 디스크립터 생성 (재무 수집 후 다시 실행하면 사업 설명이 채워짐)

$P scripts/run_pipeline.py --request input/01_user_request.example.jsonc      # 1~5단계, stub 모드 (기본, API 호출 없음)
$P scripts/run_pipeline.py --stop-at 15                                      # 1~15단계 (7~15 는 input/02_backtest_request.jsonc 사용)
MYFINSIGHT_LLM=api $P scripts/stage14_report.py && $P scripts/stage15_publish.py   # 리포트 서술을 gpt-6-luna 로 새로 생성 → Front 에 반영
$P scripts/backtest_engine.py && $P scripts/backtest_metrics.py              # 백테스트 엔진·지표 자체 검증
$P scripts/stage12_validate.py --max-drawdown 0.30                           # 검증 기준을 바꿔 다시 판정 (백테스트 재실행 없음)
$P scripts/portfolio.py                                                      # 포트폴리오 수학 자체 검증 (BL 수렴·뷰 방향·제약)
MYFINSIGHT_LLM=api $P scripts/run_pipeline.py --explain                      # 실제 LLM 호출 + 비용 리포트
$P scripts/llm_cost_report.py                                                # 마지막 실행의 토큰·비용 요약
```

리포트 화면: `cd Front && source ~/.nvm/nvm.sh && nvm use && pnpm dev` 후 http://localhost:5173/#/pipeline (화면 코드는 `Front/src/pipeline/`, 기존 앱 화면은 `#/home`).

LLM 설정은 `scripts/llm_config.py` 한 곳(모델명·생성 옵션·단가·.env 위치)에서 바꾼다. 모드는 `MYFINSIGHT_LLM=stub|api`. API 모드는 호출마다 `output/llm_usage.jsonl` 에 토큰·비용을 기록하고 원문 응답을 `output/llm_raw/` 에 남긴다(stub 으로 재사용 가능).

포트폴리오 설정(추정 윈도 756일, Ledoit-Wolf 수축, τ=0.05, 위험회피 δ, 뷰 수익률 범위, 템플릿 목록)은 `scripts/portfolio_config.py`, 백테스트 설정(거래비용 5bp, 소수 주식, 무위험수익률 4%, 체크포인트 빈도, 드리프트 허용치, 변동성 밴드)은 `scripts/backtest_config.py` 에 있다.

11단계 출력 구조: 포트폴리오마다 `headline`(KPI 6개) / `metrics`(return·risk·risk_adjusted·vs_benchmark·vs_baseline·composition·trading·stability) / `money`(적립 포함 평가금액·XIRR) / `series`(일별 지수·평가금액·낙폭, 날짜 축은 `series_dates` 공통) / `checkpoints`(리밸런싱일마다 비중 before·after·target, 보유 종목, 거래, 구간 성과 `since_last`, 누적 지표 `to_date`) / `contribution_ledger` / `events` / `view_diagnostics`.

## 알려진 한계

- 디스크립터와 유니버스는 현재 시점 스냅샷이라 과거 백테스트에 생존 편향이 있다.
- yfinance 재무제표는 분기 5개까지라 `low_per`/`quality` 는 최근 4년 범위에서만 as-of 계산이 가능하다.
- 사업 설명이 규칙 기반("회사명 — 세부산업")인 동안은 키워드 매칭 오탐이 많다. 4단계 분류 LLM 이 걸러내며, 재무 수집·LLM#0 실행 후 개선된다.
- 9단계 뷰는 뉴스 데이터 없이 LLM 이 만든 플레이스홀더라 기준일 이후 정보가 섞일 수 있다(`hindsight_risk: true`). 시총 비중은 현재 발행주식수 × 과거 종가의 근사치다.
- 10단계 타겟 비중은 구성일 기준 정적이다. 실제 서비스는 리밸런싱마다 뷰를 재생성해야 한다. 11단계도 같은 정적 비중을 리밸런싱마다 복원한다(walk-forward 재선정은 미구현).
- 백테스트는 adj_close(배당 재투자)·거래비용 5bp·소수 주식 가정이며 세금·슬리피지는 없다. 시총 비중 템플릿은 현재 발행주식수 기준 근사다.
