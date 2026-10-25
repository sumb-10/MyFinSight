import { useEffect, useRef, useState } from "react"
import { errorMessage } from "../api/client"

/** 주기 폴링. 탭이 숨겨지면 멈추고, until(data) 가 true 가 되면 끝난다. 네트워크 실패는 마지막 값을 유지하며 횟수만 센다. */
export function usePolling<T>(loader: () => Promise<T>, opts: { intervalMs: number; until: (d: T) => boolean; enabled?: boolean }, deps: unknown[]) {
  const [data, setData] = useState<T | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [failures, setFailures] = useState(0)
  const [done, setDone] = useState(false)
  const alive = useRef(true)
  useEffect(() => {
    alive.current = true
    setDone(false)
    let timer: number | undefined
    const tick = async () => {
      if (!alive.current || opts.enabled === false) return
      if (document.hidden) { timer = window.setTimeout(tick, opts.intervalMs); return }
      try {
        const d = await loader()
        if (!alive.current) return
        setData(d); setError(null); setFailures(0)
        if (opts.until(d)) { setDone(true); return }
      } catch (e) {
        if (!alive.current) return
        setFailures((n) => n + 1); setError(errorMessage(e))
        if ((e as { status?: number }).status === 404) { setDone(true); return }
      }
      timer = window.setTimeout(tick, opts.intervalMs)
    }
    tick()
    return () => { alive.current = false; if (timer) window.clearTimeout(timer) }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, deps)
  return { data, error, failures, done }
}
