"""종목 검색용 사전 (descriptor.py, backend/scripts/build_descriptor.py): 버전, 당시 분류, 소개 문장,
키워드, 검색 함수, 파일 쓰기·버전 고르기. DB 만 읽는다."""

from __future__ import annotations

import json
import sys
from datetime import date
from pathlib import Path

import pytest
from helpers import AT

from backend.db import SqlRepository, open_repository
from backend.db.readers import descriptor_inputs, mask_url
from backend.pipeline.descriptor import (
    NOT_AVAILABLE,
    Descriptor,
    build_descriptors,
    default_intro,
    first_sentence,
    josa_eun,
    keywords_for,
    select_version,
    write_descriptors,
)
from backend.pipeline.gics import load_taxonomy
from backend.schemas.market import IndexCode, IndexConstituent

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
import build_descriptor  # noqa: E402

TAX = load_taxonomy()
D1, D2 = date(2025, 3, 1), date(2026, 9, 18)


def _row(index: IndexCode, ticker: str, name: str, industry: str, d: date, code: str | None):
    sector = TAX.chain(code)[0].name_en if code else ""
    return IndexConstituent(
        index_code=index,
        ticker=ticker,
        name=name,
        sector=sector,
        industry=industry,
        snapshot_date=d,
        source="test",
        fetched_at=AT,
        gics_sub_industry_code=code,
    )


def _seed(repo: SqlRepository) -> None:
    sp, kr = IndexCode.SP500, IndexCode.KOSPI200
    repo.save_constituents(
        [
            _row(sp, "NVDA", "NVIDIA Corporation", "Semiconductors", D1, "45301020"),
            _row(sp, "OLD", "Old Co", "Application Software", D1, "45103010"),
        ]
    )
    repo.save_constituents(
        [
            _row(sp, "NVDA", "NVIDIA Corporation", "Semiconductors", D2, "45301020"),
            _row(sp, "JPM", "JPMorgan Chase", "Diversified Banks", D2, None),  # 행에 코드 없음
            _row(sp, "MYST", "Mystery Inc.", "", D2, None),
        ]
    )
    repo.save_constituents(
        [
            _row(kr, "005930.KS", "삼성전자", "Technology Hardware, Storage & Peripherals", D2,
                 "45202030"),
            _row(kr, "000660.KS", "SK하이닉스", "Semiconductors", D2, "45301020"),
        ]
    )  # fmt: skip
    repo.update_asset_profiles(
        [
            {
                "asset_id": "US-NVDA",
                "business_summary": "NVIDIA Corp. designs GPUs for the U.S. and world markets. "
                "It also sells software.",
                "business_summary_source": "YFINANCE",
                **TAX.asset_columns("45301020"),
                "gics_source": "WIKIPEDIA_SP500",
            },
            {"asset_id": "US-JPM", **TAX.asset_columns("40101010"), "gics_source": "OVERRIDE"},
            {"asset_id": "US-MYST", **TAX.asset_columns(None, sector_code="10")},
            {"asset_id": "KR-005930", **TAX.asset_columns("45202030")},
        ]
    )


@pytest.fixture()
def repo() -> SqlRepository:
    r = open_repository("sqlite://", clock=lambda: AT)
    # assets 행: 구성종목 저장만으로는 assets 가 없으므로 기본 행을 만든다
    from backend.collectors.common import ensure_assets  # noqa: E402

    ensure_assets(
        r,
        {
            "NVDA": "NVIDIA Corporation",
            "OLD": "Old Co",
            "JPM": "JPMorgan Chase",
            "MYST": "Mystery Inc.",
            "005930.KS": "삼성전자",
            "000660.KS": "SK하이닉스",
        },
    )
    _seed(r)
    return r


def _inputs(repo: SqlRepository) -> dict:
    with repo.engine.connect() as conn:
        return descriptor_inputs(conn, list(IndexCode))


# ---------------------------------------------------------------- 문장·키워드
def test_first_sentence_skips_abbreviations() -> None:
    assert first_sentence("NVIDIA Corp. designs GPUs in the U.S. market. More.") == (
        "NVIDIA Corp. designs GPUs in the U.S. market."
    )
    assert first_sentence("") == "" and first_sentence(None) == ""
    assert first_sentence("No period at all") == "No period at all"
    assert len(first_sentence("word " * 200)) <= 400


def test_josa_and_default_intro() -> None:
    assert josa_eun("삼성전자") == "는" and josa_eun("셀트리온") == "은"
    assert josa_eun("NVIDIA") == "은(는)"
    levels = {"sub_industry": {"name_ko": "반도체"}, "sector": {"name_ko": "정보기술"}}
    assert default_intro("SK하이닉스", levels, "KR") == (
        "SK하이닉스는 반도체 기업이다.",
        "DEFAULT_GICS",
    )
    assert default_intro("X", {"sector": {"name_ko": "에너지"}}, "US")[1] == "DEFAULT_SECTOR"
    assert default_intro("삼성", None, "KR") == ("삼성은 한국 상장 기업이다.", "DEFAULT_NAME")


def test_keywords_are_deterministic() -> None:
    levels = {
        lvl: {"code": n.code, "name_en": n.name_en, "name_ko": n.name_ko}
        for lvl, n in TAX.four_levels("45301020").items()
    }
    kw = keywords_for("NVIDIA Corporation", ["NVDA"], levels)
    assert kw == keywords_for("NVIDIA Corporation", ["NVDA"], levels)
    assert {"semiconductors", "반도체", "nvidia", "nvda", "information technology"} <= set(kw)
    assert "corporation" not in kw and "and" not in kw
    assert "삼성전자" in keywords_for("삼성전자", ["005930"], None)


# ---------------------------------------------------------------- 버전
def test_versions_and_historical_classification(repo: SqlRepository) -> None:
    inputs = _inputs(repo)
    assert inputs["snapshots"]["SP500"] == [D1, D2]
    docs = build_descriptors(inputs, "SP500")
    assert [d["snapshot_date"] for d in docs] == [D1.isoformat(), D2.isoformat()]
    v1, v2 = docs
    assert {s["ticker"] for s in v1["stocks"]} == {"NVDA", "OLD"}  # 그때 구성종목
    assert {s["ticker"] for s in v2["stocks"]} == {"NVDA", "JPM", "MYST"}
    s = {x["ticker"]: x for x in v2["stocks"]}
    assert s["NVDA"]["gics"]["sub_industry"]["code"] == "45301020"
    assert s["NVDA"]["gics"]["industry_group"]["code"] == "4530"
    assert s["NVDA"]["gics_asof"] == "snapshot"
    assert s["NVDA"]["intro"] == "NVIDIA Corp. designs GPUs for the U.S. and world markets."
    assert s["NVDA"]["intro_source"] == "BUSINESS_SUMMARY:YFINANCE"
    assert s["JPM"]["gics_asof"] == "current" and s["JPM"]["gics_source"] == "OVERRIDE"
    assert s["JPM"]["intro_source"] == "DEFAULT_GICS"
    assert s["JPM"]["intro"] == "JPMorgan Chase은(는) 대형 종합 은행 기업이다."
    assert s["MYST"]["gics"]["sector"]["code"] == "10" and s["MYST"]["gics"]["sub_industry"] is None
    assert s["MYST"]["intro_source"] == "DEFAULT_SECTOR"
    assert v2["missing_gics"] == ["MYST"]
    assert any("현재 분류" in x for x in v2["limitations"])
    assert any("세부산업이 없는 종목 1개" in x for x in v2["limitations"])
    tree = {n["code"]: n["count"] for n in v2["gics_tree"]}
    assert tree["45"] == 1 and tree["40"] == 1 and tree["10"] == 1 and len(tree) == 273
    assert v2["count"] == 3 and v2["universe"] == "SP500"


def test_all_universe_flags_missing_history(repo: SqlRepository) -> None:
    docs = build_descriptors(_inputs(repo), "ALL")
    first = docs[0]  # D1: KOSPI200 은 D1 이전 스냅샷이 없음 → 가장 오래된(D2) 것 + 표시
    assert first["indices"]["KOSPI200"] == {"snapshot_date": D2.isoformat(), "note": NOT_AVAILABLE}
    assert first["indices"]["NDX"]["snapshot_date"] is None
    s = {x["yfinance_symbol"]: x for x in first["stocks"]}
    assert s["005930.KS"]["ticker"] == "005930" and s["005930.KS"]["market"] == "KR"
    assert s["005930.KS"]["flags"] == [NOT_AVAILABLE]
    assert s["NVDA"]["flags"] == []  # SP500 D1 에 있음
    assert s["005930.KS"]["intro"] == "삼성전자는 기술 하드웨어·저장장치·주변기기 기업이다."
    assert s["005930.KS"]["intro_source"] == "DEFAULT_GICS"
    assert {"삼성전자", "005930", "005930.ks"} <= set(s["005930.KS"]["keywords"])
    assert any(NOT_AVAILABLE in x for x in first["limitations"])
    latest = build_descriptors(_inputs(repo), "ALL", only_latest=True)
    assert len(latest) == 1 and latest[0]["snapshot_date"] == D2.isoformat()
    hynix = {x["ticker"]: x for x in latest[0]["stocks"]}["000660"]
    assert hynix["intro_source"] == "DEFAULT_GICS" and hynix["intro"].startswith("SK하이닉스는 ")


# ---------------------------------------------------------------- 검색
def test_search_functions(repo: SqlRepository) -> None:
    d = Descriptor(build_descriptors(_inputs(repo), "ALL", only_latest=True)[0])
    assert {e["ticker"] for e in d.filter_by_gics(["4530"])} == {"NVDA", "000660"}
    assert {e["ticker"] for e in d.filter_by_gics(["45"])} == {"NVDA", "000660", "005930"}
    assert {e["ticker"] for e in d.filter_by_gics(["10", "40101010"])} == {"MYST", "JPM"}
    hits = {m.entry["ticker"]: m.matched for m in d.search_keywords(["반도체", "gpus"])}
    assert set(hits) == {"NVDA", "000660"} and hits["NVDA"] == ["반도체", "gpus"]
    assert [m.entry["ticker"] for m in d.search_keywords(["반도체", "gpus"], min_distinct=2)] == [
        "NVDA"
    ]
    assert d.search_keywords(["semi"]) == []  # 단어 경계 (부분 문자열은 안 맞음)
    assert d.search_keywords(["   "]) == []
    assert d.sector_name_to_code("정보기술") == "45" and d.sector_name_to_code("Energy") == "10"
    assert [p["code"] for p in d.parents_of("45301020")] == ["45", "4530", "453010"]
    assert d.by_ticker("005930.ks")["name"] == "삼성전자" and d.by_ticker("ZZZ") is None


# ---------------------------------------------------------------- 파일
def test_write_and_select_versions(repo: SqlRepository, tmp_path: Path) -> None:
    docs = build_descriptors(_inputs(repo), "SP500")
    res = write_descriptors(docs, tmp_path, "SP500")
    assert [p.name for p, _c in res] == [
        f"sp500_descriptor_{D1}.json",
        f"sp500_descriptor_{D2}.json",
    ] and all(c for _p, c in res)
    latest = json.loads((tmp_path / "sp500_descriptor.json").read_text("utf-8"))
    assert latest["snapshot_date"] == D2.isoformat() and "generated_at" in latest
    idx = json.loads((tmp_path / "sp500_descriptor_versions.json").read_text("utf-8"))
    assert [v["snapshot_date"] for v in idx["versions"]] == [D1.isoformat(), D2.isoformat()]
    gen = latest["generated_at"]
    # 같은 내용이면 다시 쓰지 않음 (generated_at 유지)
    again = write_descriptors(build_descriptors(_inputs(repo), "SP500"), tmp_path, "SP500")
    assert not any(c for _p, c in again)
    assert json.loads((tmp_path / f"sp500_descriptor_{D2}.json").read_text(encoding="utf-8"))["generated_at"] == gen
    # 버전 고르기
    assert select_version(tmp_path, "SP500", date(2026, 1, 1)) == (
        tmp_path / f"sp500_descriptor_{D1}.json",
        [],
    )
    assert select_version(tmp_path, "sp500", D2)[0].name == f"sp500_descriptor_{D2}.json"
    path, warn = select_version(tmp_path, "SP500", date(2020, 1, 1))
    assert path.name == f"sp500_descriptor_{D1}.json" and NOT_AVAILABLE in warn[0]
    with pytest.raises(FileNotFoundError):
        select_version(tmp_path, "NDX", D2)
    assert Descriptor.load(path).by_ticker("OLD") is not None


def test_script_reads_db_only(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    db = tmp_path / "x.db"
    url = f"sqlite:///{db}"
    r = open_repository(url, clock=lambda: AT)
    from backend.collectors.common import ensure_assets  # noqa: E402

    ensure_assets(r, {"NVDA": "NVIDIA", "005930.KS": "삼성전자"})
    r.save_constituents([_row(IndexCode.SP500, "NVDA", "NVIDIA", "Semiconductors", D2, "45301020")])
    r.engine.dispose()
    before = db.stat().st_mtime_ns
    out = tmp_path / "processed"
    code = build_descriptor.main(["--db", url, "--out", str(out), "--universe", "sp500,kospi200"])
    text = capsys.readouterr().out
    assert code == 1  # KOSPI200 스냅샷 없음 → 1, SP500 은 씀
    assert "KOSPI200: 구성종목 스냅샷 없음" in text and "SP500 2026-09-18: 1종목" in text
    assert (out / "sp500_descriptor_2026-09-18.json").exists()
    assert db.stat().st_mtime_ns == before  # 읽기 전용
    assert build_descriptor.main(["--db", url, "--out", str(out), "--universe", "SP500"]) == 0
    assert "(같음)" in capsys.readouterr().out
    with pytest.raises(SystemExit):
        build_descriptor.main(["--db", url, "--universe", "DOW"])


def test_script_stops_without_taxonomy(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    import sqlite3

    db = tmp_path / "empty.db"
    sqlite3.connect(db).close()
    assert build_descriptor.main(["--db", f"sqlite:///{db}", "--out", str(tmp_path)]) == 1
    assert "migrate_v2" in capsys.readouterr().out


def test_mask_url() -> None:
    assert mask_url("postgresql://u:secret@h:5432/db") == "postgresql://***@h:5432/db"
    assert mask_url("sqlite:///x.db") == "sqlite:///x.db"
