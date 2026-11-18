import { describe, expect, it } from "vitest"
import { render, screen, within, fireEvent } from "@testing-library/react"
import { Cards } from "./blocks"
import { parseViewCard, parseViewLine } from "./ViewCard"
import type { CardsBlock } from "../../../api/types"

// 실제 서버 카드 문장 (2026-11-11 리포트, 괄호 근거 ID 는 화면 전처리에서 빠진 뒤의 모양)
const real: CardsBlock = { type: "cards", title_ko: "시작일 뉴스 뷰 Black-Litterman 포트폴리오", items: [{
  title_ko: "AI 플랫폼 제휴와 반도체 수출 불확실성",
  text_ko: "ServiceNow와 Figma의 전략적 협업은 긍정적 신호로 해석했습니다.\n· [절대] NOW 오름(약) — 사전 기대 +40.5% → 뷰 +44.3%/년 (신뢰 0.30) — 협업을 시작했다는 소식이 긍정적이다.\n· [절대] NVDA 내림(약) — 사전 기대 +70.8% → 뷰 +65.7%/년 (신뢰 0.20) — 수출 제한 보도는 부정적이나 수요가 강하다는 소식이 반대로 작용했다.",
  meta: [{ label_ko: "기준 대비 주요 변화", value: "NOW +1.5%p, NVDA -0.9%p, GOOGL -0.5%p (뷰 없음, 재배분)" }, { label_ko: "뷰 적중률(백테스트)", value: "50%" }, { label_ko: "근거", value: "ev1, ev2" }],
}] } as CardsBlock

describe("뉴스 투자 의견 카드", () => {
  it("서버 문장 세 가지 틀(한 종목·두 종목 비교·예전 형식)을 읽고, 다른 틀이면 null", () => {
    expect(parseViewLine("· [절대] NOW 오름(약) — 사전 기대 +40.5% → 뷰 +44.3%/년 (신뢰 0.30) — 이유")).toMatchObject({ kind: "abs", long: ["NOW"], dir: "up", strength: "약", numbers: "시장 기준 기대 연 +40.5% → 뉴스 반영 후 연 +44.3% · 확신 정도 30%", reason: "이유" })
    expect(parseViewLine("· [상대] INTU > ORCL (중) — 기대 차이를 INTU 쪽으로 +2.0%p (사전 차이 -8.7% → 뷰 반영 차이 -6.7%/년 — 반영 뒤에도 INTU 쪽 기대가 낮음) (신뢰 0.40) — 이유")).toMatchObject({ kind: "rel", long: ["INTU"], short: ["ORCL"], strength: "중", numbers: "두 쪽 기대 차이: 시장 기준 −8.7% → 뉴스 반영 후 연 −6.7% (INTU 쪽으로 +2.0%p) · 반영 뒤에도 INTU 쪽 기대가 더 낮음 · 확신 정도 40%" })
    expect(parseViewLine("· [절대] MSFT +12%/년 (신뢰 0.30) — 이유")).toMatchObject({ kind: "abs", dir: null, numbers: "뉴스 반영 기대 연 +12% · 확신 정도 30%" })
    expect(parseViewLine("· [절대] 알 수 없는 새 문장")).toBeNull()
    const p = parseViewCard(real.items[0])!
    expect(p.deltas).toEqual([{ ticker: "NOW", value: "+1.5%p", noView: false }, { ticker: "NVDA", value: "−0.9%p", noView: false }, { ticker: "GOOGL", value: "−0.5%p", noView: true }])  // 괄호 안 쉼표에 잘리지 않는다
    expect(parseViewCard({ ...real.items[0], text_ko: real.items[0].text_ko + "\n· [절대] 틀이 다른 줄" })).toBeNull()  // 하나라도 다르면 원문 그대로
  })
  it("종목 · 의견 · 비중 변화 / 이유로 보여 주고, [절대]·신뢰 같은 숫자는 「숫자로 보기」 안에 쉬운 말로", () => {
    render(<Cards b={real} />)
    expect(screen.getByRole("heading", { name: "뉴스로 조정한 비중 (백테스트 시작일 · Black-Litterman)" })).toBeInTheDocument()
    expect(screen.queryByText(/\[절대\]/)).toBeNull()
    expect(screen.getByText("▲ 상승 의견 (약하게)")).toBeInTheDocument(); expect(screen.getByText("▼ 하락 의견 (약하게)")).toBeInTheDocument()
    expect(screen.getByText("비중 +1.5%p")).toBeInTheDocument(); expect(screen.getByText("비중 −0.9%p")).toBeInTheDocument()
    expect(screen.getByText("다른 종목 조정에 따른 비중 변화")).toBeInTheDocument(); expect(screen.queryByText("의견 없음")).toBeNull();  // 다른 종목 비중을 옮기며 바뀐 종목만 (저장된 '(뷰 없음, 재배분)' 표기를 읽어 2026-11-16 새 이름으로)
    expect(screen.getByText(/다른 종목 비중을 옮기면서 함께 바뀌었습니다/)).toBeInTheDocument()
    expect(screen.getByText("50% (백테스트)")).toBeInTheDocument()
    expect(screen.queryByText(/확신 정도/)).toBeNull()
    fireEvent.click(screen.getByRole("button", { name: /숫자로 보기/ }))
    expect(screen.getByText(/시장 기준 기대 연 \+40\.5% → 뉴스 반영 후 연 \+44\.3% · 확신 정도 30%/)).toBeInTheDocument()
  })
  it("분석 기준일 현재 구성 카드(「- 」 줄·「기준 비중 대비」·두 종목 비교 의견·추가 항목)도 같은 모양으로", () => {
    const cur: CardsBlock = { type: "cards", title_ko: "현재 구성 BL 1: 실적 회복과 AI 경쟁 구도", items: [{ title_ko: "실적 회복과 AI 경쟁 구도",
      text_ko: "요약 문단.\n- [절대] MRNA 오름(약) — 사전 기대 +72.8% → 뷰 +83.1%/년 (신뢰 0.25) — 흑자 복귀 기사.\n- [상대] GOOGL > NVDA (약) — 기대 차이를 GOOGL 쪽으로 +5.6%p (사전 차이 -25.6% → 뷰 반영 차이 -20.1%/년 — 반영 뒤에도 GOOGL 쪽 기대가 낮음) (신뢰 0.30) — AI 경쟁 구도 기사.",
      meta: [{ label_ko: "기준 비중 대비 주요 변화", value: "NVDA -0.8%p, MRNA +0.5%p, NOW +0.2%p (뷰 없음, 재배분)" }, { label_ko: "모형상 기대 수익·예상 변동성(최근 자료로 계산한 참고값, 수익 전망 아님)", value: "82.1% / 40.5%" }, { label_ko: "근거", value: "ev1" }] }] } as CardsBlock
    render(<Cards b={cur} />)
    expect(screen.getByRole("heading", { name: "뉴스로 조정한 비중 (분석 기준일 · Black-Litterman)" })).toBeInTheDocument()
    expect(screen.queryByText(/\[(절대|상대)\]/)).toBeNull()
    expect(screen.getByText("GOOGL vs NVDA")).toBeInTheDocument(); expect(screen.getByText("GOOGL를 NVDA보다 긍정적으로 평가 (약하게)")).toBeInTheDocument()
    expect(screen.getByText("비중 +0.5%p")).toBeInTheDocument(); expect(screen.getByText("비중 NVDA −0.8%p")).toBeInTheDocument()
    expect(screen.getByText("NOW")).toBeInTheDocument()  // 의견 없이 바뀐 종목
    expect(screen.getByText("82.1% / 40.5%")).toBeInTheDocument()  // 그 밖의 서버 항목은 그대로
  })
  it("의견 줄이 없는 다른 카드는 지금처럼 원문 그대로", () => {
    render(<Cards b={{ type: "cards", title_ko: "다음에 검토할 수 있는 선택지", items: [{ title_ko: "선택지 1", text_ko: "종목 수 조정", meta: [] }] } as CardsBlock} />)
    expect(within(screen.getByText("선택지 1").parentElement!).getByText("종목 수 조정")).toBeInTheDocument()
  })
})

describe("뉴스 의견 카드 안에 끼우는 내용 (2026-11-16 사용자 요청)", () => {
  it("between 은 「뉴스로 만든 투자 의견」 목록 뒤, 「숫자로 보기」 앞에 들어간다 (없으면 예전 그대로)", () => {
    const { container } = render(<Cards b={real} between={<div data-testid="slot">종목·비중을 정한 근거</div>} />)
    const order = [...container.querySelectorAll("p, button, [data-testid='slot']")].map((e) => e.textContent ?? "")
    const iViews = order.findIndex((t) => t.startsWith("뉴스로 만든 투자 의견")), iSlot = order.findIndex((t) => t === "종목·비중을 정한 근거"), iNum = order.findIndex((t) => t.startsWith("숫자로 보기"))
    expect(iViews).toBeGreaterThanOrEqual(0)
    expect(iViews < iSlot && iSlot < iNum).toBe(true)
  })
})
