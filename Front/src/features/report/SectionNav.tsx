import { useCallback, useEffect, useRef, useState } from "react"
import { BookOpen, ChevronLeft, ChevronRight } from "lucide-react"
import type { ReportDoc } from "../../api/types"
import { groupsFor } from "./navGroups"

/** 사용자에게 보이는 섹션 제목 (질문형). 섹션 ID 는 서버 것 그대로 쓰고, 모르는 섹션은 서버 제목을 쓴다. */
export const SECTION_TITLE: Record<string, string> = {
  summary: "투자 결과 요약",
  verdict: "왜 이런 투자 전략이 선택되었나요?",
  construction: "투자 종목과 비중은 어떻게 결정됐나요?",
  companies: "왜 이 기업들을 선택했나요?",
  market: "시장과 뉴스는 어떻게 분석했나요?",
  performance: "과거 투자 성과는 어땠나요?",
  history: "내 요청이 어떻게 반영되었나요?",
  assumptions: "투자 전에 무엇을 주의해야 하나요?",
  references: "어떤 자료를 근거로 분석했나요?",
}
export const sectionTitle = (id: string, fallback: string) => SECTION_TITLE[id] ?? fallback
export const HISTORY_TITLE = SECTION_TITLE.history

/** 상단 탭에 쓰는 짧은 이름. 섹션 안의 제목은 위 질문형 그대로다. */
export const TAB_LABEL: Record<string, string> = {
  summary: "결과 요약", verdict: "판단 이유", construction: "종목·비중", companies: "기업", market: "시장·뉴스",
  performance: "과거 성과", history: "내 요청", assumptions: "주의 사항", references: "자료",
}

/** 탭 목록: 결과 요약 + 서버 섹션 (요청 내역은 「전제」 앞, 없으면 맨 뒤). 모르는 섹션은 서버 이름. */
export function tabList(doc: ReportDoc): [string, string][] {
  const list = doc.nav.map((n) => [n.id, TAB_LABEL[n.id] ?? n.title_ko] as [string, string])
  const at = list.findIndex(([id]) => id === "assumptions")
  list.splice(at < 0 ? list.length : at, 0, ["history", TAB_LABEL.history])
  return [...(doc.summary ? [["summary", TAB_LABEL.summary] as [string, string]] : []), ...list]
}

/** 상단 고정 가로 탭: 리포트 헤더의 맨 아랫줄(구분선 위 밑줄 탭)이고, 스크롤하면 이 줄만 화면 위에 남는다. 배경은 페이지와 같은 색이라 헤더와 한 덩어리로 보인다.
 *  탭 줄만 가로로 움직이고(넘치면 양끝 화살표), 지금 보는 섹션에 밑줄을 둔다. ←/→·Home/End 로 탭 사이를 옮긴다. 오른쪽 끝의 「투자 용어 설명」은 줄과 함께 고정된다. */
export function ReportTabs({ doc, active, onJump, onGlossary }: { doc: ReportDoc; active: string; onJump: (groupId: string) => void; onGlossary: () => void }) {
  const list = groupsFor(doc).map((g) => [g.id, g.label] as [string, string])  // 상단 탭은 묶음(navGroups) 단위. active·onJump 도 묶음 ID
  const strip = useRef<HTMLDivElement>(null)
  const [edge, setEdge] = useState({ l: false, r: false })
  const sync = useCallback(() => { const el = strip.current; if (el) setEdge({ l: el.scrollLeft > 2, r: el.scrollLeft + el.clientWidth < el.scrollWidth - 2 }) }, [])
  useEffect(() => {
    sync()
    const el = strip.current
    if (!el || typeof ResizeObserver === "undefined") return
    const ro = new ResizeObserver(sync)
    ro.observe(el)
    return () => ro.disconnect()
  }, [sync])
  useEffect(() => {  // 활성 탭이 줄 밖이면 줄만 움직여 보이게 (페이지는 움직이지 않는다)
    const box = strip.current, tab = box?.querySelector<HTMLElement>('[aria-current="true"]')
    if (!box || !tab) return
    const l = tab.offsetLeft, r = l + tab.offsetWidth, pad = 32
    if (l < box.scrollLeft + pad) box.scrollLeft = Math.max(0, l - pad)
    else if (r > box.scrollLeft + box.clientWidth - pad) box.scrollLeft = r - box.clientWidth + pad
  }, [active])
  const onKey = (e: React.KeyboardEvent<HTMLDivElement>) => {
    const tabs = Array.from(strip.current?.querySelectorAll<HTMLButtonElement>("button[data-tab]") ?? [])
    const i = tabs.indexOf(document.activeElement as HTMLButtonElement)
    if (i < 0) return
    const next = e.key === "ArrowRight" ? i + 1 : e.key === "ArrowLeft" ? i - 1 : e.key === "Home" ? 0 : e.key === "End" ? tabs.length - 1 : null
    if (next === null) return
    e.preventDefault()
    tabs[Math.max(0, Math.min(tabs.length - 1, next))]?.focus()
  }
  const nudge = (d: number) => strip.current?.scrollBy({ left: d * Math.max(160, (strip.current?.clientWidth ?? 0) * 0.6), behavior: "smooth" })
  const arrow = "absolute inset-y-0 z-10 flex w-9 items-center bg-slate-50 text-slate-500 hover:text-slate-900"
  return (
    <div className="sticky top-0 z-30 -mx-4 border-b border-slate-200 bg-slate-50 px-4 lg:-mx-10 lg:px-10">
      <div className="flex h-12 items-stretch gap-2">
        <div className="relative min-w-0 flex-1">
          {edge.l && <button type="button" tabIndex={-1} aria-hidden onClick={() => nudge(-1)} className={`${arrow} left-0 justify-start`}><ChevronLeft className="size-4" /></button>}
          <div ref={strip} onScroll={sync} onKeyDown={onKey} className="report-tabs relative flex h-full items-stretch overflow-x-auto">
            <nav aria-label="리포트 섹션" className="flex items-stretch gap-1">
              {list.map(([id, label]) => (
                <button key={id} type="button" data-tab={id} onClick={() => onJump(id)} aria-current={active === id ? "true" : undefined}
                  className={`shrink-0 whitespace-nowrap border-b-2 px-3 text-sm font-semibold transition focus:outline-none focus-visible:bg-blue-50 focus-visible:ring-2 focus-visible:ring-inset focus-visible:ring-blue-500 ${active === id ? "border-blue-600 text-blue-700" : "border-transparent text-slate-500 hover:border-slate-300 hover:text-slate-900"}`}>{label}</button>
              ))}
            </nav>
          </div>
          {edge.r && <button type="button" tabIndex={-1} aria-hidden onClick={() => nudge(1)} className={`${arrow} right-0 justify-end`}><ChevronRight className="size-4" /></button>}
        </div>
        <button type="button" onClick={onGlossary} aria-label="투자 용어 설명" data-tour="glossary" className="my-auto inline-flex shrink-0 items-center gap-1.5 rounded-lg border border-slate-200 bg-white px-3 py-1.5 text-sm font-semibold text-slate-700 hover:bg-slate-100 focus:outline-none focus:ring-2 focus:ring-blue-500">
          <BookOpen className="size-4" aria-hidden /><span className="hidden sm:inline">투자 용어 설명</span><span className="sm:hidden">용어</span>
        </button>
      </div>
    </div>
  )
}
