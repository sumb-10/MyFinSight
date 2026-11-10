import { afterEach, beforeAll, beforeEach, describe, expect, it, vi } from "vitest"
import { fireEvent, render, screen, waitFor, within } from "@testing-library/react"
import { Providers } from "../../app/providers"
import { Sidebar } from "../../app/App"
import type { AnalysisService } from "../../api/service"
import type { ProposedSectorTrends } from "../../api/proposed"
import { MockService } from "../../mocks/services/MockService"
import { SECTOR_TRENDS } from "../../mocks/data/sectorTrends"
import { EXAMPLE_ROW, resetExampleMemory } from "../tutorial/exampleReport"
import { HOME_TOUR_STEPS } from "../tutorial/homeSteps"
import { EXAMPLE_IDEAS, HomeScreen } from "./HomeScreen"
import { readCachedTrends, scopeOf } from "./sectorTrends"

// 홈 화면 개편 (2026-11-11): 섹터 상자·시작 화면·예시 문장·성향 맞춤 섹터·예시 리포트 숨김·홈 둘러보기

beforeAll(() => { globalThis.ResizeObserver ??= class { observe() {} unobserve() {} disconnect() {} } as unknown as typeof ResizeObserver; Element.prototype.scrollIntoView = vi.fn() })
beforeEach(() => { try { window.localStorage.clear() } catch { /* ignore */ } resetExampleMemory(); window.history.replaceState(null, "", "/") })
afterEach(() => vi.restoreAllMocks())

const mock = () => new MockService({ latencyMs: 0, persist: false })
const show = (svc: AnalysisService) => render(<Providers service={svc}><HomeScreen /></Providers>)
const box = async () => (await screen.findByRole("heading", { name: "요즘엔 뭐가 좋아요?" }, { timeout: 5000 })).closest("section")!
const ready: ProposedSectorTrends = { status: "ready", progress: 1, data: SECTOR_TRENDS, error: null }

describe("요즘엔 뭐가 좋아요? 상자", () => {
  it("내 투자 대상 시장(미국)의 좋았던 섹터 3개를 수익률·상승 종목 수와 함께 보여 주고, 한국으로 바꿀 수 있다", async () => {
    show(mock())
    const b = await box()
    expect(within(b).getByText("최근 한 달 · 기준일 2026-10-30")).toBeInTheDocument()
    expect(within(b).getAllByRole("listitem").map((li) => li.querySelector("span span")?.textContent)).toEqual(["경기소비재", "필수소비재", "헬스케어"])  // 평균 수익률 순
    expect(within(b).getByText("+10.60%")).toBeInTheDocument()
    expect(within(b).getByText("종목 49개 중 41개 상승")).toBeInTheDocument()
    fireEvent.click(within(b).getByRole("button", { name: "한국" }))
    expect(within(b).getByText("커뮤니케이션 서비스")).toBeInTheDocument()
    expect(within(b).queryByText("경기소비재")).toBeNull()
    expect(within(b).queryByText("부동산")).toBeNull()  // 종목 1개 섹터는 뺀다
  })

  it("섹터를 고르면 그 섹터의 추천 문장이 나오고, 누르면 그 문장으로 투자조건 확인하기를 누른 것과 같다", async () => {
    const svc = mock()
    const create = vi.spyOn(svc, "createRequest")
    show(svc)
    const b = await box()
    expect(within(b).getByRole("button", { name: "* 요즘 많이 오른 미국 경기소비재 기업에 나눠 투자하고 싶어요." })).toBeInTheDocument()  // 처음에는 1위 섹터
    fireEvent.click(within(b).getByRole("button", { name: /필수소비재/ }))
    fireEvent.click(within(b).getByRole("button", { name: "* 요즘 많이 오른 미국 필수소비재 기업에 나눠 투자하고 싶어요." }))
    await waitFor(() => expect(create).toHaveBeenCalledWith({ idea: "요즘 많이 오른 미국 필수소비재 기업에 나눠 투자하고 싶어요.", mode: "new", overrides: {} }))
    await waitFor(() => expect(window.location.hash).toMatch(/^#\/analysis\//))
  })

  it("서비스에 섹터 기능이 없으면 상자 없이 입력창만 그린다", async () => {
    const s = mock()
    show(Object.assign(Object.create(s), { getSectorTrends: undefined }) as AnalysisService)
    expect(await screen.findByRole("textbox", { name: "투자하고 싶은 내용" }, { timeout: 5000 })).toBeInTheDocument()
    expect(screen.queryByRole("heading", { name: "요즘엔 뭐가 좋아요?" })).toBeNull()
    expect(screen.queryByTestId("splash")).toBeNull()
  })

  it("불러오지 못하면 상자 안에 다시 시도를 둔다", async () => {
    const s = mock()
    let n = 0
    const svc = Object.assign(Object.create(s), { getSectorTrends: async () => { n += 1; if (n === 1) throw new Error("연결 끊김"); return ready } }) as AnalysisService
    show(svc)
    const b = await box()
    expect(await within(b).findByText("섹터 자료를 불러오지 못했습니다.")).toBeInTheDocument()
    expect(screen.queryByTestId("splash")).toBeNull()
    fireEvent.click(within(b).getByRole("button", { name: "다시 시도" }))
    expect(await within(b).findByText("경기소비재")).toBeInTheDocument()
  })
})

describe("처음 불러올 때 시작 화면", () => {
  it("저장한 자료가 없으면 화면 전체에 문구·로딩바·%를 띄우고, 다 받으면 걷는다. 다음부터는 저장한 자료를 바로 보여 준다", async () => {
    const s = mock()
    const seq: ProposedSectorTrends[] = [{ status: "loading", progress: 0.4, data: null, error: null }, { status: "loading", progress: 0.75, data: null, error: null }, ready]
    let i = 0
    const svc = Object.assign(Object.create(s), { getSectorTrends: async () => seq[Math.min(i++, seq.length - 1)] }) as AnalysisService
    const first = show(svc)
    expect(await screen.findByTestId("splash")).toHaveTextContent("MyFinSight, 당신의 투자 도우미")
    const shown = () => Number(within(screen.getByTestId("splash")).getByRole("progressbar").getAttribute("aria-valuenow"))
    await waitFor(() => expect(shown()).toBeGreaterThanOrEqual(40))  // 서버 진행률(0.4)을 따라 숫자가 올라간다
    expect(screen.getByTestId("splash")).toHaveTextContent(`${shown()}%`)
    expect(await screen.findByText("경기소비재", {}, { timeout: 4000 })).toBeInTheDocument()
    const held = screen.queryByTestId("splash")  // 계산을 기다렸으면 100% 를 0.3초 보여 준 뒤 걷는다 (느린 환경에서는 이미 걷혔을 수 있다)
    if (held) expect(held).toHaveTextContent("100%")
    await waitFor(() => expect(screen.queryByTestId("splash")).toBeNull(), { timeout: 2000 })
    expect(readCachedTrends()?.as_of).toBe(SECTOR_TRENDS.as_of)
    first.unmount()
    i = 0  // 서버는 다시 계산 중이어도
    show(svc)
    expect(screen.queryByTestId("splash")).toBeNull()
    expect(await within(await box()).findByText("경기소비재")).toBeInTheDocument()  // 저장해 둔 자료로 바로
  })

  it("서버가 바로 준비된 자료를 주면 시작 화면을 100% 로 붙잡지 않고 바로 걷는다", async () => {
    const s = mock()
    show(Object.assign(Object.create(s), { getSectorTrends: async () => ready }) as AnalysisService)
    expect(await within(await box()).findByText("경기소비재")).toBeInTheDocument()
    expect(screen.queryByTestId("splash")).toBeNull()  // 자료가 그려진 그 순간에 이미 없다
  })

  it("서버가 지난 자료를 함께 주면 시작 화면 없이 그것부터 보여 준다", async () => {
    const s = mock()
    const svc = Object.assign(Object.create(s), { getSectorTrends: async () => ({ status: "loading", progress: 0.2, data: SECTOR_TRENDS, error: null }) }) as AnalysisService
    show(svc)
    expect(await within(await box()).findByText("경기소비재")).toBeInTheDocument()
    await waitFor(() => expect(screen.queryByTestId("splash")).toBeNull())
  })
})

describe("입력창·문구·기본 투자조건", () => {
  it("예시 문장 3개를 '*' 와 함께 보여 주고, 누르면 그 문장으로 요청을 만든다", async () => {
    const svc = mock()
    const create = vi.spyOn(svc, "createRequest")
    show(svc)
    const list = await screen.findByRole("list", { name: "예시 문장" }, { timeout: 5000 })
    expect(within(list).getAllByRole("button").map((b) => b.textContent)).toEqual(EXAMPLE_IDEAS.map((t) => `* ${t}`))
    fireEvent.click(within(list).getByRole("button", { name: `* ${EXAMPLE_IDEAS[1]}` }))
    await waitFor(() => expect(create).toHaveBeenCalledWith({ idea: EXAMPLE_IDEAS[1], mode: "new", overrides: {} }))
  })

  it("바뀐 문구: 안내 문장, 둘러보기 버튼 두 개, 지운 문구", async () => {
    show(mock())
    expect(await screen.findByText("내 투자조건을 반영해 종목을 고르고, 과거 데이터로 성과와 위험을 검증합니다. 투자하고 싶은 내용을 아래 채팅창에 입력하세요.", {}, { timeout: 5000 })).toBeInTheDocument()
    expect(screen.getByRole("button", { name: "리포트 보는 법 둘러보기" })).toBeInTheDocument()
    expect(screen.getByRole("button", { name: "처음이신가요? MyFinSight 둘러보기" })).toBeInTheDocument()
    expect(screen.queryByText(/이번 분석에서만 바꿀 수 있습니다/)).toBeNull()
    expect(screen.queryByText(/분석 시작」을 눌러야 시작됩니다/)).toBeNull()
    expect(screen.queryByText(/부족한 조건은 분석 모델이/)).toBeNull()
    fireEvent.click(screen.getByRole("button", { name: "리포트 보는 법 둘러보기" }))
    expect(window.location.hash).toBe("#/tutorial")
  })

  it("저장된 기본 투자조건은 항목·값 한 줄씩, 맨 아래에 성향에 맞춘 섹터 문장", async () => {
    show(mock())
    const card = (await screen.findByRole("heading", { name: "저장된 기본 투자조건" }, { timeout: 5000 })).closest("section")!
    const pairs = Array.from(card.querySelectorAll("dt")).map((dt) => [dt.textContent, dt.nextElementSibling?.textContent])
    expect(pairs).toEqual([["금액", "2,000만원 · 매달 50만원"], ["기간", "5년"], ["성향", "위험중립형 · 손실 감내 30%"], ["투자 대상", "S&P 500 · NASDAQ-100"], ["종목 고르기", "모멘텀 · 시가총액비중 · 종목당 최대 30%"]])
    expect(within(card).getByText("NVDA 필수 포함")).toBeInTheDocument()
    expect(within(card).getByText("TSLA 제외")).toBeInTheDocument()
    const pick = SECTOR_TRENDS.picks[scopeOf(["SP500", "NASDAQ100"])].위험중립형!
    expect(pick.name_ko).toBe("필수소비재")  // 수익률÷변동성 1위
    expect(await within(card).findByTestId("tendency-sector")).toHaveTextContent("위험중립형에 맞는 섹터는 미국 필수소비재입니다. 최근 한 달 +9.90% 올랐고, 주가 오르내림에 비해 오른 폭이 가장 컸습니다.")
  })

  it("초기 금액이 0원이면 매달 적립액만 보여 준다", async () => {
    const s = mock()
    const v = (await s.getProfile())!
    show(Object.assign(Object.create(s), { getProfile: async () => ({ ...v, profile: { ...v.profile, capital: { ...v.profile.capital, initial_amount: 0, monthly_contribution: 500_000 } } }) }) as AnalysisService)
    const card = (await screen.findByRole("heading", { name: "저장된 기본 투자조건" }, { timeout: 5000 })).closest("section")!
    expect(card.querySelector("dd")).toHaveTextContent(/^매달 50만원$/)
  })
})

describe("예시 리포트는 홈 최근 리포트·사이드바에 보이지 않는다", () => {
  // 예시 리포트는 목업 「정상 추천」 리포트와 이름이 같아, 서버 리포트가 없을 때 예시 줄이 생기지 않는지로 본다 (리포트 목록 화면에는 그대로 있다)
  const empty = () => Object.assign(Object.create(mock()), { listReports: async () => [] }) as AnalysisService
  it("홈 최근 분석 리포트", async () => {
    show(empty())
    const card = (await screen.findByRole("heading", { name: "최근 분석 리포트" }, { timeout: 5000 })).closest("section")!
    expect(await within(card).findByText("아직 완료된 분석이 없습니다.")).toBeInTheDocument()
    expect(within(card).queryByText(EXAMPLE_ROW.name)).toBeNull()
  })
  it("사이드바 최근 리포트", async () => {
    render(<Providers service={empty()}><Sidebar route={{ page: "home" }} /></Providers>)
    expect(await screen.findByText("아직 리포트가 없습니다.")).toBeInTheDocument()
    expect(screen.queryByText(EXAMPLE_ROW.name)).toBeNull()
    expect(screen.queryByText("리포트 보는 법 예시")).toBeNull()
  })
})

describe("처음이신가요? MyFinSight 둘러보기", () => {
  it("홈 요소를 차례로 비추고, 마치기·Esc 로 닫는다", async () => {
    render(<Providers service={mock()}><Sidebar route={{ page: "home" }} /><HomeScreen /></Providers>)
    await box()
    fireEvent.click(screen.getByRole("button", { name: "처음이신가요? MyFinSight 둘러보기" }))
    const dlg = () => screen.getByRole("dialog")
    expect(dlg()).toHaveTextContent(`1/${HOME_TOUR_STEPS.length}`)
    expect(dlg()).toHaveTextContent("메뉴")
    for (const t of HOME_TOUR_STEPS.slice(1).map((s) => s.target)) expect(document.querySelector(`[data-tour="${t}"]`), t).not.toBeNull()  // 모든 단계의 대상이 화면에 있다
    fireEvent.click(within(dlg()).getByRole("button", { name: "다음" }))
    expect(dlg()).toHaveTextContent(`2/${HOME_TOUR_STEPS.length}`)
    expect(within(dlg()).getByRole("heading")).toHaveTextContent("요즘엔 뭐가 좋아요?")
    fireEvent.keyDown(window, { key: "Escape" })
    expect(screen.queryByTestId("coachmark")).toBeNull()
    fireEvent.click(screen.getByRole("button", { name: "처음이신가요? MyFinSight 둘러보기" }))
    for (let i = 1; i < HOME_TOUR_STEPS.length; i++) fireEvent.click(screen.getByRole("button", { name: "다음" }))
    expect(screen.getByRole("dialog")).toHaveTextContent(`${HOME_TOUR_STEPS.length}/${HOME_TOUR_STEPS.length}`)
    fireEvent.click(screen.getByRole("button", { name: "마치기" }))
    expect(screen.queryByTestId("coachmark")).toBeNull()
  })
})
