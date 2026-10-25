import { Activity, FileText, Home, SlidersHorizontal, TrendingUp, WifiOff } from "lucide-react"
import { useHealth, useProfile, useService } from "./providers"
import { lazy, Suspense } from "react"
import { navigate, useHashRoute, type Route } from "./router"
import { useResource } from "../state/useResource"
import { Badge, Button, EmptyState, Loading } from "../ui"
import { HomeScreen } from "../features/home/HomeScreen"
import { ProfileScreen } from "../features/profile/ProfileScreen"
import { ClarifyScreen } from "../features/analysis/ClarifyScreen"
import { ConfirmScreen } from "../features/analysis/ConfirmScreen"
import { RunScreen } from "../features/run/RunScreen"
import { ReportList } from "../features/report/ReportList"
import { date } from "../lib/format"


// 차트(recharts)를 쓰는 화면은 따로 묶어 처음 화면이 가볍게 뜨게 한다 (F8 코드 분할).
const ReportDetail = lazy(() => import("../features/report/ReportDetail").then((m) => ({ default: m.ReportDetail })))
const ComparisonScreen = lazy(() => import("../features/report/ComparisonScreen").then((m) => ({ default: m.ComparisonScreen })))
const PaperScreen = lazy(() => import("../features/paper/PaperScreen").then((m) => ({ default: m.PaperScreen })))

function Sidebar({ route }: { route: Route }) {
  const svc = useService()
  const { health, reachable } = useHealth()
  const reports = useResource(() => svc.listReports(), [svc, route.page])
  const items = [
    { label: "홈 · 새 분석", icon: Home, to: { page: "home" } as Route, active: ["home", "clarify", "confirm", "run"].includes(route.page) },
    { label: "분석 리포트", icon: FileText, to: { page: "reports" } as Route, active: ["reports", "report"].includes(route.page) },
    { label: "모의투자", icon: Activity, to: { page: "paper" } as Route, active: route.page === "paper" },
    { label: "내 투자조건", icon: SlidersHorizontal, to: { page: "profile" } as Route, active: route.page === "profile" },
  ]
  return (
    <aside className="sticky top-0 flex h-screen w-60 shrink-0 flex-col border-r border-slate-200 bg-white px-4 py-6">
      <button onClick={() => navigate({ page: "home" })} className="flex items-center gap-3 rounded-xl px-2 text-left focus:outline-none focus:ring-2 focus:ring-blue-500">
        <span className="flex size-9 items-center justify-center rounded-xl bg-blue-700 text-white"><TrendingUp className="size-5" /></span>
        <span><span className="block text-base font-extrabold tracking-tight text-slate-950">MyFinSight</span><span className="block text-[10px] font-medium text-slate-400">개인화 투자전략</span></span>
      </button>
      <nav className="mt-8 space-y-1" aria-label="주 메뉴">
        {items.map((item) => (
          <button key={item.label} onClick={() => navigate(item.to)} className={`flex w-full items-center justify-between rounded-xl px-3 py-2.5 text-sm font-semibold transition focus:outline-none focus:ring-2 focus:ring-blue-500 ${item.active ? "bg-blue-50 text-blue-700" : "text-slate-600 hover:bg-slate-50 hover:text-slate-900"}`}>
            <span className="flex items-center gap-3"><item.icon className="size-4" />{item.label}</span>
          </button>
        ))}
      </nav>
      <div className="mt-5 border-t border-slate-100 pt-5">
        <p className="px-3 text-[11px] font-bold tracking-wider text-slate-400">최근 리포트</p>
        <div className="mt-2 space-y-1">
          {(reports.data ?? []).slice(0, 5).map((r) => (
            <button key={r.run_id} onClick={() => navigate({ page: "report", reportId: r.report_id ?? r.run_id })} className={`w-full rounded-lg px-3 py-2 text-left transition hover:bg-slate-50 focus:outline-none focus:ring-2 focus:ring-blue-500 ${route.page === "report" && route.reportId === (r.report_id ?? r.run_id) ? "bg-blue-50" : ""}`}>
              <span className="block truncate text-xs font-semibold text-slate-700">{r.strategy_name || r.idea || r.run_id}</span>
              <span className="mt-0.5 block text-[10px] text-slate-400">{date(r.created_at)} · 기준일 {r.as_of}</span>
            </button>
          ))}
          {reports.status === "ready" && (reports.data ?? []).length === 0 && <p className="px-3 text-xs text-slate-400">아직 리포트가 없습니다.</p>}
        </div>
      </div>
      <div className="mt-auto space-y-2 px-1 text-[11px] leading-5 text-slate-500">
        {!reachable && <Badge tone="red"><WifiOff className="size-3" />서버 연결 끊김</Badge>}
        {health?.llm_mode === "stub" && <Badge tone="amber">연습 모드 (LLM 없음)</Badge>}
        {health && reachable && !health.worker.alive && <Badge tone="red">분석 일꾼 꺼짐 — 새 분석이 시작되지 않습니다</Badge>}
        {health && reachable && (
          <p>
            자료 기준일 {health.db.latest_trading_day ?? "–"}
            <br />분석 일꾼 {health.worker.alive ? "실행 중" : "꺼짐"} · 대기 {health.queue_length}건 · {health.llm_mode === "api" ? "분석 모델 연결됨" : "연습 모드"}
          </p>
        )}
      </div>
    </aside>
  )
}

function Screen({ route }: { route: Route }) {
  const { profile, status } = useProfile()
  switch (route.page) {
    case "home": return <HomeScreen />
    case "profile": return <ProfileScreen mode={route.mode ?? (profile ? "view" : "setup")} />
    case "clarify": return <ClarifyScreen requestId={route.requestId} />
    case "confirm": return <ConfirmScreen requestId={route.requestId} />
    case "run": return <RunScreen runId={route.runId} />
    case "reports": return <ReportList />
    case "report": return <Suspense fallback={<Loading label="리포트 화면을 여는 중…" />}><ReportDetail reportId={route.reportId} sec={route.sec} company={route.company} rb={route.rb} /></Suspense>
    case "paper": return <Suspense fallback={<Loading />}><PaperScreen paperId={route.paperId} /></Suspense>
    case "comparison": return <Suspense fallback={<Loading />}><ComparisonScreen comparisonId={route.comparisonId} /></Suspense>
    case "not-found": return <EmptyState title="페이지를 찾을 수 없습니다" description={`주소 ${route.path} 에 해당하는 화면이 없습니다.`} action={<Button onClick={() => navigate({ page: "home" })}>홈으로</Button>} />
  }
  if (status === "loading") return null
  return null
}

function ModeBanner() {
  const { health, reachable } = useHealth()
  if (!reachable || health?.llm_mode !== "stub") return null
  return (
    <div className="mb-6 rounded-xl border border-amber-300 bg-amber-50 px-4 py-3 text-sm text-amber-950">
      <b>연습 모드로 켜져 있습니다.</b> 서버가 실제 분석 모델을 부르지 않고 미리 만들어 둔 답을 쓰기 때문에, 아이디어 해석·질문·리포트 문장이 입력과 맞지 않습니다.
      실제로 쓰려면 서버 관리자가 분석 모델 연결 설정으로 서버를 다시 켜야 합니다.
    </div>
  )
}

export default function App() {
  const route = useHashRoute()
  const { profile, status } = useProfile()
  // 프로필이 없으면 처음 설정으로 안내 (프로필 화면·리포트 열람은 허용)
  if (status === "ready" && !profile && !["profile", "reports", "report", "not-found"].includes(route.page)) {
    navigate({ page: "profile", mode: "setup" })
  }
  return (
    <div className="flex min-h-screen min-w-[1180px] bg-slate-50">
      <Sidebar route={route} />
      <main className="min-w-0 flex-1 overflow-x-auto">
        <div className="mx-auto w-full max-w-[1180px] px-10 py-9"><ModeBanner /><Screen route={route} /></div>
      </main>
    </div>
  )
}
