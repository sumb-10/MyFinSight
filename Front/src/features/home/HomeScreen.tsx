import { useEffect, useState } from "react"
import { ChevronRight, Compass, FileText, Info, Loader2, SlidersHorizontal, Sparkles, X } from "lucide-react"
import { useProfile, useService } from "../../app/providers"
import { navigate } from "../../app/router"
import { errorMessage } from "../../api/client"
import { useResource } from "../../state/useResource"
import { loadUi, saveUi } from "../../state/uiStorage"
import { Button, EmptyState, ErrorState, Loading } from "../../ui"
import { DetailConditionsDialog, OVERRIDE_LABELS, overrideText, type Overrides } from "./DetailConditions"
import { ActionError, IdeaPending } from "../analysis/flow"
import { ContinueCard } from "./ContinueCard"
import { useRenameTick } from "../report/ReportName"
import { Coachmark } from "../tutorial/Coachmark"
import { HOME_TOUR_STEPS } from "../tutorial/homeSteps"
import { clearHomeTourFlag, hasHomeTourFlag } from "../tutorial/IntroScroll"
import { HomeInfo, TOUR_TAB, type InfoTab } from "./HomeInfo"
import { HelpMenu } from "./HelpMenu"
import { RequestChat, useRequestDialog } from "./RequestChat"
import { FlowStepper } from "../analysis/FlowStepper"
import type { DialogState } from "../../api/types"
import type { Resource } from "../../state/useResource"
import { SplashScreen } from "./SplashScreen"
import { scopeOf, useSectorTrends } from "./sectorTrends"
import iconIdea from "./tossface/u1F4AC.svg"  // 토스페이스 원본 (tossface/LICENSE.txt)
import "./home.css"

/** 입력 카드 가운데 예시 문장. 누르면 그 문장을 넣고 「분석 시작하기」를 누른 것과 같다 (질문·조건 확인을 거쳐 분석 실행). */
export const EXAMPLE_IDEAS = [
  "미국 반도체 기업 중 실적이 좋은 곳에 나눠 투자하고 싶어요.",
  "배당을 꾸준히 주는 한국 대형주로 모으고 싶어요.",
  "넷플릭스·디즈니 같은 기업에 3년 투자하고 싶어요.",
]

const HEAD_BTN = "inline-flex h-8 items-center gap-1.5 rounded-chip px-2.5 text-13 font-medium text-sub transition hover:bg-sunken hover:text-main"

/**
 * 홈 (시안 3 「분할 화면」, 2026-11-17 이식): 왼쪽 카드는 아이디어를 적는 곳, 오른쪽 카드는 「내게 맞는 정보」 탭. 맨 위는 분석 진행 단계(1·2).
 * request 가 있으면(새 분석 요청 #/analysis/:id, ClarifyRoute) 왼쪽 카드가 분석 모델과의 대화창(RequestChat)이 되고, 오른쪽 첫 탭이 「이번 요청 조건」.
 * 진행 중이던 분석 · 취소한 분석은 두 카드 위 「이어서 할 일」 카드에 한 줄씩, 그만둔 요청 안내는 입력창 바로 위에 둔다.
 */
export function HomeScreen({ request }: { request?: { id: string; res: Resource<DialogState> } } = {}) {
  const svc = useService()
  const { st: reqSt, setSt: setReqSt } = useRequestDialog(request?.id, request?.res)  // 새 분석 요청 중 (#/analysis/:id) 이면 그 요청
  const { profile, status, error: profileError, reload } = useProfile()
  const trends = useSectorTrends(svc)  // 처음(이 브라우저에 저장한 자료가 없을 때)만 시작 화면
  const [idea, setIdea] = useState(() => { const u = loadUi(); return u.prefillIdea ?? u.draftIdea ?? "" })
  const [error, setError] = useState("")      // 입력 확인 (5자 미만 등)
  const [apiErr, setApiErr] = useState("")    // 서버가 요청을 만들지 못함 → 다시 시도
  const [busy, setBusy] = useState(false)
  // 상세 조건도 아이디어처럼 초안으로 남긴다. 새 요청으로 채워 온 값(prefill)이 있으면 그것이 먼저
  const [overrides, setOverrides] = useState<Overrides>(() => { const u = loadUi(); return (u.prefillOverrides ?? u.draftOverrides ?? {}) as Overrides })
  const [leftNote, setLeftNote] = useState(() => loadUi().prefillNote ?? "")  // 요청을 그만두고 돌아왔을 때: 왜 채워져 있는지
  const [detail, setDetail] = useState(false)
  const [tour, setTour] = useState<number | null>(() => (hasHomeTourFlag() ? 0 : null))  // 홈 둘러보기 단계 (소개에서 「화면 둘러보기」를 고르면 바로 시작)
  useEffect(() => { clearHomeTourFlag() }, [])
  const [tab, setTab] = useState<InfoTab | null>(null)   // 오른쪽 카드에서 연 탭 (null = 리포트 수를 보고 아직 정하는 중)
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
  // 첫 탭: 리포트 목록을 받은 뒤 한 번만 정한다. 리포트가 없는 사람(처음 쓰는 사람)은 「이렇게 진행돼요」, 있으면 「요즘 강한 섹터」
  useEffect(() => {
    if (tab !== null) return
    if (request) { setTab("request"); return }  // 요청 중이면 「이번 요청 조건」
    if (reports.status === "loading" || reports.status === "idle") return
    setTab(reports.status === "ready" && (reports.data ?? []).length === 0 ? "process" : trends.supported ? "trends" : "profile")
  }, [tab, request, reports.status, reports.data, trends.supported])
  // 둘러보기가 탭 안의 요소를 가리키면 그 탭을 연다 (말풍선이 대상을 찾을 때까지 잠깐 기다린다)
  useEffect(() => {
    if (tour === null) return
    const t = TOUR_TAB[HOME_TOUR_STEPS[tour].target]
    if (t && (t !== "trends" || trends.supported)) setTab(t)
  }, [tour, trends.supported])

  // 시작 화면은 어느 경우든 같은 자리(조각의 첫 자식)에 둔다 → 프로필을 다 불러와도 새로 그려지지 않고 로딩바가 이어진다
  const splash = trends.splash ? <SplashScreen progress={trends.progress} /> : null
  if (status === "loading") return <>{splash}<Loading /></>
  if (status === "error") return <>{splash}<ErrorState title="분석 서버에 연결할 수 없습니다" message={profileError ?? ""} retry={() => void reload()} /></>
  if (!profile) return <>{splash}<EmptyState title="먼저 내 투자조건을 설정해주세요." description="분석에 사용할 금액, 기간, 투자성향과 제약을 저장합니다." action={<Button onClick={() => navigate({ page: "profile", mode: svc.startProfileChat ? "chat" : "setup" })}>투자조건 설정 시작</Button>} /></>
  const p = profile.profile
  const scope = scopeOf(p.constraints.universe)
  const tendency = p.diagnosis?.final_tendency ?? null
  const pick = tendency ? trends.data?.picks[scope]?.[tendency] ?? null : null
  const nOverrides = Object.keys(overrides).length

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

  const activeRun = ui.activeRunId && !resumes.some((r) => r.run_id === ui.activeRunId) ? ui.activeRunId : null
  return (
    <>{splash}<div className="home-redesign grid min-h-[calc(100vh-4.5rem)] grid-cols-[minmax(0,1.3fr)_minmax(420px,1fr)] gap-4 text-body">
      {/* 왼쪽: 단계 표시 · 이어서 할 일 · 새 분석(대화창) — 남는 폭을 모두 쓴다. 오른쪽: 「내게 맞는 정보」 — 대화창 : 패널 = 1.3 : 1 (패널은 최소 420px, 2026-11-18 비율 후보 중 B), 위에서부터 끝까지 */}
      <div className="flex min-w-0 flex-col gap-4">
      <FlowStepper current={request ? 2 : 1} />
      {!request && <ContinueCard runs={resumes} onDismiss={dismissResume} activeRequestId={ui.activeRequestId ?? null} activeRunId={activeRun}
        onClearActive={() => setUi(saveUi({ activeRequestId: null, activeRunId: null }))} />}

        {request ?<RequestChat requestId={request.id} st={reqSt} setSt={setReqSt} res={request.res} /> : <section aria-labelledby="home-new" className="flex min-w-0 flex-1 flex-col rounded-card bg-surface">
          <div className="flex items-center justify-between border-b border-line px-6 py-3.5">
            <h1 id="home-new" className="t-title">새 분석</h1>
            {/* 도움 셋을 버튼 하나로 (2026-11-18 사용자 결정: 나란히 두면 소개와 둘러보기의 차이가 안 보임).
                「서비스 소개」는 스크롤형 소개 화면(#/intro, IntroScroll) */}
            <HelpMenu className={HEAD_BTN} items={[
              { icon: Sparkles, label: "서비스 소개", onClick: () => navigate({ page: "intro" }) },
              { icon: Compass, label: "홈 화면 둘러보기", onClick: () => setTour(0) },
              { icon: FileText, label: "예시 리포트 둘러보기", onClick: () => navigate({ page: "tutorial" }) },
            ]} />
          </div>
          <div className="flex flex-1 flex-col items-center justify-center px-8 py-4 text-center">
            <span className="grid size-14 place-items-center rounded-box bg-sunken"><img src={iconIdea} alt="" className="size-8" /></span>
            <h2 className="mt-4 t-heading">투자 아이디어를 적어 주세요</h2>
            <p className="mt-2 max-w-[360px] text-balance t-body">내 투자조건에 맞는 종목과 비중을 고르고, 과거 성과와 위험을 리포트로 보여드립니다.</p>
            <ul data-tour="home-examples" aria-label="예시 문장" className="mt-5 flex flex-col items-center gap-2">
              {EXAMPLE_IDEAS.map((t) => (
                <li key={t}><button type="button" disabled={busy} onClick={() => void submit(t)} className="rounded-control bg-sunken px-4 py-2.5 text-14 text-main transition hover:bg-sunken-hover disabled:cursor-not-allowed disabled:opacity-50">{t}</button></li>
              ))}
            </ul>
          </div>
          <div className="mx-auto w-full max-w-[760px] p-4">
            {/* 기다리는 동안: 무엇을 하는지·경과 시간 (서버가 LLM 으로 해석하는 데 수 초~1분) */}
            {busy && <div className="pb-3"><IdeaPending /></div>}
            {apiErr && !busy && <div className="pb-3"><ActionError title="아이디어를 해석하지 못했습니다" message={apiErr} retry={() => void submit()} /></div>}
            {/* 요청을 그만두고 돌아왔을 때: 입력창이 왜 채워져 있는지 입력창 바로 위에 */}
            {leftNote && (
              <div role="status" className="mb-2 flex items-start gap-2 rounded-box bg-tint px-4 py-3 text-left">
                <Info className="mt-0.5 size-4 shrink-0 text-accent" aria-hidden />
                <p className="min-w-0 flex-1 text-13 text-body"><b className="font-semibold text-main">그만둔 요청을 홈에 채워 두었습니다</b><br />{leftNote}</p>
                <button type="button" aria-label="안내 닫기" onClick={() => setLeftNote("")} className="-m-1 rounded-chip p-1 text-sub hover:bg-surface hover:text-main"><X className="size-4" aria-hidden /></button>
              </div>
            )}
            <div data-tour="home-idea" className="rounded-box bg-sunken p-3 transition-shadow focus-within:shadow-[0_0_0_2px_var(--color-focus)]">
              <textarea value={idea} readOnly={busy} aria-busy={busy} aria-label="투자하고 싶은 내용" rows={2} onChange={(e) => { setIdea(e.target.value); setError("") }}
                className="w-full resize-none border-0 bg-transparent px-1 text-15 leading-6 text-main outline-none placeholder:text-hint" placeholder="예: 미국과 한국의 반도체 기업에 나눠 투자하고 싶어요." />
              {nOverrides > 0 && (
                <div className="flex flex-wrap items-center gap-1.5 pt-1">
                  <span className="text-12 font-semibold text-sub">이번 분석에만 적용:</span>
                  {Object.entries(overrides).map(([k, v]) => <span key={k} className="rounded-full bg-surface px-2.5 py-1 text-12 font-semibold text-accent">{OVERRIDE_LABELS[k] ?? k} {overrideText(k, v)}</span>)}
                  <button type="button" className="text-12 text-sub hover:text-main disabled:opacity-40" disabled={busy} onClick={() => setOverrides({})}><X className="inline size-3" aria-hidden /> 모두 지우기</button>
                </div>
              )}
              <div className="mt-2 flex items-center justify-between gap-2">
                <span data-tour="home-detail" className="inline-flex"><button type="button" onClick={() => setDetail(true)} disabled={busy} className="inline-flex h-10 items-center gap-1.5 rounded-control px-3 text-14 font-semibold text-main transition hover:bg-surface disabled:opacity-50"><SlidersHorizontal className="size-4" aria-hidden />상세 조건{nOverrides ? ` (${nOverrides})` : ""}</button></span>
                <span data-tour="home-submit" className="inline-flex"><button type="button" onClick={() => void submit()} disabled={busy} className="inline-flex h-10 items-center gap-1.5 rounded-control bg-accent px-4 text-14 font-semibold text-on-accent transition enabled:hover:bg-accent-hover disabled:cursor-not-allowed disabled:opacity-60">{busy ? <><Loader2 className="size-4 animate-spin" aria-hidden />아이디어 해석 중…</> : <>분석 시작하기<ChevronRight className="size-4" aria-hidden /></>}</button></span>
              </div>
            </div>
            {error && <p className="pt-2 text-12 font-medium text-danger">{error}</p>}
          </div>
        </section>}
      </div>

        <HomeInfo tab={tab} setTab={setTab} trends={trends} market={scope === "KR" ? "KR" : "US"} busy={busy || !!request} onPrompt={(t) => void submit(t)} profile={profile} pick={pick} reports={reports} request={request ? reqSt : undefined} />

      {detail && <DetailConditionsDialog profile={profile.profile} initial={overrides} onApply={setOverrides} close={() => setDetail(false)} />}
      {tour !== null && (
        <Coachmark steps={HOME_TOUR_STEPS} index={tour} onClose={() => setTour(null)}
          onPrev={() => setTour((i) => Math.max(0, (i ?? 0) - 1))} onNext={() => setTour((i) => (i === null || i >= HOME_TOUR_STEPS.length - 1 ? null : i + 1))} />
      )}
    </div></>
  )
}
