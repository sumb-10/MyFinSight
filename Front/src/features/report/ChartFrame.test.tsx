import { describe, expect, it } from "vitest"
import { fireEvent, render, screen } from "@testing-library/react"
import { ChartFrame } from "./ChartFrame"

describe("ChartFrame", () => {
  it("캡션을 보여 주고 '표로 보기'로 전환한다", () => {
    render(<ChartFrame title="누적 수익률" caption="2023-01-02 ~ 2025-12-31 · 시작 = 100" table={{ columns: [{ key: "date", label_ko: "날짜" }, { key: "v", label_ko: "값", format: "index" }], rows: [{ date: "2023-01-02", v: 100 }, { date: "2025-12-31", v: 131.25 }] }}><svg data-testid="chart" /></ChartFrame>)
    expect(screen.getByText(/시작 = 100/)).toBeInTheDocument()
    expect(screen.getByRole("img", { name: "누적 수익률" })).toBeInTheDocument()
    fireEvent.click(screen.getByRole("button", { name: "표로 보기" }))
    expect(screen.getByText("131.3")).toBeInTheDocument()
    expect(screen.queryByTestId("chart")).toBeNull()
    fireEvent.click(screen.getByRole("button", { name: "차트로 보기" }))
    expect(screen.getByTestId("chart")).toBeInTheDocument()
  })
})
