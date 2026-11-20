import { afterEach, beforeAll, describe, expect, it, vi } from "vitest"
import { fireEvent, render, screen, waitFor, within } from "@testing-library/react"
import { Providers } from "../../app/providers"
import type { AnalysisService } from "../../api/service"
import { MockService } from "../../mocks/services/MockService"
import { ClarifyRoute } from "../analysis/ClarifyRoute"
import { ConfirmScreen } from "../analysis/ConfirmScreen"
import { NOTE_BUTTON, keepPendingNote } from "../analysis/flow"
import { loadUi } from "../../state/uiStorage"
import { HomeScreen } from "./HomeScreen"

// 새 분석의 질문 단계(#/analysis/:id)를 홈 화면 왼쪽 대화창에서 (2026-11-17). 최종 조건 확인은 따로 있는 확인 화면.

beforeAll(() => { globalThis.ResizeObserver ??= class { observe() {} unobserve() {} disconnect() {} } as unknown as typeof ResizeObserver; Element.prototype.scrollIntoView = vi.fn() })
afterEach(() => { window.history.replaceState(null, "", "/"); keepPendingNote("mock_req_asking", ""); window.localStorage.clear(); vi.restoreAllMocks() })

const IDEA = "배당을 꾸준히 주는 미국 대형주에 나눠 투자하고 싶어요"
const mock = () => new MockService({ latencyMs: 0, persist: false })
const show = (svc: AnalysisService, ui: React.ReactNode) => render(<Providers service={svc}>{ui}</Providers>)
const chat = () => screen.findByRole("list", { name: "분석 모델과의 대화" }, { timeout: 5000 })
/** 진행 단계 표시에서 지금 단계의 이름 */
const currentStep = () => within(screen.getByRole("navigation", { name: "분석 진행 단계" })).getByRole("listitem", { current: "step" })

describe("홈 대화창: 질문에 답하기", () => {
  it("내 아이디어와 질문을 말풍선으로 보여 주고, 보기를 누르면 바로 답을 보내 다음 질문으로, 다 답하면 조건 확인으로 간다", async () => {
    const s = mock()
    const answer = vi.spyOn(s, "answer")
    const st = await s.createRequest({ idea: IDEA })
    show(s, <ClarifyRoute requestId={st.request_id} />)
    const c = await chat()
    expect(await within(c).findByText(IDEA)).toBeInTheDocument()
    expect(currentStep()).toHaveTextContent("질문에 답하기")
    expect(screen.getByRole("tab", { name: "이번 요청 조건" })).toHaveAttribute("aria-selected", "true")
    // 질문이 남아 있는 동안 첫 보기를 누른다
    for (let i = 0; i < 10 && !window.location.hash.endsWith("/confirm"); i++) {
      const cur = (await s.getRequest(st.request_id)).question
      if (!cur) break
      const group = await screen.findByRole("group", { name: cur.question_ko }, { timeout: 5000 })
      fireEvent.click(within(group).getAllByRole("button")[0])
      await waitFor(() => expect(answer).toHaveBeenCalledTimes(i + 1))
      await waitFor(() => expect(within(c).getAllByText(cur.options[0].label_ko).length).toBeGreaterThan(0))  // 내 답이 말풍선으로 남는다
    }
    await waitFor(() => expect(window.location.hash).toBe(`#/analysis/${st.request_id}/confirm`))
  })

  it("아래 입력창의 「말로 보태기」로 질문과 상관없는 조건을 보탠다", async () => {
    const s = mock()
    const send = vi.spyOn(s, "sendMessage")
    show(s, <ClarifyRoute requestId="mock_req_asking" />)
    await chat()
    fireEvent.change(await screen.findByRole("textbox", { name: "말로 조건 보태기" }, { timeout: 5000 }), { target: { value: "종목은 8개만" } })
    fireEvent.click(screen.getByRole("button", { name: NOTE_BUTTON }))
    await waitFor(() => expect(send).toHaveBeenCalledWith("mock_req_asking", "종목은 8개만"))
  })

  it("「취소」는 한 번 더 확인하고, 요청을 닫은 뒤 아이디어를 홈에 다시 채워 둔다", async () => {
    const s = mock()
    show(s, <ClarifyRoute requestId="mock_req_asking" />)
    await chat()
    fireEvent.click(await screen.findByRole("button", { name: "취소" }, { timeout: 5000 }))
    expect(screen.getByRole("alertdialog", { name: "요청 취소 확인" })).toBeInTheDocument()
    fireEvent.click(screen.getByRole("button", { name: "요청 취소" }))
    await waitFor(() => expect(window.location.hash).toBe("#/home"))
    expect((await s.getRequest("mock_req_asking")).status).toBe("cancelled")
    expect(loadUi().prefillIdea).toBe((await s.getRequest("mock_req_asking")).idea)
  })

  it("서버가 해석하는 동안은 기다림과 해석 단계를 보여 주고, 끝나면 첫 질문이 이어진다", async () => {
    const expected = (await mock().createRequest({ idea: IDEA })).question!.question_ko
    const s = new MockService({ latencyMs: 20, persist: false })  // 해석 중 = 지연 ×50 = 1초
    const st = await s.createRequest({ idea: IDEA })
    expect(st.state).toBe("interpreting")
    show(s, <ClarifyRoute requestId={st.request_id} />)
    expect(await screen.findByText("아이디어를 해석하고 있어요", {}, { timeout: 5000 })).toBeInTheDocument()
    expect(screen.getByRole("list", { name: "해석 단계" })).toBeInTheDocument()
    expect(await screen.findByRole("group", { name: expected }, { timeout: 6000 })).toBeInTheDocument()  // 2초 간격으로 다시 읽음
  }, 10000)

  it("리포트에서 시작한 수정 요청은 홈 대화창이 아니라 기존 질문 화면에서", async () => {
    const s = mock()
    const base = await s.getRequest("mock_req_asking")
    const svc = Object.assign(Object.create(s), { getRequest: async () => ({ ...base, mode: "revision" }) }) as AnalysisService
    show(svc, <ClarifyRoute requestId="mock_req_asking" />)
    expect(await screen.findByRole("heading", { name: "부족한 조건을 함께 정합니다" }, { timeout: 5000 })).toBeInTheDocument()
    expect(screen.queryByRole("list", { name: "분석 모델과의 대화" })).toBeNull()
  })
})

describe("분석 진행 단계 표시", () => {
  it("홈은 1단계 「아이디어 적기」, 조건 확인 화면은 3단계 「조건 확인」", async () => {
    const first = show(mock(), <HomeScreen />)
    await screen.findByRole("heading", { name: "투자 아이디어를 적어 주세요" }, { timeout: 5000 })
    expect(currentStep()).toHaveTextContent("아이디어 적기")
    expect(screen.getByRole("button", { name: /분석 시작하기/ })).toBeInTheDocument()
    first.unmount()
    show(mock(), <ConfirmScreen requestId="mock_req_ready" />)
    await screen.findByRole("button", { name: /이 조건으로 분석 실행/ }, { timeout: 5000 })
    expect(currentStep()).toHaveTextContent("조건 확인")
  })
})
