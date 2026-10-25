"""후보 검색·분류·정량 선정 (M3-02~04)."""

from __future__ import annotations

from datetime import date

from pydantic import BaseModel, Field


class GicsLevel(BaseModel):
    code: str
    name: str


class Gics(BaseModel):
    sector: GicsLevel
    industry_group: GicsLevel
    industry: GicsLevel
    sub_industry: GicsLevel


class Candidate(BaseModel):
    ticker: str
    asset_id: str | None = None
    name: str
    market: str = "US"
    currency: str = "USD"
    gics: Gics
    company_summary: str
    market_cap_usd: float | None = None
    adv_usd: float | None = None
    matched_by: list[str]
    matched_themes: list[str]
    matched_keywords: list[str] = []
    forced: bool = False


class FilteredOut(BaseModel):
    ticker: str
    reason: str


class Candidates(BaseModel):
    request_id: str
    stage: str = "03_candidates"
    as_of: date
    descriptor_version: str | None = None
    candidates: list[Candidate]
    filtered_out: list[FilteredOut] = []
    stats: dict
    warnings: list[str] = []


class TagResult(BaseModel):
    ticker: str
    in_theme: bool
    themes: list[str] = []
    confidence: float = Field(ge=0, le=1)
    reason_ko: str
    excluded_theme: str | None = None


class Tagging(BaseModel):
    request_id: str
    stage: str = "04_tagging"
    min_confidence: float
    tagged: list[TagResult]
    excluded_by_theme: list[TagResult] = []
    passed_tickers: list[str]
    batches: int
    warnings: list[str] = []


class Selected(BaseModel):
    ticker: str
    name: str
    sector: str
    sector_code: str
    market: str = "US"
    rank: int
    metric_name: str
    metric_value: float
    metric_fact_id: str | None = None  # 인용 ID (fin:<asset_id>:<metric>:<date>)
    theme_confidence: float | None = None
    forced: bool = False


class Rejected(BaseModel):
    ticker: str
    reason: str
    metric_value: float | None = None


class Selection(BaseModel):
    request_id: str
    stage: str = "05_selection"
    as_of: date
    selected: list[Selected]
    rejected: list[Rejected] = []
    summary: dict
    infeasibility: dict | None = None  # 섹터 상한 x 종목 수로 전액 배분이 불가능할 때 사유와 선택지
    warnings: list[str] = []
