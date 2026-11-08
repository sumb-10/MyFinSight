import { afterEach, beforeAll, describe, expect, it, vi } from "vitest"
import { fireEvent, render, screen, waitFor, within } from "@testing-library/react"
import { ServiceContext } from "../app/providers"
import type { AnalysisService } from "../api/service"
import type { ProposedExecution, ProposedReport } from "../api/proposed"
import type { ReportDoc } from "../api/types"
import { AllocationCard } from "../features/report/Dashboard"
import { ReportDetail } from "../features/report/ReportDetail"
import { buildReport } from "./data/report"
import { REPORTS } from "./scenarios"
import { MockService } from "./services/MockService"

// 2단계: 분석 리포트의 목업 기능. 제안 데이터(proposed)가 있을 때만 보이고, 없으면(일반 모드) 지금 화면 그대로인지 확인한다.

beforeAll(() => { globalThis.ResizeObserver ??= class { observe() {} unobserve() {} disconnect() {} } as unknown as typeof ResizeObserver; Element.prototype.scrollIntoView = vi.fn() })
afterEach(() => window.history.replaceState(null, "", "/"))

const mock = () => new MockService({ latencyMs: 0, persist: false })
const open = async (id: string, sec?: string) => {
  window.history.replaceState(null, "", "/?mock=1")
  render(<ServiceContext.Provider value={mock()}><ReportDetail reportId={id} sec={sec} /></ServiceContext.Provider>)
  await screen.findByRole("heading", { level: 1 }, { timeout: 5000 })
}
const section = (name: RegExp) => screen.getAllByRole("button", { name }).find((b) => b.hasAttribute("aria-expanded"))!

describe("카드 2: 현재 구성과 예상 매수 주문", () => {
  it("구성을 고르는 버튼 없이 분석 기준일 「현재 구성」 하나만 보여 주고, 현금 금액과 1주 단위 예상 주문이 보인다", async () => {
    await open("mock_rep_normal")
    const card = screen.getByRole("heading", { name: "어떤 주식에 얼마를 투자하면 될까요?" }).closest("section")!
    expect(within(card).queryByRole("radiogroup")).toBeNull()
    expect(within(card).queryByText(/추천 전략 · 기준일 적용|추천 전략 · 백테스트 시작일|어떤 구성의 금액을 볼까요/)).toBeNull()
    expect(within(card).getByText(/이 배분은 분석 기준일의 「현재 구성」입니다/)).toBeInTheDocument()
    expect(within(card).queryByText("금액 미제공")).toBeNull()  // 현재 구성의 현금도 금액이 있다 (목업)
    fireEvent.click(within(card).getByRole("button", { name: /예상 매수 주문.*1주 단위/ }))
    expect(within(card).getAllByText(/^\d+주$/).length).toBeGreaterThan(3)
    expect(within(card).getByText("매수 후 남는 현금")).toBeInTheDocument()
    expect(within(card).getByText(/예상 매수 합계 \+ 수수료 \+ 남는 현금 = 투자금/)).toBeInTheDocument()
  })
  it("예상 매수 주문은 카드 2가 보여 주는 「현재 구성」 비중과 같은 기준으로 계산한다", () => {
    for (const sc of REPORTS) {
      const d = buildReport(sc) as ReportDoc & { proposed?: { execution?: { items: { ticker: string; target_weight: number }[] } | null } }
      const e = d.proposed?.execution, alloc = d.summary?.allocation
      if (!e || !alloc) continue
      const cardW = Object.fromEntries(alloc.items.map((x) => [x.ticker, x.weight]))
      for (const x of e.items) expect(x.target_weight, `${sc.id} ${x.ticker}`).toBeCloseTo(cardW[x.ticker] ?? 0, 6)
    }
  })
  it("서버의 혼합 주문: 미국은 소수 넷째 자리, 한국은 1주 단위로 보이고 현금 줄은 전략 현금 비중과 같은 금액이다", () => {
    const d = buildReport(REPORTS[0]) as ReportDoc & { proposed: ProposedReport }
    const e = d.proposed.execution!
    const execution: ProposedExecution = { ...e, share_basis: "mixed", items: e.items.map((x, i) => ({ ...x, share_basis: i ? "integer" : "fractional", shares: i ? 55 : 12.3456 })), totals: { ...e.totals, cash_target_usd: 1769.51, cash_target_krw: 2400057 } }
    const { proposed: _drop, ...plain } = d
    render(<AllocationCard a={{ ...plain.summary!.allocation!, cash_weight: 0.08 }} doc={{ ...plain, proposed: { contract: "proposed-0.1", execution } } as ReportDoc} onMore={() => {}} />)
    expect(screen.queryByText("금액 미제공")).toBeNull()
    expect(screen.getByLabelText("종목별 목표 배분액")).toHaveTextContent("240만 57원")
    fireEvent.click(screen.getByRole("button", { name: /예상 매수 주문.*미국 소수점 · 한국 1주 단위/ }))
    expect(screen.getByText("12.3456주")).toBeInTheDocument()
    expect(screen.getAllByText("55주").length).toBe(e.items.length - 1)
    expect(screen.getByText(/미국 주식은 소수 넷째 자리까지, 한국 주식은 1주 단위로 계산해/)).toBeInTheDocument()
  })
  it("제안 데이터가 없는 문서(일반 모드)는 지금처럼 고르는 칸·예상 주문 없이 「금액 미제공」으로 둔다", () => {
    const d = buildReport(REPORTS[0]) as ReportDoc & { proposed?: unknown }
    const { proposed: _drop, ...plain } = d
    render(<AllocationCard a={{ ...plain.summary!.allocation!, cash_weight: 0.1 }} doc={plain as ReportDoc} onMore={() => {}} />)
    expect(screen.queryByRole("radiogroup")).toBeNull()
    expect(screen.queryByText(/예상 매수 주문/)).toBeNull()
    expect(screen.getByText("금액 미제공")).toBeInTheDocument()
    expect(screen.getByText(/매수 수량, 거래 수수료.*제공하지 않습니다/)).toBeInTheDocument()
  })
})

describe("카드 4와 판단 이유: 분석 당시 성향·위험 기준·구조화 검증", () => {
  it("주의 시나리오: 정확한 5단계 성향(자동 진단 → 최종 선택), 기준이 다른 이유, 참고로 바뀐 검사, 추천 순위 기준 전체", async () => {
    await open("mock_rep_caution")
    const fit = screen.getByRole("heading", { name: "내 투자 조건에 맞나요?" }).closest("section")!
    fireEvent.click(within(fit).getByRole("button", { name: /조건별 자세한 결과/ }))  // 카드 4는 체크리스트가 먼저, 조건별 카드는 접혀 있다
    const vol = within(fit).getByText("변동성 적합").closest("li")!  // 서버 요약에는 없던 「기준 이내 참고 검사」도 구조화 값으로 보인다
    expect(vol).toHaveTextContent("투자성향: 위험중립형 (자동 진단 안정추구형 → 최종 선택 위험중립형)")
    expect(vol).toHaveTextContent("변동성이 너무 크지 않았으면")
    expect(vol).toHaveTextContent("분석 기간이 짧아, 이번에는 변동성 적합 여부를 판정하지 않고 참고 정보로 표시합니다.")
    expect(fit).toHaveTextContent(/판정 대신 참고로 표시한 검사: 목표수익.*변동성 적합/)
    fireEvent.click(within(fit).getByRole("button", { name: "추천 순위 기준 전체 설명 보기" }))
    expect(screen.getByRole("dialog", { name: "추천 순위 기준 전체 설명" })).toHaveTextContent(/무결성 검사.*보수 성향의 낙폭 맞춤안 우선.*낙폭 동률 처리/)
  })
  it("뉴스 꺼짐(공격투자형): 상한 없는 변동성 기준의 결과도 카드 4에 보이고 상한을 만들지 않는다", async () => {
    await open("mock_rep_newsoff")
    const fit = screen.getByRole("heading", { name: "내 투자 조건에 맞나요?" }).closest("section")!
    fireEvent.click(within(fit).getByRole("button", { name: /조건별 자세한 결과/ }))
    const vol = within(fit).getByText("변동성 적합").closest("li")!
    expect(vol).toHaveTextContent("상한 없음"); expect(vol).not.toHaveTextContent(/\d% 이하/)
    expect(vol).toHaveTextContent("투자성향: 공격투자형")
  }, 15000)  // 리포트 전체를 그려 부하가 높을 때 5초를 넘길 수 있다
  it("판단 이유는 구조화 값의 제목·설명으로 보인다", async () => {
    await open("mock_rep_normal", "verdict")
    const why = await screen.findByRole("list", { name: "핵심 판단 이유" })
    expect(within(why).getByText("비교한 투자 구성안 중 1위")).toBeInTheDocument()
    expect(within(why).getByText("SPY보다 높은 연평균 수익률")).toBeInTheDocument()
  })
})

describe("상세 섹션", () => {
  it("선택 전략이 서버 비교표에 없는 낙폭 맞춤안이어도 기준 비중과 나란히 비교한다", async () => {
    await open("mock_rep_caution", "construction")
    expect(await screen.findByRole("list", { name: "종목별 비중 비교" })).toBeInTheDocument()
    expect(screen.queryByText(/따로 없어 기준 비중과 나란히 그리지 않았습니다/)).toBeNull()
  })
  it("시장 주제 카드 4개, 기업별 뉴스 투자 의견 상태, 구조화된 선정 이유", async () => {
    await open("mock_rep_normal", "market")
    for (const t of ["전체 시장 상황", "관련 산업 동향", "투자 테마 관련 변화", "뉴스·공시 근거"]) expect((await screen.findAllByText(t)).length).toBeGreaterThan(0)
    fireEvent.click(section(/왜 이 기업들을 선택했나요/))
    expect((await screen.findAllByText(/^뉴스 투자 의견 반영 \d개$/)).length).toBeGreaterThan(0)
    expect(screen.getAllByText("근거 부족 · 투자 의견 없음").length).toBeGreaterThan(0)  // 기사가 있어도 의견이 없으면 그렇게 표시
    fireEvent.click(screen.getByText("NVDA").closest("button")!)
    expect(await screen.findByText("핵심 선정 이유")).toBeInTheDocument()
    expect(screen.getByText("선정 근거 원문")).toBeInTheDocument()  // 원문은 그대로
  })
  it("뉴스 반영을 끈 분석은 모든 종목이 「뉴스 반영 꺼짐」", async () => {
    await open("mock_rep_newsoff", "companies")
    await waitFor(() => expect(screen.getAllByText("뉴스 반영 꺼짐").length).toBe(5))
  })
  it("요청 이력에 말로 보탠 요청과 결과(반영됨/반영 안 됨)와 최종 조건이 보인다", async () => {
    await open("mock_rep_normal", "history")
    expect(await screen.findByText("“마이크론은 꼭 넣어 주세요”")).toBeInTheDocument()
    expect(screen.getByText("조건에 반영됨")).toBeInTheDocument(); expect(screen.getByText("반영되지 않음")).toBeInTheDocument()
    expect(screen.getByText(/기존 조건이 그대로 유지됩니다/)).toBeInTheDocument()
    expect(screen.getByText("최종 분석 조건")).toBeInTheDocument()
  })
  it("리밸런싱 기록에 원화 금액과 환율·날짜가 함께 보인다", async () => {
    await open("mock_rep_normal", "construction")
    expect((await screen.findAllByText(/^약 .*원 · 투입 원금 약 .*원 \(1 USD = [\d,.]+원, \d{4}-\d{2}-\d{2}\)/)).length).toBeGreaterThan(0)
  })
})

describe("이전 형식·원안 비교", () => {
  it("v1 리포트와 수정안의 원안 비교가 목업에서 열린다", async () => {
    const s = mock() as AnalysisService
    expect((await s.getReport("mock_rep_legacy")).doc_version).toBe(1)
    expect((await s.getReportComparison("mock_rep_revised"))?.comparison_id).toBe("mock_cmp_revised")
    expect((await s.getComparison("mock_cmp_revised")).condition_changes.length).toBe(2)
  })
})
