// Types for module_mockup/output/14_report.json (published to /pipeline/report.json)
export type Format = "usd" | "krw" | "pct" | "pct1" | "pp" | "num" | "int" | "ratio" | "text" | "index" | "url"

export interface Kpi { id: string; label_ko: string; value: number | null; format: Format; note_ko?: string }
export interface Column { key: string; label_ko: string; format?: Format }

export interface ParagraphsBlock { type: "paragraphs"; items: string[]; tone?: "lead" }
export interface KpisBlock { type: "kpis"; ids: string[] }
export interface TableBlock { type: "table"; title_ko?: string; columns: Column[]; rows: Record<string, unknown>[]; note_ko?: string }
export interface DonutBlock { type: "donut"; title_ko: string; items: { label: string; value: number }[]; note_ko?: string }
export interface LineBlock { type: "line"; title_ko: string; dataset: "index" | "value_usd"; series_ids: string[]; default_on: string[]; y_format: Format; note_ko?: string }
export interface AreaBlock { type: "area"; title_ko: string; dataset: "drawdown"; series_ids: string[]; default_on: string[]; y_format: Format }
export interface BarBlock { type: "bar"; title_ko: string; items: { label: string; value: number }[]; format: Format; note_ko?: string }
export interface FunnelBlock { type: "funnel"; items: { label_ko: string; count: number; note_ko?: string }[] }
export interface CalloutBlock { type: "callout"; tone: "info" | "caution"; title_ko: string; text_ko: string }
export interface CardsBlock { type: "cards"; title_ko?: string; items: { title_ko: string; text_ko: string; meta: { label_ko: string; value: string }[] }[] }
export interface Holding { ticker: string; shares_after: number; price: number; value_usd: number; weight_before: number | null; weight_after: number; period_return: number; period_contribution: number }
export interface CheckpointItem {
  seq: number; date: string; kind: "rebalance" | "closing" | "monthly"; n_trading_days_to_date: number
  weights_before: Record<string, number> | null; weights_after: Record<string, number>; weights_target: Record<string, number>
  holdings: Holding[]; since_last: Record<string, unknown> | null; to_date: Record<string, unknown> | null
  n_trades: number; commission_usd: number; value_usd: number; benchmark_value_usd: number | null; net_invested_usd: number; drift: Record<string, unknown> | null
}
export interface CheckpointsBlock { type: "checkpoints"; title_ko: string; portfolio_id: string; items: CheckpointItem[] }
export interface GlossaryBlock { type: "glossary"; items: { term: string; explain_ko: string }[] }

export type Block = ParagraphsBlock | KpisBlock | TableBlock | DonutBlock | LineBlock | AreaBlock | BarBlock | FunnelBlock | CalloutBlock | CardsBlock | CheckpointsBlock | GlossaryBlock

export interface Section { id: string; title_ko: string; blocks: Block[] }
export interface Series { label_ko: string; kind: string; index?: number[]; value_usd?: number[]; drawdown?: number[] }

export interface ReportDoc {
  request_id: string; stage: string; generated_at: string; source: string
  header: { title_ko: string; subtitle_ko: string; created_at: string; selection_as_of: string; backtest_period: { start: string; end: string; as_of: string }; data_as_of: string; chosen_portfolio_id: string; chosen_label_ko: string; chosen_note_ko: string; disclaimer_ko: string }
  kpis: Kpi[]; nav: { id: string; title_ko: string }[]; sections: Section[]
  datasets: { dates: string[]; series: Record<string, Series> }
  assessment: { intent_fit: number | null; logic_consistency: number | null; comments_ko: string[] }
  sources: { id: string; name: string; what: string; url: string | null }[]; parameters: Record<string, unknown>; warnings: string[]
}
