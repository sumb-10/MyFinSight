"""교차검증 (verify.py, M02-06 추가): 중앙값 기준값, 허용 오차, 2출처 우선순위, KIS 수정종가 제외,
다시 계산, 값이 바뀌면 재검증. SQLite 와 (MYFINSIGHT_TEST_PG_URL 이 있으면) PostgreSQL 로 돈다.
"""

from __future__ import annotations

import os
from datetime import date, timedelta

import pytest
from helpers import AT
from sqlalchemy import create_engine, select

from backend.db import SqlRepository, open_repository
from backend.db import tables as T
from backend.jobs.daily import verify_job
from backend.pipeline.verify import judge, reverify, verify_step
from backend.schemas.market import PriceBar

PG_URL = os.environ.get("MYFINSIGHT_TEST_PG_URL", "")
D = date(2026, 9, 1)


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


def _bar(t: str, src: str, adj: float, close: float | None = None, d: date = D) -> PriceBar:
    cur = "KRW" if t.endswith(".KS") else "USD"
    return PriceBar(
        ticker=t, date=d, adj_close=adj, close=close, volume=100, currency=cur,
        source=src, fetched_at=AT,
    )  # fmt: skip


def _row(src: str, adj: float, close: float | None = None) -> dict:
    return {
        "ticker": "A", "date": D, "source": src, "adj_close": adj, "close": close,
        "volume": 1, "currency": "USD", "asset_id": "US-A", "fetched_at": AT,
    }  # fmt: skip


def _published(repo: SqlRepository) -> dict[tuple[str, date], dict]:
    p = T.price_daily
    with repo.engine.connect() as c:
        return {(r.asset_id, r.date): r._asdict() for r in c.execute(select(p))}


def _rows(repo: SqlRepository) -> dict[tuple[str, date, str], dict]:
    p = T.price_daily_source
    with repo.engine.connect() as c:
        return {(r.ticker, r.date, r.source): r._asdict() for r in c.execute(select(p))}


# ---------------------------------------------------------------- judge (순수 함수)
def test_judge_three_sources_median_and_outlier() -> None:
    c, marks = judge([_row("ALPACA", 100, 101), _row("TIINGO", 100.2, 101.1), _row("YF", 103, 104)])
    assert c is not None
    assert c["adj_close"] == 100.2 and c["close"] == 101.1 and c["source_count"] == 3
    assert c["verify_status"] == "MISMATCH" and c["outlier_sources"] == ["YF"]
    status = {m["source"]: m["verify_status"] for m in marks}
    assert status == {"ALPACA": "VERIFIED", "TIINGO": "VERIFIED", "YF": "MISMATCH"}


def test_judge_tolerance_boundary() -> None:
    c, _ = judge([_row("A1", 100, 100), _row("A2", 100, 100), _row("A3", 100, 100.5)])
    assert c["verify_status"] == "VERIFIED"  # 0.5% 딱 맞으면 통과
    c, _ = judge([_row("A1", 100, 100), _row("A2", 100, 100), _row("A3", 101.01, 100)])
    assert c["verify_status"] == "MISMATCH"  # 수정종가 1% 초과


def test_judge_two_sources_uses_priority() -> None:
    rows = [_row("ALPACA", 100, 100), _row("YFINANCE", 105, 105)]
    c, marks = judge(rows, priority=("ALPACA", "TIINGO", "YFINANCE"))
    assert c["adj_close"] == 100 and c["outlier_sources"] == ["YFINANCE"]
    assert {m["source"]: m["verify_status"] for m in marks}["ALPACA"] == "VERIFIED"
    c, _ = judge([_row("ALPACA", 100, 100), _row("YFINANCE", 100.4, 100.4)], priority=("ALPACA",))
    assert c["verify_status"] == "VERIFIED" and c["adj_close"] == 100


def test_judge_kis_adj_not_compared() -> None:
    # KIS 수정주가는 배당 미반영: 수정종가가 달라도 종가가 맞으면 VERIFIED
    c, marks = judge([_row("KIS", 70000, 70000), _row("YFINANCE", 66000, 70000)])
    assert c["verify_status"] == "VERIFIED" and c["adj_close"] == 66000
    kis = next(m for m in marks if m["source"] == "KIS")
    assert kis["adj_dev_pct"] is None and kis["dev_pct"] == 0
    c, _ = judge([_row("KIS", 70000, 70000), _row("YFINANCE", 66000, 72000)])
    assert c["verify_status"] == "MISMATCH"


def test_judge_single_source() -> None:
    c, marks = judge([_row("ALPACA", 100, 100)])
    assert c is None and marks[0]["verify_status"] == "SINGLE"


# ---------------------------------------------------------------- DB 와 함께
def test_verify_step_writes_consensus_and_marks(repo: SqlRepository) -> None:
    repo.upsert_prices(
        [
            _bar("MSFT", "ALPACA", 400, 401),
            _bar("MSFT", "YFINANCE", 400.4, 401.2),
            _bar("MSFT", "TIINGO", 410, 411),
            _bar("NVDA", "ALPACA", 100, 100),
            _bar("005930.KS", "KIS", 70000, 70000),
            _bar("005930.KS", "YFINANCE", 66000, 70000),
        ]
    )
    res = verify_step(repo)
    assert res.done and res.counts["keys"] == 3
    assert (res.counts["verified"], res.counts["mismatch"], res.counts["single"]) == (1, 1, 1)
    rows = _rows(repo)
    con = rows[("MSFT", D, "CONSENSUS")]
    assert con["adj_close"] == 400.4 and con["source_count"] == 3
    assert con["verify_status"] == "MISMATCH" and con["outlier_sources"] == ["TIINGO"]
    assert rows[("MSFT", D, "TIINGO")]["verify_status"] == "MISMATCH"
    assert rows[("NVDA", D, "ALPACA")]["verify_status"] == "SINGLE"
    assert ("NVDA", D, "CONSENSUS") not in rows
    assert rows[("005930.KS", D, "CONSENSUS")]["verify_status"] == "VERIFIED"
    # 계약 price_daily 는 CONSENSUS(중앙값)가 아니라 우선순위 1위 출처의 원본 값 + 검증 상태
    frame, meta = repo.get_prices(["MSFT"], D, D)
    assert frame.iloc[0]["MSFT"] == 400 and meta.source == "ALPACA"
    pub = _published(repo)
    assert pub[("US-MSFT", D)]["verify_status"] == "MISMATCH"  # CONSENSUS 행의 상태
    assert pub[("US-NVDA", D)]["verify_status"] == "SINGLE"  # CONSENSUS 없음: 출처 행 상태
    assert pub[("KR-005930", D)]["source"] == "KIS"  # 한국 종가·OHLCV: KIS → yfinance
    assert pub[("KR-005930", D)]["adj_close"] == 66000  # 수정종가: yfinance → KIS
    assert pub[("KR-005930", D)]["adj_close_source"] == "YFINANCE"
    assert repo.pending_verification() == []
    again = verify_step(repo)  # 할 일 없음
    assert again.done and again.counts["keys"] == 0


def test_changed_value_is_reverified(repo: SqlRepository) -> None:
    repo.upsert_prices([_bar("MSFT", "ALPACA", 400, 400), _bar("MSFT", "YFINANCE", 400, 400)])
    verify_step(repo)
    assert repo.upsert_prices([_bar("MSFT", "ALPACA", 400, 400)]) == 0  # 같은 값: 표시 유지
    assert repo.pending_verification() == []
    repo.upsert_prices([_bar("MSFT", "YFINANCE", 420, 420)])  # 값이 바뀜 → 다시 검증 대상
    assert repo.pending_verification() == [("MSFT", D)]
    verify_step(repo)
    assert _rows(repo)[("MSFT", D, "CONSENSUS")]["verify_status"] == "MISMATCH"


def test_reverify_range_and_drop_stale_consensus(repo: SqlRepository) -> None:
    d2 = D + timedelta(days=1)
    repo.upsert_prices(
        [_bar("MSFT", "ALPACA", 400, 400), _bar("MSFT", "YFINANCE", 403, 403),
         _bar("MSFT", "ALPACA", 400, 400, d=d2), _bar("MSFT", "YFINANCE", 400, 400, d=d2)]
    )  # fmt: skip
    verify_step(repo)
    assert _rows(repo)[("MSFT", D, "CONSENSUS")]["verify_status"] == "MISMATCH"
    res = reverify(repo, D, D, close_tol=2.0, adj_tol=2.0)  # 허용 오차를 넓혀 하루만 다시
    assert res.counts["keys"] == 1
    assert _rows(repo)[("MSFT", D, "CONSENSUS")]["verify_status"] == "VERIFIED"
    with repo.engine.begin() as c:  # 출처 하나가 사라진 경우: CONSENSUS 도 지움
        p = T.price_daily_source
        c.execute(p.delete().where(p.c.date == d2, p.c.source == "YFINANCE"))
    reverify(repo, d2, d2)
    rows = _rows(repo)
    assert ("MSFT", d2, "CONSENSUS") not in rows
    assert rows[("MSFT", d2, "ALPACA")]["verify_status"] == "SINGLE"
    pub = _published(repo)
    assert pub[("US-MSFT", D)]["verify_status"] == "VERIFIED"
    assert pub[("US-MSFT", d2)]["verify_status"] == "SINGLE"


def test_verify_stops_at_deadline(repo: SqlRepository) -> None:
    repo.upsert_prices([_bar("MSFT", s, 400, 400) for s in ("ALPACA", "YFINANCE")])

    class Over:
        def over(self) -> bool:
            return True

    res = verify_step(repo, deadline=Over())
    assert not res.done and res.counts["keys"] == 0
    assert repo.pending_verification() == [("MSFT", D)]


def test_verify_job_and_cli_args(repo: SqlRepository) -> None:
    repo.upsert_prices([_bar("MSFT", s, 400, 400) for s in ("ALPACA", "YFINANCE")])
    res = verify_job(repo)
    assert res.name == "verify" and res.done and res.counts["verified"] == 1
    res = verify_job(repo, start=D, end=D)
    assert res.counts["keys"] == 1


def test_ohlc_saved(repo: SqlRepository) -> None:
    repo.upsert_prices(
        [PriceBar(ticker="MSFT", date=D, adj_close=399, open=398, high=402, low=397, close=401,
                  source="ALPACA", fetched_at=AT)]
    )  # fmt: skip
    row = _rows(repo)[("MSFT", D, "ALPACA")]
    assert (row["open"], row["high"], row["low"], row["close"]) == (398, 402, 397, 401)


def test_mismatch_days_reach_load_prices_summary(repo: SqlRepository) -> None:
    from backend.pipeline.price_loader import load_prices

    repo.upsert_prices([_bar("MSFT", "ALPACA", 400, 400), _bar("MSFT", "YFINANCE", 420, 420)])
    verify_step(repo)
    assert repo.mismatch_days(["MSFT", "NVDA"], D, D) == {"MSFT": 1}
    assert repo.mismatch_days(["MSFT"], D + timedelta(days=1), D + timedelta(days=5)) == {}

    class NoFetch:
        def fetch(self, *a, **k):  # noqa: ANN002, ANN003, ANN202
            raise AssertionError("받으면 안 됨")

    _, _, summary = load_prices(
        ["MSFT"], D, D, adapter=NoFetch(), repository=repo, fx_symbol=None, today=D + timedelta(1)
    )
    assert summary.mismatch_days == {"MSFT": 1}


def test_returns_forgive_constant_adjustment_gap() -> None:
    """KIS 가 유상증자 전 가격을 2.1% 낮춰 보정해 수준은 어긋나도 수익률이 같으면 VERIFIED, 수익률이 다르면 MISMATCH."""
    from backend.pipeline.verify import judge

    def row(src: str, close: float) -> dict:
        return {"ticker": "006400.KS", "date": D, "source": src, "close": close, "adj_close": close,
                "volume": 1, "currency": "KRW", "asset_id": "KR-006400", "fetched_at": AT}  # fmt: skip

    rows = [row("KIS", 97.9), row("YFINANCE", 100.0)]
    prio = ("YFINANCE", "KIS")
    c, _ = judge(rows, priority=prio, prev={"KIS": (97.9, 97.9), "YFINANCE": (100.0, 100.0)})
    assert c["verify_status"] == "VERIFIED" and c["dev_pct"] > 2
    c, _ = judge(rows, priority=prio)  # 전 거래일이 없으면 수준만 비교
    assert c["verify_status"] == "MISMATCH" and c["outlier_sources"] == ["KIS"]
    c, _ = judge(rows, priority=prio, prev={"KIS": (97.9, 97.9), "YFINANCE": (95.0, 95.0)})
    assert c["verify_status"] == "MISMATCH"  # 수익률도 다름 (0% vs 5.3%)
