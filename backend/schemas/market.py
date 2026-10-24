"""M00-02 시장 데이터 스키마 (명세서를 옮긴 임시본).

명세 대비 바꾼 점 (한국 종목 지원, DB_설계.md 3절):
- IndexCode 에 KOSPI200 추가
- PriceBar.currency 에 "KRW" 허용 (명세는 "USD" 만)
- PriceMeta.currency 추가 (기본 "USD"). 한 PriceFrame 에는 한 통화만 담는다
- PriceBar 에 open·high·low·close 추가 (선택, 출처 간 종가 교차검증용)
- TickerQuality.mismatch_days, DataQualityReport.warnings 추가 (교차검증 결과를 경고로만 전달)
- IndexConstituent.gics_sub_industry_code 추가 (스냅샷 당시 GICS 세부산업 코드, Module2 §5)
"""

from __future__ import annotations

from datetime import date, datetime
from enum import Enum
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

Currency = Literal["USD", "KRW"]


class IndexCode(str, Enum):
    SP500 = "SP500"
    NDX = "NDX"
    KOSPI200 = "KOSPI200"  # 추가: 한국 종목


class DataStatus(str, Enum):
    OK = "OK"
    FILLED = "FILLED"
    EXCLUDED = "EXCLUDED"


class RawPriceBatch(BaseModel):
    """M02-01 출력 (원본 보존)."""

    model_config = ConfigDict(extra="forbid")

    source: str
    requested_tickers: list[str]
    start: date
    end: date
    fetched_at: datetime
    payload: dict[str, Any]  # 원본 응답(JSON 직렬화 가능 형태)
    failed_tickers: dict[str, str] = {}  # 티커 → 실패 사유


class PriceBar(BaseModel):
    """M02-02 출력 행."""

    model_config = ConfigDict(extra="forbid")

    ticker: str
    date: date
    adj_close: float = Field(gt=0)
    volume: int | None = Field(None, ge=0)
    currency: Currency = "USD"
    source: str
    fetched_at: datetime
    # 추가 (선택): 시가·고가·저가·종가. 종가는 분할만 보정한 값 (배당 미반영)
    open: float | None = Field(None, gt=0)
    high: float | None = Field(None, gt=0)
    low: float | None = Field(None, gt=0)
    close: float | None = Field(None, gt=0)


class FxRate(BaseModel):
    """환율 (USD/KRW). M02-02 가 fx_symbol 데이터를 변환."""

    model_config = ConfigDict(extra="forbid")

    pair: Literal["USDKRW"] = "USDKRW"
    date: date
    rate: float = Field(gt=0)
    source: str
    fetched_at: datetime


class PriceMeta(BaseModel):
    """PriceFrame과 함께 전달하는 메타."""

    model_config = ConfigDict(extra="forbid")

    source: str
    as_of: date
    fetched_at: datetime
    tickers: list[str]
    currency: Currency = "USD"  # 추가: 값의 통화 (한국 PriceFrame 은 "KRW")


class TickerQuality(BaseModel):
    """M02-03 티커별 판정."""

    model_config = ConfigDict(extra="forbid")

    ticker: str
    coverage: float
    filled_days: int
    status: DataStatus
    reason: str | None = None
    is_required: bool  # Benchmark 또는 고정 목록(사용자 지목)
    mismatch_days: int = 0  # 추가: 출처 간 교차검증 MISMATCH 거래일 수 (경고만, 제외 안 함)


class DataQualityReport(BaseModel):
    """M02-03 출력."""

    model_config = ConfigDict(extra="forbid")

    as_of: date
    expected_days: int
    items: list[TickerQuality]
    usable_tickers: list[str]
    excluded: dict[str, str]  # 티커 → 사유
    warnings: list[str] = []  # 추가: Report 한계에 넣을 문장 (출처 간 가격 불일치 등)


class IndexConstituent(BaseModel):
    """M02-05 출력 행."""

    model_config = ConfigDict(extra="forbid")

    index_code: IndexCode
    ticker: str
    name: str
    sector: str
    industry: str
    snapshot_date: date
    source: str
    fetched_at: datetime
    # 추가 (v4): industry 를 GICS 분류표로 정규화한 세부산업 코드 (못 찾으면 None, 경고로 알림)
    gics_sub_industry_code: str | None = None


class UniverseResult(BaseModel):
    """M03-05 출력."""

    model_config = ConfigDict(extra="forbid")

    tickers: list[str]
    snapshot_dates: dict[IndexCode, date]
    criteria: dict[str, Any]
    excluded: dict[str, str]
    source: str
