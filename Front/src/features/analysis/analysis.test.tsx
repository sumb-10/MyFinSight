import { describe, expect, it, vi } from "vitest"
import { fireEvent, render, screen, waitFor, within } from "@testing-library/react"
import { Providers } from "../../app/providers"
import { ApiError } from "../../api/client"
import type { AnalysisService } from "../../api/service"
import type { ConditionRow, DialogState, ProfileView, Question } from "../../api/types"
import type { ProposedMessageResult } from "../../api/proposed"
import { ClarifyScreen } from "./ClarifyScreen"
import { ConfirmScreen } from "./ConfirmScreen"

// 새 분석 · 조건 확인 화면 회귀 테스트. 서버 대신 가짜 서비스를 꽂고, 요청 형식(answer·updateOverrides·sendMessage·confirm 인자)이 그대로인지 본다.

const version = {
  version: 1, created_at: "2026-01-01T00:00:00", profile: { user_id: "default", age_band: "30s", investment_experience: "beginner", financial_knowledge: "basic", investable_ratio_of_assets: 0.3 },
  capital: { initial_amount: 10_000_000, currency: "KRW", trading_currency: "USD", monthly_contribution: 0, contribution_day: 25 }, horizon: { target_years: 5, purpose: "wealth_growth", backtest_years: 3 },
  risk: { risk_tolerance: "moderate", max_drawdown_tolerance: 0.2, loss_reaction: "hold", target_annual_return: 0.08, benchmark: "SPY" },
  constraints: { universe: ["SP500", "NASDAQ100"], asset_types: ["stock"], num_holdings: { target: 10, min: 8, max: 12 }, max_weight_per_stock: 0.15, max_weight_per_sector: 0.4, min_cash_ratio: 0, exclude_tickers: [], exclude_sectors: [], exclude_themes: [], must_include_tickers: [], rebalance: { count: 1, unit: "1q" }, allow_leverage: false, allow_short: false, min_market_cap_usd: 0, min_avg_daily_volume_usd: 0 },
  strategy_preference: { template: "momentum", baseline_weighting: "equal_weight", use_news_tilt: true },
  diagnosis: { answers: { loss: 2, reaction: 2, priority: 2 }, computed_tendency: "위험중립형", final_tendency: "위험중립형", memo: "" }, risk_type_computed: "moderate", risk_type_overridden: false,
}
const profileView = { profile_id: "p", current_version: 1, profile: version, versions: [{ version: 1, created_at: version.created_at }] } as unknown as ProfileView

function fakeService(over: Partial<Record<keyof AnalysisService, unknown>> = {}): AnalysisService {
  return {
    mode: "api", health: () => Promise.resolve({ ok: true, api_version: "1", llm_mode: "api", db: { ok: true }, worker: { alive: true, running_run_id: null }, queue_length: 0 }),
    options: () => Promise.reject(new ApiError("NOT_IN_TEST", "테스트에서 쓰지 않음", 500)), getProfile: () => Promise.resolve(profileView),
    listRequests: () => Promise.resolve([]), listRuns: () => Promise.resolve([]), listReports: () => Promise.resolve([]), getReportComparison: () => Promise.resolve(null),
    ...over,
  } as unknown as AnalysisService
}

const row = (field: string, group_ko: string, label_ko: string, value_ko: string, profile_value_ko: string | null = null): ConditionRow =>
  ({ field, group_ko, label_ko, value_ko, changed: profile_value_ko !== null, profile_value_ko, source: profile_value_ko !== null ? "answer" : "profile", supported: true })
const rows: ConditionRow[] = [
  row("natural_language.idea", "아이디어", "투자 아이디어", "반도체"),
  row("capital.initial_amount", "자금", "투자금", "10,000,000 원"),
  row("horizon.target_years", "기간·목적", "투자기간", "5년"),
  row("constraints.universe", "종목 범위·제약", "투자 유니버스", "S&P 500", "S&P 500, NASDAQ-100"),
  row("constraints.num_holdings", "종목 범위·제약", "종목 수", "목표 8개 (최소 6 ~ 최대 10)", "목표 10개 (최소 8 ~ 최대 12)"),
  row("constraints.exclude_tickers", "종목 범위·제약", "제외 종목", "NVDA"),
  row("constraints.must_include_tickers", "종목 범위·제약", "필수 포함 종목", "TSLA, AAPL", "없음"),
  row("strategy_preference.template", "전략 선호", "선정 기준", "모멘텀"),
]
const answered: Question = { seq: 1, field: "strategy_preference.template", field_label_ko: "선정 기준", kind: "preference", question_ko: "어떤 기준으로 고를까요?", options: [], allow_free_text: true, priority: 1, asked_at: "t", answer: "모멘텀", answered_at: "t" }
const base = (extra: Partial<DialogState>): DialogState => ({
  request_id: "r1", mode: "new", status: "draft", state: "ready", turn: 2, max_questions: 5, idea: "미국 반도체 기업에 투자", question: null, questions: [answered], hard_errors: [],
  confirmation: { effective_request: {} as never, rows, all_supported: true }, unresolved: [], conditions: rows, overrides: {},
  summary: { interpretation_summary_ko: "반도체 기업 중심으로 해석했습니다.", themes: [{ id: "semi", label_ko: "반도체", description_ko: "" }], derived: null, changed_fields: [] }, warnings: [], ...extra,
})
const deferred = <T,>() => { let resolve!: (v: T) => void, reject!: (e: unknown) => void; const promise = new Promise<T>((a, b) => { resolve = a; reject = b }); return { promise, resolve, reject } }

describe("조건 확인 화면", () => {
  it("달라진 조건을 먼저, 전체 조건은 접어서 보여 주고, 제거한 버튼은 없다", async () => {
    render(<Providers service={fakeService({ getRequest: () => Promise.resolve(base({})) })}><ConfirmScreen requestId="r1" /></Providers>)
    await screen.findByText("이 조건으로 분석을 시작할까요?")
    const changed = screen.getByRole("heading", { name: /이번 분석에서 달라진 조건/ }).closest("section")!
    expect(within(changed).getByText("투자 유니버스")).toBeInTheDocument()
    expect(within(changed).getByText("목표 8개 (최소 6 ~ 최대 10)")).toBeInTheDocument()
    expect(within(changed).getByText(/기본 투자조건 목표 10개/)).toBeInTheDocument()
    expect(within(changed).queryByText("투자기간")).toBeNull()  // 안 바뀐 항목은 전체 조건에만
    const all = screen.getByRole("button", { name: /전체 투자 조건 보기/ })
    expect(all).toHaveAttribute("aria-expanded", "false")
    fireEvent.click(all)
    expect(screen.getByText("투자기간")).toBeInTheDocument()
    fireEvent.click(all); fireEvent.click(all)
    expect(screen.getByText("5년")).toBeInTheDocument()  // 접었다 펴도 값 그대로
    expect(screen.queryByRole("button", { name: /아이디어 수정/ })).toBeNull()
    expect(screen.queryByRole("button", { name: /기본 투자조건 수정/ })).toBeNull()
    const answers = screen.getByRole("button", { name: /지금까지 답한 내용/ })  // 접혀 있다가 누르면 펼쳐진다
    expect(answers).toHaveAttribute("aria-expanded", "false")
    expect(screen.queryByText("어떤 기준으로 고를까요?")).toBeNull()
    fireEvent.click(answers)
    expect(screen.getByText("어떤 기준으로 고를까요?")).toBeInTheDocument()
  })

  it("변경된 조건이 없으면 그렇다고 안내한다 (변경을 만들어 내지 않는다)", async () => {
    const plain = rows.map((r) => ({ ...r, changed: false, profile_value_ko: null, source: "profile" as const }))
    render(<Providers service={fakeService({ getRequest: () => Promise.resolve(base({ conditions: plain, confirmation: { effective_request: {} as never, rows: plain, all_supported: true } })) })}><ConfirmScreen requestId="r1" /></Providers>)
    expect(await screen.findByText(/기본 투자조건과 달라진 항목이 없습니다/)).toBeInTheDocument()
  })

  it("조건 바꾸기는 처리 중임을 보여 주고, 끝나면 바뀐 값을 알린다", async () => {
    const d = deferred<DialogState>()
    const updateOverrides = vi.fn(() => d.promise)
    render(<Providers service={fakeService({ getRequest: () => Promise.resolve(base({})), updateOverrides })}><ConfirmScreen requestId="r1" /></Providers>)
    await screen.findByText("이 조건으로 분석을 시작할까요?")
    await waitFor(() => expect(screen.getByRole("button", { name: /조건 바꾸기/ })).toBeEnabled())
    fireEvent.click(screen.getByRole("button", { name: /조건 바꾸기/ }))
    fireEvent.click(await screen.findByRole("button", { name: "이 조건으로 다시 확인" }))
    expect(updateOverrides).toHaveBeenCalledWith("r1", {})
    expect(screen.getByText("투자 조건 변경 요청을 처리하고 있습니다.")).toBeInTheDocument()
    expect(screen.getByRole("button", { name: /분석 시작/ })).toBeDisabled()
    const after = rows.map((r) => (r.field === "horizon.target_years" ? { ...r, value_ko: "3년", changed: true, profile_value_ko: "5년" } : r))
    d.resolve(base({ conditions: after, confirmation: { effective_request: {} as never, rows: after, all_supported: true } }))
    expect(await screen.findByText(/조건 변경을 반영했습니다. 바뀐 조건 1개/)).toBeInTheDocument()
    expect(screen.getByText((_, el) => el?.tagName === "LI" && el.textContent === "투자기간: 5년 → 3년")).toBeInTheDocument()
    expect(screen.queryByText("투자 조건 변경 요청을 처리하고 있습니다.")).toBeNull()
  })

  it("보내지 않은 추가 요청이 있으면 분석을 바로 시작하지 않고 먼저 묻는다", async () => {
    const confirm = vi.fn(() => Promise.resolve({ run_id: "run1", queue_position: 0 }))
    const sendMessage = vi.fn(() => Promise.resolve(base({})))
    render(<Providers service={fakeService({ getRequest: () => Promise.resolve(base({})), confirm, sendMessage })}><ConfirmScreen requestId="r1" /></Providers>)
    await screen.findByText("이 조건으로 분석을 시작할까요?")
    fireEvent.change(screen.getByLabelText("말로 조건 보태기"), { target: { value: "배당주 위주로" } })
    expect(screen.getByText(/아직 반영하지 않았습니다/)).toBeInTheDocument()
    fireEvent.click(screen.getByRole("button", { name: /분석 시작/ }))
    expect(confirm).not.toHaveBeenCalled()
    const ask = screen.getByRole("alertdialog", { name: "반영하지 않은 추가 요청" })
    fireEvent.click(within(ask).getByRole("button", { name: "먼저 반영하기" }))
    await waitFor(() => expect(sendMessage).toHaveBeenCalledWith("r1", "배당주 위주로"))
    expect(confirm).not.toHaveBeenCalled()
    expect(await screen.findByText(/추가 요청을 처리했지만 바뀐 조건 값은 없습니다/)).toBeInTheDocument()
    fireEvent.click(screen.getByRole("button", { name: /분석 시작/ }))
    await waitFor(() => expect(confirm).toHaveBeenCalledWith("r1"))
  })
})

describe("추가 점검 질문 화면", () => {
  const q: Question = { seq: 2, field: "constraints.num_holdings", field_label_ko: "종목 수", kind: "feasibility", question_ko: "후보가 부족합니다. 어떻게 할까요?", options: [{ value: "a", label_ko: "종목 수 줄이기", patch: { "constraints.num_holdings": { target: 6, min: 5, max: 8 } } }, { value: "b", label_ko: "그대로" }], allow_free_text: true, priority: 1, asked_at: "t" }
  const asking = base({ state: "asking", question: q, questions: [answered, q], confirmation: null,
    precheck: { min: 8, target: 10, short_now: false, short_at_start: true, as_of: { date: "2026-10-30", n_candidates: 40, n_with_metric: 30 }, start: { date: "2023-10-30", n_candidates: 9, n_with_metric: 5 }, feasible_start: { date: "2024-06-28", years: 2.3, n_with_metric: 9 } } })

  it("몇 번째 질문인지·답한 수를 실제 정보로만 보여 주고, 선택지가 바꾸는 조건과 점검 숫자를 알려 준다", async () => {
    render(<Providers service={fakeService({ getRequest: () => Promise.resolve(asking) })}><ClarifyScreen requestId="r1" /></Providers>)
    await screen.findByText("후보가 부족합니다. 어떻게 할까요?")
    expect(screen.getByText(/2번째 질문입니다. 지금까지 1개에 답했습니다. 질문은 최대 5개까지이며, 남은 질문 수는 답에 따라 달라집니다./)).toBeInTheDocument()
    expect(screen.getByText(/분석을 시작하기 전에 조정 방법을 고릅니다/)).toBeInTheDocument()
    expect(screen.getByText("바뀌는 조건: 종목 수 → 목표 6 (5~8)")).toBeInTheDocument()
    expect(screen.getByText(/백테스트를 2024-06-28부터 시작하면\(2.3년\) 후보 9개로 분석할 수 있습니다/)).toBeInTheDocument()
    const answers = screen.getByRole("button", { name: /지금까지 답한 내용/ })  // 접혀 있다가 누르면 펼쳐진다
    expect(answers).toHaveAttribute("aria-expanded", "false")
    expect(screen.queryByText("어떤 기준으로 고를까요?")).toBeNull()
    fireEvent.click(answers)
    expect(screen.getByText("어떤 기준으로 고를까요?")).toBeInTheDocument()
  })

  it("답변은 기존 형식으로 보내고, 처리 중 안내 뒤 실패하면 고른 답을 남긴 채 다시 시도할 수 있다", async () => {
    const d = deferred<DialogState>()
    const answer = vi.fn(() => d.promise)
    render(<Providers service={fakeService({ getRequest: () => Promise.resolve(asking), answer })}><ClarifyScreen requestId="r1" /></Providers>)
    await screen.findByText("후보가 부족합니다. 어떻게 할까요?")
    fireEvent.click(screen.getByRole("radio", { name: /종목 수 줄이기/ }))
    fireEvent.click(screen.getByRole("button", { name: "답변 보내기" }))
    expect(answer).toHaveBeenCalledWith("r1", 2, { option_value: "a" })
    expect(screen.getByText("답변을 반영하고 다음 질문을 준비하고 있습니다.")).toBeInTheDocument()
    d.reject(new ApiError("TIMEOUT", "응답이 늦습니다.", 0))
    expect(await screen.findByText("답변을 반영하지 못했습니다")).toBeInTheDocument()
    expect(screen.getByRole("radio", { name: /종목 수 줄이기/ })).toHaveAttribute("aria-checked", "true")
    answer.mockImplementation(() => new Promise(() => {}))
    fireEvent.click(screen.getByRole("button", { name: "다시 시도" }))
    expect(answer).toHaveBeenCalledTimes(2)
  })

  it("말로 보탠 뒤 더 물을 것이 없어 확인 화면으로 넘어가도, 확인 화면 맨 위에 그 결과가 이어서 나온다 (한 번만)", async () => {
    const result: ProposedMessageResult = { text: "장비 회사 위주로", at: "2026-11-10T09:00:00", outcome: "applied", note_ko: "아이디어 해석(테마)에 반영했습니다. 조건 값은 그대로입니다.",
      changes: [{ field: "intent.themes", label_ko: "해석한 테마", before_ko: "반도체", after_ko: "반도체 장비" }] }
    const sendMessage = vi.fn(() => Promise.resolve(base({})))  // 질문이 닫히고 더 물을 것이 없음 → ready
    const getMessageResults = vi.fn(() => Promise.resolve([result]))
    const svc = fakeService({ getRequest: () => Promise.resolve(asking), sendMessage, getMessageResults })
    const clarify = render(<Providers service={svc}><ClarifyScreen requestId="r1" /></Providers>)
    await screen.findByText("후보가 부족합니다. 어떻게 할까요?")
    fireEvent.change(screen.getByLabelText("말로 조건 보태기"), { target: { value: "장비 회사 위주로" } })
    fireEvent.click(screen.getByRole("button", { name: "말로 보태기" }))
    await waitFor(() => expect(getMessageResults).toHaveBeenCalledWith("r1"))
    await waitFor(() => expect(window.location.hash).toContain("confirm"))
    clarify.unmount()
    const confirmSvc = fakeService({ getRequest: () => Promise.resolve(base({})), getMessageResults })
    const first = render(<Providers service={confirmSvc}><ConfirmScreen requestId="r1" /></Providers>)
    const box = await screen.findByRole("region", { name: "방금 보낸 추가 요청 결과" })
    expect(within(box).getByText("반영됨")).toBeInTheDocument()
    expect(within(box).getByText(/해석한 테마: 반도체 →/)).toBeInTheDocument()
    expect(within(box).getByText("반도체 장비")).toBeInTheDocument()
    first.unmount()
    render(<Providers service={confirmSvc}><ConfirmScreen requestId="r1" /></Providers>)  // 다시 열면 없다
    await screen.findByText("이 조건으로 분석을 시작할까요?")
    expect(screen.queryByRole("region", { name: "방금 보낸 추가 요청 결과" })).toBeNull()
    window.history.replaceState(null, "", "/")
  })
})
