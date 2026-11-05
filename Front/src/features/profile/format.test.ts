import { describe, expect, it } from "vitest"
import { koUnits, money, monthlyText, pctText, rebalanceText, usdFloor, yearsText } from "./format"

describe("내 투자조건 값 표시", () => {
  it("원화는 억·만 단위로, 나머지를 버리지 않는다", () => {
    expect(money(500_000, "KRW")).toBe("50만원")
    expect(money(10_000_000, "KRW")).toBe("1,000만원")
    expect(money(150_000_000, "KRW")).toBe("1억 5,000만원")
    expect(money(123_456_789, "KRW")).toBe("1억 2,345만 6,789원")
    expect(money(12_345, "KRW")).toBe("1만 2,345원")
    expect(money(5_000, "KRW")).toBe("5,000원")
    expect(koUnits(0)).toBe("0")
  })
  it("USD 는 통화 이름을 붙여 원화와 구분한다", () => {
    expect(money(10_000, "USD")).toBe("10,000 USD")
    expect(money(1234.5, "USD")).toBe("1,234.5 USD")
    expect(usdFloor(2e9)).toBe("20억 USD 이상")
    expect(usdFloor(0)).toBe("제한 없음")
  })
  it("비율은 불필요한 소수점만 뺀다", () => {
    expect(pctText(0.25)).toBe("25%")
    expect(pctText(0.15)).toBe("15%")
    expect(pctText(0.125)).toBe("12.5%")
    expect(yearsText(1.5)).toBe("1.5년")
  })
  it("월 추가 투자와 리밸런싱 주기를 저장 값대로 쓴다", () => {
    expect(monthlyText({ initial_amount: 1, currency: "KRW", monthly_contribution: 500_000, contribution_day: 25 })).toBe("매월 50만원 · 25일")
    expect(monthlyText({ initial_amount: 1, currency: "USD", monthly_contribution: 0, contribution_day: 25 })).toBe("없음")
    expect(rebalanceText({ count: 1, unit: "1m" })).toBe("매월 1회")
    expect(rebalanceText({ count: 2, unit: "1m" })).toBe("2개월마다 1회")
    expect(rebalanceText({ count: 1, unit: "1q" })).toBe("분기마다 1회")
    expect(rebalanceText({ count: 2, unit: "1q" })).toBe("반기마다 1회")
    expect(rebalanceText({ count: 1, unit: "1y" })).toBe("매년 1회")
    expect(rebalanceText({ count: 2, unit: "2w" })).toBe("4주마다 1회")
    expect(rebalanceText({ count: 0, unit: "1q" })).toMatch(/^없음/)
  })
})
