"""역할 A 확장 스키마 (프로토타입 M00-02 밖).

재무(DART·SEC EDGAR)와 뉴스(네이버·NewsAPI·Google RSS) 수집 원본을 담는다. 프로토타입 명세에는
없는 부분이라 역할 D(스키마 관리)와 합의한 뒤 M00-02 에 옮긴다. 모양은 RawPriceBatch 와 같게
맞췄고, 키가 티커가 아닐 수 있어(공시 고유번호·CIK·검색어) 이름만 requested_keys 로 했다.
"""

from __future__ import annotations

from datetime import date, datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict


class RawFinancialBatch(BaseModel):
    """재무 어댑터 출력 (원본 보존). 키 = DART 고유번호 또는 SEC CIK."""

    model_config = ConfigDict(extra="forbid")

    source: str
    requested_keys: list[str]
    start: date  # 공시일(disclosed_at) 기준 조회 범위
    end: date
    fetched_at: datetime
    payload: dict[str, Any]
    failed_keys: dict[str, str] = {}


class RawNewsBatch(BaseModel):
    """뉴스 어댑터 출력 (원본 보존). 키 = 검색어."""

    model_config = ConfigDict(extra="forbid")

    source: str
    requested_keys: list[str]
    start: date  # 발행일(published_at, UTC) 기준 조회 범위
    end: date
    fetched_at: datetime
    payload: dict[str, Any]
    failed_keys: dict[str, str] = {}


class AssetInfo(BaseModel):
    """종목 마스터 한 행 (DB assets 테이블). 출처마다 다른 종목 코드를 한곳에 모은다."""

    model_config = ConfigDict(extra="forbid")

    asset_id: str  # KR-005930, US-AAPL, US-BRK-B
    ticker: str  # 거래소 코드·티커 (005930, AAPL)
    name: str | None = None
    market: str  # KOSPI / KOSDAQ / US
    asset_type: Literal["STOCK", "ETF", "INDEX"] = "STOCK"
    currency: Literal["USD", "KRW"]
    yfinance_symbol: str  # PriceFrame 열 이름 (005930.KS, BRK-B)
    dart_corp_code: str | None = None
    sec_cik: str | None = None
    kis_ticker: str | None = None
    tiingo_symbol: str | None = None
    alpaca_symbol: str | None = None


class FinancialRow(BaseModel):
    """재무 지표 한 행 (DB financials). 지표 1개 = 1행."""

    model_config = ConfigDict(extra="forbid")

    asset_id: str
    source: str  # DART / SEC_EDGAR
    period: str  # 2025_11011, FY2025
    fs_div: str = "-"  # CFS 연결 / OFS 별도 / -
    metric: str  # 매출액, 영업이익 …
    value: float
    unit: str | None = None
    fiscal_year: int | None = None
    report_code: str | None = None
    period_end: date | None = None
    disclosed_at: date  # 공시일. 이 날 이후에만 백테스트에 쓴다 (선견 금지)
    rcept_no: str | None = None
    fetched_at: datetime


class NewsRow(BaseModel):
    """뉴스 한 건 (DB news). 같은 (종목, url) 은 한 번만 저장."""

    model_config = ConfigDict(extra="forbid")

    asset_id: str
    source: str  # NAVER_NEWS / NEWSAPI / GOOGLE_RSS
    url: str
    title: str
    content: str | None = None
    publisher: str | None = None
    published_at: datetime
    language: str | None = None
    query: str | None = None
    fetched_at: datetime
