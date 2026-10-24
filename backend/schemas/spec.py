"""M00-02 Strategy Spec 스키마 (FR08, 명세서 그대로 옮긴 임시본)."""

from __future__ import annotations

import hashlib
import json
from enum import Enum
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field


class SelectionRule(str, Enum):
    FIXED_LIST = "fixed_list"
    LOW_VOL_TOP_N = "low_volatility_top_n"
    MOMENTUM_TOP_N = "momentum_top_n"


class WeightingRule(str, Enum):
    EQUAL = "equal"
    INVERSE_VOL = "inverse_volatility"


class SelectionSpec(BaseModel):
    model_config = ConfigDict(extra="forbid")

    rule: SelectionRule
    params: dict[str, Any] = {}


class WeightingSpec(BaseModel):
    model_config = ConfigDict(extra="forbid")

    rule: WeightingRule
    params: dict[str, Any] = {}


class ConstraintSpec(BaseModel):
    model_config = ConfigDict(extra="forbid")

    exclude_tickers: list[str] = []
    max_weight_all: float = Field(1.0, gt=0, le=1.0)
    max_weight_per_ticker: dict[str, float] = {}


class UniverseSpec(BaseModel):
    model_config = ConfigDict(extra="forbid")

    mode: Literal["dynamic", "fixed"] = "dynamic"
    tickers: list[str] = []


class StrategySpec(BaseModel):
    model_config = ConfigDict(extra="forbid")

    spec_id: str
    name: str
    version: int = 1
    universe: UniverseSpec
    selection: SelectionSpec
    weighting: WeightingSpec
    constraints: ConstraintSpec
    rebalance: Literal["Q"] = "Q"
    period_years: int = Field(ge=1, le=20)
    benchmark: str

    def spec_hash(self) -> str:
        """정렬된 JSON 의 SHA-256 (FR10 일치 확인용)."""
        text = json.dumps(
            self.model_dump(mode="json"), sort_keys=True, ensure_ascii=False, separators=(",", ":")
        )
        return hashlib.sha256(text.encode("utf-8")).hexdigest()
