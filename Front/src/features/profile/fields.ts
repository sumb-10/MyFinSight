// 투자조건 항목 정의 한 곳: 이름 · 범위 · 설명. 내 투자조건 화면(저장)과 홈 「상세 조건」 창(이번 분석만)이 같이 읽는다.
// 키는 서버 필드 경로("risk.max_drawdown_tolerance"). 비율 범위는 분수(0.2 = 20%), 서버 검사(HARD)보다 좁거나 같게 둔다.
// 두 화면에서 이름·범위·안내가 어긋나던 것(2026-11-16 비교)을 여기서만 고치게 하려는 표다.

export interface PctFieldDef { label: string; min: number; max: number; step: number; info: string }

/** 비율 항목 (슬라이더 + % 입력). PercentSlider 에 그대로 펼쳐 넣는다: <PercentSlider {...PCT["risk.target_annual_return"]} … /> */
export const PCT = {
  "risk.max_drawdown_tolerance": { label: "손실 감내 수준 (최대 하락 폭)", min: 0.05, max: 0.6, step: 0.01, info: "투자금이 가장 높았던 때보다 이만큼까지 떨어지는 것은 견딜 수 있다는 기준입니다." },
  "risk.target_annual_return": { label: "목표 연수익률", min: 0, max: 0.3, step: 0.01, info: "1년에 평균 이 정도 수익을 기대한다는 기준입니다." },
  "constraints.max_weight_per_stock": { label: "종목당 상한", min: 0.05, max: 1, step: 0.01, info: "한 종목에 넣을 수 있는 최대 비율" },
  "constraints.max_weight_per_sector": { label: "섹터당 상한", min: 0.1, max: 1, step: 0.05, info: "같은 업종(섹터)에 넣을 수 있는 최대 비율" },
  "constraints.min_cash_ratio": { label: "최소 현금 비율", min: 0, max: 0.5, step: 0.05, info: "주식에 넣지 않고 현금으로 남길 최소 비율" },
} satisfies Record<string, PctFieldDef>

/** 종목 수 (최소·목표·최대 모두 같은 범위) */
export const HOLDINGS = { min: 1, max: 50, info: "목표만큼 고르되, 조건에 맞는 후보가 부족하면 최소~최대 범위 안에서 조정합니다." }

/** 그 밖의 항목 이름·안내 */
export const LABEL = {
  initial_amount: "처음 투자할 금액",
  template: "어떤 기업에 투자하고 싶나요?",
  weighting: "선정한 기업에 투자금을 어떻게 나눌까요?",
  exclude_tickers: "제외할 종목",
  must_include_tickers: "반드시 포함할 종목",
  exclude_themes: "제외할 테마",
}

export const THEME_FIELD = {
  label: LABEL.exclude_themes,
  placeholder: "예: 담배, 도박 · Enter로 추가",
  info: "섹터보다 좁은 분야를 뺄 때 씁니다. 적은 표현을 분석 모델(AI)이 산업 분류·키워드 규칙으로 바꿔 해당 기업을 후보에서 뺍니다. 정해진 목록은 없으며, 실제로 빠진 기업은 리포트에서 확인할 수 있습니다.",
  normalize: (s: string) => s.trim().toLowerCase(),
}

export const TICKER_PLACEHOLDER = { exclude: "예: TSLA, 005930 · Enter로 추가", include: "예: AAPL · Enter로 추가" }
