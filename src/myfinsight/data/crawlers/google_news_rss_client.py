"""[정성] Google News RSS 검색 (키 불필요)."""

from xml.etree import ElementTree

from myfinsight.data.crawlers.common import http_session, rfc822, strip_html

SOURCE = "GOOGLE_RSS"
_session = http_session()


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


def search(query: str, lang: str = "ko", country: str = "KR", days: int = 14) -> list[dict]:
    res = _session.get(
        "https://news.google.com/rss/search",
        timeout=20,
        params={
            "q": f"{query} when:{days}d",
            "hl": lang,
            "gl": country,
            "ceid": f"{country}:{lang}",
        },
    )
    res.raise_for_status()
    return parse(res.content)


def news_rows(
    query: str, lang: str = "ko", country: str = "KR", days: int = 14, limit: int = 40
) -> list[dict]:
    """명세 payload 행 목록. 원본 collect() 의 행 만들기 부분 (DB 저장은 뺐다)."""
    rows = []
    for it in search(query, lang, country, days)[:limit]:
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
