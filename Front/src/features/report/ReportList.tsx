import { useService } from "../../app/providers"
import { navigate } from "../../app/router"
import { useResource } from "../../state/useResource"
import { useState } from "react"
import { PencilLine, Trash2 } from "lucide-react"
import { reportName } from "../../lib/reportName"
import { proposedNameOf } from "../../api/proposed"
import { MockTag } from "./proposedView"
import { Badge, Button, Card, EmptyState, ErrorState, Loading, Menu, PageHeader } from "../../ui"
import { date, ko } from "../../lib/format"
import { DeleteReportDialog, RenameReportDialog, useRenameTick } from "./ReportName"
import type { ReportRow } from "../../api/types"

const open = (r: ReportRow) => navigate({ page: "report", reportId: r.report_id ?? r.run_id })

/** 목록 한 줄의 이름·설명. link 이면 누를 수 있는 모양(마우스를 올리면 파란 밑줄). */
function RowText({ r, link }: { r: ReportRow; link?: boolean }) {
  const name = reportName(r)
  return (
    <>
      <p className="font-semibold text-slate-800"><span className={link ? "group-hover:text-blue-700 group-hover:underline" : ""}>{name}</span>{proposedNameOf(r) && <MockTag />}</p>
      {r.request_summary && r.request_summary !== name && <p className="mt-0.5 line-clamp-1 text-xs text-slate-500">{r.request_summary}</p>}
      {r.strategy_name && <p className="mt-0.5 line-clamp-1 text-xs text-slate-400">선택 전략: {r.strategy_name}</p>}
    </>
  )
}

export function ReportList() {
  const svc = useService()
  const renamed = useRenameTick()
  const res = useResource(() => svc.listReports(), [svc, renamed])
  const [rename, setRename] = useState<string | null>(null)
  const [removing, setRemoving] = useState<ReportRow | null>(null)
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
            <thead><tr className="border-b border-slate-200 bg-slate-50 text-left text-xs font-semibold text-slate-500"><th className="px-5 py-3">리포트 · 요청 요약</th><th className="px-5 py-3">분석 기준일</th><th className="px-5 py-3">작성일</th><th className="px-5 py-3">상태</th><th className="px-5 py-3"></th></tr></thead>
            <tbody>
              {rows.map((r) => (
                <tr key={r.run_id} className="border-b border-slate-100 hover:bg-slate-50">
                  <td className="px-5 py-3">{r.has_report ? (  // 이름·설명을 누르면 리포트를 연다 (따로 「열기」 버튼은 두지 않는다)
                    <button type="button" onClick={() => open(r)} className="group block w-full rounded-lg text-left focus:outline-none focus-visible:ring-2 focus-visible:ring-blue-500"><RowText r={r} link /></button>
                  ) : <RowText r={r} />}</td>
                  <td className="px-5 py-3 whitespace-nowrap">{r.as_of}</td>
                  <td className="px-5 py-3 whitespace-nowrap">{date(r.created_at)}</td>
                  <td className="px-5 py-3"><Badge tone={r.status === "success" ? "green" : "amber"}>{ko(r.status)}</Badge>{!r.has_report && <Badge tone="slate">리포트 없음</Badge>}{r.mode === "rerun" && <Badge tone="slate">재분석</Badge>}</td>
                  <td className="px-5 py-3 text-right">{r.has_report ? (
                    // 삭제·이름 변경(제안 기능)은 서비스에 메서드가 있을 때만 — 지금은 목업뿐. 일반 모드는 이 칸이 비어 있다.
                    (svc.deleteReport || svc.renameReport) && <div className="flex justify-end gap-2">
                      {svc.deleteReport && <Button variant="danger" onClick={() => setRemoving(r)}><Trash2 className="size-4" />삭제</Button>}
                      {svc.renameReport && <Menu items={[{ label: "이름 변경", icon: PencilLine, onClick: () => setRename(r.report_id ?? r.run_id) }]} />}
                    </div>
                  ) : <Button variant="ghost" onClick={() => navigate({ page: "run", runId: r.run_id })}>실행 상태 보기</Button>}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </Card>
      )}
      {rename && <RenameReportDialog reportId={rename} close={() => setRename(null)} />}
      {removing && <DeleteReportDialog reportId={removing.report_id ?? removing.run_id} name={reportName(removing)} close={() => setRemoving(null)} />}
    </div>
  )
}
