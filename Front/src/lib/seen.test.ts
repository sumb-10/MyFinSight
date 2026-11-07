import { afterEach, describe, expect, it } from "vitest"
import { initPapers, initReports, loadSeen, markRebalanceSeen, markReportSeen, SEEN_KEYS } from "./seen"

afterEach(() => { window.localStorage.clear(); window.sessionStorage.clear() })

describe("확인 기록 (이 브라우저에만)", () => {
  it("처음에는 지금 있는 리포트를 모두 본 것으로 두고, 그 뒤에 생긴 리포트만 새 리포트다", () => {
    initReports("api", ["r1", "r2"])
    expect(loadSeen("api").reports).toEqual(["r1", "r2"])
    initReports("api", ["r1", "r2", "r3"])  // 두 번째부터는 덮어쓰지 않는다 → r3 은 새 리포트로 남는다
    expect(loadSeen("api").reports).toEqual(["r1", "r2"])
    markReportSeen("api", "r3")
    expect(loadSeen("api").reports).toEqual(["r1", "r2", "r3"])
  })
  it("모의투자는 처음 볼 때의 리밸런싱 번호를 확인한 것으로 두고, 확인 번호는 줄지 않는다", () => {
    initPapers("api", [{ paper_id: "p1", n_rebalances: 3 }])
    expect(loadSeen("api").papers).toEqual({ p1: 3 })
    initPapers("api", [{ paper_id: "p1", n_rebalances: 5 }, { paper_id: "p2", n_rebalances: 0 }])
    expect(loadSeen("api").papers).toEqual({ p1: 3, p2: 0 })
    markRebalanceSeen("api", "p1", 5); markRebalanceSeen("api", "p1", 4)
    expect(loadSeen("api").papers.p1).toBe(5)
  })
  it("일반 모드는 localStorage, 목업은 sessionStorage 에 따로 두고, 목업만 시연용 시작값(seed)을 쓴다", () => {
    initReports("mock", ["m1", "m2"], { unseenReports: ["m2"], papers: {} })
    initPapers("mock", [{ paper_id: "a1", n_rebalances: 4 }], { unseenReports: [], papers: { a1: 3 } })
    expect(loadSeen("mock")).toMatchObject({ reports: ["m1"], papers: { a1: 3 } })
    expect(window.sessionStorage.getItem(SEEN_KEYS.mock)).not.toBeNull()
    expect(window.localStorage.getItem(SEEN_KEYS.api)).toBeNull()
    expect(loadSeen("api")).toEqual({ v: 1, reports: null, papers: {} })
  })
  it("깨진 기록은 처음 상태로 읽는다", () => {
    window.localStorage.setItem(SEEN_KEYS.api, "{broken")
    expect(loadSeen("api")).toEqual({ v: 1, reports: null, papers: {} })
  })
})
