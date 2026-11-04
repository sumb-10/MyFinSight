"""반올림된 비중의 최적화 실패와 뉴스 적용 횟수 오집계 회귀 검사."""

from __future__ import annotations

import datetime as dt
from importlib import import_module
from types import SimpleNamespace

import numpy as np
import pandas as pd
import pytest

from backend.analysis.common.llm import StubLlm
from backend.analysis.common.store import JsonStore
from backend.analysis.executor import stages
from backend.analysis.executor.context import RunContext
from backend.analysis.m4_portfolio import black_litterman as BL
from backend.analysis.m4_portfolio import math as P
from backend.analysis.m4_portfolio.views import generate_views
from backend.analysis.settings import AnalysisSettings

C = import_module("backend.analysis.m4_portfolio.construct")


def portfolio_inputs(monkeypatch, n_it):
    tickers = [f"T{i}" for i in range(10)]
    sectors = ["45"] * n_it + (["60", "60", "50", "25"] if n_it == 6 else ["60", "60", "25"])
    monkeypatch.setattr(BL, "sector_lists", lambda desc, tk: (sectors, sectors))
    wb = np.array([round(0.4 / n_it, 6)] * n_it + [0.15] * (10 - n_it))
    total = 1.0 if n_it == 6 else 0.849999
    mm = {
        "tickers": tickers, "cov": (np.eye(10) * 0.1).tolist(),
        "implied_returns": dict(zip(tickers, 0.15 * wb, strict=True)),
        "delta": 1.5, "tau": 0.05, "shrinkage": {}, "invested_total": total,
    }
    base = {"chosen_baseline": "equal_weight", "portfolios": [{
        "id": "equal_weight", "weights": dict(zip(tickers, wb, strict=True)),
        "cash_weight": round(1 - total, 6),
    }]}
    sets = [{"scenario_id": "news", "title_ko": "뉴스", "narrative_ko": "뉴스 의견", "views": [{
        "type": "relative", "long": [tickers[0]], "short": [tickers[1]],
        "expected_return_annual": 0.2, "confidence": 0.6, "evidence_ids": ["ev123"],
    }]}]
    req = {"request_id": "req_test", "constraints": {
        "max_weight_per_stock": 0.15, "max_weight_per_sector": 0.4,
    }}
    intent = {"news_tilt": {"enabled": True, "max_tilt_per_stock": 0.05}}
    return mm, base, sets, req, intent, None, AnalysisSettings()


@pytest.mark.parametrize("n_it", [6, 7])
@pytest.mark.parametrize("legacy_model", [False, True])
def test_rounded_baseline_does_not_make_bl_infeasible(monkeypatch, n_it, legacy_model):
    args = portfolio_inputs(monkeypatch, n_it)
    intended_total = args[0]["invested_total"]
    if legacy_model:
        args[0].pop("invested_total")
    ports, _, _ = BL.build_bl(*args)
    p = ports[0]
    assert not any(a.startswith("optimizer_failed") for a in p["active_constraints"])
    assert abs(sum(p["weights"].values()) - intended_total) < 5e-6
    assert sum(list(p["weights"].values())[:n_it]) <= 0.4 + 5e-6
    assert max(p["weights"].values()) <= 0.15 + 1e-6
    assert max(abs(d) for d in p["delta_vs_baseline"].values()) > 0.01
    assert p["views_applied"]


def test_optimizer_failure_is_counted_as_fallback(monkeypatch, tmp_path):
    mm, base, sets, req, intent, desc, settings = portfolio_inputs(monkeypatch, 6)
    monkeypatch.setattr(P, "minimize", lambda *a, **kw: SimpleNamespace(success=False, message="forced failure"))
    monkeypatch.setattr(C, "build_market_model", lambda *a, **kw: (mm, base))
    monkeypatch.setattr(C, "generate_views", lambda *a, **kw: (sets, []))
    date = dt.date(2024, 1, 2)
    evidence = SimpleNamespace(enough=True, summary=lambda: {}, to_dict=lambda: {})
    view = SimpleNamespace(as_of=date, news_window=lambda tk: evidence,
                           trading_days=lambda *a, **kw: pd.DatetimeIndex([date]))
    result = C.construct(view, mm["tickers"], req, intent, settings, None, desc, mode="rebalance")
    assert result.fallback and "최적화" in result.fallback_reason_ko
    assert result.bl_portfolios[0]["views_applied"] == []
    monkeypatch.setattr(stages, "construct", lambda *a, **kw: result)
    md = SimpleNamespace(assets={}, view=lambda d: view, market_of=lambda t: "US")
    ctx = RunContext("run_test", req, None, md, None, settings, tmp_path)
    ctx.outputs = {"02_intent": intent, "07_backtest_spec": {
        "period": {"as_of": str(date), "end": str(date)},
        "selection": {"tickers": mm["tickers"]}, "benchmark": "SPY",
        "rebalance_rule": {"enabled": True, "count": 1, "unit": "1q"},
    }}
    mm.update(delta_source="fixed", lookback={})
    summary = stages.st_walkforward(ctx)
    out = ctx.out("10w_target_paths")
    # 뷰가 반영된 날이 하나도 없으면 기준 비중과 똑같은 'wf_bl_news' 를 후보로 두지 않고 이유를 남긴다 (2026-11 QA F15·002)
    assert not any(p["kind"] == "black_litterman" for p in out["portfolios"])
    assert out["bl_omitted"]["reason"] == "no_views" and "뉴스 뷰 적용 0회" in summary and "뉴스 반영 구성 없음" in summary
    assert any(w.code == "optimizer_failed_no_tilt" for w in ctx.warnings)
    paper = import_module("backend.analysis.m6_tracking.paper")
    service = paper.PaperService(JsonStore(tmp_path), None, md, None, settings)
    monkeypatch.setattr(service, "_desc", lambda *a: desc)
    monkeypatch.setattr(paper, "construct", lambda *a, **kw: result)
    strategy = paper.Strategy("wf_bl_news", "black_litterman", None, 0.0, "뉴스 구성")
    _, _, info = service._construct_weights(strategy, view, mm["tickers"], req, intent, stage_tag="test")
    assert info["fallback"] and info["views"] == []


@pytest.mark.parametrize("raw_id, ambiguous, expected", [
    ("123", False, ["ev123"]), (123, False, ["ev123"]),
    ("ev123", True, ["ev123"]), ("123", True, []), ("999", False, []),
])
def test_missing_evidence_prefix_requires_unique_known_id(raw_id, ambiguous, expected):
    date = dt.date(2024, 1, 2)
    view = SimpleNamespace(as_of=date, adj_close=lambda *a, **kw: pd.DataFrame({"A": [100, 110]}))
    evidence = SimpleNamespace(
        start=date - dt.timedelta(days=30), end=date, dc_start=None, disclosures=[],
        by_ticker={"A": ["ev123"]}, has_evidence=lambda t: True,
        ids={"ev123", "dc123"} if ambiguous else {"ev123"},
        records=[{"ticker": "A", "evidence_id": "ev123", "published_at": "2024-01-01", "title": "news"}],
    )
    mm = {key: {"A": 0.1} for key in ["ann_vol", "cap_weights", "implied_returns"]}
    intent = {"news_tilt": {"max_view_confidence": 0.5}, "interpretation": {"themes": [], "summary_ko": "테마"}}
    answer = {"sets": [{"scenario_id": "s", "views": [{
        "type": "absolute", "long": ["A"], "short": [],
        "expected_return_annual": 0.1, "confidence": 0.4, "evidence_ids": [raw_id],
    }]}]}
    sets, _ = generate_views(view, ["A"], mm, {"A": 1.0}, intent,
                             SimpleNamespace(by_ticker=lambda t: {}), AnalysisSettings(),
                             StubLlm({"09_views_news": answer}), evidence, n_sets=1, views_per_set=4)
    assert (sets[0]["views"][0]["evidence_ids"] if sets else []) == expected
