import { useEffect, useMemo, useState } from "react"
import type { CompaniesBlock, CompanyItem } from "../../api/types"
import { fmt } from "../../lib/format"
import { Accordion, Badge } from "../../ui"
import { CitedText } from "./blocks/blocks"
import { useReport } from "./context"

/** 기업별 투자 근거: 왼쪽 종목 미니 내비 + 오른쪽 아코디언(처음 3개 펼침). 주소의 ?company= 가 있으면 그 종목을 연다. */
export function CompanyList({ b }: { b: CompaniesBlock }) {
  const rep = useReport()
  const first = useMemo(() => b.items.slice(0, 3).map((x) => x.ticker), [b.items])
  const [open, setOpen] = useState<string[]>(() => (rep?.openCompany ? Array.from(new Set([rep.openCompany, ...first])) : first))
  useEffect(() => {
    const t = rep?.openCompany
    if (t && !open.includes(t)) setOpen((o) => [...o, t])
    if (t) window.setTimeout(() => document.getElementById(`acc-${t}`)?.scrollIntoView({ behavior: "smooth", block: "start" }), 50)
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [rep?.openCompany])
  const dir = b.direction === "asc" ? "낮을수록" : "높을수록"
  return (
    <div className="rounded-xl border border-slate-200 bg-white p-5">
      <div className="mb-3 flex flex-wrap items-baseline justify-between gap-2"><h3 className="text-base font-semibold text-slate-900">{b.title_ko}</h3><p className="text-xs text-slate-500">선정 지표 {b.metric_ko} ({b.metric}) · {dir} 우선 · 분석 기준일 {b.as_of_now} / 백테스트 시작일 {b.as_of_bt}</p></div>
      <div className="grid grid-cols-[150px_1fr] gap-5">
        <nav aria-label="종목" className="sticky top-6 h-fit space-y-1 text-sm">
          {b.items.map((it) => <button key={it.ticker} type="button" onClick={() => { setOpen((o) => (o.includes(it.ticker) ? o : [...o, it.ticker])); rep?.setOpenCompany(it.ticker); document.getElementById(`acc-${it.ticker}`)?.scrollIntoView({ behavior: "smooth", block: "start" }) }} className={`block w-full rounded-lg px-2 py-1.5 text-left hover:bg-slate-100 ${open.includes(it.ticker) ? "font-semibold text-slate-900" : "text-slate-600"}`}><span className="block truncate">{it.ticker}</span><span className="block truncate text-[11px] text-slate-400">{it.weight !== null ? fmt(it.weight, "pct1") : "미보유"} · {it.sector}</span></button>)}
        </nav>
        <Accordion openIds={open} onChange={setOpen} items={b.items.map((it) => ({ id: it.ticker, title: <CompanyTitle it={it} />, summary: <span className="hidden md:inline">{it.weight !== null ? `비중 ${fmt(it.weight, "pct1")}` : "미보유"}{it.rank_now ? ` · 순위 ${it.rank_now}` : ""}</span>, body: <CompanyBody it={it} b={b} /> }))} />
      </div>
      {b.note_ko && <p className="mt-3 text-xs text-slate-500">{b.note_ko}</p>}
    </div>
  )
}

function CompanyTitle({ it }: { it: CompanyItem }) {
  return <span className="flex min-w-0 items-center gap-2"><span className="font-bold">{it.ticker}</span><span className="truncate font-normal text-slate-700">{it.name}</span>{!it.in_selection_now && <Badge tone="slate">분석 기준일 미선정</Badge>}{!it.in_backtest && <Badge tone="slate">백테스트 미포함</Badge>}</span>
}

function CompanyBody({ it, b }: { it: CompanyItem; b: CompaniesBlock }) {
  const rep = useReport()
  const facts: [string, React.ReactNode][] = [
    ["섹터 · 세부산업", `${it.sector}${it.sub_industry ? ` · ${it.sub_industry}` : ""}${it.market ? ` · ${it.market}` : ""}`],
    ["선택안 비중", it.weight !== null ? fmt(it.weight, "pct1") : "–"],
    [`${b.metric_ko} (${b.as_of_now})`, it.metric_now !== null ? <>{fmt(it.metric_now, "pct")} · 순위 {it.rank_now ?? "–"}{it.fact_id && rep && <button type="button" onClick={() => rep.openEvidence(it.fact_id!)} className="ml-1 align-super text-[11px] font-bold text-blue-700 hover:underline" aria-label={`지표 근거 ${it.fact_id} 보기`}>[{rep.numberOf(it.fact_id)}]</button>}</> : "–"],
    [`${b.metric_ko} (${b.as_of_bt})`, it.metric_bt !== null ? `${fmt(it.metric_bt, "pct")} · 순위 ${it.rank_bt ?? "–"}` : "–"],
    ["테마 판정", `${it.theme_reason_ko || "–"}${it.theme_confidence !== null ? ` (신뢰도 ${it.theme_confidence.toFixed(2)})` : ""}`],
    ["근거 자료", <>{it.n_news}건 뉴스 · {it.n_disclosures}건 공시{rep && (it.n_news + it.n_disclosures > 0) && <button type="button" onClick={() => rep.openDrawer({ ticker: it.ticker, title: `${it.ticker} 관련 근거` })} className="ml-2 text-xs font-semibold text-blue-700 hover:underline">출처 보기</button>}</>],
  ]
  return (
    <div className="grid grid-cols-[1fr_260px] gap-6">
      <div className="space-y-3 text-[15px] leading-7 text-slate-700">
        {it.summary && <p className="text-sm text-slate-500">{it.summary}</p>}
        {it.rationale_ko.length ? it.rationale_ko.map((t, i) => <p key={i} className="whitespace-pre-line"><CitedText text={t} /></p>) : <p className="text-sm text-slate-500">이 종목의 근거 설명이 없습니다 (분석 기준일에 선정되지 않았거나 설명 단계가 건너뛰어졌습니다).</p>}
      </div>
      <dl className="space-y-2 rounded-lg bg-slate-50 p-3 text-xs">{facts.map(([k, v]) => <div key={k}><dt className="font-semibold text-slate-500">{k}</dt><dd className="mt-0.5 text-slate-800">{v}</dd></div>)}</dl>
    </div>
  )
}
