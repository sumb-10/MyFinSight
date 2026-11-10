// 투자성향별 추천 전략 (목업). 실제 서버 backend/analysis/m1_request/strategy_recommendation.py 와 같은 고정 규칙 표다 —
// 조합·이유·차이 문장을 바꾸면 서버 표도 같이 바꾼다 (서버 테스트 test_strategy_recommendation 이 두 표가 같은지 본다). 안내 문장(note_ko)만 목업용.
import type { ProposedStrategyRecommendation } from "../../api/proposed"
import type { Tendency } from "../../api/types"

type Pick3 = ProposedStrategyRecommendation["recommended"]
const s = (template: string, baseline_weighting: string, use_news_tilt: boolean): Pick3 => ({ template, baseline_weighting, use_news_tilt })

const TABLE: Record<Tendency, { rec: Pick3; reasons: string[]; alts: (Pick3 & { diff_ko: string })[] }> = {
  안정형: {
    rec: s("high_dividend", "min_variance", false),
    reasons: ["손실을 가장 피하고 싶은 성향이라, 배당처럼 꾸준한 현금 흐름이 있는 기업(고배당)을 먼저 고릅니다.", "포트폴리오 전체의 오르내림이 가장 작아지도록 투자금을 나눕니다(최소분산).", "뉴스로 비중을 바꾸면 변동이 커질 수 있어 반영하지 않습니다."],
    alts: [{ ...s("low_volatility", "inverse_volatility", false), diff_ko: "배당 대신 주가 변동이 작은 기업을 고릅니다. 배당 수입은 줄 수 있지만 하락장 방어는 비슷합니다." }, { ...s("quality", "equal_weight", false), diff_ko: "수익성 좋은 기업에 똑같이 나눕니다. 상승 여력은 크지만 추천안보다 변동이 커집니다." }],
  },
  안정추구형: {
    rec: s("low_volatility", "inverse_volatility", false),
    reasons: ["손실을 줄이는 것을 먼저 보는 성향이라, 주가 변동이 작은 기업(저변동성)을 고릅니다.", "변동이 작은 기업에 더 많이 담아(역변동성) 전체 흔들림을 줄입니다.", "뉴스 반영은 끄고 기준 비중을 그대로 씁니다."],
    alts: [{ ...s("high_dividend", "min_variance", false), diff_ko: "배당 많은 기업을 최소분산으로 나눕니다. 더 보수적이지만 기대 수익도 낮아집니다." }, { ...s("quality", "equal_weight", true), diff_ko: "수익성 좋은 기업에 똑같이 나누고 뉴스도 반영합니다. 수익 기대는 크지만 낙폭이 커질 수 있습니다." }],
  },
  위험중립형: {
    rec: s("quality", "equal_weight", true),
    reasons: ["수익과 위험을 함께 보는 성향이라, 돈을 잘 버는 기업(퀄리티)을 고릅니다.", "한 기업에 쏠리지 않도록 똑같이 나눕니다(동일비중).", "뉴스·공시 근거가 있으면 비중을 조금 조정합니다."],
    alts: [{ ...s("low_volatility", "inverse_volatility", false), diff_ko: "변동이 작은 기업 위주라 덜 흔들리지만, 상승장에서 덜 오를 수 있습니다." }, { ...s("momentum", "market_cap", true), diff_ko: "최근 많이 오른 큰 기업 위주라 수익 기대는 크지만 낙폭도 커질 수 있습니다." }],
  },
  적극투자형: {
    rec: s("momentum", "market_cap", true),
    reasons: ["수익을 더 중시하는 성향이라, 최근 주가 상승세가 좋은 기업(모멘텀)을 고릅니다.", "규모가 큰 기업에 더 많이 담아(시가총액비중) 지수와 비슷하게 움직이게 합니다.", "뉴스·공시 근거로 비중을 조정합니다."],
    alts: [{ ...s("quality", "equal_weight", true), diff_ko: "수익성 좋은 기업에 똑같이 나눕니다. 추천안보다 덜 흔들리지만 상승 흐름을 덜 따라갑니다." }, { ...s("momentum", "equal_weight", true), diff_ko: "같은 기업을 똑같이 나눕니다. 작은 기업 비중이 커져 변동이 더 커질 수 있습니다." }],
  },
  공격투자형: {
    rec: s("momentum", "equal_weight", true),
    reasons: ["높은 수익을 위해 큰 변동도 감수하는 성향이라, 최근 주가 상승세가 좋은 기업(모멘텀)을 고릅니다.", "큰 기업에만 쏠리지 않게 똑같이 나눕니다(동일비중).", "뉴스·공시 근거로 비중을 조정합니다."],
    alts: [{ ...s("momentum", "market_cap", true), diff_ko: "같은 기업을 규모에 비례해 나눕니다. 큰 기업 비중이 커져 변동이 조금 줄어듭니다." }, { ...s("quality", "equal_weight", true), diff_ko: "수익성 좋은 기업으로 바꿉니다. 상승 흐름은 덜 따라가지만 낙폭이 줄 수 있습니다." }],
  },
}

/** 투자 목적에 따른 조정 (성향 표 다음에 적용): 목적이 정하는 항목만 바꾸고 나머지는 성향 표를 따른다. reasons 는 바꾼 항목의 이유 문장
 *  (성향 표의 이유는 [기업 고르는 기준, 비중 나누는 방식, 뉴스 반영] 순서라 같은 자리를 바꾼다). only = 이 성향에서만 바꾼다. 자산 증식은 성향 표 그대로.
 *  서버 strategy_recommendation.py _PURPOSE 와 같다 (서버 테스트가 확인). */
export const PURPOSE_RULES: Record<string, { set: Partial<Pick3>; only?: Tendency[]; reasons: { template?: string; weighting?: string; news?: string } }> = {
  income: { set: { template: "high_dividend" }, reasons: { template: "투자 목적이 현금흐름(배당)이라, 배당을 많이 주는 기업(고배당)을 고릅니다." } },
  capital_preservation: { set: { template: "low_volatility", baseline_weighting: "min_variance", use_news_tilt: false }, reasons: { template: "투자 목적이 원금 보존이라, 주가 변동이 작은 기업(저변동성)을 고릅니다.", weighting: "포트폴리오 전체의 오르내림이 가장 작아지도록 투자금을 나눕니다(최소분산).", news: "뉴스로 비중을 바꾸면 변동이 커질 수 있어 반영하지 않습니다." } },
  retirement: { set: { template: "quality" }, only: ["위험중립형", "적극투자형", "공격투자형"], reasons: { template: "투자 목적이 은퇴 대비라, 오래 들고 갈 수 있게 꾸준히 돈을 잘 버는 기업(퀄리티)을 고릅니다." } },
}
const PURPOSE_ALT_DIFF = "투자 목적을 빼고 투자성향만 보고 고른 조합입니다."
const same = (a: Pick3, b: Pick3) => a.template === b.template && a.baseline_weighting === b.baseline_weighting && a.use_news_tilt === b.use_news_tilt

export function recommendation(tendency: Tendency, purpose?: string | null): ProposedStrategyRecommendation {
  const t = TABLE[tendency]
  let rec = t.rec, reasons = [...t.reasons], alts = t.alts
  const rule = purpose ? PURPOSE_RULES[purpose] : undefined
  if (rule && (!rule.only || rule.only.includes(tendency))) {
    const next = { ...rec, ...rule.set }
    if (!same(next, rec)) {
      ;(["template", "weighting", "news"] as const).forEach((k, i) => { if (rule.reasons[k]) reasons[i] = rule.reasons[k]! })
      alts = [{ ...rec, diff_ko: PURPOSE_ALT_DIFF }, ...alts.filter((a) => !same(a, next))].slice(0, 2)
      rec = next
    }
  }
  return { tendency, recommended: rec, reasons_ko: reasons, alternatives: alts, note_ko: "목업 추천입니다. 실제 서버와 같은 고정 규칙(투자성향마다 정해 둔 표)입니다." }
}
