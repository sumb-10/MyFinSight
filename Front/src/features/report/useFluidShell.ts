import { useEffect } from "react"

/** 리포트·모의투자 화면에 있는 동안만 앱 틀의 고정 폭을 푼다 (index.css 의 html.report-fluid). 나가면 되돌려 다른 화면은 그대로다. */
export function useFluidShell() {
  useEffect(() => {
    document.documentElement.classList.add("report-fluid")
    return () => document.documentElement.classList.remove("report-fluid")
  }, [])
}

/** 화면에 있는 동안만 앱 틀의 본문 최대 폭을 넓힌다 (index.css 의 html.report-wide, 1360px). 리포트 상세와 같은 폭. */
export function useWideShell() {
  useEffect(() => {
    document.documentElement.classList.add("report-wide")
    return () => document.documentElement.classList.remove("report-wide")
  }, [])
}
