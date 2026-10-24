"""FNSPID (Hugging Face Zihan1004/FNSPID, Stock_news/All_external.csv) 로 미국 뉴스 보충.

1999~2023년 미국 종목 기사 목록(날짜·제목·종목·URL·언론사). 받은 CSV 파일을 읽어 우리 미국 대상
종목(universe) 기사만 news 에 넣는다 (source FNSPID, language en, 본문은 넣지 않음).
- 파일이 커서(5.5GB) chunk 행씩 나눠 읽고, 덩어리마다 저장한 뒤 fetch_log 에 남긴다
  (target = fnspid:<파일 이름>:<덩어리 번호>). 끊겨도 같은 명령이면 끝난 덩어리는 건너뛴다.
- 같은 (종목, url) 은 한 번만 (news 의 url_hash 키). Alpaca News(Benzinga) 와 같은 기사는 겹치지 않음.
- Stock_symbol 은 BRK.B 처럼 점을 쓸 수 있어 yfinance 표기(BRK-B)로 맞춘다.
"""

from __future__ import annotations

import csv
import io
import sys
from collections.abc import Iterator
from datetime import UTC, date, datetime
from pathlib import Path
from typing import Any

from backend.collectors.common import (
    JobResult,
    JobSettings,
    Progress,
    ensure_assets,
    log_row,
    universe,
)
from backend.db.base import ExtendedRepository
from backend.pipeline.normalizer import default_asset, is_kr_symbol, normalize_ticker
from backend.schemas.market_ext import NewsRow

SOURCE = "FNSPID"
PREFIX = "fnspid:"


def _rows(path: Path) -> Iterator[dict[str, str]]:
    csv.field_size_limit(min(sys.maxsize, 2**31 - 1))  # 본문 칸이 아주 긴 행이 있음
    if str(path) == "-":  # 받으면서 바로 읽기 (curl ... | load_fnspid.py - --name 파일이름)
        stdin = io.TextIOWrapper(sys.stdin.buffer, encoding="utf-8", errors="replace", newline="")
        yield from csv.DictReader(stdin)
        return
    with path.open(encoding="utf-8", newline="", errors="replace") as f:
        yield from csv.DictReader(f)


def parse_time(text: str) -> datetime | None:
    """'2020-06-05 06:30:54 UTC' 또는 '2020-06-05' → UTC 시각."""
    t = (text or "").strip().removesuffix(" UTC")
    if not t:
        return None
    try:
        d = datetime.fromisoformat(t)
    except ValueError:
        return None
    return d.replace(tzinfo=UTC) if d.tzinfo is None else d.astimezone(UTC)


def to_news(r: dict[str, str], symbol: str, at: datetime) -> NewsRow | None:
    url, title = (r.get("Url") or "").strip(), (r.get("Article_title") or "").strip()
    published = parse_time(r.get("Date") or "")
    if not url.startswith("http") or not title or published is None:
        return None
    return NewsRow(
        asset_id=default_asset(symbol).asset_id,
        source=SOURCE,
        url=url,
        title=title[:1000],
        publisher=(r.get("Publisher") or "").strip()[:200] or None,
        published_at=published,
        language="en",
        query=symbol,
        fetched_at=at,
    )


def fnspid_load(
    repo: ExtendedRepository,
    settings: JobSettings,
    *,
    path: Path,
    deadline: Any,
    chunk: int = 200_000,
    since: date | None = None,
    until: date | None = None,
    progress: Progress | None = None,
    name: str | None = None,
) -> JobResult:
    """CSV 를 chunk 행씩 읽어 대상 종목 기사만 저장. since 를 주면 그날 이후, until 을 주면 그날 전 기사만.
    name: 이어 받기 기록에 쓸 파일 이름 (path 가 "-" 표준 입력일 때)."""
    res = JobResult("news_backfill:FNSPID")
    names = universe(repo, settings)
    wanted = {t for t in names if not is_kr_symbol(t) and t not in settings.etfs}
    ensure_assets(repo, {t: names[t] for t in wanted})
    name = name or path.name
    done = repo.fetch_targets_done(SOURCE, f"{PREFIX}{name}:")
    floor = datetime.combine(since, datetime.min.time(), tzinfo=UTC) if since else None
    ceil = datetime.combine(until, datetime.min.time(), tzinfo=UTC) if until else None
    buf: list[dict[str, str]] = []
    n_chunk = 0

    def flush() -> None:
        nonlocal buf, n_chunk
        target = f"{PREFIX}{name}:{n_chunk}"
        part, buf = buf, []
        n_chunk += 1
        if target in done:
            return
        at = datetime.now(UTC)
        rows = []
        for r in part:
            sym = normalize_ticker((r.get("Stock_symbol") or "").strip().replace(".", "-"))
            if sym not in wanted:
                continue
            if (row := to_news(r, sym, at)) is not None and (
                (floor is None or row.published_at >= floor)
                and (ceil is None or row.published_at < ceil)
            ):
                rows.append(row)
        stored = repo.upsert_news(rows) if rows else 0
        repo.log_fetches(SOURCE, [log_row(target, since or date(1999, 1, 1), at.date(), at,
                                          None, len(rows))])  # fmt: skip
        res.counts["matched"] += len(rows)
        res.counts["stored"] += stored
        res.counts["chunks"] += 1
        if progress:
            progress(f"[news FNSPID] 덩어리 {n_chunk}: 읽은 행 {res.counts['read']:,}, "
                     f"대상 기사 {res.counts['matched']:,} · 새로 저장 {res.counts['stored']:,}")  # fmt: skip

    for r in _rows(path):
        buf.append(r)
        res.counts["read"] += 1
        if len(buf) >= chunk:
            if deadline.over():
                res.done = False
                return res
            flush()
    if buf and not deadline.over():
        flush()
    elif buf:
        res.done = False
    return res
