import { useCallback, useEffect, useLayoutEffect, useRef, useState } from "react"
import { X } from "lucide-react"
import type { TourStep } from "./steps"

const PAD = 8  // 하이라이트 여백
const GAP = 12  // 하이라이트와 말풍선 사이
const W = 340  // 말풍선 너비

type Box = { top: number; left: number; width: number; height: number }

const findTarget = (t: string) => document.querySelector<HTMLElement>(`[data-tour="${t}"]`)

/** 코치마크: 대상 요소를 스포트라이트로 비추고 옆에 말풍선(제목·설명·이전/다음/건너뛰기·n/전체)을 띄운다.
 *  ESC 로 닫고, 단계가 바뀌면 말풍선의 주 버튼으로 포커스를 옮기며, Tab 은 말풍선 안에서만 돈다. */
export function Coachmark({ steps, index, onPrev, onNext, onClose }: { steps: TourStep[]; index: number; onPrev: () => void; onNext: () => void; onClose: () => void }) {
  const step = steps[index]
  const last = index === steps.length - 1
  const [box, setBox] = useState<Box | null>(null)
  const pop = useRef<HTMLDivElement>(null)
  const primary = useRef<HTMLButtonElement>(null)

  const measure = useCallback(() => {
    const el = findTarget(step.target)
    if (!el) { setBox(null); return }
    const r = el.getBoundingClientRect()
    setBox({ top: r.top - PAD, left: r.left - PAD, width: r.width + PAD * 2, height: r.height + PAD * 2 })
  }, [step.target])

  useEffect(() => {  // 대상으로 스크롤하고 위치를 잰다. 화면이 아직 그려지는 중이면 잠깐 다시 찾는다
    let tries = 0
    let timer = 0
    const go = () => {
      const el = findTarget(step.target)
      if (el) { el.scrollIntoView?.({ block: "center", behavior: "smooth" }); measure(); window.setTimeout(measure, 450) }
      else if (tries++ < 20) timer = window.setTimeout(go, 150)
      else setBox(null)
    }
    go()
    return () => window.clearTimeout(timer)
  }, [step.target, measure])

  useEffect(() => {
    const on = () => measure()
    window.addEventListener("scroll", on, { passive: true }); window.addEventListener("resize", on)
    return () => { window.removeEventListener("scroll", on); window.removeEventListener("resize", on) }
  }, [measure])

  useLayoutEffect(() => { primary.current?.focus() }, [index])

  useEffect(() => {
    const key = (e: KeyboardEvent) => {
      if (e.key === "Escape") { e.preventDefault(); onClose(); return }
      if (e.key !== "Tab" || !pop.current) return
      const f = Array.from(pop.current.querySelectorAll<HTMLElement>("button:not([disabled])"))
      if (!f.length) return
      const i = f.indexOf(document.activeElement as HTMLElement)
      if (e.shiftKey && i <= 0) { e.preventDefault(); f[f.length - 1].focus() }
      else if (!e.shiftKey && (i < 0 || i === f.length - 1)) { e.preventDefault(); f[0].focus() }
    }
    window.addEventListener("keydown", key)
    return () => window.removeEventListener("keydown", key)
  }, [onClose])

  // 말풍선 자리: 아래에 공간이 있으면 아래, 아니면 위, 둘 다 없으면 화면 가운데
  const vw = typeof window !== "undefined" ? window.innerWidth : 1280
  const vh = typeof window !== "undefined" ? window.innerHeight : 800
  let style: React.CSSProperties = { top: "50%", left: "50%", transform: "translate(-50%, -50%)" }
  if (box) {
    const left = Math.max(16, Math.min(vw - W - 16, box.left))
    if (box.top + box.height + GAP + 220 < vh) style = { top: box.top + box.height + GAP, left }
    else if (box.top - GAP - 220 > 0) style = { top: box.top - GAP, left, transform: "translateY(-100%)" }
    else style = { top: Math.max(16, vh - 260), left }
  }

  return (
    <div className="fixed inset-0 z-[60]" data-testid="coachmark">
      {/* 스포트라이트: 큰 그림자로 대상 밖을 어둡게. 클릭은 아래 막이 받는다 (튜토리얼 중 화면 조작 방지) */}
      <div className="absolute inset-0" onClick={(e) => e.stopPropagation()} aria-hidden />
      {box
        ? <div aria-hidden className="pointer-events-none absolute rounded-2xl ring-2 ring-blue-400" style={{ ...box, boxShadow: "0 0 0 9999px rgba(15, 23, 42, 0.55)" }} />
        : <div aria-hidden className="pointer-events-none absolute inset-0 bg-slate-900/55" />}
      <div ref={pop} role="dialog" aria-modal="true" aria-labelledby="tour-title" aria-describedby="tour-body" className="absolute rounded-2xl border border-slate-200 bg-white p-5 shadow-xl" style={{ ...style, width: W, maxWidth: "calc(100vw - 32px)" }}>
        <div className="flex items-start justify-between gap-3">
          <p className="text-xs font-bold tracking-wider text-blue-700"><span className="sr-only">단계 </span>{index + 1}/{steps.length}</p>
          <button type="button" onClick={onClose} aria-label="둘러보기 닫기" className="-m-1 rounded-lg p-1 text-slate-400 hover:bg-slate-100 hover:text-slate-700 focus:outline-none focus:ring-2 focus:ring-blue-500"><X className="size-4" /></button>
        </div>
        <h2 id="tour-title" className="mt-1 text-base font-bold text-slate-950">{step.title}</h2>
        <p id="tour-body" className="mt-2 text-sm leading-6 text-slate-700">{step.body}</p>
        <div className="mt-4 flex items-center justify-between gap-2">
          <button type="button" onClick={onClose} className="rounded-lg px-2 py-1.5 text-sm font-semibold text-slate-500 hover:text-slate-800 focus:outline-none focus:ring-2 focus:ring-blue-500">건너뛰기</button>
          <div className="flex gap-2">
            <button type="button" onClick={onPrev} disabled={index === 0} className="rounded-lg border border-slate-200 px-3 py-1.5 text-sm font-semibold text-slate-700 hover:bg-slate-50 disabled:opacity-40 focus:outline-none focus:ring-2 focus:ring-blue-500">이전</button>
            <button ref={primary} type="button" onClick={onNext} className="rounded-lg bg-blue-700 px-3 py-1.5 text-sm font-semibold text-white hover:bg-blue-800 focus:outline-none focus:ring-2 focus:ring-blue-500">{last ? "마치기" : "다음"}</button>
          </div>
        </div>
      </div>
    </div>
  )
}
