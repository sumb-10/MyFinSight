import type { TourStep } from "./steps"

/** 홈 둘러보기 (새 분석 카드의 「둘러보기」). target 은 홈·사이드바 요소의 data-tour 값. 대상이 화면에 없으면 말풍선만 가운데에 뜬다.
 *  왼쪽 입력 카드 → 오른쪽 「내게 맞는 정보」 탭 순서. 탭 안의 대상(home-process · trends · profile · reports)은 홈이 그 탭을 열어 보여 준다 (HomeInfo TOUR_TAB). */
export const HOME_TOUR_STEPS: TourStep[] = [
  { target: "home-menu", title: "메뉴", body: "홈에서 새 분석을 시작합니다. 끝난 분석은 분석 리포트, 모의투자 기록은 모의투자, 저장된 조건은 내 투자조건에서 봅니다." },
  { target: "home-idea", title: "투자하고 싶은 내용", body: "관심 있는 산업이나 종목, 기간, 원하는 점을 평소 말로 적습니다. 적지 않은 조건은 저장된 기본 투자조건을 씁니다." },
  { target: "home-examples", title: "예시 문장", body: "예시를 누르면 그 문장으로 바로 시작합니다." },
  { target: "home-detail", title: "상세 조건", body: "금액, 기간, 종목 수 같은 조건을 이번 분석에만 바꿉니다. 저장된 기본 투자조건은 그대로입니다." },
  { target: "home-submit", title: "분석 시작하기", body: "분석 모델이 아이디어를 해석하고, 모자란 조건을 이 카드에서 대화로 몇 가지 묻습니다. 마지막에 최종 조건을 확인하고 「이 조건으로 분석 실행」을 눌러야 분석이 실행됩니다." },
  { target: "home-process", title: "이렇게 진행돼요", body: "아이디어를 적은 뒤 리포트와 모의투자까지 다섯 단계로 진행됩니다. 리포트가 아직 없으면 이 탭이 먼저 열립니다." },
  { target: "home-trends", title: "요즘 강한 섹터", body: "최근 한 달 미국과 한국에서 성과가 좋았던 섹터입니다. 섹터를 고르면 많이 오른 종목이 나오고, 아래 문장을 누르면 그 문장으로 분석을 시작합니다." },
  { target: "home-profile", title: "내 투자조건", body: "분석에 기본으로 쓰는 조건입니다. 바꾸려면 내 투자조건 보기를 누릅니다. 아래 문장은 내 투자성향에 맞는 섹터입니다." },
  { target: "home-reports", title: "최근 리포트", body: "끝난 분석은 여기와 분석 리포트 메뉴에 모입니다. 리포트 읽는 법은 위쪽 「리포트 보는 법」에서 볼 수 있습니다." },
]
