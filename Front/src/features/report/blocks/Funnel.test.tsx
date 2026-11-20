import { describe, expect, it } from "vitest"
import { fireEvent, render, screen } from "@testing-library/react"
import { dropParens, Funnel } from "./blocks"

describe("선정 과정", () => {
  it("단계 이름의 괄호 설명은 (괄호 안 괄호까지) 모두 빼고, 선정 지표 설명은 제목 옆 ? 에 둔다", () => {
    expect(dropParens("선정 지표(모멘텀(최근 12개월 수익률, 직전 1개월 제외)) 계산 가능·자격선 안 108개 + 필수 포함 4개(그중 지표 없음·자격선 밖 1개: NOW(자격선 밖 -18.0%))")).toBe("선정 지표 계산 가능·자격선 안 108개 + 필수 포함 4개")
    expect(dropParens("투자 가능 종목 (SP500 ∪ NASDAQ100)")).toBe("투자 가능 종목")
    render(<Funnel b={{ type: "funnel", items: [{ label_ko: "투자 가능 종목 (SP500 ∪ NASDAQ100)", count: 518 }, { label_ko: "최종 선정 (2026-11-10)", count: 8 }], help_ko: "선정 지표는 투자할 기업을 고르기 위한 지표입니다. 모멘텀은 …" }} />)
    expect(screen.getByText("투자 가능 종목")).toBeInTheDocument(); expect(screen.getByText("최종 선정")).toBeInTheDocument()
    expect(screen.queryByText(/\(/)).toBeNull()
    fireEvent.click(screen.getByRole("button", { name: "선정 지표 설명 보기" }))
    expect(screen.getByRole("dialog", { name: "선정 지표 설명" })).toHaveTextContent("선정 지표는 투자할 기업을 고르기 위한 지표입니다")
  })
})
