"""Module2 금융 데이터: Repository 위의 MarketData 파사드, 품질 판정, 디스크립터, 지표, 뉴스 근거.

분석 코드가 DB 를 읽는 유일한 통로. 모든 조회는 MarketDataView(as_of) 를 거쳐 기준일 이후 자료를 막는다.
"""

from backend.analysis.m2_data.market_data import MarketData, MarketDataView

__all__ = ["MarketData", "MarketDataView"]
