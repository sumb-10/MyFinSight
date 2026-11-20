import { describe, expect, it } from "vitest"
import { fireEvent, render, screen } from "@testing-library/react"
import { BarItems, DataTable } from "./blocks"
import type { TableBlock } from "../../../api/types"

describe("표 표시", () => {
  it("「분석 중 확인한 점」 표는 「분석하면서 처리한 일」로, 날짜·횟수 열은 빼고 문장에 없는 값만 문장 끝에 붙인다", () => {
    const b = { type: "table", title_ko: "분석 중 확인한 점 (조건을 바꾸면 달라질 수 있는 것)", columns: [{ key: "msg", label_ko: "내용", format: "text" }, { key: "when", label_ko: "횟수·기간", format: "text" }],
      rows: [{ msg: "미국 법인이 아닌 종목은 선정하지 않았습니다.", when: "-" }, { msg: "백테스트 시작일(2025-11-10) 기준: 다시 골랐습니다.", when: "2025-11-10" }, { msg: "같은 안내가 여러 번 나왔습니다.", when: "3회 2025-11-10~2026-11-10" }] } as TableBlock
    render(<DataTable b={b} />)
    expect(screen.getByRole("heading", { name: "분석하면서 처리한 일" })).toBeInTheDocument()
    expect(screen.queryByText(/종목을 고르고 자료를 모으는 동안/)).toBeNull()  // 설명은 처음에는 안 보이고
    fireEvent.click(screen.getByRole("button", { name: "분석하면서 처리한 일 설명 보기" }))
    expect(screen.getByRole("dialog", { name: "분석하면서 처리한 일 설명" })).toHaveTextContent("종목을 고르고 자료를 모으는 동안 이렇게 처리했습니다. 조건을 바꾸면 달라질 수 있습니다.")  // 제목 옆 ? 를 누르면 보인다
    fireEvent.click(screen.getByRole("button", { name: "설명 닫기" }))
    expect(screen.getAllByRole("columnheader").map((h) => h.textContent)).toEqual(["내용"])  // 날짜·횟수 열 없음
    expect(screen.getByText("미국 법인이 아닌 종목은 선정하지 않았습니다.")).toBeInTheDocument()  // 「-」는 붙이지 않는다
    expect(screen.getByText("백테스트 시작일(2025-11-10) 기준: 다시 골랐습니다.")).toBeInTheDocument()  // 문장에 이미 있는 날짜는 다시 붙이지 않는다
    expect(screen.getByText("같은 안내가 여러 번 나왔습니다. (3회 2025-11-10~2026-11-10)")).toBeInTheDocument()  // 문장에 없는 정보는 남긴다
  })
})

describe("주가 자료 점검", () => {
  const quality = (excluded: string, filled: string) => ({ type: "table", title_ko: "가격 자료 품질 판정 (커버리지 0.95, 1거래일 결측만 채움)", columns: [{ key: "k", label_ko: "항목", format: "text" }, { key: "v", label_ko: "값", format: "text" }],
    rows: [{ k: "기대 거래일", v: "252" }, { k: "가격 자료가 충분한 종목 (비교지수 포함)", v: "10" }, { k: "제외 종목", v: excluded }, { k: "직전값으로 채운 종목(일수)", v: filled }] }) as TableBlock
  it("문제없으면 결론 한 줄과 쉬운 항목 이름·단위, 점검 규칙은 제목 옆 ? 에", () => {
    render(<DataTable b={quality("없음", "없음")} />)
    expect(screen.getByRole("heading", { name: /^주가 자료 점검/ })).toBeInTheDocument()
    expect(screen.queryByText(/커버리지|결측/)).toBeNull()
    expect(screen.getByText("✓ 모든 종목의 주가 자료가 충분해, 빼거나 채운 종목 없이 계산했습니다.")).toBeInTheDocument()
    expect(screen.getByText("백테스트 기간 거래일 수").nextSibling).toHaveTextContent("252일")
    expect(screen.getByText("자료가 충분한 종목 (비교지수 포함)").nextSibling).toHaveTextContent("10개")
    fireEvent.click(screen.getByRole("button", { name: "주가 자료 점검 설명 보기" }))
    expect(screen.getByRole("dialog", { name: "주가 자료 점검 설명" })).toHaveTextContent("95% 이상(240일 이상)")
  })
  it("뺀 종목·채운 종목이 있으면 그 사실을 결론에 쓴다 (값은 서버 그대로)", () => {
    render(<DataTable b={quality("AAA: 가격 이력 부족, BBB: 거래 정지", "CCC 1")} />)
    expect(screen.getByText("⚠ 자료가 부족해 2개 종목을 뺐습니다 · 하루 빠진 주가를 전날 값으로 채운 종목이 있습니다.")).toBeInTheDocument()
    expect(screen.getByText("AAA: 가격 이력 부족, BBB: 거래 정지")).toBeInTheDocument()
  })
})

describe("숫자 열 정렬", () => {
  it("숫자 열은 열 이름도 값처럼 오른쪽 정렬, 글자 열은 왼쪽", () => {
    render(<DataTable b={{ type: "table", title_ko: "표", columns: [{ key: "t", label_ko: "티커", format: "text" }, { key: "m", label_ko: "모멘텀", format: "pct" }], rows: [{ t: "HPE", m: 2.195 }, { t: "X", m: null }] } as unknown as TableBlock} />)
    expect(screen.getByRole("columnheader", { name: "모멘텀" }).className).toContain("text-right")
    expect(screen.getByRole("columnheader", { name: "티커" }).className).not.toContain("text-right")
    expect(screen.getByText("–").className).toContain("text-right")
  })
})

describe("종목별 수익 기여", () => {
  it("차트 없이 표만, 기여가 큰 종목부터 보여 준다", () => {
    render(<BarItems b={{ type: "bar", title_ko: "종목별 수익 기여 (기간 전체)", format: "pp", items: [{ label: "AAA", value: 0.01 }, { label: "BBB", value: 0.05 }, { label: "CCC", value: -0.02 }] }} />)
    expect(screen.queryByRole("button", { name: /표로 보기|차트로 보기/ })).toBeNull()
    const rows = screen.getAllByRole("row").slice(1).map((r) => r.textContent ?? "")
    expect(rows.map((r) => r.slice(0, 3))).toEqual(["BBB", "AAA", "CCC"])
  })
})
