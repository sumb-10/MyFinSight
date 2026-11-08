import { AlertTriangle, CheckCircle2, MinusCircle } from "lucide-react"
import type { ProposedMessageResult } from "../../api/proposed"
import { Disclosure } from "../../ui"
import { MockTag } from "../report/proposedView"

// 「말로 보태기」 처리 결과 (제안 기능): 서비스에 getMessageResults 가 있을 때만 — 지금은 목업의 미리 정한 해석 결과뿐이다.
// 처리 중 상태는 기존 Pending 이 보여 주고, 끝나면 반영됨 / 반영되지 않음 / 추가 확인 필요 중 하나를 보여 준다.

const LOOK = {
  applied: { title: "조건에 반영됨", box: "border-emerald-200 bg-emerald-50 text-emerald-950", Icon: CheckCircle2 },
  not_applied: { title: "반영되지 않음", box: "border-slate-200 bg-slate-50 text-slate-800", Icon: MinusCircle },
  needs_confirmation: { title: "추가 확인 필요", box: "border-amber-200 bg-amber-50 text-amber-950", Icon: AlertTriangle },
} as const

export function MessageOutcome({ results }: { results: ProposedMessageResult[] }) {
  const last = results[results.length - 1]
  if (!last) return null
  const L = LOOK[last.outcome], earlier = results.slice(0, -1).reverse()
  return (
    <div className="space-y-2">
      <div role="status" className={`flex gap-3 rounded-xl border p-4 text-sm ${L.box}`}>
        <L.Icon className="mt-0.5 size-5 shrink-0" aria-hidden="true" />
        <div className="min-w-0">
          <p className="flex flex-wrap items-center font-semibold">{L.title}<MockTag /></p>
          <p className="mt-0.5 break-words text-xs opacity-80">“{last.text}”</p>
          {last.outcome === "applied" && last.changes.length > 0 && <ul className="mt-2 space-y-0.5">{last.changes.map((c) => <li key={c.field}>{c.label_ko}: {c.before_ko} → <b>{c.after_ko}</b></li>)}</ul>}
          {last.outcome !== "applied" && <p className="mt-2">{last.outcome === "not_applied" ? `바뀐 조건이 없습니다.${last.note_ko ? "" : " 기존 조건이 그대로 유지됩니다."}` : "아직 조건을 바꾸지 않았습니다. 확인될 때까지 기존 조건이 그대로 유지됩니다."}</p>}
          {last.note_ko && <p className="mt-1 text-xs leading-5 opacity-90">{last.note_ko}</p>}
        </div>
      </div>
      {earlier.length > 0 && (
        <Disclosure size="sm" title={`이전에 보낸 요청 ${earlier.length}개`}>
          <ul className="space-y-1.5 text-xs text-slate-600">{earlier.map((m, i) => <li key={i} className="break-words"><b className="text-slate-800">{LOOK[m.outcome].title}</b> · “{m.text}”{m.changes.length > 0 && ` → ${m.changes.map((c) => `${c.label_ko} ${c.after_ko}`).join(", ")}`}</li>)}</ul>
        </Disclosure>
      )}
    </div>
  )
}
