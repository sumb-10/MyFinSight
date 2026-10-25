"""B7 Module6 모의투자: 미리보기=적용 비중, 시작일 규칙, 일별 갱신(적립·리밸런싱·중복 없음), 지연, 중지·재개(건너뛴 리밸런싱), API."""

from __future__ import annotations

import datetime as dt
import os

import pytest
from fastapi.testclient import TestClient

from backend.analysis.api.app import API_PREFIX, create_analysis_app
from backend.analysis.common.llm import StubLlm
from backend.analysis.common.store import JsonStore, RequestStore
from backend.analysis.errors import Conflict, RequestInvalid
from backend.analysis.executor import worker
from backend.analysis.executor.queue import Queue
from backend.analysis.m2_data.market_data import MarketData
from backend.analysis.m6_tracking.paper import PaperService, rebalance_due_dates, resolve_strategy, strategy_options, trade_to_target
from backend.analysis.schemas.dialog import AnalysisRequestDoc
from backend.analysis.settings import AnalysisSettings, replace_settings
from backend.db import open_repository
from backend.tests.analysis.test_pipeline_e2e import INTENT_STUB, REQUEST

AS_OF = dt.date(2025, 10, 31)  # 리포트 기준일 (두 시장 거래일). 합성 자료는 2025-12-31 까지 → 두 달치 모의투자 갱신이 가능
MID = dt.date(2025, 11, 14)
END = dt.date(2025, 12, 31)
RID = "run_paper1"


@pytest.fixture(scope="module")
def paper_run(descriptor_dir, tmp_path_factory):
    """합성 DB 에 리포트 하나를 만든다 (기준일 2025-10-31, 매월 리밸런싱, 월 적립 25일)."""
    from backend.tests.analysis.conftest import seed_repository

    tmp = tmp_path_factory.mktemp("paper")
    repo = open_repository("sqlite://", clock=lambda: dt.datetime(2026, 1, 5, tzinfo=dt.UTC))
    seed_repository(repo)
    s = AnalysisSettings()
    s = replace_settings(s, portfolio=replace_settings(s.portfolio, lookback_days=252, min_history_days_for_model=120),
                         market=replace_settings(s.market, valuation_max_staleness_days=10, descriptor_dir=str(descriptor_dir)))  # fmt: skip
    store = JsonStore(tmp / "store")
    req = {**REQUEST, "request_id": "req_20251031_120000_pap1", "horizon": {**REQUEST["horizon"], "start_date": str(AS_OF)},
           "constraints": {**REQUEST["constraints"], "rebalance": {"count": 1, "unit": "1m"}}}  # fmt: skip
    os.environ["ANALYSIS_OUTPUT_DIR"] = str(tmp / "out")
    try:
        doc = AnalysisRequestDoc(request_id=req["request_id"], created_at="2025-10-31T12:00:00+09:00", profile_version=1, idea=req["natural_language"]["idea"],
                                 status="confirmed", dialog_state="confirmed", effective_request=req, intent={**INTENT_STUB, "request_id": req["request_id"], "questions": []},
                                 confirmed_at="2025-10-31T12:05:00+09:00")  # fmt: skip
        RequestStore(store).save(doc)
        Queue(store).enqueue(RID, doc.request_id)
        status = worker.run_once(repo=repo, store=store, settings=s, llm=StubLlm(run_dir=tmp / "out" / RID))
    finally:
        os.environ.pop("ANALYSIS_OUTPUT_DIR", None)
    assert status in ("success", "partial"), Queue(store).get(RID)
    results = repo.get_run_artifact(RID)["results"]
    assert results["request"]["derived"]["as_of"] == str(AS_OF)
    return repo, store, s, results


def _svc(paper_run, ceiling: dt.date) -> PaperService:
    repo, store, s, _ = paper_run
    return PaperService(store, repo, MarketData(repo, s, ceiling=ceiling), StubLlm(), s)


# ───────────────────────── 순수 함수 ─────────────────────────
def test_resolve_strategy_and_options(paper_run):
    results = paper_run[3]
    assert resolve_strategy("wf_inverse_volatility", results).kind == "template"
    assert resolve_strategy("wf_bl_news", results).kind == "black_litterman"
    assert resolve_strategy("bl_01", results).kind == "black_litterman"
    with pytest.raises(RequestInvalid):
        resolve_strategy("nope", results)
    opts = strategy_options(results)
    ids = [o["id"] for o in opts]
    assert {"equal_weight", "wf_bl_news"} <= set(ids) and sum(o["chosen"] for o in opts) == 1 and opts[0]["chosen"]


def test_trade_to_target_fees_keep_cash_non_negative():
    prices = {"A": 10.0, "B": 20.0}
    h, cash, trades, fees, turnover = trade_to_target({}, 1000.0, prices, {"A": 0.5, "B": 0.5}, 0.0, commission_bps=5)
    assert cash >= 0 and fees > 0 and len(trades) == 2 and all(t["side"] == "buy" for t in trades)
    assert h["A"] * 10 + h["B"] * 20 + cash + fees == pytest.approx(1000.0, abs=0.01)
    h2, cash2, trades2, _, turn2 = trade_to_target(h, cash, prices, {"A": 1.0}, 0.0, commission_bps=5)
    assert "B" not in h2 and any(t["side"] == "sell" and t["ticker"] == "B" for t in trades2) and 0 < turn2 <= 1


def test_rebalance_due_dates_monthly_and_buy_and_hold():
    import pandas as pd

    cal = pd.DatetimeIndex(pd.bdate_range("2025-10-31", "2025-12-31"))
    assert rebalance_due_dates({"count": 1, "unit": "1m"}, cal, dt.date(2025, 10, 31)) == [dt.date(2025, 11, 3), dt.date(2025, 12, 1)]
    assert rebalance_due_dates({"count": 0, "unit": "1q"}, cal, dt.date(2025, 10, 31)) == []
    assert rebalance_due_dates({"count": 1, "unit": "1q"}, cal, dt.date(2025, 10, 31)) == []  # 다음 분기 첫 거래일은 자료 밖


# ───────────────────────── 시작 ─────────────────────────
def test_preview_defaults_and_rules(paper_run):
    svc = _svc(paper_run, END)
    pv = svc.preview(RID)
    assert pv["start_date"] == str(END) and pv["data_ceiling"] == str(END) and pv["reconstructed_at_start"] is True
    assert pv["strategy"]["id"] == paper_run[3]["validation"]["chosen_id"] and pv["strategy_options"][0]["chosen"]
    assert abs(sum(pv["weights"].values()) + pv["cash_weight"] - 1) < 1e-3 and pv["allocation"][0]["usd"] > 0
    assert pv["initial_capital"]["currency"] == "KRW" and pv["initial_capital"]["usd"] == pytest.approx(pv["initial_capital"]["amount"] / pv["initial_capital"]["fx_rate"], rel=1e-4)
    assert pv["contribution"] == {"enabled": True, "monthly_amount": 500000.0, "currency": "KRW", "day": 25} and pv["rebalance_rule"] == {"count": 1, "unit": "1m"}
    # 기준일에 시작하면 리포트의 현재 구성 그대로
    pv0 = svc.preview(RID, start_date=str(AS_OF), strategy_id="equal_weight")
    assert pv0["reconstructed_at_start"] is False and pv0["weights"] == pv0["report_weights"] and all(d["delta"] == 0 for d in pv0["weight_diff"])
    # 시작일 규칙: 기준일 전 ✗, 자료 마감 뒤 ✗, 비거래일은 앞 거래일로
    with pytest.raises(RequestInvalid):
        svc.preview(RID, start_date="2025-10-30")
    with pytest.raises(RequestInvalid):
        svc.preview(RID, start_date="2026-01-05")
    pv1 = svc.preview(RID, start_date="2025-11-02")  # 일요일
    assert pv1["start_date"] == "2025-10-31" and pv1["warnings"]
    with pytest.raises(RequestInvalid):
        svc.preview(RID, initial_amount=-1)


def test_create_equals_preview_and_first_snapshot(paper_run):
    svc = _svc(paper_run, MID)
    pv = svc.preview(RID, start_date=str(AS_OF), strategy_id="wf_bl_news", initial_amount=10_000, currency="USD")
    d = svc.create(RID, start_date=str(AS_OF), strategy_id="wf_bl_news", initial_amount=10_000, currency="USD")
    p, snap = d["portfolio"], d["snapshots"]
    assert p["start_weights"] == pv["weights"] and p["strategy"]["kind"] == "black_litterman" and p["status"] == "active"
    assert len(snap) == 1 and snap[0]["date"] == str(AS_OF) and snap[0]["return_since_start"] <= 0  # 수수료만큼 살짝 마이너스
    assert d["rebalances"][0]["kind"] == "initial" and d["rebalances"][0]["trades"]
    held = sum(p["state"]["holdings"][t] * a["price_usd"] for a in pv["allocation"] for t in [a["ticker"]])
    assert held + p["state"]["cash_usd"] + d["rebalances"][0]["commission_usd"] == pytest.approx(10_000, abs=0.05)


# ───────────────────────── 갱신 ─────────────────────────
def test_refresh_incremental_idempotent_contribution_rebalance(paper_run):
    svc_mid = _svc(paper_run, MID)
    d = svc_mid.create(RID, start_date=str(AS_OF), strategy_id="equal_weight", initial_amount=10_000, currency="USD", monthly_contribution=1_000)
    pid = d["portfolio"]["paper_id"]
    d1 = svc_mid.refresh(pid)
    dates = [s["date"] for s in d1["snapshots"]]
    assert dates[0] == str(AS_OF) and dates[-1] == str(MID) and len(dates) == len(set(dates)) and all(a < b for a, b in zip(dates, dates[1:], strict=False))
    assert d1["summary"]["update_status"] == "ok" and d1["summary"]["days_tracked"] == len(dates)
    rebs = [r for r in d1["rebalances"] if r["kind"] == "rebalance"]
    assert [r["date"] for r in rebs] == ["2025-11-03"] and not rebs[0]["skipped"] and d1["portfolio"]["state"]["n_rebalances"] == 1
    assert d1["portfolio"]["state"]["contributions_total_usd"] == 0.0  # 25일 전
    n_before = len(d1["snapshots"])
    assert len(svc_mid.refresh(pid)["snapshots"]) == n_before  # 같은 날짜 반복 처리 없음
    # 자료가 더 들어온 뒤 (마감 12-31)
    svc_end = _svc(paper_run, END)
    d2 = svc_end.refresh(pid)
    snaps = {s["date"]: s for s in d2["snapshots"]}
    assert d2["summary"]["last_date"] == str(END) and len(snaps) == len(d2["snapshots"])
    contrib_days = [s["date"] for s in d2["snapshots"] if s["contribution_usd"] > 0]
    assert contrib_days == ["2025-11-25", "2025-12-26"] or contrib_days == ["2025-11-25", "2025-12-25"]
    assert d2["portfolio"]["state"]["contributions_total_usd"] == pytest.approx(2_000, abs=0.01)
    # 적립은 평가액은 올리지만 운용 수익률(단위가격)은 바꾸지 않는다
    before = d2["snapshots"][[s["date"] for s in d2["snapshots"]].index(contrib_days[0]) - 1]
    on = snaps[contrib_days[0]]
    unit_move = (1 + on["return_since_start"]) / (1 + before["return_since_start"])  # 그날 운용 수익률 변화 (적립 제외)
    assert on["value_usd"] == pytest.approx(before["value_usd"] * unit_move + on["contribution_usd"], rel=0.002)  # 평가액 = 전일 × 등락 + 적립
    assert abs(on["return_since_start"] - before["return_since_start"]) < 0.1
    day_move = (1 + on["benchmark_return_since_start"]) / (1 + before["benchmark_return_since_start"])  # 그날 비교지수 등락
    assert on["benchmark_value_usd"] == pytest.approx(before["benchmark_value_usd"] * day_move + on["contribution_usd"], abs=1.0)  # 비교지수에도 같은 적립
    assert [r["date"] for r in d2["rebalances"] if r["kind"] == "rebalance"] == ["2025-11-03", "2025-12-01"]
    assert [r["date"] for r in d2["rebalances"] if r["kind"] == "contribution"] == contrib_days
    s_last = d2["snapshots"][-1]
    assert abs(sum(s_last["weights"].values()) + s_last["cash_usd"] / s_last["value_usd"] - 1) < 1e-3
    summ = d2["summary"]
    assert summ["gain_usd"] == pytest.approx(s_last["value_usd"] - 10_000 - 2_000, abs=0.05) and summ["max_drawdown"] <= 0
    assert summ["benchmark_return_since_start"] is not None and summ["excess_return"] == pytest.approx(summ["return_since_start"] - summ["benchmark_return_since_start"], abs=1e-6)
    assert all(x["paper_id"] for x in svc_end.list()) and any(x["paper_id"] == pid for x in svc_end.list())


def test_stop_resume_skips_rebalances_and_leaves_gap(paper_run):
    svc_mid = _svc(paper_run, MID)
    d = svc_mid.create(RID, start_date=str(AS_OF), strategy_id="inverse_volatility", initial_amount=5_000, currency="USD", monthly_contribution=0)
    pid = d["portfolio"]["paper_id"]
    svc_mid.refresh(pid)
    stopped = svc_mid.stop(pid)
    assert stopped["portfolio"]["status"] == "stopped" and stopped["portfolio"]["history"][-1]["event"] == "stopped"
    with pytest.raises(Conflict):
        svc_mid.stop(pid)
    svc_end = _svc(paper_run, END)
    assert svc_end.refresh(pid)["summary"]["last_date"] == str(MID)  # 중지 중에는 갱신하지 않음
    resumed = svc_end.resume(pid)
    p = resumed["portfolio"]
    assert p["status"] == "active" and [h["event"] for h in p["history"]][-3:] == ["rebalance_skipped", "resumed", "resumed"][-3:] or "resumed" in [h["event"] for h in p["history"]]
    skipped = [r for r in resumed["rebalances"] if r["skipped"]]
    assert [r["date"] for r in skipped] == ["2025-12-01"]
    dates = [s["date"] for s in resumed["snapshots"]]
    assert dates[-1] == str(END) and all(not (str(MID) < x < str(END)) for x in dates)  # 중지 기간은 비어 있음
    with pytest.raises(Conflict):
        svc_end.resume(pid)


def test_refresh_marks_delayed_when_required_price_missing(paper_run):
    """필수 가격이 없으면 가짜 스냅샷 없이 delayed."""
    svc = _svc(paper_run, MID)
    d = svc.create(RID, start_date=str(AS_OF), strategy_id="equal_weight", initial_amount=1_000, currency="USD", monthly_contribution=0)
    pid = d["portfolio"]["paper_id"]
    doc = svc.papers.load(pid)
    doc["tickers"] = [*doc["tickers"], "NOPE"]
    doc["state"]["holdings"]["NOPE"] = 0.0
    svc.papers.save(doc)
    out = svc.refresh(pid)
    assert out["summary"]["update_status"] == "delayed" and "NOPE" in (out["summary"]["delayed_reason_ko"] or "") and out["summary"]["last_date"] == str(AS_OF)


# ───────────────────────── API ─────────────────────────
def test_paper_api_roundtrip(paper_run, tmp_path):
    repo, store, s, _ = paper_run
    app = create_analysis_app(lambda: repo, store_dir=store.root, settings=s, llm=lambda: StubLlm())
    c = TestClient(app)
    P = API_PREFIX
    r = c.post(f"{P}/paper/preview", json={"report_id": RID, "start_date": str(AS_OF), "strategy_id": "equal_weight"})
    assert r.status_code == 200 and r.json()["reconstructed_at_start"] is False
    r = c.post(f"{P}/paper", json={"report_id": RID, "start_date": "2025-10-01"})
    assert r.status_code == 422 and r.json()["error"]["code"] == "REQUEST_INVALID"
    r = c.post(f"{P}/paper", json={"report_id": RID, "start_date": str(AS_OF), "strategy_id": "equal_weight", "initial_amount": 3000, "currency": "USD"})
    assert r.status_code == 201
    pid = r.json()["portfolio"]["paper_id"]
    assert any(x["paper_id"] == pid for x in c.get(f"{P}/paper").json())
    d = c.post(f"{P}/paper/{pid}/refresh").json()
    assert d["summary"]["last_date"] == str(END) and d["series"]["dates"][-1] == str(END)
    assert c.post(f"{P}/paper/{pid}/stop").json()["portfolio"]["status"] == "stopped"
    assert c.post(f"{P}/paper/{pid}/stop").status_code == 409
    assert c.post(f"{P}/paper/{pid}/resume").json()["portfolio"]["status"] == "active"
    assert c.get(f"{P}/paper/nope").status_code == 404
    assert c.post(f"{P}/paper/preview", json={"report_id": "nope"}).status_code == 404
