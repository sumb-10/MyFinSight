import { afterEach, beforeAll, describe, expect, it, vi } from "vitest"
import { fireEvent, render, screen, waitFor, within } from "@testing-library/react"
import { Providers, ServiceContext } from "../../../app/providers"
import type { AnalysisService } from "../../../api/service"
import type { ReportDoc, ReportSummary } from "../../../api/types"
import { MockService } from "../../../mocks/services/MockService"
import { ReportDetail } from "../ReportDetail"
import { BeginnerReport } from "./BeginnerReport"
import { benchShort, easyModel, fromMillion, pctAbs, pctSigned, periodText, roughWon } from "./easyData"

// 왕초보용 리포트 화면 (2026-11-28): 원래 리포트와 같은 서버 값을 쉬운 말로 보여 주는지, 오른쪽 위 토글로 오가는지, 처음 화면이 투자조건 설정을 따르는지.

beforeAll(() => {
  Element.prototype.scrollIntoView = vi.fn()
  window.scrollTo = vi.fn() as unknown as typeof window.scrollTo
  globalThis.ResizeObserver ??= class { observe() {} unobserve() {} disconnect() {} } as unknown as typeof ResizeObserver
})
afterEach(() => { window.history.replaceState(null, "", "/"); window.localStorage.clear() })

const DATES = ["2023-10-30", "2024-04-29", "2024-10-08", "2025-10-30", "2026-10-30"]
const summary = (over: Partial<ReportSummary> = {}): ReportSummary => ({
  verdict: { status: "recommended_warn", label_ko: "추천(주의): 동일비중", headline_ko: "동일비중 추천", chosen_portfolio_id: "equal_weight", chosen_label_ko: "동일비중", cautions_ko: ["종목 수 부족 (2/5개)"], cautions_plain: [{ key: "종목 수 부족 (2/5개)", text: "담은 회사가 2개라 정한 최소 5개보다 적습니다 [fin:US-AAA:roe_ttm:2026-10-29]." }] },
  validation: { n_pass: 0, n_warn: 1, n_fail: 0, chosen_status: "warn", failed_rules_ko: [], rules_ko: [{ rule: "R1", name_ko: "최대낙폭", level: "flag", status: "pass", message_ko: "최대낙폭 27.2% vs 허용 30.0%" }], r1: { mdd: 0.272, tolerance: 0.3, benchmark_mdd: 0.171, excess: 0, status: "pass" } },
  kpis: [{ id: "cagr", label_ko: "연평균 수익률 (CAGR)", value: 0.37, format: "pct", benchmark_value: 0.16, benchmark_label_ko: "SPY 매수보유 (동일 적립)" }, { id: "mdd", label_ko: "최대낙폭 (MDD)", value: -0.272, format: "pct", benchmark_value: -0.171 }, { id: "sharpe", label_ko: "Sharpe 비율", value: 1.4, format: "ratio" }],
  allocation: { basis: "forward", basis_ko: "분석 기준일 구성", items: [{ ticker: "BBB", name: "BBB Inc.", sector: "IT", weight: 0.3, usd: 300, krw: 420000 }, { ticker: "AAA", name: "AAA Inc.", sector: "IT", weight: 0.6, usd: 600, krw: 840000 }], cash_weight: 0.1, initial_amount_usd: 1000, fx_rate: 1400 },
  mini_series: { dataset: "index", ids: ["equal_weight", "benchmark_SPY"] }, period: { start: "2023-10-30", end: "2026-10-30" },
  next_actions_ko: ["종목 수를 늘려 보세요 [calc:x].", "walk-forward 구성과 리밸런싱 방식의 차이를 비교해 보세요."], ...over,
})
const doc = (over: Partial<ReportDoc> = {}): ReportDoc => ({
  request_id: "req_1", run_id: "run_1", stage: "", generated_at: "2026-11-01", source: "",
  header: { title_ko: "반도체 · 퀄리티 전략", subtitle_ko: "반도체 기업 가운데 이익을 잘 내는 회사를 골랐습니다.", summary_ko: "반도체에 투자하고 싶다는 요청입니다.", created_at: "2026-11-01", selection_as_of: "2026-10-30", backtest_period: { start: "2023-10-30", end: "2026-10-30", as_of: "2023-10-30" }, data_as_of: "2026-10-30", chosen_portfolio_id: "equal_weight", chosen_label_ko: "동일비중", chosen_note_ko: "", disclaimer_ko: "면책 문구" },
  kpis: [], nav: [{ id: "companies", title_ko: "기업별 투자 근거" }],
  sections: [{ id: "performance", title_ko: "과거 성과와 해석", blocks: [
    { type: "table", title_ko: "연도별 수익률", columns: [{ key: "name", label_ko: "구분" }, { key: "2024", label_ko: "2024", format: "pct" }, { key: "2025", label_ko: "2025", format: "pct" }, { key: "2026", label_ko: "2026", format: "pct" }], rows: [{ name: "동일비중", "2024": 0.5, "2025": -0.1, "2026": 0.33 }, { name: "SPY 매수보유 (동일 적립)", "2024": 0.2, "2025": 0.1, "2026": 0.12 }], note_ko: "첫해와 마지막 해는 일부 기간입니다." },
    { type: "bar", title_ko: "종목별 수익 기여 (기간 전체)", format: "pp", items: [{ label: "AAA", value: 1.2 }, { label: "BBB", value: 0.5 }, { label: "ZZZ", value: -0.04 }, { label: "거래비용 등", value: -0.002 }] },
  ] }, { id: "companies", title_ko: "기업별 투자 근거", blocks: [
    { type: "funnel", items: [{ label_ko: "투자 가능 종목 (SP500)", count: 518 }, { label_ko: "테마 관련 종목 (산업 분류로 45개)", count: 49 }, { label_ko: "테마 해당 판정 (분석 모델, 신뢰도 ≥ 0.5)", count: 12 }, { label_ko: "최종 선정 (2026-10-30)", count: 2 }] },
    { type: "companies", title_ko: "선정 종목", metric: "roe_ttm", metric_ko: "퀄리티", direction: "desc", as_of_now: "2026-10-30", as_of_bt: "2023-10-30", portfolio_id: "equal_weight", items: [
      { ticker: "AAA", name: "AAA Inc.", market: "US", sector: "IT", sub_industry: "반도체", summary: "AAA makes chips.", theme_reason_ko: "필수 포함 종목 · AI 반도체를 만듭니다", theme_confidence: 0.9, weight: 0.6, in_selection_now: true, rank_now: 1, metric_now: 0.3, in_backtest: true, rank_bt: 1, metric_bt: 0.2, fact_id: null, rationale_ko: [], evidence_ids: [], n_news: 0, n_disclosures: 0 },
      { ticker: "BBB", name: "BBB Inc.", market: "US", sector: "IT", sub_industry: "반도체 장비", summary: "BBB makes tools.", theme_reason_ko: "", theme_confidence: 0.9, weight: 0.3, in_selection_now: true, rank_now: 2, metric_now: 0.2, in_backtest: true, rank_bt: 2, metric_bt: 0.1, fact_id: null, rationale_ko: [], evidence_ids: [], n_news: 0, n_disclosures: 0 },
    ] },
  ] }],
  datasets: { dates: DATES, series: {
    equal_weight: { label_ko: "동일비중", kind: "template", index: [100, 150, 109.2, 200, 266], drawdown: [0, 0, -0.272, 0, 0], value_usd: [1000, 1700, 1400, 2600, 3500] },
    net_invested: { label_ko: "투입 원금(누적)", kind: "reference", value_usd: [1000, 1100, 1200, 1300, 1400] },
    benchmark_SPY: { label_ko: "SPY 매수보유 (동일 적립)", kind: "benchmark", index: [100, 120, 110, 140, 157.2], drawdown: [0, 0, -0.083, 0, 0] },
  } },
  assessment: { intent_fit: null, logic_consistency: null, comments_ko: [] }, evidence: [], execution: [], tracking: { eligible: true, reason_ko: null }, sources: [], parameters: {}, warnings: [],
  doc_version: 2, summary: summary(), evidence_summary: { total: 0, cited: 0, by_kind: {} }, ...over,
})
const service = (d: ReportDoc) => ({ getReport: vi.fn(async () => d), getReportComparison: vi.fn(async () => { throw new Error("none") }), getRequest: vi.fn(async () => ({ idea: "", questions: [], revision: null, conditions: [], confirmation: { rows: [] } })), listReports: vi.fn(async () => []) }) as unknown as AnalysisService
const show = (d: ReportDoc, props: { sec?: string; readOnly?: boolean } = {}) => render(<ServiceContext.Provider value={service(d)}><ReportDetail reportId="run_1" {...props} /></ServiceContext.Provider>)
const radio = (name: string) => screen.findByRole("radio", { name }, { timeout: 5000 })

describe("왕초보용 화면 · 값 꺼내기", () => {
  it("기간·금액·수익률을 쉬운 글자로 쓴다", () => {
    expect([periodText("2023-10-30", "2026-10-30"), periodText("2023-01-01", "2025-07-01"), periodText("2026-01-01", "2026-09-01"), periodText("2026-01-01", "2025-01-01")]).toEqual(["3년", "2년 6개월", "8개월", ""])
    expect([roughWon(2_660_000), roughWon(728_000), roughWon(10_000_000), roughWon(150_000_000), roughWon(4_300)]).toEqual(["266만원", "72만 8,000원", "1,000만원", "1억 5,000만원", "4,300원"])
    expect([pctAbs(0.4213), pctSigned(1.66), pctSigned(-0.19071), pctSigned(0), pctAbs(12.5)]).toEqual(["42.1%", "+166.0%", "−19.1%", "0.0%", "1,250%"])
    expect([fromMillion(1.66), fromMillion(-0.272)]).toEqual(["266만원", "72만 8,000원"])
    expect([benchShort("benchmark_SPY"), benchShort("benchmark_069500.KS"), benchShort("benchmark_XYZ")]).toEqual(["S&P 500", "코스피 200", "XYZ"])
  })
  it("수익률·낙폭·비중은 서버 값 그대로이고, 내 전략이 첫 계열이다", () => {
    const m = easyModel(doc())!
    expect(m.series.map((s) => [s.name, s.mine])).toEqual([["내 전략", true], ["S&P 500", false]])
    expect(m.total).toBeCloseTo(1.66)                    // 그래프 계열의 마지막 값 (266 / 100 − 1)
    expect(m.bench).toEqual({ name: "S&P 500", total: expect.closeTo(0.572) })
    expect(m.periodText).toBe("3년")
    expect(m.yearly).toBe(0.37)                          // 서버 연평균 값
    expect(m.drop).toMatchObject({ mdd: 0.272, benchMdd: 0.171, benchName: "S&P 500", tolerance: 0.3, over: false, peakIdx: 1, troughIdx: 2 })
    expect(m.holdings.map((h) => [h.name, h.about, h.amount, h.weight])).toEqual([["AAA Inc.", "AI 반도체를 만듭니다", "84만원", 0.6], ["BBB Inc.", "반도체 장비", "42만원", 0.3]])  // 비중 큰 순, 「필수 포함 종목 ·」은 뗀다
    expect(m.cash).toEqual({ weight: 0.1, amount: "14만원" })
    expect(m.baseText).toBe("140만원")
    expect(m.steps).toEqual([{ label: "살 수 있는 회사", count: 518 }, { label: "주제에 맞는 회사", count: 12 }, { label: "담은 회사", count: 2 }])
    expect(m.alerts).toEqual(["담은 회사가 2개라 정한 최소 5개보다 적습니다."])   // 서버의 쉬운 문장, 근거 번호는 뗀다
    expect(m.next).toEqual(["종목 수를 늘려 보세요."])   // 어려운 말이 든 항목은 뺀다
    expect(m.how).toBe("반도체 기업 가운데 이익을 잘 내는 회사를 골랐습니다.")
    expect(m.allClear).toBe(false)
  })
  it("넣은 돈·해마다의 수익·분야 비중·수익 기여도 서버 값에서 꺼낸다", () => {
    const m = easyModel(doc())!
    expect(m.money).toMatchObject({ invested: 1_960_000, final: 4_900_000, monthly: true, won: true })   // 서버 계열(달러) × 분석한 날 환율 1,400원
    expect(m.money!.series.map((s) => [s.name, s.last])).toEqual([["불어난 돈", 4_900_000], ["넣은 돈", 1_960_000]])
    expect([m.money!.text(4_900_000), m.money!.text(1_960_000)]).toEqual(["490만원", "196만원"])
    expect(m.byYear).toEqual({ years: ["2024", "2025", "2026"], mine: [0.5, -0.1, 0.33], bench: [0.2, 0.1, 0.12], benchName: "S&P 500", note: "첫해와 마지막 해는 일부 기간입니다." })
    expect(m.sectors).toEqual([{ name: "IT", weight: expect.closeTo(0.9) }])
    expect(m.contrib).toEqual({ top: [{ name: "AAA Inc.", value: 1.2 }, { name: "BBB Inc.", value: 0.5 }], worst: { name: "ZZZ", value: -0.04 } })   // 거래비용은 빼고, 이름을 아는 회사는 이름으로
    const usd = doc(); usd.summary!.allocation!.fx_rate = 1
    expect(easyModel(usd)!.money).toMatchObject({ invested: 1400, final: 3500, won: false })
    expect(easyModel(usd)!.money!.text(3500)).toBe("3,500달러")
  })
  it("짧은 기간이면 1년 평균을 쓰지 않고, 서버가 남긴 고점·저점 날짜가 있으면 그 날짜를 쓴다. 허용보다 크게 떨어졌으면 그렇게 알린다", () => {
    const d = doc({ summary: summary({ kpis: [{ id: "cagr", label_ko: "기간 수익률 (8개월)", value: 0.2, format: "pct" }, { id: "mdd", label_ko: "최대낙폭 (MDD)", value: -0.35, format: "pct", benchmark_value: -0.1 }], validation: { n_pass: 0, n_warn: 0, n_fail: 0, chosen_status: "warn", failed_rules_ko: [], r1: { mdd: 0.35, tolerance: 0.3, benchmark_mdd: 0.1, excess: 0.05, status: "flag" } } }) })
    d.datasets.sampling = { method: "stride", stride: 2, full_points: 10, points: 5, pinned: ["2024-10-08", "2025-10-30"] }
    const m = easyModel(d)!
    expect(m.yearly).toBeNull()
    expect(m.drop).toMatchObject({ mdd: 0.35, over: true, peakIdx: 2, troughIdx: 3 })
  })
  it("쉬운 문장이 없는 옛 리포트는 위 구획이 이미 말한 전문 용어 줄(비교지수 대비·최대낙폭)을 빼고, 나머지 주의는 그대로 둔다", () => {
    const old = summary({ validation: { n_pass: 0, n_warn: 3, n_fail: 0, chosen_status: "warn", failed_rules_ko: [], r1: { mdd: 0.35, tolerance: 0.3, benchmark_mdd: 0.171, excess: 0.05, status: "flag" },
      rules_ko: [{ rule: "R1", name_ko: "최대낙폭", level: "flag", status: "flag", message_ko: "최대낙폭 35.0% vs 허용 30.0%" }, { rule: "R3", name_ko: "비교지수 대비", level: "warn", status: "warn", message_ko: "SPY 대비 초과 CAGR -4.6%p" }, { rule: "R2", name_ko: "목표수익", level: "warn", status: "warn", message_ko: "연 10.0% 목표에 못 미쳤습니다" }] } })
    old.verdict = { ...old.verdict, cautions_ko: [], cautions_plain: undefined }
    expect(easyModel(doc({ summary: old }))!.alerts).toEqual(["목표수익: 연 10.0% 목표에 못 미쳤습니다"])
    const fresh = { ...old, validation: { ...old.validation, rules_plain_ko: { R1: "가장 크게 떨어진 폭이 35.0%로, 견딜 수 있다고 한 30.0%보다 컸습니다.", R3: "같은 기간 S&P 500보다 덜 올랐습니다.", R2: "목표로 한 수익에 못 미쳤습니다." } } }
    expect(easyModel(doc({ summary: fresh }))!.alerts).toEqual(["가장 크게 떨어진 폭이 35.0%로, 견딜 수 있다고 한 30.0%보다 컸습니다.", "같은 기간 S&P 500보다 덜 올랐습니다.", "목표로 한 수익에 못 미쳤습니다."])
  })
  it("주의할 점이 없고 서버 판정이 충족이면 「모두 지켰어요」, 요약이 없는 문서는 만들지 않는다", () => {
    const ok = summary({ validation: { n_pass: 4, n_warn: 0, n_fail: 0, chosen_status: "pass", failed_rules_ko: [], r1: { mdd: 0.272, tolerance: 0.3, benchmark_mdd: 0.171, excess: 0, status: "pass" } } })
    ok.verdict = { ...ok.verdict, cautions_ko: [], cautions_plain: [] }
    expect(easyModel(doc({ summary: ok }))).toMatchObject({ alerts: [], allClear: true })
    expect(easyModel(doc({ summary: null }))).toBeNull()
  })
})

describe("왕초보용 화면 · 구획", () => {
  it("큰 제목과 숫자로 열 구획을 보여 주고, 어려운 용어는 쓰지 않는다", () => {
    const { container } = render(<BeginnerReport doc={doc()} canPaper onStartPaper={() => {}} onFull={() => {}} />)
    expect(screen.getAllByRole("heading", { level: 2 }).map((h) => h.textContent)).toEqual([
      "내 전략은 3년 동안S&P 500보다 더 올랐어요.", "넣은 돈 196만원이490만원이 됐어요.", "3년 가운데1년은 떨어졌어요.", "가장 크게 떨어졌을 때는27.2%까지 내려갔어요.", "140만원을2개 회사에 나눠 담아요.",
      "돈의 90%가IT 회사에 몰려 있어요.", "AAA Inc. 주식이가장 많이 벌어 줬어요.", "이런 순서로회사를 골랐어요.", "미리 알아둘 점이1가지 있어요.", "실제 돈을 넣기 전에모의투자로 연습할 수 있어요.",
    ])
    expect(screen.getByRole("img", { name: "넣은 돈과 불어난 돈 그래프: 넣은 돈 196만원, 불어난 돈 490만원" })).toBeInTheDocument()
    expect(screen.getByText("처음 넣은 돈에 매달 넣은 돈을 더한 금액과 견줬어요. 원화 금액은 분석한 날의 환율로 바꾼 값이에요.")).toBeInTheDocument()
    expect(screen.getByRole("img", { name: "해마다의 수익률 막대: 2024년 내 전략 +50.0%, S&P 500 +20.0% / 2025년 내 전략 −10.0%, S&P 500 +10.0% / 2026년 내 전략 +33.0%, S&P 500 +12.0%" })).toBeInTheDocument()
    expect(within(screen.getByRole("list", { name: "분야별 비중" })).getAllByRole("listitem").map((li) => li.textContent)).toEqual(["IT90%", "현금10%"])
    expect(within(screen.getByRole("list", { name: "수익에 많이 보탠 회사" })).getAllByRole("listitem").map((li) => li.textContent)).toEqual(["AAA Inc.+120.0%", "BBB Inc.+50.0%", "ZZZ−4.0%"])
    expect(screen.getByText("위 2개 회사가 +170.0%를 보탰어요. ZZZ 주식은 수익을 4.0% 깎았어요. 수익의 절반 넘게가 한 회사에서 나왔어요.")).toBeInTheDocument()
    const stat = (name: string) => screen.getAllByText(name).map((dt) => dt.nextElementSibling?.textContent)
    expect(stat("내 전략은")).toEqual(["+166.0%", "−27.2%"])
    expect(stat("S&P 500은")).toEqual(["+57.2%", "−17.1%"])
    expect(stat("100만원을 넣었다면")).toEqual(["266만원"])
    expect(stat("내가 견딜 수 있다고 한 폭은")).toEqual(["−30.0%"])
    expect(screen.getByText(/100만원이었던 돈이 한때 72만 8,000원까지 줄었던 셈이에요\. 내가 견딜 수 있다고 답한 범위 안이었어요\./)).toBeInTheDocument()
    expect(screen.getByText(/1년에 평균 37\.0%씩 오른 셈이에요/)).toBeInTheDocument()
    const rows = within(screen.getByRole("list", { name: "회사별 투자 금액" })).getAllByRole("listitem").map((li) => li.textContent)
    expect(rows).toEqual(["AAA Inc.AI 반도체를 만듭니다84만원60.0%", "BBB Inc.반도체 장비42만원30.0%", "현금주식을 사지 않고 남겨 두는 돈14만원10.0%"])
    expect(screen.getByRole("img", { name: "누적 수익률 그래프: 내 전략 +166.0%, S&P 500 +57.2%" })).toBeInTheDocument()
    expect(screen.getByRole("img", { name: /가장 크게 떨어진 구간 그래프: 2024-04-29 부터 2024-10-08 까지 27\.2% 하락/ })).toBeInTheDocument()
    expect(container.textContent).not.toMatch(/CAGR|Sharpe|최대낙폭|MDD|Black-Litterman|walk-forward|리밸런싱|%p|\[fin:|\[calc:/)
  })
  it("손실이 났으면 떨어졌다고 쓰고, 비교 대상보다 덜 올랐으면 덜 올랐다고 쓴다. 모의투자를 못 하면 원래 리포트로 안내한다", () => {
    const down = doc()
    down.datasets.series.equal_weight.index = [100, 90, 60, 70, 81]
    const a = render(<BeginnerReport doc={down} canPaper={false} onStartPaper={() => {}} onFull={() => {}} />)
    expect(screen.getAllByRole("heading", { level: 2 })[0].textContent).toBe("내 전략은 3년 동안19.0% 떨어졌어요.")
    down.datasets.series.equal_weight.value_usd = [1000, 900, 700, 800, 1100]   // 넣은 돈 1,400달러보다 적게 남았다
    a.rerender(<BeginnerReport doc={{ ...down }} canPaper={false} onStartPaper={() => {}} onFull={() => {}} />)
    expect(screen.getAllByRole("heading", { level: 2 })[1].textContent).toBe("넣은 돈 196만원이154만원으로 줄었어요.")
    expect(screen.getByText("100만원을 넣었다면").nextElementSibling?.textContent).toBe("81만원")
    expect(screen.getByRole("heading", { level: 2, name: /더 자세한 내용은\s*원래 리포트에 있어요/ })).toBeInTheDocument()
    expect(screen.queryByRole("button", { name: /모의투자 시작/ })).toBeNull()
    a.unmount()
    const less = doc()
    less.datasets.series.equal_weight.index = [100, 110, 100, 120, 130]
    render(<BeginnerReport doc={less} canPaper onStartPaper={() => {}} onFull={() => {}} />)
    expect(screen.getAllByRole("heading", { level: 2 })[0].textContent).toBe("내 전략은 3년 동안S&P 500보다 덜 올랐어요.")
  })
})

describe("리포트 화면 · 왕초보용 ↔ 원래 리포트", () => {
  it("오른쪽 위 토글로 오간다. 투자조건 설정이 없으면 원래 리포트로 시작한다", async () => {
    show(doc())
    expect(await radio("원래 리포트")).toHaveAttribute("aria-checked", "true")
    expect(screen.getByRole("heading", { level: 2, name: "자세한 분석" })).toBeInTheDocument()
    fireEvent.click(await radio("왕초보용"))
    expect(await screen.findByRole("heading", { level: 2, name: /내 전략은 3년 동안/ })).toBeInTheDocument()
    expect(screen.queryByRole("heading", { level: 2, name: "자세한 분석" })).toBeNull()
    expect(screen.getByRole("heading", { level: 1, name: "반도체 · 퀄리티 전략" })).toBeInTheDocument()   // 머리말과 버튼은 그대로
    expect(screen.getAllByRole("button", { name: /모의투자 시작/ }).length).toBe(2)
    expect(screen.getByText("면책 문구")).toBeInTheDocument()
    fireEvent.click(screen.getByRole("button", { name: "원래 리포트 보기" }))
    expect(await screen.findByRole("heading", { level: 2, name: "자세한 분석" })).toBeInTheDocument()
    expect(await radio("원래 리포트")).toHaveAttribute("aria-checked", "true")
  })
  it("둘러보기(읽기 전용)와 요약이 없는 문서에는 토글이 없다", async () => {
    const a = show(doc(), { readOnly: true })
    expect(await screen.findByRole("heading", { level: 2, name: "자세한 분석" })).toBeInTheDocument()
    expect(screen.queryByRole("radiogroup", { name: "리포트 화면" })).toBeNull()
    a.unmount()
  })
  it("투자조건에서 왕초보용 화면을 켰으면 왕초보용으로 시작하고, 주소가 섹션을 가리키면 원래 리포트로 연다", async () => {
    const s = new MockService({ latencyMs: 0, persist: false })
    const { version: _v, created_at: _c, ...base } = await s.getProfileVersion(1)
    await s.saveProfile({ ...base, beginner_view: true, note: "왕초보용 화면 켬" })
    window.history.replaceState(null, "", "/?mock=1")
    const first = render(<Providers service={s}><ReportDetail reportId="mock_rep_normal" /></Providers>)
    expect(await radio("왕초보용")).toHaveAttribute("aria-checked", "true")
    expect(screen.getByRole("heading", { level: 2, name: /내 전략은/ })).toBeInTheDocument()
    fireEvent.click(await radio("원래 리포트"))   // 토글은 이 화면만 바꾸고 투자조건 설정은 그대로
    await waitFor(() => expect(screen.getByRole("heading", { level: 2, name: "자세한 분석" })).toBeInTheDocument())
    expect((await s.getProfile())?.profile.beginner_view).toBe(true)
    first.unmount()
    render(<Providers service={s}><ReportDetail reportId="mock_rep_normal" sec="performance" /></Providers>)
    expect(await radio("원래 리포트")).toHaveAttribute("aria-checked", "true")
  })
})
