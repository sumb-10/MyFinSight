"""disclosures 의 event_type 을 지금 유형 규칙(collectors/disclosures/categories.py)으로 다시 매김.

python backend/scripts/reclassify_disclosures.py           # 확인만 (바뀔 행 수·유형별 이동)
python backend/scripts/reclassify_disclosures.py --apply   # 실행 (event_type·rule_version 만 바꿈)

rule_version 이 지금 버전과 다른 행만 본다 (행을 지우거나 더하지 않음). 몇 번 돌려도 같다.
"""

from __future__ import annotations

import argparse
import sys
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from sqlalchemy import bindparam, select, update  # noqa: E402

from backend.collectors.disclosures import categories as cat  # noqa: E402
from backend.db import open_repository  # noqa: E402
from backend.db import tables as T  # noqa: E402


def new_event(row: object) -> tuple[str, str]:
    if row.source == "DART":
        return cat.dart_event(row.title or row.form or "")
    from backend.collectors.disclosures.update import NY

    items = row._mapping["items"]  # Row.items 는 메서드라 이름으로
    return cat.sec_event(row.form or "", items, row.filed_at.astimezone(NY).date())


def current(source: str) -> list[str]:
    if source == "DART":
        return [f"dart-{cat.DART_RULE_VERSION}"]
    return [f"sec-{cat.SEC_RULE_VERSION}", f"sec-old-{cat.SEC_RULE_VERSION}"]


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument("--apply", action="store_true", help="실제로 UPDATE (없으면 확인만)")
    a = p.parse_args(argv)
    repo = open_repository()
    d = T.disclosures
    changes: list[dict] = []
    moves: Counter = Counter()
    with repo.engine.connect() as c:
        for source in ("SEC_EDGAR", "DART"):
            q = select(d.c.disclosure_id, d.c.source, d.c.form, d.c["items"], d.c.title,
                       d.c.filed_at, d.c.event_type, d.c.rule_version).where(
                d.c.source == source, d.c.rule_version.not_in(current(source)))  # fmt: skip
            for row in c.execute(q):
                event, rule = new_event(row)
                if (event, rule) != (row.event_type, row.rule_version):
                    changes.append({"i": row.disclosure_id, "e": event, "r": rule})
                    if event != row.event_type:
                        moves[(source, row.event_type, event)] += 1
    print(f"다시 매길 행: {len(changes):,} (유형이 바뀌는 행 {sum(moves.values()):,})")
    for (source, old, new), n in moves.most_common(20):
        print(f"  {source}: {old} → {new}  {n:,}")
    if not a.apply:
        print("확인만 함. 실행하려면 --apply")
        return 0
    stmt = (
        update(d)
        .where(d.c.disclosure_id == bindparam("i"))
        .values(event_type=bindparam("e"), rule_version=bindparam("r"))
    )
    with repo.engine.begin() as c:
        for i in range(0, len(changes), 5000):
            c.execute(stmt, changes[i : i + 5000])
    print(f"바꿈: {len(changes):,}행")
    repo.engine.dispose()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
