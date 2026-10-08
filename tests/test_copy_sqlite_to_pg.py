"""copy_sqlite_to_pg.py: SQLite 파일 → PostgreSQL 복사 (MYFINSIGHT_TEST_PG_URL 있을 때만)."""

from __future__ import annotations

import importlib.util
import os
from datetime import UTC, date, datetime
from pathlib import Path

import pytest
from helpers import AT, StubPriceAdapter, make_constituents
from sqlalchemy import create_engine, func, select

from myfinsight.data import jobs
from myfinsight.data.jobs import JobSettings
from myfinsight.data.repository import open_repository
from myfinsight.data.repository import tables as T
from myfinsight.schemas.market import IndexCode
from myfinsight.schemas.market_ext import NewsRow

PG_URL = os.environ.get("MYFINSIGHT_TEST_PG_URL", "")
pytestmark = pytest.mark.skipif(not PG_URL, reason="MYFINSIGHT_TEST_PG_URL 없음")

_spec = importlib.util.spec_from_file_location(
    "copy_sqlite_to_pg", Path(__file__).resolve().parents[1] / "scripts" / "copy_sqlite_to_pg.py"
)
copy_mod = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(copy_mod)


def _counts(engine) -> dict[str, int]:  # noqa: ANN001
    with engine.connect() as c:
        return {
            t.name: c.execute(select(func.count()).select_from(t)).scalar_one()
            for t in T.metadata.sorted_tables
        }


def test_copy_all_tables_rerun_and_sequences(tmp_path: Path) -> None:
    src_url = f"sqlite:///{tmp_path / 'local.db'}"
    src = open_repository(src_url, clock=lambda: AT)
    src.save_constituents(make_constituents(IndexCode.SP500, 3))
    s = JobSettings(indices=[IndexCode.SP500], benchmarks=["SPY"], backfill_years=1)
    ads = {
        "ALPACA": StubPriceAdapter(source="ALPACA"),
        "YFINANCE": StubPriceAdapter(source="YFINANCE"),
    }
    jobs.price_step(src, s, adapters=ads, today=date(2026, 10, 1))
    jobs.verify_job(src)  # CONSENSUS 행 (JSON 칸 포함)
    tricky = '쉼표, "따옴표"\n줄바꿈 \\N 그대로'
    src.upsert_news(
        [
            NewsRow(
                asset_id="US-SPY",
                source="GOOGLE_RSS",
                url="https://news.example.com/a?x=1,2",
                title=tricky,
                content="",
                published_at=datetime(2026, 9, 30, 12, tzinfo=UTC),
                fetched_at=AT,
            )
        ]
    )
    want = _counts(src.engine)
    assert want["price_daily"] > 0 and want["fetch_log"] > 0

    eng = create_engine(PG_URL)
    T.metadata.drop_all(eng)
    copy_mod.copy_all(src_url, PG_URL, batch=100, log=lambda *_: None)
    assert _counts(eng) == want
    copy_mod.copy_all(src_url, PG_URL, batch=100, log=lambda *_: None)  # 다시 돌려도 그대로
    assert _counts(eng) == want

    with eng.connect() as c:
        title, content = c.execute(select(T.news.c.title, T.news.c.content)).one()
        assert (title, content) == (tricky, "")
        q = select(T.price_daily).where(T.price_daily.c.source == "CONSENSUS").limit(1)
        row = c.execute(q).mappings().one()
        assert row["verify_status"] == "VERIFIED" and row["fetched_at"].tzinfo is not None
    dst = open_repository(PG_URL, clock=lambda: AT)
    before = want["fetch_log"]
    jobs.price_step(dst, s, adapters=ads, today=date(2026, 10, 2))  # 자동 번호가 이어져야 저장됨
    assert _counts(eng)["fetch_log"] > before
    dst.engine.dispose()
    eng.dispose()
