"""이슈 #14 6번: 추가 질문 여러 개를 한 번에 답하기.

가장 급한 질문 하나(예전 규칙 그대로) + 답이 종목 선정·후보 수에 영향이 없는 질문만 최대 3개까지 함께 묻는다 (024: 앞 답이 뒤 질문의 숫자를 바꾸면 안 된다).
한 번에 보낸 답은 함께 HARD 검사하고, 한 메시지로 LLM 에 알려 턴을 한 번만 돈다. 모든 질문은 지금처럼 「답하지 않음」 으로 넘길 수 있다.
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from backend.analysis.api.app import API_PREFIX, create_analysis_app
from backend.analysis.common.llm import StubLlm
from backend.analysis.common.store import RequestStore
from backend.analysis.errors import RequestInvalid
from backend.analysis.schemas.dialog import Question
from backend.analysis.settings import AnalysisSettings, replace_settings
from backend.tests.analysis.test_dialog import PROFILE_FIELDS, Q_REB, Q_TEMPLATE, _intent, svc_factory  # noqa: F401

IDEA = "미국과 한국의 반도체·메모리 기업에 분산 투자하고 싶다"
Q_NEWS = {"field": "strategy_preference.use_news_tilt", "kind": "preference", "question_ko": "뉴스를 비중에 반영할까요?",
          "options": [{"value": True, "label_ko": "반영"}, {"value": False, "label_ko": "반영 안 함"}], "priority": 3}  # fmt: skip
Q_SECTOR = {"field": "constraints.exclude_sectors", "kind": "preference", "question_ko": "에너지 섹터를 뺄까요?",
            "options": [{"value": ["Energy"], "label_ko": "빼기"}, {"value": [], "label_ko": "그대로"}], "priority": 2}  # fmt: skip  (선정 항목 → 함께 묻지 않음)
Q_PATCH = {"field": "constraints.num_holdings", "kind": "conflict", "question_ko": "종목 수를 줄일까요?", "priority": 1,
           "options": [{"value": "a", "label_ko": "5개로 줄이기", "patch": {"constraints.num_holdings": {"target": 5, "min": 4, "max": 6}}},
                       {"value": "b", "label_ko": "그대로", "patch": {"constraints.num_holdings": {"target": 6, "min": 4, "max": 8}}}]}  # fmt: skip


def _intent_calls(llm: StubLlm) -> int:
    return sum(1 for c in llm.calls if c["stage"] == "02_intent")


def test_independent_questions_are_asked_together_and_selection_ones_wait(svc_factory):
    """선정 기준(첫 질문) + 리밸런싱·뉴스 반영은 함께. 섹터 빼기는 종목 선정을 바꾸므로 다음 턴으로."""
    svc, store, _ = svc_factory([_intent([Q_TEMPLATE, Q_SECTOR, Q_REB, Q_NEWS]), _intent([])])
    st = svc.start(IDEA)
    open_qs = [q for q in st.questions if not q.answered_at]
    assert st.state == "asking" and [q.field for q in open_qs] == ["strategy_preference.template", "constraints.rebalance", "strategy_preference.use_news_tilt"]
    assert [q.seq for q in open_qs] == [1, 2, 3] and {q.batch for q in open_qs} == {1} and st.turn == 3
    assert st.question.seq == 1  # 하나씩 보는 화면용 「지금 질문」 은 묶음의 첫 질문
    progress = {p.key: p.detail_ko for p in RequestStore(store).load(st.request_id).progress}
    assert progress["question"] == "「선정 기준(템플릿)」 · 「리밸런싱」 · 「뉴스 반영」 묻기"


def test_answer_batch_applies_all_and_runs_one_turn(svc_factory):
    svc, store, llm = svc_factory([_intent([Q_TEMPLATE, Q_REB, Q_NEWS]), _intent([])])
    st = svc.start(IDEA)
    before = _intent_calls(llm)
    st = svc.answer_batch(st.request_id, [{"seq": 1, "option_value": "quality"}, {"seq": 2, "option_value": {"count": 1, "unit": "1m"}}, {"seq": 3, "skip": True}])
    assert st.state == "ready" and _intent_calls(llm) == before + 1  # 답 3개에 의도 해석 한 번
    assert st.overrides == {"strategy_preference.template": "quality", "constraints.rebalance": {"count": 1, "unit": "1m"}}
    q1, q2, q3 = st.questions
    assert (q1.answer, q2.answer, q3.skipped) == ("퀄리티", "매월", True) and all(q.answered_at for q in (q1, q2, q3))
    doc = RequestStore(store).load(st.request_id)
    last_user = [m for m in doc.messages if m.role == "user"][-1].content
    assert last_user.startswith("사용자가 질문 3개에 한 번에 답했습니다") and "Q1 (strategy_preference.template) 답: 퀄리티" in last_user and "Q3 (strategy_preference.use_news_tilt) 답: 답하지 않음" in last_user
    rows = {r["field"]: r for r in st.confirmation["rows"]}
    assert rows["strategy_preference.template"]["source"] == "answer" and rows["constraints.rebalance"]["source"] == "answer"


def test_missing_or_empty_answers_are_skips_and_free_text_goes_to_idea(svc_factory):
    """모든 질문은 선택: 목록에서 빠지거나 비어 있으면 답하지 않음(기본값). 자유 입력은 아이디어 보충."""
    svc, store, _ = svc_factory([_intent([Q_TEMPLATE, Q_REB]), _intent([])])
    st = svc.start(IDEA)
    st = svc.answer_batch(st.request_id, [{"seq": 1, "free_text": "  배당도 조금 보고 싶어요 "}])
    q1, q2 = st.questions
    assert q1.free_text == "배당도 조금 보고 싶어요" and not q1.skipped and q2.skipped and st.overrides == {}
    assert "[선정 기준(템플릿)] 배당도 조금 보고 싶어요" in RequestStore(store).load(st.request_id).idea_clarifications


def test_complex_first_question_is_asked_alone_and_cap_limits_batch(svc_factory):
    """보기가 여러 조건을 함께 바꾸는(patch) 질문은 혼자 — 화면이 바뀌는 조건을 따로 보여 준다. 질문 상한도 묶음에 적용된다."""
    svc, _, _ = svc_factory([_intent([Q_PATCH, Q_REB, Q_NEWS]), _intent([])])
    st = svc.start(IDEA)
    assert [q.field for q in st.questions] == ["constraints.num_holdings"]
    svc2, _, _ = svc_factory([_intent([Q_TEMPLATE, Q_REB, Q_NEWS]), _intent([])], max_questions=2)
    st2 = svc2.start(IDEA)
    assert [q.field for q in st2.questions] == ["strategy_preference.template", "constraints.rebalance"]


def test_one_by_one_answers_wait_for_the_rest_of_the_batch(svc_factory):
    """하나씩 답하는 기존 API 로 묶음에 답하면 남은 질문이 있는 동안 턴을 미룬다 (LLM 을 부르지 않음)."""
    svc, _, llm = svc_factory([_intent([Q_TEMPLATE, Q_REB]), _intent([])])
    st = svc.start(IDEA)
    before = _intent_calls(llm)
    st = svc.answer(st.request_id, 1, option_value="quality")
    assert st.state == "asking" and st.question.seq == 2 and _intent_calls(llm) == before
    st = svc.skip(st.request_id, 2)
    assert st.state == "ready" and _intent_calls(llm) == before + 1


def test_answers_that_conflict_together_are_rejected_without_change(svc_factory):
    """보기 하나하나는 맞아도 함께 고르면 HARD 규칙에 걸리는 답(종목당 상한 10% × 종목 4개 < 100%) → 422, 아무것도 바꾸지 않음."""
    svc, store, _ = svc_factory([_intent([Q_TEMPLATE, Q_REB]), _intent([])])
    st = svc.start(IDEA)
    rs = RequestStore(store)
    doc = rs.load(st.request_id)
    common = {"kind": "preference", "asked_at": "t", "batch": 1}
    doc.questions = [Question(seq=1, field="constraints.max_weight_per_stock", question_ko="종목당 상한?", field_label_ko="종목당 최대 비중", **common,
                              options=[{"value": 0.1, "label_ko": "10%"}, {"value": 0.3, "label_ko": "30%"}]),
                     Question(seq=2, field="constraints.num_holdings.target", question_ko="종목 수?", field_label_ko="목표 종목 수", **common,
                              options=[{"value": 4, "label_ko": "4개"}, {"value": 6, "label_ko": "6개"}])]  # fmt: skip
    rs.save(doc)
    with pytest.raises(RequestInvalid) as e:
        svc.answer_batch(st.request_id, [{"seq": 1, "option_value": 0.1}, {"seq": 2, "option_value": 4}])
    assert "함께 고른 답이 서로 맞지 않습니다" in str(e.value) and e.value.details["seqs"] == [1, 2]
    after = rs.load(st.request_id)
    assert after.overrides == doc.overrides and not any(q.answered_at for q in after.questions)
    with pytest.raises(RequestInvalid):
        svc.answer_batch(st.request_id, [{"seq": 9, "option_value": 1}])  # 지금 묻지 않는 질문


def test_message_closes_the_whole_batch(svc_factory):
    svc, store, _ = svc_factory([_intent([Q_TEMPLATE, Q_REB]), _intent([])])
    st = svc.start(IDEA)
    st = svc.message(st.request_id, "장비 위주로")
    assert st.state == "ready" and all(q.skipped for q in st.questions)
    [r] = RequestStore(store).load(st.request_id).message_results
    assert r.closed_seqs == [1, 2] and "답하지 않은 「선정 기준(템플릿)」·「리밸런싱」 질문은 건너뛰고" in r.note_ko


def test_batch_api(seeded_repo, descriptor_dir, tmp_path):
    s = AnalysisSettings()
    s = replace_settings(s, market=replace_settings(s.market, valuation_max_staleness_days=10, descriptor_dir=str(descriptor_dir)),
                         dialog=replace_settings(s.dialog, ask_sector_cap_conflict=False))  # fmt: skip
    llm = StubLlm({"02_intent": [_intent([Q_TEMPLATE, Q_REB]), _intent([])]})
    client, p = TestClient(create_analysis_app(lambda: seeded_repo, store_dir=tmp_path / "store", settings=s, llm=lambda: llm), raise_server_exceptions=False), API_PREFIX
    assert client.put(f"{p}/profile", json=PROFILE_FIELDS).status_code == 200
    rid = client.post(f"{p}/requests", json={"idea": IDEA}).json()["request_id"]
    b = client.get(f"{p}/requests/{rid}/questions").json()
    assert b["request_id"] == rid and [q["seq"] for q in b["questions"]] == [1, 2] and not any(q["required"] for q in b["questions"])
    assert b["questions"][1] == {"seq": 2, "field": "constraints.rebalance", "field_label_ko": "리밸런싱", "question_ko": Q_REB["question_ko"], "why_ko": None,
                                 "required": False, "options": Q_REB["options"], "allow_free_text": True}  # fmt: skip
    r = client.post(f"{p}/requests/{rid}/answers", json=[{"seq": 7, "option_value": "x"}])
    assert r.status_code == 422 and r.json()["error"]["details"]["seqs"] == [7]
    st = client.post(f"{p}/requests/{rid}/answers", json=[{"seq": 1, "option_value": "quality"}, {"seq": 2, "skip": True}]).json()
    assert st["state"] == "ready" and st["overrides"] == {"strategy_preference.template": "quality"}
    assert client.get(f"{p}/requests/{rid}/questions").json()["questions"] == []
    assert client.post(f"{p}/requests/{rid}/answers", json=[]).status_code == 409  # 답할 질문이 없음


def test_question_saved_before_batches_still_loads():
    q = Question.model_validate({"seq": 1, "field": "constraints.rebalance", "kind": "preference", "question_ko": "?", "asked_at": "t"})
    assert q.batch is None
