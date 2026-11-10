import { describe, expect, it, vi } from "vitest"
import { fireEvent, render, renderHook, screen, waitFor } from "@testing-library/react"
import { ServiceContext } from "../../app/providers"
import { ApiError } from "../../api/client"
import type { AnalysisService } from "../../api/service"
import type { CompaniesBlock, CompanyItem, DialogState } from "../../api/types"
import { CompanyList, selectionStatus } from "./CompanyList"
import { metricValue } from "./metrics"
import { RequestHistory } from "./RequestHistory"
import { useFluidShell } from "./useFluidShell"

// 리포트 화면 개선 회귀 테스트: 상태 문구가 데이터의 뜻과 맞는지, 요청 내역이 실제 기록만 보여 주는지, 범위 스타일이 다른 화면에 남지 않는지.

const company = (over: Partial<CompanyItem> = {}): CompanyItem => ({ ticker: "PLTR", name: "Palantir", market: "US", sector: "IT", sub_industry: "", summary: "", theme_reason_ko: "", theme_confidence: null, weight: null, in_selection_now: false, rank_now: null, metric_now: null, in_backtest: true, rank_bt: 2, metric_bt: 13.34, fact_id: null, rationale_ko: [], evidence_ids: [], n_news: 0, n_disclosures: 0, ...over })
const block = (items: CompanyItem[], metric = "pe_ttm"): CompaniesBlock => ({ type: "companies", title_ko: "기업", metric, metric_ko: "PER", direction: "asc", as_of_now: "2026-10-30", as_of_bt: "2025-10-30", portfolio_id: "p", items })

describe("기업 상태 문구", () => {
  it("선정 상태를 두 기준일의 실제 값으로만 구분한다", () => {
    expect(selectionStatus({ in_selection_now: true, in_backtest: true })).toBeNull()
    expect(selectionStatus({ in_selection_now: true, in_backtest: false })).toContain("분석 기준일에만 선정")
    expect(selectionStatus({ in_selection_now: false, in_backtest: true })).toContain("백테스트 시작일에만 선정")
    expect(selectionStatus({ in_selection_now: false, in_backtest: false })).toBe("두 기준일 모두 선정되지 않음")
  })
  it("PER 은 배수로, 수익률은 비율로 표시한다 (13.34 가 +1,334% 로 보이지 않는다)", () => {
    expect(metricValue("pe_ttm", 13.34)).toBe("13.34배")
    expect(metricValue("return_12m_1m", 0.5)).toBe("+50.00%")
  })
  it("설명이 없는 종목은 빈칸으로 두지 않고, 이유를 아는 경우와 모르는 경우를 구분하며, 옛 문구를 쓰지 않는다", () => {
    const { unmount } = render(<CompanyList b={block([company()])} />)
    expect(screen.queryByText(/이 종목은 분석 기준일에 선정되지 않았습니다/)).toBeNull()  // 카드는 접힌 채 시작
    fireEvent.click(screen.getByRole("button", { name: /PLTR/ }))
    expect(screen.getByText("분석 기준일 선정 종목이 아니어서 선정 이유 설명이 없습니다.")).toBeInTheDocument()
    expect(screen.getAllByText("추천안 비중 없음").length).toBeGreaterThan(0)
    expect(screen.queryByText(/미보유|미선정$|백테스트 미포함$/)).toBeNull()
    expect(screen.getAllByText(/13.34배/).length).toBeGreaterThan(0)
    unmount()
    render(<CompanyList b={block([company({ in_selection_now: true, in_backtest: true, weight: 0.1 })])} />)
    fireEvent.click(screen.getByRole("button", { name: /PLTR/ }))
    expect(screen.getByText("선정 이유 설명이 없습니다.")).toBeInTheDocument()
  })
})

const q = (seq: number, over: object) => ({ seq, field: "f", kind: "preference", question_ko: `질문${seq}`, options: [], allow_free_text: true, priority: 1, asked_at: "2026-11-01T17:54:02+09:00", answered_at: "2026-11-01T17:54:23+09:00", answer: `답${seq}`, ...over })
const state = (over: Partial<DialogState>) => ({ idea: "반도체 메모리 기업에 투자하고 싶어", questions: [q(2, {}), q(1, { skipped: true }), q(3, { answered_at: null, answer: null })], revision: null, conditions: [], confirmation: { rows: [{ field: "a", group_ko: "자금", label_ko: "섹터당 상한", value_ko: "100%", profile_value_ko: "75%", changed: true }, { field: "b", group_ko: "자금", label_ko: "투자기간", value_ko: "3년", changed: false }] }, ...over }) as unknown as DialogState
const svc = (getRequest: () => Promise<DialogState>) => ({ getRequest }) as unknown as AnalysisService
const show = (s: AnalysisService) => render(<ServiceContext.Provider value={s}><RequestHistory requestId="r1" /></ServiceContext.Provider>)

describe("투자 아이디어와 요청 내역", () => {
  it("실제 아이디어·답한 질문·달라진 조건만 시간 순서로 보여 준다", async () => {
    show(svc(() => Promise.resolve(state({}))))
    expect(await screen.findByText("반도체 메모리 기업에 투자하고 싶어")).toBeInTheDocument()
    expect(screen.getByText("섹터당 상한")).toBeInTheDocument()  // 최종 반영 조건은 처음부터 보인다
    expect(screen.queryByRole("list", { name: "요청 기록" })).toBeNull()  // 질문·답변 전체는 접혀 있다
    fireEvent.click(screen.getByRole("button", { name: /추가 질문과 답변/ }))
    const list = screen.getByRole("list", { name: "요청 기록" }).textContent ?? ""
    expect(list.indexOf("질문1")).toBeLessThan(list.indexOf("질문2"))
    expect(screen.getByText("답하지 않음 (기본값 사용)")).toBeInTheDocument()
    expect(screen.getByText("답2")).toBeInTheDocument()
    expect(screen.queryByText("질문3")).toBeNull()  // 답하지 않은 질문은 기록이 아니다
    expect(screen.getByText("섹터당 상한")).toBeInTheDocument()
    expect(screen.queryByText("투자기간")).toBeNull()
  })
  it("변경이 없으면 그렇게 말하고, 불러오지 못하면 기록을 지어내지 않는다", async () => {
    const { unmount } = show(svc(() => Promise.resolve(state({ questions: [], confirmation: null }))))
    expect(await screen.findByText("기본 투자조건과 달라진 항목이 없습니다.")).toBeInTheDocument()
    unmount()
    show(svc(() => Promise.reject(new ApiError("NOT_FOUND", "요청이 없습니다.", 404))))
    expect(await screen.findByText(/요청 내역을 불러오지 못했습니다/)).toBeInTheDocument()
    expect(screen.queryByRole("list")).toBeNull()
  })
})

describe("리포트 전용 화면 폭", () => {
  it("리포트 화면에서만 켜지고 나가면 꺼진다", async () => {
    const { unmount } = renderHook(() => useFluidShell())
    await waitFor(() => expect(document.documentElement).toHaveClass("report-fluid"))
    unmount()
    expect(document.documentElement).not.toHaveClass("report-fluid")
    vi.restoreAllMocks()
  })
})
