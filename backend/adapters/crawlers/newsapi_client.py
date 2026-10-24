"""[정성] NewsAPI.org everything 검색. 한국어 미지원 → 영문 검색어로 사용.

무료(Developer) 플랜: 최근 약 1개월 기사만, 하루 100회, 검색 한 번에 최대 100건(pageSize 100, 1쪽).
그보다 오래된 기사는 유료 플랜이 있어야 한다. 백필은 종목마다 최근 29일을 pageSize 100 으로 한 번.
"""

from datetime import UTC, datetime, timedelta

from backend.adapters.crawlers import config
from backend.adapters.crawlers.common import http_session, strip_html

SOURCE = "NEWSAPI"
_session = http_session()


def search(query: str, days: int = 14, language: str = "en", page_size: int = 50) -> list[dict]:
    config.require(NEWSAPI_KEY=config.NEWSAPI_KEY)
    res = _session.get(
        "https://newsapi.org/v2/everything",
        timeout=20,
        headers={"X-Api-Key": config.NEWSAPI_KEY},
        params={
            "q": query,
            "language": language,
            "sortBy": "publishedAt",
            "pageSize": page_size,
            "from": (datetime.now(UTC) - timedelta(days=days)).strftime("%Y-%m-%d"),
        },
    )
    payload = res.json()
    if payload.get("status") != "ok":
        raise RuntimeError(f"NewsAPI 오류 [{payload.get('code')}] {payload.get('message')}")
    return payload.get("articles", [])


def news_rows(query: str, days: int = 14, language: str = "en", page_size: int = 50) -> list[dict]:
    """명세 payload 행 목록. 원본 collect() 의 행 만들기 부분 (DB 저장은 뺐다)."""
    rows = []
    for a in search(query, days=days, language=language, page_size=page_size):
        if not (a.get("url") and a.get("title")) or a["title"] == "[Removed]":
            continue
        published = None
        if a.get("publishedAt"):
            dt = datetime.fromisoformat(a["publishedAt"].replace("Z", "+00:00")).astimezone(UTC)
            published = dt.strftime("%Y-%m-%dT%H:%M:%SZ")
        rows.append(
            {
                "url": a["url"],
                "title": strip_html(a.get("title")),
                "description": strip_html(a.get("description") or a.get("content")),
                "publisher": (a.get("source") or {}).get("name"),
                "published_at": published,
                "language": language,
            }
        )
    return rows
