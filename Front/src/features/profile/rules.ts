// 투자조건 검사 규칙 한 곳. 내 투자조건 화면(validateProfile)과 홈 「상세 조건」 창(validate)이 같이 쓴다.
// 서버 HARD 검사(backend/analysis/schemas/request.py Constraints._feasible 등)와 같은 규칙을 화면에서 먼저 알려 준다.
// 오류 위치는 서버 필드 경로로 돌려주고, 각 화면이 자기 입력 칸으로 옮긴다.

export interface RuleInput {
  initial_amount: number; monthly_contribution: number
  target_years: number; backtest_years: number | null  // null: 이 화면에서 따로 검사 (상세 조건 창의 「특정 기간」)
  num: { min: number; target: number; max: number }
  max_stock: number; max_sector: number; min_cash: number  // 분수 (0.2 = 20%)
  universe: string[]; exclude: string[]; must_include: string[]
}

export type RulePath =
  | "capital.initial_amount" | "horizon.target_years" | "horizon.backtest_years"
  | "constraints.num_holdings.min" | "constraints.num_holdings.target"
  | "constraints.max_weight_per_stock" | "constraints.max_weight_per_sector" | "constraints.universe"
  | "constraints.exclude_tickers" | "constraints.must_include_tickers"

export interface RuleError { path: RulePath; message: string }

/** allowZero: 제안 규칙 — 초기 투자금 0원 + 매월 추가 투자 (실제 서버도 같은 규칙: 첫 적립일에 처음 매수, 이슈 #14 의 3번). */
export function checkConditions(v: RuleInput, { allowZero = false }: { allowZero?: boolean } = {}): RuleError[] {
  const e: RuleError[] = []
  if (allowZero && v.initial_amount === 0) { if (!(v.monthly_contribution > 0)) e.push({ path: "capital.initial_amount", message: "처음 투자금을 0원으로 하려면 매월 추가 투자금을 정해 주세요" }) }
  else if (!(v.initial_amount > 0)) e.push({ path: "capital.initial_amount", message: "투자금은 0보다 커야 합니다" })
  if (!(v.target_years >= 1 && v.target_years <= 10)) e.push({ path: "horizon.target_years", message: "투자기간은 1~10년입니다" })
  if (v.backtest_years !== null && !(v.backtest_years > 0 && v.backtest_years <= 20)) e.push({ path: "horizon.backtest_years", message: "백테스트 기간은 0보다 크고 20년 이하입니다" })
  if (!v.universe.length) e.push({ path: "constraints.universe", message: "투자 대상 지수를 하나 이상 고르세요" })
  if (v.max_sector < v.max_stock) e.push({ path: "constraints.max_weight_per_sector", message: "섹터당 상한은 종목당 상한 이상이어야 합니다" })
  if (v.num.min > v.num.max) e.push({ path: "constraints.num_holdings.min", message: "최소 종목 수가 최대 종목 수보다 큽니다" })
  else if (v.num.target < v.num.min || v.num.target > v.num.max) e.push({ path: "constraints.num_holdings.target", message: `목표 종목 수는 최소 ${v.num.min} ~ 최대 ${v.num.max}개 사이여야 합니다` })
  const invested = 1 - v.min_cash
  if (v.max_stock * v.num.min < invested - 1e-9) {
    const need = Math.ceil((invested / v.num.min) * 100 - 1e-9)
    e.push({ path: "constraints.max_weight_per_stock", message: `종목당 상한 × 최소 종목 수가 투자 비율보다 작아 돈을 다 배분할 수 없습니다 (상한을 ${need}% 이상으로 올리거나 최소 종목 수를 늘려 주세요)` })
  }
  const clash = v.must_include.filter((t) => v.exclude.includes(t))
  if (clash.length) e.push({ path: "constraints.exclude_tickers", message: `같은 종목이 반드시 포함과 제외에 함께 있습니다: ${clash.join(", ")}` })
  if (v.must_include.length > v.num.max) e.push({ path: "constraints.must_include_tickers", message: `반드시 포함할 종목(${v.must_include.length}개)이 최대 종목 수(${v.num.max}개)보다 많습니다` })
  return e
}
