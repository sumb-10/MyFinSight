import { useEffect, useId, useRef, useState } from "react"
import { Search, X } from "lucide-react"
import { useService } from "../../app/providers"
import { stockLabel, type ProposedStock } from "../../api/proposed"
import { MockTag } from "../report/proposedView"
import { InfoTip } from "./inputs"

// 종목 이름 (제안 기능): 서비스에 종목 검색·조회(searchStocks·getStocks)가 있을 때만 쓴다 — 지금은 목업뿐.
// 저장 값은 그대로 티커 문자열 목록이고, 화면에만 「회사명 (티커)」로 보인다.

/** 티커 → 「회사명 (티커)」 바꾸는 함수. 서비스에 getStocks 가 없으면 null (일반 모드: 지금처럼 티커만). */
export function useStockNames(tickers: string[]): ((t: string) => string) | null {
  const svc = useService()
  const [names, setNames] = useState<Record<string, ProposedStock>>({})
  const key = [...new Set(tickers)].sort().join(",")
  useEffect(() => {
    if (!svc.getStocks || !key) return
    const need = key.split(",").filter((t) => !names[t])
    if (need.length) void svc.getStocks(need).then((xs) => setNames((m) => ({ ...m, ...Object.fromEntries(xs.map((x) => [x.ticker, x])) })), () => {})
  }, [svc, key])  // eslint-disable-line react-hooks/exhaustive-deps -- 이미 받은 이름은 다시 묻지 않는다
  return svc.getStocks ? (t: string) => stockLabel(names[t], t) : null
}

const looksLikeTicker = (s: string) => /^[A-Za-z]{1,5}$|^\d{6}(\.K[SQ])?$/.test(s.trim())

/** 회사 이름·티커로 찾아 고르는 종목 입력 (목업). 고른 종목은 칩으로 보이고, 저장은 티커로 된다. */
export function StockPicker({ label, values, onChange, error, other }: { label: string; values: string[]; onChange: (v: string[]) => void; error?: string; other?: { label: string; values: string[] } }) {
  const svc = useService()
  const id = useId()
  const [q, setQ] = useState("")
  const [hits, setHits] = useState<ProposedStock[]>([])
  const [open, setOpen] = useState(false)
  const [active, setActive] = useState(0)
  const [searched, setSearched] = useState("")
  const name = useStockNames(values) ?? ((t: string) => t)
  const box = useRef<HTMLDivElement>(null)
  useEffect(() => {
    const k = q.trim()
    if (!k || !svc.searchStocks) { setHits([]); setSearched(""); return }
    const t = setTimeout(() => void svc.searchStocks!(k).then((xs) => { setHits(xs); setActive(0); setSearched(k) }, () => setHits([])), 150)
    return () => clearTimeout(t)
  }, [q, svc])
  useEffect(() => {
    if (!open) return
    const click = (e: MouseEvent) => { if (!box.current?.contains(e.target as Node)) setOpen(false) }
    window.addEventListener("mousedown", click)
    return () => window.removeEventListener("mousedown", click)
  }, [open])
  const add = (t: string) => { const v = t.trim().toUpperCase(); if (v && !values.includes(v)) onChange([...values, v]); setQ(""); setHits([]); setOpen(false) }
  const key = (e: React.KeyboardEvent<HTMLInputElement>) => {
    if (e.nativeEvent.isComposing) return
    if (e.key === "ArrowDown") { e.preventDefault(); setOpen(true); setActive((a) => Math.min(a + 1, Math.max(hits.length - 1, 0))) }
    else if (e.key === "ArrowUp") { e.preventDefault(); setActive((a) => Math.max(a - 1, 0)) }
    else if (e.key === "Enter") { e.preventDefault(); const h = hits[active]; if (h && !values.includes(h.ticker)) add(h.ticker) }
    else if (e.key === "Escape") setOpen(false)
    else if (e.key === "Backspace" && q === "" && values.length) onChange(values.slice(0, -1))
  }
  const showList = open && q.trim() !== ""
  const listId = `${id}-list`
  return (
    <div ref={box}>
      <div className="mb-2 flex items-center gap-1"><label htmlFor={id} className="text-sm font-semibold text-slate-700">{label}</label><InfoTip label={label}>회사 이름(한글·영문)이나 종목 코드(티커)로 찾아 고릅니다. 저장은 티커로 됩니다. 목업 종목 목록에서만 찾습니다.</InfoTip><MockTag /></div>
      <div className={`flex flex-wrap items-center gap-1.5 rounded-xl border bg-white px-2 py-1.5 focus-within:border-blue-400 focus-within:ring-2 focus-within:ring-blue-100 ${error ? "border-red-300" : "border-slate-200"}`}>
        {values.map((v) => (
          <span key={v} className="inline-flex items-center gap-1 rounded-lg bg-blue-50 px-2 py-1 text-xs font-semibold text-blue-800">
            {name(v)}
            <button type="button" aria-label={`${name(v)} 삭제`} onClick={() => onChange(values.filter((x) => x !== v))} className="rounded p-0.5 hover:bg-blue-100 focus:outline-none focus:ring-2 focus:ring-blue-500"><X className="size-3" /></button>
          </span>
        ))}
        <span className="flex min-w-36 flex-1 items-center gap-1.5 px-1">
          <Search className="size-4 shrink-0 text-slate-400" aria-hidden="true" />
          <input id={id} role="combobox" aria-expanded={showList} aria-controls={listId} aria-autocomplete="list" aria-activedescendant={showList && hits[active] ? `${id}-${hits[active].ticker}` : undefined}
            className="min-w-0 flex-1 bg-transparent py-1 text-sm text-slate-900 outline-none placeholder:text-slate-400" value={q} placeholder={values.length ? "" : "회사 이름이나 티커로 찾기 (예: 마이크론, MU)"}
            onChange={(e) => { setQ(e.target.value); setOpen(true) }} onFocus={() => setOpen(true)} onKeyDown={key} />
        </span>
      </div>
      {showList && (
        <div className="relative">
          <ul id={listId} role="listbox" aria-label={`${label} 검색 결과`} className="absolute inset-x-0 top-1 z-30 max-h-72 overflow-y-auto rounded-xl border border-slate-200 bg-white py-1 shadow-xl">
            {hits.map((h, i) => {
              const taken = values.includes(h.ticker), clash = other?.values.includes(h.ticker)
              return (
                <li key={h.ticker} id={`${id}-${h.ticker}`} role="option" aria-selected={i === active} aria-disabled={taken}
                  onMouseDown={(e) => e.preventDefault()} onMouseEnter={() => setActive(i)} onClick={() => !taken && add(h.ticker)}
                  className={`flex cursor-pointer items-center justify-between gap-3 px-3 py-2 text-sm ${i === active ? "bg-blue-50" : ""} ${taken ? "cursor-default opacity-50" : ""}`}>
                  <span className="min-w-0"><span className="font-semibold text-slate-900">{h.name_ko}</span> <span className="font-mono text-xs font-semibold text-slate-600">{h.ticker}</span><span className="block truncate text-[11px] text-slate-500">{h.name_en} · {h.sector_ko} · {h.market === "KR" ? "한국" : "미국"}</span></span>
                  <span className="shrink-0 text-[11px] font-semibold text-slate-500">{taken ? "추가됨" : clash ? `${other!.label}에 있음` : ""}</span>
                </li>
              )
            })}
            {hits.length === 0 && searched === q.trim() && (
              <li className="px-3 py-2.5 text-xs leading-5 text-slate-500">‘{q.trim()}’와 맞는 종목이 목업 목록에 없습니다.{looksLikeTicker(q) && <> <button type="button" className="font-semibold text-blue-700 hover:underline" onMouseDown={(e) => e.preventDefault()} onClick={() => add(q)}>티커 {q.trim().toUpperCase()} 그대로 추가</button></>}</li>
            )}
          </ul>
        </div>
      )}
      {error ? <p className="mt-1.5 text-xs font-medium text-red-600">{error}</p> : <p className="mt-1.5 text-xs leading-5 text-slate-500">회사 이름이나 티커를 적으면 목록이 나옵니다. ↑↓로 고르고 Enter로 추가합니다.</p>}
    </div>
  )
}
