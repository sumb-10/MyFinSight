export type Tendency = "안정형" | "안정추구형" | "위험중립형" | "적극투자형" | "공격투자형"

export type StageStatus = "waiting" | "processing" | "completed" | "partial" | "failed" | "canceled" | "skipped"

export interface Security {
  ticker: string
  name: string
  industry: string
  type: "stock" | "etf"
}

export interface Profile {
  amountKrw: number
  horizonMonths: number
  computedTendency: Tendency
  finalTendency: Tendency
  tendencyOverridden: boolean
  lossTolerancePct: number
  industries: string[]
  preferences: string[]
  memo: string
  excludedTickers: string[]
  globalCapPct: number
  securityCaps: Record<string, number>
  allowEtf: boolean
  market: "미국"
}

export interface EffectiveConditions extends Profile {
  namedTickers: string[]
  analysisOverrides: string[]
}

export interface StrategyRules {
  universe: string
  selectionRule: "lowest-volatility" | "momentum" | "fixed-list"
  selectionCount: number
  lookbackMonths: number
  weightingRule: "equal" | "inverse-volatility"
  exclusions: string[]
  globalCapPct: number
  securityCaps: Record<string, number>
  rebalance: "분기별"
  assumptions: string[]
}

export interface Allocation {
  ticker: string
  company: string
  weight: number
  usd: number
  krw: number
  selectionReason: string
  weightingReason: string
  role: string
  capPct: number
  capAdjusted: boolean
  risk: string
  evidenceId: string
}

export interface Point {
  date: string
  portfolio: number
  benchmark: number
  drawdown: number
}

export interface Metrics {
  cumulativeReturn: number
  cagr: number | null
  volatility: number | null
  sharpe: number | null
  mdd: number
  benchmarkReturn: number
}

export interface Evidence {
  id: string
  title: string
  value: string
  provider: string
  sourceTitle: string
  sourceUrl?: string
  marketDate?: string
  publicationDate?: string
  collectedAt: string
  usedFor: string
  isDemo: boolean
  section?: string
  excerpt?: string
  recordId?: string
  supportedClaim?: string
}

export interface CitedParagraph {
  text: string
  citationIds: string[]
}

export interface CompanyAnalysis {
  ticker: string
  heading: string
  paragraphs: CitedParagraph[]
}

export interface ReportNarrative {
  overallJudgment: CitedParagraph[]
  industryAnalysis: CitedParagraph[]
  companyAnalyses: CompanyAnalysis[]
  portfolioConstruction: CitedParagraph[]
  performanceInterpretation: CitedParagraph[]
  reconsiderationConditions: CitedParagraph[]
}

export interface ExecutionRecord {
  id: string
  stage: string
  status: StageStatus
  startedAt?: string
  endedAt?: string
  summary: string
  sources: string[]
  issues: string[]
  technical?: string
  tools?: string[]
  modelOutput?: string
  decisionSummary?: string
}

export interface CandidateStrategy {
  id: string
  name: string
  selectionRule: string
  weightingRule: string
  rebalance: string
  cumulativeReturn: number
  volatility: number
  mdd: number
  sharpe: number | null
  selected: boolean
  evaluation: string
}

export interface CalculationConditions {
  startDate: string
  endDate: string
  currency: "USD"
  initialCapitalUsd: number
  benchmark: string
  benchmarkMeaning: string
  transactionCostPct: number
  riskFreeRatePct: number
  riskFreeSource: string
  fxRate: number
  fxDate: string
  compositionDate: string
  marketAsOf: string
}

export interface Report {
  id: string
  title: string
  idea: string
  createdAt: string
  isDemo: boolean
  status: "complete" | "partial"
  saved: boolean
  sourceReportId?: string
  conditions: EffectiveConditions
  strategy: StrategyRules
  allocation: Allocation[]
  evidence: Evidence[]
  execution: ExecutionRecord[]
  calculation: CalculationConditions
  series: Point[]
  metrics: Metrics
  exclusions: string[]
  limitations: string[]
  summary: string
  narrative: ReportNarrative
  candidateStrategies: CandidateStrategy[]
}

export interface PaperHolding {
  ticker: string
  company: string
  initialWeight: number
  currentWeight: number
  targetWeight: number
  lastRebalanceWeight: number
  currentValueKrw: number
}

export interface PaperPortfolio {
  id: string
  reportId: string
  title: string
  isDemo: boolean
  startedAt: string
  latestAsOf: string
  initialCapitalKrw: number
  currentValueKrw: number
  benchmarkReturn: number
  updateStatus: "정상" | "업데이트 지연" | "조회 실패"
  series: Point[]
  holdings: PaperHolding[]
  rebalanceRecords: { date: string summary: string }[]
}

export interface AnalysisDraft {
  idea: string
  conditions: EffectiveConditions
  answers: { question: string answer: string }[]
  clarificationCount: number
  mode: "new" | "reanalyze" | "revision"
  sourceReportId?: string
}

export interface AppData {
  version: number
  profile: Profile | null
  reports: Report[]
  paperPortfolios: PaperPortfolio[]
  interruptedDraft?: AnalysisDraft
}

export type DemoOutcome = "success" | "partial" | "required-data" | "infeasible" | "backtest" | "consistency" | "save-failure"
