import { useId, useState, type ReactNode } from "react"
import { ChevronDown, ChevronUp, History, PlayCircle } from "lucide-react"
import { useService } from "../../app/providers"
import { navigate } from "../../app/router"
import { errorMessage } from "../../api/client"
import type { RunRow } from "../../api/types"
import { saveUi } from "../../state/uiStorage"
import { datetime } from "../../lib/format"
import { ActionError } from "../analysis/flow"

const BTN = "inline-flex h-9 items-center rounded-control px-3.5 text-13 font-semibold transition disabled:cursor-not-allowed disabled:opacity-50"
const MAIN = `${BTN} bg-tint text-accent enabled:hover:bg-accent enabled:hover:text-on-accent`
const QUIET = `${BTN} text-sub enabled:hover:bg-sunken-hover enabled:hover:text-main`

/** 한 줄: 아이콘 · 제목과 설명 · 오른쪽 버튼 */
function Row({ icon, title, meta, actions, children }: { icon: ReactNode; title: ReactNode; meta?: ReactNode; actions: ReactNode; children?: ReactNode }) {
  return (
    <div className="py-3.5">
      <div className="flex items-center gap-4">
        <span aria-hidden className="grid size-9 shrink-0 place-items-center rounded-full bg-tint text-accent">{icon}</span>
        <div className="min-w-0 flex-1">
          <p className="t-strong">{title}</p>
          {meta && <p className="truncate t-meta">{meta}</p>}
        </div>
        <div className="flex shrink-0 items-center gap-1">{actions}</div>
      </div>
      {children}
    </div>
  )
}

/**
 * 홈 「이어서 할 일」: 진행 중이던 분석(이 브라우저에 남은 요청·실행)과 취소한 분석(멈춘 곳부터 이어서 실행 가능, 서버 실행 목록 기준)을 한 카드에 한 줄씩.
 * 취소한 분석은 가장 최근 1건만 늘 보이고, 나머지는 「나머지 N건 보기」 토글 안에 (펼쳐도 카드 안에서만 스크롤해 홈이 밀리지 않게).
 * 둘 다 없으면 그리지 않는다.
 */
export function ContinueCard({ runs, onDismiss, activeRequestId, activeRunId, onClearActive }: {
  runs: RunRow[]; onDismiss: (runId: string) => void
  activeRequestId: string | null; activeRunId: string | null; onClearActive: () => void
}) {
  const svc = useService()
  const listId = useId()
  const [open, setOpen] = useState(false)
  const [busy, setBusy] = useState<string | null>(null)
  const [err, setErr] = useState<{ id: string; message: string } | null>(null)
  const resume = async (runId: string) => {
    setBusy(runId); setErr(null)
    try { const st = await svc.retryRun(runId); saveUi({ activeRunId: st.run_id }); navigate({ page: "run", runId: st.run_id }) } catch (e) { setErr({ id: runId, message: errorMessage(e) }) } finally { setBusy(null) }
  }
  if (!runs.length && !activeRequestId && !activeRunId) return null
  const [first, ...rest] = runs

  const resumeActions = (r: RunRow, main: boolean) => <>
    <button type="button" title="같은 조건으로 다시 돌리되, 취소 전에 끝난 단계는 저장된 결과를 다시 써서 빠르게 지나갑니다." onClick={() => void resume(r.run_id)} disabled={busy !== null} className={main ? MAIN : QUIET}>{busy === r.run_id ? "다시 등록 중…" : "멈춘 곳부터 이어서 실행"}</button>
    <button type="button" onClick={() => navigate({ page: "run", runId: r.run_id })} className={QUIET}>보기</button>
    <button type="button" onClick={() => onDismiss(r.run_id)} className={QUIET}>지우기</button>
  </>
  const resumeMeta = (r: RunRow) => <>{r.idea ? `‘${r.idea.split("\n")[0]}’` : "취소한 분석"} · {datetime(r.finished_at)} 취소</>
  const resumeError = (r: RunRow) => err?.id === r.run_id && <div className="mt-2 pl-[52px]"><ActionError title="이어서 실행하지 못했습니다" message={err.message} retry={() => void resume(r.run_id)} /></div>

  return (
    <section aria-label="이어서 할 일" className="divide-y divide-line rounded-card bg-surface px-6 py-1">
      {(activeRequestId || activeRunId) && (
        <Row icon={<PlayCircle className="size-5" />} title="진행 중이던 분석이 있습니다"
          meta={activeRequestId ? "조건 확인을 마치지 않은 요청이 있어요" : "실행 중이거나 결과를 아직 보지 않은 분석이 있어요"}
          actions={<>
            {activeRequestId && <button type="button" onClick={() => navigate({ page: "clarify", requestId: activeRequestId })} className={MAIN}>조건 확인 이어서</button>}
            {activeRunId && <button type="button" onClick={() => navigate({ page: "run", runId: activeRunId })} className={activeRequestId ? QUIET : MAIN}>실행 상태 보기</button>}
            <button type="button" onClick={onClearActive} className={QUIET}>지우기</button>
          </>} />
      )}
      {first && (
        <Row icon={<History className="size-5" />} title={runs.length === 1 ? "취소한 분석이 있습니다" : `취소한 분석이 ${runs.length}건 있습니다`} meta={resumeMeta(first)} actions={resumeActions(first, true)}>
          {resumeError(first)}
          {rest.length > 0 && (
            <div className="pl-[52px]">
              <button type="button" aria-expanded={open} aria-controls={listId} onClick={() => setOpen((o) => !o)}
                className="mt-1 inline-flex items-center gap-1 rounded-chip px-1 text-12 font-semibold text-accent hover:underline">
                {open ? <><ChevronUp className="size-4" aria-hidden />접기</> : <><ChevronDown className="size-4" aria-hidden />나머지 {rest.length}건 보기</>}
              </button>
              {open && (
                <ul id={listId} aria-label="나머지 취소한 분석" className="mt-2 max-h-72 divide-y divide-line overflow-y-auto rounded-box bg-sunken px-4">
                  {rest.map((r) => (
                    <li key={r.run_id} className="py-2.5">
                      <div className="flex items-center gap-3">
                        <p className="min-w-0 flex-1 truncate t-meta">{resumeMeta(r)}</p>
                        <div className="flex shrink-0 items-center gap-1">{resumeActions(r, false)}</div>
                      </div>
                      {resumeError(r)}
                    </li>
                  ))}
                </ul>
              )}
            </div>
          )}
        </Row>
      )}
    </section>
  )
}
