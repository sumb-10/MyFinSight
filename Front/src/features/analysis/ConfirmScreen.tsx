import { useEffect, useRef, useState } from "react"
import { MessageSquareText, Play, SlidersHorizontal } from "lucide-react"
import { useProfile, useService } from "../../app/providers"
import { navigate } from "../../app/router"
import { errorMessage } from "../../api/client"
import type { DialogState } from "../../api/types"
import { useResource } from "../../state/useResource"
import { saveUi } from "../../state/uiStorage"
import { Alert, Button, EmptyState, ErrorState, Loading, inputClass } from "../../ui"
import { ko } from "../../lib/format"
import { RevisionCard } from "./RevisionCard"
import { startNewWith } from "./ClarifyScreen"
import { DetailConditionsDialog } from "../home/DetailConditions"
import { Part } from "../profile/parts"
import { ActionError, AllConditions, AnsweredList, ChangedConditions, FlowHeader, FlowSteps, IdeaPart, LLM_DETAIL, NOTE_BUTTON, NOTE_DESC, NOTE_UNSENT, Pending, ResultNote, diffRows, keepPendingNote, pendingNote, useStickyInMain, type RowChange } from "./flow"
import type { ProposedMessageResult } from "../../api/proposed"
import { MessageOutcome } from "./MessageOutcome"

type Busy = "" | "start" | "overrides" | "message"
type ActErr = { kind: Exclude<Busy, "">; message: string; retry: () => void }

export function ConfirmScreen({ requestId }: { requestId: string }) {
  const svc = useService()
  const { profile } = useProfile()
  const res = useResource(() => svc.getRequest(requestId), [svc, requestId])
  const [local, setLocal] = useState<DialogState | null>(null)  // 조건 바꾸기·말로 보태기 응답 (다시 불러오지 않고 바로 반영)
  const [busy, setBusy] = useState<Busy>("")
  const [err, setErr] = useState<ActErr | null>(null)
  const [result, setResult] = useState<{ kind: "message" | "overrides"; changes: RowChange[] } | null>(null)
  const [editing, setEditing] = useState(false)
  const [note, setNote] = useState(() => pendingNote(requestId))  // 질문 화면에서 적고 보내지 않은 문장을 이어받는다
  const [noteHint, setNoteHint] = useState("")
  const [askUnsent, setAskUnsent] = useState(false)  // 보내지 않은 추가 요청이 있는데 「분석 시작」을 눌렀을 때
  const [msgs, setMsgs] = useState<ProposedMessageResult[] | null>(null)  // 제안 기능: 말로 보태기 처리 결과 (목업에서만)
  useEffect(() => { keepPendingNote(requestId, note) }, [requestId, note])
  useStickyInMain()  // 「분석 시작」 줄
  const noteRef = useRef<HTMLDivElement>(null)
  const st = local ?? res.data
  if (res.status === "loading" && !st) return <Loading label="확정 조건을 불러오는 중…" />
  if (!st) return <ErrorState message={res.error ?? ""} retry={res.reload} />
  if (st.status === "cancelled") return <EmptyState title="취소된 요청입니다" description="이 요청은 취소되어 분석을 시작할 수 없습니다. 같은 아이디어와 조건으로 새 요청을 시작할 수 있습니다." action={<div className="flex gap-2"><Button onClick={() => startNewWith(st.idea, st.overrides)}>같은 조건으로 새 요청</Button><Button variant="ghost" onClick={() => navigate({ page: "home" })}>홈으로</Button></div>} />
  if (st.state === "asking" || st.state === "blocked") { navigate({ page: "clarify", requestId }); return null }
  if (st.status === "confirmed" && st.run_id) {
    return <Alert title="이미 분석이 시작된 요청입니다" tone="info"><Button variant="secondary" onClick={() => navigate({ page: "run", runId: st.run_id! })}>실행 상태 보기</Button></Alert>
  }
  if (!st.confirmation) return <ErrorState title="확정 조건을 만들지 못했습니다" message="조건을 바꾸거나 새 요청으로 다시 시작해 주세요." retry={res.reload} />
  const rows = st.confirmation.rows
  const unsupported = rows.filter((r) => !r.supported)
  const revision = st.mode === "revision"
  const base = revision ? "원안" : "기본 투자조건"
  const locked = busy !== ""
  const unsent = note.trim()

  const start = async () => {
    setAskUnsent(false); setBusy("start"); setErr(null)
    try {
      const { run_id } = await svc.confirm(requestId)
      saveUi({ activeRequestId: null, activeRunId: run_id })
      navigate({ page: "run", runId: run_id })
    } catch (e) { setErr({ kind: "start", message: errorMessage(e), retry: () => void start() }) } finally { setBusy("") }
  }
  const tryStart = () => { if (unsent && !revision) { setAskUnsent(true); return } void start() }
  // 조건 확인 화면에서도 조건을 바꾸거나 말로 보탤 수 있다. 바뀐 뒤 질문이 생기면 질문 화면으로 돌아간다.
  const tool = (kind: "overrides" | "message", fn: () => Promise<DialogState>) => {
    const run = async () => {
      setAskUnsent(false); setBusy(kind); setErr(null); setResult(null)
      try {
        const next = await fn()
        if (kind === "message") setNote("")
        if (next.state === "asking" || next.hard_errors.length > 0) { navigate({ page: "clarify", requestId }); return }
        setResult({ kind, changes: diffRows(rows, next.confirmation?.rows ?? []) })
        setLocal(next)
      } catch (e) { setErr({ kind, message: errorMessage(e), retry: run }) } finally { setBusy("") }
    }
    void run()
  }
  const sendNote = () => {
    if (!unsent) { setNoteHint("보탤 내용을 적어 주세요."); return }
    tool("message", async () => { const next = await svc.sendMessage(requestId, unsent); if (svc.getMessageResults) setMsgs(await svc.getMessageResults(requestId)); return next })
  }
  const applyOverrides = (o: Record<string, unknown>) => {
    const prev = st.overrides ?? {}
    const merged: Record<string, unknown> = { ...o }
    for (const k of Object.keys(prev)) if (!(k in o)) merged[k] = null
    tool("overrides", () => svc.updateOverrides(requestId, merged))
  }
  const editBtn = !revision && profile ? <Button variant="secondary" className="shrink-0 whitespace-nowrap" onClick={() => setEditing(true)} disabled={locked}><SlidersHorizontal className="size-4" />{busy === "overrides" ? "변경 처리 중…" : "조건 바꾸기"}</Button> : undefined

  return (
    <div className="mx-auto max-w-4xl space-y-8">
      <FlowHeader eyebrow={`${ko(st.mode)} · 조건 확인`} title={revision ? "이 수정안으로 분석을 시작할까요?" : "이 조건으로 분석을 시작할까요?"}
        desc={revision ? "원안의 조건에 수정 요청을 반영한 최종 조건입니다. 분석이 끝나면 원안과 비교한 결과를 볼 수 있습니다." : "기본 투자조건에 답변과 변경을 반영한 최종 조건입니다. 「분석 시작」을 누르기 전에는 분석이 실행되지 않으며, 아직 바꿀 수 있습니다."} />
      <FlowSteps current={1} />
      <IdeaPart st={st} />
      {st.revision && <RevisionCard rev={st.revision} />}
      {st.blocked_reason_ko && (
        <Alert title="보충 질문을 모두 써서 남은 항목은 지금 조건으로 둡니다" tone="info">
          <p>{st.blocked_reason_ko}</p>
          {st.unresolved.length > 0 && <ul className="mt-2 list-disc pl-5">{st.unresolved.map((u) => <li key={u.field}><b>{u.label_ko}</b>: {u.hint_ko}</li>)}</ul>}
        </Alert>
      )}
      {(st.summary.derived?.warnings?.length ?? 0) > 0 && <Alert title="계산 조건 안내" tone="warning"><ul className="list-disc pl-5">{st.summary.derived!.warnings!.map((w, i) => <li key={i}>{w}</li>)}</ul></Alert>}
      {unsupported.length > 0 && <Alert title="지원하지 않는 조건이 있어 분석을 시작할 수 없습니다" tone="error"><ul className="list-disc pl-5">{unsupported.map((r) => <li key={r.field}>{r.label_ko}: {r.note_ko}</li>)}</ul></Alert>}
      <ChangedConditions rows={rows} base={base} action={editBtn}>
        {busy === "overrides" && <Pending title="투자 조건 변경 요청을 처리하고 있습니다." detail={LLM_DETAIL} />}
        {err?.kind === "overrides" && !locked && <ActionError title="조건을 바꾸지 못했습니다" message={err.message} retry={err.retry} />}
        {result?.kind === "overrides" && !locked && <ResultNote changes={result.changes} what="조건 변경" />}
      </ChangedConditions>
      <AllConditions rows={rows} base={base} />
      <AnsweredList questions={st.questions} />
      {!revision && (
        <div ref={noteRef}><Part title="말로 조건 보태기" tag="선택" desc={NOTE_DESC}>
          <textarea className={`${inputClass} min-h-14`} value={note} onChange={(e) => { setNote(e.target.value); setNoteHint("") }} placeholder="예: 배당주 위주로 / 종목은 8개만" readOnly={locked} aria-label="말로 조건 보태기" />
          {unsent && busy !== "message" && <p className="text-xs font-medium text-amber-800">{NOTE_UNSENT}</p>}
          {noteHint && <p className="text-xs font-medium text-red-600">{noteHint}</p>}
          {busy === "message" && <Pending title="추가 요청을 처리하고 있습니다." detail={LLM_DETAIL} />}
          {err?.kind === "message" && !locked && <ActionError title="추가 요청을 반영하지 못했습니다" message={err.message} retry={err.retry} />}
          {result?.kind === "message" && !locked && (msgs ? <MessageOutcome results={msgs} /> : <ResultNote changes={result.changes} what="추가 요청" />)}
          <div className="flex justify-end"><Button variant="secondary" onClick={sendNote} disabled={locked}><MessageSquareText className="size-4" />{busy === "message" ? "반영하는 중…" : NOTE_BUTTON}</Button></div>
        </Part></div>
      )}
      {/* 「분석 시작」 줄은 화면 아래에 붙여 둔다 — 조건 표가 길어도 스크롤 끝까지 내려가지 않고 시작할 수 있게.
          시작을 눌렀을 때의 확인·등록 중·오류도 이 줄 안에 보여 준다 (화면 위쪽에서 눌러도 바로 보이게). */}
      <div className="sticky bottom-4 z-20 space-y-3 rounded-2xl border border-slate-300 bg-white px-5 py-4 shadow-lg sm:px-6">
        {askUnsent && (
          <div role="alertdialog" aria-label="반영하지 않은 추가 요청" className="rounded-xl border border-amber-300 bg-amber-50 p-4 text-sm text-amber-950">
            <p className="font-semibold">입력한 추가 요청이 아직 반영되지 않았습니다. 먼저 반영할까요?</p>
            <p className="mt-1 break-words text-amber-900">“{unsent}”</p>
            <p className="mt-1 text-xs">이대로 시작하면 이 내용은 분석에 들어가지 않습니다. 먼저 반영하면 바뀐 조건을 확인한 뒤 다시 「분석 시작」을 누르면 됩니다.</p>
            <div className="mt-3 flex flex-wrap gap-2">
              <Button onClick={() => { noteRef.current?.scrollIntoView?.({ block: "start", behavior: "smooth" }); sendNote() }}>먼저 반영하기</Button>
              <Button variant="secondary" onClick={() => { setNote(""); void start() }}>입력을 지우고 분석 시작</Button>
              <Button variant="ghost" onClick={() => setAskUnsent(false)}>닫기</Button>
            </div>
          </div>
        )}
        {busy === "start" && <Pending title="분석 요청을 대기열에 등록하고 있습니다." />}
        {err?.kind === "start" && !locked && <ActionError title="분석을 시작하지 못했습니다" message={err.message} retry={err.retry} />}
        <div className="flex flex-col gap-3 sm:flex-row sm:items-center sm:justify-between">
          <p className="text-xs leading-5 text-slate-500">{unsupported.length > 0 ? "지원하지 않는 조건을 바꿔야 분석을 시작할 수 있습니다." : locked && busy !== "start" ? "요청을 처리하는 동안에는 시작할 수 없습니다." : "시작하면 분석 대기열에 등록되고, 진행 화면에서 단계별 상태를 볼 수 있습니다. 시작한 뒤에는 조건을 바꿀 수 없습니다."}</p>
          <Button onClick={tryStart} disabled={locked || unsupported.length > 0}><Play className="size-4" />{busy === "start" ? "대기열에 등록 중…" : "분석 시작"}</Button>
        </div>
      </div>
      {editing && profile && <DetailConditionsDialog profile={profile.profile} initial={st.overrides ?? {}} onApply={applyOverrides} close={() => setEditing(false)} title="이번 요청의 조건 바꾸기" applyLabel="이 조건으로 다시 확인" intro="기본 투자조건에서 가져온 값을 이번 요청에서만 바꿉니다. 적용하면 분석 모델이 바뀐 조건으로 다시 해석하고, 필요한 질문만 다시 묻습니다. 저장된 기본 투자조건은 그대로입니다." />}
    </div>
  )
}
