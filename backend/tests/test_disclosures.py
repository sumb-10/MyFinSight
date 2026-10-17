"""공시 수집 (collectors/disclosures): 유형 규칙(옛·새 8-K item, DART 이름), available_on,
SEC·DART 첫 수집 이어 받기·한도에서 멈춤, 매일 갱신, 크롤러 쪽 넘기기.

네트워크 없이: 크롤러는 StubSession, 수집은 스텁 함수와 인메모리 SQLite.
"""

from __future__ import annotations

from datetime import UTC, date, datetime, timedelta
from typing import Any

import pytest
from helpers import AT
from stub_http import StubResponse, StubSession

from backend.adapters.crawlers import dart_client, edgar_client
from backend.adapters.crawlers.dart_client import DartLimitError
from backend.collectors.common import Forever, JobSettings
from backend.collectors.disclosures import categories as cat
from backend.collectors.disclosures.backfill import dart_backfill, sec_backfill
from backend.collectors.disclosures.update import (
    dart_rows,
    disclosure_update,
    sec_rows,
    sec_times,
)
from backend.db import SqlRepository, open_repository
from backend.db import tables as T
from backend.jobs.backfill import BackfillOptions, run_backfill

TODAY = date(2026, 10, 14)


@pytest.fixture
def repo() -> SqlRepository:
    return open_repository("sqlite://", clock=lambda: AT)


def _settings(tickers: dict[str, str]) -> JobSettings:
    return JobSettings(indices=[], benchmarks=[], extra_tickers=dict(tickers))


def _rows(repo: SqlRepository) -> list[Any]:
    with repo.engine.connect() as c:
        return list(c.execute(T.disclosures.select().order_by(T.disclosures.c.filing_id)))


# ---------------------------------------------------------------- 유형 규칙
def test_sec_new_and_old_8k_items() -> None:
    new = date(2010, 5, 1)
    assert cat.sec_event("8-K", "2.02,9.01", new) == ("earnings", "sec-v1")
    assert cat.sec_event("8-K", "5.02,8.01", new)[0] == "executive_change"
    assert cat.sec_event("8-K", "9.01", new)[0] == "exhibits_only"
    assert cat.sec_event("8-K/A", "4.02", new)[0] == "restatement"
    old = date(2003, 6, 1)
    assert cat.sec_event("8-K", "12,7", old) == ("earnings", "sec-old-v1")
    assert cat.sec_event("8-K", "5", old)[0] == "other_event"
    assert cat.sec_event("8-K", "9", old)[0] == "reg_fd"
    assert cat.sec_event("8-K", "", old)[0] == "current_report"  # 옛 공시는 item 이 비기도 함
    assert cat.sec_event("10-K405", None, old) == ("annual_report", "sec-v1")
    assert cat.sec_keep("10-Q/A") and cat.sec_keep("SC 13G") and not cat.sec_keep("4")
    assert not cat.sec_keep("424B2") and not cat.sec_keep("FWP")


def test_dart_names() -> None:
    assert cat.dart_form("[기재정정]사업보고서 (2023.12)") == ("사업보고서", True)
    assert cat.dart_form("[첨부추가]주요사항보고서(유상증자결정)") == (
        "주요사항보고서(유상증자결정)",
        False,
    )
    assert cat.dart_event("사업보고서 (2023.12)")[0] == "annual_report"
    assert cat.dart_event("연결재무제표기준영업(잠정)실적(공정공시)")[0] == "earnings"
    assert cat.dart_event("주요사항보고서(자기주식취득결정)")[0] == "buyback"
    assert cat.dart_event("현금ㆍ현물배당결정")[0] == "dividend"
    assert cat.dart_event("단일판매ㆍ공급계약체결")[0] == "material_agreement"
    assert cat.dart_event("최대주주변경")[0] == "control_change"
    assert cat.dart_event("투자설명서(일괄신고)") == ("derivative_offering", "dart-v2")
    assert (
        cat.dart_event("증권발행실적보고서[파생결합증권(주가연계증권)]")[0] == "derivative_offering"
    )
    assert cat.dart_event("투자설명서[일괄신고-사채]")[0] == "offering_document"
    assert cat.dart_event("증권발행실적보고서")[0] == "offering_document"
    assert cat.dart_event("증권신고서(채무증권)")[0] == "securities_offering"
    assert cat.dart_event("주요사항보고서(전환사채권발행결정)")[0] == "securities_offering"
    assert cat.dart_event("기업설명회(IR)개최(안내공시)")[0] == "investor_relations"
    assert cat.dart_event("특수관계인으로부터기타유가증권매수")[0] == "related_party"
    assert cat.dart_event("최대주주등소유주식변동신고서")[0] == "major_holder"
    assert cat.dart_event("공정거래자율준수프로그램운영현황(안내공시)")[0] == "other"
    assert not cat.dart_keep("임원ㆍ주요주주특정증권등소유상황보고서")
    assert cat.dart_keep("주식등의대량보유상황보고서(일반)")


def test_available_on_rules() -> None:
    # 동부 08:15 접수 (평일) → 그날, 16:30 접수 → 다음 평일, 금요일 저녁 → 월요일
    pre = {"filingDate": "2024-01-31", "acceptanceDateTime": "2024-01-31T08:15:00.000Z"}
    at, usable = sec_times(pre)
    assert usable == date(2024, 1, 31) and at == datetime(2024, 1, 31, 13, 15, tzinfo=UTC)
    assert sec_times({**pre, "acceptanceDateTime": "2024-01-31T16:30:00.000Z"})[1] == date(
        2024, 2, 1
    )
    fri = {"filingDate": "2024-02-02", "acceptanceDateTime": "2024-02-02T18:00:00.000Z"}
    assert sec_times(fri)[1] == date(2024, 2, 5)
    assert sec_times({"filingDate": "2001-03-02", "acceptanceDateTime": ""})[1] == date(2001, 3, 5)
    rows = dart_rows("005930.KS", [_dart("20240202000123", "20240202", "현금ㆍ현물배당결정")], AT)
    assert rows[0].available_on == date(2024, 2, 5)  # 날짜만 있어 다음 평일
    assert rows[0].filed_at == datetime(2024, 2, 1, 15, 0, tzinfo=UTC)  # 2월 2일 0시 KST


def _sec(acc: str, day: str, form: str = "8-K", items: str = "2.02,9.01") -> dict[str, Any]:
    return {
        "accessionNumber": acc,
        "filingDate": day,
        "acceptanceDateTime": f"{day}T16:05:00.000Z",
        "form": form,
        "items": items,
        "primaryDocument": "a8k.htm",
        "primaryDocDescription": "8-K",
    }


def _dart(no: str, day: str, name: str) -> dict[str, Any]:
    return {"rcept_no": no, "rcept_dt": day, "report_nm": name, "corp_name": "삼성전자"}


def test_sec_rows_filter_and_url() -> None:
    rows = sec_rows(
        "AAPL",
        320193,
        [_sec("0000320193-24-000001", "2024-02-01"), _sec("0000320193-24-000002", "2024-02-01",
                                                          form="4", items="")],
        AT,
    )  # fmt: skip
    assert len(rows) == 1 and rows[0].asset_id == "US-AAPL" and rows[0].event_type == "earnings"
    assert rows[0].url.endswith("/320193/000032019324000001/a8k.htm")


# ---------------------------------------------------------------- 첫 수집
class SecStub:
    def __init__(self) -> None:
        self.calls: list[tuple[str, date | None]] = []

    def __call__(self, ticker: str, since: date | None) -> tuple[int, list[dict[str, Any]]]:
        self.calls.append((ticker, since))
        if ticker == "BAD":
            raise RuntimeError("SEC 티커 목록에 BAD가 없음")
        return 1, [_sec(f"{ticker}-1", "2001-05-01", items="5"), _sec(f"{ticker}-2", "2024-05-01")]


class DartStub:
    def __init__(self, stop_at: int | None = None) -> None:
        self.calls: list[tuple[str, int]] = []
        self.stop_at = stop_at

    def __call__(self, code: str, start: date, end: date) -> list[dict[str, Any]]:
        if self.stop_at is not None and len(self.calls) >= self.stop_at:
            raise DartLimitError("DART [020] 요청 제한 초과")
        self.calls.append((code, start.year))
        return [_dart(f"{start.year}{code}", f"{start.year}0315", "사업보고서 (2023.12)")]


def test_sec_backfill_once_per_ticker(repo: SqlRepository) -> None:
    s = _settings({"AAPL": "Apple", "BAD": "Bad"})
    fetch = SecStub()
    r = sec_backfill(repo, s, fetch=fetch, today=TODAY, start_year=2000, deadline=Forever())
    assert fetch.calls == [("AAPL", date(2000, 1, 1)), ("BAD", date(2000, 1, 1))]
    assert r.counts["SEC_EDGAR_rows"] == 2 and "disclosures_backfill:BAD" in r.failed
    rows = _rows(repo)
    assert [x.rule_version for x in rows] == ["sec-old-v1", "sec-v1"]
    assert [x.event_type for x in rows] == ["other_event", "earnings"]
    sec_backfill(repo, s, fetch=fetch, today=TODAY, start_year=2000, deadline=Forever())
    assert [c[0] for c in fetch.calls[2:]] == ["BAD"]  # 성공한 종목은 다시 안 받음


def test_dart_backfill_years_resume_and_limit(repo: SqlRepository) -> None:
    s = _settings({"005930.KS": "삼성전자", "000660.KS": "SK하이닉스"})
    fetch = DartStub(stop_at=3)
    kw = {"today": TODAY, "start_year": 2024, "deadline": Forever()}
    r = dart_backfill(repo, s, fetch=fetch, **kw)
    assert not r.done and "DART 멈춤" in r.notes[0]
    # 올해부터, 같은 해를 모든 종목에 대해 끝낸 뒤 전 해로
    assert fetch.calls == [("005930", 2026), ("000660", 2026), ("005930", 2025)]
    fetch.stop_at = None
    r2 = dart_backfill(repo, s, fetch=fetch, **kw)
    assert r2.done
    # 올해는 매번 다시, 지난 해는 끝난 것 건너뜀
    assert fetch.calls[3:] == [("005930", 2026), ("000660", 2026), ("000660", 2025),
                               ("005930", 2024), ("000660", 2024)]  # fmt: skip
    assert len(_rows(repo)) == 6 and all(x.event_type == "annual_report" for x in _rows(repo))


def test_run_backfill_disclosures_step(repo: SqlRepository) -> None:
    s = _settings({"AAPL": "Apple", "005930.KS": "삼성전자"})
    opts = BackfillOptions(what=("disclosures",), disclosure_from=2026)
    sec, dart = SecStub(), DartStub()
    said: list[str] = []
    rep = run_backfill(repo, s, opts, adapters={"disclosures": {"SEC_EDGAR": sec, "DART": dart}},
                       today=TODAY, progress=said.append)  # fmt: skip
    assert [r.name for r in rep.results] == [
        "disclosures_backfill:SEC_EDGAR",
        "disclosures_backfill:DART",
    ]
    assert sec.calls == [("AAPL", date(2026, 1, 1))] and dart.calls == [("005930", 2026)]
    assert any("공시: 2026년부터" in m for m in said)


def test_daily_update_once_a_day(repo: SqlRepository) -> None:
    s = _settings({"AAPL": "Apple", "005930.KS": "삼성전자"})
    sec, dart = SecStub(), DartStub()
    r = disclosure_update(repo, s, sec_fetch=sec, dart_fetch=dart, today=TODAY)
    assert sec.calls == [("AAPL", date(2026, 9, 30))] and dart.calls == [("005930", 2026)]
    assert r.counts["SEC_EDGAR_rows"] == 2 and r.counts["DART_rows"] == 1
    disclosure_update(repo, s, sec_fetch=sec, dart_fetch=dart, today=TODAY)
    assert len(sec.calls) == 1  # 오늘 이미 받음
    # 수집 기록 시각은 실제 시계라서, 다음 날은 실행하는 날 기준으로 잡음
    next_day = max(TODAY, date.today()) + timedelta(days=1)
    again = disclosure_update(repo, s, sec_fetch=sec, dart_fetch=None, today=next_day)
    assert len(sec.calls) == 2 and again.counts["SEC_EDGAR_rows"] == 0  # 같은 공시는 안 바뀜


# ---------------------------------------------------------------- 크롤러
def _seq(*responses: StubResponse) -> StubSession:
    left = list(responses)
    return StubSession(lambda _url, _kw: left.pop(0))


def test_dart_list_pages(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("DART_API_KEY", "k")
    monkeypatch.setattr(dart_client, "MIN_INTERVAL_SEC", 0)
    pages = [
        {"status": "000", "total_page": 2, "list": [{"rcept_no": "1"}]},
        {"status": "000", "total_page": 2, "list": [{"rcept_no": "2"}]},
    ]
    sess = _seq(*[StubResponse(data=p) for p in pages])
    monkeypatch.setattr(dart_client, "_session", sess)
    got = dart_client.fetch_disclosure_list("00126380", date(2000, 1, 1), date(2000, 12, 31))
    assert [x["rcept_no"] for x in got] == ["1", "2"]
    assert [c[2]["params"]["page_no"] for c in sess.calls] == [1, 2]
    sess = _seq(StubResponse(data={"status": "013", "message": "없음"}))
    monkeypatch.setattr(dart_client, "_session", sess)
    assert dart_client.fetch_disclosure_list("x", date(1998, 1, 1), date(1998, 12, 31)) == []
    sess = _seq(StubResponse(data={"status": "020", "message": "한도"}))
    monkeypatch.setattr(dart_client, "_session", sess)
    with pytest.raises(DartLimitError):
        dart_client.fetch_disclosure_list("x", date(2000, 1, 1), date(2000, 12, 31))


def test_edgar_filings_old_pages(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("SEC_USER_AGENT", "me test@example.com")
    recent = {"accessionNumber": ["a2"], "filingDate": ["2024-01-02"], "form": ["8-K"]}
    main = {"filings": {"recent": recent, "files": [
        {"name": "CIK0000000001-submissions-001.json", "filingTo": "2010-12-31"},
        {"name": "CIK0000000001-submissions-002.json", "filingTo": "1999-12-31"},
    ]}}  # fmt: skip
    old = {"accessionNumber": ["a1"], "filingDate": ["2005-03-01"], "form": ["10-K"]}
    sess = _seq(StubResponse(data=main), StubResponse(data=old))
    monkeypatch.setattr(edgar_client, "_session", sess)
    got = edgar_client.fetch_filings(1, date(2000, 1, 1))
    assert [g["accessionNumber"] for g in got] == ["a2", "a1"]
    assert got[0]["items"] is None  # 없는 필드는 None
    assert len(sess.calls) == 2  # 2000년 전만 담은 쪽 파일은 받지 않음
