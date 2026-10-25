"""라운드 5 대화: 실행 전 점검 질문(후보 부족·창 축소), 보기 1개 질문 폐기, 종목 수 자동 보정, 질문 상한 → ready."""

from __future__ import annotations

import json

from backend.analysis.common.store import RequestStore
from backend.analysis.m1_request.validate import hard_errors
from backend.analysis.schemas.dialog import QuestionOption, QuestionProposal
from backend.tests.analysis.test_dialog import PROFILE_FIELDS, Q_TEMPLATE, _intent, svc_factory  # noqa: F401
from backend.tests.analysis.test_pipeline_e2e import REQUEST


def test_feasibility_question_when_candidates_short(svc_factory):
    """반도체 테마(seed 7종목)에 목표 10·최소 8 → 후보 부족 질문이 LLM 질문보다 먼저, 첫 보기(종목 수 축소 + 상한 상향)가 patch 로 반영된다."""
    svc, store, llm = svc_factory([_intent([Q_TEMPLATE]), _intent([]), _intent([])])
    st = svc.start("반도체 장기 투자", overrides={"constraints.num_holdings": {"target": 10, "min": 8, "max": 12}})
    q = st.question
    assert q is not None and q.kind == "feasibility" and q.field == "constraints.num_holdings" and q.field_label_ko == "종목 수"
    assert st.precheck and st.precheck["short_now"] and st.precheck["as_of"]["n_candidates"] < 8
    labels = [o.label_ko for o in q.options]
    assert any("종목 수를" in x and "상한을" in x for x in labels) and any("테마를 넓혀" in x for x in labels) and any("그대로 진행" in x for x in labels)
    shrink = next(o for o in q.options if o.patch and "constraints.num_holdings" in o.patch)
    n = shrink.patch["constraints.num_holdings"]["target"]
    st = svc.answer(st.request_id, 1, option_value=shrink.value)
    doc = RequestStore(store).load(st.request_id)
    assert doc.overrides["constraints.num_holdings"] == {"target": n, "min": n, "max": n} and doc.overrides["constraints.max_weight_per_stock"] >= 1.0 / n - 1e-9
    assert doc.questions[0].applied["patch"] == shrink.patch and not doc.hard_errors
    assert all(x.kind != "feasibility" or x.seq == 1 for x in doc.questions)  # 같은 점검 질문을 다시 묻지 않는다


def test_feasibility_proceed_option_and_widen(svc_factory):
    svc, store, _ = svc_factory([_intent([]), _intent([]), _intent([])])
    st = svc.start("반도체 장기 투자", overrides={"constraints.num_holdings": {"target": 10, "min": 8, "max": 12}})
    proceed = next(o for o in st.question.options if o.patch and o.patch.get("_ack_few_candidates"))
    st = svc.answer(st.request_id, 1, option_value=proceed.value)
    assert st.state == "ready" and "_ack_few_candidates" not in st.overrides  # 숨은 override 는 화면에 안 보인다
    doc = RequestStore(store).load(st.request_id)
    assert doc.overrides["_ack_few_candidates"] is True
    svc2, store2, _ = svc_factory([_intent([]), _intent([]), _intent([])])
    st2 = svc2.start("반도체 장기 투자", overrides={"constraints.num_holdings": {"target": 10, "min": 8, "max": 12}})
    widen = next(o for o in st2.question.options if o.clarification)
    st2 = svc2.answer(st2.request_id, 1, option_value=widen.value)
    doc2 = RequestStore(store2).load(st2.request_id)
    assert any("[테마 넓히기]" in c for c in doc2.idea_clarifications)


def test_single_option_question_is_dropped(svc_factory):
    """보기 2개 중 하나가 HARD 에 걸려 빠지면(남은 보기 1개) 질문을 내보내지 않는다."""
    q = dict(Q_TEMPLATE, options=[{"value": "momentum", "label_ko": "모멘텀"}, {"value": "not_a_template", "label_ko": "없는 템플릿"}], allow_free_text=False)
    svc, store, _ = svc_factory([_intent([q]), _intent([])])
    st = svc.start("반도체 장기 투자")
    assert st.state == "ready" and st.question is None
    assert any("fewer than 2 valid options" in w for w in RequestStore(store).load(st.request_id).warnings)


def test_num_holdings_target_auto_adjusts_min_max(svc_factory):
    svc, store, _ = svc_factory([_intent([]), _intent([])])
    st = svc.start("반도체 장기 투자")
    base = PROFILE_FIELDS["constraints"]["num_holdings"]
    st = svc.update_overrides(st.request_id, {"constraints.num_holdings.target": base["min"] - 1})
    assert not st.hard_errors
    doc = RequestStore(store).load(st.request_id)
    assert doc.overrides["constraints.num_holdings.min"] == max(2, base["min"] - 1)
    st = svc.update_overrides(st.request_id, {"constraints.num_holdings.target": base["max"] + 3})
    assert not st.hard_errors and RequestStore(store).load(st.request_id).overrides["constraints.num_holdings.max"] == base["max"] + 3


def test_hard_error_messages_use_field_units():
    req = json.loads(json.dumps(REQUEST))
    req["horizon"]["target_years"] = 0.5
    req["constraints"]["max_weight_per_stock"] = 1.01
    req["constraints"]["max_weight_per_sector"] = 1.01
    msgs = {e.field: e.message_ko for e in hard_errors(req)}
    assert msgs["horizon.target_years"] == "투자기간(년): 1년 이상이어야 합니다"
    assert msgs["constraints.max_weight_per_stock"] == "종목당 상한: 100% 이하여야 합니다"
    req = json.loads(json.dumps(REQUEST))
    req["horizon"]["target_years"] = 11
    assert {e.field: e.message_ko for e in hard_errors(req)}["horizon.target_years"] == "투자기간(년): 10년 이하여야 합니다"


def test_question_option_patch_schema_roundtrip():
    p = QuestionProposal(field="constraints.num_holdings", kind="feasibility", question_ko="?", options=[QuestionOption(value="x", label_ko="x", patch={"a.b": 1})], allow_free_text=False)
    assert p.model_dump()["options"][0]["patch"] == {"a.b": 1}
