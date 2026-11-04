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
