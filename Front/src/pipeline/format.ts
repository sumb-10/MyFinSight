import type { Format } from "./types"

// Display rules (Front/docs/04): returns 2 decimals with sign, weights 1 decimal, KRW integer, USD 2 decimals, differences in %p.
const nf = (d: number) => new Intl.NumberFormat("ko-KR", { minimumFractionDigits: d, maximumFractionDigits: d })

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

export const PALETTE = ["#2563eb", "#0f766e", "#b45309", "#7c3aed", "#be123c", "#0369a1", "#4d7c0f", "#9333ea", "#c2410c", "#334155", "#64748b"]
