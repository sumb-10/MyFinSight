import { describe, expect, it } from "vitest"
import { fireEvent, render, screen } from "@testing-library/react"
import { Disclosure, Menu, Pagination } from "./index"

describe("Disclosure", () => {
  it("접힌 내용은 처음 펼칠 때 마운트하고 aria-expanded 를 바꾼다", () => {
    render(<Disclosure title="묶음"><p>속내용</p></Disclosure>)
    const btn = screen.getByRole("button", { name: /묶음/ })
    expect(btn).toHaveAttribute("aria-expanded", "false")
    expect(screen.queryByText("속내용")).toBeNull()
    fireEvent.click(btn)
    expect(btn).toHaveAttribute("aria-expanded", "true")
    expect(screen.getByText("속내용")).toBeVisible()
    fireEvent.click(btn)
    expect(screen.getByText("속내용")).not.toBeVisible()  // 접어도 마운트는 유지 (다시 그리지 않음)
  })
})

describe("Menu", () => {
  it("열고 항목을 누르면 실행되고 닫힌다, Escape 로도 닫힌다", () => {
    let hit = 0
    render(<Menu items={[{ label: "재분석", onClick: () => { hit += 1 } }]} />)
    fireEvent.click(screen.getByRole("button", { name: /더보기/ }))
    fireEvent.click(screen.getByRole("menuitem", { name: "재분석" }))
    expect(hit).toBe(1); expect(screen.queryByRole("menu")).toBeNull()
    fireEvent.click(screen.getByRole("button", { name: /더보기/ }))
    fireEvent.keyDown(window, { key: "Escape" })
    expect(screen.queryByRole("menu")).toBeNull()
  })
})

describe("Pagination", () => {
  it("한 페이지면 그리지 않고, 여러 페이지면 범위와 버튼을 보여 준다", () => {
    const { container, rerender } = render(<Pagination page={0} pages={1} onChange={() => {}} />)
    expect(container).toBeEmptyDOMElement()
    let p = 0
    rerender(<Pagination page={0} pages={3} total={120} pageSize={50} onChange={(n) => { p = n }} />)
    expect(screen.getByText("1–50 / 120건")).toBeInTheDocument()
    expect(screen.getByRole("button", { name: "이전 페이지" })).toBeDisabled()
    fireEvent.click(screen.getByRole("button", { name: "다음 페이지" }))
    expect(p).toBe(1)
  })
})
