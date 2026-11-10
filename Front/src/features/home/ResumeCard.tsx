import { useId, useState } from "react"
import { ChevronDown, ChevronUp } from "lucide-react"
import { useService } from "../../app/providers"
import { navigate } from "../../app/router"
import { errorMessage } from "../../api/client"
import type { RunRow } from "../../api/types"
import { saveUi } from "../../state/uiStorage"
import { Alert, Button } from "../../ui"
import { datetime } from "../../lib/format"
import { ActionError } from "../analysis/flow"

/** 홈 「취소한 분석」: 멈춘 곳부터 이어서 실행할 수 있는 취소된 분석 (서버 실행 목록 기준, 최근 순 — 다른 브라우저에서도 보인다).
 *  가장 최근 1건은 늘 보이고, 나머지는 「나머지 N건 보기」 토글 안에 (펼쳐도 카드 안에서만 스크롤해 홈이 밀리지 않게). */
export function ResumeCard({ runs, onDismiss }: { runs: RunRow[]; onDismiss: (runId: string) => void }) {
  const svc = useService()
  const listId = useId()
  const [open, setOpen] = useState(false)
  const [busy, setBusy] = useState<string | null>(null)
  const [err, setErr] = useState<{ id: string; message: string } | null>(null)
  const resume = async (runId: string) => {
    setBusy(runId); setErr(null)
    try { const st = await svc.retryRun(runId); saveUi({ activeRunId: st.run_id }); navigate({ page: "run", runId: st.run_id }) } catch (e) { setErr({ id: runId, message: errorMessage(e) }) } finally { setBusy(null) }
  }
  if (!runs.length) return null
  const [first, ...rest] = runs

  const row = (r: RunRow, primary: boolean) => (
    <div className="rounded-lg border border-blue-100 bg-white/70 p-3">
      <p className="truncate text-sm text-slate-800"><b className="font-semibold">{r.idea ? `‘${r.idea.split("\n")[0]}’` : "취소한 분석"}</b><span className="text-xs text-slate-500"> · {datetime(r.finished_at)} 취소</span></p>
      <div className="mt-2 flex flex-wrap gap-2">
        <Button variant={primary ? "primary" : "secondary"} onClick={() => void resume(r.run_id)} disabled={busy !== null}>{busy === r.run_id ? "다시 등록 중…" : "멈춘 곳부터 이어서 실행"}</Button>
        <Button variant="ghost" onClick={() => navigate({ page: "run", runId: r.run_id })}>보기</Button>
        <Button variant="ghost" onClick={() => onDismiss(r.run_id)}>지우기</Button>
      </div>
      {err?.id === r.run_id && <div className="mt-2"><ActionError title="이어서 실행하지 못했습니다" message={err.message} retry={() => void resume(r.run_id)} /></div>}
    </div>
  )

  return (
    <Alert title={runs.length === 1 ? "취소한 분석이 있습니다" : `취소한 분석이 ${runs.length}건 있습니다`} tone="info">
      <p className="mb-3">멈춘 곳부터 이어서 실행하면 같은 조건으로 다시 돌리되, 취소 전에 끝난 단계는 저장된 결과를 다시 써서 빠르게 지나갑니다.</p>
      {row(first, true)}
      {rest.length > 0 && (
        <>
          <button type="button" aria-expanded={open} aria-controls={listId} onClick={() => setOpen((o) => !o)}
            className="mt-3 inline-flex items-center gap-1 rounded-md px-1 text-xs font-semibold text-blue-800 hover:underline focus:outline-none focus:ring-2 focus:ring-blue-500">
            {open ? <><ChevronUp className="size-4" aria-hidden />접기</> : <><ChevronDown className="size-4" aria-hidden />나머지 {rest.length}건 보기</>}
          </button>
          {open && <ul id={listId} aria-label="나머지 취소한 분석" className="mt-2 max-h-72 space-y-2 overflow-y-auto pr-1">{rest.map((r) => <li key={r.run_id}>{row(r, false)}</li>)}</ul>}
        </>
      )}
    </Alert>
  )
}
