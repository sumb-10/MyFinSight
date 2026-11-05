// 목업 종목 목록 (검색·포트폴리오용). 회사 이름은 실제 상장사지만 주가·시가총액·변동성은 화면 확인용 예시 값이다 — 실제 시세가 아니다.
// 백엔드 종목 자료(약 719개)를 옮긴 것이 아니라, 목업 시나리오와 검색 확인에 필요한 만큼만 직접 정했다.

export interface MockStock {
  ticker: string; name_ko: string; name_en: string; market: "US" | "KR"; sector_ko: string; sub_industry: string
  price_usd: number      // 분석 기준일(2026-10-30) 예시 주가 (한국 종목도 USD 로 환산한 예시)
  mcap_bn_usd: number    // 예시 시가총액 (십억 USD)
  vol: number            // 예시 연변동성
  drift: number          // 예시 연 기대수익 (시계열 생성용)
  summary_ko: string
}

export const STOCKS: MockStock[] = [
  { ticker: "NVDA", name_ko: "엔비디아", name_en: "NVIDIA Corporation", market: "US", sector_ko: "정보기술", sub_industry: "반도체", price_usd: 182.4, mcap_bn_usd: 4450, vol: 0.46, drift: 0.32, summary_ko: "AI 연산용 GPU와 데이터센터 반도체를 설계합니다." },
  { ticker: "MU", name_ko: "마이크론 테크놀로지", name_en: "Micron Technology", market: "US", sector_ko: "정보기술", sub_industry: "반도체", price_usd: 214.6, mcap_bn_usd: 240, vol: 0.44, drift: 0.28, summary_ko: "D램·낸드 플래시 등 메모리 반도체를 만듭니다." },
  { ticker: "AMAT", name_ko: "어플라이드 머티어리얼즈", name_en: "Applied Materials", market: "US", sector_ko: "정보기술", sub_industry: "반도체 장비", price_usd: 228.1, mcap_bn_usd: 182, vol: 0.36, drift: 0.2, summary_ko: "웨이퍼 증착·식각 등 반도체 제조 장비를 공급합니다." },
  { ticker: "LRCX", name_ko: "램리서치", name_en: "Lam Research", market: "US", sector_ko: "정보기술", sub_industry: "반도체 장비", price_usd: 146.3, mcap_bn_usd: 187, vol: 0.38, drift: 0.22, summary_ko: "메모리 공정에 많이 쓰이는 식각·증착 장비를 만듭니다." },
  { ticker: "KLAC", name_ko: "KLA", name_en: "KLA Corporation", market: "US", sector_ko: "정보기술", sub_industry: "반도체 장비", price_usd: 1012.5, mcap_bn_usd: 134, vol: 0.32, drift: 0.19, summary_ko: "반도체 공정 검사·계측 장비를 공급합니다." },
  { ticker: "ASML", name_ko: "ASML 홀딩", name_en: "ASML Holding N.V.", market: "US", sector_ko: "정보기술", sub_industry: "반도체 장비", price_usd: 948.2, mcap_bn_usd: 372, vol: 0.34, drift: 0.16, summary_ko: "극자외선(EUV) 노광 장비를 사실상 단독으로 공급합니다." },
  { ticker: "AVGO", name_ko: "브로드컴", name_en: "Broadcom Inc.", market: "US", sector_ko: "정보기술", sub_industry: "반도체", price_usd: 341.7, mcap_bn_usd: 1610, vol: 0.38, drift: 0.26, summary_ko: "네트워크·맞춤형 AI 반도체와 기업용 소프트웨어를 만듭니다." },
  { ticker: "AMD", name_ko: "AMD", name_en: "Advanced Micro Devices", market: "US", sector_ko: "정보기술", sub_industry: "반도체", price_usd: 238.9, mcap_bn_usd: 387, vol: 0.5, drift: 0.2, summary_ko: "CPU·GPU 등 컴퓨팅 반도체를 설계합니다." },
  { ticker: "TSM", name_ko: "TSMC", name_en: "Taiwan Semiconductor Manufacturing", market: "US", sector_ko: "정보기술", sub_industry: "반도체 위탁생산", price_usd: 296.4, mcap_bn_usd: 1540, vol: 0.34, drift: 0.22, summary_ko: "세계 최대 반도체 위탁생산(파운드리) 기업입니다." },
  { ticker: "MSFT", name_ko: "마이크로소프트", name_en: "Microsoft Corporation", market: "US", sector_ko: "정보기술", sub_industry: "소프트웨어", price_usd: 518.3, mcap_bn_usd: 3850, vol: 0.24, drift: 0.15, summary_ko: "클라우드(Azure)와 업무용 소프트웨어를 제공합니다." },
  { ticker: "GOOGL", name_ko: "알파벳 A", name_en: "Alphabet Inc. Class A", market: "US", sector_ko: "커뮤니케이션 서비스", sub_industry: "인터넷 서비스", price_usd: 268.1, mcap_bn_usd: 3240, vol: 0.28, drift: 0.16, summary_ko: "구글 검색·유튜브·클라우드를 운영합니다." },
  { ticker: "META", name_ko: "메타 플랫폼스", name_en: "Meta Platforms", market: "US", sector_ko: "커뮤니케이션 서비스", sub_industry: "인터넷 서비스", price_usd: 742.5, mcap_bn_usd: 1870, vol: 0.34, drift: 0.18, summary_ko: "페이스북·인스타그램 등 소셜 서비스를 운영합니다." },
  { ticker: "AAPL", name_ko: "애플", name_en: "Apple Inc.", market: "US", sector_ko: "정보기술", sub_industry: "하드웨어", price_usd: 262.8, mcap_bn_usd: 3900, vol: 0.24, drift: 0.12, summary_ko: "아이폰·맥 등 기기와 서비스를 판매합니다." },
  { ticker: "AMZN", name_ko: "아마존", name_en: "Amazon.com", market: "US", sector_ko: "경기소비재", sub_industry: "온라인 유통", price_usd: 228.4, mcap_bn_usd: 2440, vol: 0.3, drift: 0.14, summary_ko: "온라인 유통과 클라우드(AWS)를 운영합니다." },
  { ticker: "TSLA", name_ko: "테슬라", name_en: "Tesla Inc.", market: "US", sector_ko: "경기소비재", sub_industry: "자동차", price_usd: 441.2, mcap_bn_usd: 1460, vol: 0.6, drift: 0.12, summary_ko: "전기차와 에너지 저장 장치를 만듭니다." },
  { ticker: "JPM", name_ko: "JP모건 체이스", name_en: "JPMorgan Chase & Co.", market: "US", sector_ko: "금융", sub_industry: "은행", price_usd: 304.9, mcap_bn_usd: 840, vol: 0.22, drift: 0.11, summary_ko: "미국 최대 은행 지주회사입니다." },
  { ticker: "JNJ", name_ko: "존슨앤드존슨", name_en: "Johnson & Johnson", market: "US", sector_ko: "헬스케어", sub_industry: "제약", price_usd: 189.6, mcap_bn_usd: 456, vol: 0.17, drift: 0.07, summary_ko: "의약품과 의료기기를 만듭니다." },
  { ticker: "LLY", name_ko: "일라이 릴리", name_en: "Eli Lilly and Company", market: "US", sector_ko: "헬스케어", sub_industry: "제약", price_usd: 812.4, mcap_bn_usd: 770, vol: 0.3, drift: 0.18, summary_ko: "당뇨·비만 치료제 등 의약품을 개발합니다." },
  { ticker: "XOM", name_ko: "엑슨모빌", name_en: "Exxon Mobil Corporation", market: "US", sector_ko: "에너지", sub_industry: "석유·가스", price_usd: 116.8, mcap_bn_usd: 497, vol: 0.24, drift: 0.06, summary_ko: "석유·천연가스를 생산·정제합니다." },
  { ticker: "KO", name_ko: "코카콜라", name_en: "The Coca-Cola Company", market: "US", sector_ko: "필수소비재", sub_industry: "음료", price_usd: 69.4, mcap_bn_usd: 299, vol: 0.15, drift: 0.06, summary_ko: "탄산음료 등 음료를 판매합니다." },
  { ticker: "005930", name_ko: "삼성전자", name_en: "Samsung Electronics", market: "KR", sector_ko: "정보기술", sub_industry: "반도체·전자", price_usd: 72.6, mcap_bn_usd: 430, vol: 0.32, drift: 0.14, summary_ko: "메모리 반도체·스마트폰·가전을 만듭니다." },
  { ticker: "000660", name_ko: "SK하이닉스", name_en: "SK hynix", market: "KR", sector_ko: "정보기술", sub_industry: "반도체", price_usd: 268.3, mcap_bn_usd: 195, vol: 0.42, drift: 0.26, summary_ko: "D램과 고대역폭 메모리(HBM)를 만듭니다." },
  { ticker: "035420", name_ko: "NAVER", name_en: "NAVER Corporation", market: "KR", sector_ko: "커뮤니케이션 서비스", sub_industry: "인터넷 서비스", price_usd: 178.2, mcap_bn_usd: 28, vol: 0.34, drift: 0.08, summary_ko: "국내 최대 검색 포털과 커머스를 운영합니다." },
  { ticker: "035720", name_ko: "카카오", name_en: "Kakao Corp.", market: "KR", sector_ko: "커뮤니케이션 서비스", sub_industry: "인터넷 서비스", price_usd: 42.7, mcap_bn_usd: 19, vol: 0.38, drift: 0.05, summary_ko: "메신저 카카오톡과 플랫폼 서비스를 운영합니다." },
  { ticker: "005380", name_ko: "현대차", name_en: "Hyundai Motor Company", market: "KR", sector_ko: "경기소비재", sub_industry: "자동차", price_usd: 168.5, mcap_bn_usd: 36, vol: 0.3, drift: 0.09, summary_ko: "승용차·상용차를 만듭니다." },
  { ticker: "373220", name_ko: "LG에너지솔루션", name_en: "LG Energy Solution", market: "KR", sector_ko: "산업재", sub_industry: "2차전지", price_usd: 298.1, mcap_bn_usd: 70, vol: 0.4, drift: 0.04, summary_ko: "전기차용 배터리를 만듭니다." },
  { ticker: "SPY", name_ko: "SPDR S&P 500 ETF", name_en: "SPDR S&P 500 ETF Trust", market: "US", sector_ko: "ETF", sub_industry: "지수 추종", price_usd: 682.3, mcap_bn_usd: 690, vol: 0.16, drift: 0.1, summary_ko: "미국 S&P 500 지수를 따라가는 ETF입니다." },
  { ticker: "QQQ", name_ko: "인베스코 QQQ", name_en: "Invesco QQQ Trust", market: "US", sector_ko: "ETF", sub_industry: "지수 추종", price_usd: 612.4, mcap_bn_usd: 380, vol: 0.2, drift: 0.13, summary_ko: "미국 나스닥 100 지수를 따라가는 ETF입니다." },
]

export const stockOf = (t: string) => STOCKS.find((s) => s.ticker === t)!
export const STOCK_BY = new Map(STOCKS.map((s) => [s.ticker, s]))
