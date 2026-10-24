"""종목 검색용 사전 만들기 (Module2 §5): DB → backend/data/processed/<universe>_descriptor_<날짜>.json.

python backend/scripts/build_descriptor.py                        # SP500·NDX·KOSPI200·ALL, 스냅샷 날짜마다
python backend/scripts/build_descriptor.py --universe ALL --latest  # ALL 의 가장 최근 버전만
python backend/scripts/build_descriptor.py --db "postgres://..." --out backend/data/processed

- DB 만 읽는다 (assets, index_constituent, gics_taxonomy). 읽기 전용 연결이라 읽기 계정
  (myfinsight_read) 주소로도 된다. 인터넷·LLM 을 쓰지 않는다.
- 스냅샷 날짜마다 버전 파일 하나. 내용이 같으면 다시 쓰지 않는다 (generated_at 유지).
  가장 최근 버전은 <universe>_descriptor.json 에도 복사, 목록은 <universe>_descriptor_versions.json.
- GICS 가 없는 종목·당시 구성종목 미확보 같은 한계는 각 파일의 limitations 와 화면에 나온다.
먼저: python backend/scripts/migrate_v2.py --apply (gics_taxonomy·GICS 칸)
     python backend/scripts/backfill.py --what gics (종목별 GICS·사업 설명)
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT.parent))

from backend.db import default_db_url  # noqa: E402
from backend.db.readers import (  # noqa: E402
    descriptor_inputs,
    mask_url,
    readonly_engine,
)
from backend.pipeline.descriptor import (  # noqa: E402
    UNIVERSES,
    build_descriptors,
    write_descriptors,
)
from backend.schemas.market import IndexCode  # noqa: E402


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument(
        "--universe",
        default="SP500,NDX,KOSPI200,ALL",
        help="SP500,NDX,KOSPI200,ALL 중 (쉼표로 여러 개)",
    )
    p.add_argument("--latest", action="store_true", help="가장 최근 스냅샷 버전만")
    p.add_argument("--out", type=Path, default=ROOT / "data" / "processed", help="출력 폴더")
    p.add_argument("--db", help="DB 주소 (없으면 .env 의 DATABASE_URL)")
    a = p.parse_args(argv)
    universes = [u.strip().upper() for u in a.universe.split(",") if u.strip()]
    bad = [u for u in universes if u not in UNIVERSES]
    if bad:
        p.error(f"모르는 유니버스: {bad} (가능: {', '.join(UNIVERSES)})")
    url = a.db or default_db_url()
    print(f"DB: {mask_url(url)} (읽기 전용)")
    engine = readonly_engine(url)
    try:
        with engine.connect() as conn:
            inputs = descriptor_inputs(conn, list(IndexCode))
    except RuntimeError as exc:
        print(f"멈춤: {exc}")
        return 1
    finally:
        engine.dispose()
    if not inputs["taxonomy"]:
        print("gics_taxonomy 가 비어 있음: python backend/scripts/migrate_v2.py --apply")
        return 1
    worst = 0
    for u in universes:
        docs = build_descriptors(inputs, u, only_latest=a.latest)
        if not docs:
            print(f"{u}: 구성종목 스냅샷 없음 (python -m backend.jobs.daily meta 먼저)")
            worst = 1
            continue
        for (path, changed), doc in zip(write_descriptors(docs, a.out, u), docs, strict=True):
            mark = "새로 씀" if changed else "같음"
            print(f"{u} {doc['snapshot_date']}: {doc['count']}종목 → {path.name} ({mark})")
            for line in doc["limitations"]:
                print(f"   - {line}")
    return worst


if __name__ == "__main__":
    raise SystemExit(main())
