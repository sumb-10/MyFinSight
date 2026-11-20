import { useEffect, useRef, useState, type ReactNode } from "react"
import { SlidersHorizontal, X } from "lucide-react"
import { useProfile, useService } from "../../app/providers"
import { navigate } from "../../app/router"
import { errorMessage } from "../../api/client"
import type { DialogState, Question } from "../../api/types"
import type { ProposedMessageResult } from "../../api/proposed"
import type { Resource } from "../../state/useResource"
import { usePolling } from "../../state/usePolling"
import { saveUi } from "../../state/uiStorage"
import { ko } from "../../lib/format"
import { MockTag } from "../report/proposedView"
import { DetailConditionsDialog, OVERRIDE_LABELS, overrideText } from "./DetailConditions"
import { CancelRequestConfirm, KIND_HELP, LEFT_NOTE, NOTE_BUTTON, NOTE_UNSENT, ProgressList, carryNoteResult, diffRows, keepPendingNote, pendingNote, startNewWith, useFlowNotice, useLeaveRequest, type RowChange } from "../analysis/flow"
import { BotSays, CHAT_MAIN, CHAT_QUIET, Dots, ElapsedNote, ISay, Typing } from "./chatParts"

/**
 * 새 분석 요청 하나의 상태 (홈 대화창용). 서버가 뒤에서 해석하는 동안(interpreting)은 2초마다 다시 읽고,
 * 다 정해지면(ready) 조건 확인 화면으로 넘어간다. requestId 가 없으면(아이디어를 적는 홈) 아무것도 하지 않는다.
 */
export function useRequestDialog(requestId: string | undefined, res: Resource<DialogState> | undefined) {
  const svc = useService()
  const [st, setSt] = useState<DialogState | null>(null)
  useEffect(() => { if (res?.data) setSt(res.data) }, [res?.data])
  const waiting = !!requestId && st?.state === "interpreting"
  const poll = usePolling(() => svc.getRequest(requestId!), { intervalMs: 2000, until: (d: DialogState) => d.state !== "interpreting", enabled: waiting }, [svc, requestId, waiting])
  useEffect(() => { if (poll.data) setSt(poll.data) }, [poll.data])
  useEffect(() => {
    if (requestId && st && st.status !== "cancelled" && (st.state === "ready" || st.state === "confirmed")) navigate({ page: "confirm", requestId })
  }, [st, requestId])
  return { st, setSt }
}

type Busy = "" | "answer" | "skip" | "message" | "overrides"
// 기다림 문구: ChatGPT·Claude 처럼 두세 단어 (2026-11-18 사용자 요청, 긴 문장은 읽기 부담)
const WAIT: Record<Exclude<Busy, "">, string> = { answer: "답변 반영 중…", skip: "다음 질문 준비 중…", message: "보탠 말 반영 중…", overrides: "조건 다시 확인 중…" }
const OUTCOME = { applied: "반영했어요", not_applied: "반영하지 못했어요", needs_confirmation: "확인이 더 필요해요" } as const
const HEAD_BTN = "inline-flex h-8 items-center gap-1.5 rounded-chip px-2.5 text-13 font-medium text-sub transition enabled:hover:bg-sunken enabled:hover:text-main disabled:opacity-50"
const optionPatch = (patch: Record<string, unknown> | null | undefined) => Object.entries(patch ?? {}).map(([k, v]) => `${OVERRIDE_LABELS[k] ?? k} → ${overrideText(k, v)}`).join(" · ")

/** 바뀐 조건 목록 (말풍선 안) */
function Changes({ list }: { list: { label: string; before: string; after: string }[] }) {
  return <ul className="mt-1.5 space-y-0.5 text-13">{list.map((c) => <li key={c.label}>{c.label}: <span className="text-sub">{c.before}</span> → <b className="font-semibold">{c.after}</b></li>)}</ul>
}

/**
 * 홈 왼쪽 카드의 대화창 (새 분석 요청이 있을 때): 내 아이디어 → 분석 모델의 해석 → 질문과 내 답 → 말로 보탠 문장과 결과.
 * 질문은 하나씩 묻고 보기를 누르면 바로 보낸다. 아래 입력창은 「말로 보태기」. 머리의 「조건 바꾸기」·「취소」.
 * 동작은 기존 질문 화면(features/analysis/ClarifyScreen.tsx)과 같고, 모양만 대화형이다. 최종 조건 확인은 따로 있는 확인 화면에서.
 */
export function RequestChat({ requestId, st, setSt, res }: { requestId: string; st: DialogState | null; setSt: (s: DialogState) => void; res: Resource<DialogState> }) {
  const svc = useService()
  const { profile } = useProfile()
  const [busy, setBusy] = useState<Busy>("")
  const [sent, setSent] = useState("")  // 보냈지만 아직 답이 오지 않은 내 말
  const [err, setErr] = useState<{ kind: Exclude<Busy, "">; message: string; retry: () => void } | null>(null)
  const [result, setResult] = useState<{ kind: "message" | "overrides"; changes: RowChange[] } | null>(null)
  const [text, setText] = useState("")       // 질문에 직접 적는 답
  const [qHint, setQHint] = useState("")
  const [note, setNote] = useState(() => pendingNote(requestId))
  const [noteHint, setNoteHint] = useState("")
  useEffect(() => { keepPendingNote(requestId, note) }, [requestId, note])
  const [editing, setEditing] = useState(false)
  const [msgs, setMsgs] = useState<ProposedMessageResult[]>([])  // 제안 기능: 말로 보태기 처리 결과 (getMessageResults 가 있을 때)
  const [resending, setResending] = useState(false)
  const [resendErr, setResendErr] = useState("")
  const leave = useLeaveRequest(requestId, st)
  const notice = useFlowNotice(requestId)  // 조건 확인 화면에서 바꾼 것 때문에 돌아왔으면 그 이유
  const scroller = useRef<HTMLDivElement>(null)

  const settled = !!st && st.state !== "interpreting"
  useEffect(() => {
    if (!settled || !svc.getMessageResults) return
    let alive = true
    svc.getMessageResults(requestId).then((r) => { if (alive) setMsgs(r) }, () => { /* 결과를 못 읽으면 대화에서만 빠진다 */ })
    return () => { alive = false }
  }, [svc, requestId, settled])
  // 새 말풍선이 생기면 대화 영역만 맨 아래로 (페이지는 움직이지 않는다)
  useEffect(() => {
    const el = scroller.current
    if (!el) return
    const reduce = window.matchMedia?.("(prefers-reduced-motion: reduce)").matches
    el.scrollTo?.({ top: el.scrollHeight, behavior: reduce ? "auto" : "smooth" })
  }, [st, busy, msgs.length, result, err, leave.asking])

  const rows = st?.conditions ?? []
  const locked = busy !== "" || leave.busy
  /** 요청 하나 실행. 성공한 동작의 입력만 비우고, 실패하면 입력을 남긴 채 원인과 다시 시도를 보여 준다 (질문 화면 act 와 같은 규칙) */
  const act = (kind: Exclude<Busy, "">, said: string, fn: () => Promise<DialogState>) => {
    const run = async () => {
      setBusy(kind); setSent(said); setErr(null); setResult(null); setQHint("")
      try {
        const next = await fn()
        if (kind === "answer" || kind === "skip") setText("")
        if (kind === "message") setNote("")
        if (kind === "message" || kind === "overrides") setResult({ kind, changes: diffRows(rows, next.conditions ?? []) })
        setSt(next)
      } catch (e) { setErr({ kind, message: errorMessage(e), retry: run }) } finally { setBusy(""); setSent("") }
    }
    void run()
  }
  const answer = (q: Question, value: unknown, label: string) => act("answer", label, () => svc.answer(requestId, q.seq, { option_value: value }))
  const answerText = (q: Question) => {
    if (!text.trim()) { setQHint("답을 적어 주세요."); return }
    act("answer", text.trim(), () => svc.answer(requestId, q.seq, { free_text: text.trim() }))
  }
  const sendNote = () => {
    if (!note.trim()) { setNoteHint("보탤 내용을 적어 주세요."); return }
    act("message", note.trim(), async () => {
      const next = await svc.sendMessage(requestId, note.trim())
      const results = svc.getMessageResults ? await svc.getMessageResults(requestId) : null
      if (results) setMsgs(results)
      // 더 물을 것이 없으면 곧바로 확인 화면으로 넘어간다 → 결과를 확인 화면이 이어서 보여 주도록 넘긴다
      if (next.state === "ready") carryNoteResult(requestId, { changes: diffRows(rows, next.conditions ?? []), results })
      return next
    })
  }
  const applyOverrides = (o: Record<string, unknown>) => {
    // 폼이 돌려준 값(프로필과 다른 것만) + 이전에 바꿨다가 이번에 프로필 값으로 돌린 것은 null 로 지운다
    const prev = st?.overrides ?? {}
    const merged: Record<string, unknown> = { ...o }
    for (const k of Object.keys(prev)) if (!(k in o)) merged[k] = null
    act("overrides", "조건을 바꿔 주세요", () => svc.updateOverrides(requestId, merged))
  }
  /** 해석이 실패했을 때: 같은 아이디어·조건으로 새 요청 */
  const resend = async () => {
    if (!st) return
    setResending(true); setResendErr("")
    try {
      const next = await svc.createRequest({ idea: st.idea, mode: "new", overrides: st.overrides ?? {} })
      saveUi({ activeRequestId: next.request_id })
      navigate({ page: "clarify", requestId: next.request_id })
    } catch (e) { setResendErr(errorMessage(e)) } finally { setResending(false) }
  }

  const draft = !!st && st.status === "draft"
  const open = draft && (st.state === "asking" || st.state === "blocked")
  const q = st?.question ?? null
  const answeredN = st?.questions.filter((x) => x.answered_at).length ?? 0
  const showQuestion = !!st && draft && st.state === "asking" && st.hard_errors.length === 0 && !!q && busy !== "answer" && busy !== "skip"

  // 지난 대화: 답한 질문과 말로 보탠 문장을 시간순으로
  const history: { at: string; key: string; node: ReactNode }[] = []
  for (const x of st?.questions ?? []) {
    if (!x.answered_at) continue
    history.push({ at: x.answered_at, key: `q${x.seq}`, node: <><BotSays>{x.question_ko}</BotSays><ISay>{x.skipped ? "답하지 않음 (기본값 사용)" : x.answer ?? x.free_text ?? ""}</ISay></> })
  }
  msgs.forEach((m, i) => history.push({ at: m.at, key: `m${i}`, node: <>
    <ISay>{m.text}</ISay>
    <BotSays tone={m.outcome === "needs_confirmation" ? "warn" : "plain"}>
      <p className="flex flex-wrap items-center font-semibold">{OUTCOME[m.outcome]}<MockTag /></p>
      {m.outcome === "applied" && m.changes.length > 0 && <Changes list={m.changes.map((c) => ({ label: c.label_ko, before: c.before_ko, after: c.after_ko }))} />}
      {m.note_ko && <p className="mt-1 text-13 text-body">{m.note_ko}</p>}
    </BotSays>
  </> }))
  history.sort((a, b) => a.at.localeCompare(b.at))

  return (
    <section aria-labelledby="home-new" className="flex h-[clamp(34rem,calc(100vh-9.5rem),60rem)] min-w-0 flex-col rounded-card bg-surface">
      <div className="flex items-center justify-between border-b border-line px-6 py-3.5">
        <h1 id="home-new" className="t-title">새 분석</h1>
        <div className="flex gap-0.5">
          {open && profile && <button type="button" onClick={() => setEditing(true)} disabled={locked} className={HEAD_BTN}><SlidersHorizontal className="size-4" aria-hidden />조건 바꾸기</button>}
          {draft && st.state !== "interpreting" && <button type="button" onClick={leave.ask} disabled={locked || leave.asking} className={HEAD_BTN}><X className="size-4" aria-hidden />취소</button>}
        </div>
      </div>

      <div ref={scroller} className="min-h-0 flex-1 overflow-y-auto overscroll-contain px-5 py-4">
        <ol aria-label="분석 모델과의 대화" aria-live="polite" className="mx-auto flex min-h-full w-full max-w-[760px] flex-col justify-end gap-3">
          {st && <ISay>{st.idea}</ISay>}
          {!st && res.status !== "error" && <Typing label="불러오는 중…" />}
          {!st && res.status === "error" && (
            <BotSays tone="error"><p className="font-semibold">요청을 불러오지 못했어요</p><p className="text-13 text-body">{res.error}</p><button type="button" onClick={res.reload} className={`${CHAT_QUIET} mt-2`}>다시 시도</button></BotSays>
          )}

          {st?.state === "interpreting" && (
            <BotSays>
              <p className="flex items-center gap-2.5"><Dots /><span role="status" className="font-semibold">아이디어를 해석하고 있어요</span></p>
              <p className="text-13 text-body">해석이 끝나면 바로 질문이 이어집니다. 화면을 닫아도 요청은 이어서 처리돼요.</p>
              <ElapsedNote doing="해석" />
              {st.progress?.length ? <ProgressList steps={st.progress} /> : null}
            </BotSays>
          )}
          {st?.state === "failed" && (
            <BotSays tone="error">
              <p className="font-semibold">아이디어를 해석하지 못했어요</p>
              <p className="text-13 text-body">{st.error_ko ?? "서버에서 요청을 처리하지 못했습니다."}</p>
              {st.progress?.some((s) => s.status !== "waiting") && <ProgressList steps={st.progress} stopped />}
              {resendErr && <p className="mt-1 text-13 text-danger">다시 보내지 못했어요: {resendErr}</p>}
              <div className="mt-2 flex flex-wrap gap-2">
                <button type="button" onClick={() => void resend()} disabled={resending} className={CHAT_MAIN}>{resending ? "다시 보내는 중…" : "다시 시도"}</button>
                <button type="button" onClick={() => startNewWith(st.idea, st.overrides, LEFT_NOTE)} disabled={resending} className={CHAT_QUIET}>아이디어 고쳐서 다시 쓰기</button>
              </div>
            </BotSays>
          )}

          {settled && st!.summary.interpretation_summary_ko && (
            <BotSays>
              <p className="t-label">이렇게 이해했어요</p>
              <p className="mt-0.5">{st!.summary.interpretation_summary_ko}</p>
              {st!.summary.themes.length > 0 && <p className="mt-2 flex flex-wrap gap-1.5">{st!.summary.themes.map((t) => <span key={t.id} className="rounded-full bg-surface px-2.5 py-0.5 text-12 font-semibold text-body">{t.label_ko}</span>)}</p>}
            </BotSays>
          )}
          {notice && st?.state !== "ready" && (
            <BotSays tone="warn">
              <p className="font-semibold">방금 {notice.what} 때문에 분석 전에 다시 확인할 것이 생겼어요</p>
              {notice.changes.length > 0 && <Changes list={notice.changes} />}
              <p className="mt-1 text-13 text-body">{st && st.hard_errors.length > 0 ? "아래 오류를 고치면" : "아래 질문에 답하면"} 다시 조건 확인으로 넘어갑니다.</p>
            </BotSays>
          )}

          {history.map((h) => <HistoryItem key={h.key}>{h.node}</HistoryItem>)}

          {result && busy === "" && (result.kind === "overrides" || !svc.getMessageResults) && (
            <BotSays>
              <p className="font-semibold">{result.changes.length ? `${result.kind === "overrides" ? "조건 변경" : "추가 요청"}을 반영했어요. 바뀐 조건 ${result.changes.length}개` : `${result.kind === "overrides" ? "조건 변경" : "추가 요청"}을 처리했지만 바뀐 조건 값은 없어요.`}</p>
              {result.changes.length > 0 && <Changes list={result.changes} />}
            </BotSays>
          )}

          {st && draft && st.hard_errors.length > 0 && (
            <BotSays tone="error">
              <p className="font-semibold">입력 조건에 오류가 있어 먼저 고쳐야 해요</p>
              <ul className="mt-1 list-disc pl-5 text-13">{st.hard_errors.map((e) => <li key={e.field}>{e.message_ko}</li>)}</ul>
              <div className="mt-2 flex flex-wrap gap-2">
                {profile && <button type="button" onClick={() => setEditing(true)} disabled={locked} className={CHAT_MAIN}>이번 조건 고치기</button>}
                <button type="button" onClick={() => void leave.leave()} disabled={locked} className={CHAT_QUIET}>조건 그대로 새 요청</button>
              </div>
              <p className="mt-2 text-12 text-sub">기본 투자조건(내 투자조건)을 바꿔도 진행 중인 이 요청에는 적용되지 않습니다.</p>
            </BotSays>
          )}
          {st && draft && st.state === "blocked" && (
            <BotSays tone="warn">
              <p className="font-semibold">보충 질문 {st.max_questions}개를 모두 썼지만 정해지지 않은 항목이 남았어요</p>
              <ul className="mt-1 list-disc pl-5 text-13">{st.unresolved.map((u) => <li key={u.field}><b>{u.label_ko}</b>: {u.hint_ko}{u.examples_ko.length ? ` (예: ${u.examples_ko.join(", ")})` : ""}</li>)}</ul>
              <p className="mt-1 text-13 text-body">남은 항목은 「조건 바꾸기」로 직접 정하거나, 아이디어를 고쳐 다시 시작해 주세요. 분석은 시작되지 않았습니다.</p>
              <div className="mt-2 flex flex-wrap gap-2">
                {profile && <button type="button" onClick={() => setEditing(true)} disabled={locked} className={CHAT_MAIN}>조건 바꾸기</button>}
                <button type="button" onClick={() => void leave.leave()} disabled={locked} className={CHAT_QUIET}>아이디어 고쳐 다시 시작</button>
              </div>
            </BotSays>
          )}
          {showQuestion && q && <QuestionSays q={q} st={st!} n={answeredN + 1} locked={locked} text={text} hint={qHint}
            onPick={(o) => answer(q, o.value, o.label_ko)} onText={(t) => { setText(t); setQHint("") }} onSendText={() => answerText(q)}
            onSkip={() => act("skip", "답하지 않음 (기본값 사용)", () => svc.skip(requestId, q.seq))} />}
          {st && draft && st.state === "asking" && !q && busy === "" && (
            <BotSays><p>지금 표시할 질문이 없어요.</p><button type="button" onClick={res.reload} className={`${CHAT_QUIET} mt-2`}>최신 상태 불러오기</button></BotSays>
          )}
          {st && draft && st.state === "ready" && busy === "" && <BotSays><p>조건이 모두 정해졌어요. 최종 조건 확인으로 넘어갑니다.</p></BotSays>}
          {st?.status === "cancelled" && (
            <BotSays>
              <p className="font-semibold">취소된 요청이에요</p>
              <p className="text-13 text-body">이 요청은 더 진행할 수 없습니다. 같은 아이디어와 조건으로 새 요청을 시작할 수 있어요.</p>
              <div className="mt-2 flex flex-wrap gap-2">
                <button type="button" onClick={() => startNewWith(st.idea, st.overrides)} className={CHAT_MAIN}>같은 조건으로 새 요청</button>
                <button type="button" onClick={() => navigate({ page: "home" })} className={CHAT_QUIET}>홈으로</button>
              </div>
            </BotSays>
          )}

          {busy !== "" && <>{sent && <ISay pending>{sent}</ISay>}<Typing label={WAIT[busy]} /></>}
          {err && busy === "" && (
            <BotSays tone="error">
              <p className="font-semibold">{err.kind === "message" ? "추가 요청을 반영하지 못했어요" : err.kind === "overrides" ? "조건을 바꾸지 못했어요" : "답변을 반영하지 못했어요"}</p>
              <p className="text-13 text-body">{err.message} 입력한 내용은 그대로 남아 있어요.</p>
              <button type="button" onClick={err.retry} className={`${CHAT_QUIET} mt-2`}>다시 시도</button>
            </BotSays>
          )}
          {(leave.asking || leave.error) && <li className="chat-in"><CancelRequestConfirm c={leave} keepLabel="계속 답하기" disabled={busy !== ""} /></li>}
        </ol>
      </div>

      {open && (
        <div className="mx-auto w-full max-w-[760px] p-4">
          <div className="rounded-box bg-sunken p-3 transition-shadow focus-within:shadow-[0_0_0_2px_var(--color-focus)]">
            <textarea value={note} readOnly={locked} rows={2} aria-label="말로 조건 보태기" onChange={(e) => { setNote(e.target.value); setNoteHint("") }}
              className="w-full resize-none border-0 bg-transparent px-1 text-15 leading-6 text-main outline-none placeholder:text-hint" placeholder="바꾸고 싶은 조건을 말로 적어 주세요. 예: 배당주 위주로 / 종목은 8개만" />
            {note.trim() && busy !== "message" && <p className="px-1 text-12 font-medium text-warning">{NOTE_UNSENT}</p>}
            {noteHint && <p className="px-1 text-12 font-medium text-danger">{noteHint}</p>}
            <div className="mt-2 flex items-center justify-between gap-2">
              <p className="px-1 text-12 text-sub">질문과 상관없이 바꾸고 싶은 것을 적으면 분석 모델이 해석해 반영합니다.</p>
              <button type="button" onClick={sendNote} disabled={locked} className="inline-flex h-10 shrink-0 items-center rounded-control bg-accent px-4 text-14 font-semibold text-on-accent transition enabled:hover:bg-accent-hover disabled:cursor-not-allowed disabled:opacity-60">{busy === "message" ? "반영하는 중…" : NOTE_BUTTON}</button>
            </div>
          </div>
        </div>
      )}
      {editing && profile && st && <DetailConditionsDialog profile={profile.profile} initial={st.overrides ?? {}} onApply={applyOverrides} close={() => setEditing(false)} title="이번 요청의 조건 바꾸기" applyLabel="이 조건으로 다시 해석" intro="기본 투자조건에서 가져온 값을 이번 요청에서만 바꿉니다. 적용하면 분석 모델이 바뀐 조건으로 다시 해석하고, 필요한 질문만 다시 묻습니다. 저장된 기본 투자조건은 그대로입니다." />}
    </section>
  )
}

/** 지난 대화 한 묶음 (질문+답, 보탠 말+결과): 목록 안에서 두 줄을 한 항목으로 */
function HistoryItem({ children }: { children: ReactNode }) {
  return <li><ol className="flex flex-col gap-3">{children}</ol></li>
}

/** 지금 질문 말풍선: 질문 · 왜 묻는지 · 보기(누르면 바로 보냄) · 직접 적기 · 답하지 않음 */
function QuestionSays({ q, st, n, locked, text, hint, onPick, onText, onSendText, onSkip }: {
  q: Question; st: DialogState; n: number; locked: boolean; text: string; hint: string
  onPick: (o: Question["options"][number]) => void; onText: (t: string) => void; onSendText: () => void; onSkip: () => void
}) {
  const pc = st.precheck
  return (
    <BotSays wide>
      <p className="t-meta">질문 {n} · 최대 {st.max_questions}개 · {q.field_label_ko ?? ko(q.field)}</p>
      <p className="mt-1 text-15 font-bold leading-6 text-main">{q.question_ko}</p>
      <p className="mt-1 text-13 leading-5 text-body">{q.why_ko || KIND_HELP[q.kind]}</p>
      {q.kind === "feasibility" && pc && (
        <div className="mt-2 rounded-control bg-surface p-3 text-12 leading-5 text-body">
          <p>필요한 최소 종목 수 <b>{pc.min}개</b> · 분석 기준일({pc.as_of.date}) 기준 고를 수 있는 후보 <b>{pc.as_of.n_with_metric}개</b> · 백테스트 시작일({pc.start.date}) 기준 <b>{pc.start.n_with_metric}개</b></p>
          {pc.feasible_start && <p>백테스트를 {pc.feasible_start.date}부터 시작하면({pc.feasible_start.years}년) 후보 {pc.feasible_start.n_with_metric}개로 분석할 수 있습니다.</p>}
        </div>
      )}
      {q.options.length > 0 && (
        <div role="group" aria-label={q.question_ko} className="mt-3 flex flex-col gap-2">
          {q.options.map((o, i) => {
            const patch = optionPatch(o.patch)
            return (
              <button key={i} type="button" disabled={locked} onClick={() => onPick(o)} className="rounded-control bg-surface px-4 py-2.5 text-left transition enabled:hover:bg-tint disabled:opacity-60">
                <span className="block text-14 font-semibold text-main">{o.label_ko}</span>
                {patch && <span className="mt-0.5 block t-meta">바뀌는 조건: {patch}</span>}
              </button>
            )
          })}
        </div>
      )}
      {q.allow_free_text && (
        <div className="mt-2 flex gap-2">
          <input value={text} readOnly={locked} onChange={(e) => onText(e.target.value)} onKeyDown={(e) => { if (e.key === "Enter" && !e.nativeEvent.isComposing) onSendText() }}
            aria-label={q.options.length ? "또는 직접 적기" : "답변"} placeholder={q.options.length ? "또는 직접 적기" : "답을 적어 주세요"}
            className="h-10 min-w-0 flex-1 rounded-control bg-surface px-3 text-14 text-main outline-none placeholder:text-hint focus:shadow-[0_0_0_2px_var(--color-focus)]" />
          <button type="button" onClick={onSendText} disabled={locked} className={CHAT_MAIN}>답변 보내기</button>
        </div>
      )}
      {hint && <p className="mt-1 text-12 font-medium text-danger">{hint}</p>}
      <button type="button" onClick={onSkip} disabled={locked} className="mt-2 text-13 text-sub underline-offset-2 enabled:hover:text-main enabled:hover:underline">답하지 않음 (기본값 사용)</button>
    </BotSays>
  )
}
