"""End-to-end invariants of the mock-up pipeline (stub mode).

  ~/.venvs/myfinsight/bin/python -m pytest tests -q            # uses existing output/ (fast)
  MYFINSIGHT_TEST_RUN=1 ... pytest tests -q                    # re-runs stages 1-15 in stub mode first (slow)
"""
import json, os, subprocess, sys
from pathlib import Path
import numpy as np
import pytest

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "output"
PY = sys.executable


def load(name):
    p = OUT / name
    if not p.exists():
        pytest.skip(f"{name} missing: run scripts/run_pipeline.py --stop-at 15 first")
    return json.loads(p.read_text(encoding="utf-8"))


@pytest.fixture(scope="session", autouse=True)
def maybe_run_pipeline():
    if os.environ.get("MYFINSIGHT_TEST_RUN") == "1":
        env = {**os.environ, "MYFINSIGHT_LLM": "stub"}
        subprocess.run([PY, str(ROOT / "scripts" / "run_pipeline.py"), "--stop-at", "15"], check=True, env=env, cwd=ROOT)


def test_selftests():
    for script in ["portfolio.py", "backtest_engine.py", "backtest_metrics.py"]:
        subprocess.run([PY, str(ROOT / "scripts" / script)], check=True, cwd=ROOT / "scripts")


def test_selection_constraints():
    sel, req = load("05_selection.json"), load("01_request.json")
    nh = req["constraints"]["num_holdings"]
    assert len(sel["selected"]) <= nh["max"]
    if sel.get("infeasibility"):
        assert sel["infeasibility"]["max_feasible_n"] < nh["target"]
        assert len(sel["selected"]) <= sel["infeasibility"]["max_feasible_n"]


def test_candidates_no_weak_keyword_hits():
    c = load("03_candidates.json")
    for x in c["candidates"]:
        if x["matched_by"] == ["keyword_match"]:
            assert len(x["matched_keywords"]) >= 2, x["ticker"]


def test_target_portfolios_constraints():
    t = load("10_target_portfolios.json")
    wb, tilt = t["baseline"]["weights"], t["parameters"]["max_tilt_per_stock"]
    for p in t["portfolios"] + t["templates"]:
        w = p["weights"]
        assert abs(sum(w.values()) + p["cash_weight"] - 1) < 1e-4, p["id"]
        assert max(w.values()) <= t["parameters"]["max_weight_per_stock"] + 1e-6, p["id"]
        assert min(w.values()) >= 0.01 - 1e-9, (p["id"], "MIN_WEIGHT floor")
        assert max(p["sector_weights"].values()) <= t["parameters"]["max_weight_per_sector"] + 1e-6, p["id"]
        if p["kind"] == "black_litterman":
            assert max(abs(w[k] - wb[k]) for k in w) <= tilt + 1e-6, p["id"]


def test_backtest_invariants():
    r = load("11_backtest_results.json")
    n = len(r["series_dates"])
    assert n == r["period"]["trading_days"]
    for p in [*r["benchmarks"], *r["portfolios"]]:
        assert all(len(v) == n for v in p["series"].values()), p["id"]
        assert p["metrics"]["risk"]["max_drawdown"] <= 0
        cps = p["checkpoints"]
        assert sum(cp["kind"] == "closing" for cp in cps) == 1 and cps[-1]["kind"] == "closing", p["id"]
        assert all(cp["date"] != r["period"]["end"] or cp["kind"] == "closing" for cp in cps), "no rebalance on the last day"
        for cp in cps:
            if cp["kind"] == "rebalance":
                assert max(abs(cp["weights"]["after"][t] - cp["weights"]["target"][t]) for t in cp["weights"]["target"]) < 2e-3, (p["id"], cp["date"])
        chain = np.prod([1 + cp["since_last"]["return"] for cp in cps if cp["since_last"]]) - 1
        assert abs(chain - p["metrics"]["return"]["total_return"]) < 1e-4, p["id"]
        last = cps[-1]["to_date"]; m = p["metrics"]
        assert abs(last["cagr"] - m["return"]["cagr"]) < 1e-9 and abs(last["max_drawdown"] - m["risk"]["max_drawdown"]) < 1e-9, p["id"]
        assert abs(sum(l["amount_usd"] for l in p["contribution_ledger"]) - p["money"]["contributions_usd"]) < 0.02, p["id"]
        assert abs((m["return"]["cagr"] - r["engine"]["risk_free_rate"]) / m["risk"]["ann_vol"] - m["risk_adjusted"]["sharpe"]) < 1e-5, p["id"]


def test_validation_and_alternative():
    v, r = load("12_validation.json"), load("11_backtest_results.json")
    ids = {p["id"] for p in r["portfolios"]}
    assert {x["id"] for x in v["results"]} == ids
    for a in v["alternatives"]:
        assert 0 < a["cash_ratio"] < 1
        assert abs(a["headline"]["max_drawdown"]) <= v["criteria"]["max_drawdown"] + 0.01, "cash blend should meet the drawdown tolerance (±1%p)"
        assert abs(sum(a["target_weights"].values()) - (1 - a["cash_ratio"])) < 1e-3


def test_results_bundle_and_report():
    R, doc = load("13_results.json"), load("14_report.json")
    assert set(R["money_krw"]["by_portfolio"]) >= {p["id"] for p in R["backtest"]["portfolios"]}
    n = len(doc["datasets"]["dates"])
    for sid, s in doc["datasets"]["series"].items():
        for k in ("index", "value_usd", "drawdown"):
            if k in s: assert len(s[k]) == n, sid
    assert len(doc["sections"]) == 8 and len(doc["kpis"]) == 6
    types = {b["type"] for s in doc["sections"] for b in s["blocks"]}
    assert {"paragraphs", "kpis", "table", "donut", "line", "area", "bar", "funnel", "callout", "cards", "checkpoints", "glossary"} <= types
    chosen = doc["header"]["chosen_portfolio_id"]
    p = next(x for x in R["backtest"]["portfolios"] if x["id"] == chosen)
    kpi = {k["id"]: k["value"] for k in doc["kpis"]}
    assert kpi["cagr"] == p["headline"]["cagr"] and kpi["final_value"] == p["money"]["final_value_usd"]
    assert not any("banned word" in w for w in doc["warnings"])
