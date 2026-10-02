기존에 만든 **AI Agent 기반 개인 맞춤형 주식 포트폴리오 전략 생성·검증 서비스 UI**를 유지하면서, 새롭게 **Portfolio Tracking 기능**을 추가해줘.

기존 사이트의 전체 디자인 시스템, 레이아웃, typography, card style, color system은 그대로 유지하고 새로운 기능만 자연스럽게 확장한다.

---

## 핵심 개념

서비스에는 두 가지 검증 기능이 있다.

### 1. Backtest

전략 생성 이전의 과거 데이터를 사용해

“이 전략이 과거 시장에서 어떤 수익률, 변동성, 최대낙폭, 위험 특성을 보였는가?”

를 확인하는 **Historical Simulation**이다.

Backtest는 전략이 미래에도 좋은 성과를 낼 것임을 증명하는 기능이 아니다.

---

### 2. Portfolio Tracking

AI가 포트폴리오를 생성한 시점 이후부터 실제 시장 데이터를 계속 받아

“이 포트폴리오를 실제로 그때부터 운용했다고 가정하면 현재까지 어떤 결과가 나왔는가?”

를 보여주는 **Forward Paper Tracking** 기능이다.

실제 돈을 투자하거나 주문을 실행하지 않는다.

생성된 포트폴리오를 가상의 자산으로 지속적으로 추적한다.

중요:

한 번 Tracking을 시작한 포트폴리오는 이후 AI가 임의로 변경하지 않는다.

사용자 투자성향이나 상황이 바뀌어 새로운 전략을 원하면 새로운 Portfolio Report를 생성해야 한다.

---

# 1. Investment Report 화면에 Tracking CTA 추가

기존 Investment Report 하단 또는 Recommended Portfolio 영역 근처에 다음 Card를 추가한다.

제목:

**Track this Portfolio**

설명:

“이 포트폴리오를 오늘부터 실제 시장 데이터로 모의 추적할 수 있습니다.”

추가 설명:

“Tracking을 시작하면 현재 포트폴리오 구성과 전략이 저장되며 이후 시장 가격에 따라 가상의 포트폴리오 가치가 업데이트됩니다.”

Primary CTA:

**Start Tracking**

Secondary text:

“실제 매매 또는 주문은 발생하지 않습니다.”

---

# 2. Tracking 시작 Modal

사용자가 Start Tracking을 클릭하면 Modal을 보여준다.

제목:

**Start Portfolio Tracking**

다음 정보를 보여준다.

Initial Portfolio Value

₩30,000,000

Tracking Start Date

2026.09.15

Portfolio

* Microsoft 25%
* Broadcom 20%
* TSMC 20%
* Alphabet 15%
* NVIDIA 10%
* Cash 10%

Strategy

* Long-term AI Growth
* Moderate Risk
* Quarterly Rebalancing
* Maximum single stock weight: 25%

안내문:

“Tracking을 시작하면 현재 전략은 고정됩니다. 이후 투자조건을 변경하고 싶다면 새로운 분석을 생성해야 합니다.”

CTA:

**Start Paper Tracking**

Cancel

---

# 3. Sidebar에 Portfolio Tracking 메뉴 추가

기존 왼쪽 Sidebar에 다음 메뉴를 추가한다.

Home

New Analysis

Reports

**Portfolio Tracking**

Profile

Portfolio Tracking 옆에는 현재 추적 중인 포트폴리오 개수를 작은 Badge로 표시한다.

예:

Portfolio Tracking  3

---

# 4. Portfolio Tracking Dashboard

새로운 페이지를 만든다.

페이지 제목:

**Tracked Portfolios**

설명:

“AI가 생성한 포트폴리오가 생성 이후 실제 시장에서 어떻게 움직이고 있는지 확인할 수 있습니다.”

상단에는 Summary Card를 배치한다.

예:

Active Portfolios
3

Total Simulated Value
₩92,400,000

Average Return
+4.8%

Best Portfolio
AI Semiconductor +8.4%

---

그 아래 각각의 포트폴리오를 Card 형태로 보여준다.

예:

### AI Semiconductor Portfolio

Created

2026.09.15

Tracking

24 Days

Initial Value

₩30,000,000

Current Simulated Value

₩31,260,000

Return Since Creation

+4.2%

Benchmark

S&P500 +2.7%

Risk

Moderate

Card 안에 작은 Portfolio Performance Line Chart를 넣는다.

CTA:

**View Tracking**

또 다른 예:

### Dividend Stability Portfolio

Created 2026.08.20

Return +1.8%

Tracking 50 Days

Benchmark +2.2%

등 여러 개의 이전 Portfolio가 존재하는 것처럼 Mock Data를 사용한다.

---

# 5. Portfolio Tracking 상세 화면

사용자가 View Tracking을 클릭하면 해당 포트폴리오의 상세 Tracking Dashboard를 보여준다.

상단:

**AI Semiconductor Portfolio**

Status Badge:

TRACKING

Sub text:

Created 2026.09.15
Tracking since 2026.09.15

---

## A. Performance Since Creation

가장 중요한 영역.

큰 Line Chart:

**Portfolio vs Benchmark**

Portfolio와 S&P500의 가치 변화를 생성일 이후부터 현재까지 보여준다.

Y축:

Portfolio Value

X축:

Date

아래 Metric Cards:

Current Value
₩31,260,000

Return Since Creation
+4.2%

S&P500
+2.7%

Relative Performance
+1.5%

Maximum Drawdown
-6.8%

Volatility
17.4%

---

# 6. Backtest와 Tracking을 명확하게 비교

Tracking 상세 화면 안에 작은 비교 UI를 추가한다.

Tabs:

**Live Tracking**

Historical Backtest

Live Tracking을 선택하면:

“2026.09.15 이후 실제 시장 데이터 기준”

Historical Backtest를 선택하면:

“2018–2026 과거 시장 데이터를 이용한 시뮬레이션”

두 기능의 의미를 사용자가 헷갈리지 않게 아래 설명을 보여준다.

Historical Backtest

“전략 생성 이전의 과거 시장에서 이 전략이 어떤 특성을 보였는지 확인합니다.”

Portfolio Tracking

“전략 생성 이후 실제 시장에서 이 포트폴리오가 어떻게 움직이고 있는지 확인합니다.”

---

# 7. Portfolio Composition

Tracking 중인 현재 포트폴리오 구성을 보여준다.

Donut Chart + Table

Microsoft 25%

Broadcom 20%

TSMC 20%

Alphabet 15%

NVIDIA 10%

Cash 10%

중요:

이 화면에서는 종목 비중을 직접 수정할 수 없도록 한다.

상단에 작은 Lock icon과 함께:

**Strategy Locked**

“This portfolio is tracked using the strategy defined at creation.”

이라고 표시한다.

---

# 8. Original Investment Thesis

AI가 처음 이 포트폴리오를 생성했던 이유를 다시 볼 수 있게 한다.

제목:

**Original Investment Thesis**

예:

“AI 산업 성장에 참여하면서 NVIDIA 단일 종목 집중 위험을 제한하기 위해 Cloud, Semiconductor Manufacturing, AI Infrastructure 분야로 분산한 포트폴리오입니다.”

User Constraints:

* Investment horizon: 3+ years
* Risk: Moderate
* US Equities
* AI / Semiconductor
* NVIDIA ≤ 15%
* Max stock weight ≤ 25%

버튼:

**View Original Report**

---

# 9. Tracking Timeline

Portfolio Tracking이 어떻게 진행됐는지 Timeline으로 보여준다.

예:

2026.09.15

Portfolio Created

Initial Value ₩30,000,000

2026.09.30

Portfolio +2.1%

S&P500 +1.4%

2026.10.07

Largest Drawdown -4.8%

2026.10.09

Portfolio recovered to +3.4%

Mock Data로 실제 포트폴리오가 지속적으로 추적되고 있다는 느낌을 준다.

---

# 10. 사용자에게 해석 제공

Tracking 화면 하단에 AI Summary Card를 둔다.

제목:

**AI Tracking Summary**

예:

“포트폴리오 생성 이후 24일 동안 +4.2%의 모의 수익률을 기록했습니다.

같은 기간 S&P500은 +2.7% 상승했습니다.

다만 최근 반도체 종목 변동성이 확대되면서 최대 -6.8%의 일시적 낙폭이 발생했습니다.

이는 최초 Backtest에서 확인된 전략의 높은 기술주 변동성과 일관된 특성입니다.”

중요:

AI가 매번 새로운 투자전략을 생성하는 것이 아니라,

**현재 Tracking 결과와 최초 전략의 특성을 비교·해석하는 역할**을 한다.

---

# 11. New Analysis 기능

Tracking 중인 포트폴리오를 수정하는 기능은 제공하지 않는다.

대신 다음 CTA를 제공한다.

**Create New Strategy**

설명:

“현재 투자조건이 바뀌었다면 기존 Portfolio를 수정하지 않고 새로운 Portfolio Report를 생성합니다.”

예를 들어 사용자가 클릭하면 New Analysis 화면으로 이동하며 기존 사용자 Profile은 자동으로 불러온다.

---

# 12. Report / Session 구조

각 Portfolio는 하나의 독립적인 Report / Analysis Session으로 취급한다.

ChatGPT의 여러 개 대화처럼 사용자는 여러 Portfolio Report를 가질 수 있다.

예:

AI Semiconductor Portfolio

Dividend Portfolio

Low Volatility Portfolio

Tech Growth Portfolio

각 Report에는 다음 정보가 연결된다.

* 당시 User Request
* 당시 User Profile
* AI Investment Thesis
* Portfolio
* Strategy
* Historical Backtest
* Data Sources
* Portfolio Tracking

사용자의 일반적인 투자 성향과 프로필은 별도의 User Memory에 저장하지만,

각 Portfolio의 Strategy는 해당 Portfolio가 생성되었던 시점의 조건으로 고정한다.

---

# 디자인 방향

기존 사이트의 디자인을 유지한다.

새로운 Tracking Dashboard는 금융 Portfolio Management Dashboard처럼 표현하되 지나치게 복잡하지 않게 한다.

가장 중요한 정보 hierarchy:

1. 현재 Portfolio 가치
2. 생성 이후 수익률
3. Benchmark 대비 성과
4. Performance Chart
5. 현재 Portfolio 구성
6. 최초 투자 논리
7. Historical Backtest와의 차이
8. Tracking Timeline

사용자가 화면에 들어온 뒤 약 5초 안에

“내가 예전에 만든 포트폴리오가 지금 어떻게 되고 있는가?”

를 이해할 수 있어야 한다.

---

# Prototype Flow

기존 Prototype에 아래 흐름을 추가한다.

Investment Report

→ Start Tracking

→ Tracking Confirmation Modal

→ Portfolio Tracking Dashboard

→ Tracked Portfolio Detail

→ Historical Backtest / Live Tracking 전환

→ Original Report 확인

→ Create New Strategy

실제 API나 Backend 연결은 필요하지 않으며 Mock Data를 사용한다.

단, 실제 서비스처럼 Portfolio 생성일 이후 시간이 지나면서 값이 업데이트되는 느낌이 나도록 realistic mock data와 chart를 사용한다.

매수, 매도, 주문 실행 기능은 절대 추가하지 않는다.

항상 화면 하단에 다음 문구를 작게 표시한다.

“Portfolio Tracking은 실제 투자가 아닌 모의 성과 추적 기능이며, 미래 수익을 예측하거나 보장하지 않습니다.”
