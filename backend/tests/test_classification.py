"""종목별 GICS 정하기 (classification.gics_step): 출처 순서, 한국 종목, 저장, 구성종목 행 채우기,
coverage_report 의 GICS 표. 네트워크 없이 스텁 KSIC·프로필 함수로 (SQLite, PG_URL 이 있으면 PG 도).
"""

from __future__ import annotations

import os
import sys
from datetime import date
from pathlib import Path

import pytest
from helpers import AT
from sqlalchemy import create_engine, select

from backend.collectors.common import Deadline, JobSettings  # noqa: E402
from backend.db import SqlRepository, open_repository
from backend.db import tables as T
from backend.jobs.daily import run_gics  # noqa: E402
from backend.pipeline.classification import (
    Src,
    assign_gics,
    gics_step,
    load_kr_gics,
    load_ksic_map,
    resolve_row,
)
from backend.pipeline.gics import load_taxonomy
from backend.schemas.market import IndexCode, IndexConstituent

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
import coverage_report  # noqa: E402

TODAY = date(2026, 10, 1)
PG_URL = os.environ.get("MYFINSIGHT_TEST_PG_URL", "")
TAX = load_taxonomy()


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


def _row(index: IndexCode, ticker: str, sector: str, industry: str, *, d: date, src: str):
    return IndexConstituent(
        index_code=index,
        ticker=ticker,
        name=f"이름 {ticker}",
        sector=sector,
        industry=industry,
        snapshot_date=d,
        source=src,
        fetched_at=AT,
    )


D_OLD, D_NEW = date(2025, 9, 1), date(2026, 9, 18)
WIKI = "wikipedia: List of S&P 500 companies"


def _seed(repo: SqlRepository) -> None:
    sp, ndx, kr = IndexCode.SP500, IndexCode.NDX, IndexCode.KOSPI200
    repo.save_constituents(
        [
            _row(sp, "AAPL", "Information Technology", "Technology Hardware, Storage & Peripherals",
                 d=D_NEW, src=WIKI),
            _row(sp, "JPM", "Financials", "Diversified Banks", d=D_NEW, src=WIKI),
            _row(sp, "ODD", "Energy", "Mystery Business", d=D_NEW, src=WIKI),
        ]
    )  # fmt: skip
    repo.save_constituents(
        [
            _row(ndx, "AAPL", "Information Technology",
                 "Technology Hardware, Storage & Peripherals", d=D_NEW, src="file:config/ndx.csv"),
            _row(ndx, "ASML", "", "", d=D_NEW, src="file:config/ndx.csv"),  # overrides 에 있음
            _row(ndx, "NEWCO", "Information Technology", "Application Software",
                 d=D_NEW, src="file:config/ndx.csv"),
            _row(ndx, "NOPE", "", "", d=D_NEW, src="file:config/ndx.csv"),
        ]
    )  # fmt: skip
    # 예전 한국 스냅샷: Yahoo 섹터·산업 이름 (GICS 와 다름)
    repo.save_constituents(
        [
            _row(kr, "005930.KS", "Information Technology", "Consumer Electronics", d=D_OLD,
                 src="yahoo"),
        ]
    )  # fmt: skip
    repo.save_constituents(
        [
            _row(kr, "005930.KS", "Information Technology",
                 "Technology Hardware, Storage & Peripherals", d=D_NEW, src="file"),
            _row(kr, "068270.KS", "Health Care", "Biotechnology", d=D_NEW, src="file"),
            _row(kr, "999990.KS", "", "", d=D_NEW, src="file"),  # 표에 없음 → KSIC
            _row(kr, "999980.KS", "Industrials", "Conglomerates", d=D_NEW, src="file"),  # 지주
        ]
    )  # fmt: skip


KSIC = {"999990": "26110", "999980": "64992"}


def _settings() -> JobSettings:
    return JobSettings(
        indices=[IndexCode.SP500, IndexCode.NDX, IndexCode.KOSPI200], benchmarks=["SPY"]
    )


class Fetch:
    def __init__(self) -> None:
        self.ksic: list[str] = []
        self.profile: list[str] = []

    def ksic_fetch(self, code: str) -> str | None:
        self.ksic.append(code)
        return KSIC.get(code)

    def profile_fetch(self, sym: str) -> dict:
        self.profile.append(sym)
        if sym == "NOPE":
            return {"summary": "", "sector": "Technology", "source": "YFINANCE"}
        if sym == "ODD":
            raise ConnectionError("stub")
        return {"summary": f"{sym} makes things. More text.", "sector": "", "source": "YFINANCE"}


def _profiles(repo: SqlRepository) -> dict[str, dict]:
    return {p["yfinance_symbol"]: p for p in repo.asset_profiles()}


def test_gics_step_sources_and_storage(repo: SqlRepository) -> None:
    _seed(repo)
    f = Fetch()
    res = gics_step(
        repo, _settings(), today=TODAY, ksic_fetch=f.ksic_fetch, profile_fetch=f.profile_fetch
    )
    p = _profiles(repo)
    want = {
        "AAPL": ("45202030", Src.WIKIPEDIA_SP500),
        "JPM": ("40101010", Src.WIKIPEDIA_SP500),
        "ASML": ("45301010", Src.OVERRIDE),
        "NEWCO": ("45103010", Src.NDX_FILE),
        "005930.KS": ("45202030", Src.KR_MAP_REVIEWED),
        "068270.KS": ("35201010", Src.KR_MAP_DRAFT),
        "999990.KS": ("45301020", Src.KR_MAP_KSIC_AUTO),
    }
    for sym, (code, src) in want.items():
        assert (p[sym]["gics_sub_industry_code"], p[sym]["gics_source"]) == (code, src), sym
        assert p[sym]["gics_sector_code"] == code[:2]
        assert p[sym]["gics_industry_group_code"] == code[:4]
        assert p[sym]["gics_industry_code"] == code[:6]
        assert p[sym]["gics_sub_industry"] == TAX.get(code).name_en
        assert p[sym]["gics_updated_at"] is not None
    # 섹터만: Yahoo 섹터 → GICS, 구성종목 행의 섹터 이름
    assert (p["NOPE"]["gics_sector_code"], p["NOPE"]["gics_source"]) == ("45", Src.YAHOO_FALLBACK)
    assert p["NOPE"]["gics_sub_industry_code"] is None
    assert (p["ODD"]["gics_sector_code"], p["ODD"]["gics_source"]) == ("10", "CONSTITUENT_SP500")
    assert p["999980.KS"]["gics_sector_code"] == "20"  # 지주회사: KSIC 자동 매핑 안 함
    assert p["999980.KS"]["gics_sub_industry_code"] is None
    assert p["999990.KS"]["ksic_code"] == "26110"
    # ETF·벤치마크는 대상 아님
    assert p["SPY"]["gics_source"] is None
    assert "SPY" not in f.profile and "SPY" not in f.ksic
    # KSIC 는 한국 종목에만
    assert sorted(f.ksic) == ["005930", "068270", "999980", "999990"]
    # 사업 설명
    assert p["AAPL"]["business_summary"].startswith("AAPL makes things")
    assert p["AAPL"]["business_summary_source"] == "YFINANCE"
    assert p["NOPE"]["business_summary"] is None
    # 결과·로그: 못 정한 종목과 실패가 이름으로 나옴
    assert {"NOPE", "ODD", "999980.KS", "profile:ODD"} <= set(res.failed)
    assert "세부산업 모름" in res.failed["999980.KS"]
    assert res.counts["assets_with_sub_industry"] == 7
    assert res.counts["assets_sector_only"] == 3
    log = [r for r in repo.fetch_history("gics:assets")]
    assert log and log[-1]["status"] == "PARTIAL" and "NOPE" in (log[-1]["error"] or "")
    assert any("출처별 종목 수" in n for n in res.notes)


def test_gics_step_fills_constituent_rows(repo: SqlRepository) -> None:
    _seed(repo)
    gics_step(repo, _settings(), today=TODAY)
    kr = repo.latest_constituents(IndexCode.KOSPI200)
    codes = {r.ticker: r.gics_sub_industry_code for r in kr}
    assert codes["005930.KS"] == "45202030" and codes["068270.KS"] == "35201010"
    assert codes["999990.KS"] is None  # KSIC 없이 돌림 → 이 종목은 분류 없음
    # 예전 스냅샷의 Yahoo 이름은 종목의 GICS 로 바뀜
    with repo.engine.connect() as conn:
        ic = T.index_constituent
        old = conn.execute(
            select(ic.c.sector, ic.c.industry, ic.c.gics_sub_industry_code).where(
                ic.c.snapshot_date == D_OLD
            )
        ).one()
    assert tuple(old) == (
        "Information Technology",
        "Technology Hardware, Storage & Peripherals",
        "45202030",
    )
    sp = {r.ticker: r.gics_sub_industry_code for r in repo.latest_constituents(IndexCode.SP500)}
    assert sp == {"AAPL": "45202030", "JPM": "40101010", "ODD": None}
    assert repo.constituent_gics_gaps()  # 못 푼 행은 남음 (다음 실행에 다시)


def test_gics_step_is_idempotent_and_keeps_stored_values(repo: SqlRepository) -> None:
    _seed(repo)
    f = Fetch()
    gics_step(
        repo, _settings(), today=TODAY, ksic_fetch=f.ksic_fetch, profile_fetch=f.profile_fetch
    )
    before = _profiles(repo)
    f2 = Fetch()
    res = gics_step(
        repo, _settings(), today=TODAY, ksic_fetch=f2.ksic_fetch, profile_fetch=f2.profile_fetch
    )
    assert res.counts["assets_changed"] == 0 and res.counts["taxonomy_changed"] == 0
    assert res.counts["constituent_rows_filled"] == 0
    # KSIC·사업 설명은 받은 종목을 다시 받지 않음 (못 받은 종목만)
    assert sorted(f2.ksic) == ["005930", "068270"]
    assert sorted(f2.profile) == ["NOPE", "ODD"]
    assert _profiles(repo) == before
    # 이번에 못 정해도 저장된 값은 지우지 않음: KSIC 매핑이 사라진 상황
    gics_step(repo, _settings(), today=TODAY)  # ksic_map 은 그대로, 저장된 ksic_code 로 다시 정함
    assert _profiles(repo)["999990.KS"]["gics_sub_industry_code"] == "45301020"


def test_limits_leave_work_for_next_run(repo: SqlRepository) -> None:
    _seed(repo)
    f = Fetch()
    res = gics_step(
        repo,
        _settings(),
        today=TODAY,
        ksic_fetch=f.ksic_fetch,
        profile_fetch=f.profile_fetch,
        ksic_limit=1,
        profile_limit=2,
    )
    assert len(f.ksic) == 1 and len(f.profile) == 2 and res.done is False


def test_assign_gics_kr_order_and_bad_names() -> None:
    profiles = [
        {"asset_id": "KR-005930", "yfinance_symbol": "005930.KS", "market": "KR",
         "asset_type": "STOCK", "ksic_code": "64992"},
        {"asset_id": "KR-111110", "yfinance_symbol": "111110.KS", "market": "KR",
         "asset_type": "STOCK", "ksic_code": None},
        {"asset_id": "US-X", "yfinance_symbol": "X", "market": "US", "asset_type": "STOCK"},
        {"asset_id": "US-QQQ", "yfinance_symbol": "QQQ", "market": "US", "asset_type": "ETF"},
    ]  # fmt: skip
    cons = {
        IndexCode.KOSPI200: [
            _row(IndexCode.KOSPI200, "111110.KS", "Materials", "Steel", d=D_NEW, src="file")
        ],
        IndexCode.SP500: [
            _row(IndexCode.SP500, "X", "Energy", "Semiconductors", d=D_NEW, src=WIKI)
        ],  # 섹터와 세부산업이 맞지 않음
    }
    found, problems = assign_gics(
        profiles,
        cons,
        tax=TAX,
        kr_map=load_kr_gics(),
        ksic_map=load_ksic_map(),
        overrides={},
    )
    assert found["KR-005930"].source == Src.KR_MAP_REVIEWED  # 표가 KSIC 보다 먼저
    assert (found["KR-111110"].sub_code, found["KR-111110"].source) == (
        "15104050",
        "CONSTITUENT_KOSPI200",
    )
    assert found["US-X"].sub_code is None and found["US-X"].sector_code == "10"
    assert "섹터가 맞지 않음" in problems["US-X"]
    assert "US-QQQ" not in found and "US-QQQ" not in problems


def test_resolve_row() -> None:
    assert resolve_row(TAX, "Information Technology", "Semiconductors") == ("45301020", "")
    assert resolve_row(TAX, "", "Semiconductors") == ("45301020", "")
    code, why = resolve_row(TAX, "Health Care", "Semiconductors")
    assert code is None and "섹터" in why
    code, why = resolve_row(TAX, "Energy", "Oil Stuff")
    assert code is None and "못 찾음" in why


def test_run_gics_without_keys(repo: SqlRepository) -> None:
    _seed(repo)
    res = run_gics(repo, _settings(), today=TODAY, deadline=Deadline(60))
    # 키가 없는 테스트 환경: KSIC 는 건너뛴다는 메모, 분류는 인터넷 없이 됨
    assert any("DART_API_KEY" in n for n in res.notes)
    assert _profiles(repo)["AAPL"]["gics_sub_industry_code"] == "45202030"


def test_coverage_report_gics_section(repo: SqlRepository) -> None:
    _seed(repo)
    gics_step(repo, _settings(), today=TODAY)
    with repo.engine.connect() as conn:
        text = coverage_report.gics_section(conn, TODAY)
    assert "4. GICS 섹터별" in text
    assert "해당 없음" in text  # 금융 섹터(JPM) 매출액 칸
    assert "WIKIPEDIA_SP500" in text and "KR_MAP_REVIEWED" in text
    assert "GICS 세부산업이 없는 종목" in text and "NOPE" in text and "999990.KS" in text
