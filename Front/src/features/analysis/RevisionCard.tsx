import type { RevisionDraft } from "../../api/types"
import { Badge, Card } from "../../ui"

const show = (v: unknown): string => (v == null ? "–" : Array.isArray(v) ? (v.length ? v.join(", ") : "(없음)") : typeof v === "object" ? JSON.stringify(v) : String(v))

/** 수정 요청(revision) 대화에서 LLM 이 제안하고 코드가 검증한 변경 목록. 지원되지 않는 항목은 이유와 함께 표시한다. */
export function RevisionCard({ rev }: { rev: RevisionDraft }) {
  const ok = rev.changes.filter((c) => c.supported)
  const no = rev.changes.filter((c) => !c.supported)
  return (
    <Card className="p-5 text-sm text-slate-700">
      <p className="text-xs font-bold text-slate-400">수정 요청</p>
      <blockquote className="mt-2 border-l-4 border-amber-200 pl-3 text-[15px] leading-7 text-slate-800">{rev.text}</blockquote>
      {rev.summary_ko && <p className="mt-2 text-slate-600">{rev.summary_ko}</p>}
      {ok.length > 0 && (
        <div className="mt-4">
          <p className="text-xs font-semibold text-slate-500">반영한 변경</p>
          <ul className="mt-1 space-y-1">{ok.map((c) => <li key={c.field}><b>{c.label_ko ?? c.field}</b>: {show(c.base_value)} → <b className="text-blue-700">{show(c.value)}</b>{c.reason_ko ? <span className="ml-2 text-xs text-slate-500">{c.reason_ko}</span> : null}</li>)}</ul>
        </div>
      )}
      {rev.idea_update_ko && <p className="mt-3"><Badge tone="blue">테마 범위 변경</Badge> <span className="ml-1">{rev.idea_update_ko}</span></p>}
      {(no.length > 0 || rev.unsupported_ko.length > 0) && (
        <div className="mt-4 rounded-xl bg-amber-50 p-3 text-amber-950">
          <p className="text-xs font-semibold">반영하지 못한 요청</p>
          <ul className="mt-1 list-disc space-y-1 pl-5">
            {no.map((c, i) => <li key={`${c.field}-${i}`}>{c.label_ko ?? c.field} → {show(c.value)}: {c.note_ko}</li>)}
            {rev.unsupported_ko.map((u, i) => <li key={`u${i}`}>{u}</li>)}
          </ul>
        </div>
      )}
      <p className="mt-3 text-xs text-slate-500">공정한 비교를 위해 백테스트 기간·투자금·적립·비교지수·리밸런싱·종목 범위는 원안과 같게 둡니다. 분석이 끝나면 원안과 나란히 비교한 결과가 만들어집니다.</p>
    </Card>
  )
}
