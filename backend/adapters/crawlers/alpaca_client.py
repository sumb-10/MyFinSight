"""[정량·해외 보정] Alpaca Markets 일봉 (https://data.alpaca.markets/v2/stocks/{symbol}/bars,
여러 종목은 /v2/stocks/bars?symbols=… 한 번에).

- adjustment=split → close (분할만 반영, yfinance Close와 같은 기준)
- adjustment=all   → adj_close (분할 + 배당 반영)
- feed: ALPACA_FEED=sip(기본, 전체 거래소 통합) | iex. 구독이 없어 sip이 거부되면 iex로 자동 전환.
  무료 플랜은 최근 15분 SIP 데이터를 못 쓰므로 종료일은 어제까지로 제한한다.
"""

from collections import defaultdict
from datetime import date, timedelta

from backend.adapters.crawlers import config
from backend.adapters.crawlers.common import http_session

SOURCE = "ALPACA"
BASE = "https://data.alpaca.markets/v2/stocks"
_session = http_session()


def _headers() -> dict:
    config.require(
        ALPACA_API_KEY_ID=config.ALPACA_API_KEY_ID,
        ALPACA_API_SECRET_KEY=config.ALPACA_API_SECRET_KEY,
    )
    return {
        "APCA-API-KEY-ID": config.ALPACA_API_KEY_ID,
        "APCA-API-SECRET-KEY": config.ALPACA_API_SECRET_KEY,
    }


def _get_pages(url: str, params: dict, feed: str):
    """다음 쪽 토큰을 따라가며 응답 본문을 하나씩 돌려준다."""
    token = None
    while True:
        p = {**params, "page_token": token} if token else params
        res = _session.get(url, headers=_headers(), params=p, timeout=30)
        if res.status_code in (401, 403):
            raise PermissionError(
                f"Alpaca 권한 오류 status={res.status_code} feed={feed} body={res.text[:200]}"
            )
        if not res.ok:
            raise RuntimeError(f"Alpaca 오류 status={res.status_code} body={res.text[:200]}")
        payload = res.json()
        yield payload
        token = payload.get("next_page_token")
        if not token:
            return


def _params(start: date, end: date, adjustment: str, feed: str) -> dict:
    return {
        "timeframe": "1Day",
        "start": start.isoformat(),
        "end": end.isoformat(),
        "adjustment": adjustment,
        "feed": feed,
        "limit": 10000,
    }


def fetch_bars(symbol: str, start: date, end: date, adjustment: str, feed: str) -> list[dict]:
    bars: list[dict] = []
    for payload in _get_pages(f"{BASE}/{symbol}/bars", _params(start, end, adjustment, feed), feed):
        bars += payload.get("bars") or []
    return bars


def fetch_bars_many(
    symbols: list[str], start: date, end: date, adjustment: str, feed: str
) -> dict[str, list[dict]]:
    """여러 종목 일봉을 한 요청으로 (쪽 나눔은 전체 봉 수 기준). {종목: 봉 목록}."""
    out: dict[str, list[dict]] = defaultdict(list)
    params = {**_params(start, end, adjustment, feed), "symbols": ",".join(symbols)}
    for payload in _get_pages(f"{BASE}/bars", params, feed):
        for sym, bars in (payload.get("bars") or {}).items():
            out[sym] += bars or []
    return dict(out)


def _feed() -> str:
    return config.ALPACA_FEED if config.ALPACA_FEED in ("sip", "iex") else "sip"


def _with_feed(fetch, feed: str):
    """sip 구독이 없어 거부되면 iex 로 다시. (결과, 사용한 feed)"""
    try:
        return fetch(feed), feed
    except PermissionError:
        if feed == "iex":
            raise
        return fetch("iex"), "iex"


def fetch_prices(symbol: str, start: date, end: date) -> tuple[list[dict], list[dict], str]:
    """(분할보정 bars, 전체보정 bars, 사용한 feed)"""
    end = min(end, date.today() - timedelta(days=1))
    split, feed = _with_feed(lambda f: fetch_bars(symbol, start, end, "split", f), _feed())
    return split, fetch_bars(symbol, start, end, "all", feed), feed


def _rows(split: list[dict], full: list[dict]) -> list[dict]:
    adj = {b["t"][:10]: b.get("c") for b in full}
    return [
        {
            "date": b["t"][:10],
            "open": b.get("o"),
            "high": b.get("h"),
            "low": b.get("l"),
            "close": b["c"],
            "adj_close": adj.get(b["t"][:10]),
            "volume": int(b["v"]) if b.get("v") is not None else None,
            "currency": "USD",
        }
        for b in split
        if b.get("c") is not None
    ]


def price_rows(symbol: str, start: date, end: date) -> list[dict]:
    """명세 payload 행 목록. 원본 collect() 의 행 만들기 부분 (DB 저장은 뺐다)."""
    split, full, _feed_used = fetch_prices(symbol.replace("-", "."), start, end)
    return _rows(split, full)


def price_rows_many(symbols: list[str], start: date, end: date) -> dict[str, list[dict]]:
    """여러 종목을 요청 두 번(분할보정·전체보정)으로. {요청 표기: 행 목록}, 봉이 없는 종목은 빠짐."""
    names = {s.replace("-", "."): s for s in symbols}
    end = min(end, date.today() - timedelta(days=1))
    split, feed = _with_feed(
        lambda f: fetch_bars_many(list(names), start, end, "split", f), _feed()
    )
    full = fetch_bars_many(list(names), start, end, "all", feed)
    return {
        names[sym]: rows
        for sym, bars in split.items()
        if sym in names and (rows := _rows(bars, full.get(sym) or []))
    }
