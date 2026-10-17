"""가격 긴 백필 (PC): 10년치 중 빈 곳만. Tiingo(표본 줄)는 빼고, 종목 수 제한 없이."""

from __future__ import annotations

from datetime import date
from typing import Any

from backend.collectors.common import JobResult, JobSettings
from backend.collectors.prices.update import FxFetch, price_step
from backend.db.base import ExtendedRepository


def price_backfill(
    repo: ExtendedRepository,
    settings: JobSettings,
    *,
    adapters: dict[str, Any],
    today: date,
    deadline: Any,
    market: str = "ALL",
    fred: FxFetch | None = None,
) -> JobResult:
    lanes = {k: v for k, v in adapters.items() if k != "TIINGO"}
    return price_step(
        repo, settings, adapters=lanes, today=today, limit=10**6, deadline=deadline,
        market=market, fred=fred,
    )  # fmt: skip
