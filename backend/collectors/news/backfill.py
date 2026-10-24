"""뉴스 긴 백필 (PC, backend/scripts/backfill.py --what news).

뉴스 백필 줄 (매일 수집의 NEWS_PER_TICKER_DAY 상한 없이 모두 저장, url_hash 로 중복 제거)
- GOOGLE_RSS_KR / GOOGLE_RSS_US: 종목 이름으로 달마다 after:/before: 검색, 최근 달부터.
  이어 받기 target = rss_backfill:<줄>:<검색어>:<YYYY-MM>
- NAVER_NEWS: 최신순 start ≤ 1000 까지 (API 가 날짜 검색을 못 함).
  target = naver_backfill:<검색어>:<YYYY-MM-DD> (같은 날 다시 돌리면 건너뜀)
- NEWSAPI: 무료 플랜 최대 = 최근 29일 100건, 하루 한도(NEWSAPI_DAILY_MAX) 안.
  target = newsapi_backfill:<검색어>
- ALPACA_NEWS: 티커별 연도 기간을 page_token 으로 끝까지 (2015년~).
  target = alpaca_backfill:<티커>:<YYYY>
RSS 는 같은 달을 모든 종목에 대해 끝낸 뒤 그 전 달로 가므로, 중간에 멈춰도 종목 간 균형이 맞는다.
"""

from __future__ import annotations

import csv
import hashlib
from collections import defaultdict
from datetime import UTC, date, datetime, timedelta
from typing import Any

from backend.collectors.common import (
    NEWS_LANES,
    JobResult,
    JobSettings,
    Progress,
    ensure_assets,
    log_row,
    universe,
)
from backend.collectors.news.update import news_queries
from backend.pipeline.normalizer import default_asset, normalize_news
from backend.schemas.market_ext import RawNewsBatch

RSS_LANES = ("GOOGLE_RSS_KR", "GOOGLE_RSS_US")
NEWS_BACKFILL_ORDER = ("NAVER_NEWS", "NEWSAPI", "ALPACA_NEWS", *RSS_LANES)
"""뉴스 백필 순서: 빨리 끝나는 줄 먼저, Google RSS(가장 오래 걸림)는 마지막."""
NO_TARGETS = "대상 종목 없음 (구성종목이 아직 없으면 먼저 --what prices 또는 jobs meta)"
KR_QUARTER_BEFORE = date(2011, 1, 1)
"""이 날 전 달은 기사가 적은 국내 종목을 분기로 묶어 검색 (요청 1/3). 기사 많은 종목은 월 단위
(Google RSS 는 한 번에 100건 안팎에서 잘려서, 분기로 묶으면 대형주는 기사를 잃음)."""
KR_SPARSE_MONTHLY = 60
"""국내 종목의 2017~2019 Google RSS 월평균 기사가 이보다 적으면 '기사 적은 종목'."""
SPARSE_SAMPLE = (date(2017, 1, 1), date(2020, 1, 1))


def load_former_names() -> dict[str, list[tuple[str, date]]]:
    """backend/data/config/kr_former_names.csv → {6자리 코드: [(옛 이름, 바뀐 날)]} (바뀐 날 순)."""
    from backend.collectors.constituents.source import config_file

    path = config_file("kr_former_names.csv")
    out: dict[str, list[tuple[str, date]]] = defaultdict(list)
    if path.exists():
        with path.open(encoding="utf-8") as f:
            for r in csv.DictReader(f):
                out[r["ticker"].strip()].append(
                    (r["former_name"].strip(), date.fromisoformat(r["until"].strip()))
                )
    return {k: sorted(v, key=lambda x: x[1]) for k, v in out.items()}


def name_in(query: str, symbol: str, month: date, former: dict[str, list[tuple[str, date]]]) -> str:
    """그 달에 쓰던 이름: 사명 변경 전 달이면 옛 이름 (하이닉스 → SK하이닉스)."""
    for name, until in former.get(symbol.split(".")[0], []):
        if month < until:
            return name
    return query


def add_months(d: date, n: int) -> date:
    m = d.month - 1 + n
    return date(d.year + m // 12, m % 12 + 1, 1)


def rss_window(
    lane: str, symbol: str, first: date, nxt: date, sparse: set[str]
) -> tuple[date, date] | None:
    """검색 기간. 국내 기사 적은 종목의 KR_QUARTER_BEFORE 전은 분기 첫 달에만 3개월을 한 번에 (나머지 None)."""
    if lane == "GOOGLE_RSS_KR" and first < KR_QUARTER_BEFORE and symbol in sparse:
        if first.month % 3 != 1:
            return None
        return first, add_months(first, 3)
    return first, nxt


def month_windows(today: date, years: int) -> list[tuple[date, date]]:
    """[(그달 1일, 다음 달 1일)] 이번 달부터 years 년 전 달까지, 최근 달이 먼저."""
    out = []
    y, m = today.year, today.month
    for _ in range(years * 12 + 1):
        first = date(y, m, 1)
        nxt = date(y + (m == 12), m % 12 + 1, 1)
        out.append((first, nxt))
        y, m = (y - 1, 12) if m == 1 else (y, m - 1)
    return out


def short_query(query: str, size: int = 50) -> str:
    """fetch_log.target(100자)에 들어가게: 길면 앞부분 + 해시."""
    if len(query) <= size:
        return query
    return query[: size - 9] + "~" + hashlib.sha1(query.encode()).hexdigest()[:8]


def rss_target(lane: str, query: str, month: date) -> str:
    return f"rss_backfill:{lane}:{short_query(query)}:{month:%Y-%m}"


class NewsSink:
    """받은 기사를 모아 한 번에 저장하고 fetch_log 를 남김 (저장한 뒤에만 기록 → 끊겨도 안전)."""

    def __init__(self, repo: Any, source: str, flush_every: int = 20) -> None:
        self.repo, self.source, self.flush_every = repo, source, flush_every
        self.rows: list[Any] = []
        self.logs: list[dict[str, Any]] = []
        self.stored = 0
        self.fetched = 0

    def add(
        self,
        *,
        query: str,
        symbol: str,
        rows: list[dict[str, Any]],
        target: str,
        start: date,
        end: date,
        error: str | None = None,
    ) -> None:
        at = datetime.now(UTC)
        batch = RawNewsBatch(
            source=self.source,
            requested_keys=[query],
            start=start,
            end=end,
            fetched_at=at,
            payload={query: rows} if rows else {},
        )
        norm, _ = normalize_news(batch, {query: default_asset(symbol).asset_id})
        self.rows += norm
        self.fetched += len(rows)
        self.logs.append(log_row(target, start, end, at, error, len(rows)))
        if len(self.logs) >= self.flush_every:
            self.flush()

    def flush(self) -> None:
        if self.rows:
            self.stored += self.repo.upsert_news(self.rows)
        if self.logs:
            self.repo.log_fetches(self.source, self.logs)
        self.rows, self.logs = [], []


def _symbols(repo: Any, settings: JobSettings, lane: str) -> dict[str, str]:
    names = universe(repo, settings)
    q = news_queries(names, NEWS_LANES[lane], settings.etfs)
    ensure_assets(repo, {t: names[t] for t in q.values()})
    return q


def rss_backfill(
    repo: Any,
    settings: JobSettings,
    *,
    adapters: dict[str, Any],
    today: date,
    years: int,
    deadline: Any,
    interval: float = 1.5,
    flush_every: int = 20,
    progress: Progress | None = None,
    kr_years: int | None = None,
) -> JobResult:
    """Google News RSS 달별 백필 (RSS_LANES 중 adapters 에 있는 줄). 최근 달부터.

    kr_years 를 주면 국내 줄만 그만큼 더 과거로 (미국 줄은 years). 국내 줄은 사명 변경 전 달을 옛 이름으로
    검색하고(kr_former_names.csv), KR_QUARTER_BEFORE 전에는 기사 적은 종목을 분기로 묶어 검색한다.
    """
    from backend.adapters.crawlers.google_news_rss_client import RateLimited

    res = JobResult("news_backfill:GOOGLE_RSS")
    lanes = [lane for lane in RSS_LANES if lane in adapters]
    if not lanes:
        return res
    queries = {lane: _symbols(repo, settings, lane) for lane in lanes}
    if not any(queries.values()):
        res.notes.append(NO_TARGETS)
        return res
    done = repo.fetch_targets_done("GOOGLE_RSS", "rss_backfill:")
    sink = NewsSink(repo, "GOOGLE_RSS", flush_every)
    months = month_windows(today, max(years, kr_years or years))
    us_from = month_windows(today, years)[-1][0]
    former: dict[str, list[tuple[str, date]]] = {}
    sparse: set[str] = set()
    if "GOOGLE_RSS_KR" in lanes:
        former = load_former_names()
        kr = queries["GOOGLE_RSS_KR"].values()
        avg = repo.news_monthly_average(
            "GOOGLE_RSS", [default_asset(s).asset_id for s in kr], *SPARSE_SAMPLE
        )
        sparse = {s for s in kr if avg.get(default_asset(s).asset_id, 0) < KR_SPARSE_MONTHLY}

    def plan(lane: str, first: date, nxt: date) -> list[tuple[str, str, tuple[date, date]]]:
        """(검색어, 티커, 기간) 목록. 그 달에 받을 게 없는 종목은 빠짐."""
        if lane != "GOOGLE_RSS_KR" and first < us_from:
            return []
        out = []
        for query, symbol in queries[lane].items():
            win = rss_window(lane, symbol, first, nxt, sparse)
            if win is not None:
                q = name_in(query, symbol, first, former) if lane == "GOOGLE_RSS_KR" else query
                out.append((q, symbol, win))
        return out

    total = sum(len(plan(lane, f, n)) for f, n in months for lane in lanes)
    seen = 0
    try:
        for first, nxt in months:
            for lane in lanes:
                skipped = 0
                todo = plan(lane, first, nxt)
                for query, symbol, (after, before) in todo:
                    seen += 1
                    target = rss_target(lane, query, first)
                    if target in done:
                        skipped += 1
                        continue
                    if deadline.over():
                        res.done = False
                        return res
                    try:
                        rows = adapters[lane].fetch_window(query, after, before, interval=interval)
                        err = None
                    except RateLimited as exc:
                        res.done = False
                        res.notes.append(f"{lane}: Google 이 요청을 막음, 나중에 다시 실행 ({exc})")
                        return res
                    except Exception as exc:  # noqa: BLE001 - 한 달 실패는 기록하고 다음으로
                        rows, err = [], f"{type(exc).__name__}: {exc}"
                        res.failed[target] = err
                    sink.add(query=query, symbol=symbol, rows=rows, target=target,
                             start=after, end=before - timedelta(days=1), error=err)  # fmt: skip
                    res.counts[f"{lane}_requests"] += 1
                if progress and todo:
                    progress(
                        f"[news {lane}] {first:%Y-%m}: {len(todo)}종목 "
                        f"(이미 끝 {skipped}), 받은 기사 {sink.fetched:,} · 새로 저장 "
                        f"{sink.stored:,} · 전체 진행 {seen:,}/{total:,}"
                    )
    finally:
        sink.flush()
        res.counts["GOOGLE_RSS_fetched"] = sink.fetched
        res.counts["GOOGLE_RSS_rows"] = sink.stored
    return res


def naver_backfill(
    repo: Any,
    settings: JobSettings,
    *,
    adapter: Any,
    today: date,
    deadline: Any,
    flush_every: int = 20,
    progress: Progress | None = None,
) -> JobResult:
    """네이버: 종목마다 최신순 1000건 (오늘 이미 받은 종목은 건너뜀)."""
    res = JobResult("news_backfill:NAVER_NEWS")
    queries = _symbols(repo, settings, "NAVER_NEWS")
    if not queries:
        res.notes.append(NO_TARGETS)
        return res
    done = repo.fetch_targets_done("NAVER_NEWS", "naver_backfill:")
    sink = NewsSink(repo, "NAVER_NEWS", flush_every)
    try:
        for n, (query, symbol) in enumerate(queries.items(), start=1):
            target = f"naver_backfill:{short_query(query)}:{today.isoformat()}"
            if target in done:
                continue
            if deadline.over():
                res.done = False
                break
            try:
                rows, err = adapter.fetch_all(query), None
            except Exception as exc:  # noqa: BLE001
                rows, err = [], f"{type(exc).__name__}: {exc}"
                res.failed[target] = err
            sink.add(query=query, symbol=symbol, rows=rows, target=target,
                     start=today - timedelta(days=3650), end=today, error=err)  # fmt: skip
            res.counts["NAVER_NEWS_requests"] += 1
            if progress and n % 20 == 0:
                progress(f"[news NAVER_NEWS] {n}/{len(queries)}종목, 새로 저장 {sink.stored:,}")
    finally:
        sink.flush()
        res.counts["NAVER_NEWS_rows"] = sink.stored
    return res


def newsapi_backfill(
    repo: Any,
    settings: JobSettings,
    *,
    adapter: Any,
    today: date,
    deadline: Any,
    daily_max: int = 100,
    flush_every: int = 20,
    progress: Progress | None = None,
) -> JobResult:
    """NewsAPI 무료 플랜 최대치: 종목마다 최근 29일 100건. 오늘 쓴 요청 수(정기 수집 포함)를 빼고
    daily_max 안에서, 오래 안 받은 종목부터. 그보다 오래된 기사는 유료 플랜이 필요하다."""
    res = JobResult("news_backfill:NEWSAPI")
    queries = _symbols(repo, settings, "NEWSAPI")
    if not queries:
        res.notes.append(NO_TARGETS)
        return res
    day0 = datetime(today.year, today.month, today.day, tzinfo=UTC)
    left = max(0, daily_max - 5 - repo.count_fetches("NEWSAPI", day0))  # 5건은 여유
    targets = {f"newsapi_backfill:{short_query(q)}": q for q in queries}
    att = repo.fetch_attempts("NEWSAPI", list(targets))

    def last(t: str) -> datetime:
        return (att.get(t) or {}).get("last_success_at") or datetime.min.replace(tzinfo=UTC)

    due = sorted((t for t in targets if last(t) < day0), key=lambda t: (last(t), t))
    res.counts["NEWSAPI_pending"] = len(due)
    res.counts["NEWSAPI_quota_left"] = left
    if len(due) > left:
        res.done = False
        res.notes.append(
            f"NEWSAPI: 오늘 한도로 {left}/{len(due)}종목만. 내일 다시 실행하면 이어서 받음"
        )
    sink = NewsSink(repo, "NEWSAPI", flush_every)
    try:
        for target in due[:left]:
            if deadline.over():
                res.done = False
                break
            query = targets[target]
            try:
                rows, err = adapter.fetch_max(query), None
            except Exception as exc:  # noqa: BLE001
                rows, err = [], f"{type(exc).__name__}: {exc}"
                res.failed[target] = err
            sink.add(query=query, symbol=queries[query], rows=rows, target=target,
                     start=today - timedelta(days=29), end=today, error=err)  # fmt: skip
            res.counts["NEWSAPI_requests"] += 1
    finally:
        sink.flush()
        res.counts["NEWSAPI_rows"] = sink.stored
        if progress:
            progress(f"[news NEWSAPI] 요청 {res.counts['NEWSAPI_requests']}, 저장 {sink.stored:,}")
    return res


def alpaca_news_backfill(
    repo: Any,
    settings: JobSettings,
    *,
    adapter: Any,
    today: date,
    years: int,
    deadline: Any,
    flush_every: int = 20,
    progress: Progress | None = None,
) -> JobResult:
    """Alpaca News: 티커마다 연도 기간을 끝까지. 지난 해는 한 번 끝나면 건너뜀, 올해는 매번."""
    res = JobResult("news_backfill:ALPACA_NEWS")
    queries = _symbols(repo, settings, "ALPACA_NEWS")
    if not queries:
        res.notes.append(NO_TARGETS)
        return res
    done = repo.fetch_targets_done("ALPACA_NEWS", "alpaca_backfill:")
    sink = NewsSink(repo, "ALPACA_NEWS", flush_every)
    try:
        for year in range(today.year, today.year - years - 1, -1):
            first = date(year, 1, 1)
            end = min(date(year + 1, 1, 1), today + timedelta(days=1))
            for symbol in queries:
                target = f"alpaca_backfill:{symbol}:{year}"
                if year < today.year and target in done:
                    continue
                if deadline.over():
                    res.done = False
                    return res
                try:
                    rows, err = adapter.fetch_range(symbol, first, end), None
                except Exception as exc:  # noqa: BLE001
                    rows, err = [], f"{type(exc).__name__}: {exc}"
                    res.failed[target] = err
                sink.add(query=symbol, symbol=queries[symbol], rows=rows, target=target,
                         start=first, end=end - timedelta(days=1), error=err)  # fmt: skip
                res.counts["ALPACA_NEWS_requests"] += 1
            if progress:
                progress(
                    f"[news ALPACA_NEWS] {year}년 끝, 받은 기사 {sink.fetched:,} · "
                    f"새로 저장 {sink.stored:,}"
                )
    finally:
        sink.flush()
        res.counts["ALPACA_NEWS_rows"] = sink.stored
    return res
