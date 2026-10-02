AI Agent 기반 개인 맞춤형 주식 포트폴리오 전략 생성·검증 서비스를 위한 **데스크톱 웹 프로토타입**을 만들어줘.

목적은 실제 투자 서비스를 완성하는 것이 아니라, 사용자가 이 서비스를 어떻게 사용하는지 시뮬레이션할 수 있는 **간단한 클릭형 UX Prototype**을 만드는 것이다.

서비스의 핵심 질문은 다음과 같다.

“AI Agent가 사용자의 요구에 맞는 주식 포트폴리오 전략을 만들고, 이를 데이터로 검증하여 이해하기 쉬운 리포트로 전달할 수 있는가?”

지원 대상은 주식 투자이며, 시장은 우선 KOSPI / S&P500 / NASDAQ으로 제한한다.

---

## 1. 전체 사용자 시나리오

아래 사용자를 대표 Persona로 사용한다.

* 27세 직장인
* 투자 가능 금액: 3,000만 원
* 투자 기간: 3년 이상
* 위험 성향: 중간
* 투자 시장: 미국 주식
* 관심 분야: AI / 반도체
* 특정 종목에 너무 집중되는 것은 원하지 않음

사용자가 다음 질문을 입력한다.

“AI 산업이 앞으로 계속 성장할 것 같아서 관련 미국 주식에 투자하고 싶어요. 엔비디아는 너무 많이 오른 것 같아 부담스럽고 한 종목에 몰아서 투자하고 싶지는 않습니다. 3년 이상 투자할 생각이고 위험은 중간 정도까지 감수할 수 있습니다. 3천만 원 정도 투자한다면 어떤 포트폴리오가 적절할까요?”

이 질문을 기반으로 AI Agent가:

1. 사용자 투자조건 해석
2. 관련 종목 탐색
3. 가격·재무·뉴스 데이터 수집
4. 투자 논리 생성
5. 포트폴리오 전략 생성
6. 전략 규칙 검증
7. 과거 데이터 Backtest
8. 결과 해석
9. 최종 리포트 생성

순서로 동작하는 UX를 표현한다.

---

# Screen 1. 사용자 프로필 설정

최초 실행 시 보여주는 간단한 Onboarding 화면.

화면 제목:

“나에게 맞는 투자 분석을 위해 기본 정보를 알려주세요.”

입력 항목:

* 투자 가능 금액
* 투자 기간

  * 1년 미만
  * 1~3년
  * 3~5년
  * 5년 이상
* 위험 성향

  * 보수적
  * 중립적
  * 공격적
* 관심 시장

  * KOSPI
  * S&P500
  * NASDAQ
* 관심 산업 / 테마
* 최대 허용 개별 종목 비중
* ETF 포함 여부

예시값:

* 투자 가능금액: 30,000,000원
* 투자기간: 3년 이상
* 위험성향: 중립적
* 시장: S&P500 / NASDAQ
* 관심분야: AI, Semiconductor
* 단일종목 최대비중: 25%
* ETF 포함: 가능

하단 주요 CTA:

“설정 완료”

사용자는 나중에 이 정보를 수정할 수 있다는 문구를 작게 표시한다.

---

# Screen 2. Investment Agent Home

ChatGPT처럼 채팅 화면만 크게 만드는 형태는 피하고, **투자 분석을 시작하기 쉬운 Dashboard 형태**로 디자인한다.

상단:

“오늘 어떤 투자 판단을 도와드릴까요?”

중앙에 큰 자연어 입력창 배치.

Placeholder:

“예: AI 산업에 장기 투자하고 싶은데 NVIDIA 비중은 낮게 가져가고 싶어요.”

입력창 아래에는 현재 적용되는 사용자 조건을 작은 Chip 형태로 보여준다.

예:

* 3년+
* 중위험
* 미국주식
* AI / 반도체
* 종목 최대 25%

사용자가 조건을 수정할 수 있도록 “조건 수정” 버튼을 둔다.

빠른 질문 예시도 3개 정도 제공한다.

* “AI 관련 장기 포트폴리오 만들어줘”
* “현재 내 포트폴리오보다 위험을 낮춰줘”
* “배당 중심의 보수적인 포트폴리오를 만들어줘”

하단 CTA:

“AI 분석 시작”

---

# Screen 3. Agent Analysis Progress

사용자가 분석을 시작하면 즉시 결과 화면으로 넘어가지 않고,

**AI Agent가 실제로 여러 단계를 수행하고 있다는 것을 보여주는 화면**을 만든다.

Vertical Stepper 또는 Timeline 형태로 표시한다.

예:

✓ 사용자 투자조건 해석

✓ 관련 종목 후보 탐색
NVIDIA / Microsoft / Broadcom / TSMC / Alphabet / AMD

✓ 가격·재무 데이터 수집

✓ 최근 뉴스 및 시장정보 분석

● 포트폴리오 전략 생성 중

○ 전략 조건 검증

○ Historical Backtest

○ Report 생성

오른쪽 또는 하단에 현재까지 수집된 Evidence를 간단하게 보여준다.

예:

“현재 27개의 데이터 포인트와 12개의 뉴스 자료를 분석하고 있습니다.”

중요:
실제 Chain-of-Thought를 보여주지 말고,
“무엇을 수행하고 있는지”만 사용자에게 투명하게 보여준다.

---

# Screen 4. Final Investment Report

가장 중요한 화면이다.

일반적인 ChatGPT 답변 형태가 아니라 **전문 금융 리포트 + Dashboard** 형태로 만든다.

한 화면에서 주요 내용을 파악할 수 있도록 한다.

## A. 상단 Summary

제목:

“AI · Semiconductor Long-Term Portfolio”

Sub title:

“3년 이상 / 중위험 / 미국 주식 / AI·반도체”

AI 판단 요약:

“AI 산업 성장에 투자하면서 NVIDIA 단일 종목 집중도를 줄이기 위해 AI 인프라, 반도체 제조, Cloud 영역으로 위험을 분산한 포트폴리오입니다.”

옆에 작은 Badge:

“Moderate Risk”

---

## B. Recommended Portfolio

Donut chart + Table을 같이 사용한다.

예시:

Microsoft 25%
Broadcom 20%
TSMC 20%
Alphabet 15%
NVIDIA 10%
Cash 10%

각 종목을 클릭하면 간단한 선택 이유를 확인할 수 있도록 한다.

예:

NVIDIA
“AI accelerator exposure가 높지만 사용자 요청에 따라 비중을 10%로 제한했습니다.”

Microsoft
“AI + Cloud exposure와 상대적으로 낮은 개별 사업 집중도를 고려했습니다.”

---

## C. Why this Portfolio?

4개의 간단한 카드로 보여준다.

* NVIDIA 집중위험 완화
* AI 산업 내 사업영역 분산
* 종목 간 상관관계 고려
* 사용자 중위험 성향 반영

단순 자연어 설명보다 “사용자 요구가 전략에 어떻게 반영되었는지”가 명확하게 보이게 한다.

---

## D. Strategy Validation

사용자 요구와 실제 전략이 일치하는지 보여준다.

예:

✓ 미국주식만 사용

✓ AI / 반도체 중심

✓ NVIDIA ≤ 15%

✓ 단일 종목 최대 25%

✓ 포트폴리오 비중 합계 = 100%

✓ 분산투자 조건 만족

이 영역은 이 프로젝트의 핵심 기술인
“자연어 요구 → 실제 실행 가능한 전략”
변환이 제대로 되었음을 보여주는 역할을 한다.

---

## E. Historical Backtest

Portfolio와 S&P500의 누적수익률 Line Chart를 표시한다.

기간:

2018–2025

Metric Card:

Portfolio CAGR: 15.8%

Volatility: 21.4%

Sharpe Ratio: 0.74

Maximum Drawdown: -31.2%

Benchmark S&P500도 함께 작은 글씨로 비교한다.

중요:

“Backtest 결과는 미래 수익을 예측하거나 보장하지 않습니다.”

문구를 명확하게 표시한다.

Backtest의 목적은 “좋은 전략임을 증명”하는 것이 아니라
“이 투자 아이디어가 과거 시장에서 어떤 특성을 보였는지 확인”하는 것이라는 UX를 유지한다.

---

## F. Risk Analysis

간단한 Risk Card를 만든다.

예:

Overall Risk
MODERATE → MODERATE-HIGH

주요 위험:

* AI 산업 집중
* Semiconductor Cycle
* 높은 Growth Stock valuation
* 지정학적 위험
* 높은 기술주 상관관계

AI가 사용자 요구보다 위험이 높다고 판단한 경우 이를 명확하게 경고한다.

---

## G. Evidence / Sources

“이 분석에 사용된 정보” 영역을 만든다.

예:

Market Data

* Yahoo Finance Historical Price
* Company Financial Metrics

News

* NVIDIA AI demand 관련 기사
* Semiconductor export regulation 관련 기사
* TSMC AI chip demand 관련 기사

각 항목은 Source 이름, 날짜, 간단한 한 줄 설명을 보여준다.

사용자는 “모든 출처 보기”를 클릭할 수 있다.

LLM이 자기 지식으로 말하는 것이 아니라 실제 데이터에 근거한다는 느낌을 주는 것이 중요하다.

---

## H. AI Conclusion

리포트 하단에 짧은 최종 결론.

예:

“이 포트폴리오는 AI 산업 성장에 참여하면서 NVIDIA 단일 종목 집중도를 제한하도록 설계되었습니다.

과거 시뮬레이션에서는 시장 대비 높은 변동성을 보였기 때문에 현재 설정된 ‘중위험’ 성향보다 약간 공격적일 수 있습니다.

보다 보수적인 전략을 원한다면 현금 또는 방어적 자산 비중을 늘려 다시 분석할 수 있습니다.”

아래에 CTA 두 개:

“전략 수정하기”

“이 전략으로 다시 Backtest”

---

# Screen 5. Strategy Revision

사용자가 전략 수정하기를 누르면 간단한 Side Panel 또는 Modal을 띄운다.

예:

“어떤 부분을 변경할까요?”

Slider 또는 Input:

* 위험 수준 낮추기
* 단일 종목 최대비중
* NVIDIA 최대비중
* 종목 수
* 현금 비중
* Rebalancing 주기

그리고 자연어 추가 요구 입력:

“AI 비중은 유지하면서 변동성만 조금 낮춰줘.”

버튼:

“전략 다시 생성”

누르면 Analysis Progress를 짧게 보여준 후 업데이트된 Report로 이동한다.

---

# Optional Screen. Analysis History

왼쪽 Sidebar에 과거 분석 목록을 보여준다.

예:

AI Semiconductor Portfolio
2026.09.14

Dividend Portfolio
2026.09.10

Low Volatility Portfolio
2026.09.06

각 분석을 다시 열어볼 수 있도록 한다.

초기 Prototype에서는 실제 저장 기능 없이 UI만 구현해도 된다.

---

# 디자인 방향

전체적으로 전문 금융 서비스와 현대적인 AI SaaS의 중간 느낌으로 디자인한다.

키워드:

* Professional
* Minimal
* Trustworthy
* Financial Dashboard
* AI Agent
* Data driven

Robinhood처럼 지나치게 캐주얼하지 않고,
Bloomberg Terminal처럼 지나치게 복잡하지도 않게 한다.

화이트 또는 아주 연한 회색 기반의 Light Theme.

카드 기반 Dashboard.

넓은 여백과 명확한 정보 hierarchy를 사용한다.

강조 컬러는 한 가지 계열만 사용하고,
수익률의 상승/하락 컬러를 지나치게 많이 사용하지 않는다.

그래프와 데이터가 UI의 중심이어야 한다.

AI를 강조하기 위해 과도한 Gradient나 네온 효과를 사용하지 않는다.

---

# UX 원칙

1. 사용자가 복잡한 금융 용어를 몰라도 사용할 수 있어야 한다.

2. 중요한 투자조건은 항상 화면에서 확인할 수 있어야 한다.

3. AI가 왜 이런 결과를 만들었는지 설명할 수 있어야 한다.

4. 사용된 정보의 출처를 확인할 수 있어야 한다.

5. Backtest는 미래 예측이 아니라 Historical Simulation으로 표현한다.

6. 사용자가 Agent의 전략을 그대로 받아들이는 구조가 아니라,
   결과를 보고 수정하거나 다시 분석할 수 있어야 한다.

7. 자동매매 기능은 넣지 않는다.

8. 매수/매도 실행 버튼은 넣지 않는다.

9. 항상 다음 안내 문구를 Report 화면 하단에 표시한다.

“본 서비스는 투자 권유 또는 투자 자문을 제공하지 않으며, 투자 판단을 돕기 위한 정보 제공 및 시뮬레이션을 목적으로 합니다.”

---

# Prototype Interaction

클릭 가능한 Prototype으로 만들어줘.

Flow:

Profile Setup
→ Investment Agent Home
→ 질문 입력
→ Analysis Progress
→ Investment Report
→ Strategy Revision
→ Revised Report

각 화면은 실제 서비스처럼 자연스럽게 연결되도록 한다.

Desktop 기준 1440px 화면을 우선 디자인한다.

지금 단계에서는 Backend 연결이나 실제 API 연동은 필요 없고,
위 시나리오의 Mock Data를 사용해 실제 서비스처럼 보이는 UX Prototype을 만들어줘.

가장 중요한 화면은 Investment Report이며,
사용자가 약 10초 안에 다음 내용을 이해할 수 있도록 디자인한다.

1. 어떤 포트폴리오인가
2. 왜 이렇게 구성했는가
3. 나의 요구가 어떻게 반영되었는가
4. 과거에는 어떻게 작동했는가
5. 어떤 위험이 있는가
6. 어떤 데이터를 근거로 판단했는가
