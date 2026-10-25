import { useCallback, useEffect, useRef, useState } from "react"
import { errorMessage } from "../api/client"

export type Resource<T> = { status: "idle" | "loading" | "ready" | "error"; data: T | null; error: string | null; errorCode?: string; reload: () => void }

/** 비동기 조회 하나. React 19 StrictMode 의 이중 효과에서도 마지막 요청만 반영한다 (요청 ID 비교). */
export function useResource<T>(loader: () => Promise<T>, deps: unknown[]): Resource<T> {
  const [state, setState] = useState<Omit<Resource<T>, "reload">>({ status: "loading", data: null, error: null })
  const seq = useRef(0)
  const run = useCallback(() => {
    const my = ++seq.current
    setState((s) => ({ ...s, status: "loading", error: null }))
    loader().then(
      (data) => { if (my === seq.current) setState({ status: "ready", data, error: null }) },
      (e) => { if (my === seq.current) setState((s) => ({ status: "error", data: s.data, error: errorMessage(e), errorCode: (e as { code?: string }).code })) },
    )
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, deps)
  useEffect(() => { run() }, [run])
  return { ...state, reload: run }
}
