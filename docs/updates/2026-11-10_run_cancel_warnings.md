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
- 취소는 **단계 안에서도 바로 멈춘다** (처음에는 단계 사이에서만 멈추게 두었다가 같은 날 보탬, 6절). LLM 응답·재시도를 기다리는 중과 백테스트 포트폴리오마다 확인해 `immediate: true`.
  실제 실행 127개에서 단계 안 확인이 없던 단계는 중앙값 17~108초(리포트 생성 108초)라, 단계 사이에서만 멈추면 취소에 수십 초~2분이 걸렸다.
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

## 6. 즉시 취소 (같은 날 보탬)

처음 커밋에서는 취소를 단계 사이·분류 묶음·날짜별 경로에서만 확인해 `immediate: false` 였다. 이슈의 9번이 「즉시 취소」 를 포함하므로 서버가 단계 안에서도 바로 멈추게 했다.

- **`backend/analysis/common/llm.py`:** `cancel_check`(러너가 꽂음). 취소 확인이 있으면 응답을 별도 스레드에서 기다리며 0.25초마다 확인하고, 취소면 응답을 기다리지 않고 `CancelRequested`
  (이미 보낸 요청은 뒤에서 끝나고 버려진다 — 그 호출 비용은 나간다). 재시도 대기(백오프)도 취소를 보며 잔다. `complete_json` 은 취소를 「답이 틀림」으로 다시 묻지 않고 그대로 던진다.
  취소 확인이 없는 대화 단계는 예전처럼 바로 부른다.
- **`backend/analysis/m5_backtest_report/backtest.py`:** `run_backtest(..., cancel_check=)` — 비교지수·포트폴리오 하나를 돌리기 전마다 확인.
- **`backend/analysis/executor/runner.py`:** 시작할 때 `ctx.llm.cancel_check = ctx.cancel_check`. 단계가 끝난 직후에도 확인해, 단계 코드가 취소를 잡아 대체 계산으로 끝냈어도
  다음으로 가지 않는다 (끝난 단계는 SUCCESS 그대로, 실행은 취소 → 리포트 단계였어도 저장하지 않음). 취소 중에 단계가 다른 오류로 끝나면 실패가 아니라 취소.
- **`backend/analysis/executor/worker.py`:** `cancel_poller` — LLM 대기 중 자주 불리므로 `runs.json` 은 0.5초에 한 번만 읽고, 한 번 취소면 계속 True.
- **`runs.py` `cancel_view`:** `immediate: true`. 멈춘 단계 마지막 규칙 「마지막으로 끝난 단계」(마지막 단계가 끝난 뒤 취소가 반영된 경우).
- **화면:** 즉시 취소 문구의 「(목업: 즉시 취소)」 꼬리는 목업에서만.
- **테스트:** 응답 5초짜리 호출을 0.3초에 취소 → 1.5초 안에 `CancelRequested`, 재시도 대기 중 취소, 취소 확인 없을 때 예전처럼, 러너(LLM 단계 바로 멈춤·취소를 삼킨 단계·다른 오류로 바뀐 취소),
  백테스트 포트폴리오마다, `cancel_poller` 간격·고정. 기존 「단계 경계 취소」 테스트(끝난 단계는 SUCCESS)도 그대로 통과.
- **01 단계 가격 대량 적재 (처음 빠뜨림):** 화면 확인에서 「투자조건 확정과 자료 준비」 중 취소가 42초 걸렸다 (서버를 켠 뒤 첫 실행이라 `md.prefetch` 의
  DB 쿼리 한 번이 오래 걸림, 단계 안 확인 없음). `executor/parallel.py` 의 `wait_cancellable` 로 적재를 별도 스레드에서 돌리며 0.25초마다 확인 →
  취소면 기다리지 않고 멈추고, 적재는 뒤에서 끝나 캐시에 남아 다음 실행이 그대로 쓴다.
- **10·10f·10w 포트폴리오 구성:** `construct`(뉴스 조회 DB·LLM 뷰·최적화)는 ctx 를 건드리지 않는 순수 함수라 호출 전체를 `wait_cancellable` 로 감쌌다
  (10w 는 날짜마다). 뉴스 조회 쿼리·최적화 중에도 바로 멈추고, 버려진 호출 안의 LLM 은 취소 확인으로 곧 끝난다.
- **남은 것:** 포트폴리오 하나 백테스트(1~3초), 기술자료(descriptor) 읽기, 시작일 재선정에서 가격 범위가 넓어져 다시 적재하는 드문 경우(`price reload` 로그).
- **취소된 실행에 남는 것:** 결과·리포트·수정안 비교는 저장하지 않는다 (리포트 목록·모의투자에 나타나지 않음). 실행 기록(runs.json, 상태 cancelled)·단계 기록(run_step)·
  실행 폴더의 중간 파일은 기록으로 남고, 요청은 확정 상태 그대로라 「같은 조건으로 다시 실행」(새 run_id) 할 수 있다. 이미 쓴 LLM 비용은 돌아오지 않는다.

## 7. 멈춘 곳부터 이어서 실행 (같은 날 보탬)

취소한 분석을 멈춘 곳부터 이어서 돌리고, 분석 진행 화면을 떠나 홈으로 가도 이어 갈 수 있게 했다.

- **방식 (체크포인트가 아니라 캐시):** 「이어서 실행」 = 같은 확정 요청으로 새 실행 (`POST /runs/{id}/retry`, 기준일·백테스트 기간도 그대로). 1단계부터 다시 돌지만
  취소 전에 받은 LLM 답은 캐시(키 = 모델·단계·보낸 문장)에서 꺼내 쓰므로 끝난 단계는 빠르게 지나가고 LLM 비용을 다시 쓰지 않는다. 결과는 끊지 않고 끝까지 돌렸을 때와 같다.
  숫자 계산(가격 적재·뉴스 조회·최적화·백테스트)은 다시 한다. 진짜 체크포인트(끝난 단계를 아예 건너뜀)는 단계 산출물 전체를 저장·복원해야 해 하지 않았다.
- **`backend/analysis/common/llm.py`:** 응답 뒤처리(사용량 기록·원문 저장·JSON 해석·캐시 쓰기)를 `_finish` 로 떼어 내고, 취소로 버린 호출의 응답이 늦게 오면
  `_wait` 의 `on_late` 로 같은 뒤처리를 거쳐 캐시에 남긴다 → 취소 순간 진행 중이던 LLM 답도 이어서 실행할 때 다시 사지 않는다 (오류·잘린 응답은 남기지 않음).
- **`backend/analysis/api/routers/runs.py`:** `GET /runs` 행에 `resumable`·`idea`. 취소된 실행이고, 그 요청의 마지막 실행이 아직 이것(다시 실행하지 않음)이고, 요청이 확정 상태면 true.
  그때만 투자 아이디어를 채운다 (홈 카드용, 다른 행은 요청 파일을 읽지 않음).
- **화면:** 분석 진행 화면의 취소된 실행 버튼 「같은 조건으로 다시 실행」 → **「멈춘 곳부터 이어서 실행」** + 「취소 전에 끝난 단계는 저장된 결과를 다시 써서 빠르게 지나갑니다」.
  홈에 **「취소한 분석이 있습니다」** 카드 (서버 실행 목록 기준이라 다른 브라우저에서도 보임) — 「멈춘 곳부터 이어서 실행」·「취소한 분석 보기」·「지우기」(이 브라우저에서만 숨김,
  `uiStorage.dismissedResumeIds`). 같은 실행이면 「진행 중이던 분석이 있습니다」 카드는 겹쳐 띄우지 않는다. 목업도 같은 규칙(같은 요청의 가장 최근 실행이 취소)으로 `resumable`.
- **테스트:** 취소 0.2초 뒤 0.6초에 온 답이 캐시에 남고 다음 실행은 서버를 부르지 않음, `GET /runs` 의 `resumable`·`idea` 와 이어서 실행 뒤 false,
  홈 카드(이어서 실행 → 새 실행 화면, 다시 뜨지 않음, 지우기). 목업 화면 캡처로 확인 (기본 목업 홈에는 카드 없음 → 진행 재생 취소 → 홈 카드 → 이어서 실행).
  `backend/tests` 755 passed (1 failed: test_executor 기존 불안정 테스트), Front 310 passed.
