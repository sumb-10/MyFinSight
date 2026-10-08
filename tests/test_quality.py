"""M02-03 품질 판정기: 경계값, 연속 결측, 필수 종목 예외, 결측 없는 출력."""

from __future__ import annotations

from datetime import date

import numpy as np
import pandas as pd
import pytest
from helpers import StubPriceAdapter

from myfinsight.config import DataSettings
from myfinsight.data.contracts import price_frame_problems
from myfinsight.data.normalizer import normalize_to_frame
from myfinsight.data.quality import assess_quality, benchmark_calendar
from myfinsight.schemas.errors import DataQualityError
from myfinsight.schemas.market import DataStatus

S = DataSettings()  # coverage_threshold 0.95, max_fill_days 1


def _frame(n: int, **missing: list[int]) -> tuple[pd.DataFrame, list[date]]:
    """SPY 와 지정 티커들, n 거래일. missing = 티커 → 결측 위치 목록."""
    idx = pd.bdate_range("2000-01-03", periods=n, name="date")
    data = {"SPY": np.linspace(100, 200, n)}
    for t, pos in missing.items():
        col = np.linspace(10, 20, n)
        col[pos] = np.nan
        data[t] = col
    frame = pd.DataFrame(data, index=idx)
    return frame, [ts.date() for ts in idx]


def _item(report, ticker):  # noqa: ANN001, ANN202
    return next(q for q in report.items if q.ticker == ticker)


def test_coverage_boundary_095_passes_09499_excluded() -> None:
    n = 10_000
    every_10 = list(range(5, n, 10))  # 서로 떨어진 결측 (연속 아님)
    frame, cal = _frame(n, PASS=every_10[:500], FAIL=every_10[:501])
    report, clean = assess_quality(frame, ["SPY"], cal, S)
    ok, bad = _item(report, "PASS"), _item(report, "FAIL")
    assert ok.coverage == 0.95 and ok.status == DataStatus.FILLED and ok.filled_days == 500
    assert bad.coverage == pytest.approx(0.9499) and bad.status == DataStatus.EXCLUDED
    assert "커버리지" in (bad.reason or "")
    assert report.usable_tickers == ["PASS", "SPY"]
    assert list(clean.columns) == ["PASS", "SPY"]


def test_single_gap_filled_with_previous_value() -> None:
    frame, cal = _frame(100, AMD=[50])
    report, clean = assess_quality(frame, ["SPY"], cal, S)
    assert _item(report, "AMD").status == DataStatus.FILLED
    assert clean["AMD"].iloc[50] == frame["AMD"].iloc[49]
    assert _item(report, "SPY").status == DataStatus.OK


def test_two_day_gap_excluded() -> None:
    frame, cal = _frame(100, AMD=[50, 51])
    report, clean = assess_quality(frame, ["SPY"], cal, S)
    item = _item(report, "AMD")
    assert item.status == DataStatus.EXCLUDED
    assert "연속 결측 2거래일" in (item.reason or "")
    assert "AMD" in report.excluded and "AMD" not in clean.columns


def test_leading_gap_excluded() -> None:
    frame, cal = _frame(100, NEW=[0])
    report, _ = assess_quality(frame, ["SPY"], cal, S)
    assert _item(report, "NEW").status == DataStatus.EXCLUDED
    assert "직전값 없음" in (_item(report, "NEW").reason or "")


def test_max_fill_days_zero_excludes_any_gap() -> None:
    frame, cal = _frame(100, AMD=[50])
    report, _ = assess_quality(frame, ["SPY"], cal, DataSettings(max_fill_days=0))
    assert _item(report, "AMD").status == DataStatus.EXCLUDED


def test_required_missing_raises_with_report() -> None:
    frame, cal = _frame(100, NVDA=[10, 11])
    with pytest.raises(DataQualityError) as e:
        assess_quality(frame, ["SPY", "NVDA"], cal, S)
    assert e.value.code == "DATA_REQUIRED_MISSING"
    assert e.value.details["tickers"] == ["NVDA"]
    assert e.value.details["report"]["excluded"]["NVDA"]


def test_benchmark_missing_raises() -> None:
    ad = StubPriceAdapter(missing={"SPY": [date(2026, 9, d) for d in (14, 15, 16)]})
    frame, _, _ = normalize_to_frame(ad.fetch(["SPY", "MSFT"], date(2026, 7, 1), date(2026, 9, 30)))
    calendar = benchmark_calendar(frame, "MSFT")  # SPY 결측일도 포함된 거래일
    with pytest.raises(DataQualityError) as e:
        assess_quality(frame, ["SPY"], calendar, S)
    assert e.value.code == "DATA_REQUIRED_MISSING"


def test_required_ticker_absent_from_frame() -> None:
    frame, cal = _frame(30)
    with pytest.raises(DataQualityError) as e:
        assess_quality(frame, ["SPY", "QQQ"], cal, S)
    assert e.value.code == "DATA_REQUIRED_MISSING"
    assert "가격 데이터 없음" in e.value.details["reasons"]["QQQ"]


def test_no_usable_ticker() -> None:
    frame, cal = _frame(30, A=[3, 4])
    frame = frame[["A"]]
    with pytest.raises(DataQualityError) as e:
        assess_quality(frame, [], cal, S)
    assert e.value.code == "DATA_NO_USABLE_TICKER"


def test_output_has_no_nan_and_meets_contract() -> None:
    ad = StubPriceAdapter(
        missing={"AMD": [date(2026, 9, 15)], "KO": [date(2026, 9, 1), date(2026, 9, 2)]}
    )
    frame, _, _ = normalize_to_frame(
        ad.fetch(["SPY", "AMD", "KO", "NVDA"], date(2026, 7, 1), date(2026, 9, 30))
    )
    report, clean = assess_quality(frame, ["SPY"], benchmark_calendar(frame, "SPY"), S)
    assert price_frame_problems(clean, allow_nan=False) == []
    assert report.excluded.keys() == {"KO"}
    assert report.as_of == date(2026, 9, 30)
    assert report.expected_days == len(clean)


def test_extra_dates_outside_calendar_dropped() -> None:
    frame, cal = _frame(30)
    report, clean = assess_quality(frame, ["SPY"], cal[:20], S)
    assert len(clean) == 20 and report.expected_days == 20


def test_mismatch_is_warning_only() -> None:
    frame, cal = _frame(100, AMD=[], BAD=[50, 51])
    report, clean = assess_quality(frame, ["SPY"], cal, S, mismatch_days={"AMD": 3, "BAD": 2})
    amd = _item(report, "AMD")
    assert amd.status == DataStatus.OK and amd.mismatch_days == 3  # 판정은 그대로
    assert "AMD" in clean.columns
    assert report.warnings == [
        "AMD: 출처 간 가격 불일치 3거래일 (출처별 중앙값으로 보정한 값 사용)"
    ]
    assert _item(report, "BAD").mismatch_days == 2  # 제외된 종목은 경고에 안 넣음
    plain, _ = assess_quality(frame, ["SPY"], cal, S)
    assert plain.warnings == [] and _item(plain, "AMD").mismatch_days == 0
