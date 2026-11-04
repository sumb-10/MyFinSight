"""정량 선정 지표 (상세설계 표 6). 기준일 이전 자료만 쓴다 (view 가 보장).

가격 지표: return_12m_1m = P(t−21)/P(t−252) − 1, vol_60d = 60거래일 일수익률 표준편차 × √252 (수정종가, USD 환산).
재무 지표: pe_ttm, roe_ttm, dividend_yield_ttm = valuation_daily (그날까지 공시된 재무만으로 계산된 값).
각 함수는 (Series[ticker], facts) 를 돌려준다. fact.id 는 인용 ID `fin:<asset_id>:<metric>:<date>`.
"""

from __future__ import annotations

import datetime as dt
from collections.abc import Callable, Sequence
from dataclasses import asdict, dataclass

import numpy as np
import pandas as pd

from backend.analysis.m2_data.market_data import MarketDataView


@dataclass(frozen=True)
class Fact:
    id: str
    ticker: str
    asset_id: str
    metric: str
    value: float
    unit: str
    as_of: str
    source: str

    def to_dict(self) -> dict:
        return asdict(self)


def _fact(view: MarketDataView, ticker: str, metric: str, value: float, unit: str, as_of: dt.date, source: str) -> Fact:
    aid = view.md.asset_id(ticker)
    return Fact(id=f"fin:{aid}:{metric}:{as_of}", ticker=ticker, asset_id=aid, metric=metric, value=float(value), unit=unit,
                as_of=str(as_of), source=source)  # fmt: skip


def return_12m_1m(view: MarketDataView, tickers: Sequence[str]) -> tuple[pd.Series, list[Fact]]:
    px = view.adj_close(tickers, view.as_of - dt.timedelta(days=420), fill=False)
    out, facts = {}, []
    for t in tickers:
        a = px[t].dropna().to_numpy() if t in px else np.array([])
        if len(a) < 253:
            continue
        out[t] = a[-22] / a[-253] - 1
        facts.append(_fact(view, t, "return_12m_1m", out[t], "ratio", px[t].dropna().index[-1].date(), "price_daily"))
    return pd.Series(out, name="return_12m_1m", dtype=float), facts


def vol_60d(view: MarketDataView, tickers: Sequence[str]) -> tuple[pd.Series, list[Fact]]:
    px = view.adj_close(tickers, view.as_of - dt.timedelta(days=120), fill=False)
    out, facts = {}, []
    for t in tickers:
        a = px[t].dropna() if t in px else pd.Series(dtype=float)
        r = np.diff(np.log(a.to_numpy()))[-60:]
        if len(r) < 60:
            continue
        out[t] = float(np.std(r, ddof=1) * np.sqrt(252))
        facts.append(_fact(view, t, "vol_60d", out[t], "ratio", a.index[-1].date(), "price_daily"))
    return pd.Series(out, name="vol_60d", dtype=float), facts


def _valuation_metric(view: MarketDataView, tickers: Sequence[str], column: str, metric: str, *, positive_only: bool) -> tuple[pd.Series, list[Fact]]:
    v = view.valuation(tickers)
    out, facts = {}, []
    for t in tickers:
        if t not in v.index:
            continue
        x = v.at[t, column]
        if x is None or pd.isna(x):
            continue
        if positive_only and float(x) <= 0:
            continue
        out[t] = float(x)
        facts.append(_fact(view, t, metric, out[t], "ratio", v.at[t, "date"], "valuation_daily"))
    return pd.Series(out, name=metric, dtype=float), facts


def pe_ttm(view: MarketDataView, tickers: Sequence[str]) -> tuple[pd.Series, list[Fact]]:
    """PER = 종가 / 최근 4분기 EPS. 이익 ≤ 0 은 DB 에서 NULL (제외)."""
    return _valuation_metric(view, tickers, "per", "pe_ttm", positive_only=True)


def roe_ttm(view: MarketDataView, tickers: Sequence[str]) -> tuple[pd.Series, list[Fact]]:
    return _valuation_metric(view, tickers, "roe_ttm", "roe_ttm", positive_only=False)


def dividend_yield_ttm(view: MarketDataView, tickers: Sequence[str]) -> tuple[pd.Series, list[Fact]]:
    return _valuation_metric(view, tickers, "dividend_yield", "dividend_yield_ttm", positive_only=False)


# 선정 자격선 (2026-11 시나리오 QA, 사용자 정책 결정 3): 후보가 목표보다 적어도 이 범위 밖 종목은 뽑지 않는다 (강제 포함 제외).
# (하한, 상한) — 하한은 초과(>), 상한은 이하(≤). 배당 상한 30% 는 정책이 아니라 자료 오류 거름 (000: STX 배당수익률 20541).
ELIGIBLE_RANGE: dict[str, tuple[float | None, float | None]] = {"pe_ttm": (0.0, 50.0), "roe_ttm": (0.0, None), "dividend_yield_ttm": (0.0, 0.30)}


def eligible(metric: str, value: float | None, ranges: dict[str, tuple[float | None, float | None]] | None = None) -> bool:
    """선정 지표 값이 자격선 안인가. 자격선이 없는 지표(모멘텀·변동성)는 값이 있으면 통과."""
    try:
        v = float(value)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return False
    if v != v:
        return False
    lo, hi = (ranges or ELIGIBLE_RANGE).get(metric, (None, None))
    return (lo is None or v > lo) and (hi is None or v <= hi)


METRICS: dict[str, Callable[[MarketDataView, Sequence[str]], tuple[pd.Series, list[Fact]]]] = {
    "return_12m_1m": return_12m_1m,
    "vol_60d": vol_60d,
    "pe_ttm": pe_ttm,
    "roe_ttm": roe_ttm,
    "dividend_yield_ttm": dividend_yield_ttm,
}


METRIC_KO = {"return_12m_1m": "모멘텀(최근 12개월 수익률, 직전 1개월 제외)", "vol_60d": "60일 변동성(연율)", "pe_ttm": "PER(주가 ÷ 최근 12개월 주당순이익)",
             "roe_ttm": "ROE(최근 12개월 자기자본이익률)", "dividend_yield_ttm": "배당수익률(최근 12개월)"}


def display_metric(metric: str, value: float | None) -> str:
    """선정 지표 값을 사람이 읽는 말로 (LLM 입력·리포트용). 예: 0.9540 → '+95.4%', PER 4.6435 → '4.6배'."""
    try:
        v = float(value)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return "자료 없음"
    if v != v:
        return "자료 없음"
    if metric == "return_12m_1m":
        return f"{v:+.1%}"
    if metric == "pe_ttm":
        return f"{v:.1f}배"
    if metric in ("roe_ttm", "vol_60d", "dividend_yield_ttm"):
        return f"{v:.1%}" if metric != "dividend_yield_ttm" else f"{v:.2%}"
    return f"{v:.4g}"
