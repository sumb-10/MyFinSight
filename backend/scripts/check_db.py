"""DB 연결 확인: .env 의 DB 설정으로 접속해 테이블을 만들고 상태를 출력한다 (데이터는 안 바꿈).

python backend/scripts/check_db.py                     # .env 기준
python backend/scripts/check_db.py "postgres://..."    # 주소를 직접 줘서 확인
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from sqlalchemy import func, inspect, select  # noqa: E402

from backend.db import default_db_url, open_repository  # noqa: E402
from backend.db import tables as T  # noqa: E402


def _mask(url: str) -> str:
    if "@" not in url or "://" not in url:
        return url
    head, tail = url.split("://", 1)
    return f"{head}://***@{tail.split('@', 1)[1]}"


def main() -> int:
    url = sys.argv[1] if len(sys.argv) > 1 else default_db_url()
    print(f"접속: {_mask(url)}")
    repo = open_repository(url)
    eng = repo.engine
    print(f"DB 종류: {eng.dialect.name} (드라이버 {eng.dialect.driver})")
    names = sorted(inspect(eng).get_table_names())
    print(f"테이블 {len(names)}개: {', '.join(names)}")
    with eng.connect() as c:
        for t in (
            T.data_sources,
            T.index_constituent,
            T.price_daily,
            T.price_daily_source,
            T.fx_daily,
            T.financials,
            T.financials_source,
            T.valuation_daily,
            T.gics_taxonomy,
        ):
            n = c.execute(select(func.count()).select_from(t)).scalar_one()
            print(f"  {t.name:<18} {n:>10,}행")
        n = c.execute(select(func.count()).select_from(T.news)).scalar_one()
        print(f"  {'news':<18} {n:>10,}행")
    return 0 if set(T.metadata.tables) <= set(names) else 1


if __name__ == "__main__":
    raise SystemExit(main())
