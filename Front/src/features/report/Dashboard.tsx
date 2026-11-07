import { useMemo, useState } from "react"
import { AlertTriangle, CheckCircle2, ChevronDown, ChevronRight, Info, MinusCircle, XCircle } from "lucide-react"
import { Line, LineChart, ResponsiveContainer, Tooltip, XAxis, YAxis } from "recharts"
import type { ReportDoc, ReportSummary, SummaryKpi } from "../../api/types"
import { colorOf, fmt, OTHER_COLOR } from "../../lib/format"
import { Disclosure } from "../../ui"
import { money } from "../profile/format"
import { CitedText } from "./blocks/blocks"
import { holdingColor } from "./colors"
import { benchOf, checkOf, kpiDisplay, MockTag, nameOf, proposed, strategyInfoOf, toleranceExtraOf, volFromStructured } from "./proposedView"
import { DEFAULT_VOL_PREF, prefTerms, VOL_PREF_LABEL } from "../../lib/tendency"
import { HelpTip, Term } from "./terms"
import { analysisRisk, parseVolCheck, volObserved, type VolCheck, annualizedFromNote, r1Text, benchName, excessSentence, isShortWindow, kpiNote, minAnnualize, pairCagr, periodOf, pickSentence, shortWindowNote } from "./wording"

// 「투자 결과 요약」: 처음 보는 4개 카드 (결과 → 종목별 금액 → 과거 성과 → 내 조건). 숫자·판정은 서버 summary 그대로이고, 여기서는 보여 주는 방식만 정한다.

type Tone = "green" | "amber" | "red" | "slate"
const TONE_BOX: Record<Tone, string> = { green: "border-emerald-200 bg-emerald-50/70 text-emerald-900", amber: "border-amber-200 bg-amber-50/70 text-amber-950", red: "border-red-200 bg-red-50/70 text-red-950", slate: "border-slate-300 bg-slate-50 text-slate-900" }
const TONE_PILL: Record<Tone, string> = { green: "border-emerald-200 bg-emerald-50 text-emerald-800", amber: "border-amber-300 bg-amber-50 text-amber-900", red: "border-red-200 bg-red-50 text-red-800", slate: "border-slate-200 bg-slate-50 text-slate-700" }
const TONE_ICON: Record<Tone, React.ElementType> = { green: CheckCircle2, amber: AlertTriangle, red: XCircle, slate: MinusCircle }
const VERDICT_TONE: Record<ReportSummary["verdict"]["status"], Tone> = { recommended: "green", recommended_warn: "amber", insufficient: "amber", none_cash_blend: "slate", none_baseline: "slate" }

/** 상태 표시: 색과 아이콘에 글자를 함께 둔다 (색만으로 구분하지 않는다). */
export function StatusPill({ tone, children }: { tone: Tone; children: React.ReactNode }) {
  const Icon = TONE_ICON[tone]
  return <span className={`inline-flex shrink-0 items-center gap-1 rounded-full border px-2 py-0.5 text-xs font-semibold ${TONE_PILL[tone]}`}><Icon className="size-3.5" aria-hidden />{children}</span>
}

/** 요약 카드 틀: 질문형 제목 + 상세로 가는 링크. 내 투자조건 화면의 파트 카드와 같은 모양. */
function ResultCard({ id, q, desc, more, body = "space-y-4", children }: { id: string; q: string; desc?: React.ReactNode; more?: [string, () => void]; body?: string; children: React.ReactNode }) {
  return (
    <section aria-labelledby={id} className="flex min-w-0 flex-col rounded-2xl border border-slate-300 bg-white shadow-sm">
      <header className="flex flex-wrap items-start justify-between gap-x-4 gap-y-1.5 rounded-t-2xl border-b border-slate-200 bg-slate-50 px-5 py-4 sm:px-6">
        <h3 id={id} className="min-w-0 flex-[1_1_15rem] text-base font-bold text-slate-950">{q}</h3>
        {more && <MoreLink label={more[0]} onClick={more[1]} />}
        {desc && <p className="w-full text-xs leading-5 text-slate-600">{desc}</p>}
      </header>
      <div className={`flex-1 p-5 sm:p-6 ${body}`}>{children}</div>
    </section>
  )
}

export function MoreLink({ label, onClick }: { label: string; onClick: () => void }) {
  return <button type="button" onClick={onClick} className="inline-flex shrink-0 items-center gap-0.5 rounded-md text-xs font-semibold text-blue-700 hover:underline focus:outline-none focus:ring-2 focus:ring-blue-500">{label}<ChevronRight className="size-3.5" aria-hidden /></button>
}

const RULE_STATUS: Record<string, [Tone, string]> = { pass: ["green", "충족"], warn: ["amber", "주의"], fail: ["red", "미충족"], flag: ["amber", "허용 초과"], info: ["slate", "참고"] }
const ruleStatus = (s: string): [Tone, string] => RULE_STATUS[s] ?? ["slate", s]

export interface KeyAlert { tone: Tone; tag: string; text: string }
/** 기본 화면에 꼭 보여야 하는 미충족·주의 사항. 서버 판정(rules_ko·failed/warned·cautions·period_note)만 모은다. */
export function keyAlerts(sm: ReportSummary): KeyAlert[] {
  const v = sm.validation
  const out: KeyAlert[] = []
  if (sm.verdict.period_note_ko) out.push({ tone: "amber", tag: "기간 안내", text: sm.verdict.period_note_ko })
  for (const c of sm.verdict.cautions_ko ?? []) out.push({ tone: "amber", tag: "주의", text: c })
  const rules = v.rules_ko ?? []
  for (const r of rules) if (r.status === "fail" || r.status === "warn" || r.status === "flag") { const [tone, tag] = ruleStatus(r.status); const vc = r.rule === "R7" ? parseVolCheck(r.message_ko) : null; out.push({ tone, tag, text: `${r.name_ko}: ${vc ? volSummary(vc) : prefTerms(r.message_ko)}` }) }
  const named = new Set(rules.map((r) => r.name_ko))
  for (const r of v.failed_rules_ko) if (!named.has(r)) out.push({ tone: "red", tag: "미충족", text: r })
  for (const r of v.warned_rules_ko ?? []) if (!named.has(r)) out.push({ tone: "amber", tag: "주의", text: r })
  return out
}

export function AlertList({ items, label = "중요한 주의 사항" }: { items: KeyAlert[]; label?: string }) {
  if (!items.length) return null
  return (
    <ul aria-label={label} className="space-y-2">
      {items.map((a, i) => <li key={i} className={`flex flex-col gap-1.5 rounded-xl border px-3 py-2.5 text-sm leading-6 sm:flex-row sm:items-start sm:gap-3 ${TONE_BOX[a.tone]}`}><StatusPill tone={a.tone}>{a.tag}</StatusPill><span className="min-w-0 break-words"><CitedText text={a.text} /></span></li>)}
    </ul>
  )
}

const yearsOf = (p?: { start: string; end: string } | null) => (p?.start && p?.end ? Math.round(((new Date(p.end).getTime() - new Date(p.start).getTime()) / 31557600000) * 10) / 10 : null)

/** 투자 결과 요약 (4개 카드). 카드마다 관련 상세 섹션으로 가는 링크가 있다. */
export function Dashboard({ summary: sm, doc, onJump, paperReason }: { summary: ReportSummary; doc: ReportDoc; onJump: (sec: string, anchor?: string) => void; paperReason?: string | null }) {
  return (
    <section aria-labelledby="h-summary" className="space-y-4">
      <div><h2 id="h-summary" className="text-xl font-bold text-slate-950">투자 결과 요약</h2><p className="mt-1 text-sm text-slate-600">먼저 결과, 종목별 투자 금액, 과거 성과, 내 조건 충족 여부를 확인하세요. 근거와 계산 과정은 아래 「자세한 분석 보기」에 있습니다.</p></div>
      <VerdictCard sm={sm} doc={doc} onMore={() => onJump("verdict")} paperReason={paperReason} />
      {sm.allocation ? <AllocationCard a={sm.allocation} doc={doc} onMore={() => onJump("construction")} /> : (
        <ResultCard id="q-alloc" q="어떤 주식에 얼마를 투자하면 될까요?" more={["구성 자세히 보기", () => onJump("construction")]}><p className="text-sm text-slate-600">이 리포트에는 종목별 배분 금액 정보가 없습니다. 비중은 상세 분석의 구성 부분에서 확인할 수 있습니다.</p></ResultCard>
      )}
      <div className="grid grid-cols-1 gap-4 lg:grid-cols-2">
        <PastCard sm={sm} doc={doc} onMore={() => onJump("performance")} />
        <ConditionCard sm={sm} doc={doc} onMore={() => onJump("performance", "perf-validation")} />
      </div>
    </section>
  )
}

/** 카드 1: 이번 투자 전략은 어떤 결과인가요? 결론·선택 전략·기준일과 중요한 미충족·주의 사항. */
export function VerdictCard({ sm, doc, onMore, paperReason }: { sm: ReportSummary; doc: ReportDoc; onMore: () => void; paperReason?: string | null }) {
  const tone = VERDICT_TONE[sm.verdict.status] ?? "slate"
  const Icon = TONE_ICON[tone]
  const h = doc.header
  const period = sm.period ?? h.backtest_period
  const years = yearsOf(period)
  const win = periodOf(doc).window_days
  const alerts = keyAlerts(sm)
  const chosenId = sm.verdict.chosen_portfolio_id || h.chosen_portfolio_id
  const info = strategyInfoOf(doc, chosenId)
  const chosenName = sm.verdict.chosen_label_ko || h.chosen_label_ko
  const notices = sm.verdict.notices_ko ?? []
  return (
    <ResultCard id="q-verdict" q="이번 투자 전략은 어떤 결과인가요?" more={["판단 근거 자세히 보기", onMore]}>
      <div className={`rounded-xl border p-4 sm:p-5 ${TONE_BOX[tone]}`}>
        <p className="flex items-start gap-2 text-sm font-bold"><Icon className="mt-0.5 size-4 shrink-0" aria-hidden /><span className="min-w-0 break-words">{sm.verdict.label_ko}</span></p>
        <p className="mt-2 text-lg font-semibold leading-7 text-slate-950"><CitedText text={sm.verdict.headline_ko || h.chosen_note_ko} /></p>
      </div>
      <dl className="grid grid-cols-1 gap-x-6 gap-y-3 text-sm sm:grid-cols-2">
        <div className="min-w-0 sm:col-span-2">
          <dt className="text-xs font-semibold text-slate-500">선택된 전략</dt>
          <dd className="mt-0.5 flex items-start gap-1 font-semibold text-slate-900"><span className="min-w-0">{chosenName}</span>{info && <HelpTip label={chosenName}>{info.help}</HelpTip>}</dd>
          {info && <dd className="mt-0.5 text-xs leading-5 text-slate-600">{info.short}{proposed(doc)?.explanations?.strategies?.[chosenId ?? ""] && <MockTag />}</dd>}
        </div>
        <div><dt className="text-xs font-semibold text-slate-500">분석 기준일</dt><dd className="mt-0.5 tabular-nums text-slate-900">{h.data_as_of}</dd></div>
        <div><dt className="text-xs font-semibold text-slate-500">과거 성과 계산 기간 (백테스트)</dt><dd className="mt-0.5 tabular-nums text-slate-900">{period.start} ~ {period.end}<span className="block text-xs text-slate-500">{years !== null ? `약 ${years}년` : ""}{period.trading_days ? ` · ${period.trading_days}거래일` : ""}{win && win !== period.trading_days ? ` (수익률 계산 구간 ${win}거래일)` : ""}</span></dd></div>
      </dl>
      {alerts.length > 0 ? <div><p className="mb-2 text-xs font-semibold text-slate-500">꼭 확인할 점 {alerts.length}건</p><AlertList items={alerts} /></div>
        : <p className="text-xs text-slate-500">조건 검증에서 미충족·주의로 표시된 항목은 없습니다.</p>}
      {notices.length > 0 && (
        <Disclosure size="sm" title={`분석 중 확인한 점 ${sm.verdict.n_notices ?? notices.length}건`}>
          <ul className="list-disc space-y-0.5 pl-5 text-sm leading-6 text-slate-700">{notices.map((n, i) => <li key={i}>{n}</li>)}</ul>
        </Disclosure>
      )}
      {paperReason && !doc.tracking.eligible && <p className="text-xs text-slate-500">모의투자 시작 불가: {paperReason}</p>}
    </ResultCard>
  )
}

/** 투자 기준금액: 구조화 값(제안 계약)이 있으면 그것, 없으면 서버 「요청 내용」 표의 투자금 원문 앞부분 ("20,000,000원 → …" 의 "20,000,000원"). 없으면 null. */
export function requestedAmount(doc?: ReportDoc): string | null {
  const ra = proposed(doc)?.structured?.requested_amount
  if (ra) return ra.currency === "KRW" ? `${ra.amount.toLocaleString("en-US")}원` : `${ra.amount.toLocaleString("en-US")}USD`
  for (const s of doc?.sections ?? []) for (const b of s.blocks) {
    if (b.type !== "table" || b.title_ko !== "요청 내용") continue
    const v = b.rows.find((r) => r.k === "투자금")?.v
    if (typeof v === "string" && v) return v.split(" → ")[0].trim()
  }
  return null
}

const TOP_N = 8

/** 카드 2: 어떤 주식에 얼마를 투자하면 될까요? 서버 배분 표의 종목별 금액을 먼저, 비중은 보조로.
 *  서버는 매수 수량·수수료·잔여 현금·현금 금액을 주지 않아 계산하지 않는다. 보여 주는 구성은 서버 배분 하나(분석 기준일 「현재 구성」)뿐이다 —
 *  여러 구성을 고르는 버튼은 헷갈려서 두지 않는다. 제안 계약(proposed)에 현금 금액·예상 매수 주문이 있으면(지금은 목업만) 함께 보여 준다. */
export function AllocationCard({ a, doc, onMore }: { a: NonNullable<ReportSummary["allocation"]>; doc?: ReportDoc; onMore: () => void }) {
  const p = proposed(doc)
  const bases = p?.allocations ?? null
  const serverItems = useMemo(() => [...a.items].sort((x, y) => y.weight - x.weight), [a])
  const order = serverItems.map((x) => x.ticker)  // 색은 종목을 따른다: 구성을 바꿔도 같은 종목은 같은 색
  const items = serverItems
  const [all, setAll] = useState(false)
  const cashW = a.cash_weight
  const cash = cashW >= 0.0005 ? cashW : 0  // 0.0% 로 보일 만큼 작은 값(계산 잔차)은 현금 행을 만들지 않는다
  const cashAmt = bases ? { usd: bases.current.cash_usd, krw: bases.current.cash_krw } : null
  const usdOnly = !(a.fx_rate > 0) || Math.abs(a.fx_rate - 1) < 1e-9  // 환율 1.00 = USD 요청: 서버 '원화' 값이 USD 숫자와 같아 원화로 보이면 안 된다
  const base = requestedAmount(doc)
  const fee = (doc?.parameters?.backtest as { commission_bps?: number } | undefined)?.commission_bps
  const shown = all ? items : items.slice(0, TOP_N)
  const maxW = Math.max(cash, ...items.map((x) => x.weight), 1e-9)  // 막대 길이 기준: 전체 종목·현금 가운데 가장 큰 비중 (펼쳐도 기준이 바뀌지 않게)
  const forward = a.basis === "forward"
  const desc = <>{forward ? "분석 기준일의 자료로 계산한 목표 배분액입니다" : "선택된 전략의 배분액입니다"} · 기준: {a.basis_ko}{!usdOnly && a.fx_direction ? ` · 환율 ${a.fx_direction}` : ""}</>
  return (
    <ResultCard id="q-alloc" q="어떤 주식에 얼마를 투자하면 될까요?" more={["구성 자세히 보기", onMore]} desc={desc}>
      <dl className="flex flex-wrap gap-x-8 gap-y-2 text-sm">
        <div><dt className="text-xs font-semibold text-slate-500">투자 기준금액</dt><dd className="mt-0.5 text-lg font-bold tabular-nums text-slate-950">{base ?? fmt(a.initial_amount_usd, "usd")}{proposed(doc)?.structured?.requested_amount && <MockTag />}</dd></div>
        {base && <div><dt className="text-xs font-semibold text-slate-500">배분 계산에 쓴 금액</dt><dd className="mt-0.5 tabular-nums text-slate-700">{fmt(a.initial_amount_usd, "usd")}</dd></div>}
        <div><dt className="text-xs font-semibold text-slate-500">종목 수</dt><dd className="mt-0.5 tabular-nums text-slate-700">{items.length}개{cash ? " + 현금" : ""}</dd></div>
      </dl>
      <div className="flex h-3 w-full gap-0.5 overflow-hidden rounded-full" role="img" aria-label={`비중: ${items.map((x) => `${x.ticker} ${fmt(x.weight, "pct1")}`).join(", ")}${cash ? `, 현금 ${fmt(cash, "pct1")}` : ""}`}>
        {items.map((x) => <span key={x.ticker} className="min-w-0" style={{ flex: `${x.weight} 1 0`, background: holdingColor(x.ticker, order) }} />)}
        {cash > 0 && <span className="min-w-0" style={{ flex: `${cash} 1 0`, background: OTHER_COLOR }} />}
      </div>
      {/* 종목별 줄: 모든 줄이 부모 격자의 같은 칸(subgrid)을 써서, 금액 글자 길이와 상관없이 막대가 같은 위치에서 같은 길이 기준으로 시작한다.
          막대는 가장 큰 비중을 꽉 찬 길이로 둔 하나의 기준이라 종목끼리 비율이 그대로 보인다. 비중(%)은 이름 바로 옆, 금액만 오른쪽 끝. */}
      <div>
        <div aria-hidden className={`${ALLOC_GRID} border-b border-slate-200 pb-2 text-xs font-semibold text-slate-500`}><span>종목</span><span className="text-right">비중</span><span /><span className="text-right">목표 배분액</span></div>
        <ul aria-label="종목별 목표 배분액" className={`${ALLOC_GRID} divide-y divide-slate-100`}>
          {shown.map((x) => (
            <AllocRow key={x.ticker} color={holdingColor(x.ticker, order)} weight={x.weight} max={maxW}
              name={<><span className="block truncate font-semibold text-slate-900" title={x.name}>{x.name && x.name !== x.ticker ? x.name : x.ticker}</span><span className="block truncate text-xs text-slate-500">{x.name && x.name !== x.ticker ? x.ticker : ""}{x.sector ? `${x.name && x.name !== x.ticker ? " · " : ""}${x.sector}` : ""}</span></>}
              amount={<><span className="block whitespace-nowrap text-base font-bold tabular-nums text-slate-950">{usdOnly ? fmt(x.usd, "usd") : money(Math.round(x.krw), "KRW")}</span>{!usdOnly && <span className="block whitespace-nowrap text-xs tabular-nums text-slate-500">{fmt(x.usd, "usd")}</span>}</>} />
          ))}
          {cash > 0 && (
            <AllocRow color={OTHER_COLOR} weight={cash} max={maxW} name={<span className="block font-semibold text-slate-600">현금 (목표 비중)</span>}
              amount={cashAmt ? <><span className="block whitespace-nowrap text-base font-bold tabular-nums text-slate-700">{usdOnly ? fmt(cashAmt.usd, "usd") : money(cashAmt.krw, "KRW")}</span>{!usdOnly && <span className="block whitespace-nowrap text-xs tabular-nums text-slate-500">{fmt(cashAmt.usd, "usd")}</span>}</> : <span className="text-xs text-slate-600">금액 미제공</span>} />
          )}
        </ul>
      </div>
      {items.length > TOP_N && <button type="button" aria-expanded={all} onClick={() => setAll((v) => !v)} className="flex items-center gap-1 text-sm font-semibold text-blue-700 hover:underline">{all ? "상위 종목만 보기" : `전체 종목 보기 (${items.length}개${cash ? " + 현금" : ""})`}<ChevronDown className={`size-4 transition-transform ${all ? "rotate-180" : ""}`} /></button>}
      {p?.execution && <ExecutionOrders e={p.execution} usdOnly={usdOnly} doc={doc} />}
      <div className="space-y-1 rounded-xl bg-slate-50 px-4 py-3 text-xs leading-5 text-slate-600">
        {forward && doc && <p>이 배분은 분석 기준일의 「현재 구성」입니다. 위에서 선택된 전략({doc.header.chosen_label_ko})은 과거 성과로 고른 구성이라 비중이 다를 수 있습니다.</p>}
        {p?.execution
          ? <p>목표 배분액은 비중대로 나눈 금액입니다. 주식은 1주 단위로 사므로 실제로 살 수 있는 수량과 금액은 「예상 매수 주문」에서 볼 수 있습니다. 비중은 반올림해 표시해 합계가 100%와 조금 다를 수 있습니다.</p>
          : <p>목표 배분액은 실제 매수 금액과 다를 수 있습니다. 종목별 매수 수량, 거래 수수료{fee !== undefined ? `(백테스트는 거래대금의 ${fee / 100}%를 가정)` : ""}, 매수 후 남는 현금은 이 분석에서 제공하지 않습니다. 비중은 반올림해 표시해 합계가 100%와 조금 다를 수 있습니다.</p>}
      </div>
    </ResultCard>
  )
}

/** 카드 2 종목 줄의 칸: 종목 | 비중(%) | 막대 | 금액. 칸 너비는 글자와 상관없는 고정 최소값 + 비율이라 모든 줄(머리 줄 포함)이 같은 위치에 선다. */
const ALLOC_GRID = "grid grid-cols-[minmax(13rem,1.1fr)_4rem_minmax(9rem,1.4fr)_minmax(8.5rem,0.8fr)] gap-x-5"

/** 종목 한 줄. 막대는 왼쪽 기준선에서 시작하고(끝만 둥글게), 길이는 가장 큰 비중 대비 비율이다. 값은 바로 옆 % 글자로 읽는다. */
function AllocRow({ color, weight, max, name, amount }: { color: string; weight: number; max: number; name: React.ReactNode; amount: React.ReactNode }) {
  return (
    <li className="col-span-full grid grid-cols-subgrid items-center py-3">
      <div className="flex min-w-0 items-center gap-2"><span className="inline-block size-2.5 shrink-0 rounded-sm" style={{ background: color }} aria-hidden /><span className="min-w-0">{name}</span></div>
      <span className="text-right text-sm font-semibold tabular-nums text-slate-700">{fmt(weight, "pct1")}</span>
      <span className="block h-2.5 border-l border-slate-300" aria-hidden><span data-bar className="block h-full rounded-r" style={{ width: `${Math.min(100, (weight / max) * 100)}%`, minWidth: weight > 0 ? 2 : 0, background: color }} /></span>
      <div className="min-w-0 text-right">{amount}</div>
    </li>
  )
}

/** 예상 매수 주문 (제안 계약 execution): 카드 2의 배분(분석 기준일 현재 구성) 비중을 기준일 주가·환율로 실제 주문 단위로 바꾼 값. 목표 배분액과 구분한다. */
function ExecutionOrders({ e, usdOnly, doc }: { e: NonNullable<ReturnType<typeof proposed>>["execution"] & object; usdOnly: boolean; doc?: ReportDoc }) {
  const amt = (usd: number, krw: number) => (usdOnly ? fmt(usd, "usd") : money(krw, "KRW"))
  const fx = e.fx.rate
  return (
    <Disclosure size="sm" title={<span className="inline-flex items-center">예상 매수 주문<MockTag /></span>} summary={`${e.share_basis === "integer" ? "1주 단위" : "소수점"} · ${e.items.length}종목`}>
      <div className="space-y-3">
        <p className="text-xs leading-5 text-slate-600">위 배분({e.strategy_label_ko})의 비중을 분석 기준일({e.as_of}) 주가와 환율(1 USD = {fx.toLocaleString("en-US")}원)로 실제 주문 단위로 바꾼 예상입니다. {e.share_basis === "integer" ? "주식은 1주 단위로만 살 수 있어" : "소수점 주식으로 사도"} 목표 배분액과 금액이 조금 다르고, 남는 돈은 현금으로 남습니다. 거래 수수료는 거래대금의 {e.commission_bps / 100}%로 가정했습니다.</p>
        <div className="overflow-x-auto rounded-xl border border-slate-200">
          <table className="w-full min-w-[620px] text-sm">
            <thead><tr className="border-b border-slate-200 bg-slate-50 text-left text-xs font-semibold text-slate-600"><th className="px-3 py-2">종목</th><th className="px-3 py-2 text-right">기준 주가</th><th className="px-3 py-2 text-right">목표 배분액</th><th className="px-3 py-2 text-right">주식 수</th><th className="px-3 py-2 text-right">예상 매수 금액</th><th className="px-3 py-2 text-right">수수료</th></tr></thead>
            <tbody>{e.items.map((x) => <tr key={x.ticker} className="border-b border-slate-100"><td className="px-3 py-2"><b className="font-semibold text-slate-900">{x.ticker}</b> <span className="text-xs text-slate-500">{nameOf(doc, x.ticker)}</span></td><td className="whitespace-nowrap px-3 py-2 text-right tabular-nums text-slate-700">{fmt(x.price_usd, "usd")}</td><td className="whitespace-nowrap px-3 py-2 text-right tabular-nums text-slate-500">{amt(x.target_usd, x.target_krw)}</td><td className="whitespace-nowrap px-3 py-2 text-right font-semibold tabular-nums text-slate-950">{x.shares.toLocaleString("en-US")}주</td><td className="whitespace-nowrap px-3 py-2 text-right font-semibold tabular-nums text-slate-950">{amt(x.cost_usd, x.cost_krw)}</td><td className="whitespace-nowrap px-3 py-2 text-right tabular-nums text-slate-600">{amt(x.fee_usd, Math.round(x.fee_usd * fx))}</td></tr>)}</tbody>
          </table>
        </div>
        <dl className="grid grid-cols-1 gap-2 text-sm sm:grid-cols-3">
          <div className="rounded-lg bg-slate-50 px-3 py-2"><dt className="text-xs text-slate-500">예상 매수 합계</dt><dd className="font-semibold tabular-nums text-slate-900">{amt(e.totals.invested_usd, Math.round(e.totals.invested_usd * fx))}</dd></div>
          <div className="rounded-lg bg-slate-50 px-3 py-2"><dt className="text-xs text-slate-500">예상 수수료</dt><dd className="font-semibold tabular-nums text-slate-900">{amt(e.totals.fee_usd, Math.round(e.totals.fee_usd * fx))}</dd></div>
          <div className="rounded-lg bg-slate-50 px-3 py-2"><dt className="text-xs text-slate-500">매수 후 남는 현금</dt><dd className="font-semibold tabular-nums text-slate-900">{amt(e.totals.cash_left_usd, e.totals.cash_left_krw)}</dd>{e.totals.cash_target_usd > 0 && <dd className="text-xs text-slate-500">이 중 전략의 현금 비중 {amt(e.totals.cash_target_usd, e.totals.cash_target_krw)}</dd>}</div>
        </dl>
        <p className="text-xs leading-5 text-slate-500">예상 매수 합계 + 수수료 + 남는 현금 = 투자금 {fmt(e.capital.usd, "usd")}. {e.note_ko}</p>
      </div>
    </Disclosure>
  )
}

const PAST_HELP: Record<string, (k: SummaryKpi) => string> = {
  cagr: (k) => (/연평균|CAGR/.test(k.label_ko) ? "과거 기간 동안 1년에 평균 얼마나 올랐는지" : "과거 성과 계산 기간 전체 동안의 수익률 (1년 평균이 아님)"),
  mdd: () => "가장 높았던 때보다 가장 많이 떨어졌던 비율",
  excess: (k) => (/\(기간\)/.test(k.label_ko) ? "같은 기간 누적 수익률이 비교지수보다 얼마나 높거나 낮았는지" : "같은 기준으로 계산한 과거 연평균 수익률의 차이"),
}
const kpiTerm = (k: { id: string; label_ko: string }) => (k.id === "cagr" ? (/CAGR/.test(k.label_ko) ? "CAGR" : "기간 수익률") : k.id === "mdd" ? "최대낙폭" : k.id === "sharpe" ? "Sharpe" : null)

/** 카드 3: 과거에 투자했다면 어땠을까요?
 *  [지표 이름] → [선택 전략 값 | 비교지수 값] (같은 크기) → [비교지수 대비 차이(서버 excess)] → [같은 조건 안내] → (짧은 창이면) 연 환산 안내 한 줄.
 *  지표 이름은 서버가 준 KPI(짧은 창 = 기간 수익률, 아니면 CAGR)를 따르고, 값·차이는 서버 값 그대로다. 그다음 최대낙폭, 누적 수익률 미니 차트. */
export function PastCard({ sm, doc, onMore }: { sm: ReportSummary; doc: ReportDoc; onMore: () => void }) {
  const ret = sm.kpis.find((k) => k.id === "cagr")
  const ex = sm.kpis.find((k) => k.id === "excess")
  const period = sm.period ?? doc.header.backtest_period
  const hasBench = !!ret && ret.benchmark_value != null
  const exInline = hasBench && !!ex  // 비교 영역 안에서 차이를 보여 주면 아래 별도 행으로 다시 그리지 않는다
  const rest = [...(exInline || !ex ? [] : [ex]), ...sm.kpis.filter((k) => k.id === "mdd")]
  return (
    // 옆 카드 4가 길면 이 카드도 같은 높이로 늘어난다 → 요소 사이를 넓히고, 남는 높이는 누적 수익률 차트가 채운다 (좁은 화면에서는 늘어나지 않음)
    <ResultCard id="q-past" q="과거에 투자했다면 어땠을까요?" more={["과거 성과 자세히 보기", onMore]} desc={`${period.start} ~ ${period.end} 백테스트 (과거 자료로 계산한 결과)`} body="flex flex-col gap-6">
      {ret && <ReturnCompare ret={ret} ex={exInline ? ex! : null} doc={doc} />}
      {rest.length ? (
        <dl className="divide-y divide-slate-100 rounded-xl border border-slate-200">
          {rest.map((k) => {
            const n = kpiDisplay(doc, k)
            return (
              <div key={k.id} className="flex flex-wrap items-start justify-between gap-x-4 gap-y-1.5 px-5 py-4">
                <div className="min-w-0 flex-[1_1_12rem]">
                  <dt className="flex items-center gap-1 text-sm font-semibold text-slate-800"><span className="min-w-0">{n.name}</span>{kpiTerm(k) && <Term t={kpiTerm(k)!} />}{proposed(doc)?.structured?.kpi_meta?.[k.id] && <MockTag />}</dt>
                  <dd className="mt-0.5 text-xs leading-5 text-slate-500">{k.id === "excess" && k.note_ko ? kpiNote(k.note_ko, doc) : <>{PAST_HELP[k.id]?.(k)}{k.note_ko ? ` · ${kpiNote(k.note_ko, doc)}` : ""}</>}</dd>
                </div>
                <dd className="shrink-0 text-right"><span className="block text-xl font-bold tabular-nums text-slate-950">{fmt(k.value, k.format)}</span>{k.benchmark_value != null && <span className="block whitespace-nowrap text-xs tabular-nums text-slate-500">{k.benchmark_label_ko ?? "비교지수"} {fmt(k.benchmark_value, k.format)}</span>}</dd>
              </div>
            )
          })}
        </dl>
      ) : !ret && <p className="text-sm text-slate-600">요약 성과 지표가 없습니다. 상세 분석의 과거 성과에서 확인하세요.</p>}
      <ReturnMini doc={doc} ids={sm.mini_series?.ids ?? [doc.header.chosen_portfolio_id]} grow />
      <p className="text-xs leading-5 text-slate-500">과거 성과는 미래 수익을 보장하지 않습니다. 최종 평가금액·Sharpe 등 나머지 지표는 상세 분석에서 모두 볼 수 있습니다.</p>
    </ResultCard>
  )
}

/** 수익률 비교: 선택 전략과 비교지수를 같은 모양·같은 크기로. 비교 영역이 좁으면(20rem 미만) 「이름 … 값」 세로 행 둘로 바뀐다. */
function ReturnCompare({ ret, ex, doc }: { ret: SummaryKpi; ex: SummaryKpi | null; doc: ReportDoc }) {
  const n = kpiDisplay(doc, ret)
  const meta = proposed(doc)?.structured?.kpi_meta?.cagr
  const short = meta ? meta.period === "total" : /^기간 수익률/.test(ret.label_ko)  // 서버가 짧은 창이라 기간 수익률을 준 경우 (report_blocks.kpis)
  const hasBench = ret.benchmark_value != null
  const { ticker: bt, desc: etf } = benchOf(doc, ret.benchmark_label_ko)
  const bench = bt ?? ret.benchmark_label_ko ?? "비교지수"
  // 차이가 어느 수익률의 차이인지: 서버 excess 이름 「비교지수(SPY) 대비 (기간)」 = 기간 수익률 차이, 「비교지수(SPY) 대비」 = CAGR 차이
  const exSubject = ex ? (/\(기간\)$/.test(ex.label_ko) ? "전체 기간 수익률이" : /^비교지수\(.+?\) 대비$/.test(ex.label_ko) ? "연평균 수익률(CAGR)이" : null) : null
  const exText = ex ? excessSentence(ex.value, bench, exSubject) : null
  const sub = short ? `${n.sub ? `${n.sub} · ` : ""}1년 평균이 아닌 기간 전체의 수익률` : ret.note_ko
  const cell = "flex items-baseline justify-between gap-3 @xs:block"
  const value = "shrink-0 text-2xl font-bold tabular-nums text-slate-950 @xs:mt-1 @xs:block"
  return (
    <section aria-label={`${n.name} 비교`} className="@container rounded-xl border border-slate-200">
      <div className="px-5 pt-5">
        <h4 className="flex items-center gap-1 text-base font-bold text-slate-950">{n.name}{kpiTerm(ret) && <Term t={kpiTerm(ret)!} label={n.name} />}{(meta || proposed(doc)?.structured?.benchmark) && <MockTag />}</h4>
        {sub && <p className="text-xs leading-5 text-slate-500">{sub}</p>}
      </div>
      <dl className={`mt-4 grid grid-cols-1 gap-y-3 px-5 pb-5 ${hasBench ? "@xs:grid-cols-2 @xs:gap-x-6" : ""}`}>
        <div className={cell}>
          <dt className="flex items-center gap-1.5 text-sm font-semibold text-blue-700"><span className="size-2 shrink-0 rounded-full bg-blue-600" aria-hidden />선택 전략</dt>
          <dd className={value}>{fmt(ret.value, ret.format)}</dd>
        </div>
        {hasBench && (
          <div className={`${cell} @xs:border-l @xs:border-slate-200 @xs:pl-6`}>
            <dt className="flex min-w-0 items-center gap-1 text-sm font-semibold text-slate-600">
              <span className="min-w-0">비교지수 · <span className="whitespace-nowrap">{bench}</span></span>
              <HelpTip label={`비교지수 · ${bench}`}>
                {etf && <span className="block">{bench}는 {etf}입니다.</span>}
                <span className="block">{bt ? "선택 전략과 같은 날, 같은 금액을 넣고 팔지 않고 계속 보유했다고 가정해 계산했습니다 (매수 후 보유 · 동일 적립)." : "선택 전략과 같은 기간·같은 납입 조건으로 계산한 비교 기준입니다."}</span>
                {ret.benchmark_label_ko && <span className="mt-1 block text-slate-500">서버 표기: {ret.benchmark_label_ko}</span>}
              </HelpTip>
            </dt>
            <dd className={value}>{fmt(ret.benchmark_value, ret.format)}</dd>
          </div>
        )}
      </dl>
      {hasBench && (
        <div className="space-y-1.5 border-t border-slate-100 px-5 py-4">
          {exText && <p className="text-sm font-semibold text-slate-900">{exText}</p>}
          <p className="text-xs leading-5 text-slate-600">{bt ? `같은 기간, 같은 투자금 납입 조건(동일 적립)으로 ${bt}를 사서 계속 보유했다고 가정해 비교했습니다.` : "같은 기간, 같은 투자금 납입 조건으로 비교했습니다."}</p>
        </div>
      )}
      {short && <ShortWindowNotice ret={ret} doc={doc} />}
    </section>
  )
}

/** 짧은 창 안내 한 줄 + 「연 환산 수익률 안내」 도움말. 연 환산 값·최소 거래일은 서버 값이 있을 때만 쓴다. */
function ShortWindowNotice({ ret, doc }: { ret: SummaryKpi; doc: ReportDoc }) {
  const an = proposed(doc)?.structured?.annualized
  const annual = an ? fmt(an.strategy_cagr, "pct") : annualizedFromNote(ret.note_ko)
  const bench = an ? benchOf(doc).ticker ?? "비교지수" : null
  const min = minAnnualize(doc)
  const days = periodOf(doc).window_days ?? (/\((\d+)거래일\)/.exec(ret.label_ko)?.[1] ? Number(/\((\d+)거래일\)/.exec(ret.label_ko)![1]) : null)
  return (
    <p className="border-t border-slate-100 px-5 py-4 text-xs leading-5 text-slate-600">
      분석 기간이 짧아, 위 비교에는 전체 기간 수익률을 사용했습니다. 연 환산 수익률은 참고용입니다.{an && <MockTag />}{" "}
      <HelpTip label="연 환산 수익률 안내">
        {annual && <span className="block">선택 전략의 연 환산 수익률은 <b className="font-semibold tabular-nums">{annual}</b>입니다.</span>}
        {an && <span className="block">같은 기간 {bench}의 연 환산 수익률은 <b className="font-semibold tabular-nums">{fmt(an.benchmark_cagr, "pct")}</b>입니다 (전체 기간 수익률 {fmt(an.benchmark_total_return, "pct")}).</span>}
        <span className="block">연 환산 수익률은 과거{days ? ` ${days}거래일` : ""} 동안의 성과를 복리로 1년 길이에 맞춰 바꾼 계산값입니다. 실제 1년 동안의 실적이나 앞으로의 수익 예측이 아닙니다.</span>
        {min && <span className="mt-1 block">이 분석은 평가 기간이 {min.days}거래일(약 {min.years}년)보다 짧으면 목표 수익률·변동성 조건 검사를 판정 대신 참고로만 표시합니다. 프로그램 내부 기준이며, 이 기간을 넘었다고 성과를 믿을 수 있다는 뜻은 아닙니다.</span>}
      </HelpTip>
    </p>
  )
}

/** 누적 수익률 미니 차트 (시작 = 100). 서버 datasets 의 index 계열 그대로. grow = 카드에 남는 높이를 채운다 (최소 h-28). */
export function ReturnMini({ doc, ids, grow }: { doc: ReportDoc; ids: string[]; grow?: boolean }) {
  const rows = useMemo(() => doc.datasets.dates.map((d, i) => { const r: Record<string, number | string> = { date: d }; for (const id of ids) { const v = doc.datasets.series[id]?.index?.[i]; if (typeof v === "number") r[id] = v } return r }), [doc, ids])
  const last = rows[rows.length - 1] ?? {}
  if (!rows.length) return null
  return (
    <div className={grow ? "flex min-h-0 flex-1 flex-col" : ""}>
      <p className="text-xs font-semibold text-slate-600">누적 수익률 (시작 = 100)</p>
      <div className={grow ? "mt-2 min-h-28 flex-1" : "mt-1 h-28"} role="img" aria-label="누적 수익률 미니 차트">
        <ResponsiveContainer width="100%" height="100%"><LineChart data={rows}><XAxis dataKey="date" hide /><YAxis hide domain={["auto", "auto"]} /><Tooltip formatter={(v: unknown, n: unknown) => [fmt(v as number, "index"), doc.datasets.series[String(n)]?.label_ko ?? String(n)]} labelFormatter={(l) => String(l)} />
          {ids.map((id) => <Line key={id} type="monotone" dataKey={id} stroke={colorOf(id, ids)} dot={false} strokeWidth={id === doc.header.chosen_portfolio_id ? 2.5 : 1.5} isAnimationActive={false} />)}</LineChart></ResponsiveContainer>
      </div>
      <ul className={`${grow ? "mt-3 space-y-1" : "mt-1 space-y-0.5"} text-xs text-slate-600`}>{ids.map((id) => <li key={id} className="flex items-center gap-2"><span className="inline-block size-2.5 shrink-0 rounded-full" style={{ background: colorOf(id, ids) }} aria-hidden /><span className="min-w-0 truncate" title={doc.datasets.series[id]?.label_ko ?? id}>{doc.datasets.series[id]?.label_ko ?? id}</span><b className="ml-auto tabular-nums">{fmt(last[id] as number, "index")}</b></li>)}</ul>
    </div>
  )
}

const RULE_NAME: Record<string, string> = { 최대낙폭: "허용 손실 vs 과거 최대 하락폭", 목표수익: "목표 수익률", "비교지수 대비": "비교지수 대비 성과" }
const LEVEL_KO: Record<string, string> = { hard: "필수", flag: "표시" }

/** 카드 4: 내 투자 조건에 맞나요? 서버 검증 규칙(rules_ko)을 그대로, 허용 손실은 막대로. 새 판정은 만들지 않는다. */
export function ConditionCard({ sm, doc, onMore }: { sm: ReportSummary; doc?: ReportDoc; onMore: () => void }) {
  return (
    <ResultCard id="q-fit" q="내 투자 조건에 맞나요?" more={["검증 결과 자세히 보기", onMore]} desc="선택된 전략을 내가 정한 조건과 비교한 검증 결과입니다">
      <ConditionRules v={sm.validation} verdict={sm.verdict} bench={benchName(sm)} doc={doc} />
    </ResultCard>
  )
}

/** 서버 R3 문장 「SPY 대비 초과 CAGR +65.1%p」 → [비교지수, 값]. 틀이 다르면 null. */
const excessCagr = (msg: string) => { const m = /^(\S+) 대비 초과 CAGR ([+\-−]?[\d.]+%p)$/.exec(msg); return m ? { bench: m[1], value: m[2] } : null }

export function ConditionRules({ v, verdict, bench = "비교지수", doc }: { v: ReportSummary["validation"]; verdict?: ReportSummary["verdict"] | null; bench?: string; doc?: ReportDoc }) {
  const rules = v.rules_ko ?? []
  const named = new Set(rules.map((r) => r.name_ko))
  const extraFail = v.failed_rules_ko.filter((r) => !named.has(r))
  const extraWarn = (v.warned_rules_ko ?? []).filter((r) => !named.has(r))
  const total = v.n_pass + v.n_warn + v.n_fail
  const risk = doc ? analysisRisk(doc) : null
  // 구조화된 검증(제안 계약)이 있으면 그 값으로 그린다 — 서버 요약에 없던 「기준 이내였던 참고 검사」·「상한 없는 기준」도 보인다. 없으면 서버 문장을 읽는다.
  const s7 = checkOf(doc, "R7"), s3 = checkOf(doc, "R3"), s1 = checkOf(doc, "R1")
  const v7 = s7 ? volFromStructured(s7) : null
  const notes = (v.info_notes_ko ?? []).map((t) => ({ t, vc: parseVolCheck(t) }))  // 참고(서버 info) 중 변동성 검사는 따로 풀어 쓴다
  const volNotes = v7 ? [] : notes.filter((x) => x.vc), otherNotes = notes.filter((x) => !x.vc).map((x) => x.t)
  const rp = proposed(doc)?.risk_profile
  const ranking = proposed(doc)?.explanations?.ranking
  // 허용 손실은 아래 막대에 이미 보이므로 「손실 감내 수준 X%」는 다시 쓰지 않고, 그 뒤에 붙은 다른 정보(낙폭 맞춤안 목표 등)만 막대 아래에 남긴다. 막대가 없으면 원문 그대로 맨 아래에.
  const barShown = !!v.r1 && (rules.length === 0 || rules.some((r) => r.rule === "R1"))
  const tolExtra = barShown ? toleranceExtraOf(doc, v.tolerance_note_ko) : ""
  return (
    <div className="space-y-4">
      {rules.length > 0 ? (
        <ul className="space-y-3" aria-label="조건별 검증 결과">
          {rules.filter((r) => !(v7 && r.rule === "R7")).map((r) => {
            const [tone, label] = ruleStatus(r.status)
            const ex = r.rule === "R3" ? (s3?.value != null ? { bench, value: `${s3.value > 0 ? "+" : s3.value < 0 ? "-" : ""}${(Math.abs(s3.value) * 100).toFixed(1)}%p` } : excessCagr(r.message_ko)) : null
            const vc = r.rule === "R7" ? parseVolCheck(r.message_ko) : null
            const r1 = r.rule === "R1" ? (s1?.value != null && s1.threshold != null ? { main: `최대낙폭 ${(s1.value * 100).toFixed(1)}% vs 허용 ${(s1.threshold * 100).toFixed(1)}%${s1.status === "pass" ? "" : ` — 허용보다 ${((s1.value - s1.threshold) * 100).toFixed(1)}%p 큼`}`, bench: `같은 기간 ${bench} 매수 후 보유·동일 적립 시 ${((s1.benchmark_value ?? 0) * 100).toFixed(1)}%` } : r1Text(r.message_ko)) : null
            if (vc) return <VolatilityCheck key={r.rule} c={vc} status={r.status} level={LEVEL_KO[r.level]} risk={risk} doc={doc} />
            return (
              <li key={r.rule} className="rounded-xl border border-slate-200 p-4 sm:p-5">
                <div className="flex flex-wrap items-center justify-between gap-2"><span className="inline-flex items-center gap-1 text-base font-semibold text-slate-900">{RULE_NAME[r.name_ko] ?? r.name_ko}{r.rule === "R1" && <Term t="최대낙폭" />}{LEVEL_KO[r.level] && <span className="ml-0.5 text-xs font-normal text-slate-500">{LEVEL_KO[r.level]}</span>}{checkOf(doc, r.rule) && <MockTag />}</span><StatusPill tone={tone}>{label}</StatusPill></div>
                {ex ? (
                  <div className="mt-3">
                    <p className="flex items-center gap-1 text-sm font-medium text-slate-600">{ex.bench} 대비 연평균 수익률(CAGR) 차이<Term t="CAGR" /></p>
                    <p className="mt-1 text-2xl font-bold tabular-nums text-slate-950">{ex.value}</p>
                    <p className="mt-2 text-sm leading-6 text-slate-600">같은 기준으로 계산한 과거 연평균 수익률의 차이입니다.{doc && isShortWindow(doc) ? ` ${shortWindowNote(doc)}` : ""}</p>
                  </div>
                ) : r1 ? (
                  <div className="mt-2 text-sm leading-6">
                    <p className="text-slate-700">{r1.main}</p>
                    <p className="text-slate-500">비교: {r1.bench}</p>
                  </div>
                ) : <p className="mt-2 text-sm leading-6 text-slate-600">{pairCagr(prefTerms(r.message_ko))}</p>}
                {r.rule === "R1" && v.r1 && <DrawdownBar r1={v.r1} tone={tone} />}
                {r.rule === "R1" && tolExtra && <p className="mt-3 text-sm leading-6 text-slate-600">{tolExtra}{proposed(doc)?.structured?.tolerance && <MockTag />}</p>}
              </li>
            )
          })}
          {volNotes.map((x, i) => <VolatilityCheck key={`vn${i}`} c={x.vc!} status="info" risk={risk} doc={doc} />)}
          {v7 && s7 && <VolatilityCheck c={v7} status={s7.status} level={LEVEL_KO[s7.level]} risk={risk} doc={doc} mock />}
        </ul>
      ) : total > 0 ? (
        <div className="flex flex-wrap gap-2"><StatusPill tone="green">충족 {v.n_pass}</StatusPill><StatusPill tone="amber">주의 {v.n_warn}</StatusPill><StatusPill tone="red">미충족 {v.n_fail}</StatusPill></div>
      ) : <p className="text-sm text-slate-600">이 리포트에는 조건별 검증 결과가 없습니다. 판정할 수 없는 항목을 화면에서 따로 판단하지 않습니다.</p>}
      {!rules.length && v.r1 && <div><DrawdownBar r1={v.r1} tone={ruleStatus(v.r1.status)[0]} />{tolExtra && <p className="mt-3 text-sm leading-6 text-slate-600">{tolExtra}</p>}</div>}
      {extraFail.length > 0 && <div><p className="text-sm font-semibold text-red-700">미충족 규칙</p><ul className="mt-1.5 list-disc space-y-1 pl-5 text-sm leading-6 text-slate-700">{extraFail.map((r) => <li key={r}>{r}</li>)}</ul></div>}
      {extraWarn.length > 0 && <div><p className="text-sm font-semibold text-amber-800">주의 규칙</p><ul className="mt-1.5 list-disc space-y-1 pl-5 text-sm leading-6 text-slate-700">{extraWarn.map((r) => <li key={r}>{r}</li>)}</ul></div>}
      {!rules.length && volNotes.length > 0 && <ul className="space-y-3">{volNotes.map((x, i) => <VolatilityCheck key={i} c={x.vc!} status="info" risk={risk} doc={doc} />)}</ul>}
      {otherNotes.length > 0 && <div className="rounded-xl bg-slate-50 p-4 sm:p-5"><p className="flex items-center gap-1.5 text-sm font-semibold text-slate-700"><Info className="size-4" aria-hidden />참고</p><ul className="mt-2 list-disc space-y-1 pl-5 text-sm leading-6 text-slate-600">{otherNotes.map((t, i) => <li key={i}>{prefTerms(t)}</li>)}</ul></div>}
      {(rules.length > 0 || total > 0) && (
        <p className="pt-1 text-sm leading-6 text-slate-600">
          {pickSentence(v.n_candidates ?? (total || null), bench, verdict)}<Term t="투자 구성안" label="투자 구성안이란?" />
          {ranking && <span className="ml-1.5 inline-flex items-center text-xs text-slate-500">순위 기준 전체<HelpTip label="추천 순위 기준 전체"><ol className="list-decimal space-y-1 pl-4">{ranking.map((x) => <li key={x.key}><b className="font-semibold text-slate-800">{x.label_ko}</b> — {x.desc_ko}</li>)}</ol></HelpTip><MockTag /></span>}
          {!rules.length && total > 0 && <span className="block text-slate-500">포트폴리오 {total}개 중 충족 {v.n_pass} · 주의 {v.n_warn} · 미충족 {v.n_fail}</span>}
        </p>
      )}
      {!barShown && v.tolerance_note_ko && <p className="text-sm leading-6 text-slate-500">{v.tolerance_note_ko}</p>}
      {rp && rp.informational_rules.length > 0 && <p className="text-sm leading-6 text-slate-500">판정 대신 참고로 표시한 검사: {rp.informational_rules.map((x) => `${x.name_ko}(${x.reason_ko})`).join(", ")}<MockTag /></p>}
    </div>
  )
}

/** 변동성 검사 한 줄 요약 (주의 목록용). 서버 판정(warn 등)이 붙은 경우에만 쓴다. */
function volSummary(c: VolCheck): string {
  if (c.kind === "nocap" || !c.band) return `선택 전략의 연변동성 ${c.vol} · 이번 분석의 변동성 기준에는 상한이 없습니다`
  return `선택 전략의 연변동성 ${c.vol}가 이번 분석의 변동성 기준(${c.band} 이하)보다 높았습니다`
}

/** 변동성 적합(R7): 결과 → 비교 수치 → 기준 설명 → 기간 안내. 결과 문장은 서버 판정을 따르고(충족 = 이내, 주의·미충족 = 높음),
 *  서버가 판정하지 않은 짧은 기간에는 표시값이 다를 때만 높다/낮다는 관측을 적되 「미충족」으로 바꾸지 않는다. 상한이 없는 기준에 상한을 만들지 않는다. */
function VolatilityCheck({ c, status, level, risk, doc, mock = false }: { c: VolCheck; status: string; level?: string; risk: ReturnType<typeof analysisRisk> | null; doc?: ReportDoc; mock?: boolean }) {
  const [tone, label] = ruleStatus(status)
  const judged = status !== "info"
  const short = c.short || (!judged && !!doc && isShortWindow(doc))
  const obs = judged ? (status === "pass" ? "within" : "above") : volObserved(c)
  const pref = c.pref ?? risk?.pref ?? null
  const prefName = pref ? VOL_PREF_LABEL[pref] : "이번 분석의 변동성 기준"
  const result = c.kind === "nocap" ? `${prefName}에는 변동성 상한이 없어, 변동성 적합 여부를 따로 판정하지 않습니다.`
    : obs === "above" ? "선택한 전략은 이번 분석의 변동성 기준보다 변동성이 높았습니다."
    : obs === "within" ? "선택한 전략의 변동성은 이번 분석의 변동성 기준 이내였습니다."
    : "선택한 전략의 변동성은 이번 분석의 변동성 기준과 거의 같았습니다."
  const m = c.mult ? Number(c.mult) : null
  const basis = c.kind === "bench" && c.bench && m !== null
    ? `비교지수의 연변동성 ${c.bench}에 ${c.mult}배를 적용한 기준입니다.${m > 1 ? ` 비교지수보다 ${Math.round((m - 1) * 100)}% 높은 변동성까지 허용합니다.` : m === 1 ? " 비교지수와 같은 수준까지 허용합니다." : ` 비교지수보다 ${Math.round((1 - m) * 100)}% 낮은 변동성까지 허용합니다.`}`
    : c.kind === "absolute" ? `비교지수 변동성 자료가 없어, ${prefName}의 고정 상한 ${c.band}를 적용했습니다.`
    : `${prefName}은 변동성 상한을 두지 않습니다.`
  return (
    <li className="rounded-xl border border-slate-200 p-4 sm:p-5">
      <div className="flex flex-wrap items-center justify-between gap-2"><span className="inline-flex items-center gap-1 text-base font-semibold text-slate-900">변동성 적합{level && <span className="ml-0.5 text-xs font-normal text-slate-500">{level}</span>}{mock && <MockTag />}</span><StatusPill tone={tone}>{label}</StatusPill></div>
      <p className="mt-2 text-sm font-semibold leading-6 text-slate-900">{result}</p>
      <dl className="mt-3 space-y-1.5 text-sm">
        <div className="flex items-baseline justify-between gap-3"><dt className="flex items-center gap-1 text-slate-600">선택 전략의 연변동성<Term t="연변동성" /></dt><dd className="shrink-0 text-base font-semibold tabular-nums text-slate-950">{c.vol}</dd></div>
        <div className="flex items-baseline justify-between gap-3"><dt className="text-slate-600">이번 분석의 평가 기준</dt><dd className="shrink-0 text-base font-semibold tabular-nums text-slate-950">{c.band ? `${c.band} 이하` : "상한 없음"}</dd></div>
        {c.kind === "nocap" && c.bench && <div className="flex items-baseline justify-between gap-3"><dt className="text-slate-600">비교지수의 연변동성</dt><dd className="shrink-0 tabular-nums text-slate-700">{c.bench}</dd></div>}
      </dl>
      <p className="mt-3 text-sm leading-6 text-slate-600">{basis}</p>
      {(pref || risk?.tendency) && (
        <p className="mt-1 text-sm leading-6 text-slate-600">
          {pref && <span className="block">이번 분석의 변동성 기준: <b className="font-semibold text-slate-800">{VOL_PREF_LABEL[pref]}</b></span>}
          {risk?.tendency && <span className="block">투자성향: <b className="font-semibold text-slate-800">{risk.tendency}</b>{risk.computed && <span className="text-slate-500"> (자동 진단 {risk.computed} → 최종 선택 {risk.tendency})</span>}{risk.exact && <MockTag />}</span>}
          {risk?.prefDiffers && risk.reasonKo && <span className="block text-slate-500">{risk.reasonKo}</span>}
          {risk?.prefDiffers && risk.code && !risk.reasonKo && <span className="block text-slate-500">투자성향의 기본 기준({VOL_PREF_LABEL[DEFAULT_VOL_PREF[risk.code]]})과 다르게 적용됐습니다. 분석 요청에서 변동성을 따로 언급하면 그 기준이 투자성향보다 우선합니다.</span>}
        </p>
      )}
      {short && <p className="mt-3 border-t border-slate-100 pt-3 text-sm leading-6 text-slate-600">분석 기간이 짧아, 이번에는 변동성 적합 여부를 판정하지 않고 참고 정보로 표시합니다.</p>}
    </li>
  )
}

/** 허용 손실과 과거 최대 하락폭을 한 막대에. 숫자는 서버 r1 그대로, 색은 서버 판정을 따른다. */
function DrawdownBar({ r1, tone }: { r1: NonNullable<ReportSummary["validation"]["r1"]>; tone: Tone }) {
  const mdd = Math.abs(r1.mdd), tol = Math.abs(r1.tolerance), bm = Math.abs(r1.benchmark_mdd)
  const max = Math.max(mdd, tol, bm, 0.01) * 1.15
  const pos = (x: number) => `${(x / max) * 100}%`
  const fill = tone === "green" ? "bg-slate-700" : tone === "red" ? "bg-red-600" : "bg-amber-500"
  return (
    <div className="mt-4" aria-label="최대낙폭 비교">
      <div className="relative h-3.5 rounded-full bg-slate-100">
        <span className={`absolute inset-y-0 left-0 rounded-full ${fill}`} style={{ width: pos(mdd) }} />
        <span className="absolute -inset-y-1 w-0.5 bg-slate-950" style={{ left: pos(tol) }} title="허용 손실" />
        <span className="absolute -inset-y-0.5 w-0.5 bg-blue-500" style={{ left: pos(bm) }} title="비교지수 낙폭" />
      </div>
      <dl className="mt-3 grid grid-cols-3 gap-3">
        <div><dt className="text-xs text-slate-500">과거 최대 하락폭</dt><dd className="mt-0.5 text-base font-semibold tabular-nums text-slate-900">{fmt(-mdd, "pct")}</dd></div>
        <div><dt className="text-xs text-slate-500"><span className="mr-1 inline-block h-2.5 w-0.5 bg-slate-950 align-middle" />허용 손실</dt><dd className="mt-0.5 text-base font-semibold tabular-nums text-slate-900">{fmt(tol, "pct1")}</dd></div>
        <div><dt className="text-xs text-slate-500"><span className="mr-1 inline-block h-2.5 w-0.5 bg-blue-500 align-middle" />비교지수 낙폭</dt><dd className="mt-0.5 text-base font-semibold tabular-nums text-slate-900">{fmt(-bm, "pct")}</dd></div>
      </dl>
    </div>
  )
}

/** 뉴스 반영 효과: 뉴스 반영 구성 vs 같은 종목의 기준 비중 (추천이 다른 포트폴리오여도 보여 준다). 나머지 지표는 펼쳐서. */
export function NewsEffect({ n }: { n: NonNullable<ReportSummary["news_effect"]> }) {
  if (n.disabled) return <div className="rounded-xl border border-slate-200 bg-slate-50 px-4 py-3 text-sm text-slate-600"><b className="font-semibold text-slate-800">뉴스 반영 효과: </b>{n.reason_ko ?? "이 분석에서는 표시할 수 없습니다"}</div>
  const retKo = n.annualized_reliable === false ? "연 환산 수익률 (참고)" : "연평균 수익률(CAGR)"
  const rows: [string, string, string][] = [[retKo, fmt(n.bl_cagr, "pct"), fmt(n.base_cagr, "pct")], ["최대 하락폭", fmt(n.bl_mdd, "pct"), fmt(n.base_mdd, "pct")], ["비교지수 대비 (연)", fmt(n.bl_excess_cagr, "pp"), fmt(n.base_excess_cagr, "pp")]]
  return (
    <div className="rounded-2xl border border-slate-200 bg-white p-4 sm:p-5">
      <h3 className="text-base font-bold text-slate-950">뉴스·공시를 반영한 전략은 기준 비중 전략과 어떤 차이가 있었나요?</h3>
      <p className="mt-1 text-xs text-slate-500">같은 종목·같은 기간에 비중만 다르게 정한 두 구성의 과거 성과입니다.</p>
      <div className="mt-3 overflow-x-auto">
        <table className="w-full min-w-[420px] text-sm">
          <thead><tr className="border-b border-slate-200 text-left text-xs text-slate-500"><th className="py-2 pr-3 font-semibold">항목</th><th className="py-2 pr-3 text-right font-semibold">뉴스 반영<span className="block font-normal">{n.bl_label_ko ?? "뉴스 반영 구성"}</span></th><th className="py-2 text-right font-semibold">기준 비중<span className="block font-normal">{n.base_label_ko ?? "기준 비중"}</span></th></tr></thead>
          <tbody>{rows.map(([k, a, b]) => <tr key={k} className="border-b border-slate-100"><td className="py-2 pr-3 text-slate-700">{k}</td><td className="py-2 pr-3 text-right font-semibold tabular-nums text-slate-950">{a}</td><td className="py-2 text-right tabular-nums text-slate-700">{b}</td></tr>)}</tbody>
        </table>
      </div>
      <p className="mt-3 text-sm text-slate-800"><b>{retKo} 차이</b> <span className="text-base font-bold tabular-nums">{n.diff_cagr == null ? "–" : fmt(n.diff_cagr, "pp")}</span> <span className="text-xs text-slate-500">(뉴스 반영 − 기준 비중)</span></p>
      <p className="mt-1 text-xs leading-5 text-slate-500">과거 한 기간의 비교 결과이며, 이 차이가 뉴스 때문이라고 단정할 수 없습니다.</p>
      <Disclosure size="sm" className="mt-3" title="뉴스 분석 자세히 보기">
        <dl className="grid grid-cols-1 gap-3 text-xs sm:grid-cols-2">
          <div><dt className="flex items-center gap-1 text-slate-500">투자 의견 적중률 (다음 리밸런싱까지)<Term t="투자 의견(뷰)" /></dt><dd className="mt-0.5 text-base font-semibold tabular-nums">{n.hit_next_rb == null ? "–" : fmt(n.hit_next_rb, "pct1")}</dd><dd className="text-[11px] text-slate-500">투자 의견으로 비중을 바꾼 기간 안에서</dd></div>
          <div><dt className="text-slate-500">투자 의견 적중률 (12개월)</dt><dd className="mt-0.5 text-base font-semibold tabular-nums">{n.hit_365 == null ? "–" : fmt(n.hit_365, "pct1")}</dd><dd className="text-[11px] text-slate-500">구성 뒤 12개월 기준</dd></div>
          <div><dt className="text-slate-500">투자 의견 수</dt><dd className="mt-0.5 text-base font-semibold tabular-nums">{n.n_views ?? 0}개</dd></div>
          <div><dt className="text-slate-500">리밸런싱 중 뉴스 적용</dt><dd className="mt-0.5 text-base font-semibold tabular-nums">{n.n_rebalances ?? 0}회 중 {n.n_dates ?? 0}회</dd><dd className="text-[11px] text-slate-500">근거가 부족해 기준 비중을 유지한 횟수 {n.n_fallback ?? 0}회</dd></div>
        </dl>
      </Disclosure>
    </div>
  )
}

/** 서버 설명 문장 "약 29,473,358원 · 투입 원금 …" 의 원화 값. 없으면 null (환율로 다시 계산하지 않는다). */
export function krwFromNote(note: string | null | undefined): { krw: number; rest: string } | null {
  const m = /^약 ([\d,]+)원(?: · )?(.*)$/.exec(note ?? "")
  return m ? { krw: Number(m[1].replace(/,/g, "")), rest: m[2] } : null
}

const KPI_HELP: Record<string, string> = {
  final_value: "백테스트 기간 끝에 평가한 금액입니다. 과거 자료로 계산한 값이며 실제 투자 결과가 아닙니다.",
  cagr: "백테스트 기간의 수익률입니다. 과거 성과는 미래 성과를 보장하지 않습니다.",
  excess: "같은 기간 비교지수보다 수익률이 얼마나 높거나 낮았는지를 나타냅니다.",
  mdd: "기간 중 가장 높았던 평가금액에서 가장 크게 떨어진 비율입니다. 작을수록 덜 흔들린 것입니다.",
  sharpe: "감수한 변동성에 비해 얻은 수익이 어느 정도인지 나타내는 값입니다. 높을수록 위험 대비 수익이 좋았다는 뜻입니다.",
  view_hit: "뉴스·공시로 만든 투자 의견이 실제 결과와 맞은 비율입니다.",
}

/** 문서의 모든 KPI (doc.kpis) 에 요약의 비교지수 값을 붙인다. 요약에만 있는 KPI 도 뒤에 남긴다 — 요약에서 빠진 지표가 화면에서 사라지지 않게. */
export function allKpis(doc: ReportDoc): SummaryKpi[] {
  const sm = new Map((doc.summary?.kpis ?? []).map((k) => [k.id, k]))
  const base = doc.kpis.map((k) => ({ ...k, benchmark_value: sm.get(k.id)?.benchmark_value ?? null, benchmark_label_ko: sm.get(k.id)?.benchmark_label_ko ?? null }))
  const ids = new Set(base.map((k) => k.id))
  return [...base, ...(doc.summary?.kpis ?? []).filter((k) => !ids.has(k.id))]
}

export function KpiRow({ kpis, doc }: { kpis: SummaryKpi[]; doc?: ReportDoc }) {
  return (
    <div className="grid grid-cols-1 gap-3 sm:grid-cols-2 lg:grid-cols-3">
      {kpis.map((k) => {
        const fv = proposed(doc)?.structured?.final_value
        const won = k.id === "final_value" ? (fv ? { krw: fv.krw, rest: (k.note_ko ?? "").replace(/^약 [\d,]+원(?: · )?/, "") } : krwFromNote(k.note_ko)) : null
        const n = kpiDisplay(doc, k)
        const t = kpiTerm(k)
        return (
          <div key={k.id} className="min-w-0 rounded-xl border border-slate-200 bg-white p-4">
            <div className="flex items-center gap-1 text-xs font-semibold text-slate-600"><span className="min-w-0">{n.name}</span>{(proposed(doc)?.structured?.kpi_meta?.[k.id] || (k.id === "final_value" && fv)) && <MockTag />}{t ? <Term t={t} label={n.name} /> : KPI_HELP[k.id] && <HelpTip label={n.name}>{KPI_HELP[k.id]}</HelpTip>}</div>
            {n.sub && <div className="text-xs text-slate-500">{n.sub}</div>}
            <div className="mt-1 break-words text-xl font-semibold tabular-nums text-slate-900">{won ? `약 ${money(won.krw, "KRW")}` : fmt(k.value, k.format)}</div>
            {won && <div className="mt-1 text-xs tabular-nums text-slate-500">{fmt(k.value, k.format)} · 분석 기준일 환율 기준</div>}
            {k.benchmark_value !== undefined && k.benchmark_value !== null && <div className="mt-1 text-xs text-slate-500">{k.benchmark_label_ko ?? "비교지수"} {fmt(k.benchmark_value, k.format)}</div>}
            {(won ? won.rest : k.note_ko) && <div className="mt-1 text-xs leading-5 text-slate-500">{won ? won.rest : kpiNote(k.note_ko, doc)}</div>}
          </div>
        )
      })}
    </div>
  )
}
