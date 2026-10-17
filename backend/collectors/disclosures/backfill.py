"""공시 첫 수집 (PC, backend/scripts/backfill.py --what disclosures): start_year(2000)년부터.

- SEC EDGAR: 종목마다 submissions 한 번(+ 예전 쪽 파일들)에 전체 이력이 오므로 한 번에.
  이어 받기 target = disclosures_backfill:<티커> (성공하면 다시 안 받음, 그 뒤는 update.py 가 채움)
- DART: 종목·연도마다 공시검색 (100건씩 쪽 넘김, 회사 하나에 한 해 2~3번).
  target = disclosures_backfill:<6자리>:<YYYY>. 지난 해는 한 번 끝나면 건너뜀, 올해는 매번.
  DART 공시검색은 2000년부터 응답한다 (1999년은 사업보고서 몇 건뿐, 1998년 이전은 없음).
  하루 요청 한도(2만 건 안팎)에 걸리면(DartLimitError) DART 를 멈추고 다음 실행이 이어 받는다.
같은 해를 모든 종목에 대해 끝낸 뒤 그 전 해로 가므로(최근 해부터), 중간에 멈춰도 종목 간 균형이 맞는다.
"""

from __future__ import annotations

from datetime import UTC, date, datetime
from typing import Any

from backend.collectors.common import JobResult, JobSettings, Progress
from backend.collectors.disclosures.update import (
    DartFetch,
    DisclosureSink,
    SecFetch,
    _stop_error,
    dart_rows,
    sec_rows,
    targets,
)
from backend.db.base import ExtendedRepository

PREFIX = "disclosures_backfill:"


def sec_backfill(
    repo: ExtendedRepository,
    settings: JobSettings,
    *,
    fetch: SecFetch,
    today: date,
    start_year: int,
    deadline: Any,
    flush_every: int = 20,
    progress: Progress | None = None,
) -> JobResult:
    res = JobResult("disclosures_backfill:SEC_EDGAR")
    keys = targets(repo, settings, "US")
    done = repo.fetch_targets_done("SEC_EDGAR", PREFIX)
    since = date(start_year, 1, 1)
    sink = DisclosureSink(repo, "SEC_EDGAR", flush_every)
    try:
        for n, (key, symbol) in enumerate(keys.items(), start=1):
            target = f"{PREFIX}{key}"
            if target in done:
                continue
            if deadline.over():
                res.done = False
                break
            at = datetime.now(UTC)
            try:
                cik, got = fetch(key, since)
                rows, err = sec_rows(symbol, cik, got, at), None
            except Exception as exc:  # noqa: BLE001 - 한 종목 실패는 기록하고 다음 종목
                got, rows, err = [], [], f"{type(exc).__name__}: {exc}"
                res.failed[target] = err
            sink.add(rows, target=target, start=since, end=today, at=at, error=err,
                     fetched=len(got))  # fmt: skip
            res.counts["SEC_EDGAR_requests"] += 1
            if progress and n % 20 == 0:
                progress(f"[disclosures SEC_EDGAR] {n}/{len(keys)}종목, 받은 공시 "
                         f"{sink.fetched:,} · 새로 저장 {sink.stored:,}")  # fmt: skip
    finally:
        sink.flush()
        res.counts["SEC_EDGAR_rows"] = sink.stored
    return res


def dart_backfill(
    repo: ExtendedRepository,
    settings: JobSettings,
    *,
    fetch: DartFetch,
    today: date,
    start_year: int,
    deadline: Any,
    flush_every: int = 20,
    progress: Progress | None = None,
) -> JobResult:
    res = JobResult("disclosures_backfill:DART")
    keys = targets(repo, settings, "KR")
    done = repo.fetch_targets_done("DART", PREFIX)
    sink = DisclosureSink(repo, "DART", flush_every)
    try:
        for year in range(today.year, start_year - 1, -1):
            first, last = date(year, 1, 1), min(date(year, 12, 31), today)
            for code, symbol in keys.items():
                target = f"{PREFIX}{code}:{year}"
                if year < today.year and target in done:
                    continue
                if deadline.over():
                    res.done = False
                    return res
                at = datetime.now(UTC)
                try:
                    got = fetch(code, first, last)
                    rows, err = dart_rows(symbol, got, at), None
                except Exception as exc:  # noqa: BLE001
                    if _stop_error(exc):
                        res.done = False
                        res.notes.append(f"DART 멈춤 (다음 실행이 이어 받음): {exc}")
                        return res
                    got, rows, err = [], [], f"{type(exc).__name__}: {exc}"
                    res.failed[target] = err
                sink.add(rows, target=target, start=first, end=last, at=at, error=err,
                         fetched=len(got))  # fmt: skip
                res.counts["DART_requests"] += 1
            if progress:
                progress(f"[disclosures DART] {year}년 끝: 받은 공시 {sink.fetched:,} · "
                         f"새로 저장 {sink.stored:,}")  # fmt: skip
    finally:
        sink.flush()
        res.counts["DART_rows"] = sink.stored
    return res
