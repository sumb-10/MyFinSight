import { useEffect, useMemo, useRef, useState } from "react"
import { AlertCircle, AlertTriangle, Check, ChevronDown, Circle, Loader2, X } from "lucide-react"
import { useHealth, useService } from "../../app/providers"
import { navigate } from "../../app/router"
import { errorMessage } from "../../api/client"
import type { RunPartial, RunStatus, RunStep, StepStatus } from "../../api/types"
import { usePolling } from "../../state/usePolling"
import { useResource } from "../../state/useResource"
import { saveUi } from "../../state/uiStorage"
import { Alert, Button, EmptyState, Loading } from "../../ui"
import { datetime, fmt } from "../../lib/format"
import { startNewWith } from "../analysis/ClarifyScreen"
import { ActionError, FlowHeader, Pending } from "../analysis/flow"
import { Part } from "../profile/parts"
import { BUCKET_TEXT, STEP_TEXT, collectNotes, notesFromWarnings, splitSummary, stepTitle, type RunNotes } from "./steps"
import { proposedCancelOf } from "../../api/proposed"
import { MockTag } from "../report/proposedView"
import { useGuideGate } from "../tutorial/GuidePrompt"

const TERMINAL = new Set(["success", "partial", "failed", "cancelled"])
/** 상태가 앞으로만 간다: 취소 응답(cancelling)을 받은 뒤 폴링이 끝난 상태(cancelled 등)를 주면 그것을 쓴다. */
const STAGE_RANK: Record<RunStatus["status"], number> = { queued: 0, running: 1, cancelling: 2, success: 3, partial: 3, failed: 3, cancelled: 3 }

const elapsed = (from: string | null | undefined, now: number) => {
  if (!from) return null
  const s = Math.max(0, Math.round((now - new Date(from).getTime()) / 1000))
  return s < 60 ? `${s}초` : `${Math.floor(s / 60)}분 ${s % 60}초`
}

/** 선정 지표 ID (backend/analysis/m2_data/metrics.py) 의 화면 이름. 모르는 ID 는 표시하지 않는다. */
const METRIC_KO: Record<string, string> = { return_12m_1m: "최근 12개월 수익률", vol_60d: "60거래일 변동성", pe_ttm: "PER", roe_ttm: "ROE", dividend_yield_ttm: "배당수익률" }
const STATUS_TEXT: Record<StepStatus, string> = { QUEUED: "대기 중", STARTED: "진행 중", SUCCESS: "완료", PARTIAL: "완료", FAILED: "실패", CANCELLED: "취소됨" }
function StepIcon({ status, size = "size-5" }: { status: StepStatus; size?: string }) {
  if (status === "STARTED") return <Loader2 className={`${size} shrink-0 animate-spin text-blue-700`} aria-hidden="true" />
  if (status === "SUCCESS" || status === "PARTIAL") return <Check className={`${size} shrink-0 text-emerald-600`} aria-hidden="true" />  // 안내 유무는 NoteCount 로 따로 표시
  if (status === "FAILED") return <AlertCircle className={`${size} shrink-0 text-red-600`} aria-hidden="true" />
  if (status === "CANCELLED") return <X className={`${size} shrink-0 text-slate-500`} aria-hidden="true" />
  return <Circle className={`${size} shrink-0 text-slate-300`} aria-hidden="true" />
}
const statusTone = (s: StepStatus) => (s === "STARTED" ? "text-blue-700" : s === "SUCCESS" || s === "PARTIAL" ? "text-emerald-700" : s === "FAILED" ? "text-red-700" : "text-slate-400")

/** 진행 중 요약 "서버 단계 이름 i/n" 의 이름 부분만 화면 이름으로 바꾼다 (i/n 은 서버가 준 실제 진행 수). */
const startedText = (s: RunStep) => (s.summary && s.summary.startsWith(`${s.label_ko} `) ? s.summary.slice(s.label_ko.length + 1) : null)

/** 묶음·단계에 나온 안내 수. 완료 여부와 별개로 표시한다 (안내가 있어도 실패가 아니다). */
function NoteCount({ n, label }: { n: number; label: string }) {
  if (!n) return null
  return <span aria-label={`${label} ${n}건`} title={`${label} ${n}건`} className="inline-flex shrink-0 items-center gap-1 rounded-md bg-amber-50 px-1.5 py-0.5 text-[11px] font-semibold text-amber-800"><AlertTriangle className="size-3" aria-hidden="true" />확인할 점 {n}</span>
}

/** 스크린리더 알림 문구. 첫 응답의 안내는 기준으로 삼고(재진입 시 알리지 않는다), 그 뒤 처음 보는 키가 생길 때만 바뀐다. 같은 응답이 반복돼도 키가 같으면 아무 일도 없다. */
function useNewNotesAnnouncement(ready: boolean, n: RunNotes) {
  const seen = useRef<Set<string> | null>(null)
  const [live, setLive] = useState("")
  const sig = n.keys.join("\n")
  useEffect(() => {
    if (!ready) return
    if (!seen.current) { seen.current = new Set(n.keys); return }
    const added = n.keys.filter((k) => !seen.current!.has(k))
    if (!added.length) return
    for (const k of added) seen.current.add(k)
    setLive(`확인할 점에 새 안내 ${added.length}건이 추가되었습니다. 전체 ${n.total}건입니다.`)
  }, [ready, sig])  // eslint-disable-line react-hooks/exhaustive-deps -- 키 목록이 실제로 달라질 때만
  return live
}

/** 실행이 바뀌면(재실행 등) 이전 실행의 상태·알림을 모두 버린다. */
export function RunScreen({ runId }: { runId: string }) {
  return <RunView key={runId} runId={runId} />
}

function RunView({ runId }: { runId: string }) {
  const svc = useService()
  const { health } = useHealth()
  const { data, error, failures } = usePolling(() => svc.getRun(runId), { intervalMs: 2500, until: (d: RunStatus) => TERMINAL.has(d.status) }, [svc, runId])
  const gate = useGuideGate()  // 「리포트 보기」를 처음 누르면 리포트 가이드를 볼지 묻는다
  const [override, setOverride] = useState<RunStatus | null>(null)  // 취소 응답처럼 폴링보다 먼저 받은 상태
  const r = !data ? override : !override ? data : STAGE_RANK[override.status] > STAGE_RANK[data.status] ? override : data
  const done = r?.status === "success" || r?.status === "partial"
  const cmp = useResource(() => (done ? svc.getReportComparison(r?.report_id ?? runId) : Promise.resolve(null)), [svc, runId, done])  // 수정안 실행이면 원안과 비교 결과가 있다
  const [actErr, setActErr] = useState<{ kind: "cancel" | "retry" | "new"; message: string } | null>(null)
  const [busy, setBusy] = useState<"" | "cancel" | "retry" | "new">("")
  const [confirmCancel, setConfirmCancel] = useState(false)
  const [cancelAsked, setCancelAsked] = useState(false)
  const [open, setOpen] = useState<Record<string, boolean>>({})  // 묶음별 세부 단계 펼침
  const [now, setNow] = useState(() => Date.now())
  const [partial, setPartial] = useState<RunPartial | null>(null)
  const [partialTried, setPartialTried] = useState(false)
  const summaryNotes = useMemo(() => collectNotes(r?.steps ?? []), [r])
  // 제안 기능: 전체 경고 목록 (목업에서만). 단계 요약에는 단계마다 2건까지만 오므로, 있으면 전체 목록을 쓴다.
  const fullRes = useResource(() => (svc.getRunWarnings ? svc.getRunWarnings(runId) : Promise.resolve(null)), [svc, runId, summaryNotes.keys.join("|"), r?.status])
  const fullWs = fullRes.data
  const collected = useMemo(() => (fullWs ? notesFromWarnings(fullWs, r?.steps ?? []) : summaryNotes), [fullWs, summaryNotes, r])
  const live = useNewNotesAnnouncement(!!r && (!svc.getRunWarnings || !!fullWs), collected)  // 전체 목록을 쓰면 그것이 처음 온 뒤를 기준으로 삼는다
  const [notesOpen, setNotesOpen] = useState(true)
  const [flash, setFlash] = useState(false)
  const notesRef = useRef<HTMLElement>(null)
  const notesTitle = useRef<HTMLHeadingElement>(null)
  const flashTimer = useRef<number | undefined>(undefined)
  useEffect(() => () => window.clearTimeout(flashTimer.current), [])
  useEffect(() => { const t = window.setInterval(() => setNow(Date.now()), 1000); return () => window.clearInterval(t) }, [])
  useEffect(() => {  // App 의 main(overflow-x-auto)이 스크롤 컨테이너가 되면 오른쪽 열의 sticky 가 듣지 않는다. 이 화면에 있는 동안만 clip 으로 바꾸고 나갈 때 되돌린다.
    const main = document.querySelector("main")
    if (!main) return
    main.style.overflowX = "clip"
    return () => { main.style.overflowX = "" }
  }, [])
  const selStep = r?.steps.find((s) => s.step === "05_selection")
  const selDone = selStep?.status === "SUCCESS" || selStep?.status === "PARTIAL"
  useEffect(() => {  // 선정이 끝나면 종목 목록을 먼저 보여 준다 (백테스트는 뒤에 이어진다). 아직 파일이 없으면 다음 폴링 때 다시 묻는다.
    if (!selDone || partial?.selection) return
    let alive = true
    svc.getRunPartial(runId).then((p) => { if (!alive) return; if (p) setPartial(p); setPartialTried(true) }).catch(() => { if (alive) setPartialTried(true) })
    return () => { alive = false }
  }, [selDone, partial?.selection, svc, runId, r])
  if (!r && error) return <EmptyState title="실행 상태를 불러올 수 없습니다" description={error} action={<Button onClick={() => navigate({ page: "home" })}>홈으로</Button>} />
  if (!r) return <Loading label="실행 상태를 불러오는 중…" />
  if (TERMINAL.has(r.status)) saveUi({ activeRunId: null })
  const current = r.steps.filter((s) => s.status === "STARTED")  // 의존이 없는 단계는 동시에 돈다 (여러 개가 진행 중일 수 있음)
  const cancel = async () => {
    setBusy("cancel"); setActErr(null); setCancelAsked(true)
    try { setOverride(await svc.cancelRun(runId)); setConfirmCancel(false) } catch (e) { setCancelAsked(false); setActErr({ kind: "cancel", message: errorMessage(e) }) } finally { setBusy("") }
  }
  const retry = async () => {
    setBusy("retry"); setActErr(null)
    try { const st = await svc.retryRun(runId); saveUi({ activeRunId: st.run_id }); navigate({ page: "run", runId: st.run_id }) } catch (e) { setActErr({ kind: "retry", message: errorMessage(e) }) } finally { setBusy("") }
  }
  const newRequest = async () => {  // 같은 아이디어·조건을 홈에 미리 채워 새 요청으로
    setBusy("new"); setActErr(null)
    try { const d = await svc.getRequest(r.request_id); startNewWith(d.idea, d.overrides) } catch (e) { setActErr({ kind: "new", message: errorMessage(e) }) } finally { setBusy("") }
  }
  const reportId = r.report_id ?? runId
  const failedStep = r.error?.step ? r.steps.find((s) => s.step === r.error!.step) : undefined
  const workerDown = health ? !health.worker.alive : false
  const since = elapsed(r.started_at ?? r.queued_at, now)
  const doneN = r.steps.filter((s) => s.status === "SUCCESS" || s.status === "PARTIAL").length
  const active = r.status === "queued" || r.status === "running"
  /** 사용자가 눌렀을 때만 이동한다 (안내가 새로 생겨도 저절로 스크롤·포커스하지 않는다). 키보드로 실행하면 제목으로 포커스를 옮긴다. */
  const goNotes = (e: React.MouseEvent) => {
    setNotesOpen(true); setFlash(true)
    window.clearTimeout(flashTimer.current)
    flashTimer.current = window.setTimeout(() => setFlash(false), 2000)
    const reduce = window.matchMedia?.("(prefers-reduced-motion: reduce)").matches
    notesRef.current?.scrollIntoView?.({ behavior: reduce ? "auto" : "smooth", block: "start" })
    if (e.detail === 0) notesTitle.current?.focus({ preventScroll: true })
  }
  const title = r.status === "queued" ? `대기 중 (순번 ${r.queue_position ?? "-"})` : r.status === "running" ? "분석을 실행하고 있습니다" : r.status === "cancelling" ? "분석 취소를 요청했습니다" : r.status === "success" ? "분석이 끝났습니다" : r.status === "partial" ? "분석이 끝났습니다 (확인할 점 있음)" : r.status === "failed" ? "분석이 실패했습니다" : "분석이 취소되었습니다"
  const retryBtns = (
    <div className="flex flex-wrap gap-2">
      <Button variant="secondary" onClick={() => void retry()} disabled={busy !== ""}>{busy === "retry" ? "다시 등록 중…" : "같은 조건으로 다시 실행"}</Button>
      <Button variant="secondary" onClick={() => void newRequest()} disabled={busy !== ""}>{busy === "new" ? "불러오는 중…" : "조건 고쳐 새 요청"}</Button>
      <Button variant="ghost" onClick={() => navigate({ page: "home" })}>홈으로</Button>
    </div>
  )

  return (
    <div className="mx-auto max-w-6xl space-y-8">
      <p className="sr-only" role="status" aria-live="polite">{live}</p>
      <FlowHeader eyebrow="분석 진행" title={title} desc={`등록 ${datetime(r.queued_at)}${r.started_at ? ` · 시작 ${datetime(r.started_at)}` : ""}${r.finished_at ? ` · 종료 ${datetime(r.finished_at)}` : since ? ` · 경과 ${since}` : ""} · 브라우저를 닫아도 서버 실행은 계속됩니다. 보통 2~5분 걸립니다.`} />
      {failures > 0 && <Alert title="연결 재시도 중" tone="warning">서버 응답이 없어 마지막으로 받은 상태를 보여 줍니다 ({failures}회 실패). {error}</Alert>}
      {active && workerDown && <Alert title="분석 일꾼이 꺼져 있어 시작되지 않습니다" tone="error">요청은 대기열에 남아 있습니다. 서버 관리자에게 분석 일꾼을 켜 달라고 하세요. 켜지면 자동으로 시작합니다.</Alert>}
      <div className="grid grid-cols-1 items-start gap-8 lg:grid-cols-[1.15fr_0.85fr]">
        {/* 오른쪽: 지금 하는 일·취소·결과·선정 종목 (좁은 화면에서는 위로) */}
        <div className="space-y-8 lg:sticky lg:top-6 lg:col-start-2 lg:row-start-1 lg:max-h-[calc(100vh-3rem)] lg:overflow-y-auto lg:pb-1">
          <Part title={TERMINAL.has(r.status) ? "분석 결과" : "지금 하는 일"}>
            {r.status === "queued" && <p className="text-sm leading-6 text-slate-700"><b>대기열에서 차례를 기다리고 있습니다 (순번 {r.queue_position ?? "-"}).</b><br />{workerDown ? "분석 일꾼이 켜지면 자동으로 시작합니다." : "앞선 요청이 끝나면 자동으로 시작합니다. 이 화면을 닫아도 됩니다."}</p>}
            {(r.status === "running" || r.status === "cancelling") && current.map((s) => (
              <div key={s.step} className="rounded-xl border border-blue-200 bg-blue-50 p-4">
                <p className="flex items-center gap-2 text-sm font-bold text-blue-950"><StepIcon status="STARTED" size="size-4" />{stepTitle(s.step, s.label_ko)}{startedText(s) && <span className="font-normal text-blue-800">{startedText(s)}</span>}</p>
                {STEP_TEXT[s.step] && <p className="mt-1 text-xs leading-5 text-blue-900/80">{STEP_TEXT[s.step].desc}</p>}
              </div>
            ))}
            {r.status === "running" && current.length === 0 && <p className="text-sm text-slate-600">다음 단계를 준비하고 있습니다.</p>}
            {active && <button type="button" onClick={() => navigate({ page: "tutorial" })} className="text-sm font-semibold text-blue-700 hover:underline focus:outline-none focus:ring-2 focus:ring-blue-500">기다리는 동안 리포트 보는 법 둘러보기</button>}
            {active && (
              <div className="border-t border-slate-100 pt-4">
                {!confirmCancel ? <Button variant="danger" onClick={() => setConfirmCancel(true)} disabled={busy !== ""}><X className="size-4" />분석 취소</Button>
                  : (
                    <div className="rounded-xl border border-red-200 bg-red-50 p-4 text-sm text-red-900">
                      <p>정말 취소할까요? 지금까지 진행한 단계는 버려지고 리포트는 만들지 않습니다.</p>
                      <div className="mt-3 flex flex-wrap gap-2"><Button variant="danger" onClick={() => void cancel()} disabled={busy !== ""}>{busy === "cancel" ? "취소 요청을 보내는 중…" : "취소 확정"}</Button><Button variant="ghost" onClick={() => setConfirmCancel(false)} disabled={busy !== ""}>계속 진행</Button></div>
                    </div>
                  )}
                {actErr?.kind === "cancel" && <div className="mt-3"><ActionError title="취소 요청을 보내지 못했습니다" message={actErr.message} retry={() => void cancel()} /></div>}
              </div>
            )}
            {r.status === "cancelling" && (proposedCancelOf(r)?.immediate
              ? <Pending title="취소를 처리하고 있습니다." detail={`${proposedCancelOf(r)!.stopped_step ? `「${stepTitle(proposedCancelOf(r)!.stopped_step!, proposedCancelOf(r)!.stopped_step_label_ko ?? "")}」 단계를 바로 멈추고 있습니다. ` : ""}잠시 뒤 이 화면이 「분석이 취소되었습니다」로 바뀝니다. (목업: 즉시 취소)`} />
              : <Pending title="분석 취소를 요청했습니다. 현재 작업이 종료되는 데 시간이 걸릴 수 있습니다." detail="진행 중인 단계가 끝나는 시점에 분석이 멈춥니다. 서버가 취소를 마치면 이 화면이 「분석이 취소되었습니다」로 바뀝니다." />)}
            {done && (
              <>
                <p className="text-sm text-slate-700">결과와 리포트가 저장되었습니다.{cancelAsked ? " 취소 요청이 반영되기 전에 분석이 끝났습니다." : ""}</p>
                <Button className="w-full" onClick={() => gate.go({ page: "report", reportId })}>리포트 보기</Button>
                {gate.dialog}
                {collected.total > 0 && <NoteLink total={collected.total} onGo={goNotes} />}
                {cmp.data && <Button variant="secondary" className="w-full" onClick={() => navigate({ page: "comparison", comparisonId: cmp.data!.comparison_id })}>원안과 비교 보기</Button>}
              </>
            )}
            {r.status === "failed" && (
              <>
                <div role="alert" className="rounded-xl border border-red-200 bg-red-50 p-4 text-sm text-red-950">
                  <p className="font-semibold">{failedStep ? `「${stepTitle(failedStep.step, failedStep.label_ko)}」 단계에서 실패했습니다` : "분석이 실패했습니다"}</p>
                  {r.error && <p className="mt-1 opacity-80">{r.error.message_ko}</p>}
                  {cancelAsked && <p className="mt-1 text-xs">취소 요청이 반영되기 전에 분석이 끝났습니다.</p>}
                </div>
                {retryBtns}
              </>
            )}
            {r.status === "cancelled" && <>{proposedCancelOf(r) && <CancelSummary c={proposedCancelOf(r)!} />}<p className="text-sm text-slate-700">리포트는 만들지 않았습니다. 요청 조건은 보존되어 같은 조건으로 다시 시작할 수 있습니다.</p>{retryBtns}</>}
            {actErr && actErr.kind !== "cancel" && <ActionError title={actErr.kind === "retry" ? "다시 실행하지 못했습니다" : "요청 조건을 불러오지 못했습니다"} message={actErr.message} />}
          </Part>
          <SelectionPreview partial={partial} selStep={selStep} tried={partialTried} done={done} live={!TERMINAL.has(r.status)} />
        </div>
        {/* 왼쪽: 단계 진행 */}
        <div className="space-y-8 lg:col-start-1 lg:row-start-1">
          <Part title="진행 단계" aside={<MockTag />} desc={`전체 ${r.steps.length}단계 중 ${doneN}단계 완료 · 실제 실행 기록만 보여 줍니다.`}>
            <ol className="space-y-2">
              {r.buckets.map((b) => {
                const steps = r.steps.filter((s) => s.bucket === b.id)
                const running = b.status === "STARTED"
                const isOpen = open[b.id] ?? false
                return (
                  <li key={b.id} aria-current={running ? "step" : undefined} className={`rounded-xl border ${running ? "border-blue-300 bg-blue-50/60 ring-1 ring-blue-200" : "border-slate-200 bg-white"}`}>
                    <button type="button" aria-expanded={isOpen} onClick={() => setOpen((o) => ({ ...o, [b.id]: !isOpen }))} className="flex w-full items-center gap-3 rounded-xl p-3 text-left hover:bg-slate-50/80 focus:outline-none focus:ring-2 focus:ring-blue-500">
                      <StepIcon status={b.status} />
                      <span className="min-w-0 flex-1">
                        <span className={`block text-sm font-semibold ${b.status === "QUEUED" ? "text-slate-500" : "text-slate-900"}`}>{BUCKET_TEXT[b.id] ?? b.title_ko}</span>
                        <span className={`mt-0.5 block text-xs font-semibold sm:hidden ${statusTone(b.status)}`}>{STATUS_TEXT[b.status]}</span>
                        {running && <span className="mt-0.5 block text-xs text-blue-800">진행 중: {steps.filter((s) => s.status === "STARTED").map((s) => stepTitle(s.step, s.label_ko)).join(" · ")}</span>}
                      </span>
                      <NoteCount n={collected.byBucket[b.id] ?? 0} label="이 묶음의 확인할 점" />
                      <span className={`hidden shrink-0 text-xs font-semibold sm:inline ${statusTone(b.status)}`}>{STATUS_TEXT[b.status]}</span>
                      <span className="flex shrink-0 items-center gap-1 text-xs text-slate-400"><span className="hidden sm:inline">{steps.length}단계</span><ChevronDown className={`size-4 transition-transform ${isOpen ? "rotate-180" : ""}`} /></span>
                    </button>
                    {isOpen && (
                      <ol className="space-y-3 border-t border-slate-100 px-3 py-3">
                        {steps.map((s) => {
                          const sp = splitSummary(s.summary)
                          return (
                            <li key={s.step} className="flex gap-3">
                              <StepIcon status={s.status} size="size-4" />
                              <div className="min-w-0 flex-1 text-sm">
                                <p className="flex flex-wrap items-baseline justify-between gap-x-3"><span className={`font-semibold ${s.status === "QUEUED" ? "text-slate-500" : "text-slate-800"}`}>{stepTitle(s.step, s.label_ko)}</span><span className="flex items-center gap-2"><NoteCount n={sp.warnCount} label="이 단계의 확인할 점" /><span className={`text-xs font-semibold ${statusTone(s.status)}`}>{STATUS_TEXT[s.status]}</span></span></p>
                                {STEP_TEXT[s.step] && <p className="mt-0.5 text-xs leading-5 text-slate-500">{STEP_TEXT[s.step].desc}</p>}
                                {s.status === "STARTED" && startedText(s) && <p className="mt-0.5 text-xs text-blue-800">진행 {startedText(s)}</p>}
                                {s.status !== "STARTED" && sp.main && <p className="mt-0.5 break-words text-xs text-slate-600">결과: {sp.main}</p>}
                                {s.error_message && <p className="mt-0.5 break-words text-xs text-red-700">{s.error_message}</p>}
                              </div>
                            </li>
                          )
                        })}
                      </ol>
                    )}
                  </li>
                )
              })}
            </ol>
          </Part>
          <NotesCard ref={notesRef} titleRef={notesTitle} data={collected} open={notesOpen} setOpen={setNotesOpen} flash={flash} status={r.status} full={!!fullWs} />
        </div>
      </div>
    </div>
  )
}

/** 취소 결과 (제안 기능, 목업에서만): 요청·완료 시각과 멈춘 단계. */
function CancelSummary({ c }: { c: NonNullable<ReturnType<typeof proposedCancelOf>> }) {
  const hms = (s: string) => s.slice(11, 19)
  const sec = c.completed_at ? Math.max(0, Math.round((new Date(c.completed_at).getTime() - new Date(c.requested_at).getTime()) / 1000)) : null
  return (
    <div className="rounded-xl border border-slate-200 bg-slate-50 p-4 text-sm text-slate-700">
      <p className="flex items-center font-semibold text-slate-900">분석 취소 완료<MockTag /></p>
      <ol className="mt-2 space-y-1 text-xs">
        <li className="flex gap-2"><span className="w-20 shrink-0 text-slate-500">취소 요청</span><span className="tabular-nums">{hms(c.requested_at)}</span></li>
        {c.completed_at && <li className="flex gap-2"><span className="w-20 shrink-0 text-slate-500">취소 완료</span><span className="tabular-nums">{hms(c.completed_at)}{sec != null && ` (${sec}초 걸림)`}</span></li>}
      </ol>
      <p className="mt-2 text-xs leading-5">{c.stopped_step ? `「${stepTitle(c.stopped_step, c.stopped_step_label_ko ?? "")}」 단계에서 멈췄습니다. ` : "시작 전에 멈췄습니다. "}완료된 {c.done_steps}단계의 결과로는 리포트를 만들지 않았습니다.</p>
    </div>
  )
}

/** 완료 영역의 안내 표시. 전체 개수는 같은 문구를 하나로 센 수다. */
function NoteLink({ total, onGo }: { total: number; onGo: (e: React.MouseEvent) => void }) {
  return (
    <div className="flex flex-wrap items-center justify-between gap-2 rounded-xl border border-amber-200 bg-amber-50 px-3 py-2 text-sm text-amber-950">
      <span className="flex items-center gap-2 font-semibold"><AlertTriangle className="size-4 shrink-0 text-amber-600" aria-hidden="true" />확인할 점 {total}건</span>
      <button type="button" onClick={onGo} className="rounded-lg px-2 py-1 text-xs font-semibold text-amber-900 underline underline-offset-2 hover:bg-amber-100 focus:outline-none focus:ring-2 focus:ring-amber-500">확인할 점 보기</button>
    </div>
  )
}

const NOTES_EMPTY: Partial<Record<RunStatus["status"], string>> = {
  success: "등록된 확인 사항이 없습니다.", partial: "등록된 확인 사항이 없습니다.",
  failed: "분석이 실패해 끝까지 확인하지 못했습니다. 지금까지 등록된 안내는 없습니다.", cancelled: "분석이 취소되어 끝까지 확인하지 못했습니다. 지금까지 등록된 안내는 없습니다.",
}

/** 확인할 점: 처음부터 자리를 둔다. 안내가 없으면 작은 중립 카드, 있으면 주황 표시와 목록. 목록은 live 영역이 아니어서 폴링마다 다시 읽히지 않는다. */
const NOTES_SHOWN = 5  // 전체 목록(목업)이 이보다 많으면 나머지는 「더 보기」로
/** full: 전체 경고 목록(제안 기능)으로 만든 안내 — 같은 문구 횟수 표시, 많으면 접기. 없으면(일반 모드) 지금 그대로. */
function NotesCard({ ref, titleRef, data, open, setOpen, flash, status, full = false }: { ref: React.Ref<HTMLElement>; titleRef: React.Ref<HTMLHeadingElement>; data: RunNotes; open: boolean; setOpen: (v: boolean) => void; flash: boolean; status: RunStatus["status"]; full?: boolean }) {
  const [more, setMore] = useState(false)
  const ring = flash ? "ring-2 ring-amber-400" : ""
  const heading = <h3 ref={titleRef} tabIndex={-1} className="text-base font-bold text-slate-950 focus:outline-none focus-visible:underline">확인할 점{data.total > 0 && <> <span className="text-sm font-semibold text-amber-800">{data.total}건</span></>}{full && <MockTag />}</h3>
  const shown = full && !more ? data.notes.slice(0, NOTES_SHOWN) : data.notes
  if (data.total === 0) {
    return (
      <section ref={ref} className={`scroll-mt-4 rounded-2xl border border-slate-200 bg-white px-5 py-4 motion-safe:transition-shadow sm:px-6 ${ring}`}>
        {heading}
        <p className="mt-1 text-sm text-slate-500">{NOTES_EMPTY[status] ?? "현재까지 등록된 안내가 없습니다. 분석 중 확인할 내용이 생기면 이곳에 표시됩니다."}</p>
      </section>
    )
  }
  const unfinished = status === "failed" || status === "cancelled"
  return (
    <section ref={ref} className={`scroll-mt-4 rounded-2xl border border-slate-300 bg-white shadow-sm motion-safe:transition-shadow ${ring}`}>
      <header className={`flex items-start justify-between gap-3 border-b border-slate-200 bg-slate-50 px-5 py-4 sm:px-6 ${open ? "rounded-t-2xl" : "rounded-2xl border-b-0"}`}>
        <div className="min-w-0">
          {heading}
          <p className="mt-1 text-xs leading-5 text-slate-500">같은 내용은 한 번만 세므로 단계별 안내 수의 합과 다를 수 있습니다.{full ? " 단계 요약에 다 담기지 않은 안내까지 모두 보여 줍니다." : ""}{unfinished ? " 분석이 끝까지 진행되지 않아 안내가 더 있을 수 있습니다." : ""}</p>
        </div>
        <button type="button" aria-expanded={open} aria-label={open ? "확인할 점 접기" : "확인할 점 펼치기"} onClick={() => setOpen(!open)} className="shrink-0 rounded-lg p-1 text-slate-500 hover:bg-slate-100 focus:outline-none focus:ring-2 focus:ring-blue-500"><ChevronDown className={`size-4 transition-transform ${open ? "rotate-180" : ""}`} /></button>
      </header>
      {open && (
        <div className="space-y-3 p-5 sm:p-6">
          <ul className="space-y-2.5 text-sm">
            {shown.map((n) => (
              <li key={n.key} className="flex gap-2">
                <AlertTriangle className="mt-0.5 size-4 shrink-0 text-amber-600" aria-hidden="true" />
                <span className="min-w-0 break-words text-slate-800">{n.text}<span className="mt-0.5 block text-xs text-slate-500">{full ? `관련 단계: ${n.from.join(" · ")}` : n.from.join(" · ")}{full && (n.count ?? 1) > 1 && <span className="ml-1.5 rounded bg-slate-100 px-1.5 py-px font-semibold text-slate-600">같은 안내 {n.count}번</span>}</span></span>
              </li>
            ))}
          </ul>
          {full && data.notes.length > NOTES_SHOWN && <button type="button" aria-expanded={more} onClick={() => setMore(!more)} className="text-xs font-semibold text-blue-700 hover:underline">{more ? "접기" : `나머지 ${data.notes.length - NOTES_SHOWN}건 더 보기`}</button>}
          {data.unlisted > 0 && <p className="text-xs text-slate-500">내용이 표시되지 않은 안내 {data.unlisted}건은 리포트에서 확인할 수 있습니다.</p>}
        </div>
      )}
    </section>
  )
}

/** 선정 종목 미리보기: 처음부터 자리를 두고, 실제 단계 상태에 맞는 안내 → 서버가 준 선정 결과 순서로 바꾼다. */
function SelectionPreview({ partial, selStep, tried, done, live }: { partial: RunPartial | null; selStep: RunStep | undefined; tried: boolean; done: boolean; live: boolean }) {
  const sel = partial?.selection
  const st = selStep?.status
  return (
    <Part title="선정 종목 미리보기" desc={sel ? `${sel.n_selected}개${sel.n_target ? ` (목표 ${sel.n_target}개)` : ""} · 기준일 ${sel.as_of}${partial?.intent?.metric && METRIC_KO[partial.intent.metric] ? ` · 선정 지표 ${METRIC_KO[partial.intent.metric]}` : ""}${live ? " · 과거 성과 분석은 아직 진행 중" : ""}` : undefined}>
      {sel ? (
        <>
          {partial?.intent?.summary_ko && <p className="text-sm text-slate-600">{partial.intent.summary_ko}</p>}
          <div className="max-h-[45vh] overflow-auto rounded-xl border border-slate-200">
            <table className="w-full text-sm">
              <thead className="sticky top-0 bg-slate-50 text-left text-xs font-semibold text-slate-500"><tr><th className="whitespace-nowrap px-3 py-2">순위</th><th className="px-3 py-2">종목</th><th className="hidden px-3 py-2 sm:table-cell">섹터</th><th className="px-3 py-2 text-right">지표</th></tr></thead>
              <tbody>{sel.rows.map((x) => <tr key={x.ticker} className="border-t border-slate-100"><td className="px-3 py-1.5 tabular-nums text-slate-500">{x.rank ?? "–"}</td><td className="px-3 py-1.5"><b>{x.ticker}</b> <span className="text-slate-600">{x.name ?? ""}</span></td><td className="hidden px-3 py-1.5 text-slate-500 sm:table-cell">{x.sector ?? ""}</td><td className="px-3 py-1.5 text-right tabular-nums">{x.metric_value == null || Number.isNaN(x.metric_value) ? "–" : fmt(x.metric_value, "num")}</td></tr>)}</tbody>
            </table>
          </div>
        </>
      ) : (
        <p className="rounded-xl bg-slate-50 p-4 text-sm leading-6 text-slate-600">
          {st === "STARTED" ? "투자 종목을 선정하고 있습니다. 종목 선정이 완료되면 이곳에서 확인할 수 있습니다."
            : st === "SUCCESS" || st === "PARTIAL" ? (!tried ? "선정 결과를 불러오는 중입니다." : live ? "종목 선정은 끝났지만 미리보기 자료를 아직 받지 못했습니다. 잠시 뒤 자동으로 다시 확인합니다." : "미리보기 자료를 받지 못했습니다. 선정 종목은 리포트에서 확인할 수 있습니다.")
            : st === "FAILED" ? "종목 선정 단계가 실패해 표시할 종목이 없습니다."
            : st === "CANCELLED" ? "분석이 취소되어 종목 선정이 진행되지 않았습니다."
            : "종목 선정 대기 중입니다. 앞 단계가 끝나면 종목 선정을 시작하고, 완료되면 이곳에 선정 종목이 표시됩니다."}
        </p>
      )}
    </Part>
  )
}
