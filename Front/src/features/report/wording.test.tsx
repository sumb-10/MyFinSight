import { describe, expect, it } from "vitest"
import { fireEvent, render, screen } from "@testing-library/react"
import type { Block, ReportDoc } from "../../api/types"
import { ConditionRules } from "./Dashboard"
import { Funnel } from "./blocks/blocks"
import { Blocks } from "./sections"
import { HelpTip } from "./terms"
import { explainReason, kpiName, pairCagr, pickSentence, r1Text, strategyInfo, timelineTitle } from "./wording"
import { HOLDING_PALETTE, holdingColor } from "./colors"

// 표시 문구: 서버 문장 틀에 맞는 것만 풀어 쓰고, 숫자는 원문에서만 가져오며, 모르는 것은 원문 그대로 둔다.

const o = { short: false }

describe("핵심 판단 이유", () => {
  it("서버 판단 이유 조각을 제목 + 설명으로 풀고, 숫자는 원문 그대로 쓴다", () => {
    expect(explainReason("후보 16개 중 1위.", o)).toMatchObject({ title: "비교한 투자 구성안 중 1위", desc: expect.stringContaining("16개 투자 구성안") })
    expect(explainReason("목표수익(연 8.0%) 충족", o)).toMatchObject({ title: "목표 수익률 충족", tone: "good", desc: expect.stringContaining("연 8.0%") })
    expect(explainReason("SPY 대비 초과 CAGR +65.1%p", o).desc).toBe("같은 기간 SPY의 연평균 수익률(CAGR)보다 +65.1%p 높았습니다.")
    expect(explainReason("SPY 대비 초과 CAGR -3.2%p", o)).toMatchObject({ title: "SPY보다 낮은 연평균 수익률", tone: "warn" })
    expect(explainReason("최대낙폭 29.9% vs 허용 30.0% (여유 0.1%p)", o)).toMatchObject({ title: "허용 손실 범위 안", desc: expect.stringContaining("0.1%p 작았습니다") })
    expect(explainReason("최대낙폭 30.7% vs 허용 20.0% (10.7%p 초과)", o)).toMatchObject({ title: "허용 손실 범위 초과", tone: "warn" })
    expect(explainReason("Sharpe 1.44로 가장 높음", o).title).toBe("위험 대비 수익성 1위")
    expect(explainReason("Sharpe 1.61", o).desc).toMatch(/가장 높은 구성안은 아니었지만/)  // '가장 높음'이 없으면 1위라고 하지 않는다
    expect(explainReason("시가총액비중의 주식 비중을 79%로 줄여 과거 최대낙폭을 목표 30.0% 안에 맞춘 구성", o).desc).toMatch(/주식 비중을 79%로 줄이고/)
    expect(explainReason("CAGR 77.4%, 최종 평가금액 29,746 USD.", { short: true })).toMatchObject({ desc: "연평균 수익률(CAGR) 77.4% (연 환산, 참고용), 백테스트 기간 끝의 평가금액 29,746 USD입니다.", annual: true })
  })
  it("모르는 문장은 제목을 만들지 않고 원문 그대로 둔다", () => {
    expect(explainReason("새로운 서버 문장 [ev1]", o)).toEqual({ title: null, desc: "새로운 서버 문장 [ev1]" })
  })
})

describe("추천 기준 문장", () => {
  it("결과 상태에 따라 문장을 나누고, 추천이 없으면 추천했다고 하지 않는다", () => {
    const v = (status: "recommended" | "recommended_warn" | "insufficient") => ({ status, label_ko: status === "insufficient" ? "구성 불충분: 동일비중" : "추천", headline_ko: "", chosen_portfolio_id: "x", chosen_label_ko: "x" })
    expect(pickSentence(16, "SPY", v("recommended"))).toBe("16개 투자 구성안을 목표 수익률 달성 여부, SPY보다 나았는지, 허용 손실을 넘은 정도, 위험 대비 수익성(Sharpe)을 차례로 고려해 비교하고 1개를 추천했습니다.")
    expect(pickSentence(16, "SPY", v("recommended_warn"))).toMatch(/1개를 골랐지만, 주의할 점이 있습니다/)
    const none = pickSentence(16, "SPY", v("insufficient"))
    expect(none).toMatch(/「구성 불충분: 동일비중」로 추천한 구성안이 없습니다/); expect(none).not.toMatch(/추천했습니다|골랐/)
  })
})

describe("지표·제목 이름", () => {
  it("기간 수익률과 CAGR 을 섞지 않고, CAGR 은 연평균 수익률(CAGR) 로 함께 쓴다", () => {
    expect(kpiName({ id: "cagr", label_ko: "기간 수익률 (251거래일)" })).toEqual({ name: "전체 기간 수익률", sub: "251거래일 기준" })
    expect(kpiName({ id: "cagr", label_ko: "연평균 수익률 (CAGR)" })).toEqual({ name: "연평균 수익률(CAGR)" })
    expect(kpiName({ id: "excess", label_ko: "비교지수(SPY) 대비 (기간)" }).name).toBe("SPY 대비 전체 기간 수익률 차이")
    expect(kpiName({ id: "excess", label_ko: "비교지수(SPY) 대비" }).name).toBe("SPY 대비 연평균 수익률(CAGR) 차이")
    expect(kpiName({ id: "x", label_ko: "모르는 지표" }).name).toBe("모르는 지표")
    expect(pairCagr("CAGR 47.0% vs 목표 8.0% (전체 CAGR 로 판정)")).toBe("연평균 수익률(CAGR) 47.0% vs 목표 8.0% (전체 연평균 수익률(CAGR) 로 판정)")
    expect(pairCagr("연평균 수익률 (CAGR)")).toBe("연평균 수익률 (CAGR)")
  })
  it("리밸런싱 제목의 중첩 괄호를 구분 기호로 바꾸고, 전략명·비율은 그대로 둔다", () => {
    expect(timelineTitle("리밸런싱 타임라인 (낙폭 맞춤안 (주식 79% + 현금 21%, 시가총액비중 기준))")).toEqual(["낙폭 맞춤안", "주식 79%", "현금 21%", "시가총액비중 기준"])
    expect(timelineTitle("리밸런싱 타임라인 (동일비중)")).toEqual(["동일비중"])
    expect(timelineTitle("다른 제목")).toBeNull()
  })
  it("최대낙폭 규칙 문장은 괄호를 겹치지 않게 둘로 나누고, 숫자는 원문 그대로 둔다", () => {
    expect(r1Text("최대낙폭 29.9% vs 허용 30.0% (같은 기간 SPY 매수보유 (동일 적립) 8.9%)")).toEqual({ main: "최대낙폭 29.9% vs 허용 30.0%", bench: "같은 기간 SPY 매수 후 보유·동일 적립 시 8.9%" })
    expect(r1Text("최대낙폭 30.7% vs 허용 20.0% (같은 기간 SPY 매수보유 (동일 적립) 18.8%) — 허용보다 10.7%p 큼")).toEqual({ main: "최대낙폭 30.7% vs 허용 20.0% — 허용보다 10.7%p 큼", bench: "같은 기간 SPY 매수 후 보유·동일 적립 시 18.8%" })
    expect(r1Text("최대낙폭 30.7% vs 허용 20.0%")).toBeNull()  // 비교지수가 없는 문장은 원문 그대로
  })
  it("종목 색은 비중 순서대로 정해진 8색이고, 9번째부터는 새 색을 만들지 않는다", () => {
    const ids = Array.from({ length: 10 }, (_, i) => `T${i}`)
    expect(ids.slice(0, 8).map((t) => holdingColor(t, ids))).toEqual(HOLDING_PALETTE)
    expect(holdingColor("T8", ids)).toBe("#94a3b8"); expect(holdingColor("없음", ids)).toBe("#94a3b8")
  })
  it("전략 설명은 전략 ID 로 정하고, 모르는 전략은 설명하지 않는다", () => {
    expect(strategyInfo("dd_match_market_cap")?.short).toBe("주식과 현금 비중을 조절해 과거 손실 위험을 관리하려는 전략입니다.")
    expect(strategyInfo("dd_match_market_cap")?.help).toMatch(/미래 손실이 해당 수준 이하로 제한된다는 의미는 아닙니다/)
    expect(strategyInfo("equal_weight")?.short).toMatch(/같은 비율/)
    expect(strategyInfo("wf_market_cap")?.help).toMatch(/walk-forward/)
    expect(strategyInfo("benchmark_SPY")?.help).toMatch(/S&P 500 지수를 따라가는 ETF/)
    expect(strategyInfo("something_new")).toBeNull()
  })
})

describe("조건 검증·선정 과정·시장 원문", () => {
  it("비교지수 대비 규칙은 「연평균 수익률(CAGR) 차이」 이름과 큰 숫자로, %p 단위를 그대로", () => {
    render(<ConditionRules bench="SPY" v={{ n_pass: 1, n_warn: 0, n_fail: 0, n_candidates: 16, chosen_status: "pass", failed_rules_ko: [], rules_ko: [{ rule: "R3", name_ko: "비교지수 대비", level: "soft", status: "pass", message_ko: "SPY 대비 초과 CAGR +65.1%p" }] }} verdict={{ status: "recommended", label_ko: "추천", headline_ko: "", chosen_portfolio_id: "x", chosen_label_ko: "x" }} />)
    expect(screen.getByText("SPY 대비 연평균 수익률(CAGR) 차이")).toBeInTheDocument()
    expect(screen.getByText("+65.1%p")).toBeInTheDocument()
    expect(screen.queryByText("같은 기준으로 계산한 과거 연평균 수익률의 차이입니다.")).toBeNull()  // 설명 문장 없이 이름과 숫자만
    expect(screen.getByText(/16개 투자 구성안을 .* 1개를 추천했습니다/)).toBeInTheDocument()
  })
  it("선정 과정 번호는 「N단계」로, 제외와 재선정의 뜻을 구분해 적는다", () => {
    render(<Funnel b={{ type: "funnel", items: [{ label_ko: "투자 가능 종목", count: 518 }, { label_ko: "테마 관련 후보", count: 22 }, { label_ko: "최종 선정 (2026-10-30, 섹터 분산 적용)", count: 5 }, { label_ko: "백테스트용 재선정 (2025-10-30)", count: 5 }] }} />)
    expect(screen.getAllByText(/^\d단계$/).map((x) => x.textContent)).toEqual(["1단계", "2단계", "3단계", "4단계"])
    expect(screen.queryByText("선정에서 제외된 종목")).toBeNull()  // 단계 설명 문장은 두지 않는다
    expect(screen.queryByText(/백테스트 시작일 당시 알 수 있던 자료만으로/)).toBeNull()
  })
  it("시장 섹션의 두 문단 묶음은 내용에 맞는 다른 이름이고, 문단은 모두 남는다", () => {
    const blocks = [{ type: "paragraphs", items: ["아이디어 해석 문단"], src: "14b" }, { type: "table", title_ko: "요청 내용", columns: [{ key: "k", label_ko: "항목" }], rows: [{ k: "투자금" }], group_ko: "요청 조건 확인" }, { type: "paragraphs", items: ["시장 문단 1", "시장 문단 2"], src: "14c" }] as Block[]
    render(<Blocks blocks={blocks} doc={{ sections: [], datasets: { dates: [], series: {} }, kpis: [], header: {} } as unknown as ReportDoc} sec="market" />)
    fireEvent.click(screen.getByRole("button", { name: /아이디어 해석/ }))
    fireEvent.click(screen.getByRole("button", { name: /시장·뉴스 분석 원문/ }))
    expect(screen.queryByRole("button", { name: /^시장 분석 원문/ })).toBeNull()
    for (const t of ["아이디어 해석 문단", "시장 문단 1", "시장 문단 2"]) expect(screen.getByText(t)).toBeInTheDocument()
  })
  it("도움말은 눌러서 열고, 닫기 단추·Esc·바깥 누르기로 닫는다", () => {
    render(<div><HelpTip label="CAGR">연평균 수익률 설명</HelpTip><button type="button">바깥</button></div>)
    const btn = screen.getByRole("button", { name: "CAGR 설명 보기" })
    fireEvent.click(btn); expect(screen.getByRole("dialog", { name: "CAGR 설명" })).toHaveTextContent("연평균 수익률 설명")
    fireEvent.click(screen.getByRole("button", { name: "설명 닫기" })); expect(screen.queryByRole("dialog")).toBeNull()
    fireEvent.click(btn); fireEvent.keyDown(window, { key: "Escape" }); expect(screen.queryByRole("dialog")).toBeNull()
    fireEvent.click(btn); fireEvent.pointerDown(screen.getByRole("button", { name: "바깥" })); expect(screen.queryByRole("dialog")).toBeNull()
  })
})
