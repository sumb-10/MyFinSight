# MyFinSight 프론트엔드

React 19 · TypeScript · Vite 8 · Tailwind CSS 4 · Recharts 기반 데스크톱 앱. 분석 서비스 API(`backend/analysis/api`, FastAPI :8001)를 호출하는 실제 클라이언트다. 요구사항과 디자인 기준은 [docs/README.md](docs/README.md).

> **화면은 두 가지 모드로 열 수 있다.** 그냥 열면 실제 서버를 쓰는 **일반 모드**이고, 주소에 `?mock=1` 을 붙이면 백엔드 없이 목업 자료로 도는 **목업 모드**다.
> 백엔드에 아직 없는 기능(리포트 이름 바꾸기·삭제, 여러 질문 한 번에 답하기, 원화 기준 성과 등)은 **목업 모드에서만 보인다.** 아래 「목업 모드」를 먼저 본다.

## 목업 모드 (백엔드 없이 화면 보기)

```sh
cd Front
nvm use
pnpm install --frozen-lockfile
pnpm dev
# 브라우저에서 http://localhost:5173/?mock=1#/home   (?mock=1 은 # 앞에)
```

- 백엔드를 켜지 않아도 된다. 목업 모드는 서버로 요청을 보내지 않고, 바꾼 내용은 이 브라우저 탭에만 저장된다 (탭을 닫거나 「목업 데이터 초기화」를 누르면 처음 상태).
- 화면 맨 위 노란 띠가 목업 모드 표시다. 목업 값이 쓰인 곳에는 「목업」 표시가 붙는다. 목업 결과는 **실제 투자 분석 결과가 아니다.**
- 오른쪽 아래 「목업 데이터」 버튼에서 시나리오(정상·주의·추천 없음 리포트, 진행 중 분석, 질문 중인 요청 등)로 바로 이동할 수 있다.
- 일반 모드로 돌아가려면 노란 띠의 「일반 모드로 돌아가기」를 누르거나 주소에서 `?mock=1` 을 뺀다.
- **개발 서버(`pnpm dev`)에서만 켜진다.** 운영 빌드(`pnpm build`)에는 목업 코드가 들어가지 않고 `?mock=1` 을 무시한다 (시연용으로만 `VITE_ENABLE_MOCK=1` 빌드 허용).
- 자세한 내용: [docs/mock-mode.md](docs/mock-mode.md) (기능별 위치·시나리오), 백엔드가 같은 기능을 지원하려면 필요한 API·데이터: [docs/backend-integration.md](docs/backend-integration.md).

## 로컬 실행 (일반 모드 — 실제 서버)

Node.js 22.x 와 pnpm 10. `.nvmrc` 가 22.22.2 를 지정한다.

```sh
# 1) 백엔드 (저장소 루트)
uvicorn backend.analysis.api.app:app --port 8001     # 서비스 API
python -m backend.analysis.executor.worker            # 분석 워커

# 2) 프론트
cd Front
nvm use
pnpm install --frozen-lockfile
pnpm dev          # http://localhost:5173  (/api → http://localhost:8001 프록시)
pnpm typecheck && pnpm test && pnpm build
```

리포트·모의투자·비교 화면은 차트 라이브러리(recharts)를 쓰므로 `React.lazy` 로 따로 묶여 처음 화면이 가볍게 뜬다. 단위 테스트는 Vitest + Testing Library (`src/**/*.test.ts(x)`: 표시 규칙, 라우터, 오류 메시지, 수정안 카드).

환경변수(`.env.example` → `.env.local`): `VITE_API_BASE`(기본 `/api/v1`), `VITE_PROXY_TARGET`. 일반 모드의 데이터 원천은 서버 하나뿐이다 (목업 모드는 위 「목업 모드」, 개발 서버에서만). 서버가 연습(stub) LLM 모드면 사이드바에 "연습 모드 (LLM 없음)" 배지가 뜬다.

## 구조

```
src/main.tsx                서비스 어댑터 생성 → Providers → App
src/app/                    router.ts(해시 라우팅, id 경로), providers.tsx(서비스·프로필·health), App.tsx(사이드바·화면 전환)
src/api/                    types.ts(백엔드 DTO 미러), client.ts(fetch + 오류 봉투 → ApiError), service.ts(계약 + HTTP 어댑터)
src/state/                  useResource(조회), usePolling(실행 상태 폴링), uiStorage(브라우저 편의 상태만)
src/ui/                     공통 프리미티브 (Button, Card, Badge, Alert, Field, SidePanel, Dialog, StatusRow …)
src/lib/format.ts           표시 규칙 (분수 입력, 수익률 2자리·비중 1자리·원화 정수·USD 2자리·%p, halfExpand)
src/features/profile        프로필 위저드 4단계(기본·성향 진단·범위·전략 선호) → PUT /profile, 요약·버전 이력
src/features/home           아이디어 입력 → POST /requests
src/features/analysis       ClarifyScreen(보충 질문: 선택지 + 자유 입력, 1회 1항목), ConfirmScreen(조건 확인 표 → 분석 시작)
src/features/run            RunScreen(GET /runs/{id} 폴링, 5묶음 실제 run_step 상태, 취소)
src/features/report         ReportList, ReportDetail(7섹션 블록 렌더, 인용 [n] → 출처 패널, 계산 조건·실행 기록 패널, 재분석·조건 수정 요청·모의투자 시작), RevisionPanel, ComparisonScreen(원안 vs 수정안), blocks/
src/features/analysis       RevisionCard (수정안 대화에서 반영한/못한 변경 표시)
src/features/paper          PaperScreen(목록 #/paper, 상세 #/paper/:id: 시작 이후 성과·비교지수, 비중, 거래·리밸런싱·일별 기록, 갱신·중지·재개), StartPaperDialog(미리보기 → 확인 → 등록)
```

## 흐름

프로필 설정 → 홈(아이디어) → 보충 질문(최대 N회, 서버값) → 조건 확인(프로필과 달라진 값 표시) → 분석 시작(큐 등록) → 진행(실제 단계 상태) → 리포트(7섹션·출처·계산 조건·실행 기록).
리포트에서 이어지는 두 흐름: **조건 수정 요청**(말로 적기 → 반영한/못한 변경 카드 → 같은 질문·확인 흐름 → 실행 → 원안과 비교 화면), **모의투자 시작**(전략·시작일·가상 자본 고르기 → 시작 비중 미리보기 → 등록 → 모의투자 상세). 모든 상태는 서버가 가지며 새로고침·재접속 시 URL 의 id 로 다시 불러온다. 끊긴 서버는 "서버 연결 끊김" 배지와 오류 상태로 보이고 성공처럼 보이지 않는다.

## 확인

- `pnpm typecheck`, `pnpm test`, `pnpm build` 통과.
- 서버와 함께: 합성 sqlite 로 띄운 API(`DATABASE_URL=sqlite:///…`)에 대해 프로필 → 아이디어 → 질문 → 확인 → 실행 → 리포트.
