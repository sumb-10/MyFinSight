import { describe, expect, it } from "vitest"
import { fireEvent, render, screen, within } from "@testing-library/react"
import { TutorialScreen } from "./TutorialScreen"
import { TOUR_STEPS } from "./steps"
import { loadTutorialDoc } from "./tutorialService"
import { parseRoute, routePath } from "../../app/router"

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

  it("예시 데이터 띠를 보여 주고, 다음/이전으로 단계를 옮기며 n/7 을 표시한다", async () => {
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

  it("둘러보기 중에는 모의투자 시작·조건 수정 같은 쓰기 동작을 막는다", async () => {
    show()
    await tour()
    fireEvent.click(screen.getByRole("button", { name: "건너뛰기" }))
    expect(screen.getByRole("button", { name: /모의투자 시작/ })).toBeDisabled()
    expect(screen.getByRole("button", { name: /조건 수정 요청/ })).toBeDisabled()
  }, 20000)
})
