import { useService } from "../../app/providers"
import { navigate } from "../../app/router"
import { useResource } from "../../state/useResource"
import { useState } from "react"
import { Activity, PencilLine, Trash2 } from "lucide-react"
import { reportName } from "../../lib/reportName"
import { proposedNameOf } from "../../api/proposed"
import { MockTag } from "./proposedView"
import { Button, Card, EmptyState, ErrorState, Loading, Menu, PageHeader } from "../../ui"
import { date, ko } from "../../lib/format"
import { DeleteReportDialog, RenameReportDialog, useRenameTick } from "./ReportName"
import type { PaperSummary, ReportRow } from "../../api/types"
import { reportKey, useNewReports } from "../attention"
import { StartPaperDialog } from "../paper/StartPaperDialog"

const open = (r: ReportRow) => navigate({ page: "report", reportId: r.report_id ?? r.run_id })
const idOf = (r: ReportRow) => r.report_id ?? r.run_id
/** 이 리포트로 시작한 모의투자 (모의투자는 리포트 ID 또는 실행 ID 로 리포트를 가리킨다) */
const papersOf = (papers: PaperSummary[], r: ReportRow) => papers.filter((p) => p.report_id === idOf(r) || p.report_id === r.run_id || p.run_id === r.run_id)

/** 목록 한 줄의 이름·설명. link 이면 누를 수 있는 모양(마우스를 올리면 파란 밑줄). */
function RowText({ r, link, fresh }: { r: ReportRow; link?: boolean; fresh?: boolean }) {
  const name = reportName(r)
  return (
    <>
      <p className="font-semibold text-slate-800">{fresh && <span className="mr-1.5 inline-flex items-center rounded-full bg-red-500 px-1.5 py-px align-[1px] text-[10px] font-bold text-white">새 리포트</span>}<span className={link ? "group-hover:text-blue-700 group-hover:underline" : ""}>{name}</span>{proposedNameOf(r) && <MockTag />}</p>
      {r.request_summary && r.request_summary !== name && <p className="mt-0.5 line-clamp-1 text-xs text-slate-500">{r.request_summary}</p>}
      {r.strategy_name && <p className="mt-0.5 line-clamp-1 text-xs text-slate-400">선택 전략: {r.strategy_name}</p>}
      {!r.has_report && <p className="mt-0.5 text-xs text-slate-400">리포트 없음</p>}
    </>
  )
}

export function ReportList() {
  const svc = useService()
  const renamed = useRenameTick()
  const res = useResource(() => svc.listReports(), [svc, renamed])
  const papers = useResource(() => svc.listPaper(), [svc, renamed])  // 더보기의 「모의투자 보기 / 시작하기」
  const [rename, setRename] = useState<string | null>(null)
  const [removing, setRemoving] = useState<ReportRow | null>(null)
  const [starting, setStarting] = useState<string | null>(null)  // 모의투자를 시작할 리포트 (실행 ID)
  const runs = useResource(() => svc.listRuns(), [svc])
  const fresh = useNewReports(res.data)  // 새로 완료돼 아직 열지 않은 리포트 (열면 표시가 사라진다)
  if (res.status === "loading" && !res.data) return <Loading />
  if (res.status === "error") return <ErrorState message={res.error ?? ""} retry={res.reload} />
  const rows = res.data ?? []
  const active = (runs.data ?? []).filter((r) => r.status === "queued" || r.status === "running")

  /** 더보기: 이름 변경 → 모의투자(연결된 것이 있으면 보기, 없으면 시작하기) → 삭제 */
  const menu = (r: ReportRow) => {
    const items: React.ComponentProps<typeof Menu>["items"] = []
    if (svc.renameReport) items.push({ label: "이름 변경", icon: PencilLine, onClick: () => setRename(idOf(r)) })
    if (papers.data) {  // 모의투자 목록을 받기 전에는 「시작하기」로 잘못 보이지 않게 아무것도 넣지 않는다
      const linked = papersOf(papers.data, r)
      if (linked.length === 0) items.push({ label: "모의투자 시작하기", icon: Activity, onClick: () => setStarting(r.run_id) })
      for (const p of linked) items.push({ label: linked.length > 1 ? `모의투자 보기 · ${p.start_date} 시작` : "모의투자 보기", icon: Activity, onClick: () => navigate({ page: "paper", paperId: p.paper_id }) })
    }
    if (svc.deleteReport) items.push({ label: "삭제", icon: Trash2, danger: true, onClick: () => setRemoving(r) })
    return items
  }

  return (
    <div className="space-y-6">
      <PageHeader eyebrow="분석 리포트" title="저장된 리포트" actions={<Button onClick={() => navigate({ page: "home" })}>새 분석</Button>} />
      {active.length > 0 && (
        <Card className="p-4 text-sm text-slate-700">진행 중인 분석 {active.length}건: {active.map((r, i) => <button key={r.run_id} className="ml-2 font-semibold text-blue-700" onClick={() => navigate({ page: "run", runId: r.run_id })}>{i + 1}번째 실행 ({ko(r.status)}) 보기</button>)}</Card>
      )}
      {rows.length === 0 ? <EmptyState title="아직 리포트가 없습니다" description="홈에서 투자 아이디어를 입력해 첫 분석을 시작해 보세요." action={<Button onClick={() => navigate({ page: "home" })}>새 분석 시작</Button>} /> : (
        <Card className="overflow-hidden">
          <table className="w-full text-sm">
            <thead><tr className="border-b border-slate-200 bg-slate-50 text-left text-xs font-semibold text-slate-500"><th className="px-5 py-3">리포트 · 요청 요약</th><th className="whitespace-nowrap px-5 py-3">리포트 만든 날짜</th><th className="w-16 px-5 py-3"><span className="sr-only">메뉴</span></th></tr></thead>
            <tbody>
              {rows.map((r) => {
                const items = r.has_report ? menu(r) : []
                return (
                  <tr key={r.run_id} data-report={idOf(r)} className="border-b border-slate-100 hover:bg-slate-50">
                    <td className="px-5 py-3">{r.has_report ? (  // 이름·설명을 누르면 리포트를 연다 (따로 「열기」 버튼은 두지 않는다)
                      <button type="button" onClick={() => open(r)} className="group block w-full rounded-lg text-left focus:outline-none focus-visible:ring-2 focus-visible:ring-blue-500"><RowText r={r} link fresh={fresh.has(reportKey(r))} /></button>
                    ) : <RowText r={r} />}</td>
                    <td className="px-5 py-3 whitespace-nowrap text-slate-700">{date(r.created_at)}</td>
                    <td className="px-3 py-3 text-right">{r.has_report
                      ? items.length > 0 && <div className="flex justify-end"><Menu compact items={items} /></div>
                      : <Button variant="ghost" onClick={() => navigate({ page: "run", runId: r.run_id })}>실행 상태 보기</Button>}</td>
                  </tr>
                )
              })}
            </tbody>
          </table>
        </Card>
      )}
      {rename && <RenameReportDialog reportId={rename} close={() => setRename(null)} />}
      {removing && <DeleteReportDialog reportId={idOf(removing)} name={reportName(removing)} close={() => setRemoving(null)} />}
      {starting && <StartPaperDialog reportId={starting} close={() => setStarting(null)} />}
    </div>
  )
}
