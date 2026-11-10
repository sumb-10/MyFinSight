import { beforeEach, describe, expect, it } from "vitest"
import { fireEvent, render, screen, waitFor, within } from "@testing-library/react"
import { TutorialScreen } from "./TutorialScreen"
import { TOUR_STEPS } from "./steps"
import { loadTutorialDoc } from "./tutorialService"
import { parseRoute, routePath } from "../../app/router"
import { liftSticky, popoverStyle } from "./Coachmark"
import { ServiceContext } from "../../app/providers"
import type { AnalysisService } from "../../api/service"
import { ReportList } from "../report/ReportList"
import { EXAMPLE_ROW, resetExampleMemory } from "./exampleReport"

beforeEach(() => { try { window.localStorage.clear() } catch { /* ignore */ } resetExampleMemory() })

describe("목록의 예시 리포트", () => {
  const svc = { mode: "api", listReports: async () => [], listRuns: async () => [], listPaper: async () => [] } as unknown as AnalysisService
  const list = () => render(<ServiceContext.Provider value={svc}><ReportList /></ServiceContext.Provider>)

  it("분석 리포트 목록에는 예시 리포트를 두지 않는다 (서버 리포트가 없으면 빈 화면, 되돌리기 링크도 없다)", async () => {
    list()
    expect(await screen.findByText("아직 리포트가 없습니다")).toBeInTheDocument()
    expect(screen.queryByText(EXAMPLE_ROW.name)).toBeNull()
    expect(screen.queryByRole("button", { name: /예시 리포트 다시 보이기/ })).toBeNull()
  })

  it("예시 리포트 화면: 코치마크 없이 열리고, 띠에서 둘러보기를 시작하며, 더보기에 「리포트 삭제」가 있다", async () => {
    render(<TutorialScreen load={loadTutorialDoc} startTour={false} />)
    await screen.findByRole("button", { name: /모의투자 시작/ }, { timeout: 10000 })
    expect(screen.queryByTestId("coachmark")).toBeNull()
    expect(screen.getByRole("note")).toHaveTextContent("예시 리포트입니다")
    expect(screen.getByRole("heading", { level: 1 })).toHaveTextContent(EXAMPLE_ROW.name)  // 목록과 같은 이름
    expect(document.body.textContent).not.toMatch(/목업/)  // 예시 화면에는 「목업」 대신 「예시」
    expect(screen.getByRole("button", { name: /모의투자 시작/ })).toBeDisabled()
    fireEvent.click(screen.getByRole("button", { name: /더보기/ }))
    fireEvent.click(screen.getByRole("menuitem", { name: /리포트 삭제/ }))
    expect(screen.getByRole("dialog", { name: "예시 리포트를 목록에서 지울까요?" })).toBeInTheDocument()
    fireEvent.click(screen.getByRole("button", { name: "취소" }))
    fireEvent.click(screen.getByRole("button", { name: "리포트 보는 법 둘러보기" }))
    expect(screen.getByRole("dialog", { name: TOUR_STEPS[0].title })).toBeInTheDocument()
  }, 20000)
})

const show = () => render(<TutorialScreen load={loadTutorialDoc} />)
const tour = async () => {  // 예시 리포트가 다 그려진 뒤의 첫 단계 말풍선 (부하가 높으면 리포트가 늦게 그려진다)
  await screen.findByRole("button", { name: /모의투자 시작/ }, { timeout: 10000 })
  return screen.findByRole("dialog", { name: TOUR_STEPS[0].title })
}

describe("리포트 보는 법 둘러보기", () => {
  it("주소 #/tutorial", () => {
    expect(parseRoute("#/tutorial")).toEqual({ page: "tutorial" })
    expect(routePath({ page: "tutorial" })).toBe("#/tutorial")
  })

  it("예시 데이터 띠를 보여 주고, 다음/이전으로 단계를 옮기며 n/전체를 표시한다", async () => {
    show()
    const d = await tour()
    expect(screen.getByRole("note")).toHaveTextContent("예시 데이터로 보는 화면입니다")
    expect(d).toHaveTextContent(`1/${TOUR_STEPS.length}`)
    expect(within(d).getByRole("button", { name: "이전" })).toBeDisabled()
    expect(document.activeElement).toBe(within(d).getByRole("button", { name: "다음" }))  // 단계마다 주 버튼에 포커스
    fireEvent.click(within(d).getByRole("button", { name: "다음" }))
    const d2 = screen.getByRole("dialog", { name: TOUR_STEPS[1].title })
    expect(d2).toHaveTextContent(`2/${TOUR_STEPS.length}`)
    fireEvent.click(within(d2).getByRole("button", { name: "이전" }))
    expect(screen.getByRole("dialog", { name: TOUR_STEPS[0].title })).toBeInTheDocument()
    // 단계 대상은 모두 리포트 화면에 있다
    for (const s of TOUR_STEPS) expect(document.querySelector(`[data-tour="${s.target}"]`), s.target).not.toBeNull()
  }, 20000)

  it("종목별 투자 금액 단계는 금액 옆 주식 수 칸까지 안내하고, 따로 펼치는 「예상 매수 주문」은 없다", async () => {
    show()
    await tour()
    expect(document.querySelector('[data-tour="orders"]')).toBeNull()
    const i = TOUR_STEPS.findIndex((s) => s.target === "allocation-list")
    for (let n = 0; n < i; n++) fireEvent.click(screen.getByRole("button", { name: "다음" }))
    expect(screen.getByRole("dialog", { name: TOUR_STEPS[i].title })).toHaveTextContent(/주식 수/)
    const list = document.querySelector<HTMLElement>('[data-tour="allocation-list"]')!
    expect(within(list).getByText("주식 수")).toBeInTheDocument()
    expect(within(within(list).getByRole("list", { name: "종목별 목표 배분액" })).getAllByText(/^[\d,.]+주$/).length).toBeGreaterThan(0)
  }, 20000)

  it("용어 단계는 제목을 바꾸고 ? 도움말을 예시로 열며, 「투자 용어 설명」도 함께 비춘 뒤 떠나면 닫는다", async () => {
    show()
    await tour()
    const i = TOUR_STEPS.findIndex((s) => s.target === "term-help")
    expect(i).toBe(2)
    for (let n = 0; n < i; n++) fireEvent.click(screen.getByRole("button", { name: "다음" }))
    expect(TOUR_STEPS[i].title).toBe("용어 설명")
    expect(TOUR_STEPS[i].also).toEqual(["glossary"])
    expect(screen.getByRole("dialog", { name: TOUR_STEPS[i].title })).toHaveTextContent(/용어 옆 \? 를 누르면/)
    const help = document.querySelector<HTMLElement>('[data-tour="term-help"]')!
    await waitFor(() => expect(within(help).getByRole("button", { name: /설명 보기/ })).toHaveAttribute("aria-expanded", "true"))
    expect(help.querySelector('[role="dialog"]')).not.toBeNull()
    fireEvent.click(screen.getByRole("button", { name: "다음" }))
    expect(help.querySelector('[role="dialog"]')).toBeNull()
  }, 20000)

  it("고정 줄 안의 요소를 비출 때는 줄을 위 끝에서 띄우고, 끝나면 되돌린다", () => {
    const bar = document.createElement("div"); bar.style.position = "sticky"; bar.style.top = "0px"
    const btn = document.createElement("button"); bar.appendChild(btn); document.body.appendChild(bar)
    const undo = liftSticky(btn)!
    expect(bar.style.top).toBe("16px")
    undo()
    expect(bar.style.top).toBe("0px")
    bar.remove()
    expect(liftSticky(document.createElement("button"))).toBeNull()
  })

  it("마지막 단계에서 「마치기」, 끝나면 「내 분석 시작하기」가 남는다", async () => {
    show()
    await tour()
    for (let i = 0; i < TOUR_STEPS.length - 1; i++) fireEvent.click(screen.getByRole("button", { name: "다음" }))
    expect(screen.getByRole("dialog")).toHaveTextContent(`${TOUR_STEPS.length}/${TOUR_STEPS.length}`)
    fireEvent.click(screen.getByRole("button", { name: "마치기" }))
    expect(screen.queryByTestId("coachmark")).toBeNull()
    expect(screen.getByText(/둘러보기를 마쳤습니다/)).toBeInTheDocument()
    expect(screen.getByRole("button", { name: /내 분석 시작하기/ })).toBeInTheDocument()
    fireEvent.click(screen.getByRole("button", { name: "처음부터 다시 보기" }))
    expect(screen.getByRole("dialog", { name: TOUR_STEPS[0].title })).toBeInTheDocument()
  }, 20000)

  it("건너뛰기·ESC 로 닫힌다", async () => {
    show()
    fireEvent.click(within(await tour()).getByRole("button", { name: "건너뛰기" }))
    expect(screen.queryByTestId("coachmark")).toBeNull()
    fireEvent.click(screen.getByRole("button", { name: "처음부터 다시 보기" }))
    fireEvent.keyDown(window, { key: "Escape" })
    expect(screen.queryByTestId("coachmark")).toBeNull()
  }, 20000)

  it("둘러보기 중에는 사용자 스크롤을 막고, 끝나면 원래대로 푼다", async () => {
    show()
    await tour()
    const html = document.documentElement
    expect(html.style.overflow).toBe("hidden")
    const wheel = new WheelEvent("wheel", { cancelable: true, bubbles: true })
    window.dispatchEvent(wheel)
    expect(wheel.defaultPrevented).toBe(true)
    const pgdn = new KeyboardEvent("keydown", { key: "PageDown", cancelable: true, bubbles: true })
    window.dispatchEvent(pgdn)
    expect(pgdn.defaultPrevented).toBe(true)
    fireEvent.click(screen.getByRole("button", { name: "다음" }))
    expect(html.style.overflow).toBe("hidden")  // 단계를 넘겨도 잠금 유지
    fireEvent.click(screen.getByRole("button", { name: "건너뛰기" }))
    expect(html.style.overflow).toBe("")
    const wheel2 = new WheelEvent("wheel", { cancelable: true, bubbles: true })
    window.dispatchEvent(wheel2)
    expect(wheel2.defaultPrevented).toBe(false)  // 완료 화면에서는 스크롤 가능
  }, 20000)

  it("큰 강조 영역(종목별 투자 금액)은 말풍선을 왼쪽에, 좁은 화면이면 기본 배치로", () => {
    expect(TOUR_STEPS.filter((s) => s.placement === "left").map((s) => s.target)).toEqual(["allocation-list"])
    const big = { top: 64, left: 272, width: 720, height: 860 }
    const left = popoverStyle(big, "left", 1440, 900)
    expect(left.side).toBe("left")
    expect((left.css.left as number) + (left.css.width as number)).toBeLessThanOrEqual(big.left)  // 강조 영역과 겹치지 않는다
    expect(popoverStyle({ ...big, left: 120 }, "left", 800, 900).side).not.toBe("left")  // 왼쪽 공간이 좁으면 폴백
    expect(popoverStyle({ top: 100, left: 300, width: 400, height: 120 }, undefined, 1440, 900).side).toBe("below")
  })

  it("둘러보기 중에는 모의투자 시작·조건 수정 같은 쓰기 동작을 막는다", async () => {
    show()
    await tour()
    fireEvent.click(screen.getByRole("button", { name: "건너뛰기" }))
    expect(screen.getByRole("button", { name: /모의투자 시작/ })).toBeDisabled()
    expect(screen.getByRole("button", { name: /조건 수정 요청/ })).toBeDisabled()
  }, 20000)
})
