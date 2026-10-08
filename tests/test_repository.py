"""M02-04 SqlRepository: upsert 건너뛰기·갱신, PriceFrame 계약, needs_fetch 경계,
종목 마스터·한국 종목, 환율·구성종목·수집 이력·실행 기록·Report·재무·뉴스 저장과 조회.

저장소 테스트는 인메모리 SQLite 로 돈다. 환경변수 MYFINSIGHT_TEST_PG_URL 에 PostgreSQL 주소를
주면 같은 테스트를 PostgreSQL 에서도 한 번 더 돈다 (테이블을 지우고 다시 만드니 테스트 전용 DB 로).
    $env:MYFINSIGHT_TEST_PG_URL = "postgresql+pg8000://postgres:postgres@localhost:5432/myfinsight_test"
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

from myfinsight.config import AppConfig
from myfinsight.data.contracts import price_frame_problems
from myfinsight.data.normalizer import normalize, normalize_financials, normalize_news
from myfinsight.data.price_loader import load_prices
from myfinsight.data.repository import (
    ExtendedRepository,
    MarketDataRepository,
    SqlRepository,
    open_repository,
    previous_weekday,
)
from myfinsight.data.repository import tables as T
from myfinsight.data.repository.sql import url_hash
from myfinsight.schemas.errors import RepositoryError
from myfinsight.schemas.market import FxRate, IndexCode, PriceBar, UniverseResult
from myfinsight.schemas.market_ext import AssetInfo, NewsRow
from myfinsight.schemas.profile import RiskType, UserProfile
from myfinsight.schemas.report import Report, ReportData
from myfinsight.schemas.results import CalcConditions, MetricsBundle, PerformanceMetrics
from myfinsight.schemas.runlog import StepRecord, StepStatus
from myfinsight.schemas.spec import (
    ConstraintSpec,
    SelectionRule,
    SelectionSpec,
    StrategySpec,
    UniverseSpec,
    WeightingRule,
    WeightingSpec,
)

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
    kr = {"market": "KOSPI", "currency": "KRW"}
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


def test_get_prices_picks_latest_source(repo: SqlRepository) -> None:
    d = date(2026, 9, 1)
    repo.upsert_prices([_bar("A", d, 10.0, "yfinance", AT), _bar("A", d, 10.1, "tiingo", LATER)])
    frame, meta = repo.get_prices(["A"], d, d)
    assert frame.loc[pd.Timestamp(d), "A"] == 10.1 and meta.source == "TIINGO"
    repo.upsert_prices([_bar("A", d, 10.05, "CONSENSUS", AT)])  # 보정 행이 있으면 그것을 씀
    frame, meta = repo.get_prices(["A"], d, d)
    assert frame.loc[pd.Timestamp(d), "A"] == 10.05 and meta.source == "CONSENSUS"


def test_kr_prices_and_assets(repo: SqlRepository) -> None:
    kr = ["005930.KS", "000660.KS"]
    bars = _bars(kr, date(2026, 9, 1), date(2026, 9, 30))
    assert {b.currency for b in bars} == {"KRW"}
    repo.upsert_prices(bars)
    frame, meta = repo.get_prices(kr, date(2026, 9, 1), date(2026, 9, 30))
    pd.testing.assert_frame_equal(frame, _expected(kr, date(2026, 9, 1), date(2026, 9, 30)))
    assert meta.currency == "KRW" and price_frame_problems(frame) == []
    a = {x.asset_id: x for x in repo.get_assets(kr)}
    assert a["KR-005930"].market == "KOSPI" and a["KR-005930"].kis_ticker == "005930"
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


def _profile() -> UserProfile:
    return UserProfile(
        profile_id="demo-001",
        investment_amount_krw=30_000_000,
        horizon_months=36,
        risk_type_computed=RiskType.NEUTRAL,
        risk_type=RiskType.NEUTRAL,
        risk_type_overridden=False,
        loss_tolerance_pct=30,
        interest_industries=["AI", "반도체"],
    )


def _spec() -> StrategySpec:
    return StrategySpec(
        spec_id="demo-lowvol-ivol",
        name="AI 관련 저변동성 5종목, 변동성 역가중",
        universe=UniverseSpec(),
        selection=SelectionSpec(
            rule=SelectionRule.LOW_VOL_TOP_N, params={"n": 5, "lookback_days": 252}
        ),
        weighting=WeightingSpec(rule=WeightingRule.INVERSE_VOL, params={"lookback_days": 252}),
        constraints=ConstraintSpec(max_weight_all=0.25, max_weight_per_ticker={"NVDA": 0.15}),
        period_years=5,
        benchmark="SPY",
    )


def _report(run_id: str) -> Report:
    pm = PerformanceMetrics(
        total_return=0.5,
        cagr=0.08,
        ann_volatility=0.2,
        sharpe=0.4,
        mdd=-0.3,
        mdd_peak=date(2022, 1, 3),
        mdd_trough=date(2022, 10, 12),
    )
    data = ReportData(
        run_id=run_id,
        created_at=AT,
        profile=_profile(),
        spec=_spec(),
        spec_hash=_spec().spec_hash(),
        allocation_as_of=date(2026, 9, 30),
        allocation=[],
        metrics=MetricsBundle(strategy=pm, benchmark=pm, excess_total_return=0.0, excess_cagr=0.0),
        conditions=CalcConditions(
            start=date(2021, 9, 30),
            end=date(2026, 9, 30),
            rebalance="Q",
            benchmark="SPY",
            cost_bps=10.0,
            risk_free_annual=0.0,
            initial_capital_usd=21_000.0,
            fx_rate_krw_per_usd=1390.0,
            fx_as_of=date(2026, 9, 30),
        ),
        evidence=[],
        limitations=["KO 데이터 부족으로 제외"],
        process_summary=[
            StepRecord(run_id=run_id, step="fetch_prices", status=StepStatus.SUCCESS, started_at=AT)
        ],
    )
    return Report(
        data=data, text_markdown="# 리포트", display_values={"metrics.strategy.cagr": "8.00%"}
    )


def test_run_artifact_steps_report(repo: SqlRepository) -> None:
    run_id = "20261001-000000-abcdef"
    universe = UniverseResult(
        tickers=["MSFT", "NVDA"],
        snapshot_dates={IndexCode.SP500: date(2026, 9, 18)},
        criteria={"industries": ["AI"]},
        excluded={},
        source="TEST",
    )
    with pytest.raises(RepositoryError) as e:  # run_artifact 없이 Report 저장 불가
        repo.save_report(_report(run_id))
    assert e.value.code == "REPO_WRITE_FAILED"

    repo.save_run_artifact(run_id, _profile(), _spec(), universe, AppConfig())
    art = repo.get_run_artifact(run_id)
    assert art is not None and art["spec_hash"] == _spec().spec_hash()
    assert art["universe"]["tickers"] == ["MSFT", "NVDA"] and art["created_at"] == AT

    started = StepRecord(
        run_id=run_id, step="fetch_prices", status=StepStatus.STARTED, started_at=AT
    )
    repo.save_step(
        StepRecord(
            run_id=run_id,
            step="load_profile",
            status=StepStatus.SUCCESS,
            started_at=datetime(2026, 9, 30, tzinfo=UTC),
        )
    )
    repo.save_step(started)
    done = started.model_copy(
        update={
            "status": StepStatus.PARTIAL,
            "ended_at": LATER,
            "sources": ["TEST"],
            "summary": "52/55",
        }
    )
    repo.save_step(done)
    assert repo.get_steps(run_id) == [
        StepRecord(
            run_id=run_id,
            step="load_profile",
            status=StepStatus.SUCCESS,
            started_at=datetime(2026, 9, 30, tzinfo=UTC),
        ),
        done,
    ]

    report = _report(run_id)
    repo.save_report(report)
    repo.save_report(report)  # 다시 저장해도 하나
    assert repo.get_report(run_id) == report
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
    from myfinsight.data.repository import default_db_url

    assert default_db_url() == "sqlite:///data/myfinsight.db"
    monkeypatch.setenv("DATABASE_URL", "postgresql+pg8000://u:p@h:5432/db")
    assert default_db_url() == "postgresql+pg8000://u:p@h:5432/db"


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


def test_appendix_b_tables_and_columns_kept() -> None:
    """부록 B 의 테이블·칸 이름·기본키는 그대로 있고, 추가 칸만 더해짐."""
    appendix_b = {
        "price_daily": (
            ["ticker", "date", "adj_close", "volume", "currency", "source", "fetched_at"],
            ["ticker", "date", "source"],
        ),
        "fx_daily": (["pair", "date", "rate", "source", "fetched_at"], ["pair", "date", "source"]),
        "index_constituent": (
            [
                "index_code",
                "snapshot_date",
                "ticker",
                "name",
                "sector",
                "industry",
                "source",
                "fetched_at",
            ],
            ["index_code", "snapshot_date", "ticker"],
        ),
        "fetch_log": (
            ["id", "source", "target", "start_date", "end_date", "status", "fetched_at", "error"],
            ["id"],
        ),
        "run_step": (
            [
                "run_id",
                "step",
                "status",
                "started_at",
                "ended_at",
                "summary",
                "sources_json",
                "error_code",
                "error_message",
            ],
            ["run_id", "step"],
        ),
        "run_artifact": (
            [
                "run_id",
                "created_at",
                "profile_json",
                "spec_json",
                "spec_hash",
                "universe_json",
                "config_json",
            ],
            ["run_id"],
        ),
        "report": (["run_id", "created_at", "data_json", "text_markdown"], ["run_id"]),
    }
    for name, (cols, pk) in appendix_b.items():
        table = T.metadata.tables[name]
        assert [c.name for c in table.columns][: len(cols)] == cols, name
        assert [c.name for c in table.primary_key.columns] == pk, name
    assert set(T.metadata.tables) - set(appendix_b) == {
        "data_sources",
        "assets",
        "financials",
        "news",
        "extra_ticker",
    }


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
    assert r.upsert_news([_news("https://x/1", "t")]) == 0  # 예전 행과 같은 기사
    assert repo_news_count(r) == 1
    r.engine.dispose()


def repo_news_count(r: SqlRepository) -> int:
    with r.engine.connect() as c:
        return c.execute(select(func.count()).select_from(T.news)).scalar_one()
