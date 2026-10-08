"""어댑터 고르기 테스트."""

from __future__ import annotations

import pytest

from myfinsight.data.adapters.factory import financial_adapter, news_adapter, price_adapter
from myfinsight.data.adapters.real import (
    DartFinancialAdapter,
    GoogleNewsRssAdapter,
    TiingoPriceAdapter,
    YFinancePriceAdapter,
)
from myfinsight.schemas.errors import DataSourceError


def test_picks_real_adapters() -> None:
    assert isinstance(price_adapter(), YFinancePriceAdapter)  # 기본 = yfinance
    assert isinstance(price_adapter("TIINGO", retry_max=1), TiingoPriceAdapter)
    assert isinstance(financial_adapter("DART"), DartFinancialAdapter)
    assert isinstance(news_adapter("GOOGLE_RSS", lang="en", country="US"), GoogleNewsRssAdapter)


def test_bad_source() -> None:
    with pytest.raises(DataSourceError):
        price_adapter("BLOOMBERG")
    with pytest.raises(DataSourceError):
        news_adapter("DART")
