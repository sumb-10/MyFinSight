import { describe, expect, it } from "vitest"
import { fireEvent, render, screen, within } from "@testing-library/react"
import type { ReportDoc, ReportSummary } from "../../api/types"
import { allKpis, AllocationCard, ConditionRules, keyAlerts, KpiRow, krwFromNote, PastCard, VerdictCard } from "./Dashboard"

const alloc = (n: number, over: Partial<NonNullable<ReportSummary["allocation"]>> = {}): NonNullable<ReportSummary["allocation"]> => {
  const items = Array.from({ length: n }, (_, i) => ({ ticker: `T${i}`, name: `회사${i}`, sector: "IT", weight: (n - i) / 100, usd: 100 + i, krw: 140000 + i }))
  return { basis: "backtest", basis_ko: "선택안", items, cash_weight: 1 - items.reduce((s, x) => s + x.weight, 0), initial_amount_usd: 1000, fx_rate: 1400, ...over }
}
const vSummary = (over: Partial<ReportSummary["validation"]> = {}): ReportSummary["validation"] => ({ n_pass: 1, n_warn: 0, n_fail: 0, chosen_status: "pass", failed_rules_ko: [], ...over })
const sm = (over: Partial<ReportSummary> = {}): ReportSummary => ({
  verdict: { status: "recommended", label_ko: "추천: 동일비중", headline_ko: "동일비중 추천", chosen_portfolio_id: "eq", chosen_label_ko: "동일비중" },
  validation: vSummary(), kpis: [], allocation: null, mini_series: null, next_actions_ko: [], ...over,
})
const doc = (over: Partial<ReportDoc> = {}) => ({ header: { chosen_label_ko: "동일비중", chosen_note_ko: "", data_as_of: "2026-10-30", backtest_period: { start: "2025-10-30", end: "2026-10-30", as_of: "2025-10-30" }, chosen_portfolio_id: "eq" }, tracking: { eligible: true, reason_ko: null }, sections: [], kpis: [], datasets: { dates: [], series: {} }, parameters: {}, ...over }) as unknown as ReportDoc

describe("카드 2: 어떤 주식에 얼마를 투자하면 될까요?", () => {
  it("금액을 먼저 보여 주고, 상위 8개 뒤 나머지는 '전체 종목 보기'로 모두 볼 수 있으며 현금은 항상 보인다", () => {
    render(<AllocationCard a={alloc(11)} onMore={() => {}} />)
    const list = () => within(screen.getByRole("list", { name: "종목별 목표 배분액" }))
    expect(list().getByText("14만원")).toBeInTheDocument()  // 140,000원 → 읽기 쉬운 원화 (반올림 없이)
    expect(list().getByText("100.00 USD")).toBeInTheDocument()
    expect(list().queryByText("회사10")).toBeNull()
    expect(list().getByText("현금 (목표 비중)")).toBeInTheDocument()
    fireEvent.click(screen.getByRole("button", { name: /전체 종목 보기 \(11개 \+ 현금\)/ }))
    expect(list().getByText("회사10")).toBeInTheDocument()
    expect(list().getAllByRole("listitem")).toHaveLength(12)  // 11종목 + 현금
  })
  it("종목 줄은 모두 같은 칸(subgrid)을 쓰고, 막대는 가장 큰 비중을 기준으로 같은 비율로 그린다 (금액 글자 길이와 상관없음)", () => {
    const items = [{ ticker: "A", name: "가 회사", sector: "IT", weight: 0.4, usd: 4000, krw: 5_000_000 }, { ticker: "B", name: "나 회사", sector: "IT", weight: 0.2, usd: 2000, krw: 2_345_678 }]
    render(<AllocationCard a={alloc(2, { items, cash_weight: 0.1 })} onMore={() => {}} />)
    const rows = within(screen.getByRole("list", { name: "종목별 목표 배분액" })).getAllByRole("listitem")
    expect(rows.every((li) => li.className.includes("grid-cols-subgrid"))).toBe(true)
    expect(rows.map((li) => (li.querySelector("[data-bar]") as HTMLElement).style.width)).toEqual(["100%", "50%", "25%"])  // 40% · 20% · 현금 10%
    expect(rows.map((li) => li.children[1].textContent)).toEqual(["40.0%", "20.0%", "10.0%"])  // 비중은 이름 바로 옆 칸
  })
  it("없는 매수 수량·수수료·잔여 현금은 계산하지 않고 한 줄로만 알리며, 현금 금액도 지어내지 않는다", () => {
    render(<AllocationCard a={alloc(3)} doc={doc({ parameters: { backtest: { commission_bps: 5 } } })} onMore={() => {}} />)
    expect(screen.getByText(/종목별 매수 수량, 거래 수수료\(백테스트는 거래대금의 0.05%를 가정\), 매수 후 남는 현금은 이 분석에서 제공하지 않습니다/)).toBeInTheDocument()
    expect(screen.getByText("금액 미제공")).toBeInTheDocument()
    expect(screen.queryByText(/주$/)).toBeNull()
  })
  it("현재 구성 기준이면 선택 전략과 비중이 다를 수 있음을 알리고, 요청 투자금 원문을 기준금액으로 쓴다", () => {
    const d = doc({ sections: [{ id: "market", title_ko: "", blocks: [{ type: "table", title_ko: "요청 내용", columns: [], rows: [{ k: "투자금", v: "20,000,000원 → 백테스트 시작 14,044.85 USD" }] }] }] })
    render(<AllocationCard doc={d} a={alloc(1, { basis: "forward", basis_ko: "분석 기준일 구성" })} onMore={() => {}} />)
    expect(screen.getByText(/선택된 전략\(동일비중\)은 과거 성과로 고른 구성이라 비중이 다를 수 있습니다/)).toBeInTheDocument()
    expect(screen.getByText("20,000,000원")).toBeInTheDocument()
  })
  it("환율 1.00(USD 요청)이면 서버 '원화' 값을 원화로 보이지 않고 USD 로만 보여 준다", () => {
    render(<AllocationCard a={alloc(1, { fx_rate: 1, items: [{ ticker: "MU", name: "Micron", sector: "", weight: 1, usd: 1732066, krw: 1732066 }], cash_weight: 0 })} onMore={() => {}} />)
    expect(screen.getByText("1,732,066.00 USD")).toBeInTheDocument()
    expect(screen.queryByText(/원$/)).toBeNull()
  })
})

describe("카드 1·4: 결과와 조건", () => {
  it("추천 없음은 추천처럼 보이지 않고, 미충족·허용 초과·기간 안내를 기본 카드에 보여 준다", () => {
    const s = sm({ verdict: { status: "none_baseline", label_ko: "추천 없음 · 기준 포트폴리오 (동일비중)", headline_ko: "조건을 만족한 구성이 없습니다", chosen_portfolio_id: "eq", chosen_label_ko: "동일비중", period_note_ko: "백테스트 기간이 투자기간보다 짧습니다" },
      validation: vSummary({ n_pass: 0, n_fail: 1, failed_rules_ko: ["최소 종목 수"], rules_ko: [{ rule: "R1", name_ko: "최대낙폭", level: "flag", status: "flag", message_ko: "최대낙폭 30.7% vs 허용 20.0%" }] }) })
    render(<VerdictCard sm={s} doc={doc()} onMore={() => {}} />)
    expect(screen.getByText("추천 없음 · 기준 포트폴리오 (동일비중)")).toBeInTheDocument()
    const alerts = within(screen.getByRole("list", { name: "중요한 주의 사항" }))
    expect(alerts.getByText("허용 초과")).toBeInTheDocument(); expect(alerts.getByText(/최대낙폭 30.7% vs 허용 20.0%/)).toBeInTheDocument()
    expect(alerts.getByText("미충족")).toBeInTheDocument(); expect(alerts.getByText("최소 종목 수")).toBeInTheDocument()
    expect(alerts.getByText("기간 안내")).toBeInTheDocument()
    expect(keyAlerts(s)).toHaveLength(3)
  })
  it("조건 카드: 서버 규칙을 그대로, 상태는 글자로도, 허용 손실은 세 숫자 막대로", () => {
    render(<ConditionRules v={vSummary({ n_candidates: 9, rules_ko: [{ rule: "R1", name_ko: "최대낙폭", level: "flag", status: "flag", message_ko: "최대낙폭 10.9% vs 허용 8.0%" }, { rule: "R2", name_ko: "목표수익", level: "soft", status: "pass", message_ko: "CAGR 9% vs 목표 8%" }], r1: { mdd: 0.109, tolerance: 0.08, benchmark_mdd: 0.188, excess: 0.029, status: "flag" }, info_notes_ko: ["비교지수보다 낙폭이 큼"] })} />)
    expect(screen.getByText("허용 손실 vs 과거 최대 하락폭")).toBeInTheDocument()
    expect(screen.getByText("허용 초과")).toBeInTheDocument(); expect(screen.getByText("충족")).toBeInTheDocument()
    expect(screen.getByLabelText("최대낙폭 비교")).toHaveTextContent("-10.90%"); expect(screen.getByLabelText("최대낙폭 비교")).toHaveTextContent("8.0%")
    expect(screen.getByText("비교지수보다 낙폭이 큼")).toBeInTheDocument()
    expect(screen.getByText(/9개 투자 구성안을/)).toBeInTheDocument()
    expect(screen.queryByText(/추천 1개/)).toBeNull()
  })
  it("규칙 목록이 없는 예전 리포트는 개수와 미충족 이름만, 검증 결과가 아예 없으면 판단하지 않는다", () => {
    const { unmount } = render(<ConditionRules v={vSummary({ n_pass: 3, n_warn: 2, n_fail: 5, failed_rules_ko: ["최대낙폭 한도"] })} />)
    expect(screen.getByText("미충족 5")).toBeInTheDocument(); expect(screen.getByText("최대낙폭 한도")).toBeInTheDocument()
    unmount()
    render(<ConditionRules v={vSummary({ n_pass: 0 })} />)
    expect(screen.getByText(/조건별 검증 결과가 없습니다/)).toBeInTheDocument()
  })
})

describe("카드 3과 KPI 전체", () => {
  // 서버 KPI 그대로: 짧은 창은 기간 수익률·기간 차이, 긴 창은 CAGR·CAGR 차이 (report_blocks.kpis)
  const shortKpis = (excess: number | null = 0.6478) => [
    { id: "cagr", label_ko: "기간 수익률 (251거래일)", value: 0.77, format: "pct" as const, note_ko: "연 환산 +77.4% 는 1년 미만 창이라 참고만", benchmark_value: 0.1223, benchmark_label_ko: "SPY 매수보유 (동일 적립)" },
    { id: "excess", label_ko: "비교지수(SPY) 대비 (기간)", value: excess, format: "pp" as const, note_ko: "같은 기간 누적 수익률 차이" },
    { id: "mdd", label_ko: "최대낙폭 (MDD)", value: -0.3, format: "pct" as const, benchmark_value: -0.089, benchmark_label_ko: "SPY 매수보유 (동일 적립)" },
  ]
  const shortPeriod = { start: "2025-10-30", end: "2026-10-30", trading_days: 252, window_days: 251, annualized_reliable: false } as ReportSummary["period"]
  const params = { backtest: { min_annualize_days: 400, trading_days: 250 } }  // 기준은 설정값에서 읽는다 (378·1.5 를 박아 두지 않는다)
  const compare = () => screen.getByRole("region", { name: /비교$/ })

  it("짧은 창: 제목은 「전체 기간 수익률」, 두 값은 같은 모양, 차이는 서버 excess 로 바로 아래, 연 환산은 도움말로만", () => {
    const s = sm({ kpis: shortKpis(), period: shortPeriod })
    render(<PastCard sm={s} doc={doc({ summary: s, parameters: params })} onMore={() => {}} />)
    const c = compare()
    expect(within(c).getByRole("heading", { name: /전체 기간 수익률/ })).toBeInTheDocument()
    expect(within(c).queryByText(/과거 투자 성과 비교/)).toBeNull()
    expect(within(c).queryByText(/CAGR/)).toBeNull()  // 기간 수익률을 CAGR 로 부르지 않는다
    expect(within(c).getByText(/251거래일 기준 · 1년 평균이 아닌 기간 전체의 수익률/)).toBeInTheDocument()
    const mine = within(c).getByText("선택 전략").closest("div")!, bench = within(c).getByText("SPY", { selector: "dt span span" }).closest("div")!
    expect(bench.querySelector("dt")).toHaveTextContent("비교지수 · SPY")
    expect(within(mine).getByText("+77.00%").className).toBe(within(bench).getByText("+12.23%").className)  // 같은 크기·굵기
    expect(within(c).getByText("전체 기간 수익률이 SPY보다 64.78%p 높았습니다")).toBeInTheDocument()  // 어떤 수익률의 차이인지 문장에 밝힌다
    expect(within(c).getByText(/같은 기간, 같은 투자금 납입 조건\(동일 적립\)으로 SPY를 사서 계속 보유했다고 가정해 비교했습니다/)).toBeInTheDocument()
    expect(within(c).getByText(/^분석 기간이 짧아, 위 비교에는 전체 기간 수익률을 사용했습니다\. 연 환산 수익률은 참고용입니다\./)).toBeInTheDocument()
    expect(within(c).queryByText(/\+77\.4%|378|1년 미만/)).toBeNull()  // 연 환산 값·최소 기준은 기본 화면에 늘어놓지 않는다
    expect(screen.queryByText("SPY 대비 전체 기간 수익률 차이")).toBeNull()  // 별도 차이 행과 중복하지 않는다
    expect(screen.getByText("최대낙폭(MDD)")).toBeInTheDocument()
    fireEvent.click(within(c).getByRole("button", { name: "연 환산 수익률 안내 설명 보기" }))
    const tip = screen.getByRole("dialog", { name: "연 환산 수익률 안내 설명" })
    expect(tip).toHaveTextContent("+77.4%"); expect(tip).toHaveTextContent("251거래일"); expect(tip).toHaveTextContent("복리로 1년 길이")
    expect(tip).toHaveTextContent("400거래일(약 1.6년)보다 짧으면 목표 수익률·변동성 조건 검사를 판정 대신 참고로만"); expect(tip).toHaveTextContent("믿을 수 있다는 뜻은 아닙니다")
    fireEvent.click(screen.getByRole("button", { name: "설명 닫기" }))
    fireEvent.click(within(c).getByRole("button", { name: "비교지수 · SPY 설명 보기" }))
    expect(screen.getByRole("dialog", { name: "비교지수 · SPY 설명" })).toHaveTextContent("미국 S&P 500 지수를 따라가는 ETF")
  })
  it("긴 창: 제목은 「연평균 수익률(CAGR)」, 차이도 CAGR 차이로 표시하고 짧은 창 안내는 없다", () => {
    const s = sm({ kpis: [
      { id: "cagr", label_ko: "연평균 수익률 (CAGR)", value: 0.47, format: "pct", note_ko: "백테스트 기간 기준 연 환산", benchmark_value: 0.2378, benchmark_label_ko: "SPY 매수보유 (동일 적립)" },
      { id: "excess", label_ko: "비교지수(SPY) 대비", value: 0.2327, format: "pp", note_ko: "같은 기간 CAGR 차이" },
    ], period: { start: "2023-10-28", end: "2026-10-28", trading_days: 775, annualized_reliable: true } as ReportSummary["period"] })
    render(<PastCard sm={s} doc={doc({ summary: s, parameters: params })} onMore={() => {}} />)
    const c = compare()
    expect(within(c).getByRole("heading", { name: /연평균 수익률\(CAGR\)/ })).toBeInTheDocument()
    expect(within(c).getByText("백테스트 기간 기준 연 환산")).toBeInTheDocument()
    expect(within(c).getByText("연평균 수익률(CAGR)이 SPY보다 23.27%p 높았습니다")).toBeInTheDocument()
    expect(screen.queryByText(/분석 기간이 짧아/)).toBeNull()
    expect(screen.queryByRole("button", { name: /연 환산 수익률 안내/ })).toBeNull()
  })
  it("차이가 음수면 「낮았습니다」, 0 이면 「차이가 없었습니다」, 값이 없으면 문장을 만들지 않는다", () => {
    const one = (v: number | null) => { const s = sm({ kpis: shortKpis(v), period: shortPeriod }); return render(<PastCard sm={s} doc={doc({ summary: s })} onMore={() => {}} />) }
    let r = one(-0.031); expect(screen.getByText("전체 기간 수익률이 SPY보다 3.10%p 낮았습니다")).toBeInTheDocument(); r.unmount()
    r = one(0.00001); expect(screen.getByText("전체 기간 수익률이 SPY와 차이가 없었습니다 (0.00%p)")).toBeInTheDocument(); r.unmount()
    one(null); expect(screen.queryByText(/높았습니다|낮았습니다|차이가 없었습니다/)).toBeNull()
    expect(screen.getByText(/같은 기간, 같은 투자금 납입 조건/)).toBeInTheDocument()  // 비교 조건 안내는 남는다
  })
  it("비교지수 값이 없으면 비교지수 칸·차이 문장을 만들지 않고, 서버 차이 값은 기존 행으로 남긴다", () => {
    const s = sm({ kpis: [{ id: "cagr", label_ko: "연평균 수익률 (CAGR)", value: 0.12, format: "pct" }, { id: "excess", label_ko: "비교지수(SPY) 대비", value: 0.02, format: "pp" }] })
    render(<PastCard sm={s} doc={doc({ summary: s })} onMore={() => {}} />)
    const c = compare()
    expect(within(c).getByText("+12.00%")).toBeInTheDocument()
    expect(within(c).queryByText(/비교지수 ·/)).toBeNull(); expect(screen.queryByText(/높았습니다/)).toBeNull()
    expect(screen.getByText("SPY 대비 연평균 수익률(CAGR) 차이")).toBeInTheDocument(); expect(screen.getByText("+2.00%p")).toBeInTheDocument()
  })
  it("수익률 KPI 가 없으면 비교 영역 없이 나머지 지표와 주의 문구만", () => {
    const s = sm({ kpis: [{ id: "mdd", label_ko: "최대낙폭 (MDD)", value: -0.3, format: "pct" }] })
    render(<PastCard sm={s} doc={doc({ summary: s })} onMore={() => {}} />)
    expect(screen.queryByRole("region", { name: /비교$/ })).toBeNull()
    expect(screen.getByText("-30.00%")).toBeInTheDocument()
    expect(screen.getByText(/과거 성과는 미래 수익을 보장하지 않습니다/)).toBeInTheDocument()
  })
  it("요약에서 빠진 KPI(뉴스 뷰 적중률 등)도 전체 목록에 남는다", () => {
    const d = doc({ kpis: [{ id: "cagr", label_ko: "CAGR", value: 0.1, format: "pct" }, { id: "view_hit", label_ko: "뉴스 뷰 적중률", value: null, format: "pct", note_ko: "이 포트폴리오에는 뷰가 없습니다" }], summary: sm({ kpis: [{ id: "cagr", label_ko: "CAGR", value: 0.1, format: "pct", benchmark_value: 0.05, benchmark_label_ko: "SPY" }] }) })
    render(<KpiRow kpis={allKpis(d)} />)
    expect(screen.getByText("뉴스 뷰 적중률")).toBeInTheDocument(); expect(screen.getByText("이 포트폴리오에는 뷰가 없습니다")).toBeInTheDocument()
    expect(screen.getByText("SPY +5.00%")).toBeInTheDocument()
  })
  it("최종 평가금액은 서버가 준 원화를 쓰고, 원화가 없으면 USD 를 그대로 둔다 (환산하지 않는다)", () => {
    expect(krwFromNote("약 29,473,358원 · 투입 원금 18,258 USD")).toEqual({ krw: 29473358, rest: "투입 원금 18,258 USD" })
    expect(krwFromNote("투입 원금 18,258 USD")).toBeNull()
    const { unmount } = render(<KpiRow kpis={[{ id: "final_value", label_ko: "최종 평가금액", value: 22028.25, format: "usd", note_ko: "약 29,473,358원 · 투입 원금 18,258 USD" }]} />)
    expect(screen.getByText("약 2,947만 3,358원")).toBeInTheDocument()
    expect(screen.getByText(/22,028.25 USD · 분석 기준일 환율 기준/)).toBeInTheDocument()
    unmount()
    render(<KpiRow kpis={[{ id: "final_value", label_ko: "최종 평가금액", value: 100, format: "usd", note_ko: "투입 원금 90 USD" }]} />)
    expect(screen.getByText("100.00 USD")).toBeInTheDocument()
    expect(screen.queryByText(/원$/)).toBeNull()
  })
})
