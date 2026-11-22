import { describe, expect, it } from "vitest"
import { buildDbUrl, parseDbUrl } from "./dbUrl"
import { costLabel, errorCopy } from "./copy"

describe("팀 DB 접속 주소", () => {
  it("주소를 풀어 서버·포트·이름·계정을 읽는다 (비밀번호는 돌려주지 않는다)", () => {
    const p = parseDbUrl("postgresql://reader:secret-pw@db.example.com:5432/myfinsight?sslmode=require")
    expect(p).toEqual({ host: "db.example.com", port: "5432", name: "myfinsight", user: "reader" })
    expect(JSON.stringify(p)).not.toContain("secret-pw")
  })
  it("포트가 없으면 5432, postgres:// 도 읽고, 앞뒤 공백은 무시한다", () => {
    expect(parseDbUrl("  postgres://alice@10.0.0.7/market \n")).toEqual({ host: "10.0.0.7", port: "5432", name: "market", user: "alice" })
  })
  it("PostgreSQL 주소가 아니면 null", () => {
    for (const v of ["", "db.example.com", "https://db.example.com/x", "postgresql://", "sk-abc"]) expect(parseDbUrl(v), v).toBeNull()
  })
  it("항목별 입력을 주소 한 줄로 합치고, 그 주소를 다시 풀면 같은 값이 나온다 (특수문자 포함)", () => {
    const parts = { host: "db.example.com", port: "6543", name: "my db", user: "team reader", password: "p@ss:w/rd" }
    const url = buildDbUrl(parts)
    expect(url).toBe("postgresql://team%20reader:p%40ss%3Aw%2Frd@db.example.com:6543/my%20db")
    expect(parseDbUrl(url)).toEqual({ host: "db.example.com", port: "6543", name: "my db", user: "team reader" })
    expect(buildDbUrl({ host: " db.example.com ", port: "", name: "myfinsight", user: "", password: "" })).toBe("postgresql://db.example.com:5432/myfinsight")
  })
})

describe("연결 문구", () => {
  it("원인마다 한 줄 + 확인할 것, 모르는 원인은 기본 문구", () => {
    expect(errorCopy({ code: "host_not_found", value: "db.exampel.com", raw: "x" })).toEqual({ title: "서버 주소를 찾지 못했습니다", value: "db.exampel.com", fix: "주소에 오타가 없는지, 인터넷에 연결돼 있는지 확인해 주세요.", raw: "x" })
    expect(errorCopy({ code: "invalid_key", value: null, raw: null }).title).toBe("키가 올바르지 않습니다")
    expect(errorCopy({ code: "새로_생긴_코드" as never, value: null, raw: "boom" })).toEqual({ title: "연결하지 못했습니다", value: null, fix: null, raw: "boom" })
  })
  it("사용료 어림은 유효 숫자 한 자리로", () => {
    expect(costLabel(0.1)).toBe("0.1"); expect(costLabel(0.091)).toBe("0.09"); expect(costLabel(0.046)).toBe("0.05"); expect(costLabel(1.2)).toBe("1")
  })
})
