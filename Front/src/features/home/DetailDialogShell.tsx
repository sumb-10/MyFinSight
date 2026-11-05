import { useEffect, useId, useRef } from "react"
import { X } from "lucide-react"

const FOCUSABLE = 'button:not([disabled]), input:not([disabled]), select:not([disabled]), textarea:not([disabled]), a[href], [tabindex]:not([tabindex="-1"])'

/** 상세 조건 창의 틀: 머리·꼬리는 고정, 가운데 본문만 스크롤. Esc 닫기·창 안 포커스 유지·닫은 뒤 원래 버튼으로 포커스 복귀.
 *  공통 Dialog 는 모의투자 창도 쓰고 이런 동작이 없어, 그 모양과 동작을 바꾸지 않도록 따로 둔다. */
export function DetailDialogShell({ title, close, header, footer, children }: { title: string; close: () => void; header?: React.ReactNode; footer: React.ReactNode; children: React.ReactNode }) {
  const panel = useRef<HTMLDivElement>(null)
  const titleId = useId()
  const closeRef = useRef(close)
  closeRef.current = close
  useEffect(() => {
    const prev = document.activeElement as HTMLElement | null
    const overflow = document.body.style.overflow
    document.body.style.overflow = "hidden"  // 뒤 페이지까지 함께 스크롤되지 않게
    const start = panel.current?.querySelector<HTMLElement>('[role="tab"][aria-selected="true"]') ?? panel.current?.querySelector<HTMLElement>(FOCUSABLE)
    start?.focus()
    const key = (e: KeyboardEvent) => {
      if (e.key === "Escape") { e.stopPropagation(); closeRef.current(); return }
      if (e.key !== "Tab" || !panel.current) return
      const items = [...panel.current.querySelectorAll<HTMLElement>(FOCUSABLE)].filter((el) => el.offsetParent !== null || el === document.activeElement)
      if (!items.length) return
      const first = items[0], last = items[items.length - 1], at = document.activeElement
      if (!panel.current.contains(at)) { e.preventDefault(); first.focus() }
      else if (e.shiftKey && at === first) { e.preventDefault(); last.focus() }
      else if (!e.shiftKey && at === last) { e.preventDefault(); first.focus() }
    }
    window.addEventListener("keydown", key)
    return () => { window.removeEventListener("keydown", key); document.body.style.overflow = overflow; prev?.focus?.() }
  }, [])
  return (
    <div className="fixed inset-0 z-50 m-0! flex items-center justify-center p-2 sm:p-6 [@media(max-height:480px)]:p-1!" role="dialog" aria-modal="true" aria-labelledby={titleId}>
      <button aria-label="대화상자 닫기" tabIndex={-1} className="absolute inset-0 bg-slate-950/40" onClick={close} />
      <div ref={panel} className="relative flex h-full max-h-[820px] w-full min-w-0 max-w-[920px] flex-col overflow-hidden rounded-2xl bg-white shadow-2xl">
        <header className="shrink-0 border-b border-slate-200 bg-white px-4 pt-4 sm:px-6 sm:pt-5 [@media(max-height:480px)]:pt-2!">
          <div className="flex items-start justify-between gap-3">
            <h2 id={titleId} className="min-w-0 text-lg font-bold text-slate-950">{title}</h2>
            <button aria-label="닫기" onClick={close} className="-mr-2 -mt-1 shrink-0 rounded-lg p-2 text-slate-500 hover:bg-slate-100 focus:outline-none focus:ring-2 focus:ring-blue-500"><X className="size-5" /></button>
          </div>
          {header}
        </header>
        <div className="min-h-0 flex-1 overflow-y-auto overscroll-contain bg-slate-50 px-3 py-4 sm:px-6 sm:py-6 [@media(max-height:480px)]:py-2!">{children}</div>
        <footer className="shrink-0 border-t border-slate-200 bg-white px-4 py-3 sm:px-6 [@media(max-height:480px)]:py-1!">{footer}</footer>
      </div>
    </div>
  )
}
