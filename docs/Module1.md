# Module1. 사용자 정보와 분석 요청 관리

전체 구조: [Module_prototype_v2.md](Module_prototype_v2.md)

## 1. 역할

이 모듈은 사용자 프로필을 저장하고, 투자 아이디어를 실제 분석 요청으로 만드는 역할을 맡는다. 이전 요청과 리포트를 연결해 재분석과 수정 요청에 필요한 이력도 제공한다.

핵심은 저장된 기본 조건과 이번 분석 조건을 구분하는 것이다. 프로필을 수정해도 이전 분석 결과가 바뀌어서는 안 된다. 각 요청에는 사용한 프로필 버전과 최종 조건을 별도로 보관한다.

## 2. 입력과 출력

| 구분 | 내용 |
| --- | --- |
| 입력 | 프로필, 자연어 아이디어, 이번 조건 변경분, 질문 답변, 기준 리포트 |
| 출력 | 확정 요청, 조건 확인 데이터, 실행 이력, LLM용 이전 대화 요약, 수정 요청 |
| 연동 | Module2에서 기준일·환율 조회, Module3에서 의도 해석, Module5에서 결과·비교 조회, Module7에서 사용자 입력 |

## 3. 처리 흐름

### 프로필 저장

사용자는 투자 가능 금액, 투자기간, 투자성향과 손실 감내 수준을 입력한다. 나머지 항목은 기본값을 적용하고 저장 전에 함께 보여 준다. 간이 진단으로 산출한 투자성향과 사용자가 최종 선택한 투자성향은 따로 저장한다. 두 값이 다르면 변경 여부를 확인해 기록한다.

수치 범위와 제약 충돌은 코드로 검증한다. 잘못된 항목은 한 번에 모아 화면에 반환하며, 오류가 있는 프로필은 저장하지 않는다. 저장할 때마다 버전을 올리고 이전 버전을 유지한다. 프로토타입은 단일 사용자와 프로필 하나를 기준으로 하며 로그인·계정 관리는 포함하지 않는다.

### 이번 분석 요청 준비

저장된 프로필에 아이디어 원문과 이번에 변경한 조건을 합친다. 이번 변경은 해당 요청에만 적용하고 프로필 자체는 사용자가 별도로 수정할 때만 바꾼다.

먼저 코드로 검사할 수 있는 제약을 확인한다. 이후 Module2에서 데이터 마감, 분석 기준일과 환율을 조회하고 파생값을 계산한다. 이 과정에서 필요한 자료가 없으면 요청 준비를 중단한다.

Module3의 의도 해석기에 요청과 이전 실행 요약을 전달한다. 해석 결과에 부족·충돌·모호 항목이 있으면 우선순위가 가장 높은 질문 하나를 사용자에게 보여 준다. 답변을 반영한 뒤 다시 검증하고 해석한다. 질문은 최대 다섯 번까지 진행하며, 그 뒤에도 조건이 정해지지 않으면 분석을 시작하지 않고 이유를 설명한다.

질문이 끝나면 기본 조건, 이번 조건, 변경 항목과 지원 가능한 제약을 보여 준다. 사용자가 “분석 시작”을 누른 뒤 확정 요청을 저장하고 실행 대기열에 등록한다. 확정 전에도 의도 해석과 자료 조회는 수행하지만, 종목 선정 이후의 본 분석은 시작하지 않는다.

### 이력 조회와 재분석

요청, 실행, 통합 결과, 리포트와 모의투자를 식별자로 연결한다. 리포트 목록에는 전략명, 원래 요청 요약, 분석 기준일, 작성일, 결과 상태와 모의투자 여부를 반환한다.

“같은 조건으로 재분석”은 기준 리포트의 확정 요청을 복제하고 최신 분석 기준일을 적용하는 작업이다. 최신 프로필로 바꿔 실행하는 기능과 구분한다. 기준 리포트와 원래 요청은 보존하고 새 요청과 실행을 만든다.

LLM에는 최근 요청의 아이디어·테마·선정 방식·결과 상태, 질문 답변, 기준 리포트의 전략과 검증 요약, 이전에 거부하거나 수정한 항목을 정리해 전달한다. 입력 한도를 넘으면 오래된 내용부터 줄인다. 이전 이력은 해석을 돕는 참고 자료이며, 이번 확정 조건을 자동으로 바꾸는 근거가 될 수 없다.

### 기존 전략 수정

사용자가 기준 리포트와 자연어 수정 요청을 제출하면 LLM이 변경할 필드, 제안 값과 이유를 정리한다. “이 기업은 빼 달라”는 제외 종목처럼 지원되는 입력 필드로 옮긴다. 지원되지 않는 요청은 반영할 수 없다고 반환한다.

코드 검증을 거친 변경 초안을 원안과 나란히 보여 주고 확인을 받는다. 필요하면 같은 질문 흐름을 사용한다. 확정된 수정안은 `revision` 요청으로 저장하고 별도 분석을 실행한다. Module5가 원안과 수정안의 비교 결과를 만든다.

공정한 비교를 위해 백테스트 기간, 초기자본·적립, 비교지수와 리밸런싱 규칙은 원안과 같게 유지한다. 사용자가 이 조건 자체를 바꾸려는 경우에는 현재 수정안 비교 범위로 처리할 수 없음을 설명한다. 원안과 다른 평가 조건을 허용하는 기능은 별도 정책 확정이 필요하다.

## 4. 요청 데이터

### 사용자 입력 필드

| 그룹 | 필드와 값 | 처리 |
| --- | --- | --- |
| `profile` | `age_band`: 20s·30s·40s·50s·60s+; `investment_experience`: none·beginner·intermediate·advanced | 해석과 설명 수준 참고 |
| `profile` | `financial_knowledge`: basic·intermediate·expert; `investable_ratio_of_assets`: 0~1 | 용어 설명과 위험 해석 참고 |
| `capital` | `initial_amount` > 0; `currency`: KRW·USD | 범위 검증 |
| `capital` | `monthly_contribution` ≥ 0; `contribution_day`: 1~28 | 적립 규칙 검증 |
| `horizon` | `target_years` > 0; `purpose`: wealth_growth·income·capital_preservation·retirement | 투자기간과 목적 해석 |
| `horizon` | `backtest_years`: 정수 ≥ 1, 기본 3 | 과거 평가기간 결정 |
| `horizon` | `start_date` | 서비스 요청에서는 분석 기준일을 적용 |
| `risk` | `risk_tolerance`: conservative·moderate·aggressive; `loss_reaction`: sell·hold·buy_more | 위험 파라미터 해석 |
| `risk` | `max_drawdown_tolerance`: 0~1; `target_annual_return`: 실수; `benchmark`: 티커 | 손실·목표 기준과 비교지수 |
| `constraints` | `universe`: SP500·NASDAQ100·KOSPI200, 복수 선택; `asset_types`: stock·etf | 후보 범위 |
| `constraints` | `num_holdings`: min·target·max | 종목 수 검증 |
| `constraints` | `max_weight_per_stock`, `max_weight_per_sector`: 0~1 | 비중 상한 검증 |
| `constraints` | `min_cash_ratio`: 0~1 | 양수 입력의 지원 정책 확인 필요 |
| `constraints` | `exclude_tickers`, `exclude_sectors`, `exclude_themes`, `must_include_tickers` | 포함·제외 목록 |
| `constraints` | `rebalance`: count ≥ 0, unit ∈ 2w·1m·1q·6m·1y | 운용 주기 |
| `constraints` | `allow_leverage`, `allow_short` | 현재 false만 지원 |
| `constraints` | `min_market_cap_usd`, `min_avg_daily_volume_usd`: ≥ 0 | 규모·유동성 조건 |
| `strategy_preference` | `template`: low_per·quality·momentum·low_volatility·high_dividend | 정량 선정 방식 |
| `strategy_preference` | `baseline_weighting`: equal_weight·market_cap·inverse_volatility·min_variance | 기준 비중 방식 |
| `strategy_preference` | `use_news_tilt`: bool | 뉴스 기반 비중 조정 사용 여부 |
| `natural_language` | `idea`: 5자 이상; `language`: 언어 코드 | 투자 의도 해석 |

정해진 수치와 열거형은 코드로 검사한다. 목적, 경험, 성향과 아이디어는 LLM이 해석하되 사용자가 지정한 조건을 덮어쓰지 않는다.

### 저장 객체

| 파일 | 핵심 필드 |
| --- | --- |
| `store/data/profile.json` | `schema_version`, `profile_id`, `current_version`, `versions` |
| `store/data/requests/<request_id>.json` | `schema_version`, `request_id`, `created_at`, `mode`, `base_report_id`, `profile_version`, `idea`, `language`, `overrides`, `questions`, `effective_request`, `status`, `confirmed_at`, `run_id` |
| `store/data/runs.json` | `schema_version`, `runs`: 실행별 요청·상태·시각·결과 경로·리포트·오류 |
| `output/<run_id>/01_request.json` | 확정 요청, 분석 기준일, 환율과 환산액 등 파생값 |

프로필의 `versions`에는 버전, 생성 시각, 진단 성향, 최종 성향과 변경 여부, 각 조건 묶음을 넣는다. 질문에는 `seq`, `field`, `kind`, `question_ko`, `options`, `answer`, `answered_at`을 저장한다. `kind`는 missing·conflict·ambiguous 중 하나다.

요청 `mode`는 new·rerun·revision, 상태는 draft·confirmed·cancelled다. 리포트 식별자는 실행 식별자와 같게 사용한다. 기존 ID 형식은 요청 `req_<YYYYMMDD>_<HHMMSS>_<4hex>`, 실행 `run_<YYYYMMDD>_<HHMMSS>`다. 같은 초에 생성되는 실행의 충돌 방지 방식은 구현 시 정해야 한다.

## 5. 검증과 예외 처리

종목 수는 `min ≤ target ≤ max`를 만족해야 한다. 필수 포함 종목 수는 최대 보유 종목 수를 넘을 수 없고, 같은 종목을 포함·제외 목록에 동시에 넣을 수 없다. 섹터 상한은 종목 상한 이상이어야 한다. 양수 비중을 배분할 수 없는 조건은 분석 전에 사용자에게 수정하도록 반환한다.

기존 명세의 사전 검사식은 `종목 상한 × 최소 종목 수 ≥ 1`이다. 이 식은 최소 종목 수가 적고 실제 목표 종목 수가 충분한 요청까지 거부할 수 있다. 따라서 최종 구성 가능성 검사는 실제 선정 수와 섹터 구성을 반영해야 하며, 이 사전 검사식을 그대로 사용할지는 확인이 필요하다. Module3의 선정 결과와 Module4의 최적화 제약도 함께 검사한다.

LLM이 해석해야 하는 모호함은 질문으로 해결하고, 코드로 판정되는 범위 오류는 입력 수정으로 처리한다. 질문 한도 초과, 환율 누락이나 데이터 범위 조회 실패는 본 분석을 시작하지 않는다.

## 6. 구현 연결과 확인 사항

기존 `stage1_normalize.py`의 검증과 파생값 계산을 재사용한다. 서비스 입력 조립, 질문 답변 흐름과 저장은 추가해야 한다. `stage2_intent.py`와 `prompts/02_intent/`에는 이전 이력과 수정 모드를 연결한다. 저장은 공통 `store.py`, 실행은 대기열, 결과 조회는 DB 접근 계층을 사용한다.

프로필 저장, 이력 관리와 수정 요청은 원문에서 설계 단계로 기록되어 있다. 요청 정규화는 기존 구현을 보완하는 범위다.

확정해야 할 사항은 양수 `min_cash_ratio` 요청의 처리, `rebalance.count = 0`의 의미, 동일 초 실행 ID 충돌 방지다. ETF도 입력에 있지만 후보 DB·산업분류·필수 지표가 갖춰져 있는지 확인해야 한다. 지원하지 못하는 옵션은 화면에서 선택하게 한 뒤 조용히 무시하지 않는다.

## 7. 완료 기준

- 프로필 수정 후에도 기존 리포트의 조건과 수치가 유지된다.
- 질문은 필요한 항목에만 한 번에 하나씩 나오고 다섯 번을 넘지 않는다.
- 사용자 확인 전에는 본 분석이 대기열에 등록되지 않는다.
- 재분석과 수정안은 별도 요청·실행·리포트로 남는다.
- 수정안 비교에는 원안과 같은 평가 조건이 사용된다.
- 이전 이력에 비밀값이나 불필요한 원문 전체가 포함되지 않는다.
