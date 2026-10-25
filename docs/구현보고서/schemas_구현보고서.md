# schemas 구현보고서

[전체 안내](README.md)

> 작성 기준: 2026-10-25 작업 공간의 실제 소스. 기존 설계 문서는 배경 참고용이며 아래 동작 설명은 구현을 기준으로 합니다.

대상: Python 파일 10개 · 클래스 79개 · 함수/메서드 13개(중첩 함수와 비공개 보조 함수 포함).

[역할](#role) · [파일 구성](#files) · [처리 흐름](#flow) · [클래스](#classes) · [함수](#functions) · [모듈 연계](#interactions) · [오류·검증](#verification)

<a id="role"></a>
## 1. 모듈의 역할과 용어

`schemas`는 모듈 사이에 주고받는 자료의 모양과 일부 규칙을 Pydantic 모델로 정의합니다. 필드는 자료의 칸, 자료형은 그 칸에 들어갈 값의 종류, validator는 여러 칸이 함께 만족해야 하는 조건입니다. `model_validate()`로 검사하고 `model_dump(mode="json")`으로 JSON 호환 자료를 만듭니다.

모델은 자료 계약이며 업무를 실행하는 서비스가 아닙니다. `UserRequest`는 조건을 묶고 `DialogService`가 대화를 수행합니다. `Portfolio`는 비중을 담고 `construct()`가 비중을 계산합니다. `ReportDoc`는 문서 참조를 확인하고 실제 인용·금지 표현은 별도 게이트가 확인합니다.

이름이 같은 클래스도 경로가 다르면 다른 모델입니다. `schemas.intent.ReportSettings`는 언어·설명 수준이고 루트 `settings.ReportSettings`는 문서 검증 정책입니다. `schemas.intent.Conflict`는 충돌 설명 데이터이고 루트 `errors.Conflict`는 예외입니다.

<a id="files"></a>
## 2. 파일 구성과 책임

| 파일 | 책임 | 문서 내 해설 |
| --- | --- | --- |
| [schemas/__init__.py](../../backend/analysis/schemas/__init__.py) | 업무별 주요 모델 공개 재노출과 __all__ 구성 | 정의 없음 |
| [schemas/backtest.py](../../backend/analysis/schemas/backtest.py) | 기간·자본·구성 사양·체크포인트·성과 모델 | [클래스 15 · 함수 3](#file-schemas-backtest-py) |
| [schemas/dialog.py](../../backend/analysis/schemas/dialog.py) | 질문·답·수정 초안·저장 대화·API 상태 모델 | [클래스 11 · 함수 0](#schemas-dialog-py-QuestionOption-18) |
| [schemas/intent.py](../../backend/analysis/schemas/intent.py) | 테마·정량 선정·위험·의견·검증·서술 선호 모델 | [클래스 11 · 함수 2](#file-schemas-intent-py) |
| [schemas/portfolio.py](../../backend/analysis/schemas/portfolio.py) | 시장모형·기준/BL 비중·의견·타겟 모델 | [클래스 8 · 함수 2](#file-schemas-portfolio-py) |
| [schemas/report.py](../../backend/analysis/schemas/report.py) | 근거·지원 블록·섹션·문서 참조 계약 | [클래스 3 · 함수 2](#file-schemas-report-py) |
| [schemas/request.py](../../backend/analysis/schemas/request.py) | 사용자 조건·교차 제약·파생 요청 모델 | [클래스 13 · 함수 3](#file-schemas-request-py) |
| [schemas/results.py](../../backend/analysis/schemas/results.py) | 사용자/무결성 검사와 통합 결과 일관성 | [클래스 4 · 함수 1](#file-schemas-results-py) |
| [schemas/run.py](../../backend/analysis/schemas/run.py) | 큐·단계·화면 묶음·폴링 상태 모델 | [클래스 4 · 함수 0](#schemas-run-py-RunIndexEntry-21) |
| [schemas/selection.py](../../backend/analysis/schemas/selection.py) | 산업 계층·후보·판정·선정/제외 모델 | [클래스 10 · 함수 0](#schemas-selection-py-GicsLevel-10) |

<a id="flow"></a>
## 3. 처리 흐름과 예시

| 경계 | 주 모델 | 생성·사용처 |
| --- | --- | --- |
| 사용자 조건 | UserRequest → NormalizedRequest | M1 조립·검증·파생, 실행기 입력 |
| 대화 | AnalysisRequestDoc → DialogState | 로컬 저장 원본 → API 공개 상태 |
| 투자 해석 | IntentSpec | M3 해석 → 검색·구성·검증 |
| 종목 선정 | Candidates → Tagging → Selection | M3 검색 → 분류 → 정량 선정 |
| 구성 | BacktestSpec·MarketModel·Views·TargetPortfolios | M4 → M5 |
| 과거 평가 | BacktestResults → Validation → ResultsBundle | M5 계산 → 판단 → 통합 |
| 공개 문서 | ReportDoc | M5 문서 → API → 화면 |
| 실행 상태 | RunIndexEntry·RunStep·RunStatus | 큐·DB 기록 → API 폴링 |

예를 들어 `Portfolio`의 주식 비중 합이 0.8이면 cash_weight=0.2가 있어야 합계 검증을 통과합니다. 그러나 종목 상한 위반은 이 모델의 합계 검사만으로 잡지 않습니다. `Constraints`에서 최소·목표·최대 순서가 잘못되면 요청 단계에서 오류가 나고, `ReportDoc`에서 없는 시계열 ID를 참조하면 문서 조립이 실패합니다.

`Field(ge=..., le=...)`는 포함 경계, `gt/lt`는 엄격 경계, `min_length`는 최소 길이입니다. `default_factory`는 객체마다 새 기본값을 만드는 함수입니다. 기본이 없는 필드는 필수이고 `None` 허용 여부와 필수 여부는 별개입니다.

기본값 표에는 소스에 선언된 값·생성 표현을 그대로 기록합니다. `dict` 내부 구조가 자동으로 완전히 검증된다는 의미는 아닙니다. 상속 모델인 Question·NormalizedRequest는 부모 필드까지 함께 갖습니다. `schemas/__init__.py`는 주요 모델을 재노출하지만 모든 모델이 반드시 이 진입점으로만 접근되는 것은 아닙니다.


<a id="classes"></a>
## 4. 클래스 상세

필드 표는 해당 클래스에서 직접 선언한 필드입니다. 상속 필드는 부모 클래스 설명을 함께 읽습니다. `Field(...)`의 범위는 선언된 검증이며, 서비스에서 추가하는 조건은 함수 설명에 구분합니다.

<a id="schemas-backtest-py-Confirmation-13"></a>
### `Confirmation`

<!-- source-symbol: schemas/backtest.py:13:Confirmation -->
[backtest.py](../../backend/analysis/schemas/backtest.py#L13)

백테스트 확인 입력의 종목 추가·제외 목록과 확인 플래그입니다. selection_confirmed 필드의 존재만으로 상위 코드가 실행을 별도 차단한다고 가정하지 않습니다.

기반: `BaseModel`.

| 필드 | 자료형 | 기본값 또는 생성 방식 | 선언된 제약·설명 |
| --- | --- | --- | --- |
| `selection_confirmed` | `bool` | `True` | 백테스트 종목 확인 플래그 |
| `removed_tickers` | `list[str]` | `[]` | 과거 평가에서 제거 요청한 종목 |
| `added_tickers` | `list[str]` | `[]` | 과거 평가에 추가 요청한 종목 |


<a id="schemas-backtest-py-BacktestWindow-19"></a>
### `BacktestWindow`

<!-- source-symbol: schemas/backtest.py:19:BacktestWindow -->
[backtest.py](../../backend/analysis/schemas/backtest.py#L19)

요청한 백테스트 시작/끝, 시작일 재선정, 비교지수 override, 적립 포함 여부입니다. 날짜 순서를 모델에서 검증합니다.

기반: `BaseModel`.

| 필드 | 자료형 | 기본값 또는 생성 방식 | 선언된 제약·설명 |
| --- | --- | --- | --- |
| `start_date` | `date` | `필수 입력` | 요청 과거 평가 시작 날짜 |
| `end_date` | `date` | `필수 입력` | 요청 평가 종료일 |
| `reselect_at_start` | `bool` | `True` | 과거 시작일 자료로 정량 재선정할지 |
| `benchmark` | `str \| None` | `None` | 주 비교지수 티커 또는 결과 |
| `include_contributions` | `bool` | `True` | 적립을 과거 평가에 포함할지 |

메서드·속성: [_order](#schemas-backtest-py-BacktestWindow-_order-27).


<a id="schemas-backtest-py-ViewsConfig-33"></a>
### `ViewsConfig`

<!-- source-symbol: schemas/backtest.py:33:ViewsConfig -->
[backtest.py](../../backend/analysis/schemas/backtest.py#L33)

시작일 의견 세트 수와 세트당 의견 수의 요청 범위를 제한합니다. 현재 기본 실행 단계는 이 요청 객체의 값을 읽지 않고 AnalysisSettings.news의 의견 개수를 사용합니다.

기반: `BaseModel`.

| 필드 | 자료형 | 기본값 또는 생성 방식 | 선언된 제약·설명 |
| --- | --- | --- | --- |
| `n_sets` | `int` | `5` | 의견 세트 수; ge=1, le=10 |
| `views_per_set` | `int` | `4` | 세트당 의견 개수; ge=1, le=8 |


<a id="schemas-backtest-py-WalkforwardConfig-38"></a>
### `WalkforwardConfig`

<!-- source-symbol: schemas/backtest.py:38:WalkforwardConfig -->
[backtest.py](../../backend/analysis/schemas/backtest.py#L38)

날짜별 재구성 사용 여부와 의견 개수를 표현하는 요청 모델입니다. 현재 기본 레지스트리는 enabled와 관계없이 10w를 실행하고 의견 개수도 AnalysisSettings.news를 사용합니다.

기반: `BaseModel`.

| 필드 | 자료형 | 기본값 또는 생성 방식 | 선언된 제약·설명 |
| --- | --- | --- | --- |
| `enabled` | `bool` | `True` | 해당 기능·규칙의 활성화 |
| `view_sets` | `int` | `1` | 날짜별 의견 세트 수; ge=1, le=5 |
| `views_per_set` | `int` | `4` | 세트당 의견 개수; ge=1, le=8 |


<a id="schemas-backtest-py-ForwardConfig-44"></a>
### `ForwardConfig`

<!-- source-symbol: schemas/backtest.py:44:ForwardConfig -->
[backtest.py](../../backend/analysis/schemas/backtest.py#L44)

현재 구성 생성 여부와 선택 기준일을 표현합니다. 현 단계 레지스트리는 현재 구성을 항상 실행하므로 이 enabled가 전체 실행을 자동 제어하지는 않습니다.

기반: `BaseModel`.

| 필드 | 자료형 | 기본값 또는 생성 방식 | 선언된 제약·설명 |
| --- | --- | --- | --- |
| `enabled` | `bool` | `True` | 해당 기능·규칙의 활성화 |
| `as_of` | `date \| None` | `None` | 자료 판단 기준일 |


<a id="schemas-backtest-py-BacktestRequest-49"></a>
### `BacktestRequest`

<!-- source-symbol: schemas/backtest.py:49:BacktestRequest -->
[backtest.py](../../backend/analysis/schemas/backtest.py#L49)

요청 ID에 백테스트 확인·기간·의견·날짜별 구성·현재 구성 설정을 묶은 선택 입력입니다. 워커의 내부 override 또는 개발 CLI에서 주입할 수 있습니다.

기반: `BaseModel`.

| 필드 | 자료형 | 기본값 또는 생성 방식 | 선언된 제약·설명 |
| --- | --- | --- | --- |
| `request_id` | `str` | `필수 입력` | 대화·분석 요청을 연결하는 ID |
| `confirmation` | `Confirmation` | `Confirmation()` | 과거 평가 종목 확인·추가·제외 요청 |
| `backtest` | `BacktestWindow` | `필수 입력` | 과거 평가 창 또는 평가 결과 |
| `views` | `ViewsConfig` | `ViewsConfig()` | 의견 요청 수 또는 의견 집합 |
| `walkforward` | `WalkforwardConfig` | `WalkforwardConfig()` | 날짜별 재구성 조건·결과 |
| `forward_construction` | `ForwardConfig` | `ForwardConfig()` | 현재 기준일 구성 요청 조건 |


<a id="schemas-backtest-py-Period-58"></a>
### `Period`

<!-- source-symbol: schemas/backtest.py:58:Period -->
[backtest.py](../../backend/analysis/schemas/backtest.py#L58)

실제 처리 창의 start/end, 첫 구성일 as_of, 거래일 수를 담습니다. 요청 기간과 자료 보정 후 기간이 다를 수 있습니다.

기반: `BaseModel`.

| 필드 | 자료형 | 기본값 또는 생성 방식 | 선언된 제약·설명 |
| --- | --- | --- | --- |
| `start` | `date` | `필수 입력` | 구간 시작 |
| `end` | `date` | `필수 입력` | 구간 끝 |
| `as_of` | `date` | `필수 입력` | 실제 백테스트의 첫 구성 거래일 |
| `trading_days` | `int` | `필수 입력` | 연간 거래일 기준 또는 해당 기간 거래일 수 |


<a id="schemas-backtest-py-CapitalSpec-65"></a>
### `CapitalSpec`

<!-- source-symbol: schemas/backtest.py:65:CapitalSpec -->
[backtest.py](../../backend/analysis/schemas/backtest.py#L65)

확정 백테스트 자본·고정 USD 적립·적립일·원래 통화·원화 금액·시작일 환율을 담습니다. 현재 구성 환율과 구분하는 계약입니다.

기반: `BaseModel`.

| 필드 | 자료형 | 기본값 또는 생성 방식 | 선언된 제약·설명 |
| --- | --- | --- | --- |
| `initial_amount_usd` | `float` | `필수 입력` | USD 환산 초기자본 |
| `monthly_contribution_usd` | `float` | `필수 입력` | 백테스트가 사용할 USD 월 적립금 |
| `contribution_day` | `int` | `필수 입력` | 매월 적립 기준 일자 |
| `include_contributions` | `bool` | `필수 입력` | 적립을 과거 평가에 포함할지 |
| `currency` | `str \| None` | `None` | 입력/종목 통화 |
| `initial_amount_krw` | `float \| None` | `None` | 원래 KRW 초기자본 |
| `monthly_contribution_krw` | `float \| None` | `None` | 원래 KRW 월 적립금 |
| `fx_rate` | `float \| None` | `None` | 1 USD당 원화 환율; 요청 USD 입력 일부 경로는 1 사용 |
| `fx_date` | `date \| None` | `None` | 사용 환율의 관측일 |
| `fx_source` | `str \| None` | `None` | 환율 출처 |


<a id="schemas-backtest-py-SelectionRow-78"></a>
### `SelectionRow`

<!-- source-symbol: schemas/backtest.py:78:SelectionRow -->
[backtest.py](../../backend/analysis/schemas/backtest.py#L78)

백테스트 선정 표 한 행의 티커·회사·섹터·순위·지표값입니다.

기반: `BaseModel`.

| 필드 | 자료형 | 기본값 또는 생성 방식 | 선언된 제약·설명 |
| --- | --- | --- | --- |
| `ticker` | `str` | `필수 입력` | 가격 조회 표기의 종목 코드 |
| `name` | `str` | `필수 입력` | 종목·객체 이름 |
| `sector` | `str` | `필수 입력` | 산업 섹터명 또는 모델 |
| `rank` | `int` | `필수 입력` | 선정 순위 |
| `metric_value` | `float` | `필수 입력` | 선정 지표 값 |


<a id="schemas-backtest-py-SelectionSpec-86"></a>
### `SelectionSpec`

<!-- source-symbol: schemas/backtest.py:86:SelectionSpec -->
[backtest.py](../../backend/analysis/schemas/backtest.py#L86)

과거 재선정 또는 현재 목록 재사용의 출처, 지표, 비어 있지 않은 티커, 표, 현재 대비 차이·배분 불충분 정보를 담습니다.

기반: `BaseModel`.

| 필드 | 자료형 | 기본값 또는 생성 방식 | 선언된 제약·설명 |
| --- | --- | --- | --- |
| `source` | `Literal['reselected_at_start', 'original']` | `필수 입력` | 자료·설명·선정의 출처 식별 |
| `metric` | `str` | `필수 입력` | 정량 지표 코드 |
| `tickers` | `list[str]` | `필수 입력` | 관련 종목 티커 목록; min_length=1 |
| `table` | `list[SelectionRow]` | `필수 입력` | — |
| `diff_vs_original` | `dict[str, list[str]]` | `필수 입력` | 현재 선정 대비 과거 시작 선정의 추가·제외 |
| `infeasibility` | `dict \| None` | `None` | 상한 아래 배분 불충분 사유·선택지 |
| `sector_overflow` | `dict \| None` | `None` | 섹터별 선호 종목 수를 넘겨 채운 내역 |


<a id="schemas-backtest-py-BacktestSpec-96"></a>
### `BacktestSpec`

<!-- source-symbol: schemas/backtest.py:96:BacktestSpec -->
[backtest.py](../../backend/analysis/schemas/backtest.py#L96)

확정 기간·자본·리밸런싱·비교지수·체결 규칙·과거 선정 결과의 입력 계약입니다. 기본 체결 규칙은 t-1 정보로 추정하고 t 종가에 체결하는 가정입니다.

기반: `BaseModel`.

| 필드 | 자료형 | 기본값 또는 생성 방식 | 선언된 제약·설명 |
| --- | --- | --- | --- |
| `request_id` | `str` | `필수 입력` | 대화·분석 요청을 연결하는 ID |
| `stage` | `str` | `'07_backtest_spec'` | 단계 산출물 종류 |
| `period` | `Period` | `필수 입력` | 평가 기간 |
| `capital` | `CapitalSpec` | `필수 입력` | 평가 자본 조건 또는 입력 자본 |
| `rebalance_rule` | `RebalanceRule` | `필수 입력` | 실행용 리밸런싱 규칙 |
| `benchmark` | `str` | `필수 입력` | 주 비교지수 티커 또는 결과 |
| `extra_benchmarks` | `list[str]` | `[]` | 추가 비교지수 티커 |
| `execution_rule` | `dict` | `생성 함수: {'information_cutoff': 't-1', 'execution_price': 't close', 'description_ko': '리밸런싱일 t 의 비중은 t−1 까지의 가격·뉴스로 계산하고 t 종가로 체결한다.'}` | 정보 마감과 체결 가격·시점 가정 |
| `selection` | `SelectionSpec` | `필수 입력` | 선정 사양·결과 |
| `warnings` | `list[str]` | `[]` | 문맥별 전체 경고 또는 문장 검사 메모 |


<a id="schemas-backtest-py-CheckpointWeights-115"></a>
### `CheckpointWeights`

<!-- source-symbol: schemas/backtest.py:115:CheckpointWeights -->
[backtest.py](../../backend/analysis/schemas/backtest.py#L115)

특정 평가 시점의 목표 비중·조정 전/후 비중·전/후 현금을 담습니다.

기반: `BaseModel`.

| 필드 | 자료형 | 기본값 또는 생성 방식 | 선언된 제약·설명 |
| --- | --- | --- | --- |
| `target` | `dict[str, float]` | `필수 입력` | 목표 종목 수 또는 목표 비중 |
| `before` | `dict[str, float] \| None` | `None` | 조정 전 종목 비중 |
| `after` | `dict[str, float]` | `필수 입력` | 조정 후 종목 비중 |
| `cash_before` | `float \| None` | `None` | 조정 전 현금 비중 |
| `cash_after` | `float` | `필수 입력` | 조정 후 현금 비중 |


<a id="schemas-backtest-py-Checkpoint-123"></a>
### `Checkpoint`

<!-- source-symbol: schemas/backtest.py:123:Checkpoint -->
[backtest.py](../../backend/analysis/schemas/backtest.py#L123)

리밸런싱·월말·종료 시점의 비중·보유·거래·수수료·금액·구간/누적 성과·의견 진단을 담는 상세 레코드입니다.

기반: `BaseModel`.

| 필드 | 자료형 | 기본값 또는 생성 방식 | 선언된 제약·설명 |
| --- | --- | --- | --- |
| `seq` | `int` | `필수 입력` | 질문·체크포인트·거래의 순번 |
| `date` | `date` | `필수 입력` | 레코드의 날짜 |
| `kind` | `Literal['rebalance', 'closing', 'monthly']` | `필수 입력` | 객체·전략·근거·시점의 종류 |
| `n_trading_days_to_date` | `int` | `필수 입력` | 시작 이후 해당 체크포인트까지 관측 간격 수 |
| `weights` | `CheckpointWeights` | `필수 입력` | 종목별 목표 또는 평가 비중 |
| `drift` | `dict \| None` | `None` | 목표 비중과 실제 비중의 차이·이탈 |
| `holdings` | `list[dict]` | `필수 입력` | 보유 수량·가격·평가액 상세 |
| `trades` | `list[dict]` | `[]` | 가상 매수·매도 내역 |
| `turnover` | `float \| None` | `None` | 매매 회전율 |
| `commission_usd` | `float` | `0.0` | USD 거래비용 |
| `money` | `dict` | `필수 입력` | 초기자본·적립·평가액·손익·IRR |
| `since_last` | `dict \| None` | `None` | 직전 체크포인트 이후 성과 |
| `to_date` | `dict \| None` | `None` | 분석 시작부터 누적한 성과 |
| `view_diagnostics_to_date` | `list[dict]` | `[]` | 체크포인트까지의 의견 실현 진단 |


<a id="schemas-backtest-py-PortfolioResult-140"></a>
### `PortfolioResult`

<!-- source-symbol: schemas/backtest.py:140:PortfolioResult -->
[backtest.py](../../backend/analysis/schemas/backtest.py#L140)

한 백테스트 후보의 목표·날짜별 비중·성과·금액·시계열·체크포인트·적립·의견 진단을 담습니다. matched이면 기준 ID·탐색 비율·총현금·목표·실행 횟수를 함께 보관합니다.

기반: `BaseModel`.

| 필드 | 자료형 | 기본값 또는 생성 방식 | 선언된 제약·설명 |
| --- | --- | --- | --- |
| `id` | `str` | `필수 입력` | 현재 객체의 식별자 |
| `kind` | `Literal['black_litterman', 'template', 'benchmark', 'alternative', 'matched']` | `필수 입력` | 객체·전략·근거·시점의 종류 |
| `mode` | `str` | `'static'` | 실행·구성·평가 방식 |
| `base_id` | `str \| None` | `None` | 맞춤 후보의 기준 포트폴리오 |
| `cash_ratio` | `float \| None` | `None` | 기준 주식 비중을 추가로 축소하는 c |
| `cash_ratio_total` | `float \| None` | `None` | 최종 실제 총현금 비중 |
| `match_target` | `float \| None` | `None` | 맞춤 후보가 목표로 한 낙폭 |
| `solver_runs` | `int \| None` | `None` | 현금 비율 탐색에 사용한 실제 평가 횟수 |
| `weights_by_date` | `dict \| None` | `None` | 날짜별 목표 비중 경로 |
| `views_by_date` | `dict \| None` | `None` | 날짜별 반영 의견 |
| `fallback_dates` | `list \| None` | `None` | 근거 부족 등으로 기준안을 쓴 날짜 |
| `name_ko` | `str` | `필수 입력` | 한국어 이름 |
| `title_ko` | `str \| None` | `None` | 화면 한국어 제목 |
| `portfolio_view` | `str \| None` | `None` | 의견 세트와 비중 구성에 대한 설명 |
| `target_weights` | `dict[str, float]` | `필수 입력` | 평가 또는 운용 목표 비중 |
| `headline` | `dict` | `필수 입력` | 대표 성과 수치 |
| `metrics` | `dict` | `필수 입력` | 분류별 상세 성과·위험 지표 |
| `money` | `dict` | `필수 입력` | 초기자본·적립·평가액·손익·IRR |
| `series` | `dict[str, list]` | `필수 입력` | 날짜축에 정렬된 수치 배열 |
| `monthly_returns` | `list[dict]` | `필수 입력` | — |
| `yearly_returns` | `dict[str, float \| None]` | `필수 입력` | — |
| `checkpoints` | `list[Checkpoint]` | `필수 입력` | 리밸런싱·종료 시점 상세 |
| `contribution_ledger` | `list[dict]` | `[]` | 월 적립 날짜·금액 원장 |
| `events` | `list[dict]` | `[]` | 낙폭·회복·적립·조정 사건 |
| `ticker_contribution` | `dict[str, float \| None]` | `{}` | 종목별 수익 기여도 |
| `ticker_total_return` | `dict[str, float \| None]` | `{}` | 종목별 전체 기간 수익률 |
| `view_diagnostics` | `list[dict]` | `[]` | 기본 지평에서의 의견 실현 진단 |
| `view_diagnostics_next_rb` | `list[dict]` | `[]` | 다음 리밸런싱까지의 의견 진단 |

메서드·속성: [_lengths](#schemas-backtest-py-PortfolioResult-_lengths-171).


<a id="schemas-backtest-py-BacktestResults-178"></a>
### `BacktestResults`

<!-- source-symbol: schemas/backtest.py:178:BacktestResults -->
[backtest.py](../../backend/analysis/schemas/backtest.py#L178)

동일 날짜축에서 평가한 전략·비교지수, 엔진 가정·순위·재현 정보·품질을 묶습니다. 모든 시계열 길이 일치를 검증합니다.

기반: `BaseModel`.

| 필드 | 자료형 | 기본값 또는 생성 방식 | 선언된 제약·설명 |
| --- | --- | --- | --- |
| `request_id` | `str` | `필수 입력` | 대화·분석 요청을 연결하는 ID |
| `stage` | `str` | `'11_backtest_results'` | 단계 산출물 종류 |
| `mode` | `str` | `'static_weights'` | 실행·구성·평가 방식 |
| `period` | `dict` | `필수 입력` | 평가 기간 |
| `engine` | `dict` | `필수 입력` | 과거 평가 엔진·자본·비용·일정 가정 |
| `series_dates` | `list[str]` | `필수 입력` | 전체 평가 날짜축 |
| `benchmark` | `PortfolioResult` | `필수 입력` | 주 비교지수 티커 또는 결과 |
| `benchmarks` | `list[PortfolioResult]` | `[]` | 비교지수 결과 목록 |
| `portfolios` | `list[PortfolioResult]` | `필수 입력` | 전략별 비중 또는 평가 결과 목록 |
| `ranking` | `list[dict]` | `필수 입력` | 후보 성과 또는 추천 순위 |
| `reproducibility` | `dict` | `필수 입력` | 설정·패널·엔진·타겟 해시 등 재현 메타 |
| `data_quality` | `dict \| None` | `None` | 가격 커버리지·채움·제외 요약 |
| `warnings` | `list[str]` | `[]` | 문맥별 전체 경고 또는 문장 검사 메모 |

메서드·속성: [_aligned](#schemas-backtest-py-BacktestResults-_aligned-194).


<a id="schemas-dialog-py-QuestionOption-18"></a>
### `QuestionOption`

<!-- source-symbol: schemas/dialog.py:18:QuestionOption -->
[dialog.py](../../backend/analysis/schemas/dialog.py#L18)

선택지의 실제 value와 표시 라벨, 선택적 다중 필드 patch와 아이디어 clarification입니다. 하나의 질문에서 종목 수와 상한을 함께 바꾸는 데 사용합니다.

기반: `BaseModel`.

| 필드 | 자료형 | 기본값 또는 생성 방식 | 선언된 제약·설명 |
| --- | --- | --- | --- |
| `value` | `Any` | `필수 입력` | 선택·변경·지표의 실제 값 |
| `label_ko` | `str` | `필수 입력` | 한국어 표시 라벨 |
| `patch` | `dict[str, Any] \| None` | `None` | 선택 시 여러 필드를 함께 바꾸는 사전 |
| `clarification` | `str \| None` | `None` | 선택 시 추가할 자연어 보충 |


<a id="schemas-dialog-py-QuestionProposal-25"></a>
### `QuestionProposal`

<!-- source-symbol: schemas/dialog.py:25:QuestionProposal -->
[dialog.py](../../backend/analysis/schemas/dialog.py#L25)

LLM 또는 코드가 제안한 질문입니다. 필드·종류·질문·보기·자유 입력 허용·우선순위·이유를 담고 실제 노출은 대화 서비스가 결정합니다.

기반: `BaseModel`.

| 필드 | 자료형 | 기본값 또는 생성 방식 | 선언된 제약·설명 |
| --- | --- | --- | --- |
| `field` | `str` | `필수 입력` | 대상 필드의 점 경로 |
| `kind` | `QuestionKind` | `필수 입력` | 객체·전략·근거·시점의 종류 |
| `question_ko` | `str` | `필수 입력` | 사용자에게 제시할 질문 |
| `options` | `list[QuestionOption]` | `[]` | — |
| `allow_free_text` | `bool` | `True` | 선택지 외 자유 답 허용 |
| `priority` | `int` | `3` | 작을수록 우선인 질문 순위; ge=1, le=5 |
| `why_ko` | `str` | `''` | 질문이 필요한 이유 |


<a id="schemas-dialog-py-Question-37"></a>
### `Question`

<!-- source-symbol: schemas/dialog.py:37:Question -->
[dialog.py](../../backend/analysis/schemas/dialog.py#L37)

제안 질문에 실제 순번·질문 시각·답·반영 값·건너뜀·응답 시각을 추가한 영속 기록입니다.

기반: `QuestionProposal`.

| 필드 | 자료형 | 기본값 또는 생성 방식 | 선언된 제약·설명 |
| --- | --- | --- | --- |
| `seq` | `int` | `필수 입력` | 질문·체크포인트·거래의 순번; ge=1 |
| `asked_at` | `str` | `필수 입력` | 질문 제시 시각 |
| `field_label_ko` | `str \| None` | `None` | 질문 대상 필드의 표시 라벨 |
| `answer` | `str \| None` | `None` | 사용자에게 표시하는 답 텍스트 |
| `applied` | `dict[str, Any] \| None` | `None` | 코드가 실제 반영한 답·patch |
| `free_text` | `str \| None` | `None` | 자유 답변 원문 |
| `skipped` | `bool` | `False` | 질문 또는 거래 일정 건너뜀 여부 |
| `answered_at` | `str \| None` | `None` | 질문 응답 시각 |


<a id="schemas-dialog-py-FieldError-50"></a>
### `FieldError`

<!-- source-symbol: schemas/dialog.py:50:FieldError -->
[dialog.py](../../backend/analysis/schemas/dialog.py#L50)

필드 경로와 한국어 오류 한 건입니다. HARD 오류는 보충 질문 대신 이 모델로 전달합니다.

기반: `BaseModel`.

| 필드 | 자료형 | 기본값 또는 생성 방식 | 선언된 제약·설명 |
| --- | --- | --- | --- |
| `field` | `str` | `필수 입력` | 대상 필드의 점 경로 |
| `message_ko` | `str` | `필수 입력` | 한국어 안내·오류 문장 |


<a id="schemas-dialog-py-ConditionRow-55"></a>
### `ConditionRow`

<!-- source-symbol: schemas/dialog.py:55:ConditionRow -->
[dialog.py](../../backend/analysis/schemas/dialog.py#L55)

화면의 조건 확인 한 줄입니다. 그룹·라벨·현재/프로필 표시값·변경 여부·출처·지원 여부·주석을 서버가 만들어 보냅니다.

기반: `BaseModel`.

| 필드 | 자료형 | 기본값 또는 생성 방식 | 선언된 제약·설명 |
| --- | --- | --- | --- |
| `field` | `str` | `필수 입력` | 대상 필드의 점 경로 |
| `group_ko` | `str` | `필수 입력` | 조건의 한국어 그룹명 |
| `label_ko` | `str` | `필수 입력` | 한국어 표시 라벨 |
| `value_ko` | `str` | `필수 입력` | 현재 값의 표시 문장 |
| `profile_value_ko` | `str \| None` | `None` | 프로필 기본값의 표시 문장 |
| `changed` | `bool` | `False` | 프로필 대비 변경 여부 |
| `source` | `Literal['profile', 'idea', 'answer', 'default', 'derived']` | `'profile'` | 값의 출처(profile/idea/answer/default/derived) |
| `supported` | `bool` | `True` | 반영·지원 가능한 항목인지 |
| `note_ko` | `str \| None` | `None` | 화면 보조 안내 |


<a id="schemas-dialog-py-DialogMessage-69"></a>
### `DialogMessage`

<!-- source-symbol: schemas/dialog.py:69:DialogMessage -->
[dialog.py](../../backend/analysis/schemas/dialog.py#L69)

system/user/assistant 역할과 content로 구성된 누적 LLM 대화 한 건입니다. 실제 첫 메시지 목록에는 system도 저장될 수 있습니다.

기반: `BaseModel`.

| 필드 | 자료형 | 기본값 또는 생성 방식 | 선언된 제약·설명 |
| --- | --- | --- | --- |
| `role` | `Literal['system', 'user', 'assistant']` | `필수 입력` | LLM 메시지 역할 |
| `content` | `str` | `필수 입력` | LLM 메시지 본문 |


<a id="schemas-dialog-py-RevisionChange-74"></a>
### `RevisionChange`

<!-- source-symbol: schemas/dialog.py:74:RevisionChange -->
[dialog.py](../../backend/analysis/schemas/dialog.py#L74)

LLM이 제안하고 코드가 검사한 변경 한 건입니다. 새 값·원래 값·라벨·이유·supported·제외 사유를 보관합니다.

기반: `BaseModel`.

| 필드 | 자료형 | 기본값 또는 생성 방식 | 선언된 제약·설명 |
| --- | --- | --- | --- |
| `field` | `str` | `필수 입력` | 대상 필드의 점 경로 |
| `value` | `Any` | `None` | 선택·변경·지표의 실제 값 |
| `base_value` | `Any` | `None` | 수정 전 원안 값 |
| `label_ko` | `str \| None` | `None` | 한국어 표시 라벨 |
| `reason_ko` | `str \| None` | `None` | 한국어 판단 이유 |
| `supported` | `bool` | `True` | 반영·지원 가능한 항목인지 |
| `note_ko` | `str \| None` | `None` | 화면 보조 안내 |


<a id="schemas-dialog-py-RevisionDraft-86"></a>
### `RevisionDraft`

<!-- source-symbol: schemas/dialog.py:86:RevisionDraft -->
[dialog.py](../../backend/analysis/schemas/dialog.py#L86)

자연어 수정의 요약·변경 목록·미지원 요청·아이디어 보충·고정 필드·원안 실행 ID를 묶습니다. 지원 변경만 다음 요청 overrides로 전달합니다.

기반: `BaseModel`.

| 필드 | 자료형 | 기본값 또는 생성 방식 | 선언된 제약·설명 |
| --- | --- | --- | --- |
| `text` | `str` | `필수 입력` | 자연어 수정 또는 보충 내용 |
| `summary_ko` | `str \| None` | `None` | 한국어 요약 |
| `changes` | `list[RevisionChange]` | `[]` | — |
| `unsupported_ko` | `list[str]` | `[]` | 반영 불가 수정 내용·이유 |
| `idea_update_ko` | `str \| None` | `None` | 수정 시 해석에 보탤 테마 범위 문장 |
| `frozen_fields` | `list[str]` | `[]` | 원안과 같게 유지할 평가 조건 경로 |
| `base_run_id` | `str \| None` | `None` | 원안 실행 ID |


<a id="schemas-dialog-py-AnalysisRequestDoc-98"></a>
### `AnalysisRequestDoc`

<!-- source-symbol: schemas/dialog.py:98:AnalysisRequestDoc -->
[dialog.py](../../backend/analysis/schemas/dialog.py#L98)

요청 대화의 저장 원본으로 schema_version=2이며 미지 필드를 금지합니다. 프로필 버전·아이디어·답·메시지·초안/확정 요청·의도·오류·상태·실행 ID·점검·수정 초안을 보존합니다. DB 리포트와 다른 로컬 파일 계약입니다.

기반: `BaseModel`.

| 필드 | 자료형 | 기본값 또는 생성 방식 | 선언된 제약·설명 |
| --- | --- | --- | --- |
| `schema_version` | `int` | `2` | 로컬 저장 객체의 계약 버전 |
| `request_id` | `str` | `필수 입력` | 대화·분석 요청을 연결하는 ID |
| `created_at` | `str` | `필수 입력` | 객체 생성 시각 문자열 |
| `mode` | `RequestMode` | `'new'` | 실행·구성·평가 방식 |
| `base_report_id` | `str \| None` | `None` | 수정/재분석의 기준 리포트 |
| `profile_version` | `int` | `필수 입력` | 요청이 참조하는 고정 프로필 버전 |
| `idea` | `str` | `필수 입력` | 사용자 투자 아이디어 본문 |
| `language` | `str` | `'ko'` | 입출력 언어 |
| `overrides` | `dict[str, Any]` | `{}` | 이번 요청의 필드 경로별 덮어쓰기 |
| `idea_clarifications` | `list[str]` | `[]` | 자연어 보충 문장 목록 |
| `questions` | `list[Question]` | `[]` | 질문 제안 또는 실제 질문 이력 |
| `messages` | `list[DialogMessage]` | `[]` | 초기 system을 포함할 수 있는 저장 대화 전체 |
| `draft_request` | `dict[str, Any] \| None` | `None` | 아직 확정하지 않은 조립 요청 |
| `derived` | `dict[str, Any] \| None` | `None` | 기준일·환율 등 코드 파생값 |
| `intent` | `dict[str, Any] \| None` | `None` | 검증·보정한 투자 해석 명세 |
| `hard_errors` | `list[FieldError]` | `[]` | 즉시 수정해야 하는 필드 오류 |
| `status` | `Literal['draft', 'confirmed', 'cancelled']` | `'draft'` | 소속 객체의 처리 상태 |
| `dialog_state` | `DialogStatus` | `'asking'` | — |
| `turn` | `int` | `0` | 현재까지 생성한 질문 수 |
| `max_questions` | `int` | `5` | 질문 횟수 상한 |
| `blocked_reason_ko` | `str \| None` | `None` | 차단/상한 안내; 현재는 ready에서도 기본값 유지 이유로 사용 |
| `effective_request` | `dict[str, Any] \| None` | `None` | 실행에 쓰기로 확정한 요청 |
| `request_fingerprint` | `str \| None` | `None` | 시간·식별 일부를 제외한 조건 지문 |
| `confirmed_at` | `str \| None` | `None` | 요청 확정 시각 |
| `run_id` | `str \| None` | `None` | 분석 실행 시도의 ID |
| `context_summary` | `str \| None` | `None` | 이전 실행 맥락 요약용 저장 필드 |
| `revision` | `RevisionDraft \| None` | `None` | 원안 대비 수정 초안 |
| `warnings` | `list[str]` | `[]` | 문맥별 전체 경고 또는 문장 검사 메모 |
| `precheck` | `dict[str, Any] \| None` | `None` | 현재·과거 후보 수와 가능 기간의 사전 점검 |


<a id="schemas-dialog-py-DialogSummary-134"></a>
### `DialogSummary`

<!-- source-symbol: schemas/dialog.py:134:DialogSummary -->
[dialog.py](../../backend/analysis/schemas/dialog.py#L134)

현재 해석 요약·테마·파생 조건·변경 필드의 화면용 작은 묶음입니다.

기반: `BaseModel`.

| 필드 | 자료형 | 기본값 또는 생성 방식 | 선언된 제약·설명 |
| --- | --- | --- | --- |
| `interpretation_summary_ko` | `str \| None` | `None` | — |
| `themes` | `list[dict[str, Any]]` | `[]` | 해석한 투자 테마 목록 |
| `derived` | `dict[str, Any] \| None` | `None` | 기준일·환율 등 코드 파생값 |
| `changed_fields` | `list[str]` | `[]` | 프로필 대비 덮어쓴 경로 |


<a id="schemas-dialog-py-DialogState-141"></a>
### `DialogState`

<!-- source-symbol: schemas/dialog.py:141:DialogState -->
[dialog.py](../../backend/analysis/schemas/dialog.py#L141)

API에 공개하는 대화 응답입니다. 현재 질문, 전체 질문 기록, HARD 오류, 조건 표, 확정 내용·요약·수정안·실행 ID를 담으며 원본 messages 전체는 노출하지 않습니다.

기반: `BaseModel`.

| 필드 | 자료형 | 기본값 또는 생성 방식 | 선언된 제약·설명 |
| --- | --- | --- | --- |
| `request_id` | `str` | `필수 입력` | 대화·분석 요청을 연결하는 ID |
| `mode` | `RequestMode` | `필수 입력` | 실행·구성·평가 방식 |
| `base_report_id` | `str \| None` | `None` | 수정/재분석의 기준 리포트 |
| `status` | `Literal['draft', 'confirmed', 'cancelled']` | `필수 입력` | 소속 객체의 처리 상태 |
| `state` | `DialogStatus` | `필수 입력` | 대화의 화면 상태 |
| `turn` | `int` | `필수 입력` | 현재까지 생성한 질문 수 |
| `max_questions` | `int` | `필수 입력` | 질문 횟수 상한 |
| `idea` | `str` | `필수 입력` | 사용자 투자 아이디어 본문 |
| `question` | `Question \| None` | `None` | 현재 사용자에게 보여 줄 질문 |
| `questions` | `list[Question]` | `[]` | 질문 제안 또는 실제 질문 이력 |
| `hard_errors` | `list[FieldError]` | `[]` | 즉시 수정해야 하는 필드 오류 |
| `confirmation` | `dict[str, Any] \| None` | `None` | 확정 전 유효 요청과 조건 표 |
| `unresolved` | `list[dict[str, Any]]` | `[]` | 미응답·건너뜀 항목의 안내 |
| `summary` | `DialogSummary` | `DialogSummary()` | 객체별 요약 또는 대시보드 |
| `revision` | `RevisionDraft \| None` | `None` | 원안 대비 수정 초안 |
| `run_id` | `str \| None` | `None` | 분석 실행 시도의 ID |
| `warnings` | `list[str]` | `[]` | 문맥별 전체 경고 또는 문장 검사 메모 |
| `conditions` | `list[dict[str, Any]]` | `[]` | 현재 조건 확인 표 |
| `overrides` | `dict[str, Any]` | `{}` | 이번 요청의 필드 경로별 덮어쓰기 |
| `blocked_reason_ko` | `str \| None` | `None` | 차단/상한 안내; 현재는 ready에서도 기본값 유지 이유로 사용 |
| `precheck` | `dict[str, Any] \| None` | `None` | 현재·과거 후보 수와 가능 기간의 사전 점검 |


<a id="schemas-intent-py-Theme-23"></a>
### `Theme`

<!-- source-symbol: schemas/intent.py:23:Theme -->
[intent.py](../../backend/analysis/schemas/intent.py#L23)

산업 범위·검색 키워드·예시 티커를 가진 투자 테마 정의입니다. ID 형식과 GICS 코드의 모양은 모델이, 실제 사전 내 존재는 해석 코드가 검증합니다.

기반: `BaseModel`.

| 필드 | 자료형 | 기본값 또는 생성 방식 | 선언된 제약·설명 |
| --- | --- | --- | --- |
| `id` | `str` | `필수 입력` | 현재 객체의 식별자; pattern='^[a-z0-9_]+$' |
| `label_ko` | `str` | `필수 입력` | 한국어 표시 라벨 |
| `description_ko` | `str` | `필수 입력` | 한국어 설명 |
| `gics_codes` | `list[str]` | `[]` | 검색할 산업 계층 코드 |
| `keywords` | `list[str]` | `[]` | 회사 소개에서 찾을 키워드 |
| `example_tickers` | `list[str]` | `[]` | 테마 검색의 보조 예시 티커 |


<a id="schemas-intent-py-ExcludeThemeRule-33"></a>
### `ExcludeThemeRule`

<!-- source-symbol: schemas/intent.py:33:ExcludeThemeRule -->
[intent.py](../../backend/analysis/schemas/intent.py#L33)

투자에서 제외할 테마를 GICS·키워드 검색 조건으로 표현합니다.

기반: `BaseModel`.

| 필드 | 자료형 | 기본값 또는 생성 방식 | 선언된 제약·설명 |
| --- | --- | --- | --- |
| `theme` | `str` | `필수 입력` | 제외할 테마 이름 |
| `gics_codes` | `list[str]` | `[]` | 검색할 산업 계층 코드 |
| `keywords` | `list[str]` | `[]` | 회사 소개에서 찾을 키워드 |


<a id="schemas-intent-py-Conflict-40"></a>
### `Conflict`

<!-- source-symbol: schemas/intent.py:40:Conflict -->
[intent.py](../../backend/analysis/schemas/intent.py#L40)

아이디어와 기존 조건의 충돌 설명입니다. field는 관련 경로, issue_ko는 충돌 내용, resolution_ko는 해석 메모이며 idea_value가 있으면 코드가 아이디어/프로필 선택 질문으로 바꿀 수 있습니다. 공통 errors.Conflict 예외와 다른 데이터 모델입니다.

기반: `BaseModel`.

| 필드 | 자료형 | 기본값 또는 생성 방식 | 선언된 제약·설명 |
| --- | --- | --- | --- |
| `field` | `str` | `필수 입력` | 대상 필드의 점 경로 |
| `issue_ko` | `str` | `필수 입력` | 입력 충돌 내용 |
| `resolution_ko` | `str` | `필수 입력` | 해석 단계의 충돌 해소 메모 |
| `idea_value` | `Any \| None` | `None` | 아이디어가 뜻하는 조건 값 |


<a id="schemas-intent-py-Interpretation-47"></a>
### `Interpretation`

<!-- source-symbol: schemas/intent.py:47:Interpretation -->
[intent.py](../../backend/analysis/schemas/intent.py#L47)

아이디어 해석의 요약·하나 이상 테마·스타일 힌트·충돌 목록입니다.

기반: `BaseModel`.

| 필드 | 자료형 | 기본값 또는 생성 방식 | 선언된 제약·설명 |
| --- | --- | --- | --- |
| `summary_ko` | `str` | `필수 입력` | 한국어 요약 |
| `themes` | `list[Theme]` | `필수 입력` | 해석한 투자 테마 목록; min_length=1 |
| `style_hints` | `list[str]` | `[]` | 자연어 투자 스타일의 보조 단서 |
| `conflicts` | `list[Conflict]` | `[]` | 아이디어와 조건의 충돌 설명 |


<a id="schemas-intent-py-ThemeFilter-54"></a>
### `ThemeFilter`

<!-- source-symbol: schemas/intent.py:54:ThemeFilter -->
[intent.py](../../backend/analysis/schemas/intent.py#L54)

테마 분류 통과에 필요한 최소 신뢰도이며 기본 0.5입니다.

기반: `BaseModel`.

| 필드 | 자료형 | 기본값 또는 생성 방식 | 선언된 제약·설명 |
| --- | --- | --- | --- |
| `min_confidence` | `float` | `0.5` | 테마 판정 통과 최소 신뢰도; ge=0, le=1 |


<a id="schemas-intent-py-Screen-58"></a>
### `Screen`

<!-- source-symbol: schemas/intent.py:58:Screen -->
[intent.py](../../backend/analysis/schemas/intent.py#L58)

선정 템플릿·지표·방향·기준일·신뢰도·목표 개수 계약입니다. 템플릿에 대응하는 지표·방향을 강제합니다.

기반: `BaseModel`.

| 필드 | 자료형 | 기본값 또는 생성 방식 | 선언된 제약·설명 |
| --- | --- | --- | --- |
| `template` | `Template` | `필수 입력` | 정량 선정 기준 또는 전략의 기준 템플릿 |
| `metric` | `str` | `필수 입력` | 정량 지표 코드 |
| `direction` | `Literal['asc', 'desc']` | `필수 입력` | 지표 정렬 방향 |
| `as_of` | `date` | `필수 입력` | 자료 판단 기준일 |
| `theme_filter` | `ThemeFilter` | `ThemeFilter()` | — |
| `select_top_n` | `int` | `필수 입력` | 목표 선정 개수; ge=1 |

메서드·속성: [_metric_matches_template](#schemas-intent-py-Screen-_metric_matches_template-67).


<a id="schemas-intent-py-RiskParams-74"></a>
### `RiskParams`

<!-- source-symbol: schemas/intent.py:74:RiskParams -->
[intent.py](../../backend/analysis/schemas/intent.py#L74)

위험 성향·보정된 맞춤 목표·변동성 선호·해석 메모입니다. effective_max_drawdown은 현재 R1의 원래 사용자 허용값과 구별합니다.

기반: `BaseModel`.

| 필드 | 자료형 | 기본값 또는 생성 방식 | 선언된 제약·설명 |
| --- | --- | --- | --- |
| `risk_tolerance` | `RiskTolerance` | `필수 입력` | 범주형 위험 성향 |
| `effective_max_drawdown` | `float` | `필수 입력` | 성향 보정을 반영한 낙폭 맞춤안 목표; gt=0, le=1 |
| `volatility_preference` | `Literal['low', 'medium', 'high']` | `필수 입력` | 변동성 선호 범주 |
| `notes_ko` | `str` | `''` | 한국어 보조 설명 |


<a id="schemas-intent-py-NewsTilt-81"></a>
### `NewsTilt`

<!-- source-symbol: schemas/intent.py:81:NewsTilt -->
[intent.py](../../backend/analysis/schemas/intent.py#L81)

뉴스/공시 의견 반영의 켜짐·최대 신뢰도·종목당 최대 비중 이동을 담습니다. 실제 비중은 최적화 코드가 계산합니다.

기반: `BaseModel`.

| 필드 | 자료형 | 기본값 또는 생성 방식 | 선언된 제약·설명 |
| --- | --- | --- | --- |
| `enabled` | `bool` | `필수 입력` | 해당 기능·규칙의 활성화 |
| `max_view_confidence` | `float` | `필수 입력` | 의견 신뢰도 상한; ge=0, le=1 |
| `max_tilt_per_stock` | `float` | `필수 입력` | 기준 대비 종목당 최대 비중 이동; ge=0, le=1 |


<a id="schemas-intent-py-ValidationCriteria-87"></a>
### `ValidationCriteria`

<!-- source-symbol: schemas/intent.py:87:ValidationCriteria -->
[intent.py](../../backend/analysis/schemas/intent.py#L87)

의도 명세에 담긴 비교지수·사용자 허용 낙폭·목표 연수익·투자기간입니다. 기준 중 수치는 해석 코드가 요청값으로 확정합니다.

기반: `BaseModel`.

| 필드 | 자료형 | 기본값 또는 생성 방식 | 선언된 제약·설명 |
| --- | --- | --- | --- |
| `benchmark` | `str` | `필수 입력` | 주 비교지수 티커 또는 결과 |
| `max_drawdown` | `float` | `필수 입력` | — |
| `target_annual_return` | `float` | `필수 입력` | 목표 연수익률 |
| `horizon_years` | `float` | `필수 입력` | 평가에 반영할 목표 보유 연수 |


<a id="schemas-intent-py-ReportSettings-94"></a>
### `ReportSettings`

<!-- source-symbol: schemas/intent.py:94:ReportSettings -->
[intent.py](../../backend/analysis/schemas/intent.py#L94)

의도 해석에 포함되는 리포트 언어와 beginner/intermediate/expert 설명 수준입니다. 루트 settings.ReportSettings의 섹션·금지 표현 정책과 별개의 동명 모델입니다.

기반: `BaseModel`.

| 필드 | 자료형 | 기본값 또는 생성 방식 | 선언된 제약·설명 |
| --- | --- | --- | --- |
| `language` | `str` | `'ko'` | 입출력 언어 |
| `explanation_level` | `Literal['beginner', 'intermediate', 'expert']` | `필수 입력` | 입력 사용자의 설명 수준 |


<a id="schemas-intent-py-IntentSpec-99"></a>
### `IntentSpec`

<!-- source-symbol: schemas/intent.py:99:IntentSpec -->
[intent.py](../../backend/analysis/schemas/intent.py#L99)

투자 의도 해석의 정형 결과입니다. 해석·검색 제외·정량 선정·위험·의견 조정·검증·서술 선호·질문 제안·경고를 다음 단계에 전달합니다.

기반: `BaseModel`.

| 필드 | 자료형 | 기본값 또는 생성 방식 | 선언된 제약·설명 |
| --- | --- | --- | --- |
| `request_id` | `str` | `필수 입력` | 대화·분석 요청을 연결하는 ID |
| `stage` | `str` | `'02_intent'` | 단계 산출물 종류 |
| `spec_version` | `str` | `'2.0'` | 의도 명세 버전 |
| `interpretation` | `Interpretation` | `필수 입력` | 테마·요약·스타일·충돌 해석 |
| `exclude_theme_rules` | `list[ExcludeThemeRule]` | `[]` | 제외 테마를 검색 규칙으로 표현한 목록 |
| `screen` | `Screen` | `필수 입력` | 정량 선정 실행 조건 |
| `risk_params` | `RiskParams` | `필수 입력` | 위험 해석과 맞춤 목표 |
| `news_tilt` | `NewsTilt` | `필수 입력` | 근거 의견의 비중 조정 조건 |
| `validation_criteria` | `ValidationCriteria` | `필수 입력` | 평가에 사용할 사용자 조건 |
| `report_settings` | `ReportSettings` | `필수 입력` | 언어·설명 수준 |
| `questions` | `list[QuestionProposal]` | `[]` | 질문 제안 또는 실제 질문 이력 |
| `warnings` | `list[str]` | `[]` | 문맥별 전체 경고 또는 문장 검사 메모 |


<a id="schemas-portfolio-py-MarketModel-11"></a>
### `MarketModel`

<!-- source-symbol: schemas/portfolio.py:11:MarketModel -->
[portfolio.py](../../backend/analysis/schemas/portfolio.py#L11)

구성일 추정 창·종목·공분산·상관·변동성·시총 비중·위험회피 δ·τ·내재수익·수축 정보를 담습니다. 예상치이므로 과거 실현 성과와 다릅니다.

기반: `BaseModel`.

| 필드 | 자료형 | 기본값 또는 생성 방식 | 선언된 제약·설명 |
| --- | --- | --- | --- |
| `request_id` | `str` | `필수 입력` | 대화·분석 요청을 연결하는 ID |
| `stage` | `str` | `'08_market_model'` | 단계 산출물 종류 |
| `as_of` | `date` | `필수 입력` | 자료 판단 기준일 |
| `lookback` | `dict` | `필수 입력` | 추정에 사용한 기간 메타 |
| `tickers` | `list[str]` | `필수 입력` | 관련 종목 티커 목록 |
| `ann_vol` | `dict[str, float]` | `필수 입력` | 연환산 변동성 |
| `corr` | `list[list[float]]` | `필수 입력` | 상관행렬 |
| `cov` | `list[list[float]]` | `필수 입력` | 연율 공분산행렬 |
| `cap_weights` | `dict[str, float]` | `필수 입력` | 시총 기준 비중 |
| `delta` | `float` | `필수 입력` | 위험회피 계수 δ |
| `delta_source` | `str` | `'fixed'` | 위험회피를 고정/시장 내재로 정한 방식 |
| `delta_market` | `float \| None` | `None` | 비교지수에서 구한 원래 시장 내재 δ |
| `delta_multiplier` | `float \| None` | `None` | 위험 성향별 δ 배수 |
| `delta_window` | `dict \| None` | `None` | 시장 내재 δ의 관측 창 |
| `delta_dd_multiplier` | `float \| None` | `None` | 허용 낙폭에 따른 δ 배수 |
| `delta_tolerance` | `float \| None` | `None` | δ 보정에 사용한 입력 허용 낙폭 |
| `tau` | `float` | `필수 입력` | 사전 추정 불확실성 계수 τ |
| `baseline_id` | `str` | `필수 입력` | 기준 비중 방식 ID |
| `implied_returns` | `dict[str, float]` | `필수 입력` | 기준 비중에서 역산한 연간 내재수익 |
| `shrinkage` | `dict` | `필수 입력` | 공분산 수축 방식·강도 |
| `notes` | `list[str]` | `[]` | 시장모형의 계산 메모·제약·경고 |


<a id="schemas-portfolio-py-ExAnte-35"></a>
### `ExAnte`

<!-- source-symbol: schemas/portfolio.py:35:ExAnte -->
[portfolio.py](../../backend/analysis/schemas/portfolio.py#L35)

구성 시점에 추정한 수익·변동성·비율·유효 종목 수입니다. 백테스트 헤드라인 수치와 분리됩니다.

기반: `BaseModel`.

| 필드 | 자료형 | 기본값 또는 생성 방식 | 선언된 제약·설명 |
| --- | --- | --- | --- |
| `exp_return` | `float` | `필수 입력` | 모형상 기대수익 |
| `vol` | `float` | `필수 입력` | 모형상 변동성 |
| `sharpe` | `float` | `필수 입력` | 모형 또는 성과의 수익/위험 비율; 문맥별 정의 확인 |
| `effective_n` | `float` | `필수 입력` | 비중 집중도에서 계산한 유효 종목 수 |


<a id="schemas-portfolio-py-Portfolio-42"></a>
### `Portfolio`

<!-- source-symbol: schemas/portfolio.py:42:Portfolio -->
[portfolio.py](../../backend/analysis/schemas/portfolio.py#L42)

템플릿 또는 BL의 한 목표 비중입니다. 현금 포함 합계·음수 비중을 검사하며 BL이면 의견·기준 대비 이동·사후 수익·활성 제약을 추가합니다.

기반: `BaseModel`.

| 필드 | 자료형 | 기본값 또는 생성 방식 | 선언된 제약·설명 |
| --- | --- | --- | --- |
| `id` | `str` | `필수 입력` | 현재 객체의 식별자 |
| `kind` | `Literal['template', 'black_litterman']` | `필수 입력` | 객체·전략·근거·시점의 종류 |
| `name_ko` | `str` | `필수 입력` | 한국어 이름 |
| `rule_ko` | `str` | `''` | — |
| `weights` | `dict[str, float]` | `필수 입력` | 종목별 목표 또는 평가 비중 |
| `cash_weight` | `float` | `0.0` | 현금 비중 |
| `ex_ante` | `ExAnte` | `필수 입력` | 구성 시점 예상 수익·위험 |
| `sector_weights` | `dict[str, float]` | `필수 입력` | 섹터별 합산 비중 |
| `constraints_applied` | `list[str]` | `[]` | 기준 비중에 적용된 제약 |
| `scenario_id` | `str \| None` | `None` | 의견 세트 식별자 |
| `title_ko` | `str \| None` | `None` | 화면 한국어 제목 |
| `portfolio_view` | `str \| None` | `None` | 의견 세트와 비중 구성에 대한 설명 |
| `views_applied` | `list[dict]` | `[]` | 비중에 반영한 의견 메타 |
| `delta_vs_baseline` | `dict[str, float]` | `{}` | 기준 비중과의 차이 |
| `posterior_returns` | `dict[str, float]` | `{}` | BL 사후 기대수익 |
| `active_constraints` | `list[str]` | `[]` | 최적화의 활성 제약 또는 실패 라벨 |

메서드·속성: [_sums](#schemas-portfolio-py-Portfolio-_sums-62).


<a id="schemas-portfolio-py-BaselinePortfolios-71"></a>
### `BaselinePortfolios`

<!-- source-symbol: schemas/portfolio.py:71:BaselinePortfolios -->
[portfolio.py](../../backend/analysis/schemas/portfolio.py#L71)

구성일의 네 템플릿 포트폴리오와 사용자가 고른 기준 방식 ID를 묶습니다.

기반: `BaseModel`.

| 필드 | 자료형 | 기본값 또는 생성 방식 | 선언된 제약·설명 |
| --- | --- | --- | --- |
| `request_id` | `str` | `필수 입력` | 대화·분석 요청을 연결하는 ID |
| `stage` | `str` | `'08_baseline_portfolios'` | 단계 산출물 종류 |
| `as_of` | `date` | `필수 입력` | 자료 판단 기준일 |
| `chosen_baseline` | `str` | `필수 입력` | 사용자가 고른 기준 템플릿 ID |
| `portfolios` | `list[Portfolio]` | `필수 입력` | 전략별 비중 또는 평가 결과 목록 |


<a id="schemas-portfolio-py-View-79"></a>
### `View`

<!-- source-symbol: schemas/portfolio.py:79:View -->
[portfolio.py](../../backend/analysis/schemas/portfolio.py#L79)

절대 또는 상대 기대수익 가설입니다. long/short·연간 기대수익·신뢰도·지평·이유·근거 ID를 담고 양쪽 종목 관계를 검사합니다. evidence_type은 str이므로 주석의 news 전용 표현과 달리 공시/혼합도 들어갈 수 있습니다.

기반: `BaseModel`.

| 필드 | 자료형 | 기본값 또는 생성 방식 | 선언된 제약·설명 |
| --- | --- | --- | --- |
| `type` | `Literal['absolute', 'relative']` | `필수 입력` | 의견 또는 블록 종류 |
| `long` | `list[str]` | `필수 입력` | 절대/상대 의견의 양수 쪽 종목; min_length=1 |
| `short` | `list[str]` | `[]` | 상대 의견의 비교 쪽; 실제 공매도 지시가 아님 |
| `expected_return_annual` | `float` | `필수 입력` | 연간 기대수익 가설 |
| `confidence` | `float` | `필수 입력` | 의견·테마 판정 신뢰도; gt=0, le=1 |
| `horizon_months` | `int` | `12` | 의견의 기대 지평(개월); ge=1, le=60 |
| `rationale_ko` | `str` | `필수 입력` | 근거를 인용한 한국어 설명 |
| `evidence_type` | `str` | `'news'` | 인용 종류; 현 구현은 news/disclosure/mixed 사용 가능 |
| `evidence_ids` | `list[str]` | `필수 입력` | 의견에서 인용한 근거 ID; min_length=1 |

메서드·속성: [_shape](#schemas-portfolio-py-View-_shape-91).


<a id="schemas-portfolio-py-ViewSet-101"></a>
### `ViewSet`

<!-- source-symbol: schemas/portfolio.py:101:ViewSet -->
[portfolio.py](../../backend/analysis/schemas/portfolio.py#L101)

하나 이상의 의견과 시나리오 ID·제목·서술을 묶은 대안 가설 세트입니다.

기반: `BaseModel`.

| 필드 | 자료형 | 기본값 또는 생성 방식 | 선언된 제약·설명 |
| --- | --- | --- | --- |
| `scenario_id` | `str` | `필수 입력` | 의견 세트 식별자 |
| `title_ko` | `str` | `필수 입력` | 화면 한국어 제목 |
| `narrative_ko` | `str` | `필수 입력` | — |
| `views` | `list[View]` | `필수 입력` | 의견 요청 수 또는 의견 집합; min_length=1 |


<a id="schemas-portfolio-py-Views-108"></a>
### `Views`

<!-- source-symbol: schemas/portfolio.py:108:Views -->
[portfolio.py](../../backend/analysis/schemas/portfolio.py#L108)

구성일의 의견 세트와 근거 창 요약·최대 신뢰도·기준안 대체 여부·사유를 담는 단계 산출물입니다.

기반: `BaseModel`.

| 필드 | 자료형 | 기본값 또는 생성 방식 | 선언된 제약·설명 |
| --- | --- | --- | --- |
| `request_id` | `str` | `필수 입력` | 대화·분석 요청을 연결하는 ID |
| `stage` | `str` | `'09_views'` | 단계 산출물 종류 |
| `as_of` | `date` | `필수 입력` | 자료 판단 기준일 |
| `window` | `dict \| None` | `None` | 조회 창·평가 창·근거 창 요약 |
| `max_view_confidence` | `float` | `필수 입력` | 의견 신뢰도 상한 |
| `sets` | `list[ViewSet]` | `[]` | 여러 의견 세트 |
| `fallback` | `bool` | `False` | 새 의견 대신 기준/이전 비중을 사용했는지 |
| `fallback_reason_ko` | `str \| None` | `None` | 대체 처리 사유 |
| `warnings` | `list[str]` | `[]` | 문맥별 전체 경고 또는 문장 검사 메모 |


<a id="schemas-portfolio-py-TargetPortfolios-120"></a>
### `TargetPortfolios`

<!-- source-symbol: schemas/portfolio.py:120:TargetPortfolios -->
[portfolio.py](../../backend/analysis/schemas/portfolio.py#L120)

백테스트 시작일 사양·파라미터·기준 비중·BL 후보·네 템플릿을 묶습니다. 날짜별 경로와 현재 구성은 별도 산출물입니다.

기반: `BaseModel`.

| 필드 | 자료형 | 기본값 또는 생성 방식 | 선언된 제약·설명 |
| --- | --- | --- | --- |
| `request_id` | `str` | `필수 입력` | 대화·분석 요청을 연결하는 ID |
| `stage` | `str` | `'10_target_portfolios'` | 단계 산출물 종류 |
| `as_of` | `date` | `필수 입력` | 자료 판단 기준일 |
| `backtest_spec` | `dict` | `필수 입력` | — |
| `parameters` | `dict` | `필수 입력` | 계산에 사용한 설정 |
| `baseline` | `dict` | `필수 입력` | 선택 기준 비중 정보 |
| `portfolios` | `list[Portfolio]` | `필수 입력` | 전략별 비중 또는 평가 결과 목록 |
| `templates` | `list[Portfolio]` | `필수 입력` | 기준 비중 방식의 결과 |
| `notes_ko` | `list[str]` | `[]` | 한국어 보조 설명 |
| `warnings` | `list[str]` | `[]` | 문맥별 전체 경고 또는 문장 검사 메모 |


<a id="schemas-report-py-EvidenceRecord-31"></a>
### `EvidenceRecord`

<!-- source-symbol: schemas/report.py:31:EvidenceRecord -->
[report.py](../../backend/analysis/schemas/report.py#L31)

화면 출처 패널의 근거 한 건입니다. 뉴스·공시·금융 Fact·계산값을 같은 기본 필드로 연결하고 공시는 이용 가능일·양식·사건명을 추가합니다.

기반: `BaseModel`.

| 필드 | 자료형 | 기본값 또는 생성 방식 | 선언된 제약·설명 |
| --- | --- | --- | --- |
| `event_type` | `str \| None` | `None` | 공시 사건 종류 코드 |
| `event_label_ko` | `str \| None` | `None` | 공시 사건 한국어 이름 |
| `form` | `str \| None` | `None` | 공시 보고서 양식 |
| `items` | `str \| None` | `None` | 공시 양식 항목 |
| `filed_at` | `str \| None` | `None` | 공시 접수 날짜 |
| `available_on` | `str \| None` | `None` | 투자자가 공시를 이용할 수 있게 된 날짜 |
| `id` | `str` | `필수 입력` | 현재 객체의 식별자 |
| `kind` | `str` | `필수 입력` | 객체·전략·근거·시점의 종류 |
| `title` | `str` | `필수 입력` | 출처 제목 |
| `source` | `str` | `필수 입력` | 자료·설명·선정의 출처 식별 |
| `url` | `str \| None` | `None` | 기사·공시 등 출처 주소 |
| `published_at` | `str \| None` | `None` | 뉴스 발행 또는 호환 접수 날짜 |
| `data_as_of` | `str \| None` | `None` | 숫자 또는 근거의 관측 기준일 |
| `tickers` | `list[str]` | `[]` | 관련 종목 티커 목록 |
| `value` | `Any \| None` | `None` | 선택·변경·지표의 실제 값 |
| `unit` | `str \| None` | `None` | 비율 단위 또는 리밸런싱 단위 |
| `excerpt` | `str \| None` | `None` | 선택 근거 발췌문 |
| `language` | `str \| None` | `None` | 입출력 언어 |


<a id="schemas-report-py-Section-54"></a>
### `Section`

<!-- source-symbol: schemas/report.py:54:Section -->
[report.py](../../backend/analysis/schemas/report.py#L54)

리포트 섹션 ID·제목·하나 이상 블록입니다. 허용 블록 종류를 검사하지만 각 블록의 전체 내부 구조를 별도 모델로 정의하지는 않습니다.

기반: `BaseModel`.

| 필드 | 자료형 | 기본값 또는 생성 방식 | 선언된 제약·설명 |
| --- | --- | --- | --- |
| `id` | `str` | `필수 입력` | 현재 객체의 식별자 |
| `title_ko` | `str` | `필수 입력` | 화면 한국어 제목 |
| `blocks` | `list[dict]` | `필수 입력` | 표·차트·문단 등의 블록 목록; min_length=1 |

메서드·속성: [_types](#schemas-report-py-Section-_types-61).


<a id="schemas-report-py-ReportDoc-68"></a>
### `ReportDoc`

<!-- source-symbol: schemas/report.py:68:ReportDoc -->
[report.py](../../backend/analysis/schemas/report.py#L68)

화면용 블록 리포트 계약입니다. 헤더·KPI·탐색·일곱 섹션·데이터셋·근거·사용자 공지·실행·요약을 묶습니다. 기본 doc_version은 구형 1이고 새 build_doc는 명시적으로 2를 지정합니다.

기반: `BaseModel`.

| 필드 | 자료형 | 기본값 또는 생성 방식 | 선언된 제약·설명 |
| --- | --- | --- | --- |
| `request_id` | `str` | `필수 입력` | 대화·분석 요청을 연결하는 ID |
| `run_id` | `str` | `필수 입력` | 분석 실행 시도의 ID |
| `stage` | `str` | `'14_report'` | 단계 산출물 종류 |
| `generated_at` | `str` | `필수 입력` | 분석 산출물 생성 시각 문자열 |
| `source` | `str` | `필수 입력` | 자료·설명·선정의 출처 식별 |
| `header` | `dict` | `필수 입력` | 문서 제목·기준일·선택안·안내 |
| `kpis` | `list[dict]` | `필수 입력` | 대표 지표 카드 |
| `nav` | `list[dict]` | `필수 입력` | 섹션 탐색 목록 |
| `sections` | `list[Section]` | `필수 입력` | 순서 있는 본문 섹션; min_length=1 |
| `datasets` | `dict` | `필수 입력` | 문서 차트의 날짜·시계열 묶음 |
| `assessment` | `dict` | `필수 입력` | LLM이 제공한 해석 적합성 메타 |
| `evidence` | `list[EvidenceRecord]` | `[]` | 문서에 실제 포함할 근거 또는 창 객체 |
| `execution` | `list[dict]` | `[]` | 단계별 실행 요약 |
| `tracking` | `dict` | `생성 함수: {'eligible': False, 'reason_ko': None}` | 모의투자 표시 가능 여부 |
| `sources` | `list[dict]` | `필수 입력` | 자료 출처 목록 |
| `parameters` | `dict` | `필수 입력` | 계산에 사용한 설정 |
| `warnings` | `list[str]` | `[]` | 문맥별 전체 경고 또는 문장 검사 메모 |
| `notices` | `list[dict]` | `[]` | 사용자 확인이 필요한 공지 |
| `doc_version` | `int` | `1` | 화면 리포트 형식 버전 |
| `summary` | `dict \| None` | `None` | 객체별 요약 또는 대시보드 |
| `evidence_summary` | `dict` | `생성 함수: dict` | 전체/인용 근거 수와 종류 집계 |

메서드·속성: [_refs](#schemas-report-py-ReportDoc-_refs-92).


<a id="schemas-request-py-Profile-29"></a>
### `Profile`

<!-- source-symbol: schemas/request.py:29:Profile -->
[request.py](../../backend/analysis/schemas/request.py#L29)

요청 안의 인적·투자 경험·금융 지식·투자 가능 자산 비율입니다. profile.json의 버전 관리 문서 전체와는 다른 작은 모델입니다.

기반: `BaseModel`.

| 필드 | 자료형 | 기본값 또는 생성 방식 | 선언된 제약·설명 |
| --- | --- | --- | --- |
| `user_id` | `str` | `'default'` | 단일 사용자 식별 기본값 |
| `age_band` | `Literal['20s', '30s', '40s', '50s', '60s+']` | `필수 입력` | 연령대 |
| `investment_experience` | `Literal['none', 'beginner', 'intermediate', 'advanced']` | `필수 입력` | 투자 경험 범주 |
| `financial_knowledge` | `Literal['basic', 'intermediate', 'expert']` | `필수 입력` | 금융 지식 수준 |
| `investable_ratio_of_assets` | `float` | `필수 입력` | 자산 중 투자 가능한 비율; ge=0, le=1 |


<a id="schemas-request-py-Capital-37"></a>
### `Capital`

<!-- source-symbol: schemas/request.py:37:Capital -->
[request.py](../../backend/analysis/schemas/request.py#L37)

초기자본·입력 통화·거래 기준 통화 USD·월 적립·적립일입니다. 입력 금액과 USD 환산값은 서로 다른 모델에 보관합니다.

기반: `BaseModel`.

| 필드 | 자료형 | 기본값 또는 생성 방식 | 선언된 제약·설명 |
| --- | --- | --- | --- |
| `initial_amount` | `float` | `필수 입력` | 입력 초기자본; gt=0 |
| `currency` | `Literal['KRW', 'USD']` | `필수 입력` | 입력/종목 통화 |
| `trading_currency` | `Literal['USD']` | `'USD'` | 계산 기준 통화 |
| `monthly_contribution` | `float` | `0` | 입력 통화 기준 월 적립금; ge=0 |
| `contribution_day` | `int` | `25` | 매월 적립 기준 일자; ge=1, le=28 |


<a id="schemas-request-py-Horizon-45"></a>
### `Horizon`

<!-- source-symbol: schemas/request.py:45:Horizon -->
[request.py](../../backend/analysis/schemas/request.py#L45)

분석 끝 기준일 start_date, 투자 목표기간·목적, 과거 평가 연수입니다. start_date라는 이름이 백테스트 창 시작일이라는 뜻은 아닙니다.

기반: `BaseModel`.

| 필드 | 자료형 | 기본값 또는 생성 방식 | 선언된 제약·설명 |
| --- | --- | --- | --- |
| `start_date` | `date \| None` | `None` | 분석 끝 기준일(as_of); 과거 평가 시작일이 아님 |
| `target_years` | `float` | `필수 입력` | 사용자가 목표로 하는 보유 기간(년); ge=1, le=10 |
| `purpose` | `Literal['wealth_growth', 'income', 'capital_preservation', 'retirement']` | `필수 입력` | 투자 목적 |
| `backtest_years` | `float` | `3.0` | 요청한 과거 평가 길이(년); ge=1, le=20 |


<a id="schemas-request-py-Risk-52"></a>
### `Risk`

<!-- source-symbol: schemas/request.py:52:Risk -->
[request.py](../../backend/analysis/schemas/request.py#L52)

위험 성향·허용 낙폭·손실 대응·목표수익·비교지수의 사용자 입력입니다.

기반: `BaseModel`.

| 필드 | 자료형 | 기본값 또는 생성 방식 | 선언된 제약·설명 |
| --- | --- | --- | --- |
| `risk_tolerance` | `RiskTolerance` | `필수 입력` | 범주형 위험 성향 |
| `max_drawdown_tolerance` | `float` | `필수 입력` | 사용자가 입력한 허용 낙폭의 양수 비율; gt=0, le=1 |
| `loss_reaction` | `Literal['sell', 'hold', 'buy_more']` | `필수 입력` | 손실 발생 시 대응 성향 |
| `target_annual_return` | `float` | `필수 입력` | 목표 연수익률 |
| `benchmark` | `str` | `'SPY'` | 주 비교지수 티커 또는 결과 |


<a id="schemas-request-py-NumHoldings-60"></a>
### `NumHoldings`

<!-- source-symbol: schemas/request.py:60:NumHoldings -->
[request.py](../../backend/analysis/schemas/request.py#L60)

최소·목표·최대 종목 수를 담고 순서 관계를 검사합니다. 모델 필드 자체는 1 이상이며 일부 대화 보정의 2~50 정책과 구분합니다.

기반: `BaseModel`.

| 필드 | 자료형 | 기본값 또는 생성 방식 | 선언된 제약·설명 |
| --- | --- | --- | --- |
| `target` | `int` | `필수 입력` | 목표 종목 수 또는 목표 비중; ge=1 |
| `min` | `int` | `필수 입력` | 허용 최소 종목 수; ge=1 |
| `max` | `int` | `필수 입력` | 허용 최대 종목 수; ge=1 |

메서드·속성: [_order](#schemas-request-py-NumHoldings-_order-66).


<a id="schemas-request-py-Rebalance-74"></a>
### `Rebalance`

<!-- source-symbol: schemas/request.py:74:Rebalance -->
[request.py](../../backend/analysis/schemas/request.py#L74)

사용자 리밸런싱 count와 단위입니다. count=0은 정기 조정 없음이고 실제 날짜는 RebalanceRule과 달력으로 결정합니다.

기반: `BaseModel`.

| 필드 | 자료형 | 기본값 또는 생성 방식 | 선언된 제약·설명 |
| --- | --- | --- | --- |
| `count` | `int` | `필수 입력` | 반복 횟수 또는 일정 배수; ge=0, description='0 = no rebalancing (buy and hold)' |
| `unit` | `RebalanceUnit` | `필수 입력` | 비율 단위 또는 리밸런싱 단위 |


<a id="schemas-request-py-Constraints-79"></a>
### `Constraints`

<!-- source-symbol: schemas/request.py:79:Constraints -->
[request.py](../../backend/analysis/schemas/request.py#L79)

유니버스·자산 유형·종목 수·비중/현금 상한·포함/제외·일정·규모/유동성 조건입니다. 기본 교차 검증을 제공하되 실제 테마 가용성과 종목별 자료는 후속 단계가 확인합니다.

기반: `BaseModel`.

| 필드 | 자료형 | 기본값 또는 생성 방식 | 선언된 제약·설명 |
| --- | --- | --- | --- |
| `universe` | `list[Universe]` | `필수 입력` | 투자 가능 모집단의 지수 목록; min_length=1 |
| `asset_types` | `list[Literal['stock', 'etf']]` | `생성 함수: ['stock']` | 요청 자산 유형; 모델 허용과 실제 후보 지원 범위는 다를 수 있음; min_length=1 |
| `num_holdings` | `NumHoldings` | `필수 입력` | 최소·목표·최대 종목 수 |
| `max_weight_per_stock` | `float` | `필수 입력` | 종목당 허용 비중; gt=0, le=1 |
| `max_weight_per_sector` | `float` | `필수 입력` | 섹터당 허용 비중; gt=0, le=1 |
| `min_cash_ratio` | `float` | `0` | 최소 현금 비율; ge=0, lt=1 |
| `exclude_tickers` | `list[str]` | `[]` | 제외할 티커 |
| `exclude_sectors` | `list[str]` | `[]` | 제외할 산업 섹터 |
| `exclude_themes` | `list[str]` | `[]` | 제외할 자연어 테마 |
| `must_include_tickers` | `list[str]` | `[]` | 필수 포함 요청 티커 |
| `rebalance` | `Rebalance` | `필수 입력` | 사용자 리밸런싱 간격 |
| `allow_leverage` | `bool` | `False` | 레버리지 허용 요청; 현재 True 거부 |
| `allow_short` | `bool` | `False` | 공매도 허용 요청; 현재 True 거부 |
| `min_market_cap_usd` | `float` | `0` | 최소 USD 시가총액; ge=0 |
| `min_avg_daily_volume_usd` | `float` | `0` | 최소 USD 일평균 거래대금; ge=0 |

메서드·속성: [_feasible](#schemas-request-py-Constraints-_feasible-97), [markets](#schemas-request-py-Constraints-markets-115).


<a id="schemas-request-py-StrategyPreference-119"></a>
### `StrategyPreference`

<!-- source-symbol: schemas/request.py:119:StrategyPreference -->
[request.py](../../backend/analysis/schemas/request.py#L119)

최종 종목을 고를 지표 템플릿, 기준 비중 방식, 뉴스 반영 켜짐을 담습니다. 선정 방식과 비중 방식은 서로 다른 축입니다.

기반: `BaseModel`.

| 필드 | 자료형 | 기본값 또는 생성 방식 | 선언된 제약·설명 |
| --- | --- | --- | --- |
| `template` | `Template` | `필수 입력` | 정량 선정 기준 또는 전략의 기준 템플릿 |
| `baseline_weighting` | `Weighting` | `필수 입력` | 기준 비중을 계산할 방식 |
| `use_news_tilt` | `bool` | `True` | 근거 의견으로 기준 비중을 조정할지 |


<a id="schemas-request-py-NaturalLanguage-125"></a>
### `NaturalLanguage`

<!-- source-symbol: schemas/request.py:125:NaturalLanguage -->
[request.py](../../backend/analysis/schemas/request.py#L125)

최소 5자의 투자 아이디어와 언어입니다. 자유 보충 답변은 조립 단계에서 idea 본문에 합쳐집니다.

기반: `BaseModel`.

| 필드 | 자료형 | 기본값 또는 생성 방식 | 선언된 제약·설명 |
| --- | --- | --- | --- |
| `idea` | `str` | `필수 입력` | 사용자 투자 아이디어 본문; min_length=5 |
| `language` | `str` | `'ko'` | 입출력 언어 |


<a id="schemas-request-py-UserRequest-130"></a>
### `UserRequest`

<!-- source-symbol: schemas/request.py:130:UserRequest -->
[request.py](../../backend/analysis/schemas/request.py#L130)

프로필·자본·기간·위험·제약·전략·아이디어를 묶은 검증 요청입니다. extra=ignore이므로 미지 키는 이 모델 변환에서 무시됩니다.

기반: `BaseModel`.

| 필드 | 자료형 | 기본값 또는 생성 방식 | 선언된 제약·설명 |
| --- | --- | --- | --- |
| `request_id` | `str` | `필수 입력` | 대화·분석 요청을 연결하는 ID |
| `created_at` | `str` | `필수 입력` | 객체 생성 시각 문자열 |
| `profile` | `Profile` | `필수 입력` | 연령·경험·지식 등 사용자 조건 |
| `capital` | `Capital` | `필수 입력` | 평가 자본 조건 또는 입력 자본 |
| `horizon` | `Horizon` | `필수 입력` | 투자 목적·보유 기간·과거 평가 기간·기준일 |
| `risk` | `Risk` | `필수 입력` | 위험 성향·허용 낙폭·목표수익·비교지수 |
| `constraints` | `Constraints` | `필수 입력` | 유니버스·개수·비중·포함/제외·일정 제약 |
| `strategy_preference` | `StrategyPreference` | `필수 입력` | 선정 지표·기준 비중·뉴스 반영 선호 |
| `natural_language` | `NaturalLanguage` | `필수 입력` | — |


<a id="schemas-request-py-RebalanceRule-144"></a>
### `RebalanceRule`

<!-- source-symbol: schemas/request.py:144:RebalanceRule -->
[request.py](../../backend/analysis/schemas/request.py#L144)

사용자 count/unit을 실행용 거래일 간격 또는 달력 규칙·활성화·한국어 설명으로 변환한 파생 계약입니다.

기반: `BaseModel`.

| 필드 | 자료형 | 기본값 또는 생성 방식 | 선언된 제약·설명 |
| --- | --- | --- | --- |
| `count` | `int` | `필수 입력` | 반복 횟수 또는 일정 배수 |
| `unit` | `RebalanceUnit` | `필수 입력` | 비율 단위 또는 리밸런싱 단위 |
| `enabled` | `bool` | `필수 입력` | 해당 기능·규칙의 활성화 |
| `description_ko` | `str` | `필수 입력` | 한국어 설명 |
| `trading_days` | `int \| None` | `None` | 연간 거래일 기준 또는 해당 기간 거래일 수 |
| `calendar` | `Literal['month_start', 'quarter_start', 'half_year_start', 'year_start'] \| None` | `None` | — |


<a id="schemas-request-py-Derived-153"></a>
### `Derived`

<!-- source-symbol: schemas/request.py:153:Derived -->
[request.py](../../backend/analysis/schemas/request.py#L153)

기준일·환율·현재 USD 자본·자료 범위·백테스트 창·시장·경고와 시작일 환산 참고값입니다. 최종 첫 거래일 자본은 BacktestSpec에서 다시 확정됩니다.

기반: `BaseModel`.

| 필드 | 자료형 | 기본값 또는 생성 방식 | 선언된 제약·설명 |
| --- | --- | --- | --- |
| `as_of` | `date` | `필수 입력` | 자료 판단 기준일 |
| `fx_pair` | `str` | `'USDKRW'` | 환율 통화쌍 |
| `fx_rate` | `float` | `필수 입력` | 입력 통화 환산율; USD 입력이면 1, KRW 입력이면 USDKRW; gt=0, description='KRW per USD at fx_date (1.0 if currency is USD)' |
| `fx_date` | `date` | `필수 입력` | 사용 환율의 관측일 |
| `fx_source` | `str` | `'db'` | 환율 출처 |
| `initial_amount_usd` | `float` | `필수 입력` | USD 환산 초기자본 |
| `monthly_contribution_usd` | `float` | `필수 입력` | 백테스트가 사용할 USD 월 적립금 |
| `rebalance_rule` | `RebalanceRule` | `필수 입력` | 실행용 리밸런싱 규칙 |
| `price_data_start` | `date` | `필수 입력` | 가격 데이터 가용 시작 |
| `price_data_end` | `date` | `필수 입력` | 가격 데이터 가용 상한 |
| `backtest_start` | `date` | `필수 입력` | 파생된 과거 평가 시작일 |
| `backtest_end` | `date` | `필수 입력` | 파생된 과거 평가 끝 기준일 |
| `markets` | `list[str]` | `필수 입력` | 관련 시장 목록 |
| `warnings` | `list[str]` | `[]` | 문맥별 전체 경고 또는 문장 검사 메모 |
| `backtest_fx_rate` | `float \| None` | `None` | 평가 시작 환율 참고값 |
| `backtest_fx_date` | `date \| None` | `None` | 평가 시작 환율 관측일 |
| `initial_amount_usd_at_backtest_start` | `float \| None` | `None` | 시작일 환율로 환산한 자본 참고값 |
| `monthly_contribution_usd_at_backtest_start` | `float \| None` | `None` | 시작일 환율로 환산한 적립 참고값 |


<a id="schemas-request-py-NormalizedRequest-175"></a>
### `NormalizedRequest`

<!-- source-symbol: schemas/request.py:175:NormalizedRequest -->
[request.py](../../backend/analysis/schemas/request.py#L175)

UserRequest를 상속하고 01_request 단계명·Derived를 추가한 요청입니다.

기반: `UserRequest`.

| 필드 | 자료형 | 기본값 또는 생성 방식 | 선언된 제약·설명 |
| --- | --- | --- | --- |
| `stage` | `str` | `'01_request'` | 단계 산출물 종류 |
| `derived` | `Derived` | `필수 입력` | 기준일·환율 등 코드 파생값 |


<a id="schemas-results-py-Check-10"></a>
### `Check`

<!-- source-symbol: schemas/results.py:10:Check -->
[results.py](../../backend/analysis/schemas/results.py#L10)

검증 규칙 한 행으로 종류·이름·수준·상태·만족 여부·측정값·기준·메시지를 담습니다. flag와 fail은 의미가 다릅니다.

기반: `BaseModel`.

| 필드 | 자료형 | 기본값 또는 생성 방식 | 선언된 제약·설명 |
| --- | --- | --- | --- |
| `rule` | `str` | `필수 입력` | 검증 규칙 ID |
| `name_ko` | `str` | `필수 입력` | 한국어 이름 |
| `level` | `Literal['hard', 'soft', 'info', 'flag']` | `필수 입력` | 경고/검증 수준 |
| `status` | `Literal['pass', 'warn', 'fail', 'info', 'flag']` | `필수 입력` | 소속 객체의 처리 상태 |
| `ok` | `bool \| None` | `None` | 판정 기준 만족 여부 |
| `value` | `float \| None` | `None` | 선택·변경·지표의 실제 값 |
| `threshold` | `float \| None` | `None` | 검증 기준 수치 |
| `message_ko` | `str` | `필수 입력` | 한국어 안내·오류 문장 |


<a id="schemas-results-py-ValidationResult-21"></a>
### `ValidationResult`

<!-- source-symbol: schemas/results.py:21:ValidationResult -->
[results.py](../../backend/analysis/schemas/results.py#L21)

한 포트폴리오의 사용자 checks와 내부 integrity, 실패/주의/낙폭 표시 수입니다.

기반: `BaseModel`.

| 필드 | 자료형 | 기본값 또는 생성 방식 | 선언된 제약·설명 |
| --- | --- | --- | --- |
| `id` | `str` | `필수 입력` | 현재 객체의 식별자 |
| `kind` | `str` | `필수 입력` | 객체·전략·근거·시점의 종류 |
| `status` | `Literal['pass', 'warn', 'fail']` | `필수 입력` | 소속 객체의 처리 상태 |
| `checks` | `list[Check]` | `필수 입력` | 사용자 기준 검사 행 |
| `n_fail` | `int` | `필수 입력` | 실패 항목 수 |
| `n_warn` | `int` | `필수 입력` | 권장 기준 주의 수 |
| `n_flag` | `int` | `0` | 허용 낙폭 초과 표시 수 |
| `integrity` | `list[Check]` | `[]` | 종목/섹터 상한·자료의 내부 무결성 검사 |


<a id="schemas-results-py-Validation-32"></a>
### `Validation`

<!-- source-symbol: schemas/results.py:32:Validation -->
[results.py](../../backend/analysis/schemas/results.py#L32)

모든 후보의 검사·비교표·추천·선택 ID·요약·경고입니다. 현재 alternatives는 호환용 빈 목록이고 낙폭 맞춤안은 backtest.portfolios에 있습니다.

기반: `BaseModel`.

| 필드 | 자료형 | 기본값 또는 생성 방식 | 선언된 제약·설명 |
| --- | --- | --- | --- |
| `request_id` | `str` | `필수 입력` | 대화·분석 요청을 연결하는 ID |
| `stage` | `str` | `'12_validation'` | 단계 산출물 종류 |
| `criteria` | `dict` | `필수 입력` | — |
| `results` | `list[ValidationResult]` | `필수 입력` | — |
| `comparison_table` | `list[dict]` | `필수 입력` | 전략·비교지수의 비교 행 |
| `recommended` | `dict \| None` | `None` | 순위 1위 추천 정보 |
| `alternatives` | `list[dict]` | `[]` | 구형 현금 혼합안 호환 필드; 현재 새 생성은 없음 |
| `chosen_id` | `str \| None` | `None` | 문서가 중심으로 설명할 포트폴리오 ID |
| `summary` | `dict` | `필수 입력` | 객체별 요약 또는 대시보드 |
| `warnings` | `list[str]` | `[]` | 문맥별 전체 경고 또는 문장 검사 메모 |


<a id="schemas-results-py-ResultsBundle-45"></a>
### `ResultsBundle`

<!-- source-symbol: schemas/results.py:45:ResultsBundle -->
[results.py](../../backend/analysis/schemas/results.py#L45)

13_results 통합 계약입니다. 요청·의도·선정·포트폴리오·백테스트·검증·원화 표시·근거 색인·출처·설정·사용량·경고를 묶고 포트폴리오 ID와 날짜축의 일관성을 확인합니다.

기반: `BaseModel`.

| 필드 | 자료형 | 기본값 또는 생성 방식 | 선언된 제약·설명 |
| --- | --- | --- | --- |
| `request_id` | `str` | `필수 입력` | 대화·분석 요청을 연결하는 ID |
| `run_id` | `str` | `필수 입력` | 분석 실행 시도의 ID |
| `stage` | `str` | `'13_results'` | 단계 산출물 종류 |
| `generated_at` | `str` | `필수 입력` | 분석 산출물 생성 시각 문자열 |
| `pipeline_version` | `str` | `필수 입력` | 분석 구현 버전 표기 |
| `request` | `dict` | `필수 입력` | 분석 조건의 요청 사전 |
| `intent` | `dict` | `필수 입력` | 검증·보정한 투자 해석 명세 |
| `selection` | `dict` | `필수 입력` | 선정 사양·결과 |
| `portfolio` | `dict` | `필수 입력` | — |
| `backtest` | `dict` | `필수 입력` | 과거 평가 창 또는 평가 결과 |
| `validation` | `dict` | `필수 입력` | — |
| `money_krw` | `dict` | `필수 입력` | 별도 환율 기준의 원화 표시 금액 |
| `evidence_index` | `dict` | `필수 입력` | 전체 인용 ID→근거 메타 |
| `data_quality` | `dict \| None` | `None` | 가격 커버리지·채움·제외 요약 |
| `llm_usage` | `dict` | `필수 입력` | LLM 호출·토큰·비용·캐시 통계 |
| `sources` | `list[dict]` | `필수 입력` | 자료 출처 목록 |
| `parameters` | `dict` | `필수 입력` | 계산에 사용한 설정 |
| `warnings` | `list[dict]` | `[]` | 문맥별 전체 경고 또는 문장 검사 메모 |
| `warnings_summary` | `list[str]` | `[]` | 사용자·참고 경고의 렌더링 요약 |
| `notices` | `list[dict]` | `[]` | 사용자 확인이 필요한 공지 |
| `notices_ko` | `list[str]` | `[]` | 사용자 공지의 렌더링 문장 |

메서드·속성: [_consistency](#schemas-results-py-ResultsBundle-_consistency-71).


<a id="schemas-run-py-RunIndexEntry-21"></a>
### `RunIndexEntry`

<!-- source-symbol: schemas/run.py:21:RunIndexEntry -->
[run.py](../../backend/analysis/schemas/run.py#L21)

runs.json 한 실행 항목입니다. 큐 상태·시각·산출물 경로·리포트·취소·PID·오류를 담으며 extra=allow로 추가 메타를 허용합니다.

기반: `BaseModel`.

| 필드 | 자료형 | 기본값 또는 생성 방식 | 선언된 제약·설명 |
| --- | --- | --- | --- |
| `run_id` | `str` | `필수 입력` | 분석 실행 시도의 ID |
| `request_id` | `str` | `필수 입력` | 대화·분석 요청을 연결하는 ID |
| `status` | `RunState` | `필수 입력` | 소속 객체의 처리 상태 |
| `queued_at` | `str` | `필수 입력` | 실행 등록 시각 |
| `started_at` | `str \| None` | `None` | 실행·단계 시작 시각 |
| `finished_at` | `str \| None` | `None` | 실행 종료 시각 |
| `output_dir` | `str` | `필수 입력` | 실행 산출물 위치 |
| `report_id` | `str \| None` | `None` | 저장 리포트 ID |
| `llm_mode` | `Literal['stub', 'api'] \| None` | `None` | 실제 API 또는 개발 stub 모드 |
| `error_code` | `str \| None` | `None` | 안정된 업무 오류 코드 |
| `error_message` | `str \| None` | `None` | 실패 원인 설명 |
| `cancel_requested_at` | `str \| None` | `None` | 취소 요청 시각 |
| `worker_pid` | `int \| None` | `None` | 실행을 선점한 워커 PID |
| `scenario` | `str \| None` | `None` | — |


<a id="schemas-run-py-RunStep-40"></a>
### `RunStep`

<!-- source-symbol: schemas/run.py:40:RunStep -->
[run.py](../../backend/analysis/schemas/run.py#L40)

API의 단계 상태로 실행 단계 ID·라벨·화면 묶음·대문자 상태·시각·요약·오류를 담습니다.

기반: `BaseModel`.

| 필드 | 자료형 | 기본값 또는 생성 방식 | 선언된 제약·설명 |
| --- | --- | --- | --- |
| `step` | `str` | `필수 입력` | — |
| `label_ko` | `str` | `필수 입력` | 한국어 표시 라벨 |
| `bucket` | `str` | `필수 입력` | 화면 진행 묶음 ID |
| `status` | `Literal['QUEUED', 'STARTED', 'SUCCESS', 'PARTIAL', 'FAILED', 'CANCELLED']` | `필수 입력` | 소속 객체의 처리 상태 |
| `started_at` | `str \| None` | `None` | 실행·단계 시작 시각 |
| `ended_at` | `str \| None` | `None` | 단계 종료 시각 |
| `summary` | `str \| None` | `None` | 객체별 요약 또는 대시보드 |
| `error_code` | `str \| None` | `None` | 안정된 업무 오류 코드 |
| `error_message` | `str \| None` | `None` | 실패 원인 설명 |


<a id="schemas-run-py-RunBucket-52"></a>
### `RunBucket`

<!-- source-symbol: schemas/run.py:52:RunBucket -->
[run.py](../../backend/analysis/schemas/run.py#L52)

화면에 표시하는 다섯 진행 묶음 중 하나의 ID·제목·집계 상태입니다.

기반: `BaseModel`.

| 필드 | 자료형 | 기본값 또는 생성 방식 | 선언된 제약·설명 |
| --- | --- | --- | --- |
| `id` | `str` | `필수 입력` | 현재 객체의 식별자 |
| `title_ko` | `str` | `필수 입력` | 화면 한국어 제목 |
| `status` | `Literal['QUEUED', 'STARTED', 'SUCCESS', 'PARTIAL', 'FAILED', 'CANCELLED']` | `필수 입력` | 소속 객체의 처리 상태 |


<a id="schemas-run-py-RunStatus-58"></a>
### `RunStatus`

<!-- source-symbol: schemas/run.py:58:RunStatus -->
[run.py](../../backend/analysis/schemas/run.py#L58)

큐 전체 상태와 단계·묶음 기록, 대기 순번·리포트 ID·오류를 합친 폴링 응답입니다. 큐의 소문자 상태와 단계의 대문자 상태를 구분합니다.

기반: `BaseModel`.

| 필드 | 자료형 | 기본값 또는 생성 방식 | 선언된 제약·설명 |
| --- | --- | --- | --- |
| `run_id` | `str` | `필수 입력` | 분석 실행 시도의 ID |
| `request_id` | `str` | `필수 입력` | 대화·분석 요청을 연결하는 ID |
| `status` | `RunState` | `필수 입력` | 소속 객체의 처리 상태 |
| `queue_position` | `int \| None` | `None` | 등록 순서 기준 대기 순번 |
| `queued_at` | `str` | `필수 입력` | 실행 등록 시각 |
| `started_at` | `str \| None` | `None` | 실행·단계 시작 시각 |
| `finished_at` | `str \| None` | `None` | 실행 종료 시각 |
| `buckets` | `list[RunBucket]` | `필수 입력` | — |
| `steps` | `list[RunStep]` | `필수 입력` | — |
| `report_id` | `str \| None` | `None` | 저장 리포트 ID |
| `error` | `dict \| None` | `None` | 실행 대표 실패 정보 |


<a id="schemas-selection-py-GicsLevel-10"></a>
### `GicsLevel`

<!-- source-symbol: schemas/selection.py:10:GicsLevel -->
[selection.py](../../backend/analysis/schemas/selection.py#L10)

산업분류 한 계층의 코드와 이름입니다.

기반: `BaseModel`.

| 필드 | 자료형 | 기본값 또는 생성 방식 | 선언된 제약·설명 |
| --- | --- | --- | --- |
| `code` | `str` | `필수 입력` | 분류 코드 또는 업무 경고 코드 |
| `name` | `str` | `필수 입력` | 종목·객체 이름 |


<a id="schemas-selection-py-Gics-15"></a>
### `Gics`

<!-- source-symbol: schemas/selection.py:15:Gics -->
[selection.py](../../backend/analysis/schemas/selection.py#L15)

섹터·산업그룹·산업·세부산업 네 계층을 묶습니다.

기반: `BaseModel`.

| 필드 | 자료형 | 기본값 또는 생성 방식 | 선언된 제약·설명 |
| --- | --- | --- | --- |
| `sector` | `GicsLevel` | `필수 입력` | 산업 섹터명 또는 모델 |
| `industry_group` | `GicsLevel` | `필수 입력` | — |
| `industry` | `GicsLevel` | `필수 입력` | — |
| `sub_industry` | `GicsLevel` | `필수 입력` | 세부 산업 |


<a id="schemas-selection-py-Candidate-22"></a>
### `Candidate`

<!-- source-symbol: schemas/selection.py:22:Candidate -->
[selection.py](../../backend/analysis/schemas/selection.py#L22)

검색을 통과한 종목의 메타·규모·유동성·매칭 규칙/테마/키워드·강제 포함 여부입니다. 최종 선정 종목과 다릅니다.

기반: `BaseModel`.

| 필드 | 자료형 | 기본값 또는 생성 방식 | 선언된 제약·설명 |
| --- | --- | --- | --- |
| `ticker` | `str` | `필수 입력` | 가격 조회 표기의 종목 코드 |
| `asset_id` | `str \| None` | `None` | DB 종목 마스터 ID |
| `name` | `str` | `필수 입력` | 종목·객체 이름 |
| `market` | `str` | `'US'` | US·KR 등 시장 |
| `currency` | `str` | `'USD'` | 입력/종목 통화 |
| `gics` | `Gics` | `필수 입력` | 네 계층 산업분류 |
| `company_summary` | `str` | `필수 입력` | 회사 소개 |
| `market_cap_usd` | `float \| None` | `None` | USD 환산 시가총액 |
| `adv_usd` | `float \| None` | `None` | USD 일평균 거래대금 |
| `matched_by` | `list[str]` | `필수 입력` | 후보 검색에 걸린 규칙 |
| `matched_themes` | `list[str]` | `필수 입력` | 검색에 매칭된 테마 |
| `matched_keywords` | `list[str]` | `[]` | 실제로 매칭된 키워드 |
| `forced` | `bool` | `False` | 필수 포함 조건으로 유지한 후보인지 |


<a id="schemas-selection-py-FilteredOut-38"></a>
### `FilteredOut`

<!-- source-symbol: schemas/selection.py:38:FilteredOut -->
[selection.py](../../backend/analysis/schemas/selection.py#L38)

후보 검색에서 제거한 티커와 제거 사유입니다.

기반: `BaseModel`.

| 필드 | 자료형 | 기본값 또는 생성 방식 | 선언된 제약·설명 |
| --- | --- | --- | --- |
| `ticker` | `str` | `필수 입력` | 가격 조회 표기의 종목 코드 |
| `reason` | `str` | `필수 입력` | — |


<a id="schemas-selection-py-Candidates-43"></a>
### `Candidates`

<!-- source-symbol: schemas/selection.py:43:Candidates -->
[selection.py](../../backend/analysis/schemas/selection.py#L43)

기준일·사전 버전·후보 목록·제외 사유·검색 통계·경고를 담는 03 산출물입니다.

기반: `BaseModel`.

| 필드 | 자료형 | 기본값 또는 생성 방식 | 선언된 제약·설명 |
| --- | --- | --- | --- |
| `request_id` | `str` | `필수 입력` | 대화·분석 요청을 연결하는 ID |
| `stage` | `str` | `'03_candidates'` | 단계 산출물 종류 |
| `as_of` | `date` | `필수 입력` | 자료 판단 기준일 |
| `descriptor_version` | `str \| None` | `None` | 검색 사전 파일 버전 |
| `candidates` | `list[Candidate]` | `필수 입력` | — |
| `filtered_out` | `list[FilteredOut]` | `[]` | 검색 중 제거한 후보와 사유 |
| `stats` | `dict` | `필수 입력` | 검색 통계 |
| `warnings` | `list[str]` | `[]` | 문맥별 전체 경고 또는 문장 검사 메모 |


<a id="schemas-selection-py-TagResult-54"></a>
### `TagResult`

<!-- source-symbol: schemas/selection.py:54:TagResult -->
[selection.py](../../backend/analysis/schemas/selection.py#L54)

한 후보의 테마 해당 여부·테마 ID·신뢰도·한국어 이유·제외 테마를 담습니다.

기반: `BaseModel`.

| 필드 | 자료형 | 기본값 또는 생성 방식 | 선언된 제약·설명 |
| --- | --- | --- | --- |
| `ticker` | `str` | `필수 입력` | 가격 조회 표기의 종목 코드 |
| `in_theme` | `bool` | `필수 입력` | 테마 관련 여부 판정 |
| `themes` | `list[str]` | `[]` | 해석한 투자 테마 목록 |
| `confidence` | `float` | `필수 입력` | 의견·테마 판정 신뢰도; ge=0, le=1 |
| `reason_ko` | `str` | `필수 입력` | 한국어 판단 이유 |
| `excluded_theme` | `str \| None` | `None` | 제외 테마 해당 사유 |


<a id="schemas-selection-py-Tagging-63"></a>
### `Tagging`

<!-- source-symbol: schemas/selection.py:63:Tagging -->
[selection.py](../../backend/analysis/schemas/selection.py#L63)

분류 결과·제외 테마 목록·통과 티커·최소 신뢰도·배치 수·경고를 묶는 04 산출물입니다.

기반: `BaseModel`.

| 필드 | 자료형 | 기본값 또는 생성 방식 | 선언된 제약·설명 |
| --- | --- | --- | --- |
| `request_id` | `str` | `필수 입력` | 대화·분석 요청을 연결하는 ID |
| `stage` | `str` | `'04_tagging'` | 단계 산출물 종류 |
| `min_confidence` | `float` | `필수 입력` | 테마 판정 통과 최소 신뢰도 |
| `tagged` | `list[TagResult]` | `필수 입력` | 일반 테마 판정 결과 |
| `excluded_by_theme` | `list[TagResult]` | `[]` | 제외 테마에 해당한 판정 목록 |
| `passed_tickers` | `list[str]` | `필수 입력` | 테마 분류를 통과한 종목 |
| `batches` | `int` | `필수 입력` | 분류 호출 배치 수 |
| `warnings` | `list[str]` | `[]` | 문맥별 전체 경고 또는 문장 검사 메모 |


<a id="schemas-selection-py-Selected-74"></a>
### `Selected`

<!-- source-symbol: schemas/selection.py:74:Selected -->
[selection.py](../../backend/analysis/schemas/selection.py#L74)

최종 선정 종목의 회사·섹터·순위·지표와 Fact ID·테마 신뢰도·강제 포함 여부입니다.

기반: `BaseModel`.

| 필드 | 자료형 | 기본값 또는 생성 방식 | 선언된 제약·설명 |
| --- | --- | --- | --- |
| `ticker` | `str` | `필수 입력` | 가격 조회 표기의 종목 코드 |
| `name` | `str` | `필수 입력` | 종목·객체 이름 |
| `sector` | `str` | `필수 입력` | 산업 섹터명 또는 모델 |
| `sector_code` | `str` | `필수 입력` | 산업 섹터 코드 |
| `market` | `str` | `'US'` | US·KR 등 시장 |
| `rank` | `int` | `필수 입력` | 선정 순위 |
| `metric_name` | `str` | `필수 입력` | 선정 지표 이름 |
| `metric_value` | `float` | `필수 입력` | 선정 지표 값 |
| `metric_fact_id` | `str \| None` | `None` | 지표 수치의 fin 인용 ID |
| `theme_confidence` | `float \| None` | `None` | 테마 분류 신뢰도 |
| `forced` | `bool` | `False` | 필수 포함 조건으로 유지한 후보인지 |


<a id="schemas-selection-py-Rejected-88"></a>
### `Rejected`

<!-- source-symbol: schemas/selection.py:88:Rejected -->
[selection.py](../../backend/analysis/schemas/selection.py#L88)

테마 통과 뒤 지표 누락·순위 등으로 최종 선정에서 빠진 종목과 선택 지표값입니다.

기반: `BaseModel`.

| 필드 | 자료형 | 기본값 또는 생성 방식 | 선언된 제약·설명 |
| --- | --- | --- | --- |
| `ticker` | `str` | `필수 입력` | 가격 조회 표기의 종목 코드 |
| `reason` | `str` | `필수 입력` | — |
| `metric_value` | `float \| None` | `None` | 선정 지표 값 |


<a id="schemas-selection-py-Selection-94"></a>
### `Selection`

<!-- source-symbol: schemas/selection.py:94:Selection -->
[selection.py](../../backend/analysis/schemas/selection.py#L94)

선정 목록·제외 목록·지표/개수 요약·배분 불충분·경고를 담는 05 산출물입니다.

기반: `BaseModel`.

| 필드 | 자료형 | 기본값 또는 생성 방식 | 선언된 제약·설명 |
| --- | --- | --- | --- |
| `request_id` | `str` | `필수 입력` | 대화·분석 요청을 연결하는 ID |
| `stage` | `str` | `'05_selection'` | 단계 산출물 종류 |
| `as_of` | `date` | `필수 입력` | 자료 판단 기준일 |
| `selected` | `list[Selected]` | `필수 입력` | 정량 최종 선정 목록 |
| `rejected` | `list[Rejected]` | `[]` | 최종 선정에서 빠진 목록 |
| `summary` | `dict` | `필수 입력` | 객체별 요약 또는 대시보드 |
| `infeasibility` | `dict \| None` | `None` | 상한 아래 배분 불충분 사유·선택지 |
| `warnings` | `list[str]` | `[]` | 문맥별 전체 경고 또는 문장 검사 메모 |


<a id="functions"></a>
## 5. 함수·메서드 상세

시그니처에 입력 자료형·기본값·반환 자료형을 그대로 기재했습니다. `self`는 소속 클래스의 인스턴스, `cls`는 클래스입니다. 반환 주석이 없는 함수는 본문 해설의 반환 내용을 따릅니다. 속성(`property`)은 호출 괄호 없이 읽고, 중첩 함수는 바깥 함수의 지역 상태를 공유합니다. 연결 목록은 정적으로 확인되는 패키지 내부 직접 호출이며, 주입된 서비스·콜백·Repository 호출은 처리 흐름과 해설에서 설명합니다.


<a id="file-schemas-backtest-py"></a>
### schemas/backtest.py


<a id="schemas-backtest-py-BacktestWindow-_order-27"></a>
#### `BacktestWindow._order`

<!-- source-symbol: schemas/backtest.py:27:BacktestWindow._order -->
[backtest.py](../../backend/analysis/schemas/backtest.py#L27)

```python
def _order(self) -> BacktestWindow: ...
```

백테스트 시작일이 종료일보다 엄격히 앞서는지 검사합니다. 두 날짜가 같아도 오류입니다.

선언·진입 조건: `model_validator(mode='after')`.

명시적으로 발생시키는 예외: `ValueError`. 발생 조건은 위 해설과 소스의 분기를 함께 확인합니다.


<a id="schemas-backtest-py-PortfolioResult-_lengths-171"></a>
#### `PortfolioResult._lengths`

<!-- source-symbol: schemas/backtest.py:171:PortfolioResult._lengths -->
[backtest.py](../../backend/analysis/schemas/backtest.py#L171)

```python
def _lengths(self) -> PortfolioResult: ...
```

단일 포트폴리오의 모든 series 배열 길이가 같은지 검사합니다. 전체 날짜 배열 길이와의 비교는 BacktestResults에서 수행합니다.

선언·진입 조건: `model_validator(mode='after')`.

명시적으로 발생시키는 예외: `ValueError`. 발생 조건은 위 해설과 소스의 분기를 함께 확인합니다.


<a id="schemas-backtest-py-BacktestResults-_aligned-194"></a>
#### `BacktestResults._aligned`

<!-- source-symbol: schemas/backtest.py:194:BacktestResults._aligned -->
[backtest.py](../../backend/analysis/schemas/backtest.py#L194)

```python
def _aligned(self) -> BacktestResults: ...
```

대표/보조 비교지수와 모든 전략의 series 길이를 series_dates 길이와 대조합니다. 실제 값의 날짜 의미·품질은 이 검증기의 범위가 아닙니다.

선언·진입 조건: `model_validator(mode='after')`.

명시적으로 발생시키는 예외: `ValueError`. 발생 조건은 위 해설과 소스의 분기를 함께 확인합니다.


<a id="file-schemas-intent-py"></a>
### schemas/intent.py


<a id="schemas-intent-py-_check_gics_codes-16"></a>
#### `_check_gics_codes`

<!-- source-symbol: schemas/intent.py:16:_check_gics_codes -->
[intent.py](../../backend/analysis/schemas/intent.py#L16)

```python
def _check_gics_codes(codes: list[str]) -> list[str]: ...
```

GICS 문자열이 숫자이고 길이가 2·4·6·8 중 하나인지 검사합니다. 실제 산업 코드의 존재 여부는 intent.interpret가 Descriptor와 대조합니다.

명시적으로 발생시키는 예외: `ValueError`. 발생 조건은 위 해설과 소스의 분기를 함께 확인합니다.


<a id="schemas-intent-py-Screen-_metric_matches_template-67"></a>
#### `Screen._metric_matches_template`

<!-- source-symbol: schemas/intent.py:67:Screen._metric_matches_template -->
[intent.py](../../backend/analysis/schemas/intent.py#L67)

```python
def _metric_matches_template(self) -> Screen: ...
```

선정 템플릿이 요구하는 지표·정렬 방향과 입력이 정확히 일치하는지 검사합니다. 다른 지표로 실행되는 모델을 거부합니다.

선언·진입 조건: `model_validator(mode='after')`.

명시적으로 발생시키는 예외: `ValueError`. 발생 조건은 위 해설과 소스의 분기를 함께 확인합니다.


<a id="file-schemas-portfolio-py"></a>
### schemas/portfolio.py


<a id="schemas-portfolio-py-Portfolio-_sums-62"></a>
#### `Portfolio._sums`

<!-- source-symbol: schemas/portfolio.py:62:Portfolio._sums -->
[portfolio.py](../../backend/analysis/schemas/portfolio.py#L62)

```python
def _sums(self) -> Portfolio: ...
```

주식 비중과 현금 합계가 1에서 1e-4 이내인지, 주식 비중이 -1e-9보다 작은지 검사합니다. 종목별·섹터별 사용자 상한은 이 모델에서 직접 검사하지 않습니다.

선언·진입 조건: `model_validator(mode='after')`.

명시적으로 발생시키는 예외: `ValueError`. 발생 조건은 위 해설과 소스의 분기를 함께 확인합니다.


<a id="schemas-portfolio-py-View-_shape-91"></a>
#### `View._shape`

<!-- source-symbol: schemas/portfolio.py:91:View._shape -->
[portfolio.py](../../backend/analysis/schemas/portfolio.py#L91)

```python
def _shape(self) -> View: ...
```

상대 의견의 short 존재·절대 의견의 short 부재·양쪽 티커 중복 금지를 검사합니다. 실제 종목 실존과 근거 ID는 구성 코드에서 따로 확인합니다.

선언·진입 조건: `model_validator(mode='after')`.

명시적으로 발생시키는 예외: `ValueError`. 발생 조건은 위 해설과 소스의 분기를 함께 확인합니다.


<a id="file-schemas-report-py"></a>
### schemas/report.py


<a id="schemas-report-py-Section-_types-61"></a>
#### `Section._types`

<!-- source-symbol: schemas/report.py:61:Section._types -->
[report.py](../../backend/analysis/schemas/report.py#L61)

```python
def _types(cls, v: list[dict]) -> list[dict]: ...
```

섹션의 각 블록 type이 BLOCK_TYPES에 있는지 검사합니다. 블록 내부 모든 키를 별도 타입 모델로 검증하는 것은 아닙니다.

선언·진입 조건: `field_validator('blocks')`, `classmethod`.

명시적으로 발생시키는 예외: `ValueError`. 발생 조건은 위 해설과 소스의 분기를 함께 확인합니다.


<a id="schemas-report-py-ReportDoc-_refs-92"></a>
#### `ReportDoc._refs`

<!-- source-symbol: schemas/report.py:92:ReportDoc._refs -->
[report.py](../../backend/analysis/schemas/report.py#L92)

```python
def _refs(self) -> ReportDoc: ...
```

날짜와 시계열 배열 길이, KPI 참조 ID, line/area의 series ID, nav와 섹션 ID 집합 일치를 검사합니다. 일곱 섹션의 정확한 순서와 인용·금지 표현은 별도 report_check.check가 확인합니다.

선언·진입 조건: `model_validator(mode='after')`.

명시적으로 발생시키는 예외: `ValueError`. 발생 조건은 위 해설과 소스의 분기를 함께 확인합니다.


<a id="file-schemas-request-py"></a>
### schemas/request.py


<a id="schemas-request-py-NumHoldings-_order-66"></a>
#### `NumHoldings._order`

<!-- source-symbol: schemas/request.py:66:NumHoldings._order -->
[request.py](../../backend/analysis/schemas/request.py#L66)

```python
def _order(self) -> NumHoldings: ...
```

최소≤목표≤최대 관계를 검사하고 같은 모델을 반환합니다. 수치별 양수 조건은 필드 Field가 먼저 검사합니다.

선언·진입 조건: `model_validator(mode='after')`.

명시적으로 발생시키는 예외: `ValueError`. 발생 조건은 위 해설과 소스의 분기를 함께 확인합니다.


<a id="schemas-request-py-Constraints-_feasible-97"></a>
#### `Constraints._feasible`

<!-- source-symbol: schemas/request.py:97:Constraints._feasible -->
[request.py](../../backend/analysis/schemas/request.py#L97)

```python
def _feasible(self) -> Constraints: ...
```

종목 상한×최소 종목 수의 자금 수용, 섹터 상한≥종목 상한, 필수 티커 수, 포함/제외 충돌, 레버리지·공매도 금지를 검사합니다. 실제 테마의 섹터 구성에 따른 배분 가능성은 선정·구성 단계가 따로 확인합니다.

선언·진입 조건: `model_validator(mode='after')`.

명시적으로 발생시키는 예외: `ValueError`. 발생 조건은 위 해설과 소스의 분기를 함께 확인합니다.


<a id="schemas-request-py-Constraints-markets-115"></a>
#### `Constraints.markets`

<!-- source-symbol: schemas/request.py:115:Constraints.markets -->
[request.py](../../backend/analysis/schemas/request.py#L115)

```python
def markets(self) -> list[str]: ...
```

요청 유니버스 목록을 UNIVERSE_MARKET으로 매핑해 중복 제거·정렬한 시장 목록을 반환합니다.


<a id="file-schemas-results-py"></a>
### schemas/results.py


<a id="schemas-results-py-ResultsBundle-_consistency-71"></a>
#### `ResultsBundle._consistency`

<!-- source-symbol: schemas/results.py:71:ResultsBundle._consistency -->
[results.py](../../backend/analysis/schemas/results.py#L71)

```python
def _consistency(self) -> ResultsBundle: ...
```

백테스트 시계열 길이, 정적/날짜별 타겟과 결과 포트폴리오 ID 집합, matched의 base_id·명명 규칙, 모든 후보·비교지수·대안의 원화 표시값 존재를 검사합니다. 필드가 dict인 내부 객체의 모든 도메인 규칙을 재검증하는 것은 아닙니다.

선언·진입 조건: `model_validator(mode='after')`.

명시적으로 발생시키는 예외: `ValueError`. 발생 조건은 위 해설과 소스의 분기를 함께 확인합니다.


<a id="interactions"></a>
## 6. 다른 모듈과의 상호작용

모든 업무 모듈이 계약을 가져다 씁니다. 생산자는 model_dump로 JSON 호환 값을 만들고 소비자는 필요한 경계에서 model_validate합니다. [API](api_구현보고서.md)의 response_model도 이 계약 일부를 사용합니다. 모든 중간 dict가 모든 호출 시점에 동일 수준으로 재검증되는 것은 아닙니다.

로컬 JSON Schema 파일과 Pydantic 모델은 별도 검증 수단입니다. [common](common_구현보고서.md)의 profile·paper 저장은 일부 JSON Schema를 적용하고 RequestStore는 AnalysisRequestDoc을 적용합니다. 모델 상속 필드·공개 재노출·JSON Schema의 실제 적용 위치를 함께 확인해야 합니다. 모의투자 전체 계약은 현재 이 디렉터리에 전용 Pydantic 클래스로 모이지 않고 M6 사전·공통 JSON Schema에 분산되어 있습니다.

<a id="verification"></a>
## 7. 오류·제약과 검증 근거

모든 객체가 동일한 extra 정책을 쓰지는 않습니다. UserRequest는 ignore, AnalysisRequestDoc은 forbid, RunIndexEntry는 allow입니다. 또한 model_copy(update=...)는 일반 model_validate와 같은 전체 재검증이 아닙니다.

BacktestRequest의 confirmation 추가/제외와 backtest 기간·재선정·적립·비교지수는 실제 spec 생성에서 사용합니다. 반면 현재 Stage는 views·walkforward·forward_construction 설정을 읽지 않으며 10w/10f를 항상 등록합니다. 이 요청 모델의 enabled나 의견 수를 바꿨다는 이유만으로 실행 기능이 바뀌었다고 설명하지 않습니다.

dict로 선언된 metrics·header·blocks 내부는 전용 구조 모델만큼 엄격하지 않습니다. 모델에서 허용하는 ETF, 한 종목, enabled 설정과 실제 서비스가 지원·사용하는 기능은 같지 않을 수 있습니다. 예를 들어 시장모형은 최소 2종목이 필요하고 후보 선정은 주식 중심입니다. 코드가 실행 시 적용하는 교차 규칙과 모델의 선언 범위를 함께 읽어야 합니다.

### 관련 테스트

아래는 테스트 소스에서 확인한 검증 시나리오입니다. 이번 문서 작성에서는 금융 DB·유료 LLM·시나리오 워커를 실행하지 않았으며, 테스트 통과를 새로 보증하는 기록으로 사용하지 않습니다.

- [test_foundations.py](../../backend/tests/analysis/test_foundations.py): 요청 교차 제약과 예시 모델 검증.
- [test_report_doc_v2.py](../../backend/tests/analysis/test_report_doc_v2.py): 문서 배열/참조·v2 블록·v1 표시 정규화.
- [test_round5_dialog.py](../../backend/tests/analysis/test_round5_dialog.py): 질문 patch 직렬화와 필드 단위 오류.

### 문서 검증

구문 분석 정의 목록과 대조하여 이 보고서의 클래스 79개와 함수/메서드 13개를 모두 설명했습니다. 상대경로 링크와 내부 앵커를 별도로 확인합니다.
