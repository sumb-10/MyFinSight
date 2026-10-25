import { useId } from "react"
import { ChevronDown } from "lucide-react"

/** 리포트 한 부분: 번호·제목·접기. 내용은 접어도 마운트를 유지해 스크롤 위치가 튀지 않게 한다. */
export function SectionShell({ id, index, title, open, onToggle, children }: { id: string; index: number; title: string; open: boolean; onToggle: () => void; children: React.ReactNode }) {
  const bodyId = useId()
  return (
    <section id={`sec-${id}`} className="scroll-mt-6" aria-labelledby={`h-${id}`}>
      <div className="mb-4 flex items-center justify-between border-b border-slate-200 pb-2">
        <h2 id={`h-${id}`} className="text-xl font-semibold text-slate-900">{index}. {title}</h2>
        <button type="button" aria-expanded={open} aria-controls={bodyId} onClick={onToggle} className="flex items-center gap-1 rounded-lg px-2 py-1 text-xs font-semibold text-slate-500 hover:bg-slate-100">{open ? "접기" : "펼치기"}<ChevronDown className={`size-4 transition-transform ${open ? "rotate-180" : ""}`} /></button>
      </div>
      <div id={bodyId} hidden={!open} className="space-y-5">{children}</div>
    </section>
  )
}
