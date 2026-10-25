import { useService } from "../../app/providers"
import { navigate } from "../../app/router"
import type { ComparisonDoc } from "../../api/types"
import { useResource } from "../../state/useResource"
import { Alert, Badge, Button, Card, EmptyState, Loading, PageHeader } from "../../ui"
import { fmt, ko, weight } from "../../lib/format"

const show = (v: unknown): string => (v == null ? "–" : Array.isArray(v) ? (v.length ? v.join(", ") : "(없음)") : typeof v === "object" ? JSON.stringify(v) : String(v))
const cell = (v: number | null, f: "pct" | "usd" | "num") => (v == null ? "–" : f === "pct" ? fmt(v, "pct") : f === "usd" ? fmt(v, "usd") : v.toFixed(2))
/** 수정안이 나은가: 변동성은 낮을수록, 최대낙폭(음수)은 0 에 가까울수록(= 값이 클수록), 나머지는 클수록 좋다. */
export const better = (m: string, b: number | null, r: number | null) => (b == null || r == null ? null : m === "ann_vol" ? r < b : r > b)

/** 원안 vs 수정안 비교 (#/comparisons/:id). 서버가 두 결과 묶음에서 옮겨 적은 값만 보여 준다. */
export function ComparisonScreen({ comparisonId }: { comparisonId: string }) {
  const svc = useService()
  const res = useResource(() => svc.getComparison(comparisonId), [svc, comparisonId])
  if (res.status === "loading" && !res.data) return <Loading label="비교 결과를 불러오는 중…" />
  if (res.status === "error" || !res.data) {
    const code = res.errorCode
    return <EmptyState title={code === "COMPARISON_NOT_READY" ? "수정안 분석이 아직 끝나지 않았습니다" : "비교 결과를 열 수 없습니다"} description={res.error ?? ""}
      action={<div className="flex gap-2"><Button variant="secondary" onClick={() => navigate({ page: "run", runId: comparisonId.replace(/^cmp_/, "") })}>실행 상태 보기</Button><Button variant="ghost" onClick={res.reload}>다시 시도</Button></div>} />
  }
  const d: ComparisonDoc = res.data
  const pros = d.pros_cons_ko?.pros_ko ?? []
  const cons = d.pros_cons_ko?.cons_ko ?? []
  return (
    <div className="space-y-8">
      <PageHeader eyebrow={`수정안 비교 · ${d.comparison_id}`} title="원안과 수정안을 나란히 봅니다" description={d.revision_text ? `수정 요청: “${d.revision_text}”` : undefined}
        actions={<><Button variant="secondary" onClick={() => navigate({ page: "report", reportId: d.base_report_id })}>원안 리포트</Button><Button onClick={() => navigate({ page: "report", reportId: d.revised_report_id })}>수정안 리포트</Button></>} />
      <div className="flex flex-wrap gap-2 text-sm">
        <Badge tone="slate">평가 기간 {d.window.start} ~ {d.window.end}</Badge>
        <Badge tone={d.same_window ? "green" : "red"}>{d.same_window ? "같은 평가 조건" : "평가 조건 다름"}</Badge>
        {d.base_chosen_label_ko && <Badge tone="slate">원안 선택안: {d.base_chosen_label_ko}</Badge>}
        {d.revised_chosen_label_ko && <Badge tone="blue">수정안 선택안: {d.revised_chosen_label_ko}</Badge>}
      </div>
      {d.warnings.map((w, i) => <Alert key={i} tone="warning" title="주의">{w}</Alert>)}
      {d.revision_changes && d.revision_changes.length > 0 && (
        <Card className="p-5 text-sm">
          <h2 className="mb-2 text-base font-semibold text-slate-900">바꾼 조건</h2>
          <ul className="space-y-1">{d.revision_changes.map((c, i) => <li key={i} className={c.supported ? "" : "text-slate-400 line-through"}><b>{c.label_ko ?? c.field}</b>: {show(c.base_value)} → <b className="text-blue-700">{show(c.value)}</b>{!c.supported && c.note_ko ? ` (${c.note_ko})` : ""}</li>)}</ul>
        </Card>
      )}
      {d.performance_table.length > 0 && (
        <Card className="overflow-hidden">
          <div className="px-5 pt-5"><h2 className="text-base font-semibold text-slate-900">성과 비교 (선택안 기준)</h2><p className="mt-1 text-xs text-slate-500">{d.same_window ? "같은 기간·자본·적립·비교지수로 계산한 과거 백테스트 값입니다. 앞으로의 성과 차이를 뜻하지 않습니다." : "평가 창이 달라 두 값을 그대로 비교하면 안 됩니다. 참고로만 보세요."}</p></div>
          <table className="mt-3 w-full text-sm">
            <thead className="bg-slate-50 text-left text-xs font-semibold text-slate-500"><tr><th className="px-5 py-2">지표</th><th className="px-5 py-2 text-right">원안</th><th className="px-5 py-2 text-right">수정안</th><th className="px-5 py-2 text-right">차이</th><th className="px-5 py-2 text-right">비교지수</th></tr></thead>
            <tbody>
              {d.performance_table.map((r) => { const b = better(r.metric, r.base, r.revised); const diff = r.base != null && r.revised != null ? r.revised - r.base : null; return (
                <tr key={r.metric} className="border-t border-slate-100"><td className="px-5 py-2 font-medium text-slate-800">{r.label_ko}</td><td className="px-5 py-2 text-right">{cell(r.base, r.format)}</td><td className={`px-5 py-2 text-right font-semibold ${b == null ? "" : b ? "text-emerald-700" : "text-red-700"}`}>{cell(r.revised, r.format)}</td><td className="px-5 py-2 text-right text-slate-500">{diff == null ? "–" : (diff >= 0 ? "+" : "") + cell(diff, r.format)}</td><td className="px-5 py-2 text-right text-slate-500">{cell(r.benchmark, r.format)}</td></tr>
              ) })}
            </tbody>
          </table>
        </Card>
      )}
      <div className="grid gap-6 lg:grid-cols-2">
        <Card className="p-5 text-sm">
          <h2 className="mb-2 text-base font-semibold text-slate-900">종목 변화</h2>
          <p><Badge tone="green">추가 {d.ticker_changes.added.length}</Badge> <span className="ml-1">{d.ticker_changes.added.join(", ") || "없음"}</span></p>
          <p className="mt-2"><Badge tone="red">제외 {d.ticker_changes.removed.length}</Badge> <span className="ml-1">{d.ticker_changes.removed.join(", ") || "없음"}</span></p>
          <p className="mt-2"><Badge tone="slate">유지 {d.ticker_changes.kept.length}</Badge> <span className="ml-1 text-slate-600">{d.ticker_changes.kept.join(", ") || "없음"}</span></p>
        </Card>
        <Card className="p-5 text-sm">
          <h2 className="mb-2 text-base font-semibold text-slate-900">조건 검증 (규칙별)</h2>
          <table className="w-full"><thead className="text-left text-xs font-semibold text-slate-500"><tr><th className="py-1">규칙</th><th className="py-1">원안</th><th className="py-1">수정안</th></tr></thead>
            <tbody>{d.rule_changes.map((r) => <tr key={r.rule} className={`border-t border-slate-100 ${r.changed ? "bg-blue-50/40" : ""}`}><td className="py-1">{r.rule} {r.label_ko}</td><td className="py-1">{r.base ? ko(r.base) : "–"}</td><td className="py-1 font-medium">{r.revised ? ko(r.revised) : "–"}</td></tr>)}</tbody></table>
          <p className="mt-2 text-xs text-slate-500">원안 통과/주의/미통과 {d.base_validation?.n_pass ?? "–"}/{d.base_validation?.n_warn ?? "–"}/{d.base_validation?.n_fail ?? "–"} · 수정안 {d.revised_validation?.n_pass ?? "–"}/{d.revised_validation?.n_warn ?? "–"}/{d.revised_validation?.n_fail ?? "–"}</p>
        </Card>
      </div>
      <Card className="p-5 text-sm">
        <h2 className="mb-2 text-base font-semibold text-slate-900">비중 변화 (선택안 목표 비중)</h2>
        <div className="max-h-80 overflow-auto"><table className="w-full"><thead className="text-left text-xs font-semibold text-slate-500"><tr><th className="py-1">종목</th><th className="py-1 text-right">원안</th><th className="py-1 text-right">수정안</th><th className="py-1 text-right">차이</th></tr></thead>
          <tbody>{d.weight_changes.map((w) => <tr key={w.ticker} className="border-t border-slate-100"><td className="py-1 font-medium">{w.ticker}</td><td className="py-1 text-right text-slate-500">{weight(w.base)}</td><td className="py-1 text-right">{weight(w.revised)}</td><td className={`py-1 text-right ${Math.abs(w.delta) > 0.0005 ? (w.delta > 0 ? "text-emerald-700" : "text-red-700") : "text-slate-400"}`}>{(w.delta >= 0 ? "+" : "") + weight(w.delta)}</td></tr>)}</tbody></table></div>
      </Card>
      {d.condition_changes.length > 0 && (
        <Card className="p-5 text-sm"><h2 className="mb-2 text-base font-semibold text-slate-900">요청 조건 차이</h2>
          <ul className="space-y-1">{d.condition_changes.map((c) => <li key={c.field}><b>{c.label_ko}</b>: {show(c.base)} → <b>{show(c.revised)}</b></li>)}</ul></Card>
      )}
      {(pros.length > 0 || cons.length > 0) && (
        <div className="grid gap-6 lg:grid-cols-2">
          <Card className="p-5 text-sm"><h2 className="mb-2 text-base font-semibold text-emerald-800">수정안이 나은 점</h2><ul className="list-disc space-y-1 pl-5">{pros.map((x, i) => <li key={i}>{x}</li>)}</ul></Card>
          <Card className="p-5 text-sm"><h2 className="mb-2 text-base font-semibold text-red-800">수정안이 불리한 점</h2><ul className="list-disc space-y-1 pl-5">{cons.map((x, i) => <li key={i}>{x}</li>)}{cons.length === 0 && <li className="list-none text-slate-500">표에서 불리한 항목이 없습니다.</li>}</ul></Card>
        </div>
      )}
      <p className="pb-6 text-xs text-slate-400">{d.pros_cons_ko?.note_ko} · 생성 {d.created_at}</p>
    </div>
  )
}
