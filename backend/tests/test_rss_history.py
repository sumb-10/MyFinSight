"""국내 Google RSS 과거 백필: 옛 사명 검색, 기사 적은 종목의 분기 묶음."""

from __future__ import annotations

from datetime import date

from backend.collectors.news import backfill as nb


def test_former_names_file_and_name_in() -> None:
    former = nb.load_former_names()
    assert ("하이닉스", date(2012, 3, 26)) in former["000660"]
    assert nb.name_in("SK하이닉스", "000660.KS", date(2010, 6, 1), former) == "하이닉스"
    assert nb.name_in("SK하이닉스", "000660.KS", date(2012, 4, 1), former) == "SK하이닉스"
    # 두 번 바뀐 종목: 가장 이른 이름부터
    assert nb.name_in("HD한국조선해양", "009540.KS", date(2015, 1, 1), former) == "현대중공업"
    assert nb.name_in("HD한국조선해양", "009540.KS", date(2020, 1, 1), former) == "한국조선해양"
    assert nb.name_in("삼성전자", "005930.KS", date(2005, 1, 1), former) == "삼성전자"


def test_rss_window_quarters_for_sparse_kr_before_2011() -> None:
    sparse = {"001680.KS"}
    jun, jul = date(2010, 6, 1), date(2010, 7, 1)
    apr = date(2010, 4, 1)
    assert nb.rss_window("GOOGLE_RSS_KR", "001680.KS", jun, jul, sparse) is None  # 분기 첫 달만
    assert nb.rss_window("GOOGLE_RSS_KR", "001680.KS", apr, date(2010, 5, 1), sparse) == (
        apr, jul,
    )  # fmt: skip
    assert nb.rss_window("GOOGLE_RSS_KR", "005930.KS", jun, jul, sparse) == (jun, jul)  # 대형주
    assert nb.rss_window("GOOGLE_RSS_KR", "001680.KS", date(2012, 5, 1), date(2012, 6, 1),
                         sparse) == (date(2012, 5, 1), date(2012, 6, 1))  # fmt: skip
    assert nb.add_months(date(2010, 11, 1), 3) == date(2011, 2, 1)
