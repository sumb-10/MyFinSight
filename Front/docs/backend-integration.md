# 백엔드 연동 명세 — 목업으로 먼저 만든 기능 (제안 계약 `proposed-0.1`)

이 문서는 프런트엔드가 목업 모드(`?mock=1`, 개발 환경 전용)에서 먼저 만든 기능을 실제 서버와 연결할 때 필요한 데이터와 API를 정리한다.
**여기 적힌 API·필드는 모두 「제안 계약」이며 서버와 합의되지 않았다.** 이름·경로·위치는 바뀔 수 있다.
지금 실제 서버(`HttpService`)는 이 필드·메서드를 주지 않으며, 그 경우 화면은 기존 그대로 동작한다 (일반 모드 회귀 테스트로 확인).

- 목업 구조·실행 방법·시나리오: [`mock-mode.md`](./mock-mode.md)
- 타입 정의(제안 계약 원본): `src/api/proposed.ts`
- 목업 구현: `src/mocks/services/MockService.ts`, 자료 `src/mocks/data/*`, 시나리오 `src/mocks/scenarios/index.ts`

---

## 1. 연동 방식 (목업 → 실제 데이터로 바꾸는 법)

화면은 **기능이 있을 때만 연다**는 규칙으로 만들었다. 서버가 아래를 제공하면 화면 코드를 거의 고치지 않고 켜진다.

| 종류 | 화면이 보는 곳 | 실제 연동 시 할 일 |
|---|---|---|
| 새 메서드 (`getReportName`, `searchStocks` …) | `AnalysisService` 의 선택 메서드 (`src/api/service.ts` 의 `ProposedApi`) | `HttpService` 에 같은 이름의 메서드를 추가해 새 API를 부른다. 메서드가 생기는 순간 해당 UI가 열린다 |
| 기존 응답에 붙는 확장 필드 (`proposed`, `proposed_name`, `proposed_cancel`, `proposed_rules`) | 접근 함수 한 곳: `proposedOf`, `proposedNameOf`, `proposedCancelOf`, `proposedRulesOf` (`src/api/proposed.ts`) | 서버가 정식 필드 이름으로 주면 **접근 함수만** 새 위치를 읽게 바꾼다. 리포트 확장은 `src/features/report/proposedView.tsx` 의 어댑터가 한 번 더 감싼다 |
| 목업 전용 표시 | `MockTag`(「목업」 표시)는 서비스 `mode === "mock"` 일 때만 보인다 | 실제 서버 값에는 자동으로 붙지 않는다. 손댈 필요 없음 |

교체 순서 제안: ① 서버가 엔드포인트·필드 제공 → ② `HttpService` 메서드 추가(또는 접근 함수 위치 변경) → ③ 타입을 `proposed.ts` 에서 `types.ts` 로 옮기고 이름 확정 → ④ 목업 테스트(`src/mocks/*.test.tsx`)의 기대값을 서버 응답 형식으로 맞춘 계약 테스트 추가.
**주의:** 실제 서버 응답에 목업 자료가 섞이지 않도록 `MockService` 를 `HttpService` 에 합치지 말 것 (목업은 개발 환경 + `?mock=1` 에서만 동적 import 된다).

공통 규칙 (기존 `types.ts` 와 같음): 비율·수익률은 분수(0.12 = 12%), 금액은 필드 이름에 통화(`_usd`/`_krw`), 날짜 `YYYY-MM-DD`, 시각은 ISO 8601. 종목 표기는 「회사명 (티커)」.

---

## 2. 기능별 명세

각 항목: 부족한 데이터 · API/필드(타입) · 예시 · 의미와 기준 시점 · 필요한 계산/정책 · 목업 위치 · 연동 시 수정할 프런트 파일 · 주의점.

### 2-1. 리포트 이름 (자동 생성·수정·되돌리기) — 3단계

- **부족한 데이터:** 리포트 고유 이름이 없다. 목록은 `strategy_name`(리포트끼리 거의 같음), 상세는 `header.title_ko` 를 써 화면마다 달랐다. 이름 저장 기능 없음.
- **API (제안):**
  - `GET /reports/{report_id}/name` → `ProposedReportName`
  - `PATCH /reports/{report_id}/name` body `{ "custom_ko": string | null }` (null = 자동 이름으로 되돌리기) → `ProposedReportName`
  - `GET /reports` 각 행에 `name: ProposedReportName` (프런트 지금 위치: `proposed_name`)
- **타입:** `{ report_id: string; auto_ko: string; custom_ko: string | null; display_ko: string; updated_at: string | null }`
- **예시:** `{"report_id":"mock_rep_normal","auto_ko":"미국 반도체 장비·메모리 분산 투자","custom_ko":null,"display_ko":"미국 반도체 장비·메모리 분산 투자","updated_at":null}`
- **의미·기준:** `auto_ko` 는 리포트 생성 시 투자 아이디어·테마로 한 번 만든 이름(이후 고정), `display_ko = custom_ko ?? auto_ko`. 리포트 ID·실행 ID 어느 쪽으로 불러도 같은 이름.
- **정책:** 빈 문자열·공백·자동 이름과 같은 값은 `custom_ko = null` 로 저장. 최대 40자(화면 제한, 서버 검증 필요). 사용자별 권한 확인.
- **목업:** `MockService.getReportName/renameReport/nameOf`, 자동 이름 `scenarios/index.ts` 의 `auto_name_ko`(LLM 아님).
- **프런트 수정:** `api/service.ts`(HttpService 메서드), `api/proposed.ts`(`proposedNameOf` 위치). 화면 `features/report/ReportName.tsx`·`ReportDetail.tsx`·`ReportList.tsx` 는 그대로.
- **주의:** 이름이 바뀌면 홈·사이드바·목록·상세·모의투자(연동 이름)가 함께 바뀌어야 한다 — 프런트는 `myfinsight:report-renamed` 창 이벤트로 다시 읽는다. 자동 이름 생성을 LLM으로 할 경우 실패 시 대체 규칙(예: 테마 · 전략) 필요.

### 2-2. 모의투자 이름 연동 — 3단계

- **부족한 데이터:** 모의투자 `name_ko` 는 전략 이름이고 리포트 이름과 관계가 없다.
- **API (제안):** `GET /paper/{paper_id}/name` → `ProposedPaperName`, `PATCH /paper/{paper_id}/name` body `{ "mode": "linked" } | { "mode": "custom", "name_ko": string }`. 모의투자 생성(`POST /paper`)에 같은 `name` 입력 허용.
- **타입:** `{ name_ko: string; mode: "linked" | "custom"; report_name_ko: string }`
- **예시:** `{"name_ko":"시가총액 비중 비교용","mode":"custom","report_name_ko":"미국 반도체 장비·메모리 분산 투자"}`
- **정책:** `linked` 는 리포트 `display_ko` 를 따라가고(리포트 이름 변경 시 즉시 반영), `custom` 은 고정. 새 모의투자 기본값 `linked`. 목록·상세의 `name_ko` 도 같은 규칙으로 계산해 줘야 한다.
- **목업:** `MockService.getPaperName/setPaperName/paperName`. **프런트 수정:** `api/service.ts`; 화면 `features/paper/PaperName.tsx`·`StartPaperDialog.tsx`·`PaperScreen.tsx` 는 그대로.
- **주의:** 지금 프런트는 생성 후 `setPaperName` 을 한 번 더 부른다. 서버가 생성 입력으로 받으면 `StartPaperDialog.create` 를 한 번 호출로 바꾼다.

### 2-3. 종목 검색·회사명 조회 — 4단계

- **부족한 데이터:** 회사명으로 찾는 API가 없고, 화면 대부분이 티커만 안다.
- **API (제안):** `GET /stocks/search?q=마이크론&limit=8` → `ProposedStock[]`, `GET /stocks?tickers=MU,NVDA` → `ProposedStock[]` (없는 티커는 빠짐)
- **타입:** `{ ticker: string; name_ko: string; name_en: string; market: "US" | "KR"; sector_ko: string }`
- **예시:** `[{"ticker":"MU","name_ko":"마이크론 테크놀로지","name_en":"Micron Technology","market":"US","sector_ko":"정보기술"}]`
- **정책:** 티커 앞부분 일치 → 회사명(한/영) 앞부분 → 부분 일치 순. 공백 무시. ETF 는 종목 후보에서 제외. 백엔드 종목 자료(약 719개)가 원본이며 **프런트에 복사하지 않는다** (목업은 28개만 직접 정함).
- **종목 표기:** 「회사명 (티커)」(`stockLabel`). 조건 행 `value_ko`·질문 보기 이름도 같은 규칙으로 만들거나, 구조 필드(`tickers: {ticker, name_ko}[]`)를 함께 주기를 제안.
- **목업:** `MockService.searchStocks/getStocks`, 자료 `mocks/data/stocks.ts`. **프런트 수정:** `api/service.ts`. 화면 `features/profile/stocks.tsx`(검색 칸·`useStockNames`).
- **주의:** 한국 종목코드(005930 / 005930.KS) 정규화 규칙 합의 필요. 지금 일반 모드는 티커 직접 입력(TagInput) 그대로다.

### 2-4. 초기 투자금 0원 시작 — 4단계

- **부족한 데이터/정책:** 서버 검증이 `initial_amount > 0`. 0원 + 매월 적립 흐름이 없다.
- **API (제안):** `GET /meta/options` 응답에 `proposed_rules: { allow_zero_initial_amount: boolean }`. 프로필·요청 검증을 `initial_amount ≥ 0`, 0이면 `monthly_contribution > 0` 필수로 변경.
- **예시:** `{"proposed_rules":{"allow_zero_initial_amount":true}}`
- **필요한 계산:** 0원 백테스트(첫 적립일부터 매수), 수익률 기준(넣은 원금 대비 / 시간가중) 정의, 모의투자 0원 시작 처리, 리포트의 「투자 기준금액」 표시 규칙.
- **목업:** `MockService.options`, 프로필 변형 `mocks/data/profile.ts` 의 `ZERO_CAPITAL_VERSION`. **프런트 수정:** `api/proposed.ts`(`proposedRulesOf` 위치). 화면 `ProfileScreen.tsx`(검사·예상 투자 일정)는 규칙 값만 본다.
- **주의:** 홈 「상세 조건」 창의 기존 검사(투자금 > 0)는 이번 범위에서 고치지 않았다 — 규칙이 확정되면 같은 플래그를 보게 바꿔야 한다. 예상 투자 일정은 원금만 계산하며 수익을 예측하지 않는다.

### 2-5. 투자성향 기반 전략 추천 — 4단계

- **부족한 데이터:** 추천 규칙·API가 없다 (실제 규칙 미정).
- **API (제안):** `GET /strategy/recommendation?tendency=위험중립형` → `ProposedStrategyRecommendation`
- **타입:** `{ tendency; recommended: { template; baseline_weighting; use_news_tilt }; reasons_ko: string[]; alternatives: (같은 셋 + diff_ko)[]; note_ko }`
- **예시:** `{"tendency":"위험중립형","recommended":{"template":"quality","baseline_weighting":"equal_weight","use_news_tilt":true},"reasons_ko":["수익과 위험을 함께 보는 성향이라 …"],"alternatives":[{"template":"low_volatility","baseline_weighting":"inverse_volatility","use_news_tilt":false,"diff_ko":"변동이 작은 기업 위주라 …"}],"note_ko":"…"}`
- **정책:** 추천 규칙(성향 → 전략) 확정 필요. 근거 문구는 규칙에서 생성. **목업 표는 예시이며 규칙이 아니다** (`mocks/data/strategy.ts`).
- **프런트 수정:** `api/service.ts`. 화면 `features/profile/StrategyRecommend.tsx`, `StrategyFields.tsx`(선택 prop `recommended`).

### 2-6. 투자조건 변경 이력 비교 — 4단계

- **부족한 데이터:** `GET /profile` 은 과거 버전의 번호·시각만 주고 값은 안 준다.
- **API (제안):** `GET /profile/versions/{version}` → `ProfileVersion`(기존 타입 그대로, 그 버전 값 전체)
- **정책:** 비교는 프런트가 같은 표시 함수로 계산(`features/profile/compare.tsx` 의 `profileRows/diffProfiles`). 서버가 바뀐 필드 목록을 주면 더 정확(제안: `changed_fields: string[]`).
- **목업:** `MockService.getProfileVersion`, 버전 1~4(+0원 버전) `mocks/data/profile.ts`. **프런트 수정:** `api/service.ts`. 화면 `features/profile/history.tsx`·`compare.tsx`.

### 2-7. 여러 질문 한 번에 답하기 — 4단계

- **부족한 데이터:** 서버는 질문을 하나씩만 준다.
- **API (제안):** `GET /requests/{id}/questions` → `ProposedQuestionBatch`, `POST /requests/{id}/answers` body `ProposedBatchAnswer[]` → `DialogState`(기존)
- **타입:** 질문 `{ seq; field; field_label_ko; question_ko; why_ko?; required; options: {value, label_ko}[]; allow_free_text }`, 답 `{ seq; option_value?; free_text?; skip? }`
- **예시:** `{"seq":1,"field":"constraints.max_weight_per_stock","field_label_ko":"종목당 최대 비중","question_ko":"한 종목에 최대 몇 %까지 담을까요?","required":true,"options":[{"value":0.25,"label_ko":"25%"}],"allow_free_text":true}`
- **정책:** 필수 질문 미답이면 422(어느 질문인지 포함). 보기 값은 조건에 반영, `skip` 은 기본 투자조건 유지, 자유 입력은 서버(LLM)가 해석. 반영 후 조건 행(`conditions`)이 바뀐 값·`source:"answer"` 를 정확히 줘야 화면의 「반영 결과」가 맞는다.
- **목업:** `MockService.getQuestionBatch/answerBatch/advance`, 조건 반영 `mocks/data/dialog.ts` 의 `applyField`·`conditionRows`. **프런트 수정:** `api/service.ts`. 화면 `features/analysis/BatchQuestions.tsx`·`ClarifyScreen.tsx`.
- **주의:** 「이미 답한 조건을 다시 묻는 문제」는 서버 문제로 남아 있다 (한 번에 묻더라도 같은 필드를 다시 물으면 안 됨).

### 2-8. 「말로 보태기」 처리 결과 — 4단계

- **부족한 데이터:** 보낸 문장이 반영됐는지, 무엇이 바뀌었는지 응답에 없다 (화면은 조건 행 전후 비교로만 추정).
- **API (제안):** `GET /requests/{id}/messages` → `ProposedMessageResult[]` (또는 `POST /requests/{id}/message` 응답에 마지막 결과 포함)
- **타입:** `{ text; at; outcome: "applied" | "not_applied" | "needs_confirmation"; changes: {field, label_ko, before_ko, after_ko}[]; note_ko }`
- **예시:** `{"text":"테슬라도 꼭 넣어 주세요","outcome":"applied","changes":[{"field":"constraints.must_include_tickers","label_ko":"꼭 넣을 종목","before_ko":"엔비디아 (NVDA), 마이크론 테크놀로지 (MU)","after_ko":"엔비디아 (NVDA), 마이크론 테크놀로지 (MU), 테슬라 (TSLA)"}],"note_ko":"말씀하신 종목을 꼭 넣을 종목에 더했습니다."}`
- **정책:** 반영되지 않으면 기존 조건 유지와 이유, 확인 필요면 무엇을 확인해야 하는지. **실제 자연어 해석·반영은 서버 문제**(목업은 회사명·티커 + 넣다/빼다만 알아듣는다).
- **목업:** `MockService.sendMessage/getMessageResults`, 해석 `dialog.ts` 의 `interpretMessage`. **프런트 수정:** `api/service.ts`. 화면 `features/analysis/MessageOutcome.tsx`·`ClarifyScreen.tsx`·`ConfirmScreen.tsx`.

### 2-9. 분석 취소 결과 (즉시 취소) — 5단계

- **부족한 데이터:** 취소는 「요청」만 되고 진행 중인 단계가 끝나야 멈춘다. 언제·어디서 멈췄는지 응답에 없다.
- **API (제안):** `GET /runs/{id}` 에 `cancel: ProposedRunCancel` (프런트 지금 위치 `proposed_cancel`). 서버가 진행 중 작업을 바로 멈출 수 있으면 `immediate: true`.
- **타입:** `{ requested_at; completed_at: string | null; stopped_step: string | null; stopped_step_label_ko: string | null; done_steps: number; immediate: boolean }`
- **예시:** `{"requested_at":"2026-11-05T09:00:00","completed_at":null,"stopped_step":"06_explain","stopped_step_label_ko":"선정 이유","done_steps":5,"immediate":true}`
- **정책:** 상태 전이 `running → cancelling → cancelled`. 끝난 실행 취소는 409. 완료된 단계 결과로 리포트를 만들지 않음.
- **목업:** `mocks/data/runs.ts` 의 `liveStatus/cancelInfo`, `MockService.cancelRun/runOf`. **프런트 수정:** `api/proposed.ts`(`proposedCancelOf` 위치). 화면 `features/run/RunScreen.tsx`(`CancelSummary`, 즉시 취소 문구).
- **주의:** **실제 서버의 즉시 취소는 구현하지 않았다** (백엔드 작업). `immediate` 가 없으면 화면은 기존 「시간이 걸릴 수 있습니다」 문구를 쓴다.

### 2-10. 단계별 경고 전체 — 5단계

- **부족한 데이터:** 단계 요약(`summary`)에는 「확인 필요 N건: a; b」로 2건까지만 온다.
- **API (제안):** `GET /runs/{id}/warnings` → `ProposedRunWarning[]`
- **타입:** `{ step; step_label_ko; message_ko; count }` (같은 단계·같은 문구는 count 로 묶음)
- **예시:** `[{"step":"03_candidates","step_label_ko":"후보 수집","message_ko":"최소 거래대금 기준에 못 미친 종목 4개를 후보에서 뺐습니다.","count":1}]`
- **정책:** 끝난 단계의 경고만. 단계 요약의 N과 합이 맞아야 한다. 경고 ID가 있으면 새 경고 알림(스크린리더)이 더 정확.
- **목업:** `mocks/data/runs.ts` 의 `RUN_WARNINGS`(9건, 중복 포함), `MockService.getRunWarnings`. **프런트 수정:** `api/service.ts`. 화면 `RunScreen.tsx`(`NotesCard full`), `features/run/steps.ts`(`notesFromWarnings`).

### 2-11. 모의투자 원화 기준 성과·환율 적용 상태 — 5단계

- **부족한 데이터:** 원화 손익·수익률이 없다 (「납입 시점마다 환율이 달라 원화 손익은 제공하지 않습니다」). 날짜별 환율이 대체값인지 알 수 없다.
- **API (제안):** `GET /paper/{id}/krw` → `ProposedPaperKrw` (또는 `GET /paper/{id}` 에 포함)
- **타입 (요약):** `fx: {date, rate|null, status: "ok"|"carried"|"missing", carried_from?}[]`, `value_krw: (number|null)[]`, `contributions_krw_total: number|null`, `last: {date, value_krw, fx}`, `gain_krw`, `return_krw`, `usd_same_basis: {contributions_usd, value_usd, gain_usd, return_usd}`, `fx_start`, `fx_change`, `fx_effect_pp`, `fx_counts: {ok, carried, missing}`, `unavailable_reason_ko`
- **예시:** `{"contributions_krw_total":11200000,"last":{"date":"2026-10-30","value_krw":13050250,"fx":{"rate":1379.05,"status":"ok"}},"gain_krw":1850250,"return_krw":0.1652,"usd_same_basis":{"contributions_usd":8235.8,"value_usd":9463.22,"return_usd":0.1490},"fx_change":0.0149,"fx_effect_pp":0.0162,"fx_counts":{"ok":109,"carried":1,"missing":0},"unavailable_reason_ko":null}`
- **계산 규칙 (필수):** 원화 평가액 = 그날 USD 평가액 × 그날(또는 대체) 환율. 넣은 원금(원화) = 원화 납입은 그 금액, USD 납입은 납입일 환율로 환산. 원화 수익률 = 원화 평가액 ÷ 넣은 원금 − 1. **USD 수익률에 환율을 곱하지 않는다.** 비교용 USD 수익률도 같은 방식(평가액 ÷ 넣은 원금 − 1). 시작일 환율이 없으면 원화 원금을 정할 수 없으므로 null + 사유. 기존 「운용 수익률」(시간가중)과 방식이 다름을 응답 문서에 명시.
- **기준 시점:** 날짜별 평가 기록(snapshot) 날짜. 대체 환율은 출처 날짜(`carried_from`)를 함께.
- **목업:** `mocks/data/paper.ts`(`fxPath`, `buildPaper`), `MockService.getPaperKrw`. **프런트 수정:** `api/service.ts`. 화면 `features/paper/KrwPerformance.tsx`·`PaperScreen.tsx`.
- **목록에도 필요:** 모의투자 목록의 수익률 칸을 원화 기준으로 보여 주려면 `GET /paper` 목록 행마다 `return_krw`(위와 같은 계산, 없으면 null + 사유)가 있어야 한다. 지금 목업은 행마다 `getPaperKrw` 를 불러 쓰고, 일반 모드는 서버 값이 생길 때까지 USD 운용 수익률을 보여 준다 (화면에서 환율로 다시 계산하지 않는다).
- **주의:** 「환율 1.00 관련 원화 값 문제」는 서버 문제로 남아 있다 — 환율이 1.00 으로 오면 `missing` 으로 처리하는 정책 필요.

### 2-12. 분석 리포트 확장 (`ReportDoc.proposed`) — 2단계

리포트 응답(`GET /reports/{id}`)에 붙이는 확장 묶음. 화면은 `proposedOf(doc)` 와 `features/report/proposedView.tsx` 어댑터로만 읽는다 (없으면 기존 서버 문장 해석 `wording.ts` 로 대체).

| 필드 | 쓰는 곳 | 의미·기준 시점 | 필요한 계산/정책 |
|---|---|---|---|
| `execution` | 카드 2 「예상 매수 주문」 | 분석 기준일 가격·환율로 카드 2 배분(분석 기준일 현재 구성) 비중을 주문 단위로 바꾼 값 — 카드 금액과 같은 기준 | 정수 주식 반올림 규칙, 수수료(bp), 남는 현금. 목표 배분액과 구분. 합계 + 수수료 + 남는 현금 = 투자금 |
| `allocations` (`current`/`recommended_now`/`backtest_start`) | 카드 2 현금 금액 (`current` 만 씀) | 각 구성의 기준일·전략을 반드시 함께 | 현금 금액(USD/KRW) 포함. 원화는 기준일 환율. 세 구성을 고르는 버튼은 헷갈려서 두지 않기로 했다 — 화면은 `current` 의 현금 금액만 쓴다 |
| `chosen_vs_baseline` | 2. 종목·비중 | 선택 전략이 비교표에 없을 때(낙폭 맞춤안 등) 기준 비중과 같은 시점 비교 | 같은 날짜의 두 비중 |
| `company_views` | 3. 기업 카드 | 기업별 뉴스 투자 의견 여부(generated / insufficient / disabled)와 이유 | 근거 ID 연결 |
| `request_log` | 6. 내 요청 | 아이디어·질문 답·말로 보탠 요청과 결과·최종 조건 | 2-8 과 같은 결과 형식 |
| `krw` | 리밸런싱 기록 원화 | 날짜별 환율·원화 평가액·순투입 원금 | 2-11 과 같은 원칙 |
| `market_topics` | 4. 시장·뉴스 「주제별로 보기」 | 시장/산업/테마/근거 분류 | LLM 분류 + 근거 ID |
| `company_reasons` | 3. 「핵심 선정 이유」 | 구조화된 이유(지표·테마·인용·근거) | 원문은 그대로 유지 |
| `risk_profile` | 카드 4, 요청 조건 | 분석 당시 5단계 성향(자동 진단 → 최종), 변동성 선호 기본/적용과 이유, 짧은 기간 참고 검사 | 분석 시점 프로필 버전 고정 |
| `structured` | 판단 이유·카드 3·4·KPI·타임라인 제목·비교표 역할 | 서버 문장 대신 쓰는 구조화 값 (검증 규칙 R1/R3/R7, 연 환산, 요청 금액, 원화 최종액 등) | 연 환산 최소 기간(378일) 등 규칙 문서화 |
| `explanations` | 전략·순위 기준·ETF·용어 설명 | 서버가 가진 설명을 내려줌 | 지금은 일부를 프런트가 가지고 있음 |

- **예시:** `execution` → `{"as_of":"2026-10-30","strategy_label_ko":"동일비중","share_basis":"integer","commission_bps":5,"fx":{"rate":1380,"date":"2026-10-30"},"capital":{"amount":20000000,"currency":"KRW"},"items":[{"ticker":"NVDA","price_usd":182.4,"target_weight":0.1667,"target_krw":3333333,"shares":13,"cost_usd":2371.2,"fee_usd":1.19}],"totals":{"invested_usd":13275,"fee_usd":6.64,"cash_left_usd":1211.11}}`
- **목업:** `mocks/data/report.ts`(`buildReport`, `execution()`, `explanations()`), `mocks/data/backtest.ts`. **프런트 수정:** `api/proposed.ts`(`proposedOf`), `features/report/proposedView.tsx`(어댑터). 카드·섹션 컴포넌트는 어댑터 결과만 본다.
- **주의:** 일부 값(값 USD 차트의 원화, ETF·변동성 기본값 설명)은 아직 프런트 문구다(2단계 부분 구현). 서버가 `explanations` 를 주면 그쪽을 우선.

---

### 2-13. 저장된 리포트 삭제

- **부족한 데이터:** 서버에 리포트 삭제 API가 없다 (`reports.py` 는 조회·재분석·수정안만).
- **API (제안):** `DELETE /reports/{report_id}` → 204. 실행 ID로 불러도 같은 리포트.
- **정책 (서버와 정할 것):** 삭제 후 `GET /reports` 목록·`GET /reports/{id}`(404)에서 빠질 것. 이 리포트로 만든 모의투자·수정안 리포트를 어떻게 둘지(목업은 그대로 둔다), 실제로 지울지 숨김 표시만 할지.
- **목업:** `MockService.deleteReport` (상태 `deletedReports`, 목록·상세에서 뺀다). **프런트 수정:** `api/service.ts` 에 `deleteReport` 를 넣으면 목록의 「삭제」 버튼과 확인 창이 일반 모드에서도 열린다. 화면 `features/report/ReportList.tsx`.
- **지금 일반 모드:** 이름·설명을 누르면 열리고(「열기」 버튼 없음), 삭제 버튼은 보이지 않는다.

### 2-14. 리밸런싱 알림 · 새 리포트 표시 (사용자별 확인 기록)

- **지금 (두 모드 공통, 서버 추가 없음):** 확인 기록을 **브라우저에만** 저장한다 (`src/lib/seen.ts`, 일반 모드 `localStorage` 키 `myfinsight.seen.v1`, 목업 `sessionStorage`). 처음 켤 때 이미 있던 리포트·리밸런싱은 확인한 것으로 두고, 그 뒤에 생긴 것만 알린다.
  - 사이드바 「분석 리포트」 숫자 = 목록(`GET /reports`)에 새로 생겨 아직 열지 않은 리포트 수. 리포트를 열면 사라진다.
  - 사이드바 「모의투자」 숫자 = 목록(`GET /paper`)의 `n_rebalances` 가 확인한 번호보다 큰 모의투자만 상세(`GET /paper/{id}`)를 불러, 실제로 거래한 정기 리밸런싱(`kind: "rebalance"`, 건너뜀 아님, 거래 있음)이 있으면 센다. 상세 화면의 「확인했어요」로 사라진다.
  - 다음 리밸런싱 시점: `rebalance_rule`·`start_date`·`last_date` 로 서버 규칙(`m6_tracking/paper.py rebalance_due_dates`: 시작 기간부터 count 기간마다 기간 첫 거래일)을 따라 「2026년 12월 첫 거래일」처럼 **기간으로만** 말한다 (휴장일 달력은 서버에만 있음). 2주 단위는 「마지막 리밸런싱 뒤 10거래일째」.
- **한계:** 다른 기기·브라우저와 공유되지 않는다. 브라우저 기록을 지우면 처음 상태(모두 확인함)로 돌아간다.
- **서버에 있으면 더 좋은 것 (제안):**
  - `PaperSummary.last_rebalance: { seq: number; date: string; n_trades: number; skipped: boolean } | null` — 목록만으로 알림 여부를 판단 (지금은 후보마다 상세를 한 번 불러 확인).
  - `PaperSummary.next_rebalance_date: string | null` — 서버 거래일 달력으로 계산한 정확한 날짜.
  - 사용자별 확인 기록: `POST /reports/{id}/seen`, `POST /paper/{id}/rebalances/{seq}/ack` (또는 `GET/PUT /me/seen`), 목록 행에 `seen: boolean`·`unacked_rebalance_seq`. 생기면 `lib/seen.ts` 대신 서버 값을 쓰도록 `features/attention.ts` 한 곳만 바꾸면 된다.
- **목업:** `MockService.seenSeed()` 로 시연용 시작값(가장 최근 리포트 1개·첫 모의투자의 마지막 리밸런싱을 '확인 안 함')을 준다. 목업 모의투자는 매월 첫 거래일 정기 리밸런싱에서 가격 변화로 틀어진 비중을 되돌리는 매수·매도 거래를 만든다 (`mocks/data/paper.ts`).
- **프런트 파일:** `lib/seen.ts`, `features/attention.ts`(배지·목록 표시), `features/paper/rebalance.ts`(마지막 리밸런싱·다음 시점), `features/paper/RebalanceCard.tsx`(첫 화면 거래 카드·알림), `app/App.tsx`(사이드바), `ReportList.tsx`·`ReportDetail.tsx`·`PaperScreen.tsx`.

### 2-15. 대화형 초기 투자조건 (처음 사용자)

- **요약:** 투자조건이 없는 사용자가 챗봇처럼 필수 항목만 답해 기본 투자조건을 만든다 (`#/profile/chat`). 대화 API 는 초안만 만들고 저장은 기존 `PUT /profile`.
- **API (제안):** `POST /profile/chat`, `POST /profile/chat/{id}/answers`, `POST /profile/chat/{id}/rewind` → `ProposedProfileChat`
- **자세한 명세·정책:** [backend-requests-profile-chat.md](./backend-requests-profile-chat.md)
- **목업:** `MockService.startProfileChat/answerProfileChat/rewindProfileChat`, `mocks/data/profileChat.ts`. **프런트 수정:** `api/service.ts`. 화면 `features/profile/chat/*`, 진입 `app/App.tsx`·`features/home/HomeScreen.tsx`.
- **지금 일반 모드:** 대화 메서드가 없으므로 처음 사용자는 지금처럼 4단계 폼(`#/profile/setup`)으로 간다.

## 3. 일반 모드에 반영한 세 가지 (서버 추가 없이 기존 데이터만 사용)

| 기능 | 기준 | 서버에 있으면 더 좋은 것 (제안) |
|---|---|---|
| 홈 필수 포함 종목 | 프로필 `constraints.must_include_tickers` 를 티커 그대로 「NVDA 필수 포함」 배지 (없으면 표시 안 함) | — |
| 리포트 이름 통일 | `lib/reportName.ts`: 투자 아이디어(`idea` 첫 줄) → 요청 요약 → 선택 전략 → 실행 ID. 상세도 같은 목록 행을 써서 같은 이름, 서버 제목 `header.title_ko` 는 보조 줄 | 2-1 의 `name` (목록 행에 자동/사용자 이름). 또는 최소한 목록 행에 `title_ko` |
| 같은 리포트의 여러 모의투자 구분 | 「적용 전략 · 시작일 시작 · 초기 투자금」 표기(`features/paper/paperLabel.tsx`) + 원본 리포트 이름, 같은 리포트 모의투자 수·링크, 시작 창의 기존 모의투자 목록 | 모의투자 목록 행에 원본 리포트 이름, 2-2 의 이름 연동 |

### 3-1. 회의 피드백으로 두 모드에 함께 반영한 것 (서버 추가 없음)

| 기능 | 화면 | 기준 |
|---|---|---|
| 사이드바 아래 상태 문구 삭제 | 사이드바 | 「자료 기준일 · 분석 일꾼 실행 중 · 대기 N건 · 분석 모델 연결됨」 줄 삭제. 서버 연결 끊김·연습 모드·분석 일꾼 꺼짐 경고 배지는 문제가 있을 때만 그대로 보인다 |
| 전략 이름에 전문용어 괄호 | 내 투자조건(투자 전략 단계·저장 요약·변경 이력), 상세 조건 창, 조건 바꾸기 | `profile/strategyInfo.ts` 의 `templateLabel`·`weightingLabel`: 「최근 주가 상승세가 좋은 기업(모멘텀)」, 「모든 기업에 비슷하게 투자(동일비중)」. 저장 요약은 「저평가 기업 중심(저PER) · … · 뉴스 반영 켜짐」 |
| 리포트 문장의 지표 ID 숨김 | 리포트 「왜 이 기업들을 선택했나요?」 선정 지표 설명·선정 과정 깔때기·문단 | `lib/reportNormalize.ts` 의 `hideCodeIds`: 괄호 속 소문자·밑줄 ID(`(return_12m_1m)` 등)만 화면에서 지운다. (ROE)·(SPY) 같은 용어 괄호와 계산용 ID 값은 그대로 |
| 종목 비중 막대 정렬 | 리포트 카드 2 | 모든 줄이 같은 칸(부모 격자 + subgrid)을 써서 금액 글자 길이와 상관없이 막대 시작 위치·길이 기준이 같다. 막대는 가장 큰 비중 기준, 비중(%)은 이름 옆 |
| 리밸런싱 거래를 첫 화면으로 | 모의투자 상세 | 마지막 정기 리밸런싱(없으면 최초 매수)의 매수·매도를 핵심 성과(목업은 원화 기준 성과) 아래, 위험 위에 보여 준다. 서버 거래 기록 그대로 |
| 리밸런싱 알림·숫자 배지 | 사이드바, 리포트 목록, 모의투자 목록·상세 | 2-14 (브라우저 확인 기록) |

**백엔드에 정리해 두면 좋은 것 (고치지 않음):** 선정 지표 설명(`m5_backtest_report/report.py` `_metric_note`)과 선정 과정 이름(`collect.py` 「선정 지표({metric}) 계산 가능」)이 지표 ID 를 함께 적는다 — 프런트는 화면에서만 지운다.

---

## 4. 미확정 사항 (서버와 정해야 할 것)

1. 확장 필드 위치: 기존 응답에 `proposed` 묶음으로 둘지, 정식 필드로 흩어 둘지 (프런트는 접근 함수 한 곳만 바꾸면 됨).
2. 리포트 자동 이름 생성 방식(LLM/규칙), 생성 시점, 실패 시 대체 규칙.
3. 종목 검색 범위(지원 유니버스만? 한국 종목코드 표기), 회사명 한/영 우선순위.
4. 초기 투자금 0원 시 백테스트·모의투자·리포트 금액 표기 규칙.
5. 성향 기반 추천 규칙 자체 (현재 없음).
6. 여러 질문 API에서 필수/선택을 정하는 기준, 자유 입력 해석 실패 시 응답.
7. 말로 보태기 결과의 `needs_confirmation` 이후 흐름 (추가 질문으로 바꿀지).
8. 즉시 취소 가능 여부와 취소 중 상태가 얼마나 지속되는지.
9. 경고 ID·중복 기준(같은 문구 vs 같은 코드).
10. 원화 성과의 대체 환율 정책(직전 영업일 몇 일까지 허용), 환율 1.00 처리, 시작일 환율이 없을 때 정책.
11. 리밸런싱 알림을 언제까지 보여 줄지 (지금은 사용자가 「확인했어요」를 누를 때까지), 확인 기록을 서버에 둘지와 기기 간 공유 범위.
12. 대화형 초기 투자조건: 묻지 않는 항목의 기본값 출처, 질문 수·순서와 성향 진단 문항 관리 주체, 저장하지 않은 대화 보관 기간, 자유 문장 답 해석 (자세히: backend-requests-profile-chat.md 1·2절).

---

## 5. 목업으로 화면만 재현한 백엔드 문제 (고친 것 아님 — 백엔드 요청 목록)

아래는 실제 서버·LLM·데이터 정책 문제이며, 이번 작업에서 **해결하지 않았다.** 목업은 화면만 재현한다.

- 이미 답한 조건을 다시 질문하는 문제
- 자연어 추가 요청이 실제 투자조건에 반영되지 않는 문제
- AI 생성 본문의 용어·투자성향 표현 불일치
- 서버가 만든 「1년 미만」 문구 문제
- 분석 완료 단계 요약의 전문 용어
- 변동성 관련 서버 문구 오류
- 짧은 기간의 비교지수 수익률 차이
- 연환산 수익률을 쓰는 실제 검증·추천 규칙
- 거래일 252개/251개 혼재
- 환율 1.00 관련 원화 값 문제
- 투자성향 기반 자동 추천의 실제 규칙
- 모의투자 목록 API의 환율·회사명 응답 추가
- 한국어 제외 테마가 실제 분석에 반영되는지 검증
- 실제 서버의 분석 즉시 취소
- 실제 데이터 기반 추가 질문·분석 실행
- 실제 모의투자 갱신·중지·재개 동작

---

## 6. 프런트 파일 지도 (연동 시 볼 곳)

| 파일 | 역할 |
|---|---|
| `src/api/proposed.ts` | 제안 계약 타입·접근 함수 (연동 시 위치 변경의 단일 지점) |
| `src/api/service.ts` | `AnalysisService`(= 기존 + 선택 `ProposedApi`), `HttpService`(실제 서버). 새 메서드는 여기 추가 |
| `src/features/report/proposedView.tsx` | 리포트 확장 어댑터 (구조화 값 우선, 없으면 기존 문장 해석) |
| `src/features/report/ReportName.tsx`, `src/lib/reportName.ts` | 리포트 이름 바꾸기 창 / 표시 이름 기준 |
| `src/features/paper/PaperName.tsx`, `paperLabel.tsx`, `KrwPerformance.tsx` | 모의투자 이름 / 구분 표기 / 원화 성과 |
| `src/features/profile/stocks.tsx`, `StrategyRecommend.tsx`, `compare.tsx` | 종목 검색·회사명 / 성향 기반 추천 / 버전 비교 |
| `src/features/profile/chat/*`, `defaults.ts`, `validate.ts` | 대화형 초기 투자조건 화면 / 폼과 같이 쓰는 기본값·검사 |
| `src/features/analysis/BatchQuestions.tsx`, `MessageOutcome.tsx` | 여러 질문 한 번에 / 말로 보태기 결과 |
| `src/features/run/RunScreen.tsx`, `steps.ts` | 취소 결과·전체 경고 |
| `src/mocks/**` | 목업 전용 (운영 빌드에 들어가지 않음) — 연동 후에도 디자인 확인용으로 유지 가능 |
