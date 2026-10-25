"""실행 색인(runs.json 한 줄)과 API 의 실행 상태 (M0-05)."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict

RunState = Literal["queued", "running", "cancelling", "success", "partial", "failed", "cancelled"]

# UI 가 보여 주는 다섯 묶음 (Module7 §3)
BUCKETS: list[tuple[str, str]] = [
    ("conditions", "조건과 자료 확인"),
    ("candidates", "후보 선정과 포트폴리오 구성"),
    ("backtest", "백테스트"),
    ("validation", "사용자 조건 검증"),
    ("report", "리포트 구성과 정합성 검사"),
]


class RunIndexEntry(BaseModel):
    model_config = ConfigDict(extra="allow")

    run_id: str
    request_id: str
    status: RunState
    queued_at: str
    started_at: str | None = None
    finished_at: str | None = None
    output_dir: str
    report_id: str | None = None
    llm_mode: Literal["stub", "api"] | None = None
    error_code: str | None = None
    error_message: str | None = None
    cancel_requested_at: str | None = None
    worker_pid: int | None = None
    scenario: str | None = None


class RunStep(BaseModel):
    step: str
    label_ko: str
    bucket: str
    status: Literal["QUEUED", "STARTED", "SUCCESS", "PARTIAL", "FAILED", "CANCELLED"]
    started_at: str | None = None
    ended_at: str | None = None
    summary: str | None = None
    error_code: str | None = None
    error_message: str | None = None


class RunBucket(BaseModel):
    id: str
    title_ko: str
    status: Literal["QUEUED", "STARTED", "SUCCESS", "PARTIAL", "FAILED", "CANCELLED"]


class RunStatus(BaseModel):
    run_id: str
    request_id: str
    status: RunState
    queue_position: int | None = None
    queued_at: str
    started_at: str | None = None
    finished_at: str | None = None
    buckets: list[RunBucket]
    steps: list[RunStep]
    report_id: str | None = None
    error: dict | None = None
