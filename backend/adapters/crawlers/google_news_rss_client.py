"""[정성] Google News RSS 검색 (키 불필요).

- 매일 수집: "<검색어> when:Nd" (최근 N일)
- 백필: "<검색어> after:YYYY-MM-DD before:YYYY-MM-DD" (달마다 한 번, window_rows). 한 번에 최대 100건
  안팎이 오므로 기간을 한 달로 잘라 10년치를 모은다. 요청 간격(interval, 기본 NEWS_RSS_INTERVAL_SEC
  = 1.5초)을 지키고, 429·503 이 오면 RETRY_WAITS 만큼 쉬었다가 다시 부르며, 그래도 안 되면
  RateLimited 를 던진다 (부르는 쪽이 이번 실행에서 그 줄을 멈춤).
"""

import time
from datetime import date
from xml.etree import ElementTree

from backend.adapters.crawlers.common import http_session, rfc822, strip_html

SOURCE = "GOOGLE_RSS"
URL = "https://news.google.com/rss/search"
RETRY_WAITS = (30.0, 60.0, 120.0, 300.0)
"""429·503 때 쉬는 시간(초), 점점 길게. 다 쓰면 RateLimited."""
_session = http_session()
_last_call = 0.0


class RateLimited(RuntimeError):
    """Google 이 계속 요청을 막음 (429·503). 한참 뒤에 다시 돌려야 함."""


def parse(content: bytes) -> list[dict]:
    """RSS XML → 기사 목록 (제목 끝 " - 언론사" 제거)."""
    items = []
    for item in ElementTree.fromstring(content).iter("item"):
        link, title = item.findtext("link"), item.findtext("title")
        if not link or not title:
            continue
        publisher = item.findtext("source")
        if publisher and title.endswith(f" - {publisher}"):  # 제목 끝 " - 언론사" 제거
            title = title[: -len(publisher) - 3]
        items.append(
            {
                "link": link,
                "title": title,
                "description": item.findtext("description"),
                "publisher": publisher,
                "pubDate": item.findtext("pubDate"),
            }
        )
    return items


def _request(params: dict, *, interval: float = 0.0, waits=RETRY_WAITS, sleep=None):  # noqa: ANN001
    """요청 간격을 지켜 부르고, 429·503 이면 waits 대로 쉬었다가 다시. 끝내 막히면 RateLimited."""
    global _last_call
    sleep = sleep or time.sleep
    for attempt in range(len(waits) + 1):
        gap = interval - (time.monotonic() - _last_call)
        if gap > 0:
            sleep(gap)
        _last_call = time.monotonic()
        res = _session.get(URL, timeout=20, params=params)
        if res.status_code in (429, 503):
            if attempt == len(waits):
                raise RateLimited(f"Google News RSS status={res.status_code} (잠시 뒤 다시 실행)")
            sleep(waits[attempt])
            continue
        res.raise_for_status()
        return res
    raise AssertionError("도달하지 않음")


def _params(q: str, lang: str, country: str) -> dict:
    return {"q": q, "hl": lang, "gl": country, "ceid": f"{country}:{lang}"}


def search(query: str, lang: str = "ko", country: str = "KR", days: int = 14) -> list[dict]:
    res = _request(_params(f"{query} when:{days}d", lang, country), waits=(5.0,))
    return parse(res.content)


def window_query(query: str, after: date, before: date) -> str:
    """기간 검색어: '삼성전자 after:2018-03-01 before:2018-04-01'."""
    return f"{query} after:{after.isoformat()} before:{before.isoformat()}"


def _rows(items: list[dict], lang: str) -> list[dict]:
    rows = []
    for it in items:
        published = rfc822(it["pubDate"])
        rows.append(
            {
                "url": it["link"],
                "title": strip_html(it["title"]),
                "description": strip_html(it["description"]),
                "publisher": it["publisher"],
                "published_at": published.strftime("%Y-%m-%dT%H:%M:%SZ") if published else None,
                "language": lang,
            }
        )
    return rows


def news_rows(
    query: str, lang: str = "ko", country: str = "KR", days: int = 14, limit: int = 40
) -> list[dict]:
    """명세 payload 행 목록. 원본 collect() 의 행 만들기 부분 (DB 저장은 뺐다)."""
    return _rows(search(query, lang, country, days)[:limit], lang)


def window_rows(
    query: str,
    after: date,
    before: date,
    lang: str = "ko",
    country: str = "KR",
    *,
    interval: float = 1.5,
    waits=RETRY_WAITS,  # noqa: ANN001
) -> list[dict]:
    """[after, before) 기간 기사 전부 (백필용, 개수 제한 없음)."""
    res = _request(
        _params(window_query(query, after, before), lang, country), interval=interval, waits=waits
    )
    return _rows(parse(res.content), lang)
