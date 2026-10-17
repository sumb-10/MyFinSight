"""M00-02 Profile 스키마 (UC001, 명세서 그대로 옮긴 임시본)."""

from __future__ import annotations

from enum import Enum
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


class RiskType(str, Enum):
    """금융권 5단계 (UC001)."""

    STABLE = "안정형"
    STABLE_SEEKING = "안정추구형"
    NEUTRAL = "위험중립형"
    ACTIVE = "적극투자형"
    AGGRESSIVE = "공격투자형"


class ProfileConstraints(BaseModel):
    model_config = ConfigDict(extra="forbid")

    exclude_tickers: list[str] = []
    max_weight_all: float = Field(1.0, ge=0.05, le=1.0)
    max_weight_per_ticker: dict[str, float] = {}  # 값 0~1
    allow_etf: bool = False


class UserProfile(BaseModel):
    model_config = ConfigDict(extra="forbid")

    profile_id: str
    investment_amount_krw: int = Field(gt=0)
    horizon_months: int = Field(ge=12, le=120)
    risk_type_computed: RiskType
    risk_type: RiskType  # 최종(사용자 변경 가능)
    risk_type_overridden: bool
    loss_tolerance_pct: float = Field(gt=0, le=100)  # 예: 30 → -30%까지 감내
    interest_industries: list[str] = []  # industry_map 키
    preferences: list[str] = []  # 성장/가치/배당/대형주
    memo: str | None = None
    constraints: ProfileConstraints = ProfileConstraints()
    market: Literal["US"] = "US"
