import { Fragment, useEffect, useState } from "react"
import { ChevronRight, Compass, FileText, Loader2, SlidersHorizontal, X } from "lucide-react"
import { useProfile, useService } from "../../app/providers"
import { navigate } from "../../app/router"
import { errorMessage } from "../../api/client"
import type { ProfileView } from "../../api/types"
import { useResource } from "../../state/useResource"
import { loadUi, saveUi } from "../../state/uiStorage"
import { Alert, Badge, Button, Card, EmptyState, ErrorState, Loading } from "../../ui"
import { date, ko } from "../../lib/format"
import { DetailConditionsDialog, OVERRIDE_LABELS, overrideText, type Overrides } from "./DetailConditions"
import { ActionError, IdeaPending } from "../analysis/flow"
import { ResumeCard } from "./ResumeCard"
import { tendencyLabel } from "../../lib/tendency"
import { money, pctText } from "../profile/format"  // 내 투자조건 화면과 같은 표기 (1,000만원 · 10%)
import { reportName } from "../../lib/reportName"
import { proposedNameOf, type ProposedSectorPick } from "../../api/proposed"
import { MockTag } from "../report/proposedView"
import { useRenameTick } from "../report/ReportName"
import { Coachmark } from "../tutorial/Coachmark"
import { HOME_TOUR_STEPS } from "../tutorial/homeSteps"
import { SectorTrendsBox } from "./SectorTrendsBox"
import { SplashScreen } from "./SplashScreen"
import { scopeOf, useSectorTrends } from "./sectorTrends"

/** 입력창 아래 예시 문장. 누르면 그 문장을 넣고 투자조건 확인하기를 누른 것과 같다 (질문·조건 확인을 거쳐 분석 시작). */
export const EXAMPLE_IDEAS = [
  "미국 반도체 기업 중 실적이 좋은 곳에 나눠 투자하고 싶어요.",
  "배당을 꾸준히 주는 한국 대형주로 모으고 싶어요.",
  "넷플릭스·디즈니 같은 기업에 3년 투자하고 싶어요.",
]

export function HomeScreen() {
  const svc = useService()
  const { profile, status, error: profileError, reload } = useProfile()
  const trends = useSectorTrends(svc)  // 처음(이 브라우저에 저장한 자료가 없을 때)만 시작 화면
  const [idea, setIdea] = useState(() => { const u = loadUi(); return u.prefillIdea ?? u.draftIdea ?? "" })
  const [error, setError] = useState("")      // 입력 확인 (5자 미만 등)
  const [apiErr, setApiErr] = useState("")    // 서버가 요청을 만들지 못함 → 다시 시도
  const [busy, setBusy] = useState(false)
  // 상세 조건도 아이디어처럼 초안으로 남긴다 (전에는 다른 메뉴에 다녀오면 사라졌다). 새 요청으로 채워 온 값(prefill)이 있으면 그것이 먼저
  const [overrides, setOverrides] = useState<Overrides>(() => { const u = loadUi(); return (u.prefillOverrides ?? u.draftOverrides ?? {}) as Overrides })
  const [leftNote, setLeftNote] = useState(() => loadUi().prefillNote ?? "")  // 요청을 그만두고 돌아왔을 때: 왜 채워져 있는지
  const [detail, setDetail] = useState(false)
  const [tour, setTour] = useState<number | null>(null)  // 홈 둘러보기 단계
  const renamed = useRenameTick()
  const reports = useResource(() => svc.listReports(), [svc, renamed])
  const [ui, setUi] = useState(() => loadUi())
  // 취소한 분석 (이어서 실행 가능): 서버 실행 목록 기준이라 다른 브라우저에서도 보인다. 「지우기」 한 것은 이 브라우저에서만 숨김
  const runs = useResource(() => svc.listRuns(), [svc]).data
  const resumes = (runs ?? []).filter((r) => r.resumable && !(ui.dismissedResumeIds ?? []).includes(r.run_id))
  const dismissResume = (runId: string) => setUi(saveUi({ dismissedResumeIds: [...(ui.dismissedResumeIds ?? []), runId], ...(ui.activeRunId === runId ? { activeRunId: null } : {}) }))
  useEffect(() => { saveUi({ draftIdea: idea }) }, [idea])
  useEffect(() => { saveUi({ draftOverrides: overrides }) }, [overrides])
  useEffect(() => { const u = loadUi(); if (u.prefillIdea || u.prefillOverrides || u.prefillNote) setUi(saveUi({ prefillIdea: null, prefillOverrides: null, prefillNote: null })) }, [])  // 미리 채운 값(새 요청)은 한 번만 쓴다

  // 시작 화면은 어느 경우든 같은 자리(조각의 첫 자식)에 둔다 → 프로필을 다 불러와도 새로 그려지지 않고 로딩바가 이어진다
  const splash = trends.splash ? <SplashScreen progress={trends.progress} /> : null
  if (status === "loading") return <>{splash}<Loading /></>
  if (status === "error") return <>{splash}<ErrorState title="분석 서버에 연결할 수 없습니다" message={profileError ?? ""} retry={() => void reload()} /></>
  if (!profile) return <>{splash}<EmptyState title="먼저 내 투자조건을 설정해주세요." description="분석에 사용할 금액, 기간, 투자성향과 제약을 저장합니다." action={<Button onClick={() => navigate({ page: "profile", mode: svc.startProfileChat ? "chat" : "setup" })}>투자조건 설정 시작</Button>} /></>
  const p = profile.profile
  const scope = scopeOf(p.constraints.universe)
  const tendency = p.diagnosis?.final_tendency ?? null
  const pick = tendency ? trends.data?.picks[scope]?.[tendency] ?? null : null

  /** text 를 주면(예시·추천 문장) 그 문장을 입력창에 넣고 바로 확인하기를 누른 것과 같다 */
  const submit = async (text: string = idea) => {
    const t = text.trim()
    if (t.length < 5) { setError("분석할 투자 아이디어를 5자 이상 입력해주세요."); return }
    setIdea(text); setBusy(true); setError(""); setApiErr("")
    try {
      const st = await svc.createRequest({ idea: t, mode: "new", overrides })
      saveUi({ draftIdea: "", draftOverrides: {}, activeRequestId: st.request_id })
      setIdea(""); setOverrides({}); setLeftNote("")
      navigate({ page: "clarify", requestId: st.request_id })
    } catch (e) { setApiErr(errorMessage(e)) } finally { setBusy(false) }
  }

  return (
    <>{splash}<div className="space-y-8">
      <div className="mx-auto max-w-4xl pt-10 text-center">
        <Badge>개인화 투자전략</Badge>
        <h1 className="mt-5 text-4xl font-extrabold tracking-tight text-slate-950">투자 아이디어를 포트폴리오로 확인해보세요.</h1>
        <p className="mt-3 text-base text-slate-600">내 투자조건을 반영해 종목을 고르고, 과거 데이터로 성과와 위험을 검증합니다. 투자하고 싶은 내용을 아래 채팅창에 입력하세요.</p>
        <div className="mt-4 flex justify-center gap-2">
          <Button variant="secondary" onClick={() => setTour(0)}><Compass className="size-4" />처음이신가요? MyFinSight 둘러보기</Button>
          <Button variant="secondary" onClick={() => navigate({ page: "tutorial" })}><FileText className="size-4" />리포트 보는 법 둘러보기</Button>
        </div>
      </div>
      {leftNote && <Alert tone="info" title="그만둔 요청을 홈에 채워 두었습니다">{leftNote}</Alert>}
      <div className={`grid gap-5 ${trends.supported ? "grid-cols-[300px_minmax(0,1fr)]" : "grid-cols-1"}`}>
        {trends.supported && <div className="min-h-[300px]"><SectorTrendsBox trends={trends} defaultMarket={scope === "KR" ? "KR" : "US"} busy={busy} onPrompt={(t) => void submit(t)} /></div>}
        <div data-tour="home-idea" className="flex min-h-[300px] flex-col rounded-2xl border border-slate-200 bg-white p-3 text-left shadow-sm">
          <textarea value={idea} readOnly={busy} aria-busy={busy} aria-label="투자하고 싶은 내용" onChange={(e) => { setIdea(e.target.value); setError("") }} className="min-h-36 w-full flex-1 resize-none rounded-xl border-0 p-3 text-base leading-7 outline-none placeholder:text-slate-400" placeholder="예: 미국과 한국의 반도체·메모리 기업에 분산 투자하고 싶어요. 특정 종목에 너무 집중하고 싶지는 않습니다." />
          {Object.keys(overrides).length > 0 && (
            <div className="flex flex-wrap items-center gap-2 px-2 pb-3">
              <span className="text-xs font-semibold text-slate-500">이번 분석에만 적용:</span>
              {Object.entries(overrides).map(([k, v]) => <Badge key={k} tone="blue">{OVERRIDE_LABELS[k] ?? k} {overrideText(k, v)}</Badge>)}
              <button className="text-xs text-slate-400 hover:text-slate-700 disabled:opacity-40" disabled={busy} onClick={() => setOverrides({})}><X className="inline size-3" /> 모두 지우기</button>
            </div>
          )}
          {/* 기다리는 동안: 무엇을 하는지·경과 시간 (서버가 LLM 으로 해석하는 데 수 초~1분) */}
          {busy && <div className="px-2 pb-3"><IdeaPending /></div>}
          <div className="flex items-end justify-between gap-4 border-t border-slate-100 px-2 pt-3">
            <ul data-tour="home-examples" aria-label="예시 문장" className="min-w-0 space-y-1">
              {EXAMPLE_IDEAS.map((t) => (
                <li key={t}><button type="button" disabled={busy} onClick={() => void submit(t)} className="rounded-md text-left text-sm text-slate-500 transition hover:text-blue-700 focus:outline-none focus:ring-2 focus:ring-blue-500 disabled:cursor-not-allowed disabled:opacity-50">* {t}</button></li>
              ))}
            </ul>
            <div className="flex shrink-0 gap-2">
              <span data-tour="home-detail" className="inline-flex"><Button variant="secondary" onClick={() => setDetail(true)} disabled={busy}><SlidersHorizontal className="size-4" />상세 조건{Object.keys(overrides).length ? ` (${Object.keys(overrides).length})` : ""}</Button></span>
              <span data-tour="home-submit" className="inline-flex"><Button onClick={() => void submit()} disabled={busy}>{busy ? <><Loader2 className="size-4 animate-spin" aria-hidden />아이디어 해석 중…</> : <>투자조건 확인하기<ChevronRight className="size-4" /></>}</Button></span>
            </div>
          </div>
          {error && <p className="px-2 pt-2 text-xs font-medium text-red-600">{error}</p>}
          {apiErr && !busy && <div className="px-2 pt-3"><ActionError title="아이디어를 해석하지 못했습니다" message={apiErr} retry={() => void submit()} /></div>}
        </div>
      </div>
      {detail && <DetailConditionsDialog profile={profile.profile} initial={overrides} onApply={setOverrides} close={() => setDetail(false)} />}
      <ResumeCard runs={resumes} onDismiss={dismissResume} />
      {(ui.activeRequestId || (ui.activeRunId && !resumes.some((r) => r.run_id === ui.activeRunId))) && (
        <Alert title="진행 중이던 분석이 있습니다" tone="info">
          <div className="flex gap-2">
            {ui.activeRequestId && <Button variant="secondary" onClick={() => navigate({ page: "clarify", requestId: ui.activeRequestId! })}>조건 확인 이어서</Button>}
            {ui.activeRunId && !resumes.some((r) => r.run_id === ui.activeRunId) && <Button variant="secondary" onClick={() => navigate({ page: "run", runId: ui.activeRunId! })}>실행 상태 보기</Button>}
            <Button variant="ghost" onClick={() => setUi(saveUi({ activeRequestId: null, activeRunId: null }))}>지우기</Button>
          </div>
        </Alert>
      )}
      <div className="grid grid-cols-2 gap-5">
        <div data-tour="home-profile"><ProfileCard profile={profile} pick={pick} /></div>
        <div data-tour="home-reports">
          <Card className="h-full p-6">
            <div className="flex justify-between"><h2 className="font-bold text-slate-900">최근 분석 리포트</h2><button onClick={() => navigate({ page: "reports" })} className="text-xs font-semibold text-blue-700">전체 보기</button></div>
            <div className="mt-3 space-y-1">
              {reports.status === "error" && <p className="text-xs text-red-600">{reports.error}</p>}
              {(reports.data ?? []).slice(0, 4).map((r) => (
                <button key={r.run_id} onClick={() => navigate({ page: "report", reportId: r.report_id ?? r.run_id })} className="flex w-full items-center justify-between rounded-xl p-3 text-left hover:bg-slate-50">
                  <span className="min-w-0"><span className="block truncate text-sm font-semibold text-slate-800">{reportName(r)}{proposedNameOf(r) && <MockTag />}</span><span className="mt-0.5 block text-xs text-slate-400">{date(r.created_at)} · 기준일 {r.as_of}</span></span>
                  <ChevronRight className="size-4 shrink-0 text-slate-300" />
                </button>
              ))}
              {reports.status === "ready" && (reports.data ?? []).length === 0 && <p className="p-3 text-sm text-slate-500">아직 완료된 분석이 없습니다.</p>}
            </div>
          </Card>
        </div>
      </div>
      {tour !== null && (
        <Coachmark steps={HOME_TOUR_STEPS} index={tour} onClose={() => setTour(null)}
          onPrev={() => setTour((i) => Math.max(0, (i ?? 0) - 1))} onNext={() => setTour((i) => (i === null || i >= HOME_TOUR_STEPS.length - 1 ? null : i + 1))} />
      )}
    </div></>
  )
}

/** 저장된 기본 투자조건: 항목 이름 · 값 한 줄씩. 맨 아래에 투자성향에 맞춘 섹터 (섹터 자료가 있을 때). */
function ProfileCard({ profile, pick }: { profile: ProfileView; pick: ProposedSectorPick | null }) {
  const p = profile.profile
  const c = p.capital
  const monthly = c.monthly_contribution > 0 ? `매달 ${money(c.monthly_contribution, c.currency)}` : ""
  const amount = c.initial_amount > 0 ? [money(c.initial_amount, c.currency), monthly].filter(Boolean).join(" · ") : monthly || money(0, c.currency)
  const rows: [string, string][] = [
    ["금액", amount],
    ["기간", `${p.horizon.target_years}년`],
    ["성향", `${tendencyLabel({ final: p.diagnosis?.final_tendency, code: p.risk.risk_tolerance })} · 손실 감내 ${pctText(p.risk.max_drawdown_tolerance)}`],
    ["투자 대상", p.constraints.universe.map(ko).join(" · ")],
    ["종목 고르기", `${ko(p.strategy_preference.template)} · ${ko(p.strategy_preference.baseline_weighting)} · 종목당 최대 ${pctText(p.constraints.max_weight_per_stock)}`],
  ]
  const tickers = p.constraints.must_include_tickers.length + p.constraints.exclude_tickers.length > 0
  return (
    <Card className="flex h-full flex-col p-6">
      <div className="flex items-start justify-between">
        <h2 className="font-bold text-slate-900">저장된 기본 투자조건</h2>
        <button onClick={() => navigate({ page: "profile" })} className="text-xs font-semibold text-blue-700">내 투자조건 보기</button>
      </div>
      <dl className="mt-4 grid grid-cols-[80px_minmax(0,1fr)] gap-x-3 gap-y-2.5 text-sm">
        {rows.map(([k, v]) => <Fragment key={k}><dt className="text-slate-500">{k}</dt><dd className="font-semibold text-slate-900">{v}</dd></Fragment>)}
      </dl>
      {tickers && (
        <div className="mt-3 flex flex-wrap gap-2">
          {p.constraints.must_include_tickers.map((t) => <Badge key={`in-${t}`} tone="blue">{t} 필수 포함</Badge>)}
          {p.constraints.exclude_tickers.map((t) => <Badge key={t} tone="red">{t} 제외</Badge>)}
        </div>
      )}
      {pick && <div className="mt-auto pt-4"><p data-testid="tendency-sector" className="border-t border-slate-100 pt-4 text-sm leading-6 text-slate-700">{pick.text_ko}</p></div>}
    </Card>
  )
}
