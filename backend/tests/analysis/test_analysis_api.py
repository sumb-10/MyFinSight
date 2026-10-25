"""B5: 서비스 API — 프로필, 대화 흐름(생성→답→확정), 실행 상태, 워커 1회 후 결과 조회, 오류 봉투."""

from __future__ import annotations

import datetime as dt
import os

import pytest
from fastapi.testclient import TestClient

from backend.analysis.api.app import API_PREFIX, create_analysis_app
from backend.analysis.common.llm import StubLlm
from backend.analysis.common.store import JsonStore
from backend.analysis.executor import worker
from backend.analysis.settings import AnalysisSettings, replace_settings
from backend.db import open_repository
from backend.tests.analysis.conftest import seed_repository
from backend.tests.analysis.test_dialog import PROFILE_FIELDS, Q_TEMPLATE, _intent

P = API_PREFIX


@pytest.fixture(scope="module")
def api(descriptor_dir, tmp_path_factory):
    tmp = tmp_path_factory.mktemp("api")
    repo = open_repository(f"sqlite:///{tmp / 'api.db'}", clock=lambda: dt.datetime(2026, 1, 5, tzinfo=dt.UTC))
    seed_repository(repo)
    s = AnalysisSettings()
    s = replace_settings(s, portfolio=replace_settings(s.portfolio, lookback_days=252, min_history_days_for_model=120),
                         market=replace_settings(s.market, valuation_max_staleness_days=10, descriptor_dir=str(descriptor_dir)),
                         dialog=replace_settings(s.dialog, ask_sector_cap_conflict=False))  # 이 테스트는 LLM 질문 흐름만 본다 (코드 규칙 질문은 test_dialog)  # fmt: skip
    store_dir = tmp / "store"
    answers = {"02_intent": [_intent([Q_TEMPLATE]), _intent([])]}
    app = create_analysis_app(lambda: repo, store_dir=store_dir, settings=s, llm=lambda: StubLlm(answers), cors_origins=["http://localhost:5173"])
    os.environ["ANALYSIS_OUTPUT_DIR"] = str(tmp / "out")
    client = TestClient(app, raise_server_exceptions=False)
    yield client, repo, JsonStore(store_dir), s
    os.environ.pop("ANALYSIS_OUTPUT_DIR", None)


def test_health_and_options(api):
    client, *_ = api
    h = client.get(f"{P}/health").json()
    assert h["ok"] and h["db"]["latest_trading_day"] == "2025-12-31" and h["queue_length"] == 0
    o = client.get(f"{P}/meta/options").json()
    assert "KOSPI200" in o["universes"] and o["max_questions"] == 5 and o["latest_trading_day"] == "2025-12-31"


def test_profile_validation_and_versions(api):
    client, *_ = api
    r = client.get(f"{P}/profile")
    assert r.status_code == 404 and r.json()["error"]["code"] == "NOT_FOUND"
    bad = {**PROFILE_FIELDS, "constraints": {**PROFILE_FIELDS["constraints"], "max_weight_per_sector": 0.1}}
    r = client.put(f"{P}/profile", json=bad)
    assert r.status_code == 422 and r.json()["error"]["code"] == "PROFILE_INVALID" and "constraints" in str(r.json()["error"]["fields"])
    r = client.put(f"{P}/profile", json={**PROFILE_FIELDS, "note": "첫 등록"})
    assert r.status_code == 200 and r.json()["current_version"] == 1
    r = client.put(f"{P}/profile", json=PROFILE_FIELDS)
    assert r.json()["current_version"] == 2 and len(r.json()["versions"]) == 2
    assert client.get(f"{P}/profile").json()["profile"]["capital"]["initial_amount"] == 20_000_000
    r = client.put(f"{P}/profile", json={"capital": {}})
    assert r.status_code == 422 and r.json()["error"]["code"] == "VALIDATION_ERROR"


def test_dialog_flow_run_and_report_endpoints(api):
    client, repo, store, s = api
    r = client.post(f"{P}/requests", json={"idea": "미국과 한국의 반도체·메모리 기업에 분산 투자하고 싶다"})
    assert r.status_code == 200, r.text
    st = r.json()
    rid = st["request_id"]
    assert st["state"] == "asking" and st["question"]["field"] == "strategy_preference.template" and st["turn"] == 1
    r = client.post(f"{P}/requests/{rid}/confirm")
    assert r.status_code == 409 and r.json()["error"]["code"] == "DIALOG_NOT_READY"
    r = client.post(f"{P}/requests/{rid}/answer", json={"seq": 1, "option_value": "momentum"})
    st = r.json()
    assert st["state"] == "ready" and st["confirmation"]["rows"] and st["summary"]["derived"]["as_of"] == "2025-12-31"
    assert client.get(f"{P}/requests/{rid}").json()["state"] == "ready"
    r = client.post(f"{P}/requests/{rid}/confirm")
    assert r.status_code == 200 and r.json()["queue_position"] == 1
    run_id = r.json()["run_id"]
    assert client.post(f"{P}/requests/{rid}/confirm").json()["run_id"] == run_id  # 멱등
    r = client.get(f"{P}/runs/{run_id}").json()
    assert r["status"] == "queued" and r["queue_position"] == 1 and len(r["buckets"]) == 5 and all(b["status"] == "QUEUED" for b in r["buckets"])
    assert client.get(f"{P}/reports/{run_id}").status_code == 404 and client.get(f"{P}/reports/{run_id}").json()["error"]["code"] == "REPORT_NOT_READY"
    # 워커 1회 (API 와 같은 repo·store)
    status = worker.run_once(repo=repo, store=store, settings=s, llm=StubLlm())
    assert status in ("success", "partial")
    r = client.get(f"{P}/runs/{run_id}").json()
    assert r["status"] == status and r["queue_position"] is None and r["finished_at"]
    assert {b["id"]: b["status"] for b in r["buckets"]}["backtest"] in ("SUCCESS", "PARTIAL")
    assert any(s_["step"] == "13_results" and s_["status"] in ("SUCCESS", "PARTIAL") for s_ in r["steps"])
    res = client.get(f"{P}/reports/{run_id}/results").json()
    assert res["run_id"] == run_id and res["validation"]["chosen_id"]
    doc = client.get(f"{P}/reports/{run_id}").json()
    assert [s["id"] for s in doc["sections"]] == ["verdict", "market", "companies", "construction", "performance", "assumptions", "references"]
    assert doc["run_id"] == run_id and r["report_id"] == run_id
    lst = client.get(f"{P}/reports").json()
    assert lst and lst[0]["run_id"] == run_id and lst[0]["request_id"] == rid and lst[0]["as_of"] == "2025-12-31"
    assert client.get(f"{P}/runs").json()[0]["run_id"] == run_id
    assert client.get(f"{P}/requests").json()[0]["status"] == "confirmed"
    # 재분석 요청은 새 대화 (mode=rerun)
    r = client.post(f"{P}/reports/{run_id}/rerun")
    assert r.status_code == 200 and r.json()["mode"] == "rerun" and r.json()["base_report_id"] == run_id
    # 취소: 대기 중 실행은 즉시 cancelled
    rid2 = r.json()["request_id"]
    st2 = client.post(f"{P}/requests/{rid2}/answer", json={"seq": 1, "option_value": "momentum"}).json()
    if st2["state"] == "ready":
        run2 = client.post(f"{P}/requests/{rid2}/confirm").json()["run_id"]
        assert client.post(f"{P}/runs/{run2}/cancel").json()["status"] == "cancelled"
    assert client.get(f"{P}/runs/run_nope").status_code == 404
    assert client.get(f"{P}/health").json()["worker"]["running_run_id"] is None


def test_report_v2_endpoints(api):
    """라운드 4: 근거 색인 페이지·한 건·체크포인트·전체 시계열·gzip."""
    client, repo, store, s = api
    run_id = client.get(f"{P}/reports").json()[0]["run_id"]
    doc = client.get(f"{P}/reports/{run_id}").json()
    assert doc["doc_version"] == 2 and doc["summary"]["verdict"]["label_ko"] and doc["evidence_summary"]["total"] >= doc["evidence_summary"]["cited"]
    # gzip
    r = client.get(f"{P}/reports/{run_id}", headers={"accept-encoding": "gzip"})
    assert r.headers.get("content-encoding") == "gzip"
    # 근거 색인 페이지
    ev = client.get(f"{P}/reports/{run_id}/evidence", params={"limit": 5}).json()
    assert ev["total"] == doc["evidence_summary"]["total"] == ev["index_total"] and len(ev["items"]) == 5 and ev["limit"] == 5 and ev["by_kind"]
    news = client.get(f"{P}/reports/{run_id}/evidence", params={"kind": "news", "limit": 200}).json()
    assert news["total"] == ev["by_kind"].get("news", 0) and all(i["kind"] == "news" for i in news["items"])
    assert all(a["published_at"] >= b["published_at"] for a, b in zip(news["items"], news["items"][1:], strict=False))  # 최신순
    dc = client.get(f"{P}/reports/{run_id}/evidence", params={"kind": "disclosure", "limit": 200}).json()
    assert dc["total"] == ev["by_kind"].get("disclosure", 0) and all(i["event_label_ko"] for i in dc["items"])
    tk = news["items"][0]["tickers"][0]
    by_t = client.get(f"{P}/reports/{run_id}/evidence", params={"ticker": tk.lower(), "limit": 200}).json()
    assert by_t["total"] >= 1 and all(tk in i["tickers"] for i in by_t["items"])
    sel = client.get(f"{P}/reports/{run_id}/evidence", params={"ids": ",".join(i["id"] for i in ev["items"][:3])}).json()
    assert sel["total"] == 3
    assert client.get(f"{P}/reports/{run_id}/evidence", params={"limit": 999}).json()["limit"] == 200
    # 한 건 + 인용 문장
    cited = next(e for e in doc["evidence"] if e["kind"] in ("news", "financial", "disclosure"))
    one = client.get(f"{P}/reports/{run_id}/evidence/{cited['id']}").json()
    assert one["id"] == cited["id"] and isinstance(one["cited_in"], list)
    assert client.get(f"{P}/reports/{run_id}/evidence/ev999999").status_code == 404
    # 체크포인트 상세
    tl = next(b for sec in doc["sections"] for b in sec["blocks"] if b["type"] == "timeline")
    cp = client.get(f"{P}/reports/{run_id}/checkpoints/{tl['items'][-1]['seq']}").json()
    assert cp["portfolio_id"] == doc["header"]["chosen_portfolio_id"] and cp["checkpoint"]["date"] == tl["items"][-1]["date"] and cp["names"]
    assert client.get(f"{P}/reports/{run_id}/checkpoints/9999").status_code == 404
    # 전체 시계열
    se = client.get(f"{P}/reports/{run_id}/series", params={"dataset": "value_usd", "ids": f"{doc['header']['chosen_portfolio_id']},net_invested"}).json()
    assert set(se["series"]) == {doc["header"]["chosen_portfolio_id"], "net_invested"} and len(se["dates"]) == len(se["series"]["net_invested"]["values"])
    assert client.get(f"{P}/reports/{run_id}/series", params={"dataset": "nope"}).status_code == 404
    assert client.get(f"{P}/reports/run_nope/evidence").status_code == 404
