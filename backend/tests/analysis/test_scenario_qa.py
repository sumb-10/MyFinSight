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
        assert "주식 49.4%" in name and "현금 50.6%" in name  # 이름이 이 구성의 실제 비중 (백테스트 이름과 같은 소수 첫째 자리, 015)
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
    R = {"request": {"constraints": {"min_cash_ratio": 0.0, "max_weight_per_stock": 0.25, "max_weight_per_sector": 1.0}}, "backtest": {"portfolios": [base, m]}}
    orig = RP.B.find
    try:
        RP.B.find = lambda R_, pid: next(p for p in R_["backtest"]["portfolios"] if p["id"] == pid)
        cb = RP.cash_breakdown(R, m)
    finally:
        RP.B.find = orig
    assert cb["stocks"] == "49.0%" and cb["cash"] == "51.0%" and cb["cash_by_caps"] == "50.0%" and cb["cash_added_by_drawdown_match"] == "1.0%"
    assert cb["min_cash_by_user"] is None
    assert cb["cash_by_caps_cause_ko"] == "백테스트 시작일 구성은 2종목이라 종목당 상한 25%로는 50%까지만 담겨 남은 몫"


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


def test_usd_request_has_no_krw_conversion_text(e2e_results):
    """007: 달러 요청 리포트에 '1 USD = 1.00 KRW' 가 다섯 군데(요청 내용·배분표 제목·계산 조건 두 줄·대시보드), 원화 열은 달러와 같은 숫자 (N-T3-8)."""
    import copy
    import json as _json

    from backend.analysis.m5_backtest_report import report_blocks as RB

    R, _s = e2e_results
    R = copy.deepcopy(R)
    R["request"]["capital"]["currency"] = "USD"
    R["money_krw"]["fx_rate"] = 1.0
    R["money_krw"]["direction"] = "1 USD = 1.00 KRW"
    R["money_krw"]["backtest_fx"].update(fx_rate=1.0, direction="1 USD = 1.00 KRW")
    chosen = R["validation"]["recommended"]["id"]
    blocks = [RB.request_table(R), RB.parameters_table(R), RB.allocation_table(R, chosen), *RB.forward_blocks(R, chosen)]
    txt = _json.dumps(blocks, ensure_ascii=False)
    assert "1 USD = 1.00 KRW" not in txt and '"원화"' not in txt
    assert RB.build_summary(R, chosen, {}, {})["allocation"]["fx_direction"] is None


def test_cautious_reason_names_only_matching_condition():
    """F14: 성향 문구가 실제 조건(손실 시 매도 OR 투자 경험 없음) 중 해당하는 것만."""
    from backend.analysis.m5_backtest_report.validate import cautious_reason_ko

    assert cautious_reason_ko({"risk": {"loss_reaction": "sell"}, "profile": {"investment_experience": "intermediate"}}) == "손실 시 매도"
    assert cautious_reason_ko({"risk": {"loss_reaction": "hold"}, "profile": {"investment_experience": "none"}}) == "투자 경험 없음"
    assert cautious_reason_ko({"risk": {"loss_reaction": "sell"}, "profile": {"investment_experience": "none"}}) == "손실 시 매도 · 투자 경험 없음"


def test_sector_overflow_callout_says_which_date():
    """008: 시작일 선정의 '정보기술 10개가 섹터 상한 70% 를 나눠 갖습니다' 가 날짜 없이 나왔다."""
    from backend.analysis.m5_backtest_report.report_blocks import infeasibility_callout

    ov = {"note_ko": "정보기술 종목이 10개로 섹터 상한 70%를 나눠 갖습니다.", "tickers": ["NVDA", "AMAT"]}
    R = {"selection": {"backtest_as_of": {"as_of": "2022-06-21", "sector_overflow": ov}, "as_of_now": {"as_of": "2025-06-18"}}}
    assert infeasibility_callout(R)["text_ko"].startswith("백테스트 시작일(2022-06-21) 선정: ")


def test_sector_cap_question_comes_before_start_question(monkeypatch, svc_factory):
    """010: 시작일 질문('기간 유지 — 투자금의 60%만 투자')을 먼저 묻고 섹터 상한을 90% 로 올려 안내가 틀어졌다 → 섹터 상한 질문이 먼저."""
    import backend.analysis.m1_request.dialog as DG
    from backend.tests.analysis.test_dialog import _intent

    fake = {"signature": "x", "basis": "after_classification", "min": 25, "target": 30, "short_now": False, "short_at_start": True, "capacity_short": True,
            "as_of": {"n_selected": 25, "n_with_metric": 25, "n_candidates": 25, "capacity": 0.6, "invest": 0.9, "sector_counts": {"Health Care": 25}, "cap_needed": 0.9},
            "start": {"date": "2023-06-12", "n_selected": 23, "n_with_metric": 23, "n_candidates": 28, "capacity": 0.6, "sector_counts": {"Health Care": 23}},
            "feasible_start": None}  # fmt: skip
    monkeypatch.setattr(DG, "run_precheck", lambda *a, **kw: fake)
    svc, _store, _llm = svc_factory([_intent([])] * 3, sector_rule=True)
    st = svc.start("미국 헬스케어 저변동성")
    assert st.question.field == "constraints.max_weight_per_sector"


def test_no_consent_wording_after_auto_shift(monkeypatch, seeded_repo, descriptor_dir):
    """011: 시작일 질문을 하지 않았는데(보기가 1개뿐) '시작일을 옮기는 데 동의하지 않아' 라고 썼다 → '동의를 받지 않아' + 자동 이동 사실."""
    from types import SimpleNamespace

    import backend.analysis.m4_portfolio.spec as S
    from backend.analysis.schemas.selection import Tagging

    md, req, desc, s = _spec_inputs(seeded_repo, descriptor_dir)
    counts, seen = [1, 2, 2, 2, 2, 2], []

    def fake_at(md_, day, desc_, intent_, cons_, passed, rid, **kw):
        seen.append(day)
        return (SimpleNamespace(candidates=[], model_dump=lambda **k: {}), Tagging(request_id="r", min_confidence=0, tagged=[], passed_tickers=[], batches=0),
                _fake_selection(counts[min(len(seen) - 1, len(counts) - 1)]), [])  # fmt: skip

    monkeypatch.setattr(S, "selectable_at", fake_at)
    tag = Tagging(request_id="r", min_confidence=0.5, tagged=[], passed_tickers=["NVDA", "AMD", "AVGO", "MU", "AMAT", "MSFT"], batches=0)
    spec, _ = S.build_backtest_spec(md, req, {"screen": {"metric": "return_12m_1m"}}, tag, _fake_selection(6), desc, s, start_shift_ok=False)
    txt = " ".join(spec["warnings"])
    assert "자동으로 옮겼고" in txt and "동의를 받지 않아" in txt and "동의하지 않아" not in txt


def test_broken_pooled_connection_is_retried():
    """012: 네트워크 오류 뒤 풀의 사전 점검이 'can't change autocommit now: connection in transaction status ACTIVE' 로 실패해 일꾼이 멈췄다 → 끊긴 연결로 보고 다시."""
    from sqlalchemy.exc import ProgrammingError

    from backend.db.sql import _disconnected

    e = ProgrammingError("SELECT 1", {}, Exception("can't change 'autocommit' now: connection in transaction status ACTIVE"))
    assert _disconnected(e)
    assert not _disconnected(ProgrammingError("SELECT x", {}, Exception('column "x" does not exist')))  # 진짜 SQL 오류는 다시 하지 않음


def test_harness_caps_horizon_to_service_range():
    """013: 시나리오의 투자기간 15년은 프로필 범위(1~10년) 밖이라 저장이 거부됐다 → 시험 도구가 10년으로 줄이고 기록."""
    from backend.analysis.eval.run_scenarios import normalize_request

    req, notes = normalize_request({"capital": {"trading_currency": "USD"}, "constraints": {}, "horizon": {"target_years": 15}})
    assert req["horizon"]["target_years"] == 10 and any("target_years" in n for n in notes)


def test_shrink_label_mentions_only_raised_caps(monkeypatch, svc_factory):
    """012: 이미 15% 인 종목당 상한을 '15%로 올려' 라고 썼다 → 실제로 올리는 상한만."""
    import backend.analysis.m1_request.dialog as DG
    from backend.tests.analysis.test_dialog import _intent

    fake = {"signature": "x", "basis": "after_classification", "min": 12, "target": 15, "short_now": True, "short_at_start": False, "capacity_short": False,
            "as_of": {"n_selected": 9, "n_with_metric": 9, "n_candidates": 9, "capacity": 0.7, "invest": 0.9, "sector_counts": {"Financials": 9}},
            "start": None, "feasible_start": None}  # fmt: skip
    monkeypatch.setattr(DG, "run_precheck", lambda *a, **kw: fake)
    svc, _store, _llm = svc_factory([_intent([])] * 3)
    st = svc.start("국내 은행 고배당", overrides={"constraints.max_weight_per_stock": 0.15, "constraints.max_weight_per_sector": 0.7, "constraints.min_cash_ratio": 0.1,
                                                 "constraints.num_holdings": {"target": 15, "min": 12, "max": 18}})  # fmt: skip
    lab = next(o.label_ko for o in st.question.options if o.patch and "constraints.num_holdings" in o.patch)
    assert "종목당 상한" not in lab and "섹터당 상한 90%" in lab and lab.startswith("종목 수를 9개로 줄이고")


def test_sector_preference_marks_only_names_that_would_have_made_the_cut(monkeypatch):
    """008: 대신 들어간 종목(AMZN)이 맨 꼴찌라, 어차피 순위 밖인 TER·LRCX·INTC 까지 '섹터 선호로 빠졌다' 고 했다 (실제로는 WDC 하나).
    순위대로라면 뽑혔을 종목만 sector_preference, 공지에 대신 들어간 종목 이름."""
    from types import SimpleNamespace

    import pandas as pd_

    from backend.analysis.common.warnings import from_text
    from backend.analysis.m2_data import metrics as Mx
    from backend.analysis.m3_selection.screen import screen

    vals = {"A1": 0.9, "A2": 0.8, "A3": 0.7, "A4": 0.6, "A5": 0.5, "B1": 0.1}
    monkeypatch.setitem(Mx.METRICS, "return_12m_1m", lambda view, tks: (pd_.Series({t: vals[t] for t in tks}, dtype=float), []))
    sec = {"A": ("45", "Information Technology"), "B": ("25", "Consumer Discretionary")}
    monkeypatch.setattr("backend.analysis.m3_selection.screen.D.gics_model",
                        lambda e: SimpleNamespace(sector=SimpleNamespace(code=sec[e["ticker"][0]][0], name=sec[e["ticker"][0]][1])))  # fmt: skip
    desc = SimpleNamespace(by_ticker=lambda t: {"ticker": t, "name": t, "market": "US", "gics": {}})
    tagging = SimpleNamespace(tagged=[SimpleNamespace(ticker=t, confidence=0.9) for t in vals], passed_tickers=list(vals))
    intent = {"screen": {"metric": "return_12m_1m", "direction": "desc"}}
    cons = {"num_holdings": {"min": 1, "target": 3, "max": 3}, "max_weight_per_stock": 1.0, "max_weight_per_sector": 0.5, "min_cash_ratio": 0.0}
    sel, _ = screen(SimpleNamespace(as_of=dt.date(2025, 6, 25)), desc, tagging, intent, cons, request_id="r")
    reasons = {r.ticker: r.reason for r in sel.rejected}
    assert sorted(s.ticker for s in sel.selected) == ["A1", "A2", "B1"]
    assert reasons == {"A3": "sector_preference", "A4": "rank_beyond_n", "A5": "rank_beyond_n"}
    w = from_text("05_selection", next(x for x in sel.warnings if x.startswith("sector count preference")))
    assert "A3" in w.message_ko and "A4" not in w.message_ko and "(B1)" in w.message_ko


def test_walkforward_drift_measured_against_date_specific_targets():
    """008: walk-forward 드리프트를 마지막 목표 하나와 비교해 0.0965 로 보였다 (실제 날짜별 목표 대비 0.048). 그날 적용 중인 목표와 비교한다."""
    import pandas as pd_

    from backend.analysis.m5_backtest_report.backtest_metrics import composition_metrics

    idx = pd_.bdate_range("2024-01-01", periods=6)
    w = pd_.DataFrame({"A": [0.6, 0.6, 0.6, 0.3, 0.3, 0.3], "B": [0.4, 0.4, 0.4, 0.7, 0.7, 0.7]}, index=idx)
    px = pd_.DataFrame({"A": [1.0] * 6, "B": [1.0] * 6}, index=idx)
    tbd = {str(idx[0].date()): {"A": 0.6, "B": 0.4}, str(idx[3].date()): {"A": 0.3, "B": 0.7}}
    sectors = {"A": "IT", "B": "HC"}
    one = pd_.Series(1.0, index=idx)
    by_date = composition_metrics(w, px, tbd[str(idx[0].date())], sectors, 1.0, 1.0, 0.0, one, targets_by_date=tbd)
    last_only = composition_metrics(w, px, tbd[str(idx[3].date())], sectors, 1.0, 1.0, 0.0, one)
    assert by_date["max_weight_drift"] == 0.0 and by_date["max_sector_drift"] == 0.0
    assert last_only["max_weight_drift"] > 0.29


def test_explain_prompt_uses_metric_rank_and_marks_forced():
    """010: 06 설명에 선정 순서(필수 포함 = 1)를 순위로 넘겨 VRTX 를 '변동성 첫 순위' 라고 썼다 (실제 5위). 지표 순위 + '(필수 포함)' 표시."""
    from types import SimpleNamespace

    from backend.analysis.m3_selection.explain import explain
    from backend.analysis.schemas.selection import Selected

    def row(t, rank, v, forced=False):
        return Selected(ticker=t, name=t, sector="Health Care", sector_code="35", rank=rank, metric_name="vol_60d", metric_value=v, forced=forced)

    sel = SimpleNamespace(request_id="r", selected=[row("VRTX", 1, 0.2423, True), row("JNJ", 2, 0.1825), row("PFE", 3, 0.1917)],
                          summary={"metric": "vol_60d", "direction": "asc", "as_of": "2026-06-11"})  # fmt: skip
    tagging = SimpleNamespace(tagged=[SimpleNamespace(ticker=t, reason_ko="r", themes=["pharma_biotech"]) for t in ("VRTX", "JNJ", "PFE")])
    intent = {"interpretation": {"summary_ko": "s"}, "report_settings": {"explanation_level": "beginner"}}
    seen = {}

    class Llm:
        def complete_json(self, stage, messages, validator=None):
            seen["user"] = messages[-1]["content"]
            return {"portfolio_summary_ko": "s", "per_ticker": []}

    explain(sel, tagging, intent, Llm(), facts=[])
    lines = {ln.split(" | ")[1]: ln.split(" | ")[0] for ln in seen["user"].splitlines() if " | " in ln and not ln.startswith("##")}
    assert lines == {"VRTX": "3 (필수 포함)", "JNJ": "1", "PFE": "2"}
    assert "pharma biotech" in seen["user"]


def test_no_matched_plan_suggestion_is_dropped_when_none_exists():
    """011: 맞춤안이 없는데(기준 낙폭 34.7% ≤ 목표 35%) 다음 행동에 '낙폭 맞춤안을 검토할 수 있습니다' 가 나왔다 (001 Q-013 재발).
    그 문장만 빼고, 없다는 사실을 말하는 문장은 둔다."""
    from backend.analysis.m5_backtest_report.report import _drop_matched_suggestions

    ans = {"next_actions_ko": ["과거 최대낙폭이 감당 가능한 수준인지 손실 감내 수준을 다시 확인해 보세요. 허용 수준에 가까운 낙폭이 불편하다면 낙폭 맞춤안을 검토할 수 있습니다.",
                               "낙폭 맞춤안을 검토해 보세요.", "테마를 넓혀 재분석해 보세요."],
           "risk_fit_ko": ["기준 구성의 낙폭이 이미 목표 안이라 낙폭 맞춤안은 만들 필요가 없었습니다. 확인해 보세요."]}  # fmt: skip
    _drop_matched_suggestions(ans, ("next_actions_ko", "risk_fit_ko"))
    assert ans["next_actions_ko"] == ["과거 최대낙폭이 감당 가능한 수준인지 손실 감내 수준을 다시 확인해 보세요.", "테마를 넓혀 재분석해 보세요."]
    assert ans["risk_fit_ko"][0].startswith("기준 구성의 낙폭이 이미 목표 안이라 낙폭 맞춤안은 만들 필요가 없었습니다.")
    # 검토(2026-11-04)에서 나온 사례: 부정은 맞춤안~동사 사이에서만, 다시 분석하라는 안내는 둔다, 소수점이 있어도 잡는다
    keep = ["낙폭 맞춤안이 필요하다면 손실 감내 수준을 낮춰 다시 분석해 볼 수 있습니다.", "낙폭 맞춤안이 없으므로 현금 비중을 직접 검토해 보세요.",
            "낙폭 맞춤안 후보가 없어 동일비중 구성을 선택했습니다.", "낙폭 맞춤안이 필요하면 다시 분석하는 것을 고려해 보세요."]
    drop = ["더 낮은 낙폭을 우선한다면 낙폭 맞춤안을 살펴볼 수 있지만, 이번 결과에는 별도의 맞춤안이 필요하지 않았습니다.",
            "낙폭 맞춤안처럼 현금을 12.5% 섞은 구성을 검토할 수 있습니다.", "낙폭 맞춤안(현금 30.0%)을 검토해 보세요.",
            "낙폭 맞춤안을 검토할 수 있지만 결과를 장담할 수 없습니다."]  # fmt: skip
    ans2 = {"next_actions_ko": [*keep, *drop, "적립을 유지할지 검토해 보세요."]}
    _drop_matched_suggestions(ans2, ("next_actions_ko",))
    assert ans2["next_actions_ko"] == [*keep, "적립을 유지할지 검토해 보세요."]


def test_r9_cash_cause_names_stock_cap_and_backtest_basis():
    """011: 섹터 상한 100% 인데 R9 가 '종목·섹터 상한 때문에 50%를 더 넣지 못했다' 고 해서, 지금 9종목·현금 0% 구성 옆에서 지금 현금처럼 읽혔다."""
    from backend.analysis.m5_backtest_report.validate import evaluate_checks

    def run(w, stock, sector):
        p = {"id": "x", "kind": "template", "target_weights": w, "headline": {"max_drawdown": -0.1, "cagr": 0.1},
             "metrics": {"composition": {"breaches": [], "max_weight_drift": 0.0, "max_sector_drift": 0.0}, "risk": {"ann_vol": 0.15, "max_drawdown": -0.1}, "return": {"cagr": 0.1, "total_return": 0.1},
                         "vs_benchmark": {"excess_cagr": 0.0}, "trading": {"n_rebalances": 1}},
             "series": {"index": [100, 101]}, "checkpoints": [{"kind": "rebalance", "weights": {"after": w}}]}  # fmt: skip
        crit = {"max_drawdown": 0.2, "match_target": 0.2, "horizon_years": 0, "target_annual_return": 0.05, "benchmark": "SPY", "volatility_preference": "medium",
                "vol_band": 1.0, "max_weight_per_stock": stock, "max_weight_per_sector": sector, "min_holdings": 1, "min_cash_ratio": 0.0}  # fmt: skip
        cks = evaluate_checks(p, crit, 2, 1, lambda t: "IT", 0.5, False, settings=AnalysisSettings())[0]
        return next(c for c in cks if c["rule"] == "R9")["message_ko"]

    msg = run({"A": 0.25, "B": 0.25}, 0.25, 1.0)
    assert "백테스트 시작일 구성은 2종목이라 종목당 상한 25%로는 50%까지만" in msg and "섹터 상한" not in msg
    assert "섹터 상한 60% 때문에" in run({"A": 0.2, "B": 0.2, "C": 0.2}, 0.5, 0.6)
    # 002: 2종목 × 25% 에 섹터 상한 35% — 두 상한이 다 걸린다 (섹터 상한만 탓하면 '섹터 상한을 올리면 된다' 로 읽힌다)
    both = run({"A": 0.175, "B": 0.175}, 0.25, 0.35)
    assert "종목당 상한 25%로는 50%까지만 담기고, 섹터 상한 35%에도 걸려" in both and "섹터 상한만 올리면 50%까지만" in both


def test_timeline_blanks_annualized_metrics_under_one_year():
    """009·010: 29거래일 구간에 'CAGR -16.6%', 14거래일에 'CAGR 21.7%' 를 보였다. 1년 미만이면 연환산 값은 비우고(화면은 '–') 기간 수익률·MDD 는 둔다."""
    from backend.analysis.m5_backtest_report.report_blocks import _to_date_view

    short = _to_date_view({"total_return": -0.02, "cagr": -0.166, "max_drawdown": -0.05, "sharpe": -2.7, "excess_cagr": -0.1, "reliable": False})
    assert short == {"total_return": -0.02, "cagr": None, "max_drawdown": -0.05, "sharpe": None, "excess_cagr": None}
    long = _to_date_view({"total_return": 0.2, "cagr": 0.09, "max_drawdown": -0.1, "sharpe": 0.8, "excess_cagr": 0.01, "reliable": True})
    assert long["cagr"] == 0.09 and long["sharpe"] == 0.8 and _to_date_view(None) is None


def test_tilt_cap_and_bl_card_changes_use_percentage_points():
    """008·010: 카드가 '+5.0%'(상대 변화로 읽힘), 한도가 '3%p'(실제 3.33%p) 로 적혀 실제 +3.3%p 변화가 한도를 넘어 보였다."""
    from backend.analysis.m5_backtest_report.report_blocks import _pp

    assert _pp(0.033333) == "3.33%p" and _pp(0.05) == "5%p" and _pp(0.1) == "10%p"


def test_sampled_chart_keeps_every_series_drawdown_trough():
    """010: 표본(2칸마다)에서 QQQ 최저점(2025-04-08)이 빠져 차트 최저 -21.3%, 본문·KPI 는 22.8% 였다."""
    from backend.analysis.m5_backtest_report.report_blocks import sample_series

    n = 20
    dates = [f"2025-01-{i + 1:02d}" for i in range(n)]
    pf = {"index": [100.0] * n, "drawdown": [0.0] * n}
    pf["drawdown"][4] = -0.1
    bench = {"index": [100.0] * n, "drawdown": [0.0] * n}
    bench["drawdown"][7] = -0.228  # 홀수 칸 → stride 2 에서 빠지던 자리
    ds, out, meta = sample_series(dates, {"p": pf, "benchmark_QQQ": bench}, max_points=10, pin_id="p")
    assert "2025-01-08" in ds and min(out["benchmark_QQQ"]["drawdown"]) == -0.228
    assert "2025-01-08" in meta["pinned_troughs"]


def test_delta_cap_is_disclosed_not_called_market_estimate():
    """009: 기준일 δ=8.0 은 상한이 정한 값인데 '시장 자료로 추정' 이라고만 적었다."""
    from backend.analysis.m5_backtest_report.report_blocks import _delta_src_ko
    from backend.analysis.schemas.portfolio import MarketModel

    assert "delta_capped" in MarketModel.model_fields
    assert _delta_src_ko({"delta_source": "market_implied", "delta_capped": True}) == "시장 자료로 추정한 값이 상한 8을 넘어 상한 적용"
    assert _delta_src_ko({"delta_source": "market_implied"}) == "시장 자료로 추정"


def test_eligibility_range_reads_in_display_units():
    """009: 제외 표에 'roe_ttm=-0.1572, 범위 >0 ≤10' 이 퍼센트 값 옆에 나와 ROE 상한이 10% 처럼 읽혔다 (실제 1,000%)."""
    from backend.analysis.m2_data.metrics import eligible_range_ko

    assert eligible_range_ko("roe_ttm") == "0% 초과 1,000% 이하"
    assert eligible_range_ko("pe_ttm") == "0배 초과 50배 이하"
    assert eligible_range_ko("dividend_yield_ttm") == "0% 초과 30% 이하"
    assert eligible_range_ko("return_12m_1m") == ""


def test_market_facts_balance_headlines_per_ticker_and_give_counts():
    """009: 14c 에 전체 최신 60건만 넘겨(이틀치, SOLV 0건) '최근 헤드라인은 08-18~19', 'SOLV 헤드라인 근거 없음' 이라고 썼다 (SOLV 10건)."""
    from backend.analysis.m5_backtest_report import report as RP

    idx = {}
    k = 0
    for t, n, day in [("AAA", 80, "2026-08-19"), ("SOLV", 10, "2026-08-10")]:
        for i in range(n):
            k += 1
            idx[f"ev{k}"] = {"kind": "news", "tickers": [t], "published_at": day, "title": f"{t} {i}", "source": "x", "language": "en", "window_as_of": "2026-08-20"}
    idx["ev999"] = {"kind": "news", "tickers": ["SOLV"], "published_at": "2024-01-02", "title": "old wf window", "source": "x", "window_as_of": "2024-01-03"}
    R = {"evidence_index": idx, "selection": {"table": [{"ticker": "AAA", "in_selection_now": True}, {"ticker": "SOLV", "in_selection_now": True}]}}
    win, news, _ = RP._asof_news(R)
    assert win == "2026-08-20" and len(news) == 90  # walk-forward 창의 옛 헤드라인은 빼고
    picked = RP._balanced_news([{**x, "ticker": x["tickers"][0]} for x in news], {"AAA", "SOLV"}, 60)
    assert sum(1 for x in picked if x["ticker"] == "SOLV") == 10 and len(picked) == 60


def test_forward_news_note_when_news_off_mentions_loaded_headlines():
    """009: 뉴스 끔 분석의 기준일 구성 문단이 '헤드라인 건수·evidence id 가 없다' 고 썼다 (같은 리포트가 기준일 헤드라인 4건 인용)."""
    from backend.analysis.m5_backtest_report.report import _forward_news_note

    idx = {"ev1": {"kind": "news", "tickers": ["A"], "published_at": "2026-08-06", "title": "t", "window_as_of": "2026-08-20"},
           "ev2": {"kind": "news", "tickers": ["B"], "published_at": "2026-08-19", "title": "t", "window_as_of": "2026-08-20"}}
    note = _forward_news_note({"intent": {"news_tilt": {"enabled": False}}, "evidence_index": idx})
    assert "헤드라인 2건(2026-08-06 ~ 2026-08-19)" in note and "evidence" not in note
    assert _forward_news_note({"intent": {"news_tilt": {"enabled": True}}, "evidence_index": idx}) is None


def _screen_two_caps(monkeypatch, vals, sectors, stock, sector):
    from types import SimpleNamespace

    import pandas as pd_

    from backend.analysis.m2_data import metrics as Mx
    from backend.analysis.m3_selection.screen import screen

    monkeypatch.setitem(Mx.METRICS, "return_12m_1m", lambda view, tks: (pd_.Series({t: vals[t] for t in tks}, dtype=float), []))
    monkeypatch.setattr("backend.analysis.m3_selection.screen.D.gics_model",
                        lambda e: SimpleNamespace(sector=SimpleNamespace(code=sectors[e["ticker"]][0], name=sectors[e["ticker"]][1])))  # fmt: skip
    desc = SimpleNamespace(by_ticker=lambda t: {"ticker": t, "name": t, "market": "US", "gics": {}})
    tagging = SimpleNamespace(tagged=[SimpleNamespace(ticker=t, confidence=0.9) for t in vals], passed_tickers=list(vals))
    intent = {"screen": {"metric": "return_12m_1m", "direction": "desc"}}
    cons = {"num_holdings": {"min": 1, "target": len(vals), "max": len(vals)}, "max_weight_per_stock": stock, "max_weight_per_sector": sector, "min_cash_ratio": 0.0}
    sel, _ = screen(SimpleNamespace(as_of=dt.date(2024, 3, 5)), desc, tagging, intent, cons, request_id="r")
    return sel.infeasibility


def test_infeasibility_cause_follows_the_binding_cap(monkeypatch):
    """011 검토: cause_ko 를 needed 로 갈라, 섹터 상한 30% 가 묶는데도 '2개뿐이라 종목당 25%로 50%까지' 라고 썼다 (실제 30%).
    34%·66% 같은 상한이면 needed 탐색이 100% 를 건너뛰어 '3개뿐이라 102%까지' 가 나왔다."""
    inf = _screen_two_caps(monkeypatch, {"A": 0.9, "B": 0.8}, {"A": ("20", "Industrials"), "B": ("20", "Industrials")}, 0.25, 0.30)
    assert inf["capacity"] == 0.3 and inf["cap_needed_for_target"] is None
    assert inf["cause_ko"] == "2024-03-05 선정 종목은 2종목이라 종목당 상한 25%로는 50%까지만 담기고, 섹터 상한 30%에도 걸려 30%까지만 담깁니다 (상한이 종목 수를 줄인 것이 아닙니다)"
    it = {t: ("45", "Information Technology") for t in "ABC"}
    inf = _screen_two_caps(monkeypatch, {"A": 0.9, "B": 0.8, "C": 0.7}, it, 0.34, 0.66)
    assert inf["cap_needed_for_target"] == 1.0 and inf["cause_ko"] == "2024-03-05 선정 종목은 섹터 상한 66% 때문에 66%까지만 담깁니다"


def test_cash_breakdown_names_the_binding_cap_for_cap_cash():
    """011: cash_breakdown 의 '종목·섹터 상한 때문에 배분하지 못한 몫' 을 그대로 옮겨, 섹터 상한 100% 인데 섹터 탓을 했다."""
    from backend.analysis.m5_backtest_report.report import cash_breakdown

    p = {"id": "market_cap", "kind": "template", "target_weights": {"A": 0.25, "B": 0.25}}
    R = {"request": {"constraints": {"min_cash_ratio": 0.0, "max_weight_per_stock": 0.25, "max_weight_per_sector": 1.0}},
         "selection": {"table": [{"ticker": "A", "sector": "Industrials"}, {"ticker": "B", "sector": "Utilities"}]}}  # fmt: skip
    cb = cash_breakdown(R, p)
    assert cb["cash_by_caps"] == "50.0%" and cb["cash_by_caps_cause_ko"] == "백테스트 시작일 구성은 2종목이라 종목당 상한 25%로는 50%까지만 담겨 남은 몫"


def test_matched_note_advice_depends_on_why_no_plan_was_built():
    """011 검토: '손실 감내 수준을 낮춰 다시 분석하라' 는 이미 목표 안일 때만 맞다. 하한 때문에 못 만들었으면 낮출수록 더 못 만든다."""
    from backend.analysis.m5_backtest_report.report import _matched_note

    def R(mdd):
        return {"backtest": {"portfolios": [{"id": "equal_weight", "kind": "template", "headline": {"max_drawdown": mdd}}]},
                "intent": {"risk_params": {"effective_max_drawdown": 0.10}}, "request": {"risk": {"max_drawdown_tolerance": 0.12}},
                "portfolio": {"targets": {"baseline": {"id": "equal_weight"}}}, "parameters": {"backtest": {"matched_min_invested": 0.3}}}  # fmt: skip

    within = _matched_note(R(-0.08))
    # 목표가 기준 낙폭(8.0%)보다 작아져야 생기고, 그래도 하한에 막힐 수 있어 '만들 수 있습니다' (검토: '만들어집니다' 는 단정)
    assert "만들 필요가 없었습니다" in within and "목표가 8.0%보다 작아지도록" in within and within.endswith("다시 분석하면 만들 수 있습니다.")
    floor = _matched_note(R(-0.40))
    assert "만들지 않았습니다" in floor and "더 엄격해져 역시 만들 수 없으니" in floor and "다시 분석하면" not in floor


def test_dashboard_notices_skip_the_period_note_sentence():
    """011 검토: 결론 옆 기간 메모와 같은 공지가 대시보드 3칸 중 한 칸을 또 차지해, 현금 원인 공지(weight_capacity)가 다시 잘렸다."""
    from backend.analysis.m5_backtest_report.report_blocks import dashboard_notices, period_note

    shifted = "백테스트 시작일 2023-10-10 에는 선정 가능한 종목이 1개뿐이라 시작을 2024-03-05 로 자동으로 옮김 (5개월 뒤, 선정 2종목)"
    R = {"portfolio": {"backtest_spec": {"period": {"start": "2024-03-05", "end": "2026-10-08"}}}, "request": {"horizon": {"backtest_years": 3}},
         "parameters": {"backtest": {}},
         "notices": [{"code": "too_few_with_metric", "message_ko": "기준일 9개 선정", "level": "user"},
                     {"code": "backtest_start_shifted", "message_ko": shifted, "level": "user"},
                     {"code": "fewer_holdings_at_start", "message_ko": "시작일 2종목", "level": "user"},
                     {"code": "weight_capacity", "message_ko": "현금 50% 원인", "level": "user"},
                     {"code": "must_include_not_in_universe", "message_ko": "필수 포함 X 없음", "level": "user"}]}  # fmt: skip
    assert shifted in period_note(R)
    assert dashboard_notices(R) == ["필수 포함 X 없음", "시작일 2종목", "현금 50% 원인"]


def test_explain_prompt_gives_no_rank_to_forced_name_without_metric():
    """검토: 지표 자료가 없는 필수 포함 종목에 꼴찌 순위를 줬다 (공지는 '순위를 매기지 못했다'). '–' 로."""
    from types import SimpleNamespace

    from backend.analysis.m3_selection.explain import explain
    from backend.analysis.schemas.selection import Selected

    def row(t, rank, v, forced=False):
        return Selected(ticker=t, name=t, sector="Financials", sector_code="40", rank=rank, metric_name="pe_ttm", metric_value=v, forced=forced)

    sel = SimpleNamespace(request_id="r", selected=[row("MUST", 1, float("nan"), True), row("A", 2, 8.0), row("B", 3, 6.0)],
                          summary={"metric": "pe_ttm", "direction": "asc", "as_of": "2026-06-11"})  # fmt: skip
    tagging = SimpleNamespace(tagged=[])
    seen = {}

    class Llm:
        def complete_json(self, stage, messages, validator=None):
            seen["user"] = messages[-1]["content"]
            return {"portfolio_summary_ko": "s", "per_ticker": []}

    explain(sel, tagging, {"interpretation": {"summary_ko": "s"}, "report_settings": {"explanation_level": "beginner"}}, Llm(), facts=[])
    ranks = {ln.split(" | ")[1]: ln.split(" | ")[0] for ln in seen["user"].splitlines() if " | " in ln and not ln.startswith("##")}
    assert ranks == {"MUST": "– (필수 포함)", "A": "2", "B": "1"}


def test_walkforward_checkpoints_keep_names_added_after_the_first_date():
    """검토: target_weights 를 첫 날 목표로 바꾸자, 첫 날에 없던 종목이 모든 체크포인트에서 빠지고 현금으로 보였다."""
    import numpy as np
    import pandas as pd_

    from backend.analysis.m5_backtest_report.backtest import build_checkpoints
    from backend.analysis.settings import AnalysisSettings

    idx = pd_.bdate_range("2024-01-01", periods=60)
    rb = [idx[0], idx[30]]
    sw = pd_.DataFrame({"A": 0.3, "B": 0.3, "C": 0.3, "D": 0.0}, index=idx)
    sw.loc[idx[30]:, ["A", "B", "C", "D"]] = 0.25
    px = pd_.DataFrame({c: np.linspace(100, 110, len(idx)) for c in "ABCD"}, index=idx)
    vals = pd_.Series(np.linspace(1000, 1100, len(idx)), index=idx)
    raw = {"security_weights": sw, "positions": sw * 10, "transactions": pd_.DataFrame(columns=["Date", "Security", "price", "quantity"]),
           "turnover": pd_.Series(0.0, index=idx), "index": vals / 10, "values": vals, "flows": pd_.Series(0.0, index=idx)}  # fmt: skip
    bench = {"index": vals / 10, "values": vals}
    tbd = {str(rb[0].date()): {"A": 0.3, "B": 0.3, "C": 0.3}, str(rb[1].date()): {"A": 0.25, "B": 0.25, "C": 0.25, "D": 0.25}}
    cfg = {"rf": 0.0, "baseline_idx": None, "max_stock": 1.0, "max_sector": 1.0}
    cps = build_checkpoints(raw, bench, px, tbd[str(rb[0].date())], {c: "IT" for c in "ABCD"}, rb + [idx[-1]], set(rb), idx[-1], cfg, None, None,
                            idx[0], idx[-1], AnalysisSettings(), targets_by_date=tbd)  # fmt: skip
    assert all("D" in cp["weights"]["after"] for cp in cps)
    assert cps[1]["weights"]["target"]["D"] == 0.25


def test_backtest_start_moves_to_market_cap_data_start(seeded_repo, descriptor_dir):
    """정책 결정 7 의 결과: 시가총액 자료가 없는 날에는 최소 시가총액 조건으로 모든 종목이 빠진다(팀 DB: 미국 2009·한국 2015 이전).
    재무 지표 자료와 같은 규칙으로 시작을 옮기고 알린다. 최소 시가총액이 0 이면 옮기지 않는다."""
    import json

    from backend.analysis.common.warnings import from_text
    from backend.analysis.errors import RequestInvalid
    from backend.analysis.m1_request.derive import derive
    from backend.analysis.m2_data.market_data import MarketData as MD
    from backend.analysis.settings import replace_settings
    from backend.tests.analysis.test_pipeline_e2e import REQUEST

    s = AnalysisSettings()
    s = replace_settings(s, market=replace_settings(s.market, descriptor_dir=str(descriptor_dir), mcap_data_start={"US": "2024-06-03", "KR": "2024-06-03"}))
    req = json.loads(json.dumps(REQUEST))
    req["horizon"]["backtest_years"] = 4
    req["constraints"]["min_market_cap_usd"] = 1e9
    out = derive(req, MD(seeded_repo, s), s).derived
    note = next(w for w in out.warnings if "시가총액 자료가" in w)
    assert out.backtest_start == dt.date(2024, 6, 3) and from_text("01_request", note).code == "backtest_start_clamped"
    req["constraints"]["min_market_cap_usd"] = 0
    assert derive(req, MD(seeded_repo, s), s).derived.backtest_start < dt.date(2024, 6, 3)
    req["constraints"]["min_market_cap_usd"] = 1e9
    req["horizon"]["start_date"] = "2023-12-29"
    with pytest.raises(RequestInvalid):
        derive(req, MD(seeded_repo, s), s)


def test_harness_skips_scenarios_whose_backtest_starts_before_2015(monkeypatch, tmp_path):
    """사용자 결정 (2026-11-04): 백테스트 시작이 2015년 이전인 시나리오는 건너뛴다 — 대화 전(시나리오 값)과 확정 직전(대화로 바뀐 기간) 둘 다."""
    import json

    from backend.analysis.eval import run_scenarios as RS

    f = tmp_path / "scenario_x.json"
    base = {"natural_language": {"idea": "x"}, "capital": {}, "constraints": {}, "risk": {"risk_tolerance": "moderate"}, "profile": {},
            "horizon": {"start_date": "2017-06-01", "target_years": 3}}  # fmt: skip
    f.write_text(json.dumps(base), encoding="utf-8")
    monkeypatch.setitem(RS.SCENARIOS, "scenario_x", {"file": f, "title_ko": "x"})
    calls = []

    class Api:
        def ok(self, method, path, body=None):
            calls.append((method, path))
            if path == "/requests":
                return {"request_id": "r1", "state": "ready", "summary": {"derived": {"backtest_start": "2014-05-02"}}}
            return {}

    r = RS.run_scenario("scenario_x", Api(), {}, "all", 1.0)
    assert r["status"] == "skipped" and "2014-06-01" in r["skip_reason_ko"] and calls == []  # 2017-06-01 − 3년 → 대화 전에 건너뜀
    base["horizon"]["start_date"] = "2025-06-02"
    f.write_text(json.dumps(base), encoding="utf-8")
    monkeypatch.setattr(RS, "PROFILE_KEYS", ())
    monkeypatch.setattr(RS, "answer_questions", lambda api, rid, state, policy, qa: state)
    r = RS.run_scenario("scenario_x", Api(), {}, "all", 1.0)
    assert r["status"] == "skipped" and "2014-05-02" in r["skip_reason_ko"] and ("POST", "/requests/r1/confirm") not in calls


def test_period_question_follows_data_start_rules(svc_factory):
    """검토: 최소 시가총액이 하드 조건이 된 뒤에도 대화가 실행할 수 없는 과거 기간(시가총액 자료 전)을 '아이디어대로' 보기로 냈다.
    끝이 자료 시작 전이면 묻지 않고, 시작만 그 전이면 실제 평가 기간을 보기에 적는다."""
    from backend.tests.analysis.test_dialog import _intent

    svc, _store, _llm = svc_factory([_intent([]), _intent([]), _intent([]), _intent([])])
    cap = {"constraints.min_market_cap_usd": 1e9}
    st = svc.start("미국과 한국의 반도체 기업에 2010년부터 2012년까지 투자했다면", overrides=cap)
    assert not (st.question and st.question.field == "horizon")
    st = svc.start("미국과 한국의 반도체 기업에 2014년부터 2024년까지 투자했다면", overrides=cap)
    assert st.question and st.question.field == "horizon" and "자료가 2015-07-01 부터라 실제 평가는 약 9.5년" in st.question.options[0].label_ko


def test_cap_tie_advice_says_both_caps_must_move():
    """검토: 한 섹터 3종목 × 25% = 섹터 상한 75% 처럼 두 상한이 같은 지점에서 막으면, '종목당 상한을 올리면 된다' 는 거짓 안내였다."""
    from backend.analysis.common.capacity import cap_fix_ko, cap_limits

    tie = cap_limits({"IT": 3}, 0.25, 0.75, 1.0)
    assert tie["kind"] == "stock" and tie["tie"] and "함께 올려야" in cap_fix_ko(tie)
    plain = cap_limits({"IT": 2}, 0.25, 1.0, 1.0)
    assert plain["kind"] == "stock" and not plain["tie"] and cap_fix_ko(plain).startswith("종목 수가 늘거나")


def test_double_start_clamp_leaves_one_notice_from_the_requested_start(seeded_repo, descriptor_dir):
    """검토: 재무 지표·시가총액 두 규칙이 다 시작을 옮기면 기간 메모가 앞 규칙(재무 지표)을 이유로 보였다 → 마지막 규칙 하나, 원래 요청한 날부터."""
    import json

    from backend.analysis.m1_request.derive import derive
    from backend.analysis.m2_data.market_data import MarketData as MD
    from backend.analysis.settings import replace_settings
    from backend.tests.analysis.test_pipeline_e2e import REQUEST

    s = AnalysisSettings()
    s = replace_settings(s, market=replace_settings(s.market, descriptor_dir=str(descriptor_dir), valuation_data_start={"US": "2024-03-01", "KR": "2024-03-01"},
                                                    mcap_data_start={"US": "2024-06-03", "KR": "2024-06-03"}))  # fmt: skip
    req = json.loads(json.dumps(REQUEST))
    req["strategy_preference"]["template"] = "low_per"
    req["horizon"]["backtest_years"] = 4
    req["constraints"]["min_market_cap_usd"] = 1e9
    d = derive(req, MD(seeded_repo, s), s).derived
    moved = [w for w in d.warnings if "로 옮김" in w and "자료가" in w]
    assert d.backtest_start == dt.date(2024, 6, 3) and len(moved) == 1 and moved[0].startswith("최소 시가총액") and "→ 2024-06-03" in moved[0]
    assert "2024-03-01 →" not in moved[0]  # 중간 날짜(재무 지표 규칙)가 아니라 원래 요청한 시작에서


def test_rebalance_targets_tell_static_from_walkforward():
    """016: walk-forward 정의('리밸런싱일마다 비중만 다시 계산')를 정적 추천안(낙폭 맞춤안, 역변동성 기준)에도 붙였다 → 선택안 방식을 사실로 넘긴다."""
    from backend.analysis.m5_backtest_report.report import _rebalance_targets_ko
    from backend.analysis.m5_backtest_report.report_blocks import _mcap_limitation

    assert _rebalance_targets_ko({"mode": "static"}).startswith("정적 구성") and "다시 계산하지 않음" in _rebalance_targets_ko({"mode": "static"})
    assert _rebalance_targets_ko({"mode": "walkforward"}).startswith("walk-forward 방식이라") and ": " not in _rebalance_targets_ko({"mode": "walkforward"})
    assert "최대 2년 전 기준" in _mcap_limitation({"parameters": {"market": {"mcap_fallback_max_days": 730}}})


def test_round9_report_facts_windows_news_use_and_numbers():
    """013·015·016·017 독립 검토: 근거 창 끝(그날 제외)을 끝 날로 보였고, 추천이 뉴스 뷰를 안 쓰는데 '뉴스 기반 조정이 현재 제안' 이라 썼고,
    표시값끼리 맞지 않는 차이(14.2 vs 14.0 → 0.3%p)·현금 몫 합(15.0+7.7≠22.6)·'10개로 목표 10개 및 최소 8개와 같다' 가 나왔다."""
    from backend.analysis.m5_backtest_report import report as RP
    from backend.analysis.m5_backtest_report.report_blocks import shown_window

    assert shown_window(["2026-07-02", "2026-07-16"]) == ["2026-07-02", "2026-07-15"] and shown_window(None) is None
    ne = RP._news_effect_display({"disabled": False, "bl_cagr": 0.142275, "base_cagr": 0.139717, "bl_mdd": -0.082, "base_mdd": -0.081})
    assert ne["bl_cagr_pct"] == "14.2%" and ne["base_cagr_pct"] == "14.0%" and ne["diff_cagr_pp"] == "+0.2%p" and ne["diff_mdd_pp"] == "+0.1%p"
    # 016 낙폭 맞춤안: 기준 투자 85.0002%, 맞춤 77.3502%, 최소 현금 15%
    base = {"id": "inverse_volatility", "kind": "template", "target_weights": {"A": 0.425001, "B": 0.425001}}
    m = {"id": "dd_match_inverse_volatility", "kind": "matched", "base_id": "inverse_volatility", "target_weights": {"A": 0.386751, "B": 0.386751}}
    R = {"request": {"constraints": {"min_cash_ratio": 0.15, "max_weight_per_stock": 0.1, "max_weight_per_sector": 0.85}}, "backtest": {"portfolios": [base, m]}}
    orig = RP.B.find
    try:
        RP.B.find = lambda R_, pid: next(x for x in R_["backtest"]["portfolios"] if x["id"] == pid)
        cb = RP.cash_breakdown(R, m)
    finally:
        RP.B.find = orig
    assert (cb["cash"], cb["min_cash_by_user"], cb["cash_added_by_drawdown_match"], cb["stocks"]) == ("22.6%", "15.0%", "7.6%", "77.4%")


def test_chosen_current_composition_news_use_is_stated(monkeypatch):
    """013·017: 추천 현재 구성(시가총액비중·낙폭 맞춤안)은 뉴스 뷰를 쓰지 않는데 서술이 '뉴스로 비중을 조정한 현재 제안' 이라고 했다."""
    from backend.analysis.m5_backtest_report import report as RP

    monkeypatch.setattr(RP.B, "current_composition", lambda R, c: ({"A": 1.0}, 0.0, "시가총액비중"))
    R = {"portfolio": {"forward": {"chosen_weights": {"A": 0.6, "B": 0.4}, "portfolios": [{"id": "fwd_bl_01", "title_ko": "임상·제품 파이프라인 촉매", "weights": {"A": 0.6, "B": 0.4}},
                                                                                         {"id": "fwd_bl_03", "weights": {"A": 0.3, "B": 0.7}}]}}}  # fmt: skip
    no = RP._chosen_news_use(R, "market_cap", {"id": "market_cap", "kind": "template"})
    assert no["chosen_uses_news_views"] is False and "뉴스 뷰를 쓰지 않습니다" in no["chosen_news_note_ko"]
    yes = RP._chosen_news_use(R, "bl_01", {"id": "bl_01", "kind": "black_litterman"})
    # 021: 추천 현재 구성이 어느 세트인지 밝혀 다른 세트의 뷰를 반영됐다고 쓰지 않게
    assert yes["chosen_uses_news_views"] is True and yes["recommended_forward_id"] == "fwd_bl_01"
    assert "'임상·제품 파이프라인 촉매'" in yes["chosen_news_note_ko"] and "fwd_bl" not in yes["chosen_news_note_ko"] and "views" not in yes["chosen_news_note_ko"]
    assert RP._chosen_news_use(R, "dd_match_wf_bl_news", {"id": "dd_match_wf_bl_news", "kind": "matched", "base_id": "wf_bl_news"})["chosen_uses_news_views"]


def test_round9_report_blocks_formats_and_notes():
    """016: 제외 표가 PER 97.1 을 +9,710% 로 보였고, 검증 요약 메모가 손실 시 매도 성향의 동점 규칙을 빼 Sharpe 가 더 낮은 추천과 어긋나 보였다.
    015: 뉴스 끔인데 비중 비교 메모가 없는 '뉴스 뷰' 열을 설명했고, walk-forward 날짜별 비중 변화가 '제공되지 않았다' 고 썼다."""
    from backend.analysis.m5_backtest_report import report_blocks as RB

    R = {"selection": {"metric": "pe_ttm", "as_of_now": {"as_of": "2026-03-02", "rejected_examples": [{"ticker": "ABBV", "name": "AbbVie", "reason": "x", "metric_value": 97.1}]}}}
    t = RB.excluded_table(R)
    assert next(c for c in t["columns"] if c["key"] == "metric")["format"] == "num"
    R["selection"]["metric"] = "roe_ttm"
    assert next(c for c in RB.excluded_table(R)["columns"] if c["key"] == "metric")["format"] == "pct"
    wf = {"portfolios": [{"id": "wf_market_cap", "weights_by_date": {"2023-05-11": {"PFE": 0.1462, "AMGN": 0.0846}, "2023-07-03": {"PFE": 0.1462, "AMGN": 0.0846},
                                                                     "2024-01-02": {"PFE": 0.0932, "AMGN": 0.1227}}}]}  # fmt: skip
    ch = RB.walkforward_weight_changes({"portfolio": {"walkforward": wf, "targets": {"baseline": {"id": "market_cap"}}}})
    assert ch == {"2023-07-03": ["변화 없음"], "2024-01-02": ["PFE -5.3%p", "AMGN +3.8%p"]}


def test_reused_dialog_intent_gets_current_exclusion_cleanup(monkeypatch):
    """013 다시 돌리기: 실행은 대화에서 확정된 의도를 다시 써서, 예전 의도의 '성인 산업' → 영화·인터랙티브 미디어 업종 코드가 남았다 (디즈니·알파벳 제외).
    실행 단계에서도 같은 정리를 한다 (같은 규칙이면 다시 해도 그대로)."""
    from types import SimpleNamespace

    from backend.analysis.executor import stages as ST
    from backend.analysis.m3_selection.intent import clean_exclude_rules

    intent = {"exclude_theme_rules": [{"theme": "adult_entertainment", "gics_codes": ["50202010", "50203010"], "keywords": ["adult content"]},
                                      {"theme": "gambling", "gics_codes": ["253010", "50202010"], "keywords": []}]}  # fmt: skip
    warned = []
    ctx = SimpleNamespace(intent=intent, outputs={}, warn_all=lambda stage, ws: warned.extend(ws))
    ST.st_intent(ctx)
    rules = ctx.outputs["02_intent"]["exclude_theme_rules"]
    assert rules[0]["gics_codes"] == [] and rules[1]["gics_codes"] == ["25301010"] and len(warned) == 2
    assert clean_exclude_rules(rules) == []  # 두 번째는 바꿀 것이 없다


def test_news_effect_explains_views_that_could_not_move_capped_weights():
    """018: 시작일 3종목 × 종목당 상한 14% 라 37개 날짜 모두 뉴스 뷰 BL = 기준 비중이었는데 이유가 없었다(점검은 실패로 셈).
    모든 종목이 상한에 걸린 날은 뷰가 비중을 바꿀 수 없다 — 그 날 수와 이유를 남긴다."""
    from backend.analysis.m5_backtest_report.report_blocks import news_effect

    w = {"A": 0.14, "B": 0.14, "C": 0.14}
    bl = {"id": "wf_bl_news", "kind": "black_litterman", "name_ko": "뉴스 뷰 BL", "headline": {"cagr": 0.05, "excess_cagr": -0.1, "max_drawdown": -0.1},
          "views_by_date": {"2023-07-17": [{"x": 1}], "2023-08-01": [{"x": 1}]}, "weights_by_date": {"2023-07-17": dict(w), "2023-08-01": dict(w)}}
    base = {"id": "wf_market_cap", "kind": "template", "name_ko": "시가총액비중 (walk-forward)", "headline": {"cagr": 0.05, "excess_cagr": -0.1, "max_drawdown": -0.1},
            "weights_by_date": {"2023-07-17": dict(w), "2023-08-01": dict(w)}}  # fmt: skip
    R = {"backtest": {"portfolios": [bl, base], "period": {}}, "portfolio": {"targets": {"baseline": {"id": "market_cap"}}},
         "request": {"constraints": {"max_weight_per_stock": 0.14}}, "intent": {"news_tilt": {"enabled": True}}}  # fmt: skip
    ne = news_effect(R)
    assert ne["n_dates_capped"] == 2 and "모든 종목이 종목당 상한(14%)에 걸려" in ne["capped_note_ko"]


def test_adj_factor_spike_is_relinked_but_ex_dividend_step_is_kept():
    """020: 팀 DB 가 YFINANCE 가 빈 날만 KIS(수정주가 = 종가)로 채워 2022-05-09 에 한국 종목 수정주가가 배당만큼 튀었다가 돌아왔다
    (우리금융 +34.7% → −26%, 최대낙폭 30% → 38%). 계수가 잠깐 튀었다 돌아오면 앞의 계수로 이어 붙이고, 배당락처럼 바뀐 채 유지되면 둔다."""
    import pandas as pd_

    from backend.analysis.m2_data.market_data import repair_adj_spikes

    days = pd_.to_datetime(["2022-05-04", "2022-05-06", "2022-05-09", "2022-05-10", "2022-05-11", "2022-05-12"])
    close = [58200.0, 57800.0, 58100.0, 59100.0, 59600.0, 60000.0]
    adj = [c * 0.792 for c in close]
    adj[2] = 58100.0  # KIS 로 채운 날: 수정주가 = 종가
    b = pd_.DataFrame({"ticker": "017670.KS", "date": days, "close": close, "adj_close": adj})
    # 배당락 종목: 계수가 0.95 → 1.0 으로 바뀐 채 유지 (고치면 안 됨)
    b2 = pd_.DataFrame({"ticker": "XYZ", "date": days, "close": [100.0] * 6, "adj_close": [95.0, 95.0, 100.0, 100.0, 100.0, 100.0]})
    out, rep = repair_adj_spikes(pd_.concat([b, b2], ignore_index=True))
    fixed = out[out["ticker"] == "017670.KS"]["adj_close"].tolist()
    assert abs(fixed[2] - 58100.0 * 0.792) < 1e-6 and [r[:2] for r in rep] == [("017670.KS", dt.date(2022, 5, 9))]
    assert out[out["ticker"] == "XYZ"]["adj_close"].tolist() == [95.0, 95.0, 100.0, 100.0, 100.0, 100.0]


def test_round10_report_notes_and_facts(monkeypatch):
    """018~022 독립 검토: 시작일 3종목·42% 를 날짜 없이 '그대로 투자하기 부족' 이라 했고(지금은 7종목·95%), 맞춤안 메모가 뉴스 반영 walk-forward 의
    낙폭을 '기준 구성' 낙폭이라 했고, 뉴스 끔인데 '아래 뉴스 뷰 대안' 이 있다고 했고, 상한에 묶인 BL 카드가 ±0.0%p 를 '주요 변화' 로 보였다."""
    from backend.analysis.m5_backtest_report import report as RP
    from backend.analysis.m5_backtest_report.report_blocks import _delta_ko, _delta_src_ko

    assert _delta_ko([("A", 1e-6), ("B", -1e-6)]).startswith("변화 없음") and _delta_ko([("A", 0.033), ("B", 1e-6)]) == "A +3.3%p"
    assert "하한 1.5보다 낮아" in _delta_src_ko({"delta_source": "market_implied", "delta_market": -2.68, "delta_base": 1.5})
    monkeypatch.setattr(RP.B, "current_composition", lambda R, c: ({f"T{i}": 0.135 for i in range(7)}, 0.055, "시가총액비중"))
    R = {"validation": {"recommended": {"verdict": {"status": "insufficient", "cause_ko": "선정 종목이 3개뿐이라 종목당 상한 14%로는 42%까지만 투자됩니다", "cautions_ko": []}}},
         "parameters": {"backtest": {"min_invested_for_recommendation": 0.5}}, "portfolio": {"forward": {"portfolios": []}}}  # fmt: skip
    note = RP._chosen_note(R, {"id": "market_cap", "kind": "template"}, True)
    assert note.startswith("백테스트 시작일 구성은 선정 종목이 3개뿐이라") and "지금 구성(분석 기준일)은 7종목·투자 94%" in note
    off = RP._chosen_news_use(R, "market_cap", {"id": "market_cap", "kind": "template"})
    assert "뉴스 뷰 구성은 만들지 않았습니다" in off["chosen_news_note_ko"]
    mR = {"backtest": {"portfolios": [{"id": "inverse_volatility", "kind": "template", "name_ko": "역변동성비중", "headline": {"max_drawdown": -0.111}},
                                      {"id": "wf_bl_news", "kind": "black_litterman", "name_ko": "뉴스 뷰 Black-Litterman (walk-forward)", "headline": {"max_drawdown": -0.118}}]},
          "intent": {"risk_params": {"effective_max_drawdown": 0.12}}, "request": {"risk": {"max_drawdown_tolerance": 0.12}},
          "portfolio": {"targets": {"baseline": {"id": "inverse_volatility"}}}, "parameters": {"backtest": {}}}  # fmt: skip
    mn = RP._matched_note(mR)
    assert "역변동성비중 11.1%" in mn and "11.8%" in mn and "기준 구성의 과거 최대낙폭(11.8%)" not in mn


def _budget_bound_case():
    """세 종목이 한 예산(합계 100%)을 나눠 갖고 상관이 높아 최소분산 비중이 A 1.64 · B −0.11 · C −0.53 인 경우 (026 정보기술 4종목과 같은 구조)."""
    vol = np.array([0.20, 0.30, 0.40])
    corr = np.full((3, 3), 0.9)
    np.fill_diagonal(corr, 1.0)
    cov = np.outer(vol, vol) * corr
    wb = np.full(3, 1 / 3)
    pi = 2.5 * cov @ wb
    return cov, wb, pi


def test_up_view_never_lowers_weight_when_the_budget_binds():
    """026: 정보기술 4종목이 섹터 상한 65% 를 나눠 갖는데 'AVGO 오름(약)' 날 AVGO 비중이 −11.5%p (최소분산 비중이 1 을 넘는 종목은
    예산이 묶이면 오름 뷰에 오히려 준다). 뷰가 모두 오름인 종목은 기준 비중 아래로, 모두 내림인 종목은 위로 가지 않는다."""
    cov, wb, pi = _budget_bound_case()
    mu, _ = P.black_litterman(cov, pi, np.array([[1.0, 0, 0]]), np.array([pi[0] + 0.02]), np.array([0.5]), 0.05)
    free, _ = P.optimize_utility(mu, cov, 2.5, wb, 0.9, 1.0, ["X"] * 3, 0.2, 1.0, min_weight=0.01)
    assert free[0] - wb[0] < -0.03  # 경계가 없으면 오름 뷰 종목이 준다 (원인 재현)
    up = P.view_directions([{"type": "absolute", "long": ["A"], "short": [], "direction": "up"}], ["A", "B", "C"])
    w, act = P.optimize_utility(mu, cov, 2.5, wb, 0.9, 1.0, ["X"] * 3, 0.2, 1.0, min_weight=0.01, view_dir=up)
    assert w[0] >= wb[0] - 1e-9 and "view_hold:0" in act and abs(w.sum() - 1) < 1e-6
    rel = [{"type": "relative", "long": ["A"], "short": ["C"]}, {"type": "absolute", "long": ["C"], "short": [], "direction": "up"}]
    assert P.view_directions(rel, ["A", "B", "C"]).tolist() == [1, 0, 0]  # C 는 엇갈림(상대 short + 절대 up) → 제약 없음
    dn = P.view_directions([{"type": "absolute", "long": ["B"], "short": [], "direction": "down"}], ["A", "B", "C"])
    assert dn.tolist() == [0, -1, 0]


def test_build_bl_keeps_view_direction_and_labels_the_hold(monkeypatch):
    cov, wb, pi = _budget_bound_case()
    tk = ["A", "B", "C"]
    mm = {"tickers": tk, "cov": cov.tolist(), "ann_vol": dict(zip(tk, np.sqrt(np.diag(cov)).tolist(), strict=True)),
          "implied_returns": dict(zip(tk, pi.tolist(), strict=True)), "delta": 2.5, "tau": 0.05, "shrinkage": {}, "invested_total": 1.0}  # fmt: skip
    base = {"chosen_baseline": "equal_weight", "portfolios": [{"id": "equal_weight", "weights": dict(zip(tk, wb.tolist(), strict=True)), "cash_weight": 0.0}]}
    monkeypatch.setattr(BL, "sector_lists", lambda desc, t: (["45"] * 3, ["IT"] * 3))
    v = {"type": "absolute", "long": ["A"], "short": [], "direction": "up", "strength": "weak", "confidence": 0.5, "evidence_ids": ["ev1", "ev2"], "rationale_ko": "r"}
    _quantify(v, mm, tk, PS, [], "s")
    req = {"request_id": "r", "constraints": {"max_weight_per_stock": 0.9, "max_weight_per_sector": 1.0}}
    intent = {"news_tilt": {"enabled": True, "max_tilt_per_stock": 0.2}}
    ports, _, _ = BL.build_bl(mm, base, [{"scenario_id": "s", "title_ko": "t", "narrative_ko": "n", "views": [v]}], req, intent, None, AnalysisSettings())
    assert ports[0]["delta_vs_baseline"]["A"] >= -1e-6 and "view_direction_hold:A" in ports[0]["active_constraints"]


def test_view_clip_never_reverses_direction():
    """026 검토: 절대 뷰 범위(+100%)로 자를 때 사전 기대가 이미 그보다 크면 '오름' 뷰가 사전 기대보다 낮아져 내림 뷰가 된다 → 사전 기대에 멈춘다."""
    mm, _ = _mm()
    mm = {**mm, "implied_returns": {**mm["implied_returns"], "T3": 1.2}}
    w: list[str] = []
    v = {"type": "absolute", "long": ["T3"], "short": [], "direction": "up", "strength": "strong"}
    _quantify(v, mm, mm["tickers"], PS, w, "s")
    assert v["expected_return_annual"] == pytest.approx(1.2) and any("kept at the prior" in x for x in w)


def test_market_model_window_names_the_late_listing_and_report_shows_actual_days():
    """023: 카카오뱅크(2021-08 상장) 때문에 공분산 창이 487거래일이었는데 계산 조건 표는 설정값 '756거래일' 을 보였다."""
    from backend.analysis.m5_backtest_report.report_blocks import SHRINK_KO, _lookback_ko

    idx = pd.bdate_range("2020-01-01", periods=400)
    rng = np.random.default_rng(0)
    px = pd.DataFrame({"OLD": 100 * np.exp(np.cumsum(rng.normal(0, 0.01, 400))), "NEW": 100 * np.exp(np.cumsum(rng.normal(0, 0.01, 400)))}, index=idx)
    px.loc[idx[:150], "NEW"] = np.nan
    mm = P.estimate_market_model(px, ["OLD", "NEW"], lookback_days=300, min_history_days=100, shrinkage="ledoit_wolf")
    assert mm["window"]["days"] < 300 and mm["window"]["limited_by"] == ["NEW"]
    full = P.estimate_market_model(px.ffill().bfill(), ["OLD", "NEW"], lookback_days=300, min_history_days=100, shrinkage="ledoit_wolf")
    assert "limited_by" not in full["window"]
    R = {"selection": {"table": [{"ticker": "NEW", "name": "카카오뱅크"}]}}
    txt = _lookback_ko(R, {**mm["window"], "requested_days": 300}, {"lookback_days": 300})
    assert f"{mm['window']['days']}거래일 (설정 300거래일보다 짧음: 카카오뱅크(NEW)의 상장 뒤 가격만 있음)" in txt
    assert SHRINK_KO["ledoit_wolf"] == "Ledoit-Wolf"


def test_round11_report_blocks_notes():
    """023: 수정주가 12건을 이어 붙였는데 자료 품질 표는 이상 없음처럼 보였다. 026: 섹터 상한 설명이 시작일(AMAT)만 나오고 지금 구성(WDC)은 없었다.
    024: δ 가 시장 추정 × 낙폭 배수인데 '시장 자료로 추정' 이라고만 썼다."""
    from backend.analysis.m5_backtest_report.report_blocks import _delta_src_ko, data_quality_table, infeasibility_callout

    t = data_quality_table({"data_quality": {"expected_days": 775, "usable": 12, "warnings": ["배당 보정이 하루~며칠 빠진 수정주가 12건을 앞뒤 계수로 이어 붙였습니다.", "internal note"]}})
    row = next(r for r in t["rows"] if r["k"] == "가격 보정")
    assert "12건" in row["v"] and "internal" not in row["v"]
    ov = lambda tk: {"tickers": [tk], "n_in_sector": 4, "note_ko": "정보기술 종목이 4개로 섹터 상한 65%를 나눠 갖습니다."}  # noqa: E731
    c = infeasibility_callout({"selection": {"backtest_as_of": {"as_of": "2023-10-09", "sector_overflow": ov("AMAT")}, "as_of_now": {"as_of": "2026-10-09", "sector_overflow": ov("WDC")}}})
    assert "백테스트 시작일(2023-10-09)" in c["text_ko"] and "분석 기준일(2026-10-09)" in c["text_ko"] and "WDC" in c["text_ko"]
    src = _delta_src_ko({"delta_source": "market_implied", "delta_market": 7.5749, "delta_base": 1.5, "delta_multiplier": 1.0, "delta_dd_multiplier": 0.8})
    assert src == "시장 추정치 7.575 × 낙폭 배수 0.8"
    assert _delta_src_ko({"delta_source": "market_implied", "delta_market": 2.0, "delta_base": 1.5, "delta_multiplier": 1.0, "delta_dd_multiplier": 1.0}) == "시장 자료로 추정"


def test_walkforward_changes_follow_the_chosen_plan():
    """024: 추천은 시가총액비중 walk-forward 인데 리밸런싱 변화 문장은 기준(역변동성) 구성의 숫자(EIX −1.0%p)를 썼다."""
    from backend.analysis.m5_backtest_report import report as RP
    from backend.analysis.m5_backtest_report import report_blocks as RB

    wf = {"portfolios": [{"id": "wf_inverse_volatility", "kind": "template", "weights_by_date": {"2026-07-01": {"EIX": 0.10}, "2026-10-01": {"EIX": 0.09}}},
                         {"id": "wf_market_cap", "kind": "template", "weights_by_date": {"2026-07-01": {"EIX": 0.10}, "2026-10-01": {"EIX": 0.094}}}]}  # fmt: skip
    R = {"portfolio": {"walkforward": wf, "targets": {"baseline": {"id": "inverse_volatility"}}},
         "backtest": {"portfolios": [{"id": "wf_market_cap", "kind": "template"}, {"id": "market_cap", "kind": "template"}, {"id": "dd_match_wf_market_cap", "kind": "matched", "base_id": "wf_market_cap"}]}}  # fmt: skip
    assert RB.walkforward_weight_changes(R, chosen="wf_market_cap") == {"2026-10-01": ["EIX -0.6%p"]}
    assert RB.walkforward_weight_changes(R, chosen="dd_match_wf_market_cap") == {"2026-10-01": ["EIX -0.6%p"]}
    assert RB.walkforward_weight_changes(R, chosen="market_cap") == {"2026-10-01": ["EIX -1.0%p"]}
    assert RP._wf_changes_label(R, "wf_market_cap") == "시가총액비중 — 선택안"
    assert RP._wf_changes_label(R, "market_cap") == "역변동성비중 — 기준 비중 구성, 선택안과 다름"


def test_news_effect_explains_views_on_pinned_stocks():
    """023: 금융 섹터 상한 70% + 전액 투자라 KT&G·KT 가 모든 날 15% 에 묶여, 두 종목 뷰가 그 종목 비중을 한 번도 못 바꿨는데 설명이 없었다."""
    from backend.analysis.m5_backtest_report.report_blocks import news_effect

    sw = {"2024-01-02": {"033780.KS": 0.15, "030200.KS": 0.15, "105560.KS": 0.35, "055550.KS": 0.35}}
    bw = {"2024-01-02": {"033780.KS": 0.15, "030200.KS": 0.15, "105560.KS": 0.40, "055550.KS": 0.30}}
    views = {"2024-01-02": [{"long": ["030200.KS"], "short": []}, {"long": ["033780.KS"], "short": ["030200.KS"]}, {"long": ["105560.KS"], "short": []}]}
    head = {"cagr": 0.1, "excess_cagr": 0.0, "max_drawdown": -0.1}
    R = {"backtest": {"portfolios": [{"id": "wf_bl_news", "kind": "black_litterman", "views_by_date": views, "weights_by_date": bw, "headline": head},
                                     {"id": "wf_equal_weight", "kind": "template", "weights_by_date": sw, "headline": head}], "period": {}},
         "portfolio": {"targets": {"baseline": {"id": "equal_weight"}}}, "request": {"constraints": {"max_weight_per_stock": 0.15}}, "intent": {"news_tilt": {"enabled": True}},
         "selection": {"table": [{"ticker": "033780.KS", "name": "KT&G"}, {"ticker": "030200.KS", "name": "KT"}]}}  # fmt: skip
    ne = news_effect(R)
    assert ne["n_dates_capped"] == 0
    assert ne["capped_note_ko"].startswith("뉴스 뷰 3개 중 2개는 뷰가 걸린 종목(KT·KT&G)이 종목당 상한(15%)에 묶여 있어")


def test_round11_collect_and_report_texts(monkeypatch):
    """025: 지표 없는 필수 포함 CVX·XOM 에 순위 7·8 을 줬고, 깔때기 '(필수 포함 2개 포함)' 을 서술이 빠뜨려 '지표를 계산할 수 있는 17개' 라고 썼다.
    024: 제외 테마로 뺀 유틸리티 13개 이름이 어디에도 없었다. 023: 'GOOGLE_RSS' 가 문장에 나왔다. 027: 맞춤안(주식 44.6%) 옆 머리말이 '85%를 배분합니다'."""
    from backend.analysis.m5_backtest_report import collect as C
    from backend.analysis.m5_backtest_report import report as RP

    rows = {"FANG": {"metric_value": 0.05}, "CVX": {"metric_value": float("nan")}, "XOM": {"metric_value": None}, "KMI": {"metric_value": 0.06}}
    assert C.metric_rank(rows, asc=False) == {"KMI": 1, "FANG": 2}
    ex = [{"ticker": t, "name": n, "theme_ko": "화석연료"} for t, n in [("AEE", "Ameren"), ("ATO", "Atmos"), ("CMS", "CMS"), ("CNP", "CenterPoint"), ("D", "Dominion"), ("DTE", "DTE")]]
    assert C._ex_theme_ko(ex) == " · 제외 테마(화석연료)로 뺌 6개: Ameren, Atmos, CMS, CenterPoint, Dominion 외 1개" and C._ex_theme_ko([]) == ""
    nw = RP._shown_news_window({"window": ["2023-07-17", "2023-07-31"], "by_source": {"GOOGLE_RSS": 62, "NAVER_NEWS": 3}, "by_event_type": {"buyback": 4}})
    assert nw["by_source"] == {"구글 뉴스": 62, "네이버 뉴스": 3} and nw["by_event_type"] == {"자사주 취득·처분 결정": 4} and nw["window"] == ["2023-07-17", "2023-07-30"]
    R = {"intent": {"interpretation": {"summary_ko": "투자 비율 85%를 배분합니다."}}, "request": {"constraints": {"min_cash_ratio": 0.15, "num_holdings": {"target": 10, "min": 7}}}}
    monkeypatch.setattr(RP.B, "current_composition", lambda R_, c: ({"A": 0.446}, 0.554, "낙폭 맞춤안"))
    assert RP._subtitle_ko(R, "dd_match_inverse_volatility") == "요청: 투자 비율 85%를 배분합니다."
    monkeypatch.setattr(RP.B, "current_composition", lambda R_, c: ({f"T{i}": 0.085 for i in range(10)}, 0.15, "역변동성비중"))
    assert RP._subtitle_ko(R, "inverse_volatility") == "투자 비율 85%를 배분합니다."
    assert RP._holdings_vs_request(R, "inverse_volatility") == "지금 구성은 10종목으로 목표 10개와 같고, 최소 7개보다 3개 많습니다."
