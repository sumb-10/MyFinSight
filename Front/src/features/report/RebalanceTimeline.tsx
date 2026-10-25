import { useEffect, useMemo, useRef, useState } from "react"
import type { CheckpointDetail, TimelineBlock, TimelineItem } from "../../api/types"
import { fmt } from "../../lib/format"
import { Loading } from "../../ui"
import { useReport } from "./context"
import { useService } from "../../app/providers"

const KIND_KO: Record<TimelineItem["kind"], string> = { rebalance: "리밸런싱", closing: "기간 종료", monthly: "월말" }

/** 리밸런싱 타임라인: 점(시점) 스트립 + 선택 시점 요약 + 상세(보유·거래)는 서버에서 지연 로딩. ←/→ 로 이동. */
export function RebalanceTimeline({ b }: { b: TimelineBlock }) {
  const rep = useReport()
  const svc = useService()
  const items = b.items
  const [sel, setSel] = useState<number>(() => rep?.selectedRb ?? items[items.length - 1]?.seq ?? 0)
  const [all, setAll] = useState(false)
  const cache = useRef(new Map<number, CheckpointDetail | null>())
  const [detail, setDetail] = useState<CheckpointDetail | null | "pending" | "error">("pending")
  const [retry, setRetry] = useState(0)
  const cur = items.find((x) => x.seq === sel) ?? items[items.length - 1]
  useEffect(() => { if (rep && rep.selectedRb !== null && rep.selectedRb !== sel) setSel(rep.selectedRb) }, [rep, rep?.selectedRb])  // eslint-disable-line react-hooks/exhaustive-deps
  useEffect(() => {
    if (!cur) return
    if (cache.current.has(cur.seq)) { setDetail(cache.current.get(cur.seq) ?? null); return }
    let alive = true
    setDetail("pending")
    if (!rep) { setDetail(null); return }
    svc.getReportCheckpoint(rep.reportId, cur.seq, b.portfolio_id).then((d) => { cache.current.set(cur.seq, d); if (alive) setDetail(d) }).catch(() => { if (alive) setDetail("error") })  // 404(기록 없음)는 null, 그 밖은 오류
    return () => { alive = false }
  }, [rep, svc, cur, b.portfolio_id, retry])
  const idx = items.findIndex((x) => x.seq === cur?.seq)
  const move = (d: number) => { const n = items[Math.min(items.length - 1, Math.max(0, idx + d))]; if (n) { setSel(n.seq); rep?.setSelectedRb(n.seq) } }
  const onKey = (e: React.KeyboardEvent) => { if (e.key === "ArrowLeft") { e.preventDefault(); move(-1) } else if (e.key === "ArrowRight") { e.preventDefault(); move(1) } }
  const stats = useMemo(() => ({ n: items.filter((x) => x.kind === "rebalance").length, views: items.filter((x) => x.news && x.news.n_views > 0).length, fallback: items.filter((x) => x.news?.fallback).length }), [items])
  if (!cur) return null
  return (
    <div className="rounded-xl border border-slate-200 bg-white p-5">
      <div className="mb-2 flex flex-wrap items-baseline justify-between gap-2">
        <h3 className="text-base font-semibold text-slate-900">{b.title_ko}</h3>
        <p className="text-xs text-slate-500">시점 {items.length}개 (리밸런싱 {stats.n}){b.walkforward ? ` · 뉴스·공시 뷰 적용 ${stats.views}회 · 기준 비중 유지 ${stats.fallback}회` : ""}</p>
      </div>
      <div role="listbox" aria-label="리밸런싱 시점 (←/→ 로 이동)" tabIndex={0} onKeyDown={onKey} className="flex items-center gap-1 overflow-x-auto rounded-lg border border-slate-100 bg-slate-50 px-3 py-3 focus:outline-none focus:ring-2 focus:ring-blue-500">
        {items.map((it) => {
          const on = it.seq === cur.seq
          const color = it.news ? (it.news.fallback || it.news.n_views === 0 ? "bg-slate-300" : "bg-blue-600") : "bg-slate-400"
          const shape = it.kind === "closing" ? "rounded-sm" : it.kind === "monthly" ? "rounded-full scale-75" : "rounded-full"
          return <button key={it.seq} role="option" aria-selected={on} aria-label={`${it.date} ${KIND_KO[it.kind]}`} title={`${it.date} · ${KIND_KO[it.kind]}${it.news ? ` · 뉴스 ${it.news.n_articles} 공시 ${it.news.n_disclosures} 뷰 ${it.news.n_views}` : ""}`} onClick={() => { setSel(it.seq); rep?.setSelectedRb(it.seq) }} className={`size-4 shrink-0 ${shape} ${color} ${on ? "ring-2 ring-offset-2 ring-blue-700" : "hover:ring-2 hover:ring-slate-400"}`} />
        })}
      </div>
      <div className="mt-2 flex flex-wrap gap-3 text-[11px] text-slate-500"><span><i className="mr-1 inline-block size-2.5 rounded-full bg-blue-600 align-middle" />뉴스·공시 뷰 적용</span><span><i className="mr-1 inline-block size-2.5 rounded-full bg-slate-300 align-middle" />기준 비중 유지(근거 부족)</span><span><i className="mr-1 inline-block size-2.5 rounded-full bg-slate-400 align-middle" />뷰 정보 없음</span><span><i className="mr-1 inline-block size-2.5 rounded-sm bg-slate-400 align-middle" />기간 종료</span></div>
      <Selected it={cur} idx={idx} total={items.length} move={move} detail={detail} walkforward={b.walkforward} onRetry={() => { cache.current.delete(cur.seq); setRetry((n) => n + 1) }} />
      <button type="button" onClick={() => setAll((v) => !v)} className="mt-3 text-xs font-semibold text-blue-700 hover:underline" aria-expanded={all}>{all ? "전체 표 접기" : `전체 표 보기 (${items.length}행)`}</button>
      {all && <AllTable items={items} onPick={(s) => { setSel(s); rep?.setSelectedRb(s) }} />}
      {b.note_ko && <p className="mt-2 text-xs text-slate-500">{b.note_ko}</p>}
    </div>
  )
}

function Selected({ it, idx, total, move, detail, walkforward, onRetry }: { it: TimelineItem; idx: number; total: number; move: (d: number) => void; detail: CheckpointDetail | null | "pending" | "error"; walkforward: boolean; onRetry?: () => void }) {
  const rep = useReport()
  const sl = it.since_last
  return (
    <div className="mt-4 rounded-lg border border-slate-200 p-4">
      <div className="flex items-center justify-between gap-3">
        <div><span className="text-sm font-bold text-slate-900">{it.date}</span><span className="ml-2 text-xs text-slate-500">{KIND_KO[it.kind]} · {it.n_trading_days_to_date}거래일 경과 · 거래 {it.n_trades}건{it.commission_usd !== null ? ` · 비용 ${fmt(it.commission_usd, "usd")}` : ""}</span></div>
        <div className="flex gap-1 text-xs"><button type="button" aria-label="이전 시점" disabled={idx <= 0} onClick={() => move(-1)} className="rounded-lg border border-slate-200 px-2 py-1 disabled:opacity-40 hover:bg-slate-50">←</button><span className="px-1 py-1 tabular-nums text-slate-500">{idx + 1}/{total}</span><button type="button" aria-label="다음 시점" disabled={idx >= total - 1} onClick={() => move(1)} className="rounded-lg border border-slate-200 px-2 py-1 disabled:opacity-40 hover:bg-slate-50">→</button></div>
      </div>
      <div className="mt-3 grid grid-cols-4 gap-3 text-sm">
        <Stat label="평가금액" value={fmt(it.value_usd, "usd")} sub={it.benchmark_value_usd !== null ? `비교지수 동일 적립 ${fmt(it.benchmark_value_usd, "usd")}` : undefined} />
        <Stat label="투입 원금" value={fmt(it.net_invested_usd, "usd")} sub={it.cash_after !== null ? `현금 ${fmt(it.cash_after, "pct1")}` : undefined} />
        <Stat label="직전 시점 이후" value={sl ? fmt(sl.return, "pct") : "–"} sub={sl ? `비교지수 ${fmt(sl.benchmark_return, "pct")} · 차이 ${fmt(sl.excess, "pp")} · 구간 MDD ${fmt(sl.max_drawdown, "pct")}` : "구성일"} />
        <Stat label="시작부터 누적" value={it.to_date ? fmt(it.to_date.total_return, "pct") : "–"} sub={it.to_date ? `CAGR ${fmt(it.to_date.cagr, "pct")} · MDD ${fmt(it.to_date.max_drawdown, "pct")} · Sharpe ${fmt(it.to_date.sharpe, "ratio")}` : undefined} />
      </div>
      {walkforward && it.news && (
        <div className="mt-3 rounded-lg bg-slate-50 p-3 text-sm">
          <p className="text-xs text-slate-500">근거 창: 뉴스 {it.news.n_articles}건{it.news.window ? ` (${it.news.window[0]} ~ ${it.news.window[1]})` : ""} · 공시 {it.news.n_disclosures}건{it.news.disclosure_window ? ` (${it.news.disclosure_window[0]} ~)` : ""} · 근거 있는 종목 {it.news.n_tickers_with_evidence}개 → {it.news.fallback ? "근거 부족으로 기준 비중 유지" : `뷰 ${it.news.n_views}개 적용`}</p>
          {it.views.length > 0 && <ul className="mt-2 space-y-1">{it.views.map((v, i) => <li key={i} className="flex flex-wrap items-baseline gap-2 text-sm text-slate-700"><span>{v.summary_ko}</span><span className="text-xs text-slate-400">신뢰도 {v.confidence !== null ? v.confidence.toFixed(2) : "–"}{v.evidence_type ? ` · ${v.evidence_type === "disclosure" ? "공시" : v.evidence_type === "mixed" ? "공시+뉴스" : "뉴스"}` : ""}</span>{rep && v.evidence_ids.map((id) => <button key={id} type="button" onClick={() => rep.openEvidence(id)} className="text-[11px] font-bold text-blue-700 hover:underline" aria-label={`근거 ${id} 보기`}>[{rep.numberOf(id)}]</button>)}</li>)}</ul>}
          {it.top_delta.length > 0 && <p className="mt-2 text-xs text-slate-500">기준 대비 주요 변화: {it.top_delta.map((d) => `${d.ticker} ${fmt(d.delta, "pp")}`).join(", ")}</p>}
        </div>
      )}
      <div className="mt-3">
        {detail === "pending" ? <Loading label="보유·거래 상세를 불러오는 중…" /> : detail === "error" ? <p className="text-xs text-slate-500">보유·거래 상세를 불러오지 못했습니다 (서버 연결). <button type="button" onClick={onRetry} className="font-semibold text-blue-700 hover:underline">다시 시도</button></p> : detail === null ? <p className="text-xs text-slate-500">이 시점의 보유·거래 기록은 저장돼 있지 않습니다.</p> : <Holdings d={detail} />}
      </div>
    </div>
  )
}

function Stat({ label, value, sub }: { label: string; value: string; sub?: string }) {
  return <div className="rounded-lg bg-white"><p className="text-xs text-slate-500">{label}</p><p className="mt-0.5 text-base font-semibold tabular-nums text-slate-900">{value}</p>{sub && <p className="text-[11px] text-slate-500">{sub}</p>}</div>
}

function Holdings({ d }: { d: CheckpointDetail }) {
  const cp = d.checkpoint
  return (
    <div className="overflow-x-auto">
      <table className="w-full text-xs">
        <thead><tr className="border-b border-slate-200 text-left text-slate-500"><th className="px-1 py-1">종목</th><th className="px-1 py-1 text-right">직전 비중</th><th className="px-1 py-1 text-right">목표</th><th className="px-1 py-1 text-right">조정 후</th><th className="px-1 py-1 text-right">구간 수익률</th><th className="px-1 py-1 text-right">구간 기여</th><th className="px-1 py-1 text-right">평가액</th></tr></thead>
        <tbody>{cp.holdings.map((h) => <tr key={h.ticker} className="border-b border-slate-100"><td className="px-1 py-1 font-medium" title={d.names[h.ticker]}>{h.ticker}</td><td className="px-1 py-1 text-right tabular-nums">{fmt(h.weight_before, "pct1")}</td><td className="px-1 py-1 text-right tabular-nums">{fmt(cp.weights.target[h.ticker], "pct1")}</td><td className="px-1 py-1 text-right tabular-nums">{fmt(h.weight_after, "pct1")}</td><td className="px-1 py-1 text-right tabular-nums">{fmt(h.period_return, "pct")}</td><td className="px-1 py-1 text-right tabular-nums">{fmt(h.period_contribution, "pp")}</td><td className="px-1 py-1 text-right tabular-nums">{fmt(h.value_usd, "usd")}</td></tr>)}</tbody>
      </table>
      {cp.trades.length > 0 && <p className="mt-2 text-xs text-slate-500">거래: {cp.trades.map((t) => `${t.ticker} ${t.side === "buy" ? "매수" : "매도"} ${fmt(t.value_usd, "usd")}`).join(" · ")}</p>}
      {d.narrative_ko && <p className="mt-2 text-xs leading-5 text-slate-600">{d.narrative_ko}</p>}
    </div>
  )
}

function AllTable({ items, onPick }: { items: TimelineItem[]; onPick: (seq: number) => void }) {
  return (
    <div className="mt-2 max-h-80 overflow-auto rounded-lg border border-slate-100">
      <table className="w-full text-xs"><thead className="sticky top-0 bg-white"><tr className="border-b border-slate-200 text-left text-slate-500"><th className="px-2 py-1">날짜</th><th className="px-2 py-1">종류</th><th className="px-2 py-1 text-right">평가금액</th><th className="px-2 py-1 text-right">구간 수익률</th><th className="px-2 py-1 text-right">비교지수</th><th className="px-2 py-1 text-right">뉴스/공시/뷰</th><th className="px-2 py-1 text-right">거래</th></tr></thead>
        <tbody>{items.map((it) => <tr key={it.seq} className="cursor-pointer border-b border-slate-100 hover:bg-slate-50" onClick={() => onPick(it.seq)}><td className="px-2 py-1">{it.date}</td><td className="px-2 py-1">{KIND_KO[it.kind]}</td><td className="px-2 py-1 text-right tabular-nums">{fmt(it.value_usd, "usd")}</td><td className="px-2 py-1 text-right tabular-nums">{fmt(it.since_last?.return, "pct")}</td><td className="px-2 py-1 text-right tabular-nums">{fmt(it.since_last?.benchmark_return, "pct")}</td><td className="px-2 py-1 text-right tabular-nums">{it.news ? `${it.news.n_articles}/${it.news.n_disclosures}/${it.news.n_views}${it.news.fallback ? " (유지)" : ""}` : "–"}</td><td className="px-2 py-1 text-right tabular-nums">{it.n_trades}</td></tr>)}</tbody></table>
    </div>
  )
}
