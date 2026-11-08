import { afterEach, beforeAll, describe, expect, it, vi } from "vitest"
import { fireEvent, render, screen, waitFor } from "@testing-library/react"
import { Providers } from "../../app/providers"
import type { AnalysisService } from "../../api/service"
import { MockService } from "../../mocks/services/MockService"
import { fromProfile, OVERRIDE_LABELS, validate } from "../home/DetailConditions"
import { ClarifyScreen } from "./ClarifyScreen"
import { ConfirmScreen } from "./ConfirmScreen"
import { NOTE_BUTTON, NOTE_UNSENT, keepPendingNote, pendingNote } from "./flow"

// 질문·확인 화면 편의성 개선: 취소 확인, 보내지 않은 문장 이어받기, 「말로 보태기」 이름 통일, 시작 줄 고정, 라벨 통일, 0원 규칙.

beforeAll(() => { globalThis.ResizeObserver ??= class { observe() {} unobserve() {} disconnect() {} } as unknown as typeof ResizeObserver; Element.prototype.scrollIntoView = vi.fn() })
afterEach(() => { window.history.replaceState(null, "", "/"); keepPendingNote("mock_req_asking", ""); keepPendingNote("mock_req_ready", "") })

const mock = () => new MockService({ latencyMs: 0, persist: false })
const show = (svc: AnalysisService, ui: React.ReactNode) => render(<Providers service={svc}>{ui}</Providers>)

describe("질문 화면", () => {
  it("「취소하고 홈으로」는 한 번 더 확인하고, 「계속 답하기」면 요청을 그대로 둔다", async () => {
    const s = mock()
    show(s, <ClarifyScreen requestId="mock_req_asking" />)
    fireEvent.click(await screen.findByRole("button", { name: /취소하고 홈으로/ }, { timeout: 5000 }))
    expect(screen.getByRole("alertdialog", { name: "요청 취소 확인" })).toBeInTheDocument()
    fireEvent.click(screen.getByRole("button", { name: "계속 답하기" }))
    expect(screen.queryByRole("alertdialog")).toBeNull()
    expect((await s.getRequest("mock_req_asking")).status).not.toBe("cancelled")
    fireEvent.click(screen.getByRole("button", { name: /취소하고 홈으로/ }))
    fireEvent.click(screen.getByRole("button", { name: "요청 취소" }))
    await waitFor(() => expect(window.location.hash).toBe("#/home"))
    expect((await s.getRequest("mock_req_asking")).status).toBe("cancelled")
  })
  it("「말로 보태기」 버튼 이름이 확인 화면과 같고, 적은 문장은 요청별로 남는다", async () => {
    show(mock(), <ClarifyScreen requestId="mock_req_asking" />)
    fireEvent.change(await screen.findByRole("textbox", { name: "말로 조건 보태기" }, { timeout: 5000 }), { target: { value: "배당주 위주로" } })
    expect(screen.getByRole("button", { name: NOTE_BUTTON })).toBeInTheDocument()
    expect(screen.getByText(NOTE_UNSENT)).toBeInTheDocument()
    expect(pendingNote("mock_req_asking")).toBe("배당주 위주로")
    expect(pendingNote("mock_req_ready")).toBe("")
  })
})

describe("조건 확인 화면", () => {
  it("질문 화면에서 보내지 않은 문장을 이어받아, 시작 전에 반영할지 묻는다", async () => {
    keepPendingNote("mock_req_ready", "종목은 8개만")
    show(mock(), <ConfirmScreen requestId="mock_req_ready" />)
    expect(await screen.findByRole("textbox", { name: "말로 조건 보태기" }, { timeout: 5000 })).toHaveValue("종목은 8개만")
    fireEvent.click(screen.getByRole("button", { name: /분석 시작/ }))
    expect(screen.getByRole("alertdialog", { name: "반영하지 않은 추가 요청" })).toBeInTheDocument()
  })
  it("「분석 시작」 줄은 화면 아래에 고정된다", async () => {
    show(mock(), <ConfirmScreen requestId="mock_req_ready" />)
    const start = await screen.findByRole("button", { name: /분석 시작/ }, { timeout: 5000 })
    expect(start.closest("div.sticky")).not.toBeNull()
  })
})

describe("상세 조건", () => {
  it("홈 배지·질문 보기의 항목 이름은 상세 조건 창과 같은 용어를 쓴다", () => {
    expect(OVERRIDE_LABELS["risk.max_drawdown_tolerance"]).toBe("손실 감내 수준")
    expect(OVERRIDE_LABELS["constraints.universe"]).toBe("투자 대상 지수")
    expect(OVERRIDE_LABELS["risk.risk_tolerance"]).toBe("투자성향")
  })
  it("0원 시작 규칙이 있으면 매월 추가 투자금과 함께 0원을 받는다 (없으면 기존 검사 그대로)", async () => {
    const p = (await mock().getProfile())!.profile
    const f = { ...fromProfile(p, {}), initial_amount: 0 }
    const msg = (xs: { id: string; message: string }[]) => xs.find((e) => e.id === "initial_amount")?.message
    expect(msg(validate({ ...f, monthly_contribution: 0 }))).toBe("투자금은 0보다 커야 합니다")
    expect(msg(validate({ ...f, monthly_contribution: 500_000 }, { allowZero: true }))).toBeUndefined()
    expect(msg(validate({ ...f, monthly_contribution: 0 }, { allowZero: true }))).toMatch(/매월 추가 투자금을 정해/)
  })
})
