import { useEffect, useState } from "react"
import { saveUi } from "../state/uiStorage"

export type Route =
  | { page: "home" }
  | { page: "profile"; mode?: "setup" | "edit" }
  | { page: "clarify"; requestId: string }
  | { page: "confirm"; requestId: string }
  | { page: "run"; runId: string }
  | { page: "reports" }
  | { page: "report"; reportId: string; sec?: string; company?: string; rb?: number }
  | { page: "paper"; paperId?: string }
  | { page: "comparison"; comparisonId: string }
  | { page: "not-found"; path: string }

export const routePath = (r: Route): string => {
  switch (r.page) {
    case "home": return "#/home"
    case "profile": return r.mode === "setup" ? "#/profile/setup" : r.mode === "edit" ? "#/profile/edit" : "#/profile"
    case "clarify": return `#/analysis/${r.requestId}`
    case "confirm": return `#/analysis/${r.requestId}/confirm`
    case "run": return `#/runs/${r.runId}`
    case "reports": return "#/reports"
    case "report": {
      const q = new URLSearchParams()
      if (r.sec) q.set("sec", r.sec)
      if (r.company) q.set("company", r.company)
      if (r.rb !== undefined) q.set("rb", String(r.rb))
      const qs = q.toString()
      return `#/reports/${r.reportId}${qs ? `?${qs}` : ""}`
    }
    case "paper": return r.paperId ? `#/paper/${r.paperId}` : "#/paper"
    case "comparison": return `#/comparisons/${r.comparisonId}`
    case "not-found": return r.path
  }
}

export const parseRoute = (hash: string = window.location.hash): Route => {
  const path = hash.replace(/^#/, "") || "/home"
  const [pathname, query = ""] = path.split("?")
  const parts = pathname.split("/").filter(Boolean)
  const [a, b, c] = parts
  if (!a || a === "home") return { page: "home" }
  if (a === "profile") return { page: "profile", mode: b === "setup" ? "setup" : b === "edit" ? "edit" : undefined }
  if (a === "analysis" && b && c === "confirm") return { page: "confirm", requestId: b }
  if (a === "analysis" && b) return { page: "clarify", requestId: b }
  if (a === "runs" && b) return { page: "run", runId: b }
  if (a === "reports" && b) {  // 리포트 화면은 섹션·기업·리밸런싱 시점을 주소에 남긴다 (?sec=&company=&rb=)
    const q = new URLSearchParams(query)
    const r: Route = { page: "report", reportId: b }
    const sec = q.get("sec"), company = q.get("company"), rb = q.get("rb")
    if (sec) r.sec = sec
    if (company) r.company = company
    if (rb !== null && rb !== "" && Number.isFinite(Number(rb))) r.rb = Number(rb)
    return r
  }
  if (a === "reports") return { page: "reports" }
  if (a === "paper") return { page: "paper", paperId: b || undefined }
  if (a === "comparisons" && b) return { page: "comparison", comparisonId: b }
  return { page: "not-found", path: hash }
}

/** 화면 이동. 같은 리포트 안에서 시점·기업만 바꾸는 이동은 `scroll: false` 로 맨 위로 튀지 않게 한다 (라운드 5). */
export function navigate(r: Route, opts: { scroll?: boolean } = {}) {
  const path = routePath(r)
  if (window.location.hash !== path) window.location.hash = path
  saveUi({ lastRoute: path })
  if (opts.scroll !== false) window.scrollTo({ top: 0 })
}

export function useHashRoute(): Route {
  const [route, setRoute] = useState<Route>(() => parseRoute())
  useEffect(() => {
    const onHash = () => setRoute(parseRoute())
    window.addEventListener("hashchange", onHash)
    return () => window.removeEventListener("hashchange", onHash)
  }, [])
  return route
}
