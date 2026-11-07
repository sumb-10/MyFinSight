import { useEffect, useMemo, useState } from "react"
import { CartesianGrid, Legend, Line, LineChart, ResponsiveContainer, Tooltip, XAxis, YAxis } from "recharts"
import { Activity, BellRing, ChevronRight, FileText, Link2, Pause, PencilLine, Play, RefreshCw } from "lucide-react"
import { useService } from "../../app/providers"
import { navigate } from "../../app/router"
import { errorMessage } from "../../api/client"
import type { PaperDetail, PaperPortfolio, PaperRebalance, PaperSummary, ReportRow } from "../../api/types"
import { useResource } from "../../state/useResource"
import { Alert, Badge, Button, Card, Dialog, EmptyState, ErrorState, Loading, Menu, PageHeader } from "../../ui"
import { datetime, fmt, ko, PALETTE, pct, usd, weight } from "../../lib/format"
import { FlowHeader } from "../analysis/flow"
import { Part, PartDisclosure } from "../profile/parts"
import { rebalanceText } from "../profile/format"
import { useFluidShell } from "../report/useFluidShell"
import { Money, fxByDate, inCur, type Cur } from "./money"
import { PaperNameDialog } from "./PaperName"
import { FxStatus, KrwPerformance } from "./KrwPerformance"
import { MockTag } from "../report/proposedView"
import { paperBasis, paperStrategy, samePapers } from "./paperLabel"
import { findReportRow, reportName } from "../../lib/reportName"
import { initPapers, markRebalanceSeen, useSeen } from "../../lib/seen"
import { RebalanceCard } from "./RebalanceCard"
import { freshRebalance } from "./rebalance"
import { useRebalanceAlerts } from "../attention"

/** Module6 모의투자: 목록(#/paper) 과 상세(#/paper/:id). 서버가 저장한 수치만 보여 주고 화면에서 다시 계산하지 않는다 (원화는 날짜별 환율로 표시만 바꾼다). */
export function PaperScreen({ paperId }: { paperId?: string }) {
  useFluidShell()
  return paperId ? <PaperDetailScreen key={paperId} paperId={paperId} /> : <PaperList />
}

const runBadge = (s: { status: string }) => (s.status === "stopped" ? <Badge tone="slate">운용 중지</Badge> : <Badge tone="green">운용 중</Badge>)
const dataBadge = (s: PaperSummary) => (s.update_status === "delayed" ? <Badge tone="amber">자료 지연</Badge> : <Badge tone="slate">자료 정상</Badge>)
const USD_BASIS = "USD 기준 · 원화 환율 변동 미반영"

/** 목록의 평가액: 원화 모의투자는 마지막 평가일 환율이 필요해 상세를 읽는다 (목록 응답에는 없다). */
function ListValue({ r }: { r: PaperSummary }) {
  const svc = useService()
  const cur = r.initial_capital.currency
  const res = useResource(() => (cur === "KRW" ? svc.getPaper(r.paper_id) : Promise.resolve(null)), [svc, r.paper_id, cur])
  const fx = useMemo(() => (res.data ? fxByDate(res.data) : new Map<string, number>()), [res.data])
  if (cur === "KRW" && res.status === "loading") return <span className="tabular-nums text-slate-500">{usd(r.value_usd)}</span>
  return <Money usd={r.value_usd} date={r.last_date} cur={cur} fx={fx} />
}

/** 목록 수익률 칸. 원화 기준 성과(제안 기능, 지금은 목업만)가 있으면 원화 수익률(넣은 원금 대비), 없으면 서버의 USD 운용 수익률 그대로. */
function ListReturn({ r }: { r: PaperSummary }) {
  const svc = useService()
  const krw = useResource(() => (svc.getPaperKrw ? svc.getPaperKrw(r.paper_id) : Promise.resolve(null)), [svc, r.paper_id])
  const v = svc.getPaperKrw ? krw.data?.return_krw ?? null : r.return_since_start
  if (svc.getPaperKrw && krw.status === "loading") return <span className="text-slate-400">…</span>
  if (v == null) return <span className="font-normal text-slate-500">계산 불가</span>
  return <span className={v >= 0 ? "text-emerald-700" : "text-red-700"}>{pct(v)}</span>
}

/** 목록 첫 칸: 이름 · 적용 전략(이름과 다를 때만) · 원본 리포트(늘), 각각 한 줄. 시작일·초기자본은 옆 열에, 같은 리포트의 다른 모의투자는 상세 「더보기」에 있다. */
function ListName({ r, reports }: { r: PaperSummary; reports: ReportRow[] | null }) {
  const svc = useService()
  const rr = findReportRow(reports, r.report_id) ?? findReportRow(reports, r.run_id)
  const src = rr ? reportName(rr) : null
  const strategy = paperStrategy(r)
  const origin = `원본 리포트: ${src ?? r.report_id}`  // 원본 리포트는 이름과 같아도 늘 보여 준다
  return (
    <>
      {/* 리포트 목록과 같은 글씨 단계: 이름(진하게) → 적용 전략(회색) → 원본 리포트(연한 회색), 줄 사이를 조금 띄운다 */}
      {/* 「목업」 표시는 두 줄 자르기(line-clamp) 밖에 둔다 — 안에 두면 표시가 줄 높이만큼 늘어나 아래 줄과 사이가 벌어진다 */}
      <p className="flex items-center"><span className="line-clamp-2 min-w-0 break-words font-semibold leading-5 text-slate-800" title={r.name_ko}>{r.name_ko}</span>{svc.getPaperName && <MockTag />}</p>
      <div className="mt-0.5 space-y-px text-xs leading-5">
        {strategy !== r.name_ko && <p className="truncate text-slate-500" title={strategy}>{strategy}</p>}
        <p className="truncate text-slate-400" title={origin}>{origin}</p>
      </div>
    </>
  )
}

function PaperList() {
  const svc = useService()
  const res = useResource(() => svc.listPaper(), [svc])
  const reports = useResource(() => svc.listReports(), [svc])  // 원본 리포트 이름 (리포트 화면과 같은 기준)
  const alerts = useRebalanceAlerts(res.data)  // 확인하지 않은 리밸런싱 거래가 있는 모의투자
  if (res.status === "loading" && !res.data) return <Loading label="모의투자 목록을 불러오는 중…" />
  if (res.status === "error") return <ErrorState message={res.error ?? ""} retry={res.reload} />
  const rows = res.data ?? []
  return (
    <div className="space-y-6">
      <PageHeader eyebrow="모의투자" title="모의투자" description="완료된 리포트의 전략을 가상 자본으로 따라갑니다. 시작은 리포트 화면의 ‘모의투자 시작’ 버튼에서 합니다. 실제 매매는 하지 않습니다." />
      {rows.length === 0 ? (
        <EmptyState title="진행 중인 모의투자가 없습니다" description="리포트를 열고 ‘모의투자 시작’을 누르면 여기에 나타납니다." action={<Button variant="secondary" onClick={() => navigate({ page: "reports" })}>리포트 보기</Button>} />
      ) : (
        <Card className="overflow-x-auto">
          <table className="w-full min-w-[900px] text-sm">
            {/* 날짜·금액·수익률·상태·열 제목은 줄을 바꾸지 않는다 (남는 폭은 전략 칸이 쓴다) */}
            <thead className="whitespace-nowrap bg-slate-50 text-left text-xs font-semibold text-slate-500"><tr><th className="w-full px-4 py-3">모의투자</th><th className="px-4 py-3">시작일</th><th className="px-4 py-3">최근 평가일</th><th className="px-4 py-3 text-right">초기자본</th><th className="px-4 py-3 text-right">현재 평가액</th>
              <th className="px-4 py-3 text-right">{svc.getPaperKrw ? <span className="inline-flex items-center" title="날짜별로 넣은 원화 금액과 그날 환율로 환산한 평가액으로 계산한 수익률입니다">원화 수익률<MockTag /></span> : <span title="납입 시점의 영향을 뺀 USD 기준 수익률입니다">운용 수익률 (USD)</span>}</th>
              <th className="px-4 py-3 text-right" title="같은 기간 비교지수 수익률과의 차이 (USD 기준)">비교지수 대비</th><th className="px-4 py-3">상태</th></tr></thead>
            <tbody>
              {rows.map((r) => (
                <tr key={r.paper_id} className="cursor-pointer border-t border-slate-100 hover:bg-slate-50" onClick={() => navigate({ page: "paper", paperId: r.paper_id })}>
                  <td className="max-w-0 px-4 py-4"><ListName r={r} reports={reports.data} /></td>
                  <td className="whitespace-nowrap px-4 py-3 tabular-nums">{r.start_date}</td><td className="whitespace-nowrap px-4 py-3 tabular-nums">{r.last_date ?? "–"}</td>
                  <td className="whitespace-nowrap px-4 py-3 text-right tabular-nums">{inCur(r.initial_capital.amount, r.initial_capital.currency)}</td>
                  <td className="whitespace-nowrap px-4 py-3 text-right tabular-nums"><ListValue r={r} />{r.contributions_total_usd > 0 && <div className="text-xs text-slate-500">적립 포함</div>}</td>
                  <td className="whitespace-nowrap px-4 py-3 text-right font-semibold tabular-nums"><ListReturn r={r} /></td>
                  <td className="whitespace-nowrap px-4 py-3 text-right tabular-nums">{r.excess_return == null ? "–" : fmt(r.excess_return, "pp")}</td>
                  <td className="whitespace-nowrap px-4 py-3"><span className="flex flex-col items-start gap-1">{runBadge(r)}{r.update_status === "delayed" && dataBadge(r)}{alerts.has(r.paper_id) && <Badge tone="blue"><BellRing className="size-3" aria-hidden />리밸런싱 확인</Badge>}</span></td>
                </tr>
              ))}
            </tbody>
          </table>
        </Card>
      )}
    </div>
  )
}

function Stat({ label, value, note, tone }: { label: string; value: React.ReactNode; note?: React.ReactNode; tone?: "up" | "down" | "warn" }) {
  const color = tone === "up" ? "text-emerald-700" : tone === "down" ? "text-red-700" : tone === "warn" ? "text-amber-800" : "text-slate-950"
  return <div className="min-w-0"><p className="text-xs font-semibold text-slate-500">{label}</p><p className={`mt-1 break-words text-2xl font-bold tabular-nums ${color}`}>{value}</p>{note && <p className="mt-1 text-xs leading-5 text-slate-500">{note}</p>}</div>
}
function Small({ label, value, note }: { label: string; value: React.ReactNode; note?: React.ReactNode }) {
  return <div className="min-w-0"><dt className="text-xs font-semibold text-slate-500">{label}</dt><dd className="mt-0.5 break-words text-sm font-semibold text-slate-900">{value}</dd>{note && <dd className="text-xs leading-5 text-slate-500">{note}</dd>}</div>
}

type Event = { date: string; title: string; detail?: string | null; tone?: "slate" | "amber" }
const kindText = (r: PaperRebalance) => (r.skipped ? "리밸런싱 건너뜀" : r.kind === "initial" ? "최초 매수" : r.kind === "contribution" ? "적립 매수" : r.fallback ? "리밸런싱 (근거 부족으로 기준 비중 유지)" : "리밸런싱")
/** 첫 화면의 최근 이벤트: 거래 기록 + 중지·재개·갱신 실패. 건너뜀은 거래 기록에 있으므로 이력에서 다시 세지 않는다. */
function recentEvents(d: PaperDetail): Event[] {
  const rb = d.rebalances.map((r): Event => ({ date: r.date, title: kindText(r), detail: r.note_ko, tone: r.skipped ? "amber" : "slate" }))
  const his = d.portfolio.history.flatMap((h): Event[] => h.event === "stopped" ? [{ date: h.at.slice(0, 10), title: "모의운용 중지", detail: h.note }] : h.event === "resumed" ? [{ date: h.at.slice(0, 10), title: "모의운용 재개", detail: h.note }] : h.event === "refresh_failed" ? [{ date: h.at.slice(0, 10), title: "자료 갱신 실패", detail: h.note, tone: "amber" }] : [])
  return [...rb, ...his].sort((a, b) => b.date.localeCompare(a.date)).slice(0, 5)
}

/** 재개 지점에 빈 행을 넣어 중지 기간을 선으로 잇지 않는다 (서버가 평가하지 않은 기간을 보간하지 않는다). */
function chartRows(d: PaperDetail) {
  const resumes = d.portfolio.history.filter((h) => h.event === "resumed").map((h) => /^\d{4}-\d{2}-\d{2}/.exec(h.note ?? "")?.[0]).filter(Boolean) as string[]
  const rows: Record<string, string | number | null | undefined>[] = []
  let gap = 0
  d.series.dates.forEach((date, i) => {
    const prev = d.series.dates[i - 1]
    if (prev && resumes.some((r) => prev < r && r <= date)) rows.push({ date: `중지 기간 ${++gap}`, 운용수익률: null, 비교지수수익률: null })
    rows.push({ date, 운용수익률: d.series.return_since_start[i], 비교지수수익률: d.series.benchmark_return_since_start[i] ?? null })
  })
  return { rows, gap }
}

function Holdings({ d, names }: { d: PaperDetail; names: Map<string, string> }) {
  const p = d.portfolio
  const latest = d.snapshots[d.snapshots.length - 1]
  const target = p.state.target_weights
  const tickers = [...new Set([...Object.keys(latest?.weights ?? {}), ...Object.keys(target ?? {}), ...Object.keys(p.start_weights)])].sort((a, b) => (latest?.weights[b] ?? -1) - (latest?.weights[a] ?? -1))
  const w = (v: number | undefined | null) => (v == null ? "–" : weight(v))
  const curCash = latest ? latest.cash_usd / latest.value_usd : null
  const startCash = Math.max(0, 1 - Object.values(p.start_weights).reduce((a, b) => a + b, 0))
  const Bar = ({ v }: { v: number | null | undefined }) => <span className="block h-1.5 w-full overflow-hidden rounded-full bg-slate-100">{v != null && <span className="block h-full rounded-full bg-blue-600" style={{ width: `${Math.min(100, v * 100)}%` }} />}</span>
  return (
    <Part title="현재 보유 구성" desc={`현재 비중: ${latest ? `${latest.date} 평가 기준` : "평가 기록 없음"} · 목표 비중: ${p.state.last_rebalance_date ? `${p.state.last_rebalance_date} 리밸런싱 기준` : "시작 시 기준"}`}>
      <div className="overflow-x-auto">
        <table className="w-full text-sm">
          <thead className="text-left text-xs font-semibold text-slate-500"><tr><th className="py-1.5 pr-3">종목</th><th className="w-1/3 py-1.5 pr-3 sm:w-2/5">현재 비중</th><th className="py-1.5 text-right">목표 비중</th></tr></thead>
          <tbody>
            {tickers.map((t) => <tr key={t} className="border-t border-slate-100"><td className="py-2 pr-3"><b className="text-slate-900">{t}</b>{names.get(t) && <span className="ml-1.5 text-slate-600">{names.get(t)}</span>}</td><td className="py-2 pr-3"><span className="flex flex-col gap-1 sm:flex-row sm:items-center sm:gap-2"><span className="shrink-0 tabular-nums font-semibold sm:w-14">{w(latest?.weights[t])}</span><Bar v={latest?.weights[t]} /></span></td><td className="whitespace-nowrap py-2 text-right tabular-nums text-slate-600">{w(target?.[t])}</td></tr>)}
            <tr className="border-t border-slate-200 bg-slate-50"><td className="py-2 pr-3 font-medium text-slate-700">현금</td><td className="py-2 pr-3"><span className="flex flex-col gap-1 sm:flex-row sm:items-center sm:gap-2"><span className="shrink-0 tabular-nums font-semibold sm:w-14">{w(curCash)}</span><Bar v={curCash} /></span></td><td className="py-2 text-right tabular-nums text-slate-600">{w(p.state.cash_weight)}</td></tr>
          </tbody>
        </table>
      </div>
      <PartDisclosure title="비중 변화 보기">
        <div className="overflow-x-auto">
          <table className="w-full min-w-[340px] text-sm">
            <thead className="text-left text-xs font-semibold text-slate-500"><tr><th className="py-1.5">종목</th><th className="py-1.5 text-right">시작 ({p.start_date})</th><th className="py-1.5 text-right">현재</th><th className="py-1.5 text-right">목표</th></tr></thead>
            <tbody>
              {tickers.map((t) => <tr key={t} className="border-t border-slate-100"><td className="py-1.5 font-medium">{t}</td><td className="py-1.5 text-right tabular-nums">{w(p.start_weights[t])}</td><td className="py-1.5 text-right tabular-nums">{w(latest?.weights[t])}</td><td className="py-1.5 text-right tabular-nums">{w(target?.[t])}</td></tr>)}
              <tr className="border-t border-slate-200"><td className="py-1.5">현금</td><td className="py-1.5 text-right tabular-nums">{w(startCash)}</td><td className="py-1.5 text-right tabular-nums">{w(curCash)}</td><td className="py-1.5 text-right tabular-nums">{w(p.state.cash_weight)}</td></tr>
            </tbody>
          </table>
        </div>
      </PartDisclosure>
    </Part>
  )
}

function Rules({ p }: { p: PaperPortfolio }) {
  return (
    <dl className="grid grid-cols-1 gap-3 sm:grid-cols-2">
      <Small label="리밸런싱" value={p.rebalance_rule.count === 0 ? "하지 않음 (매수 후 보유)" : rebalanceText(p.rebalance_rule as never)} />
      <Small label="월 적립" value={p.contribution.enabled ? `${inCur(p.contribution.monthly_amount ?? 0, p.contribution.currency ?? p.initial_capital.currency)} · 매월 ${p.contribution.day}일` : "없음"} />
      <Small label="비교지수" value={p.benchmark} />
      <Small label="수수료" value={`거래대금의 ${((p.constraints_snapshot.commission_bps ?? 5) / 100).toFixed(2)}%`} />
      <Small label="체결 규칙" value="그 전날까지 자료로 비중 계산, 그날 종가(USD 환산) 체결" />
    </dl>
  )
}

/** 같은 리포트로 시작한 다른 모의투자 목록 창. 줄을 누르면 그 모의투자로 이동한다. 값은 모두 서버 목록(listPaper) 그대로. */
function SiblingPapersDialog({ papers, close }: { papers: PaperSummary[]; close: () => void }) {
  return (
    <Dialog title={`같은 리포트로 시작한 다른 모의투자 ${papers.length}개`} close={close}>
      <ul className="divide-y divide-slate-100 px-2 py-2">
        {papers.map((o) => (
          <li key={o.paper_id}>
            <button type="button" onClick={() => { close(); navigate({ page: "paper", paperId: o.paper_id }) }} className="flex w-full flex-wrap items-center justify-between gap-x-4 gap-y-1 rounded-xl px-4 py-3.5 text-left hover:bg-slate-50 focus:outline-none focus-visible:ring-2 focus-visible:ring-blue-500">
              <span className="min-w-0">
                <span className="block font-semibold text-slate-900">{o.name_ko}</span>
                <span className="mt-0.5 block text-xs text-slate-600">{paperBasis(o, o.name_ko)}</span>
                <span className="mt-0.5 block text-xs text-slate-500">최근 평가일 {o.last_date ?? "–"}</span>
              </span>
              <span className="flex shrink-0 items-center gap-3">
                <span className={`text-sm font-semibold tabular-nums ${o.return_since_start >= 0 ? "text-emerald-700" : "text-red-700"}`}>{pct(o.return_since_start)}</span>
                {runBadge(o)}
                <ChevronRight className="size-4 text-slate-400" aria-hidden />
              </span>
            </button>
          </li>
        ))}
      </ul>
      <p className="border-t border-slate-200 px-6 py-3 text-xs text-slate-500">수익률은 운용 수익률(USD 기준)입니다.</p>
    </Dialog>
  )
}

function PaperDetailScreen({ paperId }: { paperId: string }) {
  const svc = useService()
  const res = useResource(() => svc.getPaper(paperId), [svc, paperId])
  const [override, setOverride] = useState<PaperDetail | null>(null)
  const [busy, setBusy] = useState<"" | "refresh" | "stop" | "resume">("")
  const [err, setErr] = useState<string | null>(null)
  const [refreshed, setRefreshed] = useState<string | null>(null)
  const [askStop, setAskStop] = useState(false)
  const [nameTick, setNameTick] = useState(0)
  const [naming, setNaming] = useState(false)
  const [siblings, setSiblings] = useState(false)
  const [tradesOpen, setTradesOpen] = useState(false)
  const seen = useSeen(svc.mode)  // 이 브라우저에서 확인한 리밸런싱 번호 (서버에는 없다)
  const pname = useResource(() => (svc.getPaperName ? svc.getPaperName(paperId) : Promise.resolve(null)), [svc, paperId, nameTick]).data  // 제안 기능: 목업에서만 값이 있다
  const allPapers = useResource(() => svc.listPaper(), [svc, nameTick]).data  // 같은 리포트의 다른 모의투자 구분
  const d = override ?? res.data
  const krwRes = useResource(() => (svc.getPaperKrw ? svc.getPaperKrw(paperId) : Promise.resolve(null)), [svc, paperId, d])  // 제안 기능: 원화 기준 성과·환율 상태 (목업에서만)
  const k = krwRes.data
  const fxDay = useMemo(() => new Map((k?.fx ?? []).map((f) => [f.date, f])), [k])
  const runId = d?.portfolio.run_id
  const partial = useResource(() => (runId ? svc.getRunPartial(runId).catch(() => null) : Promise.resolve(null)), [svc, runId])  // 회사명: 모의투자 응답에는 없고 실행의 선정 결과에 있다
  const names = useMemo(() => new Map((partial.data?.selection?.rows ?? []).filter((x) => x.name).map((x) => [x.ticker, x.name as string])), [partial.data])
  const fx = useMemo(() => (d ? fxByDate(d) : new Map<string, number>()), [d])
  useEffect(() => { if (d) initPapers(svc.mode, [d.summary], svc.seenSeed?.()) }, [svc, d])  // 처음 보는 모의투자는 지금까지의 리밸런싱을 확인한 것으로 둔다
  if (res.status === "loading" && !d) return <Loading label="모의투자를 불러오는 중…" />
  if (res.status === "error" && !d) return <EmptyState title="이 모의투자를 열 수 없습니다" description={res.error ?? ""} action={<Button onClick={() => navigate({ page: "paper" })}>목록으로</Button>} />
  if (!d) return null
  const { portfolio: p, summary: s } = d
  const cur: Cur = p.initial_capital.currency
  const act = async (what: "refresh" | "stop" | "resume") => {
    setBusy(what); setErr(null); setRefreshed(null); setAskStop(false)
    const before = d.snapshots.length
    try {
      const next = await (what === "refresh" ? svc.refreshPaper(paperId) : what === "stop" ? svc.stopPaper(paperId) : svc.resumePaper(paperId))
      setOverride(next)
      if (what === "refresh") { const n = next.snapshots.length - before; setRefreshed(n > 0 ? `새 평가 ${n}일 반영` : "추가된 평가 없음") }
    } catch (e) { setErr(errorMessage(e)) } finally { setBusy("") }
  }
  const latest = d.snapshots[d.snapshots.length - 1]
  const lastFx = latest ? fx.get(latest.date) : undefined
  const paidCount = d.snapshots.filter((x) => (x.contribution_usd ?? 0) > 0).length
  const monthly = p.contribution.monthly_amount ?? 0
  const added = cur === "USD" ? s.contributions_total_usd : paidCount * monthly  // 원화 적립은 정해진 원화 금액을 납입한 것이라 환산하지 않는다
  const tolerance = (p.constraints_snapshot.request as { risk?: { max_drawdown_tolerance?: number } } | undefined)?.risk?.max_drawdown_tolerance
  const over = tolerance != null && Math.abs(s.max_drawdown) > tolerance
  const { rows, gap } = chartRows(d)
  const events = recentEvents(d)
  const stopped = p.status === "stopped"
  const fresh = freshRebalance(d, seen.papers[paperId])  // 확인하지 않은 리밸런싱 → 거래 카드를 강조
  const showAllTrades = () => { setTradesOpen(true); requestAnimationFrame(() => document.getElementById("paper-trades")?.scrollIntoView?.({ behavior: "smooth", block: "start" })) }
  const others = samePapers(allPapers ?? [], p.report_id).filter((x) => x.paper_id !== paperId)
  const relink = async () => { setErr(null); try { await svc.setPaperName!(paperId, { mode: "linked" }); setNameTick((n) => n + 1) } catch (e) { setErr(errorMessage(e)) } }
  // 더보기: 원본 리포트 · (목업) 이름 바꾸기·다시 연동 · 같은 리포트로 시작한 다른 모의투자(목록 창)
  const menu = [
    { label: "원본 리포트 보기", icon: FileText, onClick: () => navigate({ page: "report", reportId: p.report_id }) },
    ...(pname && svc.setPaperName ? [{ label: "이름 바꾸기", icon: PencilLine, onClick: () => setNaming(true) }, ...(pname.mode === "custom" ? [{ label: "리포트 이름과 다시 연동", icon: Link2, onClick: () => void relink() }] : [])] : []),
    ...(others.length ? [{ label: `같은 리포트로 시작한 다른 모의투자 ${others.length}개`, icon: Activity, onClick: () => setSiblings(true) }] : []),
  ]
  return (
    <div className="mx-auto max-w-5xl space-y-8">
      {/* 머리말 한 묶음: 제목·설명·구분 정보(적용 전략·시작일·초기 투자금) + 오른쪽 위 버튼, 바로 아래 운용 상태 줄.
          원본 리포트·이름 바꾸기·같은 리포트의 다른 모의투자는 「더보기」 안에 있다. */}
      <div className="space-y-4">
        <FlowHeader eyebrow="모의투자" title={pname?.name_ko ?? p.name_ko}
          desc={<>원본 리포트의 전략을 {p.start_date}부터 가상 자본으로 따라갑니다. 실제 매매는 하지 않습니다.<span className="mt-1 block text-xs font-semibold text-slate-700">{paperBasis(s, pname?.name_ko ?? p.name_ko)}</span></>}
          action={<div className="flex flex-col gap-2 sm:items-end sm:pt-6"><div className="flex flex-wrap items-center gap-2">
            <span title="서버에 수집된 최근 종가 자료까지 평가를 추가합니다. 실시간 시세를 조회하지 않습니다."><Button variant="secondary" onClick={() => act("refresh")} disabled={busy !== "" || stopped}><RefreshCw className={`size-4 ${busy === "refresh" ? "animate-spin" : ""}`} />{busy === "refresh" ? "자료 확인 중…" : "최신 자료로 갱신"}</Button></span>
            {stopped ? <Button onClick={() => act("resume")} disabled={busy !== ""}><Play className="size-4" />{busy === "resume" ? "재개하는 중…" : "모의운용 재개"}</Button> : <Button variant="danger" onClick={() => setAskStop(true)} disabled={busy !== ""}><Pause className="size-4" />모의운용 중지</Button>}
            <Menu items={menu} />
          </div>
          {/* 갱신 설명은 갱신 버튼 바로 아래 */}
          <p className="max-w-xs text-xs leading-5 text-slate-500 sm:text-right">갱신은 실시간 시세가 아니라, 서버에 수집된 최근 종가 자료까지 평가를 추가합니다.</p>
          </div>} />
        <div className="flex flex-wrap items-center gap-x-2 gap-y-1.5 border-t border-slate-200 pt-4 text-xs text-slate-600">
          {runBadge(s)}{dataBadge(s)}
          <span>마지막 평가일 {s.last_date ?? "–"}</span><span>· 자료 마감 {s.data_ceiling}</span>{s.last_refresh_at && <span>· 마지막 갱신 {datetime(s.last_refresh_at)}</span>}
          {p.reconstructed_at_start && <Badge tone="amber">시작일에 비중 재계산</Badge>}
        </div>
        {refreshed && <p role="status" className="text-sm font-semibold text-slate-700">{refreshed}</p>}
      </div>
      {siblings && <SiblingPapersDialog papers={others} close={() => setSiblings(false)} />}
      {naming && pname && <PaperNameDialog paperId={paperId} name={pname} close={() => setNaming(false)} saved={() => setNameTick((n) => n + 1)} />}
      {askStop && (
        <div role="alertdialog" aria-label="모의운용 중지 확인" className="rounded-xl border border-red-200 bg-red-50 p-4 text-sm text-red-950">
          <p>보유 종목을 매도하지 않고 평가와 리밸런싱 기록을 중지합니다. 재개 시 중지 기간의 기록은 소급해서 채우지 않습니다. 중지 기간의 적립도 진행되지 않습니다.</p>
          <div className="mt-3 flex flex-wrap gap-2"><Button variant="danger" onClick={() => act("stop")} disabled={busy !== ""}>{busy === "stop" ? "중지하는 중…" : "중지 확정"}</Button><Button variant="ghost" onClick={() => setAskStop(false)}>계속 운용</Button></div>
        </div>
      )}
      {err && <Alert tone="error" title="처리하지 못했습니다">{err}</Alert>}
      {s.update_status === "delayed" && <Alert tone="warning" title="자료가 아직 없어 마지막 평가일 이후를 기록하지 못했습니다">{s.delayed_reason_ko}</Alert>}
      {stopped && <Alert tone="info" title="모의운용이 중지된 상태입니다">보유는 그대로 두고 평가와 리밸런싱을 멈췄습니다. 재개하면 중지 기간은 비워 두고 재개일부터 다시 기록합니다. 중지 중 지나간 리밸런싱은 건너뛴 것으로 남깁니다.</Alert>}

      <Part title="핵심 성과" desc={cur === "KRW" ? `금액은 원화, 수익률은 ${USD_BASIS}` : "금액과 수익률 모두 USD 기준"}>
        <div className="grid grid-cols-1 gap-5 sm:grid-cols-3">
          <Stat label="현재 평가액" value={<Money usd={s.value_usd} date={latest?.date} cur={cur} fx={fx} compact />} note={cur === "KRW" ? (lastFx && latest ? usd(s.value_usd) : "평가 기록의 환율이 없어 USD 로 표시합니다") : undefined} />
          <Stat label="운용 수익률 (납입 제외)" value={pct(s.return_since_start)} tone={s.return_since_start >= 0 ? "up" : "down"} />
          <Stat label="비교지수 대비 차이" value={s.excess_return == null ? "–" : fmt(s.excess_return, "pp")} note={`${p.benchmark} ${s.benchmark_return_since_start == null ? "–" : pct(s.benchmark_return_since_start)}`} />
        </div>
        <dl className="grid grid-cols-2 gap-4 border-t border-slate-100 pt-4 sm:grid-cols-4">
          <Small label="초기 투자금" value={inCur(p.initial_capital.amount, cur)} />
          <Small label="추가 납입금" value={added > 0 ? inCur(added, cur) : "없음"} note={added > 0 ? `${paidCount}회 납입` : undefined} />
          <Small label="총 납입금" value={inCur(p.initial_capital.amount + added, cur)} />
          <Small label="평가 기준일" value={s.last_date ?? "–"} note={`평가 ${s.days_tracked}일 · 리밸런싱 ${s.n_rebalances}회`} />
        </dl>
        <p className="text-xs leading-5 text-slate-500">납입 제외 손익 {usd(s.gain_usd)} (수수료 차감 후)</p>
      </Part>

      {k && <KrwPerformance k={k} />}

      {/* 리밸런싱 거래: 접힌 상세 기록에 숨기지 않고 성과 카드 바로 아래(위험 위)에 둔다 */}
      <RebalanceCard d={d} cur={cur} fx={fx} names={names} fresh={!!fresh} onAck={() => fresh && markRebalanceSeen(svc.mode, paperId, fresh.seq)} onAll={showAllTrades} />

      <Part title="위험" desc="운용 수익률과 같은 기준으로 계산한 낙폭입니다.">
        <dl className="grid grid-cols-2 gap-4 sm:grid-cols-3">
          <Small label="현재 낙폭" value={pct(s.drawdown)} />
          <Small label="최대 낙폭" value={<span className={over ? "text-amber-800" : ""}>{pct(s.max_drawdown)}</span>} />
          <Small label="허용 낙폭" value={tolerance != null ? weight(tolerance) : "저장된 기준 없음"} note={over ? "최대 낙폭이 허용 낙폭을 넘었습니다" : undefined} />
        </dl>
      </Part>

      <Part title={`시작 이후 수익률 (${cur === "KRW" ? USD_BASIS : "USD 기준"})`}>
        {d.series.dates.length === 0 ? <p className="rounded-xl bg-slate-50 p-4 text-sm text-slate-600">아직 평가 기록이 없습니다. 첫 평가가 기록되면 이곳에 표시됩니다.</p>
          : d.series.dates.length === 1 ? <p className="rounded-xl bg-slate-50 p-4 text-sm text-slate-600">평가 기록이 {d.series.dates[0]} 하루치입니다. 다음 거래일 자료가 들어오면 그래프가 그려집니다.</p>
          : (
            <div className="h-72">
              <ResponsiveContainer width="100%" height="100%">
                <LineChart data={rows}>
                  <CartesianGrid stroke="#e2e8f0" vertical={false} />
                  <XAxis dataKey="date" tick={{ fontSize: 11 }} minTickGap={32} />
                  <YAxis tickFormatter={(v: number) => pct(v)} tick={{ fontSize: 11 }} width={64} />
                  <Tooltip formatter={(v, n) => [typeof v === "number" ? pct(v) : "–", `${String(n)} (USD 기준)`]} />
                  <Legend formatter={(v) => `${String(v)} (USD 기준)`} />
                  <Line type="monotone" dataKey="운용수익률" name="운용 수익률" stroke={PALETTE[0]} dot={false} strokeWidth={2} isAnimationActive={false} />
                  <Line type="monotone" dataKey="비교지수수익률" name={`비교지수 ${p.benchmark} 수익률`} stroke={PALETTE[1]} dot={false} strokeDasharray="4 4" isAnimationActive={false} />
                </LineChart>
              </ResponsiveContainer>
            </div>
          )}
        {gap > 0 && <p className="text-xs text-slate-500">끊긴 구간은 모의운용을 중지한 기간입니다. 평가하지 않은 기간을 선으로 잇지 않습니다.</p>}
        <p className="text-xs text-slate-500">과거 백테스트는 이어 붙이지 않습니다. <button type="button" onClick={() => navigate({ page: "report", reportId: p.report_id, sec: "performance" })} className="font-semibold text-blue-700 hover:underline">원본 리포트의 과거 성과 보기</button></p>
      </Part>

      <Holdings d={d} names={names} />

      <Part title="최근 운용 기록">
        {events.length ? (
          <ol className="divide-y divide-slate-100">
            {events.map((e, i) => <li key={i} className="flex flex-col gap-0.5 py-2 first:pt-0 last:pb-0 sm:flex-row sm:gap-4"><span className="shrink-0 text-xs tabular-nums text-slate-500 sm:w-24 sm:pt-0.5">{e.date}</span><span className="min-w-0 text-sm"><b className={e.tone === "amber" ? "text-amber-800" : "text-slate-900"}>{e.title}</b>{e.detail && <span className="block break-words text-xs text-slate-500">{e.detail}</span>}</span></li>)}
          </ol>
        ) : <p className="text-sm text-slate-600">운용 기록이 없습니다.</p>}
      </Part>

      <div id="paper-trades" className="scroll-mt-6"><PartDisclosure title="거래·리밸런싱 상세" summary={`${d.rebalances.length}건`} open={tradesOpen} onToggle={setTradesOpen}>
        {d.rebalances.length === 0 ? <p className="text-sm text-slate-600">기록이 없습니다.</p> : (
          <div className="overflow-x-auto">
            <table className="w-full min-w-[640px] text-sm">
              <thead className="text-left text-xs font-semibold text-slate-500"><tr><th className="py-1.5">날짜</th><th className="py-1.5">종류</th><th className="py-1.5 text-right">거래 수</th><th className="py-1.5 text-right">수수료 ({cur === "KRW" ? "원" : "USD"})</th><th className="py-1.5 text-right">회전율</th><th className="py-1.5 pl-3">내용</th></tr></thead>
              <tbody>
                {[...d.rebalances].reverse().map((r, i) => (
                  <tr key={i} className="border-t border-slate-100 align-top">
                    <td className="whitespace-nowrap py-1.5">{r.date}</td><td className="py-1.5">{kindText(r)}</td><td className="py-1.5 text-right">{r.trades.length}</td>
                    <td className="py-1.5 text-right">{r.skipped ? "–" : <Money usd={r.commission_usd} date={r.date} cur={cur} fx={fx} />}</td><td className="py-1.5 text-right">{weight(r.turnover)}</td>
                    <td className="py-1.5 pl-3 text-xs text-slate-600">{r.note_ko}{r.trades.length > 0 && <ul className="mt-1 space-y-0.5">{r.trades.map((t, k) => <li key={k}>{t.ticker} {t.side === "buy" ? "매수" : "매도"} <Money usd={t.value_usd} date={r.date} cur={cur} fx={fx} /> ({fmt(t.shares, "num")}주 × {fmt(t.price, "usd")})</li>)}</ul>}{r.views && r.views.length > 0 && <div className="mt-1">뉴스 뷰 {r.views.length}개{r.evidence_window ? ` · 기사 ${r.evidence_window.n_articles}건 (${r.evidence_window.start}~${r.evidence_window.end})` : ""}</div>}{(r.warnings ?? []).map((w, k) => <div key={k} className="text-amber-700">{w}</div>)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </PartDisclosure></div>

      <PartDisclosure title="일별 평가 기록" summary={`${d.snapshots.length}일`}>
        {d.snapshots.length === 0 ? <p className="text-sm text-slate-600">기록이 없습니다.</p> : (
          <div className="max-h-96 overflow-auto">
            <table className="w-full min-w-[720px] text-sm">
              <thead className="sticky top-0 bg-white text-left text-xs font-semibold text-slate-500"><tr><th className="py-1.5">날짜</th><th className="py-1.5 text-right">평가액</th><th className="py-1.5 text-right">현금</th><th className="py-1.5 text-right">적립</th>{cur === "KRW" && <th className="py-1.5 text-right">환율 (KRW/USD){k && <MockTag />}</th>}<th className="py-1.5 text-right">운용 수익률</th><th className="py-1.5 text-right">비교지수</th><th className="py-1.5 text-right">낙폭</th></tr></thead>
              <tbody>
                {[...d.snapshots].reverse().map((x) => (
                  <tr key={x.date} className="border-t border-slate-100"><td className="whitespace-nowrap py-1.5">{x.date}</td><td className="py-1.5 text-right"><Money usd={x.value_usd} date={x.date} cur={cur} fx={fx} /></td><td className="py-1.5 text-right"><Money usd={x.cash_usd} date={x.date} cur={cur} fx={fx} /></td><td className="py-1.5 text-right">{x.contribution_usd ? <Money usd={x.contribution_usd} date={x.date} cur={cur} fx={fx} /> : "–"}</td>{cur === "KRW" && <td className="py-1.5 text-right tabular-nums">{x.fx_rate ? x.fx_rate.toLocaleString("ko-KR", { maximumFractionDigits: 2 }) : "없음"}{fxDay.get(x.date) && fxDay.get(x.date)!.status !== "ok" && <span className="block text-[11px]"><FxStatus f={fxDay.get(x.date)!} short /></span>}</td>}<td className="py-1.5 text-right">{pct(x.return_since_start)}</td><td className="py-1.5 text-right">{x.benchmark_return_since_start == null ? "–" : pct(x.benchmark_return_since_start)}</td><td className="py-1.5 text-right">{pct(x.drawdown)}</td></tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </PartDisclosure>

      <PartDisclosure title="운용 규칙"><Rules p={p} /></PartDisclosure>
      <PartDisclosure title="이벤트 이력" summary={`${p.history.length}건`}>
        {p.history.length ? <ul className="space-y-1 text-xs text-slate-600">{p.history.map((h, i) => <li key={i}>{datetime(h.at)} · {ko(h.event)}{h.note ? ` — ${h.note}` : ""}</li>)}</ul> : <p className="text-sm text-slate-600">기록이 없습니다.</p>}
      </PartDisclosure>
      <p className="text-xs text-slate-400">모의투자 번호 {p.paper_id}</p>
    </div>
  )
}
