import { BellRing, Check, ChevronRight } from "lucide-react"
import type { PaperDetail, PaperTrade } from "../../api/types"
import { fmt } from "../../lib/format"
import { Button } from "../../ui"
import { rebalanceText } from "../profile/format"
import { Part } from "../profile/parts"
import { Money, type Cur } from "./money"
import { nextRebalanceText, shownTrades } from "./rebalance"

// 모의투자 첫 화면의 「리밸런싱 거래」: 접힌 상세 기록까지 내려가지 않아도 마지막 리밸런싱에서 산 종목·판 종목을 바로 본다.
// 평소에는 다른 카드처럼 조용히 두고, 확인하지 않은 리밸런싱이 있으면 카드 안에 파란 안내 상자 「지금 리밸런싱할 시점입니다」를 띄운다 (확인 기록은 이 브라우저에만).
// 노란색은 이 앱에서 주의·자료 지연 같은 경고에 쓰므로, 정상적인 정기 리밸런싱 안내에는 쓰지 않는다 (카드 테두리도 다른 카드와 같다).
// 값은 모두 서버 거래 기록 그대로이고, 원화는 거래한 날의 평가 환율로만 바꾼다 (Money).

const pct1 = (v: number) => `${(v * 100).toFixed(1)}%`

export function RebalanceCard({ d, cur, fx, names, fresh, onAck, onAll }: { d: PaperDetail; cur: Cur; fx: Map<string, number>; names: Map<string, string>; fresh: boolean; onAck: () => void; onAll: () => void }) {
  const p = d.portfolio
  const r = shownTrades(d)
  const holdOnly = p.rebalance_rule.count === 0
  const next = holdOnly || p.status === "stopped" ? null : nextRebalanceText(p.rebalance_rule, p.start_date, d.summary.last_date)
  const rule = holdOnly ? "리밸런싱 없음 (처음 산 뒤 그대로 보유)" : `${rebalanceText(p.rebalance_rule as never)} · 기간 첫 거래일`
  const byValue = (xs: PaperTrade[]) => [...xs].sort((a, b) => b.value_usd - a.value_usd)
  const buys = byValue(r?.trades.filter((t) => t.side === "buy") ?? []), sells = byValue(r?.trades.filter((t) => t.side === "sell") ?? [])
  const what = !r ? null : r.kind === "initial" ? "시작할 때 산 종목" : `${r.date} 정기 리밸런싱`
  return (
    <Part title="리밸런싱 거래" desc={<>{what ? `${what} · ` : ""}리밸런싱 주기: {rule}</>}
      aside={next ? <p className="shrink-0 text-right text-xs text-slate-500">다음 리밸런싱<span className="mt-0.5 block text-sm font-semibold text-slate-800">{next}</span></p> : p.status === "stopped" && !holdOnly ? <p className="shrink-0 text-xs text-slate-500">중지 중에는 리밸런싱하지 않습니다</p> : undefined}>
      {fresh && r && (
        <div role="status" className="flex flex-col gap-3 rounded-xl border border-blue-200 bg-blue-50 p-4 sm:flex-row sm:items-center sm:justify-between">
          <div className="flex min-w-0 items-start gap-3">
            <BellRing className="mt-0.5 size-5 shrink-0 text-blue-700" aria-hidden />
            <div className="min-w-0">
              <p className="text-sm font-bold text-blue-950">지금 리밸런싱할 시점입니다</p>
              <p className="mt-0.5 text-xs leading-5 text-blue-900">{r.date} 정기 리밸런싱에서 비중을 목표대로 되돌리려고 아래 종목을 사고팔았습니다. 확인하면 이 안내와 사이드바 숫자가 사라집니다.</p>
            </div>
          </div>
          <Button variant="secondary" className="shrink-0" onClick={onAck}><Check className="size-4" aria-hidden />확인했어요</Button>
        </div>
      )}
      {!r ? <p className="text-sm text-slate-600">아직 거래 기록이 없습니다. {next ? `${next}에 첫 리밸런싱을 합니다.` : ""}</p> : (
        <>
          <div className="grid grid-cols-1 gap-x-8 gap-y-5 sm:grid-cols-2">
            <TradeSide title="매수" dot="bg-red-500" items={buys} date={r.date} cur={cur} fx={fx} names={names} />
            <TradeSide title="매도" dot="bg-blue-500" items={sells} date={r.date} cur={cur} fx={fx} names={names} />
          </div>
          <div className="flex flex-wrap items-center justify-between gap-x-4 gap-y-2 border-t border-slate-100 pt-3 text-xs text-slate-500">
            <p>거래 {r.trades.length}건 · 수수료 <Money usd={r.commission_usd} date={r.date} cur={cur} fx={fx} />{r.kind === "rebalance" ? ` · 회전율 ${pct1(r.turnover)}` : ""} · 그날 종가(USD 환산)로 체결</p>
            <button type="button" onClick={onAll} className="inline-flex items-center gap-0.5 font-semibold text-blue-700 hover:underline">전체 거래 기록 보기<ChevronRight className="size-3.5" aria-hidden /></button>
          </div>
        </>
      )}
    </Part>
  )
}

export function TradeSide({ title, dot, items, date, cur, fx, names }: { title: string; dot: string; items: PaperTrade[]; date: string; cur: Cur; fx: Map<string, number>; names: Map<string, string> }) {
  return (
    <div className="min-w-0">
      <p className="flex items-center gap-1.5 text-xs font-bold text-slate-600"><span className={`size-2 rounded-full ${dot}`} aria-hidden />{title} {items.length}종목</p>
      {items.length === 0 ? <p className="mt-2 text-sm text-slate-500">없음</p> : (
        <ul aria-label={`${title}한 종목`} className="mt-1 divide-y divide-slate-100">
          {items.map((t) => (
            <li key={t.ticker} className="flex items-center justify-between gap-3 py-2 text-sm">
              <span className="min-w-0 truncate"><b className="font-semibold text-slate-900">{t.ticker}</b>{names.get(t.ticker) && <span className="ml-1.5 text-xs text-slate-500">{names.get(t.ticker)}</span>}</span>
              <span className="shrink-0 text-right tabular-nums"><span className="font-semibold text-slate-900"><Money usd={t.value_usd} date={date} cur={cur} fx={fx} compact /></span><span className="block text-xs text-slate-500">{fmt(t.shares, "num")}주</span></span>
            </li>
          ))}
        </ul>
      )}
    </div>
  )
}
