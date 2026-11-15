import { ArrowRight, ChevronRight } from "lucide-react"
import { navigate } from "../../app/router"
import { useResource } from "../../state/useResource"
import { loadUi } from "../../state/uiStorage"
import { ExampleFrame, GuideLinks, PAGE, PROCESS_STEPS, SwitchGroup, useHomeModel } from "./shared"
import { CARD, IdeaCard, MiniScreen, TITLE } from "./tossParts"
// 토스페이스 원본 (tossface/LICENSE.txt)
import iconWrite from "./tossface/u270F.svg"
import iconAsk from "./tossface/u1F4AC.svg"
import iconCheck from "./tossface/u1F4CB.svg"
import iconChart from "./tossface/u1F4C8.svg"
import iconPaper from "./tossface/u1F9EA.svg"

const ICONS = [iconWrite, iconAsk, iconCheck, iconChart, iconPaper]
const TOP_LINK = "inline-flex items-center gap-1.5 rounded-[12px] px-3 py-2 text-[14px] font-medium text-[#646B77] transition hover:bg-white hover:text-[#34383F]"
const ACTION = "hp-accent-text inline-flex items-center gap-0.5 text-[13px] font-semibold hover:underline"

/** 단계 카드 아래의 내 상태: 글만 있거나(text), 누르면 그 화면으로 가는 링크(go) */
interface StepState { text: string; go?: () => void }

/**
 * 홈 시안 4 (#/home/4): 분석 순서 5단계(소개 화면과 같은 순서) 카드와 입력 카드를 따로 두고, 단계마다 지금 내 상태를 붙인다.
 * 1단계는 「지금 여기」(이 화면). 2단계는 답하다 만 요청, 4단계는 진행 중인 분석, 5단계는 리포트·모의투자 수와 그 화면 링크.
 * 내 투자조건은 순서가 아니라 준비물이라 단계에서 빼고 입력 영역 아래 한 줄로 둔다. 톤은 시안 1 과 같다 (toss.css).
 * 단계 그림: 기본은 작은 화면 그림(MiniScreen, 시안 3 의 「이렇게 진행돼요」 탭과 같은 그림), 주소 ?layout=b 는 토스페이스 아이콘.
 */
export function Example4({ layout, color, bare }: { layout: "a" | "b"; color: "mix" | "all"; bare?: boolean }) {
  const m = useHomeModel()
  const papers = useResource(() => m.svc.listPaper(), [m.svc])
  const runs = useResource(() => m.svc.listRuns(), [m.svc])
  const pictures = layout === "a"  // 단계 그림: 화면 그림(기본) / 아이콘(?layout=b)
  const go = (l: "a" | "b", c: "mix" | "all") => navigate({ page: "home-example", n: 4, ...(l === "b" ? { layout: l } : {}), ...(c === "all" ? { color: c } : {}) }, { scroll: false })
  const options = <>
    <SwitchGroup label="단계 그림" items={[{ label: "화면 그림", on: pictures, go: () => go("a", color) }, { label: "아이콘", on: !pictures, go: () => go("b", color) }]} />
    <SwitchGroup label="색" items={[{ label: "버튼 진한 파랑", on: color === "mix", go: () => go(layout, "mix") }, { label: "전부 #4880EE", on: color === "all", go: () => go(layout, "all") }]} />
  </>
  return (
    <ExampleFrame m={m} n={4} theme="toss" color={color} bare={bare} options={options}>{(s) => {
      const requestId = loadUi().activeRequestId ?? null
      const running = (runs.data ?? []).filter((r) => r.status === "queued" || r.status === "running" || r.status === "cancelling")
      const nReports = m.reports.data?.length ?? null
      const nActive = papers.data ? papers.data.filter((x) => x.status === "active").length : null
      const focusIdea = () => document.querySelector<HTMLTextAreaElement>('[data-tour="home-idea"] textarea')?.focus()
      const states: StepState[][] = [
        [{ text: "아래에 바로 적기", go: focusIdea }],
        [requestId ? { text: "답하다 만 질문 이어서", go: () => navigate({ page: "clarify", requestId }) } : { text: "적고 나면 물어봐요" }],
        [{ text: "확인해야 시작돼요" }],
        [running.length ? { text: `분석 ${running.length}개 진행 중`, go: () => navigate({ page: "run", runId: running[0].run_id }) } : { text: "진행 중인 분석 없음" }],
        [
          { text: nReports === null ? "리포트 불러오는 중" : `리포트 ${nReports}개`, go: () => navigate({ page: "reports" }) },
          { text: nActive === null ? "모의투자 불러오는 중" : `모의투자 ${nActive}개`, go: () => navigate({ page: "paper" }) },
        ],
      ]
      return (
        <div className={`${PAGE} gap-4 text-[#646B77]`}>
          <header className="flex items-start justify-between gap-8">
            <h1 className={TITLE}>아이디어에서 모의투자까지<br />다섯 단계면 돼요</h1>
            <GuideLinks m={m} className="pt-1.5" linkClass={TOP_LINK} />
          </header>
          <section aria-label="분석 순서" className={`${CARD} p-4`}>
            <ol className="flex items-stretch gap-6">
              {PROCESS_STEPS.map((st, i) => (
                <li key={st.title} aria-current={i === 0 ? "step" : undefined} className="flex min-w-0 flex-1 basis-0 items-stretch">
                  {i > 0 && <span aria-hidden className="-ml-6 flex w-6 shrink-0 items-center justify-center"><ArrowRight className="size-4 text-[#6B7684]" strokeWidth={1.75} /></span>}
                  <div className={`flex min-w-0 flex-1 flex-col rounded-[18px] ${pictures ? "p-2.5" : "p-3"} ${i === 0 ? "bg-[#EEF3FE]" : pictures ? "bg-[#F2F5F7]" : ""}`}>
                    {pictures ? <>
                      <MiniScreen step={i} s={s} />
                      <span className="mt-2.5 block px-1">
                        <span className={`block text-[11px] font-bold ${i === 0 ? "hp-accent-text" : ""}`}>{i === 0 ? "1단계 · 지금 여기" : `${i + 1}단계`}</span>
                        <b className="block truncate text-[15px] font-bold text-[#34383F]">{st.title}</b>
                      </span>
                    </> : (
                      <span className="flex items-center gap-2">
                        <span className={`grid size-9 shrink-0 place-items-center rounded-[12px] ${i === 0 ? "bg-white" : "bg-[#F2F5F7]"}`}><img src={ICONS[i]} alt="" className="size-5" /></span>
                        <span className="min-w-0">
                          <span className={`block text-[11px] font-bold ${i === 0 ? "hp-accent-text" : ""}`}>{i === 0 ? "1단계 · 지금 여기" : `${i + 1}단계`}</span>
                          <b className="block truncate text-[15px] font-bold text-[#34383F]">{st.title}</b>
                        </span>
                      </span>
                    )}
                    <span className={`mt-1 text-[13px] leading-5 ${pictures ? "px-1" : "mt-2"}`}>{st.body}</span>
                    <span className={`mt-auto flex flex-wrap gap-x-3 gap-y-0.5 pt-2 ${pictures ? "px-1" : ""}`}>
                      {states[i].map((x) => x.go
                        ? <button key={x.text} type="button" onClick={x.go} className={ACTION}>{x.text}<ChevronRight className="size-3.5" aria-hidden /></button>
                        : <span key={x.text} className="text-[13px] font-semibold">{x.text}</span>)}
                    </span>
                  </div>
                </li>
              ))}
            </ol>
          </section>
          <IdeaCard m={m} s={s} row
            note={<span data-tour="home-profile">적지 않은 조건은 내 투자조건({s.amount.split(" · ")[0]} · {s.years} · {s.tendency})을 써요 · <button type="button" onClick={() => navigate({ page: "profile" })} className="hp-accent-text font-semibold hover:underline">보기</button></span>} />
        </div>
      )
    }}</ExampleFrame>
  )
}
