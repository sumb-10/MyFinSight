import { useState } from "react"
import { RotateCcw } from "lucide-react"
import { pct } from "../../lib/format"
import type { SectorTrendsState } from "./sectorTrends"

/** 홈 '요즘엔 뭐가 좋아요?': 최근 한 달 성과가 좋았던 섹터(최대 3개, 시장별)와 고른 섹터의 추천 문장. 문장을 누르면 그 문장으로 분석을 시작한다. */
export function SectorTrendsBox({ trends, defaultMarket, busy, onPrompt }: { trends: SectorTrendsState; defaultMarket: "US" | "KR"; busy: boolean; onPrompt: (idea: string) => void }) {
  const markets = trends.data?.markets ?? []
  const [code, setCode] = useState<"US" | "KR">(defaultMarket)
  const [picked, setPicked] = useState<string | null>(null)
  const m = markets.find((x) => x.code === code) ?? markets[0] ?? null
  const shown = m ? m.top.flatMap((c) => m.sectors.filter((s) => s.code === c)) : []
  const cur = shown.find((s) => s.code === picked) ?? shown[0] ?? null
  const loadingPct = Math.round(Math.max(0, Math.min(1, trends.progress)) * 100)

  return (
    <section data-tour="home-trends" aria-labelledby="home-trends-title" className="flex h-full flex-col rounded-2xl border border-slate-200 bg-white p-5 shadow-sm">
      <div className="flex items-start justify-between gap-2">
        <h2 id="home-trends-title" className="font-bold text-slate-900">요즘엔 뭐가 좋아요?</h2>
        {markets.length > 1 && (
          <div role="group" aria-label="시장" className="flex shrink-0 rounded-lg bg-slate-100 p-0.5">
            {markets.map((x) => (
              <button key={x.code} type="button" aria-pressed={x.code === m?.code} onClick={() => { setCode(x.code); setPicked(null) }}
                className={`rounded-md px-2 py-0.5 text-xs font-semibold transition focus:outline-none focus:ring-2 focus:ring-blue-500 ${x.code === m?.code ? "bg-white text-slate-900 shadow-sm" : "text-slate-500 hover:text-slate-800"}`}>{x.label_ko}</button>
            ))}
          </div>
        )}
      </div>
      {m && <p className="mt-1 text-xs text-slate-400">최근 한 달 · 기준일 {m.end_date}</p>}

      {!m && trends.status === "error" && (
        <div className="mt-4 text-sm text-slate-600">
          <p>섹터 자료를 불러오지 못했습니다.</p>
          <button type="button" onClick={trends.retry} className="mt-2 inline-flex items-center gap-1 text-sm font-semibold text-blue-700 hover:underline"><RotateCcw className="size-3.5" aria-hidden />다시 시도</button>
        </div>
      )}
      {!m && trends.status !== "error" && (
        <div className="mt-4">
          <div role="progressbar" aria-label="섹터 자료 불러오는 중" aria-valuemin={0} aria-valuemax={100} aria-valuenow={loadingPct} className="h-1.5 overflow-hidden rounded-full bg-slate-100">
            <div className="h-full rounded-full bg-blue-700 transition-[width] duration-300" style={{ width: `${loadingPct}%` }} />
          </div>
          <p className="mt-2 text-xs tabular-nums text-slate-400">불러오는 중 {loadingPct}%</p>
        </div>
      )}
      {m && shown.length === 0 && <p className="mt-4 text-sm leading-6 text-slate-600">최근 한 달은 시장 평균보다 많이 오른 섹터가 없습니다.</p>}
      {shown.length > 0 && (
        <ul className="mt-3 space-y-1">
          {shown.map((s) => {
            const on = s.code === cur?.code
            return (
              <li key={s.code}>
                <button type="button" aria-pressed={on} onClick={() => setPicked(s.code)}
                  className={`flex w-full items-center justify-between gap-2 rounded-xl px-3 py-2 text-left transition focus:outline-none focus:ring-2 focus:ring-blue-500 ${on ? "bg-blue-50" : "hover:bg-slate-50"}`}>
                  <span className="min-w-0">
                    <span className="block truncate text-sm font-semibold text-slate-800">{s.name_ko}</span>
                    <span className="block text-[11px] text-slate-400">종목 {s.n}개 중 {s.up}개 상승</span>
                  </span>
                  <span className={`shrink-0 text-sm font-bold tabular-nums ${s.avg_return >= 0 ? "text-emerald-700" : "text-red-700"}`}>{pct(s.avg_return)}</span>
                </button>
              </li>
            )
          })}
        </ul>
      )}
      {cur && (
        <button type="button" data-tour="home-trend-prompt" disabled={busy} onClick={() => onPrompt(cur.prompt_ko)}
          className="mt-auto rounded-lg pt-3 text-left text-sm leading-5 text-slate-600 transition hover:text-blue-700 focus:outline-none focus:ring-2 focus:ring-blue-500 disabled:cursor-not-allowed disabled:opacity-50">* {cur.prompt_ko}</button>
      )}
    </section>
  )
}
