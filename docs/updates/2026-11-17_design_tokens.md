# 디자인 토큰: 홈 시안 3 기준 색·글씨 위계 (2026-11-17)

홈 시안 3(`feature/front-home-examples` 의 Example3)의 색·글씨 위계를 앱 전체가 따르도록 값을 한 파일에 모았다.
브랜치 `feature/front-home-redesign`, 커밋 `9b51964`.
각 항목은 "무엇을 / 왜 / 어디를(파일) / 어떻게 확인했나"를 적는다.

## 1. 문제

- 화면마다 Tailwind 기본 색 이름(`slate-600`, `blue-700` …)과 크기(`text-sm`, `text-xl` …)를 그때그때 골라 써서, 제목·본문·보조 글씨의 단계가 화면마다 달랐다.
- 시안 3을 옮기려면 시안의 색·글씨 단계를 다른 화면도 따라야 하는데, 1,300곳이 넘는 클래스를 한 번에 바꾸면 팀원 브랜치와 충돌이 크다.

## 2. 결정

- **토큰 파일 하나**(`Front/src/styles/tokens.css`). 위쪽은 시안 기준 토큰, 아래쪽은 기존 이름을 토큰에 잇는 연결 블록.
- **글씨 색은 용도 이름** (사용자 결정): `main`(제목·값·이름) · `body`(본문) · `sub`(이름표·날짜) · `hint`(입력 예시·비활성). ink/muted 같은 영어 뜻 이름은 알아보기 어려워서 쓰지 않는다.
- **글씨 묶음 스타일**: `t-display` 28/800 · `t-heading` 22/800 · `t-title` 15/700 · `t-strong` 14/600 · `t-body` 14/400 · `t-label` 13/500 · `t-meta` 12/400 (크기·굵기·색을 한 번에). 용도 이름(`main` 등)과 함께 쓸 수 있다.
- **크기는 숫자 이름** `text-12 · 13 · 14 · 15 · 18 · 22 · 28` — 색 `body` 와 이름이 겹치지 않게.
- **기존 화면은 코드 수정 없이 따라간다**: `slate-50…950`, `blue-50`, `text-xl/2xl/3xl` 이 토큰 값을 가리킨다. 새 코드는 slate 이름을 쓰지 않고, 화면을 손볼 때 바꿔 나간다. 토큰 브랜치를 따로 만들지 않고 홈 이식 브랜치에서 함께 (사용자 결정).

| 구분 | 이름 · 값 |
| --- | --- |
| 글씨 | main `#34383f` · body `#4e545e` · sub `#646b77` · hint `#8b95a1` |
| 면·선 | canvas `#f2f5f7` · surface `#fff` · sunken `#f2f5f7` · sunken-hover `#e7ebef` · line `#e5e8eb` · bubble `#eef1f4` |
| 강조 | accent `#1d4ed8` · accent-hover `#1e40af` · tint `#eef3fe` · focus `#4880ee` |
| 의미 | up `#047857` · down `#b91c1c` · danger `#b91c1c`(+tint `#fef2f2`) · warning `#92400e`(+tint `#fffbeb`) · success `#047857`(+tint `#ecfdf5`) |
| 둥글기 | chip 8 · control 12 · bubble 14 · box 18 · card 24 |

## 3. 수정

### 화면

- **`Front/src/styles/tokens.css`(신규)**: `@theme` 토큰, `@utility t-*` 묶음, 기존 이름 연결 블록.
- **`Front/src/index.css`**: 토큰을 불러오고, 쓰지 않던 brand 토큰을 지움. 바탕·글씨·포커스 색을 토큰으로.
- `bubble`(대화 말풍선 면)·`bubble` 둥글기는 11-18 대화창 작업에서 더함 (`2026-11-17_home_chat_stepper.md`).

## 4. 알아 둘 것

- 글씨 대비(흰 바탕 / 회색 상자): main 11.8 / 10.8 · body 7.6 / 7.0 · sub 5.4 / 4.9 · hint 3.1. hint 는 정보가 아닌 글씨(입력 예시 등)에만.
- `index.css` 의 `button, input, textarea, select { font: inherit }` 는 레이어 밖 규칙이라 Tailwind 글자 크기 클래스를 이긴다. 앱 전체는 그대로 두고 홈(`.home-redesign`)만 `revert-layer` 로 되돌렸다 (`home/home.css`).
- 상승·하락 색을 한국식(빨강·파랑)으로 바꿀지는 아직 정하지 않았다. 정하면 `--color-up/down` 두 줄만 고친다.
- 차트·그림 안에 직접 쓴 색 13곳, 12px 보다 작은 글씨(`text-[11px]` 등)는 아직 토큰 밖이다.

## 5. 확인

- 이 커밋만 있는 상태에서 타입 검사 통과, 화면 테스트 356 통과 (기존 테스트 그대로).
- 실제 서버 화면에서 토큰 적용 전·후 비교 캡처: `_local/design_compare_2026-11-17/out/` (01~11).
