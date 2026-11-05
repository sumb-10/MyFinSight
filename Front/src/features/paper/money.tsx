import type { PaperDetail } from "../../api/types"
import { fmt, krw } from "../../lib/format"
import { money } from "../profile/format"

// 모의투자 금액 표시. 서버 계산은 USD 이고, 원화는 그 날짜의 평가 기록(snapshot.fx_rate)으로만 환산한다. 현재 환율 하나로 과거 금액을 바꾸지 않는다.

export type Cur = "KRW" | "USD"
export const inCur = (v: number, cur: Cur) => fmt(v, cur === "KRW" ? "krw" : "usd")
export const fxByDate = (d: PaperDetail) => new Map(d.snapshots.filter((s) => s.fx_rate).map((s) => [s.date, s.fx_rate as number]))
export const fxText = (rate: number, date: string) => `1 USD = ${rate.toLocaleString("ko-KR", { maximumFractionDigits: 2 })} KRW (${date})`

/** USD 금액을 표시 통화로. 그 날짜 환율이 없으면 환산하지 않고 USD 를 그대로 보여 준다. 정확한 값과 환율은 툴팁으로. */
export function Money({ usd, date, cur, fx, compact }: { usd: number; date: string | null | undefined; cur: Cur; fx: Map<string, number>; compact?: boolean }) {
  if (cur === "USD") return <span className="tabular-nums">{fmt(usd, "usd")}</span>
  const rate = date ? fx.get(date) : undefined
  if (!rate) return <span className="tabular-nums" title="이 날짜의 환율 기록이 없어 원화로 환산하지 못했습니다">{fmt(usd, "usd")}<span className="ml-1 text-[11px] font-normal text-amber-700">환산 불가</span></span>
  const won = Math.round(usd * rate)
  return <span className="tabular-nums" title={`${krw(won)} = ${fmt(usd, "usd")} · ${fxText(rate, date!)}`}>{compact ? money(won, "KRW") : krw(won)}</span>
}
