"""M00-02 근거·Report 스키마 (명세서 그대로 옮긴 임시본)."""

from __future__ import annotations

from datetime import date, datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict

from backend.schemas.profile import UserProfile
from backend.schemas.results import CalcConditions, MetricsBundle
from backend.schemas.runlog import StepRecord
from backend.schemas.spec import StrategySpec


class EvidenceItem(BaseModel):
    """M06-01."""

    model_config = ConfigDict(extra="forbid")

    subject: str  # 티커 또는 "portfolio"/"universe"
    kind: Literal["universe", "selection", "weight", "cap", "metric", "limitation"]
    statement: str  # 템플릿으로 만든 문장
    values: dict[str, float | str]  # 문장에 들어간 수치 원본
    source: str
    as_of: date


class AllocationRow(BaseModel):
    model_config = ConfigDict(extra="forbid")

    ticker: str
    name: str | None
    weight: float
    amount_usd: float
    amount_krw: int


class ReportData(BaseModel):
    """M06-02 가 텍스트로 렌더링하는 구조 데이터."""

    model_config = ConfigDict(extra="forbid")

    run_id: str
    created_at: datetime
    profile: UserProfile
    spec: StrategySpec
    spec_hash: str
    allocation_as_of: date
    allocation: list[AllocationRow]
    metrics: MetricsBundle
    conditions: CalcConditions
    evidence: list[EvidenceItem]
    limitations: list[str]
    process_summary: list[StepRecord]


class Report(BaseModel):
    model_config = ConfigDict(extra="forbid")

    data: ReportData
    text_markdown: str
    display_values: dict[str, str]  # 필드 경로 → 텍스트에 표시된 문자열 (M04-03 CONSIST_TEXT용)
