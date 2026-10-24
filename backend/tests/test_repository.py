"""M02-04 SqlRepository: upsert 건너뛰기·갱신, PriceFrame 계약, needs_fetch 경계,
종목 마스터·한국 종목, 환율·구성종목·수집 이력·실행 기록·리포트·재무·뉴스 저장과 조회,
데이터 계약(module_prototype2 2.2절) 테이블: 가격·재무 발행, 키, 쓰기 테이블.

저장소 테스트는 인메모리 SQLite 로 돈다. 환경변수 MYFINSIGHT_TEST_PG_URL 에 PostgreSQL 주소를
주면 같은 테스트를 PostgreSQL 에서도 한 번 더 돈다 (테이블을 지우고 다시 만드니 테스트 전용 DB 로).
    $env:MYFINSIGHT_TEST_PG_URL = "postgresql+psycopg://postgres:postgres@localhost:5432/myfinsight_test"
"""

from __future__ import annotations

import os
from datetime import UTC, date, datetime, timedelta
from pathlib import Path

import pandas as pd
import pytest
from helpers import (
    StubPriceAdapter,
    fin_row,
    financial_batch,
    make_constituents,
    news_batch,
    news_row,
    price_rows,
)
from sqlalchemy import MetaData, Table, UniqueConstraint, create_engine, func, insert, select

from backend.db import (
    ExtendedRepository,
    MarketDataRepository,
    SqlRepository,
    open_repository,
    previous_weekday,
)
from backend.db import tables as T
from backend.db.sql import statement_of, url_hash
from backend.pipeline.normalizer import normalize, normalize_financials, normalize_news
from backend.pipeline.price_loader import load_prices
from backend.schemas.contracts import price_frame_problems
from backend.schemas.errors import RepositoryError
from backend.schemas.market import FxRate, IndexCode, IndexConstituent, PriceBar
from backend.schemas.market_ext import AssetInfo, FinancialRow, NewsRow
from backend.schemas.runlog import StepRecord, StepStatus

AT = datetime(2026, 10, 1, tzinfo=UTC)
LATER = datetime(2026, 10, 2, 9, 30, tzinfo=UTC)


PG_URL = os.environ.get("MYFINSIGHT_TEST_PG_URL", "")
BACKENDS = [
    "sqlite",
    pytest.param(
        "postgresql", marks=pytest.mark.skipif(not PG_URL, reason="MYFINSIGHT_TEST_PG_URL 없음")
    ),
]


@pytest.fixture(params=BACKENDS)
def repo(request: pytest.FixtureRequest) -> SqlRepository:
    if request.param == "sqlite":
        return open_repository("sqlite://", clock=lambda: AT)
    engine = create_engine(PG_URL)
    T.metadata.drop_all(engine)
    engine.dispose()
    r = open_repository(PG_URL, clock=lambda: AT)
    request.addfinalizer(r.engine.dispose)
    return r


def _assets() -> list[AssetInfo]:
    kr = {"market": "KR", "exchange": "KOSPI", "currency": "KRW"}
    us = {"market": "US", "currency": "USD"}
    return [
        AssetInfo(
            asset_id="KR-005930",
            ticker="005930",
            name="삼성전자",
            yfinance_symbol="005930.KS",
            dart_corp_code="00126380",
            kis_ticker="005930",
            **kr,
        ),
        AssetInfo(
            asset_id="KR-000660",
            ticker="000660",
            name="SK하이닉스",
            yfinance_symbol="000660.KS",
            dart_corp_code="00164779",
            kis_ticker="000660",
            **kr,
        ),
        AssetInfo(
            asset_id="US-MSFT",
            ticker="MSFT",
            name="Microsoft",
            yfinance_symbol="MSFT",
            sec_cik="0000789019",
            tiingo_symbol="MSFT",
            alpaca_symbol="MSFT",
            **us,
        ),
        AssetInfo(
            asset_id="US-BRK-B",
            ticker="BRK-B",
            name="Berkshire Hathaway",
            yfinance_symbol="BRK-B",
            sec_cik="0001067983",
            tiingo_symbol="BRK-B",
            alpaca_symbol="BRK.B",
            **us,
        ),
        AssetInfo(
            asset_id="US-SPY",
            ticker="SPY",
            name="SPDR S&P 500 ETF",
            asset_type="ETF",
            yfinance_symbol="SPY",
            **us,
        ),
    ]


def _bars(tickers: list[str], start: date, end: date, **kw) -> list[PriceBar]:  # noqa: ANN003
    return normalize(StubPriceAdapter(**kw).fetch(tickers, start, end)).bars


def _expected(tickers: list[str], start: date, end: date) -> pd.DataFrame:
    """스텁이 낸 값으로 만든 기대 PriceFrame."""
    cols = {
        t: pd.Series({pd.Timestamp(r["date"]): r["adj_close"] for r in price_rows(t, start, end)})
        for t in sorted(tickers)
    }
    frame = pd.DataFrame(cols).astype("float64")
    frame.index.name = "date"
    return frame


def _bar(t: str, d: date, px: float, source: str = "yfinance", at: datetime = AT) -> PriceBar:
    return PriceBar(ticker=t, date=d, adj_close=px, volume=1, source=source, fetched_at=at)


def test_is_repository(repo: SqlRepository) -> None:
    assert isinstance(repo, MarketDataRepository) and isinstance(repo, ExtendedRepository)
    status = repo.source_status()
    assert {"YFINANCE", "KIS", "CONSENSUS", "WIKIPEDIA", "KRX"} <= set(status)


def test_upsert_twice_second_is_zero(repo: SqlRepository) -> None:
    bars = _bars(["SPY", "MSFT"], date(2026, 1, 1), date(2026, 9, 30))
    assert repo.upsert_prices(bars) == len(bars)
    refetched = [b.model_copy(update={"fetched_at": LATER}) for b in bars]
    assert repo.upsert_prices(refetched) == 0  # 수집 시각만 다르면 건너뜀


def test_upsert_updates_only_changed(repo: SqlRepository) -> None:
    d1, d2 = date(2026, 9, 1), date(2026, 9, 2)
    assert repo.upsert_prices([_bar("A", d1, 10.0), _bar("A", d2, 11.0)]) == 2
    assert (
        repo.upsert_prices(
            [_bar("A", d1, 10.0), _bar("A", d2, 11.5), _bar("A", date(2026, 9, 3), 12.0)]
        )
        == 2
    )
    frame, _ = repo.get_prices(["A"], d1, date(2026, 9, 3))
    assert frame["A"].tolist() == [10.0, 11.5, 12.0]


def test_get_prices_meets_contract(repo: SqlRepository) -> None:
    tickers = ["SPY", "MSFT", "NVDA"]
    start, end = date(2024, 1, 1), date(2026, 9, 30)
    repo.upsert_prices(_bars(tickers, start, end))
    frame, meta = repo.get_prices(tickers + ["NONE"], start, end)
    assert price_frame_problems(frame) == []
    pd.testing.assert_frame_equal(frame[sorted(tickers)], _expected(tickers, start, end))
    assert frame["NONE"].isna().all()
    assert meta.tickers == ["MSFT", "NONE", "NVDA", "SPY"]
    assert meta.source == "TEST" and meta.as_of == end and meta.fetched_at == AT
    assert meta.currency == "USD"


def test_get_prices_range_and_empty(repo: SqlRepository) -> None:
    repo.upsert_prices(_bars(["SPY"], date(2026, 9, 1), date(2026, 9, 30)))
    frame, _ = repo.get_prices(["SPY"], date(2026, 9, 10), date(2026, 9, 11))
    assert [d.date() for d in frame.index] == [date(2026, 9, 10), date(2026, 9, 11)]
    empty, meta = repo.get_prices(["SPY"], date(2020, 1, 1), date(2020, 1, 31))
    assert len(empty) == 0 and list(empty.columns) == ["SPY"] and meta.source == "none"
    assert price_frame_problems(empty) == []


def _published(repo: SqlRepository) -> dict[tuple[str, date], dict]:
    p = T.price_daily
    with repo.engine.connect() as c:
        return {(r.asset_id, r.date): r._asdict() for r in c.execute(select(p))}


def test_get_prices_picks_priority_source_not_consensus(repo: SqlRepository) -> None:
    """계약 price_daily = 우선순위 1위 출처의 원본 행 (CONSENSUS 중앙값은 싣지 않음)."""
    d = date(2026, 9, 1)
    repo.upsert_prices([_bar("A", d, 10.0, "yfinance", LATER), _bar("A", d, 10.1, "tiingo", AT)])
    frame, meta = repo.get_prices(["A"], d, d)  # USD: ALPACA → TIINGO → YFINANCE
    assert frame.loc[pd.Timestamp(d), "A"] == 10.1 and meta.source == "TIINGO"
    repo.upsert_prices([_bar("A", d, 10.05, "CONSENSUS", AT)])  # 검증 행은 가공값이라 안 실음
    frame, meta = repo.get_prices(["A"], d, d)
    assert frame.loc[pd.Timestamp(d), "A"] == 10.1 and meta.source == "TIINGO"
    repo.upsert_prices([_bar("A", d, 9.9, "alpaca", AT)])
    frame, meta = repo.get_prices(["A"], d, d)
    assert frame.loc[pd.Timestamp(d), "A"] == 9.9 and meta.source == "ALPACA"
    # 목록 밖 출처끼리는 수집 시각이 늦은 행
    repo.upsert_prices([_bar("B", d, 1.0, "x1", AT), _bar("B", d, 2.0, "x2", LATER)])
    assert repo.get_prices(["B"], d, d)[1].source == "X2"


def test_publish_rewrites_only_changed_rows(repo: SqlRepository) -> None:
    """원본 값이 그대로거나 실리지 않는 출처만 바뀌면 계약 price_daily 행을 다시 쓰지 않음."""
    clock = {"now": AT}
    r = SqlRepository(repo.engine, clock=lambda: clock["now"], create_tables=False)
    d1, d2 = date(2026, 9, 1), date(2026, 9, 2)
    r.upsert_prices([_bar("A", d1, 10.0, "alpaca"), _bar("A", d2, 11.0, "alpaca")])
    first = _published(r)
    assert first[("US-A", d1)]["updated_at"] == AT and first[("US-A", d1)]["ticker"] == "A"
    clock["now"] = LATER
    assert r.upsert_prices([_bar("A", d1, 10.0, "alpaca", LATER)]) == 0  # 같은 값
    r.upsert_prices([_bar("A", d1, 10.4, "yfinance")])  # 낮은 순위 출처만 추가
    assert _published(r) == first  # 계약 행은 그대로 (updated_at 도)
    r.upsert_prices([_bar("A", d2, 11.5, "alpaca")])  # 실린 출처 값이 바뀜
    after = _published(r)
    assert after[("US-A", d2)]["adj_close"] == 11.5 and after[("US-A", d2)]["updated_at"] == LATER
    assert after[("US-A", d1)] == first[("US-A", d1)]


def test_published_keeps_ohlc_and_raw_adj_close(repo: SqlRepository) -> None:
    d = date(2026, 9, 1)
    bar = PriceBar(
        ticker="005930.KS", date=d, open=70000, high=71000, low=69000, close=70500,
        adj_close=69800, volume=10, currency="KRW", source="KIS", fetched_at=AT,
    )  # fmt: skip
    repo.upsert_prices([bar])
    row = _published(repo)[("KR-005930", d)]
    assert (row["open"], row["high"], row["low"], row["close"], row["adj_close"]) == (
        70000, 71000, 69000, 70500, 69800,
    )  # fmt: skip
    assert (row["currency"], row["ticker"], row["source"]) == ("KRW", "005930.KS", "KIS")


def test_kr_prices_and_assets(repo: SqlRepository) -> None:
    kr = ["005930.KS", "000660.KS"]
    bars = _bars(kr, date(2026, 9, 1), date(2026, 9, 30))
    assert {b.currency for b in bars} == {"KRW"}
    repo.upsert_prices(bars)
    frame, meta = repo.get_prices(kr, date(2026, 9, 1), date(2026, 9, 30))
    pd.testing.assert_frame_equal(frame, _expected(kr, date(2026, 9, 1), date(2026, 9, 30)))
    assert meta.currency == "KRW" and price_frame_problems(frame) == []
    a = {x.asset_id: x for x in repo.get_assets(kr)}
    assert (a["KR-005930"].market, a["KR-005930"].exchange) == ("KR", "KOSPI")
    assert a["KR-005930"].kis_ticker == "005930"
    with pytest.raises(RepositoryError) as e:  # 통화가 다른 종목을 한 표로
        repo.get_prices(["005930.KS", "SPY"], date(2026, 9, 1), date(2026, 9, 30))
    assert e.value.code == "REPO_READ_FAILED"


def test_upsert_assets_keeps_codes(repo: SqlRepository) -> None:
    assets = _assets()
    assert repo.upsert_assets(assets) == len(assets)
    assert repo.upsert_assets(assets) == 0
    repo.upsert_prices([_bar("BRK-B", date(2026, 9, 1), 1.0)])  # 이미 있는 종목은 새로 안 만듦
    got = {a.asset_id: a for a in repo.get_assets()}
    assert len(got) == len(assets) and got["US-BRK-B"].alpaca_symbol == "BRK.B"
    assert repo.asset_key_map("dart_corp_code")["00126380"] == "KR-005930"
    changed = assets[0].model_copy(update={"name": "새 이름"})
    assert repo.upsert_assets([changed]) == 1


def test_covered_range(repo: SqlRepository) -> None:
    assert repo.covered_range("SPY") is None
    repo.upsert_prices(_bars(["SPY"], date(2026, 9, 1), date(2026, 9, 30)))
    assert repo.covered_range("SPY") == (date(2026, 9, 1), date(2026, 9, 30))


def test_previous_weekday() -> None:
    assert previous_weekday(date(2026, 10, 5)) == date(2026, 10, 2)  # 월 → 금
    assert previous_weekday(date(2026, 10, 1)) == date(2026, 9, 30)
    assert previous_weekday(date(2026, 10, 5), 2) == date(2026, 10, 1)


def test_needs_fetch_boundaries(repo: SqlRepository) -> None:
    start = date(2026, 9, 1)
    assert repo.needs_fetch("SPY", start, date(2026, 9, 30), today=date(2026, 10, 1))  # 저장 없음
    repo.upsert_prices(_bars(["SPY"], start, date(2026, 9, 29)))
    # 오늘 10/1 → 직전 거래일 9/30. 마지막 저장일 9/29 < 9/30 → 받아야 함
    assert repo.needs_fetch("SPY", start, date(2026, 9, 30), today=date(2026, 10, 1))
    # 오늘 9/30 → 직전 거래일 9/29 = 마지막 저장일 → 안 받음 (경계: 같으면 충분)
    assert not repo.needs_fetch("SPY", start, date(2026, 9, 30), today=date(2026, 9, 30))
    # end 가 과거면 end 까지만 있으면 됨
    assert not repo.needs_fetch("SPY", start, date(2026, 9, 15), today=date(2026, 10, 1))
    # 요청 시작이 저장 범위보다 이르면 받아야 함
    assert repo.needs_fetch("SPY", date(2026, 8, 1), date(2026, 9, 15), today=date(2026, 10, 1))
    # 시작일이 휴장일(토)이고 첫 저장일이 다음 영업일이면 덮은 것으로 봄
    repo.upsert_prices(_bars(["MSFT"], date(2026, 8, 3), date(2026, 9, 29)))
    assert not repo.needs_fetch(
        "MSFT", date(2026, 8, 1), date(2026, 9, 29), today=date(2026, 9, 30)
    )


def test_fx_roundtrip(repo: SqlRepository) -> None:
    r1 = FxRate(date=date(2026, 9, 25), rate=1390.0, source="YFINANCE", fetched_at=AT)
    r2 = FxRate(date=date(2026, 9, 28), rate=1392.5, source="YFINANCE", fetched_at=AT)
    assert repo.upsert_fx([r1, r2]) == 2
    assert repo.upsert_fx([r1, r2]) == 0
    assert repo.get_fx_on_or_before(date(2026, 9, 27)) == r1  # 주말이면 직전 값
    assert repo.get_fx_on_or_before(date(2026, 9, 30)) == r2
    assert repo.get_fx_on_or_before(date(2026, 9, 1)) is None
    lower = r1.model_copy(
        update={"source": "yfinance", "rate": 1391.0}
    )  # 출처 이름은 대문자로 맞춤
    assert repo.upsert_fx([lower]) == 1  # 같은 키, 다른 값 → 갱신 (부록 B 규칙)
    assert repo.get_fx_on_or_before(date(2026, 9, 27)).rate == 1391.0


def test_fx_key_is_pair_and_date(repo: SqlRepository) -> None:
    """계약 fx_daily 키는 (pair, date): 날짜마다 한 값. 출처별 원본은 fx_daily_source 에 따로,
    fx_daily 는 YFINANCE → FRED 순으로 그날 값이 있는 출처 (FRED 는 빈 날만 채움)."""
    assert [c.name for c in T.fx_daily.primary_key.columns] == ["pair", "date"]
    d, d0 = date(2026, 9, 25), date(2003, 6, 2)
    repo.upsert_fx([FxRate(date=d, rate=1390.0, source="YFINANCE", fetched_at=AT)])
    fred = [FxRate(date=d, rate=1391.5, source="FRED", fetched_at=LATER),
            FxRate(date=d0, rate=1205.0, source="FRED", fetched_at=LATER)]  # fmt: skip
    assert repo.upsert_fx(fred) == 2
    assert repo.upsert_fx(fred) == 0  # 같은 값이면 건너뜀
    with repo.engine.connect() as c:
        rows = c.execute(
            select(T.fx_daily.c.date, T.fx_daily.c.rate, T.fx_daily.c.source).order_by("date")
        ).all()
        n_src = c.execute(select(func.count()).select_from(T.fx_daily_source)).scalar_one()
    assert [tuple(r) for r in rows] == [(d0, 1205.0, "FRED"), (d, 1390.0, "YFINANCE")]
    assert n_src == 3
    assert repo.get_fx_on_or_before(date(2003, 6, 3)).rate == 1205.0


def test_constituents_latest_snapshot(repo: SqlRepository) -> None:
    assert repo.latest_constituents(IndexCode.SP500) == []
    old = make_constituents("SP500", 20, snapshot_date=date(2026, 6, 19))
    new = make_constituents("SP500", 5, snapshot_date=date(2026, 9, 18))
    repo.save_constituents(old)
    repo.save_constituents(new)
    got = repo.latest_constituents(IndexCode.SP500)
    assert got == sorted(new, key=lambda r: r.ticker)
    repo.save_constituents(new[:2])  # 같은 스냅샷 다시 저장 → 통째로 교체
    assert len(repo.latest_constituents(IndexCode.SP500)) == 2
    assert repo.latest_constituents(IndexCode.NDX) == []


def test_kospi200_constituents_stored_as_six_digit_codes(repo: SqlRepository) -> None:
    """계약: index_constituent.ticker 는 한국 6자리 코드, 미국 yfinance 표기. 조회는 yfinance 표기."""
    snap = date(2026, 6, 12)
    rows = [
        IndexConstituent(
            index_code=IndexCode.KOSPI200, ticker=t, name=n, sector="Information Technology",
            industry="Semiconductors", snapshot_date=snap, source="krx_file", fetched_at=AT,
        )
        for t, n in (("005930.KS", "삼성전자"), ("000660.KS", "SK하이닉스"))
    ]  # fmt: skip
    repo.save_constituents(rows)
    repo.save_constituents([r.model_copy(update={"index_code": IndexCode.SP500, "ticker": "brk.b"})
                            for r in rows[:1]])  # fmt: skip
    with repo.engine.connect() as c:
        ic = T.index_constituent
        stored = {
            (r.index_code, r.ticker, r.asset_id)
            for r in c.execute(select(ic.c.index_code, ic.c.ticker, ic.c.asset_id))
        }
    assert stored == {
        ("KOSPI200", "005930", "KR-005930"),
        ("KOSPI200", "000660", "KR-000660"),
        ("SP500", "BRK-B", "US-BRK-B"),
    }
    got = repo.latest_constituents(IndexCode.KOSPI200)
    assert [r.ticker for r in got] == ["000660.KS", "005930.KS"]
    assert got == sorted(rows, key=lambda r: r.ticker)


def test_fetch_log_accumulates(repo: SqlRepository) -> None:
    repo.log_fetch("yfinance", "SPY", date(2026, 9, 1), date(2026, 9, 30), "SUCCESS", AT, None)
    repo.log_fetch(
        "yfinance", "SPY", date(2026, 9, 1), date(2026, 9, 30), "FAILED", LATER, "timeout"
    )
    hist = repo.fetch_history("SPY")
    assert [h["status"] for h in hist] == ["SUCCESS", "FAILED"]
    assert hist[1]["error"] == "timeout" and hist[1]["fetched_at"] == LATER
    assert hist[0]["source"] == "YFINANCE"
    st = repo.source_status()["YFINANCE"]
    assert st["last_success_at"] == AT and st["last_failure_at"] == LATER


def test_financials_and_news(repo: SqlRepository) -> None:
    repo.upsert_assets(_assets())
    dart = financial_batch(
        "DART",
        {
            "00126380": [
                fin_row("2024_11011", "매출액", 3.0e14, "2025-03-11"),
                fin_row("2024_11011", "영업이익", 3.3e13, "2025-03-11"),
                fin_row("2025_11011", "매출액", 3.2e14, "2026-03-10"),
            ]
        },
    )
    rows, dropped = normalize_financials(dart, repo.asset_key_map("dart_corp_code"))
    assert rows and dropped == {}
    assert repo.upsert_financials(rows) == len(rows)
    assert repo.upsert_financials(rows) == 0
    got = repo.get_financials_as_of("KR-005930", date(2026, 9, 30), metrics=["매출액"])
    assert [(r.period, r.value) for r in got] == [("2025_11011", 3.2e14)]  # 최신 공시
    mid = repo.get_financials_as_of("KR-005930", date(2025, 12, 31), metrics=["매출액"])
    assert [r.period for r in mid] == ["2024_11011"]  # 2025년 값은 아직 공시 전
    early = repo.get_financials_as_of("KR-005930", date(2024, 1, 1))
    assert early == []  # 공시 전 값은 안 보임 (선견 금지)

    news = news_batch(
        "GOOGLE_RSS",
        {"Microsoft": [news_row(1, "2026-09-18T14:30:00Z"), news_row(2, "2026-09-20T00:00:00Z")]},
    )
    items, _ = normalize_news(news, {"Microsoft": "US-MSFT"})
    assert repo.upsert_news(items) == len(items) and repo.upsert_news(items) == 0
    back = repo.get_news(
        "US-MSFT", datetime(2026, 9, 1, tzinfo=UTC), datetime(2026, 10, 1, tzinfo=UTC)
    )
    assert [n.url for n in back] == sorted(n.url for n in back) or len(back) == len(items)
    assert len(back) == len(items)

    with pytest.raises(RepositoryError):  # 종목 마스터에 없는 종목
        repo.upsert_news([items[0].model_copy(update={"asset_id": "US-NOPE"})])


def _fin(
    asset_id: str, source: str, period: str, metric: str, value: float, disclosed: date, **kw
) -> FinancialRow:  # noqa: ANN003
    return FinancialRow(
        asset_id=asset_id, source=source, period=period, metric=metric, value=value,
        disclosed_at=disclosed, fetched_at=AT, **kw,
    )  # fmt: skip


def _fin_published(repo: SqlRepository) -> dict[tuple, dict]:
    f = T.financials
    with repo.engine.connect() as c:
        return {
            (r.asset_id, r.period_end, r.statement, r.item): r._asdict()
            for r in c.execute(select(f))
        }


def test_statement_mapping() -> None:
    """수집기가 만드는 지표 이름 → IS / BS / CF, 모르는 것은 ETC."""
    for item in ("매출액", "영업이익", "당기순이익", "EPS(희석)", "EPS(TTM)", "순이익(TTM)"):
        assert statement_of(item) == "IS", item
    for item in ("자산총계", "부채총계", "자본총계", "자본총계(최근)", "유동자산", "이익잉여금"):
        assert statement_of(item) == "BS", item
    assert statement_of("법인세차감전 순이익") == "IS"  # DART 표기 (띄어쓰기 무시)
    assert statement_of("영업활동현금흐름") == "CF"
    assert statement_of("발행주식수") == statement_of("BPS") == statement_of("모르는 지표") == "ETC"


def test_financials_published_by_priority_and_earliest_disclosure(repo: SqlRepository) -> None:
    repo.upsert_assets(_assets())
    pend = date(2025, 12, 31)
    kr = [
        _fin("KR-005930", "DART", "2025_11011", "매출액", 3.0e14, date(2026, 3, 10),
             fs_div="OFS", period_end=pend),
        _fin("KR-005930", "DART", "2025_11011", "매출액", 3.2e14, date(2026, 3, 12),
             fs_div="CFS", period_end=pend),  # 연결이 별도보다 먼저
        _fin("KR-005930", "OTHER", "2025", "매출액", 9.9e14, date(2026, 1, 1),
             fs_div="CFS", period_end=pend),  # 우선순위 밖 출처는 뒤
        _fin("KR-005930", "DART", "2025_11011", "자산총계", 5.0e14, date(2026, 3, 12),
             fs_div="CFS", period_end=pend),
        _fin("KR-005930", "DART", "2025_11011", "주당배당금", 1.0, date(2026, 3, 12)),  # 기간 끝 없음
    ]  # fmt: skip
    us = [  # SEC 스냅샷을 두 번 받음: 같은 기간·지표 → 가장 이른 공시일 값
        _fin("US-MSFT", "SEC_EDGAR", "2026-09-01", "EPS(TTM)", 12.0, date(2026, 7, 30),
             period_end=date(2026, 6, 30)),
        _fin("US-MSFT", "SEC_EDGAR", "2026-09-08", "EPS(TTM)", 12.5, date(2026, 8, 15),
             period_end=date(2026, 6, 30)),
        _fin("US-MSFT", "SEC_EDGAR", "2026-09-08", "발행주식수", 7.4e9, date(2026, 8, 15),
             period_end=date(2026, 7, 20), unit="주"),
    ]  # fmt: skip
    assert repo.upsert_financials(kr + us) == len(kr) + len(us)
    pub = _fin_published(repo)
    assert set(pub) == {
        ("KR-005930", pend, "IS", "매출액"),
        ("KR-005930", pend, "BS", "자산총계"),
        ("US-MSFT", date(2026, 6, 30), "IS", "EPS(TTM)"),
        ("US-MSFT", date(2026, 7, 20), "ETC", "발행주식수"),
    }
    rev = pub[("KR-005930", pend, "IS", "매출액")]
    assert (rev["value"], rev["source"], rev["fs_div"], rev["report_date"]) == (
        3.2e14, "DART", "CFS", date(2026, 3, 12),
    )  # fmt: skip
    eps = pub[("US-MSFT", date(2026, 6, 30), "IS", "EPS(TTM)")]
    assert (eps["value"], eps["report_date"], eps["period"]) == (
        12.0,
        date(2026, 7, 30),
        "2026-09-01",
    )
    assert repo.upsert_financials(kr + us) == 0 and _fin_published(repo) == pub  # 그대로
    # 출처별 조회(get_financials_as_of)는 원본을 그대로 보여 줌
    got = repo.get_financials_as_of("KR-005930", date(2026, 9, 30), metrics=["매출액"])
    assert {(r.source, r.fs_div) for r in got} == {
        ("DART", "CFS"),
        ("DART", "OFS"),
        ("OTHER", "CFS"),
    }


def test_run_artifact_steps_report(repo: SqlRepository) -> None:
    """계약 쓰기 테이블: run_artifact(run_id), run_step((run_id, step)), report(report_id=run_id)."""
    run_id = "20261001-000000-abcdef"
    doc = {"title": "AI 저변동성", "sections": [{"h": "요약", "values": [0.152]}]}
    with pytest.raises(RepositoryError) as e:  # run_artifact 없이 리포트 저장 불가
        repo.save_report(
            run_id, doc, strategy_name="s", request_summary="r", as_of=date(2026, 9, 30)
        )
    assert e.value.code == "REPO_WRITE_FAILED"

    results = {"request_id": "req-1", "stage": "merge", "warnings": [], "cagr": 0.08}
    repo.save_run_artifact(run_id, "req-1", results, {"backtest_years": 3})
    art = repo.get_run_artifact(run_id)
    assert art is not None and art["request_id"] == "req-1" and art["created_at"] == AT
    assert art["results"] == results and art["params"] == {"backtest_years": 3}
    assert art["llm_usage"] is None
    usage = {"input_tokens": 1200, "output_tokens": 300}
    repo.save_run_artifact(run_id, "req-1", results, {"backtest_years": 3}, usage)  # 결과 갱신
    assert repo.get_run_artifact(run_id)["llm_usage"] == usage
    assert repo.get_run_artifact("없음") is None

    queued = StepRecord(run_id=run_id, step="report", status=StepStatus.QUEUED)
    started = StepRecord(
        run_id=run_id, step="fetch_prices", status=StepStatus.STARTED, started_at=AT
    )
    first = StepRecord(
        run_id=run_id,
        step="load_profile",
        status=StepStatus.SUCCESS,
        started_at=datetime(2026, 9, 30, tzinfo=UTC),
    )
    for rec in (queued, first, started):
        repo.save_step(rec)
    done = started.model_copy(
        update={"status": StepStatus.PARTIAL, "ended_at": LATER, "summary": "52/55"}
    )
    repo.save_step(done)
    assert repo.get_steps(run_id) == [first, done, queued]  # 시작 전 단계는 뒤
    cancelled = queued.model_copy(update={"status": StepStatus.CANCELLED})
    repo.save_step(cancelled)
    assert repo.get_steps(run_id)[-1].status == StepStatus.CANCELLED
    with pytest.raises(Exception), repo.engine.begin() as c:  # noqa: B017 - 계약 밖 상태는 DB 가 거부
        c.execute(insert(T.run_step).values(run_id=run_id, step="x", status="SKIPPED"))

    repo.save_report(
        run_id,
        doc,
        strategy_name="AI 저변동성 5종목",
        request_summary="AI 관련",
        as_of=date(2026, 9, 30),
    )
    got = repo.get_report(run_id)
    assert got is not None and got["doc"] == doc and got["report_id"] == run_id
    assert (got["strategy_name"], got["as_of"], got["created_at"]) == (
        "AI 저변동성 5종목", date(2026, 9, 30), AT,
    )  # fmt: skip
    with pytest.raises(RepositoryError) as e:  # 리포트는 불변: 같은 id 로 다시 저장 거부
        repo.save_report(run_id, {"title": "바꿈"}, strategy_name=None, request_summary=None,
                         as_of=date(2026, 9, 30))  # fmt: skip
    assert e.value.code == "REPO_WRITE_FAILED" and e.value.details["reason"] == "immutable"
    assert repo.get_report(run_id)["doc"] == doc
    assert repo.get_report("없음") is None


def test_file_db_persists(tmp_path) -> None:  # noqa: ANN001
    url = f"sqlite:///{tmp_path / 'sub' / 'my.db'}"
    a = open_repository(url)
    a.upsert_prices([_bar("A", date(2026, 9, 1), 1.0)])
    b = open_repository(url)
    assert b.covered_range("A") == (date(2026, 9, 1), date(2026, 9, 1))


def test_bad_url() -> None:
    with pytest.raises(RepositoryError):
        open_repository("mysql://x/y")


def test_default_url_from_env(monkeypatch: pytest.MonkeyPatch) -> None:
    from backend.db import default_db_url

    assert default_db_url() == "sqlite:///data/myfinsight.db"
    monkeypatch.setenv("DATABASE_URL", "postgresql+psycopg://u:p@h:5432/db")
    assert default_db_url() == "postgresql+psycopg://u:p@h:5432/db"


def test_load_prices_uses_cache(repo: SqlRepository) -> None:
    ad = StubPriceAdapter(known={"SPY", "MSFT", "KRW=X"})
    start, end, today = date(2025, 1, 1), date(2026, 9, 30), date(2026, 10, 1)
    frame, meta, s = load_prices(
        ["SPY", "msft", "NOPE"], start, end, adapter=ad, repository=repo, today=today
    )
    assert s.fetched == ["MSFT", "SPY", "KRW=X"] and set(s.failed) == {"NOPE"}
    assert frame["NOPE"].isna().all() and price_frame_problems(frame) == []
    assert repo.get_fx_on_or_before(end) is not None
    calls = len(ad.calls)
    _, _, s2 = load_prices(["SPY", "MSFT"], start, end, adapter=ad, repository=repo, today=today)
    assert s2.cached == ["MSFT", "SPY"] and s2.fetched == [] and len(ad.calls) == calls
    statuses = {h["target"]: h["status"] for h in repo.fetch_history()}
    assert statuses == {"MSFT": "SUCCESS", "SPY": "SUCCESS", "KRW=X": "SUCCESS", "NOPE": "FAILED"}


def test_contract_tables_keys_and_minimum_fields() -> None:
    """데이터 계약(module_prototype2 2.2절)의 테이블·키·최소 필드가 있음 (칸 이름은 DB 정의)."""
    contract = {
        # 읽기 테이블 6개 + fetch_log
        "assets": (
            ["asset_id"],
            ["ticker", "name", "market", "currency", "yfinance_symbol", "exchange"],
        ),
        "index_constituent": (
            ["index_code", "snapshot_date", "ticker"],
            ["name", "sector", "industry", "asset_id"],
        ),
        "price_daily": (
            ["asset_id", "date"],
            ["open", "high", "low", "close", "adj_close", "volume", "currency"],
        ),
        "fx_daily": (["pair", "date"], ["rate", "source"]),
        "financials": (
            ["asset_id", "period_end", "statement", "item"],
            ["value", "report_date"],
        ),
        "news": (
            ["news_id"],
            [
                "asset_id",
                "source",
                "url",
                "title",
                "content",
                "publisher",
                "published_at",
                "language",
            ],
        ),  # fmt: skip
        "fetch_log": (
            ["id"],
            ["source", "target", "start_date", "end_date", "status", "fetched_at", "error"],
        ),
        # 쓰기 테이블 3개
        "run_artifact": (
            ["run_id"],
            ["request_id", "created_at", "results_json", "params_json", "llm_usage_json"],
        ),
        "run_step": (
            ["run_id", "step"],
            ["status", "started_at", "ended_at", "summary", "error_code", "error_message"],
        ),
        "report": (
            ["report_id"],
            ["created_at", "doc_json", "strategy_name", "request_summary", "as_of"],
        ),
    }
    for name, (pk, cols) in contract.items():
        table = T.metadata.tables[name]
        assert [c.name for c in table.primary_key.columns] == pk, name
        assert set(cols) <= {c.name for c in table.columns}, name
    assert T.run_step.c.started_at.nullable and not T.report.c.as_of.nullable
    assert set(T.metadata.tables) - set(contract) == {
        "data_sources",
        "extra_ticker",
        "price_daily_source",
        "financials_source",
        "fx_daily_source",
        "valuation_daily",  # 계약 밖 추가 발행 테이블 (읽기 계정이 읽음)
        "gics_taxonomy",  # 참조 테이블: GICS 분류표 (읽기 계정이 읽음)
        "disclosures",  # 계약 밖 추가 (v5): SEC EDGAR·DART 공시 목록 (읽기 계정이 읽음)
    }
    assert [c.name for c in T.valuation_daily.primary_key.columns] == ["asset_id", "date"]
    assert [c.name for c in T.gics_taxonomy.primary_key.columns] == ["code"]
    # v4 GICS 칸은 모두 NULL 허용 (v3 DB 에 ALTER TABLE ADD COLUMN 으로 더함)
    for c in ("gics_sector_code", "gics_sub_industry_code", "gics_source", "business_summary"):
        assert T.assets.c[c].nullable, c
    assert T.index_constituent.c.gics_sub_industry_code.nullable
    src = T.price_daily_source  # 출처별 원본은 v1 price_daily 칸·키 그대로
    assert [c.name for c in src.primary_key.columns] == ["ticker", "date", "source"]


def test_extra_tickers_added_once_and_listed(repo: SqlRepository) -> None:
    assert repo.add_extra_tickers(["tsla", "005930.KS"]) == 2
    assert repo.add_extra_tickers(["TSLA"]) == 0  # 이미 있음
    assert repo.extra_tickers() == ["005930.KS", "TSLA"]
    assert {a.yfinance_symbol for a in repo.get_assets(["TSLA", "005930.KS"])} == {
        "TSLA",
        "005930.KS",
    }
    assert repo.extra_tickers(since=AT + timedelta(days=1)) == []


def _news(url: str, title: str = "제목") -> NewsRow:
    return NewsRow(
        asset_id="US-SPY", source="GOOGLE_RSS", url=url, title=title,
        published_at=AT, fetched_at=AT,
    )  # fmt: skip


def test_long_news_url_saved_and_deduplicated(repo: SqlRepository) -> None:
    repo.upsert_assets(_assets())
    long_url = "https://news.google.com/rss/articles/" + "A" * 5000  # 인덱스 한도(약 2.7KB) 넘음
    assert repo.upsert_news([_news(long_url), _news(long_url + "B")]) == 2
    assert repo.upsert_news([_news(long_url)]) == 0  # 같은 주소는 건너뜀
    assert repo.upsert_news([_news(long_url, "고친 제목")]) == 1  # 값이 바뀌면 갱신
    got = repo.get_news("US-SPY", AT, AT)
    assert sorted(n.title for n in got) == ["고친 제목", "제목"]


@pytest.mark.parametrize("backend", BACKENDS)
def test_old_news_table_migrated_to_url_hash(backend: str, tmp_path: Path) -> None:
    """url_hash 가 없던 예전 news 테이블: 열면 칸이 생기고 기존 행이 채워지고 새 키로 중복을 막음."""
    url = f"sqlite:///{tmp_path / 'old.db'}" if backend == "sqlite" else PG_URL
    engine = create_engine(url)
    T.metadata.drop_all(engine)
    old = MetaData()
    for t in T.metadata.sorted_tables:
        if t.name == "news":
            cols = [c._copy() for c in t.columns if c.name != "url_hash"]
            Table("news", old, *cols, UniqueConstraint("asset_id", "url", name="uq_news_natural"))
        else:
            t.to_metadata(old)
    old.create_all(engine)
    with engine.begin() as c:
        c.execute(insert(T.data_sources).values(source_name="GOOGLE_RSS", type="QUAL"))
        a = _assets()[-1]
        c.execute(insert(T.assets).values(**a.model_dump(), created_at=AT, updated_at=AT))
        c.execute(
            insert(old.tables["news"]).values(
                asset_id=a.asset_id, source="GOOGLE_RSS", url="https://x/1", title="t",
                published_at=AT, content_hash="h", fetched_at=AT,
            )
        )  # fmt: skip
    engine.dispose()
    r = open_repository(url, clock=lambda: AT)
    with r.engine.connect() as c:
        assert c.execute(select(T.news.c.url_hash)).scalar_one() == url_hash("https://x/1")
    assert r.upsert_news([_news("https://x/1", "t")]) == 1  # 예전 행과 같은 기사: 사실 표시만 채움
    assert r.upsert_news([_news("https://x/1", "t")]) == 0
    assert repo_news_count(r) == 1
    r.engine.dispose()


def repo_news_count(r: SqlRepository) -> int:
    with r.engine.connect() as c:
        return c.execute(select(func.count()).select_from(T.news)).scalar_one()


def test_write_retries_after_disconnect(
    repo: SqlRepository, monkeypatch: pytest.MonkeyPatch
) -> None:
    """서버가 연결을 끊으면 쉬었다가 같은 트랜잭션을 다시 (끝내 안 되면 RepositoryError)."""
    from sqlalchemy.exc import OperationalError

    from backend.db import sql as S

    waits: list[float] = []
    monkeypatch.setattr(S, "_sleep", waits.append)
    calls = {"n": 0}

    def flaky(conn):  # noqa: ANN001, ANN202
        calls["n"] += 1
        if calls["n"] < 3:
            raise OperationalError(
                "SELECT 1", {}, Exception("server closed the connection unexpectedly")
            )
        return "ok"

    assert repo._write("시험", flaky) == "ok" and waits == [5.0, 20.0]

    def broken(conn):  # noqa: ANN001, ANN202
        raise OperationalError(
            "SELECT 1", {}, Exception("server closed the connection unexpectedly")
        )

    with pytest.raises(RepositoryError):
        repo._write("시험", broken)
    assert waits[2:] == [5.0, 20.0, 60.0]

    def bad_sql(conn):  # noqa: ANN001, ANN202
        raise OperationalError("SELECT x", {}, Exception("no such column: x"))

    with pytest.raises(RepositoryError):
        repo._write("시험", bad_sql)
    assert len(waits) == 5  # SQL 오류는 다시 하지 않음
