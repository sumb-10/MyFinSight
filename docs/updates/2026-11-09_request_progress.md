# 새 요청: 서버가 지금 어느 단계인지 보여 주기 (2026-11-09)

[새 요청: 서버가 번호를 바로 주고 해석은 뒤에서](2026-11-09_request_async.md)에 이어지는 작업이다. 해석 중 화면이 고정 안내 3줄과 경과 시간만
보여 주던 것을, 서버가 실제로 하고 있는 단계와 그 결과(후보 수·분류 묶음 등)로 바꿨다.
각 항목은 "무엇을 / 왜 / 어디를(파일) / 어떻게 확인했나"를 적는다.

## 1. 문제

- 해석 중 화면(`Interpreting.tsx` → `IdeaPending`)은 「아이디어 이해 / 기본 투자조건과 맞춰 보기 / 꼭 필요한 질문 고르기」 3줄과 경과 시간만 보였다.
  서버가 어디까지 했는지와 관계없는 고정 문구라, 오래 걸리면 멈춘 건지 알 수 없었다.
- 해석 중 멈춤 판정(서버 재시작으로 끊긴 요청)은 **요청을 만든 시각** 기준 15분이었다. 분류 묶음이 많아 오래 걸리면 계속 진행 중이어도 15분이 되는 순간 실패로 보였다.

## 2. 결정

- 단계와 실제 결과를 보여 준다. 새 요청의 **첫 해석만** (답·말로 보태기 턴은 화면이 그 자리에서 기다리므로 그대로). 폴링은 지금처럼 2초.
- 단계: 조건 정리 → 아이디어 해석 → 후보 종목 찾기 → 후보 분류 → 고를 수 있는 종목 확인 → 질문 고르기 (서버 `_turn`·`precheck` 순서 그대로).
- 멈춤 판정은 **마지막 진행 시각**(단계가 바뀌거나 분류 묶음이 하나 끝난 때) 기준 15분으로 바꾼다. 진짜로 끊기면 전처럼 15분 뒤에 알고, 오래 걸려도 진행 중이면 실패로 보이지 않는다.
- 새 모듈은 만들지 않았다 (Module1 요청 준비의 일부). 단계 기록만 `m1_request/progress.py` 로 나눴다.

## 3. 수정

### 백엔드 (Module1, Module3)

- **`backend/analysis/schemas/dialog.py`**: `ProgressStep`(key·label_ko·status `waiting|running|done|skipped`·detail_ko) 추가.
  `AnalysisRequestDoc` 에 `progress`·`progress_updated_at`, `DialogState` 에 `progress`. 기본값이 있어 예전 요청 파일도 그대로 읽힌다.
  `common/store_schemas/analysis_request.schema.json` 은 모델에서 다시 만들었다 (새 필드를 빼면 기존 파일과 글자 하나까지 같음을 확인).
- **`backend/analysis/m1_request/progress.py`(신규)**: 6단계 정의(`STEPS`)와 기록기 `Progress`(`step`·`close`), 첫 턴용 `for_request`, 결과 문구 `themes_ko`·`screen_ko`.
  `for_request` 는 단계가 바뀔 때마다 **저장된 요청 문서를 다시 읽어 `progress`·`progress_updated_at` 만 바꿔** 쓴다.
  `_turn` 이 고치는 중인 문서를 그대로 쓰면, 실패 처리("저장된 해석 중 문서에 실패만 적음")가 반쯤 고친 문서를 저장하게 되기 때문이다.
  `run_first_turn` 이 요청 잠금을 쥐고 있으므로 따로 잠그지 않는다. 저장이 실패해도(아래 4절) 로그만 남기고 해석은 계속한다.
- **`backend/analysis/m1_request/dialog.py`**
  - `create()`: 6단계를 모두 대기로 넣어 저장 (POST 응답부터 단계 목록이 보임).
  - `run_first_turn()`: `_turn(doc, progress=for_request(...))`. 실패하면 저장된 문서를 다시 읽으므로 멈춘 단계가 진행 중으로 남는다 → 화면이 「여기서 멈춤」으로 보여 줌.
  - `_turn(doc, *, progress=None)`: 단계마다 기록. 조건 정리(기준일·백테스트 기간), 아이디어 해석(테마 이름), 점검 단계는 `precheck` 에 콜백으로 넘김,
    고를 수 있는 종목 확인(기준일·시작일 종목 수), 질문 고르기(「X」 묻기 / 더 물을 것 없음). HARD 오류로 일찍 끝나면 남은 단계 건너뜀,
    점검이 예외면 점검 세 단계 「점검하지 못해 건너뜀」. 답·말로 보태기 턴은 `progress` 없이 불러 아무것도 기록하지 않는다.
  - `state()`: `progress` 를 내보내고, 멈춤 판정을 `_stale(progress_updated_at or created_at)` 로.
- **`backend/analysis/m1_request/precheck.py` `precheck(..., progress=None)`**: 후보 찾기 시작(「가격 자료 읽는 중」)·끝(후보 수), 분류 시작·묶음 i/n·끝(테마에 맞는 종목 수)
  또는 건너뜀, 확인 시작을 알린다.
- **`backend/analysis/m3_selection/classify.py` `classify(..., on_batch=None)`**: 시작할 때 (0, n), 묶음을 받을 때마다 (i, n).
  `map_ordered` 에 이미 있던 `on_done` 으로 넘겨, 동시 실행이어도 주 스레드에서 순서대로 센다. (`map_ordered` 는 목록을 다 모아 돌려주므로
  결과를 도는 반복문에서 세면 마지막에 한꺼번에 불린다 — 처음 그렇게 짰다가 고침.)

### 화면 (Module7)

- **`Front/src/api/types.ts`**: `ProgressStep`, `DialogState.progress`.
- **`Front/src/features/analysis/flow.tsx`**: `ProgressList`(신규) — ✓ 완료 · 돌아가는 표시 진행 중 · 번호 대기 · – 건너뜀, 단계 이름 옆에 결과 문구.
  실패 화면용 `stopped` 면 진행 중이던 단계를 빨간 「여기서 멈춤」으로. 화면 읽기 프로그램에는 상태를 괄호로 읽어 준다.
  `IdeaPending({ steps })`: 단계가 오면 `ProgressList`, 안 오면(예전 서버) 전처럼 고정 3줄.
- **`Front/src/features/analysis/Interpreting.tsx`**: 2초마다 받은 최신 응답의 `progress` 를 넘기고, 실패 화면에 멈춘 단계 목록을 보여 준다.

### 목업

- **`Front/src/mocks/data/dialog.ts` `mockProgress`(신규)**, **`MockService.ts`·`store.ts`**: 새 요청의 해석 중 시간을 평소 지연의 15배(1.8초) → **50배(6초)** 로 늘리고,
  지난 시간만큼 6단계가 차례로 진행된다 (1.8초면 2초 폴링에서 단계가 나아가는 것을 볼 수 없음). 결과 문구는 목업 질문에 맞춘 값.
  `mock_req_interpreting` 은 「후보 분류 1/2 묶음」에 머물고, `mock_req_failed` 는 「아이디어 해석」에서 멈춘 모습. 재분석·수정 요청의 기다림(15배)은 그대로.

### 문서

- `docs/Module1.md`(요청 준비: 단계 기록·멈춤 판정), `docs/Module3.md`(분류 묶음 진행), `docs/Module7.md`(해석 중·실패 화면).
- `docs/구현보고서/`: m1_request(`progress.py` 절·`Progress` 클래스 추가, `create`·`run_first_turn`·`_turn`·`state`·`_stale`·`precheck`·처리 흐름·오류 절,
  파일 9 → 10, 클래스 1 → 2, 함수 51 → 58), schemas(`ProgressStep` 추가, 필드 3곳, 클래스 79 → 80), m3_selection(`classify` 의 `on_batch`),
  README(파일 89 → 90, 클래스 142 → 144, 함수 651 → 658). 앵커 줄 번호는 기존 이름표 그대로, 새 항목만 지금 줄 번호.
- `Front/docs/mock-mode.md`: 5절 시나리오 표.

## 4. 바꾸지 않은 것 / 알아 둘 것

- **가장 오래 걸리는 단계는 LLM 이 아니라 「후보 종목 찾기」였다.** 서버를 켠 뒤 첫 요청에서 `precheck` 의 가격 자료 선적재(`md.prefetch`, 읽기 PostgreSQL)가
  약 45초 걸렸다 (연습 LLM 이라 LLM 은 0초). 그래서 이 단계에 「가격 자료 읽는 중」을 붙였다. 두 번째 요청부터는 메모리에 있어 빠르다.
  선적재를 서버 시작 때 미리 하는 것은 이번 범위 밖이다.
- 답·말로 보태기 턴의 단계 표시는 하지 않았다 (결정 사항). 이 턴들은 요청 문서의 `progress` 를 건드리지 않아 첫 해석 기록이 그대로 남는다.
- 경과 시간(「n초 경과」)은 화면이 처음 그려진 때부터 센다. 해석 중에 새로고침하면 0초부터 다시 센다 (전과 같음).
- Windows 에서 화면이 요청 파일을 읽는 순간 서버가 같은 파일을 바꾸면(`os.replace`) 드물게 실패할 수 있다 (1번 작업 문서에 적은 성질). 단계 저장이 잦아져
  만날 가능성이 조금 늘어서, 단계 저장 실패는 해석을 멈추지 않게 했다. 배포 서버(리눅스)에는 해당하지 않는다.
- 분류 묶음 「0/2 묶음」은 분류를 막 시작한 순간에만 잠깐 보인다.

## 5. 확인 (Windows 10, Python 3.12 `.venv`, Node 24)

- **백엔드 테스트**
  - 새 `test_request_progress.py`(3개): 단계 시작 시 앞 단계 완료·건너뜀 닫기·저장 횟수, 결과 문구, 분류 묶음 알림(순차·동시 모두 `(0,3)…(3,3)`).
  - `test_analysis_api.py`: 새 `test_new_request_progress` — POST 응답은 6단계 모두 대기, **LLM 이 해석하는 도중 저장된 문서를 읽으면** 「조건 정리 완료 · 아이디어 해석 진행 중」,
    끝나면 모두 완료·건너뜀과 결과 문구, 실패하면 「아이디어 해석」이 진행 중으로 남음. 기존 멈춤 테스트에 「16분 전에 만들었어도 1분 전에 진행했으면 해석 중」 추가.
  - 처음 돌렸을 때 `test_scenario_qa.py` 7개가 깨졌다. 가짜 점검 결과에 날짜가 없어 결과 문구 만들기가 예외를 냈고, 그 코드가 점검 `try` 안에 있어 **점검 결과 자체가 버려졌다.**
    문구 만들기를 `try` 밖(`else`)으로 옮기고 빠진 값에도 예외를 내지 않게 고쳐 통과.
  - `backend/tests/analysis` 전체: 423 passed, 1 failed(`test_executor.py::test_waves_and_parallel_stage_failure`). 이 테스트는 `time.sleep` 으로 시간을 재는 테스트라
    전체를 돌릴 때만 실패하고 혼자 돌리면 통과한다 (바꾼 코드에서 3번 연속 통과). 바꾸기 전 코드(HEAD `f1604ce`, 따로 만든 worktree)로 전체를 돌려도
    같은 테스트 하나만 실패한다 (419 passed, 1 failed). 원래 있던 불안정한 테스트이고 이번 변경과는 관계없다.
    이 PC 는 이번에 `bt`·`scikit-learn` 이 막히지 않아 백테스트 테스트까지 돌았다 (1번 작업 때 못 돌린 것).
- **프런트**: `npm run typecheck` 통과, `vitest run` 306 passed (flowUx: 해석 중 화면에 서버 단계 6개·진행 중 표시, 실패 화면에 「여기서 멈춤」과 결과 문구 /
  목업: 시작 시 첫 단계 진행 중, 절반 지나면 「후보 분류 1/2 묶음」, 고정 실패 요청은 「아이디어 해석」에서 멈춤).
- **Playwright** (playwright-cli 스킬이 이 PC 에 없어 Node 스크립트로)
  - 고치기 전(목업 `npm run dev` + `?mock=1`): 해석 중 화면은 고정 3줄 + 경과 시간 → 1.8초 뒤 질문.
  - 고친 뒤(목업): 새 요청 0.5초 「조건 정리 진행 중」 → 2.6초 「후보 종목 찾기 진행 중」(앞 두 단계는 기준일·테마와 함께 완료) → 해석 중 새로고침 → 5.5초 「질문 고르기 진행 중」 → 질문 화면.
    패널의 해석 중 요청(「후보 분류 1/2 묶음」), 실패 요청(「아이디어 해석 · 여기서 멈춤」).
  - 고친 뒤(**실제 백엔드**, 연습 LLM `MYFINSIGHT_LLM=stub`, 읽기 PostgreSQL): API 를 0.3초마다 읽어 대기 → 조건 정리 → 「후보 종목 찾기 · 가격 자료 읽는 중」(약 48초)
    → 분류·확인 → `ready` 로 바뀌는 것을 확인. 브라우저(`npm run dev`, 일반 모드)에서도 같은 순서로 보이고 해석 중 새로고침해도 이어지며, 끝나면 조건 확인 화면.
- 실제 LLM(`api` 모드)으로는 돌리지 않았다 (비용). 실제 LLM 이면 「아이디어 해석」과 「후보 분류 i/n 묶음」에서 각각 수 초~수십 초 머물 것이다.
