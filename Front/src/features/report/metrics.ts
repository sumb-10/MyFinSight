import { fmt } from "../../lib/format"

// 선정 지표 ID (backend/analysis/m2_data/metrics.py). 값의 단위가 달라 PER 은 배수, 나머지는 비율로 표시한다.
const METRICS: Record<string, { ko: string; per?: boolean }> = { return_12m_1m: { ko: "최근 12개월 수익률, 최근 1개월 제외" }, vol_60d: { ko: "60거래일 변동성" }, pe_ttm: { ko: "최근 12개월 이익 기준 PER", per: true }, roe_ttm: { ko: "최근 12개월 ROE" }, dividend_yield_ttm: { ko: "최근 12개월 배당수익률" } }

export const metricName = (id: string) => METRICS[id]?.ko
export const metricValue = (id: string, v: number) => (METRICS[id]?.per ? `${fmt(v, "num")}배` : fmt(v, "pct"))
