import { describe, expect, it, vi } from "vitest"
import { fireEvent, render, screen, waitFor } from "@testing-library/react"
import { ServiceContext } from "../../app/providers"
import type { AnalysisService } from "../../api/service"
import type { EvidenceRecord, ReportDoc, TimelineBlock } from "../../api/types"
import { ReportContext, type ReportCtx } from "./context"
import { SourceDrawer } from "./SourceDrawer"
import { RebalanceTimeline } from "./RebalanceTimeline"

const evidence: EvidenceRecord[] = [
  { id: "ev1", kind: "news", title: "NVDA 뉴스", source: "Reuters", tickers: ["NVDA"], published_at: "2025-12-20" },
  { id: "dc5", kind: "disclosure", title: "8-K 2.02 · 실적 발표", source: "SEC EDGAR", tickers: ["AMD"], available_on: "2025-12-11", event_label_ko: "실적 발표" },
  { id: "fin:US-NVDA:x:2025-12-30", kind: "financial", title: "지표", source: "valuation_daily", tickers: ["NVDA"], data_as_of: "2025-12-30" },
]
const doc = { run_id: "run_1", sections: [], evidence, evidence_summary: { total: 3, cited: 3, by_kind: { news: 1, disclosure: 1, financial: 1 } } } as unknown as ReportDoc
const ctx = (over: Partial<ReportCtx> = {}): ReportCtx => ({ reportId: "run_1", doc, numberOf: (id) => id, openEvidence: () => {}, openDrawer: () => {}, jump: () => {}, selectedRb: null, setSelectedRb: () => {}, openCompany: null, setOpenCompany: () => {}, ...over })
const svc = (over: Partial<AnalysisService>) => over as unknown as AnalysisService
const wrap = (ui: React.ReactNode, s: Partial<AnalysisService>, c: ReportCtx = ctx()) => render(<ServiceContext.Provider value={svc(s)}><ReportContext.Provider value={c}>{ui}</ReportContext.Provider></ServiceContext.Provider>)

describe("SourceDrawer", () => {
  it("서버 색인이 없으면(404) 문서 안의 근거로 대신하고 종류·종목으로 걸러진다", async () => {
    wrap(<SourceDrawer filter={{ ids: null }} close={() => {}} onOpen={() => {}} />, { getReportEvidence: vi.fn(async () => null) })
    await waitFor(() => expect(screen.getByText(/서버 색인을 쓸 수 없어/)).toBeInTheDocument())
    expect(screen.getByText(/NVDA 뉴스/)).toBeInTheDocument(); expect(screen.getByText(/실적 발표 · 8-K/)).toBeInTheDocument()
    fireEvent.change(screen.getByLabelText("종류"), { target: { value: "disclosure" } })
    expect(screen.queryByText(/NVDA 뉴스/)).toBeNull(); expect(screen.getByText(/실적 발표 · 8-K/)).toBeInTheDocument()
    fireEvent.change(screen.getByLabelText("종류"), { target: { value: "" } })
    fireEvent.change(screen.getByLabelText("종목"), { target: { value: "NVDA" } })
    expect(screen.getAllByRole("listitem")).toHaveLength(2)
  })
  it("서버 색인이 있으면 그 페이지를 보여 주고 필터를 서버에 보낸다", async () => {
    const getReportEvidence = vi.fn(async (_id: string, q?: Record<string, unknown>) => ({ total: 120, offset: 0, limit: 50, index_total: 120, by_kind: { news: 100, disclosure: 20 }, items: [{ id: "ev9", kind: "news", title: `서버 ${q?.kind ?? "전체"}`, source: "s", tickers: ["X"] }] }))
    wrap(<SourceDrawer filter={{ ids: null }} close={() => {}} onOpen={() => {}} />, { getReportEvidence })
    await waitFor(() => expect(screen.getByText("서버 전체")).toBeInTheDocument())
    expect(screen.getAllByText(/120건/).length).toBeGreaterThan(0); expect(screen.getByText("1 / 3")).toBeInTheDocument()
    fireEvent.change(screen.getByLabelText("종류"), { target: { value: "news" } })
    await waitFor(() => expect(screen.getByText("서버 news")).toBeInTheDocument())
    expect(getReportEvidence).toHaveBeenLastCalledWith("run_1", expect.objectContaining({ kind: "news", limit: 50, offset: 0 }))
  })
})

const tl: TimelineBlock = { type: "timeline", title_ko: "타임라인", portfolio_id: "wf_bl_news", walkforward: true, items: [0, 1, 2].map((i) => ({ seq: i, date: `2024-0${i + 1}-02`, kind: i === 2 ? "closing" : "rebalance", n_trading_days_to_date: i * 20, value_usd: 1000 + i, benchmark_value_usd: 1000, net_invested_usd: 1000, since_last: i ? { return: 0.01 * i, benchmark_return: 0.005, excess: 0.005, max_drawdown: -0.02 } : null, n_trades: i, turnover: null, commission_usd: 1, to_date: null, cash_after: 0, news: { n_articles: 3, n_disclosures: 2, n_tickers_with_evidence: 2, n_views: i === 1 ? 0 : 1, fallback: i === 1, window: ["2024-01-01", "2024-01-02"] }, views: i === 1 ? [] : [{ summary_ko: `뷰 ${i}`, confidence: 0.3, evidence_ids: ["ev1"], evidence_type: "mixed" }], top_delta: [] })) }

describe("RebalanceTimeline", () => {
  it("마지막 시점이 선택되고, ←/→ 로 이동하며, 상세는 시점마다 한 번만 조회한다", async () => {
    const getReportCheckpoint = vi.fn(async (_r: string, seq: number) => ({ portfolio_id: "wf_bl_news", label_ko: "L", checkpoint: { seq, date: "d", kind: "rebalance", n_trading_days_to_date: 0, weights: { target: { NVDA: 0.5 }, before: null, after: { NVDA: 0.5 }, cash_before: null, cash_after: 0.5 }, holdings: [{ ticker: "NVDA", shares_after: 1, price: 1, value_usd: 500, weight_before: null, weight_after: 0.5, period_return: 0, period_contribution: 0 }], trades: [], turnover: null, commission_usd: 0, money: { value_usd: 1000, cumulative_contributions_usd: 0, net_invested_usd: 1000, profit_usd: 0, benchmark_value_usd: 1000 }, since_last: null, to_date: null, drift: null }, names: { NVDA: "엔비디아" }, views: [], news_summary: null, narrative_ko: `서술 ${seq}`, market_model: null }))
    const setSelectedRb = vi.fn()
    wrap(<RebalanceTimeline b={tl} />, { getReportCheckpoint }, ctx({ setSelectedRb }))
    expect(screen.getByRole("option", { name: "2024-03-02 기간 종료" })).toHaveAttribute("aria-selected", "true")
    await waitFor(() => expect(screen.getByText("서술 2")).toBeInTheDocument())
    fireEvent.keyDown(screen.getByRole("listbox"), { key: "ArrowLeft" })
    expect(screen.getByRole("option", { name: "2024-02-02 리밸런싱" })).toHaveAttribute("aria-selected", "true")
    expect(setSelectedRb).toHaveBeenCalledWith(1)
    expect(screen.getByText(/근거 부족으로 기준 비중 유지/)).toBeInTheDocument()
    await waitFor(() => expect(screen.getByText("서술 1")).toBeInTheDocument())
    fireEvent.keyDown(screen.getByRole("listbox"), { key: "ArrowRight" })
    await waitFor(() => expect(screen.getByText("서술 2")).toBeInTheDocument())
    expect(getReportCheckpoint).toHaveBeenCalledTimes(2)  // 2 → 1 → 2 (캐시)
    expect(screen.getByText("뷰 2")).toBeInTheDocument()
    expect(screen.getByText(/뉴스·공시 뷰 적용 2회 · 기준 비중 유지 1회/)).toBeInTheDocument()
    fireEvent.click(screen.getByRole("button", { name: /전체 표 보기/ }))
    expect(screen.getAllByRole("row").length).toBeGreaterThan(3)
  })
})
