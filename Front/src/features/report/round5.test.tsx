import { describe, expect, it } from "vitest"
import { render, screen } from "@testing-library/react"
import { NewsEffectMini, ValidationMini } from "./Dashboard"
import { better } from "./ComparisonScreen"
import { navigate } from "../../app/router"

describe("라운드 5 대시보드", () => {
  it("검증 미니: 허용 초과(flag) 배지와 세 숫자(실현·허용·비교지수) 비교가 보인다", () => {
    render(<ValidationMini v={{ n_pass: 0, n_warn: 9, n_fail: 0, n_candidates: 9, chosen_status: "warn", failed_rules_ko: [], rules_ko: [{ rule: "R1", name_ko: "최대낙폭", level: "flag", status: "flag", message_ko: "최대낙폭 10.9% vs 허용 8.0% (같은 기간 SPY 18.8%) — 허용보다 2.9%p 큼" }, { rule: "R2", name_ko: "목표수익", level: "soft", status: "pass", message_ko: "목표 달성" }], r1: { mdd: 0.109, tolerance: 0.08, benchmark_mdd: 0.188, excess: 0.029, status: "flag" }, tolerance_note_ko: "손실 감내 수준 8.0% · 낙폭 맞춤안 목표 6.4% (손실 시 매도 성향 ×0.8)" }} onMore={() => {}} />)
    expect(screen.getByText("허용 초과")).toBeInTheDocument()
    expect(screen.getByText("표시")).toBeInTheDocument()
    expect(screen.getByLabelText("최대낙폭 비교")).toHaveTextContent("허용 낙폭")
    expect(screen.getByText(/후보 9개 비교 · 추천 1개/)).toBeInTheDocument()
    expect(screen.queryByText(/미통과 0/)).toBeNull()
  })
  it("뉴스 반영 효과: 두 적중률과 CAGR 차이를 보여 주고, 꺼져 있으면 사유만", () => {
    const { unmount } = render(<NewsEffectMini n={{ disabled: false, bl_id: "wf_bl_news", bl_label_ko: "뉴스 뷰", base_id: "wf_equal_weight", base_label_ko: "동일비중", bl_cagr: 0.063, base_cagr: 0.062, diff_cagr: 0.001, bl_excess_cagr: -0.11, base_excess_cagr: -0.115, bl_mdd: -0.1086, base_mdd: -0.1085, hit_365: 0.6, hit_next_rb: 0.5, n_views: 28, n_dates: 7, n_rebalances: 7, n_fallback: 0, annualized_reliable: true }} onMore={() => {}} />)
    expect(screen.getByText("뉴스 반영 효과")).toBeInTheDocument()
    expect(screen.getByText("50.0%")).toBeInTheDocument(); expect(screen.getByText("60.0%")).toBeInTheDocument()
    expect(screen.getByText("+0.10%p")).toBeInTheDocument()
    unmount()
    render(<NewsEffectMini n={{ disabled: true, reason_ko: "뉴스 반영을 끈 분석입니다 (프로필 설정)" }} onMore={() => {}} />)
    expect(screen.getByText(/뉴스 반영을 끈 분석/)).toBeInTheDocument()
  })
  it("비교 화면: 변동성은 낮을수록, 낙폭은 0 에 가까울수록 좋다", () => {
    expect(better("ann_vol", 0.2, 0.15)).toBe(true)
    expect(better("ann_vol", 0.15, 0.2)).toBe(false)
    expect(better("max_drawdown", -0.3, -0.2)).toBe(true)
    expect(better("cagr", 0.1, 0.12)).toBe(true)
    expect(better("cagr", null, 0.1)).toBeNull()
  })
  it("navigate 는 scroll:false 면 맨 위로 스크롤하지 않는다", () => {
    const calls: unknown[] = []
    const orig = window.scrollTo
    window.scrollTo = ((...a: unknown[]) => { calls.push(a) }) as typeof window.scrollTo
    navigate({ page: "report", reportId: "run_1", rb: 2 }, { scroll: false })
    expect(calls).toHaveLength(0)
    navigate({ page: "report", reportId: "run_1", rb: 3 })
    expect(calls).toHaveLength(1)
    window.scrollTo = orig
  })
})
