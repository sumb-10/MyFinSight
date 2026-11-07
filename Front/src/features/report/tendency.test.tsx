import { beforeAll, describe, expect, it } from "vitest"
import { render, screen, within } from "@testing-library/react"
import type { ReportDoc, ReportSummary } from "../../api/types"
import { ko } from "../../lib/format"
import { prefTerms, RISK_TOLERANCE_RANGE, tendencyLabel } from "../../lib/tendency"
import { TENDENCIES, toRiskTolerance } from "../profile/diagnosis"
import { ConditionRules, keyAlerts } from "./Dashboard"
import { analysisRisk, parseVolCheck } from "./wording"

// 투자성향 이름 통일과 변동성(R7) 표시. 계산·판정은 서버 값 그대로이고, 여기서는 이름과 문장 구성만 확인한다.

beforeAll(() => { globalThis.ResizeObserver ??= class { observe() {} unobserve() {} disconnect() {} } as unknown as typeof ResizeObserver })

/** 리포트 문서: 「요청 내용」의 투자성향 코드와 「성향 해석」의 변동성 선호만 둔다 (분석 당시 저장된 값). */
const rdoc = (code: string | null, pref: string | null, short = false) => ({
  sections: [{ id: "market", title_ko: "산업과 시장 분석", blocks: [
    ...(code ? [{ type: "table", title_ko: "요청 내용", columns: [{ key: "k", label_ko: "항목" }, { key: "v", label_ko: "값" }], rows: [{ k: "투자성향", v: `${code} · 손실 감내 수준 30.0% · 손실 시 hold` }] }] : []),
    ...(pref ? [{ type: "table", title_ko: "성향 해석 (소프트 조건)", columns: [{ key: "k", label_ko: "항목" }, { key: "v", label_ko: "값" }], rows: [{ k: "변동성 선호", v: pref }] }] : []),
  ] }],
  header: { backtest_period: { start: "2025-10-30", end: "2026-10-30", as_of: "2025-10-30" } },
  summary: { period: { start: "2025-10-30", end: "2026-10-30", annualized_reliable: !short } },
  datasets: { dates: [], series: {} }, kpis: [], parameters: {},
}) as unknown as ReportDoc
const val = (over: Partial<ReportSummary["validation"]>): ReportSummary["validation"] => ({ n_pass: 1, n_warn: 0, n_fail: 0, n_candidates: 4, chosen_status: "pass", failed_rules_ko: [], ...over })
const r7 = (status: string, message_ko: string) => ({ rule: "R7", name_ko: "변동성 적합", level: "soft", status, message_ko })
const box = () => screen.getByText("변동성 적합").closest("li")!

describe("투자성향 이름", () => {
  it("다섯 가지 이름이 기준이고, 세 단계 코드는 그 범위로만 쓴다 (임의로 하나를 고르지 않는다)", () => {
    expect(TENDENCIES).toEqual(["안정형", "안정추구형", "위험중립형", "적극투자형", "공격투자형"])
    for (const t of TENDENCIES) expect(RISK_TOLERANCE_RANGE[toRiskTolerance(t)]).toContain(t)  // 다섯 가지 → 세 단계 → 범위 안에 원래 이름이 있다
    expect(ko("conservative")).toBe("안정형·안정추구형"); expect(ko("moderate")).toBe("위험중립형"); expect(ko("aggressive")).toBe("적극투자형·공격투자형")
  })
  it("최종 선택 성향 > 자동 진단 > 세 단계 범위 > 성향 미확인", () => {
    expect(tendencyLabel({ final: "공격투자형", computed: "위험중립형", code: "aggressive" })).toBe("공격투자형")
    expect(tendencyLabel({ computed: "안정추구형", code: "conservative" })).toBe("안정추구형")
    expect(tendencyLabel({ code: "conservative" })).toBe("안정형·안정추구형")
    expect(tendencyLabel({})).toBe("성향 미확인")
  })
  it("서버 문장의 「안정/중립/적극 성향」은 성향이 아니라 변동성 기준 이름으로 바꾼다", () => {
    expect(prefTerms("연변동성 29.8% vs 비교지수 15.0%의 1배(안정 성향) = 15.0%")).toBe("연변동성 29.8% vs 비교지수 15.0%의 1배(낮은 변동성 기준) = 15.0%")
    expect(prefTerms("손실 시 매도 성향 ×0.8")).toBe("손실 시 매도 성향 ×0.8")
  })
  it("리포트의 성향은 그 리포트에 저장된 값에서만 읽고, 세부 성향이 없으면 범위로 둔다", () => {
    expect(analysisRisk(rdoc("moderate", "low"))).toEqual({ code: "moderate", tendency: "위험중립형", pref: "low", prefDiffers: true })
    expect(analysisRisk(rdoc("conservative", "low"))).toMatchObject({ tendency: "안정형·안정추구형", prefDiffers: false })
    expect(analysisRisk(rdoc(null, null))).toEqual({ code: null, tendency: null, pref: null, prefDiffers: false })
  })
})

describe("변동성 적합 표시", () => {
  it("서버 R7 문장 세 가지 틀을 읽고, 모르는 문장은 null", () => {
    expect(parseVolCheck("연변동성 45.5% vs 비교지수 12.8%의 1.3배(중립 성향) = 16.6% (창이 짧아 참고만)")).toEqual({ kind: "bench", vol: "45.5%", bench: "12.8%", mult: "1.3", band: "16.6%", pref: "medium", short: true })
    expect(parseVolCheck("연변동성 20.0% vs 안정 성향 상한 15.0%")).toMatchObject({ kind: "absolute", band: "15.0%", bench: null, mult: null, pref: "low" })
    expect(parseVolCheck("연변동성 20.3% (비교지수 15.2%) — 적극 성향은 변동성 상한을 두지 않습니다")).toMatchObject({ kind: "nocap", band: null, bench: "15.2%", pref: "high" })
    expect(parseVolCheck("다른 문장")).toBeNull()
  })
  it("짧은 기간(참고): 결과 → 수치 → 기준 → 기간 안내, 기준 초과는 관측으로만 쓰고 「미충족」으로 바꾸지 않는다", () => {
    render(<ConditionRules v={val({ info_notes_ko: ["연변동성 45.5% vs 비교지수 12.8%의 1.3배(중립 성향) = 16.6% (창이 짧아 참고만)", "비교지수보다 낙폭이 큼 (29.9% vs 8.9%)"] })} doc={rdoc("moderate", "medium", true)} />)
    const b = box()
    expect(within(b).getByText("참고")).toBeInTheDocument(); expect(within(b).queryByText(/미충족|주의/)).toBeNull()
    expect(within(b).getByText("선택한 전략은 이번 분석의 변동성 기준보다 변동성이 높았습니다.")).toBeInTheDocument()
    expect(within(b).getByText("45.5%")).toBeInTheDocument(); expect(within(b).getByText("16.6% 이하")).toBeInTheDocument()
    expect(within(b).getByText("비교지수의 연변동성 12.8%에 1.3배를 적용한 기준입니다. 비교지수보다 30% 높은 변동성까지 허용합니다.")).toBeInTheDocument()
    expect(b).toHaveTextContent("이번 분석의 변동성 기준: 중간 변동성 기준투자성향: 위험중립형")
    expect(within(b).getByText("분석 기간이 짧아, 이번에는 변동성 적합 여부를 판정하지 않고 참고 정보로 표시합니다.")).toBeInTheDocument()
    expect(b).not.toHaveTextContent(/ vs |창이 짧아|중립 성향/)
    expect(within(b).getByRole("button", { name: "연변동성 설명 보기" })).toBeInTheDocument()
    expect(screen.getByText("비교지수보다 낙폭이 큼 (29.9% vs 8.9%)")).toBeInTheDocument()  // 다른 참고 문장은 그대로
  })
  it("충분한 기간: 서버의 주의·충족 판정을 따르고, 반올림한 표시값으로 다시 판정하지 않는다", () => {
    const { unmount } = render(<ConditionRules v={val({ rules_ko: [r7("warn", "연변동성 29.8% vs 비교지수 15.0%의 1배(안정 성향) = 15.0%")] })} doc={rdoc("conservative", "low")} />)
    expect(within(box()).getByText("주의")).toBeInTheDocument()
    expect(within(box()).getByText("선택한 전략은 이번 분석의 변동성 기준보다 변동성이 높았습니다.")).toBeInTheDocument()
    expect(within(box()).getByText(/비교지수와 같은 수준까지 허용합니다/)).toBeInTheDocument()
    expect(within(box()).queryByText(/분석 기간이 짧아/)).toBeNull()
    unmount()
    render(<ConditionRules v={val({ rules_ko: [r7("pass", "연변동성 15.0% vs 비교지수 15.0%의 1배(안정 성향) = 15.0%")] })} doc={rdoc("conservative", "low")} />)
    expect(within(box()).getByText("충족")).toBeInTheDocument()
    expect(within(box()).getByText("선택한 전략의 변동성은 이번 분석의 변동성 기준 이내였습니다.")).toBeInTheDocument()  // 표시값이 같아도 서버 판정(충족) 그대로
  })
  it("상한이 없는 기준은 상한을 만들지 않고, 비교지수 자료가 없으면 배수로 계산했다고 하지 않는다", () => {
    const { unmount } = render(<ConditionRules v={val({ info_notes_ko: ["연변동성 20.3% (비교지수 15.2%) — 적극 성향은 변동성 상한을 두지 않습니다"] })} doc={rdoc("aggressive", "high")} />)
    expect(within(box()).getByText("상한 없음")).toBeInTheDocument()
    expect(within(box()).getByText("높은 변동성 기준에는 변동성 상한이 없어, 변동성 적합 여부를 따로 판정하지 않습니다.")).toBeInTheDocument()
    expect(box()).not.toHaveTextContent(/이하|배를 적용/)
    expect(box()).toHaveTextContent("투자성향: 적극투자형·공격투자형")
    unmount()
    render(<ConditionRules v={val({ rules_ko: [r7("warn", "연변동성 20.0% vs 안정 성향 상한 15.0%")] })} />)
    expect(within(box()).getByText("비교지수 변동성 자료가 없어, 낮은 변동성 기준의 고정 상한 15.0%를 적용했습니다.")).toBeInTheDocument()
    expect(box()).not.toHaveTextContent(/배를 적용|투자성향:/)  // 리포트 성향 자료가 없으면 성향을 쓰지 않는다
  })
  it("요청으로 변동성 기준이 성향의 기본값과 달라지면 둘을 나눠 적는다", () => {
    render(<ConditionRules v={val({ rules_ko: [r7("warn", "연변동성 29.8% vs 비교지수 15.0%의 1배(안정 성향) = 15.0%")] })} doc={rdoc("moderate", "low")} />)
    expect(box()).toHaveTextContent("이번 분석의 변동성 기준: 낮은 변동성 기준투자성향: 위험중립형")
    expect(box()).toHaveTextContent("투자성향의 기본 기준(중간 변동성 기준)과 다르게 적용됐습니다")
  })
  it("주의 목록(요약 카드)에서도 계산식 대신 쉬운 문장으로", () => {
    const a = keyAlerts({ verdict: { status: "recommended_warn", label_ko: "", headline_ko: "", chosen_portfolio_id: "x", chosen_label_ko: "x" }, validation: val({ rules_ko: [r7("warn", "연변동성 29.8% vs 비교지수 15.0%의 1배(안정 성향) = 15.0%")] }), kpis: [], allocation: null, mini_series: null, next_actions_ko: [] })
    expect(a).toEqual([{ tone: "amber", tag: "주의", text: "변동성 적합: 선택 전략의 연변동성 29.8%가 이번 분석의 변동성 기준(15.0% 이하)보다 높았습니다" }])
  })
})

