import { beforeAll, describe, expect, it, vi } from "vitest"
import { fireEvent, render, screen, waitFor, within } from "@testing-library/react"
import { ServiceContext } from "../../app/providers"
import type { AnalysisService } from "../../api/service"
import type { CompanyItem, ReportDoc, ReportSummary } from "../../api/types"
import { ReportDetail } from "./ReportDetail"
import { nowTitle } from "./sections"

// 「분석 기준일의 종목과 포트폴리오 비중」 파트 이름은 그 날짜로 (2026-11-16 사용자 요청) — 아래 문서의 selection_as_of 2026-10-30
const NOW_TITLE = "2026년 10월 30일의 종목과 포트폴리오 비중"

// 리포트 화면 전체: 개요 → 자세한 분석(통째로 접힘, 안의 섹션도 접힘). 정보가 사라지지 않는지(모두 펼치면 전부 보이는지)와 주소로 들어온 부분이 펼쳐지는지 확인한다.

beforeAll(() => {
  Element.prototype.scrollIntoView = vi.fn()
  globalThis.ResizeObserver ??= class { observe() {} unobserve() {} disconnect() {} } as unknown as typeof ResizeObserver
})

const company = (t: string, over: Partial<CompanyItem> = {}): CompanyItem => ({ ticker: t, name: `${t} Inc.`, market: "US", sector: "IT", sub_industry: "Semis", summary: `${t} makes chips.`, theme_reason_ko: `${t} 테마 이유`, theme_confidence: 0.9, weight: 0.5, in_selection_now: true, rank_now: 1, metric_now: 0.3, in_backtest: true, rank_bt: 1, metric_bt: 0.2, fact_id: null, rationale_ko: [`${t} 선정 근거 전문 문단`], evidence_ids: [], n_news: 0, n_disclosures: 0, ...over })

const summary = (over: Partial<ReportSummary> = {}): ReportSummary => ({
  verdict: { status: "recommended_warn", label_ko: "추천(주의): 동일비중", headline_ko: "동일비중을 추천하지만 낙폭이 허용보다 큽니다", reason_ko: "후보 4개 중 1위. · 최대낙폭 30.7% vs 허용 20.0%", chosen_portfolio_id: "equal_weight", chosen_label_ko: "동일비중", notices_ko: ["선정 지표 자료가 부족했습니다"], n_notices: 1 },
  validation: { n_pass: 0, n_warn: 4, n_fail: 0, n_candidates: 4, chosen_status: "warn", failed_rules_ko: [], rules_ko: [{ rule: "R1", name_ko: "최대낙폭", level: "flag", status: "flag", message_ko: "최대낙폭 30.7% vs 허용 20.0%" }], r1: { mdd: 0.307, tolerance: 0.2, benchmark_mdd: 0.18, excess: 0.107, status: "flag" } },
  news_effect: { disabled: true, reason_ko: "뉴스 반영을 끈 분석입니다" },
  kpis: [{ id: "cagr", label_ko: "연평균 수익률 (CAGR)", value: 0.12, format: "pct", benchmark_value: 0.1, benchmark_label_ko: "SPY" }, { id: "mdd", label_ko: "최대낙폭 (MDD)", value: -0.307, format: "pct" }, { id: "excess", label_ko: "비교지수(SPY) 대비", value: 0.02, format: "pp" }],
  allocation: { basis: "forward", basis_ko: "분석 기준일 구성", items: [{ ticker: "AAA", name: "AAA Inc.", sector: "IT", weight: 0.6, usd: 600, krw: 840000 }, { ticker: "BBB", name: "BBB Inc.", sector: "IT", weight: 0.3, usd: 300, krw: 420000 }], cash_weight: 0.1, initial_amount_usd: 1000, fx_rate: 1400, fx_direction: "1 USD = 1,400.00 KRW" },
  mini_series: { dataset: "index", ids: ["equal_weight"] }, period: { start: "2023-10-30", end: "2026-10-30" },
  next_actions_ko: ["허용 낙폭을 다시 검토해 보세요."], ...over,
})

const doc = (over: Partial<ReportDoc> = {}): ReportDoc => ({
  request_id: "req_1", run_id: "run_1", stage: "", generated_at: "2026-11-01", source: "",
  header: { title_ko: "반도체 · 모멘텀 전략", subtitle_ko: "요청 요약", created_at: "2026-11-01", selection_as_of: "2026-10-30", backtest_period: { start: "2023-10-30", end: "2026-10-30", as_of: "2023-10-30" }, data_as_of: "2026-10-30", chosen_portfolio_id: "equal_weight", chosen_label_ko: "동일비중", chosen_note_ko: "후보 중 1위", disclaimer_ko: "면책 문구" },
  kpis: [{ id: "final_value", label_ko: "최종 평가금액", value: 1500, format: "usd", note_ko: "투입 원금 1,000 USD" }, { id: "cagr", label_ko: "연평균 수익률 (CAGR)", value: 0.12, format: "pct" }, { id: "sharpe", label_ko: "Sharpe 비율", value: 0.9, format: "ratio" }, { id: "view_hit", label_ko: "뉴스 뷰 적중률", value: null, format: "pct", note_ko: "이 포트폴리오에는 뷰가 없습니다" }],
  nav: [{ id: "verdict", title_ko: "종합 투자 판단" }, { id: "construction", title_ko: "포트폴리오 구성과 운용" }, { id: "companies", title_ko: "기업별 투자 근거" }, { id: "performance", title_ko: "과거 성과와 해석" }, { id: "assumptions", title_ko: "판단의 전제와 재검토 조건" }],
  sections: [
    { id: "verdict", title_ko: "종합 투자 판단", blocks: [{ type: "paragraphs", tone: "lead", items: ["판단 리드 문단 전문"] }, { type: "kpis", ids: ["final_value", "cagr", "sharpe", "view_hit"] }, { type: "paragraphs", items: ["판단 둘째 문단"] }] },
    { id: "construction", title_ko: "포트폴리오 구성과 운용", blocks: [
      { type: "weights_compare", title_ko: "비중 규칙별 구성", columns: [{ id: "equal_weight", label_ko: "동일비중", kind: "template", rule_ko: "모든 종목에 같은 비중" }, { id: "market_cap", label_ko: "시가총액비중", kind: "template", rule_ko: "시가총액 비례" }], rows: [{ ticker: "AAA", name: "AAA Inc.", sector: "IT", weights: { equal_weight: 0.45, market_cap: 0.7 } }, { ticker: "BBB", name: "BBB Inc.", sector: "IT", weights: { equal_weight: 0.45, market_cap: 0.2 } }], cash: { equal_weight: 0.1, market_cap: 0.1 }, ex_ante: {}, baseline_id: "equal_weight" },
      { type: "timeline", title_ko: "리밸런싱 타임라인", portfolio_id: "equal_weight", walkforward: false, items: [{ seq: 0, date: "2023-10-30", kind: "rebalance", n_trading_days_to_date: 0, value_usd: 1000, benchmark_value_usd: 1000, net_invested_usd: 1000, since_last: null, n_trades: 2, turnover: null, commission_usd: 1, to_date: null, cash_after: 0.1, news: null, views: [], top_delta: [] }, { seq: 1, date: "2024-01-02", kind: "rebalance", n_trading_days_to_date: 40, value_usd: 1100, benchmark_value_usd: 1050, net_invested_usd: 1000, since_last: { return: 0.1 }, n_trades: 2, turnover: null, commission_usd: 1, to_date: null, cash_after: 0.1, news: null, views: [], top_delta: [] }] },
    ] },
    { id: "companies", title_ko: "기업별 투자 근거", blocks: [{ type: "companies", title_ko: "선정 종목", metric: "return_12m_1m", metric_ko: "모멘텀", direction: "desc", as_of_now: "2026-10-30", as_of_bt: "2023-10-30", portfolio_id: "equal_weight", items: [company("AAA"), company("BBB")] }] },
    { id: "performance", title_ko: "과거 성과와 해석", blocks: [
      { type: "callout", tone: "info", title_ko: "백테스트 가정", text_ko: "거래비용 0.05%" },
      { type: "table", title_ko: "포트폴리오 비교", columns: [{ key: "name", label_ko: "포트폴리오" }, { key: "kind", label_ko: "종류" }, { key: "cagr", label_ko: "CAGR", format: "pct" }, { key: "vol", label_ko: "변동성", format: "pct" }, { key: "sharpe", label_ko: "Sharpe", format: "ratio" }, { key: "mdd", label_ko: "최대낙폭", format: "pct" }], rows: [{ name: "동일비중", kind: "규칙", cagr: 0.12, vol: 0.25, sharpe: 0.9, mdd: -0.307 }, { name: "시가총액비중", kind: "규칙", cagr: 0.1, vol: 0.2, sharpe: 0.8, mdd: -0.25 }, { name: "SPY 매수보유", kind: "비교지수", cagr: 0.1, vol: 0.15, sharpe: 0.7, mdd: -0.18 }] },
      { type: "paragraphs", group_ko: "검증 상세", group_open: true, items: ["검증 상세 문단"] },
    ] },
    { id: "assumptions", title_ko: "판단의 전제와 재검토 조건", blocks: [{ type: "cards", title_ko: "확인한 한계", items: [1, 2, 3].map((i) => ({ title_ko: `한계 ${i}`, text_ko: `한계 설명 ${i}`, meta: [] })) }] },
  ],
  datasets: { dates: ["2023-10-30", "2026-10-30"], series: { equal_weight: { label_ko: "동일비중", kind: "template", index: [100, 140] } } },
  assessment: { intent_fit: null, logic_consistency: null, comments_ko: [] }, evidence: [], execution: [], tracking: { eligible: true, reason_ko: null }, sources: [], parameters: {}, warnings: [],
  doc_version: 2, summary: summary(), evidence_summary: { total: 0, cited: 0, by_kind: {} }, ...over,
})

const service = (d: ReportDoc) => ({
  getReport: vi.fn(async () => d), getReportComparison: vi.fn(async () => { throw new Error("none") }),
  getRequest: vi.fn(async () => ({ idea: "반도체에 투자하고 싶어", questions: [], revision: null, conditions: [], confirmation: { rows: [] } })),
  getReportCheckpoint: vi.fn(async () => null), getReportEvidence: vi.fn(async () => null), getReportEvidenceOne: vi.fn(async () => null),
  listReports: vi.fn(async () => []),  // 표시 이름용 목록 (행이 없으면 서버 제목 그대로)
}) as unknown as AnalysisService
const show = (d: ReportDoc, props: { sec?: string; company?: string; rb?: number } = {}) => render(<ServiceContext.Provider value={service(d)}><ReportDetail reportId="run_1" {...props} /></ServiceContext.Provider>)
const section = (name: RegExp) => screen.getAllByRole("button", { name }).find((b) => b.hasAttribute("aria-expanded"))!  // 좁은 화면 칩과 같은 이름이라 접기 단추만
// 「자세한 분석」은 접히지 않는 섹션 제목이다 (2026-11-14). 안의 섹션 카드는 처음부터 보이고 접힌 채 시작한다
const details = () => screen.findByRole("heading", { name: "자세한 분석", level: 2 })
const openDetails = async () => { await details() }

describe("리포트 화면 구조", () => {
  it("개요가 먼저 보이고, 자세한 분석은 바깥 접기 없이 섹션 카드가 바로 보이며 카드는 접힌 채 시작한다", async () => {
    show(doc())
    expect(await screen.findByRole("region", { name: "선택한 전략" })).toHaveTextContent("동일비중")
    for (const q of ["선택한 전략", "과거 투자 결과", "종목 구성과 투자 금액"]) expect(screen.getByRole("heading", { name: q })).toBeInTheDocument()
    expect(screen.queryByRole("heading", { name: /^종목 구성 ·/ })).toBeNull()  // 종목 구성 카드는 투자 금액 카드와 겹쳐 없앴다
    expect(screen.getByRole("img", { name: "누적 수익률 그래프" })).toBeInTheDocument()  // 핵심 성과 왼쪽 그래프
    for (const q of ["조건 점검", "중요한 주의 사항"]) expect(screen.queryByRole("heading", { name: q })).toBeNull()  // 판정·주의·조건 점검은 개요에 두지 않는다
    expect(screen.queryByRole("list", { name: "중요한 주의 사항" })).toBeNull()
    expect(screen.queryByText(/추천\(주의\)|동일비중을 추천하지만/)).toBeNull()
    expect(await details()).toBeInTheDocument()
    expect(screen.queryByRole("button", { name: "자세한 분석" })).toBeNull()  // 제목은 단추가 아니다 (한 번만 눌러 카드를 연다)
    expect(screen.getByRole("button", { name: "모두 펼치기" })).toBeInTheDocument()
    for (const q of [/^\d+\. 종합 판단/, /^\d+\. 포트폴리오 구성/, /^\d+\. 기업별 근거/, /^\d+\. 과거 성과/, /^\d+\. 요청 내역/, /^\d+\. 주의 사항과 전제/]) expect(section(q)).toHaveAttribute("aria-expanded", "false")
    expect(screen.queryByText("판단 리드 문단 전문")).toBeNull()
    fireEvent.click(section(/^\d+\. 주의 사항과 전제/))
    expect(within(screen.getByRole("list", { name: "중요한 주의 사항" })).getByText("허용 초과")).toBeInTheDocument()
    expect(screen.queryByText(/^분석 중 확인한 점 \d+건$/)).toBeNull()  // 아래 표와 같은 문장이라 주의 사항 아래 상자는 두지 않는다
  })
  it("모두 펼치면 개요에서 빠진 KPI·판단 원문·비교표·기업 카드·전제가 모두 화면에 나온다", async () => {
    show(doc())
    await openDetails()
    fireEvent.click((await screen.findAllByRole("button", { name: "모두 펼치기" }))[0])
    expect(section(/^\d+\. 과거 성과/)).toHaveAttribute("aria-expanded", "true")
    expect(screen.getByText("뉴스 뷰 적중률")).toBeInTheDocument(); expect(screen.getByText("이 포트폴리오에는 뷰가 없습니다")).toBeInTheDocument()
    expect(screen.getAllByText("Sharpe 비율").length).toBeGreaterThan(0)
    fireEvent.click(screen.getByRole("button", { name: /선택 근거 자세히 보기/ }))
    expect(screen.getByText("판단 리드 문단 전문")).toBeInTheDocument(); expect(screen.getByText("판단 둘째 문단")).toBeInTheDocument()
    expect(within(screen.getByRole("list", { name: "이 전략을 고른 이유" })).getByText(/^비교한 \d+개 포트폴리오 중 가장 앞선 구성$/)).toBeInTheDocument()  // 서버 판단 이유를 구분자로 나누고, 아는 틀이면 제목 + 설명으로 (개요에는 제목만)
    expect(screen.getByText(/4개 투자 구성안을 정해진 순서대로 비교했을 때/)).toBeInTheDocument()
    const why = screen.getByRole("list", { name: "이 전략을 고른 이유" })
    expect(within(why).getByText("최대낙폭 30.7% vs 허용 20.0%")).toBeInTheDocument()  // 틀에 맞지 않는 조각은 원문 그대로 — 모든 조각이 남는다
    expect(within(why).getAllByRole("listitem")).toHaveLength(2)
    expect(screen.queryByRole("button", { name: /판단 이유 원문 보기/ })).toBeNull()  // 같은 내용을 다시 보여 주던 원문 보기는 없다
    expect(screen.queryByText("검증 상세 문단")).toBeNull()  // 「조건별 근거 보기」(서버 이름 검증 상세)는 기본으로 접는다 (2026-11-16)
    fireEvent.click(screen.getByRole("button", { name: /^조건별 근거 보기/ }))
    expect(screen.getByText("검증 상세 문단")).toBeInTheDocument()
    expect(screen.queryByRole("button", { name: /^검증 상세/ })).toBeNull()
    fireEvent.click(screen.getByRole("button", { name: /전체 전략 비교표/ }))
    expect(screen.getAllByText("시가총액비중").length).toBeGreaterThan(0)
    expect(screen.getByText(/선택 전략이 기준 비중\(동일비중\)과 같습니다/)).toBeInTheDocument()  // 선택 = 기준이면 비교 막대 없이 한 줄 (2026-11-16: 설명줄 → 범례 자리)
    fireEvent.click(screen.getByRole("button", { name: /확인한 한계/ }))
    expect(screen.getByText("한계 설명 3")).toBeInTheDocument()
    expect(screen.getByText("뉴스 반영을 끈 분석입니다")).toBeInTheDocument()
    expect(screen.getByText("허용 낙폭을 다시 검토해 보세요.")).toBeInTheDocument()  // 다음에 검토할 점이 카드 블록에 없으면 따로 남는다
  })
  it("선택 전략이 기준과 다르면 같은 시점의 두 비중을 종목마다 막대 두 개로 나란히 보여 주고(차이 숫자는 쓰지 않는다), 비교표에 없으면 그리지 않는다", async () => {
    const d = doc()
    const { unmount } = show({ ...d, header: { ...d.header, chosen_portfolio_id: "market_cap", chosen_label_ko: "시가총액비중" } }, { sec: "construction" })
    const list = await screen.findByRole("list", { name: "종목별 포트폴리오 비중 비교" })
    expect(within(list).getAllByRole("listitem").map((x) => x.getAttribute("aria-label"))).toEqual(["AAA 기준 45.0%, 선택 70.0%", "BBB 기준 45.0%, 선택 20.0%", "현금 기준 10.0%, 선택 10.0%"])
    expect(list).not.toHaveTextContent("%p"); expect(list).not.toHaveTextContent("변화 없음")
    unmount()
    show({ ...d, header: { ...d.header, chosen_portfolio_id: "dd_match", chosen_label_ko: "낙폭 맞춤안" } }, { sec: "construction" })
    expect(await screen.findByText(/선택 전략의 포트폴리오 비중은 개요의 종목 구성과 투자 금액, 리밸런싱 기록에 있습니다/)).toBeInTheDocument()
    expect(screen.queryByRole("list", { name: "종목별 포트폴리오 비중 비교" })).toBeNull()
  })
  it("3. 포트폴리오 구성은 질문별 파트로 나누고, 어디에도 맞지 않는 블록도 맨 아래에 남긴다", async () => {
    const d = doc()
    const con = d.sections.find((x) => x.id === "construction")!
    const extra = [
      { type: "paragraphs", src: "14b", items: ["비중 결정 문단"] },
      { type: "table", title_ko: "배분 금액 (동일비중, 백테스트 시작일 초기 투자금 13,755 USD 기준, 원화는 시작일 환율)", columns: [{ key: "ticker", label_ko: "티커" }], rows: [{ ticker: "AAA" }] },
      { type: "callout", tone: "info", title_ko: "뉴스 뷰 Black-Litterman (walk-forward)", text_ko: "BL 기간 결과" },
      { type: "callout", tone: "info", title_ko: "시가총액비중 (walk-forward)", text_ko: "기준 기간 결과" },
      { type: "paragraphs", src: "14b", group_ko: "분석 기준일의 현재 구성", items: ["현재 구성 문단"] },
      { type: "callout", tone: "info", title_ko: "현재 구성 (분석 기준일 2026-10-30)", text_ko: "뉴스 창과 계산 세부값", group_ko: "분석 기준일의 현재 구성" },
      { type: "callout", tone: "info", title_ko: "오늘 구성 안내", text_ko: "오늘 구성", group_ko: "분석 기준일의 현재 구성" },
      { type: "callout", tone: "info", title_ko: "모르는 블록", text_ko: "남아야 하는 내용" },
      { type: "bar", title_ko: "뉴스 의견: 기준 비중 대비 변화", items: [{ label: "AAA", value: 0.01 }], format: "pp" },
      { type: "paragraphs", src: "14a", items: ["뉴스 반영 해석 문단"] },
    ]
    show({ ...d, sections: d.sections.map((x) => (x === con ? { ...con, blocks: [...con.blocks, ...extra] } : x)) } as never, { sec: "construction" })
    await screen.findByRole("heading", { name: /^전략별 투자 비중/ })
    const hs = screen.getAllByRole("heading", { level: 3 }).map((h) => h.textContent ?? "")
    // 2026-11-16 사용자 표: 1 과정 → 2 분석 기준일 → 3 백테스트 시작일 포트폴리오 비중(+ 시작일 투자 금액) → 4 전략별 → 5 뉴스 반영 → 6 조정 기록 → 그 밖
    const order = ["포트폴리오 비중이 정해진 과정", NOW_TITLE, "백테스트 시작일의 기준 비중과 선택 전략 비중", "백테스트 시작일 투자 금액 (동일비중)", "전략별 투자 비중", "뉴스를 반영한 포트폴리오 비중", "과거 포트폴리오 비중 조정 기록", "그 밖의 내용"]
    expect(order.map((t) => hs.findIndex((h) => h.startsWith(t)))).toEqual([...order.map((t) => hs.findIndex((h) => h.startsWith(t)))].sort((a, b) => a - b))
    expect(order.every((t) => hs.some((h) => h.startsWith(t)))).toBe(true)
    expect(screen.getByText("비교용 구성")).toBeInTheDocument()
    expect(screen.getByText(/첫 투자금 13,755 USD를 선택 전략\(동일비중\) 포트폴리오 비중대로 종목마다 나눈 금액입니다\. 원화는 그날 환율로 계산했습니다\./)).toBeInTheDocument()
    expect(screen.getByText("BL 기간 결과")).toBeInTheDocument(); expect(screen.queryByText("기준 기간 결과")).toBeNull()  // BL 이 아닌 전략의 기간 성과 한 줄은 「과거 성과 → 전략 비교」에 있어 여기서는 그리지 않는다
    expect(screen.getByText("오늘 구성")).toBeInTheDocument()  // 현재 구성은 접지 않는다
    expect(screen.getByText("남아야 하는 내용")).toBeInTheDocument()
    expect(screen.queryByRole("button", { name: /포트폴리오 비중 변화 그래프|뉴스 반영 해석/ })).toBeNull()  // BL 파트의 포트폴리오 비중 변화 그래프·뉴스 반영 해석은 그리지 않는다
    // 큰 파트는 번호가 붙은 구역이고, 작은 파트(블록)는 그 구역 안에 들어 있다
    const bl = screen.getByRole("region", { name: "뉴스를 반영한 포트폴리오 비중" })
    expect(within(bl).getByText("BL 기간 결과")).toBeInTheDocument()
    expect(within(screen.getByRole("region", { name: NOW_TITLE })).getByText("오늘 구성")).toBeInTheDocument()
    const now = screen.getByRole("region", { name: NOW_TITLE })
    expect(within(now).queryByText(/뉴스 창과 계산 세부값/)).toBeNull()
    fireEvent.click(within(now).getByRole("button", { name: /종목·포트폴리오 비중을 정한 근거/ }))
    expect(within(now).queryByText(/뉴스 창과 계산 세부값/)).toBeNull()  // 「계산 기준」 안내 상자는 없앴다 — 기간·건수는 본문에 한 번만 (2026-11-16 사용자 요청)
  })
  it("주소의 기업·시점으로 들어오면 그 섹션과 그 기업만 펼친다", async () => {
    show(doc(), { company: "BBB", rb: 1 })
    expect(await screen.findByText("BBB 선정 근거 전문 문단")).toBeInTheDocument()
    expect(screen.queryByText("AAA 선정 근거 전문 문단")).toBeNull()
    expect(section(/^\d+\. 포트폴리오 구성/)).toHaveAttribute("aria-expanded", "true")
    expect(screen.getByRole("option", { name: "2024-01-02 리밸런싱" })).toHaveAttribute("aria-selected", "true")
    expect(section(/^\d+\. 과거 성과/)).toHaveAttribute("aria-expanded", "false")
  })
  it("다른 리포트로 옮기면 앞 리포트의 펼침이 남지 않고, 같은 리포트에서 주소만 바뀌면 가리키는 기업을 펼친다", async () => {
    const svc = service(doc())
    const ui = (p: { reportId: string; company?: string }) => <ServiceContext.Provider value={svc}><ReportDetail {...p} /></ServiceContext.Provider>
    const { rerender } = render(ui({ reportId: "run_1" }))
    await openDetails()
    fireEvent.click((await screen.findAllByRole("button", { name: "모두 펼치기" }))[0])
    expect(section(/^\d+\. 과거 성과/)).toHaveAttribute("aria-expanded", "true")
    rerender(ui({ reportId: "run_2" }))
    await waitFor(() => expect(section(/^\d+\. 과거 성과/)).toHaveAttribute("aria-expanded", "false"))  // 다른 리포트는 카드가 다시 접힌 채
    rerender(ui({ reportId: "run_2", company: "AAA" }))
    expect(await screen.findByText("AAA 선정 근거 전문 문단")).toBeInTheDocument()
    expect(section(/^\d+\. 기업별 근거/)).toHaveAttribute("aria-expanded", "true")
  })
  it("개요의 링크는 자세한 분석의 해당 섹션 카드를 연다", async () => {
    show(doc())
    fireEvent.click(await screen.findByRole("button", { name: /과거 성과 자세히 보기/ }))
    await waitFor(() => expect(section(/^\d+\. 과거 성과/)).toHaveAttribute("aria-expanded", "true"))
    expect(document.getElementById("perf-validation")).toHaveTextContent("투자 조건 충족 여부")  // 조건 점검은 과거 성과 안으로 옮겼다
    expect(section(/^\d+\. 종합 판단/)).toHaveAttribute("aria-expanded", "false")
    fireEvent.click(screen.getByRole("button", { name: /선택 이유 보기/ }))
    await waitFor(() => expect(section(/^\d+\. 종합 판단/)).toHaveAttribute("aria-expanded", "true"))
  })
  it("summary 가 없는 예전 형식 리포트도 요약 카드를 만들고 '자동 변환'을 알린다", async () => {
    const v1 = doc({ doc_version: 1, summary: null, presented_from_version: 1 })
    show(v1)
    expect(await screen.findByRole("region", { name: "선택한 전략" })).toBeInTheDocument()
    expect(screen.getByText("예전 형식 리포트 (자동 변환)")).toBeInTheDocument()
  })
})

describe("분석 당시 투자성향", () => {
  it("현재 프로필 성향(공격투자형)과 관계없이 리포트에 저장된 성향·변동성 기준을 쓴다", async () => {
    const d = doc({ summary: summary({ validation: { ...summary().validation, info_notes_ko: ["연변동성 45.5% vs 비교지수 12.8%의 1.3배(중립 성향) = 16.6% (창이 짧아 참고만)"] } }) })
    d.nav = [...d.nav, { id: "market", title_ko: "산업과 시장 분석" }]
    d.sections = [...d.sections, { id: "market", title_ko: "산업과 시장 분석", blocks: [
      { type: "table", title_ko: "요청 내용", group_ko: "요청 조건 확인", columns: [{ key: "k", label_ko: "항목" }, { key: "v", label_ko: "내용" }], rows: [{ k: "투자성향", v: "moderate · 손실 감내 수준 30.0% · 손실 시 hold" }] },
      { type: "table", title_ko: "성향 해석 (소프트 조건)", group_ko: "요청 조건 확인", columns: [{ key: "k", label_ko: "항목" }, { key: "v", label_ko: "내용" }], rows: [{ k: "변동성 선호", v: "medium" }] },
    ] }]
    const getProfile = vi.fn(async () => ({ profile_id: "p", current_version: 9, versions: [], profile: { diagnosis: { answers: {}, computed_tendency: "공격투자형", final_tendency: "공격투자형" } } }))
    render(<ServiceContext.Provider value={{ ...service(d), getProfile } as unknown as AnalysisService}><ReportDetail reportId="run_1" sec="market" /></ServiceContext.Provider>)
    await screen.findAllByRole("button", { name: /^\d+\. 과거 성과/ })
    fireEvent.click(section(/^\d+\. 과거 성과/))  // 조건별 검증은 과거 성과 안에 있다
    const fit = document.getElementById("perf-validation")!
    expect(fit).toHaveTextContent("이번 분석의 변동성 기준: 중간 변동성 기준투자성향: 위험중립형")
    fireEvent.click(screen.getByRole("button", { name: /요청 조건 확인/ }))
    expect(screen.getByText("위험중립형 · 손실 감내 수준 30.0% · 손실 시 보유")).toBeInTheDocument()
    expect(screen.getByText("중간 변동성 기준", { selector: "td" })).toBeInTheDocument()
    expect(screen.queryByText(/공격투자형|moderate|중립 성향/)).toBeNull()
    expect(getProfile).not.toHaveBeenCalled()
  })
})

describe("이 전략을 고른 이유", () => {
  it("모르는 문장과 인용은 그대로 남고, 원문 보기 없이도 「선택 근거 자세히 보기」는 열 수 있다", async () => {
    show(doc({ summary: summary({ verdict: { ...summary().verdict, reason_ko: "후보 4개 중 1위. · 새로운 서버 문장 [ev1] · Sharpe 0.90" } }) }), { sec: "verdict" })
    const why = await screen.findByRole("list", { name: "이 전략을 고른 이유" })
    expect(within(why).getAllByRole("listitem")).toHaveLength(3)
    expect(within(why).getByText(/새로운 서버 문장/)).toBeInTheDocument()
    expect(within(why).getByRole("button", { name: "근거 ev1 보기" })).toBeInTheDocument()
    expect(within(why).getByText(/샤프 비율은 0\.90입니다/)).toBeInTheDocument()
    expect(screen.queryByRole("button", { name: /판단 이유 원문 보기/ })).toBeNull()
    fireEvent.click(screen.getByRole("button", { name: /선택 근거 자세히 보기/ }))
    expect(screen.getByText("판단 리드 문단 전문")).toBeInTheDocument()
  })
  it("평가 기간이 짧아 목표 수익률을 판정하지 않은 항목은 「목표 수익률 판정 보류」와 그 설명으로 보인다", async () => {
    show(doc({ summary: summary({ verdict: { ...summary().verdict, reason_ko: "후보 4개 중 1위. · 목표수익은 창이 짧아 참고만" } }) }), { sec: "verdict" })
    const why = await screen.findByRole("list", { name: "이 전략을 고른 이유" })
    expect(within(why).getByText("목표 수익률 판정 보류")).toBeInTheDocument()
    expect(within(why).getByText("과거 성과를 살펴본 기간이 짧아, 이번 분석에서는 연간 목표 수익률의 달성 여부를 판정하지 않았습니다.")).toBeInTheDocument()
    expect(within(why).queryByText(/목표 달성 여부는 참고용|참고로만 봤습니다/)).toBeNull()
  })
})

describe("선택 근거 자세히 보기의 용어", () => {
  it("본문에 나온 용어 이름을 넓은 화면용 오른쪽 목록과 좁은 화면용 접이식 목록으로 두고, 이름을 누르면 아래에 설명 하나, 본문 출처 버튼은 그대로", async () => {
    const d = doc()
    const verdict = { id: "verdict", title_ko: "종합 투자 판단", blocks: [{ type: "paragraphs", tone: "lead", items: ["최대낙폭은 23.2%로 허용 범위 안이었고 [ev1], 연평균 수익률(CAGR)은 23.8%였습니다."] }, { type: "paragraphs", items: ["MDD 와 샤프 비율도 확인했습니다."] }] }
    show({ ...d, sections: d.sections.map((x) => (x.id === "verdict" ? verdict : x)) } as never, { sec: "verdict" })
    fireEvent.click(await screen.findByRole("button", { name: /선택 근거 자세히 보기/ }))
    const side = screen.getByRole("complementary", { name: "본문에 나온 용어" })
    const list = within(side).getByRole("list", { name: "본문에 나온 용어 목록" })
    expect(within(list).getAllByRole("listitem").map((x) => x.textContent)).toEqual(["최대낙폭", "CAGR", "Sharpe"])  // 처음 나온 순서, 별칭(MDD·샤프 비율)은 한 번만, 이름만 보인다
    expect(within(side).queryByRole("region")).toBeNull()  // 처음에는 이름만
    fireEvent.click(within(list).getByRole("button", { name: "CAGR" }))  // 이름을 누르면 바로 아래에 설명
    expect(within(side).getByRole("region", { name: "CAGR 설명" })).toHaveTextContent("연평균 수익률")
    fireEvent.click(within(list).getByRole("button", { name: "Sharpe" }))  // 다른 이름을 누르면 그 설명만 (한 번에 하나)
    expect(within(side).getAllByRole("region").map((x) => x.getAttribute("aria-label"))).toEqual(["Sharpe 설명"])
    fireEvent.click(within(list).getByRole("button", { name: "Sharpe" }))
    expect(within(side).queryByRole("region")).toBeNull()
    const narrow = screen.getByRole("button", { name: /^본문에 나온 용어/ })  // 좁은 화면용 접이식: 펼치면 같은 목록
    expect(narrow).toHaveAttribute("aria-expanded", "false")
    fireEvent.click(narrow)
    expect(screen.getAllByRole("list", { name: "본문에 나온 용어 목록" })).toHaveLength(2)
    expect(screen.getByRole("button", { name: "근거 ev1 보기" })).toBeInTheDocument()
  })
  it("용어가 하나면 그 이름 하나만", async () => {
    const d = doc()
    const verdict = { id: "verdict", title_ko: "종합 투자 판단", blocks: [{ type: "paragraphs", tone: "lead", items: ["최대낙폭은 23.2%였습니다."] }] }
    show({ ...d, sections: d.sections.map((x) => (x.id === "verdict" ? verdict : x)) } as never, { sec: "verdict" })
    fireEvent.click(await screen.findByRole("button", { name: /선택 근거 자세히 보기/ }))
    const side = screen.getByRole("complementary", { name: "본문에 나온 용어" })
    expect(within(side).getAllByRole("listitem").map((x) => x.textContent)).toEqual(["최대낙폭"])
    expect(within(side).getByRole("button", { name: "최대낙폭" })).toHaveAttribute("aria-expanded", "false")
  })
  it("용어가 없는 본문은 목록 없이 본문만", async () => {
    show(doc(), { sec: "verdict" })
    fireEvent.click(await screen.findByRole("button", { name: /선택 근거 자세히 보기/ }))
    expect(screen.getByText("판단 리드 문단 전문")).toBeInTheDocument()
    expect(screen.queryByRole("complementary", { name: "본문에 나온 용어" })).toBeNull()
  })
})

describe("근거 번호 누르기", () => {
  it("근거 번호를 누르면 바로 밖으로 나가지 않고 근거 패널을 먼저 연다: 어느 문장의 근거인지 → 내용 → 원문 열기 (2026-11-28)", async () => {
    const open = vi.spyOn(window, "open").mockImplementation(() => null)
    const reason = "후보 4개 중 1위. · 기사 [ev1] · 계산 [ev2]"
    show(doc({ evidence: [{ id: "ev1", kind: "news", title: "기사 제목", source: "benzinga", url: "https://example.com/a", tickers: [] }, { id: "ev2", kind: "news", title: "주소 없는 자료", source: "x", url: null, tickers: [] }] as unknown as ReportDoc["evidence"], summary: summary({ verdict: { ...summary().verdict, reason_ko: reason } }) }), { sec: "verdict" })
    const why = await screen.findByRole("list", { name: "이 전략을 고른 이유" })
    fireEvent.click(within(why).getByRole("button", { name: "근거 ev1 보기" }))
    const panel = await screen.findByRole("dialog", { name: "근거 자세히" })
    expect(open).not.toHaveBeenCalled()
    expect(within(panel).getByText("기사 제목")).toBeInTheDocument()
    expect(within(panel).getByRole("link", { name: /원문 열기/ })).toHaveAttribute("href", "https://example.com/a")
    fireEvent.click(within(panel).getByRole("button", { name: "닫기" }))
    fireEvent.click(within(why).getByRole("button", { name: "근거 ev2 보기" }))
    const second = await screen.findByRole("dialog", { name: "근거 자세히" })
    expect(within(second).getByText("주소 없는 자료")).toBeInTheDocument()
    expect(within(second).queryByRole("link", { name: /원문 열기/ })).toBeNull()
    open.mockRestore()
  })
})

describe("리포트 상단 탐색·용어", () => {
  it("왼쪽 리포트 목차 없이 상단 가로 탭 하나로 이동하고, 탭을 누르면 그 섹션을 펼치고 강조한다", async () => {
    show(doc())
    await screen.findByRole("region", { name: "선택한 전략" })
    const navs = screen.getAllByRole("navigation", { name: "리포트 섹션" })
    expect(navs).toHaveLength(1)  // 예전 왼쪽 목차 + 좁은 화면 칩이 하나로
    const tabs = within(navs[0]).getAllByRole("button").map((b) => b.textContent)
    expect(tabs).toEqual(["개요", "종목 선정", "과거 성과", "요청·주의사항·자료"])  // 섹션 묶음 단위 탭. 이 문서에 market 섹션은 없다
    expect(within(navs[0]).getByRole("button", { name: "개요" })).toHaveAttribute("aria-current", "true")
    fireEvent.click(within(navs[0]).getByRole("button", { name: "종목 선정" }))
    expect(within(navs[0]).getByRole("button", { name: "종목 선정" })).toHaveAttribute("aria-current", "true")
    expect(section(/^\d+\. 종합 판단/)).toHaveAttribute("aria-expanded", "true")  // 묶음의 첫 섹션을 펼친다 (섹션 제목은 질문형 그대로)
    expect(screen.getByRole("heading", { name: "종목 선정", level: 3 })).toBeInTheDocument()  // 아래 접이식 섹션도 같은 묶음 소제목으로 묶인다
    expect(screen.queryByRole("complementary")).toBeNull()
  })
  it("선택한 전략에는 날짜 문장을 두지 않고(2026-11-14), 머리말에도 백테스트 기간을 다시 쓰지 않으며, 더보기에 출처 전체·계산 조건·실행 기록이 있다", async () => {
    show(doc())
    const strip = await screen.findByRole("region", { name: "선택한 전략" })
    expect(strip).not.toHaveTextContent(/자료 기준|과거 성과로 확인|2023-10-30 ~ 2026-10-30/)
    expect(within(strip).queryByRole("button", { name: /날짜 구분/ })).toBeNull()
    expect(screen.queryByLabelText("리포트 날짜")).toBeNull()  // 머리말에 같은 백테스트 기간을 한 번 더 쓰지 않는다
    fireEvent.click(screen.getByRole("button", { name: /더보기/ }))
    for (const n of [/출처 전체 \(0\)/, /계산 조건/, /실행 기록/]) expect(screen.getByRole("menuitem", { name: n })).toBeInTheDocument()
  })
  it("「투자 용어 설명」은 리포트 용어 풀이를 먼저, 없는 용어는 공통 설명으로 보여 주고, 하단 용어 풀이는 그대로 남는다", async () => {
    const d = doc()
    d.nav = [...d.nav, { id: "references", title_ko: "참고자료와 분석 조건" }]
    d.sections = [...d.sections, { id: "references", title_ko: "참고자료와 분석 조건", blocks: [{ type: "glossary", items: [{ term: "CAGR", explain_ko: "서버가 준 CAGR 설명" }] }] }]
    show(d)
    fireEvent.click(await screen.findByRole("button", { name: "투자 용어 설명" }))
    const panel = screen.getByRole("dialog", { name: "투자 용어 설명" })
    expect(within(panel).getByText("서버가 준 CAGR 설명")).toBeInTheDocument()
    expect(within(panel).getByText("낙폭 맞춤안")).toBeInTheDocument()  // 서버 풀이에 없는 용어
    expect(within(panel).queryAllByText(/^CAGR$/)).toHaveLength(1)  // 같은 용어를 두 번 설명하지 않는다
    fireEvent.change(within(panel).getByPlaceholderText(/용어 찾기/), { target: { value: "낙폭 맞춤" } })
    expect(within(panel).queryByText("서버가 준 CAGR 설명")).toBeNull()
    fireEvent.click(within(panel).getByRole("button", { name: "리포트의 전체 용어 풀이로 이동" }))
    expect(section(/^\d+\. 자료와 분석 조건/)).toHaveAttribute("aria-expanded", "true")
    expect(screen.getByText("서버가 준 CAGR 설명")).toBeInTheDocument()  // 하단 전체 용어 풀이
  })
  it("전체 전략 비교표는 서버 값 그대로 두고 최종 선택·기준 전략·비교지수 역할을 표시한다", async () => {
    show(doc())
    await openDetails()
    fireEvent.click((await screen.findAllByRole("button", { name: "모두 펼치기" }))[0])
    fireEvent.click(await screen.findByRole("button", { name: /전체 전략 비교표/ }))
    const table = screen.getAllByRole("table").at(-1)!
    const row = (name: string) => within(table).getByText(name).closest("tr")!
    expect(within(row("동일비중")).getByText("최종 선택")).toBeInTheDocument()
    expect(within(table).getByRole("columnheader", { name: /연평균 수익률\(CAGR\)/ })).toBeInTheDocument()
    expect(screen.queryByText(/수익률이 가장 높은 전략과 최종 선택된 전략은 다를 수 있습니다/)).toBeNull()  // 표 위 설명 문장은 두지 않는다
  })
})

describe("머리말", () => {
  it("제목은 리포트의 짧은 제목, 회색 글은 요청과 처리 이유 요약 (목록의 아이디어 원문을 제목으로 쓰지 않는다)", async () => {
    const base = doc()
    const d = doc({ header: { ...base.header, subtitle_ko: "요청 해석 문장", summary_ko: "반도체에 3년 투자하고 싶다는 요청입니다. 답하신 대로 종목 수를 줄였습니다." } })
    const svc = service(d)
    vi.mocked(svc.listReports).mockResolvedValue([{ report_id: "run_1", run_id: "run_1", request_id: "req_1", status: "success", has_report: true, as_of: "2026-10-30", idea: "반도체에 투자하고 싶어요. 아주 긴 아이디어 원문" }])
    render(<ServiceContext.Provider value={svc}><ReportDetail reportId="run_1" /></ServiceContext.Provider>)
    expect(await screen.findByRole("heading", { level: 1, name: "반도체 · 모멘텀 전략" })).toBeInTheDocument()
    expect(screen.getByText("반도체에 3년 투자하고 싶다는 요청입니다. 답하신 대로 종목 수를 줄였습니다.")).toBeInTheDocument()
    expect(screen.queryByText("요청 해석 문장")).toBeNull()
    await waitFor(() => expect(vi.mocked(svc.listReports)).toHaveBeenCalled())
    expect(screen.getByRole("heading", { level: 1 })).toHaveTextContent("반도체 · 모멘텀 전략")
  })
  it("요약이 없는 옛 리포트는 요청 해석 문장을 자르지 않고 보인다", async () => {
    const base = doc()
    show(doc({ header: { ...base.header, subtitle_ko: "요청 해석 문장" } }))
    expect(await screen.findByRole("heading", { level: 1, name: "반도체 · 모멘텀 전략" })).toBeInTheDocument()
    expect(screen.getByText("요청 해석 문장")).not.toHaveClass("truncate")
  })
})

describe("분석 기준일 파트 이름 (2026-11-16)", () => {
  it("'분석 기준일' 대신 연·월·일, 날짜가 없으면 예전 이름", () => {
    expect(nowTitle({ header: { selection_as_of: "2026-11-10" } } as never)).toBe("2026년 11월 10일의 종목과 포트폴리오 비중")
    expect(nowTitle({ header: { selection_as_of: "" } } as never)).toBe("분석한 날의 종목과 포트폴리오 비중")
  })
})

describe("낙폭 맞춤안 설명은 「이 전략을 고른 이유」 목록이 아니라 선택 전략 아래 (2026-11-20)", () => {
  it("판단 이유에서 구성 설명을 빼고, 선택 전략 설명 한 문장으로", async () => {
    const { reasonsOf, chosenDescOf } = await import("./proposedView")
    const reason_ko = "후보 12개 중 1위 · 목표수익은 창이 짧아 참고만 · Sharpe 0.89 · 시가총액비중의 주식 비중을 42.7%로 줄여 과거 최대낙폭을 목표 15.0% 안에 맞춘 구성 · CAGR 22.5%, 최종 평가금액 20,494 USD."
    const doc = { summary: { verdict: { reason_ko } } } as unknown as ReportDoc
    const rs = reasonsOf(doc, true).map(({ t }) => t)
    expect(rs).toHaveLength(4)
    expect(rs.some((t) => t.includes("주식 비중을 42.7%로 줄여"))).toBe(false)
    expect(chosenDescOf(doc)).toBe("시가총액비중 구성에서 주식 비중을 42.7%로 줄이고 나머지를 현금으로 두어, 과거 최대 하락폭을 목표 15.0% 안에 맞춘 구성입니다.")
    expect(chosenDescOf({ summary: { verdict: { reason_ko: "후보 3개 중 1위 · Sharpe 1.20로 가장 높음" } } } as unknown as ReportDoc)).toBeNull()
  })
})

describe("다음 분석에서 바꿔 볼 조건 — 번호 제목 대신 조건의 뜻 (2026-11-19)", () => {
  it("저장된 리포트의 「선택지 N」은 본문 첫 구절로 제목을 만든다", async () => {
    const { actionTitle, cardsView } = await import("./sections")
    expect(actionTitle("다음 분석에서 백테스트 기간을 3년으로 설정해 보면, 목표 수익률과 변동성 기준을 판정할 수 있는지 확인할 수 있습니다.")).toBe("백테스트 기간을 3년으로 설정해 보기")
    expect(actionTitle("다음 분석에서 업종 상한을 75%보다 낮게 설정하면, 정보기술 업종 집중도를 살펴볼 수 있습니다.")).toBe("업종 상한을 75%보다 낮게 설정하기")
    expect(actionTitle("다음 분석에서 최소 현금 비율을 정해 보면, 수익률과 최대낙폭이 어떻게 달라지는지 보면 됩니다.")).toBe("최소 현금 비율을 정해 보기")
    expect(actionTitle("다음 분석에서 현금을 더 넣으면, x")).toBe("현금을 더 넣기")
    expect(actionTitle("ServiceNow와 Micron Technology를 필수 포함 목록에서 빼고, 다른 종목과 같은 기준으로 다시 골라볼 수 있습니다.")).toBe("ServiceNow와 Micron Technology를 필수 포함에서 빼고 다시 고르기")
    expect(actionTitle("[목업] 다음 분석에서 비중을 맞추는 주기를 바꿔 보면, x")).toBe("비중을 맞추는 주기를 바꿔 보기")
    expect(actionTitle("조건을 확인해 보세요.")).toBeNull()
    const v = cardsView({ type: "cards", title_ko: "다음에 검토할 수 있는 선택지", items: [{ title_ko: "선택지 1", text_ko: "다음 분석에서 최소 현금 비율을 정해 보면, x", meta: [] }, { title_ko: "선택지 2", text_ko: "b", meta: [] }] })
    expect(v.items.map((x) => x.title_ko)).toEqual(["최소 현금 비율을 정해 보기", "조건 2"])
  })
})

describe("다음 분석에서 바꿔 볼 조건 (2026-11-16)", () => {
  it("서버 이름 「다음에 검토할 수 있는 선택지 / 선택지 N」 → 「다음 분석에서 바꿔 볼 조건 / 조건 N」, 다른 카드 묶음은 그대로", async () => {
    const { cardsView } = await import("./sections")
    const v = cardsView({ type: "cards", title_ko: "다음에 검토할 수 있는 선택지", items: [{ title_ko: "선택지 1", text_ko: "a", meta: [] }, { title_ko: "선택지 2", text_ko: "b", meta: [] }] })
    expect(v.title_ko).toBe("다음 분석에서 바꿔 볼 조건")
    expect(v.items.map((x) => x.title_ko)).toEqual(["조건 1", "조건 2"])  // 본문에서 조건을 알아볼 수 없으면 번호
    const named = cardsView({ type: "cards", title_ko: "다음에 검토할 수 있는 선택지", items: [{ title_ko: "기간 3년으로", text_ko: "다음 분석에서 기간을 늘려 보면, x", meta: [] }] })
    expect(named.items[0].title_ko).toBe("기간 3년으로")  // 서버가 준 제목은 그대로
    const lim = { type: "cards" as const, title_ko: "확인한 한계", items: [{ title_ko: "한계 1", text_ko: "a", meta: [] }] }
    expect(cardsView(lim)).toBe(lim)
  })
})
