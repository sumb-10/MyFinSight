import { useEffect, useState } from "react"
import { ArrowRight, Check, ChevronLeft, ChevronRight, FileText, Newspaper, ShieldCheck, Sparkles, TrendingUp, X } from "lucide-react"

// 소개 페이지의 첫 화면과 1단계 사이에 끼는 「MyFinSight만의 특징」 가로 슬라이드.
// 세로 장 하나 안에서 휠·화살표·점으로 옆으로 넘긴다. 마지막 장에서 더 내리면 다음 세로 장으로 간다 (IntroScroll 의 intercept).

const reduced = () => typeof window !== "undefined" && window.matchMedia?.("(prefers-reduced-motion: reduce)").matches

function useAfter(ms: number) {
  const [on, setOn] = useState(() => reduced())
  useEffect(() => { if (reduced()) return; const t = window.setTimeout(() => setOn(true), ms); return () => window.clearTimeout(t) }, [ms])
  return on
}
const appear = (on: boolean) => `transition-all duration-500 ease-out ${on ? "translate-y-0 opacity-100" : "translate-y-3 opacity-0"}`

interface Feature { kicker: string; title: string; body: string }
export const FEATURES: Feature[] = [
  { kicker: "아이디어 해석", title: "당신의 요청을 적으면\nLLM이 분석합니다", body: "문장 속 지역, 산업, 기간, 원하는 점을 LLM이 읽어 분석 조건으로 바꿉니다.\n애매한 부분은 짐작하지 않고 되묻습니다." },
  { kicker: "종목 선정", title: "LLM이 조건을 확인하고\n종목 후보를 골라요", body: "종목 사전에서 후보를 찾은 뒤, 기업의 투자 가치가 아이디어에 맞는지 LLM이 분류합니다. 남은 종목은 지표로 순위를 매기고 종목별 근거를 남깁니다." },
  { kicker: "포트폴리오 구성", title: "공시와 뉴스를 근거로\n비중을 조정해요", body: "LLM이 최근 공시와 뉴스를 읽고 종목별 의견을 냅니다. 공시를 주 근거로 삼고, Black-Litterman 방식으로 기본 비중에 반영합니다." },
  { kicker: "검증", title: "숫자는 코드가 계산하고\n근거는 다시 대조해요", body: "수익률과 비중은 모두 코드가 계산하고, LLM은 해석과 설명만 맡습니다. 리포트 속 숫자와 인용이 실제 결과·DB와 맞는지 확인한 뒤에야 보여 줍니다." },
]

// ─── 장면들 ─────────────────────────────────────────

function SceneParse() {
  const tags: [string, string, string][] = [["지역", "미국", "bg-sky-100 text-sky-800"], ["산업", "반도체", "bg-violet-100 text-violet-800"], ["기간", "3년", "bg-amber-100 text-amber-800"], ["제약", "한 종목 비중 제한", "bg-emerald-100 text-emerald-800"]]
  const t0 = useAfter(700), t1 = useAfter(1300), t2 = useAfter(1900), t3 = useAfter(2500), ask = useAfter(3500)
  const on = [t0, t1, t2, t3]
  const mark = (i: number, s: string) => <span className={`rounded px-0.5 transition-colors duration-500 ${on[i] ? tags[i][2] : ""}`}>{s}</span>
  return (
    <div className="flex h-full flex-col justify-center gap-4 px-8">
      <div className="rounded-2xl border border-slate-200 bg-white p-4 text-[15px] leading-7 text-slate-800 shadow-sm">
        {mark(0, "미국")} {mark(1, "반도체")} 기업에 {mark(2, "3년")} 정도 분산 투자하고 싶어요. {mark(3, "한 종목에 너무 몰리지 않게")}요.
      </div>
      <p className="flex items-center gap-1.5 text-xs font-bold text-blue-700"><Sparkles className="size-3.5" />LLM이 읽은 분석 조건</p>
      <div className="grid grid-cols-2 gap-2">
        {tags.map(([k, v, c], i) => (
          <div key={k} className={`rounded-xl border border-slate-200 bg-white p-3 ${appear(on[i])}`}>
            <p className="text-[11px] text-slate-500">{k}</p>
            <p className={`mt-1 inline-block rounded-md px-2 py-0.5 text-sm font-bold ${c}`}>{v}</p>
          </div>
        ))}
      </div>
      <div className={`rounded-2xl rounded-bl-sm border border-slate-200 bg-white px-4 py-2.5 text-sm leading-6 text-slate-800 ${appear(ask)}`}>
        <span className="text-xs font-bold text-blue-700">되묻기</span> 한 종목에 최대 얼마까지 담을까요?
      </div>
    </div>
  )
}

function SceneSelect() {
  const rows: [string, string, boolean][] = [["NVDA", "GPU·AI 가속기 설계", true], ["TSM", "반도체 위탁 생산", true], ["AAPL", "스마트폰·PC 제조, 칩은 자체 사용", false], ["MU", "메모리 반도체", true], ["TSLA", "전기차·에너지 저장", false], ["ASML", "반도체 노광 장비", true]]
  const shown = [useAfter(300), useAfter(700), useAfter(1100), useAfter(1500), useAfter(1900), useAfter(2300)]
  const judged = useAfter(2900), ranked = useAfter(4200)
  return (
    <div className="flex h-full flex-col justify-center gap-3 px-8">
      <p className="flex items-center gap-1.5 text-xs font-bold text-blue-700"><Sparkles className="size-3.5" />종목이 「미국 반도체」에 맞나요?</p>
      <div className="divide-y divide-slate-100 rounded-2xl border border-slate-200 bg-white px-4">
        {rows.map(([t, biz, ok], i) => (
          <div key={t} className={`flex items-center gap-3 py-2.5 text-sm ${appear(shown[i])} ${judged && !ok ? "opacity-40" : ""}`}>
            <span className="w-12 font-bold tabular-nums text-slate-800">{t}</span>
            <span className={`flex-1 text-xs text-slate-500 ${judged && !ok ? "line-through" : ""}`}>{biz}</span>
            <span className={`inline-flex items-center gap-1 rounded-full px-2 py-0.5 text-[11px] font-bold transition-all duration-500 ${judged ? (ok ? "bg-blue-600 text-white" : "bg-slate-100 text-slate-500") : "scale-90 opacity-0"}`} style={{ transitionDelay: `${i * 120}ms` }}>
              {ok ? <><Check className="size-3" />포함</> : <><X className="size-3" />제외</>}
            </span>
          </div>
        ))}
      </div>
      <div className={`rounded-2xl border border-blue-100 bg-blue-50 p-3 text-xs leading-5 text-slate-700 ${appear(ranked)}`}>
        <span className="font-bold text-blue-700">남은 4개를 지표로 순위 매기기</span> · NVDA: 데이터센터 매출 비중이 커 아이디어와 가장 가깝습니다.
      </div>
    </div>
  )
}

function SceneBuild() {
  const ev1 = useAfter(300), ev2 = useAfter(1100), shift = useAfter(2300)
  const w: [string, number, number][] = [["NVDA", 25, 27], ["TSM", 25, 29], ["MU", 25, 19], ["ASML", 25, 25]]
  return (
    <div className="flex h-full flex-col justify-center gap-3 px-8">
      <div className={`flex gap-3 rounded-2xl border border-slate-200 bg-white p-3 ${appear(ev1)}`}>
        <span className="flex size-8 shrink-0 items-center justify-center rounded-lg bg-emerald-50 text-emerald-700"><FileText className="size-4" /></span>
        <div className="min-w-0 text-xs leading-5"><p className="font-bold text-slate-800">TSM · 공시 <span className="ml-1 rounded bg-emerald-100 px-1.5 py-0.5 text-emerald-700">긍정</span></p><p className="text-slate-500">분기 매출 전망을 이전보다 높였습니다.</p></div>
      </div>
      <div className={`flex gap-3 rounded-2xl border border-slate-200 bg-white p-3 ${appear(ev2)}`}>
        <span className="flex size-8 shrink-0 items-center justify-center rounded-lg bg-amber-50 text-amber-700"><Newspaper className="size-4" /></span>
        <div className="min-w-0 text-xs leading-5"><p className="font-bold text-slate-800">MU · 뉴스 <span className="ml-1 rounded bg-amber-100 px-1.5 py-0.5 text-amber-700">신중</span></p><p className="text-slate-500">메모리 가격 하락 우려가 이어지고 있습니다.</p></div>
      </div>
      <div className="rounded-2xl border border-slate-200 bg-white p-4">
        <div className="mb-2 flex items-center justify-between text-[11px] font-semibold"><span className="text-slate-500">비중</span><span className={`text-blue-700 transition-opacity duration-500 ${shift ? "opacity-100" : "opacity-0"}`}>의견 반영 후</span></div>
        <div className="space-y-2">
          {w.map(([t, base, adj], i) => {
            const v = shift ? adj : base, d = adj - base
            return (
              <div key={t} className="flex items-center gap-2 text-xs">
                <span className="w-10 font-bold text-slate-700">{t}</span>
                <div className="h-2.5 flex-1 rounded-full bg-slate-100"><div className="h-full rounded-full bg-blue-600 transition-all duration-1000 ease-out" style={{ width: `${v * 3}%`, transitionDelay: `${i * 120}ms` }} /></div>
                <span className="w-8 text-right tabular-nums text-slate-700">{v}%</span>
                <span className={`w-8 text-right text-[11px] font-bold tabular-nums transition-opacity duration-500 ${shift ? "opacity-100" : "opacity-0"} ${d > 0 ? "text-emerald-600" : d < 0 ? "text-rose-600" : "text-slate-400"}`}>{d > 0 ? `+${d}` : d === 0 ? "±0" : d}</span>
              </div>
            )
          })}
        </div>
      </div>
    </div>
  )
}

function SceneVerify() {
  const checks = ["18.4% → 백테스트 결과값과 일치", "인용한 공시 → DB 원문과 일치", "기준일 이후 자료 → 사용하지 않음", "같은 조건 → 같은 결과 (LLM 응답 저장)"]
  const on = [useAfter(1000), useAfter(1600), useAfter(2200), useAfter(2800)]
  const pass = useAfter(3700)
  return (
    <div className="flex h-full flex-col justify-center gap-3 px-8">
      <div className="rounded-2xl border border-slate-200 bg-white p-4 text-sm leading-6 text-slate-800 shadow-sm">
        <p className="text-[11px] font-bold text-slate-500">리포트 문장</p>
        이 구성은 연평균 <span className="rounded bg-blue-100 px-1 font-bold text-blue-800">18.4%</span> 수익을 냈고, TSM은 <span className="rounded bg-emerald-100 px-1 font-bold text-emerald-800">최근 공시</span>에서 매출 전망을 높였습니다.
      </div>
      <div className="space-y-2 rounded-2xl border border-slate-200 bg-white p-4">
        {checks.map((c, i) => (
          <div key={c} className={`flex items-center gap-2 text-xs text-slate-700 ${appear(on[i])}`}>
            <span className="flex size-5 shrink-0 items-center justify-center rounded-full bg-emerald-600 text-white"><Check className="size-3" /></span>{c}
          </div>
        ))}
      </div>
      <div className={`flex items-center justify-center gap-2 rounded-xl bg-emerald-50 py-2.5 text-sm font-bold text-emerald-700 ${appear(pass)}`}><ShieldCheck className="size-4" />모든 내용을 검증 후 리포트를 냅니다</div>
    </div>
  )
}

const SCENES = [SceneParse, SceneSelect, SceneBuild, SceneVerify]

function Frame({ i, visit }: { i: number; visit: number }) {
  const Scene = SCENES[i]
  return (
    <div className="overflow-hidden rounded-3xl border border-slate-200 bg-slate-50 shadow-2xl shadow-slate-300/60">
      <div className="flex items-center gap-1.5 border-b border-slate-200 bg-white px-4 py-3">
        <span className="size-2.5 rounded-full bg-slate-200" /><span className="size-2.5 rounded-full bg-slate-200" /><span className="size-2.5 rounded-full bg-slate-200" />
        <span className="ml-3 flex items-center gap-1.5 text-xs font-bold text-slate-500"><span className="flex size-4 items-center justify-center rounded bg-blue-700 text-white"><TrendingUp className="size-2.5" /></span>MyFinSight</span>
        <span className="ml-auto text-[11px] font-semibold text-slate-400">예시 화면</span>
      </div>
      <div className="h-[460px]">{visit > 0 && <div key={visit} className="intro-scene h-full"><Scene /></div>}</div>
    </div>
  )
}

/** active: 이 세로 장이 지금 보이는지. slide/setSlide 는 IntroScroll 이 들고 있다 (휠 가로채기에 필요). */
export function FeatureSlides({ active, slide, setSlide, onNext }: { active: boolean; slide: number; setSlide: (i: number) => void; onNext: () => void }) {
  const [visits, setVisits] = useState<number[]>(() => FEATURES.map(() => 0))
  useEffect(() => { if (active) setVisits((v) => v.map((n, i) => (i === slide ? n + 1 : n))) }, [active, slide])
  const last = slide === FEATURES.length - 1
  return (
    <div className="flex h-full w-full flex-col justify-center pt-12">
      <p className={`mx-auto w-full max-w-[1180px] px-10 text-sm font-bold text-slate-400 transition-opacity duration-700 ${active ? "opacity-100" : "opacity-0"}`}>MyFinSight만의 특색은 ·{slide + 1}/{FEATURES.length}</p>
      <div className="overflow-hidden">
        <div className="flex transition-transform duration-500 ease-out" style={{ transform: `translateX(-${slide * 100}%)` }}>
          {FEATURES.map((f, i) => (
            <div key={f.kicker} aria-hidden={i !== slide} className="w-full shrink-0">
              <div className="mx-auto grid w-full max-w-[1180px] grid-cols-[minmax(0,1fr)_520px] items-center gap-16 px-10 py-6">
                <div className={`transition-all duration-700 ease-out ${active && i === slide ? "translate-x-0 opacity-100" : "translate-x-6 opacity-0"}`}>
                  <p className="flex items-center gap-2 text-sm font-bold text-violet-700"><span className="flex size-7 items-center justify-center rounded-full bg-violet-600 text-white"><Sparkles className="size-3.5" /></span>{f.kicker}</p>
                  <h2 className="mt-4 whitespace-pre-line text-4xl font-extrabold leading-tight tracking-tight text-slate-950">{f.title}</h2>
                  <p className="mt-5 max-w-xl whitespace-pre-line text-[17px] leading-8 text-slate-600">{f.body}</p>
                </div>
                <Frame i={i} visit={visits[i]} />
              </div>
            </div>
          ))}
        </div>
      </div>
      <div className="mx-auto flex w-full max-w-[1180px] items-center gap-4 px-10">
        <button onClick={() => setSlide(slide - 1)} disabled={slide === 0} aria-label="이전 특징" className="flex size-10 items-center justify-center rounded-full border border-slate-200 bg-white text-slate-600 transition hover:border-blue-300 hover:text-blue-700 disabled:opacity-30"><ChevronLeft className="size-5" /></button>
        <div className="flex gap-2" role="tablist" aria-label="특징 슬라이드">
          {FEATURES.map((f, i) => <button key={f.kicker} role="tab" aria-selected={i === slide} aria-label={f.kicker} onClick={() => setSlide(i)} className={`h-2.5 rounded-full transition-all duration-300 ${i === slide ? "w-7 bg-violet-600" : "w-2.5 bg-slate-300 hover:bg-slate-400"}`} />)}
        </div>
        <button onClick={() => (last ? onNext() : setSlide(slide + 1))} aria-label={last ? "사용 순서 보기" : "다음 특징"} className="flex h-10 items-center gap-1.5 rounded-full border border-slate-200 bg-white px-3 text-sm font-semibold text-slate-600 transition hover:border-blue-300 hover:text-blue-700">
          {last ? <>사용 순서 보기<ArrowRight className="size-4" /></> : <ChevronRight className="size-5" />}
        </button>
        <span className="ml-auto text-xs text-slate-400">스크롤이나 ← → 키로도 넘길 수 있어요</span>
      </div>
    </div>
  )
}
