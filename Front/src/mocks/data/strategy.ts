// 투자성향별 추천 전략 (목업). 실제 추천 규칙은 아직 정해지지 않아 성향마다 미리 정한 예시 결과를 쓴다 — 일반 모드에는 쓰지 않는다.
import type { ProposedStrategyRecommendation } from "../../api/proposed"
import type { Tendency } from "../../api/types"

type Pick3 = ProposedStrategyRecommendation["recommended"]
const s = (template: string, baseline_weighting: string, use_news_tilt: boolean): Pick3 => ({ template, baseline_weighting, use_news_tilt })

const TABLE: Record<Tendency, { rec: Pick3; reasons: string[]; alts: (Pick3 & { diff_ko: string })[] }> = {
  안정형: {
    rec: s("high_dividend", "min_variance", false),
    reasons: ["손실을 가장 피하고 싶은 성향이라, 배당처럼 꾸준한 현금 흐름이 있는 기업을 먼저 고릅니다.", "포트폴리오 전체의 오르내림이 가장 작아지도록 투자금을 나눕니다(최소분산).", "뉴스로 비중을 바꾸면 변동이 커질 수 있어 반영하지 않습니다."],
    alts: [{ ...s("low_volatility", "inverse_volatility", false), diff_ko: "배당 대신 주가 변동이 작은 기업을 고릅니다. 배당 수입은 줄 수 있지만 하락장 방어는 비슷합니다." }, { ...s("quality", "equal_weight", false), diff_ko: "수익성 좋은 기업에 똑같이 나눕니다. 상승 여력은 크지만 추천안보다 변동이 커집니다." }],
  },
  안정추구형: {
    rec: s("low_volatility", "inverse_volatility", false),
    reasons: ["손실을 줄이는 것을 먼저 보는 성향이라, 최근 주가 변동이 작은 기업을 고릅니다.", "변동이 작은 기업에 더 많이 담아(역변동성) 전체 흔들림을 줄입니다.", "뉴스 반영은 끄고 기준 비중을 그대로 씁니다."],
    alts: [{ ...s("high_dividend", "min_variance", false), diff_ko: "배당 많은 기업을 최소분산으로 나눕니다. 더 보수적이지만 기대 수익도 낮아집니다." }, { ...s("quality", "equal_weight", true), diff_ko: "수익성 좋은 기업에 똑같이 나누고 뉴스도 반영합니다. 수익 기대는 크지만 낙폭이 커질 수 있습니다." }],
  },
  위험중립형: {
    rec: s("quality", "equal_weight", true),
    reasons: ["수익과 위험을 함께 보는 성향이라, 돈을 잘 버는(수익성 좋은) 기업을 고릅니다.", "한 기업에 쏠리지 않도록 똑같이 나눕니다(동일비중).", "뉴스·공시 근거가 있으면 비중을 조금 조정합니다."],
    alts: [{ ...s("low_volatility", "inverse_volatility", false), diff_ko: "변동이 작은 기업 위주라 덜 흔들리지만, 상승장에서 덜 오를 수 있습니다." }, { ...s("momentum", "market_cap", true), diff_ko: "최근 많이 오른 큰 기업 위주라 수익 기대는 크지만 낙폭도 커질 수 있습니다." }],
  },
  적극투자형: {
    rec: s("momentum", "market_cap", true),
    reasons: ["수익을 더 중시하는 성향이라, 최근 상승 흐름이 좋은 기업을 고릅니다.", "규모가 큰 기업에 더 많이 담아(시가총액비중) 지수와 비슷하게 움직이게 합니다.", "뉴스·공시 근거로 비중을 조정합니다."],
    alts: [{ ...s("quality", "equal_weight", true), diff_ko: "수익성 좋은 기업에 똑같이 나눕니다. 추천안보다 덜 흔들리지만 상승 흐름을 덜 따라갑니다." }, { ...s("momentum", "equal_weight", true), diff_ko: "같은 기업을 똑같이 나눕니다. 작은 기업 비중이 커져 변동이 더 커질 수 있습니다." }],
  },
  공격투자형: {
    rec: s("momentum", "equal_weight", true),
    reasons: ["높은 수익을 위해 큰 변동도 감수하는 성향이라, 최근 상승 흐름이 좋은 기업을 고릅니다.", "큰 기업에만 쏠리지 않게 똑같이 나눕니다(동일비중).", "뉴스·공시 근거로 비중을 조정합니다."],
    alts: [{ ...s("momentum", "market_cap", true), diff_ko: "같은 기업을 규모에 비례해 나눕니다. 큰 기업 비중이 커져 변동이 조금 줄어듭니다." }, { ...s("quality", "equal_weight", true), diff_ko: "수익성 좋은 기업으로 바꿉니다. 상승 흐름은 덜 따라가지만 낙폭이 줄 수 있습니다." }],
  },
}

export function recommendation(tendency: Tendency): ProposedStrategyRecommendation {
  const t = TABLE[tendency]
  return { tendency, recommended: t.rec, reasons_ko: t.reasons, alternatives: t.alts, note_ko: "목업 추천입니다. 성향마다 미리 정한 예시이며, 실제 서비스의 추천 규칙이 아닙니다." }
}
