"""
DB -> local cache sync (spec M2-02): materialize the team PostgreSQL DB into the parquet/JSON layout
that every pipeline stage already reads (RAW = $MYFINSIGHT_DATA/raw).

  MYFINSIGHT_DATA=~/.myfinsight/data_db python scripts/db_sync.py [--since 2016-01-01] [--chunk 40]

Writes RAW/:
  universe.json        copied from --source-cache (the descriptor is keyed by these tickers)
  prices.parquet       price_daily, ONE row per ticker-date (source priority CONSENSUS > YFINANCE > ALPACA > TIINGO,
                       then verify_status VERIFIED > SINGLE > MISMATCH); columns = yfinance cache layout
  fx_KRWX.parquet      fx_daily USDKRW (date, close)
  info_snapshot.json   [{ticker, sharesOutstanding, shares_source}] from financials 발행주식수 (SEC_EDGAR), fallback source cache
  benchmarks.parquet   COPIED from --source-cache: the DB has no ETFs/indices (gap reported in the manifest)
  db_sync_manifest.json coverage, chosen sources, gaps -> stage 13 puts it into the report sources / warnings
Read-only on the DB. Credentials from MyFinSight/.env (NEWS_DB_*).
"""
import argparse, datetime as dt, json, shutil, sys, time
from pathlib import Path
import pandas as pd
from sqlalchemy import text
from common import RAW, load_json, dump_json
from news_db import get_engine

SRC_PRIO = "case p.source when 'CONSENSUS' then 0 when 'YFINANCE' then 1 when 'ALPACA' then 2 when 'TIINGO' then 3 when 'KIS' then 4 else 9 end"
VER_PRIO = "case p.verify_status when 'VERIFIED' then 0 when 'SINGLE' then 1 else 2 end"


def q(engine, sql, **params):
    with engine.connect() as c:
        return pd.read_sql(text(sql), c, params=params)


def sync_prices(engine, tickers, since, chunk):
    frames, t0 = [], time.time()
    for i in range(0, len(tickers), chunk):
        part = tickers[i:i + chunk]
        df = q(engine, f"""
            select distinct on (p.asset_id, p.date)
                   a.ticker, p.date, p.open, p.high, p.low, p.close, p.adj_close, p.volume, p.source, p.verify_status
            from price_daily p join assets a on a.asset_id = p.asset_id
            where a.market = 'US' and a.ticker = any(:tickers) and p.date >= :since
            order by p.asset_id, p.date, {SRC_PRIO}, {VER_PRIO}""", tickers=part, since=since)
        frames.append(df)
        print(f"  prices {i + len(part)}/{len(tickers)} tickers, {sum(len(f) for f in frames):,} rows, {time.time() - t0:.0f}s", flush=True)
    px = pd.concat(frames, ignore_index=True)
    px["date"] = pd.to_datetime(px["date"])
    px = px.dropna(subset=["adj_close", "close"]).sort_values(["ticker", "date"])
    by_source = px["source"].value_counts().to_dict()
    by_status = px["verify_status"].value_counts().to_dict()
    out = px[["date", "ticker", "open", "high", "low", "close", "adj_close", "volume"]].reset_index(drop=True)
    out["volume"] = out["volume"].astype("float64")
    return out, by_source, by_status


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--source-cache", default=str(Path.home() / ".myfinsight" / "data" / "raw"), help="yfinance cache: universe.json, benchmarks.parquet, info_snapshot.json fallback")
    ap.add_argument("--since", default="2016-01-01")
    ap.add_argument("--chunk", type=int, default=40)
    a = ap.parse_args()
    src = Path(a.source_cache)
    if RAW.resolve() == src.resolve():
        sys.exit("refusing to overwrite the source cache: set MYFINSIGHT_DATA to a different directory")
    RAW.mkdir(parents=True, exist_ok=True)
    engine = get_engine()
    gaps, manifest = [], {"synced_at": dt.datetime.now().isoformat(timespec="seconds"), "db": "team PostgreSQL `myfinsight` (read-only account)", "raw_dir": str(RAW)}

    # 1. universe (descriptor keys) — copied; DB index_constituent is the future source (spec M2-03)
    uni = load_json(src / "universe.json")
    tickers = [r["ticker"] for r in uni]
    shutil.copy(src / "universe.json", RAW / "universe.json")

    # 2. prices
    print(f"[db_sync] prices for {len(tickers)} tickers since {a.since}", flush=True)
    px, by_source, by_status = sync_prices(engine, tickers, a.since, a.chunk)
    px.to_parquet(RAW / "prices.parquet", index=False)
    have = set(px["ticker"].unique()); missing = sorted(set(tickers) - have)
    if missing:
        gaps.append(f"DB price_daily에 없는 유니버스 종목 {len(missing)}개: {', '.join(missing)} (후보에서 자동 제외)")
    manifest["prices"] = {"rows": int(len(px)), "n_tickers": len(have), "missing_tickers": missing, "date_min": str(px["date"].min().date()),
                          "date_max": str(px["date"].max().date()), "rows_by_source": by_source, "rows_by_verify_status": by_status,
                          "rule": "one row per ticker-date; source priority CONSENSUS > YFINANCE > ALPACA > TIINGO > KIS, then VERIFIED > SINGLE > MISMATCH"}
    print(f"[db_sync] prices.parquet rows={len(px):,} tickers={len(have)} {manifest['prices']['date_min']}..{manifest['prices']['date_max']} sources={by_source}", flush=True)

    # 3. fx
    fx = q(engine, "select date, rate as close from fx_daily where pair = 'USDKRW' and date >= :since order by date", since=a.since)
    fx["date"] = pd.to_datetime(fx["date"]); fx = fx.dropna()
    fx.to_parquet(RAW / "fx_KRWX.parquet", index=False)
    manifest["fx"] = {"pair": "USDKRW", "rows": int(len(fx)), "date_min": str(fx["date"].min().date()), "date_max": str(fx["date"].max().date())}
    print(f"[db_sync] fx_KRWX.parquet rows={len(fx)} {manifest['fx']['date_min']}..{manifest['fx']['date_max']}", flush=True)

    # 4. shares outstanding -> info_snapshot.json (only the field the pipeline reads)
    sh = q(engine, """select distinct on (asset_id) asset_id, value, period_end, source from financials
                      where metric = '발행주식수' and asset_id like 'US-%' order by asset_id, period_end desc""")
    sh["ticker"] = sh["asset_id"].str.replace("US-", "", n=1, regex=False)
    db_shares = {r.ticker: (float(r.value), str(r.period_end), r.source) for r in sh.itertuples()}
    fallback = {}
    if (src / "info_snapshot.json").exists():
        fallback = {r["ticker"]: r.get("sharesOutstanding") for r in load_json(src / "info_snapshot.json")}
    snap, n_db, n_fb, n_none = [], 0, 0, 0
    for t in tickers:
        if t in db_shares:
            v, pe, s = db_shares[t]; snap.append({"ticker": t, "sharesOutstanding": v, "shares_source": f"DB financials {s} 발행주식수 ({pe})"}); n_db += 1
        elif fallback.get(t):
            snap.append({"ticker": t, "sharesOutstanding": fallback[t], "shares_source": "yfinance cache (DB에 발행주식수 없음)"}); n_fb += 1
        else:
            snap.append({"ticker": t, "sharesOutstanding": None, "shares_source": "none"}); n_none += 1
    dump_json(snap, RAW / "info_snapshot.json")
    manifest["shares"] = {"from_db": n_db, "from_yfinance_cache": n_fb, "none": n_none}
    if n_fb:
        gaps.append(f"발행주식수가 DB(SEC_EDGAR)에 없는 종목 {n_fb}개는 yfinance 캐시 값을 사용")
    print(f"[db_sync] info_snapshot.json shares: db={n_db} fallback={n_fb} none={n_none}", flush=True)

    # 5. benchmarks — not in the DB
    bench_src = src / "benchmarks.parquet"
    if bench_src.exists():
        shutil.copy(bench_src, RAW / "benchmarks.parquet")
        b = pd.read_parquet(RAW / "benchmarks.parquet", columns=["ticker", "date"])
        manifest["benchmarks"] = {"source": "yfinance cache copy (DB에 ETF·지수 없음)", "tickers": sorted(b["ticker"].unique().tolist()),
                                  "date_min": str(b["date"].min().date()), "date_max": str(b["date"].max().date())}
        gaps.append("비교지수(SPY·QQQ·XLV 등)는 팀 DB에 없어 yfinance 캐시 사본을 사용 — DB의 extra_ticker에 ETF 추가 필요")
    else:
        gaps.append("benchmarks.parquet 없음: 비교지수 데이터가 없어 백테스트 불가")
    manifest["not_synced"] = ["dividends.parquet, statements_*.parquet (재무 템플릿 low_per/quality 미사용 시 불필요)"]
    manifest["gaps"] = gaps
    dump_json(manifest, RAW / "db_sync_manifest.json")
    print(f"[db_sync] done -> {RAW}  gaps={len(gaps)}", flush=True)
    for g in gaps:
        print("   -", g)


if __name__ == "__main__":
    main()
