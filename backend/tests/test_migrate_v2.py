"""backend/scripts/migrate_v2.py: v1 스키마 DB → 새 데이터 계약(v2). SQLite 파일로 돌고,
MYFINSIGHT_TEST_PG_URL 이 있으면 PostgreSQL 에서도 한 번 더 (테이블을 지우니 테스트 전용 DB 로).

v1 DB 는 backend/tests/v1_schema.py (예전 테이블 정의 고정본) 로 만든다.
"""

from __future__ import annotations

import importlib.util
import os
from datetime import UTC, date, datetime
from pathlib import Path

import pytest
import v1_schema as V1
from sqlalchemy import create_engine, func, insert, inspect, select, text

from backend.db import open_repository
from backend.db import tables as T
from backend.schemas.errors import RepositoryError
from backend.schemas.market import IndexCode

_spec = importlib.util.spec_from_file_location(
    "migrate_v2", Path(__file__).resolve().parents[1] / "scripts" / "migrate_v2.py"
)
mig = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(mig)

AT = datetime(2026, 10, 1, tzinfo=UTC)
LATER = datetime(2026, 10, 2, tzinfo=UTC)
D1, D2 = date(2026, 9, 29), date(2026, 9, 30)
PG_URL = os.environ.get("MYFINSIGHT_TEST_PG_URL", "")
BACKENDS = [
    "sqlite",
    pytest.param(
        "postgresql", marks=pytest.mark.skipif(not PG_URL, reason="MYFINSIGHT_TEST_PG_URL 없음")
    ),
]


def _drop_everything(url: str) -> None:
    eng = create_engine(url)
    with eng.begin() as c:
        for name in reversed(inspect(c).get_table_names()):
            c.execute(text(f'DROP TABLE IF EXISTS "{name}" CASCADE'))
    eng.dispose()


def _asset(asset_id: str, ticker: str, market: str, cur: str, sym: str) -> dict:
    return {
        "asset_id": asset_id, "ticker": ticker, "name": ticker, "market": market,
        "asset_type": "STOCK", "currency": cur, "yfinance_symbol": sym,
        "created_at": AT, "updated_at": AT,
    }  # fmt: skip


def _price(sym: str, aid: str, d: date, src: str, adj: float, **kw: object) -> dict:
    row = {
        "ticker": sym, "date": d, "adj_close": adj, "close": adj, "volume": 10,
        "currency": "KRW" if sym.endswith(".KS") else "USD", "source": src,
        "fetched_at": AT, "asset_id": aid, "open": None, "verify_status": None,
        "source_count": None, "outlier_sources": None,
    }  # fmt: skip
    row.update(kw)  # executemany 는 첫 행의 칸만 쓰므로 모든 행이 같은 칸을 갖게
    return row


def _fin(aid: str, src: str, period: str, fs_div: str, metric: str, value: float, **kw) -> dict:  # noqa: ANN003
    row = {
        "asset_id": aid, "source": src, "period": period, "fs_div": fs_div, "metric": metric,
        "value": value, "unit": "KRW", "period_end": date(2025, 12, 31),
        "disclosed_at": date(2026, 3, 10), "fetched_at": AT,
    }  # fmt: skip
    row.update(kw)
    return row


def make_v1_db(url: str, *, fx_duplicate: bool = False) -> None:
    """예전 스키마로 만들고 대표 행을 넣는다."""
    if url.startswith("postgresql"):
        _drop_everything(url)
    eng = create_engine(url)
    V1.metadata.create_all(eng)
    t = V1.metadata.tables
    with eng.begin() as c:
        c.execute(
            insert(t["data_sources"]),
            [
                {"source_name": n, "type": "QUANT"}
                for n in ("YFINANCE", "KIS", "ALPACA", "CONSENSUS", "DART", "SEC_EDGAR", "TEST")
            ],
        )
        c.execute(
            insert(t["assets"]),
            [
                _asset("KR-005930", "005930", "KOSPI", "KRW", "005930.KS"),
                _asset("KR-091990", "091990", "KOSDAQ", "KRW", "091990.KQ"),
                _asset("US-MSFT", "MSFT", "US", "USD", "MSFT"),
            ],
        )
        c.execute(
            insert(t["price_daily"]),
            [
                _price("MSFT", "US-MSFT", D1, "YFINANCE", 401.0, fetched_at=LATER),
                _price("MSFT", "US-MSFT", D1, "ALPACA", 400.0, verify_status="VERIFIED"),
                _price("MSFT", "US-MSFT", D1, "CONSENSUS", 400.5, verify_status="MISMATCH",
                       source_count=2, outlier_sources=["YFINANCE"]),
                _price("MSFT", "US-MSFT", D2, "YFINANCE", 402.0, verify_status="SINGLE"),
                _price("005930.KS", "KR-005930", D1, "KIS", 70000.0),
                _price("005930.KS", "KR-005930", D1, "YFINANCE", 69800.0, open=70100.0),
            ],
        )  # fmt: skip
        fx = [
            {"pair": "USDKRW", "date": D1, "rate": 1390.0, "source": "YFINANCE", "fetched_at": AT},
            {"pair": "USDKRW", "date": D2, "rate": 1391.0, "source": "YFINANCE", "fetched_at": AT},
        ]
        if fx_duplicate:
            fx.append({**fx[0], "source": "KIS", "rate": 1389.0})
        c.execute(insert(t["fx_daily"]), fx)
        c.execute(
            insert(t["index_constituent"]),
            [
                {
                    "index_code": code, "snapshot_date": date(2026, 6, 12), "ticker": sym,
                    "name": sym, "sector": "Information Technology", "industry": "Semis",
                    "source": "test", "fetched_at": AT, "asset_id": aid,
                }
                for code, sym, aid in (
                    ("KOSPI200", "005930.KS", "KR-005930"),
                    ("SP500", "MSFT", "US-MSFT"),
                )
            ],
        )  # fmt: skip
        c.execute(
            insert(t["financials"]),
            [
                _fin("KR-005930", "DART", "2025_11011", "OFS", "매출액", 2.0e14),
                _fin("KR-005930", "DART", "2025_11011", "CFS", "매출액", 3.0e14),
                _fin("KR-005930", "DART", "2025_11011", "CFS", "자산총계", 5.0e14),
                _fin("KR-005930", "DART", "2025_11012", "CFS", "매출액", 1.0e14, period_end=None),
            ],
        )
        c.execute(
            insert(t["fetch_log"]),
            [{"source": "YFINANCE", "target": "MSFT", "status": "SUCCESS", "fetched_at": AT}],
        )
        c.execute(
            insert(t["run_artifact"]),
            [
                {
                    "run_id": "old-run", "created_at": AT, "profile_json": {}, "spec_json": {},
                    "spec_hash": "h", "universe_json": {}, "config_json": {},
                }
            ],
        )  # fmt: skip
        c.execute(
            insert(t["run_step"]),
            [{"run_id": "old-run", "step": "fetch", "status": "SKIPPED", "started_at": AT}],
        )
        c.execute(
            insert(t["report"]),
            [
                {
                    "run_id": "old-run", "created_at": AT, "data_json": {"a": 1},
                    "text_markdown": "# 예전", "display_values_json": {},
                }
            ],
        )  # fmt: skip
    eng.dispose()


def _url(backend: str, tmp_path: Path) -> str:
    return f"sqlite:///{tmp_path / 'old.db'}" if backend == "sqlite" else PG_URL


def _snapshot(url: str) -> dict[str, int]:
    eng = create_engine(url)
    with eng.connect() as c:
        out = {
            n: c.execute(text(f'SELECT COUNT(*) FROM "{n}"')).scalar_one()
            for n in inspect(c).get_table_names()
        }
    eng.dispose()
    return out


@pytest.mark.parametrize("backend", BACKENDS)
def test_dry_run_changes_nothing_and_new_code_refuses_v1(backend: str, tmp_path: Path) -> None:
    url = _url(backend, tmp_path)
    make_v1_db(url)
    before = _snapshot(url)
    lines: list[str] = []
    assert mig.run(url, do_apply=False, log=lines.append) == 0
    assert any("price_daily → price_daily_source (6행" in x for x in lines)
    assert any("확인만 함" in x for x in lines)
    assert _snapshot(url) == before
    with pytest.raises(RepositoryError) as e:  # 옮기기 전에는 새 코드가 열지 않음 (섞임 방지)
        open_repository(url)
    assert "migrate_v2" in str(e.value)
    assert _snapshot(url) == before


@pytest.mark.parametrize("backend", BACKENDS)
def test_fx_duplicates_abort_without_changes(backend: str, tmp_path: Path) -> None:
    url = _url(backend, tmp_path)
    make_v1_db(url, fx_duplicate=True)
    before = _snapshot(url)
    lines: list[str] = []
    assert mig.run(url, do_apply=True, log=lines.append) == 1
    assert any("fx_daily 에 같은 (pair, date)" in x for x in lines)
    assert _snapshot(url) == before


@pytest.mark.parametrize("backend", BACKENDS)
def test_failure_midway_rolls_back_everything(
    backend: str, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """채우기 단계에서 실패해도 이름 바꾸기·칸 추가까지 모두 되돌림 (한 트랜잭션)."""
    url = _url(backend, tmp_path)
    make_v1_db(url)
    before = _snapshot(url)

    def boom(*_a: object, **_k: object) -> None:
        raise RuntimeError("채우기 실패")

    monkeypatch.setattr(mig.SqlRepository, "publish_all", boom)
    with pytest.raises(RuntimeError):
        mig.run(url, do_apply=True, log=lambda *_: None)
    assert _snapshot(url) == before
    eng = create_engine(url)
    with eng.connect() as c:
        assert "exchange" not in {col["name"] for col in inspect(c).get_columns("assets")}
    eng.dispose()


@pytest.mark.parametrize("backend", BACKENDS)
def test_apply_migrates_to_contract(backend: str, tmp_path: Path) -> None:
    url = _url(backend, tmp_path)
    make_v1_db(url)
    before = _snapshot(url)
    lines: list[str] = []
    assert mig.run(url, do_apply=True, log=lines.append) == 0, lines
    after = _snapshot(url)

    # 예전 데이터는 이름만 바뀌어 그대로 (지운 행 없음)
    for old, new in (
        ("price_daily", "price_daily_source"),
        ("financials", "financials_source"),
        ("run_step", "run_step_v1"),
        ("run_artifact", "run_artifact_v1"),
        ("report", "report_v1"),
    ):
        assert after[new] == before[old], new
    for name in ("assets", "fx_daily", "index_constituent", "fetch_log", "news"):
        assert after[name] == before[name], name
    assert after["run_step"] == after["run_artifact"] == after["report"] == 0

    eng = create_engine(url)
    with eng.connect() as c:
        insp = inspect(c)
        assert insp.get_pk_constraint("fx_daily")["constrained_columns"] == ["pair", "date"]
        assert insp.get_pk_constraint("price_daily")["constrained_columns"] == ["asset_id", "date"]
        if backend == "postgresql":  # 제약·인덱스 이름도 새 이름으로
            names = set(
                c.execute(
                    text(
                        "SELECT conname FROM pg_constraint "
                        "WHERE conrelid = 'price_daily_source'::regclass"
                    )
                ).scalars()
            )
            assert {"price_daily_source_pkey", "ck_price_daily_source_adj_close"} <= names
            idx = {i["name"] for i in insp.get_indexes("price_daily_source")}
            assert {"idx_price_source_ticker_date", "idx_price_source_unverified"} <= idx
            assert insp.get_unique_constraints("financials_source")[0]["name"] == (
                "uq_financials_source_natural"
            )
        else:
            assert after["fx_daily_v1"] == before["fx_daily"]  # SQLite: 기본키를 못 바꿔 복사본
        a = {
            r.asset_id: (r.market, r.exchange)
            for r in c.execute(select(T.assets.c.asset_id, T.assets.c.market, T.assets.c.exchange))
        }
        assert a == {
            "KR-005930": ("KR", "KOSPI"),
            "KR-091990": ("KR", "KOSDAQ"),
            "US-MSFT": ("US", None),
        }
        ic = T.index_constituent
        tickers = dict(c.execute(select(ic.c.index_code, ic.c.ticker)).all())
        assert tickers == {"KOSPI200": "005930", "SP500": "MSFT"}
        pub = {(r.asset_id, r.date): r for r in c.execute(select(T.price_daily))}
        assert set(pub) == {("US-MSFT", D1), ("US-MSFT", D2), ("KR-005930", D1)}
        msft = pub[("US-MSFT", D1)]  # ALPACA 원본 (CONSENSUS 값 아님) + CONSENSUS 검증 상태
        assert (msft.source, msft.adj_close, msft.verify_status) == ("ALPACA", 400.0, "MISMATCH")
        assert pub[("US-MSFT", D2)].verify_status == "SINGLE"
        kr = pub[("KR-005930", D1)]
        # 한국: 종가·OHLCV 는 KIS 행, 배당까지 보정한 수정종가는 yfinance 값 (칸별 출처)
        assert (kr.source, kr.close, kr.adj_close, kr.adj_close_source, kr.currency) == (
            "KIS",
            70000.0,
            69800.0,
            "YFINANCE",
            "KRW",
        )
        fin = {(r.statement, r.item): r for r in c.execute(select(T.financials))}
        assert set(fin) == {("IS", "매출액"), ("BS", "자산총계")}
        assert (fin[("IS", "매출액")].value, fin[("IS", "매출액")].fs_div) == (3.0e14, "CFS")
        assert fin[("IS", "매출액")].report_date == date(2026, 3, 10)
    eng.dispose()

    # 새 코드로 열고 그대로 쓸 수 있음
    repo = open_repository(url, clock=lambda: AT)
    frame, meta = repo.get_prices(["MSFT"], D1, D2)
    assert frame["MSFT"].tolist() == [400.0, 402.0] and meta.source == "ALPACA+YFINANCE"
    assert [r.ticker for r in repo.latest_constituents(IndexCode.KOSPI200)] == ["005930.KS"]
    assert repo.get_fx_on_or_before(D2).rate == 1391.0
    repo.save_run_artifact("new-run", "req-1", {"ok": True}, {})
    repo.save_report("new-run", {"t": 1}, strategy_name=None, request_summary=None, as_of=D2)
    assert repo.get_report("new-run")["doc"] == {"t": 1}
    with repo.engine.connect() as c:
        n = c.execute(select(func.count()).select_from(T.data_sources)).scalar_one()
    assert n >= len(T.SEED_SOURCES)
    repo.engine.dispose()

    # 다시 돌려도 할 일 없음
    again: list[str] = []
    assert mig.run(url, do_apply=True, log=again.append) == 0
    assert any("v1 스키마가 아님" in x for x in again)

    # 우선순위를 바꾼 뒤 --republish: 계약 price_daily 를 원본에서 다시 고름
    with pytest.MonkeyPatch.context() as mp:
        mp.setenv("PRICE_PRIORITY_US", "YFINANCE,ALPACA")
        assert mig.run(url, do_apply=True, republish=True, log=again.append) == 0
    eng = create_engine(url)
    with eng.connect() as c:
        p = T.price_daily
        row = c.execute(
            select(p.c.source, p.c.adj_close).where(p.c.date == D1, p.c.asset_id == "US-MSFT")
        ).one()
    eng.dispose()
    assert tuple(row) == ("YFINANCE", 401.0)


@pytest.mark.parametrize("backend", BACKENDS)
def test_v2_db_gets_new_tables(backend: str, tmp_path: Path) -> None:
    """v2 DB 에 새 테이블(valuation_daily)이 없으면: 확인만 하면 그대로, --apply 면 만듦."""
    url = _url(backend, tmp_path)
    if backend == "postgresql":
        _drop_everything(url)
    open_repository(url, clock=lambda: AT).engine.dispose()
    eng = create_engine(url)
    with eng.begin() as c:
        c.execute(text("DROP TABLE valuation_daily"))
    eng.dispose()

    lines: list[str] = []
    assert mig.run(url, do_apply=False, log=lines.append) == 0
    assert any("valuation_daily" in x for x in lines) and any("--apply" in x for x in lines)
    assert "valuation_daily" not in _snapshot(url)
    assert mig.run(url, do_apply=True, log=lines.append) == 0
    assert any("새 테이블 만듦: valuation_daily" in x for x in lines)
    assert _snapshot(url)["valuation_daily"] == 0
    open_repository(url, clock=lambda: AT).engine.dispose()


NEWS_LABEL_COLS = ["is_press_release", "title_has_name", "story_id", "is_first_report",
                   "available_on"]  # fmt: skip


@pytest.mark.parametrize("backend", BACKENDS)
def test_v4_db_gets_disclosures_and_news_labels(backend: str, tmp_path: Path) -> None:
    """v4 DB (공시 테이블·뉴스 사실 태그 칸 없음): 새 코드는 열지 않고, 확인 실행은 계획만,
    --apply 는 disclosures 를 만들고 news 칸을 더함 (기존 기사는 그대로, 태그는 NULL)."""
    url = _url(backend, tmp_path)
    if backend == "postgresql":
        _drop_everything(url)
    open_repository(url, clock=lambda: AT).engine.dispose()
    eng = create_engine(url)
    with eng.begin() as c:
        c.execute(insert(T.assets).values(**_asset("US-MSFT", "MSFT", "US", "USD", "MSFT")))
        c.execute(
            insert(T.news).values(
                asset_id="US-MSFT", source="GOOGLE_RSS", url="https://x/1", url_hash="h1",
                title="t", published_at=AT, content_hash="c1", fetched_at=AT,
            )
        )  # fmt: skip
        c.execute(text("DROP INDEX IF EXISTS idx_news_asset_story"))  # v4 에는 없던 인덱스
        for col in NEWS_LABEL_COLS:
            c.execute(text(f'ALTER TABLE news DROP COLUMN "{col}"'))
        c.execute(text("DROP TABLE disclosures"))
    eng.dispose()

    with pytest.raises(RepositoryError) as e:
        open_repository(url)
    assert "story_id" in str(e.value)

    lines: list[str] = []
    assert mig.run(url, do_apply=False, log=lines.append) == 0
    assert any("없는 테이블 만들기: disclosures" in x for x in lines)
    assert any("news: 칸 추가 " + ", ".join(NEWS_LABEL_COLS) in x for x in lines)
    assert "disclosures" not in _snapshot(url)

    assert mig.run(url, do_apply=True, log=lines.append) == 0
    eng = create_engine(url)
    with eng.connect() as c:
        assert set(NEWS_LABEL_COLS) <= {x["name"] for x in inspect(c).get_columns("news")}
        row = c.execute(select(T.news)).one()
    eng.dispose()
    assert row.title == "t" and row.story_id is None
    assert _snapshot(url)["disclosures"] == 0
    repo = open_repository(url, clock=lambda: AT)
    repo.engine.dispose()


GICS_ASSET_COLS = [
    "gics_sector_code", "gics_industry_group_code", "gics_industry_code",
    "gics_sub_industry_code", "gics_sub_industry", "gics_source", "gics_updated_at",
    "ksic_code", "business_summary", "business_summary_source",
]  # fmt: skip


def _make_v3_db(url: str) -> None:
    """v3 (GICS 칸이 생기기 전) DB: 지금 코드로 만든 뒤 v4 칸·테이블을 지운다."""
    repo = open_repository(url, clock=lambda: AT)
    repo.engine.dispose()
    eng = create_engine(url)
    with eng.begin() as c:
        c.execute(insert(T.assets).values(**_asset("US-MSFT", "MSFT", "US", "USD", "MSFT")))
        for col in GICS_ASSET_COLS:
            c.execute(text(f'ALTER TABLE assets DROP COLUMN "{col}"'))
        c.execute(text('ALTER TABLE index_constituent DROP COLUMN "gics_sub_industry_code"'))
        c.execute(text("DROP TABLE gics_taxonomy"))
    eng.dispose()


@pytest.mark.parametrize("backend", BACKENDS)
def test_v3_db_gets_gics_columns_and_taxonomy(backend: str, tmp_path: Path) -> None:
    """v3 DB: 새 코드는 열지 않고, 확인 실행은 계획만, --apply 는 칸·분류표를 더함 (멱등)."""
    url = _url(backend, tmp_path)
    if backend == "postgresql":
        _drop_everything(url)
    _make_v3_db(url)

    with pytest.raises(RepositoryError) as e:
        open_repository(url)
    assert "migrate_v2" in str(e.value) and "gics_sector_code" in str(e.value)
    assert "gics_taxonomy" not in _snapshot(url)  # 거절할 때는 아무것도 만들지 않음

    lines: list[str] = []
    assert mig.run(url, do_apply=False, log=lines.append) == 0
    assert any("assets: 칸 추가 gics_sector_code" in x for x in lines)
    assert any("index_constituent: 칸 추가 gics_sub_industry_code" in x for x in lines)
    assert any("gics_taxonomy: 분류표 파일과 다른 행 273개" in x for x in lines)
    assert any("확인만 함" in x for x in lines)
    eng = create_engine(url)
    with eng.connect() as c:
        assert "gics_sector_code" not in {x["name"] for x in inspect(c).get_columns("assets")}
    eng.dispose()

    lines = []
    assert mig.run(url, do_apply=True, log=lines.append) == 0, lines
    assert any(x.startswith("칸 추가: assets (") for x in lines)
    assert any("gics_taxonomy: 273행" in x for x in lines)
    eng = create_engine(url)
    with eng.connect() as c:
        cols = {x["name"] for x in inspect(c).get_columns("assets")}
        assert set(GICS_ASSET_COLS) <= cols
        n = c.execute(select(func.count()).select_from(T.gics_taxonomy)).scalar_one()
        msft = c.execute(select(T.assets).where(T.assets.c.asset_id == "US-MSFT")).one()
    eng.dispose()
    assert n == 273 and msft.ticker == "MSFT" and msft.gics_sector_code is None

    again: list[str] = []
    assert mig.run(url, do_apply=True, log=again.append) == 0
    assert any("할 일 없음" in x for x in again)
    repo = open_repository(url, clock=lambda: AT)
    assert len(repo.gics_taxonomy_rows()) == 273
    repo.engine.dispose()


@pytest.mark.parametrize("backend", BACKENDS)
def test_taxonomy_change_is_planned_and_applied(backend: str, tmp_path: Path) -> None:
    """분류표 파일과 DB 행이 다르면 (이름을 고친 경우) 그 행만 바꿈."""
    url = _url(backend, tmp_path)
    if backend == "postgresql":
        _drop_everything(url)
    open_repository(url, clock=lambda: AT).engine.dispose()
    eng = create_engine(url)
    with eng.begin() as c:
        c.execute(text("UPDATE gics_taxonomy SET name_ko = 'x' WHERE code IN ('45', '45301020')"))
    eng.dispose()
    lines: list[str] = []
    assert mig.run(url, do_apply=False, log=lines.append) == 0
    assert any("다른 행 2개" in x for x in lines)
    assert mig.run(url, do_apply=True, log=lines.append) == 0
    assert any("gics_taxonomy: 2행" in x for x in lines)
