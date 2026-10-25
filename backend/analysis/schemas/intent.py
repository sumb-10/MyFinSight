"""의도 해석 (M3-01, LLM #1). 보충 질문 제안(`questions`)은 schemas.dialog.Question 과 같은 모양."""

from __future__ import annotations

from typing import Any

from datetime import date
from typing import Literal

from pydantic import BaseModel, Field, field_validator, model_validator

from backend.analysis.schemas.dialog import QuestionProposal
from backend.analysis.schemas.request import TEMPLATE_METRICS, RiskTolerance, Template


def _check_gics_codes(codes: list[str]) -> list[str]:
    for c in codes:
        if not (c.isdigit() and len(c) in (2, 4, 6, 8)):
            raise ValueError(f"GICS code must be 2/4/6/8 digits, got {c!r}")
    return codes


class Theme(BaseModel):
    id: str = Field(pattern=r"^[a-z0-9_]+$")
    label_ko: str
    description_ko: str
    gics_codes: list[str] = []
    keywords: list[str] = []
    example_tickers: list[str] = []
    _v = field_validator("gics_codes")(_check_gics_codes)


class ExcludeThemeRule(BaseModel):
    theme: str
    gics_codes: list[str] = []
    keywords: list[str] = []
    _v = field_validator("gics_codes")(_check_gics_codes)


class Conflict(BaseModel):
    field: str
    issue_ko: str
    resolution_ko: str
    idea_value: Any | None = None  # 아이디어가 뜻하는 값 (필드 타입 그대로). 프로필 기본값과 충돌하면 코드가 이 값으로 '아이디어대로' 보기를 만든다


class Interpretation(BaseModel):
    summary_ko: str
    themes: list[Theme] = Field(min_length=1)
    style_hints: list[str] = []
    conflicts: list[Conflict] = []


class ThemeFilter(BaseModel):
    min_confidence: float = Field(ge=0, le=1, default=0.5)


class Screen(BaseModel):
    template: Template
    metric: str
    direction: Literal["asc", "desc"]
    as_of: date
    theme_filter: ThemeFilter = ThemeFilter()
    select_top_n: int = Field(ge=1)

    @model_validator(mode="after")
    def _metric_matches_template(self) -> Screen:
        m, d = TEMPLATE_METRICS[self.template]
        if (self.metric, self.direction) != (m, d):
            raise ValueError(f"template {self.template} requires metric={m}, direction={d}")
        return self


class RiskParams(BaseModel):
    risk_tolerance: RiskTolerance
    effective_max_drawdown: float = Field(gt=0, le=1)
    volatility_preference: Literal["low", "medium", "high"]
    notes_ko: str = ""


class NewsTilt(BaseModel):
    enabled: bool
    max_view_confidence: float = Field(ge=0, le=1)
    max_tilt_per_stock: float = Field(ge=0, le=1)


class ValidationCriteria(BaseModel):
    benchmark: str
    max_drawdown: float
    target_annual_return: float
    horizon_years: float


class ReportSettings(BaseModel):
    language: str = "ko"
    explanation_level: Literal["beginner", "intermediate", "expert"]


class IntentSpec(BaseModel):
    request_id: str
    stage: str = "02_intent"
    spec_version: str = "2.0"
    interpretation: Interpretation
    exclude_theme_rules: list[ExcludeThemeRule] = []
    screen: Screen
    risk_params: RiskParams
    news_tilt: NewsTilt
    validation_criteria: ValidationCriteria
    report_settings: ReportSettings
    questions: list[QuestionProposal] = []  # LLM 이 제안한 보충 질문. 코드가 걸러 1개만 묻는다 (M1-02)
    warnings: list[str] = []
