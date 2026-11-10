import { describe, expect, it } from "vitest"
import type { ReportSummary } from "../../api/types"
import { conditionCounts, conditionItems, conditionSentence, stripInternalCodes, topic } from "./summaryText"
import { indexReturn } from "./Dashboard"
import { groupOf, groupsFor } from "./navGroups"

type V = ReportSummary["validation"]
const v = (rules: [string, string, string][], extra: Partial<V> = {}): V => ({
  n_pass: 0, n_warn: 0, n_fail: 0, chosen_status: "pass", failed_rules_ko: [], warned_rules_ko: [],
  rules_ko: rules.map(([rule, name_ko, status]) => ({ rule, name_ko, status, level: "soft", message_ko: "" })), ...extra,
})

describe("조건 결과 한 문장", () => {
  it("충족과 주의를 한 문장으로 합친다", () => {
    expect(conditionSentence(v([["R1", "최대낙폭", "pass"], ["R2", "목표수익", "pass"], ["R7", "변동성 적합", "warn"]])))
      .toBe("낙폭·목표 수익 조건은 지켰고, 변동성은 기준보다 높았습니다.")
  })
  it("모두 충족 / 모두 주의 / 판정 없음", () => {
    expect(conditionSentence(v([["R1", "최대낙폭", "pass"]]))).toBe("낙폭 조건을 모두 지켰습니다.")
    expect(conditionSentence(v([["R3", "비교지수 대비", "warn"]]))).toBe("비교지수 대비 성과는 비교지수보다 낮았습니다.")
    expect(conditionSentence(v([["R9", "참고 검사", "info"]]))).toBeNull()
  })
  it("이름만 온 미충족 규칙도 체크리스트에 넣는다", () => {
    const items = conditionItems(v([["R1", "최대낙폭", "pass"]], { failed_rules_ko: ["새 규칙"] }))
    expect(items.map((x) => [x.name, x.status])).toEqual([["최대낙폭", "pass"], ["새 규칙", "fail"]])
    expect(conditionCounts(items)).toEqual({ pass: 1, issue: 1 })
  })
  it("은/는 받침 처리", () => { expect(topic("낙폭")).toBe("낙폭은"); expect(topic("변동성")).toBe("변동성은"); expect(topic("목표 수익")).toBe("목표 수익은"); expect(topic("비교지수")).toBe("비교지수는") })
})

describe("표기 도우미", () => {
  it("내부 구성 번호 BL n 을 지운다", () => { expect(stripInternalCodes("분석 기준일 구성 (현재 구성 BL 1: 실적 전망)")).toBe("분석 기준일 구성 (현재 구성: 실적 전망)") })
  it("지수 끝값을 누적 수익률로", () => { expect(indexReturn(266)).toBe("+166.0%"); expect(indexReturn(92.5)).toBe("−7.5%"); expect(indexReturn(undefined)).toBe("—") })
})

describe("상단 탭 묶음", () => {
  it("섹션을 5개 묶음으로, 모르는 섹션은 뒤에 따로", () => {
    const doc = { summary: {}, nav: [{ id: "x_new", title_ko: "새 섹션" }], sections: ["verdict", "construction", "companies", "market", "performance", "assumptions", "references", "x_new"].map((id) => ({ id, title_ko: id, blocks: [] })) }
    expect(groupsFor(doc as never).map((g) => g.label)).toEqual(["개요", "종목 선정", "과거 성과", "시장·뉴스", "요청·주의·자료", "새 섹션"])
    expect(groupOf("companies")).toBe("selection")
    expect(groupOf("history")).toBe("notes")
  })
})
