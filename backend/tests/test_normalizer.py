"""M02-02 정규화기: 행 제거·티커 정규화·환율 분리·결정론·PriceFrame 계약."""

from __future__ import annotations

from datetime import UTC, date, datetime

import pandas as pd
import pytest
from helpers import StubPriceAdapter, fin_row, financial_batch, news_batch, news_row, price_rows

from backend.schemas.contracts import price_frame_problems
from backend.pipeline.normalizer import (
    asset_id_for,
    constituent_ticker,
    default_asset,
    normalize,
    normalize_financials,
    normalize_news,
    normalize_ticker,
    normalize_to_frame,
    to_price_frame,
)
from backend.schemas.errors import DataQualityError
from backend.schemas.market import PriceBar, RawPriceBatch

AT = datetime(2026, 10, 1, tzinfo=UTC)


def _batch(payload: dict, source: str = "yfinance") -> RawPriceBatch:
    return RawPriceBatch(
        source=source,
        requested_tickers=list(payload),
        start=date(2026, 9, 1),
        end=date(2026, 9, 30),
        fetched_at=AT,
        payload=payload,
    )


@pytest.mark.parametrize(
    ("raw", "want"),
    [
        ("brk.b", "BRK-B"),
        (" msft ", "MSFT"),
        ("BF.B", "BF-B"),
        ("005930.ks", "005930.KS"),
        ("KRW=X", "KRW=X"),
    ],
)
def test_normalize_ticker(raw: str, want: str) -> None:
    assert normalize_ticker(raw) == want


def test_bad_rows_removed_and_counted() -> None:
    payload = {
        "msft": [
            {"date": "2026-09-01", "adj_close": 100.0, "volume": 10},
            {"date": "2026-09-02", "adj_close": None, "volume": 10},
            {"date": "2026-09-03", "adj_close": float("nan"), "volume": 10},
            {"date": "2026-09-04", "adj_close": 0, "volume": 10},
            {"date": "2026-09-05", "adj_close": -1.5, "volume": 10},
            {"date": "not-a-date", "adj_close": 101.0, "volume": 10},
            {"date": "2026-09-08T00:00:00", "adj_close": "102.5", "volume": -3},
        ],
    }
    r = normalize(_batch(payload))
    assert [(b.ticker, b.date, b.adj_close) for b in r.bars] == [
        ("MSFT", date(2026, 9, 1), 100.0),
        ("MSFT", date(2026, 9, 8), 102.5),
    ]
    assert r.bars[1].volume is None  # 음수 거래량은 값만 비움 (행은 유지)
    assert r.dropped == 5
    assert r.dropped_by_reason == {"invalid_price": 4, "invalid_date": 1}
    assert r.dropped_by_ticker == {"MSFT": 5}
    assert all(b.source == "yfinance" and b.fetched_at == AT for b in r.bars)


def test_currency_and_duplicates() -> None:
    payload = {
        "005930.KS": [{"date": "2026-09-01", "adj_close": 70000.0, "volume": 1}],
        "AAPL": [{"date": "2026-09-01", "adj_close": 1.0, "currency": "EUR"}],
        "BRK.B": [{"date": "2026-09-01", "adj_close": 2.0}],
        "BRK-B": [{"date": "2026-09-01", "adj_close": 1.0}],
    }
    r = normalize(_batch(payload))
    assert [(b.ticker, b.adj_close, b.currency) for b in r.bars] == [
        ("005930.KS", 70000.0, "KRW"),
        ("BRK-B", 1.0, "USD"),  # 정렬상 BRK-B 먼저
    ]
    assert r.dropped_by_reason == {"unsupported_currency": 1, "duplicate": 1}
    with pytest.raises(DataQualityError) as e:
        to_price_frame(r.bars)
    assert e.value.code == "DATA_MIXED_CURRENCY"
    kr, meta = to_price_frame(r.bars, currency="KRW")
    assert list(kr.columns) == ["005930.KS"] and meta.currency == "KRW"


def test_kr_frame_keeps_only_krw() -> None:
    tickers = ["005930.KS", "069500.KS", "SPY"]
    start, end = date(2026, 9, 1), date(2026, 9, 30)
    b = StubPriceAdapter().fetch(tickers, start, end)
    kr, meta, _ = normalize_to_frame(b, currency="KRW")
    assert list(kr.columns) == tickers[:2] and meta.currency == "KRW"
    want = {r["date"]: r["adj_close"] for r in price_rows("005930.KS", start, end)}
    assert kr["005930.KS"].to_dict() == {pd.Timestamp(d): v for d, v in want.items()}


@pytest.mark.parametrize(
    ("symbol", "asset_id", "market", "exchange", "ticker", "member"),
    [
        ("005930.KS", "KR-005930", "KR", "KOSPI", "005930", "005930"),
        ("091990.KQ", "KR-091990", "KR", "KOSDAQ", "091990", "091990"),
        ("brk.b", "US-BRK-B", "US", None, "BRK-B", "BRK-B"),
    ],
)
def test_asset_ids(
    symbol: str, asset_id: str, market: str, exchange: str | None, ticker: str, member: str
) -> None:
    """계약: market 은 US·KR, 거래소는 exchange, 구성종목 티커는 미국 yfinance·한국 6자리."""
    a = default_asset(symbol)
    assert asset_id_for(symbol) == a.asset_id == asset_id
    assert (a.market, a.exchange, a.ticker) == (market, exchange, ticker)
    assert constituent_ticker(symbol) == member


def test_normalize_financials_and_news() -> None:
    dart = financial_batch(
        "DART",
        {
            "00126380": [
                fin_row("2024_11011", "매출액", 3.0e14, "2025-03-11"),
                fin_row("2024_11011", "영업이익", None, "2025-03-11"),  # type: ignore[arg-type]
            ],
            "99999999": [fin_row("2024_11011", "매출액", 1.0, "2025-03-11")],
        },
    )
    rows, dropped = normalize_financials(dart, {"00126380": "KR-005930"})
    assert [(r.asset_id, r.metric) for r in rows] == [("KR-005930", "매출액")]
    assert dropped["unknown_asset"] == 1 and dropped["missing_value_or_date"] == 1
    assert rows[0].source == "DART" and rows[0].disclosed_at == date(2025, 3, 11)
    news = news_batch(
        "NAVER_NEWS",
        {
            "삼성전자": [news_row(1, "2026-09-18T14:30:00+09:00"), news_row(1, "2026-09-18")],
            "반도체": [news_row(2, "2026-09-19T01:00:00Z")],
        },
    )
    items, dropped = normalize_news(news, dict.fromkeys(news.payload, "KR-005930"))
    assert [n.url for n in items] == [
        "https://news.example.com/0001",
        "https://news.example.com/0002",
    ]
    assert all(n.published_at.tzinfo is not None for n in items)
    assert dropped["duplicate"] == 1


def test_fx_goes_to_fxrate() -> None:
    payload = {
        "KRW=X": [
            {"date": "2026-09-01", "adj_close": 1390.5, "volume": None},
            {"date": "2026-09-02", "adj_close": None, "volume": None},
        ],
        "SPY": [{"date": "2026-09-01", "adj_close": 500.0, "volume": 1}],
    }
    r = normalize(_batch(payload), fx_symbol="KRW=X")
    assert [b.ticker for b in r.bars] == ["SPY"]
    assert [(f.pair, f.date, f.rate) for f in r.fx] == [("USDKRW", date(2026, 9, 1), 1390.5)]
    assert r.dropped == 1


def test_same_input_same_output() -> None:
    ad = StubPriceAdapter()
    b = ad.fetch(["SPY", "NVDA", "KRW=X"], date(2025, 1, 1), date(2026, 9, 30))
    assert normalize(b) == normalize(b.model_copy(deep=True))


def test_frame_meets_contract() -> None:
    ad = StubPriceAdapter()
    tickers = ["SPY", "MSFT", "NVDA", "KO"]
    b = ad.fetch(tickers, date(2021, 1, 1), date(2026, 9, 30))
    frame, meta, result = normalize_to_frame(b)
    assert price_frame_problems(frame, allow_nan=False) == []
    assert list(frame.columns) == sorted(tickers)
    assert len(frame) == len(price_rows("SPY", date(2021, 1, 1), date(2026, 9, 30)))
    assert meta.tickers == sorted(tickers)
    assert meta.as_of == date(2026, 9, 30)
    assert result.dropped == 0


def test_missing_rows_become_nan() -> None:
    gap = date(2026, 9, 15)
    ad = StubPriceAdapter(missing={"AMD": [gap]}, overrides={"KO": {gap: None}})
    b = ad.fetch(["AMD", "KO", "SPY"], date(2026, 9, 1), date(2026, 9, 30))
    frame, _, result = normalize_to_frame(b)
    assert pd.isna(frame.loc["2026-09-15", "AMD"]) and pd.isna(frame.loc["2026-09-15", "KO"])
    assert result.dropped_by_reason == {"invalid_price": 1}
    assert price_frame_problems(frame) == []
    assert price_frame_problems(frame, allow_nan=False) == ["결측(NaN)이 있음"]


def test_to_price_frame_rejects_empty_and_duplicates() -> None:
    with pytest.raises(DataQualityError) as e:
        to_price_frame([])
    assert e.value.code == "DATA_INVALID_BARS"
    bar = PriceBar(ticker="A", date=date(2026, 9, 1), adj_close=1.0, source="x", fetched_at=AT)
    other = bar.model_copy(update={"source": "y"})
    with pytest.raises(DataQualityError):
        to_price_frame([bar, other])


def test_meta_multi_source_and_oldest_fetch() -> None:
    old = datetime(2026, 9, 1, tzinfo=UTC)
    bars = [
        PriceBar(ticker="A", date=date(2026, 9, 1), adj_close=1.0, source="b", fetched_at=AT),
        PriceBar(ticker="B", date=date(2026, 9, 2), adj_close=2.0, source="a", fetched_at=old),
    ]
    _, meta = to_price_frame(bars)
    assert meta.source == "a+b"
    assert meta.fetched_at == old
    assert meta.as_of == date(2026, 9, 2)


def test_ohlc_kept_when_present() -> None:
    row = {"date": "2026-09-01", "adj_close": 9.5, "open": 9.8, "high": 10.2, "low": 0, "close": 10}
    bar = normalize(_batch({"A": [row, {"date": "2026-09-02", "adj_close": 9.6}]})).bars
    assert (bar[0].open, bar[0].high, bar[0].low, bar[0].close) == (9.8, 10.2, None, 10)
    assert bar[1].close is None  # 없으면 None, 행은 남음
