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
    assert rel["expected_return_annual"] == pytest.approx(0.10 * sig, abs=1e-6)  # max(차이, 0) + k·σ: long 이 이긴다는 뜻이 유지된다
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
