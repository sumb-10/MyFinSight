import { describe, expect, it } from "vitest"
import { MockService } from "./services/MockService"

// 조건 바꾸기(덮어쓰기)가 목업 조건 행에 바로 반영되고, 답변으로 바뀐 조건과 함께 남는지.

const changed = (rows: { label_ko: string; value_ko: string; changed: boolean }[] | undefined) => Object.fromEntries((rows ?? []).filter((r) => r.changed).map((r) => [r.label_ko, r.value_ko]))

describe("목업 조건 바꾸기", () => {
  it("바꾼 조건을 바로 조건 행에 넣고, 답변으로 바뀐 조건과 합쳐 보여 준다", async () => {
    const s = new MockService({ latencyMs: 0, persist: false })
    const a = await s.updateOverrides("mock_req_asking", { "capital.initial_amount": 30_000_000, "horizon.target_years": 7 })
    expect(changed(a.conditions)).toEqual({ 투자금: "30,000,000원", 투자기간: "7년" })
    expect(a.overrides).toEqual({ "capital.initial_amount": 30_000_000, "horizon.target_years": 7 })

    const q = a.questions.find((x) => x.field === "constraints.max_weight_per_stock")!
    const b = await s.answer("mock_req_asking", q.seq, { option_value: q.options.find((o) => o.label_ko === "25%")!.value })
    expect(changed(b.conditions)).toMatchObject({ 투자금: "30,000,000원", 투자기간: "7년", "종목당 최대 비중": "25%" })

    const c = await s.updateOverrides("mock_req_asking", { "capital.initial_amount": null, "horizon.target_years": null })
    expect(changed(c.conditions)).toEqual({ "종목당 최대 비중": "25%" })
    expect(c.overrides).toEqual({})
  })

  it("새 요청을 만들 때 넣은 조건도 처음부터 반영한다", async () => {
    const s = new MockService({ latencyMs: 0, persist: false })
    const d = await s.createRequest({ idea: "반도체", overrides: { "horizon.target_years": 10 } })
    expect(changed(d.conditions)).toEqual({ 투자기간: "10년" })
  })

  it("조건 바꾸기로 바꿀 수 있는 항목은 모두 「달라진 조건」에 나온다 (분석 기준일은 실제 서버처럼 행이 없다)", async () => {
    const samples: Record<string, unknown> = {
      "capital.initial_amount": 30_000_000, "capital.currency": "USD", "capital.monthly_contribution": 900_000, "capital.contribution_day": 10, "horizon.target_years": 7, "horizon.backtest_years": 5,
      "risk.risk_tolerance": "aggressive", "risk.max_drawdown_tolerance": 0.4, "risk.target_annual_return": 0.12, "risk.benchmark": "QQQ", "constraints.universe": ["NASDAQ100"],
      "constraints.num_holdings.target": 9, "constraints.num_holdings": { target: 15, min: 8, max: 15 }, "constraints.max_weight_per_stock": 0.2, "constraints.max_weight_per_sector": 0.5,
      "strategy_preference.template": "quality", "strategy_preference.baseline_weighting": "equal_weight", "strategy_preference.use_news_tilt": false, "constraints.exclude_tickers": ["AAPL"],
      "constraints.exclude_themes": ["tobacco"], "constraints.exclude_sectors": ["에너지"], "constraints.min_market_cap_usd": 5e9, "constraints.min_avg_daily_volume_usd": 2e7, "constraints.min_cash_ratio": 0.1, "constraints.rebalance": { count: 1, unit: "1q" },
    }
    const base = new MockService({ latencyMs: 0, persist: false })
    expect(changed((await base.getRequest("mock_req_asking")).conditions)).toEqual({})  // 아무것도 안 바꾸면 달라진 조건 없음
    for (const [k, v] of Object.entries(samples)) {
      const s = new MockService({ latencyMs: 0, persist: false })
      const d = await s.updateOverrides("mock_req_asking", { [k]: v })
      expect(Object.keys(changed(d.conditions)).length, k).toBeGreaterThan(0)
    }
  })
})
