import { useMemo, useRef, useState } from "react"
import { pctSigned, type EasySeries } from "./easyData"

// 왕초보용 그래프: 눈금·격자 없이 선과 끝 값만 보여 준다. 선 끝에 동그라미와 수익률, 아래에 시작·끝 날짜만 둔다.
// 마우스를 올리면 그날의 값을 보여 준다. drop 을 주면 가장 크게 떨어진 구간(고점 → 저점)을 띠와 두 점으로 표시한다.
// 크기는 viewBox 로 고정하고 폭에 맞춰 줄어든다 (PC 화면 기준).

const W = 1120
const INK = "#191c20", SUB = "#646b77", GUIDE = "#c9d0d8"

const ym = (d: string) => d.slice(0, 7).replace("-", ".")
const ymd = (d: string) => d.replaceAll("-", ".")

export function EasyChart({ dates, series, drop, label, draw = false, format = pctSigned, wide = false }: {
  dates: string[]; series: EasySeries[]; label: string; draw?: boolean
  format?: (v: number) => string   // 끝 값·마우스 올린 값의 글자 (기본은 수익률)
  wide?: boolean                    // 금액처럼 긴 글자: 오른쪽 여백과 말풍선을 넓힌다
  drop?: { peakIdx: number; troughIdx: number } | null
}) {
  const H = drop ? 490 : 430
  const pad = { l: 10, r: drop ? 24 : wide ? 214 : 136, t: 30, b: drop ? 122 : 52 }  // 떨어진 구간 그림은 끝 값 글자가 없어 오른쪽 여백을 줄이고, 아래에 날짜 두 줄 자리를 둔다
  const n = dates.length
  const ref = useRef<SVGSVGElement>(null)
  const [hover, setHover] = useState<number | null>(null)
  const g = useMemo(() => {
    const all = series.flatMap((s) => s.values.filter((v): v is number => v !== null))
    const lo = Math.min(0, ...all), hi = Math.max(0, ...all)
    const span = hi - lo || 1
    const y0 = lo - span * 0.06, y1 = hi + span * 0.08
    const x = (i: number) => pad.l + (n <= 1 ? 0 : (i / (n - 1)) * (W - pad.l - pad.r))
    const y = (v: number) => pad.t + (1 - (v - y0) / (y1 - y0)) * (H - pad.t - pad.b)
    const path = (s: EasySeries) => { let d = "", pen = false; s.values.forEach((v, i) => { if (v === null) { pen = false; return } d += `${pen ? "L" : "M"}${x(i).toFixed(1)} ${y(v).toFixed(1)} `; pen = true }); return d.trim() }
    // 끝 값 글자가 겹치지 않게 위에서부터 30px 간격을 지킨다
    const ends = series.map((s) => { let i = s.values.length - 1; while (i >= 0 && s.values[i] === null) i--; return { s, i, cy: i >= 0 ? y(s.values[i] as number) : 0, ty: 0 } }).filter((e) => e.i >= 0)
    const sorted = [...ends].sort((a, b) => a.cy - b.cy)
    sorted.forEach((e, k) => { e.ty = k === 0 ? e.cy : Math.max(e.cy, sorted[k - 1].ty + 30) })
    const over = sorted.length ? sorted[sorted.length - 1].ty - (H - pad.b) : 0
    if (over > 0) sorted.forEach((e) => { e.ty -= over })
    return { x, y, path, ends }
  }, [series, n, H, wide])  // eslint-disable-line react-hooks/exhaustive-deps -- pad 는 H(=drop 여부)로 정해진다
  if (n < 2 || !series.length) return null
  const mine = series.find((s) => s.mine) ?? series[0]
  const lines = [...series].sort((a, b) => Number(a.mine) - Number(b.mine))  // 내 전략을 맨 위에 그린다
  const bottom = H - pad.b

  const move = (e: React.PointerEvent<SVGSVGElement>) => {
    const box = ref.current?.getBoundingClientRect()
    if (!box || !box.width) return
    const vx = ((e.clientX - box.left) / box.width) * W
    const i = Math.round(((vx - pad.l) / (W - pad.l - pad.r)) * (n - 1))
    setHover(i < 0 || i > n - 1 ? null : i)
  }
  const tipRows = hover === null ? [] : series.filter((s) => s.values[hover] !== null)
  const tipW = wide ? 250 : 196, tipH = 34 + tipRows.length * 24
  const tipX = hover === null ? 0 : Math.min(Math.max(g.x(hover) + 14, pad.l), W - pad.r - tipW)

  const pk = drop ? { x: g.x(drop.peakIdx), y: g.y(mine.values[drop.peakIdx] ?? 0), d: dates[drop.peakIdx] } : null
  const tr = drop ? { x: g.x(drop.troughIdx), y: g.y(mine.values[drop.troughIdx] ?? 0), d: dates[drop.troughIdx] } : null
  // 두 날짜 글자의 자리: 보통은 각 점 바로 아래 가운데. 두 날짜가 가까우면 바깥쪽으로 벌리고, 그림 끝에 닿으면 안쪽으로 당긴다 (글자가 그림 밖으로 나가지 않게)
  const LABEL_W = 156
  const marks = (() => {
    if (!pk || !tr) return []
    const close = tr.x - pk.x < 200
    let a: { x: number; anchor: "start" | "middle" | "end" } = close ? { x: pk.x - 2, anchor: "end" } : { x: pk.x, anchor: "middle" }
    let b: { x: number; anchor: "start" | "middle" | "end" } = close ? { x: tr.x + 2, anchor: "start" } : { x: tr.x, anchor: "middle" }
    const left = (m: typeof a) => (m.anchor === "start" ? m.x : m.anchor === "end" ? m.x - LABEL_W : m.x - LABEL_W / 2)
    if (left(b) + LABEL_W > W) { b = { x: Math.min(W, tr.x + 2), anchor: "end" }; if (left(a) + LABEL_W > left(b) - 12) a = { x: left(b) - 12, anchor: "end" } }
    if (left(a) < 0) { a = { x: Math.max(0, pk.x - 2), anchor: "start" }; if (left(b) < left(a) + LABEL_W + 12) b = { x: left(a) + LABEL_W + 12, anchor: "start" } }
    return [{ p: pk, name: "내려가기 시작한 날", ...a }, { p: tr, name: "가장 많이 내려간 날", ...b }]
  })()

  return (
    <svg ref={ref} viewBox={`0 0 ${W} ${H}`} role="img" aria-label={label} className={`block h-auto w-full select-none ${draw ? "easy-draw" : ""}`} onPointerMove={move} onPointerLeave={() => setHover(null)}>
      <line x1={pad.l} x2={W - pad.r} y1={g.y(0)} y2={g.y(0)} stroke={GUIDE} strokeDasharray="2 6" strokeLinecap="round" />
      <text x={drop ? W - pad.r : W - pad.r + 14} y={bottom + 34} fontSize="15" fill={SUB} textAnchor={drop ? "end" : "start"}>{ym(dates[n - 1])}</text>
      <text x={pad.l} y={bottom + 34} fontSize="15" fill={SUB}>{ym(dates[0])}</text>

      {pk && tr && <rect x={pk.x} y={pad.t - 8} width={Math.max(2, tr.x - pk.x)} height={bottom - pad.t + 8} fill={INK} opacity="0.05" rx="6" />}

      {lines.map((s) => <path key={s.id} className="easy-line" pathLength={1} d={g.path(s)} fill="none" stroke={s.color} strokeWidth={s.mine ? 4.5 : 3.5} strokeLinejoin="round" strokeLinecap="round" />)}

      {!drop && <g className="easy-ends">
        {g.ends.map(({ s, i, cy, ty }) => (
          <g key={s.id}>
            <circle cx={g.x(i)} cy={cy} r={s.mine ? 10 : 9} fill={s.color} />
            <text x={g.x(i) + 20} y={ty + 8} fontSize={s.mine ? 25 : 21} fontWeight="800" fill={s.color} style={{ fontVariantNumeric: "tabular-nums", letterSpacing: "-0.02em" }}>{format(s.values[i] as number)}</text>
          </g>
        ))}
      </g>}

      {pk && tr && (
        <g className="easy-ends">
          {marks.map(({ p, name, anchor, x: tx }) => (
            <g key={name}>
              <line x1={p.x} x2={p.x} y1={p.y} y2={bottom + 52} stroke={INK} strokeWidth="1" opacity="0.45" />
              <circle cx={p.x} cy={p.y} r="7" fill={INK} />
              <circle cx={p.x} cy={bottom + 52} r="5" fill={INK} />
              <text x={tx} y={bottom + 80} fontSize="15" fontWeight="700" fill={INK} textAnchor={anchor}>{name}</text>
              <text x={tx} y={bottom + 102} fontSize="14" fill={SUB} textAnchor={anchor} style={{ fontVariantNumeric: "tabular-nums" }}>{ymd(p.d)}</text>
            </g>
          ))}
        </g>
      )}

      {hover !== null && tipRows.length > 0 && (
        <g pointerEvents="none">
          <line x1={g.x(hover)} x2={g.x(hover)} y1={pad.t - 8} y2={bottom} stroke={INK} strokeWidth="1" opacity="0.25" />
          {tipRows.map((s) => <circle key={s.id} cx={g.x(hover)} cy={g.y(s.values[hover] as number)} r="6" fill="#fff" stroke={s.color} strokeWidth="3" />)}
          <g transform={`translate(${tipX} ${pad.t - 12})`}>
            <rect width={tipW} height={tipH} rx="12" fill={INK} />
            <text x="14" y="23" fontSize="13" fill="#b8c0c9" style={{ fontVariantNumeric: "tabular-nums" }}>{ymd(dates[hover])}</text>
            {tipRows.map((s, k) => (
              <g key={s.id} transform={`translate(14 ${44 + k * 24})`}>
                <circle cx="5" cy="-5" r="5" fill={s.color} />
                <text x="18" y="0" fontSize="14" fill="#fff">{s.name}</text>
                <text x={tipW - 28} y="0" fontSize="14" fontWeight="700" fill="#fff" textAnchor="end" style={{ fontVariantNumeric: "tabular-nums" }}>{format(s.values[hover] as number)}</text>
              </g>
            ))}
          </g>
        </g>
      )}
    </svg>
  )
}
