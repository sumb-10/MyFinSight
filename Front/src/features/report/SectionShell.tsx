import { useEffect, useId, useState } from "react"
import { ChevronDown } from "lucide-react"

/** 리포트 한 부분: 내 투자조건의 파트 카드와 같은 모양. 질문형 제목 아래에 원래 섹션 이름을 작게 둔다.
 *  내용은 처음 펼칠 때 만들고, 그 뒤로는 접어도 유지해 스크롤 위치가 튀지 않게 한다. */
export function SectionShell({ id, index, title, open, onToggle, children }: { id: string; index: number; title: string; open: boolean; onToggle: () => void; children: React.ReactNode }) {
  const bodyId = useId()
  const [seen, setSeen] = useState(open)
  useEffect(() => { if (open) setSeen(true) }, [open])
  return (
    <section id={`sec-${id}`} className="scroll-mt-16 rounded-2xl border border-slate-300 bg-white shadow-sm" aria-labelledby={`h-${id}`}>
      <h2 id={`h-${id}`}>
        <button type="button" aria-expanded={open} aria-controls={bodyId} onClick={onToggle} className={`flex w-full items-center justify-between gap-3 bg-slate-50 px-5 py-4 text-left transition hover:bg-slate-100 focus:outline-none focus:ring-2 focus:ring-blue-500 sm:px-6 ${open ? "rounded-t-2xl border-b border-slate-200" : "rounded-2xl"}`}>
          <span className="min-w-0">
            <span className="block text-base font-bold text-slate-950">{index}. {title}</span>
          </span>
          <span className="flex shrink-0 items-center gap-1 text-xs font-semibold text-slate-500">{open ? "접기" : "펼치기"}<ChevronDown className={`size-4 transition-transform ${open ? "rotate-180" : ""}`} /></span>
        </button>
      </h2>
      <div id={bodyId} hidden={!open} className="space-y-6 p-4 sm:p-6">{seen ? children : null}</div>
    </section>
  )
}
