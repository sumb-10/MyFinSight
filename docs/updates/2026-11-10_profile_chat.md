# 목업 기능 실제 연결 B-1: 대화형 초기 투자조건 (2026-11-10)

이슈 #14 묶음 B(투자조건 규칙)의 1번 「대화형 초기 투자조건」을 실제 서버에 연결했다.
각 항목은 "무엇을 / 왜 / 어디를(파일) / 어떻게 확인했나"를 적는다.

## 1. 문제

- 투자조건이 없는 사용자가 앱을 열면 목업은 챗봇처럼 필수 11문항만 묻는 대화형 설정(`#/profile/chat`)으로 보냈다.
  실제 서버에는 대화 API 가 없어 `HttpService` 에 대화 메서드가 없었고, 실제 모드의 처음 사용자는 기존 4단계 폼으로만 갔다.
- 질문 순서·보기·답 반영·다시 묻기·「고치기」 규칙은 모두 목업 엔진(`Front/src/mocks/data/profileChat.ts`)에만 있었다.

## 2. 결정

- **목업 대화를 그대로 서버로 옮긴다** (사용자 결정). 고정 11문항, 답은 보기 버튼·숫자 입력만 (LLM·자유 문장 해석 없음 — 요청 문서 2절은 이번 범위 밖).
- 묻지 않는 항목의 기본값은 프런트 `features/profile/defaults.ts` 와 같은 값을 서버가 갖는다.
- 저장은 기존 `PUT /profile` 그대로. 대화 API 는 초안만 만든다. 투자조건이 이미 있는 사용자도 대화를 쓸 수 있다 (저장하면 새 버전).
- 맞지 않는 답(범위 밖·없는 보기·필수 건너뛰기)은 **200 + 봇의 다시 묻는 말풍선**(목업과 같음), 지금 차례가 아닌 질문은 409.
- 요약(`review`)으로 넘어가기 전에 `PUT /profile` 과 같은 검사를 한다 → 대화로 만든 초안이 저장 때 거절되지 않는다.
- 「종목을 고르는 기준」의 추천은 서버 규칙 `recommend()`(B-4, `GET /strategy/recommendation` 과 같은 표).
- 처음 투자금 0원(B-3)은 금액 질문의 보기 「0원 · 매월 적립으로 시작」으로만 고른다(직접 입력은 10만원부터). 0원이면 월 적립 질문은 「추가 투자 없음」을 숨기고 0원을 받지 않으며, 요약에서 금액을 0원으로 고치면 「추가 투자 없음」이던 월 적립만 지워 다시 묻는다 (목업 엔진도 같은 규칙).
- 대화 보관: 서버 로컬 저장소(JsonStore)에 두고, 새 대화를 시작할 때 7일이 지난 대화를 지운다. 단일 사용자("default").

## 3. 수정

### 백엔드

- **`backend/analysis/m1_request/profile_chat.py`(신규)**: 목업 엔진을 옮긴 대화 규칙.
  - 표: `DEFAULT_FORM`(= `defaults.ts`), `DIAGNOSIS`·`TENDENCY_HELP`·`compute_tendency`·`to_risk_tolerance`(= `diagnosis.ts`), 화면 문구(목적·지수·전략 이름), `holdings_for`(종목 수 ±20% 와 종목당 상한).
  - `CHAT_QUESTIONS`(11문항: 목적 → 처음 투자금 → 월 추가 투자 → 기간 → 성향 진단 3 → 성향 확인 → 투자 대상 지수 → 종목 수 → 종목 고르는 기준).
  - `chat_view(state)` → 프런트 `ProposedProfileChat`. 상태는 질문별 답만 저장하고 말풍선·초안·다음 질문은 매번 답에서 다시 만든다.
    말풍선 id(`hello`, `{질문}:q`, `{질문}:a`, `{질문}:keep`, `{질문}:retry`, `done`)는 응답마다 그대로다 (프런트가 React key 로 쓴다).
  - `answer_chat(state, answer, check=)`: 형식·범위 검사 → 맞지 않으면 다시 묻는 안내(`error`)만 남긴다. 마지막 질문에 답해 `review` 가 되기 전에 `check` 로 초안을 검사하고, 오류가 있으면 그 답을 받지 않는다.
    보기 비교는 JS `===` 처럼(`true` 와 `1` 은 다르고 `1` 과 `1.0` 은 같다), `7.0` 은 `7` 로 저장해 「7.0년」이 되지 않게 한다.
  - `rewind_chat(state, question_id)`: 그 답과 그 답에 기대는 답(성향 진단 → 성향 확인)만 지운다. 뒤의 답은 남는다.
  - `ProfileChatStore`: 로컬 저장소(기본 `data/analysis_store`)의 `profile_chats/<chat_id>.json`(답·다시 묻기 안내·만든 때·마지막으로 답한 때). id 형식(`chat_YYYYMMDD_HHMMSS_xxxxxx`)이 아니면 파일을 읽지 않고 404.
    `start()` 가 먼저 `prune()` — 마지막으로 답한 지 7일이 지난 대화를 지운다 (읽을 수 없는 파일은 건드리지 않음). 쓰기는 `locked("profile_chats")` 안에서.
- **`backend/analysis/api/routers/profile.py`**: 엔드포인트 3개를 파일 끝에 더했다 (새 라우터 파일을 만들지 않아 `app.py` 라우터 목록을 고친 다른 묶음과 충돌하지 않음. `put_profile` 은 그대로).
  - `POST /profile/chat` → 새 대화.
  - `POST /profile/chat/{chat_id}/answers` body `ProposedChatAnswer` → 지금 질문이 아니면(요약 단계 포함) 409 `CONFLICT`(`details.current_question_id`), 없는 대화 404, `question_id` 없는 본문 422.
    값의 형식·범위는 body 검증에서 막지 않는다 — 숫자가 아닌 금액도 422 가 아니라 다시 묻는 말풍선.
  - `POST /profile/chat/{chat_id}/rewind` body `{question_id}` → 없는 질문 id 는 422 `REQUEST_INVALID`, 없는 대화 404.
  - `_draft_errors`: `PUT /profile` 과 같은 순서의 검사(`ProfileIn` → `build` → `hard_errors` → 저장 스키마 `profile`). 대화의 `check` 로 쓴다.

### 화면

- **`Front/src/api/service.ts`**: `HttpService.startProfileChat / answerProfileChat / rewindProfileChat` → 일반 모드에서도 처음 사용자는 대화형으로 간다 (`App.tsx`·홈의 「투자조건 설정 시작」·폼의 「대화로 설정하기」가 메서드 유무로 이미 갈라져 있어 화면은 바꾸지 않았다). 「목업」 표시는 원래 목업 모드에서만.
- 주석: `ProfileChatScreen.tsx`(「지금은 목업뿐」 정리), `mocks/data/profileChat.ts`·`features/profile/defaults.ts`·`diagnosis.ts`(서버에 같은 표가 있으니 함께 바꾼다).

### 문서

- `Front/docs/backend-integration.md` §2-15, `Front/docs/backend-requests-profile-chat.md` §0·§1 「✅ 실제 서버 구현」(정책 6개를 어떻게 정했는지), `Front/docs/mock-mode.md` 제안 메서드 표·15절.

## 4. 알아 둘 것

- 규칙이 두 곳(목업 엔진·서버)에 있다. 목업은 서버 없이 돌아야 해서 공유할 수 없다. 질문 순서·이름·고정 보기·입력 범위·정해진 말풍선, 진단 문항·점수·성향 설명, 기본값이 프런트 파일과 다르면 서버 테스트가 실패한다.
  0원 보기 문장 5개(`ZERO_START_LABEL` 등)도 같은 테스트가 목업 파일과 비교한다.
- 목업과 다른 점: 없는 대화 404, 되감기의 없는 질문 id 422(목업은 무시), 여러 개 고르는 질문에 같은 보기를 두 번 보내면 한 번만 저장(목업은 그대로 저장해 저장 스키마에서 거절될 수 있었다).
- 대화 API 는 저장을 모르므로 저장을 마친 대화도 7일 기준으로 지워진다. 저장된 값은 투자조건 버전에 있다. 프런트가 화면 상태에 들고 있던 대화(폼에 다녀오기)가 지워졌으면 404 → 화면의 「처음부터 다시 시작」.
- `review` 전 검사는 지금 고정 질문으로는 걸리지 않는다 (아래 테스트가 모든 성향 × 종목 기준 × 끝값 조합을 확인). 질문이나 기본값을 바꿀 때의 안전장치다.

## 5. 확인

브랜치는 `feature/real-strategy-recommendation`(B-4, `c92a7a3`)에서 땄다 (`recommend()` 를 쓰기 때문). `CONNECTED` 의 B 자리에 대화 메서드 3개.

- **백엔드:** 새 `test_profile_chat.py` 19개 — 시작(모양·기본값 초안이 저장 검사 통과), 끝까지 답해 요약·저장(버전 1, 다시 대화로 저장하면 버전 2, 말풍선 id 가 응답마다 그대로),
  다시 묻기(없는 보기·건너뛰기·범위 밖·문자열·`true`·소수 기간·빈 선택·중복 선택), 409·404·422, 진단과 다른 성향 → 추천도 그 성향, 「고치기」(뒤의 답 유지·말풍선 id 같음),
  진단 고치기 → 성향 확인도 다시, `review` 전 검사가 마지막 답을 막음, 성향 5개 × 종목 기준 6개 × 끝값 조합이 모두 저장 검사 통과, 7일 보관, 답만 저장, 금액 표시·종목 수 계산, 프런트 표와 같음(진단·기본값·질문).
- **목업과 같은 응답:** 같은 답 순서(재질문·되감기·건너뛰기 포함 23단계)를 서버 API 와 `MockService` 에 넣어 24개 응답 전체(말풍선·보기·초안·답한 항목)가 같음을 한 번 확인했다 (임시 스크립트, 커밋하지 않음).
- **프런트:** `npm run typecheck` 통과. `mocks.test.tsx` 연결 메서드·요청 주소(시작/답/되감기 본문), `profileChat.mock.test.tsx` 일반 모드(실제 서버 대화 API 가 있으면 처음 사용자가 대화형으로 가고 「목업」 표시 없이 다시 묻기·고치기가 서버 호출로 이어짐).
- **0원 경로 (B-3 병합 뒤 추가):** B-3 브랜치(`feature/real-zero-initial-amount`)를 합치고 서버·목업 대화 엔진에 같은 규칙을 넣었다 — 금액 보기 「0원 · 매월 적립으로 시작」,
  0원이면 월 적립 질문의 「추가 투자 없음」 숨김·0원 거절(`ZERO_NEEDS_MONTHLY`), 금액을 0원으로 고치면 「추가 투자 없음」이던 월 적립만 지워 다시 묻기.
  서버 `test_zero_start_path`·`test_rewind_amount_to_zero_reasks_monthly_none`, 저장 검사 끝값 조합에 0원 + 최소 적립, 목업 `profileChat.mock.test.tsx` 같은 두 흐름.
