"""GICS 분류표(backend/data/reference/gics_taxonomy.json)와 한국 종목 매핑표(backend/data/config/kr_gics.csv,
backend/data/config/ksic_to_gics.csv): 구조, 이름 맞추기, 저장소에 든 이름이 모두 풀리는지."""

from __future__ import annotations

import csv
import json
from collections import Counter
from pathlib import Path

import pytest
from helpers import SUB_INDUSTRIES

from backend.collectors.constituents.source import _krx_table, load_gics_overrides
from backend.pipeline.classification import kr_code, ksic_to_gics, load_kr_gics, load_ksic_map
from backend.pipeline.gics import (
    GicsTaxonomy,
    expects_revenue,
    load_taxonomy,
    normalize_name,
    reference_file,
)

ROOT = Path(__file__).resolve().parents[1]
TAX = load_taxonomy()


def test_file_is_where_the_spec_says() -> None:
    assert (
        reference_file("gics_taxonomy.json") == ROOT / "data" / "reference" / "gics_taxonomy.json"
    )
    doc = json.loads((ROOT / "data" / "reference" / "gics_taxonomy.json").read_text("utf-8"))
    assert doc["version"] == "2023-03-17"
    assert "프로젝트의 번역" in doc["description"]  # 한국어 이름은 공식 명칭이 아님


def test_counts_of_the_2023_structure() -> None:
    # 2023-03-17 시행판: 섹터 11·산업그룹 25·산업 74·세부산업 163
    assert TAX.counts() == {1: 11, 2: 25, 3: 74, 4: 163}


def test_codes_and_parents() -> None:
    for node in TAX.nodes.values():
        assert node.code.isdigit() and len(node.code) == node.level * 2, node
        if node.level == 1:
            assert node.parent_code is None
        else:  # 부모는 바로 위 단계이고 내 코드의 앞부분
            parent = TAX.get(node.parent_code)
            assert parent is not None and parent.level == node.level - 1, node
            assert node.code.startswith(parent.code), node
        assert node.name_en.strip() and node.name_ko.strip(), node
    # 잎이 아닌 단계에는 자식이 있음 (빈 산업그룹·산업 없음)
    for node in TAX.nodes.values():
        if node.level < 4:
            assert TAX.children(node.code), node


def test_names_unique_within_a_level() -> None:
    for level in (1, 2, 3, 4):
        en = Counter(normalize_name(n.name_en) for n in TAX.level_nodes(level))
        ko = Counter(n.name_ko for n in TAX.level_nodes(level))
        assert [k for k, v in en.items() if v > 1] == [], level
        assert [k for k, v in ko.items() if v > 1] == [], level


def test_known_codes() -> None:
    expect = {
        "45301020": "Semiconductors",
        "45202030": "Technology Hardware, Storage & Peripherals",
        "25503030": "Broadline Retail",
        "30101040": "Consumer Staples Merchandise Retail",
        "40201060": "Transaction & Payment Processing Services",
        "20202030": "Data Processing & Outsourced Services",  # 2023 년 IT → 산업재로 옮김
        "60108050": "Data Center REITs",
        "50203010": "Interactive Media & Services",
    }
    for code, name in expect.items():
        assert TAX.get(code).name_en == name
    assert TAX.sector_name_to_code("Information Technology") == "45"
    assert TAX.sector_name_to_code("정보기술") == "45"
    assert TAX.sector_name_to_code("information  technology") == "45"
    assert TAX.sector_name_to_code("Semiconductors") is None  # 섹터가 아님
    assert [n.code for n in TAX.parents_of("45301020")] == ["45", "4530", "453010"]
    assert [n.code for n in TAX.chain("45301020")] == ["45", "4530", "453010", "45301020"]
    assert {n.code for n in TAX.sub_industries_under("4530")} == {"45301010", "45301020"}


def test_resolve_names_and_aliases() -> None:
    assert TAX.resolve("Semiconductors").code == "45301020"
    assert TAX.resolve("반도체").code == "45301020"
    assert TAX.resolve("Soft Drinks & Non-Alcoholic Beverages").code == "30201030"
    assert TAX.resolve("Multi-Line Insurance").code == "40301030"
    assert TAX.resolve("Hotels, Resorts and Cruise Lines").code == "25301020"
    # 2023 년 개편 전 이름
    assert TAX.resolve("Internet & Direct Marketing Retail").code == "25503030"
    assert TAX.resolve("Hypermarkets & Super Centers").code == "30101040"
    assert TAX.resolve("Trucking").code == "20304030"
    assert TAX.resolve("Consumer Electronics").code == "25201010"
    assert TAX.resolve("Semiconductors & Semiconductor Equipment") is None  # 산업 단계 이름
    assert TAX.resolve("Semiconductors & Semiconductor Equipment", 3).code == "453010"
    assert TAX.resolve("45301020").code == "45301020"
    assert TAX.resolve("4530") is None and TAX.resolve("") is None and TAX.resolve("산업 1") is None
    for alias, code in json.loads(reference_file("gics_taxonomy.json").read_text("utf-8"))[
        "aliases"
    ].items():
        assert TAX.get(code).level == 4, alias


def test_asset_columns() -> None:
    cols = TAX.asset_columns("45301020")
    assert cols == {
        "gics_sector_code": "45",
        "gics_industry_group_code": "4530",
        "gics_industry_code": "453010",
        "gics_sub_industry_code": "45301020",
        "gics_sub_industry": "Semiconductors",
    }
    only = TAX.asset_columns(None, sector_code="40")
    assert only["gics_sector_code"] == "40" and only["gics_sub_industry_code"] is None
    assert not expects_revenue("40") and expects_revenue("45") and expects_revenue(None)


def test_taxonomy_from_db_rows_is_the_same() -> None:
    again = GicsTaxonomy(TAX.rows())
    assert again.rows() == TAX.rows() and again.counts() == TAX.counts()


def _sector_ok(sector: str, industry: str) -> bool:
    node = TAX.resolve(industry)
    return node is not None and TAX.chain(node.code)[0].code == TAX.sector_name_to_code(sector)


def test_override_and_ndx_names_resolve() -> None:
    """backend/data/config/gics_overrides.csv·ndx.csv·테스트 구성종목의 이름이 모두 분류표로 풀림."""
    bad = [(t, s, i) for t, (s, i) in load_gics_overrides().items() if not _sector_ok(s, i)]
    assert bad == []
    with (ROOT / "data" / "config" / "ndx.csv").open(encoding="utf-8") as f:
        rows = list(csv.DictReader(x for x in f if not x.startswith("#")))
    assert len(rows) >= 98
    assert [r["ticker"] for r in rows if not _sector_ok(r["sector"], r["industry"])] == []
    for sector, names in SUB_INDUSTRIES.items():
        assert all(_sector_ok(sector, n) for n in names) and len(names) >= 3


# ---------------------------------------------------------------- 한국
KR = load_kr_gics()

UNREVIEWED = {
    "402340", "138040", "003670", "064350", "443060", "078930", "0126Z0", "180640", "009830",
    "062040", "032640", "326030", "175330", "011790", "138930", "066970", "082740", "002380",
    "010060", "139130", "302440", "450080", "007340", "004990", "051600", "081660", "103140",
    "361610", "120110", "071970", "008770", "006280", "006040", "017960", "285130", "003240",
    "004000", "298020", "071320", "000080", "000210", "456040", "137310", "298050", "0220W0",
    "014820", "008730", "005420", "068270", "066570",
}  # fmt: skip
"""검수가 필요한 종목 (kr_gics.csv reviewed=false). 바꾸면 이 목록도 고침."""


def test_kr_map_covers_every_kospi200_row_with_valid_codes() -> None:
    krx = _krx_table(ROOT / "data" / "config" / "kospi200_krx.csv")
    names = {kr_code(r["종목코드"]): r["종목명"] for r in krx}
    assert len(names) == 201
    assert set(KR) == set(names)
    for code, row in KR.items():
        assert row.name == names[code], code  # KRX 표의 종목명과 같음
        node = TAX.get(row.code)
        assert node is not None and node.level == 4, (code, row.code)
        assert row.basis, code
    assert {c for c, r in KR.items() if not r.reviewed} == UNREVIEWED
    # 섹터 분포가 상식선 (산업재·소재가 많고 모든 행이 11개 섹터 안)
    sectors = Counter(r.code[:2] for r in KR.values())
    assert sum(sectors.values()) == 201 and set(sectors) <= {n.code for n in TAX.level_nodes(1)}
    assert KR["005930"].code == "45202030" and KR["000660"].code == "45301020"
    assert KR["105560"].code == "40101010" and KR["035420"].code == "50203010"


def test_kr_gics_csv_name_column_matches_taxonomy() -> None:
    p = ROOT / "data" / "config" / "kr_gics.csv"
    with p.open(encoding="utf-8") as f:
        rows = list(csv.DictReader(x for x in f if not x.startswith("#")))
    for r in rows:
        assert TAX.get(r["gics_sub_industry_code"]).name_en == r["gics_sub_industry"], r["ticker"]
        assert r["reviewed"] in ("true", "false")


def test_ksic_map() -> None:
    table = load_ksic_map()
    assert table and [len(p) for p, _c, _n in table] == sorted(
        (len(p) for p, _c, _n in table), reverse=True
    )
    for prefix, code, _note in table:
        assert prefix.isdigit(), prefix
        assert code is None or TAX.get(code).level == 4, prefix
    cases = {
        "264": "45202030",  # 통신·방송 장비 (휴대폰)
        "26410": "45201020",  # 유선 통신장비
        "261": "45301020",
        "21102": "35201010",  # 생물학적 제제 → 바이오
        "2110": "35202010",
        "70113": "35201010",
        "66121": "40203020",  # 증권 중개
        "6511": "40301020",
        "C26110": "45301020",  # 영문 대분류 문자는 무시
    }
    for ksic, code in cases.items():
        assert ksic_to_gics(ksic, table)[0] == code, ksic
    assert ksic_to_gics("64992", table) == (None, "64992")  # 지주회사: 자동으로 정하지 않음
    assert ksic_to_gics("", table) == (None, None)
    assert ksic_to_gics("99999", table) == (None, None)


@pytest.mark.parametrize("code", ["005930", "5930", "005930.KS", "0126Z0.KS"])
def test_kr_code(code: str) -> None:
    assert kr_code(code) in ("005930", "0126Z0")
