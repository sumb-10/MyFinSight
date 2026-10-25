import type { Format } from "../api/types"

// 표시 규칙 (Front/docs/04 §7): 수익률 2자리 부호, 비중 1자리, 원화 정수, USD 2자리, 차이 %p. 입력은 분수(0.12 = 12%).
// 반올림은 표시 직전에만 (ROUND_HALF_UP = halfExpand).
const nf = (d: number) => new Intl.NumberFormat("ko-KR", { minimumFractionDigits: d, maximumFractionDigits: d, roundingMode: "halfExpand" } as Intl.NumberFormatOptions)

export function fmt(value: unknown, format: Format | undefined): string {
  if (value === null || value === undefined || value === "") return "–"
  if (typeof value !== "number") return String(value)
  if (!Number.isFinite(value)) return "계산 불가"
  switch (format) {
    case "usd": return `${nf(2).format(value)} USD`
    case "krw": return `${nf(0).format(Math.round(value))}원`
    case "pct": return `${value > 0 ? "+" : ""}${nf(2).format(value * 100)}%`
    case "pct1": return `${nf(1).format(value * 100)}%`
    case "pp": return `${value > 0 ? "+" : ""}${nf(2).format(value * 100)}%p`
    case "ratio": return nf(2).format(value)
    case "int": return nf(0).format(value)
    case "index": return nf(1).format(value)
    case "num": return nf(2).format(value)
    default: return String(value)
  }
}

export const krw = (v: number) => fmt(v, "krw")
export const usd = (v: number) => fmt(v, "usd")
export const pct = (v: number) => fmt(v, "pct")
export const weight = (v: number) => fmt(v, "pct1")
export const fx = (rate: number, date?: string) => `1 USD = ${nf(2).format(rate)} KRW${date ? ` (${date})` : ""}`
export const date = (s?: string | null) => (s ? s.slice(0, 10) : "–")
export const datetime = (s?: string | null) => (s ? s.replace("T", " ").slice(0, 16) : "–")

// 범주형 8색 (라운드 4, 색약 대비 검증 통과). 9번째부터는 되돌아간다. 도넛은 상위 8 + "기타" 로 묶어 색이 겹치지 않게 한다.
export const PALETTE = ["#2563eb", "#eb6834", "#1baf7a", "#eda100", "#e87ba4", "#008300", "#6250d6", "#e34948"]
export const OTHER_COLOR = "#94a3b8"
/** 같은 티커·시리즈는 어느 차트에서든 같은 색: 정렬된 id 목록 안의 위치로 정한다. */
export const colorOf = (id: string, ids: string[]) => { const i = ids.indexOf(id); return i < 0 ? OTHER_COLOR : PALETTE[i % PALETTE.length] }

export const KO: Record<string, string> = {
  conservative: "안정 추구", moderate: "중립", aggressive: "적극",
  low_per: "저PER", quality: "퀄리티(ROE)", momentum: "모멘텀", low_volatility: "저변동성", high_dividend: "고배당",
  equal_weight: "동일비중", market_cap: "시가총액비중", inverse_volatility: "역변동성", min_variance: "최소분산",
  SP500: "S&P 500", NASDAQ100: "NASDAQ-100", KOSPI200: "KOSPI 200",
  wealth_growth: "자산 증식", income: "현금흐름(배당)", capital_preservation: "원금 보존", retirement: "은퇴 대비",
  sell: "매도", hold: "보유", buy_more: "추가 매수", "2w": "2주", "1m": "1개월", "1q": "분기", "6m": "반기", "1y": "1년",
  started: "시작", stopped: "중지", resumed: "재개", new: "새 분석", rerun: "재분석", revision: "수정안", pass: "통과", warn: "주의", fail: "미통과", rebalance_skipped: "리밸런싱 건너뜀", refresh_failed: "갱신 실패",
  "20s": "20대", "30s": "30대", "40s": "40대", "50s": "50대", "60s+": "60대 이상",
  none: "없음", beginner: "초보", intermediate: "중급", advanced: "고급", basic: "기초", expert: "전문가",
  queued: "대기", running: "실행 중", cancelling: "취소 요청됨", success: "성공", partial: "완료 (경고 있음)", failed: "실패", cancelled: "취소",
  QUEUED: "대기", STARTED: "처리 중", SUCCESS: "완료", PARTIAL: "완료 (경고)", FAILED: "실패", CANCELLED: "취소",
  missing: "누락", conflict: "충돌", ambiguous: "모호", preference: "선호 확인", feasibility: "실행 전 점검",
  news: "뉴스", disclosure: "공시", financial: "재무·가격 지표", calc: "계산값", data_quality: "자료 품질",
  recommended: "추천", recommended_warn: "추천 (주의 있음)", insufficient: "구성 불충분", none_cash_blend: "추천 없음 · 현금 혼합안", none_baseline: "추천 없음 · 기준 포트폴리오",
  template: "규칙", black_litterman: "뉴스 뷰(BL)", benchmark: "비교지수", alternative: "대안", matched: "낙폭 맞춤", reference: "참고", flag: "허용 초과",
}
export const ko = (k: unknown) => KO[String(k)] ?? String(k)
