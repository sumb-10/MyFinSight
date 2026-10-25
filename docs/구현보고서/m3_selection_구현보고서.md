# m3_selection 구현보고서

[전체 안내](README.md)

> 작성 기준: 2026-10-25 작업 공간의 실제 소스. 기존 설계 문서는 배경 참고용이며 아래 동작 설명은 구현을 기준으로 합니다.

대상: Python 파일 6개 · 클래스 0개 · 함수/메서드 24개(중첩 함수와 비공개 보조 함수 포함).

[역할](#role) · [파일 구성](#files) · [처리 흐름](#flow) · [클래스](#classes) · [함수](#functions) · [모듈 연계](#interactions) · [오류·검증](#verification)

<a id="role"></a>
## 1. 모듈의 역할과 용어

`m3_selection`은 투자 아이디어를 테마 검색 조건으로 바꾸고 그 안에서 정량 지표로 종목을 고릅니다. 유니버스는 투자 가능한 모집단, 후보는 검색·필터를 통과한 목록, tagging은 LLM의 테마 관련성 분류, selection은 지표와 분산 선호를 반영한 최종 목록입니다.

LLM은 의도 해석·테마 판정·기업 설명을 맡고, 후보 검색·지표 계산·정렬·개수 선택은 코드가 담당합니다. `template`은 종목을 고르는 기준이고 `baseline_weighting`은 선정 후 자금을 나누는 방식이므로 서로 다른 개념입니다.

직접적인 주요 진입은 `interpret()` → `retrieve()` → `classify()` → `screen()` → `explain()`입니다. interpret는 확정 전 대화에서도 호출되고 나머지는 실행 단계로 연결됩니다.

<a id="files"></a>
## 2. 파일 구성과 책임

| 파일 | 책임 | 문서 내 해설 |
| --- | --- | --- |
| [m3_selection/__init__.py](../../backend/analysis/m3_selection/__init__.py) | 패키지 목적 설명; 독립 함수·클래스 정의 없음 | 정의 없음 |
| [m3_selection/classify.py](../../backend/analysis/m3_selection/classify.py) | 후보별 테마 판정 배치·정리·통과 집합 | [클래스 0 · 함수 5](#file-m3_selection-classify-py) |
| [m3_selection/explain.py](../../backend/analysis/m3_selection/explain.py) | 선정 근거 LLM 서술과 허용 인용 검사 | [클래스 0 · 함수 2](#file-m3_selection-explain-py) |
| [m3_selection/intent.py](../../backend/analysis/m3_selection/intent.py) | LLM 의도 해석과 요청 기준값 강제 | [클래스 0 · 함수 7](#file-m3_selection-intent-py) |
| [m3_selection/retrieve.py](../../backend/analysis/m3_selection/retrieve.py) | 사전 후보 검색·제외/가격 필터·주식 클래스 정리·상한 | [클래스 0 · 함수 5](#file-m3_selection-retrieve-py) |
| [m3_selection/screen.py](../../backend/analysis/m3_selection/screen.py) | 지표 순위·필수 포함·섹터 선호·배분 용량 | [클래스 0 · 함수 5](#file-m3_selection-screen-py) |

<a id="flow"></a>
## 3. 처리 흐름과 예시

| 단계 | 책임 주체 | 입력 → 출력 |
| --- | --- | --- |
| 02 interpret | LLM 해석 + 코드 확정 | 요청·GICS 트리 → IntentSpec |
| 03 retrieve | 코드 | 사전·테마·제약·시장 view → Candidates |
| 04 classify | LLM 판정 + 코드 검사 | 후보 40개 단위 → Tagging |
| 05 screen | 코드 | 통과 후보·지표·제약 → Selection + Fact |
| 06 explain | LLM 서술 + 인용 검사 | 선정 결과·Fact·뉴스/공시 → 기업 설명 |

예를 들어 'AI 반도체' 아이디어는 GICS 코드·GPU/메모리 등의 키워드·예시 티커로 바뀝니다. 산업 매칭·서로 다른 키워드 둘 이상·예시 티커 등의 검색 흔적을 남긴 뒤 제외·가격 이력·유동성 필터를 거칩니다. 테마 범위가 좁아 후보가 부족하면 산업 코드를 한 단계 넓혀 다시 찾습니다.

| 선정 템플릿 | 실제 지표 | 방향 |
| --- | --- | --- |
| momentum | return_12m_1m | 높은 순 |
| low_volatility | vol_60d | 낮은 순 |
| low_per | pe_ttm, 양수만 | 낮은 순 |
| quality | roe_ttm | 높은 순 |
| high_dividend | dividend_yield_ttm | 높은 순 |

넓은 테마(기본 6개 이상 섹터 또는 코드 없음)에서 후보가 120개를 넘으면 지표 순으로 미리 자릅니다. 좁은 테마는 필수 포함·매칭 규칙 수·유동성 우선입니다. 이 후보 절단은 LLM 분류 전에 일어나므로 모든 유니버스를 분류한 뒤 최종 순위를 정하는 방식과 다릅니다.

정량 선정은 섹터별 선호 개수를 먼저 지키되 목표를 채우기 위해 보류 후보를 다시 넣을 수 있습니다. 최종 비중의 섹터 상한은 M4가 처리합니다. 필수 포함은 테마/지표 조건에 맞지 않아도 경고와 함께 남을 수 있고 자료 품질·사전 부재까지 무조건 우회하는 권리는 아닙니다.

기업 설명은 이미 정한 종목·숫자를 근거로 작성합니다. 실제 지표값과 이 날짜의 fin ID를 제공하므로 단순한 LLM의 기억에 기대지 않습니다. 설명의 실존 인용 검사는 의미적 인과관계 검증과는 별개입니다.

### 연관 리소스

| 파일 | 계약·용도 |
| --- | --- |
| [prompts/02_intent/system_prompt.md](../../backend/analysis/prompts/02_intent/system_prompt.md) | 고정 시스템 지침(로더는 치환하지 않음); 자리표시자: `max_questions` |
| [prompts/02_intent/user_prompt.md](../../backend/analysis/prompts/02_intent/user_prompt.md) | 사용자 입력 템플릿; 자리표시자: `as_of`, `asked_fields`, `context`, `dialog_history`, `gics_tree`, `initial_amount_usd`, `max_questions`, `user_request_jsonc` |
| [prompts/04_classify/system_prompt.md](../../backend/analysis/prompts/04_classify/system_prompt.md) | 고정 시스템 지침(로더는 치환하지 않음); 자리표시자 없음 |
| [prompts/04_classify/user_prompt.md](../../backend/analysis/prompts/04_classify/user_prompt.md) | 사용자 입력 템플릿; 자리표시자: `batch_index`, `batch_size`, `batch_total`, `candidates_block`, `exclude_block`, `themes_block` |
| [prompts/06_explain/system_prompt.md](../../backend/analysis/prompts/06_explain/system_prompt.md) | 고정 시스템 지침(로더는 치환하지 않음); 자리표시자 없음 |
| [prompts/06_explain/user_prompt.md](../../backend/analysis/prompts/06_explain/user_prompt.md) | 사용자 입력 템플릿; 자리표시자: `as_of`, `direction`, `explanation_level`, `metric`, `selected_block`, `summary_ko`, `warnings_block` |

<a id="classes"></a>
## 4. 클래스 상세

필드 표는 해당 클래스에서 직접 선언한 필드입니다. 상속 필드는 부모 클래스 설명을 함께 읽습니다. `Field(...)`의 범위는 선언된 검증이며, 서비스에서 추가하는 조건은 함수 설명에 구분합니다.

이 모듈은 직접 정의한 클래스 없이 함수로 구성됩니다. 입력 모델은 schemas, 자료 객체는 M2, 실행 상태는 executor에서 가져옵니다.

<a id="functions"></a>
## 5. 함수·메서드 상세

시그니처에 입력 자료형·기본값·반환 자료형을 그대로 기재했습니다. `self`는 소속 클래스의 인스턴스, `cls`는 클래스입니다. 반환 주석이 없는 함수는 본문 해설의 반환 내용을 따릅니다. 속성(`property`)은 호출 괄호 없이 읽고, 중첩 함수는 바깥 함수의 지역 상태를 공유합니다. 연결 목록은 정적으로 확인되는 패키지 내부 직접 호출이며, 주입된 서비스·콜백·Repository 호출은 처리 흐름과 해설에서 설명합니다.


<a id="file-m3_selection-classify-py"></a>
### m3_selection/classify.py


<a id="m3_selection-classify-py-_themes_block-18"></a>
#### `_themes_block`

<!-- source-symbol: m3_selection/classify.py:18:_themes_block -->
[classify.py](../../backend/analysis/m3_selection/classify.py#L18)

```python
def _themes_block(themes: list[dict[str, Any]]) -> str: ...
```

테마 ID·한국어 이름·설명을 분류 프롬프트용 Markdown 목록으로 변환합니다.

호출하는 코드: [classify._one](#m3_selection-classify-py-classify-_one-43).


<a id="m3_selection-classify-py-_exclude_block-22"></a>
#### `_exclude_block`

<!-- source-symbol: m3_selection/classify.py:22:_exclude_block -->
[classify.py](../../backend/analysis/m3_selection/classify.py#L22)

```python
def _exclude_block(rules: list[dict[str, Any]]) -> str: ...
```

제외 테마와 키워드를 프롬프트 목록으로 만들고 없으면 없음 한 줄을 반환합니다.

호출하는 코드: [classify._one](#m3_selection-classify-py-classify-_one-43).


<a id="m3_selection-classify-py-_check-26"></a>
#### `_check`

<!-- source-symbol: m3_selection/classify.py:26:_check -->
[classify.py](../../backend/analysis/m3_selection/classify.py#L26)

```python
def _check(a: dict[str, Any]) -> None: ...
```

분류 응답의 results가 목록인지 검사합니다. 개별 TagResult 자료형 검증은 배치 응답을 합친 뒤 수행합니다.

명시적으로 발생시키는 예외: `ValueError`. 발생 조건은 위 해설과 소스의 분기를 함께 확인합니다.


<a id="m3_selection-classify-py-classify-31"></a>
#### `classify`

<!-- source-symbol: m3_selection/classify.py:31:classify -->
[classify.py](../../backend/analysis/m3_selection/classify.py#L31)

```python
def classify(cand: Candidates, intent: IntentSpec | dict[str, Any], llm: LlmClient, *, batch_size: int=BATCH, max_workers: int=1, cancel_check: Callable[[], bool] | None=None) -> Tagging: ...
```

후보를 기본 40개 배치로 나누고 순서를 보존하는 병렬 호출기로 LLM 분류를 수행합니다. 누락 후보는 미해당·신뢰도 0으로 보완하고 신뢰도를 0~1로 제한합니다. 모르는 테마 ID를 제거하고 제외 테마·최저 신뢰도·필수 포함 규칙으로 통과 티커를 만들어 Tagging을 반환합니다. excluded_theme가 지정된 항목은 필수 포함 여부와 별개로 제외 목록에 들어갑니다.

직접 연결: [map_ordered](executor_구현보고서.md#executor-parallel-py-map_ordered-24), [Tagging](schemas_구현보고서.md#schemas-selection-py-Tagging-63).

호출하는 코드: [st_tagging](executor_구현보고서.md#executor-stages-py-st_tagging-95).


<a id="m3_selection-classify-py-classify-_one-43"></a>
#### `classify._one`

<!-- source-symbol: m3_selection/classify.py:43:classify._one -->
[classify.py](../../backend/analysis/m3_selection/classify.py#L43)

```python
def _one(item: tuple[int, list[Any]]) -> tuple[dict[str, dict[str, Any]], list[str]]: ...
```

배치 번호와 후보 목록을 받아 프롬프트를 만들고 LLM 응답을 요청 배치의 티커로 제한합니다. 응답 누락을 기본 미통과 항목으로 채운 티커 사전과 경고를 반환합니다. 여러 배치의 결과는 바깥 함수에서 입력 순서대로 조립합니다.

직접 연결: [load_prompts](common_구현보고서.md#common-prompts-py-load_prompts-17), [_themes_block](#m3_selection-classify-py-_themes_block-18), [_exclude_block](#m3_selection-classify-py-_exclude_block-22), [messages_from_prompts](common_구현보고서.md#common-llm-py-messages_from_prompts-54).


<a id="file-m3_selection-explain-py"></a>
### m3_selection/explain.py


<a id="m3_selection-explain-py-explain-21"></a>
#### `explain`

<!-- source-symbol: m3_selection/explain.py:21:explain -->
[explain.py](../../backend/analysis/m3_selection/explain.py#L21)

```python
def explain(sel: Selection, tagging: Tagging, intent: IntentSpec | dict[str, Any], llm: LlmClient, *, facts: list[dict[str, Any]], news: EvidenceWindow | None=None, warnings_ko: list[str] | None=None) -> dict[str, Any]: ...
```

선정 표·분류 이유·금융 Fact·뉴스·공시와 한국어 공지를 프롬프트에 담아 기업별 근거를 받습니다. 허용 티커·인용 ID 검증기를 LLM 호출기에 전달하고 단계명·사용 가능 ID를 붙인 설명 사전을 반환합니다. 설명용 LLM이 선정 지표나 최종 목록을 바꾸지는 않습니다.

직접 연결: [load_prompts](common_구현보고서.md#common-prompts-py-load_prompts-17), [messages_from_prompts](common_구현보고서.md#common-llm-py-messages_from_prompts-54).

호출하는 코드: [st_explain](executor_구현보고서.md#executor-stages-py-st_explain-115).


<a id="m3_selection-explain-py-explain-_check-59"></a>
#### `explain._check`

<!-- source-symbol: m3_selection/explain.py:59:explain._check -->
[explain.py](../../backend/analysis/m3_selection/explain.py#L59)

```python
def _check(a: dict[str, Any]) -> None: ...
```

전체 요약과 per_ticker 목록을 확인하고 각 티커가 선정 목록 안인지 검사합니다. 근거가 있으면 최소 한 인용을 요구하고 미등록 ID를 거부합니다. 각 기업별 인용이 반드시 그 기업의 Fact인지, 모든 선정 종목이 응답에 있는지까지 검사하는 것은 아닙니다.

명시적으로 발생시키는 예외: `ValueError`. 발생 조건은 위 해설과 소스의 분기를 함께 확인합니다.


<a id="file-m3_selection-intent-py"></a>
### m3_selection/intent.py


<a id="m3_selection-intent-py-field_tags-44"></a>
#### `field_tags`

<!-- source-symbol: m3_selection/intent.py:44:field_tags -->
[intent.py](../../backend/analysis/m3_selection/intent.py#L44)

```python
def field_tags(explicit_fields: Sequence[str]=()) -> dict[str, str]: ...
```

필드를 HARD·SOFT·프로필 기본값으로 구분한 프롬프트용 사전을 만듭니다. 이번 요청의 명시 경로와 상하위 경로가 겹치면 HARD(이번 입력)으로 표시합니다.

직접 연결: [field_tags.is_explicit](#m3_selection-intent-py-field_tags-is_explicit-48).

호출하는 코드: [request_text](#m3_selection-intent-py-request_text-59).


<a id="m3_selection-intent-py-field_tags-is_explicit-48"></a>
#### `field_tags.is_explicit`

<!-- source-symbol: m3_selection/intent.py:48:field_tags.is_explicit -->
[intent.py](../../backend/analysis/m3_selection/intent.py#L48)

```python
def is_explicit(f: str) -> bool: ...
```

현재 필드와 explicit_fields가 같은 경로이거나 상위·하위 관계이면 True입니다. 바깥 함수가 만든 exp 집합을 참조합니다.

호출하는 코드: [field_tags](#m3_selection-intent-py-field_tags-44).


<a id="m3_selection-intent-py-request_text-59"></a>
#### `request_text`

<!-- source-symbol: m3_selection/intent.py:59:request_text -->
[intent.py](../../backend/analysis/m3_selection/intent.py#L59)

```python
def request_text(req: dict[str, Any], explicit_fields: Sequence[str]=()) -> str: ...
```

분석 요청의 주요 일곱 블록을 필드 태그 범례와 JSON으로 묶어 반환합니다. 실행 ID·파생 자료 전체는 이 본문에 복사하지 않습니다.

직접 연결: [field_tags](#m3_selection-intent-py-field_tags-44).

호출하는 코드: [build_messages](#m3_selection-intent-py-build_messages-66).


<a id="m3_selection-intent-py-build_messages-66"></a>
#### `build_messages`

<!-- source-symbol: m3_selection/intent.py:66:build_messages -->
[intent.py](../../backend/analysis/m3_selection/intent.py#L66)

```python
def build_messages(req: dict[str, Any], desc: Descriptor, *, as_of: str, initial_amount_usd: float, context: str='', dialog_history: str='', max_questions: int=5, asked_fields: Sequence[str]=(), explicit_fields: Sequence[str]=()) -> list[Message]: ...
```

요청 조건·기준일·USD 자본·GICS 트리·과거 실행 요약·질문 이력을 02_intent 프롬프트에 채워 system/user 메시지 쌍을 반환합니다.

직접 연결: [load_prompts](common_구현보고서.md#common-prompts-py-load_prompts-17), [request_text](#m3_selection-intent-py-request_text-59), [render_tree](m2_data_구현보고서.md#m2_data-descriptor-py-render_tree-78).

호출하는 코드: [DialogService._turn](m1_request_구현보고서.md#m1_request-dialog-py-DialogService-_turn-275), [interpret](#m3_selection-intent-py-interpret-104).


<a id="m3_selection-intent-py-effective_max_drawdown-82"></a>
#### `effective_max_drawdown`

<!-- source-symbol: m3_selection/intent.py:82:effective_max_drawdown -->
[intent.py](../../backend/analysis/m3_selection/intent.py#L82)

```python
def effective_max_drawdown(req: dict[str, Any]) -> float: ...
```

입력 허용 낙폭에 손실 시 매도이면 0.8, 투자 경험 없음이면 0.9를 곱한 값을 반환합니다. 이 보정값은 낙폭 맞춤안의 목표이며 현재 검증 R1의 사용자 허용값은 원래 입력입니다.

호출하는 코드: [condition_rows](m1_request_구현보고서.md#m1_request-conditions-py-condition_rows-65), [interpret](#m3_selection-intent-py-interpret-104).


<a id="m3_selection-intent-py-_check-93"></a>
#### `_check`

<!-- source-symbol: m3_selection/intent.py:93:_check -->
[intent.py](../../backend/analysis/m3_selection/intent.py#L93)

```python
def _check(ans: dict[str, Any]) -> None: ...
```

LLM 응답의 테마 목록과 screen·risk_params·news_tilt·validation_criteria·report_settings 존재를 검사합니다. questions가 있으면 목록이어야 합니다. 전체 스키마 검증은 이후 IntentSpec 생성 시 수행됩니다.

명시적으로 발생시키는 예외: `ValueError`. 발생 조건은 위 해설과 소스의 분기를 함께 확인합니다.


<a id="m3_selection-intent-py-interpret-104"></a>
#### `interpret`

<!-- source-symbol: m3_selection/intent.py:104:interpret -->
[intent.py](../../backend/analysis/m3_selection/intent.py#L104)

```python
def interpret(req: dict[str, Any], desc: Descriptor, llm: LlmClient, settings: AnalysisSettings, *, messages: Sequence[Message] | None=None, context: str='', dialog_history: str='', asked_fields: Sequence[str]=()) -> tuple[IntentSpec, list[str], list[Message]]: ...
```

주어진 누적 대화 또는 새 프롬프트로 의도 JSON을 받습니다. 사전에 없는 산업 코드·예시 티커를 제거하고 선정 지표·방향·종목 수·기준일·뉴스 켜짐·허용 낙폭·목표수익·비교지수는 코드가 요청값으로 덮어씁니다. 질문 보기 형태를 정리하고 IntentSpec·경고·사용 메시지를 반환합니다. 최종 모델 검증은 complete_json 호출 뒤에 있어 그 실패가 항상 호출기 내부 내용 재시도로 연결되는 것은 아닙니다.

직접 연결: [build_messages](#m3_selection-intent-py-build_messages-66), [known_codes](m2_data_구현보고서.md#m2_data-descriptor-py-known_codes-124), [tickers](m2_data_구현보고서.md#m2_data-descriptor-py-tickers-128), [effective_max_drawdown](#m3_selection-intent-py-effective_max_drawdown-82).

호출하는 코드: [st_intent](executor_구현보고서.md#executor-stages-py-st_intent-67), [DialogService._turn](m1_request_구현보고서.md#m1_request-dialog-py-DialogService-_turn-275).


<a id="file-m3_selection-retrieve-py"></a>
### m3_selection/retrieve.py


<a id="m3_selection-retrieve-py-_collect-34"></a>
#### `_collect`

<!-- source-symbol: m3_selection/retrieve.py:34:_collect -->
[retrieve.py](../../backend/analysis/m3_selection/retrieve.py#L34)

```python
def _collect(desc: Descriptor, themes: list[dict[str, Any]]) -> dict[str, dict[str, set[str]]]: ...
```

각 테마의 GICS·키워드·예시 티커 검색 결과를 합쳐 티커별 매칭 규칙·테마·서로 다른 키워드 집합을 반환합니다. 한 회사가 여러 규칙에 걸려도 후보 키는 하나입니다.

호출하는 코드: [retrieve](#m3_selection-retrieve-py-retrieve-70).


<a id="m3_selection-retrieve-py-_share_class_key-58"></a>
#### `_share_class_key`

<!-- source-symbol: m3_selection/retrieve.py:58:_share_class_key -->
[retrieve.py](../../backend/analysis/m3_selection/retrieve.py#L58)

```python
def _share_class_key(entry: dict[str, Any]) -> str: ...
```

회사명에서 괄호·문장부호·Class/Series·법인 접미사를 제거해 복수 주식 클래스를 묶을 키를 만듭니다. 이름 정규화 기반이므로 법적 동일회사 식별자를 조회하는 것은 아닙니다.

호출하는 코드: [retrieve](#m3_selection-retrieve-py-retrieve-70).


<a id="m3_selection-retrieve-py-retrieve-70"></a>
#### `retrieve`

<!-- source-symbol: m3_selection/retrieve.py:70:retrieve -->
[retrieve.py](../../backend/analysis/m3_selection/retrieve.py#L70)

```python
def retrieve(view: MarketDataView, desc: Descriptor, intent: IntentSpec | dict[str, Any], constraints: dict[str, Any], *, request_id: str, descriptor_version: str | None=None, max_candidates: int | None | object=_DEFAULT, broad_min_sectors: int=BROAD_THEME_MIN_SECTORS, metric_prefilter: bool=True) -> Candidates: ...
```

사전 검색 후보가 목표보다 적으면 GICS를 한 단계 넓히고 필수 티커를 추가합니다. 약한 단독 키워드·명시 제외·산업 제외·자료 이력·거래대금·시총 필터를 적용하고 같은 회사의 주식 클래스는 보통 거래대금이 큰 하나를 남깁니다. 후보 상한 초과 시 넓은 테마는 선정 지표 순, 좁은 테마는 필수 포함·매칭 규칙·유동성 순으로 자릅니다. Candidates에 제외 사유·집계·경고를 함께 반환합니다. 필수 포함은 여러 필터를 우회하지만 사전 바깥 티커는 강제로 생성하지 않습니다.

직접 연결: [_collect](#m3_selection-retrieve-py-_collect-34), [parents_of](m2_data_구현보고서.md#m2_data-descriptor-py-parents_of-119), [sector_name_to_code](m2_data_구현보고서.md#m2_data-descriptor-py-sector_name_to_code-108), [retrieve.drop](#m3_selection-retrieve-py-retrieve-drop-129), [code_of](m2_data_구현보고서.md#m2_data-descriptor-py-code_of-59), [Candidate](schemas_구현보고서.md#schemas-selection-py-Candidate-22), [gics_model](m2_data_구현보고서.md#m2_data-descriptor-py-gics_model-64), [_share_class_key](#m3_selection-retrieve-py-_share_class_key-58), [Candidates](schemas_구현보고서.md#schemas-selection-py-Candidates-43).

호출하는 코드: [st_candidates](executor_구현보고서.md#executor-stages-py-st_candidates-84), [_count_at](m1_request_구현보고서.md#m1_request-precheck-py-_count_at-39), [build_backtest_spec](m4_portfolio_구현보고서.md#m4_portfolio-spec-py-build_backtest_spec-37).


<a id="m3_selection-retrieve-py-retrieve-drop-129"></a>
#### `retrieve.drop`

<!-- source-symbol: m3_selection/retrieve.py:129:retrieve.drop -->
[retrieve.py](../../backend/analysis/m3_selection/retrieve.py#L129)

```python
def drop(t: str, reason: str) -> None: ...
```

후보의 제외 티커·사유를 기록하고 사유 종류별 집계를 제자리 증가시킵니다.

직접 연결: [FilteredOut](schemas_구현보고서.md#schemas-selection-py-FilteredOut-38).

<details>
<summary>호출하는 코드</summary>

[retrieve](#m3_selection-retrieve-py-retrieve-70).

</details>


<a id="m3_selection-retrieve-py-retrieve-mkey-223"></a>
#### `retrieve.mkey`

<!-- source-symbol: m3_selection/retrieve.py:223:retrieve.mkey -->
[retrieve.py](../../backend/analysis/m3_selection/retrieve.py#L223)

```python
def mkey(c: Candidate): ...
```

넓은 테마의 상한 절단용 키로 필수 포함·지표 존재·지표 방향·거래대금을 반환합니다. 내림차순 정렬에 맞추어 오름차순 지표는 부호를 반대로 사용합니다.


<a id="file-m3_selection-screen-py"></a>
### m3_selection/screen.py


<a id="m3_selection-screen-py-screen-22"></a>
#### `screen`

<!-- source-symbol: m3_selection/screen.py:22:screen -->
[screen.py](../../backend/analysis/m3_selection/screen.py#L22)

```python
def screen(view: MarketDataView, desc: Descriptor, tagging: Tagging, intent: IntentSpec | dict[str, Any], constraints: dict[str, Any], *, request_id: str) -> tuple[Selection, list[dict[str, Any]]]: ...
```

테마 통과 종목의 선정 지표를 계산하고 지표 없는 일반 후보를 제외합니다. 필수 종목을 먼저 두고 지표 순으로 섹터별 선호 종목 수를 적용한 뒤 부족분은 미뤄 둔 후보로 채웁니다. 실제 비중 상한은 Module4가 적용하며 여기서는 배분 가능 용량과 불충분 사유를 계산합니다. Selection과 선정 종목의 Fact 사전 목록을 반환합니다.

직접 연결: [Rejected](schemas_구현보고서.md#schemas-selection-py-Rejected-88), [screen.sector_of](#m3_selection-screen-py-screen-sector_of-71), [screen.is_forced](#m3_selection-screen-py-screen-is_forced-76), [screen.add](#m3_selection-screen-py-screen-add-85), [screen.capacity](#m3_selection-screen-py-screen-capacity-68), [Selection](schemas_구현보고서.md#schemas-selection-py-Selection-94).

호출하는 코드: [st_selection](executor_구현보고서.md#executor-stages-py-st_selection-103), [build_backtest_spec](m4_portfolio_구현보고서.md#m4_portfolio-spec-py-build_backtest_spec-37).


<a id="m3_selection-screen-py-screen-capacity-68"></a>
#### `screen.capacity`

<!-- source-symbol: m3_selection/screen.py:68:screen.capacity -->
[screen.py](../../backend/analysis/m3_selection/screen.py#L68)

```python
def capacity(counts: Counter) -> float: ...
```

섹터별 종목 수에 대해 min(종목 수×종목 상한, 섹터 상한)을 합산해 최대 투자 가능 비율을 반환합니다.

호출하는 코드: [screen](#m3_selection-screen-py-screen-22).


<a id="m3_selection-screen-py-screen-sector_of-71"></a>
#### `screen.sector_of`

<!-- source-symbol: m3_selection/screen.py:71:screen.sector_of -->
[screen.py](../../backend/analysis/m3_selection/screen.py#L71)

```python
def sector_of(t: str) -> tuple[str, str]: ...
```

티커 사전 항목의 섹터 코드·이름을 반환하고 항목이 없으면 빈 문자열 쌍을 반환합니다.

직접 연결: [gics_model](m2_data_구현보고서.md#m2_data-descriptor-py-gics_model-64).

호출하는 코드: [screen](#m3_selection-screen-py-screen-22), [screen.add](#m3_selection-screen-py-screen-add-85).


<a id="m3_selection-screen-py-screen-is_forced-76"></a>
#### `screen.is_forced`

<!-- source-symbol: m3_selection/screen.py:76:screen.is_forced -->
[screen.py](../../backend/analysis/m3_selection/screen.py#L76)

```python
def is_forced(t: str) -> bool: ...
```

티커의 대문자 표기가 요청 must_include 집합에 들어 있는지 반환합니다.

호출하는 코드: [screen](#m3_selection-screen-py-screen-22), [screen.add](#m3_selection-screen-py-screen-add-85).


<a id="m3_selection-screen-py-screen-add-85"></a>
#### `screen.add`

<!-- source-symbol: m3_selection/screen.py:85:screen.add -->
[screen.py](../../backend/analysis/m3_selection/screen.py#L85)

```python
def add(t: str, v: float) -> None: ...
```

선정 순위·섹터·시장·지표·근거 ID·테마 신뢰도·강제 포함 여부를 담은 Selected를 추가하고 섹터별 종목 수를 갱신합니다.

직접 연결: [screen.sector_of](#m3_selection-screen-py-screen-sector_of-71), [Selected](schemas_구현보고서.md#schemas-selection-py-Selected-74), [screen.is_forced](#m3_selection-screen-py-screen-is_forced-76).

호출하는 코드: [screen](#m3_selection-screen-py-screen-22).


<a id="interactions"></a>
## 6. 다른 모듈과의 상호작용

[M1](m1_request_구현보고서.md)이 확정 전 interpret를 호출하며 [실행기](executor_구현보고서.md)의 02~06 Stage가 본 분석을 조율합니다. 같은 의도를 실행에서 재사용하면 02 LLM 재호출은 없습니다.

검색 사전·시장 view·METRICS·Fact·EvidenceWindow는 [M2](m2_data_구현보고서.md), 프롬프트·LLM·순서 유지 병렬 함수는 공통/실행기가 제공합니다. 후보→분류→선정의 모델은 [schemas](schemas_구현보고서.md)입니다.

[M4](m4_portfolio_구현보고서.md)의 과거 시작일 재선정은 retrieve·screen을 다시 쓰고 현재 tagging 통과 집합과 교집합합니다. [M5](m5_backtest_report_구현보고서.md)는 선정 표·설명·Fact를 통합하여 현재/과거 차이와 기업별 근거를 렌더링합니다.

<a id="verification"></a>
## 7. 오류·제약과 검증 근거

분류 누락은 미통과로 처리하지만 실제 관련성은 LLM 판단에 의존합니다. 이 해석·분류는 완전한 과거 시점 모델 재현이 아니며 04 프롬프트는 알려진 회사 지식 사용도 허용합니다. 후보 상한·키워드·이름 기반 주식 클래스 중복 제거는 검색 휴리스틱입니다.

상한 용량 부족 시 현금이 남을 수 있고, 최소 개수 부족이 항상 단계 실패는 아닙니다. 다만 선정이 0개면 실행기에서 실패하고 M4 추정은 최소 2종목을 요구합니다. 설명의 인용 실존 검사가 그 문장의 모든 의미를 사실 검증한다는 뜻은 아닙니다. 일부 최종 모델 검증은 LLM 호출기 validator 바깥에서 수행됩니다.

### 관련 테스트

아래는 테스트 소스에서 확인한 검증 시나리오입니다. 이번 문서 작성에서는 금융 DB·유료 LLM·시나리오 워커를 실행하지 않았으며, 테스트 통과를 새로 보증하는 기록으로 사용하지 않습니다.

- [test_round5_selection.py](../../backend/tests/analysis/test_round5_selection.py): 넓은 테마에서 후보 상한을 실제 선정 지표 순으로 적용.
- [test_pipeline_e2e.py](../../backend/tests/analysis/test_pipeline_e2e.py): 혼합 시장 선정·복수 주식 클래스·Fact와 기업 설명의 연결.
- [test_foundations.py](../../backend/tests/analysis/test_foundations.py): 괄호가 있는 주식 클래스의 동일회사 키.

### 문서 검증

구문 분석 정의 목록과 대조하여 이 보고서의 클래스 0개와 함수/메서드 24개를 모두 설명했습니다. 상대경로 링크와 내부 앵커를 별도로 확인합니다.
