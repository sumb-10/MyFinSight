import type { KeyboardEvent } from "react"
import { ChevronRight, Loader2, SlidersHorizontal, X } from "lucide-react"
import { navigate } from "../../app/router"
import { pct } from "../../lib/format"
import { ActionError, IdeaPending } from "../analysis/flow"
import { OVERRIDE_LABELS, overrideText } from "../home/DetailConditions"
import { EXAMPLE_IDEAS } from "../home/HomeScreen"
import { ExampleFrame, GuideLinks, PAGE, PROCESS_STEPS, topSectors, trendsEmptyText, useHomeModel } from "./shared"
import { CARD, returnTone } from "./tossParts"

/** 예시 문장(EXAMPLE_IDEAS)에 붙이는 한 줄 설명. 순서가 같다. */
const EXAMPLE_HINTS = ["업종과 지역만 정하고 종목은 맡기는 방식", "배당과 안정성을 먼저 보는 방식", "관심 있는 기업과 기간을 정하는 방식"]

const LABEL = "text-[13px] font-bold text-[#646B77]"
/** 누르면 그 문장으로 바로 시작하는 예시 카드 (흰 판 안의 회색 면) */
const STARTER = "flex w-full flex-col rounded-[16px] bg-[#F2F5F7] px-4 py-3 text-left transition hover:bg-[#E7EBEF] focus:outline-none focus-visible:shadow-[0_0_0_2px_#4880EE] disabled:cursor-not-allowed disabled:opacity-50"
const FOOT_LINK = "inline-flex items-center gap-1 rounded-[8px] px-1.5 py-0.5 text-[13px] text-[#646B77] transition hover:text-[#34383F]"

/**
 * 홈 시안 2 (#/home/2): 판 하나 안에 질문형 제목 → 분석 순서 5단계(소개 화면과 같은 순서, 1단계에 「지금 여기」) → 예시 카드(분류별 열) → 입력창을 위에서 아래로 잇는다.
 * 세 번째 열은 분석에 쓰는 내 투자조건이다 (적지 않은 조건은 이 값을 쓴다).
 * 예시와 입력창이 같은 판 안에 있어 「예시를 누르거나 아래에 적는다」가 한 흐름으로 읽힌다. 예시 카드를 누르면 그 문장으로 바로 시작한다.
 * 입력창은 채팅처럼 Enter 로 시작하고 Shift+Enter 로 줄을 바꾼다 (한글 조합 중의 Enter 는 무시).
 */
export function Example2({ bare }: { bare?: boolean }) {
  const m = useHomeModel()
  const { busy } = m
  const onKey = (e: KeyboardEvent<HTMLTextAreaElement>) => {
    if (e.key !== "Enter" || e.shiftKey || e.nativeEvent.isComposing) return
    e.preventDefault()
    if (!busy) void m.submit()
  }
  return (
    <ExampleFrame m={m} n={2} theme="toss" bare={bare}>{(s) => {
      const sectors = m.trends.supported ? topSectors(m.trends, s.market).rows : []
      return (
        <div className={`${PAGE} text-[#646B77]`}>
          <section className={`${CARD} flex flex-1 flex-col px-10 pb-6 pt-8`}>
            <div className="flex flex-1 flex-col justify-center">
            <div className="text-center">
              <h1 className="text-[28px] font-extrabold tracking-[-0.02em] text-[#34383F]">어떤 투자를 해보고 싶으세요?</h1>
              <p className="mt-2 text-[15px]">아래에 적거나, 예시를 누르면 바로 시작합니다.</p>
            </div>

            <ol aria-label="분석 순서" className="mt-7 grid w-full grid-cols-5 gap-3">
              {PROCESS_STEPS.map((st, i) => (
                <li key={st.title} aria-current={i === 0 ? "step" : undefined} className="relative flex min-w-0 flex-col items-center text-center">
                  {i < PROCESS_STEPS.length - 1 && <span aria-hidden className="absolute left-1/2 top-3.5 h-px w-full bg-[#D5DAE0]" />}
                  <span aria-hidden className={`relative grid size-7 place-items-center rounded-full text-[13px] font-bold ${i === 0 ? "hp-btn" : "bg-[#F2F5F7] text-[#646B77]"}`}>{i + 1}</span>
                  <b className="mt-2 block text-[15px] font-bold text-[#34383F]">{st.title}</b>
                  <span className="mt-0.5 block text-[13px] leading-5">{st.body}</span>
                  {i === 0 && <span className="hp-accent-text mt-1 text-[12px] font-bold">지금 여기</span>}
                </li>
              ))}
            </ol>

            <div className={`mt-7 grid w-full gap-5 ${m.trends.supported ? "grid-cols-[minmax(0,1fr)_minmax(0,1fr)_minmax(0,0.78fr)]" : "grid-cols-[minmax(0,1fr)_minmax(0,0.78fr)]"}`}>
              <div>
                <h2 className={LABEL}>이런 아이디어도 돼요</h2>
                <ul data-tour="home-examples" aria-label="예시 문장" className="mt-2 space-y-2">
                  {EXAMPLE_IDEAS.map((t, i) => (
                    <li key={t}><button type="button" disabled={busy} onClick={() => void m.submit(t)} className={STARTER}>
                      <span className="text-[15px] font-semibold text-[#34383F]">{t}</span>
                      <span className="mt-0.5 text-[13px]">{EXAMPLE_HINTS[i] ?? ""}</span>
                    </button></li>
                  ))}
                </ul>
              </div>
              {m.trends.supported && (
                <div data-tour="home-trends">
                  <h2 className={LABEL}>요즘 강한 섹터로</h2>
                  {sectors.length === 0 ? <p className="mt-3 text-[14px]">{trendsEmptyText(m.trends)}</p> : (
                    <ul aria-label="요즘 강한 섹터" className="mt-2 space-y-2">
                      {sectors.map((r) => (
                        <li key={r.code}><button type="button" disabled={busy} title={r.prompt_ko} onClick={() => void m.submit(r.prompt_ko)} className={STARTER}>
                          <span className="text-[15px] font-semibold text-[#34383F]">{r.name_ko} 기업에 나눠 투자</span>
                          <span className="mt-0.5 text-[13px]">최근 한 달 <b className={`font-semibold tabular-nums ${returnTone(r.avg_return)}`}>{pct(r.avg_return)}</b> · {r.n}개 중 {r.up}개 상승</span>
                        </button></li>
                      ))}
                    </ul>
                  )}
                </div>
              )}
              <div data-tour="home-profile">
                <h2 className={LABEL}>이 조건으로 분석해요</h2>
                <div className="mt-2 rounded-[16px] bg-[#F2F5F7] px-4 py-3.5">
                  <dl className="grid grid-cols-[64px_minmax(0,1fr)] gap-x-2 gap-y-2 text-[13px]">
                    {s.rows.map(([k, v]) => <div key={k} className="contents"><dt>{k}</dt><dd className="font-semibold text-[#34383F]">{v}</dd></div>)}
                  </dl>
                  <p className="mt-3 text-[12px] leading-5">적지 않은 조건은 이 값을 써요. 꼭 필요한데 빠진 조건은 2단계에서 물어봐요.</p>
                  <button type="button" onClick={() => navigate({ page: "profile" })} className="hp-accent-text mt-2 inline-flex items-center gap-0.5 text-[13px] font-semibold hover:underline">내 투자조건 보기<ChevronRight className="size-4" aria-hidden /></button>
                </div>
              </div>
            </div>

            </div>

            <div className="w-full pt-6">
              {busy && <div className="pb-3"><IdeaPending /></div>}
              {m.apiErr && !busy && <div className="pb-3"><ActionError title="아이디어를 해석하지 못했습니다" message={m.apiErr} retry={() => void m.submit()} /></div>}
              <div data-tour="home-idea" className="rounded-[18px] bg-[#F2F5F7] p-2 transition-shadow focus-within:shadow-[0_0_0_2px_#4880EE]">
                {m.nOverrides > 0 && (
                  <div className="flex flex-wrap items-center gap-1.5 px-2 pt-1">
                    {Object.entries(m.overrides).map(([k, v]) => <span key={k} className="hp-accent-text rounded-full bg-white px-2.5 py-1 text-xs font-semibold">{OVERRIDE_LABELS[k] ?? k} {overrideText(k, v)}</span>)}
                    <button type="button" className="text-xs hover:text-[#34383F] disabled:opacity-40" disabled={busy} onClick={() => m.setOverrides({})}><X className="inline size-3" aria-hidden /> 모두 지우기</button>
                  </div>
                )}
                <div className="flex items-end gap-2">
                  <textarea value={m.idea} readOnly={busy} aria-busy={busy} aria-label="투자하고 싶은 내용" aria-describedby="x2-hint" rows={1} onChange={(e) => m.type(e.target.value)} onKeyDown={onKey}
                    className="max-h-32 min-h-11 flex-1 resize-none border-0 bg-transparent px-3 py-2.5 text-[16px] leading-6 text-[#34383F] outline-none [field-sizing:content] placeholder:text-[#646B77]"
                    placeholder="예: 미국과 한국의 반도체 기업에 나눠 투자하고 싶어요." />
                  <span data-tour="home-detail" className="inline-flex"><button type="button" onClick={() => m.setDetail(true)} disabled={busy} className="inline-flex h-11 items-center gap-1.5 rounded-[12px] px-3 text-[14px] font-semibold text-[#34383F] transition hover:bg-white disabled:opacity-50"><SlidersHorizontal className="size-4" aria-hidden />상세 조건{m.nOverrides ? ` (${m.nOverrides})` : ""}</button></span>
                  <span data-tour="home-submit" className="inline-flex"><button type="button" onClick={() => void m.submit()} disabled={busy} className="hp-btn inline-flex h-11 items-center gap-1.5 rounded-[12px] px-4 text-[14px] font-semibold transition disabled:cursor-not-allowed disabled:opacity-60">{busy ? <><Loader2 className="size-4 animate-spin" aria-hidden />아이디어 해석 중…</> : <>투자조건 확인하기<ChevronRight className="size-4" aria-hidden /></>}</button></span>
                </div>
              </div>
              {m.error && <p className="px-1 pt-2 text-[13px] font-medium text-red-700">{m.error}</p>}
              <div className="mt-2.5 flex items-center justify-between gap-4 px-1">
                <p id="x2-hint" className="text-[13px]">Enter로 시작 · Shift+Enter로 줄 바꿈</p>
                <GuideLinks m={m} linkClass={FOOT_LINK} />
              </div>
            </div>
          </section>
        </div>
      )
    }}</ExampleFrame>
  )
}
