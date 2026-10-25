"""B8 수정 요청·비교: LLM 제안의 코드 검증(고정 조건·미지원·HARD 오류), revision 대화(원안 대비 변경 표시·평가 조건 고정), 실행 뒤 비교 문서, API."""

from __future__ import annotations

import datetime as dt
import os

import pytest
from fastapi.testclient import TestClient

from backend.analysis.api.app import API_PREFIX, create_analysis_app
from backend.analysis.common.llm import StubLlm
from backend.analysis.common.store import ComparisonStore, JsonStore, RequestStore
from backend.analysis.errors import RequestInvalid
from backend.analysis.executor import worker
from backend.analysis.executor.queue import Queue
from backend.analysis.m1_request import revision as R
from backend.analysis.m1_request.dialog import DialogService
from backend.analysis.m2_data.market_data import MarketData
from backend.analysis.m5_backtest_report.compare import compare
from backend.analysis.schemas.dialog import AnalysisRequestDoc
from backend.analysis.settings import AnalysisSettings, replace_settings
from backend.db import open_repository
from backend.tests.analysis.test_dialog import PROFILE_FIELDS
from backend.tests.analysis.test_pipeline_e2e import INTENT_STUB, REQUEST

BASE_RID = "run_base1"


@pytest.fixture(scope="module")
def base_run(descriptor_dir, tmp_path_factory):
    """합성 DB 에 원안 리포트 하나 (기준일 2025-10-31 고정 → 수정안도 같은 창)."""
    from backend.analysis.common.store import ProfileStore
    from backend.tests.analysis.conftest import seed_repository

    tmp = tmp_path_factory.mktemp("rev")
    repo = open_repository("sqlite://", clock=lambda: dt.datetime(2026, 1, 5, tzinfo=dt.UTC))
    seed_repository(repo)
    s = AnalysisSettings()
    s = replace_settings(s, portfolio=replace_settings(s.portfolio, lookback_days=252, min_history_days_for_model=120),
                         market=replace_settings(s.market, valuation_max_staleness_days=10, descriptor_dir=str(descriptor_dir)))  # fmt: skip
    store = JsonStore(tmp / "store")
    ProfileStore(store).save(PROFILE_FIELDS)
    req = {**REQUEST, "request_id": "req_20251031_120000_base", "horizon": {**REQUEST["horizon"], "start_date": "2025-10-31"}}
    os.environ["ANALYSIS_OUTPUT_DIR"] = str(tmp / "out")
    try:
        doc = AnalysisRequestDoc(request_id=req["request_id"], created_at="2025-10-31T12:00:00+09:00", profile_version=1, idea=req["natural_language"]["idea"],
                                 status="confirmed", dialog_state="confirmed", effective_request=req, intent={**INTENT_STUB, "request_id": req["request_id"], "questions": []},
                                 confirmed_at="2025-10-31T12:05:00+09:00")  # fmt: skip
        RequestStore(store).save(doc)
        Queue(store).enqueue(BASE_RID, doc.request_id)
        status = worker.run_once(repo=repo, store=store, settings=s, llm=StubLlm(run_dir=tmp / "out" / BASE_RID))
    finally:
        os.environ.pop("ANALYSIS_OUTPUT_DIR", None)
    assert status in ("success", "partial"), Queue(store).get(BASE_RID)
    results = repo.get_run_artifact(BASE_RID)["results"]
    return repo, store, s, results, tmp


def _svc(base_run) -> DialogService:
    repo, store, s, _, _ = base_run
    return DialogService(store, repo, MarketData(repo, s), StubLlm(), s)


# ───────────────────────── 제안·검증 ─────────────────────────
def test_propose_filters_frozen_unknown_and_hard_errors(base_run):
    results = base_run[3]
    base_req = results["request"]
    held = [r["ticker"] for r in results["selection"]["as_of_now"]["selected"]]  # 실제 보유 종목 (table 은 후보 전체)
    target = held[0]
    # 스마트 stub: "X는 빼 주세요. 종목 수는 5개로." → 두 변경 모두 지원
    d = R.propose(base_req, results["intent"], [(t, t) for t in held], f"{target}는 빼 주세요. 종목 수는 5개로.", StubLlm())
    ok = {c.field: c for c in d.changes if c.supported}
    assert target in ok["constraints.exclude_tickers"].value and ok["constraints.num_holdings"].value["target"] == 5
    assert ok["constraints.exclude_tickers"].base_value == [] and d.unsupported_ko == [] and d.summary_ko
    ov = R.overrides_from(d, base_req)
    assert ov["horizon.start_date"] == "2025-10-31" and ov["capital.initial_amount"] == base_req["capital"]["initial_amount"] and ov["constraints.rebalance"] == base_req["constraints"]["rebalance"]
    # 평가 조건 변경은 unsupported
    d2 = R.propose(base_req, results["intent"], [], "리밸런싱을 매월로 바꿔 주세요", StubLlm())
    assert not d2.changes and any("같은 조건" in u for u in d2.unsupported_ko)
    # LLM 이 고정 필드·모르는 필드·HARD 위반 값을 내면 코드가 걸러 unsupported 로 표시
    llm = StubLlm({"15_revision": {"summary_ko": "x", "changes": [
        {"field": "capital.initial_amount", "value": 1, "reason_ko": "투자금 변경"},
        {"field": "constraints.universe", "value": ["SP500"], "reason_ko": "범위 변경"},
        {"field": "profile.age_band", "value": "40s", "reason_ko": "?"},
        {"field": "constraints.max_weight_per_sector", "value": 0.1, "reason_ko": "섹터 상한 10%"},
        {"field": "strategy_preference.template", "value": "momentum", "reason_ko": "같은 값"},
        {"field": "strategy_preference.template", "value": "quality", "reason_ko": "퀄리티로"},
        {"field": "constraints.max_weight_per_stock", "value": 25, "reason_ko": "25%"}], "idea_update_ko": None, "unsupported_ko": []}})  # fmt: skip
    d3 = R.propose(base_req, results["intent"], [], "여러 가지", llm)
    by = {(c.field, c.supported): c for c in d3.changes}
    assert by[("capital.initial_amount", False)].note_ko == R.FROZEN_NOTE and ("constraints.universe", False) in by
    assert "바꿀 수 없습니다" in by[("profile.age_band", False)].note_ko
    assert ("constraints.max_weight_per_sector", False) in by and "상한" in by[("constraints.max_weight_per_sector", False)].note_ko
    assert "같은 값" in by[("strategy_preference.template", False)].note_ko and by[("strategy_preference.template", True)].value == "quality"
    assert by[("constraints.max_weight_per_stock", True)].value == 0.25  # 25 → 0.25
    assert [c.field for c in d3.changes if c.supported] == ["strategy_preference.template", "constraints.max_weight_per_stock"]


# ───────────────────────── 대화 → 실행 → 비교 ─────────────────────────
def test_revision_dialog_confirm_run_and_compare(base_run):
    repo, store, s, results, tmp = base_run
    svc = _svc(base_run)
    held = [r["ticker"] for r in results["selection"]["as_of_now"]["selected"]]
    target = held[0]
    with pytest.raises(RequestInvalid):
        svc.start_revision(BASE_RID, "짧")
    st = svc.start_revision(BASE_RID, f"{target}는 빼 주세요")
    assert st.mode == "revision" and st.base_report_id == BASE_RID and st.revision and st.revision.base_run_id == BASE_RID
    assert [c.field for c in st.revision.changes if c.supported] == ["constraints.exclude_tickers"]
    doc = RequestStore(store).load(st.request_id)
    assert doc.overrides["horizon.start_date"] == "2025-10-31" and any("[수정 요청]" in c for c in doc.idea_clarifications)
    while st.state == "asking" and st.question:
        st = svc.skip(st.request_id, st.question.seq)
    assert st.state == "ready" and st.summary.derived["as_of"] == "2025-10-31"  # 평가 창이 원안과 같다
    rows = {r["field"]: r for r in st.confirmation["rows"]}
    assert rows["constraints.exclude_tickers"]["changed"] and target in rows["constraints.exclude_tickers"]["value_ko"]
    assert not rows["capital.initial_amount"]["changed"] and not rows["constraints.rebalance"]["changed"]  # 원안 대비 변경만 표시
    run_id, _ = svc.confirm(st.request_id)
    os.environ["ANALYSIS_OUTPUT_DIR"] = str(tmp / "out")
    try:
        status = worker.run_once(repo=repo, store=store, settings=s, llm=StubLlm(run_dir=tmp / "out" / run_id))
    finally:
        os.environ.pop("ANALYSIS_OUTPUT_DIR", None)
    assert status in ("success", "partial"), Queue(store).get(run_id)
    cmp_doc = ComparisonStore(store).load(f"cmp_{run_id}")
    assert cmp_doc["same_window"] is True and cmp_doc["base_report_id"] == BASE_RID and cmp_doc["revised_report_id"] == run_id
    assert target in cmp_doc["ticker_changes"]["removed"] and target not in cmp_doc["ticker_changes"]["kept"]
    assert any(c["field"] == "constraints.exclude_tickers" for c in cmp_doc["condition_changes"])
    assert cmp_doc["performance_table"] and {r["metric"] for r in cmp_doc["performance_table"]} >= {"cagr", "max_drawdown", "sharpe"}
    assert all(r["base"] is not None and r["revised"] is not None for r in cmp_doc["performance_table"] if r["metric"] in ("cagr", "max_drawdown"))
    assert cmp_doc["rule_changes"] and cmp_doc["revision_text"].startswith(target) and cmp_doc["pros_cons_ko"]["note_ko"]
    # 평가 조건이 다르면 성과표를 만들지 않는다
    other = {**results, "request": {**results["request"], "capital": {**results["request"]["capital"], "initial_amount": 1}}}
    c2 = compare(results, other, base_report_id="a", revised_report_id="b")
    assert c2["same_window"] is False and c2["performance_table"] == [] and c2["warnings"]


def test_revision_api(base_run):
    repo, store, s, results, _ = base_run
    app = create_analysis_app(lambda: repo, store_dir=store.root, settings=s, llm=lambda: StubLlm())
    c = TestClient(app)
    P = API_PREFIX
    assert c.get(f"{P}/reports/{BASE_RID}/comparison").status_code == 404 and c.get(f"{P}/reports/{BASE_RID}/comparison").json()["error"]["code"] == "COMPARISON_MISSING"
    held = [r["ticker"] for r in results["selection"]["as_of_now"]["selected"]]
    r = c.post(f"{P}/reports/{BASE_RID}/revisions", json={"text": f"{held[-1]}는 빼 주세요. 종목 수는 5개로."})
    assert r.status_code == 200, r.text
    st = r.json()
    assert st["mode"] == "revision" and st["revision"]["changes"] and st["base_report_id"] == BASE_RID
    assert c.post(f"{P}/reports/nope/revisions", json={"text": "무엇이든"}).status_code == 404
    assert c.get(f"{P}/comparisons/cmp_nope").status_code == 404
