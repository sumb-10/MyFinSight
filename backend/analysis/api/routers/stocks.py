"""/stocks: 회사 이름·티커로 종목 찾기, 티커 → 회사 이름. 프런트 제안 계약 searchStocks·getStocks 와 같은 모양 (m2_data/stocks.py)."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Query, Request

from backend.analysis.api.routers import services
from backend.analysis.m2_data.stocks import LOOKUP_MAX, SEARCH_LIMIT_MAX, lookup, search

router = APIRouter(tags=["stocks"])


@router.get("/stocks/search")
def search_stocks(request: Request, q: str = "", limit: int = Query(default=8, ge=1, le=SEARCH_LIMIT_MAX)) -> list[dict[str, Any]]:
    """q = 회사 이름(한국 종목 한국어, 미국 종목 영어)이나 티커. 비었으면 빈 목록."""
    return search(services(request).stocks(), q, limit)


@router.get("/stocks")
def get_stocks(request: Request, tickers: str = "") -> list[dict[str, Any]]:
    """tickers = 쉼표로 구분한 티커 (최대 100개). 목록에 없는 티커는 빠진다."""
    return lookup(services(request).stocks(), tickers.split(",")[:LOOKUP_MAX])
