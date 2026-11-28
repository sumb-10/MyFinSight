import { useEffect, useMemo, useState } from "react"
import { ExternalLink } from "lucide-react"
import type { EvidenceDetail, EvidenceRecord } from "../../api/types"
import { citedIn, kindOf } from "../../lib/citations"
import { ko } from "../../lib/format"
import { Disclosure, SidePanel } from "../../ui"
import { useReport } from "./context"
import { useService } from "../../app/providers"
import { CitedText } from "./blocks/blocks"
import { companyNames, evidencePlain, evidenceValue, finParts, kindPlain, peersOf, rankText, sentenceFor } from "./evidenceText"

// 근거 한 건 (2026-11-28 다시 짬). 읽는 순서: ① 이 근거가 뒷받침하는 문장 ② 근거가 말하는 내용(숫자는 본문과 같은 단위 + 쉬운 한 문장, 같은 지표로 견준 다른 회사)
// ③ 같은 근거를 쓴 다른 문장 ④ 자료 정보(ID·출처·언어 — 접어 둔다). 뉴스·공시도 바로 밖으로 내보내지 않고 여기서 먼저 보여 준 뒤 「원문 열기」를 둔다.
// 값과 문장은 서버가 준 그대로이고, 여기서는 보여 주는 순서와 단위만 정한다.

const KIND_DESC: Record<string, string> = {
  news: "뉴스는 제목만 모읍니다. 본문은 원문에서 확인할 수 있습니다.",
  disclosure: "공시는 어떤 사건이 있었는지만 알려 줍니다. 결과가 좋았는지 나빴는지를 뜻하지 않습니다.",
  financial: "그날까지 공시된 재무 자료와 그날 종가로 계산한 값입니다.",
  calc: "과거 성과 계산 결과에서 그대로 가져온 숫자입니다.",
}

/** from = 눌러서 들어온 글 (그 안에서 이 근거 번호가 붙은 문장을 맨 위에 보여 준다). 없으면 리포트에서 이 근거를 쓴 첫 문장. */
export function SourcePanel({ item, from, close }: { item: EvidenceRecord | { id: string }; from?: string; close: () => void }) {
  const rep = useReport()
  const svc = useService()
  const [detail, setDetail] = useState<EvidenceDetail | null>(null)
  const id = item.id
  const full = ("kind" in item ? item : null) as EvidenceRecord | null
  useEffect(() => {
    let alive = true
    setDetail(null)
    if (rep) svc.getReportEvidenceOne(rep.reportId, id).then((d) => { if (alive && d) setDetail(d) }).catch(() => undefined)
    return () => { alive = false }
  }, [rep, svc, id])
  const e: EvidenceRecord = detail ?? full ?? { id, kind: kindOf(id), title: "", source: "", tickers: [] }
  const loading = detail === null && !full
  const number = rep?.numberOf(id)
  const nameOf = useMemo(() => companyNames(rep?.doc), [rep])
  const cited = useMemo(() => { const local = rep ? citedIn(rep.doc, id) : []; return local.length ? local : (detail?.cited_in ?? []) }, [rep, id, detail])
  // 맨 위 문장: 눌러서 들어온 글의 그 문장, 없으면 이 근거를 쓴 첫 문장. 아래 「다른 문장」에서는 같은 글을 빼 겹치지 않게 한다
  const value = evidenceValue(e)
  const numeric = e.kind === "financial" || e.kind === "calc"
  const pick = (t: string) => sentenceFor(t, id, numeric ? value : null)   // 숫자 근거는 그 숫자가 적힌 문장을 고른다
  const lead = from && from.includes(`[${id}]`) ? { text: pick(from), where: cited.find((c) => c.text_ko === from) ?? null } : cited[0] ? { text: pick(cited[0].text_ko), where: cited[0] } : null
  const others = cited.filter((c) => c !== lead?.where && pick(c.text_ko) !== lead?.text)
  const fin = e.kind === "financial" ? finParts(id) : null
  const who = fin ? nameOf(fin.ticker) : e.tickers.map(nameOf).join(", ")
  const plain = evidencePlain(e)
  const peers = rep && fin ? peersOf(rep.doc, id) : null
  const max = peers ? Math.max(...peers.items.map((x) => Math.abs(x.value)), 1e-9) : 1
  const date = e.kind === "disclosure" ? (e.available_on ?? e.filed_at ?? e.published_at) : (e.published_at ?? e.data_as_of ?? fin?.date)
  const info: [string, string][] = [
    ["종류", ko(e.kind)], ["근거 번호", number && number !== id ? `[${number}]` : "–"], ["자료 ID", id], ["출처", e.source || "–"],
    ...(e.kind === "disclosure" ? ([["양식 · 항목", `${e.form ?? "–"}${e.items ? ` · ${e.items}` : ""}`], ["접수일 / 볼 수 있게 된 날", `${(e.filed_at ?? e.published_at ?? "–").slice(0, 10)} / ${e.available_on ?? "–"}`]] as [string, string][]) : []),
    ...(e.language ? ([["언어", e.language]] as [string, string][]) : []),
  ]
  return (
    <SidePanel title="근거 자세히" close={close}>
      {lead && (
        <section aria-label="이 근거가 뒷받침하는 문장">
          <p className="text-xs font-bold text-blue-700">이 문장의 근거입니다</p>
          <blockquote className="mt-2 border-l-4 border-blue-600 pl-4 text-[15px] leading-7 text-slate-900"><CitedText text={lead.text} tight /></blockquote>
          {lead.where && <button type="button" onClick={() => { rep?.jump(lead.where!.section_id); close() }} className="mt-1.5 pl-5 text-xs font-semibold text-slate-500 hover:text-blue-700 hover:underline">{lead.where.block_title_ko}</button>}
        </section>
      )}

      <section aria-label="근거 내용" className={`rounded-2xl bg-slate-50 p-5 ${lead ? "mt-6" : ""}`}>
        <p className="flex items-center gap-2 text-xs font-semibold text-slate-500">{number && number !== id && <span className="rounded-md bg-white px-1.5 py-0.5 font-bold text-blue-700">[{number}]</span>}{kindPlain(e.kind)}{date ? ` · ${String(date).slice(0, 10)}` : ""}{e.kind === "news" && e.source ? ` · ${e.source}` : ""}</p>
        {numeric ? (
          <>
            <p className="mt-3 text-sm font-semibold text-slate-700">{fin ? `${who} · ${e.title.replace(new RegExp(`^${fin.ticker}\\s*`), "")}` : e.title || (loading ? "불러오는 중…" : "–")}</p>
            {value && <p className="mt-1 text-4xl font-bold tabular-nums tracking-tight text-slate-950">{value}</p>}
            {plain && <p className="mt-3 text-[15px] leading-7 text-slate-800">{plain}</p>}
          </>
        ) : (
          <>
            {e.kind === "disclosure" && who && <p className="mt-3 text-sm font-semibold text-slate-700">{who}</p>}
            <p className={`${e.kind === "disclosure" && who ? "mt-1" : "mt-3"} text-lg font-bold leading-7 text-slate-950`}>{e.kind === "disclosure" ? (e.event_label_ko || e.title || "공시") : e.title || (loading ? "불러오는 중…" : "–")}</p>
            {e.kind === "news" && who && <p className="mt-2 text-sm text-slate-600">관련 회사: {who}</p>}
            {e.excerpt && <p className="mt-3 text-sm leading-6 text-slate-700">{e.excerpt}</p>}
          </>
        )}
        {e.url && <a href={e.url} target="_blank" rel="noopener noreferrer" className="mt-4 inline-flex items-center gap-1.5 rounded-xl bg-blue-700 px-4 py-2.5 text-sm font-semibold text-white hover:bg-blue-800">원문 열기<ExternalLink className="size-4" aria-hidden /></a>}
      </section>

      {peers && (
        <section aria-label="같은 지표로 견준 회사" className="mt-6">
          <h3 className="text-sm font-bold text-slate-900">{rankText(peers)}</h3>
          <ul className="mt-3 space-y-1.5">
            {peers.items.map((x) => (
              <li key={x.ticker} className="grid grid-cols-[9.5rem_1fr_4.5rem] items-center gap-3 text-sm">
                <span className={`truncate ${x.me ? "font-bold text-slate-950" : "text-slate-600"}`} title={x.name}>{x.name}</span>
                <span className="block h-3" aria-hidden><span className={`block h-full rounded-r ${x.me ? "bg-blue-600" : "bg-slate-300"}`} style={{ width: `${Math.max(2, (Math.abs(x.value) / max) * 100)}%` }} /></span>
                <span className={`text-right tabular-nums ${x.me ? "font-bold text-blue-700" : "text-slate-600"}`}>{x.text}</span>
              </li>
            ))}
          </ul>
        </section>
      )}

      {others.length > 0 && (
        <section className="mt-6">
          <h3 className="text-sm font-bold text-slate-900">같은 근거를 쓴 다른 문장 <span className="font-normal text-slate-500">{others.length}</span></h3>
          <ul className="mt-2 space-y-2">{others.slice(0, 12).map((c, i) => <li key={i} className="rounded-xl bg-slate-50 p-3 text-sm leading-6 text-slate-700"><button type="button" onClick={() => { rep?.jump(c.section_id); close() }} className="mb-1 block text-xs font-semibold text-blue-700 hover:underline">{c.block_title_ko}</button><CitedText text={pick(c.text_ko)} tight /></li>)}</ul>
        </section>
      )}
      {!lead && !loading && <p className="mt-6 text-sm text-slate-600">본문 문장에 번호로 붙지 않은 자료입니다. 표와 투자 의견을 만들 때 참고했습니다.</p>}

      <Disclosure size="sm" className="mt-6" title="자료 정보">
        <dl className="grid grid-cols-[8.5rem_1fr] gap-x-3 gap-y-2 text-xs">{info.map(([k, v]) => <div key={k} className="contents"><dt className="font-semibold text-slate-500">{k}</dt><dd className="break-all text-slate-700">{v}</dd></div>)}</dl>
        <p className="mt-3 text-xs leading-5 text-slate-600">{KIND_DESC[e.kind] ?? "리포트가 참고한 자료입니다."}</p>
      </Disclosure>
    </SidePanel>
  )
}
