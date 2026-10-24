"""Read-only access to the team news database (PostgreSQL `myfinsight`). Credentials from MyFinSight/.env (NEWS_DB_*)."""
import hashlib, os
from urllib.parse import quote_plus
import pandas as pd
from sqlalchemy import create_engine, text
from common import RAW, load_dotenv
import portfolio_config as PC

_engine = None


def get_engine():
    global _engine
    if _engine is None:
        kv = load_dotenv(); kv.update({k: v for k, v in os.environ.items() if k.startswith("NEWS_DB_")})
        if kv.get("NEWS_DB_URL"):
            url = kv["NEWS_DB_URL"].replace("postgresql://", "postgresql+psycopg://", 1)
        else:
            missing = [k for k in ("NEWS_DB_HOST", "NEWS_DB_USER", "NEWS_DB_PASSWORD") if not kv.get(k)]
            if missing: raise RuntimeError(f".env missing {missing}")
            url = (f"postgresql+psycopg://{quote_plus(kv['NEWS_DB_USER'])}:{quote_plus(kv['NEWS_DB_PASSWORD'])}@{kv['NEWS_DB_HOST']}:"
                   f"{kv.get('NEWS_DB_PORT') or 5432}/{kv.get('NEWS_DB_NAME') or 'myfinsight'}?sslmode={kv.get('NEWS_DB_SSL') or 'require'}")
        _engine = create_engine(url, connect_args={"connect_timeout": 10})
    return _engine


def fetch_news(tickers, start, end, languages=PC.NEWS_LANGS, per_ticker=PC.NEWS_PER_TICKER, use_cache=True) -> pd.DataFrame:
    """Headlines for US tickers with published_at in [start, end), deduplicated by title, newest `per_ticker` per ticker."""
    key = hashlib.sha1(f"{sorted(tickers)}|{start}|{end}|{languages}|{per_ticker}".encode()).hexdigest()[:16]
    cache = RAW / "news_cache" / f"{key}.parquet"
    if use_cache and cache.exists():
        return pd.read_parquet(cache)
    sql = text("""
        select n.news_id, a.ticker, n.source, n.publisher, n.title, n.url, n.published_at, n.language, n.query
        from news n join assets a on a.asset_id = n.asset_id
        where a.market = 'US' and a.ticker = any(:tickers) and n.published_at >= :start and n.published_at < :end
          and n.language = any(:langs)
        order by a.ticker, n.published_at desc""")
    with get_engine().connect() as con:
        df = pd.read_sql(sql, con, params={"tickers": list(tickers), "start": pd.Timestamp(start), "end": pd.Timestamp(end), "langs": list(languages)})
    if len(df):
        df["title_key"] = df["title"].str.lower().str.replace(r"\s+", " ", regex=True).str.strip()
        df = df.drop_duplicates(["ticker", "title_key"]).groupby("ticker", group_keys=False).head(per_ticker).drop(columns=["title_key"])
        df["published_at"] = pd.to_datetime(df["published_at"], utc=True).dt.tz_convert(None)
    cache.parent.mkdir(parents=True, exist_ok=True); df.to_parquet(cache, index=False)
    return df


def to_records(df: pd.DataFrame, origin="db") -> list[dict]:
    return [{"evidence_id": f"ev{int(r.news_id)}", "ticker": r.ticker, "published_at": str(pd.Timestamp(r.published_at).date()),
             "source": r.source, "publisher": r.publisher or "", "title": r.title, "url": r.url, "origin": origin} for r in df.itertuples()]
