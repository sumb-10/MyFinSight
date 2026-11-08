import { useEffect, useState } from "react"
import { MessageSquareText, SlidersHorizontal } from "lucide-react"
import { useProfile, useService } from "../../app/providers"
import { navigate } from "../../app/router"
import { errorMessage } from "../../api/client"
import type { DialogState, Question } from "../../api/types"
import { useResource } from "../../state/useResource"
import { Alert, Badge, Button, EmptyState, ErrorState, Loading, inputClass } from "../../ui"
import { ko } from "../../lib/format"
import { RevisionCard } from "./RevisionCard"
import { DetailConditionsDialog, OVERRIDE_LABELS, overrideText } from "../home/DetailConditions"
import { Part } from "../profile/parts"
import { ActionError, AllConditions, AnsweredList, BackToQuestions, CancelRequestButton, CancelRequestConfirm, ChangedConditions, FlowHeader, FlowSteps, IdeaPart, KIND_HELP, LLM_DETAIL, NOTE_BUTTON, NOTE_DESC, NOTE_UNSENT, Pending, ResultNote, diffRows, keepPendingNote, pendingNote, startNewWith, useFlowNotice, useLeaveRequest, type RowChange } from "./flow"
import type { ProposedMessageResult } from "../../api/proposed"
import { BatchQuestions, BatchResult, type Submitted } from "./BatchQuestions"
import { MessageOutcome } from "./MessageOutcome"

type Busy = "" | "answer" | "skip" | "message" | "overrides"
const PENDING: Record<Exclude<Busy, "">, string> = {
  answer: "답변을 반영하고 다음 질문을 준비하고 있습니다.", skip: "기본값으로 두고 다음 질문을 준비하고 있습니다.",
  message: "추가 요청을 처리하고 있습니다.", overrides: "투자 조건 변경 요청을 처리하고 있습니다.",
}
const optionPatch = (patch: Record<string, unknown> | null | undefined) => Object.entries(patch ?? {}).map(([k, v]) => `${OVERRIDE_LABELS[k] ?? k} → ${overrideText(k, v)}`).join(" · ")

export function ClarifyScreen({ requestId }: { requestId: string }) {
  const svc = useService()
  const { profile } = useProfile()
  const res = useResource(() => svc.getRequest(requestId), [svc, requestId])
  const [st, setSt] = useState<DialogState | null>(null)
  const [busy, setBusy] = useState<Busy>("")
  const [qErr, setQErr] = useState<{ message: string; retry: () => void } | null>(null)
  const [toolErr, setToolErr] = useState<{ kind: "message" | "overrides"; message: string; retry: () => void } | null>(null)
  const [result, setResult] = useState<{ kind: "message" | "overrides"; changes: RowChange[] } | null>(null)
  const [text, setText] = useState("")
  const [note, setNote] = useState(() => pendingNote(requestId))
  const [noteHint, setNoteHint] = useState("")
  useEffect(() => { keepPendingNote(requestId, note) }, [requestId, note])
  const [qHint, setQHint] = useState("")
  const [picked, setPicked] = useState<unknown>(undefined)
  const [editing, setEditing] = useState(false)
  const batchMode = !!(svc.getQuestionBatch && svc.answerBatch)  // 제안 기능: 여러 질문 한 번에 (목업에서만)
  const [batchDone, setBatchDone] = useState<{ sent: Submitted[]; changes: RowChange[] } | null>(null)
  const [msgs, setMsgs] = useState<ProposedMessageResult[] | null>(null)  // 제안 기능: 말로 보태기 처리 결과 (목업에서만)
  const leave = useLeaveRequest(requestId, st)  // 취소·아이디어 고쳐 다시 시작: 요청을 닫고 아이디어·조건을 홈에 채워 둔다
  const notice = useFlowNotice(requestId)        // 확인 화면에서 바꾼 것 때문에 돌아왔으면 그 이유
  useEffect(() => { if (res.data) setSt(res.data) }, [res.data])
  useEffect(() => { const q0 = st?.question; if (q0 && q0.options.length === 1) setPicked(q0.options[0].value) }, [st?.question?.seq])  // eslint-disable-line react-hooks/exhaustive-deps -- 보기가 하나면 미리 고른다
  useEffect(() => {
    if (!st) return
    if ((st.state === "ready" || st.state === "confirmed") && !batchDone) navigate({ page: "confirm", requestId })  // 한 번에 답했으면 반영 결과를 먼저 보여 준다
  }, [st, requestId, batchDone])

  if (res.status === "loading" && !st) return <Loading label="요청을 불러오는 중…" />
  if (res.status === "error" && !st) return <ErrorState message={res.error ?? ""} retry={res.reload} />
  if (!st) return null
  if (st.status === "cancelled") return <EmptyState title="취소된 요청입니다" description="이 요청은 취소되어 더 진행할 수 없습니다. 같은 아이디어와 조건으로 새 요청을 시작할 수 있습니다." action={<div className="flex gap-2"><Button onClick={() => startNewWith(st.idea, st.overrides)}>같은 조건으로 새 요청</Button><Button variant="ghost" onClick={() => navigate({ page: "home" })}>홈으로</Button></div>} />

  const q = st.question
  const rows = st.conditions ?? []
  const locked = busy !== "" || leave.busy
  /** 요청 하나 실행. 성공한 동작의 입력만 비우고, 실패하면 입력을 남긴 채 원인과 다시 시도를 보여 준다. */
  const act = (kind: Exclude<Busy, "">, fn: () => Promise<DialogState>) => {
    const run = async () => {
      setBusy(kind); setQErr(null); setToolErr(null); setResult(null); setQHint("")
      try {
        const next = await fn()
        if (kind === "answer" || kind === "skip") { setText(""); setPicked(undefined) }
        if (kind === "message") setNote("")
        if (kind === "message" || kind === "overrides") setResult({ kind, changes: diffRows(rows, next.conditions ?? []) })
        setSt(next)
      } catch (e) {
        if (kind === "answer" || kind === "skip") setQErr({ message: errorMessage(e), retry: run })
        else setToolErr({ kind, message: errorMessage(e), retry: run })
      } finally { setBusy("") }
    }
    void run()
  }
  const submit = () => {
    if (!q) return
    if (picked !== undefined) return act("answer", () => svc.answer(requestId, q.seq, { option_value: picked }))
    if (text.trim()) return act("answer", () => svc.answer(requestId, q.seq, { free_text: text.trim() }))
    setQHint("선택지를 고르거나 답을 적어 주세요.")
  }
  const sendNote = () => {
    if (!note.trim()) { setNoteHint("보탤 내용을 적어 주세요."); return }
    act("message", async () => { const next = await svc.sendMessage(requestId, note.trim()); if (svc.getMessageResults) setMsgs(await svc.getMessageResults(requestId)); return next })
  }
  const applyOverrides = (o: Record<string, unknown>) => {
    // 폼이 돌려준 값(프로필과 다른 것만) + 이전에 바꿨다가 이번에 프로필 값으로 돌린 것은 null 로 지운다
    const prev = st.overrides ?? {}
    const merged: Record<string, unknown> = { ...o }
    for (const k of Object.keys(prev)) if (!(k in o)) merged[k] = null
    act("overrides", () => svc.updateOverrides(requestId, merged))
  }
  const answeredN = st.questions.filter((x) => x.answered_at).length
  const editBtn = profile ? <Button variant="secondary" className="shrink-0 whitespace-nowrap" onClick={() => setEditing(true)} disabled={locked}><SlidersHorizontal className="size-4" />{busy === "overrides" ? "변경 처리 중…" : "조건 바꾸기"}</Button> : undefined

  return (
    <div className="mx-auto max-w-4xl space-y-8">
      <FlowHeader eyebrow={`${ko(st.mode)} · 조건 확인`} title="부족한 조건을 함께 정합니다" desc={`분석 모델이 아이디어를 해석하고, 결과가 달라질 항목만 ${batchMode ? "골라 한 번에" : "하나씩"} 묻습니다. 답하지 않은 조건은 기본 투자조건을 그대로 씁니다.`}
        action={<CancelRequestButton c={leave} disabled={busy !== ""} />} />
      <CancelRequestConfirm c={leave} keepLabel="계속 답하기" disabled={busy !== ""} />
      <FlowSteps current={0} />
      {notice && st.state !== "ready" && <BackToQuestions n={notice} hardErrors={st.hard_errors.length > 0} />}
      <IdeaPart st={st} />
      {st.revision && <RevisionCard rev={st.revision} />}
      {st.hard_errors.length > 0 && (
        <Alert title="입력 조건에 오류가 있어 먼저 수정이 필요합니다" tone="error">
          <ul className="list-disc pl-5">{st.hard_errors.map((e) => <li key={e.field}>{e.message_ko}</li>)}</ul>
          <div className="mt-3 flex flex-wrap items-center gap-2">{profile && <Button variant="secondary" onClick={() => setEditing(true)} disabled={locked}>이번 조건 고치기</Button>}<Button variant="ghost" onClick={() => void leave.leave()} disabled={locked}>조건 그대로 새 요청</Button></div>
          <p className="mt-2 text-xs">기본 투자조건(내 투자조건)을 바꿔도 진행 중인 이 요청에는 적용되지 않습니다.</p>
        </Alert>
      )}
      {st.state === "blocked" && (
        <Alert title={`보충 질문 ${st.max_questions}개를 모두 썼지만 정해지지 않은 항목이 남았습니다`} tone="warning">
          <ul className="list-disc pl-5">{st.unresolved.map((u) => <li key={u.field}><b>{u.label_ko}</b>: {u.hint_ko}{u.examples_ko.length ? ` (예: ${u.examples_ko.join(", ")})` : ""}</li>)}</ul>
          <p className="mt-2">남은 항목은 「조건 바꾸기」로 직접 정하거나, 아이디어를 수정해 다시 시작해 주세요. 분석은 시작되지 않았습니다.</p>
          <div className="mt-3 flex gap-2">{profile && <Button variant="secondary" onClick={() => setEditing(true)} disabled={locked}>조건 바꾸기</Button>}<Button variant="ghost" onClick={() => void leave.leave()} disabled={locked}>아이디어 고쳐 다시 시작</Button></div>
        </Alert>
      )}
      {batchDone && <BatchResult requestId={requestId} sent={batchDone.sent} changes={batchDone.changes} />}
      {batchMode && st.state === "asking" && st.hard_errors.length === 0 && <BatchQuestions requestId={requestId} st={st} onDone={(next, sent) => { setResult(null); setBatchDone({ sent, changes: diffRows(rows, next.conditions ?? []) }); setSt(next) }} />}
      {!batchMode && st.state === "asking" && st.hard_errors.length === 0 && (
        <Part title="추가 점검 질문" desc={`${q ? `${answeredN + 1}번째 질문입니다. ` : ""}지금까지 ${answeredN}개에 답했습니다. 질문은 최대 ${st.max_questions}개까지이며, 남은 질문 수는 답에 따라 달라집니다.`}>
          {q ? <QuestionBody q={q} st={st} picked={picked} text={text} locked={locked} onPick={(v) => { setPicked(v); setText(""); setQHint("") }} onText={(t) => { setText(t); setPicked(undefined); setQHint("") }} />
            : busy === "" && <div className="flex flex-wrap items-center justify-between gap-3 rounded-xl bg-slate-50 p-4 text-sm text-slate-600"><span>지금 표시할 질문이 없습니다.</span><Button variant="secondary" onClick={() => { setSt(null); res.reload() }}>최신 상태 불러오기</Button></div>}
          {(busy === "answer" || busy === "skip") && <Pending title={PENDING[busy]} detail={LLM_DETAIL} />}
          {qHint && <p className="text-xs font-medium text-red-600">{qHint}</p>}
          {qErr && !locked && <ActionError title="답변을 반영하지 못했습니다" message={qErr.message} retry={qErr.retry} />}
          {q && (
            <div className="flex flex-col-reverse gap-2 border-t border-slate-100 pt-4 sm:flex-row sm:items-center sm:justify-between">
              <Button variant="ghost" onClick={() => act("skip", () => svc.skip(requestId, q.seq))} disabled={locked}>답하지 않음 (기본값 사용)</Button>
              <Button onClick={submit} disabled={locked}>{busy === "answer" ? "반영하는 중…" : "답변 보내기"}</Button>
            </div>
          )}
        </Part>
      )}
      <ChangedConditions rows={rows} base="기본 투자조건" action={editBtn}>
        {busy === "overrides" && <Pending title={PENDING.overrides} detail={LLM_DETAIL} />}
        {toolErr?.kind === "overrides" && !locked && <ActionError title="조건을 바꾸지 못했습니다" message={toolErr.message} retry={toolErr.retry} />}
        {result?.kind === "overrides" && !locked && <ResultNote changes={result.changes} what="조건 변경" />}
      </ChangedConditions>
      <AllConditions rows={rows} base="기본 투자조건" />
      {!batchDone && <AnsweredList questions={st.questions} />}  {/* 한 번에 보낸 직후(목업)에는 「보낸 답변과 반영 결과」와 겹쳐 숨긴다. 최종 확인 화면·일반 모드는 그대로 */}
      <Part title="말로 조건 보태기" tag="선택" desc={NOTE_DESC}>
        <textarea className={`${inputClass} min-h-16`} value={note} onChange={(e) => { setNote(e.target.value); setNoteHint("") }} placeholder="예: 배당주 위주로 / 종목은 8개만" readOnly={locked} aria-label="말로 조건 보태기" />
        {note.trim() && busy !== "message" && <p className="text-xs font-medium text-amber-800">{NOTE_UNSENT}</p>}
        {noteHint && <p className="text-xs font-medium text-red-600">{noteHint}</p>}
        {busy === "message" && <Pending title={PENDING.message} detail={LLM_DETAIL} />}
        {toolErr?.kind === "message" && !locked && <ActionError title="추가 요청을 반영하지 못했습니다" message={toolErr.message} retry={toolErr.retry} />}
        {result?.kind === "message" && !locked && (msgs ? <MessageOutcome results={msgs} /> : <ResultNote changes={result.changes} what="추가 요청" />)}
        <div className="flex justify-end"><Button variant="secondary" onClick={sendNote} disabled={locked}><MessageSquareText className="size-4" />{busy === "message" ? "반영하는 중…" : NOTE_BUTTON}</Button></div>
      </Part>
      {editing && profile && <DetailConditionsDialog profile={profile.profile} initial={st.overrides ?? {}} onApply={applyOverrides} close={() => setEditing(false)} title="이번 요청의 조건 바꾸기" applyLabel="이 조건으로 다시 해석" intro="기본 투자조건에서 가져온 값을 이번 요청에서만 바꿉니다. 적용하면 분석 모델이 바뀐 조건으로 다시 해석하고, 필요한 질문만 다시 묻습니다. 저장된 기본 투자조건은 그대로입니다." />}
    </div>
  )
}

function QuestionBody({ q, st, picked, text, locked, onPick, onText }: { q: Question; st: DialogState; picked: unknown; text: string; locked: boolean; onPick: (v: unknown) => void; onText: (t: string) => void }) {
  const pc = st.precheck
  return (
    <div className="space-y-4">
      <div>
        <p className="flex flex-wrap items-center gap-2 text-xs text-slate-500"><Badge tone="slate">{ko(q.kind)}</Badge>관련 항목: {q.field_label_ko ?? ko(q.field)}</p>
        <h3 className="mt-2 text-lg font-bold leading-7 text-slate-950">{q.question_ko}</h3>
        <p className="mt-1 text-xs leading-5 text-slate-500">{q.why_ko || KIND_HELP[q.kind]}</p>
      </div>
      {q.kind === "feasibility" && pc && (
        <div className="rounded-xl bg-slate-50 p-3 text-xs leading-5 text-slate-700">
          <p>필요한 최소 종목 수 <b>{pc.min}개</b> · 분석 기준일({pc.as_of.date}) 기준 고를 수 있는 후보 <b>{pc.as_of.n_with_metric}개</b> · 백테스트 시작일({pc.start.date}) 기준 <b>{pc.start.n_with_metric}개</b></p>
          {pc.feasible_start && <p>백테스트를 {pc.feasible_start.date}부터 시작하면({pc.feasible_start.years}년) 후보 {pc.feasible_start.n_with_metric}개로 분석할 수 있습니다.</p>}
        </div>
      )}
      {q.options.length > 0 && (
        <div role="radiogroup" aria-label={q.question_ko} className="grid grid-cols-1 gap-2">
          {q.options.map((o, i) => {
            const on = picked === o.value
            const patch = optionPatch(o.patch)
            return (
              <button key={i} type="button" role="radio" aria-checked={on} disabled={locked} onClick={() => onPick(o.value)} className={`rounded-xl border p-3 text-left transition focus:outline-none focus:ring-2 focus:ring-blue-500 disabled:opacity-60 ${on ? "border-blue-400 bg-blue-50 ring-1 ring-blue-200" : "border-slate-200 bg-white hover:border-slate-300 hover:bg-slate-50"}`}>
                <span className={`block text-sm font-semibold ${on ? "text-blue-900" : "text-slate-800"}`}>{o.label_ko}</span>
                {patch && <span className="mt-0.5 block text-xs text-slate-500">바뀌는 조건: {patch}</span>}
              </button>
            )
          })}
        </div>
      )}
      {q.allow_free_text && (
        <label className="block">
          <span className="mb-1.5 block text-sm font-semibold text-slate-700">{q.options.length ? "또는 직접 적기" : "답변"}</span>
          <textarea className={`${inputClass} min-h-20`} value={text} onChange={(e) => onText(e.target.value)} placeholder="자유롭게 적어 주세요. 분석 모델이 해석합니다." readOnly={locked} />
        </label>
      )}
    </div>
  )
}
