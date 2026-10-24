"""FNSPID 미국 뉴스 CSV 를 news 에 넣기 (collectors/news/fnspid.py).

python backend/scripts/load_fnspid.py D:/workup/data/fnspid/All_external.csv
python backend/scripts/load_fnspid.py <파일> --max-minutes 120      # 2시간 하고 멈춤 (다시 돌리면 이어서)
python backend/scripts/load_fnspid.py <파일> --since 2015-01-01      # 그 뒤 기사만
curl -L <Hugging Face 주소> | python backend/scripts/load_fnspid.py - --name nasdaq_exteral_data.csv
                                       # 디스크에 저장하지 않고 받으면서 넣기 (22GB 파일)

- 파일은 Hugging Face Zihan1004/FNSPID 의 Stock_news/All_external.csv (5.5GB) 를 미리 받아 둔다.
- 끊겨도 같은 명령(같은 --chunk)이면 끝난 덩어리는 건너뛴다. 긴 백필과 같이 돌아도 된다.
"""

from __future__ import annotations

import argparse
import sys
import time
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from backend.collectors.common import Deadline, Forever, JobSettings  # noqa: E402
from backend.collectors.news.fnspid import fnspid_load  # noqa: E402
from backend.db import open_repository  # noqa: E402


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument("file", type=Path, help='CSV 경로 ("-" 면 표준 입력, --name 필요)')
    p.add_argument("--name", help="이어 받기 기록용 파일 이름 (표준 입력일 때)")
    p.add_argument(
        "--max-minutes", type=float, default=0, help="이 시간이 지나면 멈춤 (0 = 끝까지)"
    )
    p.add_argument("--since", type=date.fromisoformat, help="이 날 이후 기사만")
    p.add_argument("--until", type=date.fromisoformat, help="이 날 전 기사만 (그날은 빼고)")
    p.add_argument("--chunk", type=int, default=200_000, help="한 번에 읽어 저장할 행 수")
    a = p.parse_args(argv)
    if str(a.file) == "-" and not a.name:
        p.error("표준 입력은 --name 이 필요함 (예: nasdaq_exteral_data.csv)")
    if str(a.file) != "-" and not a.file.exists():
        p.error(f"파일 없음: {a.file}")
    t0 = time.monotonic()

    def say(msg: str) -> None:
        m, s = divmod(int(time.monotonic() - t0), 60)
        print(f"[{m // 60:02d}:{m % 60:02d}:{s:02d}] {msg}", flush=True)

    repo = open_repository()
    deadline = Deadline(a.max_minutes * 60) if a.max_minutes > 0 else Forever()
    r = fnspid_load(repo, JobSettings.from_env(), path=a.file, deadline=deadline,
                    chunk=a.chunk, since=a.since,
        until=a.until, progress=say, name=a.name)  # fmt: skip
    say(f"{'끝' if r.done else '시간 제한으로 멈춤 (다시 돌리면 이어서)'}: {dict(r.counts)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
