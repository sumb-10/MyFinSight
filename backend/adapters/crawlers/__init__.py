"""실제 API 크롤러 (역할 A 가 만든 원본을 앱·DB 없이 단독으로 돌도록 정리한 것).

각 모듈은 "API 를 부르고 응답을 해석하는" 일만 한다. 재시도·배치·명세 형식(RawPriceBatch 등)
맞추기는 adapters/real.py 의 진짜 어댑터가 맡는다.

| 모듈 | 출처 | 필요한 .env 값 |
|---|---|---|
| yfinance_client | yfinance | 없음 (yfinance 패키지 필요) |
| kis_client | 한국투자증권 Open API | KIS_APP_KEY, KIS_APP_SECRET, KIS_ENV |
| tiingo_client | Tiingo | TIINGO_API_KEY |
| alpaca_client | Alpaca Markets | ALPACA_API_KEY_ID, ALPACA_API_SECRET_KEY, ALPACA_FEED |
| dart_client | OpenDART | DART_API_KEY |
| edgar_client | SEC EDGAR | SEC_USER_AGENT ("이름 이메일") |
| naver_news_client | 네이버 뉴스 검색 | NAVER_CLIENT_ID, NAVER_CLIENT_SECRET, NAVER_API |
| newsapi_client | NewsAPI.org | NEWSAPI_KEY |
| google_news_rss_client | Google News RSS | 없음 |
"""
