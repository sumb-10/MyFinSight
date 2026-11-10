import type { ProfileFields } from "../../api/types"

/**
 * 저장 전에 화면에서 하는 투자조건 검사. 키는 서버 오류 필드와 같은 점 경로("capital.initial_amount").
 * 4단계 폼과 대화형 설정의 요약이 같은 규칙을 쓴다.
 * allowZero: 제안 규칙 — 초기 투자금 0원 + 매월 추가 투자 (실제 서버도 같은 규칙: 첫 적립일에 처음 매수, 이슈 #14 의 3번).
 */
export function validateProfile(form: ProfileFields, { allowZero = false }: { allowZero?: boolean } = {}): Record<string, string> {
  const e: Record<string, string> = {}
  const c = form.constraints
  if (allowZero && form.capital.initial_amount === 0) { if (!(form.capital.monthly_contribution > 0)) e["capital.initial_amount"] = "처음 투자금을 0원으로 하려면 매월 추가 투자금을 정해 주세요" }
  else if (!(form.capital.initial_amount > 0)) e["capital.initial_amount"] = "투자금은 0보다 커야 합니다"
  if (!(form.horizon.target_years >= 1 && form.horizon.target_years <= 10)) e["horizon.target_years"] = "투자기간은 1~10년입니다"
  if (!(form.horizon.backtest_years > 0 && form.horizon.backtest_years <= 20)) e["horizon.backtest_years"] = "백테스트 기간은 0보다 크고 20년 이하입니다"
  if (!(c.num_holdings.min <= c.num_holdings.target && c.num_holdings.target <= c.num_holdings.max)) e["constraints.num_holdings"] = "최소 ≤ 목표 ≤ 최대 순서여야 합니다"
  if (c.max_weight_per_stock * c.num_holdings.min < 1 - c.min_cash_ratio - 1e-9) e["constraints.max_weight_per_stock"] = "종목당 상한 × 최소 종목 수가 투자 비율보다 작아 비중을 채울 수 없습니다"
  if (c.max_weight_per_sector < c.max_weight_per_stock) e["constraints.max_weight_per_sector"] = "섹터당 상한은 종목당 상한 이상이어야 합니다"
  if (!c.universe.length) e["constraints.universe"] = "유니버스를 하나 이상 고르세요"
  const clash = c.must_include_tickers.filter((t) => c.exclude_tickers.includes(t))
  if (clash.length) e["constraints.exclude_tickers"] = `같은 종목이 필수 포함과 제외에 함께 있습니다: ${clash.join(", ")}`
  return e
}
