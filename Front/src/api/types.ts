// 백엔드(backend/analysis) Pydantic 모델을 snake_case 그대로 미러한 DTO.
// 단위 계약: 비율·비중·수익률은 분수(0.12 = 12%), 금액은 명시된 통화, 날짜는 ISO(YYYY-MM-DD).
export const API_CONTRACT_VERSION = "1"

export type Format = "usd" | "krw" | "pct" | "pct1" | "pp" | "num" | "int" | "ratio" | "text" | "index" | "url"

// ───────────────────────── 요청 모델 (schemas/request.py) ─────────────────────────
export type Universe = "SP500" | "NASDAQ100" | "KOSPI200"
export type Template = "low_per" | "quality" | "momentum" | "low_volatility" | "high_dividend"
export type Weighting = "equal_weight" | "market_cap" | "inverse_volatility" | "min_variance"
export type RiskTolerance = "conservative" | "moderate" | "aggressive"
export type RebalanceUnit = "2w" | "1m" | "1q" | "6m" | "1y"

export interface RequestProfile { user_id?: string; age_band: "20s" | "30s" | "40s" | "50s" | "60s+"; investment_experience: "none" | "beginner" | "intermediate" | "advanced"; financial_knowledge: "basic" | "intermediate" | "expert"; investable_ratio_of_assets: number }
export interface Capital { initial_amount: number; currency: "KRW" | "USD"; trading_currency?: "USD"; monthly_contribution: number; contribution_day: number }
export interface Horizon { start_date?: string | null; target_years: number; purpose: "wealth_growth" | "income" | "capital_preservation" | "retirement"; backtest_years: number }
export interface Risk { risk_tolerance: RiskTolerance; max_drawdown_tolerance: number; loss_reaction: "sell" | "hold" | "buy_more"; target_annual_return: number; benchmark: string }
export interface NumHoldings { target: number; min: number; max: number }
export interface Rebalance { count: number; unit: RebalanceUnit }
export interface Constraints {
  universe: Universe[]; asset_types: ("stock" | "etf")[]; num_holdings: NumHoldings; max_weight_per_stock: number; max_weight_per_sector: number
  min_cash_ratio: number; exclude_tickers: string[]; exclude_sectors: string[]; exclude_themes: string[]; must_include_tickers: string[]; rebalance: Rebalance
  allow_leverage: boolean; allow_short: boolean; min_market_cap_usd: number; min_avg_daily_volume_usd: number
}
export interface StrategyPreference { template: Template; baseline_weighting: Weighting; use_news_tilt: boolean }
export interface UserRequest {
  request_id: string; created_at: string; profile: RequestProfile; capital: Capital; horizon: Horizon; risk: Risk; constraints: Constraints
  strategy_preference: StrategyPreference; natural_language: { idea: string; language: string }
  derived?: Derived
}
export interface Derived {
  as_of: string; fx_rate: number; fx_date: string; fx_source?: string; initial_amount_usd: number; monthly_contribution_usd: number; rebalance_rule: { description_ko: string; enabled: boolean; count: number; unit: RebalanceUnit; warnings?: string[] }; price_data_start: string; price_data_end: string; backtest_start: string; backtest_end: string; markets: string[]; warnings: string[]
  // 백테스트 시작일 환율 (백테스트의 초기 투자금·적립은 이 환율로 환산)
  backtest_fx_rate?: number | null; backtest_fx_date?: string | null; initial_amount_usd_at_backtest_start?: number | null; monthly_contribution_usd_at_backtest_start?: number | null
}

// ───────────────────────── 프로필 (api/routers/profile.py) ─────────────────────────
export type Tendency = "안정형" | "안정추구형" | "위험중립형" | "적극투자형" | "공격투자형"
export interface Diagnosis { answers: Record<string, number>; computed_tendency: Tendency; final_tendency: Tendency; memo?: string }
export interface ProfileFields { profile: RequestProfile; capital: Capital; horizon: Omit<Horizon, "start_date">; risk: Risk; constraints: Constraints; strategy_preference: StrategyPreference; diagnosis?: Diagnosis; risk_type_computed: RiskTolerance; risk_type_overridden: boolean; note?: string }
export interface ProfileVersion extends ProfileFields { version: number; created_at: string }
export interface ProfileView { profile_id: string; current_version: number; profile: ProfileVersion; versions: { version: number; created_at: string; note?: string | null }[] }

// ───────────────────────── 대화 (schemas/dialog.py) ─────────────────────────
export type QuestionKind = "missing" | "conflict" | "ambiguous" | "preference" | "feasibility"  // feasibility = 실행 전 점검(후보 부족·창 축소)
export type DialogStatus = "asking" | "ready" | "blocked" | "confirmed" | "cancelled"
export interface QuestionOption { value: unknown; label_ko: string; patch?: Record<string, unknown> | null; clarification?: string | null }
export interface Question { seq: number; field: string; field_label_ko?: string | null; kind: QuestionKind; question_ko: string; options: QuestionOption[]; allow_free_text: boolean; priority: number; why_ko?: string; asked_at: string; answer?: string | null; applied?: { field: string; value: unknown; patch?: Record<string, unknown> | null; clarification?: string | null } | null; free_text?: string | null; skipped?: boolean; answered_at?: string | null }
export interface FieldError { field: string; message_ko: string }
export interface ConditionRow { field: string; group_ko: string; label_ko: string; value_ko: string; profile_value_ko?: string | null; changed: boolean; source: "profile" | "idea" | "answer" | "default" | "derived"; supported: boolean; note_ko?: string | null }
export interface DialogState {
  request_id: string; mode: "new" | "rerun" | "revision"; base_report_id?: string | null; status: "draft" | "confirmed" | "cancelled"; state: DialogStatus
  turn: number; max_questions: number; idea: string; question: Question | null; questions: Question[]; hard_errors: FieldError[]
  confirmation: { effective_request: UserRequest; rows: ConditionRow[]; all_supported: boolean } | null
  unresolved: { field: string; label_ko: string; hint_ko: string; examples_ko: string[] }[]
  summary: { interpretation_summary_ko?: string | null; themes: { id: string; label_ko: string; description_ko: string }[]; derived?: Derived | null; changed_fields: string[] }
  revision?: RevisionDraft | null; run_id?: string | null; warnings: string[]
  conditions?: ConditionRow[]  // 지금 조건 표 (질문 중에도 온다)
  overrides?: Record<string, unknown>  // 이번 요청에서 직접 바꾼 조건
  blocked_reason_ko?: string | null  // 질문 상한에 닿아 남은 항목을 기본값으로 둔 사유 (state 는 ready)
  precheck?: { min: number; target: number; short_now: boolean; short_at_start: boolean; as_of: { date: string; n_candidates: number; n_with_metric: number }; start: { date: string; n_candidates: number; n_with_metric: number }; feasible_start?: { date: string; years: number; n_with_metric: number } | null } | null
}

// ───────────────────────── 실행 (schemas/run.py) ─────────────────────────
export type StepStatus = "QUEUED" | "STARTED" | "SUCCESS" | "PARTIAL" | "FAILED" | "CANCELLED"
export type RunState = "queued" | "running" | "cancelling" | "success" | "partial" | "failed" | "cancelled"
export interface RunStep { step: string; label_ko: string; bucket: string; status: StepStatus; started_at?: string | null; ended_at?: string | null; summary?: string | null; error_code?: string | null; error_message?: string | null }
export interface RunBucket { id: string; title_ko: string; status: StepStatus }
export interface RunStatus { run_id: string; request_id: string; status: RunState; queue_position: number | null; queued_at: string; started_at?: string | null; finished_at?: string | null; buckets: RunBucket[]; steps: RunStep[]; report_id?: string | null; error?: { code: string; message_ko: string; step?: string | null; actions: string[] } | null }
export interface RunRow { run_id: string; request_id: string; status: RunState; queued_at: string; started_at?: string | null; finished_at?: string | null; report_id?: string | null; error_message?: string | null }
export interface RequestRow { request_id: string; created_at: string; mode: string; idea: string; status: string; state: DialogStatus; run_id?: string | null; turn: number }
/** 실행 중 중간 결과 (GET /runs/{id}/partial): 해석 요약과 선정 종목 표가 디스크에 있으면 온다. */
export interface RunPartial { run_id: string; intent: { summary_ko?: string | null; themes: { id: string; label_ko: string }[]; template?: string | null; metric?: string | null } | null; selection: { as_of: string; metric?: string | null; n_selected: number; n_target?: number | null; n_candidates?: number | null; n_tagged?: number | null; rows: { rank?: number | null; ticker: string; name?: string | null; sector?: string | null; metric_value?: number | null }[] } | null }

// ───────────────────────── 리포트 (schemas/report.py 블록 모델) ─────────────────────────
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
export interface CheckpointItem { seq: number; date: string; kind: "rebalance" | "closing" | "monthly"; n_trading_days_to_date: number; weights_before: Record<string, number> | null; weights_after: Record<string, number>; weights_target: Record<string, number>; holdings: Holding[]; since_last: Record<string, unknown> | null; to_date: Record<string, unknown> | null; n_trades: number; commission_usd: number; value_usd: number; benchmark_value_usd: number | null; net_invested_usd: number; drift: Record<string, unknown> | null }
export interface CheckpointsBlock { type: "checkpoints"; title_ko: string; portfolio_id: string; items: CheckpointItem[] }
export interface GlossaryBlock { type: "glossary"; items: { term: string; explain_ko: string }[] }
export interface EvidenceRecord {
  id: string; kind: "news" | "disclosure" | "financial" | "calc" | string; title: string; source: string; url?: string | null; published_at?: string | null; data_as_of?: string | null; tickers: string[]; value?: unknown; unit?: string | null; language?: string | null
  // 공시 (라운드 4)
  event_type?: string | null; event_label_ko?: string | null; form?: string | null; items?: string | null; filed_at?: string | null; available_on?: string | null; excerpt?: string | null
}
export interface EvidenceBlock { type: "evidence"; title_ko: string; items: EvidenceRecord[] }
// ── 문서 v2 블록 (라운드 4) ──
export interface EvidenceRefBlock { type: "evidence_ref"; title_ko: string; ids: string[] | null; count: number; kinds: Record<string, number> }
export interface WeightsCompareBlock { type: "weights_compare"; title_ko: string; columns: { id: string; label_ko: string; kind: string; rule_ko: string }[]; rows: { ticker: string; name: string; sector: string; weights: Record<string, number> }[]; cash: Record<string, number>; ex_ante: Record<string, { vol?: number | null; effective_n?: number | null; exp_return?: number | null; cash?: number }>; baseline_id: string; note_ko?: string }
export interface TimelineView { summary_ko: string; confidence: number | null; evidence_ids: string[]; evidence_type?: string | null }
export interface TimelineItem { seq: number; date: string; kind: "rebalance" | "closing" | "monthly"; n_trading_days_to_date: number; value_usd: number; benchmark_value_usd: number | null; net_invested_usd: number; since_last: { return?: number | null; benchmark_return?: number | null; excess?: number | null; max_drawdown?: number | null } | null; n_trades: number; turnover: number | null; commission_usd: number | null; to_date: { total_return?: number | null; cagr?: number | null; max_drawdown?: number | null; sharpe?: number | null; excess_cagr?: number | null } | null; cash_after: number | null; news: { n_articles: number; n_disclosures: number; n_tickers_with_evidence: number; n_views: number; fallback: boolean; window?: [string, string] | null; disclosure_window?: [string, string] | null } | null; views: TimelineView[]; top_delta: { ticker: string; delta: number }[] }
export interface TimelineBlock { type: "timeline"; title_ko: string; portfolio_id: string; walkforward: boolean; items: TimelineItem[]; note_ko?: string }
export interface CompanyItem { ticker: string; name: string; market: string; sector: string; sub_industry: string; summary: string; theme_reason_ko: string; theme_confidence: number | null; weight: number | null; in_selection_now: boolean; rank_now: number | null; metric_now: number | null; in_backtest: boolean; rank_bt: number | null; metric_bt: number | null; fact_id: string | null; rationale_ko: string[]; evidence_ids: string[]; n_news: number; n_disclosures: number }
export interface CompaniesBlock { type: "companies"; title_ko: string; metric: string; metric_ko: string; direction: string; as_of_now: string; as_of_bt: string; portfolio_id: string; items: CompanyItem[]; note_ko?: string }
/** 모든 블록이 가질 수 있는 공통 필드: 접힘 묶음(group_ko), 처음부터 펼침(group_open), 문단 출처(src). */
export interface BlockMeta { group_ko?: string; group_open?: boolean; src?: string }
export type Block = (ParagraphsBlock | KpisBlock | TableBlock | DonutBlock | LineBlock | AreaBlock | BarBlock | FunnelBlock | CalloutBlock | CardsBlock | CheckpointsBlock | GlossaryBlock | EvidenceBlock | EvidenceRefBlock | WeightsCompareBlock | TimelineBlock | CompaniesBlock) & BlockMeta
export interface Section { id: string; title_ko: string; blocks: Block[] }
export interface Series { label_ko: string; kind: string; index?: number[]; value_usd?: number[]; drawdown?: number[] }
export interface SummaryKpi extends Kpi { benchmark_value?: number | null; benchmark_label_ko?: string | null }
export interface ReportSummary {
  verdict: { status: "recommended" | "recommended_warn" | "insufficient" | "none_cash_blend" | "none_baseline"; label_ko: string; headline_ko: string; reason_ko?: string | null; chosen_portfolio_id: string; chosen_label_ko: string; cautions_ko?: string[]; period_note_ko?: string | null; notices_ko?: string[]; n_notices?: number }
  validation: { n_pass: number; n_warn: number; n_fail: number; n_candidates?: number | null; chosen_status: string; failed_rules_ko: string[]; warned_rules_ko?: string[]; info_notes_ko?: string[]; rules_ko?: { rule: string; name_ko: string; level: string; status: string; message_ko: string }[]; tolerance_note_ko?: string; r1_ko?: string | null; r1?: { mdd: number; tolerance: number; benchmark_mdd: number; excess: number; status: string; match_target?: number | null } | null }
  news_effect?: { disabled: boolean; reason_ko?: string; bl_id?: string; bl_label_ko?: string; base_id?: string | null; base_label_ko?: string | null; bl_cagr?: number | null; base_cagr?: number | null; diff_cagr?: number | null; bl_excess_cagr?: number | null; base_excess_cagr?: number | null; bl_mdd?: number | null; base_mdd?: number | null; hit_365?: number | null; hit_next_rb?: number | null; n_views?: number; n_dates?: number; n_rebalances?: number; n_fallback?: number; annualized_reliable?: boolean } | null
  kpis: SummaryKpi[]
  allocation: { basis: string; basis_ko: string; items: { ticker: string; name: string; sector: string; weight: number; usd: number; krw: number }[]; cash_weight: number; initial_amount_usd: number; fx_rate: number; fx_direction?: string } | null
  mini_series: { dataset: "index"; ids: string[]; label_ko?: string } | null
  period?: { start: string; end: string; trading_days?: number } | null
  next_actions_ko: string[]
}
export interface ReportDoc {
  request_id: string; run_id: string; stage: string; generated_at: string; source: string
  header: { title_ko: string; title_detail_ko?: string; subtitle_ko: string; created_at: string; selection_as_of: string; backtest_period: { start: string; end: string; as_of: string; trading_days?: number }; data_as_of: string; chosen_portfolio_id: string; chosen_label_ko: string; chosen_note_ko: string; disclaimer_ko: string; run_id?: string; mode?: string; backtest_mode?: string }
  kpis: Kpi[]; nav: { id: string; title_ko: string }[]; sections: Section[]
  datasets: { dates: string[]; series: Record<string, Series>; sampling?: { method: string; stride: number; full_points: number; points: number; pinned: string[] } | null }
  assessment: { intent_fit: number | null; logic_consistency: number | null; comments_ko: string[] }
  evidence: EvidenceRecord[]; execution: { step: string; summary: string }[]; tracking: { eligible: boolean; reason_ko: string | null }
  sources: { id: string; name: string; what: string; url: string | null }[]; parameters: Record<string, unknown>; warnings: string[]
  notices?: { stage: string; code: string; level: string; message_ko: string; count: number; dates: string[] }[]
  // v2 (라운드 4). v1 문서는 lib/reportNormalize 가 채운다.
  doc_version?: number; summary?: ReportSummary | null; evidence_summary?: { total: number; cited: number; by_kind: Record<string, number> } | null; presented_from_version?: number
}
// ── 리포트 보조 조회 (라운드 4) ──
export interface EvidencePage { total: number; offset: number; limit: number; items: EvidenceRecord[]; by_kind: Record<string, number>; index_total: number }
export interface EvidenceDetail extends EvidenceRecord { cited_in: { section_id: string; block_title_ko: string; text_ko: string }[] }
export interface CheckpointDetail { portfolio_id: string; label_ko: string; checkpoint: { seq: number; date: string; kind: string; n_trading_days_to_date: number; weights: { target: Record<string, number>; before: Record<string, number> | null; after: Record<string, number>; cash_before: number | null; cash_after: number }; holdings: Holding[]; trades: { ticker: string; side: "buy" | "sell"; shares: number; price: number; value_usd: number }[]; turnover: number | null; commission_usd: number; money: { value_usd: number; cumulative_contributions_usd: number; net_invested_usd: number; profit_usd: number; benchmark_value_usd: number | null }; since_last: Record<string, unknown> | null; to_date: Record<string, unknown> | null; drift: Record<string, unknown> | null }; names: Record<string, string>; views: { summary_ko: string; rationale_ko?: string; confidence: number; evidence_ids: string[]; type?: string; long?: string[]; short?: string[] }[]; news_summary: Record<string, unknown> | null; narrative_ko: string | null; market_model: Record<string, unknown> | null; evidence?: Record<string, EvidenceRecord> }
export interface SeriesResponse { dataset: "index" | "value_usd" | "drawdown"; dates: string[]; series: Record<string, { label_ko: string; kind: string; values: number[] }> }
export interface EvidenceQuery { offset?: number; limit?: number; kind?: string; ticker?: string; q?: string; from?: string; to?: string; ids?: string[] }
export interface ReportRow { report_id: string | null; run_id: string; request_id: string; status: RunState; has_report: boolean; strategy_name?: string | null; request_summary?: string | null; as_of: string; created_at?: string | null; idea?: string | null; mode?: string | null }

// ───────────────────────── 메타 ─────────────────────────
export interface Health { ok: boolean; api_version: string; llm_mode: "stub" | "api"; db: { ok: boolean; latest_trading_day?: string; data_start?: string; error?: string }; worker: { alive: boolean; running_run_id: string | null }; queue_length: number }
export interface Options { universes: Universe[]; templates: Template[]; weightings: Weighting[]; risk_tolerance: RiskTolerance[]; rebalance_units: RebalanceUnit[]; age_band: string[]; investment_experience: string[]; financial_knowledge: string[]; purpose: string[]; loss_reaction: string[]; benchmarks: string[]; max_questions: number; default_backtest_years: number; markets: string[]; labels_ko: Record<string, Record<string, string>>; data_range: [string, string] | null; latest_trading_day?: string }
export interface ApiErrorBody { error: { code: string; message_ko: string; fields?: Record<string, string>; details?: Record<string, unknown> } }

// ───────────────────────── 모의투자 (Module6) ─────────────────────────
export type PaperStrategyKind = "template" | "black_litterman" | "cash_blend"
export interface PaperStrategy { id: string; kind: PaperStrategyKind; template: string | null; cash_ratio: number; name_ko: string }
export interface PaperStrategyOption extends PaperStrategy { status: "pass" | "warn" | "fail" | string; recommended: boolean; chosen: boolean; n_fail?: number | null; n_warn?: number | null }
export interface PaperCapital { amount: number; currency: "KRW" | "USD"; usd: number; fx_rate: number; fx_date: string }
export interface PaperContribution { enabled: boolean; monthly_amount?: number; currency?: "KRW" | "USD"; day?: number }
export interface PaperIn { report_id: string; strategy_id?: string | null; start_date?: string | null; initial_amount?: number | null; currency?: "KRW" | "USD" | null; monthly_contribution?: number | null }
export interface PaperPreview {
  report_id: string; run_id: string; report_as_of: string; strategy: PaperStrategy; strategy_options: PaperStrategyOption[]; start_date: string; data_ceiling: string; reconstructed_at_start: boolean
  initial_capital: PaperCapital; contribution: PaperContribution; rebalance_rule: { count: number; unit: string }; benchmark: string; tickers: string[]
  weights: Record<string, number>; cash_weight: number; report_weights: Record<string, number>; weight_diff: { ticker: string; report: number; start: number; delta: number }[]
  allocation: { ticker: string; weight: number; usd: number; krw: number; price_usd: number }[]; construct_info: { fallback: boolean; warnings: string[] }; warnings: string[]
}
export interface PaperSnapshot { date: string; value_usd: number; cash_usd: number; holdings_value_usd?: number; weights: Record<string, number>; drawdown: number; return_since_start: number; unit_price?: number; contribution_usd?: number; contributions_total_usd?: number; benchmark_value_usd?: number | null; benchmark_return_since_start?: number | null; fx_rate?: number | null; status: "ok" | "delayed" | "hold"; warnings?: string[] }
export interface PaperTrade { ticker: string; side: "buy" | "sell"; shares: number; price: number; value_usd: number }
export interface PaperRebalance { date: string; seq: number; kind?: "initial" | "rebalance" | "contribution"; before_weights: Record<string, number>; target_weights: Record<string, number>; applied_weights: Record<string, number>; trades: PaperTrade[]; commission_usd: number; turnover: number; views?: { summary_ko: string; evidence_ids: string[]; confidence: number }[]; evidence_window?: { start: string; end: string; n_articles: number; n_tickers_with_news: number } | null; fallback: boolean; skipped: boolean; warnings?: string[]; note_ko?: string | null }
export interface PaperSummary {
  paper_id: string; name_ko: string; strategy: PaperStrategy | null; report_id: string; run_id: string; status: "active" | "stopped"; start_date: string; last_date: string | null; days_tracked: number
  initial_capital: PaperCapital; value_usd: number; contributions_total_usd: number; gain_usd: number; return_since_start: number; benchmark: string | null; benchmark_return_since_start: number | null; excess_return: number | null
  drawdown: number; max_drawdown: number; n_rebalances: number; update_status: "ok" | "delayed"; delayed_reason_ko: string | null; last_refresh_at: string | null; data_ceiling: string; reconstructed_at_start: boolean
}
export interface PaperPortfolio {
  paper_id: string; report_id: string; run_id: string; strategy_id: string; strategy: PaperStrategy; name_ko: string; start_date: string; report_as_of?: string; reconstructed_at_start: boolean
  initial_capital: PaperCapital; contribution: PaperContribution; rebalance_rule: { count: number; unit: string }; benchmark: string; tickers: string[]; start_weights: Record<string, number>
  state: { holdings: Record<string, number>; cash_usd: number; last_snapshot_date: string | null; last_rebalance_date: string | null; n_rebalances: number; target_weights?: Record<string, number>; cash_weight?: number; update_status?: "ok" | "delayed"; delayed_reason_ko?: string | null; last_refresh_at?: string | null }
  status: "active" | "stopped"; created_at: string; stopped_at: string | null; resumed_at: string | null; history: { at: string; event: string; note?: string }[]; warnings: string[]
  constraints_snapshot: { request?: Record<string, unknown>; commission_bps?: number }
}
export interface PaperDetail { portfolio: PaperPortfolio; summary: PaperSummary; snapshots: PaperSnapshot[]; rebalances: PaperRebalance[]; series: { dates: string[]; value_usd: number[]; benchmark_value_usd: (number | null)[]; return_since_start: number[]; benchmark_return_since_start: (number | null)[]; drawdown: number[] } }

// ───────────────────────── 수정 요청·비교 (M1-05 · M5-06) ─────────────────────────
export interface RevisionChange { field: string; value: unknown; base_value: unknown; label_ko?: string | null; reason_ko?: string | null; supported: boolean; note_ko?: string | null }
export interface RevisionDraft { text: string; summary_ko?: string | null; changes: RevisionChange[]; unsupported_ko: string[]; idea_update_ko?: string | null; frozen_fields: string[]; base_run_id?: string | null }
export interface ComparisonDoc {
  comparison_id: string; base_run_id: string; revised_run_id: string; base_report_id: string; revised_report_id: string; created_at: string; same_window: boolean; window: { start: string; end: string }
  base_chosen_id?: string | null; revised_chosen_id?: string | null; base_chosen_label_ko?: string | null; revised_chosen_label_ko?: string | null
  base_validation?: { n_pass?: number; n_warn?: number; n_fail?: number } | null; revised_validation?: { n_pass?: number; n_warn?: number; n_fail?: number } | null
  condition_changes: { field: string; label_ko: string; base: unknown; revised: unknown }[]
  ticker_changes: { added: string[]; removed: string[]; kept: string[] }
  weight_changes: { ticker: string; base: number; revised: number; delta: number }[]
  rule_changes: { rule: string; label_ko: string; base: string | null; revised: string | null; changed: boolean }[]
  performance_table: { metric: string; label_ko: string; base: number | null; revised: number | null; benchmark: number | null; format: "pct" | "usd" | "num" }[]
  pros_cons_ko: { pros_ko: string[]; cons_ko: string[]; note_ko: string }
  revision_text?: string; revision_changes?: RevisionChange[]; warnings: string[]
}
