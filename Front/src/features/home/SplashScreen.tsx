import { useEffect, useState } from "react"

export const SPLASH_FADE_DELAY_MS = 150  // 서버가 바로 답하면(저장해 둔 자료) 보이기 전에 걷혀 깜빡이지 않는다

/** 홈 자료를 처음 불러올 때 화면 전체를 덮는 시작 화면: 가운데 문구, 그 아래 로딩바와 %. */
export function SplashScreen({ progress }: { progress: number }) {
  const target = Math.round(Math.max(0, Math.min(1, progress)) * 100)
  const [step, setStep] = useState(target)
  const pct = target >= 100 ? 100 : step  // 다 되면 따라 올리기를 기다리지 않고 같은 화면에서 바로 100
  const [shown, setShown] = useState(false)
  useEffect(() => { const t = window.setTimeout(() => setShown(true), SPLASH_FADE_DELAY_MS); return () => window.clearTimeout(t) }, [])
  // 서버 진행률은 0.4초마다 띄엄띄엄 오므로 숫자를 조금씩 따라 올린다. 다 되면(100) 바로 100.
  useEffect(() => {
    if (step >= target || target >= 100) return  // 진행률은 줄지 않는다 (서버가 큰 값만 남긴다)
    const t = window.setTimeout(() => setStep((p) => Math.min(target, p + Math.max(1, Math.ceil((target - p) / 3)))), 40)
    return () => window.clearTimeout(t)
  }, [step, target])
  return (
    <div data-testid="splash" className={`fixed inset-0 z-[80] flex items-center justify-center bg-slate-50 transition-opacity duration-200 ${shown ? "opacity-100" : "opacity-0"}`}>
      <div className="flex flex-col items-center text-center">
        <p className="whitespace-nowrap text-2xl font-extrabold tracking-tight text-slate-950">MyFinSight, 당신의 투자 도우미</p>
        <div role="progressbar" aria-label="불러오는 중" aria-valuemin={0} aria-valuemax={100} aria-valuenow={pct} className="mt-6 h-2 w-80 overflow-hidden rounded-full bg-slate-200">
          <div className="h-full rounded-full bg-blue-700 transition-[width] duration-300 ease-out" style={{ width: `${pct}%` }} />
        </div>
        <p className="mt-3 text-sm font-semibold tabular-nums text-slate-500">{pct}%</p>
      </div>
    </div>
  )
}
