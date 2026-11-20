import { render, screen } from "@testing-library/react"
import { describe, expect, it } from "vitest"
import { splitThemeScope, ThemeScope } from "./ThemeScope"

describe("투자 테마 「어떤 기업이 해당하는가」 포함/넣지 않음 (2026-11-16)", () => {
  it("포함 · 넣지 않음 · 덧붙인 설명을 나눈다", () => {
    expect(splitThemeScope("포함: 미국에 본사를 둔 기업 중 AI가 주력 사업이 아닌 모든 업종의 기업. 넣지 않음: AI 사업이 주력인 기업과 본사가 미국이 아닌 기업. 업종이 다르다는 사실만으로 보완 효과가 보장되지는 않습니다.")).toEqual({
      include: "미국에 본사를 둔 기업 중 AI가 주력 사업이 아닌 모든 업종의 기업.",
      exclude: "AI 사업이 주력인 기업과 본사가 미국이 아닌 기업.",
      note: "업종이 다르다는 사실만으로 보완 효과가 보장되지는 않습니다.",
    })
    expect(splitThemeScope("포함: A 기업. 넣지 않음: B 기업, C 기업.")).toEqual({ include: "A 기업.", exclude: "B 기업, C 기업.", note: null })
  })
  it("틀이 다르면 원문 그대로", () => {
    expect(splitThemeScope("AI 반도체 기업")).toBeNull()
    render(<ThemeScope text="AI 반도체 기업" />)
    expect(screen.getByText("AI 반도체 기업")).toBeInTheDocument()
  })
  it("포함과 넣지 않음이 이름표가 붙은 별도 줄로", () => {
    const { container } = render(<ThemeScope text="포함: A 기업. 넣지 않음: B 기업." />)
    expect([...container.querySelectorAll("dt")].map((x) => x.textContent)).toEqual(["포함", "넣지 않음"])
    expect([...container.querySelectorAll("dd")].map((x) => x.textContent)).toEqual(["A 기업.", "B 기업."])
  })
})
