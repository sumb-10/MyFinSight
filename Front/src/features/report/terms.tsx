import { useEffect, useId, useLayoutEffect, useMemo, useRef, useState } from "react"
import { CircleHelp, Search, X } from "lucide-react"
import type { ReportDoc } from "../../api/types"
import { inputClass, SidePanel } from "../../ui"
import { CitedText } from "./blocks/blocks"
import { useReport } from "./context"
import { proposedOf } from "../../api/proposed"
import { MockTag } from "./proposedView"

// 용어 도움말: 리포트 안의 「?」 단추와 상단 「투자 용어 설명」 패널이 같은 설명을 쓴다.
// 리포트(서버)의 용어 풀이를 먼저 쓰고, 그 리포트에 없는 용어만 아래 공통 설명으로 채운다 — 같은 용어가 자리마다 다르게 설명되지 않게.

const OPEN_EVENT = "report-helptip-open"

/** 「?」 도움말: 눌러서 열고, 닫기 단추·바깥 누르기·Esc 로 닫는다. 화면 오른쪽 끝에서는 왼쪽으로 펼친다. */
export function HelpTip({ label, children }: { label: string; children: React.ReactNode }) {
  const [open, setOpen] = useState(false)
  const [alignRight, setAlignRight] = useState(false)
  const id = useId()
  const ref = useRef<HTMLSpanElement>(null)
  const btn = useRef<HTMLButtonElement>(null)
  useLayoutEffect(() => { if (open && btn.current) setAlignRight(btn.current.getBoundingClientRect().left + 296 > window.innerWidth - 16) }, [open])
  useEffect(() => {
    if (!open) return
    const key = (e: KeyboardEvent) => { if (e.key === "Escape") { setOpen(false); btn.current?.focus() } }
    const down = (e: PointerEvent) => { if (!ref.current?.contains(e.target as Node)) setOpen(false) }
    const other = (e: Event) => { if ((e as CustomEvent<string>).detail !== id) setOpen(false) }
    window.addEventListener("keydown", key); window.addEventListener("pointerdown", down); window.addEventListener(OPEN_EVENT, other)
    return () => { window.removeEventListener("keydown", key); window.removeEventListener("pointerdown", down); window.removeEventListener(OPEN_EVENT, other) }
  }, [open, id])
  const toggle = (e: React.MouseEvent) => { e.stopPropagation(); if (!open) window.dispatchEvent(new CustomEvent(OPEN_EVENT, { detail: id })); setOpen(!open) }
  return (
    <span ref={ref} className="relative inline-flex align-middle" onClick={(e) => e.stopPropagation()}>
      <button ref={btn} type="button" aria-label={`${label} 설명 보기`} aria-expanded={open} aria-controls={id} onClick={toggle} className={`rounded-full p-0.5 transition focus:outline-none focus:ring-2 focus:ring-blue-500 ${open ? "text-blue-700" : "text-slate-400 hover:text-blue-700"}`}><CircleHelp className="size-4" aria-hidden /></button>
      {open && (
        <span id={id} role="dialog" aria-label={`${label} 설명`} className={`absolute top-full z-40 mt-1.5 block w-72 max-w-[calc(100vw-2rem)] rounded-xl border border-slate-200 bg-white p-3 pr-8 text-left text-xs font-normal leading-5 tracking-normal text-slate-700 shadow-lg ${alignRight ? "right-0" : "left-0"}`}>
          <b className="mb-0.5 block text-sm font-semibold text-slate-900">{label}</b>{children}
          <button type="button" aria-label="설명 닫기" onClick={() => { setOpen(false); btn.current?.focus() }} className="absolute right-1.5 top-1.5 rounded-md p-1 text-slate-400 hover:bg-slate-100 hover:text-slate-700"><X className="size-3.5" aria-hidden /></button>
        </span>
      )}
    </span>
  )
}

export interface TermItem { term: string; explain_ko: string; from: "report" | "common"; mock?: boolean }  // mock: 제안 계약(glossary_extra)으로 받은 용어

/** 리포트에 용어 풀이가 없을 때 쓰는 공통 설명 (짧고 쉬운 설명 우선). */
const COMMON: { term: string; explain_ko: string; aliases?: string[] }[] = [
  { term: "CAGR", aliases: ["연평균 수익률", "연환산 수익률"], explain_ko: "투자 기간 동안 매년 같은 비율로 불어났다고 가정해 계산한 연평균 수익률입니다. 평가 기간이 짧으면 참고용으로만 봅니다." },
  { term: "기간 수익률", aliases: ["전체 기간 수익률"], explain_ko: "백테스트 시작부터 끝까지 전체 기간의 누적 수익률입니다. 1년 평균이 아니어서 연평균 수익률(CAGR)과 다릅니다." },
  { term: "최대낙폭", aliases: ["MDD", "최대 하락폭"], explain_ko: "투자 기간 중 가장 높았던 평가금액에서 가장 크게 떨어진 비율입니다. 과거 값이 앞으로의 손실 한도를 뜻하지는 않습니다." },
  { term: "Sharpe", aliases: ["Sharpe 비율"], explain_ko: "감수한 흔들림(변동성)에 비해 무위험 수익률을 넘는 수익을 얼마나 얻었는지 나타내는 값입니다. 높을수록 위험 대비 수익이 좋았다는 뜻입니다." },
  { term: "연변동성", explain_ko: "수익률이 위아래로 흔들리는 정도를 1년 기준으로 환산한 값입니다. 숫자가 클수록 흔들림이 큽니다. 손실률을 뜻하지는 않습니다." },
  { term: "변동성", explain_ko: "수익률이 평균에서 얼마나 크게 오르내렸는지 나타내는 값입니다. 클수록 많이 흔들렸습니다." },
  { term: "%p (퍼센트포인트)", aliases: ["%p"], explain_ko: "두 비율의 차이를 나타내는 단위입니다. 예를 들어 30%와 20%의 차이는 10%p입니다." },
  { term: "백테스트", explain_ko: "과거 자료로 이 전략을 그때 운용했다면 어땠을지 계산해 보는 것입니다. 실제 투자 결과가 아니며 미래 수익을 보장하지 않습니다." },
  { term: "비교지수", explain_ko: "내 전략의 성과를 견주는 기준입니다. 같은 기간·같은 적립 조건으로 비교지수 ETF를 사서 보유했다고 가정해 계산합니다." },
  { term: "SPY", explain_ko: "미국 S&P 500 지수를 따라가도록 만든 ETF(상장지수펀드)입니다. 미국 대형주 500개 기업의 흐름을 보여 주지만, 시장 전체와 완전히 같지는 않습니다." },
  { term: "매수보유 (동일 적립)", aliases: ["매수보유"], explain_ko: "비교를 위해 내 전략과 같은 날, 같은 금액을 비교지수 ETF에 넣고 팔지 않고 계속 보유했다고 가정한 결과입니다." },
  { term: "리밸런싱", aliases: ["투자 비중 조정"], explain_ko: "가격이 움직여 달라진 종목별 비중을 정해 둔 목표 비중으로 다시 맞추는 일입니다." },
  { term: "낙폭 맞춤안", explain_ko: "주식과 현금 비중을 조정하여 과거 최대 하락폭을 사용자의 손실 감내 수준에 맞추려는 투자 방식입니다. 미래 손실이 해당 수준 이하로 제한된다는 의미는 아닙니다." },
  { term: "동일비중", explain_ko: "선정한 종목들에 같은 비율로 투자하는 방식입니다. 종목이 N개면 종목마다 1/N입니다." },
  { term: "시가총액비중", explain_ko: "기업의 시가총액(기업 규모)에 비례해 비중을 정하는 방식입니다. 큰 기업일수록 더 많이 투자합니다." },
  { term: "투자 의견(뷰)", aliases: ["뷰", "투자 의견", "뉴스 뷰"], explain_ko: "뉴스·공시를 근거로 정리한 종목 전망입니다 (예: 이 종목이 다른 종목보다 나을 것). Black-Litterman 방식으로 기준 비중을 제한적으로 조정하는 데 씁니다." },
  { term: "Black-Litterman", aliases: ["BL"], explain_ko: "기준 비중에 투자 의견(뷰)과 그 확신 정도를 섞어 비중을 정하는 자산 배분 방법입니다. 이 분석에서는 조정 폭에 한도를 둡니다." },
  { term: "walk-forward", explain_ko: "리밸런싱할 때마다 그 시점까지 알 수 있던 자료만으로 비중을 다시 계산하는 방식입니다. 미래 정보를 쓰지 않고 과거를 검증하기 위한 방법입니다." },
  { term: "투자 구성안", aliases: ["후보 포트폴리오", "후보"], explain_ko: "같은 선정 종목에 서로 다른 비중 규칙·뉴스 반영·주식과 현금 비율을 적용해 만든 포트폴리오 후보입니다. 비교지수(SPY 등)는 후보에 포함되지 않습니다." },
  { term: "XIRR", explain_ko: "투자금을 넣은 날짜와 금액이 서로 다를 때(적립식) 그 흐름을 반영해 계산한 연 수익률입니다. 연평균 수익률(CAGR)과 계산 방식이 다릅니다." },
]

const norm = (s: string) => s.replace(/\s+/g, "").toLowerCase()
const aliasesOf = (term: string) => { const c = COMMON.find((x) => norm(x.term) === norm(term) || x.aliases?.some((a) => norm(a) === norm(term))); return c ? [c.term, ...(c.aliases ?? [])].map(norm) : [norm(term)] }

/** 리포트 용어 풀이(서버 glossary 블록, 서버 순서) + 리포트에 없는 공통 용어. */
export function glossaryOf(doc: ReportDoc): TermItem[] {
  const out: TermItem[] = []
  const seen = new Set<string>()
  for (const s of doc.sections) for (const b of s.blocks) if (b.type === "glossary") for (const g of b.items) if (!seen.has(norm(g.term))) { seen.add(norm(g.term)); out.push({ ...g, from: "report" }) }
  for (const g of proposedOf(doc)?.explanations?.glossary_extra ?? []) if (!seen.has(norm(g.term))) { seen.add(norm(g.term)); out.push({ ...g, from: "report", mock: true }) }  // 서버가 더 주는 용어(제안 계약)
  const covered = (c: (typeof COMMON)[number]) => [c.term, ...(c.aliases ?? [])].some((a) => seen.has(norm(a)))
  for (const c of COMMON) if (!covered(c)) out.push({ term: c.term, explain_ko: c.explain_ko, from: "common" })
  return out
}

/** 용어 설명 찾기: 별칭(MDD = 최대낙폭 등)까지. */
export function findTerm(items: TermItem[], term: string): TermItem | null {
  const keys = aliasesOf(term)
  return items.find((x) => keys.includes(norm(x.term))) ?? items.find((x) => aliasesOf(x.term).some((k) => keys.includes(k))) ?? null
}

/** 용어 옆 「?」. 설명이 없는 용어면 아무것도 그리지 않는다. */
export function Term({ t, label }: { t: string; label?: string }) {
  const rep = useReport()
  const items = useMemo(() => (rep ? glossaryOf(rep.doc) : COMMON.map((c) => ({ term: c.term, explain_ko: c.explain_ko, from: "common" as const }))), [rep])
  const hit = findTerm(items, t)
  if (!hit) return null
  return <HelpTip label={label ?? hit.term}><CitedText text={hit.explain_ko} /></HelpTip>
}

/** 상단 「투자 용어 설명」 패널. 리포트의 용어 풀이를 먼저, 없는 것은 공통 설명으로. 아래 전체 용어 풀이(근거 자료 섹션)는 그대로 남는다. */
export function GlossaryPanel({ doc, close, onFull }: { doc: ReportDoc; close: () => void; onFull?: () => void }) {
  const [q, setQ] = useState("")
  const all = useMemo(() => glossaryOf(doc), [doc])
  const hit = all.filter((x) => !q || norm(x.term + x.explain_ko).includes(norm(q)))
  const group = (from: TermItem["from"], title: string, desc: string) => {
    const xs = hit.filter((x) => x.from === from)
    if (!xs.length) return null
    return (
      <section className="space-y-3">
        <div><h3 className="text-sm font-bold text-slate-950">{title}</h3><p className="text-xs text-slate-500">{desc}</p></div>
        <dl className="divide-y divide-slate-100 rounded-xl border border-slate-200">{xs.map((g) => <div key={g.term} className="px-4 py-3"><dt className="text-sm font-semibold text-slate-900">{g.term}{g.mock && <MockTag />}</dt><dd className="mt-1 text-sm leading-6 text-slate-700"><CitedText text={g.explain_ko} /></dd></div>)}</dl>
      </section>
    )
  }
  return (
    <SidePanel title="투자 용어 설명" close={close}>
      <div className="space-y-5">
        <label className="relative block"><span className="sr-only">용어 찾기</span><Search className="pointer-events-none absolute left-3 top-1/2 size-4 -translate-y-1/2 text-slate-400" aria-hidden /><input value={q} onChange={(e) => setQ(e.target.value)} placeholder="용어 찾기 (예: CAGR, 낙폭)" className={`${inputClass} pl-9`} /></label>
        {group("report", "이 리포트의 용어 풀이", "분석 결과와 함께 만들어진 설명입니다. 리포트 아래 「어떤 자료를 근거로 분석했나요?」의 용어 풀이와 같습니다.")}
        {group("common", "함께 알아두면 좋은 용어", "이 리포트의 용어 풀이에 없는 용어를 쉽게 풀어 쓴 설명입니다.")}
        {!hit.length && <p className="text-sm text-slate-500">찾는 용어가 없습니다.</p>}
        {onFull && <button type="button" onClick={onFull} className="text-sm font-semibold text-blue-700 hover:underline">리포트의 전체 용어 풀이로 이동</button>}
      </div>
    </SidePanel>
  )
}
