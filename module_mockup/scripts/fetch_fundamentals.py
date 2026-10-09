"""
Step 2b (data collection): fetch per-ticker fundamentals via yfinance and cache.

Outputs (data/raw/):
  info_snapshot.json       current-point snapshot of ~60 screening fields per ticker
  statements_quarterly.parquet  long table: ticker, period_end, statement, item, value
  statements_annual.parquet
  dividends.parquet        full dividend history per ticker
  fundamentals_log.json    which tickers failed

Usage: python scripts/fetch_fundamentals.py [--workers 4]
"""
import argparse, json, time
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
import pandas as pd
import yfinance as yf

from common import RAW  # local-disk cache dir (outside Google Drive)
CACHE = RAW / "_fund_cache"
CACHE.mkdir(parents=True, exist_ok=True)
import pickle

INFO_KEYS = [
    # valuation
    "trailingPE", "forwardPE", "pegRatio", "trailingPegRatio", "priceToBook",
    "priceToSalesTrailing12Months", "enterpriseToEbitda", "enterpriseToRevenue",
    "marketCap", "enterpriseValue", "currentPrice", "bookValue", "trailingEps", "forwardEps",
    # profitability
    "returnOnEquity", "returnOnAssets", "grossMargins", "operatingMargins", "profitMargins", "ebitdaMargins",
    # growth
    "revenueGrowth", "earningsGrowth", "earningsQuarterlyGrowth",
    # balance / cash
    "debtToEquity", "currentRatio", "quickRatio", "totalCash", "totalDebt",
    "freeCashflow", "operatingCashflow", "totalRevenue", "ebitda", "netIncomeToCommon",
    # dividend
    "dividendYield", "dividendRate", "payoutRatio", "fiveYearAvgDividendYield",
    # market / technical
    "beta", "sharesOutstanding", "floatShares", "averageVolume", "averageVolume10days",
    "fiftyTwoWeekHigh", "fiftyTwoWeekLow", "fiftyDayAverage", "twoHundredDayAverage",
    # ownership / short / analysts
    "shortPercentOfFloat", "shortRatio", "heldPercentInstitutions", "heldPercentInsiders",
    "targetMeanPrice", "targetMedianPrice", "recommendationMean", "recommendationKey", "numberOfAnalystOpinions",
    # meta
    "sector", "industry", "country", "fullTimeEmployees", "longName",
    # 1-paragraph business description: used for the universe descriptor / LLM candidate classification
    "longBusinessSummary",
]


def stmt_to_long(df, ticker, statement):
    if df is None or df.empty:
        return None
    # (pandas 3.0 melt() fails on Timestamp column labels -> build the long table by hand)
    rows = [(item, col, val) for col in df.columns for item, val in df[col].items()]
    d = pd.DataFrame(rows, columns=["item", "period_end", "value"])
    d["ticker"] = ticker
    d["statement"] = statement
    d["period_end"] = pd.to_datetime(d["period_end"])
    d["value"] = pd.to_numeric(d["value"], errors="coerce")
    return d.dropna(subset=["value"])


RATE_LIMIT_SLEEP = 120   # seconds to back off when Yahoo answers 429
RATE_LIMIT_RETRIES = 6


def fetch_one(ticker):
    cf = CACHE / f"{ticker}.pkl"
    if cf.exists():
        return pickle.load(open(cf, "rb"))
    for attempt in range(RATE_LIMIT_RETRIES + 1):
        r = _fetch_one(ticker)
        if r["error"] and "RateLimit" in r["error"] and attempt < RATE_LIMIT_RETRIES:
            print(f"  429 on {ticker}: sleeping {RATE_LIMIT_SLEEP}s (retry {attempt + 1}/{RATE_LIMIT_RETRIES})", flush=True)
            time.sleep(RATE_LIMIT_SLEEP)
            continue
        break
    if not r["error"]:
        pickle.dump(r, open(cf, "wb"))
    return r


def _fetch_one(ticker):
    t = yf.Ticker(ticker)
    out = {"ticker": ticker, "info": None, "q": [], "a": [], "div": None, "error": None}
    try:
        info = t.info or {}
        out["info"] = {k: info.get(k) for k in INFO_KEYS}
        out["info"]["ticker"] = ticker
        for name, qdf, adf in [
            ("income", t.quarterly_income_stmt, t.income_stmt),
            ("balance", t.quarterly_balance_sheet, t.balance_sheet),
            ("cashflow", t.quarterly_cashflow, t.cashflow),
        ]:
            q = stmt_to_long(qdf, ticker, name)
            a = stmt_to_long(adf, ticker, name)
            if q is not None: out["q"].append(q)
            if a is not None: out["a"].append(a)
        div = t.dividends
        if div is not None and len(div):
            d = div.rename("dividend").reset_index()
            d.columns = ["date", "dividend"]
            d["date"] = pd.to_datetime(d["date"]).dt.tz_localize(None)
            d["ticker"] = ticker
            out["div"] = d
    except Exception as e:
        out["error"] = repr(e)
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--workers", type=int, default=1)
    args = ap.parse_args()

    uni = pd.read_json(RAW / "universe.json")
    tickers = uni["ticker"].tolist()
    print(f"fetching fundamentals for {len(tickers)} tickers with {args.workers} workers", flush=True)

    infos, qs, as_, divs, errors = [], [], [], [], {}
    t0 = time.time()
    with ThreadPoolExecutor(max_workers=args.workers) as ex:
        futs = {ex.submit(fetch_one, tk): tk for tk in tickers}
        for i, f in enumerate(as_completed(futs), 1):
            r = f.result()
            if r["error"]:
                errors[r["ticker"]] = r["error"]
            if r["info"]: infos.append(r["info"])
            qs += r["q"]; as_ += r["a"]
            if r["div"] is not None: divs.append(r["div"])
            if i % 50 == 0:
                print(f"  {i}/{len(tickers)}  elapsed {time.time()-t0:.0f}s  errors={len(errors)}", flush=True)

    pd.DataFrame(infos).to_json(RAW / "info_snapshot.json", orient="records", indent=2)
    pd.concat(qs, ignore_index=True).to_parquet(RAW / "statements_quarterly.parquet", index=False)
    pd.concat(as_, ignore_index=True).to_parquet(RAW / "statements_annual.parquet", index=False)
    pd.concat(divs, ignore_index=True).to_parquet(RAW / "dividends.parquet", index=False)
    json.dump({"snapshot_date": str(pd.Timestamp.today().date()), "n_ok": len(infos),
               "errors": errors}, open(RAW / "fundamentals_log.json", "w"), indent=2)
    print(f"done in {time.time()-t0:.0f}s. ok={len(infos)} errors={len(errors)}")
    if errors: print("failed:", list(errors)[:20])


if __name__ == "__main__":
    main()
