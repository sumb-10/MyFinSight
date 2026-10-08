"""PC 의 SQLite DB 를 서버 PostgreSQL 로 그대로 복사한다 (최초 업로드용, 원본은 안 바꿈).

python scripts/copy_sqlite_to_pg.py "postgresql://사용자:비번@호스트:5432/myfinsight?sslmode=require"
python scripts/copy_sqlite_to_pg.py "주소" --from data/myfinsight.db --batch 50000

- 대상 DB 에 테이블이 없으면 만든다 (open_repository).
- 이미 있는 행(같은 키)은 건너뛰므로 중간에 끊겨도 같은 명령을 다시 돌리면 이어서 채운다.
- 끝나면 자동 번호(fetch_log.id, news.news_id 등)를 복사한 최댓값 뒤로 맞춘다.
"""

from __future__ import annotations

import argparse
import csv
import io
import json
import sys
import time
from datetime import UTC, datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from sqlalchemy import JSON, func, select, text  # noqa: E402

from myfinsight.data.repository import open_repository  # noqa: E402
from myfinsight.data.repository import tables as T  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]


def _mask(url: str) -> str:
    if "@" not in url or "://" not in url:
        return url
    head, tail = url.split("://", 1)
    return f"{head}://***@{tail.split('@', 1)[1]}"


def _cell(v: object, col) -> str:  # noqa: ANN001
    if v is None:
        return "\\N"
    if isinstance(col.type, JSON) or isinstance(v, (dict, list)):
        return json.dumps(v, ensure_ascii=False)
    if isinstance(v, datetime):
        return v.isoformat() if v.tzinfo else v.replace(tzinfo=UTC).isoformat()
    if isinstance(v, float):
        return repr(v)
    return str(v)


def _csv(part, table) -> io.BytesIO:  # noqa: ANN001
    buf = io.StringIO()
    w = csv.writer(buf, lineterminator="\n")
    for r in part:
        w.writerow([_cell(v, c) for v, c in zip(r, table.columns, strict=True)])
    return io.BytesIO(buf.getvalue().encode("utf-8"))


def copy_all(src_url: str, dst_url: str, batch: int = 50000, log=print) -> dict[str, int]:  # noqa: ANN001
    src = open_repository(src_url).engine
    dst = open_repository(dst_url).engine
    if dst.dialect.name != "postgresql":
        raise SystemExit(f"대상이 PostgreSQL 이 아님: {dst.dialect.name}")
    copied: dict[str, int] = {}
    for table in T.metadata.sorted_tables:  # 외래키 순서 (data_sources, assets 먼저)
        with src.connect() as s:
            total = s.execute(select(func.count()).select_from(table)).scalar_one()
        if total == 0:
            continue
        cols = [c.name for c in table.columns]
        col_sql = ", ".join(f'"{c}"' for c in cols)
        done, t0 = 0, time.monotonic()
        with src.connect() as s:
            rows = s.execution_options(yield_per=batch).execute(select(table))
            for part in rows.partitions():
                raw = dst.raw_connection()  # COPY 로 임시 테이블에 넣고, 겹치는 행은 건너뛰며 옮김
                try:
                    cur = raw.cursor()
                    cur.execute(f'CREATE TEMP TABLE _copy (LIKE "{table.name}") ON COMMIT DROP')
                    cur.execute(
                        f"COPY _copy ({col_sql}) FROM STDIN WITH (FORMAT csv, NULL '\\N')",
                        stream=_csv(part, table),
                    )
                    cur.execute(
                        f'INSERT INTO "{table.name}" ({col_sql}) SELECT {col_sql} FROM _copy '
                        "ON CONFLICT DO NOTHING"
                    )
                    raw.commit()
                finally:
                    raw.close()
                done += len(part)
                log(f"  {table.name:<18} {done:>10,} / {total:,}  ({time.monotonic() - t0:,.0f}초)")
        copied[table.name] = done
    with dst.begin() as d:  # 자동 번호를 복사한 값 뒤로
        for table in T.metadata.sorted_tables:
            for col in table.primary_key.columns:
                if col.autoincrement is True:
                    d.execute(
                        text(
                            f"SELECT setval(pg_get_serial_sequence('{table.name}', '{col.name}'), "
                            f"COALESCE((SELECT MAX({col.name}) FROM {table.name}), 0) + 1, false)"
                        )
                    )
    return copied


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument("to", help="대상 PostgreSQL 주소")
    p.add_argument("--from", dest="src", default=str(ROOT / "data" / "myfinsight.db"))
    p.add_argument("--batch", type=int, default=50000, help="한 번에 보내는 행 수")
    a = p.parse_args()
    if not Path(a.src).exists():
        print(f"SQLite 파일이 없음: {a.src}")
        return 1
    print(f"원본: {a.src}\n대상: {_mask(a.to)}")
    copied = copy_all(f"sqlite:///{a.src}", a.to, a.batch)
    print("완료: " + ", ".join(f"{k} {v:,}" for k, v in copied.items()))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
