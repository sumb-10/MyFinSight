"""M00-02 실행 기록 스키마 (M08-01, 명세서 그대로 옮긴 임시본)."""

from __future__ import annotations

from datetime import datetime
from enum import Enum

from pydantic import BaseModel, ConfigDict


class StepStatus(str, Enum):
    STARTED = "STARTED"
    SUCCESS = "SUCCESS"
    PARTIAL = "PARTIAL"
    FAILED = "FAILED"
    SKIPPED = "SKIPPED"


class StepRecord(BaseModel):
    model_config = ConfigDict(extra="forbid")

    run_id: str
    step: str
    status: StepStatus
    started_at: datetime
    ended_at: datetime | None = None
    summary: str | None = None
    sources: list[str] = []
    error_code: str | None = None
    error_message: str | None = None
