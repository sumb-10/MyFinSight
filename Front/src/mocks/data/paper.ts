// 목업 모의투자. 같은 리포트의 가격 경로(backtest.sim)를 그대로 써서 리포트와 숫자가 이어진다.
// 원화 성과는 날짜별 원화 납입액과 원화 평가액(= USD 평가액 × 그날 환율)으로 계산한다 — USD 수익률에 환율을 곱하지 않는다.
import type { PaperDetail, PaperPreview, PaperRebalance, PaperSnapshot, PaperStrategy } from "../../api/types"
import type { ProposedPaperKrw } from "../../api/proposed"
import type { PaperScenario, ReportScenario } from "../scenarios"
import { MOCK_AS_OF } from "../scenarios"
import { ApiError } from "../../api/client"
import { COMMISSION_BPS, templateWeights, type Backtest } from "./backtest"
import { normal, rng, round, seedOf, sum } from "./util"

export interface MockPaper { detail: PaperDetail; krw: ProposedPaperKrw }

/** 예시 환율 경로 (리포트의 백테스트 시작 환율 → 기준일 환율, 작은 흔들림). gaps 날은 자료 없음 → 직전 환율로 대체, missingUntil 까지는 환율 없음. */
export function fxPath(dates: string[], from: number, to: number, seed: string, gaps: string[] = [], missingUntil?: string) {
  const r = rng(seedOf(seed)), n = Math.max(1, dates.length - 1)
  let last: { rate: number; date: string } | null = null
  return dates.map((d, i) => {
    const raw = round(from + ((to - from) * i) / n + normal(r) * 3, 2)
    if (missingUntil && d <= missingUntil) return { date: d, rate: null, status: "missing" as const, carried_from: null }
    if (gaps.includes(d) && last) return { date: d, rate: last.rate, status: "carried" as const, carried_from: last.date }
    last = { rate: raw, date: d }
    return { date: d, rate: raw, status: "ok" as const, carried_from: null }
  })
}

export function strategyFor(bt: Backtest, sc: ReportScenario, ps: Pick<PaperScenario, "strategy">, at: number): { s: PaperStrategy; w: Record<string, number>; cash: number } {
  if (ps.strategy === "chosen") {
    const d = bt.chosen.def
    return { s: { id: d.id, kind: d.kind === "black_litterman" ? "black_litterman" : d.kind === "matched" ? "cash_blend" : "template", template: d.kind === "template" ? d.id : null, cash_ratio: d.cash, name_ko: d.label_ko }, w: d.weights, cash: d.cash }
  }
  const w = templateWeights(sc, bt.sim, ps.strategy, at)
  const name = bt.runs.find((r) => r.def.id === ps.strategy)?.def.label_ko ?? ps.strategy
  return { s: { id: ps.strategy, kind: "template", template: ps.strategy, cash_ratio: 0, name_ko: name }, w, cash: 0 }
}

export function buildPaper(ps: PaperScenario, sc: ReportScenario, bt: Backtest, name_ko: string, status: "active" | "stopped"): MockPaper {
  const i0 = Math.max(0, bt.sim.dates.findIndex((d) => d >= ps.start_date))
  const dates = bt.sim.dates.slice(i0)
  const { s, w, cash } = strategyFor(bt, sc, ps, i0)
  const fx = fxPath(dates, 1365, 1380, `fx:${ps.id}`, ps.fx_gaps, ps.fx_missing_until)
  const fx0 = fx.find((f) => f.rate !== null)?.rate ?? 1380
  const usd0 = ps.capital.currency === "KRW" ? ps.capital.amount / fx0 : ps.capital.amount
  const commission = COMMISSION_BPS / 10000
  let V = usd0 * (1 - commission), B = usd0, u = 1, peak = 1, contribUsd = usd0, contribKrw: number | null = ps.capital.currency === "KRW" ? ps.capital.amount : fx[0].rate ? usd0 * fx[0].rate : null
  const snaps: PaperSnapshot[] = [], rebs: PaperRebalance[] = []
  const valueKrw: (number | null)[] = []
  let maxDd = 0
  let lastRb = i0, nRb = 0  // 마지막 리밸런싱(처음엔 최초 매수) 날의 가격 위치, 리밸런싱 횟수 (실제 서버처럼 적립 매수는 세지 않는다)
  dates.forEach((d, k) => {
    const i = i0 + k
    let add = 0
    if (k > 0) {
      const r = sum(Object.entries(w).map(([t, x]) => x * bt.sim.ret[t][i]))
      V *= 1 + r; B *= 1 + bt.sim.ret.SPY[i]; u *= 1 + r
      const newMonth = d.slice(0, 7) !== dates[k - 1].slice(0, 7)
      if (newMonth && ps.capital.monthly) {
        add = ps.capital.currency === "KRW" ? ps.capital.monthly / (fx[k].rate ?? fx0) : ps.capital.monthly
        V += add * (1 - commission); B += add; contribUsd += add
        contribKrw = contribKrw === null ? null : contribKrw + (ps.capital.currency === "KRW" ? ps.capital.monthly : fx[k].rate ? add * fx[k].rate : NaN)
      }
      if (newMonth && add) rebs.push({ date: d, seq: nRb, kind: "contribution", before_weights: w, target_weights: w, applied_weights: w, trades: Object.entries(w).map(([t, x]) => ({ ticker: t, side: "buy" as const, shares: (add * x) / bt.sim.price[t][i], price: round(bt.sim.price[t][i]), value_usd: round(add * x) })).filter((t) => t.value_usd > 0), commission_usd: round(add * commission), turnover: 0.02, fallback: false, skipped: false, note_ko: "[목업] 월 적립금을 목표 비중대로 매수" })
      if (newMonth) {
        // 정기 리밸런싱(매월 첫 거래일): 지난 리밸런싱 뒤 가격이 달라 틀어진 비중을 목표 비중으로 되돌린다 → 오른 종목은 팔고 내린 종목은 산다
        const held = Object.fromEntries(Object.entries(w).map(([t, x]) => [t, (x * bt.sim.price[t][i]) / bt.sim.price[t][lastRb]]))
        const tot = sum(Object.values(held)) + cash
        const before = Object.fromEntries(Object.entries(held).map(([t, h]) => [t, h / tot]))
        const trades = Object.keys(w).map((t) => { const v = (w[t] - before[t]) * V; return { ticker: t, side: (v >= 0 ? "buy" : "sell") as "buy" | "sell", shares: Math.abs(v) / bt.sim.price[t][i], price: round(bt.sim.price[t][i]), value_usd: round(Math.abs(v)) } }).filter((x) => x.value_usd >= 1)
        const fee = round(sum(trades.map((x) => x.value_usd)) * commission)
        u *= 1 - fee / V; V -= fee
        nRb += 1; lastRb = i
        rebs.push({ date: d, seq: nRb, kind: "rebalance", before_weights: before, target_weights: w, applied_weights: w, trades, commission_usd: fee, turnover: round(sum(Object.keys(w).map((t) => Math.abs(w[t] - before[t]))) / 2, 4), fallback: false, skipped: false, note_ko: "[목업] 정기 리밸런싱 (종목 유지, 비중만 갱신)" })
      }
    } else rebs.push({ date: d, seq: 0, kind: "initial", before_weights: {}, target_weights: w, applied_weights: w, trades: Object.entries(w).map(([t, x]) => ({ ticker: t, side: "buy" as const, shares: (usd0 * x) / bt.sim.price[t][i], price: round(bt.sim.price[t][i]), value_usd: round(usd0 * x) })), commission_usd: round(usd0 * commission), turnover: 1, fallback: false, skipped: false })
    peak = Math.max(peak, u); const dd = u / peak - 1; maxDd = Math.min(maxDd, dd)
    valueKrw.push(fx[k].rate ? Math.round(V * fx[k].rate) : null)
    snaps.push({ date: d, value_usd: round(V), cash_usd: round(V * cash), holdings_value_usd: round(V * (1 - cash)), weights: w, drawdown: dd, return_since_start: u - 1, unit_price: u, contribution_usd: round(add), contributions_total_usd: round(contribUsd - usd0), benchmark_value_usd: round(B), benchmark_return_since_start: B / contribUsd - 1, fx_rate: fx[k].rate, status: "ok", warnings: fx[k].status === "carried" ? [`[목업] ${d} 환율 자료가 없어 ${fx[k].carried_from} 환율을 썼습니다.`] : [] })
  })
  const last = snaps[snaps.length - 1]
  const lastKrw = valueKrw[valueKrw.length - 1]
  const cK = contribKrw !== null && Number.isFinite(contribKrw) ? Math.round(contribKrw) : 0
  const capital = { amount: ps.capital.amount, currency: ps.capital.currency, usd: round(usd0), fx_rate: fx0, fx_date: fx.find((f) => f.rate !== null)?.date ?? ps.start_date }
  const summary = {
    paper_id: ps.id, name_ko, strategy: s, report_id: ps.report_id, run_id: sc.run_id, status, start_date: dates[0], last_date: last.date, days_tracked: dates.length,
    initial_capital: capital, value_usd: last.value_usd, contributions_total_usd: round(contribUsd - usd0), gain_usd: round(last.value_usd - contribUsd), return_since_start: last.return_since_start, benchmark: "SPY", benchmark_return_since_start: last.benchmark_return_since_start ?? null, excess_return: last.return_since_start - (last.benchmark_return_since_start ?? 0),
    drawdown: last.drawdown, max_drawdown: maxDd, n_rebalances: nRb, update_status: "ok" as const, delayed_reason_ko: null, last_refresh_at: `${MOCK_AS_OF}T18:00:00`, data_ceiling: MOCK_AS_OF, reconstructed_at_start: false,
  }
  const detail: PaperDetail = {
    portfolio: { paper_id: ps.id, report_id: ps.report_id, run_id: sc.run_id, strategy_id: s.id, strategy: s, name_ko, start_date: dates[0], report_as_of: MOCK_AS_OF, reconstructed_at_start: false, initial_capital: capital, contribution: { enabled: !!ps.capital.monthly, monthly_amount: ps.capital.monthly, currency: ps.capital.currency, day: 1 }, rebalance_rule: { count: 1, unit: "1m" }, benchmark: "SPY", tickers: Object.keys(w), start_weights: w,
      state: { holdings: Object.fromEntries(Object.entries(w).map(([t, x]) => [t, (last.value_usd * x) / bt.sim.price[t][i0 + dates.length - 1]])), cash_usd: last.cash_usd, last_snapshot_date: last.date, last_rebalance_date: [...rebs].reverse().find((r) => r.kind !== "contribution")?.date ?? null, n_rebalances: nRb, target_weights: w, cash_weight: cash, update_status: "ok", delayed_reason_ko: null, last_refresh_at: `${MOCK_AS_OF}T18:00:00` },
      status, created_at: `${ps.start_date}T09:00:00`, stopped_at: status === "stopped" ? "2026-10-15T09:00:00" : null, resumed_at: null, history: [{ at: `${ps.start_date}T09:00:00`, event: "started" }, ...(status === "stopped" ? [{ at: "2026-10-15T09:00:00", event: "stopped" }] : [])], warnings: [], constraints_snapshot: { commission_bps: COMMISSION_BPS } },
    summary, snapshots: snaps, rebalances: rebs,
    series: { dates, value_usd: snaps.map((x) => x.value_usd), benchmark_value_usd: snaps.map((x) => x.benchmark_value_usd ?? null), return_since_start: snaps.map((x) => x.return_since_start), benchmark_return_since_start: snaps.map((x) => x.benchmark_return_since_start ?? null), drawdown: snaps.map((x) => x.drawdown) },
  }
  const fxDays = fx.map(({ date, rate, status: st, carried_from }) => ({ date, rate, status: st, carried_from }))
  const lastFx = fxDays[fxDays.length - 1], startFx = fxDays[0]
  const okK = contribKrw !== null && Number.isFinite(contribKrw) && cK > 0
  const returnKrw = lastKrw !== null && okK ? lastKrw / cK - 1 : null
  const returnUsd = last.value_usd / contribUsd - 1
  const krw: ProposedPaperKrw = {
    fx: fxDays, value_krw: valueKrw, contributions_krw_total: okK ? cK : null,
    last: { date: last.date, value_krw: lastKrw, fx: lastFx },
    gain_krw: lastKrw !== null && okK ? lastKrw - cK : null, return_krw: returnKrw,
    usd_same_basis: { contributions_usd: round(contribUsd), value_usd: last.value_usd, gain_usd: round(last.value_usd - contribUsd), return_usd: returnUsd },
    fx_start: startFx, fx_change: startFx.rate && lastFx.rate ? lastFx.rate / startFx.rate - 1 : null,
    fx_effect_pp: returnKrw === null ? null : returnKrw - returnUsd,
    fx_counts: { ok: fxDays.filter((f) => f.status === "ok").length, carried: fxDays.filter((f) => f.status === "carried").length, missing: fxDays.filter((f) => f.status === "missing").length },
    unavailable_reason_ko: lastKrw === null ? "마지막 평가일의 환율이 없어 원화로 환산할 수 없습니다." : !okK ? `시작일(${startFx.date})의 환율이 없어 넣은 원금을 원화로 정할 수 없습니다.` : null,
  }
  return { detail, krw }
}

/** 목업 시작일 규칙 (서버 m6_tracking/paper.py _plan 과 같은 뜻): 분석일 이전도 되고, 가장 이른 날은 가격 경로의 앞쪽 약 6개월(비중 계산에 쓸 과거 자료)을 뺀 날. */
export const paperDataStart = (bt: Backtest) => bt.sim.dates[Math.min(bt.sim.dates.length - 1, 126)]
export function paperStartIndex(bt: Backtest, startDate: string | null | undefined): number {
  const dates = bt.sim.dates, earliest = paperDataStart(bt)
  const want = startDate && startDate < MOCK_AS_OF ? startDate : MOCK_AS_OF
  if (want < earliest) throw new ApiError("REQUEST_INVALID", `[목업] 시작일 ${want} 에는 비중을 계산할 자료가 모자랍니다. ${earliest} 이후 날짜로 시작해 주세요`, 422)
  let i = dates.length - 1
  while (i > 0 && dates[i] > want) i--  // 거래일이 아니면 앞 거래일
  return i
}

export function paperPreview(sc: ReportScenario, bt: Backtest, strategyId: string | null | undefined, amount: number, currency: "KRW" | "USD", monthly: number | null | undefined, startDate?: string | null): PaperPreview {
  const ps = { strategy: !strategyId || strategyId === bt.chosen.def.id ? "chosen" : strategyId }
  const at = paperStartIndex(bt, startDate)
  const start = bt.sim.dates[at]
  const { s, w, cash } = strategyFor(bt, sc, ps, at)
  const fx = 1380, usdAmt = currency === "KRW" ? amount / fx : amount
  const options = bt.runs.map((r) => ({ id: r.def.id, kind: (r.def.kind === "black_litterman" ? "black_litterman" : r.def.kind === "matched" ? "cash_blend" : "template") as PaperStrategy["kind"], template: r.def.kind === "template" ? r.def.id : null, cash_ratio: r.def.cash, name_ko: r.def.label_ko, status: bt.status[r.def.id], recommended: r.def.id === bt.chosen.def.id, chosen: r.def.id === s.id }))
  return { report_id: sc.id, run_id: sc.run_id, report_as_of: MOCK_AS_OF, strategy: s, strategy_options: options, start_date: start, data_start: paperDataStart(bt), data_ceiling: MOCK_AS_OF, reconstructed_at_start: start !== MOCK_AS_OF, initial_capital: { amount, currency, usd: round(usdAmt), fx_rate: fx, fx_date: MOCK_AS_OF }, contribution: { enabled: !!monthly, monthly_amount: monthly ?? 0, currency, day: 1 }, rebalance_rule: { count: 1, unit: "1m" }, benchmark: "SPY", tickers: Object.keys(w), weights: w, cash_weight: cash, report_weights: bt.chosen.def.weights, weight_diff: Object.keys(w).map((t) => ({ ticker: t, report: bt.chosen.def.weights[t] ?? 0, start: w[t], delta: w[t] - (bt.chosen.def.weights[t] ?? 0) })), allocation: Object.entries(w).map(([t, x]) => ({ ticker: t, weight: x, usd: round(usdAmt * x), krw: Math.round(usdAmt * x * fx), price_usd: round(bt.sim.price[t][at]) })), construct_info: { fallback: false, warnings: [] }, warnings: [...(start < MOCK_AS_OF ? [`분석일 ${MOCK_AS_OF} 보다 앞선 날로 시작합니다. 종목은 분석일에 고른 것이라, 그날 실제로 시작했을 때보다 결과가 좋게 나올 수 있습니다.`] : []), "[목업] 목업 모의투자는 서버에 저장되지 않습니다."] }
}
