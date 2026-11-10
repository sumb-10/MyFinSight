// ───────────────────────── 제안 계약 (proposed contract, 미확정) ─────────────────────────
// 아직 서버가 주지 않는 데이터의 "이런 모양으로 받으면 좋겠다"는 제안이다. 지금은 목업 서비스(src/mocks)만 이 값을 채운다.
// 실제 서버(HttpService)는 이 필드·메서드를 주지 않으므로 화면은 값이 있을 때만 새 기능을 보여 주고, 없으면 지금 화면 그대로 둔다.
// 백엔드와 합의하면 이름·위치가 바뀔 수 있다 — 화면은 proposedOf() 같은 접근 함수 한 곳만 고치면 되게 쓴다.
// 단위 규칙은 types.ts 와 같다: 비율·수익률은 분수(0.12 = 12%), 금액은 통화를 필드 이름에 붙인다(_usd/_krw), 날짜는 YYYY-MM-DD.

import type { RiskTolerance, Tendency } from "./types"

export const PROPOSED_CONTRACT_VERSION = "proposed-0.1"

/* ───────── 리포트 ───────── */

/** 매수 실행 예상 (분석 기준일 가격·환율로 추천 전략 비중을 실제 주문 단위로 바꾼 값). 목표 배분액(allocation)과 다르다. */
export interface ProposedExecution {
  as_of: string                          // 가격·환율 기준일
  strategy_id: string; strategy_label_ko: string
  share_basis: "integer" | "fractional" | "mixed"  // 정수 주식 / 소수점 주식 / 혼합 (미국 소수점 · 한국 1주 단위)
  commission_bps: number                 // 거래 수수료 (bp)
  fx: { rate: number; date: string; source_ko: string }  // 1 USD = rate KRW
  capital: { amount: number; currency: "KRW" | "USD"; usd: number }
  items: { ticker: string; name: string; price_usd: number; target_weight: number; target_usd: number; target_krw: number; share_basis?: "integer" | "fractional"; shares: number; cost_usd: number; fee_usd: number; cost_krw: number }[]
  totals: { invested_usd: number; fee_usd: number; cash_left_usd: number; cash_left_krw: number; cash_target_usd: number; cash_target_krw: number }
  note_ko?: string
}

/** 한 포트폴리오 구성 (기준·날짜를 반드시 함께 둔다). */
export interface ProposedAllocationBasis { basis: "current" | "recommended_now" | "backtest_start"; label_ko: string; as_of: string; strategy_id: string; strategy_label_ko: string; items: { ticker: string; weight: number; usd: number; krw: number }[]; cash_weight: number; cash_usd: number; cash_krw: number }

export interface ProposedCompanyView { status: "generated" | "insufficient" | "disabled"; n_views: number; reason_ko: string; view_summaries_ko: string[]; evidence_ids: string[] }

export interface ProposedRequestLog {
  idea: string
  qa: { question_ko: string; answer_ko: string; at: string; applied_ko?: string | null }[]
  messages: { text: string; at: string; outcome: "applied" | "not_applied" | "needs_confirmation"; changes_ko: string[]; note_ko?: string | null }[]
  final_conditions: { label_ko: string; value_ko: string; changed: boolean }[]
}

export interface ProposedMarketTopic { id: string; kind: "market" | "industry" | "theme" | "evidence"; title_ko: string; summary_ko: string; points_ko: string[]; evidence_ids: string[] }

export interface ProposedCompanyReason { title_ko: string; text_ko: string; metric?: { label_ko: string; value: number; format: "pct" | "num" | "ratio" } | null; theme_link_ko?: string | null; quote_ko?: string | null; evidence_ids: string[] }

export interface ProposedRiskProfile {
  profile_version: number
  tendency_final: Tendency; tendency_computed: Tendency; risk_tolerance: RiskTolerance
  default_vol_pref: "low" | "medium" | "high"; applied_vol_pref: "low" | "medium" | "high"
  pref_reason_ko: string | null          // 기본값과 적용값이 다른 이유 (같으면 null)
  short_window: boolean; min_annualize_days: number
  informational_rules: { rule: string; name_ko: string; reason_ko: string }[]  // 짧은 기간에 참고로 바뀐 검사
}

/** 검증 규칙 구조화 (지금은 message_ko 문장만 온다). */
export interface ProposedCheck {
  rule: "R1" | "R3" | "R7" | string; name_ko: string; level: "flag" | "soft" | "hard" | "info"; status: "pass" | "warn" | "fail" | "flag" | "info"
  value: number | null; threshold: number | null; benchmark_value?: number | null; benchmark_label_ko?: string | null
  basis?: "total" | "annualized" | "benchmark_multiple" | "absolute" | "no_cap" | null
  multiplier?: number | null; vol_pref?: "low" | "medium" | "high" | null; observed_above?: boolean | null
}

export interface ProposedReason { code: string; title_ko: string; text_ko: string; tone: "good" | "warn" | "neutral"; values: Record<string, number | string> }

export interface ProposedStructured {
  reasons: ProposedReason[]
  checks: ProposedCheck[]
  tolerance: { input: number; match_target: number | null; factors_ko: string[] }
  annualized: { strategy_total_return: number; strategy_cagr: number; benchmark_total_return: number; benchmark_cagr: number; days: number; reliable: boolean }
  requested_amount: { amount: number; currency: "KRW" | "USD"; monthly: number }
  final_value: { usd: number; krw: number; fx_rate: number; fx_date: string }
  kpi_meta: Record<string, { name_ko: string; period: "total" | "annual" | "point"; days?: number | null }>
  benchmark: { ticker: string; kind: "etf"; label_ko: string; description_ko: string }
  timeline_meta: { strategy_id: string; strategy_label_ko: string; equity_ratio: number | null; cash_ratio: number | null; base_label_ko: string | null }
  compare_rows: { name: string; id: string; role: "chosen" | "baseline" | "benchmark" | "candidate" }[]
  exclusion_reasons: Record<string, string>
}

export interface ProposedExplanations {
  strategies: Record<string, { short_ko: string; help_ko: string }>
  ranking: { order: number; key: string; label_ko: string; desc_ko: string }[]
  etfs: Record<string, { label_ko: string; description_ko: string }>
  short_window_rules: { rule: string; name_ko: string; desc_ko: string }[]
  default_vol_by_risk: Record<RiskTolerance, "low" | "medium" | "high">
  glossary_extra: { term: string; explain_ko: string }[]
}

/** 원화 확장 (기준 환율·날짜를 늘 같이). value_krw[i] = value_usd[i] × fx[i]. */
export interface ProposedKrw { fx_dates: string[]; fx_rates: number[]; value_krw: number[]; final_value_krw: number; timeline_krw: { seq: number; date: string; fx_rate: number; value_krw: number; net_invested_krw: number; commission_krw: number | null }[] }

export interface ProposedReport {
  contract: typeof PROPOSED_CONTRACT_VERSION
  execution?: ProposedExecution | null
  allocations?: { current: ProposedAllocationBasis; recommended_now: ProposedAllocationBasis; backtest_start: ProposedAllocationBasis } | null
  chosen_vs_baseline?: { as_of: string; chosen_id: string; chosen_label_ko: string; baseline_id: string; baseline_label_ko: string; rows: { ticker: string; name: string; chosen: number; baseline: number }[]; cash: { chosen: number; baseline: number } } | null
  company_views?: Record<string, ProposedCompanyView> | null
  request_log?: ProposedRequestLog | null
  krw?: ProposedKrw | null
  market_topics?: ProposedMarketTopic[] | null
  company_reasons?: Record<string, ProposedCompanyReason[]> | null
  risk_profile?: ProposedRiskProfile | null
  structured?: ProposedStructured | null
  explanations?: ProposedExplanations | null
}

/** 리포트 이름 (자동 이름과 사용자가 바꾼 이름을 따로 둔다). */
export interface ProposedReportName { report_id: string; auto_ko: string; custom_ko: string | null; display_ko: string; updated_at: string | null }
/** 리포트 목록 행에 붙는 이름 (GET /reports 의 각 행). 홈·사이드바·목록이 상세와 같은 이름을 쓰게 한다. */
export interface ProposedReportRowExt { proposed_name?: ProposedReportName }
export const proposedNameOf = <T extends object>(row: T): string | null => ((row as ProposedReportRowExt).proposed_name?.display_ko ?? null)

/* ───────── 내 투자조건·새 분석 ───────── */

export interface ProposedStock { ticker: string; name_ko: string; name_en: string | null; market: "US" | "KR"; sector_ko: string }   // 실제 서버: 미국 종목은 name_ko 도 영문(한국어 이름 자료 없음), 한국 종목은 name_en 이 null
/** 종목 표기 규칙: 「회사명 (티커)」. 서버가 만드는 조건 문장(value_ko·질문 보기)도 같은 규칙을 쓴다고 가정한다. */
export const stockLabel = (s: Pick<ProposedStock, "ticker" | "name_ko"> | null | undefined, ticker: string) => (s ? `${s.name_ko} (${ticker})` : ticker)
/** GET /options 에 붙는 입력 규칙 (지금 서버는 주지 않는다 → 화면은 기존 규칙 그대로). */
export interface ProposedOptionsExt { proposed_rules?: { allow_zero_initial_amount: boolean } }
export const proposedRulesOf = <T extends object>(o: T | null | undefined) => ((o as ProposedOptionsExt | null | undefined)?.proposed_rules ?? null)
export interface ProposedStrategyRecommendation { tendency: Tendency; recommended: { template: string; baseline_weighting: string; use_news_tilt: boolean }; reasons_ko: string[]; alternatives: { template: string; baseline_weighting: string; use_news_tilt: boolean; diff_ko: string }[]; note_ko: string }
export interface ProposedQuestionBatch { request_id: string; questions: { seq: number; field: string; field_label_ko: string; question_ko: string; why_ko?: string | null; required: boolean; options: { value: unknown; label_ko: string }[]; allow_free_text: boolean }[] }
/** 여러 질문 한 번에 답하기. skip = 답하지 않음(기본값 사용, 필수 질문에는 못 쓴다). */
export type ProposedBatchAnswer = { seq: number; option_value?: unknown; free_text?: string; skip?: boolean }
export interface ProposedMessageResult { text: string; at: string; outcome: "applied" | "not_applied" | "needs_confirmation"; changes: { field: string; label_ko: string; before_ko: string; after_ko: string }[]; note_ko: string }

/**
 * 대화형 초기 투자조건 (처음 쓰는 사용자). 서버가 대화를 이끈다: 질문 순서·보기·답 반영·다시 묻기는 서버가 정하고, 화면은 받은 대로 그린다.
 * 대화는 초안(draft)만 만든다 — 저장은 기존 PUT /profile(saveProfile)로 한다. draft 는 기본값이 채워진 완전한 모양.
 * kind: choice = 보기 하나, multi = 보기 여러 개(값 배열), money = 원 단위 금액, number = 숫자. 금액·숫자는 보기(빠른 선택) + 직접 입력(input 범위).
 */
export type ProposedChatKind = "choice" | "multi" | "money" | "number"
export interface ProposedChatQuestion { id: string; field_label_ko: string; kind: ProposedChatKind; options: { value: unknown; label_ko: string; help_ko?: string | null; recommended?: boolean }[]; input: { min: number; max: number; step: number; unit_ko: string } | null; allow_skip: boolean }
/** editable = 사용자 답 말풍선의 「고치기」 대상 (그 질문만 다시 묻는다). */
export interface ProposedChatMessage { id: string; role: "bot" | "user"; text_ko: string; question_id?: string | null; editable?: boolean }
export interface ProposedProfileChat {
  chat_id: string
  state: "asking" | "review"                 // review = 필수 질문을 다 답함 → 화면은 요약·저장
  messages: ProposedChatMessage[]
  question: ProposedChatQuestion | null      // 지금 답할 질문 (review 면 null)
  progress: { done: number; total: number }
  draft: import("./types").ProfileFields
  asked_fields: string[]                     // 답으로 정해진 항목 (점 경로). 나머지는 기본값
  derived_fields?: Record<string, string>    // 답에 맞춰 정한 항목 → 이유 (요약의 「답에 맞춰 정한 조건」: 비중 상한·비교지수·목표 연수익률 등)
}
/** 답: 보기를 고르면 option_value(multi 는 배열), 직접 입력하면 number. skip 은 allow_skip 인 질문만. */
export type ProposedChatAnswer = { question_id: string; option_value?: unknown; number?: number; skip?: boolean }

/* ───────── 분석 진행 ───────── */
export interface ProposedRunWarning { step: string; step_label_ko: string; message_ko: string; count: number }
/** GET /runs/{id} 에 붙는 취소 결과. immediate = 서버가 진행 중인 작업을 바로 멈출 수 있음 (지금 서버는 단계가 끝날 때 멈춘다). */
export interface ProposedRunCancel { requested_at: string; completed_at: string | null; stopped_step: string | null; stopped_step_label_ko: string | null; done_steps: number; immediate: boolean }
/** 취소 결과: 실행 상태의 `cancel` (실제 서버 GET /runs/{id}·목업 모두, 취소를 요청한 실행만). 없으면 null. */
export const proposedCancelOf = <T extends object>(r: T | null | undefined) => ((r as { cancel?: ProposedRunCancel | null } | null | undefined)?.cancel ?? null)

/* ───────── 모의투자 ───────── */
export type ProposedFxDay = { date: string; rate: number | null; status: "ok" | "carried" | "missing"; carried_from?: string | null }  // ok = 그날 환율, carried = 직전 환율 대체, missing = 환율 없음(환산 불가)
/** 원화 기준 성과. 날짜별 원화 납입액과 그날 환율로 환산한 평가액으로 계산한다 (USD 수익률에 환율을 곱하지 않는다).
 *  수익률은 USD·원화 모두 「넣은 원금 대비」 같은 방식이라, 둘의 차이는 환율 변화 효과다. 화면의 「운용 수익률」(납입 시점 영향을 뺀 값)과는 계산 방식이 다르다. */
export interface ProposedPaperKrw {
  fx: ProposedFxDay[]
  value_krw: (number | null)[]                   // 날짜별 원화 평가액 (환율 없으면 null)
  contributions_krw_total: number | null         // 넣은 원금(원화). 원화 납입은 그 금액, USD 납입은 납입일 환율로 환산. 환율이 없어 정할 수 없으면 null
  last: { date: string; value_krw: number | null; fx: ProposedFxDay }
  gain_krw: number | null; return_krw: number | null
  usd_same_basis: { contributions_usd: number; value_usd: number; gain_usd: number; return_usd: number }
  fx_start: ProposedFxDay; fx_change: number | null   // 시작일 → 마지막 평가일 환율 변화율
  fx_effect_pp: number | null                         // return_krw − usd_same_basis.return_usd
  fx_counts: { ok: number; carried: number; missing: number }
  unavailable_reason_ko: string | null                // 원화 수익률을 계산하지 못한 이유
}
export interface ProposedPaperName { name_ko: string; mode: "linked" | "custom"; report_name_ko: string }
export type ProposedPaperNameIn = { mode: "linked" } | { mode: "custom"; name_ko: string }   // linked = 리포트 이름을 따라감, custom = 직접 정한 이름

/* ───────── 서비스 확장 (모두 선택). 목업 서비스는 모두 가지고, 실제 서버 서비스(HttpService)는 서버가 구현한 것만 가진다
   (어느 것인지는 mocks/mocks.test.tsx 의 CONNECTED) → 화면은 메서드가 있을 때만 기능을 연다. ───────── */
export interface ProposedApi {
  getReportName(reportId: string): Promise<ProposedReportName>
  renameReport(reportId: string, name: string | null): Promise<ProposedReportName>   // null = 자동 이름으로 되돌리기
  deleteReport(reportId: string): Promise<void>   // 저장된 리포트 삭제 (실제 서버는 목록·조회에서 숨긴다)
  searchStocks(q: string): Promise<ProposedStock[]>
  getStocks(tickers: string[]): Promise<ProposedStock[]>   // 티커 → 회사명 (목록에 없는 티커는 빠진다)
  getProfileVersion(version: number): Promise<import("./types").ProfileVersion>
  recommendStrategy(tendency: Tendency, purpose?: string | null): Promise<ProposedStrategyRecommendation>
  startProfileChat(): Promise<ProposedProfileChat>   // 대화형 초기 투자조건: 새 대화 시작
  answerProfileChat(chatId: string, answer: ProposedChatAnswer): Promise<ProposedProfileChat>
  rewindProfileChat(chatId: string, questionId: string): Promise<ProposedProfileChat>   // 그 질문만 다시 묻기 (뒤의 답은 남기고, 그 답에 기대는 질문만 함께 다시 묻는다)
  getQuestionBatch(requestId: string): Promise<ProposedQuestionBatch | null>
  answerBatch(requestId: string, answers: ProposedBatchAnswer[]): Promise<import("./types").DialogState>
  getMessageResults(requestId: string): Promise<ProposedMessageResult[]>
  getRunWarnings(runId: string): Promise<ProposedRunWarning[]>
  getPaperKrw(paperId: string): Promise<ProposedPaperKrw | null>
  getPaperName(paperId: string): Promise<ProposedPaperName>
  setPaperName(paperId: string, input: ProposedPaperNameIn): Promise<ProposedPaperName>
}

/** ProposedApi 메서드 이름 전부. 인터페이스에 메서드를 더하고 여기 빠뜨리면 타입 검사가 잡는다 (테스트가 목업·실제 서버 서비스에 무엇이 있는지 볼 때 쓴다). */
const PROPOSED_ALL: Record<keyof ProposedApi, true> = {
  getReportName: true, renameReport: true, deleteReport: true, searchStocks: true, getStocks: true, getProfileVersion: true, recommendStrategy: true,
  startProfileChat: true, answerProfileChat: true, rewindProfileChat: true, getQuestionBatch: true, answerBatch: true, getMessageResults: true,
  getRunWarnings: true, getPaperKrw: true, getPaperName: true, setPaperName: true,
}
export const PROPOSED_METHODS = Object.keys(PROPOSED_ALL) as (keyof ProposedApi)[]

/** 응답에 붙은 제안 필드 읽기 (없으면 null). 실제 서버 응답에는 없다. */
export const proposedOf = <T extends object>(x: T): ProposedReport | null => ((x as { proposed?: ProposedReport }).proposed ?? null)
