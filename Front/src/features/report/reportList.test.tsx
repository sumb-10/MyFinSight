import { beforeAll, beforeEach, describe, expect, it, vi } from "vitest"
import { fireEvent, render, screen, waitFor, within } from "@testing-library/react"
import { ServiceContext } from "../../app/providers"
import type { AnalysisService } from "../../api/service"
import { MockService } from "../../mocks/services/MockService"
import { ReportList } from "./ReportList"

// 분석 리포트 목록 정리 (2026-11-11): 열은 리포트·리포트 만든 날짜만, 줄마다 「⋯」 하나, 더보기에 모의투자 보기/시작하기

beforeAll(() => { globalThis.ResizeObserver ??= class { observe() {} unobserve() {} disconnect() {} } as unknown as typeof ResizeObserver; Element.prototype.scrollIntoView = vi.fn() })
beforeEach(() => { try { window.localStorage.clear() } catch { /* ignore */ } window.history.replaceState(null, "", "/?mock=1") })

const mock = () => new MockService({ latencyMs: 0, persist: false })
const show = (svc: AnalysisService) => render(<ServiceContext.Provider value={svc}><ReportList /></ServiceContext.Provider>)
const row = async (id: string) => { await waitFor(() => expect(document.querySelector(`tr[data-report="${id}"]`)).not.toBeNull(), { timeout: 5000 }); return document.querySelector<HTMLElement>(`tr[data-report="${id}"]`)! }
const openMenu = async (id: string) => { fireEvent.click(within(await row(id)).getByRole("button", { name: "더보기" })); return screen.getAllByRole("menuitem").map((m) => m.textContent) }

describe("분석 리포트 목록", () => {
  it("열은 리포트와 리포트 만든 날짜뿐이고, 안내 문장·상태·분석 기준일·예시 리포트·줄마다 삭제 버튼이 없다", async () => {
    show(mock())
    await row("mock_rep_normal")
    expect(Array.from(document.querySelectorAll("thead th")).map((th) => th.textContent)).toEqual(["리포트 · 요청 요약", "리포트 만든 날짜", "메뉴"])
    expect(screen.queryByText(/완료된 분석의 리포트입니다/)).toBeNull()
    expect(screen.queryByText("분석 기준일")).toBeNull()
    expect(screen.queryByText("상태")).toBeNull()
    expect(screen.queryByText("예시")).toBeNull()
    expect(screen.queryByRole("button", { name: /예시 리포트 다시 보이기/ })).toBeNull()
    expect(screen.queryByRole("button", { name: "삭제" })).toBeNull()  // 삭제는 더보기 안으로
    expect(within(await row("mock_rep_normal")).getByText("2026-10-31")).toBeInTheDocument()  // 리포트 만든 날짜
  })

  it("연결된 모의투자가 여러 개면 이름 변경 아래에 시작일로 구분해 하나씩, 누르면 그 모의투자로 간다", async () => {
    const svc = mock()
    show(svc)
    const linked = (await svc.listPaper()).filter((p) => p.report_id === "mock_rep_normal")
    expect(linked.length).toBeGreaterThan(1)
    expect(await openMenu("mock_rep_normal")).toEqual(["이름 변경", ...linked.map((p) => `모의투자 보기 · ${p.start_date} 시작`), "삭제"])
    fireEvent.click(screen.getByRole("menuitem", { name: `모의투자 보기 · ${linked[1].start_date} 시작` }))
    expect(window.location.hash).toBe(`#/paper/${linked[1].paper_id}`)
  })

  it("연결된 모의투자가 하나면 「모의투자 보기」", async () => {
    const svc = mock()
    show(svc)
    const [one] = (await svc.listPaper()).filter((p) => p.report_id === "mock_rep_caution")
    expect(await openMenu("mock_rep_caution")).toEqual(["이름 변경", "모의투자 보기", "삭제"])
    fireEvent.click(screen.getByRole("menuitem", { name: "모의투자 보기" }))
    expect(window.location.hash).toBe(`#/paper/${one.paper_id}`)
  })

  it("연결된 모의투자가 없으면 「모의투자 시작하기」를 두고, 누르면 모의투자 시작 창이 뜬다", async () => {
    const svc = mock()
    show(svc)
    expect((await svc.listPaper()).some((p) => p.report_id === "mock_rep_newsoff")).toBe(false)
    expect(await openMenu("mock_rep_newsoff")).toEqual(["이름 변경", "모의투자 시작하기", "삭제"])
    fireEvent.click(screen.getByRole("menuitem", { name: "모의투자 시작하기" }))
    expect(await screen.findByRole("dialog", { name: "모의투자 시작" })).toBeInTheDocument()
  })

  it("모의투자 목록을 받기 전에는 모의투자 항목을 넣지 않는다 (시작하기로 잘못 보이지 않게)", async () => {
    const s = mock()
    show(Object.assign(Object.create(s), { listPaper: () => new Promise(() => {}) }) as AnalysisService)
    expect(await openMenu("mock_rep_newsoff")).toEqual(["이름 변경", "삭제"])
  })
})
