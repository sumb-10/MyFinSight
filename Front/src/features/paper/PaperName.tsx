import { useState } from "react"
import { useService } from "../../app/providers"
import { errorMessage } from "../../api/client"
import type { ProposedPaperName } from "../../api/proposed"
import { Alert, Button, Dialog, inputClass } from "../../ui"
import { MockTag } from "../report/proposedView"
import { NAME_MAX } from "../report/ReportName"

// 모의투자 이름 (제안 기능): 리포트 이름과 연동하거나 직접 입력한다. 서비스에 setPaperName 이 있을 때만 쓰인다 (실제 서버: GET/PUT /paper/{id}/name).
// 연동(linked)은 리포트 이름을 바꾸면 함께 바뀌고, 직접 입력(custom)은 그대로다.

export type NameMode = "linked" | "custom"
export const emptyNameError = "모의투자 이름을 입력해 주세요. 리포트 이름을 그대로 쓰려면 ‘리포트 이름과 동일하게 사용’을 고르세요."

export function PaperNameChoice({ reportName, mode, setMode, value, setValue, error, setError }: { reportName: string; mode: NameMode; setMode: (m: NameMode) => void; value: string; setValue: (v: string) => void; error: string; setError: (e: string) => void }) {
  return (
    <fieldset className="space-y-3 rounded-xl border border-slate-200 p-4">
      <legend className="flex items-center px-1 text-sm font-semibold text-slate-700">모의투자 이름<MockTag /></legend>
      <label className="flex cursor-pointer items-start gap-2.5"><input type="radio" name="paper-name" className="mt-1" checked={mode === "linked"} onChange={() => { setMode("linked"); setError("") }} />
        <span className="min-w-0"><span className="block font-semibold text-slate-800">리포트 이름과 동일하게 사용</span><span className="block break-words text-xs leading-5 text-slate-500">‘{reportName}’ · 리포트 이름을 바꾸면 함께 바뀝니다</span></span></label>
      <label className="flex cursor-pointer items-start gap-2.5"><input type="radio" name="paper-name" className="mt-1" checked={mode === "custom"} onChange={() => setMode("custom")} />
        <span className="min-w-0"><span className="block font-semibold text-slate-800">모의투자 이름 직접 입력</span><span className="block text-xs leading-5 text-slate-500">리포트 이름을 바꿔도 그대로입니다. 같은 리포트로 여러 모의투자를 할 때 구분하기 좋습니다</span></span></label>
      {mode === "custom" && <div className="pl-6"><input className={inputClass} aria-label="모의투자 이름" maxLength={NAME_MAX} value={value} placeholder={`예: ${reportName} · 시가총액 비교`} autoFocus onChange={(e) => { setValue(e.target.value); setError("") }} />{error && <p className="mt-1.5 text-xs font-medium text-red-600">{error}</p>}</div>}
    </fieldset>
  )
}

export function PaperNameDialog({ paperId, name, close, saved }: { paperId: string; name: ProposedPaperName; close: () => void; saved: () => void }) {
  const svc = useService()
  const [mode, setMode] = useState<NameMode>(name.mode)
  const [value, setValue] = useState(name.mode === "custom" ? name.name_ko : "")
  const [error, setError] = useState("")
  const [busy, setBusy] = useState(false)
  const save = async () => {
    if (mode === "custom" && !value.trim()) { setError(emptyNameError); return }
    setBusy(true)
    try { await svc.setPaperName!(paperId, mode === "linked" ? { mode } : { mode, name_ko: value.trim() }); saved(); close() } catch (e) { setError(errorMessage(e)) } finally { setBusy(false) }
  }
  return (
    <Dialog title="모의투자 이름 바꾸기" close={close}>
      <form className="space-y-4 p-4 text-sm text-slate-700 sm:p-6" onSubmit={(e) => { e.preventDefault(); void save() }}>
        <PaperNameChoice reportName={name.report_name_ko} mode={mode} setMode={setMode} value={value} setValue={setValue} error={error} setError={setError} />
        {error && mode === "linked" && <Alert tone="error" title="저장하지 못했습니다">{error}</Alert>}
        <p className="text-xs text-slate-500">이름만 바뀌고 모의투자 기록·설정은 그대로입니다.{svc.mode === "mock" && " 목업 화면에서만 바뀌고 실제 서버에는 저장하지 않습니다."}</p>
        <div className="flex justify-end gap-2"><Button variant="ghost" onClick={close}>취소</Button><Button type="submit" disabled={busy}>{busy ? "저장하는 중…" : "저장"}</Button></div>
      </form>
    </Dialog>
  )
}
