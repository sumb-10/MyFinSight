import { useMemo, useState } from "react"
import { AlertTriangle, CheckCircle2, ChevronDown, ChevronRight, Info, MinusCircle, XCircle } from "lucide-react"
import { CartesianGrid, Line, LineChart, ReferenceLine, ResponsiveContainer, Tooltip, XAxis, YAxis } from "recharts"
import type { ReportDoc, ReportSummary, SummaryKpi } from "../../api/types"
import { colorOf, fmt, OTHER_COLOR } from "../../lib/format"
import { Disclosure, NOTICE_BOX } from "../../ui"
import { money } from "../profile/format"
import { CitedText } from "./blocks/blocks"
import { holdingColor } from "./colors"
import { benchOf, checkOf, kpiDisplay, MockTag, proposed, strategyInfoOf, toleranceExtraOf, volFromStructured } from "./proposedView"
import { DEFAULT_VOL_PREF, prefTerms, VOL_PREF_LABEL } from "../../lib/tendency"
import { HelpTip, Term } from "./terms"
import { analysisRisk, parseVolCheck, volObserved, type VolCheck, annualizedFromNote, r1Text, excessSentence, isShortWindow, kpiNote, minAnnualize, pairCagr, periodOf, pickSentence, shortWindowNote } from "./wording"

// 「개요」: 처음 보는 화면 (선택 전략·날짜 → 백테스트 핵심 성과 → 종목 구성 → 종목별 투자 금액). 숫자는 서버 summary 그대로이고, 여기서는 보여 주는 방식만 정한다.

type Tone = "green" | "amber" | "red" | "slate"
const TONE_BOX: Record<Tone, string> = { green: `${NOTICE_BOX.success} text-body`, amber: `${NOTICE_BOX.warning} text-body`, red: `${NOTICE_BOX.error} text-body`, slate: `${NOTICE_BOX.neutral} text-body` }  // 알림 상자: 테두리 없음 (2026-11-18)
const TONE_PILL: Record<Tone, string> = { green: "border-emerald-200 bg-emerald-50 text-emerald-800", amber: "border-amber-300 bg-amber-50 text-amber-900", red: "border-red-200 bg-red-50 text-red-800", slate: "border-slate-200 bg-slate-50 text-slate-700" }
const TONE_ICON: Record<Tone, React.ElementType> = { green: CheckCircle2, amber: AlertTriangle, red: XCircle, slate: MinusCircle }

/** 상태 표시: 색과 아이콘에 글자를 함께 둔다 (색만으로 구분하지 않는다). */
export function StatusPill({ tone, children, icon }: { tone: Tone; children: React.ReactNode; icon?: React.ElementType }) {
  const Icon = icon ?? TONE_ICON[tone]
  return <span className={`inline-flex shrink-0 items-center gap-1 rounded-full border px-2 py-0.5 text-xs font-semibold ${TONE_PILL[tone]}`}><Icon className="size-3.5" aria-hidden />{children}</span>
}

/** 요약 카드 틀: 질문형 제목 + 상세로 가는 링크. 내 투자조건 화면의 파트 카드와 같은 모양. */
function ResultCard({ id, q, desc, more, body = "space-y-4", tour, children }: { id: string; q: string; desc?: React.ReactNode; more?: [string, () => void]; body?: string; tour?: string; children: React.ReactNode }) {
  return (
    <section aria-labelledby={id} data-tour={tour} className="flex min-w-0 flex-col rounded-2xl border border-slate-300 bg-white shadow-sm">
      <header className="flex flex-wrap items-start justify-between gap-x-4 gap-y-1 rounded-t-2xl border-b border-slate-200 bg-slate-50 px-5 py-3 sm:px-6">
        <h3 id={id} className="min-w-0 flex-[1_1_15rem] text-base font-bold text-slate-950">{q}</h3>
        {more && <MoreLink label={more[0]} onClick={more[1]} />}
        {desc && <p className="w-full text-[13px] leading-5 text-slate-600">{desc}</p>}
      </header>
      <div className={`flex-1 px-5 py-5 sm:px-6 sm:py-6 ${body}`}>{children}</div>
    </section>
  )
}

export function MoreLink({ label, onClick }: { label: string; onClick: () => void }) {
  return <button type="button" onClick={onClick} className="inline-flex shrink-0 items-center gap-0.5 rounded-md text-xs font-semibold text-blue-700 hover:underline focus:outline-none focus:ring-2 focus:ring-blue-500">{label}<ChevronRight className="size-3.5" aria-hidden /></button>
}

const RULE_STATUS: Record<string, [Tone, string]> = { pass: ["green", "충족"], warn: ["amber", "주의"], fail: ["red", "미충족"], flag: ["amber", "허용 초과"], info: ["slate", "참고"] }
const ruleStatus = (s: string): [Tone, string] => RULE_STATUS[s] ?? ["slate", s]

export interface KeyAlert { tone: Tone; tag: string; text: string }
// 판정 주의 중 같은 조건의 규칙 결과(숫자 포함)가 따로 있으면 규칙 쪽만 둔다 (「비교지수 하회」와 「비교지수 대비: SPY 대비 초과 CAGR -4.6%p」가 둘 다 나왔다)
const SAME_RULE: [string, string][] = [["허용 낙폭 초과", "R1"], ["목표수익 미달", "R2"], ["비교지수 하회", "R3"]]
/** 미충족·주의 사항. 서버 판정(rules_ko·failed/warned·cautions·period_note)만 모은다.
 *  서버가 쉬운 문장(cautions_plain·rules_plain_ko, 2026-11-16)을 주면 그 문장을, 예전 리포트는 원래 문장을 쓴다. 같은 내용은 한 번만. */
export function keyAlerts(sm: ReportSummary): KeyAlert[] {
  const v = sm.validation
  const out: KeyAlert[] = []
  const rules = v.rules_ko ?? []
  const plainRule = v.rules_plain_ko ?? {}
  const flagged = new Set(rules.filter((r) => r.status === "fail" || r.status === "warn" || r.status === "flag").map((r) => r.rule))
  if (sm.verdict.period_note_ko) out.push({ tone: "amber", tag: "기간 안내", text: sm.verdict.period_note_ko })
  const cautions = sm.verdict.cautions_plain ?? (sm.verdict.cautions_ko ?? []).map((c) => ({ key: c, text: c }))
  for (const c of cautions) if (!SAME_RULE.some(([w, rule]) => c.key.startsWith(w) && flagged.has(rule))) out.push({ tone: "amber", tag: "주의", text: c.text })
  for (const r of rules) if (flagged.has(r.rule)) {
    const [tone, tag] = ruleStatus(r.status)
    if (plainRule[r.rule]) { out.push({ tone, tag, text: plainRule[r.rule] }); continue }
    const vc = r.rule === "R7" ? parseVolCheck(r.message_ko) : null
    out.push({ tone, tag, text: `${r.name_ko}: ${vc ? volSummary(vc) : prefTerms(r.message_ko)}` })
  }
  const named = new Set(rules.map((r) => r.name_ko))
  for (const r of v.failed_rules_ko) if (!named.has(r)) out.push({ tone: "red", tag: "미충족", text: r })
  for (const r of v.warned_rules_ko ?? []) if (!named.has(r)) out.push({ tone: "amber", tag: "주의", text: r })
  return out
}

export function AlertList({ items, label = "중요한 주의 사항" }: { items: KeyAlert[]; label?: string }) {
  if (!items.length) return null
  return (
    <ul aria-label={label} className="space-y-3.5">{/* 항목 사이를 넓게 (2026-11-19 사용자 요청: 글이 많아 덜 직관적) */}
      {/* 표시(주의·미충족 등) 아래에 문장 — 「참고」 상자와 같은 위→아래 배치 (2026-11-14 사용자 요청). 상자는 테두리 없는 알림 스타일 (2026-11-18 main) */}
      {items.map((a, i) => <li key={i} className={`flex flex-col items-start gap-2 rounded-control px-4 py-3.5 text-sm leading-6 ${TONE_BOX[a.tone]}`}><StatusPill tone={a.tone}>{a.tag}</StatusPill><span className="min-w-0 break-words"><CitedText text={a.text} /></span></li>)}
    </ul>
  )
}


/** 개요: 위에서 아래로 읽는 순서 — 결론 요약(선택된 전략·날짜) → 백테스트 핵심 성과(그래프 → 두 지표 → 해석) → 종목 구성과 투자 금액.
 *  한 줄에 여러 덩어리를 나란히 두지 않고, 그래프·결론은 카드 폭 전체를 쓴다. 판정(추천·주의)과 조건 점검은 첫 화면에 두지 않고 아래 자세한 분석에 둔다. 숫자는 서버 summary 그대로. */
export function Dashboard({ summary: sm, doc, onJump, paperReason }: { summary: ReportSummary; doc: ReportDoc; onJump: (sec: string, anchor?: string) => void; paperReason?: string | null }) {
  return (
    <section aria-labelledby="h-summary" className="space-y-4">
      <h2 id="h-summary" className="sr-only">개요</h2>
      <VerdictCard sm={sm} doc={doc} onMore={() => onJump("verdict")} paperReason={paperReason} />
      <PastCard sm={sm} doc={doc} onMore={() => onJump("performance")} />
      {sm.allocation ? <AllocationCard a={sm.allocation} doc={doc} onMore={() => onJump("construction")} /> : (
        <ResultCard id="q-alloc" q="종목 구성과 투자 금액" more={["구성 자세히 보기", () => onJump("construction")]}><p className="text-sm text-slate-600">배분 금액 정보가 없습니다.</p></ResultCard>
      )}
    </section>
  )
}

/** 개요 첫 카드 「결론 요약」: 다른 요약 카드와 같은 틀(제목 줄 오른쪽에 「왜 이 전략인가요?」).
 *  ① 선택된 전략 이름을 가장 크게 ② 전략 설명(서버·화면에 있는 짧은 설명)을 ? 밖에 한 줄로 ③ 날짜는 뜻이 보이는 한 문장으로 작게.
 *  판정·결론 문장과 주의 사항은 첫 화면에 두지 않는다 (아래 자세한 분석의 「종합 판단」·「주의 사항과 전제」). */
export function VerdictCard({ sm, doc, onMore, paperReason }: { sm: ReportSummary; doc: ReportDoc; onMore?: () => void; paperReason?: string | null }) {
  const h = doc.header
  const chosenId = sm.verdict.chosen_portfolio_id || h.chosen_portfolio_id
  const info = strategyInfoOf(doc, chosenId)
  const chosenName = sm.verdict.chosen_label_ko || h.chosen_label_ko
  return (
    <>
      <ResultCard id="q-verdict" tour="verdict" q="선택한 전략" more={onMore ? ["선택 이유 보기", onMore] : undefined}>
        {/* 날짜 문장(자료 기준일·백테스트 기간)은 두지 않는다 (2026-11-14 사용자 요청). 기간은 아래 「전체 기간 수익률」의 거래일 수와 자세한 분석에 있다 */}
        <div>
          {/* 카드 제목이 「선택한 전략」이라 같은 뜻의 작은 라벨 「선택된 전략」은 두지 않는다 (2026-11-16 사용자 요청) */}
          <p className="flex items-start gap-1.5 text-xl font-bold leading-7 text-slate-950"><span className="min-w-0">{chosenName}</span>{info && <HelpTip label={chosenName}>{info.help}</HelpTip>}</p>
          {info && <p className="mt-1.5 text-sm leading-6 text-slate-700">{info.short}</p>}
        </div>
      </ResultCard>
      {paperReason && !doc.tracking.eligible && <p className="text-[13px] text-slate-600">모의투자 시작 불가: {paperReason}</p>}
    </>
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

/** 카드 2: 종목별 투자 금액. 서버 배분 표의 종목별 금액을 먼저, 비중은 보조로.
 *  화면은 매수 수량·수수료·잔여 현금을 계산하지 않고 서버가 준 값만 쓴다. 보여 주는 구성은 서버 배분 하나(분석 기준일 「현재 구성」)뿐이다 —
 *  여러 구성을 고르는 버튼은 헷갈려서 두지 않는다. 제안 계약(proposed)에 예상 매수 주문이 있으면(서버 또는 목업) 함께 보여 준다. */
export function AllocationCard({ a, doc, onMore }: { a: NonNullable<ReportSummary["allocation"]>; doc?: ReportDoc; onMore?: () => void }) {
  const p = proposed(doc)
  const bases = p?.allocations ?? null
  const serverItems = useMemo(() => [...a.items].sort((x, y) => y.weight - x.weight), [a])
  const order = serverItems.map((x) => x.ticker)  // 색은 종목을 따른다: 구성을 바꿔도 같은 종목은 같은 색
  const items = serverItems
  const [all, setAll] = useState(false)
  const cashW = a.cash_weight
  const cash = cashW >= 0.0005 ? cashW : 0  // 0.0% 로 보일 만큼 작은 값(계산 잔차)은 현금 행을 만들지 않는다
  const cashAmt = bases ? { usd: bases.current.cash_usd, krw: bases.current.cash_krw } : p?.execution ? { usd: p.execution.totals.cash_target_usd, krw: p.execution.totals.cash_target_krw } : null  // 「예상 매수 주문」의 전략 현금 비중과 같은 값
  const usdOnly = !(a.fx_rate > 0) || Math.abs(a.fx_rate - 1) < 1e-9  // 환율 1.00 = USD 요청: 서버 '원화' 값이 USD 숫자와 같아 원화로 보이면 안 된다
  const base = a.amount_basis_ko ? null : requestedAmount(doc)  // 0원 시작: 요청 원문(0원)이 아니라 배분 계산에 쓴 첫 적립금을 기준금액으로
  const fee = (doc?.parameters?.backtest as { commission_bps?: number } | undefined)?.commission_bps
  const shown = all ? items : items.slice(0, TOP_N)
  const maxW = Math.max(cash, ...items.map((x) => x.weight), 1e-9)  // 막대 길이 기준: 전체 종목·현금 가운데 가장 큰 비중 (펼쳐도 기준이 바뀌지 않게)
  // 주식 수: 예상 매수 주문(서버 execution)이 있으면 금액 오른쪽 칸에 (2026-11-11 사용자 요청: 따로 접힌 표 대신 위 표와 통일)
  const ex = p?.execution ?? null
  const shares = new Map((ex?.items ?? []).map((x) => [x.ticker, x.shares]))
  const grid = ex ? ALLOC_GRID_SHARES : ALLOC_GRID
  const desc = <>{a.basis === "forward" && doc?.header.data_as_of ? `${doc.header.data_as_of} 기준` : a.basis_ko}{!usdOnly && a.fx_rate > 0 ? ` · 1 USD = ${a.fx_rate.toLocaleString("en-US", { maximumFractionDigits: 2 })}원` : ""}</>
  return (
    <ResultCard id="q-alloc" q="종목 구성과 투자 금액" more={onMore ? ["구성 자세히 보기", onMore] : undefined} desc={desc} body="space-y-6">
      <div data-tour="allocation-list" className="@container space-y-6">
      <dl className="flex flex-wrap gap-x-8 gap-y-2 text-sm">
        <div><dt className="text-xs font-semibold text-slate-500">투자 기준금액{a.amount_basis_ko ? ` · ${a.amount_basis_ko}` : ""}</dt><dd className="mt-0.5 text-lg font-bold tabular-nums text-slate-950">{base ?? fmt(a.initial_amount_usd, "usd")}{proposed(doc)?.structured?.requested_amount && <MockTag />}</dd></div>
        {base && <div><dt className="text-xs font-semibold text-slate-500">배분 계산에 쓴 금액</dt><dd className="mt-0.5 tabular-nums text-slate-700">{fmt(a.initial_amount_usd, "usd")}</dd></div>}
      </dl>
      {/* 종목별 줄: 모든 줄이 부모 격자의 같은 칸(subgrid)을 써서, 금액 글자 길이와 상관없이 막대가 같은 위치에서 같은 길이 기준으로 시작한다.
          막대는 가장 큰 비중을 꽉 찬 길이로 둔 하나의 기준이라 종목끼리 비율이 그대로 보인다. 비중(%)은 이름 바로 옆, 금액만 오른쪽 끝. */}
      <div>
        {/* 카드가 좁으면(48rem 미만, 모바일 등) 한 종목을 두 줄로: 이름 … 금액 / 비중·막대 … 주식 수. 넓으면 한 줄 표 */}
        <div aria-hidden className="flex justify-between border-b border-slate-200 pb-2 text-xs font-semibold text-slate-500 @3xl:hidden"><span>종목 · 투자 비중</span><span>{ex ? "목표 배분액 · 주식 수" : "목표 배분액"}</span></div>
        <div aria-hidden className={`hidden ${grid} border-b border-slate-200 pb-2 text-xs font-semibold text-slate-500`}><span>종목</span><span className="text-right">투자 비중</span><span /><span className="text-right">목표 배분액</span>{ex && <span className="inline-flex items-center justify-end">주식 수<MockTag /></span>}</div>
        <ul aria-label="종목별 목표 배분액" className={`${grid} divide-y divide-slate-100`}>
          {shown.map((x) => (
            <AllocRow key={x.ticker} color={holdingColor(x.ticker, order)} weight={x.weight} max={maxW} shares={ex ? sharesText(shares.get(x.ticker)) : undefined}
              name={<><span className="block truncate font-semibold text-slate-900" title={x.name}>{x.name && x.name !== x.ticker ? x.name : x.ticker}</span>{x.name && x.name !== x.ticker && <span className="block truncate text-xs text-slate-500">{x.ticker}</span>}</>}
              amount={<><span className="block whitespace-nowrap text-base font-bold tabular-nums text-slate-950">{usdOnly ? fmt(x.usd, "usd") : money(Math.round(x.krw), "KRW")}</span>{!usdOnly && <span className="block whitespace-nowrap text-xs tabular-nums text-slate-500">{fmt(x.usd, "usd")}</span>}</>} />
          ))}
          {cash > 0 && (
            <AllocRow color={OTHER_COLOR} weight={cash} max={maxW} shares={ex ? "" : undefined} name={<span className="block font-semibold text-slate-600">현금</span>}
              amount={cashAmt ? <><span className="block whitespace-nowrap text-base font-bold tabular-nums text-slate-700">{usdOnly ? fmt(cashAmt.usd, "usd") : money(cashAmt.krw, "KRW")}</span>{!usdOnly && <span className="block whitespace-nowrap text-xs tabular-nums text-slate-500">{fmt(cashAmt.usd, "usd")}</span>}</> : <span className="text-xs text-slate-600">금액 미제공</span>} />
          )}
        </ul>
      </div>
      </div>
      {items.length > TOP_N && <button type="button" aria-expanded={all} onClick={() => setAll((v) => !v)} className="flex items-center gap-1 text-sm font-semibold text-blue-700 hover:underline">{all ? "상위 종목만 보기" : `전체 종목 보기 (${items.length}개${cash ? " + 현금" : ""})`}<ChevronDown className={`size-4 transition-transform ${all ? "rotate-180" : ""}`} /></button>}
      {ex && <p className="text-xs leading-5 text-slate-500">주식 수: {ex.as_of} 주가 기준 · {SHARE_BASIS[ex.share_basis].short} · 수수료 {ex.commission_bps / 100}% · 매수 후 남는 현금 {usdOnly ? fmt(ex.totals.cash_left_usd, "usd") : money(ex.totals.cash_left_krw, "KRW")}</p>}
    </ResultCard>
  )
}

/** 카드 2 종목 줄의 칸: 종목 | 비중(%) | 막대 | 금액 (| 주식 수). 칸 너비는 글자와 상관없는 고정 최소값 + 비율이라 모든 줄(머리 줄 포함)이 같은 위치에 선다. */
const ALLOC_GRID = "@3xl:grid @3xl:grid-cols-[minmax(13rem,1.1fr)_4rem_minmax(9rem,1.4fr)_minmax(8.5rem,0.8fr)] @3xl:gap-x-5"
const ALLOC_GRID_SHARES = "@3xl:grid @3xl:grid-cols-[minmax(13rem,1.1fr)_4rem_minmax(8rem,1.3fr)_minmax(8.5rem,0.8fr)_minmax(5.5rem,0.5fr)] @3xl:gap-x-5"

/** 주식 수: 소수점 주식은 넷째 자리까지, 1주 단위는 정수. 값이 없으면 – */
const sharesText = (n: number | undefined) => (n == null ? "–" : `${n.toLocaleString("en-US", { maximumFractionDigits: 4 })}주`)

/** 종목 한 줄. 막대는 왼쪽 기준선에서 시작하고(끝만 둥글게), 길이는 가장 큰 비중 대비 비율이다. 값은 바로 옆 % 글자로 읽는다. shares 를 주면 금액 오른쪽에 주식 수 칸.
 *  넓은 카드: 부모 격자의 같은 칸(subgrid)에 한 줄. 좁은 카드: 「이름 … 금액」 / 「비중 막대 … 주식 수」 두 줄 (가로로 잘리지 않게). */
function AllocRow({ color, weight, max, name, amount, shares }: { color: string; weight: number; max: number; name: React.ReactNode; amount: React.ReactNode; shares?: string }) {
  const reset = "@3xl:col-auto @3xl:row-auto"
  return (
    <li className="grid grid-cols-[3.5rem_minmax(0,1fr)_auto] items-center gap-x-3 gap-y-1.5 py-3 @3xl:col-span-full @3xl:grid-cols-subgrid @3xl:gap-x-5 @3xl:gap-y-0">
      <div className={`col-span-2 row-start-1 flex min-w-0 items-center gap-2 ${reset}`}><span className="inline-block size-2.5 shrink-0 rounded-sm" style={{ background: color }} aria-hidden /><span className="min-w-0">{name}</span></div>
      <span className={`col-start-1 row-start-2 text-sm font-semibold tabular-nums text-slate-700 @3xl:text-right ${reset}`}>{fmt(weight, "pct1")}</span>
      <span className={`col-start-2 row-start-2 block h-2.5 border-l border-slate-300 ${reset}`} aria-hidden><span data-bar className="block h-full rounded-r" style={{ width: `${Math.min(100, (weight / max) * 100)}%`, minWidth: weight > 0 ? 2 : 0, background: color }} /></span>
      <div className={`col-start-3 row-start-1 min-w-0 text-right ${reset}`}>{amount}</div>
      {shares !== undefined && <span className={`col-start-3 row-start-2 whitespace-nowrap text-right text-sm font-semibold tabular-nums text-slate-800 ${reset}`}>{shares}</span>}
    </li>
  )
}

const SHARE_BASIS = {
  integer: { short: "1주 단위" },
  fractional: { short: "소수점" },
  mixed: { short: "미국 소수점 · 한국 1주 단위" },
} as const

const kpiTerm = (k: { id: string; label_ko: string }) => (k.id === "cagr" ? (/CAGR/.test(k.label_ko) ? "CAGR" : "기간 수익률") : k.id === "mdd" ? "최대낙폭" : k.id === "sharpe" ? "Sharpe" : null)

/** 그래프의 마지막 누적 수익률 (지수 시작 = 100). 값이 없으면 null. */
const lastIndexReturn = (doc: ReportDoc, id: string | undefined) => {
  const xs = id ? doc.datasets.series[id]?.index : undefined
  const v = xs?.length ? xs[xs.length - 1] : undefined
  return typeof v === "number" && Number.isFinite(v) ? v / 100 - 1 : null
}

/** 개요의 백테스트 핵심 성과: ① 누적 수익률 그래프(카드 폭 전체) ② 전체 기간 수익률 | 최대낙폭 (같은 크기 두 칸, 좁으면 한 줄씩) ③ 결과 해석.
 *  숫자는 서버 값 그대로다. 「전체 기간 수익률」: 짧은 창은 서버 KPI(기간 수익률), 긴 창은 서버가 연평균(CAGR)을 주므로 그래프 마지막 값(같은 서버 계열)을 쓰고 CAGR 은 아래에 함께 둔다.
 *  해석 문장은 서버 값(비교지수 대비 차이·최대낙폭·허용 손실)이 있을 때만 만든다. */
export function PastCard({ sm, doc, onMore, chart = true }: { sm: ReportSummary; doc: ReportDoc; onMore: () => void; chart?: boolean }) {
  const ret = sm.kpis.find((k) => k.id === "cagr")
  const ex = sm.kpis.find((k) => k.id === "excess")
  const mdd = sm.kpis.find((k) => k.id === "mdd")
  const r1 = sm.validation?.r1 ?? null
  const ids = sm.mini_series?.ids ?? [doc.header.chosen_portfolio_id]
  const showChart = chart && doc.datasets.dates.length > 1
  const chosen = sm.verdict.chosen_portfolio_id || doc.header.chosen_portfolio_id
  const benchId = ids.find((id) => id !== chosen && doc.datasets.series[id]?.kind === "benchmark") ?? ids.find((id) => id !== chosen)
  const short = ret ? (proposed(doc)?.structured?.kpi_meta?.cagr ? proposed(doc)!.structured!.kpi_meta!.cagr!.period === "total" : /^기간 수익률/.test(ret.label_ko)) : false
  // 긴 창: 서버 KPI 는 CAGR → 전체 기간 값은 그래프와 같은 계열의 마지막 값 (없으면 CAGR 그대로 보여 준다)
  const total = ret && !short ? lastIndexReturn(doc, chosen) : null
  const totalBench = total !== null ? lastIndexReturn(doc, benchId) : null
  const hasBench = !!ret && ret.benchmark_value != null
  const { ticker: bt } = benchOf(doc, ret?.benchmark_label_ko ?? mdd?.benchmark_label_ko)
  const bench = bt ?? ret?.benchmark_label_ko ?? "비교지수"
  const exAlone = !!ex && !hasBench  // 비교지수 값이 없으면 서버 차이 값을 따로 한 줄로 남긴다
  return (
    <ResultCard id="q-past" tour="past" q="과거 투자 결과" more={["과거 성과 자세히 보기", onMore]} body="space-y-9">
      {showChart && <CoreChart doc={doc} ids={ids} />}
      {(ret || mdd) && (
        <div className={`grid grid-cols-1 gap-5 ${ret && mdd ? "sm:grid-cols-2" : ""}`}>
          {ret && <ReturnKpi ret={ret} doc={doc} bench={bench} short={short} total={total} totalBench={totalBench} />}
          {mdd && <MddKpi k={mdd} doc={doc} bench={bench} />}
        </div>
      )}
      {exAlone && (() => { const n = kpiDisplay(doc, ex!); return <dl className="flex flex-wrap items-center justify-between gap-x-4 gap-y-1 rounded-xl border border-slate-200 px-5 py-3"><dt className="text-sm font-semibold text-slate-800">{n.name}</dt><dd className="text-xl font-bold tabular-nums text-slate-950">{fmt(ex!.value, ex!.format)}</dd></dl> })()}
      {!ret && !mdd && <p className="text-sm text-slate-600">요약 성과 지표가 없습니다.</p>}
      <PastReading ret={ret ?? null} ex={hasBench ? ex ?? null : null} mdd={mdd ?? null} r1={r1} bench={bench} doc={doc} short={short} />
    </ResultCard>
  )
}

/** 개요 그래프: 누적 수익률(시작 = 0%). 서버 datasets 의 index 계열(시작 = 100)을 그대로 쓰고 축 글자만 % 로 읽는다. 카드 폭 전체를 쓰고, 아래에 계열별 마지막 값. */
function CoreChart({ doc, ids }: { doc: ReportDoc; ids: string[] }) {
  const rows = useMemo(() => doc.datasets.dates.map((d, i) => { const r: Record<string, number | string> = { date: d }; for (const id of ids) { const v = doc.datasets.series[id]?.index?.[i]; if (typeof v === "number") r[id] = v } return r }), [doc, ids])
  const last = rows[rows.length - 1] ?? {}
  const ticks = useMemo(() => returnTicks(rows, ids), [rows, ids])
  const label = (id: string) => doc.datasets.series[id]?.label_ko ?? id
  return (
    <figure className="flex min-w-0 flex-col">
      <figcaption className="flex flex-wrap items-baseline justify-between gap-x-3 gap-y-0.5"><span className="text-base font-bold text-slate-950">누적 수익률</span><span className="text-xs text-slate-500">시작일 0% 기준</span></figcaption>
      <div className="mt-4 h-60 min-w-0 sm:h-72" role="img" aria-label="누적 수익률 그래프">
        <ResponsiveContainer width="100%" height="100%">
          <LineChart data={rows} margin={{ top: 8, right: 12, bottom: 4, left: 0 }}>
            <CartesianGrid stroke="#e2e8f0" vertical={false} />
            <XAxis dataKey="date" tick={{ fontSize: 12 }} minTickGap={56} tickMargin={6} />
            <YAxis tickFormatter={(v: number) => `${Math.round(v - 100)}%`} tick={{ fontSize: 12 }} width={52} {...(ticks.length ? { ticks, domain: [ticks[0], ticks[ticks.length - 1]] } : { domain: ["auto", "auto"] })} />
            <ReferenceLine y={100} stroke="#94a3b8" strokeDasharray="4 4" />
            <Tooltip formatter={(v: unknown, n: unknown) => [indexReturn(v as number), label(String(n))]} labelFormatter={(l) => String(l)} />
            {ids.map((id) => <Line key={id} type="monotone" dataKey={id} stroke={colorOf(id, ids)} dot={false} strokeWidth={id === doc.header.chosen_portfolio_id ? 2.5 : 1.5} isAnimationActive={false} />)}
          </LineChart>
        </ResponsiveContainer>
      </div>
      <ul aria-label="그래프 범례" className="mt-4 flex flex-wrap gap-x-10 gap-y-2 text-base text-slate-700">{/* 범례 글자·색 표시를 크게 (2026-11-14 사용자 요청) */}{ids.map((id) => <li key={id} className="flex min-w-0 items-center gap-2.5"><span className="inline-block size-3.5 shrink-0 rounded-full" style={{ background: colorOf(id, ids) }} aria-hidden /><span className="min-w-0 truncate" title={label(id)}>{label(id)}</span><b className="tabular-nums text-slate-900" title={`시작 = 100 기준 ${fmt(last[id] as number, "index")}`}>{indexReturn(last[id] as number)}</b></li>)}</ul>
    </figure>
  )
}

const KPI_BOX = "@container flex min-w-0 flex-col rounded-xl border border-slate-200 px-5 py-5"
const KPI_CELL = "flex items-baseline justify-between gap-3 @xs:block"
const KPI_VALUE = "shrink-0 text-3xl font-bold tabular-nums text-slate-950 @xs:mt-1 @xs:block"

/** 두 값(선택 전략 | 비교지수)을 같은 모양·같은 크기로. 칸이 좁으면(20rem 미만) 「이름 … 값」 두 줄로 바뀐다. */
function PairValues({ mine, other, otherLabel, mineSub, otherSub }: { mine: string; other: string | null; otherLabel: React.ReactNode; mineSub?: React.ReactNode; otherSub?: React.ReactNode }) {
  const sub = (x: React.ReactNode) => x ? <dd className="mt-0.5 whitespace-nowrap text-xs tabular-nums text-slate-500 @xs:block">{x}</dd> : null
  return (
    <dl className={`mt-4 grid grid-cols-1 gap-y-2 ${other !== null ? "@xs:grid-cols-2 @xs:gap-x-6" : ""}`}>
      <div><div className={KPI_CELL}><dt className="flex items-center gap-1.5 text-sm font-semibold text-blue-700"><span className="size-2 shrink-0 rounded-full bg-blue-600" aria-hidden />선택 전략</dt><dd className={KPI_VALUE}>{mine}</dd></div>{sub(mineSub)}</div>
      {other !== null && <div className="@xs:border-l @xs:border-slate-200 @xs:pl-6"><div className={KPI_CELL}><dt className="flex min-w-0 items-center gap-1 text-sm font-semibold text-slate-600">{otherLabel}</dt><dd className={KPI_VALUE}>{other}</dd></div>{sub(otherSub)}</div>}
    </dl>
  )
}

/** 비교지수 이름 + ? 도움말 (무엇이고 어떻게 계산했는지). */
function BenchLabel({ doc, bench, label }: { doc: ReportDoc; bench: string; label?: string | null }) {
  const { ticker: bt, desc: etf } = benchOf(doc, label)
  return (
    <>
      <span className="min-w-0">비교지수 · <span className="whitespace-nowrap">{bench}</span></span>
      <HelpTip label={`비교지수 · ${bench}`}>
        {etf && <span className="block">{bench}는 {etf}입니다.</span>}
        <span className="block">{bt ? "선택 전략과 같은 날, 같은 금액을 넣고 팔지 않고 계속 보유했다고 가정해 계산했습니다 (매수 후 보유 · 동일 적립)." : "선택 전략과 같은 기간·같은 납입 조건으로 계산한 비교 기준입니다."}</span>
      </HelpTip>
    </>
  )
}

/** 지표 1: 전체 기간 수익률. 짧은 창은 서버 기간 수익률, 긴 창은 그래프 마지막 값(+ 서버 CAGR 한 줄). 그래프 값이 없으면 서버 KPI 이름(CAGR) 그대로. */
function ReturnKpi({ ret, doc, bench, short, total, totalBench }: { ret: SummaryKpi; doc: ReportDoc; bench: string; short: boolean; total: number | null; totalBench: number | null }) {
  const n = kpiDisplay(doc, ret)
  const meta = proposed(doc)?.structured?.kpi_meta?.cagr
  const useTotal = total !== null
  const name = useTotal ? "전체 기간 수익률" : n.name
  const term = useTotal ? "기간 수익률" : kpiTerm(ret)
  // 아래 줄은 「○○거래일 기준」만 (2026-11-14 사용자 요청: 「1년 평균이 아닌 …」 같은 설명은 두지 않는다)
  const days = periodOf(doc).window_days ?? periodOf(doc).trading_days ?? null
  const sub = short ? n.sub ?? (days ? `${days}거래일 기준` : null) : useTotal && days ? `${days}거래일 기준` : null
  const mine = useTotal ? fmt(total, "pct") : fmt(ret.value, ret.format)
  const other = useTotal ? (totalBench !== null ? fmt(totalBench, "pct") : null) : ret.benchmark_value != null ? fmt(ret.benchmark_value, ret.format) : null
  return (
    <section aria-label={`${name} 비교`} className={KPI_BOX}>
      <h4 data-tour="term-help" className="flex items-center gap-1 text-base font-bold text-slate-950">{name}{term && <Term t={term} label={name} />}{(meta || proposed(doc)?.structured?.benchmark) && <MockTag />}</h4>
      {sub && <p className="text-[13px] leading-5 text-slate-500">{sub}</p>}
      {/* 긴 창: 서버의 연평균 수익률(CAGR)은 각 숫자 바로 아래 작은 줄로 (따로 한 줄을 더 두면 옆 최대낙폭 칸 아래가 비어 보인다) */}
      <PairValues mine={mine} other={other} otherLabel={<BenchLabel doc={doc} bench={bench} label={ret.benchmark_label_ko} />}
        mineSub={useTotal ? <>연평균(CAGR) {fmt(ret.value, ret.format)}</> : undefined} otherSub={useTotal && ret.benchmark_value != null ? <>연평균(CAGR) {fmt(ret.benchmark_value, ret.format)}</> : undefined} />
    </section>
  )
}

/** 지표 2: 최대낙폭. 선택 전략 | 비교지수 (서버 값). 허용 손실과의 비교는 아래 「결과 읽기」에서. */
function MddKpi({ k, doc, bench }: { k: SummaryKpi; doc: ReportDoc; bench: string }) {
  const n = kpiDisplay(doc, k)
  return (
    <section aria-label={n.name} className={KPI_BOX}>
      <h4 className="flex items-center gap-1 text-base font-bold text-slate-950">{n.name}<Term t="최대낙폭" label={n.name} />{proposed(doc)?.structured?.kpi_meta?.[k.id] && <MockTag />}</h4>
      <p className="text-[13px] leading-5 text-slate-500">가장 높았던 때와 비교해 가장 많이 떨어졌던 비율</p>
      <PairValues mine={fmt(k.value, k.format)} other={k.benchmark_value != null ? fmt(k.benchmark_value, k.format) : null} otherLabel={<BenchLabel doc={doc} bench={bench} label={k.benchmark_label_ko} />} />
    </section>
  )
}

/** 해석 (세 번째 줄): 서버 값으로만 만든 짧은 문장. 과거 계산 결과임을 문장 시제로 드러내고, 미래 수익을 말하지 않는다. */
function PastReading({ ret, ex, mdd, r1, bench, doc, short }: { ret: SummaryKpi | null; ex: SummaryKpi | null; mdd: SummaryKpi | null; r1: ReportSummary["validation"]["r1"] | null; bench: string; doc: ReportDoc; short: boolean }) {
  // 차이가 어느 수익률의 차이인지: 서버 excess 이름 「비교지수(SPY) 대비 (기간)」 = 기간 수익률 차이, 「비교지수(SPY) 대비」 = CAGR 차이
  const exSubject = ex ? (/\(기간\)$/.test(ex.label_ko) ? "전체 기간 수익률이" : /^비교지수\(.+?\) 대비$/.test(ex.label_ko) ? "연평균 수익률(CAGR)이" : null) : null
  const exText = ex ? excessSentence(ex.value, bench, exSubject) : null
  const fall = mdd && mdd.value != null && Number.isFinite(mdd.value) ? fmt(Math.abs(mdd.value), "pct1") : null
  const benchFall = mdd?.benchmark_value != null ? fmt(Math.abs(mdd.benchmark_value), "pct1") : null
  const within = r1 && Number.isFinite(r1.mdd) && Number.isFinite(r1.tolerance) ? Math.abs(r1.mdd) <= Math.abs(r1.tolerance) + 1e-9 : null
  const lines = [
    exText,
    fall ? `이 기간 중 가장 높았던 때보다 최대 ${fall}까지 떨어진 적이 있었습니다${benchFall ? ` (같은 기간 ${bench}는 최대 ${benchFall})` : ""}` : null,
    within === null ? null : within ? `이 하락폭은 내가 정한 허용 손실 ${fmt(Math.abs(r1!.tolerance), "pct1")} 안이었습니다` : `이 하락폭은 내가 정한 허용 손실 ${fmt(Math.abs(r1!.tolerance), "pct1")}보다 컸습니다`,
  ].filter((x): x is string => !!x)
  if (!lines.length && !(short && ret)) return null
  // 처음에는 접어 두고, 누르면 펼친다 (2026-11-14 사용자 요청)
  return (
    <section aria-label="결과 해석">
      <Disclosure size="sm" title="결과 읽기" summary={lines.length ? `${lines.length}가지` : undefined}>
        {lines.length > 0 && <ul className="space-y-1.5">{lines.map((t) => <li key={t} className="flex gap-2 text-sm leading-6 text-slate-800"><span className="mt-2.5 size-1 shrink-0 rounded-full bg-slate-500" aria-hidden /><span className="min-w-0">{t}</span></li>)}</ul>}
        {short && ret && <ShortWindowNotice ret={ret} doc={doc} />}
      </Disclosure>
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
    <p className="mt-3 border-t border-slate-200 pt-3 text-[13px] leading-5 text-slate-600">
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

/** 누적 수익률 축 눈금: 0% 를 지나는 보기 좋은 간격(5·10·20·25·50·100…%p)으로 6개 이하. 값은 지수(시작 = 100) 단위. 값이 없으면 빈 배열(자동 눈금). */
export function returnTicks(rows: Record<string, number | string>[], ids: string[]): number[] {
  let lo = 100, hi = 100, seen = false
  for (const r of rows) for (const id of ids) { const v = r[id]; if (typeof v === "number" && Number.isFinite(v)) { lo = Math.min(lo, v); hi = Math.max(hi, v); seen = true } }
  if (!seen) return []
  const span = Math.max(hi - lo, 1)
  const step = [5, 10, 20, 25, 50, 100, 200, 250, 500, 1000, 2000, 2500, 5000].find((s) => span / s <= 5) ?? Math.ceil(span / 5000) * 1000
  const out: number[] = []
  for (let v = 100 + Math.floor((lo - 100) / step) * step; v <= 100 + Math.ceil((hi - 100) / step) * step + 1e-9; v += step) out.push(v)
  return out
}

/** 지수(시작 = 100) → 누적 수익률 표기: 266.0 → 「+166.0%」. 값이 없으면 「—」. */
export const indexReturn = (v: number | undefined | null) => (typeof v === "number" && Number.isFinite(v) ? `${v >= 100 ? "+" : "−"}${Math.abs(v - 100).toFixed(1)}%` : "—")

const RULE_NAME: Record<string, string> = { 최대낙폭: "허용 손실 vs 과거 최대 하락폭", 목표수익: "목표 수익률", "비교지수 대비": "비교지수 대비 성과" }
const LEVEL_KO: Record<string, string> = { hard: "필수", flag: "표시" }

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
  // 변동성 외의 참고 문장(낙폭 비교·목표 수익률 보류·비중 쏠림)은 「7. 주의 사항과 전제 → 참고」에 쉬운 문장으로 있어 여기서는 보이지 않는다 (2026-11-16 사용자 요청: 4번 참고 삭제)
  const volNotes = v7 ? [] : notes.filter((x) => x.vc)
  const rp = proposed(doc)?.risk_profile
  const ranking = proposed(doc)?.explanations?.ranking
  // 허용 손실은 아래 막대에 이미 보이므로 「손실 감내 수준 X%」는 다시 쓰지 않고, 그 뒤에 붙은 다른 정보(낙폭 맞춤안 목표 등)만 막대 아래에 남긴다. 막대가 없으면 원문 그대로 맨 아래에.
  const barShown = !!v.r1 && (rules.length === 0 || rules.some((r) => r.rule === "R1"))
  const tolExtra = barShown ? toleranceExtraOf(doc, v.tolerance_note_ko) : ""
  return (
    <div className="space-y-4">
      {rules.length > 0 ? (
        <ul className="space-y-3" aria-label="투자 조건 충족 여부">
          {rules.filter((r) => !(v7 && r.rule === "R7")).map((r) => {
            const [tone, label] = ruleStatus(r.status)
            const ex = r.rule === "R3" ? (s3?.value != null ? { bench, value: `${s3.value > 0 ? "+" : s3.value < 0 ? "-" : ""}${(Math.abs(s3.value) * 100).toFixed(1)}%p` } : excessCagr(r.message_ko)) : null
            const vc = r.rule === "R7" ? parseVolCheck(r.message_ko) : null
            const r1 = r.rule === "R1" ? (s1?.value != null && s1.threshold != null ? { main: `최대낙폭 ${(s1.value * 100).toFixed(1)}% vs 허용 ${(s1.threshold * 100).toFixed(1)}%${s1.status === "pass" ? "" : ` — 허용보다 ${((s1.value - s1.threshold) * 100).toFixed(1)}%p 큼`}`, bench: `같은 기간 ${bench} 매수 후 보유·동일 적립 시 ${((s1.benchmark_value ?? 0) * 100).toFixed(1)}%` } : r1Text(r.message_ko)) : null
            if (vc) return <VolatilityCheck key={r.rule} c={vc} status={r.status} level={LEVEL_KO[r.level]} risk={risk} doc={doc} benchName={bench} />
            return (
              <li key={r.rule} className="rounded-xl border border-slate-200 p-4 sm:p-5">
                <div className="flex flex-wrap items-center justify-between gap-2"><span className="inline-flex items-center gap-1 text-base font-semibold text-slate-900">{RULE_NAME[r.name_ko] ?? r.name_ko}{r.rule === "R1" && <Term t="최대낙폭" />}{LEVEL_KO[r.level] && <span className="ml-0.5 text-xs font-normal text-slate-500">{LEVEL_KO[r.level]}</span>}{checkOf(doc, r.rule) && <MockTag />}</span><StatusPill tone={tone}>{label}</StatusPill></div>
                {ex ? (
                  <div className="mt-3">
                    <p className="flex items-center gap-1 text-sm font-medium text-slate-600">{ex.bench} 대비 연평균 수익률(CAGR) 차이<Term t="CAGR" /></p>
                    <p className="mt-1 text-2xl font-bold tabular-nums text-slate-950">{ex.value}</p>
                    {doc && isShortWindow(doc) && <p className="mt-2 text-sm leading-6 text-slate-600">{shortWindowNote(doc)}</p>}
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
          {volNotes.map((x, i) => <VolatilityCheck key={`vn${i}`} c={x.vc!} status="info" risk={risk} doc={doc} benchName={bench} />)}
          {v7 && s7 && <VolatilityCheck c={v7} status={s7.status} level={LEVEL_KO[s7.level]} risk={risk} doc={doc} mock benchName={bench} />}
        </ul>
      ) : total > 0 ? (
        <div className="flex flex-wrap gap-2"><StatusPill tone="green">충족 {v.n_pass}</StatusPill><StatusPill tone="amber">주의 {v.n_warn}</StatusPill><StatusPill tone="red">미충족 {v.n_fail}</StatusPill></div>
      ) : <p className="text-sm text-slate-600">투자 조건 충족 여부를 확인한 결과가 없습니다.</p>}
      {!rules.length && v.r1 && <div><DrawdownBar r1={v.r1} tone={ruleStatus(v.r1.status)[0]} />{tolExtra && <p className="mt-3 text-sm leading-6 text-slate-600">{tolExtra}</p>}</div>}
      {extraFail.length > 0 && <div><p className="text-sm font-semibold text-red-700">미충족 규칙</p><ul className="mt-1.5 list-disc space-y-1 pl-5 text-sm leading-6 text-slate-700">{extraFail.map((r) => <li key={r}>{r}</li>)}</ul></div>}
      {extraWarn.length > 0 && <div><p className="text-sm font-semibold text-amber-800">주의 규칙</p><ul className="mt-1.5 list-disc space-y-1 pl-5 text-sm leading-6 text-slate-700">{extraWarn.map((r) => <li key={r}>{r}</li>)}</ul></div>}
      {!rules.length && volNotes.length > 0 && <ul className="space-y-3">{volNotes.map((x, i) => <VolatilityCheck key={i} c={x.vc!} status="info" risk={risk} doc={doc} benchName={bench} />)}</ul>}
      {(rules.length > 0 || total > 0) && (
        // <p> 안에 물음표 설명의 번호 목록(<ol>)이 들어가 HTML 구조 경고가 났다 → 같은 모양의 <div> (2026-11-16 검증 중 발견)
        <div className="pt-1 text-sm leading-6 text-slate-600">
          {pickSentence(v.n_candidates ?? (total || null), bench, verdict)}<Term t="투자 구성안" label="투자 구성안이란?" />
          {ranking && <span className="ml-1.5 inline-flex items-center text-xs text-slate-500">순위 기준 전체<HelpTip label="추천 순위 기준 전체"><ol className="list-decimal space-y-1 pl-4">{ranking.map((x) => <li key={x.key}><b className="font-semibold text-slate-800">{x.label_ko}</b> — {x.desc_ko}</li>)}</ol></HelpTip><MockTag /></span>}
          {!rules.length && total > 0 && <span className="block text-slate-500">포트폴리오 {total}개 중 충족 {v.n_pass} · 주의 {v.n_warn} · 미충족 {v.n_fail}</span>}
        </div>
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
/** 변동성 기준 이름 옆 ? 도움말: 이 리포트에서 실제로 적용한 기준만 (판정 결과는 쓰지 않는다 — 카드 위 결과 문장·상태 표시와 구분, 2026-11-16 사용자 요청). */
export function volStandardHelp(c: VolCheck, benchName = "비교지수"): string {
  const m = c.mult ? Number(c.mult) : null
  if (c.kind === "nocap") return "수익률이 얼마나 흔들렸는지는 보여주며, 변동성 상한을 정해 충족 여부를 판단하는 절차는 없습니다."
  if (c.kind === "absolute") return `비교지수 변동성 자료를 쓰지 않고, 고정된 기준값을 적용했습니다. 이 분석에서는 연변동성 ${c.band ?? "-"} 이하를 기준으로 정했습니다.`
  if (m === 1) return `전략의 수익률이 비교지수보다 더 크게 흔들렸는지 확인합니다. 이 분석에서는 비교지수와 같은 수준까지 허용합니다.${c.bench ? ` ${benchName}의 연변동성 ${c.bench}를 그대로 기준으로 정했습니다.` : ""}`
  const verb = m !== null && m < 1 ? "작게" : "크게"
  return `전략의 수익률이 비교지수보다 얼마나 더 ${verb} 흔들렸는지 확인합니다.${c.bench && c.mult && c.band ? ` 이 분석에서는 ${benchName}의 연변동성 ${c.bench}에 ${c.mult}을 곱해 ${c.band}를 기준으로 정했습니다.` : ""}`
}

function VolatilityCheck({ c, status, level, risk, doc, mock = false, benchName }: { c: VolCheck; status: string; level?: string; risk: ReturnType<typeof analysisRisk> | null; doc?: ReportDoc; mock?: boolean; benchName?: string }) {
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
          {pref && <span className="block">이번 분석의 변동성 기준: <span className="whitespace-nowrap"><b className="font-semibold text-slate-800">{VOL_PREF_LABEL[pref]}</b><span className="ml-0.5 inline-flex h-[1lh] items-center align-top"><HelpTip label={VOL_PREF_LABEL[pref]}>{volStandardHelp(c, benchName)}</HelpTip></span></span></span>}
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
  if (n.disabled) return <div className="rounded-box bg-sunken px-4 py-3 text-14 text-body"><b className="font-semibold text-main">뉴스 반영 효과: </b>{n.reason_ko ?? "이 분석에서는 표시할 수 없습니다"}</div>
  const retKo = n.annualized_reliable === false ? "연 환산 수익률 (참고)" : "연평균 수익률(CAGR)"
  const rows: [string, string, string][] = [[retKo, fmt(n.bl_cagr, "pct"), fmt(n.base_cagr, "pct")], ["최대 하락폭", fmt(n.bl_mdd, "pct"), fmt(n.base_mdd, "pct")], ["비교지수 대비 (연)", fmt(n.bl_excess_cagr, "pp"), fmt(n.base_excess_cagr, "pp")]]
  return (
    <div className="rounded-2xl border border-slate-200 bg-white p-4 sm:p-5">
      <div className="overflow-x-auto">
        <table className="w-full min-w-[420px] text-sm">
          <thead><tr className="border-b border-slate-200 text-left text-xs text-slate-500"><th className="py-2 pr-3 font-semibold">항목</th><th className="py-2 pr-3 text-right font-semibold">뉴스 반영<span className="block font-normal">{n.bl_label_ko ?? "뉴스 반영 구성"}</span></th><th className="py-2 text-right font-semibold">기준 비중<span className="block font-normal">{n.base_label_ko ?? "기준 비중"}</span></th></tr></thead>
          <tbody>{rows.map(([k, a, b]) => <tr key={k} className="border-b border-slate-100"><td className="py-2 pr-3 text-slate-700">{k}</td><td className="py-2 pr-3 text-right font-semibold tabular-nums text-slate-950">{a}</td><td className="py-2 text-right tabular-nums text-slate-700">{b}</td></tr>)}</tbody>
        </table>
      </div>
      <p className="mt-3 text-sm text-slate-800"><b>{retKo} 차이</b> <span className="text-base font-bold tabular-nums">{n.diff_cagr == null ? "–" : fmt(n.diff_cagr, "pp")}</span> <span className="text-xs text-slate-500">(뉴스 반영 − 기준 비중)</span></p>
      <Disclosure size="sm" className="mt-3" title="뉴스 분석 자세히 보기">
        <dl className="grid grid-cols-1 gap-3 text-xs sm:grid-cols-2">
          <div><dt className="flex items-center gap-1 text-slate-500">투자 의견 적중률 (다음 리밸런싱까지)<Term t="투자 의견(뷰)" /></dt><dd className="mt-0.5 text-base font-semibold tabular-nums">{n.hit_next_rb == null ? "–" : fmt(n.hit_next_rb, "pct1")}</dd><dd className="text-[11px] text-slate-500">투자 의견으로 포트폴리오 비중을 바꾼 기간 안에서</dd></div>
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
  cagr: "백테스트 기간 전체의 수익률입니다.",
  excess: "같은 기간 비교지수보다 수익률이 얼마나 높거나 낮았는지를 나타냅니다.",
  mdd: "기간 중 가장 높았던 평가금액에서 가장 크게 떨어진 비율입니다. 작을수록 덜 흔들렸다는 뜻입니다.",
  sharpe: "흔들림(변동성)에 비해 수익을 얼마나 냈는지 봅니다. 높을수록 좋습니다.",
  view_hit: "분석 모델이 뉴스·공시를 읽고 제안한 투자 의견이 실제 결과와 맞은 비율입니다.",
}

/** 문서의 모든 KPI (doc.kpis) 에 요약의 비교지수 값을 붙인다. 요약에만 있는 KPI 도 뒤에 남긴다 — 요약에서 빠진 지표가 화면에서 사라지지 않게. */
export function allKpis(doc: ReportDoc): SummaryKpi[] {
  const sm = new Map((doc.summary?.kpis ?? []).map((k) => [k.id, k]))
  const base = doc.kpis.map((k) => ({ ...k, benchmark_value: sm.get(k.id)?.benchmark_value ?? null, benchmark_label_ko: sm.get(k.id)?.benchmark_label_ko ?? null }))
  const ids = new Set(base.map((k) => k.id))
  return [...base, ...(doc.summary?.kpis ?? []).filter((k) => !ids.has(k.id))]
}

/** 「성과 지표 전체」 비교 표: 지표를 줄로, 「선택 전략 | 비교지수」를 칸으로 (2026-11-14 사용자 요청: 카드마다 같은 비교지수 이름·긴 보조 문장이 반복돼 글자가 많았다).
 *  비교지수 이름은 칸 제목에 한 번, 지표 설명과 서버 보조 문장(환율 기준·무위험수익률·연 환산 참고 등)은 지표 이름 옆 ? 안으로. 숫자는 서버 그대로. */
export function KpiTable({ kpis, doc }: { kpis: SummaryKpi[]; doc?: ReportDoc }) {
  const fv = proposed(doc)?.structured?.final_value
  const benchLabel = kpis.find((k) => k.benchmark_label_ko)?.benchmark_label_ko ?? null
  const { ticker: bt } = benchOf(doc, benchLabel)
  const hasBench = kpis.some((k) => k.benchmark_value != null)
  // 비교지수 대비 차이(excess)는 따로 한 줄을 두지 않고 수익률 줄의 선택 전략 값 아래에 — 수익률 줄에 비교지수 값이 있을 때만 (없으면 원래대로 한 줄)
  const ex = kpis.find((k) => k.id === "excess")
  const ret = kpis.find((k) => k.id === "cagr" && k.benchmark_value != null)
  const foldEx = !!(ex && ret && ex.value != null)
  const rows = foldEx ? kpis.filter((k) => k !== ex) : kpis
  // 비교지수 최종 평가금액의 원화: 서버는 USD만 준다 → 「종목 구성과 투자 금액」 카드와 같은 분석 기준일 환율(서버 값)로 환산 (2026-11-14 사용자 요청).
  // 환율이 없거나 1(USD 요청)이면 하지 않는다. 선택 전략 원화는 서버 값 그대로.
  const fxr = doc?.summary?.allocation?.fx_rate ?? 0
  const fx = fxr > 0 && Math.abs(fxr - 1) > 1e-9 ? fxr : null
  return (
    <div className="overflow-x-auto rounded-xl border border-slate-200">
      {/* 좁은 화면: 줄마다 지표 이름을 위 한 줄로, 그 아래에 선택 전략·비교지수 값을 두 칸으로 (표 칸이 잘리지 않게) */}
      <table className="block w-full text-sm sm:table">
        <thead className="block sm:table-header-group">
          <tr className={`grid border-b border-slate-200 bg-slate-50 text-left text-xs font-semibold text-slate-500 sm:table-row ${hasBench ? "grid-cols-2" : "grid-cols-1"}`}>
            <th className="hidden px-4 py-2.5 sm:table-cell">지표</th>
            <th className="px-4 py-2.5 text-right"><span className="inline-flex items-center gap-1.5"><span className="size-2 rounded-full bg-blue-600" aria-hidden />선택 전략</span></th>
            {hasBench && <th className="px-4 py-2.5 text-right"><span className="inline-flex items-center gap-1">비교지수 {bt ?? ""}{benchLabel && <HelpTip label="비교지수">{benchLabel}: 선택 전략과 같은 날, 같은 금액을 넣고 팔지 않고 계속 보유했다고 가정한 결과입니다.</HelpTip>}</span></th>}
          </tr>
        </thead>
        <tbody className="block divide-y divide-slate-100 sm:table-row-group">
          {rows.map((k) => {
            const n = kpiDisplay(doc, k)
            const won = k.id === "final_value" ? (fv ? { krw: fv.krw, rest: (k.note_ko ?? "").replace(/^약 [\d,]+원(?: · )?/, "") } : krwFromNote(k.note_ko)) : null
            const note = won ? won.rest : kpiNote(k.note_ko, doc)
            const principal = won?.rest ? /^투입 원금 (.+?)(?: — .*)?$/.exec(won.rest)?.[1] ?? null : null  // 「투입 원금 17,538 USD(약 23,568,050원) — …」의 금액
            const tol = k.id === "mdd" ? /손실 감내 수준 ([\d.]+%)/.exec(k.note_ko ?? "")?.[1] ?? null : null  // 허용 손실은 값 아래에 짧게
            const exHere = foldEx && k === ret ? ex! : null
            const empty = k.value == null && !won && !!note  // 값이 없으면 「–」 대신 서버 이유 문장(예: 이 포트폴리오에는 뷰가 없습니다)을 칸에 그대로
            const benchKrw = won && fx && k.benchmark_value != null ? Math.round(k.benchmark_value * fx) : null
            const help = [KPI_HELP[k.id], n.sub, note && !principal && !empty ? note : principal ? won!.rest : null, exHere ? `${KPI_HELP.excess}${exHere.note_ko ? ` (${exHere.note_ko})` : ""}` : null, benchKrw != null ? `비교지수 원화 금액은 분석한 날의 환율(1 USD = ${fx!.toLocaleString("en-US", { maximumFractionDigits: 2 })}원)로 환산한 값입니다.` : null].filter(Boolean)
            return (
              <tr key={k.id} className={`grid align-top sm:table-row ${hasBench ? "grid-cols-2" : "grid-cols-1"}`}>
                <th scope="row" className={`px-4 pb-1 pt-3 text-left font-medium text-slate-800 sm:table-cell sm:pb-3 ${hasBench ? "col-span-2" : ""}`}>
                  <span className="inline-flex items-center gap-1">{n.name}{(proposed(doc)?.structured?.kpi_meta?.[k.id] || (k.id === "final_value" && fv)) && <MockTag />}{help.length > 0 && <HelpTip label={n.name}>{help.map((x, i) => <span key={i} className="block">{x}</span>)}</HelpTip>}</span>
                  {principal && <span className="mt-0.5 block text-xs font-normal text-slate-500">투입 원금 {principal}</span>}
                </th>
                <td className="whitespace-nowrap px-4 pb-3 pt-1 text-right sm:table-cell sm:pt-3">
                  {empty ? <span className="block whitespace-normal text-xs leading-5 text-slate-500">{note}</span> : <span className="block text-base font-bold tabular-nums text-slate-950">{won ? `약 ${money(won.krw, "KRW")}` : fmt(k.value, k.format)}</span>}
                  {won && <span className="block text-xs tabular-nums text-slate-500">{fmt(k.value, k.format)}</span>}
                  {exHere && <span className={`block text-xs font-semibold tabular-nums ${(exHere.value ?? 0) > 0 ? "text-emerald-700" : (exHere.value ?? 0) < 0 ? "text-red-700" : "text-slate-500"}`}>{bt ?? "비교지수"}보다 {fmt(exHere.value, exHere.format)}</span>}
                  {tol && <span className="block text-xs text-slate-500">허용 손실 {tol}</span>}
                </td>
                {hasBench && <td className="whitespace-nowrap px-4 pb-3 pt-1 text-right tabular-nums text-slate-700 sm:table-cell sm:pt-3">{benchKrw != null ? <><span className="block text-base">약 {money(benchKrw, "KRW")}</span><span className="block text-xs text-slate-500">{fmt(k.benchmark_value, k.format)}</span></> : k.benchmark_value != null ? fmt(k.benchmark_value, k.format) : <span className="text-slate-400">–</span>}</td>}
              </tr>
            )
          })}
        </tbody>
      </table>
    </div>
  )
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
            {won && <div className="mt-1 text-xs tabular-nums text-slate-500">{fmt(k.value, k.format)} · 분석한 날의 환율 기준</div>}
            {k.benchmark_value !== undefined && k.benchmark_value !== null && <div className="mt-1 text-xs text-slate-500">{k.benchmark_label_ko ?? "비교지수"} {fmt(k.benchmark_value, k.format)}</div>}
            {(won ? won.rest : k.note_ko) && <div className="mt-1 text-[13px] leading-5 text-slate-600">{won ? won.rest : kpiNote(k.note_ko, doc)}</div>}
          </div>
        )
      })}
    </div>
  )
}
