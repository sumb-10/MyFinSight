import { useMemo, useState } from "react"
import { Area, AreaChart, Bar, BarChart, CartesianGrid, Cell, Legend, Line, LineChart, Pie, PieChart, ReferenceLine, ResponsiveContainer, Tooltip, XAxis, YAxis } from "recharts"
import type { AreaBlock, BarBlock, Block, CardsBlock, CheckpointsBlock, DonutBlock, FunnelBlock, Kpi, LineBlock, ReportDoc, TableBlock } from "./types"
import { fmt, PALETTE } from "./format"

const card = "rounded-xl border border-slate-200 bg-white p-5"
const h3 = "mb-3 text-base font-semibold text-slate-900"

export function Paragraphs({ items, tone }: { items: string[]; tone?: "lead" }) {
  return (
    <div className={tone === "lead" ? "space-y-4 text-[15.5px] leading-7 text-slate-800" : "space-y-3 text-[15px] leading-7 text-slate-700"}>
      {items.map((t, i) => <p key={i} className="max-w-3xl whitespace-pre-line">{t}</p>)}
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

export function DataTable({ b }: { b: TableBlock }) {
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
            {b.rows.map((r, i) => (
              <tr key={i} className="border-b border-slate-100 align-top">
                {b.columns.map((c) => {
                  const v = r[c.key]; const num = typeof v === "number"
                  if (c.format === "url") {
                    const href = typeof v === "string" && v ? v : null
                    return <td key={c.key} className="px-2 py-2">{href ? <a href={href} target="_blank" rel="noreferrer" className="text-brand-700 underline underline-offset-2">원문</a> : "–"}</td>
                  }
                  return <td key={c.key} className={`px-2 py-2 ${num ? "tabular-nums whitespace-nowrap text-right" : "text-slate-700"}`}>{c.format === "text" || c.format === undefined ? String(v ?? "–") : fmt(v, c.format)}</td>
                })}
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      {b.note_ko && <p className="mt-2 text-xs text-slate-500">{b.note_ko}</p>}
    </div>
  )
}

export function Donut({ b }: { b: DonutBlock }) {
  const total = b.items.reduce((s, x) => s + x.value, 0)
  return (
    <div className={card}>
      <h3 className={h3}>{b.title_ko}</h3>
      <div className="flex items-center gap-6">
        <div className="h-56 w-56 shrink-0">
          <ResponsiveContainer width="100%" height="100%">
            <PieChart>
              <Pie data={b.items} dataKey="value" nameKey="label" innerRadius={60} outerRadius={100} paddingAngle={1} isAnimationActive={false}>
                {b.items.map((_, i) => <Cell key={i} fill={PALETTE[i % PALETTE.length]} />)}
              </Pie>
              <Tooltip formatter={(v: unknown) => fmt(v as number, "pct1")} />
            </PieChart>
          </ResponsiveContainer>
        </div>
        <table className="text-sm">
          <tbody>
            {b.items.map((x, i) => (
              <tr key={x.label}>
                <td className="pr-2 py-0.5"><span className="inline-block h-3 w-3 rounded-sm" style={{ background: PALETTE[i % PALETTE.length] }} /></td>
                <td className="pr-4 py-0.5 font-medium">{x.label}</td>
                <td className="py-0.5 tabular-nums text-right">{fmt(x.value, "pct1")}</td>
              </tr>
            ))}
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

export function LineSeries({ b, doc }: { b: LineBlock | AreaBlock; doc: ReportDoc }) {
  const [on, setOn] = useState<string[]>(b.default_on)
  const rows = useRows(doc, b.dataset, b.series_ids)
  const toggle = (id: string) => setOn((s) => (s.includes(id) ? s.filter((x) => x !== id) : [...s, id]))
  const last = rows[rows.length - 1] ?? {}
  const yf = (v: number) => (b.y_format === "pct" ? `${(v * 100).toFixed(0)}%` : b.y_format === "usd" ? `${Math.round(v / 1000)}k` : v.toFixed(0))
  return (
    <div className={card}>
      <h3 className={h3}>{b.title_ko}</h3>
      <div className="mb-3 flex flex-wrap gap-2">
        {b.series_ids.map((id, i) => (
          <button key={id} type="button" onClick={() => toggle(id)} aria-pressed={on.includes(id)}
            className={`rounded-full border px-3 py-1 text-xs ${on.includes(id) ? "border-slate-800 bg-slate-800 text-white" : "border-slate-300 text-slate-600"}`}>
            <span className="mr-1 inline-block h-2 w-2 rounded-full" style={{ background: PALETTE[i % PALETTE.length] }} />{doc.datasets.series[id]?.label_ko ?? id}
          </button>
        ))}
      </div>
      <div className="h-80">
        <ResponsiveContainer width="100%" height="100%">
          {b.type === "area" ? (
            <AreaChart data={rows}>
              <CartesianGrid strokeDasharray="3 3" stroke="#e2e8f0" /><XAxis dataKey="date" minTickGap={60} tick={{ fontSize: 11 }} /><YAxis tickFormatter={yf} tick={{ fontSize: 11 }} width={48} />
              <Tooltip formatter={(v: unknown, n: unknown) => [fmt(v as number, b.y_format), doc.datasets.series[String(n)]?.label_ko ?? String(n)]} />
              {b.series_ids.filter((id) => on.includes(id)).map((id) => <Area key={id} type="monotone" dataKey={id} stroke={PALETTE[b.series_ids.indexOf(id) % PALETTE.length]} fill={PALETTE[b.series_ids.indexOf(id) % PALETTE.length]} fillOpacity={0.12} dot={false} isAnimationActive={false} />)}
            </AreaChart>
          ) : (
            <LineChart data={rows}>
              <CartesianGrid strokeDasharray="3 3" stroke="#e2e8f0" /><XAxis dataKey="date" minTickGap={60} tick={{ fontSize: 11 }} /><YAxis tickFormatter={yf} tick={{ fontSize: 11 }} width={48} domain={["auto", "auto"]} />
              <Tooltip formatter={(v: unknown, n: unknown) => [fmt(v as number, b.y_format), doc.datasets.series[String(n)]?.label_ko ?? String(n)]} />
              {b.dataset === "index" && <ReferenceLine y={100} stroke="#94a3b8" strokeDasharray="4 4" />}
              {b.series_ids.filter((id) => on.includes(id)).map((id) => <Line key={id} type="monotone" dataKey={id} stroke={PALETTE[b.series_ids.indexOf(id) % PALETTE.length]} dot={false} strokeWidth={id === doc.header.chosen_portfolio_id ? 2.5 : 1.5} isAnimationActive={false} />)}
            </LineChart>
          )}
        </ResponsiveContainer>
      </div>
      <table className="mt-3 text-xs text-slate-600"><tbody>
        <tr>{b.series_ids.filter((id) => on.includes(id)).map((id) => <td key={id} className="pr-5">{doc.datasets.series[id]?.label_ko}: 마지막 값 <b className="tabular-nums">{fmt(last[id] as number, b.y_format)}</b></td>)}</tr>
      </tbody></table>
      {"note_ko" in b && b.note_ko && <p className="mt-2 text-xs text-slate-500">{b.note_ko}</p>}
    </div>
  )
}

export function BarItems({ b }: { b: BarBlock }) {
  return (
    <div className={card}>
      <h3 className={h3}>{b.title_ko}</h3>
      <div style={{ height: Math.max(220, b.items.length * 26) }}>
        <ResponsiveContainer width="100%" height="100%">
          <BarChart data={b.items} layout="vertical" margin={{ left: 20 }}>
            <CartesianGrid strokeDasharray="3 3" stroke="#e2e8f0" /><XAxis type="number" tickFormatter={(v: number) => `${(v * 100).toFixed(1)}`} tick={{ fontSize: 11 }} /><YAxis type="category" dataKey="label" width={60} tick={{ fontSize: 11 }} />
            <Tooltip formatter={(v: unknown) => fmt(v as number, b.format)} /><ReferenceLine x={0} stroke="#94a3b8" />
            <Bar dataKey="value" isAnimationActive={false}>{b.items.map((x, i) => <Cell key={i} fill={x.value >= 0 ? "#2563eb" : "#b45309"} />)}</Bar>
          </BarChart>
        </ResponsiveContainer>
      </div>
      <p className="mt-2 text-xs text-slate-500">{b.items.map((x) => `${x.label} ${fmt(x.value, b.format)}`).join(" · ")}</p>
    </div>
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
            <div className="h-6 rounded bg-brand-600/80" style={{ width: `${Math.max(4, (x.count / max) * 100)}%`, maxWidth: "60%" }} />
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
      <div className="mb-1 font-semibold">{title}</div><div className="whitespace-pre-line">{text}</div>
    </div>
  )
}

export function Cards({ b }: { b: CardsBlock }) {
  return (
    <div>
      {b.title_ko && <h3 className={h3}>{b.title_ko}</h3>}
      <div className="grid grid-cols-2 gap-3">
        {b.items.map((c, i) => (
          <div key={i} className={card}>
            <div className="font-semibold text-slate-900">{c.title_ko}</div>
            <p className="mt-2 whitespace-pre-line text-sm leading-6 text-slate-700">{c.text_ko}</p>
            {c.meta.length > 0 && <dl className="mt-3 space-y-1 text-xs text-slate-600">{c.meta.map((m) => <div key={m.label_ko} className="flex gap-2"><dt className="shrink-0 font-medium">{m.label_ko}</dt><dd>{m.value}</dd></div>)}</dl>}
          </div>
        ))}
      </div>
    </div>
  )
}

const TO_DATE_LABELS: [string, string, "pct" | "ratio"][] = [["total_return", "누적 수익률", "pct"], ["cagr", "CAGR", "pct"], ["ann_vol", "변동성", "pct"], ["sharpe", "Sharpe", "ratio"], ["max_drawdown", "최대낙폭", "pct"], ["excess_cagr", "비교지수 대비", "pct"], ["irr_annual", "적립 기준 연수익(XIRR)", "pct"]]

export function CheckpointExplorer({ b }: { b: CheckpointsBlock }) {
  const [i, setI] = useState(b.items.length - 1)
  const cp = b.items[i]
  const w = Object.entries(cp.weights_after).sort((a, c) => c[1] - a[1]).map(([label, value]) => ({ label, value }))
  const sl = cp.since_last as Record<string, number | { ticker: string; return: number }> | null
  const td = cp.to_date as Record<string, number | boolean | null> | null
  return (
    <div className={card}>
      <h3 className={h3}>{b.title_ko}</h3>
      <div className="flex items-center gap-3">
        <label className="text-sm text-slate-600" htmlFor="cp-select">시점</label>
        <select id="cp-select" className="rounded border border-slate-300 px-2 py-1 text-sm" value={i} onChange={(e) => setI(Number(e.target.value))}>
          {b.items.map((x, k) => <option key={x.seq} value={k}>{x.date} · {x.kind === "rebalance" ? "리밸런싱" : x.kind === "closing" ? "기간 종료" : "월말"}</option>)}
        </select>
        <input type="range" min={0} max={b.items.length - 1} value={i} onChange={(e) => setI(Number(e.target.value))} aria-label="리밸런싱 시점" className="w-64" />
        <span className="text-xs text-slate-500">{cp.n_trading_days_to_date}거래일 경과 · 거래 {cp.n_trades}건 · 비용 {fmt(cp.commission_usd, "usd")}</span>
      </div>
      <div className="mt-4 grid grid-cols-3 gap-4">
        <div>
          <div className="mb-1 text-xs font-semibold text-slate-500">리밸런싱 후 배분 비중</div>
          <div className="h-48"><ResponsiveContainer width="100%" height="100%"><PieChart><Pie data={w} dataKey="value" nameKey="label" innerRadius={45} outerRadius={75} isAnimationActive={false}>{w.map((_, k) => <Cell key={k} fill={PALETTE[k % PALETTE.length]} />)}</Pie><Tooltip formatter={(v: unknown) => fmt(v as number, "pct1")} /></PieChart></ResponsiveContainer></div>
          <div className="text-xs text-slate-600">평가금액 {fmt(cp.value_usd, "usd")} · 투입 원금 {fmt(cp.net_invested_usd, "usd")}{cp.benchmark_value_usd != null && <> · 비교지수 동일 적립 시 {fmt(cp.benchmark_value_usd, "usd")}</>}</div>
        </div>
        <div className="col-span-2 overflow-x-auto">
          <table className="w-full text-xs">
            <thead><tr className="border-b border-slate-200 text-left text-slate-500"><th className="px-1 py-1">종목</th><th className="px-1 py-1 text-right">직전 비중</th><th className="px-1 py-1 text-right">목표</th><th className="px-1 py-1 text-right">조정 후</th><th className="px-1 py-1 text-right">구간 수익률</th><th className="px-1 py-1 text-right">구간 기여</th><th className="px-1 py-1 text-right">평가액</th></tr></thead>
            <tbody>{cp.holdings.map((h) => <tr key={h.ticker} className="border-b border-slate-100"><td className="px-1 py-1 font-medium">{h.ticker}</td><td className="px-1 py-1 text-right tabular-nums">{fmt(h.weight_before, "pct1")}</td><td className="px-1 py-1 text-right tabular-nums">{fmt(cp.weights_target[h.ticker], "pct1")}</td><td className="px-1 py-1 text-right tabular-nums">{fmt(h.weight_after, "pct1")}</td><td className="px-1 py-1 text-right tabular-nums">{fmt(h.period_return, "pct")}</td><td className="px-1 py-1 text-right tabular-nums">{fmt(h.period_contribution, "pp")}</td><td className="px-1 py-1 text-right tabular-nums">{fmt(h.value_usd, "usd")}</td></tr>)}</tbody>
          </table>
        </div>
      </div>
      <div className="mt-4 grid grid-cols-2 gap-4 text-sm">
        <div className="rounded-lg bg-slate-50 p-3">
          <div className="mb-1 text-xs font-semibold text-slate-500">직전 시점 이후 구간</div>
          {sl ? <ul className="space-y-0.5">
            <li>포트폴리오 {fmt(sl.return as number, "pct")} · 비교지수 {fmt(sl.benchmark_return as number, "pct")} · 차이 {fmt(sl.excess as number, "pp")}</li>
            <li>구간 최대낙폭 {fmt(sl.max_drawdown as number, "pct")} · 변동성 {fmt(sl.ann_vol as number, "pct")}</li>
            <li>가장 좋았던 종목 {(sl.best as { ticker: string; return: number }).ticker} {fmt((sl.best as { return: number }).return, "pct")} · 가장 나빴던 종목 {(sl.worst as { ticker: string; return: number }).ticker} {fmt((sl.worst as { return: number }).return, "pct")}</li>
          </ul> : <p className="text-slate-500">구성일입니다.</p>}
        </div>
        <div className="rounded-lg bg-slate-50 p-3">
          <div className="mb-1 text-xs font-semibold text-slate-500">구성일부터 이 시점까지 누적{td && td.reliable === false && <span className="ml-2 font-normal text-slate-400">(1년 미만, 연 환산 지표는 참고만)</span>}</div>
          {td ? <table className="text-xs"><tbody>{TO_DATE_LABELS.map(([k, label, f]) => <tr key={k}><td className="pr-3 py-0.5 text-slate-600">{label}</td><td className="py-0.5 tabular-nums text-right">{fmt(td[k] as number, f)}</td></tr>)}</tbody></table> : <p className="text-slate-500">아직 누적 지표가 없습니다.</p>}
        </div>
      </div>
    </div>
  )
}

export function Glossary({ items }: { items: { term: string; explain_ko: string }[] }) {
  return (
    <div className={card}>
      <h3 className={h3}>용어 풀이</h3>
      <dl className="grid grid-cols-2 gap-x-8 gap-y-3 text-sm">{items.map((g) => <div key={g.term}><dt className="font-semibold text-slate-900">{g.term}</dt><dd className="text-slate-700 leading-6">{g.explain_ko}</dd></div>)}</dl>
    </div>
  )
}

export function RenderBlock({ b, doc }: { b: Block; doc: ReportDoc }) {
  switch (b.type) {
    case "paragraphs": return <Paragraphs items={b.items} tone={b.tone} />
    case "kpis": return <KpiCards kpis={doc.kpis} ids={b.ids} />
    case "table": return <DataTable b={b} />
    case "donut": return <Donut b={b} />
    case "line": case "area": return <LineSeries b={b} doc={doc} />
    case "bar": return <BarItems b={b} />
    case "funnel": return <Funnel b={b} />
    case "callout": return <Callout tone={b.tone} title={b.title_ko} text={b.text_ko} />
    case "cards": return <Cards b={b} />
    case "checkpoints": return <CheckpointExplorer b={b} />
    case "glossary": return <Glossary items={b.items} />
  }
}
