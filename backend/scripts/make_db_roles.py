"""분석 쪽 DB 계정 2개 권한 맞추기 (데이터 계약 module_prototype2 2.2절: 읽기 계정·쓰기 계정).

python backend/scripts/make_db_roles.py                  # 실행할 SQL 만 보여 줌 (기본, DB 에 접속 안 함)
python backend/scripts/make_db_roles.py --apply          # .env 의 DATABASE_URL(마스터 계정)로 실행
python backend/scripts/make_db_roles.py "postgres://..." --apply

- 읽기 계정 (기본 이름 myfinsight_read): 계약 읽기 테이블 6개(assets, index_constituent,
  price_daily, fx_daily, financials, news) + fetch_log + valuation_daily(계약 밖 추가 발행 테이블:
  일별 PER·PBR·ROE·배당수익률) + gics_taxonomy(GICS 분류표 참조 테이블) + disclosures(공시 목록)
  의 SELECT 만.
  읽기 전용 트랜잭션.
- 쓰기 계정 (기본 이름 myfinsight_write): 읽기 계정 권한 + run_step·run_artifact·report 의
  SELECT·INSERT·UPDATE (DELETE 없음). 그 밖의 테이블(원본 *_source 등)은 권한 없음.
- 비밀번호는 환경변수로만 받는다: MYFINSIGHT_READ_PASSWORD, MYFINSIGHT_WRITE_PASSWORD
  (화면·로그에 찍지 않음, SQL 출력에는 '***'). 영문·숫자와 _ - . ~ ! * 만, 12자 이상.
- 몇 번 실행해도 됨: 있으면 비밀번호만 바꾸고, 권한은 먼저 모두 거둔 뒤 위 목록만 다시 준다.
- 팀원용 reader 계정(backend/scripts/make_reader.py, 모든 테이블 SELECT)은 그대로 둔다.
- 먼저 backend/scripts/migrate_v2.py --apply 로 새 테이블이 있어야 한다.
"""

from __future__ import annotations

import argparse
import os
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from sqlalchemy import create_engine, text  # noqa: E402

from backend.db import default_db_url, normalize_db_url  # noqa: E402

READ_TABLES = (
    "assets",
    "index_constituent",
    "price_daily",
    "fx_daily",
    "financials",
    "news",
    "fetch_log",
    "valuation_daily",
    "gics_taxonomy",
    "disclosures",
)
"""읽기 계정이 읽는 테이블: 계약 읽기 테이블 6개 + fetch_log (데이터 마감·결측 사유)
+ valuation_daily (수집기가 계산해 싣는 일별 가치평가, M3-04 pe_ttm·roe_ttm·dividend_yield_ttm)
+ gics_taxonomy (GICS 분류표 참조 테이블, Module2 §5 종목 검색용 사전)
+ disclosures (SEC EDGAR·DART 공시 목록과 유형, v5)."""
WRITE_TABLES = ("run_step", "run_artifact", "report")
"""쓰기 계정이 쓰는 테이블 (계약 쓰기 테이블 3개, K1: 새 테이블 없음)."""
PASSWORD_ENV = {"read": "MYFINSIGHT_READ_PASSWORD", "write": "MYFINSIGHT_WRITE_PASSWORD"}
_OK_PASSWORD = re.compile(r"[A-Za-z0-9_\-.~!*]{12,}")
_OK_NAME = re.compile(r"[a-z_][a-z0-9_]{0,62}")
MASK = "'***'"


def role_sql(role: str, db: str, *, write: bool, password_literal: str = MASK) -> list[str]:
    """한 계정의 권한 SQL (계정 만들기·비밀번호는 apply 에서 따로). password_literal 은 출력용."""
    tables = ", ".join(READ_TABLES)
    out = [
        f"-- {role}: CREATE ROLE {role} LOGIN PASSWORD {password_literal}"
        " (이미 있으면 ALTER ROLE ... PASSWORD)",
        f"REVOKE ALL ON ALL TABLES IN SCHEMA public FROM {role}",
        f"REVOKE ALL ON ALL SEQUENCES IN SCHEMA public FROM {role}",
        f'GRANT CONNECT ON DATABASE "{db}" TO {role}',
        f"GRANT USAGE ON SCHEMA public TO {role}",
        f"GRANT SELECT ON {tables} TO {role}",
        f"ALTER ROLE {role} SET statement_timeout = '5min'",
        f"ALTER ROLE {role} CONNECTION LIMIT 10",
    ]
    if write:
        out.append(f"GRANT SELECT, INSERT, UPDATE ON {', '.join(WRITE_TABLES)} TO {role}")
        out.append(f"ALTER ROLE {role} SET default_transaction_read_only = off")
    else:
        out.append(f"ALTER ROLE {role} SET default_transaction_read_only = on")
    return out


def _password(kind: str) -> str:
    env = PASSWORD_ENV[kind]
    pw = os.environ.get(env, "")
    if not pw:
        raise SystemExit(f"환경변수 {env} 가 비어 있음 (비밀번호는 환경변수로만 받음)")
    if not _OK_PASSWORD.fullmatch(pw):
        raise SystemExit(f"{env}: 12자 이상, 영문·숫자와 _ - . ~ ! * 만 가능")
    return pw


def check_rows(conn, roles: dict[str, str]) -> list[tuple[str, str, str, bool]]:  # noqa: ANN001
    """(계정, 테이블, 권한, 있음) 목록. 마스터 계정으로 has_table_privilege 확인."""
    rows = []
    for role in roles.values():
        for table in (*READ_TABLES, *WRITE_TABLES, "price_daily_source"):
            for priv in ("SELECT", "INSERT", "UPDATE", "DELETE"):
                ok = conn.execute(
                    text("SELECT has_table_privilege(:r, :t, :p)"),
                    {"r": role, "t": f"public.{table}", "p": priv},
                ).scalar_one()
                rows.append((role, table, priv, bool(ok)))
    return rows


def expected(kind: str, table: str, priv: str) -> bool:
    """계약대로라면 있어야 하는 권한인가."""
    if table in READ_TABLES:
        return priv == "SELECT"
    if table in WRITE_TABLES:
        return kind == "write" and priv in ("SELECT", "INSERT", "UPDATE")
    return False


def apply(url_text: str, roles: dict[str, str]) -> int:
    url, args = normalize_db_url(url_text)
    if url.get_backend_name() != "postgresql":
        raise SystemExit("PostgreSQL 주소가 아님 (.env 의 DATABASE_URL 확인)")
    passwords = {kind: _password(kind) for kind in roles}
    engine = create_engine(url, connect_args=args)
    try:
        with engine.begin() as c:
            for kind, role in roles.items():
                exists = c.execute(
                    text("SELECT 1 FROM pg_roles WHERE rolname = :r"), {"r": role}
                ).first()
                lit = "'" + passwords[kind].replace("'", "''") + "'"
                verb = "ALTER" if exists else "CREATE"
                c.execute(text(f"{verb} ROLE {role} LOGIN PASSWORD {lit}"))
                for sql in role_sql(role, url.database or "", write=kind == "write")[1:]:
                    c.execute(text(sql))
                print(f"{role}: {'갱신' if exists else '만듦'}")
        with engine.connect() as c:
            wrong = [
                r
                for r in check_rows(c, roles)
                if r[3] != expected(next(k for k, v in roles.items() if v == r[0]), r[1], r[2])
            ]
    finally:
        engine.dispose()
    if wrong:
        print("확인 실패 (계정, 테이블, 권한, 있음):")
        for r in wrong:
            print(f"  {r}")
        return 1
    print(
        "확인: 읽기 계정은 읽기 테이블 SELECT 만, 쓰기 계정은 + 실행 기록 3개 SELECT·INSERT·UPDATE"
    )
    return 0


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument("url", nargs="?", help="마스터 계정 DB 주소 (없으면 .env 의 DATABASE_URL)")
    p.add_argument("--apply", action="store_true", help="실제로 실행 (없으면 SQL 만 출력)")
    p.add_argument("--reader", default="myfinsight_read", help="읽기 계정 이름")
    p.add_argument("--writer", default="myfinsight_write", help="쓰기 계정 이름")
    a = p.parse_args(argv)
    roles = {"read": a.reader, "write": a.writer}
    for name in roles.values():
        if not _OK_NAME.fullmatch(name):
            raise SystemExit(f"계정 이름은 소문자·숫자·_ 만: {name}")
    if not a.apply:
        db = "myfinsight"
        if a.url:
            db = normalize_db_url(a.url)[0].database or db
        for kind, role in roles.items():
            print(f"-- {kind} 계정 (비밀번호: 환경변수 {PASSWORD_ENV[kind]})")
            for sql in role_sql(role, db, write=kind == "write"):
                print(sql if sql.startswith("--") else sql + ";")
            print()
        print("-- 실행하려면 --apply (마스터 계정 주소, 비밀번호 환경변수 두 개 필요)")
        return 0
    return apply(a.url or default_db_url(), roles)


if __name__ == "__main__":
    raise SystemExit(main())
