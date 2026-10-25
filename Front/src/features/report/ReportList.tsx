import { useService } from "../../app/providers"
import { navigate } from "../../app/router"
import { useResource } from "../../state/useResource"
import { Badge, Button, Card, EmptyState, ErrorState, Loading, PageHeader } from "../../ui"
import { date, ko } from "../../lib/format"

export function ReportList() {
  const svc = useService()
  const res = useResource(() => svc.listReports(), [svc])
  const runs = useResource(() => svc.listRuns(), [svc])
  if (res.status === "loading" && !res.data) return <Loading />
  if (res.status === "error") return <ErrorState message={res.error ?? ""} retry={res.reload} />
  const rows = res.data ?? []
  const active = (runs.data ?? []).filter((r) => r.status === "queued" || r.status === "running")
  return (
    <div className="space-y-6">
      <PageHeader eyebrow="분석 리포트" title="저장된 리포트" description="완료된 분석의 리포트입니다. 리포트는 저장 당시의 요청·조건·자료·결과를 그대로 유지하며 프로필을 바꿔도 변하지 않습니다." actions={<Button onClick={() => navigate({ page: "home" })}>새 분석</Button>} />
      {active.length > 0 && (
        <Card className="p-4 text-sm text-slate-700">진행 중인 분석 {active.length}건: {active.map((r, i) => <button key={r.run_id} className="ml-2 font-semibold text-blue-700" onClick={() => navigate({ page: "run", runId: r.run_id })}>{i + 1}번째 실행 ({ko(r.status)}) 보기</button>)}</Card>
      )}
      {rows.length === 0 ? <EmptyState title="아직 리포트가 없습니다" description="홈에서 투자 아이디어를 입력해 첫 분석을 시작해 보세요." action={<Button onClick={() => navigate({ page: "home" })}>새 분석 시작</Button>} /> : (
        <Card className="overflow-hidden">
          <table className="w-full text-sm">
            <thead><tr className="border-b border-slate-200 bg-slate-50 text-left text-xs font-semibold text-slate-500"><th className="px-5 py-3">전략 · 요청 요약</th><th className="px-5 py-3">분석 기준일</th><th className="px-5 py-3">작성일</th><th className="px-5 py-3">상태</th><th className="px-5 py-3"></th></tr></thead>
            <tbody>
              {rows.map((r) => (
                <tr key={r.run_id} className="border-b border-slate-100 hover:bg-slate-50">
                  <td className="px-5 py-3"><p className="font-semibold text-slate-800">{r.strategy_name || r.idea || r.run_id}</p><p className="mt-0.5 line-clamp-1 text-xs text-slate-500">{r.request_summary || r.idea}</p></td>
                  <td className="px-5 py-3 whitespace-nowrap">{r.as_of}</td>
                  <td className="px-5 py-3 whitespace-nowrap">{date(r.created_at)}</td>
                  <td className="px-5 py-3"><Badge tone={r.status === "success" ? "green" : "amber"}>{ko(r.status)}</Badge>{!r.has_report && <Badge tone="slate">리포트 없음</Badge>}{r.mode === "rerun" && <Badge tone="slate">재분석</Badge>}</td>
                  <td className="px-5 py-3 text-right">{r.has_report ? <Button variant="secondary" onClick={() => navigate({ page: "report", reportId: r.report_id ?? r.run_id })}>열기</Button> : <Button variant="ghost" onClick={() => navigate({ page: "run", runId: r.run_id })}>실행 상태 보기</Button>}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </Card>
      )}
    </div>
  )
}
