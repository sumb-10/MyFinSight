"""가격: 출처 줄(PRICE_LANES)마다 ① 최근 increment_days(10)일 증분 ② 그 출처로 아직 N년치가 없는
종목 백필. 매일 실행(jobs/daily.py prices)과 긴 백필(prices/backfill.py)이 같은 단계를 쓴다."""

from __future__ import annotations

import logging
import time
from collections import defaultdict
from collections.abc import Callable, Sequence
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, date, datetime, timedelta
from datetime import time as dtime
from typing import Any
from zoneinfo import ZoneInfo

from backend.collectors.common import (
    MAX_FAILURES,
    PRICE_LANES,
    Deadline,
    JobResult,
    JobSettings,
    chunks,
    ensure_assets,
    log_row,
    sync_asset_types,
    universe,
    years_before,
)
from backend.db.base import ExtendedRepository
from backend.db.sql import START_GRACE_DAYS, previous_weekday
from backend.pipeline.normalizer import currency_of_symbol, default_asset, is_kr_symbol, normalize
from backend.schemas.market import FxRate

logger = logging.getLogger(__name__)
FxFetch = Callable[[date, date], list[FxRate]]
"""(시작일, 끝일) → 환율 목록 (FRED 등 가격 어댑터 밖의 환율 출처)."""

MARKET_CLOSE: dict[str, tuple[ZoneInfo, dtime]] = {
    # 장 마감 + 30분 (종가가 확정되고 출처에 올라오는 시각). 이 뒤면 그날 가격까지 요청
    "KR": (ZoneInfo("Asia/Seoul"), dtime(16, 0)),  # 15:30 마감
    "US": (ZoneInfo("America/New_York"), dtime(16, 30)),  # 16:00 마감
}


def closed_through(market: str, now: datetime) -> date:
    """now 기준으로 장이 끝난 마지막 날짜 (현지). 마감 전이면 현지 전날.

    주말·공휴일은 보지 않음 (그날 요청이 비어도 다음 실행이 다시 받음).
    """
    tz, after = MARKET_CLOSE[market]
    local = now.astimezone(tz)
    return local.date() if local.time() >= after else local.date() - timedelta(days=1)


def _in_market(symbol: str, market: str) -> bool:
    return market == "ALL" or is_kr_symbol(symbol) == (market == "KR")


def _request_key(lane: str, symbol: str) -> str:
    """출처가 받는 종목 코드. KIS 는 6자리 종목코드, 나머지는 yfinance 표기."""
    return default_asset(symbol).ticker if lane == "KIS" else symbol


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
            log_row(t, start, end, batch.fetched_at, failed.get(t), len(payload.get(t) or []))
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
    """이 출처에서 받을 (종목, 시작일) 목록. ① 최근 증분 ② 백필 (sample 줄은 ③ 표본만).

    end 까지 받아야 하는 마지막 평일(need_until) 보다 저장 범위가 짧은 종목이 증분 대상.
    """
    need_until = min(
        end, previous_weekday(end + timedelta(days=1), getattr(repo, "cache_max_age_days", 1))
    )
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
    fred: FxFetch | None = None,
    now: datetime | None = None,
) -> JobResult:
    """가격 한 단계: 출처 줄(PRICE_LANES)마다 ① 최근 증분 ② N년치 백필을 받는다.

    환율을 먼저 받고, 줄(KIS·Alpaca·yfinance·Tiingo)을 동시에 chunk 종목씩 처리한다.
    줄마다 한 번에 최대 limit 종목. 시간 예산이 끝나면 멈추고 done=False.
    adapters 에 없는 줄(키 없음 등)은 건너뜀.
    market: KR·US 면 그 시장 종목만. lanes: 받을 줄만 (None = adapters 전부).
    ALPACA 는 받는데 YFINANCE 줄은 안 받는 실행(미국 매일분)에서는 Alpaca 가 못 받은 종목만
    yfinance 로 대신 받는다 (adapters 에 YFINANCE 가 있을 때).
    fred: 환율 두 번째 출처 (FRED DEXKOUS). 환율을 받는 실행이면 같은 기간을 받아 출처별로 저장
    (yfinance KRW=X 가 없는 2003-11 전 등은 FRED 값이 fx_daily 에 실림).
    now: 지금 시각. 주면 시장마다 장이 끝난 날(closed_through)까지 받는다
    (한국 16:00 KST 뒤 실행이면 그날 종가까지). 없으면 두 시장 모두 today 전날까지.
    """
    res = JobResult("prices")
    deadline = deadline or Deadline(480)
    names = universe(repo, settings)
    res.counts["etf_marked"] = sync_asset_types(repo, settings)
    end = today - timedelta(days=1)
    inc_start = end - timedelta(days=settings.increment_days)
    full_start = years_before(end, settings.backfill_years)
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
    market_end = {m: closed_through(m, now) if now else end for m in ("KR", "US")}

    # 줄마다 할 일(요청 묶음)을 만든 뒤 줄마다 스레드 하나로 동시에 처리:
    # 출처마다 요청 간격·응답 대기가 따로라 겹치면 빨라지고, 한 출처가 느려도 다른 출처는 진행됨
    queues: dict[str, list[tuple[date, date, list[str]]]] = {}
    chosen = [x.upper() for x in lanes] if lanes is not None else list(adapters)
    for lane, spec in PRICE_LANES.items():
        adapter = adapters.get(lane)
        if adapter is None or lane not in chosen:
            continue
        source = adapter.source_name
        plan: list[tuple[str, date, date]] = []
        for m, m_end in market_end.items():  # 시장마다 받을 끝날이 다름
            tickers = [
                t
                for t in names
                if _in_market(t, spec["market"]) and _in_market(t, market) and _in_market(t, m)
            ]
            if not tickers:
                continue
            m_plan = _lane_plan(
                repo,
                lane,
                source,
                tickers,
                today=today,
                end=m_end,
                inc_start=inc_start,
                full_start=full_start,
                sample_size=settings.sample_daily.get(lane, 0),
            )
            plan += [(t, start, m_end) for t, start in m_plan]
        res.counts[f"{lane}_pending"] = len(plan)
        if len(plan) > limit:
            res.done = False
        groups: dict[tuple[date, date, str], list[str]] = defaultdict(list)
        for t, start, m_end in plan[:limit]:
            groups[(start, m_end, currency_of_symbol(t))].append(t)
        queues[lane] = [
            (start, m_end, part)
            for (start, m_end, _cur), group in groups.items()
            for part in chunks(group, chunk)
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
    if fx_due and fred is not None and not deadline.over():
        try:
            res.counts["fx_fred_rows"] += repo.upsert_fx(fred(fx_start, end))
        except Exception as exc:  # noqa: BLE001 - 보조 출처: 실패는 기록만
            res.notes.append(f"FRED 환율 건너뜀: {type(exc).__name__}: {exc}")

    def run_lane(lane: str) -> JobResult:  # 출처마다 스레드 하나 (요청 대기 시간이 겹치게)
        out = JobResult("prices")
        for start, part_end, part in queues[lane]:
            if deadline.over():
                out.done = False
                break
            ensure_assets(repo, {t: names.get(t) for t in part})
            rows, _, failed = store_prices(repo, adapters[lane], part, start, part_end, lane=lane)
            out.counts[f"{lane}_tickers"] += len(part)
            out.counts[f"{lane}_rows"] += rows
            out.failed.update({f"{lane}:{t}": e for t, e in failed.items()})
            for t in failed:
                missed[lane].append((start, part_end, t))
        return out

    missed: dict[str, list[tuple[date, date, str]]] = defaultdict(list)

    lanes = [lane for lane, q in queues.items() if q]
    if lanes:
        # SQLite(PC 실행)는 동시 쓰기에 약해서 한 줄씩
        workers = len(lanes) if getattr(repo, "dialect", "") == "postgresql" else 1
        with ThreadPoolExecutor(max_workers=workers) as pool:
            for part_res in pool.map(run_lane, lanes):
                res.counts.update(part_res.counts)
                res.failed.update(part_res.failed)
                res.done = res.done and part_res.done
    _fallback(repo, adapters, missed, chosen, res, deadline)
    return res


FALLBACK_LANES = {"ALPACA": "YFINANCE"}
"""primary 줄이 못 받은 종목을 대신 받을 줄 (그 줄을 이번 실행에서 안 받을 때만)."""


def _fallback(
    repo: ExtendedRepository,
    adapters: dict[str, Any],
    missed: dict[str, list[tuple[date, date, str]]],
    chosen: list[str],
    res: JobResult,
    deadline: Deadline,
) -> None:
    for lane, other in FALLBACK_LANES.items():
        if not missed.get(lane) or other in chosen or other not in adapters:
            continue
        groups: dict[tuple[date, date], list[str]] = defaultdict(list)
        for start, end, t in missed[lane]:
            groups[(start, end)].append(t)
        for (start, end), group in groups.items():
            for part in chunks(group, 50):
                if deadline.over():
                    res.done = False
                    return
                rows, _, failed = store_prices(repo, adapters[other], part, start, end, lane=other)
                res.counts[f"{other}_fallback_tickers"] += len(part)
                res.counts[f"{other}_fallback_rows"] += rows
                res.failed.update({f"{other}:{t}": e for t, e in failed.items()})
