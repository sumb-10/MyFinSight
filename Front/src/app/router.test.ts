import { describe, expect, it } from "vitest"
import { parseRoute, routePath, type Route } from "./router"

const ROUTES: Route[] = [
  { page: "home" }, { page: "profile" }, { page: "profile", mode: "setup" }, { page: "profile", mode: "edit" },
  { page: "clarify", requestId: "req_1" }, { page: "confirm", requestId: "req_1" }, { page: "run", runId: "run_1" },
  { page: "reports" }, { page: "report", reportId: "run_1" }, { page: "paper" }, { page: "paper", paperId: "paper_20261024_abcd" },
  { page: "comparison", comparisonId: "cmp_run_1" },
]

describe("router", () => {
  it("경로 → 해시 → 경로가 그대로 돌아온다", () => {
    for (const r of ROUTES) expect(parseRoute(routePath(r))).toEqual(r)
  })
  it("빈 해시는 홈, 모르는 주소는 not-found", () => {
    expect(parseRoute("")).toEqual({ page: "home" })
    expect(parseRoute("#/")).toEqual({ page: "home" })
    expect(parseRoute("#/nope/1")).toEqual({ page: "not-found", path: "#/nope/1" })
  })
  it("리포트 주소의 쿼리(sec·company·rb)는 읽고, 다른 화면의 쿼리는 무시한다", () => {
    expect(parseRoute("#/reports/run_1?sec=market")).toEqual({ page: "report", reportId: "run_1", sec: "market" })
    expect(parseRoute("#/reports/run_1?sec=companies&company=NVDA&rb=3")).toEqual({ page: "report", reportId: "run_1", sec: "companies", company: "NVDA", rb: 3 })
    expect(routePath({ page: "report", reportId: "run_1", sec: "companies", company: "NVDA", rb: 3 })).toBe("#/reports/run_1?sec=companies&company=NVDA&rb=3")
    expect(parseRoute("#/reports/run_1?rb=abc")).toEqual({ page: "report", reportId: "run_1" })
    expect(parseRoute("#/paper?x=1")).toEqual({ page: "paper", paperId: undefined })
  })
})
