# 백엔드 요청 — 대화형 초기 투자조건 (제안 계약 `proposed-0.1`)

> 대상: 분석 서비스(`backend/analysis`) 담당. 프런트는 **목업으로 화면과 흐름을 먼저 만들었고**(`?mock=1`, 개발 서버 전용), 실제 서버에는 아직 아무것도 바뀌지 않았다.
> 이 문서는 같은 화면을 일반 모드에서 쓰려면 서버가 무엇을 주어야 하는지 정리한다. 형식은 [backend-integration.md](./backend-integration.md) 2절과 같다.
> 작성: 재민 (회의록 6.4 담당 — 리포트 외 화면 편의성 개선, 대화형 초기 프로필). 2026-11-09.

## 0. 요약

| # | 요청 | 우선순위 | 지금 일반 모드 |
|---|---|---|---|
| 1 | 대화형 초기 투자조건 API 3개 (시작 / 답 / 되감기) | 높음 | ✅ 실제 서버 구현 (2026-11-10) — 처음 사용자는 일반 모드에서도 대화형으로 간다 (1절 끝) |
| 2 | 대화 중 **자유 문장 답** 해석 (LLM) | 중간 — 1 이후 | 목업은 보기·숫자만 받는다 |
| 3 | 이미 있는 요청과 겹치는 것: 0원 시작(2-4), 여러 질문 한 번에(2-7), 즉시 취소(2-9) | 기존 명세 참고 | 각 절 그대로 |

저장은 **기존 `PUT /profile` 을 그대로 쓴다.** 대화 API 는 저장하지 않고 초안(draft)만 만든다. 그래서 1번이 없어도 서비스는 지금처럼 동작한다.

---

## 1. 대화형 초기 투자조건 API

- **화면:** `#/profile/chat`. 투자조건이 없는 사용자가 앱을 열면 여기로 온다(서비스에 대화 메서드가 있을 때만, 없으면 `#/profile/setup` 4단계 폼).
  - 한 질문씩 말풍선으로 묻는다. 답은 보기 버튼이나 금액·숫자 직접 입력으로 받는다.
  - 사용자 답 말풍선의 「고치기」를 누르면 그 질문만 다시 묻는다. 뒤의 답은 지우지 않고, 다시 답하면 남은 질문(없으면 요약)으로 돌아간다.
    단, 고친 답에 기대는 질문(성향 진단 → 성향 확인)은 함께 다시 묻는다. `rewind` 를 구현할 때 이 의존 관계를 서버가 정한다.
  - 다 답하면 요약(답한 값 / 기본값으로 둔 값)을 보여 주고 「이대로 저장」·「폼에서 세부 수정」·「처음부터 다시」를 고르게 한다.
- **부족한 데이터:** 질문 순서·보기·답 반영·다시 묻기를 정해 주는 서버 API가 없다.
- **API (제안):**
  - `POST /profile/chat` → `ProposedProfileChat` (새 대화)
  - `POST /profile/chat/{chat_id}/answers` body `ProposedChatAnswer` → `ProposedProfileChat`
  - `POST /profile/chat/{chat_id}/rewind` body `{ "question_id": "amount" }` → `ProposedProfileChat`
- **타입** (`Front/src/api/proposed.ts`):
  ```ts
  ProposedProfileChat = {
    chat_id: string
    state: "asking" | "review"                  // review = 필수 질문을 다 답함
    messages: { id; role: "bot" | "user"; text_ko; question_id?; editable? }[]   // 처음부터 지금까지 전체 (화면은 그대로 그린다)
    question: { id; field_label_ko; kind: "choice" | "multi" | "money" | "number";
                options: { value; label_ko; help_ko?; recommended? }[];
                input: { min; max; step; unit_ko } | null;      // money·number 의 직접 입력 범위
                allow_skip: boolean } | null                    // review 면 null
    progress: { done: number; total: number }
    draft: ProfileFields                         // PUT /profile 본문과 같은 모양, 기본값이 채워진 완전한 값
    asked_fields: string[]                       // 답으로 정해진 항목 키 (요약표 「답한 값」 표시용)
  }
  ProposedChatAnswer = { question_id; option_value?; number?; skip? }   // multi 는 option_value 가 배열
  ```
- **예시 (금액 질문 차례):**
  `{"chat_id":"chat_01","state":"asking","messages":[{"id":"hello","role":"bot","text_ko":"안녕하세요! …"},{"id":"purpose:q","role":"bot","text_ko":"이번 투자의 목적은 무엇인가요?","question_id":"purpose"},{"id":"purpose:a","role":"user","text_ko":"자산 증식","question_id":"purpose","editable":true},{"id":"amount:q","role":"bot","text_ko":"처음에 얼마로 시작할까요? 원화 기준으로 알려 주세요.","question_id":"amount"}],"question":{"id":"amount","field_label_ko":"처음 투자할 금액","kind":"money","options":[{"value":5000000,"label_ko":"500만원"},{"value":10000000,"label_ko":"1,000만원"}],"input":{"min":100000,"max":10000000000,"step":100000,"unit_ko":"원"},"allow_skip":false},"progress":{"done":1,"total":11},"draft":{…},"asked_fields":["horizon.purpose"]}`
- **목업이 묻는 순서 (필수 11문항, 나머지는 기본값):**
  1. 목적 `horizon.purpose`
  2. 처음 투자금 `capital.initial_amount` (원화)
  3. 월 추가 투자 `capital.monthly_contribution`
  4. 투자 기간 `horizon.target_years` (1~10)
  5. 성향 진단 3문항 (`diagnosis.answers`, `risk.max_drawdown_tolerance`, `risk.loss_reaction`)
  6. 성향 확인. 진단 결과를 추천으로 보여 주고, 다르게 고르면 `risk_type_overridden=true`
  7. 투자 대상 지수 `constraints.universe` (여러 개)
  8. 종목 수. `num_holdings` ±20% 범위와 `max_weight_per_stock` 을 함께 정한다
  9. 종목 고르는 기준. 성향별 추천 묶음(`strategy_preference` 셋) 또는 template 하나
- **정책 (서버와 정할 것):**
  1. **검사는 `PUT /profile` 과 똑같이.** 지금 `routers/profile.py` 는 `ProfileIn` + `build(...)` + `hard_errors()` 로 검사한다. `review` 로 넘어가기 전 draft 를 같은 함수로 검사해 주면, 대화로 만든 값이 저장 때 거절되는 일이 없다. (프런트는 `features/profile/validate.ts` 의 같은 규칙으로 한 번 더 막는다.)
  2. **기본값 출처.** 묻지 않는 항목(비교지수·백테스트 기간·리밸런싱·상한 등)의 기본값을 서버가 정할지(`/meta/options` 의 기본값), 프런트 `features/profile/defaults.ts` 를 따를지.
  3. **맞지 않는 답.** 범위 밖 값·없는 보기·필수 건너뛰기는 400 이 아니라 **200 + 봇의 다시 묻는 말풍선**으로 돌려준다(목업과 같음). 지금 차례가 아닌 `question_id` 만 409.
  4. **질문 수와 순서.** 목업은 11문항 고정. 나이·경험 같은 참고 정보를 더 물을지, 성향 진단 문항을 서버가 관리할지(지금은 프런트 `features/profile/diagnosis.ts`).
  5. **대화 보관.** 저장하지 않은 대화를 얼마나 둘지(목업은 탭을 닫으면 사라짐). 같은 사용자의 여러 대화 처리.
  6. **이미 투자조건이 있는 사용자.** 목업은 대화로 저장하면 새 버전(note "대화로 다시 설정"). 서버도 허용할지.
- **목업:** `MockService.startProfileChat/answerProfileChat/rewindProfileChat`, 규칙 `mocks/data/profileChat.ts`(질문 표 `CHAT_QUESTIONS`, `chatView`·`answerChat`·`rewindChat`), 상태 `MockState.profileChats`.
- **프런트 수정 (연동 시):** `api/service.ts` 의 `HttpService` 에 세 메서드를 추가하면 끝. 화면 `features/profile/chat/*` 은 그대로. 메서드가 생기는 순간 처음 사용자 진입(`app/App.tsx`)이 대화형으로 바뀐다.
- **주의:** 응답의 `messages` 는 **전체 대화**다(덧붙이기 아님). 프런트는 받은 목록을 그대로 그리고 메시지 `id` 를 React key 로 쓰므로, 같은 메시지는 같은 `id` 를 유지해야 한다.
- **✅ 실제 서버 구현 (2026-11-10):** 위 API 3개 그대로 (`backend/analysis/api/routers/profile.py`, 규칙 `backend/analysis/m1_request/profile_chat.py`). 정책은 이렇게 정했다.
  1. **검사:** `review` 로 넘어가기 직전(마지막 남은 질문에 답할 때) 초안을 `PUT /profile` 과 같은 순서(`ProfileIn` → `build` → `hard_errors` → 저장 스키마)로 검사한다.
     오류가 있으면 그 답을 받지 않고 오류 문장을 봇 말풍선(`{질문}:retry`)으로 보여 준다. 지금의 고정 질문으로는 이 경우가 생기지 않는다(서버 테스트가 성향·종목 기준·끝값 조합을 모두 확인).
  2. **기본값:** 서버가 프런트 `defaults.ts` 와 같은 값을 갖는다 (`DEFAULT_FORM`). 성향 진단 문항도 서버가 `diagnosis.ts` 와 같은 표를 갖는다. 서버 테스트가 두 파일과 같은지 본다.
  3. **맞지 않는 답:** 목업과 같다 — 범위 밖·없는 보기·필수 건너뛰기·숫자가 아닌 값은 200 + 다시 묻는 말풍선, 지금 차례가 아닌 `question_id`(요약 단계 포함)는 409 `CONFLICT`(`details.current_question_id`).
     목업에 없던 것: 없는 대화 404, 되감기의 없는 질문 id 422(목업은 무시), 여러 개 고르는 질문에 같은 보기를 두 번 보내면 한 번만 저장(저장 스키마가 중복을 받지 않음).
  4. **질문 수와 순서:** 목업 11문항 그대로. 나이·경험 같은 참고 정보는 묻지 않는다(기본값). 「종목을 고르는 기준」의 추천은 서버 규칙 `recommend()`(`GET /strategy/recommendation` 과 같은 표). 처음 투자금 최소는 10만원 그대로(0원 시작은 별도 작업).
  5. **대화 보관:** 서버 로컬 저장소(기본 `data/analysis_store`)의 `profile_chats/<chat_id>.json` 에 답만 둔다(말풍선·초안은 매번 답에서 다시 만든다). 새 대화를 시작할 때 마지막으로 답한 지 7일이 지난 대화를 지운다.
     대화 API 는 저장을 모르므로 저장한 대화도 같은 기준으로 지워진다(저장된 값은 투자조건 버전에 있다). 같은 사용자("default")의 여러 대화를 함께 둘 수 있다.
  6. **이미 투자조건이 있는 사용자:** 허용. 대화는 기본값에서 시작하고, 저장하면 새 버전이 된다.

  목업과 서버가 같은 응답을 내는지는 같은 답 순서(재질문·되감기 포함 23단계)를 양쪽에 넣어 한 번 비교했고, 서버 테스트 `test_profile_chat.py` 가 질문 순서·이름·고정 보기·입력 범위·정해진 말풍선·진단 표·기본값이 프런트 파일과 같은지 계속 본다.

## 2. 자유 문장 답 해석 (1 이후)

- **부족한 데이터:** 목업은 보기·숫자만 받는다. "한 3천 정도요", "미국이랑 한국 둘 다" 같은 문장은 해석하지 않는다.
- **API (제안):** `ProposedChatAnswer` 에 `free_text?: string` 추가. 서버(LLM)가 지금 질문의 값으로 바꾸고, 확신이 낮으면 봇이 확인 질문을 한다("3,000만원으로 할까요?").
- **정책:** 숫자는 코드가 다시 검사(설계 원칙: 숫자는 코드가 계산). 해석 실패·모호 시 같은 질문을 다시 묻는다. 한 문장에 여러 항목이 있으면(“3천으로 5년”) 다음 질문을 미리 채울지.
- **프런트 수정:** `ChatInput.tsx` 에 자유 입력칸 추가 (질문에 `allow_free_text` 플래그 제안).

## 3. 이미 있는 요청과 겹치는 것

화면 개선 작업(질문·확인·진행 화면)에서 서버가 필요한 항목은 아래 기존 명세 그대로다. 새로 정할 점만 적는다.

- **0원 시작 (backend-integration.md 2-4):** 대화형 금액 질문의 최소값은 지금 10만원. 0원 시작이 허용되면 금액 질문에 "0원 + 매월 적립" 경로를 넣는다.
- **여러 질문 한 번에 (2-7):** 분석 요청의 보충 질문. 대화형 프로필과는 별개지만, 질문 표현(`field_label_ko`·보기·필수 여부)을 같은 모양으로 맞추면 화면 부품을 함께 쓸 수 있다.
- **즉시 취소 (2-9):** 변경 없음.
