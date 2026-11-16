import { describe, expect, it } from "vitest"
import { checkConditions, type RuleInput } from "./rules"
import { validateProfile } from "./validate"
import { DEFAULT_FORM } from "./defaults"

// 내 투자조건 화면과 홈 상세 조건 창이 같이 쓰는 검사 규칙 (rules.ts)

const ok: RuleInput = {
  initial_amount: 10_000_000, monthly_contribution: 0, target_years: 3, backtest_years: 3,
  num: { min: 8, target: 10, max: 12 }, max_stock: 0.15, max_sector: 0.4, min_cash: 0,
  universe: ["SP500"], exclude: [], must_include: [],
}
const paths = (v: Partial<RuleInput>) => checkConditions({ ...ok, ...v }).map((e) => e.path)

describe("투자조건 검사 규칙", () => {
  it("문제가 없으면 오류가 없다", () => {
    expect(checkConditions(ok)).toEqual([])
  })

  it("서버 HARD 규칙과 같은 것을 잡는다", () => {
    expect(paths({ initial_amount: 0 })).toEqual(["capital.initial_amount"])
    expect(paths({ target_years: 11 })).toEqual(["horizon.target_years"])
    expect(paths({ universe: [] })).toEqual(["constraints.universe"])
    expect(paths({ max_sector: 0.1 })).toEqual(["constraints.max_weight_per_sector"])
    expect(paths({ num: { min: 13, target: 10, max: 12 } })).toEqual(["constraints.num_holdings.min"])
    expect(paths({ num: { min: 8, target: 15, max: 12 } })).toEqual(["constraints.num_holdings.target"])
    expect(paths({ exclude: ["TSLA"], must_include: ["TSLA"] })).toEqual(["constraints.exclude_tickers"])
    expect(paths({ must_include: ["A", "B", "C"], num: { min: 2, target: 2, max: 2 }, max_stock: 0.5, max_sector: 0.5 })).toEqual(["constraints.must_include_tickers"])
  })

  it("종목당 상한 × 최소 종목 수가 모자라면 필요한 상한을 알려 준다", () => {
    const [e] = checkConditions({ ...ok, max_stock: 0.1, num: { min: 5, target: 5, max: 5 }, min_cash: 0.05 })
    expect(e.path).toBe("constraints.max_weight_per_stock")
    expect(e.message).toContain("상한을 19% 이상으로")  // 95% ÷ 5종목
  })

  it("백테스트 기간을 null 로 주면 검사하지 않는다 (상세 조건 창의 「특정 기간」은 그 창이 따로 본다)", () => {
    expect(paths({ backtest_years: 30 })).toEqual(["horizon.backtest_years"])
    expect(paths({ backtest_years: null })).toEqual([])
  })

  it("내 투자조건 화면은 종목 수 오류를 한 칸에, 꼭 넣을 종목 수 초과도 이제 잡는다", () => {
    const form = structuredClone(DEFAULT_FORM)
    form.constraints.num_holdings = { min: 8, target: 20, max: 12 }
    form.constraints.must_include_tickers = Array.from({ length: 13 }, (_, i) => `T${i}`)
    const e = validateProfile(form)
    expect(e["constraints.num_holdings"]).toBe("목표 종목 수는 최소 8 ~ 최대 12개 사이여야 합니다")
    expect(e["constraints.must_include_tickers"]).toBe("반드시 포함할 종목(13개)이 최대 종목 수(12개)보다 많습니다")
  })
})
