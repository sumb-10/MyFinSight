"""KOSPI200 구성종목 파일 만들기 (make_constituents_csv.py --index KOSPI200 와 같음).

python scripts/make_kospi200_csv.py --as-of 2026-10-05
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from make_constituents_csv import main  # noqa: E402

if __name__ == "__main__":
    raise SystemExit(main(default_index="KOSPI200"))
