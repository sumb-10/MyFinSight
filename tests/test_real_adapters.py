"""어댑터 + 크롤러 테스트 (네트워크 없음: HTTP 응답을 테스트용으로 끼운다).

확인하는 것
- 크롤러가 API 응답을 제대로 해석하는가 (분할 보정, 페이지 넘기기, 공시일 등)
- 출처가 달라도 어댑터의 행 모양(키)이 같은가 (M02-02 가 출처와 상관없이 정규화하는 근거)
- .env 키가 없으면 재시도 없이 바로 알려 주는가
"""

from __future__ import annotations

import os
from datetime import date

import pandas as pd
import pytest
from helpers import FIN_ROW_KEYS, NEWS_ROW_KEYS, PRICE_ROW_KEYS
from stub_http import StubResponse, StubSession

from myfinsight.data.adapters import (
    FinancialSourceAdapter,
    NewsSourceAdapter,
    PriceSourceAdapter,
)
from myfinsight.data.adapters.real import (
    AlpacaPriceAdapter,
    DartFinancialAdapter,
    GoogleNewsRssAdapter,
    KisPriceAdapter,
    NaverNewsAdapter,
    NewsApiAdapter,
    SecFinancialAdapter,
    TiingoPriceAdapter,
    YFinancePriceAdapter,
)
from myfinsight.data.crawlers import (
    alpaca_client,
    config,
    dart_client,
    edgar_client,
    google_news_rss_client,
    kis_client,
    naver_news_client,
    newsapi_client,
    tiingo_client,
    yfinance_client,
)
from myfinsight.data.crawlers.common import num, rfc822, strip_html, to_date
from myfinsight.data.crawlers.config import MissingApiKeyError

SEP_1, SEP_30 = date(2026, 9, 1), date(2026, 9, 30)


def _no_sleep(waits: list[float]):  # noqa: ANN202
    return waits.append


ROW_KEYS = {"price": PRICE_ROW_KEYS, "financial": FIN_ROW_KEYS, "news": NEWS_ROW_KEYS}
"""출처별 어댑터가 모두 내야 하는 행 키."""


# ---------------------------------------------------------------- 설정 (.env)


def test_parse_env() -> None:
    text = (
        "# 주석\n\nDART_API_KEY=abc123\nexport TIINGO_API_KEY='t k'\n"
        'SEC_USER_AGENT="Kim kim@example.com"\nNAVER_API=developers # 메모\n'
    )
    assert config.parse_env(text) == {
        "DART_API_KEY": "abc123",
        "TIINGO_API_KEY": "t k",
        "SEC_USER_AGENT": "Kim kim@example.com",
        "NAVER_API": "developers",
    }


def test_load_env_does_not_override(monkeypatch: pytest.MonkeyPatch, tmp_path) -> None:  # noqa: ANN001
    env = tmp_path / ".env"
    env.write_text("DART_API_KEY=from_file\nNEWSAPI_KEY=news\n", encoding="utf-8")
    monkeypatch.setenv("DART_API_KEY", "from_shell")
    config.load_env(env, force=True)
    try:
        assert config.DART_API_KEY == "from_shell" and config.NEWSAPI_KEY == "news"
    finally:
        os.environ.pop("NEWSAPI_KEY", None)


def test_defaults_and_require() -> None:
    assert (config.KIS_ENV, config.ALPACA_FEED, config.NAVER_API) == ("prod", "sip", "hub")
    with pytest.raises(MissingApiKeyError) as e:
        config.require(DART_API_KEY=config.DART_API_KEY, NEWSAPI_KEY="x")
    assert e.value.details["missing"] == ["DART_API_KEY"] and ".env" in e.value.message


def test_common_helpers() -> None:
    assert num("1,234") == 1234.0 and num("-") is None and num(None) is None and num("x") is None
    assert to_date("20260930") == to_date("2026-09-30T10:00:00") == date(2026, 9, 30)
    assert rfc822("Tue, 29 Sep 2026 09:00:00 +0900").isoformat() == "2026-09-29T00:00:00+00:00"
    assert rfc822("이상한 날짜") is None
    assert strip_html("<b>삼성</b>전자 &amp; SK") == "삼성전자 & SK"


# ---------------------------------------------------------------- 가격


def test_tiingo_split_adjust_and_shape(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("TIINGO_API_KEY", "tk")
    raw = [  # 9/3 에 2:1 분할 → 9/2 이전 값은 2로 나눠야 분할 보정
        {"date": "2026-09-02T00:00:00.000Z", "open": 200, "high": 210, "low": 190, "close": 204,
         "volume": 100, "adjClose": 101.0, "splitFactor": 1.0},
        {"date": "2026-09-03T00:00:00.000Z", "open": 103, "high": 106, "low": 101, "close": 105,
         "volume": 300, "adjClose": 104.5, "splitFactor": 2.0},
    ]  # fmt: skip
    stub = StubSession(lambda url, kw: StubResponse(200, raw))
    monkeypatch.setattr(tiingo_client, "_session", stub)
    ad = TiingoPriceAdapter()
    assert isinstance(ad, PriceSourceAdapter)
    batch = ad.fetch(["BRK.B"], SEP_1, SEP_30)
    rows = batch.payload["BRK.B"]
    assert batch.source == "TIINGO" and batch.failed_tickers == {}
    assert rows[0]["close"] == 102.0 and rows[0]["volume"] == 200 and rows[0]["adj_close"] == 101.0
    assert rows[1]["close"] == 105.0 and rows[1]["volume"] == 300
    assert "/brk-b/prices" in stub.calls[0][1]  # 원본 규칙: BRK.B → brk-b
    assert stub.calls[0][2]["headers"]["Authorization"] == "Token tk"
    assert set(rows[0]) == ROW_KEYS["price"]


def test_missing_key_stops_without_retry() -> None:
    waits: list[float] = []
    ad = TiingoPriceAdapter(sleep=_no_sleep(waits))
    with pytest.raises(MissingApiKeyError, match="TIINGO_API_KEY"):
        ad.fetch(["MSFT"], SEP_1, SEP_30)
    assert waits == []  # 키가 없으면 재시도해도 소용없음


def test_tiingo_404_retried_then_recorded(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("TIINGO_API_KEY", "tk")
    monkeypatch.setattr(tiingo_client, "_session", StubSession(lambda u, k: StubResponse(404, {})))
    waits: list[float] = []
    batch = TiingoPriceAdapter(sleep=_no_sleep(waits), retry_max=2).fetch(["NOPE"], SEP_1, SEP_30)
    assert batch.payload == {} and "Tiingo에 NOPE 티커가 없음" in batch.failed_tickers["NOPE"]
    assert batch.failed_tickers["NOPE"].startswith("3회 시도 후 실패")
    assert waits == [1.0, 2.0]


def test_alpaca_sip_to_iex_and_paging(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("ALPACA_API_KEY_ID", "id")
    monkeypatch.setenv("ALPACA_API_SECRET_KEY", "secret")

    def handler(url: str, kw: dict) -> StubResponse:
        p = kw["params"]
        if p["feed"] == "sip":
            return StubResponse(
                403, {"message": "subscription does not permit querying recent SIP"}
            )
        mult = 1.0 if p["adjustment"] == "split" else 0.99
        if p.get("page_token") is None:
            bars = [{"t": "2026-09-02T04:00:00Z", "o": 10, "h": 11, "l": 9, "c": 10 * mult, "v": 5}]
            return StubResponse(200, {"bars": bars, "next_page_token": "p2"})
        bars = [{"t": "2026-09-03T04:00:00Z", "o": 10, "h": 12, "l": 9, "c": 11 * mult, "v": 7}]
        return StubResponse(200, {"bars": bars, "next_page_token": None})

    stub = StubSession(handler)
    monkeypatch.setattr(alpaca_client, "_session", stub)
    batch = AlpacaPriceAdapter(min_interval_sec=0).fetch(["BRK-B"], SEP_1, SEP_30)
    rows = batch.payload["BRK-B"]
    assert [r["date"] for r in rows] == ["2026-09-02", "2026-09-03"]
    assert rows[1]["close"] == 11 and rows[1]["adj_close"] == pytest.approx(10.89)
    assert "/BRK.B/bars" in stub.calls[0][1]
    assert {c[2]["params"]["feed"] for c in stub.calls[1:]} == {"iex"}
    assert set(rows[0]) == ROW_KEYS["price"]


def test_alpaca_many_symbols_in_one_request(monkeypatch: pytest.MonkeyPatch) -> None:
    """여러 종목은 /bars?symbols=… 로 묶어 받고, 묶음에서 빠진 종목만 한 개씩 다시."""
    monkeypatch.setenv("ALPACA_API_KEY_ID", "id")
    monkeypatch.setenv("ALPACA_API_SECRET_KEY", "secret")

    def handler(url: str, kw: dict) -> StubResponse:
        p = kw["params"]
        mult = 1.0 if p["adjustment"] == "split" else 0.99
        bar = {"t": "2026-09-02T04:00:00Z", "o": 10, "h": 11, "l": 9, "c": 10 * mult, "v": 5}
        if url.endswith("/stocks/bars"):  # 묶음: ZZZ 는 응답에 없음
            return StubResponse(200, {"bars": {"AAPL": [bar], "BRK.B": [bar]}})
        return StubResponse(200, {"bars": [], "next_page_token": None})

    stub = StubSession(handler)
    monkeypatch.setattr(alpaca_client, "_session", stub)
    batch = AlpacaPriceAdapter(min_interval_sec=0).fetch(["AAPL", "BRK-B", "ZZZ"], SEP_1, SEP_30)
    assert set(batch.payload) == {"AAPL", "BRK-B"} and "ZZZ" in batch.failed_tickers
    assert batch.payload["BRK-B"][0]["adj_close"] == pytest.approx(9.9)
    many = [c for c in stub.calls if c[1].endswith("/stocks/bars")]
    assert len(many) == 2 and many[0][2]["params"]["symbols"] == "AAPL,BRK.B,ZZZ"
    assert [c[1] for c in stub.calls if "/ZZZ/" in c[1]]  # 빠진 종목만 한 개씩


def test_kis_paging_and_domestic_only(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(kis_client, "get_access_token", lambda: "tok")
    monkeypatch.setattr(kis_client.time, "sleep", lambda s: None)
    monkeypatch.setenv("KIS_APP_KEY", "k")
    monkeypatch.setenv("KIS_APP_SECRET", "s")
    days = pd.bdate_range("2026-05-01", "2026-09-30")[::-1]  # KIS 는 최신순으로 준다

    def handler(url: str, kw: dict) -> StubResponse:
        hi = kw["params"]["FID_INPUT_DATE_2"]
        page = [d for d in days if d.strftime("%Y%m%d") <= hi][:100]
        out = [
            {"stck_bsop_date": d.strftime("%Y%m%d"), "stck_oprc": "70000", "stck_hgpr": "71000",
             "stck_lwpr": "69000", "stck_clpr": "70500", "acml_vol": "1234567"}
            for d in page
        ]  # fmt: skip
        return StubResponse(200, {"rt_cd": "0", "output2": out})

    stub = StubSession(handler)
    monkeypatch.setattr(kis_client, "_session", stub)
    batch = KisPriceAdapter(retry_max=0).fetch(["005930", "NVDA"], date(2026, 5, 1), SEP_30)
    rows = batch.payload["005930"]
    assert len(rows) == len(days) and len(stub.calls) == 2  # 100일씩 두 번
    assert rows[0]["date"] == "2026-05-01" and rows[0]["close"] == rows[0]["adj_close"] == 70500
    assert rows[0]["currency"] == "KRW" and rows[0]["volume"] == 1234567
    assert "6자리 국내 종목코드만" in batch.failed_tickers["NVDA"]
    assert set(rows[0]) == ROW_KEYS["price"]


def test_kis_token_cached(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("KIS_APP_KEY", "k")
    monkeypatch.setenv("KIS_APP_SECRET", "s")
    stub = StubSession(
        lambda u, k: StubResponse(
            200, {"access_token": "T1", "access_token_token_expired": "2099-01-01 00:00:00"}
        )
    )
    monkeypatch.setattr(kis_client, "_session", stub)
    assert kis_client.get_access_token() == kis_client.get_access_token() == "T1"
    assert len(stub.calls) == 1  # 두 번째는 .cache 의 토큰 재사용


def test_yfinance_kosdaq_fallback(monkeypatch: pytest.MonkeyPatch) -> None:
    asked: list[str] = []

    def stub_history(symbol: str, start: date, end: date) -> pd.DataFrame:
        asked.append(symbol)
        if symbol.endswith(".KS"):
            return pd.DataFrame()
        idx = pd.to_datetime(["2026-09-01", "2026-09-02"]).date
        return pd.DataFrame(
            {"Open": [1.0, 2.0], "High": [1.0, 2.0], "Low": [1.0, 2.0], "Close": [1.0, 2.0],
             "Adj Close": [0.9, 1.9], "Volume": [10, 20]}, index=idx,
        )  # fmt: skip

    monkeypatch.setattr(yfinance_client, "fetch_history", stub_history)
    batch = YFinancePriceAdapter(min_interval_sec=0).fetch(["091990.KS"], SEP_1, SEP_30)
    rows = batch.payload["091990.KS"]
    assert asked == ["091990.KS", "091990.KQ"] and rows[1]["adj_close"] == 1.9
    assert rows[0]["currency"] == "KRW" and yfinance_client.currency_of("KRW=X") is None
    assert set(rows[0]) == ROW_KEYS["price"]


def test_yfinance_many_then_single_for_missing(monkeypatch: pytest.MonkeyPatch) -> None:
    """yf.download 로 묶어 받고, 비어 있던 종목(.KQ 종목 등)만 한 개씩 다시."""
    idx = pd.to_datetime(["2026-09-01", "2026-09-02"])
    one = {"Open": [1.0, 2.0], "High": [1.0, 2.0], "Low": [1.0, 2.0], "Close": [1.0, 2.0],
           "Adj Close": [0.9, 1.9], "Volume": [10, 20]}  # fmt: skip
    nan = {k: [float("nan")] * 2 for k in one}
    frames = {"AAPL": pd.DataFrame(one, index=idx), "091990.KS": pd.DataFrame(nan, index=idx)}

    class StubYf:
        @staticmethod
        def download(symbols, **kw):  # type: ignore[no-untyped-def]
            return pd.concat(frames, axis=1)

    single: list[str] = []
    monkeypatch.setattr(yfinance_client, "_yf", lambda: StubYf)
    monkeypatch.setattr(
        yfinance_client,
        "price_rows",
        lambda s, a, b: single.append(s) or [{"date": "2026-09-02", "close": 5.0}],
    )
    batch = YFinancePriceAdapter(min_interval_sec=0).fetch(["AAPL", "091990.KS"], SEP_1, SEP_30)
    assert (
        batch.payload["AAPL"][1]["adj_close"] == 1.9
        and batch.payload["AAPL"][0]["currency"] == "USD"
    )
    assert single == ["091990.KS"] and batch.payload["091990.KS"][0]["close"] == 5.0


# ---------------------------------------------------------------- 재무


def test_dart_rows_point_in_time(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("DART_API_KEY", "dk")

    def handler(url: str, kw: dict) -> StubResponse:
        p = kw["params"]
        if (p["bsns_year"], p["reprt_code"]) == ("2025", "11011"):
            items = [
                {"rcept_no": "20260310000123", "bsns_year": "2025", "fs_div": "CFS",
                 "account_nm": "매출액", "thstrm_dt": "2025.01.01 ~ 2025.12.31",
                 "thstrm_amount": "300,870,903,000,000", "currency": "KRW"},
                {"rcept_no": "20260310000123", "bsns_year": "2025", "fs_div": "CFS",
                 "account_nm": "매출액", "thstrm_amount": "1"},  # 중복 계정 → 첫 번째만
            ]  # fmt: skip
            return StubResponse(200, {"status": "000", "list": items})
        if (p["bsns_year"], p["reprt_code"]) == ("2026", "11013"):
            items = [{"rcept_no": "20260515000001", "bsns_year": "2026", "fs_div": "CFS",
                      "account_nm": "매출액", "thstrm_dt": "2026.03.31 현재",
                      "thstrm_amount": "79,000,000,000,000"}]  # fmt: skip
            return StubResponse(200, {"status": "000", "list": items})
        return StubResponse(200, {"status": "013", "message": "조회된 데이타가 없습니다."})

    stub = StubSession(handler)
    monkeypatch.setattr(dart_client, "_session", stub)
    monkeypatch.setattr(dart_client, "MIN_INTERVAL_SEC", 0)
    monkeypatch.setattr(
        dart_client,
        "find_by_stock_code",
        lambda c: {"corp_code": "00126380", "corp_name": "삼성전자"},
    )
    ad = DartFinancialAdapter()
    assert isinstance(ad, FinancialSourceAdapter)
    batch = ad.fetch(["005930"], date(2026, 1, 1), date(2026, 4, 30))
    rows = batch.payload["005930"]
    assert len(rows) == 1  # 5월 공시된 1분기 보고서는 4월 말 기준으로는 안 보임
    r = rows[0]
    assert (r["disclosed_at"], r["period_end"], r["value"]) == (
        "2026-03-10",
        "2025-12-31",
        300_870_903_000_000.0,
    )
    assert {c[2]["params"]["corp_code"] for c in stub.calls} == {"00126380"}
    assert {c[2]["params"]["bsns_year"] for c in stub.calls} == {"2025", "2026"}
    assert set(r) == ROW_KEYS["financial"]


def _facts() -> dict:
    def fy(val, end, filed, start=None, form="10-K", accn="a"):  # noqa: ANN001, ANN202
        e = {"val": val, "end": end, "filed": filed, "form": form, "accn": accn}
        if start:
            e["start"] = start
        return e

    rev = [
        fy(100, "2024-12-31", "2025-02-20", "2024-01-01", accn="k24"),
        fy(101, "2024-12-31", "2026-02-19", "2024-01-01", accn="k25"),  # 비교수치 → 무시
        fy(120, "2025-12-31", "2026-02-19", "2025-01-01", accn="k25"),
        fy(30, "2026-03-31", "2026-05-01", "2026-01-01", form="10-Q"),
        fy(25, "2025-03-31", "2025-05-01", "2025-01-01", form="10-Q"),
    ]
    assets = [fy(500, "2025-12-31", "2026-02-19")]
    shares = [fy(10, "2026-04-20", "2026-05-01", form="10-Q")]
    return {
        "facts": {
            "us-gaap": {
                "Revenues": {"units": {"USD": rev}},
                "NetIncomeLoss": {"units": {"USD": rev}},
                "Assets": {"units": {"USD": assets}},
                "StockholdersEquity": {"units": {"USD": assets}},
            },
            "dei": {"EntityCommonStockSharesOutstanding": {"units": {"shares": shares}}},
        }
    }


def test_edgar_build_rows() -> None:
    rows = edgar_client.build_rows(_facts(), years=3, today=date(2026, 10, 1))
    fy24 = next(r for r in rows if r["metric"] == "매출액" and r["period"] == "FY2024")
    assert fy24["value"] == 100 and fy24["disclosed_at"] == "2025-02-20"  # 최초 제출값
    snap = {r["metric"]: r["value"] for r in rows if r["report_code"] == "SNAPSHOT"}
    assert snap["순이익(TTM)"] == 120 + 30 - 25 and snap["BPS"] == 50


def test_sec_adapter(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("SEC_USER_AGENT", "Kim kim@example.com")
    stub = StubSession(lambda u, k: StubResponse(200, _facts()))
    monkeypatch.setattr(edgar_client, "_session", stub)
    batch = SecFinancialAdapter(include_snapshot=False, min_interval_sec=0).fetch(
        ["789019"], date(2025, 1, 1), date(2026, 2, 18)
    )
    rows = batch.payload["789019"]
    assert {r["period"] for r in rows} == {"FY2024"}  # FY2025 는 2026-02-19 공시
    assert "CIK0000789019.json" in stub.calls[0][1]
    assert stub.calls[0][2]["headers"]["User-Agent"] == "Kim kim@example.com"
    assert set(rows[0]) == ROW_KEYS["financial"]


# ---------------------------------------------------------------- 뉴스


@pytest.mark.parametrize(
    ("api", "id_header"),
    [("hub", "X-NCP-APIGW-API-KEY-ID"), ("developers", "X-Naver-Client-Id")],
)
def test_naver(monkeypatch: pytest.MonkeyPatch, api: str, id_header: str) -> None:
    monkeypatch.setenv("NAVER_CLIENT_ID", "cid")
    monkeypatch.setenv("NAVER_CLIENT_SECRET", "sec")
    monkeypatch.setenv("NAVER_API", api)
    items = [
        {"title": "<b>삼성전자</b> 실적", "originallink": "https://a.example/1", "link": "x",
         "description": "요약 &quot;A&quot;", "pubDate": "Tue, 29 Sep 2026 09:00:00 +0900"},
        {"title": "옛날 기사", "link": "https://a.example/2", "description": "",
         "pubDate": "Mon, 03 Aug 2026 09:00:00 +0900"},
    ]  # fmt: skip
    stub = StubSession(lambda u, k: StubResponse(200, {"items": items}))
    monkeypatch.setattr(naver_news_client, "_session", stub)
    ad = NaverNewsAdapter()
    assert isinstance(ad, NewsSourceAdapter)
    arts = ad.fetch(["삼성전자"], SEP_1, SEP_30).payload["삼성전자"]
    assert len(arts) == 1 and arts[0]["title"] == "삼성전자 실적"
    assert (
        arts[0]["published_at"] == "2026-09-29T00:00:00Z" and arts[0]["description"] == '요약 "A"'
    )
    assert id_header in stub.calls[0][2]["headers"]
    assert set(arts[0]) == ROW_KEYS["news"]


def test_newsapi(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("NEWSAPI_KEY", "nk")
    arts = [
        {"url": "https://b.example/1", "title": "NVIDIA beats", "description": "d",
         "source": {"name": "Wire"}, "publishedAt": "2026-09-20T12:00:00Z"},
        {"url": "https://b.example/2", "title": "[Removed]", "publishedAt": "2026-09-20T12:00:00Z"},
    ]  # fmt: skip
    monkeypatch.setattr(
        newsapi_client,
        "_session",
        StubSession(lambda u, k: StubResponse(200, {"status": "ok", "articles": arts})),
    )
    got = NewsApiAdapter().fetch(["NVIDIA"], SEP_1, SEP_30).payload["NVIDIA"]
    assert [a["url"] for a in got] == ["https://b.example/1"] and got[0]["publisher"] == "Wire"
    assert set(got[0]) == ROW_KEYS["news"]


def test_newsapi_error_recorded(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("NEWSAPI_KEY", "nk")
    bad = {"status": "error", "code": "rateLimited", "message": "too many"}
    monkeypatch.setattr(
        newsapi_client, "_session", StubSession(lambda u, k: StubResponse(429, bad))
    )
    batch = NewsApiAdapter(retry_max=0).fetch(["NVIDIA"], SEP_1, SEP_30)
    assert "rateLimited" in batch.failed_keys["NVIDIA"]


RSS = """<?xml version="1.0" encoding="UTF-8"?><rss><channel>
<item><title>엔비디아 신제품 - 예시일보</title><link>https://c.example/1</link>
<pubDate>Wed, 16 Sep 2026 03:00:00 GMT</pubDate><description>&lt;a&gt;요약&lt;/a&gt;</description>
<source url="https://c.example">예시일보</source></item>
<item><title>링크 없음</title></item>
</channel></rss>""".encode()


def test_google_rss(monkeypatch: pytest.MonkeyPatch) -> None:
    stub = StubSession(lambda u, k: StubResponse(200, content=RSS))
    monkeypatch.setattr(google_news_rss_client, "_session", stub)
    got = GoogleNewsRssAdapter().fetch(["엔비디아"], SEP_1, SEP_30).payload["엔비디아"]
    assert (
        len(got) == 1 and got[0]["title"] == "엔비디아 신제품" and got[0]["publisher"] == "예시일보"
    )
    assert got[0]["description"] == "요약" and got[0]["language"] == "ko"
    assert stub.calls[0][2]["params"]["ceid"] == "KR:ko"
    assert set(got[0]) == ROW_KEYS["news"]


def test_dart_reconnects_after_remote_disconnect(monkeypatch: pytest.MonkeyPatch) -> None:
    import requests

    def dropped(url, kw):  # noqa: ANN001, ANN202
        raise requests.ConnectionError("Remote end closed connection without response")

    fresh = StubSession(lambda u, k: StubResponse(200, {"status": "013"}))
    slept: list[float] = []
    monkeypatch.setattr(dart_client, "_session", StubSession(dropped))
    monkeypatch.setattr(dart_client, "http_session", lambda: fresh)
    monkeypatch.setattr(dart_client.time, "sleep", slept.append)
    monkeypatch.setenv("DART_API_KEY", "k")
    assert dart_client.fetch_financials("00126380", 2025) == []  # 새 연결로 다시 불러 성공
    assert len(fresh.calls) == 1 and 2 in slept
