"""팀원용 읽기 전용 DB 계정(reader) 만들기. .env 의 DB 주소(마스터 계정)로 접속해 실행한다.

python scripts/make_reader.py                  # .env 기준, 비밀번호는 화면에 안 보이게 입력
python scripts/make_reader.py "postgres://..." # 주소를 직접 줘서

- 이미 있으면 비밀번호와 제한만 다시 맞춤 (몇 번 실행해도 됨)
- 읽기만 (SELECT), 기본이 읽기 전용 트랜잭션, 쿼리 하나 5분 제한, 동시 연결 10개
- 끝나면 reader 로 다시 접속해 읽기는 되고 지우기는 막히는지 확인
- 비밀번호는 영문·숫자와 _ - . ~ ! * 만 (주소에 그대로 넣을 수 있게), 12자 이상
"""

from __future__ import annotations

import getpass
import os
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from sqlalchemy import create_engine, text  # noqa: E402
from sqlalchemy.exc import DBAPIError  # noqa: E402

from myfinsight.data.repository import default_db_url, normalize_db_url  # noqa: E402

ROLE = "reader"
_OK_PASSWORD = re.compile(r"[A-Za-z0-9_\-.~!*]{12,}")


def _password() -> str:
    pw = os.environ.get("READER_PASSWORD")  # 자동 실행용 (보통은 입력)
    if not pw:
        pw = getpass.getpass(f"{ROLE} 비밀번호 (12자 이상, 화면에 안 보임): ")
        if getpass.getpass("한 번 더: ") != pw:
            raise SystemExit("두 번 입력한 비밀번호가 다름")
    if not _OK_PASSWORD.fullmatch(pw):
        raise SystemExit("비밀번호는 12자 이상, 영문·숫자와 _ - . ~ ! * 만 가능")
    return pw


def main() -> int:
    url, args = normalize_db_url(sys.argv[1] if len(sys.argv) > 1 else default_db_url())
    if url.get_backend_name() != "postgresql":
        raise SystemExit("PostgreSQL 주소가 아님 (.env 의 DATABASE_URL 확인)")
    db = url.database
    pw = _password()
    lit = "'" + pw.replace("'", "''") + "'"
    master = create_engine(url, connect_args=args, isolation_level="AUTOCOMMIT")
    with master.connect() as c:
        exists = c.execute(text("SELECT 1 FROM pg_roles WHERE rolname = :r"), {"r": ROLE}).first()
        verb = "ALTER" if exists else "CREATE"
        c.execute(text(f"{verb} ROLE {ROLE} LOGIN PASSWORD {lit}"))
        for sql in (
            f'GRANT CONNECT ON DATABASE "{db}" TO {ROLE}',
            f"GRANT USAGE ON SCHEMA public TO {ROLE}",
            f"GRANT SELECT ON ALL TABLES IN SCHEMA public TO {ROLE}",
            f"ALTER DEFAULT PRIVILEGES IN SCHEMA public GRANT SELECT ON TABLES TO {ROLE}",
            f"ALTER ROLE {ROLE} SET default_transaction_read_only = on",
            f"ALTER ROLE {ROLE} SET statement_timeout = '5min'",
            f"ALTER ROLE {ROLE} CONNECTION LIMIT 10",
        ):
            c.execute(text(sql))
    master.dispose()
    print(f"{ROLE} 계정 {'갱신' if exists else '만듦'}")

    reader = create_engine(url.set(username=ROLE, password=pw), connect_args=args)
    try:
        with reader.connect() as c:
            n = c.execute(text("SELECT count(*) FROM assets")).scalar_one()
            print(f"확인: 읽기 됨 (assets {n:,}행)")
            try:
                c.execute(text("DELETE FROM assets WHERE false"))
                print("확인 실패: 지우기가 막히지 않음")
                return 1
            except DBAPIError:
                print("확인: 지우기는 막힘")
    finally:
        reader.dispose()
    host = f"{url.host}:{url.port or 5432}"
    print(f"팀원 주소: postgresql://{ROLE}:비밀번호@{host}/{db}?sslmode=require")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
