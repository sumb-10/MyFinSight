import { describe, expect, it } from "vitest"
import type { PaperDetail, PaperRebalance } from "../../api/types"
import { freshRebalance, lastRebalance, nextRebalanceText, shownTrades } from "./rebalance"

const rb = (over: Partial<PaperRebalance>): PaperRebalance => ({ date: "2026-01-02", seq: 0, kind: "rebalance", before_weights: {}, target_weights: {}, applied_weights: {}, trades: [{ ticker: "MU", side: "buy", shares: 1, price: 100, value_usd: 100 }], commission_usd: 0.05, turnover: 0.1, fallback: false, skipped: false, ...over })
const detail = (rebalances: PaperRebalance[]) => ({ rebalances }) as unknown as PaperDetail

describe("다음 리밸런싱 시점 (서버 규칙: 시작일이 속한 기간부터 count 기간마다 기간 첫 거래일)", () => {
  it("매월·분기·반기·매년", () => {
    expect(nextRebalanceText({ count: 1, unit: "1m" }, "2026-06-01", "2026-10-30")).toBe("2026년 11월 첫 거래일")
    expect(nextRebalanceText({ count: 1, unit: "1m" }, "2026-06-01", "2026-12-15")).toBe("2027년 1월 첫 거래일")  // 해 넘김
    expect(nextRebalanceText({ count: 1, unit: "1q" }, "2026-02-10", "2026-03-31")).toBe("2026년 4월 첫 거래일")
    expect(nextRebalanceText({ count: 1, unit: "1q" }, "2026-02-10", "2026-04-01")).toBe("2026년 7월 첫 거래일")  // 4월 첫 거래일에 이미 했다
    expect(nextRebalanceText({ count: 1, unit: "6m" }, "2026-08-03", "2026-10-30")).toBe("2027년 1월 첫 거래일")
    expect(nextRebalanceText({ count: 1, unit: "1y" }, "2026-08-03", "2026-10-30")).toBe("2027년 1월 첫 거래일")
  })
  it("두 기간 이상 간격은 시작 기간부터 센다 (2개월마다: 6월 시작 → 8월·10월·12월)", () => {
    expect(nextRebalanceText({ count: 2, unit: "1m" }, "2026-06-01", "2026-09-30")).toBe("2026년 10월 첫 거래일")
    expect(nextRebalanceText({ count: 2, unit: "1m" }, "2026-06-01", "2026-10-30")).toBe("2026년 12월 첫 거래일")
    expect(nextRebalanceText({ count: 2, unit: "1m" }, "2026-06-01", null)).toBe("2026년 8월 첫 거래일")  // 평가 기록이 아직 없으면 시작일 기준
  })
  it("2주 단위는 거래일 수로, 리밸런싱이 없으면 null", () => {
    expect(nextRebalanceText({ count: 1, unit: "2w" }, "2026-06-01", "2026-10-30")).toBe("마지막 리밸런싱 뒤 10거래일째")
    expect(nextRebalanceText({ count: 0, unit: "1m" }, "2026-06-01", "2026-10-30")).toBeNull()
  })
})

describe("확인하지 않은 리밸런싱", () => {
  const rebs = [rb({ kind: "initial", seq: 0 }), rb({ kind: "contribution", seq: 0, date: "2026-02-01" }), rb({ seq: 1, date: "2026-02-02" }), rb({ seq: 2, date: "2026-03-02", skipped: true, trades: [] })]
  it("마지막으로 실제 거래한 정기 리밸런싱만 본다 (적립 매수·건너뜀 제외)", () => {
    expect(lastRebalance(detail(rebs))?.date).toBe("2026-02-02")
    expect(shownTrades(detail(rebs))?.date).toBe("2026-02-02")
    expect(shownTrades(detail(rebs.slice(0, 2)))?.kind).toBe("initial")  // 아직 리밸런싱 전이면 최초 매수
  })
  it("확인한 번호보다 크면 알리고, 확인 기록이 없거나 건너뛴 리밸런싱만 늘었으면 알리지 않는다", () => {
    expect(freshRebalance(detail(rebs), 0)?.seq).toBe(1)
    expect(freshRebalance(detail(rebs), 1)).toBeNull()  // seq 2 는 중지 중 건너뜀(거래 없음)이라 알릴 것이 없다
    expect(freshRebalance(detail(rebs), undefined)).toBeNull()
  })
})
