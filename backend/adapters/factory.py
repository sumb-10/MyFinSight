"""출처 이름으로 어댑터 만들기. 다른 팀원은 이 함수만 쓰면 된다.

from backend.adapters.factory import price_adapter, financial_adapter, news_adapter

prices = price_adapter()             # 기본 출처 yfinance (명세 M02-01)
tiingo = price_adapter("TIINGO")     # 출처 지정
dart = financial_adapter("DART")
naver = news_adapter("NAVER_NEWS")
"""

from __future__ import annotations

from typing import Any

from backend.schemas.errors import DataSourceError


def _pick(table: dict[str, Any], source: str, kind: str) -> Any:
    try:
        return table[source]
    except KeyError:
        raise DataSourceError(
            f"{kind} 출처가 아님: {source}", details={"allowed": sorted(table)}
        ) from None


def price_adapter(source: str | None = None, **kwargs: Any) -> Any:
    """가격 어댑터. source=None 이면 yfinance."""
    from backend.adapters.real import PRICE_ADAPTERS

    return _pick(PRICE_ADAPTERS, source or "YFINANCE", "가격")(**kwargs)


def financial_adapter(source: str, **kwargs: Any) -> Any:
    """재무 어댑터. source 는 "DART" 또는 "SEC_EDGAR"."""
    from backend.adapters.real import FINANCIAL_ADAPTERS

    return _pick(FINANCIAL_ADAPTERS, source, "재무")(**kwargs)


def news_adapter(source: str, **kwargs: Any) -> Any:
    """뉴스 어댑터. source 는 "NAVER_NEWS", "NEWSAPI", "GOOGLE_RSS" 중 하나."""
    from backend.adapters.real import NEWS_ADAPTERS

    return _pick(NEWS_ADAPTERS, source, "뉴스")(**kwargs)
