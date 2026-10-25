"""품질 판정 (M2-02). backend.pipeline.quality.assess_quality 를 그대로 쓴다.

규칙: 커버리지 = 값 있는 거래일 / 기대 거래일, 0.95 이상 통과(0.95 정확히 = 통과). 1거래일 결측만 직전값 채움(FILLED),
2일 이상 연속 결측·커버리지 미달은 EXCLUDED. 필수 종목이 제외되면 DataMissing(DATA_REQUIRED_MISSING) 으로 바꿔 올린다.
"""

from __future__ import annotations

from collections.abc import Iterable
from datetime import date

import pandas as pd

from backend.analysis.errors import DataMissing
from backend.analysis.settings import MarketSettings
from backend.pipeline.quality import assess_quality
from backend.schemas.errors import DataQualityError
from backend.schemas.market import DataQualityReport


def assess(
    prices: pd.DataFrame,
    required: Iterable[str],
    expected_calendar: Iterable[date] | pd.DatetimeIndex,
    settings: MarketSettings,
) -> tuple[DataQualityReport, pd.DataFrame]:
    try:
        return assess_quality(prices, required, expected_calendar, settings)
    except DataQualityError as e:
        raise DataMissing(str(e), details=getattr(e, "details", None)) from e


def report_summary(report: DataQualityReport) -> dict:
    """리포트 §6(전제와 한계)·결과 번들에 넣는 요약."""
    return {
        "as_of": str(report.as_of),
        "expected_days": report.expected_days,
        "usable": len(report.usable_tickers),
        "excluded": dict(report.excluded),
        "filled": {q.ticker: q.filled_days for q in report.items if q.filled_days},
        "coverage": {q.ticker: round(q.coverage, 4) for q in report.items},
        "warnings": list(report.warnings),
    }
