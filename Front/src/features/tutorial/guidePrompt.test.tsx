import { beforeEach, describe, expect, it, vi } from "vitest"
import { fireEvent, render, screen, waitFor, within } from "@testing-library/react"
import { Providers } from "../../app/providers"
import { Sidebar } from "../../app/App"
import { parseRoute, routePath } from "../../app/router"
import type { AnalysisService } from "../../api/service"
import { RunScreen } from "../run/RunScreen"
import { guideDestination } from "./GuidePrompt"
import { clearGuideRecord, guideRecord, recordGuide } from "./guideRecord"
import { TutorialScreen } from "./TutorialScreen"
import { loadTutorialDoc } from "./tutorialService"

const TITLE = "리포트 가이드를 보시겠습니까?"
const svc = {
  mode: "api", health: () => Promise.resolve({ ok: true, api_version: "1", llm_mode: "api", db: { ok: true }, worker: { alive: true, running_run_id: null }, queue_length: 0 }),
  options: () => Promise.reject(new Error("쓰지 않음")), getProfile: () => Promise.resolve(null), listRequests: () => Promise.resolve([]), listRuns: () => Promise.resolve([]), listReports: () => Promise.resolve([]), listPaper: () => Promise.resolve([]),
  getReportComparison: () => Promise.resolve(null), getRunPartial: () => Promise.resolve(null),
  getRun: () => Promise.resolve({ run_id: "run1", request_id: "r1", report_id: "rep1", status: "success", queue_position: null, queued_at: "2026-11-01T10:00:00", started_at: "2026-11-01T10:00:01", finished_at: "2026-11-01T10:05:00", buckets: [], steps: [] }),
} as unknown as AnalysisService

const sidebar = () => { render(<Providers service={svc}><Sidebar route={{ page: "home" }} /></Providers>); return within(screen.getByRole("navigation", { name: "주 메뉴" })).getByRole("button", { name: /분석 리포트/ }) }
const runButton = async () => { render(<Providers service={svc}><RunScreen runId="run1" /></Providers>); return screen.findByRole("button", { name: "리포트 보기" }) }
const dialog = () => screen.queryByRole("dialog", { name: TITLE })
const answer = (name: "예" | "아니요") => fireEvent.click(within(dialog()!).getByRole("button", { name }))
const tour = (after: Parameters<typeof TutorialScreen>[0]["after"]) => { render(<TutorialScreen load={loadTutorialDoc} after={after} />); return screen.findByRole("button", { name: "건너뛰기" }, { timeout: 10000 }) }

beforeEach(() => { window.localStorage.clear(); clearGuideRecord(); window.location.hash = ""; vi.spyOn(window, "scrollTo").mockImplementation(() => {}) })

describe("리포트 가이드 안내 창", () => {
  it("사이드바 「분석 리포트」: 처음에는 이동을 멈추고 묻고, 「예」면 돌아갈 곳(목록)을 담아 튜토리얼로 간다", () => {
    fireEvent.click(sidebar())
    expect(dialog()).toBeInTheDocument()
    expect(window.location.hash).toBe("")
    answer("예")
    expect(window.location.hash).toBe("#/tutorial?next=reports")
    expect(dialog()).toBeNull()
  })

  it("진행 화면 「리포트 보기」: 「예」면 만든 리포트를 돌아갈 곳으로 담는다", async () => {
    fireEvent.click(await runButton())
    answer("예")
    expect(window.location.hash).toBe("#/tutorial?report=rep1")
  })

  it("「아니요」는 원래 가려던 곳으로 가고 거절을 기록해 다시 묻지 않는다", async () => {
    fireEvent.click(await runButton())
    answer("아니요")
    expect(window.location.hash).toBe("#/reports/rep1")
    expect(guideRecord()).toBe("declined")
    fireEvent.click(screen.getByRole("button", { name: "리포트 보기" }))
    expect(dialog()).toBeNull()
  })

  it("리포트가 이미 있고 예전 로컬 기록이 남아 있는 사용자에게도 처음 한 번은 묻는다 (새 키만 본다)", async () => {
    window.localStorage.setItem("myfinsight.seen.v1", JSON.stringify({ v: 1, reports: ["rep_old"], papers: {} }))
    window.localStorage.setItem("myfinsight.exampleReport.v1", "hidden")
    window.localStorage.setItem("myfinsight.ui.v1", JSON.stringify({ version: 1, lastRoute: "#/tutorial" }))
    const withReports = { ...svc, listReports: () => Promise.resolve([{ run_id: "rep_old", report_id: "rep_old", created_at: "2026-11-01T10:00:00", as_of: "2026-10-30" }]) } as unknown as AnalysisService
    render(<Providers service={withReports}><Sidebar route={{ page: "home" }} /></Providers>)
    fireEvent.click(await within(screen.getByRole("navigation", { name: "주 메뉴" })).findByRole("button", { name: /분석 리포트/ }))
    expect(dialog()).toBeInTheDocument()
    expect(guideRecord()).toBeNull()
  })

  it("닫기·Esc 는 기록 없이 그 자리에 머물러 다음에 다시 묻는다", () => {
    const b = sidebar()
    fireEvent.click(b)
    fireEvent.keyDown(window, { key: "Escape" })
    expect(dialog()).toBeNull()
    expect(window.location.hash).toBe("")
    expect(guideRecord()).toBeNull()
    fireEvent.click(b)
    fireEvent.click(within(dialog()!).getByRole("button", { name: "닫기" }))
    expect(guideRecord()).toBeNull()
    fireEvent.click(b)
    expect(dialog()).toBeInTheDocument()
  })

  it("다른 경로로 둘러보기를 시작했으면 묻지 않고, 기록을 지우면 다시 묻는다", async () => {
    await tour(null)
    expect(guideRecord()).toBe("seen")
    fireEvent.click(sidebar())
    expect(dialog()).toBeNull()
    expect(window.location.hash).toBe("#/reports")
    clearGuideRecord()
    fireEvent.click(within(screen.getByRole("navigation", { name: "주 메뉴" })).getByRole("button", { name: /분석 리포트/ }))
    expect(dialog()).toBeInTheDocument()
  }, 20000)

  it("거절 기록이 있어도 튜토리얼은 언제든 열 수 있다", async () => {
    recordGuide("declined")
    await tour(null)
    expect(screen.getByTestId("coachmark")).toBeInTheDocument()
  }, 20000)
})

describe("가이드를 마친 뒤 이동", () => {
  it("건너뛰기: 목록에서 왔으면 목록으로", async () => {
    fireEvent.click(await tour({ page: "reports" }))
    expect(window.location.hash).toBe("#/reports")
  }, 20000)

  it("Esc·마치기: 진행 화면에서 왔으면 그 리포트로, 띠의 버튼도 같은 곳으로", async () => {
    await tour({ page: "report", reportId: "rep1" })
    expect(screen.getByRole("button", { name: "내 리포트 보기" })).toBeInTheDocument()
    expect(screen.queryByRole("button", { name: /내 분석 시작하기/ })).toBeNull()
    await waitFor(() => { fireEvent.keyDown(window, { key: "Escape" }); expect(window.location.hash).toBe("#/reports/rep1") })  // 리포트를 그리는 동안 키 입력 연결이 늦을 수 있다
  }, 20000)

  it("돌아갈 곳이 없으면 기존처럼 그 자리에서 끝나고 「내 분석 시작하기」가 남는다", async () => {
    fireEvent.click(await tour(null))
    expect(window.location.hash).toBe("")
    expect(screen.getByRole("button", { name: /내 분석 시작하기/ })).toBeInTheDocument()
  }, 20000)

  it("주소 왕복", () => {
    for (const hash of ["#/tutorial", "#/tutorial?next=reports", "#/tutorial?report=run_1"]) expect(routePath(parseRoute(hash))).toBe(hash)
    expect(guideDestination({ page: "tutorial", reportId: "run_1" })).toEqual({ page: "report", reportId: "run_1" })
    expect(guideDestination({ page: "tutorial", next: "reports" })).toEqual({ page: "reports" })
    expect(guideDestination({ page: "tutorial" })).toBeNull()
  })
})
