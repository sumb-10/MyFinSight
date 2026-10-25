# api 구현보고서

[전체 안내](README.md)

> 작성 기준: 2026-10-25 작업 공간의 실제 소스. 기존 설계 문서는 배경 참고용이며 아래 동작 설명은 구현을 기준으로 합니다.

대상: Python 파일 11개 · 클래스 9개 · 함수/메서드 57개(중첩 함수와 비공개 보조 함수 포함).

[역할](#role) · [파일 구성](#files) · [처리 흐름](#flow) · [클래스](#classes) · [함수](#functions) · [모듈 연계](#interactions) · [오류·검증](#verification)

<a id="role"></a>
## 1. 모듈의 역할과 용어

`api`는 화면의 HTTP 요청을 분석 서비스에 연결하는 입구입니다. 프로필 저장, 아이디어 대화, 실행 확정·상태 조회, 리포트·근거 조회, 모의투자 조작을 제공합니다. 라우터는 주소별 접수 창구이고 `Services`는 그 창구들이 같이 쓰는 저장소·설정·서비스 묶음입니다.

일반 분석은 요청 확정 시 큐에 등록되고 별도 워커가 실행합니다. 다만 대화의 의도 해석·실행 전 점검, 모의투자 미리보기·수동 갱신은 해당 API 요청 안에서 계산될 수 있습니다. 따라서 'API는 모든 계산을 비동기로 넘긴다'는 설명은 정확하지 않습니다.

주 진입점은 `create_analysis_app()`이고 서버 대상은 `backend.analysis.api.app:app`입니다. 기본 주소 접두사는 `/api/v1`, API 명세 화면은 `/api/v1/docs`입니다.

<a id="files"></a>
## 2. 파일 구성과 책임

| 파일 | 책임 | 문서 내 해설 |
| --- | --- | --- |
| [api/__init__.py](../../backend/analysis/api/__init__.py) | 패키지 목적 설명; 독립 함수·클래스 정의 없음 | 정의 없음 |
| [api/app.py](../../backend/analysis/api/app.py) | FastAPI 앱·미들웨어·라우터 구성 | [클래스 0 · 함수 1](#file-api-app-py) |
| [api/errors.py](../../backend/analysis/api/errors.py) | 예외별 HTTP 상태와 한국어 오류 봉투 | [클래스 0 · 함수 5](#file-api-errors-py) |
| [api/routers/__init__.py](../../backend/analysis/api/routers/__init__.py) | HTTP Request에서 Services 조회 | [클래스 0 · 함수 1](#file-api-routers-__init__-py) |
| [api/routers/meta.py](../../backend/analysis/api/routers/meta.py) | 건강 상태·입력 선택지 메타 조회 | [클래스 0 · 함수 2](#file-api-routers-meta-py) |
| [api/routers/paper.py](../../backend/analysis/api/routers/paper.py) | 모의투자 시작·조회·갱신·중지·재개 | [클래스 1 · 함수 8](#file-api-routers-paper-py) |
| [api/routers/profile.py](../../backend/analysis/api/routers/profile.py) | 프로필 검증·버전 저장·조회 | [클래스 1 · 함수 3](#file-api-routers-profile-py) |
| [api/routers/reports.py](../../backend/analysis/api/routers/reports.py) | 리포트·근거·시계열·체크포인트·재분석·수정·비교 | [클래스 1 · 함수 13](#file-api-routers-reports-py) |
| [api/routers/requests.py](../../backend/analysis/api/routers/requests.py) | 아이디어 대화·답·직접 수정·확정·취소 | [클래스 5 · 함수 9](#file-api-routers-requests-py) |
| [api/routers/runs.py](../../backend/analysis/api/routers/runs.py) | 실행 상태·중간 결과·취소·전체 재시도 | [클래스 0 · 함수 6](#file-api-routers-runs-py) |
| [api/services.py](../../backend/analysis/api/services.py) | 공유 Repository·저장소·LLM·업무 서비스·결과 캐시 | [클래스 1 · 함수 9](#file-api-services-py) |

<a id="flow"></a>
## 3. 처리 흐름과 예시

1. 앱 팩터리가 설정과 Services를 준비합니다. 라우터는 요청의 app.state에서 이를 얻습니다.
2. 사용자가 프로필을 저장하고 아이디어로 `/requests`를 만듭니다. 질문·조건 수정 결과는 `DialogState`로 받습니다.
3. `/requests/{id}/confirm`은 `run_id`·`queue_position`을 반환합니다. 별도 워커가 처리하는 동안 `/runs/{id}`와 `/partial`로 진행을 조회합니다.
4. 완료 후 `/reports/{id}`는 문서, `/evidence`는 전체 근거 페이지, `/series`는 전체 시계열을 제공합니다. 문서 본문의 배열은 크기 절약용 표본일 수 있습니다.
5. 수정 요청은 새 대화와 별도 실행을 만들고, 모의투자는 미리보기와 등록으로 이어집니다.

예를 들어 응답이 `{"run_id":"run_예시","queue_position":1}`이면 요청이 접수된 것이며 리포트가 이미 있다는 뜻은 아닙니다. 실행 성공 여부와 `report_id`를 조회한 후 문서를 읽습니다. 오류는 `{"error":{"code":"REQUEST_INVALID","message_ko":"…","fields":{"horizon.target_years":"…"}}}`와 같은 공통 봉투입니다.

다음 경로 표는 라우터 데코레이터에서 확인한 목록입니다. 본문 모델의 모든 필드는 아래 클래스 표에, 각 경로의 반환·분기는 함수 해설에 있습니다. 기본 성공 코드는 200이고 모의투자 등록만 명시적으로 201입니다.

### HTTP 경로 목록

| 메서드·전체 경로 | 처리 함수 | 명시 반환 계약 |
| --- | --- | --- |
| `GET /api/v1/health` | [health](#api-routers-meta-py-health-18) | `dict[str, Any]` |
| `GET /api/v1/meta/options` | [options](#api-routers-meta-py-options-42) | `dict[str, Any]` |
| `POST /api/v1/paper/preview` | [preview](#api-routers-paper-py-preview-30) | `dict[str, Any]` |
| `POST /api/v1/paper` | [create](#api-routers-paper-py-create-35) | `dict[str, Any]` |
| `GET /api/v1/paper` | [list_papers](#api-routers-paper-py-list_papers-40) | `list[dict[str, Any]]` |
| `GET /api/v1/paper/{paper_id}` | [detail](#api-routers-paper-py-detail-45) | `dict[str, Any]` |
| `POST /api/v1/paper/{paper_id}/refresh` | [refresh](#api-routers-paper-py-refresh-50) | `dict[str, Any]` |
| `POST /api/v1/paper/{paper_id}/stop` | [stop](#api-routers-paper-py-stop-55) | `dict[str, Any]` |
| `POST /api/v1/paper/{paper_id}/resume` | [resume](#api-routers-paper-py-resume-60) | `dict[str, Any]` |
| `GET /api/v1/profile` | [get_profile](#api-routers-profile-py-get_profile-39) | `dict[str, Any]` |
| `PUT /api/v1/profile` | [put_profile](#api-routers-profile-py-put_profile-47) | `dict[str, Any]` |
| `GET /api/v1/reports` | [list_reports](#api-routers-reports-py-list_reports-20) | `list[dict[str, Any]]` |
| `GET /api/v1/reports/{report_id}` | [get_report](#api-routers-reports-py-get_report-40) | `dict[str, Any]` |
| `GET /api/v1/reports/{report_id}/evidence` | [list_evidence](#api-routers-reports-py-list_evidence-70) | `dict[str, Any]` |
| `GET /api/v1/reports/{report_id}/evidence/{eid}` | [get_evidence](#api-routers-reports-py-get_evidence-105) | `dict[str, Any]` |
| `GET /api/v1/reports/{report_id}/checkpoints/{seq}` | [get_checkpoint](#api-routers-reports-py-get_checkpoint-131) | `dict[str, Any]` |
| `GET /api/v1/reports/{report_id}/series` | [get_series](#api-routers-reports-py-get_series-164) | `dict[str, Any]` |
| `GET /api/v1/reports/{report_id}/results` | [get_results](#api-routers-reports-py-get_results-192) | `dict[str, Any]` |
| `POST /api/v1/reports/{report_id}/rerun` | [rerun](#api-routers-reports-py-rerun-200) | `DialogState` |
| `POST /api/v1/reports/{report_id}/revisions` | [create_revision](#api-routers-reports-py-create_revision-213) | `DialogState` |
| `GET /api/v1/comparisons/{comparison_id}` | [get_comparison](#api-routers-reports-py-get_comparison-233) | `dict[str, Any]` |
| `GET /api/v1/reports/{report_id}/comparison` | [get_report_comparison](#api-routers-reports-py-get_report_comparison-238) | `dict[str, Any]` |
| `POST /api/v1/requests` | [create](#api-routers-requests-py-create-35) | `DialogState` |
| `GET /api/v1/requests` | [list_requests](#api-routers-requests-py-list_requests-40) | `list[dict[str, Any]]` |
| `GET /api/v1/requests/{request_id}` | [get](#api-routers-requests-py-get-47) | `DialogState` |
| `POST /api/v1/requests/{request_id}/answer` | [answer](#api-routers-requests-py-answer-52) | `DialogState` |
| `POST /api/v1/requests/{request_id}/skip` | [skip](#api-routers-requests-py-skip-57) | `DialogState` |
| `POST /api/v1/requests/{request_id}/overrides` | [update_overrides](#api-routers-requests-py-update_overrides-70) | `DialogState` |
| `POST /api/v1/requests/{request_id}/message` | [message](#api-routers-requests-py-message-76) | `DialogState` |
| `POST /api/v1/requests/{request_id}/confirm` | [confirm](#api-routers-requests-py-confirm-82) | `dict[str, Any]` |
| `POST /api/v1/requests/{request_id}/cancel` | [cancel](#api-routers-requests-py-cancel-88) | `DialogState` |
| `GET /api/v1/runs` | [list_runs](#api-routers-runs-py-list_runs-41) | `list[dict[str, Any]]` |
| `GET /api/v1/runs/{run_id}` | [get_run](#api-routers-runs-py-get_run-46) | `RunStatus` |
| `POST /api/v1/runs/{run_id}/cancel` | [cancel_run](#api-routers-runs-py-cancel_run-51) | `RunStatus` |
| `GET /api/v1/runs/{run_id}/partial` | [partial](#api-routers-runs-py-partial-58) | `dict[str, Any]` |
| `POST /api/v1/runs/{run_id}/retry` | [retry_run](#api-routers-runs-py-retry_run-84) | `RunStatus` |

<a id="classes"></a>
## 4. 클래스 상세

필드 표는 해당 클래스에서 직접 선언한 필드입니다. 상속 필드는 부모 클래스 설명을 함께 읽습니다. `Field(...)`의 범위는 선언된 검증이며, 서비스에서 추가하는 조건은 함수 설명에 구분합니다.

<a id="api-routers-paper-py-PaperIn-16"></a>
### `PaperIn`

<!-- source-symbol: api/routers/paper.py:16:PaperIn -->
[paper.py](../../backend/analysis/api/routers/paper.py#L16)

모의투자 미리보기·등록의 HTTP 본문입니다. report_id는 출발 리포트, strategy_id는 선택 전략이고 날짜·자본·통화·적립은 생략하면 서비스 기본값을 사용합니다. 초기자본 양수·적립 비음수는 API 모델에서 제한합니다.

기반: `BaseModel`.

| 필드 | 자료형 | 기본값 또는 생성 방식 | 선언된 제약·설명 |
| --- | --- | --- | --- |
| `report_id` | `str` | `필수 입력` | 저장 리포트 ID |
| `strategy_id` | `str \| None` | `None` | 추적·선택할 전략 식별자 |
| `start_date` | `dt.date \| None` | `None` | 해당 기능의 시작 날짜; Horizon에서는 분석 끝 기준일로 별도 해석 |
| `initial_amount` | `float \| None` | `None` | 입력 초기자본; gt=0 |
| `currency` | `Literal['KRW', 'USD'] \| None` | `None` | 입력/종목 통화 |
| `monthly_contribution` | `float \| None` | `None` | 입력 통화 기준 월 적립금; ge=0 |

메서드·속성: [kwargs](#api-routers-paper-py-PaperIn-kwargs-24).


<a id="api-routers-profile-py-ProfileIn-19"></a>
### `ProfileIn`

<!-- source-symbol: api/routers/profile.py:19:ProfileIn -->
[profile.py](../../backend/analysis/api/routers/profile.py#L19)

프로필 저장 본문으로 기본 인적 정보·자본·기간·위험·제약·전략 선호와 진단 메타를 담습니다. 큰 조건 블록은 dict이므로 put_profile이 전체 UserRequest를 조립해 교차 검증합니다.

기반: `BaseModel`.

| 필드 | 자료형 | 기본값 또는 생성 방식 | 선언된 제약·설명 |
| --- | --- | --- | --- |
| `profile` | `dict[str, Any]` | `생성 함수: dict` | 연령·경험·지식 등 사용자 조건 |
| `capital` | `dict[str, Any]` | `필수 입력` | 평가 자본 조건 또는 입력 자본 |
| `horizon` | `dict[str, Any]` | `필수 입력` | 투자 목적·보유 기간·과거 평가 기간·기준일 |
| `risk` | `dict[str, Any]` | `필수 입력` | 위험 성향·허용 낙폭·목표수익·비교지수 |
| `constraints` | `dict[str, Any]` | `필수 입력` | 유니버스·개수·비중·포함/제외·일정 제약 |
| `strategy_preference` | `dict[str, Any]` | `필수 입력` | 선정 지표·기준 비중·뉴스 반영 선호 |
| `diagnosis` | `dict[str, Any] \| None` | `None` | 투자 성향 진단 메타 |
| `risk_type_computed` | `str` | `'moderate'` | 진단에서 계산한 위험 유형 |
| `risk_type_overridden` | `bool` | `False` | 계산 유형을 사용자가 변경했는지 |
| `note` | `str \| None` | `None` | 프로필 버전의 선택 메모 |


<a id="api-routers-reports-py-RevisionIn-208"></a>
### `RevisionIn`

<!-- source-symbol: api/routers/reports.py:208:RevisionIn -->
[reports.py](../../backend/analysis/api/routers/reports.py#L208)

리포트 수정 요청의 text 한 필드를 받습니다. 모델에는 최소 길이 제한이 없고 실제 3자 검사는 DialogService.start_revision이 수행합니다.

기반: `BaseModel`.

| 필드 | 자료형 | 기본값 또는 생성 방식 | 선언된 제약·설명 |
| --- | --- | --- | --- |
| `text` | `str` | `필수 입력` | 자연어 수정 또는 보충 내용 |


<a id="api-routers-requests-py-RequestIn-16"></a>
### `RequestIn`

<!-- source-symbol: api/routers/requests.py:16:RequestIn -->
[requests.py](../../backend/analysis/api/routers/requests.py#L16)

분석 대화 생성 본문입니다. idea와 경로별 overrides, 요청 모드·원안 ID·언어를 담습니다. 모델은 idea 최소 1자이고 서비스가 최소 5자를 추가로 확인합니다.

기반: `BaseModel`.

| 필드 | 자료형 | 기본값 또는 생성 방식 | 선언된 제약·설명 |
| --- | --- | --- | --- |
| `idea` | `str` | `필수 입력` | 사용자 투자 아이디어 본문; min_length=1 |
| `overrides` | `dict[str, Any]` | `생성 함수: dict` | 이번 요청의 필드 경로별 덮어쓰기 |
| `mode` | `str` | `'new'` | 실행·구성·평가 방식 |
| `base_report_id` | `str \| None` | `None` | 수정/재분석의 기준 리포트 |
| `language` | `str` | `'ko'` | 입출력 언어 |


<a id="api-routers-requests-py-AnswerIn-24"></a>
### `AnswerIn`

<!-- source-symbol: api/routers/requests.py:24:AnswerIn -->
[requests.py](../../backend/analysis/api/routers/requests.py#L24)

질문 응답 본문으로 seq는 질문 순번, option_value는 선택지의 실제 값, free_text는 자유 답입니다. 두 답 중 사용 가능한 값의 존재·적용 방식은 대화 서비스가 결정합니다.

기반: `BaseModel`.

| 필드 | 자료형 | 기본값 또는 생성 방식 | 선언된 제약·설명 |
| --- | --- | --- | --- |
| `seq` | `int` | `필수 입력` | 질문·체크포인트·거래의 순번 |
| `option_value` | `Any \| None` | `None` | — |
| `free_text` | `str \| None` | `None` | 자유 답변 원문 |


<a id="api-routers-requests-py-SeqIn-30"></a>
### `SeqIn`

<!-- source-symbol: api/routers/requests.py:30:SeqIn -->
[requests.py](../../backend/analysis/api/routers/requests.py#L30)

질문 건너뛰기에서 필요한 순번 본문입니다.

기반: `BaseModel`.

| 필드 | 자료형 | 기본값 또는 생성 방식 | 선언된 제약·설명 |
| --- | --- | --- | --- |
| `seq` | `int` | `필수 입력` | 질문·체크포인트·거래의 순번 |


<a id="api-routers-requests-py-OverridesIn-61"></a>
### `OverridesIn`

<!-- source-symbol: api/routers/requests.py:61:OverridesIn -->
[requests.py](../../backend/analysis/api/routers/requests.py#L61)

조건 확인 화면에서 직접 변경한 필드 경로→값 사전을 받습니다. 값 None은 해당 덮어쓰기 제거를 뜻합니다.

기반: `BaseModel`.

| 필드 | 자료형 | 기본값 또는 생성 방식 | 선언된 제약·설명 |
| --- | --- | --- | --- |
| `overrides` | `dict[str, Any]` | `필수 입력` | 이번 요청의 필드 경로별 덮어쓰기 |


<a id="api-routers-requests-py-MessageIn-65"></a>
### `MessageIn`

<!-- source-symbol: api/routers/requests.py:65:MessageIn -->
[requests.py](../../backend/analysis/api/routers/requests.py#L65)

질문 외 자유 메시지 본문이며 최소 1자입니다. 공백만 입력한 경우 서비스가 다시 거부합니다.

기반: `BaseModel`.

| 필드 | 자료형 | 기본값 또는 생성 방식 | 선언된 제약·설명 |
| --- | --- | --- | --- |
| `text` | `str` | `필수 입력` | 자연어 수정 또는 보충 내용; min_length=1 |


<a id="api-services-py-Services-20"></a>
### `Services`

<!-- source-symbol: api/services.py:20:Services -->
[services.py](../../backend/analysis/api/services.py#L20)

API 전체가 공유하는 의존성 묶음입니다. repo_factory·store·settings가 필수이며 llm_factory를 주입할 수 있습니다. MarketData 한 개와 최근 결과 8개의 프로세스 캐시를 잠금으로 보호하고 프로필·대화·큐·모의투자 서비스를 제공합니다.

기반: `명시적 부모 없음` · 선언: `dataclass`.

| 필드 | 자료형 | 기본값 또는 생성 방식 | 선언된 제약·설명 |
| --- | --- | --- | --- |
| `repo_factory` | `Callable[[], Any]` | `필수 입력` | Repository를 반환하는 주입 함수 |
| `store` | `JsonStore` | `필수 입력` | 공유 로컬 JSON 저장소 |
| `settings` | `AnalysisSettings` | `필수 입력` | 실행 설정 묶음 |
| `llm_factory` | `Callable[[], LlmClient] \| None` | `None` | 테스트/환경별 LLM 호출기 생성 함수 |
| `_md` | `MarketData \| None` | `None` | — |
| `_lock` | `threading.Lock` | `생성 함수: threading.Lock` | — |
| `_results_cache` | `dict[str, dict[str, Any]]` | `생성 함수: dict` | — |

메서드·속성: [repo](#api-services-py-Services-repo-30), [profiles](#api-services-py-Services-profiles-34), [requests](#api-services-py-Services-requests-38), [queue](#api-services-py-Services-queue-42), [llm](#api-services-py-Services-llm-45), [market_data](#api-services-py-Services-market_data-48), [dialog](#api-services-py-Services-dialog-63), [paper](#api-services-py-Services-paper-66), [results](#api-services-py-Services-results-69).


<a id="functions"></a>
## 5. 함수·메서드 상세

시그니처에 입력 자료형·기본값·반환 자료형을 그대로 기재했습니다. `self`는 소속 클래스의 인스턴스, `cls`는 클래스입니다. 반환 주석이 없는 함수는 본문 해설의 반환 내용을 따릅니다. 속성(`property`)은 호출 괄호 없이 읽고, 중첩 함수는 바깥 함수의 지역 상태를 공유합니다. 연결 목록은 정적으로 확인되는 패키지 내부 직접 호출이며, 주입된 서비스·콜백·Repository 호출은 처리 흐름과 해설에서 설명합니다.


<a id="file-api-app-py"></a>
### api/app.py


<a id="api-app-py-create_analysis_app-30"></a>
#### `create_analysis_app`

<!-- source-symbol: api/app.py:30:create_analysis_app -->
[app.py](../../backend/analysis/api/app.py#L30)

```python
def create_analysis_app(repo: Callable[[], Any] | None=None, *, store_dir: Path | str | None=None, settings: AnalysisSettings | None=None, llm: Callable[[], LlmClient] | None=None, cors_origins: list[str] | None=None) -> FastAPI: ...
```

설정·Repository 생성 함수·JSON 저장소·LLM 생성 함수를 묶어 Services를 만들고 FastAPI 앱의 state에 보관합니다. CORS와 1,024바이트 이상 GZip 압축, 공통 예외 처리기를 설치하고 여섯 라우터를 `/api/v1` 아래 등록한 앱을 반환합니다. 외부에서 의존성을 주입할 수 있어 테스트용 DB와 stub LLM으로 같은 API를 검증할 수 있습니다. 모듈 끝의 `app`은 이 팩터리로 생성됩니다.

직접 연결: [AnalysisSettings.load](common_구현보고서.md#settings-py-AnalysisSettings-load-256), [Services](#api-services-py-Services-20), [JsonStore](common_구현보고서.md#common-store-py-JsonStore-34), [install](#api-errors-py-install-47).


<a id="file-api-errors-py"></a>
### api/errors.py


<a id="api-errors-py-envelope-38"></a>
#### `envelope`

<!-- source-symbol: api/errors.py:38:envelope -->
[errors.py](../../backend/analysis/api/errors.py#L38)

```python
def envelope(code: str, message_ko: str, *, fields: dict[str, str] | None=None, details: dict[str, Any] | None=None) -> dict[str, Any]: ...
```

오류 코드와 한국어 메시지를 `error` 객체에 담은 사전을 반환합니다. fields와 details가 비어 있으면 해당 키를 생략하여 모든 처리기가 같은 응답 형태를 쓰게 합니다.

호출하는 코드: [install._mfs](#api-errors-py-install-_mfs-49), [install._val](#api-errors-py-install-_val-58), [install._any](#api-errors-py-install-_any-69).


<a id="api-errors-py-install-47"></a>
#### `install`

<!-- source-symbol: api/errors.py:47:install -->
[errors.py](../../backend/analysis/api/errors.py#L47)

```python
def install(app: FastAPI) -> None: ...
```

전달받은 FastAPI 앱에 도메인 예외, 요청 형식 검증 예외, 기타 예외를 처리하는 세 비동기 콜백을 등록합니다. 앱 구성을 변경하며 반환값은 없습니다.

호출하는 코드: [create_analysis_app](#api-app-py-create_analysis_app-30).


<a id="api-errors-py-install-_mfs-49"></a>
#### `install._mfs`

<!-- source-symbol: api/errors.py:49:install._mfs -->
[errors.py](../../backend/analysis/api/errors.py#L49)

```python
async def _mfs(_: Request, exc: MyFinSightError) -> JSONResponse: ...
```

MyFinSightError를 받아 예외 클래스별 HTTP 상태를 고르고 details의 fields를 응답 최상위 오류 필드로 분리합니다. 크기가 큰 report 상세는 제외하고 원래 오류 코드와 메시지를 보존한 JSONResponse를 반환합니다.

선언·진입 조건: `app.exception_handler(MyFinSightError)`.

직접 연결: [envelope](#api-errors-py-envelope-38).


<a id="api-errors-py-install-_val-58"></a>
#### `install._val`

<!-- source-symbol: api/errors.py:58:install._val -->
[errors.py](../../backend/analysis/api/errors.py#L58)

```python
async def _val(_: Request, exc: RequestValidationError) -> JSONResponse: ...
```

FastAPI 요청 검증 오류의 body/query/path 접두사를 제거해 필드 경로를 만듭니다. Module1의 한국어 변환 규칙과 라벨을 재사용하여 422 VALIDATION_ERROR 응답을 반환합니다.

선언·진입 조건: `app.exception_handler(RequestValidationError)`.

직접 연결: [_ko](m1_request_구현보고서.md#m1_request-validate-py-_ko-50), [envelope](#api-errors-py-envelope-38).


<a id="api-errors-py-install-_any-69"></a>
#### `install._any`

<!-- source-symbol: api/errors.py:69:install._any -->
[errors.py](../../backend/analysis/api/errors.py#L69)

```python
async def _any(_: Request, exc: Exception) -> JSONResponse: ...
```

처리되지 않은 예외를 HTTP 500 INTERNAL_ERROR로 변환합니다. 응답에는 공통 안내와 예외 타입만 넣고 예외 원문은 포함하지 않습니다.

선언·진입 조건: `app.exception_handler(Exception)`.

직접 연결: [envelope](#api-errors-py-envelope-38).


<a id="file-api-routers-__init__-py"></a>
### api/routers/__init__.py


<a id="api-routers-__init__-py-services-8"></a>
#### `services`

<!-- source-symbol: api/routers/__init__.py:8:services -->
[__init__.py](../../backend/analysis/api/routers/__init__.py#L8)

```python
def services(request: Request) -> Services: ...
```

현재 HTTP Request의 app.state.services를 반환합니다. 각 라우터가 동일한 의존성 묶음에 접근하는 진입 함수이며 서비스 생성이나 분석 실행은 수행하지 않습니다.

<details>
<summary>호출하는 코드</summary>

[health](#api-routers-meta-py-health-18), [options](#api-routers-meta-py-options-42), [preview](#api-routers-paper-py-preview-30), [create](#api-routers-paper-py-create-35), [list_papers](#api-routers-paper-py-list_papers-40), [detail](#api-routers-paper-py-detail-45), [refresh](#api-routers-paper-py-refresh-50), [stop](#api-routers-paper-py-stop-55), [resume](#api-routers-paper-py-resume-60), [get_profile](#api-routers-profile-py-get_profile-39), [put_profile](#api-routers-profile-py-put_profile-47), [list_reports](#api-routers-reports-py-list_reports-20), [get_report](#api-routers-reports-py-get_report-40), [list_evidence](#api-routers-reports-py-list_evidence-70), [get_evidence](#api-routers-reports-py-get_evidence-105), [get_checkpoint](#api-routers-reports-py-get_checkpoint-131), [get_series](#api-routers-reports-py-get_series-164), [get_results](#api-routers-reports-py-get_results-192), [rerun](#api-routers-reports-py-rerun-200), [create_revision](#api-routers-reports-py-create_revision-213), [get_comparison](#api-routers-reports-py-get_comparison-233), [get_report_comparison](#api-routers-reports-py-get_report_comparison-238), [create](#api-routers-requests-py-create-35), [list_requests](#api-routers-requests-py-list_requests-40), [get](#api-routers-requests-py-get-47), [answer](#api-routers-requests-py-answer-52), [skip](#api-routers-requests-py-skip-57), [update_overrides](#api-routers-requests-py-update_overrides-70), [message](#api-routers-requests-py-message-76), [confirm](#api-routers-requests-py-confirm-82), [cancel](#api-routers-requests-py-cancel-88), [list_runs](#api-routers-runs-py-list_runs-41), [get_run](#api-routers-runs-py-get_run-46), [cancel_run](#api-routers-runs-py-cancel_run-51), [partial](#api-routers-runs-py-partial-58), [retry_run](#api-routers-runs-py-retry_run-84).

</details>


<a id="file-api-routers-meta-py"></a>
### api/routers/meta.py


<a id="api-routers-meta-py-health-18"></a>
#### `health`

<!-- source-symbol: api/routers/meta.py:18:health -->
[meta.py](../../backend/analysis/api/routers/meta.py#L18)

```python
def health(request: Request) -> dict[str, Any]: ...
```

LLM 모드, DB의 최신 거래일·자료 범위·접속 대상, worker.lock의 PID 생존 여부, 실행 중 ID와 대기 건수를 모아 반환합니다. DB 조회 실패는 응답의 ok와 db.ok를 false로 바꾸어 표현하며, HTTP 상태 자체를 실패 상태로 바꾸지는 않습니다.

선언·진입 조건: `router.get('/health')`.

직접 연결: [services](#api-routers-__init__-py-services-8), [describe](common_구현보고서.md#common-dbconn-py-describe-96), [pid_alive](executor_구현보고서.md#executor-queue-py-pid_alive-127).


<a id="api-routers-meta-py-options-42"></a>
#### `options`

<!-- source-symbol: api/routers/meta.py:42:options -->
[meta.py](../../backend/analysis/api/routers/meta.py#L42)

```python
def options(request: Request) -> dict[str, Any]: ...
```

요청 스키마의 Literal과 현재 설정에서 유니버스·선정 기준·비중 방식·위험 성향·리밸런싱 단위·비교지수와 한국어 라벨을 구성합니다. 자료 범위 조회가 실패해도 선택지는 반환하고 data_error를 덧붙입니다.

선언·진입 조건: `router.get('/meta/options')`.

직접 연결: [services](#api-routers-__init__-py-services-8).


<a id="file-api-routers-paper-py"></a>
### api/routers/paper.py


<a id="api-routers-paper-py-PaperIn-kwargs-24"></a>
#### `PaperIn.kwargs`

<!-- source-symbol: api/routers/paper.py:24:PaperIn.kwargs -->
[paper.py](../../backend/analysis/api/routers/paper.py#L24)

```python
def kwargs(self) -> dict[str, Any]: ...
```

report_id를 제외한 선택 전략·시작일·자본·통화·적립 값을 서비스 호출용 사전으로 반환합니다. None도 전달해 서비스가 기본값을 결정하도록 합니다.


<a id="api-routers-paper-py-preview-30"></a>
#### `preview`

<!-- source-symbol: api/routers/paper.py:30:preview -->
[paper.py](../../backend/analysis/api/routers/paper.py#L30)

```python
def preview(body: PaperIn, request: Request) -> dict[str, Any]: ...
```

PaperIn을 모의투자 미리보기 서비스로 전달하고 시작 계획을 반환합니다. 모의투자 파일은 등록하지 않지만 자료 조회와 필요한 비중 재구성은 수행할 수 있습니다.

선언·진입 조건: `router.post('/paper/preview')`.

직접 연결: [services](#api-routers-__init__-py-services-8).


<a id="api-routers-paper-py-create-35"></a>
#### `create`

<!-- source-symbol: api/routers/paper.py:35:create -->
[paper.py](../../backend/analysis/api/routers/paper.py#L35)

```python
def create(body: PaperIn, request: Request) -> dict[str, Any]: ...
```

PaperService.create를 호출해 모의투자와 최초 기록을 저장하고 상세 응답을 HTTP 201로 반환합니다.

선언·진입 조건: `router.post('/paper', status_code=201)`.

직접 연결: [services](#api-routers-__init__-py-services-8).


<a id="api-routers-paper-py-list_papers-40"></a>
#### `list_papers`

<!-- source-symbol: api/routers/paper.py:40:list_papers -->
[paper.py](../../backend/analysis/api/routers/paper.py#L40)

```python
def list_papers(request: Request) -> list[dict[str, Any]]: ...
```

등록된 모의투자의 요약 목록을 반환합니다.

선언·진입 조건: `router.get('/paper')`.

직접 연결: [services](#api-routers-__init__-py-services-8).


<a id="api-routers-paper-py-detail-45"></a>
#### `detail`

<!-- source-symbol: api/routers/paper.py:45:detail -->
[paper.py](../../backend/analysis/api/routers/paper.py#L45)

```python
def detail(paper_id: str, request: Request) -> dict[str, Any]: ...
```

모의투자 설정·요약·스냅샷·거래 기록·차트 시계열을 반환합니다.

선언·진입 조건: `router.get('/paper/{paper_id}')`.

직접 연결: [services](#api-routers-__init__-py-services-8).


<a id="api-routers-paper-py-refresh-50"></a>
#### `refresh`

<!-- source-symbol: api/routers/paper.py:50:refresh -->
[paper.py](../../backend/analysis/api/routers/paper.py#L50)

```python
def refresh(paper_id: str, request: Request) -> dict[str, Any]: ...
```

선택한 모의투자를 새로 처리 가능한 거래일까지 갱신하고 상세를 반환합니다.

선언·진입 조건: `router.post('/paper/{paper_id}/refresh')`.

직접 연결: [services](#api-routers-__init__-py-services-8).


<a id="api-routers-paper-py-stop-55"></a>
#### `stop`

<!-- source-symbol: api/routers/paper.py:55:stop -->
[paper.py](../../backend/analysis/api/routers/paper.py#L55)

```python
def stop(paper_id: str, request: Request) -> dict[str, Any]: ...
```

선택 모의투자의 중지 상태와 이력을 저장하고 상세를 반환합니다.

선언·진입 조건: `router.post('/paper/{paper_id}/stop')`.

직접 연결: [services](#api-routers-__init__-py-services-8).


<a id="api-routers-paper-py-resume-60"></a>
#### `resume`

<!-- source-symbol: api/routers/paper.py:60:resume -->
[paper.py](../../backend/analysis/api/routers/paper.py#L60)

```python
def resume(paper_id: str, request: Request) -> dict[str, Any]: ...
```

중지 기간의 리밸런싱 건너뜀을 기록하고 평가를 재개한 상세를 반환합니다.

선언·진입 조건: `router.post('/paper/{paper_id}/resume')`.

직접 연결: [services](#api-routers-__init__-py-services-8).


<a id="file-api-routers-profile-py"></a>
### api/routers/profile.py


<a id="api-routers-profile-py-_view-32"></a>
#### `_view`

<!-- source-symbol: api/routers/profile.py:32:_view -->
[profile.py](../../backend/analysis/api/routers/profile.py#L32)

```python
def _view(doc: dict[str, Any]) -> dict[str, Any]: ...
```

저장 문서에서 current_version과 일치하는 프로필 내용을 찾고 버전별 생성시각·메모를 요약한 응답을 반환합니다. 전체 과거 버전의 세부 조건은 목록에 복사하지 않습니다.

호출하는 코드: [get_profile](#api-routers-profile-py-get_profile-39), [put_profile](#api-routers-profile-py-put_profile-47).


<a id="api-routers-profile-py-get_profile-39"></a>
#### `get_profile`

<!-- source-symbol: api/routers/profile.py:39:get_profile -->
[profile.py](../../backend/analysis/api/routers/profile.py#L39)

```python
def get_profile(request: Request) -> dict[str, Any]: ...
```

현재 프로필을 읽어 화면용 응답으로 변환합니다. 파일이 없으면 NotFound이며 저장이나 버전 추가는 하지 않습니다.

선언·진입 조건: `router.get('/profile')`.

직접 연결: [services](#api-routers-__init__-py-services-8), [NotFound](common_구현보고서.md#errors-py-NotFound-73), [_view](#api-routers-profile-py-_view-32).

명시적으로 발생시키는 예외: `NotFound`. 발생 조건은 위 해설과 소스의 분기를 함께 확인합니다.


<a id="api-routers-profile-py-put_profile-47"></a>
#### `put_profile`

<!-- source-symbol: api/routers/profile.py:47:put_profile -->
[profile.py](../../backend/analysis/api/routers/profile.py#L47)

```python
def put_profile(body: ProfileIn, request: Request) -> dict[str, Any]: ...
```

입력에서 메모를 분리하고 user_id 기본값을 채우며 프로필의 start_date를 제거합니다. 임시 아이디어로 요청을 조립해 HARD 검증한 뒤 새 프로필 버전을 추가합니다. Pydantic 및 JSON Schema 오류는 PROFILE_INVALID의 필드별 메시지로 바꿉니다.

선언·진입 조건: `router.put('/profile')`.

직접 연결: [services](#api-routers-__init__-py-services-8), [build](m1_request_구현보고서.md#m1_request-assemble-py-build-33), [hard_errors](m1_request_구현보고서.md#m1_request-validate-py-hard_errors-69), [RequestInvalid](common_구현보고서.md#errors-py-RequestInvalid-11), [_view](#api-routers-profile-py-_view-32).

명시적으로 발생시키는 예외: `RequestInvalid`. 발생 조건은 위 해설과 소스의 분기를 함께 확인합니다.


<a id="file-api-routers-reports-py"></a>
### api/routers/reports.py


<a id="api-routers-reports-py-list_reports-20"></a>
#### `list_reports`

<!-- source-symbol: api/routers/reports.py:20:list_reports -->
[reports.py](../../backend/analysis/api/routers/reports.py#L20)

```python
def list_reports(request: Request, limit: int=100) -> list[dict[str, Any]]: ...
```

DB 리포트 메타와 완료된 큐 색인·요청 문서를 결합해 목록을 반환합니다. 성공/부분 성공한 실행만 포함하며 has_report로 실제 저장 문서 유무를 구분합니다.

선언·진입 조건: `router.get('/reports')`.

직접 연결: [services](#api-routers-__init__-py-services-8).


<a id="api-routers-reports-py-get_report-40"></a>
#### `get_report`

<!-- source-symbol: api/routers/reports.py:40:get_report -->
[reports.py](../../backend/analysis/api/routers/reports.py#L40)

```python
def get_report(report_id: str, request: Request) -> dict[str, Any]: ...
```

저장된 리포트를 반환하고 구형 v1 문서는 present_doc로 읽기 시 정규화합니다. 문서가 없으면 실행 상태를 조회해 REPORT_BLOCKED, REPORT_NOT_READY, 일반 NOT_FOUND를 구분합니다.

선언·진입 조건: `router.get('/reports/{report_id}')`.

직접 연결: [services](#api-routers-__init__-py-services-8), [NotFound](common_구현보고서.md#errors-py-NotFound-73), [present_doc](m5_backtest_report_구현보고서.md#m5_backtest_report-report-py-present_doc-328).

명시적으로 발생시키는 예외: `NotFound`. 발생 조건은 위 해설과 소스의 분기를 함께 확인합니다.


<a id="api-routers-reports-py-_evidence_rows-60"></a>
#### `_evidence_rows`

<!-- source-symbol: api/routers/reports.py:60:_evidence_rows -->
[reports.py](../../backend/analysis/api/routers/reports.py#L60)

```python
def _evidence_rows(R: dict[str, Any]) -> list[dict[str, Any]]: ...
```

evidence_index 사전을 id 포함 행 목록으로 바꾸고 종류 우선순위와 날짜 문자열 키로 정렬합니다. 코드에 두 번의 sort가 있으며 마지막 키가 최종 순서를 결정합니다. 날짜 앞에 '-'를 붙이는 문자열 정렬이므로 주석의 최신순을 보장한다고 설명해서는 안 됩니다.

호출하는 코드: [list_evidence](#api-routers-reports-py-list_evidence-70).


<a id="api-routers-reports-py-list_evidence-70"></a>
#### `list_evidence`

<!-- source-symbol: api/routers/reports.py:70:list_evidence -->
[reports.py](../../backend/analysis/api/routers/reports.py#L70)

```python
def list_evidence(report_id: str, request: Request, offset: int=0, limit: int=50, kind: str | None=None, ticker: str | None=None, q: str | None=None, from_: str | None=Query(None, alias='from'), to: str | None=None, ids: str | None=None) -> dict[str, Any]: ...
```

근거 목록에 ids·kind·ticker·검색어·기간 필터를 적용하고 페이지·종류별 수량을 반환합니다. limit는 1~200으로 보정하지만 offset은 별도로 보정하지 않습니다. by_kind와 index_total은 필터 전 전체 색인 기준이고 total은 필터 후 기준입니다.

선언·진입 조건: `router.get('/reports/{report_id}/evidence')`.

직접 연결: [services](#api-routers-__init__-py-services-8), [NotFound](common_구현보고서.md#errors-py-NotFound-73), [_evidence_rows](#api-routers-reports-py-_evidence_rows-60).

명시적으로 발생시키는 예외: `NotFound`. 발생 조건은 위 해설과 소스의 분기를 함께 확인합니다.


<a id="api-routers-reports-py-get_evidence-105"></a>
#### `get_evidence`

<!-- source-symbol: api/routers/reports.py:105:get_evidence -->
[reports.py](../../backend/analysis/api/routers/reports.py#L105)

```python
def get_evidence(report_id: str, eid: str, request: Request) -> dict[str, Any]: ...
```

근거 한 건과 그 ID를 인용한 문단·카드·기업 설명·타임라인의 위치를 반환합니다. 인용 탐색은 저장 리포트의 지원 블록 타입에 한정합니다.

선언·진입 조건: `router.get('/reports/{report_id}/evidence/{eid}')`.

직접 연결: [services](#api-routers-__init__-py-services-8), [NotFound](common_구현보고서.md#errors-py-NotFound-73).

명시적으로 발생시키는 예외: `NotFound`. 발생 조건은 위 해설과 소스의 분기를 함께 확인합니다.


<a id="api-routers-reports-py-get_checkpoint-131"></a>
#### `get_checkpoint`

<!-- source-symbol: api/routers/reports.py:131:get_checkpoint -->
[reports.py](../../backend/analysis/api/routers/reports.py#L131)

```python
def get_checkpoint(report_id: str, seq: int, request: Request, portfolio_id: str | None=None) -> dict[str, Any]: ...
```

지정 포트폴리오 또는 선택안에서 seq 체크포인트를 찾아 보유·거래·구간 성과를 반환합니다. walk-forward BL과 그 낙폭 맞춤안이면 해당 날짜의 투자 의견·시장모형·근거도 결합합니다.

선언·진입 조건: `router.get('/reports/{report_id}/checkpoints/{seq}')`.

직접 연결: [services](#api-routers-__init__-py-services-8), [NotFound](common_구현보고서.md#errors-py-NotFound-73), [chosen_portfolio_id](m5_backtest_report_구현보고서.md#m5_backtest_report-report_blocks-py-chosen_portfolio_id-33), [find](m5_backtest_report_구현보고서.md#m5_backtest_report-report_blocks-py-find-29), [pf_label](m5_backtest_report_구현보고서.md#m5_backtest_report-report_blocks-py-pf_label-17).

명시적으로 발생시키는 예외: `NotFound`. 발생 조건은 위 해설과 소스의 분기를 함께 확인합니다.


<a id="api-routers-reports-py-get_series-164"></a>
#### `get_series`

<!-- source-symbol: api/routers/reports.py:164:get_series -->
[reports.py](../../backend/analysis/api/routers/reports.py#L164)

```python
def get_series(report_id: str, request: Request, dataset: str='index', ids: str | None=None) -> dict[str, Any]: ...
```

index, value_usd, drawdown 중 요청 데이터셋의 전체 해상도 시계열을 반환합니다. ids로 대상을 고를 수 있으며 value_usd에는 선택안의 적립 원장을 누적한 net_invested도 추가할 수 있습니다. 미지원 데이터셋은 NotFound입니다.

선언·진입 조건: `router.get('/reports/{report_id}/series')`.

직접 연결: [services](#api-routers-__init__-py-services-8), [NotFound](common_구현보고서.md#errors-py-NotFound-73), [all_blocks](m5_backtest_report_구현보고서.md#m5_backtest_report-report_blocks-py-all_blocks-25), [pf_label](m5_backtest_report_구현보고서.md#m5_backtest_report-report_blocks-py-pf_label-17), [chosen_portfolio_id](m5_backtest_report_구현보고서.md#m5_backtest_report-report_blocks-py-chosen_portfolio_id-33), [find](m5_backtest_report_구현보고서.md#m5_backtest_report-report_blocks-py-find-29).

명시적으로 발생시키는 예외: `NotFound`. 발생 조건은 위 해설과 소스의 분기를 함께 확인합니다.


<a id="api-routers-reports-py-get_results-192"></a>
#### `get_results`

<!-- source-symbol: api/routers/reports.py:192:get_results -->
[reports.py](../../backend/analysis/api/routers/reports.py#L192)

```python
def get_results(report_id: str, request: Request) -> dict[str, Any]: ...
```

저장된 run_artifact의 13_results 전체를 반환합니다. 문서용 축약·표본 시계열이 아닌 통합 원본입니다.

선언·진입 조건: `router.get('/reports/{report_id}/results')`.

직접 연결: [services](#api-routers-__init__-py-services-8), [NotFound](common_구현보고서.md#errors-py-NotFound-73).

명시적으로 발생시키는 예외: `NotFound`. 발생 조건은 위 해설과 소스의 분기를 함께 확인합니다.


<a id="api-routers-reports-py-rerun-200"></a>
#### `rerun`

<!-- source-symbol: api/routers/reports.py:200:rerun -->
[reports.py](../../backend/analysis/api/routers/reports.py#L200)

```python
def rerun(report_id: str, request: Request) -> DialogState: ...
```

기존 요청의 프로필 버전·아이디어·overrides를 사용해 rerun 모드의 새 대화를 시작합니다. overrides에 과거 기준일이 남아 있으면 그대로 전달되므로 모든 경우에 최신 기준일로 바뀐다고 단정할 수 없습니다.

선언·진입 조건: `router.post('/reports/{report_id}/rerun', response_model=DialogState)`.

직접 연결: [services](#api-routers-__init__-py-services-8).


<a id="api-routers-reports-py-create_revision-213"></a>
#### `create_revision`

<!-- source-symbol: api/routers/reports.py:213:create_revision -->
[reports.py](../../backend/analysis/api/routers/reports.py#L213)

```python
def create_revision(report_id: str, body: RevisionIn, request: Request) -> DialogState: ...
```

자연어 수정 문장을 start_revision에 전달해 원안 조건을 고정한 수정 대화를 시작합니다. 분석 실행과 비교 문서 생성은 이후 확정 및 워커 처리에서 이뤄집니다.

선언·진입 조건: `router.post('/reports/{report_id}/revisions', response_model=DialogState)`.

직접 연결: [services](#api-routers-__init__-py-services-8).


<a id="api-routers-reports-py-_comparison-218"></a>
#### `_comparison`

<!-- source-symbol: api/routers/reports.py:218:_comparison -->
[reports.py](../../backend/analysis/api/routers/reports.py#L218)

```python
def _comparison(sv: Any, comparison_id: str) -> dict[str, Any]: ...
```

cmp_ 접두사를 보완해 비교 JSON을 읽습니다. 파일이 없으면 실행 상태에 따라 COMPARISON_NOT_READY 또는 COMPARISON_MISSING을 반환하는 NotFound를 발생시킵니다.

직접 연결: [ComparisonStore](common_구현보고서.md#common-store-py-ComparisonStore-266), [NotFound](common_구현보고서.md#errors-py-NotFound-73).

호출하는 코드: [get_comparison](#api-routers-reports-py-get_comparison-233), [get_report_comparison](#api-routers-reports-py-get_report_comparison-238).

명시적으로 발생시키는 예외: `NotFound`. 발생 조건은 위 해설과 소스의 분기를 함께 확인합니다.


<a id="api-routers-reports-py-get_comparison-233"></a>
#### `get_comparison`

<!-- source-symbol: api/routers/reports.py:233:get_comparison -->
[reports.py](../../backend/analysis/api/routers/reports.py#L233)

```python
def get_comparison(comparison_id: str, request: Request) -> dict[str, Any]: ...
```

comparison_id로 원안과 수정안의 저장된 비교 문서를 반환합니다.

선언·진입 조건: `router.get('/comparisons/{comparison_id}')`.

직접 연결: [_comparison](#api-routers-reports-py-_comparison-218), [services](#api-routers-__init__-py-services-8).


<a id="api-routers-reports-py-get_report_comparison-238"></a>
#### `get_report_comparison`

<!-- source-symbol: api/routers/reports.py:238:get_report_comparison -->
[reports.py](../../backend/analysis/api/routers/reports.py#L238)

```python
def get_report_comparison(report_id: str, request: Request) -> dict[str, Any]: ...
```

수정안 report_id를 비교 ID로 해석해 원안 대비 비교를 반환합니다. 원안 자체의 모든 파생 수정안을 나열하는 API는 아닙니다.

선언·진입 조건: `router.get('/reports/{report_id}/comparison')`.

직접 연결: [_comparison](#api-routers-reports-py-_comparison-218), [services](#api-routers-__init__-py-services-8).


<a id="file-api-routers-requests-py"></a>
### api/routers/requests.py


<a id="api-routers-requests-py-create-35"></a>
#### `create`

<!-- source-symbol: api/routers/requests.py:35:create -->
[requests.py](../../backend/analysis/api/routers/requests.py#L35)

```python
def create(body: RequestIn, request: Request) -> DialogState: ...
```

RequestIn의 아이디어·덮어쓰기·모드·기준 리포트·언어를 DialogService.start에 전달하고 첫 DialogState를 반환합니다. 첫 대화 턴에서 의도 해석이 수행될 수 있습니다.

선언·진입 조건: `router.post('/requests', response_model=DialogState)`.

직접 연결: [services](#api-routers-__init__-py-services-8).


<a id="api-routers-requests-py-list_requests-40"></a>
#### `list_requests`

<!-- source-symbol: api/routers/requests.py:40:list_requests -->
[requests.py](../../backend/analysis/api/routers/requests.py#L40)

```python
def list_requests(request: Request, limit: int=50, include_cancelled: bool=False) -> list[dict[str, Any]]: ...
```

저장 요청 중 취소 건 포함 여부를 적용하고 최근 limit건의 식별자·아이디어·상태·실행 ID를 최신순으로 반환합니다. 대화 전문은 응답에 넣지 않습니다.

선언·진입 조건: `router.get('/requests', response_model=list[dict[str, Any]])`.

직접 연결: [services](#api-routers-__init__-py-services-8).


<a id="api-routers-requests-py-get-47"></a>
#### `get`

<!-- source-symbol: api/routers/requests.py:47:get -->
[requests.py](../../backend/analysis/api/routers/requests.py#L47)

```python
def get(request_id: str, request: Request) -> DialogState: ...
```

request_id에 해당하는 현재 대화 상태를 반환합니다. 조회 과정에서 새로운 질문 턴을 실행하지 않습니다.

선언·진입 조건: `router.get('/requests/{request_id}', response_model=DialogState)`.

직접 연결: [services](#api-routers-__init__-py-services-8).


<a id="api-routers-requests-py-answer-52"></a>
#### `answer`

<!-- source-symbol: api/routers/requests.py:52:answer -->
[requests.py](../../backend/analysis/api/routers/requests.py#L52)

```python
def answer(request_id: str, body: AnswerIn, request: Request) -> DialogState: ...
```

질문 순번과 선택 값 또는 자유 입력을 대화 서비스에 전달합니다. 서비스가 답을 반영하고 다음 상태를 계산한 결과를 반환합니다.

선언·진입 조건: `router.post('/requests/{request_id}/answer', response_model=DialogState)`.

직접 연결: [services](#api-routers-__init__-py-services-8).


<a id="api-routers-requests-py-skip-57"></a>
#### `skip`

<!-- source-symbol: api/routers/requests.py:57:skip -->
[requests.py](../../backend/analysis/api/routers/requests.py#L57)

```python
def skip(request_id: str, body: SeqIn, request: Request) -> DialogState: ...
```

본문의 seq에 해당하는 질문을 건너뛰고 다음 대화 상태를 반환합니다. seq 본문은 필수입니다.

선언·진입 조건: `router.post('/requests/{request_id}/skip', response_model=DialogState)`.

직접 연결: [services](#api-routers-__init__-py-services-8).


<a id="api-routers-requests-py-update_overrides-70"></a>
#### `update_overrides`

<!-- source-symbol: api/routers/requests.py:70:update_overrides -->
[requests.py](../../backend/analysis/api/routers/requests.py#L70)

```python
def update_overrides(request_id: str, body: OverridesIn, request: Request) -> DialogState: ...
```

필드 경로별 덮어쓰기를 적용하고 새 대화 턴을 실행합니다. 값이 None인 경로는 덮어쓰기를 지워 프로필 기본값으로 돌아갑니다.

선언·진입 조건: `router.post('/requests/{request_id}/overrides', response_model=DialogState)`.

직접 연결: [services](#api-routers-__init__-py-services-8).


<a id="api-routers-requests-py-message-76"></a>
#### `message`

<!-- source-symbol: api/routers/requests.py:76:message -->
[requests.py](../../backend/analysis/api/routers/requests.py#L76)

```python
def message(request_id: str, body: MessageIn, request: Request) -> DialogState: ...
```

질문 선택과 별개로 입력한 문장을 아이디어 보충에 추가하고 다음 의도 해석 결과를 반환합니다. 자연어 문장이 곧바로 수치 필드를 변경하는 것은 아닙니다.

선언·진입 조건: `router.post('/requests/{request_id}/message', response_model=DialogState)`.

직접 연결: [services](#api-routers-__init__-py-services-8).


<a id="api-routers-requests-py-confirm-82"></a>
#### `confirm`

<!-- source-symbol: api/routers/requests.py:82:confirm -->
[requests.py](../../backend/analysis/api/routers/requests.py#L82)

```python
def confirm(request_id: str, request: Request) -> dict[str, Any]: ...
```

준비된 요청을 확정하고 큐에 넣은 실행 ID와 대기 순번을 반환합니다. 같은 요청을 다시 확정하면 서비스가 기존 실행 ID를 반환합니다.

선언·진입 조건: `router.post('/requests/{request_id}/confirm')`.

직접 연결: [services](#api-routers-__init__-py-services-8).


<a id="api-routers-requests-py-cancel-88"></a>
#### `cancel`

<!-- source-symbol: api/routers/requests.py:88:cancel -->
[requests.py](../../backend/analysis/api/routers/requests.py#L88)

```python
def cancel(request_id: str, request: Request) -> DialogState: ...
```

대화 요청을 취소한 상태를 반환합니다. 이미 실행 큐에 들어간 분석의 취소는 runs 라우터가 별도로 담당합니다.

선언·진입 조건: `router.post('/requests/{request_id}/cancel', response_model=DialogState)`.

직접 연결: [services](#api-routers-__init__-py-services-8).


<a id="file-api-routers-runs-py"></a>
### api/routers/runs.py


<a id="api-routers-runs-py-run_status-19"></a>
#### `run_status`

<!-- source-symbol: api/routers/runs.py:19:run_status -->
[runs.py](../../backend/analysis/api/routers/runs.py#L19)

```python
def run_status(sv, run_id: str) -> RunStatus: ...
```

runs.json의 실행 상태와 DB run_step 기록을 합쳐 RunStatus를 만듭니다. 단계 기록이 없으면 레지스트리 전체를 QUEUED로 채우고 화면용 다섯 묶음을 보완합니다. 실행 중 취소 요청은 cancelling으로 표시하고 실패 시 오류·실패 단계·가능한 화면 행동을 제공합니다.

직접 연결: [steps_for_api](m5_backtest_report_구현보고서.md#m5_backtest_report-persist-py-steps_for_api-50), [bucket_status](m5_backtest_report_구현보고서.md#m5_backtest_report-persist-py-bucket_status-61), [RunStatus](schemas_구현보고서.md#schemas-run-py-RunStatus-58).

호출하는 코드: [get_run](#api-routers-runs-py-get_run-46), [cancel_run](#api-routers-runs-py-cancel_run-51), [retry_run](#api-routers-runs-py-retry_run-84).


<a id="api-routers-runs-py-list_runs-41"></a>
#### `list_runs`

<!-- source-symbol: api/routers/runs.py:41:list_runs -->
[runs.py](../../backend/analysis/api/routers/runs.py#L41)

```python
def list_runs(request: Request, limit: int=50) -> list[dict[str, Any]]: ...
```

등록된 실행 색인의 최근 limit건을 JSON 호환 사전 목록으로 반환합니다.

선언·진입 조건: `router.get('/runs', response_model=list[dict[str, Any]])`.

직접 연결: [services](#api-routers-__init__-py-services-8).


<a id="api-routers-runs-py-get_run-46"></a>
#### `get_run`

<!-- source-symbol: api/routers/runs.py:46:get_run -->
[runs.py](../../backend/analysis/api/routers/runs.py#L46)

```python
def get_run(run_id: str, request: Request) -> RunStatus: ...
```

지정 실행을 run_status로 조립해 반환합니다. 클라이언트가 이 API를 반복 조회해 진행 상황을 표시합니다.

선언·진입 조건: `router.get('/runs/{run_id}', response_model=RunStatus)`.

직접 연결: [run_status](#api-routers-runs-py-run_status-19), [services](#api-routers-__init__-py-services-8).


<a id="api-routers-runs-py-cancel_run-51"></a>
#### `cancel_run`

<!-- source-symbol: api/routers/runs.py:51:cancel_run -->
[runs.py](../../backend/analysis/api/routers/runs.py#L51)

```python
def cancel_run(run_id: str, request: Request) -> RunStatus: ...
```

큐에 취소 요청을 기록한 뒤 최신 RunStatus를 반환합니다. 대기 건은 즉시 취소되고 실행 중 건은 실행기의 취소 확인 지점에서 중단됩니다.

선언·진입 조건: `router.post('/runs/{run_id}/cancel', response_model=RunStatus)`.

직접 연결: [services](#api-routers-__init__-py-services-8), [run_status](#api-routers-runs-py-run_status-19).


<a id="api-routers-runs-py-partial-58"></a>
#### `partial`

<!-- source-symbol: api/routers/runs.py:58:partial -->
[runs.py](../../backend/analysis/api/routers/runs.py#L58)

```python
def partial(run_id: str, request: Request) -> dict[str, Any]: ...
```

실행 존재를 확인하고 output의 02_intent.json과 05_selection.json이 있으면 요약·테마·선정 표를 반환합니다. 아직 없는 부분은 None이며 최종 리포트 없이 중간 결과를 볼 수 있습니다. 파일 읽기·파싱 예외를 별도로 흡수하지는 않습니다.

선언·진입 조건: `router.get('/runs/{run_id}/partial')`.

직접 연결: [services](#api-routers-__init__-py-services-8), [run_dir](common_구현보고서.md#paths-py-run_dir-27).


<a id="api-routers-runs-py-retry_run-84"></a>
#### `retry_run`

<!-- source-symbol: api/routers/runs.py:84:retry_run -->
[runs.py](../../backend/analysis/api/routers/runs.py#L84)

```python
def retry_run(run_id: str, request: Request) -> RunStatus: ...
```

실패 또는 취소된 실행의 확정 요청을 새 run_id로 다시 큐에 등록합니다. 요청 문서의 run_id도 새 ID로 저장합니다. 이전 단계부터 이어가는 재개가 아니라 동일 확정 요청의 전체 재실행입니다.

선언·진입 조건: `router.post('/runs/{run_id}/retry', response_model=RunStatus)`.

직접 연결: [services](#api-routers-__init__-py-services-8), [Conflict](common_구현보고서.md#errors-py-Conflict-78), [new_run_id](common_구현보고서.md#common-store-py-new_run_id-103), [run_status](#api-routers-runs-py-run_status-19).

명시적으로 발생시키는 예외: `Conflict`. 발생 조건은 위 해설과 소스의 분기를 함께 확인합니다.


<a id="file-api-services-py"></a>
### api/services.py


<a id="api-services-py-Services-repo-30"></a>
#### `Services.repo`

<!-- source-symbol: api/services.py:30:Services.repo -->
[services.py](../../backend/analysis/api/services.py#L30)

```python
def repo(self) -> Any: ...
```

repo_factory를 호출해 Repository를 반환하는 속성입니다. Services 자체가 연결 객체를 새로 여는지 여부는 주입된 팩터리에 달려 있습니다.

선언·진입 조건: `property`.


<a id="api-services-py-Services-profiles-34"></a>
#### `Services.profiles`

<!-- source-symbol: api/services.py:34:Services.profiles -->
[services.py](../../backend/analysis/api/services.py#L34)

```python
def profiles(self) -> ProfileStore: ...
```

공유 JsonStore를 사용하는 ProfileStore 래퍼를 만들어 반환합니다. 프로필 원본 파일은 여러 요청이 공유합니다.

선언·진입 조건: `property`.

직접 연결: [ProfileStore](common_구현보고서.md#common-store-py-ProfileStore-114).


<a id="api-services-py-Services-requests-38"></a>
#### `Services.requests`

<!-- source-symbol: api/services.py:38:Services.requests -->
[services.py](../../backend/analysis/api/services.py#L38)

```python
def requests(self) -> RequestStore: ...
```

공유 JsonStore에 연결된 RequestStore를 반환하여 요청 대화의 저장·조회를 제공합니다.

선언·진입 조건: `property`.

직접 연결: [RequestStore](common_구현보고서.md#common-store-py-RequestStore-154).


<a id="api-services-py-Services-queue-42"></a>
#### `Services.queue`

<!-- source-symbol: api/services.py:42:Services.queue -->
[services.py](../../backend/analysis/api/services.py#L42)

```python
def queue(self) -> Queue: ...
```

같은 runs.json을 사용하는 Queue 래퍼를 반환합니다. 래퍼 생성만으로 실행이 등록되지는 않습니다.

선언·진입 조건: `property`.

직접 연결: [Queue](executor_구현보고서.md#executor-queue-py-Queue-21).


<a id="api-services-py-Services-llm-45"></a>
#### `Services.llm`

<!-- source-symbol: api/services.py:45:Services.llm -->
[services.py](../../backend/analysis/api/services.py#L45)

```python
def llm(self) -> LlmClient: ...
```

주입된 llm_factory가 있으면 그 결과를, 없으면 현재 LlmSettings로 만든 호출기를 반환합니다. 호출기 생성과 실제 LLM 요청은 별개입니다.

직접 연결: [make_llm](common_구현보고서.md#common-llm-py-make_llm-363).

호출하는 코드: [Services.dialog](#api-services-py-Services-dialog-63), [Services.paper](#api-services-py-Services-paper-66).


<a id="api-services-py-Services-market_data-48"></a>
#### `Services.market_data`

<!-- source-symbol: api/services.py:48:Services.market_data -->
[services.py](../../backend/analysis/api/services.py#L48)

```python
def market_data(self) -> MarketData: ...
```

잠금 안에서 프로세스가 재사용하는 MarketData를 반환합니다. 최초 접근, 최신 거래일 변화, 기존 자료 상태 확인 실패 때 캐시를 다시 생성하여 새 거래일을 반영합니다.

직접 연결: [MarketData](m2_data_구현보고서.md#m2_data-market_data-py-MarketData-56).

호출하는 코드: [Services.dialog](#api-services-py-Services-dialog-63), [Services.paper](#api-services-py-Services-paper-66).


<a id="api-services-py-Services-dialog-63"></a>
#### `Services.dialog`

<!-- source-symbol: api/services.py:63:Services.dialog -->
[services.py](../../backend/analysis/api/services.py#L63)

```python
def dialog(self) -> DialogService: ...
```

공유 저장소·Repository·MarketData와 이번 호출용 LLM을 주입한 DialogService를 반환합니다. 대화 이력은 서비스 인스턴스가 아니라 RequestStore에 보존됩니다.

직접 연결: [DialogService](m1_request_구현보고서.md#m1_request-dialog-py-DialogService-81), [Services.market_data](#api-services-py-Services-market_data-48), [Services.llm](#api-services-py-Services-llm-45).


<a id="api-services-py-Services-paper-66"></a>
#### `Services.paper`

<!-- source-symbol: api/services.py:66:Services.paper -->
[services.py](../../backend/analysis/api/services.py#L66)

```python
def paper(self) -> PaperService: ...
```

같은 기반 객체를 주입한 PaperService를 반환합니다. 실제 등록·갱신은 호출자가 해당 메서드를 호출할 때 수행합니다.

직접 연결: [PaperService](m6_tracking_구현보고서.md#m6_tracking-paper-py-PaperService-184), [Services.market_data](#api-services-py-Services-market_data-48), [Services.llm](#api-services-py-Services-llm-45).


<a id="api-services-py-Services-results-69"></a>
#### `Services.results`

<!-- source-symbol: api/services.py:69:Services.results -->
[services.py](../../backend/analysis/api/services.py#L69)

```python
def results(self, report_id: str) -> dict[str, Any] | None: ...
```

report_id로 run_artifact의 results를 읽어 반환하고 최근 최대 8개를 메모리에 보관합니다. 캐시가 차면 먼저 삽입된 항목을 지우므로 접근할 때마다 순서를 바꾸는 LRU 방식은 아닙니다. 저장된 결과가 없으면 None입니다.


<a id="interactions"></a>
## 6. 다른 모듈과의 상호작용

| 상대 모듈 | 전달·반환·저장 관계 |
| --- | --- |
| [M1](m1_request_구현보고서.md) | 프로필 조건·아이디어·답·수정 문장 → DialogService → DialogState |
| [실행기](executor_구현보고서.md) | confirm으로 Queue 등록, 상태 조회는 큐와 DB 단계 기록 결합 |
| [M5](m5_backtest_report_구현보고서.md) | 저장 ReportDoc·ResultsBundle 조회, 근거/시계열/체크포인트 노출, v1 표시 보완 |
| [M6](m6_tracking_구현보고서.md) | 시작 옵션·ID → PaperService → 계획·상세·요약 |
| [공통](common_구현보고서.md) | JsonStore와 분리 Repository·LLM·오류 봉투의 기반 |

라우터는 직접 SQL을 만들지 않습니다. `Services.results()`가 저장된 13_results를 조회하고 근거·차트 API는 이를 필터링합니다. 실행 중 중간 결과 API만 실행 폴더의 파일을 직접 읽습니다.

<a id="verification"></a>
## 7. 오류·제약과 검증 근거

단일 사용자·인증 없는 앱이며 CORS 기본값은 localhost:5173입니다. 공개 서비스용 인증이 이미 구현되었다고 설명하지 않습니다. 업무 예외별 404/409/422/502/503 등은 errors.STATUS에서 결정하고 기타 오류는 500입니다.

경로 limit 입력 전체에 공통 검증이 있는 것은 아닙니다. 근거 페이지 limit만 1~200으로 보정합니다. 건강 조회는 워커 PID 파일 존재와 실제 생존을 구분합니다. 재분석은 원래 overrides를 그대로 복사하므로 명시 과거 기준일도 남을 수 있습니다. 응답 본문 생성·모의투자 처리 등 일부 API 작업은 길어질 수 있습니다.

### 관련 테스트

아래는 테스트 소스에서 확인한 검증 시나리오입니다. 이번 문서 작성에서는 금융 DB·유료 LLM·시나리오 워커를 실행하지 않았으며, 테스트 통과를 새로 보증하는 기록으로 사용하지 않습니다.

- [test_analysis_api.py](../../backend/tests/analysis/test_analysis_api.py): 프로필 버전·대화 확정·워커 연계, 리포트·근거·체크포인트·전체 시계열 API.
- [test_paper.py](../../backend/tests/analysis/test_paper.py): 모의투자 API 등록·갱신·중지·재개와 오류 응답.

### 문서 검증

구문 분석 정의 목록과 대조하여 이 보고서의 클래스 9개와 함수/메서드 57개를 모두 설명했습니다. 상대경로 링크와 내부 앵커를 별도로 확인합니다.
