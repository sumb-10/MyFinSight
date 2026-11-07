import { describe, expect, it, vi } from "vitest"
import { fireEvent, render, screen, waitFor, within } from "@testing-library/react"
import { Providers } from "../../app/providers"
import { ApiError } from "../../api/client"
import type { AnalysisService } from "../../api/service"
import type { ProfileFields, ProfileView } from "../../api/types"
import { ProfileScreen } from "./ProfileScreen"

// 기본 투자조건 화면 UI 개선 회귀 테스트: 저장 값(필드·enum·티커)이 그대로인지, 접힌 설정 값이 남는지, 단계 이동 규칙. 서버 대신 가짜 서비스를 꽂는다.

const version = {
  version: 1, created_at: "2026-01-01T00:00:00", profile: { user_id: "default", age_band: "40s", investment_experience: "intermediate", financial_knowledge: "expert", investable_ratio_of_assets: 0.45 },
  capital: { initial_amount: 10_000_000, currency: "KRW", trading_currency: "USD", monthly_contribution: 300_000, contribution_day: 10 }, horizon: { target_years: 7, purpose: "wealth_growth", backtest_years: 5 },
  risk: { risk_tolerance: "moderate", max_drawdown_tolerance: 0.2, loss_reaction: "hold", target_annual_return: 0.08, benchmark: "QQQ" },
  constraints: { universe: ["SP500", "KOSPI200"], asset_types: ["stock"], num_holdings: { target: 10, min: 8, max: 12 }, max_weight_per_stock: 0.15, max_weight_per_sector: 0.35, min_cash_ratio: 0.05, exclude_tickers: ["NVDA"], exclude_sectors: ["Financials", "반도체업"], exclude_themes: ["tobacco"], must_include_tickers: [], rebalance: { count: 2, unit: "1m" }, allow_leverage: false, allow_short: false, min_market_cap_usd: 2e9, min_avg_daily_volume_usd: 5e6 },
  strategy_preference: { template: "momentum", baseline_weighting: "equal_weight", use_news_tilt: true },
  diagnosis: { answers: { loss: 2, reaction: 2, priority: 2 }, computed_tendency: "위험중립형", final_tendency: "위험중립형", memo: "메모" }, risk_type_computed: "moderate", risk_type_overridden: false,
}
const profileView = { profile_id: "p", current_version: 1, profile: version, versions: [{ version: 1, created_at: version.created_at }] } as unknown as ProfileView

function fakeService(over: Partial<Record<keyof AnalysisService, unknown>> = {}): AnalysisService {
  const no = () => Promise.reject(new ApiError("NOT_IN_TEST", "테스트에서 쓰지 않음", 500))
  return {
    mode: "api", health: () => Promise.resolve({ ok: true, api_version: "1", llm_mode: "api", db: { ok: true }, worker: { alive: true, running_run_id: null }, queue_length: 0 }),
    options: no, getProfile: () => Promise.resolve(profileView), saveProfile: no, listRequests: () => Promise.resolve([]), listRuns: () => Promise.resolve([]), listReports: () => Promise.resolve([]), getReportComparison: () => Promise.resolve(null),
    ...over,
  } as unknown as AnalysisService
}

const stepNav = () => screen.getByRole("navigation", { name: "설정 단계" })
const stepBtn = (name: RegExp) => within(stepNav()).getByRole("button", { name })

describe("기본 투자조건 수정 화면", () => {
  it("단계 카드로 바로 이동하고, 접힌 값·기존 값은 그대로 두며, 바꾼 값만 기존 형식으로 저장한다", async () => {
    const saveProfile = vi.fn((f: ProfileFields) => Promise.resolve({ ...profileView, profile: { ...version, ...f } } as unknown as ProfileView))
    render(<Providers service={fakeService({ saveProfile })}><ProfileScreen mode="edit" /></Providers>)
    await screen.findByText("저장된 투자조건을 수정합니다.")

    // 4단계로 바로 이동 → 쉬운 문구, 설명용 예시, 주의 문구
    fireEvent.click(stepBtn(/투자 전략/))
    expect(stepBtn(/투자 전략/)).toHaveAttribute("aria-current", "step")
    expect(screen.getByRole("heading", { name: "투자 전략 설정" })).toBeInTheDocument()
    expect(screen.getByText(/설명용 예시/)).toBeInTheDocument()
    expect(screen.getByText("뉴스 반영이 반드시 더 높은 수익률을 의미하지는 않습니다.")).toBeInTheDocument()
    fireEvent.click(screen.getByRole("radio", { name: /가격이 상대적으로 저평가된 기업/ }))
    fireEvent.click(screen.getByRole("radio", { name: /규모가 큰 기업에 더 많이 투자/ }))
    expect(screen.getByText("선택: 뉴스·공시 반영 켜짐")).toBeInTheDocument()
    fireEvent.click(screen.getByRole("switch", { name: /뉴스와 공시를 참고해/ }))
    expect(screen.getByText("선택: 뉴스·공시 반영 꺼짐")).toBeInTheDocument()  // 켜면/끄면 카드 대신 지금 선택만 한 상자로
    // 전략 이름은 쉬운 표현 옆에 전문용어를 괄호로 함께 보여 준다 (카드·선택 줄·저장 요약 모두)
    expect(screen.getByRole("radio", { name: /^가격이 상대적으로 저평가된 기업\(저PER\)/ })).toHaveAttribute("aria-checked", "true")
    expect(screen.getByRole("radio", { name: /^최근 주가 상승세가 좋은 기업\(모멘텀\)/ })).toBeInTheDocument()
    expect(screen.getByRole("radio", { name: /^규모가 큰 기업에 더 많이 투자\(시가총액비중\)/ })).toHaveAttribute("aria-checked", "true")
    expect(screen.getByText("저평가 기업 중심(저PER) · 규모가 큰 기업에 더 많이 투자(시가총액비중) · 뉴스 반영 꺼짐")).toBeInTheDocument()
    expect(screen.queryByText(/전문 용어/)).toBeNull()  // 괄호로 보이므로 따로 적지 않는다
    // ⓘ 설명은 Esc 로 닫힌다
    const tip = screen.getByRole("button", { name: "투자 전략 설정 설명 보기" })
    fireEvent.click(tip)
    expect(tip).toHaveAttribute("aria-expanded", "true")
    fireEvent.keyDown(window, { key: "Escape" })
    expect(screen.queryByRole("note")).toBeNull()

    // 3단계: 저장된 영문 섹터 이름은 같은 섹터로 체크되고, 목록에 없는 값은 지우지 않고 보여 준다
    fireEvent.click(stepBtn(/종목 범위/))
    expect(screen.getByRole("button", { name: /빼거나 꼭 넣을 종목/ })).toHaveAttribute("aria-expanded", "true")  // 값이 있으면 펼쳐 둔다
    expect(screen.getByRole("checkbox", { name: /금융/ })).toBeChecked()
    expect(screen.getByText(/목록에 없는 섹터 이름/)).toBeInTheDocument()
    fireEvent.click(screen.getByRole("checkbox", { name: /정보기술/ }))
    const exclude = screen.getByLabelText("제외할 종목")
    fireEvent.change(exclude, { target: { value: "tsla" } })
    fireEvent.keyDown(exclude, { key: "Enter", isComposing: true })  // 한글 조합 중 Enter 는 무시
    expect(screen.queryByText("TSLA")).toBeNull()
    fireEvent.keyDown(exclude, { key: "Enter" })
    expect(screen.getByText("TSLA")).toBeInTheDocument()
    const themes = screen.getByLabelText("제외할 테마")
    fireEvent.change(themes, { target: { value: "도박, " } })
    expect(screen.getByText("도박")).toBeInTheDocument()

    // 다른 단계에 갔다 와도 값이 남는다
    fireEvent.click(stepBtn(/기본 조건/))
    fireEvent.click(stepBtn(/투자 전략/))
    expect(screen.getByRole("radio", { name: /가격이 상대적으로 저평가된 기업/ })).toHaveAttribute("aria-checked", "true")

    fireEvent.click(screen.getByRole("button", { name: "저장" }))
    await waitFor(() => expect(saveProfile).toHaveBeenCalledTimes(1))
    const body = saveProfile.mock.calls[0][0]
    expect(body.strategy_preference).toEqual({ template: "low_per", baseline_weighting: "market_cap", use_news_tilt: false })
    expect(body.constraints.exclude_tickers).toEqual(["NVDA", "TSLA"])
    expect(body.constraints.exclude_sectors).toEqual(["Financials", "반도체업", "정보기술"])
    expect(body.constraints.exclude_themes).toEqual(["tobacco", "도박"])
    // 펼치지 않은 고급 설정·참고 정보는 저장 값 그대로
    expect(body.profile).toEqual(version.profile)
    expect(body.capital).toEqual(version.capital)
    expect(body.horizon).toEqual(version.horizon)
    expect(body.risk).toEqual(version.risk)
    expect({ ...body.constraints, exclude_tickers: [], exclude_sectors: [], exclude_themes: [] }).toEqual({ ...version.constraints, exclude_tickers: [], exclude_sectors: [], exclude_themes: [] })
  }, 15_000)  // 전체 테스트를 병렬로 돌리면 느려진다

  it("슬라이더와 % 숫자 입력이 서로 맞춰지고, 범위를 벗어난 숫자는 반영하지 않는다", async () => {
    const saveProfile = vi.fn((f: ProfileFields) => Promise.resolve({ ...profileView, profile: { ...version, ...f } } as unknown as ProfileView))
    render(<Providers service={fakeService({ saveProfile })}><ProfileScreen mode="edit" /></Providers>)
    await screen.findByText("저장된 투자조건을 수정합니다.")
    fireEvent.click(stepBtn(/투자성향/))
    const num = screen.getByRole("spinbutton", { name: /손실 감내 수준/ })
    const slider = screen.getByRole("slider", { name: /손실 감내 수준/ })
    expect(num).toHaveValue(20)
    fireEvent.change(num, { target: { value: "23" } })
    expect(slider).toHaveValue("0.23")
    fireEvent.change(num, { target: { value: "75" } })
    expect(screen.getByText("5~60% 사이로 입력해 주세요")).toBeInTheDocument()
    expect(slider).toHaveValue("0.23")
    fireEvent.blur(num)
    expect(num).toHaveValue(23)
    fireEvent.change(slider, { target: { value: "0.31" } })
    expect(num).toHaveValue(31)
    fireEvent.click(stepBtn(/투자 전략/))
    fireEvent.click(screen.getByRole("button", { name: "저장" }))
    await waitFor(() => expect(saveProfile).toHaveBeenCalledTimes(1))
    expect(saveProfile.mock.calls[0][0].risk.max_drawdown_tolerance).toBe(0.31)
  })

  it("저장 검사에 걸린 값이 접힌 고급 설정 안에 있으면 펼쳐서 보여 준다", async () => {
    render(<Providers service={fakeService()}><ProfileScreen mode="edit" /></Providers>)
    await screen.findByText("저장된 투자조건을 수정합니다.")
    fireEvent.click(stepBtn(/종목 범위/))
    fireEvent.change(screen.getByLabelText("최소"), { target: { value: "5" } })  // 15% × 5 < 95% → 종목당 상한 오류
    fireEvent.click(stepBtn(/투자 전략/))
    fireEvent.click(screen.getByRole("button", { name: "저장" }))
    expect(stepBtn(/종목 범위/)).toHaveTextContent("확인 필요")
    fireEvent.click(stepBtn(/종목 범위/))
    expect(screen.getByRole("button", { name: /세부 제약 조건/ })).toHaveAttribute("aria-expanded", "true")
    expect(screen.getAllByText(/최소 종목 수가 투자 비율보다 작아/).length).toBeGreaterThan(0)
  })
})

describe("기간·숫자 입력", () => {
  it("두 기간의 짧은 설명을 늘 보여 주고, 검증 기간이 더 짧으면 관계를 안내한다", async () => {
    render(<Providers service={fakeService()}><ProfileScreen mode="edit" /></Providers>)
    await screen.findByText("저장된 투자조건을 수정합니다.")
    expect(screen.getByText(/앞으로 7년 동안 투자하는 것을 기준으로 분석합니다/)).toBeInTheDocument()
    expect(screen.getByText(/과거 5년의 데이터로 전략을 검증합니다/)).toBeInTheDocument()
    expect(screen.getByText("투자기간 7년 중 과거 검증은 5년으로 설정되어 있습니다")).toBeInTheDocument()
    fireEvent.change(screen.getByRole("spinbutton", { name: "과거 성과를 확인할 기간 (년)" }), { target: { value: "8" } })
    expect(screen.queryByText(/중 과거 검증은/)).toBeNull()
  })

  it("0 이 들어 있던 숫자 칸에 숫자를 치면 앞의 0 이 지워진다", async () => {
    const saveProfile = vi.fn((f: ProfileFields) => Promise.resolve({ ...profileView, profile: { ...version, ...f } } as unknown as ProfileView))
    render(<Providers service={fakeService({ saveProfile })}><ProfileScreen mode="edit" /></Providers>)
    await screen.findByText("저장된 투자조건을 수정합니다.")
    fireEvent.click(stepBtn(/종목 범위/))
    fireEvent.click(screen.getByRole("button", { name: /세부 제약 조건/ }))
    const count = screen.getByRole("spinbutton", { name: "리밸런싱 간격" })
    fireEvent.change(count, { target: { value: "0" } })
    fireEvent.change(count, { target: { value: "03" } })  // 0 뒤에 3 을 친 상태
    expect(count).toHaveValue(3)
    expect((count as HTMLInputElement).value).toBe("3")
    fireEvent.click(stepBtn(/투자성향/))
    const pct = screen.getByRole("spinbutton", { name: /목표 연수익률/ })
    fireEvent.change(pct, { target: { value: "012" } })
    expect((pct as HTMLInputElement).value).toBe("12")
    fireEvent.click(stepBtn(/투자 전략/))
    fireEvent.click(screen.getByRole("button", { name: "저장" }))
    await waitFor(() => expect(saveProfile).toHaveBeenCalledTimes(1))
    expect(saveProfile.mock.calls[0][0].constraints.rebalance).toEqual({ count: 3, unit: "1m" })
    expect(saveProfile.mock.calls[0][0].risk.target_annual_return).toBe(0.12)
  })
})

describe("저장된 투자조건 화면", () => {
  const v = (n: number, patch: (x: typeof version) => void, created_at: string) => { const x = structuredClone({ ...version, version: n, created_at }); patch(x); return x }
  const v1 = v(1, (x) => { x.capital.initial_amount = 10_000_000; x.risk.max_drawdown_tolerance = 0.15 }, "2026-10-29T17:37:30+09:00")
  const v2 = v(2, (x) => { x.capital.initial_amount = 10_000_000; x.risk.max_drawdown_tolerance = 0.15 }, "2026-10-30T14:16:37+09:00")  // 같은 값으로 다시 저장
  const v3 = v(3, () => {}, "2026-10-30T16:58:00+09:00")  // 투자금·손실 감내 수준 + 여러 항목이 바뀐 버전 (아래에서 더 바꾼다)
  v3.capital.initial_amount = 20_000_000; v3.constraints.exclude_tickers = ["NVDA", "TSLA"]; v3.strategy_preference.use_news_tilt = false; v3.horizon.backtest_years = 4
  const view = { ...profileView, current_version: 3, profile: v3, versions: [v1, v2, v3].map((x) => ({ version: x.version, created_at: x.created_at })) } as unknown as ProfileView

  it("저장 값을 자연스러운 표현과 단위로 보여 준다", async () => {
    render(<Providers service={fakeService({ getProfile: () => Promise.resolve(view) })}><ProfileScreen mode="view" /></Providers>)
    await screen.findByText("저장된 기본 투자조건")
    expect(screen.getByText("2,000만원")).toBeInTheDocument()
    expect(screen.getByText("매월 30만원 · 10일")).toBeInTheDocument()
    expect(screen.getByText("종목당 최대 15% · 섹터당 최대 35%")).toBeInTheDocument()
    expect(screen.getByText("2개월마다 1회")).toBeInTheDocument()
    expect(screen.getByText("주식")).toBeInTheDocument()
    expect(screen.getByText("투자 대상 지수")).toBeInTheDocument()
    expect(screen.getByText("위험중립형")).toBeInTheDocument()  // "위험중립형 (중립)" 같은 중복 없이
    expect(screen.getByText("20억 USD 이상")).toBeInTheDocument()
    expect(screen.getByText("주가 상승세 좋은 기업 중심(모멘텀) · 모든 기업에 비슷하게 투자(동일비중) · 뉴스 반영 꺼짐")).toBeInTheDocument()
    expect(screen.queryByText(/stock|1×|\(중립\)/)).toBeNull()
  })

  it("변경 이력은 접혀 있고, 펼치면 최신 버전부터 저장 시각·버전만 보여 준다 (과거 값이 없어 변경 내용은 추측하지 않는다)", async () => {
    render(<Providers service={fakeService({ getProfile: () => Promise.resolve(view) })}><ProfileScreen mode="view" /></Providers>)
    await screen.findByText("저장된 기본 투자조건")
    const toggle = screen.getByRole("button", { name: /변경 이력 보기/ })
    expect(toggle).toHaveAttribute("aria-expanded", "false")
    expect(screen.queryByText(/· 버전 1/)).toBeNull()
    fireEvent.click(toggle)
    const heads = screen.getAllByRole("listitem").map((li) => li.textContent ?? "").filter((t) => t.includes("· 버전"))
    expect(heads.map((t) => t.replace(/^2026년 /, ""))).toEqual(["10월 30일 16:58 · 버전 3현재", "10월 30일 14:16 · 버전 2", "10월 29일 17:37 · 버전 1최초 설정"])  // 올해가 아니면 연도가 붙는다
    expect(screen.queryByText(/→/)).toBeNull()
  })
})

describe("처음 설정 화면", () => {
  it("아직 지나지 않은 단계는 앞 단계를 검사해 막히는 단계에서 멈춘다", async () => {
    render(<Providers service={fakeService({ getProfile: () => Promise.resolve(null) })}><ProfileScreen mode="setup" /></Providers>)
    await screen.findByText("기본 투자조건을 알려주세요.")
    expect(screen.getByRole("textbox", { name: "처음 투자할 금액" })).toHaveValue("10,000,000")  // 기본값은 그대로
    fireEvent.click(stepBtn(/투자 전략/))
    expect(stepBtn(/투자성향/)).toHaveAttribute("aria-current", "step")
    expect(screen.getAllByText("필수 질문에 모두 답해 주세요").length).toBeGreaterThan(0)
    // 지나온 1단계는 검사 없이 바로 돌아간다
    fireEvent.click(stepBtn(/기본 조건/))
    expect(stepBtn(/기본 조건/)).toHaveAttribute("aria-current", "step")
  })
})
