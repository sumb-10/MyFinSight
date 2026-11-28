import { useEffect, useId, useState } from "react"
import { ChevronDown } from "lucide-react"
import type { CompaniesBlock, CompanyItem, ReportSummary } from "../../api/types"
import { fmt } from "../../lib/format"
import { metricName, metricValue } from "./metrics"
import { CitedText } from "./blocks/blocks"
import { useReport } from "./context"
import { MockTag, proposed } from "./proposedView"
import { companyNames, evidenceTitle, kindPlain } from "./evidenceText"

/** 종목 카드의 비중이 어느 날짜 기준인지. 서버는 분석 기준일 구성을 만들 수 있으면 그 비중을, 못 만들면 백테스트 시작일 목표 비중을 넣는다
 *  (2026-10-30 리포트처럼 예전 리포트는 항상 백테스트 시작일 포트폴리오 비중). 요약 배분(분석 기준일 구성)과 모든 종목 값이 같으면 분석 기준일 포트폴리오 비중이다.
 *  2026-11-16: 같은 숫자가 「추천안 비중 (백테스트)」·「분석 기준일 구성 비중」 두 줄로 나와 이름이 틀렸다. */
export function weightBasis(items: Pick<CompanyItem, "ticker" | "weight">[], alloc: ReportSummary["allocation"] | undefined): "now" | "bt" {
  if (alloc?.basis !== "forward") return "bt"
  const fw = new Map(alloc.items.map((x) => [x.ticker, x.weight]))
  return items.every((it) => { const a = it.weight ?? null, f = fw.get(it.ticker) ?? null; return a === null || f === null ? a === f : Math.abs(a - f) < 1e-6 }) ? "now" : "bt"
}

/** 기업별 투자 근거: 기업 카드 목록 (모두 접힘). 카드에는 선정 상태·비중·지표 순위·테마 관련성만, 누르면 원문·지표·출처 전체. 주소의 ?company= 가 있으면 그 기업을 펼친다. */
export function CompanyList({ b }: { b: CompaniesBlock }) {
  const rep = useReport()
  const [open, setOpen] = useState<string[]>(() => (rep?.openCompany ? [rep.openCompany] : []))
  useEffect(() => {
    const t = rep?.openCompany
    if (t && !open.includes(t)) setOpen((o) => [...o, t])
    if (t) window.setTimeout(() => document.getElementById(`acc-${t}`)?.scrollIntoView({ behavior: "smooth", block: "start" }), 50)
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [rep?.openCompany])
  const toggle = (t: string) => {
    const next = !open.includes(t)
    setOpen((o) => (next ? [...o, t] : o.filter((x) => x !== t)))
    if (next) rep?.setOpenCompany(t)
  }
  const basis = weightBasis(b.items, rep?.doc.summary?.allocation)
  const dir = b.direction === "asc" ? "낮을수록" : "높을수록"
  const nNow = b.items.filter((x) => x.in_selection_now).length, nBt = b.items.filter((x) => x.in_backtest).length
  return (
    // 「선정 과정」처럼 한 카드 안에: 제목·설명 줄 → 기업 카드 목록 (기업 카드는 그대로)
    <div className="space-y-3 rounded-xl border border-slate-200 bg-white p-5">
      <div className="flex flex-wrap items-baseline justify-between gap-2">
        <h3 className="text-base font-semibold text-slate-900">{b.title_ko} <span className="text-sm font-normal text-slate-500">{b.items.length}개</span></h3>
        <button type="button" onClick={() => setOpen(open.length === b.items.length ? [] : b.items.map((x) => x.ticker))} className="text-xs font-semibold text-blue-700 hover:underline">{open.length === b.items.length ? "모두 접기" : "모든 기업 펼치기"}</button>
      </div>
      <p className="text-xs leading-5 text-slate-500">선정 지표 {b.metric_ko}{metricName(b.metric) ? ` (${metricName(b.metric)})` : ""} · {dir} 우선 · {b.holdings_fixed ? `백테스트 시작일 ${b.as_of_bt}에 ${nBt}개를 골라 분석한 날 ${b.as_of_now}까지 유지` : `분석한 날 ${b.as_of_now} 선정 ${nNow}개 / 백테스트 시작일 ${b.as_of_bt} 선정 ${nBt}개`}</p>
      <ul className="space-y-2" aria-label="기업 목록">{b.items.map((it) => <CompanyCard key={it.ticker} it={it} b={b} basis={basis} open={open.includes(it.ticker)} onToggle={() => toggle(it.ticker)} />)}</ul>
      {b.note_ko && <p className="text-xs text-slate-500">{b.note_ko}</p>}
    </div>
  )
}

/** 선정 시점 상태. in_selection_now = 분석 기준일에 선정, in_backtest = 백테스트 시작일에 선정 (서버 표의 뜻 그대로). */
export function selectionStatus(it: Pick<CompanyItem, "in_selection_now" | "in_backtest">): string | null {
  if (it.in_selection_now && it.in_backtest) return null
  if (it.in_selection_now) return "분석한 날에만 선정 · 과거 성과 계산에는 포함되지 않음"
  if (it.in_backtest) return "백테스트 시작일에만 선정 · 분석한 날에는 선정되지 않음"
  return "두 기준일 모두 선정되지 않음"
}

/** 종목별 뉴스 투자 의견 생성 여부 (제안 계약 company_views). 기사 수가 아니라 의견이 실제로 만들어졌는지를 보여 준다. */
const VIEW_TAG: Record<string, [string, string]> = { generated: ["뉴스 투자 의견 반영", "border-blue-200 bg-blue-50 text-blue-800"], insufficient: ["근거 부족 · 투자 의견 없음", "border-slate-200 bg-white text-slate-600"], disabled: ["뉴스 반영 꺼짐", "border-slate-200 bg-white text-slate-500"] }

function CompanyCard({ it, b, basis, open, onToggle }: { it: CompanyItem; b: CompaniesBlock; basis: "now" | "bt"; open: boolean; onToggle: () => void }) {
  const bodyId = useId()
  const view = proposed(useReport()?.doc)?.company_views?.[it.ticker]
  const st = selectionStatus(it)
  const now = it.in_selection_now && it.rank_now !== null  // 분석 기준일 순위가 있으면 그것, 없으면 백테스트 시작일 순위 (날짜를 함께 적어 섞이지 않게)
  const rank = now ? `${it.rank_now}위 (${b.as_of_now})` : it.rank_bt !== null ? `${it.rank_bt}위 (${b.as_of_bt})` : null
  const raw = now ? it.metric_now : it.metric_bt
  const wLabel = basis === "now" ? "분석한 날의 포트폴리오 비중" : "백테스트 시작일 포트폴리오 비중"
  const wValue = <span className={`block text-sm font-bold tabular-nums ${it.weight !== null ? "text-slate-950" : "text-slate-400"}`}>{it.weight !== null ? fmt(it.weight, "pct1") : "담지 않음"}</span>
  const value = raw !== null ? metricValue(b.metric, raw) : null
  return (
    <li id={`acc-${it.ticker}`} className={`scroll-mt-16 rounded-xl border bg-white ${open ? "border-slate-300 shadow-sm" : "border-slate-200"}`}>
      <button type="button" aria-expanded={open} aria-controls={bodyId} onClick={onToggle} className="w-full rounded-xl px-4 py-3 text-left hover:bg-slate-50 focus:outline-none focus:ring-2 focus:ring-blue-500 sm:px-5">
        {/* 섹터 줄은 펼친 상세(섹터 · 세부산업)에만: 이름 줄을 오른쪽 비중(두 줄)과 가운데 맞춰 빈 공간이 생기지 않게 */}
        {/* 넓은 화면: 이름 | 비중(두 줄) | 펼침 표시. 좁은 화면(2026-11-20): 비중을 이름 아래 한 줄로 내려 회사 이름이 'Broadc/om' 처럼 글자 단위로 끊기지 않게 */}
        <span className="flex items-center justify-between gap-3">
          <span className="min-w-0">
            <span className="flex flex-wrap items-baseline gap-x-2"><span className="font-bold text-slate-950">{it.ticker}</span><span className="text-sm text-slate-700">{it.name}</span></span>
            <span className="mt-0.5 flex items-baseline gap-1.5 sm:hidden"><span className="text-[11px] text-slate-500">{wLabel}</span>{wValue}</span>
          </span>
          <span className="flex shrink-0 items-center gap-2 text-right">
            <span className="hidden sm:block"><span className="block text-[11px] text-slate-500">{wLabel}</span>{wValue}</span>
            <ChevronDown className={`size-4 text-slate-400 transition-transform ${open ? "rotate-180" : ""}`} aria-hidden />
          </span>
        </span>
        {/* 모든 종목에 같은 「백테스트 시작일 선정 · 분석한 날까지 유지」 표시는 뺐다 (2026-11-20 사용자 요청). 두 날짜의 선정이 다른 예전 리포트의 종목만 상태 표시를 남긴다.
            표시할 것이 없으면 줄 자체를 그리지 않아 빈 간격이 생기지 않게 한다. */}
        {(st || rank || view) && (
          <span className="mt-2 flex flex-wrap gap-1.5 text-[11px]">
            {st && <span className="rounded-md border border-slate-200 bg-slate-50 px-1.5 py-0.5 font-semibold text-slate-600">{st}</span>}
            {rank && <span className="rounded-md bg-slate-100 px-1.5 py-0.5 text-slate-700">{b.metric_ko} {value ?? "–"} · {rank}</span>}
            {view && <span className={`rounded-md border px-1.5 py-0.5 font-semibold ${VIEW_TAG[view.status]?.[1] ?? ""}`}>{VIEW_TAG[view.status]?.[0] ?? view.status}{view.status === "generated" ? ` ${view.n_views}개` : ""}</span>}{view && <MockTag />}
          </span>
        )}
        <span className="mt-3 block rounded-lg bg-slate-50 px-3 py-2.5">
          <span className="block text-sm font-bold text-slate-900">테마 관련성</span>
          <span className="mt-1.5 block text-sm leading-6 text-slate-700">{it.theme_reason_ko || "설명이 제공되지 않았습니다"}</span>
        </span>
      </button>
      <div id={bodyId} hidden={!open} className="border-t border-slate-100 px-4 py-4 sm:px-5">{open ? <CompanyBody it={it} b={b} basis={basis} /> : null}</div>
    </li>
  )
}

function CompanyBody({ it, b, basis }: { it: CompanyItem; b: CompaniesBlock; basis: "now" | "bt" }) {
  const rep = useReport()
  const alloc = rep?.doc.summary?.allocation
  const nowW = (w: number | null | undefined): [string, React.ReactNode] => [`분석한 날의 포트폴리오 비중 (${b.as_of_now})`, w != null ? fmt(w, "pct1") : "없음 (분석한 날의 구성에 담지 않음)"]
  // 두 값이 같으면 한 줄(분석 기준일), 다르면 백테스트 시작일·분석 기준일 두 줄로 날짜를 나눠 적는다
  const weightRows: [string, React.ReactNode][] = basis === "now" ? [nowW(it.weight)]
    : [[`백테스트 시작일 포트폴리오 비중 (${b.as_of_bt})`, it.weight !== null ? fmt(it.weight, "pct1") : "없음 (백테스트 시작일 구성에 담지 않음)"],
       ...(alloc?.basis === "forward" ? [nowW(alloc.items.find((x) => x.ticker === it.ticker)?.weight)] : [])]
  const p = proposed(rep?.doc)
  const view = p?.company_views?.[it.ticker]
  const reasons = p?.company_reasons?.[it.ticker]
  const facts: [string, React.ReactNode][] = [
    ["선정 상태", selectionStatus(it) ?? (b.holdings_fixed ? "백테스트 시작일 선정 · 분석한 날까지 유지" : "분석한 날·백테스트 시작일 모두 선정")],
    ["섹터 · 세부산업", `${it.sector}${it.sub_industry ? ` · ${it.sub_industry}` : ""}${it.market ? ` · ${it.market}` : ""}`],
    ...weightRows,
    [`${b.metric_ko} (${b.as_of_now})`, it.metric_now !== null ? <>{metricValue(b.metric, it.metric_now)} · 순위 {it.rank_now ?? "–"}{it.fact_id && rep && <button type="button" onClick={() => rep.openEvidence(it.fact_id!)} className="ml-1 align-super text-[11px] font-bold text-blue-700 hover:underline" aria-label={`지표 근거 ${it.fact_id} 보기`}>[{rep.numberOf(it.fact_id)}]</button>}</> : "–"],
    [`${b.metric_ko} (${b.as_of_bt})`, it.metric_bt !== null ? `${metricValue(b.metric, it.metric_bt)} · 순위 ${it.rank_bt ?? "–"}` : "–"],
    ["투자 테마와의 관련성", `${it.theme_reason_ko || "–"}${it.theme_confidence ? ` (확신 정도 ${Math.round(it.theme_confidence * 100)}%)` : ""}`],
    ...(view ? [["뉴스 투자 의견", <><MockTag />{" "}{view.reason_ko}{view.view_summaries_ko.length > 0 && <span className="mt-0.5 block text-slate-600">{view.view_summaries_ko.join(" / ")}</span>}</>] as [string, React.ReactNode]] : []),
  ]
  // 근거 묶음 (2026-11-28): 이 회사에 대해 본문이 쓴 근거를 카드 안에서 바로 보여 준다 (지표 숫자 · 뉴스 · 공시). 읽기만 한 뉴스·공시는 「모두 보기」로
  const nameOf = companyNames(rep?.doc)
  const used = (rep?.doc.evidence ?? []).filter((e) => e.tickers.includes(it.ticker) || e.id === it.fact_id)
  const order = ["financial", "disclosure", "news", "calc"]
  const when = (e: (typeof used)[number]) => String((e.kind === "disclosure" ? e.available_on : e.published_at ?? e.data_as_of) ?? "")
  used.sort((a, b) => order.indexOf(a.kind) - order.indexOf(b.kind) || when(b).localeCompare(when(a)))  // 숫자 → 공시 → 뉴스, 같은 종류는 최근 것부터
  const SHOWN = 5
  return (
    <div className="grid grid-cols-1 gap-6 lg:grid-cols-[1fr_260px]">
      <div className="min-w-0 space-y-3 break-words text-[15px] leading-7 text-slate-700">
        {reasons && reasons.length > 0 && (
          <div className="space-y-2">
            <h4 className="flex items-center text-sm font-bold text-slate-900">이 종목을 고른 이유<MockTag /></h4>
            <ul className="space-y-2">
              {reasons.map((x, i) => (
                <li key={i} className="rounded-lg border border-slate-200 px-3 py-2.5">
                  <p className="flex flex-wrap items-baseline justify-between gap-x-3 text-sm font-bold text-slate-900"><span>{x.title_ko}</span>{x.metric && <span className="text-xs font-semibold tabular-nums text-slate-600">{x.metric.label_ko} {x.metric.format === "pct" ? fmt(x.metric.value, "pct") : x.metric.value}</span>}</p>
                  <p className="mt-0.5 text-sm leading-6 text-slate-700">{x.text_ko}</p>
                  {x.theme_link_ko && <p className="text-xs text-slate-500">관련 테마: {x.theme_link_ko}</p>}
                  {x.quote_ko && <p className="mt-1 border-l-2 border-slate-200 pl-2 text-xs leading-5 text-slate-600">{x.quote_ko}</p>}
                  {rep && x.evidence_ids.length > 0 && <span className="mt-1 flex flex-wrap gap-1">{x.evidence_ids.map((id) => <button key={id} type="button" onClick={() => rep.openEvidence(id)} className="text-[11px] font-bold text-blue-700 hover:underline" aria-label={`근거 ${id} 보기`}>[{rep.numberOf(id)}]</button>)}</span>}
                </li>
              ))}
            </ul>
          </div>
        )}
        <h4 className="text-sm font-bold text-slate-900">{reasons?.length ? "선정 근거 원문" : "선정 근거"}</h4>
        {it.summary && <p className="text-sm text-slate-500"><span className="font-semibold">회사 소개 </span>{it.summary}</p>}
        {it.rationale_ko.length ? it.rationale_ko.map((t, i) => <p key={i} className="whitespace-pre-line"><CitedText text={t} /></p>) : <p className="rounded-lg bg-slate-50 p-3 text-sm text-slate-600">{it.in_selection_now ? "선정 이유 설명이 없습니다." : "분석한 날의 선정 종목이 아니어서 선정 이유 설명이 없습니다."}</p>}
        {rep && (used.length > 0 || it.n_news + it.n_disclosures > 0) && (
          <div className="pt-2">
            <h4 className="text-sm font-bold text-slate-900">근거 자료{used.length > 0 && <span className="ml-1.5 font-normal text-slate-500">본문에 쓰인 {used.length}건</span>}</h4>
            {used.length > 0 && (
              <ul aria-label={`${it.ticker} 근거 자료`} className="mt-2 divide-y divide-slate-100 rounded-xl border border-slate-200">
                {used.slice(0, SHOWN).map((e) => (
                  <li key={e.id}>
                    <button type="button" onClick={() => rep.openEvidence(e.id)} className="flex w-full items-baseline gap-3 px-3 py-2.5 text-left text-sm hover:bg-slate-50">
                      <span className="w-8 shrink-0 text-right text-xs font-bold tabular-nums text-blue-700">{rep.numberOf(e.id) !== e.id ? `[${rep.numberOf(e.id)}]` : ""}</span>{/* 본문 문장에 번호로 붙지 않은 자료는 번호 없이 (내부 ID 를 보이지 않는다) */}
                      <span className="min-w-0 flex-1 truncate font-semibold text-slate-900">{evidenceTitle(e, nameOf)}</span>
                      <span className="shrink-0 text-xs text-slate-500">{kindPlain(e.kind)} · {String((e.kind === "disclosure" ? e.available_on : e.published_at ?? e.data_as_of) ?? "").slice(0, 10)}</span>
                    </button>
                  </li>
                ))}
              </ul>
            )}
            <div className="mt-2 flex flex-wrap gap-x-4 gap-y-1">
              {used.length > SHOWN && <button type="button" onClick={() => rep.openDrawer({ ticker: it.ticker, title: `${it.name || it.ticker} 관련 자료`, scope: "cited" })} className="text-xs font-semibold text-blue-700 hover:underline">본문에 쓰인 {used.length}건 모두 보기</button>}
              {it.n_news + it.n_disclosures > 0 && <button type="button" onClick={() => rep.openDrawer({ ticker: it.ticker, title: `${it.name || it.ticker} 관련 자료`, scope: "all" })} className="text-xs font-semibold text-blue-700 hover:underline">읽은 뉴스 {it.n_news}건 · 공시 {it.n_disclosures}건 모두 보기</button>}
            </div>
          </div>
        )}
      </div>
      <dl className="h-fit space-y-2 rounded-lg bg-slate-50 p-3 text-xs">{facts.map(([k, v]) => <div key={k}><dt className="font-semibold text-slate-500">{k}</dt><dd className="mt-0.5 text-slate-800">{v}</dd></div>)}</dl>
    </div>
  )
}
