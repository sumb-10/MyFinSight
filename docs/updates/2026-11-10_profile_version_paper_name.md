# 목업 기능 실제 연결 F: 투자조건 변경 이력 비교·모의투자 이름 (2026-11-10)

목업(`?mock=1`)에만 있던 기능 13개 중 묶음 F(5번 변경 이력 비교, 13번 모의투자 이름)를 실제 서버에 연결했다.
다른 묶음과 관계없고 가장 작아 먼저 했다. 각 항목은 "무엇을 / 왜 / 어디를(파일) / 어떻게 확인했나"를 적는다.

## 1. 문제

- **변경 이력 비교:** `GET /profile` 은 과거 버전의 번호·시각·메모만 주고 값은 주지 않는다. 화면의 버전 비교(`features/profile/compare.tsx`)는
  서비스에 `getProfileVersion` 이 있을 때만 열리는데 `HttpService` 에 없어, 일반 모드에서는 「변경 이력 보기」에 비교가 없었다.
  서버는 버전 값 전체를 `profile.json` 에 이미 갖고 있다 (`ProfileStore.version()`).
- **모의투자 이름:** 실제 서버는 모의투자 이름을 항상 원본 리포트의 지금 이름으로 돌려줬다 (커밋 `29a13d5`). 직접 정한 이름(같은 리포트로 여러 모의투자를
  할 때 구분용)을 저장할 곳과 API 가 없어, 화면의 이름 선택·「이름 바꾸기」·「리포트 이름과 다시 연동」이 일반 모드에서는 숨겨져 있었다.

## 2. 수정

### 백엔드

- **`backend/analysis/api/routers/profile.py`**: `GET /profile/versions/{version}` — 그 버전 값 전체 (`GET /profile` 의 `profile` 과 같은 모양, `note` 포함).
  프로필이나 버전이 없으면 404 `NOT_FOUND`, 숫자가 아니면 422 `VALIDATION_ERROR`. 바뀐 필드 목록(`changed_fields`, 명세의 선택 제안)은 넣지 않았다 — 비교는 지금처럼 프런트가 한다.
- **`backend/analysis/m6_tracking/paper_meta.py`(신규)**: `PaperMetaStore` — 직접 정한 이름을 `store/data/paper_meta.json` 에 둔다.
  `portfolio.json` 은 스키마(`paper_portfolio`) 검증을 받는 원본이라 건드리지 않았다 (리포트 이름 `report_meta.json` 과 같은 방식, 스키마 변경 없음).
  linked(기본)는 기록이 없고, custom 만 `{custom_name, renamed_at}` 을 남긴다. `clean_name()`: 연속 공백을 하나로 줄인 뒤 1~40자(리포트 이름과 같은 `NAME_MAX`), 아니면 `REQUEST_INVALID`.
- **`backend/analysis/api/routers/paper.py`**
  - `GET /paper/{paper_id}/name` → `{name_ko, mode, report_name_ko}` (프런트 제안 계약 `ProposedPaperName` 그대로).
  - `PUT /paper/{paper_id}/name` body `{mode: "linked"} | {mode: "custom", name_ko}`. 제안 명세는 `PATCH` 였지만 실제 리포트 이름 API(`PUT /reports/{id}/name`)와 맞췄다.
  - `POST /paper` body 에 `name`(같은 모양, 선택). 이름 검사를 모의투자 생성 **전에** 해서, 이름이 틀리면 모의투자를 만들지 않는다.
  - 목록·상세·갱신·중지·재개 응답의 `name_ko` 를 한 함수(`_namer`)로: 직접 정한 이름 → 원본 리포트의 지금 이름 → 저장된 이름(전략 이름, 리포트를 못 찾을 때).
- **`backend/analysis/api/routers/report_names.py`**: 쓰는 곳이 없어진 `with_report_name` 을 지움 (`_namer` 로 옮김).

### 화면

- **`Front/src/api/service.ts`**: `HttpService.getProfileVersion`·`getPaperName`·`setPaperName`. 메서드가 생겨 일반 모드에서도 버전 비교와 모의투자 이름 기능이 열린다 (화면 코드는 그대로).
- **`Front/src/api/proposed.ts`·`types.ts`**: 이름 입력 타입 `ProposedPaperNameIn`, `PaperIn.name`.
- **`Front/src/features/paper/StartPaperDialog.tsx`**: 등록 뒤 `setPaperName` 을 한 번 더 부르던 것을 `createPaper({ ..., name })` 한 번으로 (등록은 됐는데 이름만 실패하는 경우가 없어짐).
- **`Front/src/features/paper/PaperName.tsx`**: 「목업 화면에서만 바뀌고 실제 서버에는 저장하지 않습니다」 안내를 목업 모드에서만 보여 줌.
- **목업 `MockService.createPaper`**: 실제 서버처럼 `name` 입력을 받는다.
- 「지금은 목업뿐」 주석 정리 (`compare.tsx`·`history.tsx`·`PaperScreen.tsx`).

### 문서

- `Front/docs/backend-integration.md` §2-2·§2-6 에 「✅ 실제 서버 구현」 (실제 경로·본문·검증·저장 위치), 머리말 문장.
- `Front/docs/mock-mode.md` §10(제목·원칙 — 리포트 이름 `29a13d5` 도 함께 지금 상태로)·§13 마지막 문장.

## 3. 바꾸지 않은 것 / 알아 둘 것

- `docs/구현보고서/` 는 고치지 않았다. 2026-10-25 기준 스냅샷이고 리포트 이름 API(`report_names.py`, `29a13d5`)도 아직 들어 있지 않다. 한꺼번에 맞추는 게 낫다.
- 직접 정한 이름이 리포트 이름과 같아도 custom 으로 둔다 (사용자가 「고정」을 고른 것이므로). 리포트 이름은 같으면 자동 이름으로 되돌리는 것과 다르다.
- 모의투자 이름은 사용자 구분 없이 하나의 파일에 있다 (지금 사용자는 `default` 하나). 사람별 데이터 분리 작업 때 함께 나눠야 한다.
- 일반 모드 회귀 테스트(`features/normalMode.test.tsx`)는 제안 메서드를 모두 뺀 서비스로 "기능이 없는 서버"일 때의 화면을 계속 확인한다.

## 4. 확인 (Windows 10, Python 3.12 `.venv`, Node 24)

- **백엔드:** `test_report_orders_names.py` 에 `test_paper_name_custom_and_relink` — 등록 때 직접 이름(공백 정리), 빈 이름이면 등록 안 됨, 리포트 이름을 바꿔도
  직접 이름 유지(`report_name_ko` 는 바뀜), 다시 연동하면 리포트 이름·기록 지워짐, 중지 응답도 같은 이름, 빈 이름·41자 422, 모르는 `mode` 422, 없는 모의투자 404, linked 등록은 기록 없음.
  `test_analysis_api.py::test_profile_validation_and_versions` 에 버전 조회 (프로필 없을 때 404, 버전 1 값·메모, 버전 2 = 현재, 없는 버전 404, 숫자 아님 422).
  `backend/tests/analysis` 전체: 424 passed, 1 failed(`test_executor.py::test_waves_and_parallel_stage_failure`, 혼자 돌리면 통과 — 이전 작업 문서에 적은 기존 불안정 테스트). ruff check 통과.
- **프런트:** `npm run typecheck` 통과, `vitest run` 307 passed. `mocks.test.tsx`: `HttpService` 에 연결된 메서드 목록, 새 메서드 세 개와 `createPaper` 의 `name` 이 보내는 주소·방식·본문.
  (첫 전체 실행에서 `mocks.test.tsx` 의 리포트 제목 찾기가 한 번 시간 초과 — 파일만 돌리면 통과, 다시 전체를 돌려 307 passed. 부하에 따른 기존 성질)
- 브라우저(실제 서버)로는 확인하지 않았다. 화면 코드는 바꾸지 않았고 목업에서 이미 확인한 흐름이라, 연결 경로는 위 HTTP 테스트로 확인했다.
