import { useEffect, useState } from "react"
import { ChevronDown, ChevronRight, X } from "lucide-react"
import { useHealth, useService } from "../../app/providers"
import { navigate } from "../../app/router"
import { errorMessage } from "../../api/client"
import type { RunPartial, RunStatus } from "../../api/types"
import { usePolling } from "../../state/usePolling"
import { useResource } from "../../state/useResource"
import { saveUi } from "../../state/uiStorage"
import { Alert, Badge, Button, Card, EmptyState, Loading, PageHeader, StatusRow } from "../../ui"
import { datetime, fmt, ko } from "../../lib/format"
import { startNewWith } from "../analysis/ClarifyScreen"

const TERMINAL = new Set(["success", "partial", "failed", "cancelled"])

const elapsed = (from: string | null | undefined, now: number) => {
  if (!from) return null
  const s = Math.max(0, Math.round((now - new Date(from).getTime()) / 1000))
  return s < 60 ? `${s}초` : `${Math.floor(s / 60)}분 ${s % 60}초`
}

export function RunScreen({ runId }: { runId: string }) {
  const svc = useService()
  const { health } = useHealth()
  const { data, error, failures } = usePolling(() => svc.getRun(runId), { intervalMs: 2500, until: (d: RunStatus) => TERMINAL.has(d.status) }, [svc, runId])
  const [override, setOverride] = useState<RunStatus | null>(null)  // 취소 응답처럼 폴링보다 먼저 받은 상태
  const r = override && (!data || override.finished_at || override.status === "cancelling") ? override : data
  const done = r?.status === "success" || r?.status === "partial"
  const cmp = useResource(() => (done ? svc.getReportComparison(r?.report_id ?? runId) : Promise.resolve(null)), [svc, runId, done])  // 수정안 실행이면 원안과 비교 결과가 있다
  const [showSteps, setShowSteps] = useState(false)
  const [actErr, setActErr] = useState("")
  const [busy, setBusy] = useState<"" | "cancel" | "retry" | "new">("")
  const [confirmCancel, setConfirmCancel] = useState(false)
  const [now, setNow] = useState(() => Date.now())
  const [partial, setPartial] = useState<RunPartial | null>(null)
  useEffect(() => { const t = window.setInterval(() => setNow(Date.now()), 1000); return () => window.clearInterval(t) }, [])
  const selDone = !!r?.steps.some((s) => s.step === "05_selection" && (s.status === "SUCCESS" || s.status === "PARTIAL"))
  useEffect(() => {  // 선정이 끝나면 종목 목록을 먼저 보여 준다 (백테스트는 뒤에 이어진다) — 라운드 5
    if (!selDone || partial?.selection) return
    let alive = true
    svc.getRunPartial(runId).then((p) => { if (alive && p) setPartial(p) }).catch(() => {})
    return () => { alive = false }
  }, [selDone, partial?.selection, svc, runId])
  if (!r && error) return <EmptyState title="실행 상태를 불러올 수 없습니다" description={error} action={<Button onClick={() => navigate({ page: "home" })}>홈으로</Button>} />
  if (!r) return <Loading label="실행 상태를 불러오는 중…" />
  if (TERMINAL.has(r.status)) saveUi({ activeRunId: null })
  const current = r.steps.find((s) => s.status === "STARTED")
  const cancel = async () => {
    setBusy("cancel"); setActErr("")
    try { setOverride(await svc.cancelRun(runId)); setConfirmCancel(false) } catch (e) { setActErr(errorMessage(e)) } finally { setBusy("") }
  }
  const retry = async () => {
    setBusy("retry"); setActErr("")
    try { const st = await svc.retryRun(runId); saveUi({ activeRunId: st.run_id }); navigate({ page: "run", runId: st.run_id }) } catch (e) { setActErr(errorMessage(e)) } finally { setBusy("") }
  }
  const newRequest = async () => {  // 같은 아이디어·조건을 홈에 미리 채워 새 요청으로
    setBusy("new"); setActErr("")
    try { const d = await svc.getRequest(r.request_id); startNewWith(d.idea, d.overrides) } catch (e) { setActErr(errorMessage(e)) } finally { setBusy("") }
  }
  const reportId = r.report_id ?? runId
  const failedStep = r.error?.step ? r.steps.find((s) => s.step === r.error!.step) : undefined
  const workerDown = health ? !health.worker.alive : false
  const since = elapsed(r.started_at ?? r.queued_at, now)
  return (
    <div className="mx-auto max-w-4xl space-y-7 pt-6">
      <PageHeader eyebrow="분석 진행" title={r.status === "queued" ? `대기 중 (순번 ${r.queue_position ?? "-"})` : r.status === "running" ? "분석을 실행하고 있습니다" : r.status === "cancelling" ? "취소 요청됨 — 현재 단계가 끝나면 중단됩니다" : r.status === "success" ? "분석이 끝났습니다" : r.status === "partial" ? "분석이 끝났습니다 (확인할 점 있음)" : r.status === "failed" ? "분석이 실패했습니다" : "분석이 취소되었습니다"}
        description={`등록 ${datetime(r.queued_at)}${r.started_at ? ` · 시작 ${datetime(r.started_at)}` : ""}${r.finished_at ? ` · 종료 ${datetime(r.finished_at)}` : since ? ` · 경과 ${since}` : ""} · 실행 번호 ${r.run_id}. 브라우저를 닫아도 서버 실행은 계속되며, 실패한 실행은 자동으로 다시 돌리지 않습니다. 보통 2~5분 걸립니다.`} />
      {failures > 0 && <Alert title="연결 재시도 중" tone="warning">서버 응답이 없어 마지막으로 받은 상태를 보여 줍니다 ({failures}회 실패). {error}</Alert>}
      {(r.status === "queued" || r.status === "running") && workerDown && <Alert title="분석 일꾼이 꺼져 있어 시작되지 않습니다" tone="error">요청은 대기열에 남아 있습니다. 서버 관리자에게 분석 일꾼을 켜 달라고 하세요. 켜지면 자동으로 시작합니다.</Alert>}
      <div className="grid grid-cols-[1.2fr_0.8fr] gap-6">
        <div className="space-y-4">
          <Card className="p-6">
            <h2 className="font-bold text-slate-900">단계별 상태</h2>
            <p className="mt-1 text-xs text-slate-500">실제 실행 기록입니다. 가짜 진행률은 표시하지 않습니다.</p>
            <div className="mt-5 space-y-4">
              {r.buckets.map((b) => {
                const steps = r.steps.filter((s) => s.bucket === b.id)
                const started = steps.filter((s) => s.status === "STARTED")  // 의존이 없는 단계는 동시에 돈다 (여러 개가 진행 중일 수 있음)
                const lastDone = [...steps].reverse().find((s) => s.summary && s.status !== "STARTED")
                const detail = started.length > 0 ? `진행: ${started.map((s) => s.summary ?? s.label_ko).join(" · ")}` : lastDone?.summary ?? null
                return <StatusRow key={b.id} label={b.title_ko} status={b.status} detail={detail} />
              })}
            </div>
            <button type="button" onClick={() => setShowSteps((v) => !v)} className="mt-5 flex items-center gap-1 text-xs font-semibold text-blue-700">{showSteps ? <ChevronDown className="size-4" /> : <ChevronRight className="size-4" />}세부 단계 {r.steps.length}개 {showSteps ? "접기" : "펼치기"}</button>
            {showSteps && (
              <ol className="mt-3 space-y-2 border-t border-slate-100 pt-3">
                {r.steps.map((s) => <li key={s.step}><StatusRow label={s.label_ko} status={s.status} detail={s.error_message ?? s.summary ?? null} /></li>)}
              </ol>
            )}
          </Card>
          {partial?.selection && (
            <Card className="p-6">
              <div className="flex flex-wrap items-baseline justify-between gap-2">
                <h2 className="font-bold text-slate-900">선정 종목 미리 보기 <span className="text-sm font-normal text-slate-500">{partial.selection.n_selected}개{partial.selection.n_target ? ` (목표 ${partial.selection.n_target})` : ""}</span></h2>
                <span className="text-xs text-slate-500">기준일 {partial.selection.as_of}{partial.intent?.metric ? ` · 선정 지표 ${ko(partial.intent.metric)}` : ""}{done ? "" : " · 백테스트는 아직 진행 중"}</span>
              </div>
              {partial.intent?.summary_ko && <p className="mt-2 text-sm text-slate-600">{partial.intent.summary_ko}</p>}
              <div className="mt-3 max-h-72 overflow-auto rounded-xl border border-slate-100">
                <table className="w-full text-sm"><thead className="bg-slate-50 text-left text-xs font-semibold text-slate-500"><tr><th className="px-3 py-2">순위</th><th className="px-3 py-2">종목</th><th className="px-3 py-2">섹터</th><th className="px-3 py-2 text-right">지표</th></tr></thead>
                  <tbody>{partial.selection.rows.map((x) => <tr key={x.ticker} className="border-t border-slate-100"><td className="px-3 py-1.5 tabular-nums text-slate-500">{x.rank ?? "–"}</td><td className="px-3 py-1.5"><b>{x.ticker}</b> <span className="text-slate-600">{x.name ?? ""}</span></td><td className="px-3 py-1.5 text-slate-500">{x.sector ?? ""}</td><td className="px-3 py-1.5 text-right tabular-nums">{x.metric_value == null || Number.isNaN(x.metric_value) ? "–" : fmt(x.metric_value, "num")}</td></tr>)}</tbody>
                </table>
              </div>
            </Card>
          )}
        </div>
        <div className="space-y-4">
          <Card className="p-5">
            <p className="text-xs font-bold text-slate-400">현재 단계</p>
            <p className="mt-2 font-bold text-slate-900">{current ? current.label_ko : r.status === "queued" ? "대기열에서 차례를 기다리는 중" : ko(r.status)}</p>
            <p className="mt-2 text-sm leading-6 text-slate-500">{r.status === "queued" ? (workerDown ? "분석 일꾼이 켜지면 자동으로 시작합니다." : "앞선 요청이 끝나면 자동으로 시작합니다. 이 화면을 닫아도 됩니다.") : current ? "완료되면 다음 단계로 넘어갑니다. 취소는 단계 경계에서 반영됩니다." : ""}</p>
          </Card>
          {r.status === "failed" && r.error && (
            <Alert title={failedStep ? `「${failedStep.label_ko}」 단계에서 실패했습니다` : "분석이 실패했습니다"} tone="error">
              <p>{r.error.message_ko}</p>
              <div className="mt-3 flex flex-wrap gap-2">
                <Button variant="secondary" onClick={() => void retry()} disabled={busy !== ""}>{busy === "retry" ? "다시 등록 중…" : "같은 조건으로 다시 실행"}</Button>
                <Button variant="secondary" onClick={() => void newRequest()} disabled={busy !== ""}>조건 고쳐 새 요청</Button>
                <Button variant="ghost" onClick={() => navigate({ page: "home" })}>홈으로</Button>
              </div>
              {actErr && <p className="mt-2 text-xs font-medium text-red-700">{actErr}</p>}
            </Alert>
          )}
          {done && (
            <Card className="p-5">
              <Badge tone={r.status === "success" ? "green" : "amber"}>{ko(r.status)}</Badge>
              <p className="mt-3 text-sm text-slate-700">결과와 리포트가 저장되었습니다.{r.status === "partial" ? " 조건을 바꾸면 결과가 달라질 수 있는 점이 있습니다. 아래 내용과 리포트 결론 옆의 안내를 확인해 주세요." : ""}</p>
              {r.status === "partial" && <ul className="mt-2 list-disc space-y-1 pl-5 text-xs text-slate-600">{r.steps.filter((s) => s.status === "PARTIAL" && s.summary).map((s) => <li key={s.step}>{s.summary!.split(" · 확인 필요")[1] ? s.summary!.split(" · 확인 필요")[1].replace(/^ \d+건: /, "") : s.summary}</li>)}</ul>}
              <Button className="mt-4 w-full" onClick={() => navigate({ page: "report", reportId })}>리포트 보기</Button>
              {cmp.data && <Button variant="secondary" className="mt-2 w-full" onClick={() => navigate({ page: "comparison", comparisonId: cmp.data!.comparison_id })}>원안과 비교 보기</Button>}
            </Card>
          )}
          {r.status === "cancelled" && (
            <Card className="p-5 text-sm text-slate-600">리포트는 생성하지 않았습니다. 요청 조건은 보존되어 같은 조건으로 다시 시작할 수 있습니다.
              <div className="mt-4 flex flex-col gap-2"><Button variant="secondary" onClick={() => void retry()} disabled={busy !== ""}>같은 조건으로 다시 실행</Button><Button variant="secondary" onClick={() => void newRequest()} disabled={busy !== ""}>조건 고쳐 새 요청</Button><Button variant="ghost" onClick={() => navigate({ page: "home" })}>홈으로</Button></div>
              {actErr && <p className="mt-2 text-xs font-medium text-red-700">{actErr}</p>}
            </Card>
          )}
          {(r.status === "queued" || r.status === "running") && (
            <div>
              {!confirmCancel ? <Button variant="danger" onClick={() => setConfirmCancel(true)} disabled={busy !== ""}><X className="size-4" />분석 취소</Button>
                : <div className="rounded-xl border border-red-200 bg-red-50 p-3 text-sm text-red-900"><p>정말 취소할까요? 지금까지 진행한 단계는 버려지고 리포트는 만들지 않습니다.</p><div className="mt-2 flex gap-2"><Button variant="danger" onClick={() => void cancel()} disabled={busy !== ""}>{busy === "cancel" ? "취소 요청 중…" : "취소 확정"}</Button><Button variant="ghost" onClick={() => setConfirmCancel(false)}>계속 진행</Button></div></div>}
              {actErr && <p className="mt-2 text-xs text-red-600">{actErr}</p>}
            </div>
          )}
        </div>
      </div>
    </div>
  )
}
