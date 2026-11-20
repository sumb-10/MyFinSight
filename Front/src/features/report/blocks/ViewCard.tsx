import type { CardsBlock } from "../../../api/types"
import { Disclosure } from "../../../ui"
import { HelpTip } from "../terms"

// 뉴스 투자 의견(Black-Litterman 뷰) 카드를 읽기 쉽게: 서버 카드 문장(m4_portfolio/black_litterman.py view_summary · m5 report_blocks.scenario_cards)을
// 화면에서만 나눠 「종목 · 의견 · 비중 변화 / 이유」로 보여 주고, 사전 기대·신뢰 같은 숫자는 「숫자로 보기」 안에 쉬운 말로 둔다.
// 서버 문장이 아래 틀과 하나라도 다르면 null 을 돌려주고, 카드는 원문 그대로 그린다 (내용을 빠뜨리거나 잘못 바꾸지 않게).

type Card = CardsBlock["items"][number]
const STRENGTH: Record<string, string> = { 약: "약하게", 중: "보통", 강: "강하게" }
const pct = (s: string) => s.replace("-", "−")  // 서버 숫자 문자열 그대로, 빼기 기호만 읽기 쉬운 「−」로

export interface ParsedView {
  kind: "abs" | "rel"
  long: string[]; short: string[]
  dir: "up" | "down" | null       // 한 종목 의견의 방향 (예전 형식은 null)
  strength: string | null
  numbers: string                 // 「숫자로 보기」에 쓸 쉬운 말
  reason: string
}
export interface ParsedViewCard { summary: string; views: ParsedView[]; note: string | null; deltas: { ticker: string; value: string; noView: boolean }[]; hit: string | null; evidence: string | null; extra: { label: string; value: string }[] }

const confText = (c: string) => `확신 정도 ${Math.round(Number(c) * 100)}%`

/** 뷰 한 줄 → 구조. 틀이 다르면 null. */
export function parseViewLine(line: string): ParsedView | null {
  const t = line.replace(/^[·-]\s*/, "").trim()  // 시작일 카드는 「· 」, 현재 구성 카드는 「- 」로 시작한다
  let m = /^\[(절대)\] (\S+) (오름|내림)\((약|중|강)\) — 사전 기대 ([+\-−]?[\d.]+%) → 뷰 ([+\-−]?[\d.]+%)\/년 \(신뢰 ([\d.]+)\) — ([\s\S]+)$/.exec(t)
  if (m) return { kind: "abs", long: m[2].split("+"), short: [], dir: m[3] === "오름" ? "up" : "down", strength: m[4], numbers: `시장 기준 기대 연 ${pct(m[5])} → 뉴스 반영 후 연 ${pct(m[6])} · ${confText(m[7])}`, reason: m[8].trim() }
  m = /^\[(상대)\] (\S+) > (\S+) \((약|중|강)\) — 기대 차이를 (\S+) 쪽으로 ([+\-−]?[\d.]+%p) \(사전 차이 ([+\-−]?[\d.]+%) → 뷰 반영 차이 ([+\-−]?[\d.]+%)\/년( — 반영 뒤에도 .+? 쪽 기대가 낮음)?\) \(신뢰 ([\d.]+)\) — ([\s\S]+)$/.exec(t)
  if (m) return { kind: "rel", long: m[2].split("+"), short: m[3].split("+"), dir: null, strength: m[4], numbers: `두 쪽 기대 차이: 시장 기준 ${pct(m[7])} → 뉴스 반영 후 연 ${pct(m[8])} (${m[5]} 쪽으로 ${pct(m[6])})${m[9] ? ` · 반영 뒤에도 ${m[5]} 쪽 기대가 더 낮음` : ""} · ${confText(m[10])}`, reason: m[11].trim() }
  m = /^\[(절대|상대)\] (\S+)(?: > (\S+))? ([+\-−]?[\d.]+%)\/년 \(신뢰 ([\d.]+)\) — ([\s\S]+)$/.exec(t)  // 예전 형식 (방향·강도 없음)
  if (m) return { kind: m[1] === "상대" ? "rel" : "abs", long: m[2].split("+"), short: m[3] ? m[3].split("+") : [], dir: null, strength: null, numbers: `뉴스 반영 기대 ${m[1] === "상대" ? "차이 " : ""}연 ${pct(m[4])} · ${confText(m[5])}`, reason: m[6].trim() }
  return null
}

/** 카드 한 장 → 구조. 의견 줄이 없거나 하나라도 틀이 다르면 null (원문 그대로 그린다). */
export function parseViewCard(c: Card): ParsedViewCard | null {
  const lines = c.text_ko.split("\n")
  const viewIdx = lines.map((l, i) => (/^[·-]\s*\[(절대|상대)\]/.test(l) ? i : -1)).filter((i) => i >= 0)
  if (!viewIdx.length) return null
  const views = viewIdx.map((i) => parseViewLine(lines[i]))
  if (views.some((v) => !v)) return null
  const first = viewIdx[0], last = viewIdx[viewIdx.length - 1]
  if (viewIdx.some((i, k) => i !== first + k)) return null  // 의견 줄은 이어서 나온다
  const meta = (k: string) => c.meta.find((m) => m.label_ko === k)?.value ?? null
  const DELTA_LABELS = ["기준 대비 주요 변화", "기준 비중 대비 주요 변화"]  // 시작일 카드 · 현재 구성 카드
  const rawDelta = DELTA_LABELS.map(meta).find((x) => x !== null) ?? null
  // 「NOW +1.5%p, NVDA -0.9%p, GOOGL -0.5%p (뷰 없음, 재배분)」 — 괄호 안에도 쉼표가 있어 쉼표로 자르지 않고 종목 단위로 읽는다. 남는 글자가 있으면 틀이 다른 것
  const DELTA = /(\S+) ([+\-−]?[\d.]+%p)( \(뷰 없음, 재배분\))?/g
  const deltas = rawDelta && rawDelta !== "변화 없음" ? [...rawDelta.matchAll(DELTA)].map((m) => ({ ticker: m[1], value: pct(m[2]), noView: !!m[3] })) : []
  if (rawDelta && rawDelta !== "변화 없음" && rawDelta.replace(DELTA, "").replace(/[,\s]/g, "") !== "") return null
  const hit = meta("뷰 적중률(백테스트)")
  const known = new Set([...DELTA_LABELS, "뷰 적중률(백테스트)", "근거"])
  const extra = c.meta.filter((m) => !known.has(m.label_ko)).map((m) => ({ label: m.label_ko, value: m.value }))  // 그 밖의 서버 항목(모형상 기대 수익 등)은 그대로 아래에
  return { summary: lines.slice(0, first).join("\n").trim(), views: views as ParsedView[], note: lines.slice(last + 1).join("\n").trim() || null, deltas: deltas as ParsedViewCard["deltas"], hit: hit && hit !== "-" ? hit : null, evidence: meta("근거"), extra }
}

const Badge = ({ v }: { v: ParsedView }) => {
  const s = v.strength ? ` (${STRENGTH[v.strength] ?? v.strength})` : ""
  if (v.kind === "rel") return <span className="inline-flex shrink-0 items-center rounded-full border border-slate-200 bg-slate-50 px-2 py-0.5 text-xs font-semibold text-slate-700">{v.long.join("·")}를 {v.short.join("·")}보다 긍정적으로 평가{s}</span>
  if (v.dir === "up") return <span className="inline-flex shrink-0 items-center rounded-full border border-emerald-200 bg-emerald-50 px-2 py-0.5 text-xs font-semibold text-emerald-800">▲ 상승 의견{s}</span>
  if (v.dir === "down") return <span className="inline-flex shrink-0 items-center rounded-full border border-red-200 bg-red-50 px-2 py-0.5 text-xs font-semibold text-red-800">▼ 하락 의견{s}</span>
  return <span className="inline-flex shrink-0 items-center rounded-full border border-slate-200 bg-slate-50 px-2 py-0.5 text-xs font-semibold text-slate-700">투자 의견</span>
}

/** 정리된 의견 카드 본문. text: 인용 표시를 그리는 함수(CitedText), evidence: 근거 줄(기존 링크 그대로). */
/** between: 「뉴스로 만든 투자 의견」과 「숫자로 보기」 사이에 넣을 내용 (3. 포트폴리오 구성의 「종목·비중을 정한 근거」, 2026-11-16 사용자 요청). */
export function ViewCardBody({ p, text, evidence, between }: { p: ParsedViewCard; text: (t: string) => React.ReactNode; evidence: React.ReactNode; between?: React.ReactNode }) {
  const delta = new Map(p.deltas.map((d) => [d.ticker, d]))
  const legs = new Set(p.views.flatMap((v) => [...v.long, ...v.short]))
  const others = p.deltas.filter((d) => !legs.has(d.ticker))
  const change = (tickers: string[]) => tickers.map((t) => delta.get(t)).filter(Boolean).map((d) => (tickers.length > 1 ? `${d!.ticker} ${d!.value}` : d!.value)).join(" · ")
  return (
    <div className="mt-2 space-y-4">
      {p.summary && <p className="whitespace-pre-line break-words text-sm leading-6 text-slate-700">{text(p.summary)}</p>}
      <div>
        <p className="flex items-center gap-1 text-xs font-semibold text-slate-500">뉴스로 만든 투자 의견
          <HelpTip label="뉴스로 만든 투자 의견">분석 모델이 뉴스·공시를 읽고 제안한 종목 의견입니다. 한 종목이 오르거나 내릴 것이라는 의견(절대 의견)과, 두 종목 가운데 어느 쪽이 나을 것이라는 의견(상대 의견)이 있습니다. 의견의 확신 정도만큼 기준 비중에서 조금씩 비중을 옮깁니다(Black-Litterman 방식).</HelpTip>
        </p>
        <ul className="mt-1.5 divide-y divide-slate-100 rounded-xl border border-slate-200">
          {p.views.map((v, i) => {
            const ch = change([...v.long, ...v.short])
            return (
              <li key={i} className="px-4 py-3">
                <div className="flex flex-wrap items-center gap-x-3 gap-y-1.5">
                  <b className="text-sm font-bold text-slate-950">{v.kind === "rel" ? `${v.long.join("+")} vs ${v.short.join("+")}` : v.long.join("+")}</b>
                  <Badge v={v} />
                  {ch && <span className="ml-auto text-sm font-semibold tabular-nums text-slate-900">비중 {ch}</span>}
                </div>
                <p className="mt-1 break-words text-sm leading-6 text-slate-600">{text(v.reason)}</p>
              </li>
            )
          })}
          {others.map((d) => (
            <li key={d.ticker} className="px-4 py-3">
              <div className="flex flex-wrap items-center gap-x-3 gap-y-1.5">
                <b className="text-sm font-bold text-slate-950">{d.ticker}</b>
                <span className="inline-flex shrink-0 items-center rounded-full border border-slate-200 bg-white px-2 py-0.5 text-xs font-semibold text-slate-500">{d.noView ? "다른 종목 조정에 따른 포트폴리오 비중 변화" : "의견 없음"}</span>
                <span className="ml-auto text-sm font-semibold tabular-nums text-slate-900">비중 {d.value}</span>
              </div>
              <p className="mt-1 text-sm leading-6 text-slate-600">{d.noView ? "이 종목에 대한 의견은 없고, 다른 종목의 포트폴리오 비중을 옮기면서 함께 바뀌었습니다." : "기준 비중과 달라진 종목입니다."}</p>
            </li>
          ))}
        </ul>
        {p.note && <p className="mt-2 text-xs leading-5 text-slate-500">{text(p.note)}</p>}
      </div>
      {between}
      <Disclosure size="sm" title="숫자로 보기">
        <ul className="space-y-1.5 text-sm leading-6 text-slate-700">
          {p.views.map((v, i) => <li key={i}><b className="font-semibold text-slate-900">{v.kind === "rel" ? `${v.long.join("+")} vs ${v.short.join("+")}` : v.long.join("+")}</b> · {v.numbers}</li>)}
        </ul>
        <p className="mt-2 text-xs leading-5 text-slate-500">시장 기준 기대는 뉴스를 반영하기 전 시장 가격에 담긴 연 기대 수익률이고, 확신 정도가 높을수록 포트폴리오 비중을 더 많이 옮깁니다. 앞으로의 수익을 뜻하지 않습니다.</p>
      </Disclosure>
      <dl className="space-y-1 text-xs text-slate-600">
        {p.hit && <div className="flex gap-2"><dt className="shrink-0 font-medium">과거에 이런 의견이 맞은 비율</dt><dd>{p.hit} (백테스트)</dd></div>}
        {p.extra.map((m) => <div key={m.label} className="flex gap-2"><dt className="font-medium">{m.label}</dt><dd className="shrink-0">{m.value}</dd></div>)}
        {evidence}
      </dl>
    </div>
  )
}
