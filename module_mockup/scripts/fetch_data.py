"""
Step 2 (data collection): download S&P500 + NASDAQ100 constituents and
daily OHLCV history via yfinance, then cache to data/raw/.

Usage:
    python scripts/fetch_data.py --years 15
"""
import argparse, json, time, io, re
from pathlib import Path
import pandas as pd
import yfinance as yf
import requests

from common import RAW  # local-disk cache dir (outside Google Drive)
RAW.mkdir(parents=True, exist_ok=True)
HEADERS = {"User-Agent": "Mozilla/5.0"}


def read_wiki_tables(url):
    html = requests.get(url, headers=HEADERS, timeout=30).text
    return pd.read_html(io.StringIO(html))


def get_sp500():
    tables = read_wiki_tables("https://en.wikipedia.org/wiki/List_of_S%26P_500_companies")
    df = tables[0]
    df = df.rename(columns={"Symbol": "ticker", "Security": "name",
                            "GICS Sector": "sector", "GICS Sub-Industry": "industry"})
    df = df[["ticker", "name", "sector", "industry"]].copy()
    df["index"] = "SP500"
    return df


def get_nasdaq100():
    tables = read_wiki_tables("https://en.wikipedia.org/wiki/List_of_NASDAQ-100_companies")
    for t in tables:
        cols = [str(c) for c in t.columns]
        if "Ticker" in cols or "Symbol" in cols:
            df = t.copy()
            df.columns = [re.sub(r"\[.*?\]", "", str(c)).strip() for c in df.columns]
            df = df.rename(columns={"Ticker": "ticker", "Symbol": "ticker", "Company": "name",
                                    "GICS Sector": "sector", "GICS Sub-Industry": "industry",
                                    "ICB Industry": "sector", "ICB Subsector": "industry"})
            keep = [c for c in ["ticker", "name", "sector", "industry"] if c in df.columns]
            df = df[keep].copy()
            df["index"] = "NASDAQ100"
            return df
    raise RuntimeError("NASDAQ100 table not found")


def build_universe():
    sp = get_sp500()
    nq = get_nasdaq100()
    uni = pd.concat([sp, nq], ignore_index=True)
    # yfinance uses '-' instead of '.' (e.g. BRK.B -> BRK-B)
    uni["ticker"] = uni["ticker"].astype(str).str.replace(".", "-", regex=False).str.strip()
    # merge index membership
    grouped = uni.groupby("ticker").agg(
        name=("name", "first"), sector=("sector", "first"),
        industry=("industry", "first"), indices=("index", lambda s: sorted(set(s)))
    ).reset_index()
    return grouped


def download_prices(tickers, years):
    end = pd.Timestamp.today().normalize()
    start = end - pd.DateOffset(years=years)
    frames = []
    batch = 100
    for i in range(0, len(tickers), batch):
        chunk = tickers[i:i + batch]
        print(f"  downloading {i + 1}-{i + len(chunk)} / {len(tickers)} ...", flush=True)
        df = yf.download(chunk, start=start, end=end, auto_adjust=False,
                         group_by="ticker", threads=True, progress=False)
        if isinstance(df.columns, pd.MultiIndex):
            df = df.stack(level=0, future_stack=True).rename_axis(["date", "ticker"]).reset_index()
        else:
            df = df.reset_index().assign(ticker=chunk[0]).rename(columns={"Date": "date"})
        frames.append(df)
        time.sleep(1)
    out = pd.concat(frames, ignore_index=True)
    out.columns = [str(c).lower().replace(" ", "_") for c in out.columns]
    out = out.dropna(subset=["close"])
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--years", type=int, default=15)
    args = ap.parse_args()

    print("[1/3] building universe (S&P500 + NASDAQ100)")
    uni = build_universe()
    uni.to_json(RAW / "universe.json", orient="records", indent=2, force_ascii=False)
    print(f"      {len(uni)} unique tickers")

    print(f"[2/3] downloading {args.years}y daily prices for benchmarks")
    bench = download_prices(["SPY", "QQQ", "^GSPC", "^NDX"], args.years)
    bench.to_parquet(RAW / "benchmarks.parquet", index=False)

    print(f"[3/3] downloading {args.years}y daily prices for constituents")
    t0 = time.time()
    prices = download_prices(uni["ticker"].tolist(), args.years)
    prices.to_parquet(RAW / "prices.parquet", index=False)
    print(f"      done in {time.time() - t0:.0f}s, rows={len(prices):,}")

    summary = prices.groupby("ticker")["date"].agg(["min", "max", "count"])
    summary["min"] = summary["min"].astype(str); summary["max"] = summary["max"].astype(str)
    summary.reset_index().to_json(RAW / "coverage.json", orient="records", indent=2)
    print("coverage summary:")
    print(summary.describe())


if __name__ == "__main__":
    main()
