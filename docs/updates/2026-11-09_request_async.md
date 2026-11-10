# 새 요청: 서버가 번호를 바로 주고 해석은 뒤에서 (2026-11-09)

홈에서 「투자조건 확인하기」를 누른 뒤 해석이 끝나기 전에 새로고침하면 요청이 사라지던 문제를 고쳤다. 새 요청은 서버가 번호를 먼저 돌려주고
의도 해석·첫 질문은 응답 뒤에 서버에서 이어서 한다. 분석 실행(「분석 시작」 → `run_id` 즉시 → 진행 화면이 상태 조회)과 같은 방식이다.
각 항목은 "무엇을 / 왜 / 어디를(파일) / 어떻게 확인했나"를 적는다.

## 1. 문제

- `POST /requests` 가 `DialogService.start()` 안에서 파생값·의도 해석(LLM)·점검(LLM 분류)·첫 질문까지 끝낸 뒤에야 응답했다 (수 초~1분).
  요청 번호(`request_id`)는 서버에서 맨 처음 만들어지지만 화면은 응답이 와야 알 수 있었다.
- 그 사이 새로고침하면 브라우저는 응답을 잃는데, 서버(동기 endpoint)는 끝까지 돌아 요청을 저장했다. 화면에는 아이디어 글자만 남고
  그 요청으로 갈 길이 없었으며, 다시 누르면 같은 요청이 하나 더 생겼다. (Playwright 재현: 서버에는 `draft` 요청이 생겼는데 새로고침한 홈에는
  기다림 표시도 「진행 중이던 분석」도 없음)

## 2. 수정

### 백엔드 (Module1)

- **`backend/analysis/schemas/dialog.py`**: `DialogStatus` 에 `interpreting`(해석 중)·`failed`(첫 해석 실패) 추가. `AnalysisRequestDoc`·`DialogState` 에
  `error_ko`(실패 이유) 추가. 기본값이 있어 예전 요청 파일도 그대로 읽힌다.
  `common/store_schemas/analysis_request.schema.json` 은 모델에서 다시 만들었다 (`model_json_schema()` + `$schema`·`$id`, 기존 파일과 같은 방식).
- **`backend/analysis/m1_request/dialog.py`**
  - `create()`(신규): 프로필·5자 검사 후 요청을 `interpreting` 으로 저장하고 바로 돌려준다. LLM·시장 자료를 부르지 않는다.
  - `run_first_turn(request_id, reraise=False)`(신규): 요청 잠금 안에서 첫 턴(`_turn`)을 돌려 저장. 이미 해석 중이 아니면 아무것도 하지 않는다.
    예외면 저장돼 있던 해석 중 문서에 `failed` + `error_ko` 만 적는다 (MyFinSightError 면 `public_message`, 그 밖은 "서버 오류로 해석을 마치지 못했습니다." 와 로그).
  - `start()`: `create()` + `run_first_turn(reraise=True)`. 재분석(`POST /reports/{id}/rerun`)·수정 요청·테스트는 지금처럼 끝까지 기다렸다 받고 오류도 그대로 응답된다.
  - `state()`: `interpreting` 인 채로 만든 지 15분이 지나면 `failed`("서버가 다시 시작돼 해석이 끊겼습니다.")로 돌려준다 (`_stale`). 저장하지 않으므로
    잠금을 기다리지 않고 서버 프로세스가 여럿이어도 같다. 새 요청 첫 턴은 LLM 두 번(+분류 배치), 호출당 한도 180초라 15분이면 넉넉하다.
- **`backend/analysis/api/routers/requests.py` `create`**: `create()` 결과를 바로 응답하고, FastAPI `BackgroundTasks` 로 응답 뒤에 `run_first_turn()` 을 돈다 (sync 함수라 스레드풀).
- **`backend/analysis/eval/run_scenarios.py`**: `wait_for_first_turn()`(신규) — POST 응답이 해석 중이면 2초 간격으로 다시 읽는다. 실패·시간 초과면 그 상태로
  not_confirmed 기록 (`error_ko` 포함). 시나리오 평가 도구가 바뀐 응답을 받기 위해 필요했다.

### 화면 (Module7)

- **`Front/src/api/types.ts`**: `DialogStatus` 두 값, `DialogState.error_ko`.
- **`Front/src/features/analysis/Interpreting.tsx`(신규)**: 해석 중이면 기존 기다림 표시(`IdeaPending`)를 보여 주고 `usePolling` 으로 2초마다 다시 읽어 끝나면 넘긴다.
  실패면 이유 + 「다시 시도」(같은 아이디어·조건으로 새 요청 → 새 번호로 이동) + 「아이디어 고쳐서 다시 쓰기」(`startNewWith`). 다음 작업(처리 단계 표시)을 붙일 자리.
- **`ClarifyScreen.tsx`**: `interpreting`·`failed` 면 `Interpreting` 을 그린다. **`ConfirmScreen.tsx`**: 두 상태면 질문 화면으로 보낸다.
- **홈은 바꾸지 않았다**: 이미 응답의 번호로 질문 화면으로 가고 `activeRequestId` 를 저장한다. 응답이 0.01초대로 짧아졌을 뿐이다.

### 목업

- **`Front/src/mocks/services/MockService.ts`·`store.ts`**: 새 요청은 번호를 먼저 주고 평소 지연의 15배(기본 약 1.8초) 동안 `interpreting`, 지나면 질문 중
  (목업 시계 `clock` 기준, 상태가 `sessionStorage` 에 있어 새로고침해도 이어짐). 지연 0(테스트)이면 전처럼 바로 질문 중. 재분석·수정 요청은 실제 서버처럼
  해석까지 끝낸 뒤 돌려준다. 고정 요청 `mock_req_interpreting`(계속 해석 중)·`mock_req_failed`(해석 실패) 추가.
- **`Front/src/mocks/MockChrome.tsx`**: 패널 「새 분석」에 「아이디어 해석 중인 요청」·「아이디어 해석에 실패한 요청」.

### 문서

- `docs/Module1.md` 3절(요청 준비: 비동기 생성·실패·멈춤)·4절(저장 필드 `dialog_state`·`error_ko`, 대화 상태 값),
  `docs/Module7.md` 3절(해석 중 화면·새로고침·실패)·4절 API 계약 표.
- `docs/구현보고서/`: m1_request(`create`·`run_first_turn`·`_stale` 항목 추가, `start`·`state`·처리 흐름·오류 절, 함수 수 48 → 51), api(`create`),
  schemas(`dialog_state` 값, `error_ko` 필드 2곳), eval(`wait_for_first_turn` 추가, `run_scenario`, 함수 수 45 → 46), README(함수 합계 647 → 651, 흐름 한 줄).
  앵커의 줄 번호는 기존처럼 2026-10-25 기준 이름표로 두고 새 항목만 지금 줄 번호로 만들었다.
- `Front/docs/mock-mode.md`: 패널 설명, 5절 시나리오 표.

## 3. 바꾸지 않은 것 / 선택지

- **화면이 번호를 정하는 방식(커밋 `c1a5fa6`, 같은 브랜치)을 걷어냈다.** 처음에는 화면이 `req_…_<8hex>` 번호를 만들어 보내고(서버는 형식 검사·중복 409),
  새로고침 뒤 그 번호로 조회했다. 동작은 했지만 (1) 번호를 서버가 만들어 바로 주는 쪽이 오래 걸리는 작업의 일반적인 방식(202 + 작업 번호 + 조회)이고
  이 레포의 분석 실행과도 같으며, (2) 화면에 번호 생성·저장·이어 가기 코드가 필요 없고 주소에 번호가 들어가 새로고침이 저절로 해결되며,
  (3) 클라이언트가 정한 번호에 대한 위조 걱정을 없앤다. 같은 브랜치에 커밋을 더하는 방식으로 바꿨다 (force push 없음).
- **처리 단계 표시(예: 의도 해석 → 후보 분류 2/3)는 다음 작업이다.** 지금 기다림 화면은 고정 3줄과 경과 시간이다. `Interpreting.tsx` 가 그 자리다.
- **시크릿 새 창·다른 브라우저·다른 기기**에서는 홈의 「진행 중이던 분석」이 브라우저 저장소(`activeRequestId`) 기준이라 보이지 않는다.
  배포 전 사람별 데이터 분리(초대 코드) 작업 때 서버의 '내 끝나지 않은 요청'으로 보여 주면 된다. 지금은 사용자가 하나(`default`)라 구분할 수 없다.
- 첫 해석이 실패한 요청은 `failed` 로 파일에 남는다 (`GET /requests` 목록에도 보임, 화면 목록은 이 API 를 쓰지 않음). 재분석·수정 요청이 첫 턴에서 실패해도
  이제 `failed` 파일이 남는다 (전에는 파일이 생기지 않았다).
- 해석 중에는 질문 화면에 「요청 취소」가 없다. 취소는 요청 잠금을 기다리므로 해석이 끝난 뒤에 할 수 있다. 사이드바로 떠날 수는 있다.
- Windows 에서는 해석 중 화면이 요청 파일을 읽는 순간 서버가 같은 파일을 바꾸면(`os.replace`) 드물게 실패할 수 있다(기존 질문 답변에도 있던 성질).
  배포 서버(리눅스)에는 해당하지 않는다.

## 4. 확인 (Windows 11, Python 3.13 `.venv`, Node 24)

이 PC 는 Windows 스마트 앱 컨트롤이 `bt`·`scikit-learn` 의 DLL 을 막아 백테스트(일꾼)를 돌릴 수 없다. 서버 확인은 `bt` 를 빈 모듈로 바꿔 끼운 실행기(레포 밖)로 했다.

- **백엔드 테스트**: `test_analysis_api.py` 의 요청 부분(POST → `interpreting`, GET → 첫 질문)과 새 테스트(첫 턴 실패 → `failed`·`error_ko`, 16분 멈춘 요청 → `failed`, 저장값은 그대로)
  통과. `test_dialog.py` 14개, `test_scenario_qa.py` 의 실행기 테스트(새 `wait_for_first_turn` 포함) 통과.
  `backend/tests/analysis` 전체: 바꾸기 전과 같은 31 failed / 29 errors (모두 백테스트 단계 `bt` 없음에서 비롯), 통과 360.
  **맥·리눅스(백테스트 포함)에서 `pytest backend/tests/analysis` 를 한 번 돌려 확인 필요.**
- **프런트**: `pnpm typecheck` 통과, `pnpm test` 306 passed (새 테스트: 질문 화면 해석 중 → 첫 질문, 실패 → 다시 시도로 새 요청, 확인 화면 → 질문 화면 이동,
  홈 기다림·잠금(응답을 직접 풀어 주는 가짜 서비스), 목업 시계·새로고침 이어짐·재분석 동기·고정 요청).
- **Playwright** (`pnpm build && pnpm preview`, 연습 LLM 의 해석에 8초 지연을 넣은 서버, 데모 SQLite DB)
  - `POST /requests` 응답 0.015초, `state=interpreting`.
  - 보내기 → 2초 안에 `#/analysis/<번호>` + 해석 중 화면 → 8초 뒤 조건 확인 화면(연습 LLM 은 질문 없이 ready). 서버 요청 1개.
  - 해석 중 새로고침 → 같은 해석 중 화면 → 이어서 확인 화면. 요청 1개.
  - 해석 중 브라우저를 닫음(서버 상태 `interpreting`) → 다시 열어 사이트 주소 → 홈 「진행 중이던 분석이 있습니다」 → 「조건 확인 이어서」 → 그 요청의 확인 화면.
  - 첫 해석 실패(일부러 낸 오류) → 「아이디어를 해석하지 못했습니다」 + 이유 + 「다시 시도」 → 새 번호로 해석 중 → 확인 화면. 실패 요청은 `failed` 로 남음.
  - 평소 흐름: 확인 화면 「분석 시작」 → 실행 `queued`, 진행 화면.
  - 목업(`pnpm dev`, `?mock=1`): 새 요청 → 바로 질문 화면 주소 + 해석 중 → 질문. 새로고침해도 요청이 남음. 패널의 해석 중·실패 요청 화면, 실패의 「다시 시도」 → 새 목업 요청.
- 실제 LLM(`api` 모드)으로는 돌리지 않았다. 해석이 실제로 수십 초 걸릴 때 같은 흐름인지 한 번 확인하면 좋다.
