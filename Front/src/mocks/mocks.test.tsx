import { afterEach, beforeAll, describe, expect, it, vi } from "vitest"
import { render, screen } from "@testing-library/react"
import { createServiceAsync, HttpService, type AnalysisService } from "../api/service"
import { fetchJson } from "../api/client"
import { PROPOSED_METHODS, proposedOf, type ProposedApi } from "../api/proposed"
import { normalizeDoc } from "../lib/reportNormalize"
import { Providers } from "../app/providers"
import App from "../app/App"
import { isMockMode } from "./mode"
import { MockService } from "./services/MockService"
import { MOCK_STORE_KEY } from "./services/store"
import { PAPERS, REPORTS } from "./scenarios"
import { buildReport } from "./data/report"

// 1단계 검증: 목업 모드 분리(기본은 일반 모드, 목업은 네트워크를 쓰지 않음)와 목업 자료의 일관성.

const setUrl = (u: string) => window.history.replaceState(null, "", u)
const mock = () => new MockService({ latencyMs: 0, persist: false })
afterEach(() => { setUrl("/"); vi.restoreAllMocks(); window.sessionStorage.clear(); window.localStorage.clear() })
beforeAll(() => { globalThis.ResizeObserver ??= class { observe() {} unobserve() {} disconnect() {} } as unknown as typeof ResizeObserver; Element.prototype.scrollIntoView = vi.fn() })

describe("목업 모드 분리", () => {
  it("기본은 일반 모드이고, 개발 환경에서 ?mock=1 일 때만 목업 모드다", async () => {
    setUrl("/#/home")
    expect(isMockMode()).toBe(false)
    expect((await createServiceAsync()).mode).toBe("api")
    setUrl("/?mock=1#/reports/x")
    expect(isMockMode()).toBe(true)
    setUrl("/?mock=0#/home")
    expect(isMockMode()).toBe(false)
  })
  it("제안 계약 메서드: 목업 서비스는 전부 가지고, 실제 서버 서비스는 서버가 구현한 것(CONNECTED)만 가진다", () => {
    const http: AnalysisService = new HttpService(), m = mock()
    // 실제 서버에 연결된 제안 메서드. 묶음(이슈 #14)마다 자기 주석 아래에만 이름을 더한다 — 주석 줄이 사이에 있어 묶음 브랜치끼리 충돌하지 않는다
    const CONNECTED: (keyof ProposedApi)[] = [
      // 리포트 이름·삭제
      "getReportName", "renameReport", "deleteReport",
      // A 종목 이름
      // B 투자조건 규칙
      "recommendStrategy",
      "startProfileChat", "answerProfileChat", "rewindProfileChat",
      // C 질문 화면
      // D 분석 진행
      // E 원화 계산
      // F 변경 이력·모의투자 이름
    ]
    for (const name of PROPOSED_METHODS) {
      expect(typeof m[name], name).toBe("function")
      expect(typeof http[name], name).toBe(CONNECTED.includes(name) ? "function" : "undefined")
    }
  })
  it("리포트 이름·삭제는 서버 주소로 요청한다", async () => {
    const f = vi.spyOn(globalThis, "fetch").mockImplementation(async () => new Response(JSON.stringify({ report_id: "r1", deleted: true }), { status: 200 }))
    const http = new HttpService()
    await http.getReportName("r1"); await http.renameReport("r1", "새 이름"); await http.deleteReport("r1")
    const calls = f.mock.calls.map(([u, i]) => [String(u).replace(/^.*\/api\/v1/, ""), i?.method, i?.body])
    expect(calls).toEqual([["/reports/r1/name", "GET", undefined], ["/reports/r1/name", "PUT", JSON.stringify({ name: "새 이름" })], ["/reports/r1", "DELETE", undefined]])
  })
  it("목업 모드에서는 서버 요청 함수가 요청을 보내지 않고 막는다", async () => {
    const f = vi.spyOn(globalThis, "fetch")
    setUrl("/?mock=1#/home")
    await expect(fetchJson("/reports")).rejects.toMatchObject({ code: "MOCK_NETWORK_BLOCKED" })
    expect(f).not.toHaveBeenCalled()
  })
  it("목업 서비스는 어떤 메서드도 네트워크를 쓰지 않고, 바뀐 상태는 목업 전용 sessionStorage 에만 둔다", async () => {
    const f = vi.spyOn(globalThis, "fetch")
    const s = new MockService({ latencyMs: 0, persist: true })
    await s.health(); await s.options(); await s.getProfile(); await s.listReports(); await s.listRuns(); await s.listRequests(); await s.listPaper()
    for (const r of REPORTS) { await s.getReport(r.id); await s.getRun(r.run_id) }
    await s.renameReport!("mock_rep_normal", "내 반도체 리포트")
    await s.getReportCheckpoint("mock_rep_normal", 1); await s.getReportEvidence("mock_rep_normal", { kind: "news" }); await s.getReportComparison("mock_rep_revised")
    await s.getPaper("mock_paper_a1"); await s.getPaperKrw!("mock_paper_a1"); await s.searchStocks!("삼성")
    expect(f).not.toHaveBeenCalled()
    expect(window.sessionStorage.getItem(MOCK_STORE_KEY)).toContain("내 반도체 리포트")
    expect(window.localStorage.getItem("myfinsight.ui.v1")).toBeNull()  // 일반 모드의 화면 상태 키는 건드리지 않는다
  })
  it("성향 기반 추천은 서버 주소로 요청한다 (한글 성향은 인코딩)", async () => {
    const f = vi.spyOn(globalThis, "fetch").mockImplementation(async () => new Response("{}", { status: 200 }))
    await new HttpService().recommendStrategy("위험중립형")
    expect(f.mock.calls.map(([u, i]) => [String(u).replace(/^.*\/api\/v1/, ""), i?.method])).toEqual([[`/strategy/recommendation?tendency=${encodeURIComponent("위험중립형")}`, "GET"]])
  })
  it("대화형 초기 투자조건은 서버 주소로 요청한다 (시작 / 답 / 되감기)", async () => {
    const f = vi.spyOn(globalThis, "fetch").mockImplementation(async () => new Response("{}", { status: 200 }))
    const http = new HttpService()
    await http.startProfileChat(); await http.answerProfileChat("chat_1", { question_id: "amount", number: 5_000_000 }); await http.rewindProfileChat("chat_1", "amount")
    const calls = f.mock.calls.map(([u, i]) => [String(u).replace(/^.*\/api\/v1/, ""), i?.method, i?.body])
    expect(calls).toEqual([["/profile/chat", "POST", undefined], ["/profile/chat/chat_1/answers", "POST", JSON.stringify({ question_id: "amount", number: 5_000_000 })],
      ["/profile/chat/chat_1/rewind", "POST", JSON.stringify({ question_id: "amount" })]])
  })
})

describe("목업 시나리오 결과", () => {
  it("정상 추천 · 주의 · 추천안 없음 · 뉴스 꺼짐(상한 없음) · 이전 형식 · 수정안이 의도대로 나온다", async () => {
    const s = mock()
    const st = async (id: string) => (await s.getReport(id)).summary?.verdict.status
    expect(await st("mock_rep_normal")).toBe("recommended")
    expect(await st("mock_rep_caution")).toBe("recommended_warn")
    expect(await st("mock_rep_none")).toBe("insufficient")
    expect(await st("mock_rep_newsoff")).toBe("recommended")
    const off = await s.getReport("mock_rep_newsoff")
    expect(off.summary?.news_effect?.disabled).toBe(true)
    expect(proposedOf(off)?.structured?.checks.find((c) => c.rule === "R7")?.basis).toBe("no_cap")
    const legacy = await s.getReport("mock_rep_legacy")
    expect(legacy.doc_version).toBe(1); expect(legacy.summary).toBeUndefined()
    expect(normalizeDoc(legacy).summary?.verdict.status).toBe("recommended")  // 이전 형식도 화면 변환기로 요약이 만들어진다
    expect(await s.getReportComparison("mock_rep_revised")).toMatchObject({ base_report_id: "mock_rep_normal", revised_report_id: "mock_rep_revised" })
    expect((await s.getReport("mock_rep_caution")).summary?.period).toMatchObject({ annualized_reliable: false })  // 짧은 기간(1년)
  })
})

describe("목업 자료의 일관성 (같은 값이 화면마다 같다)", () => {
  for (const sc of REPORTS.filter((r) => r.doc_version === 2)) {
    it(`${sc.label_ko}: 요약·표·문장·리밸런싱·실행 예상이 같은 계산에서 나온다`, () => {
      const d = buildReport(sc), sm = d.summary!, p = proposedOf(d)!
      const chosenId = sm.verdict.chosen_portfolio_id
      const short = sm.period && "annualized_reliable" in sm.period && sm.period.annualized_reliable === false
      // KPI ↔ 비교표 ↔ 판단 이유
      const cmp = d.sections.flatMap((x) => x.blocks).find((b) => b.type === "table" && b.title_ko?.startsWith("포트폴리오 비교"))
      const row = cmp && cmp.type === "table" ? cmp.rows.find((r) => r.name === sm.verdict.chosen_label_ko)! : null
      expect(row).toBeTruthy()
      const kCagr = sm.kpis.find((k) => k.id === "cagr")!
      expect(kCagr.value).toBeCloseTo(short ? p.structured!.annualized.strategy_total_return : (row!.cagr as number), 10)
      expect(sm.kpis.find((k) => k.id === "mdd")!.value).toBeCloseTo(row!.mdd as number, 10)
      const r3 = sm.validation.rules_ko!.find((r) => r.rule === "R3")!.message_ko
      expect(sm.verdict.reason_ko).toContain(r3)  // 판단 이유와 검증 문장의 숫자가 같다
      // 최종 평가금액 ↔ 리밸런싱 마지막 시점
      const tl = d.sections.flatMap((x) => x.blocks).find((b) => b.type === "timeline")
      if (tl && tl.type === "timeline") expect(tl.items[tl.items.length - 1].value_usd).toBeCloseTo(sm.kpis.find((k) => k.id === "final_value")!.value!, 1)
      // 기업 카드의 비중 = 선택 전략 비중
      const comp = d.sections.flatMap((x) => x.blocks).find((b) => b.type === "companies")
      if (comp && comp.type === "companies") for (const c of comp.items) expect(c.weight).toBeCloseTo(p.chosen_vs_baseline!.rows.find((r) => r.ticker === c.ticker)!.chosen, 10)
      // 요약 배분: 원화 = USD × 환율, 합계 = 투자금 × (1 − 현금)
      const a = sm.allocation!
      for (const it of a.items) expect(Math.abs(it.krw - it.usd * a.fx_rate)).toBeLessThan(a.fx_rate)
      expect(a.items.reduce((s, x) => s + x.usd, 0)).toBeCloseTo(a.initial_amount_usd * (1 - a.cash_weight), -1)
      // 실행 예상: 정수 주식, 매수금 + 수수료 + 남는 현금 = 투자금
      const e = p.execution!
      expect(e.share_basis).toBe("integer")
      for (const it of e.items) { expect(Number.isInteger(it.shares)).toBe(true); expect(it.cost_usd).toBeCloseTo(it.shares * it.price_usd, 1) }
      expect(e.totals.invested_usd + e.totals.fee_usd + e.totals.cash_left_usd).toBeCloseTo(e.capital.usd, 1)
      expect(e.totals.cash_left_usd).toBeGreaterThanOrEqual(0)
      expect(p.allocations!.recommended_now.strategy_id).toBe(chosenId)
      // 원화 확장: 시점별 원화 = USD × 그날 환율
      const series = d.datasets.series[chosenId].value_usd!
      p.krw!.value_krw.forEach((v, i) => expect(Math.abs(v - series[i] * p.krw!.fx_rates[i])).toBeLessThan(p.krw!.fx_rates[i]))
    })
  }
})

describe("목업 모의투자와 이름", () => {
  it("같은 리포트에서 시작한 모의투자 3개는 전략·시작일·투자금으로 구분되고, 원화 성과는 원화 흐름으로 계산한다", async () => {
    const s = mock()
    const list = await s.listPaper()
    const same = list.filter((p) => p.report_id === "mock_rep_normal")
    expect(same).toHaveLength(3)
    expect(new Set(same.map((p) => `${p.strategy?.id}|${p.start_date}|${p.initial_capital.amount}`)).size).toBe(3)
    const krw = (await s.getPaperKrw!("mock_paper_a1"))!
    const d = await s.getPaper("mock_paper_a1")
    expect(krw.fx.filter((f) => f.status === "carried").map((f) => f.date)).toEqual(PAPERS[0].fx_gaps.filter((g) => d.series.dates.includes(g)))
    krw.value_krw.forEach((v, i) => { if (v !== null) expect(Math.abs(v - d.snapshots[i].value_usd * krw.fx[i].rate!)).toBeLessThan(krw.fx[i].rate!) })
    const months = new Set(d.series.dates.slice(1).filter((x, i) => x.slice(0, 7) !== d.series.dates[i].slice(0, 7)).map((x) => x.slice(0, 7))).size
    expect(krw.contributions_krw_total).toBe(10_000_000 + 300_000 * months)  // 원화 납입액 그대로
    expect(krw.return_krw).toBeCloseTo(krw.value_krw[krw.value_krw.length - 1]! / krw.contributions_krw_total! - 1, 10)
    const usdOnly = (await s.getPaperKrw!("mock_paper_a3"))!
    expect(usdOnly.fx[0]).toMatchObject({ status: "missing", rate: null })  // 환율이 없는 날은 환산 불가
    expect(usdOnly.value_krw[0]).toBeNull()
  })
  it("리포트 이름을 바꾸면 연동된 모의투자 이름은 따라가고, 직접 지정한 이름은 그대로다. 되돌리면 자동 이름", async () => {
    const s = mock()
    expect((await s.getReportName!("mock_rep_normal")).display_ko).toBe("미국 반도체 장비·메모리 분산 투자")
    await s.renameReport!("mock_rep_normal", "  나의 반도체 포트폴리오  ")
    const names = Object.fromEntries((await s.listPaper()).map((p) => [p.paper_id, p.name_ko]))
    expect(names.mock_paper_a1).toBe("나의 반도체 포트폴리오")
    expect(names.mock_paper_a2).toBe("시가총액 비중 비교용")
    await s.setPaperName!("mock_paper_a2", { mode: "linked" })
    expect((await s.getPaperName!("mock_paper_a2")).name_ko).toBe("나의 반도체 포트폴리오")
    expect((await s.renameReport!("mock_rep_normal", null)).display_ko).toBe("미국 반도체 장비·메모리 분산 투자")
  })
  it("투자조건: 변경 이력은 버전마다 값 전체가 있고, 0원 시나리오는 목업에서만 허용된다", async () => {
    const s = mock()
    const v1 = await s.getProfileVersion!(1), v4 = await s.getProfileVersion!(4)
    expect(v1.capital.initial_amount).toBe(10_000_000); expect(v4.constraints.must_include_tickers).toEqual(["NVDA"])
    s.setProfileVariant("zero")
    expect((await s.getProfile())!.profile.capital).toMatchObject({ initial_amount: 0, monthly_contribution: 1_000_000 })
    expect((await s.searchStocks!("하이닉스")).map((x) => x.ticker)).toEqual(["000660"])
  })
  it("여러 질문 한 번에 답하면 조건 확인 단계로 넘어간다", async () => {
    const s = mock()
    const b = (await s.getQuestionBatch!("mock_req_asking"))!
    expect(b.questions).toHaveLength(3)
    const d = await s.answerBatch!("mock_req_asking", b.questions.map((q) => ({ seq: q.seq, option_value: q.options[0].value })))
    expect(d.state).toBe("ready")
    expect((await s.getRunWarnings!("mock_run_notices")).find((w) => w.count === 2)).toBeTruthy()  // 같은 경고는 한 줄로 묶는다
  })
})

describe("목업 모드 화면", () => {
  it("모든 화면 위에 목업 안내 띠가 있고, 목업 리포트가 서버 요청 없이 열린다", async () => {
    const f = vi.spyOn(globalThis, "fetch")
    setUrl("/?mock=1#/reports/mock_rep_normal")
    render(<Providers service={mock()}><App /></Providers>)
    expect(await screen.findByText("목업 데이터 화면입니다 · 실제 투자 분석 결과가 아닙니다.", {}, { timeout: 5000 })).toBeInTheDocument()  // 띠는 지연 로딩
    expect(await screen.findByRole("heading", { level: 1, name: REPORTS[0].auto_name_ko }, { timeout: 5000 })).toBeInTheDocument()  // 3단계부터 목업 제목은 리포트 이름 (자동 이름)
    expect(screen.getAllByText(/^\[목업\]/).length).toBeGreaterThan(0)
    expect(f).not.toHaveBeenCalled()
  }, 15000)  // 앱 전체를 그리고(지연 로딩 화면 포함) 리포트·목록을 함께 읽어 병렬 실행 중에는 5초를 넘길 수 있다
  it("일반 모드에서는 목업 띠가 없다", async () => {
    setUrl("/#/reports/x")
    render(<Providers service={mock()}><App /></Providers>)  // 띠는 주소(?mock=1)로만 정해진다
    await new Promise((r) => setTimeout(r, 50))
    expect(screen.queryByText(/목업 데이터 화면입니다/)).toBeNull()
  })
})

// 새 요청: 실제 서버처럼 번호를 먼저 주고(interpreting) 지연 ×50 동안 해석 중(지난 만큼 6단계가 나아감), 지나면 질문. 목업 상태가 sessionStorage 에 있어 새로고침해도 이어진다.
describe("목업 새 요청: 번호를 먼저 주고 뒤에서 해석", () => {
  const IDEA = "미국 대형 기술주에 나눠 투자하고 싶어요"
  it("정한 시각까지는 해석 중(질문·조건 없음), 지나면 질문 중 대화가 된다", async () => {
    const c = { now: 1_000_000 }
    const s = new MockService({ latencyMs: 1, persist: false, clock: () => c.now })  // 해석 중 = 50ms (시계로만 판정)
    const st = await s.createRequest({ idea: IDEA })
    expect(st).toMatchObject({ state: "interpreting", question: null, questions: [], conditions: [] })
    expect(st.progress?.map((p) => p.status)).toEqual(["running", "waiting", "waiting", "waiting", "waiting", "waiting"])
    c.now += 25  // 절반: 3단계가 끝나고 후보 분류가 진행 중
    const mid = await s.getRequest(st.request_id)
    expect(mid.state).toBe("interpreting")
    expect(mid.progress?.map((p) => p.status)).toEqual(["done", "done", "done", "running", "waiting", "waiting"])
    expect(mid.progress?.[1].detail_ko).toMatch(/^테마 /)
    expect(mid.progress?.[3]).toMatchObject({ key: "classify", detail_ko: "1/2 묶음" })
    c.now += 25
    const after = await s.getRequest(st.request_id)
    expect(after.state).toBe("asking")
    expect(after.question).not.toBeNull()
  })
  it("지연 0(테스트)이면 바로 질문 중이다 (기존 동작)", async () => {
    expect((await mock().createRequest({ idea: IDEA })).state).toBe("asking")
  })
  it("해석 중에 새로고침해도(목업 상태를 다시 읽어도) 이어진다", async () => {
    const c = { now: 1_000_000 }
    const st = await new MockService({ latencyMs: 1, clock: () => c.now }).createRequest({ idea: IDEA })  // persist 기본값: sessionStorage
    const reloaded = new MockService({ latencyMs: 1, clock: () => c.now })
    expect((await reloaded.getRequest(st.request_id)).state).toBe("interpreting")
    c.now += 50
    expect((await reloaded.getRequest(st.request_id)).state).toBe("asking")
  })
  it("재분석·수정 요청은 실제 서버처럼 해석까지 끝낸 뒤 돌려준다", async () => {
    const s = new MockService({ latencyMs: 1, persist: false })
    expect((await s.rerun(REPORTS[0].id)).state).toBe("asking")
    expect((await s.createRevision(REPORTS[0].id, "엔비디아는 빼 주세요")).state).toBe("asking")
  })
  it("패널의 고정 요청: 계속 해석 중 / 해석 실패(이유 포함)", async () => {
    const s = mock()
    expect((await s.getRequest("mock_req_interpreting")).state).toBe("interpreting")
    const f = await s.getRequest("mock_req_failed")
    expect(f.state).toBe("failed")
    expect(f.error_ko).toMatch(/응답 형식이 맞지 않습니다/)
    expect(f.progress?.slice(0, 3).map((p) => p.status)).toEqual(["done", "running", "waiting"])  // 아이디어 해석에서 멈춤
  })
})
