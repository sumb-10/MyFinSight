import { afterEach, beforeAll, describe, expect, it, vi } from "vitest"
import { fireEvent, render, screen, waitFor, within } from "@testing-library/react"
import { Providers } from "../app/providers"
import type { AnalysisService } from "../api/service"
import { proposedRulesOf } from "../api/proposed"
import { ProfileScreen } from "../features/profile/ProfileScreen"
import { ClarifyScreen } from "../features/analysis/ClarifyScreen"
import { ConfirmScreen } from "../features/analysis/ConfirmScreen"
import { MockService } from "./services/MockService"

// 4단계: 내 투자조건(종목 검색·0원 시작·성향 기반 추천·변경 이력 비교)과 새 분석(여러 질문 한 번에·종목 이름·말로 보태기 결과).
// 서비스에 제안 메서드가 없으면(일반 모드) 지금 화면 그대로인지도 확인한다.

beforeAll(() => { globalThis.ResizeObserver ??= class { observe() {} unobserve() {} disconnect() {} } as unknown as typeof ResizeObserver; Element.prototype.scrollIntoView = vi.fn() })
afterEach(() => window.history.replaceState(null, "", "/"))

const mock = () => new MockService({ latencyMs: 0, persist: false })
const withSvc = (svc: AnalysisService, ui: React.ReactNode) => { window.history.replaceState(null, "", "/?mock=1"); return render(<Providers service={svc}>{ui}</Providers>) }
/** 제안 메서드·규칙을 뺀 서비스 (일반 모드의 HttpService 처럼). */
const plain = (s: MockService): AnalysisService => Object.assign(Object.create(s), {
  mode: "api", searchStocks: undefined, getStocks: undefined, recommendStrategy: undefined, getProfileVersion: undefined, getQuestionBatch: undefined, answerBatch: undefined, getMessageResults: undefined,
  options: async () => { const { proposed_rules: _r, ...o } = await s.options(); return o },
})
const step = async (n: number, label: string) => fireEvent.click(await screen.findByRole("button", { name: new RegExp(`^${n}단계 ${label}`) }, { timeout: 5000 }))

describe("목업 서비스 규칙", () => {
  it("처음 사용자: 저장 전에는 투자조건이 없고, 처음 저장하면 버전 1이 된다", async () => {
    const s = mock()
    const { version: _v, created_at: _c, ...base } = await s.getProfileVersion(1)  // 저장할 값의 모양만 빌린다
    s.setProfileVariant("none")
    expect(await s.getProfile()).toBeNull()
    const v = await s.saveProfile({ ...base, note: "첫 등록" })
    expect(v).toMatchObject({ current_version: 1, versions: [{ version: 1, note: "첫 등록" }] })
    expect((await s.getProfile())?.current_version).toBe(1)
  })
  it("회사 이름·티커 검색 (티커·이름 앞부분이 먼저), 티커로 회사명 조회", async () => {
    const s = mock()
    expect((await s.searchStocks("마이크론"))[0].ticker).toBe("MU")
    expect((await s.searchStocks("mu"))[0].ticker).toBe("MU")
    expect((await s.searchStocks("삼성"))[0]).toMatchObject({ ticker: "005930", market: "KR" })
    expect(await s.searchStocks("spy")).toEqual([])  // ETF 는 종목 후보가 아니다
    expect((await s.getStocks(["NVDA", "ZZZZ"])).map((x) => x.name_ko)).toEqual(["엔비디아"])
  })
  it("0원 시작 규칙은 목업 옵션으로, 성향별 추천은 서버와 같은 고정 규칙 표로 온다", async () => {
    const s = mock()
    expect(proposedRulesOf(await s.options())?.allow_zero_initial_amount).toBe(true)
    expect((await s.recommendStrategy("안정형")).recommended).toMatchObject({ template: "high_dividend", baseline_weighting: "min_variance", use_news_tilt: false })
    expect((await s.recommendStrategy("위험중립형")).alternatives).toHaveLength(2)
  })
  it("여러 질문 한 번에: 필수 질문이 비면 거절하고, 고른 보기는 조건에 반영된다 (종목은 회사명과 함께)", async () => {
    const s = mock()
    const b = (await s.getQuestionBatch("mock_req_asking"))!
    expect(b.questions.map((q) => q.required)).toEqual([true, false, true])
    await expect(s.answerBatch("mock_req_asking", [{ seq: 1, option_value: 0.25 }, { seq: 2, skip: true }])).rejects.toMatchObject({ message: expect.stringContaining("손실 감내 수준") })
    const d = await s.answerBatch("mock_req_asking", [{ seq: 1, option_value: 0.25 }, { seq: 2, option_value: ["MU"] }, { seq: 3, option_value: 0.35 }])
    expect(d.state).toBe("ready")
    const row = (f: string) => d.confirmation!.rows.find((r) => r.field === f)!
    expect(row("constraints.max_weight_per_stock")).toMatchObject({ profile_value_ko: "30%", value_ko: "25%", changed: true, source: "answer" })
    expect(row("risk.max_drawdown_tolerance").value_ko).toBe("35%")
    expect(row("constraints.must_include_tickers").value_ko).toBe("엔비디아 (NVDA), 마이크론 테크놀로지 (MU)")
    expect(row("constraints.exclude_tickers").value_ko).toBe("테슬라 (TSLA)")
  })
  it("말로 보태기: 반영됨(바뀐 조건 전후) / 추가 확인 필요 / 반영되지 않음(기존 조건 유지)", async () => {
    const s = mock()
    await s.sendMessage("mock_req_ready", "테슬라도 꼭 넣어 주세요")
    await s.sendMessage("mock_req_ready", "담배 회사는 빼 주세요")
    await s.sendMessage("mock_req_ready", "좀 더 안전하게 해 주세요")
    const [a, b, c] = await s.getMessageResults("mock_req_ready")
    expect(a.outcome).toBe("applied")
    expect(a.changes.map((x) => x.label_ko)).toEqual(["꼭 넣을 종목", "뺄 종목"])
    expect(a.changes[1]).toMatchObject({ before_ko: "테슬라 (TSLA)", after_ko: "없음" })
    expect(b).toMatchObject({ outcome: "needs_confirmation", changes: [] })
    expect(c).toMatchObject({ outcome: "not_applied", changes: [] })
    expect((await s.getRequest("mock_req_ready")).confirmation!.rows.find((r) => r.field === "constraints.exclude_tickers")!.value_ko).toBe("없음")
  })
  it("0원 시작 프로필로 새 분석을 만들면 조건에 투자금 0원·매월 추가 투자금이 그대로 들어간다", async () => {
    const s = mock(); s.setProfileVariant("zero")
    const d = await s.createRequest({ idea: "반도체에 매달 적립식으로 투자하고 싶어요" })
    const v = (f: string) => d.conditions!.find((r) => r.field === f)!.value_ko
    expect(v("capital.initial_amount")).toBe("0원"); expect(v("capital.monthly_contribution")).toBe("1,000,000원")
  })
})

describe("내 투자조건 화면 (목업)", () => {
  it("회사 이름으로 찾아 반드시 포함할 종목에 추가하면 「회사명 (티커)」 칩이 생긴다", async () => {
    withSvc(mock(), <ProfileScreen mode="edit" />)
    await step(3, "종목 범위·제약")
    expect(await screen.findByText("엔비디아 (NVDA)")).toBeInTheDocument()
    const box = screen.getByRole("combobox", { name: "반드시 포함할 종목" })
    fireEvent.change(box, { target: { value: "마이크론" } })
    fireEvent.click(await screen.findByRole("option", { name: /마이크론 테크놀로지.*MU/ }))
    expect(await screen.findByText("마이크론 테크놀로지 (MU)")).toBeInTheDocument()
    fireEvent.change(box, { target: { value: "엔비" } })
    expect(await screen.findByRole("option", { name: /엔비디아.*추가됨/ })).toHaveAttribute("aria-disabled", "true")
    fireEvent.change(box, { target: { value: "xyzq" } })
    expect(await screen.findByText(/와 맞는 종목이 목업 목록에 없습니다/)).toBeInTheDocument()
  })
  it("실제 서버 응답 모양: 미국 종목은 영문 이름을 한 번만, 한국 종목은 영문 이름 없이, 못 찾으면 지원 종목 기준 안내", async () => {
    const US = { ticker: "MU", name_ko: "Micron Technology", name_en: "Micron Technology", market: "US" as const, sector_ko: "정보기술" }
    const KR = { ticker: "005930.KS", name_ko: "삼성전자", name_en: null, market: "KR" as const, sector_ko: "정보기술" }
    let hits = [US, KR]
    const svc: AnalysisService = Object.assign(Object.create(mock()), { mode: "api", searchStocks: async () => hits, getStocks: async (ts: string[]) => [US, KR].filter((x) => ts.includes(x.ticker)) })
    withSvc(svc, <ProfileScreen mode="edit" />)
    await step(3, "종목 범위·제약")
    const box = screen.getByRole("combobox", { name: "반드시 포함할 종목" })
    fireEvent.change(box, { target: { value: "m" } })
    const us = await screen.findByRole("option", { name: /Micron Technology.*MU/ })
    expect(us).toHaveTextContent("정보기술 · 미국"); expect(us.textContent!.match(/Micron Technology/g)).toHaveLength(1)
    const kr = screen.getByRole("option", { name: /삼성전자/ })
    expect(kr).toHaveTextContent("정보기술 · 한국"); expect(kr).not.toHaveTextContent("null")
    fireEvent.click(us)
    expect(await screen.findByText("Micron Technology (MU)")).toBeInTheDocument()
    hits = []
    fireEvent.change(box, { target: { value: "xyzq" } })
    expect(await screen.findByText(/와 맞는 종목이 지원 종목\(S&P 500·NASDAQ-100·KOSPI 200\)에 없습니다/)).toBeInTheDocument()
  })
  it("초기 투자금 0원: 매월 추가 투자금이 있으면 예상 투자 일정을 보여 주고, 없으면 다음 단계로 가지 않는다", async () => {
    withSvc(mock(), <ProfileScreen mode="edit" />)
    const amount = await screen.findByLabelText("처음 투자할 금액", {}, { timeout: 5000 })
    fireEvent.change(amount, { target: { value: "0" } })
    const plan = await screen.findByRole("note", { name: "예상 투자 일정" })
    expect(plan).toHaveTextContent("매월 25일에 50만원씩"); expect(plan).toHaveTextContent("1년 뒤 넣은 원금 600만원")
    fireEvent.change(screen.getByLabelText(/^매월 추가 투자금/, { selector: "input" }), { target: { value: "0" } })
    fireEvent.click(screen.getByRole("button", { name: "다음" }))
    expect((await screen.findAllByText("처음 투자금을 0원으로 하려면 매월 추가 투자금을 정해 주세요")).length).toBeGreaterThan(0)
    expect(screen.getByRole("button", { name: /^1단계 기본 조건 \(현재 단계\)/ })).toBeInTheDocument()
  })
  it("투자 전략 단계: 성향에 맞는 추천 전략·이유·다른 전략과의 차이, 적용하면 「지금 적용됨」, 직접 다른 전략도 고를 수 있다", async () => {
    withSvc(mock(), <ProfileScreen mode="edit" />)
    await step(4, "투자 전략")
    const card = (await screen.findByRole("heading", { name: "위험중립형에게 추천하는 전략" })).closest("section")!
    expect(within(card).getByText("수익성이 좋은 기업(퀄리티) · 모든 기업에 비슷하게 투자(동일비중) · 뉴스·공시 반영")).toBeInTheDocument()
    expect(within(card).getAllByText(/퀄리티/).length).toBeGreaterThan(1)  // 추천 전략 이름과 추천 이유 모두 같은 용어(괄호)
    expect(within(card).getByText(/지금은 추천과 다른 전략을 쓰고 있습니다/)).toBeInTheDocument()
    expect(screen.getAllByText("추천")).toHaveLength(2)  // 기업 고르는 기준·나누는 방식 카드
    fireEvent.click(within(card).getByRole("button", { name: "추천 전략 적용" }))
    expect(await within(card).findByText("지금 적용됨")).toBeInTheDocument()
    expect(screen.getByRole("radio", { name: /수익성이 좋은 기업/ })).toHaveAttribute("aria-checked", "true")
    fireEvent.click(screen.getByRole("radio", { name: /^주가 변동이 작은 기업\(저변동성\)최근/ }))
    expect(await within(card).findByRole("button", { name: "추천 전략 적용" })).toBeInTheDocument()
  })
  it("실제 서버 응답: 추천 카드가 일반 모드에서도 보이고, 「목업」 표시 없이 서버 안내 문장을 보여 준다", async () => {
    const m = mock()
    const asked: string[] = []
    const note = "투자성향마다 정해 둔 고정 규칙에 따른 추천입니다. 지금 시장 상황이나 과거 성과를 보고 고른 것은 아닙니다."
    const svc: AnalysisService = Object.assign(Object.create(m), { mode: "api", recommendStrategy: async (t: Parameters<MockService["recommendStrategy"]>[0]) => { asked.push(t); return { ...(await m.recommendStrategy(t)), note_ko: note } } })
    withSvc(svc, <ProfileScreen mode="edit" />)
    await step(4, "투자 전략")
    const card = (await screen.findByRole("heading", { name: "위험중립형에게 추천하는 전략" })).closest("section")!
    expect(asked).toContain("위험중립형")
    expect(within(card).getByText(new RegExp(note))).toBeInTheDocument()
    expect(screen.queryByText("목업")).toBeNull()
    expect(screen.getAllByText("추천")).toHaveLength(2)
  })
  it("변경 이력: 앞 버전과 비교하면 바뀐 항목만 강조하고, 그대로인 항목은 따로 접어 둔다", async () => {
    withSvc(mock(), <ProfileScreen mode="view" />)
    fireEvent.click(await screen.findByRole("button", { name: /변경 이력 보기/ }, { timeout: 5000 }))
    const changed = await screen.findByRole("list", { name: "바뀐 항목" })
    await waitFor(() => expect(changed).toHaveTextContent(/제외 종목.*없음.*→.*테슬라 \(TSLA\)/))  // 회사명은 따로 조회해 붙는다
    expect(within(changed).getByText("엔비디아 (NVDA)")).toBeInTheDocument()
    expect(within(changed).getByText("규모가 큰 기업에 더 많이 투자(시가총액비중)")).toBeInTheDocument()
    expect(screen.getByRole("button", { name: /바뀌지 않은 항목 \d+개/ })).toBeInTheDocument()
    fireEvent.click(screen.getByRole("button", { name: "버전 2을 앞 버전과 비교" }))
    await waitFor(() => expect(screen.getByRole("list", { name: "바뀐 항목" })).toHaveTextContent(/처음 투자할 금액.*1,000만원.*2,000만원/))
  })
})

describe("새 분석 · 조건 확인 화면 (목업)", () => {
  it("여러 질문 한 번에: 필수 질문을 비우면 표시하고, 보내면 답변 요약과 반영된 조건을 보여 준 뒤 확인 화면으로 간다", async () => {
    withSvc(mock(), <ClarifyScreen requestId="mock_req_asking" />)
    const send = await screen.findByRole("button", { name: "답변 3개 한 번에 보내기" }, { timeout: 5000 })
    expect(screen.getByRole("radio", { name: "마이크론 테크놀로지 (MU)" })).toBeInTheDocument()  // 보기에도 회사명 (티커)
    fireEvent.click(send)
    expect(await screen.findAllByText("필수 질문입니다. 보기를 고르거나 답을 적어 주세요.")).toHaveLength(2)
    fireEvent.click(screen.getByRole("radio", { name: "25%" }))
    fireEvent.click(screen.getByRole("radio", { name: "35%까지" }))
    fireEvent.click(send)
    const res = (await screen.findByRole("heading", { name: "보낸 답변과 반영 결과" })).closest("section")!
    expect(res).toHaveTextContent("종목당 최대 비중: 30% → 25%")
    expect(res).toHaveTextContent("손실 감내 수준: 30% → 35%")
    expect(res).toHaveTextContent("기본 투자조건을 그대로 씁니다.")  // 비워 둔 선택 질문
    expect(screen.queryByText("지금까지 답한 내용")).toBeNull()  // 반영 결과와 겹치는 카드는 숨긴다
    fireEvent.click(within(res).getByRole("button", { name: /조건 최종 확인으로/ }))
    await waitFor(() => expect(window.location.hash).toBe("#/analysis/mock_req_asking/confirm"))
  })
  it("말로 보태기: 처리 결과(반영됨·추가 확인 필요·반영되지 않음)와 이전 요청 기록", async () => {
    withSvc(mock(), <ConfirmScreen requestId="mock_req_ready" />)
    const box = await screen.findByRole("textbox", { name: "말로 조건 보태기" }, { timeout: 5000 })
    const send = () => fireEvent.click(screen.getByRole("button", { name: "말로 보태기" }))
    fireEvent.change(box, { target: { value: "테슬라도 꼭 넣어 주세요" } }); send()
    expect(await screen.findByText("조건에 반영됨")).toBeInTheDocument()
    expect(screen.getByText(/뺄 종목: 테슬라 \(TSLA\) →/)).toBeInTheDocument()
    fireEvent.change(box, { target: { value: "담배 회사는 빼 주세요" } }); send()
    expect(await screen.findByText("추가 확인 필요")).toBeInTheDocument()
    fireEvent.change(box, { target: { value: "좀 더 안전하게 해 주세요" } }); send()
    expect(await screen.findByText("반영되지 않음")).toBeInTheDocument()
    expect(screen.getByText("바뀐 조건이 없습니다.")).toBeInTheDocument()  // 서버 안내(note_ko)가 있으면 「그대로 유지」를 두 번 말하지 않는다
    expect(screen.getAllByText(/기존 조건이 그대로 유지됩니다/)).toHaveLength(1)
    expect(screen.getByRole("button", { name: /이전에 보낸 요청 2개/ })).toBeInTheDocument()
  })
})

describe("일반 모드 (제안 메서드 없음)", () => {
  it("내 투자조건은 지금처럼 티커 입력·직접 고르기·0원 불가", async () => {
    withSvc(plain(mock()), <ProfileScreen mode="edit" />)
    fireEvent.change(await screen.findByLabelText("처음 투자할 금액", {}, { timeout: 5000 }), { target: { value: "0" } })
    expect(screen.queryByRole("note", { name: "예상 투자 일정" })).toBeNull()
    fireEvent.click(screen.getByRole("button", { name: "다음" }))
    expect((await screen.findAllByText("투자금은 0보다 커야 합니다")).length).toBeGreaterThan(0)
    await step(3, "종목 범위·제약")
    expect(screen.queryByRole("combobox")).toBeNull()
    expect(screen.getByText("NVDA")).toBeInTheDocument()
    await step(4, "투자 전략")
    expect(screen.queryByText(/추천하는 전략/)).toBeNull()
    expect(screen.queryByText("추천")).toBeNull()
  })
  it("질문은 하나씩, 말로 보태기는 기존 결과 안내", async () => {
    withSvc(plain(mock()), <ClarifyScreen requestId="mock_req_asking" />)
    expect(await screen.findByRole("button", { name: "답변 보내기" }, { timeout: 5000 })).toBeInTheDocument()
    expect(screen.queryByRole("button", { name: /한 번에 보내기/ })).toBeNull()
  })
})

describe("최종 확인 화면은 「지금까지 답한 내용」을 그대로 보여 준다", () => {
  it("목업에서 한 번에 답한 뒤에도 확인 화면에는 답한 내용 카드가 있다", async () => {
    const svc = mock()
    const q = (await svc.getQuestionBatch!("mock_req_asking"))!.questions
    await svc.answerBatch!("mock_req_asking", q.map((x) => (x.required ? { seq: x.seq, option_value: x.options[0].value } : { seq: x.seq, skip: true })))
    withSvc(svc, <ConfirmScreen requestId="mock_req_asking" />)
    expect(await screen.findByText("지금까지 답한 내용", {}, { timeout: 5000 })).toBeInTheDocument()
  })
})
