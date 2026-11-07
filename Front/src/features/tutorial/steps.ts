/** 튜토리얼 단계. target 은 리포트 화면 요소의 data-tour 값이다 (리포트 컴포넌트에는 이 속성만 붙인다). */
/** placement "left": 강조 영역이 커서 말풍선이 묻히는 단계는 말풍선을 화면 왼쪽(사이드바 위)에 둔다. 좁은 화면이면 기본 배치로. */
export interface TourStep { target: string; title: string; body: string; placement?: "left" }

export const TOUR_STEPS: TourStep[] = [
  { target: "verdict", title: "결론부터 확인하세요", body: "맨 위 상자가 이번 분석의 결론입니다. 추천인지, 내 조건 중 무엇을 지켰고 무엇이 기준을 넘었는지 한 문장으로 정리돼 있습니다." },
  { target: "allocation", placement: "left", title: "얼마를 투자하나요?", body: "종목별로 얼마씩 나눠 투자하는지 보여 줍니다. 막대 길이는 비중이고, 오른쪽 금액은 내 투자금 기준 목표 배분액입니다." },
  { target: "past", title: "과거에 투자했다면", body: "같은 기간 비교지수와 나란히, 이 전략을 과거에 따랐다면 어땠을지 계산한 결과입니다. 미래 수익을 보장하지는 않습니다." },
  { target: "conditions", title: "내 조건 체크", body: "허용 손실·목표 수익·변동성 같은 내 조건을 하나씩 충족·주의로 표시합니다. 자세한 수치는 「조건별 자세한 결과」를 펼쳐 보세요." },
  { target: "details", placement: "left", title: "자세한 분석 펼치기", body: "왜 이 종목과 비중이 나왔는지, 시장·뉴스는 어떻게 봤는지 같은 근거는 아래 접이식 섹션에 있습니다. 위쪽 탭으로 바로 이동할 수도 있습니다." },
  { target: "glossary", title: "어려운 용어는 ?·용어 설명으로", body: "문장 옆 ? 표시를 누르면 짧은 설명이 뜹니다. 「투자 용어 설명」에서는 리포트에 나온 용어를 한곳에서 찾아볼 수 있습니다." },
  { target: "paper-start", title: "모의투자로 지켜보기", body: "마음에 드는 리포트라면 「모의투자 시작」으로 실제 돈 없이 이 구성을 따라가 볼 수 있습니다. 둘러보기에서는 누르지 않아도 됩니다." },
]
