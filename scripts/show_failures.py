"""수집 실패 사유 보기: fetch_log 의 FAILED 기록을 출처별로 최근 몇 개씩 출력 (데이터는 안 바꿈).

python scripts/show_failures.py            # 출처별 최근 3개
python scripts/show_failures.py DART 10    # DART 만 최근 10개
python scripts/show_failures.py --reset DART   # DART 실패 기록 지우기 (원인을 고친 뒤 다시 받게)

같은 대상이 성공 없이 3번 실패하면 수집 작업이 그 대상을 건너뛴다. 출처 쪽 문제(연결 끊김 등)를
고친 뒤에는 --reset 으로 실패 기록을 지워야 다시 받는다. 성공 기록은 지우지 않는다.
"""

from __future__ import annotations

import sys
from collections import Counter, defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from sqlalchemy import delete  # noqa: E402

from myfinsight.data.repository import open_repository  # noqa: E402
from myfinsight.data.repository import tables as T  # noqa: E402


def reset(source: str) -> int:
    repo = open_repository()
    f = T.fetch_log
    with repo.engine.begin() as c:
        n = c.execute(delete(f).where(f.c.source == source, f.c.status == "FAILED")).rowcount
    print(f"[{source}] 실패 기록 {n}건 지움")
    return 0


def main() -> int:
    if len(sys.argv) > 2 and sys.argv[1] == "--reset":
        return reset(sys.argv[2].upper())
    only = sys.argv[1].upper() if len(sys.argv) > 1 else None
    n = int(sys.argv[2]) if len(sys.argv) > 2 else 3
    rows = [r for r in open_repository().fetch_history() if r["status"] == "FAILED"]
    if only:
        rows = [r for r in rows if r["source"] == only]
    if not rows:
        print("실패 기록 없음")
        return 0
    by: dict[str, list[dict]] = defaultdict(list)
    for r in rows:
        by[r["source"]].append(r)
    for source, items in sorted(by.items()):
        reasons = Counter((r["error"] or "")[:120] for r in items)
        print(f"[{source}] 실패 {len(items)}건, 사유 {len(reasons)}종류")
        for reason, cnt in reasons.most_common(n):
            print(f"  {cnt}건: {reason}")
        print("  최근 대상:", ", ".join(r["target"] for r in items[-n:]))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
