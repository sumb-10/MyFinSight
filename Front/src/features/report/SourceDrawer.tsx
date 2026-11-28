import { useEffect, useMemo, useState } from "react"
import { Search } from "lucide-react"
import type { EvidencePage, EvidenceRecord } from "../../api/types"
import { ko } from "../../lib/format"
import { Loading, Pagination, SidePanel, inputClass } from "../../ui"
import { type DrawerFilter, useReport } from "./context"
import { useService } from "../../app/providers"
import { companyNames, evidenceTitle, kindPlain } from "./evidenceText"

const PAGE = 50
const KINDS = ["news", "disclosure", "financial", "calc"]

/** 출처 드로어: 근거 색인을 검색·종류·종목으로 걸러 50건씩 본다. 서버 /evidence 가 없으면(404) 문서 안의 근거로 대신한다.
 *  2026-11-28: 처음에는 「본문에 쓰인 근거」만 보여 주고, 읽기만 한 자료는 「읽은 자료 전체」로 따로 본다 (전체 1,000여 건 가운데 본문이 쓴 것은 수십 건).
 *  줄마다 근거 번호와 내용(숫자는 값과 함께, 회사는 이름으로)을 먼저, 자료 ID 는 보이지 않게 둔다 (검색은 된다). */
export function SourceDrawer({ filter, close, onOpen }: { filter: DrawerFilter; close: () => void; onOpen: (e: EvidenceRecord) => void }) {
  const rep = useReport()
  const svc = useService()
  const [q, setQ] = useState("")
  const [kind, setKind] = useState(filter.kind ?? "")
  const [ticker, setTicker] = useState(filter.ticker ?? "")
  const [page, setPage] = useState(0)
  const citedIds = useMemo(() => (rep?.doc.evidence ?? []).map((e) => e.id), [rep])  // 문서에 실린 근거 = 본문이 쓴 근거
  const canScope = !filter.ids && citedIds.length > 0
  const tickerCited = !filter.ticker || (rep?.doc.evidence ?? []).some((e) => e.tickers.some((t) => t.toUpperCase() === filter.ticker!.toUpperCase()))
  const [scope, setScope] = useState<"cited" | "all">(filter.scope ?? (tickerCited ? "cited" : "all"))
  const ids = filter.ids ?? (canScope && scope === "cited" ? citedIds : undefined)
  const nameOf = useMemo(() => companyNames(rep?.doc), [rep])
  const [remote, setRemote] = useState<EvidencePage | null | "pending">("pending")
  useEffect(() => { setPage(0) }, [q, kind, ticker, scope])
  useEffect(() => {
    if (!rep) { setRemote(null); return }
    let alive = true
    setRemote("pending")
    svc.getReportEvidence(rep.reportId, { offset: page * PAGE, limit: PAGE, kind: kind || undefined, ticker: ticker || undefined, q: q || undefined, ids })
      .then((p) => { if (alive) setRemote(p) }).catch(() => { if (alive) setRemote(null) })
    return () => { alive = false }
  }, [rep, svc, page, kind, ticker, q, ids])
  const local = useMemo(() => {  // 서버가 없을 때: 문서 안의 근거
    const all = rep?.doc.evidence ?? []
    const want = ids ? new Set(ids) : null
    return all.filter((e) => (!want || want.has(e.id)) && (!kind || e.kind === kind) && (!ticker || e.tickers.some((t) => t.toUpperCase() === ticker.toUpperCase())) && (!q || e.title.toLowerCase().includes(q.toLowerCase()) || e.id.toLowerCase().includes(q.toLowerCase()) || (e.event_label_ko ?? "").includes(q)))
  }, [rep, ids, kind, ticker, q])
  const useRemote = remote !== null && remote !== "pending"
  const items = useRemote ? remote.items : local.slice(page * PAGE, (page + 1) * PAGE)
  const total = useRemote ? remote.total : local.length
  // 종류별 건수: 본문에 쓰인 근거를 볼 때는 그 범위(문서에 실린 근거)로 센다 — 서버 건수는 읽은 자료 전체 기준이다
  const byKind = canScope && scope === "cited" ? countKinds(rep?.doc.evidence ?? []) : useRemote ? remote.by_kind : (rep?.doc.evidence_summary?.by_kind ?? countKinds(rep?.doc.evidence ?? []))
  const tickers = useMemo(() => Array.from(new Set((rep?.doc.evidence ?? []).flatMap((e) => e.tickers))).sort(), [rep])
  return (
    <SidePanel title={filter.title ?? "출처 전체"} close={close}>
      {canScope && (
        <div role="radiogroup" aria-label="보여 줄 범위" className="mb-3 inline-flex rounded-xl bg-slate-100 p-1 text-sm">
          {([["cited", "본문에 쓰인 근거", citedIds.length], ["all", "읽은 자료 전체", rep?.doc.evidence_summary?.total ?? null]] as const).map(([v, label, n]) => (
            <button key={v} type="button" role="radio" aria-checked={scope === v} onClick={() => setScope(v)} className={`rounded-lg px-3 py-1.5 font-semibold ${scope === v ? "bg-white text-slate-950 shadow-sm" : "text-slate-600 hover:text-slate-900"}`}>{label}{n !== null && <span className="ml-1.5 font-normal tabular-nums text-slate-500">{n.toLocaleString("en-US")}</span>}</button>
          ))}
        </div>
      )}
      <div className="grid grid-cols-[1fr_auto_auto] gap-2">
        <label className="relative"><Search className="pointer-events-none absolute left-3 top-3 size-4 text-slate-400" /><input aria-label="근거 검색" value={q} onChange={(e) => setQ(e.target.value)} placeholder="제목·ID·사건 종류 검색" className={`${inputClass} pl-9`} /></label>
        <select aria-label="종류" value={kind} onChange={(e) => setKind(e.target.value)} className={inputClass}><option value="">모든 종류</option>{KINDS.map((k) => <option key={k} value={k}>{ko(k)}{byKind[k] !== undefined ? ` (${byKind[k]})` : ""}</option>)}</select>
        <select aria-label="종목" value={ticker} onChange={(e) => setTicker(e.target.value)} className={inputClass}><option value="">모든 종목</option>{tickers.map((t) => <option key={t} value={t}>{t}</option>)}</select>
      </div>
      <p className="mt-3 text-xs text-slate-500">{total}건{filter.ids ? " (이 블록이 인용한 근거)" : ""}{!useRemote && remote === null ? " · 서버 색인을 쓸 수 없어 문서 안의 근거만 보여 줍니다" : ""}</p>
      {remote === "pending" && local.length === 0 ? <Loading label="근거를 불러오는 중…" /> : (
        <ul className="mt-3 divide-y divide-slate-100">
          {items.map((e) => (
            <li key={e.id}>
              <button type="button" onClick={() => onOpen(e)} title={e.id} className="flex w-full items-start gap-3 py-3 text-left hover:bg-slate-50">
                <span className={`mt-0.5 w-9 shrink-0 text-right text-xs font-bold tabular-nums ${rep && rep.numberOf(e.id) !== e.id ? "text-blue-700" : "text-slate-300"}`}>{rep && rep.numberOf(e.id) !== e.id ? `[${rep.numberOf(e.id)}]` : "–"}</span>
                <span className="min-w-0 flex-1">
                  <span className="block truncate text-sm font-semibold text-slate-900">{evidenceTitle(e, nameOf)}</span>
                  <span className="block truncate text-xs text-slate-500">{kindPlain(e.kind)}{e.kind !== "financial" && e.tickers.length ? ` · ${e.tickers.map(nameOf).join(", ")}` : ""} · {String((e.kind === "disclosure" ? e.available_on : e.published_at ?? e.data_as_of) ?? "–").slice(0, 10)}{e.source && e.kind === "news" ? ` · ${e.source}` : ""}</span>
                </span>
              </button>
            </li>
          ))}
          {items.length === 0 && <li className="py-6 text-center text-sm text-slate-500">조건에 맞는 근거가 없습니다.</li>}
        </ul>
      )}
      <Pagination page={page} pages={Math.max(1, Math.ceil(total / PAGE))} onChange={setPage} total={total} pageSize={PAGE} />
    </SidePanel>
  )
}

function countKinds(items: EvidenceRecord[]): Record<string, number> {
  const out: Record<string, number> = {}
  for (const e of items) out[e.kind] = (out[e.kind] ?? 0) + 1
  return out
}
