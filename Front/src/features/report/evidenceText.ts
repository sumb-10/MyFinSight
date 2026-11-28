import type { CompaniesBlock, EvidenceRecord, ReportDoc } from "../../api/types"
import { fmt } from "../../lib/format"

// 근거 화면(근거 자세히 · 출처 목록 · 기업 카드의 근거 묶음)이 함께 쓰는 글자 (2026-11-28).
// 근거 한 건을 「장부 항목」이 아니라 「무엇을 말하는 자료인가」로 읽히게 한다: 숫자는 본문과 같은 단위로, 뜻은 쉬운 한 문장으로, 회사는 이름으로.
// 값은 서버가 준 그대로이고 여기서는 표시만 바꾼다.

export const KIND_PLAIN: Record<string, string> = { news: "뉴스 제목", disclosure: "공시", financial: "재무 숫자", calc: "계산한 숫자" }
export const kindPlain = (k: string) => KIND_PLAIN[k] ?? "자료"

/** `fin:US-AVGO:roe_ttm:2025-11-04` → 지표·종목·날짜. 틀이 다르면 null. */
export function finParts(id: string): { ticker: string; metric: string; date: string } | null {
  const m = /^fin:[A-Z]+-([^:]+):([a-z0-9_]+):(\d{4}-\d{2}-\d{2})$/.exec(id)
  return m ? { ticker: m[1], metric: m[2], date: m[3] } : null
}
/** `calc:max_drawdown:market_cap` → 계산 종류. */
export const calcMetric = (id: string) => /^calc:([a-z0-9_]+)/.exec(id)?.[1] ?? null

/** 지표 값 글자: 본문 문장과 같은 소수 한 자리 (27.3%). PER 은 배수, 주가 수익률은 부호를 붙인다. */
export const metricText = (metric: string, v: number) => (metric === "pe_ttm" ? `${fmt(v, "num")}배` : `${metric === "return_12m_1m" && v > 0 ? "+" : ""}${fmt(v, "pct1")}`)
const signed1 = (v: number) => `${v > 0 ? "+" : ""}${fmt(v, "pct1")}`

const METRIC_SHORT: Record<string, string> = { roe_ttm: "ROE", pe_ttm: "PER", return_12m_1m: "최근 1년 주가 수익률", vol_60d: "주가 변동성", dividend_yield_ttm: "배당수익률" }
const CALC_PCT = new Set(["cagr", "period_return", "max_drawdown", "ann_vol", "ex_ante_vol_now"])

/** 회사 이름 찾기: 기업 카드·배분 표에 있는 이름, 없으면 티커. */
export function companyNames(doc: Pick<ReportDoc, "sections" | "summary"> | null | undefined): (ticker: string) => string {
  const names = new Map<string, string>()
  for (const s of doc?.sections ?? []) for (const b of s.blocks) {
    if (b.type === "companies") for (const it of b.items) names.set(it.ticker, it.name)
    if (b.type === "weights_compare") for (const r of b.rows) if (!names.has(r.ticker)) names.set(r.ticker, r.name)
  }
  for (const it of doc?.summary?.allocation?.items ?? []) if (!names.has(it.ticker)) names.set(it.ticker, it.name)
  return (t) => names.get(t) || t
}

/** 근거의 값 글자 (본문과 같은 단위): 재무 지표는 지표 단위(27.3% · 18.2배), 계산값은 % · %p · USD · 소수. 값이 없으면 null. */
export function evidenceValue(e: Pick<EvidenceRecord, "id" | "kind" | "value" | "unit">): string | null {
  const v = e.value
  if (typeof v !== "number" || !Number.isFinite(v)) return v == null || v === "" ? null : String(v)
  if (e.kind === "financial") { const f = finParts(e.id); return f ? metricText(f.metric, v) : fmt(v, "pct1") }
  if (e.unit === "usd") return fmt(v, "usd")
  const c = calcMetric(e.id)
  if (c === "excess_cagr") return `${signed1(v)}p`  // 본문과 같은 소수 한 자리 (+52.3%p)
  if (c && CALC_PCT.has(c)) return c === "cagr" || c === "period_return" ? signed1(v) : fmt(v, "pct1")
  return fmt(v, "num")
}

/** 목록·기업 카드에 쓰는 한 줄 이름: 「Broadcom ROE 27.3%」 「구조조정 공시 (Applied Materials)」 「뉴스 제목」. */
export function evidenceTitle(e: EvidenceRecord, nameOf: (t: string) => string): string {
  const who = e.tickers?.length ? nameOf(e.tickers[0]) : ""
  const val = evidenceValue(e)
  if (e.kind === "financial") { const f = finParts(e.id); const label = f ? (METRIC_SHORT[f.metric] ?? e.title) : e.title; return `${f ? `${nameOf(f.ticker)} ${label}` : label}${val ? ` ${val}` : ""}` }
  if (e.kind === "calc") return `${e.title}${val ? ` ${val}` : ""}`
  if (e.kind === "disclosure") return `${e.event_label_ko || e.title || "공시"}${who ? ` (${who})` : ""}`
  return e.title || e.id
}

const won = (x: number) => { const n = x * 100; return Math.abs(n) >= 10 ? Math.round(n).toLocaleString("en-US") : n.toFixed(1) }
const absPct = (v: number) => fmt(Math.abs(v), "pct1")

/** 숫자 근거의 뜻을 쉬운 한 문장으로. 모르는 지표는 null (지어내지 않는다). */
export function evidencePlain(e: Pick<EvidenceRecord, "id" | "kind" | "value" | "unit">): string | null {
  const v = e.value
  if (typeof v !== "number" || !Number.isFinite(v)) return null
  if (e.kind === "financial") {
    switch (finParts(e.id)?.metric) {
      case "roe_ttm": return `자기 돈(자기자본) 100원으로 1년 동안 ${won(v)}원을 벌었다는 뜻입니다.`
      case "pe_ttm": return `지금 주가가 1년 동안 번 이익의 ${fmt(v, "num")}배라는 뜻입니다.`
      case "return_12m_1m": return `최근 1년 동안(가장 최근 한 달은 빼고) 주가가 ${absPct(v)} ${v >= 0 ? "올랐다" : "내렸다"}는 뜻입니다.`
      case "vol_60d": return "최근 60거래일 동안 주가가 오르내린 정도를 1년 기준으로 바꾼 값입니다. 클수록 많이 흔들렸습니다."
      case "dividend_yield_ttm": return `주식 100원어치를 갖고 있으면 1년에 ${won(v)}원을 배당으로 받았다는 뜻입니다.`
      default: return null
    }
  }
  if (e.kind === "calc") {
    switch (calcMetric(e.id)) {
      case "cagr": return `과거 성과 계산에서 1년에 평균 ${absPct(v)}씩 ${v >= 0 ? "올랐다" : "내렸다"}는 뜻입니다.`
      case "period_return": return `과거 성과를 계산한 전체 기간 동안 ${absPct(v)} ${v >= 0 ? "올랐다" : "내렸다"}는 뜻입니다.`
      case "max_drawdown": return `가장 높았던 때보다 ${absPct(v)}까지 내려간 적이 있다는 뜻입니다.`
      case "excess_cagr": return `비교 대상보다 1년에 평균 ${`${fmt(Math.abs(v), "pct1")}p`} ${v >= 0 ? "더 올랐다" : "덜 올랐다"}는 뜻입니다.`
      case "final_value_usd": return "과거 성과를 계산한 마지막 날의 평가금액입니다."
      case "ann_vol": case "ex_ante_vol_now": return "값이 1년 동안 오르내린 정도입니다. 클수록 많이 흔들립니다."
      case "sharpe": return "감수한 위험에 비해 얼마나 벌었는지를 나타냅니다. 클수록 좋습니다."
      default: return null
    }
  }
  return null
}

/** 글에서 이 근거 번호가 붙은 문장만 꺼낸다 (문단이 길 때 그 문장만 보이게). 못 찾으면 글 전체.
 *  valueText(근거의 값 글자, 예: "27.3%")를 주면: 번호가 붙은 문장에 그 값이 없고 같은 글의 다른 문장에 있을 때 그 문장을 고른다
 *  (번호가 문단 끝의 풀이 문장에 붙어 있고, 정작 값은 앞 문장에 적힌 경우). */
export function sentenceFor(text: string, id: string, valueText?: string | null): string {
  const tag = `[${id}]`
  if (!text.includes(tag)) return text
  const parts = text.split(/(?<=[.!?。])\s+(?=[^\s[])/)
  const tagged = parts.find((p) => p.includes(tag))?.trim() ?? text
  const v = valueText?.replace(/^[+\-−]/, "")
  if (v && !tagged.includes(v)) { const withValue = parts.find((p) => p.includes(v)); if (withValue) return withValue.trim() }
  return tagged
}

/** 같은 지표로 견준 순위 문장: 맨 앞·맨 뒤는 「가장 높습니다/낮습니다」, 그 사이는 「N번째로 …」. */
export function rankText(p: Pick<Peers, "direction" | "rank" | "items">): string {
  const n = p.items.length, hi = p.direction === "desc"
  if (p.rank === 1) return `담은 회사 ${n}개 가운데 가장 ${hi ? "높습니다" : "낮습니다"}`
  if (p.rank === n) return `담은 회사 ${n}개 가운데 가장 ${hi ? "낮습니다" : "높습니다"}`
  return `담은 회사 ${n}개 가운데 ${p.rank}번째로 ${hi ? "높습니다" : "낮습니다"}`
}

export interface Peers { metricKo: string; direction: "asc" | "desc"; rank: number; items: { ticker: string; name: string; value: number; text: string; me: boolean }[] }
/** 같은 지표로 견준 다른 회사들: 이 근거가 기업 카드의 선정 지표 값일 때, 담은 회사들의 같은 날 값을 좋은 순으로. */
export function peersOf(doc: Pick<ReportDoc, "sections">, id: string): Peers | null {
  for (const s of doc.sections) for (const b of s.blocks) {
    if (b.type !== "companies") continue
    const cb = b as CompaniesBlock
    const me = cb.items.find((it) => it.fact_id === id)
    if (!me || me.metric_now === null) continue
    const desc = cb.direction !== "asc"
    const items = cb.items.filter((it) => it.metric_now !== null).sort((x, y) => (desc ? (y.metric_now as number) - (x.metric_now as number) : (x.metric_now as number) - (y.metric_now as number)))
      .map((it) => ({ ticker: it.ticker, name: it.name || it.ticker, value: it.metric_now as number, text: metricText(cb.metric, it.metric_now as number), me: it.ticker === me.ticker }))
    if (items.length < 2) return null
    return { metricKo: METRIC_SHORT[cb.metric] ?? cb.metric_ko, direction: desc ? "desc" : "asc", rank: items.findIndex((x) => x.me) + 1, items }
  }
  return null
}
