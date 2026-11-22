"""종목 검색용 사전 (M2-03). backend/pipeline/descriptor.py 가 DB 로 만든 버전 파일을 읽는다.

- `sync(repo, market)`: 팀 DB 에서 버전 파일을 다시 만든다. 화면 서버가 DB 를 열 때 부른다 (api/services.py).
- `load_for(as_of, universes, markets)`: 기준일 이전 최신 버전 선택(K4), 요청 유니버스·시장으로 종목을 걸러 Descriptor 로.
- `render_tree(desc)`: 의도 해석 프롬프트용 GICS 트리(종목 수 포함).
- `gics_model(entry)`: 사전 항목의 gics → schemas.selection.Gics.
"""

from __future__ import annotations

import logging
from collections.abc import Iterable
from datetime import date
from pathlib import Path
from typing import Any

from backend.analysis.errors import DataMissing
from backend.analysis.paths import PROCESSED
from backend.analysis.schemas.selection import Gics, GicsLevel
from backend.db.readers import descriptor_inputs
from backend.pipeline.descriptor import (
    Descriptor,
    build_descriptors,
    select_version,
    write_descriptors,
)
from backend.schemas.market import IndexCode

log = logging.getLogger(__name__)
LEVELS = ["sector", "industry_group", "industry", "sub_industry"]
LEVEL_LEN = {"sector": 2, "industry_group": 4, "industry": 6, "sub_industry": 8}
UNIVERSE_INDEX = {"SP500": "SP500", "NASDAQ100": "NDX", "KOSPI200": "KOSPI200"}


def sync(repo: Any, market: Any) -> list[str]:
    """사전 파일을 팀 DB 기준으로 맞춘다 (backend/scripts/build_descriptor.py 가 손으로 하던 일). market = settings.market.

    DB 의 세 표(분류표 · 지수 구성종목 · 종목 마스터)만 읽는다. 읽기 계정으로 되고 인터넷·분석 모델을 쓰지 않는다.
    버전 파일은 스냅샷 날짜마다 하나이고 내용이 같으면 다시 쓰지 않으므로, DB 가 그대로면 예전 실행이 고른 버전도 그대로다.
    돌려주는 값은 새로 쓰거나 바뀐 버전의 날짜. 맞추지 못해도 오류를 올리지 않는다 — 있던 파일을 그대로 쓰고 이유는 로그에 남긴다
    (사전을 못 맞춘 것이 서버를 멈출 일은 아니다. 파일이 하나도 없으면 load_for 가 알린다).
    """
    if not market.descriptor_sync:
        return []
    universe = market.descriptor_universe
    try:
        with repo.engine.connect() as conn:  # 저장소의 재시도(끊기면 최대 85초 기다림)를 거치지 않는다: 서버가 잠금을 쥔 채 부른다
            inputs = descriptor_inputs(conn, list(IndexCode))
        docs = build_descriptors(inputs, universe) if inputs["taxonomy"] else []
        if not docs:
            log.warning("[descriptor] 팀 DB 에 분류표나 지수 구성종목이 없어 종목 사전을 만들지 못했습니다")
            return []
        written = write_descriptors(docs, market.descriptor_dir or PROCESSED, universe)
    except Exception:  # noqa: BLE001 — 어떤 이유로든 못 맞추면 있던 것을 쓴다
        log.warning("[descriptor] 종목 사전을 팀 DB 기준으로 맞추지 못했습니다 (있던 파일을 그대로 씁니다)", exc_info=True)
        return []
    changed = [doc["snapshot_date"] for (_path, is_new), doc in zip(written, docs, strict=True) if is_new]
    log.info("[descriptor] %s 버전 %d개 확인, 새로 쓴 것 %d개 %s", universe, len(docs), len(changed), changed or "")
    return changed


def load_for(
    as_of: date,
    universes: Iterable[str],
    markets: Iterable[str] = ("US", "KR"),
    *,
    processed_dir: Path | str = PROCESSED,
    universe_file: str = "ALL",
) -> tuple[Descriptor, dict[str, Any], list[str]]:
    """(사전, 버전 정보, 경고). 종목은 요청 유니버스(indices ∩)와 시장으로 거른다."""
    try:
        path, warnings = select_version(processed_dir, universe_file, as_of)
    except FileNotFoundError as exc:
        raise DataMissing("종목 사전이 아직 없습니다. 팀 DB 에 연결하면 자동으로 만들어집니다 — 연결 설정에서 팀 DB 상태를 확인해 주세요") from exc
    full = Descriptor.load(path)
    want_idx = {UNIVERSE_INDEX[u] for u in universes}
    want_mkt = set(markets)
    stocks = [
        s for s in full.stocks
        if set(s.get("indices", [])) & want_idx and s.get("market", "US") in want_mkt and s.get("gics", {}).get("sector")
    ]  # fmt: skip
    doc = {**full.doc, "stocks": stocks, "count": len(stocks)}
    desc = Descriptor(doc)
    info = {
        "file": path.name,
        "snapshot_date": full.doc.get("snapshot_date"),
        "taxonomy_version": full.doc.get("taxonomy_version"),
        "indices": full.doc.get("indices"),
        "universes": sorted(universes),
        "markets": sorted(want_mkt),
        "n_stocks": len(stocks),
        "limitations": list(full.doc.get("limitations", [])),
    }
    draft = [s["ticker"] for s in stocks if (s.get("gics_source") or "").endswith("DRAFT")]
    if draft:
        warnings.append(f"GICS 분류 검수 대기(DRAFT) 종목 {len(draft)}개: {', '.join(draft[:15])}")
    return desc, info, list(warnings)


def code_of(entry: dict[str, Any], level: str) -> str | None:
    node = (entry.get("gics") or {}).get(level)
    return node["code"] if node else None


def gics_model(entry: dict[str, Any]) -> Gics:
    g = entry.get("gics") or {}

    def lvl(name: str) -> GicsLevel:
        node = g.get(name)
        if node:
            return GicsLevel(code=node["code"], name=node.get("name_en") or node.get("name") or "")
        # 상위 코드로 채움 (세부산업이 없는 종목)
        sec = g.get("sector") or {"code": "", "name_en": ""}
        return GicsLevel(code=sec["code"], name=sec.get("name_en") or "")

    return Gics(sector=lvl("sector"), industry_group=lvl("industry_group"), industry=lvl("industry"), sub_industry=lvl("sub_industry"))


def render_tree(desc: Descriptor, max_level: str = "sub_industry") -> str:
    """GICS 트리 텍스트 (코드 이름 (종목 수)). 종목 수는 이 사전에 남은 종목 기준."""
    names: dict[str, dict[str, str]] = {lvl: {} for lvl in LEVELS}
    counts: dict[str, int] = {}
    for s in desc.stocks:
        for lvl in LEVELS:
            node = (s.get("gics") or {}).get(lvl)
            if not node:
                continue
            names[lvl][node["code"]] = node.get("name_en") or node.get("name") or ""
            counts[node["code"]] = counts.get(node["code"], 0) + 1
    depth = LEVELS.index(max_level)
    lines = []
    for s in sorted(names["sector"]):
        lines.append(f"{s} {names['sector'][s]} ({counts.get(s, 0)})")
        if depth < 1:
            continue
        for g in sorted(k for k in names["industry_group"] if k.startswith(s)):
            lines.append(f"  {g} {names['industry_group'][g]} ({counts.get(g, 0)})")
            if depth < 2:
                continue
            for i in sorted(k for k in names["industry"] if k.startswith(g)):
                lines.append(f"    {i} {names['industry'][i]} ({counts.get(i, 0)})")
                if depth < 3:
                    continue
                for u in sorted(k for k in names["sub_industry"] if k.startswith(i)):
                    lines.append(f"      {u} {names['sub_industry'][u]} ({counts.get(u, 0)})")
    return "\n".join(lines)


def sector_name_to_code(desc: Descriptor) -> dict[str, str]:
    out: dict[str, str] = {}
    for s in desc.stocks:
        node = (s.get("gics") or {}).get("sector")
        if node:
            out[node.get("name_en") or node.get("name") or ""] = node["code"]
            if node.get("name_ko"):
                out[node["name_ko"]] = node["code"]
    return out


def parents_of(code: str) -> list[str]:
    """상위 코드, 가까운 것부터: 45301020 -> ['453010', '4530', '45']."""
    return [code[:n] for n in (6, 4, 2) if n < len(code)]


def known_codes(desc: Descriptor) -> set[str]:
    return {r["code"] for r in desc.tax.rows()}


def tickers(desc: Descriptor) -> list[str]:
    return sorted(s["yfinance_symbol"] for s in desc.stocks)


def entry(desc: Descriptor, ticker: str) -> dict[str, Any] | None:
    return desc.by_ticker(ticker)
