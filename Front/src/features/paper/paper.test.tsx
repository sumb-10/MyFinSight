import { describe, expect, it } from "vitest"
import { render, screen } from "@testing-library/react"
import { RevisionCard } from "../analysis/RevisionCard"

describe("RevisionCard", () => {
  it("반영한 변경과 반영하지 못한 요청을 나눠 보여 준다", () => {
    render(<RevisionCard rev={{ text: "NVDA는 빼 주세요. 리밸런싱은 매월로", summary_ko: "요약", frozen_fields: [], unsupported_ko: ["수정안 비교에서는 원안과 같은 조건을 유지합니다"],
      changes: [{ field: "constraints.exclude_tickers", label_ko: "제외 종목", value: ["NVDA"], base_value: [], supported: true, reason_ko: "엔비디아 제외" },
        { field: "capital.initial_amount", label_ko: "투자금", value: 1, base_value: 100, supported: false, note_ko: "원안과 같은 조건을 유지" }] }} />)
    expect(screen.getByText("반영한 변경")).toBeInTheDocument()
    expect(screen.getByText(/제외 종목/)).toBeInTheDocument()
    expect(screen.getByText(/반영하지 못한 요청/)).toBeInTheDocument()
    expect(screen.getAllByText(/원안과 같은 조건/).length).toBeGreaterThan(0)
  })
})
