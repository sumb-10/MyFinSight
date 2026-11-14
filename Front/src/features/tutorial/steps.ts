/** 튜토리얼 단계. target 은 리포트 화면 요소의 data-tour 값이다 (리포트 컴포넌트에는 이 속성만 붙인다). */
/** placement "left": 강조 영역이 커서 말풍선이 묻히는 단계는 말풍선을 화면 왼쪽(사이드바 위)에 둔다. 좁은 화면이면 기본 배치로. */
/** reveal: 이 단계에 들어갈 때 펼칠 접이식·도움말의 data-tour 값 (떠날 때 다시 닫는다). also: 함께 비출 다른 요소. */
/** demo: 강조 영역 위에 겹쳐 보여 줄 시연. "type" = 대상 안 입력 칸에 text 가 한 글자씩 쳐지는 모습,
 *  "click" = 마우스가 다가가 누르는 모습 (selector: 대상 안에서 가리킬 요소의 CSS 선택자, label: 그중 이 글자가 든 요소). 실제 앱 상태는 바뀌지 않는다. */
//  "hover" = 커서가 selector 로 고른 문장들을 차례로 가리키며 실제 hover 모습을 보여 준다.
//  toggles: 누르는 순간 reveal 의 실제 도움말을 열고, 잠시 뒤 닫기를 되풀이한다 (처음엔 닫힌 채로 시작).
export type TourDemo = { kind: "type"; text: string } | { kind: "click"; selector?: string; label?: string; toggles?: boolean } | { kind: "hover"; selector: string }
export interface TourStep { target: string; title: string; body: string; placement?: "left"; reveal?: string; also?: string[]; demo?: TourDemo }

export const TOUR_STEPS: TourStep[] = [
  { target: "verdict", demo: { kind: "click", label: "선택 이유" }, title: "선택된 전략", body: "개요 맨 위 줄에 이번 분석이 고른 전략과 분석 기준일, 백테스트 기간이 있습니다. 선택 이유를 누르면 왜 이 전략을 골랐는지 볼 수 있습니다." },
  { target: "past", title: "백테스트 핵심 성과", body: "왼쪽 그래프는 이 전략을 과거에 따랐다면 수익률이 어떻게 변했을지를 비교지수와 함께 보여 줍니다. 오른쪽에는 연평균 수익률과 최대낙폭이 있습니다." },
  { target: "term-help", reveal: "term-help", also: ["glossary"], demo: { kind: "click", selector: "button[aria-expanded]", toggles: true }, title: "용어 설명", body: "용어 옆 ? 를 누르면 이렇게 짧은 설명이 뜹니다. 위쪽 투자 용어 설명에서는 리포트에 나온 용어를 한곳에서 찾아볼 수 있습니다." },
  { target: "composition", title: "종목 구성", body: "어떤 종목을 어떤 비중으로 담는지 한눈에 보여 줍니다. 막대 길이가 비중입니다." },
  { target: "allocation-list", placement: "left", title: "종목별 투자 금액", body: "종목마다 내 투자금에서 얼마를 넣는지(목표 배분액)와 그 금액으로 사는 주식 수입니다." },
  { target: "details", demo: { kind: "click", selector: "button[aria-expanded] > span[aria-hidden]" }, title: "자세한 분석", body: "선택 이유, 비중이 정해진 과정, 기업별 근거, 과거 성과와 내 조건 점검, 시장·뉴스 분석이 들어 있습니다. 눌러서 펼치고, 위쪽 탭을 눌러도 바로 열립니다." },
  { target: "paper-start", demo: { kind: "click" }, title: "모의투자로 지켜보기", body: "마음에 드는 리포트라면 모의투자 시작으로 실제 돈 없이 이 구성을 따라가 볼 수 있습니다. 둘러보기에서는 누르지 않아도 됩니다." },
]
