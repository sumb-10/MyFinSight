import { PROCESS_STEPS } from "../analysis/FlowStepper"

/** 홈 「이렇게 진행돼요」 탭: 분석 순서 5단계(PROCESS_STEPS, FlowStepper.tsx)를 작은 화면 그림과 문장으로 보여 준다. */
export function ProcessSteps({ amount, years }: { amount: string; years: string }) {
  return (
    <ol aria-label="분석 순서" className="space-y-1.5">
      {PROCESS_STEPS.map((st, i) => (
        <li key={st.title} className="flex items-center gap-4 rounded-box bg-sunken p-2">
          <span className="w-[164px] shrink-0"><MiniScreen step={i} amount={amount} years={years} /></span>
          <span className="min-w-0">
            <span className="flex items-center gap-1.5">
              <span aria-hidden className="grid size-5 shrink-0 place-items-center rounded-full bg-surface text-12 font-bold text-accent">{i + 1}</span>
              <b className="t-title">{st.title}</b>
            </span>
            <span className="mt-0.5 block text-13 text-body">{st.body}</span>
          </span>
        </li>
      ))}
    </ol>
  )
}

// 그림 전용 색 (장식이라 화면 읽기에서 숨긴다). 그림 안의 색은 정보가 아니어서 토큰 대신 여기서만 쓴다
const PIC = { point: "#4880ee", line: "#b0b8c1", bar: "#d5dae0" }

/** 단계별 작은 화면 그림. 소개 화면의 장면을 홈 크기로 줄여 움직이지 않게 그린 것. 수익률 같은 숫자는 넣지 않는다. */
function MiniScreen({ step, amount, years }: { step: number; amount: string; years: string }) {
  const chip = (on: boolean) => `rounded-full px-1.5 py-px text-[10px] font-semibold ${on ? "text-on-accent" : "bg-sunken text-sub"}`
  const row = "flex items-center justify-between gap-1 border-b border-sunken py-0.5 last:border-0"
  return (
    <span aria-hidden className="flex h-[76px] flex-col rounded-control bg-surface p-2 text-[11px] leading-[1.35] text-sub">
      {step === 0 && <>
        <span className="text-main">미국 반도체 기업에 3년 정도 나눠 투자<span className="ml-px inline-block h-3 w-px translate-y-0.5 bg-main" /></span>
        <span className="mt-auto self-end rounded-[6px] px-1.5 py-0.5 text-[10px] font-semibold text-on-accent" style={{ background: PIC.point }}>분석 시작하기 ›</span>
      </>}
      {step === 1 && <>
        <span className="self-start rounded-chip bg-sunken px-1.5 py-0.5 text-main">어떤 기준으로 고를까요?</span>
        <span className="mt-auto flex gap-1"><span className={chip(true)} style={{ background: PIC.point }}>최근 흐름</span><span className={chip(false)}>기업 규모</span><span className={chip(false)}>배당</span></span>
      </>}
      {step === 2 && <>
        <span className={row}><span>금액</span><b className="truncate font-semibold text-main">{amount.split(" · ")[0]}</b></span>
        <span className={row}><span>기간</span><b className="font-semibold text-main">{years}</b></span>
        <span className="mt-auto rounded-[6px] py-0.5 text-center text-[10px] font-semibold text-on-accent" style={{ background: PIC.point }}>▷ 분석 실행</span>
      </>}
      {step === 3 && (
        <svg viewBox="0 0 120 44" className="h-full w-full" preserveAspectRatio="none">
          <polyline points="0,40 15,37 30,38 45,30 60,31 75,22 90,20 105,12 120,8" fill="none" stroke={PIC.point} strokeWidth="2" vectorEffect="non-scaling-stroke" />
          <polyline points="0,40 15,39 30,38 45,35 60,36 75,31 90,30 105,27 120,25" fill="none" stroke={PIC.line} strokeWidth="1.5" vectorEffect="non-scaling-stroke" />
        </svg>
      )}
      {step === 4 && <>
        <span className="h-2 w-3/4 rounded-full" style={{ background: PIC.bar }} />
        <span className="mt-1.5 h-1.5 w-full rounded-full bg-sunken" />
        <span className="mt-1 h-1.5 w-5/6 rounded-full bg-sunken" />
        <span className="mt-auto self-start rounded-full bg-tint px-1.5 py-px text-[10px] font-semibold text-accent">모의투자 진행 중</span>
      </>}
    </span>
  )
}
