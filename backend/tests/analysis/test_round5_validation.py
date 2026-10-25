"""라운드 5: 최대낙폭은 합격 기준이 아니라 표시·순위 신호. 추천은 항상 하나, 낙폭 맞춤안은 실제 일정으로 맞춘 정식 후보."""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from backend.analysis.m5_backtest_report import matched as MX
from backend.analysis.m5_backtest_report.backtest_metrics import drawdown_series, view_diagnostics_next_window
from backend.analysis.m5_backtest_report.validate import check, dd_bucket, rank_key, verdict_for
from backend.tests.analysis.test_pipeline_e2e import e2e  # noqa: F401


def _row(pid, kind="template", sharpe=0.5, mdd=-0.10, excess=0.01):
    return {"id": pid, "kind": kind, "sharpe": sharpe, "max_drawdown": mdd, "excess_cagr": excess, "name_ko": pid}


def test_check_flag_never_fails():
    assert check("R1", "최대낙폭", "flag", False, 0.2, 0.1, "x")["status"] == "flag"
    assert check("R1", "최대낙폭", "flag", True, 0.05, 0.1, "x")["status"] == "pass"
    assert check("R4", "상한", "hard", False, 1, 1, "x")["status"] == "fail"


def test_dd_bucket_steps_of_five_points():
    assert dd_bucket(-0.08, 0.10, 0.05) == 0
    assert dd_bucket(-0.12, 0.10, 0.05) == 1
    assert dd_bucket(-0.15, 0.10, 0.05) == 1
    assert dd_bucket(-0.151, 0.10, 0.05) == 2


def test_rank_key_order_target_then_benchmark_then_drawdown_then_sharpe():
    tol, size = 0.10, 0.05
    a = _row("a", sharpe=1.5, mdd=-0.30)  # Sharpe 최고지만 목표수익 미달
    b = _row("b", sharpe=0.8, mdd=-0.14)  # 목표 충족, 낙폭 4%p 초과(구간 1)
    c = _row("c", sharpe=0.6, mdd=-0.09)  # 목표 충족, 낙폭 안
    d = _row("d", sharpe=0.9, mdd=-0.09)  # 목표 충족, 낙폭 안, Sharpe 더 높음
    st = {"a": {"R2": "warn", "R3": "pass"}, "b": {"R2": "pass", "R3": "pass"}, "c": {"R2": "pass", "R3": "pass"}, "d": {"R2": "pass", "R3": "pass"}}
    order = sorted([a, b, c, d], key=lambda r: rank_key(r, st[r["id"]], integrity_failed=False, tol=tol, bucket_size=size, cautious=False))
    assert [r["id"] for r in order] == ["d", "c", "b", "a"]
    # 무결성 실패는 맨 뒤
    order = sorted([c, d], key=lambda r: rank_key(r, st[r["id"]], integrity_failed=(r["id"] == "d"), tol=tol, bucket_size=size, cautious=False))
    assert [r["id"] for r in order] == ["c", "d"]
    # 보수 성향: 같은 등급이면 낙폭 맞춤안 우선, 아니면 Sharpe
    m = _row("dd_match_c", kind="matched", sharpe=0.4, mdd=-0.09)
    st["dd_match_c"] = {"R2": "pass", "R3": "pass"}
    assert sorted([d, m], key=lambda r: rank_key(r, st[r["id"]], integrity_failed=False, tol=tol, bucket_size=size, cautious=True))[0]["id"] == "dd_match_c"
    assert sorted([d, m], key=lambda r: rank_key(r, st[r["id"]], integrity_failed=False, tol=tol, bucket_size=size, cautious=False))[0]["id"] == "d"


def test_verdict_labels():
    v = verdict_for(mdd=0.09, tol=0.10, st={"R2": "pass", "R3": "pass"}, base_invested=0.9, min_invested=0.5, name_ko="동일비중")
    assert v["status"] == "recommended" and v["label_ko"] == "추천: 동일비중" and v["cautions_ko"] == []
    v = verdict_for(mdd=0.17, tol=0.10, st={"R2": "warn", "R3": "warn"}, base_invested=0.9, min_invested=0.5, name_ko="동일비중")
    assert v["status"] == "recommended_warn" and v["label_ko"].startswith("추천(주의: 허용 낙폭 초과 (7.0%p) · 목표수익 미달 · 비교지수 하회)")
    v = verdict_for(mdd=0.05, tol=0.10, st={"R2": "pass", "R3": "pass"}, base_invested=0.4, min_invested=0.5, name_ko="동일비중")
    assert v["status"] == "insufficient" and v["label_ko"].startswith("구성 불충분")


def test_matched_solver_synthetic_schedule():
    """합성 수익률: 실제 일정 대신 '비중 × (1−c)' 일별 혼합을 run_fn 으로 넘겨도 목표 안에 들어오고 0.5%p 단위로 올림된다."""
    rng = np.random.default_rng(0)
    r = pd.Series(rng.normal(0.0003, 0.02, 600), index=pd.bdate_range("2022-01-03", periods=600))
    r.iloc[100:160] = -0.012  # 급락 구간 → MDD 약 50%
    idx = (1 + r).cumprod()
    base_mdd = abs(float(drawdown_series(idx).min()))
    assert base_mdd > 0.3

    def run_fn(c):
        mixed = (1 + (1 - c) * r).cumprod()
        return {"index": mixed}

    target = 0.15
    seed = MX.seed_cash_ratio(idx.values, target)
    c, raw, n = MX.solve_cash_ratio(run_fn, seed, target)
    assert c is not None and 0 < c <= MX.MAX_CASH and abs(float(drawdown_series(raw["index"]).min())) <= target + 1e-9
    assert abs(c * 200 - round(c * 200)) < 1e-6  # 0.5%p 단위
    assert n <= 14
    # 이미 목표 안이면 씨앗 0
    assert MX.seed_cash_ratio(idx.values, 0.9) == 0.0
    assert MX.matched_name("동일비중", 0.5) == "낙폭 맞춤안 (주식 50% + 현금 50%, 동일비중 기준)"


def test_matched_meets_target_under_real_schedule(e2e):
    from backend.analysis.m5_backtest_report.backtest import run_raw

    ctx, _ = e2e
    bt_ctx = ctx.out("_bt_ctx")
    bt = ctx.outputs["11_backtest_results"]
    base = next(x for x in bt["portfolios"] if x["id"] == bt_ctx["baseline_id"])
    braw = run_raw(bt_ctx, base["id"], base["target_weights"])
    base_mdd = abs(float(drawdown_series(braw["index"]).min()))
    target = round(base_mdd * 0.6, 4)
    seed = MX.seed_cash_ratio(braw["index"].values, target)
    c, raw, n = MX.solve_cash_ratio(lambda cc: run_raw(bt_ctx, "dd_match_test", MX.scale_weights(base["target_weights"], cc)), seed, target)
    assert c is not None and 0 < c < 1 and abs(float(drawdown_series(raw["index"]).min())) <= target + 1e-9


def test_drawdown_delta_multiplier():
    from backend.analysis.m4_portfolio.market_model import drawdown_delta_multiplier
    from backend.analysis.settings import PortfolioSettings

    ps = PortfolioSettings()
    assert drawdown_delta_multiplier(0.20, ps) == 1.0
    assert drawdown_delta_multiplier(0.10, ps) == 1.5  # 상한
    assert drawdown_delta_multiplier(0.40, ps) == 0.75  # 하한
    assert drawdown_delta_multiplier(0.25, ps) == 0.8
    assert drawdown_delta_multiplier(0.0, ps) == 1.0


def test_view_hits_next_window_synthetic():
    dates = pd.bdate_range("2024-01-01", periods=60)
    px = pd.DataFrame({"A": np.linspace(100, 130, 60), "B": np.linspace(100, 90, 60), "C": 100 + np.zeros(60)}, index=dates)
    rb = [dates[0], dates[20], dates[40]]
    views = {str(dates[0].date()): [{"type": "relative", "long": ["A"], "short": ["B"], "expected_return_annual": 0.1, "evidence_ids": ["ev1"]},
                                    {"type": "absolute", "long": ["C"], "expected_return_annual": 0.3, "evidence_ids": []}],
             str(dates[20].date()): [{"type": "relative", "long": ["B"], "short": ["A"], "expected_return_annual": 0.1}]}
    out = view_diagnostics_next_window(views, px, rb, dates[-1], {}, {"C": 0.05})
    assert [o["hit"] for o in out] == [True, False, False]  # A>B 적중, C 는 내재 수익 이상 못 냄, 두 번째 창 B>A 빗나감
    assert out[0]["window_end"] == str(dates[20].date()) and out[2]["window_end"] == str(dates[40].date()) and out[0]["horizon"] == "next_rebalance"


def test_paper_resolves_matched_strategy():
    from backend.analysis.m6_tracking.paper import resolve_strategy

    results = {"backtest": {"portfolios": [{"id": "dd_match_inverse_volatility", "kind": "matched", "base_id": "inverse_volatility", "cash_ratio": 0.4, "name_ko": "낙폭 맞춤안 (주식 51% + 현금 49%, 역변동성비중 기준)"},
                                           {"id": "dd_match_wf_bl_news", "kind": "matched", "base_id": "wf_bl_news", "cash_ratio": 0.3, "name_ko": "낙폭 맞춤안 (주식 70% + 현금 30%, 뉴스 반영 BL 기준)"}]},
               "validation": {"results": [], "alternatives": []}}
    s = resolve_strategy("dd_match_inverse_volatility", results)
    assert s.kind == "cash_blend" and s.template == "inverse_volatility" and s.cash_ratio == 0.4 and s.name_ko.startswith("낙폭 맞춤안")
    s2 = resolve_strategy("dd_match_wf_bl_news", results)
    assert s2.kind == "cash_blend" and s2.template is None and s2.cash_ratio == 0.3
    with pytest.raises(Exception):
        resolve_strategy("dd_match_missing", results)
