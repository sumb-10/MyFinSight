import { describe, expect, it } from "vitest"
import { overrideText, toOverrides } from "./DetailConditions"
import type { ProfileVersion } from "../../api/types"

const profile = {
  version: 1, created_at: "2026-01-01", profile: { age_band: "30s", investment_experience: "beginner", financial_knowledge: "basic", investable_ratio_of_assets: 0.3 },
  capital: { initial_amount: 10_000_000, currency: "KRW", monthly_contribution: 500_000, contribution_day: 25 }, horizon: { target_years: 3, purpose: "wealth_growth", backtest_years: 5 },
  risk: { risk_tolerance: "moderate", max_drawdown_tolerance: 0.3, loss_reaction: "hold", target_annual_return: 0.12, benchmark: "SPY" },
  constraints: { universe: ["SP500", "NASDAQ100", "KOSPI200"], asset_types: ["stock"], num_holdings: { target: 12, min: 2, max: 16 }, max_weight_per_stock: 0.77, max_weight_per_sector: 0.95, min_cash_ratio: 0, exclude_tickers: [], exclude_sectors: [], exclude_themes: ["tobacco", "gambling"], must_include_tickers: [], rebalance: { count: 1, unit: "2w" }, allow_leverage: false, allow_short: false, min_market_cap_usd: 5_000_000_000, min_avg_daily_volume_usd: 20_000_000 },
  strategy_preference: { template: "momentum", baseline_weighting: "market_cap", use_news_tilt: true }, risk_type_computed: "moderate", risk_type_overridden: false,
} as unknown as ProfileVersion

describe("DetailConditions.toOverrides", () => {
  const base = { initial_amount: 10_000_000, currency: "KRW" as const, monthly_contribution: 500_000, contribution_day: 25, target_years: 3, bt_mode: "recent" as const, backtest_years: 5, bt_start_year: 2021, bt_end_year: 2025,
    risk_tolerance: "moderate" as const, max_drawdown_pct: 30, target_return_pct: 12, benchmark: "SPY", universe: ["SP500", "NASDAQ100", "KOSPI200"] as ("SP500" | "NASDAQ100" | "KOSPI200")[], num_target: 12, num_min: 2, num_max: 16, max_stock_pct: 77, max_sector_pct: 95,
    template: "momentum" as const, weighting: "market_cap" as const, use_news_tilt: true, exclude: "", exclude_themes: "tobacco, gambling", exclude_sectors: "", min_market_cap_b: 5, min_adv_m: 20, min_cash_pct: 0, rebalance_count: 1, rebalance_unit: "2w" }
  it("프로필과 같으면 덮어쓰기가 없다", () => {
    expect(toOverrides(base, profile)).toEqual({})
  })
  it("숨은 항목(제외 테마·시총·거래대금·현금·리밸런싱)을 바꾸면 그 경로만 나온다", () => {
    const o = toOverrides({ ...base, exclude_themes: "", min_market_cap_b: 0, min_adv_m: 0, min_cash_pct: 10, rebalance_count: 1, rebalance_unit: "1q", universe: ["SP500", "NASDAQ100"] }, profile)
    expect(o).toEqual({ "constraints.exclude_themes": [], "constraints.min_market_cap_usd": 0, "constraints.min_avg_daily_volume_usd": 0, "constraints.min_cash_ratio": 0.1, "constraints.rebalance": { count: 1, unit: "1q" }, "constraints.universe": ["SP500", "NASDAQ100"] })
    expect(overrideText("constraints.rebalance", { count: 1, unit: "1q" })).toBe("1×분기")
    expect(overrideText("constraints.min_market_cap_usd", 0)).toBe("제한 없음")
    expect(overrideText("constraints.exclude_themes", [])).toBe("없음")
  })
  it("종목 수 범위를 바꾸면 통째로, 목표만 바꾸면 target 경로만 나온다 (라운드 5)", () => {
    expect(toOverrides({ ...base, num_target: 8 }, profile)).toEqual({ "constraints.num_holdings.target": 8 })
    expect(toOverrides({ ...base, num_target: 20, num_max: 20 }, profile)).toEqual({ "constraints.num_holdings": { target: 20, min: 2, max: 20 } })
    expect(overrideText("constraints.num_holdings", { target: 20, min: 2, max: 20 })).toBe("목표 20 (2~20)")
  })
})
