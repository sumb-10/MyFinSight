import { useState } from "react"
import { ArrowRight, Check } from "lucide-react"
import { useService } from "../../app/providers"
import { navigate } from "../../app/router"
import { errorMessage } from "../../api/client"
import type { ProposedBatchAnswer, ProposedQuestionBatch } from "../../api/proposed"
import type { DialogState } from "../../api/types"
import { useResource } from "../../state/useResource"
import { Badge, Button, inputClass, Loading } from "../../ui"
import { MockTag } from "../report/proposedView"
import { Part } from "../profile/parts"
import { ActionError, Pending, type RowChange } from "./flow"

// 여러 질문에 한 번에 답하기 (제안 기능): 서비스에 getQuestionBatch·answerBatch 가 있고 함께 물은 질문이 둘 이상일 때 (ClarifyScreen).
// 실제 서버는 가장 급한 질문 + 답이 종목 선정·후보 수에 영향이 없는 질문만 함께 묻고, 모든 질문은 비워 두면 답하지 않음(기본값)이다.
// 목업은 꼭 넣을 종목 외에는 필수로 둔다.

type Q = ProposedQuestionBatch["questions"][number]
type Draft = { pick?: { v: unknown }; text: string }
export interface Submitted { seq: number; question: string; field: string; fieldLabel: string; answer: string; kind: "option" | "text" | "skip" }

export function BatchQuestions({ requestId, st, onDone }: { requestId: string; st: DialogState; onDone: (next: DialogState, sent: Submitted[]) => void }) {
  const svc = useService()
  const batch = useResource(() => svc.getQuestionBatch!(requestId), [svc, requestId, st.turn])
  const [drafts, setDrafts] = useState<Record<number, Draft>>({})
  const [errs, setErrs] = useState<Record<number, string>>({})
  const [busy, setBusy] = useState(false)
  const [err, setErr] = useState<string | null>(null)
  if (batch.status === "loading" && !batch.data) return <Loading label="질문을 불러오는 중…" />
  const qs = batch.data?.questions ?? []
  if (!qs.length) return null
  const d = (q: Q): Draft => drafts[q.seq] ?? { text: "" }
  const set = (q: Q, x: Draft) => { setDrafts((m) => ({ ...m, [q.seq]: x })); setErrs((m) => { const n = { ...m }; delete n[q.seq]; return n }) }
  const has = (q: Q) => !!d(q).pick || !!d(q).text.trim()
  const required = qs.filter((q) => q.required), done = qs.filter(has).length

  const submit = async () => {
    const miss = Object.fromEntries(required.filter((q) => !has(q)).map((q) => [q.seq, "필수 질문입니다. 보기를 고르거나 답을 적어 주세요."]))
    setErrs(miss)
    if (Object.keys(miss).length) { document.getElementById(`batch-q-${Object.keys(miss)[0]}`)?.scrollIntoView({ block: "center" }); return }
    const answers: ProposedBatchAnswer[] = qs.map((q) => { const x = d(q); return x.pick ? { seq: q.seq, option_value: x.pick.v } : x.text.trim() ? { seq: q.seq, free_text: x.text.trim() } : { seq: q.seq, skip: true } })
    const sent: Submitted[] = qs.map((q) => { const x = d(q); return { seq: q.seq, question: q.question_ko, field: q.field, fieldLabel: q.field_label_ko, answer: x.pick ? q.options.find((o) => o.value === x.pick!.v)?.label_ko ?? "" : x.text.trim() || "답하지 않음 (기본값 사용)", kind: x.pick ? "option" : x.text.trim() ? "text" : "skip" } })
    setBusy(true); setErr(null)
    try { onDone(await svc.answerBatch!(requestId, answers), sent) } catch (e) { setErr(errorMessage(e)) } finally { setBusy(false) }
  }

  return (
    <Part title="추가 점검 질문" aside={<MockTag />} desc={`질문 ${qs.length}개를 한 화면에서 답하고 한 번에 보냅니다. ${required.length ? `필수 ${required.length}개 · 선택 ${qs.length - required.length}개 (선택 질문은 비워 두면 기본 투자조건을 그대로 씁니다).` : "비워 둔 질문은 기본 투자조건을 그대로 씁니다."}`}>
      <ol className="space-y-4">
        {qs.map((q, i) => {
          const x = d(q), e = errs[q.seq]
          return (
            <li key={q.seq} id={`batch-q-${q.seq}`} className={`rounded-xl border p-4 ${e ? "border-red-300 bg-red-50/40" : "border-slate-200 bg-white"}`}>
              <fieldset className="space-y-3" disabled={busy}>
                <legend className="w-full">
                  <span className="flex flex-wrap items-center gap-2 text-xs text-slate-500"><span className="font-bold text-slate-700">질문 {i + 1}</span><Badge tone={q.required ? "amber" : "slate"}>{q.required ? "필수" : "선택"}</Badge>관련 항목: {q.field_label_ko}{has(q) && <Check className="size-4 text-emerald-600" aria-label="답함" />}</span>
                  <span className="mt-1.5 block text-base font-bold leading-7 text-slate-950">{q.question_ko}</span>
                  {q.why_ko && <span className="mt-0.5 block text-xs leading-5 text-slate-500">{q.why_ko}</span>}
                </legend>
                {q.options.length > 0 && (
                  <div role="radiogroup" aria-label={q.question_ko} className="grid grid-cols-1 gap-2 sm:grid-cols-3">
                    {q.options.map((o) => {
                      const on = !!x.pick && x.pick.v === o.value
                      return <button key={o.label_ko} type="button" role="radio" aria-checked={on} onClick={() => set(q, { pick: on ? undefined : { v: o.value }, text: "" })} className={`rounded-xl border p-3 text-left text-sm font-semibold transition focus:outline-none focus:ring-2 focus:ring-blue-500 ${on ? "border-blue-400 bg-blue-50 text-blue-900 ring-1 ring-blue-200" : "border-slate-200 bg-white text-slate-800 hover:bg-slate-50"}`}>{o.label_ko}</button>
                    })}
                  </div>
                )}
                {q.allow_free_text && <input className={inputClass} aria-label={`질문 ${i + 1} 직접 적기`} value={x.text} placeholder={q.options.length ? "또는 직접 적기" : "답변"} onChange={(ev) => set(q, { pick: undefined, text: ev.target.value })} />}
                {e && <p className="text-xs font-medium text-red-600">{e}</p>}
              </fieldset>
            </li>
          )
        })}
      </ol>
      {busy && <Pending title={`답변 ${qs.length}개를 반영하고 있습니다.`} />}
      {err && !busy && <ActionError title="답변을 반영하지 못했습니다" message={err} retry={() => void submit()} />}
      <div className="flex flex-col gap-2 border-t border-slate-100 pt-4 sm:flex-row sm:items-center sm:justify-between">
        <p className="text-xs text-slate-500">{done}/{qs.length}개 답함{Object.keys(errs).length > 0 && <span className="ml-2 font-semibold text-red-600">필수 질문 {Object.keys(errs).length}개에 답해 주세요</span>}</p>
        <Button onClick={() => void submit()} disabled={busy}>{busy ? "반영하는 중…" : `답변 ${qs.length}개 한 번에 보내기`}</Button>
      </div>
    </Part>
  )
}

/** 보낸 답변 요약과 최종 조건에 반영된 결과. 확인 화면으로 넘어가기 전에 한 번 보여 준다. */
/** more = 답을 반영한 뒤 서버가 질문을 더 냈다 (실제 서버는 종목 선정을 바꾸는 질문을 다음 턴에 묻는다) → 확인 화면으로 가는 버튼 대신 아래 질문으로. */
export function BatchResult({ requestId, sent, changes, more = false }: { requestId: string; sent: Submitted[]; changes: RowChange[]; more?: boolean }) {
  const svc = useService()
  const byLabel = (label: string) => changes.find((c) => c.label === label)
  const extra = changes.filter((c) => !sent.some((s) => s.fieldLabel === c.label))
  return (
    <Part title="보낸 답변과 반영 결과" aside={<MockTag />} desc={more ? "답변을 조건에 반영했습니다. 답에 따라 더 확인할 질문이 생겨 아래에 이어서 묻습니다." : "답변을 조건에 반영했습니다. 확인 화면에서 최종 조건을 한 번 더 보고 분석을 시작합니다."}>
      <ol className="space-y-2">
        {sent.map((s, i) => {
          const c = byLabel(s.fieldLabel)
          return (
            <li key={s.seq} className="rounded-xl border border-slate-200 bg-white p-3 text-sm">
              <p className="text-xs text-slate-500"><b className="text-slate-700">질문 {i + 1}</b> · {s.question}</p>
              <p className="mt-1 font-semibold text-slate-950">{s.answer}</p>
              <p className="mt-0.5 text-xs text-slate-600">{c ? <>조건에 반영됨 · {c.label}: {c.before} → <b>{c.after}</b></> : s.kind === "skip" ? "기본 투자조건을 그대로 씁니다." : s.kind === "text" ? (svc.mode === "mock" ? "직접 적은 답은 기록만 했습니다 (목업은 자유 입력을 해석하지 않습니다)." : "직접 적은 답은 아이디어 보충으로 전달해 분석 모델이 해석했습니다.") : "기본 투자조건과 같은 값이라 바뀐 조건은 없습니다."}</p>
            </li>
          )
        })}
      </ol>
      {/* 질문별 줄에 이미 나온 변경은 다시 적지 않는다 (아래 「이번 분석에서 달라진 조건」 카드에도 같은 내용이 있다). 답변 때문에 함께 바뀐 항목만 따로 알린다. */}
      {extra.length > 0 && (
        <div className="rounded-xl border border-emerald-200 bg-emerald-50 p-4 text-sm text-emerald-950">
          <p className="font-semibold">답변에 따라 함께 바뀐 항목 {extra.length}개</p>
          <ul className="mt-1.5 space-y-0.5">{extra.map((c) => <li key={c.label}>{c.label}: {c.before} → <b>{c.after}</b></li>)}</ul>
        </div>
      )}
      {changes.length === 0 && <p className="rounded-xl border border-slate-200 bg-slate-50 p-4 text-sm text-slate-700">답변으로 바뀐 조건 값은 없습니다.</p>}
      {!more && <div className="flex justify-end"><Button onClick={() => navigate({ page: "confirm", requestId })}>조건 최종 확인으로<ArrowRight className="size-4" /></Button></div>}
    </Part>
  )
}
