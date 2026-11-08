import { useCallback, useEffect, useLayoutEffect, useRef, useState } from "react"
import { X } from "lucide-react"
import type { TourStep } from "./steps"

const PAD = 8  // 하이라이트 여백
const GAP = 12  // 하이라이트와 말풍선 사이
const W = 340  // 말풍선 너비
const TOP_GAP = 72  // 긴 대상을 맞출 때 위쪽 여백 (고정 탭 48px + 여유)
const EDGE = 12  // 강조 테두리와 화면 위 끝 사이 최소 여백
const STICKY_GAP = 16  // 고정 탭 줄을 비출 때 줄을 내리는 거리

export type Box = { top: number; left: number; width: number; height: number }

const findTarget = (t: string) => document.querySelector<HTMLElement>(`[data-tour="${t}"]`)
const revealButton = (t: string) => findTarget(t)?.querySelector<HTMLButtonElement>("button[aria-expanded]") ?? null

/** 요소의 화면 위치. 안에 열린 도움말(말풍선)이 있으면 함께 감싼다. 화면에 그려지지 않은 요소는 null. */
function boxOf(el: HTMLElement): Box | null {
  if (!el.getClientRects().length) return null
  const r = el.getBoundingClientRect()
  const tip = el.querySelector<HTMLElement>('[role="dialog"]')?.getBoundingClientRect()
  const top = Math.min(r.top, tip?.top ?? r.top), left = Math.min(r.left, tip?.left ?? r.left)
  const right = Math.max(r.right, tip?.right ?? r.right), bottom = Math.max(r.bottom, tip?.bottom ?? r.bottom)
  const boxTop = Math.max(EDGE, top - PAD)  // 테두리가 화면 위 끝에 붙어 잘리지 않게
  return { top: boxTop, left: left - PAD, width: right - left + PAD * 2, height: bottom + PAD - boxTop }
}

/** 요소가 든 고정(sticky) 줄을 화면 위에서 띄운다. 맨 위에 붙은 줄 안의 요소도 테두리 여백이 생긴다. 돌려주는 함수가 원래대로 되돌린다. */
export function liftSticky(el: HTMLElement): (() => void) | null {
  for (let p: HTMLElement | null = el; p; p = p.parentElement) {
    if (getComputedStyle(p).position !== "sticky") continue
    const bar = p, prev = bar.style.top
    bar.style.top = `${STICKY_GAP}px`
    return () => { bar.style.top = prev }
  }
  return null
}

const LEFT_MIN = 200  // 왼쪽 배치에 필요한 최소 폭 (이보다 좁으면 기본 배치)

/** 말풍선 자리.
 *  - placement "left": 강조 영역 왼쪽 빈 곳(사이드바 위)에 세로 가운데로. 강조 영역과 겹치지 않게 폭을 그 공간에 맞춘다.
 *  - 기본: 아래에 공간이 있으면 아래, 아니면 위, 둘 다 없으면 화면 아래쪽. 대상을 못 찾으면 화면 가운데. */
export function popoverStyle(box: Box | null, placement: "left" | undefined, vw: number, vh: number): { side: "left" | "below" | "above" | "bottom" | "center"; css: React.CSSProperties } {
  if (!box) return { side: "center", css: { top: "50%", left: "50%", transform: "translate(-50%, -50%)", width: W } }
  const room = box.left - GAP - 16
  if (placement === "left" && room >= LEFT_MIN) return { side: "left", css: { top: "50%", left: 16, transform: "translateY(-50%)", width: Math.min(W, room) } }
  const left = Math.max(16, Math.min(vw - W - 16, box.left))
  if (box.top + box.height + GAP + 220 < vh) return { side: "below", css: { top: box.top + box.height + GAP, left, width: W } }
  if (box.top - GAP - 220 > 0) return { side: "above", css: { top: box.top - GAP, left, transform: "translateY(-100%)", width: W } }
  return { side: "bottom", css: { top: Math.max(16, vh - 260), left, width: W } }
}

const SCROLL_KEYS =new Set(["PageUp", "PageDown", "ArrowUp", "ArrowDown", "Home", "End", " "])

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
  const [extra, setExtra] = useState<Box[]>([])  // 함께 비추는 요소들 (step.also)
  const pop = useRef<HTMLDivElement>(null)
  const primary = useRef<HTMLButtonElement>(null)

  const measure = useCallback(() => {
    const el = findTarget(step.target)
    setExtra((step.also ?? []).flatMap((t) => { const x = findTarget(t); const b = x ? boxOf(x) : null; return b ? [b] : [] }))
    setBox(el ? boxOf(el) : null)
  }, [step.target, step.also])

  useEffect(() => lockScroll(), [])  // 둘러보기 동안 사용자 스크롤을 막아 화면을 고정한다. 닫히면(언마운트) 원래대로

  useEffect(() => {  // 단계가 바뀔 때만 코드로 대상을 화면 가운데로 옮기고 위치를 잰다. 화면이 아직 그려지는 중이면 잠깐 다시 찾는다
    let tries = 0
    let timer = 0
    let revealed = !step.reveal
    let opened = false
    const unlift = (step.also ?? []).flatMap((t) => { const x = findTarget(t); const undo = x ? liftSticky(x) : null; return undo ? [undo] : [] })
    const go = () => {
      const el = findTarget(step.target)
      if (el) {
        if (!revealed) {  // 접이식·도움말을 먼저 펼치고, 펼친 뒤의 크기로 위치를 잰다
          revealed = true
          const b = revealButton(step.reveal!)
          if (b?.getAttribute("aria-expanded") === "false") { b.click(); opened = true; measure(); timer = window.setTimeout(go, 80); return }
        }
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
    return () => {
      window.clearTimeout(timer)
      unlift.forEach((undo) => undo())
      const b = opened && step.reveal ? revealButton(step.reveal) : null  // 이 단계에서 펼친 것만 원래대로 접는다
      if (b?.getAttribute("aria-expanded") === "true") b.click()
    }
  }, [step.target, step.reveal, step.also, measure])

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

  const style = popoverStyle(box, step.placement, window.innerWidth, window.innerHeight)

  return (
    // onPointerDown: 열어 둔 예시 도움말이 「바깥 누르기」로 닫히지 않게 한다 (단계를 떠날 때 닫는다)
    <div className="fixed inset-0 z-[60]" data-testid="coachmark" onPointerDown={(e) => e.stopPropagation()}>
      {/* 스포트라이트: 대상 자리만 뚫린 어두운 막(여러 곳을 함께 비출 수 있다). 클릭은 아래 막이 받는다 (튜토리얼 중 화면 조작 방지) */}
      <div className="absolute inset-0" onClick={(e) => e.stopPropagation()} aria-hidden />
      {box
        ? <>
            <svg aria-hidden className="pointer-events-none absolute inset-0 size-full">
              <defs><mask id="tour-holes"><rect width="100%" height="100%" fill="white" />{[box, ...extra].map((b, i) => <rect key={i} x={b.left} y={b.top} width={b.width} height={b.height} rx={16} fill="black" />)}</mask></defs>
              <rect width="100%" height="100%" fill="rgba(15, 23, 42, 0.55)" mask="url(#tour-holes)" />
            </svg>
            {[box, ...extra].map((b, i) => <div key={i} aria-hidden className="pointer-events-none absolute rounded-2xl ring-2 ring-blue-400" style={b} />)}
          </>
        : <div aria-hidden className="pointer-events-none absolute inset-0 bg-slate-900/55" />}
      <div ref={pop} role="dialog" aria-modal="true" aria-labelledby="tour-title" aria-describedby="tour-body" data-placement={style.side} className="absolute rounded-2xl border border-slate-200 bg-white p-5 shadow-xl" style={{ ...style.css, maxWidth: "calc(100vw - 32px)" }}>
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
