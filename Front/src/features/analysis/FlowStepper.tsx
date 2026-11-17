import { Check } from "lucide-react"

/**
 * 분석 순서 5단계. 문구는 소개 화면(팀원 브랜치 tutorial-improve 의 IntroScroll)과 같은 순서·뜻을 짧게 줄인 것이다.
 * 홈 「이렇게 진행돼요」 탭과 화면 위 진행 단계 표시(FlowStepper)가 같이 쓴다. 단계 문구는 여기서만 고친다.
 */
export const PROCESS_STEPS: { title: string; body: string }[] = [
  { title: "아이디어 적기", body: "평소 말로 한 줄이면 돼요" },
  { title: "질문에 답하기", body: "빠진 조건만, 보기 중에서 골라요" },
  { title: "조건 확인", body: "「이 조건으로 분석 실행」을 눌러야 시작돼요" },
  { title: "분석·검증", body: "보통 5~10분 걸려요" },
  { title: "리포트·모의투자", body: "실제 돈 없이 따라가 봐요" },
]

export type FlowStep = 1 | 2 | 3 | 4 | 5

/**
 * 지금 분석 순서 5단계 중 어디인지 (홈 1·2 · 조건 확인 3 · 분석 진행 4 · 끝나면 5).
 * 지난 단계는 체크, 지금 단계는 강조(aria-current="step"), 다음 단계는 흐리게. 누르는 기능은 없다.
 * 표시 폭이 760px 보다 좁으면(홈 대화창 옆) 지금 단계만 이름을 보이고 나머지는 번호만 (이름은 화면 읽기·마우스 올림으로).
 */
export function FlowStepper({ current }: { current: FlowStep }) {
  return (
    <nav aria-label="분석 진행 단계" className="@container rounded-card bg-surface px-6 py-4">
      <ol className="flex items-center gap-3">
        {PROCESS_STEPS.map((s, i) => {
          const n = i + 1, done = n < current, now = n === current
          return (
            <li key={s.title} title={s.title} aria-current={now ? "step" : undefined} className={`flex min-w-0 items-center gap-3 ${n < PROCESS_STEPS.length ? "flex-1" : ""}`}>
              <span className="flex shrink-0 items-center gap-2">
                <span aria-hidden className={`grid size-7 place-items-center rounded-full text-13 font-bold ${done || now ? "bg-accent text-on-accent" : "bg-sunken text-hint"} ${now ? "ring-4 ring-tint" : ""}`}>
                  {done ? <Check className="size-4" strokeWidth={3} /> : n}
                </span>
                <span className={`whitespace-nowrap text-14 ${now ? "font-bold text-main" : `${done ? "font-medium text-body" : "text-hint"} sr-only @min-[760px]:not-sr-only`}`}>
                  {s.title}<span className="sr-only"> ({now ? "지금 단계" : done ? "완료" : "다음 단계"})</span>
                </span>
              </span>
              {n < PROCESS_STEPS.length && <span aria-hidden className={`h-0.5 min-w-4 flex-1 rounded-full ${done ? "bg-accent" : "bg-line"}`} />}
            </li>
          )
        })}
      </ol>
    </nav>
  )
}
