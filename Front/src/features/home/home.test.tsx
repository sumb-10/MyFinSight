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

// 홈 화면 (2026-11-17 시안 3 이식): 왼쪽 새 분석 카드 · 오른쪽 「내게 맞는 정보」 탭 · 시작 화면 · 예시 문장 · 성향 맞춤 섹터 · 예시 리포트 숨김 · 홈 둘러보기

beforeAll(() => { globalThis.ResizeObserver ??= class { observe() {} unobserve() {} disconnect() {} } as unknown as typeof ResizeObserver; Element.prototype.scrollIntoView = vi.fn() })
beforeEach(() => { try { window.localStorage.clear() } catch { /* ignore */ } resetExampleMemory(); window.history.replaceState(null, "", "/") })
afterEach(() => vi.restoreAllMocks())

const mock = () => new MockService({ latencyMs: 0, persist: false })
const show = (svc: AnalysisService) => render(<Providers service={svc}><HomeScreen /></Providers>)
/** 오른쪽 카드에서 탭을 열고 그 내용(tabpanel)을 돌려준다 */
const openTab = async (name: string) => { fireEvent.click(await screen.findByRole("tab", { name }, { timeout: 5000 })); return screen.getByRole("tabpanel") }
const box = () => openTab("요즘 강한 섹터")
const sectors = (b: HTMLElement) => within(b).getByRole("list", { name: "많이 오른 섹터" })
const ready: ProposedSectorTrends = { status: "ready", progress: 1, data: SECTOR_TRENDS, error: null }

describe("요즘 강한 섹터 탭", () => {
  it("내 투자 대상 시장(미국)의 좋았던 섹터 3개를 수익률·상승 종목 수와 함께 보여 주고, 한국으로 바꿀 수 있다", async () => {
    show(mock())
    const b = await box()
    expect(await within(b).findByText("최근 한 달 · 기준일 2026-10-30")).toBeInTheDocument()
    expect(within(sectors(b)).getAllByRole("listitem").map((li) => li.querySelector("span span")?.textContent)).toEqual(["경기소비재", "필수소비재", "헬스케어"])  // 평균 수익률 순
    expect(within(sectors(b)).getByText("+10.60%")).toBeInTheDocument()
    expect(within(sectors(b)).getByText("49개 중 41개 상승")).toBeInTheDocument()
    expect(within(b).getByRole("heading", { name: "경기소비재에서 많이 오른 종목" })).toBeInTheDocument()  // 고른 섹터의 종목
    fireEvent.click(within(b).getByRole("button", { name: "한국" }))
    expect(within(sectors(b)).getByText("커뮤니케이션 서비스")).toBeInTheDocument()
    expect(within(b).queryByText("경기소비재")).toBeNull()
    expect(within(b).queryByText("부동산")).toBeNull()  // 종목 1개 섹터는 뺀다
  })

  it("섹터를 고르면 그 섹터의 추천 문장이 나오고, 누르면 그 문장으로 「분석 시작하기」를 누른 것과 같다", async () => {
    const svc = mock()
    const create = vi.spyOn(svc, "createRequest")
    show(svc)
    const b = await box()
    expect(await within(b).findByRole("button", { name: "요즘 많이 오른 미국 경기소비재 기업에 나눠 투자하고 싶어요." })).toBeInTheDocument()  // 처음에는 1위 섹터
    fireEvent.click(within(sectors(b)).getByRole("button", { name: /필수소비재/ }))
    fireEvent.click(within(b).getByRole("button", { name: "요즘 많이 오른 미국 필수소비재 기업에 나눠 투자하고 싶어요." }))
    await waitFor(() => expect(create).toHaveBeenCalledWith({ idea: "요즘 많이 오른 미국 필수소비재 기업에 나눠 투자하고 싶어요.", mode: "new", overrides: {} }))
    await waitFor(() => expect(window.location.hash).toMatch(/^#\/analysis\//))
  })

  it("서비스에 섹터 기능이 없으면 그 탭 없이 그린다", async () => {
    const s = mock()
    show(Object.assign(Object.create(s), { getSectorTrends: undefined }) as AnalysisService)
    expect(await screen.findByRole("textbox", { name: "투자하고 싶은 내용" }, { timeout: 5000 })).toBeInTheDocument()
    expect(await screen.findByRole("tab", { name: "내 투자조건" })).toBeInTheDocument()
    expect(screen.queryByRole("tab", { name: "요즘 강한 섹터" })).toBeNull()
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
  it("예시 문장 3개를 보여 주고, 누르면 그 문장으로 요청을 만든다", async () => {
    const svc = mock()
    const create = vi.spyOn(svc, "createRequest")
    show(svc)
    const list = await screen.findByRole("list", { name: "예시 문장" }, { timeout: 5000 })
    expect(within(list).getAllByRole("button").map((b) => b.textContent)).toEqual(EXAMPLE_IDEAS)
    fireEvent.click(within(list).getByRole("button", { name: EXAMPLE_IDEAS[1] }))
    await waitFor(() => expect(create).toHaveBeenCalledWith({ idea: EXAMPLE_IDEAS[1], mode: "new", overrides: {} }))
  })

  it("새 분석 카드: 안내 제목·문장, 둘러보기·리포트 보는 법 버튼", async () => {
    show(mock())
    expect(await screen.findByRole("heading", { name: "투자 아이디어를 적어 주세요" }, { timeout: 5000 })).toBeInTheDocument()
    expect(screen.getByText("내 투자조건에 맞는 종목과 비중을 고르고, 과거 성과와 위험을 리포트로 보여드립니다.")).toBeInTheDocument()
    expect(screen.getByRole("button", { name: "둘러보기" })).toBeInTheDocument()
    fireEvent.click(screen.getByRole("button", { name: "리포트 보는 법" }))
    expect(window.location.hash).toBe("#/tutorial")
  })

  it("첫 탭: 리포트가 있으면 「요즘 강한 섹터」, 없으면(처음 쓰는 사람) 「이렇게 진행돼요」", async () => {
    const first = show(mock())
    await waitFor(() => expect(screen.getByRole("tab", { name: "요즘 강한 섹터" })).toHaveAttribute("aria-selected", "true"), { timeout: 5000 })
    first.unmount()
    show(Object.assign(Object.create(mock()), { listReports: async () => [] }) as AnalysisService)
    await waitFor(() => expect(screen.getByRole("tab", { name: "이렇게 진행돼요" })).toHaveAttribute("aria-selected", "true"), { timeout: 5000 })
    expect(within(screen.getByRole("list", { name: "분석 순서" })).getAllByRole("listitem")).toHaveLength(5)
  })

  it("저장된 기본 투자조건은 항목·값 한 줄씩, 아래에 성향에 맞춘 섹터 문장", async () => {
    show(mock())
    const card = await openTab("내 투자조건")
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
    const card = await openTab("내 투자조건")
    expect(card.querySelector("dd")).toHaveTextContent(/^매달 50만원$/)
  })
})

describe("예시 리포트는 홈 최근 리포트·사이드바에 보이지 않는다", () => {
  // 예시 리포트는 목업 「정상 추천」 리포트와 이름이 같아, 서버 리포트가 없을 때 예시 줄이 생기지 않는지로 본다 (리포트 목록 화면에는 그대로 있다)
  const empty = () => Object.assign(Object.create(mock()), { listReports: async () => [] }) as AnalysisService
  it("홈 최근 리포트 탭", async () => {
    show(empty())
    const card = await openTab("최근 리포트")
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

describe("홈 둘러보기", () => {
  it("홈 요소를 차례로 비추고(탭 안의 대상은 그 탭을 열어서), 마치기·Esc 로 닫는다", async () => {
    render(<Providers service={mock()}><Sidebar route={{ page: "home" }} /><HomeScreen /></Providers>)
    await box()
    fireEvent.click(screen.getByRole("button", { name: "둘러보기" }))
    const dlg = () => screen.getByRole("dialog")
    expect(dlg()).toHaveTextContent(`1/${HOME_TOUR_STEPS.length}`)
    expect(dlg()).toHaveTextContent("메뉴")
    for (let i = 1; i < HOME_TOUR_STEPS.length; i++) {  // 단계마다 그 대상이 화면에 있다
      fireEvent.click(within(dlg()).getByRole("button", { name: "다음" }))
      expect(dlg()).toHaveTextContent(`${i + 1}/${HOME_TOUR_STEPS.length}`)
      const t = HOME_TOUR_STEPS[i].target
      await waitFor(() => expect(document.querySelector(`[data-tour="${t}"]`), t).not.toBeNull())
    }
    expect(screen.getByRole("tab", { name: "최근 리포트" })).toHaveAttribute("aria-selected", "true")  // 마지막 단계에서 그 탭이 열려 있다
    fireEvent.keyDown(window, { key: "Escape" })
    expect(screen.queryByTestId("coachmark")).toBeNull()
    fireEvent.click(screen.getByRole("button", { name: "둘러보기" }))
    expect(within(dlg()).getByRole("heading")).toHaveTextContent("메뉴")
    for (let i = 1; i < HOME_TOUR_STEPS.length; i++) fireEvent.click(screen.getByRole("button", { name: "다음" }))
    expect(screen.getByRole("dialog")).toHaveTextContent(`${HOME_TOUR_STEPS.length}/${HOME_TOUR_STEPS.length}`)
    fireEvent.click(screen.getByRole("button", { name: "마치기" }))
    expect(screen.queryByTestId("coachmark")).toBeNull()
  })
})
