import type { Capital, Rebalance } from "../../api/types"

// 내 투자조건 화면의 값 표시. 저장 값(분수 비율·원 단위 금액·enum)은 그대로 두고 읽기 쉬운 글로만 바꾼다.

const int = new Intl.NumberFormat("ko-KR", { maximumFractionDigits: 0 })
const upTo2 = new Intl.NumberFormat("ko-KR", { maximumFractionDigits: 2 })

/** 억·만 단위로 나눠 쓴다. 나머지를 버리지 않으므로 반올림돼 달라 보이지 않는다: 123,456,789 → "1억 2,345만 6,789". */
export function koUnits(v: number): string {
  if (!Number.isFinite(v)) return "–"
  if (!Number.isInteger(v)) return upTo2.format(v)  // 정수가 아니면 나누지 않고 그대로
  const n = Math.abs(v)
  const eok = Math.floor(n / 1e8), man = Math.floor((n % 1e8) / 1e4), rest = n % 1e4
  const parts = [eok ? `${int.format(eok)}억` : "", man ? `${int.format(man)}만` : "", rest ? int.format(rest) : ""].filter(Boolean)
  return (v < 0 ? "-" : "") + (parts.join(" ") || "0")
}

/** 원화: "50만원", "1,000만원", "1억 5,000만원" · 달러: "10,000 USD" (원화와 섞이지 않게 통화 이름을 붙인다). */
export const money = (v: number, cur: "KRW" | "USD") => (cur === "KRW" ? `${koUnits(v)}원` : `${upTo2.format(v)} USD`)

/** 비율: 0.25 → "25%", 0.125 → "12.5%" (불필요한 소수점만 뺀다, 최대 소수 둘째 자리). */
export const pctText = (v: number) => (Number.isFinite(v) ? `${upTo2.format(v * 100)}%` : "–")

export const yearsText = (n: number) => `${Number.isFinite(n) ? upTo2.format(n) : "–"}년`

/** "매월 50만원 · 25일" / "없음" */
export const monthlyText = (c: Capital) => (c.monthly_contribution ? `매월 ${money(c.monthly_contribution, c.currency)} · ${c.contribution_day}일` : "없음")

const UNIT_MONTHS: Record<string, number> = { "1m": 1, "1q": 3, "6m": 6, "1y": 12 }

/** 리밸런싱 주기. 백엔드 규칙(backend/analysis/m1_request/derive.py rebalance_rule)과 같은 계산: 간격 × 단위. */
export function rebalanceText(rb: Rebalance): string {
  if (!rb.count) return "없음 (처음 산 뒤 그대로 보유)"
  if (rb.unit === "2w") return `${2 * rb.count}주마다 1회`
  const months = (UNIT_MONTHS[rb.unit] ?? 0) * rb.count
  if (!months) return `${rb.count}×${rb.unit}`
  return `${({ 1: "매월", 3: "분기마다", 6: "반기마다", 12: "매년" } as Record<number, string>)[months] ?? `${months}개월마다`} 1회`
}

export const ASSET_KO: Record<string, string> = { stock: "주식", etf: "ETF" }
export const listText = (xs: string[] | undefined) => (xs?.length ? xs.join(", ") : "없음")

// 비교지수 목록은 /meta/options(settings.py MarketSettings) 기준. 값(티커)은 그대로 저장하고 이름만 붙인다.
const BENCH_KO: Record<string, string> = { SPY: "미국 S&P 500 지수 (SPY)", QQQ: "미국 NASDAQ-100 지수 (QQQ)", "069500.KS": "한국 KOSPI 200 지수 (KODEX 200, 069500.KS)" }
export const benchName = (b: string) => BENCH_KO[b] ?? b

/** "시가총액 20억 USD 이상" 같은 하한 표시 (0 = 제한 없음). */
export const usdFloor = (v: number | undefined) => (v ? `${koUnits(v)} USD 이상` : "제한 없음")
