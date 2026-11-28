import { afterEach, beforeAll, describe, expect, it, vi } from "vitest"
import { fireEvent, render, screen, waitFor } from "@testing-library/react"
import { Providers } from "../app/providers"
import type { AnalysisService } from "../api/service"
import { isBeginnerView } from "../features/profile/BeginnerView"
import { ProfileChatScreen } from "../features/profile/chat/ProfileChatScreen"
import { diffProfiles, profileRows } from "../features/profile/compare"
import { DEFAULT_FORM } from "../features/profile/defaults"
import { ProfileScreen } from "../features/profile/ProfileScreen"
import { MockService } from "./services/MockService"

// 왕초보용 화면 설정 (2026-11-28): 대화형 설정의 첫 질문, 저장된 투자조건 화면의 스위치(바로 저장), 4단계 폼의 스위치(함께 저장), 요약표 행.
// 여기서는 값을 묻고 저장하는 것만 확인한다. 리포트의 왕초보용 화면은 features/report/beginner/beginner.test.tsx.

beforeAll(() => { globalThis.ResizeObserver ??= class { observe() {} unobserve() {} disconnect() {} } as unknown as typeof ResizeObserver; Element.prototype.scrollIntoView = vi.fn() })
afterEach(() => { window.history.replaceState(null, "", "/"); window.localStorage.clear() })

const mock = () => new MockService({ latencyMs: 0, persist: false })
const firstUser = () => { const s = mock(); s.setProfileVariant("none"); return s }
const show = (svc: AnalysisService, ui: React.ReactNode) => { window.history.replaceState(null, "", "/?mock=1"); return render(<Providers service={svc}>{ui}</Providers>) }
const theSwitch = () => screen.findByRole("switch", { name: "왕초보용 화면" }, { timeout: 5000 })
const pick = async (name: RegExp) => fireEvent.click(await screen.findByRole("button", { name }, { timeout: 5000 }))

describe("왕초보용 화면 · 저장된 투자조건 화면", () => {
  it("맨 위 스위치를 누르면 그 값만 바꿔 바로 저장한다 (새 버전, 다른 값은 그대로)", async () => {
    const s = mock()
    const before = (await s.getProfile())!
    expect(isBeginnerView(before)).toBe(false)  // 값이 없는 예전 투자조건은 일반 화면
    show(s, <ProfileScreen mode="view" />)
    const sw = await theSwitch()
    expect(sw).toHaveAttribute("aria-checked", "false")
    expect(screen.getByText("사용 안 함")).toBeInTheDocument()
    fireEvent.click(sw)
    await waitFor(() => expect(screen.getByRole("switch", { name: "왕초보용 화면" })).toHaveAttribute("aria-checked", "true"), { timeout: 5000 })
    expect(screen.getByText("사용 중")).toBeInTheDocument()
    const on = (await s.getProfile())!
    expect(on.current_version).toBe(before.current_version + 1)
    expect(on.profile).toMatchObject({ beginner_view: true, note: "왕초보용 화면 켬", capital: before.profile.capital, risk: before.profile.risk, constraints: before.profile.constraints, strategy_preference: before.profile.strategy_preference })
    fireEvent.click(screen.getByRole("switch", { name: "왕초보용 화면" }))
    await waitFor(() => expect(screen.getByRole("switch", { name: "왕초보용 화면" })).toHaveAttribute("aria-checked", "false"), { timeout: 5000 })
    expect((await s.getProfile())!).toMatchObject({ current_version: before.current_version + 2, profile: { beginner_view: false, note: "왕초보용 화면 끔" } })
  })
  it("저장하지 못하면 이유를 보여 주고 스위치는 그대로 둔다", async () => {
    const s = mock()
    const svc: AnalysisService = Object.assign(Object.create(s), { saveProfile: () => Promise.reject(new Error("서버에 연결하지 못했습니다")) })
    show(svc, <ProfileScreen mode="view" />)
    fireEvent.click(await theSwitch())
    expect(await screen.findByText(/저장하지 못했습니다: 서버에 연결하지 못했습니다/, {}, { timeout: 5000 })).toBeInTheDocument()
    expect(screen.getByRole("switch", { name: "왕초보용 화면" })).toHaveAttribute("aria-checked", "false")
    expect(isBeginnerView(await s.getProfile())).toBe(false)
  })
})

describe("왕초보용 화면 · 4단계 폼", () => {
  it("어느 단계에서나 스위치가 보이고, 바꾼 값은 마지막 단계의 「저장」에서 다른 값과 함께 저장된다", async () => {
    const s = mock()
    show(s, <ProfileScreen mode="edit" />)
    const sw = await theSwitch()
    fireEvent.click(sw)
    expect(sw).toHaveAttribute("aria-checked", "true")
    expect(isBeginnerView(await s.getProfile())).toBe(false)  // 아직 저장 전
    for (const [n, label] of [[2, "투자성향"], [3, "종목 범위·제약"], [4, "투자 전략"]] as const) {
      await pick(new RegExp(`^${n}단계 ${label}`))
      expect(screen.getByRole("switch", { name: "왕초보용 화면" })).toHaveAttribute("aria-checked", "true")
    }
    expect(screen.getByText(/· 왕초보용 화면 사용$/)).toBeInTheDocument()  // 저장 요약
    fireEvent.click(screen.getByRole("button", { name: "저장" }))
    await waitFor(async () => expect(isBeginnerView(await s.getProfile())).toBe(true), { timeout: 5000 })
    expect((await s.getProfile())!.profile.note).toBe("수정")
  })
  it("대화에서 「예」라고 답하고 폼으로 넘어오면 스위치가 켜져 있다", async () => {
    const s = firstUser()
    const { unmount } = show(s, <ProfileChatScreen />)
    expect(await screen.findByText("왕초보용 화면으로 설정할까요?", {}, { timeout: 5000 })).toBeInTheDocument()
    await pick(/^예/)
    await screen.findByRole("button", { name: /^자산 증식/ }, { timeout: 5000 })
    fireEvent.click(screen.getByRole("button", { name: /폼으로 한 번에 입력/ }))
    unmount()
    show(s, <ProfileScreen mode="setup" />)
    expect(await theSwitch()).toHaveAttribute("aria-checked", "true")
  })
})

describe("왕초보용 화면 · 요약표", () => {
  it("요약표·버전 비교의 첫 행으로 보이고, 값이 없는 예전 투자조건은 「사용 안 함」이다", () => {
    expect(profileRows(DEFAULT_FORM)[0]).toEqual({ group: "화면", key: "beginner_view", label: "왕초보용 화면", value: "사용 안 함" })
    expect(diffProfiles(DEFAULT_FORM, { ...DEFAULT_FORM, beginner_view: true }).filter((r) => r.changed))
      .toEqual([{ group: "화면", key: "beginner_view", label: "왕초보용 화면", before: "사용 안 함", after: "사용", changed: true }])
    const { beginner_view: _unset, ...old } = DEFAULT_FORM
    expect(profileRows(old)[0].value).toBe("사용 안 함")
  })
})
