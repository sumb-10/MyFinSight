# 목업 기능 실제 연결 D: 분석 진행의 경고 전체·취소 결과 (2026-11-10)

이슈 #14 묶음 D(9번 즉시 취소와 취소 결과, 10번 경고 전체 목록)를 실제 서버에 연결했다.
각 항목은 "무엇을 / 왜 / 어디를(파일) / 어떻게 확인했나"를 적는다.

## 1. 문제

- **경고 전체(10번):** 분석 진행 화면의 「확인할 점」은 단계 요약(`run_step.summary`)의 「확인 필요 N건: a; b」 에서 2건까지만 읽었다.
  서버는 단계별 경고를 실행 메모리(`ctx.warnings`)에만 두고 분석이 끝나야 `run_meta.json` 에 썼고, 전체를 주는 API 가 없었다.
- **취소 결과(9번):** 취소를 누르면 「요청」만 되고, 언제·어느 단계에서 멈췄는지·끝난 단계가 몇 개인지 응답에 없었다. 화면의 「분석 취소 완료」 카드는 목업에서만 보였다.

## 2. 결정

- 경고는 **단계 요약과 같은 규칙**으로 센다: 같은 경고는 `merge` 로 묶어 `count`, level 이 user 인 것만 → 단계별 줄 수 = 요약의 N.
- 끝난 단계의 경고만 (실패·취소된 단계의 경고는 요약에도 없다).
- 취소는 **지금처럼 단계 사이·LLM 묶음 사이에서 멈춘다**. 도는 계산(백테스트 등)을 바로 끊는 진짜 즉시 취소는 이번 범위 밖이라 `immediate: false` 로 사실대로 알린다
  (화면은 「현재 작업이 종료되는 데 시간이 걸릴 수 있습니다」).
- 필드 이름은 제안 명세의 정식 이름 `cancel` (프런트 임시 위치 `proposed_cancel` 은 목업과 함께 바꿈).

## 3. 수정

### 백엔드

- **`backend/analysis/executor/step_warnings.py`(신규):** `user_warnings`(요약과 같은 규칙), `save`/`load`(`step_warnings.json`, 없으면 예전 실행의 `run_meta.json` 에서 다시 만듦),
  `api_rows`(단계 순서, `{step, step_label_ko, message_ko, count}`).
- **`backend/analysis/executor/runner.py`:** 단계가 끝날 때마다(SUCCESS·PARTIAL) 그 단계의 사용자 경고를 모아 `step_warnings.json` 에 쓴다.
  동시에 도는 단계가 있으므로 모으기·쓰기를 모두 기존 `io_lock` 안에서. `dump=False`(테스트)면 쓰지 않는다.
- **`backend/analysis/api/routers/runs.py`:**
  - `GET /runs/{id}/warnings` (없는 실행 404).
  - `cancel_view` → `GET /runs/{id}`·`POST /runs/{id}/cancel` 응답의 `cancel`. 취소를 요청했고 `running`(= 화면의 cancelling) 이거나 `cancelled` 인 실행만.
    멈춘 단계: 취소 중이면 지금 도는 단계, 끝났으면 도중에 멈춘 단계(시작했는데 CANCELLED) → 없으면 다음 차례였던 단계, 대기 중 취소면 없음. `done_steps` = SUCCESS·PARTIAL 수.
- **`backend/analysis/schemas/run.py`:** `RunStatus.cancel`.

### 화면

- **`Front/src/api/service.ts`:** `HttpService.getRunWarnings` → 실제 모드에서도 「확인할 점」 전체(같은 문구 묶음·나온 단계·횟수)가 열린다.
- **`Front/src/api/proposed.ts`:** `proposedCancelOf` 가 정식 필드 `cancel` 을 읽는다. 목업(`mocks/data/runs.ts`·`MockService`)도 `proposed_cancel` → `cancel`.
- 「목업에서만」 주석 정리 (`RunScreen.tsx`·`steps.ts`). 「분석 취소 완료」 카드의 「목업」 표시는 원래 목업 모드에서만 보인다.

### 문서

- `Front/docs/backend-integration.md` §2-9·§2-10 「✅ 실제 서버 구현」, 1절 확장 필드 표. `Front/docs/mock-mode.md` 실행 필드 이름.

## 4. 바꾸지 않은 것 / 알아 둘 것

- 진짜 즉시 취소(도는 백테스트를 끊기)는 하지 않았다. 필요하면 백테스트 루프 안에 취소 확인을 넣는 작업이 따로 있다.
- 끝난 실행을 취소하면 지금처럼 그 상태를 돌려준다 (명세의 409 는 아님).
- 경고 ID 가 없어 화면의 「새 경고」 알림은 지금처럼 문구로 구분한다.
- `test_executor.py::test_waves_and_parallel_stage_failure` 는 `dump=False` 로 돌아 이번 파일 쓰기를 거치지 않는다. 스레드 순서에 기대는 기존 불안정 테스트다:
  같은 웨이브에서 `c` 가 바로 실패하면 빈자리로 늦게 들어간 `d` 가 「이미 실패」를 보고 CANCELLED 가 된다. 이 변경 전 커밋(`7186eb4`)에서도 실행기 파일만 돌려 3번 중 2번 실패했다.
  테스트 자체를 고치는 일은 따로 남긴다.

## 5. 확인 (Windows 10, Python 3.12 `.venv`, Node 24)

브랜치는 `feature/request-progress` 에서 따고 공유 테스트 구조 커밋(`cceec8d`)을 병합해 두었다 (`CONNECTED` 의 D 자리에 `getRunWarnings`). 묶음 A·F 와 충돌하지 않는다.

- **백엔드:** 새 `test_run_warnings_cancel.py` — 러너가 단계마다 파일을 씀(다음 단계가 실행 중에 앞 단계 경고를 읽음), 같은 경고 count 2·info 제외·실패 단계 제외,
  단계별 줄 수 = 요약 N, `run_meta.json` 에서 다시 만들기, API(단계 순서·한국어 단계 이름·404), 취소 상태 5가지(취소 중·도중 멈춤·단계 사이·대기 중·요청 없음/끝남).
  실제 실행 기록 24개로 다시 만든 목록의 단계별 수가 요약의 「확인 필요 N건」 과 모두 같음을 확인.
- **전체:** `backend/tests/analysis` 427 passed, 1 failed(위 불안정 테스트). Front `vitest run` 308 passed.
- **프런트:** `npm run typecheck` 통과, `mocks.test.tsx`(요청 주소, `cancel` 읽기), `run.mock.test.tsx`(실제 서버 모양 `immediate:false` — 취소 중 문구, 취소 완료 카드·걸린 시간·멈춘 단계, 목업 표시 없음).
