"""재무 긴 백필 (PC): FIN_YEARS 년치 전체를 종목 수 제한 없이 (financial_step 과 같은 규칙)."""

from __future__ import annotations

from datetime import date
from typing import Any

from backend.collectors.common import JobResult, JobSettings, Progress
from backend.collectors.financials.update import financial_step
from backend.db.base import ExtendedRepository


def financial_backfill(
    repo: ExtendedRepository,
    settings: JobSettings,
    *,
    adapters: dict[str, Any],
    today: date,
    deadline: Any,
    progress: Progress | None = None,
) -> JobResult:
    return financial_step(
        repo,
        settings,
        adapters=adapters,
        today=today,
        limit=10**6,
        deadline=deadline,
        progress=progress,
    )
