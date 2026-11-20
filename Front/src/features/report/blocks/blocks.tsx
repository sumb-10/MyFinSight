import { parseViewCard, ViewCardBody } from "./ViewCard"
import { ThemeScope } from "./ThemeScope"
import { CitationContext } from "./citationContext"
import { politeAssumptions } from "../wording"
import { HelpTip } from "../terms"
import { useContext, useMemo, useState } from "react"
import { Area, AreaChart, Bar, BarChart, CartesianGrid, Cell, Line, LineChart, Pie, PieChart, ReferenceLine, ResponsiveContainer, Tooltip, XAxis, YAxis } from "recharts"
import type { AreaBlock, BarBlock, Block, CardsBlock, DonutBlock, EvidenceRefBlock, FunnelBlock, Kpi, LineBlock, ReportDoc, TableBlock, WeightsCompareBlock } from "../../../api/types"
import { CITE_RE } from "../../../lib/citations"
import { colorOf, fmt, ko, OTHER_COLOR, PALETTE } from "../../../lib/format"
import { NOTICE_BOX, Pagination } from "../../../ui"
import { ChartFrame } from "../ChartFrame"
import { useReport } from "../context"
import { CompanyList } from "../CompanyList"
import { RebalanceTimeline } from "../RebalanceTimeline"
import { kpiName } from "../wording"
import { prefTerms } from "../../../lib/tendency"
import { holdingColor } from "../colors"
import { strategyInfoOf } from "../proposedView"

const card = "rounded-xl border border-slate-200 bg-white p-5"
const h3 = "mb-3 text-base font-semibold text-slate-900"
const PAGE_ROWS = 25
const DONUT_TOP = 8

/** 인용 ID 클릭 시 출처 패널을 여는 콜백. ReportDetail 이 제공한다. */
export { CitationContext }  // 정의는 citationContext.ts (기존 import 경로 유지)

/** tight: 「선택 근거 자세히 보기」 전용 (2026-11-16 사용자 요청: 한 문단 안의 큰 공백).
 *  전역 CSS `button { font: inherit }` 가 버튼의 text-[11px] 을 덮어 출처 번호가 본문 크기 그대로 위첨자(align-super)가 되어
 *  출처가 있는 줄만 줄 간격이 벌어졌다 → 크기·굵기는 안쪽 span 에, 위로 올리는 것은 줄 높이에 영향이 없는 relative 로.
 *  출처 앞 공백·출처 사이 공백도 빼서 「입니다 [3] .」 처럼 떨어지지 않게 한다. 다른 섹션은 예전 모양 그대로. */
/** 서버의 '(뷰 없음, 재배분)'·'(그날 뷰 없음, 재배분)' 표기를 화면에서는 '다른 종목 조정에 따른 비중 변화' 로 (2026-11-16 사용자 요청). 저장된 글은 그대로 읽는다. */
export const relabelNoView = (t: string) => t.replace(/\((?:그날 )?뷰 없음, 재배분\)/g, "(다른 종목 조정에 따른 포트폴리오 비중 변화)")

/** tight 문단의 공백 정리: 줄 앞뒤의 공백·탭과 연속 공백을 하나로 (같은 문단의 줄이 같은 왼쪽 기준선에 오게). 줄바꿈은 그대로. */
export const tidySpaces = (t: string) => t.replace(/\t/g, " ").replace(/[ \u00a0\u3000]*\n[ \u00a0\u3000]*/g, "\n").replace(/[ \u00a0\u3000]{2,}/g, " ").trim()

/** 서버 글의 `**강조**` 를 굵은 글씨로 (2026-11-19 사용자 요청: 중요한 말은 굵게). 짝이 맞지 않는 `**` 는 지운다. */
const BOLD_RE = /\*\*([^*\n]+?)\*\*/g
export function withBold(seg: string, key: string): React.ReactNode[] {
  const out: React.ReactNode[] = []
  let last = 0, n = 0
  for (const m of seg.matchAll(BOLD_RE)) {
    const at = m.index ?? 0
    if (at > last) out.push(seg.slice(last, at).replace(/\*\*/g, ""))
    out.push(<strong key={`${key}-b${n++}`} className="font-semibold text-slate-900">{m[1]}</strong>)
    last = at + m[0].length
  }
  if (last < seg.length) out.push(seg.slice(last).replace(/\*\*/g, ""))
  return out.filter((x) => x !== "")
}
/** 굵은 글씨 표시(**)를 뺀 글 — 제목·표 칸·도움말처럼 글자만 보이는 곳. */
export const stripBold = (t: string) => t.replace(/\*\*/g, "")

export function CitedText({ text: raw, tight }: { text: string; tight?: boolean }) {
  const ctx = useContext(CitationContext)
  const text = tight ? tidySpaces(relabelNoView(raw)) : relabelNoView(raw)
  const parts: React.ReactNode[] = []
  let last = 0
  for (const m of text.matchAll(CITE_RE)) {
    const start = m.index ?? 0
    if (start > last) {
      const seg = text.slice(last, start)
      const keep = tight ? seg.replace(/[ \t]+$/, "") : seg
      if (keep) parts.push(...withBold(keep, `s${start}`))
    }
    const id = m[1]
    parts.push(
      tight ? (
        ctx ? (
          <button key={`${id}-${start}`} type="button" onClick={() => ctx.onCite(id)} aria-label={`근거 ${id} 보기`} className="relative -top-[0.45em] ml-0.5 leading-none text-blue-700 hover:underline focus:outline-none focus-visible:ring-2 focus-visible:ring-blue-500"><span className="text-[11px] font-bold leading-none">[{ctx.label(id)}]</span></button>
        ) : (
          <span key={`${id}-${start}`} className="relative -top-[0.45em] ml-0.5 text-[11px] font-bold leading-none text-slate-500">[{id}]</span>
        )
      ) : ctx ? (
        <button key={`${id}-${start}`} type="button" onClick={() => ctx.onCite(id)} aria-label={`근거 ${id} 보기`} className="mx-0.5 align-super text-[11px] font-bold text-blue-700 hover:underline">[{ctx.label(id)}]</button>
      ) : (
        <span key={`${id}-${start}`} className="mx-0.5 align-super text-[11px] font-bold text-slate-500">[{id}]</span>
      ),
    )
    last = start + m[0].length
  }
  if (last < text.length) parts.push(...withBold(text.slice(last), "end"))
  return <>{parts}</>
}

/** tight(「선택 근거 자세히 보기」) 문단의 첫 줄이 소제목이면 [소제목, 본문]. 소제목 = 줄바꿈 앞의 40자 이하 줄, 마침표로 끝나지 않음
 *  (서버가 만든 '2026년 11월 10일 분석 기준일에 빠진 종목\n…' 문단, 2026-11-16). */
export function splitLeadTitle(t: string): [string, string] | null {
  const i = t.indexOf("\n")
  if (i <= 0) return null
  const head = t.slice(0, i).trim()
  return head.length <= 40 && !/[.。!?]$/.test(head) && !/\[[^\]]+\]/.test(head) ? [head, t.slice(i + 1)] : null
}

export function Paragraphs({ items, tone, tight }: { items: string[]; tone?: "lead"; tight?: boolean }) {
  return (
    <div className={tone === "lead" ? "space-y-4 text-[15.5px] leading-7 text-slate-800" : "space-y-3 text-[15px] leading-7 text-slate-700"}>
      {items.map((t, i) => {
        const lt = tight ? splitLeadTitle(tidySpaces(t)) : null
        return lt
          ? <p key={i} className="max-w-3xl whitespace-pre-line"><strong className="block font-semibold text-slate-900">{lt[0]}</strong><CitedText text={lt[1]} tight /></p>
          : <p key={i} className="max-w-3xl whitespace-pre-line"><CitedText text={t} tight={tight} /></p>
      })}
    </div>
  )
}

export function KpiCards({ kpis, ids }: { kpis: Kpi[]; ids: string[] }) {
  const sel = ids.map((id) => kpis.find((k) => k.id === id)).filter(Boolean) as Kpi[]
  return (
    <div className="grid grid-cols-1 gap-3 sm:grid-cols-3">
      {sel.map((k) => (
        <div key={k.id} className={card}>
          <div className="text-xs font-medium text-slate-500">{kpiName(k).name}{kpiName(k).sub ? ` (${kpiName(k).sub})` : ""}</div>
          <div className="mt-1 text-2xl font-semibold tabular-nums text-slate-900">{fmt(k.value, k.format)}</div>
          {k.note_ko && <div className="mt-1 text-xs text-slate-500">{k.note_ko}</div>}
        </div>
      ))}
    </div>
  )
}

/** 표: 25행이 넘으면 페이지로. 셀 값이 인용 ID 면 버튼으로. */
/** 표 제목·열 이름 표시: 서버 「분석 중 확인한 점 (조건을 바꾸면 달라질 수 있는 것)」은 무엇을 담은 표인지 바로 보이게 바꾸고 설명 한 줄을 단다 (2026-11-14 사용자 요청). 나머지는 그대로. */
// drop: 따로 두지 않을 열 — 값이 내용 문장에 이미 없으면 그 문장 끝에 괄호로 붙여 정보는 남긴다 (into: 붙일 열)
const TABLE_VIEW: { test: RegExp; title: string; desc: string; cols: Record<string, string>; drop?: { col: string; into: string } }[] = [
  { test: /^분석 중 확인한 점/, title: "분석하면서 처리한 일", desc: "종목을 고르고 자료를 모으는 동안 이렇게 처리했습니다. 조건을 바꾸면 달라질 수 있습니다.", cols: {}, drop: { col: "횟수·기간", into: "내용" } },
]
/** 열 하나를 빼고, 그 값이 붙일 열의 문장 안에 없으면(「-」 제외) 문장 끝에 「(값)」으로 붙인다. 열을 찾지 못하면 표를 그대로 둔다. */
function dropColumn(b: TableBlock, col: string, into: string): TableBlock {
  const drop = b.columns.find((c) => c.label_ko === col), keep = b.columns.find((c) => c.label_ko === into)
  if (!drop || !keep) return b
  return { ...b, columns: b.columns.filter((c) => c !== drop), rows: b.rows.map((r) => {
    const v = String(r[drop.key] ?? "").trim(), text = String(r[keep.key] ?? "")
    const extra = v && v !== "-" && v !== "–" && !v.split(/\s+/).every((part) => text.includes(part.replace(/~.*/, ""))) ? ` (${v})` : ""
    return { ...r, [keep.key]: `${text}${extra}` }
  }) }
}

/** 날짜·날짜 범위(앞에 「3회」가 붙을 수 있음)는 줄을 바꾸지 않는다: 「2025-11-10」이 「2025-11-」/「10」으로 꺾이지 않게. */
const DATE_LIKE = /^(\d+회\s*)?\d{4}-\d{2}-\d{2}(\s*~\s*\d{4}-\d{2}-\d{2})?$/

/** 주가 자료 점검 (서버 「가격 자료 품질 판정 (커버리지 0.95, 1거래일 결측만 채움)」): 결론 한 줄 + 쉬운 항목 이름. 점검 규칙은 제목 옆 ? 에.
 *  값은 서버 그대로이고 단위만 붙인다. 모르는 항목은 서버 이름 그대로 둔다 (2026-11-14 사용자 요청). */
const QUALITY_LABEL: Record<string, [string, string]> = {
  "기대 거래일": ["백테스트 기간 거래일 수", "일"], "가격 자료가 충분한 종목 (비교지수 포함)": ["자료가 충분한 종목 (비교지수 포함)", "개"],
  "제외 종목": ["자료가 부족해 뺀 종목", ""], "직전값으로 채운 종목(일수)": ["하루 빠진 주가를 전날 값으로 채운 종목 (일수)", ""], "가격 보정": ["주가 보정", ""],
}
function PriceQuality({ b }: { b: TableBlock }) {
  const [kc, vc] = b.columns
  const rows = b.rows.map((r) => ({ k: String(r[kc.key] ?? ""), v: String(r[vc.key] ?? "–") }))
  const val = (k: string) => rows.find((r) => r.k === k)?.v ?? null
  const none = (v: string | null) => v === null || v === "없음" || v === "-" || v === "–"
  const excluded = val("제외 종목"), filled = val("직전값으로 채운 종목(일수)")
  const nEx = none(excluded) ? 0 : (excluded!.match(/[^,\s:]+:/g) ?? [excluded]).length
  const ok = !nEx && none(filled)
  const minDays = Math.ceil(Number(val("기대 거래일")) * 0.95)
  return (
    <div className={card}>
      <h3 className={`${h3} flex items-center gap-1`}>주가 자료 점검
        <HelpTip label="주가 자료 점검">과거 성과 계산에 쓴 주가 자료가 빠진 날 없이 충분했는지 점검한 결과입니다. 백테스트 기간 거래일의 95% 이상{Number.isFinite(minDays) && minDays > 0 ? `(${minDays}일 이상)` : ""} 주가가 있는 종목만 씁니다. 주가가 하루만 빠진 날은 전날 값으로 채우고, 이틀 이상 빠지면 채우지 않습니다.</HelpTip>
      </h3>
      <p className={`mb-3 rounded-lg px-3 py-2 text-sm font-semibold ${ok ? "bg-emerald-50 text-emerald-800" : "bg-amber-50 text-amber-900"}`}>
        {ok ? "✓ 모든 종목의 주가 자료가 충분해, 빼거나 채운 종목 없이 계산했습니다." : `⚠ ${[nEx ? `자료가 부족해 ${nEx}개 종목을 뺐습니다` : null, none(filled) ? null : "하루 빠진 주가를 전날 값으로 채운 종목이 있습니다"].filter(Boolean).join(" · ")}.`}
      </p>
      <dl className="divide-y divide-slate-100 text-sm">
        {rows.map((r) => { const m = QUALITY_LABEL[r.k]; const unit = m?.[1] && /^\d+$/.test(r.v) ? m[1] : ""; return (
          <div key={r.k} className="flex items-start justify-between gap-4 px-2 py-2"><dt className="text-slate-700">{m?.[0] ?? r.k}</dt><dd className="text-right tabular-nums text-slate-900">{r.v}{unit}</dd></div>
        ) })}
      </dl>
    </div>
  )
}

/** 표 하나: 주가 자료 점검 표는 전용 모양으로, 나머지는 일반 표로. */
export function DataTable({ b }: { b: TableBlock }) {
  return b.title_ko && /^가격 자료 품질 판정/.test(b.title_ko) && b.columns.length === 2 ? <PriceQuality b={b} /> : <PlainTable b={b} />
}

function PlainTable({ b: raw }: { b: TableBlock }) {
  const view = TABLE_VIEW.find((x) => raw.title_ko && x.test.test(raw.title_ko))
  const b = view?.drop ? dropColumn(raw, view.drop.col, view.drop.into) : raw
  const [page, setPage] = useState(0)
  const ctx = useContext(CitationContext)
  const pages = Math.max(1, Math.ceil(b.rows.length / PAGE_ROWS))
  const rows = b.rows.length > PAGE_ROWS ? b.rows.slice(page * PAGE_ROWS, (page + 1) * PAGE_ROWS) : b.rows
  const isCite = (v: unknown) => typeof v === "string" && /^(ev\d+|dc\d+|fin:\S+|calc:\S+)$/.test(v)
  return (
    <div className={card}>
      {b.title_ko && (view
        ? <h3 className={`${h3} flex items-center gap-1`}>{view.title}<HelpTip label={view.title}>{view.desc}</HelpTip></h3>  // 설명은 제목 옆 ? 안에 (2026-11-14 사용자 요청)
        : <h3 className={h3}>{b.title_ko}</h3>)}
      {b.subtitle_ko && <p className="-mt-1 mb-3 text-xs leading-5 text-slate-500">{b.subtitle_ko}</p>}
      <div className="overflow-x-auto">
        <table className={`w-full border-collapse text-sm ${b.columns.length > 4 ? "min-w-[720px]" : ""}`}>
          <thead>
            <tr className="border-b border-slate-200 text-left text-xs font-semibold text-slate-500">
              {/* 숫자 열(비율·금액·수)은 값처럼 오른쪽 정렬 — 열 이름이 아래 숫자와 같은 줄에 선다 */}
              {b.columns.map((c) => <th key={c.key} className={`px-2 py-2 whitespace-nowrap ${c.format && !["text", "url"].includes(c.format) ? "text-right" : ""}`}>{view?.cols[c.label_ko] ?? c.label_ko}</th>)}
            </tr>
          </thead>
          <tbody>
            {rows.map((r, i) => (
              <tr key={i} className="border-b border-slate-100 align-top">
                {b.columns.map((c) => {
                  const v = r[c.key]; const num = typeof v === "number" || (!!c.format && !["text", "url"].includes(c.format))  // 숫자 열은 값이 비어(–) 있어도 오른쪽 정렬
                  if (c.format === "url") {
                    const href = typeof v === "string" && v ? v : null
                    return <td key={c.key} className="px-2 py-2">{href ? <a href={href} target="_blank" rel="noreferrer" className="text-blue-700 underline underline-offset-2">원문</a> : "–"}</td>
                  }
                  if (ctx && isCite(v)) return <td key={c.key} className="px-2 py-2"><button type="button" onClick={() => ctx.onCite(v as string)} className="font-mono text-xs text-blue-700 hover:underline" aria-label={`근거 ${v} 보기`}>[{ctx.label(v as string)}]</button></td>
                  // 「추출한 테마」의 「어떤 기업이 해당하는가」: 포함 / 넣지 않음을 나눠서 (2026-11-16 사용자 요청)
                  if (c.key === "desc" && raw.title_ko === "추출한 테마" && typeof v === "string") return <td key={c.key} className="px-2 py-2 sm:min-w-[16rem]"><ThemeScope text={v} /></td>
                  const dateLike = typeof v === "string" && DATE_LIKE.test(v.trim())
                  return <td key={c.key} className={`px-2 py-2 ${num ? "tabular-nums whitespace-nowrap text-right" : dateLike ? "whitespace-nowrap tabular-nums text-slate-700" : "text-slate-700"}`}>{c.format === "text" || c.format === undefined ? prefTerms(String(v ?? "–")) : fmt(v, c.format)}</td>
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
  const color = (label: string) => (label.startsWith("기타") ? OTHER_COLOR : holdingColor(label, order))  // 투자 금액 카드와 같은 종목 색
  return (
    <div className={card}>
      <h3 className={h3}>{b.title_ko}</h3>
      <div className="flex flex-wrap items-center gap-6">
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

/** 선·면 차트: 기본 켜진 계열 ≤ 3, 나머지는 칩으로 켠다. 캡션에 기간·단위·표본 안내.
 *  칩은 늘 같은 순서(서버 series_ids)로 모두 보인다. 눌러도 자리가 바뀌지 않고, 「모두 보기」로 한 번에 켠다 (2026-11-11: 켠 칩이 맨 앞으로 오고 나머지는 「계열 더 보기」에 숨던 것을 고침). */
export function LineSeries({ b, doc }: { b: LineBlock | AreaBlock; doc: ReportDoc }) {
  const defaults = b.default_on.slice(0, 3)
  const [on, setOn] = useState<string[]>(defaults)
  const rows = useRows(doc, b.dataset, b.series_ids)
  const toggle = (id: string) => setOn((s) => (s.includes(id) ? s.filter((x) => x !== id) : [...s, id]))
  const last = rows[rows.length - 1] ?? {}
  const yf = (v: number) => (b.y_format === "pct" ? `${(v * 100).toFixed(0)}%` : b.y_format === "usd" ? `${Math.round(v / 1000)}k` : v.toFixed(0))
  const dates = doc.datasets.dates
  const unit = b.y_format === "pct" ? "고점 대비 낙폭(%)" : b.y_format === "usd" ? "USD" : "시작 = 100"
  const caption = `${dates[0] ?? ""} ~ ${dates[dates.length - 1] ?? ""} · ${unit}`
  const table = { columns: [{ key: "date", label_ko: "날짜" }, ...on.map((id) => ({ key: id, label_ko: doc.datasets.series[id]?.label_ko ?? id, format: b.y_format }))], rows }
  const color = (id: string) => colorOf(id, b.series_ids)
  const dash = (id: string) => (b.series_ids.indexOf(id) >= PALETTE.length ? "6 3" : undefined)  // 색이 한 바퀴 돈 뒤(9번째 계열부터)는 같은 색을 점선으로
  const allOn = b.series_ids.every((id) => on.includes(id))
  const controls = (
    <div className="flex flex-wrap gap-2">
      {b.series_ids.length > 1 && <button type="button" onClick={() => setOn(allOn ? defaults : [...b.series_ids])} aria-pressed={allOn} className="rounded-full border border-slate-300 px-3 py-1 text-xs font-semibold text-slate-700 hover:bg-slate-50">{allOn ? "기본만 보기" : "모두 보기"}</button>}
      {b.series_ids.map((id) => (
        <button key={id} type="button" onClick={() => toggle(id)} aria-pressed={on.includes(id)} className={`max-w-full truncate rounded-full border px-3 py-1 text-xs ${on.includes(id) ? "border-slate-800 bg-slate-800 text-white" : "border-slate-300 text-slate-600"}`}>
          {dash(id) ? <span aria-hidden className="mr-1 inline-block w-3 align-middle" style={{ borderTop: `2px dashed ${color(id)}` }} /> : <span aria-hidden className="mr-1 inline-block h-2 w-2 rounded-full" style={{ background: color(id) }} />}{doc.datasets.series[id]?.label_ko ?? id}
        </button>
      ))}
    </div>
  )
  // 수익률 추이(선 그래프)의 아래 줄: 켜진 선마다 「색 · 이름 · 마지막 값 · 쉬운 설명 한 줄」 범례 (2026-11-15 사용자 요청: 칩 이름이 전문용어라 뜻을 알 수 없음,
  // ? 아이콘은 부자연스러워 범례에 설명을 붙인다). 칩을 켜고 끄면 그 줄도 생기고 사라진다. 설명이 없는 항목(투입 원금 등)은 이름과 값만. 낙폭(면 그래프)은 그대로
  const lastText = (v: unknown) => b.y_format === "index" && typeof v === "number" && Number.isFinite(v) ? `${v >= 100 ? "+" : "−"}${Math.abs(v - 100).toFixed(1)}%` : fmt(v as number, b.y_format)
  const footer = b.type === "line" ? (
    <ul aria-label="그래프 범례와 설명" className="space-y-2 text-sm sm:grid sm:grid-cols-[auto_auto_auto_minmax(0,1fr)] sm:items-baseline sm:gap-x-3 sm:gap-y-2 sm:space-y-0">
      {b.series_ids.filter((id) => on.includes(id)).map((id) => (
        <li key={id} className="flex flex-wrap items-baseline gap-x-2 sm:contents">
          <span aria-hidden className="inline-block w-4 shrink-0 self-center" style={{ borderTop: `2px ${dash(id) ? "dashed" : "solid"} ${color(id)}` }} />
          <span className="font-medium text-slate-800">{doc.datasets.series[id]?.label_ko ?? id}</span>
          <b className="tabular-nums text-slate-900" title={b.y_format === "index" ? `시작 = 100 기준 ${fmt(last[id] as number, "index")}` : undefined}>{lastText(last[id])}</b>
          <span className="basis-full pl-6 text-xs leading-5 text-slate-600 sm:basis-auto sm:pl-0 sm:text-[13px]">{strategyInfoOf(doc, id)?.short ?? ""}</span>
        </li>
      ))}
    </ul>
  ) : <p className="text-xs text-slate-600">{b.series_ids.filter((id) => on.includes(id)).map((id) => <span key={id} className="mr-4 inline-block">{doc.datasets.series[id]?.label_ko}: 마지막 값 <b className="tabular-nums">{fmt(last[id] as number, b.y_format)}</b></span>)}</p>
  return (
    <ChartFrame title={b.title_ko.replace(/^누적 수익률 \(시작 = 100\)/, "투자 가치 추이 (시작 = 100)")} caption={caption} table={table} height={280} note={"note_ko" in b ? b.note_ko : undefined} controls={controls} footer={footer}>
      <div className="h-full w-full">
        <ResponsiveContainer width="100%" height="100%">
          {b.type === "area" ? (
            <AreaChart data={rows}>
              <CartesianGrid strokeDasharray="3 3" stroke="#e2e8f0" /><XAxis dataKey="date" minTickGap={60} tick={{ fontSize: 11 }} /><YAxis tickFormatter={yf} tick={{ fontSize: 11 }} width={48} />
              <Tooltip formatter={(v: unknown, n: unknown) => [fmt(v as number, b.y_format), doc.datasets.series[String(n)]?.label_ko ?? String(n)]} />
              {b.series_ids.filter((id) => on.includes(id)).map((id) => <Area key={id} type="monotone" dataKey={id} stroke={color(id)} strokeDasharray={dash(id)} fill={color(id)} fillOpacity={0.12} dot={false} isAnimationActive={false} />)}
            </AreaChart>
          ) : (
            <LineChart data={rows}>
              <CartesianGrid strokeDasharray="3 3" stroke="#e2e8f0" /><XAxis dataKey="date" minTickGap={60} tick={{ fontSize: 11 }} /><YAxis tickFormatter={yf} tick={{ fontSize: 11 }} width={48} domain={["auto", "auto"]} />
              <Tooltip formatter={(v: unknown, n: unknown) => [fmt(v as number, b.y_format), doc.datasets.series[String(n)]?.label_ko ?? String(n)]} />
              {b.dataset === "index" && <ReferenceLine y={100} stroke="#94a3b8" strokeDasharray="4 4" />}
              {b.series_ids.filter((id) => on.includes(id)).map((id) => <Line key={id} type="monotone" dataKey={id} stroke={color(id)} strokeDasharray={dash(id)} dot={false} strokeWidth={id === doc.header.chosen_portfolio_id ? 2.5 : 1.5} isAnimationActive={false} />)}
            </LineChart>
          )}
        </ResponsiveContainer>
      </div>
    </ChartFrame>
  )
}

export function BarItems({ b }: { b: BarBlock }) {
  // 종목별 수익 기여: 차트 없이 표만 (2026-11-15 사용자 요청). 기여가 큰 종목부터
  if (/^종목별 수익 기여/.test(b.title_ko ?? "")) return <DataTable b={{ type: "table", title_ko: b.title_ko, columns: [{ key: "label", label_ko: "종목" }, { key: "value", label_ko: "수익 기여", format: b.format }], rows: [...b.items].sort((x, y) => y.value - x.value), note_ko: b.note_ko?.replace(/^막대를 모두 더하면/, "모두 더하면") }} />  // 표로 바뀌었으니 안내문의 「막대를」은 뺀다
  const table = { columns: [{ key: "label", label_ko: "항목" }, { key: "value", label_ko: "값", format: b.format }], rows: b.items }
  // 「섹터 노출 (기간 평균 비중, 최소분산)」 → 「업종별 투자 비중 (최소분산, 백테스트 기간 평균)」 (2026-11-15 사용자 요청: 「노출」이 무슨 뜻인지 알기 어려움). 틀이 다르면 앞말만 바꾼다
  const sector = /^섹터 노출 \(기간 평균 비중, (.+)\)$/.exec(b.title_ko ?? "")
  const title = sector ? `업종별 투자 비중 (${sector[1]}, 백테스트 기간 평균)` : (b.title_ko ?? "").replace(/^섹터 노출/, "업종별 투자 비중")
  return (
    <ChartFrame title={title} caption={`${b.items.length}개 항목 · ${b.format === "pp" ? "%p" : "%"}`} table={table} height={Math.max(200, b.items.length * 26)} note={b.note_ko}>
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

/** 선정 과정: 단계 번호(「1단계」…) + 막대 + 종목 수 + 단계 이름. 아래에 「제외된 종목」과 「재선정」이 무엇인지 짧게 구분한다. */
/** 괄호와 그 안의 글자를 모두 지운다 (괄호 안에 괄호가 있어도): 「선정 지표(모멘텀(최근 12개월 수익률)) 계산 가능」 → 「선정 지표 계산 가능」. */
export const dropParens = (t: string) => { let x = t, prev = ""; while (x !== prev) { prev = x; x = x.replace(/\s?\([^()]*\)/g, "") } return x.trim() }

/** 선정 과정: 단계별 남은 종목 수. 단계 이름의 괄호 설명은 빼고 짧게 (2026-11-14 사용자 요청). 선정 지표 설명은 제목 옆 ? 에. */
export function Funnel({ b }: { b: FunnelBlock }) {
  const max = Math.max(...b.items.map((x) => x.count))
  return (
    <div className={card}>
      <h3 className={`${h3} flex items-center gap-1`}>선정 과정{b.help_ko && <HelpTip label="선정 지표">{b.help_ko}</HelpTip>}</h3>
      <ol className="space-y-2" aria-label="선정 단계">
        {b.items.map((x, i) => (
          <li key={i} className="flex items-center gap-3 text-sm">
            <span className="w-12 shrink-0 whitespace-nowrap text-right text-xs font-semibold text-slate-500">{i + 1}단계</span>
            <div className="h-6 shrink-0 rounded bg-blue-600/80" style={{ width: `${Math.max(4, (x.count / max) * 100)}%`, maxWidth: "45%" }} />
            <span className="shrink-0 tabular-nums font-semibold">{x.count}</span><span className="min-w-0 text-slate-700">{dropParens(x.label_ko)}</span>
          </li>
        ))}
      </ol>
    </div>
  )
}

export function Callout({ tone, title, text }: { tone: "info" | "caution"; title: string; text: string }) {
  return (
    <div className={`rounded-box p-4 text-14 leading-6 text-body ${NOTICE_BOX[tone === "caution" ? "warning" : "neutral"]}`}>
      <div className="mb-1 font-semibold text-main">{title}</div><div className="whitespace-pre-line"><CitedText text={title === "백테스트 가정" ? politeAssumptions(text) : text} /></div>
    </div>
  )
}

/** 카드 묶음 제목 표시: 뉴스 의견(Black-Litterman) 카드 묶음은 쉬운 말(전문용어) 순서로 — 시작일·분석 기준일을 제목에서 구분한다. 나머지는 그대로. */
const cardsTitle = (t: string) => {
  if (/^시작일 뉴스 뷰 Black-Litterman 포트폴리오$/.test(t)) return "뉴스로 조정한 포트폴리오 비중 (백테스트 시작일 · Black-Litterman)"
  const m = /^현재 구성 BL (\d+): .+$/.exec(t)  // 분석 기준일 구성: 주제는 카드 안 제목에 그대로 있다
  if (m) return `뉴스로 조정한 포트폴리오 비중 (분석한 날 · Black-Litterman)${m[1] !== "1" ? ` · 구성 ${m[1]}` : ""}`
  return t
}

/** between: 첫 번째 뉴스 의견 카드의 「뉴스로 만든 투자 의견」과 「숫자로 보기」 사이에 넣을 내용 (없으면 예전 그대로). */
export function Cards({ b, between }: { b: CardsBlock; between?: React.ReactNode }) {
  const ctx = useContext(CitationContext)
  const cite = (v: string) => v.split(/[,\s]+/).filter((x) => /^(ev\d+|dc\d+|fin:\S+|calc:\S+)$/.test(x))
  return (
    <div>
      {b.title_ko && <h3 className={h3}>{cardsTitle(b.title_ko)}</h3>}
      {/* 두 칸 격자는 카드가 2개 이상일 때만 — 1개면 왼쪽 칸만 차지해 오른쪽이 비어 보이므로 전체 폭을 쓴다 */}
      <div className={`grid grid-cols-1 gap-3 ${b.items.length > 1 ? "md:grid-cols-2" : ""}`}>
        {b.items.map((c, i) => {
          const metaRow = (m: (typeof c.meta)[number]) => { const ids = m.label_ko === "근거" && ctx ? cite(m.value) : []; return <div key={m.label_ko} className="flex gap-2"><dt className="shrink-0 font-medium">{m.label_ko}</dt><dd>{ids.length ? ids.map((id) => <button key={id} type="button" onClick={() => ctx!.onCite(id)} className="mr-1 font-bold text-blue-700 hover:underline" aria-label={`근거 ${id} 보기`}>[{ctx!.label(id)}]</button>) : m.value}</dd></div> }
          const pv = parseViewCard(c)  // 뉴스 투자 의견 카드면 종목·의견·비중 변화로 나눠 보여 준다 (틀이 다르면 원문 그대로)
          return (
            <div key={i} className={`${card} min-w-0`}>
              <div className="font-semibold text-slate-900">{c.title_ko}</div>
              {pv ? <ViewCardBody p={pv} text={(t) => <CitedText text={t} />} evidence={c.meta.filter((m) => m.label_ko === "근거").map(metaRow)} between={i === 0 ? between : undefined} /> : <>
                <p className="mt-2 whitespace-pre-line break-words text-sm leading-6 text-slate-700"><CitedText text={c.text_ko} /></p>
                {i === 0 && between ? <div className="mt-3">{between}</div> : null}
                {c.meta.length > 0 && <dl className="mt-3 space-y-1 text-xs text-slate-600">{c.meta.map(metaRow)}</dl>}
              </>}
            </div>
          )
        })}
      </div>
    </div>
  )
}

export function Glossary({ items }: { items: { term: string; explain_ko: string }[] }) {
  return (
    <div className={card}>
      <h3 className={h3}>용어 풀이</h3>
      <dl className="grid grid-cols-1 gap-x-8 gap-y-3 text-sm md:grid-cols-2">{items.map((g) => <div key={g.term}><dt className="font-semibold text-slate-900">{g.term}</dt><dd className="text-slate-700 leading-6"><CitedText text={g.explain_ko} /></dd></div>)}</dl>
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
            <tr className="border-t border-slate-200 text-slate-600"><td className="px-2 py-1.5">현금</td><td />{b.columns.map((c) => <td key={c.id} className="px-2 py-1.5 text-right tabular-nums">{fmt(b.cash[c.id] ?? 0, "pct1")}</td>)}</tr>
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
    case "kpis": return <KpiCards kpis={doc.kpis} ids={b.ids} />  // 상세 섹션은 이 블록 대신 「과거 투자 성과」 맨 위에 KPI 전체를 그린다 (sections.tsx). 다른 곳에 오면 그대로 그린다
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
