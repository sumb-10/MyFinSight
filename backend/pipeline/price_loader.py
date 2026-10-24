"""가격 불러오기 흐름 (명세 0-2 실행 흐름 3번의 A 부분): 캐시 확인 → 수집 → 정규화 → 저장 → 조회.

    from backend.pipeline.price_loader import load_prices
    prices, meta, summary = load_prices(
        ["SPY", "MSFT", "NVDA"], start, end, adapter=price_adapter(), repository=repo
    )
    report, clean = assess_quality(
        prices, ["SPY"], benchmark_calendar(prices, "SPY"), config.data,
        mismatch_days=summary.mismatch_days,   # 교차검증 불일치는 경고만 (report.warnings)
    )

M02-01·02·04 공개 함수만 이어 붙인 것이라 파이프라인(M08-02)이 그대로 쓰거나 같은 순서로 직접
불러도 된다. 품질 판정(M02-03)은 필수 종목·기간을 아는 쪽에서 따로 부른다.
"""

from __future__ import annotations

import logging
from datetime import UTC, date, datetime

import pandas as pd
from pydantic import BaseModel, ConfigDict

from backend.adapters.base import PriceSourceAdapter
from backend.pipeline.normalizer import normalize, normalize_ticker
from backend.db.base import MarketDataRepository
from backend.db.sql import previous_weekday
from backend.schemas.market import PriceMeta

logger = logging.getLogger(__name__)


class PriceLoadSummary(BaseModel):
    """load_prices 가 한 일 (실행 기록 요약·Report 한계에 쓸 수 있음)."""

    model_config = ConfigDict(extra="forbid")

    requested: list[str]
    cached: list[str]  # 저장소에 있어 받지 않은 티커
    fetched: list[str]  # 이번에 받은 티커 (환율 심볼 포함)
    failed: dict[str, str]  # 받지 못한 티커 → 사유
    stored_rows: int  # 새로 넣거나 바뀐 가격 행 수
    stored_fx_rows: int
    dropped_rows: int  # 정규화에서 버린 행 수
    dropped_by_reason: dict[str, int]
    mismatch_days: dict[str, int] = {}  # 추가: 교차검증 MISMATCH 거래일 수 (M02-03 경고용)


def load_prices(
    tickers: list[str],
    start: date,
    end: date,
    *,
    adapter: PriceSourceAdapter,
    repository: MarketDataRepository,
    fx_symbol: str | None = "KRW=X",
    today: date | None = None,
) -> tuple[pd.DataFrame, PriceMeta, PriceLoadSummary]:
    """저장소에 없거나 오래된 티커만 받아 저장한 뒤, 저장소에서 PriceFrame 을 읽어 돌려준다.

    fx_symbol 을 주면 저장된 환율이 오래됐을 때 같이 받는다 (None 이면 환율은 건드리지 않음).
    받지 못한 티커는 summary.failed 에 남고 PriceFrame 에는 NaN 열로 나온다 (판정은 M02-03).
    """
    today = today or datetime.now(UTC).date()
    wanted = sorted({normalize_ticker(t) for t in tickers})
    to_fetch = [t for t in wanted if repository.needs_fetch(t, start, end, today=today)]
    cached = [t for t in wanted if t not in to_fetch]
    if fx_symbol:
        fx = repository.get_fx_on_or_before(end)
        if fx is None or fx.date < min(end, previous_weekday(today)):
            to_fetch.append(fx_symbol)

    failed: dict[str, str] = {}
    stored = stored_fx = dropped = 0
    reasons: dict[str, int] = {}
    if to_fetch:
        batch = adapter.fetch(to_fetch, start, end)
        failed = dict(batch.failed_tickers)
        for t in batch.requested_tickers:
            repository.log_fetch(
                batch.source,
                t,
                start,
                end,
                "FAILED" if t in failed else "SUCCESS",
                batch.fetched_at,
                failed.get(t),
            )
        result = normalize(batch, fx_symbol=fx_symbol or "KRW=X")
        stored = repository.upsert_prices(result.bars)
        stored_fx = repository.upsert_fx(result.fx) if fx_symbol else 0
        dropped, reasons = result.dropped, result.dropped_by_reason
        if failed:
            logger.warning("가격 수집 실패 %d개: %s", len(failed), sorted(failed))

    frame, meta = repository.get_prices(wanted, start, end)
    # 교차검증 결과는 확장 저장소에만 있음 (명세 13개 메서드만 있는 저장소면 비움)
    count = getattr(repository, "mismatch_days", None)
    mismatch = count(wanted, start, end) if callable(count) else {}
    summary = PriceLoadSummary(
        requested=wanted,
        cached=cached,
        fetched=[t for t in to_fetch if t not in failed],
        failed=failed,
        stored_rows=stored,
        stored_fx_rows=stored_fx,
        dropped_rows=dropped,
        dropped_by_reason=reasons,
        mismatch_days=mismatch,
    )
    return frame, meta, summary
