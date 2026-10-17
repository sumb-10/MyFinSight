"""뉴스 사실 표시 규칙 (pipeline/news_labels.py)과 저장할 때 채우기·첫 보도 (upsert_news)."""

from __future__ import annotations

from datetime import UTC, date, datetime

from sqlalchemy import select

from backend.db import open_repository
from backend.db import tables as T
from backend.pipeline import news_labels as L
from backend.schemas.market_ext import AssetInfo, NewsRow

SAMSUNG = L.AssetNames("KR-005930", "KR", "005930", "삼성전자")
APPLE = L.AssetNames("US-AAPL", "US", "AAPL", "Apple Inc.")
AGILENT = L.AssetNames("US-A", "US", "A", "Agilent Technologies")
ATT = L.AssetNames("US-T", "US", "T", "AT&T")


def test_press_release() -> None:
    assert L.is_press_release("Samsung Global Newsroom", None, SAMSUNG)
    assert L.is_press_release("samsung.com", None, SAMSUNG)  # 한글 이름이라 도메인 이름표로
    assert L.is_press_release(None, "https://news.samsung.com/kr/123", SAMSUNG)
    assert L.is_press_release("PR Newswire", None, APPLE)
    assert L.is_press_release(None, "https://www.businesswire.com/news/x", APPLE)
    assert L.is_press_release("뉴스와이어", None, SAMSUNG)
    assert not L.is_press_release("연합뉴스", "https://www.yna.co.kr/view/1", SAMSUNG)
    assert not L.is_press_release("Yahoo Finance", None, APPLE)
    assert not L.is_press_release("GeekWire", None, APPLE)  # wire 가 들어 있어도 언론사


def test_title_has_name() -> None:
    assert L.title_has_name("SK하이닉스·삼성전자 거래대금 28조원", SAMSUNG)
    assert not L.title_has_name("반도체가 이끈 집값 상승, 서울도 밀어 올릴까?", SAMSUNG)
    assert L.title_has_name("NVIDIA (NVDA) vs. Apple (AAPL): Which Stock Wins", APPLE)
    assert L.title_has_name("Evercore Maintains Outperform on Apple", APPLE)
    assert L.title_has_name("Agilent beats estimates", AGILENT)  # 첫 단어 (흔한 단어 아님)
    assert not L.title_has_name("DigiCert TLM Records 38% Annual Revenue Growth", AGILENT)
    assert not L.title_has_name("A new chip arrives", AGILENT)  # 한 글자 티커는 그냥 단어로 안 봄
    assert L.title_has_name("SpaceX Takes On AT&T", ATT)
    assert L.core_name("(주)삼성전자") == "삼성전자" and L.core_name("Apple Inc.") == "Apple"


def test_story_key_and_available_on() -> None:
    a = L.normalize_title("[단독] 삼성전자, 3Q 영업익 신기록 - 연합뉴스", "연합뉴스")
    b = L.normalize_title("삼성전자, 3Q 영업익 신기록...")
    assert a == b == "삼성전자3q영업익신기록"
    at = datetime(2026, 10, 8, 1, 0, tzinfo=UTC)
    s1 = L.story_id("KR-005930", "[단독] 삼성전자, 3Q 영업익 신기록 - 연합뉴스", "연합뉴스", at, "KR")
    s2 = L.story_id("KR-005930", "삼성전자, 3Q 영업익 신기록...", None, at, "KR")
    other_day = L.story_id("KR-005930", "삼성전자, 3Q 영업익 신기록", None,
                           datetime(2026, 10, 9, 1, 0, tzinfo=UTC), "KR")  # fmt: skip
    assert s1 == s2 != other_day
    # 장 시작 전(현지)이면 그날, 아니면 다음 평일 (주말 건너뜀)
    assert L.available_on(datetime(2026, 10, 13, 13, 0, tzinfo=UTC), "US") == date(2026, 10, 13)
    assert L.available_on(datetime(2026, 10, 13, 14, 0, tzinfo=UTC), "US") == date(2026, 10, 14)
    assert L.available_on(datetime(2026, 10, 9, 23, 0, tzinfo=UTC), "KR") == date(2026, 10, 12)
    assert L.available_on(datetime(2026, 10, 12, 23, 30, tzinfo=UTC), "KR") == date(2026, 10, 13)
    # 날짜만 있는 Google RSS (태평양 자정 = UTC 07:00): 그날 끝에 나왔다고 봄
    rss = datetime(2026, 10, 13, 7, 0, tzinfo=UTC)  # 태평양 10-13
    assert L.available_on(rss, "US") == date(2026, 10, 13)  # 시각 모르면 원래는 그날이지만
    assert L.available_on(rss, "US", "GOOGLE_RSS") == date(2026, 10, 14)  # 태평양 23:59 → 다음 날
    assert L.available_on(rss, "KR", "GOOGLE_RSS") == date(2026, 10, 15)  # 서울 10-14 15:59 → 장중
    assert L.available_on(datetime(2015, 3, 2, tzinfo=UTC), "US", "FNSPID") == date(2015, 3, 3)
    assert L.title_has_name("네이버, 3분기 실적 발표", L.AssetNames("KR-035420", "KR", "035420", "NAVER"))


def _news(url: str, title: str, hour: int, publisher: str | None = None) -> NewsRow:
    return NewsRow(
        asset_id="KR-005930", source="NAVER_NEWS", url=url, title=title, publisher=publisher,
        published_at=datetime(2026, 10, 8, hour, 0, tzinfo=UTC), query="삼성전자",
        fetched_at=datetime(2026, 10, 9, tzinfo=UTC),
    )  # fmt: skip


def test_upsert_fills_labels_and_first_report() -> None:
    repo = open_repository("sqlite://")
    repo.upsert_assets([AssetInfo(
        asset_id="KR-005930", ticker="005930", name="삼성전자", market="KR", currency="KRW",
        yfinance_symbol="005930.KS",
    )])  # fmt: skip
    later = _news("https://b/1", "삼성전자, 3Q 영업익 신기록...", 5)
    repo.upsert_news([later, _news("https://c/1", "평택시 방위산업 육성", 6)])
    earlier = _news("https://a/1", "[속보] 삼성전자, 3Q 영업익 신기록 - 뉴시스", 2, "뉴시스")
    repo.upsert_news([earlier])
    n = T.news
    with repo.engine.connect() as c:
        rows = {r.url: r for r in c.execute(select(n).order_by(n.c.url))}
    assert rows["https://a/1"].story_id == rows["https://b/1"].story_id
    assert rows["https://a/1"].is_first_report is True
    assert rows["https://b/1"].is_first_report is False  # 나중에 더 이른 기사가 들어와 바뀜
    assert rows["https://c/1"].is_first_report is True
    assert rows["https://c/1"].title_has_name is False and rows["https://b/1"].title_has_name
    assert rows["https://a/1"].available_on == date(2026, 10, 9)  # 서울 11:00 (장중) → 다음 평일
