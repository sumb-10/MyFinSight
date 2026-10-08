"""[정량] yfinance — 일봉(수정주가 포함). 국내(.KS/.KQ)·미국·환율(KRW=X) 모두.

국내 종목은 먼저 .KS로 조회하고, 비어 있으면 .KQ(코스닥)로 다시 조회한다.
원본의 주요 지표 스냅샷(PER·PBR 등, yf.Ticker().info)은 가격 어댑터 범위 밖이라 snapshot() 으로
따로 남겨 두었다.
"""

from datetime import date, timedelta

import pandas as pd

SOURCE = "YFINANCE"
INFO_FIELDS = {
    "trailingPE": ("PER", "배"),
    "priceToBook": ("PBR", "배"),
    "returnOnEquity": ("ROE", "비율"),
    "marketCap": ("시가총액", None),
    "dividendYield": ("배당수익률", "%"),
}


def _yf():
    try:
        import yfinance as yf
    except (
        ImportError
    ) as exc:  # yfinance 를 안 쓰는 출처만 쓸 때는 설치가 없어도 되게 늦게 불러온다
        raise ImportError('yfinance 가 없음: python -m pip install -e ".[real]"') from exc
    return yf


def fetch_history(symbol: str, start: date, end: date) -> pd.DataFrame:
    df = (
        _yf()
        .Ticker(symbol)
        .history(start=start, end=end + timedelta(days=1), auto_adjust=False, actions=False)
    )
    if df.empty:
        return df
    df = df.dropna(subset=["Close"])
    df.index = pd.to_datetime(df.index).date
    return df


def _f(v):
    return float(v) if v is not None and pd.notna(v) else None


def currency_of(symbol: str) -> str | None:
    """표기로 통화 추정: .KS/.KQ → KRW, 환율(=X) → None, 나머지 → USD."""
    if symbol.endswith((".KS", ".KQ")):
        return "KRW"
    if symbol.endswith("=X"):
        return None
    return "USD"


def _rows(df: pd.DataFrame, cur: str | None) -> list[dict]:
    return [
        {
            "date": d.isoformat(),
            "open": _f(r.get("Open")),
            "high": _f(r.get("High")),
            "low": _f(r.get("Low")),
            "close": float(r["Close"]),
            "adj_close": _f(r.get("Adj Close")),
            "volume": int(r["Volume"]) if pd.notna(r.get("Volume")) else None,
            "currency": cur,
        }
        for d, r in df.iterrows()
    ]


def price_rows(symbol: str, start: date, end: date) -> list[dict]:
    """명세 payload 행 목록. .KS 가 비면 .KQ 로 다시 조회 (원본 collect() 의 시장 자동 판별)."""
    df = fetch_history(symbol, start, end)
    if df.empty and symbol.endswith((".KS", ".KQ")):
        alt = symbol[:-3] + (".KQ" if symbol.endswith(".KS") else ".KS")
        df = fetch_history(alt, start, end)
    if df.empty:
        raise RuntimeError(f"yfinance에서 {symbol} 가격을 찾지 못함 (티커 확인)")
    return _rows(df, currency_of(symbol))


def download_many(symbols: list[str], start: date, end: date) -> dict[str, pd.DataFrame]:
    """yf.download 로 여러 종목을 한 번에 (yfinance 가 안에서 동시에 요청). 빈 종목은 빠짐."""
    df = _yf().download(
        list(symbols),
        start=start,
        end=end + timedelta(days=1),
        auto_adjust=False,
        actions=False,
        group_by="ticker",
        threads=True,
        progress=False,
    )
    out: dict[str, pd.DataFrame] = {}
    if df is None or df.empty:
        return out
    multi = isinstance(df.columns, pd.MultiIndex)
    have = set(df.columns.get_level_values(0)) if multi else set()
    for s in symbols:
        if multi and s not in have:
            continue
        sub = (df[s] if multi else df).dropna(subset=["Close"])
        if sub.empty:
            continue
        sub = sub.copy()
        sub.index = pd.to_datetime(sub.index).date
        out[s] = sub
    return out


def price_rows_many(symbols: list[str], start: date, end: date) -> dict[str, list[dict]]:
    """여러 종목 행 목록. 빠진 종목(.KQ 로 바꿔야 하는 종목 등)은 호출자가 한 종목씩 다시 받음."""
    return {s: _rows(df, currency_of(s)) for s, df in download_many(symbols, start, end).items()}


def snapshot(symbol: str) -> dict[str, tuple[float, str | None]]:
    """주요 지표 스냅샷 {지표: (값, 단위)}. 원본 collect() 의 info 부분."""
    info = _yf().Ticker(symbol).info or {}
    out = {}
    for key, (metric, unit) in INFO_FIELDS.items():
        v = _f(info.get(key)) if isinstance(info.get(key), (int, float)) else None
        if v is not None:
            out[metric] = (v, unit or info.get("currency"))
    return out


def sector_of(symbol: str) -> tuple[str, str]:
    """Yahoo 섹터·산업 이름 (예: Technology, Semiconductors). 모르면 ("", "")."""
    try:
        info = _yf().Ticker(symbol).info or {}
    except Exception:  # noqa: BLE001 - 한 종목 실패는 빈 칸으로 두고 보충표로 채움
        return "", ""
    return str(info.get("sector") or ""), str(info.get("industry") or "")


_KINDS = {"ETF": "ETF", "MUTUALFUND": "ETF", "INDEX": "INDEX", "EQUITY": "STOCK"}


def asset_kind(symbol: str) -> tuple[str | None, str | None]:
    """(assets.asset_type, 이름). Yahoo quoteType: ETF·MUTUALFUND → ETF, INDEX → INDEX,
    EQUITY → STOCK. 못 받으면 (None, None)."""
    try:
        info = _yf().Ticker(symbol).info or {}
    except Exception:  # noqa: BLE001 - 종류를 몰라도 가격 저장은 그대로 (기본 STOCK)
        return None, None
    name = info.get("longName") or info.get("shortName")
    return _KINDS.get(str(info.get("quoteType") or "").upper()), (str(name) if name else None)
