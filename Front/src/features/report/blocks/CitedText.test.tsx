import { render } from "@testing-library/react"
import { describe, expect, it } from "vitest"
import { CitationContext, CitedText, Paragraphs, splitLeadTitle } from "./blocks"

const ctx = { onCite: () => {}, label: (id: string) => (id === "calc:a" ? "1" : "2") }

describe("CitedText tight (「선택 근거 자세히 보기」 전용, 2026-11-16)", () => {
  it("출처 앞·사이 공백을 빼고, 글자 크기는 안쪽 span 에 둔다 (전역 button { font: inherit } 이 버튼 크기를 덮어 줄 간격이 벌어졌다)", () => {
    const { container } = render(<CitationContext.Provider value={ctx}><p><CitedText tight text="높았습니다 [calc:a] [calc:b]. 다음 문장" /></p></CitationContext.Provider>)
    const p = container.querySelector("p")!
    expect(p.textContent).toBe("높았습니다[1][2]. 다음 문장")
    const btn = p.querySelector("button")!
    expect(btn.className).not.toContain("align-super")
    expect(btn.querySelector("span")!.className).toContain("text-[11px]")
  })
  it("다른 섹션(기본)은 예전 모양 그대로", () => {
    const { container } = render(<CitationContext.Provider value={ctx}><p><CitedText text="높았습니다 [calc:a]." /></p></CitationContext.Provider>)
    expect(container.querySelector("p")!.textContent).toBe("높았습니다 [1].")
    expect(container.querySelector("button")!.className).toContain("align-super")
  })
})

describe("소제목 줄 (「선택 근거 자세히 보기」 종목 변경 문단)", () => {
  it("짧고 마침표 없는 첫 줄만 소제목으로, 본문 문장은 그대로", () => {
    expect(splitLeadTitle("2026년 11월 10일 분석 기준일에 빠진 종목\nA는 빠졌습니다.")).toEqual(["2026년 11월 10일 분석 기준일에 빠진 종목", "A는 빠졌습니다."])
    expect(splitLeadTitle("한 문장입니다.\n다음 줄")).toBeNull()
    expect(splitLeadTitle("줄바꿈 없는 문단")).toBeNull()
    const { container } = render(<Paragraphs tight items={["2026년 11월 10일 분석 기준일에 빠진 종목\nA는 빠졌습니다."]} />)
    expect(container.querySelector("strong")!.textContent).toBe("2026년 11월 10일 분석 기준일에 빠진 종목")
    const { container: c2 } = render(<Paragraphs items={["2026년 11월 10일 분석 기준일에 빠진 종목\nA는 빠졌습니다."]} />)
    expect(c2.querySelector("strong")).toBeNull()  // 다른 섹션은 그대로
  })
})

describe("비중 결정 설명 정리 (2026-11-16)", () => {
  it("'(뷰 없음, 재배분)'·'(그날 뷰 없음, 재배분)' 은 화면에서 새 이름으로, 저장된 글은 그대로 읽는다", async () => {
    const { relabelNoView } = await import("./blocks")
    expect(relabelNoView("NOW +0.2%p (뷰 없음, 재배분), MU (그날 뷰 없음, 재배분)")).toBe("NOW +0.2%p (다른 종목 조정에 따른 비중 변화), MU (다른 종목 조정에 따른 비중 변화)")
  })
  it("tight 문단은 줄 앞 공백·탭과 연속 공백을 하나로 (같은 왼쪽 기준선), 줄바꿈은 그대로", async () => {
    const { tidySpaces } = await import("./blocks")
    expect(tidySpaces("첫 줄입니다.\n\t  둘째 줄   입니다.  ")).toBe("첫 줄입니다.\n둘째 줄 입니다.")
  })
})
