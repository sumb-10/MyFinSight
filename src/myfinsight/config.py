"""M00-01 설정 스키마 임시본 (모델만, 파일 읽기 함수는 없음).

주의: M00-01 담당은 역할 C. 역할 A 모듈(M02-*)이 AppConfig.data 기본값으로 개발·테스트하려고
명세서 스키마만 그대로 옮겨 둠. C 의 확정본이 나오면 이 파일은 그것으로 교체함.
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


class BacktestSettings(BaseModel):
    period_years: int = Field(5, ge=1, le=20)
    rebalance: Literal["Q"] = "Q"
    rebalance_anchor: Literal["first_trading_day"] = "first_trading_day"
    benchmark: str = "SPY"
    allowed_benchmarks: list[str] = ["SPY", "QQQ"]
    cost_bps: float = Field(10.0, ge=0, le=200)
    trading_days_per_year: int = 252


class RiskFreeSettings(BaseModel):
    provider: Literal["fixed"] = "fixed"
    annual_rate: float = Field(0.0, ge=0, le=0.2)


class DataSettings(BaseModel):
    """역할 A 모듈이 읽는 설정 (M02-01 재시도, M02-03 품질 기준, M02-04 DB 위치·캐시)."""

    db_url: str = "sqlite:///data/myfinsight.db"
    price_source: Literal["yfinance"] = "yfinance"
    fx_symbol: str = "KRW=X"
    coverage_threshold: float = Field(0.95, gt=0, le=1)
    max_fill_days: int = Field(1, ge=0, le=1)
    retry_max: int = Field(3, ge=0, le=10)
    retry_backoff_sec: float = 1.0
    cache_max_age_days: int = 1


class UniverseSettings(BaseModel):
    indices: list[Literal["SP500", "NDX"]] = ["SP500", "NDX"]
    max_size: int = Field(60, ge=5, le=200)
    industry_map_path: str = "config/industry_map.toml"


class AppConfig(BaseModel):
    model_config = ConfigDict(frozen=True)

    backtest: BacktestSettings = BacktestSettings()
    risk_free: RiskFreeSettings = RiskFreeSettings()
    data: DataSettings = DataSettings()
    universe: UniverseSettings = UniverseSettings()
    industry_map: dict[str, list[str]] = {}
