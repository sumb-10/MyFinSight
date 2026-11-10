import { useService } from "../../app/providers"
import { useResource } from "../../state/useResource"
import { Button, Disclosure, Loading } from "../../ui"
import { RevisionCard } from "../analysis/RevisionCard"
import { whenText } from "../profile/history"
import type { ProposedRequestLog } from "../../api/proposed"
import { MockTag } from "./proposedView"

function Bubble({ who, time, children }: { who: "user" | "system"; time?: string | null; children: React.ReactNode }) {
  const user = who === "user"
  return (
    <li className={`flex flex-col ${user ? "items-end" : "items-start"}`}>
      <span className="mb-0.5 text-[11px] text-slate-500">{user ? "사용자" : "분석 모델 질문"}{time ? ` · ${whenText(time)}` : ""}</span>
      <p className={`max-w-[90%] whitespace-pre-line break-words rounded-2xl px-3 py-2 text-sm leading-6 ${user ? "rounded-tr-sm bg-slate-800 text-white" : "rounded-tl-sm bg-slate-100 text-slate-800"}`}>{children}</p>
    </li>
  )
}

const OUTCOME: Record<ProposedRequestLog["messages"][number]["outcome"], [string, string]> = { applied: ["반영됨", "border-emerald-200 bg-emerald-50 text-emerald-800"], not_applied: ["반영되지 않음", "border-slate-200 bg-slate-50 text-slate-700"], needs_confirmation: ["추가 확인 필요", "border-amber-300 bg-amber-50 text-amber-900"] }

/** 이 리포트를 만든 요청의 실제 기록 (GET /requests/{id}): 처음 아이디어와 최종 반영 조건을 먼저, 질문·답변 전체는 펼쳐서. 서버가 주는 기록만 보여 준다.
 *  「말로 보탠 요청」 원문은 서버가 주지 않는다 — 제안 계약 request_log(지금은 목업만)가 있을 때만 그 기록을 보여 준다. */
export function RequestHistory({ requestId, log }: { requestId: string; log?: ProposedRequestLog | null }) {
  const svc = useService()
  const res = useResource(() => svc.getRequest(requestId), [svc, requestId])
  if (res.status === "loading" && !res.data) return <Loading label="요청 내역을 불러오는 중…" />
  const st = res.data
  if (!st) return <div className="rounded-xl border border-slate-200 bg-slate-50 p-4 text-sm text-slate-600"><p>요청 내역을 불러오지 못했습니다. {res.error ?? ""}</p><Button variant="secondary" className="mt-2" onClick={res.reload}>다시 시도</Button></div>
  const answered = st.questions.filter((q) => q.answered_at).sort((a, b) => a.seq - b.seq)
  const changed = (st.confirmation?.rows ?? st.conditions ?? []).filter((r) => r.changed && r.group_ko !== "아이디어")
  return (
    <div className="space-y-5">
      <div className="grid grid-cols-1 gap-4 lg:grid-cols-2">
        <div className="rounded-xl border border-slate-200 p-4">
          <h3 className="text-sm font-bold text-slate-900">처음 입력한 투자 아이디어</h3>
          <p className="mt-2 whitespace-pre-line break-words text-[15px] leading-7 text-slate-800">{st.idea}</p>
        </div>
        <div className="rounded-xl border border-slate-200 p-4">
          <h3 className="text-sm font-bold text-slate-900">최종 분석에 반영된 변경 조건</h3>
          {changed.length ? (
            <ul className="mt-2 divide-y divide-slate-100 text-sm">{changed.map((r) => <li key={r.field} className="flex flex-col gap-0.5 py-2 sm:flex-row sm:gap-4"><span className="shrink-0 font-semibold text-slate-800 sm:w-36">{r.label_ko}</span><span className="min-w-0 break-words text-slate-700">{r.profile_value_ko != null && <><span className="text-slate-500">{r.profile_value_ko}</span><span className="mx-1.5 text-slate-400">→</span></>}<b>{r.value_ko}</b></span></li>)}</ul>
          ) : <p className="mt-2 text-sm text-slate-600">기본 투자조건과 달라진 항목이 없습니다.</p>}
        </div>
      </div>
      <Disclosure title="추가 질문 및 답변 전체 보기" summary={`${answered.length}건`}>
        {answered.length ? (
          <ol className="space-y-3" aria-label="요청 기록">
            <Bubble who="user">{st.idea}</Bubble>
            {answered.flatMap((q) => [
              <Bubble key={`q${q.seq}`} who="system" time={q.asked_at}>{q.question_ko}</Bubble>,
              <Bubble key={`a${q.seq}`} who="user" time={q.answered_at}>{q.skipped ? "답하지 않음 (기본값 사용)" : q.answer}</Bubble>,
            ])}
          </ol>
        ) : <p className="text-sm text-slate-600">저장된 추가 질문과 답변이 없습니다.</p>}
      </Disclosure>
      {log && (
        <div className="rounded-xl border border-slate-200 p-4">
          <h3 className="flex items-center text-sm font-bold text-slate-900">말로 보탠 요청 {log.messages.length}건<MockTag /></h3>
          {log.messages.length ? (
            <ul className="mt-2 space-y-2">
              {log.messages.map((m, i) => (
                <li key={i} className="rounded-lg bg-slate-50 px-3 py-2.5">
                  <p className="flex flex-wrap items-center justify-between gap-2"><span className="text-sm font-semibold text-slate-900">“{m.text}”</span><span className={`rounded-full border px-2 py-0.5 text-xs font-semibold ${OUTCOME[m.outcome][1]}`}>{OUTCOME[m.outcome][0]}</span></p>
                  <p className="text-xs text-slate-500">{whenText(m.at)}</p>
                  {m.changes_ko.length > 0 && <ul className="mt-1 list-disc pl-5 text-sm leading-6 text-slate-700">{m.changes_ko.map((c, j) => <li key={j}>{c}</li>)}</ul>}
                  {m.outcome !== "applied" && <p className="mt-1 text-sm leading-6 text-slate-600">{m.note_ko ?? "기존 조건이 그대로 유지됩니다."}</p>}
                </li>
              ))}
            </ul>
          ) : <p className="mt-2 text-sm text-slate-600">말로 보탠 요청이 없습니다.</p>}
          <h4 className="mt-4 text-sm font-bold text-slate-900">최종 분석 조건</h4>
          <dl className="mt-1 divide-y divide-slate-100 text-sm">{log.final_conditions.map((c) => <div key={c.label_ko} className="flex gap-4 py-1.5"><dt className="w-36 shrink-0 text-slate-600">{c.label_ko}</dt><dd className={c.changed ? "font-semibold text-slate-900" : "text-slate-700"}>{c.value_ko}{c.changed && <span className="ml-1.5 text-xs font-normal text-blue-700">요청으로 바뀜</span>}</dd></div>)}</dl>
        </div>
      )}
      {st.revision && <RevisionCard rev={st.revision} />}
      <p className="text-xs leading-5 text-slate-500">{log ? "아이디어, 답한 질문과 답, 말로 보탠 요청과 그 결과, 조건 변경 결과를 표시합니다." : "저장된 기록(아이디어, 답한 질문과 답, 조건 변경 결과)만 표시합니다. 「말로 조건 보태기」로 보낸 문장 자체는 불러올 수 있는 기록이 없어 여기에 나오지 않습니다."}</p>
    </div>
  )
}
