import { useState } from "react"
import { useService } from "../../app/providers"
import { navigate } from "../../app/router"
import { errorMessage } from "../../api/client"
import { Alert, Button, SidePanel, inputClass } from "../../ui"

/** 리포트 → 자연어 수정 요청. 텍스트만 보내고, 어떤 조건이 바뀌는지는 다음 화면(조건 확인)에서 코드가 검증한 결과로 보여 준다. */
export function RevisionPanel({ reportId, close }: { reportId: string; close: () => void }) {
  const svc = useService()
  const [text, setText] = useState("")
  const [busy, setBusy] = useState(false)
  const [err, setErr] = useState<string | null>(null)
  const send = async () => {
    setBusy(true); setErr(null)
    try { const st = await svc.createRevision(reportId, text.trim()); close(); navigate({ page: "clarify", requestId: st.request_id }) } catch (e) { setErr(errorMessage(e)) } finally { setBusy(false) }
  }
  return (
    <SidePanel title="조건 수정 요청" close={close}>
      <div className="space-y-4 text-sm text-slate-700">
        <p>이 리포트를 바탕으로 바꾸고 싶은 점을 말로 적어 주세요. 예: “엔비디아(NVDA)는 빼 주세요”, “종목 수를 10개로”, “한 종목 비중은 12%까지만”, “선정 기준을 퀄리티로”.</p>
        <p className="text-xs text-slate-500">공정한 비교를 위해 백테스트 기간·투자금·적립·비교지수·리밸런싱·종목 범위는 원안과 같게 둡니다. 그 조건을 바꾸려면 홈에서 새 분석을 시작해 주세요.</p>
        <textarea className={`${inputClass} min-h-32`} value={text} onChange={(e) => setText(e.target.value)} placeholder="바꾸고 싶은 점을 적어 주세요" />
        {err && <Alert tone="error" title="보내지 못했습니다">{err}</Alert>}
        <div className="flex justify-end gap-2"><Button variant="ghost" onClick={close}>취소</Button><Button onClick={send} disabled={busy || text.trim().length < 3}>{busy ? "해석하는 중…" : "변경 초안 보기"}</Button></div>
      </div>
    </SidePanel>
  )
}
