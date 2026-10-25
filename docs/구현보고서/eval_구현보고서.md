# eval 구현보고서

[전체 안내](README.md)

> 작성 기준: 2026-10-25 작업 공간의 실제 소스. 기존 설계 문서는 배경 참고용이며 아래 동작 설명은 구현을 기준으로 합니다.

대상: Python 파일 4개 · 클래스 1개 · 함수/메서드 45개(중첩 함수와 비공개 보조 함수 포함).

[역할](#role) · [파일 구성](#files) · [처리 흐름](#flow) · [클래스](#classes) · [함수](#functions) · [모듈 연계](#interactions) · [오류·검증](#verification)

<a id="role"></a>
## 1. 모듈의 역할과 용어

`eval`은 분석 기능을 운영·개발 관점에서 점검하는 명령 도구입니다. `run_scenarios`는 실제 API 사용자 흐름을 자동 수행하고, `requirements`는 테스트와 저장 결과를 요구사항별로 묶으며, `grade`는 저장 산출물에서 지표를 추출해 사람이 채점할 뼈대를 만듭니다.

자동 점검은 파일·필드·숫자·문서 구조처럼 기계적으로 확인할 수 있는 사실입니다. 테마 해석이 타당한지, 문장이 자연스러운지, 사용자가 이해하기 쉬운지는 사람이 판단하는 칸으로 남습니다. requirements의 요구사항 R번호는 포트폴리오 검증 규칙 R번호와 다른 체계입니다.

평가 코드도 실제 프로필 저장·DB 연결·워커 실행·LLM 호출을 할 수 있습니다. 이번 보고서 작성에서는 코드를 읽어 설명하며 이 명령을 실제 운영 데이터에 실행하지 않았습니다.

<a id="files"></a>
## 2. 파일 구성과 책임

| 파일 | 책임 | 문서 내 해설 |
| --- | --- | --- |
| [eval/__init__.py](../../backend/analysis/eval/__init__.py) | 패키지 목적 설명; 독립 함수·클래스 정의 없음 | 정의 없음 |
| [eval/grade.py](../../backend/analysis/eval/grade.py) | 저장 실행의 자동 지표·독립 재계산·채점 초안·실행 비교 | [클래스 0 · 함수 17](#file-eval-grade-py) |
| [eval/requirements.py](../../backend/analysis/eval/requirements.py) | 요구사항별 테스트와 저장 결과 점검표 | [클래스 0 · 함수 16](#file-eval-requirements-py) |
| [eval/run_scenarios.py](../../backend/analysis/eval/run_scenarios.py) | 실제 API 시나리오·자동 답·워커·결과 수집 | [클래스 1 · 함수 12](#file-eval-run_scenarios-py) |

<a id="flow"></a>
## 3. 처리 흐름과 예시

| 도구 | 자료 경로 | 결과 | 부수효과 |
| --- | --- | --- | --- |
| run_scenarios | 시나리오 → 실제 API → 큐/워커 | 시나리오 JSON·요약 Markdown | 프로필 버전·요청·실행·결과 추가, 실제 모드면 유료 LLM |
| requirements | pytest + 기본 저장소/결과 DB | 요구사항 점검 Markdown | 테스트 실행·파일 쓰기·DB 연결 |
| grade | 저장된 output·요청·선택 시나리오 | metrics.json·채점 Markdown | 로컬 결과 쓰기, 새 LLM 실행 없음 |

코드의 명령 사용 예시는 다음과 같습니다. 이번 문서 작성에서 실행한 명령 목록이 아닙니다.

```bash
python -m backend.analysis.eval.run_scenarios --list
python -m backend.analysis.eval.run_scenarios --scenarios ai,kr --llm stub --answer all
python -m backend.analysis.eval.requirements --skip-tests
python -m backend.analysis.eval.grade --run run_예시 --scenario backend/test_scenarios/scenario_000.json --out /tmp/grade-example
python -m backend.analysis.eval.grade --compare run_A run_B
```

run_scenarios는 프로필을 저장하고 질문에 first/all/skip 정책으로 응답합니다. ready이면 확정하고 worker --once를 호출합니다. 실행 후 원래 프로필 내용을 새 버전으로 복원하므로 버전 이력·실행 기록은 남습니다. 기존 서버를 재사용하면 새 --llm 환경이 이미 떠 있는 서버에 자동 반영되는 것은 아닙니다.

예를 들어 grade의 CAGR 재계산 일치는 저장 지수에서 수치를 다시 계산했다는 의미입니다. 실제 금융 DB의 과거 원본이 정확한지·시장 가설이 적절한지까지 검증한 결과는 아닙니다. `compare_runs`도 선정·시작 비중·일부 성과·선택 ID 범위의 비교입니다.


<a id="classes"></a>
## 4. 클래스 상세

필드 표는 해당 클래스에서 직접 선언한 필드입니다. 상속 필드는 부모 클래스 설명을 함께 읽습니다. `Field(...)`의 범위는 선언된 검증이며, 서비스에서 추가하는 조건은 함수 설명에 구분합니다.

<a id="eval-run_scenarios-py-Api-51"></a>
### `Api`

<!-- source-symbol: eval/run_scenarios.py:51:Api -->
[run_scenarios.py](../../backend/analysis/eval/run_scenarios.py#L51)

평가 도구에서 실제 HTTP API에 접근하는 작은 클라이언트입니다. base 주소를 보관하며 status/body 반환과 성공 응답 강제 메서드를 나눕니다.

기반: `명시적 부모 없음`.

메서드·속성: [__init__](#eval-run_scenarios-py-Api-__init__-52), [call](#eval-run_scenarios-py-Api-call-55), [ok](#eval-run_scenarios-py-Api-ok-64).


<a id="functions"></a>
## 5. 함수·메서드 상세

시그니처에 입력 자료형·기본값·반환 자료형을 그대로 기재했습니다. `self`는 소속 클래스의 인스턴스, `cls`는 클래스입니다. 반환 주석이 없는 함수는 본문 해설의 반환 내용을 따릅니다. 속성(`property`)은 호출 괄호 없이 읽고, 중첩 함수는 바깥 함수의 지역 상태를 공유합니다. 연결 목록은 정적으로 확인되는 패키지 내부 직접 호출이며, 주입된 서비스·콜백·Repository 호출은 처리 흐름과 해설에서 설명합니다.


<a id="file-eval-grade-py"></a>
### eval/grade.py


<a id="eval-grade-py-_has-45"></a>
#### `_has`

<!-- source-symbol: eval/grade.py:45:_has -->
[grade.py](../../backend/analysis/eval/grade.py#L45)

```python
def _has(doc: dict[str, Any], sid: str, btype: str, title_prefix: str | None=None) -> bool: ...
```

특정 섹션에 블록 타입과 선택 제목 접두사가 일치하는 블록이 있는지 반환합니다. 리포트 12항목 구조 확인에 사용합니다.


<a id="eval-grade-py-_load-55"></a>
#### `_load`

<!-- source-symbol: eval/grade.py:55:_load -->
[grade.py](../../backend/analysis/eval/grade.py#L55)

```python
def _load(p: Path) -> Any: ...
```

존재하는 경로의 JSON을 읽고 파일이 없으면 None을 반환합니다. 잘못된 JSON은 오류입니다.

호출하는 코드: [load_run](#eval-grade-py-load_run-59), [grade_run](#eval-grade-py-grade_run-271), [main](#eval-grade-py-main-353).


<a id="eval-grade-py-load_run-59"></a>
#### `load_run`

<!-- source-symbol: eval/grade.py:59:load_run -->
[grade.py](../../backend/analysis/eval/grade.py#L59)

```python
def load_run(run_id: str) -> dict[str, Any]: ...
```

고정 output/<run_id>에서 단계 JSON·run_meta·LLM 사용량, 고정 data/analysis_store에서 요청 문서를 읽어 묶습니다. 환경변수 경로 함수를 재사용하지 않으므로 경로를 옮긴 실행은 기본 탐색과 다를 수 있습니다.

직접 연결: [_load](#eval-grade-py-_load-55).

호출하는 코드: [grade_run](#eval-grade-py-grade_run-271), [compare_runs](#eval-grade-py-compare_runs-279).

명시적으로 발생시키는 예외: `SystemExit`. 발생 조건은 위 해설과 소스의 분기를 함께 확인합니다.


<a id="eval-grade-py-independent_cagr_mdd-74"></a>
#### `independent_cagr_mdd`

<!-- source-symbol: eval/grade.py:74:independent_cagr_mdd -->
[grade.py](../../backend/analysis/eval/grade.py#L74)

```python
def independent_cagr_mdd(index: list[float], td: int=252) -> tuple[float, float]: ...
```

저장 지수 배열에서 연환산 CAGR과 누적 최고 대비 최대낙폭을 numpy로 독립 재계산합니다. 기본 연간 거래일은 252입니다.

호출하는 코드: [backtest_metrics](#eval-grade-py-backtest_metrics-166).


<a id="eval-grade-py-conditions_metrics-83"></a>
#### `conditions_metrics`

<!-- source-symbol: eval/grade.py:83:conditions_metrics -->
[grade.py](../../backend/analysis/eval/grade.py#L83)

```python
def conditions_metrics(run: dict[str, Any], scenario: dict[str, Any] | None) -> dict[str, Any]: ...
```

시나리오 또는 요청의 포함·제외·시장·현금·상한·일정·기준일·기간·선정 방식·종목 수가 실행에 반영된 사실을 집계합니다. 시나리오 이후 사용자 답변으로 바뀐 의도까지 모두 의미적으로 판정하지는 않습니다.

호출하는 코드: [grade_run](#eval-grade-py-grade_run-271).


<a id="eval-grade-py-dialog_metrics-130"></a>
#### `dialog_metrics`

<!-- source-symbol: eval/grade.py:130:dialog_metrics -->
[grade.py](../../backend/analysis/eval/grade.py#L130)

```python
def dialog_metrics(run: dict[str, Any]) -> dict[str, Any]: ...
```

저장 질문·답·덮어쓰기·보충·충돌·테마·설명 수준·보정 낙폭을 요약합니다. 해석의 자연스러움이나 투자 타당성 점수는 사람이 평가합니다.

호출하는 코드: [grade_run](#eval-grade-py-grade_run-271).


<a id="eval-grade-py-selection_metrics-142"></a>
#### `selection_metrics`

<!-- source-symbol: eval/grade.py:142:selection_metrics -->
[grade.py](../../backend/analysis/eval/grade.py#L142)

```python
def selection_metrics(run: dict[str, Any]) -> dict[str, Any]: ...
```

매칭·후보·테마 통과·지표 보유·선정 수, 선정 표·섹터 분포·불충분 사유·경고를 반환합니다.

호출하는 코드: [grade_run](#eval-grade-py-grade_run-271).


<a id="eval-grade-py-construction_metrics-150"></a>
#### `construction_metrics`

<!-- source-symbol: eval/grade.py:150:construction_metrics -->
[grade.py](../../backend/analysis/eval/grade.py#L150)

```python
def construction_metrics(run: dict[str, Any]) -> dict[str, Any]: ...
```

날짜별 의견의 수와 뉴스/공시/혼합 근거 분류·fallback·시작일 BL·현재 구성 상태를 집계합니다.

호출하는 코드: [grade_run](#eval-grade-py-grade_run-271).


<a id="eval-grade-py-backtest_metrics-166"></a>
#### `backtest_metrics`

<!-- source-symbol: eval/grade.py:166:backtest_metrics -->
[grade.py](../../backend/analysis/eval/grade.py#L166)

```python
def backtest_metrics(run: dict[str, Any]) -> dict[str, Any]: ...
```

각 포트폴리오의 CAGR·MDD를 저장 지수에서 재계산해 허용오차로 비교하고 필요한 지표·동일 적립·검증·맞춤 후보·품질 요약을 반환합니다. 전체 금융 계산의 독립 재구현은 아닙니다.

직접 연결: [independent_cagr_mdd](#eval-grade-py-independent_cagr_mdd-74).

호출하는 코드: [grade_run](#eval-grade-py-grade_run-271).


<a id="eval-grade-py-evidence_metrics-190"></a>
#### `evidence_metrics`

<!-- source-symbol: eval/grade.py:190:evidence_metrics -->
[grade.py](../../backend/analysis/eval/grade.py#L190)

```python
def evidence_metrics(run: dict[str, Any]) -> dict[str, Any]: ...
```

종류별 근거 수·본문 인용 실존·전체 기준일 이후 자료·구성 창 밖 자료·가격 끝 날짜·기업 근거 인용·문서 크기를 점검합니다. 기존 결과 파일만 읽어 평가하며 시장 DB 원본과 각 레코드를 다시 대조하지는 않습니다.

호출하는 코드: [grade_run](#eval-grade-py-grade_run-271).


<a id="eval-grade-py-report_metrics-235"></a>
#### `report_metrics`

<!-- source-symbol: eval/grade.py:235:report_metrics -->
[grade.py](../../backend/analysis/eval/grade.py#L235)

```python
def report_metrics(run: dict[str, Any]) -> dict[str, Any]: ...
```

리포트가 없으면 present=False를 반환합니다. 있으면 기본 AnalysisSettings로 문서 게이트를 재검사하고 일곱 섹션·12항목·문단·용어·공지·대시보드를 집계합니다. 실행 당시 설정 스냅샷 전체를 복구해 검사하는 방식은 아닙니다.

직접 연결: [check](m5_backtest_report_구현보고서.md#m5_backtest_report-report_check-py-check-107), [AnalysisSettings](common_구현보고서.md#settings-py-AnalysisSettings-241).

호출하는 코드: [grade_run](#eval-grade-py-grade_run-271).


<a id="eval-grade-py-execution_metrics-252"></a>
#### `execution_metrics`

<!-- source-symbol: eval/grade.py:252:execution_metrics -->
[grade.py](../../backend/analysis/eval/grade.py#L252)

```python
def execution_metrics(run: dict[str, Any]) -> dict[str, Any]: ...
```

run_meta와 사용량 JSONL에서 시작/끝·소요시간·단계 완결 기록·호출 비용·캐시·잘림·공지·출처를 집계합니다.

호출하는 코드: [grade_run](#eval-grade-py-grade_run-271).


<a id="eval-grade-py-grade_run-271"></a>
#### `grade_run`

<!-- source-symbol: eval/grade.py:271:grade_run -->
[grade.py](../../backend/analysis/eval/grade.py#L271)

```python
def grade_run(run_id: str, scenario_file: str | None) -> dict[str, Any]: ...
```

하나의 저장 실행과 선택 시나리오 파일을 읽어 조건·대화·선정·구성·백테스트·근거·리포트·실행 지표를 묶은 채점 자료를 반환합니다.

직접 연결: [load_run](#eval-grade-py-load_run-59), [_load](#eval-grade-py-_load-55), [conditions_metrics](#eval-grade-py-conditions_metrics-83), [dialog_metrics](#eval-grade-py-dialog_metrics-130), [selection_metrics](#eval-grade-py-selection_metrics-142), [construction_metrics](#eval-grade-py-construction_metrics-150), [backtest_metrics](#eval-grade-py-backtest_metrics-166), [evidence_metrics](#eval-grade-py-evidence_metrics-190), [report_metrics](#eval-grade-py-report_metrics-235), [execution_metrics](#eval-grade-py-execution_metrics-252).

호출하는 코드: [main](#eval-grade-py-main-353).


<a id="eval-grade-py-compare_runs-279"></a>
#### `compare_runs`

<!-- source-symbol: eval/grade.py:279:compare_runs -->
[grade.py](../../backend/analysis/eval/grade.py#L279)

```python
def compare_runs(a: str, b: str) -> dict[str, Any]: ...
```

두 실행의 현재 선정 순서, 시작 타겟 비중, 헤드라인 세 지표, 선택 ID와 캐시 통계를 비교합니다. 비중·성과는 허용오차로 비교하며 모든 날짜별 경로와 문장까지 동일하다는 검사는 아닙니다.

직접 연결: [load_run](#eval-grade-py-load_run-59).

호출하는 코드: [main](#eval-grade-py-main-353).


<a id="eval-grade-py-_yn-296"></a>
#### `_yn`

<!-- source-symbol: eval/grade.py:296:_yn -->
[grade.py](../../backend/analysis/eval/grade.py#L296)

```python
def _yn(v: Any) -> str: ...
```

True·False·그 외 값을 통과/실패/빈 표시 문자열로 바꿉니다.

<details>
<summary>호출하는 코드</summary>

[skeleton_md](#eval-grade-py-skeleton_md-300).

</details>


<a id="eval-grade-py-skeleton_md-300"></a>
#### `skeleton_md`

<!-- source-symbol: eval/grade.py:300:skeleton_md -->
[grade.py](../../backend/analysis/eval/grade.py#L300)

```python
def skeleton_md(tag: str, g: dict[str, Any]) -> str: ...
```

자동 지표 표와 사람이 채울 점수·근거 칸을 가진 채점 Markdown 초안을 만듭니다. 자동으로 의미 품질 점수를 매기지는 않습니다. 일부 라벨에 보정 낙폭을 검증값으로 부르는 구형 문구가 남아 있어 실행 코드 해석과 구분합니다.

직접 연결: [_yn](#eval-grade-py-_yn-296).

호출하는 코드: [main](#eval-grade-py-main-353).


<a id="eval-grade-py-main-353"></a>
#### `main`

<!-- source-symbol: eval/grade.py:353:main -->
[grade.py](../../backend/analysis/eval/grade.py#L353)

```python
def main(argv: list[str] | None=None) -> int: ...
```

--compare면 두 실행 비교 JSON을 출력합니다. --run 또는 --from이면 저장 실행을 채점해 metrics.json을 쓰고 기존 채점 Markdown은 덮어쓰지 않습니다. 사람이 입력한 점수 보존을 위한 동작입니다.

직접 연결: [compare_runs](#eval-grade-py-compare_runs-279), [_load](#eval-grade-py-_load-55), [grade_run](#eval-grade-py-grade_run-271), [skeleton_md](#eval-grade-py-skeleton_md-300).


<a id="file-eval-requirements-py"></a>
### eval/requirements.py


<a id="eval-requirements-py-run_tests-47"></a>
#### `run_tests`

<!-- source-symbol: eval/requirements.py:47:run_tests -->
[requirements.py](../../backend/analysis/eval/requirements.py#L47)

```python
def run_tests(expr: str) -> tuple[bool, str]: ...
```

요구사항별 -k 표현식으로 analysis pytest를 자식 프로세스에서 실행합니다. 종료코드 0과 마지막 줄의 passed를 함께 확인해 성공 여부·요약 문자열을 반환합니다.

호출하는 코드: [main](#eval-requirements-py-main-197).


<a id="eval-requirements-py-_results_db-54"></a>
#### `_results_db`

<!-- source-symbol: eval/requirements.py:54:_results_db -->
[requirements.py](../../backend/analysis/eval/requirements.py#L54)

```python
def _results_db() -> Any: ...
```

기본 분석 Repository를 열고 분리 저장소이면 results를 반환합니다. 읽기 목적으로 보이더라도 Repository 생성 시 연결·준비가 수행될 수 있습니다.

직접 연결: [open_analysis_repository](common_구현보고서.md#common-dbconn-py-open_analysis_repository-75).

호출하는 코드: [evidence_index](#eval-requirements-py-evidence_index-94), [construction_section](#eval-requirements-py-construction_section-106), [performance_section](#eval-requirements-py-performance_section-123), [citations_in_text](#eval-requirements-py-citations_in_text-133), [run_steps](#eval-requirements-py-run_steps-149), [banned_phrases](#eval-requirements-py-banned_phrases-176).


<a id="eval-requirements-py-_store-61"></a>
#### `_store`

<!-- source-symbol: eval/requirements.py:61:_store -->
[requirements.py](../../backend/analysis/eval/requirements.py#L61)

```python
def _store() -> Any: ...
```

기본 경로 JsonStore를 생성해 반환합니다. 디렉터리가 없으면 생성됩니다.

직접 연결: [JsonStore](common_구현보고서.md#common-store-py-JsonStore-34).

호출하는 코드: [profile_versions](#eval-requirements-py-profile_versions-78), [dialog_questions](#eval-requirements-py-dialog_questions-85), [comparisons](#eval-requirements-py-comparisons-161), [papers](#eval-requirements-py-papers-168).


<a id="eval-requirements-py-_reports-67"></a>
#### `_reports`

<!-- source-symbol: eval/requirements.py:67:_reports -->
[requirements.py](../../backend/analysis/eval/requirements.py#L67)

```python
def _reports(repo: Any, limit: int=50) -> list[tuple[str, dict[str, Any], dict[str, Any]]]: ...
```

최대 limit 리포트 메타를 읽고 본문·결과 번들이 모두 있는 (ID,문서,결과) 목록을 반환합니다.

호출하는 코드: [evidence_index](#eval-requirements-py-evidence_index-94), [construction_section](#eval-requirements-py-construction_section-106), [performance_section](#eval-requirements-py-performance_section-123), [citations_in_text](#eval-requirements-py-citations_in_text-133), [banned_phrases](#eval-requirements-py-banned_phrases-176).


<a id="eval-requirements-py-profile_versions-78"></a>
#### `profile_versions`

<!-- source-symbol: eval/requirements.py:78:profile_versions -->
[requirements.py](../../backend/analysis/eval/requirements.py#L78)

```python
def profile_versions() -> str: ...
```

프로필 존재·전체 버전 수·현재 버전을 한국어 요약으로 반환합니다.

직접 연결: [_store](#eval-requirements-py-_store-61).


<a id="eval-requirements-py-dialog_questions-85"></a>
#### `dialog_questions`

<!-- source-symbol: eval/requirements.py:85:dialog_questions -->
[requirements.py](../../backend/analysis/eval/requirements.py#L85)

```python
def dialog_questions() -> str: ...
```

저장 요청의 전체 질문 수·요청당 최대·설정 상한·복수 질문 요청 수를 집계합니다. 대화 적절성 자체를 자동 평가하지는 않습니다.

직접 연결: [RequestStore](common_구현보고서.md#common-store-py-RequestStore-154), [_store](#eval-requirements-py-_store-61).


<a id="eval-requirements-py-evidence_index-94"></a>
#### `evidence_index`

<!-- source-symbol: eval/requirements.py:94:evidence_index -->
[requirements.py](../../backend/analysis/eval/requirements.py#L94)

```python
def evidence_index() -> str: ...
```

저장 결과의 근거 수와 published_at이 as_of보다 늦은 건수를 집계합니다. 공시 available_on 등 모든 종류의 완전한 시점 검증은 grade.evidence_metrics와 실제 게이트를 함께 봐야 합니다.

직접 연결: [_results_db](#eval-requirements-py-_results_db-54), [_reports](#eval-requirements-py-_reports-67).


<a id="eval-requirements-py-construction_section-106"></a>
#### `construction_section`

<!-- source-symbol: eval/requirements.py:106:construction_section -->
[requirements.py](../../backend/analysis/eval/requirements.py#L106)

```python
def construction_section() -> str: ...
```

저장 문서에 비어 있지 않은 construction 섹션이 존재하는 건수를 셉니다.

직접 연결: [_results_db](#eval-requirements-py-_results_db-54), [_reports](#eval-requirements-py-_reports-67).


<a id="eval-requirements-py-report_gate-112"></a>
#### `report_gate`

<!-- source-symbol: eval/requirements.py:112:report_gate -->
[requirements.py](../../backend/analysis/eval/requirements.py#L112)

```python
def report_gate() -> str: ...
```

실행 색인에서 실패 수와 REPORT_CHECK_FAILED/REPORT_INVALID 또는 관련 메시지로 차단된 건수를 집계합니다. 실행을 새로 실패시키는 검사 명령은 아닙니다.

직접 연결: [Queue](executor_구현보고서.md#executor-queue-py-Queue-21), [JsonStore](common_구현보고서.md#common-store-py-JsonStore-34).


<a id="eval-requirements-py-performance_section-123"></a>
#### `performance_section`

<!-- source-symbol: eval/requirements.py:123:performance_section -->
[requirements.py](../../backend/analysis/eval/requirements.py#L123)

```python
def performance_section() -> str: ...
```

과거 성과 섹션과 비교지수 결과가 함께 있는 리포트 수를 집계합니다.

직접 연결: [_results_db](#eval-requirements-py-_results_db-54), [_reports](#eval-requirements-py-_reports-67).


<a id="eval-requirements-py-citations_in_text-133"></a>
#### `citations_in_text`

<!-- source-symbol: eval/requirements.py:133:citations_in_text -->
[requirements.py](../../backend/analysis/eval/requirements.py#L133)

```python
def citations_in_text() -> str: ...
```

paragraphs 블록 인용의 전체 횟수와 색인에 없는 ID 수를 셉니다. 카드·기업·타임라인의 전체 인용을 모두 검사하는 함수는 아닙니다.

직접 연결: [_results_db](#eval-requirements-py-_results_db-54), [_reports](#eval-requirements-py-_reports-67).


<a id="eval-requirements-py-run_steps-149"></a>
#### `run_steps`

<!-- source-symbol: eval/requirements.py:149:run_steps -->
[requirements.py](../../backend/analysis/eval/requirements.py#L149)

```python
def run_steps() -> str: ...
```

저장 리포트에 해당하는 실행의 단계 행 수와 평균을 계산합니다. 리포트 없는 실패 실행의 모든 기록을 포함하지는 않습니다.

직접 연결: [_results_db](#eval-requirements-py-_results_db-54).


<a id="eval-requirements-py-comparisons-161"></a>
#### `comparisons`

<!-- source-symbol: eval/requirements.py:161:comparisons -->
[requirements.py](../../backend/analysis/eval/requirements.py#L161)

```python
def comparisons() -> str: ...
```

로컬 comparisons의 JSON 수와 same_window=True 건수를 반환합니다.

직접 연결: [_store](#eval-requirements-py-_store-61).


<a id="eval-requirements-py-papers-168"></a>
#### `papers`

<!-- source-symbol: eval/requirements.py:168:papers -->
[requirements.py](../../backend/analysis/eval/requirements.py#L168)

```python
def papers() -> str: ...
```

저장 모의투자의 전체·active·그 외 상태 수를 요약합니다.

직접 연결: [PaperStore](common_구현보고서.md#common-store-py-PaperStore-231), [_store](#eval-requirements-py-_store-61).


<a id="eval-requirements-py-banned_phrases-176"></a>
#### `banned_phrases`

<!-- source-symbol: eval/requirements.py:176:banned_phrases -->
[requirements.py](../../backend/analysis/eval/requirements.py#L176)

```python
def banned_phrases() -> str: ...
```

저장 paragraphs의 금지 표현을 훑고 허용 전문 용어·부정형을 제외한 수를 반환합니다. 의미적 수익 보장을 완전히 판별하는 검사는 아닙니다.

직접 연결: [_results_db](#eval-requirements-py-_results_db-54), [_reports](#eval-requirements-py-_reports-67), [_find_all](m5_backtest_report_구현보고서.md#m5_backtest_report-report_check-py-_find_all-50).


<a id="eval-requirements-py-main-197"></a>
#### `main`

<!-- source-symbol: eval/requirements.py:197:main -->
[requirements.py](../../backend/analysis/eval/requirements.py#L197)

```python
def main(argv: list[str] | None=None) -> int: ...
```

요구사항별 pytest와 저장 결과 확인 함수를 실행하고 통과·실패·생략 및 확인 사실을 Markdown에 씁니다. --skip-tests는 테스트만 생략하며 DB·저장소 조회는 여전히 수행합니다. 문장 품질·사용성 등 수동 항목을 별도 표시합니다.

직접 연결: [run_tests](#eval-requirements-py-run_tests-47).


<a id="file-eval-run_scenarios-py"></a>
### eval/run_scenarios.py


<a id="eval-run_scenarios-py-load_request-45"></a>
#### `load_request`

<!-- source-symbol: eval/run_scenarios.py:45:load_request -->
[run_scenarios.py](../../backend/analysis/eval/run_scenarios.py#L45)

```python
def load_request(path: Path) -> dict[str, Any]: ...
```

확장자가 .jsonc면 주석 허용 로더, 나머지는 JSON 로더로 시나리오 요청을 읽습니다.

직접 연결: [load_jsonc](common_구현보고서.md#common-jsonio-py-load_jsonc-15), [load_json](common_구현보고서.md#common-jsonio-py-load_json-23).

호출하는 코드: [run_scenario](#eval-run_scenarios-py-run_scenario-162), [main](#eval-run_scenarios-py-main-229).


<a id="eval-run_scenarios-py-Api-__init__-52"></a>
#### `Api.__init__`

<!-- source-symbol: eval/run_scenarios.py:52:Api.__init__ -->
[run_scenarios.py](../../backend/analysis/eval/run_scenarios.py#L52)

```python
def __init__(self, base: str) -> None: ...
```

API 기본 주소를 보관합니다. 일반 기본값 사용 경로는 /api/v1까지 포함합니다.


<a id="eval-run_scenarios-py-Api-call-55"></a>
#### `Api.call`

<!-- source-symbol: eval/run_scenarios.py:55:Api.call -->
[run_scenarios.py](../../backend/analysis/eval/run_scenarios.py#L55)

```python
def call(self, method: str, path: str, body: Any | None=None) -> tuple[int, Any]: ...
```

urllib로 JSON HTTP 요청을 보내 상태코드·파싱 응답을 반환합니다. HTTPError도 상태·본문 쌍으로 바꾸지만 네트워크 오류·비JSON 응답은 전파합니다. 실제 서버를 변경하는 요청도 보낼 수 있습니다.

호출하는 코드: [Api.ok](#eval-run_scenarios-py-Api-ok-64).


<a id="eval-run_scenarios-py-Api-ok-64"></a>
#### `Api.ok`

<!-- source-symbol: eval/run_scenarios.py:64:Api.ok -->
[run_scenarios.py](../../backend/analysis/eval/run_scenarios.py#L64)

```python
def ok(self, method: str, path: str, body: Any | None=None) -> Any: ...
```

call 결과의 상태가 400 이상이면 요약 RuntimeError, 그 외는 응답 객체를 반환합니다.

직접 연결: [Api.call](#eval-run_scenarios-py-Api-call-55).

명시적으로 발생시키는 예외: `RuntimeError`. 발생 조건은 위 해설과 소스의 분기를 함께 확인합니다.


<a id="eval-run_scenarios-py-ensure_server-71"></a>
#### `ensure_server`

<!-- source-symbol: eval/run_scenarios.py:71:ensure_server -->
[run_scenarios.py](../../backend/analysis/eval/run_scenarios.py#L71)

```python
def ensure_server(api: Api, port: int, env: dict[str, str], log: Path) -> subprocess.Popen | None: ...
```

/health에 접속할 수 있으면 기존 서버를 사용하고 아니면 uvicorn 자식 프로세스를 띄워 최대 90차례 확인합니다. 프로세스 또는 None을 반환합니다. health 응답의 ok와 설정 일치까지 검사하는 것은 아닙니다.

호출하는 코드: [main](#eval-run_scenarios-py-main-229).

명시적으로 발생시키는 예외: `SystemExit`. 발생 조건은 위 해설과 소스의 분기를 함께 확인합니다.


<a id="eval-run_scenarios-py-answer_questions-89"></a>
#### `answer_questions`

<!-- source-symbol: eval/run_scenarios.py:89:answer_questions -->
[run_scenarios.py](../../backend/analysis/eval/run_scenarios.py#L89)

```python
def answer_questions(api: Api, rid: str, state: dict[str, Any], policy: str, log: list[dict[str, Any]]) -> dict[str, Any]: ...
```

first/all/skip 정책으로 질문에 응답하며 각 질문·보기·선택·종류·소요시간을 로그에 남깁니다. first는 첫 질문만 첫 보기, 이후는 건너뛰고 all은 매번 첫 보기입니다. 더 이상 asking 질문이 없으면 현재 상태를 반환합니다.

호출하는 코드: [run_scenario](#eval-run_scenarios-py-run_scenario-162).


<a id="eval-run_scenarios-py-wait_for_run-115"></a>
#### `wait_for_run`

<!-- source-symbol: eval/run_scenarios.py:115:wait_for_run -->
[run_scenarios.py](../../backend/analysis/eval/run_scenarios.py#L115)

```python
def wait_for_run(api: Api, run_id: str, timeout_s: float, poll_s: float=10.0) -> dict[str, Any]: ...
```

실행 상태를 일정 간격으로 조회해 종료 상태 또는 제한시간까지 기다린 뒤 마지막 응답을 반환합니다. 시간 초과 자체를 별도 예외로 만들지는 않습니다.

호출하는 코드: [run_scenario](#eval-run_scenarios-py-run_scenario-162).


<a id="eval-run_scenarios-py-collect-125"></a>
#### `collect`

<!-- source-symbol: eval/run_scenarios.py:125:collect -->
[run_scenarios.py](../../backend/analysis/eval/run_scenarios.py#L125)

```python
def collect(name: str, api: Api, prev: dict[str, Any]) -> dict[str, Any]: ...
```

저장된 run_id의 최신 상태·리포트·검증·성과·사용량을 다시 읽어 기존 시나리오 요약을 갱신합니다. 새 분석은 등록하지 않지만 실제 API에 조회 요청은 보냅니다.

호출하는 코드: [main](#eval-run_scenarios-py-main-229).


<a id="eval-run_scenarios-py-normalize_request-149"></a>
#### `normalize_request`

<!-- source-symbol: eval/run_scenarios.py:149:normalize_request -->
[run_scenarios.py](../../backend/analysis/eval/run_scenarios.py#L149)

```python
def normalize_request(req: dict[str, Any]) -> tuple[dict[str, Any], list[str]]: ...
```

시나리오 요청을 깊은 복사하고 trading_currency가 USD가 아니면 USD로 바꾼 뒤 변경 기록을 반환합니다. 원본 파일은 수정하지 않습니다.

호출하는 코드: [run_scenario](#eval-run_scenarios-py-run_scenario-162).


<a id="eval-run_scenarios-py-run_scenario-162"></a>
#### `run_scenario`

<!-- source-symbol: eval/run_scenarios.py:162:run_scenario -->
[run_scenarios.py](../../backend/analysis/eval/run_scenarios.py#L162)

```python
def run_scenario(name: str, api: Api, env: dict[str, str], policy: str, wait_s: float) -> dict[str, Any]: ...
```

시나리오 프로필을 실제 API에 저장하고 요청 생성·자동 답·확정·worker --once·완료 대기·리포트 수집을 수행합니다. 대화가 ready가 아니면 not_confirmed 결과를 반환합니다. 자식 워커는 큐 전체의 다음 항목을 처리하므로 자기 run_id를 즉시 실행한다고 보장할 수 없습니다.

직접 연결: [normalize_request](#eval-run_scenarios-py-normalize_request-149), [load_request](#eval-run_scenarios-py-load_request-45), [answer_questions](#eval-run_scenarios-py-answer_questions-89), [wait_for_run](#eval-run_scenarios-py-wait_for_run-115).

호출하는 코드: [main](#eval-run_scenarios-py-main-229).


<a id="eval-run_scenarios-py-to_markdown-214"></a>
#### `to_markdown`

<!-- source-symbol: eval/run_scenarios.py:214:to_markdown -->
[run_scenarios.py](../../backend/analysis/eval/run_scenarios.py#L214)

```python
def to_markdown(rows: list[dict[str, Any]], llm: str) -> str: ...
```

시나리오별 상태·질문·추천·선택안·검증·근거·소요시간 표와 오류 요약을 Markdown으로 만듭니다.

호출하는 코드: [main](#eval-run_scenarios-py-main-229).


<a id="eval-run_scenarios-py-main-229"></a>
#### `main`

<!-- source-symbol: eval/run_scenarios.py:229:main -->
[run_scenarios.py](../../backend/analysis/eval/run_scenarios.py#L229)

```python
def main(argv: list[str] | None=None) -> int: ...
```

기본/임의 파일 시나리오·LLM·응답 정책·포트·출력 폴더 옵션을 처리합니다. 서버를 확보하고 시나리오별 JSON·시간표시/최신 요약을 씁니다. 원래 프로필은 finally에서 내용 복원용 새 버전을 추가하고 자신이 띄운 서버는 종료합니다. 실행 기록과 프로필 버전이 완전히 원상복구되는 명령은 아닙니다.

직접 연결: [load_request](#eval-run_scenarios-py-load_request-45), [Api](#eval-run_scenarios-py-Api-51), [ensure_server](#eval-run_scenarios-py-ensure_server-71), [collect](#eval-run_scenarios-py-collect-125), [run_scenario](#eval-run_scenarios-py-run_scenario-162), [to_markdown](#eval-run_scenarios-py-to_markdown-214).

명시적으로 발생시키는 예외: `SystemExit`. 발생 조건은 위 해설과 소스의 분기를 함께 확인합니다.


<a id="interactions"></a>
## 6. 다른 모듈과의 상호작용

run_scenarios는 [API](api_구현보고서.md)의 실제 프로필·대화·확정·조회 경로와 [워커](executor_구현보고서.md)를 사용합니다. 기본 시나리오 일부는 module_mockup/input, kr·lowper는 analysis/examples, 임의 입력은 backend/test_scenarios 등을 받습니다.

requirements는 [기존 테스트](../../backend/tests/analysis/)와 [공통 저장소](common_구현보고서.md)의 기본 경로를 조회합니다. grade는 [M5](m5_backtest_report_구현보고서.md)의 문서 게이트를 재사용하지만 CAGR·MDD는 numpy로 별도 계산해 비교합니다. 결과를 수집·요약하는 코드이며 사용자 요청의 투자전략을 바꾸는 계산 계층은 아닙니다.

<a id="verification"></a>
## 7. 오류·제약과 검증 근거

run_scenarios는 프로필 내용 복원도 새 버전 저장으로 처리하며 기존 서버의 설정을 검증·재시작하지 않습니다. worker --once가 큐의 다른 실행을 처리할 수도 있습니다. --collect와 --skip-tests도 각각 API·DB 조회는 남아 있습니다.

grade의 output·store는 고정 경로이며 실행 당시 설정 전체로 재평가하지 않습니다. 결과 수집이나 일부 검사는 지원 블록만 대상으로 하므로 전체 의미 품질 검증으로 확대 해석하지 않습니다. metrics.json은 갱신하되 기존 사람이 채운 Markdown은 보존합니다. 이 모듈 전용 테스트 파일이 별도로 있는 것은 아니며 기반 기능 테스트와 코드 검토를 근거로 설명합니다.

### 관련 테스트

아래는 테스트 소스에서 확인한 검증 시나리오입니다. 이번 문서 작성에서는 금융 DB·유료 LLM·시나리오 워커를 실행하지 않았으며, 테스트 통과를 새로 보증하는 기록으로 사용하지 않습니다.

- [test_pipeline_e2e.py](../../backend/tests/analysis/test_pipeline_e2e.py): 평가 도구가 읽는 결과·문서·단계 산출물과 수치 계약.
- [test_analysis_api.py](../../backend/tests/analysis/test_analysis_api.py): 시나리오 실행이 이용하는 실제 API 흐름의 테스트.

### 문서 검증

구문 분석 정의 목록과 대조하여 이 보고서의 클래스 1개와 함수/메서드 45개를 모두 설명했습니다. 상대경로 링크와 내부 앵커를 별도로 확인합니다.
