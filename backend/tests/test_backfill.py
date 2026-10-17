"""긴 백필 (jobs/backfill.py·collectors/*/backfill.py, 뉴스 크롤러 쪽 넘기기, backend/scripts/coverage_report.py).

네트워크 없이: 크롤러는 StubSession, 백필은 스텁 어댑터와 DB(인메모리 SQLite, MYFINSIGHT_TEST_PG_URL
이 있으면 PostgreSQL 도)로 돈다.
"""

from __future__ import annotations

import importlib.util
import os
from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from typing import Any

import pytest
from helpers import AT, news_row
from sqlalchemy import create_engine, func, select
from stub_http import StubResponse, StubSession

from backend.adapters.crawlers import alpaca_news_client, google_news_rss_client, naver_news_client
from backend.adapters.crawlers.google_news_rss_client import RateLimited
from backend.collectors.common import Forever, JobSettings, ensure_assets
from backend.collectors.financials.supplements import split_step
from backend.collectors.news.backfill import (
    alpaca_news_backfill,
    month_windows,
    naver_backfill,
    newsapi_backfill,
    rss_backfill,
    rss_target,
)
from backend.collectors.news.update import prune_old_news
from backend.db import SqlRepository, open_repository
from backend.db import tables as T
from backend.jobs.backfill import BackfillOptions, run_backfill
from backend.schemas.market_ext import NewsRow

TODAY = date(2026, 10, 10)
PG_URL = os.environ.get("MYFINSIGHT_TEST_PG_URL", "")
KR = {"005930.KS": "삼성전자", "000660.KS": "SK하이닉스"}
US = {"AAPL": "Apple", "MSFT": "Microsoft"}


@pytest.fixture(
    params=[
        "sqlite",
        pytest.param(
            "postgresql", marks=pytest.mark.skipif(not PG_URL, reason="MYFINSIGHT_TEST_PG_URL 없음")
        ),
    ]
)
def repo(request: pytest.FixtureRequest) -> SqlRepository:
    if request.param == "sqlite":
        return open_repository("sqlite://", clock=lambda: AT)
    engine = create_engine(PG_URL)
    T.metadata.drop_all(engine)
    engine.dispose()
    r = open_repository(PG_URL, clock=lambda: AT)
    request.addfinalizer(r.engine.dispose)
    return r


def _settings(tickers: dict[str, str]) -> JobSettings:
    return JobSettings(indices=[], benchmarks=[], extra_tickers=dict(tickers), backfill_years=1)


class After:
    """n 번 물어본 뒤부터 시간 끝 (Deadline 과 같은 모양)."""

    def __init__(self, n: int) -> None:
        self.left = n

    def over(self) -> bool:
        self.left -= 1
        return self.left < 0


def _rows(key: str, n: int = 2) -> list[dict]:
    base = datetime(2026, 9, 1, tzinfo=UTC)
    seed = abs(hash(key)) % 10**6
    return [news_row(seed * 10 + i, (base + timedelta(hours=i)).isoformat()) for i in range(n)]


class StubRss:
    def __init__(self, fail_at: int | None = None) -> None:
        self.calls: list[tuple[str, date, date, float]] = []
        self.fail_at = fail_at

    def fetch_window(self, query: str, after: date, before: date, *, interval: float = 1.5):  # noqa: ANN201
        self.calls.append((query, after, before, interval))
        if self.fail_at is not None and len(self.calls) >= self.fail_at:
            raise RateLimited("status=429")
        return _rows(f"{query}{after}")


class StubAlpaca:
    def __init__(self) -> None:
        self.calls: list[tuple[str, date, date]] = []

    def fetch_range(self, symbol: str, start: date, end: date) -> list[dict]:
        self.calls.append((symbol, start, end))
        return _rows(f"{symbol}{start}")


class StubAll:
    def __init__(self) -> None:
        self.calls: list[str] = []

    def fetch_all(self, query: str) -> list[dict]:
        self.calls.append(query)
        return _rows(query, 3)

    fetch_max = fetch_all


# ---------------------------------------------------------------- 달 구간
def test_month_windows_recent_first_and_year_wrap() -> None:
    w = month_windows(date(2026, 1, 15), 1)
    assert len(w) == 13
    assert w[0] == (date(2026, 1, 1), date(2026, 2, 1))
    assert w[1] == (date(2025, 12, 1), date(2026, 1, 1))
    assert w[-1] == (date(2025, 1, 1), date(2025, 2, 1))
    assert len(month_windows(TODAY, 10)) == 121


def test_rss_target_fits_fetch_log() -> None:
    long = "가" * 200
    t = rss_target("GOOGLE_RSS_KR", long, date(2018, 3, 1))
    assert len(t) <= 100 and t.endswith(":2018-03")
    assert t != rss_target("GOOGLE_RSS_KR", long + "x", date(2018, 3, 1))


# ---------------------------------------------------------------- RSS 크롤러
RSS = (
    b"<rss><channel><item><title>Samsung up - Paper</title><link>https://x.example/1</link>"
    b"<source>Paper</source><pubDate>Thu, 01 Mar 2018 09:00:00 GMT</pubDate></item>"
    b"</channel></rss>"
)


def test_rss_window_query_and_backoff(monkeypatch: pytest.MonkeyPatch) -> None:
    replies = [StubResponse(429), StubResponse(503), StubResponse(200, content=RSS)]
    stub = StubSession(lambda u, k: replies.pop(0))
    slept: list[float] = []
    monkeypatch.setattr(google_news_rss_client, "_session", stub)
    monkeypatch.setattr(google_news_rss_client.time, "sleep", slept.append)
    rows = google_news_rss_client.window_rows(
        "삼성전자", date(2018, 3, 1), date(2018, 4, 1), interval=0.0, waits=(7.0, 9.0)
    )
    assert [r["title"] for r in rows] == ["Samsung up"]
    params = stub.calls[0][2]["params"]
    assert params["q"] == "삼성전자 after:2018-03-01 before:2018-04-01"
    assert params["ceid"] == "KR:ko" and len(stub.calls) == 3
    assert slept == [7.0, 9.0]  # 429·503 마다 점점 길게 쉼


def test_rss_gives_up_with_rate_limited(monkeypatch: pytest.MonkeyPatch) -> None:
    stub = StubSession(lambda u, k: StubResponse(429))
    monkeypatch.setattr(google_news_rss_client, "_session", stub)
    monkeypatch.setattr(google_news_rss_client.time, "sleep", lambda s: None)
    with pytest.raises(RateLimited):
        google_news_rss_client.window_rows(
            "AAPL", date(2020, 1, 1), date(2020, 2, 1), "en", "US", interval=0.0, waits=(1.0,)
        )
    assert len(stub.calls) == 2


def test_rss_keeps_interval_between_calls(monkeypatch: pytest.MonkeyPatch) -> None:
    stub = StubSession(lambda u, k: StubResponse(200, content=RSS))
    slept: list[float] = []
    monkeypatch.setattr(google_news_rss_client, "_session", stub)
    monkeypatch.setattr(google_news_rss_client.time, "sleep", slept.append)
    for m in (1, 2):
        google_news_rss_client.window_rows(
            "A", date(2020, m, 1), date(2020, m + 1, 1), interval=1.5
        )
    assert slept and 0 < slept[-1] <= 1.5


# ---------------------------------------------------------------- 네이버 쪽 넘기기
def _naver(monkeypatch: pytest.MonkeyPatch, sizes: list[int]) -> StubSession:
    monkeypatch.setenv("NAVER_CLIENT_ID", "cid")
    monkeypatch.setenv("NAVER_CLIENT_SECRET", "sec")
    it = iter(sizes)

    def handler(url: str, kw: dict[str, Any]) -> StubResponse:
        n, start = next(it), kw["params"]["start"]
        items = [
            {"title": f"t{start + i}", "originallink": f"https://n.example/{start + i}",
             "pubDate": "Mon, 01 Sep 2025 09:00:00 +0900"}
            for i in range(n)
        ]  # fmt: skip
        return StubResponse(200, {"items": items})

    stub = StubSession(handler)
    monkeypatch.setattr(naver_news_client, "_session", stub)
    return stub


def test_naver_pages_up_to_api_limit(monkeypatch: pytest.MonkeyPatch) -> None:
    stub = _naver(monkeypatch, [100] * 20)
    rows = naver_news_client.news_rows_all("삼성전자")
    starts = [c[2]["params"]["start"] for c in stub.calls]
    assert starts == list(range(1, 1000, 100)) and max(starts) <= 1000
    assert {c[2]["params"]["display"] for c in stub.calls} == {100}
    assert {c[2]["params"]["sort"] for c in stub.calls} == {"date"}
    assert len(rows) == 1000


def test_naver_stops_on_short_page(monkeypatch: pytest.MonkeyPatch) -> None:
    stub = _naver(monkeypatch, [100, 100, 37])
    assert len(naver_news_client.news_rows_all("SK하이닉스")) == 237
    assert len(stub.calls) == 3


# ---------------------------------------------------------------- Alpaca News 쪽 넘기기
def test_alpaca_news_follows_page_token(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("ALPACA_API_KEY_ID", "id")
    monkeypatch.setenv("ALPACA_API_SECRET_KEY", "secret")
    pages = {
        None: ({"id": 1, "headline": "A1", "url": "https://b.example/1", "source": "benzinga",
                "created_at": "2018-05-01T13:00:00Z", "summary": "<p>s</p>"}, "tok1"),
        "tok1": ({"id": 2, "headline": "A2", "url": "https://b.example/2",
                  "created_at": "2018-04-01T13:00:00-04:00"}, "tok2"),
        "tok2": ({"id": 3, "headline": "", "url": "https://b.example/3"}, None),
    }  # fmt: skip

    def handler(url: str, kw: dict[str, Any]) -> StubResponse:
        item, nxt = pages[kw["params"].get("page_token")]
        return StubResponse(200, {"news": [item], "next_page_token": nxt})

    stub = StubSession(handler)
    monkeypatch.setattr(alpaca_news_client, "_session", stub)
    monkeypatch.setattr(alpaca_news_client.time, "sleep", lambda s: None)
    rows = alpaca_news_client.news_rows("BRK-B", date(2018, 1, 1), date(2019, 1, 1))
    assert [r["title"] for r in rows] == ["A1", "A2"]  # 제목 없는 기사는 뺌
    assert rows[1]["published_at"] == "2018-04-01T17:00:00Z" and rows[0]["description"] == "s"
    p0 = stub.calls[0][2]["params"]
    assert p0["symbols"] == "BRK.B" and p0["limit"] == 50 and "page_token" not in p0
    assert [c[2]["params"].get("page_token") for c in stub.calls] == [None, "tok1", "tok2"]
    assert stub.calls[0][2]["headers"]["APCA-API-KEY-ID"] == "id"
    capped = alpaca_news_client.news_rows("AAPL", date(2018, 1, 1), date(2019, 1, 1), max_pages=1)
    assert len(capped) == 1


# ---------------------------------------------------------------- 뉴스 보관
@pytest.mark.parametrize("keep", [0, -1])
def test_news_keep_days_zero_or_less_keeps_everything(repo: SqlRepository, keep: int) -> None:
    ensure_assets(repo, {"005930.KS": "삼성전자"})
    old = NewsRow(
        asset_id="KR-005930",
        source="NAVER_NEWS",
        url="https://n.example/old",
        title="옛 기사",
        published_at=datetime(2012, 1, 1, tzinfo=UTC),
        fetched_at=AT,
    )
    repo.upsert_news([old])
    s = _settings(KR)
    s.news_keep_days = keep
    assert prune_old_news(repo, s, AT) == 0
    assert len(repo.get_news("KR-005930", datetime(2000, 1, 1, tzinfo=UTC), AT)) == 1
    s.news_keep_days = 4000
    assert prune_old_news(repo, s, AT) == 1


def test_default_keep_days_is_long() -> None:
    assert JobSettings().news_keep_days == 4000


# ---------------------------------------------------------------- RSS 백필 (이어 받기)
def _news_count(repo: SqlRepository, source: str | None = None) -> int:
    q = select(func.count()).select_from(T.news)
    if source:
        q = q.where(T.news.c.source == source)
    with repo.engine.connect() as c:
        return c.execute(q).scalar_one()


def test_rss_backfill_resumes_month_by_month(repo: SqlRepository) -> None:
    s = _settings(KR)
    ad = StubRss()
    kw = {"adapters": {"GOOGLE_RSS_KR": ad}, "today": TODAY, "years": 1, "flush_every": 3}
    r1 = rss_backfill(repo, s, deadline=After(5), interval=0.25, **kw)
    assert not r1.done and r1.counts["GOOGLE_RSS_KR_requests"] == 5
    # 최근 달을 모든 종목에 대해 먼저, 그다음 전 달
    assert [(q, a) for q, a, _, _ in ad.calls[:3]] == [
        ("삼성전자", date(2026, 10, 1)), ("SK하이닉스", date(2026, 10, 1)),
        ("삼성전자", date(2026, 9, 1)),
    ]  # fmt: skip
    assert {c[3] for c in ad.calls} == {0.25}
    done = repo.fetch_targets_done("GOOGLE_RSS", "rss_backfill:")
    assert len(done) == 5  # 멈출 때 남은 기록도 저장됨
    assert "rss_backfill:GOOGLE_RSS_KR:삼성전자:2026-10" in done
    assert _news_count(repo, "GOOGLE_RSS") == 10

    r2 = rss_backfill(repo, s, deadline=Forever(), **kw)
    assert r2.done and r2.counts["GOOGLE_RSS_KR_requests"] == 26 - 5
    asked = [(q, a) for q, a, _, _ in ad.calls]
    assert len(asked) == len(set(asked)) == 26  # 같은 달을 두 번 받지 않음
    r3 = rss_backfill(repo, s, deadline=Forever(), **kw)
    assert r3.done and r3.counts["GOOGLE_RSS_KR_requests"] == 0


def test_rss_backfill_stops_lane_when_blocked(repo: SqlRepository) -> None:
    s = _settings(KR)
    ad = StubRss(fail_at=3)
    r = rss_backfill(repo, s, adapters={"GOOGLE_RSS_KR": ad}, today=TODAY, years=1,
                        deadline=Forever())  # fmt: skip
    assert not r.done and len(ad.calls) == 3 and "막음" in r.notes[0]
    assert len(repo.fetch_targets_done("GOOGLE_RSS", "rss_backfill:")) == 2  # 막힌 달은 기록 안 함


def test_rss_backfill_failure_recorded_and_retried(repo: SqlRepository) -> None:
    s = _settings(KR)

    class Flaky(StubRss):
        def fetch_window(self, query, after, before, *, interval=1.5):  # noqa: ANN001, ANN201
            if query == "SK하이닉스" and after == date(2026, 10, 1) and not self.calls:
                self.calls.append((query, after, before, interval))
                raise ValueError("bad xml")
            return super().fetch_window(query, after, before, interval=interval)

    ad = Flaky()
    kw = {"adapters": {"GOOGLE_RSS_KR": ad}, "today": TODAY, "years": 0}
    s.extra_tickers = {"000660.KS": "SK하이닉스"}
    r = rss_backfill(repo, s, deadline=Forever(), **kw)
    assert r.failed and r.done
    assert repo.fetch_targets_done("GOOGLE_RSS", "rss_backfill:") == set()
    again = rss_backfill(repo, s, deadline=Forever(), **kw)
    assert again.counts["GOOGLE_RSS_KR_requests"] == 1 and not again.failed


# ---------------------------------------------------------------- 다른 뉴스 줄
def test_naver_backfill_once_per_day(repo: SqlRepository) -> None:
    s = _settings(KR)
    ad = StubAll()
    r = naver_backfill(repo, s, adapter=ad, today=TODAY, deadline=Forever())
    assert r.counts["NAVER_NEWS_requests"] == 2 and _news_count(repo, "NAVER_NEWS") == 6
    naver_backfill(repo, s, adapter=ad, today=TODAY, deadline=Forever())
    assert len(ad.calls) == 2  # 같은 날 다시 안 받음
    naver_backfill(repo, s, adapter=ad, today=TODAY + timedelta(days=1), deadline=Forever())
    assert len(ad.calls) == 4


def test_newsapi_backfill_respects_daily_budget(repo: SqlRepository) -> None:
    s = _settings({**US, "NVDA": "NVIDIA", "AMZN": "Amazon"})
    ad = StubAll()
    r = newsapi_backfill(repo, s, adapter=ad, today=TODAY, deadline=Forever(), daily_max=7)
    assert r.counts["NEWSAPI_quota_left"] == 2 and len(ad.calls) == 2 and not r.done
    r2 = newsapi_backfill(repo, s, adapter=ad, today=TODAY, deadline=Forever(), daily_max=7)
    assert r2.counts["NEWSAPI_quota_left"] == 0 and len(ad.calls) == 2  # 오늘 쓴 만큼 빠짐
    newsapi_backfill(repo, s, adapter=ad, today=TODAY + timedelta(days=1),
                        deadline=Forever(), daily_max=7)  # fmt: skip
    assert len(set(ad.calls)) == 4  # 다음 날은 아직 안 받은 종목부터


def test_alpaca_backfill_skips_finished_years_but_refreshes_this_year(
    repo: SqlRepository,
) -> None:
    s = _settings(US)
    ad = StubAlpaca()
    kw = {"adapter": ad, "today": TODAY, "years": 2, "deadline": Forever()}
    r = alpaca_news_backfill(repo, s, **kw)
    assert r.done and r.counts["ALPACA_NEWS_requests"] == 6
    assert ad.calls[0] == ("AAPL", date(2026, 1, 1), TODAY + timedelta(days=1))
    assert ad.calls[-1] == ("MSFT", date(2024, 1, 1), date(2025, 1, 1))
    alpaca_news_backfill(repo, s, **kw)
    assert [c[1].year for c in ad.calls[6:]] == [2026, 2026]


# ---------------------------------------------------------------- 전체 실행 + 시간 제한
def test_run_backfill_stops_cleanly_and_continues(repo: SqlRepository) -> None:
    s = _settings({**KR, **US})
    news = {"NAVER_NEWS": StubAll(), "ALPACA_NEWS": StubAlpaca(), "GOOGLE_RSS_KR": StubRss(),
            "GOOGLE_RSS_US": StubRss()}  # fmt: skip
    opts = BackfillOptions(what=("news",), years=1, flush_every=50)
    said: list[str] = []
    rep = run_backfill(repo, s, opts, adapters={"news": news}, today=TODAY,
                          deadline=After(9), progress=said.append)  # fmt: skip
    assert rep.stopped
    names = [r.name for r in rep.results]
    assert names[0] == "news_backfill:NAVER_NEWS"
    first_stored = _news_count(repo)
    assert first_stored > 0  # 멈춰도 받은 것은 저장됨 (flush_every 보다 적어도)
    assert any("뉴스 백필" in m for m in said)

    rep2 = run_backfill(repo, s, opts, adapters={"news": news}, today=TODAY)
    assert not rep2.stopped and all(r.done for r in rep2.results)
    assert news["NAVER_NEWS"].calls == ["삼성전자", "SK하이닉스"]  # 같은 날 두 번 받지 않음
    rss_kr = [(q, a) for q, a, _, _ in news["GOOGLE_RSS_KR"].calls]
    assert len(rss_kr) == len(set(rss_kr)) == 2 * 13
    assert {q for q, *_ in news["GOOGLE_RSS_US"].calls} == {"Apple", "Microsoft"}
    assert _news_count(repo) > first_stored


def test_run_backfill_lane_and_market_filters(repo: SqlRepository) -> None:
    s = _settings({**KR, **US})
    news = {"NAVER_NEWS": StubAll(), "GOOGLE_RSS_US": StubRss()}
    opts = BackfillOptions(what=("news",), years=0, markets=("US",))
    rep = run_backfill(repo, s, opts, adapters={"news": news}, today=TODAY)
    assert [r.name for r in rep.results] == ["news_backfill:GOOGLE_RSS"]
    assert news["NAVER_NEWS"].calls == []
    opts = BackfillOptions(what=("news",), years=0, news_lanes=["naver_news"])
    rep = run_backfill(repo, s, opts, adapters={"news": news}, today=TODAY)
    assert [r.name for r in rep.results] == ["news_backfill:NAVER_NEWS"]


def test_run_backfill_deadline_before_start_does_nothing(repo: SqlRepository) -> None:
    s = _settings(KR)
    news = {"NAVER_NEWS": StubAll()}
    rep = run_backfill(repo, s, BackfillOptions(), adapters={"news": news}, today=TODAY,
                          deadline=After(0))  # fmt: skip
    assert rep.stopped and rep.results == [] and news["NAVER_NEWS"].calls == []


# ---------------------------------------------------------------- scripts
def _script(name: str) -> Any:
    spec = importlib.util.spec_from_file_location(
        name, Path(__file__).resolve().parents[1] / "scripts" / f"{name}.py"
    )
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_coverage_report_on_filled_db(tmp_path: Path, capsys: pytest.CaptureFixture) -> None:
    url = f"sqlite:///{tmp_path / 'c.db'}"
    repo = open_repository(url, clock=lambda: AT)
    s = _settings({**KR, **US})
    rss_backfill(repo, s, adapters={"GOOGLE_RSS_KR": StubRss(), "GOOGLE_RSS_US": StubRss()},
                    today=TODAY, years=0, deadline=Forever())  # fmt: skip
    repo.engine.dispose()
    before = (tmp_path / "c.db").read_bytes()
    assert _script("coverage_report").main([url]) == 0
    out = capsys.readouterr().out
    assert "읽기 전용" in out and "GOOGLE_RSS" in out
    for section in ("0. 가격", "0-1. 환율", "5. 공시", "6. 재무 공시일 지연", "7. 테이블 크기"):
        assert section in out, section
    assert (tmp_path / "c.db").read_bytes() == before  # 읽기만 함


def test_coverage_report_refuses_empty_db(tmp_path: Path, capsys: pytest.CaptureFixture) -> None:
    url = f"sqlite:///{tmp_path / 'empty.db'}"
    assert _script("coverage_report").main([url]) == 1
    assert "migrate_v2" in capsys.readouterr().out


def test_split_step_saves_splits_once(repo: SqlRepository) -> None:
    s = _settings({**US, **KR})
    asked: list[str] = []

    def splits(t: str) -> list[dict]:
        asked.append(t)
        return [{"date": "2020-08-31", "ratio": 4.0}] if t == "AAPL" else []

    r = split_step(repo, s, fetch_splits=splits, today=TODAY, markets=["US"])
    assert sorted(asked) == ["AAPL", "MSFT"] and r.counts["rows"] == 1
    with repo.engine.connect() as c:
        f = T.financials
        row = c.execute(select(f.c.item, f.c.value, f.c.report_date)
                        .where(f.c.asset_id == "US-AAPL")).one()  # fmt: skip
    assert tuple(row) == ("주식분할", 4.0, date(2020, 8, 31))
    split_step(repo, s, fetch_splits=splits, today=TODAY, markets=["US"])
    assert len(asked) == 2  # FIN_REFRESH_DAYS 안에는 다시 안 받음


def test_split_step_adds_yf_shares_for_listed_tickers(repo: SqlRepository) -> None:
    """yf_shares 에 든 종목만 yfinance 유통주식수 이력도 저장 (SEC 에 주식 수 없는 회사 보충)."""
    s = _settings(US)
    s.yf_shares = ["MSFT"]
    asked: list[str] = []

    def shares(t: str) -> list[dict]:
        asked.append(t)
        return [{"date": "2026-08-29", "shares": 7.4e9}, {"date": "2026-09-30", "shares": 7.3e9}]

    split_step(repo, s, fetch_splits=lambda _t: [], today=TODAY, markets=["US"],
                    fetch_shares=shares)  # fmt: skip
    assert asked == ["MSFT"]
    with repo.engine.connect() as c:
        f = T.financials
        rows = c.execute(select(f.c.item, f.c.period_end, f.c.value, f.c.source, f.c.unit)
                         .where(f.c.asset_id == "US-MSFT")
                         .order_by(f.c.period_end)).all()  # fmt: skip
    assert [tuple(r) for r in rows] == [
        ("유통주식수", date(2026, 8, 29), 7.4e9, "YFINANCE_SHARES", "주"),
        ("유통주식수", date(2026, 9, 30), 7.3e9, "YFINANCE_SHARES", "주"),
    ]


def test_backfill_script_valuation_only(tmp_path: Path, capsys: pytest.CaptureFixture) -> None:
    url = f"sqlite:///{tmp_path / 'b.db'}"
    open_repository(url, clock=lambda: AT).engine.dispose()
    mod = _script("backfill")
    assert mod.main(["--what", "valuation", "--db", url, "--max-minutes", "5"]) == 0
    out = capsys.readouterr().out
    assert "valuation_daily" in out and "끝" in out
    with pytest.raises(SystemExit):
        mod.main(["--what", "everything", "--db", url])


def test_run_backfill_gics_step(repo: SqlRepository) -> None:
    """--what gics: kr_gics.csv·KSIC·사업 설명으로 종목별 GICS (스텁 함수, 네트워크 없음)."""
    s = _settings({**KR, **US, "123450.KS": "표에 없는 종목", "ZZZZ": "Unknown"})
    calls: list[str] = []

    def ksic(code: str) -> str | None:
        calls.append(code)
        return {"123450": "21102"}.get(code)

    def profile(sym: str) -> dict:
        return {"summary": f"{sym} 설명.", "sector": "Technology", "source": "YFINANCE"}

    opts = BackfillOptions(what=("gics",))
    rep = run_backfill(repo, s, opts, adapters={"gics": {"ksic": ksic, "profile": profile}},
                          today=TODAY)  # fmt: skip
    assert [r.name for r in rep.results] == ["gics"]
    p = {x["yfinance_symbol"]: x for x in repo.asset_profiles()}
    assert (p["005930.KS"]["gics_sub_industry_code"], p["005930.KS"]["gics_source"]) == (
        "45202030",
        "KR_MAP_REVIEWED",
    )
    assert (p["123450.KS"]["gics_sub_industry_code"], p["123450.KS"]["gics_source"]) == (
        "35201010",
        "KR_MAP_KSIC_AUTO",
    )
    assert p["AAPL"]["gics_source"] == "OVERRIDE"  # 구성종목이 없으면 gics_overrides.csv
    # 구성종목도 overrides 도 없는 미국 종목: Yahoo 섹터만
    assert (p["ZZZZ"]["gics_sector_code"], p["ZZZZ"]["gics_source"]) == ("45", "YAHOO_FALLBACK")
    assert p["MSFT"]["business_summary"] == "MSFT 설명."
    assert sorted(calls) == ["000660", "005930", "123450"]


def test_backfill_script_gics_without_keys(tmp_path: Path, capsys: pytest.CaptureFixture) -> None:
    url = f"sqlite:///{tmp_path / 'g.db'}"
    open_repository(url, clock=lambda: AT).engine.dispose()
    mod = _script("backfill")
    assert mod.main(["--what", "gics", "--no-profiles", "--db", url, "--max-minutes", "5"]) == 0
    out = capsys.readouterr().out
    assert "GICS 분류" in out and "DART_API_KEY" in out


# ---------------------------------------------------------------- FNSPID
def test_fnspid_load_filters_and_resumes(repo: SqlRepository, tmp_path: Path) -> None:
    from backend.collectors.news.fnspid import fnspid_load

    head = "Date,Article_title,Stock_symbol,Url,Publisher,Author,Article,Lsa_summary\n"
    lines = [
        '2020-06-05 06:30:54 UTC,Apple beats,AAPL,https://x/1,Benzinga,,"long\nbody",\n',
        "2021-01-02 00:00:00 UTC,Berkshire,BRK.B,https://x/2,Reuters,,,\n",
        "2019-03-01 10:00:00 UTC,Not ours,ZZZZ,https://x/3,Reuters,,,\n",
        "2010-03-01 10:00:00 UTC,Old Apple,AAPL,https://x/4,Reuters,,,\n",
        "bad date,No time,AAPL,https://x/5,Reuters,,,\n",
    ]
    path = tmp_path / "All_external.csv"
    path.write_text(head + "".join(lines), encoding="utf-8")
    s = _settings({"AAPL": "Apple", "BRK-B": "Berkshire"})
    r = fnspid_load(repo, s, path=path, deadline=After(1), chunk=2)
    assert not r.done and r.counts["chunks"] == 1 and r.counts["stored"] == 2
    r2 = fnspid_load(repo, s, path=path, deadline=Forever(), chunk=2, since=date(2015, 1, 1))
    assert r2.done and r2.counts["chunks"] == 2  # 첫 덩어리는 건너뜀
    assert _news_count(repo, "FNSPID") == 2  # 2010 기사는 since 로, 날짜 없는 행·남의 종목은 뺌
    r3 = fnspid_load(repo, s, path=path, deadline=Forever(), chunk=2, until=date(2016, 1, 1),
                     name="again.csv")
    assert r3.counts["matched"] == 1 and r3.counts["stored"] == 1  # 2010 기사만 (until 전)
