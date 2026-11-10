"""이슈 #14 11번 중 request_log: 리포트 「내 요청」 기록 — 아이디어, 답한 질문, 말로 보탠 요청과 결과, 최종 조건.

실행이 끝날 때 리포트에 붙여 저장하고, 이 기능 전 리포트는 읽을 때 요청 문서에서 만든다. 결과 기록 없이 보낸 말이 있으면 붙이지 않는다.
"""

from __future__ import annotations

import datetime as dt
import os

import pytest
from fastapi.testclient import TestClient

from backend.analysis.api.app import API_PREFIX, create_analysis_app
from backend.analysis.common.llm import StubLlm
from backend.analysis.common.store import JsonStore
from backend.analysis.executor import worker
from backend.analysis.m5_backtest_report.request_log import build, on_read, with_request_log
from backend.analysis.schemas.dialog import AnalysisRequestDoc, ConditionRow, MessageChange, MessageResult, Question
from backend.analysis.settings import AnalysisSettings, replace_settings
from backend.db import open_repository
from backend.tests.analysis.conftest import seed_repository
from backend.tests.analysis.test_dialog import PROFILE_FIELDS, Q_TEMPLATE, _intent
from backend.tests.analysis.test_message_results import IDEA, _themes

P = API_PREFIX


def _doc(**kw) -> AnalysisRequestDoc:
    return AnalysisRequestDoc(request_id="req_1", created_at="2026-11-10T09:00:00", profile_version=1, idea="반도체", **kw)


def _row(label: str, value: str, changed: bool = False, group: str = "종목 범위·제약") -> ConditionRow:
    return ConditionRow(field=label, group_ko=group, label_ko=label, value_ko=value, changed=changed)


def test_build_lists_answers_messages_and_final_conditions():
    q1 = Question(field="strategy_preference.template", kind="preference", question_ko="선정 기준은?", seq=1, asked_at="t1", answer="퀄리티", answered_at="t2",
                  applied={"field": "strategy_preference.template", "value": "quality"})  # fmt: skip
    q2 = Question(field="constraints.rebalance", kind="preference", question_ko="리밸런싱은?", seq=2, asked_at="t3", answer="(말로 조건을 보태 건너뜀)", answered_at="t4", skipped=True)
    q3 = Question(field="constraints.num_holdings", kind="feasibility", question_ko="종목이 부족합니다", seq=3, asked_at="t5", answer="줄이기", answered_at="t6",
                  applied={"field": "constraints.num_holdings", "value": "a", "patch": {"constraints.num_holdings": {"target": 6, "min": 5, "max": 8}, "_allow": True}})  # fmt: skip
    q4 = Question(field="constraints.max_weight_per_stock", kind="preference", question_ko="대기 중", seq=4, asked_at="t7")  # 답하지 않은 질문은 넣지 않는다
    msg = MessageResult(text="장비 위주로", at="t3b", outcome="applied", note_ko="아이디어 해석(테마)에 반영했습니다.",
                        changes=[MessageChange(field="intent.themes", label_ko="해석한 테마", before_ko="반도체", after_ko="반도체 장비")])  # fmt: skip
    doc = _doc(questions=[q1, q2, q3, q4], idea_clarifications=["[추가 요청] 장비 위주로"], message_results=[msg])
    rows = [_row("종목 수", "목표 6개", True), _row("투자 아이디어", "반도체", group="아이디어")]
    log = build(doc, rows)
    assert log["idea"] == "반도체"
    assert [(x["question_ko"], x["answer_ko"], x["at"], x["applied_ko"]) for x in log["qa"]] == [
        ("선정 기준은?", "퀄리티", "t2", "선정 기준(템플릿) → 퀄리티(ROE)"),
        ("리밸런싱은?", "(말로 조건을 보태 건너뜀)", "t4", None),
        ("종목이 부족합니다", "줄이기", "t6", "종목 수 → 목표 6개 (최소 5 ~ 최대 8)"),  # 숨은 덮어쓰기(_)는 빼고 patch 값으로
    ]
    assert log["messages"] == [{"text": "장비 위주로", "at": "t3b", "outcome": "applied", "changes_ko": ["해석한 테마: 반도체 → 반도체 장비"], "note_ko": "아이디어 해석(테마)에 반영했습니다."}]
    assert log["final_conditions"] == [{"label_ko": "종목 수", "value_ko": "목표 6개", "changed": True}]  # 아이디어 행은 뺀다


def test_message_sent_before_results_were_recorded_omits_the_log():
    """이 기능 전에 보낸 말은 결과를 알 수 없다 → request_log 를 붙이지 않아 화면은 예전 안내 그대로. 수정안이 원안에게 물려받은 말은 세지 않는다."""
    assert build(_doc(idea_clarifications=["[추가 요청] 예전 말", "[종목 수] 8개"]), []) is None
    assert build(_doc(idea_clarifications=["[선정 기준 바꾸기] 고배당"]), [])["messages"] == []
    assert build(_doc(mode="revision", idea_clarifications=["[추가 요청] 원안에서 보낸 말", "[수정 요청] 엔비디아 빼 줘"]), [], inherited=1) is not None


def test_with_request_log_keeps_other_proposed_values():
    doc = {"run_id": "r", "proposed": {"contract": "proposed-0.1", "execution": {"items": []}}}
    out = with_request_log(doc, {"idea": "x", "qa": [], "messages": [], "final_conditions": []})
    assert out["proposed"]["execution"] == {"items": []} and out["proposed"]["request_log"]["idea"] == "x" and "proposed" in doc and "request_log" not in doc["proposed"]
    assert with_request_log(doc, None) is doc


@pytest.fixture(scope="module")
def flow(descriptor_dir, tmp_path_factory):
    tmp = tmp_path_factory.mktemp("reqlog")
    repo = open_repository(f"sqlite:///{tmp / 'api.db'}", clock=lambda: dt.datetime(2026, 1, 5, tzinfo=dt.UTC))
    seed_repository(repo)
    s = AnalysisSettings()
    s = replace_settings(s, portfolio=replace_settings(s.portfolio, lookback_days=252, min_history_days_for_model=120),
                         market=replace_settings(s.market, valuation_max_staleness_days=10, descriptor_dir=str(descriptor_dir)),
                         dialog=replace_settings(s.dialog, ask_sector_cap_conflict=False))  # fmt: skip
    llm = StubLlm({"02_intent": [_intent([Q_TEMPLATE]), _themes("반도체 장비")]})
    app = create_analysis_app(lambda: repo, store_dir=tmp / "store", settings=s, llm=lambda: llm)
    os.environ["ANALYSIS_OUTPUT_DIR"] = str(tmp / "out")
    yield TestClient(app, raise_server_exceptions=False), repo, JsonStore(tmp / "store"), s
    os.environ.pop("ANALYSIS_OUTPUT_DIR", None)


def test_report_carries_request_log_and_old_reports_get_it_on_read(flow):
    client, repo, store, s = flow
    assert client.put(f"{P}/profile", json=PROFILE_FIELDS).status_code == 200
    rid = client.post(f"{P}/requests", json={"idea": IDEA}).json()["request_id"]
    st = client.post(f"{P}/requests/{rid}/message", json={"text": "장비 회사 위주로"}).json()  # 떠 있던 질문을 닫고 테마가 바뀜 → ready
    assert st["state"] == "ready"
    run_id = client.post(f"{P}/requests/{rid}/confirm").json()["run_id"]
    assert worker.run_once(repo=repo, store=store, settings=s, llm=StubLlm()) in ("success", "partial")
    doc = client.get(f"{P}/reports/{run_id}").json()
    log = doc["proposed"]["request_log"]
    assert log["idea"] == IDEA and log["qa"][0]["question_ko"] == Q_TEMPLATE["question_ko"] and log["qa"][0]["applied_ko"] is None
    assert [(m["text"], m["outcome"], m["changes_ko"]) for m in log["messages"]] == [("장비 회사 위주로", "applied", ["해석한 테마: 반도체 → 반도체 장비"])]
    labels = {c["label_ko"] for c in log["final_conditions"]}
    assert {"투자금", "분석 기준일"} <= labels and "투자 아이디어" not in labels
    stored = repo.get_report(run_id)
    stored = stored["doc"] if isinstance(stored, dict) and "doc" in stored else stored
    assert stored["proposed"]["request_log"] == log  # 실행이 끝날 때 저장했다 (읽을 때 만든 것이 아니다)
    # 이 기능 전 리포트: 저장 문서에 없으면 읽을 때 요청 문서에서 같은 기록을 만든다
    old = {**stored, "proposed": {k: v for k, v in stored["proposed"].items() if k != "request_log"}}
    assert on_read(store, old)["proposed"]["request_log"] == log
    assert on_read(store, {**old, "request_id": "req_nope"}) == {**old, "request_id": "req_nope"}  # 요청 문서가 없으면 그대로
