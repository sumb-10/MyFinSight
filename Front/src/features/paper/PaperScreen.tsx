import { useState } from "react"
import { CartesianGrid, Legend, Line, LineChart, ResponsiveContainer, Tooltip, XAxis, YAxis } from "recharts"
import { Pause, Play, RefreshCw } from "lucide-react"
import { useService } from "../../app/providers"
import { navigate } from "../../app/router"
import { errorMessage } from "../../api/client"
import type { PaperDetail, PaperSummary } from "../../api/types"
import { useResource } from "../../state/useResource"
import { Alert, Badge, Button, Card, EmptyState, ErrorState, Loading, MetricCard, PageHeader } from "../../ui"
import { datetime, fmt, ko, PALETTE, pct, usd, weight } from "../../lib/format"

/** Module6 모의투자: 목록(#/paper) 과 상세(#/paper/:id). 서버가 저장한 수치만 보여 주고 화면에서 다시 계산하지 않는다. */
export function PaperScreen({ paperId }: { paperId?: string }) {
  return paperId ? <PaperDetailScreen paperId={paperId} /> : <PaperList />
}

const statusBadge = (s: PaperSummary) => s.status === "stopped" ? <Badge tone="slate">중지</Badge> : s.update_status === "delayed" ? <Badge tone="amber">자료 지연</Badge> : <Badge tone="green">진행 중</Badge>
const signed = (v: number | null | undefined) => (v == null ? "–" : `${v >= 0 ? "+" : ""}${pct(v)}`)

function PaperList() {
  const svc = useService()
  const res = useResource(() => svc.listPaper(), [svc])
  if (res.status === "loading" && !res.data) return <Loading label="모의투자 목록을 불러오는 중…" />
  if (res.status === "error") return <ErrorState message={res.error ?? ""} retry={res.reload} />
  const rows = res.data ?? []
  return (
    <div className="space-y-6">
      <PageHeader eyebrow="모의투자" title="모의투자" description="완료된 리포트의 전략을 가상 자본으로 따라갑니다. 시작은 리포트 화면의 ‘모의투자 시작’ 버튼에서 합니다. 실제 매매는 하지 않습니다." />
      {rows.length === 0 ? (
        <EmptyState title="진행 중인 모의투자가 없습니다" description="리포트를 열고 ‘모의투자 시작’을 누르면 여기에 나타납니다." action={<Button variant="secondary" onClick={() => navigate({ page: "reports" })}>리포트 보기</Button>} />
      ) : (
        <Card className="overflow-hidden">
          <table className="w-full text-sm">
            <thead className="bg-slate-50 text-left text-xs font-semibold text-slate-500"><tr><th className="px-4 py-3">전략</th><th className="px-4 py-3">시작일</th><th className="px-4 py-3">최근 평가일</th><th className="px-4 py-3 text-right">초기자본</th><th className="px-4 py-3 text-right">현재 평가액</th><th className="px-4 py-3 text-right">운용 수익률</th><th className="px-4 py-3 text-right">비교지수 대비</th><th className="px-4 py-3">상태</th></tr></thead>
            <tbody>
              {rows.map((r) => (
                <tr key={r.paper_id} className="cursor-pointer border-t border-slate-100 hover:bg-slate-50" onClick={() => navigate({ page: "paper", paperId: r.paper_id })}>
                  <td className="px-4 py-3 font-medium text-slate-900">{r.name_ko}<div className="text-xs font-normal text-slate-500">{r.paper_id}</div></td>
                  <td className="px-4 py-3">{r.start_date}</td><td className="px-4 py-3">{r.last_date ?? "–"}</td>
                  <td className="px-4 py-3 text-right">{fmt(r.initial_capital.amount, r.initial_capital.currency === "KRW" ? "krw" : "usd")}</td>
                  <td className="px-4 py-3 text-right">{usd(r.value_usd)}{r.contributions_total_usd > 0 && <div className="text-xs text-slate-500">적립 {usd(r.contributions_total_usd)} 포함</div>}</td>
                  <td className={`px-4 py-3 text-right font-semibold ${r.return_since_start >= 0 ? "text-emerald-700" : "text-red-700"}`}>{signed(r.return_since_start)}</td>
                  <td className="px-4 py-3 text-right">{signed(r.excess_return)}</td>
                  <td className="px-4 py-3">{statusBadge(r)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </Card>
      )}
    </div>
  )
}

function PaperDetailScreen({ paperId }: { paperId: string }) {
  const svc = useService()
  const res = useResource(() => svc.getPaper(paperId), [svc, paperId])
  const [override, setOverride] = useState<PaperDetail | null>(null)
  const [busy, setBusy] = useState("")
  const [err, setErr] = useState<string | null>(null)
  const [view, setView] = useState<"paper" | "backtest">("paper")
  const d = override ?? res.data
  if (res.status === "loading" && !d) return <Loading label="모의투자를 불러오는 중…" />
  if (res.status === "error" && !d) return <EmptyState title="이 모의투자를 열 수 없습니다" description={res.error ?? ""} action={<Button onClick={() => navigate({ page: "paper" })}>목록으로</Button>} />
  if (!d) return null
  const { portfolio: p, summary: s } = d
  const act = async (what: "refresh" | "stop" | "resume") => {
    setBusy(what); setErr(null)
    try { setOverride(await (what === "refresh" ? svc.refreshPaper(paperId) : what === "stop" ? svc.stopPaper(paperId) : svc.resumePaper(paperId))) } catch (e) { setErr(errorMessage(e)) } finally { setBusy("") }
  }
  const rows = d.series.dates.map((date, i) => ({ date, 포트폴리오: d.series.value_usd[i], 비교지수: d.series.benchmark_value_usd[i] ?? undefined, 운용수익률: d.series.return_since_start[i], 비교지수수익률: d.series.benchmark_return_since_start[i] ?? undefined }))
  const latest = d.snapshots[d.snapshots.length - 1]
  return (
    <div className="space-y-8">
      <PageHeader eyebrow={`모의투자 · 번호 ${p.paper_id}`} title={p.name_ko} description={`원본 리포트의 전략을 ${p.start_date} 부터 가상 자본으로 따라갑니다.`}
        actions={<>
          <Button variant="secondary" onClick={() => act("refresh")} disabled={busy !== "" || p.status !== "active"}><RefreshCw className="size-4" />최신 자료로 갱신</Button>
          {p.status === "active" ? <Button variant="danger" onClick={() => act("stop")} disabled={busy !== ""}><Pause className="size-4" />중지</Button> : <Button onClick={() => act("resume")} disabled={busy !== ""}><Play className="size-4" />재개</Button>}
          <Button variant="ghost" onClick={() => navigate({ page: "report", reportId: p.report_id })}>원본 리포트</Button>
        </>} />
      {err && <Alert tone="error" title="처리하지 못했습니다">{err}</Alert>}
      <div className="flex flex-wrap items-center gap-2 text-sm text-slate-600">
        {statusBadge(s)}
        <Badge tone="slate">자료 마감 {s.data_ceiling}</Badge>
        <Badge tone="slate">마지막 평가 {s.last_date ?? "–"}</Badge>
        {s.last_refresh_at && <span className="text-xs">갱신 시각 {datetime(s.last_refresh_at)}</span>}
        {p.reconstructed_at_start && <Badge tone="amber">시작일에 비중 재계산</Badge>}
      </div>
      {s.update_status === "delayed" && <Alert tone="warning" title="자료가 아직 없어 마지막 평가일 이후를 기록하지 못했습니다">{s.delayed_reason_ko}</Alert>}
      {p.status === "stopped" && <Alert tone="info" title="중지 상태입니다">보유는 그대로 두고 평가와 리밸런싱을 멈췄습니다. 재개하면 중지 기간은 비워 두고 재개일부터 다시 기록합니다. 중지 중 지나간 리밸런싱은 건너뛴 것으로 남깁니다.</Alert>}
      <div className="grid grid-cols-2 gap-4 md:grid-cols-4">
        <MetricCard label="가상 초기자본" value={fmt(p.initial_capital.amount, p.initial_capital.currency === "KRW" ? "krw" : "usd")} note={`= ${usd(p.initial_capital.usd)} (${p.initial_capital.fx_date} 환율)`} />
        <MetricCard label="현재 평가액" value={usd(s.value_usd)} note={s.contributions_total_usd > 0 ? `납입 합계 ${usd(s.contributions_total_usd)} · 자산 증가 ${usd(s.gain_usd)}` : `자산 증가 ${usd(s.gain_usd)}`} />
        <MetricCard label="운용 수익률 (납입 제외)" value={signed(s.return_since_start)} note={`비교지수 ${p.benchmark} ${signed(s.benchmark_return_since_start)} · 차이 ${signed(s.excess_return)}`} danger={s.return_since_start < 0} />
        <MetricCard label="현재 낙폭 / 최대 낙폭" value={`${pct(s.drawdown)} / ${pct(s.max_drawdown)}`} note={`${s.days_tracked}거래일 · 리밸런싱 ${s.n_rebalances}회`} danger={s.max_drawdown < -0.1} />
      </div>
      <Card className="p-5">
        <div className="mb-3 flex items-center justify-between">
          <h2 className="text-base font-semibold text-slate-900">시작 이후 성과</h2>
          <div className="flex gap-1 text-xs">
            <button type="button" onClick={() => setView("paper")} className={`rounded-lg px-3 py-1.5 ${view === "paper" ? "bg-blue-50 font-semibold text-blue-700" : "text-slate-600 hover:bg-slate-100"}`}>모의투자 (시작 이후)</button>
            <button type="button" onClick={() => setView("backtest")} className={`rounded-lg px-3 py-1.5 ${view === "backtest" ? "bg-blue-50 font-semibold text-blue-700" : "text-slate-600 hover:bg-slate-100"}`}>과거 백테스트</button>
          </div>
        </div>
        {view === "paper" ? (
          rows.length < 2 ? <p className="text-sm text-slate-500">아직 평가 기록이 하루뿐입니다. 다음 거래일 자료가 들어오면 그래프가 그려집니다.</p> : (
            <div className="h-72">
              <ResponsiveContainer width="100%" height="100%">
                <LineChart data={rows}>
                  <CartesianGrid stroke="#e2e8f0" vertical={false} />
                  <XAxis dataKey="date" tick={{ fontSize: 11 }} minTickGap={32} />
                  <YAxis tickFormatter={(v: number) => pct(v)} tick={{ fontSize: 11 }} width={64} />
                  <Tooltip formatter={(v) => (typeof v === "number" ? pct(v) : String(v))} />
                  <Legend />
                  <Line type="monotone" dataKey="운용수익률" stroke={PALETTE[0]} dot={false} strokeWidth={2} isAnimationActive={false} />
                  <Line type="monotone" dataKey="비교지수수익률" stroke={PALETTE[1]} dot={false} strokeDasharray="4 4" isAnimationActive={false} />
                </LineChart>
              </ResponsiveContainer>
            </div>
          )
        ) : (
          <div className="space-y-2 text-sm text-slate-700">
            <p>과거 백테스트는 전략의 과거 평가이고, 모의투자는 등록한 날 이후의 가상 운용입니다. 두 결과를 한 곡선으로 이어 붙이지 않습니다.</p>
            <Button variant="secondary" onClick={() => navigate({ page: "report", reportId: p.report_id })}>원본 리포트에서 과거 성과 보기</Button>
          </div>
        )}
      </Card>
      <div className="grid gap-6 lg:grid-cols-2">
        <Card className="p-5">
          <h2 className="mb-3 text-base font-semibold text-slate-900">비중</h2>
          <table className="w-full text-sm">
            <thead className="text-left text-xs font-semibold text-slate-500"><tr><th className="py-1.5">종목</th><th className="py-1.5 text-right">시작</th><th className="py-1.5 text-right">현재</th><th className="py-1.5 text-right">목표</th></tr></thead>
            <tbody>
              {Object.keys({ ...p.start_weights, ...(latest?.weights ?? {}) }).sort((a, b) => (latest?.weights[b] ?? 0) - (latest?.weights[a] ?? 0)).map((t) => (
                <tr key={t} className="border-t border-slate-100"><td className="py-1.5 font-medium text-slate-900">{t}</td><td className="py-1.5 text-right text-slate-500">{weight(p.start_weights[t] ?? 0)}</td><td className="py-1.5 text-right">{weight(latest?.weights[t] ?? 0)}</td><td className="py-1.5 text-right text-slate-500">{weight(p.state.target_weights?.[t] ?? 0)}</td></tr>
              ))}
              <tr className="border-t border-slate-200 bg-slate-50"><td className="py-1.5 font-medium text-slate-700">현금</td><td className="py-1.5 text-right text-slate-500">{weight(Math.max(0, 1 - Object.values(p.start_weights).reduce((a, b) => a + b, 0)))}</td><td className="py-1.5 text-right">{latest ? weight(latest.cash_usd / latest.value_usd) : "–"}</td><td className="py-1.5 text-right text-slate-500">{weight(p.state.cash_weight ?? 0)}</td></tr>
            </tbody>
          </table>
        </Card>
        <Card className="p-5">
          <h2 className="mb-3 text-base font-semibold text-slate-900">규칙과 이력</h2>
          <dl className="grid grid-cols-2 gap-y-2 text-sm">
            <dt className="text-slate-500">리밸런싱</dt><dd>{p.rebalance_rule.count === 0 ? "하지 않음 (매수 후 보유)" : `${p.rebalance_rule.count}×${ko(p.rebalance_rule.unit)} 첫 거래일`}</dd>
            <dt className="text-slate-500">월 적립</dt><dd>{p.contribution.enabled ? `${fmt(p.contribution.monthly_amount ?? 0, p.contribution.currency === "KRW" ? "krw" : "usd")} · 매월 ${p.contribution.day}일` : "없음"}</dd>
            <dt className="text-slate-500">비교지수</dt><dd>{p.benchmark}</dd>
            <dt className="text-slate-500">수수료</dt><dd>거래대금의 {((p.constraints_snapshot.commission_bps ?? 5) / 100).toFixed(2)}%</dd>
            <dt className="text-slate-500">체결 규칙</dt><dd>그 전날까지 자료로 비중 계산, 그날 종가(USD 환산) 체결</dd>
          </dl>
          <ul className="mt-4 space-y-1 text-xs text-slate-600">
            {p.history.map((h, i) => <li key={i}>{datetime(h.at)} · {ko(h.event)}{h.note ? ` — ${h.note}` : ""}</li>)}
          </ul>
        </Card>
      </div>
      <Card className="p-5">
        <h2 className="mb-3 text-base font-semibold text-slate-900">거래·리밸런싱 기록</h2>
        <div className="max-h-96 overflow-auto">
          <table className="w-full text-sm">
            <thead className="text-left text-xs font-semibold text-slate-500"><tr><th className="py-1.5">날짜</th><th className="py-1.5">종류</th><th className="py-1.5 text-right">거래 수</th><th className="py-1.5 text-right">수수료</th><th className="py-1.5 text-right">회전율</th><th className="py-1.5">비고</th></tr></thead>
            <tbody>
              {[...d.rebalances].reverse().map((r, i) => (
                <tr key={i} className="border-t border-slate-100 align-top">
                  <td className="py-1.5">{r.date}</td>
                  <td className="py-1.5">{r.skipped ? <Badge tone="slate">건너뜀</Badge> : r.kind === "initial" ? "최초 매수" : r.kind === "contribution" ? "적립 매수" : r.fallback ? <>리밸런싱 <Badge tone="amber">기준 비중</Badge></> : "리밸런싱"}</td>
                  <td className="py-1.5 text-right">{r.trades.length}</td><td className="py-1.5 text-right">{usd(r.commission_usd)}</td><td className="py-1.5 text-right">{pct(r.turnover)}</td>
                  <td className="py-1.5 text-xs text-slate-600">{r.note_ko}{r.views && r.views.length > 0 && <div className="mt-1">뉴스 뷰 {r.views.length}개{r.evidence_window ? ` · 기사 ${r.evidence_window.n_articles}건 (${r.evidence_window.start}~${r.evidence_window.end})` : ""}</div>}{(r.warnings ?? []).map((w, k) => <div key={k} className="text-amber-700">{w}</div>)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </Card>
      <Card className="p-5">
        <h2 className="mb-3 text-base font-semibold text-slate-900">일별 평가 기록</h2>
        <div className="max-h-80 overflow-auto">
          <table className="w-full text-sm">
            <thead className="text-left text-xs font-semibold text-slate-500"><tr><th className="py-1.5">날짜</th><th className="py-1.5 text-right">평가액</th><th className="py-1.5 text-right">현금</th><th className="py-1.5 text-right">적립</th><th className="py-1.5 text-right">운용 수익률</th><th className="py-1.5 text-right">비교지수</th><th className="py-1.5 text-right">낙폭</th><th className="py-1.5 text-right">환율</th></tr></thead>
            <tbody>
              {[...d.snapshots].reverse().map((x) => (
                <tr key={x.date} className="border-t border-slate-100"><td className="py-1.5">{x.date}</td><td className="py-1.5 text-right">{usd(x.value_usd)}</td><td className="py-1.5 text-right">{usd(x.cash_usd)}</td><td className="py-1.5 text-right">{x.contribution_usd ? usd(x.contribution_usd) : "–"}</td><td className="py-1.5 text-right">{signed(x.return_since_start)}</td><td className="py-1.5 text-right">{signed(x.benchmark_return_since_start)}</td><td className="py-1.5 text-right">{pct(x.drawdown)}</td><td className="py-1.5 text-right text-slate-500">{x.fx_rate ? x.fx_rate.toFixed(1) : "–"}</td></tr>
              ))}
            </tbody>
          </table>
        </div>
      </Card>
    </div>
  )
}
