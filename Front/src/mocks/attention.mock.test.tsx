import { act } from "react"
import { afterEach, beforeAll, describe, expect, it, vi } from "vitest"
import { render, screen, waitFor, within } from "@testing-library/react"
import { Providers } from "../app/providers"
import { Sidebar } from "../app/App"
import type { AnalysisService } from "../api/service"
import { markRebalanceSeen, markReportSeen, SEEN_KEYS } from "../lib/seen"
import { MockService } from "./services/MockService"

// 사이드바 숫자 배지: 새로 완료된 리포트, 확인하지 않은 리밸런싱. 확인 기록은 이 브라우저에만 있고 서버로 보내지 않는다.

beforeAll(() => { globalThis.ResizeObserver ??= class { observe() {} unobserve() {} disconnect() {} } as unknown as typeof ResizeObserver; Element.prototype.scrollIntoView = vi.fn() })
afterEach(() => { window.sessionStorage.clear(); window.localStorage.clear(); window.history.replaceState(null, "", "/") })

const mock = () => new MockService({ latencyMs: 0, persist: false })
const nav = () => within(screen.getByRole("navigation", { name: "주 메뉴" }))

describe("사이드바 숫자 배지", () => {
  it("목업: 새로 완료된 리포트 1개·확인하지 않은 리밸런싱 1건을 숫자로 보여 주고, 열어 보거나 확인하면 사라진다", async () => {
    window.history.replaceState(null, "", "/?mock=1")
    const s = mock()
    render(<Providers service={s}><Sidebar route={{ page: "home" }} /></Providers>)
    expect(await nav().findByRole("button", { name: "분석 리포트(새로 완료된 리포트 1개)" })).toHaveTextContent("1")
    expect(await nav().findByRole("button", { name: "모의투자(리밸런싱 확인 1건)" }, { timeout: 5000 })).toHaveTextContent("1")
    expect(screen.getByText("새 리포트:")).toBeInTheDocument()  // 최근 리포트 목록에도 표시
    act(() => markReportSeen("mock", "mock_rep_revised"))
    await waitFor(() => expect(nav().getByRole("button", { name: "분석 리포트" })).toBeInTheDocument())
    const n = (await s.listPaper()).find((p) => p.paper_id === "mock_paper_a1")!.n_rebalances
    act(() => markRebalanceSeen("mock", "mock_paper_a1", n))
    await waitFor(() => expect(nav().getByRole("button", { name: "모의투자" })).toBeInTheDocument())
    expect(window.localStorage.getItem(SEEN_KEYS.api)).toBeNull()  // 목업 기록은 일반 모드 기록과 섞이지 않는다
  })
  it("일반 모드: 처음 켤 때 이미 있던 리포트·리밸런싱은 알리지 않고, 그 뒤에 새로 완료된 리포트만 알린다", async () => {
    const s = mock()
    let extra = false
    const svc = Object.assign(Object.create(s), {
      mode: "api", seenSeed: undefined,
      listReports: async () => { const rows = await s.listReports(); return extra ? [{ ...rows[0], report_id: "run_new", run_id: "run_new", created_at: "2026-11-07" }, ...rows] : rows },
    }) as AnalysisService
    const ui = (page: "home" | "reports") => <Providers service={svc}><Sidebar route={{ page }} /></Providers>
    const { rerender } = render(ui("home"))
    await waitFor(() => expect(JSON.parse(window.localStorage.getItem(SEEN_KEYS.api) ?? "{}").reports).toHaveLength(6))
    await waitFor(() => expect(Object.keys(JSON.parse(window.localStorage.getItem(SEEN_KEYS.api)!).papers)).toHaveLength(4))
    expect(nav().getByRole("button", { name: "분석 리포트" })).toBeInTheDocument()
    expect(nav().getByRole("button", { name: "모의투자" })).toBeInTheDocument()
    extra = true
    rerender(ui("reports"))  // 다른 화면으로 가면 목록을 다시 읽는다
    expect(await nav().findByRole("button", { name: "분석 리포트(새로 완료된 리포트 1개)" })).toBeInTheDocument()
    expect(window.sessionStorage.getItem(SEEN_KEYS.mock)).toBeNull()
  })
})
