"""종목 찾기·이름 (GET /stocks/search, GET /stocks): 유니버스 구성종목 목록, 검색 순서, 티커 표기 변형, 하루 캐시."""

from __future__ import annotations

import datetime as dt

import pytest
from fastapi.testclient import TestClient

from backend.analysis.api.app import API_PREFIX as P
from backend.analysis.api.app import create_analysis_app
from backend.analysis.common.llm import StubLlm
from backend.analysis.m2_data.stocks import load_stocks, lookup, search
from backend.analysis.settings import AnalysisSettings
from backend.db import open_repository
from backend.tests.analysis.conftest import seed_repository


@pytest.fixture(scope="module")
def repo():
    r = open_repository("sqlite://", clock=lambda: dt.datetime(2026, 1, 5, tzinfo=dt.UTC))
    seed_repository(r)
    return r


@pytest.fixture(scope="module")
def stocks(repo):
    return load_stocks(repo, dt.date(2026, 11, 10))


def test_list_is_universe_stocks_once_each(stocks):
    tickers = [s["ticker"] for s in stocks]
    assert len(tickers) == len(set(tickers))  # S&P 500 과 NASDAQ-100 에 함께 있는 NVDA 도 한 번
    assert "SPY" not in tickers and "069500.KS" not in tickers  # 구성종목이 아닌 ETF 는 없다
    mu = next(s for s in stocks if s["ticker"] == "MU")
    assert mu == {"ticker": "MU", "name_ko": "Micron Technology", "name_en": "Micron Technology", "market": "US", "sector_ko": "정보기술"}  # 미국: 영어 이름
    sam = next(s for s in stocks if s["ticker"] == "005930.KS")
    assert sam == {"ticker": "005930.KS", "name_ko": "삼성전자", "name_en": None, "market": "KR", "sector_ko": "정보기술"}  # 한국: 한국어 이름


@pytest.mark.parametrize(("q", "first"), [
    ("MU", "MU"), ("  micron   tech ", "MU"), ("NvIdIa", "NVDA"), ("삼성", "005930.KS"), ("005930", "005930.KS"),
    ("하이닉스", "000660.KS"), ("johnson&johnson", "JNJ"), ("alphabet", "GOOGL"),
])  # fmt: skip
def test_search_finds_by_name_or_ticker(stocks, q, first):
    assert search(stocks, q)[0]["ticker"] == first


def test_search_order_and_limits(stocks):
    tick = lambda q: [s["ticker"] for s in search(stocks, q)]  # noqa: E731
    assert tick("am") == ["AMD", "AMZN", "AMAT", "PG"]  # 티커 앞부분(짧은 티커 먼저, 같으면 이름순) → 이름 안에 포함(Procter & Gamble)
    assert tick("goog") == ["GOOG", "GOOGL"]  # 티커가 똑같은 것이 먼저
    assert tick("alphabet") == ["GOOGL", "GOOG"]  # 이름으로 맞으면 짧은 이름 → 이름순 (Class A, Class C)
    assert search(stocks, "") == [] and search(stocks, " ,. ") == [] and search(stocks, "zzzz") == []
    assert len(search(stocks, "a", limit=2)) == 2 and len(search(stocks, "a", limit=999)) <= 20


def test_lookup_echoes_requested_spelling(stocks):
    got = lookup(stocks, ["MU", "005930", "005930.KS", "mu", "NOPE", "SPY", " ", "MU"])
    assert [(s["ticker"], s["name_ko"]) for s in got] == [("MU", "Micron Technology"), ("005930", "삼성전자"), ("005930.KS", "삼성전자"), ("mu", "Micron Technology")]


def test_api_and_daily_cache(repo, tmp_path):
    calls = []

    class Counting:
        def __getattr__(self, name):
            return getattr(repo, name)

        def constituents_at(self, index, d):
            calls.append(index)
            return repo.constituents_at(index, d)

    c = TestClient(create_analysis_app(lambda: Counting(), store_dir=tmp_path / "store", settings=AnalysisSettings(), llm=lambda: StubLlm()))
    r = c.get(f"{P}/stocks/search", params={"q": "micron"})
    assert r.status_code == 200 and r.json()[0] == {"ticker": "MU", "name_ko": "Micron Technology", "name_en": "Micron Technology", "market": "US", "sector_ko": "정보기술"}
    assert c.get(f"{P}/stocks/search").json() == []
    assert [s["ticker"] for s in c.get(f"{P}/stocks", params={"tickers": "MU,005930.KS,NOPE"}).json()] == ["MU", "005930.KS"]
    assert c.get(f"{P}/stocks").json() == []
    for bad in (0, 21):
        r = c.get(f"{P}/stocks/search", params={"q": "a", "limit": bad})
        assert r.status_code == 422 and r.json()["error"]["code"] == "VALIDATION_ERROR"
    assert len(calls) == 3  # 유니버스 셋을 처음 한 번만 읽고, 같은 날 다시 묻지 않는다


def test_condition_rows_show_company_names(stocks):
    """조건 표(이번 분석에서 달라진 조건·전체 투자 조건)의 제외·필수 포함 종목을 「회사명 (티커)」로 (이슈 #14 의 8번)."""
    from backend.analysis.m1_request.assemble import build
    from backend.analysis.m1_request.conditions import condition_rows
    from backend.tests.analysis.test_dialog import PROFILE_FIELDS

    def with_tickers(must, exc):
        prof = {**PROFILE_FIELDS, "constraints": {**PROFILE_FIELDS["constraints"], "must_include_tickers": must, "exclude_tickers": exc}}
        return build(prof, "반도체 기업에 나눠 투자하고 싶다", request_id="req_x", created_at="2026-11-10T00:00:00+09:00")

    base, req = with_tickers(["MU"], []), with_tickers(["MU", "005930.KS", "ZZZ"], ["TSLA"])
    label = lambda t: f"{h[0]['name_ko']} ({t})" if (h := lookup(stocks, [t])) else t  # noqa: E731
    rows = {r.field: r for r in condition_rows(req, base, stock_label=label)}
    must = rows["constraints.must_include_tickers"]
    assert must.value_ko == "Micron Technology (MU), 삼성전자 (005930.KS), ZZZ" and must.profile_value_ko == "Micron Technology (MU)"  # 목록에 없는 티커는 그대로
    assert rows["constraints.exclude_tickers"].value_ko == "TSLA" and rows["constraints.exclude_tickers"].profile_value_ko == "없음"
    assert {r.field: r for r in condition_rows(req, base)}["constraints.must_include_tickers"].value_ko == "MU, 005930.KS, ZZZ"  # 이름 함수가 없으면 지금처럼


def test_services_stock_label_falls_back_to_ticker(repo, tmp_path):
    from backend.analysis.api.services import Services
    from backend.analysis.common.store import JsonStore

    sv = Services(repo_factory=lambda: repo, store=JsonStore(tmp_path), settings=AnalysisSettings())
    assert sv.stock_label("MU") == "Micron Technology (MU)" and sv.stock_label("005930") == "삼성전자 (005930)" and sv.stock_label("NOPE") == "NOPE"

    class NoConstituents:
        def constituents_at(self, *_a):
            raise RuntimeError("db down")

    broken = Services(repo_factory=lambda: NoConstituents(), store=JsonStore(tmp_path), settings=AnalysisSettings())
    assert broken.stock_label("MU") == "MU"  # 목록을 못 읽어도 조건 표는 티커로 보인다
