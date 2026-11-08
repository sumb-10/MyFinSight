import { describe, expect, it } from "vitest"
import type { ProposedChatAnswer, ProposedProfileChat } from "../api/proposed"
import { validateProfile } from "../features/profile/validate"
import { CHAT_QUESTIONS, holdingsFor } from "./data/profileChat"
import { MockService } from "./services/MockService"

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
    expect(c.asked_fields).toEqual(expect.arrayContaining(["capital.initial_amount", "constraints.universe", "strategy_preference"]))
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
  it("「고치기」는 그 질문부터 다시 묻고 뒤의 답은 지운다", async () => {
    const s = mock()
    const c = await answerAll(s, await s.startProfileChat())
    const r = await s.rewindProfileChat(c.chat_id, "amount")
    expect(r).toMatchObject({ state: "asking", question: { id: "amount" }, progress: { done: 1 } })
    expect(r.draft.capital.initial_amount).toBe(10_000_000)  // 기본값으로 돌아감
    expect(r.messages.filter((m) => m.role === "user")).toHaveLength(1)
  })
  it("종목 수에 맞춰 범위와 종목당 상한을 같이 정한다", () => {
    expect(holdingsFor(10)).toMatchObject({ num_holdings: { target: 10, min: 8, max: 12 }, max_weight_per_stock: 0.15 })
    expect(holdingsFor(3)).toMatchObject({ num_holdings: { min: 2, max: 4 }, max_weight_per_stock: 0.5, max_weight_per_sector: 0.5 })
  })
})
