"""
Stage 1: validate the user request (Pydantic, HARD rules) and derive machine values.

in : input/01_user_request.example.jsonc
out: output/01_request.json   (= request + derived{as_of, fx, usd amounts, rebalance rule, data range})

Usage: python scripts/stage1_normalize.py [--request PATH] [--fx-rate 1400]
  --fx-rate : manual KRW-per-USD rate, only used when the FX cache is empty and yfinance is unavailable.
"""
import argparse, datetime as dt
import pandas as pd
import pyarrow.parquet as pq
from common import INPUT, OUTPUT, RAW, load_jsonc, dump_json
from schemas import UserRequest, NormalizedRequest, Derived, RebalanceRule

REBALANCE_DESC = {"2w": "2주", "1m": "1개월", "1q": "분기", "6m": "반기", "1y": "1년"}
CALENDAR = {"1m": "month_start", "1q": "quarter_start", "6m": "half_year_start", "1y": "year_start"}


def price_data_range():
    t = pq.read_table(RAW / "prices.parquet", columns=["date"])
    s = pd.to_datetime(t.column("date").to_pandas())
    return s.min().date(), s.max().date()


def fx_rate_on(pair: str, day: dt.date, manual: float | None):
    """Last close of `pair` on or before `day`. Cache -> yfinance -> manual fallback."""
    cache = RAW / f"fx_{pair.replace('=', '')}.parquet"
    hist = pd.read_parquet(cache) if cache.exists() else pd.DataFrame(columns=["date", "close"])
    hist["date"] = pd.to_datetime(hist["date"]) if len(hist) else hist["date"]
    sel = hist[hist["date"] <= pd.Timestamp(day)] if len(hist) else hist
    if len(sel) and (pd.Timestamp(day) - sel["date"].max()).days <= 7:
        r = sel.iloc[-1]; return float(r["close"]), r["date"].date(), "cache"
    try:
        import yfinance as yf
        df = yf.download(pair, start=day - dt.timedelta(days=15), end=day + dt.timedelta(days=1),
                         auto_adjust=False, progress=False)
        if df is None or df.empty:
            raise RuntimeError("empty")
        close = df["Close"].iloc[:, 0] if hasattr(df["Close"], "columns") else df["Close"]
        new = pd.DataFrame({"date": pd.to_datetime(close.index), "close": close.values}).dropna()
        hist = pd.concat([hist, new]).drop_duplicates("date").sort_values("date")
        hist.to_parquet(cache, index=False)
        sel = hist[hist["date"] <= pd.Timestamp(day)]
        r = sel.iloc[-1]; return float(r["close"]), r["date"].date(), "yfinance"
    except Exception as e:
        if manual is None:
            raise SystemExit(f"[stage1] FX {pair} unavailable ({e!r}); pass --fx-rate to continue")
        return float(manual), day, "manual_placeholder"


def rebalance_rule(count: int, unit: str) -> RebalanceRule:
    if count == 0:
        return RebalanceRule(count=0, unit=unit, enabled=False, description_ko="리밸런싱 없음 (매수 후 보유)")
    desc = f"{count}×{REBALANCE_DESC[unit]}마다 리밸런싱"
    if unit == "2w":
        return RebalanceRule(count=count, unit=unit, enabled=True, description_ko=desc, trading_days=10 * count)
    return RebalanceRule(count=count, unit=unit, enabled=True, description_ko=desc, calendar=CALENDAR[unit])


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--request", default=str(INPUT / "01_user_request.example.jsonc"))
    ap.add_argument("--fx-rate", type=float, default=None)
    ap.add_argument("--out", default=str(OUTPUT / "01_request.json"))
    args = ap.parse_args()

    req = UserRequest.model_validate(load_jsonc(args.request))
    d0, d1 = price_data_range()
    as_of = req.horizon.start_date
    if not (d0 <= as_of <= d1):
        raise SystemExit(f"[stage1] start_date {as_of} outside price data range {d0}..{d1}")

    if req.capital.currency == "USD":
        rate, fx_date, src, pair = 1.0, as_of, "none", "USD"
    else:
        pair = f"{req.capital.currency}=X"             # KRW=X : KRW per 1 USD
        rate, fx_date, src = fx_rate_on(pair, as_of, args.fx_rate)

    derived = Derived(
        as_of=as_of, fx_pair=pair, fx_rate=rate, fx_date=fx_date,
        initial_amount_usd=round(req.capital.initial_amount / rate, 2),
        monthly_contribution_usd=round(req.capital.monthly_contribution / rate, 2),
        rebalance_rule=rebalance_rule(req.constraints.rebalance.count, req.constraints.rebalance.unit),
        price_data_start=d0, price_data_end=d1,
    )
    out = NormalizedRequest(**req.model_dump(), derived=derived)
    payload = out.model_dump(mode="json")
    payload["derived"]["fx_source"] = src
    dump_json(payload, args.out)
    print(f"[stage1] ok -> {args.out}\n         as_of={as_of} fx={rate:.2f} ({src}, {fx_date}) "
          f"initial_usd={derived.initial_amount_usd:,.0f} rebalance={derived.rebalance_rule.description_ko}")


if __name__ == "__main__":
    main()
