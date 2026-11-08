import { useEffect, useState } from "react"
import { useService } from "../../app/providers"
import { errorMessage } from "../../api/client"
import type { ProposedReportName } from "../../api/proposed"
import { Alert, Button, Dialog, Field, inputClass } from "../../ui"
import { MockTag } from "./proposedView"

// 리포트 이름 바꾸기·삭제. 일반 모드는 서버에 저장하고, 목업 모드는 목업 상태에서만 바뀐다.
// 이름을 바꾸거나 리포트를 지우면 홈·사이드바·목록이 다시 불러오도록 창 이벤트 하나를 보낸다.

const RENAMED = "myfinsight:report-renamed"
export const NAME_MAX = 40
export const announceRename = () => window.dispatchEvent(new Event(RENAMED))

/** 이름이 바뀔 때마다 1씩 늘어나는 값. useResource 의 deps 에 넣어 다시 불러온다. */
export function useRenameTick() {
  const [n, setN] = useState(0)
  useEffect(() => {
    const on = () => setN((x) => x + 1)
    window.addEventListener(RENAMED, on)
    return () => window.removeEventListener(RENAMED, on)
  }, [])
  return n
}

export function RenameReportDialog({ reportId, close }: { reportId: string; close: () => void }) {
  const svc = useService()
  const [name, setName] = useState<ProposedReportName | null>(null)
  const [value, setValue] = useState("")
  const [error, setError] = useState<string | null>(null)
  const [busy, setBusy] = useState(false)
  useEffect(() => {
    svc.getReportName?.(reportId).then((n) => { setName(n); setValue(n.display_ko) }, (e) => setError(errorMessage(e)))
  }, [svc, reportId])

  const save = async (next: string | null) => {
    if (!svc.renameReport) return
    if (next !== null && !next.trim()) { setError("이름을 입력해 주세요. 자동 이름을 쓰려면 ‘자동 이름으로 되돌리기’를 누르세요."); return }
    setBusy(true); setError(null)
    try { await svc.renameReport(reportId, next); announceRename(); close() } catch (e) { setError(errorMessage(e)) } finally { setBusy(false) }
  }
  const unchanged = !!name && value.trim() === name.display_ko

  return (
    <Dialog title="리포트 이름 바꾸기" close={close}>
      <form className="space-y-4 p-4 text-sm text-slate-700 sm:p-6" onSubmit={(e) => { e.preventDefault(); void save(value) }}>
        {name && (
          <>
            <Field label="리포트 이름" help={`최대 ${NAME_MAX}자`}>
              <input className={inputClass} value={value} maxLength={NAME_MAX} autoFocus onChange={(e) => { setValue(e.target.value); setError(null) }} />
            </Field>
            <p className="break-words text-xs leading-5 text-slate-500">자동 이름: <b className="font-semibold text-slate-700">{name.auto_ko}</b> (투자 아이디어로 만든 이름){name.custom_ko && " · 지금은 직접 정한 이름을 쓰고 있습니다"}</p>
            {svc.getPaperName && <p className="text-xs leading-5 text-slate-500">‘리포트 이름과 동일하게’ 연동한 모의투자 이름도 함께 바뀝니다. 직접 입력한 모의투자 이름은 그대로입니다.</p>}
          </>
        )}
        {error && <Alert tone="error" title="저장하지 못했습니다">{error}</Alert>}
        {svc.mode === "mock" && <p className="flex items-center text-xs text-amber-900"><MockTag /><span className="ml-1.5">목업 화면에서만 바뀌고 실제 서버에는 저장하지 않습니다.</span></p>}
        <div className="flex flex-wrap items-center justify-between gap-2">
          <div>{name?.custom_ko && <Button type="button" variant="ghost" onClick={() => void save(null)} disabled={busy}>자동 이름으로 되돌리기</Button>}</div>
          <div className="flex gap-2">
            <Button type="button" variant="ghost" onClick={close}>취소</Button>
            <Button type="submit" disabled={busy || !name || unchanged}>{busy ? "저장하는 중…" : "저장"}</Button>
          </div>
        </div>
      </form>
    </Dialog>
  )
}

/** 리포트 삭제 확인 (목록·리포트 화면 공용): 「확인」을 눌러야 삭제하고, 「취소」·닫기는 아무것도 하지 않는다. */
export function DeleteReportDialog({ reportId, name, close, onDeleted }: { reportId: string; name: string; close: () => void; onDeleted?: () => void }) {
  const svc = useService()
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const remove = async () => {
    if (!svc.deleteReport) return
    setBusy(true); setError(null)
    try { await svc.deleteReport(reportId); announceRename(); close(); onDeleted?.() } catch (e) { setError(errorMessage(e)) } finally { setBusy(false) }
  }
  return (
    <Dialog title="리포트를 삭제할까요?" close={busy ? () => {} : close}>
      <div className="space-y-3 px-6 py-5 text-sm leading-6 text-slate-700">
        <p><b className="text-slate-950">「{name}」</b> 리포트를 삭제합니다. 삭제하면 저장된 리포트 목록에서 사라지고 다시 열 수 없습니다.</p>
        {svc.mode === "mock" && <p className="flex flex-wrap items-center gap-1.5 text-xs text-slate-500"><MockTag />목업 데이터에서만 삭제되고, 실제 서버의 리포트는 그대로입니다.</p>}
        {error && <Alert title="리포트를 삭제하지 못했습니다" tone="error">{error}</Alert>}
      </div>
      <div className="flex justify-end gap-2 border-t border-slate-200 px-6 py-4">
        <Button variant="neutral" onClick={close} disabled={busy}>취소</Button>
        <Button variant="destructive" onClick={() => void remove()} disabled={busy}>{busy ? "삭제하는 중…" : "확인"}</Button>
      </div>
    </Dialog>
  )
}
