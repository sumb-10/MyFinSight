"""B0: 설정·스키마·LLM 호출기·로컬 저장소 기본 동작."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from pydantic import ValidationError

from backend.analysis.common.jsonio import canonical_json, load_jsonc
from backend.analysis.common.llm import OpenAiLlm, StubLlm, messages_from_prompts
from backend.analysis.common.store import JsonStore, ProfileStore, RequestStore, RunIndex, new_run_id
from backend.analysis.errors import LlmOutputError
from backend.analysis.paths import REPO_ROOT, STUBS
from backend.analysis.schemas import AnalysisRequestDoc, Constraints, IntentSpec, RunIndexEntry, UserRequest
from backend.analysis.settings import AnalysisSettings

MOCKUP_INPUT = REPO_ROOT / "module_mockup" / "input"


# ───────────────────────── settings ─────────────────────────
def test_settings_defaults_and_env(monkeypatch):
    monkeypatch.setenv("MYFINSIGHT_LLM", "stub")
    s = AnalysisSettings.load()
    assert s.llm.mode == "stub" and s.dialog.max_questions == 5 and s.market.markets == ("US", "KR")
    monkeypatch.setenv("MYFINSIGHT_LLM", "api")
    monkeypatch.setenv("ANALYSIS_MAX_QUESTIONS", "3")
    s2 = AnalysisSettings.load()
    assert s2.llm.mode == "api" and s2.dialog.max_questions == 3
    snap = s2.snapshot()
    json.dumps(snap)  # 직렬화 가능
    assert "api_key_env" not in snap["llm"] and snap["backtest"]["commission_bps"] == 5


# ───────────────────────── schemas ─────────────────────────
def test_mockup_request_files_still_validate():
    files = sorted(MOCKUP_INPUT.glob("01_user_request.*.jsonc"))
    assert files
    for f in files:
        req = UserRequest.model_validate(load_jsonc(f))
        assert req.horizon.backtest_years == 3.0  # 새 기본값
        assert req.constraints.markets() == ["US"]


def _constraints(**kw) -> dict:
    base = {
        "universe": ["SP500", "KOSPI200"],
        "num_holdings": {"target": 10, "min": 8, "max": 12},
        "max_weight_per_stock": 0.15,
        "max_weight_per_sector": 0.4,
        "rebalance": {"count": 1, "unit": "1q"},
    }
    base.update(kw)
    return base


def test_constraints_rules():
    c = Constraints.model_validate(_constraints())
    assert c.markets() == ["KR", "US"] and c.asset_types == ["stock"]
    with pytest.raises(ValidationError, match="cannot sum"):
        Constraints.model_validate(_constraints(max_weight_per_stock=0.1, num_holdings={"target": 5, "min": 5, "max": 6}))
    # 현금 비율이 있으면 그만큼 완화된다
    Constraints.model_validate(
        _constraints(max_weight_per_stock=0.1, min_cash_ratio=0.5, num_holdings={"target": 5, "min": 5, "max": 6})
    )
    with pytest.raises(ValidationError, match="included and excluded"):
        Constraints.model_validate(_constraints(exclude_tickers=["AAPL"], must_include_tickers=["AAPL"]))
    with pytest.raises(ValidationError, match="not supported"):
        Constraints.model_validate(_constraints(allow_short=True))


def test_intent_stub_accepts_questions():
    raw = json.loads((STUBS / "02_intent.example.json").read_text(encoding="utf-8"))
    raw["questions"] = [
        {
            "field": "strategy_preference.template",
            "kind": "preference",
            "question_ko": "선정 기준을 무엇으로 할까요?",
            "options": [{"value": "momentum", "label_ko": "모멘텀"}, {"value": "quality", "label_ko": "퀄리티"}],
            "priority": 2,
        }
    ]
    spec = IntentSpec.model_validate(raw)
    assert spec.questions[0].kind == "preference" and spec.questions[0].allow_free_text is True
    with pytest.raises(ValidationError):
        IntentSpec.model_validate({**raw, "questions": [{"field": "x", "kind": "weird", "question_ko": "?"}]})


# ───────────────────────── llm ─────────────────────────
def test_stub_llm_turn_sequence(tmp_path):
    llm = StubLlm({"02_intent": [{"turn": 1}, {"turn": 2}]}, run_dir=tmp_path)
    msgs = messages_from_prompts("sys", "user")
    assert llm.complete_json("02_intent", msgs)["turn"] == 1
    assert llm.complete_json("02_intent", msgs)["turn"] == 2
    assert llm.complete_json("02_intent", msgs)["turn"] == 2  # 마지막 답 반복
    assert (tmp_path / "prompts" / "02_intent.md").exists()
    # 파일 stub (패키지 stubs/)
    ans = StubLlm().complete_json("04_classify", msgs)
    assert "results" in ans or isinstance(ans, dict)
    with pytest.raises(ValueError):
        StubLlm({"x": {"a": 1}}).complete_json("x", msgs, validator=lambda a: (_ for _ in ()).throw(ValueError("bad")))


class _FakeResp:
    def __init__(self, text: str):
        class U:
            prompt_tokens = 100
            completion_tokens = 20
            prompt_tokens_details = None
            completion_tokens_details = None

        class C:
            finish_reason = "stop"

            class message:
                content = text

        self.model = "gpt-6-luna"
        self.usage = U()
        self.choices = [C()]


class _FakeClient:
    def __init__(self, answers: list[str]):
        self.answers = list(answers)
        self.n = 0

        outer = self

        class _Comp:
            def create(self, **kw):
                outer.n += 1
                return _FakeResp(outer.answers.pop(0))

        class _Chat:
            completions = _Comp()

        self.chat = _Chat()


def test_openai_llm_cache_and_retry(tmp_path):
    s = AnalysisSettings().llm
    client = _FakeClient(['{"ok": 1}'])
    llm = OpenAiLlm(s, run_dir=tmp_path / "run", cache_dir=tmp_path / "cache", client=client, run_id="r1")
    msgs = messages_from_prompts("s", "u")
    assert llm.complete_json("02_intent", msgs) == {"ok": 1}
    # 같은 메시지 -> 캐시 적중, 호출 없음
    assert llm.complete_json("02_intent", msgs) == {"ok": 1}
    assert client.n == 1 and llm.usage_summary()["cache_hits"] == 1
    assert (tmp_path / "run" / "llm_usage.jsonl").read_text(encoding="utf-8").count("\n") == 1
    # 다른 대화(답 추가) -> 다른 키
    client.answers.append('{"ok": 2}')
    assert llm.complete_json("02_intent", [*msgs, {"role": "user", "content": "답: 모멘텀"}]) == {"ok": 2}
    # 깨진 JSON -> 피드백 재시도 1회
    client.answers += ["not json", '{"ok": 3}']
    assert llm.complete_json("x", msgs) == {"ok": 3}
    # 두 번 실패 -> LlmOutputError
    client.answers += ["bad", "bad"]
    with pytest.raises(LlmOutputError):
        llm.complete_json("y", msgs)


# ───────────────────────── store ─────────────────────────
def test_store_roundtrip_and_lock(tmp_path):
    store = JsonStore(tmp_path)
    prof = ProfileStore(store)
    assert prof.current() is None
    fields = {
        "risk_type_computed": "moderate",
        "risk_type_overridden": False,
        "profile": {"user_id": "u", "age_band": "30s", "investment_experience": "beginner",
                    "financial_knowledge": "basic", "investable_ratio_of_assets": 0.3},
        "capital": {"initial_amount": 10_000_000, "currency": "KRW"},
        "horizon": {"target_years": 5, "purpose": "wealth_growth", "backtest_years": 3},
        "risk": {"risk_tolerance": "moderate", "max_drawdown_tolerance": 0.25, "loss_reaction": "hold",
                 "target_annual_return": 0.08, "benchmark": "SPY"},
        "constraints": _constraints(),
        "strategy_preference": {"template": "momentum", "baseline_weighting": "equal_weight", "use_news_tilt": True},
    }
    v1 = prof.save(fields)
    v2 = prof.save({**fields, "capital": {"initial_amount": 20_000_000, "currency": "KRW"}})
    assert v1["version"] == 1 and v2["version"] == 2 and prof.current()["version"] == 2
    assert prof.version(1)["capital"]["initial_amount"] == 10_000_000  # 과거 버전 보존

    reqs = RequestStore(store)
    doc = AnalysisRequestDoc(request_id="req_20261024_120000_abcd", created_at="2026-10-24T12:00:00+09:00",
                             profile_version=2, idea="미국 반도체에 분산 투자", max_questions=5)
    reqs.save(doc)
    assert reqs.load(doc.request_id).idea == doc.idea and len(reqs.list()) == 1

    idx = RunIndex(store)
    rid = new_run_id()
    idx.upsert(RunIndexEntry(run_id=rid, request_id=doc.request_id, status="queued",
                             queued_at="2026-10-24T12:01:00+09:00", output_dir="/tmp/x"))
    idx.update(rid, status="running", started_at="2026-10-24T12:02:00+09:00")
    assert idx.get(rid).status == "running"
    with store.locked("runs"):
        pass  # 재진입 없이 획득·해제
    assert not list((tmp_path).glob("*.tmp"))


def test_canonical_json_is_order_independent():
    assert canonical_json({"b": 1, "a": [1, {"d": 2, "c": 3}]}) == canonical_json({"a": [1, {"c": 3, "d": 2}], "b": 1})
    assert Path(REPO_ROOT / "backend" / "analysis" / "prompts" / "02_intent" / "system_prompt.md").exists()


def test_llm_stage_family_setting_and_backoff_and_stub_threads(tmp_path):
    """날짜가 붙은 단계명도 stage_overrides['09_views_news'] 를 따르고, 백오프는 지터 범위 안, StubLlm 은 스레드에서 순서 답을 한 번씩만 낸다."""
    import threading

    from backend.analysis.common.llm import OpenAiLlm, StubLlm
    from backend.analysis.settings import LlmSettings, replace_settings

    s = replace_settings(LlmSettings(), stage_overrides={"09_views_news": {"max_output_tokens": 6000}}, retry_backoff_s=2, retry_backoff_max_s=10)
    llm = OpenAiLlm(s, run_dir=tmp_path, cache_dir=tmp_path / "c", client=object())
    assert llm._setting("09_views_news_2024-01-02_current", "max_output_tokens") == 6000
    assert llm._setting("14b_narrate", "max_output_tokens") == s.max_output_tokens
    delays = [llm._backoff(a, None) for a in range(5)]
    assert all(1.0 <= d <= 10 * 1.5 for d in delays) and delays[0] <= 3.0

    class _Resp:  # Retry-After 존중
        headers = {"retry-after": "7"}

    class _Exc:
        response = _Resp()

    assert llm._backoff(0, _Exc()) >= 7.0
    stub = StubLlm({"x": [{"i": 1}, {"i": 2}, {"i": 3}, {"i": 4}]})
    got: list[int] = []
    lock = threading.Lock()

    def worker():
        a = stub.complete_json("x", [{"role": "user", "content": "q"}])
        with lock:
            got.append(a["i"])

    ts = [threading.Thread(target=worker) for _ in range(4)]
    [t.start() for t in ts]
    [t.join() for t in ts]
    assert sorted(got) == [1, 2, 3, 4] and len(stub.calls) == 4
    # 날짜 붙은 단계명으로 주입한 답이 stub_key 보다 우선
    stub2 = StubLlm({"09_views_news_2024-01-02": {"sets": []}, "09_views_news": {"sets": [{"scenario_id": "a", "views": []}]}})
    assert stub2.complete_json("09_views_news_2024-01-02", [], stub_key="09_views_news") == {"sets": []}


def test_views_accept_disclosure_ids_and_clip_disclosure_only_confidence(seeded_repo, descriptor_dir):
    """09 뷰: dc 인용 허용, 공시만 인용한 뷰는 신뢰도 상한으로, 모르는 dc 는 제거, 근거 없는 종목의 절대 뷰는 삭제, evidence_type 은 코드가 계산."""
    import datetime as dt

    from backend.analysis.common.llm import StubLlm
    from backend.analysis.m2_data import descriptor as D
    from backend.analysis.m2_data.market_data import MarketData
    from backend.analysis.m4_portfolio.market_model import build_market_model
    from backend.analysis.m4_portfolio.views import generate_views
    from backend.analysis.settings import AnalysisSettings, replace_settings
    from backend.tests.analysis.test_pipeline_e2e import INTENT_STUB, REQUEST

    s = AnalysisSettings()
    s = replace_settings(s, portfolio=replace_settings(s.portfolio, lookback_days=252, min_history_days_for_model=120),
                         market=replace_settings(s.market, descriptor_dir=str(descriptor_dir), valuation_max_staleness_days=10))  # fmt: skip
    md = MarketData(seeded_repo, s)
    view = md.view(dt.date(2025, 12, 31))
    desc, _i, _w = D.load_for(dt.date(2025, 12, 31), ["SP500", "NASDAQ100"], ["US"], processed_dir=str(descriptor_dir))
    tickers = ["NVDA", "AMD", "JPM", "XOM"]  # JPM: 공시만, XOM: 뉴스만(공시 없음)
    req = {**REQUEST, "derived": {"as_of": "2025-12-31", "initial_amount_usd": 10000.0}}
    mm, base = build_market_model(view, tickers, req, desc, s, request_id="r")
    ev = view.news_window(tickers)
    dc_jpm = ev.by_ticker_dc["JPM"][0]
    ev_xom = ev.by_ticker["XOM"][0]
    ans = {"sets": [{"scenario_id": "t", "title_ko": "t", "narrative_ko": "t", "views": [
        {"type": "absolute", "long": ["JPM"], "short": [], "expected_return_annual": 0.1, "confidence": 0.5, "evidence_type": "news", "evidence_ids": [dc_jpm]},
        {"type": "absolute", "long": ["XOM"], "short": [], "expected_return_annual": 0.1, "confidence": 0.4, "evidence_type": "news", "evidence_ids": [ev_xom, dc_jpm]},
        {"type": "absolute", "long": ["AMD"], "short": [], "expected_return_annual": 0.1, "confidence": 0.4, "evidence_type": "news", "evidence_ids": ["dc999999"]},
    ]}]}  # fmt: skip
    wb = {t: base["portfolios"][0]["weights"].get(t, 0.25) for t in mm["tickers"]}
    sets, warns = generate_views(view, mm["tickers"], mm, wb, INTENT_STUB, desc, s, StubLlm({"09_views_news": ans}), ev, n_sets=1, views_per_set=4, stage_tag="09_views_news_test")
    views = sets[0]["views"]
    by = {v["long"][0]: v for v in views}
    assert by["JPM"]["evidence_type"] == "disclosure" and by["JPM"]["confidence"] == s.disclosures.disclosure_only_max_confidence
    assert by["XOM"]["evidence_type"] == "mixed" and by["XOM"]["confidence"] == 0.4
    assert "AMD" not in by and any("unknown evidence ids" in w for w in warns) and any("clipped to" in w for w in warns)


def test_report_retry_routes_to_failing_call_only(e2e_results):
    """14 검증 오류가 시장 문단(14c)에서만 나면 14c 만 다시 부르고 14a·14b 는 그대로 (라운드 4 S6)."""
    from backend.analysis.common.llm import StubLlm
    from backend.analysis.common.stub_answers import stub_interpret, stub_market, stub_narrate
    from backend.analysis.m5_backtest_report.report import generate_report

    R, settings = e2e_results
    calls: list[str] = []

    def market_bad_then_good(messages):
        calls.append("14c")
        ans = stub_market(messages)
        if len([c for c in calls if c == "14c"]) == 1:
            ans["market_ko"] = ["이 전략은 수익을 보장합니다."] + ans["market_ko"]  # 금지 표현
        return ans

    def interp(messages):
        calls.append("14a")
        return stub_interpret(messages)

    def narr(messages):
        calls.append("14b")
        return stub_narrate(messages)

    llm = StubLlm({"14a_interpret": interp, "14c_market": market_bad_then_good, "14b_narrate": narr})
    doc, _ = generate_report(R, llm, settings)
    assert calls.count("14c") == 2 and calls.count("14a") == 1 and calls.count("14b") == 1
    assert all("보장합니다" not in t for s in doc["sections"] for b in s["blocks"] if b["type"] == "paragraphs" for t in b["items"])
    # 블록에 출처 태그가 붙어 있다
    srcs = {b.get("src") for s in doc["sections"] for b in s["blocks"] if b["type"] == "paragraphs"}
    assert {"14a", "14b", "14c"} <= srcs


def test_share_class_key_groups_parenthesized_classes():
    from backend.analysis.m3_selection.retrieve import _share_class_key as k

    assert k({"name": "Alphabet Inc. (Class A)"}) == k({"name": "Alphabet Inc. (Class C)"}) == "alphabet"
    assert k({"name": "Fox Corporation Class A"}) == k({"name": "Fox Corp. Class B"})
    assert k({"name": "News Corp (Class A)"}) != k({"name": "Alphabet Inc. (Class A)"})
    assert k({"name": "Berkshire Hathaway Inc. Class B"}) == "berkshire hathaway"
    assert k({"name": "Samsung Electronics Co., Ltd."}) == "samsung electronics"
    assert k({"name": "", "yfinance_symbol": "X"}) == "X"
