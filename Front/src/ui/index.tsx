import { useEffect, useId, useRef, useState } from "react"
import { AlertCircle, AlertTriangle, Check, ChevronDown, ChevronLeft, ChevronRight, Circle, FileSearch, Info, Loader2, MoreHorizontal, ShieldCheck, X } from "lucide-react"
import type { StepStatus } from "../api/types"
import { ko } from "../lib/format"

export const inputClass = "w-full rounded-xl border border-slate-200 bg-white px-3.5 py-2.5 text-sm text-slate-900 outline-none transition placeholder:text-slate-400 focus:border-blue-400 focus:ring-2 focus:ring-blue-100"

export function Button({ children, variant = "primary", className = "", disabled, onClick, type = "button" }: { children: React.ReactNode; variant?: "primary" | "secondary" | "ghost" | "danger"; className?: string; disabled?: boolean; onClick?: () => void; type?: "button" | "submit" }) {
  const variants = { primary: "bg-blue-700 text-white border-blue-700 hover:bg-blue-800", secondary: "bg-white text-blue-700 border-blue-200 hover:bg-blue-50", ghost: "bg-transparent text-slate-600 border-transparent hover:bg-slate-100", danger: "bg-white text-red-700 border-red-200 hover:bg-red-50" }
  return (
    <button type={type} disabled={disabled} onClick={onClick} className={`inline-flex min-h-10 items-center justify-center gap-2 rounded-xl border px-4 py-2 text-sm font-semibold transition focus:outline-none focus:ring-2 focus:ring-blue-500 focus:ring-offset-2 disabled:cursor-not-allowed disabled:opacity-50 ${variants[variant]} ${className}`}>
      {children}
    </button>
  )
}

export function Card({ children, className = "" }: { children: React.ReactNode; className?: string }) {
  return <section className={`rounded-2xl border border-slate-200 bg-white ${className}`}>{children}</section>
}

export function Badge({ children, tone = "blue" }: { children: React.ReactNode; tone?: "blue" | "green" | "amber" | "red" | "slate" }) {
  const tones = { blue: "border-blue-200 bg-blue-50 text-blue-700", green: "border-emerald-200 bg-emerald-50 text-emerald-700", amber: "border-amber-200 bg-amber-50 text-amber-800", red: "border-red-200 bg-red-50 text-red-700", slate: "border-slate-200 bg-slate-50 text-slate-600" }
  return <span className={`inline-flex items-center gap-1 rounded-full border px-2.5 py-1 text-xs font-semibold ${tones[tone]}`}>{children}</span>
}

export function Alert({ title, children, tone = "info" }: { title: string; children?: React.ReactNode; tone?: "info" | "warning" | "error" | "success" }) {
  const tones = { info: "border-blue-200 bg-blue-50 text-blue-950", warning: "border-amber-200 bg-amber-50 text-amber-950", error: "border-red-200 bg-red-50 text-red-950", success: "border-emerald-200 bg-emerald-50 text-emerald-950" }
  const Icon = tone === "error" ? AlertCircle : tone === "success" ? ShieldCheck : tone === "warning" ? AlertTriangle : Info
  return (
    <div className={`flex gap-3 rounded-xl border p-4 ${tones[tone]}`} role={tone === "error" ? "alert" : "status"}>
      <Icon className="mt-0.5 size-5 shrink-0" />
      <div className="min-w-0">
        <p className="text-sm font-semibold">{title}</p>
        {children && <div className="mt-1 text-sm leading-6 opacity-80">{children}</div>}
      </div>
    </div>
  )
}

export function Field({ label, error, help, children }: { label: string; error?: string; help?: string; children: React.ReactNode }) {
  return (
    <label className="block">
      <span className="mb-2 block text-sm font-semibold text-slate-700">{label}</span>
      {children}
      {help && !error && <span className="mt-1.5 block text-xs leading-5 text-slate-500">{help}</span>}
      {error && <span className="mt-1.5 block text-xs font-medium text-red-600">{error}</span>}
    </label>
  )
}

export function PageHeader({ eyebrow, title, description, actions }: { eyebrow?: string; title: string; description?: string; actions?: React.ReactNode }) {
  return (
    <header className="flex items-start justify-between gap-8">
      <div className="max-w-3xl">
        {eyebrow && <p className="mb-2 text-xs font-bold tracking-widest text-blue-700">{eyebrow}</p>}
        <h1 className="text-3xl font-bold tracking-tight text-slate-950">{title}</h1>
        {description && <p className="mt-2 text-sm leading-6 text-slate-600">{description}</p>}
      </div>
      {actions && <div className="flex shrink-0 gap-2">{actions}</div>}
    </header>
  )
}

export function EmptyState({ title, description, action }: { title: string; description: string; action?: React.ReactNode }) {
  return (
    <Card className="flex min-h-72 flex-col items-center justify-center p-8 text-center">
      <FileSearch className="size-10 text-slate-300" />
      <h2 className="mt-4 text-lg font-bold text-slate-900">{title}</h2>
      <p className="mt-2 max-w-md text-sm leading-6 text-slate-500">{description}</p>
      {action && <div className="mt-5">{action}</div>}
    </Card>
  )
}

export function Loading({ label = "불러오는 중입니다…" }: { label?: string }) {
  return <div className="flex items-center gap-2 p-6 text-sm text-slate-500"><Loader2 className="size-4 animate-spin" />{label}</div>
}

export function ErrorState({ title = "불러오지 못했습니다", message, retry }: { title?: string; message: string; retry?: () => void }) {
  return (
    <Alert title={title} tone="error">
      <p>{message}</p>
      {retry && <div className="mt-3"><Button variant="secondary" onClick={retry}>다시 시도</Button></div>}
    </Alert>
  )
}

export function MetricCard({ label, value, note, danger }: { label: string; value: string; note?: string; danger?: boolean }) {
  return (
    <div className={`rounded-xl border p-4 ${danger ? "border-amber-200 bg-amber-50" : "border-slate-200 bg-white"}`}>
      <p className="text-xs font-semibold text-slate-500">{label}</p>
      <p className={`mt-1 text-xl font-bold tabular-nums ${danger ? "text-amber-800" : "text-slate-950"}`}>{value}</p>
      {note && <p className="mt-1 text-[11px] leading-4 text-slate-500">{note}</p>}
    </div>
  )
}

export function StatusRow({ label, status, detail }: { label: string; status: StepStatus; detail?: string | null }) {
  const map: Record<StepStatus, { icon: React.ElementType; classes: string }> = {
    QUEUED: { icon: Circle, classes: "text-slate-400" }, STARTED: { icon: Loader2, classes: "text-blue-700" }, SUCCESS: { icon: Check, classes: "text-emerald-700" },
    PARTIAL: { icon: AlertTriangle, classes: "text-amber-700" }, FAILED: { icon: AlertCircle, classes: "text-red-700" }, CANCELLED: { icon: X, classes: "text-slate-600" },
  }
  const item = map[status]
  return (
    <div className="flex items-start gap-3">
      <item.icon className={`mt-0.5 size-5 shrink-0 ${item.classes} ${status === "STARTED" ? "animate-spin" : ""}`} />
      <div className="min-w-0 flex-1">
        <div className="flex items-center justify-between gap-3">
          <p className={`text-sm font-semibold ${status === "QUEUED" ? "text-slate-400" : "text-slate-800"}`}>{label}</p>
          <span className={`shrink-0 text-xs font-semibold ${item.classes}`}>{ko(status)}</span>
        </div>
        {detail && <p className="mt-1 text-xs leading-5 text-slate-500">{detail}</p>}
      </div>
    </div>
  )
}

export function SidePanel({ title, close, children }: { title: string; close: () => void; children: React.ReactNode }) {
  const closeRef = useRef<HTMLButtonElement>(null)
  useEffect(() => {
    const prev = document.activeElement as HTMLElement | null
    closeRef.current?.focus()
    const handler = (event: KeyboardEvent) => event.key === "Escape" && close()
    window.addEventListener("keydown", handler)
    return () => { window.removeEventListener("keydown", handler); prev?.focus?.() }
  }, [close])
  return (
    <div className="fixed inset-0 z-50 flex" role="dialog" aria-modal="true" aria-label={title}>
      <button aria-label="패널 닫기" className="flex-1 bg-slate-950/30" onClick={close} />
      <aside className="h-full w-[620px] overflow-y-auto bg-white shadow-2xl">
        <header className="sticky top-0 flex items-center justify-between border-b border-slate-200 bg-white px-6 py-5">
          <h2 className="font-bold text-slate-950">{title}</h2>
          <button ref={closeRef} aria-label="닫기" onClick={close} className="rounded-lg p-2 hover:bg-slate-100"><X className="size-5" /></button>
        </header>
        <div className="p-6">{children}</div>
      </aside>
    </div>
  )
}

export function Dialog({ title, close, children }: { title: string; close: () => void; children: React.ReactNode }) {
  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center p-8" role="dialog" aria-modal="true" aria-label={title}>
      <button aria-label="대화상자 닫기" className="absolute inset-0 bg-slate-950/40" onClick={close} />
      <div className="relative max-h-[90vh] w-full max-w-2xl overflow-y-auto rounded-2xl bg-white shadow-2xl">
        <header className="flex items-center justify-between border-b border-slate-200 px-6 py-5">
          <h2 className="font-bold text-slate-950">{title}</h2>
          <button aria-label="닫기" onClick={close} className="rounded-lg p-2 text-slate-500 hover:bg-slate-100"><X className="size-5" /></button>
        </header>
        {children}
      </div>
    </div>
  )
}

export function Chip({ active, onClick, children }: { active?: boolean; onClick: () => void; children: React.ReactNode }) {
  return (
    <button type="button" onClick={onClick} className={`rounded-xl border px-3 py-2 text-left text-sm transition focus:outline-none focus:ring-2 focus:ring-blue-500 ${active ? "border-blue-400 bg-blue-50 text-blue-900" : "border-slate-200 bg-white text-slate-700 hover:bg-slate-50"}`}>
      {children}
    </button>
  )
}


// ───────────────────────── 라운드 4: 접이식·아코디언·페이지·더보기 ─────────────────────────
/** 접이식 영역. 내용은 처음 펼칠 때 마운트한다 (무거운 표·차트를 접어 두면 그리지 않는다). */
export function Disclosure({ title, summary, open: openProp, defaultOpen = false, onToggle, children, className = "", size = "md" }: { title: React.ReactNode; summary?: React.ReactNode; open?: boolean; defaultOpen?: boolean; onToggle?: (open: boolean) => void; children: React.ReactNode; className?: string; size?: "md" | "sm" }) {
  const [own, setOwn] = useState(defaultOpen)
  const open = openProp ?? own
  const [mounted, setMounted] = useState(open)
  useEffect(() => { if (open) setMounted(true) }, [open])
  const id = useId()
  const toggle = () => { const next = !open; if (openProp === undefined) setOwn(next); onToggle?.(next) }
  return (
    <div className={`rounded-xl border border-slate-200 bg-white ${className}`}>
      <button type="button" aria-expanded={open} aria-controls={id} onClick={toggle} className={`flex w-full items-center justify-between gap-3 text-left ${size === "sm" ? "px-4 py-2.5 text-sm" : "px-5 py-3.5"} font-semibold text-slate-800 hover:bg-slate-50 focus:outline-none focus:ring-2 focus:ring-blue-500 rounded-xl`}>
        <span className="min-w-0 truncate">{title}</span>
        <span className="flex shrink-0 items-center gap-3 text-xs font-normal text-slate-500">{summary}<ChevronDown className={`size-4 transition-transform ${open ? "rotate-180" : ""}`} /></span>
      </button>
      <div id={id} hidden={!open} className={open ? `border-t border-slate-100 ${size === "sm" ? "p-4" : "p-5"}` : ""}>{mounted ? children : null}</div>
    </div>
  )
}

/** 아코디언: 항목마다 접이식, 여러 개를 동시에 펼 수 있다. openIds 가 없으면 스스로 관리. */
export function Accordion({ items, openIds, onChange, defaultOpenIds = [] }: { items: { id: string; title: React.ReactNode; summary?: React.ReactNode; body: React.ReactNode }[]; openIds?: string[]; onChange?: (ids: string[]) => void; defaultOpenIds?: string[] }) {
  const [own, setOwn] = useState<string[]>(defaultOpenIds)
  const open = openIds ?? own
  const toggle = (id: string, next: boolean) => { const ids = next ? [...open, id] : open.filter((x) => x !== id); if (openIds === undefined) setOwn(ids); onChange?.(ids) }
  return <div className="space-y-2">{items.map((it) => <div key={it.id} id={`acc-${it.id}`}><Disclosure title={it.title} summary={it.summary} open={open.includes(it.id)} onToggle={(n) => toggle(it.id, n)}>{it.body}</Disclosure></div>)}</div>
}

export function Pagination({ page, pages, onChange, total, pageSize }: { page: number; pages: number; onChange: (p: number) => void; total?: number; pageSize?: number }) {
  if (pages <= 1) return null
  const from = total !== undefined && pageSize ? page * pageSize + 1 : null
  const to = total !== undefined && pageSize ? Math.min(total, (page + 1) * pageSize) : null
  return (
    <nav className="mt-3 flex items-center justify-between text-xs text-slate-600" aria-label="페이지">
      <span>{from !== null ? `${from}–${to} / ${total}건` : ""}</span>
      <span className="flex items-center gap-1">
        <button type="button" aria-label="이전 페이지" disabled={page === 0} onClick={() => onChange(page - 1)} className="rounded-lg border border-slate-200 p-1.5 disabled:opacity-40 hover:bg-slate-50"><ChevronLeft className="size-4" /></button>
        <span className="px-2 tabular-nums">{page + 1} / {pages}</span>
        <button type="button" aria-label="다음 페이지" disabled={page >= pages - 1} onClick={() => onChange(page + 1)} className="rounded-lg border border-slate-200 p-1.5 disabled:opacity-40 hover:bg-slate-50"><ChevronRight className="size-4" /></button>
      </span>
    </nav>
  )
}

/** "더보기 ▾" 메뉴. Escape·바깥 클릭으로 닫힌다. */
export function Menu({ label = "더보기", items }: { label?: string; items: { label: string; onClick: () => void; disabled?: boolean; icon?: React.ElementType }[] }) {
  const [open, setOpen] = useState(false)
  const ref = useRef<HTMLDivElement>(null)
  useEffect(() => {
    if (!open) return
    const key = (e: KeyboardEvent) => e.key === "Escape" && setOpen(false)
    const click = (e: MouseEvent) => { if (ref.current && !ref.current.contains(e.target as Node)) setOpen(false) }
    window.addEventListener("keydown", key); window.addEventListener("mousedown", click)
    return () => { window.removeEventListener("keydown", key); window.removeEventListener("mousedown", click) }
  }, [open])
  return (
    <div ref={ref} className="relative">
      <Button variant="secondary" onClick={() => setOpen((v) => !v)}><MoreHorizontal className="size-4" />{label}</Button>
      {open && (
        <ul role="menu" className="absolute right-0 z-30 mt-1 w-60 overflow-hidden rounded-xl border border-slate-200 bg-white py-1 shadow-xl">
          {items.map((it) => <li key={it.label} role="none"><button role="menuitem" type="button" disabled={it.disabled} onClick={() => { setOpen(false); it.onClick() }} className="flex w-full items-center gap-2 px-4 py-2.5 text-left text-sm text-slate-700 hover:bg-slate-50 disabled:opacity-40">{it.icon && <it.icon className="size-4" />}{it.label}</button></li>)}
        </ul>
      )}
    </div>
  )
}
