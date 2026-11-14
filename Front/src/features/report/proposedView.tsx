// 제안 계약(api/proposed.ts) 값 읽기. 구조화된 값이 있으면 그것을 쓰고, 없으면 지금처럼 서버 문장·표를 읽는 방식(wording.ts)으로 돌아간다.
// 실제 서버는 아직 proposed 를 주지 않으므로 일반 모드에서는 모두 기존 경로를 탄다 (화면 그대로). 목업 모드(?mock=1)에서만 구조화 값이 쓰인다.
import { useContext } from "react"
import type { ProposedCheck, ProposedReport } from "../../api/proposed"
import { proposedOf } from "../../api/proposed"
import type { ReportDoc, SummaryKpi } from "../../api/types"
import { ServiceContext } from "../../app/providers"
import { benchTicker, etfDesc, explainReason, kpiName, strategyInfo, type Reason, type StrategyInfo, type VolCheck } from "./wording"

export const proposed = (doc?: ReportDoc | null): ProposedReport | null => (doc ? proposedOf(doc) : null)

/** 목업 자료로 보이는 화면 요소 옆의 작은 표시. 목업 모드에서만 보인다 (실제 서버가 같은 값을 주면 표시 없이 그대로 쓰인다). */
export function MockTag() {
  const svc = useContext(ServiceContext)
  if (svc?.mode !== "mock") return null
  return <span data-mock-ui className="ml-1.5 inline-flex shrink-0 items-center rounded border border-amber-300 bg-amber-50 px-1.5 py-px align-middle text-[11px] font-semibold text-amber-900">목업</span>
}

/** KPI 이름·기간: 구조화된 kpi_meta 가 있으면 그것, 없으면 서버 이름 읽기. */
export function kpiDisplay(doc: ReportDoc | null | undefined, k: Pick<SummaryKpi, "id" | "label_ko">): { name: string; sub?: string } {
  const m = proposed(doc)?.structured?.kpi_meta?.[k.id]
  if (!m) return kpiName(k)
  return { name: m.name_ko, sub: m.period === "total" && m.days && k.id !== "mdd" ? `${m.days}거래일 기준` : undefined }
}

/** 핵심 판단 이유: 구조화 값(제목·설명·톤)이 있으면 그대로, 없으면 서버 문장 틀 읽기. */
export function reasonsOf(doc: ReportDoc, short: boolean): { t: string; r: Reason }[] {
  const rs = proposed(doc)?.structured?.reasons
  if (rs?.length) return rs.map((x) => ({ t: x.text_ko, r: { title: x.title_ko, desc: x.text_ko, tone: x.tone === "neutral" ? undefined : x.tone } }))
  return (doc.summary?.verdict.reason_ko ?? "").split(" · ").map((t) => t.trim()).filter(Boolean).map((t) => ({ t, r: explainReason(t, { short }) }))
}

export const checkOf = (doc: ReportDoc | null | undefined, rule: string): ProposedCheck | null => proposed(doc)?.structured?.checks.find((c) => c.rule === rule) ?? null

const pct1 = (x: number) => `${(x * 100).toFixed(1)}%`

/** 구조화된 변동성 검사 → 화면의 VolCheck 모양 (서버 문장 읽기 결과와 같은 모양). */
export function volFromStructured(c: ProposedCheck): VolCheck | null {
  if (c.rule !== "R7" || c.value === null) return null
  const kind = c.basis === "no_cap" ? "nocap" : c.basis === "absolute" ? "absolute" : "bench"
  return { kind, vol: pct1(c.value), bench: c.benchmark_value != null ? pct1(c.benchmark_value) : null, mult: c.multiplier != null ? String(c.multiplier) : null, band: c.threshold != null ? pct1(c.threshold) : null, pref: c.vol_pref ?? null, short: false }
}

/** 손실 감내 문구에서 허용 손실 말고 덧붙일 내용 (낙폭 맞춤안 목표). */
export function toleranceExtraOf(doc: ReportDoc | null | undefined, note: string | null | undefined): string {
  const t = proposed(doc)?.structured?.tolerance
  if (t) return t.match_target !== null ? `낙폭 맞춤안 목표 ${pct1(t.match_target)}${t.factors_ko.length ? ` (${t.factors_ko.join(", ")})` : ""}` : ""
  return (note ?? "").replace(/^손실 감내 수준 [\d.]+%(?: · )?/, "").trim()
}

/** 비교지수 이름·설명. */
export function benchOf(doc: ReportDoc | null | undefined, label?: string | null): { ticker: string | null; desc: string | null } {
  const b = proposed(doc)?.structured?.benchmark
  if (b) return { ticker: b.ticker, desc: b.description_ko }
  const t = benchTicker(label)
  return { ticker: t, desc: t ? etfDesc(t) : null }
}

/** 전략 설명: 서버(제안 계약)가 준 설명이 있으면 그것, 없으면 프런트에 적어 둔 설명. */
export function strategyInfoOf(doc: ReportDoc | null | undefined, id?: string | null): StrategyInfo | null {
  const e = id ? proposed(doc)?.explanations?.strategies?.[id] : null
  return e ? { short: e.short_ko, help: e.help_ko } : strategyInfo(id)
}

/** 비교표 행의 전략 ID·역할 (구조화 값이 있을 때). */
export function compareRowOf(doc: ReportDoc | null | undefined, name: unknown) {
  return proposed(doc)?.structured?.compare_rows.find((r) => r.name === name) ?? null
}

/** 리밸런싱 제목 조각 (전략명 · 주식 x% · 현금 y% · 기준). 구조화 값이 없으면 null (서버 제목 읽기로). */
export function timelineParts(doc: ReportDoc | null | undefined): string[] | null {
  const m = proposed(doc)?.structured?.timeline_meta
  if (!m) return null
  return [m.strategy_label_ko, ...(m.equity_ratio !== null ? [`주식 ${Math.round(m.equity_ratio * 100)}%`] : []), ...(m.cash_ratio !== null ? [`현금 ${Math.round(m.cash_ratio * 100)}%`] : []), ...(m.base_label_ko ? [`${m.base_label_ko} 기준`] : [])]
}

/** 종목 이름 (문서 안의 기업 카드·배분 표에서). */
export function nameOf(doc: ReportDoc | null | undefined, ticker: string): string {
  for (const s of doc?.sections ?? []) for (const b of s.blocks) if (b.type === "companies") { const it = b.items.find((x) => x.ticker === ticker); if (it) return it.name }
  return doc?.summary?.allocation?.items.find((x) => x.ticker === ticker)?.name ?? ticker
}
