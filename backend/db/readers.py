"""읽기 전용 조회 (분석 쪽 읽기 계정으로도 됨): 테이블을 만들거나 바꾸지 않는다.

SqlRepository 는 열 때 테이블을 만들고 기본 행을 넣으므로 쓰기 권한이 필요하다. 읽기 계정
(myfinsight_read)으로 DB 만 읽는 스크립트(coverage_report.py, build_descriptor.py)는 여기의
readonly_engine 과 조회 함수를 쓴다.
"""

from __future__ import annotations

from collections import defaultdict
from datetime import date
from typing import Any

from sqlalchemy import Engine, create_engine, event, inspect, select

from backend.db import tables as T
from backend.schemas.market import IndexCode


def readonly_engine(url_text: str) -> Engine:
    """읽기 전용 연결 엔진 (PostgreSQL default_transaction_read_only, SQLite query_only)."""
    from backend.db import normalize_db_url

    url, args = normalize_db_url(url_text)
    if url.get_backend_name() == "postgresql":
        args = {**args, "options": "-c default_transaction_read_only=on"}
        return create_engine(url, connect_args=args)
    engine = create_engine(url)

    @event.listens_for(engine, "connect")
    def _ro(dbapi_conn: Any, _rec: Any) -> None:
        dbapi_conn.execute("PRAGMA query_only = ON")

    return engine


def mask_url(url: str) -> str:
    """화면에 찍을 DB 주소 (비밀번호 가림)."""
    if "@" not in url or "://" not in url:
        return url
    head, tail = url.split("://", 1)
    return f"{head}://***@{tail.split('@', 1)[1]}"


ASSET_FIELDS = (
    "asset_id",
    "ticker",
    "name",
    "market",
    "currency",
    "asset_type",
    "yfinance_symbol",
    "gics_sector_code",
    "gics_industry_group_code",
    "gics_industry_code",
    "gics_sub_industry_code",
    "gics_sub_industry",
    "gics_source",
    "gics_updated_at",
    "business_summary",
    "business_summary_source",
)


def descriptor_inputs(conn: Any, indices: list[IndexCode]) -> dict[str, Any]:
    """종목 검색용 사전 재료: 분류표, 지수별 스냅샷 날짜·구성종목, 종목 마스터 (DB 만 읽음).

    {"taxonomy": [행], "snapshots": {지수: [날짜]}, "members": {(지수, 날짜): [행]},
     "assets": {asset_id: 행}}
    """
    have = set(inspect(conn).get_table_names())
    if "gics_taxonomy" not in have:
        raise RuntimeError("gics_taxonomy 테이블이 없음 (python backend/scripts/migrate_v2.py --apply)")
    g = T.gics_taxonomy
    taxonomy = [
        dict(r._mapping)
        for r in conn.execute(
            select(g.c.code, g.c.level, g.c.name_en, g.c.name_ko, g.c.parent_code).order_by(
                g.c.code
            )
        )
    ]
    ic = T.index_constituent
    codes = [IndexCode(i).value for i in indices]
    members: dict[tuple[str, date], list[dict[str, Any]]] = defaultdict(list)
    q = (
        select(
            ic.c.index_code,
            ic.c.snapshot_date,
            ic.c.ticker,
            ic.c.asset_id,
            ic.c.name,
            ic.c.sector,
            ic.c.industry,
            ic.c.gics_sub_industry_code,
        )
        .where(ic.c.index_code.in_(codes))
        .order_by(ic.c.index_code, ic.c.snapshot_date, ic.c.ticker)
    )
    for r in conn.execute(q):
        members[(r.index_code, r.snapshot_date)].append(dict(r._mapping))
    snapshots: dict[str, list[date]] = {c: [] for c in codes}
    for code, d in members:
        snapshots[code].append(d)
    ids = sorted({m["asset_id"] for rows in members.values() for m in rows})
    a = T.assets
    assets: dict[str, dict[str, Any]] = {}
    for i in range(0, len(ids), 500):
        part = ids[i : i + 500]
        for r in conn.execute(
            select(*(a.c[c] for c in ASSET_FIELDS)).where(a.c.asset_id.in_(part))
        ):
            assets[r.asset_id] = dict(r._mapping)
    return {
        "taxonomy": taxonomy,
        "snapshots": {k: sorted(v) for k, v in snapshots.items()},
        "members": dict(members),
        "assets": assets,
    }
