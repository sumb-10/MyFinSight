import { beforeEach, describe, expect, it, vi } from "vitest"
import { fireEvent, render, screen, waitFor, within } from "@testing-library/react"
import { ServiceContext } from "../../app/providers"
import type { AnalysisService } from "../../api/service"
import type { PaperDetail, PaperIn, PaperPortfolio, PaperPreview, PaperRebalance, PaperSnapshot, PaperSummary } from "../../api/types"
import { RevisionCard } from "../analysis/RevisionCard"
import { PaperScreen } from "./PaperScreen"
import { StartPaperDialog } from "./StartPaperDialog"

describe("RevisionCard", () => {
  it("반영한 변경과 반영하지 못한 요청을 나눠 보여 준다", () => {
    render(<RevisionCard rev={{ text: "NVDA는 빼 주세요. 리밸런싱은 매월로", summary_ko: "요약", frozen_fields: [], unsupported_ko: ["수정안 비교에서는 원안과 같은 조건을 유지합니다"],
      changes: [{ field: "constraints.exclude_tickers", label_ko: "제외 종목", value: ["NVDA"], base_value: [], supported: true, reason_ko: "엔비디아 제외" },
        { field: "capital.initial_amount", label_ko: "투자금", value: 1, base_value: 100, supported: false, note_ko: "원안과 같은 조건을 유지" }] }} />)
    expect(screen.getByText("반영한 변경")).toBeInTheDocument()
    expect(screen.getByText(/제외 종목/)).toBeInTheDocument()
    expect(screen.getByText(/반영하지 못한 요청/)).toBeInTheDocument()
    expect(screen.getAllByText(/원안과 같은 조건/).length).toBeGreaterThan(0)
  })
})

// ── 모의투자 화면: 모두 가짜 서비스. 사용자의 실제 모의투자를 만들거나 바꾸지 않는다. ──
const cap = (cur: "KRW" | "USD") => (cur === "KRW" ? { amount: 14_000_000, currency: cur, usd: 10_000, fx_rate: 1400, fx_date: "2026-01-02" } : { amount: 10_000, currency: cur, usd: 10_000, fx_rate: 1400, fx_date: "2026-01-02" })
const snap = (date: string, value: number, extra: Partial<PaperSnapshot> = {}): PaperSnapshot => ({ date, value_usd: value, cash_usd: 1000, weights: { MU: 0.6, NOW: 0.3 }, drawdown: -0.02, return_since_start: 0.05, benchmark_return_since_start: 0.02, fx_rate: 1400, status: "ok", contribution_usd: 0, ...extra })
const detail = (cur: "KRW" | "USD", snapshots: PaperSnapshot[], over: { p?: Partial<PaperPortfolio>; s?: Partial<PaperSummary>; rebalances?: PaperRebalance[] } = {}): PaperDetail => {
  const last = snapshots[snapshots.length - 1]
  const portfolio = { paper_id: "p1", report_id: "rep1", run_id: "run1", strategy_id: "s", strategy: { id: "s", kind: "template", template: null, cash_ratio: 0, name_ko: "전략" }, name_ko: "아주 긴 전략 이름 낙폭 맞춤안 (주식 47% + 현금 53%, 시가총액비중 기준)", start_date: "2026-01-02", reconstructed_at_start: false, initial_capital: cap(cur), contribution: { enabled: false, currency: cur }, rebalance_rule: { count: 1, unit: "1m" }, benchmark: "SPY", tickers: ["MU", "NOW"], start_weights: { MU: 0.5, NOW: 0.4 }, state: { holdings: {}, cash_usd: 1000, last_snapshot_date: last?.date ?? null, last_rebalance_date: "2026-02-02", n_rebalances: 1, target_weights: { MU: 0.55, NOW: 0.35 }, cash_weight: 0.1 }, status: "active", created_at: "t", stopped_at: null, resumed_at: null, history: [{ at: "2026-01-02T09:00:00+09:00", event: "started" }], warnings: [], constraints_snapshot: { request: {} }, ...over.p } as unknown as PaperPortfolio
  const summary = { paper_id: "p1", name_ko: portfolio.name_ko, status: portfolio.status, start_date: "2026-01-02", last_date: last?.date ?? null, days_tracked: snapshots.length, initial_capital: cap(cur), value_usd: last?.value_usd ?? 10_000, contributions_total_usd: 0, gain_usd: 500, return_since_start: 0.05, benchmark: "SPY", benchmark_return_since_start: 0.02, excess_return: 0.03, drawdown: -0.02, max_drawdown: -0.08, n_rebalances: 1, update_status: "ok", delayed_reason_ko: null, last_refresh_at: "2026-03-01T10:00:00+09:00", data_ceiling: "2026-03-01", ...over.s } as unknown as PaperSummary
  return { portfolio, summary, snapshots, rebalances: over.rebalances ?? [], series: { dates: snapshots.map((x) => x.date), value_usd: snapshots.map((x) => x.value_usd), benchmark_value_usd: [], return_since_start: snapshots.map((x) => x.return_since_start), benchmark_return_since_start: snapshots.map((x) => x.benchmark_return_since_start ?? null), drawdown: [] } }
}
const service = (over: Partial<Record<keyof AnalysisService, unknown>>) => ({ mode: "api", listReports: () => Promise.resolve([]), listPaper: () => Promise.resolve([]), getRunPartial: () => Promise.resolve({ run_id: "run1", intent: null, selection: { as_of: "x", n_selected: 2, rows: [{ ticker: "MU", name: "Micron Technology" }] } }), ...over }) as unknown as AnalysisService
const show = (d: PaperDetail, over: Partial<Record<keyof AnalysisService, unknown>> = {}) => render(<ServiceContext.Provider value={service({ getPaper: () => Promise.resolve(d), ...over })}><PaperScreen paperId="p1" /></ServiceContext.Provider>)
const openPart = (name: RegExp) => fireEvent.click(screen.getByRole("button", { name }))

describe("모의투자 통화와 환율", () => {
  it("원화는 날짜별 환율로 환산하고 수익률은 USD 기준임을 표시한다", async () => {
    const d = detail("KRW", [snap("2026-01-02", 10_000, { fx_rate: 1400 }), snap("2026-02-02", 11_000, { fx_rate: 1300 })], { rebalances: [{ date: "2026-01-02", seq: 0, kind: "initial", before_weights: {}, target_weights: {}, applied_weights: {}, trades: [{ ticker: "MU", side: "buy", shares: 2, price: 100, value_usd: 200 }], commission_usd: 1, turnover: 1, fallback: false, skipped: false }] })
    show(d)
    await screen.findByText("핵심 성과")
    expect(screen.getByText("1,430만원")).toBeInTheDocument()  // 11,000 × 그날 환율 1,300 (시작일 환율 1,400 이 아니다)
    expect(screen.getByText("11,000.00 USD")).toBeInTheDocument()  // 환율 문구는 두지 않는다 (금액에 마우스를 올리면 보인다)
    expect(screen.getByText(/금액은 원화, 수익률은 USD 기준 · 원화 환율 변동 미반영/)).toBeInTheDocument()
    expect(screen.queryByText(/원화 수익률/)).toBeNull()
    expect(screen.getByText("+3.00%p")).toBeInTheDocument()
    expect(screen.getAllByText("14,000,000원")).toHaveLength(1)  // 총 납입금 (적립이 없어 초기 투자금과 같다)
    expect(screen.getByText("초기 14,000,000원 · 추가 납입 없음")).toBeInTheDocument()
    expect(screen.getByText(/^납입 제외 손익 .+ USD \(수수료 차감 후\)$/)).toBeInTheDocument()
    openPart(/거래·리밸런싱 상세/)
    const trades = within(screen.getByRole("button", { name: /거래·리밸런싱 상세/ }).closest("section")!)
    expect(trades.getByText("280,000원")).toBeInTheDocument()  // 그날 환율 1,400 으로 거래금액 환산
    expect(trades.getByText("1,400원")).toBeInTheDocument()
  })
  it("달러 모의투자는 저장된 통화대로 USD 로 보여 주고 원화 안내를 달지 않는다", async () => {
    show(detail("USD", [snap("2026-01-02", 10_000), snap("2026-02-02", 11_000)]))
    await screen.findByText("핵심 성과")
    expect(screen.getByText("11,000.00 USD")).toBeInTheDocument()
    expect(screen.getAllByText("10,000.00 USD")).toHaveLength(1)
    expect(screen.getByText("초기 10,000.00 USD · 추가 납입 없음")).toBeInTheDocument()
    expect(screen.queryByText(/환율 변동 미반영/)).toBeNull()
  })
  it("환율 기록이 없으면 다른 환율을 쓰지 않고 환산 불가와 USD 를 보여 준다", async () => {
    show(detail("KRW", [snap("2026-01-02", 10_000), snap("2026-02-02", 11_000, { fx_rate: null })]))
    await screen.findByText("핵심 성과")
    expect(screen.getByText("11,000.00 USD")).toBeInTheDocument()
    expect(screen.getAllByText("환산 불가").length).toBeGreaterThan(0)
    expect(screen.queryByText("1,540만원")).toBeNull()
  })
  it("추가 납입금은 원화 납입액을 그대로 쓰고 손익과 구분한다", async () => {
    show(detail("KRW", [snap("2026-01-02", 10_000), snap("2026-01-25", 10_400, { contribution_usd: 350 }), snap("2026-02-25", 10_800, { contribution_usd: 340 })], { p: { contribution: { enabled: true, monthly_amount: 500_000, currency: "KRW", day: 25 } }, s: { contributions_total_usd: 690 } }))
    await screen.findByText("핵심 성과")
    expect(screen.getByText("초기 14,000,000원 · 추가 1,000,000원 (2회 납입)")).toBeInTheDocument()
    expect(screen.getByText("15,000,000원")).toBeInTheDocument()
    expect(screen.getByText(/2회 납입/)).toBeInTheDocument()
  })
  it("목록은 각 모의투자의 통화와 마지막 평가일 환율로 평가액을 보여 준다", async () => {
    const krw = detail("KRW", [snap("2026-02-02", 11_000, { fx_rate: 1300 })]), dollar = detail("USD", [snap("2026-02-02", 9_000)])
    const getPaper = vi.fn((id: string) => Promise.resolve(id === "a" ? krw : dollar))
    const rows = [{ ...krw.summary, paper_id: "a" }, { ...dollar.summary, paper_id: "b" }]
    render(<ServiceContext.Provider value={service({ listPaper: () => Promise.resolve(rows), getPaper })}><PaperScreen /></ServiceContext.Provider>)
    expect(await screen.findByText("14,300,000원")).toBeInTheDocument()
    expect(screen.getByText("9,000.00 USD")).toBeInTheDocument()
    expect(getPaper).toHaveBeenCalledTimes(1)  // 달러는 상세가 필요 없다
    expect(screen.queryByText(/\+\+/)).toBeNull()  // 예전 "++5.00%" 표시 방지
  })
})

describe("모의투자 상세 상태", () => {
  it("평가 기록 0건·1건·여러 건을 구분하고, 기록이 없어도 오류처럼 보이지 않으며 없는 값을 0 으로 쓰지 않는다", async () => {
    const { unmount } = show(detail("KRW", []))
    expect(await screen.findByText(/아직 평가 기록이 없습니다/)).toBeInTheDocument()
    expect(screen.getByRole("heading", { name: "현재 보유 구성" }).closest("section")).toHaveTextContent("–")
    expect(screen.queryByText("0.0%")).toBeNull()
    unmount()
    const r = show(detail("KRW", [snap("2026-01-02", 10_000)]))
    expect(await screen.findByText(/2026-01-02 하루치입니다/)).toBeInTheDocument()
    r.unmount()
    show(detail("KRW", [snap("2026-01-02", 10_000), snap("2026-02-02", 11_000)]))
    await screen.findByText("핵심 성과")
    expect(screen.queryByText(/하루치|평가 기록이 없습니다/)).toBeNull()
  })
  it("보유 구성은 회사명·현금·목표를 보여 주고, 시작 비중은 펼쳐서 본다. 허용 낙폭은 저장값을 쓴다", async () => {
    show(detail("KRW", [snap("2026-02-02", 10_000)], { p: { constraints_snapshot: { request: { risk: { max_drawdown_tolerance: 0.05 } } } } }))
    expect(await screen.findByText("Micron Technology")).toBeInTheDocument()
    expect(screen.getByText("55.0%")).toBeInTheDocument()
    expect(screen.getByText("현금")).toBeInTheDocument()
    expect(screen.queryByText("50.0%")).toBeNull()
    openPart(/비중 변화 보기/)
    expect(screen.getByText("50.0%")).toBeInTheDocument()
    expect(screen.getByText("5.0%")).toBeInTheDocument()
    expect(screen.getByText("최대 낙폭이 허용 낙폭을 넘었습니다")).toBeInTheDocument()
  })
  it("저장된 허용 낙폭이 없으면 고정 기준으로 판단하지 않는다", async () => {
    show(detail("KRW", [snap("2026-02-02", 10_000)], { s: { max_drawdown: -0.5 } }))
    expect(await screen.findByText("저장된 기준 없음")).toBeInTheDocument()
    expect(screen.queryByText(/허용 낙폭을 넘었습니다/)).toBeNull()
  })
  it("갱신은 응답으로 확인한 만큼만 알리고, 진행 중 중복 요청을 막는다", async () => {
    const before = detail("USD", [snap("2026-01-02", 10_000)])
    let done!: (d: PaperDetail) => void
    const refreshPaper = vi.fn(() => new Promise<PaperDetail>((r) => { done = r }))
    show(before, { refreshPaper })
    await screen.findByText("핵심 성과")
    fireEvent.click(screen.getByRole("button", { name: "최신 자료로 갱신" }))
    expect(screen.getByRole("button", { name: "자료 확인 중…" })).toBeDisabled()
    done(detail("USD", [snap("2026-01-02", 10_000), snap("2026-01-05", 10_100), snap("2026-01-06", 10_200)]))
    expect(await screen.findByText("새 평가 2일 반영")).toBeInTheDocument()
    refreshPaper.mockImplementation(() => Promise.resolve(detail("USD", [snap("2026-01-02", 10_000), snap("2026-01-05", 10_100), snap("2026-01-06", 10_200)])))
    fireEvent.click(screen.getByRole("button", { name: "최신 자료로 갱신" }))
    expect(await screen.findByText("추가된 평가 없음")).toBeInTheDocument()
  })
  it("중지는 확인 뒤에만 보내고, 운용 상태와 자료 상태를 따로 보여 주며, 중지 기간을 잇지 않는다", async () => {
    const stopPaper = vi.fn(() => Promise.resolve(detail("KRW", [snap("2026-01-02", 10_000)], { p: { status: "stopped" }, s: { status: "stopped", update_status: "delayed", delayed_reason_ko: "자료 없음" } })))
    show(detail("KRW", [snap("2026-01-02", 10_000)]), { stopPaper })
    await screen.findByText("핵심 성과")
    fireEvent.click(screen.getByRole("button", { name: "모의투자 중지" }))
    expect(stopPaper).not.toHaveBeenCalled()
    expect(screen.getByText(/보유 종목을 매도하지 않고 평가와 리밸런싱 기록을 중지합니다. 재개 시 중지 기간의 기록은 소급해서 채우지 않습니다./)).toBeInTheDocument()
    fireEvent.click(screen.getByRole("button", { name: "중지 확정" }))
    expect(await screen.findByRole("button", { name: "모의투자 재개" })).toBeInTheDocument()
    expect(screen.getByText("운용 중지")).toBeInTheDocument()
    expect(screen.getByText("자료 지연")).toBeInTheDocument()
    expect(screen.getByRole("button", { name: /최신 자료로 갱신/ })).toBeDisabled()
  })
  it("재개한 기록이 있으면 최근 이벤트에 나오고 차트 안내가 붙는다. 최근 기록은 5개까지다", async () => {
    const rebalances = Array.from({ length: 7 }, (_, i): PaperRebalance => ({ date: `2026-01-0${i + 1}`, seq: i, kind: "rebalance", before_weights: {}, target_weights: {}, applied_weights: {}, trades: [], commission_usd: 0, turnover: 0, fallback: false, skipped: i === 6, note_ko: i === 6 ? "중지 기간에 지나감" : null }))
    show(detail("KRW", [snap("2026-01-02", 10_000), snap("2026-03-02", 11_000)], { rebalances, p: { history: [{ at: "2026-03-02T09:00:00+09:00", event: "resumed", note: "2026-03-01 부터 다시 평가" }] } }))
    await screen.findByText("핵심 성과")
    const box = screen.getByRole("heading", { name: "최근 운용 기록" }).closest("section")!
    expect(within(box).getAllByRole("listitem")).toHaveLength(5)
    expect(within(box).getByText("모의투자 재개")).toBeInTheDocument()
    expect(within(box).getByText("리밸런싱 건너뜀")).toBeInTheDocument()
    expect(screen.getByText(/끊긴 구간은 모의투자를 중지한 기간입니다/)).toBeInTheDocument()
  })
})

describe("모의투자 시작", () => {
  const preview = (cur: "KRW" | "USD", over: Partial<PaperPreview> = {}): PaperPreview => ({ report_id: "r", run_id: "r", report_as_of: "2026-01-01", strategy: { id: "s", kind: "template", template: null, cash_ratio: 0, name_ko: "아주 긴 전략 이름 낙폭 맞춤안 (주식 47% + 현금 53%, 시가총액비중 기준)" }, strategy_options: [{ id: "s", kind: "template", template: null, cash_ratio: 0, name_ko: "아주 긴 전략 이름 낙폭 맞춤안 (주식 47% + 현금 53%, 시가총액비중 기준)", status: "warn", recommended: false, chosen: true }], start_date: "2026-01-02", data_ceiling: "2026-01-02", reconstructed_at_start: true, initial_capital: cap(cur), contribution: { enabled: true, monthly_amount: cur === "KRW" ? 700_000 : 500, currency: cur, day: 25 }, rebalance_rule: { count: 1, unit: "1m" }, benchmark: "SPY", tickers: ["MU"], weights: { MU: 0.9 }, cash_weight: 0.1, report_weights: { MU: 0.85 }, weight_diff: [{ ticker: "MU", report: 0.85, start: 0.9, delta: 0.05 }], allocation: [{ ticker: "MU", weight: 0.9, usd: 9000, krw: 12_600_000, price_usd: 100 }], construct_info: { fallback: false, warnings: [] }, warnings: [], ...over })
  const open = (previewPaper: unknown) => render(<ServiceContext.Provider value={service({ previewPaper })}><StartPaperDialog reportId="r" close={() => {}} /></ServiceContext.Provider>)

  it("서버가 정한 분석 요청의 통화를 기본값으로 쓴다 (달러 요청·상세 조건 변경 모두 서버 값)", async () => {
    const previewPaper = vi.fn(() => Promise.resolve(preview("USD")))
    open(previewPaper)
    expect(await screen.findByDisplayValue("USD")).toBeInTheDocument()
    expect(previewPaper).toHaveBeenCalledWith({ report_id: "r" })  // 프로필 통화를 보내지 않는다
    expect(screen.getByLabelText(/월 적립액 \(USD\)/)).toHaveValue(500)
  })
  it("시작 화면에서 통화를 바꾸면 초기자본·월 적립금을 함께 환산하고, 그 통화로 요청·확인한다", async () => {
    const previewPaper = vi.fn((f: PaperIn) => Promise.resolve(preview(f.currency === "USD" ? "USD" : "KRW")))
    open(previewPaper)
    await screen.findByDisplayValue("KRW")
    fireEvent.change(screen.getByDisplayValue("KRW"), { target: { value: "USD" } })
    expect(screen.getByLabelText(/월 적립액 \(USD\)/)).toHaveValue(500)
    expect(screen.getByDisplayValue("10000")).toBeInTheDocument()
    fireEvent.click(screen.getByRole("button", { name: "시작 조건 확인" }))
    await screen.findByText("달러 (USD)")
    expect(previewPaper).toHaveBeenLastCalledWith(expect.objectContaining({ currency: "USD", initial_amount: 10000, monthly_contribution: 500 }))
  })
  it("최종 확인에 전략·시작일·통화·초기자본·월 적립금·현금 비중과 %p 차이를 보여 준다", async () => {
    open(() => Promise.resolve(preview("KRW")))
    await screen.findByDisplayValue("KRW")
    expect(screen.getByText(/검증 주의 · 리포트 선택안/)).toBeInTheDocument()
    fireEvent.click(screen.getByRole("button", { name: "시작 조건 확인" }))
    expect(await screen.findByText("원 (KRW)")).toBeInTheDocument()
    expect(screen.getByText("14,000,000원")).toBeInTheDocument()
    expect(screen.getByText("700,000원 · 매월 25일")).toBeInTheDocument()
    expect(screen.getAllByText("10.0%").length).toBeGreaterThan(0)
    expect(screen.getByText("+5.00%p")).toBeInTheDocument()
    expect(screen.getByText("12,600,000원")).toBeInTheDocument()
  })
})

describe("모의투자 시작일: 분석일 이전도 (2026-11-11)", () => {
  const pv = (f: PaperIn): PaperPreview => ({ report_id: "r", run_id: "r", report_as_of: "2026-01-01", strategy: { id: "s", kind: "template", template: null, cash_ratio: 0, name_ko: "동일비중" }, strategy_options: [{ id: "s", kind: "template", template: null, cash_ratio: 0, name_ko: "동일비중", status: "pass", recommended: true, chosen: true }],
    start_date: f.start_date ?? "2026-03-02", data_start: "2021-01-04", data_ceiling: "2026-03-02", reconstructed_at_start: (f.start_date ?? "2026-03-02") !== "2026-01-01", initial_capital: cap("KRW"), contribution: { enabled: false, monthly_amount: 0, currency: "KRW", day: 25 },
    rebalance_rule: { count: 1, unit: "1m" }, benchmark: "SPY", tickers: ["MU"], weights: { MU: 1 }, cash_weight: 0, report_weights: { MU: 1 }, weight_diff: [{ ticker: "MU", report: 1, start: 1, delta: 0 }], allocation: [{ ticker: "MU", weight: 1, usd: 10_000, krw: 14_000_000, price_usd: 100 }],
    construct_info: { fallback: false, warnings: [] }, warnings: f.start_date && f.start_date < "2026-01-01" ? ["분석일 2026-01-01 보다 앞선 날로 시작합니다. 종목은 분석일에 고른 것이라, 그날 실제로 시작했을 때보다 결과가 좋게 나올 수 있습니다."] : [] })

  it("가격 자료가 있는 날부터 고를 수 있고 분석일 이전이면 알린다. 지난 날로 만들면 바로 지금까지 계산한 뒤 연다", async () => {
    window.history.replaceState(null, "", "/")
    const previewPaper = vi.fn((f: PaperIn) => Promise.resolve(pv(f)))
    const made = detail("KRW", [snap("2025-06-02", 10_000)], { p: { start_date: "2025-06-02" } })
    const createPaper = vi.fn(() => Promise.resolve(made)), refreshPaper = vi.fn(() => Promise.resolve(made))
    render(<ServiceContext.Provider value={service({ previewPaper, createPaper, refreshPaper })}><StartPaperDialog reportId="r" close={() => {}} /></ServiceContext.Provider>)
    const date = await screen.findByDisplayValue("2026-03-02")
    expect(date).toHaveAttribute("min", "2021-01-04")
    expect(date).toHaveAttribute("max", "2026-03-02")
    expect(screen.getByText(/2021-01-04 ~ 2026-03-02 사이 · 분석일 2026-01-01 이전도 됩니다/)).toBeInTheDocument()
    expect(screen.queryByText(/분석일보다 앞선 날입니다/)).toBeNull()
    fireEvent.change(date, { target: { value: "2025-06-02" } })
    expect(screen.getByText("분석일보다 앞선 날입니다. 종목은 분석일에 고른 것이라 결과가 실제보다 좋게 나올 수 있습니다.")).toBeInTheDocument()
    fireEvent.click(screen.getByRole("button", { name: "시작 조건 확인" }))
    expect(await screen.findByText(/분석일 2026-01-01 보다 앞선 날로 시작합니다/)).toBeInTheDocument()
    expect(screen.getByText("시작일이 리포트 기준일과 달라 그날 자료로 비중을 다시 계산했습니다")).toBeInTheDocument()
    expect(previewPaper).toHaveBeenLastCalledWith(expect.objectContaining({ start_date: "2025-06-02" }))
    fireEvent.click(screen.getByRole("button", { name: "이 조건으로 시작" }))
    await waitFor(() => expect(refreshPaper).toHaveBeenCalledWith("p1"))
    await waitFor(() => expect(window.location.hash).toBe("#/paper/p1"))
  })

  it("마지막 거래일에 시작하면 따로 계산하지 않고 바로 연다", async () => {
    window.history.replaceState(null, "", "/")
    const made = detail("KRW", [snap("2026-03-02", 10_000)], { p: { start_date: "2026-03-02" } })
    const refreshPaper = vi.fn(() => Promise.resolve(made))
    render(<ServiceContext.Provider value={service({ previewPaper: (f: PaperIn) => Promise.resolve(pv(f)), createPaper: () => Promise.resolve(made), refreshPaper })}><StartPaperDialog reportId="r" close={() => {}} /></ServiceContext.Provider>)
    await screen.findByDisplayValue("2026-03-02")
    fireEvent.click(screen.getByRole("button", { name: "시작 조건 확인" }))
    fireEvent.click(await screen.findByRole("button", { name: "이 조건으로 시작" }))
    await waitFor(() => expect(window.location.hash).toBe("#/paper/p1"))
    expect(refreshPaper).not.toHaveBeenCalled()
  })
})

describe("리밸런싱 거래 (첫 화면) · 리밸런싱 알림", () => {
  beforeEach(() => { window.localStorage.clear(); window.sessionStorage.clear() })  // 앞 테스트가 남긴 확인 기록을 지운다
  const t = (ticker: string, side: "buy" | "sell", value_usd: number) => ({ ticker, side, shares: value_usd / 100, price: 100, value_usd })
  const rebs: PaperRebalance[] = [
    { date: "2026-01-02", seq: 0, kind: "initial", before_weights: {}, target_weights: {}, applied_weights: {}, trades: [t("MU", "buy", 6000), t("NOW", "buy", 3000)], commission_usd: 4.5, turnover: 1, fallback: false, skipped: false },
    { date: "2026-02-02", seq: 1, kind: "rebalance", before_weights: {}, target_weights: {}, applied_weights: {}, trades: [t("MU", "buy", 200), t("NOW", "sell", 300)], commission_usd: 0.25, turnover: 0.03, fallback: false, skipped: false },
  ]
  const usdDetail = () => detail("USD", [snap("2026-01-02", 10_000), snap("2026-02-02", 11_000)], { rebalances: rebs })

  it("접힌 상세를 열지 않아도 개요 바로 아래(위험 위)에서 마지막 리밸런싱의 매수·매도와 다음 리밸런싱 시점을 보여 준다 (평소에는 강조 없음)", async () => {
    show(usdDetail())
    await screen.findByText("핵심 성과")
    const heads = screen.getAllByRole("heading", { level: 3 }).map((h) => h.textContent)
    expect(heads.slice(0, 4)).toEqual(["핵심 성과", "보유 구성", "리밸런싱", "최근 운용 기록"])  // 개요
    expect(heads.indexOf("리밸런싱 거래")).toBe(heads.indexOf("최근 운용 기록") + 1)
    expect(heads.indexOf("위험")).toBe(heads.indexOf("리밸런싱 거래") + 1)
    const card = within(screen.getByRole("heading", { name: "리밸런싱 거래" }).closest("section")!)
    await waitFor(() => expect(card.getByRole("list", { name: "매수한 종목" })).toHaveTextContent(/MU.*Micron Technology.*200\.00 USD.*2\.00주/))  // 회사명은 실행 결과에서 따로 온다
    expect(card.getByRole("list", { name: "매도한 종목" })).toHaveTextContent(/NOW.*300\.00 USD.*3\.00주/)
    expect(card.getByText(/2026-02-02 정기 리밸런싱/)).toBeInTheDocument()
    expect(card.getByText("2026년 3월 첫 거래일")).toBeInTheDocument()
    expect(card.queryByText("지금 리밸런싱할 시점입니다")).toBeNull()  // 처음 보는 모의투자는 이미 있던 리밸런싱을 확인한 것으로 시작
    expect(JSON.parse(window.localStorage.getItem("myfinsight.seen.v1")!).papers).toEqual({ p1: 1 })
    fireEvent.click(card.getByRole("button", { name: /전체 거래 기록 보기/ }))
    expect(screen.getByRole("button", { name: /거래·리밸런싱 상세/ })).toHaveAttribute("aria-expanded", "true")
  })
  it("확인하지 않은 리밸런싱이면 「지금 리밸런싱할 시점입니다」로 강조하고, 「확인했어요」를 누르면 이 브라우저에 확인 기록을 남기고 평소 모양으로 돌아간다", async () => {
    window.localStorage.setItem("myfinsight.seen.v1", JSON.stringify({ v: 1, reports: [], papers: { p1: 0 } }))
    show(usdDetail())
    expect(await screen.findByText("지금 리밸런싱할 시점입니다")).toBeInTheDocument()
    fireEvent.click(screen.getByRole("button", { name: "확인했어요" }))
    await waitFor(() => expect(screen.queryByText("지금 리밸런싱할 시점입니다")).toBeNull())
    expect(JSON.parse(window.localStorage.getItem("myfinsight.seen.v1")!).papers.p1).toBe(1)
  })
  it("아직 리밸런싱 전이면 시작할 때 산 종목을 보여 주고, 매수 후 보유 규칙이면 다음 시점을 말하지 않는다", async () => {
    show(detail("USD", [snap("2026-01-02", 10_000)], { rebalances: rebs.slice(0, 1), p: { rebalance_rule: { count: 0, unit: "1m" } } }))
    const card = within((await screen.findByRole("heading", { name: "리밸런싱 거래" })).closest("section")!)
    expect(card.getByText(/시작할 때 산 종목/)).toBeInTheDocument()
    expect(card.getByText(/리밸런싱 없음/)).toBeInTheDocument()
    expect(card.queryByText(/첫 거래일$/)).toBeNull()
    expect(card.getByText("매도 0종목")).toBeInTheDocument()
  })
})

describe("개요 · 접속 기록 · 리밸런싱 팝업 (2026-11-11)", () => {
  beforeEach(() => { window.localStorage.clear(); window.sessionStorage.clear() })
  const t = (ticker: string, side: "buy" | "sell", value_usd: number) => ({ ticker, side, shares: value_usd / 100, price: 100, value_usd })
  const reb = (seq: number, date: string, kind: "initial" | "rebalance", trades: ReturnType<typeof t>[]): PaperRebalance => ({ date, seq, kind, before_weights: {}, target_weights: {}, applied_weights: {}, trades, commission_usd: 0.5, turnover: 0.05, fallback: false, skipped: false })
  const base = [reb(0, "2026-01-02", "initial", [t("MU", "buy", 6000), t("NOW", "buy", 3000)]), reb(1, "2026-02-02", "rebalance", [t("MU", "buy", 200), t("NOW", "sell", 300)])]
  const withRebs = (rebalances: PaperRebalance[]) => detail("USD", [snap("2026-01-02", 10_000), snap("2026-03-02", 11_000)], { rebalances })
  const seenState = () => JSON.parse(window.localStorage.getItem("myfinsight.seen.v1")!)

  it("개요: 핵심 성과(왼쪽 그래프·오른쪽 숫자) 아래에 보유 구성·리밸런싱·최근 운용 기록. 바뀐 문구", async () => {
    show(withRebs(base))
    const overview = await screen.findByRole("region", { name: "개요" })
    expect(within(overview).getAllByRole("heading", { level: 3 }).map((h) => h.textContent)).toEqual(["핵심 성과", "보유 구성", "리밸런싱", "최근 운용 기록"])
    expect(within(overview).getByText("현재 평가액")).toBeInTheDocument()
    expect(within(overview).getByText("2026년 4월 첫 거래일")).toBeInTheDocument()  // 다음 리밸런싱 (마지막 평가일 3월 2일 다음 달)
    expect(within(overview).getByText("매수 1종목 · 매도 1종목")).toBeInTheDocument()
    expect(within(overview).getByText("현금 비중")).toBeInTheDocument()
    expect(screen.getByText("직전 거래일까지 갱신합니다.")).toBeInTheDocument()
    expect(screen.getByRole("button", { name: "모의투자 중지" })).toBeInTheDocument()
    expect(screen.queryByText(/실시간 시세가 아니라/)).toBeNull()
    expect(screen.queryByText(/가상 자본으로 따라갑니다/)).toBeNull()
    expect(screen.queryByText(/모의운용/)).toBeNull()
  })

  it("처음 들어오면 팝업 없이 접속을 기록하고, 다음에 들어왔을 때 그 뒤 새 리밸런싱이 있으면 팝업으로 알린다. 확인하면 확인 기록을 남긴다", async () => {
    const first = show(withRebs(base))
    await screen.findByText("핵심 성과")
    expect(screen.queryByRole("dialog", { name: "리밸런싱할 시점입니다" })).toBeNull()
    await waitFor(() => expect(seenState().visits.p1.seq).toBe(1))
    expect(seenState().visits.p1.at).toMatch(/^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}$/)  // 이 컴퓨터 시각
    first.unmount()
    show(withRebs([...base, reb(2, "2026-03-02", "rebalance", [t("MU", "sell", 400), t("NOW", "buy", 500)])]))
    const dlg = await screen.findByRole("dialog", { name: "리밸런싱할 시점입니다" })
    expect(dlg).toHaveTextContent("2026-03-02 정기 리밸런싱")
    expect(within(dlg).getByRole("list", { name: "매수한 종목" })).toHaveTextContent(/NOW.*500\.00 USD/)
    await waitFor(() => expect(within(dlg).getByRole("list", { name: "매도한 종목" })).toHaveTextContent(/MU.*Micron Technology.*400\.00 USD/))  // 회사명은 실행 결과에서 따로 온다
    expect(screen.getByText(/지난 접속 \d{4}-\d{2}-\d{2} \d{2}:\d{2}/)).toBeInTheDocument()
    fireEvent.click(within(dlg).getByRole("button", { name: "확인했어요" }))
    await waitFor(() => expect(screen.queryByRole("dialog", { name: "리밸런싱할 시점입니다" })).toBeNull())
    expect(seenState().papers.p1).toBe(2)
    expect(screen.queryByText("지금 리밸런싱할 시점입니다")).toBeNull()  // 아래 거래 카드 안내도 함께 사라진다
  })

  it("팝업을 닫기만 하면 확인 기록은 그대로(아래 안내는 남음)이고, 다음 접속에는 다시 띄우지 않는다", async () => {
    window.localStorage.setItem("myfinsight.seen.v1", JSON.stringify({ v: 1, reports: [], papers: { p1: 1 }, visits: { p1: { at: "2026-02-10T09:30:00", seq: 1 } } }))
    const more = withRebs([...base, reb(2, "2026-03-02", "rebalance", [t("MU", "sell", 400)])])
    const r1 = show(more)
    const dlg = await screen.findByRole("dialog", { name: "리밸런싱할 시점입니다" })
    expect(screen.getByText("· 지난 접속 2026-02-10 09:30")).toBeInTheDocument()
    fireEvent.click(within(dlg).getByRole("button", { name: "닫기" }))
    expect(screen.queryByRole("dialog", { name: "리밸런싱할 시점입니다" })).toBeNull()
    expect(screen.getByText("지금 리밸런싱할 시점입니다")).toBeInTheDocument()
    expect(seenState().papers.p1).toBe(1)
    r1.unmount()
    show(more)
    await screen.findByText("핵심 성과")
    expect(screen.queryByRole("dialog", { name: "리밸런싱할 시점입니다" })).toBeNull()
    expect(screen.getByText("지금 리밸런싱할 시점입니다")).toBeInTheDocument()
  })

  it("이미 확인한 리밸런싱이나 거래 없는 리밸런싱은 팝업을 띄우지 않는다", async () => {
    window.localStorage.setItem("myfinsight.seen.v1", JSON.stringify({ v: 1, reports: [], papers: { p1: 2 }, visits: { p1: { at: "2026-02-10T09:30:00", seq: 1 } } }))
    const r = show(withRebs([...base, reb(2, "2026-03-02", "rebalance", [t("MU", "sell", 400)])]))
    await screen.findByText("핵심 성과")
    expect(screen.queryByRole("dialog", { name: "리밸런싱할 시점입니다" })).toBeNull()
    r.unmount()
    window.localStorage.setItem("myfinsight.seen.v1", JSON.stringify({ v: 1, reports: [], papers: { p1: 1 }, visits: { p1: { at: "2026-02-10T09:30:00", seq: 1 } } }))
    show(withRebs([...base, reb(2, "2026-03-02", "rebalance", [])]))
    await screen.findByText("핵심 성과")
    expect(screen.queryByRole("dialog", { name: "리밸런싱할 시점입니다" })).toBeNull()
  })

  it("목록 설명 문장", async () => {
    render(<ServiceContext.Provider value={service({ listPaper: () => Promise.resolve([withRebs(base).summary]), getPaper: () => Promise.resolve(withRebs(base)) })}><PaperScreen /></ServiceContext.Provider>)
    expect(await screen.findByText("완료된 리포트의 전략을 가상으로 시뮬레이션 합니다.")).toBeInTheDocument()
    expect(screen.queryByText(/가상 자본으로 따라갑니다/)).toBeNull()
  })
})
