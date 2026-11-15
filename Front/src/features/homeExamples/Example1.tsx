import { useState } from "react"
import { ChevronRight, Compass, FileText } from "lucide-react"
import { navigate } from "../../app/router"
import { EXAMPLE_REPORT_ID } from "../tutorial/exampleReport"
import { date, pct } from "../../lib/format"
import { reportName } from "../../lib/reportName"
import type { SectorTrendsState } from "../home/sectorTrends"
import { ExampleFrame, PAGE, PROCESS_STEPS, SwitchGroup, topSectors, trendsEmptyText, useHomeModel } from "./shared"
import { CARD, H2, IdeaCard, QUIET, TITLE, returnTone } from "./tossParts"

const TOP_LINK = "inline-flex items-center gap-1.5 rounded-[12px] px-3 py-2 text-[14px] font-medium text-[#646B77] transition hover:bg-white hover:text-[#34383F]"

/**
 * 홈 시안 1 (#/home/1): 알약을 빼고, 제목에서 무엇이 나오는지 말하고, 작은 그림으로 흐름을 보여 준다.
 * 입력 옆에 「이렇게 진행돼요」(분석 순서 5단계, 소개 화면과 같은 순서 · 1단계 「지금 여기」), 아래에 기존 카드 3개. (예전 구성 B 의 5단계 흐름 띠는 시안 4 로 옮겼다)
 * color: mix = 강조 #4880EE + 버튼 진한 파랑 / all = 전부 #4880EE (주소 ?color=all, toss.css).
 */
export function Example1({ color, bare }: { color: "mix" | "all"; bare?: boolean }) {
  const m = useHomeModel()
  const go = (c: "mix" | "all") => navigate({ page: "home-example", n: 1, ...(c === "all" ? { color: c } : {}) }, { scroll: false })
  const options = <SwitchGroup label="색" items={[{ label: "버튼 진한 파랑", on: color === "mix", go: () => go("mix") }, { label: "전부 #4880EE", on: color === "all", go: () => go("all") }]} />
  return (
    <ExampleFrame m={m} n={1} theme="toss" color={color} bare={bare} options={options}>{(s) => (
      <div className={`${PAGE} gap-4 text-[#646B77]`}>
        <header className="flex items-start justify-between gap-8">
          <h1 className={TITLE}>투자 아이디어를 적으면<br />종목과 비중, 과거 성과를 리포트로 보여드립니다</h1>
          <div className="flex shrink-0 gap-1 pt-1.5">
            <button type="button" onClick={() => m.setTour(0)} className={TOP_LINK}><Compass className="size-4" aria-hidden />둘러보기</button>
            <button type="button" onClick={() => navigate({ page: "tutorial" })} className={TOP_LINK}><FileText className="size-4" aria-hidden />리포트 보는 법</button>
          </div>
        </header>
        <>
          <div className="grid flex-1 grid-cols-[minmax(0,1fr)_340px] gap-4">
            <IdeaCard m={m} s={s} row={false} />
            <section aria-labelledby="x1-after" className={`${CARD} flex flex-col px-6 py-5`}>
              <h2 id="x1-after" className={H2}>이렇게 진행돼요</h2>
              <ol aria-label="분석 순서" className="mt-3 space-y-2">
                {PROCESS_STEPS.map((st, i) => (
                  <li key={st.title} aria-current={i === 0 ? "step" : undefined} className="relative flex gap-3">
                    {i < PROCESS_STEPS.length - 1 && <span aria-hidden className="absolute left-3 top-7 h-[calc(100%-24px)] w-px bg-[#D5DAE0]" />}
                    <span aria-hidden className={`relative grid size-6 shrink-0 place-items-center rounded-full text-[12px] font-bold ${i === 0 ? "hp-btn" : "bg-[#EEF3FE] hp-accent-text"}`}>{i + 1}</span>
                    <span className="min-w-0">
                      <span className="flex items-center gap-1.5"><b className="text-[15px] font-bold text-[#34383F]">{st.title}</b>{i === 0 && <span className="hp-accent-text text-[12px] font-bold">지금 여기</span>}</span>
                      <span className="block text-[13px] leading-[18px]">{st.body}</span>
                    </span>
                  </li>
                ))}
              </ol>
              <button type="button" onClick={() => navigate({ page: "report", reportId: EXAMPLE_REPORT_ID })} className="hp-accent-text mt-auto inline-flex items-center gap-1 self-start pt-3 text-[14px] font-semibold hover:underline">예시 리포트 보기<ChevronRight className="size-4" aria-hidden /></button>
            </section>
          </div>
          <div className="grid grid-cols-3 gap-4">
            <section data-tour="home-profile" className={`${CARD} p-6`}>
              <div className="flex items-center justify-between gap-3"><h2 className={H2}>내 투자조건</h2><button type="button" onClick={() => navigate({ page: "profile" })} className="hp-accent-text text-[13px] font-semibold hover:underline">내 투자조건 보기</button></div>
              <dl className="mt-4 grid grid-cols-[68px_minmax(0,1fr)] gap-x-3 gap-y-2.5 text-[14px]">
                {s.rows.map(([k, v]) => <div key={k} className="contents"><dt>{k}</dt><dd className="font-semibold text-[#34383F]">{v}</dd></div>)}
              </dl>
            </section>
            {m.trends.supported && <SectorCard trends={m.trends} defaultMarket={s.market} busy={m.busy} onPrompt={(t) => void m.submit(t)} />}
            <section data-tour="home-reports" className={`${CARD} p-6`}>
              <div className="flex items-center justify-between gap-3"><h2 className={H2}>최근 분석 리포트</h2><button type="button" onClick={() => navigate({ page: "reports" })} className="hp-accent-text text-[13px] font-semibold hover:underline">전체 보기</button></div>
              <div className="-mx-2 mt-2">
                {m.reports.status === "error" && <p className="px-2 py-2 text-[13px] text-red-700">{m.reports.error}</p>}
                {(m.reports.data ?? []).slice(0, 3).map((r) => (
                  <button key={r.run_id} type="button" onClick={() => navigate({ page: "report", reportId: r.report_id ?? r.run_id })} className="flex w-full items-center justify-between gap-2 rounded-[14px] px-2 py-2 text-left transition hover:bg-[#F2F5F7]">
                    <span className="min-w-0"><span className="block truncate text-[14px] font-semibold text-[#34383F]">{reportName(r)}</span><span className="mt-0.5 block text-[12px]">{date(r.created_at)} · 기준일 {r.as_of}</span></span>
                    <ChevronRight className="size-4 shrink-0 text-[#6B7684]" aria-hidden />
                  </button>
                ))}
                {m.reports.status === "ready" && (m.reports.data ?? []).length === 0 && <p className="px-2 py-2 text-[14px]">아직 완료된 분석이 없습니다.</p>}
              </div>
            </section>
          </div>
        </>
      </div>
    )}</ExampleFrame>
  )
}

/** 구성 A: 요즘엔 뭐가 좋아요? 카드. 섹터를 고르고 아래 문장을 누르면 그 문장으로 분석을 시작한다 (기존 홈과 같은 동작). */
function SectorCard({ trends, defaultMarket, busy, onPrompt }: { trends: SectorTrendsState; defaultMarket: "US" | "KR"; busy: boolean; onPrompt: (idea: string) => void }) {
  const markets = trends.data?.markets ?? []
  const [code, setCode] = useState<"US" | "KR">(defaultMarket)
  const [picked, setPicked] = useState<string | null>(null)
  const { end, rows } = topSectors(trends, code)
  const cur = rows.find((r) => r.code === picked) ?? rows[0] ?? null
  return (
    <section data-tour="home-trends" aria-labelledby="hp-trends-title" className={`${CARD} flex flex-col p-6`}>
      <div className="flex items-center justify-between gap-3">
        <h2 id="hp-trends-title" className={H2}>요즘엔 뭐가 좋아요?</h2>
        {markets.length > 1 && (
          <div role="group" aria-label="시장" className="flex shrink-0 rounded-[10px] bg-[#F2F5F7] p-0.5">
            {markets.map((x) => (
              <button key={x.code} type="button" aria-pressed={x.code === code} onClick={() => { setCode(x.code); setPicked(null) }}
                className={`rounded-[8px] px-2.5 py-1 text-[12px] font-semibold transition ${x.code === code ? "bg-white text-[#34383F]" : "text-[#646B77] hover:text-[#34383F]"}`}>{x.label_ko}</button>
            ))}
          </div>
        )}
      </div>
      {end && <p className="mt-1 text-[12px]">최근 한 달 · 기준일 {end}</p>}
      {rows.length === 0 ? <p className="mt-3 text-[14px]">{trendsEmptyText(trends)}</p> : (
        <ul className="-mx-2 mt-2">
          {rows.map((r) => (
            <li key={r.code}>
              <button type="button" aria-pressed={r.code === cur?.code} onClick={() => setPicked(r.code)}
                className={`flex w-full items-center justify-between gap-2 rounded-[14px] px-2 py-1 text-left transition ${r.code === cur?.code ? "bg-[#EEF3FE]" : "hover:bg-[#F2F5F7]"}`}>
                <span className="min-w-0 truncate text-[14px] font-semibold text-[#34383F]">{r.name_ko} <span className="font-normal text-[#646B77]">· {r.n}개 중 {r.up}개 상승</span></span>
                <span className={`shrink-0 text-[14px] font-bold tabular-nums ${returnTone(r.avg_return)}`}>{pct(r.avg_return)}</span>
              </button>
            </li>
          ))}
        </ul>
      )}
      {cur && <div className="mt-auto pt-2"><button type="button" data-tour="home-trend-prompt" disabled={busy} title={cur.prompt_ko} onClick={() => onPrompt(cur.prompt_ko)} className={`${QUIET} block w-full truncate px-3.5 py-2.5 text-left text-[13px]`}>{cur.prompt_ko}</button></div>}
    </section>
  )
}
