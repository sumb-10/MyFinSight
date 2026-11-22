import { Activity, AlertCircle, AlertTriangle, FileText, Home, Settings, SlidersHorizontal, TrendingUp, WifiOff } from "lucide-react"
import { useHealth, useProfile, useService } from "./providers"
import { lazy, Suspense } from "react"
import { navigate, useHashRoute, type Route } from "./router"
import { useResource } from "../state/useResource"
import { Alert, Button, EmptyState, Loading, NOTICE_BOX, NOTICE_ICON, type NoticeTone } from "../ui"
import { HomeScreen } from "../features/home/HomeScreen"
import { ProfileScreen } from "../features/profile/ProfileScreen"
import { ProfileChatScreen } from "../features/profile/chat/ProfileChatScreen"
import { ClarifyRoute } from "../features/analysis/ClarifyRoute"
import { ConfirmScreen } from "../features/analysis/ConfirmScreen"
import { RunScreen } from "../features/run/RunScreen"
import { ReportList } from "../features/report/ReportList"
import { useRenameTick } from "../features/report/ReportName"
import { reportName } from "../lib/reportName"
import { proposedNameOf } from "../api/proposed"
import { MockTag } from "../features/report/proposedView"
import { date } from "../lib/format"
import { isMockMode } from "../mocks/mode"
import { reportKey, useNewReports, useRebalanceAlerts } from "../features/attention"
import { EXAMPLE_REPORT_ID } from "../features/tutorial/exampleReport"
import { guideDestination, useGuideGate } from "../features/tutorial/GuidePrompt"
import { IntroScroll, introSeen } from "../features/tutorial/IntroScroll"
import { ConnectFlow } from "../features/connect/ConnectFlow"
import { ConnectionSettings } from "../features/connect/ConnectionSettings"
import { connectSkipped } from "../features/connect/skip"
import type { Health } from "../api/types"

/** 연습 모드: 팀 DB 나 분석 모델 중 하나라도 연결되지 않아 예시 데이터·미리 만든 답으로 도는 상태 */
const practicing = (h: Health | null) => !!h && (h.llm_mode === "stub" || !h.db.ok)


// 차트(recharts)를 쓰는 화면은 따로 묶어 처음 화면이 가볍게 뜨게 한다 (F8 코드 분할).
const ReportDetail = lazy(() => import("../features/report/ReportDetail").then((m) => ({ default: m.ReportDetail })))
const ComparisonScreen = lazy(() => import("../features/report/ComparisonScreen").then((m) => ({ default: m.ComparisonScreen })))
// 목업 모드 표시·개발용 패널: 개발 환경 + ?mock=1 일 때만 불러온다. 환경 조건을 그대로 써야 운영 빌드에서 import 가 빠진다 (mocks/mode.ts 참고).
const MockChrome = import.meta.env.DEV || import.meta.env.VITE_ENABLE_MOCK === "1" ? lazy(() => import("../mocks/MockChrome")) : null
const TutorialScreen = lazy(() => import("../features/tutorial/TutorialScreen").then((m) => ({ default: m.TutorialScreen })))  // 예시 리포트 둘러보기 (예시 리포트, 운영 빌드에서도 동작)
const PaperScreen = lazy(() => import("../features/paper/PaperScreen").then((m) => ({ default: m.PaperScreen })))

export function Sidebar({ route }: { route: Route }) {
  const svc = useService()
  const { health, reachable } = useHealth()
  const renamed = useRenameTick()
  const reports = useResource(() => svc.listReports(), [svc, route.page, renamed])
  const papers = useResource(() => svc.listPaper(), [svc, route.page, renamed])
  // 숫자 배지(카카오톡처럼): 새로 완료돼 아직 열지 않은 리포트 수, 확인하지 않은 리밸런싱 거래가 있는 모의투자 수. 확인 기록은 이 브라우저에만 있다.
  const fresh = useNewReports(reports.data)
  const alerts = useRebalanceAlerts(papers.data)
  const gate = useGuideGate()  // 「분석 리포트」를 처음 누르면 리포트 가이드를 볼지 묻는다
  const items = [
    { label: "홈 · 새 분석", icon: Home, to: { page: "home" } as Route, active: ["home", "clarify", "confirm", "run"].includes(route.page), badge: 0, badgeText: "" },
    { label: "분석 리포트", icon: FileText, to: { page: "reports" } as Route, active: ["reports", "report"].includes(route.page), badge: fresh.size, badgeText: `새로 완료된 리포트 ${fresh.size}개` },
    { label: "모의투자", icon: Activity, to: { page: "paper" } as Route, active: route.page === "paper", badge: alerts.size, badgeText: `리밸런싱 확인 ${alerts.size}건` },
    { label: "내 투자조건", icon: SlidersHorizontal, to: { page: "profile" } as Route, active: route.page === "profile", badge: 0, badgeText: "" },
  ]
  return (
    <aside className="sticky top-0 flex h-screen w-60 shrink-0 flex-col border-r border-slate-200 bg-white px-4 py-6">
      <button onClick={() => navigate({ page: "home" })} className="flex items-center gap-3 rounded-xl px-2 text-left focus:outline-none focus:ring-2 focus:ring-blue-500">
        <span className="flex size-9 items-center justify-center rounded-xl bg-blue-700 text-white"><TrendingUp className="size-5" /></span>
        <span><span className="block text-base font-extrabold tracking-tight text-slate-950">MyFinSight</span><span className="block text-[10px] font-medium text-slate-400">개인화 투자전략</span></span>
      </button>
      <nav data-tour="home-menu" className="mt-8 space-y-1" aria-label="주 메뉴">
        {items.map((item) => (
          <button key={item.label} onClick={() => (item.to.page === "reports" ? gate.go(item.to) : navigate(item.to))} className={`flex w-full items-center justify-between rounded-xl px-3 py-2.5 text-sm font-semibold transition focus:outline-none focus:ring-2 focus:ring-blue-500 ${item.active ? "bg-blue-50 text-blue-700" : "text-slate-600 hover:bg-slate-50 hover:text-slate-900"}`}>
            <span className="flex items-center gap-3"><item.icon className="size-4" />{item.label}</span>
            {item.badge > 0 && <><span aria-hidden className="inline-flex h-5 min-w-5 items-center justify-center rounded-full bg-red-500 px-1.5 text-[11px] font-bold tabular-nums text-white">{item.badge}</span><span className="sr-only"> ({item.badgeText})</span></>}
          </button>
        ))}
      </nav>
      <div className="mt-5 border-t border-slate-100 pt-5">
        <p className="px-3 text-[11px] font-bold tracking-wider text-slate-400">최근 리포트</p>
        <div className="mt-2 space-y-1">
          {(reports.data ?? []).slice(0, 5).map((r) => (
            <button key={r.run_id} onClick={() => navigate({ page: "report", reportId: r.report_id ?? r.run_id })} className={`w-full rounded-lg px-3 py-2 text-left transition hover:bg-slate-50 focus:outline-none focus:ring-2 focus:ring-blue-500 ${route.page === "report" && route.reportId === (r.report_id ?? r.run_id) ? "bg-blue-50" : ""}`}>
              <span className="flex min-w-0 items-center gap-1.5 text-xs font-semibold text-slate-700">{fresh.has(reportKey(r)) && <><span aria-hidden className="size-1.5 shrink-0 rounded-full bg-red-500" /><span className="sr-only">새 리포트:</span></>}<span className="truncate">{reportName(r)}</span>{proposedNameOf(r) && <MockTag />}</span>
              <span className="mt-0.5 block text-[10px] text-slate-400">{date(r.created_at)} · 기준일 {r.as_of}</span>
            </button>
          ))}
          {reports.status === "ready" && (reports.data ?? []).length === 0 && <p className="px-3 text-xs text-slate-400">아직 리포트가 없습니다.</p>}
        </div>
      </div>
      <div className="mt-auto space-y-2 px-1 text-[11px] leading-5 text-slate-500">
        {!reachable && <SideNote tone="error" icon={WifiOff}>서버 연결 끊김</SideNote>}
        {/* 연결 설정(제안 기능)이 있으면: 연습 모드 표시는 한 줄로, 들어가는 길은 바로 아래 「연결 설정」. 없으면 지금까지처럼 */}
        {svc.getConnections
          ? practicing(health) && <SideNote tone="warning" icon={AlertTriangle}>연습 모드</SideNote>
          : health?.llm_mode === "stub" && <SideNote tone="warning" icon={AlertTriangle}>연습 모드 (LLM 없음)</SideNote>}
        {health && reachable && !health.worker.alive && <SideNote tone="error" icon={AlertCircle} detail="실행해 두면 기다렸다가 다시 켜지면 자동으로 시작돼요">분석 실행이 멈춰 있어요</SideNote>}
        {svc.getConnections && (
          <button onClick={() => navigate({ page: "settings" })} aria-current={route.page === "settings" ? "page" : undefined} className={`-mx-1 flex w-[calc(100%+0.5rem)] rounded-xl px-3 py-2.5 transition focus:outline-none focus:ring-2 focus:ring-blue-500 ${route.page === "settings" ? "bg-blue-50 text-blue-700" : "text-slate-600 hover:bg-slate-50 hover:text-slate-900"}`}>
            {/* 글자 크기·굵기는 안쪽에: 전역 「button { font: inherit }」가 버튼에 준 클래스를 덮어써서, 이 자리(작은 글씨 영역)에서는 11px 로 줄어든다 */}
            <span className="flex items-center gap-3 text-sm font-semibold"><Settings className="size-4" aria-hidden="true" />연결 설정</span>
          </button>
        )}
      </div>
      {gate.dialog}
    </aside>
  )
}

/** 사이드바 아래 서버 상태 안내: 알림 상자와 같은 모양(테두리 없음 · 연한 면 · 색은 아이콘에만, 2026-11-18) */
function SideNote({ tone, icon: Icon, children, detail }: { tone: NoticeTone; icon: React.ElementType; children: React.ReactNode; detail?: string }) {
  // 제목 한 줄 + 설명 한 줄로 나눠 문장 중간에서 줄이 끊기지 않게 한다 (사이드바 폭 240px)
  return (
    <p className={`flex items-start gap-1.5 break-keep rounded-control px-2.5 py-1.5 text-12 leading-5 ${NOTICE_BOX[tone]}`}>
      <Icon className={`mt-0.5 size-3.5 shrink-0 ${NOTICE_ICON[tone]}`} aria-hidden="true" />
      <span><b className="block font-semibold text-main">{children}</b>{detail && <span className="block text-body">{detail}</span>}</span>
    </p>
  )
}

function Screen({ route }: { route: Route }) {
  const { profile, status } = useProfile()
  const svc = useService()
  switch (route.page) {
    case "home": return <HomeScreen />
    case "profile": return route.mode === "chat" ? <ProfileChatScreen /> : <ProfileScreen mode={route.mode ?? (profile ? "view" : "setup")} />
    case "clarify": return <ClarifyRoute key={route.requestId} requestId={route.requestId} />  // 새 분석은 홈 대화창, 재분석·수정 요청은 질문 화면
    case "confirm": return <ConfirmScreen requestId={route.requestId} />
    case "run": return <RunScreen runId={route.runId} />
    case "reports": return <ReportList />
    case "report": if (route.reportId === EXAMPLE_REPORT_ID) return <Suspense fallback={<Loading label="예시 리포트를 여는 중…" />}><TutorialScreen key="example" startTour={false} /></Suspense>
      return <Suspense fallback={<Loading label="리포트 화면을 여는 중…" />}><ReportDetail reportId={route.reportId} sec={route.sec} company={route.company} rb={route.rb} /></Suspense>
    case "paper": return <Suspense fallback={<Loading />}><PaperScreen paperId={route.paperId} /></Suspense>
    case "comparison": return <Suspense fallback={<Loading />}><ComparisonScreen comparisonId={route.comparisonId} /></Suspense>
    case "tutorial": return <Suspense fallback={<Loading label="둘러보기를 여는 중…" />}><TutorialScreen key="tutorial" after={guideDestination(route)} /></Suspense>
    case "intro": return null  // App 이 사이드바 없이 따로 그린다
    case "connect": return null  // 〃
    case "settings": return svc.getConnections ? <ConnectionSettings /> : <EmptyState title="페이지를 찾을 수 없습니다" description="이 서버에는 연결 설정 기능이 없습니다." action={<Button onClick={() => navigate({ page: "home" })}>홈으로</Button>} />
    case "not-found": return <EmptyState title="페이지를 찾을 수 없습니다" description={`주소 ${route.path} 에 해당하는 화면이 없습니다.`} action={<Button onClick={() => navigate({ page: "home" })}>홈으로</Button>} />
  }
  if (status === "loading") return null
  return null
}

function ModeBanner({ route }: { route: Route }) {
  const { health, reachable } = useHealth()
  const svc = useService()
  // 연결 설정(제안 기능)이 있으면: 무엇이 다른지 한 문장 + 「연결 설정」 버튼. 연결 설정 화면 자체에는 띄우지 않는다
  if (svc.getConnections) {
    if (!reachable || !practicing(health) || route.page === "settings") return null
    return (  // 알림 상자(Alert)와 같은 모양에 오른쪽 버튼을 둔다
      <div role="status" className={`mb-6 flex items-center gap-3 rounded-box p-4 text-14 leading-6 text-body ${NOTICE_BOX.warning}`}>
        <AlertTriangle className={`mt-0.5 size-5 shrink-0 self-start ${NOTICE_ICON.warning}`} aria-hidden="true" />
        <div className="min-w-0 flex-1">
          <p className="font-semibold text-main">연습 모드로 둘러보는 중입니다.</p>
          <p className="mt-1">예시 데이터와 미리 만든 답을 쓰기 때문에 결과가 입력한 아이디어와 맞지 않습니다.</p>
        </div>
        <Button variant="soft" className="shrink-0" onClick={() => navigate({ page: "settings" })}><span className="font-semibold">연결 설정</span></Button>
      </div>
    )
  }
  if (!reachable || health?.llm_mode !== "stub") return null
  return (
    <Alert tone="warning" className="mb-6" title="연습 모드로 켜져 있습니다.">
      서버가 실제 분석 모델을 부르지 않고 미리 만들어 둔 답을 쓰기 때문에, 아이디어 해석·질문·리포트 문장이 입력과 맞지 않습니다.
      실제로 쓰려면 서버 관리자가 분석 모델 연결 설정으로 서버를 다시 켜야 합니다.
    </Alert>
  )
}

export default function App() {
  const route = useHashRoute()
  const { profile, status } = useProfile()
  const svc = useService()
  const { health, reachable } = useHealth()
  const mockChrome = MockChrome && isMockMode() ? <Suspense fallback={null}><MockChrome /></Suspense> : null
  // 처음 온 사람은 홈 대신 스크롤형 소개부터 (한 번 열면 다시 띄우지 않는다)
  // 주소만 #/intro 로 바꾸고 소개를 바로 그린다. 예전엔 null 을 돌려주고 주소 변경 알림을 기다렸는데, 첫 방문에서 그 알림이 화면이 듣기 전에 와서
  // 새로고침 전까지 빈 화면이었다 (2026-11-20). 두 경우 모두 같은 자리에 IntroScroll 이라 알림이 와도 다시 만들지 않는다
  if (route.page === "home" && !introSeen()) { navigate({ page: "intro" }); return <IntroScroll /> }
  if (route.page === "intro") return <IntroScroll />
  // 연결 흐름(제안 기능)은 소개처럼 사이드바 없이 따로 그린다. 서비스에 기능이 없으면 홈으로
  if (route.page === "connect") {
    if (!svc.getConnections) { navigate({ page: "home" }); return null }
    return <>{mockChrome}<ConnectFlow step={route.step === "llm" ? "llm" : "database"} /></>
  }
  // 프로필이 없으면 처음 설정으로 안내할 화면들 (프로필 화면·리포트 열람·연결 설정은 그대로 둔다)
  const needsProfile = status === "ready" && !profile && !["profile", "reports", "report", "tutorial", "settings", "not-found"].includes(route.page)
  // 연결 흐름(소개 → 연결 → 내 투자조건): 연결 설정 기능이 있고, 연결되지 않은 것이 있고, 이번에 켠 동안 아직 넘기지 않았을 때.
  // 처음 사용자는 투자조건 설정 앞에서, 투자조건이 이미 있는 사람은 홈에 왔을 때 띄운다
  // (키를 지우거나 새 PC 로 옮겨 연결이 사라졌는데 연습 모드 알림만 보이면, 어디서 넣는지 찾아야 한다. 리포트 주소로 바로 들어온 사람은 막지 않는다).
  // 「나중에 하기」로 넘기면 이 창을 닫을 때까지 다시 띄우지 않는다 (features/connect/skip.ts) — 그동안은 연습 모드 알림과 사이드바의 「연결 설정」으로.
  // 다음에 켰을 때도 연결되지 않은 것이 있으면 다시 묻는다. 둘 다 연결돼 있으면 뜰 일이 없다.
  // 연결 여부는 서버 상태(health)로 본다 — 아직 못 읽었으면 잠깐 기다린다 (서버에 닿지 않으면 기다리지 않고 지금까지처럼)
  if (svc.getConnections && !connectSkipped() && (needsProfile || (status === "ready" && !!profile && route.page === "home"))) {
    if (!health && reachable) return null
    if (practicing(health)) { navigate({ page: "connect" }); return null }
  }
  // 대화형 설정(제안 기능)이 있으면 대화로, 없으면 4단계 폼으로.
  if (needsProfile) navigate({ page: "profile", mode: svc.startProfileChat ? "chat" : "setup" })
  return (
    <>
    {mockChrome}
    <div className="flex min-h-screen min-w-[1180px] bg-slate-50">
      <Sidebar route={route} />
      <main className="min-w-0 flex-1 overflow-x-auto">
        {/* 홈·질문 대화(clarify)는 넓게: 오른쪽 「내게 맞는 정보」 패널을 고정 폭으로 두고 남는 폭을 대화창에 (2026-11-18 회의). 나머지 화면은 1180px */}
        <div className={`mx-auto w-full py-9 ${route.page === "home" || route.page === "clarify" ? "max-w-[1600px] px-8" : "max-w-[1180px] px-10"}`}><ModeBanner route={route} /><Screen route={route} /></div>
      </main>
    </div>
    </>
  )
}
