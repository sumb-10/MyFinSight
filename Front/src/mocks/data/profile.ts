// 목업 투자조건(프로필)과 변경 이력. 버전마다 실제 값 전체를 갖고 있어 변경 전후 비교가 가능하다 (지금 서버는 현재 버전 값만 준다).
import type { Constraints, ProfileFields, ProfileVersion, ProfileView } from "../../api/types"

const constraints = (over: Partial<Constraints> = {}): Constraints => ({
  universe: ["SP500", "NASDAQ100"], asset_types: ["stock"], num_holdings: { target: 6, min: 4, max: 10 }, max_weight_per_stock: 0.25, max_weight_per_sector: 1,
  min_cash_ratio: 0, exclude_tickers: [], exclude_sectors: [], exclude_themes: [], must_include_tickers: [], rebalance: { count: 1, unit: "1m" },
  allow_leverage: false, allow_short: false, min_market_cap_usd: 2_000_000_000, min_avg_daily_volume_usd: 10_000_000, ...over,
})

const base: ProfileFields = {
  profile: { user_id: "mock", age_band: "30s", investment_experience: "beginner", financial_knowledge: "basic", investable_ratio_of_assets: 0.3 },
  capital: { initial_amount: 10_000_000, currency: "KRW", monthly_contribution: 300_000, contribution_day: 25 },
  horizon: { target_years: 5, purpose: "wealth_growth", backtest_years: 3 },
  risk: { risk_tolerance: "conservative", max_drawdown_tolerance: 0.2, loss_reaction: "hold", target_annual_return: 0.08, benchmark: "SPY" },
  constraints: constraints(), strategy_preference: { template: "momentum", baseline_weighting: "equal_weight", use_news_tilt: true },
  diagnosis: { answers: { loss: 1, reaction: 1, priority: 1 }, computed_tendency: "안정추구형", final_tendency: "안정추구형", memo: "" },
  risk_type_computed: "conservative", risk_type_overridden: false,
}

/** 버전 1~4 (변경 이력 비교용). 각 버전이 무엇을 바꿨는지 note 에 적는다. */
export const PROFILE_VERSIONS: ProfileVersion[] = [
  { ...base, version: 1, created_at: "2026-09-01T10:00:00", note: "첫 등록" },
  { ...base, capital: { ...base.capital, initial_amount: 20_000_000, monthly_contribution: 500_000 }, version: 2, created_at: "2026-09-20T21:10:00", note: "투자금 늘림" },
  { ...base, capital: { ...base.capital, initial_amount: 20_000_000, monthly_contribution: 500_000 }, risk: { ...base.risk, risk_tolerance: "moderate", max_drawdown_tolerance: 0.3, target_annual_return: 0.1 }, diagnosis: { answers: { loss: 2, reaction: 2, priority: 2 }, computed_tendency: "위험중립형", final_tendency: "위험중립형", memo: "진단 다시 함" }, risk_type_computed: "moderate", version: 3, created_at: "2026-10-12T08:30:00", note: "투자성향 다시 진단" },
  { ...base, capital: { ...base.capital, initial_amount: 20_000_000, monthly_contribution: 500_000 }, risk: { ...base.risk, risk_tolerance: "moderate", max_drawdown_tolerance: 0.3, target_annual_return: 0.1 }, diagnosis: { answers: { loss: 2, reaction: 2, priority: 2 }, computed_tendency: "위험중립형", final_tendency: "위험중립형", memo: "진단 다시 함" }, risk_type_computed: "moderate", constraints: constraints({ must_include_tickers: ["NVDA"], exclude_tickers: ["TSLA"], max_weight_per_stock: 0.3 }), strategy_preference: { template: "momentum", baseline_weighting: "market_cap", use_news_tilt: true }, version: 4, created_at: "2026-10-28T19:45:00", note: "필수 포함·제외 종목 추가" },
]

/** 「초기 투자금 0원」 시나리오: 같은 이력 뒤에 0원 + 매월 추가 투자금 버전이 현재. 서버는 0원을 받지 않는다(gt=0) — 목업에서만. */
export const ZERO_CAPITAL_VERSION: ProfileVersion = { ...PROFILE_VERSIONS[3], capital: { initial_amount: 0, currency: "KRW", monthly_contribution: 1_000_000, contribution_day: 25 }, version: 5, created_at: "2026-11-02T09:00:00", note: "초기 투자금 0원으로 시작" }

export function profileView(versions: ProfileVersion[]): ProfileView {
  const cur = versions[versions.length - 1]
  return { profile_id: "mock_profile", current_version: cur.version, profile: cur, versions: versions.map((v) => ({ version: v.version, created_at: v.created_at, note: v.note ?? null })) }
}
