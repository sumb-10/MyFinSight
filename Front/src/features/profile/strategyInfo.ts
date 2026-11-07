import type { StrategyPreference, Template, Weighting } from "../../api/types"

// 투자 전략 설정의 화면 문구. API 로 보내는 값은 enum 그대로이고, 여기서는 표시만 바꾼다.
// 이름은 쉬운 표현(name) 옆에 전문용어(short)를 괄호로 함께 보여 준다 — 나중에 금융 용어를 익힐 때도 쓰이게.
// 지표 정의는 backend/analysis/m2_data/metrics.py, 비중 방식은 m4_portfolio/math.py, 뉴스 반영 창은 settings.py(NewsSettings·DisclosureSettings) 기준.

export interface TemplateInfo { name: string; short: string; focus: string; desc: string; pros: string; caution: string; metric: string }
export interface WeightingInfo { name: string; short: string; desc: string; caution: string; example: number[]; exampleNote?: string }

const VALUATION_NOTE = "재무 자료가 쌓인 기간에만 백테스트할 수 있어 아주 오래된 기간은 고를 수 없습니다."

export const TEMPLATE_INFO: Record<Template, TemplateInfo> = {
  low_per: { name: "가격이 상대적으로 저평가된 기업", short: "저PER", focus: "저평가 기업 중심", desc: "벌어들이는 이익에 비해 주가가 낮은 기업을 고릅니다.", pros: "이미 많이 오른 기업보다 싸게 살 가능성을 노립니다.", caution: `주가가 낮은 데는 실적 악화 같은 이유가 있을 수 있습니다. ${VALUATION_NOTE}`, metric: "최근 12개월 이익 기준 PER (주가 ÷ 주당순이익, 낮을수록 우선, 적자 기업 제외)" },
  quality: { name: "수익성이 좋은 기업", short: "퀄리티", focus: "수익성 좋은 기업 중심", desc: "자기 돈(자기자본)으로 이익을 많이 내는 기업을 고릅니다.", pros: "돈을 잘 버는 체질의 기업에 집중합니다.", caution: `빚이 많아도 ROE 가 높게 나올 수 있고, 좋은 실적이 이미 주가에 반영돼 있을 수 있습니다. ${VALUATION_NOTE}`, metric: "최근 12개월 ROE (순이익 ÷ 자기자본, 높을수록 우선)" },
  momentum: { name: "최근 주가 상승세가 좋은 기업", short: "모멘텀", focus: "주가 상승세 좋은 기업 중심", desc: "최근 1년(가장 최근 한 달 제외) 동안 주가가 상대적으로 많이 오른 기업을 고릅니다.", pros: "오르는 흐름이 한동안 이어지는 경향을 활용합니다.", caution: "과거 상승이 미래의 수익을 보장하지는 않습니다. 흐름이 꺾이면 크게 떨어질 수 있습니다.", metric: "최근 12개월 수익률, 가장 최근 1개월 제외 (높을수록 우선)" },
  low_volatility: { name: "주가 변동이 작은 기업", short: "저변동성", focus: "주가 변동 작은 기업 중심", desc: "최근 주가의 오르내림이 작은 기업을 고릅니다.", pros: "하락장에서 덜 흔들리는 경향을 기대할 수 있습니다.", caution: "상승장에서는 수익이 상대적으로 낮을 수 있고, 변동이 작다고 손실이 없는 것은 아닙니다.", metric: "최근 60거래일 주가 변동성 (낮을수록 우선)" },
  high_dividend: { name: "배당을 많이 주는 기업", short: "고배당", focus: "배당 많은 기업 중심", desc: "주가에 비해 배당을 많이 주는 기업을 고릅니다.", pros: "배당 같은 현금 흐름을 중시할 때 맞습니다.", caution: `배당은 줄거나 중단될 수 있고, 주가가 크게 떨어져 배당수익률만 높아 보이는 경우도 있습니다. ${VALUATION_NOTE}`, metric: "최근 12개월 배당수익률 (주당배당금 ÷ 주가, 높을수록 우선)" },
}

export const WEIGHTING_INFO: Record<Weighting, WeightingInfo> = {
  equal_weight: { name: "모든 기업에 비슷하게 투자", short: "동일비중", desc: "선정한 기업에 같은 비율로 나눕니다.", caution: "단순하고 한 기업에 쏠리지 않지만, 기업의 크기나 위험 차이는 고려하지 않습니다.", example: [25, 25, 25, 25] },
  market_cap: { name: "규모가 큰 기업에 더 많이 투자", short: "시가총액비중", desc: "기업의 시가총액(시장에서 평가된 기업 가치)에 비례해 나눕니다. 주가지수와 비슷한 방식입니다.", caution: "큰 기업 몇 곳에 비중이 몰릴 수 있습니다.", example: [50, 30, 15, 5], exampleNote: "A가 가장 큰 기업" },
  inverse_volatility: { name: "주가 변동이 작은 기업에 더 많이 투자", short: "역변동성", desc: "주가 변동이 작은 기업일수록 더 많이, 변동이 큰 기업일수록 적게 담습니다.", caution: "변동이 작던 기업도 갑자기 크게 움직일 수 있습니다.", example: [35, 28, 22, 15], exampleNote: "A가 가장 덜 흔들리는 기업" },
  min_variance: { name: "전체 투자 위험을 줄이도록 비중 계산", short: "최소분산", desc: "기업들이 서로 얼마나 함께 오르내리는지까지 따져, 포트폴리오 전체의 변동이 가장 작아지도록 계산합니다.", caution: "과거 자료로 계산하므로 앞으로도 위험이 작다는 보장은 없고, 일부 기업에 비중이 몰리거나 아주 적게 담길 수 있습니다.", example: [40, 10, 35, 15], exampleNote: "함께 덜 움직이는 조합에 더 많이" },
}

export const NEWS_INFO = {
  title: "뉴스와 공시를 참고해 투자 비중 조정하기",
 
  desc: "투자 시점 이전에 발표된 기업 뉴스와 공시를 AI가 분석해 투자 비중을 조정하는 기능입니다. 근거가 부족하면 기준 비중을 그대로 씁니다.",
  off: "선택한 방식으로 나눈 기준 비중을 그대로 사용합니다.",
  on: "기준 비중을 만든 뒤, 뉴스·공시로 만든 투자 의견을 참고해 비중을 조금 조정합니다.",
  caution: "뉴스 반영이 반드시 더 높은 수익률을 의미하지는 않습니다.",
  details: [
    "기술적으로는 블랙-리터만(Black-Litterman) 모형을 씁니다. 기준 비중을 출발점으로 두고, AI가 만든 투자 의견(뷰, view)과 그 신뢰도만큼 비중을 조금씩 옮깁니다.",
    "투자 의견은 각 투자 시점(백테스트 시작일·리밸런싱일·분석 기준일) 직전 기간의 자료만 씁니다. 뉴스는 약 2주, 공시는 약 45일 분량이며, 그 시점 이후에 나온 뉴스는 쓰지 않습니다.",
    "근거가 있는 기업이 너무 적거나 의견을 만들지 못한 시점에는 기준 비중을 그대로 씁니다.",
    "한 기업의 비중이 움직이는 폭에는 한도가 있습니다 (종목당 상한의 1/3 이내).",
    "리포트에서 뉴스 반영 전·후의 결과를 나란히 비교해 볼 수 있습니다.",
  ],
}

export const TEMPLATE_ORDER: Template[] = ["low_per", "quality", "momentum", "low_volatility", "high_dividend"]
export const WEIGHTING_ORDER: Weighting[] = ["equal_weight", "market_cap", "inverse_volatility", "min_variance"]

/** 화면에 보이는 전략 이름: 쉬운 표현 옆에 전문용어를 괄호로 함께 쓴다 ("최근 주가 상승세가 좋은 기업(모멘텀)"). 모르는 값은 그대로. */
export const templateLabel = (t: string) => { const i = TEMPLATE_INFO[t as Template]; return i ? `${i.name}(${i.short})` : t }
export const weightingLabel = (w: string) => { const i = WEIGHTING_INFO[w as Weighting]; return i ? `${i.name}(${i.short})` : w }

/** 저장 요약 한 줄: 쉬운 표현(전문용어) · … · 뉴스 반영 ("저평가 기업 중심(저PER) · 모든 기업에 비슷하게 투자(동일비중) · 뉴스 반영 켜짐"). */
export function strategySummary(sp: StrategyPreference): string {
  const t = TEMPLATE_INFO[sp.template]
  const w = WEIGHTING_INFO[sp.baseline_weighting]
  return `${t ? `${t.focus}(${t.short})` : sp.template} · ${w ? `${w.name}(${w.short})` : sp.baseline_weighting} · 뉴스 반영 ${sp.use_news_tilt ? "켜짐" : "꺼짐"}`
}
