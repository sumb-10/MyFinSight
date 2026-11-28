import type { BarBlock, CompaniesBlock, FunnelBlock, ReportDoc, ReportSummary, TableBlock, WeightsCompareBlock } from "../../../api/types"
import { CITE_RE } from "../../../lib/citations"
import { keyAlerts } from "../Dashboard"
import { strategyInfoOf } from "../proposedView"
import { periodOf } from "../wording"

// 왕초보용 리포트 화면이 쓰는 값 (2026-11-28). 원래 리포트와 같은 서버 문서에서 꺼내고, 숫자를 새로 만들지 않는다:
// 수익률·낙폭·비중·금액·주의 문장은 서버 값 그대로이고, 여기서 하는 계산은 「100만원이었다면」 예시(서버 수익률 × 100만원)와 달러 → 원 표시뿐이다.
// 어려운 지표(연환산·Sharpe·뉴스 반영 구성·조건 점검 표·리밸런싱 기록·근거 번호)는 꺼내지 않는다 — 원래 리포트에 있다.

/** 그래프 색: 내 전략은 파랑, 비교 대상은 주황·초록·분홍 순. */
export const EASY_BLUE = "#3d7bf3"
const BENCH_COLORS = ["#f2953b", "#4fb83a", "#ee3d5e"]

/** 비교 대상의 쉬운 이름 (지수 이름만). 모르는 것은 티커 그대로. */
const BENCH_SHORT: Record<string, string> = { SPY: "S&P 500", QQQ: "나스닥 100", "069500.KS": "코스피 200" }
export const benchShort = (id: string) => { const t = id.replace(/^benchmark_/, ""); return BENCH_SHORT[t] ?? t }

export interface EasySeries { id: string; name: string; mine: boolean; color: string; values: (number | null)[]; last: number | null }
export interface EasyDrop { mdd: number; benchMdd: number | null; benchName: string | null; tolerance: number | null; over: boolean | null; peakIdx: number | null; troughIdx: number | null }
export interface EasyHolding { ticker: string; name: string; about: string; weight: number; amount: string }
/** 넣은 돈과 그 돈의 가치 (두 선). 금액은 서버 계열(달러)을 분석한 날 환율로 원화로 바꾼 값 — 원래 리포트의 「최종 평가금액 · 투입 원금」과 같은 방식. */
export interface EasyMoney { series: EasySeries[]; invested: number; final: number; text: (v: number) => string; monthly: boolean; won: boolean }
/** 해마다의 수익률 (서버 「연도별 수익률」 표). */
export interface EasyYearly { years: string[]; mine: (number | null)[]; bench: (number | null)[] | null; benchName: string | null; note: string | null }
/** 수익에 보탠 회사 (서버 「종목별 수익 기여」): 많이 보탠 순 3개와 가장 많이 깎은 1개. */
export interface EasyContrib { top: { name: string; value: number }[]; worst: { name: string; value: number } | null }
export interface EasyModel {
  dates: string[]
  series: EasySeries[]                 // 첫째가 내 전략
  periodText: string                   // "3년" · "2년 6개월" · "8개월"
  total: number | null                 // 내 전략의 전체 기간 수익률 (0.42 = 42%)
  bench: { name: string; total: number } | null
  yearly: number | null                // 1년 평균 수익률 (서버가 연환산을 믿을 만하다고 한 긴 기간만)
  drop: EasyDrop | null
  baseText: string | null              // 나눠 담는 돈 ("1,000만원")
  baseNote: string | null              // 0원 시작이면 "첫 적립금"
  holdings: EasyHolding[]
  money: EasyMoney | null
  byYear: EasyYearly | null
  sectors: { name: string; weight: number }[]   // 분야별 비중 (지금 구성의 회사별 비중을 분야로 묶은 값, 큰 순)
  contrib: EasyContrib | null
  cash: { weight: number; amount: string | null } | null
  weighting: string | null             // 나누는 방법 한 줄
  how: string | null                   // 회사를 고른 기준 (서버 요약 문장)
  steps: { label: string; count: number }[]
  alerts: string[]
  allClear: boolean                    // 주의할 점이 없고 서버 판정이 「충족」
  next: string[]
}

const num = (v: unknown): number | null => (typeof v === "number" && Number.isFinite(v) ? v : null)
const stripCites = (s: string) => s.replace(CITE_RE, "").replace(/\s+([.,])/g, "$1").replace(/\s{2,}/g, " ").trim()

/** 기간을 쉬운 말로: 36개월 → "3년", 30개월 → "2년 6개월", 8개월 → "8개월". */
export function periodText(start: string, end: string): string {
  const a = new Date(`${start}T00:00:00Z`).getTime(), b = new Date(`${end}T00:00:00Z`).getTime()
  if (!Number.isFinite(a) || !Number.isFinite(b) || b <= a) return ""
  const months = Math.max(1, Math.round((b - a) / 86_400_000 / 30.4375))
  const y = Math.floor(months / 12), m = months % 12
  return y === 0 ? `${m}개월` : m === 0 ? `${y}년` : `${y}년 ${m}개월`
}

/** 원화 금액을 읽기 쉬운 단위로: 1,000만원 · 63만원 · 5천원 단위. */
export function roughWon(v: number): string {
  const n = Math.abs(v)
  const r = n >= 1_000_000 ? Math.round(v / 10_000) * 10_000 : n >= 10_000 ? Math.round(v / 1_000) * 1_000 : Math.round(v)
  const eok = Math.floor(Math.abs(r) / 100_000_000), man = Math.floor((Math.abs(r) % 100_000_000) / 10_000), rest = Math.abs(r) % 10_000
  const parts = [eok ? `${eok.toLocaleString("en-US")}억` : "", man ? `${man.toLocaleString("en-US")}만` : "", rest ? rest.toLocaleString("en-US") : ""].filter(Boolean)
  return `${r < 0 ? "-" : ""}${parts.join(" ") || "0"}원`
}

/** 수익률 글자: 0.4213 → "42.1%" (부호는 쓰는 쪽에서 붙인다). 1000% 이상은 소수 없이. */
export const pctAbs = (v: number) => { const p = Math.abs(v) * 100; return `${p >= 1000 ? Math.round(p).toLocaleString("en-US") : p.toFixed(1)}%` }
export const pctSigned = (v: number) => `${v > 0 ? "+" : v < 0 ? "−" : ""}${pctAbs(v)}`

/** 100만원이 그 수익률이면 얼마가 되는가 (예시). */
export const fromMillion = (r: number) => roughWon(1_000_000 * (1 + r))

function seriesOf(doc: ReportDoc, sm: ReportSummary): EasySeries[] {
  const chosen = sm.verdict.chosen_portfolio_id || doc.header.chosen_portfolio_id
  const ids = [chosen, ...(sm.mini_series?.ids ?? []).filter((id) => id !== chosen)].filter((id) => doc.datasets.series[id]?.index?.length)
  let b = 0
  return ids.map((id) => {
    const mine = id === chosen
    const values = (doc.datasets.series[id].index ?? []).map((v) => (typeof v === "number" && Number.isFinite(v) ? v / 100 - 1 : null))
    const last = [...values].reverse().find((v) => v !== null) ?? null
    return { id, name: mine ? "내 전략" : benchShort(id), mine, color: mine ? EASY_BLUE : BENCH_COLORS[b++ % BENCH_COLORS.length], values, last }
  })
}

/** 가장 크게 떨어진 구간: 숫자는 서버 판정(r1)·핵심 지표(mdd) 값, 날짜는 서버가 그래프에 꼭 남긴 고점·저점(sampling.pinned) 또는 낙폭 계열의 가장 낮은 점. */
function dropOf(doc: ReportDoc, sm: ReportSummary, mine: EasySeries | undefined, bench: EasySeries | undefined): EasyDrop | null {
  const r1 = sm.validation?.r1 ?? null
  const k = sm.kpis.find((x) => x.id === "mdd")
  const mdd = num(r1?.mdd) ?? (num(k?.value) !== null ? Math.abs(k!.value as number) : null)
  if (mdd === null) return null
  const benchMdd = num(r1?.benchmark_mdd) ?? (num(k?.benchmark_value) !== null ? Math.abs(k!.benchmark_value as number) : null)
  const tolerance = num(r1?.tolerance)
  const dates = doc.datasets.dates
  const dd = mine ? doc.datasets.series[mine.id]?.drawdown : undefined
  let peakIdx: number | null = null, troughIdx: number | null = null
  if (dd?.length) {
    let t = 0
    for (let i = 1; i < dd.length; i++) if (dd[i] < dd[t]) t = i
    if (dd[t] < -1e-9) {
      troughIdx = t
      let p = t
      while (p > 0 && dd[p] < -1e-9) p--
      peakIdx = p
    }
  }
  const pinned = doc.datasets.sampling?.pinned ?? []
  if (pinned.length === 2) {  // 서버가 남긴 고점·저점 날짜가 그래프에 있으면 그 날짜를 쓴다
    const p = dates.indexOf(pinned[0]), t = dates.indexOf(pinned[1])
    if (p >= 0 && t > p) { peakIdx = p; troughIdx = t }
  }
  return { mdd, benchMdd, benchName: benchMdd !== null && bench ? bench.name : null, tolerance, over: tolerance !== null ? mdd > tolerance + 1e-9 : null, peakIdx, troughIdx }
}

/** 다음에 살펴볼 것 가운데 왕초보에게 어려운 말이 든 항목은 뺀다 (원래 리포트에는 그대로 있다). */
const HARD_WORDS = /walk-forward|리밸런싱|백테스트|Black-Litterman|블랙리터만|CAGR|Sharpe|변동성|%p|낙폭 맞춤|시가총액비중|동일비중|역변동성|최소분산|뉴스 뷰/i

const blocksOf = (doc: ReportDoc) => doc.sections.flatMap((x) => x.blocks)

function moneyOf(doc: ReportDoc, sm: ReportSummary, chosen: string): EasyMoney | null {
  const v = doc.datasets.series[chosen]?.value_usd, inv = doc.datasets.series.net_invested?.value_usd
  if (!v?.length || !inv?.length) return null
  const fx = sm.allocation?.fx_rate ?? 0
  const won = fx > 0 && Math.abs(fx - 1) > 1e-9
  const k = won ? fx : 1
  const vals = (xs: number[]) => xs.map((x) => (typeof x === "number" && Number.isFinite(x) ? x * k : null))
  const value = vals(v), invested = vals(inv)
  const last = (xs: (number | null)[]) => [...xs].reverse().find((x) => x !== null) ?? null
  const a = last(invested), b = last(value), first = invested.find((x) => x !== null) ?? null
  if (a === null || b === null) return null
  return {
    series: [{ id: "value", name: b >= a ? "불어난 돈" : "남은 돈", mine: true, color: EASY_BLUE, values: value, last: b }, { id: "invested", name: "넣은 돈", mine: false, color: "#6b7480", values: invested, last: a }],
    invested: a, final: b, won, monthly: first !== null && a > first * 1.001,
    text: (x: number) => (won ? roughWon(x) : `${Math.round(x).toLocaleString("en-US")}달러`),
  }
}

function yearlyOf(doc: ReportDoc, chosenLabel: string, bench: EasySeries | undefined): EasyYearly | null {
  const t = blocksOf(doc).find((b) => b.type === "table" && b.title_ko === "연도별 수익률") as TableBlock | undefined
  const years = (t?.columns ?? []).map((c) => c.key).filter((k) => /^\d{4}$/.test(k))
  if (!t || years.length < 2 || !t.rows.length) return null
  const mineRow = t.rows.find((r) => r.name === chosenLabel) ?? t.rows[0]
  const benchRow = t.rows.find((r) => r !== mineRow)
  const pick = (r: Record<string, unknown>) => years.map((y) => num(r[y]))
  return { years, mine: pick(mineRow), bench: benchRow ? pick(benchRow) : null, benchName: benchRow ? (bench?.name ?? String(benchRow.name ?? "비교 대상")) : null, note: t.note_ko ?? null }
}

function contribOf(doc: ReportDoc, sm: ReportSummary): EasyContrib | null {
  const b = blocksOf(doc).find((x) => x.type === "bar" && /^종목별 수익 기여/.test(x.title_ko)) as BarBlock | undefined
  if (!b) return null
  const names = new Map<string, string>()
  for (const x of blocksOf(doc)) {
    if (x.type === "weights_compare") for (const r of (x as WeightsCompareBlock).rows) names.set(r.ticker, r.name)
    if (x.type === "companies") for (const it of (x as CompaniesBlock).items) names.set(it.ticker, it.name)
  }
  for (const it of sm.allocation?.items ?? []) names.set(it.ticker, it.name)
  const items = b.items.filter((x) => !/^(거래비용|현금)/.test(x.label) && Number.isFinite(x.value)).map((x) => ({ name: names.get(x.label) || x.label, value: x.value }))
  const top = items.filter((x) => x.value > 0).sort((x, y) => y.value - x.value).slice(0, 3)
  const worst = items.filter((x) => x.value < 0).sort((x, y) => x.value - y.value)[0] ?? null
  return top.length ? { top, worst } : null
}

function sectorsOf(sm: ReportSummary): { name: string; weight: number }[] {
  const by = new Map<string, number>()
  for (const it of sm.allocation?.items ?? []) by.set(it.sector || "기타", (by.get(it.sector || "기타") ?? 0) + it.weight)
  return [...by].map(([name, weight]) => ({ name, weight })).sort((x, y) => y.weight - x.weight)
}

const FUNNEL_STEPS: [RegExp, string][] = [[/^투자 가능 종목/, "살 수 있는 회사"], [/^테마 해당 판정/, "주제에 맞는 회사"]]

export function easyModel(doc: ReportDoc): EasyModel | null {
  const sm = doc.summary
  if (!sm) return null
  const series = seriesOf(doc, sm)
  const mine = series.find((s) => s.mine), bench = series.find((s) => !s.mine)
  const period = periodOf(doc)
  const cagr = sm.kpis.find((k) => k.id === "cagr")
  const short = !!cagr && /^기간 수익률/.test(cagr.label_ko)
  // 전체 기간 수익률: 그래프와 같은 서버 계열의 마지막 값 (원래 리포트의 「전체 기간 수익률」과 같은 값). 계열이 없으면 서버 기간 수익률
  const total = mine?.last ?? (short ? num(cagr?.value) : null)
  const yearly = !short && period.annualized_reliable !== false ? num(cagr?.value) : null

  const a = sm.allocation
  const usdOnly = !a || !(a.fx_rate > 0) || Math.abs(a.fx_rate - 1) < 1e-9
  const amount = (usd: number, krw: number) => (usdOnly ? `${usd.toLocaleString("en-US", { maximumFractionDigits: 0 })}달러` : roughWon(krw))
  const companies = doc.sections.flatMap((s) => s.blocks).find((b) => b.type === "companies") as CompaniesBlock | undefined
  const about = new Map((companies?.items ?? []).map((c) => [c.ticker, (c.theme_reason_ko || "").replace(/^필수 포함 종목\s*·\s*/, "").trim() || c.sub_industry || c.sector]))
  const items = a ? [...a.items].sort((x, y) => y.weight - x.weight) : []
  const holdings = items.map((x) => ({ ticker: x.ticker, name: x.name && x.name !== x.ticker ? x.name : x.ticker, about: about.get(x.ticker) || x.sector || "", weight: x.weight, amount: amount(x.usd, x.krw) }))
  const cashW = a && a.cash_weight >= 0.0005 ? a.cash_weight : 0
  const cash = cashW > 0 && a ? { weight: cashW, amount: amount(a.initial_amount_usd * cashW, a.initial_amount_usd * cashW * a.fx_rate) } : null
  const baseText = a ? amount(a.initial_amount_usd, a.initial_amount_usd * a.fx_rate) : null

  const funnel = doc.sections.flatMap((s) => s.blocks).find((b) => b.type === "funnel") as FunnelBlock | undefined
  const steps = FUNNEL_STEPS.flatMap(([re, label]) => { const it = funnel?.items.find((x) => re.test(x.label_ko)); return it ? [{ label, count: it.count }] : [] })
  if (steps.length && holdings.length) steps.push({ label: "담은 회사", count: holdings.length })

  const h = doc.header
  // 고른 기준: 머리말에 요청 요약(summary_ko)이 따로 보이면 해석 문장(subtitle_ko)을, 머리말이 해석 문장을 쓰는 옛 리포트는 겹치지 않게 비운다
  const how = h.summary_ko && h.subtitle_ko && h.subtitle_ko !== h.summary_ko ? stripCites(h.subtitle_ko) : null
  const drop = dropOf(doc, sm, mine, bench)
  // 주의 문장: 서버의 쉬운 문장을 그대로 쓴다. 쉬운 문장이 없는 옛 리포트는 위 구획이 이미 말한 두 가지(비교 대상보다 덜 오름 · 견딜 수 있는 폭보다 크게 떨어짐)의 전문 용어 줄을 뺀다
  const plain = Object.keys(sm.validation?.rules_plain_ko ?? {}).length > 0
  const said = (t: string) => !plain && ((/^비교지수 대비:/.test(t) && !!bench) || (/^최대낙폭:/.test(t) && !!drop))
  const alerts = keyAlerts(sm).map((x) => stripCites(x.text)).filter((t) => t && !said(t))
  return {
    dates: doc.datasets.dates, series, periodText: periodText(period.start, period.end), total,
    bench: bench && bench.last !== null ? { name: bench.name, total: bench.last } : null, yearly,
    drop,
    baseText, baseNote: a?.amount_basis_ko ?? null, holdings, cash,
    money: moneyOf(doc, sm, sm.verdict.chosen_portfolio_id || h.chosen_portfolio_id),
    byYear: yearlyOf(doc, sm.verdict.chosen_label_ko || h.chosen_label_ko, bench),
    sectors: sectorsOf(sm), contrib: contribOf(doc, sm),
    weighting: strategyInfoOf(doc, sm.verdict.chosen_portfolio_id || h.chosen_portfolio_id)?.short ?? null,
    how, steps, alerts, allClear: alerts.length === 0 && sm.validation?.chosen_status === "pass",
    next: (sm.next_actions_ko ?? []).map(stripCites).filter((t) => t && !HARD_WORDS.test(t)),
  }
}
