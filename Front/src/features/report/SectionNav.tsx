import { BookOpenText, ListChecks, Sigma } from "lucide-react"
import type { ReportDoc } from "../../api/types"
import { Button } from "../../ui"

/** 왼쪽 고정 내비: 한눈에 보기 + 7부분, 모두 접기/펼치기, 작성·기준일, 계산 조건·실행 기록·출처 전체 버튼. */
export function SectionNav({ doc, active, onJump, allOpen, onToggleAll, onCalc, onExec, onSources }: { doc: ReportDoc; active: string; onJump: (id: string) => void; allOpen: boolean; onToggleAll: () => void; onCalc: () => void; onExec: () => void; onSources: () => void }) {
  const h = doc.header
  const total = doc.evidence_summary?.total ?? doc.evidence.length
  const item = (id: string, label: string) => <a key={id} href={`#/reports/${doc.run_id}?sec=${id}`} onClick={(e) => { e.preventDefault(); onJump(id) }} aria-current={active === id ? "true" : undefined} className={`block rounded-lg px-2 py-1.5 ${active === id ? "bg-blue-50 font-semibold text-blue-700" : "text-slate-700 hover:bg-slate-100"}`}>{label}</a>
  return (
    <aside className="sticky top-6 h-fit w-56 shrink-0">
      <p className="text-xs font-bold tracking-wider text-slate-400">섹션</p>
      <nav className="mt-2 space-y-1 text-sm" aria-label="리포트 섹션">
        {doc.summary && item("summary", "한눈에 보기")}
        {doc.nav.map((n, i) => item(n.id, `${i + 1}. ${n.title_ko}`))}
      </nav>
      <button type="button" onClick={onToggleAll} className="mt-3 text-xs font-semibold text-blue-700 hover:underline">{allOpen ? "모두 접기" : "모두 펼치기"}</button>
      <div className="mt-5 space-y-1 text-xs leading-5 text-slate-500">
        <p>작성일 {h.created_at}</p><p>분석 기준일 {h.data_as_of}</p><p>백테스트 {h.backtest_period.start} ~ {h.backtest_period.end}</p><p>종목 선정 기준일 {h.selection_as_of}</p>
      </div>
      <div className="mt-5 space-y-2">
        <Button variant="secondary" className="w-full" onClick={onCalc}><Sigma className="size-4" />계산 조건</Button>
        <Button variant="secondary" className="w-full" onClick={onExec}><ListChecks className="size-4" />실행 기록</Button>
        <Button variant="secondary" className="w-full" onClick={onSources}><BookOpenText className="size-4" />출처 전체 ({total})</Button>
      </div>
    </aside>
  )
}
