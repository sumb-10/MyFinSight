import type { ReportDoc, ReportSummary, RiskTolerance } from "../../api/types"
import { proposedOf } from "../../api/proposed"
import { DEFAULT_VOL_PREF, isRiskTolerance, isVolPref, LEGACY_PREF_KO, RISK_TOLERANCE_RANGE, type VolPref } from "../../lib/tendency"

// 화면에 보이는 이름·짧은 설명만 정한다. 서버 값·ID·전략명은 그대로 두고, 서버가 쓰는 문장 틀(백엔드 report_blocks·validate)에 맞는 것만 풀어 쓴다.
// 틀에 맞지 않는 문장은 손대지 않고 원문 그대로 보여 준다.

type Period = { start: string; end: string; trading_days?: number; window_days?: number; annualized_reliable?: boolean }
export const periodOf = (doc: ReportDoc): Period => (doc.summary?.period ?? doc.header.backtest_period) as Period

/** 백테스트 창이 짧아 연환산 값(CAGR·Sharpe·XIRR)을 참고로만 보는가 (서버 period.annualized_reliable). 값이 없으면 false. */
export const isShortWindow = (doc: ReportDoc) => periodOf(doc).annualized_reliable === false

/** 연환산 값을 판정에 쓰는 최소 거래일 수 (서버 parameters.backtest.min_annualize_days, 없으면 null). */
export function minAnnualize(doc?: ReportDoc): { days: number; years: number } | null {
  const bt = doc?.parameters?.backtest as { min_annualize_days?: number; trading_days?: number } | undefined
  if (!bt?.min_annualize_days) return null
  return { days: bt.min_annualize_days, years: Math.round((bt.min_annualize_days / (bt.trading_days || 252)) * 10) / 10 }
}

/** 짧은 창 안내 한 문장. 서버 문구의 '1년 미만'은 실제 기준(min_annualize_days, 기본 378거래일 ≈ 1.5년)과 달라 기준을 함께 적는다. */
export function shortWindowNote(doc: ReportDoc) {
  const m = minAnnualize(doc)
  return `평가 기간이 짧아 연 환산 값은 참고용입니다${m ? ` (이 분석은 ${m.days}거래일, 약 ${m.years}년 이상일 때만 연 환산 값으로 판정합니다)` : ""}.`
}

/** KPI 이름: 지표 이름과 기간 정보를 나누고, CAGR 은 「연평균 수익률(CAGR)」로 함께 쓴다. 기간 수익률을 CAGR 로 부르지 않는다. */
export function kpiName(k: { id: string; label_ko: string }): { name: string; sub?: string } {
  let m = /^기간 수익률 \((\d+)거래일\)$/.exec(k.label_ko)
  if (m) return { name: "전체 기간 수익률", sub: `${m[1]}거래일 기준` }
  if (k.id === "cagr" && /^연평균 수익률 ?\(CAGR\)$/.test(k.label_ko)) return { name: "연평균 수익률(CAGR)" }
  m = /^비교지수\((.+?)\) 대비 \(기간\)$/.exec(k.label_ko)
  if (m) return { name: `${m[1]} 대비 전체 기간 수익률 차이` }
  m = /^비교지수\((.+?)\) 대비$/.exec(k.label_ko)
  if (m && k.id === "excess") return { name: `${m[1]} 대비 연평균 수익률(CAGR) 차이` }
  if (k.label_ko === "최대낙폭 (MDD)") return { name: "최대낙폭(MDD)" }
  return { name: k.label_ko }
}

/** KPI 설명 문장: 서버의 짧은 창 문구("연 환산 +77.4% 는 1년 미만 창이라 참고만")만 바꾸고 나머지는 그대로. */
export function kpiNote(note: string | null | undefined, doc?: ReportDoc): string | null {
  if (!note) return null
  const m = /^연 환산 ([+\-−]?[\d.,]+%) 는 1년 미만 창이라 참고만$/.exec(note)
  if (!m) return note
  const a = minAnnualize(doc)
  return `연 환산 수익률 ${m[1]} — 평가 기간이 짧아 참고용${a ? ` (${a.days}거래일·약 ${a.years}년 이상일 때만 판정에 사용)` : ""}`
}

/** 서버의 짧은 창 KPI 문구("연 환산 +77.4% 는 1년 미만 창이라 참고만")에서 연 환산 값만 꺼낸다. 틀이 다르면 null. */
export const annualizedFromNote = (note?: string | null) => (note ? /^연 환산 ([+\-−]?[\d.,]+%) 는 /.exec(note)?.[1] ?? null : null)

/** 서버 비교지수 대비 차이(excess, %p) → 문장. 주어(subject)로 어떤 수익률의 차이인지 밝힌다 (예: "전체 기간 수익률이").
 *  값이 없으면 null, 표시 단위(0.01%p)에서 0 이면 「차이가 없었습니다」. 차이는 다시 계산하지 않는다. */
export function excessSentence(value: number | null | undefined, bench: string, subject?: string | null): string | null {
  if (value === null || value === undefined || !Number.isFinite(value)) return null
  const head = subject ? `${subject} ` : ""
  if (Math.round(value * 10000) === 0) return `${head}${bench}와 차이가 없었습니다 (0.00%p)`
  const abs = `${(Math.abs(value) * 100).toFixed(2)}%p`
  return `${head}${bench}보다 ${abs} ${value > 0 ? "높았습니다" : "낮았습니다"}`
}

/** 서버 R1 문장 「최대낙폭 29.9% vs 허용 30.0% (같은 기간 SPY 매수보유 (동일 적립) 8.9%) — 허용보다 …p 큼」을 괄호 겹침 없이 둘로 나눈다.
 *  main: 「최대낙폭 29.9% vs 허용 30.0% — 허용보다 …」, bench: 「같은 기간 SPY 매수 후 보유·동일 적립 시 8.9%」. 틀이 다르면 null (원문 그대로). */
export function r1Text(msg: string): { main: string; bench: string } | null {
  const m = /^(최대낙폭 [\d.]+% vs 허용 [\d.]+%) \(같은 기간 (.+) ([\d.]+%)\)(?: — (.+))?$/.exec(msg)
  if (!m) return null
  const t = benchTicker(m[2])
  return { main: m[4] ? `${m[1]} — ${m[4]}` : m[1], bench: `같은 기간 ${t ? `${t} 매수 후 보유·동일 적립` : m[2]} 시 ${m[3]}` }
}

/** 서버 문장 안의 단독 「CAGR」을 「연평균 수익률(CAGR)」로. 이미 함께 쓴 곳은 그대로. */
export const pairCagr = (t: string) => t.replace(/(?<![(A-Za-z가-힣])CAGR(?![)A-Za-z])/g, "연평균 수익률(CAGR)")

/** 비교지수 이름 (SPY 등). 서버 KPI 이름 「비교지수(SPY) 대비」에서 읽는다. */
export function benchName(sm?: ReportSummary | null): string {
  for (const k of sm?.kpis ?? []) { const m = /^비교지수\((.+?)\) 대비/.exec(k.label_ko); if (m) return m[1] }
  for (const r of sm?.validation.rules_ko ?? []) { const m = /^(\S+) 대비 초과 CAGR/.exec(r.message_ko); if (m) return m[1] }
  return "비교지수"
}

const ETF: Record<string, string> = { SPY: "미국 S&P 500 지수를 따라가는 ETF", QQQ: "미국 나스닥 100 지수를 따라가는 ETF", "069500.KS": "코스피 200 지수를 따라가는 ETF (KODEX 200)" }
export const etfDesc = (ticker: string) => ETF[ticker] ?? null
/** 「SPY 매수보유 (동일 적립)」 → "SPY". 틀에 맞지 않으면 null. */
export const benchTicker = (label?: string | null) => (label ? /^(.+?) 매수보유 \(동일 적립\)$/.exec(label)?.[1] ?? null : null)

/* ───────── 전략 설명 (전략 ID 기준, 이름은 바꾸지 않는다) ───────── */

const TEMPLATE: Record<string, [string, string]> = {
  equal_weight: ["선정한 종목에 같은 비율로 나눠 투자하는 방식입니다.", "종목이 N개면 종목마다 1/N씩 투자합니다. 종목·섹터 상한이 있으면 그 안에서 조정합니다."],
  market_cap: ["기업 규모(시가총액)가 클수록 더 많이 투자하는 방식입니다.", "시가총액에 비례해 비중을 정합니다. 주가지수와 같은 방식이며, 종목 상한을 넘는 비중은 다른 종목으로 나눌 수 있습니다."],
  inverse_volatility: ["주가가 덜 흔들린 종목에 더 많이 투자하는 방식입니다.", "과거 변동성이 낮은 종목일수록 비중을 크게 둡니다 (변동성의 역수에 비례)."],
  min_variance: ["포트폴리오 전체의 흔들림이 가장 작아지도록 비중을 정하는 방식입니다.", "과거 자료로 추정한 분산(흔들림)이 가장 작아지는 비중을 종목·섹터 상한 안에서 최적화로 찾습니다."],
}
const DD_MATCH: [string, string] = ["주식과 현금 비중을 조절해 과거 손실 위험을 관리하려는 전략입니다.", "기준 구성의 주식 비중을 줄이고 나머지를 현금으로 두어, 과거 최대 하락폭을 사용자의 손실 감내 수준(목표)에 맞추려는 투자 방식입니다. 미래 손실이 해당 수준 이하로 제한된다는 의미는 아닙니다."]

export interface StrategyInfo { short: string; help: string }
/** 전략 ID → 짧은 설명 + 도움말. 모르는 ID 는 null (설명을 지어내지 않는다). */
export function strategyInfo(id?: string | null): StrategyInfo | null {
  if (!id) return null
  let m = /^benchmark_(.+)$/.exec(id)
  if (m) { const e = etfDesc(m[1]); return { short: `비교를 위해 같은 날, 같은 금액을 ${m[1]}에 넣고 팔지 않고 보유했다고 가정한 결과입니다.`, help: `${e ? `${m[1]}는 ${e}입니다. ` : ""}내 전략과 같은 기간·같은 적립 조건으로 계산한 비교 기준이며, 투자 후보는 아닙니다.` } }
  if (id.startsWith("dd_match_")) return { short: DD_MATCH[0], help: DD_MATCH[1] }
  if (id === "wf_bl_news") return { short: "리밸런싱할 때마다 그때까지의 뉴스·공시로 투자 의견을 새로 만들어 비중을 조정하는 방식입니다.", help: "기준 비중에 Black-Litterman 방식으로 투자 의견(뷰)을 제한적으로 반영합니다. 근거가 부족한 시점에는 기준 비중을 그대로 씁니다. 종목은 바꾸지 않습니다." }
  m = /^wf_(.+)$/.exec(id)
  if (m && TEMPLATE[m[1]]) return { short: TEMPLATE[m[1]][0], help: `${TEMPLATE[m[1]][1]} 이 구성은 리밸런싱할 때마다 그 시점까지의 자료로 비중을 다시 계산합니다 (walk-forward, 종목은 고정).` }
  if (/^bl_\d+$/.test(id)) return { short: "뉴스·공시로 만든 투자 의견(뷰)을 기준 비중에 제한적으로 반영한 방식입니다.", help: "백테스트 시작일까지의 뉴스·공시로 만든 투자 의견을 Black-Litterman 방식으로 기준 비중에 반영했습니다. 종목별로 비중을 움직일 수 있는 폭에는 한도가 있습니다." }
  if (TEMPLATE[id]) return { short: TEMPLATE[id][0], help: `${TEMPLATE[id][1]} 백테스트 시작일에 정한 비중을 목표로 리밸런싱합니다.` }
  return null
}

/** 화면 이름 → 전략 ID (서버 datasets 계열 이름). 비교표 행에는 ID 가 없어 이름으로 찾는다. */
export function idByLabel(doc: ReportDoc): Map<string, string> {
  return new Map(Object.entries(doc.datasets.series).map(([id, s]) => [s.label_ko, id]))
}

/** 「낙폭 맞춤안 (주식 79% + 현금 21%, 시가총액비중 기준)」 → ["낙폭 맞춤안", "주식 79%", "현금 21%", "시가총액비중 기준"]. 괄호가 없으면 그대로 한 조각. */
export function nameParts(name: string): string[] {
  const m = /^(.+?) \((.+)\)$/.exec(name)
  return m ? [m[1], ...m[2].split(/, | \+ /)] : [name]
}

/** 리밸런싱 타임라인 제목: 중첩 괄호 없이 한 줄로. 틀이 다르면 null (원래 제목을 쓴다). */
export function timelineTitle(t: string): string[] | null {
  const m = /^리밸런싱 타임라인 \((.+)\)$/.exec(t)
  return m ? nameParts(m[1]) : null
}

/* ───────── 핵심 판단 이유 (서버 validate.py 의 reason 조각 틀) ───────── */

export interface Reason { title: string | null; desc: string; tone?: "good" | "warn"; annual?: boolean }  // annual: 연 환산 값이 들어 있어 짧은 창에서는 참고용
/** 판단 이유 한 조각 → 제목 + 한두 문장. 숫자는 원문에서만 가져온다. 틀에 맞지 않으면 제목 없이 원문 그대로.
 *  짧은 창이면 연 환산 값이 든 문장 끝에 「(연 환산, 참고용)」만 붙이고, 긴 안내는 목록 아래에 한 번만 둔다. */
export function explainReason(text: string, o: { short: boolean }): Reason {
  const ref = o.short ? " (연 환산, 참고용)" : ""
  const t = text.trim().replace(/\.$/, "")
  let m: RegExpExecArray | null
  if ((m = /^후보 (\d+)개 중 1위$/.exec(t))) return { title: "비교한 투자 구성안 중 1위", desc: `${m[1]}개 투자 구성안을 정해진 순서대로 비교했을 때 가장 앞선 구성안입니다.` }
  if ((m = /^목표수익\(연 ([\d.]+%)\) 충족$/.exec(t))) return { title: "목표 수익률 충족", tone: "good", desc: `과거 연평균 수익률(CAGR)이 목표로 정한 연 ${m[1]}에 도달했습니다.` }
  if ((m = /^목표수익\(연 ([\d.]+%)\) 미달$/.exec(t))) return { title: "목표 수익률 미달", tone: "warn", desc: `과거 연평균 수익률(CAGR)이 목표로 정한 연 ${m[1]}에 미치지 못했습니다.` }
  if (t === "목표수익은 창이 짧아 참고만") return { title: "목표 수익률은 참고만", desc: "과거 성과 계산 기간이 짧아 목표 수익률 달성 여부는 참고로만 봤습니다.", annual: true }
  if ((m = /^(\S+) 대비 초과 CAGR ([+\-−]?)([\d.]+%p)$/.exec(t))) {
    const up = m[2] !== "-" && m[2] !== "−"
    return { title: `${m[1]}보다 ${up ? "높은" : "낮은"} 연평균 수익률`, tone: up ? "good" : "warn", desc: `같은 기간 ${m[1]}의 연평균 수익률(CAGR)보다 ${m[2]}${m[3]} ${up ? "높았습니다" : "낮았습니다"}${ref}.`, annual: true }
  }
  if ((m = /^최대낙폭 ([\d.]+%) vs 허용 ([\d.]+%) \(여유 ([\d.]+%p)\)$/.exec(t))) return { title: "허용 손실 범위 안", tone: "good", desc: `과거 최대 하락폭(최대낙폭)은 ${m[1]}로, 내가 정한 허용 손실 ${m[2]}보다 ${m[3]} 작았습니다.` }
  if ((m = /^최대낙폭 ([\d.]+%) vs 허용 ([\d.]+%) \(([\d.]+%p) 초과\)$/.exec(t))) return { title: "허용 손실 범위 초과", tone: "warn", desc: `과거 최대 하락폭(최대낙폭)은 ${m[1]}로, 내가 정한 허용 손실 ${m[2]}보다 ${m[3]} 컸습니다.` }
  if ((m = /^Sharpe (-?[\d.]+)로 가장 높음$/.exec(t))) return { title: "위험 대비 수익성 1위", tone: "good", desc: `위험 대비 수익성을 나타내는 Sharpe 비율이 ${m[1]}로, 비교한 구성안 중 가장 높았습니다.` }
  if ((m = /^Sharpe (-?[\d.]+) \(음수, 가장 덜 나쁨\)$/.exec(t))) return { title: "위험 대비 수익성", tone: "warn", desc: `Sharpe 비율이 ${m[1]}로 음수였지만, 비교한 구성안 중에서는 가장 덜 나빴습니다.` }
  if ((m = /^Sharpe (-?[\d.]+)$/.exec(t))) return { title: "위험 대비 수익성", desc: `Sharpe 비율은 ${m[1]}입니다. 이 값이 가장 높은 구성안은 아니었지만, 앞선 기준(목표 수익률·비교지수·허용 손실)에서 앞서 선택됐습니다.` }
  if ((m = /^(.+)의 주식 비중을 (\d+%)로 줄여 과거 최대낙폭을 목표 ([\d.]+%) 안에 맞춘 구성$/.exec(t))) return { title: "주식·현금 비중 조절", desc: `${m[1]} 구성에서 주식 비중을 ${m[2]}로 줄이고 나머지를 현금으로 두어, 과거 최대 하락폭을 목표 ${m[3]} 안에 맞췄습니다.` }
  if (t === "손실 시 매도·투자 경험 없음 성향이라 같은 조건이면 낙폭 맞춤안을 우선했습니다") return { title: "투자 성향 반영", desc: `${t}.` }
  if ((m = /^CAGR ([+\-−]?[\d.]+%), 최종 평가금액 (.+)$/.exec(t))) return { title: "과거 성과 요약", desc: `연평균 수익률(CAGR) ${m[1]}${ref}, 백테스트 기간 끝의 평가금액 ${m[2]}입니다.`, annual: true }
  return { title: null, desc: text }
}

/** 추천 기준 한 문장 (서버 rank_key 순서: 목표수익 → 비교지수 → 허용 낙폭 초과 구간 → Sharpe). 결과 상태에 따라 문장을 나눈다. */
export function pickSentence(n: number | null, bench: string, verdict?: ReportSummary["verdict"] | null): string {
  const base = `${n ? `${n}개 투자 구성안을` : "투자 구성안을"} 목표 수익률 달성 여부, ${bench}보다 나았는지, 허용 손실을 넘은 정도, 위험 대비 수익성(Sharpe)을 차례로 고려해 비교`
  if (!verdict) return `${base}한 결과입니다.`
  if (verdict.status === "recommended") return `${base}하고 1개를 추천했습니다.`
  if (verdict.status === "recommended_warn") return `${base}하고 1개를 골랐지만, 주의할 점이 있습니다.`
  return `${base}했지만, 결과는 「${verdict.label_ko}」로 추천한 구성안이 없습니다.`
}

/* ───────── 분석 당시 투자성향과 변동성 기준 (현재 프로필이 아니라 이 리포트에 저장된 값) ───────── */

const kvRow = (doc: ReportDoc, title: string, key: string) => {
  for (const s of doc.sections) for (const b of s.blocks) if (b.type === "table" && b.title_ko === title) { const v = b.rows.find((r) => r.k === key)?.v; if (typeof v === "string") return v }
  return null
}

export interface AnalysisRisk { code: RiskTolerance | null; tendency: string | null; pref: VolPref | null; prefDiffers: boolean; computed?: string | null; reasonKo?: string | null; exact?: boolean }
/** 서버 「요청 내용」 표의 투자성향(세 단계 코드)과 「성향 해석」 표의 변동성 선호(low/medium/high). 리포트에는 다섯 가지 중 어느 성향인지 저장돼 있지 않아
 *  성향은 확인 가능한 범위(예: 「안정형·안정추구형」)로만 쓴다. prefDiffers: 적용한 변동성 기준이 성향의 기본 기준과 다르다 (요청 문장의 변동성 언급이 우선). */
export function analysisRisk(doc: ReportDoc): AnalysisRisk {
  // 제안 계약(분석 당시 저장된 5단계 성향, 지금은 목업만)이 있으면 그것을 쓴다 — 현재 프로필이 아니라 그 분석의 값이다.
  const rp = proposedOf(doc)?.risk_profile
  if (rp) return { code: rp.risk_tolerance, tendency: rp.tendency_final, computed: rp.tendency_computed !== rp.tendency_final ? rp.tendency_computed : null, pref: rp.applied_vol_pref, prefDiffers: rp.applied_vol_pref !== rp.default_vol_pref, reasonKo: rp.pref_reason_ko, exact: true }
  const head = kvRow(doc, "요청 내용", "투자성향")?.split(" · ")[0]?.trim()
  const code = isRiskTolerance(head) ? head : null
  const p = kvRow(doc, "성향 해석 (소프트 조건)", "변동성 선호")?.trim()
  const pref = isVolPref(p) ? p : null
  return { code, tendency: code ? RISK_TOLERANCE_RANGE[code] : null, pref, prefDiffers: !!code && !!pref && DEFAULT_VOL_PREF[code] !== pref }
}

/** 변동성 적합(R7) 검사. 서버가 이 검사를 문장으로만 주므로(validate.py R7 세 가지 틀) 그 틀에서 숫자를 읽는다. 틀이 다르면 null — 원문을 그대로 쓴다.
 *  bench: 비교지수 연변동성 × 배수 / absolute: 비교지수 자료가 없어 고정 상한 / nocap: 상한 없는 기준. */
export interface VolCheck { kind: "bench" | "absolute" | "nocap"; vol: string; bench: string | null; mult: string | null; band: string | null; pref: VolPref | null; short: boolean }
export function parseVolCheck(msg: string): VolCheck | null {
  let m = /^연변동성 ([\d.]+%) vs 비교지수 ([\d.]+%)의 ([\d.]+)배\((.+?)\) = ([\d.]+%)( \(창이 짧아 참고만\))?$/.exec(msg)
  if (m) return { kind: "bench", vol: m[1], bench: m[2], mult: m[3], band: m[5], pref: LEGACY_PREF_KO[m[4]] ?? null, short: !!m[6] }
  m = /^연변동성 ([\d.]+%) vs (.+?) 상한 ([\d.]+%)$/.exec(msg)
  if (m) return { kind: "absolute", vol: m[1], bench: null, mult: null, band: m[3], pref: LEGACY_PREF_KO[m[2]] ?? null, short: false }
  m = /^연변동성 ([\d.]+%)(?: \(비교지수 ([\d.]+%)\))? — (.+?)은 변동성 상한을 두지 않습니다$/.exec(msg)
  if (m) return { kind: "nocap", vol: m[1], bench: m[2] ?? null, mult: null, band: null, pref: LEGACY_PREF_KO[m[3]] ?? null, short: false }
  return null
}

/** 짧은 창(서버 판정 없음)에서만 쓰는 관측: 표시값이 다를 때만 높다/낮다고 말한다 (0.1% 단위로 표시된 두 값이 다르면 실제 크기 순서도 같다). 같으면 null. */
export function volObserved(c: VolCheck): "above" | "within" | null {
  if (!c.band) return null
  const a = parseFloat(c.vol), b = parseFloat(c.band)
  return a > b ? "above" : a < b ? "within" : null
}
