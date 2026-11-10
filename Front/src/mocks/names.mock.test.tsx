import { beforeEach, afterEach, beforeAll, describe, expect, it, vi } from "vitest"
import { fireEvent, render, screen, waitFor, within } from "@testing-library/react"
import { ServiceContext } from "../app/providers"
import type { AnalysisService } from "../api/service"
import { proposedNameOf } from "../api/proposed"
import { ReportDetail } from "../features/report/ReportDetail"
import { ReportList } from "../features/report/ReportList"
import { StartPaperDialog } from "../features/paper/StartPaperDialog"
import { PaperScreen } from "../features/paper/PaperScreen"
import { REPORTS } from "./scenarios"
import { MockService } from "./services/MockService"
import { setExampleHidden } from "../features/tutorial/exampleReport"

// 목록 맨 위 「예시」 리포트는 이 파일이 다루는 서버 리포트 이름·삭제와 별개라 숨겨 둔다 (기본 이름이 목업 리포트와 같다)
beforeEach(() => setExampleHidden(true))

// 3단계: 리포트 이름(자동 이름·바꾸기·되돌리기)과 모의투자 이름 연동. 서비스에 제안 메서드가 없으면(일반 모드) 지금 화면 그대로인지도 확인한다.

beforeAll(() => { globalThis.ResizeObserver ??= class { observe() {} unobserve() {} disconnect() {} } as unknown as typeof ResizeObserver; Element.prototype.scrollIntoView = vi.fn() })
afterEach(() => window.history.replaceState(null, "", "/"))

const mock = () => new MockService({ latencyMs: 0, persist: false })
const AUTO = REPORTS[0].auto_name_ko  // mock_rep_normal
const withSvc = (svc: AnalysisService, ui: React.ReactNode) => { window.history.replaceState(null, "", "/?mock=1"); return render(<ServiceContext.Provider value={svc}>{ui}</ServiceContext.Provider>) }
/** 제안 메서드를 뺀 서비스 (일반 모드의 HttpService 처럼). 나머지는 목업 자료를 그대로 쓴다. */
const plain = (s: MockService): AnalysisService => Object.assign(Object.create(s), {
  mode: "api", getReportName: undefined, renameReport: undefined, getPaperName: undefined, setPaperName: undefined,
  listReports: async () => (await s.listReports()).map(({ proposed_name: _n, ...r }) => r),
})

describe("이름 규칙 (목업 서비스)", () => {
  it("리포트 ID·실행 ID 어느 쪽으로 바꿔도 같은 이름이고, 목록 행에도 같은 이름이 붙는다", async () => {
    const s = mock()
    expect((await s.getReportName("mock_rep_normal")).display_ko).toBe(AUTO)
    await s.renameReport(REPORTS[0].run_id, "  반도체 장기 보유  ")
    expect(await s.getReportName("mock_rep_normal")).toMatchObject({ display_ko: "반도체 장기 보유", custom_ko: "반도체 장기 보유", auto_ko: AUTO })
    expect(proposedNameOf((await s.listReports()).find((r) => r.report_id === "mock_rep_normal")!)).toBe("반도체 장기 보유")
  })
  it("되돌리기(null)·빈 이름·자동 이름과 같은 이름은 모두 자동 이름으로 둔다", async () => {
    const s = mock()
    for (const v of [null, "   ", AUTO]) { await s.renameReport("mock_rep_normal", "임시"); expect((await s.renameReport("mock_rep_normal", v)).custom_ko).toBeNull() }
  })
  it("연동한 모의투자 이름은 리포트 이름을 따라가고, 직접 입력한 이름은 그대로다. 다시 연동하면 리포트 이름이 된다", async () => {
    const s = mock()
    await s.renameReport("mock_rep_normal", "새 이름")
    const names = Object.fromEntries((await s.listPaper()).map((p) => [p.paper_id, p.name_ko]))
    expect(names.mock_paper_a1).toBe("새 이름"); expect(names.mock_paper_a3).toBe("새 이름")
    expect(names.mock_paper_a2).toBe("시가총액 비중 비교용")
    expect((await s.getPaper("mock_paper_a1")).portfolio.name_ko).toBe("새 이름")
    expect(await s.setPaperName("mock_paper_a2", { mode: "linked" })).toMatchObject({ mode: "linked", name_ko: "새 이름" })
    await s.setPaperName("mock_paper_a1", { mode: "custom", name_ko: "적립식 비교" })
    await s.renameReport("mock_rep_normal", null)
    expect((await s.getPaperName("mock_paper_a1")).name_ko).toBe("적립식 비교")
    expect((await s.getPaperName("mock_paper_a2")).name_ko).toBe(AUTO)
  })
})

describe("리포트 이름 바꾸기 화면", () => {
  it("상세: 연필 버튼 → 저장하면 제목이 바뀌고, 취소하면 그대로, 되돌리면 자동 이름", async () => {
    withSvc(mock(), <ReportDetail reportId="mock_rep_normal" />)
    const h1 = await screen.findByRole("heading", { level: 1 }, { timeout: 5000 })
    await waitFor(() => expect(h1).toHaveTextContent(AUTO))
    expect(screen.queryByText("투자 아이디어로 자동으로 만든 이름")).toBeNull()
    expect(screen.getAllByText(`[목업] ${REPORTS[0].idea}`)).toHaveLength(1)  // 제목 바로 아래 한 번만 (날짜 위에 다시 두지 않는다)
    fireEvent.click(screen.getByRole("button", { name: "리포트 이름 바꾸기" }))
    let dlg = await screen.findByRole("dialog", { name: "리포트 이름 바꾸기" })
    const input = within(dlg).getByRole("textbox", { name: /리포트 이름/ })
    await waitFor(() => expect(input).toHaveValue(AUTO))
    expect(within(dlg).getByRole("button", { name: "저장" })).toBeDisabled()  // 바뀐 게 없으면 저장하지 않는다
    expect(within(dlg).queryByRole("button", { name: "자동 이름으로 되돌리기" })).toBeNull()
    fireEvent.change(input, { target: { value: "" } }); fireEvent.click(within(dlg).getByRole("button", { name: "저장" }))
    expect(await within(dlg).findByText(/이름을 입력해 주세요/)).toBeInTheDocument()
    fireEvent.change(input, { target: { value: "취소할 이름" } }); fireEvent.click(within(dlg).getByRole("button", { name: "취소" }))
    expect(h1).toHaveTextContent(AUTO)
    fireEvent.click(screen.getByRole("button", { name: "리포트 이름 바꾸기" }))
    dlg = await screen.findByRole("dialog", { name: "리포트 이름 바꾸기" })
    fireEvent.change(await within(dlg).findByRole("textbox", { name: /리포트 이름/ }), { target: { value: "내 반도체 포트폴리오" } })
    fireEvent.click(within(dlg).getByRole("button", { name: "저장" }))
    await waitFor(() => expect(h1).toHaveTextContent("내 반도체 포트폴리오"))
    fireEvent.click(screen.getByRole("button", { name: "리포트 이름 바꾸기" }))
    fireEvent.click(await screen.findByRole("button", { name: "자동 이름으로 되돌리기" }))
    await waitFor(() => expect(h1).toHaveTextContent(AUTO))
  }, 15000)
  it("목록: 더보기 → 이름 변경으로 바꾸면 목록의 이름이 바로 바뀐다", async () => {
    withSvc(mock(), <ReportList />)
    const row = (await screen.findByText(AUTO)).closest("tr")!
    fireEvent.click(within(row).getByRole("button", { name: "더보기" }))
    fireEvent.click(screen.getByRole("menuitem", { name: "이름 변경" }))  // 메뉴는 표 밖(body)에 뜬다
    const dlg = await screen.findByRole("dialog", { name: "리포트 이름 바꾸기" })
    fireEvent.change(await within(dlg).findByRole("textbox", { name: /리포트 이름/ }), { target: { value: "목록에서 바꾼 이름" } })
    fireEvent.click(within(dlg).getByRole("button", { name: "저장" }))
    expect(await screen.findByText("목록에서 바꾼 이름")).toBeInTheDocument()
    expect(screen.queryByText(AUTO)).toBeNull()
  })
  it("일반 모드(제안 메서드 없음): 목록 더보기에 이름 변경이 없고 상세에 연필 버튼이 없으며, 목록 이름은 투자 아이디어·상세 제목은 리포트의 짧은 제목", async () => {
    const s = plain(mock())
    const { unmount } = withSvc(s, <ReportList />)
    const idea = REPORTS[0].idea
    expect((await screen.findAllByText(idea, {}, { timeout: 3000 })).length).toBeGreaterThan(0)
    fireEvent.click(screen.getAllByRole("button", { name: "더보기" })[0])  // 더보기에는 모의투자·삭제만
    expect(screen.queryByRole("menuitem", { name: "이름 변경" })).toBeNull()
    expect(screen.getByRole("menuitem", { name: "삭제" })).toBeInTheDocument()
    expect(screen.queryByText(AUTO)).toBeNull()
    unmount()
    withSvc(s, <ReportDetail reportId="mock_rep_normal" />)
    const h1 = await screen.findByRole("heading", { level: 1 }, { timeout: 5000 })
    const { header } = await s.getReport("mock_rep_normal")
    await waitFor(() => expect(h1).toHaveTextContent(header.title_ko))
    expect(h1).not.toHaveTextContent(idea)
    expect(screen.queryByRole("button", { name: "리포트 이름 바꾸기" })).toBeNull()
  })
})

describe("모의투자 이름 연동 화면", () => {
  it("시작 창: 직접 입력을 고르면 빈 이름을 막고, 확인 화면에 이름이 보이며, 만든 모의투자에 그 이름이 붙는다", async () => {
    const s = mock()
    withSvc(s, <StartPaperDialog reportId={REPORTS[0].run_id} close={() => {}} />)
    expect(await screen.findByText(`‘${AUTO}’ · 리포트 이름을 바꾸면 함께 바뀝니다`, {}, { timeout: 3000 })).toBeInTheDocument()
    fireEvent.click(screen.getByRole("radio", { name: /모의투자 이름 직접 입력/ }))
    fireEvent.click(screen.getByRole("button", { name: "시작 조건 확인" }))
    expect(await screen.findByText(/모의투자 이름을 입력해 주세요/)).toBeInTheDocument()
    fireEvent.change(screen.getByRole("textbox", { name: "모의투자 이름" }), { target: { value: "소액 테스트" } })
    fireEvent.click(screen.getByRole("button", { name: "시작 조건 확인" }))
    expect(await screen.findByText("직접 입력 · 리포트 이름을 바꿔도 그대로입니다")).toBeInTheDocument()
    expect(screen.getByText("소액 테스트")).toBeInTheDocument()
    fireEvent.click(screen.getByRole("button", { name: "이 조건으로 시작" }))
    await waitFor(async () => expect((await s.listPaper()).map((p) => p.name_ko)).toContain("소액 테스트"))
    await s.renameReport("mock_rep_normal", "바뀐 리포트")
    expect((await s.listPaper()).map((p) => p.name_ko)).toContain("소액 테스트")
  })
  it("시작 창: 기본값(리포트 이름과 동일)으로 만들면 리포트 이름을 따라간다", async () => {
    const s = mock()
    withSvc(s, <StartPaperDialog reportId="mock_rep_caution" close={() => {}} />)
    fireEvent.click(await screen.findByRole("button", { name: "시작 조건 확인" }, { timeout: 3000 }))
    expect(await screen.findByText("리포트 이름과 연동 · 리포트 이름을 바꾸면 함께 바뀝니다")).toBeInTheDocument()
    fireEvent.click(screen.getByRole("button", { name: "이 조건으로 시작" }))
    await waitFor(async () => expect((await s.listPaper()).length).toBe(5))
    await s.renameReport("mock_rep_caution", "저변동 비교")
    expect((await s.listPaper()).filter((p) => p.name_ko === "저변동 비교").length).toBe(2)  // 기존 b1 + 새로 만든 것
  })
  it("상세: 직접 정한 이름은 「리포트 이름과 다시 연동」으로 리포트 이름이 되고, 이름 바꾸기 창에서 다시 직접 입력할 수 있다", async () => {
    withSvc(mock(), <PaperScreen paperId="mock_paper_a2" />)
    const h1 = await screen.findByRole("heading", { level: 1, name: "시가총액 비중 비교용" }, { timeout: 5000 })
    expect(screen.queryByText(/직접 정한 이름 · 리포트 이름:|리포트 이름과 연동된 이름/)).toBeNull()  // 이름 정해진 방식 줄은 두지 않는다
    expect(screen.queryByRole("button", { name: "이름 바꾸기" })).toBeNull()  // 글자 버튼은 없다 (제목 옆 연필과 더보기 안)
    const more = () => fireEvent.click(screen.getByRole("button", { name: "더보기" }))
    more(); fireEvent.click(screen.getByRole("menuitem", { name: "리포트 이름과 다시 연동" }))
    await waitFor(() => expect(h1).toHaveTextContent(AUTO))
    more(); expect(screen.queryByRole("menuitem", { name: "리포트 이름과 다시 연동" })).toBeNull()
    fireEvent.click(screen.getByRole("menuitem", { name: "이름 바꾸기" }))
    const dlg = await screen.findByRole("dialog", { name: "모의투자 이름 바꾸기" })
    fireEvent.click(within(dlg).getByRole("radio", { name: /모의투자 이름 직접 입력/ }))
    fireEvent.change(within(dlg).getByRole("textbox", { name: "모의투자 이름" }), { target: { value: "시총 비교 2" } })
    fireEvent.click(within(dlg).getByRole("button", { name: "저장" }))
    await waitFor(() => expect(h1).toHaveTextContent("시총 비교 2"))
    // 제목 옆 연필로도 같은 창이 열린다 (리포트 상세와 같음). 지금 이름 방식(직접 입력)이 골라져 있다
    fireEvent.click(within(h1.parentElement!).getByRole("button", { name: "모의투자 이름 바꾸기" }))
    const dlg2 = await screen.findByRole("dialog", { name: "모의투자 이름 바꾸기" })
    expect(within(dlg2).getByRole("radio", { name: /모의투자 이름 직접 입력/ })).toBeChecked()
    expect(within(dlg2).getByRole("textbox", { name: "모의투자 이름" })).toHaveValue("시총 비교 2")
  })
  it("일반 모드(제안 메서드 없음): 시작 창에 이름 선택이 없고, 상세에 이름 바꾸기가 없다", async () => {
    const s = plain(mock())
    const { unmount } = withSvc(s, <StartPaperDialog reportId="mock_rep_normal" close={() => {}} />)
    await screen.findByRole("button", { name: "시작 조건 확인" }, { timeout: 3000 })
    expect(screen.queryByRole("radio")).toBeNull()
    unmount()
    withSvc(s, <PaperScreen paperId="mock_paper_a2" />)
    await screen.findByRole("heading", { level: 1 }, { timeout: 5000 })
    expect(screen.queryByRole("button", { name: "모의투자 이름 바꾸기" })).toBeNull()  // 제목 옆 연필도 없다
    fireEvent.click(screen.getByRole("button", { name: "더보기" }))
    expect(screen.queryByRole("menuitem", { name: "이름 바꾸기" })).toBeNull()
    expect(screen.getByRole("menuitem", { name: "원본 리포트 보기" })).toBeInTheDocument()
  })
})

describe("저장된 리포트 목록: 이름으로 열기 · 삭제 (목업)", () => {
  it("「열기」 버튼 없이 이름을 누르면 열리고, 삭제(더보기 안)는 확인 창에서 「확인」을 눌러야 지워진다 (취소하면 그대로)", async () => {
    const svc = new MockService({ latencyMs: 0, persist: false })
    withSvc(svc, <ReportList />)
    const first = REPORTS[0], name = svc.reportDisplayName(first.id)
    const row = (await screen.findByText(name, {}, { timeout: 5000 })).closest("tr")!
    expect(screen.queryByRole("button", { name: "열기" })).toBeNull()
    fireEvent.click(within(row).getByText(name))
    expect(window.location.hash).toBe(`#/reports/${first.id}`)

    const del = () => { fireEvent.click(within(row).getByRole("button", { name: "더보기" })); fireEvent.click(screen.getByRole("menuitem", { name: "삭제" })) }  // 삭제는 더보기 안 맨 아래
    del()
    const dlg = screen.getByRole("dialog", { name: "리포트를 삭제할까요?" })
    fireEvent.click(within(dlg).getByRole("button", { name: "취소" }))
    expect(screen.queryByRole("dialog")).toBeNull()
    expect((await svc.listReports()).some((r) => r.report_id === first.id)).toBe(true)

    del()
    fireEvent.click(within(screen.getByRole("dialog")).getByRole("button", { name: "확인" }))
    await waitFor(() => expect(row).not.toBeInTheDocument())  // 같은 이름의 수정안 리포트가 있을 수 있어 줄로 확인
    expect((await svc.listReports()).some((r) => r.report_id === first.id)).toBe(false)
    await expect(svc.getReport(first.id)).rejects.toThrow()
  })
})
