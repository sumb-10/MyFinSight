import { afterEach, describe, expect, it, vi } from "vitest"
import { act, fireEvent, render, screen, waitFor, within } from "@testing-library/react"
import { Providers } from "../../app/providers"
import { ApiError } from "../../api/client"
import type { AnalysisService } from "../../api/service"
import type { RunPartial, RunStatus, RunStep, StepStatus } from "../../api/types"
import { RunScreen } from "./RunScreen"
import { collectNotes } from "./steps"

// 분석 진행 화면 회귀 테스트: 서버 상태를 그대로 보여 주는지(단계 이름만 바꿈), 미리보기 자리·중복 안내 정리·취소 상태 구분.

function fakeService(over: Partial<Record<keyof AnalysisService, unknown>> = {}): AnalysisService {
  return {
    mode: "api", health: () => Promise.resolve({ ok: true, api_version: "1", llm_mode: "api", db: { ok: true }, worker: { alive: true, running_run_id: null }, queue_length: 0 }),
    options: () => Promise.reject(new ApiError("NOT_IN_TEST", "테스트에서 쓰지 않음", 500)), getProfile: () => Promise.resolve(null),
    listRequests: () => Promise.resolve([]), listRuns: () => Promise.resolve([]), listReports: () => Promise.resolve([]), getReportComparison: () => Promise.resolve(null), getRunPartial: () => Promise.resolve(null),
    ...over,
  } as unknown as AnalysisService
}

const IDS: [string, string, string][] = [
  ["01_request", "요청 확정과 자료 준비", "conditions"], ["02_intent", "의도 해석", "conditions"], ["03_candidates", "후보 검색", "candidates"], ["04_tagging", "테마 분류", "candidates"],
  ["05_selection", "정량 선정", "candidates"], ["06_explain", "기업별 근거", "candidates"], ["07_backtest_spec", "백테스트 사양·시작일 재선정", "candidates"], ["10f_current", "현재 구성", "candidates"],
  ["10_targets", "시작일 포트폴리오 구성", "candidates"], ["10w_paths", "리밸런싱일별 재구성 (walk-forward)", "candidates"], ["11_backtest", "백테스트", "backtest"], ["12_validation", "사용자 조건 검증", "validation"],
  ["13_results", "결과 통합", "report"], ["14_report", "리포트 문서 생성·검증", "report"],
]
const BUCKETS = [["conditions", "조건과 자료 확인"], ["candidates", "후보 선정과 포트폴리오 구성"], ["backtest", "백테스트"], ["validation", "사용자 조건 검증"], ["report", "리포트 구성과 정합성 검사"]]
const run = (status: RunStatus["status"], st: Record<string, Partial<RunStep>>): RunStatus => {
  const steps = IDS.map(([step, label_ko, bucket]) => ({ ...st[step], step, label_ko, bucket, status: st[step]?.status ?? ("QUEUED" as StepStatus) }))
  const agg = (id: string): StepStatus => { const ss = steps.filter((s) => s.bucket === id).map((s) => s.status); return ss.includes("FAILED") ? "FAILED" : ss.includes("STARTED") ? "STARTED" : ss.every((x) => x === "SUCCESS" || x === "PARTIAL") ? "SUCCESS" : ss.every((x) => x === "QUEUED") ? "QUEUED" : ss.includes("CANCELLED") ? "CANCELLED" : "STARTED" }
  return { run_id: "run1", request_id: "r1", status, queue_position: null, queued_at: "2026-11-01T10:00:00", started_at: "2026-11-01T10:00:01", buckets: BUCKETS.map(([id, title_ko]) => ({ id, title_ko, status: agg(id) })), steps }
}
const ok = { status: "SUCCESS" as StepStatus, summary: "완료" }
const WARN = "필수 포함 종목 NVDA 가 투자 유니버스에 없어 넣지 못했습니다"

describe("분석 진행 화면", () => {
  it("단계 이름을 쉬운 말로 보여 주고, 진행 중 단계와 서버가 준 진행 수를 강조하며, 선정 전에도 미리보기 자리를 둔다", async () => {
    const st = run("running", { "01_request": ok, "02_intent": ok, "03_candidates": ok, "04_tagging": { status: "STARTED", summary: "테마 분류 12/40" } })
    render(<Providers service={fakeService({ getRun: () => Promise.resolve(st) })}><RunScreen runId="run1" /></Providers>)
    await screen.findByText("분석을 실행하고 있습니다")
    const now = screen.getByRole("heading", { name: "지금 하는 일" }).closest("section")!
    expect(within(now).getByText("투자 테마에 맞는 기업 고르기")).toBeInTheDocument()
    expect(within(now).getByText("12/40")).toBeInTheDocument()
    expect(screen.getByText(/전체 14단계 중 3단계 완료/)).toBeInTheDocument()
    expect(screen.getByText(/종목 선정 대기 중입니다/)).toBeInTheDocument()  // 아직 그 단계에 이르지 않음
    const bucket = screen.getByRole("button", { name: /종목 선정과 투자 비중 계산/ })
    expect(bucket.closest("li")).toHaveAttribute("aria-current", "step")
    fireEvent.click(bucket)
    expect(screen.getByText("투자 조건에 맞는 종목 선정")).toBeInTheDocument()
    expect(screen.getByText("현재 시점의 종목별 투자 비중 계산")).toBeInTheDocument()
    expect(screen.queryByText("정량 선정")).toBeNull()
  })

  it("종목 선정 중 안내 → 선정이 끝나면 서버가 준 선정 결과를 보여 준다", async () => {
    let st = run("running", { "01_request": ok, "02_intent": ok, "03_candidates": ok, "04_tagging": ok, "05_selection": { status: "STARTED" } })
    const partial: RunPartial = { run_id: "run1", intent: { summary_ko: "반도체 기업", themes: [], metric: "momentum_12_1" }, selection: { as_of: "2026-10-30", n_selected: 2, n_target: 2, rows: [{ rank: 1, ticker: "NVDA", name: "NVIDIA", sector: "IT", metric_value: 1.2 }, { rank: 2, ticker: "AMD", name: "AMD", sector: "IT", metric_value: 0.8 }] } }
    const getRunPartial = vi.fn(() => Promise.resolve(partial))
    render(<Providers service={fakeService({ getRun: () => Promise.resolve(st), getRunPartial })}><RunScreen runId="run1" /></Providers>)
    expect(await screen.findByText(/투자 종목을 선정하고 있습니다. 종목 선정이 완료되면 이곳에서 확인할 수 있습니다./)).toBeInTheDocument()
    expect(getRunPartial).not.toHaveBeenCalled()
    st = run("running", { "01_request": ok, "02_intent": ok, "03_candidates": ok, "04_tagging": ok, "05_selection": ok, "06_explain": { status: "STARTED" } })
    expect(await screen.findByText("NVIDIA", {}, { timeout: 4000 })).toBeInTheDocument()
    expect(screen.getByText(/2개 \(목표 2개\) · 기준일 2026-10-30/)).toBeInTheDocument()
  })

  it("같은 안내가 여러 단계에 붙어 오면 「확인할 점」에 한 번만, 나온 단계와 함께 보여 준다 (원본 요약은 그대로)", async () => {
    const st = run("partial", Object.fromEntries(IDS.map(([id]) => [id, ok])) as never)
    st.steps[4].summary = `선정 10개 · 확인 필요 1건: ${WARN}`; st.steps[4].status = "PARTIAL"
    st.steps[6].summary = `시작일 재선정 10개 · 확인 필요 1건: ${WARN}`; st.steps[6].status = "PARTIAL"
    render(<Providers service={fakeService({ getRun: () => Promise.resolve(st) })}><RunScreen runId="run1" /></Providers>)
    await screen.findByText("분석이 끝났습니다 (확인할 점 있음)")
    expect(screen.getAllByText(WARN)).toHaveLength(1)
    expect(screen.getByText("투자 조건에 맞는 종목 선정 · 과거 성과 분석 조건 설정")).toBeInTheDocument()
    fireEvent.click(screen.getByRole("button", { name: /종목 선정과 투자 비중 계산/ }))
    expect(screen.getByText("결과: 선정 10개")).toBeInTheDocument()  // 안내 수는 「안내 N」 표시로 따로
    expect(screen.getAllByLabelText("이 단계의 확인할 점 1건")).toHaveLength(2)
    expect(screen.getAllByText(WARN)).toHaveLength(1)
  })

  it("취소: 요청을 보내는 중 → 접수됨(작업 종료 대기) → 서버가 취소를 마치면 취소됨으로 바뀐다", async () => {
    let st = run("running", { "01_request": ok, "02_intent": { status: "STARTED" } })
    let send!: () => void
    const cancelRun = vi.fn(() => new Promise<RunStatus>((res) => { send = () => res({ ...st, status: "cancelling" }) }))
    render(<Providers service={fakeService({ getRun: () => Promise.resolve(st), cancelRun })}><RunScreen runId="run1" /></Providers>)
    await screen.findByText("분석을 실행하고 있습니다")
    fireEvent.click(screen.getByRole("button", { name: /분석 취소/ }))
    fireEvent.click(screen.getByRole("button", { name: "취소 확정" }))
    expect(screen.getByRole("button", { name: "취소 요청을 보내는 중…" })).toBeDisabled()
    send()
    expect(await screen.findByText("분석 취소를 요청했습니다. 현재 작업이 종료되는 데 시간이 걸릴 수 있습니다.")).toBeInTheDocument()
    expect(screen.queryByText("분석이 취소되었습니다")).toBeNull()  // 요청만으로 취소됐다고 하지 않는다
    expect(screen.queryByRole("button", { name: /분석 취소/ })).toBeNull()
    st = run("cancelled", { "01_request": ok, "02_intent": { status: "CANCELLED" } })
    expect(await screen.findByText("분석이 취소되었습니다", {}, { timeout: 4000 })).toBeInTheDocument()
    expect(cancelRun).toHaveBeenCalledTimes(1)
  })

  it("취소 요청이 실패하면 상태는 그대로 두고 오류와 다시 시도를 보여 준다", async () => {
    const st = run("running", { "01_request": { status: "STARTED" } })
    const cancelRun = vi.fn(() => Promise.reject(new ApiError("NETWORK_UNAVAILABLE", "서버에 연결할 수 없습니다.", 0)))
    render(<Providers service={fakeService({ getRun: () => Promise.resolve(st), cancelRun })}><RunScreen runId="run1" /></Providers>)
    await screen.findByText("분석을 실행하고 있습니다")
    fireEvent.click(screen.getByRole("button", { name: /분석 취소/ }))
    fireEvent.click(screen.getByRole("button", { name: "취소 확정" }))
    expect(await screen.findByText("취소 요청을 보내지 못했습니다")).toBeInTheDocument()
    expect(screen.getByText("분석을 실행하고 있습니다")).toBeInTheDocument()
    fireEvent.click(screen.getByRole("button", { name: "다시 시도" }))
    await waitFor(() => expect(cancelRun).toHaveBeenCalledTimes(2))
  })
})

describe("확인할 점", () => {
  afterEach(() => { vi.useRealTimers(); vi.unstubAllGlobals(); vi.restoreAllMocks() })
  const warn = (main: string, ...ws: string[]) => ({ status: "PARTIAL" as StepStatus, summary: `${main} · 확인 필요 ${ws.length}건: ${ws.join("; ")}` })
  const LINK = { name: "확인할 점 보기" }
  const flush = () => act(async () => { await vi.advanceTimersByTimeAsync(0) })
  const tick = () => act(async () => { await vi.advanceTimersByTimeAsync(2500) })
  const live = () => document.querySelector('[aria-live="polite"]')?.textContent ?? ""

  it("집계: 같은 문구는 하나로, 나온 단계를 모으고, 본문 없는 안내도 세며, 묶음 수는 전체 수와 따로 센다", () => {
    const st = run("running", { "04_tagging": warn("a", "공통 안내"), "05_selection": { status: "PARTIAL", summary: "b · 확인 필요 3건: 공통 안내; 선정 안내" }, "11_backtest": warn("c", "공통 안내") })
    const n = collectNotes(st.steps)
    expect(n.notes.map((x) => x.text)).toEqual(["공통 안내", "선정 안내"])
    expect(n.notes[0].from).toEqual(["투자 테마에 맞는 기업 고르기", "투자 조건에 맞는 종목 선정", "과거 성과 계산"])
    expect(n.unlisted).toBe(1)
    expect(n.total).toBe(3)
    expect(n.byBucket).toMatchObject({ candidates: 3, backtest: 1 })
    expect(new Set(n.keys).size).toBe(3)
  })

  it("안내 없음 → 최초 → 같은 응답 반복 → 추가(중복 포함) → 완료 흐름에서 새 안내만 알리고, 저절로 스크롤하지 않는다", async () => {
    vi.useFakeTimers()
    const scroll = vi.fn(); vi.stubGlobal("Element", Element); Element.prototype.scrollIntoView = scroll
    const base = { "01_request": ok, "02_intent": ok, "03_candidates": ok }
    let st = run("running", { ...base, "04_tagging": { status: "STARTED" } })
    const getRun = vi.fn(() => Promise.resolve(st))
    render(<Providers service={fakeService({ getRun })}><RunScreen runId="run1" /></Providers>)
    await flush()
    expect(screen.getByText("현재까지 등록된 안내가 없습니다. 분석 중 확인할 내용이 생기면 이곳에 표시됩니다.")).toBeInTheDocument()
    expect(screen.queryByRole("button", LINK)).toBeNull()
    expect(live()).toBe("")

    st = run("running", { ...base, "04_tagging": warn("테마 통과", WARN), "05_selection": { status: "STARTED" } })
    await tick()
    const heading = () => screen.getByRole("heading", { name: /^확인할 점/ })
    expect(heading()).toHaveTextContent("확인할 점 1건")
    expect(screen.queryByRole("button", LINK)).toBeNull()  // 바로가기는 완료 영역에만
    expect(live()).toBe("확인할 점에 새 안내 1건이 추가되었습니다. 전체 1건입니다.")
    expect(screen.getByRole("button", { name: /종목 선정과 투자 비중 계산/ })).toHaveTextContent("확인할 점 1")
    expect(screen.getByRole("button", { name: /종목 선정과 투자 비중 계산/ })).toHaveTextContent("진행 중")  // 안내가 있어도 실패로 바꾸지 않는다

    const calls = getRun.mock.calls.length
    await tick(); await tick()
    expect(getRun.mock.calls.length).toBeGreaterThan(calls)
    expect(live()).toBe("확인할 점에 새 안내 1건이 추가되었습니다. 전체 1건입니다.")  // 같은 응답을 또 알리지 않는다

    st = run("running", { ...base, "04_tagging": warn("테마 통과", WARN), "05_selection": warn("선정", WARN, "목표보다 적게 선정했습니다"), "06_explain": { status: "STARTED" } })
    await tick()
    expect(heading()).toHaveTextContent("확인할 점 2건")
    expect(live()).toBe("확인할 점에 새 안내 1건이 추가되었습니다. 전체 2건입니다.")  // 중복 문구는 새 안내가 아니다
    expect(screen.queryByText(/새 안내/, { ignore: "[aria-live]" })).toBeNull()  // 화면에는 표시하지 않는다
    expect(scroll).not.toHaveBeenCalled()
    expect(document.body).toHaveFocus()

    st = run("partial", Object.fromEntries(IDS.map(([id]) => [id, id === "04_tagging" ? warn("테마 통과", WARN) : id === "05_selection" ? warn("선정", WARN, "목표보다 적게 선정했습니다") : ok])))
    await tick()
    const result = screen.getByRole("heading", { name: "분석 결과" }).closest("section")!
    expect(within(result).getByRole("button", { name: "리포트 보기" })).toBeEnabled()  // 안내를 보지 않아도 리포트를 연다
    expect(within(result).getByText("확인할 점 2건")).toBeInTheDocument()
    expect(screen.getAllByRole("button", LINK)).toHaveLength(1)

    fireEvent.click(screen.getByRole("button", LINK), { detail: 1 })  // 마우스: 이동만, 포커스는 옮기지 않는다
    expect(scroll).toHaveBeenCalledTimes(1)
    expect(heading()).not.toHaveFocus()
    expect(heading().closest("section")).toHaveClass("ring-2")
    await act(async () => { await vi.advanceTimersByTimeAsync(2100) })
    expect(heading().closest("section")).not.toHaveClass("ring-2")
  })

  it("재진입: 이미 있던 안내는 개수만 바로 보여 주고 새 안내라고 하지 않는다. 본문 없는 안내도 센다", async () => {
    const st = run("running", { "01_request": ok, "02_intent": { status: "PARTIAL", summary: "해석 · 확인 필요 4건: 첫째; 둘째" }, "03_candidates": { status: "STARTED" } })
    render(<Providers service={fakeService({ getRun: () => Promise.resolve(st) })}><RunScreen runId="run1" /></Providers>)
    expect(await screen.findByRole("heading", { name: "확인할 점 4건" })).toBeInTheDocument()
    expect(live()).toBe("")
    expect(screen.getByText(/내용이 표시되지 않은 안내 2건은 리포트에서 확인할 수 있습니다/)).toBeInTheDocument()
  })

  it("runId 가 바뀌면 이전 실행의 알림·개수를 버리고 새 실행을 기준으로 다시 시작한다", async () => {
    vi.useFakeTimers()
    let one = run("running", { "01_request": { status: "STARTED" } })
    const two = { ...run("running", { "01_request": warn("준비", "둘째 실행 안내"), "02_intent": { status: "STARTED" } }), run_id: "run2" }
    const getRun = vi.fn((id: string) => Promise.resolve(id === "run2" ? two : one))
    const ui = (id: string) => <Providers service={fakeService({ getRun })}><RunScreen runId={id} /></Providers>
    const { rerender } = render(ui("run1"))
    await flush()
    one = run("running", { "01_request": warn("준비", WARN), "02_intent": { status: "STARTED" } })
    await tick()
    expect(live()).toContain("새 안내 1건")
    rerender(ui("run2"))
    await flush()
    expect(screen.getByRole("heading", { name: "확인할 점 1건" })).toBeInTheDocument()
    expect(screen.getByText("둘째 실행 안내")).toBeInTheDocument()
    expect(screen.queryByText(WARN)).toBeNull()
    expect(live()).toBe("")
  })

  it("키보드로 실행하면 접힌 영역을 펼치고 제목으로 포커스하며, reduced-motion 이면 부드러운 스크롤을 쓰지 않는다", async () => {
    const scroll = vi.fn(); Element.prototype.scrollIntoView = scroll
    vi.stubGlobal("matchMedia", (q: string) => ({ matches: q.includes("reduce") }))
    const st = run("partial", { "01_request": warn("준비", WARN), "02_intent": ok })
    render(<Providers service={fakeService({ getRun: () => Promise.resolve(st) })}><RunScreen runId="run1" /></Providers>)
    await screen.findByText(WARN)
    fireEvent.click(screen.getByRole("button", { name: "확인할 점 접기" }))
    expect(screen.queryByText(WARN)).toBeNull()
    fireEvent.click(screen.getByRole("button", LINK), { detail: 0 })  // Enter·Space 는 detail 0
    expect(screen.getByText(WARN)).toBeInTheDocument()
    expect(screen.getByRole("heading", { name: /^확인할 점/ })).toHaveFocus()
    expect(scroll).toHaveBeenCalledWith({ behavior: "auto", block: "start" })
  })

  it("안내가 없을 때 끝 상태별 문구: 정상 완료만 ‘확인 사항 없음’이고 실패·취소는 검증 완료처럼 말하지 않는다", async () => {
    for (const [status, text] of [["success", "등록된 확인 사항이 없습니다."], ["failed", /실패해 끝까지 확인하지 못했습니다/], ["cancelled", /취소되어 끝까지 확인하지 못했습니다/]] as const) {
      const st = run(status, { "01_request": ok })
      const { unmount } = render(<Providers service={fakeService({ getRun: () => Promise.resolve(st) })}><RunScreen runId="run1" /></Providers>)
      expect(await screen.findByText(text)).toBeInTheDocument()
      if (status !== "success") expect(screen.queryByText("등록된 확인 사항이 없습니다.")).toBeNull()
      unmount()
    }
  })
})
