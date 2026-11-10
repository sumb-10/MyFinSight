"""예상 매수 주문(proposed.execution)과 리포트 이름 조회·변경·삭제(숨김)."""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from backend.analysis.api.app import API_PREFIX as P
from backend.analysis.api.app import create_analysis_app
from backend.analysis.common.llm import StubLlm
from backend.analysis.m5_backtest_report.execution_orders import estimate_orders, with_execution
from backend.analysis.m5_backtest_report.report_meta import ReportMetaStore, auto_name, name_view
from backend.analysis.m6_tracking.paper_meta import PaperMetaStore
from backend.tests.analysis.test_paper import RID, paper_run  # noqa: F401  # 합성 DB 리포트 fixture


def _doc(basis: str = "forward", fx: float = 1350.0, bps: float | None = 5, a: str = "AAA.KS", b: str = "BBB.KS") -> dict:
    return {
        "header": {"data_as_of": "2026-11-06", "chosen_portfolio_id": "p1", "chosen_label_ko": "선택안"},
        "parameters": {"backtest": {} if bps is None else {"commission_bps": bps}},
        "summary": {"allocation": {"basis": basis, "basis_ko": "분석 기준일 2026-11-06 구성 (낙폭 맞춤안 (주식 90%))", "cash_weight": 0.1, "initial_amount_usd": 10000.0, "fx_rate": fx,
                                   "items": [{"ticker": a, "name": "에이", "weight": 0.6, "usd": 6000.0, "krw": 8100000}, {"ticker": b, "name": "비", "weight": 0.3, "usd": 3000.0, "krw": 4050000}]}},
    }  # fmt: skip


def _balanced(e: dict) -> bool:
    t = e["totals"]
    return t["invested_usd"] + t["fee_usd"] + t["cash_left_usd"] == pytest.approx(e["capital"]["usd"], abs=0.01)


def test_us_orders_are_fractional_to_four_decimals():
    e = estimate_orders(_doc(a="AAA", b="BBB"), {"AAA": 100.0, "BBB": 7000.0})
    a, b = e["items"]
    assert e["share_basis"] == "fractional" and a["share_basis"] == "fractional" and "소수 4째 자리" in e["note_ko"]
    assert a["shares"] == 59.97 and a["cost_usd"] == 5997.0 and a["fee_usd"] == 3.0
    assert b["shares"] == 0.4283 and b["cost_usd"] == 2998.1 and b["fee_usd"] == 1.5
    assert e["totals"]["cash_left_usd"] == 1000.4 and _balanced(e)
    assert all(x["cost_usd"] + x["fee_usd"] <= x["target_usd"] for x in e["items"])


def test_mixed_orders_keep_korean_shares_whole():
    e = estimate_orders(_doc(a="AAA", b="BBB.KQ"), {"AAA": 100.0, "BBB.KQ": 700.0})
    a, b = e["items"]
    assert e["share_basis"] == "mixed" and "한국 주식은 1주 단위" in e["note_ko"]
    assert (a["share_basis"], a["shares"]) == ("fractional", 59.97)
    assert (b["share_basis"], b["shares"]) == ("integer", 4) and isinstance(b["shares"], int) and _balanced(e)


def test_orders_round_down_with_fee_and_keep_totals():
    e = estimate_orders(_doc(), {"AAA.KS": 100.0, "BBB.KS": 7000.0})
    a, b = e["items"]
    assert a["shares"] == 59 and a["cost_usd"] == 5900.0 and a["fee_usd"] == 2.95  # 60주면 수수료까지 6000 을 넘는다
    assert b["shares"] == 0 and b["cost_usd"] == 0.0  # 1주 값이 목표 금액보다 크면 0주
    t = e["totals"]
    assert t["invested_usd"] == 5900.0 and t["fee_usd"] == 2.95 and t["cash_left_usd"] == 4097.05 and t["cash_target_usd"] == 1000.0
    assert t["cash_left_krw"] == round(4097.05 * 1350)
    assert e["as_of"] == "2026-11-06" and e["share_basis"] == "integer" and e["commission_bps"] == 5
    assert e["strategy_label_ko"] == "낙폭 맞춤안 (주식 90%)" and e["fx"]["rate"] == 1350.0 and e["capital"]["usd"] == 10000.0


@pytest.mark.parametrize("doc,prices", [(_doc(), {"AAA.KS": 100.0}), (_doc(basis="backtest"), {"AAA.KS": 1.0, "BBB.KS": 1.0}), (_doc(bps=None), {"AAA.KS": 1.0, "BBB.KS": 1.0}), (_doc(fx=0), {"AAA.KS": 1.0, "BBB.KS": 1.0}), ({}, {})])
def test_orders_absent_when_inputs_missing(doc, prices):
    assert estimate_orders(doc, prices) is None


def test_with_execution_copies_and_keeps_other_proposed_fields():
    doc = {"proposed": {"krw": 1}}
    out = with_execution(doc, {"as_of": "x"})
    assert out["proposed"] == {"contract": "proposed-0.1", "krw": 1, "execution": {"as_of": "x"}} and doc == {"proposed": {"krw": 1}}
    assert with_execution(doc, None) is doc


def test_name_rules():
    assert auto_name(idea=" 반도체에\n투자 ", request_summary="요약", strategy_name="전략", run_id="r") == "반도체에"
    assert auto_name(idea="", request_summary=None, strategy_name="전략", run_id="r") == "전략"
    assert auto_name(idea=None, request_summary=None, strategy_name=None, run_id="r") == "r"
    assert name_view("r", "자동", {"custom_name": "내 이름", "renamed_at": "t"}) == {"report_id": "r", "auto_ko": "자동", "custom_ko": "내 이름", "display_ko": "내 이름", "updated_at": "t"}
    assert name_view("r", "자동", None)["display_ko"] == "자동"


@pytest.fixture
def client(paper_run):  # noqa: F811
    repo, store, s, _ = paper_run
    yield TestClient(create_analysis_app(lambda: repo, store_dir=store.root, settings=s, llm=lambda: StubLlm())), store
    store.write(ReportMetaStore.REL, {})  # 모듈 공유 저장소를 원래대로
    store.write(PaperMetaStore.REL, {})


def test_new_report_stores_execution_and_matches_card(paper_run):  # noqa: F811
    repo, *_ = paper_run
    doc = repo.get_report(RID)["doc"]
    e, a = doc["proposed"]["execution"], doc["summary"]["allocation"]
    assert a["basis"] == "forward" and [x["ticker"] for x in e["items"]] == [x["ticker"] for x in a["items"]]
    assert e["totals"]["invested_usd"] + e["totals"]["fee_usd"] + e["totals"]["cash_left_usd"] == pytest.approx(a["initial_amount_usd"], abs=0.02)
    assert all(x["price_usd"] > 0 and x["cost_usd"] + x["fee_usd"] <= x["target_usd"] + 0.01 for x in e["items"])


def test_old_report_gets_execution_on_read_without_changing_saved_doc(paper_run):  # noqa: F811
    repo, store, s, _ = paper_run
    stored = repo.get_report(RID)["doc"]
    old = {k: v for k, v in stored.items() if k != "proposed"}

    class Repo:
        def __getattr__(self, name):
            return getattr(repo, name)

        def get_report(self, report_id):
            return {"report_id": report_id, "doc": old}

    c = TestClient(create_analysis_app(lambda: Repo(), store_dir=store.root, settings=s, llm=lambda: StubLlm()))
    r = c.get(f"{P}/reports/{RID}")
    assert r.status_code == 200 and r.json()["proposed"]["execution"]["totals"] == stored["proposed"]["execution"]["totals"]
    assert "proposed" not in old


def test_rename_roundtrip_and_validation(client):
    c, _ = client
    auto = c.get(f"{P}/reports/{RID}/name").json()
    assert auto["custom_ko"] is None and auto["display_ko"] == auto["auto_ko"] and auto["updated_at"] is None
    r = c.put(f"{P}/reports/{RID}/name", json={"name": "  내   리포트 "}).json()
    assert r["custom_ko"] == "내 리포트" and r["display_ko"] == "내 리포트" and r["updated_at"]
    row = next(x for x in c.get(f"{P}/reports").json() if x["report_id"] == RID)
    assert row["proposed_name"]["display_ko"] == "내 리포트"
    assert c.put(f"{P}/reports/{RID}/name", json={"name": auto["auto_ko"]}).json()["custom_ko"] is None  # 자동 이름과 같으면 직접 정한 이름이 아니다
    c.put(f"{P}/reports/{RID}/name", json={"name": "다시"})
    assert c.put(f"{P}/reports/{RID}/name", json={"name": None}).json()["display_ko"] == auto["auto_ko"]
    bad = c.put(f"{P}/reports/{RID}/name", json={"name": "가" * 41})
    assert bad.status_code == 422 and bad.json()["error"]["code"] == "REQUEST_INVALID"
    assert c.get(f"{P}/reports/nope/name").status_code == 404 and c.put(f"{P}/reports/nope/name", json={"name": "x"}).status_code == 404


def test_paper_name_follows_report_name(client):
    c, _ = client
    auto = c.get(f"{P}/reports/{RID}/name").json()["auto_ko"]
    d = c.post(f"{P}/paper", json={"report_id": RID, "start_date": "2025-10-31", "strategy_id": "equal_weight", "initial_amount": 3000, "currency": "USD"}).json()
    pid = d["portfolio"]["paper_id"]
    assert d["portfolio"]["name_ko"] == auto and d["summary"]["name_ko"] == auto and d["portfolio"]["strategy"]["name_ko"] != auto  # 전략 이름은 따로 남는다
    c.put(f"{P}/reports/{RID}/name", json={"name": "바뀐 이름"})
    assert next(x for x in c.get(f"{P}/paper").json() if x["paper_id"] == pid)["name_ko"] == "바뀐 이름"
    d = c.get(f"{P}/paper/{pid}").json()
    assert d["portfolio"]["name_ko"] == "바뀐 이름" and d["summary"]["name_ko"] == "바뀐 이름"
    assert c.post(f"{P}/paper/{pid}/stop").json()["summary"]["name_ko"] == "바뀐 이름"
    c.delete(f"{P}/reports/{RID}")
    assert next(x for x in c.get(f"{P}/paper").json() if x["paper_id"] == pid)["name_ko"] == "바뀐 이름"  # 리포트를 숨겨도 모의투자는 그대로


def test_delete_hides_keeps_data_and_can_restore(client, paper_run):  # noqa: F811
    c, store = client
    repo, *_ = paper_run
    assert c.delete(f"{P}/reports/{RID}").json() == {"report_id": RID, "deleted": True}
    assert all(x["report_id"] != RID for x in c.get(f"{P}/reports").json())
    assert c.get(f"{P}/reports/{RID}").status_code == 404 and c.get(f"{P}/reports/{RID}/name").status_code == 404
    assert c.delete(f"{P}/reports/{RID}").status_code == 404
    assert repo.get_report(RID) and repo.get_run_artifact(RID)  # 원본은 남아 있다
    assert c.post(f"{P}/paper/preview", json={"report_id": RID, "start_date": "2025-10-31"}).status_code == 200  # 모의투자 쪽은 영향 없음
    ReportMetaStore(store).restore(RID)
    assert c.get(f"{P}/reports/{RID}").status_code == 200 and any(x["report_id"] == RID for x in c.get(f"{P}/reports").json())
    assert store.read(ReportMetaStore.REL, {}) == {}  # 복구하면 흔적이 남지 않는다


def test_paper_name_custom_and_relink(client):
    c, store = client
    body = {"report_id": RID, "start_date": "2025-10-31", "strategy_id": "equal_weight", "initial_amount": 3000, "currency": "USD"}
    auto = c.get(f"{P}/reports/{RID}/name").json()["auto_ko"]
    n0 = len(c.get(f"{P}/paper").json())
    bad = c.post(f"{P}/paper", json={**body, "name": {"mode": "custom", "name_ko": "  "}})
    assert bad.status_code == 422 and bad.json()["error"]["code"] == "REQUEST_INVALID" and len(c.get(f"{P}/paper").json()) == n0  # 이름이 틀리면 만들지 않는다

    d = c.post(f"{P}/paper", json={**body, "name": {"mode": "custom", "name_ko": " 시가총액  비교용 "}}).json()
    pid = d["portfolio"]["paper_id"]
    assert d["portfolio"]["name_ko"] == d["summary"]["name_ko"] == "시가총액 비교용"
    assert c.get(f"{P}/paper/{pid}/name").json() == {"name_ko": "시가총액 비교용", "mode": "custom", "report_name_ko": auto}

    c.put(f"{P}/reports/{RID}/name", json={"name": "바뀐 이름"})  # 직접 정한 이름은 리포트 이름을 따라가지 않는다
    assert next(x for x in c.get(f"{P}/paper").json() if x["paper_id"] == pid)["name_ko"] == "시가총액 비교용"
    assert c.get(f"{P}/paper/{pid}/name").json()["report_name_ko"] == "바뀐 이름"

    assert c.put(f"{P}/paper/{pid}/name", json={"mode": "linked"}).json() == {"name_ko": "바뀐 이름", "mode": "linked", "report_name_ko": "바뀐 이름"}
    assert c.get(f"{P}/paper/{pid}").json()["summary"]["name_ko"] == "바뀐 이름" and pid not in PaperMetaStore(store).all()

    assert c.put(f"{P}/paper/{pid}/name", json={"mode": "custom", "name_ko": "다시 직접"}).json()["mode"] == "custom"
    assert c.post(f"{P}/paper/{pid}/stop").json()["portfolio"]["name_ko"] == "다시 직접"
    for b in ({"mode": "custom"}, {"mode": "custom", "name_ko": "가" * 41}):
        r = c.put(f"{P}/paper/{pid}/name", json=b)
        assert r.status_code == 422 and r.json()["error"]["code"] == "REQUEST_INVALID"
    assert c.get(f"{P}/paper/{pid}/name").json()["name_ko"] == "다시 직접"  # 틀린 입력은 저장하지 않음
    assert c.put(f"{P}/paper/{pid}/name", json={"mode": "other"}).json()["error"]["code"] == "VALIDATION_ERROR"
    assert c.get(f"{P}/paper/nope/name").status_code == 404 and c.put(f"{P}/paper/nope/name", json={"mode": "linked"}).status_code == 404

    d2 = c.post(f"{P}/paper", json={**body, "name": {"mode": "linked"}}).json()
    assert d2["summary"]["name_ko"] == "바뀐 이름" and d2["portfolio"]["paper_id"] not in PaperMetaStore(store).all()
