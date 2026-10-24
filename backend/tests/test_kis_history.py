"""한국 2015년 전 재무 보충 (collectors/financials/kis_history.py): KIS 연간 재무 → financials_source,
공시일 규칙(사업보고서 최초 접수일, 2010년까지는 기말+150일 이상), 이어 받기, 가치평가의 EPS·BPS 경로.

네트워크 없이: KIS 응답은 스텁 함수, DB 는 인메모리 SQLite.
"""

from __future__ import annotations

from datetime import UTC, date, datetime

import pandas as pd
import pytest
from helpers import AT

from backend.collectors.common import Forever, JobSettings
from backend.collectors.financials.kis_history import (
    BPS_CUR,
    EPS_CUR,
    disclosed_on,
    kis_financial_backfill,
    kis_rows,
)
from backend.db import SqlRepository, open_repository
from backend.db import tables as T
from backend.pipeline.valuation import compute_asset
from backend.schemas.market_ext import DisclosureRow

KIS_2008 = {"sale_account": "1212943.00", "bsop_prti": "60319.00", "thtr_ntin": "58902.00",
            "total_aset": "1053007.00", "total_lblt": "423767.00", "total_cptl": "629240.00",
            "eps": "650.00", "bps": "7913.00", "depr_cost": "99.99"}  # fmt: skip


@pytest.fixture
def repo() -> SqlRepository:
    return open_repository("sqlite://", clock=lambda: AT)


def test_disclosed_rule() -> None:
    # 2010년까지는 연결이 늦게 나와 기말 + 150일보다 이르지 않게, 2011년부터는 사업보고서 접수일
    assert disclosed_on(date(2008, 12, 31), date(2009, 3, 31)) == date(2009, 5, 30)
    assert disclosed_on(date(2008, 12, 31), date(2009, 6, 30)) == date(2009, 6, 30)
    assert disclosed_on(date(2012, 12, 31), date(2013, 3, 29)) == date(2013, 3, 29)
    assert disclosed_on(date(2012, 12, 31), None) == date(2013, 6, 29)  # 보고서 없음: 기말 + 180일


def test_kis_rows_units_and_years() -> None:
    data = {"200812": KIS_2008, "201512": KIS_2008, "202606": KIS_2008}
    rows = kis_rows("005930.KS", data, {"200812": date(2009, 3, 31)}, AT)
    assert {r.period for r in rows} == {"FY200812"}  # 2015년부터는 DART
    by = {r.metric: r for r in rows}
    assert by["매출액"].value == 1212943 * 1e8 and by["매출액"].unit == "원"
    assert by[EPS_CUR].value == 650.0 and by[BPS_CUR].value == 7913.0
    assert by["자본총계"].disclosed_at == date(2009, 5, 30) and by["자본총계"].source == "KIS_FIN"
    assert "depr_cost" not in by and len(rows) == 8


def test_backfill_uses_report_dates_and_resumes(repo: SqlRepository) -> None:
    s = JobSettings(indices=[], benchmarks=[], extra_tickers={"005930.KS": "삼성전자"})
    calls: list[str] = []

    def fetch(code: str) -> dict:
        calls.append(code)
        return {"201212": KIS_2008}

    # 공시 테이블의 사업보고서 최초 접수일 (정정 공시는 무시)
    from backend.collectors.disclosures.update import targets

    targets(repo, s, "KR")
    filed = [
        ("2013-04-01", "사업보고서 (2012.12)", False),
        ("2013-07-01", "[기재정정]사업보고서 (2012.12)", True),
    ]
    repo.upsert_disclosures([
        DisclosureRow(asset_id="KR-005930", source="DART", filing_id=f"r{i}", form="사업보고서",
                      title=title, filed_at=datetime.fromisoformat(d).replace(tzinfo=UTC),
                      available_on=date.fromisoformat(d), is_amendment=amend, fetched_at=AT)
        for i, (d, title, amend) in enumerate(filed)
    ])  # fmt: skip
    assert repo.annual_report_dates(["KR-005930"]) == {"KR-005930": {"201212": date(2013, 4, 1)}}
    r = kis_financial_backfill(repo, s, fetch=fetch, deadline=Forever())
    assert r.counts["rows"] == 8 and calls == ["005930"]
    with repo.engine.connect() as c:
        disc = c.execute(T.financials_source.select()).all()
    assert {x.disclosed_at for x in disc} == {date(2013, 4, 1)}
    kis_financial_backfill(repo, s, fetch=fetch, deadline=Forever())
    assert calls == ["005930"]  # 이미 받은 종목은 건너뜀


def test_valuation_uses_current_basis_eps_bps() -> None:
    prices = pd.DataFrame({
        "date": [date(2009, 5, 29), date(2009, 6, 1), date(2009, 6, 2)],
        "close": [10000.0, 10000.0, 9750.0],
        "fetched_at": [AT] * 3,
    })  # fmt: skip
    fins = pd.DataFrame([
        {"item": EPS_CUR, "period_end": date(2008, 12, 31), "period": "FY200812", "value": 650.0,
         "report_date": date(2009, 6, 1)},
        {"item": BPS_CUR, "period_end": date(2008, 12, 31), "period": "FY200812", "value": 7800.0,
         "report_date": date(2009, 6, 1)},
    ])  # fmt: skip
    rows = compute_asset(prices, fins, asset_id="KR-005930", ticker="005930.KS", currency="KRW")
    assert rows[0]["per"] is None and rows[0]["pbr"] is None  # 공시일 전에는 없음 (선견 금지)
    assert rows[1]["per"] == pytest.approx(10000 / 650) and rows[1]["pbr"] == pytest.approx(
        10000 / 7800
    )
    assert rows[2]["eps_ttm"] == 650.0 and rows[2]["bps"] == 7800.0
    assert "PER=EPS@KIS_FIN" in rows[1]["method"] and "PBR=BPS@KIS_FIN" in rows[1]["method"]
