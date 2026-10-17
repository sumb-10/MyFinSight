"""뉴스 매일 수집: 줄(NEWS_LANES)마다 오래 안 받은 종목부터 하루 한도만큼, 종목·날짜당
NEWS_PER_TICKER_DAY 건. NEWS_KEEP_DAYS 보다 오래된 기사 삭제 (0 이하면 지우지 않음)."""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Iterable
from datetime import UTC, date, datetime, timedelta
from typing import Any

from backend.adapters.base import NO_DATA
from backend.collectors.common import (
    NEWS_LANES,
    Deadline,
    JobResult,
    JobSettings,
    chunks,
    ensure_assets,
    log_row,
    universe,
)
from backend.db.base import ExtendedRepository
from backend.pipeline.normalizer import default_asset, is_kr_symbol, normalize_news
from backend.schemas.market_ext import NewsRow


def cap_news(rows: list[NewsRow], per_day: int) -> list[NewsRow]:
    """(종목, 발행일) 마다 최신 per_day 건만 남김."""
    groups: dict[tuple[str, date], list[NewsRow]] = defaultdict(list)
    for r in rows:
        groups[(r.asset_id, r.published_at.date())].append(r)
    out: list[NewsRow] = []
    for g in groups.values():
        out.extend(sorted(g, key=lambda r: r.published_at, reverse=True)[:per_day])
    return sorted(out, key=lambda r: (r.asset_id, r.published_at, r.url))


def news_step(
    repo: ExtendedRepository,
    settings: JobSettings,
    *,
    adapters: dict[str, Any],
    today: date,
    chunk: int = 10,
    deadline: Deadline | None = None,
    now: datetime | None = None,
) -> JobResult:
    """뉴스 한 단계: 줄(NEWS_LANES)마다 오래 안 받은 종목부터 하루 한도만큼 받고, 옛 기사 삭제."""
    res = JobResult("news")
    deadline = deadline or Deadline(480)
    now = now or datetime.now(UTC)
    names = universe(repo, settings)
    skip = settings.etfs
    for lane, spec in NEWS_LANES.items():
        adapter = adapters.get(lane)
        limit = settings.news_daily_limits.get(lane, 0)
        if adapter is None or limit <= 0:
            continue
        query_to_symbol = news_queries(names, spec, skip)
        attempts = repo.fetch_attempts(spec["source"], list(query_to_symbol))
        today_start = datetime.combine(today, datetime.min.time(), tzinfo=UTC)

        def last_ok(q: str, attempts: dict = attempts) -> datetime | None:
            return (attempts.get(q) or {}).get("last_success_at")

        queries = [
            q
            for q in query_to_symbol
            if (last_ok(q) or datetime.min.replace(tzinfo=UTC)) < today_start
        ]
        queries.sort(key=lambda q: last_ok(q) or datetime.min.replace(tzinfo=UTC))
        res.counts[f"{lane}_pending"] = len(queries)
        for part in chunks(queries[:limit], chunk):
            if deadline.over():
                res.done = False
                break
            oldest = min((last_ok(q) for q in part if last_ok(q)), default=None)
            start = max((oldest or now - timedelta(days=7)).date(), today - timedelta(days=30))
            symbols = {query_to_symbol[q]: names[query_to_symbol[q]] for q in part}
            ensure_assets(repo, symbols)
            batch = adapter.fetch(part, start, today)
            q2a = {q: default_asset(query_to_symbol[q]).asset_id for q in part}
            rows, _ = normalize_news(batch, q2a)
            rows = cap_news(rows, settings.news_per_ticker_day)
            stored = repo.upsert_news(rows) if rows else 0
            logs = []
            for q in part:
                err = batch.failed_keys.get(q)
                if err and NO_DATA in err:  # 기사 없는 날은 정상: 성공(0건)으로 기록해 순번을 넘김
                    err = None
                logs.append(
                    log_row(q, start, today, batch.fetched_at, err, len(batch.payload.get(q) or []))
                )
                if err:
                    res.failed[f"{lane}:{q}"] = err
            repo.log_fetches(spec["source"], logs)
            res.counts[f"{lane}_queries"] += len(part)
            res.counts[f"{lane}_rows"] += stored
    res.counts["pruned"] = prune_old_news(repo, settings, now)
    return res


def news_queries(
    names: dict[str, str | None], spec: dict[str, Any], skip: Iterable[str]
) -> dict[str, str]:
    """뉴스 줄의 검색어 → 티커. 이름 검색 줄은 종목 이름(없으면 티커), symbol 줄은 티커."""
    kr = spec["market"] == "KR"
    by_symbol = spec.get("query") == "symbol"
    skip = set(skip)
    out: dict[str, str] = {}
    for t, name in names.items():
        if t in skip or is_kr_symbol(t) != kr:
            continue
        out.setdefault(t if by_symbol else (name or t), t)
    return out


def prune_old_news(repo: ExtendedRepository, settings: JobSettings, now: datetime) -> int:
    """NEWS_KEEP_DAYS 보다 오래된 기사 삭제. 0 이하면 아무것도 지우지 않음 (영구 보관)."""
    if settings.news_keep_days <= 0:
        return 0
    return repo.prune_news(now - timedelta(days=settings.news_keep_days))
