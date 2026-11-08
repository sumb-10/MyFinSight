"""2026-11 프로토타입 평가에서 찾은 세 가지: 적립일 수익률 정의, 수정안 비교의 낙폭 장단점, 사용자 응답에 나온 DB 주소."""

from __future__ import annotations

import copy

import numpy as np
import pandas as pd
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from backend.analysis.api.errors import install
from backend.analysis.common import dbconn
from backend.analysis.errors import public_message, redact
from backend.analysis.m5_backtest_report.backtest_engine import contribution_dates, extract_raw, rebalance_dates, run_static_portfolio
from backend.analysis.m5_backtest_report.compare import compare
from backend.analysis.settings import BacktestSettings, replace_settings
from backend.schemas.errors import RepositoryError
from backend.tests.analysis.test_revision import base_run  # noqa: F401  (모듈 범위 fixture 재사용)

HOST = "db-1a2b3c.cluster-xyz.ap-northeast-2.rds.amazonaws.com"


def test_contribution_day_return_is_the_return_of_yesterdays_holdings():
    """월 적립일에도 지수 수익률 = 전날 종가 보유 비중 × 그날 종목 수익률 (적립금은 그날 종가에 사므로 거래일 끝 유입 식, Module5 §4).
    예전 bt 가격 지수는 적립금을 그날 아침부터 있던 현금으로 봐서 적립일 수익률이 적립금 비율만큼 줄었다."""
    rng = np.random.default_rng(11)
    cal = pd.bdate_range("2023-01-02", periods=180)
    px = pd.DataFrame({"A": 100 * np.cumprod(1 + rng.normal(0.001, 0.02, len(cal))), "B": 40 * np.cumprod(1 + rng.normal(0.0005, 0.015, len(cal)))}, index=cal)
    w = {"A": 0.6, "B": 0.4}
    s = replace_settings(BacktestSettings(), commission_bps=0.0)
    rb = rebalance_dates({"enabled": True, "count": 1, "unit": "1q"}, cal, cal[0], s)
    cd = contribution_dates(cal, cal[0], cal[-1], 15)
    b, res = run_static_portfolio("p", w, px, 1_000.0, rb, cd, 1_000.0, s)  # 적립금이 평가액과 비슷해 차이가 잘 보인다
    raw = extract_raw(b, res, cal[0])
    idx = raw["index"]
    model = (raw["security_weights"][list(w)].shift(1) * px[list(w)].pct_change()).sum(axis=1)
    assert cd and idx.iloc[0] == pytest.approx(100.0)
    assert float((idx.pct_change() - model).iloc[1:].abs().max()) < 1e-10
    old = res.prices["p"].reindex(idx.index).pct_change()
    assert float((old - model)[cd].abs().max()) > 1e-3  # 고치기 전 지수는 적립일에 어긋났다
    v, f = raw["values"], raw["flows"]
    assert float(((v - f) / v.shift(1) - 1 - idx.pct_change()).iloc[1:].abs().max()) < 1e-12


def test_comparison_counts_a_smaller_drawdown_as_a_pro(base_run):  # noqa: F811
    """최대낙폭은 음수로 저장된다. 수정안이 덜 빠졌으면(−10% vs −20%) 장점, 더 빠졌으면 단점 (예전에는 거꾸로)."""
    _, _, _, results, _ = base_run
    cid = results["validation"]["chosen_id"]
    base_mdd = next(p for p in results["backtest"]["portfolios"] if p["id"] == cid)["headline"]["max_drawdown"]
    assert base_mdd < -0.002
    for factor, side in ((0.5, "pros_ko"), (1.5, "cons_ko")):
        revised = copy.deepcopy(results)
        next(p for p in revised["backtest"]["portfolios"] if p["id"] == cid)["headline"]["max_drawdown"] = round(base_mdd * factor, 6)
        pc = compare(results, revised, base_report_id="a", revised_report_id="b")["pros_cons_ko"]
        other = "cons_ko" if side == "pros_ko" else "pros_ko"
        assert any(x.startswith("최대 낙폭") for x in pc[side]), (factor, pc)
        assert not any(x.startswith("최대 낙폭") for x in pc[other]), (factor, pc)


# ───────────────────────── 5번: 자연어 전략 → 실행 규칙 (2026-11 평가 뒤) ─────────────────────────
def test_idea_sets_dividend_growth_and_balance_sheet_guards():
    """'배당을 꾸준히 늘린' → 최근 3년 주당배당을 줄이지 않고 늘린 종목만, '재무가 탄탄한' → 부채비율 300% 상한. 코드가 정해 LLM 값은 덮는다
    (078·086: 해석이 차이를 알아채고도 고를 보기가 없어 묻지 못했고 배당을 깎은 F·DOW 가 들어갔다)."""
    from backend.analysis.m3_selection.intent import idea_screen_guards
    from backend.analysis.settings import AnalysisSettings

    s = AnalysisSettings()
    # 성장 문구('늘려 온') → 최근 5년 해마다 인상, 안정 문구('꾸준히 많이 주는') → 최근 3년 삭감 없음 (평가 000·086·012)
    cases = [("배당을 꾸준히 늘려 온 미국 기업에 투자하고 싶어요", 5, True, None), ("재무가 탄탄하고 이익률이 높은 회사 위주로", 0, False, 3.0),
             ("부채가 적고 연속으로 배당을 올린 회사", 5, True, 3.0), ("배당을 꾸준히 많이 주는 은행", 3, False, None),
             ("AI 반도체 기업에 공격적으로", 0, False, None), ("배당수익률이 높은 종목", 0, False, None)]  # fmt: skip
    for idea, years, growth, de in cases:
        scr = {"template": "high_dividend", "dividend_growth_years": 7}
        warns = idea_screen_guards({"natural_language": {"idea": idea}}, scr, s)
        assert (scr["dividend_growth_years"], scr["dividend_require_growth"], scr["max_debt_to_equity"]) == (years, growth, de), idea
        assert any("dividend_growth_years" in w for w in warns)  # LLM 이 적은 7 은 아이디어로 정한 값으로 바뀐다


class _FakeView:
    def __init__(self, dps=None, de=None, margin=None):
        self._dps, self._de, self._margin = dps or {}, de or {}, margin or {}
        self.s = __import__("backend.analysis.settings", fromlist=["AnalysisSettings"]).AnalysisSettings()
        self.md = type("MD", (), {"market_of": staticmethod(lambda t: "KR" if str(t).endswith((".KS", ".KQ")) else "US")})()

    def dps_history(self, tickers, years):
        return {t: self._dps.get(t, [None] * (years + 1)) for t in tickers}

    def debt_to_equity(self, tickers):
        return {t: self._de.get(t) for t in tickers}

    def operating_margin_ttm(self, tickers):
        return {t: self._margin.get(t) for t in tickers}


class _FakeDesc:
    def __init__(self, sectors, universe=(), intros=None):
        self.sectors, self.intros = sectors, intros or {}
        self.stocks = [{"yfinance_symbol": t} for t in universe]  # D.tickers(desc) = 유니버스 (중앙값 기준선)

    def by_ticker(self, t):
        code = self.sectors.get(t, "45")
        g = {"code": code, "name": "x"}
        return {"intro": self.intros.get(t, ""), "gics": {"sector": g, "industry_group": {"code": code + "10", "name": "x"},
                                                          "industry": {"code": code + "1010", "name": "x"}, "sub_industry": {"code": code + "101010", "name": "x"}}}


def test_screen_guards_drop_dividend_cutters_and_thin_equity():
    """주당배당 [기준일, 1년 전, 2년 전, 3년 전]: 늘었고 한 해도 5% 넘게 줄지 않아야 남는다(중간 해 자료가 비면 건너뜀).
    부채비율: 상한(3)을 넘거나 자본이 0 이하면 뺀다. 금융(GICS 40)은 재지 않고, 자료가 없으면 남기고, 필수 포함은 남기고 알린다."""
    import math

    from backend.analysis.common.warnings import from_text
    from backend.analysis.m3_selection.screen import _idea_guards

    view = _FakeView(dps={"GROW": [4.2, 3.9, 3.7, 3.5], "FLAT": [1.6] * 4, "CUT": [1.75, 2.8, 2.8, 2.6], "GAP": [4.2, None, 3.7, 3.5],
                          "SHORT": [1.0, 0.9, None, None], "MUST": [1.0, 2.0, 2.0, 2.0]})  # fmt: skip
    rej, warns = _idea_guards(view, _FakeDesc({}), {"dividend_growth_years": 3}, list(view._dps), {"MUST"})
    assert {r.ticker: r.reason for r in rej} == {"FLAT": "dividend_not_growing(3y)", "CUT": "dividend_cut(3y)", "SHORT": "dividend_history_short(3y)"}
    notes = [from_text("05_selection", w) for w in warns if not w.startswith("must_include")]
    assert {n.code for n in notes} == {"dividend_growth_dropped", "dividend_history_dropped"} and all(n.level == "user" for n in notes)
    assert "FLAT, CUT" in next(n for n in notes if n.code == "dividend_growth_dropped").message_ko
    assert any(w.startswith("must_include MUST: dividend_cut") for w in warns)
    # 안정 문구: 동결(FLAT)은 남고 삭감(CUT)만 빠진다
    rej, warns = _idea_guards(view, _FakeDesc({}), {"dividend_growth_years": 3, "dividend_require_growth": False}, ["GROW", "FLAT", "CUT"], set())
    assert {r.ticker: r.reason for r in rej} == {"CUT": "dividend_cut(3y)"}
    assert from_text("05_selection", warns[0]).code == "dividend_steady_dropped"
    # 성장 문구: 해마다 거의 빠짐없이 인상 — 3번 중 2번 이상 0.5% 넘게 늘어야 (TFC·HBAN 처럼 묶어 두면 빠진다)
    view2 = _FakeView(dps={"HOLD": [2.08, 2.08, 2.08, 1.92], "OK": [2.5, 2.4, 2.4, 2.2]})
    rej, _ = _idea_guards(view2, _FakeDesc({}), {"dividend_growth_years": 3}, ["HOLD", "OK"], set())
    assert {r.ticker for r in rej} == {"HOLD"}

    view = _FakeView(de={"LOW": 0.5, "HIGH": 6.95, "NEG": math.inf, "BANK": 12.0, "UNK": None})
    rej, warns = _idea_guards(view, _FakeDesc({"BANK": "40"}), {"max_debt_to_equity": 3.0}, list(view._de), set())
    assert {r.ticker for r in rej} == {"HIGH", "NEG"}
    lev = from_text("05_selection", next(w for w in warns if "above" in w))
    assert lev.code == "high_leverage_dropped" and "300%" in lev.message_ko and "자본 0 이하" in lev.message_ko
    assert from_text("05_selection", next(w for w in warns if "unknown" in w)).code == "leverage_unknown"
    assert _idea_guards(view, _FakeDesc({}), {}, list(view._de), set()) == ([], [])  # 조건이 없으면 아무것도 하지 않는다


class _FakeMd:
    def __init__(self, caps, names):
        self.assets = {t: {"market": "US", "asset_type": "STOCK", "ticker": t, "yfinance_symbol": t, "name": names.get(t, t)} for t in caps}

    def market_of(self, t):
        return "US"


class _CapView(_FakeView):
    def __init__(self, caps, names):
        super().__init__()
        self._caps, self.md = caps, _FakeMd(caps, names)

    def market_cap_usd(self, tickers):
        return {t: self._caps[t] for t in tickers if t in self._caps}


def test_big_tech_idea_keeps_only_top_market_caps():
    """'빅테크 대형주' → 선정일 시가총액 30위 안만 (같은 시장 전체 주식 기준, 같은 회사의 주식 클래스는 한 회사).
    평가 7개 시나리오(019·022·063·070·073·084·095)에서 업종 코드로만 잡아 FTNT·HPQ·SNDK 가 뽑히고 AAPL·MSFT·NVDA 는 빠졌다."""
    from backend.analysis.common.warnings import from_text, guard_reason_ko
    from backend.analysis.m3_selection.intent import idea_screen_guards
    from backend.analysis.m3_selection.screen import _idea_guards
    from backend.analysis.settings import AnalysisSettings

    s = AnalysisSettings()
    for idea, k in (("미국 빅테크 대형주 중 최근 주가 흐름이 강한 종목", 30), ("시총 상위 기술주에 투자", 30), ("AI 반도체 기업에 공격적으로", None), ("국내 대형 우량주", None)):
        scr: dict = {}
        idea_screen_guards({"natural_language": {"idea": idea}}, scr, s)
        assert scr["mega_cap_rank"] == k, idea

    caps = {"GOOGL": 4000.0, "GOOG": 3990.0, **{f"T{i}": 3000.0 - 50 * i for i in range(2, 41)}}
    view = _CapView(caps, {"GOOGL": "Alphabet Inc. (Class A)", "GOOG": "Alphabet Inc. (Class C)"})
    rej, warns = _idea_guards(view, _FakeDesc({}), {"mega_cap_rank": 30}, ["GOOG", "T30", "T31", "NOCAP", "T35"], {"T35"})
    assert {r.ticker: r.reason for r in rej} == {"T31": "market_cap_rank(31>30)", "NOCAP": "market_cap_rank(unknown)"}  # GOOG·GOOGL 을 따로 셌다면 T30 이 31위
    assert "must_include T35: market_cap_rank(35>30), kept" in warns
    note = from_text("05_selection", next(w for w in warns if w.startswith("mega cap")))
    assert note.code == "mega_cap_dropped" and note.level == "user" and "시가총액 30위 안" in note.message_ko and "T31 31위, NOCAP 자료 없음" in note.message_ko
    assert guard_reason_ko("market_cap_rank(31>30)") == "시가총액 31위로 30위 밖 (초대형주 조건)"
    assert guard_reason_ko("debt_to_equity(6.95>3)") == "부채비율 695%로 상한 300% 초과 (재무 건전성 조건)"
    assert guard_reason_ko("rank_beyond_n") is None


def test_momentum_floor_and_low_volatility_half(eligibility_lines_on):
    """모멘텀은 12-1 수익률 0 초과만, 저변동성은 테마 후보 중 변동성이 낮은 절반(중앙값 이하)만 — 모자라도 채우지 않는다 (008·010).
    후보가 목표의 두 배 이상이면 위쪽 절반은 어차피 뽑히지 않아 결과가 같다."""
    from backend.analysis.m2_data import metrics as M
    from backend.analysis.m3_selection import screen as S
    from backend.analysis.schemas.selection import Rejected

    assert not M.eligible("return_12m_1m", -0.04) and not M.eligible("return_12m_1m", 0.0) and M.eligible("return_12m_1m", 0.12)
    assert M.eligible_range_ko("return_12m_1m") == "0% 초과" and "낮은 절반" in M.eligible_range_ko("vol_60d")
    rejected: list[Rejected] = []
    pool = [("A", 0.18), ("B", 0.22), ("C", 0.31), ("D", 0.49), ("E", 0.45), ("F", 0.60)]
    kept = S._low_vol_half(pool, {"F"}, rejected)
    assert [t for t, _ in kept] == ["A", "B", "C", "F"] and [r.ticker for r in rejected] == ["D", "E"]
    assert rejected[0].reason.startswith("metric_out_of_range(vol_60d=0.49, 후보 중앙값 0.31")


def test_balance_sheet_reader_is_point_in_time():
    """재무상태표는 공시일(report_date)이 기준일 이하인 가장 최근 회계기간만 읽는다. 부채총계가 빈 회사는 자산총계 − 자본총계로 부채비율을 잰다."""
    import datetime as dt

    from backend.analysis.m2_data.market_data import MarketDataView
    from backend.db import open_repository
    from backend.schemas.market_ext import AssetInfo, FinancialRow

    repo = open_repository("sqlite://")
    repo.upsert_assets([AssetInfo(asset_id="US-AAA", ticker="AAA", name="A", market="US", currency="USD", yfinance_symbol="AAA"),
                        AssetInfo(asset_id="US-BBB", ticker="BBB", name="B", market="US", currency="USD", yfinance_symbol="BBB")])  # fmt: skip
    at = dt.datetime(2026, 1, 1, tzinfo=dt.UTC)

    def row(aid, period, end, disclosed, metric, v):
        return FinancialRow(asset_id=aid, source="SEC_EDGAR", period=period, metric=metric, value=v, period_end=end, disclosed_at=disclosed, fetched_at=at)

    repo.upsert_financials([
        row("US-AAA", "Q1", dt.date(2025, 3, 31), dt.date(2025, 5, 1), "부채총계", 200.0), row("US-AAA", "Q1", dt.date(2025, 3, 31), dt.date(2025, 5, 1), "자본총계", 100.0),
        row("US-AAA", "Q2", dt.date(2025, 6, 30), dt.date(2025, 8, 1), "부채총계", 900.0), row("US-AAA", "Q2", dt.date(2025, 6, 30), dt.date(2025, 8, 1), "자본총계", 100.0),
        row("US-BBB", "Q1", dt.date(2025, 3, 31), dt.date(2025, 5, 1), "자산총계", 500.0), row("US-BBB", "Q1", dt.date(2025, 3, 31), dt.date(2025, 5, 1), "자본총계", 250.0),
    ])  # fmt: skip
    got = repo.get_balance_sheet_asof(["US-AAA", "US-BBB"], dt.date(2025, 7, 15), ("부채총계", "자본총계", "자산총계"))
    assert got["US-AAA"]["부채총계"] == 200.0 and got["US-AAA"]["period_end"] == dt.date(2025, 3, 31)  # 8월에 나온 2분기는 아직 안 보인다
    md = type("MD", (), {})()
    md.repo, md.s, md.asset_id = repo, _FakeView().s, (lambda t: f"US-{t}")
    view = MarketDataView(md, dt.date(2025, 8, 15))
    assert view.debt_to_equity(["AAA", "BBB", "CCC"]) == {"AAA": 9.0, "BBB": 1.0, "CCC": None}


def _db_error() -> RepositoryError:
    class DriverError(Exception):
        pass

    try:
        try:
            raise DriverError(f"(psycopg.OperationalError) failed to resolve host '{HOST}'\n(Background on this error at: https://sqlalche.me/e/20/e3q8)")
        except DriverError as e:
            raise RepositoryError(f"종목 매핑 조회 실패: {e}", code="REPO_READ_FAILED", details={"what": "종목 매핑"}) from e
    except RepositoryError as exc:
        return exc


def test_user_facing_errors_and_health_do_not_show_the_db_host(monkeypatch):
    """DB 연결 오류는 무엇이 실패했는지와 한국어 안내만, 다른 문장도 주소·호스트·IP 를 지운다. /health 저장소 설명에도 호스트·계정이 없다."""
    err = _db_error()
    msg = public_message(err)
    assert HOST not in msg and "psycopg" not in msg and msg.startswith("종목 매핑 조회 실패: 팀 DB 에서 자료를 읽지 못했습니다")
    s = redact(f"연결 실패 postgresql://reader:pw@{HOST}:5432/db, 10.0.12.7:5432 (Background on this error at: https://sqlalche.me/e/20/e3q8)")
    assert HOST not in s and "pw@" not in s and "10.0.12.7" not in s and "sqlalche" not in s and s.startswith("연결 실패")
    plain = "BRK.B 비중 10.5% · psycopg.OperationalError · data/analysis_results.db"
    assert redact(plain) == plain  # 종목·숫자·모듈 이름은 그대로
    app = FastAPI()
    install(app)

    @app.get("/boom")
    def boom():
        raise err

    r = TestClient(app).get("/boom")
    assert r.status_code == 503 and HOST not in r.text and r.json()["error"]["message_ko"] == msg
    monkeypatch.setattr(dbconn, "database_url", lambda: f"postgresql+psycopg://reader:secret@{HOST}:5432/myfinsight?sslmode=require")
    monkeypatch.setattr(dbconn, "results_url", lambda _u: "sqlite:///data/analysis_results.db")
    assert dbconn.describe() == "읽기 PostgreSQL / 결과 SQLite data/analysis_results.db"


def test_grouped_citations_are_split_one_id_per_bracket():
    """'[ev1, ev2]' 처럼 묶은 인용을 '[ev1][ev2]' 로 — 묶어 적은 시장 분석이 '인용 없음' 으로 리포트 검사에 걸려 실행이 실패했다 (평가 074).
    인용 id 가 아닌 괄호는 그대로 둔다."""
    from backend.analysis.common.citations import CITE_RE, split_grouped, split_grouped_in

    text = "사고 보도 [ev1269587, ev1269569]. 계산 [calc:cagr:x，fin:US-A:roe_ttm:2025-01-01] 그대로 [ev1] [보통 괄호, 글]"
    out = split_grouped(text)
    assert out == "사고 보도 [ev1269587][ev1269569]. 계산 [calc:cagr:x][fin:US-A:roe_ttm:2025-01-01] 그대로 [ev1] [보통 괄호, 글]"
    assert CITE_RE.findall(out) == ["ev1269587", "ev1269569", "calc:cagr:x", "fin:US-A:roe_ttm:2025-01-01", "ev1"]
    ans = {"market_ko": ["a [ev1, dc2]"], "x": {"y": "b [ev3、ev4]"}}
    assert split_grouped_in(ans) is ans and ans == {"market_ko": ["a [ev1][dc2]"], "x": {"y": "b [ev3][ev4]"}}


def test_high_margin_idea_keeps_margins_above_the_universe_median():
    """'이익률이 높은' → 영업이익률(최근 4개 분기)이 같은 유니버스(같은 시장) 비금융 종목의 중앙값 이상만. 금융은 재지 않고, 자료가 없으면 남기고,
    필수 포함은 남기고 알린다 (평가: 퀄리티 아이디어 28개의 공통 문구인데 ROE·부채비율로만 재 '이익률은 재지 않음' 으로 E2 감점).
    예전에는 테마 후보끼리 비교해 이익률 33% 인 GOOGL 이 빅테크 후보 중앙값 33.2% 에 0.1%p 모자라 빠졌다 (2026-11 평가 019·063)."""
    from backend.analysis.common.warnings import from_text, guard_reason_ko
    from backend.analysis.m3_selection.intent import idea_screen_guards
    from backend.analysis.m3_selection.screen import _idea_guards
    from backend.analysis.settings import AnalysisSettings

    for idea, on in (("재무가 탄탄하고 이익률이 높은 회사 위주로", True), ("마진이 좋은 기업", True), ("배당수익률이 높은 종목", False)):
        scr: dict = {}
        idea_screen_guards({"natural_language": {"idea": idea}}, scr, AnalysisSettings())
        assert scr["high_margin"] is on, idea
    margin = {"A": 0.40, "B": 0.30, "C": 0.20, "D": 0.10, "E": 0.05, "F": 0.15, "G": 0.25, "BANK": 0.01, "UNK": None, "MUST": 0.02}
    view = _FakeView(margin=margin)
    desc = _FakeDesc({"BANK": "40"}, universe=list(margin))  # 유니버스 비금융 값 [0.02 … 0.40] 8개의 중앙값 (0.15 + 0.20) / 2 = 0.175
    rej, warns = _idea_guards(view, desc, {"high_margin": True}, ["A", "B", "C", "D", "E", "BANK", "UNK", "MUST"], {"MUST"})
    assert {r.ticker for r in rej} == {"D", "E"}  # C(0.20) 는 후보끼리 보면 가운데지만 유니버스 중앙값 0.175 이상이라 남는다
    assert any(w.startswith("must_include MUST: operating_margin(") for w in warns)
    note = from_text("05_selection", next(w for w in warns if w.startswith("profit margin: dropped")))
    assert note.code == "low_margin_dropped" and note.level == "user" and "17.5%" in note.message_ko and "D 10.0%, E 5.0%" in note.message_ko
    assert "같은 유니버스" in note.message_ko
    assert from_text("05_selection", next(w for w in warns if "unknown" in w)).code == "margin_unknown"
    assert guard_reason_ko("operating_margin(0.1000<0.1750)") == "영업이익률 10.0%로 중앙값 17.5% 미만 (이익률 조건)"
    # 예전 원문(후보 중앙값)도 읽는다
    assert from_text("05_selection", "profit margin: dropped 1 below candidates' median operating margin 0.2000 [D 10.0%]").code == "low_margin_dropped"


def test_income_reader_sums_the_last_four_disclosed_quarters():
    """손익은 공시일(report_date)이 기준일 이하인 최근 4개 분기의 합 (TTM). 아직 공시 안 된 분기는 넣지 않고, 4개 분기가 모자라면 값이 없다."""
    import datetime as dt

    from backend.analysis.m2_data.market_data import MarketDataView
    from backend.db import open_repository
    from backend.schemas.market_ext import AssetInfo, FinancialRow

    repo = open_repository("sqlite://")
    repo.upsert_assets([AssetInfo(asset_id="US-AAA", ticker="AAA", name="A", market="US", currency="USD", yfinance_symbol="AAA"),
                        AssetInfo(asset_id="US-BBB", ticker="BBB", name="B", market="US", currency="USD", yfinance_symbol="BBB")])  # fmt: skip
    at = dt.datetime(2026, 1, 1, tzinfo=dt.UTC)
    ends = [dt.date(2024, 12, 31), dt.date(2025, 3, 31), dt.date(2025, 6, 30), dt.date(2025, 9, 30), dt.date(2025, 12, 31)]
    rows = []
    for i, e in enumerate(ends):  # 분기 끝 40일 뒤 공시, 매출 100·200·300·400·500, 영업이익 10·20·30·40·50
        rows += [FinancialRow(asset_id="US-AAA", source="SEC_EDGAR", period=f"Q{i}", metric=m, value=v, period_end=e, disclosed_at=e + dt.timedelta(days=40), fetched_at=at)
                 for m, v in (("매출액(분기)", 100.0 * (i + 1)), ("영업이익(분기)", 10.0 * (i + 1)))]  # fmt: skip
    rows += [FinancialRow(asset_id="US-BBB", source="SEC_EDGAR", period="Q1", metric=m, value=v, period_end=ends[1], disclosed_at=ends[1] + dt.timedelta(days=40), fetched_at=at)
             for m, v in (("매출액(분기)", 100.0), ("영업이익(분기)", 30.0))]  # fmt: skip
    repo.upsert_financials(rows)
    got = repo.get_income_ttm_asof(["US-AAA", "US-BBB"], dt.date(2025, 12, 1))
    assert got["US-AAA"]["매출액(분기)"] == 100 + 200 + 300 + 400 and got["US-AAA"]["period_end"] == dt.date(2025, 9, 30)  # 2025-12 분기는 아직 공시 전
    assert "US-BBB" not in got  # 1개 분기뿐
    md = type("MD", (), {})()
    md.repo, md.s, md.asset_id = repo, _FakeView().s, (lambda t: f"US-{t}")
    assert MarketDataView(md, dt.date(2026, 3, 1)).operating_margin_ttm(["AAA", "BBB"]) == {"AAA": 0.1, "BBB": None}


def test_user_floor_notice_names_theme_candidates_dropped_by_the_users_own_limits():
    """사용자가 정한 최소 시가총액·거래대금 때문에 빠진 테마 관련 종목을 공지로 (평가 081: 농심·오뚜기가 리포트 깔때기에만 있고 공지가 없었다). 넓은 테마는 내지 않는다."""
    from backend.analysis.common.warnings import from_text
    from backend.analysis.m3_selection.retrieve import floor_warnings
    from backend.analysis.schemas.selection import Candidates, FilteredOut

    cand = Candidates(request_id="r", as_of="2026-01-02", candidates=[], filtered_out=[FilteredOut(ticker="004370.KS", reason="min_avg_daily_volume_usd"),
                      FilteredOut(ticker="ZZZ", reason="keyword_weak")], stats={}, warnings=[])  # fmt: skip
    desc = type("D", (), {"by_ticker": staticmethod(lambda t: {"name": "농심"} if t == "004370.KS" else None)})()
    warns = floor_warnings(cand, {"min_avg_daily_volume_usd": 10_000_000}, desc, broad=False)
    note = from_text("03_candidates", warns[0])
    assert note.code == "user_floor_dropped" and note.level == "user" and "최소 일평균 거래대금" in note.message_ko and "농심" in note.message_ko
    assert floor_warnings(cand, {"min_avg_daily_volume_usd": 10_000_000}, desc, broad=True) == []


def test_us_company_idea_adds_a_headquarters_boundary_to_themes():
    """'미국 기업' 이라고 하면 테마 경계에 '본사가 미국이 아닌 기업은 넣지 않음' 을 붙인다 — 분류가 본사로 판정하게 (평가 075: 네덜란드 본사 NBIS 가 선정).
    '미국 시장 전체' 처럼 회사를 말하지 않으면 붙이지 않고, 이미 본사 조건이 있으면 그대로 둔다."""
    from backend.analysis.m3_selection.intent import us_headquarters_boundary

    themes = [{"id": "cloud", "description_ko": "포함: 클라우드 기업. 넣지 않음: 광고."}, {"id": "x", "description_ko": "포함: 미국 본사 기업만."}]
    warns = us_headquarters_boundary({"natural_language": {"idea": "클라우드·소프트웨어 플랫폼 미국 기업 중 최근 주가 흐름이 강한 종목"}}, themes)
    assert themes[0]["description_ko"].endswith("본사가 미국이 아닌 기업(미국에 상장한 해외 기업)은 넣지 않음.") and len(warns) == 1
    assert themes[1]["description_ko"] == "포함: 미국 본사 기업만."
    t2 = [{"id": "all", "description_ko": "포함: 업종에 관계없이 모든 기업."}]
    assert us_headquarters_boundary({"natural_language": {"idea": "특정 테마 없이 미국 시장 전체에서 재무가 탄탄한 기업 위주로"}}, t2) == []
    assert us_headquarters_boundary({"natural_language": {"idea": "미국 빅테크 대형주 중 최근 주가 흐름이 강한 종목"}}, [{"id": "b", "description_ko": "포함: 빅테크."}])


def test_dividend_and_per_selection_need_to_beat_the_universe_median(monkeypatch):
    """고배당은 배당수익률이 같은 유니버스(같은 시장) 종목 중앙값 이상, 저PER 은 PER 이 중앙값 이하인 종목에서만 고른다 (2026-11 평가 사용자 결정).
    후보가 목표보다 적어 모두 담을 때 배당 0.12% 인 CEG 가 '배당을 많이 주는', PER 25.5 인 카카오뱅크가 '실적 대비 싼' 종목으로 들어갔다.
    시장마다 따로 재고, 필수 포함은 남기고 알리며, 값이 5개 미만이면 거르지 않는다."""
    import pandas as pd

    from backend.analysis.common.warnings import _out_of_range_ko
    from backend.analysis.m2_data import metrics as M
    from backend.analysis.m3_selection.screen import _style_floor

    dy = {"U1": 0.01, "U2": 0.015, "U3": 0.02, "U4": 0.025, "U5": 0.03, "U6": 0.04, "U7": 0.05,  # 미국 중앙값 0.025
          "K1.KS": 0.03, "K2.KS": 0.04, "K3.KS": 0.05, "K4.KS": 0.06, "K5.KS": 0.07}  # 한국 중앙값 0.05
    monkeypatch.setitem(M.METRICS, "dividend_yield_ttm", lambda view, tks: (pd.Series({t: dy[t] for t in tks if t in dy}, dtype=float), []))
    view, desc = _FakeView(), _FakeDesc({}, universe=list(dy))
    rejected, warnings = [], []
    keep = _style_floor(view, desc, "dividend_yield_ttm", [("U7", 0.05), ("U5", 0.03), ("U3", 0.02), ("CEG", 0.0012), ("MUST", 0.01), ("K4.KS", 0.06), ("K1.KS", 0.03)],
                        {"MUST"}, rejected, warnings)
    assert [t for t, _ in keep] == ["U7", "U5", "MUST", "K4.KS"]  # K1.KS 0.03 은 미국이면 남지만 한국 중앙값 0.05 미만
    assert {r.ticker for r in rejected} == {"U3", "CEG", "K1.KS"} and all(r.reason.startswith("metric_out_of_range(") for r in rejected)
    assert any(w.startswith("must_include MUST: metric_out_of_range(dividend_yield_ttm=0.01, 시장 중앙값 0.025 미만)") for w in warnings)
    txt = _out_of_range_ko(next(r for r in rejected if r.ticker == "CEG").reason[len("metric_out_of_range("):].rstrip(")"))
    assert "같은 유니버스 중앙값" in txt and "미만" in txt and txt.startswith("배당수익률")
    pe = {"U1": 8.0, "U2": 10.0, "U3": 12.0, "U4": 14.0, "U5": 16.0, "U6": 20.0, "U7": 30.0}  # 중앙값 14
    monkeypatch.setitem(M.METRICS, "pe_ttm", lambda view, tks: (pd.Series({t: pe[t] for t in tks if t in pe}, dtype=float), []))
    rejected = []
    keep = _style_floor(view, _FakeDesc({}, universe=list(pe)), "pe_ttm", [("B1", 6.0), ("B2", 14.0), ("KAKAOBANK", 25.5)], set(), rejected, [])
    assert [t for t, _ in keep] == ["B1", "B2"] and [r.ticker for r in rejected] == ["KAKAOBANK"] and "초과" in rejected[0].reason
    rejected = []  # 유니버스 값이 5개 미만이면 중앙값을 믿지 않고 거르지 않는다
    assert len(_style_floor(view, _FakeDesc({}, universe=["U1", "U2", "U3"]), "pe_ttm", [("KAKAOBANK", 25.5)], set(), rejected, [])) == 1 and not rejected


def test_us_company_idea_drops_companies_domiciled_abroad():
    """'미국 기업' 아이디어 → 법인 소재지가 미국 밖인 기업(회사 소개 첫 문장의 정식 이름이 plc·N.V.·Ltd 등)을 뺀다.
    분류(04)가 테마 경계 문장을 놓쳐 MDT·ACN·AMCR·LIN·STE 가 '미국 기업' 에 들어갔다 (2026-11 평가 7건). 한국 종목·예외(미국 법인 WYNN)·필수 포함은 그대로."""
    from backend.analysis.common.warnings import from_text, guard_reason_ko
    from backend.analysis.m3_selection.intent import idea_screen_guards
    from backend.analysis.m3_selection.screen import _idea_guards, foreign_domicile
    from backend.analysis.settings import AnalysisSettings

    for idea, on in (("미국 헬스케어와 제약·바이오 기업 중", True), ("배당을 꾸준히 늘려 온 미국 기업", True), ("국내 은행·금융지주 중", False)):
        scr: dict = {}
        idea_screen_guards({"natural_language": {"idea": idea}}, scr, AnalysisSettings())
        assert scr["us_hq_only"] is on, idea
    assert foreign_domicile("Medtronic plc develops, manufactures, and sells") == "plc"
    assert foreign_domicile("Amcor plc, through its subsidiaries, develops") == "plc"
    assert foreign_domicile("LyondellBasell Industries N.V. operates as a chemical company") == "N.V."
    assert foreign_domicile("Smurfit Westrock Plc, together with its subsidiaries") == "Plc"
    assert foreign_domicile("Apple Inc. designs, manufactures, and markets smartphones") is None
    assert foreign_domicile("MercadoLibre, Inc. operates online commerce platforms") is None
    intros = {"MDT": "Medtronic plc develops medical therapies.", "AAPL": "Apple Inc. designs smartphones.", "WYNN": "Wynn Resorts, Limited, together with its subsidiaries, designs resorts.",
              "LIN": "Linde plc operates as an industrial gas company.", "005930.KS": "Samsung Electronics Co., Ltd. engages in consumer electronics."}
    rej, warns = _idea_guards(_FakeView(), _FakeDesc({}, intros=intros), {"us_hq_only": True}, ["MDT", "AAPL", "WYNN", "LIN", "005930.KS"], {"LIN"})
    assert [r.ticker for r in rej] == ["MDT"] and rej[0].reason == "foreign_domicile(plc)"
    assert any(w.startswith("must_include LIN: foreign_domicile(plc), kept") for w in warns)
    note = from_text("05_selection", next(w for w in warns if w.startswith("us headquarters: dropped")))
    assert note.code == "foreign_hq_dropped" and note.level == "user" and "MDT" in note.message_ko and "미국 기업 조건" in note.message_ko
    assert "법인 소재지가 미국 밖" in guard_reason_ko("foreign_domicile(plc)")
    assert _idea_guards(_FakeView(), _FakeDesc({}, intros=intros), {"us_hq_only": False}, ["MDT"], set())[0] == []


def test_style_floor_keeps_the_better_half_when_every_candidate_misses_the_median(monkeypatch):
    """테마 후보가 모두 유니버스 중앙값 밖이면(인터넷·게임 저PER, 2026-11 평가 003: NAVER PER 20·카카오 40, KOSPI 중앙값 13.8) 분석할 종목이 없어진다
    → 그 시장 후보 중 나은 절반만 고르고 알린다. 하나라도 기준선 안이면 대체하지 않는다."""
    import pandas as pd

    from backend.analysis.common.warnings import from_text
    from backend.analysis.m2_data import metrics as M
    from backend.analysis.m3_selection.screen import _style_floor

    pe = {"K1.KS": 8.0, "K2.KS": 10.0, "K3.KS": 13.8, "K4.KS": 15.0, "K5.KS": 20.0}  # 중앙값 13.8
    monkeypatch.setitem(M.METRICS, "pe_ttm", lambda view, tks: (pd.Series({t: pe[t] for t in tks if t in pe}, dtype=float), []))
    view, desc = _FakeView(), _FakeDesc({}, universe=list(pe))
    rejected, warnings = [], []
    keep = _style_floor(view, desc, "pe_ttm", [("035420.KS", 20.0), ("035720.KS", 40.2)], set(), rejected, warnings)
    assert [t for t, _ in keep] == ["035420.KS"] and [r.ticker for r in rejected] == ["035720.KS"]
    note = from_text("05_selection", next(w for w in warnings if w.startswith("style floor:")))
    assert note.code == "style_floor_fallback" and note.level == "user" and "PER이 같은 유니버스 중앙값" in note.message_ko and "035420.KS" in note.message_ko
    rejected, warnings = [], []  # 하나라도 기준선 안이면 기준선 그대로
    keep = _style_floor(view, desc, "pe_ttm", [("B1.KS", 9.0), ("035720.KS", 40.2)], set(), rejected, warnings)
    assert [t for t, _ in keep] == ["B1.KS"] and not any(w.startswith("style floor:") for w in warnings)


def test_explain_requires_a_card_for_every_selected_ticker():
    """기업별 근거는 선정 종목마다 카드 하나 — 빠진 종목이 있으면 첫 답을 되돌린다 (2026-11 평가 077: 7종목 중 1종목만 쓴 답이 통과)."""
    from backend.analysis.m3_selection.explain import missing_cards

    ans = {"per_ticker": [{"ticker": "A", "rationale_ko": "근거 [fin:US-A:roe_ttm:2026-01-02]"}, {"ticker": "B", "rationale_ko": "  "}]}
    assert missing_cards(ans, {"A", "B", "C"}) == ["B", "C"]
    assert missing_cards({"per_ticker": [{"ticker": "A", "rationale_ko": "x"}]}, {"A"}) == []
