import { afterEach, beforeAll, describe, expect, it, vi } from "vitest"
import { fireEvent, render, screen, within } from "@testing-library/react"
import { Providers } from "../app/providers"
import type { AnalysisService } from "../api/service"
import type { ProfileView } from "../api/types"
import { reportName } from "../lib/reportName"
import { HomeScreen } from "./home/HomeScreen"
import { PaperScreen } from "./paper/PaperScreen"
import { StartPaperDialog } from "./paper/StartPaperDialog"
import { MockService } from "../mocks/services/MockService"
import { REPORTS } from "../mocks/scenarios"

// 6단계: 일반 모드에 반영한 세 가지 기능. 제안 메서드가 없는 서비스(실제 서버와 같은 모양)로 확인한다. 자료는 목업 시나리오를 빌려 쓴다.

beforeAll(() => { globalThis.ResizeObserver ??= class { observe() {} unobserve() {} disconnect() {} } as unknown as typeof ResizeObserver; Element.prototype.scrollIntoView = vi.fn() })
afterEach(() => window.history.replaceState(null, "", "/"))

const PROPOSED = ["getReportName", "renameReport", "deleteReport", "searchStocks", "getStocks", "getProfileVersion", "recommendStrategy", "getQuestionBatch", "answerBatch", "getMessageResults", "getRunWarnings", "getPaperKrw", "getPaperName", "setPaperName"]
const normal = (over: Partial<Record<keyof AnalysisService, unknown>> = {}): AnalysisService => {
  const s = new MockService({ latencyMs: 0, persist: false })
  return Object.assign(Object.create(s), { mode: "api", ...Object.fromEntries(PROPOSED.map((k) => [k, undefined])),
    listReports: async () => (await s.listReports()).map(({ proposed_name: _n, ...r }) => r), ...over })
}
const show = (svc: AnalysisService, ui: React.ReactNode) => render(<Providers service={svc}>{ui}</Providers>)

describe("10-1 홈 요약 카드의 필수 포함 종목", () => {
  it("저장된 필수 포함 종목을 티커 그대로 제외 종목과 함께 보여 준다", async () => {
    show(normal(), <HomeScreen />)
    expect(await screen.findByText("NVDA 필수 포함", {}, { timeout: 5000 })).toBeInTheDocument()
    expect(screen.getByText("TSLA 제외")).toBeInTheDocument()
  })
  it("필수 포함 종목이 없으면 아무것도 덧붙이지 않는다", async () => {
    const base = new MockService({ latencyMs: 0, persist: false })
    const v = (await base.getProfile())!
    const empty: ProfileView = { ...v, profile: { ...v.profile, constraints: { ...v.profile.constraints, must_include_tickers: [] } } }
    show(normal({ getProfile: async () => empty }), <HomeScreen />)
    expect(await screen.findByText("TSLA 제외", {}, { timeout: 5000 })).toBeInTheDocument()
    expect(screen.queryByText(/필수 포함$/)).toBeNull()
  })
})

describe("10-3 리포트 이름 표시 기준", () => {
  it("투자 아이디어(첫 줄) → 요청 요약 → 선택 전략 → 실행 ID 순서, 목업 제안 이름이 있으면 그것", () => {
    const row = { run_id: "run_1", idea: "  반도체에\n투자 ", request_summary: "요약", strategy_name: "동일비중" }
    expect(reportName(row)).toBe("반도체에")
    expect(reportName({ ...row, idea: "" })).toBe("요약")
    expect(reportName({ ...row, idea: "", request_summary: null })).toBe("동일비중")
    expect(reportName({ run_id: "run_1", idea: "", request_summary: null, strategy_name: null })).toBe("run_1")
    expect(reportName({ ...row, proposed_name: { display_ko: "내 이름" } } as never)).toBe("내 이름")
  })
  it("홈 「최근 분석 리포트」도 같은 이름", async () => {
    show(normal(), <HomeScreen />)
    const card = (await screen.findByRole("heading", { name: "최근 분석 리포트" }, { timeout: 5000 })).parentElement!.parentElement!
    expect(await within(card).findByText(REPORTS[0].idea)).toBeInTheDocument()
  })
})

describe("10-2 같은 리포트로 만든 여러 모의투자 구분", () => {
  it("목록: 이름 아래 적용 전략(이름과 다를 때)과 원본 리포트를 한 줄씩, 시작일·초기자본은 옆 열 (ID·중복 줄 없음)", async () => {
    show(normal(), <PaperScreen />)
    const row = (await screen.findByRole("cell", { name: "2026-06-01" }, { timeout: 5000 })).closest("tr")!
    expect(within(row).getByText("동일비중")).toBeInTheDocument()
    expect(within(row).getByText(`원본 리포트: ${REPORTS[0].idea}`)).toBeInTheDocument()
    expect(within(row).getByRole("cell", { name: "10,000,000원" })).toBeInTheDocument()
    const table = row.closest("table")!
    expect(table).not.toHaveTextContent(/시작 · 초기|같은 리포트 모의투자|mock_paper_/)
    expect(within(table).getByRole("columnheader", { name: "모의투자" })).toBeInTheDocument()
  })
  it("상세: 버튼은 머리말 오른쪽, 원본 리포트·같은 리포트의 다른 모의투자(목록 창)는 「더보기」 안 (본문 줄은 없다)", async () => {
    show(normal(), <PaperScreen paperId="mock_paper_a1" />)
    const more = await screen.findByRole("button", { name: "더보기" }, { timeout: 5000 })
    expect(screen.queryByText(/같은 리포트로 시작한 다른 모의투자/)).toBeNull()
    expect(screen.queryByRole("button", { name: "원본 리포트" })).toBeNull()
    expect(screen.queryByRole("button", { name: REPORTS[0].idea })).toBeNull()
    expect(within(more.closest("header")!).getByRole("button", { name: "최신 자료로 갱신" })).toBeInTheDocument()
    fireEvent.click(more)
    expect(screen.queryByRole("menuitem", { name: "이름 바꾸기" })).toBeNull()
    fireEvent.click(screen.getByRole("menuitem", { name: "같은 리포트로 시작한 다른 모의투자 2개" }))
    const dlg = screen.getByRole("dialog", { name: "같은 리포트로 시작한 다른 모의투자 2개" })
    fireEvent.click(within(dlg).getByRole("button", { name: /2026-08-03 시작 · 초기 5,000,000원/ }))
    expect(window.location.hash).toBe("#/paper/mock_paper_a2")
    expect(screen.queryByRole("dialog")).toBeNull()
    fireEvent.click(more)
    fireEvent.click(screen.getByRole("menuitem", { name: "원본 리포트 보기" }))
    expect(window.location.hash).toBe(`#/reports/${REPORTS[0].id}`)
  })
  it("시작 창: 이 리포트로 이미 시작한 모의투자를 같은 표기로 보여 준다 (이름 선택은 없다)", async () => {
    show(normal(), <StartPaperDialog reportId={REPORTS[0].run_id} close={() => {}} />)
    expect(await screen.findByText("이 리포트로 이미 시작한 모의투자 3개", {}, { timeout: 5000 })).toBeInTheDocument()
    expect(screen.queryByRole("radio")).toBeNull()
  })
})
