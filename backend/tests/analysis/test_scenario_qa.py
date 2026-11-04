"""2026-11 시나리오 QA 회귀 테스트. 라운드 0: 뉴스 뷰(방향·강도 → 코드가 사전 기대 대비 수치) · BL 최적화 공분산 · δ 하한 순서 · 뷰 적중."""

from __future__ import annotations

import datetime as dt

import numpy as np
import pandas as pd
import pytest

from backend.analysis.m4_portfolio import black_litterman as BL
from backend.analysis.m4_portfolio import math as P
from backend.analysis.m4_portfolio.views import _quantify
from backend.analysis.m5_backtest_report import backtest_metrics as M
from backend.analysis.settings import AnalysisSettings
from backend.tests.analysis.test_dialog import svc_factory  # noqa: F401
from backend.tests.analysis.test_pipeline_e2e import e2e  # noqa: F401

PS = AnalysisSettings().portfolio


def _mm(delta: float = 2.5):
    tk = ["T0", "T1", "T2", "T3"]
    vol = np.array([0.20, 0.25, 0.30, 0.35])
    corr = np.full((4, 4), 0.3)
    np.fill_diagonal(corr, 1.0)
    cov = np.outer(vol, vol) * corr
    wb = np.array([0.25, 0.25, 0.25, 0.25])
    pi = delta * cov @ wb  # 기준 비중의 역최적화 (market_model.py 와 같은 식)
    mm = {"tickers": tk, "cov": cov.tolist(), "ann_vol": dict(zip(tk, vol.tolist(), strict=True)),
          "implied_returns": dict(zip(tk, pi.tolist(), strict=True)), "delta": delta, "tau": 0.05, "shrinkage": {}, "invested_total": 1.0}  # fmt: skip
    base = {"chosen_baseline": "equal_weight", "portfolios": [{"id": "equal_weight", "weights": dict(zip(tk, wb.tolist(), strict=True)), "cash_weight": 0.0}]}
    return mm, base


def _bl_args(monkeypatch, views, *, max_tilt=0.05):
    mm, base = _mm()
    monkeypatch.setattr(BL, "sector_lists", lambda desc, tk: (["45", "45", "60", "25"], ["IT", "IT", "RE", "CD"]))
    req = {"request_id": "r", "constraints": {"max_weight_per_stock": 0.6, "max_weight_per_sector": 1.0}}
    intent = {"news_tilt": {"enabled": True, "max_tilt_per_stock": max_tilt}}
    sets = [{"scenario_id": "s", "title_ko": "t", "narrative_ko": "n", "views": views}]
    return mm, base, sets, req, intent, None, AnalysisSettings()


def test_quantify_absolute_up_down_and_relative():
    mm, _ = _mm()
    pi, w = mm["implied_returns"], []
    up = {"type": "absolute", "long": ["T1"], "short": [], "direction": "up", "strength": "medium"}
    _quantify(up, mm, mm["tickers"], PS, w, "s")
    assert up["prior_return"] == round(pi["T1"], 6)
    assert up["expected_return_annual"] == pytest.approx(pi["T1"] + 0.20 * 0.25, abs=1e-6)
    dn = {"type": "absolute", "long": ["T1"], "short": [], "direction": "down", "strength": "strong"}
    _quantify(dn, mm, mm["tickers"], PS, w, "s")
    assert dn["expected_return_annual"] == pytest.approx(pi["T1"] - 0.35 * 0.25, abs=1e-6)
    rel = {"type": "relative", "long": ["T0"], "short": ["T3"], "strength": "weak"}
    _quantify(rel, mm, mm["tickers"], PS, w, "s")
    sig = np.sqrt(0.20**2 + 0.35**2 - 2 * 0.3 * 0.20 * 0.35)
    spread = pi["T0"] - pi["T3"]  # 음수: 사전에는 T3 가 더 높다
    assert rel["prior_return"] == pytest.approx(spread, abs=1e-6) and spread < 0
    assert rel["expected_return_annual"] == pytest.approx(spread + 0.10 * sig, abs=1e-6)  # 사전 차이를 long 쪽으로 k·σ 만큼 (약한 뷰는 작게)
    assert rel["direction"] == "up" and not w


def test_quantify_legacy_number_and_relative_down():
    mm, _ = _mm()
    w: list[str] = []
    old = {"type": "absolute", "long": ["T0"], "short": [], "expected_return_annual": 0.03}  # 옛 응답: 방향 없이 '좋은 소식 +3%'
    _quantify(old, mm, mm["tickers"], PS, w, "s")
    assert old["direction"] == "up" and old["strength"] == "medium" and old["expected_return_annual"] > old["prior_return"]
    rel = {"type": "relative", "long": ["T0"], "short": ["T1"], "direction": "down", "strength": "medium"}
    _quantify(rel, mm, mm["tickers"], PS, w, "s")
    assert rel["long"] == ["T1"] and rel["short"] == ["T0"] and rel["direction"] == "up"
    assert any("no direction" in x for x in w) and any("rewritten" in x for x in w)


def test_positive_view_raises_weight_and_negative_view_lowers_it(monkeypatch):
    """C1 회귀: 사전 기대보다 낮은 '긍정' 숫자 때문에 비중이 줄던 문제. 방향대로 움직여야 한다."""
    mm, _ = _mm()
    for direction, sign in (("up", 1), ("down", -1)):
        v = {"type": "absolute", "long": ["T2"], "short": [], "direction": direction, "strength": "medium", "confidence": 0.5,
             "evidence_ids": ["ev1", "ev2"], "rationale_ko": "r"}  # fmt: skip
        _quantify(v, mm, mm["tickers"], PS, [], "s")
        ports, _, _ = BL.build_bl(*_bl_args(monkeypatch, [v]))
        d = ports[0]["delta_vs_baseline"]["T2"]
        assert sign * d > 0.005, (direction, d)
        assert "사전 기대" in ports[0]["views_applied"][0]["summary_ko"]


def test_negligible_confidence_keeps_baseline_weights(monkeypatch):
    """사후 공분산(Σ+M)으로 최적화하면 뷰가 거의 없어도 최소분산 쪽으로 쏠렸다. 사전 Σ 를 쓰면 기준 비중 그대로."""
    mm, _ = _mm()
    v = {"type": "absolute", "long": ["T0"], "short": [], "direction": "up", "strength": "weak", "confidence": 1e-6,
         "evidence_ids": ["ev1", "ev2"], "rationale_ko": "r"}  # fmt: skip
    _quantify(v, mm, mm["tickers"], PS, [], "s")
    ports, _, _ = BL.build_bl(*_bl_args(monkeypatch, [v]))
    assert max(abs(x) for x in ports[0]["delta_vs_baseline"].values()) < 1e-4


def test_failed_optimizer_marks_set_without_view_text(monkeypatch):
    from types import SimpleNamespace

    mm, _ = _mm()
    v = {"type": "absolute", "long": ["T0"], "short": [], "direction": "up", "strength": "weak", "confidence": 0.4,
         "evidence_ids": ["ev1", "ev2"], "rationale_ko": "r"}  # fmt: skip
    _quantify(v, mm, mm["tickers"], PS, [], "s")
    monkeypatch.setattr(P, "minimize", lambda *a, **kw: SimpleNamespace(success=False, message="forced"))
    ports, warns, _ = BL.build_bl(*_bl_args(monkeypatch, [v]))
    p = ports[0]
    assert p["views_applied"] == [] and "뷰 미반영" in p["name_ko"] and "[절대]" not in (p["portfolio_view"] or "")
    assert p["posterior_returns"] == {t: round(x, 6) for t, x in mm["implied_returns"].items()}
    assert any("optimizer failed" in w for w in warns)


def test_view_hit_follows_direction_and_waits_for_full_window():
    idx = pd.bdate_range("2023-01-02", periods=300)
    px = pd.DataFrame({"A": np.linspace(100, 115, 300), "B": np.linspace(100, 104, 300)}, index=idx)
    up = {"type": "absolute", "long": ["A"], "short": [], "direction": "up", "prior_return": 0.10, "expected_return_annual": 0.15}
    dn = {"type": "absolute", "long": ["B"], "short": [], "direction": "down", "prior_return": 0.10, "expected_return_annual": 0.05}
    rel = {"type": "relative", "long": ["A"], "short": ["B"], "direction": "up", "prior_return": 0.0, "expected_return_annual": 0.05}
    full = M.view_diagnostics([up, dn, rel], px, idx[0], idx[-1], {}, horizon_days=200)
    assert [r["hit"] for r in full] == [True, True, True] and not any(r["pending"] for r in full)
    short = M.view_diagnostics([up], px, idx[-60], idx[-1], {}, horizon_days=365)
    assert short[0]["hit"] is None and short[0]["pending"]
    partial = M.view_diagnostics([up], px, idx[-60], idx[-1], {}, horizon_days=365, require_full=False)
    assert partial[0]["partial"] and partial[0]["hit"] is not None


def test_delta_floor_applies_before_profile_multipliers(monkeypatch, seeded_repo, descriptor_dir):
    """시장 δ 가 음수인 날: 예전에는 성향과 무관하게 1.5. 이제는 max(δ, 하한) × 성향 × 낙폭 배수."""
    from backend.analysis.m2_data import descriptor as D
    from backend.analysis.m2_data.market_data import MarketData
    from backend.analysis.m4_portfolio.market_model import build_market_model
    from backend.analysis.settings import replace_settings
    from backend.tests.analysis.test_pipeline_e2e import REQUEST

    s = AnalysisSettings()
    s = replace_settings(s, portfolio=replace_settings(s.portfolio, lookback_days=252, min_history_days_for_model=120),
                         market=replace_settings(s.market, descriptor_dir=str(descriptor_dir), valuation_max_staleness_days=10))  # fmt: skip
    view = MarketData(seeded_repo, s).view(dt.date(2025, 12, 31))
    desc, _i, _w = D.load_for(dt.date(2025, 12, 31), ["SP500", "NASDAQ100"], ["US"], processed_dir=str(descriptor_dir))
    monkeypatch.setattr(P, "market_implied_delta", lambda *a, **kw: (-0.4, {"start": "2023-01-01", "end": "2025-12-30"}))
    req = {**REQUEST, "risk": {**REQUEST["risk"], "risk_tolerance": "conservative", "max_drawdown_tolerance": 0.10},
           "derived": {"as_of": "2025-12-31", "initial_amount_usd": 10000.0}}  # fmt: skip
    mm, _ = build_market_model(view, ["NVDA", "AMD", "JPM", "XOM"], req, desc, s, request_id="r")
    assert mm["delta_base"] == s.portfolio.delta_floor
    assert mm["delta"] == pytest.approx(s.portfolio.delta_floor * 1.5 * 1.5, abs=1e-4)  # 보수 1.5 × 허용 낙폭 10% → 1.5


# ───────────────────────── 라운드 1 (시나리오 000·001) ─────────────────────────
def test_backtest_fx_uses_first_trading_day_when_start_is_weekend(seeded_repo, descriptor_dir):
    """000: 백테스트 시작일(2022-06-25)이 토요일이면 시작일 환율 대신 기준일 환율로 떨어졌다."""
    from backend.analysis.m1_request.derive import derive
    from backend.analysis.m2_data.market_data import MarketData
    from backend.analysis.settings import replace_settings
    from backend.tests.analysis.test_pipeline_e2e import REQUEST

    s = AnalysisSettings()
    s = replace_settings(s, portfolio=replace_settings(s.portfolio, lookback_days=252, min_history_days_for_model=120),
                         market=replace_settings(s.market, descriptor_dir=str(descriptor_dir), valuation_max_staleness_days=10))  # fmt: skip
    md = MarketData(seeded_repo, s)
    req = {**REQUEST, "capital": {**REQUEST["capital"], "currency": "KRW", "initial_amount": 30_000_000, "monthly_contribution": 0},
           "horizon": {**REQUEST["horizon"], "start_date": "2025-12-31", "backtest_years": 3}}  # fmt: skip
    d = derive(req, md, s).derived
    assert d.backtest_start == dt.date(2022, 12, 31) and d.backtest_start.weekday() == 5
    first_day = md.view(d.as_of).trading_days(d.backtest_start, d.as_of, markets=d.markets)[0].date()
    assert d.backtest_fx_date == md.view(first_day).fx_on_or_before(first_day).date and d.backtest_start < first_day <= dt.date(2023, 1, 6)


def test_exclude_keywords_need_two_hits_in_name_or_intro_and_skip_negations():
    from types import SimpleNamespace

    from backend.analysis.m3_selection.retrieve import _exclude_keyword_hits

    desc = SimpleNamespace(stocks=[
        {"yfinance_symbol": "KO", "name": "Coca-Cola", "intro": "Maker of soft drinks and non-alcoholic beverages.", "keywords": ["tobacco", "beverage"]},
        {"yfinance_symbol": "BF-B", "name": "Brown-Forman", "intro": "Producer of whiskey and other alcoholic beverages.", "keywords": []},
        {"yfinance_symbol": "CAT", "name": "Caterpillar", "intro": "Construction machinery and natural gas engines.", "keywords": []},
    ])  # fmt: skip
    hits = _exclude_keyword_hits(desc, ["alcoholic beverages", "whiskey", "liquor"])
    assert "KO" not in hits and hits["BF-B"] == {"alcoholic beverages", "whiskey"}
    fossil = _exclude_keyword_hits(desc, ["natural gas", "coal", "oil"])
    assert fossil.get("CAT") == {"natural gas"}  # 1개뿐 → retrieve 는 하드 제외하지 않는다 (04 가 판단)


def test_broad_theme_does_not_filter_by_llm_theme_judgement():
    from backend.analysis.common.llm import StubLlm
    from backend.analysis.m3_selection.classify import classify
    from backend.analysis.schemas.selection import Candidates

    def cand(t):
        return {"ticker": t, "name": t, "market": "US", "gics": {"sector": {"code": "30", "name": "Staples"}, "industry_group": {"code": "3020", "name": "x"},
                "industry": {"code": "302020", "name": "x"}, "sub_industry": {"code": "30202030", "name": "x"}}, "company_summary": "s", "matched_by": ["gics"],
                "matched_themes": ["hd"], "forced": False}  # fmt: skip

    cands = Candidates.model_validate({"request_id": "r", "as_of": "2025-06-25", "candidates": [cand("A"), cand("B"), cand("C")], "filtered_out": [], "stats": {}, "warnings": []})
    intent = {"interpretation": {"themes": [{"id": "hd", "label_ko": "고배당", "description_ko": "d"}]}, "screen": {"theme_filter": {"min_confidence": 0.5}},
              "exclude_theme_rules": [{"theme": "tobacco", "keywords": ["tobacco"]}]}  # fmt: skip
    ans = {"results": [{"ticker": "A", "in_theme": True, "themes": ["hd"], "confidence": 0.9, "reason_ko": "", "excluded_theme": None},
                       {"ticker": "B", "in_theme": False, "themes": [], "confidence": 0.2, "reason_ko": "배당수익률이 낮은 편", "excluded_theme": "없음"},
                       {"ticker": "C", "in_theme": True, "themes": ["hd"], "confidence": 0.9, "reason_ko": "", "excluded_theme": "tobacco"}]}  # fmt: skip
    narrow = classify(cands, intent, StubLlm({"04_classify": ans}))
    broad = classify(cands, intent, StubLlm({"04_classify": ans}), broad=True)
    assert narrow.passed_tickers == ["A"] and sorted(broad.passed_tickers) == ["A", "B"]  # C 는 제외 테마라 넓은 테마에서도 빠진다
    assert any("not an exclude rule" in w for w in broad.warnings)  # B 의 '없음' 은 제외 사유가 아니다


def test_notices_tell_the_real_reason_and_keep_different_numbers():
    from backend.analysis.common.warnings import from_text, merge

    w = from_text("07_backtest_spec", "screen@2022-06-27: must_include PG: metric_missing, kept with metric=nan")
    assert w.code == "must_include_no_metric" and w.message_ko.startswith("백테스트 시작일(2022-06-27)") and "자료가 없어" in w.message_ko
    s = from_text("05_selection", "sector count preference (3/sector, sector cap 50%) skipped higher-ranked ['AVGO', 'CSCO'] (Information Technology) for lower-ranked names in other sectors")
    assert s.code == "sector_preference_skipped" and s.level == "user" and "AVGO, CSCO" in s.message_ko
    a = from_text("05_selection", "weight capacity 0.70 < 0.90: caps cannot absorb")
    b = from_text("07_backtest_spec", "weight capacity 0.60 < 0.90: caps cannot absorb")
    assert len(merge([a, b])) == 2  # 숫자가 다른 공지를 첫 문장 하나로 덮지 않는다


def test_r9_does_not_blame_caps_for_requested_min_cash():
    from backend.analysis.m5_backtest_report.validate import evaluate_checks

    def run(invested, min_cash):
        p = {"id": "x", "kind": "template", "target_weights": {"A": invested / 2, "B": invested / 2}, "headline": {"max_drawdown": -0.1, "cagr": 0.1},
             "metrics": {"composition": {"breaches": [], "max_weight_drift": 0.0, "max_sector_drift": 0.0}, "risk": {"ann_vol": 0.15, "max_drawdown": -0.1}, "return": {"cagr": 0.1, "total_return": 0.1},
                         "vs_benchmark": {"excess_cagr": 0.0}, "trading": {"n_rebalances": 1}},
             "series": {"index": [100, 101]}, "checkpoints": [{"kind": "rebalance", "weights": {"after": {"A": invested / 2, "B": invested / 2}}}]}  # fmt: skip
        crit = {"max_drawdown": 0.2, "match_target": 0.2, "horizon_years": 0, "target_annual_return": 0.05, "benchmark": "SPY", "volatility_preference": "medium",
                "vol_band": 1.0, "max_weight_per_stock": 1.0, "max_weight_per_sector": 1.0, "min_holdings": 1, "min_cash_ratio": min_cash}  # fmt: skip
        cks = evaluate_checks(p, crit, 2, 1, lambda t: "S", 0.5, False, settings=AnalysisSettings())[0]
        return next(c for c in cks if c["rule"] == "R9")

    ok = run(0.85, 0.15)
    assert ok["ok"] and "최소 현금 15%" in ok["message_ko"] and "상한 때문" not in ok["message_ko"]
    bad = run(0.60, 0.15)
    assert not bad["ok"] and "25%" in bad["message_ko"]


def test_current_composition_follows_recommended_rule():
    from backend.analysis.m5_backtest_report.report_blocks import current_composition

    R = {"portfolio": {"forward": {"as_of": "2025-06-25", "baseline": {"id": "equal_weight"},
                                   "templates": [{"id": "equal_weight", "name_ko": "동일비중", "weights": {"A": 0.475, "B": 0.475}},
                                                 {"id": "min_variance", "name_ko": "최소분산", "weights": {"A": 0.7, "B": 0.25}}],
                                   "portfolios": [{"id": "fwd_bl_01", "name_ko": "BL 1", "weights": {"A": 0.5, "B": 0.45}}, {"id": "fwd_bl_02", "name_ko": "BL 2", "weights": {"A": 0.4, "B": 0.55}}],
                                   "chosen_weights": {"A": 0.4, "B": 0.55}},
                       "targets": {"portfolios": []}, "templates": []},
         "backtest": {"portfolios": [{"id": "dd_match_equal_weight", "kind": "matched", "base_id": "equal_weight", "cash_ratio": 0.48, "name_ko": "낙폭 맞춤안"},
                                     {"id": "wf_min_variance", "kind": "template", "name_ko": "최소분산 (walk-forward)"},
                                     {"id": "bl_02", "kind": "black_litterman", "name_ko": "BL 2"}], "benchmarks": [], "benchmark": {"id": "b", "kind": "benchmark"}}}  # fmt: skip
    import backend.analysis.m5_backtest_report.report_blocks as RB

    RB_find = RB.find
    try:
        RB.find = lambda R_, pid: next(p for p in R_["backtest"]["portfolios"] if p["id"] == pid)
        w, cash, name = current_composition(R, "dd_match_equal_weight")
        assert w == pytest.approx({"A": 0.475 * 0.52, "B": 0.475 * 0.52}) and cash == pytest.approx(1 - 0.95 * 0.52)
        assert "주식 49%" in name and "현금 51%" in name  # 이름이 이 구성의 실제 비중
        assert current_composition(R, "wf_min_variance")[0] == {"A": 0.7, "B": 0.25}
        assert current_composition(R, "bl_02")[0] == {"A": 0.4, "B": 0.55}  # 모의투자와 같은 규칙: 분석 기준일의 chosen_weights
    finally:
        RB.find = RB_find


def test_effective_n_ignores_cash():
    w = np.full(4, 0.2125)  # 4종목 85% + 현금 15%
    assert P.ex_ante_stats(w, np.zeros(4), np.eye(4) * 0.04)["effective_n"] == pytest.approx(4.0)


@pytest.mark.parametrize("metric, vals, expect_sel, expect_out", [
    ("pe_ttm", {"A": 5.0, "B": 8.0, "C": 734.0}, ["A", "B"], ["C"]),                       # F11: 저PER 에 PER 734
    ("roe_ttm", {"A": 0.20, "B": 0.10, "C": -0.15}, ["A", "B"], ["C"]),                     # F12: 퀄리티에 ROE 음수
    ("dividend_yield_ttm", {"A": 0.05, "B": 0.0, "C": 20541.4}, ["A"], ["B", "C"]),         # 무배당·자료 오류(000 STX)
])
def test_screen_rejects_values_outside_eligibility(monkeypatch, metric, vals, expect_sel, expect_out):
    from types import SimpleNamespace

    import pandas as pd_

    from backend.analysis.m2_data import metrics as Mx
    from backend.analysis.m3_selection.screen import screen

    monkeypatch.setitem(Mx.METRICS, metric, lambda view, tks: (pd_.Series({t: vals[t] for t in tks}, dtype=float), []))
    desc = SimpleNamespace(by_ticker=lambda t: {"ticker": t, "name": t, "market": "US", "gics": {}})
    tagging = SimpleNamespace(tagged=[SimpleNamespace(ticker=t, confidence=0.9) for t in vals], passed_tickers=list(vals))
    intent = {"screen": {"metric": metric, "direction": "asc" if metric == "pe_ttm" else "desc"}}
    cons = {"num_holdings": {"min": 1, "target": 3, "max": 3}, "max_weight_per_stock": 1.0, "max_weight_per_sector": 1.0, "min_cash_ratio": 0.0}
    sel, _ = screen(SimpleNamespace(as_of=dt.date(2025, 6, 25)), desc, tagging, intent, cons, request_id="r")
    assert sorted(s.ticker for s in sel.selected) == expect_sel
    assert sorted(r.ticker for r in sel.rejected if r.reason.startswith("metric_out_of_range")) == expect_out
    assert any("within eligibility" in w for w in sel.warnings)


def test_overlapping_exclude_keywords_count_once():
    from types import SimpleNamespace

    from backend.analysis.m3_selection.retrieve import _exclude_keyword_hits

    desc = SimpleNamespace(stocks=[{"yfinance_symbol": "X", "name": "X Co", "intro": "Seller of tobacco products in Asia."},
                                   {"yfinance_symbol": "Y", "name": "Y Co", "intro": "Tobacco grower and cigarette maker."}])  # fmt: skip
    hits = _exclude_keyword_hits(desc, ["tobacco", "tobacco products", "cigarette"])
    assert hits["X"] == {"tobacco products"} and hits["Y"] == {"tobacco", "cigarette"}


def test_sector_preference_reason_only_when_displaced(monkeypatch):
    from types import SimpleNamespace

    import pandas as pd_

    from backend.analysis.m2_data import metrics as Mx
    from backend.analysis.m3_selection.screen import screen

    vals = {"A1": 0.9, "A2": 0.8, "A3": 0.7, "B1": 0.6, "A4": 0.5}
    monkeypatch.setitem(Mx.METRICS, "return_12m_1m", lambda view, tks: (pd_.Series({t: vals[t] for t in tks}, dtype=float), []))
    sec = {"A": ("45", "Information Technology"), "B": ("50", "Communication Services")}
    monkeypatch.setattr("backend.analysis.m3_selection.screen.D.gics_model",
                        lambda e: SimpleNamespace(sector=SimpleNamespace(code=sec[e["ticker"][0]][0], name=sec[e["ticker"][0]][1])))  # fmt: skip
    desc = SimpleNamespace(by_ticker=lambda t: {"ticker": t, "name": t, "market": "US", "gics": {}})
    tagging = SimpleNamespace(tagged=[SimpleNamespace(ticker=t, confidence=0.9) for t in vals], passed_tickers=list(vals))
    intent = {"screen": {"metric": "return_12m_1m", "direction": "desc"}}
    cons = {"num_holdings": {"min": 1, "target": 3, "max": 3}, "max_weight_per_stock": 1.0, "max_weight_per_sector": 0.5, "min_cash_ratio": 0.0}
    sel, _ = screen(SimpleNamespace(as_of=dt.date(2025, 6, 25)), desc, tagging, intent, cons, request_id="r")
    reasons = {r.ticker: r.reason for r in sel.rejected}
    assert [s.ticker for s in sel.selected] == ["A1", "B1", "A2"]  # 섹터당 1종목 선호(0.5×3) → B1 이 A2·A3 를 앞질렀다
    assert reasons["A3"] == "sector_preference" and reasons["A4"] == "rank_beyond_n"  # A4 는 B1 보다 순위가 낮다


# ───────────────────────── 라운드 2 (시나리오 002·003) ─────────────────────────
def _spec_inputs(seeded_repo, descriptor_dir):
    from backend.analysis.m1_request.derive import derive
    from backend.analysis.m2_data import descriptor as D
    from backend.analysis.m2_data.market_data import MarketData
    from backend.analysis.settings import replace_settings
    from backend.tests.analysis.test_pipeline_e2e import REQUEST

    s = AnalysisSettings()
    s = replace_settings(s, portfolio=replace_settings(s.portfolio, lookback_days=252, min_history_days_for_model=120),
                         market=replace_settings(s.market, descriptor_dir=str(descriptor_dir), valuation_max_staleness_days=10))  # fmt: skip
    md = MarketData(seeded_repo, s)
    req = {**REQUEST, "constraints": {**REQUEST["constraints"], "num_holdings": {"target": 5, "min": 5, "max": 6}},
           "horizon": {**REQUEST["horizon"], "start_date": "2025-12-31", "backtest_years": 3}}  # fmt: skip
    req = derive(req, md, s).model_dump(mode="json")
    desc, _i, _w = D.load_for(dt.date(2025, 12, 31), req["constraints"]["universe"], ["US"], processed_dir=str(descriptor_dir))
    return md, req, desc, s


def _fake_selection(n: int):
    from backend.analysis.schemas.selection import Selection

    tk = ["NVDA", "AMD", "AVGO", "MU", "AMAT", "MSFT"][:n]
    return Selection.model_validate({"request_id": "r", "as_of": "2025-12-31", "rejected": [], "summary": {"metric": "return_12m_1m"}, "warnings": [],
                                     "selected": [{"ticker": t, "name": t, "sector": "IT", "sector_code": "45", "market": "US", "rank": i + 1,
                                                   "metric_name": "return_12m_1m", "metric_value": 0.1, "metric_fact_id": None, "theme_confidence": 0.9,
                                                   "forced": False} for i, t in enumerate(tk)]})  # fmt: skip


@pytest.mark.parametrize("consent, allow_fewer, counts, expect_shift, expect_n", [
    (False, False, [2, 3, 5, 6], False, 2),   # 동의 없음 → 옮기지 않고 2종목으로 시작
    (False, True, [1, 1, 2, 5], True, 2),     # '기간 유지' 를 골라도 1종목 이하면 2종목 되는 첫 날로 자동 이동
    (True, False, [2, 3, 5, 6], True, 5),     # 동의 → 최소 종목 수(5)를 채우는 첫 날
    (True, False, [2, 3, 3, 3], False, 2),    # 동의했어도 끝까지 못 채우면 원래 시작일로 되돌림 (창만 줄지 않게)
])
def test_start_date_policy(monkeypatch, seeded_repo, descriptor_dir, consent, allow_fewer, counts, expect_shift, expect_n):
    from types import SimpleNamespace

    import backend.analysis.m4_portfolio.spec as S
    from backend.analysis.schemas.selection import Tagging

    md, req, desc, s = _spec_inputs(seeded_repo, descriptor_dir)
    seen: list[dt.date] = []

    def fake_at(md_, day, desc_, intent_, cons_, passed, rid, **kw):
        seen.append(day)
        n = counts[min(len(seen) - 1, len(counts) - 1)]
        return SimpleNamespace(candidates=[], model_dump=lambda **k: {}), Tagging(request_id="r", min_confidence=0, tagged=[], passed_tickers=[], batches=0), _fake_selection(n), []

    monkeypatch.setattr(S, "selectable_at", fake_at)
    tag = Tagging(request_id="r", min_confidence=0.5, tagged=[], passed_tickers=["NVDA", "AMD", "AVGO", "MU", "AMAT", "MSFT"], batches=0)
    spec, _ = S.build_backtest_spec(md, req, {"screen": {"metric": "return_12m_1m"}}, tag, _fake_selection(6), desc, s,
                                    allow_fewer_at_start=allow_fewer, start_shift_ok=consent)  # fmt: skip
    shifted = str(spec["period"]["start"]) != str(req["derived"]["backtest_start"])
    assert shifted == expect_shift and len(spec["selection"]["tickers"]) == expect_n


def test_start_date_with_no_selectable_stock_stops_in_korean(monkeypatch, seeded_repo, descriptor_dir):
    from types import SimpleNamespace

    import backend.analysis.m4_portfolio.spec as S
    from backend.analysis.errors import DataMissing
    from backend.analysis.schemas.selection import Tagging

    md, req, desc, s = _spec_inputs(seeded_repo, descriptor_dir)
    monkeypatch.setattr(S, "selectable_at", lambda *a, **kw: (SimpleNamespace(candidates=[], model_dump=lambda **k: {}),
                                                              Tagging(request_id="r", min_confidence=0, tagged=[], passed_tickers=[], batches=0), _fake_selection(0), []))  # fmt: skip
    tag = Tagging(request_id="r", min_confidence=0.5, tagged=[], passed_tickers=["NVDA"], batches=0)
    with pytest.raises(DataMissing) as e:
        S.build_backtest_spec(md, req, {"screen": {"metric": "return_12m_1m"}}, tag, _fake_selection(6), desc, s)
    assert "선정 가능한 종목이 없습니다" in str(e.value)


def test_single_asset_market_model():
    idx = pd.bdate_range("2024-01-01", periods=300)
    px = pd.DataFrame({"A": 100 * np.cumprod(1 + np.random.default_rng(0).normal(0, 0.01, 300))}, index=idx)
    for shrink in ("ledoit_wolf", "none"):
        mm = P.estimate_market_model(px, ["A"], lookback_days=252, min_history_days=200, shrinkage=shrink)
        assert np.asarray(mm["cov"]).shape == (1, 1) and mm["tickers"] == ["A"]


def test_insufficient_label_keeps_cautions_and_min_holdings():
    from backend.analysis.m5_backtest_report.validate import verdict_for

    v = verdict_for(mdd=0.17, tol=0.10, st={"R2": "pass", "R3": "warn"}, base_invested=0.35, min_invested=0.5, name_ko="동일비중",
                    n_holdings=2, min_holdings=5, cause_ko="선정 종목이 산업재 등 적은 섹터에 몰려 섹터당 상한 35% 때문에 35%만 투자됩니다")  # fmt: skip
    assert v["status"] == "insufficient" and v["label_ko"].startswith("구성 불충분(주의:")
    assert "허용 낙폭 초과 (7.0%p)" in v["label_ko"] and "비교지수 하회" in v["label_ko"] and "종목 수 부족 (2/5개)" in v["label_ko"]
    same = verdict_for(mdd=0.0, tol=0.1, st={}, base_invested=0.49999, min_invested=0.5, name_ko="x")
    assert same["status"] == "recommended"  # 경계의 반올림 잡음으로 라벨이 뒤집히지 않는다


def test_cagr_uses_calendar_time_on_union_calendar():
    from backend.analysis.m5_backtest_report.backtest_metrics import cagr

    days = pd.date_range("2023-01-02", "2026-01-02", freq="D")
    cal = days[days.dayofweek < 6][:: 1]  # 주 6일 ≈ 1년 313행 (한·미 합집합처럼 252 보다 많다)
    years = (cal[-1] - cal[0]).days / 365.25
    idx = pd.Series(100 * (1.10 ** (np.arange(len(cal)) / ((len(cal) - 1) / years))), index=cal)
    assert cagr(idx, 252) == pytest.approx(0.10, abs=1e-4)


def test_skipping_start_question_gives_consent(monkeypatch, svc_factory):
    from backend.analysis.common.store import RequestStore
    from backend.tests.analysis.test_dialog import _intent

    import backend.analysis.m1_request.dialog as DG

    fake = {"signature": "x", "basis": "after_classification", "min": 5, "target": 5, "short_now": False, "short_at_start": True, "capacity_short": False,
            "as_of": {"n_selected": 6, "n_with_metric": 6, "n_candidates": 6, "capacity": 1.0, "invest": 1.0, "sector_counts": {"IT": 6}, "cap_needed": None},
            "start": {"date": "2023-01-02", "n_selected": 3, "n_with_metric": 3, "n_candidates": 3, "sector_counts": {"IT": 3}},
            "feasible_start": {"date": "2023-06-01", "n_with_metric": 5, "n_selected": 5, "years": 2.5}}  # fmt: skip
    monkeypatch.setattr(DG, "run_precheck", lambda *a, **kw: fake)
    svc, store, _llm = svc_factory([_intent([])] * 3)
    st = svc.start("반도체 장기 투자")
    assert st.question is not None and st.question.field == "horizon.backtest_years" and "답하지 않으면 시작일을 2023-06-01로" in st.question.question_ko
    st = svc.skip(st.request_id, st.question.seq)
    assert RequestStore(store).load(st.request_id).overrides.get("_start_shift_ok") is True


def test_auto_start_shift_is_a_user_notice():
    """1종목 이하라 자동으로 옮긴 시작일도 사용자 공지 (003: 정규식이 '로 옮김' 만 찾아 '로 자동으로 옮김' 이 공지에서 빠졌다)."""
    from backend.analysis.common.warnings import from_text

    for text in ["백테스트 시작일 2023-10-10 에는 선정 가능한 종목이 1개뿐이라 시작을 2024-04-03 로 자동으로 옮김 (6개월 뒤, 선정 2종목)",
                 "백테스트 시작일 2023-10-10 에는 테마 후보 중 선정 가능한 종목이 최소 종목 수(5)보다 적어 시작을 2024-05-28 로 옮김 (10개월 뒤, 선정 6종목)"]:
        w = from_text("07_backtest_spec", text)
        assert w.code == "backtest_start_shifted" and w.level == "user" and w.message_ko == text


def test_matched_plan_respects_stock_floor():
    """정책 결정 2: 주식 30% 아래로 줄여야 목표 낙폭을 맞추면 맞춤안을 만들지 않는다 (003: 주식 23.5% 안이 추천됐다)."""
    from backend.analysis.common.warnings import from_text
    from backend.analysis.m5_backtest_report import matched as MX

    days = pd.bdate_range("2024-01-01", periods=300)
    r = np.r_[np.zeros(100), np.full(100, -0.006), np.zeros(100)]  # 기준 구성 MDD ≈ 45%

    def run_fn(c):
        return {"index": pd.Series(np.cumprod(1 + (1 - c) * r) * 100, index=days)}

    c, raw, _n = MX.solve_cash_ratio(run_fn, MX.seed_cash_ratio(run_fn(0)["index"], 0.15), 0.15)
    assert c is not None and 0.6 < c < 0.75  # 하한이 없으면 주식 약 30% 안팎
    c2, raw2, _ = MX.solve_cash_ratio(run_fn, MX.seed_cash_ratio(run_fn(0)["index"], 0.15), 0.15, max_cash=0.5)  # 주식 50% 이상 유지
    assert c2 is None and raw2 is None
    w = from_text("11_backtest", "matched variant skipped for equal_weight: stocks below floor 30% would be needed to bring max drawdown within 15.0% (base invested 100%, cash cap 70%, 9 runs)")
    assert w.code == "matched_floor" and w.level == "user" and "30%" in w.message_ko and "15.0%" in w.message_ko


def test_capacity_notice_names_the_binding_cap_and_total_cash():
    """002: 2종목 × 종목당 25% 라 섹터 상한과 무관한데 '섹터 상한을 올리면 해소' 라고 했다 · 07 과 10 이 같은 날 같은 공지를 두 번 냈다 · F19 총 현금."""
    from backend.analysis.common.warnings import from_text, merge

    a = from_text("07_backtest_spec", "screen@2023-07-10: weight capacity 0.50 < 1.00: caps cannot absorb the capital with these sectors (cap needed None; stock 25%, sector 75%, 2 names)")
    b = from_text("10_targets", "start@2023-07-10: caps allow at most 50% invested (stock 25%, sector 75%, 2 names, investable 100%): 50% kept as cash; relax the caps or widen the theme to invest fully")
    m = merge([a, b])
    assert len(m) == 1 and m[0].count == 1 and m[0].message_ko.startswith("백테스트 시작일(2023-07-10) 기준: 선정 종목 2개")
    assert "섹터 상한만 올려서는 해소되지 않습니다" in m[0].message_ko and "현금이 50%" in m[0].message_ko
    c = from_text("05_selection", "weight capacity 0.60 < 0.85: caps cannot absorb the capital with these sectors (cap needed 0.6; stock 25%, sector 35%, 9 names)")
    assert "현금이 40% 남습니다 (최소 현금 15% 포함)" in c.message_ko and "섹터 상한을 60%로 올리거나" in c.message_ko


def test_infeasibility_callout_says_when_and_uses_korean_sectors():
    from backend.analysis.m5_backtest_report.report_blocks import infeasibility_callout

    inf = {"stock_cap": 0.25, "sector_cap": 0.75, "capacity": 0.5, "n_selected": 2, "sector_counts": {"Industrials": 2},
           "options_ko": ["섹터 상한 완화로도 해결 불가", "종목당 상한을 올리기", "테마를 넓혀 다른 섹터 후보를 늘리기"]}  # 예전 결과 형식
    R = {"selection": {"backtest_as_of": {"as_of": "2023-07-10", "infeasibility": inf}, "as_of_now": {"as_of": "2026-07-10", "infeasibility": None}}}
    txt = infeasibility_callout(R)["text_ko"]
    assert txt.startswith("백테스트 시작일(2023-07-10)에 고른 종목 2개") and "산업재 2개" in txt and "해결 불가" not in txt


def test_rank_ties_prefer_users_baseline():
    """같은 성과(1e-6 잡음)면 사용자가 고른 기준 비중이 앞 (002: 역변동성비중을 골랐는데 동일비중이 앞)."""
    from backend.analysis.m5_backtest_report.validate import rank_key

    rows = [{"id": "equal_weight", "kind": "template", "max_drawdown": -0.2526, "sharpe": 1.407370},
            {"id": "inverse_volatility", "kind": "template", "max_drawdown": -0.2526, "sharpe": 1.407369},
            {"id": "wf_bl_news", "kind": "black_litterman", "max_drawdown": -0.2526, "sharpe": 1.407371}]
    st = {"R2": "pass", "R3": "warn"}
    order = sorted(rows, key=lambda r: rank_key(r, st, integrity_failed=False, tol=0.25, bucket_size=0.05, cautious=False, baseline_id="inverse_volatility"))
    assert order[0]["id"] == "inverse_volatility"


def test_matched_current_composition_keeps_tested_stock_share():
    """002: 시작일 2종목이라 기준 구성이 현금 50% → c=2% 로 '주식 49%' 를 맞췄는데, 기준일(9종목 전액 투자)에 × 0.98 을 해 주식 98% 로 보였다."""
    import backend.analysis.m5_backtest_report.report_blocks as RB
    from backend.analysis.m6_tracking.paper import Strategy, resolve_strategy

    blk = {"id": "dd_match_inverse_volatility", "kind": "matched", "base_id": "inverse_volatility", "cash_ratio": 0.02, "cash_ratio_total": 0.51,
           "name_ko": "낙폭 맞춤안 (주식 49% + 현금 51%, 역변동성비중 기준)"}
    R = {"portfolio": {"forward": {"as_of": "2026-07-10", "templates": [{"id": "inverse_volatility", "name_ko": "역변동성비중", "weights": {"A": 0.5, "B": 0.3, "C": 0.2}}],
                                   "portfolios": []}},
         "backtest": {"portfolios": [blk]}}
    orig = RB.find
    try:
        RB.find = lambda R_, pid: next(p for p in R_["backtest"]["portfolios"] if p["id"] == pid)
        w, cash, name = RB.current_composition(R, "dd_match_inverse_volatility")
    finally:
        RB.find = orig
    assert sum(w.values()) == pytest.approx(0.49) and cash == pytest.approx(0.51) and name.startswith("낙폭 맞춤안 (주식 49% + 현금 51%")
    s = resolve_strategy("dd_match_inverse_volatility", {"backtest": {"portfolios": [blk]}})
    assert s.target_invested == pytest.approx(0.49) and sum(s.blend({"A": 0.5, "B": 0.3, "C": 0.2}).values()) == pytest.approx(0.49)
    assert sum(s.blend({"A": 0.2, "B": 0.2}).values()) == pytest.approx(0.4)  # 기준일 구성이 더 적게 담으면 그대로
    old = Strategy("dd_match_equal_weight", "cash_blend", "equal_weight", 0.3, "옛 저장본")  # target_invested 없는 예전 모의투자 문서
    assert sum(old.blend({"A": 0.5, "B": 0.5}).values()) == pytest.approx(0.7)


@pytest.mark.parametrize("news_on, fail", [(True, False), (True, True), (False, False)])
def test_walkforward_keeps_news_bl_only_with_applied_views(monkeypatch, tmp_path, news_on, fail):
    """F15: 뉴스를 꺼도 wf_bl_news 가 생겼다 · 002/003: 모든 날짜가 기준 비중인데 '뉴스 뷰 BL' 후보가 남아 동점 잡음으로 추천될 수 있었다."""
    from types import SimpleNamespace

    from importlib import import_module

    from backend.analysis.executor import stages
    from backend.analysis.executor.context import RunContext
    from backend.tests.analysis.test_rebalance_regressions import portfolio_inputs

    C = import_module("backend.analysis.m4_portfolio.construct")  # 패키지가 같은 이름의 함수를 내보내 'import construct as C' 는 함수가 된다

    mm, base, sets, req, intent, desc, settings = portfolio_inputs(monkeypatch, 6)
    intent = {**intent, "news_tilt": {**intent["news_tilt"], "enabled": news_on}}
    if fail:
        monkeypatch.setattr(P, "minimize", lambda *a, **kw: SimpleNamespace(success=False, message="forced failure"))
    monkeypatch.setattr(C, "build_market_model", lambda *a, **kw: (mm, base))
    monkeypatch.setattr(C, "generate_views", lambda *a, **kw: (sets, []))
    date = dt.date(2024, 1, 2)
    evidence = SimpleNamespace(enough=True, summary=lambda: {}, to_dict=lambda: {})
    view = SimpleNamespace(as_of=date, news_window=lambda tk: evidence, trading_days=lambda *a, **kw: pd.DatetimeIndex([date]))
    result = C.construct(view, mm["tickers"], req, intent, settings, None, desc, mode="rebalance")
    monkeypatch.setattr(stages, "construct", lambda *a, **kw: result)
    md = SimpleNamespace(assets={}, view=lambda d: view, market_of=lambda t: "US")
    ctx = RunContext("run_test", req, None, md, None, settings, tmp_path)
    ctx.outputs = {"02_intent": intent, "07_backtest_spec": {"period": {"as_of": str(date), "end": str(date)}, "selection": {"tickers": mm["tickers"]},
                                                            "benchmark": "SPY", "rebalance_rule": {"enabled": True, "count": 1, "unit": "1q"}}}  # fmt: skip
    mm.update(delta_source="fixed", lookback={})
    stages.st_walkforward(ctx)
    out = ctx.out("10w_target_paths")
    has_bl = any(p["kind"] == "black_litterman" for p in out["portfolios"])
    assert has_bl == (news_on and not fail)
    if not has_bl:
        assert out["bl_omitted"]["reason"] == ("news_off" if not news_on else "no_views")


def test_capacity_question_uses_korean_sector_names(monkeypatch, svc_factory):
    """F25 질문 문장에 'Industrials 8개' 대신 '산업재 8개' (002)."""
    import backend.analysis.m1_request.dialog as DG
    from backend.tests.analysis.test_dialog import _intent

    fake = {"signature": "x", "basis": "after_classification", "min": 5, "target": 10, "short_now": False, "short_at_start": False, "capacity_short": True,
            "as_of": {"n_selected": 9, "n_with_metric": 9, "n_candidates": 14, "capacity": 0.6, "invest": 1.0, "sector_counts": {"Industrials": 8, "Utilities": 1},
                      "cap_needed": 0.75},
            "start": None, "feasible_start": None}  # fmt: skip
    monkeypatch.setattr(DG, "run_precheck", lambda *a, **kw: fake)
    svc, _store, _llm = svc_factory([_intent([])] * 3, sector_rule=True)
    st = svc.start("국내 전력 인프라 장기 투자")
    q = st.question
    assert q is not None and q.field == "constraints.max_weight_per_sector" and "산업재 8개, 유틸리티 1개" in q.question_ko and "Industrials" not in q.question_ko


def test_backtest_start_metric_has_its_own_fact_id(e2e_results):
    """003: 시작일 PER 에 기준일 인용 ID([fin:…:2026-10-07])를 붙였다 → 시작일 값은 시작일 ID 를 따로 넘긴다."""
    from backend.analysis.m5_backtest_report.report import facts_for_narrate

    R, _s = e2e_results
    rows = [t for t in R["selection"]["table"] if t["in_backtest"]]
    assert rows and all(t.get("metric_backtest_fact_id") for t in rows)
    start = str(R["portfolio"]["backtest_spec"]["period"]["as_of"])
    for t in rows:
        fid = t["metric_backtest_fact_id"]
        assert fid in R["evidence_index"] and fid.rsplit(":", 1)[1] < start  # 시작일 전날까지의 재무 (기준일 ID 아님)
    chosen = R["validation"]["recommended"]["id"]
    ids = facts_for_narrate(R, chosen, {})["fact_ids"]
    assert {t["metric_backtest_fact_id"] for t in rows} <= set(ids)


# ───────────────────────── 라운드 2 독립 검토 (002·003 결과물 다시 읽기) ─────────────────────────
def test_report_money_uses_start_fx_for_paid_amounts(e2e_results):
    """002: 백테스트 시작일 배분표 원화가 기준일 환율이라 원금 1,000만 원이 1,160만 원으로 보였다 · 넣은 원화도 기준일 환율."""
    import copy

    from backend.analysis.m5_backtest_report import report_blocks as RB

    R, _s = e2e_results
    R = copy.deepcopy(R)
    R["money_krw"]["backtest_fx"]["fx_rate"] = 1300.0
    R["money_krw"]["fx_rate"] = 1500.0
    chosen = R["validation"]["recommended"]["id"]
    rows = RB.allocation_table(R, chosen)["rows"]
    init = R["portfolio"]["backtest_spec"]["capital"]["initial_amount_usd"]
    assert sum(r["krw"] for r in rows) == pytest.approx(init * 1300.0, rel=1e-6)


def test_collect_keeps_delta_floor_for_formula(e2e_results):
    """'계산 조건' 의 δ 식에서 하한이 빠져 '0.1965 × 1.0 × 0.8 = 1.2' 처럼 틀린 식이 나왔다 (결과 묶음이 delta_base 를 버림)."""
    import copy

    from backend.analysis.m5_backtest_report import report_blocks as RB

    R, _s = e2e_results
    R = copy.deepcopy(R)
    mm = R["portfolio"]["market_model"]
    assert "delta_base" in mm or mm.get("delta_source") != "market_implied"
    if mm.get("delta_source") == "market_implied":
        mm["delta_market"], mm["delta_base"] = 0.1965, 1.5
        txt = json_dumps(RB.parameters_table(R))
        assert "하한" in txt


def json_dumps(x):
    import json

    return json.dumps(x, ensure_ascii=False)


def test_selection_table_rank_is_metric_rank_and_flags_forced(e2e_results):
    """002: 필수 포함 LS ELECTRIC 이 선정 순서상 맨 앞이라 'ROE 순위 1' 로 보였다 (실제 9개 중 5위)."""
    R, _s = e2e_results
    rows = [t for t in R["selection"]["table"] if t["in_selection_now"] and t["metric_now"] is not None]
    asc = R["selection"]["direction"] == "asc"
    by_metric = sorted(rows, key=lambda t: t["metric_now"] if asc else -t["metric_now"])
    assert [t["rank_now"] for t in by_metric] == list(range(1, len(by_metric) + 1)) and all("forced" in t for t in R["selection"]["table"])


def test_company_cards_show_current_composition(e2e_results):
    """002: 회사 카드가 백테스트 시작일 목표 비중이라 지금 선정 9개 중 7개가 '미보유', 날짜도 없었다."""
    from backend.analysis.m5_backtest_report import report_blocks as RB

    R, _s = e2e_results
    chosen = R["validation"]["recommended"]["id"]
    cc = RB.current_composition(R, chosen)
    blk = RB.companies(R, chosen)
    if cc:
        now = {it["ticker"]: it["weight"] for it in blk["items"] if it["in_selection_now"]}
        assert all(now[t] == pytest.approx(cc[0].get(t, 0.0)) for t in now) and "분석 기준일" in blk["note_ko"]


def test_funnel_shows_filter_step_and_reasons(e2e_results):
    """003: 게임주 4개가 모두 거래대금 기준으로 빠졌는데 깔때기에 그 단계가 없었다."""
    R, _s = e2e_results
    stages = [f["stage"] for f in R["selection"]["funnel"]]
    assert stages[:3] == ["universe", "matched", "candidates"] and isinstance(R["selection"]["candidates_filtered"], list)


def test_market_facts_separate_current_and_backtest_holdings(e2e_results):
    """002: 시장 분석이 지금 9종목 옆에 백테스트(2종목 + 현금) 평균 섹터 비중을 붙여 '평균 산업재 51.6%' 라고 썼다."""
    from backend.analysis.m5_backtest_report.report import facts_for_market

    R, _s = e2e_results
    f = facts_for_market(R)
    assert "current_sector_weights_pct" in f and "backtest_holdings" in f and all("weight_now" in h for h in f["holdings"])
    assert "backtest_holdings" in f["sector_exposure_note"]


def test_cash_breakdown_explains_where_cash_came_from():
    """002: 서술이 '종목·섹터 상한 때문에 주식 49%' 라고 써서 낙폭 맞춤으로 더 줄인 1%p 까지 상한 탓으로 돌렸다."""
    from backend.analysis.m5_backtest_report import report as RP

    base = {"id": "inverse_volatility", "kind": "template", "target_weights": {"A": 0.25, "B": 0.25}}
    m = {"id": "dd_match_inverse_volatility", "kind": "matched", "base_id": "inverse_volatility", "target_weights": {"A": 0.245, "B": 0.245}}
    R = {"request": {"constraints": {"min_cash_ratio": 0.0}}, "backtest": {"portfolios": [base, m]}}
    orig = RP.B.find
    try:
        RP.B.find = lambda R_, pid: next(p for p in R_["backtest"]["portfolios"] if p["id"] == pid)
        cb = RP.cash_breakdown(R, m)
    finally:
        RP.B.find = orig
    assert cb["stocks"] == "49.0%" and cb["cash"] == "51.0%" and cb["cash_by_caps"] == "50.0%" and cb["cash_added_by_drawdown_match"] == "1.0%"
    assert cb["min_cash_by_user"] is None


def test_assumptions_and_execution_note_tell_the_truth(e2e_results):
    """003: 현금 76.5% 가 0% 수익인데 '무위험수익률 연 4%' 만 적혀 있었다 · 실행 기록이 리포트 작성 전 LLM 사용량(3회)만 보여 줬다."""
    from backend.analysis.m5_backtest_report import report_blocks as RB

    R, _s = e2e_results
    assert "0%로 계산" in RB.assumptions_callout(R)["text_ko"]
    assert "리포트 작성 포함" in RB.execution_table(R, {}, {"calls": 6, "cache_hits": 1, "cost_usd": 0.0272, "model": "m"})["note_ko"]


def test_request_tables_use_korean_words(e2e_results):
    """002/003: '투자성향: moderate · 손실 시 hold', '제외: fossil_fuels', 카드 제목 'horizon.backtest_years'."""
    import copy

    from backend.analysis.m5_backtest_report import report_blocks as RB

    R, _s = e2e_results
    R = copy.deepcopy(R)
    R["request"]["constraints"]["exclude_themes"] = ["fossil_fuels"]
    R["intent"]["interpretation"]["conflicts"] = [{"field": "horizon.backtest_years", "issue_ko": "x", "resolution_ko": "y"}]
    req_rows = {r["k"]: r["v"] for r in RB.request_table(R)["rows"]}
    assert not any(w in req_rows["투자성향"] for w in ("moderate", "conservative", "aggressive", "hold", "sell", "buy_more"))
    assert "화석연료" in {r["k"]: r["v"] for r in RB.constraints_table(R)["rows"]}["제외"]
    assert RB.conflicts_cards(R)["items"][0]["title_ko"] == "백테스트 기간(년)"


def test_keep_window_option_warns_about_cash(monkeypatch, svc_factory):
    """002: '기간 유지' 를 골라 백테스트가 현금 50% 로 평가됐는데 보기에는 그 사실이 없었다."""
    import backend.analysis.m1_request.dialog as DG
    from backend.tests.analysis.test_dialog import _intent

    fake = {"signature": "x", "basis": "after_classification", "min": 5, "target": 10, "short_now": False, "short_at_start": True, "capacity_short": False,
            "as_of": {"n_selected": 9, "n_with_metric": 9, "n_candidates": 14, "capacity": 1.0, "invest": 1.0, "sector_counts": {"Industrials": 8, "Utilities": 1}},
            "start": {"date": "2023-07-10", "n_selected": 2, "n_with_metric": 2, "n_candidates": 8, "capacity": 0.5, "sector_counts": {"Industrials": 2}},
            "feasible_start": {"date": "2024-05-28", "n_with_metric": 6, "n_selected": 6, "years": 2.1}}  # fmt: skip
    monkeypatch.setattr(DG, "run_precheck", lambda *a, **kw: fake)
    svc, _store, _llm = svc_factory([_intent([])] * 3)
    st = svc.start("국내 전력 인프라 장기 투자")
    opts = {o.value: o.label_ko for o in st.question.options}
    assert "투자금의 50%만 투자" in opts["keep_window"] and st.question.question_ko.startswith("백테스트 시작일(2023-07-10)에 선정할 수 있는 종목이 2개")


def test_dialog_keeps_themes_when_answer_is_not_about_themes(svc_factory):
    """004: '종목 수 4개로 줄임' 답 뒤에 LLM 이 의도를 다시 쓰며 테마 GICS 코드를 바꿔(2510 이 빠짐) 점검 후보가 4 → 3 이 됐다.
    테마와 무관한 답이면 이전 턴의 테마를 그대로 두고, 아이디어에 말을 보탠 답이면 새 테마를 받는다."""
    from backend.analysis.common.store import RequestStore
    from backend.tests.analysis.test_dialog import Q_IDEA, Q_TEMPLATE, _intent

    t1, t2, t3 = _intent([Q_TEMPLATE]), _intent([Q_IDEA]), _intent([])
    t2["interpretation"]["themes"][0]["gics_codes"] = ["45"]  # 테마와 무관한 답 뒤의 표류
    t3["interpretation"]["themes"][0]["gics_codes"] = ["4530", "4520"]  # 말을 보탠 뒤의 정당한 변경
    svc, store, _llm = svc_factory([t1, t2, t3])
    st = svc.start("반도체 장기 투자")
    first = RequestStore(store).load(st.request_id).intent["interpretation"]["themes"]
    st = svc.answer(st.request_id, 1, option_value="quality")
    assert RequestStore(store).load(st.request_id).intent["interpretation"]["themes"] == first
    st = svc.answer(st.request_id, 2, free_text="장비 회사도 포함해 주세요")
    assert RequestStore(store).load(st.request_id).intent["interpretation"]["themes"][0]["gics_codes"] == ["4530", "4520"]


# ───────────────────────── 라운드 3 (004·005) ─────────────────────────
def test_roe_data_error_ceiling():
    """005: AbbVie ROE 141% → 15,367% (자기자본이 0 근처·음수) 가 '퀄리티 1위' 로 뽑혔다 → 1000% 초과는 자료 오류로 거른다."""
    from backend.analysis.m2_data import metrics as MM

    assert MM.eligible("roe_ttm", 1.41) and MM.eligible("roe_ttm", 8.89) and not MM.eligible("roe_ttm", 153.67) and not MM.eligible("roe_ttm", -0.1)


def test_usd_ko_units():
    from backend.analysis.common.labels import usd_ko

    assert usd_ko(10e9) == "100억 달러" and usd_ko(2e9) == "20억 달러" and usd_ko(2e7) == "2,000만 달러" and usd_ko(5e6) == "500만 달러" and usd_ko(2.5e8) == "2.5억 달러"


def test_narrate_facts_label_start_and_current_allocation_and_news_off(e2e_results):
    """005: 시작일 비중을 '최종 구성' 이라 쓰고 '14.6818%' 를 옮겼다 · 004: 뉴스를 껐는데 '헤드라인 0건' 이라고 썼다."""
    import copy

    from backend.analysis.m5_backtest_report.report import facts_for_interpret, facts_for_narrate

    R, _s = e2e_results
    chosen = R["validation"]["recommended"]["id"]
    ch = facts_for_narrate(R, chosen, {})["construction"]["chosen"]
    assert ch["allocation_at_backtest_start"] and all(r["weight"].endswith("%") for r in ch["allocation_at_backtest_start"]) and "allocation_now" in ch
    R2 = copy.deepcopy(R)
    R2["intent"]["news_tilt"]["enabled"] = False
    wf = facts_for_interpret(R2, chosen).get("walkforward")
    if wf:
        assert isinstance(wf["news_summary"], str) and "불러오지 않았" in wf["news_summary"]



# ───────────────────────── 라운드 2 후속: 매매일 달력 (독립 검토 에이전트 작업) ─────────────────────────
from types import SimpleNamespace  # noqa: E402

from backend.analysis.common.llm import StubLlm  # noqa: E402
from backend.analysis.executor import stages  # noqa: E402
from backend.analysis.executor.context import RunContext  # noqa: E402
from backend.analysis.m2_data.market_data import MarketData  # noqa: E402
from backend.analysis.m5_backtest_report.backtest import prepare, run_raw, trade_schedule  # noqa: E402
from backend.analysis.m5_backtest_report.backtest_engine import contribution_dates, rebalance_dates  # noqa: E402

# ───────────────────────── 매매일 달력 (QA 002: 한국 종목만 + 미국 비교지수) ─────────────────────────
def _days(start, end, holidays):
    return pd.DatetimeIndex([d for d in pd.bdate_range(start, end) if d.date() not in holidays], name="date")


def test_rebalance_and_contribution_dates_skip_holding_market_holidays():
    """평가 달력이 한국 ∪ 미국 합집합이어도 한국 종목만 든 포트폴리오의 리밸런싱·적립은 한국이 연 날에만 (QA 002 에서 걸린 실제 날짜)."""
    kr_h = {dt.date(2023, 8, 15), dt.date(2023, 10, 2), dt.date(2023, 10, 3), dt.date(2024, 9, 16), dt.date(2024, 9, 17), dt.date(2024, 9, 18),
            dt.date(2024, 10, 1), dt.date(2024, 10, 3)}  # fmt: skip
    us_h = {dt.date(2023, 7, 4), dt.date(2023, 9, 4), dt.date(2024, 7, 4), dt.date(2024, 9, 2)}
    kr, us = _days("2023-03-02", "2024-12-31", kr_h), _days("2023-03-02", "2024-12-31", us_h)
    union, bs, q = kr.union(us), AnalysisSettings().backtest, {"count": 1, "unit": "1q", "enabled": True}
    old = rebalance_dates(q, union, "2023-03-02", bs)  # tradable 없이 = 예전 동작: 합집합에서 바로 골라 한국 휴장일에 매매
    new = rebalance_dates(q, union, "2023-03-02", bs, tradable=kr)
    assert {pd.Timestamp("2023-10-02"), pd.Timestamp("2024-10-01")} <= set(old)
    assert [str(d.date()) for d in new] == ["2023-03-02", "2023-04-03", "2023-07-03", "2023-10-04", "2024-01-01", "2024-04-01", "2024-07-01", "2024-10-02"]
    for day, closed, moved in [(15, "2023-08-15", "2023-08-16"), (16, "2024-09-16", "2024-09-19")]:
        c_old = contribution_dates(union, "2023-03-02", "2024-12-31", day)
        c_new = contribution_dates(union, "2023-03-02", "2024-12-31", day, tradable=kr)
        assert pd.Timestamp(closed) in c_old and pd.Timestamp(closed) not in c_new and pd.Timestamp(moved) in c_new
        assert len(c_new) == len(c_old) and set(c_new) <= set(kr)
    assert set(rebalance_dates({"count": 1, "unit": "2w", "enabled": True}, union, "2023-03-02", bs, tradable=kr)) <= set(kr)
    assert rebalance_dates({"count": 0, "unit": "1q"}, union, "2023-03-02", bs, tradable=kr) == [pd.Timestamp("2023-03-02")]
    # 한 기간 내내 휴장이면 다음 기간 첫 매매일과 겹쳐 하나만 · 마지막 날로 밀리면 리밸런싱하지 않음 (종료 체크포인트만)
    gap = kr[(kr < "2024-04-01") | (kr >= "2024-07-01")]
    assert [str(d.date()) for d in rebalance_dates(q, union, "2024-01-02", bs, tradable=gap)] == ["2024-01-02", "2024-07-01", "2024-10-02"]
    assert [str(d.date()) for d in rebalance_dates(q, union[union <= "2024-10-02"], "2024-07-01", bs, tradable=kr)] == ["2024-07-01"]


KR_SPEC = {"period": {"start": "2022-07-01", "end": "2023-06-30", "as_of": "2022-07-01"}, "benchmark": "069500.KS", "extra_benchmarks": ["QQQ"],
           "selection": {"tickers": ["005930.KS", "000660.KS"]}, "rebalance_rule": {"count": 1, "unit": "1q", "enabled": True},
           "capital": {"initial_amount_usd": 10_000.0, "monthly_contribution_usd": 300.0, "contribution_day": 3, "include_contributions": True}}  # fmt: skip


def test_kr_only_portfolio_trades_on_kr_days_and_walkforward_matches_engine(seeded_repo, seed_info, settings, monkeypatch, tmp_path):
    """합성 DB 의 2022-10-03(월)은 한국만 휴장(QQQ 는 거래)인 4분기 첫 거래일. 리밸런싱·적립은 다음 한국 거래일(10-04)로 가고,
    평가 시계열은 합집합 그대로, walk-forward(10w) 구성일 == 백테스트(11) 리밸런싱일."""
    md = MarketData(seeded_repo, settings)
    kr = {pd.Timestamp(d) for d in seed_info["kr_days"]}
    closed, moved = pd.Timestamp("2022-10-03"), pd.Timestamp("2022-10-04")
    sch = trade_schedule(md, KR_SPEC, settings)
    assert closed in sch["cal"] and closed not in sch["tradable"]
    assert closed in rebalance_dates(KR_SPEC["rebalance_rule"], sch["cal"], "2022-07-01", settings.backtest)  # 예전: 합집합에서 바로 → 한국 휴장일
    assert [str(d.date()) for d in sch["rb"]] == ["2022-07-01", "2022-10-04", "2023-01-02", "2023-04-03"]
    assert moved in sch["cd"] and closed not in sch["cd"] and set(sch["rb"]) | set(sch["cd"]) <= kr
    bt_ctx = prepare(md, KR_SPEC, {"constraints": {}}, {"validation_criteria": {"target_annual_return": 0.05}}, {}, SimpleNamespace(by_ticker=lambda t: None),
                     settings, "equal_weight")  # fmt: skip
    assert bt_ctx["rb"] == sch["rb"] and bt_ctx["cd"] == sch["cd"] and closed in bt_ctx["panel"].index  # 비교지수는 자기 거래일에 평가 (합집합 유지)
    raw = run_raw(bt_ctx, "kr_eq", {"005930.KS": 0.5, "000660.KS": 0.5})
    traded = set(pd.to_datetime(raw["transactions"]["Date"]))
    assert moved in traded and traded <= kr  # 한국 휴장일에 묵은 가격으로 체결하지 않는다

    seen = []

    def fake_construct(view, tickers, *a, **k):  # 날짜별 구성 내용은 보지 않고 구성일만 기록
        seen.append(view.as_of)
        return SimpleNamespace(market_model={"delta": 2.5, "delta_source": "test", "lookback": 252, "implied_returns": {}}, baselines={"portfolios": []},
                               evidence_summary=lambda: None, evidence=None, warnings=[], bl_portfolios=[], view_sets=[], baseline_weights={t: 0.5 for t in tickers},
                               applied_bl=[], fallback=True, fallback_reason_ko="")  # fmt: skip

    monkeypatch.setattr(stages, "construct", fake_construct)
    ctx = RunContext(run_id="qa002", request={"request_id": "req_qa002"}, repo=seeded_repo, md=md, llm=StubLlm(), settings=settings, run_dir=tmp_path)
    ctx.outputs.update({"07_backtest_spec": KR_SPEC, "02_intent": {}})
    stages.st_walkforward(ctx)
    assert ctx.outputs["10w_target_paths"]["dates"] == [str(d.date()) for d in bt_ctx["rb"]] and sorted(seen) == [d.date() for d in bt_ctx["rb"]]


def test_mixed_portfolio_trades_when_both_markets_open_and_walkforward_matches(e2e_results, seed_info):
    """미국+한국 혼합(e2e): 리밸런싱·적립은 두 시장이 모두 연 날에만, 10w 구성일 == 모든 포트폴리오의 리밸런싱 체크포인트·사건 날짜 (감사 항목)."""
    R, _s = e2e_results
    wf = R["portfolio"]["walkforward"]
    own = {"KR" if t.endswith(".KS") else "US" for t in wf["tickers"]}
    assert own == {"KR", "US"}  # 혼합 포트폴리오를 시험한다 (선정이 한쪽 시장만 되면 아래 확인이 조용히 사라지지 않게)
    open_days = set.intersection(*[{str(d) for d in seed_info["kr_days" if m == "KR" else "us_days"]} for m in own])
    for p in [*R["backtest"]["benchmarks"], *R["backtest"]["portfolios"]]:
        assert [c["date"] for c in p["checkpoints"] if c["kind"] == "rebalance"] == wf["dates"], p["id"]
        assert [e["date"] for e in p["events"] if e["type"] == "rebalance"] == wf["dates"], p["id"]
        cdates = [e["date"] for e in p["events"] if e["type"] == "contribution"]
        assert cdates and set(cdates) <= open_days and set(wf["dates"]) <= open_days, p["id"]
    first = R["backtest"]["portfolios"][0]
    contrib = [e["date"] for e in first["events"] if e["type"] == "contribution"]
    assert "2025-12-25" not in contrib and "2025-12-26" in contrib  # 2025-12-25(목)는 합성 DB 에서 한국만 휴장 → 그달 적립은 12-26



# ───────────────────────── 라운드 2 후속: 종목별 수익 기여 = 기간 수익률 (독립 검토 에이전트 작업) ─────────────────────────
from backend.analysis.m5_backtest_report.backtest_engine import extract_raw, run_static_portfolio, xirr  # noqa: E402
from backend.analysis.settings import BacktestSettings, replace_settings  # noqa: E402

# ───────────────────────── 종목별 수익 기여 = 기간 수익률 (Carino 로그 연결, 시나리오 002·003) ─────────────────────────
# 보고서 막대 '종목별 수익 기여 (기간 전체)' 가 일별 기여의 단순합이라 기간 수익률과 합이 안 맞았다 (002: 80.9%p + 44.5%p 인데 기간 수익률 205.4%).
_CD = pd.bdate_range("2024-01-02", periods=8)
# 두 종목 + 현금 약 10%. 비중은 날마다 바뀐다 (리밸런싱·드리프트). w 는 그날 거래 뒤 비중이라 다음 날 수익에 곱해진다.
_CW = pd.DataFrame({"A": [0.60, 0.62, 0.45, 0.45, 0.50, 0.55, 0.52, 0.50], "B": [0.30, 0.28, 0.45, 0.45, 0.40, 0.35, 0.38, 0.40]}, index=_CD)
# A 는 오르고 B 는 내린다 (부호 섞임). 4번째 날은 0.45·(+1%) + 0.45·(−1%) = 0, 5번째 날은 둘 다 0 (휴장일 직전값 유지) → 지수 수익 0 인 날 2개
_CR = pd.DataFrame({"A": [0.0, 0.10, -0.04, 0.01, 0.0, 0.12, -0.03, 0.09], "B": [0.0, -0.06, 0.03, -0.01, 0.0, -0.05, 0.02, -0.04]}, index=_CD)
_CSECTORS = {"A": "Tech", "B": "Energy"}


def _contrib_index(cost: dict[int, float] | None = None) -> pd.Series:
    """지수 = Π(1 + Σ_i w_i(t−1)·r_i(t) − 비용_t). 현금 수익은 0. cost = {날짜 위치: 그날 지수 대비 비용률}."""
    c = np.zeros(len(_CD))
    for i, v in (cost or {}).items():
        c[i] = v
    return 100 * (1 + (_CW.shift(1) * _CR).sum(axis=1) - c).cumprod()


def test_linked_contribution_sums_to_compounded_index_return():
    idx = _contrib_index()
    R = idx.iloc[-1] / idx.iloc[0] - 1
    assert (M.daily_returns(idx) == 0).sum() == 2  # 지수 수익 0 인 날(k_t = 1 로 두는 분기)이 실제로 들어 있다
    contrib, resid = M.linked_contribution(_CW, _CR, idx)
    assert abs(contrib.sum() - R) < 1e-9 and abs(resid) < 1e-9
    assert contrib["A"] > 0 > contrib["B"]  # 부호가 섞여도 합이 맞는다
    assert abs((_CW.shift(1) * _CR).sum().sum() - R) > 1e-3  # 예전 단순합은 이 자료에서 맞지 않는다 (테스트가 결함을 잡는지)


def test_linked_contribution_residual_is_linked_trading_cost():
    at, cost = 2, 0.001  # 3번째 날(비중을 바꾼 날) 지수의 0.1% 를 수수료로 냄
    idx = _contrib_index({at: cost})
    R = idx.iloc[-1] / idx.iloc[0] - 1
    contrib, resid = M.linked_contribution(_CW, _CR, idx)
    assert abs(resid - (R - contrib.sum())) < 1e-12
    rt = idx.iloc[at] / idx.iloc[at - 1] - 1
    assert abs(resid + (np.log1p(rt) / rt) / (np.log1p(R) / R) * cost) < 1e-12  # 잔차 = −(k_t/K)·비용 (닫힌 식)
    assert resid < 0


def test_composition_metrics_contribution_plus_residual_is_period_return_also_to_date():
    idx = _contrib_index({2: 0.001})
    px = 100 * (1 + _CR).cumprod()
    targets = {"A": 0.55, "B": 0.35}
    out = M.composition_metrics(_CW, px, targets, _CSECTORS, 1.0, 1.0, 0.25, idx)
    assert set(out["ticker_contribution"]) == {"A", "B"}  # 잔차는 가짜 종목이 아니라 별도 필드
    assert abs(sum(out["ticker_contribution"].values()) + out["ticker_contribution_residual"] - (idx.iloc[-1] / idx.iloc[0] - 1)) < 2e-6  # 6자리 반올림 3개
    d = _CD[4]  # 체크포인트처럼 앞부분만 잘라도 (가격은 전체 기간) 그 구간의 기간 수익률과 맞는다
    part = M.composition_metrics(_CW.loc[:d], px, targets, _CSECTORS, 1.0, 1.0, 0.25, idx.loc[:d])
    assert abs(sum(part["ticker_contribution"].values()) + part["ticker_contribution_residual"] - (idx[d] / idx.iloc[0] - 1)) < 2e-6


def test_compute_all_contribution_bars_reconcile_with_headline_in_bt():
    """실제 엔진(bt): 비용·적립이 없으면 잔차 0 (w(t−1)·r(t) 가 bt 지수 일 수익률과 날짜가 맞는지), 수수료만 있으면 음수, 적립까지 있어도 막대 + 잔차 = 기간 수익률."""
    rng = np.random.default_rng(3)
    cal = pd.bdate_range("2023-01-02", periods=260)
    px = pd.DataFrame({"A": 100 * np.cumprod(1 + rng.normal(0.001, 0.02, len(cal))), "B": 50 * np.cumprod(1 + rng.normal(0.0, 0.015, len(cal)))}, index=cal)
    w = {"A": 0.6, "B": 0.3}  # 현금 10%
    rb = rebalance_dates({"enabled": True, "count": 1, "unit": "1q"}, cal, cal[0], BacktestSettings())
    for bps, amount in ((0.0, 0.0), (5.0, 0.0), (5.0, 500.0)):
        s = replace_settings(BacktestSettings(), commission_bps=bps)
        cd = contribution_dates(cal, cal[0], cal[-1], 25) if amount else []
        b, res = run_static_portfolio("p", w, px, 10_000.0, rb, cd, amount, s)
        raw = extract_raw(b, res, cal[0])
        out = M.compute_all(raw, raw["index"], px, w, _CSECTORS, rb, 0.0, 0.05, 1.0, 1.0, xirr, s)
        resid = out["metrics"]["composition"]["ticker_contribution_residual"]
        assert abs(sum(out["ticker_contribution"].values()) + resid - out["metrics"]["return"]["total_return"]) < 3e-6, (bps, amount)
        if not bps and not amount:
            assert abs(resid) < 1e-6
        elif not amount:
            assert resid < 0



# ───────────────────────── 라운드 2 후속: 근거 품질 (독립 검토 에이전트 작업) ─────────────────────────
# ───────────────────────── 시나리오 003: 근거 품질 (매매거래 정지 라벨 · 공시 날짜 · 한국어 뉴스 관련성) ─────────────────────────
QA003_ASSETS = [("035420.KS", "NAVER", "STOCK"), ("035720.KS", "카카오", "STOCK"), ("267260.KS", "HD현대일렉트릭", "STOCK"), ("015760.KS", "한국전력", "STOCK"),
                ("010120.KS", "LS ELECTRIC", "STOCK"), ("005380.KS", "현대차", "STOCK"), ("AAPL", "Apple", "STOCK"), ("069500.KS", "KODEX 200", "ETF"),
                ("SPY", "SPDR S&P 500 ETF", "ETF")]  # fmt: skip
QA003_HALT = "매매거래정지및정지해제(중요내용공시)"
QA003_AS_OF = dt.date(2026, 8, 31)


def _qa003_news():
    from backend.schemas.market_ext import NewsRow
    from backend.tests.analysis.conftest import AT

    def n(aid, k, title, day, *, publisher="한국경제", url=None, source="NAVER_NEWS", lang="ko", query=None):
        return NewsRow(asset_id=aid, source=source, url=url or f"https://news.test/{aid}/{k}", title=title, publisher=publisher,
                       published_at=dt.datetime(2026, 8, day, 1, k, tzinfo=dt.UTC), language=lang, query=query, fetched_at=AT)  # fmt: skip

    return [  # 종목 안에서 최신순: 잡음·이용자 글이 가장 새것이라 거르지 않으면 상한(per_asset)을 먼저 채운다
        n("KR-035420", 1, "부산 분양 시장, 청약 열기", 30, publisher="부산일보", query="NAVER"),
        n("KR-035420", 2, "네이버페이 써보니 후기", 30, publisher="Naver Blog", source="GOOGLE_RSS"),  # 이용자 글 (회사 이름이 있어도)
        n("KR-035420", 3, "네이버 웹툰 신작 정리", 29, publisher=None, url="https://m.blog.naver.com/someone/223"),  # 주소가 블로그
        n("KR-035420", 4, "네이버 주가 전망", 29, publisher="네이버 프리미엄콘텐츠", source="GOOGLE_RSS"),
        n("KR-035420", 5, "○○구청, 가을 축제 개최", 28, publisher="뉴시스", query="NAVER"),  # 지자체 보도자료
        n("KR-035420", 6, "네이버, AI 검색 개편", 27),
        n("KR-035420", 7, "NAVER(035420) 장중 강세", 26, publisher="이데일리"),
        n("KR-035420", 8, "네이버, AI 검색 개편", 25, publisher="서울경제"),  # 같은 제목 (중복)
        n("KR-035420", 9, "네이버 클라우드 수주", 24),
        n("KR-035420", 10, "NHN 라인, 가입자 3억 돌파", 23, source="GOOGLE_RSS", query="NHN"),  # 옛 사명으로 찾은 기사: 검색어가 제목에 있으면 남김
        n("KR-035720", 1, "BMW, 신형 5시리즈 출시", 30),
        n("KR-035720", 2, "카카오, 분할합병 결정", 29),
        n("US-AAPL", 1, "Stocks rally as Fed signals cut", 30, publisher="Reuters", source="GOOGLE_RSS", lang="en"),  # 영어: 제목 검사 안 함
        n("US-AAPL", 2, "iPhone 18 launch date", 29, publisher="The Verge", source="GOOGLE_RSS", lang="en"),
    ]


def _qa003_discl():
    from backend.schemas.market_ext import DisclosureRow
    from backend.tests.analysis.conftest import AT

    def d(aid, source, fid, form, filed_at, avail, et, items=None):
        return DisclosureRow(asset_id=aid, source=source, filing_id=fid, form=form, items=items, title=form, filed_at=filed_at, available_on=avail,
                             url=f"https://filings.test/{fid}", event_type=et, rule_version="sec-v1" if source == "SEC_EDGAR" else "dart-v2", fetched_at=AT)  # fmt: skip

    return [  # DART 는 날짜만 있어 그날 0시 KST(= 전날 15시 UTC)로 저장된다. 정지 행은 예전 규칙(v2)으로 delisting_notice 로 저장됨
        d("KR-035720", "DART", "20260821000123", QA003_HALT, dt.datetime(2026, 8, 20, 15, 30, tzinfo=dt.UTC), dt.date(2026, 8, 24), "delisting_notice"),
        d("KR-035720", "DART", "20260821000456", "주요사항보고서(회사분할합병결정)", dt.datetime(2026, 8, 20, 15, 0, tzinfo=dt.UTC), dt.date(2026, 8, 24), "merger_split"),
        d("US-AAPL", "SEC_EDGAR", "0000320193-26-000001", "8-K", dt.datetime(2026, 8, 21, 1, 30, tzinfo=dt.UTC), dt.date(2026, 8, 21), "earnings", "2.02,9.01"),  # 동부 20일 21:30
    ]  # fmt: skip


def _qa003_md(**news_kw):
    from backend.analysis.m2_data.market_data import MarketData
    from backend.analysis.settings import AnalysisSettings, replace_settings
    from backend.db import open_repository
    from backend.schemas.market import PriceBar
    from backend.tests.analysis.conftest import AT, _asset

    repo = open_repository("sqlite://", clock=lambda: AT)
    repo.upsert_assets([_asset(s, n, "KR" if s.endswith(".KS") else "US", k) for s, n, k in QA003_ASSETS])
    repo.upsert_prices([PriceBar(ticker=s, date=dt.date(2026, 9, 1), adj_close=100.0, currency=c, source="TEST", fetched_at=AT) for s, c in (("SPY", "USD"), ("069500.KS", "KRW"))])  # 기준일 상한만
    repo.upsert_news(_qa003_news())
    repo.upsert_disclosures(_qa003_discl())
    s = AnalysisSettings()
    return MarketData(repo, replace_settings(s, news=replace_settings(s.news, **news_kw)) if news_kw else s)


def test_qa003_trading_halt_is_not_delisting_notice():
    """거래소의 절차상 매매거래 정지(중요 공시 전후)를 '상장폐지·관리종목 통지' 로 부르지 않는다: 수집기 규칙(새 자료) + 읽을 때 고침(저장된 자료)."""
    from backend.analysis.m2_data.disclosure_labels import EVENT_LABEL_KO, event_type_of, label_ko
    from backend.analysis.settings import DisclosureSettings
    from backend.collectors.disclosures import categories as C

    assert C.dart_event(QA003_HALT) == ("trading_halt", "dart-v3") and C.dart_event("[기재정정]" + QA003_HALT)[0] == "trading_halt"
    for name in ("상장폐지사유발생", "관리종목지정(매매거래정지)", "불성실공시법인지정(매매거래정지)", "주권매매거래정지(상장폐지사유발생)"):
        assert C.dart_event(name)[0] == "delisting_notice", name  # 진짜 상장폐지·관리종목 사유는 그대로
    assert C.dart_event("주권매매거래정지해제")[0] == "trading_halt"
    assert label_ko("trading_halt") == "매매거래 정지·해제" == EVENT_LABEL_KO["trading_halt"]
    old = {"source": "DART", "form": QA003_HALT, "title": QA003_HALT, "event_type": "delisting_notice"}
    assert event_type_of(old) == "trading_halt" == C.dart_event(QA003_HALT)[0]  # 새 규칙과 같은 판정
    for name in ("관리종목지정(매매거래정지)", "주권매매거래정지(상장폐지사유발생)"):
        assert event_type_of({**old, "form": name, "title": name}) == "delisting_notice"
    assert event_type_of({"source": "SEC_EDGAR", "form": "8-K", "items": "3.01", "title": "8-K", "event_type": "delisting_notice"}) == "delisting_notice"
    assert event_type_of({**old, "event_type": "merger_split"}) == "merger_split"
    ds = DisclosureSettings()  # 절차상 정지는 뷰 근거·90일 요약 허용 목록에 없다 (악재 사건으로 쓰지 않음)
    assert "trading_halt" not in ds.event_types and "trading_halt" not in ds.summary_extra_event_types


def test_qa003_disclosure_window_relabels_halt_and_uses_local_filing_date():
    from backend.analysis.m2_data.news import _filed_date, build_window
    from backend.analysis.m3_selection.explain import _dc_date

    assert _filed_date(dt.datetime(2026, 8, 20, 15, 30, tzinfo=dt.UTC), "DART") == dt.date(2026, 8, 21)  # 서울 21일 00:30
    assert _filed_date(dt.datetime(2026, 8, 21, 1, 30, tzinfo=dt.UTC), "SEC_EDGAR") == dt.date(2026, 8, 20)  # 뉴욕 20일 21:30
    assert _filed_date(dt.datetime(2026, 8, 20, 15, 30), "DART") == dt.date(2026, 8, 20)  # tz 없는 값은 그대로
    md = _qa003_md()
    # 허용 목록 없이 읽으면: 정지 행이 보이되 '매매거래 정지·해제' 로, 날짜는 접수번호(20260821…)와 같은 서울 날짜
    win = build_window(md, ["035720.KS", "AAPL"], QA003_AS_OF, days=14, per_ticker=10, languages=["en", "ko"], min_tickers=1, dc_days=45)
    by = {r["form"]: r for r in win.disclosures}
    halt, merger, k8 = by[QA003_HALT], by["주요사항보고서(회사분할합병결정)"], by["8-K"]
    assert (halt["event_type"], halt["event_label_ko"]) == ("trading_halt", "매매거래 정지·해제")
    assert halt["filed_at"] == halt["published_at"] == "2026-08-21" == merger["filed_at"] and halt["available_on"] == "2026-08-24"
    assert k8["filed_at"] == "2026-08-20" and k8["available_on"] == "2026-08-21"
    assert _dc_date(merger) == "2026-08-21(이용 가능일 2026-08-24)" and _dc_date(k8 | {"filed_at": "2026-08-21"}) == "2026-08-21"
    # 실제 경로(뷰 09: 허용 목록, 기업 근거 06: 허용 목록 + 정기·절차)에서는 정지가 빠지고 본 공시(분할합병)만 남는다
    from backend.analysis.settings import DisclosureSettings

    ds = DisclosureSettings()
    view = md.view(QA003_AS_OF)
    for w in (view.news_window(["035720.KS", "AAPL"]), view.news_window(["035720.KS", "AAPL"], dc_days=90, dc_event_types=[*ds.event_types, *ds.summary_extra_event_types])):
        kinds = {r["event_type"] for r in w.disclosures if r["ticker"] == "035720.KS"}
        assert kinds == {"merger_split"} and "상장폐지·관리종목 통지" not in w.event_counts("035720.KS")


def test_qa003_news_batch_skips_ugc_and_unrelated_korean_titles():
    from backend.analysis.m2_data.news import title_aliases

    md = _qa003_md()
    repo, start, end = md.repo, dt.datetime(2026, 8, 17, tzinfo=dt.UTC), dt.datetime(2026, 8, 31, tzinfo=dt.UTC)
    ids = ["KR-035420", "KR-035720", "US-AAPL"]
    aliases = {**title_aliases(md, ["035420.KS", "035720.KS"]), "US-AAPL": ["Apple"]}

    def titles(rows, aid):
        return [r.title for r in rows if r.asset_id == aid]

    rows = repo.get_news_batch(ids, start, end, aliases=aliases)
    assert titles(rows, "KR-035420") == ["네이버, AI 검색 개편", "NAVER(035420) 장중 강세", "네이버 클라우드 수주", "NHN 라인, 가입자 3억 돌파"]
    assert titles(rows, "KR-035720") == ["카카오, 분할합병 결정"]
    assert titles(rows, "US-AAPL") == ["Stocks rally as Fed signals cut", "iPhone 18 launch date"]  # 영어 기사는 이름이 없어도 그대로
    two = repo.get_news_batch(ids, start, end, aliases=aliases, per_asset=2)  # 상한은 거른 뒤의 진짜 기사로 센다
    assert titles(two, "KR-035420") == ["네이버, AI 검색 개편", "NAVER(035420) 장중 강세"] and titles(two, "KR-035720") == ["카카오, 분할합병 결정"]
    raw = repo.get_news_batch(ids, start, end)  # 이름표가 없으면 제목 검사 없음, 이용자 글만 빠짐 (중복 제목 규칙은 그대로)
    assert titles(raw, "KR-035420") == ["부산 분양 시장, 청약 열기", "○○구청, 가을 축제 개최", "네이버, AI 검색 개편", "NAVER(035420) 장중 강세", "네이버 클라우드 수주", "NHN 라인, 가입자 3억 돌파"]
    # 근거 창(설정 news.require_title_mention, 기본 켬)과 끄기
    win = md.view(QA003_AS_OF).news_window(["035420.KS", "035720.KS", "AAPL"], dc_days=0)
    assert [r["title"] for r in win.records if r["ticker"] == "035420.KS"] == titles(rows, "KR-035420")
    assert len(win.by_ticker["AAPL"]) == 2 and not any(r["publisher"] in ("Naver Blog", "네이버 프리미엄콘텐츠") for r in win.records)
    off = _qa003_md(require_title_mention=False).view(QA003_AS_OF).news_window(["035420.KS"], dc_days=0)
    assert "부산 분양 시장, 청약 열기" in [r["title"] for r in off.records] and not any("블로그" in (r["publisher"] or "") or r["publisher"] == "Naver Blog" for r in off.records)


def test_qa003_title_aliases_and_matching_rules():
    from backend.analysis.m2_data.news import title_aliases
    from backend.db.analysis_readers import _is_ugc, _title_mentions

    al = title_aliases(_qa003_md(), ["035420.KS", "035720.KS", "267260.KS", "015760.KS", "010120.KS", "005380.KS", "AAPL", "123456.KS"])
    assert {"NAVER", "네이버", "035420"} <= set(al["KR-035420"]) and {"카카오", "035720"} <= set(al["KR-035720"])
    assert "현대일렉트릭" in al["KR-267260"] and "한전" in al["KR-015760"] and "LS일렉트릭" in al["KR-010120"] and "현대자동차" in al["KR-005380"]
    assert "US-AAPL" not in al and "KR-123456" not in al  # 미국 종목·이름 모르는 종목은 검사하지 않음
    assert _title_mentions("현대일렉트릭, 美 변압기 수주", al["KR-267260"]) and _title_mentions("HD현대일렉트릭 신고가", al["KR-267260"])
    assert _title_mentions("한전, 전기요금 동결", al["KR-015760"]) and _title_mentions("LS 일렉트릭 수주", al["KR-010120"])  # 한글 이름은 띄어쓰기 무시
    assert _title_mentions("네이버가 웃었다", al["KR-035420"]) and _title_mentions("Naver to buy startup", al["KR-035420"])
    assert not _title_mentions("부산 분양 시장", al["KR-035420"]) and not _title_mentions("KTX 증편", ["KT"]) and _title_mentions("KT, 5G 요금제", ["KT"])
    assert _is_ugc("Naver Blog", None) and _is_ugc("네이버 블로그", None) and _is_ugc("네이버 프리미엄콘텐츠", None) and _is_ugc("다음 카페", None)
    assert _is_ugc(None, "https://m.blog.naver.com/x/1") and _is_ugc(None, "https://post.naver.com/viewer?x=1") and _is_ugc(None, "https://abc.tistory.com/12")
    assert _is_ugc(None, "https://contents.premium.naver.com/a/b") and _is_ugc(None, "https://brunch.co.kr/@a/1") and _is_ugc(None, "https://cafe.naver.com/x")
    assert not _is_ugc("Bloomberg", "https://www.bloomberg.com/news/a") and not _is_ugc("한국경제", "https://n.news.naver.com/article/015/1")
    assert not _is_ugc("The Washington Post", "https://news.google.com/rss/articles/abc") and not _is_ugc(None, "http://[broken")


def test_linked_contribution_per_ticker_values_and_prefix_residual():
    """검토 보강: 지수 수익 0 인 날(k_t=1) 분기를 종목별 값으로 확인하고, 앞부분만 자른 창의 K 가 그 창의 R 에서 오는지 잔차 닫힌 식으로 확인."""
    idx = _contrib_index()
    R, Rt = idx.iloc[-1] / idx.iloc[0] - 1, M.daily_returns(idx)
    K = np.log1p(R) / R
    exp = {c: sum(((np.log1p(Rt[d]) / Rt[d]) if Rt[d] != 0 else 1.0) / K * _CW[c].iloc[i - 1] * _CR[c].iloc[i] for i, d in enumerate(_CD) if i > 0) for c in "AB"}
    contrib, _ = M.linked_contribution(_CW, _CR, idx)
    assert contrib.notna().all() and all(abs(contrib[c] - exp[c]) < 1e-12 for c in "AB")
    idx2 = _contrib_index({2: 0.001})
    d = _CD[4]
    px = 100 * (1 + _CR).cumprod()
    part = M.composition_metrics(_CW.loc[:d], px, {"A": 0.55, "B": 0.35}, _CSECTORS, 1.0, 1.0, 0.25, idx2.loc[:d])
    Rp, rt = idx2[d] / idx2.iloc[0] - 1, idx2.iloc[2] / idx2.iloc[1] - 1
    assert abs(part["ticker_contribution_residual"] + (np.log1p(rt) / rt) / (np.log1p(Rp) / Rp) * 0.001) < 2e-6


def test_contribution_residual_is_costs_only_with_large_contributions():
    """검토: 적립이 큰 실행에서 수수료 0 인데도 잔차가 −3.4%p (bt 의 적립일 희석) → values·flows 로 비중을 줄여 잔차 ≈ 0."""
    rng = np.random.default_rng(7)
    cal = pd.bdate_range("2023-01-02", periods=520)
    px = pd.DataFrame({"A": 100 * np.cumprod(1 + rng.normal(0.0015, 0.02, len(cal))), "B": 50 * np.cumprod(1 + rng.normal(0.0005, 0.015, len(cal)))}, index=cal)
    w = {"A": 0.6, "B": 0.35}
    rb = rebalance_dates({"enabled": True, "count": 1, "unit": "1q"}, cal, cal[0], BacktestSettings())
    s = replace_settings(BacktestSettings(), commission_bps=0.0)
    b, res = run_static_portfolio("p", w, px, 1_000.0, rb, contribution_dates(cal, cal[0], cal[-1], 25), 1_000.0, s)
    raw = extract_raw(b, res, cal[0])
    out = M.compute_all(raw, raw["index"], px, w, _CSECTORS, rb, 0.0, 0.05, 1.0, 1.0, xirr, s)
    assert abs(out["metrics"]["composition"]["ticker_contribution_residual"]) < 2e-3


def test_shrink_to_result_size_keeps_same_candidates(e2e):
    """004: GICS 넓히기를 필터 전 일치 수로 판단해 목표 25 일 때 넓혀서 4개 → '4개로 줄임' 뒤에는 넓히지 않아 3개.
    합성 자료로 같은 상황: 반도체 소분류(45301020) 6개 중 2개를 제외 종목으로 빼면 4개, 한 단계 넓히면(453010) AMAT 이 더해져 5개.
    예전 규칙: 목표 10 → 일치 6 < 10 이라 넓혀 5개, 목표 5 → 일치 6 ≥ 5 라 안 넓혀 4개 (어긋남). 지금은 둘 다 5개.
    (합성 가격·시가총액은 프로세스마다 달라지는 hash 로 만들어 시가총액 하한 대신 제외 종목으로 거른다)"""
    import json as _json

    from backend.analysis.m3_selection.retrieve import retrieve
    from backend.tests.analysis.test_pipeline_e2e import REQUEST

    ctx, _ = e2e
    view = ctx.md.view(ctx.out("_bt_ctx")["end"].date())
    it = _json.loads(_json.dumps(ctx.outputs["02_intent"]))
    it["interpretation"]["themes"] = [{**it["interpretation"]["themes"][0], "gics_codes": ["45301020"], "keywords": [], "example_tickers": []}]
    cons = _json.loads(_json.dumps(REQUEST["constraints"]))
    cons.update(min_market_cap_usd=0, min_avg_daily_volume_usd=0, exclude_tickers=["NVDA", "AMD"], must_include_tickers=[])
    got = {}
    for tgt in (10, 5):
        cons["num_holdings"] = {"target": tgt, "min": tgt, "max": tgt}
        got[tgt] = sorted(c.ticker for c in retrieve(view, ctx.desc, it, cons, request_id="t", max_candidates=None).candidates)
    cons["num_holdings"] = {"target": 5, "min": 5, "max": 5}
    unwidened = retrieve(view, ctx.desc, it, cons, request_id="t", max_candidates=None, _widen=False)
    assert unwidened.stats["n_matched"] == 6 and len(unwidened.candidates) == 4  # 예전 규칙이면 여기서 넓히지 않았다 (6 ≥ 5)
    assert got[10] == got[5] and "AMAT" in got[5] and len(got[5]) == 5


def test_news_gate_review_fixes():
    """검토 보강: (1) 'HL만도 OR 만도 OR Mando' 같은 OR 검색어는 나눠서 본다 (통째로 비교하면 HL만도 8,154건 중 3건만 남았다)
    (2) 영어 기사의 회사 공지 블로그(Cisco Blogs·NVIDIA Blog)는 이용자 글이 아니다 (3) '공식 블로그' 는 남긴다 (4) 흔한 줄임말 별칭."""
    import datetime as _dt

    from backend.analysis.m2_data.news import KR_TITLE_ALIASES
    from backend.db import open_repository
    from backend.db.analysis_readers import _is_ugc
    from backend.schemas.market_ext import NewsRow
    from backend.tests.analysis.conftest import AT, _asset

    assert not _is_ugc("NVIDIA Blog", "https://blogs.nvidia.com/x", "en") and not _is_ugc("Cisco Blogs", None, "en")
    assert _is_ugc("Naver Blog", None, "ko") and _is_ugc("네이버 프리미엄콘텐츠", None, "ko") and not _is_ugc("에이피알 공식 블로그", None, "ko")
    assert _is_ugc(None, "https://blog.naver.com/someone/1", "en")  # 주소가 블로그면 언어와 무관
    assert {"SKT"} <= set(KR_TITLE_ALIASES["017670"]) and "엔씨소프트" in KR_TITLE_ALIASES["036570"]
    repo = open_repository("sqlite://", clock=lambda: AT)
    repo.upsert_assets([_asset("204320.KS", "HL만도", "KR", "STOCK")])
    repo.upsert_news([NewsRow(asset_id="KR-204320", source="NAVER_NEWS", url=f"https://news.test/m/{k}", title=t, publisher="한국경제",
                              published_at=_dt.datetime(2015, 3, 2 + k, 1, tzinfo=_dt.UTC), language="ko", query="만도 OR HL만도 OR Mando", fetched_at=AT)
                      for k, t in enumerate(["만도, 3분기 영업이익 증가", "부산 분양 시장 열기"])])  # fmt: skip
    rows = repo.get_news_batch(["KR-204320"], _dt.datetime(2015, 3, 1, tzinfo=_dt.UTC), _dt.datetime(2015, 3, 9, tzinfo=_dt.UTC),
                               per_asset=10, aliases={"KR-204320": ["HL만도", "204320"]})  # fmt: skip
    assert [r.title for r in rows] == ["만도, 3분기 영업이익 증가"]
