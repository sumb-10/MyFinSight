"""분기 재무: SEC EDGAR 분기 값 만들기, DART 3개월·누적·주식 총수·배당, 한도 초과 처리.

응답 모양은 공식 문서 기준으로 만든 고정 예시 (네트워크 없음)
- SEC companyfacts: facts.<taxonomy>.<concept>.units.<unit>[] = {start?, end, val, accn, fy, fp,
  form, filed}
- OpenDART fnlttSinglAcnt / stockTotqySttus / alotMatter: {"status": "000", "list": [...]}
"""

from __future__ import annotations

from datetime import date

import pytest
from helpers import StubKeyedAdapter
from stub_http import StubResponse, StubSession

from backend.adapters.crawlers import dart_client, edgar_client
from backend.adapters.real import DartFinancialAdapter
from backend.collectors.common import JobSettings
from backend.collectors.financials.update import financial_step
from backend.db import open_repository
from backend.db.sql import statement_of
from backend.schemas.errors import DataSourceError
from backend.schemas.market import IndexCode

TODAY = date(2026, 10, 1)


def e(val, start, end, filed, form="10-Q", accn=None):  # noqa: ANN001, ANN201
    out = {"val": val, "end": end, "filed": filed, "form": form, "accn": accn or f"{form}-{filed}"}
    if start:
        out["start"] = start
    return out


def _facts() -> dict:
    """회계연도 = 달력연도. 2024년:
    1분기 3개월 10 (5/1 공시), 2분기 3개월 없음 → 6개월 누적 25 (8/1), 3분기 3개월 12 + 9개월
    누적 37 (11/1), 연간 50 (10-K 2025-02-20) → 4분기 = 50 − 37 = 13.
    2025년 1분기 값은 2025-05-01 에 9, 나중 보고서에서 10 으로 정정됐지만 처음 값 9 를 써야 함.
    """
    ni = [
        e(10, "2024-01-01", "2024-03-31", "2024-05-01"),
        e(25, "2024-01-01", "2024-06-30", "2024-08-01"),
        e(12, "2024-07-01", "2024-09-30", "2024-11-01"),
        e(37, "2024-01-01", "2024-09-30", "2024-11-01"),
        e(50, "2024-01-01", "2024-12-31", "2025-02-20", form="10-K"),
        e(9, "2025-01-01", "2025-03-31", "2025-05-01"),
        e(10, "2025-01-01", "2025-03-31", "2026-05-01"),  # 정정·비교수치 → 무시
        e(99, "2024-01-01", "2024-03-31", "2023-12-01", form="S-1"),  # 등록신고서 → 무시
    ]
    rev_old = [e(100, "2023-01-01", "2023-12-31", "2024-02-20", form="10-K")]  # 예전 개념
    rev_new = [  # 2024년부터 새 개념, 분기만 (9개월 누적 없음) → 4분기 = 연간 − 세 분기
        e(30, "2024-01-01", "2024-03-31", "2024-05-01"),
        e(31, "2024-04-01", "2024-06-30", "2024-08-01"),
        e(32, "2024-07-01", "2024-09-30", "2024-11-01"),
        e(130, "2024-01-01", "2024-12-31", "2025-02-20", form="10-K"),
    ]
    eq = [
        e(400, None, "2023-12-31", "2024-02-20", form="10-K"),
        e(420, None, "2024-03-31", "2024-05-01"),
        e(440, None, "2024-12-31", "2025-02-20", form="10-K"),
    ]
    dps = [
        e(0.25, "2024-01-01", "2024-03-31", "2024-05-01"),
        e(0.5, "2024-01-01", "2024-06-30", "2024-08-01"),
    ]
    dei = [e(1000, None, "2024-04-20", "2024-05-01"), e(990, None, "2024-07-20", "2024-08-01")]
    gaap_shares = [e(1234, None, "2024-03-31", "2024-05-01")]
    return {
        "facts": {
            "us-gaap": {
                "NetIncomeLoss": {"units": {"USD": ni}},
                "SalesRevenueNet": {"units": {"USD": rev_old}},
                "RevenueFromContractWithCustomerExcludingAssessedTax": {"units": {"USD": rev_new}},
                "StockholdersEquity": {"units": {"USD": eq}},
                "CommonStockDividendsPerShareDeclared": {"units": {"USD/shares": dps}},
                "CommonStockSharesOutstanding": {"units": {"shares": gaap_shares}},
            },
            "dei": {"EntityCommonStockSharesOutstanding": {"units": {"shares": dei}}},
        }
    }


def _by(rows: list[dict], metric: str) -> dict[str, dict]:
    return {r["period_end"]: r for r in rows if r["metric"] == metric}


# ---------------------------------------------------------------- SEC EDGAR
def test_us_quarters_from_ytd_and_q4_is_fy_minus_9m() -> None:
    rows = edgar_client.build_rows(_facts(), years=5, today=TODAY)
    q = _by(rows, "당기순이익(분기)")
    assert {k: v["value"] for k, v in q.items()} == {
        "2024-03-31": 10,
        "2024-06-30": 15,  # 6개월 25 − 1분기 10
        "2024-09-30": 12,  # 3개월 값 그대로
        "2024-12-31": 13,  # 연간 50 − 9개월 37
        "2025-03-31": 9,  # 처음 공시된 값 (나중 정정 10 아님)
    }
    assert q["2024-06-30"]["disclosed_at"] == "2024-08-01"
    assert q["2024-12-31"]["disclosed_at"] == "2025-02-20"  # 10-K 제출일
    assert q["2024-12-31"]["report_code"] == "10-K" and q["2024-12-31"]["period"] == "Q2024-12-31"
    assert q["2025-03-31"]["disclosed_at"] == "2025-05-01"  # 첫 제출일
    annual = _by(rows, "당기순이익")
    assert annual["2024-12-31"]["value"] == 50 and annual["2024-12-31"]["period"] == "FY2024"


def test_us_q4_from_three_quarters_and_concept_merge() -> None:
    rows = edgar_client.build_rows(_facts(), years=5, today=TODAY)
    q = _by(rows, "매출액(분기)")
    assert q["2024-12-31"]["value"] == 130 - 30 - 31 - 32
    fy = _by(rows, "매출액")
    # 예전 개념(SalesRevenueNet)의 2023년과 새 개념의 2024년이 한 줄로 이어짐
    assert fy["2023-12-31"]["value"] == 100 and fy["2024-12-31"]["value"] == 130


def test_us_instants_shares_and_dividends() -> None:
    rows = edgar_client.build_rows(_facts(), years=5, today=TODAY)
    eq = _by(rows, "자본총계")
    assert eq["2024-03-31"]["value"] == 420 and eq["2024-03-31"]["period"] == "Q2024-03-31"
    assert any(r["period"] == "FY2024" and r["metric"] == "자본총계" for r in rows)
    shares = _by(rows, "유통주식수")
    # dei 가 있으면 dei 만 (us-gaap 1234 는 섞지 않음)
    assert {k: v["value"] for k, v in shares.items()} == {"2024-04-20": 1000, "2024-07-20": 990}
    assert shares["2024-04-20"]["report_code"] == "DEI"
    dps = _by(rows, "주당배당금(분기)")
    assert dps["2024-06-30"]["value"] == pytest.approx(0.25)
    assert all(statement_of(r["metric"]) in ("IS", "BS", "ETC") for r in rows)


def test_us_gaap_shares_used_when_no_dei() -> None:
    f = _facts()
    del f["facts"]["dei"]
    shares = _by(edgar_client.build_rows(f, years=5, today=TODAY), "유통주식수")
    assert {k: v["value"] for k, v in shares.items()} == {"2024-03-31": 1234}


def test_us_weighted_shares_when_no_share_count() -> None:
    """종류주식 회사: dei·us-gaap 주식수가 둘 다 없으면 가중평균(희석) 주식수, 3개월 값 우선."""
    f = _facts()
    del f["facts"]["dei"]
    del f["facts"]["us-gaap"]["CommonStockSharesOutstanding"]
    wads = "WeightedAverageNumberOfDilutedSharesOutstanding"
    f["facts"]["us-gaap"][wads] = {"units": {"shares": [
        e(500, "2024-01-01", "2024-03-31", "2024-05-01"),
        e(510, "2024-04-01", "2024-06-30", "2024-08-01"),
        e(505, "2024-01-01", "2024-06-30", "2024-08-01"),  # 6개월 → 안 씀
        e(520, "2024-01-01", "2024-12-31", "2025-02-20", form="10-K"),
    ]}}  # fmt: skip
    rows = edgar_client.build_rows(f, years=5, today=TODAY)
    shares = _by(rows, "유통주식수")
    assert {k: v["value"] for k, v in shares.items()} == {
        "2024-03-31": 500, "2024-06-30": 510, "2024-12-31": 520,
    }  # fmt: skip
    assert {v["report_code"] for v in shares.values()} == {"WADS"}
    snap = [r for r in rows if r["metric"] == "발행주식수"]
    assert snap and snap[0]["value"] == 520
    # 다른 종류주식 기준 가중평균 (BRK: A주 환산) 은 비율을 곱함
    brk = _by(edgar_client.build_rows(f, years=5, today=TODAY, ticker="BRK.B"), "유통주식수")
    assert brk["2024-03-31"]["value"] == 500 * 1500


def test_us_stale_dei_falls_back_to_weighted() -> None:
    """dei 가 오래전에 멈춘 회사 (ACN: 2010년 값만): 최근까지 있는 가중평균 주식수를 씀."""
    f = _facts()
    f["facts"]["dei"]["EntityCommonStockSharesOutstanding"]["units"]["shares"] = [
        e(700, None, "2010-03-19", "2010-04-01"),
    ]
    del f["facts"]["us-gaap"]["CommonStockSharesOutstanding"]
    f["facts"]["us-gaap"]["WeightedAverageNumberOfDilutedSharesOutstanding"] = {"units": {
        "shares": [e(630, "2025-04-01", "2025-06-30", "2025-08-01")],
    }}  # fmt: skip
    rows = edgar_client.build_rows(f, years=20, today=TODAY)
    shares = _by(rows, "유통주식수")
    assert {k: v["value"] for k, v in shares.items()} == {"2025-06-30": 630}
    assert [r["value"] for r in rows if r["metric"] == "발행주식수"] == [630]


def test_us_gaap_in_other_currency() -> None:
    """US GAAP 을 EUR 로 낸 회사 (ASML): EUR 값을 읽고 unit=EUR, 섞인 달러 값은 안 씀."""
    f = {"facts": {"us-gaap": {
        "NetIncomeLoss": {"units": {"EUR": [
            e(70, "2024-01-01", "2024-12-31", "2025-02-10", "20-F"),
        ]}},
        "StockholdersEquity": {"units": {"EUR": [
            e(180, None, "2024-12-31", "2025-02-10", "20-F"),
        ]}},
        "EarningsPerShareDiluted": {"units": {
            "EUR/shares": [e(19.2, "2024-01-01", "2024-12-31", "2025-02-10", "20-F")],
            "USD/shares": [e(99, "2024-01-01", "2024-12-31", "2025-02-10", "20-F")],
        }},
    }}}  # fmt: skip
    rows = edgar_client.build_rows(f, years=5, today=TODAY)
    assert _by(rows, "당기순이익")["2024-12-31"]["value"] == 70
    assert _by(rows, "당기순이익")["2024-12-31"]["unit"] == "EUR"
    assert _by(rows, "EPS(희석)")["2024-12-31"]["value"] == pytest.approx(19.2)
    assert {r["unit"] for r in rows} <= {"EUR", "주"}


def test_ifrs_filer_read_with_report_currency() -> None:
    """us-gaap 이 없는 IFRS 신고 회사 (20-F): ifrs-full 개념으로 읽고 단위는 보고 통화 그대로."""
    ifrs = {
        "Revenue": {"units": {"EUR": [e(900, "2024-01-01", "2024-12-31", "2025-02-10", "20-F")]}},
        "ProfitLossAttributableToOwnersOfParent": {"units": {"EUR": [
            e(300, "2023-01-01", "2023-12-31", "2024-02-10", "20-F"),
            e(350, "2024-01-01", "2024-12-31", "2025-02-10", "20-F"),
        ]}},
        "ProfitLoss": {"units": {"EUR": [
            e(999, "2024-01-01", "2024-12-31", "2025-02-10", "20-F"),
        ]}},
        "EquityAttributableToOwnersOfParent": {"units": {"EUR": [
            e(2000, None, "2024-12-31", "2025-02-10", "20-F"),
        ]}},
        "DilutedEarningsPerShare": {"units": {"EUR/shares": [
            e(8.5, "2024-01-01", "2024-12-31", "2025-02-10", "20-F"),
        ]}},
    }  # fmt: skip
    dei = {"EntityCommonStockSharesOutstanding": {"units": {"shares": [
        e(40, None, "2025-01-31", "2025-02-10", "20-F"),
    ]}}}  # fmt: skip
    rows = edgar_client.build_rows({"facts": {"ifrs-full": ifrs, "dei": dei}}, years=5, today=TODAY)
    ni = _by(rows, "당기순이익")
    assert {k: v["value"] for k, v in ni.items()} == {"2023-12-31": 300, "2024-12-31": 350}
    assert ni["2024-12-31"]["unit"] == "EUR"  # 지배주주 순이익 우선, 통화는 EUR 그대로
    assert _by(rows, "매출액")["2024-12-31"]["value"] == 900
    assert _by(rows, "자본총계")["2024-12-31"]["unit"] == "EUR"
    assert _by(rows, "EPS(희석)")["2024-12-31"]["unit"] == "EUR"
    assert _by(rows, "유통주식수")["2025-01-31"]["unit"] == "주"
    assert {r["unit"] for r in rows} <= {"EUR", "주"}


def test_us_gaap_filer_ignores_ifrs_block() -> None:
    f = _facts()
    f["facts"]["ifrs-full"] = {"Revenue": {"units": {"EUR": [
        e(1, "2024-01-01", "2024-12-31", "2025-02-20", "10-K"),
    ]}}}  # fmt: skip
    rows = edgar_client.build_rows(f, years=5, today=TODAY)
    assert {r["unit"] for r in rows} <= {"USD", "주"}
    assert _by(rows, "매출액")["2024-12-31"]["value"] == 130


def test_valuation_inputs_skip_other_currency() -> None:
    """가치평가 입력에서 종목 통화와 다른 통화 단위 재무는 뺌 (주식 수 '주' 는 그대로)."""
    from datetime import UTC, datetime

    from backend.db import tables as T

    repo = open_repository("sqlite://")
    now = datetime.now(UTC)
    with repo.engine.begin() as c:
        c.execute(T.assets.insert().values(
            asset_id="US-ASML", ticker="ASML", market="US", currency="USD",
            yfinance_symbol="ASML", created_at=now, updated_at=now,
        ))  # fmt: skip
        for item, unit in [("당기순이익", "EUR"), ("자본총계", "USD"), ("유통주식수", "주")]:
            c.execute(T.financials.insert().values(
                asset_id="US-ASML", period_end=date(2024, 12, 31), statement="IS", item=item,
                value=1, unit=unit, report_date=date(2025, 2, 10), source="SEC_EDGAR",
                period="FY2024", updated_at=now,
            ))  # fmt: skip
    _prices, fins = repo.valuation_inputs(["US-ASML"], date(2025, 1, 1))
    assert sorted(fins["item"]) == ["유통주식수", "자본총계"]


def test_us_rows_before_cutoff_dropped() -> None:
    rows = edgar_client.build_rows(_facts(), years=1, today=TODAY)
    assert min(r["period_end"] for r in rows if r["report_code"] != "SNAPSHOT") >= "2025-01-01"


def test_statement_mapping_for_new_items() -> None:
    assert statement_of("매출액(분기)") == "IS" and statement_of("당기순이익(누적)") == "IS"
    assert statement_of("EPS(희석·분기)") == "IS" and statement_of("지배주주순이익(분기)") == "IS"
    assert statement_of("자본총계") == "BS"
    for item in (
        "유통주식수",
        "발행주식수",
        "자기주식수",
        "주당배당금",
        "주당배당금(분기)",
        "주식분할",
    ):
        assert statement_of(item) == "ETC"


# ---------------------------------------------------------------- DART
def _acct(rcept: str, year: int, rc: str, name: str, amount: str, dt: str, add: str | None = None,
          fs_div: str = "CFS", sj: str = "IS") -> dict:  # fmt: skip
    r = {"rcept_no": rcept, "bsns_year": str(year), "reprt_code": rc, "fs_div": fs_div,
         "sj_div": sj, "account_nm": name, "thstrm_dt": dt, "thstrm_amount": amount,
         "currency": "KRW"}  # fmt: skip
    if add is not None:
        r["thstrm_add_amount"] = add
    return r


def _dart_handler(fnltt: dict, shares: dict | None = None, divs: dict | None = None):  # noqa: ANN202
    def handler(url: str, kw: dict) -> StubResponse:
        p = kw["params"]
        key = (p["bsns_year"], p["reprt_code"])
        table = fnltt if "fnlttSinglAcnt" in url else shares if "stockTotqy" in url else divs
        items = (table or {}).get(key)
        if items is None:
            return StubResponse(200, {"status": "013", "message": "조회된 데이타가 없습니다."})
        return StubResponse(200, {"status": "000", "message": "정상", "list": items})

    return handler


def _stub_dart(monkeypatch: pytest.MonkeyPatch, handler) -> StubSession:  # noqa: ANN001
    monkeypatch.setenv("DART_API_KEY", "dk")
    stub = StubSession(handler)
    monkeypatch.setattr(dart_client, "_session", stub)
    monkeypatch.setattr(dart_client, "MIN_INTERVAL_SEC", 0)
    return stub


FNLTT_2024 = {
    ("2024", "11013"): [
        _acct("20240515000001", 2024, "11013", "매출액", "100", "2024.01.01 ~ 2024.03.31", "100"),
        _acct("20240515000001", 2024, "11013", "자본총계", "900", "2024.03.31 현재", sj="BS"),
    ],
    ("2024", "11012"): [  # 반기: 당기 = 2분기 3개월, 누적 = 6개월
        _acct("20240814000001", 2024, "11012", "매출액", "120", "2024.04.01 ~ 2024.06.30", "220"),
    ],
    ("2024", "11014"): [  # 3분기 보고서가 당기 금액을 누적(9개월)으로 준 경우 (기간 > 100일)
        _acct("20241114000001", 2024, "11014", "매출액", "350", "2024.01.01 ~ 2024.09.30"),
    ],
    ("2024", "11011"): [
        _acct("20250311000001", 2024, "11011", "매출액", "500", "2024.01.01 ~ 2024.12.31"),
        _acct(
            "20250311000001", 2024, "11011", "당기순이익(손실)", "-40", "2024.01.01 ~ 2024.12.31"
        ),
    ],  # fmt: skip
}


def test_dart_three_month_and_cumulative(monkeypatch: pytest.MonkeyPatch) -> None:
    _stub_dart(monkeypatch, _dart_handler(FNLTT_2024))
    rows = dart_client.financial_rows("00126380", [2024], today=TODAY)
    q = {r["period"]: r for r in rows if r["metric"] == "매출액(분기)"}
    assert {p: r["value"] for p, r in q.items()} == {
        "2024_11013": 100,
        "2024_11012": 120,
        "2024_11014": 130,  # 9개월 350 − 6개월 220
        "2024_11011": 150,  # 연간 500 − 9개월 350
    }
    assert q["2024_11011"]["period_end"] == "2024-12-31"
    assert q["2024_11011"]["disclosed_at"] == "2025-03-11"
    assert q["2024_11014"]["disclosed_at"] == "2024-11-14"
    cum = {r["period"]: r["value"] for r in rows if r["metric"] == "매출액(누적)"}
    assert cum == {"2024_11012": 220, "2024_11014": 350}
    # 보고서에 나온 값은 예전처럼 계정 이름 그대로 (3분기는 받은 그대로 350)
    raw = {r["period"]: r["value"] for r in rows if r["metric"] == "매출액"}
    assert raw == {"2024_11013": 100, "2024_11012": 120, "2024_11014": 350, "2024_11011": 500}
    # 재무상태 항목은 분기 값을 만들지 않음, 당기순이익(손실) → 당기순이익 이름으로 묶임
    assert not any(r["metric"].startswith("자본총계(") for r in rows)
    assert not any(r["metric"] == "당기순이익(분기)" for r in rows)  # 분기 값이 없어 4분기 못 만듦


def test_dart_q4_from_three_quarters_when_no_cumulative(monkeypatch: pytest.MonkeyPatch) -> None:
    f = {
        ("2023", rc): [_acct(f"2023{m}01000001", 2023, rc, "영업이익", v, dt)]
        for rc, m, v, dt in (
            ("11013", "05", "10", "2023.01.01 ~ 2023.03.31"),
            ("11012", "08", "20", "2023.04.01 ~ 2023.06.30"),
            ("11014", "11", "30", "2023.07.01 ~ 2023.09.30"),
        )
    }
    f[("2023", "11011")] = [
        _acct("20240310000001", 2023, "11011", "영업이익", "100", "2023.01.01 ~ 2023.12.31")
    ]
    _stub_dart(monkeypatch, _dart_handler(f))
    rows = dart_client.financial_rows("00126380", [2023], today=TODAY)
    q = {r["period"]: r["value"] for r in rows if r["metric"] == "영업이익(분기)"}
    assert q["2023_11011"] == 40


def test_dart_shares_and_dividends(monkeypatch: pytest.MonkeyPatch) -> None:
    shares = {
        ("2024", "11011"): [
            {"rcept_no": "20250311000001", "se": "보통주", "istc_totqy": "5,969,782,550",
             "tesstk_co": "100,000", "distb_stock_co": "5,969,682,550", "stlm_dt": "2024-12-31"},
            {"rcept_no": "20250311000001", "se": "우선주", "istc_totqy": "822,886,700",
             "tesstk_co": "0", "distb_stock_co": "822,886,700", "stlm_dt": "2024-12-31"},
            {"rcept_no": "20250311000001", "se": "합계", "istc_totqy": "6,792,669,250",
             "tesstk_co": "100,000", "distb_stock_co": "6,792,569,250", "stlm_dt": "2024-12-31"},
        ],
        ("2024", "11013"): [  # 기준일 없음 → 1분기말
            {"rcept_no": "20240515000001", "se": "합계", "istc_totqy": "1,000",
             "tesstk_co": "-", "distb_stock_co": "1,000"},
        ],
    }  # fmt: skip
    divs = {
        ("2024", "11011"): [
            {"rcept_no": "20250311000001", "se": "주당액면가액(원)", "thstrm": "100"},
            {"rcept_no": "20250311000001", "se": "주당 현금배당금(원)", "stock_knd": "보통주",
             "thstrm": "1,446", "frmtrm": "1,444", "stlm_dt": "2024-12-31"},
            {"rcept_no": "20250311000001", "se": "주당 현금배당금(원)", "stock_knd": "우선주",
             "thstrm": "1,447", "stlm_dt": "2024-12-31"},
            {"rcept_no": "20250311000001", "se": "현금배당금총액(백만원)", "thstrm": "9,810,000",
             "stlm_dt": "2024-12-31"},
            {"rcept_no": "20250311000001", "se": "주식배당수익률(%)", "stock_knd": "보통주",
             "thstrm": "-"},
        ],
    }  # fmt: skip
    stub = _stub_dart(monkeypatch, _dart_handler({}, shares, divs))
    rows = dart_client.financial_rows("00126380", [2024], today=TODAY)
    got = {
        (r["period"], r["metric"]): (r["value"], r["period_end"], r["disclosed_at"]) for r in rows
    }
    assert got[("2024_11011", "발행주식수")] == (5_969_782_550, "2024-12-31", "2025-03-11")
    assert got[("2024_11011", "자기주식수")][0] == 100_000
    assert got[("2024_11011", "유통주식수")][0] == 5_969_682_550  # 보통주 행
    assert got[("2024_11013", "발행주식수")] == (1000, "2024-03-31", "2024-05-15")  # 합계 행
    assert ("2024_11013", "자기주식수") not in got  # '-' 는 값 없음
    assert got[("2024_11011", "주당배당금")] == (1446, "2024-12-31", "2025-03-11")  # 보통주
    assert got[("2024_11011", "배당금총액")][0] == 9_810_000 * 1_000_000
    # 배당은 기본으로 사업보고서만 부름
    div_calls = [c for c in stub.calls if "alotMatter" in c[1]]
    assert {c[2]["params"]["reprt_code"] for c in div_calls} == {"11011"}


def test_dart_skips_reports_not_yet_due_and_years_before_2015(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    stub = _stub_dart(monkeypatch, _dart_handler({}))
    dart_client.financial_rows("00126380", [2014, 2026], today=date(2026, 6, 1))
    called = {(c[1].rsplit("/", 1)[1], c[2]["params"]["bsns_year"], c[2]["params"]["reprt_code"])
              for c in stub.calls}  # fmt: skip
    assert ("fnlttSinglAcnt.json", "2026", "11013") in called
    assert ("fnlttSinglAcnt.json", "2026", "11012") not in called  # 반기 보고서는 8월쯤
    assert ("fnlttSinglAcnt.json", "2026", "11011") not in called  # 2027년 3월쯤
    assert not any(y == "2014" and p != "fnlttSinglAcnt.json" for p, y, _ in called)


def test_dart_quota_stops_without_retry(monkeypatch: pytest.MonkeyPatch) -> None:
    stub = _stub_dart(
        monkeypatch,
        lambda u, k: StubResponse(200, {"status": "020", "message": "요청 제한을 초과하였습니다."}),
    )
    monkeypatch.setattr(
        dart_client, "find_by_stock_code", lambda c: {"corp_code": "00126380", "corp_name": "x"}
    )
    with pytest.raises(DataSourceError, match="020"):
        DartFinancialAdapter().fetch(["005930"], date(2024, 1, 1), TODAY)
    assert len(stub.calls) == 1  # 재시도 없이 바로 멈춤


def test_financial_step_full_then_refresh_and_quota_stop() -> None:
    repo = open_repository("sqlite://")
    repo.save_constituents([])
    s = JobSettings(indices=[IndexCode.SP500], benchmarks=[], fin_years=12)
    s.extra_tickers = {"005930.KS": "삼성전자", "000660.KS": "SK하이닉스", "AAPL": "Apple"}

    class Quota(StubKeyedAdapter):
        def fetch(self, keys, start, end):  # noqa: ANN001, ANN201
            self.calls.append((list(keys), start, end))
            raise dart_client.DartLimitError("DART [020] 요청 제한 초과")

    dart = Quota("DART", lambda k: [])
    sec = StubKeyedAdapter("SEC_EDGAR", lambda k: [])
    r = financial_step(
        repo, s, adapters={"DART": dart, "SEC_EDGAR": sec}, today=TODAY, chunk=1
    )
    assert len(dart.calls) == 1 and "DART 멈춤" in r.notes[0] and not r.done
    assert dart.calls[0][1] == date(2014, 1, 1)  # 처음은 12년 전 1월 1일부터
    assert repo.fetch_attempts("DART", ["005930", "000660"]) == {}  # 기록 안 남김 → 다음에 이어서
    assert sec.calls[0][1] == date(2014, 1, 1)
    # 전체를 받은 종목은 FIN_REFRESH_DAYS 뒤에 최근분(작년 1월 1일부터)만
    later = date(2026, 10, 20)
    financial_step(repo, s, adapters={"SEC_EDGAR": sec}, today=later)
    assert sec.calls[-1][1] == date(2025, 1, 1)
