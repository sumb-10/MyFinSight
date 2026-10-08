"""종목 종류 판단 순서 (공식 API 먼저, yfinance 보완). 네트워크 없이 각 단계를 바꿔 끼워 확인."""

import io
import zipfile

import pytest

from myfinsight.data import asset_kind
from myfinsight.data.crawlers import tiingo_client


def _steps(monkeypatch, kr=None, us=None):
    calls = []

    def make(source, answer):
        def step(symbol):
            calls.append(source)
            if isinstance(answer, Exception):
                raise answer
            return answer

        return (source, step)

    if kr is not None:
        monkeypatch.setattr(asset_kind, "KR_STEPS", [make(s, a) for s, a in kr])
    if us is not None:
        monkeypatch.setattr(asset_kind, "US_STEPS", [make(s, a) for s, a in us])
    return calls


def test_kr_stock_decided_by_dart_without_yahoo(monkeypatch):
    calls = _steps(
        monkeypatch,
        kr=[("DART", ("STOCK", "삼성전자")), ("KIS", ("STOCK", "x")), ("YF", ("ETF", "y"))],
    )
    assert asset_kind.classify("005930.KS") == ("STOCK", "삼성전자")
    assert calls == ["DART"]


def test_kr_etf_from_kis_when_not_in_dart(monkeypatch):
    calls = _steps(
        monkeypatch,
        kr=[("DART", (None, None)), ("KIS", ("ETF", "KODEX 200")), ("YF", ("STOCK", "y"))],
    )
    assert asset_kind.classify("069500.KS") == ("ETF", "KODEX 200")
    assert calls == ["DART", "KIS"]


def test_failures_fall_back_to_yahoo(monkeypatch):
    _steps(
        monkeypatch,
        kr=[("DART", RuntimeError("키 없음")), ("KIS", RuntimeError("x")), ("YF", ("ETF", "Y"))],
    )
    assert asset_kind.classify("069500.KS") == ("ETF", "Y")


def test_us_kind_from_tiingo_name_from_yahoo(monkeypatch):
    calls = _steps(monkeypatch, us=[("TIINGO", ("ETF", None)), ("YF", ("STOCK", "SPDR S&P 500"))])
    assert asset_kind.classify("SPY") == ("ETF", "SPDR S&P 500")  # 종류는 공식(Tiingo) 우선
    assert calls == ["TIINGO", "YF"]


def test_index_prefix_and_unknown(monkeypatch):
    calls = _steps(monkeypatch, us=[("TIINGO", (None, None)), ("YF", (None, None))])
    assert asset_kind.classify("^GSPC") == ("INDEX", None)
    assert calls == []
    assert asset_kind.classify("ZZZZ") == (None, None)


def test_kis_codes_mapped(monkeypatch):
    from myfinsight.data.crawlers import kis_client

    monkeypatch.setattr(
        kis_client, "stock_info", lambda code: {"scty_grp_id_cd": "EN", "prdt_abrv_name": "ETN"}
    )
    assert asset_kind._kis("580001.KS") == ("ETF", "ETN")


class _Res:
    def __init__(self, content):
        self.content = content

    def raise_for_status(self):
        pass


@pytest.fixture
def tiingo_zip(monkeypatch):
    rows = (
        "ticker,exchange,assetType,priceCurrency,startDate,endDate\n"
        "spy,NYSE ARCA,ETF,USD,1993-01-29,2026-10-06\n"
        "aapl,NASDAQ,Stock,USD,1980-12-12,2026-10-06\n"
        "brk-b,NYSE,Stock,USD,1996-05-09,2026-10-06\n"
        "abc,NYSE,Mutual Fund,USD,2001-01-01,2005-01-01\n"
        "abc,NASDAQ,ETF,USD,2010-01-01,2026-10-06\n"
    )
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        z.writestr("supported_tickers.csv", rows)
    got = []

    class _Session:
        def get(self, url, timeout):
            got.append(url)
            return _Res(buf.getvalue())

    monkeypatch.setattr(tiingo_client, "_session", _Session())
    return got


def test_tiingo_supported_list_parsed_and_cached(tiingo_zip):
    assert asset_kind._tiingo("SPY") == ("ETF", None)
    assert asset_kind._tiingo("BRK.B") == ("STOCK", None)
    assert asset_kind._tiingo("ABC") == ("ETF", None)  # 가장 최근 줄 기준
    assert asset_kind._tiingo("NONE") == (None, None)
    assert len(tiingo_zip) == 1  # 두 번째부터는 캐시
