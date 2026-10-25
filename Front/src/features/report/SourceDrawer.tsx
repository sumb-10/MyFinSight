import { useEffect, useMemo, useState } from "react"
import { Search } from "lucide-react"
import type { EvidencePage, EvidenceRecord } from "../../api/types"
import { ko } from "../../lib/format"
import { Loading, Pagination, SidePanel, inputClass } from "../../ui"
import { type DrawerFilter, useReport } from "./context"
import { useService } from "../../app/providers"

const PAGE = 50
const KINDS = ["news", "disclosure", "financial", "calc"]

/** 출처 드로어: 근거 색인을 검색·종류·종목으로 걸러 50건씩 본다. 서버 /evidence 가 없으면(404) 문서 안의 근거로 대신한다. */
export function SourceDrawer({ filter, close, onOpen }: { filter: DrawerFilter; close: () => void; onOpen: (e: EvidenceRecord) => void }) {
  const rep = useReport()
  const svc = useService()
  const [q, setQ] = useState("")
  const [kind, setKind] = useState(filter.kind ?? "")
  const [ticker, setTicker] = useState(filter.ticker ?? "")
  const [page, setPage] = useState(0)
  const [remote, setRemote] = useState<EvidencePage | null | "pending">("pending")
  useEffect(() => { setPage(0) }, [q, kind, ticker])
  useEffect(() => {
    if (!rep) { setRemote(null); return }
    let alive = true
    setRemote("pending")
    svc.getReportEvidence(rep.reportId, { offset: page * PAGE, limit: PAGE, kind: kind || undefined, ticker: ticker || undefined, q: q || undefined, ids: filter.ids ?? undefined })
      .then((p) => { if (alive) setRemote(p) }).catch(() => { if (alive) setRemote(null) })
    return () => { alive = false }
  }, [rep, svc, page, kind, ticker, q, filter.ids])
  const local = useMemo(() => {  // 서버가 없을 때: 문서 안의 근거
    const all = rep?.doc.evidence ?? []
    const want = filter.ids ? new Set(filter.ids) : null
    return all.filter((e) => (!want || want.has(e.id)) && (!kind || e.kind === kind) && (!ticker || e.tickers.some((t) => t.toUpperCase() === ticker.toUpperCase())) && (!q || e.title.toLowerCase().includes(q.toLowerCase()) || e.id.toLowerCase().includes(q.toLowerCase()) || (e.event_label_ko ?? "").includes(q)))
  }, [rep, filter.ids, kind, ticker, q])
  const useRemote = remote !== null && remote !== "pending"
  const items = useRemote ? remote.items : local.slice(page * PAGE, (page + 1) * PAGE)
  const total = useRemote ? remote.total : local.length
  const byKind = useRemote ? remote.by_kind : (rep?.doc.evidence_summary?.by_kind ?? countKinds(rep?.doc.evidence ?? []))
  const tickers = useMemo(() => Array.from(new Set((rep?.doc.evidence ?? []).flatMap((e) => e.tickers))).sort(), [rep])
  return (
    <SidePanel title={filter.title ?? "출처 전체"} close={close}>
      <div className="grid grid-cols-[1fr_auto_auto] gap-2">
        <label className="relative"><Search className="pointer-events-none absolute left-3 top-3 size-4 text-slate-400" /><input aria-label="근거 검색" value={q} onChange={(e) => setQ(e.target.value)} placeholder="제목·ID·사건 종류 검색" className={`${inputClass} pl-9`} /></label>
        <select aria-label="종류" value={kind} onChange={(e) => setKind(e.target.value)} className={inputClass}><option value="">모든 종류</option>{KINDS.map((k) => <option key={k} value={k}>{ko(k)}{byKind[k] !== undefined ? ` (${byKind[k]})` : ""}</option>)}</select>
        <select aria-label="종목" value={ticker} onChange={(e) => setTicker(e.target.value)} className={inputClass}><option value="">모든 종목</option>{tickers.map((t) => <option key={t} value={t}>{t}</option>)}</select>
      </div>
      <p className="mt-3 text-xs text-slate-500">{total}건{filter.ids ? " (이 블록이 인용한 근거)" : ""}{!useRemote && remote === null ? " · 서버 색인을 쓸 수 없어 문서 안의 근거만 보여 줍니다" : ""}{rep?.doc.evidence_summary ? ` · 색인 전체 ${rep.doc.evidence_summary.total}건` : ""}</p>
      {remote === "pending" && local.length === 0 ? <Loading label="근거를 불러오는 중…" /> : (
        <ul className="mt-3 divide-y divide-slate-100">
          {items.map((e) => (
            <li key={e.id}>
              <button type="button" onClick={() => onOpen(e)} className="flex w-full items-start gap-3 py-2.5 text-left hover:bg-slate-50">
                <span className="mt-0.5 w-14 shrink-0 text-[11px] font-semibold text-slate-500">{ko(e.kind)}</span>
                <span className="min-w-0 flex-1">
                  <span className="block truncate text-sm text-slate-800">{e.kind === "disclosure" && e.event_label_ko ? `${e.event_label_ko} · ` : ""}{e.title || e.id}</span>
                  <span className="block text-[11px] text-slate-400">{rep?.numberOf(e.id) !== e.id ? `[${rep?.numberOf(e.id)}] ` : ""}{e.id} · {e.tickers.join(", ") || "–"} · {(e.kind === "disclosure" ? e.available_on : e.published_at ?? e.data_as_of) ?? "–"}{e.source ? ` · ${e.source}` : ""}</span>
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
