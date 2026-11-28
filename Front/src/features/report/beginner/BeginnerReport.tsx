import { useMemo } from "react"
import { Activity, ArrowRight } from "lucide-react"
import type { ReportDoc } from "../../../api/types"
import { Button } from "../../../ui"
import { PALETTE } from "../../../lib/format"
import { EasyChart } from "./EasyChart"
import { EASY_BLUE, easyModel, fromMillion, pctAbs, pctSigned, type EasyModel, type EasySeries } from "./easyData"
import "./beginner.css"

// 왕초보용 리포트 화면 (2026-11-28). 원래 리포트와 같은 서버 문서를 쉬운 말과 큰 그림으로 다시 보여 준다:
// 얼마나 올랐나(그래프 · 비교 대상 · 100만원 예시) → 넣은 돈과 불어난 돈 → 해마다의 수익 → 가장 크게 떨어진 때 → 어떤 회사에 얼마씩 → 한 분야에 몰렸나 → 누가 벌어 줬나
// → 어떻게 골랐나 → 미리 알아둘 점 → 다음에 할 일.
// 연환산·Sharpe·뉴스 반영 구성·조건 점검 표·리밸런싱 기록·근거 번호는 뺐다 — 오른쪽 위 토글의 「원래 리포트」에 그대로 있다.
// 숫자와 문장은 서버 값 그대로다 (easyData.ts).

export type ReportViewMode = "easy" | "full"

/** 리포트 머리 오른쪽 위의 화면 전환. 고른 쪽을 어두운 알약으로 표시한다. */
export function ViewToggle({ value, onChange }: { value: ReportViewMode; onChange: (v: ReportViewMode) => void }) {
  return (
    <div role="radiogroup" aria-label="리포트 화면" className="inline-flex shrink-0 rounded-full bg-[#e3e7eb] p-1">
      {([["easy", "왕초보용"], ["full", "원래 리포트"]] as const).map(([v, label]) => (
        <button key={v} type="button" role="radio" aria-checked={value === v} onClick={() => onChange(v)}
          className={`rounded-full px-4 py-1.5 text-sm font-bold transition-colors ${value === v ? "bg-[#191c20] text-white" : "text-slate-600 hover:text-slate-950"}`}>{label}</button>
      ))}
    </div>
  )
}

const INK = "text-[#191c20]"
const LEAD = "text-[22px] font-bold leading-8 text-[#a3abb5]"   // 큰 숫자 앞의 회색 한 줄 (강조 낱말만 먹색)
const BODY = "max-w-3xl text-[17px] leading-8 text-body"
const STAT_NAME = `text-[21px] font-bold leading-8 ${INK}`

/** 그래프 범례: 어두운 알약 안에 선 모양 표시와 이름. */
function Pills({ series }: { series: EasySeries[] }) {
  return (
    <ul aria-label="그래프 범례" className="flex shrink-0 flex-wrap justify-end gap-2.5 pb-2">
      {series.map((s) => (
        <li key={s.id} className="inline-flex items-center gap-2.5 rounded-[14px] bg-[#1c1f23] px-5 py-3 text-[15px] font-bold text-white">
          <svg width="30" height="14" viewBox="0 0 30 14" aria-hidden><line x1="1" x2="16" y1="7" y2="7" stroke={s.color} strokeWidth="3" strokeLinecap="round" /><circle cx="22" cy="7" r="7" fill={s.color} /></svg>
          {s.name}
        </li>
      ))}
    </ul>
  )
}

function Stat({ name, value, color }: { name: string; value: string; color: string }) {
  return <div><dt className={STAT_NAME}>{name}</dt><dd className="easy-num mt-1" style={{ color }}>{value}</dd></div>
}

/** 받침에 맞춘 조사: 원 → 을, 달러 → 를 / 500 → 은, 코스피 200 → 은 … (숫자·영문은 읽는 소리 기준으로 흔한 경우만) */
const hasFinal = (w: string) => {
  const c = w.trim().slice(-1)
  const code = c.charCodeAt(0)
  if (code >= 0xac00 && code <= 0xd7a3) return (code - 0xac00) % 28 !== 0
  return /[013678]/.test(c) || /[lmnr]/i.test(c)  // 영·일·삼·육·칠·팔, 엘·엠·엔·알
}
const eun = (w: string) => `${w}${hasFinal(w) ? "은" : "는"}`
const eul = (w: string) => `${w}${hasFinal(w) ? "을" : "를"}`
const iga = (w: string) => `${w}${hasFinal(w) ? "이" : "가"}`
const euro = (w: string) => `${w}${hasFinal(w) ? "으로" : "로"}`

function Performance({ m }: { m: EasyModel }) {
  if (m.total === null) return null
  const up = m.total >= 0
  const b = m.bench
  const line2 = !up ? `${pctAbs(m.total)} 떨어졌어요.` : b ? (m.total >= b.total ? `${b.name}보다 더 올랐어요.` : `${b.name}보다 덜 올랐어요.`) : `${pctAbs(m.total)} 올랐어요.`
  return (
    <section aria-labelledby="easy-perf">
      <div className="flex items-end justify-between gap-8">
        <h2 id="easy-perf" className="easy-display">내 전략은 {m.periodText} 동안<br /><em>{line2}</em></h2>
        <Pills series={m.series} />
      </div>
      <div className="mt-4"><EasyChart draw dates={m.dates} series={m.series} label={`누적 수익률 그래프: ${m.series.filter((s) => s.last !== null).map((s) => `${s.name} ${pctSigned(s.last as number)}`).join(", ")}`} /></div>
      <p className={`mt-12 ${LEAD}`}>지난 <span className={INK}>{m.periodText} 동안 투자</span>했다면,</p>
      <dl className="mt-5 flex flex-wrap gap-x-16 gap-y-8">
        <Stat name="내 전략은" value={pctSigned(m.total)} color={EASY_BLUE} />
        {m.series.filter((s) => !s.mine && s.last !== null).map((s) => <Stat key={s.id} name={eun(s.name)} value={pctSigned(s.last as number)} color={s.color} />)}
        <Stat name="100만원을 넣었다면" value={fromMillion(m.total)} color="#191c20" />
      </dl>
      <p className={`mt-9 ${BODY}`}>과거의 실제 주가로 계산한 결과예요.{m.yearly !== null && m.yearly > 0 ? ` 1년에 평균 ${pctAbs(m.yearly)}씩 오른 셈이에요.` : m.yearly !== null && m.yearly < 0 ? ` 1년에 평균 ${pctAbs(m.yearly)}씩 떨어진 셈이에요.` : ""}{b ? ` ${eun(b.name)} 같은 날 같은 돈을 넣고 그대로 뒀을 때의 결과예요.` : ""}</p>
    </section>
  )
}

/** 넣은 돈과 그 돈의 가치: 두 선. 매달 넣은 돈이 있으면 「넣은 돈」 선이 계단처럼 올라간다. */
function Money({ m }: { m: EasyModel }) {
  const x = m.money
  if (!x) return null
  const up = x.final >= x.invested
  return (
    <section aria-labelledby="easy-money">
      <div className="flex items-end justify-between gap-8">
        <h2 id="easy-money" className="easy-display">넣은 돈 {iga(x.text(x.invested))}<br /><em>{up ? `${iga(x.text(x.final))} 됐어요.` : `${euro(x.text(x.final))} 줄었어요.`}</em></h2>
        <Pills series={x.series} />
      </div>
      <div className="mt-4"><EasyChart wide format={x.text} dates={m.dates} series={x.series} label={`넣은 돈과 ${x.series[0].name} 그래프: 넣은 돈 ${x.text(x.invested)}, ${x.series[0].name} ${x.text(x.final)}`} /></div>
      <p className={`mt-8 ${BODY}`}>{x.monthly ? "처음 넣은 돈에 매달 넣은 돈을 더한 금액과 견줬어요." : "처음에 한 번 넣은 돈과 견줬어요."}{x.won ? " 원화 금액은 분석한 날의 환율로 바꾼 값이에요." : ""}</p>
    </section>
  )
}

/** 해마다의 수익률: 내 전략과 비교 대상을 나란히 세운 막대. 0 선 위는 오른 해, 아래는 떨어진 해. */
function YearBars({ y, benchColor }: { y: NonNullable<EasyModel["byYear"]>; benchColor: string }) {
  const W = 1120, H = 380, top = 46, bottom = 60
  const all = [...y.mine, ...(y.bench ?? [])].filter((v): v is number => v !== null)
  const hi = Math.max(0, ...all), lo = Math.min(0, ...all)
  const span = hi - lo || 1
  const yOf = (v: number) => top + ((hi - v) / span) * (H - top - bottom - (lo < 0 ? 26 : 0))
  const group = W / y.years.length
  const bw = Math.min(72, group * 0.26), gap = 12
  const bar = (v: number | null, cx: number, color: string, big: boolean) => {
    if (v === null) return null
    const y0 = yOf(0), y1 = yOf(v)
    const h = Math.max(3, Math.abs(y1 - y0))
    return (
      <g>
        <rect x={cx - bw / 2} y={v >= 0 ? y0 - h : y0} width={bw} height={h} rx="8" fill={color} />
        <text x={cx} y={v >= 0 ? y0 - h - 10 : y0 + h + 22} textAnchor="middle" fontSize={big ? 19 : 16} fontWeight="800" fill={color} style={{ fontVariantNumeric: "tabular-nums", letterSpacing: "-0.02em" }}>{pctSigned(v)}</text>
      </g>
    )
  }
  const label = `해마다의 수익률 막대: ${y.years.map((yr, i) => `${yr}년 내 전략 ${y.mine[i] === null ? "없음" : pctSigned(y.mine[i] as number)}${y.bench && y.bench[i] !== null ? `, ${y.benchName} ${pctSigned(y.bench[i] as number)}` : ""}`).join(" / ")}`
  return (
    <svg viewBox={`0 0 ${W} ${H}`} role="img" aria-label={label} className="block h-auto w-full">
      <line x1="0" x2={W} y1={yOf(0)} y2={yOf(0)} stroke="#c9d0d8" strokeWidth="1.5" />
      {y.years.map((yr, i) => {
        const cx = group * (i + 0.5)
        return (
          <g key={yr}>
            {bar(y.mine[i], y.bench ? cx - bw / 2 - gap / 2 : cx, EASY_BLUE, true)}
            {y.bench && bar(y.bench[i], cx + bw / 2 + gap / 2, benchColor, false)}
            <text x={cx} y={H - 14} textAnchor="middle" fontSize="18" fontWeight="700" fill="#191c20">{yr}년</text>
          </g>
        )
      })}
    </svg>
  )
}

function Yearly({ m }: { m: EasyModel }) {
  const y = m.byYear
  if (!y) return null
  const vals = y.mine.filter((v): v is number => v !== null)
  if (vals.length < 2) return null
  const down = vals.filter((v) => v < 0).length
  const bench = m.series.find((s) => !s.mine)
  const pills: EasySeries[] = [{ ...(m.series.find((s) => s.mine) ?? m.series[0]) }, ...(y.bench && y.benchName ? [{ id: "bench", name: y.benchName, mine: false, color: bench?.color ?? "#f2953b", values: [], last: null }] : [])]
  return (
    <section aria-labelledby="easy-year">
      <div className="flex items-end justify-between gap-8">
        <h2 id="easy-year" className="easy-display">{down > 0 ? <>{vals.length}년 가운데<br /><em>{down}년은 떨어졌어요.</em></> : <>해마다 올랐지만<br /><em>오른 폭은 달랐어요.</em></>}</h2>
        <Pills series={pills} />
      </div>
      <div className="mt-8"><YearBars y={y} benchColor={bench?.color ?? "#f2953b"} /></div>
      {y.note && <p className={`mt-6 ${BODY}`}>{y.note}</p>}
    </section>
  )
}

const SECTOR_TINTS = [EASY_BLUE, "#8fb3f8", "#bcd2fb", "#d9e5fd"]

/** 한 분야에 몰렸나: 지금 구성의 회사별 비중을 분야로 묶은 막대 하나. */
function Sectors({ m }: { m: EasyModel }) {
  const top = m.sectors[0]
  if (!top) return null
  const pct0 = (v: number) => `${Math.round(v * 100)}%`
  const many = top.weight < 0.5
  const rows = [...m.sectors.map((x, i) => ({ ...x, color: SECTOR_TINTS[Math.min(i, SECTOR_TINTS.length - 1)] })), ...(m.cash ? [{ name: "현금", weight: m.cash.weight, color: "#cdd3da" }] : [])]
  return (
    <section aria-labelledby="easy-sector">
      <h2 id="easy-sector" className="easy-display">{many ? <>여러 분야에<br /><em>나눠 담겨 있어요.</em></> : <>돈의 {pct0(top.weight)}가<br /><em>{top.name} 회사에 몰려 있어요.</em></>}</h2>
      <div className="mt-10 flex h-14 overflow-hidden rounded-2xl" aria-hidden>
        {rows.map((x) => <span key={x.name} style={{ width: `${x.weight * 100}%`, background: x.color }} />)}
      </div>
      <ul aria-label="분야별 비중" className="mt-5 flex flex-wrap gap-x-10 gap-y-3">
        {rows.map((x) => <li key={x.name} className="flex items-center gap-2.5 text-[17px]"><span className="size-3.5 rounded-full" style={{ background: x.color }} aria-hidden /><span className={`font-bold ${INK}`}>{x.name}</span><span className="tabular-nums text-sub">{pct0(x.weight)}</span></li>)}
      </ul>
      {!many && <p className={`mt-8 ${BODY}`}>한 분야가 흔들리면 담은 회사들이 함께 흔들릴 수 있어요.</p>}
    </section>
  )
}

/** 누가 벌어 줬나: 수익에 가장 많이 보탠 회사 3개 (+ 가장 많이 깎은 회사 1개). */
function Contrib({ m }: { m: EasyModel }) {
  const c = m.contrib
  if (!c || m.total === null) return null
  const max = Math.max(...c.top.map((x) => x.value), Math.abs(c.worst?.value ?? 0), 1e-9)
  const sum = c.top.reduce((a, x) => a + x.value, 0)
  const row = (x: { name: string; value: number }, color: string) => (
    <li key={x.name} className="grid grid-cols-[minmax(0,18rem)_1fr_7.5rem] items-center gap-6 border-b border-[#dfe3e8] py-5">
      <span className={`truncate text-[21px] font-bold ${INK}`}>{x.name}</span>
      <span className="block h-6" aria-hidden><span className="block h-full rounded-full" style={{ width: `${Math.max(1.5, (Math.abs(x.value) / max) * 100)}%`, background: color }} /></span>
      <span className="text-right text-[24px] font-extrabold tabular-nums tracking-tight" style={{ color }}>{pctSigned(x.value)}</span>
    </li>
  )
  return (
    <section aria-labelledby="easy-contrib">
      <h2 id="easy-contrib" className="easy-display"><em>{c.top[0].name} 주식이</em><br />가장 많이 벌어 줬어요.</h2>
      <p className={`mt-10 ${LEAD}`}>전체 수익 <span className={INK}>{pctSigned(m.total)}</span> 가운데,</p>
      <ul aria-label="수익에 많이 보탠 회사" className="mt-3 max-w-5xl">
        {c.top.map((x) => row(x, EASY_BLUE))}
        {c.worst && row(c.worst, "#191c20")}
      </ul>
      <p className={`mt-8 ${BODY}`}>{c.top.length > 1 ? `위 ${c.top.length}개 회사가 ${pctSigned(sum)}를 보탰어요.` : ""}{c.worst ? ` ${c.worst.name} 주식은 수익을 ${pctAbs(c.worst.value)} 깎았어요.` : ""}{m.total > 0 && c.top[0].value / m.total >= 0.5 ? " 수익의 절반 넘게가 한 회사에서 나왔어요." : ""}</p>
    </section>
  )
}

function Risk({ m }: { m: EasyModel }) {
  const d = m.drop
  if (!d) return null
  const mine = m.series.find((s) => s.mine)
  const marks = d.peakIdx !== null && d.troughIdx !== null && mine ? { peakIdx: d.peakIdx, troughIdx: d.troughIdx } : null
  return (
    <section aria-labelledby="easy-risk">
      <h2 id="easy-risk" className="easy-display">가장 크게 떨어졌을 때는<br /><em>{pctAbs(d.mdd)}까지 내려갔어요.</em></h2>
      {marks && mine && <div className="mt-6"><EasyChart dates={m.dates} series={[mine]} drop={marks} label={`가장 크게 떨어진 구간 그래프: ${m.dates[marks.peakIdx]} 부터 ${m.dates[marks.troughIdx]} 까지 ${pctAbs(d.mdd)} 하락`} /></div>}
      <p className={`mt-12 ${LEAD}`}>가장 크게 <span className={INK}>떨어진 폭</span>을 견주면,</p>
      <dl className="mt-5 flex flex-wrap gap-x-16 gap-y-8">
        <Stat name="내 전략은" value={`−${pctAbs(d.mdd)}`} color={EASY_BLUE} />
        {d.benchMdd !== null && d.benchName && <Stat name={eun(d.benchName)} value={`−${pctAbs(d.benchMdd)}`} color={m.series.find((s) => !s.mine)?.color ?? "#f2953b"} />}
        {d.tolerance !== null && <Stat name="내가 견딜 수 있다고 한 폭은" value={`−${pctAbs(d.tolerance)}`} color="#191c20" />}
      </dl>
      <p className={`mt-9 ${BODY}`}>100만원이었던 돈이 한때 {fromMillion(-d.mdd)}까지 줄었던 셈이에요.{d.over === true ? " 내가 견딜 수 있다고 답한 것보다 더 크게 떨어졌어요." : d.over === false ? " 내가 견딜 수 있다고 답한 범위 안이었어요." : ""}</p>
    </section>
  )
}

function Holdings({ m }: { m: EasyModel }) {
  if (!m.holdings.length) return null
  // 색: 범주 색 8개를 차례로 돌려 쓴다 (원래 리포트의 종목 색은 9번째부터 회색이라, 회사가 많으면 막대의 절반이 회색 한 덩어리로 보였다)
  const colorOf = new Map(m.holdings.map((h, i) => [h.ticker, PALETTE[i % PALETTE.length]]))
  const holdingColor = (t: string) => colorOf.get(t) ?? "#cdd3da"
  const base = m.baseText ? `${m.baseNote ? `${m.baseNote} ` : ""}${eul(m.baseText)}` : "투자금을"
  return (
    <section aria-labelledby="easy-hold">
      <h2 id="easy-hold" className="easy-display">{base}<br /><em>{m.holdings.length}개 회사에 나눠 담아요.</em></h2>
      <div className="mt-10 flex h-5 overflow-hidden rounded-full" aria-hidden>
        {m.holdings.map((h) => <span key={h.ticker} style={{ width: `${h.weight * 100}%`, background: holdingColor(h.ticker) }} />)}
        {m.cash && <span style={{ width: `${m.cash.weight * 100}%`, background: "#cdd3da" }} />}
      </div>
      <ul aria-label="회사별 투자 금액" className="mt-8 grid grid-cols-2 gap-x-14">
        {m.holdings.map((h) => (
          <li key={h.ticker} className="flex items-center gap-4 border-b border-[#dfe3e8] py-4">
            <span className="size-3.5 shrink-0 rounded-full" style={{ background: holdingColor(h.ticker) }} aria-hidden />
            <span className="min-w-0 flex-1">
              <span className={`block truncate text-[19px] font-bold ${INK}`}>{h.name}</span>
              {h.about && <span className="block truncate text-sm text-sub" title={h.about}>{h.about}</span>}
            </span>
            <span className="shrink-0 text-right">
              <span className={`block text-[19px] font-bold tabular-nums ${INK}`}>{h.amount}</span>
              <span className="block text-sm tabular-nums text-sub">{(h.weight * 100).toFixed(1)}%</span>
            </span>
          </li>
        ))}
        {m.cash && (
          <li className="flex items-center gap-4 border-b border-[#dfe3e8] py-4">
            <span className="size-3.5 shrink-0 rounded-full bg-[#cdd3da]" aria-hidden />
            <span className="min-w-0 flex-1"><span className={`block text-[19px] font-bold ${INK}`}>현금</span><span className="block text-sm text-sub">주식을 사지 않고 남겨 두는 돈</span></span>
            <span className="shrink-0 text-right">{m.cash.amount && <span className={`block text-[19px] font-bold tabular-nums ${INK}`}>{m.cash.amount}</span>}<span className="block text-sm tabular-nums text-sub">{(m.cash.weight * 100).toFixed(1)}%</span></span>
          </li>
        )}
      </ul>
      {m.weighting && <p className={`mt-8 ${BODY}`}>{m.weighting}</p>}
    </section>
  )
}

function How({ m }: { m: EasyModel }) {
  if (!m.how && m.steps.length < 2) return null
  return (
    <section aria-labelledby="easy-how">
      <h2 id="easy-how" className="easy-display">이런 순서로<br /><em>회사를 골랐어요.</em></h2>
      {m.steps.length >= 2 && (
        <ol aria-label="회사를 고른 순서" className="mt-10 flex flex-wrap items-end gap-x-8 gap-y-6">
          {m.steps.map((s, i) => (
            <li key={s.label} className="flex items-end gap-8">
              {i > 0 && <ArrowRight className="mb-4 size-8 text-[#a3abb5]" aria-hidden />}
              <span><span className={`block ${STAT_NAME}`}>{s.label}</span><span className="easy-num mt-1 block" style={{ color: i === m.steps.length - 1 ? EASY_BLUE : "#191c20" }}>{s.count.toLocaleString("en-US")}개</span></span>
            </li>
          ))}
        </ol>
      )}
      {m.how && <p className={`mt-9 ${BODY}`}>{m.how}</p>}
    </section>
  )
}

function Alerts({ m }: { m: EasyModel }) {
  if (!m.alerts.length && !m.allClear) return null
  if (!m.alerts.length) return <section aria-labelledby="easy-alert"><h2 id="easy-alert" className="easy-display">내가 정한 조건을<br /><em>모두 지켰어요.</em></h2></section>
  return (
    <section aria-labelledby="easy-alert">
      <h2 id="easy-alert" className="easy-display">미리 알아둘 점이<br /><em>{m.alerts.length}가지 있어요.</em></h2>
      <ul className="mt-8 max-w-4xl">
        {m.alerts.map((t, i) => <li key={i} className="flex gap-4 border-b border-[#dfe3e8] py-5 text-[17px] leading-8 text-body"><span className="mt-3 size-2 shrink-0 rounded-full bg-[#191c20]" aria-hidden /><span className="min-w-0 break-words">{t}</span></li>)}
      </ul>
    </section>
  )
}

function Next({ m, canPaper, onStartPaper, onFull }: { m: EasyModel; canPaper: boolean; onStartPaper: () => void; onFull: () => void }) {
  return (
    <section aria-labelledby="easy-next">
      <h2 id="easy-next" className="easy-display">{canPaper ? <>실제 돈을 넣기 전에<br /><em>모의투자로 연습할 수 있어요.</em></> : <>더 자세한 내용은<br /><em>원래 리포트에 있어요.</em></>}</h2>
      <div className="mt-8 flex flex-wrap gap-3">
        {canPaper && <Button onClick={onStartPaper}><Activity className="size-4" />모의투자 시작</Button>}
        <Button variant="secondary" onClick={onFull}>원래 리포트 보기</Button>
      </div>
      {m.next.length > 0 && (
        <>
          <h3 className={`mt-12 text-[21px] font-bold ${INK}`}>다음에 살펴볼 것</h3>
          <ul className="mt-3 max-w-4xl">
            {m.next.map((t, i) => <li key={i} className="flex gap-4 border-b border-[#dfe3e8] py-5 text-[17px] leading-8 text-body"><span className="mt-3 size-2 shrink-0 rounded-full bg-[#191c20]" aria-hidden /><span className="min-w-0 break-words">{t}</span></li>)}
          </ul>
        </>
      )}
    </section>
  )
}

/** 왕초보용 화면을 만들 수 있는 리포트인가 (요약과 그래프 계열이 있는 문서). */
export const canShowEasy = (doc: ReportDoc) => { const m = easyModel(doc); return !!m && m.total !== null }

export function BeginnerReport({ doc, canPaper, onStartPaper, onFull }: { doc: ReportDoc; canPaper: boolean; onStartPaper: () => void; onFull: () => void }) {
  const m = useMemo(() => easyModel(doc), [doc])
  if (!m) return null
  return (
    <div className="easy space-y-32 pb-8 pt-10" data-view="easy">
      <Performance m={m} />
      <Money m={m} />
      <Yearly m={m} />
      <Risk m={m} />
      <Holdings m={m} />
      <Sectors m={m} />
      <Contrib m={m} />
      <How m={m} />
      <Alerts m={m} />
      <Next m={m} canPaper={canPaper} onStartPaper={onStartPaper} onFull={onFull} />
    </div>
  )
}
