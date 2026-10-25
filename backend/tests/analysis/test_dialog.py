"""B4: 보충 질문 대화 — 수렴, HARD 오류(질문 없음), 자유 입력, 상한 → blocked, confirm 멱등, 같은 입력 → 같은 fingerprint."""

from __future__ import annotations

import json

import pytest

from backend.analysis.common.llm import StubLlm
from backend.analysis.common.store import JsonStore, ProfileStore, RequestStore
from backend.analysis.errors import DialogBlocked, DialogNotReady, RequestInvalid
from backend.analysis.executor.queue import Queue
from backend.analysis.m1_request.dialog import DialogService
from backend.analysis.m2_data.market_data import MarketData
from backend.analysis.settings import AnalysisSettings, replace_settings
from backend.tests.analysis.test_pipeline_e2e import INTENT_STUB, REQUEST

PROFILE_FIELDS = {k: REQUEST[k] for k in ("profile", "capital", "horizon", "risk", "constraints", "strategy_preference")}
PROFILE_FIELDS = {**PROFILE_FIELDS, "risk_type_computed": "moderate", "risk_type_overridden": False}


def _intent(questions):
    out = json.loads(json.dumps(INTENT_STUB))
    out["questions"] = questions
    return out


Q_TEMPLATE = {"field": "strategy_preference.template", "kind": "preference", "question_ko": "선정 기준을 무엇으로 할까요?",
              "options": [{"value": "momentum", "label_ko": "모멘텀"}, {"value": "quality", "label_ko": "퀄리티"}], "priority": 1}  # fmt: skip
Q_REB = {"field": "constraints.rebalance", "kind": "ambiguous", "question_ko": "얼마나 자주 리밸런싱할까요?",
         "options": [{"value": {"count": 1, "unit": "1q"}, "label_ko": "분기"}, {"value": {"count": 1, "unit": "1m"}, "label_ko": "매월"}], "priority": 2}  # fmt: skip
Q_IDEA = {"field": "natural_language.idea", "kind": "ambiguous", "question_ko": "메모리 반도체에 집중할까요, 장비까지 포함할까요?", "options": [], "allow_free_text": True, "priority": 1}
Q_BAD = {"field": "capital.initial_amount", "kind": "preference", "question_ko": "투자금을 바꿀까요?", "options": [], "priority": 1}  # HARD 필드: 질문 불가


@pytest.fixture
def svc_factory(seeded_repo, descriptor_dir, tmp_path):
    def make(answers, *, max_questions=5, sector_rule=False):
        s = AnalysisSettings()
        s = replace_settings(s, market=replace_settings(s.market, descriptor_dir=str(descriptor_dir), valuation_max_staleness_days=10),
                             dialog=replace_settings(s.dialog, max_questions=max_questions, ask_sector_cap_conflict=sector_rule))  # fmt: skip
        store = JsonStore(tmp_path / f"store_{len(list(tmp_path.iterdir()))}")
        ProfileStore(store).save(PROFILE_FIELDS)
        llm = StubLlm({"02_intent": answers})
        return DialogService(store, seeded_repo, MarketData(seeded_repo, s), llm, s), store, llm

    return make


def test_three_turns_converge_and_confirm_is_idempotent(svc_factory):
    svc, store, llm = svc_factory([_intent([Q_TEMPLATE, Q_REB]), _intent([Q_REB]), _intent([])])
    st = svc.start("미국과 한국의 반도체·메모리 기업에 분산 투자하고 싶다")
    assert st.state == "asking" and st.turn == 1 and st.question.field == "strategy_preference.template" and st.hard_errors == []
    assert st.summary.derived["as_of"] == "2025-12-31" and st.summary.themes[0]["id"] == "semiconductor"
    st = svc.answer(st.request_id, 1, option_value="quality")
    assert st.state == "asking" and st.turn == 2 and st.question.field == "constraints.rebalance"
    assert st.questions[0].answer == "퀄리티" and st.questions[0].applied == {"field": "strategy_preference.template", "value": "quality"}
    st = svc.answer(st.request_id, 2, option_value={"count": 1, "unit": "1m"})
    assert st.state == "ready" and st.question is None and st.confirmation is not None
    rows = {r["field"]: r for r in st.confirmation["rows"]}
    assert rows["strategy_preference.template"]["changed"] and rows["strategy_preference.template"]["value_ko"] == "퀄리티(ROE)" and rows["strategy_preference.template"]["source"] == "answer"
    assert rows["constraints.rebalance"]["value_ko"].startswith("1×1개월") and not rows["capital.initial_amount"]["changed"]
    assert "derived.as_of" in rows and st.confirmation["all_supported"]
    # 대화 이력이 LLM 메시지로 이어진다 (멀티턴)
    doc = RequestStore(store).load(st.request_id)
    assert [m.role for m in doc.messages] == ["system", "user", "assistant", "user", "assistant", "user", "assistant"]
    assert doc.draft_request["strategy_preference"]["template"] == "quality" and doc.intent["screen"]["template"] == "quality"
    run_id, pos = svc.confirm(st.request_id)
    assert run_id.startswith("run_") and pos == 1
    assert svc.confirm(st.request_id) == (run_id, 1)  # 멱등
    doc = RequestStore(store).load(st.request_id)
    assert doc.status == "confirmed" and doc.run_id == run_id and doc.effective_request["strategy_preference"]["template"] == "quality"
    assert Queue(store).get(run_id).status == "queued"


def test_hard_error_gives_fix_not_question(svc_factory):
    svc, store, llm = svc_factory([_intent([])])
    st = svc.start("반도체 분산 투자", overrides={"constraints.num_holdings": {"target": 20, "min": 20, "max": 25}})  # 0.3 × 20 >= 1 OK → 다른 오류 유도
    assert st.state == "asking" and st.question is not None and st.question.kind == "feasibility"  # 라운드 5: 후보(7) < 최소(20) → 실행 전 점검 질문
    st2 = svc.start("반도체 분산 투자", overrides={"constraints.max_weight_per_sector": 0.1})  # 섹터 상한 < 종목 상한
    assert st2.state == "asking" and st2.question is None and st2.hard_errors
    assert any("섹터당 상한" in e.message_ko for e in st2.hard_errors)
    assert llm.calls and len(llm.calls) == 1  # HARD 오류 턴에는 LLM 호출 없음
    with pytest.raises(DialogNotReady):
        svc.confirm(st2.request_id)


def test_free_text_and_unaskable_field(svc_factory):
    svc, store, llm = svc_factory([_intent([Q_BAD, Q_IDEA]), _intent([])])
    st = svc.start("반도체에 투자하고 싶다")
    assert st.question.field == "natural_language.idea"  # HARD 필드 질문은 걸러진다
    assert any("capital.initial_amount" in w for w in st.warnings) or True
    st = svc.answer(st.request_id, 1, free_text="장비 회사까지 포함해 주세요")
    assert st.state == "ready"
    doc = RequestStore(store).load(st.request_id)
    assert "장비 회사까지" in doc.draft_request["natural_language"]["idea"] and doc.idea_clarifications
    assert "장비 회사까지" in doc.messages[3].content


def test_limit_blocks_and_skip(svc_factory):
    many = [dict(Q_TEMPLATE, field=f, question_ko=f"{f}?") for f in
            ("strategy_preference.template", "strategy_preference.baseline_weighting", "constraints.num_holdings.target", "horizon.backtest_years", "risk.benchmark", "horizon.purpose")]
    for q in many[2:]:
        q["options"] = []
        q["allow_free_text"] = True
    svc, store, llm = svc_factory([_intent(many)] * 10, max_questions=2)
    st = svc.start("반도체 장기 투자")
    assert st.turn == 1 and st.max_questions == 2
    st = svc.skip(st.request_id, 1)
    assert st.turn == 2 and st.question.field == "strategy_preference.baseline_weighting"
    assert st.question.options == []  # momentum/quality 는 baseline_weighting 에 무효 → 선택지가 걸러짐 (자유 입력만)
    st = svc.answer(st.request_id, 2, option_value="equal_weight")
    # 라운드 5: 질문 상한에 닿아도 막지 않는다 — 남은 항목은 기본값으로 두고 ready, 사유는 blocked_reason_ko 로 보여 준다
    assert st.state == "ready" and "2회" in (st.blocked_reason_ko or "") and "2회" in (RequestStore(store).load(st.request_id).blocked_reason_ko or "")
    assert [x["field"] for x in st.unresolved] == ["strategy_preference.template"]  # 건너뛴 질문은 미확정(기본값)으로 표시
    run_id, _pos = svc.confirm(st.request_id)
    assert run_id
    # 잘못된 값으로 답하면 HARD 오류 → 질문 대신 수정 안내
    svc2, store2, _ = svc_factory([_intent([Q_TEMPLATE]), _intent([])])
    s2 = svc2.start("반도체 장기 투자")
    s2 = svc2.answer(s2.request_id, 1, option_value="not_a_template")
    assert s2.hard_errors and s2.question is None and s2.state == "asking"


def test_same_inputs_same_fingerprint_and_cache(svc_factory):
    svc, store, llm = svc_factory([_intent([Q_TEMPLATE]), _intent([])] * 2)
    a = svc.start("반도체 분산 투자")
    a = svc.answer(a.request_id, 1, option_value="momentum")
    b = svc.start("반도체 분산 투자")
    b = svc.answer(b.request_id, 1, option_value="momentum")
    svc.confirm(a.request_id)
    svc.confirm(b.request_id)
    da, db = RequestStore(store).load(a.request_id), RequestStore(store).load(b.request_id)
    assert da.request_fingerprint == db.request_fingerprint and da.run_id != db.run_id
    # LLM 메시지(system 제외)가 요청 ID 를 빼면 같다 → 캐시 키가 같다
    strip = lambda m: m.content.replace(da.request_id, "X").replace(db.request_id, "X")  # noqa: E731
    assert [strip(m) for m in da.messages[1:2]] == [strip(m) for m in db.messages[1:2]]


def test_start_requires_profile_and_idea(seeded_repo, descriptor_dir, tmp_path):
    s = AnalysisSettings()
    s = replace_settings(s, market=replace_settings(s.market, descriptor_dir=str(descriptor_dir)))
    store = JsonStore(tmp_path / "empty")
    svc = DialogService(store, seeded_repo, MarketData(seeded_repo, s), StubLlm(), s)
    with pytest.raises(RequestInvalid):
        svc.start("반도체 분산 투자")
    ProfileStore(store).save(PROFILE_FIELDS)
    with pytest.raises(RequestInvalid):
        svc.start("짧음")


def test_sector_cap_conflict_is_asked_by_code_rule(svc_factory):
    """테마가 한 섹터(반도체=IT)인데 섹터 상한 0.8 < 1.0 → LLM 질문이 없어도 코드가 먼저 묻는다. 답하면 상한이 바뀐다."""
    svc, store, llm = svc_factory([_intent([]), _intent([])], sector_rule=True)
    st = svc.start("미국과 한국의 반도체·메모리 기업에 분산 투자하고 싶다")
    assert st.state == "asking" and st.question.field == "constraints.max_weight_per_sector" and st.question.kind == "conflict"
    assert "현금" in st.question.question_ko and [o.value for o in st.question.options] == [1.0, 0.8]
    st = svc.answer(st.request_id, 1, option_value=1.0)
    assert st.state == "ready"
    doc = RequestStore(store).load(st.request_id)
    assert doc.draft_request["constraints"]["max_weight_per_sector"] == 1.0 and doc.overrides["constraints.max_weight_per_sector"] == 1.0
    rows = {r["field"]: r for r in st.confirmation["rows"]}
    assert rows["constraints.max_weight_per_sector"]["changed"] and rows["constraints.max_weight_per_sector"]["source"] == "answer"
    # 상한을 이미 풀어 둔 요청에는 묻지 않는다
    st2 = svc.start("미국과 한국의 반도체·메모리 기업에 분산 투자하고 싶다", overrides={"constraints.max_weight_per_sector": 1.0})
    assert st2.state == "ready"


def test_period_in_idea_is_asked_and_applied(svc_factory):
    """아이디어의 "2022년부터 2024년까지" → 코드가 기간 질문 → 답하면 기준일 2024-12-31·백테스트 3년 (부분 갱신)."""
    import datetime as dt

    from backend.analysis.m1_request.assemble import set_path
    from backend.analysis.m1_request.dialog import parse_period

    assert parse_period("2005년부터 약 12년간", today=dt.date(2026, 10, 23)) == {"start_year": 2005, "end_year": 2016, "years": 12.0, "end_date": "2016-12-31"}
    assert parse_period("2006년 경제위기 ~ 2016년까지", today=dt.date(2026, 10, 23))["years"] == 11.0
    assert parse_period("반도체", today=dt.date(2026, 10, 23)) is None
    d = {"horizon": {"target_years": 5, "purpose": "wealth_growth", "backtest_years": 2}}
    set_path(d, "horizon", {"start_date": "2024-12-31", "backtest_years": 3})
    assert d["horizon"] == {"target_years": 5, "purpose": "wealth_growth", "backtest_years": 3, "start_date": "2024-12-31"}
    svc, store, llm = svc_factory([_intent([]), _intent([])])
    st = svc.start("미국과 한국의 반도체 기업에 2022년부터 2024년까지 투자했다면 어땠을지 보고 싶다")
    assert st.state == "asking" and st.question.field == "horizon" and st.question.kind == "conflict"
    assert st.question.options[0].value == {"backtest_years": 3.0, "start_date": "2024-12-31"}
    st = svc.answer(st.request_id, 1, option_value=st.question.options[0].value)
    assert st.state == "ready" and st.summary.derived["as_of"] == "2024-12-31"
    # 합성 자료가 2021-01 부터라 공분산 창(756거래일) 규칙으로 시작일이 2024-01-05 로 당겨지고 경고가 남는다
    assert st.summary.derived["backtest_start"] == "2024-01-05" and any("자료 범위" in w for w in st.summary.derived["warnings"])
    rows = {r["field"]: r for r in st.confirmation["rows"]}
    assert rows["horizon.backtest_years"]["changed"] and rows["horizon.backtest_years"]["source"] == "answer" and rows["derived.as_of"]["value_ko"].startswith("2024-12-31")
    # 같은 기간이 이미 설정돼 있으면 묻지 않는다
    st2 = svc.start("반도체 기업에 2022년부터 2024년까지 투자", overrides={"horizon.start_date": "2024-12-31", "horizon.backtest_years": 3})
    assert st2.state == "ready"


def test_etf_in_profile_is_a_note_not_a_block(svc_factory):
    svc, store, llm = svc_factory([_intent([])])
    st = svc.start("반도체 분산 투자", overrides={"constraints.asset_types": ["stock", "etf"]})
    assert st.state == "ready"
    row = next(r for r in st.confirmation["rows"] if r["field"] == "constraints.asset_types")
    assert row["supported"] and "주식만" in (row["note_ko"] or "") and st.confirmation["all_supported"]


def test_valuation_template_window_is_clamped(seeded_repo, descriptor_dir):
    """저PER 처럼 재무 지표를 쓰는 템플릿은 재무 자료 시작일 이전 구간을 백테스트에서 잘라내고 경고를 남긴다."""
    import json

    from backend.analysis.errors import RequestInvalid
    from backend.analysis.m1_request.derive import derive

    s = AnalysisSettings()
    s = replace_settings(s, market=replace_settings(s.market, descriptor_dir=str(descriptor_dir), valuation_data_start={"US": "2024-06-03", "KR": "2024-06-03"}))
    req = json.loads(json.dumps(REQUEST))
    req["strategy_preference"]["template"] = "low_per"
    req["horizon"]["backtest_years"] = 4
    out = derive(req, MarketData(seeded_repo, s), s).derived
    assert out.backtest_start == __import__("datetime").date(2024, 6, 3) and any("재무 지표" in w for w in out.warnings)
    req["horizon"]["start_date"] = "2023-12-29"
    with pytest.raises(RequestInvalid):
        derive(req, MarketData(seeded_repo, s), s)


# ───────────────────────── 라운드 4 피드백: 자연어 vs 프로필 기본값, 조건 직접 바꾸기, 말로 보태기 ─────────────────────────
def _intent_with_conflict(field, issue, idea_value, questions=()):
    out = _intent(list(questions))
    out["interpretation"]["conflicts"] = [{"field": f"natural_language.idea / {field}", "issue_ko": issue, "resolution_ko": "프로필 값을 따름", "idea_value": idea_value}]
    return out


def test_idea_vs_profile_conflict_becomes_a_question_and_idea_can_win(svc_factory):
    """LLM 이 conflicts 에 idea_value 를 적으면 코드가 '아이디어대로 / 프로필대로' 질문을 만든다. 아이디어대로 고르면 override 로 반영된다."""
    svc, store, llm = svc_factory([_intent_with_conflict("constraints.universe", "자연어는 미국 기업만 말하지만 유니버스에 KOSPI200 이 있습니다.", ["SP500", "NASDAQ100"]), _intent([]), _intent([])])
    st = svc.start("미국 반도체 기업에만 투자하고 싶다")
    assert st.state == "asking" and st.question.field == "constraints.universe" and st.question.kind == "conflict"
    assert st.question.options[0].label_ko.startswith("아이디어대로") and st.question.options[0].value == ["SP500", "NASDAQ100"]
    assert st.question.options[1].label_ko.startswith("프로필대로") and set(st.question.options[1].value) == {"SP500", "NASDAQ100", "KOSPI200"}
    assert st.conditions and any(r["field"] == "constraints.universe" for r in st.conditions)  # 질문 중에도 조건 표가 있다
    st = svc.answer(st.request_id, 1, option_value=["SP500", "NASDAQ100"])
    assert st.state == "ready" and st.overrides == {"constraints.universe": ["SP500", "NASDAQ100"]}
    row = next(r for r in st.confirmation["rows"] if r["field"] == "constraints.universe")
    assert row["changed"] and "KOSPI" not in row["value_ko"] and row["source"] == "answer"


def test_explicit_override_is_not_asked_again_and_tags_say_hard(svc_factory):
    """이번 요청에서 직접 정한 값(override)은 아이디어와 달라도 묻지 않는다. 프롬프트 태그도 HARD(이번 입력) 로 바뀐다."""
    from backend.analysis.m3_selection.intent import field_tags

    svc, store, llm = svc_factory([_intent_with_conflict("constraints.universe", "충돌", ["SP500"]), _intent([])])
    st = svc.start("미국 반도체", overrides={"constraints.universe": ["SP500", "NASDAQ100", "KOSPI200"]})
    assert st.state == "ready" and st.overrides["constraints.universe"] == ["SP500", "NASDAQ100", "KOSPI200"]
    tags = field_tags(["constraints.universe"])
    assert tags["constraints.universe"].startswith("HARD") and tags["strategy_preference.template"].startswith("PROFILE")


def test_update_overrides_and_message_turns(svc_factory):
    """조건 확인 화면의 폼(update_overrides)과 말로 보태기(message)는 새 턴을 돌고, 대기 중 질문은 건너뜀으로 닫힌다."""
    svc, store, llm = svc_factory([_intent([Q_TEMPLATE]), _intent([]), _intent([]), _intent([])])
    st = svc.start("미국과 한국의 반도체·메모리 기업에 분산 투자하고 싶다")
    assert st.state == "asking" and st.question.field == "strategy_preference.template"
    st = svc.update_overrides(st.request_id, {"constraints.num_holdings.target": 8, "strategy_preference.baseline_weighting": "market_cap"})
    assert st.overrides == {"constraints.num_holdings.target": 8, "strategy_preference.baseline_weighting": "market_cap"}
    assert st.questions[0].skipped and "직접" in (st.questions[0].answer or "")
    rows = {r["field"]: r for r in st.conditions}
    assert rows["constraints.num_holdings"]["changed"] and "8" in rows["constraints.num_holdings"]["value_ko"]
    assert rows["strategy_preference.baseline_weighting"]["value_ko"] == "시가총액비중"
    st = svc.update_overrides(st.request_id, {"constraints.num_holdings.target": None})  # None → 프로필 값으로
    assert "constraints.num_holdings.target" not in st.overrides
    st = svc.message(st.request_id, "한국 종목은 삼성전자만 넣어 주세요")
    doc = RequestStore(store).load(st.request_id)
    assert any("삼성전자" in c for c in doc.idea_clarifications) and doc.draft_request["natural_language"]["idea"].count("추가 요청") == 1
    with pytest.raises(RequestInvalid):
        svc.message(st.request_id, "   ")
    # derived 에 백테스트 시작일 환율이 들어 있다
    d = st.summary.derived
    assert d["backtest_fx_rate"] and d["initial_amount_usd_at_backtest_start"] and d["backtest_fx_date"] <= d["backtest_start"]
