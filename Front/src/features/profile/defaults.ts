import type { ProfileFields } from "../../api/types"

/** 처음 설정할 때 채워 두는 기본 투자조건. 4단계 폼과 대화형 설정이 같은 값에서 시작한다. */
export const DEFAULT_FORM: ProfileFields = {
  profile: { user_id: "default", age_band: "30s", investment_experience: "beginner", financial_knowledge: "basic", investable_ratio_of_assets: 0.3 },
  capital: { initial_amount: 10_000_000, currency: "KRW", trading_currency: "USD", monthly_contribution: 0, contribution_day: 25 },
  horizon: { target_years: 5, purpose: "wealth_growth", backtest_years: 3 },
  risk: { risk_tolerance: "moderate", max_drawdown_tolerance: 0.2, loss_reaction: "hold", target_annual_return: 0.08, benchmark: "SPY" },
  constraints: { universe: ["SP500", "NASDAQ100"], asset_types: ["stock"], num_holdings: { target: 10, min: 8, max: 12 }, max_weight_per_stock: 0.15, max_weight_per_sector: 0.4, min_cash_ratio: 0, exclude_tickers: [], exclude_sectors: [], exclude_themes: [], must_include_tickers: [], rebalance: { count: 1, unit: "1q" }, allow_leverage: false, allow_short: false, min_market_cap_usd: 0, min_avg_daily_volume_usd: 0 },
  strategy_preference: { template: "momentum", baseline_weighting: "equal_weight", use_news_tilt: true },
  diagnosis: { answers: {}, computed_tendency: "위험중립형", final_tendency: "위험중립형", memo: "" },
  risk_type_computed: "moderate",
  risk_type_overridden: false,
}
