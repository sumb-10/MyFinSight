import { useState } from "react"
import { describe, expect, it, vi } from "vitest"
import { fireEvent, render, screen, waitFor, within } from "@testing-library/react"
import { Providers } from "../../app/providers"
import { ApiError } from "../../api/client"
import type { AnalysisService } from "../../api/service"
import type { ProfileVersion } from "../../api/types"
import { DetailConditionsDialog, type Overrides } from "./DetailConditions"

// 상세 조건 창: 적용 버튼에서만 onApply, 변경 표시·개수·요약이 실제 overrides 와 일치, 숨은 오류 안내, 키보드·포커스.

const profile = {
  version: 3, created_at: "2026-01-01", profile: { age_band: "30s", investment_experience: "beginner", financial_knowledge: "basic", investable_ratio_of_assets: 0.3 },
  capital: { initial_amount: 10_000_000, currency: "KRW", monthly_contribution: 500_000, contribution_day: 25 }, horizon: { target_years: 3, purpose: "wealth_growth", backtest_years: 5 },
  risk: { risk_tolerance: "moderate", max_drawdown_tolerance: 0.125, loss_reaction: "hold", target_annual_return: 0.12, benchmark: "SPY" },
  constraints: { universe: ["SP500", "NASDAQ100"], asset_types: ["stock"], num_holdings: { target: 10, min: 8, max: 12 }, max_weight_per_stock: 0.15, max_weight_per_sector: 0.4, min_cash_ratio: 0, exclude_tickers: [], exclude_sectors: [], exclude_themes: [], must_include_tickers: [], rebalance: { count: 1, unit: "1q" }, allow_leverage: false, allow_short: false, min_market_cap_usd: 0, min_avg_daily_volume_usd: 0 },
  strategy_preference: { template: "momentum", baseline_weighting: "equal_weight", use_news_tilt: true }, risk_type_computed: "moderate", risk_type_overridden: false,
} as unknown as ProfileVersion

const service = { mode: "api", health: () => Promise.resolve({ ok: true, api_version: "1", llm_mode: "api", db: { ok: true }, worker: { alive: true, running_run_id: null }, queue_length: 0 }), options: () => Promise.reject(new ApiError("NOT_IN_TEST", "없음", 500)), getProfile: () => Promise.resolve(null), listRequests: () => Promise.resolve([]), listRuns: () => Promise.resolve([]), listReports: () => Promise.resolve([]) } as unknown as AnalysisService

function setup(props: { initial?: Overrides; intro?: string; title?: string; applyLabel?: string } = {}) {
  const onApply = vi.fn(), close = vi.fn()
  render(<Providers service={service}><DetailConditionsDialog profile={profile} initial={props.initial ?? {}} onApply={onApply} close={close} title={props.title} applyLabel={props.applyLabel} intro={props.intro} /></Providers>)
  return { onApply, close }
}
const tab = (name: RegExp) => screen.getByRole("tab", { name })
const applyBtn = () => screen.getByRole("button", { name: "이 조건 적용" })

describe("상세 조건 창", () => {
  it("탭을 옮겨도 값이 남고, 입력·탭 이동만으로는 onApply 를 부르지 않으며, 적용 때만 실제 overrides 를 넘긴다", () => {
    const { onApply, close } = setup()
    expect(screen.getByText("변경 없음")).toBeInTheDocument()
    fireEvent.change(screen.getByLabelText("투자금"), { target: { value: "20000000" } })
    fireEvent.click(tab(/전략/))
    fireEvent.change(screen.getByLabelText(/어떤 기업에 투자할까요/), { target: { value: "low_per" } })
    fireEvent.click(tab(/자금·기간/))
    expect(screen.getByLabelText(/^투자금/)).toHaveValue("20,000,000")
    expect(tab(/자금·기간/)).toHaveAccessibleName(/변경 1개/)
    expect(tab(/전략/)).toHaveAccessibleName(/변경 1개/)
    expect(onApply).not.toHaveBeenCalled()
    fireEvent.click(screen.getByRole("button", { name: /변경 2개/ }))
    const panel = screen.getByRole("tabpanel")
    expect(within(panel).getByText("1,000만원")).toBeInTheDocument()
    expect(within(panel).getByText("2,000만원")).toBeInTheDocument()
    expect(within(panel).getByText("가격이 상대적으로 저평가된 기업")).toBeInTheDocument()
    expect(within(panel).getAllByRole("listitem")).toHaveLength(2)
    fireEvent.click(applyBtn())
    expect(onApply).toHaveBeenCalledTimes(1)
    expect(onApply).toHaveBeenCalledWith({ "capital.initial_amount": 20_000_000, "strategy_preference.template": "low_per" })
    expect(close).toHaveBeenCalledTimes(1)
  })

  it("값을 기본값으로 돌리면 변경 표시가 사라진다", () => {
    setup()
    const amount = screen.getByLabelText("투자금")
    fireEvent.change(amount, { target: { value: "20000000" } })
    expect(screen.getByText("변경됨")).toBeInTheDocument()
    fireEvent.change(amount, { target: { value: "10000000" } })
    expect(screen.queryByText("변경됨")).toBeNull()
    expect(screen.getByText("변경 없음")).toBeInTheDocument()
  })

  it("정수로 다루는 값(12.5% → 13)은 건드리지 않으면 변경으로 잡지 않는다", () => {
    const { onApply } = setup()
    expect(screen.getByText("변경 없음")).toBeInTheDocument()
    fireEvent.click(applyBtn())
    expect(onApply).toHaveBeenCalledWith({})
  })

  it("취소·닫기·Esc 는 적용하지 않고, 되돌리기는 창을 유지한 채 값만 초기화한다", () => {
    const { onApply, close } = setup({ initial: { "capital.initial_amount": 30_000_000 } })
    expect(screen.getByLabelText(/^투자금/)).toHaveValue("30,000,000")
    fireEvent.click(screen.getByRole("button", { name: "기본 투자조건으로 되돌리기" }))
    expect(screen.getByLabelText(/^투자금/)).toHaveValue("10,000,000")
    expect(onApply).not.toHaveBeenCalled()
    expect(close).not.toHaveBeenCalled()
    fireEvent.click(screen.getByRole("button", { name: "취소" }))
    fireEvent.click(screen.getByRole("button", { name: "닫기" }))
    fireEvent.keyDown(window, { key: "Escape" })
    expect(close).toHaveBeenCalledTimes(3)
    expect(onApply).not.toHaveBeenCalled()
    fireEvent.click(applyBtn())
    expect(onApply).toHaveBeenCalledWith({})
  })

  it("다른 탭의 접힌 영역에 오류가 있으면 그 탭으로 가서 펼치고 첫 오류 입력에 포커스한다", async () => {
    const { onApply } = setup()
    fireEvent.click(tab(/종목·배분/))
    fireEvent.click(screen.getByRole("button", { name: /종목 수 범위/ }))
    fireEvent.change(screen.getByLabelText("최소 종목 수"), { target: { value: "20" } })
    fireEvent.click(screen.getByRole("button", { name: /종목 수 범위/ }))
    expect(screen.queryByLabelText(/최소 종목 수/)).toBeNull()
    fireEvent.click(tab(/전략/))
    fireEvent.click(applyBtn())
    expect(onApply).not.toHaveBeenCalled()
    expect(tab(/종목·배분/)).toHaveAttribute("aria-selected", "true")
    expect(screen.getByRole("button", { name: /종목 수 범위/ })).toHaveAttribute("aria-expanded", "true")
    await waitFor(() => expect(screen.getByLabelText(/최소 종목 수/)).toHaveFocus())
    expect(screen.getByText("최소 종목 수가 최대 종목 수보다 큽니다")).toBeInTheDocument()
  })

  it("목표 종목 수를 범위 밖으로 바꾸면 최소·최대는 그대로 두고 목표 칸에 바로 오류를 보여 주며, 고칠 때까지 적용하지 않는다", () => {
    const { onApply } = setup()
    fireEvent.click(tab(/종목·배분/))
    const target = screen.getByLabelText(/목표 종목 수/)
    fireEvent.change(target, { target: { value: "15" } })
    const msg = "목표 종목 수는 최소 8 ~ 최대 12개 사이여야 합니다. 목표를 바꾸거나 아래 「종목 수 범위」에서 최소·최대를 바꿔 주세요"
    expect(screen.getByText(msg)).toBeInTheDocument()  // 적용을 누르기 전에도 바로
    expect(target).toHaveAttribute("aria-invalid", "true")
    fireEvent.click(screen.getByRole("button", { name: /종목 수 범위/ }))
    expect(screen.getByLabelText(/최소 종목 수/)).toHaveValue(8)  // 저절로 바뀌지 않는다
    expect(screen.getByLabelText(/최대 종목 수/)).toHaveValue(12)
    fireEvent.click(applyBtn())
    expect(onApply).not.toHaveBeenCalled()
    fireEvent.change(screen.getByLabelText(/최대 종목 수/), { target: { value: "15" } })  // 범위를 넓히면 오류가 사라진다
    expect(screen.queryByText(msg)).toBeNull()
    fireEvent.click(applyBtn())
    expect(onApply).toHaveBeenCalledWith({ "constraints.num_holdings": { target: 15, min: 8, max: 15 } })
  })

  it("이미 바꾼 값이 있는 고급 영역은 처음부터 펼치고, 접힌 영역은 현재 설정을 요약한다", () => {
    setup({ initial: { "constraints.exclude_tickers": ["TSLA"] } })
    fireEvent.click(tab(/종목·배분/))
    expect(screen.getByRole("button", { name: /제외 조건/ })).toHaveAttribute("aria-expanded", "true")
    expect(screen.getByLabelText(/제외 종목/)).toHaveValue("TSLA")
    const floor = screen.getByRole("button", { name: /종목 규모 하한/ })
    expect(floor).toHaveAttribute("aria-expanded", "false")
    expect(floor).toHaveTextContent("시가총액 제한 없음 · 거래대금 제한 없음")
    expect(screen.getByRole("button", { name: /현금·리밸런싱/ })).toHaveTextContent("현금 0% · 분기마다 1회")
  })

  it("백테스트: 고른 방식의 입력만 보이고, 기존 변환 규칙대로 overrides 를 만든다", () => {
    const { onApply } = setup()
    expect(screen.getByText(/과거 성과를 확인할 기간은 지난 자료로 전략을 검증하는 기간입니다/)).toBeInTheDocument()
    expect(screen.getByLabelText("최근 몇 년을 볼까요? (년)")).toBeInTheDocument()
    expect(screen.queryByLabelText("시작 연도")).toBeNull()
    fireEvent.click(screen.getByRole("radio", { name: /특정 기간/ }))
    expect(screen.queryByLabelText(/최근 몇 년/)).toBeNull()
    fireEvent.change(screen.getByLabelText("시작 연도"), { target: { value: "2018" } })
    fireEvent.change(screen.getByLabelText("끝 연도"), { target: { value: "2020" } })
    fireEvent.click(applyBtn())
    expect(onApply).toHaveBeenCalledWith({ "horizon.backtest_years": 3, "horizon.start_date": "2020-12-31" })
  })

  it("탭은 방향키로 옮기고, 호출 화면의 제목·안내·버튼 문구를 유지하며, 부모가 다시 그려져도 입력을 지우지 않는다", async () => {
    function Parent() {  // 조건 확인 화면처럼 initial 이 렌더마다 새 {} 인 경우
      const [, bump] = useState(0)
      return <><button onClick={() => bump((n) => n + 1)}>다시 그리기</button><DetailConditionsDialog profile={profile} initial={{}} onApply={() => {}} close={() => {}} title="이번 요청의 조건 바꾸기" applyLabel="이 조건으로 다시 확인" intro="안내 문구" /></>
    }
    render(<Providers service={service}><Parent /></Providers>)
    expect(screen.getByRole("dialog", { name: "이번 요청의 조건 바꾸기" })).toBeInTheDocument()
    expect(screen.getByText("안내 문구")).toBeInTheDocument()
    expect(screen.getByText("저장된 기본 투자조건은 바뀌지 않고 이번 요청에만 적용됩니다.")).toBeInTheDocument()
    expect(screen.getByRole("button", { name: "이 조건으로 다시 확인" })).toBeInTheDocument()
    fireEvent.change(screen.getByLabelText("투자금"), { target: { value: "20000000" } })
    fireEvent.click(screen.getByText("다시 그리기"))
    expect(screen.getByLabelText(/^투자금/)).toHaveValue("20,000,000")
    const first = tab(/자금·기간/)
    first.focus()
    fireEvent.keyDown(first, { key: "ArrowLeft" })
    await waitFor(() => expect(tab(/전략/)).toHaveFocus())
    expect(tab(/전략/)).toHaveAttribute("aria-selected", "true")
    fireEvent.keyDown(tab(/전략/), { key: "Home" })
    await waitFor(() => expect(tab(/자금·기간/)).toHaveFocus())
  })

  it("창을 열면 선택한 탭으로 포커스가 가고, 닫으면 연 버튼으로 돌아온다", async () => {
    function Host() {
      const [open, setOpen] = useState(false)
      return <><button onClick={() => setOpen(true)}>상세 조건 열기</button>{open && <DetailConditionsDialog profile={profile} initial={{}} onApply={() => {}} close={() => setOpen(false)} />}</>
    }
    render(<Providers service={service}><Host /></Providers>)
    const opener = screen.getByText("상세 조건 열기")
    opener.focus()
    fireEvent.click(opener)
    expect(tab(/자금·기간/)).toHaveFocus()
    fireEvent.keyDown(window, { key: "Escape" })
    await waitFor(() => expect(screen.queryByRole("dialog")).toBeNull())
    expect(opener).toHaveFocus()
  })
})
