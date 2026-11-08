"""최소 시가총액 하드 필터 (2026-11-04 사용자 정책): 시가총액이 빈 날은 마지막으로 알려진 주식수(최대 730일 전) × 그날 종가로 추정하고,
그래도 없으면 후보에서 뺀다 (필수 포함은 예외). 합성 DB 에 팀 DB 의 공백 모양을 만든다:
앞쪽 공백(XOM: 주식수가 기준일 뒤에만), 중간 공백 + 분할(AVGO), 오래된 주식수(CAT 731일·JNJ 730일), 한국 종목(KRW 환산)."""

from __future__ import annotations

import datetime as dt

import pandas as pd
import pytest
from sqlalchemy import update

from backend.analysis.common.dbconn import SplitRepository
from backend.analysis.common.warnings import from_text, merge
from backend.analysis.m2_data import descriptor as D
from backend.analysis.m2_data.market_data import MarketData
from backend.analysis.m3_selection.retrieve import mcap_warnings, retrieve
from backend.analysis.m4_portfolio.market_model import build_market_model
from backend.analysis.m4_portfolio.spec import selectable_at
from backend.analysis.settings import AnalysisSettings, replace_settings
from backend.db import open_repository
from backend.db import tables as T
from backend.tests.analysis.conftest import AT, START, seed_repository

AS_OF = dt.date(2025, 12, 31)
EST_DAY = AS_OF - dt.timedelta(days=1)  # 추정용(strict) 기준일: valuation() 은 as_of−1 이하 행을 쓴다
T0 = dt.date(2024, 12, 31)  # 중간 공백 전 마지막 주식수
STALE = EST_DAY - dt.timedelta(days=731)  # 한계(730일) 하루 밖
EDGE = EST_DAY - dt.timedelta(days=730)  # 한계 당일 (포함)
INTENT = {"interpretation": {"themes": [{"id": "mix", "label_ko": "혼합", "description_ko": "", "gics_codes": ["45301020", "10102010", "20106010"],
                                         "keywords": [], "example_tickers": []}]},
          "exclude_theme_rules": [], "screen": {"template": "momentum", "metric": "return_12m_1m", "direction": "desc"}}  # fmt: skip
CONS = {"universe": ["SP500", "NASDAQ100", "KOSPI200"], "asset_types": ["stock"], "num_holdings": {"target": 2, "min": 1, "max": 8},
        "max_weight_per_stock": 0.5, "max_weight_per_sector": 1.0, "min_cash_ratio": 0.0, "exclude_tickers": [], "exclude_sectors": [],
        "must_include_tickers": ["MU"], "min_market_cap_usd": 1e9, "min_avg_daily_volume_usd": 0}  # fmt: skip


def _vrow(sym: str, day: dt.date, close: float, *, sf: float = 1.0, shares: float | None = None, ccy: str = "USD", shares_as_of: dt.date | None = None) -> dict:
    aid = f"KR-{sym[:-3]}" if sym.endswith(".KS") else f"US-{sym}"
    return {"asset_id": aid, "date": day, "ticker": sym, "currency": ccy, "close": close, "split_factor": sf, "shares_outstanding": shares,
            "market_cap": None if shares is None else close * sf * shares, "net_income_ttm": None, "eps_ttm": None, "per": None, "bps": None,
            "pbr": None, "roe_ttm": None, "dps_ttm": None, "dividend_yield": None, "fin_period_end": None, "fin_disclosed_at": None,
            "shares_as_of": (shares_as_of or day) if shares else None, "method": "TEST"}  # fmt: skip


@pytest.fixture(scope="module")
def gap(descriptor_dir):
    """세션 합성 DB 와 같은 자료 + 공백. 세션 DB 는 다른 시험이 쓰므로 따로 만든다."""
    repo = open_repository("sqlite://", clock=lambda: AT)
    seed_repository(repo)
    v = T.valuation_daily

    def blank(aid: str, after: dt.date | None = None) -> None:  # 주식수·시가총액을 비운다 (after 를 주면 그날 뒤만)
        with repo.engine.begin() as conn:
            conn.execute(update(v).where(v.c.asset_id == aid, *([v.c.date > after] if after else [])).values(shares_outstanding=None, market_cap=None))

    blank("US-XOM")
    blank("US-MU")
    for aid, after in (("US-AVGO", T0), ("US-AMD", T0), ("KR-005930", T0), ("US-CAT", STALE), ("US-JNJ", EDGE), ("US-MSFT", T0)):
        blank(aid, after)
    repo.upsert_valuation([
        _vrow("XOM", AS_OF, 100.0, shares=4e9),  # 기준일 당일(= 추정 기준일 뒤)에만 주식수 → 쓰면 선견
        _vrow("AVGO", T0, 100.0, sf=4.0, shares=2e9), _vrow("AVGO", EST_DAY, 150.0),  # T0 뒤 4:1 분할: 분할 전 행은 sf=4 (실제 종가 = close × 4)
        _vrow("AMD", T0, 100.0, shares=1e3), _vrow("AMD", EST_DAY, 120.0),  # 추정 시가총액 12만 달러 < 하한 10억 달러
        _vrow("005930.KS", T0, 60_000.0, shares=5.9e9, ccy="KRW"), _vrow("005930.KS", EST_DAY, 70_000.0, ccy="KRW"),
        _vrow("CAT", STALE, 200.0, shares=5e8), _vrow("JNJ", EDGE, 150.0, shares=2.4e9),
        # 행은 T0(1년 전)지만 주식수 자체는 800일 전 값 (팀 DB 가 550일까지 옛 주식수를 행에 남긴다: SCHW 2022-02 행 = 2020-07 주식수)
        _vrow("MSFT", T0, 300.0, shares=7e9, shares_as_of=EST_DAY - dt.timedelta(days=800)), _vrow("MSFT", EST_DAY, 400.0),
    ])  # fmt: skip
    s = AnalysisSettings()
    s = replace_settings(s, market=replace_settings(s.market, valuation_max_staleness_days=10))
    md = MarketData(repo, s)
    desc, _info, _w = D.load_for(AS_OF, CONS["universe"], processed_dir=descriptor_dir)
    md.prefetch(D.tickers(desc), START, AS_OF)  # 01 단계처럼 가격 이력을 먼저 (안 하면 후보 검색이 가격 이력 부족으로 모두 뺀다)
    return repo, md, desc


# ───────────────────────── 리더 ─────────────────────────
def test_shares_reader_is_point_in_time_and_bounded(gap):
    repo, _md, _desc = gap
    got = repo.get_shares_asof(["US-AVGO", "US-XOM", "US-NVDA"], EST_DAY, max_staleness_days=730)
    assert got["US-AVGO"] == {"date": T0, "shares_outstanding": 2e9, "shares_as_of": T0, "split_factor": 4.0, "currency": "USD"}
    assert "US-XOM" not in got and got["US-NVDA"]["date"] <= EST_DAY  # XOM 주식수는 EST_DAY 뒤에만 → 읽지 않는다
    assert repo.get_shares_asof(["US-XOM"], AS_OF)["US-XOM"]["date"] == AS_OF  # 그 행은 있다: 날짜 경계만이 막는다
    assert repo.get_shares_asof(["US-CAT"], STALE + dt.timedelta(days=730), max_staleness_days=730)["US-CAT"]["date"] == STALE  # 730일은 포함
    assert repo.get_shares_asof(["US-CAT"], STALE + dt.timedelta(days=731), max_staleness_days=730) == {}
    assert SplitRepository(repo, repo).get_shares_asof(["US-AVGO"], EST_DAY)["US-AVGO"]["date"] == T0  # 결과 저장소 분리 래퍼도 시장 저장소로 넘긴다


# ───────────────────────── MarketDataView ─────────────────────────
def test_estimate_math_with_split_staleness_and_krw(gap):
    _repo, md, _desc = gap
    view = md.view(AS_OF)
    tk = ["AVGO", "XOM", "CAT", "JNJ", "005930.KS", "NVDA"]
    mc = view.market_cap_usd(tk)
    # 분할: 실제 종가 150 × 실제 주식수 (2e9 × 4) = close(그날) × S(T0) × sf(T0)
    assert mc["AVGO"] == pytest.approx(150.0 * 2e9 * 4.0)
    assert "XOM" not in mc and "CAT" not in mc  # 주식수가 그날 뒤에만 있음(선견 금지) · 731일 전 주식수
    fx = view.fx_on_or_before(EST_DAY).rate
    assert mc["005930.KS"] == pytest.approx(70_000.0 * 5.9e9 / fx)  # KRW 시가총액을 기존과 같은 환율로 환산
    assert view.market_cap_estimated(tk) == {"AVGO": T0, "JNJ": EDGE, "005930.KS": T0}  # 730일 전은 한계 안
    v = view.valuation(tk)
    assert v.loc["NVDA", "market_cap_source"] == "valuation" and v.loc["NVDA", "market_cap_basis_date"] == v.loc["NVDA", "date"]
    assert pd.isna(v.loc["XOM", "market_cap_source"]) and pd.isna(v.loc["XOM", "market_cap_usd"])
    assert view.valuation(list(reversed(tk))) is v  # 대체값도 (기준일, 종목 집합) 캐시 그대로
    assert view.valuation(["XOM"], strict_before=False).loc["XOM", "market_cap_source"] == "valuation"  # 기준일 당일(체결용)이면 그날 행이 있다


def test_repository_without_shares_reader_means_no_estimate(gap):
    """옛 가짜 저장소처럼 get_shares_asof 가 없으면 대체 없이 '자료 없음' (실행이 멈추지 않는다)."""
    repo, md, _desc = gap

    class NoShares:
        def __getattr__(self, name):
            if name == "get_shares_asof":
                raise AttributeError(name)
            return getattr(repo, name)

    view = MarketData(NoShares(), md.s).view(AS_OF)
    assert view.market_cap_usd(["AVGO", "NVDA"]).keys() == {"NVDA"} and view.market_cap_estimated(["AVGO"]) == {}


def test_shares_lookup_is_asked_once_per_day_and_asset(gap):
    """후보 검색·선정 지표·시장모형이 같은 날 종목 집합만 바꿔 다시 부른다 → 주식수는 (날짜, 종목)마다 한 번만 묻는다 (없음도 기억)."""
    repo, md, _desc = gap
    asked = []

    class Counting:
        def __getattr__(self, name):
            return getattr(repo, name)

        def get_shares_asof(self, ids, d, **kw):
            asked.append(sorted(ids))
            return repo.get_shares_asof(ids, d, **kw)

    view = MarketData(Counting(), md.s).view(AS_OF)
    first = view.market_cap_usd(["AVGO", "NVDA", "XOM"])
    assert view.market_cap_usd(["AVGO", "XOM"]) == {"AVGO": first["AVGO"]}
    assert asked == [["US-AVGO", "US-XOM"]]


# ───────────────────────── 후보 검색 ─────────────────────────
def test_retrieve_drops_missing_keeps_estimated_and_forced(gap):
    _repo, md, desc = gap
    cand = retrieve(md.view(AS_OF), desc, INTENT, CONS, request_id="t", max_candidates=None)
    reasons = {f.ticker: f.reason for f in cand.filtered_out}
    assert reasons == {"XOM": "market_cap_missing", "CAT": "market_cap_missing", "AMD": "min_market_cap_usd(estimated)"}
    assert cand.stats["by_filter"] == {"market_cap_missing": 2, "min_market_cap_usd": 1}
    by = {c.ticker: c for c in cand.candidates}
    assert sorted(by) == ["000660.KS", "005930.KS", "AVGO", "MU", "NVDA"]
    assert by["MU"].forced and by["MU"].market_cap_usd is None  # 필수 포함은 후보 조건 밖 (자료가 없어도 남는다)
    assert by["AVGO"].market_cap_usd == pytest.approx(1.2e12) == md.view(AS_OF).market_cap_usd(["AVGO"])["AVGO"]  # 필터와 시가총액비중이 같은 값
    assert cand.stats["mcap_estimated"] == {"005930.KS": str(T0), "AVGO": str(T0)}
    mw = [w for w in cand.warnings if "market cap" in w and not w.startswith("user floor")]
    assert mw == ["min market cap 1000000000 USD: dropped 2 candidates without market cap data ['CAT', 'XOM']",
                  "market cap estimated from last known shares (within 730 days) for ['005930.KS', 'AVGO']"]  # fmt: skip
    # 최소 시가총액 미달로 뺀 테마 후보는 따로 공지한다 (2026-11 평가: 사용자 하한으로 빠진 테마 대표 종목을 알리지 않았다)
    assert [w for w in cand.warnings if w.startswith("user floor")] == ["user floor min market cap 1000000000 USD: dropped 1 theme candidates [AMD]"]
    ws = [from_text("03_candidates", w) for w in mw]
    assert [(w.code, w.level) for w in ws] == [("min_mcap_missing", "user"), ("mcap_estimated", "user")]
    assert ws[0].message_ko == "시가총액 자료가 없어 최소 시가총액(10억 달러)을 확인할 수 없는 2개 종목(CAT, XOM)은 후보에서 뺐습니다."
    assert ws[1].message_ko == "시가총액 자료가 빈 2개 종목(005930.KS, AVGO)은 직전에 알려진 주식수(최대 2년 전)에 그날 종가를 곱해 시가총액을 추정했습니다."
    # 07 재선정용: 기준일 테마 통과 종목만 적고, 남는 종목이 없으면 그 경고는 내지 않는다
    assert mcap_warnings(cand, CONS, 730, only=["AVGO", "XOM", "NVDA"]) == [
        "min market cap 1000000000 USD: dropped 1 candidates without market cap data ['XOM']",
        "market cap estimated from last known shares (within 730 days) for ['AVGO']"]  # fmt: skip
    assert mcap_warnings(cand, CONS, 730, only=["NVDA", "MU"]) == []


def test_retrieve_without_min_cap_keeps_missing_names_quietly(gap):
    _repo, md, desc = gap
    cand = retrieve(md.view(AS_OF), desc, INTENT, {**CONS, "min_market_cap_usd": 0}, request_id="t", max_candidates=None)
    assert {"XOM", "CAT", "AMD"} <= {c.ticker for c in cand.candidates} and not cand.filtered_out
    assert not [w for w in cand.warnings if "market cap" in w]  # 하한이 없으면 확인할 것도 없다
    assert set(cand.stats["mcap_estimated"]) == {"005930.KS", "AMD", "AVGO"}  # 추정했다는 기록은 파일에 남긴다


def test_selectable_at_forwards_only_theme_passed_names_as_dated_notice(gap):
    _repo, md, desc = gap
    _cand, _tag, sel, _facts = selectable_at(md, AS_OF, desc, INTENT, CONS, ["AVGO", "XOM", "NVDA", "MU"], "t")
    mw = [w for w in sel.warnings if "market cap" in w]
    assert mw == ["min market cap 1000000000 USD: dropped 1 candidates without market cap data ['XOM']",
                  "market cap estimated from last known shares (within 730 days) for ['AVGO']"]  # fmt: skip
    w = from_text("07_backtest_spec", f"screen@{AS_OF}: {mw[0]}")  # 07 이 붙이는 앞말
    assert w.level == "user" and w.code == "min_mcap_missing" and w.dates == [str(AS_OF)]
    assert w.message_ko == "백테스트 시작일(2025-12-31) 기준: 시가총액 자료가 없어 최소 시가총액(10억 달러)을 확인할 수 없는 1개 종목(XOM)은 후보에서 뺐습니다."
    _c, _t, sel2, _f = selectable_at(md, AS_OF, desc, INTENT, CONS, ["NVDA"], "t")
    assert not [w for w in sel2.warnings if "market cap" in w]  # 테마 통과 종목과 무관한 그날 후보는 공지에 섞지 않는다


def test_market_model_cap_weights_use_the_same_estimate(gap):
    _repo, md, desc = gap
    view = md.view(AS_OF)
    req = {"request_id": "t", "risk": {"risk_tolerance": "moderate", "max_drawdown_tolerance": 0.35, "benchmark": "SPY"},
           "constraints": {"max_weight_per_stock": 1.0, "max_weight_per_sector": 1.0, "min_cash_ratio": 0.0},
           "strategy_preference": {"baseline_weighting": "equal_weight"}}  # fmt: skip
    model, _base = build_market_model(view, ["NVDA", "AVGO", "XOM"], req, desc, md.s)
    mc = view.market_cap_usd(["NVDA", "AVGO", "XOM"])
    assert model["cap_weights"]["AVGO"] == pytest.approx(mc["AVGO"] / (mc["AVGO"] + mc["NVDA"]), abs=2e-6) and model["cap_weights"]["XOM"] == 0
    note = next(n for n in model["notes"] if n.startswith("market cap missing for"))
    assert "XOM" in note and "AVGO" not in note
    w = from_text("08_market_model", note)
    # 시장모형 공지는 후보 단계 공지에 가려지지 않는다. 시가총액비중에서 최소 비중만 받는다는 사실은 사용자 공지 (025: 필수 포함 XOM 1.4~1.7%)
    assert w.code == "market_cap_missing" and w.level == "user" and "XOM" in w.message_ko


# ───────────────────────── 경고 문구 ─────────────────────────
def test_mcap_notices_plain_dated_shortened_and_kept_apart():
    names = ["A", "B", "C", "D", "E", "F", "G"]
    w = from_text("07_backtest_spec", f"screen@2023-06-12: min market cap 50000000000 USD: dropped 7 candidates without market cap data {names}")
    assert w.code == "min_mcap_missing" and w.dates == ["2023-06-12"]
    assert w.message_ko == "백테스트 시작일(2023-06-12) 기준: 시가총액 자료가 없어 최소 시가총액(500억 달러)을 확인할 수 없는 7개 종목(A, B, C, D, E 외 2개)은 후보에서 뺐습니다."
    e = from_text("03_candidates", "market cap estimated from last known shares (within 730 days) for ['SCHW']")
    assert e.code == "mcap_estimated" and e.dates == []
    assert e.message_ko == "시가총액 자료가 빈 1개 종목(SCHW)은 직전에 알려진 주식수(최대 2년 전)에 그날 종가를 곱해 시가총액을 추정했습니다."
    assert "최대 400일 전" in from_text("03_candidates", "market cap estimated from last known shares (within 400 days) for ['SCHW']").message_ko
    # 기준일 공지와 시작일 공지는 같은 종목이라도 따로 둔다 (merge 키 = 종목 + '백테스트 시작일' 여부)
    now = from_text("03_candidates", "min market cap 50000000000 USD: dropped 1 candidates without market cap data ['XOM']")
    start = from_text("07_backtest_spec", "screen@2023-06-12: min market cap 50000000000 USD: dropped 1 candidates without market cap data ['XOM']")
    assert now.message_ko.startswith("시가총액 자료가 없어") and len(merge([now, start])) == 2
    for old in ("market cap missing for ['XOM']: treated as 0 in market_cap weights", "market cap unavailable from valuation_daily for all candidates"):
        assert from_text("08_market_model", old).code == "market_cap_missing"
    assert from_text("05_selection", "min market cap 5 USD not checked (no market cap data) for selected ['VEEV']").code == "legacy_note"  # 옛 코드는 없앴다


@pytest.mark.parametrize(("detail", "expect"), [
    ("roe_ttm=-0.1572, 범위 >0 ≤10", "ROE -15.7%, 자격선 0% 초과 1,000% 이하"),
    ("dividend_yield_ttm=0.3512, 범위 >0 ≤0.3", "배당수익률 35.12%, 자격선 0% 초과 30% 이하"),
    ("pe_ttm=73.4, 범위 >0 ≤50", "PER 73.4배, 자격선 0배 초과 50배 이하"),
    ("vol_60d=0.5, 범위 >0", "vol_60d 0.5, 범위 >0"),  # 자격선이 없는 지표(원래 나오지 않음)는 예전처럼 이름만 바꾼다
])  # fmt: skip
def test_must_include_out_of_range_detail_is_readable(detail, expect):
    """009 리포트 결함의 형제: 필수 포함 공지가 'ROE -0.1572, 범위 >0 ≤10' 처럼 원문 소수를 보여 줬다."""
    w = from_text("05_selection", f"must_include PG: metric_out_of_range({detail}), kept")
    assert w.code == "must_include_out_of_range"
    assert w.message_ko == f"필수 포함 종목 PG은(는) 선정 지표가 자격선 밖({expect})이지만 요청에 따라 포함했습니다."


def test_estimate_age_is_measured_from_the_share_count_date(gap):
    """검토(2026-11-04): '최대 2년' 을 행 날짜로 재서 3년 넘은 주식수(SCHW 2020-07)로 추정했고 공지의 '최대 2년 전' 이 거짓이었다.
    주식수 자체의 기준일(shares_as_of)로 잰다 → 800일 된 주식수는 쓰지 않고, 근거 날짜도 주식수 기준일."""
    _repo, md, _desc = gap
    view = md.view(AS_OF)
    assert "MSFT" not in view.market_cap_usd(["MSFT"]) and view.market_cap_estimated(["MSFT", "AVGO"]) == {"AVGO": T0}


# ───────────────────────── 주식수 이상값 (047) ─────────────────────────
def test_mcap_guard_fixes_unit_and_double_split_errors_only():
    """047: 팀 DB 의 GOOGL 2022-07-27 ~ 10-26 주식수가 분할(20:1)을 두 번 반영해 20배 → 시가총액 28.9조 달러, 시총비중 87%.
    2015년 이후 51종목에 주식수가 1000배(단위)·분할 비율만큼 틀린 구간이 있다. 직전 400일 중앙값과 비교해 그 두 모양만 고친다.
    실제 주식수 변화(합병 7.7배)와, 고친 값이 회사 크기로 말이 안 되는 경우(틀린 값이 기간 대부분인 ECHO)는 그대로 둔다."""
    from sqlalchemy import delete

    repo = open_repository("sqlite://", clock=lambda: AT)
    seed_repository(repo)
    names = ["NVDA", "AMD", "AVGO", "MSFT"]
    with repo.engine.begin() as conn:
        conn.execute(delete(T.valuation_daily).where(T.valuation_daily.c.asset_id.in_([f"US-{t}" for t in names])))
    split_day, err_from = EST_DAY - dt.timedelta(days=60), EST_DAY - dt.timedelta(days=30)
    rows = []
    for i in range(120):
        d = EST_DAY - dt.timedelta(days=119 - i)
        late = d >= err_from
        sf = 4.0 if d < split_day else 1.0  # NVDA 4:1 분할 (분할 전 행은 실제 종가 = close × 4, 실제 주식수 = 1e9 / 4)
        rows += [_vrow("NVDA", d, 100.0, sf=sf, shares=1e9 / sf * (4 if late else 1)),  # 분할 뒤 공시 주식수에 분할을 또 곱함 → 4배
                 _vrow("AMD", d, 100.0, shares=1e9 * (1e-3 if late else 1)),  # 천 주 단위로 들어간 분기 → 1/1000
                 _vrow("AVGO", d, 100.0, shares=1e9 * (7.7 if late else 1)),  # 합병으로 실제 7.7배
                 _vrow("MSFT", d, 100.0, shares=1e9 * (1 if late else 1e-3))]  # 틀린 값(1/1000)이 기간 대부분 → 고치면 1억 달러
    repo.upsert_valuation(rows)
    view = MarketData(repo, AnalysisSettings()).view(AS_OF)
    mc = view.market_cap_usd(names)
    assert mc["NVDA"] == pytest.approx(1e11) and mc["AMD"] == pytest.approx(1e11)  # 중앙값 주식수 1e9 × 종가 100
    assert mc["AVGO"] == pytest.approx(7.7e11) and mc["MSFT"] == pytest.approx(1e11)  # 그대로
    rep = view.market_cap_repaired(names)
    assert set(rep) == {"NVDA", "AMD"} and rep["NVDA"] == pytest.approx(4.0) and rep["AMD"] == pytest.approx(1e-3)
    assert view.valuation(names).loc["NVDA", "market_cap_source"] == "repaired"
    # 자료 품질 표에 한국어로 남긴다
    _panel, q = view.panel(["NVDA", "AMD"], EST_DAY - dt.timedelta(days=5), AS_OF, required=["SPY"], benchmarks=["SPY"])
    note = next(w for w in q.warnings if "주식수가 잘못 들어간" in w)
    assert "2건" in note and f"AMD {EST_DAY} 1/1000" in note and f"NVDA {EST_DAY} 4배" in note
