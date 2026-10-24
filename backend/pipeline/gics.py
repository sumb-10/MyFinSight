"""GICS 분류표 (Module2 §5 종목 검색용 사전의 산업분류 기준).

    from backend.pipeline.gics import load_taxonomy
    tax = load_taxonomy()                       # backend/data/reference/gics_taxonomy.json
    node = tax.resolve("Semiconductors")        # 이름 → 세부산업 (45301020)
    tax.sector_name_to_code("정보기술")          # "45" (영문·한국어 이름 모두)
    [n.code for n in tax.parents_of("45301020")]  # ["45", "4530", "453010"]

- GICS 는 섹터(2자리) → 산업그룹(4) → 산업(6) → 세부산업(8) 네 단계이고 아래 단계 코드는 위 단계
  코드로 시작한다. 2023년 3월 17일 시행판: 섹터 11·산업그룹 25·산업 74·세부산업 163.
- 원본은 backend/data/reference/gics_taxonomy.json (저장소에 포함). 수집기는 같은 내용을 DB 참조 테이블
  gics_taxonomy 에 싣고(분석 코드는 DB 만 읽음, K3), 이 모듈은 파일과 DB 행 어느 쪽으로도 만든다.
- name_ko 는 이 프로젝트의 번역이다 (공식 한국어 명칭이 아님).
- 이름 맞추기: 대소문자·"&"/"and"·문장부호·공백 차이는 무시하고, 2023년 개편 전 이름(aliases,
  예: Internet & Direct Marketing Retail → Broadline Retail)도 지금 코드로 잇는다.
"""

from __future__ import annotations

import json
import re
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import Any

from backend.core.paths import DATA_DIR

TAXONOMY_FILE = "gics_taxonomy.json"
LEVELS: Mapping[int, str] = {1: "sector", 2: "industry_group", 3: "industry", 4: "sub_industry"}
"""단계 번호 → 이름 (코드 길이는 단계 × 2)."""
FINANCIALS = "40"
"""금융 섹터 코드: 은행·보험·증권은 손익계산서에 매출액·영업이익 줄이 없다 (DART·EDGAR)."""
NO_REVENUE_LINE_SECTORS = frozenset({FINANCIALS})
"""매출액·영업이익을 기대하지 않는 섹터 (재무 결측 집계에서 빼는 기준)."""
REVENUE_ITEMS = ("매출액", "매출액(분기)", "영업이익", "영업이익(분기)")


def reference_file(name: str) -> Path:
    """backend/data/reference/ 파일 위치."""
    return DATA_DIR / "reference" / name


def normalize_name(text: str) -> str:
    """이름 비교용: 소문자, & → and, 문장부호 제거, 공백 하나로."""
    t = str(text).strip().lower().replace("&", " and ")
    t = re.sub(r"[^0-9a-z가-힣]+", " ", t)
    return " ".join(t.split())


@dataclass(frozen=True)
class GicsNode:
    """분류표 한 줄."""

    code: str
    level: int
    name_en: str
    name_ko: str
    parent_code: str | None

    def as_dict(self) -> dict[str, Any]:
        return {
            "code": self.code,
            "level": self.level,
            "name_en": self.name_en,
            "name_ko": self.name_ko,
            "parent_code": self.parent_code,
        }


class GicsTaxonomy:
    """GICS 4단계 분류표: 코드·이름 변환, 상위 분류, 접두 코드 검색."""

    def __init__(
        self,
        nodes: Iterable[GicsNode | Mapping[str, Any]],
        *,
        aliases: Mapping[str, str] | None = None,
        version: str = "",
    ) -> None:
        self.version = version
        self.nodes: dict[str, GicsNode] = {}
        for n in nodes:
            node = n if isinstance(n, GicsNode) else GicsNode(**dict(n))
            self.nodes[node.code] = node
        self._by_name: dict[tuple[int, str], str] = {}
        for node in sorted(self.nodes.values(), key=lambda x: x.code):
            for name in (node.name_en, node.name_ko):
                self._by_name.setdefault((node.level, normalize_name(name)), node.code)
        self.aliases = {normalize_name(k): v for k, v in (aliases or {}).items()}

    # ------------------------------------------------------------------ 조회
    def get(self, code: str | None) -> GicsNode | None:
        return self.nodes.get(str(code)) if code else None

    def level_nodes(self, level: int) -> list[GicsNode]:
        return sorted((n for n in self.nodes.values() if n.level == level), key=lambda n: n.code)

    def resolve(self, name: str | None, level: int = 4) -> GicsNode | None:
        """이름(영문·한국어·예전 이름) 또는 코드 → 그 단계 분류. 모르면 None."""
        if not name or not str(name).strip():
            return None
        text = str(name).strip()
        if text.isdigit():
            node = self.nodes.get(text)
            return node if node and node.level == level else None
        key = normalize_name(text)
        code = self._by_name.get((level, key))
        if code is None and level == 4:
            code = self.aliases.get(key)
        return self.nodes.get(code) if code else None

    def sector_name_to_code(self, name: str) -> str | None:
        """섹터 이름(영문·한국어, 예: "Information Technology", "정보기술") → 2자리 코드."""
        node = self.resolve(name, 1)
        return node.code if node else None

    def chain(self, code: str) -> list[GicsNode]:
        """섹터부터 code 자신까지 (모르는 코드면 빈 목록)."""
        out: list[GicsNode] = []
        node = self.nodes.get(code)
        while node is not None:
            out.append(node)
            node = self.nodes.get(node.parent_code) if node.parent_code else None
        return out[::-1]

    def parents_of(self, code: str) -> list[GicsNode]:
        """상위 분류 (섹터 → 바로 위 단계 순, code 자신은 빼고)."""
        return self.chain(code)[:-1]

    def children(self, code: str) -> list[GicsNode]:
        return sorted(
            (n for n in self.nodes.values() if n.parent_code == code), key=lambda n: n.code
        )

    def sub_industries_under(self, prefix: str) -> list[GicsNode]:
        """코드가 prefix 로 시작하는 세부산업 (접두 코드 검색)."""
        return [n for n in self.level_nodes(4) if n.code.startswith(str(prefix))]

    def four_levels(self, sub_code: str | None) -> dict[str, GicsNode] | None:
        """세부산업 코드 → {sector, industry_group, industry, sub_industry}. 모르면 None."""
        node = self.get(sub_code)
        if node is None or node.level != 4:
            return None
        chain = self.chain(node.code)
        return {LEVELS[n.level]: n for n in chain}

    def asset_columns(self, sub_code: str | None, *, sector_code: str | None = None) -> dict:
        """assets 의 GICS 칸 값. 세부산업을 모르면 sector_code 만 (나머지 None)."""
        levels = self.four_levels(sub_code)
        if levels is None:
            sector = self.get(sector_code)
            return {
                "gics_sector_code": sector.code if sector and sector.level == 1 else None,
                "gics_industry_group_code": None,
                "gics_industry_code": None,
                "gics_sub_industry_code": None,
                "gics_sub_industry": None,
            }
        return {
            "gics_sector_code": levels["sector"].code,
            "gics_industry_group_code": levels["industry_group"].code,
            "gics_industry_code": levels["industry"].code,
            "gics_sub_industry_code": levels["sub_industry"].code,
            "gics_sub_industry": levels["sub_industry"].name_en,
        }

    def rows(self) -> list[dict[str, Any]]:
        """DB 참조 테이블 gics_taxonomy 행 (코드 순)."""
        return [n.as_dict() for n in sorted(self.nodes.values(), key=lambda n: n.code)]

    def counts(self) -> dict[int, int]:
        return {lvl: len(self.level_nodes(lvl)) for lvl in LEVELS}


def taxonomy_from_file(path: Path | str | None = None) -> GicsTaxonomy:
    p = Path(path) if path else reference_file(TAXONOMY_FILE)
    doc = json.loads(p.read_text(encoding="utf-8"))
    return GicsTaxonomy(
        doc["nodes"], aliases=doc.get("aliases") or {}, version=str(doc.get("version") or "")
    )


@lru_cache(maxsize=4)
def _cached(path: str) -> GicsTaxonomy:
    return taxonomy_from_file(path)


def load_taxonomy(path: Path | str | None = None) -> GicsTaxonomy:
    """backend/data/reference/gics_taxonomy.json (한 번 읽어 둠)."""
    return _cached(str(Path(path) if path else reference_file(TAXONOMY_FILE)))


def expects_revenue(sector_code: str | None) -> bool:
    """이 섹터 종목에 매출액·영업이익 줄을 기대하는가 (금융 섹터는 아님, 모르면 기대함)."""
    return (sector_code or "")[:2] not in NO_REVENUE_LINE_SECTORS
