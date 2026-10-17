"""M02-05 구성종목 수집기: 정기 변경일, 결과 검사, 갱신·미갱신·실패 분기, 위키백과 표 해석."""

from __future__ import annotations

from datetime import UTC, date, datetime

import pytest
from helpers import StubConstituentSource
from stub_http import StubResponse, StubSession

from backend.adapters.crawlers import wikipedia_client
from backend.collectors.constituents.collector import (
    ConstituentCollector,
    RefreshStatus,
    last_rebalance_date,
    needs_refresh,
    third_friday,
    validate_constituents,
)
from backend.collectors.constituents.source import WikipediaConstituentSource
from backend.db import open_repository
from backend.schemas.errors import DataSourceError
from backend.schemas.market import IndexCode

AT = datetime(2026, 10, 1, tzinfo=UTC)
SIZES = {IndexCode.SP500: 20, IndexCode.NDX: 12, IndexCode.KOSPI200: 8}
SMALL = {IndexCode.SP500: (20, 20), IndexCode.NDX: (12, 12)}  # 테스트 출처 행 수에 맞춘 범위


def Source(**kw):  # noqa: ANN003, ANN201, N802
    return StubConstituentSource(SIZES, **kw)


def test_third_friday() -> None:
    assert third_friday(2026, 9) == date(2026, 9, 18)
    assert third_friday(2026, 3) == date(2026, 3, 20)
    assert third_friday(2026, 5) == date(2026, 5, 15)  # 1일이 금요일인 달


@pytest.mark.parametrize(
    ("today", "want"),
    [
        (date(2026, 9, 18), date(2026, 9, 18)),
        (date(2026, 9, 17), date(2026, 6, 19)),
        (date(2026, 10, 3), date(2026, 9, 18)),
        (date(2026, 1, 10), date(2025, 12, 19)),
        (date(2026, 3, 19), date(2025, 12, 19)),
        (date(2026, 3, 20), date(2026, 3, 20)),
    ],
)
def test_last_rebalance_date(today: date, want: date) -> None:
    assert last_rebalance_date(today) == want


def test_needs_refresh() -> None:
    today = date(2026, 10, 3)
    assert needs_refresh(None, today)
    assert needs_refresh(date(2026, 9, 17), today)
    assert not needs_refresh(date(2026, 9, 18), today)


def test_validate_rules() -> None:
    rows = Source().fetch(IndexCode.SP500)
    assert validate_constituents(IndexCode.SP500, rows, row_bounds=SMALL) == []
    assert "행 수 20" in validate_constituents(IndexCode.SP500, rows)[0]  # 실제 범위 495~510
    bad = [
        *rows,
        rows[0],
        rows[1].model_copy(update={"industry": " "}),
        rows[2].model_copy(update={"ticker": "ZZZ", "sector": "Technology"}),
    ]
    problems = validate_constituents(IndexCode.SP500, bad, row_bounds={IndexCode.SP500: (0, 99)})
    assert any("티커 중복" in p for p in problems)
    assert any("빈 칸" in p for p in problems)
    assert any("GICS 섹터 이름이 아님" in p for p in problems)


def _collector(source, repo, **kw):  # noqa: ANN001, ANN003, ANN202
    return ConstituentCollector(source, repo, clock=lambda: AT, **kw)


def test_refresh_then_up_to_date() -> None:
    repo = open_repository("sqlite://")
    src = Source()
    col = _collector(src, repo, row_bounds=SMALL)
    today = date(2026, 10, 3)
    first = col.update(["SP500", "NDX"], today)
    assert {k: v.status for k, v in first.items()} == {
        IndexCode.SP500: RefreshStatus.REFRESHED,
        IndexCode.NDX: RefreshStatus.REFRESHED,
    }
    assert all(r.snapshot_date == today for r in repo.latest_constituents(IndexCode.SP500))
    again = col.update(["SP500"], date(2026, 12, 17))  # 12월 셋째 금요일(12/18) 전
    assert again[IndexCode.SP500].status == RefreshStatus.UP_TO_DATE
    assert src.calls == [IndexCode.SP500, IndexCode.NDX]
    after = col.update(["SP500"], date(2026, 12, 18))
    assert after[IndexCode.SP500].status == RefreshStatus.REFRESHED
    assert len(repo.fetch_history()) == 3


def test_row_count_violation_not_saved_keeps_old() -> None:
    repo = open_repository("sqlite://")
    _collector(Source(), repo, row_bounds=SMALL).update(["SP500"], date(2026, 6, 20))
    res = _collector(Source(), repo).update_one("SP500", date(2026, 10, 3))  # 실제 범위
    assert res.status == RefreshStatus.KEPT_OLD
    assert res.snapshot_date == date(2026, 6, 20)
    assert "2026-06-20 스냅샷 사용" in res.warnings[0]
    assert repo.latest_constituents(IndexCode.SP500)[0].snapshot_date == date(2026, 6, 20)
    assert repo.fetch_history()[-1]["status"] == "FAILED"


def test_source_error_without_snapshot_raises() -> None:
    repo = open_repository("sqlite://")
    col = _collector(Source(fail_indices=["NDX"]), repo, row_bounds=SMALL)
    with pytest.raises(DataSourceError) as e:
        col.update_one("NDX", date(2026, 10, 3))
    assert e.value.code == "DATA_CONSTITUENTS_UNAVAILABLE"


def test_force_refresh() -> None:
    repo = open_repository("sqlite://")
    src = Source()
    col = _collector(src, repo, row_bounds=SMALL)
    col.update_one("SP500", date(2026, 10, 3))
    col.update_one("SP500", date(2026, 10, 4), force=True)
    assert len(src.calls) == 2
    assert repo.latest_constituents(IndexCode.SP500)[0].snapshot_date == date(2026, 10, 4)


SP_HTML = """<html><body>
<table class="wikitable" id="constituents"><tbody>
<tr><th>Symbol</th><th>Security</th><th>GICS Sector</th><th>GICS Sub-Industry</th><th>Headquarters Location</th></tr>
<tr><td><a href="x">MMM</a></td><td><a>3M</a></td><td>Industrials</td><td>Industrial Conglomerates</td><td>Saint Paul</td></tr>
<tr><td>BRK.B</td><td>Berkshire Hathaway<sup class="reference">[5]</sup></td><td>Financials</td><td>Multi-Sector Holdings</td><td>Omaha</td></tr>
<tr><td>NVDA</td><td>Nvidia</td><td>Information Technology</td><td>Semiconductors</td><td>Santa Clara</td></tr>
</tbody></table>
<table id="changes"><tr><th>Date</th></tr><tr><td>2026</td></tr></table>
</body></html>"""

NDX_HTML = """<table id="constituents">
<tr><th>Ticker</th><th>Company</th><th>ICB Industry</th><th>ICB Subsector</th></tr>
<tr><td>NVDA</td><td>Nvidia</td><td>Technology</td><td>Semiconductors</td></tr>
<tr><td>ASML</td><td>ASML Holding</td><td>Technology</td><td>Semiconductors</td></tr>
<tr><td>XYZ</td><td>Unknown Co</td><td>Technology</td><td>Software</td></tr>
</table>"""


def _session() -> StubSession:
    def handler(url, kw):  # noqa: ANN001, ANN202
        html = SP_HTML if url == wikipedia_client.SP500_URL else NDX_HTML
        return StubResponse(content=html.encode())

    return StubSession(handler)


def test_parse_table_footnotes_and_other_tables() -> None:
    rows = wikipedia_client.parse_table(SP_HTML)
    assert [r["Symbol"] for r in rows] == ["MMM", "BRK.B", "NVDA"]
    assert rows[1]["Security"] == "Berkshire Hathaway"


def test_wikipedia_sp500() -> None:
    src = WikipediaConstituentSource(session=_session(), clock=lambda: AT)
    rows = src.fetch(IndexCode.SP500)
    assert [(r.ticker, r.sector, r.industry) for r in rows] == [
        ("BRK-B", "Financials", "Multi-Sector Holdings"),
        ("MMM", "Industrials", "Industrial Conglomerates"),
        ("NVDA", "Information Technology", "Semiconductors"),
    ]
    assert rows[0].source.startswith("wikipedia:S&P 500 https://")
    assert rows[0].fetched_at == AT


def test_wikipedia_ndx_gics_lookup(tmp_path) -> None:  # noqa: ANN001
    overrides = tmp_path / "gics.csv"
    overrides.write_text(
        "ticker,sector,industry\nASML,Information Technology,Semiconductor Materials & Equipment\n",
        encoding="utf-8",
    )
    src = WikipediaConstituentSource(session=_session(), overrides_csv=overrides, clock=lambda: AT)
    rows = {r.ticker: r for r in src.fetch(IndexCode.NDX)}
    assert rows["NVDA"].industry == "Semiconductors"  # S&P 500 표에서
    assert rows["ASML"].industry == "Semiconductor Materials & Equipment"  # 보충표에서
    assert rows["XYZ"].sector == ""  # 못 찾음 → 결과 검사에서 걸림
    problems = validate_constituents(
        IndexCode.NDX, list(rows.values()), row_bounds={IndexCode.NDX: (3, 3)}
    )
    assert problems == ["sector·industry 빈 칸 1개: ['XYZ']"]


def test_default_overrides_file_loads() -> None:
    from backend.collectors.constituents.source import load_gics_overrides

    table = load_gics_overrides()
    assert table["ASML"][0] == "Information Technology"


@pytest.mark.parametrize(
    ("today", "want"),
    [
        (date(2026, 6, 12), date(2026, 6, 12)),  # 6월 둘째 목요일 6/11 다음 날
        (date(2026, 6, 11), date(2025, 12, 12)),  # 2025-12 둘째 목요일 12/11 다음 날
        (date(2026, 10, 3), date(2026, 6, 12)),
        (date(2026, 12, 11), date(2026, 12, 11)),  # 2026-12 둘째 목요일 12/10 다음 날
    ],
)
def test_kospi200_rebalance(today: date, want: date) -> None:
    assert last_rebalance_date(today, IndexCode.KOSPI200) == want


def test_kospi200_flow() -> None:
    repo = open_repository("sqlite://")
    bounds = {IndexCode.KOSPI200: (8, 8)}
    col = _collector(Source(), repo, row_bounds=bounds)
    res = col.update_one("KOSPI200", date(2026, 10, 3))
    assert res.status == RefreshStatus.REFRESHED and len(res.rows) == 8
    assert res.rows[0].ticker.endswith(".KS")
    # 9월 셋째 금요일(미국 기준)이 지나도 KOSPI200 은 12월 정기 변경 전이라 다시 받지 않음
    again = col.update_one("KOSPI200", date(2026, 12, 10))
    assert again.status == RefreshStatus.UP_TO_DATE
    kr = {a.asset_id: a for a in repo.get_assets()}
    assert kr["KR-000010"].name == "종목 1" and kr["KR-000010"].currency == "KRW"


def test_wikipedia_rejects_kospi200() -> None:
    src = WikipediaConstituentSource(session=_session(), clock=lambda: AT)
    with pytest.raises(DataSourceError):
        src.fetch(IndexCode.KOSPI200)


def test_parse_table_without_id_uses_header() -> None:
    html = NDX_HTML.replace('<table id="constituents">', '<table class="wikitable sortable">')
    html = '<table id="infobox"><tr><th>Exchange</th></tr><tr><td>Nasdaq</td></tr></table>' + html
    assert wikipedia_client.parse_table(html) == []  # id 로만 찾으면 없음
    rows = wikipedia_client.parse_table(html, needs=("Ticker", "Company"))
    assert [r["Ticker"] for r in rows] == ["NVDA", "ASML", "XYZ"]


def test_parse_table_nested_in_layout_table() -> None:
    inner = NDX_HTML.replace('<table id="constituents">', '<table class="wikitable">')
    html = f'<table class="layout"><tr><td>{inner}</td></tr></table>'
    rows = wikipedia_client.parse_table(html, needs=("ticker", "company"))
    assert [r["Ticker"] for r in rows] == ["NVDA", "ASML", "XYZ"]
