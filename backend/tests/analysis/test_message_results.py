"""이슈 #14 7번: 「말로 보태기」 결과 기록 — 동작(아이디어 보충 + 의도 해석 다시)은 그대로, 그 턴 전후로 무엇이 달라졌는지만 남긴다.

확인 질문이 생김 → needs_confirmation / 테마·조건 표시값이 달라짐 → applied / 둘 다 아님 → not_applied.
"""

from __future__ import annotations

from fastapi.testclient import TestClient

from backend.analysis.api.app import API_PREFIX, create_analysis_app
from backend.analysis.common.llm import StubLlm
from backend.analysis.common.store import JsonStore, RequestStore
from backend.analysis.m1_request.message_result import THEMES_FIELD, Snapshot, judge
from backend.analysis.schemas.dialog import ConditionRow, Question
from backend.analysis.settings import AnalysisSettings, replace_settings
from backend.tests.analysis.test_dialog import PROFILE_FIELDS, Q_REB, Q_TEMPLATE, _intent, svc_factory  # noqa: F401

IDEA = "미국과 한국의 반도체·메모리 기업에 분산 투자하고 싶다"


def _themes(*labels: str) -> dict:
    out = _intent([])
    out["interpretation"]["themes"] = [{**out["interpretation"]["themes"][0], "id": f"t{i}", "label_ko": lab} for i, lab in enumerate(labels)]
    return out


def test_new_question_means_needs_confirmation_and_open_question_is_closed(svc_factory):
    """말 때문에 LLM 이 질문을 제안하면 → 확인 필요 (그 질문에 답해야 조건이 바뀐다). 떠 있던 질문은 건너뜀으로 닫혔다고 알린다."""
    svc, store, _ = svc_factory([_intent([Q_TEMPLATE]), _intent([Q_REB])])
    st = svc.start(IDEA)
    assert st.state == "asking" and st.question.seq == 1
    st = svc.message(st.request_id, "리밸런싱은 매달 해 주세요")
    assert st.state == "asking" and st.question.seq == 2 and st.question.field == "constraints.rebalance"
    [r] = RequestStore(store).load(st.request_id).message_results
    assert r.outcome == "needs_confirmation" and r.text == "리밸런싱은 매달 해 주세요" and r.at
    assert r.question_seq == 2 and r.closed_seq == 1
    assert "「리밸런싱」 항목을 확인하는 질문" in r.note_ko and "답하지 않은 「선정 기준(템플릿)」 질문은 건너뛰고" in r.note_ko
    assert r.changes == []  # 테마·조건 값은 그대로


def test_theme_change_is_applied_with_before_and_after(svc_factory):
    """조건 값은 그대로여도 테마 해석이 바뀌면 반영됨. 바뀐 것은 「해석한 테마: 전 → 후」."""
    svc, store, _ = svc_factory([_intent([]), _themes("반도체 장비")])
    st = svc.start(IDEA)
    assert st.state == "ready"
    st = svc.message(st.request_id, "장비 회사 위주로 봐 주세요")
    assert st.state == "ready"
    [r] = RequestStore(store).load(st.request_id).message_results
    assert r.outcome == "applied" and r.question_seq is None and r.closed_seq is None
    assert [(c.field, c.label_ko, c.before_ko, c.after_ko) for c in r.changes] == [(THEMES_FIELD, "해석한 테마", "반도체", "반도체 장비")]
    assert r.note_ko.startswith("아이디어 해석(테마)에 반영했습니다")


def test_nothing_changed_is_not_applied_and_points_to_condition_editor(svc_factory):
    """테마도 조건도 그대로면 반영 안 됨 — 말은 아이디어 보충으로 남고, 숫자·종목은 「조건 바꾸기」로 안내한다. 보낸 순서대로 쌓인다."""
    svc, store, _ = svc_factory([_intent([]), _intent([]), _themes("메모리")])
    st = svc.start(IDEA)
    st = svc.message(st.request_id, "테슬라도 꼭 넣어 주세요")
    st = svc.message(st.request_id, "메모리 위주로")
    doc = RequestStore(store).load(st.request_id)
    first, second = doc.message_results
    assert first.outcome == "not_applied" and first.changes == [] and "「조건 바꾸기」" in first.note_ko and "아이디어 보충으로 남아" in first.note_ko
    assert second.outcome == "applied" and second.changes[0].before_ko == "반도체" and second.changes[0].after_ko == "메모리"
    assert [c for c in doc.idea_clarifications if c.startswith("[추가 요청]")] == ["[추가 요청] 테슬라도 꼭 넣어 주세요", "[추가 요청] 메모리 위주로"]


def test_question_cap_reached_is_not_applied_with_reason(svc_factory):
    """질문 상한을 다 쓴 뒤 LLM 이 또 묻고 싶어 하면 → 질문이 생기지 않으므로 반영 안 됨 + 「추가 질문을 모두 써서」."""
    svc, store, _ = svc_factory([_intent([Q_TEMPLATE]), _intent([Q_REB])], max_questions=1)
    st = svc.start(IDEA)
    st = svc.message(st.request_id, "리밸런싱은 매달")
    assert st.state == "ready" and st.blocked_reason_ko
    [r] = RequestStore(store).load(st.request_id).message_results
    assert r.outcome == "not_applied" and "추가 질문을 모두 써서" in r.note_ko and r.closed_seq == 1


def test_judge_reports_condition_rows_and_ignores_idea_row():
    """조건 행 표시값이 달라지면 「조건에 반영했습니다」. 아이디어 행은 보탠 말이 붙어 늘 달라지므로 비교하지 않는다."""
    row = lambda f, g, v: ConditionRow(field=f, group_ko=g, label_ko=f, value_ko=v)  # noqa: E731
    from backend.analysis.m1_request.message_result import snapshot

    before = snapshot([row("constraints.num_holdings", "종목 범위·제약", "목표 10개"), row("natural_language.idea", "아이디어", "a")], None)
    after = snapshot([row("constraints.num_holdings", "종목 범위·제약", "목표 8개"), row("natural_language.idea", "아이디어", "a [추가 요청] 8개만")], None)
    r = judge("8개만", "t", before, after, asked=None, closed=None, capped=False)
    assert r.outcome == "applied" and [c.field for c in r.changes] == ["constraints.num_holdings"] and r.note_ko == "조건에 반영했습니다."
    q = Question(field="constraints.rebalance", kind="preference", question_ko="?", seq=3, asked_at="t", field_label_ko="리밸런싱")
    assert judge("x", "t", Snapshot(), Snapshot(), asked=q, closed=None, capped=False).question_seq == 3


def test_messages_endpoint_lists_results_in_order(seeded_repo, descriptor_dir, tmp_path):
    s = AnalysisSettings()
    s = replace_settings(s, market=replace_settings(s.market, valuation_max_staleness_days=10, descriptor_dir=str(descriptor_dir)),
                         dialog=replace_settings(s.dialog, ask_sector_cap_conflict=False))  # fmt: skip
    llm = StubLlm({"02_intent": [_intent([]), _intent([]), _themes("반도체 장비")]})  # 호출 순서대로 답하도록 한 객체를 계속 쓴다
    app = create_analysis_app(lambda: seeded_repo, store_dir=tmp_path / "store", settings=s, llm=lambda: llm)
    client, p = TestClient(app, raise_server_exceptions=False), API_PREFIX
    assert client.put(f"{p}/profile", json=PROFILE_FIELDS).status_code == 200
    rid = client.post(f"{p}/requests", json={"idea": IDEA}).json()["request_id"]
    assert client.get(f"{p}/requests/{rid}/messages").json() == []
    client.post(f"{p}/requests/{rid}/message", json={"text": "테슬라도 넣어 주세요"})
    client.post(f"{p}/requests/{rid}/message", json={"text": "장비 위주로"})
    rows = client.get(f"{p}/requests/{rid}/messages").json()
    assert [(r["text"], r["outcome"]) for r in rows] == [("테슬라도 넣어 주세요", "not_applied"), ("장비 위주로", "applied")]
    assert set(rows[1]) >= {"text", "at", "outcome", "changes", "note_ko"} and rows[1]["changes"][0]["after_ko"] == "반도체 장비"
    assert client.get(f"{p}/requests/req_nope/messages").status_code == 404


def test_request_saved_before_this_feature_still_loads(tmp_path):
    """message_results 가 없는 예전 요청 문서도 그대로 읽힌다 (저장 모델은 extra=forbid 라 필드 추가만 했다)."""
    store = JsonStore(tmp_path)
    old = {"request_id": "req_20261101_000000_abcd", "created_at": "2026-11-01T00:00:00+09:00", "profile_version": 1, "idea": "반도체", "idea_clarifications": ["[추가 요청] 예전 말"]}
    store.write("requests/req_20261101_000000_abcd.json", old)
    assert RequestStore(store).load("req_20261101_000000_abcd").message_results == []
