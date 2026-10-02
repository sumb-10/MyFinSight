import type { Security, Tendency } from "./types"

export const APP_CONFIG = {
  horizon: { minMonths: 12, maxMonths: 120 },
  globalCap: { min: 5, max: 100 },
  securityCap: { min: 0, max: 100 },
  coveragePct: 95,
  clarificationLimit: 5,
  canonicalAsOf: "2025-02-28",
  fxRate: 1458.2,
  fxDate: "2025-02-28",
}

export const TENDENCIES: Tendency[] = [
  "안정형",
  "안정추구형",
  "위험중립형",
  "적극투자형",
  "공격투자형",
]

export const INDUSTRIES = [
  "AI·소프트웨어",
  "반도체",
  "헬스케어",
  "금융",
  "소비재",
  "산업재",
  "에너지",
]

export const PREFERENCES = ["성장", "가치", "배당", "대형주"]

export const SECURITIES: Security[] = [
  {
    ticker: "MSFT",
    name: "Microsoft",
    industry: "AI·소프트웨어",
    type: "stock",
  },
  { ticker: "AVGO", name: "Broadcom", industry: "반도체", type: "stock" },
  { ticker: "TSM", name: "TSMC", industry: "반도체", type: "stock" },
  {
    ticker: "GOOGL",
    name: "Alphabet",
    industry: "AI·소프트웨어",
    type: "stock",
  },
  { ticker: "NVDA", name: "NVIDIA", industry: "반도체", type: "stock" },
  { ticker: "AMD", name: "AMD", industry: "반도체", type: "stock" },
  {
    ticker: "META",
    name: "Meta Platforms",
    industry: "AI·소프트웨어",
    type: "stock",
  },
  {
    ticker: "JNJ",
    name: "Johnson & Johnson",
    industry: "헬스케어",
    type: "stock",
  },
  { ticker: "JPM", name: "JPMorgan Chase", industry: "금융", type: "stock" },
  { ticker: "PG", name: "Procter & Gamble", industry: "소비재", type: "stock" },
  { ticker: "KO", name: "Coca-Cola", industry: "소비재", type: "stock" },
  { ticker: "PEP", name: "PepsiCo", industry: "소비재", type: "stock" },
]

export const QUESTIONS = [
  {
    id: "loss",
    question:
      "과거에 투자금이 일시적으로 하락했을 때 어느 수준까지 감수할 수 있나요?",
    options: [
      { label: "약 5% 하락도 크게 부담됩니다", score: 0, loss: 5 },
      { label: "약 10% 하락까지 감수할 수 있습니다", score: 1, loss: 10 },
      { label: "약 20% 하락까지 감수할 수 있습니다", score: 2, loss: 20 },
      {
        label: "약 30% 이상 하락도 장기 관점에서 감수할 수 있습니다",
        score: 4,
        loss: 30,
      },
    ],
  },
  {
    id: "reaction",
    question: "시장 급락 시 가장 가까운 행동은 무엇인가요?",
    options: [
      { label: "즉시 대부분 매도합니다", score: 0 },
      { label: "일부를 줄이고 상황을 지켜봅니다", score: 1 },
      { label: "계획을 유지합니다", score: 2 },
      { label: "추가 매수를 검토합니다", score: 4 },
    ],
  },
  {
    id: "priority",
    question: "수익과 안정성 중 더 중요한 것은 무엇인가요?",
    options: [
      { label: "원금 변동 최소화", score: 0 },
      { label: "안정성을 조금 더 중시", score: 1 },
      { label: "균형", score: 2 },
      { label: "높은 변동을 감수한 장기 성장", score: 4 },
    ],
  },
]
