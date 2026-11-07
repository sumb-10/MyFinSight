// 목업 백테스트: 시나리오 정의에서 종목 수익률(결정적 난수) → 전략별 시계열 → 지표 → 검증 규칙 → 순위·결론까지 한 번에 계산한다.
// 화면에 보이는 숫자(성과·검증 문장·판단 이유)는 모두 여기서 나온 값이라 서로 어긋나지 않는다. 규칙의 모양은 백엔드(validate.py)를 따라 했지만
// 실제 백엔드 계산이 아니다 — 시세는 예시 값이고, 리밸런싱은 매일 같은 비중을 유지한다고 단순화했다.
import type { ReportScenario } from "../scenarios"
import { MOCK_AS_OF } from "../scenarios"
import { stockOf } from "./stocks"
import { addDays, capWeights, mean, normal, normalize, rng, seedOf, std, sum, tradingDays } from "./util"

export const RF = 0.04
export const COMMISSION_BPS = 5
export const MIN_ANNUALIZE_DAYS = 378
export const VOL_MULT: Record<string, number | null> = { low: 1, medium: 1.3, high: null }
export const VOL_BAND_ABS: Record<string, number> = { low: 0.15, medium: 0.3, high: 9.99 }
export const NAMES_KO: Record<string, string> = { equal_weight: "동일비중", market_cap: "시가총액비중", inverse_volatility: "역변동성비중", min_variance: "최소분산" }
export const RULES_KO: Record<string, string> = { equal_weight: "모든 종목에 같은 비중 1/N", market_cap: "시가총액에 비례한 비중 (지수 방식)", inverse_volatility: "변동성이 낮은 종목에 더 큰 비중 (1/σ 정규화)", min_variance: "포트폴리오 분산을 최소화하는 비중 (제약 포함 최적화)" }

export interface Sim { dates: string[]; ret: Record<string, number[]>; price: Record<string, number[]> }

/** 종목·비교지수 일별 수익률과 가격 경로 (끝 가격 = 분석 기준일 예시 주가). */
export function simulate(sc: ReportScenario): Sim {
  const end = MOCK_AS_OF
  const start = addDays(end, -Math.round(sc.backtest_years * 365))
  const dates = tradingDays(start, end)
  const n = dates.length
  const rm = rng(seedOf(`market:${sc.id.replace("_revised", "_normal")}`))  // 수정안은 원안과 같은 시장 흐름
  const zm = dates.map((_, i) => (i === 0 ? 0 : normal(rm)))
  const ret: Record<string, number[]> = {}
  for (const t of [...sc.tickers, "SPY", "QQQ"]) {
    const s = stockOf(t)
    const r = rng(seedOf(`stock:${t}:${sc.id.replace("_revised", "_normal")}`))
    const bench = t === "SPY" || t === "QQQ"
    const drift = bench ? (t === "SPY" ? sc.bench_drift : sc.bench_drift + 0.02) : s.drift + sc.drift_shift
    const beta = bench ? 0.95 : 0.65
    ret[t] = dates.map((_, i) => (i === 0 ? 0 : drift / 252 + (s.vol / Math.sqrt(252)) * (beta * zm[i] + Math.sqrt(1 - beta * beta) * normal(r))))
  }
  const price: Record<string, number[]> = {}
  for (const [t, r] of Object.entries(ret)) {
    const p = new Array<number>(n)
    p[n - 1] = stockOf(t).price_usd
    for (let i = n - 1; i > 0; i--) p[i - 1] = p[i] / (1 + r[i])
    price[t] = p
  }
  return { dates, ret, price }
}

export interface PortfolioDef { id: string; label_ko: string; kind: "template" | "black_litterman" | "matched" | "benchmark"; rule_ko: string; weights: Record<string, number>; cash: number; base_id?: string; title_ko?: string }

/** 시작일(t=0) 자료로 정한 비중. */
export function templateWeights(sc: ReportScenario, sim: Sim, kind: string, at = 0): Record<string, number> {
  const ts = sc.tickers
  const raw: Record<string, number> = {}
  for (const t of ts) {
    const s = stockOf(t)
    const mcap = s.mcap_bn_usd * (sim.price[t][at] / s.price_usd)
    raw[t] = kind === "equal_weight" ? 1 : kind === "market_cap" ? mcap : kind === "inverse_volatility" ? 1 / s.vol : 1 / (s.vol * s.vol)
  }
  return capWeights(normalize(raw), sc.max_weight)
}

export const BL_TITLES = ["실적 전망과 수요 신호", "공급 제약과 가격 흐름", "경쟁 구도와 상대 가치"]

export function candidates(sc: ReportScenario, sim: Sim): PortfolioDef[] {
  const out: PortfolioDef[] = (["equal_weight", "market_cap", "inverse_volatility", "min_variance"] as const).map((k) => ({ id: k, label_ko: NAMES_KO[k], kind: "template", rule_ko: RULES_KO[k], weights: templateWeights(sc, sim, k), cash: 0 }))
  if (sc.news) {
    const base = templateWeights(sc, sim, sc.baseline)
    BL_TITLES.forEach((title, i) => {
      const r = rng(seedOf(`bl:${sc.id}:${i}`))
      const tilt: Record<string, number> = {}
      for (const t of sc.tickers) tilt[t] = Math.max(0.01, base[t] + (r() - 0.5) * 0.1)
      out.push({ id: `bl_0${i + 1}`, label_ko: `뉴스 뷰: ${title}`, kind: "black_litterman", rule_ko: `${title}에 관한 뉴스·공시 헤드라인으로 만든 투자 의견을 기준 비중에 제한적으로 반영했습니다.`, weights: capWeights(normalize(tilt), sc.max_weight), cash: 0, title_ko: title })
    })
  }
  return out
}

export interface Metrics { total_return: number; cagr: number; vol: number; sharpe: number; mdd: number; final_usd: number; net_invested_usd: number; irr: number }
export interface Run { def: PortfolioDef; index: number[]; value: number[]; invested: number[]; drawdown: number[]; daily: number[]; m: Metrics }

export function contributionDays(sc: ReportScenario, dates: string[]): Set<number> {
  const out = new Set<number>()
  if (!sc.capital.monthly) return out
  let lastMonth = dates[0].slice(0, 7)
  for (let i = 1; i < dates.length; i++) {
    const ym = dates[i].slice(0, 7), day = Number(dates[i].slice(8))
    if (ym !== lastMonth && day >= Math.min(sc.capital.day, 28)) { out.add(i); lastMonth = ym }
  }
  return out
}

export const toUsd = (sc: ReportScenario, krwOrUsd: number, fx: number) => (sc.capital.currency === "KRW" ? krwOrUsd / fx : krwOrUsd)

export function runPortfolio(sc: ReportScenario, sim: Sim, def: PortfolioDef): Run {
  const n = sim.dates.length
  const contrib = contributionDays(sc, sim.dates)
  const init = toUsd(sc, sc.capital.amount, sc.fx_bt), monthly = toUsd(sc, sc.capital.monthly, sc.fx_bt)
  const index = [100], value = [init], invested = [init], daily = [0]
  for (let i = 1; i < n; i++) {
    const r = sum(Object.entries(def.weights).map(([t, w]) => w * sim.ret[t][i]))
    daily.push(r)
    index.push(index[i - 1] * (1 + r))
    const add = contrib.has(i) ? monthly : 0
    value.push(value[i - 1] * (1 + r) + add)
    invested.push(invested[i - 1] + add)
  }
  return finish(def, index, value, invested, daily, sim.dates, contrib, init, monthly)
}

function finish(def: PortfolioDef, index: number[], value: number[], invested: number[], daily: number[], dates: string[], contrib: Set<number>, init: number, monthly: number): Run {
  let peak = index[0]
  const drawdown = index.map((x) => { peak = Math.max(peak, x); return x / peak - 1 })
  const n = index.length - 1
  const tr = index[n] / 100 - 1
  const cagr = (1 + tr) ** (252 / n) - 1
  const vol = std(daily.slice(1)) * Math.sqrt(252)
  const flows = [{ i: 0, v: -init }, ...[...contrib].map((i) => ({ i, v: -monthly })), { i: n, v: value[n] }]
  const days = (i: number) => (new Date(`${dates[i]}T00:00:00Z`).getTime() - new Date(`${dates[0]}T00:00:00Z`).getTime()) / 86400000
  const npv = (r: number) => sum(flows.map((f) => f.v / (1 + r) ** (days(f.i) / 365)))
  let lo = -0.95, hi = 10
  for (let k = 0; k < 100; k++) { const mid = (lo + hi) / 2; if (npv(mid) > 0) lo = mid; else hi = mid }
  return { def, index, value, invested, drawdown, daily, m: { total_return: tr, cagr, vol, sharpe: vol ? (cagr - RF) / vol : 0, mdd: Math.min(...drawdown), final_usd: value[n], net_invested_usd: invested[n], irr: (lo + hi) / 2 } }
}

/** 낙폭 맞춤안: 기준 비중의 주식 비율 c 를 낮춰 과거 최대낙폭을 목표 안에 맞춘다 (나머지는 현금). 맞출 수 없으면 null. */
export function matchDrawdown(sc: ReportScenario, sim: Sim, base: PortfolioDef, target: number): PortfolioDef | null {
  for (let c = 0.99; c >= 0.1; c = Math.round((c - 0.01) * 100) / 100) {
    const w = Object.fromEntries(Object.entries(base.weights).map(([t, v]) => [t, v * c]))
    const run = runPortfolio(sc, sim, { ...base, weights: w, cash: 1 - c })
    if (-run.m.mdd <= target + 1e-9) {
      const eq = Math.round(c * 100)
      return { id: `dd_match_${base.id}`, label_ko: `낙폭 맞춤안 (주식 ${eq}% + 현금 ${100 - eq}%, ${base.label_ko} 기준)`, kind: "matched", rule_ko: `${base.label_ko}의 주식 비율을 ${eq}%로 줄여 과거 최대낙폭을 목표 안에 맞춘 구성`, weights: w, cash: 1 - c, base_id: base.id }
    }
  }
  return null
}

export function benchmarkRun(sc: ReportScenario, sim: Sim, t: "SPY" | "QQQ"): Run {
  return runPortfolio(sc, sim, { id: `benchmark_${t}`, label_ko: `${t} 매수보유 (동일 적립)`, kind: "benchmark", rule_ko: `${t} 를 사서 계속 보유`, weights: { [t]: 1 }, cash: 0 })
}

/* ───────── 검증 (validate.py 의 R1·R2·R3·R7 모양을 따른 목업) ───────── */

export interface Check { rule: string; name_ko: string; level: "flag" | "soft" | "info" | "hard"; status: "pass" | "warn" | "fail" | "flag" | "info"; ok: boolean; value: number | null; threshold: number | null; message_ko: string; basis?: string; multiplier?: number | null }
const pct1 = (x: number) => `${(x * 100).toFixed(1)}%`
const spct1 = (x: number) => `${x > 0 ? "+" : x < 0 ? "-" : ""}${(Math.abs(x) * 100).toFixed(1)}%`
const check = (rule: string, name_ko: string, level: Check["level"], ok: boolean, value: number | null, threshold: number | null, message_ko: string, extra: Partial<Check> = {}): Check =>
  ({ rule, name_ko, level, ok, value, threshold, message_ko, status: level === "info" ? "info" : level === "flag" ? (ok ? "pass" : "flag") : ok ? "pass" : level === "hard" ? "fail" : "warn", ...extra })

export const isShort = (sim: Sim) => sim.dates.length - 1 < MIN_ANNUALIZE_DAYS
export const matchTarget = (sc: ReportScenario) => sc.max_dd * (sc.loss_reaction === "sell" ? 0.8 : 1) * (sc.experience === "none" ? 0.9 : 1)
export const toleranceNote = (sc: ReportScenario) => {
  const t = matchTarget(sc)
  if (Math.abs(t - sc.max_dd) < 1e-9) return `손실 감내 수준 ${pct1(sc.max_dd)}`
  const why = [sc.loss_reaction === "sell" ? "손실 시 매도 성향 ×0.8" : null, sc.experience === "none" ? "투자 경험 없음 ×0.9" : null].filter(Boolean).join(", ")
  return `손실 감내 수준 ${pct1(sc.max_dd)} · 낙폭 맞춤안 목표 ${pct1(t)} (${why})`
}

export function evaluate(sc: ReportScenario, run: Run, bench: Run, short: boolean): Check[] {
  const m = run.m, b = bench.m
  const mdd = Math.abs(m.mdd), bmdd = Math.abs(b.mdd), tol = sc.max_dd
  const out: Check[] = []
  out.push(check("R1", "최대낙폭", "flag", mdd <= tol + 1e-9, mdd, tol, `최대낙폭 ${pct1(mdd)} vs 허용 ${pct1(tol)} (같은 기간 SPY 매수보유 (동일 적립) ${pct1(bmdd)})${mdd <= tol + 1e-9 ? "" : ` — 허용보다 ${pct1(mdd - tol)}p 큼`}`, { basis: "total" }))
  out.push(check("R1b", "비교지수 대비 낙폭", "info", mdd <= bmdd, mdd, bmdd, `비교지수보다 낙폭이 ${mdd <= bmdd ? "작음" : "큼"} (${pct1(mdd)} vs ${pct1(bmdd)})`))
  const soft = short ? "info" : "soft"
  out.push(check("R2", "목표수익", soft, m.cagr >= sc.target_return, m.cagr, sc.target_return,
    short ? `CAGR ${pct1(m.cagr)} vs 목표 ${pct1(sc.target_return)} (기간 수익률 ${spct1(m.total_return)}; 창이 짧아 참고만)`
      : `CAGR ${pct1(m.cagr)} vs 목표 ${pct1(sc.target_return)}${sc.backtest_years < sc.horizon_years ? ` (백테스트 창이 투자기간 ${sc.horizon_years}년보다 짧아 전체 CAGR 로 판정)` : ""}`, { basis: "annualized" }))
  const ex = m.cagr - b.cagr
  out.push(check("R3", "비교지수 대비", "soft", ex > 0, ex, 0, `SPY 대비 초과 CAGR ${spct1(ex)}p`, { basis: "annualized" }))
  const mult = VOL_MULT[sc.vol_pref], prefKo = { low: "안정 성향", medium: "중립 성향", high: "적극 성향" }[sc.vol_pref]
  if (mult === null) out.push(check("R7", "변동성 적합", "info", true, m.vol, null, `연변동성 ${pct1(m.vol)} (비교지수 ${pct1(b.vol)}) — ${prefKo}은 변동성 상한을 두지 않습니다`, { basis: "no_cap", multiplier: null }))
  else {
    const band = b.vol * mult
    out.push(check("R7", "변동성 적합", soft, m.vol <= band, m.vol, band, `연변동성 ${pct1(m.vol)} vs 비교지수 ${pct1(b.vol)}의 ${mult}배(${prefKo}) = ${pct1(band)}${short ? " (창이 짧아 참고만)" : ""}`, { basis: "benchmark_multiple", multiplier: mult }))
  }
  return out
}

export const statusOf = (cks: Check[]) => (cks.some((c) => c.status === "fail") ? "fail" : cks.some((c) => c.status === "warn" || c.status === "flag") ? "warn" : "pass")

/** 순위 키 (작을수록 좋음): 목표수익 미달 → 비교지수 열위 → 허용 낙폭 초과 구간 → (보수 성향) 낙폭 맞춤안 우선 → Sharpe 높음 → 낙폭 작음. 무결성 검사는 목업에서 모두 통과. */
export function rankKey(sc: ReportScenario, run: Run, cks: Check[]): number[] {
  const st = Object.fromEntries(cks.map((c) => [c.rule, c.status]))
  const mdd = Math.abs(run.m.mdd)
  const bucket = mdd <= sc.max_dd + 1e-9 ? 0 : Math.ceil((mdd - sc.max_dd) / 0.05)
  const cautious = sc.loss_reaction === "sell" || sc.experience === "none"
  return [0, st.R2 !== "pass" ? 1 : 0, st.R3 !== "pass" ? 1 : 0, bucket, cautious && run.def.kind === "matched" ? 0 : 1, -run.m.sharpe, mdd]
}
export const cmpKey = (a: number[], b: number[]) => { for (let i = 0; i < a.length; i++) if (a[i] !== b[i]) return a[i] - b[i]; return 0 }

export interface Backtest {
  sim: Sim; short: boolean; runs: Run[]; bench: Run; qqq: Run; checks: Record<string, Check[]>; status: Record<string, string>
  ranking: string[]; chosen: Run; baseline: Run; verdict: { status: "recommended" | "recommended_warn" | "insufficient"; head_ko: string; label_ko: string; cautions_ko: string[] }
  reason_ko: string; match_target: number
}

/** 시나리오 → 백테스트 전체. */
export function backtest(sc: ReportScenario): Backtest {
  const sim = simulate(sc)
  const short = isShort(sim)
  const defs = candidates(sc, sim)
  const runs = defs.map((d) => runPortfolio(sc, sim, d))
  const bench = benchmarkRun(sc, sim, "SPY"), qqq = benchmarkRun(sc, sim, "QQQ")
  const target = matchTarget(sc)
  const baseDef = defs.find((d) => d.id === sc.baseline)!
  const baseRun = runs.find((r) => r.def.id === sc.baseline)!
  if (Math.abs(baseRun.m.mdd) > target) { const md = matchDrawdown(sc, sim, baseDef, target); if (md) runs.push(runPortfolio(sc, sim, md)) }
  const checks = Object.fromEntries(runs.map((r) => [r.def.id, evaluate(sc, r, bench, short)]))
  const status = Object.fromEntries(runs.map((r) => [r.def.id, statusOf(checks[r.def.id])]))
  const keys = Object.fromEntries(runs.map((r) => [r.def.id, rankKey(sc, r, checks[r.def.id])]))
  const ranking = [...runs].sort((a, b) => cmpKey(keys[a.def.id], keys[b.def.id])).map((r) => r.def.id)
  const chosen = runs.find((r) => r.def.id === ranking[0])!
  const st = Object.fromEntries(checks[chosen.def.id].map((c) => [c.rule, c.status]))
  const mdd = Math.abs(chosen.m.mdd)
  const cautions = [mdd > sc.max_dd + 1e-9 ? `허용 낙폭 초과 (${pct1(mdd - sc.max_dd)}p)` : null, st.R2 === "warn" ? "목표수익 미달" : null, st.R3 === "warn" ? "비교지수 하회" : null].filter(Boolean) as string[]
  const invested = sum(Object.values(chosen.def.weights))
  const vs: Backtest["verdict"]["status"] = invested < 0.5 ? "insufficient" : cautions.length ? "recommended_warn" : "recommended"
  const head = vs === "insufficient" ? "구성 불충분" : vs === "recommended_warn" ? `추천(주의: ${cautions.join(" · ")})` : "추천"
  // 판단 이유 (validate.py 의 문장 틀)
  const parts = [`후보 ${runs.length}개 중 1위.`]
  parts.push(st.R2 === "pass" ? `목표수익(연 ${pct1(sc.target_return)}) 충족` : st.R2 === "warn" ? `목표수익(연 ${pct1(sc.target_return)}) 미달` : "목표수익은 창이 짧아 참고만")
  parts.push(`SPY 대비 초과 CAGR ${spct1(chosen.m.cagr - bench.m.cagr)}p`)
  parts.push(`최대낙폭 ${pct1(mdd)} vs 허용 ${pct1(sc.max_dd)}${mdd <= sc.max_dd + 1e-9 ? ` (여유 ${pct1(sc.max_dd - mdd)}p)` : ` (${pct1(mdd - sc.max_dd)}p 초과)`}`)
  const top = chosen.m.sharpe >= Math.max(...runs.map((r) => r.m.sharpe)) - 1e-12
  parts.push(top && chosen.m.sharpe > 0 ? `Sharpe ${chosen.m.sharpe.toFixed(2)}로 가장 높음` : top ? `Sharpe ${chosen.m.sharpe.toFixed(2)} (음수, 가장 덜 나쁨)` : `Sharpe ${chosen.m.sharpe.toFixed(2)}`)
  if (chosen.def.kind === "matched") parts.push(`${baseDef.label_ko}의 주식 비중을 ${Math.round(invested * 100)}%로 줄여 과거 최대낙폭을 목표 ${pct1(target)} 안에 맞춘 구성`)
  parts.push(`CAGR ${pct1(chosen.m.cagr)}, 최종 평가금액 ${Math.round(chosen.m.final_usd).toLocaleString("en-US")} USD.`)
  return { sim, short, runs, bench, qqq, checks, status, ranking, chosen, baseline: baseRun, verdict: { status: vs, head_ko: head, label_ko: `${head}: ${chosen.def.label_ko}`, cautions_ko: cautions }, reason_ko: parts.join(" · "), match_target: target }
}

export const yearsBetween = (a: string, b: string) => (new Date(`${b}T00:00:00Z`).getTime() - new Date(`${a}T00:00:00Z`).getTime()) / (365.25 * 86400000)
export { mean }
