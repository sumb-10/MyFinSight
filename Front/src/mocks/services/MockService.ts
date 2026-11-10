// 목업 서비스: 화면이 쓰는 AnalysisService 계약 + 제안 계약(ProposedApi)을 목업 자료로 구현한다. 네트워크를 쓰지 않는다 (api/client 를 import 하지 않음).
// 정해진 자료(리포트·백테스트·모의투자 시세)는 시나리오에서 결정적으로 만들고, 사용자가 바꾼 것(이름·조건·새 요청)은 store(sessionStorage)에 둔다.
import { ApiError } from "../../api/client"
import type { AnalysisService } from "../../api/service"
import type { ProposedBatchAnswer, ProposedChatAnswer, ProposedProfileChat, ProposedMessageResult, ProposedOptionsExt, ProposedPaperName, ProposedPaperNameIn, ProposedQuestionBatch, ProposedReportName, ProposedReportRowExt, ProposedRunWarning, ProposedStrategyRecommendation } from "../../api/proposed"
import type { CheckpointDetail, ComparisonDoc, DialogState, EvidencePage, EvidenceQuery, Health, Options, PaperDetail, PaperIn, PaperPreview, PaperSummary, ProfileFields, ProfileVersion, ProfileView, ReportDoc, ReportRow, RequestRow, RunPartial, RunRow, RunStatus, SeriesResponse, Tendency } from "../../api/types"
import { MOCK_AS_OF, PAPERS, REPORTS, RUN_STATES, reportScenario, type PaperScenario, type ReportScenario } from "../scenarios"
import { backtest, type Backtest } from "../data/backtest"
import { MOCK_CANDIDATES, MOCK_PROGRESS_STEPS, applyField, applyOverrides, askingDialog, conditionRows, confirmedDialog, feasibilityQuestion, interpretMessage, mockProgress, readyDialog, requestFromProfile, requestRows } from "../data/dialog"
import { recommendation } from "../data/strategy"
import { answerChat, chatView, currentQuestion, newChat, rewindChat } from "../data/profileChat"
import { buildPaper, paperPreview, type MockPaper } from "../data/paper"
import { PROFILE_VERSIONS, profileView, ZERO_CAPITAL_VERSION } from "../data/profile"
import { buildReport, checkpointDetail, type MockReportDoc } from "../data/report"
import { CANCEL_MS, RUN_WARNINGS, STEPS, buckets, cancelInfo, liveStatus, runPartial, runRows, runStatus } from "../data/runs"
import { STOCKS } from "../data/stocks"
import { localIso } from "../data/util"
import { clearState, initialState, loadState, saveState, type MockState } from "./store"
import type { SeenSeed } from "../../lib/seen"

const notFound = (what: string) => new ApiError("NOT_FOUND", `[목업] ${what}을(를) 찾을 수 없습니다`, 404)
const clone = <T>(x: T): T => JSON.parse(JSON.stringify(x)) as T
const INTERPRET_X = 50  // 새 요청이 '해석 중'인 시간 = 평소 지연 × 이 값 (기본 6초, 2초마다 읽는 화면에서 단계가 나아가는 것이 보이게)

export interface MockOptions { latencyMs?: number; persist?: boolean; clock?: () => number }  // clock: 진행 시퀀스·취소 시간을 테스트에서 바꿔 끼운다

/** 목업도 실제 서버처럼: 같은 요청의 가장 최근 실행이 취소된 것이면 「멈춘 곳부터 이어서 실행」 할 수 있다 (그때만 투자 아이디어). */
const withResumable = (requests: Record<string, { idea?: string }>) => (rows: RunRow[]): RunRow[] => {
  const latest = new Map<string, RunRow>()
  for (const r of rows) { const l = latest.get(r.request_id); if (!l || r.queued_at > l.queued_at) latest.set(r.request_id, r) }
  return rows.map((r) => { const resumable = r.status === "cancelled" && latest.get(r.request_id) === r; return { ...r, resumable, idea: resumable ? requests[r.request_id]?.idea ?? null : null } })
}

export class MockService implements AnalysisService {
  readonly mode = "mock" as const
  private s: MockState
  private bt = new Map<string, Backtest>()
  private docs = new Map<string, MockReportDoc>()
  private papers = new Map<string, MockPaper>()
  private readonly latency: number
  private readonly persist: boolean
  private readonly now: () => number

  constructor(opts: MockOptions = {}) {
    this.latency = opts.latencyMs ?? 120
    this.persist = opts.persist ?? true
    this.now = opts.clock ?? Date.now
    this.s = this.persist ? loadState() : initialState()
  }

  /* ───────── 내부 ───────── */
  private async wait<T>(f: () => T, ms = this.latency): Promise<T> {
    if (ms > 0) await new Promise((r) => setTimeout(r, ms))
    return clone(f())
  }
  private commit() { this.papers.clear(); if (this.persist) saveState(this.s) }
  private sc(id: string): ReportScenario { const sc = reportScenario(id); if (!sc) throw notFound("리포트"); return sc }
  private backtestOf(sc: ReportScenario) { let b = this.bt.get(sc.id); if (!b) { b = backtest(sc); this.bt.set(sc.id, b) } return b }
  private docOf(sc: ReportScenario) { let d = this.docs.get(sc.id); if (!d) { d = buildReport(sc); this.docs.set(sc.id, d) } return d }
  private versions(): ProfileVersion[] {
    if (this.s.profileVariant === "none") return [...this.s.savedVersions]  // 처음 사용자: 저장하기 전에는 투자조건이 없다
    return [...PROFILE_VERSIONS, ...(this.s.profileVariant === "zero" ? [ZERO_CAPITAL_VERSION] : []), ...this.s.savedVersions]
  }
  private allPapers(): PaperScenario[] { return [...PAPERS, ...this.s.createdPapers] }
  reportDisplayName(id: string) { const sc = this.sc(id); return this.s.reportNames[sc.id] ?? sc.auto_name_ko }  // 리포트 ID·실행 ID 어느 쪽으로 불러도 같은 이름
  private paperName(ps: PaperScenario) { const n = this.s.paperNames[ps.id] ?? ps.name; return n.mode === "custom" ? n.name_ko : this.reportDisplayName(ps.report_id) }
  private paperOf(id: string): MockPaper {
    let p = this.papers.get(id)
    if (p) return p
    const ps = this.allPapers().find((x) => x.id === id)
    if (!ps) throw notFound("모의투자")
    const sc = this.sc(ps.report_id)
    p = buildPaper(ps, sc, this.backtestOf(sc), this.paperName(ps), this.s.paperStatus[id] ?? ps.status)
    this.papers.set(id, p)
    return p
  }

  /* ───────── 개발용 (목업 패널) ───────── */
  state() { return clone(this.s) }
  setProfileVariant(v: MockState["profileVariant"]) { this.s.profileVariant = v; this.commit() }
  reset() { clearState(); this.s = initialState(); this.bt.clear(); this.docs.clear(); this.papers.clear() }
  /** 시연용 확인 기록 시작값: 가장 최근에 완료된 리포트 하나와 첫 모의투자의 마지막 리밸런싱을 '확인 안 함'으로 둔다 (사이드바 배지·알림이 보이게). */
  seenSeed(): SeenSeed {
    const live = this.allPapers().some((p) => p.id === "mock_paper_a1") ? this.paperOf("mock_paper_a1").detail.summary.n_rebalances : 0
    return { unseenReports: ["mock_rep_revised"], papers: live > 0 ? { mock_paper_a1: live - 1 } : {} }
  }

  /* ───────── 메타·프로필 ───────── */
  health(): Promise<Health> { return this.wait(() => ({ ok: true, api_version: "mock", llm_mode: "api" as const, db: { ok: true, latest_trading_day: MOCK_AS_OF, data_start: "2020-01-02" }, worker: { alive: true, running_run_id: null }, queue_length: 0 })) }
  options(): Promise<Options & ProposedOptionsExt> {
    return this.wait(() => ({ proposed_rules: { allow_zero_initial_amount: true }, universes: ["SP500", "NASDAQ100", "KOSPI200"], templates: ["low_per", "quality", "momentum", "low_volatility", "high_dividend"], weightings: ["equal_weight", "market_cap", "inverse_volatility", "min_variance"], risk_tolerance: ["conservative", "moderate", "aggressive"], rebalance_units: ["2w", "1m", "1q", "6m", "1y"], age_band: ["20s", "30s", "40s", "50s", "60s+"], investment_experience: ["none", "beginner", "intermediate", "advanced"], financial_knowledge: ["basic", "intermediate", "expert"], purpose: ["wealth_growth", "income", "capital_preservation", "retirement"], loss_reaction: ["sell", "hold", "buy_more"], benchmarks: ["SPY", "QQQ"], max_questions: 5, default_backtest_years: 3, markets: ["US", "KR"], labels_ko: {}, data_range: ["2020-01-02", MOCK_AS_OF] as [string, string], latest_trading_day: MOCK_AS_OF }))
  }
  getProfile(): Promise<ProfileView | null> { return this.wait(() => { const vs = this.versions(); return vs.length ? profileView(vs) : null }) }
  saveProfile(fields: ProfileFields): Promise<ProfileView> {
    const vs = this.versions()
    const v: ProfileVersion = { ...clone(fields), version: (vs.at(-1)?.version ?? 0) + 1, created_at: localIso() }  // 서버처럼 시간대 오프셋 포함 (UTC 를 떼면 9시간 이른 「저장 시각」)
    this.s.savedVersions.push(v); this.commit()
    return this.wait(() => profileView(this.versions()))
  }
  getProfileVersion(version: number): Promise<ProfileVersion> { return this.wait(() => { const v = this.versions().find((x) => x.version === version); if (!v) throw notFound("투자조건 버전"); return v }) }
  recommendStrategy(tendency: Tendency, purpose?: string | null): Promise<ProposedStrategyRecommendation> { return this.wait(() => recommendation(tendency, purpose)) }  // 실제 서버와 같은 고정 규칙 표 (data/strategy.ts)

  /* 대화형 초기 투자조건: 정해진 질문 순서와 보기로만 묻는다 (data/profileChat.ts). 저장은 saveProfile 그대로.
     봇이 답을 준비하는 「…」가 보이도록 대화 응답만 평소 지연의 5배 (기본 0.6초, 테스트 latencyMs 0 이면 0). */
  private chatWait<T>(f: () => T) { return this.wait(f, this.latency * 5) }
  startProfileChat(): Promise<ProposedProfileChat> {
    return this.chatWait(() => { const id = this.nextId("mock_chat"); this.s.profileChats[id] = newChat(id); this.commit(); return chatView(this.s.profileChats[id]) })
  }
  answerProfileChat(chatId: string, answer: ProposedChatAnswer): Promise<ProposedProfileChat> {
    return this.chatWait(() => {
      const c = this.chatOf(chatId)
      if (currentQuestion(c)?.id !== answer.question_id) throw new ApiError("CONFLICT", "[목업] 지금 답할 질문이 아닙니다", 409)
      this.s.profileChats[chatId] = answerChat(c, answer); this.commit()
      return chatView(this.s.profileChats[chatId])
    })
  }
  rewindProfileChat(chatId: string, questionId: string): Promise<ProposedProfileChat> {
    return this.chatWait(() => { this.s.profileChats[chatId] = rewindChat(this.chatOf(chatId), questionId); this.commit(); return chatView(this.s.profileChats[chatId]) })
  }
  private chatOf(id: string) { const c = this.s.profileChats[id]; if (!c) throw notFound("대화"); return c }
  searchStocks(q: string) {
    const k = q.trim().toLowerCase().replace(/\s+/g, "")
    const flat = (x: string) => x.toLowerCase().replace(/\s+/g, "")
    const hit = (s: (typeof STOCKS)[number]) => (s.ticker.toLowerCase().startsWith(k) ? 0 : flat(s.name_ko).startsWith(k) || flat(s.name_en).startsWith(k) ? 1 : [s.ticker, s.name_ko, s.name_en].some((x) => flat(x).includes(k)) ? 2 : 9)
    return this.wait(() => (k ? STOCKS.filter((s) => s.sector_ko !== "ETF" && hit(s) < 9).sort((a, b) => hit(a) - hit(b)).slice(0, 8) : []).map(this.stockView))
  }
  getStocks(tickers: string[]) { return this.wait(() => tickers.map((t) => STOCKS.find((s) => s.ticker === t.toUpperCase())).filter((s) => !!s).map(this.stockView)) }
  private stockView = (s: (typeof STOCKS)[number]) => ({ ticker: s.ticker, name_ko: s.name_ko, name_en: s.name_en, market: s.market, sector_ko: s.sector_ko })


  /* ───────── 요청·질문 ───────── */
  private base(): ProfileVersion { return this.versions().at(-1) ?? PROFILE_VERSIONS[0] }  // 처음 사용자는 화면이 투자조건 설정으로 보내지만, 고정 시나리오 요청은 기본 이력으로 연다
  /** 실제 서버의 '해석 중' 응답처럼: 번호·아이디어·바꾼 조건과 진행 단계만 있고 질문·조건 표·해석 결과는 아직 없다. done = 끝난 단계 수 */
  private interpretingView(d: DialogState, done = 0): DialogState {
    return { ...d, state: "interpreting", turn: 0, question: null, questions: [], conditions: [], confirmation: null, unresolved: [], summary: { themes: [], changed_fields: [] }, precheck: null, progress: mockProgress(d, done) }
  }
  private dialog(id: string): DialogState {
    const t = this.s.interpreting[id]
    if (t) {  // 새 요청: 정한 시각까지는 해석 중(지난 시간만큼 단계가 나아감), 지나면 만들어 둔 질문 중 대화 (상태가 sessionStorage 에 있어 새로고침해도 이어진다)
      if (this.now() < t.until && this.s.requests[id]) {
        const from = t.from ?? t.until - this.latency * INTERPRET_X, frac = (this.now() - from) / Math.max(1, t.until - from)
        return this.interpretingView(this.s.requests[id], Math.min(MOCK_PROGRESS_STEPS - 1, Math.max(0, Math.floor(frac * MOCK_PROGRESS_STEPS))))
      }
      delete this.s.interpreting[id]; this.commit()
    }
    if (this.s.requests[id]) return this.s.requests[id]
    if (id === "mock_req_asking") return askingDialog(this.base())
    if (id === "mock_req_ready") return readyDialog()
    if (id === "mock_req_interpreting") return this.interpretingView(askingDialog(this.base(), id), 3)  // 패널: 계속 해석 중인 요청 (후보 분류 1/2 묶음에 머묾, 화면 확인용)
    if (id === "mock_req_failed") return { ...this.interpretingView(askingDialog(this.base(), id), 1), state: "failed", error_ko: "목업: 분석 모델 응답 형식이 맞지 않습니다." }  // 패널: 해석 실패 (아이디어 해석에서 멈춤)
    const sc = REPORTS.find((r) => r.request_id === id)
    if (!sc) throw notFound("요청")
    return confirmedDialog(sc)
  }
  private put(d: DialogState) { this.s.requests[d.request_id] = d; this.commit(); return d }
  private nextId(p: string) { const n = this.s.seq++; return `${p}_${String(n).padStart(3, "0")}` }
  /** 요청의 지금 조건. 처음 부르면 확인 화면 조건(있으면) 또는 기본 투자조건(현재 버전)에서 만든다. */
  private draft(d: DialogState) {
    const base = this.base()
    return (this.s.drafts[d.request_id] ??= { req: d.confirmation?.effective_request ?? requestFromProfile(base, d.request_id, d.idea), touched: [], base: d.confirmation ? PROFILE_VERSIONS[3] : base })
  }
  /** 지금 조건으로 조건 행·확인 화면을 다시 만든다. */
  private withRows(d: DialogState): DialogState {
    const dr = this.draft(d), rows = conditionRows(dr.req, dr.touched, dr.base)
    return { ...d, conditions: rows, confirmation: d.state === "ready" || d.state === "confirmed" ? { effective_request: dr.req, rows, all_supported: true } : d.confirmation }
  }
  createRequest(input: { idea: string; overrides?: Record<string, unknown>; mode?: "new" | "rerun" | "revision"; base_report_id?: string | null }): Promise<DialogState> {
    const id = this.nextId("mock_req"), base = this.base()
    const d = { ...askingDialog(base, id, input.idea), mode: input.mode ?? "new", base_report_id: input.base_report_id ?? null, overrides: input.overrides ?? {} }
    const fresh = requestFromProfile(base, id, input.idea), o = input.overrides ?? {}
    this.s.drafts[id] = { req: applyOverrides(fresh, fresh, o), touched: Object.keys(o), base }
    // 실제 서버처럼 번호를 먼저 돌려주고 해석은 뒤에서 한다: 평소 지연의 50배(기본 6초) 동안 '해석 중'으로 6단계를 차례로 보이다가 질문으로
    // (2초마다 다시 읽는 화면에서 단계가 나아가는 것이 보이게. 테스트 latencyMs 0 이면 바로 질문)
    const ms = this.latency * INTERPRET_X
    return this.wait(() => {
      const saved = this.put(this.withRows(d))
      if (ms <= 0) return saved
      this.s.interpreting[id] = { from: this.now(), until: this.now() + ms }; this.commit()
      return this.interpretingView(saved)
    })
  }
  getRequest(id: string) { return this.wait(() => this.dialog(id)) }
  listRequests(): Promise<RequestRow[]> { return this.wait(() => requestRows([...Object.values(this.s.requests), ...(this.s.requests.mock_req_asking ? [] : [askingDialog(this.base())]), ...(this.s.requests.mock_req_ready ? [] : [readyDialog()])])) }
  /** 답 하나 반영: 보기를 골랐으면 그 값을 조건에 넣고, 자유 입력·답하지 않음은 조건을 바꾸지 않는다 (목업은 자유 입력을 해석하지 않음). */
  private advance(d: DialogState, seq: number, answer: string | null, value?: { v: unknown }): DialogState {
    const q = d.questions.find((x) => x.seq === seq)
    const dr = this.draft(d)
    if (q && value) { dr.req = applyField(dr.req, q.field, value.v); if (!dr.touched.includes(q.field)) dr.touched.push(q.field) }
    const questions = d.questions.map((x) => (x.seq === seq ? { ...x, answer, skipped: answer === null, answered_at: new Date().toISOString() } : x))
    const next = questions.find((x) => !x.answered_at) ?? null
    // 점검 질문처럼 바꾼 조건(overrides)을 다시 정하는 답이면 그 값도 고친다 (다시 「조건 바꾸기」를 열 때 맞는 값이 보이게)
    const overrides = q && value && d.overrides && q.field in d.overrides ? { ...d.overrides, [q.field]: value.v } : d.overrides
    return this.withRows({ ...d, overrides, questions, question: next, turn: d.turn + 1, state: next ? "asking" : "ready" })
  }
  private pickOf(id: string, seq: number, input: { option_value?: unknown; free_text?: string }) {
    const o = this.dialog(id).questions.find((x) => x.seq === seq)?.options.find((x) => input.option_value !== undefined && JSON.stringify(x.value) === JSON.stringify(input.option_value))
    return o ? { label: o.label_ko, value: { v: o.value } } : { label: input.free_text ?? "", value: undefined }
  }
  answer(id: string, seq: number, input: { option_value?: unknown; free_text?: string }) {
    const p = this.pickOf(id, seq, input)
    return this.wait(() => this.put(this.advance(this.dialog(id), seq, p.label, p.value)))
  }
  skip(id: string, seq: number) { return this.wait(() => this.put(this.advance(this.dialog(id), seq, null))) }
  /** 조건 바꾸기: 덮어쓰기를 지금 조건에 넣고 조건 행을 다시 만든다 (null = 그 덮어쓰기를 지워 기본 투자조건 값으로). 답으로 바뀐 다른 항목은 그대로 둔다. */
  updateOverrides(id: string, overrides: Record<string, unknown>) {
    const d = this.dialog(id), dr = this.draft(d)
    dr.req = applyOverrides(dr.req, requestFromProfile(dr.base, id, d.idea), overrides)
    const merged = { ...d.overrides }
    for (const [k, v] of Object.entries(overrides)) {
      if (v === null) { delete merged[k]; dr.touched = dr.touched.filter((f) => f !== k) }
      else { merged[k] = v; if (!dr.touched.includes(k)) dr.touched.push(k) }
    }
    // 실행 전 점검 (목업 규칙): 종목 수 최소가 후보보다 많으면 점검 질문을 내고 다시 「질문 중」으로. 실제 서버(dialog.py _turn)가 조건 변경 뒤 새 질문을 고르는 경우를 흉내 낸다.
    const nh = merged["constraints.num_holdings"] as { min?: number } | undefined
    const min = nh?.min ?? (merged["constraints.num_holdings.min"] as number | undefined)
    if (typeof min === "number" && min > MOCK_CANDIDATES && !d.questions.some((x) => !x.answered_at && x.field === "constraints.num_holdings")) {
      const fq = feasibilityQuestion(d.questions.length + 1, min)
      return this.wait(() => this.put(this.withRows({ ...d, overrides: merged, state: "asking", status: "draft", question: fq, questions: [...d.questions, fq] })))
    }
    return this.wait(() => this.put(this.withRows({ ...d, overrides: merged })))
  }
  sendMessage(id: string, text: string) {
    const d = this.dialog(id), dr = this.draft(d)
    const before = conditionRows(dr.req, dr.touched, dr.base)
    const r = interpretMessage(text, dr.req)
    if (r.outcome === "applied") { dr.req = r.req; for (const f of r.fields) if (!dr.touched.includes(f)) dr.touched.push(f) }
    const after = conditionRows(dr.req, dr.touched, dr.base)
    const changes = after.filter((x) => before.find((b) => b.field === x.field)?.value_ko !== x.value_ko).map((x) => ({ field: x.field, label_ko: x.label_ko, before_ko: before.find((b) => b.field === x.field)!.value_ko, after_ko: x.value_ko }))
    const result: ProposedMessageResult = r.outcome === "applied" && !changes.length
      ? { text, at: new Date().toISOString(), outcome: "not_applied", changes, note_ko: "말씀하신 내용은 이미 조건에 들어 있어 바뀐 것이 없습니다. 기존 조건이 그대로 유지됩니다." }
      : { text, at: new Date().toISOString(), outcome: r.outcome, changes, note_ko: r.note_ko }
    ;(this.s.messages[id] ??= []).push(result)
    return this.wait(() => this.put(this.withRows(d)))
  }
  getMessageResults(id: string): Promise<ProposedMessageResult[]> {
    const sc = REPORTS.find((r) => r.request_id === id)
    const fromScenario = (sc?.messages ?? []).map((m) => ({ text: m.text, at: `${sc!.created_at}T08:30:00`, outcome: m.outcome, changes: m.changes_ko.map((c) => ({ field: "constraints", label_ko: c.split(":")[0], before_ko: c.split(": ")[1]?.split(" → ")[0] ?? "", after_ko: c.split(" → ")[1] ?? "" })), note_ko: m.note_ko ?? "" }))
    return this.wait(() => [...fromScenario, ...(this.s.messages[id] ?? [])])
  }
  /** 필수 질문: 종목을 꼭 넣을지 묻는 질문만 선택 (나머지는 결과가 달라지는 조건이라 필수). */
  private static required = (field: string) => field !== "constraints.must_include_tickers"
  getQuestionBatch(id: string): Promise<ProposedQuestionBatch | null> {
    const d = this.dialog(id)
    const open = d.questions.filter((x) => !x.answered_at)
    return this.wait(() => (open.length ? { request_id: id, questions: open.map((x) => ({ seq: x.seq, field: x.field, field_label_ko: x.field_label_ko ?? x.field, question_ko: x.question_ko, why_ko: x.why_ko ?? null, required: MockService.required(x.field), options: x.options.map((o) => ({ value: o.value, label_ko: o.label_ko })), allow_free_text: x.allow_free_text })) } : null))
  }
  answerBatch(id: string, answers: ProposedBatchAnswer[]) {
    let d = this.dialog(id)
    const open = d.questions.filter((x) => !x.answered_at)
    const missing = open.filter((x) => MockService.required(x.field) && !answers.some((a) => a.seq === x.seq && !a.skip && (a.option_value !== undefined || a.free_text?.trim())))
    if (missing.length) return Promise.reject(new ApiError("VALIDATION_ERROR", `[목업] 필수 질문에 답해 주세요: ${missing.map((x) => x.field_label_ko ?? x.field).join(", ")}`, 422))
    for (const a of answers) {
      if (a.skip) { d = this.advance(d, a.seq, null); continue }
      const p = this.pickOf(id, a.seq, a)
      d = this.advance(d, a.seq, p.label, p.value)
    }
    return this.wait(() => this.put(d))
  }
  confirm(id: string) { const d = this.dialog(id); const run_id = this.startLiveRun("success", id); this.put({ ...d, status: "confirmed", state: "confirmed", run_id }); return this.wait(() => ({ run_id, queue_position: 1 })) }
  cancelRequest(id: string) { const d = this.dialog(id); return this.wait(() => this.put({ ...d, status: "cancelled", state: "cancelled" })) }
  rerun(reportId: string) { const sc = this.sc(reportId); return this.settled(this.createRequest({ idea: sc.idea, mode: "rerun", base_report_id: reportId })) }
  createRevision(reportId: string, text: string) { const sc = this.sc(reportId); return this.settled(this.createRequest({ idea: `${sc.idea}\n${text}`, mode: "revision", base_report_id: reportId })) }
  /** 재분석·수정 요청은 실제 서버처럼 해석까지 끝낸 뒤 돌려준다 (번호를 먼저 주는 것은 홈의 새 요청만). 기다림은 전과 같은 지연의 15배 */
  private async settled(p: Promise<DialogState>): Promise<DialogState> {
    const st = await p
    if (!this.s.interpreting[st.request_id]) return st
    await new Promise((r) => setTimeout(r, this.latency * 15))
    delete this.s.interpreting[st.request_id]; this.commit()
    return clone(this.dialog(st.request_id))
  }

  /* ───────── 실행 ───────── */
  /** 이벤트 시퀀스 실행을 만든다: 대기 → 단계 진행(확인할 점이 차례로 생김) → 완료(정상 추천 리포트) 또는 백테스트에서 실패. */
  startLiveRun(ending: "success" | "failed" = "success", request_id = REPORTS[0].request_id): string {
    const id = this.nextId("mock_run_live")
    this.s.live[id] = { started: this.now(), ending, request_id, report_id: REPORTS[0].id }
    this.commit()
    return id
  }
  private runOf(id: string): RunStatus {
    const lv = this.s.live[id]
    if (lv) return liveStatus(id, lv, this.now())
    const r = runStatus(id)
    if (!r) throw notFound("분석")
    const c = this.s.runs[id]
    if (!c) return r
    const iso = localIso
    if (this.now() - c.cancel_at < CANCEL_MS) return { ...r, status: "cancelling", cancel: cancelInfo(r.steps, iso(c.cancel_at), null) } as RunStatus
    const st = r.steps.map((x) => (x.status === "STARTED" || x.status === "QUEUED" ? { ...x, status: "CANCELLED" as const } : x))
    return { ...r, status: "cancelled", finished_at: iso(c.cancel_at + CANCEL_MS), steps: st, buckets: buckets(st), cancel: cancelInfo(r.steps, iso(c.cancel_at), iso(c.cancel_at + CANCEL_MS)) } as RunStatus
  }
  listRuns(): Promise<RunRow[]> {
    return this.wait(() => [...Object.keys(this.s.live).map((id) => this.runOf(id)), ...runRows().map((r) => this.runOf(r.run_id))].map((r) => ({ run_id: r.run_id, request_id: r.request_id, status: r.status, queued_at: r.queued_at, started_at: r.started_at ?? null, finished_at: r.finished_at ?? null, report_id: r.report_id ?? null, error_message: r.error?.message_ko ?? null }))).then(withResumable(this.s.requests))
  }
  getRun(id: string): Promise<RunStatus> { return this.wait(() => this.runOf(id)) }
  /** 목업 즉시 취소: 누른 시각에 진행을 멈추고 CANCEL_MS 동안 「취소 처리 중」, 그 뒤 「취소됨」. 이미 끝난 분석은 취소할 수 없다. */
  cancelRun(id: string): Promise<RunStatus> {
    const r = this.runOf(id)
    if (!["queued", "running"].includes(r.status)) return Promise.reject(new ApiError("RUN_NOT_CANCELLABLE", "[목업] 이미 끝났거나 취소 중인 분석입니다.", 409))
    const t = this.now(), lv = this.s.live[id]
    if (lv) lv.cancel = { at: t, frozen: t }; else this.s.runs[id] = { cancel_at: t }
    this.commit()
    return this.getRun(id)
  }
  /** 다시 실행: 같은 요청으로 새 시퀀스 실행을 만든다 (끝까지 완료). */
  retryRun(id: string): Promise<RunStatus> { const r = this.runOf(id); return this.getRun(this.startLiveRun("success", r.request_id)) }
  getRunPartial(id: string): Promise<RunPartial | null> { return this.wait(() => runPartial(id)) }
  /** 지금까지 끝난 단계의 경고 전체 (같은 단계의 같은 문구는 하나로 묶고 횟수를 센다). 경고가 있는 실행: 「확인할 점」 시나리오·이벤트 시퀀스. */
  getRunWarnings(id: string): Promise<ProposedRunWarning[]> {
    return this.wait(() => {
      const withNotes = id === "mock_run_notices" || !!this.s.live[id]
      if (!withNotes) return []
      const r = this.runOf(id)
      const done = new Set(r.steps.filter((x) => x.status === "SUCCESS" || x.status === "PARTIAL").map((x) => x.step))  // 단계 요약과 같은 기준 (끝난 단계만)
      const label = Object.fromEntries(STEPS.map(([s, l]) => [s, l]))
      return RUN_WARNINGS.filter((w) => done.has(w.step)).reduce<ProposedRunWarning[]>((acc, w) => { const same = acc.find((a) => a.step === w.step && a.message_ko === w.message_ko); if (same) same.count++; else acc.push({ step: w.step, step_label_ko: label[w.step] ?? w.step, message_ko: w.message_ko, count: 1 }); return acc }, [])
    })
  }


  /* ───────── 리포트 ───────── */
  listReports(): Promise<(ReportRow & ProposedReportRowExt)[]> {
    // 실제 서버처럼 최근에 만든 리포트부터 (같은 날이면 시나리오 순서)
    return this.wait(() => [...REPORTS].sort((x, y) => y.created_at.localeCompare(x.created_at)).filter((sc) => !this.s.deletedReports.includes(sc.id)).map((sc) => { const b = this.backtestOf(sc); return { report_id: sc.id, run_id: sc.run_id, request_id: sc.request_id, status: "success" as const, has_report: true, strategy_name: b.chosen.def.label_ko, request_summary: sc.idea, as_of: MOCK_AS_OF, created_at: sc.created_at, idea: sc.idea, mode: sc.base_report_id ? "revision" : "new", proposed_name: this.nameOf(sc.id) } }))
  }
  getReport(id: string): Promise<ReportDoc> { return this.wait(() => { const sc = this.sc(id); if (this.s.deletedReports.includes(sc.id)) throw notFound("리포트"); return this.docOf(sc) }) }
  /** 리포트 삭제: 목업 상태에서만 빠진다 (이 리포트로 만든 모의투자는 그대로 둔다). */
  deleteReport(id: string): Promise<void> {
    const sc = this.sc(id)
    if (!this.s.deletedReports.includes(sc.id)) { this.s.deletedReports.push(sc.id); this.commit() }
    return this.wait(() => null).then(() => undefined)  // wait 은 결과를 JSON 으로 복사하므로 undefined 는 넘기지 않는다
  }
  getReportName(id: string): Promise<ProposedReportName> { return this.wait(() => this.nameOf(id)) }
  private nameOf(id: string): ProposedReportName { const sc = this.sc(id); const custom = this.s.reportNames[sc.id] ?? null; return { report_id: sc.id, auto_ko: sc.auto_name_ko, custom_ko: custom, display_ko: custom ?? sc.auto_name_ko, updated_at: this.s.reportRenamedAt[sc.id] ?? null } }
  renameReport(id: string, name: string | null): Promise<ProposedReportName> {
    const sc = this.sc(id)
    const v = name?.trim() || null
    this.s.reportNames[sc.id] = v === sc.auto_name_ko ? null : v; this.s.reportRenamedAt[sc.id] = new Date().toISOString(); this.commit()
    return this.wait(() => this.nameOf(id))
  }
  getComparison(id: string): Promise<ComparisonDoc> { return this.wait(() => { if (id !== "mock_cmp_revised") throw notFound("비교"); return this.comparison() }) }
  getReportComparison(reportId: string): Promise<ComparisonDoc | null> { return this.wait(() => (reportId === "mock_rep_revised" ? this.comparison() : null)) }
  private comparison(): ComparisonDoc {
    const base = this.sc("mock_rep_normal"), rev = this.sc("mock_rep_revised")
    const a = this.backtestOf(base), b = this.backtestOf(rev)
    const w = (bt: Backtest) => bt.chosen.def.weights
    const perf = (k: "cagr" | "mdd" | "final_usd", label: string, fmt: "pct" | "usd") => ({ metric: k, label_ko: label, base: a.chosen.m[k], revised: b.chosen.m[k], benchmark: a.bench.m[k], format: fmt })
    return { comparison_id: "mock_cmp_revised", base_run_id: base.run_id, revised_run_id: rev.run_id, base_report_id: base.id, revised_report_id: rev.id, created_at: "2026-11-01T10:00:00", same_window: true, window: { start: a.sim.dates[0], end: MOCK_AS_OF },
      base_chosen_id: a.chosen.def.id, revised_chosen_id: b.chosen.def.id, base_chosen_label_ko: a.chosen.def.label_ko, revised_chosen_label_ko: b.chosen.def.label_ko,
      condition_changes: [{ field: "constraints.max_weight_per_stock", label_ko: "종목당 최대 비중", base: base.max_weight, revised: rev.max_weight }, { field: "risk.max_drawdown_tolerance", label_ko: "손실 감내 수준", base: base.max_dd, revised: rev.max_dd }],
      ticker_changes: { added: [], removed: [], kept: base.tickers },
      weight_changes: base.tickers.map((t) => ({ ticker: t, base: w(a)[t] ?? 0, revised: w(b)[t] ?? 0, delta: (w(b)[t] ?? 0) - (w(a)[t] ?? 0) })),
      rule_changes: [{ rule: "R1", label_ko: "최대낙폭", base: a.checks[a.chosen.def.id][0].status, revised: b.checks[b.chosen.def.id][0].status, changed: a.checks[a.chosen.def.id][0].status !== b.checks[b.chosen.def.id][0].status }],
      performance_table: [perf("cagr", "연평균 수익률(CAGR)", "pct"), perf("mdd", "최대낙폭", "pct"), perf("final_usd", "최종 평가금액", "usd")],
      pros_cons_ko: { pros_ko: ["[목업] 종목당 상한을 낮춰 한 종목 쏠림이 줄었습니다."], cons_ko: ["[목업] 수익률이 조금 낮아질 수 있습니다."], note_ko: "목업 비교입니다." }, revision_text: rev.revision_text, warnings: [] }
  }
  getReportEvidence(reportId: string, q: EvidenceQuery = {}): Promise<EvidencePage | null> {
    return this.wait(() => {
      const ev = this.docOf(this.sc(reportId)).evidence
      const f = ev.filter((e) => (!q.kind || e.kind === q.kind) && (!q.ticker || e.tickers.includes(q.ticker)) && (!q.q || e.title.includes(q.q)) && (!q.ids || q.ids.includes(e.id)))
      const by_kind: Record<string, number> = {}; for (const e of f) by_kind[e.kind] = (by_kind[e.kind] ?? 0) + 1
      const off = q.offset ?? 0, lim = q.limit ?? 50
      return { total: f.length, offset: off, limit: lim, items: f.slice(off, off + lim), by_kind, index_total: ev.length }
    })
  }
  getReportEvidenceOne(reportId: string, eid: string) { return this.wait(() => { const e = this.docOf(this.sc(reportId)).evidence.find((x) => x.id === eid); return e ? { ...e, cited_in: [] } : null }) }
  getReportCheckpoint(reportId: string, seq: number): Promise<CheckpointDetail | null> { return this.wait(() => { const sc = this.sc(reportId); return checkpointDetail(sc, this.backtestOf(sc), seq) }) }
  getReportSeries(reportId: string, dataset: "index" | "value_usd" | "drawdown", ids?: string[]): Promise<SeriesResponse | null> {
    return this.wait(() => { const d = this.docOf(this.sc(reportId)); return { dataset, dates: d.datasets.dates, series: Object.fromEntries(Object.entries(d.datasets.series).filter(([k, s]) => (!ids || ids.includes(k)) && s[dataset]).map(([k, s]) => [k, { label_ko: s.label_ko, kind: s.kind, values: s[dataset]! }])) } })
  }

  /* ───────── 모의투자 ───────── */
  previewPaper(input: PaperIn): Promise<PaperPreview> {
    const sc = this.sc(input.report_id)
    return this.wait(() => paperPreview(sc, this.backtestOf(sc), input.strategy_id, input.initial_amount ?? sc.capital.amount, input.currency ?? sc.capital.currency, input.monthly_contribution))
  }
  createPaper(input: PaperIn): Promise<PaperDetail> {
    const sc = this.sc(input.report_id), b = this.backtestOf(sc)
    const ps: PaperScenario = { id: this.nextId("mock_paper"), report_id: sc.id, strategy: !input.strategy_id || input.strategy_id === b.chosen.def.id ? "chosen" : input.strategy_id, start_date: "2026-10-01", capital: { amount: input.initial_amount ?? sc.capital.amount, currency: input.currency ?? sc.capital.currency, monthly: input.monthly_contribution ?? 0 }, name: input.name ?? { mode: "linked" }, status: "active", fx_gaps: [] }
    this.s.createdPapers.push(ps); this.commit()
    return this.wait(() => this.paperOf(ps.id).detail)
  }
  listPaper(): Promise<PaperSummary[]> { return this.wait(() => this.allPapers().map((p) => this.paperOf(p.id).detail.summary)) }
  getPaper(id: string): Promise<PaperDetail> { return this.wait(() => this.paperOf(id).detail) }
  refreshPaper(id: string) { return this.getPaper(id) }
  stopPaper(id: string) { this.s.paperStatus[id] = "stopped"; this.commit(); return this.getPaper(id) }
  resumePaper(id: string) { this.s.paperStatus[id] = "active"; this.commit(); return this.getPaper(id) }
  getPaperKrw(id: string) { return this.wait(() => this.paperOf(id).krw) }
  getPaperName(id: string): Promise<ProposedPaperName> { return this.wait(() => this.paperNameView(id)) }
  private paperNameView(id: string): ProposedPaperName { const ps = this.allPapers().find((x) => x.id === id); if (!ps) throw notFound("모의투자"); const n = this.s.paperNames[id] ?? ps.name; return { name_ko: this.paperName(ps), mode: n.mode, report_name_ko: this.reportDisplayName(ps.report_id) } }
  setPaperName(id: string, input: ProposedPaperNameIn): Promise<ProposedPaperName> { this.s.paperNames[id] = input; this.commit(); return this.wait(() => this.paperNameView(id)) }
}

export const MOCK_RUN_STATES = RUN_STATES
