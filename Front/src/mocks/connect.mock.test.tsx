import { afterEach, beforeAll, describe, expect, it, vi } from "vitest"
import { fireEvent, render, screen, waitFor, within } from "@testing-library/react"
import type { AnalysisService } from "../api/service"
import { HttpService } from "../api/service"
import App from "../app/App"
import { Providers } from "../app/providers"
import { connectSkipped, markConnectSkipped } from "../features/connect/skip"
import { MOCK_DB_MASKED, MOCK_KEY_MASKED, checkConnection } from "./data/connections"
import { MockService } from "./services/MockService"

beforeAll(() => { globalThis.ResizeObserver ??= class { observe() {} unobserve() {} disconnect() {} } as unknown as typeof ResizeObserver; Element.prototype.scrollIntoView = vi.fn(); window.scrollTo = vi.fn() as unknown as typeof window.scrollTo })
afterEach(() => { window.history.replaceState(null, "", "/"); window.localStorage.clear(); window.sessionStorage.clear() })

// 연결 설정 (제안 기능 · 목업): 처음 켰을 때의 연결 흐름(팀 DB → 분석 모델 → 내 투자조건)과 사이드바 「연결 설정」 화면.

const GOOD_DB = "postgresql://reader:example-pw@db.example.com:5432/myfinsight?sslmode=require"
const TYPO_DB = "postgresql://reader:example-pw@db.exampel.com:5432/myfinsight"
const GOOD_KEY = "sk-example-0000000000000000a3F9"

const mock = () => new MockService({ latencyMs: 0, persist: false })
/** 처음 켠 사람: 연결 전 + 투자조건 없음 */
const fresh = () => { const s = mock(); s.setConnections(false); s.setProfileVariant("none"); return s }
const show = (svc: AnalysisService, hash = "") => { window.history.replaceState(null, "", `/?mock=1${hash}`); return render(<Providers service={svc}><App /></Providers>) }
const type = (label: string, value: string) => fireEvent.change(screen.getByLabelText(label), { target: { value } })
const click = (name: string | RegExp) => fireEvent.click(screen.getByRole("button", { name }))

describe("연결 설정 · 목업 규칙", () => {
  it("값의 모양으로 판정한다: 되면 가린 표시, 안 되면 원인 코드", () => {
    expect(checkConnection("database", GOOD_DB)).toEqual({ ok: true, masked: MOCK_DB_MASKED })
    expect(checkConnection("database", TYPO_DB)).toMatchObject({ ok: false, error: { code: "host_not_found", value: "db.exampel.com" } })
    expect(checkConnection("database", "postgresql://reader:pw@db.example.com:1/myfinsight")).toMatchObject({ ok: false, error: { code: "no_response", value: "db.example.com:1" } })
    expect(checkConnection("database", "postgresql://wrong:pw@db.example.com/myfinsight")).toMatchObject({ ok: false, error: { code: "auth_failed", value: null } })
    expect(checkConnection("database", "postgresql://reader:pw@db.example.com/nope")).toMatchObject({ ok: false, error: { code: "database_not_found", value: "nope" } })
    expect(checkConnection("database", "그냥 글자")).toMatchObject({ ok: false, error: { code: "unknown" } })
    expect(checkConnection("llm", GOOD_KEY)).toEqual({ ok: true, masked: MOCK_KEY_MASKED })
    expect(checkConnection("llm", "sk-short")).toMatchObject({ ok: false, error: { code: "invalid_key" } })
    expect(checkConnection("llm", "sk-quota-000000000000000000")).toMatchObject({ ok: false, error: { code: "quota" } })
  })
  it("가린 표시와 오류 문장에 비밀번호·키 본문이 남지 않는다", () => {
    const all = JSON.stringify([checkConnection("database", GOOD_DB), checkConnection("database", TYPO_DB), checkConnection("database", "postgresql://wrong:example-pw@db.example.com/x"), checkConnection("llm", GOOD_KEY), checkConnection("llm", "sk-bad-key-body")])
    expect(all).not.toContain("example-pw")
    expect(all).not.toContain("0000000000000000")
    expect(all).not.toContain("bad-key-body")
  })
  it("확인이 돼야 저장하고, 서버 상태(연습 모드·DB)도 연결에 맞춰 바뀐다", async () => {
    const s = fresh()
    expect(await s.getConnections()).toMatchObject({ database: { connected: false, masked: null, latest_trading_day: null }, llm: { connected: false, masked: null, cost_per_run_usd: 0.1 } })
    expect(await s.health()).toMatchObject({ llm_mode: "stub", db: { ok: false } })

    const bad = await s.saveConnection("database", TYPO_DB)
    expect(bad).toMatchObject({ ok: false, error: { code: "host_not_found" }, connections: { database: { connected: false } } })
    const ok = await s.saveConnection("database", GOOD_DB)
    expect(ok).toMatchObject({ ok: true, error: null, connections: { database: { connected: true, masked: MOCK_DB_MASKED }, llm: { connected: false } } })
    expect(ok.connections.database.latest_trading_day).toMatch(/^\d{4}-\d{2}-\d{2}$/)
    expect(await s.health()).toMatchObject({ llm_mode: "stub", db: { ok: true } })

    await s.saveConnection("llm", GOOD_KEY)
    expect(await s.health()).toMatchObject({ llm_mode: "api", db: { ok: true } })
    expect(await s.clearConnection("llm")).toMatchObject({ llm: { connected: false, masked: null }, database: { connected: true } })
    expect(await s.health()).toMatchObject({ llm_mode: "stub" })
  })
  it("기본 목업은 둘 다 연결된 상태다 (다른 목업 화면이 연습 모드로 보이지 않게)", async () => {
    const s = mock()
    expect(await s.getConnections()).toMatchObject({ database: { connected: true }, llm: { connected: true } })
    expect(await s.health()).toMatchObject({ llm_mode: "api", db: { ok: true } })
  })
})

describe("처음 켰을 때의 연결 흐름", () => {
  it("연결 전 + 투자조건 없음이면 홈 대신 연결 흐름부터 뜨고, 빈 칸이면 「연결하기」를 누를 수 없다", async () => {
    show(fresh(), "#/home")
    expect(await screen.findByRole("heading", { name: "팀에서 받은 DB 주소를 붙여 넣어 주세요" })).toBeInTheDocument()
    expect(window.location.hash).toBe("#/connect")
    expect(screen.queryByRole("navigation", { name: "주 메뉴" })).not.toBeInTheDocument()  // 사이드바 없이
    expect(screen.getByRole("button", { name: "연결하기" })).toBeDisabled()
    expect(screen.getByRole("list", { name: "시작 준비 단계" })).toHaveTextContent("팀 DB분석 모델내 투자조건")
    expect(within(screen.getByRole("list", { name: "시작 준비 단계" })).getByText("팀 DB").closest("li")).toHaveAttribute("aria-current", "step")
  })
  it("주소를 붙여 넣으면 서버·포트·이름·계정을 풀어서 보여 준다 (칸은 가려져 있고 비밀번호는 보이지 않는다)", async () => {
    show(fresh(), "#/connect")
    await screen.findByRole("heading", { name: /DB 주소를 붙여 넣어/ })
    const field = screen.getByLabelText("팀에서 받은 DB 접속 주소")
    expect(field).toHaveAttribute("type", "password")
    expect(screen.queryByText("서버")).not.toBeInTheDocument()
    type("팀에서 받은 DB 접속 주소", GOOD_DB)
    expect(screen.getByText("서버").nextSibling).toHaveTextContent("db.example.com")
    expect(screen.getByText("포트").nextSibling).toHaveTextContent("5432")
    expect(screen.getByText("데이터베이스").nextSibling).toHaveTextContent("myfinsight")
    expect(screen.getByText("계정").nextSibling).toHaveTextContent("reader")
    expect(document.body).not.toHaveTextContent("example-pw")
    expect(screen.getByRole("button", { name: "연결하기" })).toBeEnabled()
    click("팀에서 받은 DB 접속 주소 보기")
    expect(field).toHaveAttribute("type", "text")
  })
  it("팀 DB → 분석 모델 → 내 투자조건: 연결되면 제목이 바뀌고, 끝나면 이번 실행 동안 다시 띄우지 않게 적어 둔다", async () => {
    show(fresh(), "#/home")
    await screen.findByRole("heading", { name: /DB 주소를 붙여 넣어/ })
    type("팀에서 받은 DB 접속 주소", GOOD_DB)
    click("연결하기")
    expect(await screen.findByRole("heading", { name: "팀 DB에 연결했습니다" })).toBeInTheDocument()
    expect(screen.getByText(MOCK_DB_MASKED)).toBeInTheDocument()
    expect(screen.getByText("최신 거래일")).toBeInTheDocument()
    // 자료 시작일은 시장마다 다르다 → 미국·한국을 따로 보여 준다
    expect(screen.getByText("미국 자료 시작일").nextElementSibling).toHaveTextContent("1993-01-29")
    expect(screen.getByText("한국 자료 시작일").nextElementSibling).toHaveTextContent("2002-10-14")
    expect(within(screen.getByRole("list", { name: "시작 준비 단계" })).getByText("팀 DB").closest("li")).toHaveTextContent("(연결됨)")

    click("다음")
    expect(await screen.findByRole("heading", { name: "OpenAI API 키를 넣어 주세요" })).toBeInTheDocument()
    expect(window.location.hash).toBe("#/connect/llm")
    expect(screen.getByText("분석 1회 약 0.1달러")).toBeInTheDocument()
    expect(screen.getByRole("link", { name: "API 키 만들기" })).toHaveAttribute("href", "https://platform.openai.com/api-keys")
    type("OpenAI API 키", GOOD_KEY)
    click("연결하기")
    expect(await screen.findByRole("heading", { name: "OpenAI에 연결했습니다" })).toBeInTheDocument()
    expect(screen.getByText(MOCK_KEY_MASKED)).toBeInTheDocument()

    click("내 투자조건 설정으로")
    await waitFor(() => expect(window.location.hash).toBe("#/profile/chat"))
    expect(connectSkipped()).toBe(true)
    expect(await screen.findByRole("heading", { name: "내 프로필을 정해봅시다" })).toBeInTheDocument()
    await waitFor(() => expect(screen.queryByText("연습 모드로 둘러보는 중입니다.")).not.toBeInTheDocument())  // 둘 다 연결했으니 연습 모드가 아니다
  })
  it("실패하면 원인과 문제가 된 값을 보여 주고, 값을 고치기 시작하면 오류 표시가 사라진다", async () => {
    show(fresh(), "#/connect")
    await screen.findByRole("heading", { name: /DB 주소를 붙여 넣어/ })
    type("팀에서 받은 DB 접속 주소", TYPO_DB)
    click("연결하기")
    const alert = await screen.findByRole("alert")
    expect(alert).toHaveTextContent("서버 주소를 찾지 못했습니다: db.exampel.com")
    expect(alert).toHaveTextContent("주소에 오타가 없는지, 인터넷에 연결돼 있는지 확인해 주세요.")
    expect(alert).toHaveTextContent("could not translate host name")
    expect(alert).not.toHaveTextContent("비밀번호")  // 원인에 맞는 것만 말한다
    expect(screen.getByLabelText("팀에서 받은 DB 접속 주소")).toHaveAttribute("aria-invalid", "true")
    expect(screen.getByRole("button", { name: "다시 연결하기" })).toBeEnabled()

    type("팀에서 받은 DB 접속 주소", GOOD_DB)
    expect(screen.queryByRole("alert")).not.toBeInTheDocument()
    expect(screen.getByLabelText("팀에서 받은 DB 접속 주소")).toHaveAttribute("aria-invalid", "false")
    click("연결하기")
    expect(await screen.findByRole("heading", { name: "팀 DB에 연결했습니다" })).toBeInTheDocument()
  })
  it("항목별로 넣어도 같은 주소로 연결한다", async () => {
    const s = fresh(), save = vi.spyOn(s, "saveConnection")
    show(s, "#/connect")
    await screen.findByRole("heading", { name: /DB 주소를 붙여 넣어/ })
    click("항목별로 입력")
    expect(screen.getByRole("button", { name: "연결하기" })).toBeDisabled()
    type("서버", "db.example.com"); type("계정", "reader"); type("비밀번호", "p@ss")
    click("연결하기")
    expect(await screen.findByRole("heading", { name: "팀 DB에 연결했습니다" })).toBeInTheDocument()
    expect(save).toHaveBeenCalledWith("database", "postgresql://reader:p%40ss@db.example.com:5432/myfinsight")
  })
  it("「나중에 하기」로 둘 다 넘기면 투자조건 설정으로 가고, 연습 모드 알림의 「연결 설정」으로 다시 들어온다", async () => {
    show(fresh(), "#/home")
    await screen.findByRole("heading", { name: /DB 주소를 붙여 넣어/ })
    click("나중에 하기")
    expect(await screen.findByRole("heading", { name: "OpenAI API 키를 넣어 주세요" })).toBeInTheDocument()
    expect(within(screen.getByRole("list", { name: "시작 준비 단계" })).getByText("팀 DB").closest("li")).toHaveTextContent("(건너뜀)")
    click("나중에 하기")
    await waitFor(() => expect(window.location.hash).toBe("#/profile/chat"))
    expect(connectSkipped()).toBe(true)

    const banner = (await screen.findByText("연습 모드로 둘러보는 중입니다.")).closest("[role=status]") as HTMLElement
    expect(banner).toHaveTextContent("예시 데이터와 미리 만든 답을 쓰기 때문에 결과가 입력한 아이디어와 맞지 않습니다.")
    fireEvent.click(within(banner).getByRole("button", { name: "연결 설정" }))
    expect(await screen.findByRole("heading", { name: "연결 설정" })).toBeInTheDocument()
    expect(window.location.hash).toBe("#/settings")
    expect(screen.queryByText("연습 모드로 둘러보는 중입니다.")).not.toBeInTheDocument()  // 연결 설정 화면에는 알림을 띄우지 않는다
  })
  it("투자조건이 이미 있어도, 연결이 없고 이 흐름을 거친 적이 없으면 홈에서 한 번 띄운다 (끝나면 홈으로)", async () => {
    const s = mock(); s.setConnections(false)  // 투자조건은 있고 연결만 없다 (키를 지웠거나 새 PC 로 옮긴 경우)
    const first = show(s, "#/reports")
    expect(await screen.findByText("연습 모드로 둘러보는 중입니다.")).toBeInTheDocument()
    expect(window.location.hash).toBe("#/reports")  // 리포트 주소로 바로 들어온 사람은 막지 않는다
    first.unmount()

    show(s, "#/home")
    expect(await screen.findByRole("heading", { name: "팀에서 받은 DB 주소를 붙여 넣어 주세요" })).toBeInTheDocument()
    expect(window.location.hash).toBe("#/connect")
    click("나중에 하기")
    await screen.findByRole("heading", { name: "OpenAI API 키를 넣어 주세요" })
    type("OpenAI API 키", GOOD_KEY); click("연결하기")
    await screen.findByRole("heading", { name: "OpenAI에 연결했습니다" })
    click("홈으로")  // 투자조건이 있으니 다음은 투자조건 설정이 아니라 홈
    await waitFor(() => expect(window.location.hash).toBe("#/home"))
    expect(connectSkipped()).toBe(true)
    expect(await screen.findByText("연습 모드로 둘러보는 중입니다.")).toBeInTheDocument()  // 팀 DB 는 넘겼으니 아직 연습 모드. 흐름은 다시 뜨지 않는다
    expect(screen.queryByRole("heading", { name: /DB 주소를 붙여 넣어/ })).not.toBeInTheDocument()
  })
  it("넘긴 뒤에는 이 창을 닫을 때까지만 다시 띄우지 않는다: 다음에 켜면 연결 안 된 것이 있는 한 다시 묻는다", async () => {
    window.history.replaceState(null, "", "/?mock=1")
    markConnectSkipped()  // 이번 실행에서 이미 넘겼다
    const first = show(fresh(), "#/home")
    await waitFor(() => expect(window.location.hash).toBe("#/profile/chat"))
    first.unmount()

    window.sessionStorage.clear()  // 창을 닫았다가 다시 켰다 (localStorage 는 그대로 남는다)
    show(fresh(), "#/home")
    expect(await screen.findByRole("heading", { name: "팀에서 받은 DB 주소를 붙여 넣어 주세요" })).toBeInTheDocument()
    expect(window.location.hash).toBe("#/connect")
  })
  it("둘 다 연결돼 있으면 넘긴 적이 없어도 띄우지 않는다", async () => {
    const s = mock(); s.setProfileVariant("none")  // 둘 다 연결된 처음 사용자
    show(s, "#/home")
    await waitFor(() => expect(window.location.hash).toBe("#/profile/chat"))
    expect(connectSkipped()).toBe(false)
  })
  it("실제 서버 서비스는 연결 설정을 서버 주소로 요청한다 (저장은 값만 본문에)", async () => {
    const f = vi.spyOn(globalThis, "fetch").mockImplementation(async () => new Response("{}", { status: 200 }))
    const http = new HttpService()
    await http.getConnections(); await http.saveConnection("llm", GOOD_KEY); await http.clearConnection("database")
    const calls = f.mock.calls.map(([url, init]) => `${init?.method} ${String(url).replace(/^.*\/api\/v1/, "")} ${init?.body ?? ""}`.trim())
    expect(calls).toEqual(["GET /connections", `PUT /connections/llm {"value":"${GOOD_KEY}"}`, "DELETE /connections/database"])
    f.mockRestore()
  })
  it("연결 설정 기능이 없는 서비스(옛 서버)는 지금까지와 같다: 연결 흐름·사이드바 입구가 없다", async () => {
    const s = fresh()
    const plain = new Proxy(s, { get: (t, k) => (k === "getConnections" || k === "saveConnection" || k === "clearConnection" ? undefined : Reflect.get(t, k, t)) }) as unknown as AnalysisService
    show(plain, "#/home")
    await waitFor(() => expect(window.location.hash).toBe("#/profile/chat"))
    expect(await screen.findByText("연습 모드로 켜져 있습니다.")).toBeInTheDocument()
    expect(screen.getByText("연습 모드 (LLM 없음)")).toBeInTheDocument()
    expect(screen.queryByRole("button", { name: "연결 설정" })).not.toBeInTheDocument()
  })
})

describe("값의 출처: 환경변수는 읽기만, 화면 저장은 운영체제 보관함", () => {
  it("안내 문장에 저장하는 곳(보관함 이름)을 적는다", async () => {
    show(fresh(), "#/connect")
    await screen.findByRole("heading", { name: /DB 주소를 붙여 넣어/ })
    expect(screen.getByText("주소는 Windows 자격 증명 관리자에 저장되고 연결 설정에서 지울 수 있습니다.")).toBeInTheDocument()
    click("나중에 하기")
    await screen.findByRole("heading", { name: "OpenAI API 키를 넣어 주세요" })
    expect(screen.getByText("키는 Windows 자격 증명 관리자에 저장되고 연결 설정에서 지울 수 있습니다.")).toBeInTheDocument()
  })
  it("환경변수로 들어온 연결(개발 PC 의 .env · Docker Compose)은 보여 주기만 하고 바꾸기·지우기 버튼이 없다", async () => {
    const s = mock(); s.setConnections(true, { fromEnv: true })
    expect(await s.getConnections()).toMatchObject({ database: { connected: true, source: "env" }, llm: { connected: true, source: "env" } })
    await expect(s.saveConnection("llm", GOOD_KEY)).rejects.toMatchObject({ code: "CONNECTION_FROM_ENV", status: 409 })
    await expect(s.clearConnection("database")).rejects.toMatchObject({ code: "CONNECTION_FROM_ENV" })

    show(s, "#/settings")
    const llm = await screen.findByRole("region", { name: "분석 모델" })
    expect(llm).toHaveTextContent("연결됨"); expect(llm).toHaveTextContent("환경변수(.env)로 설정됨"); expect(llm).toHaveTextContent(MOCK_KEY_MASKED)
    expect(within(llm).queryByRole("button")).not.toBeInTheDocument()
    expect(within(screen.getByRole("region", { name: "팀 DB" })).queryByRole("button")).not.toBeInTheDocument()
  })
  it("운영체제 보관함이 없는 환경(Docker)에서는 입력칸 대신 .env 로 넣는 방법을 알리고, 연결 설정에도 버튼이 없다", async () => {
    const s = fresh(); s.setConnections(false, { noSave: true })
    expect(await s.getConnections()).toMatchObject({ can_save: false, store_label_ko: null, llm: { connected: false, source: null } })
    await expect(s.saveConnection("llm", GOOD_KEY)).rejects.toMatchObject({ code: "SECRET_STORE_UNAVAILABLE", status: 409 })

    show(s, "#/connect")
    expect(await screen.findByText("이 환경에서는 화면에서 저장할 수 없습니다.")).toBeInTheDocument()
    expect(screen.getByText("DATABASE_URL=postgresql://…")).toBeInTheDocument()
    expect(screen.queryByLabelText("팀에서 받은 DB 접속 주소")).not.toBeInTheDocument()
    click("다음")
    expect(await screen.findByText("OPENAI_API_KEY=sk-…")).toBeInTheDocument()
    click("내 투자조건 설정으로")
    await waitFor(() => expect(window.location.hash).toBe("#/profile/chat"))

    fireEvent.click((await screen.findAllByRole("button", { name: "연결 설정" }))[0])  // 연습 모드 알림과 사이드바 둘 다 같은 곳으로 간다
    const llm = await screen.findByRole("region", { name: "분석 모델" })
    expect(llm).toHaveTextContent("연결 전"); expect(within(llm).queryByRole("button")).not.toBeInTheDocument()
    expect(screen.getByText("이 환경에서는 화면에서 저장할 수 없습니다. 서버의 .env 파일에 적은 값으로 연결합니다.")).toBeInTheDocument()
  })
  it("환경변수의 주소가 닿지 않으면 「연결됨」이 아니라 원인을 보여 준다 (화면에서 고칠 수 없으니)", async () => {
    const s = fresh(); s.setConnections(true, { fromEnv: true, envDown: true })
    expect(await s.getConnections()).toMatchObject({ database: { connected: false, source: "env", error: { code: "host_not_found" } } })
    expect(await s.health()).toMatchObject({ db: { ok: false } })

    show(s, "#/connect")
    expect(await screen.findByRole("heading", { name: "팀 DB에 연결하지 못했습니다" })).toBeInTheDocument()
    expect(screen.getByRole("alert")).toHaveTextContent("서버 주소를 찾지 못했습니다: db.example.com")
    expect(screen.getByText(/환경변수\(\.env\)로 설정된 연결입니다/)).toBeInTheDocument()
    expect(screen.queryByLabelText("팀에서 받은 DB 접속 주소")).not.toBeInTheDocument()
    expect(screen.queryByRole("button", { name: "팀 DB 접속 주소 바꾸기" })).not.toBeInTheDocument()

    window.history.replaceState(null, "", "/?mock=1#/settings"); window.dispatchEvent(new HashChangeEvent("hashchange"))
    const db = await screen.findByRole("region", { name: "팀 DB" })
    expect(db).toHaveTextContent("연결 전"); expect(db).toHaveTextContent("환경변수(.env)로 설정됨"); expect(db).toHaveTextContent("서버 주소를 찾지 못했습니다: db.example.com")
    expect(db).not.toHaveTextContent("최신 거래일")
    expect(within(db).queryByRole("button", { name: /연결하기|바꾸기|지우기/ })).not.toBeInTheDocument()
  })
  it("서버가 연습 모드로 고정돼 있으면(.env.example 을 그대로 복사한 상태) 입력칸 대신 푸는 방법을 알린다", async () => {
    const s = fresh(); s.setConnections(false, { stubPinned: true })
    expect(await s.getConnections()).toMatchObject({ llm: { connected: false, stub_pinned: true } })

    show(s, "#/connect/llm")
    expect(await screen.findByText("서버가 연습 모드로 고정돼 있어 지금은 키를 넣을 수 없습니다.")).toBeInTheDocument()
    expect(screen.getByText("MYFINSIGHT_LLM=stub")).toBeInTheDocument()
    expect(screen.queryByLabelText("OpenAI API 키")).not.toBeInTheDocument()

    window.history.replaceState(null, "", "/?mock=1#/settings"); window.dispatchEvent(new HashChangeEvent("hashchange"))
    const llm = await screen.findByRole("region", { name: "분석 모델" })
    expect(llm).toHaveTextContent("서버가 연습 모드로 고정돼 있습니다."); expect(llm).toHaveTextContent(".env 파일에서 MYFINSIGHT_LLM=stub 줄을 지우고 서버를 다시 켜 주세요.")
    expect(within(llm).queryByRole("button", { name: "연결하기" })).not.toBeInTheDocument()
    expect(within(screen.getByRole("region", { name: "팀 DB" })).getByRole("button", { name: "연결하기" })).toBeInTheDocument()  // 팀 DB 는 화면에서 넣을 수 있다
  })
  it("저장하려는 순간 서버가 연습 모드 고정을 알려 와도 그 사정과 고치는 법을 보여 준다", async () => {
    const s = fresh()
    vi.spyOn(s, "saveConnection").mockResolvedValue({ ok: false, connections: await s.getConnections(), error: { code: "stub_pinned", value: null, raw: "MYFINSIGHT_LLM=stub" } })
    show(s, "#/connect/llm")
    await screen.findByRole("heading", { name: "OpenAI API 키를 넣어 주세요" })
    type("OpenAI API 키", GOOD_KEY); click("연결하기")
    const alert = await screen.findByRole("alert")
    expect(alert).toHaveTextContent("서버가 연습 모드로 고정돼 있습니다."); expect(alert).toHaveTextContent(".env 파일에서 MYFINSIGHT_LLM=stub 줄을 지우고 서버를 다시 켜 주세요.")
  })
})

describe("연결 설정 화면", () => {
  it("연결마다 한 줄: 가린 값과 상태를 보여 주고, 사이드바 입구가 켜져 있다", async () => {
    show(mock(), "#/settings")
    expect(await screen.findByRole("heading", { name: "연결 설정" })).toBeInTheDocument()
    const db = screen.getByRole("region", { name: "팀 DB" }), llm = screen.getByRole("region", { name: "분석 모델" })
    expect(db).toHaveTextContent(MOCK_DB_MASKED); expect(db).toHaveTextContent("연결됨"); expect(db).toHaveTextContent("최신 거래일")
    // 자료 시작일은 최신 거래일과 다른 줄이다 (한 줄에 이으면 읽기 어렵다)
    expect(within(db).getByText("자료 시작일 미국 1993-01-29, 한국 2002-10-14")).toBeInTheDocument()
    expect(within(db).getByText(/^최신 거래일 \d{4}-\d{2}-\d{2}$/)).toBeInTheDocument()
    expect(llm).toHaveTextContent(MOCK_KEY_MASKED); expect(llm).toHaveTextContent("연결됨")
    expect(screen.getByRole("button", { name: "연결 설정" })).toHaveAttribute("aria-current", "page")
    expect(screen.queryByText("연습 모드")).not.toBeInTheDocument()
  })
  it("지우기는 한 번 더 묻고, 지우면 연결 전으로 돌아가 사이드바에 연습 모드가 뜬다", async () => {
    show(mock(), "#/settings")
    const llm = await screen.findByRole("region", { name: "분석 모델" })
    fireEvent.click(within(llm).getByRole("button", { name: "지우기" }))
    const ask = within(llm).getByRole("alertdialog", { name: "분석 모델 지우기 확인" })
    expect(ask).toHaveTextContent("저장한 키를 지울까요?")
    fireEvent.click(within(ask).getByRole("button", { name: "취소" }))
    expect(within(llm).queryByRole("alertdialog")).not.toBeInTheDocument()
    expect(llm).toHaveTextContent("연결됨")

    fireEvent.click(within(llm).getByRole("button", { name: "지우기" }))
    fireEvent.click(within(within(llm).getByRole("alertdialog")).getByRole("button", { name: "지우기" }))
    await waitFor(() => expect(llm).toHaveTextContent("연결 전"))
    expect(llm).not.toHaveTextContent(MOCK_KEY_MASKED)
    expect(await screen.findByText("연습 모드")).toBeInTheDocument()
  })
  it("「연결하기」를 누르면 그 줄이 입력칸으로 펼쳐지고, 틀린 키는 원인을 알려 주고, 맞는 키는 연결됨으로 바뀐다", async () => {
    const s = mock(); s.setConnections(false)
    show(s, "#/settings")
    const llm = await screen.findByRole("region", { name: "분석 모델" })
    expect(llm).toHaveTextContent("연결 전")
    fireEvent.click(within(llm).getByRole("button", { name: "연결하기" }))
    const field = within(llm).getByLabelText("OpenAI API 키")
    expect(within(llm).getAllByRole("button", { name: "연결하기" })).toHaveLength(1)  // 줄의 버튼은 숨기고 아래 하나만
    expect(within(llm).getByRole("button", { name: "연결하기" })).toBeDisabled()

    fireEvent.change(field, { target: { value: "sk-short" } })
    fireEvent.click(within(llm).getByRole("button", { name: "연결하기" }))
    expect(await within(llm).findByRole("alert")).toHaveTextContent("키가 올바르지 않습니다.")

    fireEvent.change(field, { target: { value: GOOD_KEY } })
    fireEvent.click(within(llm).getByRole("button", { name: "연결하기" }))
    await waitFor(() => expect(llm).toHaveTextContent(MOCK_KEY_MASKED))
    expect(llm).toHaveTextContent("연결됨")
    expect(within(llm).queryByLabelText("OpenAI API 키")).not.toBeInTheDocument()
    expect(document.body).not.toHaveTextContent("0000000000000000")  // 넣은 키 본문은 화면에 남지 않는다
  })
})
