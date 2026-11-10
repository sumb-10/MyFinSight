import { afterEach, beforeAll, describe, expect, it, vi } from "vitest"
import { fireEvent, render, screen, waitFor } from "@testing-library/react"
import type { ProposedChatAnswer, ProposedProfileChat } from "../api/proposed"
import type { AnalysisService } from "../api/service"
import App from "../app/App"
import { Providers } from "../app/providers"
import { ProfileChatScreen } from "../features/profile/chat/ProfileChatScreen"
import { ProfileScreen } from "../features/profile/ProfileScreen"
import { validateProfile } from "../features/profile/validate"
import { loadUi } from "../state/uiStorage"
import { CHAT_QUESTIONS, holdingsFor } from "./data/profileChat"
import { recommendation } from "./data/strategy"
import { parseCount, parseKrw } from "../features/profile/chat/ChatInput"
import { ChatReviewSummary } from "../features/profile/chat/ChatReview"
import { profileRows } from "../features/profile/compare"
import { MockService } from "./services/MockService"

beforeAll(() => { globalThis.ResizeObserver ??= class { observe() {} unobserve() {} disconnect() {} } as unknown as typeof ResizeObserver; Element.prototype.scrollIntoView = vi.fn() })
afterEach(() => { window.history.replaceState(null, "", "/"); window.localStorage.clear() })

// 대화형 초기 투자조건 (제안 기능 · 목업). 정해진 질문 순서·보기로만 묻고, 결과 초안은 폼과 같은 검사를 통과해야 한다.

const mock = () => new MockService({ latencyMs: 0, persist: false })

/** 위험중립형이 나오는 기본 답 (진단 점수 2+2+2=6 → 위험중립형). */
const PATH: Record<string, Omit<ProposedChatAnswer, "question_id">> = {
  purpose: { option_value: "wealth_growth" }, amount: { option_value: 10_000_000 }, monthly: { number: 300_000 }, years: { option_value: 5 },
  age: { option_value: "40s" }, experience: { option_value: "intermediate" }, knowledge: { option_value: "intermediate" }, ratio: { option_value: 0.5 },
  loss: { option_value: 2 }, reaction: { option_value: 2 }, priority: { option_value: 2 },
  tendency: { option_value: "위험중립형" }, tendency_apply: { option_value: "apply" }, universe: { option_value: ["SP500"] }, holdings: { option_value: 5 },
  strategy: { option_value: "recommended" },
}
/** 진단 결과대로 고르면 묻는 질문 수 (「성향 기본값」은 진단과 다른 성향일 때만 묻는다). */
const ASKED = CHAT_QUESTIONS.length - 1
async function answerAll(s: MockService, c: ProposedProfileChat, until?: string): Promise<ProposedProfileChat> {
  while (c.question && c.question.id !== until) c = await s.answerProfileChat(c.chat_id, { question_id: c.question.id, ...PATH[c.question.id] })
  return c
}

describe("대화형 초기 투자조건 · 목업 규칙", () => {
  it("인사와 첫 질문으로 시작하고, 초안은 기본값으로 채워져 있다", async () => {
    const c = await mock().startProfileChat()
    expect(c).toMatchObject({ state: "asking", progress: { done: 0, total: ASKED }, question: { id: "purpose", kind: "choice" }, asked_fields: [], derived_fields: {} })
    expect(c.messages.map((m) => m.role)).toEqual(["bot", "bot"])
    expect(validateProfile(c.draft)).toEqual({})
  })
  it("끝까지 답하면 요약 단계가 되고, 초안은 답을 반영해 폼 검사를 통과한다", async () => {
    const s = mock()
    const c = await answerAll(s, await s.startProfileChat())
    expect(c).toMatchObject({ state: "review", question: null, progress: { done: ASKED, total: ASKED } })
    const d = c.draft
    expect(d.capital).toMatchObject({ initial_amount: 10_000_000, monthly_contribution: 300_000, currency: "KRW" })
    expect(d.horizon).toMatchObject({ purpose: "wealth_growth", target_years: 5 })
    expect(d.diagnosis).toMatchObject({ answers: { loss: 2, reaction: 2, priority: 2 }, computed_tendency: "위험중립형", final_tendency: "위험중립형" })
    expect(d.risk).toMatchObject({ risk_tolerance: "moderate", max_drawdown_tolerance: 0.2, loss_reaction: "hold" })
    expect(d.constraints).toMatchObject({ universe: ["SP500"], num_holdings: { target: 5, min: 4, max: 6 }, max_weight_per_stock: 0.25 })
    expect(d.strategy_preference).toEqual({ template: "quality", baseline_weighting: "equal_weight", use_news_tilt: true })  // 위험중립형 추천 예시
    expect(validateProfile(d)).toEqual({})
    expect(c.asked_fields).toEqual(expect.arrayContaining(["capital.initial_amount", "capital.monthly", "tendency", "constraints.universe", "strategy.template", "strategy.weighting"]))
    expect(c.asked_fields).not.toContain("risk.benchmark")  // 답에 맞춰 정한 항목은 따로 (이유와 함께)
    expect(c.derived_fields).toEqual({ "risk.target_annual_return": "투자성향 ‘위험중립형’ 기본값", "risk.benchmark": "투자 대상(S&P 500)에 맞춤", "constraints.max_weight": "종목 5개에 맞춤 · 같은 업종이 많으면 섹터 상한(40%) 때문에 현금이 남을 수 있어요" })
    expect(d.profile).toMatchObject({ age_band: "40s", investment_experience: "intermediate", financial_knowledge: "intermediate", investable_ratio_of_assets: 0.5 })
    expect(c.messages.at(-1)?.text_ko).toMatch(/요약을 확인하고 저장/)
  })
  it("범위 밖 금액은 저장하지 않고 다시 묻는다. 맞는 값을 주면 안내가 사라진다", async () => {
    const s = mock()
    const c0 = await answerAll(s, await s.startProfileChat(), "amount")
    const bad = await s.answerProfileChat(c0.chat_id, { question_id: "amount", number: 1_000 })
    expect(bad.question?.id).toBe("amount")
    expect(bad.messages.at(-1)).toMatchObject({ role: "bot", text_ko: expect.stringContaining("10만원 이상") })
    const ok = await s.answerProfileChat(c0.chat_id, { question_id: "amount", number: 2_500_000 })
    expect(ok.question?.id).toBe("monthly")
    expect(ok.draft.capital.initial_amount).toBe(2_500_000)
    expect(ok.messages.some((m) => m.id.endsWith(":retry"))).toBe(false)
  })
  it("처음 투자금 0원은 보기로 고르고, 그러면 월 적립 0원은 받지 않는다 (서버 규칙과 같음). 요약 초안은 0원 규칙으로 검사를 통과한다", async () => {
    const s = mock()
    const c0 = await answerAll(s, await s.startProfileChat(), "amount")
    expect(c0.question?.options.at(-1)).toMatchObject({ value: 0, label_ko: "0원 · 매월 적립으로 시작" })
    const z = await s.answerProfileChat(c0.chat_id, { question_id: "amount", option_value: 0 })
    expect(z.question?.id).toBe("monthly")
    expect(z.question?.options.map((o) => o.value)).not.toContain(0)
    expect(z.messages.at(-1)?.text_ko).toMatch(/^처음 투자금 없이 시작하니 매월 추가 투자금이 꼭 있어야 해요/)
    const bad = await s.answerProfileChat(c0.chat_id, { question_id: "monthly", number: 0 })
    expect(bad.question?.id).toBe("monthly")
    expect(bad.messages.at(-1)?.text_ko).toMatch(/0원이라 매월 추가 투자금이 꼭 있어야/)
    const c = await answerAll(s, bad)
    expect(c.state).toBe("review")
    expect(c.draft.capital).toMatchObject({ initial_amount: 0, monthly_contribution: 300_000 })
    expect(validateProfile(c.draft, { allowZero: true })).toEqual({})
  })
  it("요약에서 금액을 0원으로 고치면 「추가 투자 없음」이던 월 적립만 다시 묻는다", async () => {
    const s = mock()
    let c = await s.startProfileChat()
    while (c.question) c = await s.answerProfileChat(c.chat_id, { question_id: c.question.id, ...(c.question.id === "monthly" ? { option_value: 0 } : PATH[c.question.id]) })
    await s.rewindProfileChat(c.chat_id, "amount")
    const r = await s.answerProfileChat(c.chat_id, { question_id: "amount", option_value: 0 })
    expect(r.question?.id).toBe("monthly")
    expect(r.progress.done).toBe(ASKED - 1)
  })
  it("지금 질문이 아닌 답은 거절하고, 꼭 답해야 하는 질문은 건너뛸 수 없다", async () => {
    const s = mock()
    const c = await s.startProfileChat()
    await expect(s.answerProfileChat(c.chat_id, { question_id: "amount", number: 1_000_000 })).rejects.toMatchObject({ status: 409 })
    const skipped = await s.answerProfileChat(c.chat_id, { question_id: "purpose", skip: true })
    expect(skipped.question?.id).toBe("purpose")
    expect(skipped.messages.at(-1)?.text_ko).toMatch(/꼭 답해/)
  })
  it("진단과 다른 성향을 고르면 표시가 남고, 추천 전략도 고른 성향을 따른다", async () => {
    const s = mock()
    let c = await answerAll(s, await s.startProfileChat(), "tendency")
    expect(c.question?.options.find((o) => o.recommended)?.value).toBe("위험중립형")
    c = await s.answerProfileChat(c.chat_id, { question_id: "tendency", option_value: "안정형" })
    c = await answerAll(s, c)
    expect(c.draft).toMatchObject({ risk_type_overridden: true, risk: { risk_tolerance: "conservative" }, diagnosis: { computed_tendency: "위험중립형", final_tendency: "안정형" } })
    expect(c.draft.strategy_preference.template).toBe("high_dividend")
  })
  it("「고치기」는 그 답만 다시 묻고, 다시 답하면 나머지 답은 그대로 둔 채 요약으로 돌아간다", async () => {
    const s = mock()
    const c = await answerAll(s, await s.startProfileChat())
    const r = await s.rewindProfileChat(c.chat_id, "amount")
    expect(r).toMatchObject({ state: "asking", question: { id: "amount" }, progress: { done: ASKED - 1 } })
    expect(r.messages.filter((m) => m.role === "user")).toHaveLength(1)  // 뒤의 말풍선은 지금 질문에 답할 때까지 숨긴다
    expect(r.messages.at(-1)?.text_ko).toMatch(/뒤에 답한 13개는 그대로/)
    expect(r.draft.constraints.universe).toEqual(["SP500"])               // 뒤의 답은 초안에 남아 있다
    const back = await s.answerProfileChat(c.chat_id, { question_id: "amount", option_value: 30_000_000 })
    expect(back).toMatchObject({ state: "review", draft: { capital: { initial_amount: 30_000_000, monthly_contribution: 300_000 } } })
    expect(back.messages.filter((m) => m.role === "user")).toHaveLength(ASKED)
  })
  it("성향 진단 답을 고치면 진단 결과가 바뀔 수 있어 「성향 확인」도 다시 묻는다", async () => {
    const s = mock()
    const c = await answerAll(s, await s.startProfileChat())
    await s.rewindProfileChat(c.chat_id, "loss")
    let r = await s.answerProfileChat(c.chat_id, { question_id: "loss", option_value: 3 })
    expect(r.question?.id).toBe("tendency")
    expect(r.question?.options.find((o) => o.recommended)?.value).toBe(r.draft.diagnosis!.computed_tendency)
    r = await s.answerProfileChat(c.chat_id, { question_id: "tendency", option_value: r.draft.diagnosis!.computed_tendency })
    expect(r.state).toBe("review")
  })
  it("종목 수에 맞춰 범위와 종목당 상한을 같이 정한다", () => {
    expect(holdingsFor(10)).toMatchObject({ num_holdings: { target: 10, min: 8, max: 12 }, max_weight_per_stock: 0.15 })
    expect(holdingsFor(3)).toMatchObject({ num_holdings: { min: 2, max: 4 }, max_weight_per_stock: 0.5, max_weight_per_sector: 0.5 })
  })
})

/** 처음 사용자(투자조건 없음) 목업 서비스. */
const firstUser = () => { const s = mock(); s.setProfileVariant("none"); return s }
const show = (svc: AnalysisService, ui: React.ReactNode, hash = "") => { window.history.replaceState(null, "", `/?mock=1${hash}`); return render(<Providers service={svc}>{ui}</Providers>) }
const pick = async (name: RegExp) => fireEvent.click(await screen.findByRole("button", { name }, { timeout: 5000 }))

describe("대화형 초기 투자조건 화면 (목업)", () => {
  it("보기를 눌러 끝까지 답하고 요약에서 저장하면 버전 1이 생기고 홈으로 간다", async () => {
    const s = firstUser()
    show(s, <ProfileChatScreen />)
    expect(await screen.findByRole("heading", { level: 1, name: "내 프로필을 정해봅시다" }, { timeout: 5000 })).toBeInTheDocument()
    await pick(/^자산 증식/)
    await pick(/^1,000만원/)
    await pick(/^추가 투자 없음/)
    await pick(/^5년/)
    await pick(/^40대/)
    await pick(/^중급/)  // 투자 경험
    await pick(/^중급/)  // 금융 지식
    await pick(/^50% 정도/)
    await pick(/^약 20% 하락까지/)
    await pick(/^계획을 유지합니다/)
    await pick(/^균형/)
    await pick(/^위험중립형 \(진단 결과\)/)
    await pick(/^S&P 500/)
    await pick(/^선택 완료 \(1\)/)
    await pick(/^10개/)
    await pick(/^추천:/)
    expect(await screen.findByRole("heading", { name: "이렇게 정리했어요" }, { timeout: 5000 })).toBeInTheDocument()
    expect(screen.getByRole("progressbar", { name: "답한 질문" })).toHaveAttribute("aria-valuenow", String(ASKED))
    fireEvent.click(screen.getByRole("button", { name: /이대로 저장/ }))
    await waitFor(() => expect(window.location.hash).toBe("#/home"))
    expect(await s.getProfile()).toMatchObject({ current_version: 1, profile: { note: "첫 등록", capital: { initial_amount: 10_000_000 }, constraints: { universe: ["SP500"] } } })
  })
  it("직접 입력한 금액이 범위 밖이면 다시 묻고, 「고치기」로 앞의 답을 다시 고를 수 있다", async () => {
    show(firstUser(), <ProfileChatScreen />)
    await pick(/^현금흐름\(배당\)/)
    const input = await screen.findByRole("textbox", { name: "처음 투자할 금액 직접 입력" }, { timeout: 5000 })
    fireEvent.change(input, { target: { value: "5,000" } })
    expect(input).toHaveValue("5,000")
    fireEvent.click(screen.getByRole("button", { name: /보내기/ }))
    expect(await screen.findByText(/10만원 이상 100억원 이하로 알려 주세요/, {}, { timeout: 5000 })).toBeInTheDocument()
    fireEvent.click(screen.getByRole("button", { name: "‘현금흐름(배당)’ 답 고치기" }))
    expect(await screen.findByRole("button", { name: /^원금 보존/ }, { timeout: 5000 })).toBeInTheDocument()
    expect(screen.queryByText("현금흐름(배당)", { selector: "p" })).toBeNull()
  })
  it("「폼으로 한 번에 입력」은 답한 내용을 넘기고, 처음 설정 폼이 그 값으로 미리 채운다", async () => {
    const s = firstUser()
    const { unmount } = show(s, <ProfileChatScreen />)
    await pick(/^은퇴 대비/)
    await pick(/^5,000만원/)
    await screen.findByRole("button", { name: /^추가 투자 없음/ }, { timeout: 5000 })
    fireEvent.click(screen.getByRole("button", { name: /폼으로 한 번에 입력/ }))
    expect(window.location.hash).toBe("#/profile/setup")
    expect(loadUi().profileDraft).toMatchObject({ capital: { initial_amount: 50_000_000 }, horizon: { purpose: "retirement" } })
    unmount()
    const { unmount: unmount2 } = show(s, <ProfileScreen mode="setup" />)
    expect(await screen.findByText("대화에서 답한 내용으로 채웠습니다", {}, { timeout: 5000 })).toBeInTheDocument()
    expect(screen.getByRole("button", { name: /2단계 투자성향 \(아직 시작 전\)/ })).toBeInTheDocument()  // 대화 중간에 넘어왔으면 묻지 않은 단계를 「완료」로 보이지 않는다
    fireEvent.click(screen.getByRole("button", { name: /대화로 이어서 하기/ }))
    expect(window.location.hash).toBe("#/profile/chat")
    unmount2()
  })
  it("폼에 다녀와도 대화는 처음부터가 아니라 넘어가기 전 질문에서 이어진다", async () => {
    const s = firstUser()
    const { unmount } = show(s, <ProfileChatScreen />)
    await pick(/^은퇴 대비/)
    await screen.findByRole("button", { name: /^5,000만원/ }, { timeout: 5000 })
    fireEvent.click(screen.getByRole("button", { name: /폼으로 한 번에 입력/ }))
    unmount()
    show(s, <ProfileChatScreen />, "#/profile/chat")
    expect(await screen.findByRole("button", { name: /^5,000만원/ }, { timeout: 5000 })).toBeInTheDocument()
    expect(screen.getByRole("progressbar", { name: "답한 질문" })).toHaveAttribute("aria-valuenow", "1")
    await pick(/^5,000만원/)
    expect(await screen.findByRole("button", { name: /^추가 투자 없음/ }, { timeout: 5000 })).toBeInTheDocument()
  })
  it("메신저처럼: 보낸 답과 「…」가 응답 전에 먼저 보이고, 스크롤은 대화창 안에서만 한다", async () => {
    const scrollTo = vi.fn()
    Element.prototype.scrollTo = scrollTo as unknown as typeof Element.prototype.scrollTo
    vi.mocked(Element.prototype.scrollIntoView).mockClear()
    const s = new MockService({ latencyMs: 40, persist: false }); s.setProfileVariant("none")
    show(s, <ProfileChatScreen />)
    fireEvent.click(await screen.findByRole("button", { name: /^현금흐름\(배당\)/ }, { timeout: 5000 }))
    expect(screen.getByText("현금흐름(배당)", { selector: "p" })).toBeInTheDocument()          // 응답 전에 내 답 말풍선
    expect(screen.getByText("도우미가 답을 확인하고 있습니다")).toBeInTheDocument()             // 봇 「…」
    expect(await screen.findByRole("button", { name: /^1,000만원/ }, { timeout: 5000 })).toBeInTheDocument()
    expect(screen.queryByText("도우미가 답을 확인하고 있습니다")).toBeNull()
    expect(scrollTo).toHaveBeenCalled()                                                      // 대화 영역 자체를 내린다
    expect(Element.prototype.scrollIntoView).not.toHaveBeenCalled()                          // 페이지까지 움직이는 scrollIntoView 는 쓰지 않는다
  })
  it("처음 사용자는 앱을 열면 대화형 설정으로 간다", async () => {
    show(firstUser(), <App />, "#/home")
    expect(await screen.findByRole("heading", { level: 1, name: "내 프로필을 정해봅시다" }, { timeout: 5000 })).toBeInTheDocument()
    expect(window.location.hash).toBe("#/profile/chat")
  })
})

describe("일반 모드 (대화 메서드 없음)", () => {
  const plain = (s: MockService): AnalysisService => Object.assign(Object.create(s), { mode: "api", startProfileChat: undefined, answerProfileChat: undefined, rewindProfileChat: undefined })
  it("처음 사용자는 지금처럼 4단계 폼으로 가고, 폼에 「대화로 설정하기」가 없다", async () => {
    window.history.replaceState(null, "", "/#/home")
    render(<Providers service={plain(firstUser())}><App /></Providers>)
    expect(await screen.findByRole("heading", { level: 1, name: "기본 투자조건을 알려주세요." }, { timeout: 5000 })).toBeInTheDocument()
    expect(window.location.hash).toBe("#/profile/setup")
    expect(screen.queryByRole("button", { name: /대화로 설정하기/ })).toBeNull()
  })
  it("주소로 대화형 화면을 열어도 4단계 폼을 보여 준다", async () => {
    render(<Providers service={plain(firstUser())}><ProfileChatScreen /></Providers>)
    expect(await screen.findByRole("heading", { level: 1, name: "기본 투자조건을 알려주세요." }, { timeout: 5000 })).toBeInTheDocument()
  })
})

describe("일반 모드 (실제 서버에 대화 API 가 있음)", () => {
  /** 실제 서버(POST /profile/chat …)처럼 대화 메서드가 있는 일반 모드 서비스. 응답은 서버와 같은 규칙인 목업 대화로 만든다. */
  const real = (s: MockService) => {
    const calls: string[] = []
    const svc: AnalysisService = Object.assign(Object.create(s), {
      mode: "api",
      startProfileChat: async () => { calls.push("start"); return s.startProfileChat() },
      answerProfileChat: async (id: string, a: ProposedChatAnswer) => { calls.push(`answer:${a.question_id}`); return s.answerProfileChat(id, a) },
      rewindProfileChat: async (id: string, q: string) => { calls.push(`rewind:${q}`); return s.rewindProfileChat(id, q) },
    })
    return { svc, calls }
  }
  it("처음 사용자는 앱을 열면 대화형 설정으로 가고, 「목업」 표시 없이 서버 대화를 이어 간다", async () => {
    const s = firstUser()
    const { svc, calls } = real(s)
    window.history.replaceState(null, "", "/#/home")
    render(<Providers service={svc}><App /></Providers>)
    expect(await screen.findByRole("heading", { level: 1, name: "내 프로필을 정해봅시다" }, { timeout: 5000 })).toBeInTheDocument()
    expect(window.location.hash).toBe("#/profile/chat")
    expect(screen.queryByText("목업")).toBeNull()
    await pick(/^자산 증식/)
    const input = await screen.findByRole("textbox", { name: "처음 투자할 금액 직접 입력" }, { timeout: 5000 })
    fireEvent.change(input, { target: { value: "5,000" } })
    fireEvent.click(screen.getByRole("button", { name: /보내기/ }))
    expect(await screen.findByText(/10만원 이상 100억원 이하로 알려 주세요/, {}, { timeout: 5000 })).toBeInTheDocument()  // 서버의 다시 묻는 말풍선
    fireEvent.click(screen.getByRole("button", { name: "‘자산 증식’ 답 고치기" }))
    expect(await screen.findByRole("button", { name: /^원금 보존/ }, { timeout: 5000 })).toBeInTheDocument()
    expect(calls).toEqual(["start", "answer:purpose", "answer:amount", "rewind:purpose"])
  })
})

// 2026-11-11 (docs/update_hojin_11.11.md): 한국식 금액 입력, 성향 기본값 확인, 목적에 맞춘 추천, 답에 맞춰 정한 조건, 일부 줄이기 표시
describe("대화형 설정 2026-11-11", () => {
  it("금액 칸은 「2천만원」「1억 5천만」「2,000만」「1.5억」도 읽고, 숫자 칸은 「3년」「10개」를 읽는다. 못 읽으면 null", () => {
    expect([parseKrw("2천만원"), parseKrw("1억 5천만원"), parseKrw("2,000만"), parseKrw("1.5억"), parseKrw("20000000"), parseKrw("천만원"), parseKrw("50만 원")])
      .toEqual([20_000_000, 150_000_000, 20_000_000, 150_000_000, 20_000_000, 10_000_000, 500_000])
    expect([parseKrw("많이"), parseKrw(""), parseKrw("2천만달러")]).toEqual([null, null, null])
    expect([parseCount("3년"), parseCount("10개"), parseCount("1.5"), parseCount("세 개")]).toEqual([3, 10, 1.5, null])
  })
  it("화면: 「2천만원」을 입력하면 2,000만원으로 미리 보이고 그대로 보낼 수 있다. 숫자가 아니면 「숫자로 적어 주세요」에 보내기가 잠긴다", async () => {
    show(firstUser(), <ProfileChatScreen />)
    await pick(/^자산 증식/)
    const input = await screen.findByRole("textbox", { name: "처음 투자할 금액 직접 입력" }, { timeout: 5000 })
    expect(input).toHaveAttribute("placeholder", expect.stringMatching(/^숫자로 적어 주세요 \(예: 2000만원, 20000000\)/))
    fireEvent.change(input, { target: { value: "많이" } })
    expect(screen.getByText("숫자로 적어 주세요")).toBeInTheDocument()
    expect(screen.getByRole("button", { name: "보내기" })).toBeDisabled()
    fireEvent.change(input, { target: { value: "2천만원" } })
    expect(screen.getByText("2,000만원")).toBeInTheDocument()
    fireEvent.click(screen.getByRole("button", { name: "보내기" }))
    expect(await screen.findByText(/매월 추가로 투자할 금액이 있나요/, {}, { timeout: 5000 })).toBeInTheDocument()
  })
  it("진단과 다른 성향을 고르면 그 성향 기본값으로 바뀌는 항목을 보여 주고, 「네」면 바꾸고 「아니요」면 그대로 둔다", async () => {
    for (const [choice, expected] of [["apply", { max_drawdown_tolerance: 0.3, loss_reaction: "buy_more", target_annual_return: 0.12 }], ["keep", { max_drawdown_tolerance: 0.2, loss_reaction: "hold", target_annual_return: 0.08 }]] as const) {
      const s = mock()
      let c = await answerAll(s, await s.startProfileChat(), "tendency")
      c = await s.answerProfileChat(c.chat_id, { question_id: "tendency", option_value: "공격투자형" })
      expect(c.question?.id).toBe("tendency_apply")
      expect(c.progress).toEqual({ done: 12, total: ASKED + 1 })
      expect(c.messages.at(-1)?.text_ko).toBe("‘공격투자형’으로 바꾸면 아래 조건도 이 성향의 기본값으로 바뀌어요.\n· 손실 감내 수준: 20% → 30%\n· 손실 시 대응: 보유 → 추가 매수\n· 목표 연수익률: 8% → 12%\n괜찮으신가요?")
      c = await answerAll(s, await s.answerProfileChat(c.chat_id, { question_id: "tendency_apply", option_value: choice }))
      expect(c.state).toBe("review")
      expect(c.draft.risk).toMatchObject({ risk_tolerance: "aggressive", ...expected })
    }
  })
  it("투자 목적을 보고 추천을 바꾼다: 배당 → 고배당, 원금 보존 → 저변동성·최소분산·뉴스 반영 끔, 은퇴 대비 → 퀄리티(위험중립형 이상)", () => {
    expect(recommendation("공격투자형", "income").recommended).toEqual({ template: "high_dividend", baseline_weighting: "equal_weight", use_news_tilt: true })
    expect(recommendation("위험중립형", "capital_preservation").recommended).toEqual({ template: "low_volatility", baseline_weighting: "min_variance", use_news_tilt: false })
    expect(recommendation("적극투자형", "retirement").recommended.template).toBe("quality")
    expect(recommendation("안정형", "retirement")).toEqual(recommendation("안정형"))
    expect(recommendation("공격투자형", "income").alternatives[0]).toMatchObject({ ...recommendation("공격투자형").recommended, diff_ko: "투자 목적을 빼고 투자성향만 보고 고른 조합입니다." })
  })
  it("KOSPI 200 만 고르면 비교지수는 KODEX 200, 요약은 답한 내용 · 답에 맞춰 정한 조건(이유) · 기본값으로 나눠 보인다", async () => {
    const s = mock()
    const c = await answerAll(s, await s.startProfileChat(), "universe")
    const r = await answerAll(s, await s.answerProfileChat(c.chat_id, { question_id: "universe", option_value: ["KOSPI200"] }))
    expect(r.draft.risk.benchmark).toBe("069500.KS")
    expect(r.derived_fields?.["risk.benchmark"]).toBe("투자 대상(KOSPI 200)에 맞춤")
    render(<Providers service={s}><ChatReviewSummary chat={r} allowZero /></Providers>)
    expect(screen.getByText(`질문 ${ASKED}개에 답하신 내용입니다. 저장하면 기본 투자조건으로 기록됩니다.`)).toBeInTheDocument()
    expect(screen.getByRole("heading", { name: "답에 맞춰 정한 조건 3개" })).toBeInTheDocument()
    expect(screen.getByText("투자 대상(KOSPI 200)에 맞춤")).toBeInTheDocument()
    expect(screen.getByText(/종목 5개에 맞춤 · 같은 업종이 많으면 섹터 상한\(40%\)/)).toBeInTheDocument()
  })
  it("「일부를 줄이고 상황을 지켜봅니다」는 보유로 저장하되 요약에는 그 뜻을 붙인다", async () => {
    const s = mock()
    const c = await answerAll(s, await s.startProfileChat(), "reaction")
    const r = await answerAll(s, await s.answerProfileChat(c.chat_id, { question_id: "reaction", option_value: 1 }))
    expect(r.draft.risk.loss_reaction).toBe("hold")
    expect(profileRows(r.draft).find((x) => x.key === "risk.loss_reaction")?.value).toBe("보유 (일부 줄이고 지켜봄)")
  })
})
