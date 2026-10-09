"""As-of screening metrics. Every function only uses data dated <= as_of (no look-ahead)."""
import datetime as dt
import numpy as np
import pandas as pd
import pyarrow.parquet as pq
from common import RAW

REPORT_LAG_DAYS = 45       # quarter results are assumed public 45 days after period end


def _prices(tickers, start, end, cols=("date", "ticker", "adj_close", "close")):
    t = pq.read_table(RAW / "prices.parquet", columns=list(cols),
                      filters=[("ticker", "in", list(tickers)), ("date", ">=", pd.Timestamp(start)),
                               ("date", "<=", pd.Timestamp(end))])
    return t.to_pandas().sort_values(["ticker", "date"])


def _last_close(px: pd.DataFrame, col="close") -> pd.Series:
    return px.groupby("ticker")[col].last()


def return_12m_1m(tickers, as_of: dt.date) -> pd.Series:
    """12-month return skipping the most recent month: P(t-21 trading days) / P(t-252) - 1."""
    px = _prices(tickers, as_of - dt.timedelta(days=420), as_of)
    out = {}
    for t, g in px.groupby("ticker"):
        a = g["adj_close"].to_numpy()
        if len(a) < 253: continue
        out[t] = a[-22] / a[-253] - 1
    return pd.Series(out, name="return_12m_1m")


def vol_60d(tickers, as_of: dt.date) -> pd.Series:
    px = _prices(tickers, as_of - dt.timedelta(days=120), as_of)
    out = {}
    for t, g in px.groupby("ticker"):
        r = np.diff(np.log(g["adj_close"].to_numpy()))[-60:]
        if len(r) < 60: continue
        out[t] = float(np.std(r, ddof=1) * np.sqrt(252))
    return pd.Series(out, name="vol_60d")


def dividend_yield_ttm(tickers, as_of: dt.date) -> pd.Series:
    p = RAW / "dividends.parquet"
    if not p.exists():
        raise FileNotFoundError("dividends.parquet missing: run scripts/fetch_fundamentals.py")
    d = pd.read_parquet(p)
    d["date"] = pd.to_datetime(d["date"])
    d = d[(d["ticker"].isin(tickers)) & (d["date"] <= pd.Timestamp(as_of)) & (d["date"] > pd.Timestamp(as_of - dt.timedelta(days=365)))]
    ttm = d.groupby("ticker")["dividend"].sum()
    px = _last_close(_prices(tickers, as_of - dt.timedelta(days=10), as_of))
    return (ttm / px).dropna().rename("dividend_yield_ttm")


def _quarterly(item: str, statement: str, tickers, as_of: dt.date) -> pd.DataFrame:
    p = RAW / "statements_quarterly.parquet"
    if not p.exists():
        raise FileNotFoundError("statements_quarterly.parquet missing: run scripts/fetch_fundamentals.py")
    s = pd.read_parquet(p)
    s = s[(s["ticker"].isin(tickers)) & (s["statement"] == statement) & (s["item"] == item)]
    s["period_end"] = pd.to_datetime(s["period_end"])
    return s[s["period_end"] <= pd.Timestamp(as_of - dt.timedelta(days=REPORT_LAG_DAYS))]


def pe_ttm(tickers, as_of: dt.date) -> pd.Series:
    """price(as_of) / sum of the last 4 reported quarterly diluted EPS. Non-positive EPS -> NaN (excluded)."""
    eps = _quarterly("Diluted EPS", "income", tickers, as_of)
    ttm = eps.sort_values("period_end").groupby("ticker").tail(4).groupby("ticker").agg(eps=("value", "sum"), n=("value", "size"))
    ttm = ttm[(ttm["n"] == 4) & (ttm["eps"] > 0)]["eps"]
    px = _last_close(_prices(tickers, as_of - dt.timedelta(days=10), as_of))
    return (px / ttm).dropna().rename("pe_ttm")


def roe_ttm(tickers, as_of: dt.date) -> pd.Series:
    ni = _quarterly("Net Income Common Stockholders", "income", tickers, as_of)
    ni4 = ni.sort_values("period_end").groupby("ticker").tail(4).groupby("ticker").agg(ni=("value", "sum"), n=("value", "size"))
    eq = _quarterly("Stockholders Equity", "balance", tickers, as_of).sort_values("period_end").groupby("ticker")["value"].last()
    df = ni4[ni4["n"] == 4].join(eq.rename("eq"), how="inner")
    df = df[df["eq"] > 0]
    return (df["ni"] / df["eq"]).rename("roe_ttm")


METRICS = {"pe_ttm": pe_ttm, "roe_ttm": roe_ttm, "return_12m_1m": return_12m_1m,
           "vol_60d": vol_60d, "dividend_yield_ttm": dividend_yield_ttm}
