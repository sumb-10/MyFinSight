import { useEffect, useState } from "react"
import { useService } from "../../app/providers"
import { navigate } from "../../app/router"
import { errorMessage } from "../../api/client"
import type { DialogState } from "../../api/types"
import { usePolling } from "../../state/usePolling"
import { saveUi } from "../../state/uiStorage"
import { Button } from "../../ui"
import { ko } from "../../lib/format"
import { ActionError, FlowHeader, FlowSteps, IdeaPart, IdeaPending, LEFT_NOTE, startNewWith } from "./flow"

/** 서버가 새 요청의 번호만 먼저 돌려주고(state=interpreting) 해석·첫 질문은 뒤에서 할 때의 질문 화면.
 *  2초마다 다시 읽어 끝나면 onDone 으로 넘긴다 (질문 중이면 질문, 끝났으면 확인 화면으로). 주소에 번호가 있으므로
 *  새로고침·재접속해도 이 화면이 이어서 기다린다. 해석이 실패(failed)했으면 이유와 「다시 시도」(같은 아이디어·조건으로 새 요청). */
export function Interpreting({ requestId, st, onDone }: { requestId: string; st: DialogState; onDone: (next: DialogState) => void }) {
  const svc = useService()
  const waiting = st.state === "interpreting"
  const poll = usePolling(() => svc.getRequest(requestId), { intervalMs: 2000, until: (d: DialogState) => d.state !== "interpreting", enabled: waiting }, [svc, requestId, waiting])
  useEffect(() => { if (poll.data && poll.data.state !== "interpreting") onDone(poll.data) }, [poll.data])  // eslint-disable-line react-hooks/exhaustive-deps -- 새 응답이 올 때만
  const [resending, setResending] = useState(false)
  const [resendErr, setResendErr] = useState("")
  const resend = async () => {
    setResending(true); setResendErr("")
    try {
      const next = await svc.createRequest({ idea: st.idea, mode: "new", overrides: st.overrides ?? {} })
      saveUi({ activeRequestId: next.request_id })
      navigate({ page: "clarify", requestId: next.request_id })
    } catch (e) { setResendErr(errorMessage(e)) } finally { setResending(false) }
  }
  return (
    <div className="mx-auto max-w-4xl space-y-8">
      <FlowHeader eyebrow={`${ko(st.mode)} · 조건 확인`} title="부족한 조건을 함께 정합니다" desc="분석 모델이 아이디어를 해석한 뒤, 결과가 달라질 항목만 묻습니다. 해석하는 동안 화면을 닫거나 새로고침해도 이 요청은 이어서 처리됩니다." />
      <FlowSteps current={0} />
      {waiting ? <IdeaPending /> : (
        <div className="space-y-3">
          <ActionError title="아이디어를 해석하지 못했습니다" message={st.error_ko ?? "서버에서 요청을 처리하지 못했습니다."} retry={resending ? undefined : () => void resend()} />
          {resendErr && <ActionError title="다시 보내지 못했습니다" message={resendErr} />}
          <Button variant="ghost" onClick={() => startNewWith(st.idea, st.overrides, LEFT_NOTE)} disabled={resending}>아이디어 고쳐서 다시 쓰기</Button>
        </div>
      )}
      <IdeaPart st={st} />
    </div>
  )
}
