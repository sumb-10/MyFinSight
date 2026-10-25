import { describe, expect, it } from "vitest"
import { date, datetime, fmt, fx, ko, pct, usd, weight } from "./format"

describe("format", () => {
  it("비율은 분수 입력을 퍼센트로 보여 준다", () => {
    expect(pct(0.1234)).toBe("+12.34%")  // 수익률: 2자리 + 부호
    expect(weight(0.0533)).toBe("5.3%")  // 비중: 1자리
    expect(pct(-0.2883)).toBe("-28.83%")
    expect(pct(0)).toBe("0.00%")
  })
  it("금액과 환율", () => {
    expect(usd(1234.5)).toMatch(/1,234/)
    expect(fmt(50_399_033, "krw")).toMatch(/50,399,033/)
    expect(fx(1339.08, "2026-10-08")).toBe("1 USD = 1,339.08 KRW (2026-10-08)")
  })
  it("날짜와 라벨", () => {
    expect(date("2026-10-24T21:00:00+09:00")).toBe("2026-10-24")
    expect(datetime("2026-10-24T21:05:00+09:00")).toBe("2026-10-24 21:05")
    expect(date(null)).toBe("–")
    expect(ko("1q")).toBe("분기")
    expect(ko("revision")).toBe("수정안")
    expect(ko("unknown_key")).toBe("unknown_key")
  })
})
