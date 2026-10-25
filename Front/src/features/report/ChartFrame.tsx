import { useEffect, useRef, useState } from "react"
import { Table2 } from "lucide-react"
import type { Column } from "../../api/types"
import { fmt } from "../../lib/format"

/** 차트 공통 틀: 제목 · 캡션(기간·단위·기준일·표본) · "표로 보기" 전환 · 접근성 라벨. 차트 자체는 children. */
export function ChartFrame({ title, caption, ariaLabel, table, height = 320, children, note, controls, footer }: { title: string; caption?: string; ariaLabel?: string; table?: { columns: Column[]; rows: Record<string, unknown>[] }; height?: number; children: React.ReactNode; note?: string; controls?: React.ReactNode; footer?: React.ReactNode }) {
  const [asTable, setAsTable] = useState(false)
  return (
    <figure className="overflow-hidden rounded-xl border border-slate-200 bg-white p-5">
      <figcaption className="mb-3 flex items-start justify-between gap-3">
        <div className="min-w-0"><h3 className="text-base font-semibold text-slate-900">{title}</h3>{caption && <p className="mt-0.5 text-xs text-slate-500">{caption}</p>}</div>
        {table && <button type="button" aria-pressed={asTable} onClick={() => setAsTable((v) => !v)} className="flex shrink-0 items-center gap-1 rounded-lg border border-slate-200 px-2.5 py-1.5 text-xs font-semibold text-slate-600 hover:bg-slate-50"><Table2 className="size-3.5" />{asTable ? "차트로 보기" : "표로 보기"}</button>}
      </figcaption>
      {controls && !asTable && <div className="mb-3">{controls}</div>}
      {asTable && table ? (
        <div className="max-h-96 overflow-auto"><table className="w-full text-xs"><thead><tr className="border-b border-slate-200 text-left text-slate-500">{table.columns.map((c) => <th key={c.key} className="px-2 py-1 whitespace-nowrap">{c.label_ko}</th>)}</tr></thead>
          <tbody>{table.rows.map((r, i) => <tr key={i} className="border-b border-slate-100">{table.columns.map((c) => <td key={c.key} className={`px-2 py-1 ${typeof r[c.key] === "number" ? "text-right tabular-nums" : ""}`}>{c.format && c.format !== "text" ? fmt(r[c.key], c.format) : String(r[c.key] ?? "–")}</td>)}</tr>)}</tbody></table></div>
      ) : (
        <LazyMount height={height}><div role="img" aria-label={ariaLabel ?? title} style={{ height }}>{children}</div></LazyMount>
      )}
      {footer && !asTable && <div className="mt-2">{footer}</div>}
      {note && <p className="mt-2 text-xs text-slate-500">{note}</p>}
    </figure>
  )
}

/** 화면에 들어올 때 마운트 (높이는 고정해 레이아웃이 튀지 않게). IntersectionObserver 가 없으면 바로 그린다. */
export function LazyMount({ height, children }: { height: number; children: React.ReactNode }) {
  const ref = useRef<HTMLDivElement>(null)
  const [show, setShow] = useState(typeof IntersectionObserver === "undefined")
  useEffect(() => {
    if (show || !ref.current) return
    const io = new IntersectionObserver((es) => { if (es.some((e) => e.isIntersecting)) { setShow(true); io.disconnect() } }, { rootMargin: "200px" })
    io.observe(ref.current)
    return () => io.disconnect()
  }, [show])
  return <div ref={ref} style={{ minHeight: height }}>{show ? children : null}</div>
}
