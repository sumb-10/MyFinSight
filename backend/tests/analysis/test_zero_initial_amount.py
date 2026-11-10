"""초기 투자금 0원 + 매월 적립 (이슈 #14 의 3번): 첫 적립일에 처음 매수하고 수익률은 그날부터.

검증(0원이면 적립 필수), 저장 스키마, /meta/options 규칙, 파이프라인 01~14 (지수·금액·리포트 문장·예상 매수 주문), 모의투자.
"""

from __future__ import annotations

import copy
import json
import math
import re

import pytest
from fastapi.testclient import TestClient

from backend.analysis.api.app import API_PREFIX as P
from backend.analysis.api.app import create_analysis_app
from backend.analysis.common.llm import StubLlm
from backend.analysis.errors import RequestInvalid
from backend.analysis.executor.context import RunContext
from backend.analysis.executor.runner import run
from backend.analysis.m1_request.validate import hard_errors
from backend.analysis.m2_data.market_data import MarketData
from backend.analysis.m5_backtest_report.execution_orders import estimate_orders
from backend.analysis.m5_backtest_report.report_blocks import FIRST_CONTRIBUTION_KO, basis_amount
from backend.analysis.settings import AnalysisSettings, replace_settings
from backend.tests.analysis.test_dialog import PROFILE_FIELDS
from backend.tests.analysis.test_paper import AS_OF, END, RID, _svc, paper_run  # noqa: F401 (paper_run 은 픽스처)
from backend.tests.analysis.test_pipeline_e2e import INTENT_STUB, REQUEST

ZERO = copy.deepcopy(REQUEST)
ZERO["request_id"] = "req_20251231_120000_zero"
ZERO["capital"].update(initial_amount=0, monthly_contribution=500_000)
ZERO_INTENT = {**INTENT_STUB, "request_id": ZERO["request_id"]}


def _with_capital(**cap):
    r = copy.deepcopy(REQUEST)
    r["capital"].update(cap)
    return r


# ───────────────────────── 검증 ─────────────────────────
def test_zero_needs_monthly_contribution():
    assert hard_errors(_with_capital(initial_amount=0, monthly_contribution=500_000)) == []
    errs = hard_errors(_with_capital(initial_amount=0, monthly_contribution=0))
    assert [(e.field, e.message_ko) for e in errs] == [("capital.monthly_contribution", "월 적립금: 처음 투자금이 0원이면 매월 추가 투자금이 있어야 합니다")]
    assert [e.field for e in hard_errors(_with_capital(initial_amount=-1))] == ["capital.initial_amount"]
    assert hard_errors(_with_capital(initial_amount=1, monthly_contribution=0)) == []  # 원금이 있으면 적립은 없어도 된다


def test_basis_amount():
    assert basis_amount(1000.0, 1_300_000, 50.0, 65_000) == (1000.0, 1_300_000, None)
    assert basis_amount(0.0, 0, 50.0, 65_000) == (50.0, 65_000, FIRST_CONTRIBUTION_KO)
    assert basis_amount(0.0, None, 50.0, None) == (50.0, None, FIRST_CONTRIBUTION_KO)


def test_api_profile_and_options(tmp_path):
    def no_db():
        raise AssertionError("DB 를 읽지 않는다")

    c = TestClient(create_analysis_app(no_db, store_dir=tmp_path / "store", settings=AnalysisSettings(), llm=lambda: StubLlm()))
    assert c.get(f"{P}/meta/options").json()["proposed_rules"] == {"allow_zero_initial_amount": True}
    zero = copy.deepcopy(PROFILE_FIELDS)
    zero["capital"].update(initial_amount=0, monthly_contribution=500_000)
    r = c.put(f"{P}/profile", json=zero)
    assert r.status_code == 200 and r.json()["profile"]["capital"]["initial_amount"] == 0  # 저장 스키마(profile.schema.json)도 0 을 받는다
    zero["capital"]["monthly_contribution"] = 0
    r = c.put(f"{P}/profile", json=zero)
    assert r.status_code == 422 and r.json()["error"]["code"] == "PROFILE_INVALID"
    assert "capital.monthly_contribution" in r.json()["error"]["fields"]


# ───────────────────────── 파이프라인 ─────────────────────────
@pytest.fixture(scope="module")
def zero_run(seeded_repo, descriptor_dir, tmp_path_factory):
    s = AnalysisSettings()
    s = replace_settings(s, portfolio=replace_settings(s.portfolio, lookback_days=252, min_history_days_for_model=120),
                         market=replace_settings(s.market, valuation_max_staleness_days=10, descriptor_dir=str(descriptor_dir)))  # fmt: skip
    run_dir = tmp_path_factory.mktemp("run_zero")
    ctx = RunContext(run_id="run_zero_test", request=copy.deepcopy(ZERO), repo=seeded_repo, md=MarketData(seeded_repo, s),
                     llm=StubLlm({"02_intent": ZERO_INTENT}, run_dir=run_dir), settings=s, run_dir=run_dir)  # fmt: skip
    return ctx, run(ctx)


def test_zero_run_completes(zero_run):
    ctx, outcome = zero_run
    assert outcome.status in ("success", "partial"), outcome.to_dict()
    assert all(s.status in ("SUCCESS", "PARTIAL") for s in outcome.steps), [(s.name, s.status) for s in outcome.steps]


def test_index_starts_at_first_contribution(zero_run):
    """첫 적립일까지 평가액 0 → 지수 100 그대로, 그 뒤 시간가중 수익률. 비교지수도 같은 적립이라 같은 날 출발한다."""
    ctx, _ = zero_run
    bt = ctx.outputs["11_backtest_results"]
    dates = bt["series_dates"]
    for p in [*bt["portfolios"], *bt["benchmarks"]]:
        first = p["contribution_ledger"][0]
        assert first["value_before_usd"] == 0.0, p["id"]
        k = dates.index(first["date"])
        idx, val = p["series"]["index"], p["series"]["value_usd"]
        assert all(v is not None and math.isfinite(v) for v in idx), p["id"]
        assert idx[: k + 1] == [100.0] * (k + 1) and val[k - 1] == 0.0 and val[k] > 0, p["id"]
        assert idx[-1] != 100.0, p["id"]
        m = p["money"]
        assert m["initial_usd"] == 0.0 and m["net_invested_usd"] == m["contributions_usd"] > 0 and math.isfinite(m["irr_annual"]), p["id"]
        assert all(v is not None for v in (p["metrics"]["return"]["cagr"], p["metrics"]["risk"]["max_drawdown"])), p["id"]


def test_report_amounts_use_first_contribution(zero_run):
    ctx, _ = zero_run
    rep = ctx.outputs["14_report"]
    monthly = ctx.request["derived"]["monthly_contribution_usd"]
    a = rep["summary"]["allocation"]
    assert a["amount_basis_ko"] == FIRST_CONTRIBUTION_KO and a["initial_amount_usd"] == pytest.approx(monthly)
    assert sum(x["usd"] for x in a["items"]) + monthly * a["cash_weight"] == pytest.approx(monthly, abs=0.05)
    assert sum(x["krw"] for x in a["items"]) == pytest.approx(500_000 * (1 - a["cash_weight"]), abs=10)  # 원화는 원화 적립금 × 비중
    txt = json.dumps(rep, ensure_ascii=False)
    assert "첫 적립일에 처음 매수" in txt and "첫 적립금" in txt
    # 0 USD 는 가정 문단의 「초기 투자금 0 USD (첫 적립일에 …)」 하나뿐 — 배분 금액 표가 0 × 비중이 되지 않는다
    assert [m.start() for m in re.finditer(r"투자금 0 USD", txt)] == [m.start() for m in re.finditer(r"투자금 0 USD \(첫 적립일에 처음 매수", txt)]
    tables = [b for s in rep["sections"] for b in s["blocks"] if b["type"] == "table" and str(b.get("title_ko", "")).startswith("배분 금액")]
    assert len(tables) == 2 and all("첫 적립금" in b["title_ko"] for b in tables)
    assert all(row["usd"] > 0 for b in tables for row in b["rows"])
    orders = estimate_orders(rep, {x["ticker"]: 100.0 for x in a["items"]})
    assert orders["capital"]["usd"] == pytest.approx(monthly, abs=0.01) and orders["note_ko"].startswith("처음 투자금이 0원이라 첫 적립금")
    assert 0 < orders["totals"]["invested_usd"] <= monthly


# ───────────────────────── 모의투자 ─────────────────────────
def test_paper_zero_start(paper_run):  # noqa: F811
    svc = _svc(paper_run, END)
    with pytest.raises(RequestInvalid):
        svc.create(RID, start_date=str(AS_OF), strategy_id="equal_weight", initial_amount=0, currency="USD", monthly_contribution=0)
    pv = svc.preview(RID, start_date=str(AS_OF), strategy_id="equal_weight", initial_amount=0, currency="USD", monthly_contribution=1_000)
    assert pv["allocation_basis_ko"] == "첫 적립금" and sum(a["usd"] for a in pv["allocation"]) + 1_000 * pv["cash_weight"] == pytest.approx(1_000, abs=0.05)
    d = svc.create(RID, start_date=str(AS_OF), strategy_id="equal_weight", initial_amount=0, currency="USD", monthly_contribution=1_000)
    pid = d["portfolio"]["paper_id"]
    first = d["snapshots"][0]
    assert first["value_usd"] == 0.0 and first["return_since_start"] == 0.0 and first["unit_price"] == 1.0
    assert d["portfolio"]["benchmark_start_px"] is None and d["rebalances"][0]["trades"] == [] and "0원" in d["rebalances"][0]["note_ko"]
    d2 = svc.refresh(pid)
    snaps = d2["snapshots"]
    k = next(i for i, s in enumerate(snaps) if s["contribution_usd"] > 0)
    assert all(s["value_usd"] == 0.0 and s["return_since_start"] == 0.0 and s["benchmark_return_since_start"] == 0.0 for s in snaps[:k])
    on = snaps[k]
    assert on["value_usd"] == pytest.approx(1_000, abs=2) and abs(on["return_since_start"]) < 0.002 and on["benchmark_return_since_start"] == 0.0
    assert d2["portfolio"]["benchmark_start_px"] is not None  # 첫 적립일 가격
    assert any(t["side"] == "buy" for r in d2["rebalances"] if r["kind"] == "contribution" for t in r["trades"])
    summ = d2["summary"]
    assert summ["contributions_total_usd"] == pytest.approx(2_000, abs=0.01)
    assert summ["gain_usd"] == pytest.approx(snaps[-1]["value_usd"] - 2_000, abs=0.05)
    assert summ["excess_return"] == pytest.approx(summ["return_since_start"] - summ["benchmark_return_since_start"], abs=1e-6)
