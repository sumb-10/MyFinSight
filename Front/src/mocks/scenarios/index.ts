// 목업 시나리오 정의. 한 시나리오의 아이디어·조건·질문/답변·말로 보태기·종목·전략·성과·모의투자가 화면마다 같은 값을 쓰도록
// 여기 한 곳에서 정하고, 숫자(성과·금액·수량)는 data/ 의 생성기가 이 정의에서 계산한다.
import type { RiskTolerance, Template, Tendency, Weighting } from "../../api/types"

export const MOCK_AS_OF = "2026-10-30"          // 분석 기준일 (가격·환율 기준)
export const MOCK_FX_NOW = 1380                 // 분석 기준일 예시 환율 (1 USD = 1,380 KRW)

export interface ReportScenario {
  id: string; run_id: string; request_id: string; created_at: string
  key: "normal" | "caution" | "none" | "news_off" | "legacy" | "revised"
  label_ko: string                              // 개발용 시나리오 이름 (목업 패널에만)
  doc_version: 1 | 2
  idea: string
  auto_name_ko: string                          // 아이디어에서 만든 리포트 이름 (제안 기능: 자동 이름)
  themes: { label: string; desc: string }[]
  tickers: string[]; must_include: string[]; exclude: string[]
  tendency_final: Tendency; tendency_computed: Tendency; risk_tolerance: RiskTolerance
  vol_pref: "low" | "medium" | "high"; vol_pref_reason_ko: string | null
  loss_reaction: "sell" | "hold" | "buy_more"; experience: "none" | "beginner" | "intermediate" | "advanced"
  capital: { amount: number; currency: "KRW" | "USD"; monthly: number; day: number }
  fx_bt: number                                 // 백테스트 시작일 예시 환율
  horizon_years: number; backtest_years: number
  max_dd: number; target_return: number; benchmark: "SPY"
  max_weight: number; template: Template; baseline: Weighting
  news: boolean
  drift_shift: number; bench_drift: number       // 시나리오 결과(추천/주의/없음)가 나오도록 정한 예시 시장 흐름
  qa: { question_ko: string; answer_ko: string; applied_ko: string | null }[]
  messages: { text: string; outcome: "applied" | "not_applied" | "needs_confirmation"; changes_ko: string[]; note_ko: string | null }[]
  profile_version: number
  base_report_id?: string                       // 원안 비교: 이 리포트의 원안
  revision_text?: string
}

export const REPORTS: ReportScenario[] = [
  {
    id: "mock_rep_normal", run_id: "mock_run_normal", request_id: "mock_req_normal", created_at: "2026-10-31", key: "normal", label_ko: "정상 추천 · 뉴스 반영 켜짐 · 3년", doc_version: 2,
    idea: "미국 반도체 장비와 메모리 기업에 나눠 투자하고 싶어요. 한 종목에 너무 몰리지 않았으면 좋겠어요.",
    auto_name_ko: "미국 반도체 장비·메모리 분산 투자",
    themes: [{ label: "반도체 장비", desc: "증착·식각·노광·검사 장비를 만드는 기업" }, { label: "메모리 반도체", desc: "D램·낸드·HBM을 만드는 기업" }],
    tickers: ["NVDA", "MU", "AMAT", "LRCX", "KLAC", "ASML"], must_include: ["MU", "NVDA"], exclude: ["TSLA"],
    tendency_final: "위험중립형", tendency_computed: "위험중립형", risk_tolerance: "moderate", vol_pref: "medium", vol_pref_reason_ko: null,
    loss_reaction: "hold", experience: "beginner",
    capital: { amount: 20_000_000, currency: "KRW", monthly: 500_000, day: 25 }, fx_bt: 1352,
    horizon_years: 5, backtest_years: 3, max_dd: 0.3, target_return: 0.1, benchmark: "SPY", max_weight: 0.25, template: "momentum", baseline: "market_cap", news: true,
    drift_shift: 0.04, bench_drift: 0.11,
    qa: [
      { question_ko: "한 종목에 최대 몇 %까지 담을까요?", answer_ko: "25%", applied_ko: "종목당 최대 비중 25%" },
      { question_ko: "엔비디아처럼 이미 많이 오른 대형주도 포함할까요?", answer_ko: "포함해도 괜찮아요", applied_ko: "대형주 제외 없음" },
    ],
    messages: [
      { text: "마이크론은 꼭 넣어 주세요", outcome: "applied", changes_ko: ["꼭 넣을 종목: NVDA → MU, NVDA (마이크론 테크놀로지 추가)"], note_ko: null },
      { text: "한국 반도체 기업도 조금 섞으면 좋겠어요", outcome: "not_applied", changes_ko: [], note_ko: "투자 대상 지수(S&P 500·나스닥 100)에 한국 종목이 없어 조건을 바꾸지 않았습니다. 기존 조건이 그대로 유지됩니다." },
    ],
    profile_version: 4,
  },
  {
    id: "mock_rep_caution", run_id: "mock_run_caution", request_id: "mock_req_caution", created_at: "2026-10-31", key: "caution", label_ko: "주의 있는 추천 · 짧은 기간(1년) · 변동성 기준 조정", doc_version: 2,
    idea: "AI 반도체와 클라우드 기업에 투자하고 싶은데, 변동성이 너무 크지 않았으면 좋겠어요.",
    auto_name_ko: "AI 반도체·클라우드 저변동 투자",
    themes: [{ label: "AI 반도체", desc: "AI 연산용 GPU·맞춤형 칩을 만드는 기업" }, { label: "클라우드", desc: "AI 서비스를 운영하는 대형 클라우드 기업" }],
    tickers: ["NVDA", "AVGO", "AMD", "TSM", "MSFT", "GOOGL"], must_include: [], exclude: ["TSLA"],
    tendency_final: "위험중립형", tendency_computed: "안정추구형", risk_tolerance: "moderate", vol_pref: "low",
    vol_pref_reason_ko: "요청 문장에 \"변동성이 너무 크지 않았으면\"이 있어, 투자성향의 기본 기준(중간 변동성 기준) 대신 낮은 변동성 기준을 적용했습니다.",
    loss_reaction: "hold", experience: "beginner",
    capital: { amount: 30_000_000, currency: "KRW", monthly: 0, day: 25 }, fx_bt: 1418,
    horizon_years: 3, backtest_years: 1, max_dd: 0.3, target_return: 0.12, benchmark: "SPY", max_weight: 0.3, template: "momentum", baseline: "market_cap", news: true,
    drift_shift: -0.04, bench_drift: 0.3,
    qa: [{ question_ko: "손실이 나면 어떻게 하시겠어요?", answer_ko: "일부만 줄이고 지켜볼게요", applied_ko: "손실 시 대응: 보유" }],
    messages: [{ text: "테슬라는 빼 주세요", outcome: "needs_confirmation", changes_ko: [], note_ko: "테슬라는 이번 테마 후보에 없어 제외 목록에만 추가할지 확인이 필요합니다." }],
    profile_version: 4,
  },
  {
    id: "mock_rep_none", run_id: "mock_run_none", request_id: "mock_req_none", created_at: "2026-10-30", key: "none", label_ko: "추천안 없음 · 허용 손실 5%", doc_version: 2,
    idea: "배당을 꾸준히 주는 안정적인 기업에 투자하고 싶어요. 손실은 5% 이내였으면 좋겠어요.",
    auto_name_ko: "안정 배당 기업 투자",
    themes: [{ label: "배당 안정 기업", desc: "오랫동안 배당을 이어 온 대형 기업" }],
    tickers: ["JNJ", "KO", "XOM", "JPM"], must_include: [], exclude: [],
    tendency_final: "안정형", tendency_computed: "안정형", risk_tolerance: "conservative", vol_pref: "low", vol_pref_reason_ko: null,
    loss_reaction: "sell", experience: "none",
    capital: { amount: 10_000_000, currency: "KRW", monthly: 300_000, day: 10 }, fx_bt: 1352,
    horizon_years: 3, backtest_years: 3, max_dd: 0.05, target_return: 0.06, benchmark: "SPY", max_weight: 0.3, template: "high_dividend", baseline: "equal_weight", news: true,
    drift_shift: -0.02, bench_drift: 0.1,
    qa: [{ question_ko: "허용 손실 5%는 주식만으로는 지키기 어려울 수 있어요. 그대로 둘까요?", answer_ko: "그대로 둘게요", applied_ko: "손실 감내 수준 5% 유지" }],
    messages: [],
    profile_version: 3,
  },
  {
    id: "mock_rep_newsoff", run_id: "mock_run_newsoff", request_id: "mock_req_newsoff", created_at: "2026-10-29", key: "news_off", label_ko: "뉴스 반영 꺼짐 · 공격투자형(변동성 상한 없음)", doc_version: 2,
    idea: "전기차와 2차전지 기업에 공격적으로 투자하고 싶어요.",
    auto_name_ko: "전기차·2차전지 성장 투자",
    themes: [{ label: "전기차", desc: "전기차를 만드는 완성차 기업" }, { label: "2차전지", desc: "전기차 배터리를 만드는 기업" }],
    tickers: ["TSLA", "005380", "373220", "AMZN", "NVDA"], must_include: ["TSLA"], exclude: [],
    tendency_final: "공격투자형", tendency_computed: "적극투자형", risk_tolerance: "aggressive", vol_pref: "high", vol_pref_reason_ko: null,
    loss_reaction: "buy_more", experience: "intermediate",
    capital: { amount: 15_000, currency: "USD", monthly: 500, day: 1 }, fx_bt: 1352,
    horizon_years: 10, backtest_years: 3, max_dd: 0.45, target_return: 0.15, benchmark: "SPY", max_weight: 0.3, template: "momentum", baseline: "equal_weight", news: false,
    drift_shift: 0.03, bench_drift: 0.1,
    qa: [],
    messages: [],
    profile_version: 4,
  },
  {
    id: "mock_rep_legacy", run_id: "mock_run_legacy", request_id: "mock_req_legacy", created_at: "2026-09-12", key: "legacy", label_ko: "이전 형식(v1) 리포트", doc_version: 1,
    idea: "미국 대형 기술주에 장기 투자하고 싶어요.",
    auto_name_ko: "미국 대형 기술주 장기 투자",
    themes: [{ label: "대형 기술주", desc: "시가총액이 큰 미국 기술 기업" }],
    tickers: ["AAPL", "MSFT", "GOOGL", "AMZN", "META"], must_include: [], exclude: [],
    tendency_final: "적극투자형", tendency_computed: "적극투자형", risk_tolerance: "aggressive", vol_pref: "high", vol_pref_reason_ko: null,
    loss_reaction: "hold", experience: "intermediate",
    capital: { amount: 10_000_000, currency: "KRW", monthly: 0, day: 25 }, fx_bt: 1352,
    horizon_years: 10, backtest_years: 3, max_dd: 0.3, target_return: 0.1, benchmark: "SPY", max_weight: 0.3, template: "quality", baseline: "market_cap", news: false,
    drift_shift: 0, bench_drift: 0.1,
    qa: [], messages: [], profile_version: 2,
  },
  {
    id: "mock_rep_revised", run_id: "mock_run_revised", request_id: "mock_req_revised", created_at: "2026-11-01", key: "revised", label_ko: "수정 요청 결과 (원안 비교 있음)", doc_version: 2,
    idea: "미국 반도체 장비와 메모리 기업에 나눠 투자하고 싶어요. 한 종목에 너무 몰리지 않았으면 좋겠어요.",
    auto_name_ko: "미국 반도체 장비·메모리 분산 투자 (수정안)",
    themes: [{ label: "반도체 장비", desc: "증착·식각·노광·검사 장비를 만드는 기업" }, { label: "메모리 반도체", desc: "D램·낸드·HBM을 만드는 기업" }],
    tickers: ["NVDA", "MU", "AMAT", "LRCX", "KLAC", "ASML"], must_include: ["MU"], exclude: [],
    tendency_final: "위험중립형", tendency_computed: "위험중립형", risk_tolerance: "moderate", vol_pref: "medium", vol_pref_reason_ko: null,
    loss_reaction: "hold", experience: "beginner",
    capital: { amount: 20_000_000, currency: "KRW", monthly: 500_000, day: 25 }, fx_bt: 1352,
    horizon_years: 5, backtest_years: 3, max_dd: 0.3, target_return: 0.1, benchmark: "SPY", max_weight: 0.2, template: "momentum", baseline: "market_cap", news: true,
    drift_shift: 0.04, bench_drift: 0.11,
    qa: [], messages: [],
    profile_version: 4, base_report_id: "mock_rep_normal", revision_text: "종목당 상한을 20%로 낮추고, 허용 손실을 30%로 줄여 주세요.",
  },
]

/** 모의투자 시나리오: 같은 리포트(mock_rep_normal)에서 여러 개를 시작한 경우 포함. */
export interface PaperScenario {
  id: string; report_id: string; strategy: "chosen" | Weighting | string; start_date: string
  capital: { amount: number; currency: "KRW" | "USD"; monthly: number }
  name: { mode: "linked" } | { mode: "custom"; name_ko: string }
  status: "active" | "stopped"
  fx_gaps: string[]          // 환율 자료가 없는 날 (직전 환율로 대체)
  fx_missing_until?: string  // 이 날까지는 환율이 아예 없음 (환산 불가)
}
export const PAPERS: PaperScenario[] = [
  { id: "mock_paper_a1", report_id: "mock_rep_normal", strategy: "chosen", start_date: "2026-06-01", capital: { amount: 10_000_000, currency: "KRW", monthly: 300_000 }, name: { mode: "linked" }, status: "active", fx_gaps: ["2026-08-15", "2026-10-03", "2026-10-09"] },
  { id: "mock_paper_a2", report_id: "mock_rep_normal", strategy: "market_cap", start_date: "2026-08-03", capital: { amount: 5_000_000, currency: "KRW", monthly: 0 }, name: { mode: "custom", name_ko: "시가총액 비중 비교용" }, status: "active", fx_gaps: ["2026-10-03"] },
  { id: "mock_paper_a3", report_id: "mock_rep_normal", strategy: "chosen", start_date: "2026-09-01", capital: { amount: 3_000, currency: "USD", monthly: 0 }, name: { mode: "linked" }, status: "active", fx_gaps: [], fx_missing_until: "2026-09-02" },
  { id: "mock_paper_b1", report_id: "mock_rep_caution", strategy: "chosen", start_date: "2026-07-01", capital: { amount: 30_000_000, currency: "KRW", monthly: 0 }, name: { mode: "linked" }, status: "stopped", fx_gaps: ["2026-08-15"] },
]

/** 분석 진행 화면 시나리오 (상태만 다르고 같은 요청: 정상 추천 시나리오의 아이디어). */
export const RUN_STATES = [
  { id: "mock_run_queued", state: "queued", label_ko: "대기 중" },
  { id: "mock_run_running", state: "running", label_ko: "분석 진행 중 (5단계 완료)" },
  { id: "mock_run_notices", state: "running", label_ko: "확인할 점 발생 (경고 9건, 중복 포함)" },
  { id: "mock_run_failed", state: "failed", label_ko: "분석 실패" },
  { id: "mock_run_cancelled", state: "cancelled", label_ko: "분석 취소" },
] as const

export const reportScenario = (id: string) => REPORTS.find((r) => r.id === id || r.run_id === id) ?? null
