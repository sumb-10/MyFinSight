import { describe, expect, it } from "vitest"
import type { ReportDoc } from "../api/types"
import { stripStrayBold } from "./reportNormalize"

describe("굵은 글씨 표시 정리 (2026-11-19)", () => {
  it("문단·카드 본문·주의 문장에는 ** 를 남기고, 제목·표·요약 머리말에서는 지운다", () => {
    const doc = {
      header: { title_ko: "**제목**", summary_ko: "요약 **강조**" },
      summary: { verdict: { headline_ko: "**결론**", cautions_plain: [{ key: "k", text: "**주의**" }] }, validation: { info_plain_ko: ["**참고**"] }, next_actions_ko: ["**조건**"] },
      sections: [{ id: "v", title_ko: "x", blocks: [
        { type: "paragraphs", items: ["**문단**"] },
        { type: "cards", title_ko: "**카드 묶음**", items: [{ title_ko: "**카드**", text_ko: "**본문**", meta: [] }] },
        { type: "table", title_ko: "**표**", columns: [], rows: [{ a: "**칸**" }] },
      ] }],
    } as unknown as ReportDoc
    const out = stripStrayBold(doc) as unknown as typeof doc & Record<string, never>
    const s = JSON.stringify(out)
    for (const kept of ["**문단**", "**본문**", "**주의**", "**참고**", "**조건**"]) expect(s).toContain(kept)
    for (const gone of ["**제목**", "**강조**", "**결론**", "**카드 묶음**", "**카드**\"", "**표**", "**칸**"]) expect(s).not.toContain(gone)
    expect(stripStrayBold(out as unknown as ReportDoc)).toBe(out)  // 바꿀 것이 없으면 같은 객체
  })
})

describe("'분석 기준일' → '분석한 날' (2026-11-19)", () => {
  it("화면 글은 쉬운 말로, 화면이 서버 이름으로 찾는 자리(묶음 이름·정해진 제목)는 그대로", async () => {
    const { easyAsOfWord, easyAsOfWords } = await import("./reportNormalize")
    expect(easyAsOfWord("분석 기준일인 2026년 11월 18일의 분석 기준일 구성은 분석 기준일까지 유지")).toBe("분석한 날인 2026년 11월 18일의 분석한 날의 구성은 분석한 날까지 유지")
    const doc = { header: {}, sections: [{ id: "c", title_ko: "x", blocks: [
      { type: "callout", title_ko: "현재 구성 (분석 기준일 2026-11-18)", text_ko: "분석 기준일 비중", group_ko: "분석 기준일의 현재 구성" },
      { type: "paragraphs", items: ["분석 기준일에 고른 종목"] }] }] } as unknown as ReportDoc
    const s = JSON.stringify(easyAsOfWords(doc))
    expect(s).toContain("현재 구성 (분석 기준일 2026-11-18)")
    expect(s).toContain("\"group_ko\":\"분석 기준일의 현재 구성\"")
    expect(s).toContain("분석한 날의 비중")
    expect(s).toContain("분석한 날에 고른 종목")
    const k = easyAsOfWords({ ...doc, kpis: [{ id: "final_value", note_ko: "원화는 둘 다 분석 기준일 환율로 계산" }] } as unknown as ReportDoc)
    expect(k.kpis[0].note_ko).toBe("원화는 둘 다 분석한 날의 환율로 계산")  // 「주요 성과 지표」 보조 문장도
  })
})
