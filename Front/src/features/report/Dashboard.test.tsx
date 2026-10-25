import { describe, expect, it } from "vitest"
import { render, screen } from "@testing-library/react"
import { AllocationMini, KpiRow, ValidationMini } from "./Dashboard"

describe("Dashboard parts", () => {
  it("배분 미니: 상위 8 + 기타 + 현금으로 묶고 합이 100% 다", () => {
    const items = Array.from({ length: 11 }, (_, i) => ({ ticker: `T${i}`, name: "", sector: "", weight: (11 - i) / 72, usd: 0, krw: 0 }))
    const total = items.reduce((s, x) => s + x.weight, 0)
    render(<AllocationMini a={{ basis: "backtest", basis_ko: "선택안", items, cash_weight: 1 - total, initial_amount_usd: 1000, fx_rate: 1400 }} onMore={() => {}} />)
    expect(screen.getByText("기타 3종목")).toBeInTheDocument()
    expect(screen.getByText("현금")).toBeInTheDocument()
    expect(screen.getAllByRole("row")).toHaveLength(10)  // 8 + 기타 + 현금
    const pct = screen.getAllByRole("cell").filter((c) => /%$/.test(c.textContent ?? "")).map((c) => parseFloat((c.textContent ?? "0").replace("%", "")))
    expect(pct.reduce((s, x) => s + x, 0)).toBeCloseTo(100, 0)
  })
  it("KPI 타일은 비교지수 값을 함께 보여 준다", () => {
    render(<KpiRow kpis={[{ id: "cagr", label_ko: "CAGR", value: 0.1234, format: "pct", benchmark_value: 0.0987, benchmark_label_ko: "SPY 매수보유" }, { id: "mdd", label_ko: "MDD", value: -0.2, format: "pct", note_ko: "손실 감내 35%", benchmark_value: null }]} />)
    expect(screen.getByText("+12.34%")).toBeInTheDocument()
    expect(screen.getByText("SPY 매수보유 +9.87%")).toBeInTheDocument()
    expect(screen.getByText("손실 감내 35%")).toBeInTheDocument()
  })
  it("검증 미니: 규칙 목록이 있으면 한 줄씩, 없으면 수와 미통과 규칙 이름", () => {
    const { unmount } = render(<ValidationMini v={{ n_pass: 3, n_warn: 2, n_fail: 5, chosen_status: "fail", failed_rules_ko: ["최대낙폭 한도", "목표 수익률"] }} onMore={() => {}} />)
    expect(screen.getByText("통과 3")).toBeInTheDocument(); expect(screen.getByText("미통과 5")).toBeInTheDocument()
    expect(screen.getByText("최대낙폭 한도")).toBeInTheDocument()
    unmount()
    render(<ValidationMini v={{ n_pass: 1, n_warn: 0, n_fail: 0, chosen_status: "pass", failed_rules_ko: [], rules_ko: [{ rule: "R1", name_ko: "최대낙폭", level: "hard", status: "pass", message_ko: "최대낙폭 22.5% ≤ 허용 25% (같은 기간 SPY 18.8%)" }, { rule: "R2", name_ko: "목표수익", level: "soft", status: "warn", message_ko: "3년 구간 500개 중 40%가 목표 달성" }], info_notes_ko: ["투자 40%, 현금 60% — 상한 때문에 돈을 다 넣지 못했습니다"], tolerance_note_ko: "검증 기준 24% (입력 30%, 손실 시 매도 성향 ×0.8)" }} onMore={() => {}} />)
    expect(screen.getByText("최대낙폭")).toBeInTheDocument(); expect(screen.getByText(/같은 기간 SPY/)).toBeInTheDocument()
    expect(screen.getByText("주의")).toBeInTheDocument(); expect(screen.getByText(/현금 60%/)).toBeInTheDocument(); expect(screen.getByText(/입력 30%/)).toBeInTheDocument()
  })
})
