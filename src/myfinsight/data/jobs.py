"""서버 수집 작업: 정해진 주기마다 실제 데이터를 받아 DB 에 채운다 (역할 A, M02-01~05 를 묶음).

    python -m myfinsight.data.jobs prices      # 가격: 매일 증분 + 처음 N년치 백필 (나눠서)
    python -m myfinsight.data.jobs meta        # 구성종목 갱신 + 재무
    python -m myfinsight.data.jobs news        # 뉴스 (출처별 하루 한도 안) + 오래된 기사 삭제
    python -m myfinsight.data.jobs verify      # 교차검증만 (prices 도 끝에 이어서 함)
    python -m myfinsight.data.jobs verify --start 2026-01-01 --end 2026-09-30   # 기간 다시 계산
    python -m myfinsight.data.jobs all

- 어디서 돌든 같음: PC, GitHub Actions (.github/workflows/collect.yml).
  DB 는 .env 의 DATABASE_URL 로만 정해진다 (open_repository).
- 한 번 실행은 시간 예산(budget_sec, 기본 480초) 안에서 끝나고, 남은 일은 다음 실행이 이어 받는다.
  진행 상황은 DB 가 기억한다 (저장 범위 = price_daily, 시도 기록 = fetch_log). 따로 커서가 없다.
- 설정은 .env (crawlers/config.py): UNIVERSE_INDICES, EXTRA_TICKERS, BENCHMARK_TICKERS,
  BACKFILL_YEARS, FIN_YEARS, FIN_REFRESH_DAYS, NEWS_PER_TICKER_DAY, NEWS_KEEP_DAYS,
  NEWS_DAILY_LIMITS.
"""

from __future__ import annotations

import argparse
import json
import logging
import time
from collections import defaultdict
from collections.abc import Callable, Iterable, Sequence
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from datetime import UTC, date, datetime, timedelta
from typing import Any

from myfinsight.data.adapters.base import NO_DATA
from myfinsight.data.constituents import ConstituentCollector
from myfinsight.data.crawlers import config
from myfinsight.data.normalizer import (
    currency_of_symbol,
    default_asset,
    is_kr_symbol,
    normalize,
    normalize_financials,
    normalize_news,
    normalize_ticker,
)
from myfinsight.data.repository.base import ExtendedRepository
from myfinsight.data.repository.sql import START_GRACE_DAYS, previous_weekday
from myfinsight.schemas.errors import DataSourceError
from myfinsight.schemas.market import IndexCode
from myfinsight.schemas.market_ext import NewsRow

logger = logging.getLogger(__name__)

MAX_FAILURES = 3
"""같은 대상이 이만큼 실패하면 (성공 기록 없이) 백필·재무 대상에서 뺀다. 상장폐지·ETF 등."""

NEWS_LANES: dict[str, dict[str, Any]] = {
    # 이름: (출처, 시장, 어댑터 인자)
    "NAVER_NEWS": {"source": "NAVER_NEWS", "market": "KR", "kwargs": {}},
    "GOOGLE_RSS_KR": {"source": "GOOGLE_RSS", "market": "KR", "kwargs": {}},
    "GOOGLE_RSS_US": {
        "source": "GOOGLE_RSS",
        "market": "US",
        "kwargs": {"lang": "en", "country": "US"},
    },
    "NEWSAPI": {"source": "NEWSAPI", "market": "US", "kwargs": {}},
}
"""뉴스 수집 줄. 하루 한도는 NEWS_DAILY_LIMITS 로 줄마다 정한다."""


# ---------------------------------------------------------------- 설정
def _csv(text: str) -> list[str]:
    return [x.strip() for x in text.split(",") if x.strip()]


@dataclass
class JobSettings:
    """수집 작업 설정 (.env 에서 읽음, from_env)."""

    indices: list[IndexCode] = field(
        default_factory=lambda: [IndexCode.SP500, IndexCode.NDX, IndexCode.KOSPI200]
    )
    extra_tickers: dict[str, str | None] = field(default_factory=dict)  # 티커 → 이름
    benchmarks: list[str] = field(default_factory=lambda: ["SPY", "QQQ"])
    etf_tickers: list[str] = field(default_factory=list)  # 벤치마크 밖 ETF (EXTRA_TICKERS 등)
    backfill_years: int = 1
    fin_years: int = 1
    fin_refresh_days: int = 7
    news_per_ticker_day: int = 5
    news_keep_days: int = 365
    news_daily_limits: dict[str, int] = field(
        default_factory=lambda: {
            "NAVER_NEWS": 200,
            "GOOGLE_RSS_KR": 200,
            "GOOGLE_RSS_US": 200,
            "NEWSAPI": 90,
        }
    )
    increment_days: int = 10  # 매일 증분 때 다시 받는 최근 일수 (휴일·지연 반영 대비)
    price_lanes: list[str] = field(default_factory=lambda: list(PRICE_LANES))
    sample_daily: dict[str, int] = field(default_factory=lambda: {"TIINGO": 15})
    fx_symbol: str | None = "KRW=X"

    @classmethod
    def from_env(cls) -> JobSettings:
        s = cls()
        if v := config.get("UNIVERSE_INDICES"):
            s.indices = [IndexCode(x.upper()) for x in _csv(v)]
        if v := config.get("EXTRA_TICKERS"):  # 005930.KS:삼성전자,000660.KS:SK하이닉스,TSLA
            s.extra_tickers = {}
            for item in _csv(v):
                t, _, name = item.partition(":")
                s.extra_tickers[normalize_ticker(t)] = name.strip() or None
        if v := config.get("BENCHMARK_TICKERS"):
            s.benchmarks = [normalize_ticker(x) for x in _csv(v)]
        if v := config.get("ETF_TICKERS"):
            s.etf_tickers = [normalize_ticker(x) for x in _csv(v)]
        for name in (
            "backfill_years",
            "fin_years",
            "fin_refresh_days",
            "news_per_ticker_day",
            "news_keep_days",
        ):
            if v := config.get(name.upper()):
                setattr(s, name, int(v))
        if v := config.get("PRICE_SOURCES"):  # KIS,ALPACA,YFINANCE,TIINGO
            s.price_lanes = [x.upper() for x in _csv(v)]
        if v := config.get("TIINGO_DAILY_SYMBOLS"):
            s.sample_daily["TIINGO"] = int(v)
        if v := config.get("NEWS_DAILY_LIMITS"):  # NAVER_NEWS=200,NEWSAPI=90,...
            for item in _csv(v):
                k, _, n = item.partition("=")
                s.news_daily_limits[k.strip().upper()] = int(n)
        return s

    @property
    def etfs(self) -> set[str]:
        """assets.asset_type = ETF 로 둘 종목: 벤치마크 + ETF_TICKERS. 재무·뉴스 대상에서 빠짐."""
        return set(self.benchmarks) | set(self.etf_tickers)


@dataclass
class JobResult:
    """작업 한 번의 결과. done=False 면 남은 일이 있어 다음 실행이 이어 받음."""

    name: str
    done: bool = True
    counts: dict[str, int] = field(default_factory=lambda: defaultdict(int))
    failed: dict[str, str] = field(default_factory=dict)
    notes: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "done": self.done,
            "counts": dict(self.counts),
            "failed": dict(list(self.failed.items())[:50]),
            "failed_total": len(self.failed),
            "notes": self.notes,
        }


class Deadline:
    """시간 예산. 함수 실행 제한(예: 9분) 전에 스스로 멈추기 위함."""

    def __init__(self, budget_sec: float, clock: Callable[[], float] = time.monotonic) -> None:
        self._clock = clock
        self._end = clock() + budget_sec

    def over(self) -> bool:
        return self._clock() >= self._end


def _chunks(items: Sequence[Any], n: int) -> Iterable[list[Any]]:
    for i in range(0, len(items), n):
        yield list(items[i : i + n])


def _years_before(d: date, years: int) -> date:
    try:
        return d.replace(year=d.year - years)
    except ValueError:  # 2월 29일
        return d.replace(year=d.year - years, day=28)


# ---------------------------------------------------------------- 대상 종목
def universe(repo: ExtendedRepository, settings: JobSettings) -> dict[str, str | None]:
    """수집 대상 티커 → 이름 (순서 유지).

    최신 구성종목 + EXTRA_TICKERS + 서비스 요청으로 늘어난 종목(extra_ticker)
    + 벤치마크 + ETF_TICKERS.
    """
    out: dict[str, str | None] = {}
    for index in settings.indices:
        for r in repo.latest_constituents(index):
            out.setdefault(normalize_ticker(r.ticker), r.name)
    for t, name in settings.extra_tickers.items():
        out.setdefault(t, name)
    asset_names = None
    for t in repo.extra_tickers():
        if t not in out:
            asset_names = asset_names or {a.yfinance_symbol: a.name for a in repo.get_assets()}
            out[t] = asset_names.get(t)
    for t in (*settings.benchmarks, *settings.etf_tickers):
        out.setdefault(t, None)
    return out


def _ensure_assets(repo: ExtendedRepository, names: dict[str, str | None]) -> None:
    """assets 에 없는 종목만 기본 행으로 추가 (있는 행은 건드리지 않음)."""
    have = {a.yfinance_symbol for a in repo.get_assets(list(names))}
    missing = [default_asset(t, names[t]) for t in names if t not in have]
    if missing:
        repo.upsert_assets(missing)


def sync_asset_types(repo: ExtendedRepository, settings: JobSettings) -> int:
    """설정의 ETF 종목을 assets.asset_type = ETF 로 맞춤 (이미 STOCK 으로 저장된 행도 고침)."""
    etfs = sorted(settings.etfs)
    if not etfs:
        return 0
    _ensure_assets(repo, dict.fromkeys(etfs))
    wrong = [a for a in repo.get_assets(etfs) if a.asset_type != "ETF"]
    if not wrong:
        return 0
    return repo.upsert_assets([a.model_copy(update={"asset_type": "ETF"}) for a in wrong])


# ---------------------------------------------------------------- 구성종목
def refresh_constituents(
    repo: ExtendedRepository, settings: JobSettings, *, source: Any, today: date
) -> JobResult:
    """지수별 구성종목: 정기 변경일이 지났으면 새로 받아 저장 (M02-05)."""
    res = JobResult("constituents")
    collector = ConstituentCollector(source, repo)
    for index in settings.indices:
        try:
            r = collector.update_one(index, today)
        except DataSourceError as exc:
            res.failed[index.value] = str(exc)
            continue
        res.counts[r.status.value] += 1
        res.notes.extend(r.warnings)
    return res


# ---------------------------------------------------------------- 가격
PRICE_LANES: dict[str, dict[str, Any]] = {
    # 이름: 출처, 시장(KR·US·ALL), 역할. 순서 = 받는 순서 (primary 먼저)
    "KIS": {"market": "KR", "role": "primary"},
    "ALPACA": {"market": "US", "role": "primary"},
    "YFINANCE": {"market": "ALL", "role": "secondary"},  # 환율(KRW=X)도 이 줄에서
    "TIINGO": {"market": "US", "role": "sample"},  # 무료 한도 → 하루 N종목씩 돌아가며 최근분만
}
"""가격 수집 줄. primary = 공식 API, secondary = 전 종목 보완, sample = 표본 교차검증."""


def _in_market(symbol: str, market: str) -> bool:
    return market == "ALL" or is_kr_symbol(symbol) == (market == "KR")


def _request_key(lane: str, symbol: str) -> str:
    """출처가 받는 종목 코드. KIS 는 6자리 종목코드, 나머지는 yfinance 표기."""
    return default_asset(symbol).ticker if lane == "KIS" else symbol


def _log_row(
    target: str, start: date, end: date, at: datetime, error: str | None, count: int
) -> dict[str, Any]:
    """fetch_log 한 줄 (repo.log_fetches 입력)."""
    return {
        "target": target,
        "start_date": start,
        "end_date": end,
        "status": "FAILED" if error else "SUCCESS",
        "fetched_at": at,
        "error": error,
        "fetched_count": count,
    }


def store_prices(
    repo: ExtendedRepository,
    adapter: Any,
    symbols: list[str],
    start: date,
    end: date,
    *,
    lane: str,
    fx_symbol: str | None = None,
) -> tuple[int, int, dict[str, str]]:
    """한 출처에서 받아 정규화·저장하고 fetch_log 를 남김. (가격 행, 환율 행, 실패) 반환.

    load_prices 와 달리 캐시 판단을 하지 않고 주어진 종목을 그 출처에서 그대로 받는다
    (출처별로 따로 채우기 위함). 출처 코드(KIS 6자리)는 yfinance 표기로 되돌려 저장한다.
    """
    keys = {_request_key(lane, t): t for t in symbols}
    request = list(keys) + ([fx_symbol] if fx_symbol else [])
    t0 = time.monotonic()
    batch = adapter.fetch(request, start, end)
    t1 = time.monotonic()
    payload = {keys.get(k, k): v for k, v in batch.payload.items()}
    failed = {keys.get(k, k): v for k, v in batch.failed_tickers.items()}
    batch = batch.model_copy(
        update={
            "payload": payload,
            "failed_tickers": failed,
            "requested_tickers": [keys.get(k, k) for k in request],
        }
    )
    repo.log_fetches(
        batch.source,
        [
            _log_row(t, start, end, batch.fetched_at, failed.get(t), len(payload.get(t) or []))
            for t in batch.requested_tickers
        ],
    )
    result = normalize(batch, fx_symbol=fx_symbol or "KRW=X")
    rows = repo.upsert_prices(result.bars) if result.bars else 0
    fx_rows = repo.upsert_fx(result.fx) if fx_symbol and result.fx else 0
    logger.info(
        "%s %d종목 받기 %.1f초 · 저장 %.1f초 (%d행)",
        lane,
        len(symbols) or len(request),
        t1 - t0,
        time.monotonic() - t1,
        rows + fx_rows,
    )
    return rows, fx_rows, failed


def _lane_plan(
    repo: ExtendedRepository,
    lane: str,
    source: str,
    tickers: list[str],
    *,
    today: date,
    end: date,
    inc_start: date,
    full_start: date,
    sample_size: int,
) -> list[tuple[str, date]]:
    """이 출처에서 받을 (종목, 시작일) 목록. ① 최근 증분 ② 백필 (sample 줄은 ③ 표본만)."""
    need_until = min(end, previous_weekday(today, getattr(repo, "cache_max_age_days", 1)))
    if PRICE_LANES[lane]["role"] == "sample":
        att = repo.fetch_attempts(source, tickers)
        day0 = datetime.combine(today, datetime.min.time(), tzinfo=UTC)

        def last(t: str) -> datetime:
            return (att.get(t) or {}).get("last_success_at") or datetime.min.replace(tzinfo=UTC)

        due = sorted((t for t in tickers if last(t) < day0), key=lambda t: (last(t), t))
        left = max(0, sample_size - (len(tickers) - len(due)))  # 하루 한도: 오늘 받은 수를 뺌
        return [(t, inc_start) for t in due[:left]]

    ranges = repo.covered_ranges(tickers, source=source)
    increment = [t for t in tickers if t in ranges and ranges[t][1] < need_until]
    # need_until 까지 요청해 성공했는데도 없으면 휴장일(대체공휴일 등): 다음 거래일까지 다시 안 받음
    asked = repo.fetch_attempts(source, increment, end_on_or_after=need_until)
    increment = [t for t in increment if (asked.get(t) or {}).get("last_success_at") is None]
    grace = full_start + timedelta(days=START_GRACE_DAYS)
    short = [t for t in tickers if t not in ranges or ranges[t][0] > grace]
    attempts = repo.fetch_attempts(source, short, start_on_or_before=grace)
    backfill = []
    for t in short:
        a = attempts.get(t)
        # 백필 범위를 덮는 요청이 성공했으면 끝 (상장이 늦은 종목은 그 이전 데이터가 없음)
        if a and (a["last_success_at"] is not None or a["failures"] >= MAX_FAILURES):
            continue
        backfill.append(t)
    # 백필 요청이 증분 기간까지 덮으므로 둘 다 필요한 종목(BACKFILL_YEARS 를 늘린 경우 등)은 백필만
    increment = [t for t in increment if t not in backfill]
    return [(t, inc_start) for t in increment] + [(t, full_start) for t in backfill]


def price_step(
    repo: ExtendedRepository,
    settings: JobSettings,
    *,
    adapters: dict[str, Any],
    today: date,
    limit: int = 100,
    chunk: int = 50,
    deadline: Deadline | None = None,
    market: str = "ALL",
    lanes: Sequence[str] | None = None,
) -> JobResult:
    """가격 한 단계: 출처 줄(PRICE_LANES)마다 ① 최근 증분 ② N년치 백필을 받는다.

    환율을 먼저 받고, 줄(KIS·Alpaca·yfinance·Tiingo)을 동시에 chunk 종목씩 처리한다.
    줄마다 한 번에 최대 limit 종목. 시간 예산이 끝나면 멈추고 done=False.
    adapters 에 없는 줄(키 없음 등)은 건너뜀.
    market: KR·US 면 그 시장 종목만. lanes: 받을 줄만 (None = adapters 전부).
    ALPACA 는 받는데 YFINANCE 줄은 안 받는 실행(미국 매일분)에서는 Alpaca 가 못 받은 종목만
    yfinance 로 대신 받는다 (adapters 에 YFINANCE 가 있을 때).
    """
    res = JobResult("prices")
    deadline = deadline or Deadline(480)
    names = universe(repo, settings)
    res.counts["etf_marked"] = sync_asset_types(repo, settings)
    end = today - timedelta(days=1)
    inc_start = end - timedelta(days=settings.increment_days)
    full_start = _years_before(end, settings.backfill_years)
    fx_due = settings.fx_symbol is not None and (
        (fx := repo.get_fx_on_or_before(end)) is None or fx.date < min(end, previous_weekday(today))
    )
    # 환율도 백필 기간 앞부분이 비었으면(BACKFILL_YEARS 를 늘린 경우 등) 처음부터 받음
    fx_backfill = (
        settings.fx_symbol is not None
        and repo.get_fx_on_or_before(full_start + timedelta(days=START_GRACE_DAYS)) is None
    )
    fx_start = full_start if fx_backfill else inc_start
    fx_due = fx_due or fx_backfill

    # 줄마다 할 일(요청 묶음)을 만든 뒤 줄마다 스레드 하나로 동시에 처리:
    # 출처마다 요청 간격·응답 대기가 따로라 겹치면 빨라지고, 한 출처가 느려도 다른 출처는 진행됨
    queues: dict[str, list[tuple[date, list[str]]]] = {}
    chosen = [x.upper() for x in lanes] if lanes is not None else list(adapters)
    for lane, spec in PRICE_LANES.items():
        adapter = adapters.get(lane)
        if adapter is None or lane not in chosen:
            continue
        source = adapter.source_name
        tickers = [t for t in names if _in_market(t, spec["market"]) and _in_market(t, market)]
        plan = _lane_plan(
            repo,
            lane,
            source,
            tickers,
            today=today,
            end=end,
            inc_start=inc_start,
            full_start=full_start,
            sample_size=settings.sample_daily.get(lane, 0),
        )
        res.counts[f"{lane}_pending"] = len(plan)
        if len(plan) > limit:
            res.done = False
        groups: dict[tuple[date, str], list[str]] = defaultdict(list)
        for t, start in plan[:limit]:
            groups[(start, currency_of_symbol(t))].append(t)
        queues[lane] = [
            (start, part)
            for (start, _cur), group in groups.items()
            for part in _chunks(group, chunk)
        ]
    fx_due = fx_due and market != "KR"  # 환율은 미국 종목 원화 환산용
    if fx_due and "YFINANCE" in adapters:  # 환율은 따로 한 번 요청 (종목과 기간이 다를 수 있음)
        if deadline.over():
            res.done = False
            return res
        _, fx_rows, _ = store_prices(
            repo,
            adapters["YFINANCE"],
            [],
            fx_start,
            end,
            lane="YFINANCE",
            fx_symbol=settings.fx_symbol,
        )
        res.counts["fx_rows"] += fx_rows

    def run_lane(lane: str) -> JobResult:  # 출처마다 스레드 하나 (요청 대기 시간이 겹치게)
        out = JobResult("prices")
        for start, part in queues[lane]:
            if deadline.over():
                out.done = False
                break
            _ensure_assets(repo, {t: names.get(t) for t in part})
            rows, _, failed = store_prices(repo, adapters[lane], part, start, end, lane=lane)
            out.counts[f"{lane}_tickers"] += len(part)
            out.counts[f"{lane}_rows"] += rows
            out.failed.update({f"{lane}:{t}": e for t, e in failed.items()})
            for t in failed:
                missed[lane].append((start, t))
        return out

    missed: dict[str, list[tuple[date, str]]] = defaultdict(list)

    lanes = [lane for lane, q in queues.items() if q]
    if lanes:
        # SQLite(PC 실행)는 동시 쓰기에 약해서 한 줄씩
        workers = len(lanes) if getattr(repo, "dialect", "") == "postgresql" else 1
        with ThreadPoolExecutor(max_workers=workers) as pool:
            for part_res in pool.map(run_lane, lanes):
                res.counts.update(part_res.counts)
                res.failed.update(part_res.failed)
                res.done = res.done and part_res.done
    _fallback(repo, adapters, missed, chosen, end, res, deadline)
    return res


FALLBACK_LANES = {"ALPACA": "YFINANCE"}
"""primary 줄이 못 받은 종목을 대신 받을 줄 (그 줄을 이번 실행에서 안 받을 때만)."""


def _fallback(
    repo: ExtendedRepository,
    adapters: dict[str, Any],
    missed: dict[str, list[tuple[date, str]]],
    chosen: list[str],
    end: date,
    res: JobResult,
    deadline: Deadline,
) -> None:
    for lane, other in FALLBACK_LANES.items():
        if not missed.get(lane) or other in chosen or other not in adapters:
            continue
        groups: dict[date, list[str]] = defaultdict(list)
        for start, t in missed[lane]:
            groups[start].append(t)
        for start, group in groups.items():
            for part in _chunks(group, 50):
                if deadline.over():
                    res.done = False
                    return
                rows, _, failed = store_prices(repo, adapters[other], part, start, end, lane=other)
                res.counts[f"{other}_fallback_tickers"] += len(part)
                res.counts[f"{other}_fallback_rows"] += rows
                res.failed.update({f"{other}:{t}": e for t, e in failed.items()})


# ---------------------------------------------------------------- 재무
def _financial_targets(
    names: dict[str, str | None], etfs: Iterable[str]
) -> dict[str, dict[str, str]]:
    """출처 → {요청 키: 티커}. 한국 DART(6자리 종목코드), 미국 SEC EDGAR(티커). ETF 제외."""
    skip = set(etfs)
    out: dict[str, dict[str, str]] = {"DART": {}, "SEC_EDGAR": {}}
    for t in names:
        if t in skip:
            continue
        if is_kr_symbol(t):
            out["DART"][default_asset(t).ticker] = t
        else:
            out["SEC_EDGAR"][t] = t
    return out


def financial_step(
    repo: ExtendedRepository,
    settings: JobSettings,
    *,
    adapters: dict[str, Any],
    today: date,
    limit: int = 100,
    chunk: int = 10,
    deadline: Deadline | None = None,
) -> JobResult:
    """재무 한 단계: 마지막 성공이 FIN_REFRESH_DAYS 보다 오래된 종목부터 받아 저장."""
    res = JobResult("financials")
    deadline = deadline or Deadline(480)
    names = universe(repo, settings)
    start = date(today.year - settings.fin_years, 1, 1)
    # 기준은 실행 날짜 0시 (UTC). 실제 실행에선 today = 오늘이라 현재 시각 기준과 하루 안쪽 차이
    day0 = datetime(today.year, today.month, today.day, tzinfo=UTC)
    fresh_after = day0 - timedelta(days=settings.fin_refresh_days)
    budget = limit
    for source, keymap in _financial_targets(names, settings.etfs).items():
        adapter = adapters.get(source)
        if adapter is None or not keymap:
            continue
        attempts = repo.fetch_attempts(source, list(keymap))

        def due(k: str, attempts: dict = attempts) -> bool:
            a = attempts.get(k)
            if a is None:
                return True
            if a["last_success_at"] is None:
                return a["failures"] < MAX_FAILURES
            return a["last_success_at"] < fresh_after

        keys = sorted(
            (k for k in keymap if due(k)),
            key=lambda k: (
                (attempts.get(k) or {}).get("last_success_at") or datetime.min.replace(tzinfo=UTC)
            ),
        )
        res.counts[f"{source}_pending"] = len(keys)
        if len(keys) > budget:
            res.done = False
        for part in _chunks(keys[:budget], chunk):
            if deadline.over():
                res.done = False
                break
            _ensure_assets(repo, {keymap[k]: names[keymap[k]] for k in part})
            batch = adapter.fetch(part, start, today)
            rows, _ = normalize_financials(
                batch, {k: default_asset(keymap[k]).asset_id for k in part}
            )
            stored = repo.upsert_financials(rows) if rows else 0
            per_key: dict[str, int] = defaultdict(int)
            for k in part:
                per_key[k] = len(batch.payload.get(k) or [])
            repo.log_fetches(
                source,
                [
                    _log_row(
                        k, start, today, batch.fetched_at, batch.failed_keys.get(k), per_key[k]
                    )
                    for k in part
                ],
            )
            for k in part:
                if err := batch.failed_keys.get(k):
                    res.failed[f"{source}:{k}"] = err
            res.counts[f"{source}_keys"] += len(part)
            res.counts[f"{source}_rows"] += stored
            budget -= len(part)
        if budget <= 0:
            break
    return res


# ---------------------------------------------------------------- 뉴스
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
        kr = spec["market"] == "KR"
        query_to_symbol: dict[str, str] = {}
        for t, name in names.items():
            if t in skip or is_kr_symbol(t) != kr:
                continue
            query_to_symbol.setdefault(name or t, t)
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
        for part in _chunks(queries[:limit], chunk):
            if deadline.over():
                res.done = False
                break
            oldest = min((last_ok(q) for q in part if last_ok(q)), default=None)
            start = max((oldest or now - timedelta(days=7)).date(), today - timedelta(days=30))
            symbols = {query_to_symbol[q]: names[query_to_symbol[q]] for q in part}
            _ensure_assets(repo, symbols)
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
                    _log_row(
                        q, start, today, batch.fetched_at, err, len(batch.payload.get(q) or [])
                    )
                )
                if err:
                    res.failed[f"{lane}:{q}"] = err
            repo.log_fetches(spec["source"], logs)
            res.counts[f"{lane}_queries"] += len(part)
            res.counts[f"{lane}_rows"] += stored
    res.counts["pruned"] = repo.prune_news(now - timedelta(days=settings.news_keep_days))
    return res


# ---------------------------------------------------------------- 실행 진입점 (실제 출처)
def _open(repo: ExtendedRepository | None) -> ExtendedRepository:
    if repo is not None:
        return repo
    from myfinsight.data.repository import open_repository

    return open_repository()


def _try(make: Callable[[], Any], what: str, notes: list[str]) -> Any:
    """키가 없는 출처는 건너뛴다 (MissingApiKeyError 등)."""
    try:
        return make()
    except Exception as exc:  # noqa: BLE001
        notes.append(f"{what} 건너뜀: {exc}")
        return None


def run_prices(
    repo: ExtendedRepository | None = None,
    *,
    budget_sec: float = 480,
    limit: int = 100,
    market: str = "ALL",
    lanes: Sequence[str] | None = None,
    sample: int | None = None,
) -> JobResult:
    from myfinsight.data.adapters.factory import price_adapter

    repo = _open(repo)
    settings = JobSettings.from_env()
    if sample is not None:  # 표본 줄(Tiingo) 이번 실행 종목 수 (주간 실행에서 한 번에)
        settings.sample_daily = {k: sample for k in settings.sample_daily}
    today = datetime.now(UTC).date()
    notes: list[str] = []
    if not any(repo.latest_constituents(i) for i in settings.indices):
        # 처음 실행: 구성종목이 아직 없으면 먼저 받음 (meta 작업보다 먼저 돌았을 때)
        from myfinsight.data.constituent_source import default_constituent_source

        cons = refresh_constituents(
            repo, settings, source=default_constituent_source(), today=today
        )
        notes.append(f"구성종목 먼저 받음: {cons.to_dict()['counts']}")
    adapters = {
        lane: a
        for lane in settings.price_lanes
        if lane in PRICE_LANES
        and (a := _try(lambda s=lane: _checked(price_adapter(s)), lane, notes)) is not None
    }
    deadline = Deadline(budget_sec)
    res = price_step(
        repo,
        settings,
        adapters=adapters,
        today=today,
        limit=limit,
        deadline=deadline,
        market=market,
        lanes=lanes,
    )
    res.notes.extend(notes)
    # 남은 시간에 교차검증 (예약 함수를 늘리지 않음). 못 끝낸 몫은 다음 실행이 이어 받음
    ver = verify_job(repo, deadline=deadline)
    res.counts.update({f"verify_{k}": n for k, n in ver.counts.items()})
    if not ver.done:
        res.notes.append("교차검증 남음: 다음 실행에서 이어감")
    return res


def verify_job(
    repo: ExtendedRepository,
    *,
    deadline: Deadline | None = None,
    start: date | None = None,
    end: date | None = None,
) -> JobResult:
    """출처 간 교차검증 (verify.py). start·end 를 주면 그 기간 표시를 지우고 다시 계산."""
    from myfinsight.data.verify import reverify, verify_step

    if start is not None or end is not None:
        v = reverify(repo, start or date(1900, 1, 1), end or date(2999, 12, 31), deadline=deadline)
    else:
        v = verify_step(repo, deadline=deadline)
    res = JobResult("verify", done=v.done, notes=[f"MISMATCH {m}" for m in v.mismatches])
    res.counts.update(v.counts)
    return res


def run_verify(
    repo: ExtendedRepository | None = None,
    *,
    budget_sec: float = 480,
    start: date | None = None,
    end: date | None = None,
) -> JobResult:
    return verify_job(_open(repo), deadline=Deadline(budget_sec), start=start, end=end)


def run_meta(
    repo: ExtendedRepository | None = None, *, budget_sec: float = 480, limit: int = 120
) -> list[JobResult]:
    from myfinsight.data.adapters.factory import financial_adapter
    from myfinsight.data.constituent_source import default_constituent_source

    repo = _open(repo)
    settings = JobSettings.from_env()
    today = datetime.now(UTC).date()
    deadline = Deadline(budget_sec)
    cons = refresh_constituents(repo, settings, source=default_constituent_source(), today=today)
    notes: list[str] = []
    adapters = {
        s: a
        for s in ("DART", "SEC_EDGAR")
        if (a := _try(lambda s=s: _checked(financial_adapter(s)), s, notes)) is not None
    }
    fin = financial_step(
        repo, settings, adapters=adapters, today=today, limit=limit, deadline=deadline
    )
    fin.notes.extend(notes)
    return [cons, fin]


def run_news(repo: ExtendedRepository | None = None, *, budget_sec: float = 480) -> JobResult:
    from myfinsight.data.adapters.factory import news_adapter

    repo = _open(repo)
    notes: list[str] = []
    adapters = {
        lane: a
        for lane, spec in NEWS_LANES.items()
        if (
            a := _try(
                lambda s=spec: _checked(news_adapter(s["source"], **s["kwargs"])), lane, notes
            )
        )
        is not None
    }
    res = news_step(
        repo,
        JobSettings.from_env(),
        adapters=adapters,
        today=datetime.now(UTC).date(),
        deadline=Deadline(budget_sec),
    )
    res.notes.extend(notes)
    return res


_NEEDS: dict[str, tuple[str, ...]] = {
    "KIS": ("KIS_APP_KEY", "KIS_APP_SECRET"),
    "ALPACA": ("ALPACA_API_KEY_ID", "ALPACA_API_SECRET_KEY"),
    "TIINGO": ("TIINGO_API_KEY",),
    "DART": ("DART_API_KEY",),
    "SEC_EDGAR": ("SEC_USER_AGENT",),
    "NAVER_NEWS": ("NAVER_CLIENT_ID", "NAVER_CLIENT_SECRET"),
    "NEWSAPI": ("NEWSAPI_KEY",),
}


def _checked(adapter: Any) -> Any:
    """필요한 .env 키가 비었으면 미리 알림 (요청마다 실패 기록이 쌓이지 않게)."""
    need = _NEEDS.get(adapter.source_name, ())
    config.require(**{k: config.get(k) for k in need})
    return adapter


def main(argv: Sequence[str] | None = None) -> int:
    p = argparse.ArgumentParser(description="역할 A 서버 수집 작업")
    p.add_argument("job", choices=["prices", "meta", "news", "verify", "all"])
    p.add_argument("--budget", type=float, default=480, help="시간 예산(초)")
    p.add_argument("--limit", type=int, default=None, help="한 번에 처리할 종목 수")
    p.add_argument("--start", type=date.fromisoformat, help="verify: 다시 계산할 시작일")
    p.add_argument("--end", type=date.fromisoformat, help="verify: 다시 계산할 종료일")
    p.add_argument(
        "--market", choices=["KR", "US", "ALL"], default="ALL", help="prices: 이 시장 종목만"
    )
    p.add_argument("--lanes", help="prices: 받을 출처 줄만 (예: ALPACA 또는 YFINANCE,TIINGO)")
    p.add_argument("--sample", type=int, help="prices: 표본 줄(Tiingo) 이번 실행 종목 수")
    a = p.parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
    results: list[JobResult] = []
    if a.job in ("prices", "all"):
        results.append(
            run_prices(
                budget_sec=a.budget,
                limit=a.limit or 100,
                market=a.market,
                lanes=_csv(a.lanes) if a.lanes else None,
                sample=a.sample,
            )
        )
    if a.job in ("meta", "all"):
        results.extend(run_meta(budget_sec=a.budget, limit=a.limit or 100))
    if a.job in ("news", "all"):
        results.append(run_news(budget_sec=a.budget))
    if a.job == "verify":
        results.append(run_verify(budget_sec=a.budget, start=a.start, end=a.end))
    print(json.dumps([r.to_dict() for r in results], ensure_ascii=False, indent=2, default=str))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
