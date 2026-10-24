"""valuation_daily: 공시일 기준 as-of (선견 없음), 적자 PER NULL, 분할 보정, 바뀐 행만 다시 씀.

순수 계산(compute_asset)과 저장소를 거친 작업(valuation_step, 인메모리 SQLite·있으면 PostgreSQL).
"""

from __future__ import annotations

import os
from datetime import UTC, date, datetime, timedelta

import pandas as pd
import pytest
from helpers import AT
from sqlalchemy import create_engine

from backend.db import SqlRepository, open_repository
from backend.db import tables as T
from backend.pipeline.valuation import compute_asset, plan_from_dates, valuation_step
from backend.schemas.market import PriceBar
from backend.schemas.market_ext import FinancialRow

PG_URL = os.environ.get("MYFINSIGHT_TEST_PG_URL", "")
FETCHED = datetime(2025, 8, 1, tzinfo=UTC)


def _f(item: str, pend: date, val: float, rep: date, period: str | None = None) -> dict:
    return {"item": item, "period_end": pend, "period": period or f"Q{pend}", "value": val,
            "report_date": rep}  # fmt: skip


def _px(days: list[date], close: float | list[float], fetched: datetime = FETCHED) -> pd.DataFrame:
    closes = close if isinstance(close, list) else [close] * len(days)
    return pd.DataFrame({"date": days, "close": closes, "fetched_at": [fetched] * len(days)})


QUARTERS = [date(2024, 3, 31), date(2024, 6, 30), date(2024, 9, 30), date(2024, 12, 31)]


def _fins(ni_last: float = 10.0, extra: list[dict] | None = None) -> pd.DataFrame:
    rows = [_f("당기순이익(분기)", q, 10.0, q + timedelta(days=40)) for q in QUARTERS[:3]]
    rows.append(_f("당기순이익(분기)", QUARTERS[3], ni_last, date(2025, 3, 1)))
    rows += [
        _f("자본총계", date(2023, 12, 31), 360.0, date(2024, 3, 1)),
        _f("자본총계", QUARTERS[3], 440.0, date(2025, 3, 1)),
        _f("유통주식수", QUARTERS[3], 100.0, date(2025, 3, 1)),
    ]
    return pd.DataFrame(rows + (extra or []))


def _one(rows: list[dict], d: date) -> dict:
    return next(r for r in rows if r["date"] == d)


def test_method_marks_supplementary_share_source() -> None:
    """주식 수가 보충 출처(yfinance) 값이면 method 에 @출처, 공시 출처(SEC) 값이면 그대로."""
    fins = _fins()
    fins["source"] = "SEC_EDGAR"
    yf = _f("유통주식수", date(2025, 3, 31), 120.0, date(2025, 3, 31)) | {"source": "YFINANCE_SHARES"}
    fins = pd.concat([fins, pd.DataFrame([yf])], ignore_index=True)
    days = [date(2025, 3, 3), date(2025, 4, 1)]
    rows = compute_asset(_px(days, 20.0), fins, asset_id="US-X", ticker="X", currency="USD")
    assert "SH=유통주식수;" in _one(rows, date(2025, 3, 3))["method"]
    after = _one(rows, date(2025, 4, 1))
    assert "SH=유통주식수@YFINANCE_SHARES;" in after["method"]
    assert after["market_cap"] == pytest.approx(20.0 * 120.0)


def test_as_of_uses_only_disclosed_values() -> None:
    days = [date(2025, 2, 28), date(2025, 3, 1), date(2025, 3, 3)]
    rows = compute_asset(_px(days, 20.0), _fins(), asset_id="US-X", ticker="X", currency="USD")
    before = _one(rows, date(2025, 2, 28))
    # 2024년 4분기 공시 전날: 이어진 4개 분기가 없음 → TTM 없음, 주식 수도 없음
    assert before["net_income_ttm"] is None and before["per"] is None
    assert before["market_cap"] is None and before["shares_as_of"] is None
    on = _one(rows, date(2025, 3, 1))  # 공시일 당일부터 씀
    assert on["net_income_ttm"] == 40.0 and on["market_cap"] == 2000.0
    assert on["per"] == pytest.approx(50.0) and on["eps_ttm"] == pytest.approx(0.4)
    assert on["per"] == pytest.approx(on["close"] / on["eps_ttm"])
    assert on["pbr"] == pytest.approx(2000 / 440)
    assert on["roe_ttm"] == pytest.approx(40 / ((440 + 360) / 2))  # 평균 자본 (1년 전과)
    assert on["bps"] == pytest.approx(4.4)
    assert (on["fin_period_end"], on["fin_disclosed_at"], on["shares_as_of"]) == (
        date(2024, 12, 31), date(2025, 3, 1), date(2024, 12, 31),
    )  # fmt: skip
    assert on["method"].startswith("NI=4Q;SH=유통주식수")


def test_negative_earnings_gives_null_per() -> None:
    rows = compute_asset(
        _px([date(2025, 3, 3)], 20.0), _fins(ni_last=-100.0), asset_id="US-X", ticker="X",
        currency="USD",
    )  # fmt: skip
    r = rows[0]
    assert r["net_income_ttm"] == -70.0 and r["per"] is None
    assert r["eps_ttm"] == pytest.approx(-0.7) and r["pbr"] is not None


def test_split_after_price_was_fetched_and_shares_adjusted() -> None:
    """2:1 분할(2025-06-02). 6월 전 종가는 분할 뒤에 받아 분할 보정된 값 (실제의 절반)."""
    split = _f("주식분할", date(2025, 6, 2), 2.0, date(2025, 6, 2), "SPLIT2025-06-02")
    days = [date(2025, 3, 3), date(2025, 6, 3)]
    rows = compute_asset(_px(days, [10.0, 10.0]), _fins(extra=[split]), asset_id="US-X",
                         ticker="X", currency="USD")  # fmt: skip
    pre, post = rows
    assert pre["split_factor"] == 2.0 and post["split_factor"] == 1.0
    assert pre["shares_outstanding"] == 100 and post["shares_outstanding"] == 200
    assert pre["market_cap"] == 2000 and post["market_cap"] == 2000  # 실제 종가 20 × 100
    assert pre["per"] == pytest.approx(post["per"]) == pytest.approx(50.0)
    assert pre["eps_ttm"] == pytest.approx(0.2)  # close(분할 보정) 기준 주당 값


def test_dividends_ttm_and_fallbacks() -> None:
    dq = [_f("주당배당금(분기)", q, 0.25, q + timedelta(days=40)) for q in QUARTERS[:3]]
    dq.append(_f("주당배당금(분기)", QUARTERS[3], 0.25, date(2025, 3, 1)))
    r = compute_asset(_px([date(2025, 3, 3)], 20.0), _fins(extra=dq), asset_id="US-X",
                      ticker="X", currency="USD")[0]  # fmt: skip
    assert r["dps_ttm"] == pytest.approx(1.0) and r["dividend_yield"] == pytest.approx(0.05)
    # 한국: 사업연도 주당배당금, 분기 손익이 없으면 사업연도 순이익
    kr = pd.DataFrame([
        _f("당기순이익", date(2024, 12, 31), 5e11, date(2025, 3, 11), "2024_11011"),
        _f("당기순이익", date(2025, 3, 31), 9e11, date(2025, 5, 15), "2025_11013"),  # 3개월 → 안 씀
        _f("주당배당금", date(2024, 12, 31), 1446.0, date(2025, 3, 11), "2024_11011"),
        _f("발행주식수", date(2024, 12, 31), 1e9, date(2025, 3, 11), "2024_11011"),
        _f("자기주식수", date(2024, 12, 31), 1e8, date(2025, 3, 11), "2024_11011"),
    ])  # fmt: skip
    r = compute_asset(_px([date(2025, 6, 2)], 50000.0), kr, asset_id="KR-005930",
                      ticker="005930.KS", currency="KRW")[0]  # fmt: skip
    assert r["net_income_ttm"] == 5e11 and r["method"].startswith("NI=FY;SH=발행-자기;DPS=FY")
    assert r["shares_outstanding"] == 9e8 and r["per"] == pytest.approx(50000 * 9e8 / 5e11)
    assert r["dividend_yield"] == pytest.approx(1446 / 50000)


def test_stale_values_dropped() -> None:
    far = date(2025, 3, 1) + timedelta(days=600)
    r = compute_asset(_px([far], 20.0), _fins(), asset_id="US-X", ticker="X", currency="USD")[0]
    assert r["net_income_ttm"] is None and r["market_cap"] is None and r["pbr"] is None


def test_plan_from_dates() -> None:
    start = date(2016, 1, 1)
    plan = plan_from_dates(
        ["A", "B", "C", "D"],
        start=start,
        last_valued={"A": date(2025, 1, 10), "B": date(2025, 1, 10), "D": date(2025, 1, 10)},
        last_price={
            "A": date(2025, 1, 13),
            "B": date(2025, 1, 10),
            "C": date(2025, 1, 10),
            "D": date(2025, 1, 10),
        },  # fmt: skip
        changes={"D": date(2024, 6, 1)},
    )
    assert plan == {"A": date(2025, 1, 11), "C": start, "D": date(2024, 6, 1)}


# ---------------------------------------------------------------- 저장소 + 작업
@pytest.fixture(
    params=[
        "sqlite",
        pytest.param(
            "postgresql", marks=pytest.mark.skipif(not PG_URL, reason="MYFINSIGHT_TEST_PG_URL 없음")
        ),
    ]
)
def repo(request: pytest.FixtureRequest) -> SqlRepository:
    clock = {"now": AT}
    if request.param == "sqlite":
        r = open_repository("sqlite://", clock=lambda: clock["now"])
    else:
        engine = create_engine(PG_URL)
        T.metadata.drop_all(engine)
        engine.dispose()
        r = open_repository(PG_URL, clock=lambda: clock["now"])
        request.addfinalizer(r.engine.dispose)
    r.test_clock = clock  # type: ignore[attr-defined]
    return r


def _bars(days: list[date], close: float) -> list[PriceBar]:
    return [PriceBar(ticker="AAPL", date=d, adj_close=close, close=close, source="ALPACA",
                     fetched_at=FETCHED) for d in days]  # fmt: skip


def _fin_rows(rows: pd.DataFrame) -> list[FinancialRow]:
    return [
        FinancialRow(asset_id="US-AAPL", source="SEC_EDGAR", period=r.period, metric=r.item,
                     value=r.value, period_end=r.period_end, disclosed_at=r.report_date,
                     fetched_at=FETCHED)
        for r in rows.itertuples()
    ]  # fmt: skip


def _weekdays(start: date, end: date) -> list[date]:
    out, d = [], start
    while d <= end:
        if d.weekday() < 5:
            out.append(d)
        d += timedelta(days=1)
    return out


def _run(repo: SqlRepository, now: datetime, **kw: object):  # noqa: ANN202
    repo.test_clock["now"] = now  # type: ignore[attr-defined]
    return valuation_step(repo, today=date(2025, 4, 30), years=10, now=now, **kw)


def test_valuation_step_writes_only_changes(repo: SqlRepository) -> None:
    days = _weekdays(date(2025, 2, 24), date(2025, 3, 7))
    repo.test_clock["now"] = datetime(2025, 3, 31, tzinfo=UTC)  # type: ignore[attr-defined]
    repo.upsert_prices(_bars(days, 20.0))
    repo.upsert_financials(_fin_rows(_fins()))
    t1 = datetime(2025, 4, 1, tzinfo=UTC)
    first = _run(repo, t1)
    assert first.done and first.written == len(days)
    with repo.engine.connect() as c:
        stored = {r.date: r for r in c.execute(T.valuation_daily.select())}
    assert stored[date(2025, 2, 28)].per is None and stored[date(2025, 3, 3)].per == 50.0
    assert stored[date(2025, 3, 3)].updated_at == t1

    # 아무것도 안 바뀜 → 읽을 종목도, 쓸 행도 없음
    again = _run(repo, datetime(2025, 4, 2, tzinfo=UTC))
    assert again.assets == 0 and again.written == 0

    # 새 거래일 하나 → 그날만
    repo.test_clock["now"] = datetime(2025, 4, 3, tzinfo=UTC)  # type: ignore[attr-defined]
    repo.upsert_prices(_bars([date(2025, 3, 10)], 21.0))
    inc = _run(repo, datetime(2025, 4, 3, 1, tzinfo=UTC))
    assert inc.rows == 1 and inc.written == 1

    # 2024-12-31 순이익이 정정돼 다시 저장됨(공시일 2025-03-01) → 그 날부터 다시 계산,
    # 공시 전 날짜(2/24~2/28) 행은 그대로
    repo.test_clock["now"] = datetime(2025, 4, 4, tzinfo=UTC)  # type: ignore[attr-defined]
    repo.upsert_financials(_fin_rows(_fins(ni_last=30.0)))
    fix = _run(repo, datetime(2025, 4, 4, 1, tzinfo=UTC))
    after_pub = [d for d in days + [date(2025, 3, 10)] if d >= date(2025, 3, 1)]
    assert fix.rows == len(after_pub) and fix.written == len(after_pub)
    with repo.engine.connect() as c:
        stored = {r.date: r for r in c.execute(T.valuation_daily.select())}
    assert stored[date(2025, 3, 3)].net_income_ttm == 60.0
    assert stored[date(2025, 2, 24)].updated_at == t1  # 안 바뀐 행은 다시 쓰지 않음


def test_valuation_step_partial_then_resume(repo: SqlRepository) -> None:
    class Stop:
        def over(self) -> bool:
            return True

    repo.upsert_prices(_bars([date(2025, 3, 3)], 20.0))
    repo.upsert_financials(_fin_rows(_fins()))
    t1 = datetime(2025, 4, 1, tzinfo=UTC)
    stopped = _run(repo, t1, deadline=Stop())
    assert not stopped.done and stopped.written == 0
    hist = repo.fetch_history("valuation_daily")
    assert [h["status"] for h in hist] == ["PARTIAL"]
    done = _run(repo, datetime(2025, 4, 2, tzinfo=UTC))
    assert done.done and done.written == 1
    # 끝난 바퀴의 기준 시각 = 처음 멈춘 실행의 시각 (그 사이 바뀐 입력을 놓치지 않게)
    assert repo.fetch_history("valuation_daily")[-1]["fetched_at"] == t1


def test_dart_annual_net_income_fills_broken_quarters() -> None:
    """분기 사슬이 끊겨도 DART 사업보고서의 "당기순이익(손실)"(2024_11011) 로 PER (method NI=FY)."""
    fins = pd.DataFrame([
        _f("당기순이익(손실)", QUARTERS[3], 40.0, date(2025, 3, 10), period="2024_11011"),
        _f("당기순이익(손실)", QUARTERS[2], 99.0, date(2024, 11, 14), period="2024_11014"),  # 분기 보고서 값은 안 씀
        _f("자본총계", QUARTERS[3], 440.0, date(2025, 3, 10)),
        _f("유통주식수", QUARTERS[3], 100.0, date(2025, 3, 10)),
    ])  # fmt: skip
    rows = compute_asset(_px([date(2025, 3, 11)], 20.0), fins, asset_id="KR-X", ticker="X.KS",
                         currency="KRW")  # fmt: skip
    r = rows[0]
    assert r["net_income_ttm"] == 40.0 and r["per"] == pytest.approx(20.0 * 100 / 40.0)
    assert r["method"].startswith("NI=FY;")
