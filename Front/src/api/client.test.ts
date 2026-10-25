import { describe, expect, it } from "vitest"
import { ApiError, errorMessage } from "./client"

describe("client errors", () => {
  it("서버 오류 봉투의 한국어 메시지를 그대로 보여 준다", () => {
    const e = new ApiError("PROFILE_INVALID", "프로필 값에 오류가 있습니다", 422, { "constraints.max_weight_per_sector": "섹터당 상한은 종목당 상한 이상이어야 합니다" })
    expect(errorMessage(e)).toContain("프로필 값에 오류가 있습니다")
    expect(e.status).toBe(422)
  })
  it("모르는 오류도 문장이 된다", () => {
    expect(typeof errorMessage(new Error("boom"))).toBe("string")
    expect(errorMessage("x").length).toBeGreaterThan(0)
  })
})
