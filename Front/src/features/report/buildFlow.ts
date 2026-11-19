import type { CompaniesBlock, ReportDoc, WeightsCompareBlock } from "../../api/types"
import { strategyInfo } from "./wording"

/** 「3. 포트폴리오 구성 → 비중이 정해진 과정」 카드의 단계별 짧은 설명 (2026-11-16 사용자 요청).
 *  저장된 리포트와 새 리포트 모두 기존 리포트 자료(companies·weights_compare·summary)로 문장을 만든다. 이 카드 전용 문구라 다른 화면은 그대로다. */
export interface FlowStep { t: string; d: string; off?: boolean }

/** 선정 지표마다 순위를 매긴 짧은 기준 (긴 설명 — 모멘텀 계산 기간 등 — 은 「선택 근거 자세히 보기」에 있다, 2026-11-16 사용자 요청). */
const RANK_SHORT: Record<string, string> = {
  return_12m_1m: "주가 상승률",
  dividend_yield_ttm: "배당수익률이 높은",
  pe_ttm: "PER이 낮은",
  roe_ttm: "ROE가 높은",
  vol_60d: "주가 변동성이 낮은",
}

/** 기준 전략 규칙 → 한 문장. 시가총액·동일비중은 이 카드 전용 문장, 그 밖은 strategyInfo 의 짧은 설명을 '…했습니다' 로. */
const BASE_SENTENCE: Record<string, string> = {
  market_cap: "시가총액이 큰 기업에 더 많은 투자금을 배정했습니다.",
  equal_weight: "선정한 종목에 투자금을 같은 비율로 나눴습니다.",
}

const blocksOf = (doc: ReportDoc, type: string, sec?: string) =>
  doc.sections.filter((s) => !sec || s.id === sec).flatMap((s) => s.blocks).filter((b) => b.type === type)

const isForced = (reason: string | null | undefined) => (reason ?? "").startsWith("필수 포함")

/** 「지켜야 하는 조건」 표의 「필수 포함」 행 (예: 'NOW, GOOGL, MU, NVDA'). 2026-11-11 이전 리포트는 종목 설명에 '필수 포함' 머리말이 없어 이 행으로 찾는다. */
function mustInclude(doc: ReportDoc): Set<string> {
  for (const b of doc.sections.flatMap((s) => s.blocks)) {
    if (b.type !== "table") continue
    for (const r of b.rows as Record<string, unknown>[]) {
      if (r && r.k === "필수 포함" && typeof r.v === "string") return new Set(r.v.split(/\s*,\s*/).map((x) => x.trim()).filter((x) => x && x !== "없음" && x !== "-"))
    }
  }
  return new Set()
}

function selectionStep(comp: CompaniesBlock, must: Set<string>): FlowStep {
  // 짧게 (2026-11-16 사용자 요청): 「분석 기준일과 백테스트 시작일에 각각 8종목을 담았습니다. 필수 포함 4종목과 주가 상승률 순으로 고른 4종목입니다.」
  // 필수 포함은 순위와 관계없이 담는다 — 순위로 뽑은 것처럼 읽히지 않게 수를 나눠 쓴다 (서버 theme_reason_ko 의 '필수 포함 종목 · ' 머리말, 예전 리포트는 「지켜야 하는 조건」 표)
  const isF = (x: CompaniesBlock["items"][number]) => isForced(x.theme_reason_ko) || must.has(x.ticker)
  const nNow = comp.items.filter((x) => x.in_selection_now).length
  const nBt = comp.items.filter((x) => x.in_backtest).length
  const fNow = comp.items.filter((x) => x.in_selection_now && isF(x)).length
  const fBt = comp.items.filter((x) => x.in_backtest && isF(x)).length
  const rank = RANK_SHORT[comp.metric] ?? `${comp.metric_ko} 값이 ${comp.direction === "asc" ? "낮은" : "높은"}`
  const how = (n: number, f: number) => (f === 0 ? `${rank} 순 ${n}종목` : f >= n ? "모두 필수 포함" : `필수 포함 ${f}종목, ${rank} 순 ${n - f}종목`)
  if (nNow === nBt && fNow === fBt) {
    const head = `분석 기준일과 백테스트 시작일에 각각 ${nNow}종목을 담았습니다.`
    const tail = fNow === 0 ? ` 모두 ${rank} 순으로 골랐습니다.` : fNow >= nNow ? " 모두 필수 포함 종목입니다." : ` 필수 포함 ${fNow}종목과 ${rank} 순으로 고른 ${nNow - fNow}종목입니다.`
    return { t: "투자 종목 선정", d: head + tail }
  }
  return { t: "투자 종목 선정", d: `분석 기준일에는 ${nNow}종목(${how(nNow, fNow)}), 백테스트 시작일에는 ${nBt}종목(${how(nBt, fBt)})을 담았습니다.` }
}

function baseStep(wc: WeightsCompareBlock): FlowStep | null {
  const base = wc.columns.find((c) => c.id === wc.baseline_id)
  if (!base) return null
  const core = base.id.replace(/^wf_/, "")
  const short = strategyInfo(base.id)?.short
  const d = BASE_SENTENCE[core] ?? (short ? short.replace(/하는 방식입니다\.$/, "했습니다.") : base.rule_ko ? `${base.label_ko}: ${base.rule_ko}` : `${base.label_ko} 방식으로 계산했습니다.`)
  return { t: "기준 투자 비중 계산", d }
}

function newsStep(doc: ReportDoc, wc: WeightsCompareBlock | undefined): FlowStep | null {
  const ne = doc.summary?.news_effect
  const nBl = wc?.columns.filter((c) => c.kind === "black_litterman").length ?? 0
  if (nBl > 0 || (ne && !ne.disabled)) {
    return { t: "뉴스·공시 반영", d: nBl > 1 ? `기준 비중에 뉴스와 공시를 반영해 ${nBl}개의 별도 구성을 만들었습니다.` : "기준 비중에 뉴스와 공시를 반영해 별도 구성을 만들었습니다." }
  }
  if (ne?.disabled) return { t: "뉴스·공시 반영 안 함", d: ne.reason_ko ?? "이 분석에서는 뉴스를 반영하지 않았습니다", off: true }
  return null
}

/** 선택 전략 이름 + '방식'/'구성'. 템플릿(시가총액·동일비중 등)은 '방식', 이름에 괄호가 있거나 뉴스 반영·낙폭 맞춤안은 '구성'. */
function chosenPhrase(id: string, label: string): string {
  const core = id.replace(/^wf_/, "")
  return ["equal_weight", "market_cap", "inverse_volatility", "min_variance"].includes(core) ? `${label} 방식` : `${label} 구성`
}

function finalStep(doc: ReportDoc): FlowStep {
  const v = doc.summary?.verdict
  const id = v?.chosen_portfolio_id ?? doc.header.chosen_portfolio_id ?? ""
  const label = v?.chosen_label_ko ?? doc.header.chosen_label_ko
  const ph = chosenPhrase(id, label)
  const d =
    v?.status === "none_baseline" ? `조건을 충족한 추천 구성이 없어, 기준 구성인 ${ph}의 비중을 실었습니다.`
    : v?.status === "none_cash_blend" ? `조건을 충족한 추천 구성이 없어, 현금을 섞은 ${ph}의 비중을 실었습니다.`
    : v?.status === "insufficient" ? `과거 성과를 비교한 뒤 ${ph}으로 정했지만, 투자 비율이 낮아 구성 불충분으로 표시했습니다.`
    : `과거 성과를 비교한 뒤, ${ph}으로 최종 비중을 정했습니다.`
  return { t: "최종 비중 결정", d }
}

export function buildFlowSteps(doc: ReportDoc): FlowStep[] {
  const comp = blocksOf(doc, "companies")[0] as CompaniesBlock | undefined
  const wc = blocksOf(doc, "weights_compare", "construction")[0] as WeightsCompareBlock | undefined
  return [comp ? selectionStep(comp, mustInclude(doc)) : null, wc ? baseStep(wc) : null, newsStep(doc, wc), finalStep(doc)].filter((x): x is FlowStep => x !== null)
}
