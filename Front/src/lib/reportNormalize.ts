import type { Block, CheckpointsBlock, DonutBlock, EvidenceBlock, ReportDoc, ReportSummary, TableBlock, TimelineBlock } from "../api/types"

/** 저장된 v1 문서(라운드 3 이전)를 v2 화면이 그릴 수 있게 바꾼다. v2 문서는 그대로 돌려준다 (같은 객체). 서버의 present_doc 과 같은 규칙. */
export function normalizeDoc(doc: ReportDoc): ReportDoc {
  if ((doc.doc_version ?? 1) >= 2 && doc.summary) return doc
  const evidence = doc.evidence ?? []
  const byId = new Map(evidence.map((e) => [e.id, e]))
  const sections = doc.sections.map((s) => ({ ...s, blocks: s.blocks.map((b) => convertBlock(b, byId.size)) }))
  const out: ReportDoc = { ...doc, sections, doc_version: doc.doc_version ?? 1 }
  if (!out.summary) out.summary = deriveSummary(out)
  if (!out.evidence_summary) {
    const by_kind: Record<string, number> = {}
    for (const e of evidence) by_kind[e.kind] = (by_kind[e.kind] ?? 0) + 1
    out.evidence_summary = { total: evidence.length, cited: evidence.length, by_kind }
  }
  return out
}

function convertBlock(b: Block, total: number): Block {
  if (b.type === "evidence") {
    const e = b as EvidenceBlock
    const ids = e.items.map((x) => x.id)
    const kinds: Record<string, number> = {}
    for (const x of e.items) kinds[x.kind] = (kinds[x.kind] ?? 0) + 1
    const full = total > 0 && ids.length >= total && total > 3  // 색인 전체를 복사한 참고자료 블록만 '전체' 로 (작은 색인은 그대로 id 목록)
    return { type: "evidence_ref", title_ko: e.title_ko, ids: full ? null : ids, count: ids.length, kinds }
  }
  if (b.type === "checkpoints") return checkpointsToTimeline(b as CheckpointsBlock)
  return b
}

export function checkpointsToTimeline(b: CheckpointsBlock): TimelineBlock {
  const pick = (o: Record<string, unknown> | null, keys: string[]) => (o ? Object.fromEntries(keys.map((k) => [k, (o[k] as number | null | undefined) ?? null])) : null)
  return {
    type: "timeline", title_ko: b.title_ko, portfolio_id: b.portfolio_id, walkforward: false,
    items: b.items.map((cp) => ({
      seq: cp.seq, date: cp.date, kind: cp.kind, n_trading_days_to_date: cp.n_trading_days_to_date, value_usd: cp.value_usd, benchmark_value_usd: cp.benchmark_value_usd, net_invested_usd: cp.net_invested_usd,
      since_last: pick(cp.since_last, ["return", "benchmark_return", "excess", "max_drawdown"]), n_trades: cp.n_trades, turnover: null, commission_usd: cp.commission_usd,
      to_date: pick(cp.to_date, ["total_return", "cagr", "max_drawdown", "sharpe", "excess_cagr"]), cash_after: null, news: null, views: [], top_delta: [],
    })),
    note_ko: "예전 형식의 리포트라 리밸런싱일의 뉴스·뷰 정보는 없습니다.",
  }
}

/** v1 문서에서 요약 대시보드 자료를 만든다 (있는 것만; 없는 항목은 null). */
export function deriveSummary(doc: ReportDoc): ReportSummary {
  const h = doc.header
  const status: ReportSummary["verdict"]["status"] = h.chosen_note_ko.includes("추천된") ? "recommended" : h.chosen_note_ko.includes("현금 혼합") ? "none_cash_blend" : "none_baseline"
  const blocks = doc.sections.flatMap((s) => s.blocks.map((b) => ({ sec: s.id, b })))
  const lead = blocks.find((x) => x.b.type === "paragraphs" && x.b.tone === "lead")?.b
  const headline = lead && lead.type === "paragraphs" ? (lead.items[0] ?? "") : ""
  const rec = blocks.find((x) => x.b.type === "cards" && x.b.title_ko === "검증 결과")?.b
  let n_pass = 0, n_warn = 0, n_fail = 0
  if (rec && rec.type === "cards") {
    const m = /(\d+)\/(\d+)\/(\d+)/.exec(rec.items[0]?.meta.find((x) => x.label_ko.includes("통과"))?.value ?? "")
    if (m) [n_pass, n_warn, n_fail] = [Number(m[1]), Number(m[2]), Number(m[3])]
  }
  const next = blocks.find((x) => x.b.type === "cards" && (x.b.title_ko ?? "").startsWith("다음에 검토"))?.b
  const alloc = blocks.find((x) => x.sec === "construction" && x.b.type === "table" && (x.b.title_ko ?? "").startsWith("배분 금액"))?.b as TableBlock | undefined
  const donut = blocks.find((x) => x.sec === "construction" && x.b.type === "donut")?.b as DonutBlock | undefined
  const items = alloc
    ? alloc.rows.filter((r) => r.ticker !== "현금").map((r) => ({ ticker: String(r.ticker), name: String(r.name ?? ""), sector: String(r.sector ?? ""), weight: Number(r.w ?? 0), usd: Number(r.usd ?? 0), krw: Number(r.krw ?? 0) }))
    : donut ? donut.items.map((x) => ({ ticker: x.label, name: "", sector: "", weight: x.value, usd: 0, krw: 0 })) : []
  const cash = alloc ? Number(alloc.rows.find((r) => r.ticker === "현금")?.w ?? 0) : Math.max(0, 1 - items.reduce((s, x) => s + x.weight, 0))
  const bench = Object.entries(doc.datasets.series).find(([, s]) => s.kind === "benchmark")?.[0]
  return {
    verdict: { status, label_ko: status === "recommended" ? `추천: ${h.chosen_label_ko}` : status === "none_cash_blend" ? `추천 없음 · 현금 혼합안 (${h.chosen_label_ko})` : `추천 없음 · 기준 포트폴리오 (${h.chosen_label_ko})`, headline_ko: headline, reason_ko: rec && rec.type === "cards" ? rec.items[0]?.text_ko : null, chosen_portfolio_id: h.chosen_portfolio_id, chosen_label_ko: h.chosen_label_ko },
    validation: { n_pass, n_warn, n_fail, chosen_status: status === "recommended" ? "pass" : "n/a", failed_rules_ko: [] },
    kpis: doc.kpis.filter((k) => !(k.id === "view_hit" && k.value === null)).map((k) => ({ ...k, benchmark_value: null, benchmark_label_ko: null })),
    allocation: items.length ? { basis: "backtest", basis_ko: `백테스트 선택안 (${h.chosen_label_ko})`, items, cash_weight: cash, initial_amount_usd: items.reduce((s, x) => s + x.usd, 0) || 0, fx_rate: items[0]?.usd ? items[0].krw / items[0].usd : 0 } : null,
    mini_series: { dataset: "index", ids: bench ? [h.chosen_portfolio_id, bench] : [h.chosen_portfolio_id] },
    period: h.backtest_period, next_actions_ko: next && next.type === "cards" ? next.items.map((it) => it.text_ko) : [],
  }
}

/** 연속된 블록 중 group_ko 가 같은 것을 한 묶음으로. 묶음이 없는 블록은 group 없이 하나씩. */
export function groupBlocks(blocks: Block[]): { group_ko?: string; open?: boolean; blocks: Block[] }[] {
  const out: { group_ko?: string; open?: boolean; blocks: Block[] }[] = []
  for (const b of blocks) {
    const last = out[out.length - 1]
    if (b.group_ko && last && last.group_ko === b.group_ko) { last.blocks.push(b); if (b.group_open) last.open = true; continue }
    out.push(b.group_ko ? { group_ko: b.group_ko, open: !!b.group_open, blocks: [b] } : { blocks: [b] })
  }
  return out
}
