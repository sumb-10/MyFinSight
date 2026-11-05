// 목업 리포트 문서. 서버 리포트(v2·v1)와 같은 모양으로 만들고, 아직 서버가 주지 않는 값은 proposed(제안 계약)에 따로 담는다.
// 모든 숫자는 backtest.ts 의 계산 결과에서 가져온다 — 문장 속 숫자, 표, 차트, 요약 카드가 같은 값을 쓴다.
import type { Block, CheckpointDetail, CompanyItem, EvidenceRecord, Kpi, ReportDoc, ReportSummary, Section, SummaryKpi, TimelineItem } from "../../api/types"
import type { ProposedAllocationBasis, ProposedExecution, ProposedReport } from "../../api/proposed"
import { PROPOSED_CONTRACT_VERSION } from "../../api/proposed"
import { DEFAULT_VOL_PREF } from "../../lib/tendency"
import { ko } from "../../lib/format"
import type { ReportScenario } from "../scenarios"
import { MOCK_AS_OF, MOCK_FX_NOW } from "../scenarios"
import { backtest, BL_TITLES, COMMISSION_BPS, MIN_ANNUALIZE_DAYS, NAMES_KO, RULES_KO, templateWeights, toleranceNote, toUsd, type Backtest, type Run } from "./backtest"
import { stockOf } from "./stocks"
import { capWeights, normalize, rng, round, seedOf, sum } from "./util"

export type MockReportDoc = ReportDoc & { proposed: ProposedReport }

const pct1 = (x: number) => `${(x * 100).toFixed(1)}%`
const spct1 = (x: number) => `${x > 0 ? "+" : x < 0 ? "-" : ""}${(Math.abs(x) * 100).toFixed(1)}%`
const won = (x: number) => `${Math.round(x).toLocaleString("en-US")}원`
const usd = (x: number) => `${round(x).toLocaleString("en-US", { minimumFractionDigits: 2, maximumFractionDigits: 2 })} USD`
const kindKo = (k: string) => ({ template: "규칙", black_litterman: "뉴스 뷰(BL)", matched: "낙폭 맞춤", benchmark: "비교지수" }[k] ?? k)
const statusKo = (s: string) => ({ pass: "통과", warn: "주의", fail: "미통과" }[s] ?? "-")
const PREF_TABLE: Record<string, string> = { low: "low", medium: "medium", high: "high" }
/** 선정 기준(템플릿) → 서버 지표 이름과 설명 (목업). */
const METRIC: Record<string, [string, string, string]> = { momentum: ["return_12m_1m", "모멘텀", "최근 12개월 주가 수익률에서 가장 최근 1개월을 뺀 값입니다. 높은 순서로 뽑습니다."], high_dividend: ["dividend_yield_ttm", "고배당", "최근 1년 주당배당금을 기준일 종가로 나눈 값입니다. 높은 순서로 뽑습니다."], quality: ["roe", "퀄리티(ROE)", "자기자본이익률입니다. 높은 순서로 뽑습니다."], low_per: ["pe_ttm", "저PER", "주가를 최근 1년 주당순이익으로 나눈 값입니다. 낮은 순서로 뽑습니다."], low_volatility: ["vol_60d", "저변동성", "최근 60거래일 주가 변동성입니다. 낮은 순서로 뽑습니다."] }

/* ───────── 근거 자료 (목업 뉴스·공시: 실제 기사가 아니다) ───────── */
function evidenceFor(sc: ReportScenario): EvidenceRecord[] {
  const out: EvidenceRecord[] = []
  const r = rng(seedOf(`ev:${sc.id}`))
  let n = 1
  for (const t of sc.tickers) {
    const s = stockOf(t)
    const k = sc.news ? 2 : 1
    for (let i = 0; i < k; i++) out.push({ id: `ev${n++}`, kind: "news", title: `[목업] ${s.name_ko} ${["수요 전망 상향 보도", "신제품 출하 일정 보도", "증설 계획 보도", "분기 실적 관련 보도"][Math.floor(r() * 4)]}`, source: "목업 뉴스", url: null, published_at: `2026-10-${String(10 + Math.floor(r() * 18)).padStart(2, "0")}`, tickers: [t], language: "ko" })
  }
  sc.tickers.slice(0, 3).forEach((t, i) => out.push({ id: `dc${i + 1}`, kind: "disclosure", title: `[목업] ${stockOf(t).name_ko} 분기 보고서 제출`, source: "목업 공시", url: null, filed_at: "2026-10-20", available_on: "2026-10-21", tickers: [t], event_type: "periodic", event_label_ko: "정기 보고서" }))
  for (const t of sc.tickers) out.push({ id: `fin:${t}:metric`, kind: "financial", title: `${t} 선정 지표 값`, source: "목업 재무 자료", data_as_of: MOCK_AS_OF, tickers: [t] })
  out.push({ id: "calc:max_drawdown", kind: "calc", title: "선택 전략 최대낙폭 계산", source: "목업 계산", tickers: [] }, { id: "calc:cagr", kind: "calc", title: "선택 전략 연평균 수익률 계산", source: "목업 계산", tickers: [] })
  return out
}

/* ───────── 체크포인트 (리밸런싱 기록) ───────── */
interface Cp { seq: number; i: number; date: string }
function checkpoints(bt: Backtest): Cp[] {
  const d = bt.sim.dates, out: Cp[] = [{ seq: 0, i: 0, date: d[0] }]
  for (let i = 1; i < d.length; i++) if (d[i].slice(0, 7) !== d[i - 1].slice(0, 7)) out.push({ seq: out.length, i, date: d[i] })
  const last = d.length - 1
  if (out[out.length - 1].i !== last) out.push({ seq: out.length, i: last, date: d[last] })
  return out
}
const growth = (bt: Backtest, t: string, a: number, b: number) => bt.sim.price[t][b] / bt.sim.price[t][a]
const mddOf = (xs: number[]) => { let p = xs[0], m = 0; for (const x of xs) { p = Math.max(p, x); m = Math.min(m, x / p - 1) } return m }

export function checkpointDetail(sc: ReportScenario, bt: Backtest, seq: number): CheckpointDetail | null {
  const cps = checkpoints(bt), cp = cps.find((c) => c.seq === seq)
  if (!cp) return null
  const run = bt.chosen, w = run.def.weights, prev = cps[seq - 1]
  const V = run.value[cp.i]
  const before = prev ? Object.fromEntries(Object.entries(w).map(([t, x]) => [t, (x * growth(bt, t, prev.i, cp.i)) / (run.index[cp.i] / run.index[prev.i])])) : null
  const holdings = Object.entries(w).map(([t, x]) => ({ ticker: t, shares_after: (V * x) / bt.sim.price[t][cp.i], price: round(bt.sim.price[t][cp.i]), value_usd: round(V * x), weight_before: before ? before[t] : null, weight_after: x, period_return: prev ? growth(bt, t, prev.i, cp.i) - 1 : 0, period_contribution: prev ? x * (growth(bt, t, prev.i, cp.i) - 1) : 0 }))
  const trades = holdings.map((h) => { const dw = h.weight_after - (h.weight_before ?? 0); return { ticker: h.ticker, side: (dw >= 0 ? "buy" : "sell") as "buy" | "sell", shares: Math.abs((dw * V) / h.price), price: h.price, value_usd: round(Math.abs(dw * V)) } }).filter((t) => t.value_usd > 0.5)
  const turnover = sum(trades.map((t) => t.value_usd)) / V
  const commission = round((sum(trades.map((t) => t.value_usd)) * COMMISSION_BPS) / 10000)
  return {
    portfolio_id: run.def.id, label_ko: run.def.label_ko,
    checkpoint: { seq, date: cp.date, kind: seq === 0 ? "rebalance" : cp.i === bt.sim.dates.length - 1 ? "closing" : "rebalance", n_trading_days_to_date: cp.i, weights: { target: w, before, after: w, cash_before: prev ? run.def.cash : null, cash_after: run.def.cash }, holdings, trades, turnover, commission_usd: commission,
      money: { value_usd: round(V), cumulative_contributions_usd: round(run.invested[cp.i]), net_invested_usd: round(run.invested[cp.i]), profit_usd: round(V - run.invested[cp.i]), benchmark_value_usd: round(bt.bench.value[cp.i]) }, since_last: null, to_date: null, drift: null },
    names: Object.fromEntries(sc.tickers.map((t) => [t, stockOf(t).name_en])), views: [], news_summary: null,
    narrative_ko: prev ? `[목업] ${cp.date} 리밸런싱: 직전 시점 이후 오른 종목의 비중을 줄이고 내린 종목을 채워 목표 비중으로 되돌렸습니다.` : "[목업] 백테스트 시작일에 처음 구성했습니다.", market_model: null,
  }
}

function timelineItems(sc: ReportScenario, bt: Backtest): TimelineItem[] {
  const run = bt.chosen, cps = checkpoints(bt)
  return cps.map((cp, k) => {
    const prev = cps[k - 1]
    const d = checkpointDetail(sc, bt, cp.seq)!
    const tr = run.index[cp.i] / 100 - 1, days = cp.i
    return {
      seq: cp.seq, date: cp.date, kind: d.checkpoint.kind as TimelineItem["kind"], n_trading_days_to_date: days, value_usd: round(run.value[cp.i]), benchmark_value_usd: round(bt.bench.value[cp.i]), net_invested_usd: round(run.invested[cp.i]),
      since_last: prev ? { return: run.index[cp.i] / run.index[prev.i] - 1, benchmark_return: bt.bench.index[cp.i] / bt.bench.index[prev.i] - 1, excess: run.index[cp.i] / run.index[prev.i] - bt.bench.index[cp.i] / bt.bench.index[prev.i], max_drawdown: mddOf(run.index.slice(prev.i, cp.i + 1)) } : null,
      n_trades: d.checkpoint.trades.length, turnover: d.checkpoint.turnover, commission_usd: d.checkpoint.commission_usd,
      to_date: days ? { total_return: tr, cagr: (1 + tr) ** (252 / days) - 1, max_drawdown: mddOf(run.index.slice(0, cp.i + 1)), sharpe: null, excess_cagr: null } : null,
      cash_after: run.def.cash, news: null, views: [], top_delta: [],
    }
  })
}

/* ───────── 표 도우미 ───────── */
const table = (title_ko: string, columns: [string, string, string?][], rows: Record<string, unknown>[], extra: Partial<Block> = {}): Block => ({ type: "table", title_ko, columns: columns.map(([key, label_ko, format]) => ({ key, label_ko, format: (format ?? "text") as never })), rows, ...extra }) as Block
const kv = (title_ko: string, rows: [string, string][], extra: Partial<Block> = {}) => table(title_ko, [["k", "항목"], ["v", "내용"]], rows.map(([k, v]) => ({ k, v })), extra)

function yearly(run: Run, bench: Run, dates: string[]) {
  const years = [...new Set(dates.map((d) => d.slice(0, 4)))]
  const row = (r: Run, name: string) => Object.fromEntries([["name", name], ...years.map((y) => { const idx = dates.map((d, i) => [d, i] as const).filter(([d]) => d.startsWith(y)).map(([, i]) => i); const a = Math.max(0, idx[0] - 1), b = idx[idx.length - 1]; return [y, r.index[b] / r.index[a] - 1] })])
  return table("연도별 수익률", [["name", "포트폴리오"], ...years.map((y) => [y, y, "pct"] as [string, string, string])], [row(run, run.def.label_ko), row(bench, bench.def.label_ko)], { group_ko: "연도별·월별 수익률" })
}
function monthly(run: Run, dates: string[]) {
  const years = [...new Set(dates.map((d) => d.slice(0, 4)))]
  const rows = years.map((y) => { const r: Record<string, unknown> = { year: y }; for (let m = 1; m <= 12; m++) { const ym = `${y}-${String(m).padStart(2, "0")}`; const idx = dates.map((d, i) => [d, i] as const).filter(([d]) => d.startsWith(ym)).map(([, i]) => i); r[`m${m}`] = idx.length ? run.index[idx[idx.length - 1]] / run.index[Math.max(0, idx[0] - 1)] - 1 : null } return r })
  return table("월별 수익률", [["year", "연도"], ...Array.from({ length: 12 }, (_, i) => [`m${i + 1}`, `${i + 1}월`, "pct"] as [string, string, string])], rows, { group_ko: "연도별·월별 수익률" })
}

/* ───────── 문서 ───────── */
export function buildReport(sc: ReportScenario): MockReportDoc {
  const bt = backtest(sc)
  const { sim, short, chosen, bench, qqq } = bt
  const dates = sim.dates, n = dates.length - 1
  const start = dates[0], end = dates[n]
  const ev = evidenceFor(sc)
  const fxNow = MOCK_FX_NOW
  const capUsdNow = toUsd(sc, sc.capital.amount, fxNow), capUsdBt = toUsd(sc, sc.capital.amount, sc.fx_bt)
  const allRuns = [...bt.runs, bench, qqq]
  const label = (id: string) => allRuns.find((r) => r.def.id === id)?.def.label_ko ?? id
  const ckChosen = bt.checks[chosen.def.id]
  const ck = (rule: string) => ckChosen.find((c) => c.rule === rule)!
  const r1 = ck("R1")
  const vs = bt.verdict.status
  const benchName = "SPY 매수보유 (동일 적립)"
  const capKo = sc.capital.currency === "KRW" ? won(sc.capital.amount) : `${sc.capital.amount.toLocaleString("en-US")}USD`
  const monthlyKo = sc.capital.currency === "KRW" ? won(sc.capital.monthly) : `${sc.capital.monthly.toLocaleString("en-US")}USD`

  // KPI (report_blocks.kpis 의 모양: 짧은 창이면 기간 수익률·기간 차이)
  const days = n
  const finalKrw = chosen.m.final_usd * fxNow
  const kpis: Kpi[] = [
    { id: "final_value", label_ko: "최종 평가금액", value: round(chosen.m.final_usd), format: "usd", note_ko: `${sc.capital.currency === "KRW" ? `약 ${Math.round(finalKrw).toLocaleString("en-US")}원 · ` : ""}투입 원금 ${Math.round(chosen.m.net_invested_usd).toLocaleString("en-US")} USD` },
    short ? { id: "cagr", label_ko: `기간 수익률 (${days}거래일)`, value: chosen.m.total_return, format: "pct", note_ko: `연 환산 ${spct1(chosen.m.cagr)} 는 1년 미만 창이라 참고만` } : { id: "cagr", label_ko: "연평균 수익률 (CAGR)", value: chosen.m.cagr, format: "pct", note_ko: "백테스트 기간 기준 연 환산" },
    short ? { id: "excess", label_ko: "비교지수(SPY) 대비 (기간)", value: chosen.m.total_return - bench.m.total_return, format: "pp", note_ko: "같은 기간 누적 수익률 차이" } : { id: "excess", label_ko: "비교지수(SPY) 대비", value: chosen.m.cagr - bench.m.cagr, format: "pp", note_ko: "같은 기간 CAGR 차이" },
    { id: "mdd", label_ko: "최대낙폭 (MDD)", value: chosen.m.mdd, format: "pct", note_ko: toleranceNote(sc) },
    { id: "sharpe", label_ko: "Sharpe 비율", value: chosen.m.sharpe, format: "ratio", note_ko: "무위험수익률 4% 가정" },
  ]
  const benchVals: Record<string, number | null> = { final_value: bench.m.final_usd, cagr: short ? bench.m.total_return : bench.m.cagr, excess: null, mdd: bench.m.mdd, sharpe: bench.m.sharpe }
  const skpis: SummaryKpi[] = kpis.map((k) => ({ ...k, benchmark_value: benchVals[k.id] ?? null, benchmark_label_ko: benchVals[k.id] != null ? benchName : null }))

  // 분석 기준일의 현재 구성: 뉴스 반영이면 「현재 구성 BL 1」, 아니면 선택 전략의 비중을 그대로 (서버 summary.allocation 과 같은 구분)
  const nowBase = templateWeights(sc, sim, sc.baseline, n)
  const blNow = sc.news ? capWeights(normalize(Object.fromEntries(sc.tickers.map((t, i) => [t, Math.max(0.01, nowBase[t] + (i % 2 ? -0.02 : 0.02))]))), sc.max_weight) : null
  const currentW = blNow ?? chosen.def.weights
  const currentLabel = sc.news ? `현재 구성 BL 1: ${BL_TITLES[0]}` : chosen.def.label_ko
  const currentCash = Math.max(0, 1 - sum(Object.values(currentW)))
  const allocation: ReportSummary["allocation"] = {
    basis: sc.news ? "forward" : "backtest", basis_ko: sc.news ? `분석 기준일 ${MOCK_AS_OF} 구성 (${currentLabel})` : `백테스트 선택안 (${chosen.def.label_ko})`,
    items: Object.entries(currentW).sort((a, b) => b[1] - a[1]).map(([t, w]) => ({ ticker: t, name: stockOf(t).name_en, sector: stockOf(t).sector_ko, weight: w, usd: round(capUsdNow * w), krw: Math.round(capUsdNow * w * fxNow) })),
    cash_weight: currentCash, initial_amount_usd: round(capUsdNow), fx_rate: fxNow, fx_direction: `1 USD = ${fxNow.toLocaleString("en-US")}.00 KRW`,
  }

  const rules_ko = ckChosen.filter((c) => c.level !== "info").map((c) => ({ rule: c.rule, name_ko: c.name_ko, level: c.level, status: c.status, message_ko: c.message_ko }))
  const info_notes = ckChosen.filter((c) => c.status === "info" && !c.ok).map((c) => c.message_ko)
  const nCand = bt.runs.length
  const st = Object.values(bt.status)
  const blRuns = bt.runs.filter((r) => r.def.kind === "black_litterman")
  const baseRun = bt.baseline
  const newsEffect: ReportSummary["news_effect"] = sc.news && blRuns.length ? (() => { const bl = blRuns.find((r) => r.def.id === chosen.def.id) ?? blRuns[0]; return { disabled: false, bl_id: bl.def.id, bl_label_ko: bl.def.label_ko, base_id: baseRun.def.id, base_label_ko: baseRun.def.label_ko, bl_cagr: bl.m.cagr, base_cagr: baseRun.m.cagr, diff_cagr: bl.m.cagr - baseRun.m.cagr, bl_excess_cagr: bl.m.cagr - bench.m.cagr, base_excess_cagr: baseRun.m.cagr - bench.m.cagr, bl_mdd: bl.m.mdd, base_mdd: baseRun.m.mdd, hit_365: 0.58, hit_next_rb: 0.62, n_views: 12, n_dates: 9, n_rebalances: checkpoints(bt).length - 1, n_fallback: 3, annualized_reliable: !short } })() : { disabled: true, reason_ko: "뉴스 반영을 끈 분석입니다 (투자조건 설정)" }

  const headline = vs === "insufficient" ? `[목업] 조건을 모두 지키는 구성은 주식 비중이 ${Math.round(sum(Object.values(chosen.def.weights)) * 100)}%에 그쳐 추천하지 않았습니다.` : vs === "recommended_warn" ? `[목업] ${chosen.def.label_ko}이 1위지만 ${bt.verdict.cautions_ko.join(", ")} 주의가 있습니다.` : `[목업] ${chosen.def.label_ko}이 내 조건을 지키면서 비교지수보다 나은 성과를 보였습니다.`
  const nextActions = [`허용 손실 ${pct1(sc.max_dd)}가 실제로 감당할 수 있는 수준인지 다시 확인해 보세요.`, `종목 ${sc.tickers.length}개가 한 산업에 모여 있어, 분산을 더 원하면 테마를 넓혀 볼 수 있습니다.`, "과거 성과는 미래 수익을 보장하지 않으므로 모의투자로 먼저 지켜보는 방법도 있습니다."]
  const period = { start, end, as_of: start, trading_days: n + 1, window_days: n, annualized_reliable: !short }
  const summary: ReportSummary = {
    verdict: { status: vs, label_ko: bt.verdict.label_ko, headline_ko: headline, reason_ko: bt.reason_ko, chosen_portfolio_id: chosen.def.id, chosen_label_ko: chosen.def.label_ko, cautions_ko: bt.verdict.cautions_ko, period_note_ko: null, notices_ko: sc.key === "none" ? ["[목업] 허용 손실 5%를 지키려면 현금 비중이 크게 늘어나 주식 투자 효과가 거의 없습니다."] : [], n_notices: sc.key === "none" ? 1 : 0 },
    validation: { n_pass: st.filter((s) => s === "pass").length, n_warn: st.filter((s) => s === "warn").length, n_fail: st.filter((s) => s === "fail").length, n_candidates: nCand, chosen_status: bt.status[chosen.def.id], failed_rules_ko: [], warned_rules_ko: [], info_notes_ko: info_notes, rules_ko, tolerance_note_ko: toleranceNote(sc), r1_ko: r1.message_ko,
      r1: { mdd: Math.abs(chosen.m.mdd), tolerance: sc.max_dd, benchmark_mdd: Math.abs(bench.m.mdd), excess: Math.max(0, Math.abs(chosen.m.mdd) - sc.max_dd), status: r1.status, match_target: bt.match_target } },
    news_effect: newsEffect, kpis: skpis, allocation, mini_series: { dataset: "index", ids: [chosen.def.id, bench.def.id] }, period: period as ReportSummary["period"], next_actions_ko: nextActions,
  }

  // 데이터셋
  const series: ReportDoc["datasets"]["series"] = Object.fromEntries(allRuns.map((r) => [r.def.id, { label_ko: r.def.label_ko, kind: r.def.kind, index: r.index.map((x) => round(x, 3)), value_usd: r.value.map((x) => round(x)), drawdown: r.drawdown.map((x) => round(x, 4)) }]))
  series.net_invested = { label_ko: "투입 원금(누적)", kind: "invested", value_usd: chosen.invested.map((x) => round(x)) }
  const defaultOn = [chosen.def.id, bench.def.id, ...(chosen.def.id !== baseRun.def.id ? [baseRun.def.id] : [])]

  // 기업
  const companies: CompanyItem[] = sc.tickers.map((t, i) => {
    const s = stockOf(t)
    const ids = ev.filter((e) => e.tickers.includes(t) && e.kind === "news").map((e) => e.id)
    return { ticker: t, name: s.name_en, market: s.market, sector: s.sector_ko, sub_industry: s.sub_industry, summary: s.summary_ko, theme_reason_ko: `[목업] ${s.sub_industry} 기업으로 「${sc.themes[i % sc.themes.length].label}」 테마에 해당합니다.`, theme_confidence: round(0.9 - i * 0.04, 2), weight: chosen.def.weights[t] ?? null, in_selection_now: true, rank_now: i + 1, metric_now: round(0.42 - i * 0.05, 4), in_backtest: true, rank_bt: i + 1, metric_bt: round(0.35 - i * 0.04, 4), fact_id: `fin:${t}:metric`, rationale_ko: [`[목업] ${s.name_ko}는 선정 지표 순위 ${i + 1}위로 뽑혔습니다 [fin:${t}:metric].`, ids[0] ? `[목업] 최근 보도에서 수요 관련 소식이 확인됐습니다 [${ids[0]}].` : "[목업] 최근 관련 보도는 많지 않았습니다."], evidence_ids: ids, n_news: ids.length, n_disclosures: ev.filter((e) => e.kind === "disclosure" && e.tickers.includes(t)).length }
  })

  // 비교표 (같은 기간·같은 적립)
  const cmpRows = allRuns.map((r) => ({ name: r.def.label_ko, kind: kindKo(r.def.kind), cagr: r.m.cagr, vol: r.m.vol, sharpe: r.m.sharpe, mdd: r.m.mdd, excess: r.m.cagr - bench.m.cagr, final: round(r.m.final_usd), irr: r.m.irr, status: r.def.kind === "benchmark" ? "-" : statusKo(bt.status[r.def.id]) }))
  const wcCols = bt.runs.filter((r) => r.def.kind === "template" || r.def.kind === "black_litterman")
  const funnel = [{ label_ko: "투자 가능 종목 (SP500 ∪ NASDAQ100)", count: 518 }, { label_ko: "테마 관련 후보 (GICS·키워드·예시 종목 검색)", count: 18 + sc.tickers.length }, { label_ko: "테마 해당 판정 (분석 모델, 신뢰도 ≥ 0.5)", count: 6 + sc.tickers.length }, { label_ko: "선정 지표 계산 가능", count: 4 + sc.tickers.length }, { label_ko: `최종 선정 (${MOCK_AS_OF}, 섹터 분산 적용)`, count: sc.tickers.length }, { label_ko: `백테스트용 재선정 (${start})`, count: sc.tickers.length }]
  const newsIds = ev.filter((e) => e.kind === "news" || e.kind === "disclosure").map((e) => e.id)
  const evKinds = (ids: string[]) => { const k: Record<string, number> = {}; for (const e of ev.filter((x) => ids.includes(x.id))) k[e.kind] = (k[e.kind] ?? 0) + 1; return k }

  const [metricId, metricKo, metricDesc] = METRIC[sc.template] ?? METRIC.momentum
  const sections: Section[] = [
    { id: "verdict", title_ko: "종합 투자 판단", blocks: [
      { type: "paragraphs", tone: "lead", src: "14b", items: [`[목업] 결론은 「${bt.verdict.head_ko}」입니다. ${start}부터 ${end}까지 ${short ? `기간 수익률은 ${spct1(chosen.m.total_return)}` : `연평균 수익률은 ${pct1(chosen.m.cagr)}`}, 최대낙폭은 ${pct1(Math.abs(chosen.m.mdd))}였습니다 [calc:cagr].`, `[목업] 같은 기간 SPY를 같은 조건으로 샀다면 ${short ? `기간 수익률 ${spct1(bench.m.total_return)}` : `연평균 ${pct1(bench.m.cagr)}`}였습니다.`] },
      { type: "kpis", ids: kpis.map((k) => k.id) },
      { type: "paragraphs", src: "14a", items: [`[목업] 허용 손실 ${pct1(sc.max_dd)}에 비해 선택안의 최대낙폭은 ${pct1(Math.abs(chosen.m.mdd))}였습니다 [calc:max_drawdown].`] },
    ] },
    { id: "market", title_ko: "산업과 시장 분석", blocks: [
      { type: "paragraphs", src: "14b", items: [`[목업] 요청은 ${sc.themes.map((t) => t.label).join("·")} 기업에 투자하려는 것으로 이해했습니다.`, `[목업] 투자금은 ${capKo}, 매월 ${monthlyKo}을 더 넣는 조건입니다.`] },
      table("추출한 테마", [["label", "테마"], ["desc", "설명"], ["codes", "산업 분류"], ["kw", "키워드"]], sc.themes.map((t) => ({ label: t.label, desc: t.desc, codes: "목업", kw: t.label })), { group_ko: "요청 조건 확인" }),
      kv("요청 내용", [["투자금", `${capKo} → 백테스트 시작 ${usd(capUsdBt)} (시작일 환율 1 USD = ${sc.fx_bt.toLocaleString("en-US")}.00 KRW, ${start}) · 현재 구성 ${usd(capUsdNow)} (기준일 환율 1 USD = ${fxNow.toLocaleString("en-US")}.00 KRW, ${MOCK_AS_OF})`], ["월 적립", `${monthlyKo} (매월 ${sc.capital.day}일)`], ["투자기간", `${sc.horizon_years.toFixed(1)}년 (분석 기준일 ${MOCK_AS_OF}, 백테스트 ${sc.backtest_years.toFixed(1)}년)`], ["투자성향", `${sc.risk_tolerance} · 손실 감내 수준 ${pct1(sc.max_dd)} · 손실 시 ${sc.loss_reaction}`], ["목표 수익률", `연 ${pct1(sc.target_return)} · 비교지수 SPY`], ["투자 유니버스", "SP500, NASDAQ100"], ["투자 아이디어", sc.idea]], { group_ko: "요청 조건 확인" }),
      kv("지켜야 하는 조건 (하드 제약)", [["종목당 최대 비중", pct1(sc.max_weight)], ["필수 포함 종목", sc.must_include.join(", ") || "없음"], ["제외 종목", sc.exclude.join(", ") || "없음"]], { group_ko: "요청 조건 확인" }),
      kv("성향 해석 (소프트 조건)", [["변동성 선호", PREF_TABLE[sc.vol_pref]], ["허용 최대낙폭·낙폭 맞춤안 목표", toleranceNote(sc).replace("손실 감내 수준 ", "")], ["해석 메모", `[목업] ${sc.vol_pref_reason_ko ?? "투자성향의 기본 변동성 기준을 그대로 적용했습니다."}`]], { group_ko: "요청 조건 확인" }),
      { type: "paragraphs", src: "14c", items: [`[목업] ${sc.themes[0].label} 관련 보도는 수요 회복 기대를 다뤘습니다 [${newsIds[0]}].`, `[목업] 다만 일부 보도는 공급 증가에 따른 가격 하락 가능성도 언급했습니다 [${newsIds[1] ?? newsIds[0]}].`] },
      { type: "bar", title_ko: `섹터 노출 (기간 평균 비중, ${chosen.def.label_ko})`, items: Object.entries(Object.entries(chosen.def.weights).reduce<Record<string, number>>((a, [t, w]) => { const s = stockOf(t).sector_ko; a[s] = (a[s] ?? 0) + w; return a }, {})).map(([label, value]) => ({ label, value })), format: "pct" },
      { type: "evidence_ref", title_ko: "시장 분석·뷰에 인용된 뉴스·공시 근거", ids: newsIds, count: newsIds.length, kinds: evKinds(newsIds) },
    ] },
    { id: "companies", title_ko: "기업별 투자 근거", blocks: [
      { type: "paragraphs", src: "14b", items: [`[목업] 투자 가능 종목 518개에서 테마 관련 후보를 찾고, 선정 지표 순위와 섹터 분산 규칙으로 ${sc.tickers.length}개를 골랐습니다.`] },
      { type: "funnel", items: funnel },
      { type: "callout", tone: "info", title_ko: "선정 지표", text_ko: `[목업] ${metricKo}(${metricId})는 ${metricDesc}` },
      { type: "companies", title_ko: "선정 종목과 기업별 근거", metric: metricId, metric_ko: metricKo, direction: sc.template === "low_per" || sc.template === "low_volatility" ? "asc" : "desc", as_of_now: MOCK_AS_OF, as_of_bt: start, portfolio_id: chosen.def.id, items: companies },
      table(`테마에는 해당하지만 최종 선정에서 빠진 예 (${MOCK_AS_OF} 기준)`, [["ticker", "티커"], ["name", "회사"], ["reason", "제외 이유"], ["metric", "지표값", "pct"]], [{ ticker: "INTC", name: "Intel Corporation", reason: "rank_beyond_n", metric: -0.12 }, { ticker: "QCOM", name: "Qualcomm", reason: "metric_missing", metric: null }], { group_ko: "제외된 종목과 재선정 차이" }),
      table("분석 기준일 선정 목록과 백테스트 시작일 재선정 목록의 차이", [["k", "구분"], ["v", "종목"]], [{ k: "백테스트용 재선정에서 추가된 종목", v: "없음" }, { k: "빠진 종목", v: "없음" }], { group_ko: "제외된 종목과 재선정 차이", note_ko: "백테스트는 시작일 당시에 알 수 있던 정보만으로 같은 규칙을 다시 적용합니다. 그래서 목록이 달라질 수 있습니다." }),
    ] },
    { id: "construction", title_ko: "포트폴리오 구성과 운용", blocks: [
      { type: "paragraphs", src: "14b", items: [`[목업] 기준 비중은 ${baseRun.def.label_ko}이며, 종목당 상한 ${pct1(sc.max_weight)}을 지켰습니다.`] },
      { type: "weights_compare", title_ko: "비중 규칙별 구성 (백테스트 시작일)", columns: wcCols.map((r) => ({ id: r.def.id, label_ko: r.def.label_ko, kind: r.def.kind, rule_ko: r.def.rule_ko })), rows: sc.tickers.map((t) => ({ ticker: t, name: stockOf(t).name_en, sector: stockOf(t).sector_ko, weights: Object.fromEntries(wcCols.map((r) => [r.def.id, r.def.weights[t] ?? 0])) })), cash: Object.fromEntries(wcCols.map((r) => [r.def.id, r.def.cash])), ex_ante: Object.fromEntries(wcCols.map((r) => [r.def.id, { vol: r.m.vol }])), baseline_id: baseRun.def.id },
      table(`배분 금액 (${chosen.def.label_ko}, 백테스트 초기 투자금 ${Math.round(capUsdBt).toLocaleString("en-US")} USD 기준)`, [["ticker", "티커"], ["name", "회사"], ["sector", "섹터"], ["w", "비중", "pct1"], ["usd", "USD", "usd"], ["krw", "원화", "krw"]], [...Object.entries(chosen.def.weights).map(([t, w]) => ({ ticker: t, name: stockOf(t).name_en, sector: stockOf(t).sector_ko, w, usd: round(capUsdBt * w), krw: Math.round(capUsdBt * w * sc.fx_bt) })), ...(chosen.def.cash > 0 ? [{ ticker: "현금", name: "", sector: "", w: chosen.def.cash, usd: round(capUsdBt * chosen.def.cash), krw: Math.round(capUsdBt * chosen.def.cash * sc.fx_bt) }] : [])]),
      { type: "timeline", title_ko: `리밸런싱 타임라인 (${chosen.def.label_ko})`, portfolio_id: chosen.def.id, walkforward: false, items: timelineItems(sc, bt) },
      ...(sc.news ? [
        { type: "paragraphs", src: "14b", group_ko: "분석 기준일의 현재 구성", group_open: true, items: [`[목업] 분석 기준일 ${MOCK_AS_OF}의 뉴스로 만든 현재 구성입니다. 백테스트 선택안과 비중이 다를 수 있습니다.`] } as Block,
        { type: "donut", title_ko: `${currentLabel} 배분 비중 (현재 구성)`, items: Object.entries(currentW).map(([label, value]) => ({ label, value })), group_ko: "분석 기준일의 현재 구성" } as Block,
      ] : []),
    ] },
    { id: "performance", title_ko: "과거 성과와 해석", blocks: [
      { type: "callout", tone: "info", title_ko: "백테스트 가정", text_ko: `[목업] ${start}~${end}, 거래 수수료 ${COMMISSION_BPS / 100}%, 매월 같은 비중으로 리밸런싱, 적립은 매월 ${sc.capital.day}일. 시세는 화면 확인용 예시 값입니다.` },
      { type: "line", title_ko: "누적 수익률 (시작 = 100)", dataset: "index", series_ids: allRuns.map((r) => r.def.id), default_on: defaultOn, y_format: "index" },
      { type: "paragraphs", src: "14a", items: [`[목업] 선택안은 ${short ? `기간 수익률 ${spct1(chosen.m.total_return)}` : `연평균 ${pct1(chosen.m.cagr)}`}, 연변동성 ${pct1(chosen.m.vol)}였습니다.`] },
      { type: "line", title_ko: "평가금액과 투입 원금 (USD)", dataset: "value_usd", series_ids: [chosen.def.id, bench.def.id, "net_invested"], default_on: [chosen.def.id, bench.def.id, "net_invested"], y_format: "usd" },
      { type: "area", title_ko: "고점 대비 낙폭", dataset: "drawdown", series_ids: defaultOn, default_on: defaultOn, y_format: "pct" },
      table("포트폴리오 비교 (같은 기간·같은 적립)", [["name", "포트폴리오"], ["kind", "종류"], ["cagr", "CAGR", "pct"], ["vol", "변동성", "pct"], ["sharpe", "Sharpe", "ratio"], ["mdd", "최대낙폭", "pct"], ["excess", "비교지수 대비", "pp"], ["final", "최종 평가금액", "usd"], ["irr", "적립 기준 연수익(XIRR)", "pct"], ["status", "검증", "text"]], cmpRows, { note_ko: "비교지수 대비는 SPY 기준 연평균 수익률(CAGR) 차이입니다. [목업] 예시 시세로 계산했습니다." }),
      yearly(chosen, bench, dates), monthly(chosen, dates),
      { type: "bar", title_ko: "종목별 수익 기여 (기간 전체)", items: Object.entries(chosen.def.weights).map(([t, w]) => ({ label: t, value: w * (growth(bt, t, 0, n) - 1) })), format: "pp" },
      { type: "paragraphs", src: "14a", group_ko: "검증 상세", group_open: true, items: [`[목업] 후보 ${nCand}개를 같은 규칙으로 검증했습니다.`] },
      table(`검증 규칙 (${chosen.def.label_ko})`, [["rule", "규칙"], ["name", "이름"], ["level", "수준"], ["msg", "내용"], ["status", "결과"]], ckChosen.map((c) => ({ rule: c.rule, name: c.name_ko, level: { flag: "표시", soft: "권장", info: "참고", hard: "필수" }[c.level], msg: c.message_ko, status: { pass: "통과", warn: "주의", flag: "허용 초과", info: "참고", fail: "미통과" }[c.status] })), { group_ko: "검증 상세" }),
      table("전체 포트폴리오 검증 요약", [["name", "포트폴리오"], ["status", "검증"], ["fails", "미통과 항목"], ["warns", "주의·표시 항목"]], bt.runs.map((r) => ({ name: r.def.label_ko, status: statusKo(bt.status[r.def.id]), fails: "-", warns: bt.checks[r.def.id].filter((c) => c.status === "warn" || c.status === "flag").map((c) => c.name_ko).join(", ") || "-" })), { group_ko: "검증 상세" }),
    ] },
    { id: "assumptions", title_ko: "판단의 전제와 재검토 조건", blocks: [
      { type: "paragraphs", src: "14b", items: ["[목업] 백테스트는 과거 자료로 계산한 결과이며, 실제 투자 결과와 다를 수 있습니다.", "[목업] 리밸런싱은 매월 첫 거래일에 목표 비중으로 되돌린다고 가정했습니다."] },
      { type: "cards", title_ko: "다음에 검토할 수 있는 선택지", items: nextActions.map((t, i) => ({ title_ko: `선택지 ${i + 1}`, text_ko: t, meta: [] })) },
      { type: "cards", title_ko: "확인한 한계", items: ["[목업] 시세는 화면 확인용 예시 값입니다.", "[목업] 거래 비용 외 세금은 반영하지 않았습니다.", "[목업] 휴장일은 반영하지 않았습니다."].map((t, i) => ({ title_ko: `한계 ${i + 1}`, text_ko: t, meta: [] })) },
    ] },
    { id: "references", title_ko: "참고자료와 분석 조건", blocks: [
      table("자료 출처", [["name", "자료"], ["what", "쓰임"], ["url", "링크", "url"]], [{ name: "목업 시세", what: "가격·수익률 (예시 값)", url: null }, { name: "목업 뉴스·공시", what: "투자 의견 근거 (예시)", url: null }], { group_ko: "자료 출처·계산 조건·실행 기록" }),
      kv("계산 조건", [["백테스트 기간", `${start} ~ ${end}`], ["거래 수수료", `${COMMISSION_BPS / 100}%`], ["무위험수익률", "4%"], ["환율(기준일)", `1 USD = ${fxNow.toLocaleString("en-US")}.00 KRW (${MOCK_AS_OF}, 목업)`]], { group_ko: "자료 출처·계산 조건·실행 기록" }),
      table("실행 기록", [["stage", "단계"], ["what", "내용"]], [{ stage: "01_request", what: "[목업] 요청 확정" }, { stage: "14_report", what: "[목업] 리포트 작성" }], { group_ko: "자료 출처·계산 조건·실행 기록" }),
      { type: "glossary", items: [{ term: "CAGR", explain_ko: "[목업 용어 풀이] 매년 같은 비율로 불어났다고 가정한 연평균 수익률입니다." }, { term: "최대낙폭", explain_ko: "[목업 용어 풀이] 가장 높았던 평가금액에서 가장 크게 떨어진 비율입니다." }, { term: "동일비중", explain_ko: "[목업 용어 풀이] 모든 종목에 같은 비율로 투자하는 방식입니다." }] },
      { type: "evidence_ref", title_ko: "근거 색인 (뉴스·공시·재무 지표·계산값)", ids: null, count: ev.length, kinds: evKinds(ev.map((e) => e.id)) },
    ] },
  ]

  const doc: ReportDoc = {
    request_id: sc.request_id, run_id: sc.run_id, stage: "14_report", generated_at: `${sc.created_at}T09:00:00`, source: "mock",
    header: { title_ko: `[목업] ${sc.themes.map((t) => t.label).join(" · ")} · ${ko(sc.template)} 전략`, subtitle_ko: `[목업] ${sc.idea}`, created_at: sc.created_at, selection_as_of: MOCK_AS_OF, backtest_period: { start, end, as_of: start, trading_days: n + 1 }, data_as_of: MOCK_AS_OF, chosen_portfolio_id: chosen.def.id, chosen_label_ko: chosen.def.label_ko, chosen_note_ko: vs === "insufficient" ? "추천 조건을 만족하는 구성이 없습니다." : "후보 중 순위 1위로 추천된 구성입니다.", disclaimer_ko: "목업 데이터 화면입니다. 실제 투자 분석 결과가 아니며, 투자 권유가 아닙니다.", run_id: sc.run_id },
    kpis, nav: sections.map((s) => ({ id: s.id, title_ko: s.title_ko })), sections,
    datasets: { dates, series }, assessment: { intent_fit: 0.8, logic_consistency: 0.85, comments_ko: [] },
    evidence: ev, execution: [{ step: "01_request", summary: "[목업] 요청 확정" }, { step: "14_report", summary: "[목업] 리포트 작성" }], tracking: { eligible: vs !== "insufficient", reason_ko: vs === "insufficient" ? "추천 구성이 없어 모의투자를 시작할 수 없습니다 (목업)." : null },
    sources: [{ id: "mock_prices", name: "목업 시세", what: "예시 값", url: null }], parameters: { backtest: { commission_bps: COMMISSION_BPS, risk_free_rate: 0.04, trading_days: 252, min_annualize_days: MIN_ANNUALIZE_DAYS } }, warnings: [],
    doc_version: 2, summary, evidence_summary: { total: ev.length, cited: newsIds.length + 3, by_kind: evKinds(ev.map((e) => e.id)) },
  }
  return { ...(sc.doc_version === 1 ? toV1(doc, sc, bt) : doc), proposed: proposedFor(sc, bt, doc, currentW, currentLabel) }
}

/** 이전 형식(v1): summary 없음, 체크포인트·근거 블록, 검증 카드. 화면은 lib/reportNormalize 로 바꿔 그린다. */
function toV1(doc: ReportDoc, sc: ReportScenario, bt: Backtest): ReportDoc {
  const st = Object.values(bt.status)
  const sections = doc.sections.map((s) => ({ ...s, blocks: s.blocks.flatMap((b): Block[] => {
    if (b.type === "timeline") return [{ type: "checkpoints", title_ko: b.title_ko, portfolio_id: b.portfolio_id, items: b.items.map((it) => { const d = checkpointDetail(sc, bt, it.seq)!.checkpoint; return { seq: it.seq, date: it.date, kind: it.kind, n_trading_days_to_date: it.n_trading_days_to_date, weights_before: d.weights.before, weights_after: d.weights.after, weights_target: d.weights.target, holdings: d.holdings, since_last: it.since_last as Record<string, unknown> | null, to_date: it.to_date as Record<string, unknown> | null, n_trades: it.n_trades, commission_usd: it.commission_usd ?? 0, value_usd: it.value_usd, benchmark_value_usd: it.benchmark_value_usd, net_invested_usd: it.net_invested_usd, drift: null } }) }]
    if (b.type === "evidence_ref") return [{ type: "evidence", title_ko: b.title_ko, items: doc.evidence.filter((e) => !b.ids || b.ids.includes(e.id)) }]
    if (b.type === "companies" || b.type === "weights_compare") return []
    return [b]
  }) }))
  sections.find((s) => s.id === "verdict")!.blocks.push({ type: "cards", title_ko: "검증 결과", items: [{ title_ko: "검증", text_ko: bt.reason_ko, meta: [{ label_ko: "통과/주의/미통과", value: `${st.filter((x) => x === "pass").length}/${st.filter((x) => x === "warn").length}/${st.filter((x) => x === "fail").length}` }] }] })
  return { ...doc, doc_version: 1, summary: undefined, evidence_summary: undefined, sections, header: { ...doc.header, chosen_note_ko: "후보 중 순위 1위로 추천된 구성입니다." } }
}

/* ───────── 제안 계약 값 (proposed) ───────── */
function proposedFor(sc: ReportScenario, bt: Backtest, doc: ReportDoc, currentW: Record<string, number>, currentLabel: string): ProposedReport {
  const { chosen, bench, short, sim } = bt
  const n = sim.dates.length - 1, fx = MOCK_FX_NOW
  const capUsd = toUsd(sc, sc.capital.amount, fx)
  // 추천 전략을 분석 기준일에 적용: 같은 규칙의 비중을 기준일 자료로 다시 계산 (낙폭 맞춤안은 같은 주식 비율)
  const baseKind = chosen.def.kind === "matched" ? chosen.def.base_id! : chosen.def.kind === "template" ? chosen.def.id : sc.baseline
  const eq = sum(Object.values(chosen.def.weights))
  const nowW = Object.fromEntries(Object.entries(templateWeights(sc, sim, baseKind, n)).map(([t, w]) => [t, w * eq]))
  const exec = execution(sc, "current", currentLabel, currentW, capUsd, fx)  // 예상 매수 주문은 카드 2가 보여 주는 「현재 구성」 비중으로 (카드 금액과 같은 기준)
  const basis = (b: ProposedAllocationBasis["basis"], label_ko: string, as_of: string, id: string, lab: string, w: Record<string, number>, cap: number, rate: number): ProposedAllocationBasis => {
    const cash = Math.max(0, 1 - sum(Object.values(w)))
    return { basis: b, label_ko, as_of, strategy_id: id, strategy_label_ko: lab, items: Object.entries(w).sort((a, c) => c[1] - a[1]).map(([t, x]) => ({ ticker: t, weight: x, usd: round(cap * x), krw: Math.round(cap * x * rate) })), cash_weight: cash, cash_usd: round(cap * cash), cash_krw: Math.round(cap * cash * rate) }
  }
  const capUsdBt = toUsd(sc, sc.capital.amount, sc.fx_bt)
  const baseRun = bt.baseline
  const views = Object.fromEntries(sc.tickers.map((t, i) => {
    const ids = doc.evidence.filter((e) => e.tickers.includes(t) && e.kind !== "financial").map((e) => e.id)
    if (!sc.news) return [t, { status: "disabled", n_views: 0, reason_ko: "이 분석은 뉴스 반영을 꺼서 투자 의견을 만들지 않았습니다.", view_summaries_ko: [], evidence_ids: [] }]
    if (i % 3 === 2) return [t, { status: "insufficient", n_views: 0, reason_ko: `관련 뉴스 ${ids.length}건은 있었지만 방향을 판단할 근거가 부족해 투자 의견을 만들지 않았습니다. 기준 비중을 그대로 썼습니다.`, view_summaries_ko: [], evidence_ids: ids }]
    return [t, { status: "generated", n_views: 1 + (i % 2), reason_ko: "뉴스·공시 근거로 투자 의견을 만들어 비중에 제한적으로 반영했습니다.", view_summaries_ko: [`[목업] ${stockOf(t).name_ko} 수요 개선 기대 (확신 낮음)`], evidence_ids: ids.slice(0, 2) }]
  })) as ProposedReport["company_views"]
  const fxDates = sim.dates
  const fxRates = fxDates.map((_, i) => round(sc.fx_bt + ((fx - sc.fx_bt) * i) / n, 2))
  const cps = checkpoints(bt)
  const pref = sc.vol_pref, defPref = DEFAULT_VOL_PREF[sc.risk_tolerance]
  const ck = bt.checks[chosen.def.id]
  return {
    contract: PROPOSED_CONTRACT_VERSION,
    execution: sc.doc_version === 1 ? null : exec,
    allocations: { current: basis("current", "분석 기준일의 현재 구성", MOCK_AS_OF, sc.news ? "bl_now_01" : chosen.def.id, currentLabel, currentW, capUsd, fx), recommended_now: basis("recommended_now", "추천 전략을 분석 기준일에 적용", MOCK_AS_OF, chosen.def.id, chosen.def.label_ko, nowW, capUsd, fx), backtest_start: basis("backtest_start", "백테스트 시작일의 추천 전략", sim.dates[0], chosen.def.id, chosen.def.label_ko, chosen.def.weights, capUsdBt, sc.fx_bt) },
    chosen_vs_baseline: { as_of: sim.dates[0], chosen_id: chosen.def.id, chosen_label_ko: chosen.def.label_ko, baseline_id: baseRun.def.id, baseline_label_ko: baseRun.def.label_ko, rows: sc.tickers.map((t) => ({ ticker: t, name: stockOf(t).name_en, chosen: chosen.def.weights[t] ?? 0, baseline: baseRun.def.weights[t] ?? 0 })), cash: { chosen: chosen.def.cash, baseline: baseRun.def.cash } },
    company_views: views,
    request_log: { idea: sc.idea, qa: sc.qa.map((q, i) => ({ question_ko: q.question_ko, answer_ko: q.answer_ko, at: `${sc.created_at}T08:${String(10 + i * 3).padStart(2, "0")}:00`, applied_ko: q.applied_ko })), messages: sc.messages.map((m, i) => ({ text: m.text, at: `${sc.created_at}T08:${String(30 + i * 4).padStart(2, "0")}:00`, outcome: m.outcome, changes_ko: m.changes_ko, note_ko: m.note_ko })), final_conditions: [{ label_ko: "투자금", value_ko: sc.capital.currency === "KRW" ? `${sc.capital.amount.toLocaleString("en-US")}원` : `${sc.capital.amount.toLocaleString("en-US")} USD`, changed: false }, { label_ko: "종목당 최대 비중", value_ko: pct1(sc.max_weight), changed: sc.qa.some((q) => q.applied_ko?.includes("종목당")) }, { label_ko: "필수 포함 종목", value_ko: sc.must_include.join(", ") || "없음", changed: sc.messages.some((m) => m.outcome === "applied") }, { label_ko: "손실 감내 수준", value_ko: pct1(sc.max_dd), changed: false }] },
    krw: { fx_dates: fxDates, fx_rates: fxRates, value_krw: chosen.value.map((v, i) => Math.round(v * fxRates[i])), final_value_krw: Math.round(chosen.m.final_usd * fxRates[n]), timeline_krw: cps.map((c) => ({ seq: c.seq, date: c.date, fx_rate: fxRates[c.i], value_krw: Math.round(chosen.value[c.i] * fxRates[c.i]), net_invested_krw: Math.round(chosen.invested[c.i] * fxRates[c.i]), commission_krw: null })) },
    market_topics: [
      { id: "market", kind: "market", title_ko: "전체 시장 상황", summary_ko: `[목업] 같은 기간 SPY는 ${short ? `기간 수익률 ${spct1(bench.m.total_return)}` : `연평균 ${pct1(bench.m.cagr)}`}, 최대낙폭 ${pct1(Math.abs(bench.m.mdd))}였습니다.`, points_ko: ["[목업] 금리 인하 기대가 이어졌습니다.", "[목업] 대형 기술주 비중이 높아졌습니다."], evidence_ids: [] },
      { id: "industry", kind: "industry", title_ko: "관련 산업 동향", summary_ko: `[목업] ${sc.themes[0].label} 업종은 수요 회복 기대와 공급 증가 우려가 함께 나왔습니다.`, points_ko: ["[목업] 설비 투자 계획 발표가 늘었습니다."], evidence_ids: doc.evidence.filter((e) => e.kind === "news").slice(0, 2).map((e) => e.id) },
      { id: "theme", kind: "theme", title_ko: "투자 테마 관련 변화", summary_ko: `[목업] ${sc.themes.map((t) => t.label).join("·")} 테마의 후보 종목 수는 이전 분석과 같습니다.`, points_ko: [], evidence_ids: [] },
      { id: "evidence", kind: "evidence", title_ko: "뉴스·공시 근거", summary_ko: `[목업] 뉴스 ${doc.evidence.filter((e) => e.kind === "news").length}건, 공시 ${doc.evidence.filter((e) => e.kind === "disclosure").length}건을 인용했습니다.`, points_ko: [], evidence_ids: doc.evidence.filter((e) => e.kind === "news" || e.kind === "disclosure").map((e) => e.id) },
    ],
    company_reasons: Object.fromEntries(sc.tickers.map((t, i) => [t, [
      { title_ko: "선정 지표 상위", text_ko: `${(METRIC[sc.template] ?? METRIC.momentum)[1]} 순위 ${i + 1}위로 선정 기준을 통과했습니다.`, metric: { label_ko: (METRIC[sc.template] ?? METRIC.momentum)[1], value: round(0.42 - i * 0.05, 4), format: "pct" as const }, theme_link_ko: null, quote_ko: null, evidence_ids: [`fin:${t}:metric`] },
      { title_ko: "테마 관련성", text_ko: `${stockOf(t).sub_industry} 기업으로 「${sc.themes[i % sc.themes.length].label}」 테마에 해당합니다.`, metric: null, theme_link_ko: sc.themes[i % sc.themes.length].label, quote_ko: `[목업] ${stockOf(t).summary_ko}`, evidence_ids: [] },
    ]])),
    risk_profile: { profile_version: sc.profile_version, tendency_final: sc.tendency_final, tendency_computed: sc.tendency_computed, risk_tolerance: sc.risk_tolerance, default_vol_pref: defPref, applied_vol_pref: pref, pref_reason_ko: pref !== defPref ? sc.vol_pref_reason_ko : null, short_window: short, min_annualize_days: MIN_ANNUALIZE_DAYS, informational_rules: short ? [{ rule: "R2", name_ko: "목표수익", reason_ko: "평가 기간이 짧아 판정 대신 참고로 표시" }, { rule: "R7", name_ko: "변동성 적합", reason_ko: "평가 기간이 짧아 판정 대신 참고로 표시" }] : pref === "high" ? [{ rule: "R7", name_ko: "변동성 적합", reason_ko: "높은 변동성 기준은 상한이 없어 판정하지 않음" }] : [] },
    structured: {
      reasons: structuredReasons(sc, bt),
      checks: ck.map((c) => ({ rule: c.rule, name_ko: c.name_ko, level: c.level, status: c.status, value: c.value, threshold: c.threshold, benchmark_value: c.rule === "R1" ? Math.abs(bench.m.mdd) : c.rule === "R7" ? bench.m.vol : null, benchmark_label_ko: c.rule === "R1" || c.rule === "R7" ? "SPY 매수보유 (동일 적립)" : null, basis: (c.basis ?? null) as never, multiplier: c.multiplier ?? null, vol_pref: c.rule === "R7" ? pref : null, observed_above: c.rule === "R7" && c.threshold !== null && c.value !== null ? c.value > c.threshold : null })),
      tolerance: { input: sc.max_dd, match_target: bt.match_target !== sc.max_dd ? bt.match_target : null, factors_ko: [sc.loss_reaction === "sell" ? "손실 시 매도 성향 ×0.8" : null, sc.experience === "none" ? "투자 경험 없음 ×0.9" : null].filter(Boolean) as string[] },
      annualized: { strategy_total_return: chosen.m.total_return, strategy_cagr: chosen.m.cagr, benchmark_total_return: bench.m.total_return, benchmark_cagr: bench.m.cagr, days: n, reliable: !short },
      requested_amount: { amount: sc.capital.amount, currency: sc.capital.currency, monthly: sc.capital.monthly },
      final_value: { usd: round(chosen.m.final_usd), krw: Math.round(chosen.m.final_usd * fx), fx_rate: fx, fx_date: MOCK_AS_OF },
      kpi_meta: { final_value: { name_ko: "최종 평가금액", period: "point" }, cagr: short ? { name_ko: "전체 기간 수익률", period: "total", days: n } : { name_ko: "연평균 수익률(CAGR)", period: "annual", days: n }, excess: short ? { name_ko: "SPY 대비 전체 기간 수익률 차이", period: "total", days: n } : { name_ko: "SPY 대비 연평균 수익률(CAGR) 차이", period: "annual", days: n }, mdd: { name_ko: "최대낙폭(MDD)", period: "total", days: n }, sharpe: { name_ko: "Sharpe 비율", period: "annual", days: n } },
      benchmark: { ticker: "SPY", kind: "etf", label_ko: "SPY 매수보유 (동일 적립)", description_ko: "미국 S&P 500 지수를 따라가는 ETF" },
      timeline_meta: { strategy_id: chosen.def.id, strategy_label_ko: chosen.def.kind === "matched" ? "낙폭 맞춤안" : chosen.def.label_ko, equity_ratio: chosen.def.kind === "matched" ? eq : null, cash_ratio: chosen.def.kind === "matched" ? 1 - eq : null, base_label_ko: chosen.def.kind === "matched" ? bt.baseline.def.label_ko : null },
      compare_rows: [...bt.runs, bt.bench, bt.qqq].map((r) => ({ name: r.def.label_ko, id: r.def.id, role: r.def.id === chosen.def.id ? "chosen" : r.def.kind === "benchmark" ? "benchmark" : r.def.id === baseRun.def.id ? "baseline" : "candidate" })),
      exclusion_reasons: { rank_beyond_n: "선정 지표 순위가 선정 개수 밖", metric_missing: "선정 지표를 계산할 자료 없음", weight_capacity: "비중 한도 안에 담을 수 없음" },
    },
    explanations: explanations(),
  }
}

/** 추천 전략을 기준일 가격으로 정수 주문: 수수료까지 감안해 살 수 있는 만큼(내림), 남는 돈은 현금. */
export function execution(sc: ReportScenario, id: string, label: string, w: Record<string, number>, capUsd: number, fx: number): ProposedExecution {
  const fee = COMMISSION_BPS / 10000
  const items = Object.entries(w).sort((a, b) => b[1] - a[1]).map(([t, x]) => {
    const p = stockOf(t).price_usd, target = capUsd * x
    const shares = Math.floor(target / (p * (1 + fee)))
    const cost = round(shares * p), f = round(cost * fee)
    return { ticker: t, name: stockOf(t).name_en, price_usd: p, target_weight: x, target_usd: round(target), target_krw: Math.round(target * fx), shares, cost_usd: cost, fee_usd: f, cost_krw: Math.round(cost * fx) }
  })
  const invested = round(sum(items.map((x) => x.cost_usd))), fees = round(sum(items.map((x) => x.fee_usd)))
  const left = round(capUsd - invested - fees), cashTarget = round(capUsd * Math.max(0, 1 - sum(Object.values(w))))
  return { as_of: MOCK_AS_OF, strategy_id: id, strategy_label_ko: label, share_basis: "integer", commission_bps: COMMISSION_BPS, fx: { rate: fx, date: MOCK_AS_OF, source_ko: "목업 환율" }, capital: { amount: sc.capital.amount, currency: sc.capital.currency, usd: round(capUsd) }, items, totals: { invested_usd: invested, fee_usd: fees, cash_left_usd: left, cash_left_krw: Math.round(left * fx), cash_target_usd: cashTarget, cash_target_krw: Math.round(cashTarget * fx) }, note_ko: "정수 주식 기준입니다. 주가·환율은 목업 예시 값이며, 실제 주문 시 가격이 달라집니다." }
}

function structuredReasons(sc: ReportScenario, bt: Backtest): ProposedReport["structured"] extends infer S ? S extends { reasons: infer R } ? R : never : never {
  const { chosen, bench } = bt
  const st = Object.fromEntries(bt.checks[chosen.def.id].map((c) => [c.rule, c.status]))
  const mdd = Math.abs(chosen.m.mdd)
  return [
    { code: "rank_first", title_ko: "비교한 투자 구성안 중 1위", text_ko: `${bt.runs.length}개 투자 구성안을 정해진 순서대로 비교했을 때 가장 앞선 구성안입니다.`, tone: "neutral", values: { n: bt.runs.length } },
    st.R2 === "info" ? { code: "target_info", title_ko: "목표 수익률은 참고만", text_ko: "과거 성과 계산 기간이 짧아 목표 수익률 달성 여부는 참고로만 봤습니다.", tone: "neutral", values: { target: sc.target_return } }
      : { code: st.R2 === "pass" ? "target_met" : "target_missed", title_ko: st.R2 === "pass" ? "목표 수익률 충족" : "목표 수익률 미달", text_ko: `과거 연평균 수익률(CAGR) ${pct1(chosen.m.cagr)}, 목표 연 ${pct1(sc.target_return)}.`, tone: st.R2 === "pass" ? "good" : "warn", values: { cagr: chosen.m.cagr, target: sc.target_return } },
    { code: "vs_benchmark", title_ko: chosen.m.cagr > bench.m.cagr ? "SPY보다 높은 연평균 수익률" : "SPY보다 낮은 연평균 수익률", text_ko: `연평균 수익률(CAGR) 차이 ${spct1(chosen.m.cagr - bench.m.cagr)}p.`, tone: chosen.m.cagr > bench.m.cagr ? "good" : "warn", values: { diff: chosen.m.cagr - bench.m.cagr } },
    { code: mdd <= sc.max_dd ? "drawdown_within" : "drawdown_over", title_ko: mdd <= sc.max_dd ? "허용 손실 범위 안" : "허용 손실 범위 초과", text_ko: `과거 최대 하락폭 ${pct1(mdd)}, 허용 손실 ${pct1(sc.max_dd)}.`, tone: mdd <= sc.max_dd ? "good" : "warn", values: { mdd, tolerance: sc.max_dd } },
    { code: "sharpe", title_ko: "위험 대비 수익성", text_ko: `Sharpe 비율 ${chosen.m.sharpe.toFixed(2)}.`, tone: "neutral", values: { sharpe: chosen.m.sharpe } },
  ]
}

export function explanations(): NonNullable<ProposedReport["explanations"]> {
  return {
    strategies: Object.fromEntries(Object.entries(NAMES_KO).map(([id, label]) => [id, { short_ko: `[목업 설명] ${label}: ${RULES_KO[id]}`, help_ko: `[목업 설명] ${RULES_KO[id]}. 백테스트 시작일에 정한 비중을 목표로 리밸런싱합니다.` }])),
    ranking: [
      { order: 1, key: "integrity", label_ko: "무결성 검사", desc_ko: "자료 길이·상한 위반 같은 내부 점검을 통과하지 못한 구성은 맨 뒤로 보냅니다." },
      { order: 2, key: "target_return", label_ko: "목표 수익률", desc_ko: "목표 수익률을 충족한 구성을 앞에 둡니다 (짧은 기간에는 모두 같은 등급)." },
      { order: 3, key: "benchmark", label_ko: "비교지수 대비", desc_ko: "비교지수보다 연평균 수익률이 높은 구성을 앞에 둡니다." },
      { order: 4, key: "drawdown_bucket", label_ko: "허용 손실 초과 정도", desc_ko: "허용 손실을 넘은 폭을 5%p 단위 구간으로 나눠 덜 넘은 구성을 앞에 둡니다." },
      { order: 5, key: "cautious_match", label_ko: "보수 성향의 낙폭 맞춤안 우선", desc_ko: "손실 시 매도하거나 투자 경험이 없으면 같은 조건에서 낙폭 맞춤안을 먼저 둡니다." },
      { order: 6, key: "sharpe", label_ko: "위험 대비 수익성(Sharpe)", desc_ko: "Sharpe 비율이 높은 구성을 앞에 둡니다." },
      { order: 7, key: "drawdown_tie", label_ko: "낙폭 동률 처리", desc_ko: "위 기준이 모두 같으면 최대낙폭이 작은 구성을 앞에 둡니다." },
    ],
    etfs: { SPY: { label_ko: "SPY", description_ko: "미국 S&P 500 지수를 따라가는 ETF" }, QQQ: { label_ko: "QQQ", description_ko: "미국 나스닥 100 지수를 따라가는 ETF" } },
    short_window_rules: [{ rule: "R2", name_ko: "목표수익", desc_ko: `평가 기간이 ${MIN_ANNUALIZE_DAYS}거래일보다 짧으면 판정 대신 참고로 표시` }, { rule: "R7", name_ko: "변동성 적합", desc_ko: `평가 기간이 ${MIN_ANNUALIZE_DAYS}거래일보다 짧으면 판정 대신 참고로 표시` }],
    default_vol_by_risk: DEFAULT_VOL_PREF,
    glossary_extra: [{ term: "투자 구성안", explain_ko: "[목업 용어] 같은 종목에 서로 다른 비중 규칙을 적용한 포트폴리오 후보입니다." }, { term: "목표 배분액", explain_ko: "[목업 용어] 비중대로 나눈 이론상의 금액입니다. 실제 매수 금액은 주가 단위 때문에 조금 다릅니다." }],
  }
}

export const isMockReportDoc = (d: ReportDoc): d is MockReportDoc => "proposed" in d
