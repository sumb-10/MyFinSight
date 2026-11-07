import { useCallback, useEffect, useLayoutEffect, useRef, useState } from "react"
import { X } from "lucide-react"
import type { TourStep } from "./steps"

const PAD = 8  // 하이라이트 여백
const GAP = 12  // 하이라이트와 말풍선 사이
const W = 340  // 말풍선 너비
const TOP_GAP = 72  // 긴 대상을 맞출 때 위쪽 여백 (고정 탭 48px + 여유)

type Box = { top: number; left: number; width: number; height: number }

const findTarget = (t: string) => document.querySelector<HTMLElement>(`[data-tour="${t}"]`)

const SCROLL_KEYS = new Set(["PageUp", "PageDown", "ArrowUp", "ArrowDown", "Home", "End", " "])

/** 페이지 스크롤 잠금: html 의 overflow 를 숨기고(스크롤바 폭만큼 오른쪽 여백으로 보정해 화면이 흔들리지 않게), 휠·터치·스크롤 키를 막는다.
 *  코드로 하는 scrollIntoView 는 그대로 된다. 말풍선 버튼 위의 스페이스·엔터(누르기)와 Tab 은 막지 않는다. 돌려주는 함수가 잠금을 모두 푼다. */
export function lockScroll(): () => void {
  const html = document.documentElement, body = document.body
  const prev = { overflow: html.style.overflow, padding: body.style.paddingRight }
  const bar = window.innerWidth - html.clientWidth
  html.style.overflow = "hidden"
  if (bar > 0) body.style.paddingRight = `${bar}px`
  const block = (e: Event) => e.preventDefault()
  const key = (e: KeyboardEvent) => {
    if (!SCROLL_KEYS.has(e.key)) return
    if (e.key === " " && (e.target as HTMLElement | null)?.closest?.("button")) return  // 포커스된 버튼을 스페이스로 누르기
    e.preventDefault()
  }
  window.addEventListener("wheel", block, { passive: false })
  window.addEventListener("touchmove", block, { passive: false })
  window.addEventListener("keydown", key)
  return () => {
    html.style.overflow = prev.overflow
    body.style.paddingRight = prev.padding
    window.removeEventListener("wheel", block)
    window.removeEventListener("touchmove", block)
    window.removeEventListener("keydown", key)
  }
}

/** 코치마크: 대상 요소를 스포트라이트로 비추고 옆에 말풍선(제목·설명·이전/다음/건너뛰기·n/전체)을 띄운다.
 *  떠 있는 동안 페이지는 고정되고, 화면 이동은 이전/다음(그리고 닫기)으로만 일어난다. ESC 로 닫고, 단계가 바뀌면 말풍선의 주 버튼으로 포커스를 옮기며, Tab 은 말풍선 안에서만 돈다. */
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

  useEffect(() => lockScroll(), [])  // 둘러보기 동안 사용자 스크롤을 막아 화면을 고정한다. 닫히면(언마운트) 원래대로

  useEffect(() => {  // 단계가 바뀔 때만 코드로 대상을 화면 가운데로 옮기고 위치를 잰다. 화면이 아직 그려지는 중이면 잠깐 다시 찾는다
    let tries = 0
    let timer = 0
    const go = () => {
      const el = findTarget(step.target)
      if (el) {
        // 즉시 이동 (index.css 의 scroll-behavior: smooth 를 따르면 움직이는 도중에 위치를 재게 된다). 화면보다 긴 대상은 위쪽(고정 탭 아래)에 맞춘다
        const tall = el.getBoundingClientRect().height > window.innerHeight * 0.6
        if (tall) window.scrollTo?.({ top: window.scrollY + el.getBoundingClientRect().top - TOP_GAP, behavior: "instant" })
        else el.scrollIntoView?.({ block: "center", behavior: "instant" })
        measure(); timer = window.setTimeout(measure, 120)
      }
      else if (tries++ < 20) timer = window.setTimeout(go, 150)
      else setBox(null)
    }
    go()
    return () => window.clearTimeout(timer)
  }, [step.target, measure])

  useEffect(() => {  // 창 크기가 바뀌거나 코드로 스크롤된 뒤에 위치를 다시 잰다 (사용자 스크롤은 잠겨 있어 이 경우만 생긴다)
    const on = () => measure()
    window.addEventListener("resize", on); window.addEventListener("scroll", on, { passive: true })
    return () => { window.removeEventListener("resize", on); window.removeEventListener("scroll", on) }
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
