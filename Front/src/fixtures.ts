import { APP_CONFIG } from "./config"
import { calculateMetrics } from "./lib"
import type {
  Allocation,
  EffectiveConditions,
  Evidence,
  ExecutionRecord,
  PaperPortfolio,
  Point,
  Profile,
  Report,
  ReportNarrative,
  StrategyRules,
} from "./types"

export const DEMO_PROFILE: Profile = {
  amountKrw: 30_000_000,
  horizonMonths: 36,
  computedTendency: "위험중립형",
  finalTendency: "위험중립형",
  tendencyOverridden: false,
  lossTolerancePct: 20,
  industries: ["AI·소프트웨어", "반도체"],
  preferences: ["성장", "대형주"],
  memo: "장기 성장성을 선호하지만 한 종목에 집중하고 싶지 않습니다.",
  excludedTickers: [],
  globalCapPct: 25,
  securityCaps: { NVDA: 10 },
  allowEtf: false,
  market: "미국",
}

const aiConditions: EffectiveConditions = {
  ...DEMO_PROFILE,
  namedTickers: ["NVDA"],
  analysisOverrides: ["securityCaps"],
}

const aiStrategy: StrategyRules = {
  universe: "미국 대형 기술주와 반도체 기업",
  selectionRule: "lowest-volatility",
  selectionCount: 5,
  lookbackMonths: 12,
  weightingRule: "inverse-volatility",
  exclusions: [],
  globalCapPct: 25,
  securityCaps: { NVDA: 10 },
  rebalance: "분기별",
  assumptions: [
    "매수 포지션만 운용",
    "투자금 전액 배분",
    "레버리지와 공매도 미사용",
    "현금 미보유",
    "분기 첫 거래일 종가로 재조정",
  ],
}

const aiCapitalUsd = 20_573.31
const aiWeights = [
  ["MSFT", "Microsoft", 25, 24.8, 25.6],
  ["AVGO", "Broadcom", 22, 31.2, 20.3],
  ["TSM", "TSMC", 20, 34.0, 18.7],
  ["GOOGL", "Alphabet", 23, 29.6, 21.1],
  ["NVDA", "NVIDIA", 10, 45.9, 14.3],
] as const

const aiRoles: Record<string, string> = {
  MSFT: "기업용 AI 소프트웨어와 클라우드 수요",
  AVGO: "맞춤형 가속기와 데이터센터 연결 반도체",
  TSM: "첨단 반도체 위탁생산",
  GOOGL: "AI 기반 광고·클라우드 플랫폼",
  NVDA: "범용 AI 가속 컴퓨팅",
}

const aiAllocation: Allocation[] = aiWeights.map(
  ([ticker, company, weight, volatility, uncapped]) => ({
    ticker,
    company,
    weight,
    usd: Math.round(aiCapitalUsd * (weight / 100) * 100) / 100,
    krw: Math.round(30_000_000 * (weight / 100)),
    selectionReason: `${aiRoles[ticker]}에 직접 연결되는 사업을 보유하고 있으며, 관련 기업 자료에서 AI 투자 확대가 각 사업의 수요로 이어지는 경로를 확인했습니다.`,
    weightingReason: `최근 12개월 연환산 변동성 ${volatility.toFixed(1)}%를 이용한 역변동성 계산의 한도 적용 전 비중은 ${uncapped.toFixed(1)}%였습니다. 종목별 한도와 재배분을 거쳐 ${weight.toFixed(1)}%로 확정했습니다.`,
    role: aiRoles[ticker],
    capPct: ticker === "NVDA" ? 10 : 25,
    capAdjusted: ticker === "NVDA" || ticker === "MSFT",
    risk:
      ticker === "TSM"
        ? "첨단 공정 수요의 집중과 대만 생산기지 관련 지정학적 위험"
        : "AI 설비투자 둔화와 기술주 밸류에이션 조정 위험",
    evidenceId: `qual-${ticker.toLowerCase()}`,
  }),
)
aiAllocation[aiAllocation.length - 1].usd =
  Math.round(
    (aiCapitalUsd -
      aiAllocation.slice(0, -1).reduce((sum, item) => sum + item.usd, 0)) *
      100,
  ) / 100

const aiSeries: Point[] = [
  { date: "2019-01-02", portfolio: 100, benchmark: 100, drawdown: 0 },
  { date: "2020-01-02", portfolio: 124, benchmark: 128, drawdown: -7.4 },
  { date: "2021-01-04", portfolio: 161, benchmark: 151, drawdown: -5.9 },
  { date: "2022-01-03", portfolio: 192, benchmark: 191, drawdown: -8.2 },
  { date: "2023-01-03", portfolio: 141, benchmark: 158, drawdown: -31.2 },
  { date: "2024-01-02", portfolio: 184, benchmark: 196, drawdown: -14.6 },
  { date: "2025-02-28", portfolio: 221, benchmark: 239, drawdown: -6.1 },
]

const aiEvidence: Evidence[] = [
  {
    id: "industry-capex",
    title: "클라우드 사업자의 AI 인프라 투자 확대",
    value: "주요 클라우드 기업이 AI 인프라를 핵심 투자영역으로 제시",
    provider: "Microsoft Corporation",
    sourceTitle: "Microsoft 2024 Annual Report",
    publicationDate: "2024-07-30",
    collectedAt: "2025-02-28 17:30",
    usedFor:
      "AI 인프라 수요가 클라우드, 가속기, 네트워크, 파운드리로 이어지는 경로 평가",
    isDemo: true,
    section: "Business; Management’s Discussion and Analysis",
    excerpt:
      "회사는 클라우드와 AI 인프라 수요에 대응하기 위한 데이터센터 투자를 주요 자본지출 항목으로 설명한다.",
    recordId: "QR-AI-IND-001",
    supportedClaim:
      "AI 수요가 소프트웨어 사용 증가뿐 아니라 데이터센터 설비투자로 연결되고 있다.",
  },
  {
    id: "industry-cycle",
    title: "AI 수요와 반도체 공급망의 연결",
    value: "가속기, 네트워크 반도체, 첨단 공정이 동일한 설비투자 주기에 노출",
    provider: "TSMC",
    sourceTitle: "TSMC 2023 Annual Report",
    publicationDate: "2024-04-18",
    collectedAt: "2025-02-28 17:34",
    usedFor: "포트폴리오 내 공통 경기요인과 공급망 집중 위험 평가",
    isDemo: true,
    section: "Industry Overview; Business",
    excerpt:
      "첨단 공정과 고성능 컴퓨팅 수요가 성장 동력으로 제시되며, 고객 수요와 설비투자 계획이 긴밀히 연결되어 있다.",
    recordId: "QR-AI-IND-002",
    supportedClaim:
      "기업 수는 분산되어도 보유종목 대부분이 같은 AI 설비투자 주기의 영향을 받는다.",
  },
  {
    id: "qual-msft",
    title: "Microsoft의 클라우드·AI 사업 구조",
    value: "Azure 인프라와 기업용 소프트웨어를 함께 제공",
    provider: "Microsoft Corporation",
    sourceTitle: "Microsoft 2024 Annual Report",
    publicationDate: "2024-07-30",
    collectedAt: "2025-02-28 17:31",
    usedFor: "Microsoft 후보 편입과 포트폴리오 역할 판단",
    isDemo: true,
    section:
      "Business — Intelligent Cloud and Productivity and Business Processes",
    excerpt:
      "Azure와 기업용 생산성 제품은 클라우드 인프라와 응용 소프트웨어를 함께 제공하는 사업구조를 형성한다.",
    recordId: "QR-MSFT-2024-10K",
    supportedClaim:
      "Microsoft는 AI 인프라 투자와 기업용 소프트웨어 수익화에 동시에 노출된다.",
  },
  {
    id: "qual-avgo",
    title: "Broadcom의 반도체·인프라 소프트웨어 사업",
    value: "네트워크·맞춤형 반도체와 인프라 소프트웨어를 함께 운영",
    provider: "Broadcom Inc.",
    sourceTitle: "Broadcom 2024 Form 10-K",
    publicationDate: "2024-12-20",
    collectedAt: "2025-02-28 17:32",
    usedFor: "Broadcom 후보 편입과 NVIDIA 외 가속기 공급망 노출 평가",
    isDemo: true,
    section: "Business — Semiconductor Solutions and Infrastructure Software",
    excerpt:
      "반도체 부문은 데이터센터 네트워킹과 맞춤형 제품을 포함하며, 소프트웨어 부문은 별도의 반복 수익원을 제공한다.",
    recordId: "QR-AVGO-2024-10K",
    supportedClaim:
      "Broadcom은 AI 데이터센터의 연결 및 맞춤형 연산 수요에 참여하면서 사업구조가 GPU 한 영역에만 묶이지 않는다.",
  },
  {
    id: "qual-tsm",
    title: "TSMC의 첨단 공정과 위탁생산 모델",
    value: "독립 파운드리로서 다수 설계회사의 첨단 반도체를 생산",
    provider: "TSMC",
    sourceTitle: "TSMC 2023 Annual Report",
    publicationDate: "2024-04-18",
    collectedAt: "2025-02-28 17:34",
    usedFor: "설계회사와 구분되는 제조 노출의 편입 근거 평가",
    isDemo: true,
    section: "Business — Foundry Services and Advanced Technologies",
    excerpt:
      "회사는 자체 제품을 설계하지 않는 전업 파운드리 모델과 첨단 공정 투자를 경쟁력의 핵심으로 설명한다.",
    recordId: "QR-TSM-2023-AR",
    supportedClaim:
      "TSMC는 특정 설계회사의 단일 제품보다 첨단 반도체 생산 수요 전반에 노출된다.",
  },
  {
    id: "qual-googl",
    title: "Alphabet의 광고·클라우드·AI 투자 구조",
    value: "광고 현금흐름과 Google Cloud가 AI 연구 및 인프라 투자를 뒷받침",
    provider: "Alphabet Inc.",
    sourceTitle: "Alphabet 2024 Form 10-K",
    publicationDate: "2025-02-05",
    collectedAt: "2025-02-28 17:36",
    usedFor: "Alphabet의 플랫폼 역할과 투자부담 평가",
    isDemo: true,
    section: "Business; Capital Resources and Liquidity",
    excerpt:
      "회사는 Google Services와 Google Cloud를 주요 사업으로 구분하고 AI 기술과 인프라에 지속적으로 투자한다고 설명한다.",
    recordId: "QR-GOOGL-2024-10K",
    supportedClaim:
      "Alphabet은 AI 인프라 비용을 부담하는 동시에 광고와 클라우드에서 활용 기회를 보유한다.",
  },
  {
    id: "qual-nvda",
    title: "NVIDIA의 가속 컴퓨팅 사업",
    value: "데이터센터용 GPU와 네트워킹 제품을 통합 제공",
    provider: "NVIDIA Corporation",
    sourceTitle: "NVIDIA 2024 Form 10-K",
    publicationDate: "2024-02-21",
    collectedAt: "2025-02-28 17:38",
    usedFor: "AI 가속기 핵심 노출의 필요성과 집중위험 평가",
    isDemo: true,
    section: "Business — Compute & Networking",
    excerpt:
      "데이터센터 플랫폼은 가속 컴퓨팅 제품과 네트워킹을 결합하며, 고객의 AI 학습 및 추론 작업을 주요 사용처로 제시한다.",
    recordId: "QR-NVDA-2024-10K",
    supportedClaim:
      "NVIDIA는 AI 연산 수요에 가장 직접적으로 노출되지만 높은 변동성과 집중위험도 함께 가진다.",
  },
  {
    id: "quant-ai",
    title: "가격·변동성 계산 기록",
    value: "2019-01-02~2025-02-28 조정 종가, 일별 수익률, 12개월 연환산 변동성",
    provider: "MyFinSight 가격 데이터베이스",
    sourceTitle: "미국 상장주식 조정 종가",
    marketDate: "2025-02-28",
    collectedAt: "2025-02-28 18:10",
    usedFor: "역변동성 배분, 과거 성과, 최대 낙폭 계산",
    isDemo: true,
    section: "가격 및 기업행동 반영 시계열",
    excerpt:
      "MSFT 24.8%, AVGO 31.2%, TSM 34.0%, GOOGL 29.6%, NVDA 45.9%의 12개월 연환산 변동성을 배분 계산에 사용했다.",
    recordId: "PX-AI-20250228",
    supportedClaim:
      "정확한 배분 비중은 정성 판단이 아니라 역변동성 계산과 비중 한도에서 결정되었다.",
  },
]

const aiNarrative: ReportNarrative = {
  overallJudgment: [
    {
      text: "이 전략의 목적은 AI 산업의 장기 성장에 참여하되 NVIDIA 한 종목에 대한 의존을 10% 이하로 제한하는 것이다. 투자기간 3년, 위험중립형 투자성향, 과거 손실 감내 수준 20%를 반영해 미국 대형 기술주와 반도체 기업을 투자 대상으로 삼았다. 따라서 가장 높은 단기 수익을 추구하기보다 AI 수요가 매출로 연결되는 서로 다른 사업단계를 함께 보유하는 것이 핵심이다.",
      citationIds: ["industry-capex", "qual-nvda"],
    },
    {
      text: "중심 판단은 AI 투자가 소프트웨어 사용 증가만의 이야기가 아니라 데이터센터, 가속기, 네트워크 반도체, 첨단 제조공정으로 이어지는 설비투자 주기라는 점이다. Microsoft와 Alphabet은 인프라 투자자이면서 클라우드와 소프트웨어를 통해 이를 수익화하는 기업이고, NVIDIA와 Broadcom은 연산과 연결 장비를, TSMC는 첨단 반도체 생산을 담당한다. 이 조합은 한 제품에 대한 의존은 낮추지만 AI 설비투자라는 공통 경제요인까지 없애지는 않는다.",
      citationIds: ["industry-capex", "industry-cycle"],
    },
    {
      text: "기업 편입은 각 회사의 사업자료에서 확인되는 AI 가치사슬상의 역할을 바탕으로 했고, 정확한 비중은 정성 판단이 아니라 최근 12개월 변동성의 역수와 사용자 한도로 계산했다. 특히 NVIDIA는 핵심 가속기 노출을 유지할 필요가 있었지만, 14.3%의 한도 적용 전 비중을 사용자 요청에 따라 10%로 낮췄다. Microsoft도 공통 한도 25%를 적용했으며, 줄어든 비중은 나머지 종목에 다시 배분했다.",
      citationIds: ["qual-msft", "qual-nvda", "quant-ai"],
    },
    {
      text: "과거 결과는 이 선택의 대가를 분명히 보여준다. 포트폴리오는 분석기간에 121% 상승했지만 같은 기간 비교지수는 139% 상승해 18%p 뒤처졌다. 또한 2022년을 포함한 하락구간의 최대 낙폭은 -31.2%로 사용자의 손실 감내 수준 20%보다 컸다. 따라서 이 전략은 AI 집중을 완화한 전략이지 안정형 전략은 아니며, 현재의 목표에 적합하려면 사용자가 비교지수 대비 초과수익보다 NVIDIA 집중 제한과 사업단계 분산을 더 중요하게 여겨야 한다.",
      citationIds: ["quant-ai"],
    },
  ],
  industryAnalysis: [
    {
      text: "AI 산업의 수요는 기업의 모델 사용량 증가가 클라우드 연산 수요로 이어지고, 다시 데이터센터 투자와 반도체 주문으로 연결되는 구조를 가진다. Microsoft의 사업자료는 클라우드와 AI 인프라 수요에 대응한 데이터센터 투자를 주요 자본지출로 설명한다. 이 기록은 Microsoft 자체의 성장기회뿐 아니라 NVIDIA의 가속기, Broadcom의 네트워크·맞춤형 반도체, TSMC의 첨단 생산능력에 대한 수요가 같은 투자결정에서 파생된다는 점을 뒷받침한다.",
      citationIds: ["industry-capex", "qual-avgo", "qual-tsm"],
    },
    {
      text: "이 구조에서 Microsoft와 Alphabet은 비용 부담과 수익화 기회를 동시에 가진다. 두 회사가 데이터센터 투자를 늘리면 반도체 공급망에는 주문이 발생하지만, 클라우드와 응용 서비스의 매출이 투자비를 충분히 회수하지 못하면 향후 설비투자 속도가 낮아질 수 있다. 따라서 AI 사용 확대 자체보다 클라우드 성장과 자본지출의 관계를 함께 살펴야 한다.",
      citationIds: ["qual-msft", "qual-googl"],
    },
    {
      text: "포트폴리오는 다섯 기업에 나뉘어 있지만 경제적 분산은 제한적이다. TSMC 자료가 보여주듯 첨단 공정 수요는 고객사의 투자계획과 밀접하고, NVIDIA와 Broadcom 역시 데이터센터 예산의 영향을 받는다. AI 설비투자가 예상보다 오래 지속되면 가치사슬 여러 단계가 함께 수혜를 받을 수 있지만, 투자 회수기간이 길어지거나 고객이 지출을 줄이면 보유종목 대부분이 동시에 압력을 받을 수 있다.",
      citationIds: ["industry-cycle", "qual-nvda", "qual-avgo"],
    },
  ],
  companyAnalyses: [
    {
      ticker: "MSFT",
      heading: "Microsoft — 인프라 투자와 기업용 수익화의 연결",
      paragraphs: [
        {
          text: "Microsoft는 Azure 인프라와 기업용 생산성 소프트웨어를 함께 보유한다. 연차보고서에서 두 사업은 각각 Intelligent Cloud와 Productivity and Business Processes의 핵심으로 제시된다. 이는 AI 연산 수요를 받는 인프라 사업과 기업 고객에게 기능을 판매하는 응용 소프트웨어가 한 회사 안에 있다는 뜻이다.",
          citationIds: ["qual-msft"],
        },
        {
          text: "포트폴리오에서는 AI 설비투자와 소프트웨어 수익화 사이를 연결하는 중심 역할을 맡는다. 다만 대규모 데이터센터 지출이 실제 매출과 현금흐름으로 전환되는 속도가 기대에 못 미치면 이 장점은 오히려 투자부담으로 바뀔 수 있다. 24.8%의 측정 변동성은 다섯 종목 중 가장 낮아 한도 적용 전 25.6%가 계산됐고, 공통 한도에 따라 최종 25%를 배분했다.",
          citationIds: ["qual-msft", "quant-ai"],
        },
      ],
    },
    {
      ticker: "AVGO",
      heading: "Broadcom — 맞춤형 연산과 네트워크의 보완 노출",
      paragraphs: [
        {
          text: "Broadcom의 반도체 사업은 데이터센터 네트워킹과 맞춤형 제품을 포함하고, 인프라 소프트웨어가 별도의 사업축을 이룬다. 이는 AI 데이터센터 지출에 참여하되 범용 GPU와는 다른 제품군을 통해 수요를 받는 구조다. NVIDIA 중심의 연산 노출을 보완할 후보로 선택한 이유다.",
          citationIds: ["qual-avgo"],
        },
        {
          text: "맞춤형 반도체 확대는 기회지만 고객 집중과 프로젝트별 수요 변동이 커질 수 있다. 또한 소프트웨어 사업이 있다고 해서 반도체 주기의 영향이 사라지는 것은 아니다. 31.2%의 변동성으로 계산한 한도 적용 전 비중은 20.3%였고, NVIDIA와 Microsoft에서 줄어든 비중 일부를 재배분해 최종 22%가 됐다.",
          citationIds: ["qual-avgo", "quant-ai"],
        },
      ],
    },
    {
      ticker: "TSM",
      heading: "TSMC — 설계회사를 가로지르는 첨단 제조 기반",
      paragraphs: [
        {
          text: "TSMC는 자체 반도체 제품을 판매하기보다 여러 고객의 설계를 생산하는 전업 파운드리다. 이 사업모델은 특정 가속기 브랜드의 점유율 변화와 별개로 첨단 공정 수요에 접근할 수 있게 한다. NVIDIA와 Broadcom을 함께 보유하면서도 제조단계의 수익원을 추가한다는 점이 편입 근거다.",
          citationIds: ["qual-tsm"],
        },
        {
          text: "그러나 고객 다변화가 생산지역과 설비투자 위험까지 분산시키지는 않는다. 첨단 공정 투자규모가 크고 대만 생산기지에 대한 지정학적 우려가 기업가치에 영향을 줄 수 있다. 측정 변동성은 34.0%, 한도 적용 전 비중은 18.7%였으며 한도 조정분을 재배분한 뒤 20%를 배정했다.",
          citationIds: ["qual-tsm", "industry-cycle", "quant-ai"],
        },
      ],
    },
    {
      ticker: "GOOGL",
      heading: "Alphabet — 광고 현금흐름과 클라우드 AI의 조합",
      paragraphs: [
        {
          text: "Alphabet은 광고 중심의 Google Services와 Google Cloud를 함께 운영하며 AI 기술과 인프라에 지속적으로 투자한다고 설명한다. 광고에서 창출하는 현금이 연구와 데이터센터 투자 여력을 제공하고, Cloud는 외부 기업의 AI 사용을 매출로 전환할 통로가 된다.",
          citationIds: ["qual-googl"],
        },
        {
          text: "반대편에는 검색 서비스의 변화가 기존 광고경제성에 미칠 영향과 높은 자본지출 부담이 있다. 포트폴리오에서 Alphabet은 Microsoft와 함께 플랫폼·소프트웨어 노출을 제공하지만 두 기업 모두 같은 데이터센터 투자비 증가에 노출된다. 29.6% 변동성을 사용한 한도 적용 전 비중 21.1%에 조정분을 배분해 최종 23%가 됐다.",
          citationIds: ["qual-googl", "industry-capex", "quant-ai"],
        },
      ],
    },
    {
      ticker: "NVDA",
      heading: "NVIDIA — 가장 직접적인 AI 연산 노출, 가장 엄격한 한도",
      paragraphs: [
        {
          text: "NVIDIA의 데이터센터 플랫폼은 가속 컴퓨팅과 네트워킹을 결합하고 AI 학습과 추론을 주요 사용처로 둔다. 따라서 AI 연산 수요를 표현하는 가장 직접적인 종목으로 후보군에 포함했다. 이 핵심 노출을 완전히 제외하면 사용자의 AI 투자 아이디어가 약해질 수 있다.",
          citationIds: ["qual-nvda"],
        },
        {
          text: "동시에 이 직접성은 수요 기대와 경쟁 변화가 주가에 빠르게 반영될 수 있다는 뜻이다. 실제 12개월 변동성은 45.9%로 보유종목 중 가장 높았다. 역변동성 계산의 한도 적용 전 비중은 14.3%였지만 사용자가 요구한 10% 한도를 적용했고, 남은 4.3%p는 다른 종목에 재배분했다. 10%는 정성적 확신의 점수가 아니라 사용자 제약과 수치규칙의 결과다.",
          citationIds: ["qual-nvda", "quant-ai"],
        },
      ],
    },
  ],
  portfolioConstruction: [
    {
      text: "정성 연구는 AI 가치사슬에 실제 사업연결이 있는 기업을 후보군으로 좁히는 데 사용했다. 그다음 전략 엔진은 후보의 최근 12개월 변동성을 측정해 변동성이 낮을수록 높은 비중을 주는 역변동성 방식을 적용했다. 따라서 기업을 보유해야 하는 이유와 정확히 몇 퍼센트를 보유하는지는 서로 다른 근거를 가진다.",
      citationIds: ["industry-capex", "quant-ai"],
    },
    {
      text: "한도 적용 전 비중은 MSFT 25.6%, AVGO 20.3%, TSM 18.7%, GOOGL 21.1%, NVDA 14.3%였다. Microsoft에는 공통 한도 25%, NVIDIA에는 사용자 지정 한도 10%를 적용했다. 줄어든 4.9%p는 한도 여유와 역변동성 비율에 따라 Broadcom, TSMC, Alphabet에 다시 배분해 최종 25%, 22%, 20%, 23%, 10%로 맞췄다.",
      citationIds: ["quant-ai"],
    },
    {
      text: "분기별 리밸런싱에서는 각 분기 첫 거래일에 후보 적격성과 변동성을 다시 계산하고 목표비중으로 조정한다. 분석 기준일의 구성은 현재 계산 결과일 뿐, 과거 백테스트 내내 동일한 종목과 비중을 유지했다는 뜻은 아니다. 전략은 매수 포지션만 사용하고 투자금을 전액 배분하며 레버리지, 공매도, 현금 비중을 사용하지 않는다.",
      citationIds: ["quant-ai"],
    },
  ],
  performanceInterpretation: [
    {
      text: "2019년 1월부터 2025년 2월까지 포트폴리오의 누적 수익률은 121%, 비교지수는 139%였다. 같은 출발값 100을 기준으로 최종값이 각각 221과 239이므로 포트폴리오는 18%p 뒤처졌다. NVIDIA 비중 제한과 역변동성 배분이 집중위험을 낮추는 방향으로 작동했지만, 분석기간의 비교지수 상승을 따라잡지는 못했다.",
      citationIds: ["quant-ai"],
    },
    {
      text: "연환산 성장률은 계산기간 전체의 복리 성장을 보여주지만, 경로는 매끄럽지 않았다. 2022년 이후 포트폴리오 지수는 192에서 141로 하락했고 최대 낙폭은 -31.2%였다. 이후 2025년 2월에는 221까지 회복했으나, 이 하락폭은 사용자가 제시한 손실 감내 수준 20%를 11.2%p 초과한다. 따라서 3년 이상 보유할 수 있다는 조건만으로 실제 하락구간을 견딜 수 있다고 단정하기 어렵다.",
      citationIds: ["quant-ai"],
    },
    {
      text: "연환산 변동성 21.42%와 Sharpe 비율 0.74는 수익이 상당한 가격변동을 동반했음을 보여준다. 거래비용은 재조정 거래마다 0.10%를 반영했지만 종목별 성과기여 자료는 제공되지 않았으므로 특정 기업이 상대부진의 원인이라고 해석하지 않았다. 관찰 가능한 결론은 이 전략이 비교지수보다 낮은 수익과 여전히 큰 낙폭을 기록했다는 점이다.",
      citationIds: ["quant-ai"],
    },
  ],
  reconsiderationConditions: [
    {
      text: "첫 번째 재검토 조건은 클라우드 사업자의 데이터센터 투자와 AI 관련 매출의 관계가 약해지는 경우다. Microsoft와 Alphabet의 투자지출이 계속 늘지만 클라우드와 응용 서비스의 수익화가 뒤따르지 않으면, 반도체 공급망으로 이어지는 수요의 지속기간을 낮춰 평가해야 한다.",
      citationIds: ["industry-capex", "qual-msft", "qual-googl"],
    },
    {
      text: "두 번째는 가속기와 네트워크 반도체의 경쟁구도가 달라지는 경우다. 고객의 맞춤형 칩 채택이 확대되면 Broadcom에는 기회가 될 수 있지만 NVIDIA의 역할은 줄어들 수 있다. 반대로 범용 GPU 중심의 생태계가 더 강해지면 NVIDIA 10% 한도가 수익참여를 제한할 수 있다. 어느 경우에도 자동매매 기준을 두지 않고 다음 분기 연구기록과 재조정 시점에 후보 적격성을 다시 판단한다.",
      citationIds: ["qual-avgo", "qual-nvda"],
    },
    {
      text: "세 번째는 첨단 공정 수요와 생산위험이다. TSMC의 첨단 설비 가동 전망이 약해지거나 생산지역 위험이 커지면 제조단계 분산의 효용을 재검토해야 한다. 동시에 실제 운용에서 -20%를 넘는 하락을 감내하기 어렵다고 판단되면, 종목 수와 투자대상을 넓힌 별도 전략을 새로 분석하는 편이 현재 전략의 한도를 임의로 완화하는 것보다 일관된 대응이다.",
      citationIds: ["qual-tsm", "industry-cycle", "quant-ai"],
    },
  ],
}

const aiExecution: ExecutionRecord[] = [
  {
    id: "ai-s1",
    stage: "투자조건 확인",
    status: "completed",
    startedAt: "2025-02-28 18:00",
    endedAt: "2025-02-28 18:00",
    summary:
      "투자기간, 투자성향, 손실 감내 수준과 NVIDIA 10% 한도를 확인했습니다.",
    sources: [],
    issues: [],
    tools: ["투자조건 검증기"],
    modelOutput:
      "투자기간 36개월, 위험중립형, 손실 감내 수준 20%, 종목당 최대 25%, NVDA 최대 10%를 적용 조건으로 확정했습니다.",
    decisionSummary:
      "사용자가 명시한 NVDA 한도를 기본 투자조건보다 우선해 이번 분석에 적용했습니다.",
  },
  {
    id: "ai-s2",
    stage: "자료 조회와 후보 구성",
    status: "completed",
    startedAt: "2025-02-28 18:00",
    endedAt: "2025-02-28 18:01",
    summary: "기업자료와 산업자료를 바탕으로 AI 가치사슬 후보를 구성했습니다.",
    sources: aiEvidence.map((item) => item.id),
    issues: [],
    tools: ["정성자료 검색", "종목 후보 검색"],
    modelOutput:
      "AI 수요와 직접 연결되는 클라우드, 가속기, 네트워크 반도체, 파운드리 기업 7개를 후보로 구성했습니다.",
    decisionSummary:
      "기업자료에서 확인되는 사업 연관성을 기준으로 후보군을 만들고 중복 노출이 큰 AMD와 범위가 넓은 META를 후순위로 분류했습니다.",
  },
  {
    id: "ai-s3",
    stage: "전략 구성과 조건 검증",
    status: "completed",
    startedAt: "2025-02-28 18:01",
    endedAt: "2025-02-28 18:01",
    summary:
      "역변동성 배분과 종목별 한도를 적용하고 비중 합계 100%를 확인했습니다.",
    sources: ["quant-ai"],
    issues: [],
    tools: ["전략 생성기", "비중 검증기", "제약조건 검증기"],
    modelOutput:
      "고정 종목, 저변동성 상위 N개, 모멘텀 상위 N개를 각각 동일가중·역변동성 방식과 결합해 4개 후보전략을 생성했습니다.",
    decisionSummary:
      "사용자의 집중도 제한을 지키면서 후보 간 성과와 위험을 비교할 수 있도록 선정 규칙과 배분 규칙을 달리했습니다.",
  },
  {
    id: "ai-s4",
    stage: "과거 성과 분석",
    status: "completed",
    startedAt: "2025-02-28 18:01",
    endedAt: "2025-02-28 18:02",
    summary: "동일 기간과 비용 조건으로 포트폴리오와 비교지수를 계산했습니다.",
    sources: ["quant-ai"],
    issues: [],
    tools: ["백테스트 엔진", "성과지표 계산기"],
    modelOutput:
      "4개 후보전략을 같은 기간, 거래비용, 비교지수 조건으로 실행하고 누적수익률, 변동성, 최대 낙폭, Sharpe 비율을 계산했습니다.",
    decisionSummary:
      "수익률 한 항목이 아니라 손실 감내 수준, 위험조정 성과, 사용자 제약 충족 여부를 함께 비교했습니다.",
  },
  {
    id: "ai-s5",
    stage: "근거 검토와 리포트 작성",
    status: "completed",
    startedAt: "2025-02-28 18:02",
    endedAt: "2025-02-28 18:03",
    summary: "서술, 배분, 계산값과 인용자료의 연결을 확인했습니다.",
    sources: aiEvidence.map((item) => item.id),
    issues: [],
    tools: ["근거 연결 검사", "수치 일관성 검사", "리포트 생성기"],
    modelOutput:
      "저변동성 상위 5종목·역변동성 배분·분기별 리밸런싱 전략을 최종안으로 선택하고 기업자료 인용과 계산값을 연결했습니다.",
    decisionSummary:
      "최고 누적수익 전략은 아니지만 최대 낙폭과 변동성이 더 낮고 NVDA 10% 제한을 안정적으로 유지해 최종안으로 선택했습니다.",
  },
]

const aiCandidates = [
  {
    id: "ai-c1",
    name: "저변동성·역변동성",
    selectionRule: "12개월 변동성이 낮은 상위 5종목",
    weightingRule: "역변동성 배분 후 비중 한도 적용",
    rebalance: "분기별",
    cumulativeReturn: 121,
    volatility: 21.42,
    mdd: -31.2,
    sharpe: 0.74,
    selected: true,
    evaluation:
      "누적수익은 모멘텀 전략보다 낮았지만 변동성과 최대 낙폭이 더 작고 NVDA 10% 제한을 일관되게 충족했습니다.",
  },
  {
    id: "ai-c2",
    name: "모멘텀·동일가중",
    selectionRule: "12개월 모멘텀이 높은 상위 5종목",
    weightingRule: "동일가중 후 비중 한도 적용",
    rebalance: "분기별",
    cumulativeReturn: 148.6,
    volatility: 29.8,
    mdd: -42.7,
    sharpe: 0.71,
    selected: false,
    evaluation:
      "누적수익은 가장 높았지만 최대 낙폭과 변동성이 사용자의 손실 감내 수준에서 크게 벗어났습니다.",
  },
  {
    id: "ai-c3",
    name: "고정 종목·동일가중",
    selectionRule: "정성자료로 선정한 5종목 고정",
    weightingRule: "동일가중 후 NVDA 한도 재배분",
    rebalance: "분기별",
    cumulativeReturn: 115.4,
    volatility: 24.7,
    mdd: -35.9,
    sharpe: 0.66,
    selected: false,
    evaluation:
      "규칙은 단순하지만 위험조정 성과가 최종안보다 낮았고 하락폭도 더 컸습니다.",
  },
  {
    id: "ai-c4",
    name: "저변동성·동일가중",
    selectionRule: "12개월 변동성이 낮은 상위 5종목",
    weightingRule: "동일가중 후 비중 한도 적용",
    rebalance: "반기별",
    cumulativeReturn: 108.9,
    volatility: 22.6,
    mdd: -33.8,
    sharpe: 0.63,
    selected: false,
    evaluation:
      "거래 빈도는 낮지만 최종안보다 수익과 위험조정 성과가 모두 낮았습니다.",
  },
]

export function makeDemoReport(
  id = "report-ai-20250228",
  title = "AI 인프라 분산 전략",
  idea = "AI 산업에 투자하고 싶지만 NVIDIA 비중은 10% 이하로 가져가고 싶어요.",
): Report {
  const metrics = calculateMetrics(aiSeries)
  return {
    id,
    title,
    idea,
    createdAt: "2025-02-28",
    isDemo: true,
    status: "complete",
    saved: true,
    conditions: structuredClone(aiConditions),
    strategy: structuredClone(aiStrategy),
    allocation: structuredClone(aiAllocation),
    evidence: structuredClone(aiEvidence),
    execution: structuredClone(aiExecution),
    calculation: {
      startDate: "2019-01-02",
      endDate: "2025-02-28",
      currency: "USD",
      initialCapitalUsd: aiCapitalUsd,
      benchmark: "S&P 500 비교 시계열",
      benchmarkMeaning: "미국 대형주 시장의 같은 기간 성과",
      transactionCostPct: 0.1,
      riskFreeRatePct: 3.8,
      riskFreeSource: "분석 기준일 미국 단기 국채 수익률 자료",
      fxRate: APP_CONFIG.fxRate,
      fxDate: APP_CONFIG.fxDate,
      compositionDate: "2025-02-28",
      marketAsOf: "2025-02-28",
    },
    series: structuredClone(aiSeries),
    metrics: { ...metrics, volatility: 21.42, sharpe: 0.74 },
    exclusions: [
      "AMD: 정성 연구에서 NVIDIA·Broadcom과 중복되는 연산 반도체 노출이 커 최종 후보에서 제외",
      "META: 플랫폼 사업은 관련성이 있으나 이번 전략의 클라우드·반도체 가치사슬 범위에서 제외",
    ],
    limitations: [
      "현재 구성종목을 기준으로 과거를 분석해 생존자 편향 가능성이 있습니다.",
      "기간 중 지수 구성종목 변경과 세금은 반영하지 않았습니다.",
      "종목별 성과기여 자료가 없어 과거 수익률의 기업별 원인을 구분하지 않았습니다.",
    ],
    summary:
      "AI 설비투자의 수혜가 클라우드, 가속기, 네트워크 반도체, 첨단 제조로 이어진다는 판단을 다섯 기업으로 표현한 전략입니다.",
    narrative: structuredClone(aiNarrative),
    candidateStrategies: structuredClone(aiCandidates),
  }
}

const stabilityConditions: EffectiveConditions = {
  ...DEMO_PROFILE,
  horizonMonths: 36,
  computedTendency: "안정추구형",
  finalTendency: "안정추구형",
  lossTolerancePct: 15,
  industries: ["헬스케어", "소비재", "금융"],
  preferences: ["배당", "대형주"],
  memo: "경기변동에 덜 민감한 대형주를 중심으로 완만한 성장을 추구합니다.",
  globalCapPct: 25,
  securityCaps: {},
  namedTickers: [],
  analysisOverrides: [],
}

const stabilityStrategy: StrategyRules = {
  universe: "미국 헬스케어·필수소비재·금융 대형주",
  selectionRule: "lowest-volatility",
  selectionCount: 5,
  lookbackMonths: 12,
  weightingRule: "inverse-volatility",
  exclusions: [],
  globalCapPct: 25,
  securityCaps: {},
  rebalance: "분기별",
  assumptions: [
    "매수 포지션만 운용",
    "투자금 전액 배분",
    "레버리지와 공매도 미사용",
    "현금 미보유",
    "분기 첫 거래일 종가로 재조정",
  ],
}

const stabilityCapitalUsd = 21_818.18
const stabilityAllocation: Allocation[] = [
  ["JNJ", "Johnson & Johnson", 25, 18.2, 27.4, "의약품과 의료기기"],
  ["PG", "Procter & Gamble", 25, 16.9, 29.1, "생활필수품"],
  ["JPM", "JPMorgan Chase", 20, 24.7, 19.9, "대형은행"],
  ["KO", "Coca-Cola", 15, 20.5, 12.4, "글로벌 음료"],
  ["PEP", "PepsiCo", 15, 21.3, 11.2, "음료와 간편식"],
].map(([ticker, company, weight, volatility, uncapped, role]) => ({
  ticker: String(ticker),
  company: String(company),
  weight: Number(weight),
  usd: Math.round(stabilityCapitalUsd * (Number(weight) / 100) * 100) / 100,
  krw: Math.round(30_000_000 * (Number(weight) / 100)),
  selectionReason: `${role} 사업의 반복수요와 현금창출 특성이 안정추구형 목표에 부합해 후보에 포함했습니다.`,
  weightingReason: `최근 12개월 연환산 변동성 ${Number(volatility).toFixed(1)}%를 이용한 역변동성 계산의 한도 적용 전 비중은 ${Number(uncapped).toFixed(1)}%였습니다. 공통 한도와 재배분을 거쳐 ${Number(weight).toFixed(1)}%로 확정했습니다.`,
  role: String(role),
  capPct: 25,
  capAdjusted: Number(weight) === 25,
  risk:
    ticker === "JPM"
      ? "신용비용과 금리환경 변화"
      : "원가 상승, 가격전가력 약화, 규제 변화",
  evidenceId: `stable-${String(ticker).toLowerCase()}`,
}))
stabilityAllocation[stabilityAllocation.length - 1].usd =
  Math.round(
    (stabilityCapitalUsd -
      stabilityAllocation
        .slice(0, -1)
        .reduce((sum, item) => sum + item.usd, 0)) *
      100,
  ) / 100

const stabilitySeries: Point[] = [
  { date: "2019-01-02", portfolio: 100, benchmark: 100, drawdown: 0 },
  { date: "2020-01-02", portfolio: 116, benchmark: 128, drawdown: -5.6 },
  { date: "2021-01-04", portfolio: 133, benchmark: 151, drawdown: -8.9 },
  { date: "2022-01-03", portfolio: 156, benchmark: 191, drawdown: -4.2 },
  { date: "2023-01-03", portfolio: 142, benchmark: 158, drawdown: -15.7 },
  { date: "2024-01-02", portfolio: 165, benchmark: 196, drawdown: -7.8 },
  { date: "2025-01-31", portfolio: 188, benchmark: 230, drawdown: -3.4 },
]

const stabilityEvidence: Evidence[] = [
  {
    id: "stable-jnj",
    title: "Johnson & Johnson의 사업구조",
    value: "혁신의약품과 의료기기 사업을 운영",
    provider: "Johnson & Johnson",
    sourceTitle: "Johnson & Johnson 2023 Annual Report",
    publicationDate: "2024-02-16",
    collectedAt: "2025-01-31 16:20",
    usedFor: "헬스케어 방어수요와 제품·소송위험 평가",
    isDemo: true,
    section: "Business Segments",
    excerpt:
      "회사는 혁신의약품과 MedTech를 핵심 사업으로 구분하며 의료수요를 기반으로 매출을 창출한다.",
    recordId: "QR-JNJ-2023-AR",
    supportedClaim:
      "경기와 무관하게 발생하는 의료수요가 포트폴리오의 수요 안정성을 보완한다.",
  },
  {
    id: "stable-pg",
    title: "Procter & Gamble의 생활필수품 포트폴리오",
    value: "세제, 생활용품, 개인관리 제품의 글로벌 브랜드를 운영",
    provider: "The Procter & Gamble Company",
    sourceTitle: "P&G 2024 Annual Report",
    publicationDate: "2024-08-06",
    collectedAt: "2025-01-31 16:22",
    usedFor: "반복구매 수요와 가격전가력 평가",
    isDemo: true,
    section: "Business; Segment Results",
    excerpt:
      "일상적으로 소비되는 제품군과 다수의 글로벌 브랜드가 사업의 핵심을 이룬다.",
    recordId: "QR-PG-2024-AR",
    supportedClaim:
      "생활필수품의 반복구매 수요가 경기둔화 시 매출 변동을 완화할 수 있다.",
  },
  {
    id: "stable-jpm",
    title: "JPMorgan Chase의 다각화된 금융사업",
    value: "소비자금융, 기업금융, 자산관리 사업을 함께 운영",
    provider: "JPMorgan Chase & Co.",
    sourceTitle: "JPMorgan Chase 2023 Annual Report",
    publicationDate: "2024-04-08",
    collectedAt: "2025-01-31 16:24",
    usedFor: "금융업 노출과 신용·금리 위험 평가",
    isDemo: true,
    section: "Business Segments; Risk Management",
    excerpt:
      "소비자, 기업, 투자은행, 자산관리 사업이 서로 다른 수익원을 제공하지만 신용과 시장위험 관리는 핵심 과제로 남는다.",
    recordId: "QR-JPM-2023-AR",
    supportedClaim:
      "JPMorgan은 소비재·헬스케어와 다른 금리·신용 요인에 노출되어 수익원 구성을 넓힌다.",
  },
  {
    id: "stable-ko",
    title: "Coca-Cola의 브랜드·유통 모델",
    value: "농축액 판매와 보틀링 파트너 체계를 활용",
    provider: "The Coca-Cola Company",
    sourceTitle: "Coca-Cola 2023 Annual Report",
    publicationDate: "2024-02-20",
    collectedAt: "2025-01-31 16:26",
    usedFor: "글로벌 음료수요와 유통구조 평가",
    isDemo: true,
    section: "Business — Products and Distribution",
    excerpt:
      "글로벌 브랜드와 보틀링 파트너 네트워크가 제품 생산·유통을 분담하는 구조다.",
    recordId: "QR-KO-2023-AR",
    supportedClaim:
      "브랜드와 파트너 유통망은 반복적인 음료수요에 접근하는 기반이다.",
  },
  {
    id: "stable-pep",
    title: "PepsiCo의 음료·간편식 사업",
    value: "음료와 간편식 제품군을 함께 운영",
    provider: "PepsiCo, Inc.",
    sourceTitle: "PepsiCo 2023 Annual Report",
    publicationDate: "2024-02-09",
    collectedAt: "2025-01-31 16:28",
    usedFor: "제품군 분산과 원가위험 평가",
    isDemo: true,
    section: "Business — Divisions and Product Categories",
    excerpt:
      "음료와 간편식 부문이 지역별 사업을 구성해 단일 제품군 의존을 낮춘다.",
    recordId: "QR-PEP-2023-AR",
    supportedClaim:
      "PepsiCo는 Coca-Cola와 음료 노출이 겹치지만 간편식 사업을 추가로 제공한다.",
  },
  {
    id: "quant-stability",
    title: "가격·변동성 계산 기록",
    value: "2019-01-02~2025-01-31 조정 종가, 일별 수익률, 12개월 연환산 변동성",
    provider: "MyFinSight 가격 데이터베이스",
    sourceTitle: "미국 상장주식 조정 종가",
    marketDate: "2025-01-31",
    collectedAt: "2025-01-31 17:10",
    usedFor: "역변동성 배분, 과거 성과, 최대 낙폭 계산",
    isDemo: true,
    section: "가격 및 기업행동 반영 시계열",
    excerpt:
      "JNJ 18.2%, PG 16.9%, JPM 24.7%, KO 20.5%, PEP 21.3%의 12개월 연환산 변동성을 배분 계산에 사용했다.",
    recordId: "PX-STABLE-20250131",
    supportedClaim:
      "정확한 배분은 사업평가가 아니라 역변동성 계산과 25% 공통 한도에서 결정되었다.",
  },
]

const stabilityCompanyCopy: Record<string, [string, string]> = {
  JNJ: [
    "Johnson & Johnson은 혁신의약품과 의료기기를 통해 경기와 무관하게 발생하는 의료수요에 접근한다. 두 사업은 생활필수품 기업과 다른 수요기반을 제공해 포트폴리오의 방어축을 넓힌다.",
    "의약품 특허와 제품책임 관련 위험은 안정적인 수요와 별개의 문제다. 18.2%의 변동성으로 계산한 비중은 27.4%였지만 공통 한도 25%를 적용했다.",
  ],
  PG: [
    "P&G는 세제와 개인관리 등 반복구매 빈도가 높은 생활필수품 브랜드를 운영한다. 소비자가 경기둔화에도 구매를 완전히 중단하기 어려운 제품군이라는 점이 안정추구형 목표와 맞는다.",
    "원재료와 물류비 상승을 가격에 충분히 반영하지 못하면 수익성이 약해질 수 있다. 변동성 기준 계산값 29.1%에 25% 한도를 적용했다.",
  ],
  JPM: [
    "JPMorgan은 소비자금융, 기업금융, 투자은행, 자산관리를 함께 운영한다. 헬스케어와 소비재와 달리 금리와 신용환경에 노출되어 포트폴리오의 수익원 구성을 넓힌다.",
    "다만 경기둔화가 신용비용 상승으로 이어지면 손실 변동이 커질 수 있다. 24.7%의 측정 변동성으로 계산된 19.9%를 반올림해 최종 20%를 배분했다.",
  ],
  KO: [
    "Coca-Cola는 브랜드와 보틀링 파트너 네트워크를 통해 글로벌 음료수요에 접근한다. 직접 생산설비 부담 일부를 파트너와 나누는 유통구조가 특징이다.",
    "소비자 기호 변화와 원가·환율은 주요 변수다. 20.5% 변동성에 따른 계산값은 12.4%였고, 상한 적용 후 남은 비중을 재배분해 15%가 됐다.",
  ],
  PEP: [
    "PepsiCo는 음료와 간편식을 함께 운영해 Coca-Cola와 겹치는 음료 노출에 식품 수요를 더한다. 이 조합은 필수소비재 내 제품군을 넓힌다.",
    "농산물과 포장재 원가, 건강 규제 변화가 수익성에 영향을 줄 수 있다. 21.3% 변동성의 계산값 11.2%에 조정분을 배분해 최종 15%가 됐다.",
  ],
}

const stabilityNarrative: ReportNarrative = {
  overallJudgment: [
    {
      text: "이 전략은 3년의 투자기간과 안정추구형 투자성향에 맞춰 경기와 무관하게 반복되는 의료·생활필수품 수요를 중심에 두고, 금융업을 보완적으로 편입했다. 목표는 시장 상승을 최대한 따라가는 것이 아니라 매출 기반이 서로 다른 대형주를 통해 가격변동과 사업집중을 낮추는 것이다.",
      citationIds: ["stable-jnj", "stable-pg", "stable-jpm"],
    },
    {
      text: "Johnson & Johnson은 의료수요, P&G·Coca-Cola·PepsiCo는 일상 소비, JPMorgan은 신용과 금리환경에 각각 노출된다. 소비재 세 기업은 방어적 수요라는 공통점이 있어 완전한 경제적 분산은 아니지만, 헬스케어와 금융을 함께 두어 단일 산업의 이익구조에만 의존하지 않도록 구성했다.",
      citationIds: [
        "stable-jnj",
        "stable-pg",
        "stable-jpm",
        "stable-ko",
        "stable-pep",
      ],
    },
    {
      text: "정확한 비중은 사업의 우수성을 점수화한 결과가 아니다. 정성자료로 후보를 정한 뒤 12개월 변동성의 역수를 사용했고, JNJ와 PG는 계산비중이 25%를 넘어 공통 한도를 적용했다. 한도 적용으로 남은 비중은 JPMorgan, Coca-Cola, PepsiCo에 재배분했다.",
      citationIds: ["quant-stability"],
    },
    {
      text: "과거 누적 수익률은 88%로 비교지수 130%보다 42%p 낮았다. 대신 최대 낙폭은 -15.7%, 연환산 변동성은 14.8%로 AI 전략보다 낮았다. 최대 낙폭이 사용자의 손실 감내 수준 15%를 0.7%p 초과했다는 점은 이 전략도 원금변동을 피할 수 없음을 보여준다. 시장수익 추종보다 변동 완화를 우선한다는 목적에는 부합하지만, 장기 상승장에서 상대수익을 포기하는 대가가 분명하다.",
      citationIds: ["quant-stability"],
    },
  ],
  industryAnalysis: [
    {
      text: "헬스케어와 생활필수품의 공통점은 소비를 장기간 미루기 어렵다는 것이다. Johnson & Johnson의 의료제품과 P&G의 생활용품은 구매동기가 서로 다르지만 경제활동 감소가 곧바로 수요 소멸로 이어지지 않는다는 점에서 경기민감 업종보다 안정적인 매출기반을 기대할 수 있다.",
      citationIds: ["stable-jnj", "stable-pg"],
    },
    {
      text: "Coca-Cola와 PepsiCo는 글로벌 브랜드와 유통망을 통해 반복수요에 접근한다. 다만 두 회사는 음료시장과 원재료·포장비용에 함께 노출되므로 회사 수가 늘었다고 경제요인이 완전히 분리되는 것은 아니다. PepsiCo의 간편식 사업은 제품군을 넓히지만 소비재 원가와 가격전가력은 두 회사 모두의 핵심 변수다.",
      citationIds: ["stable-ko", "stable-pep"],
    },
    {
      text: "JPMorgan은 수요방어형 기업들과 다른 금리·신용요인을 추가한다. 금융업은 경기둔화 때 신용비용이 상승할 수 있어 절대적으로 방어적이지 않지만, 소비재 원가나 의료제품 주기와 다른 수익구조를 제공한다. 이 차이가 포트폴리오의 사업요인 분산에 기여한다.",
      citationIds: ["stable-jpm"],
    },
  ],
  companyAnalyses: stabilityAllocation.map((item) => ({
    ticker: item.ticker,
    heading: `${item.company} — ${item.role}`,
    paragraphs: [
      {
        text: stabilityCompanyCopy[item.ticker][0],
        citationIds: [item.evidenceId],
      },
      {
        text: stabilityCompanyCopy[item.ticker][1],
        citationIds: [item.evidenceId, "quant-stability"],
      },
    ],
  })),
  portfolioConstruction: [
    {
      text: "기업자료는 반복수요와 사업구조를 확인하고 투자 후보를 구성하는 데 사용했다. 이후 전략 엔진이 최근 12개월 변동성을 계산해 변동성이 낮은 종목에 더 높은 비중을 부여했다. 이 과정에서 사업의 질을 정확한 퍼센트로 바꾸지 않았고, 정성 선택과 수치 배분을 분리했다.",
      citationIds: ["stable-jnj", "stable-pg", "stable-jpm", "quant-stability"],
    },
    {
      text: "한도 적용 전 비중은 JNJ 27.4%, PG 29.1%, JPM 19.9%, KO 12.4%, PEP 11.2%였다. JNJ와 PG에 25% 상한을 적용한 뒤 남은 비중을 다른 세 종목에 배분해 최종 비중을 25%, 25%, 20%, 15%, 15%로 정했다.",
      citationIds: ["quant-stability"],
    },
    {
      text: "분기별 리밸런싱은 분기 첫 거래일마다 후보의 적격성과 변동성을 다시 측정해 목표비중으로 조정한다. 분석 기준일의 구성과 과거 각 재조정 시점의 보유내역은 다를 수 있다. 전략은 투자금을 전액 배분하고 레버리지, 공매도, 현금 비중을 사용하지 않는다.",
      citationIds: ["quant-stability"],
    },
  ],
  performanceInterpretation: [
    {
      text: "2019년 1월부터 2025년 1월까지 포트폴리오는 88% 상승했고 비교지수는 130% 상승했다. 42%p의 격차는 방어적 대형주와 비중 상한을 선택한 기회비용이다. 시장 상승을 최대한 따라가는 전략이라면 만족스럽지 않은 결과지만, 변동 완화를 우선한 목적과 함께 평가해야 한다.",
      citationIds: ["quant-stability"],
    },
    {
      text: "포트폴리오의 최대 낙폭은 -15.7%로 비교적 제한됐지만 사용자의 손실 감내 수준 15%를 소폭 넘었다. 2022년의 지수 156에서 2023년 142로 내려간 구간은 방어적 업종도 금리와 비용환경 변화에서 자유롭지 않음을 보여준다. 이후 2025년 1월 188까지 회복했지만 회복기간 동안 비교지수와의 격차는 남았다.",
      citationIds: ["quant-stability"],
    },
    {
      text: "연환산 변동성 14.8%와 Sharpe 비율 0.69는 가격흔들림이 AI 전략보다 작았지만 위험조정 성과가 압도적이지 않았음을 뜻한다. 종목별 성과기여 자료가 없으므로 상대부진을 특정 기업의 탓으로 돌릴 수 없다. 확인 가능한 결론은 더 낮은 변동과 더 낮은 시장참여가 함께 나타났다는 점이다.",
      citationIds: ["quant-stability"],
    },
  ],
  reconsiderationConditions: [
    {
      text: "생활필수품 기업의 가격인상이 판매량 감소로 이어지거나 원가상승을 상쇄하지 못하면 반복수요의 방어력이 약해질 수 있다. P&G, Coca-Cola, PepsiCo의 다음 사업자료에서 판매량과 가격효과가 함께 악화되는지 확인해야 한다.",
      citationIds: ["stable-pg", "stable-ko", "stable-pep"],
    },
    {
      text: "Johnson & Johnson의 제품책임과 의약품 파이프라인 위험이 커지면 의료수요의 안정성만으로 편입을 정당화하기 어렵다. JPMorgan은 신용비용이 빠르게 상승할 경우 소비재와 다른 수익원을 제공한다는 장점보다 경기민감성이 더 크게 나타날 수 있다.",
      citationIds: ["stable-jnj", "stable-jpm"],
    },
    {
      text: "사용자가 15% 안팎의 과거 낙폭도 감내하기 어렵거나 비교지수와의 장기 수익격차를 받아들이기 어렵다면 투자목표 자체를 다시 확인해야 한다. 이 경우 기존 리포트를 소급 변경하지 않고, 더 넓은 투자대상이나 다른 배분규칙을 적용한 새 분석으로 비교하는 것이 적절하다.",
      citationIds: ["quant-stability"],
    },
  ],
}

const stabilityExecution: ExecutionRecord[] = [
  {
    id: "stable-s1",
    stage: "투자조건 확인",
    status: "completed",
    startedAt: "2025-01-31 17:00",
    endedAt: "2025-01-31 17:00",
    summary: "안정추구형 성향, 15% 손실 감내 수준과 관심 산업을 확인했습니다.",
    sources: [],
    issues: [],
    tools: ["투자조건 검증기"],
    modelOutput:
      "투자기간 36개월, 안정추구형, 손실 감내 수준 15%, 헬스케어·소비재·금융 중심 조건을 확정했습니다.",
    decisionSummary:
      "시장수익 극대화보다 변동 완화를 우선하는 분석목표로 해석했습니다.",
  },
  {
    id: "stable-s2",
    stage: "자료 조회와 후보 구성",
    status: "completed",
    startedAt: "2025-01-31 17:00",
    endedAt: "2025-01-31 17:03",
    summary: "헬스케어, 필수소비재, 금융 대형주의 사업자료를 검토했습니다.",
    sources: stabilityEvidence.map((item) => item.id),
    issues: [],
    tools: ["정성자료 검색", "종목 후보 검색"],
    modelOutput:
      "반복수요와 사업구조가 확인되는 헬스케어, 필수소비재, 금융 대형주를 후보군으로 구성했습니다.",
    decisionSummary:
      "경기민감 기술주보다 의료·생활수요를 우선하고 금융업을 다른 수익요인으로 포함했습니다.",
  },
  {
    id: "stable-s3",
    stage: "전략 구성과 조건 검증",
    status: "completed",
    startedAt: "2025-01-31 17:03",
    endedAt: "2025-01-31 17:04",
    summary: "역변동성 비중과 25% 상한을 적용했습니다.",
    sources: ["quant-stability"],
    issues: [],
    tools: ["전략 생성기", "비중 검증기", "제약조건 검증기"],
    modelOutput:
      "저변동성·역변동성, 저변동성·동일가중, 고정 종목·동일가중, 배당성장·역변동성의 4개 후보전략을 생성했습니다.",
    decisionSummary:
      "선정 규칙과 배분 방식을 달리해 변동 완화와 수익 포기의 정도를 비교하도록 구성했습니다.",
  },
  {
    id: "stable-s4",
    stage: "과거 성과 분석",
    status: "completed",
    startedAt: "2025-01-31 17:04",
    endedAt: "2025-01-31 17:06",
    summary: "같은 기간의 포트폴리오와 비교지수 성과를 계산했습니다.",
    sources: ["quant-stability"],
    issues: [],
    tools: ["백테스트 엔진", "성과지표 계산기"],
    modelOutput:
      "4개 후보를 같은 분석기간과 거래비용으로 실행해 수익률, 변동성, 최대 낙폭, Sharpe 비율을 비교했습니다.",
    decisionSummary:
      "누적수익보다 손실 감내 수준과 변동성, 위험조정 성과를 우선해 평가했습니다.",
  },
  {
    id: "stable-s5",
    stage: "근거 검토와 리포트 작성",
    status: "completed",
    startedAt: "2025-01-31 17:06",
    endedAt: "2025-01-31 17:08",
    summary: "기업별 판단, 배분비중, 계산값과 자료 연결을 확인했습니다.",
    sources: stabilityEvidence.map((item) => item.id),
    issues: [],
    tools: ["근거 연결 검사", "수치 일관성 검사", "리포트 생성기"],
    modelOutput:
      "저변동성 상위 5종목·역변동성 배분·분기별 리밸런싱 전략을 최종안으로 확정했습니다.",
    decisionSummary:
      "후보 중 변동성과 최대 낙폭이 가장 낮고 사용자 관심 산업을 모두 포함해 최종안으로 선택했습니다.",
  },
]

const stabilityCandidates = [
  {
    id: "stable-c1",
    name: "저변동성·역변동성",
    selectionRule: "12개월 변동성이 낮은 상위 5종목",
    weightingRule: "역변동성 배분 후 25% 상한 적용",
    rebalance: "분기별",
    cumulativeReturn: 88,
    volatility: 14.8,
    mdd: -15.7,
    sharpe: 0.69,
    selected: true,
    evaluation:
      "후보 중 변동성과 최대 낙폭이 가장 낮아 안정추구형 목표에 가장 가까웠습니다.",
  },
  {
    id: "stable-c2",
    name: "저변동성·동일가중",
    selectionRule: "12개월 변동성이 낮은 상위 5종목",
    weightingRule: "동일가중",
    rebalance: "분기별",
    cumulativeReturn: 91.6,
    volatility: 16.2,
    mdd: -18.9,
    sharpe: 0.66,
    selected: false,
    evaluation:
      "수익률은 소폭 높았지만 최대 낙폭이 손실 감내 수준을 더 크게 넘어섰습니다.",
  },
  {
    id: "stable-c3",
    name: "고정 종목·동일가중",
    selectionRule: "정성자료로 선정한 5종목 고정",
    weightingRule: "동일가중",
    rebalance: "반기별",
    cumulativeReturn: 84.2,
    volatility: 15.7,
    mdd: -17.4,
    sharpe: 0.61,
    selected: false,
    evaluation: "운용 규칙은 단순하지만 최종안보다 위험조정 성과가 낮았습니다.",
  },
  {
    id: "stable-c4",
    name: "배당성장·역변동성",
    selectionRule: "배당 지속성과 변동성 기준 상위 5종목",
    weightingRule: "역변동성 배분",
    rebalance: "분기별",
    cumulativeReturn: 93.1,
    volatility: 17.1,
    mdd: -19.6,
    sharpe: 0.65,
    selected: false,
    evaluation:
      "누적수익은 높았지만 금융·소비재 비중이 커져 산업 균형과 하락 방어가 약해졌습니다.",
  },
]

const stabilityMetrics = calculateMetrics(stabilitySeries)
const stabilityReport: Report = {
  id: "report-quality-20250131",
  title: "미국 대형주 안정성 전략",
  idea: "헬스케어, 생활필수품, 금융 대형주를 중심으로 변동성을 낮춘 3년 전략을 보고 싶어요.",
  createdAt: "2025-01-31",
  isDemo: true,
  status: "complete",
  saved: true,
  conditions: stabilityConditions,
  strategy: stabilityStrategy,
  allocation: stabilityAllocation,
  evidence: stabilityEvidence,
  execution: stabilityExecution,
  calculation: {
    startDate: "2019-01-02",
    endDate: "2025-01-31",
    currency: "USD",
    initialCapitalUsd: stabilityCapitalUsd,
    benchmark: "S&P 500 비교 시계열",
    benchmarkMeaning: "미국 대형주 시장의 같은 기간 성과",
    transactionCostPct: 0.1,
    riskFreeRatePct: 4.2,
    riskFreeSource: "분석 기준일 미국 단기 국채 수익률 자료",
    fxRate: 1375,
    fxDate: "2025-01-31",
    compositionDate: "2025-01-31",
    marketAsOf: "2025-01-31",
  },
  series: stabilitySeries,
  metrics: { ...stabilityMetrics, volatility: 14.8, sharpe: 0.69 },
  exclusions: [
    "기술주: 안정추구형 관심 산업과 반복수요 중심 후보 기준에서 제외",
    "고변동 금융주: 12개월 변동성 순위에서 최종 후보 밖으로 제외",
  ],
  limitations: [
    "현재 구성종목을 기준으로 과거를 분석해 생존자 편향 가능성이 있습니다.",
    "기간 중 지수 구성종목 변경과 세금은 반영하지 않았습니다.",
    "종목별 성과기여 자료가 없어 상대수익 차이의 기업별 원인을 구분하지 않았습니다.",
  ],
  summary:
    "의료와 생활필수품의 반복수요를 중심에 두고 금융업을 보완적으로 편입한 저변동성 대형주 전략입니다.",
  narrative: stabilityNarrative,
  candidateStrategies: stabilityCandidates,
}

const paperSeries: Point[] = [
  {
    date: "2025-02-03",
    portfolio: 30_000_000,
    benchmark: 30_000_000,
    drawdown: 0,
  },
  {
    date: "2025-02-10",
    portfolio: 30_180_000,
    benchmark: 30_240_000,
    drawdown: -0.2,
  },
  {
    date: "2025-02-18",
    portfolio: 30_060_000,
    benchmark: 30_120_000,
    drawdown: -0.6,
  },
  {
    date: "2025-02-24",
    portfolio: 30_360_000,
    benchmark: 30_420_000,
    drawdown: -0.1,
  },
  {
    date: "2025-02-28",
    portfolio: 30_510_000,
    benchmark: 30_600_000,
    drawdown: 0,
  },
]

export const DEMO_PAPER: PaperPortfolio = {
  id: "paper-quality-demo",
  reportId: stabilityReport.id,
  title: stabilityReport.title,
  isDemo: true,
  startedAt: "2025-02-03",
  latestAsOf: "2025-02-28 18:00",
  initialCapitalKrw: 30_000_000,
  currentValueKrw: 30_510_000,
  benchmarkReturn: 2,
  updateStatus: "업데이트 지연",
  series: paperSeries,
  holdings: stabilityReport.allocation.map((item, index) => ({
    ticker: item.ticker,
    company: item.company,
    initialWeight: item.weight,
    currentWeight: item.weight + [0.3, -0.2, 0.2, -0.1, -0.2][index],
    targetWeight: item.weight,
    lastRebalanceWeight: item.weight,
    currentValueKrw: Math.round(
      30_510_000 * ((item.weight + [0.3, -0.2, 0.2, -0.1, -0.2][index]) / 100),
    ),
  })),
  rebalanceRecords: [
    {
      date: "2025-02-03",
      summary:
        "추적 시작일의 목표비중을 적용했습니다. 실제 주문은 발생하지 않았습니다.",
    },
  ],
}

export const INITIAL_FIXTURES = {
  reports: [makeDemoReport(), stabilityReport],
  paperPortfolios: [DEMO_PAPER],
}
