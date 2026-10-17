"""재무: 한국 DART, 미국 SEC EDGAR. 처음 한 번은 FIN_YEARS(기본 12)년치 전체를 받고, 그 뒤로는
FIN_REFRESH_DAYS 마다 최근 2년(작년 1월 1일부터)만 다시 받는다 (fetch_log 의 start_date 로 판단)."""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Callable, Iterable
from datetime import UTC, date, datetime, timedelta
from typing import Any

from backend.collectors.common import (
    MAX_FAILURES,
    Deadline,
    JobResult,
    JobSettings,
    chunks,
    ensure_assets,
    log_row,
    universe,
)
from backend.db.base import ExtendedRepository
from backend.pipeline.normalizer import default_asset, is_kr_symbol, normalize_financials
from backend.schemas.errors import DataSourceError


def financial_targets(
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
    progress: Callable[[str], None] | None = None,
) -> JobResult:
    """재무 한 단계.

    - 전체 기간(FIN_YEARS 년 전 1월 1일부터)을 아직 성공적으로 받지 못한 종목: 전체 기간 (먼저)
    - 이미 받은 종목: 마지막 성공이 FIN_REFRESH_DAYS 보다 오래됐으면 최근분만
      (fin_refresh_years 년 전 1월 1일부터)
    - 출처가 한도·키 오류(DataSourceError, 예: DART 020)를 내면 그 출처는 이번 실행에서 멈춘다
      (fetch_log 를 남기지 않아 다음 실행이 같은 종목부터 이어 받음)
    """
    res = JobResult("financials")
    deadline = deadline or Deadline(480)
    names = universe(repo, settings)
    full_start = date(today.year - settings.fin_years, 1, 1)
    refresh_start = date(today.year - settings.fin_refresh_years, 1, 1)
    # 기준은 실행 날짜 0시 (UTC). 실제 실행에선 today = 오늘이라 현재 시각 기준과 하루 안쪽 차이
    day0 = datetime(today.year, today.month, today.day, tzinfo=UTC)
    fresh_after = day0 - timedelta(days=settings.fin_refresh_days)
    budget = limit
    for source, keymap in financial_targets(names, settings.etfs).items():
        adapter = adapters.get(source)
        if adapter is None or not keymap:
            continue
        keys_all = list(keymap)
        full = repo.fetch_attempts(source, keys_all, start_on_or_before=full_start)
        anyrun = repo.fetch_attempts(source, keys_all)

        def start_of(
            k: str, full: dict = full, anyrun: dict = anyrun
        ) -> tuple[date, datetime] | None:
            f = full.get(k) or {}
            if f.get("last_success_at") is None and f.get("failures", 0) < MAX_FAILURES:
                return full_start, datetime.min.replace(tzinfo=UTC)
            a = anyrun.get(k) or {}
            last = a.get("last_success_at")
            if last is None:
                return None  # 실패만 MAX_FAILURES 번
            return (refresh_start, last) if last < fresh_after else None

        plan = {k: p for k in keys_all if (p := start_of(k)) is not None}
        keys = sorted(plan, key=lambda k: (plan[k][0] != full_start, plan[k][1], k))
        res.counts[f"{source}_pending"] = len(keys)
        res.counts[f"{source}_full_pending"] = sum(plan[k][0] == full_start for k in keys)
        if len(keys) > budget:
            res.done = False
        todo = keys[:budget]
        groups: dict[date, list[str]] = defaultdict(list)
        for k in todo:
            groups[plan[k][0]].append(k)
        stop = False
        done_n = 0
        for start, group in sorted(groups.items()):
            for part in chunks(group, chunk):
                if deadline.over():
                    res.done = False
                    stop = True
                    break
                ensure_assets(repo, {keymap[k]: names[keymap[k]] for k in part})
                try:
                    batch = adapter.fetch(part, start, today)
                except DataSourceError as exc:  # 한도 초과·키 오류: 이 출처는 다음 실행에
                    res.failed[f"{source}:*"] = str(exc)
                    res.notes.append(f"{source} 멈춤: {exc}")
                    res.done = False
                    stop = True
                    break
                rows, _ = normalize_financials(
                    batch, {k: default_asset(keymap[k]).asset_id for k in part}
                )
                stored = repo.upsert_financials(rows) if rows else 0
                repo.log_fetches(
                    source,
                    [
                        log_row(
                            k,
                            start,
                            today,
                            batch.fetched_at,
                            batch.failed_keys.get(k),
                            len(batch.payload.get(k) or []),
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
                done_n += len(part)
                if progress:
                    progress(
                        f"[financials {source}] {done_n}/{len(todo)}종목 "
                        f"(시작 {start}), 저장 {res.counts[f'{source}_rows']:,}행"
                    )
            if stop:
                break
        if budget <= 0:
            break
    return res
