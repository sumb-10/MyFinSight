import { describe, expect, it } from "vitest"
import { citationNumbers, citedIn, collectCitations, findCitations, kindOf } from "./citations"
import type { ReportDoc } from "../api/types"

const doc = { sections: [
  { id: "verdict", title_ko: "판단", blocks: [{ type: "paragraphs", items: ["첫 문장 [calc:cagr:x].", "둘째 [ev2] 와 [fin:US-NVDA:pe_ttm:2025-12-30]."] }] },
  { id: "market", title_ko: "시장", blocks: [{ type: "cards", title_ko: "카드", items: [{ title_ko: "a", text_ko: "공시 [dc7] 와 다시 [ev2]", meta: [] }] },
    { type: "companies", title_ko: "기업", metric: "m", metric_ko: "모멘텀", direction: "desc", as_of_now: "", as_of_bt: "", portfolio_id: "p", items: [{ ticker: "NVDA", name: "엔비디아", market: "US", sector: "IT", sub_industry: "", summary: "", theme_reason_ko: "", theme_confidence: 0.9, weight: 0.3, in_selection_now: true, rank_now: 1, metric_now: 0.1, in_backtest: true, rank_bt: 1, metric_bt: 0.1, fact_id: "fin:US-NVDA:return_12m_1m:2025-12-30", rationale_ko: ["근거 [dc9]"], evidence_ids: ["dc9"], n_news: 1, n_disclosures: 1 }] },
    { type: "timeline", title_ko: "t", portfolio_id: "p", walkforward: true, items: [{ seq: 0, date: "2024-01-02", kind: "rebalance", n_trading_days_to_date: 0, value_usd: 1, benchmark_value_usd: 1, net_invested_usd: 1, since_last: null, n_trades: 1, turnover: null, commission_usd: 0, to_date: null, cash_after: 0, news: null, views: [{ summary_ko: "뷰", confidence: 0.3, evidence_ids: ["ev5", "dc7"] }], top_delta: [] }] }] },
] } as unknown as Pick<ReportDoc, "sections">

describe("citations", () => {
  it("인용 ID 네 종류를 찾고 종류를 가른다", () => {
    expect(findCitations("a [ev1] b [dc2] c [fin:US-A:pe_ttm:2025-01-01] d [calc:cagr:p] e [zz9]")).toEqual(["ev1", "dc2", "fin:US-A:pe_ttm:2025-01-01", "calc:cagr:p"])
    expect(["ev1", "dc2", "fin:x", "calc:y", "q"].map(kindOf)).toEqual(["news", "disclosure", "financial", "calc", "unknown"])
  })
  it("읽는 순서로 번호를 매기고 중복은 한 번만", () => {
    expect(collectCitations(doc)).toEqual(["calc:cagr:x", "ev2", "fin:US-NVDA:pe_ttm:2025-12-30", "dc7", "dc9", "fin:US-NVDA:return_12m_1m:2025-12-30", "ev5"])
    expect(citationNumbers(doc).get("dc7")).toBe(4)
  })
  it("근거를 인용한 문장을 섹션·블록 제목과 함께 돌려준다", () => {
    const hits = citedIn(doc, "ev2")
    expect(hits.map((h) => h.section_id)).toEqual(["verdict", "market"])
    expect(citedIn(doc, "dc9")[0].block_title_ko).toBe("NVDA · 엔비디아")
    expect(citedIn(doc, "dc7").map((h) => h.block_title_ko)).toEqual(["a", "2024-01-02 뷰"])
    expect(citedIn(doc, "nope")).toEqual([])
  })
})
