import { afterEach, beforeAll, describe, expect, it, vi } from "vitest"
import { fireEvent, render, screen, waitFor, within } from "@testing-library/react"
import { Providers } from "../../app/providers"
import type { AnalysisService } from "../../api/service"
import type { DialogState } from "../../api/types"
import { MockService } from "../../mocks/services/MockService"
import { fromProfile, OVERRIDE_LABELS, validate } from "../home/DetailConditions"
import { ClarifyScreen } from "./ClarifyScreen"
import { ConfirmScreen } from "./ConfirmScreen"
import { BatchResult } from "./BatchQuestions"
import { RunScreen } from "../run/RunScreen"
import { localIso } from "../../mocks/data/util"
import { LEFT_NOTE, NOTE_BUTTON, NOTE_UNSENT, keepPendingNote, leaveFlowNotice, pendingNote } from "./flow"
import { HomeScreen } from "../home/HomeScreen"
import { loadUi, saveUi } from "../../state/uiStorage"
import { MOCK_CANDIDATES } from "../../mocks/data/dialog"

// 질문·확인 화면 편의성 개선: 취소 확인, 보내지 않은 문장 이어받기, 「말로 보태기」 이름 통일, 시작 줄 고정, 라벨 통일, 0원 규칙.

beforeAll(() => { globalThis.ResizeObserver ??= class { observe() {} unobserve() {} disconnect() {} } as unknown as typeof ResizeObserver; Element.prototype.scrollIntoView = vi.fn() })
afterEach(() => { window.history.replaceState(null, "", "/"); keepPendingNote("mock_req_asking", ""); keepPendingNote("mock_req_ready", ""); window.localStorage.clear() })

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
    // 고정된 「분석 시작」 줄 안에 뜬다 (화면 위쪽에서 눌러도 바로 보인다)
    expect(screen.getByRole("alertdialog", { name: "반영하지 않은 추가 요청" }).closest("div.sticky")).not.toBeNull()
  })
  it("「분석 시작」 줄은 화면 아래에 고정되고, 그동안 main 이 스크롤 컨테이너가 되지 않게 한다", async () => {
    const { unmount } = show(mock(), <main><ConfirmScreen requestId="mock_req_ready" /></main>)
    const start = await screen.findByRole("button", { name: /분석 시작/ }, { timeout: 5000 })
    expect(start.closest("div.sticky")).not.toBeNull()
    expect(document.querySelector("main")!.style.overflowX).toBe("clip")  // overflow-x-auto 그대로면 sticky 가 창 스크롤에 붙지 않는다
    unmount()
  })
})

describe("묶음 답변 결과", () => {
  it("질문별 줄에 나온 변경은 다시 나열하지 않고, 답변에 따라 함께 바뀐 항목만 따로 알린다", () => {
    const sent = [{ seq: 1, question: "한 종목에 최대 몇 %까지 담을까요?", field: "constraints.max_weight_per_stock", fieldLabel: "종목당 최대 비중", answer: "20%", kind: "option" as const }]
    show(mock(), <BatchResult requestId="r" sent={sent} changes={[{ label: "종목당 최대 비중", before: "30%", after: "20%" }, { label: "섹터당 최대 비중", before: "40%", after: "30%" }]} />)
    expect(screen.getAllByText(/종목당 최대 비중: 30%/)).toHaveLength(1)
    expect(screen.getByText("답변에 따라 함께 바뀐 항목 1개")).toBeInTheDocument()
    expect(screen.getByText(/섹터당 최대 비중: 40%/)).toBeInTheDocument()
  })
})

describe("진행 화면", () => {
  it("끝난 실행에는 「서버 실행은 계속됩니다·보통 2~5분」 안내를 붙이지 않는다", async () => {
    show(mock(), <RunScreen runId="mock_run_cancelled" />)
    expect(await screen.findByRole("heading", { level: 1, name: "분석이 취소되었습니다" }, { timeout: 5000 })).toBeInTheDocument()
    expect(screen.queryByText(/서버 실행은 계속됩니다/)).toBeNull()
  })
  it("목업 시각은 서버처럼 시간대 오프셋을 붙인다 (없으면 UTC 시각이 로컬로 읽혀 경과 시간이 9시간 늘어난다)", () => {
    const now = Date.now(), s = localIso(now)
    expect(s).toMatch(/^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}[+-]\d{2}:\d{2}$/)
    expect(Math.abs(new Date(s).getTime() - now)).toBeLessThan(1000)
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

// 흐름 A1~A4: 요청을 그만둬도 아이디어를 잃지 않고, 확인 화면에도 나가는 길이 있고, 말없이 화면이 바뀌지 않는다.
describe("흐름: 잃지 않기 · 막다른 길 없애기", () => {
  it("A1 질문 화면에서 취소하면 홈에 아이디어·바꾼 조건과 안내를 채워 둔다", async () => {
    const s = mock()
    const st = await s.createRequest({ idea: "배당을 꾸준히 주는 미국 대형주", overrides: { "horizon.target_years": 3 } })
    show(s, <ClarifyScreen requestId={st.request_id} />)
    fireEvent.click(await screen.findByRole("button", { name: /취소하고 홈으로/ }, { timeout: 5000 }))
    fireEvent.click(screen.getByRole("button", { name: "요청 취소" }))
    await waitFor(() => expect(window.location.hash).toBe("#/home"))
    expect(loadUi()).toMatchObject({ prefillIdea: "배당을 꾸준히 주는 미국 대형주", prefillOverrides: { "horizon.target_years": 3 }, prefillNote: LEFT_NOTE, activeRequestId: null })
    expect((await s.getRequest(st.request_id)).status).toBe("cancelled")
  })
  it("A1 홈은 채워 둔 아이디어와 「그만둔 요청을 홈에 채워 두었습니다」 안내를 한 번 보여 준다", async () => {
    saveUi({ prefillIdea: "배당을 꾸준히 주는 미국 대형주", prefillOverrides: { "horizon.target_years": 3 }, prefillNote: LEFT_NOTE })
    show(mock(), <HomeScreen />)
    expect(await screen.findByText("그만둔 요청을 홈에 채워 두었습니다", {}, { timeout: 5000 })).toBeInTheDocument()
    expect(screen.getByDisplayValue("배당을 꾸준히 주는 미국 대형주")).toBeInTheDocument()
    expect(screen.getByText(/이번 분석에만 적용/)).toBeInTheDocument()
    expect(loadUi().prefillNote).toBeNull()  // 한 번만
  })
  it("A2 확인 화면에도 「취소하고 홈으로」가 있고, 한 번 더 확인한 뒤 요청을 닫고 홈에 채워 둔다", async () => {
    const s = mock()
    show(s, <ConfirmScreen requestId="mock_req_ready" />)
    fireEvent.click(await screen.findByRole("button", { name: /취소하고 홈으로/ }, { timeout: 5000 }))
    expect(screen.getByRole("alertdialog", { name: "요청 취소 확인" })).toBeInTheDocument()
    fireEvent.click(screen.getByRole("button", { name: "계속 확인하기" }))
    expect(screen.queryByRole("alertdialog", { name: "요청 취소 확인" })).toBeNull()
    fireEvent.click(screen.getByRole("button", { name: /취소하고 홈으로/ }))
    fireEvent.click(screen.getByRole("button", { name: "요청 취소" }))
    await waitFor(() => expect(window.location.hash).toBe("#/home"))
    expect((await s.getRequest("mock_req_ready")).status).toBe("cancelled")
    expect(loadUi().prefillIdea).toBeTruthy()
  })
  it("A2 수정안 확인 화면은 취소 대신 「원안 리포트로 돌아가기」만 둔다", async () => {
    const s = mock()
    const rev = await s.createRevision("mock_rep_normal", "종목은 8개만")
    await s.answerBatch(rev.request_id, [{ seq: 1, option_value: 0.2 }, { seq: 2, skip: true }, { seq: 3, option_value: 0.2 }])
    show(s, <ConfirmScreen requestId={rev.request_id} />)
    fireEvent.click(await screen.findByRole("button", { name: /원안 리포트로 돌아가기/ }, { timeout: 5000 }))
    expect(screen.queryByRole("button", { name: /취소하고 홈으로/ })).toBeNull()
    expect(window.location.hash).toBe("#/reports/mock_rep_normal")
  })
  it("A3 (목업 규칙) 종목 수 최소를 후보보다 크게 바꾸면 실행 전 점검 질문이 생겨 다시 「질문 중」이 된다", async () => {
    const s = mock()
    const st = await s.updateOverrides("mock_req_ready", { "constraints.num_holdings": { target: 30, min: MOCK_CANDIDATES + 5, max: 35 } })
    expect(st).toMatchObject({ state: "asking", question: { kind: "feasibility", field: "constraints.num_holdings" } })
    const done = await s.answer("mock_req_ready", st.question!.seq, { option_value: st.question!.options[0].value })
    expect(done.state).toBe("ready")
    expect(done.overrides?.["constraints.num_holdings"]).toEqual({ target: 10, min: 8, max: 12 })  // 다시 「조건 바꾸기」를 열면 고른 값
  })
  it("A3 확인 화면에서 바꾼 것 때문에 돌아오면 질문 화면 맨 위에 이유와 바뀐 조건을 보여 준다", async () => {
    const s = mock()
    await s.updateOverrides("mock_req_ready", { "constraints.num_holdings": { target: 30, min: 20, max: 35 } })
    leaveFlowNotice("mock_req_ready", { what: "바꾼 조건", changes: [{ label: "종목 수", before: "목표 10개 (8~12)", after: "목표 30개 (20~35)" }] })
    show(s, <ClarifyScreen requestId="mock_req_ready" />)
    expect(await screen.findByText(/방금 바꾼 조건 때문에 분석 전에 다시 확인할 것이 생겨/, {}, { timeout: 5000 })).toBeInTheDocument()
    expect(screen.getByText(/종목 수: 목표 10개 \(8~12\) →/)).toBeInTheDocument()
  })
  it("A4 홈 상세 조건은 초안으로 남고, 제출하면 비워진다", async () => {
    saveUi({ draftIdea: "배당을 꾸준히 주는 미국 대형주", draftOverrides: { "horizon.target_years": 3 } })
    const s = mock()
    const { unmount } = show(s, <HomeScreen />)
    expect(await screen.findByText(/이번 분석에만 적용/, {}, { timeout: 5000 })).toBeInTheDocument()  // 다른 메뉴에 다녀와도 그대로
    fireEvent.click(screen.getByRole("button", { name: /투자조건 확인하기/ }))
    await waitFor(() => expect(window.location.hash).toMatch(/^#\/analysis\//))
    expect(loadUi()).toMatchObject({ draftIdea: "", draftOverrides: {} })
    unmount()
  })
})

// 홈 「투자조건 확인하기」 뒤 기다림: 서버가 아이디어를 해석하는 동안(실제 서버 수 초~1분) 돌아가는지 알 수 있게.
describe("홈: 아이디어 해석을 기다리는 동안", () => {
  const IDEA = "배당을 꾸준히 주는 미국 대형주에 나눠 투자하고 싶어요"
  it("누르면 서버가 번호를 줄 때까지 「아이디어를 해석하고 있습니다」와 하는 일이 보이고 입력이 잠기며, 번호를 받으면 그 질문 화면 주소로 간다", async () => {
    const s = mock()
    let answer: (st: DialogState) => void = () => {}
    const slow = Object.assign(Object.create(s), { createRequest: () => new Promise<DialogState>((r) => { answer = r }) }) as AnalysisService  // 응답을 직접 풀어 준다
    show(slow, <HomeScreen />)
    fireEvent.change(await screen.findByPlaceholderText(/예: 미국과 한국의 반도체/, {}, { timeout: 5000 }), { target: { value: IDEA } })
    fireEvent.click(screen.getByRole("button", { name: /투자조건 확인하기/ }))
    expect(await screen.findByText("아이디어를 해석하고 있습니다")).toBeInTheDocument()
    expect(screen.getByText("꼭 필요한 질문 고르기")).toBeInTheDocument()
    expect(screen.getByDisplayValue(IDEA)).toHaveAttribute("readonly")
    expect(screen.getByRole("button", { name: /^상세 조건/ })).toBeDisabled()
    expect(screen.getByRole("button", { name: /아이디어 해석 중/ })).toBeDisabled()
    answer({ ...(await s.createRequest({ idea: IDEA })), request_id: "req_x", state: "interpreting" })
    await waitFor(() => expect(window.location.hash).toBe("#/analysis/req_x"))
    expect(loadUi().activeRequestId).toBe("req_x")
  })
  it("실패하면 이유와 「다시 시도」를 보여 주고, 아이디어는 그대로 남는다", async () => {
    const s = mock()
    let calls = 0
    const failing = Object.assign(Object.create(s), { createRequest: () => { calls++; return Promise.reject(new Error("서버에 연결할 수 없습니다.")) } }) as AnalysisService
    show(failing, <HomeScreen />)
    fireEvent.change(await screen.findByPlaceholderText(/예: 미국과 한국의 반도체/, {}, { timeout: 5000 }), { target: { value: IDEA } })
    fireEvent.click(screen.getByRole("button", { name: /투자조건 확인하기/ }))
    expect(await screen.findByText("아이디어를 해석하지 못했습니다")).toBeInTheDocument()
    expect(screen.getByDisplayValue(IDEA)).not.toHaveAttribute("readonly")
    fireEvent.click(screen.getByRole("button", { name: "다시 시도" }))
    await waitFor(() => expect(calls).toBe(2))
  })
})

// 새 요청은 서버가 번호를 먼저 주고(interpreting) 해석·첫 질문은 뒤에서 한다. 질문 화면이 2초마다 다시 읽어 이어 간다 (새로고침해도 주소에 번호가 있다).
describe("질문 화면: 서버가 아이디어를 해석하는 동안", () => {
  const IDEA = "배당을 꾸준히 주는 미국 대형주에 나눠 투자하고 싶어요"
  it("해석 중이면 기다림을 보여 주고, 해석이 끝나면 첫 질문을 보여 준다", async () => {
    const expected = (await mock().createRequest({ idea: IDEA })).question!.question_ko  // 지연 0 목업은 바로 질문
    const s = new MockService({ latencyMs: 20, persist: false })  // 해석 중 = 지연 ×50 = 1초
    const st = await s.createRequest({ idea: IDEA })
    expect(st.state).toBe("interpreting")
    show(s, <ClarifyScreen requestId={st.request_id} />)
    expect(await screen.findByText("아이디어를 해석하고 있습니다", {}, { timeout: 5000 })).toBeInTheDocument()
    const steps = screen.getByRole("list", { name: "해석 단계" })  // 서버가 주는 단계 (고정 안내가 아니라)
    expect(within(steps).getAllByRole("listitem")).toHaveLength(6)
    expect(within(steps).getByText("조건 정리")).toBeInTheDocument()
    expect(within(steps).getByText(/(진행 중)/)).toBeInTheDocument()
    expect(screen.getByText(IDEA)).toBeInTheDocument()
    expect(await screen.findByText(expected, {}, { timeout: 5000 })).toBeInTheDocument()  // 2초 간격으로 다시 읽음
    expect(screen.queryByText("아이디어를 해석하고 있습니다")).not.toBeInTheDocument()
  })
  it("해석이 실패했으면 이유와 「다시 시도」를 보여 주고, 누르면 같은 아이디어로 새 요청을 보내 그 주소로 간다", async () => {
    const s = mock()
    const sent: unknown[] = []
    const svc = Object.assign(Object.create(s), { createRequest: (input: { idea: string }) => { sent.push(input); return s.createRequest(input) } }) as AnalysisService
    show(svc, <ClarifyScreen requestId="mock_req_failed" />)
    expect(await screen.findByText("아이디어를 해석하지 못했습니다", {}, { timeout: 5000 })).toBeInTheDocument()
    expect(screen.getByText(/분석 모델 응답 형식이 맞지 않습니다/)).toBeInTheDocument()
    const steps = screen.getByRole("list", { name: "해석 단계" })  // 어느 단계에서 멈췄는지
    expect(within(within(steps).getByText("아이디어 해석").closest("li")!).getByText("여기서 멈춤")).toBeInTheDocument()
    expect(within(within(steps).getByText("조건 정리").closest("li")!).getByText(/^기준일 /)).toBeInTheDocument()
    fireEvent.click(screen.getByRole("button", { name: "다시 시도" }))
    await waitFor(() => expect(window.location.hash).toMatch(/^#\/analysis\/mock_req_\d+$/))
    expect(sent).toHaveLength(1)
    expect(loadUi().activeRequestId).toBe(window.location.hash.replace("#/analysis/", ""))
  })
  it("확인 화면 주소로 해석 중인 요청을 열면 질문 화면으로 보낸다", async () => {
    show(mock(), <ConfirmScreen requestId="mock_req_interpreting" />)
    await waitFor(() => expect(window.location.hash).toBe("#/analysis/mock_req_interpreting"))
  })
})
