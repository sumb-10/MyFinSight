"""구성종목 갱신 (M02-05): 정기 변경일이 지났으면 지수별로 새로 받아 저장."""

from __future__ import annotations

from datetime import date
from typing import Any

from backend.collectors.common import JobResult, JobSettings
from backend.collectors.constituents.collector import ConstituentCollector
from backend.db.base import ExtendedRepository
from backend.schemas.errors import DataSourceError


def refresh_constituents(
    repo: ExtendedRepository, settings: JobSettings, *, source: Any, today: date
) -> JobResult:
    """지수별 구성종목: 정기 변경일이 지났으면 새로 받아 저장 (M02-05).

    받은 스냅샷이 행 수 범위(constituents.ROW_BOUNDS: SP500 495~510, NDX 98~105, KOSPI200 195~205)
    등 결과 검사를 통과하지 못하면 저장하지 않고, fetch_log 에 FAILED 와 이유를 남긴다
    (ConstituentCollector.update_one). 기존 스냅샷이 있으면 그대로 쓰고 notes 에 경고.
    """
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
