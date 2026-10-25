import { useMemo } from "react"
import { Activity, PencilLine, RefreshCw } from "lucide-react"
import { Cell, Line, LineChart, Pie, PieChart, ResponsiveContainer, Tooltip, XAxis, YAxis } from "recharts"
import type { ReportDoc, ReportSummary } from "../../api/types"
import { colorOf, fmt, OTHER_COLOR } from "../../lib/format"
import { Badge, Button } from "../../ui"
import { CitedText } from "./blocks/blocks"

const TONE: Record<ReportSummary["verdict"]["status"], { badge: "green" | "amber" | "slate"; box: string }> = {
  recommended: { badge: "green", box: "border-emerald-200 bg-emerald-50/60" }, recommended_warn: { badge: "amber", box: "border-amber-200 bg-amber-50/60" },
  insufficient: { badge: "slate", box: "border-slate-300 bg-slate-50" },
  none_cash_blend: { badge: "slate", box: "border-slate-200 bg-slate-50" }, none_baseline: { badge: "slate", box: "border-slate-200 bg-slate-50" },
}
const TOP = 8

/** "한눈에 보기": 판단 · KPI(비교지수 동반) · 배분 · 누적 수익률 미니 · 검증 · 다음에 할 일. 문서의 summary 를 그린다 (계산은 서버). */
export function Dashboard({ summary: sm, doc, onRerun, onRevise, onPaper, onJump, busy, paperReason }: { summary: ReportSummary; doc: ReportDoc; onRerun: () => void; onRevise: () => void; onPaper: () => void; onJump: (sec: string) => void; busy?: string; paperReason?: string | null }) {
  const tone = TONE[sm.verdict.status] ?? TONE.none_baseline
  const years = sm.period?.start && sm.period?.end ? Math.round(((new Date(sm.period.end).getTime() - new Date(sm.period.start).getTime()) / 31557600000) * 10) / 10 : null
  return (
    <section aria-label="한눈에 보기" className="space-y-4">
      <div className={`rounded-2xl border p-5 ${tone.box}`}>
        <div className="flex flex-wrap items-center gap-2"><Badge tone={tone.badge}>{sm.verdict.label_ko}</Badge><span className="text-xs text-slate-500">백테스트 {sm.period?.start ?? doc.header.backtest_period.start} ~ {sm.period?.end ?? doc.header.backtest_period.end}{years !== null ? ` (${years}년` : ""}{sm.period?.trading_days ? `${years !== null ? " · " : " ("}${sm.period.trading_days}거래일)` : years !== null ? ")" : ""}</span></div>
        <p className="mt-3 text-lg font-semibold leading-7 text-slate-900"><CitedText text={sm.verdict.headline_ko || doc.header.chosen_note_ko} /></p>
        {sm.verdict.reason_ko && <p className="mt-1 text-sm leading-6 text-slate-600"><CitedText text={sm.verdict.reason_ko} /></p>}
        {sm.verdict.period_note_ko && <p className="mt-2 rounded-lg bg-amber-100/70 px-3 py-1.5 text-sm text-amber-900" role="note">⚠ {sm.verdict.period_note_ko}</p>}
        {(sm.verdict.notices_ko?.length ?? 0) > 0 && (
          <div className="mt-2 rounded-lg bg-white/70 px-3 py-2 text-sm text-slate-700">
            <p className="text-xs font-semibold text-slate-500">분석 중 확인한 점 {sm.verdict.n_notices ?? sm.verdict.notices_ko!.length}건</p>
            <ul className="mt-1 list-disc space-y-0.5 pl-5">{sm.verdict.notices_ko!.map((n, i) => <li key={i}>{n}</li>)}</ul>
            <button type="button" onClick={() => onJump("assumptions")} className="mt-1 text-xs font-semibold text-blue-700 hover:underline">전제와 재검토 조건에서 자세히</button>
          </div>
        )}
        <div className="mt-4 flex flex-wrap gap-2">
          <span title={paperReason ?? undefined}><Button onClick={onPaper} disabled={!doc.tracking.eligible}><Activity className="size-4" />모의투자 시작</Button></span>
          <Button variant="secondary" onClick={onRevise}><PencilLine className="size-4" />조건 수정 요청</Button>
          <Button variant="secondary" onClick={onRerun} disabled={busy === "rerun"}><RefreshCw className="size-4" />조건 확인 후 다시 분석</Button>
        </div>
        {paperReason && !doc.tracking.eligible && <p className="mt-2 text-xs text-slate-500">모의투자 시작 불가: {paperReason}</p>}
      </div>
      <KpiRow kpis={sm.kpis} />
      <div className="grid grid-cols-3 gap-4">
        {sm.allocation ? <AllocationMini a={sm.allocation} onMore={() => onJump("construction")} /> : <div className="rounded-xl border border-slate-200 bg-white p-4 text-sm text-slate-500">배분 정보가 없습니다.</div>}
        <ReturnMini doc={doc} ids={sm.mini_series?.ids ?? [doc.header.chosen_portfolio_id]} onMore={() => onJump("performance")} />
        <ValidationMini v={sm.validation} onMore={() => onJump("performance")} />
      </div>
      {sm.news_effect && <NewsEffectMini n={sm.news_effect} onMore={() => onJump("construction")} />}
      {sm.next_actions_ko.length > 0 && (
        <div className="rounded-xl border border-slate-200 bg-white p-4">
          <h3 className="text-sm font-semibold text-slate-900">다음에 할 수 있는 일</h3>
          <ul className="mt-2 grid grid-cols-2 gap-x-6 gap-y-1 text-sm leading-6 text-slate-700">{sm.next_actions_ko.map((t, i) => <li key={i} className="flex gap-2"><span className="text-slate-400">{i + 1}.</span><span><CitedText text={t} /></span></li>)}</ul>
        </div>
      )}
    </section>
  )
}

/** 뉴스 반영 효과 (라운드 5): 뉴스 반영 구성 vs 같은 종목의 기준 비중 — 추천이 다른 포트폴리오여도 보여 준다. */
export function NewsEffectMini({ n, onMore }: { n: NonNullable<ReportSummary["news_effect"]>; onMore: () => void }) {
  if (n.disabled) return <div className="rounded-xl border border-slate-200 bg-white px-4 py-3 text-xs text-slate-500">뉴스 반영 효과: {n.reason_ko ?? "표시할 수 없습니다"}</div>
  const sign = (v: number | null | undefined) => (v == null ? "–" : fmt(v, "pp"))
  const retKo = n.annualized_reliable === false ? "CAGR(연환산, 참고)" : "CAGR"
  return (
    <div className="rounded-xl border border-slate-200 bg-white p-4">
      <div className="flex items-start justify-between"><h3 className="text-sm font-semibold text-slate-900">뉴스 반영 효과</h3><button type="button" onClick={onMore} className="text-xs font-semibold text-blue-700 hover:underline">자세히</button></div>
      <p className="mt-0.5 text-[11px] text-slate-500">{n.bl_label_ko ?? "뉴스 반영 구성"} vs {n.base_label_ko ?? "기준 비중"} (같은 종목, 같은 기간)</p>
      <dl className="mt-2 grid grid-cols-5 gap-3 text-xs">
        <div><dt className="text-slate-500">{retKo} 차이</dt><dd className={`mt-0.5 text-base font-semibold tabular-nums ${(n.diff_cagr ?? 0) >= 0 ? "text-emerald-700" : "text-red-700"}`}>{n.diff_cagr == null ? "–" : fmt(n.diff_cagr, "pp")}</dd><dd className="text-[11px] text-slate-500">{fmt(n.bl_cagr, "pct")} vs {fmt(n.base_cagr, "pct")}</dd></div>
        <div><dt className="text-slate-500">최대낙폭</dt><dd className="mt-0.5 text-base font-semibold tabular-nums">{fmt(n.bl_mdd, "pct")}</dd><dd className="text-[11px] text-slate-500">기준 {fmt(n.base_mdd, "pct")}</dd></div>
        <div><dt className="text-slate-500">뷰 적중률 (다음 리밸런싱까지)</dt><dd className="mt-0.5 text-base font-semibold tabular-nums">{n.hit_next_rb == null ? "–" : fmt(n.hit_next_rb, "pct1")}</dd><dd className="text-[11px] text-slate-500">뷰로 비중을 바꾼 기간 안에서</dd></div>
        <div><dt className="text-slate-500">뷰 적중률 (12개월)</dt><dd className="mt-0.5 text-base font-semibold tabular-nums">{n.hit_365 == null ? "–" : fmt(n.hit_365, "pct1")}</dd><dd className="text-[11px] text-slate-500">구성 뒤 12개월 기준</dd></div>
        <div><dt className="text-slate-500">뷰 수</dt><dd className="mt-0.5 text-base font-semibold tabular-nums">{n.n_views ?? 0}</dd><dd className="text-[11px] text-slate-500">리밸런싱 {n.n_rebalances ?? 0}회 중 뉴스 적용 {n.n_dates ?? 0}회{n.n_fallback ? ` · 기준 비중 유지 ${n.n_fallback}회` : ""}</dd></div>
      </dl>
      <p className="mt-2 text-[11px] text-slate-400">비교지수 대비: 뉴스 반영 {sign(n.bl_excess_cagr)} · 기준 비중 {sign(n.base_excess_cagr)}. 뉴스가 성과의 원인이라고 단정할 수 없습니다.</p>
    </div>
  )
}

export function KpiRow({ kpis }: { kpis: ReportSummary["kpis"] }) {
  return (
    <div className="grid gap-3" style={{ gridTemplateColumns: `repeat(${Math.min(6, Math.max(1, kpis.length))}, minmax(0, 1fr))` }}>
      {kpis.map((k) => (
        <div key={k.id} className="rounded-xl border border-slate-200 bg-white p-4">
          <div className="text-xs font-medium text-slate-500">{k.label_ko}</div>
          <div className="mt-1 text-2xl font-semibold tabular-nums text-slate-900">{fmt(k.value, k.format)}</div>
          {k.benchmark_value !== undefined && k.benchmark_value !== null && <div className="mt-1 text-xs text-slate-500">{k.benchmark_label_ko ?? "비교지수"} {fmt(k.benchmark_value, k.format)}</div>}
          {k.note_ko && <div className="mt-1 text-[11px] leading-4 text-slate-500">{k.note_ko}</div>}
        </div>
      ))}
    </div>
  )
}

/** 도넛(상위 8 + 기타) + 표. 색은 티커 고정. */
export function AllocationMini({ a, onMore }: { a: NonNullable<ReportSummary["allocation"]>; onMore: () => void }) {
  const { data, order } = useMemo(() => {
    const sorted = [...a.items].sort((x, y) => y.weight - x.weight)
    const top = sorted.slice(0, TOP)
    const rest = sorted.slice(TOP)
    const order = top.map((x) => x.ticker)
    const data = top.map((x) => ({ label: x.ticker, value: x.weight }))
    if (rest.length) data.push({ label: `기타 ${rest.length}종목`, value: rest.reduce((s, x) => s + x.weight, 0) })
    if (a.cash_weight > 1e-6) data.push({ label: "현금", value: a.cash_weight })
    return { data, order }
  }, [a])
  return (
    <div className="rounded-xl border border-slate-200 bg-white p-4">
      <div className="flex items-start justify-between"><h3 className="text-sm font-semibold text-slate-900">배분 비중</h3><button type="button" onClick={onMore} className="text-xs font-semibold text-blue-700 hover:underline">자세히</button></div>
      <p className="mt-0.5 text-[11px] text-slate-500">{a.basis_ko}{a.initial_amount_usd ? ` · ${fmt(a.initial_amount_usd, "usd")}` : ""}</p>
      <div className="mt-2 flex items-center gap-3">
        <div className="h-28 w-28 shrink-0" role="img" aria-label="배분 비중 도넛">
          <ResponsiveContainer width="100%" height="100%"><PieChart><Pie data={data} dataKey="value" nameKey="label" innerRadius={34} outerRadius={54} paddingAngle={1} isAnimationActive={false}>{data.map((d) => <Cell key={d.label} fill={d.label.startsWith("기타") || d.label === "현금" ? OTHER_COLOR : colorOf(d.label, order)} />)}</Pie><Tooltip formatter={(v: unknown) => fmt(v as number, "pct1")} /></PieChart></ResponsiveContainer>
        </div>
        <table className="min-w-0 flex-1 text-xs"><tbody>
          {data.map((d) => <tr key={d.label}><td className="py-0.5 pr-1"><span className="inline-block size-2.5 rounded-sm" style={{ background: d.label.startsWith("기타") || d.label === "현금" ? OTHER_COLOR : colorOf(d.label, order) }} /></td><td className="truncate py-0.5 pr-2 font-medium text-slate-700">{d.label}</td><td className="py-0.5 text-right tabular-nums">{fmt(d.value, "pct1")}</td></tr>)}
        </tbody></table>
      </div>
    </div>
  )
}

export function ReturnMini({ doc, ids, onMore }: { doc: ReportDoc; ids: string[]; onMore: () => void }) {
  const rows = useMemo(() => doc.datasets.dates.map((d, i) => { const r: Record<string, number | string> = { date: d }; for (const id of ids) { const v = doc.datasets.series[id]?.index?.[i]; if (typeof v === "number") r[id] = v } return r }), [doc, ids])
  const last = rows[rows.length - 1] ?? {}
  return (
    <div className="rounded-xl border border-slate-200 bg-white p-4">
      <div className="flex items-start justify-between"><h3 className="text-sm font-semibold text-slate-900">누적 수익률 (시작 = 100)</h3><button type="button" onClick={onMore} className="text-xs font-semibold text-blue-700 hover:underline">자세히</button></div>
      <div className="mt-2 h-28" role="img" aria-label="누적 수익률 미니 차트">
        <ResponsiveContainer width="100%" height="100%"><LineChart data={rows}><XAxis dataKey="date" hide /><YAxis hide domain={["auto", "auto"]} /><Tooltip formatter={(v: unknown, n: unknown) => [fmt(v as number, "index"), doc.datasets.series[String(n)]?.label_ko ?? String(n)]} labelFormatter={(l) => String(l)} />
          {ids.map((id) => <Line key={id} type="monotone" dataKey={id} stroke={colorOf(id, ids)} dot={false} strokeWidth={id === doc.header.chosen_portfolio_id ? 2.5 : 1.5} isAnimationActive={false} />)}</LineChart></ResponsiveContainer>
      </div>
      <ul className="mt-1 space-y-0.5 text-xs text-slate-600">{ids.map((id) => <li key={id} className="flex items-center gap-2"><span className="inline-block size-2.5 rounded-full" style={{ background: colorOf(id, ids) }} /><span className="truncate">{doc.datasets.series[id]?.label_ko ?? id}</span><b className="ml-auto tabular-nums">{fmt(last[id] as number, "index")}</b></li>)}</ul>
    </div>
  )
}

const RULE_TONE: Record<string, "green" | "amber" | "red" | "slate"> = { pass: "green", warn: "amber", fail: "red", info: "slate", flag: "amber" }
const RULE_STATUS_KO: Record<string, string> = { pass: "통과", warn: "주의", fail: "미통과", info: "참고", flag: "허용 초과" }
const LEVEL_KO: Record<string, string> = { hard: "필수", flag: "표시" }

/** 선택안의 사용자 기준 4개(최대낙폭·목표수익·비교지수·변동성)를 한 줄씩 보여 준다. 내부 점검(상한·무결성)은 여기 없다. */
export function ValidationMini({ v, onMore }: { v: ReportSummary["validation"]; onMore: () => void }) {
  const rules = v.rules_ko ?? []
  return (
    <div className="rounded-xl border border-slate-200 bg-white p-4">
      <div className="flex items-start justify-between"><h3 className="text-sm font-semibold text-slate-900">내 조건과 맞나</h3><button type="button" onClick={onMore} className="text-xs font-semibold text-blue-700 hover:underline">자세히</button></div>
      {rules.length > 0 ? (
        <ul className="mt-2 space-y-1.5">
          {rules.map((r) => (
            <li key={r.rule} className="flex items-start gap-2 text-xs leading-5">
              <Badge tone={RULE_TONE[r.status] ?? "slate"}>{RULE_STATUS_KO[r.status] ?? r.status}</Badge>
              <span className="min-w-0"><span className="font-semibold text-slate-800">{r.name_ko}</span>{LEVEL_KO[r.level] && <span className="ml-1 text-[10px] text-slate-400">{LEVEL_KO[r.level]}</span>}<span className="block text-slate-600">{r.message_ko}</span></span>
            </li>
          ))}
        </ul>
      ) : (
        <>
          <div className="mt-2 flex gap-2 text-xs"><Badge tone="green">통과 {v.n_pass}</Badge><Badge tone="amber">주의 {v.n_warn}</Badge><Badge tone="red">미통과 {v.n_fail}</Badge></div>
          {v.failed_rules_ko.length > 0 && <div className="mt-2"><p className="text-xs font-semibold text-red-700">미통과 규칙</p><ul className="mt-1 list-disc pl-4 text-xs leading-5 text-slate-700">{v.failed_rules_ko.map((r) => <li key={r}>{r}</li>)}</ul></div>}
          {(v.warned_rules_ko?.length ?? 0) > 0 && <div className="mt-2"><p className="text-xs font-semibold text-amber-700">주의 규칙</p><ul className="mt-1 list-disc pl-4 text-xs leading-5 text-slate-700">{v.warned_rules_ko!.map((r) => <li key={r}>{r}</li>)}</ul></div>}
        </>
      )}
      {v.r1 && (
        <div className="mt-2 grid grid-cols-3 gap-2 rounded-lg bg-slate-50 p-2 text-center text-[11px]" aria-label="최대낙폭 비교">
          <div><p className="text-slate-500">실현 최대낙폭</p><p className={`font-semibold tabular-nums ${v.r1.status === "flag" ? "text-amber-700" : "text-slate-800"}`}>{fmt(-Math.abs(v.r1.mdd), "pct")}</p></div>
          <div><p className="text-slate-500">허용 낙폭</p><p className="font-semibold tabular-nums text-slate-800">{fmt(v.r1.tolerance, "pct1")}</p></div>
          <div><p className="text-slate-500">비교지수 낙폭</p><p className="font-semibold tabular-nums text-slate-800">{fmt(-Math.abs(v.r1.benchmark_mdd), "pct")}</p></div>
        </div>
      )}
      {(v.info_notes_ko?.length ?? 0) > 0 && <div className="mt-2 rounded-lg bg-slate-50 p-2"><p className="text-[11px] font-semibold text-slate-500">참고</p><ul className="mt-0.5 list-disc pl-4 text-[11px] leading-4 text-slate-600">{v.info_notes_ko!.map((t, i) => <li key={i}>{t}</li>)}</ul></div>}
      <p className="mt-2 text-[11px] text-slate-400">{rules.length > 0 ? `후보 ${v.n_candidates ?? v.n_pass + v.n_warn + v.n_fail}개 비교 · 추천 1개 (순위: 목표수익 → 비교지수 → 허용 낙폭 초과 폭 → Sharpe)` : `포트폴리오 ${v.n_pass + v.n_warn + v.n_fail}개 중 통과 ${v.n_pass} · 주의 ${v.n_warn} · 미통과 ${v.n_fail}`}{v.tolerance_note_ko ? ` · ${v.tolerance_note_ko}` : ""}</p>
    </div>
  )
}
