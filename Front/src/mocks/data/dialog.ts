// 목업 요청(대화) 상태. 리포트 시나리오마다 확정된 요청이 있고, 질문 중인 요청 하나(여러 질문 한 번에 답하기 확인용)를 더 둔다.
import { stockLabel } from "../../api/proposed"
import type { ConditionRow, DialogState, ProfileFields, Question, RequestRow, UserRequest } from "../../api/types"
import type { ReportScenario } from "../scenarios"
import { MOCK_AS_OF, MOCK_FX_NOW, REPORTS } from "../scenarios"
import { PROFILE_VERSIONS } from "./profile"
import { STOCKS, stockOf } from "./stocks"
import { ko } from "../../lib/format"

const won = (x: number, c: "KRW" | "USD") => (c === "KRW" ? `${x.toLocaleString("en-US")}원` : `${x.toLocaleString("en-US")} USD`)
const pct = (x: number) => `${Math.round(x * 1000) / 10}%`
const pct0 = (x: number) => `${Math.round(x * 100)}%`
const listKo = (xs: string[] | undefined) => (xs?.length ? xs.map(ko).join(", ") : "없음")
const holdingsKo = (n: { target: number; min: number; max: number }) => `목표 ${n.target}개 (최소 ${n.min} ~ 최대 ${n.max})`
const rebalanceKo = (r: { count: number; unit: string }) => (r.count === 0 ? "없음 (매수 후 보유)" : `${r.count}×${ko(r.unit)}마다`)
const capKo = (v: number | undefined) => (v ? `${(v / 1e9).toLocaleString("en-US", { maximumFractionDigits: 1 })}B USD 이상` : "제한 없음")
const advKo = (v: number | undefined) => (v ? `일 ${Math.round(v / 1e6).toLocaleString("en-US")}M USD 이상` : "제한 없음")
const nameOf = (t: string) => STOCKS.find((s) => s.ticker === t) ?? null
/** 종목 목록 표기: 「회사명 (티커)」 (목업 종목에 없으면 티커만). */
export const tickersKo = (ts: string[]) => (ts.length ? ts.map((t) => stockLabel(nameOf(t), t)).join(", ") : "없음")

export function effectiveRequest(sc: Pick<ReportScenario, "request_id" | "created_at" | "idea" | "capital" | "horizon_years" | "backtest_years" | "risk_tolerance" | "max_dd" | "loss_reaction" | "target_return" | "max_weight" | "must_include" | "exclude" | "template" | "baseline" | "news" | "experience">): UserRequest {
  const p = PROFILE_VERSIONS[3]
  return {
    request_id: sc.request_id, created_at: `${sc.created_at}T08:00:00`, profile: { ...p.profile, investment_experience: sc.experience },
    capital: { initial_amount: sc.capital.amount, currency: sc.capital.currency, monthly_contribution: sc.capital.monthly, contribution_day: sc.capital.day },
    horizon: { start_date: MOCK_AS_OF, target_years: sc.horizon_years, purpose: "wealth_growth", backtest_years: sc.backtest_years },
    risk: { risk_tolerance: sc.risk_tolerance, max_drawdown_tolerance: sc.max_dd, loss_reaction: sc.loss_reaction, target_annual_return: sc.target_return, benchmark: "SPY" },
    constraints: { ...p.constraints, max_weight_per_stock: sc.max_weight, must_include_tickers: sc.must_include, exclude_tickers: sc.exclude },
    strategy_preference: { template: sc.template, baseline_weighting: sc.baseline, use_news_tilt: sc.news },
    natural_language: { idea: sc.idea, language: "ko" },
    derived: { as_of: MOCK_AS_OF, fx_rate: MOCK_FX_NOW, fx_date: MOCK_AS_OF, fx_source: "목업", initial_amount_usd: sc.capital.currency === "KRW" ? sc.capital.amount / MOCK_FX_NOW : sc.capital.amount, monthly_contribution_usd: sc.capital.currency === "KRW" ? sc.capital.monthly / MOCK_FX_NOW : sc.capital.monthly, rebalance_rule: { description_ko: "매월 1회", enabled: true, count: 1, unit: "1m" }, price_data_start: "2020-01-02", price_data_end: MOCK_AS_OF, backtest_start: "", backtest_end: MOCK_AS_OF, markets: ["US"], warnings: [] },
  }
}

/** 조건 행. touched = 답변·조건 바꾸기·말로 보태기로 바꾼 항목 (기본 투자조건과 값이 다를 때만 「달라짐」).
 *  항목은 실제 서버(conditions.py GROUPS)와 같은 범위 — 조건 바꾸기로 바꿀 수 있는 값은 모두 행이 있다. 분석 기준일(horizon.start_date)은 서버처럼 행이 없다. */
export function conditionRows(req: UserRequest, touched: string[] = [], base: ProfileFields = PROFILE_VERSIONS[3]): ConditionRow[] {
  const p = base, c = req.constraints, pc = p.constraints
  const byUser = (field: string) => touched.some((t) => t === field || t.startsWith(`${field}.`))  // 예: num_holdings.target 을 바꿔도 「종목 수」 행
  const row = (field: string, group_ko: string, label_ko: string, value_ko: string, profile_value_ko: string): ConditionRow => { const changed = value_ko !== profile_value_ko; return { field, group_ko, label_ko, value_ko, profile_value_ko, changed, source: !changed ? "profile" : byUser(field) ? "answer" : "idea", supported: true } }
  return [
    row("capital.initial_amount", "투자금", "투자금", won(req.capital.initial_amount, req.capital.currency), won(p.capital.initial_amount, p.capital.currency)),
    row("capital.currency", "투자금", "투자금 통화", ko(req.capital.currency), ko(p.capital.currency)),
    row("capital.monthly_contribution", "투자금", "매월 추가 투자금", won(req.capital.monthly_contribution, req.capital.currency), won(p.capital.monthly_contribution, p.capital.currency)),
    row("capital.contribution_day", "투자금", "적립일", `매월 ${req.capital.contribution_day}일`, `매월 ${p.capital.contribution_day}일`),
    row("horizon.target_years", "기간", "투자기간", `${req.horizon.target_years}년`, `${p.horizon.target_years}년`),
    row("horizon.backtest_years", "기간", "백테스트 기간", `${req.horizon.backtest_years ?? 3}년`, `${p.horizon.backtest_years ?? 3}년`),
    row("risk.risk_tolerance", "위험", "위험 성향", ko(req.risk.risk_tolerance), ko(p.risk.risk_tolerance)),
    row("risk.max_drawdown_tolerance", "위험", "손실 감내 수준", pct(req.risk.max_drawdown_tolerance), pct(p.risk.max_drawdown_tolerance)),
    row("risk.target_annual_return", "위험", "목표 수익률", pct(req.risk.target_annual_return), pct(p.risk.target_annual_return)),
    row("risk.benchmark", "위험", "비교지수", req.risk.benchmark, p.risk.benchmark),
    row("constraints.universe", "종목", "투자 대상 지수", listKo(c.universe), listKo(pc.universe)),
    row("constraints.num_holdings", "종목", "종목 수", holdingsKo(c.num_holdings), holdingsKo(pc.num_holdings)),
    row("constraints.max_weight_per_stock", "종목", "종목당 최대 비중", pct(c.max_weight_per_stock), pct(pc.max_weight_per_stock)),
    row("constraints.max_weight_per_sector", "종목", "섹터당 최대 비중", pct0(c.max_weight_per_sector), pct0(pc.max_weight_per_sector)),
    row("constraints.min_cash_ratio", "종목", "최소 현금 비율", pct0(c.min_cash_ratio ?? 0), pct0(pc.min_cash_ratio ?? 0)),
    row("constraints.must_include_tickers", "종목", "꼭 넣을 종목", tickersKo(c.must_include_tickers), tickersKo(pc.must_include_tickers)),
    row("constraints.exclude_tickers", "종목", "뺄 종목", tickersKo(c.exclude_tickers), tickersKo(pc.exclude_tickers)),
    row("constraints.exclude_sectors", "종목", "제외 섹터", listKo(c.exclude_sectors), listKo(pc.exclude_sectors)),
    row("constraints.exclude_themes", "종목", "제외 테마", listKo(c.exclude_themes), listKo(pc.exclude_themes)),
    row("constraints.min_market_cap_usd", "종목", "최소 시가총액", capKo(c.min_market_cap_usd), capKo(pc.min_market_cap_usd)),
    row("constraints.min_avg_daily_volume_usd", "종목", "최소 일평균 거래대금", advKo(c.min_avg_daily_volume_usd), advKo(pc.min_avg_daily_volume_usd)),
    row("constraints.rebalance", "종목", "리밸런싱", rebalanceKo(c.rebalance), rebalanceKo(pc.rebalance)),
    row("strategy_preference.template", "전략", "선정 기준", ko(req.strategy_preference.template), ko(p.strategy_preference.template)),
    row("strategy_preference.baseline_weighting", "전략", "기준 비중 방식", ko(req.strategy_preference.baseline_weighting), ko(p.strategy_preference.baseline_weighting)),
    row("strategy_preference.use_news_tilt", "전략", "뉴스 반영", req.strategy_preference.use_news_tilt ? "예" : "아니오", p.strategy_preference.use_news_tilt ? "예" : "아니오"),
  ]
}

export const FIELD_LABEL: Record<string, string> = { "constraints.max_weight_per_stock": "종목당 최대 비중", "constraints.must_include_tickers": "꼭 넣을 종목", "constraints.exclude_tickers": "뺄 종목", "risk.max_drawdown_tolerance": "손실 감내 수준", constraints: "종목 조건" }
const q = (seq: number, field: string, question_ko: string, options: [unknown, string][], answer?: string, why_ko?: string): Question => ({ seq, field, field_label_ko: FIELD_LABEL[field] ?? null, kind: "preference", question_ko, why_ko, options: options.map(([value, label_ko]) => ({ value, label_ko })), allow_free_text: true, priority: seq, asked_at: "2026-10-31T08:05:00", ...(answer ? { answer, answered_at: "2026-10-31T08:10:00" } : {}) })

/** 기본 투자조건(현재 버전)으로 만든 이번 요청 조건. 질문에 답하거나 말로 보태면 여기서 값이 바뀐다. */
export function requestFromProfile(p: ProfileFields, request_id: string, idea: string, created_at = "2026-11-04"): UserRequest {
  const c = p.constraints
  const r = effectiveRequest({ request_id, created_at, idea, capital: { amount: p.capital.initial_amount, currency: p.capital.currency, monthly: p.capital.monthly_contribution, day: p.capital.contribution_day }, horizon_years: p.horizon.target_years, backtest_years: p.horizon.backtest_years, risk_tolerance: p.risk.risk_tolerance, max_dd: p.risk.max_drawdown_tolerance, loss_reaction: p.risk.loss_reaction, target_return: p.risk.target_annual_return, max_weight: c.max_weight_per_stock, must_include: c.must_include_tickers, exclude: c.exclude_tickers, template: p.strategy_preference.template, baseline: p.strategy_preference.baseline_weighting, news: p.strategy_preference.use_news_tilt, experience: p.profile.investment_experience } as never)
  // effectiveRequest 는 시나리오용이라 일부 값(종목 범위·비교지수 등)을 고정 버전에서 가져온다 → 지금 기본 투자조건 값으로 맞춘다
  return { ...r, constraints: JSON.parse(JSON.stringify(c)), risk: { ...r.risk, benchmark: p.risk.benchmark }, horizon: { ...r.horizon, backtest_years: p.horizon.backtest_years ?? 3 } }
}

/** 답(보기 값) 하나를 조건에 넣는다. 종목 목록은 기존 목록에 더한다 (「없어요」= 그대로). 자유 입력은 해석하지 않는다(목업). */
export function applyField(req: UserRequest, field: string, value: unknown): UserRequest {
  const r = JSON.parse(JSON.stringify(req)) as UserRequest
  if (field === "constraints.max_weight_per_stock" && typeof value === "number") r.constraints.max_weight_per_stock = value
  else if (field === "risk.max_drawdown_tolerance" && typeof value === "number") r.risk.max_drawdown_tolerance = value
  else if (field === "constraints.must_include_tickers" && Array.isArray(value)) { r.constraints.must_include_tickers = [...new Set([...r.constraints.must_include_tickers, ...value as string[]])]; r.constraints.exclude_tickers = r.constraints.exclude_tickers.filter((t) => !(value as string[]).includes(t)) }
  else if (field === "constraints.num_holdings" && value && typeof value === "object") r.constraints.num_holdings = { ...(value as UserRequest["constraints"]["num_holdings"]) }
  else if (field === "constraints.exclude_tickers" && Array.isArray(value)) { r.constraints.exclude_tickers = [...new Set([...r.constraints.exclude_tickers, ...value as string[]])]; r.constraints.must_include_tickers = r.constraints.must_include_tickers.filter((t) => !(value as string[]).includes(t)) }
  return r
}

/** 조건 바꾸기(이번 요청의 덮어쓰기)를 조건에 넣는다. 키는 요청의 경로(예: capital.initial_amount)이고, null 이면 기본 투자조건 값으로 되돌린다.
 *  실제 서버는 덮어쓰기를 반영해 분석 모델을 한 번 더 돌린다 (dialog.update_overrides) — 목업은 값만 그대로 넣는다. */
export function applyOverrides(req: UserRequest, profileReq: UserRequest, overrides: Record<string, unknown>): UserRequest {
  const r = JSON.parse(JSON.stringify(req)) as UserRequest
  for (const [k, v] of Object.entries(overrides)) {
    if (k.startsWith("_") || k === "natural_language.idea") continue
    const path = k.split("."), last = path.pop()!
    const parent = path.reduce<Record<string, unknown> | undefined>((o, key) => o?.[key] as Record<string, unknown> | undefined, r as unknown as Record<string, unknown>)
    const from = path.reduce<Record<string, unknown> | undefined>((o, key) => o?.[key] as Record<string, unknown> | undefined, profileReq as unknown as Record<string, unknown>)
    if (parent) parent[last] = JSON.parse(JSON.stringify(v === null ? from?.[last] ?? null : v))
  }
  return r
}

/** 「말로 보태기」 목업 해석: 미리 정한 규칙(회사명·티커 + 넣다/빼다)만 알아듣는다. 실제 분석 모델의 해석이 아니다. */
export function interpretMessage(text: string, req: UserRequest): { outcome: "applied" | "not_applied" | "needs_confirmation"; req: UserRequest; fields: string[]; note_ko: string } {
  const t = text.toLowerCase()
  const hits = STOCKS.filter((s) => s.market && (new RegExp(`(^|[^a-z0-9])${s.ticker.toLowerCase()}([^a-z0-9]|$)`).test(t) || t.includes(s.name_ko.split(" ")[0].toLowerCase()) || t.includes(s.name_en.split(" ")[0].toLowerCase()))).map((s) => s.ticker)
  const drop = /빼|제외|말고|없이/.test(text), add = /넣|포함|담아|추가|꼭/.test(text)
  if (hits.length && drop) return { outcome: "applied", req: applyField(req, "constraints.exclude_tickers", hits), fields: ["constraints.exclude_tickers", "constraints.must_include_tickers"], note_ko: "말씀하신 종목을 뺄 종목에 넣었습니다." }
  if (hits.length && add) return { outcome: "applied", req: applyField(req, "constraints.must_include_tickers", hits), fields: ["constraints.must_include_tickers", "constraints.exclude_tickers"], note_ko: "말씀하신 종목을 꼭 넣을 종목에 더했습니다." }
  if (hits.length) return { outcome: "needs_confirmation", req, fields: [], note_ko: `${tickersKo(hits)}을(를) 꼭 넣을지, 뺄지 확인이 필요합니다. 「꼭 넣어 주세요」나 「빼 주세요」처럼 다시 적어 주세요.` }
  if (drop) return { outcome: "needs_confirmation", req, fields: [], note_ko: "무엇을 뺄지 정확히 알 수 없습니다. 종목이면 회사 이름이나 티커를 적어 주시고, 분야라면 「조건 바꾸기」에서 제외할 섹터·테마로 정해 주세요." }
  return { outcome: "not_applied", req, fields: [], note_ko: "이번 요청에서 바꿀 조건을 찾지 못했습니다. 기존 조건이 그대로 유지됩니다." }
}

export function confirmedDialog(sc: ReportScenario): DialogState {
  const req = effectiveRequest(sc)
  const rows = conditionRows(req)
  return {
    request_id: sc.request_id, mode: sc.base_report_id ? "revision" : "new", base_report_id: sc.base_report_id ?? null, status: "confirmed", state: "confirmed", turn: sc.qa.length, max_questions: 5, idea: sc.idea,
    question: null, questions: sc.qa.map((x, i) => q(i + 1, "constraints", x.question_ko, [[x.answer_ko, x.answer_ko]], x.answer_ko)), hard_errors: [],
    confirmation: { effective_request: req, rows, all_supported: true }, unresolved: [],
    summary: { interpretation_summary_ko: `[목업] ${sc.themes.map((t) => t.label).join("·")} 기업에 투자하려는 요청으로 이해했습니다.`, themes: sc.themes.map((t, i) => ({ id: `t${i + 1}`, label_ko: t.label, description_ko: t.desc })), derived: req.derived, changed_fields: rows.filter((r) => r.changed).map((r) => r.field) },
    revision: null, run_id: sc.run_id, warnings: [], conditions: rows, overrides: {},
  }
}

/** 목업 실행 전 점검: 이 아이디어로 고를 수 있는 후보 수 (실제 서버는 종목 사전·DB 로 센다). */
export const MOCK_CANDIDATES = 15
/** 실행 전 점검 질문 (목업): 종목 수 최소가 후보보다 많을 때. 확인 화면에서 조건을 바꿨더니 다시 「질문 중」이 되는 경우를 재현한다. */
export function feasibilityQuestion(seq: number, min: number, candidates = MOCK_CANDIDATES): Question {
  const lo = Math.max(2, candidates - 5)
  return {
    ...q(seq, "constraints.num_holdings", `이 아이디어로 고를 수 있는 후보가 ${candidates}개라 최소 ${min}개를 채울 수 없습니다. 종목 수를 어떻게 할까요?`,
      [[{ target: 10, min: 8, max: 12 }, "8~12개로 줄이기 (목표 10개)"], [{ target: candidates, min: lo, max: candidates }, `후보에 맞춰 ${lo}~${candidates}개로`]],
      undefined, `[목업] 바꾼 종목 수(최소 ${min}개)가 고를 수 있는 후보(${candidates}개)보다 많아, 분석을 시작하기 전에 확인합니다.`),
    field_label_ko: "종목 수", kind: "feasibility", asked_at: new Date().toISOString(),
  }
}

/** 질문 중인 요청: 같은 화면에서 여러 질문에 답하는 흐름(4단계)과 말로 보태기 결과 확인용. 아이디어는 정상 추천 시나리오와 같고, 조건은 기본 투자조건(base)에서 시작한다. */
export function askingDialog(base: ProfileFields = PROFILE_VERSIONS[3], request_id = "mock_req_asking", idea = REPORTS[0].idea): DialogState {
  const sc = REPORTS[0]
  const req = requestFromProfile(base, request_id, idea)
  const rows = conditionRows(req, [], base)
  const mu = stockLabel(stockOf("MU"), "MU")
  const questions = [
    q(1, "constraints.max_weight_per_stock", "한 종목에 최대 몇 %까지 담을까요?", [[0.2, "20%"], [0.25, "25%"], [0.3, "30%"]], undefined, "반도체 기업끼리는 함께 오르내리는 경우가 많아, 한 종목에 너무 쏠리지 않게 상한을 정합니다."),
    q(2, "constraints.must_include_tickers", `꼭 넣고 싶은 종목이 있나요? 예: ${mu}`, [[["MU"], mu], [[], "없어요"]], undefined, "아이디어에 메모리 기업이 있어, 특정 기업을 꼭 넣을지 확인합니다."),
    q(3, "risk.max_drawdown_tolerance", "잠깐 손실이 나도 견딜 수 있는 수준은 어느 정도인가요?", [[0.2, "20%까지"], [0.3, "30%까지"], [0.35, "35%까지"]], undefined, "반도체 업종은 하락 폭이 큰 편이라, 손실 감내 수준을 다시 확인합니다."),
  ]
  return {
    request_id, mode: "new", base_report_id: null, status: "draft", state: "asking", turn: 0, max_questions: 5, idea,
    question: questions[0], questions, hard_errors: [], confirmation: null, unresolved: [],
    summary: { interpretation_summary_ko: `[목업] ${sc.themes.map((t) => t.label).join("·")} 기업에 투자하려는 요청으로 이해했습니다.`, themes: sc.themes.map((t, i) => ({ id: `t${i + 1}`, label_ko: t.label, description_ko: t.desc })), derived: req.derived, changed_fields: [] },
    revision: null, run_id: null, warnings: [], conditions: rows, overrides: {},
  }
}

/** 질문에 모두 답해 확인만 남은 요청 (조건 확인 화면 확인용). */
export function readyDialog(): DialogState {
  const a = askingDialog(PROFILE_VERSIONS[3], "mock_req_ready")
  const picks = [1, 0, 1]  // 25% · 마이크론 넣기 · 30%까지(기본 투자조건과 같음)
  let req = requestFromProfile(PROFILE_VERSIONS[3], "mock_req_ready", a.idea)
  const questions = a.questions.map((x, i) => { const o = x.options[picks[i]]; req = applyField(req, x.field, o.value); return { ...x, answer: o.label_ko, answered_at: "2026-11-04T08:20:00" } })
  const rows = conditionRows(req, questions.map((x) => x.field))
  return { ...a, state: "ready", turn: questions.length, question: null, questions, confirmation: { effective_request: req, rows, all_supported: true }, conditions: rows }
}

export function requestRows(extra: DialogState[]): RequestRow[] {
  return [...extra, ...REPORTS.map(confirmedDialog)].map((d) => ({ request_id: d.request_id, created_at: d.confirmation?.effective_request.created_at ?? "2026-11-04T08:00:00", mode: d.mode, idea: d.idea, status: d.status, state: d.state, run_id: d.run_id ?? null, turn: d.turn }))
}
