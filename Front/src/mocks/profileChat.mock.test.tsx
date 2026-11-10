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
import { MockService } from "./services/MockService"

beforeAll(() => { globalThis.ResizeObserver ??= class { observe() {} unobserve() {} disconnect() {} } as unknown as typeof ResizeObserver; Element.prototype.scrollIntoView = vi.fn() })
afterEach(() => { window.history.replaceState(null, "", "/"); window.localStorage.clear() })

// 대화형 초기 투자조건 (제안 기능 · 목업). 정해진 질문 순서·보기로만 묻고, 결과 초안은 폼과 같은 검사를 통과해야 한다.

const mock = () => new MockService({ latencyMs: 0, persist: false })

/** 위험중립형이 나오는 기본 답 (진단 점수 2+2+2=6 → 위험중립형). */
const PATH: Record<string, Omit<ProposedChatAnswer, "question_id">> = {
  purpose: { option_value: "wealth_growth" }, amount: { option_value: 10_000_000 }, monthly: { number: 300_000 }, years: { option_value: 5 },
  loss: { option_value: 2 }, reaction: { option_value: 2 }, priority: { option_value: 2 },
  tendency: { option_value: "위험중립형" }, universe: { option_value: ["SP500"] }, holdings: { option_value: 5 }, strategy: { option_value: "recommended" },
}
async function answerAll(s: MockService, c: ProposedProfileChat, until?: string): Promise<ProposedProfileChat> {
  while (c.question && c.question.id !== until) c = await s.answerProfileChat(c.chat_id, { question_id: c.question.id, ...PATH[c.question.id] })
  return c
}

describe("대화형 초기 투자조건 · 목업 규칙", () => {
  it("인사와 첫 질문으로 시작하고, 초안은 기본값으로 채워져 있다", async () => {
    const c = await mock().startProfileChat()
    expect(c).toMatchObject({ state: "asking", progress: { done: 0, total: CHAT_QUESTIONS.length }, question: { id: "purpose", kind: "choice" }, asked_fields: [] })
    expect(c.messages.map((m) => m.role)).toEqual(["bot", "bot"])
    expect(validateProfile(c.draft)).toEqual({})
  })
  it("끝까지 답하면 요약 단계가 되고, 초안은 답을 반영해 폼 검사를 통과한다", async () => {
    const s = mock()
    const c = await answerAll(s, await s.startProfileChat())
    expect(c).toMatchObject({ state: "review", question: null, progress: { done: CHAT_QUESTIONS.length } })
    const d = c.draft
    expect(d.capital).toMatchObject({ initial_amount: 10_000_000, monthly_contribution: 300_000, currency: "KRW" })
    expect(d.horizon).toMatchObject({ purpose: "wealth_growth", target_years: 5 })
    expect(d.diagnosis).toMatchObject({ answers: { loss: 2, reaction: 2, priority: 2 }, computed_tendency: "위험중립형", final_tendency: "위험중립형" })
    expect(d.risk).toMatchObject({ risk_tolerance: "moderate", max_drawdown_tolerance: 0.2, loss_reaction: "hold" })
    expect(d.constraints).toMatchObject({ universe: ["SP500"], num_holdings: { target: 5, min: 4, max: 6 }, max_weight_per_stock: 0.25 })
    expect(d.strategy_preference).toEqual({ template: "quality", baseline_weighting: "equal_weight", use_news_tilt: true })  // 위험중립형 추천 예시
    expect(validateProfile(d)).toEqual({})
    expect(c.asked_fields).toEqual(expect.arrayContaining(["capital.initial_amount", "capital.monthly", "tendency", "constraints.universe", "strategy.template", "strategy.weighting"]))
    expect(c.asked_fields).not.toContain("risk.benchmark")  // 묻지 않은 항목은 기본값
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
    expect(r.progress.done).toBe(CHAT_QUESTIONS.length - 1)
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
    expect(r).toMatchObject({ state: "asking", question: { id: "amount" }, progress: { done: CHAT_QUESTIONS.length - 1 } })
    expect(r.messages.filter((m) => m.role === "user")).toHaveLength(1)  // 뒤의 말풍선은 지금 질문에 답할 때까지 숨긴다
    expect(r.messages.at(-1)?.text_ko).toMatch(/뒤에 답한 9개는 그대로/)
    expect(r.draft.constraints.universe).toEqual(["SP500"])               // 뒤의 답은 초안에 남아 있다
    const back = await s.answerProfileChat(c.chat_id, { question_id: "amount", option_value: 30_000_000 })
    expect(back).toMatchObject({ state: "review", draft: { capital: { initial_amount: 30_000_000, monthly_contribution: 300_000 } } })
    expect(back.messages.filter((m) => m.role === "user")).toHaveLength(CHAT_QUESTIONS.length)
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
    expect(await screen.findByRole("heading", { level: 1, name: "대화로 기본 투자조건을 정해요" }, { timeout: 5000 })).toBeInTheDocument()
    await pick(/^자산 증식/)
    await pick(/^1,000만원/)
    await pick(/^추가 투자 없음/)
    await pick(/^5년/)
    await pick(/^약 20% 하락까지/)
    await pick(/^계획을 유지합니다/)
    await pick(/^균형/)
    await pick(/^위험중립형 \(진단 결과\)/)
    await pick(/^S&P 500/)
    await pick(/^선택 완료 \(1\)/)
    await pick(/^10개/)
    await pick(/^추천:/)
    expect(await screen.findByRole("heading", { name: "이렇게 정리했어요" }, { timeout: 5000 })).toBeInTheDocument()
    expect(screen.getByRole("progressbar", { name: "답한 질문" })).toHaveAttribute("aria-valuenow", String(CHAT_QUESTIONS.length))
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
    expect(await screen.findByRole("heading", { level: 1, name: "대화로 기본 투자조건을 정해요" }, { timeout: 5000 })).toBeInTheDocument()
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
    expect(await screen.findByRole("heading", { level: 1, name: "대화로 기본 투자조건을 정해요" }, { timeout: 5000 })).toBeInTheDocument()
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
