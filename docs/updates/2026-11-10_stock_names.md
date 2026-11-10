# 목업 기능 실제 연결 A: 종목 검색·「회사명 (티커)」 표시 (2026-11-10)

이슈 #14 묶음 A(2번 회사 이름으로 종목 검색, 8번 종목을 「회사명 (티커)」로 표시)를 실제 서버에 연결했다.
각 항목은 "무엇을 / 왜 / 어디를(파일) / 어떻게 확인했나"를 적는다.

## 1. 문제

- 실제 모드의 투자조건 화면은 제외·필수 포함 종목을 티커로 직접 입력했고(`NVDA`), 화면 어디에도 회사 이름이 없었다. 종목 검색·조회 API 가 없어
  목업에만 있던 검색 칸(`features/profile/stocks.tsx`)·「회사명 (티커)」 칩·이력 비교의 이름이 숨겨져 있었다.
- 조건 확인 화면의 표(이번 분석에서 달라진 조건·전체 투자 조건)도 서버 문장(`value_ko`)이 티커만 적었다.

## 2. 결정

- **미국 종목은 영문 이름 그대로** (사용자 결정). DB 에는 한국 종목의 한국어 이름, 미국 종목의 영문 이름만 있고 미국 종목의 한국어 이름 자료가 없다.
  한국어 이름 표(번역·검수)는 나중 일로 두고, 지금은 영문 이름으로 찾고 보여 준다. 응답 모양은 제안 계약 그대로 두고 `name_ko` 에 영문 이름을 넣는다 (화면 표시 이름).
- 찾는 범위는 **지원 유니버스(S&P 500·NASDAQ-100·KOSPI 200) 구성종목** — 분석이 실제로 고를 수 있는 종목. 구성종목이 아닌 ETF 는 나오지 않는다.
- 8번은 **조건 표만**. 질문 보기 이름은 LLM 이 쓴 문장이라 서버가 안전하게 바꾸기 어렵다. 「말로 보태기 결과」는 묶음 C 의 API 라 그때 같이 한다.

## 3. 수정

### 백엔드

- **`backend/analysis/m2_data/stocks.py`(신규)**
  - `load_stocks(repo, as_of)`: 유니버스 셋의 최신 구성종목 스냅샷(`constituents_at`)을 합쳐 티커 하나에 한 줄. 이름·섹터(`sector_ko`)는 스냅샷에서.
  - `search(stocks, q, limit)`: 글자·숫자만 비교 (공백·쉼표·점·하이픈 무시 → `brk.b` = `BRK-B`, `micron tech` = `Micron Technology`). 한국 종목은 6자리 코드로도.
    순서: 티커 앞부분(티커가 똑같은 것 → 짧은 티커) → 이름 앞부분(짧은 이름) → 어디든 포함.
  - `lookup(stocks, tickers)`: 응답 `ticker` 는 요청한 표기 그대로 (화면이 그 표기로 찾는다). `005930`·`005930.KS`·`brk.b` 모두 찾고, 목록에 없는 티커는 빠진다.
- **`backend/analysis/api/routers/stocks.py`(신규)**: `GET /stocks/search?q=&limit=`(기본 8, 1~20), `GET /stocks?tickers=`(쉼표, 최대 100개).
- **`backend/analysis/api/services.py`**: `stocks()` — 목록을 하루 한 번만 DB 에서 다시 읽는다 (구성종목은 가끔 바뀜). `stock_label(t)` — 「회사명 (티커)」, 목록을 못 읽거나 없는 티커면 티커 그대로.
- **`backend/analysis/m1_request/conditions.py`·`dialog.py`**: `condition_rows`·`fmt` 에 선택 인자 `stock_label`, `DialogService(..., stock_label=)`.
  API 의 `Services.dialog()` 가 넘긴다. 넘기지 않으면(테스트·워커) 지금처럼 티커만.

### 화면

- **`Front/src/api/service.ts`**: `HttpService.searchStocks`(검색어 인코딩)·`getStocks`(티커가 없으면 요청하지 않음) → 실제 모드에서도 검색 칸·「회사명 (티커)」 칩·이력 비교 이름이 열린다.
- **`Front/src/api/proposed.ts`**: `ProposedStock.name_en` 을 `string | null` 로.
- **`Front/src/features/profile/stocks.tsx`**: 검색 결과 둘째 줄에 영문 이름은 `name_ko` 와 다를 때만 (미국 종목 이름이 두 번 나오지 않게, 한국 종목은 `null` 이 보이지 않게).
  안내·예시·못 찾음 문구는 목업이면 그대로, 실제 서버면 「미국 종목은 영문 이름, 한국 종목은 한글 이름」·「예: Micron, 삼성전자, MU」·「지원 종목(S&P 500·NASDAQ-100·KOSPI 200)에 없습니다」.
- 「목업에서만」 주석 정리 (`ProfileScreen.tsx`).

### 문서

- `Front/docs/backend-integration.md` §2-3 「✅ 실제 서버 구현」.

## 4. 알아 둘 것

- 한국 종목은 이름순으로 같은 길이면 가나다순이라, `삼성` 을 찾으면 삼성물산·삼성생명·삼성전기·삼성전자 순이다. 시가총액 순 정렬은 가격 자료가 필요해 넣지 않았다.
- 실제 DB 로 확인한 목록: 719개 (미국 518, 한국 201), 섹터 11개 모두 한국어.

## 5. 확인

브랜치는 main(`59769d2`)에서 땄다. 그 위에 먼저 테스트 구조 커밋(`cceec8d`)을 두었다: 「실제 서버에 연결된 제안 메서드」 목록(`mocks.test.tsx` 의 `CONNECTED`)을
묶음별 주석 자리로 나누고, 제안 메서드 전부(`PROPOSED_METHODS`)에 대해 목업은 모두·실제 서버는 연결된 것만 있는지 본다. 같은 커밋을 묶음 F 브랜치에도 병합해 두어,
A·F 가 각자 자기 자리에만 이름을 더하므로 둘을 합쳐도 충돌하지 않는다. 이후 묶음(C·D·B…)도 main 에서 따서 자기 주석 아래에만 더하면 된다.

- **백엔드:** 새 `test_stocks.py` 14개 — 유니버스 종목 한 번씩·ETF 없음·미국 영문/한국 한글, 이름·티커·6자리 코드·공백·대소문자·기호 검색, 순서, 빈 검색어·한도,
  요청 표기 그대로 돌려주기, API(422 포함)와 하루 캐시(구성종목 3번만 읽음), 조건 표 「회사명 (티커)」·없는 티커·이름 함수 없을 때, 목록을 못 읽으면 티커로.
  실제 DB 읽기 확인: `micron`·`nvidia`·`brk.b`·`005930`·`삼성`·`현대` 검색. `backend/tests/analysis` 전체 432 passed (main 기준).
- **프런트:** `npm run typecheck` 통과, `vitest run` 300 passed (main 기준). `mocks.test.tsx` 연결 메서드·요청 주소(한글 검색어 인코딩, 빈 목록이면 요청 없음),
  `profile.mock.test.tsx` 실제 서버 응답 모양(미국 종목 영문 이름 한 번, 한국 종목 `null` 안 보임, 지원 종목 기준 안내).
