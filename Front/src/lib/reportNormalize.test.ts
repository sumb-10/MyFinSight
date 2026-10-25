import { describe, expect, it } from "vitest"
import { groupBlocks, normalizeDoc } from "./reportNormalize"
import type { Block, ReportDoc } from "../api/types"

const base = (): ReportDoc => ({
  request_id: "r", run_id: "run_1", stage: "14_report", generated_at: "2026-01-01T00:00:00", source: "13_results",
  header: { title_ko: "t", subtitle_ko: "s", created_at: "2026-01-01", selection_as_of: "2025-12-31", backtest_period: { start: "2023-01-02", end: "2025-12-31", as_of: "2023-01-02" }, data_as_of: "2025-12-31", chosen_portfolio_id: "bl_1", chosen_label_ko: "뉴스 뷰: A", chosen_note_ko: "검증 결과 추천된 포트폴리오입니다.", disclaimer_ko: "d" },
  kpis: [{ id: "cagr", label_ko: "CAGR", value: 0.1, format: "pct" }, { id: "view_hit", label_ko: "적중", value: null, format: "pct" }], nav: [{ id: "verdict", title_ko: "판단" }, { id: "construction", title_ko: "구성" }],
  sections: [
    { id: "verdict", title_ko: "판단", blocks: [{ type: "paragraphs", items: ["한 줄 판단 [calc:cagr:bl_1]"], tone: "lead" }, { type: "cards", title_ko: "검증 결과", items: [{ title_ko: "추천: A", text_ko: "이유", meta: [{ label_ko: "통과/주의/미통과", value: "3/2/1" }] }] }] },
    { id: "construction", title_ko: "구성", blocks: [
      { type: "table", title_ko: "배분 금액 (A)", columns: [{ key: "ticker", label_ko: "t" }], rows: [{ ticker: "NVDA", name: "엔비디아", sector: "IT", w: 0.6, usd: 600, krw: 840000 }, { ticker: "AMD", name: "AMD", sector: "IT", w: 0.3, usd: 300, krw: 420000 }, { ticker: "현금", name: "", sector: "", w: 0.1, usd: 100, krw: 140000 }] },
      { type: "checkpoints", title_ko: "체크포인트", portfolio_id: "bl_1", items: [{ seq: 0, date: "2023-01-02", kind: "rebalance", n_trading_days_to_date: 0, weights_before: null, weights_after: { NVDA: 0.6 }, weights_target: { NVDA: 0.6 }, holdings: [], since_last: null, to_date: null, n_trades: 2, commission_usd: 1, value_usd: 1000, benchmark_value_usd: 1000, net_invested_usd: 1000, drift: null }] },
      { type: "evidence", title_ko: "근거", items: [{ id: "ev1", kind: "news", title: "n", source: "s", tickers: ["NVDA"] }] },
      { type: "cards", title_ko: "다음에 검토할 수 있는 선택지", items: [{ title_ko: "선택지 1", text_ko: "종목 수 조정", meta: [] }] },
    ] },
  ],
  datasets: { dates: ["2023-01-02"], series: { bl_1: { label_ko: "A", kind: "black_litterman", index: [100] }, benchmark_SPY: { label_ko: "SPY", kind: "benchmark", index: [100] } } },
  assessment: { intent_fit: null, logic_consistency: null, comments_ko: [] }, evidence: [{ id: "ev1", kind: "news", title: "n", source: "s", tickers: ["NVDA"] }, { id: "calc:cagr:bl_1", kind: "calc", title: "c", source: "s", tickers: [] }],
  execution: [], tracking: { eligible: true, reason_ko: null }, sources: [], parameters: {}, warnings: [],
})

describe("normalizeDoc", () => {
  it("v1 문서: evidence 블록 → evidence_ref, checkpoints → timeline, summary 유도", () => {
    const out = normalizeDoc(base())
    const types = out.sections.flatMap((s) => s.blocks.map((b) => b.type))
    expect(types).not.toContain("evidence"); expect(types).not.toContain("checkpoints"); expect(types).toContain("evidence_ref"); expect(types).toContain("timeline")
    const ref = out.sections[1].blocks.find((b) => b.type === "evidence_ref")
    expect(ref && ref.type === "evidence_ref" && ref.ids).toEqual(["ev1"])
    const tl = out.sections[1].blocks.find((b) => b.type === "timeline")
    expect(tl && tl.type === "timeline" && tl.items[0]).toMatchObject({ seq: 0, date: "2023-01-02", n_trades: 2, views: [], news: null })
    const sm = out.summary!
    expect(sm.verdict.status).toBe("recommended"); expect(sm.verdict.headline_ko).toContain("한 줄 판단"); expect(sm.validation).toMatchObject({ n_pass: 3, n_warn: 2, n_fail: 1 })
    expect(sm.kpis.map((k) => k.id)).toEqual(["cagr"])  // 값 없는 적중률은 숨김
    expect(sm.allocation!.items.map((i) => i.ticker)).toEqual(["NVDA", "AMD"]); expect(sm.allocation!.cash_weight).toBeCloseTo(0.1)
    expect(sm.mini_series!.ids).toEqual(["bl_1", "benchmark_SPY"]); expect(sm.next_actions_ko).toEqual(["종목 수 조정"])
    expect(out.evidence_summary).toEqual({ total: 2, cited: 2, by_kind: { news: 1, calc: 1 } })
  })
  it("v2 문서는 그대로 (같은 객체)", () => {
    const v2 = { ...base(), doc_version: 2, summary: { verdict: { status: "recommended", label_ko: "x", headline_ko: "h", chosen_portfolio_id: "bl_1", chosen_label_ko: "A" }, validation: { n_pass: 1, n_warn: 0, n_fail: 0, chosen_status: "pass", failed_rules_ko: [] }, kpis: [], allocation: null, mini_series: null, next_actions_ko: [] } } as ReportDoc
    expect(normalizeDoc(v2)).toBe(v2)
  })
  it("groupBlocks: 연속된 같은 묶음만 합친다", () => {
    const blocks = [{ type: "callout", tone: "info", title_ko: "a", text_ko: "x" }, { type: "callout", tone: "info", title_ko: "b", text_ko: "x", group_ko: "G" }, { type: "callout", tone: "info", title_ko: "c", text_ko: "x", group_ko: "G", group_open: true }, { type: "callout", tone: "info", title_ko: "d", text_ko: "x" }, { type: "callout", tone: "info", title_ko: "e", text_ko: "x", group_ko: "G" }] as Block[]
    const g = groupBlocks(blocks)
    expect(g.map((x) => [x.group_ko ?? null, x.blocks.length, x.open ?? null])).toEqual([[null, 1, null], ["G", 2, true], [null, 1, null], ["G", 1, false]])
  })
})
