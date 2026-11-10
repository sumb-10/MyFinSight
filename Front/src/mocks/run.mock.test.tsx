import { afterEach, beforeAll, describe, expect, it, vi } from "vitest"
import { fireEvent, render, screen, waitFor, within } from "@testing-library/react"
import { Providers } from "../app/providers"
import type { AnalysisService } from "../api/service"
import { proposedCancelOf } from "../api/proposed"
import { RunScreen } from "../features/run/RunScreen"
import { HomeScreen } from "../features/home/HomeScreen"
import { PaperScreen } from "../features/paper/PaperScreen"
import { CANCEL_MS, LIVE_QUEUE_MS, LIVE_STEP_MS, STEPS } from "./data/runs"
import { MockService } from "./services/MockService"

// 5단계: 분석 진행(즉시 취소·경고 전체·상태별 시나리오와 이벤트 시퀀스)과 모의투자(원화 기준 성과·환율 대체 여부·이름 연동).

beforeAll(() => { globalThis.ResizeObserver ??= class { observe() {} unobserve() {} disconnect() {} } as unknown as typeof ResizeObserver; Element.prototype.scrollIntoView = vi.fn() })
afterEach(() => window.history.replaceState(null, "", "/"))

const T0 = Date.parse("2026-11-05T09:00:00Z")
const clocked = () => { const c = { now: T0 }; return { c, s: new MockService({ latencyMs: 0, persist: false, clock: () => c.now }) } }
const withSvc = (svc: AnalysisService, ui: React.ReactNode) => { window.history.replaceState(null, "", "/?mock=1"); return render(<Providers service={svc}>{ui}</Providers>) }
const plain = (s: MockService): AnalysisService => Object.assign(Object.create(s), { mode: "api", getRunWarnings: undefined, getPaperKrw: undefined, getPaperName: undefined, setPaperName: undefined })

describe("분석 진행 (목업 서비스)", () => {
  it("이벤트 시퀀스: 대기 → 단계 진행(확인할 점이 차례로) → 완료, 완료 리포트는 정상 추천 리포트", async () => {
    const { c, s } = clocked()
    const id = s.startLiveRun("success")
    expect((await s.getRun(id)).status).toBe("queued")
    c.now = T0 + LIVE_QUEUE_MS + 5 * LIVE_STEP_MS + 10
    const mid = await s.getRun(id)
    expect(mid.status).toBe("running")
    expect(mid.steps.filter((x) => x.status === "SUCCESS")).toHaveLength(5)
    expect(mid.steps[5].status).toBe("STARTED")
    expect((await s.getRunWarnings(id)).map((w) => w.step)).toEqual(["01_request", "03_candidates", "03_candidates", "03_candidates", "05_selection"])
    c.now = T0 + LIVE_QUEUE_MS + STEPS.length * LIVE_STEP_MS + 10
    const end = await s.getRun(id)
    expect(end).toMatchObject({ status: "success", report_id: "mock_rep_normal" })
    const ws = await s.getRunWarnings(id)
    expect(ws.reduce((a, w) => a + w.count, 0)).toBe(9)
    expect(ws.find((w) => w.step === "05_selection")!.count).toBe(2)  // 같은 단계의 같은 문구는 하나로, 횟수 2
  })
  it("실패 시퀀스는 백테스트 단계에서 실패한다", async () => {
    const { c, s } = clocked()
    const id = s.startLiveRun("failed")
    c.now = T0 + LIVE_QUEUE_MS + STEPS.length * LIVE_STEP_MS
    const r = await s.getRun(id)
    expect(r.status).toBe("failed"); expect(r.error?.step).toBe("11_backtest")
  })
  it("즉시 취소: 누른 시각에 진행이 멈추고 「취소 처리 중」 → 「취소됨」, 완료된 단계는 그대로. 끝난 분석은 다시 취소할 수 없고, 다시 실행은 새 실행", async () => {
    const { c, s } = clocked()
    const id = s.startLiveRun("success")
    c.now = T0 + LIVE_QUEUE_MS + 4 * LIVE_STEP_MS + 10
    const r1 = await s.cancelRun(id)
    expect(r1.status).toBe("cancelling")
    expect(proposedCancelOf(r1)).toMatchObject({ completed_at: null, stopped_step: "05_selection", done_steps: 4, immediate: true })
    c.now += 10 * LIVE_STEP_MS  // 시간이 지나도 진행하지 않는다
    const r2 = await s.getRun(id)
    expect(r2.status).toBe("cancelled")
    expect(r2.steps.filter((x) => x.status === "SUCCESS")).toHaveLength(4)
    expect(r2.steps[4].status).toBe("CANCELLED")
    expect(proposedCancelOf(r2)!.completed_at).not.toBeNull()
    await expect(s.cancelRun(id)).rejects.toMatchObject({ status: 409 })
    const again = await s.retryRun(id)
    expect(again.run_id).not.toBe(id); expect(again.status).toBe("queued")
  })
  it("정해진 진행 상태(분석 진행 중)도 같은 방식으로 취소되고, 조건 확인의 「분석 시작」은 시퀀스 실행을 만든다", async () => {
    const { c, s } = clocked()
    expect((await s.cancelRun("mock_run_running")).status).toBe("cancelling")
    c.now += CANCEL_MS
    expect((await s.getRun("mock_run_running")).status).toBe("cancelled")
    const { run_id } = await s.confirm("mock_req_ready")
    expect(run_id).toMatch(/^mock_run_live_/)
    expect((await s.getRequest("mock_req_ready")).run_id).toBe(run_id)
  })
})

describe("분석 진행 화면 (목업)", () => {
  it("경고 전체: 개수·관련 단계·같은 안내 횟수, 단계 요약에 빠진 안내까지 보이고 많으면 「더 보기」", async () => {
    const { s } = clocked()
    withSvc(s, <RunScreen runId="mock_run_notices" />)
    const card = (await screen.findByRole("heading", { name: /확인할 점 7건/ }, { timeout: 5000 })).closest("section")!
    expect(within(card).getByText("[목업] 제외 종목 TSLA 는 후보에서 뺐습니다.")).toBeInTheDocument()  // 요약에는 없던 세 번째 안내
    expect(within(card).getByText("같은 안내 2번")).toBeInTheDocument()
    expect(within(card).queryByText(/뉴스 근거가 부족한 시점/)).toBeNull()
    fireEvent.click(within(card).getByRole("button", { name: "나머지 2건 더 보기" }))
    const news = within(card).getByText(/뉴스 근거가 부족한 시점/).closest("li")!
    expect(news).toHaveTextContent(/관련 단계: .+ · .+/)
    expect(news).toHaveTextContent("같은 안내 2번")
    expect(within(card).queryByText(/내용이 표시되지 않은 안내/)).toBeNull()
  })
  it("취소: 확인 → 「취소 처리 중」 → 「분석이 취소되었습니다」, 취소 요청·완료 시각과 멈춘 단계, 다시 실행 버튼", async () => {
    const { c, s } = clocked()
    const id = s.startLiveRun("success")
    c.now = T0 + LIVE_QUEUE_MS + 4 * LIVE_STEP_MS + 10
    withSvc(s, <RunScreen runId={id} />)
    fireEvent.click(await screen.findByRole("button", { name: "분석 취소" }, { timeout: 5000 }))
    fireEvent.click(screen.getByRole("button", { name: "취소 확정" }))
    expect(await screen.findByText("취소를 처리하고 있습니다.")).toBeInTheDocument()
    expect(screen.queryByRole("button", { name: "분석 취소" })).toBeNull()
    c.now += CANCEL_MS
    expect(await screen.findByRole("heading", { level: 1, name: "분석이 취소되었습니다" }, { timeout: 4000 })).toBeInTheDocument()
    expect(screen.getByText("분석 취소 완료")).toBeInTheDocument()
    expect(screen.getByText(/단계에서 멈췄습니다. 완료된 4단계의 결과로는 리포트를 만들지 않았습니다/)).toBeInTheDocument()
    expect(screen.getByRole("button", { name: "멈춘 곳부터 이어서 실행" })).toBeEnabled()
  }, 10000)
  it("실제 서버 응답 모양(cancel, immediate=true): 취소 중에는 「○○ 단계를 바로 멈추고 있습니다」, 취소 뒤에는 요청·완료 시각과 멈춘 단계 (목업 표시 없음)", async () => {
    const s = new MockService({ latencyMs: 0, persist: false })
    const base = await s.getRun("mock_run_running")
    const at = base.steps.find((x) => x.status === "STARTED")!
    const cancel = { requested_at: "2026-11-10T09:00:00+09:00", completed_at: null as string | null, stopped_step: at.step, stopped_step_label_ko: at.label_ko, done_steps: 4, immediate: true }
    let run = { ...base, status: "cancelling", cancel } as typeof base
    const svc: AnalysisService = Object.assign(Object.create(s), { mode: "api", getRunWarnings: undefined, getRun: async () => run })
    const { unmount } = withSvc(svc, <RunScreen runId="mock_run_running" />)
    expect(await screen.findByText("취소를 처리하고 있습니다.", {}, { timeout: 5000 })).toBeInTheDocument()
    expect(screen.getByText(/단계를 바로 멈추고 있습니다. 잠시 뒤 이 화면이 「분석이 취소되었습니다」로 바뀝니다.$/)).toBeInTheDocument()  // 「(목업: 즉시 취소)」 꼬리 없음
    unmount()
    run = { ...base, status: "cancelled", finished_at: "2026-11-10T09:00:07+09:00", steps: base.steps.map((x) => (x.status === "STARTED" || x.status === "QUEUED" ? { ...x, status: "CANCELLED" } : x)),
      cancel: { ...cancel, completed_at: "2026-11-10T09:00:07+09:00" } } as typeof base  // fmt: skip
    withSvc(svc, <RunScreen runId="mock_run_running" />)
    expect(await screen.findByText("분석 취소 완료", {}, { timeout: 5000 })).toBeInTheDocument()
    expect(screen.getByText(/(7초 걸림)/)).toBeInTheDocument()
    expect(screen.getByText(new RegExp(`단계에서 멈췄습니다. 완료된 4단계의 결과로는 리포트를 만들지 않았습니다`))).toBeInTheDocument()
    expect(screen.queryByText("목업")).toBeNull()
  })
  it("일반 모드(전체 경고 목록 없음): 지금처럼 단계 요약의 안내만, 빠진 안내는 건수로 안내하고 「더 보기」가 없다", async () => {
    const { s } = clocked()
    withSvc(plain(s), <RunScreen runId="mock_run_notices" />)
    const card = (await screen.findByRole("heading", { name: /확인할 점 \d+건/ }, { timeout: 5000 })).closest("section")!
    expect(within(card).queryByText("[목업] 제외 종목 TSLA 는 후보에서 뺐습니다.")).toBeNull()
    expect(within(card).getByText(/내용이 표시되지 않은 안내 1건/)).toBeInTheDocument()
    expect(within(card).queryByRole("button", { name: /더 보기/ })).toBeNull()
    expect(within(card).queryByText(/같은 안내/)).toBeNull()
  })
})

describe("모의투자 원화 기준 성과 (목업)", () => {
  it("원화 수익률은 원화 금액 흐름으로 계산되고, USD(같은 방식)와의 차이는 환율 변화 효과다", async () => {
    const { s } = clocked()
    const k = (await s.getPaperKrw("mock_paper_a2"))!  // 원화 500만원, 적립 없음
    expect(k.contributions_krw_total).toBe(5_000_000)
    expect(k.return_krw!).toBeCloseTo(k.last.value_krw! / 5_000_000 - 1, 10)
    expect(k.return_krw!).toBeCloseTo((1 + k.usd_same_basis.return_usd) * (1 + k.fx_change!) - 1, 4)  // 적립이 없으면 (1+USD)×(1+환율 변화)−1
    expect(k.fx_effect_pp!).toBeCloseTo(k.return_krw! - k.usd_same_basis.return_usd, 10)
    const a1 = (await s.getPaperKrw("mock_paper_a1"))!  // 적립 있음: 단순 곱과 다르다
    expect(Math.abs(a1.return_krw! - ((1 + a1.usd_same_basis.return_usd) * (1 + a1.fx_change!) - 1))).toBeGreaterThan(1e-6)
    expect(a1.fx_counts.carried).toBeGreaterThan(0)
    const a3 = (await s.getPaperKrw("mock_paper_a3"))!  // USD 모의투자, 시작일 환율 없음
    expect(a3).toMatchObject({ return_krw: null, gain_krw: null, contributions_krw_total: null })
    expect(a3.unavailable_reason_ko).toMatch(/시작일\(2026-09-01\)의 환율이 없어/)
    expect(a3.fx_counts.missing).toBeGreaterThan(0)
  })
  it("상세 화면: 원화 평가액·수익률·손익, USD 기준 비교, 환율 적용 상태(정상·직전 환율 대체·환율 없음)", async () => {
    const { s } = clocked()
    const { unmount } = withSvc(s, <PaperScreen paperId="mock_paper_a1" />)
    const card = (await screen.findByRole("heading", { name: "원화 기준 성과" }, { timeout: 5000 })).closest("section")!
    expect(within(card).getByRole("table", { name: "원화와 USD 기준 비교" })).toHaveTextContent(/원화 기준.*원.*USD 기준.*USD/)
    expect(within(card).getByText(/원화 수익률이 USD 수익률보다/)).toBeInTheDocument()
    const sum = within(card).getByRole("list", { name: "환율 적용 상태 요약" })
    expect(sum).toHaveTextContent(/직전 환율 대체 [1-9]\d*일/)
    fireEvent.click(within(card).getByRole("button", { name: /대체·환산 불가 날짜/ }))
    expect(within(card).getAllByText(/^직전 환율 대체 \(\d{4}-\d{2}-\d{2}\)$/).length).toBeGreaterThan(0)
    expect(screen.getByText(/^납입 제외 손익 .+ USD \(수수료 차감 후\)$/)).toBeInTheDocument()  // 긴 안내 대신 한 줄
    expect(within(card).queryByText(/넣은 원금 [\d,]+원$|평가액 − 넣은 원금|다를 수 있습니다/)).toBeNull()  // 작은 글씨 정리
    unmount()
    withSvc(s, <PaperScreen paperId="mock_paper_a3" />)
    const c3 = (await screen.findByRole("heading", { name: "원화 기준 성과" }, { timeout: 5000 })).closest("section")!
    expect(within(c3).getByText("원화 수익률을 계산하지 않았습니다.")).toBeInTheDocument()
    expect(within(c3).getAllByText("계산 불가").length).toBe(2)
    expect(within(c3).getByRole("list", { name: "환율 적용 상태 요약" })).toHaveTextContent(/환율 없음\(환산 불가\) [1-9]\d*일/)
  })
  it("일반 모드(제안 메서드 없음): 원화 기준 성과 카드가 없고 손익은 USD 한 줄", async () => {
    const { s } = clocked()
    withSvc(plain(s), <PaperScreen paperId="mock_paper_a1" />)
    await screen.findByRole("heading", { name: "핵심 성과" }, { timeout: 5000 })
    expect(screen.queryByRole("heading", { name: "원화 기준 성과" })).toBeNull()
    expect(screen.getByText(/^납입 제외 손익 .+ USD \(수수료 차감 후\)$/)).toBeInTheDocument()
  })
})

describe("취소한 분석 이어서 실행 (홈)", () => {
  const cancelledLive = async () => {
    const { c, s } = clocked()
    const id = s.startLiveRun("success")
    c.now = T0 + LIVE_QUEUE_MS + 2 * LIVE_STEP_MS + 10
    await s.cancelRun(id)
    c.now += CANCEL_MS + 10
    expect((await s.getRun(id)).status).toBe("cancelled")
    return { s, id }
  }
  it("홈에 「취소한 분석이 있습니다」가 남고, 「멈춘 곳부터 이어서 실행」은 같은 요청으로 새 실행 화면을 연다. 이어서 실행했으면 다시 뜨지 않는다", async () => {
    const { s, id } = await cancelledLive()
    expect((await s.listRuns()).find((r) => r.run_id === id)?.resumable).toBe(true)
    const { unmount } = withSvc(s, <HomeScreen />)
    expect(await screen.findByText("취소한 분석이 있습니다", {}, { timeout: 5000 })).toBeInTheDocument()
    fireEvent.click(screen.getByRole("button", { name: "멈춘 곳부터 이어서 실행" }))
    await waitFor(() => expect(window.location.hash).toMatch(/^#\/runs\//))
    expect(window.location.hash).not.toBe(`#/runs/${id}`)
    expect((await s.listRuns()).find((r) => r.run_id === id)?.resumable).toBe(false)
    unmount()
    withSvc(s, <HomeScreen />)
    await screen.findByRole("heading", { level: 1 }, { timeout: 5000 })
    await waitFor(() => expect(screen.queryByText("취소한 분석이 있습니다")).toBeNull())
  })
  it("「지우기」 하면 이 브라우저에서는 그 취소한 분석 카드를 다시 띄우지 않는다", async () => {
    const { s } = await cancelledLive()
    const { unmount } = withSvc(s, <HomeScreen />)
    fireEvent.click(within((await screen.findByText("취소한 분석이 있습니다", {}, { timeout: 5000 })).closest("[role=alert],[role=status],div")!.parentElement!).getAllByRole("button", { name: "지우기" })[0])
    await waitFor(() => expect(screen.queryByText("취소한 분석이 있습니다")).toBeNull())
    unmount()
    withSvc(s, <HomeScreen />)
    await screen.findByRole("heading", { level: 1 }, { timeout: 5000 })
    expect(screen.queryByText("취소한 분석이 있습니다")).toBeNull()
  })
})
