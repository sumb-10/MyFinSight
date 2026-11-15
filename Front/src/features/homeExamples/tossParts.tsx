import type { ReactNode } from "react"
import { ChevronRight, Loader2, SlidersHorizontal, X } from "lucide-react"
import { pct } from "../../lib/format"
import { ActionError, IdeaPending } from "../analysis/flow"
import { OVERRIDE_LABELS, overrideText } from "../home/DetailConditions"
import { EXAMPLE_IDEAS } from "../home/HomeScreen"
import type { SectorTrendsState } from "../home/sectorTrends"
import { topSectors, trendsEmptyText, type HomeModel, type ProfileSummary } from "./shared"
import "./toss.css"

// 토스풍 시안(1·4)이 같이 쓰는 조각: 카드 모양, 아이디어 입력 카드, 요즘 강한 섹터 한 줄.

export const CARD = "rounded-[24px] bg-white"
export const H2 = "text-[17px] font-bold text-[#34383F]"
export const QUIET = "rounded-[14px] bg-[#F2F5F7] text-[#34383F] transition hover:bg-[#E7EBEF] disabled:cursor-not-allowed disabled:opacity-50"
export const TITLE = "text-[34px] font-extrabold leading-[1.32] tracking-[-0.02em] text-[#34383F]"
export const returnTone = (v: number) => (v >= 0 ? "text-emerald-700" : "text-red-700")

/**
 * 아이디어 입력 카드. row = 예시 문장을 가로로 늘어놓고 요즘 강한 섹터를 같이 보여 준다.
 * header = 입력창 위에 같은 판 안으로 넣을 내용 (구분선으로 나눈다). 있으면 포커스 강조는 입력 영역에만 준다.
 * note = 버튼 줄 왼쪽에 둘 한 줄 (예: 내 투자조건 요약).
 */
export function IdeaCard({ m, s, row, header, note }: { m: HomeModel; s: ProfileSummary; row: boolean; header?: ReactNode; note?: ReactNode }) {
  const { busy } = m
  const ring = "transition-shadow focus-within:shadow-[0_0_0_2px_#4880EE]"
  const body = (
    <>
      <textarea value={m.idea} readOnly={busy} aria-busy={busy} aria-label="투자하고 싶은 내용" onChange={(e) => m.type(e.target.value)}
        className="min-h-[60px] w-full flex-1 resize-none border-0 bg-transparent p-1 text-[17px] leading-7 text-[#34383F] outline-none placeholder:text-[#646B77]"
        placeholder="예: 미국과 한국의 반도체 기업에 나눠 투자하고 싶어요. 특정 종목에 너무 집중하고 싶지는 않습니다." />
      {m.nOverrides > 0 && (
        <div className="flex flex-wrap items-center gap-2 pb-3">
          <span className="text-[13px] font-semibold">이번 분석에만 적용</span>
          {Object.entries(m.overrides).map(([k, v]) => <span key={k} className="hp-accent-text rounded-full bg-[#EEF3FE] px-3 py-1 text-[13px] font-semibold">{OVERRIDE_LABELS[k] ?? k} {overrideText(k, v)}</span>)}
          <button type="button" className="text-[13px] hover:text-[#34383F] disabled:opacity-40" disabled={busy} onClick={() => m.setOverrides({})}><X className="inline size-3.5" aria-hidden /> 모두 지우기</button>
        </div>
      )}
      {busy && <div className="pb-3"><IdeaPending /></div>}
      <div className={row ? "space-y-2" : ""}>
        <ul data-tour="home-examples" aria-label="예시 문장" className={row ? "flex flex-wrap gap-2" : "space-y-2"}>
          {EXAMPLE_IDEAS.map((t) => (
            <li key={t}><button type="button" disabled={busy} onClick={() => void m.submit(t)} className={`${QUIET} ${row ? "" : "w-full"} px-4 py-2 text-left text-[14px]`}>{t}</button></li>
          ))}
        </ul>
        {row && m.trends.supported && <SectorChips trends={m.trends} market={s.market} busy={busy} onPrompt={(t) => void m.submit(t)} />}
      </div>
      <div className={`mt-4 flex items-center gap-2 ${note ? "justify-between" : "justify-end"}`}>
        {note && <div className="min-w-0 flex-1 text-[13px]">{note}</div>}
        <span data-tour="home-detail" className="inline-flex"><button type="button" onClick={() => m.setDetail(true)} disabled={busy} className={`${QUIET} inline-flex h-11 items-center gap-2 px-4 text-[15px] font-semibold`}><SlidersHorizontal className="size-4" aria-hidden />상세 조건{m.nOverrides ? ` (${m.nOverrides})` : ""}</button></span>
        <span data-tour="home-submit" className="inline-flex"><button type="button" onClick={() => void m.submit()} disabled={busy} className="hp-btn inline-flex h-11 items-center gap-1.5 rounded-[14px] px-5 text-[15px] font-semibold transition disabled:cursor-not-allowed disabled:opacity-60">{busy ? <><Loader2 className="size-4 animate-spin" aria-hidden />아이디어 해석 중…</> : <>투자조건 확인하기<ChevronRight className="size-4" aria-hidden /></>}</button></span>
      </div>
      {m.error && <p className="pt-2 text-right text-[13px] font-medium text-red-700">{m.error}</p>}
      {m.apiErr && !busy && <div className="pt-3"><ActionError title="아이디어를 해석하지 못했습니다" message={m.apiErr} retry={() => void m.submit()} /></div>}
    </>
  )
  if (!header) return <section data-tour="home-idea" className={`${CARD} flex min-h-[280px] flex-1 flex-col p-6 ${ring}`}>{body}</section>
  return (
    <section className={`${CARD} flex flex-1 flex-col`}>
      <div className="border-b border-[#E5E8EB] p-5">{header}</div>
      <div data-tour="home-idea" className={`flex flex-1 flex-col rounded-b-[24px] p-6 ${ring}`}>{body}</div>
    </section>
  )
}

/** 요즘 강한 섹터를 한 줄로 (이름표 없이, 칩 안에 「한 달」 수익률). 누르면 그 섹터의 추천 문장으로 분석을 시작한다 (문장은 마우스를 올리면 보인다). */
export function SectorChips({ trends, market, busy, onPrompt }: { trends: SectorTrendsState; market: "US" | "KR"; busy: boolean; onPrompt: (idea: string) => void }) {
  const { rows } = topSectors(trends, market)
  if (rows.length === 0) return <p data-tour="home-trends" className="pt-2 text-[14px]">{trendsEmptyText(trends)}</p>
  return (
    <ul data-tour="home-trends" aria-label="요즘 강한 섹터" className="flex flex-wrap gap-2">
      {rows.map((r) => (
        <li key={r.code}><button type="button" disabled={busy} title={r.prompt_ko} onClick={() => onPrompt(r.prompt_ko)} className={`${QUIET} inline-flex items-center gap-1.5 px-4 py-2 text-[14px]`}>{r.name_ko}<span className="text-[13px]">한 달</span><span className={`font-bold tabular-nums ${returnTone(r.avg_return)}`}>{pct(r.avg_return)}</span></button></li>
      ))}
    </ul>
  )
}

const MINI = "flex h-[76px] flex-col rounded-[12px] bg-white p-2 text-[11px] leading-[1.35]"

/**
 * 분석 순서 5단계(PROCESS_STEPS)의 작은 화면 그림 (시안 3 · 시안 4). 소개 화면(IntroScroll)의 장면을 홈 크기로 줄여, 움직이지 않게 그린 것이다.
 * 장식이라 화면 읽기에서는 숨기고(단계 제목·설명이 같은 뜻을 글로 전한다), 수익률 같은 숫자는 넣지 않는다.
 */
export function MiniScreen({ step, s }: { step: number; s: ProfileSummary }) {
  const chip = (on: boolean) => `rounded-full px-1.5 py-px text-[10px] font-semibold ${on ? "bg-[#4880EE] text-white" : "bg-[#F2F5F7] text-[#646B77]"}`
  const row = "flex items-center justify-between gap-1 border-b border-[#F2F5F7] py-0.5 last:border-0"
  return (
    <span aria-hidden className={MINI}>
      {step === 0 && <>
        <span className="text-[#34383F]">미국 반도체 기업에 3년 정도 나눠 투자<span className="ml-px inline-block h-3 w-px translate-y-0.5 bg-[#34383F]" /></span>
        <span className="mt-auto self-end rounded-[6px] bg-[#4880EE] px-1.5 py-0.5 text-[10px] font-semibold text-white">투자조건 확인 ›</span>
      </>}
      {step === 1 && <>
        <span className="self-start rounded-[8px] bg-[#F2F5F7] px-1.5 py-0.5 text-[#34383F]">어떤 기준으로 고를까요?</span>
        <span className="mt-auto flex gap-1"><span className={chip(true)}>최근 흐름</span><span className={chip(false)}>기업 규모</span><span className={chip(false)}>배당</span></span>
      </>}
      {step === 2 && <>
        <span className={row}><span>금액</span><b className="truncate font-semibold text-[#34383F]">{s.amount.split(" · ")[0]}</b></span>
        <span className={row}><span>기간</span><b className="font-semibold text-[#34383F]">{s.years}</b></span>
        <span className="mt-auto rounded-[6px] bg-[#4880EE] py-0.5 text-center text-[10px] font-semibold text-white">▷ 분석 시작</span>
      </>}
      {step === 3 && (
        <svg viewBox="0 0 120 44" className="h-full w-full" preserveAspectRatio="none">
          <polyline points="0,40 15,37 30,38 45,30 60,31 75,22 90,20 105,12 120,8" fill="none" stroke="#4880EE" strokeWidth="2" vectorEffect="non-scaling-stroke" />
          <polyline points="0,40 15,39 30,38 45,35 60,36 75,31 90,30 105,27 120,25" fill="none" stroke="#B0B8C1" strokeWidth="1.5" vectorEffect="non-scaling-stroke" />
        </svg>
      )}
      {step === 4 && <>
        <span className="h-2 w-3/4 rounded-full bg-[#D5DAE0]" />
        <span className="mt-1.5 h-1.5 w-full rounded-full bg-[#F2F5F7]" />
        <span className="mt-1 h-1.5 w-5/6 rounded-full bg-[#F2F5F7]" />
        <span className="mt-auto self-start rounded-full bg-[#EEF3FE] px-1.5 py-px text-[10px] font-semibold text-[#1D4ED8]">모의투자 진행 중</span>
      </>}
    </span>
  )
}
