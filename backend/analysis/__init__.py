"""MyFinSight 분석 패키지 (설계보고서 3안: 단계 고정 파이프라인 + Strategy Spec + 역할 한정 LLM).

모듈 대응 (docs/Module1~7.md):
  m1_request          Module1 사용자·요청 관리 (프로필, 요청 조립, 보충 질문 대화, 이력, 수정 요청)
  m2_data             Module2 금융 데이터 (Repository 위의 MarketData 파사드, 품질 판정, 디스크립터, 지표, 뉴스 근거)
  m3_selection        Module3 종목 선정·전략 생성 (의도 해석, 후보 검색, 분류, 정량 선정, 기업별 근거)
  m4_portfolio        Module4 포트폴리오 구성 (시장모형, 템플릿 비중, 뉴스 뷰, Black-Litterman, construct())
  m5_backtest_report  Module5 백테스트·검증·리포트
  m6_tracking         Module6 모의투자
  executor            M0-05 실행기·큐·워커
  api                 M0-06 서비스 API (Module7 React 화면이 호출)
  common              설정·LLM 호출기·로컬 JSON 저장소·JSON 입출력

규칙: 분석 코드는 팀 DB를 backend.db Repository 로만 읽는다 (외부 호출 0건, K3·C-10).
`module_mockup/` 은 이 패키지의 원본 실험 기록이며 수정하지 않는다.
"""
