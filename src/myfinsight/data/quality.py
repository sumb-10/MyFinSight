"""M02-03 데이터 품질 판정기 (FR05, 부록 A-3).

    from myfinsight.data.quality import assess_quality, benchmark_calendar
    calendar = benchmark_calendar(prices, "SPY")
    report, clean = assess_quality(prices, ["SPY"], calendar, config.data)

판정 규칙 (기준값은 설정에서만 읽는다: coverage_threshold, max_fill_days)
1. 기대 거래일 = expected_calendar (Benchmark 거래일). 그 밖의 날짜 행은 버린다.
2. 커버리지 = 값이 있는 거래일 수 / 기대 거래일 수 (채우기 전 원래 값 기준)
3. 연속 결측이 max_fill_days 일 이하면 직전값으로 채움 → FILLED (채운 일수 기록)
4. EXCLUDED: 커버리지 < coverage_threshold, 연속 결측이 max_fill_days 초과(기본: 2일 이상),
   또는 첫 거래일부터 결측이라 채울 직전값이 없음. 사유를 모두 적는다.
5. 필수 종목이 EXCLUDED 면 DataQualityError(DATA_REQUIRED_MISSING),
   사용 가능 종목이 0개면 DataQualityError(DATA_NO_USABLE_TICKER).
   예외 details["report"] 에 판정 결과(JSON) 를 담아 실행 기록에 남길 수 있게 한다.

6. (추가) mismatch_days 를 주면 출처 간 교차검증 MISMATCH 날 수를 종목별로 적고,
   사용 가능 종목이면 report.warnings 에 Report 한계 문장을 남긴다. 판정(OK·FILLED·EXCLUDED)은
   바꾸지 않는다. 값은 이미 CONSENSUS 로 보정돼 있음 (verify.py).

값을 새로 만들지 않는다 (C-07): 채우기는 직전 거래일 값 복사만 한다.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from datetime import date
from typing import Protocol

import numpy as np
import pandas as pd

from myfinsight.schemas.errors import DataQualityError
from myfinsight.schemas.market import DataQualityReport, DataStatus, TickerQuality


class QualitySettings(Protocol):
    """판정 기준 (AppConfig.data 가 이 모양을 만족한다)."""

    coverage_threshold: float
    max_fill_days: int


def benchmark_calendar(prices: pd.DataFrame, benchmark: str) -> list[date]:
    """Benchmark 열에 값이 있는 날짜 = 기대 거래일 목록."""
    if benchmark not in prices.columns:
        raise DataQualityError(
            f"Benchmark {benchmark} 가격이 없음",
            code="DATA_REQUIRED_MISSING",
            details={"ticker": benchmark},
        )
    col = prices[benchmark]
    return [ts.date() for ts in col.index[col.notna()]]


def _missing_runs(isna: np.ndarray) -> list[tuple[int, int]]:
    """결측 구간 (시작 위치, 길이) 목록."""
    runs: list[tuple[int, int]] = []
    start = None
    for i, miss in enumerate(isna):
        if miss and start is None:
            start = i
        elif not miss and start is not None:
            runs.append((start, i - start))
            start = None
    if start is not None:
        runs.append((start, len(isna) - start))
    return runs


def _judge(
    ticker: str,
    values: np.ndarray,
    days: list[date],
    *,
    threshold: float,
    max_fill: int,
    required: bool,
) -> TickerQuality:
    n = len(days)
    isna = np.isnan(values)
    valid = int(n - isna.sum())
    coverage = valid / n
    reasons: list[str] = []
    if valid == 0:
        reasons.append("가격 데이터 없음")
    else:
        if coverage < threshold:
            reasons.append(f"커버리지 {coverage:.4f} < 기준 {threshold}")
        runs = _missing_runs(isna)
        if runs and runs[0][0] == 0:
            reasons.append(f"첫 거래일 {days[0]} 부터 {runs[0][1]}일 결측 (채울 직전값 없음)")
            runs = runs[1:]
        long_runs = [(s, ln) for s, ln in runs if ln > max_fill]
        if long_runs:
            s, ln = max(long_runs, key=lambda r: (r[1], -r[0]))
            reasons.append(
                f"연속 결측 {ln}거래일 ({days[s]}~{days[s + ln - 1]}), 허용 {max_fill}일"
            )
    missing = n - valid
    if reasons:
        return TickerQuality(
            ticker=ticker,
            coverage=coverage,
            filled_days=0,
            status=DataStatus.EXCLUDED,
            reason="; ".join(reasons),
            is_required=required,
        )
    return TickerQuality(
        ticker=ticker,
        coverage=coverage,
        filled_days=missing,
        status=DataStatus.FILLED if missing else DataStatus.OK,
        is_required=required,
    )


def assess_quality(
    prices: pd.DataFrame,
    required_tickers: Iterable[str],
    expected_calendar: Iterable[date] | pd.DatetimeIndex,
    settings: QualitySettings,
    *,
    mismatch_days: Mapping[str, int] | None = None,
) -> tuple[DataQualityReport, pd.DataFrame]:
    """티커별 품질을 판정하고 (DataQualityReport, 결측 없는 PriceFrame) 을 돌려준다.

    prices: PriceFrame (결측 허용). required_tickers: Benchmark + Spec 고정 목록 종목.
    expected_calendar: Benchmark 거래일 (기간 = Backtest 기간 + 최대 lookback 으로 잘라서 넘긴다).
    settings: AppConfig.data (coverage_threshold, max_fill_days).
    mismatch_days: 티커 → 기간 안 MISMATCH 거래일 수 (load_prices 의 summary.mismatch_days).
        경고만 남기고 판정에는 쓰지 않는다.
    결과 PriceFrame 은 사용 가능 종목만, 행 = expected_calendar, 결측 없음.
    """
    threshold = float(settings.coverage_threshold)
    max_fill = int(settings.max_fill_days)
    days = sorted({pd.Timestamp(d).date() for d in expected_calendar})
    if not days:
        raise DataQualityError("기대 거래일 목록이 비어 있음", code="DATA_INVALID_INPUT")
    required = sorted(set(required_tickers))
    index = pd.DatetimeIndex(pd.to_datetime(days), name="date")
    frame = prices.reindex(index=index).astype("float64")
    tickers = sorted(set(frame.columns) | set(required))
    frame = frame.reindex(columns=tickers)

    items = [
        _judge(
            t,
            frame[t].to_numpy(dtype="float64"),
            days,
            threshold=threshold,
            max_fill=max_fill,
            required=t in required,
        )
        for t in tickers
    ]
    mism = {t: int(n) for t, n in (mismatch_days or {}).items() if n}
    items = [q.model_copy(update={"mismatch_days": mism.get(q.ticker, 0)}) for q in items]
    usable = [q.ticker for q in items if q.status != DataStatus.EXCLUDED]
    excluded = {q.ticker: q.reason or "" for q in items if q.status == DataStatus.EXCLUDED}
    warnings = [
        f"{t}: 출처 간 가격 불일치 {mism[t]}거래일 (출처별 중앙값으로 보정한 값 사용)"
        for t in usable
        if t in mism
    ]
    report = DataQualityReport(
        as_of=days[-1],
        expected_days=len(days),
        items=items,
        usable_tickers=usable,
        excluded=excluded,
        warnings=warnings,
    )

    missing_required = [t for t in required if t in excluded]
    if missing_required:
        raise DataQualityError(
            f"필수 종목 데이터 부족: {', '.join(missing_required)}",
            code="DATA_REQUIRED_MISSING",
            details={
                "tickers": missing_required,
                "reasons": {t: excluded[t] for t in missing_required},
                "report": report.model_dump(mode="json"),
            },
        )
    if not usable:
        raise DataQualityError(
            "사용 가능한 종목이 없음",
            code="DATA_NO_USABLE_TICKER",
            details={"excluded": excluded, "report": report.model_dump(mode="json")},
        )

    clean = frame[usable].ffill(limit=max_fill) if max_fill > 0 else frame[usable].copy()
    clean.columns.name = None
    if clean.isna().to_numpy().any():  # 규칙상 일어나면 안 됨 (방어)
        raise DataQualityError("품질 판정 후에도 결측이 남음", code="DATA_INVALID_INPUT")
    return report, clean
