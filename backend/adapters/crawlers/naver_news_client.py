"""[정성] 네이버 뉴스 검색.

NAVER_API=hub        → NAVER API HUB (ncloud, https://naverapihub.apigw.ntruss.com/search/v1/news)
NAVER_API=developers → 기존 developers.naver.com 검색 API (https://openapi.naver.com/v1/search/news.json)
두 방식은 발급 키가 서로 다르므로 .env의 NAVER_CLIENT_ID/SECRET을 해당 콘솔에서 받은 값으로 넣어야 함.

검색 API 는 날짜로 거를 수 없고 start ≤ 1000, display ≤ 100 이 한계다. 백필(news_rows_all)은
최신순(sort=date)으로 start=1, 101, …, 901 열 쪽(최대 1000건)을 받는다. 기사가 많은 종목은
1000건이 며칠치일 수 있어 오래된 기사는 Google News RSS 백필로 채운다.
"""

from backend.adapters.crawlers import config
from backend.adapters.crawlers.common import http_session, rfc822, strip_html

SOURCE = "NAVER_NEWS"
_session = http_session()


MAX_START = 1000  # API 한계 (start 1~1000)
PAGE = 100  # API 한계 (display 10~100)


def search(query: str, display: int = 100, sort: str = "date", start: int = 1) -> list[dict]:
    config.require(
        NAVER_CLIENT_ID=config.NAVER_CLIENT_ID, NAVER_CLIENT_SECRET=config.NAVER_CLIENT_SECRET
    )
    if config.NAVER_API == "developers":
        url = "https://openapi.naver.com/v1/search/news.json"
        headers = {
            "X-Naver-Client-Id": config.NAVER_CLIENT_ID,
            "X-Naver-Client-Secret": config.NAVER_CLIENT_SECRET,
        }
    else:
        url = "https://naverapihub.apigw.ntruss.com/search/v1/news"
        headers = {
            "X-NCP-APIGW-API-KEY-ID": config.NAVER_CLIENT_ID,
            "X-NCP-APIGW-API-KEY": config.NAVER_CLIENT_SECRET,
        }
    res = _session.get(
        url,
        headers=headers,
        timeout=20,
        params={"query": query, "display": display, "start": start, "sort": sort},
    )
    if not res.ok:
        raise RuntimeError(
            f"네이버 API 오류 status={res.status_code} ({config.NAVER_API}) body={res.text[:200]}"
        )
    return res.json().get("items", [])


def page_starts(max_start: int = MAX_START, page: int = PAGE) -> list[int]:
    """백필에서 부를 start 값들: 1, 101, …, 901 (start 가 max_start 를 넘지 않게)."""
    return list(range(1, min(max_start, MAX_START) + 1, page))


def news_rows_all(query: str, max_start: int = MAX_START) -> list[dict]:
    """최신순으로 쪽을 넘기며 API 한계(1000건)까지. 쪽이 덜 차면 거기서 멈춘다."""
    rows: list[dict] = []
    for start in page_starts(max_start):
        items = search(query, display=PAGE, start=start)
        rows += _rows(items)
        if len(items) < PAGE:
            break
    return rows


def news_rows(query: str) -> list[dict]:
    """명세 payload 행 목록. 원본 collect() 의 행 만들기 부분 (DB 저장은 뺐다)."""
    return _rows(search(query))


def _rows(items: list[dict]) -> list[dict]:
    rows = []
    for it in items:
        url = it.get("originallink") or it.get("link")
        title = strip_html(it.get("title"))
        if url and title:
            published = rfc822(it.get("pubDate"))
            rows.append(
                {
                    "url": url,
                    "title": title,
                    "description": strip_html(it.get("description")),
                    "publisher": None,
                    "published_at": published.strftime("%Y-%m-%dT%H:%M:%SZ") if published else None,
                    "language": "ko",
                }
            )
    return rows
