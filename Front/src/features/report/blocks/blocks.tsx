import { createContext, useContext, useMemo, useState } from "react"
import { Area, AreaChart, Bar, BarChart, CartesianGrid, Cell, Line, LineChart, Pie, PieChart, ReferenceLine, ResponsiveContainer, Tooltip, XAxis, YAxis } from "recharts"
import type { AreaBlock, BarBlock, Block, CardsBlock, DonutBlock, EvidenceRefBlock, FunnelBlock, Kpi, LineBlock, ReportDoc, TableBlock, WeightsCompareBlock } from "../../../api/types"
import { CITE_RE } from "../../../lib/citations"
import { colorOf, fmt, ko, OTHER_COLOR, PALETTE } from "../../../lib/format"
import { Pagination } from "../../../ui"
import { ChartFrame } from "../ChartFrame"
import { useReport } from "../context"
import { CompanyList } from "../CompanyList"
import { RebalanceTimeline } from "../RebalanceTimeline"

const card = "rounded-xl border border-slate-200 bg-white p-5"
const h3 = "mb-3 text-base font-semibold text-slate-900"
const PAGE_ROWS = 25
const DONUT_TOP = 8

/** 인용 ID 클릭 시 출처 패널을 여는 콜백. ReportDetail 이 제공한다. */
export const CitationContext = createContext<{ onCite: (id: string) => void; label: (id: string) => string } | null>(null)

export function CitedText({ text }: { text: string }) {
  const ctx = useContext(CitationContext)
  const parts: React.ReactNode[] = []
  let last = 0
  for (const m of text.matchAll(CITE_RE)) {
    const start = m.index ?? 0
    if (start > last) parts.push(text.slice(last, start))
    const id = m[1]
    parts.push(
      ctx ? (
        <button key={`${id}-${start}`} type="button" onClick={() => ctx.onCite(id)} aria-label={`근거 ${id} 보기`} className="mx-0.5 align-super text-[11px] font-bold text-blue-700 hover:underline">[{ctx.label(id)}]</button>
      ) : (
        <span key={`${id}-${start}`} className="mx-0.5 align-super text-[11px] font-bold text-slate-500">[{id}]</span>
      ),
    )
    last = start + m[0].length
  }
  if (last < text.length) parts.push(text.slice(last))
  return <>{parts}</>
}

export function Paragraphs({ items, tone }: { items: string[]; tone?: "lead" }) {
  return (
    <div className={tone === "lead" ? "space-y-4 text-[15.5px] leading-7 text-slate-800" : "space-y-3 text-[15px] leading-7 text-slate-700"}>
      {items.map((t, i) => <p key={i} className="max-w-3xl whitespace-pre-line"><CitedText text={t} /></p>)}
    </div>
  )
}

export function KpiCards({ kpis, ids }: { kpis: Kpi[]; ids: string[] }) {
  const sel = ids.map((id) => kpis.find((k) => k.id === id)).filter(Boolean) as Kpi[]
  return (
    <div className="grid grid-cols-3 gap-3">
      {sel.map((k) => (
        <div key={k.id} className={card}>
          <div className="text-xs font-medium text-slate-500">{k.label_ko}</div>
          <div className="mt-1 text-2xl font-semibold tabular-nums text-slate-900">{fmt(k.value, k.format)}</div>
          {k.note_ko && <div className="mt-1 text-xs text-slate-500">{k.note_ko}</div>}
        </div>
      ))}
    </div>
  )
}

/** 표: 25행이 넘으면 페이지로. 셀 값이 인용 ID 면 버튼으로. */
export function DataTable({ b }: { b: TableBlock }) {
  const [page, setPage] = useState(0)
  const ctx = useContext(CitationContext)
  const pages = Math.max(1, Math.ceil(b.rows.length / PAGE_ROWS))
  const rows = b.rows.length > PAGE_ROWS ? b.rows.slice(page * PAGE_ROWS, (page + 1) * PAGE_ROWS) : b.rows
  const isCite = (v: unknown) => typeof v === "string" && /^(ev\d+|dc\d+|fin:\S+|calc:\S+)$/.test(v)
  return (
    <div className={card}>
      {b.title_ko && <h3 className={h3}>{b.title_ko}</h3>}
      <div className="overflow-x-auto">
        <table className="w-full min-w-[720px] border-collapse text-sm">
          <thead>
            <tr className="border-b border-slate-200 text-left text-xs font-semibold text-slate-500">
              {b.columns.map((c) => <th key={c.key} className="px-2 py-2 whitespace-nowrap">{c.label_ko}</th>)}
            </tr>
          </thead>
          <tbody>
            {rows.map((r, i) => (
              <tr key={i} className="border-b border-slate-100 align-top">
                {b.columns.map((c) => {
                  const v = r[c.key]; const num = typeof v === "number"
                  if (c.format === "url") {
                    const href = typeof v === "string" && v ? v : null
                    return <td key={c.key} className="px-2 py-2">{href ? <a href={href} target="_blank" rel="noreferrer" className="text-blue-700 underline underline-offset-2">원문</a> : "–"}</td>
                  }
                  if (ctx && isCite(v)) return <td key={c.key} className="px-2 py-2"><button type="button" onClick={() => ctx.onCite(v as string)} className="font-mono text-xs text-blue-700 hover:underline" aria-label={`근거 ${v} 보기`}>[{ctx.label(v as string)}]</button></td>
                  return <td key={c.key} className={`px-2 py-2 ${num ? "tabular-nums whitespace-nowrap text-right" : "text-slate-700"}`}>{c.format === "text" || c.format === undefined ? String(v ?? "–") : fmt(v, c.format)}</td>
                })}
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      <Pagination page={page} pages={pages} onChange={setPage} total={b.rows.length} pageSize={PAGE_ROWS} />
      {b.note_ko && <p className="mt-2 text-xs text-slate-500">{b.note_ko}</p>}
    </div>
  )
}

/** 도넛: 상위 8 + 기타. 색은 라벨(티커) 고정. */
export function Donut({ b }: { b: DonutBlock }) {
  const sorted = [...b.items].filter((x) => x.value > 1e-6).sort((a, c) => c.value - a.value)
  const top = sorted.slice(0, DONUT_TOP), rest = sorted.slice(DONUT_TOP)
  const items = rest.length ? [...top, { label: `기타 ${rest.length}종목`, value: rest.reduce((s, x) => s + x.value, 0) }] : top
  const order = top.map((x) => x.label)
  const total = sorted.reduce((s, x) => s + x.value, 0)
  const color = (label: string) => (label.startsWith("기타") ? OTHER_COLOR : colorOf(label, order))
  return (
    <div className={card}>
      <h3 className={h3}>{b.title_ko}</h3>
      <div className="flex items-center gap-6">
        <div className="h-52 w-52 shrink-0" role="img" aria-label={`${b.title_ko} 도넛`}>
          <ResponsiveContainer width="100%" height="100%">
            <PieChart>
              <Pie data={items} dataKey="value" nameKey="label" innerRadius={56} outerRadius={94} paddingAngle={1} isAnimationActive={false}>{items.map((x) => <Cell key={x.label} fill={color(x.label)} />)}</Pie>
              <Tooltip formatter={(v: unknown) => fmt(v as number, "pct1")} />
            </PieChart>
          </ResponsiveContainer>
        </div>
        <table className="text-sm">
          <tbody>
            {items.map((x) => <tr key={x.label}><td className="pr-2 py-0.5"><span className="inline-block h-3 w-3 rounded-sm" style={{ background: color(x.label) }} /></td><td className="pr-4 py-0.5 font-medium">{x.label}</td><td className="py-0.5 tabular-nums text-right">{fmt(x.value, "pct1")}</td></tr>)}
            <tr className="border-t border-slate-200 text-slate-500"><td /><td className="pr-4 py-0.5">합계</td><td className="py-0.5 text-right tabular-nums">{fmt(total, "pct1")}</td></tr>
          </tbody>
        </table>
      </div>
      {b.note_ko && <p className="mt-2 text-xs text-slate-500">{b.note_ko}</p>}
    </div>
  )
}

function useRows(doc: ReportDoc, dataset: "index" | "value_usd" | "drawdown", ids: string[]) {
  return useMemo(() => doc.datasets.dates.map((d, i) => {
    const row: Record<string, number | string> = { date: d }
    for (const id of ids) { const v = doc.datasets.series[id]?.[dataset]?.[i]; if (typeof v === "number") row[id] = v }
    return row
  }), [doc, dataset, ids])
}

/** 선·면 차트: 기본 켜진 계열 ≤ 3, 나머지는 칩으로 켠다. 캡션에 기간·단위·표본 안내. */
export function LineSeries({ b, doc }: { b: LineBlock | AreaBlock; doc: ReportDoc }) {
  const [on, setOn] = useState<string[]>(b.default_on.slice(0, 3))
  const rows = useRows(doc, b.dataset, b.series_ids)
  const toggle = (id: string) => setOn((s) => (s.includes(id) ? s.filter((x) => x !== id) : [...s, id]))
  const last = rows[rows.length - 1] ?? {}
  const yf = (v: number) => (b.y_format === "pct" ? `${(v * 100).toFixed(0)}%` : b.y_format === "usd" ? `${Math.round(v / 1000)}k` : v.toFixed(0))
  const dates = doc.datasets.dates
  const samp = doc.datasets.sampling
  const unit = b.y_format === "pct" ? "고점 대비 낙폭(%)" : b.y_format === "usd" ? "USD" : "시작 = 100"
  const caption = `${dates[0] ?? ""} ~ ${dates[dates.length - 1] ?? ""} · ${unit} · 분석 기준일 ${doc.header.data_as_of}${samp ? ` · 표본 ${samp.points}/${samp.full_points}점 (전체는 서버 조회)` : ""}`
  const table = { columns: [{ key: "date", label_ko: "날짜" }, ...on.map((id) => ({ key: id, label_ko: doc.datasets.series[id]?.label_ko ?? id, format: b.y_format }))], rows }
  const color = (id: string) => colorOf(id, b.series_ids)
  const [moreChips, setMoreChips] = useState(false)
  const MAX_CHIPS = 8
  const shown = moreChips || b.series_ids.length <= MAX_CHIPS ? b.series_ids : [...b.series_ids.filter((id) => on.includes(id)), ...b.series_ids.filter((id) => !on.includes(id))].slice(0, MAX_CHIPS)
  const hidden = b.series_ids.length - shown.length
  const controls = (
    <div className="flex flex-wrap gap-2">
      {shown.map((id) => (
        <button key={id} type="button" onClick={() => toggle(id)} aria-pressed={on.includes(id)} className={`max-w-full truncate rounded-full border px-3 py-1 text-xs ${on.includes(id) ? "border-slate-800 bg-slate-800 text-white" : "border-slate-300 text-slate-600"}`}>
          <span className="mr-1 inline-block h-2 w-2 rounded-full" style={{ background: color(id) }} />{doc.datasets.series[id]?.label_ko ?? id}
        </button>
      ))}
      {b.series_ids.length > MAX_CHIPS && <button type="button" onClick={() => setMoreChips((v) => !v)} className="rounded-full border border-dashed border-slate-300 px-3 py-1 text-xs text-slate-500 hover:bg-slate-50">{moreChips ? "계열 접기" : `계열 더 보기 (+${hidden})`}</button>}
    </div>
  )
  const footer = <p className="text-xs text-slate-600">{b.series_ids.filter((id) => on.includes(id)).map((id) => <span key={id} className="mr-4 inline-block">{doc.datasets.series[id]?.label_ko}: 마지막 값 <b className="tabular-nums">{fmt(last[id] as number, b.y_format)}</b></span>)}</p>
  return (
    <ChartFrame title={b.title_ko} caption={caption} table={table} height={280} note={"note_ko" in b ? b.note_ko : undefined} controls={controls} footer={footer}>
      <div className="h-full w-full">
        <ResponsiveContainer width="100%" height="100%">
          {b.type === "area" ? (
            <AreaChart data={rows}>
              <CartesianGrid strokeDasharray="3 3" stroke="#e2e8f0" /><XAxis dataKey="date" minTickGap={60} tick={{ fontSize: 11 }} /><YAxis tickFormatter={yf} tick={{ fontSize: 11 }} width={48} />
              <Tooltip formatter={(v: unknown, n: unknown) => [fmt(v as number, b.y_format), doc.datasets.series[String(n)]?.label_ko ?? String(n)]} />
              {b.series_ids.filter((id) => on.includes(id)).map((id) => <Area key={id} type="monotone" dataKey={id} stroke={color(id)} fill={color(id)} fillOpacity={0.12} dot={false} isAnimationActive={false} />)}
            </AreaChart>
          ) : (
            <LineChart data={rows}>
              <CartesianGrid strokeDasharray="3 3" stroke="#e2e8f0" /><XAxis dataKey="date" minTickGap={60} tick={{ fontSize: 11 }} /><YAxis tickFormatter={yf} tick={{ fontSize: 11 }} width={48} domain={["auto", "auto"]} />
              <Tooltip formatter={(v: unknown, n: unknown) => [fmt(v as number, b.y_format), doc.datasets.series[String(n)]?.label_ko ?? String(n)]} />
              {b.dataset === "index" && <ReferenceLine y={100} stroke="#94a3b8" strokeDasharray="4 4" />}
              {b.series_ids.filter((id) => on.includes(id)).map((id) => <Line key={id} type="monotone" dataKey={id} stroke={color(id)} dot={false} strokeWidth={id === doc.header.chosen_portfolio_id ? 2.5 : 1.5} isAnimationActive={false} />)}
            </LineChart>
          )}
        </ResponsiveContainer>
      </div>
    </ChartFrame>
  )
}

export function BarItems({ b }: { b: BarBlock }) {
  const table = { columns: [{ key: "label", label_ko: "항목" }, { key: "value", label_ko: "값", format: b.format }], rows: b.items }
  return (
    <ChartFrame title={b.title_ko} caption={`${b.items.length}개 항목 · ${b.format === "pp" ? "%p" : "%"}`} table={table} height={Math.max(200, b.items.length * 26)} note={b.note_ko}>
      <ResponsiveContainer width="100%" height="100%">
        <BarChart data={b.items} layout="vertical" margin={{ left: 20 }}>
          <CartesianGrid strokeDasharray="3 3" stroke="#e2e8f0" /><XAxis type="number" tickFormatter={(v: number) => `${(v * 100).toFixed(1)}`} tick={{ fontSize: 11 }} /><YAxis type="category" dataKey="label" width={60} tick={{ fontSize: 11 }} />
          <Tooltip formatter={(v: unknown) => fmt(v as number, b.format)} /><ReferenceLine x={0} stroke="#94a3b8" />
          <Bar dataKey="value" isAnimationActive={false}>{b.items.map((x, i) => <Cell key={i} fill={x.value >= 0 ? PALETTE[0] : PALETTE[1]} />)}</Bar>
        </BarChart>
      </ResponsiveContainer>
    </ChartFrame>
  )
}

export function Funnel({ b }: { b: FunnelBlock }) {
  const max = Math.max(...b.items.map((x) => x.count))
  return (
    <div className={card}>
      <h3 className={h3}>선정 과정</h3>
      <ol className="space-y-2">
        {b.items.map((x, i) => (
          <li key={i} className="flex items-center gap-3 text-sm">
            <span className="w-8 text-right text-xs text-slate-400">{i + 1}</span>
            <div className="h-6 rounded bg-blue-600/80" style={{ width: `${Math.max(4, (x.count / max) * 100)}%`, maxWidth: "60%" }} />
            <span className="tabular-nums font-semibold">{x.count}</span><span className="text-slate-700">{x.label_ko}</span>
          </li>
        ))}
      </ol>
    </div>
  )
}

export function Callout({ tone, title, text }: { tone: "info" | "caution"; title: string; text: string }) {
  return (
    <div className={`rounded-xl border p-4 text-sm leading-6 ${tone === "caution" ? "border-amber-300 bg-amber-50 text-amber-900" : "border-slate-200 bg-slate-50 text-slate-700"}`}>
      <div className="mb-1 font-semibold">{title}</div><div className="whitespace-pre-line"><CitedText text={text} /></div>
    </div>
  )
}

export function Cards({ b }: { b: CardsBlock }) {
  const ctx = useContext(CitationContext)
  const cite = (v: string) => v.split(/[,\s]+/).filter((x) => /^(ev\d+|dc\d+|fin:\S+|calc:\S+)$/.test(x))
  return (
    <div>
      {b.title_ko && <h3 className={h3}>{b.title_ko}</h3>}
      <div className="grid grid-cols-2 gap-3">
        {b.items.map((c, i) => (
          <div key={i} className={card}>
            <div className="font-semibold text-slate-900">{c.title_ko}</div>
            <p className="mt-2 whitespace-pre-line text-sm leading-6 text-slate-700"><CitedText text={c.text_ko} /></p>
            {c.meta.length > 0 && <dl className="mt-3 space-y-1 text-xs text-slate-600">{c.meta.map((m) => { const ids = m.label_ko === "근거" && ctx ? cite(m.value) : []; return <div key={m.label_ko} className="flex gap-2"><dt className="shrink-0 font-medium">{m.label_ko}</dt><dd>{ids.length ? ids.map((id) => <button key={id} type="button" onClick={() => ctx!.onCite(id)} className="mr-1 font-bold text-blue-700 hover:underline" aria-label={`근거 ${id} 보기`}>[{ctx!.label(id)}]</button>) : m.value}</dd></div> })}</dl>}
          </div>
        ))}
      </div>
    </div>
  )
}

export function Glossary({ items }: { items: { term: string; explain_ko: string }[] }) {
  return (
    <div className={card}>
      <h3 className={h3}>용어 풀이</h3>
      <dl className="grid grid-cols-2 gap-x-8 gap-y-3 text-sm">{items.map((g) => <div key={g.term}><dt className="font-semibold text-slate-900">{g.term}</dt><dd className="text-slate-700 leading-6"><CitedText text={g.explain_ko} /></dd></div>)}</dl>
    </div>
  )
}

/** 근거 참조: 색인을 복사하지 않고 "N건 · 출처 보기" 버튼으로 드로어를 연다. */
export function EvidenceRef({ b }: { b: EvidenceRefBlock }) {
  const rep = useReport()
  const kinds = Object.entries(b.kinds).map(([k, n]) => `${ko(k)} ${n}`).join(" · ")
  return (
    <div className="flex flex-wrap items-center justify-between gap-3 rounded-xl border border-dashed border-slate-300 bg-slate-50 px-4 py-3 text-sm">
      <span className="text-slate-700"><b>{b.title_ko}</b> <span className="text-slate-500">{b.count}건{kinds ? ` (${kinds})` : ""}</span></span>
      {rep && <button type="button" onClick={() => rep.openDrawer({ ids: b.ids, title: b.title_ko })} className="rounded-lg border border-blue-200 bg-white px-3 py-1.5 text-xs font-semibold text-blue-700 hover:bg-blue-50">출처 보기</button>}
    </div>
  )
}

/** 규칙별 비중 표 (도넛 여러 개 대신). */
export function WeightsCompare({ b }: { b: WeightsCompareBlock }) {
  const [page, setPage] = useState(0)
  const pages = Math.max(1, Math.ceil(b.rows.length / PAGE_ROWS))
  const rows = b.rows.slice(page * PAGE_ROWS, (page + 1) * PAGE_ROWS)
  return (
    <div className={card}>
      <h3 className={h3}>{b.title_ko}</h3>
      <div className="overflow-x-auto">
        <table className="w-full text-sm">
          <thead><tr className="border-b border-slate-200 text-left text-xs font-semibold text-slate-500"><th className="px-2 py-2">종목</th><th className="px-2 py-2">섹터</th>{b.columns.map((c) => <th key={c.id} className={`px-2 py-2 text-right whitespace-nowrap ${c.id === b.baseline_id ? "text-blue-700" : ""}`} title={c.rule_ko}>{c.label_ko}{c.id === b.baseline_id ? " (기준)" : ""}</th>)}</tr></thead>
          <tbody>
            {rows.map((r) => <tr key={r.ticker} className="border-b border-slate-100"><td className="px-2 py-1.5 font-medium" title={r.name}>{r.ticker}</td><td className="px-2 py-1.5 text-slate-500">{r.sector}</td>{b.columns.map((c) => <td key={c.id} className="px-2 py-1.5 text-right tabular-nums">{fmt(r.weights[c.id], "pct1")}</td>)}</tr>)}
            <tr className="border-t border-slate-200 text-slate-600"><td className="px-2 py-1.5">현금</td><td /> {b.columns.map((c) => <td key={c.id} className="px-2 py-1.5 text-right tabular-nums">{fmt(b.cash[c.id] ?? 0, "pct1")}</td>)}</tr>
            <tr className="text-xs text-slate-500"><td className="px-2 py-1.5">예상 변동성</td><td />{b.columns.map((c) => <td key={c.id} className="px-2 py-1.5 text-right tabular-nums">{fmt(b.ex_ante[c.id]?.vol, "pct")}</td>)}</tr>
          </tbody>
        </table>
      </div>
      <Pagination page={page} pages={pages} onChange={setPage} total={b.rows.length} pageSize={PAGE_ROWS} />
      {b.note_ko && <p className="mt-2 text-xs text-slate-500">{b.note_ko}</p>}
    </div>
  )
}

export function RenderBlock({ b, doc }: { b: Block; doc: ReportDoc }) {
  switch (b.type) {
    case "paragraphs": return <Paragraphs items={b.items} tone={b.tone} />
    case "kpis": return doc.summary ? null : <KpiCards kpis={doc.kpis} ids={b.ids} />  // 대시보드가 있으면 중복이라 그리지 않음
    case "table": return <DataTable b={b} />
    case "donut": return <Donut b={b} />
    case "line": case "area": return <LineSeries b={b} doc={doc} />
    case "bar": return <BarItems b={b} />
    case "funnel": return <Funnel b={b} />
    case "callout": return <Callout tone={b.tone} title={b.title_ko} text={b.text_ko} />
    case "cards": return <Cards b={b} />
    case "glossary": return <Glossary items={b.items} />
    case "evidence_ref": return <EvidenceRef b={b} />
    case "weights_compare": return <WeightsCompare b={b} />
    case "timeline": return <RebalanceTimeline b={b} />
    case "companies": return <CompanyList b={b} />
    case "checkpoints": case "evidence": return null  // v1 전용 블록은 normalizeDoc 이 바꾼다
  }
}
