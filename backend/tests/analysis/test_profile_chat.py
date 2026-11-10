"""대화형 초기 투자조건 (POST /profile/chat …): 목업과 같은 질문·답 반영·다시 묻기·고치기, 저장 검사, 409·404·422, 보관(7일), 프런트 표와 같은지."""

from __future__ import annotations

import datetime as dt
import json
import re
from pathlib import Path
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

from backend.analysis.api.app import API_PREFIX as P
from backend.analysis.api.app import create_analysis_app
from backend.analysis.api.routers.profile import _draft_errors
from backend.analysis.common.llm import StubLlm
from backend.analysis.common.store import JsonStore
from backend.analysis.errors import NotFound
from backend.analysis.m1_request import profile_chat as pc
from backend.analysis.m1_request.strategy_recommendation import recommend
from backend.analysis.settings import AnalysisSettings

FRONT = Path(__file__).resolve().parents[3] / "Front" / "src"
MOCK_CHAT = FRONT / "mocks" / "data" / "profileChat.ts"
DIAGNOSIS_TS = FRONT / "features" / "profile" / "diagnosis.ts"
DEFAULTS_TS = FRONT / "features" / "profile" / "defaults.ts"

# 위험중립형이 나오는 기본 답 (진단 점수 2+2+2=6). 프런트 profileChat.mock.test.tsx 의 PATH 와 같다.
PATH = {
    "purpose": {"option_value": "wealth_growth"}, "amount": {"option_value": 10_000_000}, "monthly": {"number": 300_000}, "years": {"option_value": 5},
    "loss": {"option_value": 2}, "reaction": {"option_value": 2}, "priority": {"option_value": 2},
    "tendency": {"option_value": "위험중립형"}, "universe": {"option_value": ["SP500"]}, "holdings": {"option_value": 5}, "strategy": {"option_value": "recommended"},
}  # fmt: skip


@pytest.fixture
def client(tmp_path):
    def no_db():
        raise AssertionError("대화형 설정은 DB 를 읽지 않는다")

    return TestClient(create_analysis_app(no_db, store_dir=tmp_path / "store", settings=AnalysisSettings(), llm=lambda: StubLlm()))


def _answer(c, chat_id, qid, **a):
    r = c.post(f"{P}/profile/chat/{chat_id}/answers", json={"question_id": qid, **a})
    assert r.status_code == 200, r.text
    return r.json()


def _answer_all(c, v, until=None, path=PATH):
    views = [v]
    while v["question"] and v["question"]["id"] != until:
        v = _answer(c, v["chat_id"], v["question"]["id"], **path[v["question"]["id"]])
        views.append(v)
    return v, views


def _users(v):
    return [m for m in v["messages"] if m["role"] == "user"]


# ───────────────────────── API: 목업과 같은 흐름 ─────────────────────────
def test_start(client):
    r = client.post(f"{P}/profile/chat")
    assert r.status_code == 200
    v = r.json()
    assert set(v) == {"chat_id", "state", "messages", "question", "progress", "draft", "asked_fields"}  # 프런트 ProposedProfileChat
    assert v["state"] == "asking" and v["progress"] == {"done": 0, "total": 11} and v["asked_fields"] == []
    assert v["question"] == {"id": "purpose", "field_label_ko": "투자 목적", "kind": "choice", "input": None, "allow_skip": False,
                             "options": [{"value": "wealth_growth", "label_ko": "자산 증식"}, {"value": "income", "label_ko": "현금흐름(배당)"},
                                         {"value": "capital_preservation", "label_ko": "원금 보존"}, {"value": "retirement", "label_ko": "은퇴 대비"}]}  # fmt: skip
    assert [(m["id"], m["role"]) for m in v["messages"]] == [("hello", "bot"), ("purpose:q", "bot")]
    assert v["draft"] == pc.DEFAULT_FORM and _draft_errors(client.app.state.services, v["draft"]) == []
    assert v["chat_id"] != client.post(f"{P}/profile/chat").json()["chat_id"]


def test_full_path_review_and_save(client):
    v, views = _answer_all(client, client.post(f"{P}/profile/chat").json())
    assert v["state"] == "review" and v["question"] is None and v["progress"] == {"done": 11, "total": 11}
    d = v["draft"]
    assert d["capital"] == {**pc.DEFAULT_FORM["capital"], "initial_amount": 10_000_000, "monthly_contribution": 300_000, "currency": "KRW"}
    assert d["horizon"]["purpose"] == "wealth_growth" and d["horizon"]["target_years"] == 5
    assert d["diagnosis"] == {"answers": {"loss": 2, "reaction": 2, "priority": 2}, "computed_tendency": "위험중립형", "final_tendency": "위험중립형", "memo": ""}
    assert d["risk"] == {**pc.DEFAULT_FORM["risk"], "risk_tolerance": "moderate", "max_drawdown_tolerance": 0.2, "loss_reaction": "hold"}
    assert d["constraints"]["universe"] == ["SP500"] and d["constraints"]["num_holdings"] == {"target": 5, "min": 4, "max": 6}
    assert d["constraints"]["max_weight_per_stock"] == 0.25
    assert d["strategy_preference"] == recommend("위험중립형")["recommended"] == {"template": "quality", "baseline_weighting": "equal_weight", "use_news_tilt": True}
    assert set(v["asked_fields"]) >= {"capital.initial_amount", "capital.monthly", "tendency", "constraints.universe", "strategy.template", "strategy.weighting"}
    assert "risk.benchmark" not in v["asked_fields"]  # 묻지 않은 항목은 기본값
    assert v["messages"][-1] == {"id": "done", "role": "bot", "text_ko": pc.DONE_TEXT}
    assert len(_users(v)) == 11 and all(m["editable"] for m in _users(v))
    # 말풍선 id 는 응답마다 그대로 (프런트 React key): 앞 응답의 말풍선은 다음 응답의 앞부분과 같다
    for a, b in zip(views, views[1:], strict=False):
        assert b["messages"][: len(a["messages"])] == a["messages"]
    assert len({m["id"] for m in v["messages"]}) == len(v["messages"])
    # 저장은 기존 PUT /profile. 투자조건이 있는 사용자도 대화로 다시 정하면 새 버전
    assert client.put(f"{P}/profile", json={**d, "note": "첫 등록"}).json()["current_version"] == 1
    v2, _ = _answer_all(client, client.post(f"{P}/profile/chat").json())
    assert client.put(f"{P}/profile", json={**v2["draft"], "note": "대화로 다시 설정"}).json()["current_version"] == 2


def test_invalid_answers_retry_with_200(client):
    """맞지 않는 답은 400 이 아니라 200 + 봇의 다시 묻는 말풍선. 답은 저장하지 않는다."""
    v = client.post(f"{P}/profile/chat").json()
    cid = v["chat_id"]

    def retry_text(qid, **a):
        r = _answer(client, cid, qid, **a)
        assert r["question"]["id"] == qid and r["progress"]["done"] == v_done[0], a
        assert r["messages"][-1]["id"] == f"{qid}:retry" and r["messages"][-1]["role"] == "bot"
        return r["messages"][-1]["text_ko"]

    v_done = [0]
    assert retry_text("purpose", option_value="growth") == "아래 보기 중에서 골라 주세요."
    assert retry_text("purpose", skip=True) == "이 질문은 꼭 답해 주셔야 해요. 아래에서 골라 주세요."
    assert retry_text("purpose") == "아래 보기 중에서 골라 주세요."
    v = _answer(client, cid, "purpose", option_value="income")
    assert not any(m["id"].endswith(":retry") for m in v["messages"])  # 맞는 답을 주면 안내가 사라진다
    v_done[0] = 1
    assert retry_text("amount", number=1_000) == "10만원 이상 100억원 이하로 알려 주세요."
    assert retry_text("amount", number=20_000_000_000) == "10만원 이상 100억원 이하로 알려 주세요."
    assert retry_text("amount", number="5000000") == "10만원 이상 100억원 이하로 알려 주세요."  # 문자열은 숫자가 아니다
    assert retry_text("amount", option_value=True) == "10만원 이상 100억원 이하로 알려 주세요."
    v = _answer(client, cid, "amount", number=2_500_000)
    assert v["question"]["id"] == "monthly" and v["draft"]["capital"]["initial_amount"] == 2_500_000
    assert _users(v)[-1]["text_ko"] == "250만원"
    v = _answer(client, cid, "monthly", option_value=0)
    assert _users(v)[-1]["text_ko"] == "추가 투자는 없어요"
    v_done[0] = 3
    assert retry_text("years", number=2.5) == "정수로 알려 주세요."
    assert retry_text("years", number=11) == "1년 이상 10년 이하로 알려 주세요."
    v = _answer(client, cid, "years", number=7.0)
    assert v["draft"]["horizon"]["target_years"] == 7 and _users(v)[-1]["text_ko"] == "7년"  # 「7.0년」이 아니다
    v_done[0] = 4
    assert retry_text("loss", option_value=True) == "아래 보기 중에서 골라 주세요."  # JS 처럼 true ≠ 1
    assert retry_text("loss", option_value=4) == "아래 보기 중에서 골라 주세요."
    v = _answer(client, cid, "loss", option_value=1.0)
    assert v["draft"]["diagnosis"]["answers"] == {"loss": 1}
    v = _answer(client, cid, "reaction", option_value=0)
    v = _answer(client, cid, "priority", option_value=0)
    v_done[0] = 7
    assert retry_text("tendency", option_value="중립형") == "아래 보기 중에서 골라 주세요."
    v = _answer(client, cid, "tendency", option_value="안정형")
    v_done[0] = 8
    assert retry_text("universe", option_value=[]) == "하나 이상 골라 주세요."
    assert retry_text("universe", option_value="SP500") == "하나 이상 골라 주세요."
    assert retry_text("universe", option_value=["SP500", "DOW30"]) == "하나 이상 골라 주세요."
    v = _answer(client, cid, "universe", option_value=["KOSPI200", "SP500", "KOSPI200"])
    assert v["draft"]["constraints"]["universe"] == ["KOSPI200", "SP500"]  # 같은 보기는 한 번만 (저장 스키마는 중복을 받지 않는다)
    v_done[0] = 9
    assert retry_text("holdings", number=2) == "3개 이상 30개 이하로 알려 주세요."
    v = _answer(client, cid, "holdings", number=3)
    assert v["draft"]["constraints"]["num_holdings"] == {"target": 3, "min": 2, "max": 4} and v["draft"]["constraints"]["max_weight_per_stock"] == 0.5
    v_done[0] = 10
    assert retry_text("strategy", option_value="value") == "아래 보기 중에서 골라 주세요."
    v = _answer(client, cid, "strategy", option_value="low_per")
    assert v["state"] == "review" and v["draft"]["strategy_preference"]["template"] == "low_per"
    assert v["asked_fields"][-1] == "strategy.template" and "strategy.weighting" not in v["asked_fields"]
    assert client.put(f"{P}/profile", json=v["draft"]).status_code == 200


def test_not_current_question_409_and_missing_chat_404(client):
    v = client.post(f"{P}/profile/chat").json()
    r = client.post(f"{P}/profile/chat/{v['chat_id']}/answers", json={"question_id": "amount", "number": 1_000_000})
    assert r.status_code == 409 and r.json()["error"]["code"] == "CONFLICT" and r.json()["error"]["details"] == {"current_question_id": "purpose"}
    done, _ = _answer_all(client, v)
    r = client.post(f"{P}/profile/chat/{v['chat_id']}/answers", json={"question_id": "strategy", "option_value": "recommended"})
    assert r.status_code == 409 and r.json()["error"]["details"] == {"current_question_id": None}  # 요약 단계에는 답할 질문이 없다
    for cid in ("chat_20261110_120000_abcdef", "profile", "chat_x", "chat_20261110_120000_ABCDEF"):
        for path, body in (("answers", {"question_id": "purpose", "option_value": "income"}), ("rewind", {"question_id": "purpose"})):
            r = client.post(f"{P}/profile/chat/{cid}/{path}", json=body)
            assert r.status_code == 404 and r.json()["error"]["code"] == "NOT_FOUND", (cid, path)
    r = client.post(f"{P}/profile/chat/{v['chat_id']}/answers", json={"option_value": "income"})
    assert r.status_code == 422  # question_id 없는 본문은 형식 오류


def test_override_tendency_follows_recommendation(client):
    v, _ = _answer_all(client, client.post(f"{P}/profile/chat").json(), until="tendency")
    opts = v["question"]["options"]
    assert [o["value"] for o in opts] == list(pc.TENDENCIES)
    assert [o["value"] for o in opts if o["recommended"]] == ["위험중립형"] and opts[2]["label_ko"] == "위험중립형 (진단 결과)"
    v = _answer(client, v["chat_id"], "tendency", option_value="안정형")
    assert _users(v)[-1]["text_ko"] == "안정형으로 할게요"
    strat = _answer(client, v["chat_id"], "universe", option_value=["SP500"])
    strat = _answer(client, v["chat_id"], "holdings", option_value=10)
    first = strat["question"]["options"][0]
    rec = recommend("안정형")
    assert first == {"value": "recommended", "label_ko": "추천: 배당을 많이 주는 기업(고배당) · 전체 투자 위험을 줄이도록 비중 계산(최소분산)",
                     "help_ko": rec["reasons_ko"][0], "recommended": True}  # fmt: skip
    assert [o["value"] for o in strat["question"]["options"][1:]] == list(pc.TEMPLATE_ORDER)
    v = _answer(client, v["chat_id"], "strategy", option_value="recommended")
    assert v["draft"]["risk_type_overridden"] is True and v["draft"]["risk"]["risk_tolerance"] == "conservative"
    assert v["draft"]["diagnosis"]["computed_tendency"] == "위험중립형" and v["draft"]["diagnosis"]["final_tendency"] == "안정형"
    assert v["draft"]["risk_type_computed"] == "moderate"
    assert v["draft"]["strategy_preference"] == rec["recommended"]


def test_rewind_keeps_later_answers(client):
    v, _ = _answer_all(client, client.post(f"{P}/profile/chat").json())
    ids = [m["id"] for m in v["messages"]]
    r = client.post(f"{P}/profile/chat/{v['chat_id']}/rewind", json={"question_id": "amount"}).json()
    assert r["state"] == "asking" and r["question"]["id"] == "amount" and r["progress"]["done"] == 10
    assert len(_users(r)) == 1  # 뒤의 말풍선은 지금 질문에 답할 때까지 숨긴다
    assert r["messages"][-1] == {"id": "amount:keep", "role": "bot", "question_id": "amount",
                                 "text_ko": "이 질문만 다시 답해 주세요. 뒤에 답한 9개는 그대로 두었다가 답하시면 다시 보여 드릴게요."}  # fmt: skip
    assert r["draft"]["constraints"]["universe"] == ["SP500"]  # 뒤의 답은 초안에 남아 있다
    back = _answer(client, v["chat_id"], "amount", option_value=30_000_000)
    assert back["state"] == "review" and back["draft"]["capital"]["initial_amount"] == 30_000_000 and back["draft"]["capital"]["monthly_contribution"] == 300_000
    assert len(_users(back)) == 11 and [m["id"] for m in back["messages"]] == ids
    # 요약 단계에서 고치지 않은 질문을 되감아도 그 질문만 다시 묻는다
    r = client.post(f"{P}/profile/chat/{v['chat_id']}/rewind", json={"question_id": "strategy"}).json()
    assert r["question"]["id"] == "strategy" and r["progress"]["done"] == 10 and "strategy:keep" not in [m["id"] for m in r["messages"]]
    r = client.post(f"{P}/profile/chat/{v['chat_id']}/rewind", json={"question_id": "nope"})
    assert r.status_code == 422 and r.json()["error"]["code"] == "REQUEST_INVALID"


def test_zero_start_path(client):
    """처음 투자금 0원 (이슈 #14 의 3번): 금액 보기로만 고르고, 그러면 월 적립은 0원을 받지 않는다. 저장까지 된다."""
    v, _ = _answer_all(client, client.post(f"{P}/profile/chat").json(), until="amount")
    assert v["question"]["options"][-1] == {"value": 0, "label_ko": pc.ZERO_START_LABEL, "help_ko": pc.ZERO_START_HELP}
    assert v["question"]["input"]["min"] == 100_000  # 직접 입력은 10만원부터 — 0원은 보기로
    r = _answer(client, v["chat_id"], "amount", option_value=0)
    assert r["question"]["id"] == "monthly" and r["draft"]["capital"]["initial_amount"] == 0 and _users(r)[-1]["text_ko"] == pc.ZERO_START_SAY
    assert r["messages"][-1]["text_ko"].startswith(pc.ZERO_MONTHLY_ASK) and 0 not in [o["value"] for o in r["question"]["options"]]
    r = _answer(client, v["chat_id"], "monthly", number=0)
    assert r["question"]["id"] == "monthly" and r["messages"][-1] == {"id": "monthly:retry", "role": "bot", "text_ko": pc.ZERO_NEEDS_MONTHLY, "question_id": "monthly"}
    r, _ = _answer_all(client, r)
    assert r["state"] == "review" and (r["draft"]["capital"]["initial_amount"], r["draft"]["capital"]["monthly_contribution"]) == (0, 300_000)
    assert client.put(f"{P}/profile", json={**r["draft"], "note": "첫 등록"}).status_code == 200


def test_rewind_amount_to_zero_reasks_monthly_none(client):
    """요약에서 금액을 0원으로 고치면, 「추가 투자 없음」이던 월 적립만 지워 다시 묻는다 (적립이 있으면 그대로)."""
    v, _ = _answer_all(client, client.post(f"{P}/profile/chat").json(), path={**PATH, "monthly": {"option_value": 0}})
    assert v["state"] == "review" and v["draft"]["capital"]["monthly_contribution"] == 0
    client.post(f"{P}/profile/chat/{v['chat_id']}/rewind", json={"question_id": "amount"})
    r = _answer(client, v["chat_id"], "amount", option_value=0)
    assert r["question"]["id"] == "monthly" and r["progress"]["done"] == 10 and "monthly" not in [m["question_id"] for m in _users(r)]
    r = _answer(client, v["chat_id"], "monthly", option_value=500_000)
    assert r["state"] == "review" and r["draft"]["capital"]["monthly_contribution"] == 500_000
    client.post(f"{P}/profile/chat/{v['chat_id']}/rewind", json={"question_id": "amount"})
    r = _answer(client, v["chat_id"], "amount", option_value=0)
    assert r["state"] == "review"  # 적립이 있으면 다시 묻지 않는다


def test_rewind_diagnosis_reasks_tendency(client):
    v, _ = _answer_all(client, client.post(f"{P}/profile/chat").json())
    r = client.post(f"{P}/profile/chat/{v['chat_id']}/rewind", json={"question_id": "loss"}).json()
    assert r["question"]["id"] == "loss" and r["progress"]["done"] == 9  # 진단 답과 「성향 확인」 둘 다 지운다
    r = _answer(client, v["chat_id"], "loss", option_value=3)
    assert r["question"]["id"] == "tendency"
    assert r["draft"]["diagnosis"]["computed_tendency"] == "적극투자형"  # 4+2+2=8
    assert [o["value"] for o in r["question"]["options"] if o["recommended"]] == [r["draft"]["diagnosis"]["computed_tendency"]]
    r = _answer(client, v["chat_id"], "tendency", option_value="적극투자형")
    assert r["state"] == "review" and r["draft"]["strategy_preference"] == recommend("적극투자형")["recommended"]  # 추천은 성향에서 다시 계산


# ───────────────────────── 요약 전 저장 검사 ─────────────────────────
def test_review_check_blocks_last_answer():
    st = {"chat_id": "chat_x", "answers": {}, "error": None}
    for q in pc.CHAT_QUESTIONS[:-1]:
        st = pc.answer_chat(st, PATH[q.id], check=lambda _d: ["불러지면 안 됨"])  # 요약 전까지는 검사하지 않는다
        assert st["error"] is None
    calls = []
    out = pc.answer_chat(st, PATH["strategy"], check=lambda d: calls.append(d) or ["종목당 상한: 1 이하여야 합니다"])
    assert len(calls) == 1 and calls[0]["strategy_preference"]["template"] == "quality"  # 이 답이 반영된 초안을 검사한다
    assert "strategy" not in out["answers"]  # 답을 받지 않는다
    v = pc.chat_view(out)
    assert v["state"] == "asking" and v["question"]["id"] == "strategy"
    assert v["messages"][-1]["id"] == "strategy:retry" and "종목당 상한: 1 이하여야 합니다" in v["messages"][-1]["text_ko"]
    assert pc.chat_view(pc.answer_chat(st, PATH["strategy"], check=lambda _d: []))["state"] == "review"


@pytest.mark.parametrize("tendency", pc.TENDENCIES)
def test_review_drafts_pass_put_profile_checks(tmp_path, tendency):
    """대화로 만들 수 있는 초안은 PUT /profile 검사를 모두 통과한다 (성향 × 종목 기준 × 종목 수·금액·지수의 끝값)."""
    sv = SimpleNamespace(store=JsonStore(tmp_path))
    for strategy in ("recommended", *pc.TEMPLATE_ORDER):
        for holdings, amount, monthly, universe in ((3, 100_000, 100_000_000, ["KOSPI200"]), (30, 10_000_000_000, 0, ["SP500", "NASDAQ100", "KOSPI200"]),
                                                    (5, 0, 10_000, ["SP500"])):  # 마지막: 0원 시작 + 최소 적립
            path = {**PATH, "tendency": {"option_value": tendency}, "strategy": {"option_value": strategy}, "holdings": {"number": holdings},
                    "amount": {"number": amount}, "monthly": {"number": monthly}, "universe": {"option_value": universe}}  # fmt: skip
            st = {"chat_id": "chat_x", "answers": {}, "error": None}
            for q in pc.CHAT_QUESTIONS:
                st = pc.answer_chat(st, path[q.id], check=lambda d: _draft_errors(sv, d))
            v = pc.chat_view(st)
            assert v["state"] == "review", (strategy, holdings, v["messages"][-1])


# ───────────────────────── 보관 ─────────────────────────
def test_prune_old_chats_on_start(tmp_path):
    store = JsonStore(tmp_path)
    chats = pc.ProfileChatStore(store)
    t0 = dt.datetime(2026, 11, 1, 9, 0, tzinfo=dt.UTC)
    old = chats.start(now=t0)
    recent = chats.start(now=t0 + dt.timedelta(days=1))
    touched = chats.start(now=t0)
    with chats.locked():
        chats.save(pc.answer_chat(chats.load(touched["chat_id"]), PATH["purpose"]), now=t0 + dt.timedelta(days=3))  # 답하면 보관 기간이 다시 시작된다
    store.write(f"{chats.DIR}/chat_20260101_000000_000000.json", {"broken": True})  # 읽을 수 없는 파일은 건드리지 않는다
    new = chats.start(now=t0 + dt.timedelta(days=7, seconds=1))
    left = sorted(p.stem for p in store.path(chats.DIR).glob("chat_*.json"))
    assert old["chat_id"] not in left
    assert {recent["chat_id"], touched["chat_id"], new["chat_id"], "chat_20260101_000000_000000"} == set(left)
    with pytest.raises(NotFound, match="없습니다"):
        chats.load(old["chat_id"])
    saved = chats.load(new["chat_id"])
    assert saved["user_id"] == "default" and saved["answers"] == {} and saved["created_at"] == saved["updated_at"]


def test_chat_is_stored_as_answers_only(client):
    v = client.post(f"{P}/profile/chat").json()
    _answer(client, v["chat_id"], "purpose", option_value="income")
    _answer(client, v["chat_id"], "amount", number=1)  # 다시 묻기 안내도 저장된다 (새로고침해도 같은 말풍선)
    root = Path(client.app.state.services.store.root)
    raw = json.loads((root / "profile_chats" / f"{v['chat_id']}.json").read_text(encoding="utf-8"))
    assert raw["answers"] == {"purpose": {"v": "income"}} and raw["error"]["question_id"] == "amount"
    assert pc.chat_view(raw)["messages"][-1]["id"] == "amount:retry"


# ───────────────────────── 계산·표시 ─────────────────────────
def test_holdings_and_money_text():
    assert pc.holdings_for(10) == {"num_holdings": {"target": 10, "min": 8, "max": 12}, "max_weight_per_stock": 0.15, "max_weight_per_sector": 0.4}
    assert pc.holdings_for(3) == {"num_holdings": {"target": 3, "min": 2, "max": 4}, "max_weight_per_stock": 0.5, "max_weight_per_sector": 0.5}
    assert [pc.won(x) for x in (100_000, 10_000_000, 123_456_789, 10_000_000_000, 0, 1234.5, 5_000_000.0)] == [
        "10만원", "1,000만원", "1억 2,345만 6,789원", "100억원", "0원", "1,234.5원", "500만원"]  # fmt: skip
    assert [pc.compute_tendency({"a": s}) for s in (0, 2, 3, 6, 7, 10, 12)] ==["안정형", "안정형", "안정추구형", "위험중립형", "적극투자형", "공격투자형", "공격투자형"]


# ───────────────────────── 프런트와 같은 표 ─────────────────────────
def _ts(path: Path) -> str:
    return re.sub(r"(?<=\d)_(?=\d)", "", path.read_text(encoding="utf-8"))  # 10_000 → 10000


@pytest.mark.skipif(not DIAGNOSIS_TS.exists(), reason="프런트 소스가 없는 배포본")
def test_diagnosis_same_as_front():
    """성향 진단 문항·보기·점수(·손실 감내·대응)와 성향 설명이 프런트 diagnosis.ts 와 같다."""
    src = _ts(DIAGNOSIS_TS)
    assert "export const TENDENCIES: Tendency[] = " + json.dumps(list(pc.TENDENCIES), ensure_ascii=False).replace('","', '", "') in src
    assert "Math.floor(score / 2.3)" in src
    assert re.findall(r'\{ id: "(\w+)", question:', src) == [q["id"] for q in pc.DIAGNOSIS]
    for q in pc.DIAGNOSIS:
        assert f'id: "{q["id"]}", question: "{q["question"]}"' in src
        for o in q["options"]:
            extra = (f", loss: {o['loss']}" if "loss" in o else "") + (f', reaction: "{o["reaction"]}"' if "reaction" in o else "")
            assert f'{{ label: "{o["label"]}", score: {o["score"]}{extra} }}' in src, o
    for t, text in pc.TENDENCY_HELP.items():
        assert f'{t}: "{text}"' in src


@pytest.mark.skipif(not DEFAULTS_TS.exists(), reason="프런트 소스가 없는 배포본")
def test_defaults_same_as_front():
    body = _ts(DEFAULTS_TS).split("export const DEFAULT_FORM: ProfileFields = ", 1)[1].strip()
    body = re.sub(r"([{,]\s*)([A-Za-z_]\w*)\s*:", r'\1"\2":', body)  # 키에 따옴표
    body = re.sub(r",(\s*[}\]])", r"\1", body)  # 끝 쉼표
    assert json.loads(body) == pc.DEFAULT_FORM


@pytest.mark.skipif(not MOCK_CHAT.exists(), reason="프런트 소스가 없는 배포본")
def test_chat_questions_same_as_front_mock():
    """질문 id·순서, 이름, 고정 보기, 직접 입력 범위, 정해진 말풍선이 목업 대화(profileChat.ts)와 같다."""
    src = _ts(MOCK_CHAT)
    table = src.split("export const CHAT_QUESTIONS", 1)[1].split("\n]\n", 1)[0]
    order = [m[0] or pc.DIAGNOSIS[int(m[1])]["id"] for m in re.findall(r'\bid: "(\w+)"|diagQ\((\d)\)', table)]
    assert order == list(pc.QUESTION_IDS)
    for q in pc.CHAT_QUESTIONS:
        if q.id in {d["id"] for d in pc.DIAGNOSIS}:
            assert q.label == "투자성향 진단" and 'label: "투자성향 진단"' in src
            continue
        block = table.split(f'id: "{q.id}"', 1)[1].split('\n  {', 1)[0]
        assert f'label: "{q.label}", kind: "{q.kind}"' in block, q.id
        if q.input:
            i = q.input
            assert f'input: {{ min: {i["min"]}, max: {i["max"]}, step: {i["step"]}, unit_ko: "{i["unit_ko"]}" }}' in block, q.id
        else:
            assert "input:" not in block, q.id
        if q.id not in ("tendency", "strategy"):  # 보기가 고정된 질문
            values = [o["value"] for o in q.options(pc.DEFAULT_FORM)]
            assert json.dumps(values, ensure_ascii=False).replace('","', '", "') in block, q.id
    for text in (pc.GREETING, pc.DONE_TEXT, "아래 보기 중에서 골라 주세요.", "하나 이상 골라 주세요.", "정수로 알려 주세요.", "이 질문은 꼭 답해 주셔야 해요. 아래에서 골라 주세요.",
                 pc.ZERO_START_LABEL, pc.ZERO_START_HELP, pc.ZERO_START_SAY, pc.ZERO_MONTHLY_ASK, pc.ZERO_NEEDS_MONTHLY):
        assert text in src, text
    assert "Object.fromEntries(QUESTIONS.map((q) => [q.id, [\"tendency\"]]))" in src  # 고친 답에 기대는 질문 (DEPENDENTS)
