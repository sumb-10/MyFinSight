"""0-4 PriceFrame 계약 검사 함수 (M02-02 평가 기준, 다른 역할 테스트에서도 사용)."""

from __future__ import annotations

import pandas as pd


def price_frame_problems(frame: pd.DataFrame, *, allow_nan: bool = True) -> list[str]:
    """PriceFrame 계약 위반 항목을 모두 모아 돌려준다. 빈 목록이면 통과.

    allow_nan=False 는 M02-03 통과 후 (결측 없음) 계약을 검사할 때 쓴다.
    """
    problems: list[str] = []
    idx = frame.index
    if not isinstance(idx, pd.DatetimeIndex):
        problems.append("index 가 DatetimeIndex 가 아님")
    else:
        if idx.tz is not None:
            problems.append("index 에 timezone 이 있음")
        if not idx.is_monotonic_increasing:
            problems.append("index 가 오름차순이 아님")
        if idx.has_duplicates:
            problems.append("index 에 중복 날짜가 있음")
        if len(idx) and not (idx == idx.normalize()).all():
            problems.append("index 에 시각 성분이 있음 (자정이 아님)")
    if idx.name != "date":
        problems.append(f"index 이름이 'date' 가 아님: {idx.name!r}")
    cols = list(frame.columns)
    if not all(isinstance(c, str) for c in cols):
        problems.append("열 이름이 모두 문자열(티커)이 아님")
    elif cols != sorted(cols):
        problems.append("열(티커)이 정렬되어 있지 않음")
    if len(set(cols)) != len(cols):
        problems.append("중복 티커 열이 있음")
    bad_dtypes = [c for c in cols if frame[c].dtype != "float64"]
    if bad_dtypes:
        problems.append(f"float64 가 아닌 열: {bad_dtypes}")
    values = frame.to_numpy(dtype="float64", na_value=float("nan")) if not bad_dtypes else None
    if values is not None:
        if not allow_nan and pd.isna(values).any():
            problems.append("결측(NaN)이 있음")
        finite = values[~pd.isna(values)]
        if (finite <= 0).any():
            problems.append("0 이하 가격이 있음")
    return problems
