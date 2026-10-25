# common 구현보고서

[전체 안내](README.md)

> 작성 기준: 2026-10-25 작업 공간의 실제 소스. 기존 설계 문서는 배경 참고용이며 아래 동작 설명은 구현을 기준으로 합니다.

대상: Python 파일 13개 · 클래스 36개 · 함수/메서드 105개(중첩 함수와 비공개 보조 함수 포함).

[역할](#role) · [파일 구성](#files) · [처리 흐름](#flow) · [클래스](#classes) · [함수](#functions) · [모듈 연계](#interactions) · [오류·검증](#verification)

<a id="role"></a>
## 1. 모듈의 역할과 용어

`common`은 여러 업무 모듈이 공유하는 입출력·LLM·경고·인용 기능입니다. 이 보고서는 패키지 루트의 `settings.py`, `paths.py`, `errors.py`, `__init__.py`도 포함하여 실행 기반을 한 곳에서 설명합니다.

Repository는 DB 종류를 숨기는 읽기/쓰기 인터페이스입니다. JsonStore는 DB에 없는 사용자 상태를 파일로 저장합니다. LLM은 자연어를 해석하거나 설명을 쓰는 호출기이고, stub은 네트워크 없이 테스트 응답을 만드는 대체 구현입니다. 금융 계산과 실제 조건 변경은 각 업무 모듈의 코드가 담당합니다.

대표 진입점은 `AnalysisSettings.load()`, `open_analysis_repository()`, `JsonStore()`, `make_llm()`입니다. 기본값과 운영 환경변수 적용값을 구분해야 합니다. 예를 들어 LlmSettings의 기본은 stub이지만 load는 API 키가 있으면 api를 선택할 수 있습니다.

<a id="files"></a>
## 2. 파일 구성과 책임

| 파일 | 책임 | 문서 내 해설 |
| --- | --- | --- |
| [__init__.py](../../backend/analysis/__init__.py) | 패키지의 모듈 대응과 책임 설명 | 정의 없음 |
| [common/__init__.py](../../backend/analysis/common/__init__.py) | 패키지 목적 설명; 독립 함수·클래스 정의 없음 | 정의 없음 |
| [common/citations.py](../../backend/analysis/common/citations.py) | 인용 정규식·접두사별 종류 | [클래스 0 · 함수 1](#file-common-citations-py) |
| [common/dbconn.py](../../backend/analysis/common/dbconn.py) | 시장 읽기/결과 쓰기 DB 연결·메서드 위임 | [클래스 1 · 함수 11](#file-common-dbconn-py) |
| [common/jsonio.py](../../backend/analysis/common/jsonio.py) | JSON/JSONC·정규 직렬화·해시·시각 | [클래스 0 · 함수 7](#file-common-jsonio-py) |
| [common/llm.py](../../backend/analysis/common/llm.py) | Protocol·stub·실제 LLM·캐시·재시도·사용량 | [클래스 4 · 함수 19](#file-common-llm-py) |
| [common/prompts.py](../../backend/analysis/common/prompts.py) | 프롬프트 파일 읽기·사용자 템플릿 치환 | [클래스 0 · 함수 2](#file-common-prompts-py) |
| [common/store.py](../../backend/analysis/common/store.py) | 프로필·요청·실행·모의투자·비교의 파일 저장과 잠금 | [클래스 6 · 함수 42](#file-common-store-py) |
| [common/stub_answers.py](../../backend/analysis/common/stub_answers.py) | 프롬프트 입력에 맞춘 개발용 규칙 응답 | [클래스 0 · 함수 9](#file-common-stub_answers-py) |
| [common/warnings.py](../../backend/analysis/common/warnings.py) | 경고 코드·등급·레거시 파싱·병합·표시 | [클래스 1 · 함수 7](#file-common-warnings-py) |
| [errors.py](../../backend/analysis/errors.py) | 업무 예외와 안정된 오류 코드 | [클래스 12 · 함수 0](#errors-py-RequestInvalid-11) |
| [paths.py](../../backend/analysis/paths.py) | 저장소·산출물·프롬프트·사전 경로 | [클래스 0 · 함수 4](#file-paths-py) |
| [settings.py](../../backend/analysis/settings.py) | 하위 설정 기본값·환경 적용·실행 스냅샷 | [클래스 12 · 함수 3](#file-settings-py) |

<a id="flow"></a>
## 3. 처리 흐름과 예시

설정은 기본 dataclass → 환경변수 → 명시 overrides 순으로 결정합니다. 경로 설정은 `paths.py`가 `os.environ`을 직접 읽고, 분석 설정·DB 설정은 수집기와 공유하는 `config.get`을 사용합니다. 두 경로의 환경 읽기 방식이 같다고 가정하지 않습니다.

| 저장 계층 | 기본 위치·대상 | 주요 내용 |
| --- | --- | --- |
| 시장 Repository | 환경의 팀 DB 또는 backend.db 기본값 | 가격·환율·가치평가·뉴스·공시·종목 |
| 결과 Repository | 명시 외부 시장 DB이면 기본 로컬 SQLite `data/analysis_results.db` | run_step·run_artifact·report |
| JsonStore | `data/analysis_store` | profile.json·requests·runs.json·paper·comparisons |
| 실행 디렉터리 | `output/<run_id>` | 단계 JSON·run_meta·프롬프트·LLM 원문·일별 Parquet |
| 공용 LLM 캐시 | `output/llm_cache` | 모델·단계·전체 대화의 해시별 응답 |

예를 들어 프로필 저장은 profile 잠금 → 버전 추가 → 스키마 검사 → 임시 파일 쓰기 → 원자 교체 순입니다. `JsonStore.write()`의 원자 교체와 `locked()`의 읽기-수정-쓰기 직렬화는 다른 기능입니다. JSONL 추가는 기본적으로 별도 잠금이나 검증을 수행하지 않습니다.

LLM 실제 경로는 프롬프트 저장 → 캐시 확인 → 실제 요청/전송 재시도 → 원문·사용량·캐시 저장 → 도메인 validator → 필요 시 오류 메시지를 추가한 내용 보정 1회입니다. 같은 입력을 캐시로 재사용할 수 있지만 모델·단계·대화 외 설정 변경이 모두 캐시 키에 반영되는 것은 아닙니다.

인용은 뉴스 `[ev123]`, 공시 `[dc45]`, 금융 지표 `[fin:US-AAPL:pe_ttm:2026-10-01]`, 계산값 `[calc:cagr:equal_weight]`로 구분합니다. ID의 형식·실존·종목/시점 검사는 각각 정규식·근거 색인·업무 검증에 나뉩니다.

경고는 `user`(행동·확인 필요), `info`(참고), `debug`(개발 원문)로 구분합니다. 단계의 user 경고는 PARTIAL을 만들고, 결과 파일은 전 등급을 보존하며 리포트 notices는 user만 노출합니다. 과거 경고 카탈로그에 남은 코드가 현재 매 실행에서 발생하는 것은 아닙니다.

### 연관 리소스

| 파일 | 계약·용도 |
| --- | --- |
| [common/store_schemas/analysis_request.schema.json](../../backend/analysis/common/store_schemas/analysis_request.schema.json) | 계약 파일 존재; RequestStore.save는 Pydantic AnalysisRequestDoc 사용; 필수 루트 키: `request_id`, `created_at`, `profile_version`, `idea` |
| [common/store_schemas/paper_portfolio.schema.json](../../backend/analysis/common/store_schemas/paper_portfolio.schema.json) | PaperStore.save가 JSON Schema 적용; 필수 루트 키: `schema_version`, `paper_id`, `report_id`, `run_id`, `strategy_id`, `name_ko`, `start_date`, `initial_capital`, `contribution`, `rebalance_rule`, `constraints_snapshot`, `tickers`, `start_weights`, `state`, `status`, `created_at` |
| [common/store_schemas/paper_snapshot.schema.json](../../backend/analysis/common/store_schemas/paper_snapshot.schema.json) | 계약 파일 존재; append_snapshot 경로는 직접 검증하지 않음; 필수 루트 키: `date`, `value_usd`, `cash_usd`, `weights`, `drawdown`, `return_since_start`, `status` |
| [common/store_schemas/profile.schema.json](../../backend/analysis/common/store_schemas/profile.schema.json) | ProfileStore.save가 JSON Schema 적용; 필수 루트 키: `schema_version`, `profile_id`, `current_version`, `versions` |
| [common/store_schemas/rebalance_record.schema.json](../../backend/analysis/common/store_schemas/rebalance_record.schema.json) | 계약 파일 존재; append_rebalance 경로는 직접 검증하지 않음; 필수 루트 키: `date`, `seq`, `before_weights`, `target_weights`, `applied_weights`, `trades`, `commission_usd`, `turnover`, `fallback`, `skipped` |
| [common/store_schemas/revision_comparison.schema.json](../../backend/analysis/common/store_schemas/revision_comparison.schema.json) | 계약 파일 존재; ComparisonStore.save는 schema 인자를 전달하지 않음; 필수 루트 키: `schema_version`, `comparison_id`, `base_run_id`, `revised_run_id`, `base_report_id`, `revised_report_id`, `created_at`, `same_window`, `condition_changes`, `ticker_changes`, `weight_changes`, `rule_changes`, `performance_table` |
| [common/store_schemas/run_index.schema.json](../../backend/analysis/common/store_schemas/run_index.schema.json) | 계약 파일 존재; RunIndex는 행을 Pydantic으로 읽고 JSON 쓰기에 이 스키마를 전달하지 않음; 필수 루트 키: `schema_version`, `runs` |
| [stubs/02_intent.example.json](../../backend/analysis/stubs/02_intent.example.json) | 고정 stub 예시; 루트 키: `request_id`, `spec_version`, `interpretation`, `exclude_theme_rules`, `screen`, `risk_params`, `news_tilt`, `validation_criteria`, `report_settings` |
| [stubs/04_classify.example.json](../../backend/analysis/stubs/04_classify.example.json) | 고정 stub 예시; 루트 키: `results` |
| [stubs/09_views.example.json](../../backend/analysis/stubs/09_views.example.json) | 고정 stub 예시; 루트 키: `sets` |
| [stubs/14a_interpret.example.json](../../backend/analysis/stubs/14a_interpret.example.json) | 고정 stub 예시; 루트 키: `performance_ko`, `risk_fit_ko`, `validation_ko`, `view_review_ko`, `next_actions_ko`, `assessment` |
| [stubs/14b_narrate.example.json](../../backend/analysis/stubs/14b_narrate.example.json) | 고정 stub 예시; 루트 키: `overview_ko`, `request_interpretation_ko`, `selection_ko`, `construction_ko`, `assumptions_ko`, `reconsideration_ko`, `glossary` |

stub은 입력 의존적인 단계에서 SMART_STUBS를 기본 우선합니다. `09_views.example.json`은 현재 `09_views_news` 키와 파일명이 같지 않습니다. 스마트 구현이 없는 일반 키는 대응 파일이 필요하고, 응답 예시는 임의 요청에 대한 유효한 응답을 항상 보장하지 않습니다.

<a id="classes"></a>
## 4. 클래스 상세

필드 표는 해당 클래스에서 직접 선언한 필드입니다. 상속 필드는 부모 클래스 설명을 함께 읽습니다. `Field(...)`의 범위는 선언된 검증이며, 서비스에서 추가하는 조건은 함수 설명에 구분합니다.

<a id="common-dbconn-py-SplitRepository-52"></a>
### `SplitRepository`

<!-- source-symbol: common/dbconn.py:52:SplitRepository -->
[dbconn.py](../../backend/analysis/common/dbconn.py#L52)

읽기용 시장 DB와 쓰기용 결과 DB를 하나의 Repository처럼 노출합니다. _market과 _results에 실제 객체를 보관하고 정해진 메서드 이름만 결과 쪽으로 분기합니다. 두 DB 사이의 분산 트랜잭션을 제공하지는 않습니다.

기반: `명시적 부모 없음`.

메서드·속성: [__init__](#common-dbconn-py-SplitRepository-__init__-55), [market](#common-dbconn-py-SplitRepository-market-60), [results](#common-dbconn-py-SplitRepository-results-64), [__getattr__](#common-dbconn-py-SplitRepository-__getattr__-67), [__repr__](#common-dbconn-py-SplitRepository-__repr__-71).


<a id="common-llm-py-LlmClient-40"></a>
### `LlmClient`

<!-- source-symbol: common/llm.py:40:LlmClient -->
[llm.py](../../backend/analysis/common/llm.py#L40)

전체 분석 코드가 의존하는 LLM Protocol입니다. JSON 객체 응답과 사용량 요약만 계약으로 노출하여 실제 API와 개발 stub을 바꿔 끼울 수 있습니다.

기반: `Protocol`.

메서드·속성: [complete_json](#common-llm-py-LlmClient-complete_json-41), [usage_summary](#common-llm-py-LlmClient-usage_summary-51).


<a id="common-llm-py-_Base-67"></a>
### `_Base`

<!-- source-symbol: common/llm.py:67:_Base -->
[llm.py](../../backend/analysis/common/llm.py#L67)

LLM 구현의 공통 기반입니다. 선택 run_dir과 calls 목록을 보관하며 프롬프트 파일 저장·사용량 합계를 제공합니다.

기반: `명시적 부모 없음`.

메서드·속성: [__init__](#common-llm-py-_Base-__init__-70), [_save_prompt](#common-llm-py-_Base-_save_prompt-74), [usage_summary](#common-llm-py-_Base-usage_summary-85).


<a id="common-llm-py-StubLlm-98"></a>
### `StubLlm`

<!-- source-symbol: common/llm.py:98:StubLlm -->
[llm.py](../../backend/analysis/common/llm.py#L98)

네트워크 없이 주입 객체·순서형 응답·저장 파일·프롬프트 기반 스마트 응답을 반환하는 개발 호출기입니다. _cursor와 _lock으로 다중 스레드의 응답 순서를 관리합니다. 실제 의도/투자 판단 품질을 보장하는 모델은 아닙니다.

기반: `_Base`.

메서드·속성: [__init__](#common-llm-py-StubLlm-__init__-101), [complete_json](#common-llm-py-StubLlm-complete_json-117).


<a id="common-llm-py-OpenAiLlm-160"></a>
### `OpenAiLlm`

<!-- source-symbol: common/llm.py:160:OpenAiLlm -->
[llm.py](../../backend/analysis/common/llm.py#L160)

설정된 클라이언트로 JSON LLM 응답을 받아 캐시·사용량·전송 재시도·내용 보정을 처리합니다. settings·cache_dir·usage_log·run_id·지연 생성 _client·기록 잠금·동시 호출 세마포어를 보관합니다. 실제 호출과 숫자 계산의 책임을 분리하는 경계입니다.

기반: `_Base`.

메서드·속성: [__init__](#common-llm-py-OpenAiLlm-__init__-161), [_family](#common-llm-py-OpenAiLlm-_family-182), [_setting](#common-llm-py-OpenAiLlm-_setting-186), [_client_openai](#common-llm-py-OpenAiLlm-_client_openai-194), [_backoff](#common-llm-py-OpenAiLlm-_backoff-206), [_cost_usd](#common-llm-py-OpenAiLlm-_cost_usd-219), [cache_key](#common-llm-py-OpenAiLlm-cache_key-234), [_call](#common-llm-py-OpenAiLlm-_call-238), [complete_json](#common-llm-py-OpenAiLlm-complete_json-329).


<a id="common-store-py-JsonStore-34"></a>
### `JsonStore`

<!-- source-symbol: common/store.py:34:JsonStore -->
[store.py](../../backend/analysis/common/store.py#L34)

프로필·요청·큐·모의투자·비교를 파일로 저장하는 기반 객체입니다. root와 schemas_dir를 보관하고 단일 JSON 원자 교체·JSONL 추가·명시적 이름별 잠금을 제공합니다. write 자체가 모든 읽기-수정-쓰기 연산을 직렬화하는 것은 아닙니다.

기반: `명시적 부모 없음`.

메서드·속성: [__init__](#common-store-py-JsonStore-__init__-35), [path](#common-store-py-JsonStore-path-40), [read](#common-store-py-JsonStore-read-43), [validate](#common-store-py-JsonStore-validate-49), [write](#common-store-py-JsonStore-write-55), [append_jsonl](#common-store-py-JsonStore-append_jsonl-70), [read_jsonl](#common-store-py-JsonStore-read_jsonl-78), [locked](#common-store-py-JsonStore-locked-85).


<a id="common-store-py-ProfileStore-114"></a>
### `ProfileStore`

<!-- source-symbol: common/store.py:114:ProfileStore -->
[store.py](../../backend/analysis/common/store.py#L114)

profile.json의 단일 사용자 프로필과 버전 이력을 관리합니다. REL은 파일명이고 store는 실제 입출력 객체입니다. 수정은 새 버전 추가로 처리합니다.

기반: `명시적 부모 없음`.

클래스 상수: `REL = 'profile.json'`.

메서드·속성: [__init__](#common-store-py-ProfileStore-__init__-119), [load](#common-store-py-ProfileStore-load-122), [current](#common-store-py-ProfileStore-current-125), [version](#common-store-py-ProfileStore-version-132), [save](#common-store-py-ProfileStore-save-141).


<a id="common-store-py-RequestStore-154"></a>
### `RequestStore`

<!-- source-symbol: common/store.py:154:RequestStore -->
[store.py](../../backend/analysis/common/store.py#L154)

requests/<request_id>.json을 AnalysisRequestDoc으로 읽고 씁니다. 저장 경로와 요청별 잠금을 모아 대화 갱신의 일관성을 제공합니다.

기반: `명시적 부모 없음`.

메서드·속성: [__init__](#common-store-py-RequestStore-__init__-157), [rel](#common-store-py-RequestStore-rel-160), [load](#common-store-py-RequestStore-load-163), [save](#common-store-py-RequestStore-save-169), [list](#common-store-py-RequestStore-list-172), [locked](#common-store-py-RequestStore-locked-180).


<a id="common-store-py-RunIndex-186"></a>
### `RunIndex`

<!-- source-symbol: common/store.py:186:RunIndex -->
[store.py](../../backend/analysis/common/store.py#L186)

runs.json의 실행 목록을 관리합니다. 실행 상태는 금융 결과 DB와 별도이며 큐가 선점·취소·완료를 기록하는 원본입니다.

기반: `명시적 부모 없음`.

클래스 상수: `REL = 'runs.json'`.

메서드·속성: [__init__](#common-store-py-RunIndex-__init__-191), [load](#common-store-py-RunIndex-load-194), [save](#common-store-py-RunIndex-save-198), [get](#common-store-py-RunIndex-get-202), [upsert](#common-store-py-RunIndex-upsert-208), [update](#common-store-py-RunIndex-update-214), [locked](#common-store-py-RunIndex-locked-225).


<a id="common-store-py-PaperStore-231"></a>
### `PaperStore`

<!-- source-symbol: common/store.py:231:PaperStore -->
[store.py](../../backend/analysis/common/store.py#L231)

paper/<paper_id>/portfolio.json, snapshots.jsonl, rebalances.jsonl을 관리합니다. 각 기록을 별도 파일로 저장하고 여러 파일을 한 번에 커밋하는 기능은 없습니다.

기반: `명시적 부모 없음`.

메서드·속성: [__init__](#common-store-py-PaperStore-__init__-232), [rel](#common-store-py-PaperStore-rel-235), [load](#common-store-py-PaperStore-load-238), [save](#common-store-py-PaperStore-save-244), [list](#common-store-py-PaperStore-list-247), [append_snapshot](#common-store-py-PaperStore-append_snapshot-253), [snapshots](#common-store-py-PaperStore-snapshots-256), [append_rebalance](#common-store-py-PaperStore-append_rebalance-259), [rebalances](#common-store-py-PaperStore-rebalances-262).


<a id="common-store-py-ComparisonStore-266"></a>
### `ComparisonStore`

<!-- source-symbol: common/store.py:266:ComparisonStore -->
[store.py](../../backend/analysis/common/store.py#L266)

comparisons/<comparison_id>.json에 원안·수정안 비교 결과를 저장합니다. 비교 수치를 계산하지 않고 파일 입출력만 담당합니다.

기반: `명시적 부모 없음`.

메서드·속성: [__init__](#common-store-py-ComparisonStore-__init__-267), [rel](#common-store-py-ComparisonStore-rel-270), [load](#common-store-py-ComparisonStore-load-273), [save](#common-store-py-ComparisonStore-save-279).


<a id="common-warnings-py-Warning-19"></a>
### `Warning`

<!-- source-symbol: common/warnings.py:19:Warning -->
[warnings.py](../../backend/analysis/common/warnings.py#L19)

한 실행 경고의 구조화 레코드입니다. stage·code·level·message_ko가 기본이고 count는 반복 수, dates는 발생 날짜, details는 병합 키나 원문 등 추가 정보입니다. user/info/debug 등급이 화면 표시·부분 성공을 결정합니다.

기반: `명시적 부모 없음` · 선언: `dataclass`.

| 필드 | 자료형 | 기본값 또는 생성 방식 | 선언된 제약·설명 |
| --- | --- | --- | --- |
| `stage` | `str` | `필수 입력` | 단계 산출물 종류 |
| `code` | `str` | `필수 입력` | 분류 코드 또는 업무 경고 코드 |
| `level` | `Level` | `필수 입력` | 경고/검증 수준 |
| `message_ko` | `str` | `필수 입력` | 한국어 안내·오류 문장 |
| `count` | `int` | `1` | 같은 종류 경고의 반복 발생 수 |
| `dates` | `list[str]` | `생성 함수: list` | 관련 날짜 목록 |
| `details` | `dict[str, Any] \| None` | `None` | 오류·경고의 보조 정보 |

메서드·속성: [to_dict](#common-warnings-py-Warning-to_dict-28).


<a id="errors-py-RequestInvalid-11"></a>
### `RequestInvalid`

<!-- source-symbol: errors.py:11:RequestInvalid -->
[errors.py](../../backend/analysis/errors.py#L11)

요청 조건 검증 실패 예외입니다. details.fields로 필드별 수정 안내를 전달하고 API는 기본 HTTP 422로 변환합니다.

기반: `MyFinSightError`.

클래스 상수: `code = 'REQUEST_INVALID'`; `recoverable = True`.

직접 정의한 메서드는 없습니다. 부모의 동작과 위 상수/계약을 사용합니다.


<a id="errors-py-DialogBlocked-18"></a>
### `DialogBlocked`

<!-- source-symbol: errors.py:18:DialogBlocked -->
[errors.py](../../backend/analysis/errors.py#L18)

blocked 대화의 확정을 거부하는 호환 예외입니다. 현재 정상 턴은 질문 상한에서 ready를 허용하므로 상한 도달이 항상 이 예외를 뜻하지 않습니다.

기반: `MyFinSightError`.

클래스 상수: `code = 'DIALOG_BLOCKED'`; `recoverable = True`.

직접 정의한 메서드는 없습니다. 부모의 동작과 위 상수/계약을 사용합니다.


<a id="errors-py-DialogNotReady-25"></a>
### `DialogNotReady`

<!-- source-symbol: errors.py:25:DialogNotReady -->
[errors.py](../../backend/analysis/errors.py#L25)

ready 조건을 만족하지 못한 confirm을 거부하는 예외입니다. 현재 상태와 HARD 오류 정보를 함께 전달할 수 있습니다.

기반: `MyFinSightError`.

클래스 상수: `code = 'DIALOG_NOT_READY'`; `recoverable = True`.

직접 정의한 메서드는 없습니다. 부모의 동작과 위 상수/계약을 사용합니다.


<a id="errors-py-LookaheadError-32"></a>
### `LookaheadError`

<!-- source-symbol: errors.py:32:LookaheadError -->
[errors.py](../../backend/analysis/errors.py#L32)

기준일 또는 strict 정보 마감을 넘는 조회를 차단하는 DATA_LOOKAHEAD 예외입니다.

기반: `MyFinSightError`.

클래스 상수: `code = 'DATA_LOOKAHEAD'`.

직접 정의한 메서드는 없습니다. 부모의 동작과 위 상수/계약을 사용합니다.


<a id="errors-py-DataMissing-38"></a>
### `DataMissing`

<!-- source-symbol: errors.py:38:DataMissing -->
[errors.py](../../backend/analysis/errors.py#L38)

환율·필수 가격·비교지수·평가 범위 등 필수 자료 부재를 나타냅니다. 기본 코드는 DATA_REQUIRED_MISSING이고 모의투자에서는 지연 상태로 변환될 수 있습니다.

기반: `MyFinSightError`.

클래스 상수: `code = 'DATA_REQUIRED_MISSING'`.

직접 정의한 메서드는 없습니다. 부모의 동작과 위 상수/계약을 사용합니다.


<a id="errors-py-StageFailed-44"></a>
### `StageFailed`

<!-- source-symbol: errors.py:44:StageFailed -->
[errors.py](../../backend/analysis/errors.py#L44)

분석 단계의 일반 실패를 기록할 때 사용하는 STAGE_FAILED 오류 종류입니다. 원래 예외가 도메인 오류가 아니면 러너가 이 코드를 대표로 기록합니다.

기반: `MyFinSightError`.

클래스 상수: `code = 'STAGE_FAILED'`.

직접 정의한 메서드는 없습니다. 부모의 동작과 위 상수/계약을 사용합니다.


<a id="errors-py-LlmOutputError-50"></a>
### `LlmOutputError`

<!-- source-symbol: errors.py:50:LlmOutputError -->
[errors.py](../../backend/analysis/errors.py#L50)

실제 LLM 설정·응답 파싱·보정 후 검증 실패를 전달합니다. 기본 LLM_OUTPUT_INVALID 외 LLM_CONFIG 같은 명시 코드도 사용할 수 있습니다.

기반: `MyFinSightError`.

클래스 상수: `code = 'LLM_OUTPUT_INVALID'`.

직접 정의한 메서드는 없습니다. 부모의 동작과 위 상수/계약을 사용합니다.


<a id="errors-py-ReportCheckError-56"></a>
### `ReportCheckError`

<!-- source-symbol: errors.py:56:ReportCheckError -->
[errors.py](../../backend/analysis/errors.py#L56)

최종 문서 게이트 오류를 전달하는 REPORT_CHECK_FAILED 예외입니다. 실패 문서가 정상 리포트 저장 경로로 가지 않도록 러너를 실패시킵니다.

기반: `MyFinSightError`.

클래스 상수: `code = 'REPORT_CHECK_FAILED'`.

직접 정의한 메서드는 없습니다. 부모의 동작과 위 상수/계약을 사용합니다.


<a id="errors-py-QueueError-62"></a>
### `QueueError`

<!-- source-symbol: errors.py:62:QueueError -->
[errors.py](../../backend/analysis/errors.py#L62)

큐 관련 도메인 오류를 표현하는 종류입니다. 정의 존재와 현재 모든 큐 실패가 이 타입으로 발생한다는 주장은 구분합니다.

기반: `MyFinSightError`.

클래스 상수: `code = 'QUEUE_ERROR'`.

직접 정의한 메서드는 없습니다. 부모의 동작과 위 상수/계약을 사용합니다.


<a id="errors-py-CancelRequested-66"></a>
### `CancelRequested`

<!-- source-symbol: errors.py:66:CancelRequested -->
[errors.py](../../backend/analysis/errors.py#L66)

취소 확인 지점에서 작업 중단을 나타내는 RUN_CANCELLED 예외입니다. 강제 스레드 종료 신호는 아닙니다.

기반: `MyFinSightError`.

클래스 상수: `code = 'RUN_CANCELLED'`; `recoverable = True`.

직접 정의한 메서드는 없습니다. 부모의 동작과 위 상수/계약을 사용합니다.


<a id="errors-py-NotFound-73"></a>
### `NotFound`

<!-- source-symbol: errors.py:73:NotFound -->
[errors.py](../../backend/analysis/errors.py#L73)

요청·실행·리포트·근거·모의투자 부재를 나타내며 API에서 HTTP 404로 변환합니다.

기반: `MyFinSightError`.

클래스 상수: `code = 'NOT_FOUND'`; `recoverable = True`.

직접 정의한 메서드는 없습니다. 부모의 동작과 위 상수/계약을 사용합니다.


<a id="errors-py-Conflict-78"></a>
### `Conflict`

<!-- source-symbol: errors.py:78:Conflict -->
[errors.py](../../backend/analysis/errors.py#L78)

중복 응답·이미 확정·부적합 실행 상태 등 동작과 현재 상태의 충돌을 표현합니다. HTTP 기본값은 409입니다.

기반: `MyFinSightError`.

클래스 상수: `code = 'CONFLICT'`; `recoverable = True`.

직접 정의한 메서드는 없습니다. 부모의 동작과 위 상수/계약을 사용합니다.


<a id="settings-py-MarketSettings-19"></a>
### `MarketSettings`

<!-- source-symbol: settings.py:19:MarketSettings -->
[settings.py](../../backend/analysis/settings.py#L19)

지원 시장·유니버스·비교지수·달력·품질·가치평가 유효기간·사전·재무 시작일 설정입니다. 가용 시작일은 코드의 운영 기본값이며 실시간 DB 탐지값이 아닙니다.

기반: `명시적 부모 없음` · 선언: `dataclass(frozen=True)`.

| 필드 | 자료형 | 기본값 또는 생성 방식 | 선언된 제약·설명 |
| --- | --- | --- | --- |
| `markets` | `tuple[str, ...]` | `('US', 'KR')` | 관련 시장 목록 |
| `universes` | `tuple[str, ...]` | `('SP500', 'NASDAQ100', 'KOSPI200')` | — |
| `primary_benchmark_default` | `str` | `'SPY'` | — |
| `kr_benchmark` | `str` | `'069500.KS'` | — |
| `extra_benchmarks` | `tuple[str, ...]` | `('QQQ',)` | 추가 비교지수 티커 |
| `calendar` | `Literal['union']` | `'union'` | — |
| `coverage_threshold` | `float` | `0.95` | — |
| `max_fill_days` | `int` | `1` | — |
| `valuation_max_staleness_days` | `int` | `10` | — |
| `descriptor_universe` | `str` | `'ALL'` | — |
| `descriptor_dir` | `str \| None` | `None` | — |
| `valuation_data_start` | `dict[str, str]` | `생성 함수: {'US': '2010-04-01', 'KR': '2005-06-01'}` | — |
| `valuation_templates` | `tuple[str, ...]` | `('low_per', 'quality', 'high_dividend')` | — |


<a id="settings-py-PortfolioSettings-37"></a>
### `PortfolioSettings`

<!-- source-symbol: settings.py:37:PortfolioSettings -->
[settings.py](../../backend/analysis/settings.py#L37)

추정 이력·공분산 수축·BL τ·위험회피·성향/낙폭 배수·최소 비중·의견 범위·네 비중 방식과 반복 제약 설정입니다. frozen dataclass로 실행 중 직접 필드 변경을 막습니다.

기반: `명시적 부모 없음` · 선언: `dataclass(frozen=True)`.

| 필드 | 자료형 | 기본값 또는 생성 방식 | 선언된 제약·설명 |
| --- | --- | --- | --- |
| `lookback_days` | `int` | `756` | — |
| `min_history_days_for_model` | `int` | `252` | — |
| `shrinkage` | `Literal['ledoit_wolf', 'none']` | `'ledoit_wolf'` | 공분산 수축 방식·강도 |
| `tau` | `float` | `0.05` | 사전 추정 불확실성 계수 τ |
| `risk_aversion` | `dict[str, float]` | `생성 함수: {'conservative': 4.0, 'moderate': 2.5, 'aggressive': 1.5}` | — |
| `risk_aversion_mode` | `Literal['fixed', 'market_implied']` | `'market_implied'` | — |
| `risk_aversion_mult` | `dict[str, float]` | `생성 함수: {'conservative': 1.5, 'moderate': 1.0, 'aggressive': 0.7}` | — |
| `delta_floor` | `float` | `1.5` | — |
| `delta_dd_ref_tol` | `float` | `0.2` | — |
| `delta_dd_mult_range` | `tuple[float, float]` | `(0.75, 1.5)` | — |
| `min_weight` | `float` | `0.01` | — |
| `omega_method` | `str` | `'he_litterman_confidence'` | — |
| `confidence_floor` | `float` | `0.1` | — |
| `abs_return_range` | `tuple[float, float]` | `(-0.5, 1.0)` | — |
| `rel_return_range` | `tuple[float, float]` | `(0.0, 0.5)` | — |
| `templates` | `tuple[str, ...]` | `('equal_weight', 'market_cap', 'inverse_volatility', 'min_variance')` | 기준 비중 방식의 결과 |
| `template_names_ko` | `dict[str, tuple[str, str]]` | `생성 함수: {'equal_weight': ('동일비중', '모든 종목에 같은 비중 1/N'), 'market_cap': ('시가총액비중', '시가총액에 비례한 비중 (지수 방식)'), 'inverse_volatility': ('역변동성비중', '변동성이 낮은 종목에 더 큰 비중 (1/σ 정규화)'), 'min_variance': ('최소분산', '포트폴리오 분산을 최소화하는 비중 (제약 포함 최적화)')}` | — |
| `max_iter` | `int` | `50` | — |
| `estimation_strict_before` | `bool` | `True` | — |


<a id="settings-py-NewsSettings-73"></a>
### `NewsSettings`

<!-- source-symbol: settings.py:73:NewsSettings -->
[settings.py](../../backend/analysis/settings.py#L73)

뉴스 창 길이·종목당 기사 수·최소 근거 종목 수·언어·시작/재구성 의견 수의 기본값입니다.

기반: `명시적 부모 없음` · 선언: `dataclass(frozen=True)`.

| 필드 | 자료형 | 기본값 또는 생성 방식 | 선언된 제약·설명 |
| --- | --- | --- | --- |
| `window_days` | `int` | `14` | — |
| `per_ticker` | `int` | `10` | — |
| `min_tickers` | `int` | `3` | 의견 생성에 필요한 근거 종목 수 |
| `languages` | `tuple[str, ...]` | `('en', 'ko')` | — |
| `view_sets_at_start` | `int` | `5` | — |
| `view_sets_at_rebalance` | `int` | `1` | — |
| `views_per_set` | `int` | `4` | 세트당 의견 개수 |


<a id="settings-py-DisclosureSettings-84"></a>
### `DisclosureSettings`

<!-- source-symbol: settings.py:84:DisclosureSettings -->
[settings.py](../../backend/analysis/settings.py#L84)

공시 사용·45일 의견 창·90일 요약 창·종목당 건수·최소 종목 수 포함·공시 단독 신뢰도·수정 제외·사건 허용 목록 설정입니다.

기반: `명시적 부모 없음` · 선언: `dataclass(frozen=True)`.

| 필드 | 자료형 | 기본값 또는 생성 방식 | 선언된 제약·설명 |
| --- | --- | --- | --- |
| `enabled` | `bool` | `True` | 해당 기능·규칙의 활성화 |
| `window_days` | `int` | `45` | — |
| `summary_days` | `int` | `90` | — |
| `per_ticker` | `int` | `8` | — |
| `count_toward_min_tickers` | `bool` | `True` | — |
| `disclosure_only_max_confidence` | `float` | `0.25` | — |
| `include_amendments` | `bool` | `False` | — |
| `event_types` | `tuple[str, ...]` | `('earnings', 'executive_change', 'material_agreement', 'agreement_termination', 'buyback', 'dividend', 'merger_split', 'merger_registration', 'acquisition_disposition', 'securities_offering', 'capital_change', 'control_change', 'litigation', 'rumor_response', 'capex', 'restructuring', 'impairment', 'bankruptcy', 'restatement', 'delisting_notice', 'debt_acceleration', 'auditor_change', 'production_change', 'tender_offer', 'fair_disclosure', 'cybersecurity')` | — |
| `summary_extra_event_types` | `tuple[str, ...]` | `('quarterly_report', 'annual_report', 'semiannual_report', 'investor_relations', 'reg_fd', 'other_event', 'voluntary_disclosure')` | — |


<a id="settings-py-BacktestSettings-106"></a>
### `BacktestSettings`

<!-- source-symbol: settings.py:106:BacktestSettings -->
[settings.py](../../backend/analysis/settings.py#L106)

수수료·소수/정수 수량·무위험수익률·연간 거래일·일정·드리프트·체크포인트·검증·짧은 창·추천·시계열 저장 설정입니다. 단가와 임계치는 코드 기본값으로 읽어야 합니다.

기반: `명시적 부모 없음` · 선언: `dataclass(frozen=True)`.

| 필드 | 자료형 | 기본값 또는 생성 방식 | 선언된 제약·설명 |
| --- | --- | --- | --- |
| `commission_bps` | `float` | `5` | — |
| `integer_positions` | `bool` | `False` | — |
| `risk_free_rate` | `float` | `0.04` | — |
| `trading_days` | `int` | `252` | 연간 거래일 기준 또는 해당 기간 거래일 수 |
| `drift_tolerance` | `float` | `0.25` | — |
| `rebalance_trading_days` | `dict[str, int]` | `생성 함수: {'2w': 10}` | — |
| `checkpoint_freq` | `Literal['rebalance', 'monthly']` | `'rebalance'` | — |
| `event_drawdown_levels` | `tuple[float, ...]` | `(-0.1, -0.2)` | — |
| `save_daily_panel` | `bool` | `True` | — |
| `view_horizon_days` | `int` | `365` | — |
| `vol_bands` | `dict[str, float]` | `생성 함수: {'low': 0.15, 'medium': 0.3, 'high': 9.99}` | — |
| `vol_multipliers` | `dict[str, float \| None]` | `생성 함수: {'low': 1.0, 'medium': 1.3, 'high': None}` | — |
| `target_window_min_ratio` | `float` | `0.5` | — |
| `min_invested_ratio` | `float` | `0.9` | — |
| `default_backtest_years` | `float` | `3.0` | — |
| `min_annualize_days` | `int` | `378` | — |
| `min_invested_for_recommendation` | `float` | `0.5` | — |
| `dd_excess_bucket` | `float` | `0.05` | — |
| `checkpoint_view_diagnostics` | `bool` | `False` | — |


<a id="settings-py-LlmSettings-130"></a>
### `LlmSettings`

<!-- source-symbol: settings.py:130:LlmSettings -->
[settings.py](../../backend/analysis/settings.py#L130)

실제/stub 모드·모델·출력·단계별 override·캐시·타임아웃·재시도·동시 수·로그 비용 계산용 단가를 보관합니다. API 키는 값이 아니라 읽을 환경변수 이름만 보관합니다.

기반: `명시적 부모 없음` · 선언: `dataclass(frozen=True)`.

| 필드 | 자료형 | 기본값 또는 생성 방식 | 선언된 제약·설명 |
| --- | --- | --- | --- |
| `mode` | `LlmMode` | `'stub'` | 실행·구성·평가 방식 |
| `provider` | `str` | `'openai'` | — |
| `model` | `str` | `'gpt-6-luna'` | — |
| `temperature` | `float \| None` | `None` | — |
| `max_output_tokens` | `int` | `8000` | — |
| `reasoning_effort` | `str \| None` | `None` | — |
| `response_format_json` | `bool` | `True` | — |
| `stage_overrides` | `dict[str, dict[str, Any]]` | `생성 함수: {'04_classify': {'max_output_tokens': 6000}, '09_views_news': {'max_output_tokens': 8000}, '14a_interpret': {'max_output_tokens': 8000}, '14b_narrate': {'max_output_tokens': 10000}}` | — |
| `max_output_tokens_ceiling` | `int` | `16000` | — |
| `timeout_s` | `int` | `180` | — |
| `retries` | `int` | `3` | — |
| `retry_backoff_max_s` | `int` | `60` | — |
| `max_concurrency` | `int` | `4` | — |
| `retry_backoff_s` | `int` | `15` | — |
| `cache` | `bool` | `True` | — |
| `api_key_env` | `str` | `'OPENAI_API_KEY'` | — |
| `pricing_usd_per_1m` | `dict[str, dict[str, float]]` | `생성 함수: {'gpt-6-luna': {'input': 0.1, 'cached_input': 0.01, 'cache_write': 0.125, 'output': 0.5}}` | — |


<a id="settings-py-SelectionSettings-162"></a>
### `SelectionSettings`

<!-- source-symbol: settings.py:162:SelectionSettings -->
[settings.py](../../backend/analysis/settings.py#L162)

후보 상한 120, 넓은 테마 섹터 수 6, 지표 기반 사전 절단 켜짐 설정입니다.

기반: `명시적 부모 없음` · 선언: `dataclass(frozen=True)`.

| 필드 | 자료형 | 기본값 또는 생성 방식 | 선언된 제약·설명 |
| --- | --- | --- | --- |
| `max_candidates` | `int` | `120` | — |
| `broad_theme_min_sectors` | `int` | `6` | — |
| `metric_prefilter` | `bool` | `True` | — |


<a id="settings-py-DialogSettings-171"></a>
### `DialogSettings`

<!-- source-symbol: settings.py:171:DialogSettings -->
[settings.py](../../backend/analysis/settings.py#L171)

질문 상한·턴당 제안 수·섹터 상한 충돌 질문·질문 가능 필드 목록을 보관합니다. 상한을 만났을 때의 실제 상태 전이는 DialogService가 결정합니다.

기반: `명시적 부모 없음` · 선언: `dataclass(frozen=True)`.

| 필드 | 자료형 | 기본값 또는 생성 방식 | 선언된 제약·설명 |
| --- | --- | --- | --- |
| `max_questions` | `int` | `5` | 질문 횟수 상한 |
| `max_proposals_per_turn` | `int` | `3` | — |
| `ask_sector_cap_conflict` | `bool` | `True` | — |
| `askable_fields` | `tuple[str, ...]` | `('natural_language.idea', 'strategy_preference.template', 'strategy_preference.baseline_weighting', 'strategy_preference.use_news_tilt', 'constraints.universe', 'constraints.num_holdings.target', 'constraints.num_holdings', 'constraints.exclude_sectors', 'constraints.exclude_themes', 'constraints.exclude_tickers', 'constraints.must_include_tickers', 'constraints.rebalance', 'constraints.max_weight_per_stock', 'constraints.max_weight_per_sector', 'constraints.min_cash_ratio', 'risk.benchmark', 'risk.target_annual_return', 'risk.max_drawdown_tolerance', 'horizon.backtest_years', 'horizon.start_date', 'horizon', 'horizon.purpose', 'capital.monthly_contribution')` | — |


<a id="settings-py-ReportSettings-206"></a>
### `ReportSettings`

<!-- source-symbol: settings.py:206:ReportSettings -->
[settings.py](../../backend/analysis/settings.py#L206)

설정 모음의 리포트 정책입니다. 일곱 섹션 순서·숫자 엄격 검사·금지 표현·시계열 표본 크기를 보관합니다. 의도 스키마의 동명 클래스는 언어·설명 수준을 뜻하므로 별도로 설명합니다.

기반: `명시적 부모 없음` · 선언: `dataclass(frozen=True)`.

| 필드 | 자료형 | 기본값 또는 생성 방식 | 선언된 제약·설명 |
| --- | --- | --- | --- |
| `sections` | `tuple[str, ...]` | `('verdict', 'market', 'companies', 'construction', 'performance', 'assumptions', 'references')` | 순서 있는 본문 섹션 |
| `strict_numbers` | `bool` | `False` | — |
| `banned_phrases` | `tuple[str, ...]` | `('보장', '확실한 수익', '무위험', '반드시 오른다', '손실 없음')` | — |
| `max_series_points` | `int` | `600` | — |


<a id="settings-py-ExecutorSettings-222"></a>
### `ExecutorSettings`

<!-- source-symbol: settings.py:222:ExecutorSettings -->
[settings.py](../../backend/analysis/settings.py#L222)

단계·날짜별 구성·분류 병렬 수, 14a/14c 병렬 여부와 진행 통지 최소 간격입니다. 0인 하위 작업 수는 LLM 동시 수를 사용한다는 상위 코드 규칙이 있습니다.

기반: `명시적 부모 없음` · 선언: `dataclass(frozen=True)`.

| 필드 | 자료형 | 기본값 또는 생성 방식 | 선언된 제약·설명 |
| --- | --- | --- | --- |
| `max_parallel_stages` | `int` | `3` | — |
| `walkforward_workers` | `int` | `0` | — |
| `classify_workers` | `int` | `0` | — |
| `parallel_report_calls` | `bool` | `True` | — |
| `progress_min_interval_s` | `float` | `1.5` | — |


<a id="settings-py-TrackingSettings-233"></a>
### `TrackingSettings`

<!-- source-symbol: settings.py:233:TrackingSettings -->
[settings.py](../../backend/analysis/settings.py#L233)

워커가 한가할 때 모의투자를 갱신할지와 기본 3,600초 간격을 설정합니다.

기반: `명시적 부모 없음` · 선언: `dataclass(frozen=True)`.

| 필드 | 자료형 | 기본값 또는 생성 방식 | 선언된 제약·설명 |
| --- | --- | --- | --- |
| `refresh_interval_s` | `int` | `3600` | — |
| `refresh_on_worker_idle` | `bool` | `True` | — |


<a id="settings-py-AnalysisSettings-241"></a>
### `AnalysisSettings`

<!-- source-symbol: settings.py:241:AnalysisSettings -->
[settings.py](../../backend/analysis/settings.py#L241)

모든 하위 설정과 pipeline_version을 묶는 실행 설정입니다. load가 환경을 적용하고 snapshot이 실행 근거로 저장할 사전을 만듭니다.

기반: `명시적 부모 없음` · 선언: `dataclass(frozen=True)`.

| 필드 | 자료형 | 기본값 또는 생성 방식 | 선언된 제약·설명 |
| --- | --- | --- | --- |
| `market` | `MarketSettings` | `생성 함수: MarketSettings` | US·KR 등 시장 |
| `portfolio` | `PortfolioSettings` | `생성 함수: PortfolioSettings` | — |
| `news` | `NewsSettings` | `생성 함수: NewsSettings` | 조건별 뉴스·공시 창 캐시 |
| `backtest` | `BacktestSettings` | `생성 함수: BacktestSettings` | 과거 평가 창 또는 평가 결과 |
| `llm` | `LlmSettings` | `생성 함수: LlmSettings` | 실제 또는 stub LLM 호출기 |
| `dialog` | `DialogSettings` | `생성 함수: DialogSettings` | — |
| `selection` | `SelectionSettings` | `생성 함수: SelectionSettings` | 선정 사양·결과 |
| `report` | `ReportSettings` | `생성 함수: ReportSettings` | — |
| `tracking` | `TrackingSettings` | `생성 함수: TrackingSettings` | 모의투자 표시 가능 여부 |
| `disclosures` | `DisclosureSettings` | `생성 함수: DisclosureSettings` | 공시 사건 레코드 |
| `executor` | `ExecutorSettings` | `생성 함수: ExecutorSettings` | — |
| `pipeline_version` | `str` | `'analysis-1.0'` | 분석 구현 버전 표기 |

메서드·속성: [load](#settings-py-AnalysisSettings-load-256), [snapshot](#settings-py-AnalysisSettings-snapshot-295).


<a id="functions"></a>
## 5. 함수·메서드 상세

시그니처에 입력 자료형·기본값·반환 자료형을 그대로 기재했습니다. `self`는 소속 클래스의 인스턴스, `cls`는 클래스입니다. 반환 주석이 없는 함수는 본문 해설의 반환 내용을 따릅니다. 속성(`property`)은 호출 괄호 없이 읽고, 중첩 함수는 바깥 함수의 지역 상태를 공유합니다. 연결 목록은 정적으로 확인되는 패키지 내부 직접 호출이며, 주입된 서비스·콜백·Repository 호출은 처리 흐름과 해설에서 설명합니다.


<a id="file-common-citations-py"></a>
### common/citations.py


<a id="common-citations-py-kind_of-17"></a>
#### `kind_of`

<!-- source-symbol: common/citations.py:17:kind_of -->
[citations.py](../../backend/analysis/common/citations.py#L17)

```python
def kind_of(cid: str) -> str: ...
```

인용 ID 접두사 ev, dc, fin, calc를 각각 뉴스·공시·금융 지표·계산값 종류로 분류합니다. 일치하지 않으면 unknown을 반환하며 ID 전체 형식 검증은 하지 않습니다.


<a id="file-common-dbconn-py"></a>
### common/dbconn.py


<a id="common-dbconn-py-database_url-27"></a>
#### `database_url`

<!-- source-symbol: common/dbconn.py:27:database_url -->
[dbconn.py](../../backend/analysis/common/dbconn.py#L27)

```python
def database_url() -> str | None: ...
```

DATABASE_URL, NEWS_DB_URL, NEWS_DB_HOST/USER/PASSWORD 조합 순으로 시장 DB 주소를 선택합니다. 조합 시 사용자·비밀번호를 URL 인코딩하고 포트·DB명·SSL 기본값을 적용합니다. 지정이 없으면 None으로 backend.db 기본값에 맡깁니다.

호출하는 코드: [open_analysis_repository](#common-dbconn-py-open_analysis_repository-75), [describe](#common-dbconn-py-describe-96).


<a id="common-dbconn-py-results_url-40"></a>
#### `results_url`

<!-- source-symbol: common/dbconn.py:40:results_url -->
[dbconn.py](../../backend/analysis/common/dbconn.py#L40)

```python
def results_url(market_url: str | None) -> str | None: ...
```

ANALYSIS_RESULTS_DB가 main이면 시장 DB 재사용을 뜻하는 None, 별도 값이면 그 주소를 반환합니다. 미지정 상태에서 명시된 시장 URL이 SQLite가 아니면 로컬 analysis_results.db를 사용하고, 나머지는 시장 저장소를 재사용합니다.

호출하는 코드: [open_analysis_repository](#common-dbconn-py-open_analysis_repository-75), [describe](#common-dbconn-py-describe-96).


<a id="common-dbconn-py-SplitRepository-__init__-55"></a>
#### `SplitRepository.__init__`

<!-- source-symbol: common/dbconn.py:55:SplitRepository.__init__ -->
[dbconn.py](../../backend/analysis/common/dbconn.py#L55)

```python
def __init__(self, market: Any, results: Any) -> None: ...
```

시장 읽기용과 결과 저장용 Repository를 각각 보관합니다. 메서드 라우팅은 __getattr__에서 수행됩니다.


<a id="common-dbconn-py-SplitRepository-market-60"></a>
#### `SplitRepository.market`

<!-- source-symbol: common/dbconn.py:60:SplitRepository.market -->
[dbconn.py](../../backend/analysis/common/dbconn.py#L60)

```python
def market(self) -> Any: ...
```

보관된 시장 자료 Repository를 반환합니다.

선언·진입 조건: `property`.


<a id="common-dbconn-py-SplitRepository-results-64"></a>
#### `SplitRepository.results`

<!-- source-symbol: common/dbconn.py:64:SplitRepository.results -->
[dbconn.py](../../backend/analysis/common/dbconn.py#L64)

```python
def results(self) -> Any: ...
```

보관된 실행 기록·결과·리포트 Repository를 반환합니다.

선언·진입 조건: `property`.


<a id="common-dbconn-py-SplitRepository-__getattr__-67"></a>
#### `SplitRepository.__getattr__`

<!-- source-symbol: common/dbconn.py:67:SplitRepository.__getattr__ -->
[dbconn.py](../../backend/analysis/common/dbconn.py#L67)

```python
def __getattr__(self, name: str) -> Any: ...
```

요청한 이름이 RESULT_METHODS에 있으면 결과 저장소로, 나머지는 시장 저장소로 위임합니다. save_step/get_steps, artifact/report 저장·조회, list_reports, job_lock 등이 결과 저장소에 배정됩니다.


<a id="common-dbconn-py-SplitRepository-__repr__-71"></a>
#### `SplitRepository.__repr__`

<!-- source-symbol: common/dbconn.py:71:SplitRepository.__repr__ -->
[dbconn.py](../../backend/analysis/common/dbconn.py#L71)

```python
def __repr__(self) -> str: ...
```

두 Repository의 표현을 포함한 디버깅 문자열을 반환합니다. 사용자용 접속 위치 안내에는 describe를 사용합니다.


<a id="common-dbconn-py-open_analysis_repository-75"></a>
#### `open_analysis_repository`

<!-- source-symbol: common/dbconn.py:75:open_analysis_repository -->
[dbconn.py](../../backend/analysis/common/dbconn.py#L75)

```python
def open_analysis_repository(market_url: str | None=None) -> Any: ...
```

전달 URL 또는 환경 설정으로 시장 Repository를 열고 필요한 경우 결과 Repository를 따로 열어 SplitRepository로 반환합니다. 실제 DB 연결·테이블 준비 등 부수효과는 backend.db.open_repository 구현에 따릅니다.

직접 연결: [database_url](#common-dbconn-py-database_url-27), [results_url](#common-dbconn-py-results_url-40), [SplitRepository](#common-dbconn-py-SplitRepository-52).

호출하는 코드: [default_repo](#common-dbconn-py-default_repo-85), [_results_db](eval_구현보고서.md#eval-requirements-py-_results_db-54), [main](executor_구현보고서.md#executor-cli-py-main-27), [main](executor_구현보고서.md#executor-worker-py-main-112).


<a id="common-dbconn-py-default_repo-85"></a>
#### `default_repo`

<!-- source-symbol: common/dbconn.py:85:default_repo -->
[dbconn.py](../../backend/analysis/common/dbconn.py#L85)

```python
def default_repo() -> Any: ...
```

프로세스에서 최대 한 번 생성한 분석 Repository를 lru_cache로 재사용합니다. API 기본 팩터리로 사용됩니다.

선언·진입 조건: `lru_cache(maxsize=1)`.

직접 연결: [open_analysis_repository](#common-dbconn-py-open_analysis_repository-75).


<a id="common-dbconn-py-_host-90"></a>
#### `_host`

<!-- source-symbol: common/dbconn.py:90:_host -->
[dbconn.py](../../backend/analysis/common/dbconn.py#L90)

```python
def _host(url: str) -> str: ...
```

SQLite 주소는 그대로, 그 외 주소는 사용자 정보 앞부분을 제외한 호스트 표시 문자열로 변환합니다. 일반 URL 파서가 아닌 문자열 분리 기반 안내 함수입니다.

호출하는 코드: [describe](#common-dbconn-py-describe-96).


<a id="common-dbconn-py-describe-96"></a>
#### `describe`

<!-- source-symbol: common/dbconn.py:96:describe -->
[dbconn.py](../../backend/analysis/common/dbconn.py#L96)

```python
def describe() -> str: ...
```

현재 시장 DB와 별도 결과 DB의 표시 위치를 문자열로 반환합니다. 시장 주소는 _host로 축약하지만 별도 결과 주소는 그대로 덧붙이므로 모든 구성에서 비밀값이 자동 제거된다고 가정하지 않습니다.

직접 연결: [database_url](#common-dbconn-py-database_url-27), [_host](#common-dbconn-py-_host-90), [results_url](#common-dbconn-py-results_url-40).

호출하는 코드: [health](api_구현보고서.md#api-routers-meta-py-health-18).


<a id="file-common-jsonio-py"></a>
### common/jsonio.py


<a id="common-jsonio-py-load_jsonc-15"></a>
#### `load_jsonc`

<!-- source-symbol: common/jsonio.py:15:load_jsonc -->
[jsonio.py](../../backend/analysis/common/jsonio.py#L15)

```python
def load_jsonc(path: str | Path) -> Any: ...
```

파일을 읽고 문자열 안의 내용은 보존하면서 //·/* */ 주석과 마지막 쉼표를 제거한 뒤 JSON으로 파싱합니다. 파일·문법 오류는 호출자에게 전달됩니다.

호출하는 코드: [load_request](eval_구현보고서.md#eval-run_scenarios-py-load_request-45), [main](executor_구현보고서.md#executor-cli-py-main-27).


<a id="common-jsonio-py-load_json-23"></a>
#### `load_json`

<!-- source-symbol: common/jsonio.py:23:load_json -->
[jsonio.py](../../backend/analysis/common/jsonio.py#L23)

```python
def load_json(path: str | Path) -> Any: ...
```

UTF-8 파일을 JSON 객체로 읽어 반환합니다. 파일이 없을 때 기본값을 반환하는 기능은 JsonStore.read가 담당합니다.

<details>
<summary>호출하는 코드</summary>

[StubLlm.complete_json](#common-llm-py-StubLlm-complete_json-117), [OpenAiLlm._call](#common-llm-py-OpenAiLlm-_call-238), [JsonStore.read](#common-store-py-JsonStore-read-43), [JsonStore.validate](#common-store-py-JsonStore-validate-49), [RequestStore.list](#common-store-py-RequestStore-list-172), [PaperStore.list](#common-store-py-PaperStore-list-247), [load_request](eval_구현보고서.md#eval-run_scenarios-py-load_request-45), [main](executor_구현보고서.md#executor-cli-py-main-27).

</details>


<a id="common-jsonio-py-_default-27"></a>
#### `_default`

<!-- source-symbol: common/jsonio.py:27:_default -->
[jsonio.py](../../backend/analysis/common/jsonio.py#L27)

```python
def _default(o: Any) -> Any: ...
```

날짜는 ISO 문자열, Pydantic 모델은 JSON 사전, 배열·스칼라는 tolist 또는 item으로 변환합니다. 지원되지 않는 객체는 str로 바꾸며 JSON 직렬화의 default 콜백으로 사용됩니다.


<a id="common-jsonio-py-dump_json-39"></a>
#### `dump_json`

<!-- source-symbol: common/jsonio.py:39:dump_json -->
[jsonio.py](../../backend/analysis/common/jsonio.py#L39)

```python
def dump_json(obj: Any, path: str | Path) -> Path: ...
```

부모 디렉터리를 생성하고 들여쓰기·한국어 보존으로 JSON 파일을 쓴 뒤 Path를 반환합니다. JsonStore.write와 달리 임시 파일 교체를 사용하지 않는 산출물용 쓰기입니다.

호출하는 코드: [_dump_outputs](executor_구현보고서.md#executor-runner-py-_dump_outputs-59), [run](executor_구현보고서.md#executor-runner-py-run-92).


<a id="common-jsonio-py-canonical_json-46"></a>
#### `canonical_json`

<!-- source-symbol: common/jsonio.py:46:canonical_json -->
[jsonio.py](../../backend/analysis/common/jsonio.py#L46)

```python
def canonical_json(obj: Any) -> str: ...
```

키 정렬과 공백 제거를 적용한 JSON 문자열을 반환합니다. 사전의 삽입 순서가 달라도 같은 내용의 지문·캐시 키를 만들기 위한 정규화입니다.

호출하는 코드: [OpenAiLlm.cache_key](#common-llm-py-OpenAiLlm-cache_key-234), [DialogService.confirm](m1_request_구현보고서.md#m1_request-dialog-py-DialogService-confirm-247), [signature](m1_request_구현보고서.md#m1_request-precheck-py-signature-28).


<a id="common-jsonio-py-sha256_hex-51"></a>
#### `sha256_hex`

<!-- source-symbol: common/jsonio.py:51:sha256_hex -->
[jsonio.py](../../backend/analysis/common/jsonio.py#L51)

```python
def sha256_hex(text: str, n: int | None=None) -> str: ...
```

문자열의 UTF-8 바이트를 SHA-256으로 해시합니다. n이 지정되면 앞 n자리만 반환하며 내용 지문과 식별 키에 사용합니다.

호출하는 코드: [OpenAiLlm.cache_key](#common-llm-py-OpenAiLlm-cache_key-234), [DialogService.confirm](m1_request_구현보고서.md#m1_request-dialog-py-DialogService-confirm-247), [signature](m1_request_구현보고서.md#m1_request-precheck-py-signature-28).


<a id="common-jsonio-py-now_iso-56"></a>
#### `now_iso`

<!-- source-symbol: common/jsonio.py:56:now_iso -->
[jsonio.py](../../backend/analysis/common/jsonio.py#L56)

```python
def now_iso() -> str: ...
```

호스트의 현재 현지 시간과 UTC 오프셋을 초 단위 ISO 문자열로 반환합니다. 문서 작성 시점의 한국 시간 설정을 애플리케이션 코드가 강제한다고 보아서는 안 됩니다.

<details>
<summary>호출하는 코드</summary>

[ProfileStore.save](#common-store-py-ProfileStore-save-141), [Queue.enqueue](executor_구현보고서.md#executor-queue-py-Queue-enqueue-27), [Queue.claim_next](executor_구현보고서.md#executor-queue-py-Queue-claim_next-70), [Queue.finish](executor_구현보고서.md#executor-queue-py-Queue-finish-84), [Queue.request_cancel](executor_구현보고서.md#executor-queue-py-Queue-request_cancel-89), [Queue.recover_stale](executor_구현보고서.md#executor-queue-py-Queue-recover_stale-110), [run](executor_구현보고서.md#executor-runner-py-run-92), [run._run_stage](executor_구현보고서.md#executor-runner-py-run-_run_stage-126), [DialogService.start](m1_request_구현보고서.md#m1_request-dialog-py-DialogService-start-89), [DialogService.answer](m1_request_구현보고서.md#m1_request-dialog-py-DialogService-answer-138), [DialogService._settle_pending](m1_request_구현보고서.md#m1_request-dialog-py-DialogService-_settle_pending-219), [DialogService.skip](m1_request_구현보고서.md#m1_request-dialog-py-DialogService-skip-225), [DialogService.confirm](m1_request_구현보고서.md#m1_request-dialog-py-DialogService-confirm-247), [DialogService._turn](m1_request_구현보고서.md#m1_request-dialog-py-DialogService-_turn-275), [build_results](m5_backtest_report_구현보고서.md#m5_backtest_report-collect-py-build_results-42), [build_doc](m5_backtest_report_구현보고서.md#m5_backtest_report-report-py-build_doc-224).

</details>


<a id="file-common-llm-py"></a>
### common/llm.py


<a id="common-llm-py-LlmClient-complete_json-41"></a>
#### `LlmClient.complete_json`

<!-- source-symbol: common/llm.py:41:LlmClient.complete_json -->
[llm.py](../../backend/analysis/common/llm.py#L41)

```python
def complete_json(self, stage: str, messages: Sequence[Message], *, validator: Validator | None=None, stub_key: str | None=None, batch: int | None=None) -> dict[str, Any]: ...
```

단계 이름·메시지·선택 검증기·stub 키·배치 번호를 받아 JSON 사전을 돌려주는 Protocol 계약입니다. 자체 실행 코드는 없고 StubLlm과 OpenAiLlm이 이 인터페이스를 구현합니다.


<a id="common-llm-py-LlmClient-usage_summary-51"></a>
#### `LlmClient.usage_summary`

<!-- source-symbol: common/llm.py:51:LlmClient.usage_summary -->
[llm.py](../../backend/analysis/common/llm.py#L51)

```python
def usage_summary(self) -> dict[str, Any]: ...
```

호출 횟수·토큰·비용 요약을 반환해야 한다는 Protocol 계약입니다. 구체적 집계는 _Base가 제공합니다.


<a id="common-llm-py-messages_from_prompts-54"></a>
#### `messages_from_prompts`

<!-- source-symbol: common/llm.py:54:messages_from_prompts -->
[llm.py](../../backend/analysis/common/llm.py#L54)

```python
def messages_from_prompts(system: str, user: str) -> list[Message]: ...
```

시스템·사용자 문자열을 두 개의 role/content 메시지 목록으로 변환합니다.

<details>
<summary>호출하는 코드</summary>

[classify._one](m3_selection_구현보고서.md#m3_selection-classify-py-classify-_one-43), [explain](m3_selection_구현보고서.md#m3_selection-explain-py-explain-21), [generate_views](m4_portfolio_구현보고서.md#m4_portfolio-views-py-generate_views-36), [call_interpret](m5_backtest_report_구현보고서.md#m5_backtest_report-report-py-call_interpret-146), [call_market](m5_backtest_report_구현보고서.md#m5_backtest_report-report-py-call_market-161), [call_narrate](m5_backtest_report_구현보고서.md#m5_backtest_report-report-py-call_narrate-167), [generate_report](m5_backtest_report_구현보고서.md#m5_backtest_report-report-py-generate_report-394), [generate_report._redo_interp](m5_backtest_report_구현보고서.md#m5_backtest_report-report-py-generate_report-_redo_interp-410), [generate_report._redo_market](m5_backtest_report_구현보고서.md#m5_backtest_report-report-py-generate_report-_redo_market-417).

</details>


<a id="common-llm-py-parse_json_answer-58"></a>
#### `parse_json_answer`

<!-- source-symbol: common/llm.py:58:parse_json_answer -->
[llm.py](../../backend/analysis/common/llm.py#L58)

```python
def parse_json_answer(text: str) -> dict[str, Any]: ...
```

응답 양끝의 Markdown JSON 코드 펜스를 제거하고 JSON 객체로 파싱합니다. 배열·문자열 같은 JSON 값은 거부하며 이후 도메인 검증은 전달된 validator가 맡습니다.

호출하는 코드: [OpenAiLlm._call](#common-llm-py-OpenAiLlm-_call-238).

명시적으로 발생시키는 예외: `ValueError`. 발생 조건은 위 해설과 소스의 분기를 함께 확인합니다.


<a id="common-llm-py-_Base-__init__-70"></a>
#### `_Base.__init__`

<!-- source-symbol: common/llm.py:70:_Base.__init__ -->
[llm.py](../../backend/analysis/common/llm.py#L70)

```python
def __init__(self, run_dir: Path | None=None) -> None: ...
```

선택 실행 디렉터리와 빈 호출 기록 목록을 초기화합니다.


<a id="common-llm-py-_Base-_save_prompt-74"></a>
#### `_Base._save_prompt`

<!-- source-symbol: common/llm.py:74:_Base._save_prompt -->
[llm.py](../../backend/analysis/common/llm.py#L74)

```python
def _save_prompt(self, stage: str, messages: Sequence[Message], batch: int | None) -> None: ...
```

run_dir이 있으면 단계·배치별 prompts/*.md에 메시지를 기록합니다. 같은 단계·배치 이름으로 다시 호출하면 같은 파일에 덮어씁니다.


<a id="common-llm-py-_Base-usage_summary-85"></a>
#### `_Base.usage_summary`

<!-- source-symbol: common/llm.py:85:_Base.usage_summary -->
[llm.py](../../backend/analysis/common/llm.py#L85)

```python
def usage_summary(self) -> dict[str, Any]: ...
```

메모리에 기록된 호출에서 횟수·캐시 적중·입출력 토큰·비용·단계 이름을 집계한 사전을 반환합니다. 가격 정보가 없는 비용은 합계에서 0으로 취급되므로 정확한 청구액 검증용은 아닙니다.


<a id="common-llm-py-StubLlm-__init__-101"></a>
#### `StubLlm.__init__`

<!-- source-symbol: common/llm.py:101:StubLlm.__init__ -->
[llm.py](../../backend/analysis/common/llm.py#L101)

```python
def __init__(self, answers: dict[str, Any] | None=None, *, stubs_dir: Path | None=None, run_dir: Path | None=None, prefer_smart: bool=True) -> None: ...
```

주입 응답, stub 폴더, 스마트 응답 우선 여부와 순서형 응답 커서를 준비합니다. 여러 스레드가 목록 응답을 중복 소비하지 않도록 Lock을 만듭니다.


<a id="common-llm-py-StubLlm-complete_json-117"></a>
#### `StubLlm.complete_json`

<!-- source-symbol: common/llm.py:117:StubLlm.complete_json -->
[llm.py](../../backend/analysis/common/llm.py#L117)

```python
def complete_json(self, stage: str, messages: Sequence[Message], *, validator: Validator | None=None, stub_key: str | None=None, batch: int | None=None) -> dict[str, Any]: ...
```

단계별 주입 응답을 우선하고 callable·순서형 목록·고정 객체를 지원합니다. 없으면 prefer_smart 설정에 따라 파일 또는 SMART_STUBS를 선택합니다. 응답을 JSON 왕복 복사해 원본 변형을 막고 validator를 호출한 뒤 사용량에 stub 호출을 기록합니다. 응답 소스가 없으면 FileNotFoundError이며 실제 API는 호출하지 않습니다.

직접 연결: [load_json](#common-jsonio-py-load_json-23).

명시적으로 발생시키는 예외: `FileNotFoundError`. 발생 조건은 위 해설과 소스의 분기를 함께 확인합니다.


<a id="common-llm-py-OpenAiLlm-__init__-161"></a>
#### `OpenAiLlm.__init__`

<!-- source-symbol: common/llm.py:161:OpenAiLlm.__init__ -->
[llm.py](../../backend/analysis/common/llm.py#L161)

```python
def __init__(self, settings: LlmSettings, *, run_dir: Path | None=None, cache_dir: Path | None=None, usage_log: Path | None=None, client: Any | None=None, run_id: str | None=None) -> None: ...
```

LLM 설정·캐시·사용량 로그·선택 클라이언트·실행 ID를 보관합니다. 기록용 잠금과 동시 실제 호출 수를 제한하는 BoundedSemaphore를 생성합니다.

직접 연결: [llm_cache_dir](#paths-py-llm_cache_dir-31).


<a id="common-llm-py-OpenAiLlm-_family-182"></a>
#### `OpenAiLlm._family`

<!-- source-symbol: common/llm.py:182:OpenAiLlm._family -->
[llm.py](../../backend/analysis/common/llm.py#L182)

```python
def _family(stage: str) -> str: ...
```

단계 이름의 날짜 이후 꼬리표를 제거합니다. 예를 들어 날짜별 뉴스 뷰 호출이 공통 09_views_news 설정을 재사용하게 합니다.

선언·진입 조건: `staticmethod`.

호출하는 코드: [OpenAiLlm._setting](#common-llm-py-OpenAiLlm-_setting-186).


<a id="common-llm-py-OpenAiLlm-_setting-186"></a>
#### `OpenAiLlm._setting`

<!-- source-symbol: common/llm.py:186:OpenAiLlm._setting -->
[llm.py](../../backend/analysis/common/llm.py#L186)

```python
def _setting(self, stage: str, name: str) -> Any: ...
```

정확한 단계명 override, 날짜를 뺀 단계군 override, 전역 기본값 순으로 지정 설정 항목을 고릅니다. 실제 전송 모델은 _call에서 settings.model을 사용합니다.

직접 연결: [OpenAiLlm._family](#common-llm-py-OpenAiLlm-_family-182).

호출하는 코드: [OpenAiLlm._call](#common-llm-py-OpenAiLlm-_call-238).


<a id="common-llm-py-OpenAiLlm-_client_openai-194"></a>
#### `OpenAiLlm._client_openai`

<!-- source-symbol: common/llm.py:194:OpenAiLlm._client_openai -->
[llm.py](../../backend/analysis/common/llm.py#L194)

```python
def _client_openai(self) -> Any: ...
```

주입 클라이언트가 없으면 잠금 안에서 API 키 환경변수를 읽고 OpenAI 클라이언트를 한 번 생성합니다. 키가 없으면 LLM_CONFIG 오류이며 내용 보정 재시도를 하지 않습니다.

직접 연결: [LlmOutputError](#errors-py-LlmOutputError-50).

호출하는 코드: [OpenAiLlm._call](#common-llm-py-OpenAiLlm-_call-238).

명시적으로 발생시키는 예외: `LlmOutputError`. 발생 조건은 위 해설과 소스의 분기를 함께 확인합니다.


<a id="common-llm-py-OpenAiLlm-_backoff-206"></a>
#### `OpenAiLlm._backoff`

<!-- source-symbol: common/llm.py:206:OpenAiLlm._backoff -->
[llm.py](../../backend/analysis/common/llm.py#L206)

```python
def _backoff(self, attempt: int, exc: Any) -> float: ...
```

지수 증가 대기와 0.5~1.5배 지터를 계산하고 Retry-After가 더 크면 그 값을 적용합니다. 기본 대기값을 cap으로 제한한 뒤 지터·서버 값을 적용하므로 최종 대기는 설정 cap을 넘을 수 있습니다.

호출하는 코드: [OpenAiLlm._call](#common-llm-py-OpenAiLlm-_call-238).


<a id="common-llm-py-OpenAiLlm-_cost_usd-219"></a>
#### `OpenAiLlm._cost_usd`

<!-- source-symbol: common/llm.py:219:OpenAiLlm._cost_usd -->
[llm.py](../../backend/analysis/common/llm.py#L219)

```python
def _cost_usd(self, model: str, prompt: int, cached: int, completion: int, cache_write: int=0) -> float | None: ...
```

코드에 저장된 모델별 백만 토큰 단가로 일반 입력·캐시 입력·캐시 쓰기·출력 비용을 계산합니다. 모델 단가가 없으면 기본 모델 단가를 시도하고 그래도 없으면 None입니다. 이 표는 저장소 설정값이며 현재 공개 요금을 조회한 결과가 아닙니다.

호출하는 코드: [OpenAiLlm._call](#common-llm-py-OpenAiLlm-_call-238).


<a id="common-llm-py-OpenAiLlm-cache_key-234"></a>
#### `OpenAiLlm.cache_key`

<!-- source-symbol: common/llm.py:234:OpenAiLlm.cache_key -->
[llm.py](../../backend/analysis/common/llm.py#L234)

```python
def cache_key(self, stage: str, messages: Sequence[Message]) -> str: ...
```

settings.model·전체 단계명·정규화된 전체 대화를 합쳐 24자리 해시를 반환합니다. temperature 등 나머지 설정 전체를 키에 넣지는 않습니다.

직접 연결: [sha256_hex](#common-jsonio-py-sha256_hex-51), [canonical_json](#common-jsonio-py-canonical_json-46).

호출하는 코드: [OpenAiLlm._call](#common-llm-py-OpenAiLlm-_call-238).


<a id="common-llm-py-OpenAiLlm-_call-238"></a>
#### `OpenAiLlm._call`

<!-- source-symbol: common/llm.py:238:OpenAiLlm._call -->
[llm.py](../../backend/analysis/common/llm.py#L238)

```python
def _call(self, stage: str, messages: Sequence[Message], batch: int | None) -> dict[str, Any]: ...
```

캐시 적중이면 저장 JSON을 즉시 읽습니다. 미적중이면 세마포어 안에서 실제 chat completion을 보내고 전송 오류에 백오프 재시도, 응답 잘림에 토큰 상한 증가를 적용합니다. 토큰·비용·원문을 기록한 뒤 JSON을 파싱해 캐시에 저장합니다. 캐시 저장은 도메인 validator 실행보다 앞서므로 캐시 적중 응답도 complete_json에서 재검증합니다.

직접 연결: [OpenAiLlm.cache_key](#common-llm-py-OpenAiLlm-cache_key-234), [load_json](#common-jsonio-py-load_json-23), [OpenAiLlm._client_openai](#common-llm-py-OpenAiLlm-_client_openai-194), [OpenAiLlm._setting](#common-llm-py-OpenAiLlm-_setting-186), [OpenAiLlm._backoff](#common-llm-py-OpenAiLlm-_backoff-206), [OpenAiLlm._cost_usd](#common-llm-py-OpenAiLlm-_cost_usd-219), [LlmOutputError](#errors-py-LlmOutputError-50), [parse_json_answer](#common-llm-py-parse_json_answer-58).

호출하는 코드: [OpenAiLlm.complete_json](#common-llm-py-OpenAiLlm-complete_json-329).

명시적으로 발생시키는 예외: `LlmOutputError`. 발생 조건은 위 해설과 소스의 분기를 함께 확인합니다.


<a id="common-llm-py-OpenAiLlm-complete_json-329"></a>
#### `OpenAiLlm.complete_json`

<!-- source-symbol: common/llm.py:329:OpenAiLlm.complete_json -->
[llm.py](../../backend/analysis/common/llm.py#L329)

```python
def complete_json(self, stage: str, messages: Sequence[Message], *, validator: Validator | None=None, stub_key: str | None=None, batch: int | None=None) -> dict[str, Any]: ...
```

프롬프트를 저장하고 _call 응답을 validator로 검사합니다. 형식·검증 실패 등을 받으면 오류 피드백 메시지를 덧붙여 한 번 더 시도하며, 두 번째 실패는 LlmOutputError로 올립니다. _call 내부 전송 재시도와 이 내용 보정 재시도는 서로 다른 층입니다.

직접 연결: [OpenAiLlm._call](#common-llm-py-OpenAiLlm-_call-238), [LlmOutputError](#errors-py-LlmOutputError-50).

명시적으로 발생시키는 예외: `LlmOutputError`. 발생 조건은 위 해설과 소스의 분기를 함께 확인합니다.


<a id="common-llm-py-make_llm-363"></a>
#### `make_llm`

<!-- source-symbol: common/llm.py:363:make_llm -->
[llm.py](../../backend/analysis/common/llm.py#L363)

```python
def make_llm(settings: LlmSettings, *, run_dir: Path | None=None, run_id: str | None=None, stub_answers: dict[str, Any] | None=None) -> LlmClient: ...
```

settings.mode가 api면 OpenAiLlm, 나머지면 StubLlm을 반환합니다. 실제 API 호출은 생성 이후 complete_json에서 발생합니다.

직접 연결: [OpenAiLlm](#common-llm-py-OpenAiLlm-160), [StubLlm](#common-llm-py-StubLlm-98).

호출하는 코드: [Services.llm](api_구현보고서.md#api-services-py-Services-llm-45), [main](executor_구현보고서.md#executor-cli-py-main-27), [execute_run](executor_구현보고서.md#executor-worker-py-execute_run-38), [refresh_all_papers](m6_tracking_구현보고서.md#m6_tracking-paper-py-refresh_all_papers-555).


<a id="file-common-prompts-py"></a>
### common/prompts.py


<a id="common-prompts-py-render_template-10"></a>
#### `render_template`

<!-- source-symbol: common/prompts.py:10:render_template -->
[prompts.py](../../backend/analysis/common/prompts.py#L10)

```python
def render_template(template: str, **vars_: object) -> str: ...
```

템플릿의 {{이름}}을 전달받은 값의 문자열로 치환합니다. 전달되지 않은 자리표시자는 그대로 남으며 템플릿 문법이나 누락 여부를 별도로 검증하지 않습니다.

호출하는 코드: [load_prompts](#common-prompts-py-load_prompts-17).


<a id="common-prompts-py-load_prompts-17"></a>
#### `load_prompts`

<!-- source-symbol: common/prompts.py:17:load_prompts -->
[prompts.py](../../backend/analysis/common/prompts.py#L17)

```python
def load_prompts(stage_dir: str, *, root: Path | None=None, **vars_: object) -> tuple[str, str]: ...
```

단계 디렉터리에서 system_prompt.md와 user_prompt.md를 읽어 쌍으로 반환합니다. 사용자 프롬프트에만 변수를 치환하여 시스템 프롬프트는 고정 텍스트로 유지합니다.

직접 연결: [render_template](#common-prompts-py-render_template-10).

<details>
<summary>호출하는 코드</summary>

[propose](m1_request_구현보고서.md#m1_request-revision-py-propose-80), [classify._one](m3_selection_구현보고서.md#m3_selection-classify-py-classify-_one-43), [explain](m3_selection_구현보고서.md#m3_selection-explain-py-explain-21), [build_messages](m3_selection_구현보고서.md#m3_selection-intent-py-build_messages-66), [generate_views](m4_portfolio_구현보고서.md#m4_portfolio-views-py-generate_views-36), [call_interpret](m5_backtest_report_구현보고서.md#m5_backtest_report-report-py-call_interpret-146), [call_market](m5_backtest_report_구현보고서.md#m5_backtest_report-report-py-call_market-161), [call_narrate](m5_backtest_report_구현보고서.md#m5_backtest_report-report-py-call_narrate-167), [generate_report](m5_backtest_report_구현보고서.md#m5_backtest_report-report-py-generate_report-394), [generate_report._redo_interp](m5_backtest_report_구현보고서.md#m5_backtest_report-report-py-generate_report-_redo_interp-410), [generate_report._redo_market](m5_backtest_report_구현보고서.md#m5_backtest_report-report-py-generate_report-_redo_market-417).

</details>


<a id="file-common-store-py"></a>
### common/store.py


<a id="common-store-py-JsonStore-__init__-35"></a>
#### `JsonStore.__init__`

<!-- source-symbol: common/store.py:35:JsonStore.__init__ -->
[store.py](../../backend/analysis/common/store.py#L35)

```python
def __init__(self, root: Path | None=None, *, schemas_dir: Path=STORE_SCHEMAS) -> None: ...
```

저장 루트와 JSON Schema 경로를 정하고 루트 디렉터리를 생성합니다.

직접 연결: [store_dir](#paths-py-store_dir-17).


<a id="common-store-py-JsonStore-path-40"></a>
#### `JsonStore.path`

<!-- source-symbol: common/store.py:40:JsonStore.path -->
[store.py](../../backend/analysis/common/store.py#L40)

```python
def path(self, rel: str) -> Path: ...
```

저장 루트에 상대경로를 붙인 Path를 반환합니다. 경로 안전성 검사나 파일 접근은 이 함수에서 수행하지 않습니다.

호출하는 코드: [JsonStore.read](#common-store-py-JsonStore-read-43), [JsonStore.write](#common-store-py-JsonStore-write-55), [JsonStore.append_jsonl](#common-store-py-JsonStore-append_jsonl-70), [JsonStore.read_jsonl](#common-store-py-JsonStore-read_jsonl-78).


<a id="common-store-py-JsonStore-read-43"></a>
#### `JsonStore.read`

<!-- source-symbol: common/store.py:43:JsonStore.read -->
[store.py](../../backend/analysis/common/store.py#L43)

```python
def read(self, rel: str, default: Any=None) -> Any: ...
```

파일이 있으면 JSON을 읽고 없으면 전달된 default를 반환합니다. 잘못된 JSON은 예외로 전달됩니다.

직접 연결: [JsonStore.path](#common-store-py-JsonStore-path-40), [load_json](#common-jsonio-py-load_json-23).


<a id="common-store-py-JsonStore-validate-49"></a>
#### `JsonStore.validate`

<!-- source-symbol: common/store.py:49:JsonStore.validate -->
[store.py](../../backend/analysis/common/store.py#L49)

```python
def validate(self, obj: Any, schema_name: str) -> None: ...
```

지정 schema_name의 JSON Schema를 Draft 2020-12 검증기로 적용합니다. jsonschema 패키지가 설치되지 않았으면 검증을 생략합니다.

직접 연결: [load_json](#common-jsonio-py-load_json-23).

호출하는 코드: [JsonStore.write](#common-store-py-JsonStore-write-55).


<a id="common-store-py-JsonStore-write-55"></a>
#### `JsonStore.write`

<!-- source-symbol: common/store.py:55:JsonStore.write -->
[store.py](../../backend/analysis/common/store.py#L55)

```python
def write(self, rel: str, obj: Any, *, schema: str | None=None, model: type[BaseModel] | None=None) -> Path: ...
```

Pydantic 객체를 JSON 사전으로 바꾸고 지정된 모델·스키마 검증을 수행합니다. 같은 폴더의 임시 파일에 쓴 뒤 os.replace로 교체하고 저장 경로를 반환합니다. 단일 파일 교체의 원자성과 여러 파일을 아우르는 트랜잭션은 다르며 이 함수가 자동으로 잠금을 잡지는 않습니다.

직접 연결: [JsonStore.validate](#common-store-py-JsonStore-validate-49), [JsonStore.path](#common-store-py-JsonStore-path-40).


<a id="common-store-py-JsonStore-append_jsonl-70"></a>
#### `JsonStore.append_jsonl`

<!-- source-symbol: common/store.py:70:JsonStore.append_jsonl -->
[store.py](../../backend/analysis/common/store.py#L70)

```python
def append_jsonl(self, rel: str, obj: Any) -> None: ...
```

객체를 한 줄 JSON으로 직렬화해 파일 끝에 추가합니다. 모델 검증·파일 잠금·다중 기록 트랜잭션은 이 메서드 내부에 없습니다.

직접 연결: [JsonStore.path](#common-store-py-JsonStore-path-40).


<a id="common-store-py-JsonStore-read_jsonl-78"></a>
#### `JsonStore.read_jsonl`

<!-- source-symbol: common/store.py:78:JsonStore.read_jsonl -->
[store.py](../../backend/analysis/common/store.py#L78)

```python
def read_jsonl(self, rel: str) -> list[Any]: ...
```

JSONL의 비어 있지 않은 줄을 객체 목록으로 읽고 파일이 없으면 빈 목록을 반환합니다. 중간에 깨진 줄이 있으면 파싱 예외가 발생합니다.

직접 연결: [JsonStore.path](#common-store-py-JsonStore-path-40).


<a id="common-store-py-JsonStore-locked-85"></a>
#### `JsonStore.locked`

<!-- source-symbol: common/store.py:85:JsonStore.locked -->
[store.py](../../backend/analysis/common/store.py#L85)

```python
def locked(self, name: str) -> Iterator[None]: ...
```

.locks 아래 이름별 파일을 열고 fcntl.flock 배타 잠금을 잡는 컨텍스트 관리자입니다. finally에서 잠금을 해제하며 사용자가 이 블록 안에서 읽기-수정-쓰기를 묶어야 합니다.

선언·진입 조건: `contextmanager`.


<a id="common-store-py-new_request_id-98"></a>
#### `new_request_id`

<!-- source-symbol: common/store.py:98:new_request_id -->
[store.py](../../backend/analysis/common/store.py#L98)

```python
def new_request_id(now: dt.datetime | None=None) -> str: ...
```

날짜·시각과 임의 2바이트 토큰으로 req_ 접두사의 요청 ID를 반환합니다.

호출하는 코드: [DialogService.start](m1_request_구현보고서.md#m1_request-dialog-py-DialogService-start-89).


<a id="common-store-py-new_run_id-103"></a>
#### `new_run_id`

<!-- source-symbol: common/store.py:103:new_run_id -->
[store.py](../../backend/analysis/common/store.py#L103)

```python
def new_run_id(now: dt.datetime | None=None) -> str: ...
```

날짜·시각과 임의 토큰으로 run_ 접두사의 실행 ID를 반환합니다. 내용 기반 지문과는 별개의 식별자입니다.

호출하는 코드: [retry_run](api_구현보고서.md#api-routers-runs-py-retry_run-84), [main](executor_구현보고서.md#executor-cli-py-main-27), [DialogService.confirm](m1_request_구현보고서.md#m1_request-dialog-py-DialogService-confirm-247).


<a id="common-store-py-new_paper_id-108"></a>
#### `new_paper_id`

<!-- source-symbol: common/store.py:108:new_paper_id -->
[store.py](../../backend/analysis/common/store.py#L108)

```python
def new_paper_id(now: dt.datetime | None=None) -> str: ...
```

날짜와 임의 토큰으로 paper_ 접두사의 모의투자 ID를 반환합니다.

호출하는 코드: [PaperService.create](m6_tracking_구현보고서.md#m6_tracking-paper-py-PaperService-create-333).


<a id="common-store-py-ProfileStore-__init__-119"></a>
#### `ProfileStore.__init__`

<!-- source-symbol: common/store.py:119:ProfileStore.__init__ -->
[store.py](../../backend/analysis/common/store.py#L119)

```python
def __init__(self, store: JsonStore) -> None: ...
```

프로필 읽기·쓰기에 사용할 JsonStore를 보관합니다.


<a id="common-store-py-ProfileStore-load-122"></a>
#### `ProfileStore.load`

<!-- source-symbol: common/store.py:122:ProfileStore.load -->
[store.py](../../backend/analysis/common/store.py#L122)

```python
def load(self) -> dict[str, Any] | None: ...
```

profile.json 전체 문서 또는 미등록 시 None을 반환합니다.

호출하는 코드: [ProfileStore.current](#common-store-py-ProfileStore-current-125), [ProfileStore.version](#common-store-py-ProfileStore-version-132), [ProfileStore.save](#common-store-py-ProfileStore-save-141).


<a id="common-store-py-ProfileStore-current-125"></a>
#### `ProfileStore.current`

<!-- source-symbol: common/store.py:125:ProfileStore.current -->
[store.py](../../backend/analysis/common/store.py#L125)

```python
def current(self) -> dict[str, Any] | None: ...
```

current_version에 해당하는 프로필 버전을 반환합니다. 프로필이 없으면 None입니다.

직접 연결: [ProfileStore.load](#common-store-py-ProfileStore-load-122).


<a id="common-store-py-ProfileStore-version-132"></a>
#### `ProfileStore.version`

<!-- source-symbol: common/store.py:132:ProfileStore.version -->
[store.py](../../backend/analysis/common/store.py#L132)

```python
def version(self, version: int) -> dict[str, Any]: ...
```

지정 버전 번호의 프로필을 검색합니다. 프로필이나 해당 버전이 없으면 NotFound입니다.

직접 연결: [ProfileStore.load](#common-store-py-ProfileStore-load-122), [NotFound](#errors-py-NotFound-73).

명시적으로 발생시키는 예외: `NotFound`. 발생 조건은 위 해설과 소스의 분기를 함께 확인합니다.


<a id="common-store-py-ProfileStore-save-141"></a>
#### `ProfileStore.save`

<!-- source-symbol: common/store.py:141:ProfileStore.save -->
[store.py](../../backend/analysis/common/store.py#L141)

```python
def save(self, fields: dict[str, Any], *, note: str | None=None) -> dict[str, Any]: ...
```

profile 잠금 안에서 버전을 증가시키고 생성시각·메모·조건을 versions에 추가한 뒤 profile 스키마로 저장합니다. 새 버전을 반환하며 기존 버전은 보존합니다.

직접 연결: [ProfileStore.load](#common-store-py-ProfileStore-load-122), [now_iso](#common-jsonio-py-now_iso-56).


<a id="common-store-py-RequestStore-__init__-157"></a>
#### `RequestStore.__init__`

<!-- source-symbol: common/store.py:157:RequestStore.__init__ -->
[store.py](../../backend/analysis/common/store.py#L157)

```python
def __init__(self, store: JsonStore) -> None: ...
```

요청 저장에 사용할 공통 JsonStore를 보관합니다.


<a id="common-store-py-RequestStore-rel-160"></a>
#### `RequestStore.rel`

<!-- source-symbol: common/store.py:160:RequestStore.rel -->
[store.py](../../backend/analysis/common/store.py#L160)

```python
def rel(self, request_id: str) -> str: ...
```

요청 ID를 requests/<ID>.json 상대경로로 변환합니다.

호출하는 코드: [RequestStore.load](#common-store-py-RequestStore-load-163), [RequestStore.save](#common-store-py-RequestStore-save-169).


<a id="common-store-py-RequestStore-load-163"></a>
#### `RequestStore.load`

<!-- source-symbol: common/store.py:163:RequestStore.load -->
[store.py](../../backend/analysis/common/store.py#L163)

```python
def load(self, request_id: str) -> AnalysisRequestDoc: ...
```

요청 파일을 AnalysisRequestDoc으로 검증해 반환합니다. 파일이 없으면 NotFound입니다.

직접 연결: [RequestStore.rel](#common-store-py-RequestStore-rel-160), [NotFound](#errors-py-NotFound-73).

명시적으로 발생시키는 예외: `NotFound`. 발생 조건은 위 해설과 소스의 분기를 함께 확인합니다.


<a id="common-store-py-RequestStore-save-169"></a>
#### `RequestStore.save`

<!-- source-symbol: common/store.py:169:RequestStore.save -->
[store.py](../../backend/analysis/common/store.py#L169)

```python
def save(self, doc: AnalysisRequestDoc) -> Path: ...
```

AnalysisRequestDoc을 모델 검증 후 해당 요청 파일에 저장하고 Path를 반환합니다. 이 경로는 analysis_request JSON Schema 파일 대신 Pydantic 모델 검증을 사용합니다.

직접 연결: [RequestStore.rel](#common-store-py-RequestStore-rel-160).


<a id="common-store-py-RequestStore-list-172"></a>
#### `RequestStore.list`

<!-- source-symbol: common/store.py:172:RequestStore.list -->
[store.py](../../backend/analysis/common/store.py#L172)

```python
def list(self) -> list[AnalysisRequestDoc]: ...
```

requests의 req_*.json을 모두 모델로 읽고 created_at 오름차순으로 반환합니다. 저장 문서 하나의 검증 실패도 호출자에게 전달됩니다.

직접 연결: [load_json](#common-jsonio-py-load_json-23).


<a id="common-store-py-RequestStore-locked-180"></a>
#### `RequestStore.locked`

<!-- source-symbol: common/store.py:180:RequestStore.locked -->
[store.py](../../backend/analysis/common/store.py#L180)

```python
def locked(self, request_id: str) -> Iterator[None]: ...
```

request_<ID>라는 이름의 공통 파일 잠금으로 특정 요청의 대화 갱신을 직렬화합니다.

선언·진입 조건: `contextmanager`.


<a id="common-store-py-RunIndex-__init__-191"></a>
#### `RunIndex.__init__`

<!-- source-symbol: common/store.py:191:RunIndex.__init__ -->
[store.py](../../backend/analysis/common/store.py#L191)

```python
def __init__(self, store: JsonStore) -> None: ...
```

runs.json 접근용 JsonStore를 보관합니다.


<a id="common-store-py-RunIndex-load-194"></a>
#### `RunIndex.load`

<!-- source-symbol: common/store.py:194:RunIndex.load -->
[store.py](../../backend/analysis/common/store.py#L194)

```python
def load(self) -> list[RunIndexEntry]: ...
```

runs.json의 runs 배열을 RunIndexEntry 목록으로 검증해 반환합니다. 파일이 없으면 빈 목록입니다.

호출하는 코드: [RunIndex.get](#common-store-py-RunIndex-get-202), [RunIndex.upsert](#common-store-py-RunIndex-upsert-208), [RunIndex.update](#common-store-py-RunIndex-update-214).


<a id="common-store-py-RunIndex-save-198"></a>
#### `RunIndex.save`

<!-- source-symbol: common/store.py:198:RunIndex.save -->
[store.py](../../backend/analysis/common/store.py#L198)

```python
def save(self, runs: list[RunIndexEntry]) -> None: ...
```

queued_at 기준 안정 정렬한 목록을 schema_version과 함께 runs.json에 씁니다. 함수 자체는 잠금을 잡지 않으므로 큐의 갱신 경로에서 locked 블록으로 감쌉니다.

호출하는 코드: [RunIndex.upsert](#common-store-py-RunIndex-upsert-208), [RunIndex.update](#common-store-py-RunIndex-update-214).


<a id="common-store-py-RunIndex-get-202"></a>
#### `RunIndex.get`

<!-- source-symbol: common/store.py:202:RunIndex.get -->
[store.py](../../backend/analysis/common/store.py#L202)

```python
def get(self, run_id: str) -> RunIndexEntry: ...
```

실행 ID가 일치하는 색인 항목을 반환하고 없으면 NotFound를 발생시킵니다.

직접 연결: [RunIndex.load](#common-store-py-RunIndex-load-194), [NotFound](#errors-py-NotFound-73).

명시적으로 발생시키는 예외: `NotFound`. 발생 조건은 위 해설과 소스의 분기를 함께 확인합니다.


<a id="common-store-py-RunIndex-upsert-208"></a>
#### `RunIndex.upsert`

<!-- source-symbol: common/store.py:208:RunIndex.upsert -->
[store.py](../../backend/analysis/common/store.py#L208)

```python
def upsert(self, entry: RunIndexEntry) -> None: ...
```

runs 잠금 안에서 같은 ID를 제거하고 새 항목으로 교체·저장합니다.

직접 연결: [RunIndex.load](#common-store-py-RunIndex-load-194), [RunIndex.save](#common-store-py-RunIndex-save-198).


<a id="common-store-py-RunIndex-update-214"></a>
#### `RunIndex.update`

<!-- source-symbol: common/store.py:214:RunIndex.update -->
[store.py](../../backend/analysis/common/store.py#L214)

```python
def update(self, run_id: str, **changes: Any) -> RunIndexEntry: ...
```

runs 잠금 안에서 지정 실행을 model_copy(update=...)로 갱신해 저장하고 갱신 항목을 반환합니다. 이 복사 방식은 모델의 전체 재검증과 같지 않습니다.

직접 연결: [RunIndex.load](#common-store-py-RunIndex-load-194), [RunIndex.save](#common-store-py-RunIndex-save-198), [NotFound](#errors-py-NotFound-73).

명시적으로 발생시키는 예외: `NotFound`. 발생 조건은 위 해설과 소스의 분기를 함께 확인합니다.


<a id="common-store-py-RunIndex-locked-225"></a>
#### `RunIndex.locked`

<!-- source-symbol: common/store.py:225:RunIndex.locked -->
[store.py](../../backend/analysis/common/store.py#L225)

```python
def locked(self) -> Iterator[None]: ...
```

runs라는 공통 이름의 잠금을 제공해 FIFO 등록·선점 등 복합 연산을 보호합니다.

선언·진입 조건: `contextmanager`.


<a id="common-store-py-PaperStore-__init__-232"></a>
#### `PaperStore.__init__`

<!-- source-symbol: common/store.py:232:PaperStore.__init__ -->
[store.py](../../backend/analysis/common/store.py#L232)

```python
def __init__(self, store: JsonStore) -> None: ...
```

모의투자 파일과 JSONL 기록용 JsonStore를 보관합니다.


<a id="common-store-py-PaperStore-rel-235"></a>
#### `PaperStore.rel`

<!-- source-symbol: common/store.py:235:PaperStore.rel -->
[store.py](../../backend/analysis/common/store.py#L235)

```python
def rel(self, paper_id: str, name: str='portfolio.json') -> str: ...
```

paper/<ID>/<파일명> 경로를 반환합니다. 파일명 기본값은 portfolio.json입니다.

호출하는 코드: [PaperStore.load](#common-store-py-PaperStore-load-238), [PaperStore.save](#common-store-py-PaperStore-save-244), [PaperStore.append_snapshot](#common-store-py-PaperStore-append_snapshot-253), [PaperStore.snapshots](#common-store-py-PaperStore-snapshots-256), [PaperStore.append_rebalance](#common-store-py-PaperStore-append_rebalance-259), [PaperStore.rebalances](#common-store-py-PaperStore-rebalances-262).


<a id="common-store-py-PaperStore-load-238"></a>
#### `PaperStore.load`

<!-- source-symbol: common/store.py:238:PaperStore.load -->
[store.py](../../backend/analysis/common/store.py#L238)

```python
def load(self, paper_id: str) -> dict[str, Any]: ...
```

모의투자 portfolio.json을 읽고 없으면 NotFound입니다. 로드 시 별도 Pydantic 검증은 하지 않습니다.

직접 연결: [PaperStore.rel](#common-store-py-PaperStore-rel-235), [NotFound](#errors-py-NotFound-73).

명시적으로 발생시키는 예외: `NotFound`. 발생 조건은 위 해설과 소스의 분기를 함께 확인합니다.


<a id="common-store-py-PaperStore-save-244"></a>
#### `PaperStore.save`

<!-- source-symbol: common/store.py:244:PaperStore.save -->
[store.py](../../backend/analysis/common/store.py#L244)

```python
def save(self, doc: dict[str, Any]) -> Path: ...
```

paper_portfolio JSON Schema로 검증한 설정·상태를 원자적 파일 교체로 저장하고 Path를 반환합니다.

직접 연결: [PaperStore.rel](#common-store-py-PaperStore-rel-235).


<a id="common-store-py-PaperStore-list-247"></a>
#### `PaperStore.list`

<!-- source-symbol: common/store.py:247:PaperStore.list -->
[store.py](../../backend/analysis/common/store.py#L247)

```python
def list(self) -> list[dict[str, Any]]: ...
```

paper_*/portfolio.json을 경로순으로 읽어 목록으로 반환합니다. 최신순 정렬은 PaperService.list가 수행합니다.

직접 연결: [load_json](#common-jsonio-py-load_json-23).


<a id="common-store-py-PaperStore-append_snapshot-253"></a>
#### `PaperStore.append_snapshot`

<!-- source-symbol: common/store.py:253:PaperStore.append_snapshot -->
[store.py](../../backend/analysis/common/store.py#L253)

```python
def append_snapshot(self, paper_id: str, snap: dict[str, Any]) -> None: ...
```

snapshots.jsonl에 하루 평가 스냅샷을 추가합니다. 이 경로에서는 paper_snapshot 스키마를 직접 적용하지 않습니다.

직접 연결: [PaperStore.rel](#common-store-py-PaperStore-rel-235).


<a id="common-store-py-PaperStore-snapshots-256"></a>
#### `PaperStore.snapshots`

<!-- source-symbol: common/store.py:256:PaperStore.snapshots -->
[store.py](../../backend/analysis/common/store.py#L256)

```python
def snapshots(self, paper_id: str) -> list[dict[str, Any]]: ...
```

해당 모의투자의 스냅샷 JSONL을 읽습니다. 날짜 중복 정리는 PaperService._snapshots가 수행합니다.

직접 연결: [PaperStore.rel](#common-store-py-PaperStore-rel-235).


<a id="common-store-py-PaperStore-append_rebalance-259"></a>
#### `PaperStore.append_rebalance`

<!-- source-symbol: common/store.py:259:PaperStore.append_rebalance -->
[store.py](../../backend/analysis/common/store.py#L259)

```python
def append_rebalance(self, paper_id: str, rec: dict[str, Any]) -> None: ...
```

rebalances.jsonl에 최초 매수·적립·리밸런싱 기록을 추가합니다. rebalance_record 스키마를 직접 적용하지 않습니다.

직접 연결: [PaperStore.rel](#common-store-py-PaperStore-rel-235).


<a id="common-store-py-PaperStore-rebalances-262"></a>
#### `PaperStore.rebalances`

<!-- source-symbol: common/store.py:262:PaperStore.rebalances -->
[store.py](../../backend/analysis/common/store.py#L262)

```python
def rebalances(self, paper_id: str) -> list[dict[str, Any]]: ...
```

모의투자의 거래·리밸런싱 원장을 저장된 줄 순서대로 반환합니다.

직접 연결: [PaperStore.rel](#common-store-py-PaperStore-rel-235).


<a id="common-store-py-ComparisonStore-__init__-267"></a>
#### `ComparisonStore.__init__`

<!-- source-symbol: common/store.py:267:ComparisonStore.__init__ -->
[store.py](../../backend/analysis/common/store.py#L267)

```python
def __init__(self, store: JsonStore) -> None: ...
```

수정안 비교 문서용 JsonStore를 보관합니다.


<a id="common-store-py-ComparisonStore-rel-270"></a>
#### `ComparisonStore.rel`

<!-- source-symbol: common/store.py:270:ComparisonStore.rel -->
[store.py](../../backend/analysis/common/store.py#L270)

```python
def rel(self, comparison_id: str) -> str: ...
```

comparison_id를 comparisons/<ID>.json 경로로 변환합니다.

호출하는 코드: [ComparisonStore.load](#common-store-py-ComparisonStore-load-273), [ComparisonStore.save](#common-store-py-ComparisonStore-save-279).


<a id="common-store-py-ComparisonStore-load-273"></a>
#### `ComparisonStore.load`

<!-- source-symbol: common/store.py:273:ComparisonStore.load -->
[store.py](../../backend/analysis/common/store.py#L273)

```python
def load(self, comparison_id: str) -> dict[str, Any]: ...
```

비교 JSON 문서를 반환하고 없으면 NotFound입니다.

직접 연결: [ComparisonStore.rel](#common-store-py-ComparisonStore-rel-270), [NotFound](#errors-py-NotFound-73).

명시적으로 발생시키는 예외: `NotFound`. 발생 조건은 위 해설과 소스의 분기를 함께 확인합니다.


<a id="common-store-py-ComparisonStore-save-279"></a>
#### `ComparisonStore.save`

<!-- source-symbol: common/store.py:279:ComparisonStore.save -->
[store.py](../../backend/analysis/common/store.py#L279)

```python
def save(self, doc: dict[str, Any]) -> Path: ...
```

comparison_id에 해당하는 비교 JSON을 저장하고 Path를 반환합니다. revision_comparison 스키마 파일이 존재하지만 이 호출은 schema 인자를 전달하지 않습니다.

직접 연결: [ComparisonStore.rel](#common-store-py-ComparisonStore-rel-270).


<a id="file-common-stub_answers-py"></a>
### common/stub_answers.py


<a id="common-stub_answers-py-_user-20"></a>
#### `_user`

<!-- source-symbol: common/stub_answers.py:20:_user -->
[stub_answers.py](../../backend/analysis/common/stub_answers.py#L20)

```python
def _user(messages: Sequence[Message]) -> str: ...
```

재시도 피드백보다 앞의 사실 목록을 잃지 않도록 모든 user 메시지의 content를 줄바꿈으로 합칩니다.

호출하는 코드: [stub_classify](#common-stub_answers-py-stub_classify-25), [stub_views](#common-stub_answers-py-stub_views-42), [stub_explain](#common-stub_answers-py-stub_explain-65), [_ids](#common-stub_answers-py-_ids-78), [stub_revision](#common-stub_answers-py-stub_revision-117).


<a id="common-stub_answers-py-stub_classify-25"></a>
#### `stub_classify`

<!-- source-symbol: common/stub_answers.py:25:stub_classify -->
[stub_answers.py](../../backend/analysis/common/stub_answers.py#L25)

```python
def stub_classify(messages: Sequence[Message]) -> dict[str, Any]: ...
```

프롬프트 후보 표의 모든 종목을 테마 해당으로 분류하고 일반 0.8, 반도체 문구가 있는 행은 0.9 신뢰도를 넣습니다. 개발용 고정 규칙이며 실제 분류 품질 평가에 쓰는 판단은 아닙니다.

직접 연결: [_user](#common-stub_answers-py-_user-20).


<a id="common-stub_answers-py-stub_views-42"></a>
#### `stub_views`

<!-- source-symbol: common/stub_answers.py:42:stub_views -->
[stub_answers.py](../../backend/analysis/common/stub_answers.py#L42)

```python
def stub_views(messages: Sequence[Message]) -> dict[str, Any]: ...
```

프롬프트의 뉴스·공시 ID를 종목별로 읽고 가능한 경우 절대 의견과 상대 의견을 한 세트로 만듭니다. 수익률·신뢰도는 테스트용 값이며 실제 시장 예측이 아닙니다.

직접 연결: [_user](#common-stub_answers-py-_user-20).


<a id="common-stub_answers-py-stub_explain-65"></a>
#### `stub_explain`

<!-- source-symbol: common/stub_answers.py:65:stub_explain -->
[stub_answers.py](../../backend/analysis/common/stub_answers.py#L65)

```python
def stub_explain(messages: Sequence[Message]) -> dict[str, Any]: ...
```

선정 표에서 순위·회사·인용 ID를 추출해 per_ticker 설명과 전체 요약을 만듭니다. 입력 근거를 이용하므로 임의 종목을 추가하지 않습니다.

직접 연결: [_user](#common-stub_answers-py-_user-20).


<a id="common-stub_answers-py-_ids-78"></a>
#### `_ids`

<!-- source-symbol: common/stub_answers.py:78:_ids -->
[stub_answers.py](../../backend/analysis/common/stub_answers.py#L78)

```python
def _ids(messages: Sequence[Message], prefix: str) -> list[str]: ...
```

전체 user 메시지에서 지정 접두사의 따옴표로 감싼 ID를 중복 제거·정렬합니다. ev와 dc는 숫자 ID만 인식해 일반 JSON 키를 근거로 오인하지 않게 합니다.

직접 연결: [_user](#common-stub_answers-py-_user-20).

호출하는 코드: [stub_interpret](#common-stub_answers-py-stub_interpret-83), [stub_market](#common-stub_answers-py-stub_market-94), [stub_narrate](#common-stub_answers-py-stub_narrate-102).


<a id="common-stub_answers-py-stub_interpret-83"></a>
#### `stub_interpret`

<!-- source-symbol: common/stub_answers.py:83:stub_interpret -->
[stub_answers.py](../../backend/analysis/common/stub_answers.py#L83)

```python
def stub_interpret(messages: Sequence[Message]) -> dict[str, Any]: ...
```

결과 해석에 필요한 문단 배열·후속 행동·평가 객체를 테스트용 문장으로 반환합니다. 계산 ID가 있으면 첫 ID를 인용합니다.

직접 연결: [_ids](#common-stub_answers-py-_ids-78).


<a id="common-stub_answers-py-stub_market-94"></a>
#### `stub_market`

<!-- source-symbol: common/stub_answers.py:94:stub_market -->
[stub_answers.py](../../backend/analysis/common/stub_answers.py#L94)

```python
def stub_market(messages: Sequence[Message]) -> dict[str, Any]: ...
```

뉴스 ID가 있으면 뉴스, 없으면 공시 ID를 이용해 근거 문장을 만듭니다. 둘 다 없으면 근거 부족 안내 문장만 반환합니다.

직접 연결: [_ids](#common-stub_answers-py-_ids-78).


<a id="common-stub_answers-py-stub_narrate-102"></a>
#### `stub_narrate`

<!-- source-symbol: common/stub_answers.py:102:stub_narrate -->
[stub_answers.py](../../backend/analysis/common/stub_answers.py#L102)

```python
def stub_narrate(messages: Sequence[Message]) -> dict[str, Any]: ...
```

리포트 서술 단계가 요구하는 개요·선정·구성·전제·재검토·용어집을 규칙형 문장으로 생성합니다. 금융 지표 ID가 있으면 인용을 붙입니다.

직접 연결: [_ids](#common-stub_answers-py-_ids-78).


<a id="common-stub_answers-py-stub_revision-117"></a>
#### `stub_revision`

<!-- source-symbol: common/stub_answers.py:117:stub_revision -->
[stub_answers.py](../../backend/analysis/common/stub_answers.py#L117)

```python
def stub_revision(messages: Sequence[Message]) -> dict[str, Any]: ...
```

수정 문장에서 티커 포함·제외, 종목 수, 퍼센트 상한, 선정 기준 단어를 간단한 정규식으로 읽습니다. 고정 평가 조건 변경은 unsupported로 표시하고 알려진 변경이 없으면 아이디어 보충으로 반환합니다.

직접 연결: [_user](#common-stub_answers-py-_user-20).


<a id="file-common-warnings-py"></a>
### common/warnings.py


<a id="common-warnings-py-Warning-to_dict-28"></a>
#### `Warning.to_dict`

<!-- source-symbol: common/warnings.py:28:Warning.to_dict -->
[warnings.py](../../backend/analysis/common/warnings.py#L28)

```python
def to_dict(self) -> dict[str, Any]: ...
```

경고 dataclass를 사전으로 변환합니다. 단계·코드·등급·한국어 메시지·날짜·횟수·추가 정보를 결과 파일에 저장할 때 사용합니다.


<a id="common-warnings-py-make-108"></a>
#### `make`

<!-- source-symbol: common/warnings.py:108:make -->
[warnings.py](../../backend/analysis/common/warnings.py#L108)

```python
def make(stage: str, code: str, *, dates: list[str] | tuple[str, ...]=(), details: dict[str, Any] | None=None, **fmt: Any) -> Warning: ...
```

카탈로그에서 코드별 등급과 템플릿을 골라 Warning을 만듭니다. 미등록 코드는 debug legacy_note로 바꾸고 누락된 템플릿 값은 그대로 노출되지 않도록 대체합니다. 날짜는 중복 제거·정렬합니다.

직접 연결: [_fmt_value](#common-warnings-py-_fmt_value-122), [Warning](#common-warnings-py-Warning-19).

호출하는 코드: [from_text](#common-warnings-py-from_text-128), [RunContext.warn](executor_구현보고서.md#executor-context-py-RunContext-warn-49).


<a id="common-warnings-py-_fmt_value-122"></a>
#### `_fmt_value`

<!-- source-symbol: common/warnings.py:122:_fmt_value -->
[warnings.py](../../backend/analysis/common/warnings.py#L122)

```python
def _fmt_value(v: Any) -> str: ...
```

목록·튜플·집합은 쉼표로 연결하고 나머지는 str로 변환하여 경고 템플릿에 삽입합니다.

호출하는 코드: [make](#common-warnings-py-make-108).


<a id="common-warnings-py-from_text-128"></a>
#### `from_text`

<!-- source-symbol: common/warnings.py:128:from_text -->
[warnings.py](../../backend/analysis/common/warnings.py#L128)

```python
def from_text(stage: str, text: str, *, dates: list[str] | None=None) -> Warning: ...
```

기존 문자열 경고에서 날짜 접두사를 분리하고 정규식으로 알려진 코드·변수를 추출합니다. 규칙·지표 이름을 한국어로 바꾸며 미분류 문장은 debug로 원문 보존합니다.

직접 연결: [from_text](#common-warnings-py-from_text-128), [make](#common-warnings-py-make-108), [Warning](#common-warnings-py-Warning-19).

호출하는 코드: [from_text](#common-warnings-py-from_text-128), [RunContext.warn](executor_구현보고서.md#executor-context-py-RunContext-warn-49).


<a id="common-warnings-py-merge-167"></a>
#### `merge`

<!-- source-symbol: common/warnings.py:167:merge -->
[warnings.py](../../backend/analysis/common/warnings.py#L167)

```python
def merge(ws: list[Warning]) -> list[Warning]: ...
```

동일 코드와 details.key를 가진 경고를 합치고 횟수·날짜를 누적합니다. legacy_note는 메시지 자체가 키입니다. 최초 등장 순서를 유지하며 서로 다른 단계에서 나온 경고도 같은 키면 합쳐질 수 있습니다.

직접 연결: [Warning](#common-warnings-py-Warning-19).

호출하는 코드: [run](executor_구현보고서.md#executor-runner-py-run-92), [run._run_stage](executor_구현보고서.md#executor-runner-py-run-_run_stage-126), [st_explain](executor_구현보고서.md#executor-stages-py-st_explain-115), [build_results](m5_backtest_report_구현보고서.md#m5_backtest_report-collect-py-build_results-42).


<a id="common-warnings-py-render-183"></a>
#### `render`

<!-- source-symbol: common/warnings.py:183:render -->
[warnings.py](../../backend/analysis/common/warnings.py#L183)

```python
def render(w: Warning) -> str: ...
```

단일 경고를 한국어 문장으로 렌더링하고 반복이면 횟수와 날짜 범위를 덧붙입니다. 사용자 경고의 단일 날짜는 기본 문장에 추가하지 않습니다.

호출하는 코드: [run._run_stage](executor_구현보고서.md#executor-runner-py-run-_run_stage-126), [st_explain](executor_구현보고서.md#executor-stages-py-st_explain-115), [build_results](m5_backtest_report_구현보고서.md#m5_backtest_report-collect-py-build_results-42).


<a id="common-warnings-py-by_level-190"></a>
#### `by_level`

<!-- source-symbol: common/warnings.py:190:by_level -->
[warnings.py](../../backend/analysis/common/warnings.py#L190)

```python
def by_level(ws: list[Warning], *levels: str) -> list[Warning]: ...
```

주어진 등급에 해당하는 경고만 원래 순서를 유지한 목록으로 반환합니다.


<a id="file-paths-py"></a>
### paths.py


<a id="paths-py-store_dir-17"></a>
#### `store_dir`

<!-- source-symbol: paths.py:17:store_dir -->
[paths.py](../../backend/analysis/paths.py#L17)

```python
def store_dir() -> Path: ...
```

ANALYSIS_STORE_DIR가 있으면 그 경로, 없으면 저장소 루트의 data/analysis_store 경로를 반환합니다. 여기서는 경로만 계산하고 디렉터리는 만들지 않습니다.

호출하는 코드: [JsonStore.__init__](#common-store-py-JsonStore-__init__-35).


<a id="paths-py-output_root-22"></a>
#### `output_root`

<!-- source-symbol: paths.py:22:output_root -->
[paths.py](../../backend/analysis/paths.py#L22)

```python
def output_root() -> Path: ...
```

ANALYSIS_OUTPUT_DIR 또는 기본 output 경로를 반환합니다. 상대경로 환경변수는 호출 프로세스의 작업 디렉터리를 기준으로 해석됩니다.

호출하는 코드: [run_dir](#paths-py-run_dir-27), [llm_cache_dir](#paths-py-llm_cache_dir-31).


<a id="paths-py-run_dir-27"></a>
#### `run_dir`

<!-- source-symbol: paths.py:27:run_dir -->
[paths.py](../../backend/analysis/paths.py#L27)

```python
def run_dir(run_id: str) -> Path: ...
```

실행 산출물 루트 아래 run_id 디렉터리 경로를 반환합니다. 같은 ID는 같은 산출물 위치를 가리킵니다.

직접 연결: [output_root](#paths-py-output_root-22).

호출하는 코드: [partial](api_구현보고서.md#api-routers-runs-py-partial-58), [main](executor_구현보고서.md#executor-cli-py-main-27), [Queue.enqueue](executor_구현보고서.md#executor-queue-py-Queue-enqueue-27), [execute_run](executor_구현보고서.md#executor-worker-py-execute_run-38).


<a id="paths-py-llm_cache_dir-31"></a>
#### `llm_cache_dir`

<!-- source-symbol: paths.py:31:llm_cache_dir -->
[paths.py](../../backend/analysis/paths.py#L31)

```python
def llm_cache_dir() -> Path: ...
```

산출물 루트 아래 공유 llm_cache 경로를 반환합니다. 실행별 폴더와 별도로 유지되는 응답 캐시입니다.

직접 연결: [output_root](#paths-py-output_root-22).

호출하는 코드: [OpenAiLlm.__init__](#common-llm-py-OpenAiLlm-__init__-161).


<a id="file-settings-py"></a>
### settings.py


<a id="settings-py-AnalysisSettings-load-256"></a>
#### `AnalysisSettings.load`

<!-- source-symbol: settings.py:256:AnalysisSettings.load -->
[settings.py](../../backend/analysis/settings.py#L256)

```python
def load(cls, **overrides: Any) -> AnalysisSettings: ...
```

기본 dataclass 설정에 환경변수와 명시적 overrides를 순서대로 적용한 새 설정을 반환합니다. MYFINSIGHT_LLM이 유효하면 우선하고, 미지정 상태에서 API 키가 있으면 api 모드가 됩니다. ANALYSIS_PARALLEL=0으로 단계·분류·날짜별 구성·리포트를 순차화한 뒤 ANALYSIS_MAX_PARALLEL_STAGES가 있으면 단계 동시 수만 다시 덮어쓸 수 있습니다.

선언·진입 조건: `classmethod`.

직접 연결: [replace_settings](#settings-py-replace_settings-302), [ExecutorSettings](#settings-py-ExecutorSettings-222).

호출하는 코드: [create_analysis_app](api_구현보고서.md#api-app-py-create_analysis_app-30), [main](executor_구현보고서.md#executor-cli-py-main-27), [main](executor_구현보고서.md#executor-worker-py-main-112).


<a id="settings-py-AnalysisSettings-snapshot-295"></a>
#### `AnalysisSettings.snapshot`

<!-- source-symbol: settings.py:295:AnalysisSettings.snapshot -->
[settings.py](../../backend/analysis/settings.py#L295)

```python
def snapshot(self) -> dict[str, Any]: ...
```

중첩 설정을 asdict로 복사하고 llm.api_key_env 항목을 제거한 사전을 반환합니다. 실행 기록과 결과의 재현 조건으로 저장하며 실제 API 키 값은 설정 필드에 보관하지 않습니다.


<a id="settings-py-replace_settings-302"></a>
#### `replace_settings`

<!-- source-symbol: settings.py:302:replace_settings -->
[settings.py](../../backend/analysis/settings.py#L302)

```python
def replace_settings(obj: Any, **changes: Any) -> Any: ...
```

dataclasses.replace를 사용해 지정 필드만 바꾼 새 설정 객체를 반환합니다. frozen 설정을 직접 수정하지 않고 하위 설정을 교체할 때 사용합니다.

<details>
<summary>호출하는 코드</summary>

[main](executor_구현보고서.md#executor-cli-py-main-27), [AnalysisSettings.load](#settings-py-AnalysisSettings-load-256).

</details>


<a id="interactions"></a>
## 6. 다른 모듈과의 상호작용

공통 모듈은 [API](api_구현보고서.md)·[실행기](executor_구현보고서.md)·[M1](m1_request_구현보고서.md)·[M3](m3_selection_구현보고서.md)·[M4](m4_portfolio_구현보고서.md)·[M5](m5_backtest_report_구현보고서.md)·[M6](m6_tracking_구현보고서.md)에 기반 객체를 제공합니다. 저장 객체의 Pydantic 계약은 [schemas](schemas_구현보고서.md)에 있습니다.

DB 구현은 [backend.db](../../backend/db/__init__.py), [읽기 확장](../../backend/db/analysis_readers.py), [SQL 저장소](../../backend/db/sql.py)에 위임합니다. 오류 부모는 [MyFinSightError](../../backend/schemas/errors.py)이고 환경 읽기는 [수집기 config](../../backend/adapters/crawlers/config.py)를 재사용합니다. 설정에 들어 있는 비용 단가는 이 저장소의 로그 계산용 값이며 외부 요금표를 확인한 결과로 제시하지 않습니다.

<a id="verification"></a>
## 7. 오류·제약과 검증 근거

파일 잠금은 fcntl 기반이므로 현재 실행 환경의 플랫폼 의존이 있습니다. JSON 원자 교체는 여러 파일·DB 쓰기를 한 번에 되돌리는 트랜잭션이 아닙니다. jsonschema가 없으면 JsonStore의 JSON Schema 검증은 생략됩니다.

LLM 캐시는 재현성을 돕지만 외부 모델의 영구 결정론을 보증하지 않습니다. 전송·내용·최종 문서 보정이 중첩되어 전체 호출 수가 '한 번 재시도'보다 많을 수 있습니다. 비용은 코드 단가표 기반 추정이고 호출 상한을 강제하는 예산 기능은 없습니다. stub 결과는 실제 분석 품질의 근거가 아닙니다.

프롬프트 로더는 user 템플릿만 치환합니다. 현재 02_intent 시스템 문서에 있는 {{max_questions}}는 이 경로에서 그대로 남고 사용자 프롬프트에는 실제 값이 채워집니다. 고정 stub 예시와 스마트 stub의 응답 생성 경로·파일명 차이도 구분해야 합니다.

### 관련 테스트

아래는 테스트 소스에서 확인한 검증 시나리오입니다. 이번 문서 작성에서는 금융 DB·유료 LLM·시나리오 워커를 실행하지 않았으며, 테스트 통과를 새로 보증하는 기록으로 사용하지 않습니다.

- [test_foundations.py](../../backend/tests/analysis/test_foundations.py): 설정 기본/환경 적용·LLM 캐시/재시도·순서형 stub·저장소 잠금·정규 JSON.
- [test_warnings.py](../../backend/tests/analysis/test_warnings.py): 경고 카탈로그·레거시 매핑·병합·사용자/참고 등급.

### 문서 검증

구문 분석 정의 목록과 대조하여 이 보고서의 클래스 36개와 함수/메서드 105개를 모두 설명했습니다. 상대경로 링크와 내부 앵커를 별도로 확인합니다.
