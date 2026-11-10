import type { TourStep } from "./steps"

/** 홈 둘러보기 (처음이신가요? MyFinSight 둘러보기). target 은 홈·사이드바 요소의 data-tour 값. 대상이 화면에 없으면 말풍선만 가운데에 뜬다. */
export const HOME_TOUR_STEPS: TourStep[] = [
  { target: "home-menu", title: "메뉴", body: "홈에서 새 분석을 시작합니다. 끝난 분석은 분석 리포트, 모의투자 기록은 모의투자, 저장된 조건은 내 투자조건에서 봅니다." },
  { target: "home-trends", title: "요즘엔 뭐가 좋아요?", body: "최근 한 달 미국과 한국에서 성과가 좋았던 섹터입니다. 섹터를 고르고 아래 문장을 누르면 그 문장으로 분석을 시작합니다." },
  { target: "home-idea", title: "투자하고 싶은 내용", body: "관심 있는 산업이나 종목, 기간, 원하는 점을 평소 말로 적습니다. 적지 않은 조건은 저장된 기본 투자조건을 씁니다." },
  { target: "home-examples", title: "예시 문장", body: "예시를 누르면 그 문장으로 바로 시작합니다." },
  { target: "home-detail", title: "상세 조건", body: "금액, 기간, 종목 수 같은 조건을 이번 분석에만 바꿉니다. 저장된 기본 투자조건은 그대로입니다." },
  { target: "home-submit", title: "투자조건 확인하기", body: "모자란 조건을 몇 가지 묻고 최종 조건을 보여 줍니다. 조건을 확인하고 분석 시작을 눌러야 분석이 실행됩니다." },
  { target: "home-profile", title: "저장된 기본 투자조건", body: "분석에 기본으로 쓰는 조건입니다. 바꾸려면 내 투자조건 보기를 누릅니다. 맨 아래 문장은 내 투자성향에 맞는 섹터입니다." },
  { target: "home-reports", title: "최근 분석 리포트", body: "끝난 분석은 여기와 분석 리포트 메뉴에 모입니다. 리포트 읽는 법은 리포트 보는 법 둘러보기에서 볼 수 있습니다." },
]
