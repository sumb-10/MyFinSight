import { useEffect, useId, useState } from "react"
import { ChevronDown } from "lucide-react"
import type { CompaniesBlock, CompanyItem } from "../../api/types"
import { fmt } from "../../lib/format"
import { metricName, metricValue } from "./metrics"
import { CitedText } from "./blocks/blocks"
import { useReport } from "./context"
import { MockTag, proposed } from "./proposedView"

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
  const dir = b.direction === "asc" ? "낮을수록" : "높을수록"
  const nNow = b.items.filter((x) => x.in_selection_now).length, nBt = b.items.filter((x) => x.in_backtest).length
  return (
    <div className="space-y-3">
      <div className="flex flex-wrap items-baseline justify-between gap-2">
        <h3 className="text-base font-bold text-slate-900">{b.title_ko} <span className="text-sm font-normal text-slate-500">{b.items.length}개</span></h3>
        <button type="button" onClick={() => setOpen(open.length === b.items.length ? [] : b.items.map((x) => x.ticker))} className="text-xs font-semibold text-blue-700 hover:underline">{open.length === b.items.length ? "모두 접기" : "모든 기업 펼치기"}</button>
      </div>
      <p className="text-xs leading-5 text-slate-500">선정 지표 {b.metric_ko}{metricName(b.metric) ? ` (${metricName(b.metric)})` : ""} · {dir} 우선 · 분석 기준일 {b.as_of_now} 선정 {nNow}개 / 백테스트 시작일 {b.as_of_bt} 선정 {nBt}개. 「내 투자 테마와 어떤 관련이 있나요?」는 투자 아이디어에서 뽑은 테마에 기업이 해당하는지 분석 모델이 판정한 이유입니다. 카드를 누르면 선정 근거 전문과 지표·출처를 볼 수 있습니다.</p>
      <ul className="space-y-2" aria-label="기업 목록">{b.items.map((it) => <CompanyCard key={it.ticker} it={it} b={b} open={open.includes(it.ticker)} onToggle={() => toggle(it.ticker)} />)}</ul>
      {b.note_ko && <p className="text-xs text-slate-500">{b.note_ko}</p>}
      <p className="text-xs leading-5 text-slate-500">비중이 줄었다고 해서 그 종목에 부정적인 근거가 있다는 뜻은 아닙니다. 다른 종목의 비중이 늘면서 상대적으로 줄 수 있습니다. 구체적인 비중 변화는 「투자 종목과 비중은 어떻게 결정됐나요?」에서 확인할 수 있습니다.</p>
    </div>
  )
}

/** 선정 시점 상태. in_selection_now = 분석 기준일에 선정, in_backtest = 백테스트 시작일에 선정 (서버 표의 뜻 그대로). */
export function selectionStatus(it: Pick<CompanyItem, "in_selection_now" | "in_backtest">): string | null {
  if (it.in_selection_now && it.in_backtest) return null
  if (it.in_selection_now) return "분석 기준일에만 선정 · 과거 성과 계산에는 포함되지 않음"
  if (it.in_backtest) return "백테스트 시작일에만 선정 · 분석 기준일에는 선정되지 않음"
  return "두 기준일 모두 선정되지 않음"
}

/** 종목별 뉴스 투자 의견 생성 여부 (제안 계약 company_views). 기사 수가 아니라 의견이 실제로 만들어졌는지를 보여 준다. */
const VIEW_TAG: Record<string, [string, string]> = { generated: ["뉴스 투자 의견 반영", "border-blue-200 bg-blue-50 text-blue-800"], insufficient: ["근거 부족 · 투자 의견 없음", "border-slate-200 bg-white text-slate-600"], disabled: ["뉴스 반영 꺼짐", "border-slate-200 bg-white text-slate-500"] }

function CompanyCard({ it, b, open, onToggle }: { it: CompanyItem; b: CompaniesBlock; open: boolean; onToggle: () => void }) {
  const bodyId = useId()
  const view = proposed(useReport()?.doc)?.company_views?.[it.ticker]
  const st = selectionStatus(it)
  const now = it.in_selection_now && it.rank_now !== null  // 분석 기준일 순위가 있으면 그것, 없으면 백테스트 시작일 순위 (날짜를 함께 적어 섞이지 않게)
  const rank = now ? `${it.rank_now}위 (${b.as_of_now})` : it.rank_bt !== null ? `${it.rank_bt}위 (${b.as_of_bt})` : null
  const raw = now ? it.metric_now : it.metric_bt
  const value = raw !== null ? metricValue(b.metric, raw) : null
  return (
    <li id={`acc-${it.ticker}`} className={`scroll-mt-16 rounded-xl border bg-white ${open ? "border-slate-300 shadow-sm" : "border-slate-200"}`}>
      <button type="button" aria-expanded={open} aria-controls={bodyId} onClick={onToggle} className="w-full rounded-xl px-4 py-3 text-left hover:bg-slate-50 focus:outline-none focus:ring-2 focus:ring-blue-500 sm:px-5">
        <span className="flex items-start justify-between gap-3">
          <span className="min-w-0">
            <span className="flex flex-wrap items-baseline gap-x-2"><span className="font-bold text-slate-950">{it.ticker}</span><span className="min-w-0 break-words text-sm text-slate-700">{it.name}</span></span>
            <span className="mt-0.5 block text-xs text-slate-500">{it.sector}{it.sub_industry ? ` · ${it.sub_industry}` : ""}</span>
          </span>
          <span className="flex shrink-0 items-center gap-2 text-right">
            <span><span className="block text-[11px] text-slate-500">추천안 비중</span><span className={`block text-sm font-bold tabular-nums ${it.weight !== null ? "text-slate-950" : "text-slate-400"}`}>{it.weight !== null ? fmt(it.weight, "pct1") : "추천안 비중 없음"}</span></span>
            <ChevronDown className={`size-4 text-slate-400 transition-transform ${open ? "rotate-180" : ""}`} aria-hidden />
          </span>
        </span>
        <span className="mt-2 flex flex-wrap gap-1.5 text-[11px]">
          {st ? <span className="rounded-md border border-slate-200 bg-slate-50 px-1.5 py-0.5 font-semibold text-slate-600">{st}</span> : <span className="rounded-md border border-slate-200 bg-slate-50 px-1.5 py-0.5 font-semibold text-slate-600">분석 기준일·백테스트 시작일 모두 선정</span>}
          {rank && <span className="rounded-md bg-slate-100 px-1.5 py-0.5 text-slate-700">{b.metric_ko} {value ?? "–"} · {rank}</span>}
          {view && <span className={`rounded-md border px-1.5 py-0.5 font-semibold ${VIEW_TAG[view.status]?.[1] ?? ""}`}>{VIEW_TAG[view.status]?.[0] ?? view.status}{view.status === "generated" ? ` ${view.n_views}개` : ""}</span>}{view && <MockTag />}
        </span>
        <span className="mt-3 block rounded-lg bg-slate-50 px-3 py-2.5">
          <span className="block text-sm font-bold text-slate-900">내 투자 테마와 어떤 관련이 있나요?</span>
          <span className="mt-1.5 block text-sm leading-6 text-slate-700">{it.theme_reason_ko || "설명이 제공되지 않았습니다"}</span>
        </span>
      </button>
      <div id={bodyId} hidden={!open} className="border-t border-slate-100 px-4 py-4 sm:px-5">{open ? <CompanyBody it={it} b={b} /> : null}</div>
    </li>
  )
}

function CompanyBody({ it, b }: { it: CompanyItem; b: CompaniesBlock }) {
  const rep = useReport()
  const forward = rep?.doc.summary?.allocation?.basis === "forward" ? rep.doc.summary.allocation.items.find((x) => x.ticker === it.ticker) : undefined
  const p = proposed(rep?.doc)
  const view = p?.company_views?.[it.ticker]
  const reasons = p?.company_reasons?.[it.ticker]
  const facts: [string, React.ReactNode][] = [
    ["선정 상태", selectionStatus(it) ?? "분석 기준일·백테스트 시작일 모두 선정"],
    ["섹터 · 세부산업", `${it.sector}${it.sub_industry ? ` · ${it.sub_industry}` : ""}${it.market ? ` · ${it.market}` : ""}`],
    ["추천안 비중 (백테스트)", it.weight !== null ? fmt(it.weight, "pct1") : "없음 (추천안에 포함되지 않음)"],
    ...(forward ? [["분석 기준일 구성 비중", fmt(forward.weight, "pct1")] as [string, React.ReactNode]] : []),
    [`${b.metric_ko} (${b.as_of_now})`, it.metric_now !== null ? <>{metricValue(b.metric, it.metric_now)} · 순위 {it.rank_now ?? "–"}{it.fact_id && rep && <button type="button" onClick={() => rep.openEvidence(it.fact_id!)} className="ml-1 align-super text-[11px] font-bold text-blue-700 hover:underline" aria-label={`지표 근거 ${it.fact_id} 보기`}>[{rep.numberOf(it.fact_id)}]</button>}</> : "–"],
    [`${b.metric_ko} (${b.as_of_bt})`, it.metric_bt !== null ? `${metricValue(b.metric, it.metric_bt)} · 순위 ${it.rank_bt ?? "–"}` : "–"],
    ["투자 테마와의 관련성", `${it.theme_reason_ko || "–"}${it.theme_confidence !== null ? ` (신뢰도 ${it.theme_confidence.toFixed(2)})` : ""}`],
    ...(view ? [["뉴스 투자 의견", <><MockTag />{" "}{view.reason_ko}{view.view_summaries_ko.length > 0 && <span className="mt-0.5 block text-slate-600">{view.view_summaries_ko.join(" / ")}</span>}</>] as [string, React.ReactNode]] : []),
    ["근거 자료", <>{it.n_news}건 뉴스 · {it.n_disclosures}건 공시{rep && (it.n_news + it.n_disclosures > 0) && <button type="button" onClick={() => rep.openDrawer({ ticker: it.ticker, title: `${it.ticker} 관련 근거` })} className="ml-2 text-xs font-semibold text-blue-700 hover:underline">출처 보기</button>}</>],
  ]
  return (
    <div className="grid grid-cols-1 gap-6 lg:grid-cols-[1fr_260px]">
      <div className="min-w-0 space-y-3 break-words text-[15px] leading-7 text-slate-700">
        {reasons && reasons.length > 0 && (
          <div className="space-y-2">
            <h4 className="flex items-center text-sm font-bold text-slate-900">핵심 선정 이유<MockTag /></h4>
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
        {it.rationale_ko.length ? it.rationale_ko.map((t, i) => <p key={i} className="whitespace-pre-line"><CitedText text={t} /></p>) : <p className="rounded-lg bg-slate-50 p-3 text-sm text-slate-600">이 종목의 선정 이유 설명은 제공되지 않았습니다.{it.in_selection_now ? " 설명이 없는 이유는 확인할 수 없습니다." : " 선정 이유 설명은 분석 기준일 선정 종목에 대해 만들어지며, 이 종목은 분석 기준일에 선정되지 않았습니다."}</p>}
      </div>
      <dl className="h-fit space-y-2 rounded-lg bg-slate-50 p-3 text-xs">{facts.map(([k, v]) => <div key={k}><dt className="font-semibold text-slate-500">{k}</dt><dd className="mt-0.5 text-slate-800">{v}</dd></div>)}</dl>
    </div>
  )
}
