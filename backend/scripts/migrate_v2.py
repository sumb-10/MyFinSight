"""예전(v1) 스키마 DB 를 새 데이터 계약(v2, module_prototype2 2.2절) 스키마로 옮긴다.

python backend/scripts/migrate_v2.py                   # 확인만 (기본): 계획·행 수를 보여 주고 바꾸지 않음
python backend/scripts/migrate_v2.py --apply           # 한 트랜잭션으로 실행 (실패하면 전부 되돌림)
python backend/scripts/migrate_v2.py "postgres://..."  # 주소를 직접 줘서 (없으면 .env 의 DATABASE_URL)

하는 일 (--apply, 순서대로)
1. 확인: v1 인지, 새 이름(price_daily_source 등)이 비어 있는지, fx_daily 에 같은 (pair, date) 가
   여러 출처로 있는지. 하나라도 걸리면 아무것도 바꾸지 않고 멈춘다 (행을 지우지 않음).
2. 이름 바꾸기: price_daily → price_daily_source, financials → financials_source (출처별 원본,
   제약·인덱스·시퀀스 이름도 새 이름으로). run_step·run_artifact·report → *_v1 (예전 실행 기록).
3. assets: exchange 칸 추가, market KOSPI·KOSDAQ → KR (거래소 이름은 exchange 로).
4. fx_daily: 기본키 (pair, date, source) → (pair, date). SQLite 는 기본키를 못 바꿔서 fx_daily_v1 로
   이름을 바꾸고 새 표에 복사한다.
5. index_constituent: KOSPI200 티커 005930.KS → 005930 (계약: 한국 6자리 코드).
6. 새 테이블 만들기 (price_daily, financials, run_step, run_artifact, report) 와 출처 기본 행.
7. 계약 price_daily·financials 채우기: 저장소의 발행 함수로 종목 묶음씩 (SqlRepository.publish_all).

예전 데이터는 지우지 않는다 (DROP·DELETE 없음, SQLite 인덱스만 새 이름으로 다시 만듦).
이미 v2 인 DB: 확인만 하면 없는 새 테이블(예: valuation_daily, gics_taxonomy, v5 disclosures)·새 칸
(v4: assets 의 gics_* · ksic_code · business_summary*, index_constituent.gics_sub_industry_code;
v5: news 의 is_press_release · title_has_name · story_id · is_first_report · available_on)과 GICS 분류표
(backend/data/reference/gics_taxonomy.json → gics_taxonomy) 차이를 보여 주고, `--apply` 는 그것만 한다
(ALTER TABLE ... ADD COLUMN, 모두 NULL 허용 칸이라 기존 행은 그대로). 몇 번 돌려도 같다.
`--apply --republish` 는 7번도 다시 한다 (.env PRICE_PRIORITY_* 를 바꾼 뒤 등).
실행 중에는 수집 작업(GitHub Actions)과 데이터 API 를 멈춰 두는 것이 좋다 (표 잠금).
새 칸이 없는 DB 는 새 코드의 저장소가 열지 않는다 (먼저 이 스크립트로 옮김).
"""

from __future__ import annotations

import argparse
import sys
from collections.abc import Callable
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from sqlalchemy import Engine, create_engine, event, inspect, text  # noqa: E402

from backend.db import (  # noqa: E402
    _price_priority_from_env,
    default_db_url,
    normalize_db_url,
)
from backend.db import tables as T  # noqa: E402
from backend.db.sql import (  # noqa: E402
    SqlRepository,
    is_v1_schema,
    missing_columns,
    seed_gics_taxonomy,
)

RENAMES = [
    # (예전 이름, 새 이름, 따로 만든 인덱스 예전 이름 → 새 이름)
    (
        "price_daily",
        "price_daily_source",
        {
            "idx_price_ticker_date": "idx_price_source_ticker_date",
            "idx_price_unverified": "idx_price_source_unverified",
        },
    ),
    (
        "financials",
        "financials_source",
        {"idx_financials_asset_disclosed": "idx_financials_source_asset_disclosed"},
    ),
    ("report", "report_v1", {}),  # report 가 run_artifact 를 참조하므로 먼저
    ("run_step", "run_step_v1", {}),
    ("run_artifact", "run_artifact_v1", {}),
]
NEW_TABLES = ("price_daily", "financials", "run_step", "run_artifact", "report")
KR_MARKETS = ("KOSPI", "KOSDAQ")


class MigrationError(RuntimeError):
    """옮기기 전 확인에서 걸림 (아무것도 바꾸지 않음)."""


def _mask(url: str) -> str:
    if "@" not in url or "://" not in url:
        return url
    head, tail = url.split("://", 1)
    return f"{head}://***@{tail.split('@', 1)[1]}"


def _count(conn: Any, sql: str) -> int:
    return int(conn.execute(text(sql)).scalar_one())


def survey(conn: Any) -> dict[str, Any]:
    """현재 DB 상태 (읽기만). 확인 실행과 --apply 앞의 검사에 쓴다."""
    insp = inspect(conn)
    tables = set(insp.get_table_names())
    out: dict[str, Any] = {"v1": is_v1_schema(conn), "tables": tables, "problems": []}
    cols = missing_columns(conn)
    if out["v1"]:  # 이름을 바꿀 v1 테이블은 비교하지 않음, assets.exchange 는 3번에서 따로 더함
        renamed = {old for old, _, _ in RENAMES}
        cols = {t: c for t, c in cols.items() if t not in renamed}
        if "assets" in cols:
            cols["assets"] = [c for c in cols["assets"] if c != "exchange"]
    if "url_hash" in cols.get("news", []):
        cols["news"].remove("url_hash")
    out["columns"] = {t: c for t, c in cols.items() if c}  # news.url_hash 는 저장소가 열 때 고침
    out["taxonomy"] = taxonomy_diff(conn, tables)
    for table, names in out["columns"].items():
        strict = [c for c in names if not T.metadata.tables[table].c[c].nullable]
        if strict:
            out["problems"].append(f"{table} 에 NULL 불가 칸이 없음: {strict} (직접 확인)")
    if not out["v1"]:
        return out
    for old, new, _ in RENAMES:
        out[f"rows:{old}"] = _count(conn, f"SELECT COUNT(*) FROM {old}")
        if new in tables:
            out["problems"].append(f"{new} 테이블이 이미 있음 (예전에 새 코드로 연 DB?)")
    if "fx_daily_v1" in tables and conn.dialect.name == "sqlite":
        out["problems"].append("fx_daily_v1 테이블이 이미 있음")
    out["rows:fx_daily"] = _count(conn, "SELECT COUNT(*) FROM fx_daily")
    out["fx_duplicates"] = _count(
        conn,
        "SELECT COUNT(*) FROM (SELECT pair, date FROM fx_daily GROUP BY pair, date "
        "HAVING COUNT(*) > 1) d",
    )
    if out["fx_duplicates"]:
        out["problems"].append(
            f"fx_daily 에 같은 (pair, date) 가 여러 출처로 {out['fx_duplicates']}개 있음: "
            "남길 행을 직접 정한 뒤 다시 실행 (이 스크립트는 행을 지우지 않음)"
        )
    out["assets_kr"] = _count(
        conn, "SELECT COUNT(*) FROM assets WHERE market IN ('KOSPI', 'KOSDAQ')"
    )
    out["assets_total"] = _count(conn, "SELECT COUNT(*) FROM assets")
    out["kr_constituents"] = _count(
        conn,
        "SELECT COUNT(*) FROM index_constituent "
        "WHERE index_code = 'KOSPI200' AND (ticker LIKE '%.KS' OR ticker LIKE '%.KQ')",
    )
    out["price_keys"] = _count(
        conn,
        "SELECT COUNT(*) FROM (SELECT DISTINCT ticker, date FROM price_daily "
        "WHERE source <> 'CONSENSUS') k",
    )
    out["financial_rows_with_period_end"] = _count(
        conn, "SELECT COUNT(*) FROM financials WHERE period_end IS NOT NULL"
    )
    return out


def missing_tables(s: dict[str, Any]) -> list[str]:
    """코드에는 있는데 DB 에 없는 테이블 (v2 DB 에 새로 더한 valuation_daily 등)."""
    return sorted(set(T.metadata.tables) - s["tables"])


def taxonomy_diff(conn: Any, tables: set[str]) -> int:
    """gics_taxonomy 를 파일과 같게 하려면 넣거나 바꿀 행 수 (테이블이 없으면 전체 행 수)."""
    from backend.pipeline.gics import TAXONOMY_FILE, reference_file, taxonomy_from_file

    path = reference_file(TAXONOMY_FILE)
    if not path.exists():
        return 0
    want = {r["code"]: r for r in taxonomy_from_file(path).rows()}
    if "gics_taxonomy" not in tables:
        return len(want)
    have = {
        r.code: dict(r._mapping)
        for r in conn.execute(
            text("SELECT code, level, name_en, name_ko, parent_code FROM gics_taxonomy")
        )
    }
    return sum(1 for code, r in want.items() if have.get(code) != r)


def column_lines(s: dict[str, Any]) -> list[str]:
    return [f"- {t}: 칸 추가 {', '.join(cols)}" for t, cols in sorted(s["columns"].items())]


def add_missing_columns(conn: Any, log: Callable[[str], None] = print) -> int:
    """코드에 있고 DB 기존 테이블에 없는 칸을 더함 (NULL 허용 칸만, 기본값 없음). 더한 칸 수."""
    n = 0
    for table, cols in sorted(missing_columns(conn).items()):
        added = []
        for name in cols:
            col = T.metadata.tables[table].c[name]
            if not col.nullable:
                continue
            ddl = col.type.compile(dialect=conn.dialect)
            conn.execute(text(f'ALTER TABLE "{table}" ADD COLUMN "{name}" {ddl}'))
            added.append(name)
        if added:
            log(f"칸 추가: {table} ({', '.join(added)})")
            n += len(added)
    return n


def plan_lines(s: dict[str, Any]) -> list[str]:
    """확인 실행에서 보여 줄 계획."""
    if not s["v1"]:
        missing = missing_tables(s)
        lines = []
        if missing:
            lines.append("- 없는 테이블 만들기: " + ", ".join(missing))
        lines += column_lines(s)
        if s["taxonomy"]:
            lines.append(f"- gics_taxonomy: 분류표 파일과 다른 행 {s['taxonomy']}개 넣기·바꾸기")
        if lines:
            return [
                "v2 스키마. [계획]",
                *lines,
                "(기존 테이블·행은 그대로, --apply 로 실행)",
            ]
        return ["v1 스키마가 아님 (이미 옮겼거나 빈 DB): 테이블·칸이 모두 있음, 할 일 없음"]
    lines = ["[계획]"]
    for old, new, _ in RENAMES:
        lines.append(f"- {old} → {new} ({s[f'rows:{old}']:,}행, 이름만 바꿈)")
    lines += [
        f"- assets: exchange 칸 추가, market KOSPI·KOSDAQ → KR ({s['assets_kr']:,}"
        f"/{s['assets_total']:,}행)",
        f"- fx_daily: 기본키 (pair, date) 로 ({s['rows:fx_daily']:,}행, "
        f"중복 키 {s['fx_duplicates']}개)",
        f"- index_constituent: KOSPI200 티커 → 6자리 코드 ({s['kr_constituents']:,}행)",
        *column_lines(s),
        "- 새 테이블: " + ", ".join(NEW_TABLES) + ", gics_taxonomy 등 (분류표 행 채움)",
        f"- 계약 price_daily 채우기: (종목, 날짜) 약 {s['price_keys']:,}행",
        "- 계약 financials 채우기: 기간 끝 날짜가 있는 원본 "
        f"{s['financial_rows_with_period_end']:,}행에서 키마다 한 행",
    ]
    if s["problems"]:
        lines.append("[멈춤 사유]")
        lines += [f"- {p}" for p in s["problems"]]
    return lines


# ---------------------------------------------------------------- 이름 바꾸기
def _rename_pg(conn: Any, old: str, new: str, index_map: dict[str, str]) -> None:
    conn.execute(text(f'ALTER TABLE "{old}" RENAME TO "{new}"'))
    names = conn.execute(
        text("SELECT conname FROM pg_constraint WHERE conrelid = CAST(:t AS regclass)"),
        {"t": new},
    ).scalars()
    for name in list(names):
        renamed = None
        for prefix in ("", "ck_", "uq_"):
            if name.startswith(f"{prefix}{old}_"):
                renamed = f"{prefix}{new}_{name[len(prefix) + len(old) + 1 :]}"
                break
        if renamed:
            conn.execute(text(f'ALTER TABLE "{new}" RENAME CONSTRAINT "{name}" TO "{renamed}"'))
    for name, renamed in index_map.items():
        conn.execute(text(f'ALTER INDEX IF EXISTS "{name}" RENAME TO "{renamed}"'))
    for col in inspect(conn).get_columns(new):  # 자동 번호 시퀀스 (financials_financial_id_seq)
        seq = conn.execute(
            text("SELECT pg_get_serial_sequence(:t, :c)"), {"t": new, "c": col["name"]}
        ).scalar()
        if seq:
            short = seq.split(".")[-1].strip('"')
            if short.startswith(f"{old}_"):
                conn.execute(
                    text(f'ALTER SEQUENCE {seq} RENAME TO "{new}_{short[len(old) + 1 :]}"')
                )


def _rename_sqlite(conn: Any, old: str, new: str, index_map: dict[str, str]) -> None:
    conn.execute(text(f'ALTER TABLE "{old}" RENAME TO "{new}"'))
    # SQLite 는 인덱스 이름을 못 바꿈: 따로 만든 인덱스만 지우고 새 이름으로 다시 만듦
    for name in index_map:
        conn.execute(text(f'DROP INDEX IF EXISTS "{name}"'))
    if new in T.metadata.tables:
        for idx in T.metadata.tables[new].indexes:
            idx.create(conn, checkfirst=True)


def _fx_primary_key(conn: Any) -> None:
    if conn.dialect.name == "postgresql":
        pk = inspect(conn).get_pk_constraint("fx_daily").get("name") or "fx_daily_pkey"
        conn.execute(text(f'ALTER TABLE fx_daily DROP CONSTRAINT "{pk}"'))
        conn.execute(
            text("ALTER TABLE fx_daily ADD CONSTRAINT fx_daily_pkey PRIMARY KEY (pair, date)")
        )
        return
    conn.execute(text("ALTER TABLE fx_daily RENAME TO fx_daily_v1"))
    T.fx_daily.create(conn)
    conn.execute(
        text(
            "INSERT INTO fx_daily (pair, date, rate, source, fetched_at) "
            "SELECT pair, date, rate, source, fetched_at FROM fx_daily_v1"
        )
    )


def apply(conn: Any, repo: SqlRepository, log: Callable[[str], None] = print) -> dict[str, int]:
    """conn 의 트랜잭션 안에서 옮긴다. 확인에 걸리면 MigrationError (아무것도 안 바꿈)."""
    s = survey(conn)
    if not s["v1"]:
        log("v1 스키마가 아님: 할 일 없음")
        return {}
    if s["problems"]:
        raise MigrationError("; ".join(s["problems"]))
    pg = conn.dialect.name == "postgresql"
    for old, new, index_map in RENAMES:
        (_rename_pg if pg else _rename_sqlite)(conn, old, new, index_map)
        log(f"이름 바꿈: {old} → {new}")
    conn.execute(text("ALTER TABLE assets ADD COLUMN exchange VARCHAR(10)"))
    conn.execute(
        text(
            "UPDATE assets SET exchange = market, market = 'KR' WHERE market IN ('KOSPI', 'KOSDAQ')"
        )
    )
    log(f"assets: market KR {s['assets_kr']:,}행")
    _fx_primary_key(conn)
    log("fx_daily: 기본키 (pair, date)")
    n = conn.execute(
        text(
            "UPDATE index_constituent SET ticker = substr(ticker, 1, length(ticker) - 3) "
            "WHERE index_code = 'KOSPI200' AND (ticker LIKE '%.KS' OR ticker LIKE '%.KQ')"
        )
    ).rowcount
    log(f"index_constituent: KOSPI200 티커 {n:,}행 → 6자리 코드")
    add_missing_columns(conn, log)  # v4 GICS 칸 등 (NULL 허용)
    repo._create(conn)  # 새 테이블 + 출처 기본 행 + GICS 분류표 (v1 검사도 다시 함)
    log("새 테이블 만듦: " + ", ".join(NEW_TABLES))
    out = repo.publish_all(conn, log=log)
    log(
        f"계약 테이블 채움: price_daily {out['price_daily']:,}행, "
        f"financials {out['financials']:,}행"
    )
    return out


def transactional(engine: Engine) -> Engine:
    """SQLite 도 DDL 까지 한 트랜잭션으로 묶이게 (pysqlite 기본은 DDL 앞에서 BEGIN 을 안 함)."""
    if engine.dialect.name == "sqlite":

        @event.listens_for(engine, "connect")
        def _no_auto(dbapi_conn: Any, _rec: Any) -> None:
            dbapi_conn.isolation_level = None

        @event.listens_for(engine, "begin")
        def _begin(conn: Any) -> None:
            conn.exec_driver_sql("BEGIN")

    return engine


def run(
    url_text: str,
    *,
    do_apply: bool,
    republish: bool = False,
    log: Callable[[str], None] = print,
) -> int:
    url, args = normalize_db_url(url_text)
    engine = transactional(create_engine(url, connect_args=args))
    try:
        with engine.connect() as conn:
            s = survey(conn)
            for line in plan_lines(s):
                log(line)
            conn.rollback()
        if not s["v1"]:
            missing = missing_tables(s)
            todo = bool(missing or s["columns"] or s["taxonomy"])
            if s["problems"]:
                log("멈춤: " + "; ".join(s["problems"]))
                return 1
            if todo and do_apply:
                repo = SqlRepository(engine, create_tables=False)
                with engine.begin() as conn:
                    add_missing_columns(conn, log)
                    repo._create(conn)  # 없는 테이블 + 출처 기본 행 (있는 것은 그대로)
                    seed_gics_taxonomy(conn, repo._clock(), only_if_empty=False)
                if missing:
                    log("새 테이블 만듦: " + ", ".join(missing))
                if s["taxonomy"]:
                    log(f"gics_taxonomy: {s['taxonomy']}행 넣거나 바꿈")
                s["tables"] |= set(missing)
            elif todo:
                log("확인만 함 (바꾼 것 없음). 실행하려면 --apply")
            if republish and do_apply and set(T.metadata.tables) <= s["tables"]:
                repo = SqlRepository(
                    engine, create_tables=False, price_priority=_price_priority_from_env()
                )
                with engine.begin() as conn:
                    out = repo.publish_all(conn, log=log)
                log(
                    f"다시 채움: price_daily {out['price_daily']:,}행, "
                    f"financials {out['financials']:,}행"
                )
            elif republish:
                log("--republish 는 v2 DB 에서 --apply 와 함께 (확인만 할 때는 바꾸지 않음)")
            return 0
        if not do_apply:
            log("확인만 함 (바꾼 것 없음). 실행하려면 --apply")
            return 1 if s["problems"] else 0
        if s["problems"]:
            log("멈춤: 위 사유를 먼저 해결")
            return 1
        repo = SqlRepository(engine, create_tables=False, price_priority=_price_priority_from_env())
        try:
            with engine.begin() as conn:
                apply(conn, repo, log)
        except MigrationError as exc:
            log(f"멈춤 (바꾼 것 없음): {exc}")
            return 1
        log("완료. 다음: python backend/scripts/make_db_roles.py (읽기·쓰기 계정 권한)")
        return 0
    finally:
        engine.dispose()


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument("url", nargs="?", help="DB 주소 (없으면 .env 의 DATABASE_URL)")
    p.add_argument("--apply", action="store_true", help="실제로 옮김 (없으면 확인만)")
    p.add_argument(
        "--republish",
        action="store_true",
        help="v2 DB: 원본으로 계약 price_daily·financials 를 다시 고름 (우선순위를 바꾼 뒤)",
    )
    a = p.parse_args(argv)
    url = a.url or default_db_url()
    print(f"DB: {_mask(url)}")
    return run(url, do_apply=a.apply, republish=a.republish)


if __name__ == "__main__":
    raise SystemExit(main())
