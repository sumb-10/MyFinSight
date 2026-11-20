import { describe, expect, it } from "vitest"
import { fireEvent, render, screen, within } from "@testing-library/react"
import { BarItems, LineSeries } from "./blocks"
import type { LineBlock, ReportDoc } from "../../../api/types"

const doc = { header: {}, sections: [], kpis: [], parameters: {}, datasets: { dates: ["2025-01-01", "2025-01-02"], series: { equal_weight: { label_ko: "동일비중", kind: "template", index: [100, 110] }, inverse_volatility: { label_ko: "역변동성비중", kind: "template", index: [100, 95] }, net_invested: { label_ko: "투입 원금(누적)", kind: "line", index: [100, 100] } } } } as unknown as ReportDoc
const b: LineBlock = { type: "line", title_ko: "누적 수익률 (시작 = 100)", dataset: "index", series_ids: ["equal_weight", "inverse_volatility", "net_invested"], default_on: ["equal_weight", "net_invested"], y_format: "index" } as LineBlock

describe("수익률 추이 범례", () => {
  it("켜진 선마다 이름·마지막 값·쉬운 설명 한 줄, 칩을 켜면 그 줄이 생긴다", () => {
    render(<LineSeries b={b} doc={doc} />)
    const lg = screen.getByRole("list", { name: "그래프 범례와 설명" })
    expect(within(lg).getAllByRole("listitem")).toHaveLength(2)
    expect(lg).toHaveTextContent("동일비중+10.0%선정한 종목에 같은 비율로 나눠 투자하는 방식입니다.")
    expect(lg).toHaveTextContent("투입 원금(누적)")  // 설명이 없는 항목은 이름과 값만
    fireEvent.click(screen.getByRole("button", { name: /역변동성비중/ }))
    expect(within(lg).getAllByRole("listitem")).toHaveLength(3)
    expect(lg).toHaveTextContent("역변동성비중−5.0%주가가 덜 흔들린 종목에 더 많이 투자하는 방식입니다.")
  })
})

describe("업종별 투자 비중", () => {
  it("「섹터 노출 (기간 평균 비중, 전략)」 제목을 「업종별 투자 비중 (전략, 백테스트 기간 평균)」으로 보여 준다", () => {
    render(<BarItems b={{ type: "bar", title_ko: "섹터 노출 (기간 평균 비중, 최소분산)", format: "pct", items: [{ label: "정보기술", value: 0.6 }] }} />)
    expect(screen.getByText("업종별 투자 비중 (최소분산, 백테스트 기간 평균)")).toBeInTheDocument()
    expect(screen.queryByText(/섹터 노출/)).toBeNull()
  })
})
