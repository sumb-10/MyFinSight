# 목업 기능 실제 연결 B-4: 투자성향 기반 전략 추천 (2026-11-10)

이슈 #14 묶음 B(투자조건 규칙)의 4번 「투자성향에 맞는 전략 추천」을 실제 서버에 연결했다.
각 항목은 "무엇을 / 왜 / 어디를(파일) / 어떻게 확인했나"를 적는다.

## 1. 문제

- 내 투자조건 화면의 「투자 전략」 단계에서 목업은 성향(안정형~공격투자형)에 맞는 추천 전략·이유·다른 전략과의 차이를 보여 주고 버튼 하나로 적용했다.
  실제 서버에는 추천 규칙도 API 도 없어, 실제 모드에서는 이 카드가 숨겨지고 기업 고르는 기준·나누는 방식·뉴스 반영을 사용자가 직접만 골랐다.
- 목업 추천 표(`Front/src/mocks/data/strategy.ts`, 11/5 김찬우 작성, 11/7 회의 피드백으로 용어 괄호만 수정)는 「예시이며 실제 규칙이 아님」으로 표시돼 있었다.

## 2. 결정

- **일단 고정 규칙** (사용자 결정). 목업 표의 성향별 조합·이유 3개·다른 전략 2개와 차이 문장을 그대로 서버 규칙으로 쓴다.
  시장 상황·과거 성과를 보고 고르지 않으며, 응답의 안내 문장(`note_ko`)이 그렇게 말한다.

  | 성향 | 기업 고르는 기준 | 나누는 방식 | 뉴스 반영 |
  |---|---|---|---|
  | 안정형 | 고배당 | 최소분산 | 끔 |
  | 안정추구형 | 저변동성 | 역변동성 | 끔 |
  | 위험중립형 | 퀄리티 | 동일비중 | 켬 |
  | 적극투자형 | 모멘텀 | 시가총액비중 | 켬 |
  | 공격투자형 | 모멘텀 | 동일비중 | 켬 |

- 입력은 서버의 3단계 `risk_tolerance` 가 아니라 프런트 진단의 **5단계 성향**(`diagnosis.final_tendency`). 추천이 5단계마다 다르기 때문.
- 목업과 실제가 같은 추천을 보이도록 **표는 두 곳에 같게** 두고, 서버 테스트가 같은지 확인한다 (목업은 서버 없이 돌아야 해서 표를 공유할 수 없다).

## 3. 수정

### 백엔드

- **`backend/analysis/m1_request/strategy_recommendation.py`(신규)**: `Tendency`(5단계), 고정 규칙 표, `recommend(tendency)` → 프런트 `ProposedStrategyRecommendation` 모양.
  호출한 쪽이 결과를 고쳐도 표가 바뀌지 않게 새 dict 로 돌려준다.
- **`backend/analysis/api/routers/meta.py`**: `GET /strategy/recommendation?tendency=` (성향이 없거나 5개 밖이면 422 `VALIDATION_ERROR`). DB·LLM 을 쓰지 않는다.
  새 라우터 파일 대신 `meta.py` 에 둔 것은 `app.py` 라우터 목록을 고친 묶음 A 브랜치와 충돌하지 않게 하려는 것.

### 화면

- **`Front/src/api/service.ts`**: `HttpService.recommendStrategy`(한글 성향 인코딩) → 실제 모드에서도 추천 카드와 선택 카드의 「추천」 표시가 열린다.
  「목업」 표시(`MockTag`)는 원래 목업 모드에서만 보여 따로 고치지 않았다.
- **`Front/src/mocks/data/strategy.ts`**: 서버 표와 같다는 주석, 목업 안내 문장을 「실제 서버와 같은 고정 규칙」으로. 「목업에서만」 주석 정리 (`StrategyRecommend.tsx`·`StrategyFields.tsx`·`MockService.ts`).

### 문서

- `Front/docs/backend-integration.md` §2-5 「✅ 실제 서버 구현」, `Front/docs/mock-mode.md` 제안 메서드 표.

## 4. 알아 둘 것

- 규칙을 바꾸려면 서버 표와 목업 표를 함께 고친다. 하나만 고치면 `test_same_as_front_mock_table` 이 실패한다.
- 대화형 초기 설정(1번)의 「종목을 고르는 기준」 질문은 지금 목업 대화 엔진(`mocks/data/profileChat.ts`)이 목업 표를 직접 읽는다. 1번을 서버로 옮길 때는 `recommend()` 를 쓰면 된다.
- 추천은 저장된 투자조건을 바꾸지 않는다. 사용자가 「추천 전략 적용」을 누르고 저장해야 반영된다 (기존 `PUT /profile`).

## 5. 확인

브랜치는 `feature/request-progress`(PR 13, `b863822`)에서 따고 공통 테스트 구조 커밋(`cceec8d`)을 병합했다. `CONNECTED` 의 B 자리에 `recommendStrategy`.

- **백엔드:** 새 `test_strategy_recommendation.py` 9개 — 성향 5개 모두 이유 3개·다른 전략 2개, 모든 조합이 서버 저장 검증(`StrategyPreference`)을 통과하고 서로 다름,
  규칙 값, 결과를 고쳐도 표가 그대로, 목업 표와 같음, API(200·성향 없음/영문/없는 성향 422, DB 를 읽지 않음).
- **프런트:** `npm run typecheck` 통과. `mocks.test.tsx` 연결 메서드·요청 주소(한글 성향 인코딩),
  `profile.mock.test.tsx` 실제 서버 응답(일반 모드에서 추천 카드가 보이고 「목업」 표시 없이 서버 안내 문장, 선택 카드 「추천」 2개).
