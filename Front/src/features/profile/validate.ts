import type { ProfileFields } from "../../api/types"
import { checkConditions } from "./rules"

/**
 * 저장 전에 화면에서 하는 투자조건 검사. 키는 서버 오류 필드와 같은 점 경로("capital.initial_amount").
 * 4단계 폼과 대화형 설정의 요약이 같은 규칙을 쓰고, 규칙 자체는 홈 상세 조건 창과 같이 쓰는 rules.ts 에 있다.
 * 종목 수 오류(최소·목표)는 이 화면에서 한 칸(constraints.num_holdings)에 보여 준다.
 */
export function validateProfile(form: ProfileFields, { allowZero = false }: { allowZero?: boolean } = {}): Record<string, string> {
  const c = form.constraints
  const errors = checkConditions({
    initial_amount: form.capital.initial_amount, monthly_contribution: form.capital.monthly_contribution,
    target_years: form.horizon.target_years, backtest_years: form.horizon.backtest_years,
    num: c.num_holdings, max_stock: c.max_weight_per_stock, max_sector: c.max_weight_per_sector, min_cash: c.min_cash_ratio,
    universe: c.universe, exclude: c.exclude_tickers, must_include: c.must_include_tickers,
  }, { allowZero })
  const e: Record<string, string> = {}
  for (const { path, message } of errors) {
    const key = path.startsWith("constraints.num_holdings") ? "constraints.num_holdings" : path
    e[key] ??= message
  }
  return e
}
