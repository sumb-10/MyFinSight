"""시나리오 QA 라운드 12 (029~031): R9 의 '현금 -0%' (030), R4b 가 상한을 넘은 날과 허용 폭을 넘은 날을 따로 세기 (031),
허용 폭이 100% 이상이면 '허용 폭 안' 이라 하지 않기 (031), 리밸런싱 사이 현금이 최소 현금 아래로 내려간 날 (031),
뉴스 뷰가 비중을 바꾸지 못했으면 '뉴스 뷰 적용' 이라 하지 않기 (029), 시작일 선정 요약의 후보 수 (031).
DB·LLM 없이 함수에 작은 합성 입력을 넣는다."""

from __future__ import annotations

import datetime as dt
from types import SimpleNamespace

import numpy as np
import pandas as pd
import pytest

from backend.analysis.executor import stages
from backend.analysis.executor.context import RunContext
from backend.analysis.m4_portfolio import spec as S
from backend.analysis.m5_backtest_report import backtest_metrics as M
from backend.analysis.m5_backtest_report.backtest_engine import contribution_dates, extract_raw, rebalance_dates, run_static_portfolio, xirr
from backend.analysis.m5_backtest_report.validate import _drift_msg_ko, evaluate_checks
from backend.analysis.settings import AnalysisSettings, BacktestSettings

SECTORS = {"A": "Energy", "B": "Energy", "C": "Utilities"}


def _comp(w: pd.DataFrame, stock_cap: float, sector_cap: float, **kw) -> dict:
    idx = w.index
    return M.composition_metrics(w, pd.DataFrame(1.0, index=idx, columns=w.columns), dict(w.iloc[0]), SECTORS, stock_cap, sector_cap, 0.25,
                                 pd.Series(1.0, index=idx), **kw)  # fmt: skip


def _checks(comp: dict, target: dict[str, float], stock_cap: float, sector_cap: float, *, min_cash: float = 0.0, kind: str = "template",
            n_rb: int = 3, n_days: int = 2) -> dict[str, dict]:  # fmt: skip
    p = {"id": "x", "kind": kind, "target_weights": target,
         "metrics": {"risk": {"max_drawdown": -0.1, "ann_vol": 0.1}, "return": {"cagr": 0.1, "total_return": 0.2}, "vs_benchmark": {"excess_cagr": 0.01},
                     "composition": comp, "trading": {"n_rebalances": n_rb}},
         "series": {"index": [100.0] * n_days}, "checkpoints": [{"kind": "rebalance", "weights": {"after": target}}]}  # fmt: skip
    crit = {"max_drawdown": 0.2, "benchmark": "SPY", "target_annual_return": 0.05, "volatility_preference": "high", "vol_band": 9.99,
            "max_weight_per_stock": stock_cap, "max_weight_per_sector": sector_cap, "min_cash_ratio": min_cash}  # fmt: skip
    cks, *_ = evaluate_checks(p, crit, n_days, n_rb, lambda t: SECTORS.get(t, "Energy"), 0.25, settings=AnalysisSettings())
    return {c["rule"]: c for c in cks}


# ───────────────────────── 030: 현금 -0% ─────────────────────────
def test_r9_never_shows_negative_cash():
    """030: 최소분산 시작일 비중 합이 1.000003 이라 R9 가 '투자 100%, 현금 -0%' 였다 → 보이는 값은 0~100%."""
    target = {"A": 0.500002, "B": 0.500001}
    assert f"{1 - sum(target.values()):.0%}" == "-0%"  # 예전 식이 만들던 문구 (시험이 결함을 잡는지)
    r9 = _checks({"breaches": [], "max_weight_drift": 0.0, "max_sector_drift": 0.0}, target, 1.0, 1.0)["R9"]
    assert r9["message_ko"] == "투자 100%, 현금 0%" and r9["ok"]


# ───────────────────────── 031: 허용 폭을 넘은 날 ─────────────────────────
def _drift_weights() -> pd.DataFrame:
    """종목 상한 40%(허용 폭 50%)·섹터 상한 60%(허용 폭 75%). 셋째 날은 허용 폭을 0.05%p 안쪽(50.03%, 75.03%)으로만 넘는다."""
    idx = pd.bdate_range("2024-01-01", periods=6)
    return pd.DataFrame({"A": [0.40, 0.44, 0.5003, 0.52, 0.55, 0.40], "B": [0.30, 0.28, 0.25, 0.25, 0.24, 0.30],
                         "C": [0.30, 0.28, 0.2497, 0.23, 0.21, 0.30]}, index=idx)  # fmt: skip


def test_drift_rule_counts_days_above_tolerance_separately():
    """031: 'rule: 상한 10%를 넘은 날이 754거래일 중 747일이고 허용 폭(상한의 1.25배, 12.5%)도 넘음' 을 서술이 '12.5% 를 747일 넘었다' 로 옮겼다
    (12.5% 를 넘은 날은 90일). 허용 폭을 넘은 날을 같은 잡음 폭(0.05%p)으로 따로 세고 문구에 두 날 수를 다 적는다."""
    w = _drift_weights()
    comp = _comp(w, 0.40, 0.60)
    assert (comp["days_above_stock_cap"], comp["days_above_stock_tol"]) == (4, 2)
    assert (comp["days_above_sector_cap"], comp["days_above_sector_tol"]) == (6, 2)
    assert comp["breaches"] == ["sector_cap:Energy", "stock_cap:A"]  # 판정(넘었나)은 예전대로 잡음 폭 없이
    ck = _checks(comp, dict(w.iloc[0]), 0.40, 0.60)
    assert not ck["R4b"]["ok"] and ck["R4b"]["message_ko"] == (
        "리밸런싱 사이 최대 종목 비중 55.0%(A) — 상한 40%를 넘은 종목이 있던 날이 6거래일 중 4일, 허용 폭(상한의 1.25배, 50.0%)을 넘은 종목이 있던 날은 2일 (A). 리밸런싱 주기를 줄이면 완화됩니다")
    assert not ck["R5b"]["ok"] and ck["R5b"]["message_ko"] == (
        "리밸런싱 사이 최대 섹터 비중 79.0%(에너지) — 상한 60%를 넘은 섹터가 있던 날이 6거래일 중 6일, 허용 폭(상한의 1.25배, 75.0%)을 넘은 섹터가 있던 날은 2일 (에너지). "
        "리밸런싱 주기를 줄이면 완화됩니다")


def test_drift_rule_keeps_old_wording_for_old_results_and_handles_noise_only_breach():
    old = {"max_stock_weight": 0.55, "max_stock_weight_ticker": "A", "days_above_stock_cap": 4, "n_days": 6}  # 허용 폭 날 수가 없는 예전 결과
    assert _drift_msg_ko("stock", old, 0.40, 0.25, ["A"]) == (
        "리밸런싱 사이 최대 종목 비중 55.0%(A) — 상한 40%를 넘은 종목이 있던 날이 6거래일 중 4일이고 허용 폭(상한의 1.25배, 50.0%)도 넘음 (A). 리밸런싱 주기를 줄이면 완화됩니다")
    # 판정은 허용 폭을 넘었는데 넘은 폭이 잡음(0.05%p) 안이라 날 수가 0 이면 '0일' 이라 쓰지 않는다
    tiny = {**old, "max_stock_weight": 0.5003, "days_above_stock_cap": 1, "days_above_stock_tol": 0}
    assert _drift_msg_ko("stock", tiny, 0.40, 0.25, ["A"]) == (
        "리밸런싱 사이 최대 종목 비중 50.0%(A) — 상한 40%를 넘은 종목이 있던 날이 6거래일 중 1일, 허용 폭(상한의 1.25배, 50.0%)은 0.05%p 안쪽으로만 넘음 (A). 리밸런싱 주기를 줄이면 완화됩니다")


# ───────────────────────── 031: 허용 폭이 100% 이상 ─────────────────────────
def test_drift_rule_does_not_claim_within_tolerance_when_tolerance_is_100_percent_or_more():
    """031: 섹터 상한 90% 면 허용 폭이 112.5% 라 R5b 는 걸릴 수 없는데 '상한 90%를 넘은 날이 754거래일 중 565일 있었지만 허용 폭(상한의 1.25배) 안' 이라 써서
    서술이 '허용 폭 안이었습니다' 라고 했다. 종목 상한도 같은 규칙 (80% × 1.25 = 100%)."""
    idx = pd.bdate_range("2024-01-01", periods=4)
    w = pd.DataFrame({"A": [0.45, 0.47, 0.48, 0.45], "B": [0.45, 0.46, 0.47, 0.45]}, index=idx)
    comp = _comp(w, 0.50, 0.90)
    ck = _checks(comp, dict(w.iloc[0]), 0.50, 0.90)
    assert ck["R5b"]["ok"] and ck["R5b"]["message_ko"] == (
        "리밸런싱 사이 최대 섹터 비중 95.0%(에너지) — 상한 90%를 넘은 섹터가 있던 날이 4거래일 중 2일 (허용 폭이 100% 이상이라 이 점검으로는 거르지 않음)")
    assert ck["R4b"]["message_ko"] == "리밸런싱 사이 최대 종목 비중 48.0%(A) — 상한 50% 안에 머묾"  # 허용 폭 62.5% 는 그대로
    stock = {"max_stock_weight": 0.85, "max_stock_weight_ticker": "A", "days_above_stock_cap": 3, "n_days": 10, "days_above_stock_tol": 0}
    assert _drift_msg_ko("stock", stock, 0.80, 0.25, []) == (
        "리밸런싱 사이 최대 종목 비중 85.0%(A) — 상한 80%를 넘은 종목이 있던 날이 10거래일 중 3일 (허용 폭이 100% 이상이라 이 점검으로는 거르지 않음)")
    # 상한을 넘은 날이 없으면 예전처럼 '상한 안'
    assert _drift_msg_ko("sector", {**comp, "max_sector_weight": 0.9, "days_above_sector_cap": 0}, 0.90, 0.25, []).endswith("상한 90% 안에 머묾")


# ───────────────────────── 031: 최소 현금 아래로 내려간 날 ─────────────────────────
def _cash_dip_weights() -> pd.DataFrame:
    """최소 현금 10%: 둘째 날 9.02%, 셋째 날 9.97%(리밸런싱 반올림 같은 0.05%p 안쪽 → 세지 않음), 넷째 날 7.56%."""
    idx = pd.bdate_range("2024-01-01", periods=5)
    return pd.DataFrame({"A": [0.45, 0.46, 0.4503, 0.47, 0.45], "B": [0.45, 0.4498, 0.45, 0.4544, 0.45]}, index=idx)


def test_composition_counts_days_below_min_cash():
    w = _cash_dip_weights()
    comp = _comp(w, 0.50, 0.90, min_cash=0.10)
    assert comp["min_cash_weight"] == pytest.approx(0.0756) and comp["min_cash_date"] == "2024-01-04" and comp["days_cash_below_min"] == 2
    base = _comp(w, 0.50, 0.90)  # 최소 현금 0(기본) = 날 수를 세지 않는다
    assert base["days_cash_below_min"] is None and base["min_cash_weight"] == pytest.approx(0.0756)
    assert M.cash_floor(w.iloc[:0], 0.1) == {"min_cash_weight": None, "min_cash_date": None, "days_cash_below_min": None}


def test_compute_all_cash_share_matches_engine_cash_including_contribution_days():
    """bt 의 security_weights 는 현금까지 합친 평가액 대비 → 1 − Σ 가 엔진의 현금 ÷ 평가액과 날마다 같다 (월 적립일 포함).
    compute_all 이 그 값으로 센 최소 현금 미달 날 수·최저값을 composition 에 남기고, 리밸런싱일(목표로 다시 맞춘 날)은 세지 않는다."""
    rng = np.random.default_rng(31)
    cal = pd.bdate_range("2023-01-02", periods=260)
    px = pd.DataFrame({"A": 100 * np.cumprod(1 + rng.normal(0.002, 0.012, len(cal))), "B": 50 * np.cumprod(1 + rng.normal(0.0015, 0.012, len(cal)))}, index=cal)
    w = {"A": 0.45, "B": 0.45}  # 최소 현금 10%
    s = BacktestSettings()
    rb = rebalance_dates({"enabled": True, "count": 1, "unit": "1q"}, cal, cal[0], s)
    cd = contribution_dates(cal, cal[0], cal[-1], 25)
    b, res = run_static_portfolio("p", w, px, 10_000.0, rb, cd, 500.0, s)
    raw = extract_raw(b, res, cal[0])
    eng = (b.strategy.data["cash"] / b.strategy.data["value"]).reindex(raw["index"].index)
    mine = 1.0 - raw["security_weights"].fillna(0.0).sum(axis=1)
    assert cd and float((mine - eng).abs().max()) < 1e-9 and float((mine - eng)[cd].abs().max()) < 1e-9
    out = M.compute_all(raw, raw["index"], px, w, {"A": "Energy", "B": "Energy"}, rb, 0.0, 0.05, 0.5, 0.9, xirr, s, min_cash=0.10)
    comp = out["metrics"]["composition"]
    want = int((eng < 0.10 - 5e-4).sum())
    assert want > 0 and comp["days_cash_below_min"] == want
    assert comp["min_cash_weight"] == pytest.approx(float(eng.min()), abs=1e-6) and comp["min_cash_date"] == str(eng.idxmin().date())
    assert all(eng[d] >= 0.10 - 5e-4 for d in rb)
    assert {"days_above_stock_tol", "days_above_sector_tol", "min_cash_weight", "min_cash_date", "days_cash_below_min"} <= set(comp)
    plain = M.compute_all(raw, raw["index"], px, w, {"A": "Energy", "B": "Energy"}, rb, 0.0, 0.05, 0.5, 0.9, xirr, s)["metrics"]["composition"]
    assert plain["days_cash_below_min"] is None and plain["min_cash_weight"] == comp["min_cash_weight"]


def test_r9_says_when_cash_fell_below_min_between_rebalances():
    """031: 모두 에너지 종목이라 섹터 비중이 90% 를 넘은 565일은 현금이 최소 10% 아래(최저 7.56%)였는데 아무 데도 없었고,
    서술은 리밸런싱일 목표대로 '현금 10.0%' 라고 했다. 낙폭 맞춤안은 일부러 현금을 들고 있어 R9 대상이 아니다."""
    w = _cash_dip_weights()
    comp = _comp(w, 0.50, 0.90, min_cash=0.10)
    target = dict(w.iloc[0])
    r9 = _checks(comp, target, 0.50, 0.90, min_cash=0.10, n_days=5)["R9"]
    assert r9["message_ko"] == ("투자 90%, 현금 10% (요청한 최소 현금 10% 포함) · 리밸런싱 사이 현금은 최저 7.6%(2024-01-04)까지 내려가 "
                                "최소 현금 10%보다 낮았던 날이 5거래일 중 2일 (리밸런싱 때 다시 맞춤)")  # fmt: skip
    hold = _checks(comp, target, 0.50, 0.90, min_cash=0.10, n_rb=1, n_days=5)["R9"]["message_ko"]  # 시작일 1회뿐(매수 후 보유)
    assert hold.endswith(" · 현금은 최저 7.6%(2024-01-04)까지 내려가 최소 현금 10%보다 낮았던 날이 5거래일 중 2일 (시작 뒤 리밸런싱이 없어 다시 맞추지 않음)")
    assert "R9" not in _checks(comp, target, 0.50, 0.90, min_cash=0.10, kind="matched", n_days=5)
    assert _checks(comp, target, 0.50, 0.90, min_cash=0.0, n_days=5)["R9"]["message_ko"] == "투자 90%, 현금 10%"  # 최소 현금을 안 정했으면 말하지 않는다
    for stale in ({**comp, "days_cash_below_min": 0}, {k: v for k, v in comp.items() if k != "days_cash_below_min"}):  # 미달 없음 · 예전 결과
        assert _checks(stale, target, 0.50, 0.90, min_cash=0.10, n_days=5)["R9"]["message_ko"] == "투자 90%, 현금 10% (요청한 최소 현금 10% 포함)"


def test_backtest_metrics_receive_the_requested_min_cash(monkeypatch):
    """031: 지표 계산이 요청의 최소 현금을 받아야 '최소 현금보다 낮았던 날' 을 센다 (evaluate → compute_all)."""
    from backend.analysis.m5_backtest_report import backtest as BT

    seen: dict = {}

    class Stop(Exception):
        pass

    def fake(*a, **k):
        seen.update(k)
        raise Stop

    monkeypatch.setattr(BT.M, "compute_all", fake)
    monkeypatch.setattr(BT, "_usable_weights", lambda ctx, w: w)
    ctx = {"settings": AnalysisSettings(), "rb": [], "rf": 0.0, "target_return": 0.1, "mm": {"implied_returns": {}}, "panel": None, "sectors": {},
           "as_of": None, "end": None, "cons": {"max_weight_per_stock": 0.1, "max_weight_per_sector": 0.9, "min_cash_ratio": 0.1}}  # fmt: skip
    with pytest.raises(Stop):
        BT.evaluate(ctx, {"id": "x", "weights": {"A": 0.9}}, {"index": None}, "template", {"index": None}, None)
    assert seen["min_cash"] == pytest.approx(0.1)


# ───────────────────────── 029: '뉴스 뷰 적용' ─────────────────────────
EX_ANTE = {"exp_return": 0.05, "vol": 0.2, "sharpe": 0.25, "effective_n": 9.0}
TICKERS = [f"T{i}" for i in range(9)]
BASE = {t: 0.10 for t in TICKERS}  # 9종목 모두 종목 상한 10%, 최소 현금 10%


def _bl(k: int, shift: float, *, capped: bool = True) -> dict:
    w = {**BASE, "T0": round(0.10 + shift, 6), "T1": round(0.10 - shift, 6)}
    return {"id": f"bl_{k:02d}", "kind": "black_litterman", "name_ko": f"BL 타겟 {k}", "weights": w, "cash_weight": 0.1, "ex_ante": EX_ANTE, "sector_weights": {},
            "views_applied": [{"summary_ko": "T0 오름", "type": "absolute", "long": ["T0"], "short": [], "expected_return_annual": 0.1}],
            "delta_vs_baseline": {t: round(w[t] - BASE[t], 6) for t in w}, "active_constraints": [f"tilt_or_stock_cap:{t}" for t in TICKERS] if capped else []}  # fmt: skip


def _construct_res(ports: list[dict]) -> SimpleNamespace:
    tpl = {"id": "equal_weight", "kind": "template", "name_ko": "동일비중", "weights": dict(BASE), "cash_weight": 0.1, "ex_ante": EX_ANTE, "sector_weights": {}}
    mm = {"as_of": "2025-01-14", "lookback": {}, "tickers": TICKERS, "ann_vol": {}, "cap_weights": {}, "delta": 2.5, "delta_source": "fixed", "tau": 0.05,
          "implied_returns": {}}  # fmt: skip
    return SimpleNamespace(market_model=mm, baselines={"chosen_baseline": "equal_weight", "portfolios": [tpl]}, evidence=None, view_sets=[], fallback=not ports,
                           fallback_reason_ko=None, warnings=[], bl_portfolios=ports, applied_bl=[p for p in ports if p["views_applied"]],
                           params={"max_tilt_per_stock": 0.05} if ports else None, baseline_weights=dict(BASE), chosen_weights=dict(BASE))  # fmt: skip


def _targets_summary(monkeypatch, tmp_path, ports: list[dict]) -> str:
    monkeypatch.setattr(stages, "construct", lambda *a, **k: _construct_res(ports))
    ctx = RunContext("run_t", {"request_id": "r"}, None, SimpleNamespace(view=lambda d: SimpleNamespace(as_of=d)), None, AnalysisSettings(), tmp_path)
    spec = {"period": {"as_of": "2023-01-03", "start": "2023-01-03", "end": "2025-01-14"}, "capital": {}, "rebalance_rule": {}, "benchmark": "SPY",
            "extra_benchmarks": [], "selection": {"tickers": TICKERS}, "execution_rule": None}  # fmt: skip
    ctx.outputs.update({"07_backtest_spec": spec, "02_intent": {"news_tilt": {"max_view_confidence": 0.5}}})
    return stages.st_targets(ctx)


def test_targets_summary_says_news_views_applied_only_when_a_weight_moved(monkeypatch, tmp_path):
    """029: 9종목이 모두 상한 10% 라 다섯 세트 모두 기준 비중과 같았는데(|delta_vs_baseline| 최대 1e-6) 실행 기록이 '뉴스 반영 구성 5개 (뉴스 뷰 적용)' 이었다."""
    stuck = [_bl(k, 1e-6) for k in range(1, 6)]
    assert _targets_summary(monkeypatch, tmp_path, stuck) == "비중 규칙 1개 + 뉴스 반영 구성 5개 (뉴스 뷰는 있었지만 상한에 묶여 기준 비중과 같음)"
    assert _targets_summary(monkeypatch, tmp_path, [*stuck[:4], _bl(5, 0.02)]).endswith("뉴스 반영 구성 5개 (뉴스 뷰 적용)")  # 한 세트라도 1e-4 넘게 움직이면
    # 최적화가 상한에 걸렸다는 기록이 없으면 이유를 지어내지 않는다
    assert _targets_summary(monkeypatch, tmp_path, [_bl(1, 0.0, capped=False)]).endswith("(뉴스 뷰는 있었지만 기준 비중과 같음)")
    assert _targets_summary(monkeypatch, tmp_path, []) == "비중 규칙 1개 + 뉴스 반영 구성 0개 (기준 비중 유지)"


def test_forward_summary_applies_the_same_rule(monkeypatch, tmp_path):
    """029: 기준일(10f) 요약도 같은 규칙 — 'BL 5' 만 적어 뉴스 뷰가 현재 구성을 바꾼 것처럼 읽혔다."""
    req = {"request_id": "r", "derived": {"as_of": "2025-01-14", "initial_amount_usd": 10_000, "fx_rate": 1.0, "fx_date": "2025-01-14"}}

    def run(ports: list[dict]) -> str:
        monkeypatch.setattr(stages, "construct", lambda *a, **k: _construct_res(ports))
        ctx = RunContext("run_t", req, None, SimpleNamespace(view=lambda d: SimpleNamespace(as_of=d)), None, AnalysisSettings(), tmp_path)
        ctx.outputs.update({"05_selection": {"selected": [{"ticker": t} for t in TICKERS]}, "02_intent": {}})
        return stages.st_forward(ctx)

    assert run([_bl(k, 1e-6) for k in range(1, 6)]) == "기준일 2025-01-14 현재 구성: 비중 규칙 1개 + 뉴스 반영 구성 5개 (뉴스 뷰는 있었지만 상한에 묶여 기준 비중과 같음)"
    assert run([_bl(1, 0.02)]).endswith("(뉴스 뷰 적용)") and run([]).endswith("뉴스 반영 구성 0개 (기준 비중 유지)")


# ───────────────────────── 031: 시작일 선정 요약의 후보 수 ─────────────────────────
def test_start_date_selection_summary_counts_that_days_candidates(monkeypatch):
    """031: 시작일 재선정은 테마 판정을 다시 하지 않아(Tagging.tagged=[]) screen 이 n_candidates 를 늘 0 으로 적었다 → 그날 후보 수.
    실행 전 점검(precheck)·07 이 쓰는 (후보, 판정, 선정, 지표) 네 개짜리 반환은 그대로."""
    from backend.analysis.m2_data import metrics as Mx

    vals = {"XOM": 0.03, "CVX": 0.04, "EOG": 0.02}
    monkeypatch.setitem(Mx.METRICS, "dividend_yield_ttm", lambda view, tks: (pd.Series({t: vals[t] for t in tks}, dtype=float), []))
    cand = SimpleNamespace(candidates=[SimpleNamespace(ticker=t) for t in ["XOM", "CVX", "EOG", "OXY", "SLB"]])
    monkeypatch.setattr(S, "retrieve", lambda *a, **k: cand)
    monkeypatch.setattr(S, "mcap_warnings", lambda *a, **k: [])
    md = SimpleNamespace(view=lambda d: SimpleNamespace(as_of=d), s=SimpleNamespace(market=SimpleNamespace(mcap_fallback_max_days=730)))
    desc = SimpleNamespace(by_ticker=lambda t: {"ticker": t, "name": t, "market": "US", "gics": {}})
    cons = {"num_holdings": {"min": 2, "target": 3, "max": 5}, "max_weight_per_stock": 0.4, "max_weight_per_sector": 1.0, "min_cash_ratio": 0.0,
            "must_include_tickers": []}  # fmt: skip
    c, tag, sel, facts = S.selectable_at(md, dt.date(2023, 7, 17), desc, {"screen": {"metric": "dividend_yield_ttm", "direction": "desc"}}, cons,
                                         ["XOM", "CVX", "EOG", "KMI"], "r")  # fmt: skip
    assert c is cand and tag.tagged == [] and tag.passed_tickers == ["CVX", "EOG", "XOM"] and facts == []
    assert sel.summary["n_candidates"] == 5 and sel.summary["n_tagged"] == 3 and [s.ticker for s in sel.selected] == ["CVX", "XOM", "EOG"]
    assert sel.model_dump(mode="json")["summary"]["n_candidates"] == 5  # 07_selection_bt.json 에 그대로 남는다
