import type { PaperDetail, PaperRebalance } from "../../api/types"

// 모의투자 첫 화면의 「리밸런싱 거래」와 알림에 쓰는 계산. 모두 서버가 준 거래 기록·규칙만 쓴다 (새 값을 지어내지 않는다).

/** 마지막 정기 리밸런싱 가운데 실제로 거래한 것 (건너뜀·거래 없음 제외). */
export const lastRebalance = (d: PaperDetail): PaperRebalance | null => [...d.rebalances].reverse().find((r) => r.kind === "rebalance" && !r.skipped && r.trades.length > 0) ?? null

/** 첫 화면에 보여 줄 거래: 마지막 정기 리밸런싱, 아직 없으면 시작할 때의 최초 매수 (적립 매수는 상세 기록에서 본다). */
export const shownTrades = (d: PaperDetail): PaperRebalance | null => lastRebalance(d) ?? d.rebalances.find((r) => r.kind === "initial" && r.trades.length > 0) ?? null

/** 아직 확인하지 않은 리밸런싱: 마지막 리밸런싱 번호가 이 브라우저에서 확인한 번호보다 크면 그 리밸런싱. 확인 기록이 없으면(처음 봄) 알리지 않는다. */
export const freshRebalance = (d: PaperDetail, seenSeq: number | undefined): PaperRebalance | null => {
  const r = lastRebalance(d)
  return r && seenSeq !== undefined && r.seq > seenSeq ? r : null
}

const PERIOD_MONTHS: Record<string, number> = { "1m": 1, "1q": 3, "6m": 6, "1y": 12 }

/** 다음 정기 리밸런싱 시점. 서버 규칙(backend m6_tracking/paper.py rebalance_due_dates)과 같이 시작일이 속한 기간부터 count 기간마다 「기간 첫 거래일」.
 *  휴장일 달력은 서버에만 있어 날짜 대신 「2026년 12월 첫 거래일」처럼 기간으로 말한다. 2주 단위는 거래일 수로만 안내한다. 리밸런싱이 없으면 null. */
export function nextRebalanceText(rule: { count: number; unit: string }, start: string, last: string | null): string | null {
  if (!rule.count) return null
  if (rule.unit === "2w") return `마지막 리밸런싱 뒤 ${10 * rule.count}거래일째`
  const m = PERIOD_MONTHS[rule.unit]
  if (!m || !/^\d{4}-\d{2}/.test(start)) return null
  const period = (d: string) => Math.floor((Number(d.slice(0, 4)) * 12 + Number(d.slice(5, 7)) - 1) / m)
  const s = period(start), l = period(last && /^\d{4}-\d{2}/.test(last) ? last : start)
  const next = (s + (Math.floor((l - s) / rule.count) + 1) * rule.count) * m  // 다음 기간의 첫 달 (0부터 센 달 번호)
  return `${Math.floor(next / 12)}년 ${(next % 12) + 1}월 첫 거래일`
}
