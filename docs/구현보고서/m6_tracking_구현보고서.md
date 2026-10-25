# m6_tracking 구현보고서

[전체 안내](README.md)

> 작성 기준: 2026-10-25 작업 공간의 실제 소스. 기존 설계 문서는 배경 참고용이며 아래 동작 설명은 구현을 기준으로 합니다.

대상: Python 파일 2개 · 클래스 2개 · 함수/메서드 26개(중첩 함수와 비공개 보조 함수 포함).

[역할](#role) · [파일 구성](#files) · [처리 흐름](#flow) · [클래스](#classes) · [함수](#functions) · [모듈 연계](#interactions) · [오류·검증](#verification)

<a id="role"></a>
## 1. 모듈의 역할과 용어

`m6_tracking`은 리포트 전략을 가상 자본으로 시작한 뒤 새 자료가 들어오는 날짜마다 운용 결과를 기록합니다. 실제 계좌·브로커·주문 전송은 없고 DB 가격으로 가상 체결합니다. 사용자가 명시적으로 등록해야 추적 대상이 됩니다.

snapshot은 하루 평가 기록, rebalance 기록은 최초 매수·적립·정기 조정의 가상 거래 원장입니다. 단위가격은 자금을 동일한 단위로 나눈 기준가격으로, 적립 시 새 단위를 발행해 추가 납입을 수익으로 오인하지 않게 합니다. delayed는 필수 자료 부족으로 최신 평가를 만들지 못한 상태입니다.

`PaperService.preview()`가 시작 조건을 계산하고 `create()`가 등록합니다. `refresh()`는 날짜를 진행시키고 워커는 한가할 때 `refresh_all_papers()`를 호출합니다. 백테스트와 같은 구성 함수를 사용하지만 모의투자의 실제 기록은 별도로 저장합니다.

<a id="files"></a>
## 2. 파일 구성과 책임

| 파일 | 책임 | 문서 내 해설 |
| --- | --- | --- |
| [m6_tracking/__init__.py](../../backend/analysis/m6_tracking/__init__.py) | 패키지 목적 설명; 독립 함수·클래스 정의 없음 | 정의 없음 |
| [m6_tracking/paper.py](../../backend/analysis/m6_tracking/paper.py) | 전략 해석·계획·가상 거래·날짜 진행·상태·조회 | [클래스 2 · 함수 26](#file-m6_tracking-paper-py) |

<a id="flow"></a>
## 3. 처리 흐름과 예시

1. 리포트와 결과 번들에서 선택 전략·현재 종목을 읽습니다. 기본 시작일은 최신 공통 거래일이며 리포트 기준일보다 이를 수 없습니다.
2. 리포트 기준일과 같으면 저장된 현재 비중을 사용하고 더 늦으면 `construct(mode="paper")`로 비중을 새로 구합니다.
3. preview는 비중·환율·배분·현재 대비 차이를 반환합니다. create는 같은 계획 함수를 다시 계산하고 최초 가상 매수·스냅샷을 저장합니다.
4. refresh는 마지막 처리일 이후 날짜를 진행하며 적립·정기 조정·수수료를 반영합니다. 필수 가격 부재는 지연, 구성 자료 부족은 이전 목표 비중 대체가 될 수 있습니다.
5. stop은 보유를 청산하지 않고 갱신을 중단합니다. resume은 재개 전 일별 기록을 비워 두고 지나간 리밸런싱은 skipped로 표시합니다.

예를 들어 평가액 1,100 USD, 단위 수 1,000이면 단위가격은 1.1입니다. 110 USD를 적립할 때 100단위를 추가하면 평가액 1,210/단위 1,100으로 단위가격은 여전히 1.1입니다. 실제 코드에는 당일 가격 변동·거래비용도 반영되므로 수익률은 그 효과만큼 움직일 수 있습니다. 비교지수도 같은 적립 USD를 투자합니다.

전략은 템플릿·뉴스 BL·맞춤 현금 축소를 해석합니다. `dd_match_*`는 과거에 구한 c를 고정해 같은 기준 구성에 (1-c)를 적용하며 모의투자 미래 낙폭이 목표를 반드시 만족한다는 뜻은 아닙니다. BL은 각 새 날짜에 한 세트 의견을 만들어 적용하고 근거 부족이면 기준 비중을 사용합니다.

저장 구조는 `paper/<ID>/portfolio.json`(설정·제약 스냅샷·현재 보유·현금·단위·상태), `snapshots.jsonl`(날짜별 금액·수익·낙폭·적립·비교지수), `rebalances.jsonl`(최초 매수·적립·정기 조정·건너뜀)입니다. API detail은 내부 의도 스냅샷을 제외한 공개 데이터와 차트 배열을 조립합니다.


<a id="classes"></a>
## 4. 클래스 상세

필드 표는 해당 클래스에서 직접 선언한 필드입니다. 상속 필드는 부모 클래스 설명을 함께 읽습니다. `Field(...)`의 범위는 선언된 검증이며, 서비스에서 추가하는 조건은 함수 설명에 구분합니다.

<a id="m6_tracking-paper-py-Strategy-50"></a>
### `Strategy`

<!-- source-symbol: m6_tracking/paper.py:50:Strategy -->
[paper.py](../../backend/analysis/m6_tracking/paper.py#L50)

모의투자가 이해하는 불변 전략 정의입니다. 원래 ID와 template/black_litterman/cash_blend 종류, 기준 템플릿, 현금 축소 비율, 이름을 보관합니다. cash_ratio는 최종 총현금 비율과 항상 같지 않습니다.

기반: `명시적 부모 없음` · 선언: `dataclass(frozen=True)`.

| 필드 | 자료형 | 기본값 또는 생성 방식 | 선언된 제약·설명 |
| --- | --- | --- | --- |
| `id` | `str` | `필수 입력` | 현재 객체의 식별자 |
| `kind` | `Kind` | `필수 입력` | 객체·전략·근거·시점의 종류 |
| `template` | `str \| None` | `필수 입력` | 정량 선정 기준 또는 전략의 기준 템플릿 |
| `cash_ratio` | `float` | `필수 입력` | 기준 주식 비중을 추가로 축소하는 c |
| `name_ko` | `str` | `필수 입력` | 한국어 이름 |

메서드·속성: [to_dict](#m6_tracking-paper-py-Strategy-to_dict-57).


<a id="m6_tracking-paper-py-PaperService-184"></a>
### `PaperService`

<!-- source-symbol: m6_tracking/paper.py:184:PaperService -->
[paper.py](../../backend/analysis/m6_tracking/paper.py#L184)

리포트 전략을 가상 자본으로 등록·평가하는 서비스입니다. store/papers·repo·md·llm·settings를 사용하며 PaperStore에 상태와 날짜별 원장을 저장합니다. 실제 주문 전송 기능은 없습니다.

기반: `명시적 부모 없음`.

메서드·속성: [__init__](#m6_tracking-paper-py-PaperService-__init__-185), [_bundle](#m6_tracking-paper-py-PaperService-_bundle-194), [_desc](#m6_tracking-paper-py-PaperService-_desc-204), [_report_weights](#m6_tracking-paper-py-PaperService-_report_weights-211), [_construct_weights](#m6_tracking-paper-py-PaperService-_construct_weights-231), [_plan](#m6_tracking-paper-py-PaperService-_plan-272), [preview](#m6_tracking-paper-py-PaperService-preview-329), [create](#m6_tracking-paper-py-PaperService-create-333), [refresh](#m6_tracking-paper-py-PaperService-refresh-367), [_advance](#m6_tracking-paper-py-PaperService-_advance-380), [stop](#m6_tracking-paper-py-PaperService-stop-466), [resume](#m6_tracking-paper-py-PaperService-resume-476), [summary](#m6_tracking-paper-py-PaperService-summary-502), [_snapshots](#m6_tracking-paper-py-PaperService-_snapshots-519), [detail](#m6_tracking-paper-py-PaperService-detail-525), [list](#m6_tracking-paper-py-PaperService-list-536), [refresh_all](#m6_tracking-paper-py-PaperService-refresh_all-539).


<a id="functions"></a>
## 5. 함수·메서드 상세

시그니처에 입력 자료형·기본값·반환 자료형을 그대로 기재했습니다. `self`는 소속 클래스의 인스턴스, `cls`는 클래스입니다. 반환 주석이 없는 함수는 본문 해설의 반환 내용을 따릅니다. 속성(`property`)은 호출 괄호 없이 읽고, 중첩 함수는 바깥 함수의 지역 상태를 공유합니다. 연결 목록은 정적으로 확인되는 패키지 내부 직접 호출이며, 주입된 서비스·콜백·Repository 호출은 처리 흐름과 해설에서 설명합니다.


<a id="file-m6_tracking-paper-py"></a>
### m6_tracking/paper.py


<a id="m6_tracking-paper-py-_d-40"></a>
#### `_d`

<!-- source-symbol: m6_tracking/paper.py:40:_d -->
[paper.py](../../backend/analysis/m6_tracking/paper.py#L40)

```python
def _d(x: Any) -> dt.date: ...
```

pandas 호환 날짜를 순수 date로 변환합니다.

호출하는 코드: [rebalance_due_dates](#m6_tracking-paper-py-rebalance_due_dates-165), [PaperService._advance](#m6_tracking-paper-py-PaperService-_advance-380).


<a id="m6_tracking-paper-py-_now-44"></a>
#### `_now`

<!-- source-symbol: m6_tracking/paper.py:44:_now -->
[paper.py](../../backend/analysis/m6_tracking/paper.py#L44)

```python
def _now() -> str: ...
```

UTC 현재 시각을 호스트 현지 시간대로 변환한 ISO 문자열로 반환합니다.

호출하는 코드: [PaperService.create](#m6_tracking-paper-py-PaperService-create-333), [PaperService.refresh](#m6_tracking-paper-py-PaperService-refresh-367), [PaperService._advance](#m6_tracking-paper-py-PaperService-_advance-380), [PaperService.stop](#m6_tracking-paper-py-PaperService-stop-466), [PaperService.resume](#m6_tracking-paper-py-PaperService-resume-476), [PaperService.refresh_all](#m6_tracking-paper-py-PaperService-refresh_all-539).


<a id="m6_tracking-paper-py-Strategy-to_dict-57"></a>
#### `Strategy.to_dict`

<!-- source-symbol: m6_tracking/paper.py:57:Strategy.to_dict -->
[paper.py](../../backend/analysis/m6_tracking/paper.py#L57)

```python
def to_dict(self) -> dict[str, Any]: ...
```

전략 dataclass를 모의투자 파일·API용 사전으로 반환합니다.


<a id="m6_tracking-paper-py-resolve_strategy-61"></a>
#### `resolve_strategy`

<!-- source-symbol: m6_tracking/paper.py:61:resolve_strategy -->
[paper.py](../../backend/analysis/m6_tracking/paper.py#L61)

```python
def resolve_strategy(strategy_id: str, results: dict[str, Any]) -> Strategy: ...
```

리포트 포트폴리오 ID에서 wf_/fwd_ 접두사를 벗겨 템플릿·BL·현금 축소 전략을 판별합니다. dd_match는 정식 백테스트 후보의 base_id와 cash_ratio를 읽고 구형 cash_blend는 alternatives를 읽습니다. ID가 없거나 기준 방식을 알 수 없으면 오류입니다. BL 시나리오 번호를 그대로 장기 유지하기보다 첫 유효 BL 구성을 쓰는 공통 전략으로 환원합니다.

직접 연결: [NotFound](common_구현보고서.md#errors-py-NotFound-73), [Strategy](#m6_tracking-paper-py-Strategy-50), [RequestInvalid](common_구현보고서.md#errors-py-RequestInvalid-11).

호출하는 코드: [strategy_options](#m6_tracking-paper-py-strategy_options-97), [PaperService._plan](#m6_tracking-paper-py-PaperService-_plan-272).

명시적으로 발생시키는 예외: `NotFound`, `RequestInvalid`. 발생 조건은 위 해설과 소스의 분기를 함께 확인합니다.


<a id="m6_tracking-paper-py-strategy_options-97"></a>
#### `strategy_options`

<!-- source-symbol: m6_tracking/paper.py:97:strategy_options -->
[paper.py](../../backend/analysis/m6_tracking/paper.py#L97)

```python
def strategy_options(results: dict[str, Any]) -> list[dict[str, Any]]: ...
```

검증 결과와 구형 대안에서 해석 가능한 전략만 모아 검증 상태·추천/선택 여부를 붙입니다. 선택안·추천안 우선으로 정렬하며 상태 fail 자체로 등록 가능 목록에서 제거하지는 않습니다.

직접 연결: [resolve_strategy](#m6_tracking-paper-py-resolve_strategy-61).

호출하는 코드: [PaperService._plan](#m6_tracking-paper-py-PaperService-_plan-272).


<a id="m6_tracking-paper-py-trade_to_target-120"></a>
#### `trade_to_target`

<!-- source-symbol: m6_tracking/paper.py:120:trade_to_target -->
[paper.py](../../backend/analysis/m6_tracking/paper.py#L120)

```python
def trade_to_target(holdings: dict[str, float], cash: float, prices: dict[str, float], target_w: dict[str, float], cash_w: float, commission_bps: float) -> tuple[dict[str, float], float, list[dict[str, Any]], float, float]: ...
```

현재 수량·현금·당일 USD 가격으로 총액을 구하고 현금 목표와 수수료 여유를 뺀 투자 금액으로 목표 수량을 계산합니다. 각 종목 차액을 소수 수량으로 가상 매매해 새 보유·현금·거래·수수료·회전율을 반환합니다. 가격이 없거나 양수가 아닌 종목은 건너뛰고 반환 현금은 음수면 0으로 제한합니다.

호출하는 코드: [PaperService.create](#m6_tracking-paper-py-PaperService-create-333), [PaperService._advance](#m6_tracking-paper-py-PaperService-_advance-380).


<a id="m6_tracking-paper-py-weights_of-157"></a>
#### `weights_of`

<!-- source-symbol: m6_tracking/paper.py:157:weights_of -->
[paper.py](../../backend/analysis/m6_tracking/paper.py#L157)

```python
def weights_of(holdings: dict[str, float], cash: float, prices: dict[str, float]) -> tuple[dict[str, float], float, float]: ...
```

종목 수량×가격을 합쳐 보유 평가액·현금 포함 총액과 비중 사전을 반환합니다. 가격이 없는 보유 종목은 계산에서 빠지므로 정상 서비스 경로는 필수 가격 품질 검사를 먼저 합니다.

호출하는 코드: [PaperService.create](#m6_tracking-paper-py-PaperService-create-333), [PaperService._advance](#m6_tracking-paper-py-PaperService-_advance-380).


<a id="m6_tracking-paper-py-rebalance_due_dates-165"></a>
#### `rebalance_due_dates`

<!-- source-symbol: m6_tracking/paper.py:165:rebalance_due_dates -->
[paper.py](../../backend/analysis/m6_tracking/paper.py#L165)

```python
def rebalance_due_dates(rule: dict[str, Any], calendar: pd.DatetimeIndex, start: dt.date, *, two_week_days: int=10) -> list[dt.date]: ...
```

모의투자 시작 이후의 리밸런싱 날짜를 실제 달력으로 고릅니다. 시작일은 최초 매수로 제외하고 백테스트와 달리 마지막 날짜도 정기 일정이면 유지합니다. count=0 또는 빈 달력이면 빈 목록입니다.

직접 연결: [_d](#m6_tracking-paper-py-_d-40).

호출하는 코드: [PaperService._advance](#m6_tracking-paper-py-PaperService-_advance-380), [PaperService.resume](#m6_tracking-paper-py-PaperService-resume-476).


<a id="m6_tracking-paper-py-PaperService-__init__-185"></a>
#### `PaperService.__init__`

<!-- source-symbol: m6_tracking/paper.py:185:PaperService.__init__ -->
[paper.py](../../backend/analysis/m6_tracking/paper.py#L185)

```python
def __init__(self, store: JsonStore, repo: Any, md: MarketData, llm: Any, settings: AnalysisSettings) -> None: ...
```

공유 저장소와 PaperStore·Repository·MarketData·LLM·설정을 보관합니다.

직접 연결: [PaperStore](common_구현보고서.md#common-store-py-PaperStore-231).


<a id="m6_tracking-paper-py-PaperService-_bundle-194"></a>
#### `PaperService._bundle`

<!-- source-symbol: m6_tracking/paper.py:194:PaperService._bundle -->
[paper.py](../../backend/analysis/m6_tracking/paper.py#L194)

```python
def _bundle(self, report_id: str) -> tuple[dict[str, Any], dict[str, Any]]: ...
```

저장된 리포트와 그 run_id의 결과 번들을 함께 읽어 반환합니다. 둘 중 하나라도 없으면 NotFound입니다.

직접 연결: [NotFound](common_구현보고서.md#errors-py-NotFound-73).

호출하는 코드: [PaperService._plan](#m6_tracking-paper-py-PaperService-_plan-272).

명시적으로 발생시키는 예외: `NotFound`. 발생 조건은 위 해설과 소스의 분기를 함께 확인합니다.


<a id="m6_tracking-paper-py-PaperService-_desc-204"></a>
#### `PaperService._desc`

<!-- source-symbol: m6_tracking/paper.py:204:PaperService._desc -->
[paper.py](../../backend/analysis/m6_tracking/paper.py#L204)

```python
def _desc(self, as_of: dt.date, req: dict[str, Any]): ...
```

해당 구성일·요청 유니버스에 맞는 Descriptor를 로드해 반환합니다. 이 함수는 반환된 버전 경고를 따로 전달하지 않습니다.

직접 연결: [load_for](m2_data_구현보고서.md#m2_data-descriptor-py-load_for-24).

호출하는 코드: [PaperService._construct_weights](#m6_tracking-paper-py-PaperService-_construct_weights-231).


<a id="m6_tracking-paper-py-PaperService-_report_weights-211"></a>
#### `PaperService._report_weights`

<!-- source-symbol: m6_tracking/paper.py:211:PaperService._report_weights -->
[paper.py](../../backend/analysis/m6_tracking/paper.py#L211)

```python
def _report_weights(strategy: Strategy, results: dict[str, Any]) -> tuple[dict[str, float], float]: ...
```

리포트의 현재 구성 forward에서 전략에 해당하는 비중을 꺼냅니다. BL은 forward.chosen_weights, 템플릿은 지정 ID를 사용하며 맞춤 전략이면 추가로 (1-c)를 곱하고 잔여를 현금으로 반환합니다.

선언·진입 조건: `staticmethod`.

직접 연결: [NotFound](common_구현보고서.md#errors-py-NotFound-73).

호출하는 코드: [PaperService._plan](#m6_tracking-paper-py-PaperService-_plan-272).

명시적으로 발생시키는 예외: `NotFound`. 발생 조건은 위 해설과 소스의 분기를 함께 확인합니다.


<a id="m6_tracking-paper-py-PaperService-_construct_weights-231"></a>
#### `PaperService._construct_weights`

<!-- source-symbol: m6_tracking/paper.py:231:PaperService._construct_weights -->
[paper.py](../../backend/analysis/m6_tracking/paper.py#L231)

```python
def _construct_weights(self, strategy: Strategy, view: MarketDataView, tickers: list[str], req: dict[str, Any], intent: dict[str, Any], *, stage_tag: str) -> tuple[dict[str, float], float, dict[str, Any]]: ...
```

시작일 또는 리밸런싱일 view로 고정 종목의 비중을 다시 구성합니다. BL과 BL 기반 맞춤안은 한 의견 세트, 템플릿 기반은 뉴스 반영을 꺼 LLM 없이 계산합니다. 비중·현금·의견/근거/fallback/경고 메타를 반환하고 맞춤 현금 비율은 과거 탐색값을 그대로 적용합니다.

직접 연결: [PaperService._desc](#m6_tracking-paper-py-PaperService-_desc-204), [construct](m4_portfolio_구현보고서.md#m4_portfolio-construct-py-construct-59), [PaperService.list](#m6_tracking-paper-py-PaperService-list-536), [DataMissing](common_구현보고서.md#errors-py-DataMissing-38).

호출하는 코드: [PaperService._plan](#m6_tracking-paper-py-PaperService-_plan-272), [PaperService._advance](#m6_tracking-paper-py-PaperService-_advance-380).

명시적으로 발생시키는 예외: `DataMissing`. 발생 조건은 위 해설과 소스의 분기를 함께 확인합니다.


<a id="m6_tracking-paper-py-PaperService-_plan-272"></a>
#### `PaperService._plan`

<!-- source-symbol: m6_tracking/paper.py:272:PaperService._plan -->
[paper.py](../../backend/analysis/m6_tracking/paper.py#L272)

```python
def _plan(self, report_id: str, *, strategy_id: str | None, start_date: dt.date | str | None, initial_amount: float | None, currency: str | None, monthly_contribution: float | None) -> dict[str, Any]: ...
```

리포트·전략을 확인하고 기본 최신 공통 거래일 또는 지정일을 시작일로 정합니다. 리포트 이전·자료 상한 이후 시작은 거부하고 자본·적립·환율·현재 비중 또는 새 구성·차이·필수 가격·배분을 계산합니다. 시작일이 리포트 기준일보다 늦으면 재구성합니다. 외부 표시 정보와 등록에 필요한 '_' 내부 자료를 가진 계획 사전을 반환합니다.

직접 연결: [PaperService._bundle](#m6_tracking-paper-py-PaperService-_bundle-194), [RequestInvalid](common_구현보고서.md#errors-py-RequestInvalid-11), [resolve_strategy](#m6_tracking-paper-py-resolve_strategy-61), [PaperService.list](#m6_tracking-paper-py-PaperService-list-536), [PaperService._report_weights](#m6_tracking-paper-py-PaperService-_report_weights-211), [PaperService._construct_weights](#m6_tracking-paper-py-PaperService-_construct_weights-231), [strategy_options](#m6_tracking-paper-py-strategy_options-97).

호출하는 코드: [PaperService.preview](#m6_tracking-paper-py-PaperService-preview-329), [PaperService.create](#m6_tracking-paper-py-PaperService-create-333).

명시적으로 발생시키는 예외: `RequestInvalid`. 발생 조건은 위 해설과 소스의 분기를 함께 확인합니다.


<a id="m6_tracking-paper-py-PaperService-preview-329"></a>
#### `PaperService.preview`

<!-- source-symbol: m6_tracking/paper.py:329:PaperService.preview -->
[paper.py](../../backend/analysis/m6_tracking/paper.py#L329)

```python
def preview(self, report_id: str, **kw: Any) -> dict[str, Any]: ...
```

_plan을 계산하고 '_' 내부 결과·요청·가격을 제거한 공개 계획을 반환합니다. 계획을 토큰이나 파일로 고정하지 않으며 create가 다시 계산합니다.

직접 연결: [PaperService._plan](#m6_tracking-paper-py-PaperService-_plan-272).


<a id="m6_tracking-paper-py-PaperService-create-333"></a>
#### `PaperService.create`

<!-- source-symbol: m6_tracking/paper.py:333:PaperService.create -->
[paper.py](../../backend/analysis/m6_tracking/paper.py#L333)

```python
def create(self, report_id: str, **kw: Any) -> dict[str, Any]: ...
```

계획을 다시 계산해 가상 최초 매수를 수행하고 portfolio.json·최초 매수 원장·첫 스냅샷을 저장합니다. 초기 단위 수는 USD 자본으로 두고 수수료 후 단위가격을 기록해 손익에 반영합니다. 등록한 모의투자 상세를 반환합니다. 같은 입력의 중복 등록 방지나 preview와 동일 조건을 잠그는 별도 승인 토큰은 없습니다.

직접 연결: [PaperService._plan](#m6_tracking-paper-py-PaperService-_plan-272), [trade_to_target](#m6_tracking-paper-py-trade_to_target-120), [weights_of](#m6_tracking-paper-py-weights_of-157), [new_paper_id](common_구현보고서.md#common-store-py-new_paper_id-108), [_now](#m6_tracking-paper-py-_now-44), [PaperService.list](#m6_tracking-paper-py-PaperService-list-536), [PaperService.detail](#m6_tracking-paper-py-PaperService-detail-525).


<a id="m6_tracking-paper-py-PaperService-refresh-367"></a>
#### `PaperService.refresh`

<!-- source-symbol: m6_tracking/paper.py:367:PaperService.refresh -->
[paper.py](../../backend/analysis/m6_tracking/paper.py#L367)

```python
def refresh(self, paper_id: str) -> dict[str, Any]: ...
```

active인 모의투자만 _advance로 갱신합니다. DataMissing이면 delayed·사유·확인 시각을 저장하고 마지막 성공 기록을 유지합니다. 그 외 예외는 호출자에게 전달되고 stopped 상태는 조회만 반환합니다.

직접 연결: [PaperService.detail](#m6_tracking-paper-py-PaperService-detail-525), [PaperService._advance](#m6_tracking-paper-py-PaperService-_advance-380), [_now](#m6_tracking-paper-py-_now-44).

호출하는 코드: [PaperService.resume](#m6_tracking-paper-py-PaperService-resume-476), [PaperService.refresh_all](#m6_tracking-paper-py-PaperService-refresh_all-539).


<a id="m6_tracking-paper-py-PaperService-_advance-380"></a>
#### `PaperService._advance`

<!-- source-symbol: m6_tracking/paper.py:380:PaperService._advance -->
[paper.py](../../backend/analysis/m6_tracking/paper.py#L380)

```python
def _advance(self, doc: dict[str, Any]) -> None: ...
```

미처리 날짜의 품질 통과 패널과 환율을 읽고 날짜순으로 평가→적립→리밸런싱→최종 단위가격을 기록합니다. 적립은 현재 단위가격으로 단위를 추가해 납입을 수익에서 분리하고 비교지수에도 같은 금액을 넣습니다. 적립 시 trade_to_target을 호출하므로 기존 보유도 목표로 조정될 수 있습니다. 정기 재구성의 DataMissing은 이전 목표 비중으로 대체하며 날짜 중복·재개 전 날짜는 건너뜁니다. 상태 JSON·거래 JSONL·스냅샷 JSONL은 별도 쓰기입니다.

직접 연결: [Strategy](#m6_tracking-paper-py-Strategy-50), [PaperService.list](#m6_tracking-paper-py-PaperService-list-536), [_now](#m6_tracking-paper-py-_now-44), [contribution_dates](m5_backtest_report_구현보고서.md#m5_backtest_report-backtest_engine-py-contribution_dates-42), [rebalance_due_dates](#m6_tracking-paper-py-rebalance_due_dates-165), [_d](#m6_tracking-paper-py-_d-40), [weights_of](#m6_tracking-paper-py-weights_of-157), [trade_to_target](#m6_tracking-paper-py-trade_to_target-120), [PaperService._construct_weights](#m6_tracking-paper-py-PaperService-_construct_weights-231).

호출하는 코드: [PaperService.refresh](#m6_tracking-paper-py-PaperService-refresh-367).


<a id="m6_tracking-paper-py-PaperService-stop-466"></a>
#### `PaperService.stop`

<!-- source-symbol: m6_tracking/paper.py:466:PaperService.stop -->
[paper.py](../../backend/analysis/m6_tracking/paper.py#L466)

```python
def stop(self, paper_id: str) -> dict[str, Any]: ...
```

active 문서를 stopped로 바꾸고 중지 시각·마지막 평가일 이력을 저장합니다. 이미 중지면 Conflict입니다. 보유 자산을 가상 매도하지는 않습니다.

직접 연결: [Conflict](common_구현보고서.md#errors-py-Conflict-78), [_now](#m6_tracking-paper-py-_now-44), [PaperService.detail](#m6_tracking-paper-py-PaperService-detail-525).

명시적으로 발생시키는 예외: `Conflict`. 발생 조건은 위 해설과 소스의 분기를 함께 확인합니다.


<a id="m6_tracking-paper-py-PaperService-resume-476"></a>
#### `PaperService.resume`

<!-- source-symbol: m6_tracking/paper.py:476:PaperService.resume -->
[paper.py](../../backend/analysis/m6_tracking/paper.py#L476)

```python
def resume(self, paper_id: str) -> dict[str, Any]: ...
```

최신 공통 거래일을 재개일로 잡고 마지막 평가 이후 그 전까지 지나간 리밸런싱을 skipped로 남깁니다. active로 저장한 뒤 refresh하며 중지 기간 일별 스냅샷은 소급 생성하지 않습니다. 이미 active면 Conflict입니다.

직접 연결: [Conflict](common_구현보고서.md#errors-py-Conflict-78), [PaperService.list](#m6_tracking-paper-py-PaperService-list-536), [rebalance_due_dates](#m6_tracking-paper-py-rebalance_due_dates-165), [_now](#m6_tracking-paper-py-_now-44), [PaperService.refresh](#m6_tracking-paper-py-PaperService-refresh-367).

명시적으로 발생시키는 예외: `Conflict`. 발생 조건은 위 해설과 소스의 분기를 함께 확인합니다.


<a id="m6_tracking-paper-py-PaperService-summary-502"></a>
#### `PaperService.summary`

<!-- source-symbol: m6_tracking/paper.py:502:PaperService.summary -->
[paper.py](../../backend/analysis/m6_tracking/paper.py#L502)

```python
def summary(self, doc: dict[str, Any], snaps: list[dict[str, Any]] | None=None) -> dict[str, Any]: ...
```

마지막 스냅샷·자본·적립·상태에서 금액 손익, 단위가격 수익·비교지수 대비, 현재/최대낙폭, 처리 날짜·횟수·지연 정보를 계산합니다. 스냅샷이 없으면 초기자본·0 수익으로 요약합니다.

직접 연결: [PaperService._snapshots](#m6_tracking-paper-py-PaperService-_snapshots-519).

호출하는 코드: [PaperService.detail](#m6_tracking-paper-py-PaperService-detail-525), [PaperService.list](#m6_tracking-paper-py-PaperService-list-536).


<a id="m6_tracking-paper-py-PaperService-_snapshots-519"></a>
#### `PaperService._snapshots`

<!-- source-symbol: m6_tracking/paper.py:519:PaperService._snapshots -->
[paper.py](../../backend/analysis/m6_tracking/paper.py#L519)

```python
def _snapshots(self, paper_id: str) -> list[dict[str, Any]]: ...
```

스냅샷 JSONL을 날짜별로 묶어 중복일은 마지막 줄을 채택한 뒤 날짜순으로 반환합니다. 파일 자체에서 중복 줄을 삭제하지는 않습니다.

호출하는 코드: [PaperService.summary](#m6_tracking-paper-py-PaperService-summary-502), [PaperService.detail](#m6_tracking-paper-py-PaperService-detail-525).


<a id="m6_tracking-paper-py-PaperService-detail-525"></a>
#### `PaperService.detail`

<!-- source-symbol: m6_tracking/paper.py:525:PaperService.detail -->
[paper.py](../../backend/analysis/m6_tracking/paper.py#L525)

```python
def detail(self, paper_id: str) -> dict[str, Any]: ...
```

공개 모의투자 문서·요약·스냅샷·거래·차트 배열을 묶습니다. constraints_snapshot에서 원래 요청과 수수료만 공개하고 내부 intent는 제외합니다.

직접 연결: [PaperService._snapshots](#m6_tracking-paper-py-PaperService-_snapshots-519), [PaperService.summary](#m6_tracking-paper-py-PaperService-summary-502).

호출하는 코드: [PaperService.create](#m6_tracking-paper-py-PaperService-create-333), [PaperService.refresh](#m6_tracking-paper-py-PaperService-refresh-367), [PaperService.stop](#m6_tracking-paper-py-PaperService-stop-466).


<a id="m6_tracking-paper-py-PaperService-list-536"></a>
#### `PaperService.list`

<!-- source-symbol: m6_tracking/paper.py:536:PaperService.list -->
[paper.py](../../backend/analysis/m6_tracking/paper.py#L536)

```python
def list(self) -> list[dict[str, Any]]: ...
```

모의투자 문서를 생성 최신순으로 정렬하고 각 summary를 반환합니다. 자동 갱신을 수행하는 조회는 아닙니다.

직접 연결: [PaperService.summary](#m6_tracking-paper-py-PaperService-summary-502).

<details>
<summary>호출하는 코드</summary>

[PaperService._construct_weights](#m6_tracking-paper-py-PaperService-_construct_weights-231), [PaperService._plan](#m6_tracking-paper-py-PaperService-_plan-272), [PaperService.create](#m6_tracking-paper-py-PaperService-create-333), [PaperService._advance](#m6_tracking-paper-py-PaperService-_advance-380), [PaperService.resume](#m6_tracking-paper-py-PaperService-resume-476).

</details>


<a id="m6_tracking-paper-py-PaperService-refresh_all-539"></a>
#### `PaperService.refresh_all`

<!-- source-symbol: m6_tracking/paper.py:539:PaperService.refresh_all -->
[paper.py](../../backend/analysis/m6_tracking/paper.py#L539)

```python
def refresh_all(self) -> list[str]: ...
```

active 모의투자를 각각 갱신하고 처리 ID를 모읍니다. 한 건의 예외는 로그와 refresh_failed 이력으로 남기고 다른 건을 계속합니다. delayed를 정상 반환한 건도 처리 ID에 포함될 수 있습니다.

직접 연결: [PaperService.refresh](#m6_tracking-paper-py-PaperService-refresh-367), [_now](#m6_tracking-paper-py-_now-44).


<a id="m6_tracking-paper-py-refresh_all_papers-555"></a>
#### `refresh_all_papers`

<!-- source-symbol: m6_tracking/paper.py:555:refresh_all_papers -->
[paper.py](../../backend/analysis/m6_tracking/paper.py#L555)

```python
def refresh_all_papers(repo: Any, store: JsonStore, settings: AnalysisSettings, llm: Any=None) -> list[str]: ...
```

워커의 유휴 갱신용 진입점으로 새 MarketData·필요 LLM·PaperService를 만들어 active 전체를 갱신합니다.

직접 연결: [MarketData](m2_data_구현보고서.md#m2_data-market_data-py-MarketData-56), [PaperService](#m6_tracking-paper-py-PaperService-184), [make_llm](common_구현보고서.md#common-llm-py-make_llm-363).

호출하는 코드: [main](executor_구현보고서.md#executor-worker-py-main-112).


<a id="interactions"></a>
## 6. 다른 모듈과의 상호작용

[API](api_구현보고서.md)의 /paper 라우터와 [워커](executor_구현보고서.md)의 유휴 갱신이 서비스를 호출합니다. [M5](m5_backtest_report_구현보고서.md)에서 저장한 리포트·13_results를 읽어 원안 요청·의도·현재 구성을 고정합니다.

가격·환율·공통 거래일·품질 패널은 [M2](m2_data_구현보고서.md), 새 비중은 [M4](m4_portfolio_구현보고서.md)의 construct, 적립 날짜는 M5.backtest_engine.contribution_dates를 재사용합니다. 시작 이후 정기 리밸런싱 날짜는 이 모듈의 함수를 써 종료일 처리 차이를 둡니다.

영속화는 [공통 PaperStore](common_구현보고서.md)입니다. 단일 파일 교체는 JsonStore가 처리하지만 모의투자 한 건의 refresh 전체를 자동으로 잠그지는 않습니다. 결과 API의 파생 요약은 저장 스냅샷에서 계산합니다.

<a id="verification"></a>
## 7. 오류·제약과 검증 근거

preview와 create는 같은 계산 함수를 재호출하므로 자료·설정·LLM 결과가 바뀌면 계획이 달라질 수 있습니다. 저장된 미리보기 토큰으로 비중을 강제하는 구조는 아닙니다. 거래비용 때문에 목표 비중과 실제 체결 후 비중도 작은 차이가 날 수 있습니다.

동일 날짜 재처리를 피하는 정상 경로는 있지만 모의투자별 잠금이나 상태/거래/스냅샷 다중 파일 트랜잭션은 없습니다. 동시 refresh 또는 중간 프로세스 중단의 완전한 원자성을 보장하지 않습니다. 적립 처리는 백테스트와 달리 trade_to_target으로 기존 보유까지 조정될 수 있습니다.

중지 기간 스냅샷은 비지만 보유를 그대로 이어가므로 재개일 평가액에 그 사이 가격 변화가 반영될 수 있습니다. skipped 리밸런싱도 현재 n_rebalances 집계에 추가됩니다. schema_version의 일부 JSON Schema는 파일로 존재해도 append 경로에서 직접 검증하지 않습니다.

### 관련 테스트

아래는 테스트 소스에서 확인한 검증 시나리오입니다. 이번 문서 작성에서는 금융 DB·유료 LLM·시나리오 워커를 실행하지 않았으며, 테스트 통과를 새로 보증하는 기록으로 사용하지 않습니다.

- [test_paper.py](../../backend/tests/analysis/test_paper.py): 미리보기/등록·비용·적립·중복 날짜 방지·정기 조정·중지 공백·필수 자료 지연.
- [test_round5_validation.py](../../backend/tests/analysis/test_round5_validation.py): 정식 낙폭 맞춤 후보를 모의투자 전략으로 해석.

### 문서 검증

구문 분석 정의 목록과 대조하여 이 보고서의 클래스 2개와 함수/메서드 26개를 모두 설명했습니다. 상대경로 링크와 내부 앵커를 별도로 확인합니다.
