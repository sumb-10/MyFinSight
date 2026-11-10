import { useEffect, useState } from "react"
import { errorMessage } from "../../api/client"
import type { AnalysisService } from "../../api/service"
import type { ProposedSectorScope, ProposedSectorTrendsData } from "../../api/proposed"
import { isMockMode } from "../../mocks/mode"

// 홈 '요즘엔 뭐가 좋아요?' 자료. 서버는 새 거래일마다 한 번 계산해 저장해 두고, 이 브라우저는 마지막으로 받은 자료를 저장소에 둔다.
// 저장해 둔 자료가 있으면 바로 보여 주고 뒤에서 새 자료를 받는다. 처음(저장한 자료가 없을 때)만 시작 화면(SplashScreen)에 진행률을 띄운다.

export const POLL_MS = 400
export const SPLASH_MAX_MS = 20_000  // 이보다 오래 걸리면 시작 화면을 걷고 상자 안에서 기다린다
export const SPLASH_DONE_MS = 300    // 100% 를 잠깐 보여 준 뒤 걷는다

const KEY = () => (isMockMode() ? "myfinsight.mock.sectorTrends.v1" : "myfinsight.sectorTrends.v1")

export function readCachedTrends(): ProposedSectorTrendsData | null {
  try {
    const raw = window.localStorage.getItem(KEY())
    const v = raw ? (JSON.parse(raw) as ProposedSectorTrendsData) : null
    return v && Array.isArray(v.markets) && v.picks ? v : null
  } catch { return null }
}

function writeCachedTrends(d: ProposedSectorTrendsData) {
  try { window.localStorage.setItem(KEY(), JSON.stringify(d)) } catch { /* 저장소를 못 쓰면 이번 화면에서만 */ }
}

/** 내 투자 대상 → 추천 섹터를 고를 시장 범위 */
export function scopeOf(universe: readonly string[]): ProposedSectorScope {
  const us = universe.some((u) => u === "SP500" || u === "NASDAQ100"), kr = universe.includes("KOSPI200")
  return us && kr ? "ALL" : kr ? "KR" : "US"
}

export interface SectorTrendsState {
  supported: boolean                         // 서비스에 섹터 성과 기능이 있는가 (없으면 상자를 그리지 않는다)
  data: ProposedSectorTrendsData | null      // 보여 줄 자료 (새 자료를 받는 동안에는 저장해 둔 자료)
  status: "loading" | "ready" | "error"
  progress: number                           // 0~1 (서버 계산 진행률)
  error: string | null
  splash: boolean                            // 시작 화면을 띄울지
  retry: () => void
}

export function useSectorTrends(svc: AnalysisService): SectorTrendsState {
  const supported = typeof svc.getSectorTrends === "function"
  const [data, setData] = useState<ProposedSectorTrendsData | null>(() => (supported ? readCachedTrends() : null))
  const [status, setStatus] = useState<SectorTrendsState["status"]>("loading")
  const [progress, setProgress] = useState(0)
  const [error, setError] = useState<string | null>(null)
  const [splash, setSplash] = useState(() => supported && readCachedTrends() === null)
  const [attempt, setAttempt] = useState(0)

  useEffect(() => {
    if (typeof svc.getSectorTrends !== "function") return
    let alive = true
    let timer = 0
    let waited = false  // 서버가 한 번이라도 계산 중이라고 했는가 (아니면 시작 화면을 100% 로 붙잡지 않고 바로 걷는다)
    const started = Date.now()
    const tick = async () => {
      try {
        const r = await svc.getSectorTrends!()
        if (!alive) return
        if (r.status === "ready" && r.data) {
          setData(r.data); writeCachedTrends(r.data); setProgress(1); setStatus("ready")
          if (waited) timer = window.setTimeout(() => { if (alive) setSplash(false) }, SPLASH_DONE_MS)
          else setSplash(false)
          return
        }
        waited = true
        if (r.status === "error") { if (r.data) setData((d) => d ?? r.data); setStatus("error"); setError(r.error ?? "섹터 자료를 불러오지 못했습니다."); setSplash(false); return }
        setProgress(r.progress)
        if (r.data) { setData((d) => d ?? r.data); setSplash(false) }  // 서버가 지난 자료를 함께 주면 그것부터 보여 준다
        if (Date.now() - started > SPLASH_MAX_MS) setSplash(false)
        timer = window.setTimeout(tick, POLL_MS)
      } catch (e) {
        if (!alive) return
        setStatus("error"); setError(errorMessage(e)); setSplash(false)
      }
    }
    setStatus("loading"); setError(null)
    void tick()
    return () => { alive = false; window.clearTimeout(timer) }
  }, [svc, attempt])

  return { supported, data, status, progress, error, splash, retry: () => setAttempt((a) => a + 1) }
}
