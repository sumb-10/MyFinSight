// 목업 자료 생성 도구. 무작위처럼 보이는 값도 시드가 정해진 결정적 난수로 만들어, 새로고침해도 같은 숫자가 나온다.

/** mulberry32: 시드가 같으면 같은 수열. */
export function rng(seed: number) {
  let a = seed >>> 0
  return () => {
    a = (a + 0x6d2b79f5) >>> 0
    let t = a
    t = Math.imul(t ^ (t >>> 15), t | 1)
    t ^= t + Math.imul(t ^ (t >>> 7), t | 61)
    return ((t ^ (t >>> 14)) >>> 0) / 4294967296
  }
}

/** 문자열 → 시드. */
export const seedOf = (s: string) => { let h = 2166136261; for (const c of s) h = Math.imul(h ^ c.charCodeAt(0), 16777619); return h >>> 0 }

/** 표준정규 (Box–Muller). */
export const normal = (r: () => number) => Math.sqrt(-2 * Math.log(Math.max(1e-12, r()))) * Math.cos(2 * Math.PI * r())

export const iso = (d: Date) => d.toISOString().slice(0, 10)
/** 시각 (서버 now_iso() 와 같은 모양: 이 PC 시간대 + 오프셋, 예 2026-11-09T03:21:00+09:00).
 *  toISOString().slice(0, 19) 는 UTC 시각에서 시간대를 떼어 버려, 화면이 9시간 이른 시각을 보이고 경과 시간이 9시간 늘어난다. */
export function localIso(ms: number = Date.now()) {
  const d = new Date(ms), p = (n: number) => String(Math.abs(n)).padStart(2, "0")
  const off = -d.getTimezoneOffset()
  return `${d.getFullYear()}-${p(d.getMonth() + 1)}-${p(d.getDate())}T${p(d.getHours())}:${p(d.getMinutes())}:${p(d.getSeconds())}${off >= 0 ? "+" : "-"}${p(Math.floor(Math.abs(off) / 60))}:${p(Math.abs(off) % 60)}`
}
export const addDays = (s: string, n: number) => { const d = new Date(`${s}T00:00:00Z`); d.setUTCDate(d.getUTCDate() + n); return iso(d) }

/** 평일만 (휴장일은 단순화를 위해 넣지 않는다 — 목업). start·end 포함. */
export function tradingDays(start: string, end: string): string[] {
  const out: string[] = []
  for (let d = start; d <= end; d = addDays(d, 1)) { const w = new Date(`${d}T00:00:00Z`).getUTCDay(); if (w !== 0 && w !== 6) out.push(d) }
  return out
}

export const round = (x: number, n = 2) => { const f = 10 ** n; return Math.round(x * f) / f }
export const sum = (xs: number[]) => xs.reduce((s, x) => s + x, 0)
export const mean = (xs: number[]) => (xs.length ? sum(xs) / xs.length : 0)
export const std = (xs: number[]) => { const m = mean(xs); return Math.sqrt(mean(xs.map((x) => (x - m) ** 2))) }

/** 비중 합을 1 로 (또는 total 로) 맞춘다. */
export const normalize = (w: Record<string, number>, total = 1) => { const s = sum(Object.values(w)); return Object.fromEntries(Object.entries(w).map(([k, v]) => [k, (v / s) * total])) }

/** 종목당 상한(cap)을 넘는 비중을 나머지 종목에 비례 배분 (반복). */
export function capWeights(w: Record<string, number>, cap: number): Record<string, number> {
  let cur = normalize(w)
  for (let i = 0; i < 20; i++) {
    const over = Object.entries(cur).filter(([, v]) => v > cap + 1e-12)
    if (!over.length) break
    const excess = sum(over.map(([, v]) => v - cap))
    const free = Object.entries(cur).filter(([, v]) => v < cap - 1e-12)
    const freeSum = sum(free.map(([, v]) => v))
    cur = Object.fromEntries(Object.entries(cur).map(([k, v]) => [k, v > cap ? cap : v + (freeSum ? (v / freeSum) * excess : 0)]))
  }
  return cur
}
