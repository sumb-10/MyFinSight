# 연결 설정: 팀 DB 주소 · OpenAI 키를 화면에서 넣기 (2026-11-23)

`.env` 를 손으로 고치지 않아도 팀 DB 주소와 OpenAI 키를 화면에서 넣을 수 있게 했다. 저장소 없이 쓰는 배포판(`2026-11-23_packaging_release.md`)의 앞 단계다.
브랜치 `feature/front-connection-setup`, 커밋 `2576de5`, PR 33.
각 항목은 "무엇을 / 왜 / 어디를(파일) / 어떻게 확인했나"를 적는다.

## 1. 문제

- 팀 DB 주소와 OpenAI 키는 `.env` 에만 적을 수 있었다. 실행 파일로 받은 사람에게는 고칠 `.env` 가 없다.
- 연결이 안 된 상태를 알리는 화면이 없었다. 연습 모드 띠는 "서버 관리자가…"라고만 했다.
- `.env.example` 을 그대로 복사해 켜면 예시 글자(`sk-...`)가 진짜 값처럼 읽혔다.

## 2. 결정

- **값을 찾는 순서**: ① 환경변수(`.env` · Docker Compose) → ② 운영체제 보관함(화면에서 저장한 값) → ③ 없음(연습 모드).
  - 앱은 `.env` 를 읽기만 한다. 고치지 않고, 어떤 파일에도 비밀 값을 쓰지 않는다.
  - ①로 들어온 값은 화면에 「환경변수(.env)로 설정됨」으로 보이고 화면에서 바꿀 수 없다.
- **보관함**: Windows 자격 증명 관리자 · macOS 키체인 · Linux 키링 (`keyring` 라이브러리). 보관함이 없는 환경(Docker 등)에서는 화면이 입력칸 대신 ".env 에 적어 주세요"를 보여 준다.
- **저장 전에 실제로 접속해 본다.** 안 되면 저장하지 않고 원인 코드를 돌려준다: `host_not_found` · `no_response` · `auth_failed` · `database_not_found` · `invalid_key` · `quota` · `unknown`. 문구는 화면이 고른다.
- **값은 가려서만 돌려준다.** 가린 값도 이 컴퓨터에서 물었을 때만 주고, 저장 · 지우기는 이 컴퓨터에서 온 요청만 받는다.
- **연결 흐름이 뜨는 때** (사용자 결정): 켤 때마다 한 번. 연결 안 된 것이 있으면 뜨고, 「나중에 하기」로 넘기면 그 창을 닫을 때까지 다시 묻지 않는다. 리포트 주소로 바로 들어오면 막지 않는다.
- **예시 글자는 넣지 않은 것으로 본다**: `.env.example` 의 `sk-...`, `your-endpoint`, `PASSWORD@` 같은 값은 켤 때 이 프로세스의 환경변수에서 뺀다 (파일은 그대로).
- **사용료 어림**: 실행 기록이 5건 미만이면 0.1달러, 그 뒤로는 최근 실행의 중앙값.

## 3. 수정

### 서버

- **`backend/analysis/connections.py`(신규)**: 값 찾기, 접속 확인, 오류 분류, 가리기, 저장 · 지우기, 사용료 어림, 예시 글자 빼기.
- **`backend/analysis/secret_store.py`(신규)**: 운영체제 보관함 읽기 · 쓰기. `MYFINSIGHT_SECRET_STORE=none` 으로 끄고, `MYFINSIGHT_SECRET_SERVICE` 로 항목 이름을 바꾼다.
- **`api/routers/connections.py`(신규)**: `GET` · `PUT` · `DELETE /connections`.
- **`api/services.py`**: `reload_connections()` — 값이 바뀌면 서버를 다시 켜지 않고 반영.
- **`executor/worker.py`**: 일꾼은 저장소 폴더의 `connections.stamp`(시각만 적힌 파일)를 보고 값이 바뀐 것을 알아채 설정과 DB 를 다시 연다.
- **`m2_data/market_data.py`**: `data_starts()` — 시장별 자료 시작일(미국 SPY, 한국 069500.KS 의 첫 날짜).
- `pyproject.toml`: `analysis` 묶음에 `keyring>=24`.

### 화면

- **`features/connect/`(신규)**: `ConnectFlow`(팀 DB → 분석 모델 → 투자조건), `ConnectionSettings`(연결 설정 화면), 주소 풀어 보여 주기(`dbUrl`), 문구(`copy`).
- 주소: `#/connect` · `#/connect/llm` · `#/settings`. 사이드바 메뉴와 연습 모드 알림에서 들어온다.
- 최신 거래일 아래에 「자료 시작일」을 미국 · 한국 따로 표시.
- 목업 서비스에도 같은 기능 (`mocks/data/connections.ts`).

## 4. 알아 둘 것

- `pip install -e ".[analysis]"` 를 다시 해야 한다 (`keyring`). 없어도 서버는 뜨고, 그때는 `.env` 로만 넣을 수 있다.
- 기존에 `.env` 를 쓰던 환경은 동작이 같다. `.env` 값이 가장 먼저 쓰인다.
- `MYFINSIGHT_LLM=stub` 이 환경변수에 있으면 키를 저장하지 않고 그 사정을 알린다. `.env.example` 에 이 줄이 있어서, 예시를 복사한 사람은 그 줄을 지워야 화면에서 키를 넣을 수 있다. 예시 파일을 고칠지는 미정.
- `MYFINSIGHT_LLM=api` 인데 키가 없으면 화면이 분석 모델을 연결된 것으로 본다. 팀 DB 만 연결하면 알림이 뜨지 않는데 분석은 실패한다. 고치지 않았다.
- 테스트는 공통 고정물이 보관함을 꺼서(`MYFINSIGHT_SECRET_STORE=none`) 실제 보관함을 건드리지 않는다.

## 5. 확인

- 서버 `test_connections.py` 통과, 화면 타입 검사 통과 · 화면 테스트 458 통과.
- Windows 자격 증명 관리자에 저장 → 서버를 껐다 켜도 연결 유지 → 일꾼이 변경을 알아챔 → 그 연결로 분석 실행 (시험용 항목 이름으로 하고 끝나고 지움).
- Docker 조건(환경변수 + 보관함 없음)으로 띄워 「환경변수로 설정됨」 표시 확인.
- 확인하지 못한 것: 실제 OpenAI 키로 연결 성공(가짜 키 거절만 확인), macOS 키체인, 실제 팀 DB 주소로 저장하는 흐름.
