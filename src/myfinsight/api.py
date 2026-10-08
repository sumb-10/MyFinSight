"""서비스용 데이터 API (Lightsail 인스턴스에서 띄움). 프론트는 DB 대신 이 주소로 요청한다.

    uvicorn myfinsight.api:app --host 0.0.0.0 --port 8000

GET /health                                         DB 연결·출처별 최근 성공 시각
GET /assets?type=STOCK&index=SP500                  종목 목록 (type·index 는 선택)
GET /prices?tickers=AAPL,005930.KS&start=2025-01-01&end=2026-09-30
    저장된 수정종가. DB 에 없는 종목은 그 자리에서 yfinance 로 받아 저장하고, 정기 수집 대상
    (extra_ticker)에 올려 다음 GitHub Actions 실행부터 모든 출처로 10년치를 채운다.
    새 종목은 Yahoo 종목 종류로 assets.asset_type (STOCK·ETF·INDEX) 과 이름을 채운다.
GET /fx?start=2026-01-01&end=2026-09-30             USD/KRW 환율
GET /financials/{ticker}?as_of=2026-09-30           as_of 까지 공시된 재무 지표 최신 값
GET /news/{ticker}?days=30                          최근 기사

.env:
    API_TOKEN            값이 있으면 모든 요청에 Authorization: Bearer <값> 필요 (없으면 공개)
    CORS_ORIGINS         프론트 주소 (쉼표로 여러 개). 기본 * (모두 허용)
    ON_DEMAND_DAILY_LIMIT  하루에 새로 받는 종목 수 상한. 기본 10
"""

from __future__ import annotations

import math
from collections import defaultdict
from collections.abc import Callable
from datetime import UTC, date, datetime, timedelta
from functools import lru_cache
from typing import Any

from fastapi import Depends, FastAPI, HTTPException, Query, Request
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy import select

from myfinsight.data.crawlers import config
from myfinsight.data.normalizer import asset_id_for, currency_of_symbol, normalize_ticker
from myfinsight.data.price_loader import load_prices
from myfinsight.data.repository import open_repository
from myfinsight.data.repository import tables as T
from myfinsight.data.repository.sql import SqlRepository
from myfinsight.schemas.errors import DataSourceError, RepositoryError
from myfinsight.schemas.market import IndexCode

MAX_TICKERS = 50


@lru_cache(maxsize=1)
def _default_repo() -> SqlRepository:
    return open_repository()


def _default_adapter() -> Any:
    from myfinsight.data.adapters.factory import price_adapter

    return price_adapter()


def _default_kind(symbol: str) -> tuple[str | None, str | None]:
    from myfinsight.data.asset_kind import classify

    return classify(symbol)


def _num(v: float | None) -> float | None:
    return None if v is None or (isinstance(v, float) and math.isnan(v)) else v


def create_app(
    repo: Callable[[], SqlRepository] = _default_repo,
    adapter: Callable[[], Any] = _default_adapter,
    *,
    token: str | None = None,
    daily_limit: int | None = None,
    cors_origins: list[str] | None = None,
    clock: Callable[[], datetime] = lambda: datetime.now(UTC),
    kind: Callable[[str], tuple[str | None, str | None]] = _default_kind,
) -> FastAPI:
    """앱을 만든다. 테스트는 repo·adapter 를 바꿔 끼운다. 나머지는 None 이면 .env 값."""
    token = config.get("API_TOKEN") if token is None else token
    if daily_limit is None:
        daily_limit = int(config.get("ON_DEMAND_DAILY_LIMIT") or 10)
    if cors_origins is None:
        cors_origins = [x.strip() for x in (config.get("CORS_ORIGINS") or "*").split(",")]

    def auth(request: Request) -> None:
        if token and request.headers.get("Authorization", "") != f"Bearer {token}":
            raise HTTPException(401, "unauthorized")

    app = FastAPI(title="MyFinSight 데이터 API", dependencies=[Depends(auth)])
    app.add_middleware(
        CORSMiddleware, allow_origins=cors_origins, allow_methods=["GET"], allow_headers=["*"]
    )

    @app.exception_handler(RepositoryError)
    async def _repo_error(request: Request, exc: RepositoryError) -> Any:
        from fastapi.responses import JSONResponse

        return JSONResponse({"detail": str(exc)}, status_code=503)

    @app.get("/health")
    def health() -> dict[str, Any]:
        return {"ok": True, "sources": repo().source_status()}

    @app.get("/assets")
    def assets(type: str | None = None, index: str | None = None) -> list[dict[str, Any]]:
        rows = repo().get_assets()
        if type:
            rows = [a for a in rows if a.asset_type == type.upper()]
        if index:
            try:
                code = IndexCode(index.upper())
            except ValueError as exc:
                raise HTTPException(400, f"모르는 지수: {index}") from exc
            members = {normalize_ticker(r.ticker) for r in repo().latest_constituents(code)}
            rows = [a for a in rows if a.yfinance_symbol in members]
        keep = ("asset_id", "yfinance_symbol", "name", "market", "asset_type", "currency")
        return [{k: getattr(a, k) for k in keep} for a in rows]

    def _mark_kinds(r: SqlRepository, symbols: list[str]) -> None:
        """새 종목의 종류(STOCK·ETF·INDEX)와 이름을 assets 에 채움. 모르면 기본값 그대로."""
        fixed = []
        for a in r.get_assets(symbols):
            asset_type, name = kind(a.yfinance_symbol)
            update: dict[str, Any] = {}
            if asset_type and asset_type != a.asset_type:
                update["asset_type"] = asset_type
            if name and not a.name:
                update["name"] = name
            if update:
                fixed.append(a.model_copy(update=update))
        if fixed:
            r.upsert_assets(fixed)

    @app.get("/prices")
    def prices(tickers: str, start: date, end: date) -> dict[str, Any]:
        wanted = sorted({normalize_ticker(t) for t in tickers.split(",") if t.strip()})
        if not wanted:
            raise HTTPException(400, "tickers 가 비어 있음")
        if len(wanted) > MAX_TICKERS:
            raise HTTPException(400, f"한 번에 {MAX_TICKERS}개까지")
        if start > end:
            raise HTTPException(400, "start 가 end 보다 늦음")
        r = repo()
        stored = r.covered_ranges(wanted)
        new = [t for t in wanted if t not in stored]
        if new:
            today_start = clock().replace(hour=0, minute=0, second=0, microsecond=0)
            left = daily_limit - len(r.extra_tickers(since=today_start))
            if len(new) > left:
                raise HTTPException(
                    429, f"오늘 새로 받을 수 있는 종목이 {max(left, 0)}개 남음 (요청 {len(new)}개)"
                )
        groups: dict[str, list[str]] = defaultdict(list)  # PriceFrame 은 통화 하나씩
        for t in wanted:
            groups[currency_of_symbol(t)].append(t)
        out: list[dict[str, Any]] = []
        failed: dict[str, str] = {}
        source = adapter() if new else None
        for group in groups.values():
            if source is None:
                frame, _ = r.get_prices(group, start, end)
            else:
                try:
                    frame, _, summary = load_prices(
                        group, start, end, adapter=source, repository=r, fx_symbol=None
                    )
                except DataSourceError as exc:
                    raise HTTPException(502, f"수집 실패: {exc}") from exc
                failed.update(summary.failed)
            for t in frame.columns:
                for d, v in frame[t].items():
                    if _num(v) is not None:
                        out.append({"ticker": t, "date": d.date().isoformat(), "adj_close": v})
        got = {row["ticker"] for row in out}
        added = [t for t in new if t in got and t not in failed]
        if added:
            r.add_extra_tickers(added)
            _mark_kinds(r, added)
        return {
            "prices": out,
            "new_tickers": added,
            "failed": {**failed, **{t: "데이터 없음" for t in wanted if t not in got}},
        }

    @app.get("/fx")
    def fx(start: date, end: date) -> list[dict[str, Any]]:
        f = T.fx_daily
        q = (
            select(f.c.date, f.c.rate, f.c.source)
            .where(f.c.date >= start, f.c.date <= end)
            .order_by(f.c.date, f.c.source)
        )
        with repo().engine.connect() as c:
            rows = c.execute(q).all()
        return [{"date": d.isoformat(), "rate": rate, "source": s} for d, rate, s in rows]

    @app.get("/financials/{ticker}")
    def financials(ticker: str, as_of: date | None = None) -> list[dict[str, Any]]:
        rows = repo().get_financials_as_of(
            asset_id_for(normalize_ticker(ticker)), as_of or clock().date()
        )
        return [row.model_dump(mode="json") for row in rows]

    @app.get("/news/{ticker}")
    def news(ticker: str, days: int = Query(30, ge=1, le=365)) -> list[dict[str, Any]]:
        now = clock()
        rows = repo().get_news(
            asset_id_for(normalize_ticker(ticker)), now - timedelta(days=days), now
        )
        keep = ("source", "title", "url", "publisher", "published_at")
        return [
            {k: v for k, v in row.model_dump(mode="json").items() if k in keep}
            for row in sorted(rows, key=lambda n: n.published_at, reverse=True)
        ]

    return app


app = create_app()
