import { useEffect, useRef, useState, type ReactNode } from "react"
import { ArrowDown, ChevronRight, Compass, FileText, MessageCircle, Play, Sparkles, TrendingUp } from "lucide-react"
import { navigate } from "../../app/router"

// 처음 온 사람에게 전체 흐름을 보여 주는 스크롤형 소개 페이지 (#/intro).
// 오른쪽 화면 틀은 고정(sticky)되어 있고, 왼쪽 설명을 스크롤로 한 장씩 넘기면 화면 속 내용이 다음 단계로 바뀐다.
// 기존 두 둘러보기(홈·리포트)는 그대로 두고, 마지막 장의 선택지로만 연결한다.

const INTRO_KEY = "myfinsight.intro.v1"
const HOME_TOUR_FLAG = "myfinsight.startHomeTour"

export function introSeen(): boolean {
  if (import.meta.env.MODE === "test") return true  // 기존 화면 테스트가 홈 대신 소개로 넘어가지 않게
  try { return window.localStorage.getItem(INTRO_KEY) === "seen" } catch { return true }  // 저장소를 못 쓰면 매번 띄우지 않는다
}
export function recordIntro() {
  try { window.localStorage.setItem(INTRO_KEY, "seen") } catch { /* ignore */ }
}
/** 소개 마지막 장에서 「화면 둘러보기」를 고르면 홈이 열리자마자 홈 둘러보기를 시작한다 (한 번만) */
export function hasHomeTourFlag(): boolean {
  try { return window.sessionStorage.getItem(HOME_TOUR_FLAG) === "1" } catch { return false }
}
export function clearHomeTourFlag() {
  try { window.sessionStorage.removeItem(HOME_TOUR_FLAG) } catch { /* ignore */ }
}

const reduced = () => typeof window !== "undefined" && window.matchMedia?.("(prefers-reduced-motion: reduce)").matches

interface Step { no: number; kicker: string; title: string; body: string }
const STEPS: Step[] = [
  { no: 1, kicker: "아이디어 입력", title: "투자하고 싶은 내용을\n평소 말로 적어 보세요", body: "관심 있는 산업, 종목, 기간을 한 줄로 적으면 됩니다.\n적지 않은 조건은 미리 저장해 둔 내 투자조건을 씁니다." },
  { no: 2, kicker: "보충 질문", title: "모자란 조건은\nMyFinSight가 물어봐요", body: "분석에 꼭 필요한데 빠진 조건이 있으면 한 번에 하나씩 묻습니다.\n보기 중에서 고르기만 하면 됩니다." },
  { no: 3, kicker: "조건 확인", title: "최종 조건을 확인하고\n분석을 시작해요", body: "이번 분석에서 달라진 조건을 한눈에 보여 줍니다.\n확인하고 「분석 시작」을 눌러야 분석이 실행됩니다." },
  { no: 4, kicker: "분석·검증", title: "종목을 고르고,\n과거 데이터로 검증해요", body: "조건에 맞는 종목을 고르고 비중을 정한 뒤, 과거에 이 구성을 따랐다면 어땠을지 계산합니다. 보통 5~10분 걸리니 다른 일을 하다 오셔도 됩니다." },
  { no: 5, kicker: "리포트·모의투자", title: "리포트로 확인하고,\n모의투자로 지켜봐요", body: "추천 구성, 과거 성과와 위험, 내 조건을 지켰는지가 리포트에 정리됩니다. 마음에 들면 실제 돈 없이 모의투자로 따라가 볼 수 있습니다." },
]

/** 장 넘김: 첫 화면, 1~5장, 마지막 화면이 각각 화면 하나 높이로 아래로 쌓여 있다.
 *  휠 한 번 = 한 장. 휠을 가로채 다음(이전) 장 맨 위로 부드럽게 스크롤한다. 지금 장은 화면 가운데에 걸친 장이다. */
const PAGE_MS = 500  // 한 장 넘어가는 시간

/** 브라우저 기본 부드러운 스크롤은 속도가 제각각이라 직접 움직인다: PAGE_MS 동안 천천히 시작해 천천히 멈춘다 */
let scrollAnim = 0
function animateScrollTo(top: number) {
  if (scrollAnim) window.cancelAnimationFrame(scrollAnim)
  const html = document.documentElement
  const from = window.scrollY, dist = top - from
  if (reduced() || Math.abs(dist) < 2) { window.scrollTo({ top, behavior: "auto" }); return }
  const prev = html.style.scrollBehavior
  html.style.scrollBehavior = "auto"  // index.css 의 smooth 가 한 프레임씩 움직이는 것을 방해하지 않게
  const t0 = performance.now()
  const ease = (t: number) => (t < 0.5 ? 4 * t * t * t : 1 - Math.pow(-2 * t + 2, 3) / 2)
  const step = (now: number) => {
    const t = Math.min(1, (now - t0) / PAGE_MS)
    window.scrollTo(0, from + dist * ease(t))
    if (t < 1) scrollAnim = window.requestAnimationFrame(step)
    else { scrollAnim = 0; html.style.scrollBehavior = prev }
  }
  scrollAnim = window.requestAnimationFrame(step)
}

function usePager(count: number) {
  const pages = useRef<(HTMLElement | null)[]>([])
  const [page, setPage] = useState(0)
  const pageRef = useRef(0)
  pageRef.current = page
  const goTo = (i: number) => {
    const el = pages.current[Math.max(0, Math.min(count - 1, i))]
    if (el) animateScrollTo(el.offsetTop)
  }
  const goRef = useRef(goTo)
  goRef.current = goTo
  useEffect(() => {
    let raf = 0
    const read = () => {
      raf = 0
      const mid = window.innerHeight / 2
      const i = pages.current.findIndex((el) => { if (!el) return false; const r = el.getBoundingClientRect(); return r.top <= mid && r.bottom > mid })
      if (i >= 0) setPage(i)
    }
    const onScroll = () => { if (!raf) raf = window.requestAnimationFrame(read) }
    let lockUntil = 0, target = -1  // 넘어가는 동안 들어온 휠(트랙패드의 연속 입력 포함)은 무시
    const onWheel = (e: WheelEvent) => {
      if (Math.abs(e.deltaY) < 2 || e.ctrlKey) return
      e.preventDefault()
      const now = Date.now()
      if (now < lockUntil) return
      const from = target >= 0 && now < lockUntil + 200 ? target : pageRef.current
      const next = Math.max(0, Math.min(count - 1, from + (e.deltaY > 0 ? 1 : -1)))
      lockUntil = now + PAGE_MS + 150
      target = next
      goRef.current(next)
    }
    const onKey = (e: KeyboardEvent) => {
      const down = ["ArrowDown", "PageDown", " "].includes(e.key), up = ["ArrowUp", "PageUp"].includes(e.key)
      if (!down && !up) return
      e.preventDefault()
      goRef.current(pageRef.current + (down ? 1 : -1))
    }
    read()
    window.addEventListener("scroll", onScroll, { passive: true })
    window.addEventListener("resize", onScroll)
    window.addEventListener("wheel", onWheel, { passive: false })
    window.addEventListener("keydown", onKey)
    return () => {
      window.removeEventListener("scroll", onScroll); window.removeEventListener("resize", onScroll)
      window.removeEventListener("wheel", onWheel); window.removeEventListener("keydown", onKey)
      if (raf) window.cancelAnimationFrame(raf)
    }
  }, [count])
  return { page, pages, goTo }
}

/** 글자가 한 자씩 찍히는 효과 (움직임 줄이기 설정이면 바로 전체) */
function useTyping(text: string, speed = 45, delay = 300) {
  const [n, setN] = useState(() => (reduced() ? text.length : 0))
  useEffect(() => {
    if (reduced()) return
    let i = 0, t: number
    const tick = () => { i += 1; setN(i); if (i < text.length) t = window.setTimeout(tick, speed) }
    t = window.setTimeout(tick, delay)
    return () => window.clearTimeout(t)
  }, [text, speed, delay])
  return text.slice(0, n)
}

/** start ms 뒤에 true (장면 안의 순서 있는 등장용) */
function useAfter(ms: number) {
  const [on, setOn] = useState(() => reduced())
  useEffect(() => { if (reduced()) return; const t = window.setTimeout(() => setOn(true), ms); return () => window.clearTimeout(t) }, [ms])
  return on
}

const appear = (on: boolean) => `transition-all duration-500 ease-out ${on ? "translate-y-0 opacity-100" : "translate-y-3 opacity-0"}`

// ─── 장면들 (화면 틀 안) ─────────────────────────────────────────

function SceneIdea() {
  const typed = useTyping("미국 반도체 기업에 3년 정도 분산 투자하고 싶어요. 한 종목에 너무 몰리지 않게요.")
  const btn = useAfter(4200)
  return (
    <div className="flex h-full flex-col items-center justify-center px-8">
      <p className="text-center text-xl font-extrabold text-slate-900">투자 아이디어를 포트폴리오로 확인해보세요.</p>
      <div className="mt-6 w-full rounded-2xl border border-slate-200 bg-white p-4 shadow-sm">
        <p className="min-h-24 text-[15px] leading-7 text-slate-800">{typed}<span className="ml-0.5 inline-block h-5 w-0.5 translate-y-1 animate-pulse bg-blue-600" /></p>
        <div className="flex justify-end border-t border-slate-100 pt-3">
          <span className={`inline-flex items-center gap-1 rounded-xl px-4 py-2 text-sm font-bold text-white transition-all duration-300 ${btn ? "scale-95 bg-blue-800 ring-4 ring-blue-200" : "bg-blue-700"}`}>투자조건 확인하기<ChevronRight className="size-4" /></span>
        </div>
      </div>
    </div>
  )
}

function Bubble({ show, children, me = false }: { show: boolean; children: ReactNode; me?: boolean }) {
  return (
    <div className={`flex ${me ? "justify-end" : "justify-start"} ${appear(show)}`}>
      <div className={`max-w-[80%] rounded-2xl px-4 py-2.5 text-sm leading-6 ${me ? "rounded-br-sm bg-blue-700 text-white" : "rounded-bl-sm border border-slate-200 bg-white text-slate-800"}`}>{children}</div>
    </div>
  )
}

function Chips({ items, pick, picked }: { items: string[]; pick: number; picked: boolean }) {
  return (
    <div className="mt-2 flex gap-1.5">
      {items.map((t, i) => <span key={t} className={`rounded-full border px-3 py-1 text-xs font-semibold transition-all duration-300 ${picked && i === pick ? "border-blue-600 bg-blue-600 text-white" : "border-slate-200 bg-slate-50 text-slate-600"}`}>{t}</span>)}
    </div>
  )
}

function SceneQuestions() {
  const q1 = useAfter(200), a1 = useAfter(1400), r1 = useAfter(1900), q2 = useAfter(2700), a2 = useAfter(3900), r2 = useAfter(4400)
  return (
    <div className="flex h-full flex-col justify-center gap-3 px-8">
      <Bubble show={q1}><span className="flex items-center gap-1.5 text-xs font-bold text-blue-700"><MessageCircle className="size-3.5" />질문 1/2</span>섹터 안에서 어떤 기준으로 종목을 고를까요?<Chips items={["최근 주가 흐름", "기업 규모", "배당"]} pick={0} picked={a1} /></Bubble>
      <Bubble show={r1} me>최근 주가 흐름</Bubble>
      <Bubble show={q2}><span className="flex items-center gap-1.5 text-xs font-bold text-blue-700"><MessageCircle className="size-3.5" />질문 2/2</span>한 종목에 최대 얼마까지 담을까요?<Chips items={["20%", "25%", "30%"]} pick={1} picked={a2} /></Bubble>
      <Bubble show={r2} me>25%</Bubble>
    </div>
  )
}

function SceneConfirm() {
  const rows: [string, string, string | null][] = [["금액", "2,000만 원", null], ["기간", "5년", "3년"], ["종목당 최대 비중", "30%", "25%"], ["섹터", "전체", "반도체"], ["종목 선정 기준", "모멘텀·시가총액", "최근 주가 흐름"]]
  const changed = useAfter(900), press = useAfter(3200)
  return (
    <div className="flex h-full flex-col justify-center px-8">
      <div className="rounded-2xl border border-slate-200 bg-white p-5 shadow-sm">
        <p className="text-sm font-bold text-slate-900">이번 분석에서 달라진 조건</p>
        <div className="mt-3 divide-y divide-slate-100">
          {rows.map(([k, base, next], i) => (
            <div key={k} className="flex items-center justify-between py-2.5 text-sm">
              <span className="text-slate-500">{k}</span>
              <span className="font-semibold">
                {next ? <><span className={`transition-all duration-500 ${changed ? "text-slate-400 line-through" : "text-slate-800"}`}>기본 {base}</span><span className={`ml-2 inline-block text-blue-700 transition-all duration-500 ${changed ? "translate-x-0 opacity-100" : "-translate-x-2 opacity-0"}`} style={{ transitionDelay: `${i * 250}ms` }}>→ {next}</span></> : <span className="text-slate-800">{base}</span>}
              </span>
            </div>
          ))}
        </div>
      </div>
      <span className={`mt-4 inline-flex items-center justify-center gap-2 rounded-xl py-3 text-sm font-bold text-white transition-all duration-300 ${press ? "scale-[0.97] bg-blue-800 ring-4 ring-blue-200" : "bg-blue-700"}`}><Play className="size-4" />분석 시작</span>
    </div>
  )
}

const TICKERS = ["NVDA", "AVGO", "TSM", "AMD", "MU", "ASML", "QCOM", "AMAT", "LRCX", "KLAC", "INTC", "TXN"]
const PICKED = new Set(["NVDA", "AVGO", "TSM", "MU", "ASML", "AMAT"])
const STRAT = "M0,90 L20,86 L40,80 L60,84 L80,70 L100,64 L120,68 L140,52 L160,46 L180,50 L200,34 L220,28 L240,30 L260,18 L280,12"
const BENCH = "M0,90 L20,88 L40,85 L60,87 L80,80 L100,77 L120,79 L140,70 L160,67 L180,69 L200,62 L220,58 L240,60 L260,54 L280,50"

function SceneAnalyze() {
  const filter = useAfter(1200), stage2 = useAfter(2200), chart = useAfter(2600), done = useAfter(5200)
  const stages = ["종목 고르기", "비중 정하기", "과거 성과 검증"]
  const at = done ? 3 : chart ? 2 : stage2 ? 1 : 0
  return (
    <div className="flex h-full flex-col justify-center gap-4 px-8">
      <div className="flex items-center gap-2">
        {stages.map((s, i) => (
          <div key={s} className="flex flex-1 flex-col gap-1.5">
            <div className="h-1.5 overflow-hidden rounded-full bg-slate-200"><div className="h-full rounded-full bg-blue-600 transition-all duration-700" style={{ width: i < at ? "100%" : i === at ? "45%" : "0%" }} /></div>
            <span className={`text-[11px] font-semibold ${i <= at ? "text-blue-700" : "text-slate-400"}`}>{s}</span>
          </div>
        ))}
      </div>
      <div className="flex flex-wrap gap-1.5 rounded-2xl border border-slate-200 bg-white p-4">
        {TICKERS.map((t, i) => (
          <span key={t} className={`rounded-lg px-2.5 py-1 text-xs font-bold tabular-nums transition-all duration-500 ${filter ? (PICKED.has(t) ? "bg-blue-600 text-white" : "scale-90 bg-slate-100 text-slate-300") : "bg-slate-100 text-slate-700"}`} style={{ transitionDelay: `${i * 60}ms` }}>{t}</span>
        ))}
      </div>
      <div className={`rounded-2xl border border-slate-200 bg-white p-4 ${appear(chart)}`}>
        <div className="flex items-center gap-4 text-[11px] font-semibold"><span className="flex items-center gap-1.5 text-blue-700"><span className="h-0.5 w-4 bg-blue-600" />이 구성을 따랐다면</span><span className="flex items-center gap-1.5 text-slate-400"><span className="h-0.5 w-4 bg-slate-400" />비교지수</span></div>
        <svg viewBox="0 0 280 100" className="mt-2 h-28 w-full" preserveAspectRatio="none" aria-hidden>
          <path d={BENCH} fill="none" stroke="#94a3b8" strokeWidth="2" pathLength={1} className="intro-draw" />
          <path d={STRAT} fill="none" stroke="#2563eb" strokeWidth="2.5" pathLength={1} className="intro-draw" />
        </svg>
      </div>
      <p className="text-center text-xs font-semibold text-slate-500">{done ? "분석이 끝났습니다. 리포트가 준비됐어요." : "보통 5~10분 걸립니다"}</p>
    </div>
  )
}

function SceneReport() {
  const s1 = useAfter(200), s2 = useAfter(800), s3 = useAfter(1400), s4 = useAfter(2400)
  const hold: [string, number][] = [["NVDA", 25], ["AVGO", 20], ["TSM", 18], ["ASML", 15], ["MU", 12], ["AMAT", 10]]
  return (
    <div className="flex h-full flex-col justify-center gap-3 px-8">
      <div className={`rounded-2xl border border-emerald-200 bg-emerald-50 p-4 ${appear(s1)}`}>
        <p className="text-xs font-bold text-emerald-700">결과 요약</p>
        <p className="mt-1 text-sm font-semibold leading-6 text-slate-800">반도체 6개 종목을 최대 25%씩 담는 구성이 비교지수보다 높은 수익을 냈습니다.</p>
      </div>
      <div className={`grid grid-cols-3 gap-2 ${appear(s2)}`}>
        {[["연평균 수익률", "+18.4%", "text-blue-700"], ["최대 낙폭", "-24.1%", "text-slate-800"], ["내 조건", "4개 중 4개 충족", "text-emerald-700"]].map(([k, v, c]) => (
          <div key={k} className="rounded-xl border border-slate-200 bg-white p-3"><p className="text-[11px] text-slate-500">{k}</p><p className={`mt-1 text-sm font-extrabold ${c}`}>{v}</p></div>
        ))}
      </div>
      <div className={`space-y-1.5 rounded-2xl border border-slate-200 bg-white p-4 ${appear(s3)}`}>
        {hold.map(([t, w], i) => (
          <div key={t} className="flex items-center gap-2 text-xs">
            <span className="w-10 font-bold text-slate-700">{t}</span>
            <div className="h-2 flex-1 rounded-full bg-slate-100"><div className="h-full rounded-full bg-blue-600 transition-all duration-700" style={{ width: s3 ? `${w * 4}%` : "0%", transitionDelay: `${i * 90}ms` }} /></div>
            <span className="w-8 text-right tabular-nums text-slate-500">{w}%</span>
          </div>
        ))}
      </div>
      <span className={`inline-flex items-center justify-center gap-2 rounded-xl border border-blue-200 bg-white py-2.5 text-sm font-bold text-blue-700 ${appear(s4)}`}><TrendingUp className="size-4" />모의투자로 지켜보기</span>
    </div>
  )
}

const SCENES = [SceneIdea, SceneQuestions, SceneConfirm, SceneAnalyze, SceneReport]

/** 장마다 하나씩 있는 화면 틀. 그 장에 처음 들어올 때 장면을 그리고, 다시 들어오면(visit 이 바뀌면) 처음부터 재생한다. */
function DeviceFrame({ step, visit }: { step: number; visit: number }) {
  const Scene = SCENES[step]
  return (
    <div className="overflow-hidden rounded-3xl border border-slate-200 bg-slate-50 shadow-2xl shadow-slate-300/60">
      <div className="flex items-center gap-1.5 border-b border-slate-200 bg-white px-4 py-3">
        <span className="size-2.5 rounded-full bg-slate-200" /><span className="size-2.5 rounded-full bg-slate-200" /><span className="size-2.5 rounded-full bg-slate-200" />
        <span className="ml-3 flex items-center gap-1.5 text-xs font-bold text-slate-500"><span className="flex size-4 items-center justify-center rounded bg-blue-700 text-white"><TrendingUp className="size-2.5" /></span>MyFinSight</span>
        <span className="ml-auto text-[11px] font-semibold text-blue-700">{STEPS[step].no}/5 · {STEPS[step].kicker}</span>
      </div>
      <div className="h-[460px]">{visit > 0 && <div key={visit} className="intro-scene h-full"><Scene /></div>}</div>
    </div>
  )
}

export function IntroScroll() {
  const PAGES = STEPS.length + 2  // 첫 화면 + 5장 + 마지막 화면
  const { page, pages, goTo } = usePager(PAGES)
  const step = page - 1  // 지금 보이는 장 (0~4, 첫·마지막 화면이면 범위 밖)
  const [visits, setVisits] = useState<number[]>(() => STEPS.map(() => 0))
  useEffect(() => { if (step >= 0 && step < STEPS.length) setVisits((v) => v.map((n, i) => (i === step ? n + 1 : n))) }, [step])
  useEffect(() => { recordIntro(); window.scrollTo({ top: 0 }) }, [])  // 한 번 열면 「본 것」: 첫 방문 자동 열기를 다시 하지 않는다
  const go = (to: "home" | "tour" | "example") => {
    if (to === "tour") { try { window.sessionStorage.setItem(HOME_TOUR_FLAG, "1") } catch { /* ignore */ } }
    navigate(to === "example" ? { page: "tutorial" } : { page: "home" })
  }

  return (
    <div className="min-h-screen bg-white">
      <style>{`
        .intro-scene { animation: intro-in .45s ease-out both }
        @keyframes intro-in { from { opacity: 0; transform: translateY(8px) } to { opacity: 1; transform: none } }
        .intro-draw { stroke-dasharray: 1; stroke-dashoffset: 1; animation: intro-draw 2.2s ease-out .3s forwards }
        @keyframes intro-draw { to { stroke-dashoffset: 0 } }
        .intro-bob { animation: intro-bob 1.6s ease-in-out infinite }
        @keyframes intro-bob { 50% { transform: translateY(6px) } }
      `}</style>

      {/* 위쪽 고정 막대: 로고, 건너뛰기 */}
      <header className="fixed inset-x-0 top-0 z-30 flex items-center justify-between border-b border-slate-100 bg-white/85 px-10 py-4 backdrop-blur">
        <span className="flex items-center gap-2.5"><span className="flex size-8 items-center justify-center rounded-lg bg-blue-700 text-white"><TrendingUp className="size-4" /></span><span className="text-base font-extrabold tracking-tight text-slate-950">MyFinSight</span></span>
        <button onClick={() => go("home")} className="rounded-lg px-3 py-1.5 text-sm font-semibold text-slate-500 hover:bg-slate-100 hover:text-slate-900">건너뛰기</button>
      </header>

      {/* 첫 화면 */}
      <section ref={(el) => { pages.current[0] = el }} className="flex h-screen flex-col items-center justify-center px-10 text-center">
        <span className="inline-flex items-center gap-1.5 rounded-full bg-blue-50 px-3 py-1 text-xs font-bold text-blue-700"><Sparkles className="size-3.5" />처음 오셨나요?</span>
        <h1 className="mt-6 text-5xl font-extrabold leading-tight tracking-tight text-slate-950">투자 아이디어 한 줄이<br />검증된 포트폴리오가 되기까지</h1>
        <p className="mt-5 max-w-xl text-lg leading-8 text-slate-600">MyFinSight가 어떤 순서로 분석하는지 보여 드릴게요.</p>
        <button onClick={() => goTo(1)} className="intro-bob mt-14 flex flex-col items-center gap-2 text-sm font-semibold text-slate-400 hover:text-slate-600">아래로 스크롤<ArrowDown className="size-5" /></button>
      </section>

      {/* 단계: 장마다 설명과 화면 틀이 따로 있고, 휠 한 번에 한 장씩 아래로 넘어간다 */}
      {STEPS.map((st, i) => (
        <section key={st.no} ref={(el) => { pages.current[i + 1] = el }} className={`flex h-screen items-center ${i % 2 ? "bg-slate-50/70" : "bg-white"}`}>
          <div className="mx-auto grid w-full max-w-[1180px] grid-cols-[minmax(0,1fr)_520px] items-center gap-16 px-10 pt-12">
            <div className={`transition-all duration-700 ease-out ${step === i ? "translate-y-0 opacity-100" : "translate-y-6 opacity-0"}`}>
              <p className="flex items-center gap-2 text-sm font-bold text-blue-700"><span className="flex size-7 items-center justify-center rounded-full bg-blue-700 text-xs text-white">{st.no}</span>{st.kicker}</p>
              <h2 className="mt-4 whitespace-pre-line text-4xl font-extrabold leading-tight tracking-tight text-slate-950">{st.title}</h2>
              <p className="mt-5 max-w-xl whitespace-pre-line text-[17px] leading-8 text-slate-600">{st.body}</p>
            </div>
            <DeviceFrame step={i} visit={visits[i]} />
          </div>
        </section>
      ))}

      {/* 진행 표시: 오른쪽 점. 누르면 그 장으로 */}
      <nav aria-label="소개 단계" className={`fixed right-6 top-1/2 z-20 flex -translate-y-1/2 flex-col gap-3 transition-opacity ${step >= 0 && step < STEPS.length ? "opacity-100" : "pointer-events-none opacity-0"}`}>
        {STEPS.map((st, i) => (
          <button key={st.no} onClick={() => goTo(i + 1)} aria-label={`${st.no}단계 ${st.kicker}`} aria-current={step === i ? "step" : undefined} className={`w-2.5 rounded-full transition-all duration-300 ${step === i ? "h-6 bg-blue-700" : "h-2.5 bg-slate-300 hover:bg-slate-400"}`} />
        ))}
      </nav>

      {/* 마지막: 선택지 */}
      <section ref={(el) => { pages.current[STEPS.length + 1] = el }} className="flex h-screen flex-col items-center justify-center bg-slate-50 px-10 text-center">
        <h2 className="text-4xl font-extrabold tracking-tight text-slate-950">이제 직접 해 볼까요?</h2>
        <p className="mt-4 text-lg text-slate-600">처음이라면 예시 리포트를 먼저 보는 것도 좋아요.</p>
        <div className="mt-10 grid w-full max-w-4xl grid-cols-3 gap-4">
          <button onClick={() => go("home")} className="group rounded-2xl bg-blue-700 px-5 py-4 text-white shadow-lg shadow-blue-200 transition hover:bg-blue-800">
            <span className="flex items-center justify-center gap-2"><Play className="size-5 shrink-0" /><span className="text-lg font-extrabold">바로 시작하기</span></span><p className="mt-1.5 text-sm md:whitespace-nowrap text-blue-100">내 투자 아이디어를 입력합니다</p>
          </button>
          <button onClick={() => go("example")} className="rounded-2xl border border-slate-200 bg-white px-5 py-4 text-slate-900 transition hover:border-blue-300 hover:shadow-md">
            <span className="flex items-center justify-center gap-2"><FileText className="size-5 shrink-0 text-blue-700" /><span className="text-lg font-extrabold">예시 리포트 먼저 보기</span></span><p className="mt-1.5 text-sm md:whitespace-nowrap text-slate-500">리포트 읽는 법을 단계별로 안내합니다</p>
          </button>
          <button onClick={() => go("tour")} className="rounded-2xl border border-slate-200 bg-white px-5 py-4 text-slate-900 transition hover:border-blue-300 hover:shadow-md">
            <span className="flex items-center justify-center gap-2"><Compass className="size-5 shrink-0 text-blue-700" /><span className="text-lg font-extrabold">화면 둘러보기</span></span><p className="mt-1.5 text-sm md:whitespace-nowrap text-slate-500">홈 화면의 각 부분을 짚어 줍니다</p>
          </button>
        </div>
        <p className="mt-10 text-sm text-slate-400">이 소개는 홈의 「MyFinSight 소개」에서 언제든 다시 볼 수 있습니다.</p>
      </section>
    </div>
  )
}
