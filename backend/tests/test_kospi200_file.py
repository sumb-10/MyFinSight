"""KOSPI200 고정 파일 출처: KRX 표 변환, 파일 읽기, 지수별 출처 나누기, 수집기 저장."""

from __future__ import annotations

from datetime import UTC, date, datetime

import pytest

from backend.collectors.constituents.collector import ConstituentCollector, RefreshStatus
from backend.collectors.constituents.source import (
    FileConstituentSource,
    RoutedConstituentSource,
    kospi200_rows_from_table,
    kr_symbol,
)
from backend.db import open_repository
from backend.schemas.errors import DataSourceError
from backend.schemas.market import IndexCode

AT = datetime(2026, 10, 1, 9, 0, tzinfo=UTC)
SECTORS = {"005930.KS": ("Technology", "Consumer Electronics"), "000660.KS": ("", "")}


def _write(tmp_path, n: int = 200):  # noqa: ANN001, ANN202
    path = tmp_path / "kospi200.csv"
    lines = ["# KRX 지수구성종목 코스피 200, 2026-06-12", "ticker,name,sector,industry"]
    lines += [f"{i:06d}.KS,종목{i},Financials,Banks" for i in range(1, n + 1)]
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return path


def test_kr_symbol() -> None:
    assert kr_symbol("5930") == "005930.KS"
    assert kr_symbol("005930.ks") == "005930.KS"
    assert kr_symbol(" 000660 ") == "000660.KS"


def test_rows_from_krx_table() -> None:
    table = [
        {"종목코드": "5930", "종목명": "삼성전자", "종가": "70000"},
        {"종목코드": "000660", "종목명": "SK하이닉스", "종가": "1"},
        {"종목코드": "", "종목명": "합계", "종가": ""},
    ]
    rows = kospi200_rows_from_table(table, lambda t: SECTORS.get(t, ("", "")))
    assert [r["ticker"] for r in rows] == ["000660.KS", "005930.KS"]
    samsung = rows[1]
    assert samsung["sector"] == "Information Technology"  # Yahoo → GICS
    assert samsung["name"] == "삼성전자" and samsung["industry"] == "Consumer Electronics"
    with pytest.raises(DataSourceError, match="종목코드"):
        kospi200_rows_from_table([{"코드": "1"}], lambda t: ("", ""))


def test_file_source_reads_csv(tmp_path) -> None:  # noqa: ANN001
    src = FileConstituentSource({IndexCode.KOSPI200: _write(tmp_path)}, clock=lambda: AT)
    rows = src.fetch(IndexCode.KOSPI200)
    assert len(rows) == 200 and rows[0].ticker == "000001.KS"
    assert rows[0].source == "file:config/kospi200.csv (KRX 지수구성종목 코스피 200, 2026-06-12)"
    with pytest.raises(DataSourceError, match="없음"):
        FileConstituentSource({IndexCode.KOSPI200: tmp_path / "x.csv"}).fetch(IndexCode.KOSPI200)
    with pytest.raises(DataSourceError):
        FileConstituentSource().fetch(IndexCode.SP500)


def test_routed_source_and_collector(tmp_path) -> None:  # noqa: ANN001
    class Wiki:
        source_name = "wikipedia"

        def fetch(self, index: IndexCode) -> list:
            raise AssertionError("KOSPI200 은 위키백과로 가면 안 됨")

    routed = RoutedConstituentSource(
        {IndexCode.KOSPI200: FileConstituentSource({IndexCode.KOSPI200: _write(tmp_path)})},
        Wiki(),
    )
    repo = open_repository("sqlite://", clock=lambda: AT)
    r = ConstituentCollector(routed, repo, clock=lambda: AT).update_one(
        IndexCode.KOSPI200, date(2026, 10, 4)
    )
    assert r.status == RefreshStatus.REFRESHED and len(r.rows) == 200
    assert routed.source_name == "krx_file"
    assert repo.fetch_history("constituents:KOSPI200")[0]["source"] == "KRX_FILE"
    # 11월까지는 정기 변경일(12월)이 안 지나 다시 읽지 않음
    again = ConstituentCollector(routed, repo).update_one(IndexCode.KOSPI200, date(2026, 11, 30))
    assert again.status == RefreshStatus.UP_TO_DATE


def test_shipped_krx_file_parses() -> None:
    from pathlib import Path

    import pandas as pd

    path = Path(__file__).resolve().parents[1] / "data" / "config" / "kospi200_krx.csv"
    if not path.exists():
        pytest.skip("backend/data/config/kospi200_krx.csv 없음")
    table = pd.read_csv(path, dtype=str, encoding="cp949").fillna("").to_dict(orient="records")
    rows = kospi200_rows_from_table(table, lambda t: ("", ""))
    assert 198 <= len(rows) <= 202
    by = {r["ticker"]: r["name"] for r in rows}
    assert by["005930.KS"] == "삼성전자" and "0126Z0.KS" in by


def test_ndx_rows_from_etf_holdings_and_file_source(tmp_path) -> None:  # noqa: ANN001
    from backend.collectors.constituents.source import constituent_rows_from_table

    table = [
        {"Fund Ticker": "QQQ", "Holding Ticker": "NVDA ", "Name": "NVIDIA CORP"},
        {"Fund Ticker": "QQQ", "Holding Ticker": "BRK.B", "Name": "X"},
        {"Fund Ticker": "QQQ", "Holding Ticker": "", "Name": "CASH"},
        {"Fund Ticker": "QQQ", "Holding Ticker": "USD CASH", "Name": "현금"},
    ]
    gics = {"NVDA": ("Information Technology", "Semiconductors")}
    rows = constituent_rows_from_table(table, lambda t: gics.get(t, ("", "")), index=IndexCode.NDX)
    assert [r["ticker"] for r in rows] == ["BRK-B", "NVDA"]  # 현금 행은 빠짐
    path = tmp_path / "ndx.csv"
    lines = ["# Nasdaq-100", "ticker,name,sector,industry"]
    lines += [f"T{i:03d},회사{i},Financials,Banks".replace("T", "A") for i in range(100)]
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    src = FileConstituentSource({IndexCode.NDX: path}, name="ndx_file")
    got = src.fetch(IndexCode.NDX)
    assert len(got) == 100 and src.source_name == "ndx_file"


# ---------------------------------------------------------------- GICS (kr_gics.csv)
def test_kr_gics_overlay(tmp_path) -> None:  # noqa: ANN001
    path = tmp_path / "kospi200.csv"
    path.write_text(
        "ticker,name,sector,industry\n"
        "005930.KS,삼성전자,Information Technology,Consumer Electronics\n"
        "999999.KS,없는종목,Industrials,Conglomerates\n",
        encoding="utf-8",
    )
    rows = {
        r.ticker: r
        for r in FileConstituentSource({IndexCode.KOSPI200: path}, clock=lambda: AT).fetch(
            IndexCode.KOSPI200
        )
    }
    s = rows["005930.KS"]  # Yahoo 이름 → kr_gics.csv 의 GICS 이름·코드
    assert (s.sector, s.industry, s.gics_sub_industry_code) == (
        "Information Technology",
        "Technology Hardware, Storage & Peripherals",
        "45202030",
    )
    assert rows["999999.KS"].industry == "Conglomerates"  # 표에 없으면 그대로
    assert rows["999999.KS"].gics_sub_industry_code is None
    raw = FileConstituentSource({IndexCode.KOSPI200: path}, use_kr_gics=False).fetch(
        IndexCode.KOSPI200
    )
    assert {r.industry for r in raw} == {"Consumer Electronics", "Conglomerates"}


def test_default_kospi200_from_krx_file_and_kr_gics() -> None:
    """backend/data/config/kospi200.csv 가 없으면 KRX 원본 + kr_gics.csv 로 (인터넷 없이) 201행 모두 GICS."""
    from backend.collectors.constituents.source import config_file

    if config_file("kospi200.csv").exists():
        pytest.skip("backend/data/config/kospi200.csv 가 있음 (그 파일을 읽음)")
    rows = FileConstituentSource(clock=lambda: AT).fetch(IndexCode.KOSPI200)
    assert len(rows) == 201
    assert all(r.gics_sub_industry_code for r in rows)
    assert rows[0].source.startswith("file:config/kospi200_krx.csv")
    by = {r.ticker: r for r in rows}
    assert by["000660.KS"].industry == "Semiconductors" and by["000660.KS"].name == "SK하이닉스"


def test_collector_reports_unresolved_gics_names(tmp_path) -> None:  # noqa: ANN001
    """GICS 세부산업이 아닌 이름(Banks 는 산업 단계)은 코드 없이 저장하고 PARTIAL·경고로 알림."""
    repo = open_repository("sqlite://", clock=lambda: AT)
    src = FileConstituentSource({IndexCode.KOSPI200: _write(tmp_path)}, use_kr_gics=False)
    r = ConstituentCollector(src, repo, clock=lambda: AT).update_one(
        IndexCode.KOSPI200, date(2026, 10, 4)
    )
    assert r.status == RefreshStatus.REFRESHED and len(r.rows) == 200
    assert r.warnings and "GICS 세부산업을 못 찾은 행 200개" in r.warnings[0]
    log = repo.fetch_history("constituents:KOSPI200")[-1]
    assert log["status"] == "PARTIAL" and "Banks" in log["error"]
    assert all(
        x.gics_sub_industry_code is None for x in repo.latest_constituents(IndexCode.KOSPI200)
    )
