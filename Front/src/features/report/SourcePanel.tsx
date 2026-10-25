import { useEffect, useState } from "react"
import type { EvidenceDetail, EvidenceRecord } from "../../api/types"
import { citedIn, kindOf } from "../../lib/citations"
import { fmt, ko } from "../../lib/format"
import { SidePanel } from "../../ui"
import { useReport } from "./context"
import { useService } from "../../app/providers"

const KIND_DESC: Record<string, string> = {
  news: "뉴스 헤드라인 (팀 데이터베이스 news). 본문은 수집하지 않아 발췌가 없습니다.",
  disclosure: "공시 목록 (SEC EDGAR 8-K·10-Q·10-K, DART). 사건 종류·양식·접수일·이용 가능일만 있고 본문은 없습니다.",
  financial: "재무·가격 지표 (valuation_daily · price_daily). 그날까지 공시된 재무와 그날 종가로 계산한 값입니다.",
  calc: "백테스트 계산값. 결과에서 그대로 가져온 숫자입니다.",
}

/** 근거 한 건의 상세. 종류별 필드(공시는 사건·양식·접수일·이용 가능일) + 이 근거를 인용한 문장 + 원문 링크. */
export function SourcePanel({ item, close }: { item: EvidenceRecord | { id: string }; close: () => void }) {
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
  const number = rep?.numberOf(id)
  const local = rep ? citedIn(rep.doc, id) : []
  const cited = local.length ? local : (detail?.cited_in ?? [])
  const dateLabel = e.kind === "disclosure" ? "접수일 / 이용 가능일" : e.kind === "news" ? "발행일" : "기준일"
  const dateVal = e.kind === "disclosure" ? `${(e.filed_at ?? e.published_at ?? "–").slice(0, 10)} / ${e.available_on ?? "–"}` : (e.published_at ?? e.data_as_of ?? "–")
  const rows: [string, React.ReactNode][] = [
    ["근거 번호 · ID", `${number && number !== id ? `[${number}]` : "–"} · ${id}`], ["종류", ko(e.kind)],
    ...(e.kind === "disclosure" ? ([["사건 종류", e.event_label_ko ?? e.event_type ?? "–"], ["양식 · 항목", `${e.form ?? "–"}${e.items ? ` · ${e.items}` : ""}`]] as [string, React.ReactNode][]) : []),
    ["내용", e.title || (detail === null && !full ? "불러오는 중…" : "–")],
    ...(e.value !== undefined && e.value !== null ? ([["값", typeof e.value === "number" ? (e.unit === "usd" ? fmt(e.value, "usd") : e.unit === "ratio" ? fmt(e.value, "num") : String(e.value)) : String(e.value)]] as [string, React.ReactNode][]) : []),
    ["관련 종목", e.tickers.join(", ") || "–"], [dateLabel, dateVal], ["출처", e.source || "–"], ["언어", e.language ?? "–"],
    ["발췌", e.excerpt ? e.excerpt : <span className="text-slate-400">발췌 없음 — {e.kind === "news" ? "헤드라인만 수집" : e.kind === "disclosure" ? "공시 목록만 수집(본문 없음)" : "해당 없음"}</span>],
  ]
  return (
    <SidePanel title="참고자료 상세" close={close}>
      <dl className="space-y-4">{rows.map(([k, v]) => <div key={k}><dt className="text-xs font-semibold text-slate-400">{k}</dt><dd className="mt-1 text-sm leading-6 text-slate-700">{v}</dd></div>)}</dl>
      {e.url && <a href={e.url} target="_blank" rel="noreferrer" className="mt-6 block rounded-xl border border-blue-200 bg-blue-50 p-4 text-sm font-semibold text-blue-800">원문 열기 ↗</a>}
      <h3 className="mt-6 text-sm font-bold text-slate-800">이 근거를 인용한 문장 {cited.length > 0 && <span className="font-normal text-slate-400">({cited.length})</span>}</h3>
      {cited.length === 0 ? <p className="mt-2 text-xs text-slate-500">본문에서 직접 인용하지 않은 근거입니다 (뷰·표의 참고 자료).</p> : (
        <ul className="mt-2 space-y-2">{cited.slice(0, 12).map((c, i) => <li key={i} className="rounded-lg bg-slate-50 p-3 text-sm leading-6 text-slate-700"><button type="button" onClick={() => { rep?.jump(c.section_id); close() }} className="mb-1 block text-xs font-semibold text-blue-700 hover:underline">{c.block_title_ko}</button>{c.text_ko}</li>)}</ul>
      )}
      <p className="mt-6 rounded-xl bg-slate-50 p-4 text-xs leading-5 text-slate-600">{KIND_DESC[e.kind] ?? "리포트가 인용한 근거입니다."}{e.kind === "disclosure" && " 공시는 사건의 존재만 알려 주며, 결과(좋았다·나빴다)를 뜻하지 않습니다."}</p>
    </SidePanel>
  )
}
