import { useEffect, useRef, useState } from "react"
import { ChevronDown, CircleHelp } from "lucide-react"

export type HelpItem = { icon: React.ElementType; label: string; onClick: () => void }

/** 새 분석 카드 머리의 「사용 안내」 (2026-11-18). 서비스 소개 · 홈 화면 둘러보기 · 예시 리포트 둘러보기를 버튼 하나로 모은다.
 *  항목 아래 설명 줄은 두지 않는다 (사용자 결정: 이름만으로 구분됨). 버튼 이름은 처음 「처음이세요?」였으나 다시 보러 온 사람에게 어색해 「사용 안내」로.
 *  Esc · 바깥 클릭 · Tab 으로 메뉴 밖에 초점이 나가면 닫히고, 열면 첫 항목에 초점, 위아래 화살표로 옮긴다. 닫히면 초점은 버튼으로 돌아간다. */
export function HelpMenu({ items, className = "" }: { items: HelpItem[]; className?: string }) {
  const [open, setOpen] = useState(false)
  const box = useRef<HTMLDivElement>(null)
  const btn = useRef<HTMLButtonElement>(null)
  const list = useRef<HTMLUListElement>(null)
  const close = (focus = true) => { setOpen(false); if (focus) btn.current?.focus() }
  useEffect(() => {
    if (!open) return
    list.current?.querySelector<HTMLButtonElement>("[role=menuitem]")?.focus()
    const click = (e: MouseEvent) => { if (!box.current?.contains(e.target as Node)) setOpen(false) }
    window.addEventListener("mousedown", click)
    return () => window.removeEventListener("mousedown", click)
  }, [open])
  const keys = (e: React.KeyboardEvent) => {
    if (e.key === "Escape") { e.stopPropagation(); close(); return }
    if (e.key !== "ArrowDown" && e.key !== "ArrowUp") return
    e.preventDefault()
    const all = [...(list.current?.querySelectorAll<HTMLButtonElement>("[role=menuitem]") ?? [])]
    const at = all.indexOf(document.activeElement as HTMLButtonElement)
    all[(at + (e.key === "ArrowDown" ? 1 : all.length - 1)) % all.length]?.focus()
  }
  return (
    <div ref={box} className="relative" onKeyDown={open ? keys : undefined}
      onBlur={(e) => { if (open && !box.current?.contains(e.relatedTarget as Node | null)) setOpen(false) }}>
      <button ref={btn} type="button" aria-haspopup="menu" aria-expanded={open} onClick={() => setOpen((v) => !v)}
        className={`${className} ${open ? "bg-sunken text-main" : ""}`}>
        <CircleHelp className="size-4" aria-hidden />사용 안내<ChevronDown className={`size-3.5 transition-transform ${open ? "rotate-180" : ""}`} aria-hidden />
      </button>
      {open && (
        <ul ref={list} role="menu" aria-label="사용 안내" className="absolute right-0 top-full z-30 mt-1.5 min-w-48 rounded-box bg-surface p-1.5 shadow-overlay">
          {items.map((it) => (
            <li key={it.label} role="none">
              <button type="button" role="menuitem" onClick={() => { close(false); it.onClick() }}
                className="flex w-full items-center gap-2.5 whitespace-nowrap rounded-control px-3 py-2.5 text-left text-14 font-medium text-main transition hover:bg-sunken focus-visible:bg-sunken focus-visible:outline-none">
                <it.icon className="size-4 shrink-0 text-sub" aria-hidden />{it.label}
              </button>
            </li>
          ))}
        </ul>
      )}
    </div>
  )
}
