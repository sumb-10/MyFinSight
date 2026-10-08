"""[정성] 네이버 뉴스 검색.

NAVER_API=hub        → NAVER API HUB (ncloud, https://naverapihub.apigw.ntruss.com/search/v1/news)
NAVER_API=developers → 기존 developers.naver.com 검색 API (https://openapi.naver.com/v1/search/news.json)
두 방식은 발급 키가 서로 다르므로 .env의 NAVER_CLIENT_ID/SECRET을 해당 콘솔에서 받은 값으로 넣어야 함.
"""

from myfinsight.data.crawlers import config
from myfinsight.data.crawlers.common import http_session, rfc822, strip_html

SOURCE = "NAVER_NEWS"
_session = http_session()


def search(query: str, display: int = 100, sort: str = "date") -> list[dict]:
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
        params={"query": query, "display": display, "start": 1, "sort": sort},
    )
    if not res.ok:
        raise RuntimeError(
            f"네이버 API 오류 status={res.status_code} ({config.NAVER_API}) body={res.text[:200]}"
        )
    return res.json().get("items", [])


def news_rows(query: str) -> list[dict]:
    """명세 payload 행 목록. 원본 collect() 의 행 만들기 부분 (DB 저장은 뺐다)."""
    rows = []
    for it in search(query):
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
