import { createContext, useCallback, useContext, useEffect, useMemo, useState } from "react"
import type { AnalysisService } from "../api/service"
import type { Health, ProfileView } from "../api/types"
import { errorMessage } from "../api/client"

interface ProfileCtx { profile: ProfileView | null; status: "loading" | "ready" | "error"; error: string | null; reload: () => Promise<void>; set: (p: ProfileView) => void }

export const ServiceContext = createContext<AnalysisService | null>(null)  // 테스트에서 가짜 서비스를 꽂을 때 쓴다
const ProfileContext = createContext<ProfileCtx | null>(null)
const HealthContext = createContext<{ health: Health | null; reachable: boolean; error: string | null }>({ health: null, reachable: true, error: null })

export function useService(): AnalysisService {
  const s = useContext(ServiceContext)
  if (!s) throw new Error("ServiceProvider missing")
  return s
}
export function useProfile(): ProfileCtx {
  const p = useContext(ProfileContext)
  if (!p) throw new Error("ProfileProvider missing")
  return p
}
export const useHealth = () => useContext(HealthContext)

export function Providers({ service, children }: { service: AnalysisService; children: React.ReactNode }) {
  const [profile, setProfile] = useState<ProfileView | null>(null)
  const [status, setStatus] = useState<"loading" | "ready" | "error">("loading")
  const [error, setError] = useState<string | null>(null)
  const reload = useCallback(async () => {
    setStatus("loading")
    try {
      setProfile(await service.getProfile())
      setStatus("ready")
      setError(null)
    } catch (e) {
      setStatus("error")
      setError(errorMessage(e))
    }
  }, [service])
  useEffect(() => { void reload() }, [reload])
  useEffect(() => {  // 서버가 꺼져 있다가 살아나면 다시 읽는다 (프로필 "없음" 과 "서버 연결 실패" 를 구분, 라운드 5)
    const onFocus = () => { if (status === "error") void reload() }
    window.addEventListener("focus", onFocus)
    document.addEventListener("visibilitychange", onFocus)
    return () => { window.removeEventListener("focus", onFocus); document.removeEventListener("visibilitychange", onFocus) }
  }, [status, reload])

  const [health, setHealth] = useState<Health | null>(null)
  const [reachable, setReachable] = useState(true)
  const [herr, setHerr] = useState<string | null>(null)
  useEffect(() => {
    let alive = true
    const tick = async () => {
      try {
        const h = await service.health()
        if (alive) { setHealth(h); setReachable(true); setHerr(null) }
      } catch (e) {
        if (alive) { setReachable(false); setHerr(errorMessage(e)) }
      }
    }
    void tick()
    const t = window.setInterval(tick, 15_000)
    return () => { alive = false; window.clearInterval(t) }
  }, [service])

  const profileCtx = useMemo<ProfileCtx>(() => ({ profile, status, error, reload, set: setProfile }), [profile, status, error, reload])
  const healthCtx = useMemo(() => ({ health, reachable, error: herr }), [health, reachable, herr])
  return (
    <ServiceContext.Provider value={service}>
      <HealthContext.Provider value={healthCtx}>
        <ProfileContext.Provider value={profileCtx}>{children}</ProfileContext.Provider>
      </HealthContext.Provider>
    </ServiceContext.Provider>
  )
}
