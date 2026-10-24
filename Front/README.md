# MyFinSight 프론트엔드

React 19 · TypeScript · Vite 8 · Tailwind CSS 4 · Recharts 기반 데스크톱 앱입니다.
프로젝트 요구사항과 디자인 기준은 [docs/README.md](docs/README.md)를 참고하세요.

## 로컬 실행

Node.js 22.12 이상인 22.x와 pnpm 10을 사용합니다. `.nvmrc`는 이 컴퓨터에 설치된 22.22.2를 지정합니다.

```sh
cd Front
nvm use
pnpm install --frozen-lockfile
pnpm dev
```

접속 주소: <http://localhost:5173/>

`nvm`이 셸에 로드되지 않았다면 먼저 `source ~/.nvm/nvm.sh`를 실행하세요.
최초 접속은 투자조건 설정으로 이동합니다. 프로필을 저장하면 홈에서 분석 흐름을 시작할 수 있습니다.
서버 종료는 터미널에서 `Ctrl+C`를 누릅니다.

```sh
pnpm typecheck
pnpm build
pnpm preview
```

`preview`도 localhost:5173을 사용하므로 개발 서버를 종료한 후 실행하세요.
다른 포트가 필요하면 `pnpm dev --port 5174`처럼 지정할 수 있습니다.
포트가 사용 중이면 자동으로 다른 포트로 바꾸지 않고 오류를 표시합니다.

## 분석 파이프라인 리포트 화면 (`#/pipeline`)

`module_mockup` 파이프라인이 만든 리포트(`public/pipeline/report.json`)를 렌더링하는 독립 화면입니다. 기존 앱 화면·데이터 모델과 분리되어 있으며 `src/main.tsx` 가 해시가 `#/pipeline` 로 시작할 때만 이 화면을 보여줍니다.

- `src/pipeline/PipelineReport.tsx`: 섹션 메뉴 + 본문. `fetch("/pipeline/report.json")`
- `src/pipeline/blocks.tsx`: 블록 렌더러 (KPI 카드, 표, 도넛, 누적수익·평가금액 선 차트(시리즈 토글), 낙폭 영역 차트, 막대, 깔때기, 카드, 리밸런싱 시점 탐색기, 용어 풀이)
- `src/pipeline/types.ts`, `src/pipeline/format.ts`: report.json 타입과 표시 규칙(docs/04)
- 리포트 갱신: `module_mockup` 에서 `python scripts/stage15_publish.py` (또는 `run_pipeline.py --stop-at 15`) 실행 후 새로고침

## 현재 구현

- `src/App.tsx`: 프로필, 홈, 조건 확인, 분석 진행, 리포트, 모의투자, 수정안 비교와 패널. hash 기반 화면 이동.
- `src/types.ts`: 프로필·리포트·근거·전략·모의투자의 공유 타입.
- `src/config.ts`: 입력 범위, 지원 종목, 성향 질문과 고정 자료 기준일.
- `src/fixtures.ts`: 별도로 구성된 AI 전략·안정성 전략, 본문·출처·성과 자료.
- `src/localDataService.ts`: 브라우저 localStorage 저장. 키는 `myfinsight.local.v1`, 데이터 버전은 4.
- `src/lib.ts`: 표시 포맷, 일부 입력 검증과 성과 계산.
- `src/index.css`: 기존 파란색 강조, 밝은 배경, 최소 너비 1180px.

현재는 화면 상호작용을 확인하는 고정 자료 앱입니다. 실제 LLM, 시장자료 수집,
Python 전략 엔진, 백테스트 실행, 지속적인 모의투자 갱신은 연결되어 있지 않습니다.
신규 분석의 기본 결과는 AI 전략을 복사하고, 수정안은 고정 시계열을 변형합니다.
입력 조건에 따른 종목·비중·금액·본문 재계산은 구현되어 있지 않습니다.
외부 폰트(Google Fonts)를 불러오지만 실패하면 시스템 폰트를 사용합니다.

자료 기준일은 `2025-02-28`이며 현재 날짜를 의미하지 않습니다.
기본 제공되는 과거 리포트 2개와 모의투자 1개는 localStorage에 사용자 프로필이 없을 때도 공급됩니다.

## 후속 디자인 작업에서 확인할 사항

- 조건 변경에 맞는 전략·배분·계산 조건·본문의 정합성.
- 수정 비교의 실제 공통 기간·비용·통화 재평가.
- 근거 기록의 원문 검증과 링크 연결, 고정 실험 수치의 성격 표시.
- 실행 기록에 적힌 데이터 조회·Tool·LLM 출력과 실제 수행 사실의 구분.
- 저장 실패 처리, 이전 데이터 버전 마이그레이션에서 기존 결과 보존.
- 패널·대화상자의 초점 유지·복귀와 키보드 조작.

요구사항은 `docs/`를 기준으로 사용합니다. `src/imports/pasted_text/`의 이전 기획에는
현금 배분·모의투자 평균 수익·최고 전략 등의 내용이 있으나 최신 요구사항과 다릅니다.

## 실행 확인 (2026-10-03)

- Node 22.22.2, pnpm 10.20.0으로 기존 lockfile 의존성 설치.
- `pnpm typecheck`, `pnpm build` 통과. 빌드에는 500 kB 초과 JavaScript 번들 경고가 남아 있습니다.
- Chrome 1440px 화면에서 프로필 등록 → 자연어 입력 → NVIDIA 비중 보충 질문 →
  조건 확인 → 분석 완료 → 리포트 → 출처 패널 → 시작 확인 → 모의투자 상세 →
  과거 백테스트 전환을 확인했습니다.
- 새로고침 후 프로필·신규 리포트·모의투자와 원본 연결을 확인했습니다.
  위 흐름에서 브라우저 실행 오류는 없었습니다.
- 이 확인은 고정 자료 화면의 상호작용 검증이며 실제 전략 계산·자료 조회·LLM 호출 검증이 아닙니다.
