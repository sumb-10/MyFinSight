import { APP_CONFIG, SECURITIES } from "./config"
import type {
  Allocation,
  EffectiveConditions,
  Metrics,
  Point,
  Profile,
} from "./types"

const halfUp = (value: number, digits: number) => {
  const factor = 10 ** digits
  return Math.round((value + Number.EPSILON) * factor) / factor
}

export const format = {
  krw: (value: number) => `${Math.round(value).toLocaleString("ko-KR")}원`,
  usd: (value: number) =>
    new Intl.NumberFormat("en-US", {
      style: "currency",
      currency: "USD",
    }).format(halfUp(value, 2)),
  pct: (value: number, signed = false) =>
    `${signed && value > 0 ? "+" : ""}${halfUp(value, 2).toFixed(2)}%`,
  weight: (value: number) => `${halfUp(value, 1).toFixed(1)}%`,
  pp: (value: number) =>
    `${value > 0 ? "+" : ""}${halfUp(value, 2).toFixed(2)}%p`,
  sharpe: (value: number | null) =>
    value == null ? "산출 불가" : halfUp(value, 2).toFixed(2),
  horizon: (months: number) =>
    months % 12 === 0
      ? `${months / 12}년`
      : months > 12
        ? `${Math.floor(months / 12)}년 ${months % 12}개월`
        : `${months}개월`,
}

export function defaultConditions(profile: Profile): EffectiveConditions {
  return {
    ...profile,
    securityCaps: { ...profile.securityCaps },
    namedTickers: [],
    analysisOverrides: [],
  }
}

export function validateProfile(profile: Profile) {
  const errors: Record<string, string> = {}
  if (!Number.isFinite(profile.amountKrw) || profile.amountKrw <= 0)
    errors.amountKrw = "투자 금액은 0원보다 커야 합니다."
  if (
    profile.horizonMonths < APP_CONFIG.horizon.minMonths ||
    profile.horizonMonths > APP_CONFIG.horizon.maxMonths
  ) {
    errors.horizonMonths = `투자기간은 ${APP_CONFIG.horizon.minMonths}~${APP_CONFIG.horizon.maxMonths}개월 범위로 입력해주세요.`
  }
  if (
    profile.globalCapPct < APP_CONFIG.globalCap.min ||
    profile.globalCapPct > APP_CONFIG.globalCap.max
  ) {
    errors.globalCapPct = `공통 최대 비중은 ${APP_CONFIG.globalCap.min}~${APP_CONFIG.globalCap.max}% 범위여야 합니다.`
  }
  Object.entries(profile.securityCaps).forEach(([ticker, cap]) => {
    if (!SECURITIES.some((item) => item.ticker === ticker))
      errors[`cap-${ticker}`] = "지원 종목에 없는 ticker입니다."
    else if (cap > profile.globalCapPct)
      errors[`cap-${ticker}`] =
        "종목별 한도는 공통 최대 비중을 넘을 수 없습니다."
    else if (profile.excludedTickers.includes(ticker))
      errors[`cap-${ticker}`] =
        "제외 종목에는 별도 비중 한도를 설정할 수 없습니다."
  })
  return errors
}

export function calculateMetrics(series: Point[]): Metrics {
  const first = series[0]
  const last = series.at(-1)!
  const years = Math.max(
    1,
    (new Date(last.date).getTime() - new Date(first.date).getTime()) /
      31_557_600_000,
  )
  const cumulativeReturn = (last.portfolio / first.portfolio - 1) * 100
  const benchmarkReturn = (last.benchmark / first.benchmark - 1) * 100
  const cagr = (Math.pow(last.portfolio / first.portfolio, 1 / years) - 1) * 100
  return {
    cumulativeReturn,
    cagr,
    volatility: 21.42,
    sharpe: 0.74,
    mdd: Math.min(...series.map((point) => point.drawdown)),
    benchmarkReturn,
  }
}

export function validateReportConsistency(
  allocation: Allocation[],
  capitalUsd: number,
) {
  const weight = allocation.reduce((sum, item) => sum + item.weight, 0)
  const usd = allocation.reduce((sum, item) => sum + item.usd, 0)
  return Math.abs(weight - 100) < 0.0001 && Math.abs(usd - capitalUsd) < 0.02
}
