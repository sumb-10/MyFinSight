import { describe, expect, it } from "vitest"
import type { ReportDoc } from "../../api/types"
import { buildFlowSteps } from "./buildFlow"

const item = (t: string, now: boolean, bt: boolean, forced = false) => ({ ticker: t, name: t, theme_reason_ko: forced ? "필수 포함 종목 · 테마" : "테마", in_selection_now: now, in_backtest: bt })
const doc = (o: { metric?: string; direction?: string; metric_ko?: string; items?: object[]; base?: string; cols?: { id: string; kind: string }[]; ne?: object | null; status?: string; chosen?: [string, string] }) => {
  const [cid, clabel] = o.chosen ?? ["min_variance", "최소분산"]
  const cols = o.cols ?? [{ id: "market_cap", kind: "template" }, { id: "min_variance", kind: "template" }, { id: "bl_01", kind: "black_litterman" }]
  return {
    header: { chosen_portfolio_id: cid, chosen_label_ko: clabel },
    summary: { verdict: { status: o.status ?? "recommended", chosen_portfolio_id: cid, chosen_label_ko: clabel }, news_effect: o.ne === undefined ? { disabled: false } : o.ne },
    sections: [
      { id: "companies", blocks: [{ type: "companies", metric: o.metric ?? "return_12m_1m", metric_ko: o.metric_ko ?? "모멘텀", direction: o.direction ?? "desc", items: o.items ?? [item("A", true, true), item("B", true, true)] }] },
      { id: "construction", blocks: [{ type: "weights_compare", baseline_id: o.base ?? "market_cap", columns: cols.map((c) => ({ ...c, label_ko: c.id, rule_ko: "" })), rows: [], cash: {}, ex_ante: {} }] },
    ],
  } as unknown as ReportDoc
}
const d = (x: ReportDoc) => buildFlowSteps(x).map((s) => `${s.t}|${s.d}`)

describe("비중이 정해진 과정 (2026-11-16)", () => {
  it("미국 AI 모양: 같은 종목 수 · 필수 포함 따로 · 모멘텀 순위 기준 · 시가총액 기준 · 뉴스 구성 하나 · 선택 전략 이름", () => {
    const s = d(doc({ items: [item("GOOGL", true, true, true), item("NVDA", true, true, true), item("DELL", true, false), item("ECHO", false, true)] }))
    expect(s[0]).toBe("투자 종목 선정|분석 기준일과 백테스트 시작일에 각각 3종목을 담았습니다. 필수 포함 2종목과 주가 상승률 순으로 고른 1종목입니다.")
    expect(s[1]).toBe("기준 투자 비중 계산|시가총액이 큰 기업에 더 많은 투자금을 배정했습니다.")
    expect(s[2]).toBe("뉴스·공시 반영|기준 비중에 뉴스와 공시를 반영해 별도 구성을 만들었습니다.")
    expect(s[3]).toBe("최종 비중 결정|과거 성과를 비교한 뒤, 최소분산 방식으로 최종 비중을 정했습니다.")
  })
  it("예전 리포트는 「지켜야 하는 조건」 표의 필수 포함 행으로 필수 포함을 찾는다", () => {
    const x = doc({ items: [item("NVDA", true, true), item("AVGO", true, true), item("TXN", true, true)] })
    ;(x.sections as unknown as { id: string; blocks: object[] }[]).push({ id: "market", blocks: [{ type: "table", title_ko: "지켜야 하는 조건 (하드 제약)", columns: [], rows: [{ k: "필수 포함", v: "NVDA" }] }] })
    expect(d(x)[0]).toContain("필수 포함 1종목과 주가 상승률 순으로 고른 2종목입니다.")
  })
  it("종목 수가 다르면 날짜마다 따로", () => {
    expect(d(doc({ items: [item("A", true, true), item("B", true, false), item("C", true, false)] }))[0]).toBe("투자 종목 선정|분석 기준일에는 3종목(주가 상승률 순 3종목), 백테스트 시작일에는 1종목(주가 상승률 순 1종목)을 담았습니다.")
    // 필수 포함 수가 날짜마다 다르면 날짜별로
    expect(d(doc({ items: [item("G", true, true, true), item("N", true, false, true), item("D", true, true)] }))[0]).toBe("투자 종목 선정|분석 기준일에는 3종목(필수 포함 2종목, 주가 상승률 순 1종목), 백테스트 시작일에는 2종목(필수 포함 1종목, 주가 상승률 순 1종목)을 담았습니다.")
    // 필수 포함이 없을 때 · 모두 필수 포함일 때
    expect(d(doc({ items: [item("A", true, true), item("B", true, true)] }))[0]).toBe("투자 종목 선정|분석 기준일과 백테스트 시작일에 각각 2종목을 담았습니다. 모두 주가 상승률 순으로 골랐습니다.")
    expect(d(doc({ items: [item("A", true, true, true), item("B", true, true, true)] }))[0]).toBe("투자 종목 선정|분석 기준일과 백테스트 시작일에 각각 2종목을 담았습니다. 모두 필수 포함 종목입니다.")
  })
  it("다른 지표는 그 지표와 순위 방향으로", () => {
    expect(d(doc({ metric: "dividend_yield_ttm", metric_ko: "고배당" }))[0]).toContain("모두 배당수익률이 높은 순으로 골랐습니다.")
    expect(d(doc({ metric: "pe_ttm", metric_ko: "저PER", direction: "asc" }))[0]).toContain("모두 PER이 낮은 순으로 골랐습니다.")
  })
  it("다른 기준 전략: 동일비중은 이 카드 문장, 그 밖은 strategyInfo 짧은 설명", () => {
    expect(d(doc({ base: "equal_weight", cols: [{ id: "equal_weight", kind: "template" }] }))[1]).toBe("기준 투자 비중 계산|선정한 종목에 투자금을 같은 비율로 나눴습니다.")
    expect(d(doc({ base: "inverse_volatility", cols: [{ id: "inverse_volatility", kind: "template" }] }))[1]).toBe("기준 투자 비중 계산|주가가 덜 흔들린 종목에 더 많이 투자했습니다.")
  })
  it("뉴스 반영 구성이 여러 개 · 뉴스를 끈 리포트는 기존 사유 · 자료가 없으면 단계 없음", () => {
    expect(d(doc({ cols: [{ id: "market_cap", kind: "template" }, { id: "bl_01", kind: "black_litterman" }, { id: "bl_02", kind: "black_litterman" }] }))[2]).toContain("2개의 별도 구성을 만들었습니다")
    const off = buildFlowSteps(doc({ cols: [{ id: "market_cap", kind: "template" }], ne: { disabled: true, reason_ko: "뉴스 반영을 끈 분석입니다 (투자조건 설정)" } }))
    expect(off[2]).toEqual({ t: "뉴스·공시 반영 안 함", d: "뉴스 반영을 끈 분석입니다 (투자조건 설정)", off: true })
    expect(buildFlowSteps(doc({ cols: [{ id: "market_cap", kind: "template" }], ne: null })).map((s) => s.t)).toEqual(["투자 종목 선정", "기준 투자 비중 계산", "최종 비중 결정"])
  })
  it("뉴스 반영 구성이 최종 선택돼도 자연스럽게 · 추천이 없으면 판단 결과대로", () => {
    expect(d(doc({ chosen: ["bl_04", "뉴스 뷰: AI 수요"] }))[3]).toBe("최종 비중 결정|과거 성과를 비교한 뒤, 뉴스 뷰: AI 수요 구성으로 최종 비중을 정했습니다.")
    expect(d(doc({ status: "none_baseline", chosen: ["equal_weight", "동일비중"] }))[3]).toBe("최종 비중 결정|조건을 충족한 추천 구성이 없어, 기준 구성인 동일비중 방식의 비중을 보여 줍니다.")
    expect(d(doc({ status: "none_cash_blend", chosen: ["cash_blend_30", "현금 혼합안 (현금 30%)"] }))[3]).toContain("현금을 섞은 현금 혼합안 (현금 30%) 구성의 비중")
    expect(d(doc({ chosen: ["dd_match_market_cap", "낙폭 맞춤안 (주식 55% + 현금 45%, 시가총액비중 기준)"] }))[3]).toContain("낙폭 맞춤안 (주식 55% + 현금 45%, 시가총액비중 기준) 구성으로 최종 비중을 정했습니다")
  })
})
