"""서버 수집 작업 (collectors/·jobs/daily.py): 나눠서 이어 받기, 증분, 실패 제외, 재무·뉴스, 뉴스 상한·삭제.

스텁 어댑터와 DB(인메모리 SQLite, MYFINSIGHT_TEST_PG_URL 이 있으면 PostgreSQL 도)로 돈다.
"""

from __future__ import annotations

import os
import threading
from datetime import UTC, date, datetime, timedelta

import pytest
from helpers import (
    AT,
    StubConstituentSource,
    StubKeyedAdapter,
    StubPriceAdapter,
    fin_row,
    make_constituents,
    news_row,
)
from sqlalchemy import create_engine, func, select

from backend.collectors.common import (
    MAX_FAILURES,
    Deadline,
    JobSettings,
    ensure_assets,
    sync_asset_types,
    universe,
)
from backend.collectors.constituents.update import refresh_constituents
from backend.collectors.financials.update import financial_step, financial_targets
from backend.collectors.news.update import news_step
from backend.collectors.prices.update import closed_through, price_step, store_prices
from backend.db import SqlRepository, open_repository
from backend.db import tables as T
from backend.schemas.market import IndexCode
from backend.schemas.market_ext import NewsRow

TODAY = date(2026, 10, 1)
PG_URL = os.environ.get("MYFINSIGHT_TEST_PG_URL", "")


@pytest.fixture(
    params=[
        "sqlite",
        pytest.param(
            "postgresql",
            marks=pytest.mark.skipif(not PG_URL, reason="MYFINSIGHT_TEST_PG_URL 없음"),
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


def _settings(**kw: object) -> JobSettings:
    s = JobSettings(indices=[IndexCode.SP500], benchmarks=["SPY"], backfill_years=1)
    for k, v in kw.items():
        setattr(s, k, v)
    return s


def _seed(repo: SqlRepository, n: int = 12) -> None:
    repo.save_constituents(make_constituents(IndexCode.SP500, n))


# ---------------------------------------------------------------- 종목 종류
def test_etfs_marked_and_existing_stock_rows_fixed(repo: SqlRepository) -> None:
    _seed(repo, 3)
    ensure_assets(repo, {"SPY": None})  # 예전 실행처럼 STOCK 으로 먼저 저장된 상태
    assert repo.get_assets(["SPY"])[0].asset_type == "STOCK"
    s = _settings(etf_tickers=["069500.KS"])
    res = price_step(repo, s, adapters=_yf(), today=TODAY)
    kinds = {a.yfinance_symbol: a.asset_type for a in repo.get_assets()}
    assert kinds["SPY"] == "ETF" and kinds["069500.KS"] == "ETF"
    assert {kinds[r.ticker] for r in make_constituents(IndexCode.SP500, 3)} == {"STOCK"}
    assert res.counts["etf_marked"] == 2
    assert sync_asset_types(repo, s) == 0  # 다시 돌리면 바꿀 것 없음
    assert "069500" not in financial_targets(universe(repo, s), s.etfs)["DART"]


# ---------------------------------------------------------------- 구성종목 행 수 검사
@pytest.mark.parametrize(
    ("index", "bad", "good"),
    [(IndexCode.SP500, 494, 510), (IndexCode.NDX, 106, 98), (IndexCode.KOSPI200, 194, 205)],
)
def test_constituent_count_out_of_range_not_saved(
    repo: SqlRepository, index: IndexCode, bad: int, good: int
) -> None:
    """계약 M2-01 범위(SP500 495~510, NDX 98~105, KOSPI200 195~205) 밖이면 저장하지 않고 FAILED."""
    s = _settings(indices=[index])
    r = refresh_constituents(repo, s, source=StubConstituentSource({index: bad}), today=TODAY)
    assert index.value in r.failed and repo.latest_constituents(index) == []
    log = repo.fetch_history(f"constituents:{index.value}")
    assert log[-1]["status"] == "FAILED" and f"행 수 {bad}" in log[-1]["error"]
    ok = refresh_constituents(
        repo, s, source=StubConstituentSource({index: good}), today=TODAY
    )
    assert ok.counts["REFRESHED"] == 1 and len(repo.latest_constituents(index)) == good
    assert repo.fetch_history(f"constituents:{index.value}")[-1]["status"] == "SUCCESS"


# ---------------------------------------------------------------- 가격
def _yf(**kw: object) -> dict[str, StubPriceAdapter]:
    return {"YFINANCE": StubPriceAdapter(source="YFINANCE", **kw)}


def test_backfill_runs_in_parts_until_done(repo: SqlRepository) -> None:
    _seed(repo)  # 12종목 + SPY = 13
    s = _settings()
    ads = _yf()
    r1 = price_step(repo, s, adapters=ads, today=TODAY, limit=5, chunk=5)
    assert (r1.done, r1.counts["YFINANCE_tickers"], r1.counts["YFINANCE_pending"]) == (
        False,
        5,
        13,
    )
    r2 = price_step(repo, s, adapters=ads, today=TODAY, limit=5, chunk=5)
    assert (r2.done, r2.counts["YFINANCE_pending"]) == (False, 8)
    r3 = price_step(repo, s, adapters=ads, today=TODAY, limit=5, chunk=5)
    assert (r3.done, r3.counts["YFINANCE_pending"]) == (True, 3)
    r4 = price_step(repo, s, adapters=ads, today=TODAY, limit=5, chunk=5)
    assert r4.done and r4.counts["YFINANCE_tickers"] == 0
    start = date(2025, 9, 30)
    ranges = repo.covered_ranges(["SPY", "T0001", "T0012"])
    assert all(lo <= start + timedelta(days=4) for lo, _ in ranges.values())
    assert repo.get_fx_on_or_before(TODAY) is not None  # 환율도 같이 받음


def test_increment_fetches_only_recent_window(repo: SqlRepository) -> None:
    _seed(repo, 3)
    s = _settings()
    price_step(repo, s, adapters=_yf(), today=TODAY, limit=50)
    week_later = TODAY + timedelta(days=7)
    ads = _yf()
    r = price_step(repo, s, adapters=ads, today=week_later, limit=50)
    assert r.counts["YFINANCE_pending"] == 4
    assert r.done and r.counts["YFINANCE_rows"] > 0 and r.counts["fx_rows"] > 0
    hist = [h for h in repo.fetch_history("T0001") if h["start_date"] > date(2026, 9, 1)]
    assert hist and hist[-1]["start_date"] == week_later - timedelta(days=11)
    again = price_step(repo, s, adapters=ads, today=week_later, limit=50)
    assert again.counts["YFINANCE_pending"] == 0 and again.counts["YFINANCE_tickers"] == 0


def test_longer_backfill_extends_in_one_run(repo: SqlRepository) -> None:
    _seed(repo, 2)
    ads = _yf()
    price_step(repo, _settings(backfill_years=1), adapters=ads, today=TODAY, limit=50)
    week_later = TODAY + timedelta(days=7)
    s = _settings(backfill_years=2)  # 기간을 늘림: 증분 날이어도 한 번에 앞부분까지 받음
    r = price_step(repo, s, adapters=ads, today=week_later, limit=50)
    assert r.done and r.counts["YFINANCE_pending"] == 3  # 2종목 + SPY
    lo, hi = repo.covered_ranges(["T0001"], source="YFINANCE")["T0001"]
    assert lo <= week_later - timedelta(days=2 * 365) + timedelta(days=7)
    assert hi >= week_later - timedelta(days=3)
    assert r.counts["fx_rows"] > 0  # 환율도 늘어난 기간 앞부분까지
    assert repo.get_fx_on_or_before(week_later - timedelta(days=2 * 365) + timedelta(days=7))
    again = price_step(repo, s, adapters=ads, today=week_later, limit=50)
    assert again.counts["YFINANCE_pending"] == 0 and again.counts["fx_rows"] == 0


def test_failing_ticker_dropped_after_max_failures(repo: SqlRepository) -> None:
    _seed(repo, 2)
    s = _settings()
    ads = _yf(fail_plan={"T0001": -1}, retry_max=0)
    for _ in range(MAX_FAILURES):
        r = price_step(repo, s, adapters=ads, today=TODAY, limit=50)
        assert "YFINANCE:T0001" in r.failed
    r = price_step(repo, s, adapters=ads, today=TODAY, limit=50)
    assert r.counts["YFINANCE_pending"] == 0 and r.done


def test_late_listed_ticker_not_refetched(repo: SqlRepository) -> None:
    _seed(repo, 2)
    s = _settings()
    early = [date(2025, 9, 30) + timedelta(days=i) for i in range(120)]
    ads = _yf(missing={"T0002": early})  # 처음 넉 달 데이터 없음 (늦은 상장)
    price_step(repo, s, adapters=ads, today=TODAY, limit=50)
    assert repo.tickers_needing_fetch(["T0002"], date(2025, 9, 30), date(2026, 9, 30), today=TODAY)
    r = price_step(repo, s, adapters=ads, today=TODAY, limit=50)
    assert r.counts["YFINANCE_pending"] == 0 and r.counts["YFINANCE_tickers"] == 0


def test_deadline_stops_before_work(repo: SqlRepository) -> None:
    _seed(repo, 2)
    r = price_step(repo, _settings(), adapters=_yf(), today=TODAY, deadline=Deadline(0))
    assert not r.done and r.counts["YFINANCE_tickers"] == 0


def test_lanes_run_at_the_same_time_on_postgresql(repo: SqlRepository) -> None:
    """PostgreSQL 이면 출처마다 스레드 하나로 동시에 받음 (한 출처가 느려도 다른 출처가 진행)."""
    if repo.dialect != "postgresql":
        pytest.skip("SQLite 는 한 줄씩")
    _seed(repo)
    both = threading.Barrier(2, timeout=10)  # 두 출처가 동시에 요청 중이어야 통과

    class Together(StubPriceAdapter):
        def fetch(self, tickers, start, end):  # type: ignore[no-untyped-def]
            both.wait()
            return super().fetch(tickers, start, end)

    ads = {"ALPACA": Together(source="ALPACA"), "YFINANCE": Together()}
    r = price_step(repo, _settings(fx_symbol=None), adapters=ads, today=TODAY, chunk=5)
    assert r.done and not r.failed
    assert r.counts["ALPACA_tickers"] == r.counts["YFINANCE_tickers"] == 13


def test_holiday_not_refetched_after_success(repo: SqlRepository) -> None:
    """마지막 거래일까지 요청해 성공했는데 그 날 데이터가 없으면(휴장) 같은 날 다시 안 받음."""
    s = _settings(indices=[], benchmarks=["SPY"], fx_symbol=None)
    holiday = TODAY - timedelta(days=1)
    ad = StubPriceAdapter(missing={"SPY": [holiday]})
    price_step(repo, s, adapters={"YFINANCE": ad}, today=TODAY)
    again = price_step(repo, s, adapters={"YFINANCE": ad}, today=TODAY)
    assert again.counts["YFINANCE_pending"] == 0


def test_kr_and_us_fetched_in_separate_frames(repo: SqlRepository) -> None:
    s = _settings(indices=[], extra_tickers={"005930.KS": "삼성전자"}, benchmarks=["SPY"])
    ads = _yf()
    r = price_step(repo, s, adapters=ads, today=TODAY, limit=50)
    calls = ads["YFINANCE"].calls
    assert r.done and not r.failed
    assert {c for call in calls for c in call} >= {"005930.KS", "SPY"}
    assert not any({"005930.KS", "SPY"} <= set(call) for call in calls)


def test_every_source_collected_and_primary_preferred(repo: SqlRepository) -> None:
    """모든 출처를 받고, 고를 때는 통화별 우선순위 (미국 Alpaca, 한국 yfinance → KIS)."""
    s = _settings(indices=[], extra_tickers={"005930.KS": "삼성전자"}, benchmarks=["SPY"])
    ads = {
        "KIS": StubPriceAdapter(source="KIS"),
        "ALPACA": StubPriceAdapter(source="ALPACA"),
        "YFINANCE": StubPriceAdapter(source="YFINANCE"),
        "TIINGO": StubPriceAdapter(source="TIINGO"),
    }
    r = price_step(repo, s, adapters=ads, today=TODAY, limit=50)
    assert r.done and not r.failed
    assert ads["KIS"].calls == [("005930",)]  # KIS 는 6자리 코드로 요청
    assert ads["ALPACA"].calls == [("SPY",)]
    assert ads["TIINGO"].calls == [("SPY",)]  # 표본 줄: 최근 증분만
    assert {c for call in ads["YFINANCE"].calls for c in call} == {"005930.KS", "SPY", "KRW=X"}
    for src in ("KIS", "YFINANCE"):
        assert repo.covered_ranges(["005930.KS"], source=src)  # KIS 행도 005930.KS 로 저장
    _, meta = repo.get_prices(["SPY"], date(2026, 9, 1), date(2026, 9, 30))
    assert meta.source == "ALPACA"
    _, meta = repo.get_prices(["005930.KS"], date(2026, 9, 1), date(2026, 9, 30))
    assert meta.source == "KIS"  # 한국 종가는 KIS 먼저 (수정종가는 yfinance)
    again = price_step(repo, s, adapters=ads, today=TODAY, limit=50)
    assert again.counts["TIINGO_pending"] == 0  # 같은 날 표본은 다시 안 받음


def test_market_split_and_alpaca_only_with_fallback(repo: SqlRepository) -> None:
    """시장별 실행: KR 은 KIS·yfinance 의 한국 종목만, US 매일분은 Alpaca 만 받고 못 받은 종목만
    yfinance 로 대신 받음. 환율은 US 실행에서만."""
    s = _settings(indices=[], extra_tickers={"005930.KS": "삼성전자", "MSFT": None})
    ads = {
        "KIS": StubPriceAdapter(source="KIS"),
        "ALPACA": StubPriceAdapter(source="ALPACA", known={"SPY"}),  # MSFT 는 못 받음
        "YFINANCE": StubPriceAdapter(source="YFINANCE"),
        "TIINGO": StubPriceAdapter(source="TIINGO"),
    }
    kr = price_step(repo, s, adapters=ads, today=TODAY, limit=50, market="KR")
    assert kr.done and ads["KIS"].calls == [("005930",)]
    assert ads["YFINANCE"].calls == [("005930.KS",)] and not ads["ALPACA"].calls
    ads["YFINANCE"].calls.clear()
    us = price_step(
        repo, s, adapters=ads, today=TODAY, limit=50, market="US", lanes=["ALPACA"]
    )
    assert ads["ALPACA"].calls[0] == ("MSFT", "SPY") and not ads["TIINGO"].calls
    assert ads["YFINANCE"].calls == [("KRW=X",), ("MSFT",)]  # 환율 + Alpaca 가 못 받은 종목
    assert us.counts["YFINANCE_fallback_tickers"] == 1
    assert repo.covered_ranges(["MSFT"], source="YFINANCE")
    assert not repo.covered_ranges(["SPY"], source="YFINANCE")


def test_closed_through_uses_market_close_time() -> None:
    """장 마감 + 30분 뒤면 그 현지 날짜, 전이면 현지 전날."""
    at = lambda h, m=0: datetime(2026, 10, 16, h, m, tzinfo=UTC)  # noqa: E731
    assert closed_through("KR", at(6, 59)) == date(2026, 10, 15)  # 15:59 KST
    assert closed_through("KR", at(7, 37)) == date(2026, 10, 16)  # 16:37 KST (한국 예약 실행)
    assert closed_through("KR", at(12, 43)) == date(2026, 10, 16)  # 예약이 늦게 돌아도 그날
    assert closed_through("US", at(20, 29)) == date(2026, 10, 15)  # 16:29 EDT
    assert closed_through("US", at(22, 37)) == date(2026, 10, 16)  # 18:37 EDT (미국 예약 실행)
    assert closed_through("US", datetime(2026, 10, 17, 0, 50, tzinfo=UTC)) == date(2026, 10, 16)


def test_kr_run_after_close_gets_same_day(repo: SqlRepository) -> None:
    """한국 장 마감 뒤(16:37 KST) 실행은 그날 종가까지 받음. 마감 전이면 전날까지."""
    s = _settings(indices=[], extra_tickers={"005930.KS": "삼성전자"}, fx_symbol=None)
    ads = {"KIS": StubPriceAdapter(source="KIS"), "YFINANCE": StubPriceAdapter(source="YFINANCE")}
    price_step(repo, s, adapters=ads, today=TODAY, limit=50, market="KR")
    assert repo.covered_ranges(["005930.KS"], source="KIS")["005930.KS"][1] == date(2026, 9, 30)
    fri = date(2026, 10, 2)
    before = datetime(2026, 10, 2, 6, 0, tzinfo=UTC)  # 15:00 KST
    price_step(repo, s, adapters=ads, today=fri, limit=50, market="KR", now=before)
    assert repo.covered_ranges(["005930.KS"], source="KIS")["005930.KS"][1] == date(2026, 10, 1)
    after = datetime(2026, 10, 2, 7, 37, tzinfo=UTC)  # 16:37 KST
    r = price_step(repo, s, adapters=ads, today=fri, limit=50, market="KR", now=after)
    assert r.counts["KIS_tickers"] == 1
    for src in ("KIS", "YFINANCE"):
        assert repo.covered_ranges(["005930.KS"], source=src)["005930.KS"][1] == fri
    again = price_step(repo, s, adapters=ads, today=fri, limit=50, market="KR", now=after)
    assert again.counts["KIS_tickers"] == 0  # 이미 그날까지 있으면 다시 안 받음


def test_weekly_secondary_run_fills_the_gap(repo: SqlRepository) -> None:
    """주간 실행(yfinance·Tiingo)은 마지막 저장일부터 한 주치를 한 번에 받음."""
    s = _settings(indices=[], extra_tickers={"MSFT": None}, fx_symbol=None)
    ads = {
        "YFINANCE": StubPriceAdapter(source="YFINANCE"),
        "TIINGO": StubPriceAdapter(source="TIINGO"),
    }
    price_step(repo, s, adapters=ads, today=TODAY, limit=50, market="US")
    week = TODAY + timedelta(days=7)
    r = price_step(
        repo, s, adapters=ads, today=week, limit=50, market="US", lanes=["YFINANCE", "TIINGO"]
    )
    assert r.done and r.counts["YFINANCE_tickers"] == 2
    assert repo.covered_ranges(["MSFT"], source="YFINANCE")["MSFT"][1] >= week - timedelta(days=3)


def test_same_values_with_float_noise_not_rewritten(repo: SqlRepository) -> None:
    """다시 받은 값이 끝자리만 다르면(계산 순서 차이) 바뀐 행으로 보지 않음."""
    s = _settings(indices=[], fx_symbol=None)
    price_step(repo, s, adapters=_yf(), today=TODAY)
    days = [TODAY - timedelta(days=d) for d in range(1, 11)]
    stored, _ = repo.get_prices(["SPY"], days[-1], days[0])
    noisy = {d.date(): float(v) * (1 + 1e-12) for d, v in stored["SPY"].dropna().items()}
    ad = StubPriceAdapter(source="YFINANCE", overrides={"SPY": noisy})
    again = store_prices(repo, ad, ["SPY"], days[-1], days[0], lane="YFINANCE")
    assert again[0] == 0


def test_many_rows_saved_in_one_call(repo: SqlRepository) -> None:
    """한 번에 수천 행(PostgreSQL 은 여러 문장으로 나눠 묶음)도 빠짐없이 저장."""
    _seed(repo)
    r = price_step(repo, _settings(fx_symbol=None), adapters=_yf(), today=TODAY, chunk=50)
    with repo.engine.connect() as c:
        n = c.execute(select(func.count()).select_from(T.price_daily)).scalar()
    assert r.counts["YFINANCE_rows"] > 3000 and n == r.counts["YFINANCE_rows"]


def test_tiingo_sample_rotates(repo: SqlRepository) -> None:
    _seed(repo, 4)
    s = _settings(sample_daily={"TIINGO": 2})
    ad = StubPriceAdapter(source="TIINGO")
    price_step(repo, s, adapters={"TIINGO": ad}, today=TODAY, limit=50)
    price_step(repo, s, adapters={"TIINGO": ad}, today=TODAY + timedelta(days=1), limit=50)
    first, second = set(ad.calls[0]), set(ad.calls[1])
    assert len(first) == len(second) == 2 and not first & second


def test_tiingo_sample_daily_limit_across_runs(repo: SqlRepository) -> None:
    _seed(repo, 4)
    s = _settings(sample_daily={"TIINGO": 2})
    ad = StubPriceAdapter(source="TIINGO")  # fetched_at = AT = TODAY 0시
    price_step(repo, s, adapters={"TIINGO": ad}, today=TODAY, limit=50)
    r = price_step(repo, s, adapters={"TIINGO": ad}, today=TODAY, limit=50)
    assert r.counts["TIINGO_pending"] == 0  # 같은 날 다시 돌려도 하루 2종목을 넘지 않음


# ---------------------------------------------------------------- 재무
def _fin_rows(key: str) -> list[dict]:
    return [fin_row("2025_11011", "매출액", 1.0e12, "2026-03-10")]


def test_financials_saved_and_skipped_while_fresh(repo: SqlRepository) -> None:
    _seed(repo, 2)
    s = _settings(extra_tickers={"005930.KS": "삼성전자"})
    dart = StubKeyedAdapter("DART", _fin_rows)
    sec = StubKeyedAdapter("SEC_EDGAR", _fin_rows, fail=["T0002"])
    r = financial_step(repo, s, adapters={"DART": dart, "SEC_EDGAR": sec}, today=TODAY)
    assert dart.calls[0][0] == ["005930"]
    assert sorted(sec.calls[0][0]) == ["T0001", "T0002"]  # SPY(벤치마크) 는 빠짐
    assert r.counts["DART_rows"] == 1 and r.counts["SEC_EDGAR_rows"] == 1
    assert "SEC_EDGAR:T0002" in r.failed
    assert repo.get_financials_as_of("KR-005930", TODAY)[0].value == 1.0e12

    r2 = financial_step(repo, s, adapters={"DART": dart, "SEC_EDGAR": sec}, today=TODAY)
    assert r2.counts["DART_pending"] == 0
    assert r2.counts["SEC_EDGAR_pending"] == 1  # 실패한 종목만 다시


# ---------------------------------------------------------------- 뉴스
def _news_rows(query: str) -> list[dict]:
    base = datetime(2026, 9, 30, 0, 0, tzinfo=UTC)
    return [news_row(i, (base + timedelta(hours=i)).isoformat()) for i in range(8)]


def test_news_capped_per_day_and_old_pruned(repo: SqlRepository) -> None:
    s = _settings(
        indices=[], extra_tickers={"005930.KS": "삼성전자"}, news_per_ticker_day=5,
        news_keep_days=365,
    )  # fmt: skip
    naver = StubKeyedAdapter("NAVER_NEWS", _news_rows, kind="news")
    ensure_assets(repo, {"005930.KS": "삼성전자"})
    old = NewsRow(
        asset_id="KR-005930",
        source="NAVER_NEWS",
        url="https://news.example.com/old",
        title="옛 기사",
        published_at=datetime(2025, 1, 1, tzinfo=UTC),
        fetched_at=AT,
    )
    repo.upsert_news([old])
    r = news_step(repo, s, adapters={"NAVER_NEWS": naver}, today=TODAY, now=AT)
    assert naver.calls[0][0] == ["삼성전자"]
    assert r.counts["NAVER_NEWS_rows"] == 5 and r.counts["pruned"] == 1
    kept = repo.get_news("KR-005930", datetime(2024, 1, 1, tzinfo=UTC), AT)
    assert [n.title for n in kept] == ["기사 3", "기사 4", "기사 5", "기사 6", "기사 7"]
    again = news_step(repo, s, adapters={"NAVER_NEWS": naver}, today=TODAY, now=AT)
    assert again.counts["NAVER_NEWS_pending"] == 0  # 같은 날 다시 받지 않음


def test_news_daily_limit_rotates(repo: SqlRepository) -> None:
    _seed(repo, 4)
    s = _settings(news_daily_limits={"NEWSAPI": 3})
    api = StubKeyedAdapter("NEWSAPI", _news_rows, kind="news")
    news_step(repo, s, adapters={"NEWSAPI": api}, today=TODAY, now=AT)
    first = set(api.calls[0][0])
    assert len(first) == 3
    news_step(repo, s, adapters={"NEWSAPI": api}, today=TODAY + timedelta(days=1), now=AT)
    assert not (set(api.calls[1][0]) - set(make_q(4))) and set(api.calls[1][0]) - first


def test_news_empty_is_success_not_failure(repo: SqlRepository) -> None:
    s = _settings(indices=[], extra_tickers={"005930.KS": "삼성전자", "000660.KS": "SK하이닉스"})
    ensure_assets(repo, {"005930.KS": "삼성전자", "000660.KS": "SK하이닉스"})
    naver = StubKeyedAdapter("NAVER_NEWS", _news_rows, kind="news", empty=["SK하이닉스"])
    r = news_step(repo, s, adapters={"NAVER_NEWS": naver}, today=TODAY, now=AT)
    assert r.failed == {}  # 기사가 없는 종목은 실패가 아님
    again = news_step(repo, s, adapters={"NAVER_NEWS": naver}, today=TODAY, now=AT)
    assert again.counts["NAVER_NEWS_pending"] == 0  # 성공(0건)으로 기록돼 같은 날 다시 안 받음


def make_q(n: int) -> list[str]:
    return [r.name for r in make_constituents(IndexCode.SP500, n)]


# ---------------------------------------------------------------- 설정
def test_settings_from_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("UNIVERSE_INDICES", "sp500, ndx")
    monkeypatch.setenv("EXTRA_TICKERS", "005930.ks:삼성전자, TSLA")
    monkeypatch.setenv("BENCHMARK_TICKERS", "SPY,069500.KS")
    monkeypatch.setenv("ETF_TICKERS", "tqqq")
    monkeypatch.setenv("BACKFILL_YEARS", "3")
    monkeypatch.setenv("NEWS_DAILY_LIMITS", "newsapi=50")
    monkeypatch.setenv("PRICE_SOURCES", "alpaca,yfinance")
    monkeypatch.setenv("TIINGO_DAILY_SYMBOLS", "10")
    s = JobSettings.from_env()
    assert s.indices == [IndexCode.SP500, IndexCode.NDX]
    assert s.extra_tickers == {"005930.KS": "삼성전자", "TSLA": None}
    assert s.benchmarks == ["SPY", "069500.KS"]
    assert s.etfs == {"SPY", "069500.KS", "TQQQ"}
    assert s.backfill_years == 3
    assert s.news_daily_limits["NEWSAPI"] == 50 and s.news_daily_limits["NAVER_NEWS"] == 200
    assert s.price_lanes == ["ALPACA", "YFINANCE"] and s.sample_daily["TIINGO"] == 10


def test_resave_reads_only_same_dates_and_source(repo: SqlRepository) -> None:
    """다시 저장할 때 기존 행은 같은 날짜 범위·출처만 읽고, 발행은 바뀐 키만 (전체 이력 X)."""
    from sqlalchemy import event

    from backend.schemas.market import PriceBar

    def bars(days: range, source: str, bump: float = 0.0) -> list[PriceBar]:
        return [
            PriceBar(
                ticker="AAPL",
                date=TODAY - timedelta(days=d),
                adj_close=100 + d + bump,
                source=source,
                fetched_at=AT,
            )
            for d in days
        ]

    repo.upsert_prices(bars(range(300), "ALPACA") + bars(range(300), "YFINANCE"))
    seen: list[tuple[str, object]] = []

    def count(conn, cursor, statement, params, context, executemany):  # noqa: ANN001
        if statement.lstrip().upper().startswith("SELECT") and "price_daily" in statement:
            seen.append((statement, params))

    new = bars(range(7), "ALPACA")
    new[0] = new[0].model_copy(update={"adj_close": 999.0})
    event.listen(repo.engine, "after_cursor_execute", count)
    try:
        n = repo.upsert_prices(new)
    finally:
        event.remove(repo.engine, "after_cursor_execute", count)
    assert n == 1  # 바뀐 1행만 반영
    with repo.engine.connect() as c:  # 같은 조회를 다시 돌려 읽은 행 수 확인
        raw = c.connection.dbapi_connection
        read = {"source": 0, "published": 0}
        for statement, params in seen:
            cur = raw.cursor()
            cur.execute(statement, params)
            kind = "source" if "price_daily_source" in statement else "published"
            read[kind] += len(cur.fetchall())
    # 원본: 600행 중 같은 출처·같은 7일(비교용) + 값이 바뀐 하루의 두 출처(발행할 행 고르기)
    # 계약 price_daily: 바뀐 하루 1행만
    assert read == {"source": 7 + 2, "published": 1}


def test_fred_fills_fx_before_yfinance_starts(repo: SqlRepository) -> None:
    """FRED 환율은 출처별로 따로 저장되고, yfinance 값이 없는 날만 fx_daily 에 실린다."""
    from backend.adapters.crawlers import fred_client
    from backend.schemas.market import FxRate

    _seed(repo, 1)
    calls: list[tuple[date, date]] = []

    def fred(start: date, end: date) -> list[FxRate]:
        calls.append((start, end))
        at = datetime(2026, 10, 1, tzinfo=UTC)
        return [FxRate(date=start - timedelta(days=30), rate=1111.0, source="FRED", fetched_at=at),
                FxRate(date=end, rate=1999.0, source="FRED", fetched_at=at)]  # fmt: skip

    r = price_step(repo, _settings(), adapters=_yf(), today=TODAY, limit=50, fred=fred)
    assert len(calls) == 1 and r.counts["fx_fred_rows"] == 2
    start, end = calls[0]
    assert repo.get_fx_on_or_before(start - timedelta(days=30)).rate == 1111.0  # yfinance 없는 날
    assert repo.get_fx_on_or_before(end).source == "YFINANCE"  # 둘 다 있으면 yfinance
    text = "observation_date,DEXKOUS\n2000-01-03,1128.1\n2000-01-17,.\n"
    got = fred_client.parse(text, "USDKRW", datetime(2026, 1, 1, tzinfo=UTC))
    assert [(x.date, x.rate) for x in got] == [(date(2000, 1, 3), 1128.1)]
