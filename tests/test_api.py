"""서비스용 데이터 API (api.py): 저장값 조회, 없는 종목 즉시 수집·정기 수집 등록, 한도·토큰."""

from __future__ import annotations

from datetime import date
from pathlib import Path

import pytest

pytest.importorskip("fastapi")
pytest.importorskip("httpx")

from fastapi.testclient import TestClient  # noqa: E402
from helpers import AT, StubPriceAdapter, make_constituents  # noqa: E402

from myfinsight.api import create_app  # noqa: E402
from myfinsight.data import jobs  # noqa: E402
from myfinsight.data.jobs import JobSettings  # noqa: E402
from myfinsight.data.price_loader import load_prices  # noqa: E402
from myfinsight.data.repository import SqlRepository, open_repository  # noqa: E402
from myfinsight.schemas.market import IndexCode  # noqa: E402

START, END = "2026-09-01", "2026-09-30"


@pytest.fixture
def repo(tmp_path: Path) -> SqlRepository:  # 요청은 다른 스레드에서 돌아서 파일 DB 사용
    r = open_repository(f"sqlite:///{tmp_path / 'api.db'}", clock=lambda: AT)
    r.save_constituents(make_constituents(IndexCode.SP500, 2))
    load_prices(
        ["AAPL"], date(2026, 9, 1), date(2026, 9, 30),
        adapter=StubPriceAdapter(source="YFINANCE"), repository=r, fx_symbol=None,
        today=date(2026, 10, 1),
    )  # fmt: skip
    return r


def _client(repo: SqlRepository, adapter: StubPriceAdapter | None = None, **kw: object):  # noqa: ANN202
    def no_fetch() -> StubPriceAdapter:
        raise AssertionError("저장된 종목만 요청했는데 수집함")

    app = create_app(
        lambda: repo,
        (lambda: adapter) if adapter else no_fetch,
        token=kw.pop("token", ""),
        daily_limit=kw.pop("daily_limit", 30),
        cors_origins=["*"],
        clock=lambda: AT,
        kind=kw.pop("kind", lambda symbol: (None, None)),
    )
    return TestClient(app)


def test_stored_prices_read_without_fetch(repo: SqlRepository) -> None:
    res = _client(repo).get("/prices", params={"tickers": "aapl", "start": START, "end": END})
    body = res.json()
    assert res.status_code == 200 and body["new_tickers"] == [] and body["failed"] == {}
    assert {p["ticker"] for p in body["prices"]} == {"AAPL"} and len(body["prices"]) > 10


def test_new_tickers_fetched_saved_and_added_to_universe(repo: SqlRepository) -> None:
    stub = StubPriceAdapter(source="YFINANCE", known={"MSFT", "005930.KS"})
    client = _client(repo, stub)
    res = client.get(
        "/prices", params={"tickers": "AAPL,MSFT,005930.KS,ZZZZ", "start": START, "end": END}
    )
    body = res.json()
    assert res.status_code == 200
    assert body["new_tickers"] == ["005930.KS", "MSFT"]
    assert "ZZZZ" in body["failed"]
    assert {p["ticker"] for p in body["prices"]} == {"AAPL", "MSFT", "005930.KS"}
    assert repo.extra_tickers() == ["005930.KS", "MSFT"]  # 받지 못한 ZZZZ 는 안 올림
    names = jobs.universe(repo, JobSettings(indices=[IndexCode.SP500], benchmarks=[]))
    assert {"MSFT", "005930.KS"} <= set(names)


def test_new_ticker_kind_and_name_from_yahoo(repo: SqlRepository) -> None:
    kinds = {"QQQM": ("ETF", "Invesco NASDAQ 100 ETF"), "MSFT": ("STOCK", "Microsoft")}
    stub = StubPriceAdapter(source="YFINANCE", known={"QQQM", "MSFT"})
    client = _client(repo, stub, kind=lambda s: kinds.get(s, (None, None)))
    res = client.get("/prices", params={"tickers": "QQQM,MSFT", "start": START, "end": END})
    assert res.status_code == 200
    got = {a.yfinance_symbol: a for a in repo.get_assets(["QQQM", "MSFT"])}
    assert got["QQQM"].asset_type == "ETF" and got["QQQM"].name == "Invesco NASDAQ 100 ETF"
    assert got["MSFT"].asset_type == "STOCK" and got["MSFT"].name == "Microsoft"


def test_daily_limit_for_new_tickers(repo: SqlRepository) -> None:
    client = _client(repo, StubPriceAdapter(source="YFINANCE"), daily_limit=1)
    res = client.get("/prices", params={"tickers": "MSFT,NVDA", "start": START, "end": END})
    assert res.status_code == 429
    ok = client.get("/prices", params={"tickers": "MSFT", "start": START, "end": END})
    assert ok.status_code == 200 and ok.json()["new_tickers"] == ["MSFT"]
    again = client.get("/prices", params={"tickers": "NVDA", "start": START, "end": END})
    assert again.status_code == 429


def test_token_required_when_set(repo: SqlRepository) -> None:
    client = _client(repo, token="secret")
    assert client.get("/health").status_code == 401
    res = client.get("/health", headers={"Authorization": "Bearer secret"})
    assert res.status_code == 200 and res.json()["ok"] is True


def test_assets_filter_by_type_and_index(repo: SqlRepository) -> None:
    jobs.sync_asset_types(repo, JobSettings(benchmarks=["SPY"]))
    client = _client(repo)
    assert [a["yfinance_symbol"] for a in client.get("/assets?type=ETF").json()] == ["SPY"]
    members = {r.ticker for r in make_constituents(IndexCode.SP500, 2)}
    got = {a["yfinance_symbol"] for a in client.get("/assets?index=sp500&type=stock").json()}
    assert got == members
    assert client.get("/assets?index=XYZ").status_code == 400


def test_fx_financials_news_shapes(repo: SqlRepository) -> None:
    client = _client(repo)
    assert client.get("/fx", params={"start": START, "end": END}).json() == []
    assert client.get("/financials/AAPL").json() == []
    assert client.get("/news/AAPL?days=7").json() == []
    empty = client.get("/prices", params={"tickers": "", "start": START, "end": END})
    assert empty.status_code == 400
