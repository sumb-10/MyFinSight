import { beforeAll, describe, expect, it, vi } from "vitest"
import { fireEvent, render, screen, waitFor, within } from "@testing-library/react"
import { ServiceContext } from "../../app/providers"
import type { AnalysisService } from "../../api/service"
import type { CompanyItem, EvidenceRecord, ReportDoc } from "../../api/types"
import { ReportContext, type ReportCtx } from "./context"
import { companyNames, evidencePlain, evidenceTitle, evidenceValue, finParts, peersOf, rankText, sentenceFor } from "./evidenceText"
import { ReportDetail } from "./ReportDetail"
import { SourceDrawer } from "./SourceDrawer"

// 근거 화면 (2026-11-28): 근거 한 건을 「어느 문장의 근거인가 → 무엇을 말하는가 → 다른 회사와 견주면 → 자료 정보」 순서로 보여 주는지,
// 숫자를 본문과 같은 단위와 쉬운 한 문장으로 쓰는지, 목록은 본문에 쓰인 근거부터 보여 주는지, 기업 카드에 근거 묶음이 있는지.

beforeAll(() => {
  Element.prototype.scrollIntoView = vi.fn()
  window.scrollTo = vi.fn() as unknown as typeof window.scrollTo
  globalThis.ResizeObserver ??= class { observe() {} unobserve() {} disconnect() {} } as unknown as typeof ResizeObserver
})

const FIN = (t: string) => `fin:US-${t}:roe_ttm:2026-10-29`
const company = (t: string, name: string, roe: number, text: string[]): CompanyItem => ({ ticker: t, name, market: "US", sector: "IT", sub_industry: "반도체", summary: "", theme_reason_ko: `${name} 테마 이유`, theme_confidence: 0.9, weight: 0.3, in_selection_now: true, rank_now: 1, metric_now: roe, in_backtest: true, rank_bt: 1, metric_bt: roe, fact_id: FIN(t), rationale_ko: text, evidence_ids: [FIN(t)], n_news: 10, n_disclosures: 1 })
const evidence: EvidenceRecord[] = [
  { id: FIN("AAA"), kind: "financial", title: "AAA ROE", source: "팀 데이터베이스(가치평가)", data_as_of: "2026-10-29", tickers: ["AAA"], value: 0.2725, unit: "ratio" },
  { id: FIN("BBB"), kind: "financial", title: "BBB ROE", source: "팀 데이터베이스(가치평가)", data_as_of: "2026-10-29", tickers: ["BBB"], value: 1.094, unit: "ratio" },
  { id: "ev7", kind: "news", title: "Alpha Q3 EPS Beats Estimate", source: "benzinga", url: "https://example.com/news", published_at: "2026-10-20", tickers: ["AAA"], language: "en" },
  { id: "dc3", kind: "disclosure", title: "8-K 2.05 · 구조조정", source: "SEC EDGAR", url: "https://example.com/8k", available_on: "2026-10-24", filed_at: "2026-10-24", event_label_ko: "구조조정", form: "8-K", items: "2.05", tickers: ["AAA"] },
  { id: "calc:max_drawdown:equal_weight", kind: "calc", title: "동일비중 최대낙폭", source: "백테스트 계산", data_as_of: "2026-10-30", tickers: [], value: -0.288, unit: "ratio" },
]
const AAA_TEXT = "알파는 반도체를 만듭니다. 필수 포함으로 담았고 ROE는 27.3%입니다 [fin:US-AAA:roe_ttm:2026-10-29]. 최근 실적도 예상보다 좋았습니다 [ev7]."
const doc = (): ReportDoc => ({
  request_id: "req_1", run_id: "run_1", stage: "", generated_at: "2026-11-01", source: "",
  header: { title_ko: "반도체 전략", subtitle_ko: "요청 요약", created_at: "2026-11-01", selection_as_of: "2026-10-30", backtest_period: { start: "2023-10-30", end: "2026-10-30", as_of: "2023-10-30" }, data_as_of: "2026-10-30", chosen_portfolio_id: "equal_weight", chosen_label_ko: "동일비중", chosen_note_ko: "", disclaimer_ko: "면책 문구" },
  kpis: [], nav: [{ id: "companies", title_ko: "기업별 투자 근거" }],
  sections: [{ id: "companies", title_ko: "기업별 투자 근거", blocks: [
    { type: "paragraphs", items: ["선정된 알파의 ROE는 27.3%, 베타는 109.4%였습니다 [fin:US-AAA:roe_ttm:2026-10-29] [fin:US-BBB:roe_ttm:2026-10-29]. 가장 크게 떨어진 폭은 28.8%였습니다 [calc:max_drawdown:equal_weight]."] },
    { type: "companies", title_ko: "선정 종목", metric: "roe_ttm", metric_ko: "퀄리티", direction: "desc", as_of_now: "2026-10-30", as_of_bt: "2023-10-30", portfolio_id: "equal_weight", items: [
      company("AAA", "Alpha Inc.", 0.2725, [AAA_TEXT]), company("BBB", "Beta Corp", 1.094, ["베타 설명 [fin:US-BBB:roe_ttm:2026-10-29]."]), company("CCC", "Gamma", 0.6, []),
    ] },
  ] }],
  datasets: { dates: ["2023-10-30", "2026-10-30"], series: { equal_weight: { label_ko: "동일비중", kind: "template", index: [100, 140] } } },
  assessment: { intent_fit: null, logic_consistency: null, comments_ko: [] }, evidence, execution: [], tracking: { eligible: true, reason_ko: null }, sources: [], parameters: {}, warnings: [],
  doc_version: 2, summary: null, evidence_summary: { total: 1191, cited: 5, by_kind: { news: 1005, disclosure: 87, financial: 14, calc: 85 } },
})
const service = (d: ReportDoc, over: Partial<AnalysisService> = {}) => ({
  getReport: vi.fn(async () => d), getReportComparison: vi.fn(async () => { throw new Error("none") }), getRequest: vi.fn(async () => ({ idea: "", questions: [], revision: null, conditions: [], confirmation: { rows: [] } })),
  getReportEvidence: vi.fn(async () => null), getReportEvidenceOne: vi.fn(async () => null), getReportCheckpoint: vi.fn(async () => null), listReports: vi.fn(async () => []), ...over,
}) as unknown as AnalysisService

describe("근거 글자", () => {
  it("숫자는 본문과 같은 단위로, 뜻은 쉬운 한 문장으로 쓴다. 모르는 지표는 지어내지 않는다", () => {
    const [aaa, , news, disc, dd] = evidence
    expect(finParts(aaa.id)).toEqual({ ticker: "AAA", metric: "roe_ttm", date: "2026-10-29" })
    expect([evidenceValue(aaa), evidenceValue(dd), evidenceValue({ id: "fin:US-X:pe_ttm:2026-10-29", kind: "financial", value: 18.234, unit: "ratio" }), evidenceValue({ id: "calc:sharpe:x", kind: "calc", value: 2.139, unit: "ratio" }), evidenceValue({ id: "calc:final_value_usd:x", kind: "calc", value: 37599.17, unit: "usd" }), evidenceValue(news)])
      .toEqual(["27.3%", "-28.8%", "18.23배", "2.14", "37,599.17 USD", null])
    expect(evidencePlain(aaa)).toBe("자기 돈(자기자본) 100원으로 1년 동안 27원을 벌었다는 뜻입니다.")
    expect(evidencePlain(dd)).toBe("가장 높았던 때보다 28.8%까지 내려간 적이 있다는 뜻입니다.")
    expect(evidencePlain({ id: "fin:US-X:return_12m_1m:2026-10-29", kind: "financial", value: -0.125, unit: "ratio" })).toBe("최근 1년 동안(가장 최근 한 달은 빼고) 주가가 12.5% 내렸다는 뜻입니다.")
    expect(evidencePlain({ id: "fin:US-X:unknown_metric:2026-10-29", kind: "financial", value: 1, unit: "ratio" })).toBeNull()
    expect(evidencePlain(news)).toBeNull()
    const nameOf = companyNames(doc())
    expect([evidenceTitle(aaa, nameOf), evidenceTitle(news, nameOf), evidenceTitle(disc, nameOf), evidenceTitle(dd, nameOf)]).toEqual(["Alpha Inc. ROE 27.3%", "Alpha Q3 EPS Beats Estimate", "구조조정 (Alpha Inc.)", "동일비중 최대낙폭 -28.8%"])
  })
  it("긴 글에서는 그 근거 번호가 붙은 문장만 꺼내고, 같은 지표의 다른 회사 값을 좋은 순으로 견준다", () => {
    expect(sentenceFor(AAA_TEXT, FIN("AAA"))).toBe("필수 포함으로 담았고 ROE는 27.3%입니다 [fin:US-AAA:roe_ttm:2026-10-29].")
    expect(sentenceFor(AAA_TEXT, "ev7")).toBe("최근 실적도 예상보다 좋았습니다 [ev7].")
    expect(sentenceFor("번호가 없는 글.", "ev7")).toBe("번호가 없는 글.")
    // 번호가 문단 끝의 풀이 문장에 붙어 있어도, 숫자 근거는 그 숫자가 적힌 문장을 고른다
    expect(sentenceFor("필수 포함으로 담았습니다. ROE는 27.3%이며 순위는 매기지 않았습니다. ROE는 이익의 정도를 보여 줍니다 [x].", "x", "27.3%")).toBe("ROE는 27.3%이며 순위는 매기지 않았습니다.")
    const p3 = peersOf(doc(), FIN("AAA"))!
    expect([rankText(p3), rankText({ ...p3, rank: 1 }), rankText({ ...p3, rank: 2 }), rankText({ ...p3, direction: "asc", rank: 1 })]).toEqual(["담은 회사 3개 가운데 가장 낮습니다", "담은 회사 3개 가운데 가장 높습니다", "담은 회사 3개 가운데 2번째로 높습니다", "담은 회사 3개 가운데 가장 낮습니다"])
    expect(peersOf(doc(), FIN("AAA"))).toMatchObject({ metricKo: "ROE", direction: "desc", rank: 3, items: [{ name: "Beta Corp", text: "109.4%", me: false }, { name: "Gamma", text: "60.0%", me: false }, { name: "Alpha Inc.", text: "27.3%", me: true }] })
    expect(peersOf(doc(), "ev7")).toBeNull()
  })
})

describe("근거 패널 · 기업 카드의 근거 묶음", () => {
  it("기업 카드 안에 본문이 쓴 근거(숫자 · 공시 · 뉴스)가 번호와 함께 있고, 읽기만 한 자료는 「모두 보기」로 연다", async () => {
    render(<ServiceContext.Provider value={service(doc())}><ReportDetail reportId="run_1" sec="companies" company="AAA" /></ServiceContext.Provider>)
    const list = await screen.findByRole("list", { name: "AAA 근거 자료" }, { timeout: 5000 })
    expect(within(list).getAllByRole("listitem").map((li) => li.textContent)).toEqual(["[1]Alpha Inc. ROE 27.3%재무 숫자 · 2026-10-29", "구조조정 (Alpha Inc.)공시 · 2026-10-24", "[4]Alpha Q3 EPS Beats Estimate뉴스 제목 · 2026-10-20"])
    fireEvent.click(screen.getAllByRole("button", { name: "읽은 뉴스 10건 · 공시 1건 모두 보기" })[0])
    const drawer = await screen.findByRole("dialog", { name: "Alpha Inc. 관련 자료" })
    expect(within(drawer).getByRole("radio", { name: /읽은 자료 전체/ })).toHaveAttribute("aria-checked", "true")
  })
  it("문장의 번호를 누르면: 그 문장 → 숫자와 쉬운 뜻 → 다른 회사와 견준 막대 → 같은 근거를 쓴 다른 문장. 자료 ID 는 접힌 「자료 정보」에만 있다", async () => {
    render(<ServiceContext.Provider value={service(doc())}><ReportDetail reportId="run_1" sec="companies" company="AAA" /></ServiceContext.Provider>)
    const card = await screen.findByRole("list", { name: "AAA 근거 자료" }, { timeout: 5000 })
    const body = card.closest("li")!
    fireEvent.click(within(body).getAllByRole("button", { name: `근거 ${FIN("AAA")} 보기` })[0])   // 선정 근거 문단의 [1]
    const panel = await screen.findByRole("dialog", { name: "근거 자세히" })
    const lead = within(panel).getByRole("region", { name: "이 근거가 뒷받침하는 문장" })
    expect(lead.textContent).toBe("이 문장의 근거입니다필수 포함으로 담았고 ROE는 27.3%입니다[1].AAA · Alpha Inc.")   // 긴 문단에서 그 문장만, 번호는 [1] 로
    const content = within(panel).getByRole("region", { name: "근거 내용" })
    expect(content.textContent).toBe("[1]재무 숫자 · 2026-10-29Alpha Inc. · ROE27.3%자기 돈(자기자본) 100원으로 1년 동안 27원을 벌었다는 뜻입니다.")
    expect(within(panel).getByRole("heading", { name: "담은 회사 3개 가운데 가장 낮습니다" })).toBeInTheDocument()
    expect(within(within(panel).getByRole("region", { name: "같은 지표로 견준 회사" })).getAllByRole("listitem").map((li) => li.textContent)).toEqual(["Beta Corp109.4%", "Gamma60.0%", "Alpha Inc.27.3%"])
    expect(within(panel).getByRole("heading", { name: /같은 근거를 쓴 다른 문장/ }).textContent).toBe("같은 근거를 쓴 다른 문장 1")
    expect(panel.textContent).not.toContain("fin:US-")   // 내부 ID 는 보이지 않는다
    fireEvent.click(within(panel).getByRole("button", { name: /자료 정보/ }))
    expect(within(panel).getByText(FIN("AAA"))).toBeInTheDocument()
    expect(within(panel).getByText("팀 데이터베이스(가치평가)")).toBeInTheDocument()
  })
  it("뉴스·공시는 제목·사건과 회사 이름을 보여 주고 「원문 열기」를 둔다", async () => {
    render(<ServiceContext.Provider value={service(doc())}><ReportDetail reportId="run_1" sec="companies" company="AAA" /></ServiceContext.Provider>)
    const list = await screen.findByRole("list", { name: "AAA 근거 자료" }, { timeout: 5000 })
    fireEvent.click(within(list).getByRole("button", { name: /구조조정/ }))
    let panel = await screen.findByRole("dialog", { name: "근거 자세히" })
    expect(within(panel).getByRole("region", { name: "근거 내용" }).textContent).toBe("공시 · 2026-10-24Alpha Inc.구조조정원문 열기")   // 본문 문장에 번호로 붙지 않은 자료는 번호가 없다
    expect(within(panel).getByText("본문 문장에 번호로 붙지 않은 자료입니다. 표와 투자 의견을 만들 때 참고했습니다.")).toBeInTheDocument()
    fireEvent.click(within(panel).getByRole("button", { name: "닫기" }))
    fireEvent.click(within(list).getByRole("button", { name: /Alpha Q3 EPS/ }))
    panel = await screen.findByRole("dialog", { name: "근거 자세히" })
    expect(within(panel).getByRole("region", { name: "근거 내용" }).textContent).toBe("[4]뉴스 제목 · 2026-10-20 · benzingaAlpha Q3 EPS Beats Estimate관련 회사: Alpha Inc.원문 열기")
    expect(within(panel).getByRole("link", { name: /원문 열기/ })).toHaveAttribute("href", "https://example.com/news")
    expect(within(panel).getByRole("region", { name: "이 근거가 뒷받침하는 문장" }).textContent).toContain("최근 실적도 예상보다 좋았습니다")
  })
})

describe("출처 목록", () => {
  const ctx = (d: ReportDoc): ReportCtx => ({ reportId: "run_1", doc: d, numberOf: (id) => (id === FIN("AAA") ? "1" : id), openEvidence: () => {}, openDrawer: () => {}, jump: () => {}, selectedRb: null, setSelectedRb: () => {}, openCompany: null, setOpenCompany: () => {} })
  it("처음에는 본문에 쓰인 근거만 청하고, 「읽은 자료 전체」를 고르면 전체를 청한다", async () => {
    const d = doc()
    const getReportEvidence = vi.fn(async (_id: string, q?: { ids?: string[] }) => ({ total: q?.ids ? 5 : 1191, offset: 0, limit: 50, index_total: 1191, by_kind: {}, items: q?.ids ? evidence : [{ id: "ev999", kind: "news", title: "읽기만 한 뉴스", source: "s", tickers: ["AAA"] }] }))
    render(<ServiceContext.Provider value={service(d, { getReportEvidence } as unknown as Partial<AnalysisService>)}><ReportContext.Provider value={ctx(d)}><SourceDrawer filter={{ ids: null, title: "출처 전체" }} close={() => {}} onOpen={() => {}} /></ReportContext.Provider></ServiceContext.Provider>)
    await waitFor(() => expect(screen.getByText("Alpha Inc. ROE 27.3%")).toBeInTheDocument())
    expect(getReportEvidence).toHaveBeenLastCalledWith("run_1", expect.objectContaining({ ids: evidence.map((e) => e.id) }))
    expect(screen.getByRole("radio", { name: "본문에 쓰인 근거5" })).toHaveAttribute("aria-checked", "true")
    expect(screen.getByRole("radio", { name: "읽은 자료 전체1,191" })).toHaveAttribute("aria-checked", "false")
    expect(screen.getAllByRole("listitem")[0].textContent).toBe("[1]Alpha Inc. ROE 27.3%재무 숫자 · 2026-10-29")   // 번호 · 내용 · 종류 · 날짜 (자료 ID 는 보이지 않는다)
    fireEvent.click(screen.getByRole("radio", { name: /읽은 자료 전체/ }))
    await waitFor(() => expect(screen.getByText("읽기만 한 뉴스")).toBeInTheDocument())
    expect(getReportEvidence).toHaveBeenLastCalledWith("run_1", expect.objectContaining({ ids: undefined }))
  })
})
