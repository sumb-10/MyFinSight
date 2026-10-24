"""M00-02 실행 기록 스키마 (데이터 계약 run_step, module_prototype2 2.2절 (b)).

DB run_step 한 행 = StepRecord 하나. status 는 계약의 6가지 값.
"""

from __future__ import annotations

from datetime import datetime
from enum import Enum

from pydantic import BaseModel, ConfigDict


class StepStatus(str, Enum):
    QUEUED = "QUEUED"
    STARTED = "STARTED"
    SUCCESS = "SUCCESS"
    PARTIAL = "PARTIAL"
    FAILED = "FAILED"
    CANCELLED = "CANCELLED"


class StepRecord(BaseModel):
    model_config = ConfigDict(extra="forbid")

    run_id: str
    step: str
    status: StepStatus
    started_at: datetime | None = None  # QUEUED 는 아직 시작 전
    ended_at: datetime | None = None
    summary: str | None = None
    error_code: str | None = None
    error_message: str | None = None
