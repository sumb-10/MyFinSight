import { useEffect, useMemo, useState } from "react"
import { ArrowLeft, Loader2, MessageSquareText, Send, SlidersHorizontal } from "lucide-react"
import { useProfile, useService } from "../../app/providers"
import { navigate } from "../../app/router"
import { errorMessage } from "../../api/client"
import type { ConditionRow, DialogState, Question } from "../../api/types"
import { useResource } from "../../state/useResource"
import { saveUi } from "../../state/uiStorage"
import { Alert, Badge, Button, Card, Chip, EmptyState, ErrorState, Loading, PageHeader, inputClass } from "../../ui"
import { ko } from "../../lib/format"
import { RevisionCard } from "./RevisionCard"
import { DetailConditionsDialog } from "../home/DetailConditions"

const KIND_TONE: Record<Question["kind"], "red" | "amber" | "blue" | "slate"> = { missing: "red", conflict: "amber", ambiguous: "blue", preference: "slate", feasibility: "amber" }

/** 같은 아이디어·조건으로 새 요청을 시작할 수 있게 홈에 미리 채워 둔다 (프로필을 바꿔도 진행 중 요청에는 적용되지 않으므로). */
export function startNewWith(idea: string, overrides: Record<string, unknown> | undefined) {
  saveUi({ prefillIdea: idea, prefillOverrides: overrides ?? {}, activeRequestId: null })
  navigate({ page: "home" })
}
const SOURCE_KO: Record<ConditionRow["source"], string> = { profile: "프로필", idea: "아이디어", answer: "답변·직접 변경", default: "기본값", derived: "계산" }

export function ClarifyScreen({ requestId }: { requestId: string }) {
  const svc = useService()
  const { profile } = useProfile()
  const res = useResource(() => svc.getRequest(requestId), [svc, requestId])
  const [st, setSt] = useState<DialogState | null>(null)
  const [busy, setBusy] = useState<"" | "answer" | "skip" | "message" | "overrides" | "cancel">("")
  const [err, setErr] = useState("")
  const [noteErr, setNoteErr] = useState("")
  const [text, setText] = useState("")
  const [note, setNote] = useState("")
  const [picked, setPicked] = useState<unknown>(undefined)
  const [editing, setEditing] = useState(false)
  useEffect(() => { if (res.data) setSt(res.data) }, [res.data])
  useEffect(() => { const q0 = st?.question; if (q0 && q0.options.length === 1) setPicked(q0.options[0].value) }, [st?.question?.seq])  // eslint-disable-line react-hooks/exhaustive-deps -- 보기가 하나면 미리 고른다
  useEffect(() => {
    if (!st) return
    if (st.state === "ready" || st.state === "confirmed") navigate({ page: "confirm", requestId })
  }, [st, requestId])
  const conditions = useMemo(() => (st?.conditions ?? []).filter((r) => r.group_ko !== "아이디어" && r.group_ko !== "계산 조건"), [st])
  const groups = useMemo(() => [...new Set(conditions.map((r) => r.group_ko))], [conditions])

  if (res.status === "loading" && !st) return <Loading label="요청을 불러오는 중…" />
  if (res.status === "error" && !st) return <ErrorState message={res.error ?? ""} retry={res.reload} />
  if (!st) return null
  if (st.status === "cancelled") return <EmptyState title="취소된 요청입니다" description="이 요청은 취소되어 더 진행할 수 없습니다. 같은 아이디어와 조건으로 새 요청을 시작할 수 있습니다." action={<div className="flex gap-2"><Button onClick={() => startNewWith(st.idea, st.overrides)}>같은 조건으로 새 요청</Button><Button variant="ghost" onClick={() => navigate({ page: "home" })}>홈으로</Button></div>} />

  const q = st.question
  const act = async (kind: typeof busy, fn: () => Promise<DialogState>) => {
    const setE = kind === "answer" || kind === "skip" ? setErr : setNoteErr  // 답변 오류는 질문 카드에, 메모·조건 변경 오류는 그 도구 옆에 (P2-15)
    setBusy(kind); setErr(""); setNoteErr("")
    try { const next = await fn(); setSt(next); setText(""); setNote(""); setPicked(undefined) } catch (e) { setE(errorMessage(e)) } finally { setBusy("") }
  }
  const cancelAndHome = async () => {
    setBusy("cancel"); setNoteErr("")
    try { await svc.cancelRequest(requestId); saveUi({ activeRequestId: null }); navigate({ page: "home" }) } catch (e) { setNoteErr(errorMessage(e)) } finally { setBusy("") }
  }
  const submit = () => {
    if (!q) return
    if (picked !== undefined) return act("answer", () => svc.answer(requestId, q.seq, { option_value: picked }))
    if (text.trim()) return act("answer", () => svc.answer(requestId, q.seq, { free_text: text.trim() }))
    setErr("선택지를 고르거나 답을 적어 주세요.")
  }
  const sendNote = () => { if (!note.trim()) { setNoteErr("보탤 내용을 적어 주세요."); return } void act("message", () => svc.sendMessage(requestId, note.trim())) }
  const applyOverrides = (o: Record<string, unknown>) => {
    // 폼이 돌려준 값(프로필과 다른 것만) + 이전에 바꿨다가 이번에 프로필 값으로 돌린 것은 null 로 지운다
    const prev = st.overrides ?? {}
    const merged: Record<string, unknown> = { ...o }
    for (const k of Object.keys(prev)) if (!(k in o)) merged[k] = null
    void act("overrides", () => svc.updateOverrides(requestId, merged))
  }
  const d = st.summary.derived
  const changedN = conditions.filter((r) => r.changed).length

  return (
    <div className="mx-auto max-w-6xl space-y-6">
      <PageHeader eyebrow={`${ko(st.mode)} · 조건 확인`} title="부족한 조건을 함께 정합니다" description={`분석 모델이 아이디어를 해석하고, 전략이 달라질 항목만 한 번에 하나씩 묻습니다 (최대 ${st.max_questions}회). 아래 "지금 조건"은 프로필에서 가져온 기본값이며, 버튼이나 말로 언제든 바꿀 수 있습니다. 답과 변경은 코드가 요청 조건에 반영하고 검증합니다.`}
        actions={<Button variant="ghost" onClick={() => void cancelAndHome()} disabled={busy !== ""}><ArrowLeft className="size-4" />취소하고 홈으로</Button>} />
      <div className="grid grid-cols-[1.05fr_0.95fr] gap-6">
        <div className="space-y-4">
          {st.revision && <RevisionCard rev={st.revision} />}
          <Card className="p-5">
            <p className="text-xs font-bold text-slate-400">투자 아이디어</p>
            <blockquote className="mt-2 border-l-4 border-blue-200 pl-3 text-[15px] leading-7 text-slate-800">{st.idea}</blockquote>
            {st.summary.interpretation_summary_ko && (
              <div className="mt-4 rounded-xl bg-slate-50 p-4 text-sm text-slate-700">
                <p className="text-xs font-bold text-slate-400">분석 모델의 이해</p>
                <p className="mt-1">{st.summary.interpretation_summary_ko}</p>
                <div className="mt-2 flex flex-wrap gap-2">{st.summary.themes.map((t) => <Badge key={t.id} tone="blue">{t.label_ko}</Badge>)}</div>
              </div>
            )}
          </Card>
          {conditions.length > 0 && (
            <Card className="p-5">
              <div className="flex items-start justify-between gap-3">
                <div><p className="text-xs font-bold text-slate-400">지금 조건 {changedN > 0 && <Badge tone="blue">프로필과 다른 항목 {changedN}</Badge>}</p><p className="mt-1 text-xs text-slate-500">파란 줄은 이번 요청에서 바뀐 값입니다. 질문에 답하지 않아도 여기서 바로 고칠 수 있습니다.</p></div>
                {profile && <Button variant="secondary" onClick={() => setEditing(true)} disabled={busy !== ""}><SlidersHorizontal className="size-4" />조건 바꾸기</Button>}
              </div>
              <div className="mt-3 grid grid-cols-2 gap-x-6 gap-y-1 text-sm">
                {groups.map((g) => (
                  <div key={g} className="space-y-1">
                    <p className="mt-2 text-[11px] font-bold tracking-wider text-slate-400">{g}</p>
                    {conditions.filter((r) => r.group_ko === g).map((r) => (
                      <div key={r.field} className={`rounded-lg px-2 py-1 ${r.changed ? "bg-blue-50/70" : ""}`} title={`출처: ${SOURCE_KO[r.source]}${r.profile_value_ko ? ` · 프로필 ${r.profile_value_ko}` : ""}`}>
                        <div className="flex items-baseline justify-between gap-3"><span className="shrink-0 text-slate-500">{r.label_ko}</span><span className={`break-words text-right ${r.changed ? "font-semibold text-blue-800" : "text-slate-800"}`}>{r.value_ko}</span></div>
                        {r.note_ko && <p className="mt-0.5 text-[11px] leading-4 text-amber-700">{r.note_ko}</p>}
                      </div>
                    ))}
                  </div>
                ))}
              </div>
            </Card>
          )}
          {st.questions.filter((x) => x.answered_at).length > 0 && (
            <Card className="p-5">
              <p className="text-xs font-bold text-slate-400">지금까지의 질문과 답</p>
              <ol className="mt-3 space-y-3">
                {st.questions.filter((x) => x.answered_at).map((x) => (
                  <li key={x.seq} className="space-y-1.5">
                    <div className="flex items-start gap-2"><Badge tone={KIND_TONE[x.kind]}>{ko(x.kind)}</Badge><p className="rounded-2xl rounded-tl-sm bg-slate-100 px-3 py-2 text-sm text-slate-800">{x.question_ko}</p></div>
                    <div className="flex justify-end"><p className={`rounded-2xl rounded-tr-sm px-3 py-2 text-sm ${x.skipped ? "bg-slate-200 text-slate-600" : "bg-blue-700 text-white"}`}>{x.answer}</p></div>
                  </li>
                ))}
              </ol>
            </Card>
          )}
        </div>
        <div className="space-y-4">
          {st.hard_errors.length > 0 && (
            <Alert title="입력 조건에 오류가 있어 먼저 수정이 필요합니다" tone="error">
              <ul className="list-disc pl-5">{st.hard_errors.map((e) => <li key={e.field}>{e.message_ko}</li>)}</ul>
              <div className="mt-3 flex flex-wrap items-center gap-2">{profile && <Button variant="secondary" onClick={() => setEditing(true)}>이번 조건 고치기</Button>}<Button variant="ghost" onClick={() => startNewWith(st.idea, st.overrides)}>조건 그대로 새 요청</Button></div>
              <p className="mt-2 text-xs">프로필(기본 투자조건)을 바꿔도 진행 중인 이 요청에는 적용되지 않습니다. 프로필을 바꾸려면 저장한 뒤 새 요청으로 시작해 주세요.</p>
            </Alert>
          )}
          {st.state === "blocked" && (
            <Alert title={`보충 질문 ${st.max_questions}회를 모두 썼지만 확정되지 않은 항목이 남았습니다`} tone="warning">
              <ul className="list-disc pl-5">{st.unresolved.map((u) => <li key={u.field}><b>{u.label_ko}</b>: {u.hint_ko}{u.examples_ko.length ? ` (예: ${u.examples_ko.join(", ")})` : ""}</li>)}</ul>
              <p className="mt-2">남은 항목은 아래 "조건 바꾸기"로 직접 정하거나, 아이디어를 수정해 다시 시작해 주세요. 분석은 시작되지 않았습니다.</p>
              <div className="mt-3 flex gap-2">{profile && <Button variant="secondary" onClick={() => setEditing(true)}>조건 바꾸기</Button>}<Button variant="ghost" onClick={() => navigate({ page: "home" })}>아이디어 수정</Button></div>
            </Alert>
          )}
          {q && st.state === "asking" && (
            <Card className="p-6">
              <div className="flex items-center justify-between"><Badge tone={KIND_TONE[q.kind]}><MessageSquareText className="size-3" />{ko(q.kind)}</Badge><span className="text-xs text-slate-400">질문 {q.seq} / {st.max_questions}</span></div>
              <h2 className="mt-3 text-lg font-bold text-slate-900">{q.question_ko}</h2>
              {q.why_ko && <p className="mt-1 text-xs text-slate-500">{q.why_ko}</p>}
              <p className="mt-1 text-xs text-slate-400">관련 항목: {q.field_label_ko ?? ko(q.field)}</p>
              {q.options.length > 0 && (
                <div className="mt-4 grid grid-cols-1 gap-2">
                  {q.options.map((o, i) => <Chip key={i} active={picked === o.value} onClick={() => { setPicked(o.value); setText("") }}>{o.label_ko}</Chip>)}
                </div>
              )}
              {q.allow_free_text && (
                <div className="mt-4">
                  <label className="text-xs font-semibold text-slate-500">{q.options.length ? "또는 직접 적기" : "답변"}</label>
                  <textarea className={`${inputClass} mt-1 min-h-20`} value={text} onChange={(e) => { setText(e.target.value); setPicked(undefined) }} placeholder="자유롭게 적어 주세요. 분석 모델이 다음 턴에 해석합니다." disabled={busy !== ""} />
                </div>
              )}
              {err && busy === "" && <p className="mt-2 text-xs font-medium text-red-600">{err}</p>}
              <div className="mt-5 flex items-center justify-between">
                <Button variant="ghost" onClick={() => act("skip", () => svc.skip(requestId, q.seq))} disabled={busy !== ""}>답하지 않음 (기본값 사용)</Button>
                <Button onClick={submit} disabled={busy !== ""}>{busy === "answer" ? <><Loader2 className="size-4 animate-spin" />다음 질문을 준비하는 중…</> : "답변 보내기"}</Button>
              </div>
            </Card>
          )}
          {!q && st.state === "asking" && st.hard_errors.length === 0 && <Card className="p-6 text-sm text-slate-600"><Loader2 className="mr-2 inline size-4 animate-spin" />조건을 정리하는 중입니다…</Card>}
          <Card className="p-5">
            <p className="text-xs font-bold text-slate-400">말로 조건 보태기</p>
            <p className="mt-1 text-xs text-slate-500">질문과 상관없이 바꾸고 싶은 것을 적어 주세요. 예: "한국 종목은 빼 주세요", "종목은 8개만", "배당주 위주로". 분석 모델이 해석해 조건 질문으로 되묻거나 테마에 반영합니다. 숫자 조건은 위 "조건 바꾸기" 폼이 더 정확합니다.</p>
            <textarea className={`${inputClass} mt-2 min-h-16`} value={note} onChange={(e) => setNote(e.target.value)} placeholder="바꾸고 싶은 조건이나 덧붙일 설명" disabled={busy !== ""} />
            {noteErr && busy === "" && <p className="mt-2 text-xs font-medium text-red-600">{noteErr}</p>}
            <div className="mt-2 flex justify-end"><Button variant="secondary" onClick={sendNote} disabled={busy !== ""}>{busy === "message" ? <><Loader2 className="size-4 animate-spin" />반영하는 중…</> : <><Send className="size-4" />보내기</>}</Button></div>
          </Card>
          {d && (
            <Card className="p-5 text-sm text-slate-700">
              <p className="text-xs font-bold text-slate-400">코드가 계산한 조건</p>
              <ul className="mt-2 space-y-1">
                <li>분석 기준일 {d.as_of}</li>
                <li>백테스트 {d.backtest_start} ~ {d.backtest_end}</li>
                {d.backtest_fx_rate && d.initial_amount_usd_at_backtest_start !== null && d.initial_amount_usd_at_backtest_start !== undefined && d.backtest_fx_rate !== d.fx_rate
                  ? <>
                      <li>백테스트 투자금 {d.initial_amount_usd_at_backtest_start.toLocaleString("ko-KR", { maximumFractionDigits: 2 })} USD (시작일 {d.backtest_fx_date} 환율 1 USD = {d.backtest_fx_rate.toLocaleString("ko-KR", { maximumFractionDigits: 2 })} KRW)</li>
                      <li>현재 구성 투자금 {d.initial_amount_usd.toLocaleString("ko-KR", { maximumFractionDigits: 2 })} USD (기준일 {d.fx_date} 환율 1 USD = {d.fx_rate.toLocaleString("ko-KR", { maximumFractionDigits: 2 })} KRW)</li>
                    </>
                  : <><li>환율 1 USD = {d.fx_rate.toLocaleString("ko-KR", { maximumFractionDigits: 2 })} KRW ({d.fx_date})</li><li>투자금 {d.initial_amount_usd.toLocaleString("ko-KR", { maximumFractionDigits: 2 })} USD</li></>}
              </ul>
              {(d.warnings?.length ?? 0) > 0 && <ul className="mt-2 list-disc pl-5 text-xs text-amber-800">{d.warnings.map((w, i) => <li key={i}>{w}</li>)}</ul>}
            </Card>
          )}
          {st.warnings.filter((w) => !w.startsWith("question on") && !w.startsWith("precheck")).length > 0 && <p className="text-xs text-slate-400">{st.warnings.filter((w) => !w.startsWith("question on") && !w.startsWith("precheck")).slice(0, 3).join(" · ")}</p>}
        </div>
      </div>
      {editing && profile && <DetailConditionsDialog profile={profile.profile} initial={st.overrides ?? {}} onApply={applyOverrides} close={() => setEditing(false)} title="이번 요청의 조건 바꾸기" applyLabel="이 조건으로 다시 해석" intro="프로필에서 가져온 기본값을 이번 요청에서만 바꿉니다. 적용하면 분석 모델이 바뀐 조건으로 다시 해석하고, 필요한 질문만 다시 묻습니다. 프로필 자체는 그대로입니다." />}
    </div>
  )
}
