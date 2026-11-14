import { useCallback, useEffect, useLayoutEffect, useRef, useState } from "react"
import { MousePointer2, X } from "lucide-react"
import type { TourDemo, TourStep } from "./steps"

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

/** 두 영역을 모두 덮는 영역 */
function unionBox(a: Box, b: Box): Box {
  const top = Math.min(a.top, b.top), left = Math.min(a.left, b.left)
  return { top, left, width: Math.max(a.left + a.width, b.left + b.width) - left, height: Math.max(a.top + a.height, b.top + b.height) - top }
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

/** 말풍선 자리 (왼쪽 고정 카드를 둘 공간이 없을 때 쓰는 배치).
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

const DOCK_EDGE = 24  // 화면 끝에서 카드까지
const LEFT_MIN_W = 220  // 왼쪽 카드 최소 폭 (이보다 공간이 좁으면 popoverStyle 배치로)

/** 카드 높이: 이 둘러보기에서 가장 긴 설명이 들어가는 만큼만 (글자 폭 ≈ 14px, 줄 높이 24px). 모든 단계에서 같은 높이라 버튼이 움직이지 않는다 */
function leftCardHeight(steps: TourStep[], w: number): number {
  const perLine = Math.max(8, Math.floor((w - 40) / 14))
  const lines = Math.max(...steps.map((s) => Math.ceil(s.body.length / perLine)))
  return 156 + lines * 24
}

/** 설명 카드를 본문 왼쪽 빈 곳(사이드바 자리)에 고정한다. 강조 테두리만 단계마다 움직인다. 창이 좁아 공간이 없으면 null */
function dockStyle(steps: TourStep[]): { side: "dock-left"; css: React.CSSProperties } | null {
  // 단계마다 크기·자리가 바뀌지 않게 대상이 아니라 본문 내용의 왼쪽 끝(강조 테두리 바깥 끝 = 내용 - PAD - 4px) 기준으로 잰다.
  // 화면 왼쪽 끝 ~ 그 끝 사이 빈 곳의 가운데에 두어 카드 좌우 여백을 같게 한다 (폭은 최대 300px)
  const wrap = document.querySelector<HTMLElement>("main > div")
  const contentLeft = wrap ? wrap.getBoundingClientRect().left + parseFloat(getComputedStyle(wrap).paddingLeft || "0") - PAD - 4 : 0
  const w = Math.min(300, contentLeft - 16 * 2)  // 좌우 여백 16px씩
  if (w < LEFT_MIN_W) return null  // 창이 좁아 사이드바가 없을 때
  const left = (contentLeft - w) / 2, height = leftCardHeight(steps, w)
  // 홈 둘러보기는 1단계에서 왼쪽 메뉴를 비추므로, 카드를 처음부터 끝까지 메뉴 아래 같은 자리에 둔다 (가능한 한 세로 가운데)
  if (steps.some((s) => s.target === "home-menu")) {
    const menuBottom = findTarget("home-menu")?.getBoundingClientRect().bottom ?? 0
    const top = Math.min(window.innerHeight - height - DOCK_EDGE, Math.max((window.innerHeight - height) / 2, menuBottom + PAD + 4 + DOCK_EDGE))
    return { side: "dock-left", css: { top, left, width: w, height } }
  }
  return { side: "dock-left", css: { top: "50%", left, transform: "translateY(-50%)", width: w, height } }
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

// ─── 시연 애니메이션: 입력 칸에는 글자가 쳐지는 모습, 버튼에는 마우스가 다가가 누르는 모습, 문장 목록에는 마우스를 올린 모습을 강조 영역 위에 보여 준다.
//     글자·커서는 겹친 그림일 뿐이고, 마우스 올림은 요소에 표시(data-tour-hover)만 잠깐 붙인다. 앱 상태는 바뀌지 않는다.
//     예외: toggles 단계(용어 ?)는 누르는 순간 실제 도움말을 열고, 잠시 뒤 닫는다 ───────────────────────────────
const TYPE_MS = 60  // 글자 하나 치는 시간
const TYPE_HOLD = 1500  // 다 친 뒤 멈춰 있는 시간
const CLICK_LOOP = 2400  // 누르기 한 번의 길이
const TOGGLE_LOOP = 4400  // 누르고 도움말을 열어 두는 시연 한 번의 길이
export const TOGGLE_PRESS = Math.round(TOGGLE_LOOP * 0.23)  // 커서가 누르는 순간 (tour-cursor-long 의 23%)
const TOGGLE_HOLD = 2500  // 도움말을 열어 두는 시간
const HOVER_MOVE = 500  // 다음 문장으로 커서가 옮겨 가는 시간
const HOVER_EACH = 1300  // 문장 하나에 머무는 시간 (옮겨 가는 시간 포함)
const HOVER_MAX = 4  // 차례로 가리킬 문장 수

const reducedMotion = () => { try { return window.matchMedia?.("(prefers-reduced-motion: reduce)").matches ?? false } catch { return false } }
const visible = (e: HTMLElement) => e.getClientRects().length > 0

/** 시연이 가리킬 요소: 글자 치기는 대상 안의 입력 칸, 누르기는 selector·label 로 고른 요소.
 *  selector·label 을 주지 않으면 대상 안 첫 버튼(없으면 대상 전체), 주었는데 못 찾으면 null (시연 없음) */
function demoElement(target: HTMLElement, demo: TourDemo): HTMLElement | null {
  if (demo.kind === "type") return target.querySelector<HTMLElement>("textarea, input")
  if (demo.kind === "hover") return null
  const all = Array.from(target.querySelectorAll<HTMLElement>(demo.selector ?? "button, a")).filter(visible)
  const hit = demo.label ? all.find((e) => e.textContent?.includes(demo.label!)) : all[0]
  return hit ?? (demo.selector || demo.label ? null : target)
}

/* data-mock-ui: 개발용 목업 표시(띠·「목업 데이터」 단추·「목업」 꼬리표). 둘러보기는 실제 서비스 화면처럼 보여야 하므로 그동안 숨긴다.
   data-tour-hover: 마우스 올림 시연 중인 문장 (예시 문장·추천 문장의 hover 모습: 파란 글자 + 옅은 배경) */
const TOUR_CSS = `
[data-mock-ui] { display: none !important }
[data-tour-measuring] [role="dialog"] { visibility: hidden !important }
[data-tour-hover] { color: #1d4ed8 !important; background-color: #f8fafc !important; transition: color .15s, background-color .15s }
@keyframes tour-cursor { 0% { transform: translate(44px, 40px); opacity: 0 } 10% { opacity: 1 } 32% { transform: translate(0, 0) scale(1) } 40% { transform: translate(0, 0) scale(.85) } 48% { transform: translate(0, 0) scale(1) } 85% { transform: translate(0, 0); opacity: 1 } 100% { transform: translate(0, 0); opacity: 0 } }
@keyframes tour-ripple { 0%, 38% { transform: translate(-50%, -50%) scale(.2); opacity: 0 } 40% { transform: translate(-50%, -50%) scale(.3); opacity: .8 } 75%, 100% { transform: translate(-50%, -50%) scale(1.6); opacity: 0 } }
@keyframes tour-cursor-long { 0% { transform: translate(44px, 40px); opacity: 0 } 6% { opacity: 1 } 20% { transform: translate(0, 0) scale(1) } 23% { transform: translate(0, 0) scale(.85) } 27% { transform: translate(0, 0) scale(1) } 88% { transform: translate(0, 0); opacity: 1 } 100% { transform: translate(0, 0); opacity: 0 } }
@keyframes tour-ripple-long { 0%, 22% { transform: translate(-50%, -50%) scale(.2); opacity: 0 } 23% { transform: translate(-50%, -50%) scale(.3); opacity: .8 } 42%, 100% { transform: translate(-50%, -50%) scale(1.6); opacity: 0 } }
@keyframes tour-caret { 50% { opacity: 0 } }`

function Cursor({ x, y, style }: { x: number; y: number; style?: React.CSSProperties }) {
  // 화살표 끝(아이콘의 왼쪽 위 ≈ 4px)이 가리키는 자리에 오게 둔다
  return (
    <span aria-hidden data-testid="tour-demo-cursor" className="pointer-events-none absolute" style={{ top: y - 4, left: x - 4, transformOrigin: "4px 4px", ...style }}>
      <MousePointer2 className="size-[22px] fill-slate-900 text-white drop-shadow" strokeWidth={1.5} />
    </span>
  )
}

function TypingDemo({ rect, text, still }: { rect: DOMRect; text: string; still: boolean }) {
  const [n, setN] = useState(still ? text.length : 0)
  useEffect(() => {
    if (still) { setN(text.length); return }
    let i = 0, timer = 0
    const tick = () => {
      if (i < text.length) { i++; setN(i); timer = window.setTimeout(tick, TYPE_MS) }
      else timer = window.setTimeout(() => { i = 0; setN(0); timer = window.setTimeout(tick, 400) }, TYPE_HOLD)
    }
    setN(0); timer = window.setTimeout(tick, 300)
    return () => window.clearTimeout(timer)
  }, [text, still])
  return (
    <div aria-hidden data-testid="tour-demo-type" className="pointer-events-none absolute overflow-hidden rounded-xl bg-white p-3 text-left text-base leading-7 text-slate-800"
      style={{ top: rect.top, left: rect.left, width: rect.width, height: rect.height }}>
      {text.slice(0, n)}<span className="ml-px inline-block h-5 w-0.5 translate-y-1 bg-blue-600" style={still ? undefined : { animation: "tour-caret 1s step-end infinite" }} />
    </div>
  )
}

function ClickDemo({ rect, still, long }: { rect: DOMRect; still: boolean; long: boolean }) {
  const x = rect.left + rect.width / 2, y = rect.top + rect.height / 2
  const ms = long ? TOGGLE_LOOP : CLICK_LOOP, sfx = long ? "-long" : ""
  return (
    <>
      {!still && <span aria-hidden className="pointer-events-none absolute size-9 rounded-full border-2 border-blue-500 bg-blue-400/20" style={{ top: y, left: x, animation: `tour-ripple${sfx} ${ms}ms ease-out infinite` }} />}
      <Cursor x={x} y={y} style={still ? undefined : { animation: `tour-cursor${sfx} ${ms}ms ease-in-out infinite` }} />
    </>
  )
}

/** 마우스 올림: 커서가 문장을 차례로 옮겨 다니며, 머무는 문장에 실제 hover 와 같은 모습을 붙인다 */
function HoverDemo({ els, still, tick }: { els: HTMLElement[]; still: boolean; tick: unknown }) {
  const [i, setI] = useState(0)
  const [arrived, setArrived] = useState(still)
  useEffect(() => {
    if (still) return
    let k = 0, t1 = 0
    setArrived(false)
    const first = window.setTimeout(() => setArrived(true), 60)  // 처음엔 오른쪽 아래에서 다가온다
    const loop = window.setInterval(() => {
      k = (k + 1) % els.length; setArrived(false); setI(k)
      t1 = window.setTimeout(() => setArrived(true), HOVER_MOVE)
    }, HOVER_EACH)
    return () => { window.clearTimeout(first); window.clearTimeout(t1); window.clearInterval(loop) }
  }, [els, still])
  useEffect(() => {  // 커서가 도착한 문장에만 hover 모습. 떠날 때·단계가 끝날 때 지운다
    const el = arrived ? els[i] : null
    el?.setAttribute("data-tour-hover", "")
    return () => el?.removeAttribute("data-tour-hover")
  }, [els, i, arrived])
  void tick
  const el = els[i]
  if (!el || !visible(el)) return null
  const r = el.getBoundingClientRect()
  const x = r.left + Math.min(r.width / 2, 48), y = r.top + r.height / 2  // 긴 문장은 앞부분을 가리킨다
  const started = arrived || i > 0
  return <Cursor x={x} y={y} style={still ? undefined : { transform: started ? "none" : "translate(44px, 40px)", opacity: started ? 1 : 0, transition: `top ${HOVER_MOVE}ms ease-in-out, left ${HOVER_MOVE}ms ease-in-out, transform ${HOVER_MOVE}ms ease-out, opacity 200ms` }} />
}

/** 지금 단계의 시연. 강조 영역(box)을 다시 잴 때마다 위치를 다시 잰다 */
function Demo({ step, box }: { step: TourStep; box: Box | null }) {
  const [rect, setRect] = useState<DOMRect | null>(null)
  const [els, setEls] = useState<HTMLElement[]>([])
  const still = reducedMotion()
  useLayoutEffect(() => {
    const el = step.demo && box ? findTarget(step.target) : null
    if (step.demo?.kind === "hover") {
      const found = el ? Array.from(el.querySelectorAll<HTMLElement>(step.demo.selector)).filter(visible).slice(0, HOVER_MAX) : []
      setEls((prev) => (prev.length === found.length && prev.every((x, i) => x === found[i]) ? prev : found))
      setRect(null); return
    }
    const at = el ? demoElement(el, step.demo!) : null
    setRect(at && visible(at) ? at.getBoundingClientRect() : null)
  }, [step, box])
  if (!step.demo) return null
  if (step.demo.kind === "hover") return els.length ? <HoverDemo key={step.target} els={els} still={still} tick={box} /> : null
  if (!rect) return null
  return step.demo.kind === "type"
    ? <TypingDemo key={step.target} rect={rect} text={step.demo.text} still={still} />
    : <ClickDemo key={step.target} rect={rect} still={still} long={!!step.demo.toggles} />
}

/** 코치마크: 대상 요소를 스포트라이트로 비추고, 설명 카드(제목·설명·이전/다음/건너뛰기·n/전체)를 본문 왼쪽 빈 곳에 고정해 띄운다 (공간이 없으면 대상 옆 말풍선).
 *  입력 칸·버튼 단계에서는 글자 치기·누르기 시연을 겹쳐 보여 준다.
 *  떠 있는 동안 페이지는 고정되고, 화면 이동은 이전/다음(그리고 닫기)으로만 일어난다. ESC 로 닫고, 단계가 바뀌면 카드의 주 버튼으로 포커스를 옮기며, Tab 은 카드 안에서만 돈다. */
export function Coachmark({ steps, index, onPrev, onNext, onClose }: { steps: TourStep[]; index: number; onPrev: () => void; onNext: () => void; onClose: () => void }) {
  const step = steps[index]
  const last = index === steps.length - 1
  const [box, setBox] = useState<Box | null>(null)
  const [extra, setExtra] = useState<Box[]>([])  // 함께 비추는 요소들 (step.also)
  const pop = useRef<HTMLDivElement>(null)
  const primary = useRef<HTMLButtonElement>(null)

  // toggles 단계: 도움말이 열렸을 때까지 덮는 강조 영역. 처음에 한 번 재 두고, 열고 닫는 동안 테두리 크기가 바뀌지 않게 이것과 합쳐 쓴다
  const lockBox = useRef<Box | null>(null)
  const measure = useCallback(() => {
    const el = findTarget(step.target)
    setExtra((step.also ?? []).flatMap((t) => { const x = findTarget(t); const b = x ? boxOf(x) : null; return b ? [b] : [] }))
    const b = el ? boxOf(el) : null, l = lockBox.current
    setBox(b && l ? unionBox(b, l) : b)
  }, [step.target, step.also])

  useEffect(() => lockScroll(), [])  // 둘러보기 동안 사용자 스크롤을 막아 화면을 고정한다. 닫히면(언마운트) 원래대로

  useEffect(() => {  // 단계가 바뀔 때만 코드로 대상을 화면 가운데로 옮기고 위치를 잰다. 화면이 아직 그려지는 중이면 잠깐 다시 찾는다
    let tries = 0
    let timer = 0
    // toggles 시연(용어 ?): 처음엔 닫아 두고, 커서가 누르는 순간 열었다가 TOGGLE_HOLD 뒤 닫기를 되풀이한다 (동작 줄이기 설정이면 처음부터 열어 둔다)
    const toggles = !!step.reveal && step.demo?.kind === "click" && !!step.demo.toggles && !reducedMotion()
    let revealed = !step.reveal || toggles
    let opened = toggles
    const cycle: number[] = []
    const setOpen = (open: boolean) => {
      const b = revealButton(step.reveal!)
      if (b && (b.getAttribute("aria-expanded") === "true") !== open) b.click()
      measure(); cycle.push(window.setTimeout(measure, 80))
    }
    const startCycle = () => {
      const run = () => {
        cycle.push(window.setTimeout(() => setOpen(true), TOGGLE_PRESS))
        cycle.push(window.setTimeout(() => setOpen(false), TOGGLE_PRESS + TOGGLE_HOLD))
      }
      run(); cycle.push(window.setInterval(run, TOGGLE_LOOP))
    }
    lockBox.current = null
    let locking = toggles
    const unlift = (step.also ?? []).flatMap((t) => { const x = findTarget(t); const undo = x ? liftSticky(x) : null; return undo ? [undo] : [] })
    const go = () => {
      const el = findTarget(step.target)
      if (el && locking) {  // toggles 단계: 도움말을 보이지 않게 잠깐 열어 열린 크기를 재고 닫는다 → 강조 영역을 처음부터 그 크기로 고정
        locking = false
        el.scrollIntoView?.({ block: "center", behavior: "instant" })
        const b = revealButton(step.reveal!)
        if (b?.getAttribute("aria-expanded") === "false") {
          el.setAttribute("data-tour-measuring", "")
          b.click()
          timer = window.setTimeout(() => {
            lockBox.current = boxOf(el)
            if (b.getAttribute("aria-expanded") === "true") b.click()
            el.removeAttribute("data-tour-measuring")
            go()
          }, 80)
          return
        }
      }
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
        if (toggles) startCycle()
      }
      else if (tries++ < 20) timer = window.setTimeout(go, 150)
      else setBox(null)
    }
    go()
    return () => {
      window.clearTimeout(timer)
      findTarget(step.target)?.removeAttribute("data-tour-measuring")
      lockBox.current = null
      cycle.forEach((t) => { window.clearTimeout(t); window.clearInterval(t) })
      unlift.forEach((undo) => undo())
      const b = opened && step.reveal ? revealButton(step.reveal) : null  // 이 단계에서 펼친 것만 원래대로 접는다
      if (b?.getAttribute("aria-expanded") === "true") b.click()
    }
  }, [step.target, step.reveal, step.also, step.demo, measure])

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

  const docked = dockStyle(steps)
  const style = docked ?? popoverStyle(box, step.placement, window.innerWidth, window.innerHeight)

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
            {[box, ...extra].map((b, i) => <div key={i} aria-hidden className={`pointer-events-none absolute rounded-2xl ${docked ? "ring-4 ring-blue-500 shadow-[0_0_0_8px_rgba(59,130,246,0.25)]" : "ring-2 ring-blue-400"}`} style={b} />)}
          </>
        : <div aria-hidden className="pointer-events-none absolute inset-0 bg-slate-900/55" />}
      <style>{TOUR_CSS}</style>
      <Demo step={step} box={box} />
      <div ref={pop} role="dialog" aria-modal="true" aria-labelledby="tour-title" aria-describedby="tour-body" data-placement={style.side} className={`absolute rounded-2xl border border-slate-200 bg-white p-5 ${docked ? "flex flex-col shadow-2xl" : "shadow-xl"}`} style={{ ...style.css, maxWidth: "calc(100vw - 32px)" }}>
        <div className="flex items-start justify-between gap-3">
          <p className="text-xs font-bold tracking-wider text-blue-700"><span className="sr-only">단계 </span>{index + 1}/{steps.length}</p>
          <button type="button" onClick={onClose} aria-label="둘러보기 닫기" className="-m-1 rounded-lg p-1 text-slate-400 hover:bg-slate-100 hover:text-slate-700 focus:outline-none focus:ring-2 focus:ring-blue-500"><X className="size-4" /></button>
        </div>
        <h2 id="tour-title" className="mt-1 text-base font-bold text-slate-950">{step.title}</h2>
        <p id="tour-body" className="mt-2 text-sm leading-6 text-slate-700">{step.body}</p>
        <div className={`flex items-center justify-between gap-2 ${docked ? "mt-auto pt-4" : "mt-4"}`}>
          <button type="button" onClick={onClose} className="whitespace-nowrap rounded-lg px-1.5 py-1.5 text-sm font-semibold text-slate-500 hover:text-slate-800 focus:outline-none focus:ring-2 focus:ring-blue-500">건너뛰기</button>
          <div className="flex gap-1.5">
            <button type="button" onClick={onPrev} disabled={index === 0} className="whitespace-nowrap rounded-lg border border-slate-200 px-3 py-1.5 text-sm font-semibold text-slate-700 hover:bg-slate-50 disabled:opacity-40 focus:outline-none focus:ring-2 focus:ring-blue-500">이전</button>
            <button ref={primary} type="button" onClick={onNext} className="whitespace-nowrap rounded-lg bg-blue-700 px-3 py-1.5 text-sm font-semibold text-white hover:bg-blue-800 focus:outline-none focus:ring-2 focus:ring-blue-500">{last ? "마치기" : "다음"}</button>
          </div>
        </div>
      </div>
    </div>
  )
}
