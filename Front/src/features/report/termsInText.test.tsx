import { describe, expect, it } from "vitest"
import type { ReportDoc } from "../../api/types"
import { glossaryOf, termsInText } from "./terms"

const doc = { sections: [{ id: "references", title_ko: "자료", blocks: [{ type: "glossary", items: [{ term: "CAGR", explain_ko: "리포트의 CAGR 풀이" }, { term: "MDD", explain_ko: "리포트의 MDD 풀이" }] }] }] } as unknown as ReportDoc

describe("본문에 나온 용어", () => {
  const items = glossaryOf(doc)
  const names = (texts: string[]) => termsInText(items, texts).map((t) => t.term)
  it("본문에 실제로 나온 용어만, 처음 나온 순서대로 한 번씩 (별칭은 한 묶음, 리포트 풀이 우선)", () => {
    const got = termsInText(items, ["최대낙폭은 23.2%였고 연평균 수익률(CAGR) 23.8%, 샤프 비율 0.59였습니다.", "MDD 와 CAGR 을 다시 말하고 Sharpe 도 다시 나옵니다. 연변동성은 33%입니다."])
    expect(got.map((t) => t.term)).toEqual(["MDD", "CAGR", "Sharpe", "연변동성"])  // 최대낙폭 = MDD, 샤프 비율 = Sharpe
    expect(got[0].explain_ko).toBe("리포트의 MDD 풀이")  // 상단 「투자 용어 설명」과 같은 설명
  })
  it("조사가 붙은 표현은 잡고, 다른 단어의 일부인 짧은 영문 약어·한글 용어는 잡지 않는다", () => {
    expect(names(["ABLE 과 TABLE, BLOCK 은 용어가 아닙니다."])).toEqual([])  // BL(Black-Litterman)
    expect(names(["연변동성은 높았습니다."])).toEqual(["연변동성"])  // 「변동성」은 따로 잡지 않는다
    expect(names(["리밸런싱을 매월 했습니다."])).toEqual(["리밸런싱"])
  })
  it("7. 분석의 전제 용어: 긴 용어 안에서만 나온 짧은 용어는 긴 용어 하나로 (2026-11-16)", () => {
    expect(names(["정적 최소분산과 워크포워드 최소분산을 비교했습니다."])).toEqual(["정적 최소분산", "워크포워드 최소분산"])  // 「워크포워드」 따로 없음
    expect(names(["워크포워드 방식으로 다시 계산했습니다."])).toEqual(["walk-forward"])
    expect(names(["사후 선택 효과가 있고, 호가 차이는 반영하지 않았습니다."])).toEqual(["사후 선택 효과", "호가 차이"])
    expect(names(["최소분산 (walk-forward) 의 결과"])).toEqual(["walk-forward"])  // 괄호 이름표는 방식 이름으로만, 「최소분산」을 정적이라 하지 않는다
  })
  it("근거 표시 [calc:cagr:…] 안의 글자는 용어로 보지 않고, 용어가 없으면 빈 목록", () => {
    expect(names(["결과는 좋았습니다 [calc:cagr:min_variance] [ev12]."])).toEqual([])
  })
})
