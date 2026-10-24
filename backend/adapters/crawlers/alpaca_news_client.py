"""[정성] Alpaca News API (Benzinga 기사, 미국 종목, 2015년부터). 가격과 같은 ALPACA 키를 쓴다.

GET https://data.alpaca.markets/v1beta1/news
  symbols=AAPL  start=2018-01-01  end=2019-01-01  limit=50(최대)  sort=desc
  include_content=false (본문 HTML 은 크고 대부분 요약으로 충분해서 받지 않음)
  page_token=<앞 응답의 next_page_token>
응답: {"news": [{"id", "headline", "author", "created_at", "updated_at", "summary", "content", "url",
                 "images", "symbols", "source"}], "next_page_token": "..." 또는 null}
무료 플랜 한도는 분당 200회 → 요청 사이 MIN_INTERVAL_SEC(0.31초), 429 면 쉬었다가 다시.
"""

import time
from datetime import UTC, date, datetime

from backend.adapters.crawlers import config
from backend.adapters.crawlers.common import http_session, strip_html

SOURCE = "ALPACA_NEWS"
URL = "https://data.alpaca.markets/v1beta1/news"
PAGE_LIMIT = 50  # API 최대
MIN_INTERVAL_SEC = 0.31  # 분당 200회 안
RETRY_WAITS = (5.0, 15.0, 60.0)
_session = http_session()
_last_call = 0.0


def _headers() -> dict:
    config.require(
        ALPACA_API_KEY_ID=config.ALPACA_API_KEY_ID,
        ALPACA_API_SECRET_KEY=config.ALPACA_API_SECRET_KEY,
    )
    return {
        "APCA-API-KEY-ID": config.ALPACA_API_KEY_ID,
        "APCA-API-SECRET-KEY": config.ALPACA_API_SECRET_KEY,
    }


def _get(params: dict, sleep=None) -> dict:  # noqa: ANN001
    global _last_call
    sleep = sleep or time.sleep
    for attempt in range(len(RETRY_WAITS) + 1):
        gap = MIN_INTERVAL_SEC - (time.monotonic() - _last_call)
        if gap > 0:
            sleep(gap)
        _last_call = time.monotonic()
        res = _session.get(URL, headers=_headers(), params=params, timeout=30)
        if res.status_code == 429 and attempt < len(RETRY_WAITS):
            sleep(RETRY_WAITS[attempt])
            continue
        if res.status_code in (401, 403):
            raise PermissionError(f"Alpaca News 권한 오류 status={res.status_code}")
        if not res.ok:
            raise RuntimeError(f"Alpaca News 오류 status={res.status_code} body={res.text[:200]}")
        return res.json()
    raise AssertionError("도달하지 않음")


def _iso(v: str | None) -> str | None:
    if not v:
        return None
    dt = datetime.fromisoformat(v.replace("Z", "+00:00"))
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=UTC)
    return dt.astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


def to_row(item: dict) -> dict | None:
    """기사 한 건 → payload 행 (주소·제목 없으면 None)."""
    if not item.get("url") or not item.get("headline"):
        return None
    return {
        "url": item["url"],
        "title": strip_html(item["headline"]),
        "description": strip_html(item.get("summary")) or None,
        "publisher": item.get("source") or item.get("author"),
        "published_at": _iso(item.get("created_at")),
        "language": "en",
    }


def news_rows(symbol: str, start: date, end: date, *, max_pages: int | None = None) -> list[dict]:
    """[start, end) 기사 전부 (next_page_token 을 따라 끝까지, max_pages 를 주면 그만큼만)."""
    params = {
        "symbols": symbol.replace("-", "."),
        "start": start.isoformat(),
        "end": end.isoformat(),
        "limit": PAGE_LIMIT,
        "sort": "desc",
        "include_content": "false",
    }
    rows: list[dict] = []
    token = None
    pages = 0
    while True:
        payload = _get({**params, "page_token": token} if token else params)
        rows += [r for item in payload.get("news") or [] if (r := to_row(item))]
        pages += 1
        token = payload.get("next_page_token")
        if not token or (max_pages is not None and pages >= max_pages):
            return rows
