"""분석 진행 화면 (이슈 #14 묶음 D): 단계별 경고 전체(GET /runs/{id}/warnings)와 취소 결과(GET /runs/{id} 의 cancel)."""

from __future__ import annotations

import json
import threading
import time
from pathlib import Path
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

from backend.analysis.api.app import API_PREFIX as P
from backend.analysis.api.app import create_analysis_app
from backend.analysis.api.routers.runs import cancel_view
from backend.analysis.common.llm import OpenAiLlm, StubLlm
from backend.analysis.common.store import JsonStore
from backend.analysis.common.warnings import make
from backend.analysis.errors import CancelRequested, LlmOutputError
from backend.analysis.executor import step_warnings
from backend.analysis.executor.queue import Queue
from backend.analysis.executor.runner import run
from backend.analysis.executor.stages import Stage
from backend.analysis.settings import AnalysisSettings, replace_settings
from backend.tests.analysis.test_executor import _ctx

FEW = {"n": 3, "target": 10}


def test_runner_writes_user_warnings_after_each_stage(tmp_path, seeded_repo, settings):
    ctx = _ctx(tmp_path, seeded_repo, settings)
    seen_by_s2: dict = {}

    def s1(c):
        c.warn("s1", "too_few_candidates", **FEW)
        c.warn("s1", "too_few_candidates", **FEW)  # 같은 경고 → count 2 로 묶임
        c.warn("s1", "leverage_unknown", n=2, tickers="A, B")  # info: 화면 목록에는 없음
        c.warn("s1", "must_include_not_in_universe", tickers="ZZZ")
        return "s1 끝"

    def s2(c):
        seen_by_s2.update(json.loads((c.run_dir / step_warnings.FILE).read_text(encoding="utf-8")))  # 실행 중에도 끝난 단계의 경고가 파일에 있다
        c.warn("s2", "too_few_candidates", n=1, target=5)
        return "s2 끝"

    def s3(c):
        c.warn("s3", "too_few_candidates", **FEW)
        raise ValueError("kaput")  # 실패한 단계의 경고는 목록에 없다 (요약에도 없음)

    out = run(ctx, stages=[Stage("s1", "하나", "conditions", s1), Stage("s2", "둘", "candidates", s2, deps=("s1",)),
                           Stage("s3", "셋", "backtest", s3, deps=("s2",))])  # fmt: skip
    assert out.status == "failed"
    assert list(seen_by_s2) == ["s1"]
    rows = step_warnings.api_rows(step_warnings.load(ctx.run_dir), {"s1": "하나", "s2": "둘", "s3": "셋"}, ["s1", "s2", "s3"])
    assert [(r["step"], r["count"]) for r in rows] == [("s1", 2), ("s1", 1), ("s2", 1)]
    assert rows[0]["step_label_ko"] == "하나" and rows[0]["message_ko"].startswith("테마 후보가 3개로")
    summary = {s.name: s.summary for s in out.steps}
    assert "확인 필요 2건" in summary["s1"] and "확인 필요 1건" in summary["s2"]  # 단계별 줄 수 = 요약의 N


def test_load_rebuilds_from_run_meta_for_older_runs(tmp_path):
    w = [make("s1", "too_few_candidates", **FEW), make("s1", "too_few_candidates", **FEW), make("s1", "leverage_unknown", n=1, tickers="A"),
         make("s2", "too_few_candidates", **FEW)]  # fmt: skip
    meta = {"warnings": [x.to_dict() for x in w], "steps": [{"name": "s1", "status": "PARTIAL"}, {"name": "s2", "status": "FAILED"}]}
    (tmp_path / "run_meta.json").write_text(json.dumps(meta, ensure_ascii=False), encoding="utf-8")
    by = step_warnings.load(tmp_path)
    assert list(by) == ["s1"] and [(x["code"], x["count"]) for x in by["s1"]] == [("too_few_candidates", 2)]
    assert step_warnings.load(tmp_path / "nope") == {}


def test_warnings_api(tmp_path, monkeypatch):
    monkeypatch.setenv("ANALYSIS_OUTPUT_DIR", str(tmp_path / "out"))
    store = JsonStore(tmp_path / "store")
    Queue(store).enqueue("run_w", "req_w")
    c = TestClient(create_analysis_app(lambda: None, store_dir=store.root, settings=AnalysisSettings(), llm=lambda: StubLlm()))
    assert c.get(f"{P}/runs/run_w/warnings").json() == []  # 아직 끝난 단계가 없음
    d = Path(tmp_path / "out" / "run_w")
    step_warnings.save(d, {"05_selection": [make("05_selection", "too_few_candidates", **FEW)], "03_candidates": [make("03_candidates", "must_include_not_in_universe", tickers="ZZZ")]})
    rows = c.get(f"{P}/runs/run_w/warnings").json()
    assert [r["step"] for r in rows] == ["03_candidates", "05_selection"]  # 저장 순서와 상관없이 단계 순서대로
    assert all(r["step_label_ko"] != r["step"] and r["message_ko"] and r["count"] == 1 for r in rows)  # 단계 이름은 레지스트리의 한국어
    assert c.get(f"{P}/runs/nope/warnings").status_code == 404


def _e(status, requested="2026-11-10T09:00:00+09:00", finished=None):
    return SimpleNamespace(status=status, cancel_requested_at=requested, finished_at=finished)


def _st(step, status, started=None):
    return {"step": step, "label_ko": {"03_candidates": "후보 수집", "05_selection": "종목 선정", "11_backtest": "백테스트"}.get(step, step), "status": status, "started_at": started}


def test_cancel_view_states():
    done = [_st("03_candidates", "SUCCESS", "t"), _st("05_selection", "PARTIAL", "t")]
    # 취소 중: 지금 도는 단계
    v = cancel_view(_e("running"), [*done, _st("11_backtest", "STARTED", "t")])
    assert v == {"requested_at": "2026-11-10T09:00:00+09:00", "completed_at": None, "stopped_step": "11_backtest", "stopped_step_label_ko": "백테스트",
                 "done_steps": 2, "immediate": True}  # fmt: skip
    # 단계 도중에 멈춤 (시작했는데 CANCELLED) — 순서가 섞여 와도 단계 순서로 고른다
    v = cancel_view(_e("cancelled", finished="2026-11-10T09:00:07+09:00"), [_st("11_backtest", "CANCELLED", "t"), *done])
    assert (v["stopped_step"], v["completed_at"], v["done_steps"]) == ("11_backtest", "2026-11-10T09:00:07+09:00", 2)
    # 단계 사이에 멈춤: 다음 차례였던 단계
    v = cancel_view(_e("cancelled", finished="x"), [_st("11_backtest", "CANCELLED"), _st("05_selection", "CANCELLED"), _st("03_candidates", "SUCCESS", "t")])
    assert (v["stopped_step"], v["done_steps"]) == ("05_selection", 1)
    # 마지막 단계가 끝난 뒤 취소가 반영됨 (단계는 SUCCESS 로 남고 실행만 취소): 마지막으로 끝난 단계
    v = cancel_view(_e("cancelled", finished="x"), done)
    assert (v["stopped_step"], v["done_steps"]) == ("05_selection", 2)
    # 대기 중 취소: 시작 전
    v = cancel_view(_e("cancelled", finished="x"), [_st("03_candidates", "QUEUED")])
    assert (v["stopped_step"], v["done_steps"]) == (None, 0)
    # 취소를 요청하지 않았거나, 요청이 반영되기 전에 끝난 실행은 없음
    assert cancel_view(_e("running", requested=None), done) is None and cancel_view(_e("success"), done) is None and cancel_view(_e("failed"), done) is None


# ───────────────────────── 즉시 취소: LLM 응답 대기·재시도 대기·백테스트·러너 ─────────────────────────
class _SlowClient:
    """응답이 오래 걸리는 가짜 OpenAI 클라이언트 (chat.completions.create 가 seconds 동안 잔다)."""

    def __init__(self, seconds: float, exc: Exception | None = None) -> None:
        self.seconds, self.exc, self.calls = seconds, exc, 0
        self.chat = SimpleNamespace(completions=SimpleNamespace(create=self._create))

    def _create(self, **_kw):
        self.calls += 1
        if self.exc:
            raise self.exc
        time.sleep(self.seconds)
        raise AssertionError("취소됐으면 이 응답을 쓰지 않는다")


def _llm(tmp_path, client):
    s = AnalysisSettings().llm
    return OpenAiLlm(replace_settings(s, cache=False, retries=2, retry_backoff_s=30, retry_backoff_max_s=30), client=client, cache_dir=tmp_path)


def test_llm_wait_stops_soon_after_cancel(tmp_path):
    llm = _llm(tmp_path, _SlowClient(5.0))
    flag = threading.Event()
    llm.cancel_check = flag.is_set
    threading.Timer(0.3, flag.set).start()
    t0 = time.monotonic()
    with pytest.raises(CancelRequested):  # 「답이 틀림」으로 다시 묻지 않고 그대로 (LlmOutputError 아님)
        llm.complete_json("06_explain", [{"role": "user", "content": "x"}])
    assert time.monotonic() - t0 < 1.5  # 응답(5초)을 기다리지 않는다


def test_llm_retry_backoff_stops_on_cancel(tmp_path):
    import openai

    client = _SlowClient(0, exc=openai.APIConnectionError(request=SimpleNamespace(method="POST", url="x")))  # type: ignore[arg-type]
    llm = _llm(tmp_path, client)
    flag = threading.Event()
    llm.cancel_check = flag.is_set
    threading.Timer(0.3, flag.set).start()
    t0 = time.monotonic()
    with pytest.raises(CancelRequested):
        llm.complete_json("02_intent", [{"role": "user", "content": "x"}])
    assert time.monotonic() - t0 < 1.5 and client.calls == 1  # 재시도 대기(백오프) 중에 멈춤


def test_llm_without_cancel_check_calls_directly(tmp_path):
    """대화 단계처럼 취소 확인이 없으면 예전처럼 바로 부른다 (대기용 스레드를 만들지 않음)."""
    llm = _llm(tmp_path, _SlowClient(0, exc=ValueError("boom")))
    with pytest.raises(LlmOutputError):  # 보낼 때 난 오류는 지금처럼 한 번 다시 묻고 LLM 오류로
        llm.complete_json("02_intent", [{"role": "user", "content": "x"}])
    assert llm._pool is None and llm.cancel_check is None


def test_runner_cancel_inside_stage(tmp_path, seeded_repo, settings):
    flag = threading.Event()

    def asks_llm(c):  # LLM 을 부르는 단계: 취소면 호출에서 바로 멈춤
        flag.set()
        c.llm.complete_json("06_explain", [{"role": "user", "content": "x"}])
        return "never"

    ctx = _ctx(tmp_path, seeded_repo, settings)
    ctx.cancel_check = flag.is_set
    out = run(ctx, stages=[Stage("a", "a", "conditions", asks_llm), Stage("b", "b", "conditions", lambda c: "b")], dump=False)
    assert out.status == "cancelled" and [s.status for s in out.steps] == ["CANCELLED", "CANCELLED"]
    assert ctx.llm.cancel_check is ctx.cancel_check  # 러너가 LLM 에 취소 확인을 꽂는다

    def swallows(c):  # 단계 코드가 취소를 잡아 대체 계산으로 끝내도 실행은 취소 (리포트 단계면 저장하지 않음)
        flag.set()
        try:
            c.llm.complete_json("14_report", [{"role": "user", "content": "x"}])
        except Exception:  # noqa: BLE001
            pass
        return "fallback"

    flag.clear()
    ctx2 = _ctx(tmp_path, seeded_repo, settings)
    ctx2.cancel_check = flag.is_set
    out2 = run(ctx2, stages=[Stage("r", "r", "report", swallows)], dump=False)
    assert out2.status == "cancelled" and out2.steps[0].status == "SUCCESS"

    def converts(c):  # 취소로 끊긴 호출을 다른 오류로 바꿔 던져도 실패가 아니라 취소
        flag.set()
        raise ValueError("LLM 실패를 감싼 오류")

    flag.clear()
    ctx3 = _ctx(tmp_path, seeded_repo, settings)
    ctx3.cancel_check = flag.is_set
    out3 = run(ctx3, stages=[Stage("x", "x", "conditions", converts)], dump=False)
    assert out3.status == "cancelled" and out3.steps[0].status == "CANCELLED" and out3.error is None


def test_backtest_checks_cancel_per_portfolio(monkeypatch):
    from backend.analysis.m5_backtest_report import backtest as B

    calls = []
    monkeypatch.setattr(B, "prepare", lambda *a, **k: {"excluded": [], "benches": ["SPY"], "bench": "SPY", "baseline_id": "p1"})
    monkeypatch.setattr(B, "run_raw", lambda c, pid, w: calls.append(pid) or {"id": pid, "index": None})
    targets = {"backtest_spec": {}, "baseline": {"id": "p1"}, "portfolios": [{"id": "p1", "weights": {}}], "templates": [{"id": "p2", "weights": {}}], "request_id": "r"}
    seen = iter([False, False, True])  # 비교지수·p1 은 돌고 p2 앞에서 취소
    with pytest.raises(CancelRequested):
        B.run_backtest(None, targets, {}, {}, {}, None, AnalysisSettings(), cancel_check=lambda: next(seen))  # type: ignore[arg-type]
    assert calls == ["benchmark_SPY", "p1"]


def test_cancel_poller_reads_index_at_most_every_interval_and_sticks():
    from backend.analysis.executor.worker import cancel_poller

    reads = []

    class Q:
        def is_cancel_requested(self, run_id):
            reads.append(run_id)
            return len(reads) >= 2

    check = cancel_poller(Q(), "run_p", every_s=0.2)  # type: ignore[arg-type]
    assert check() is False and check() is False and len(reads) == 1  # 간격 안에서는 다시 읽지 않음
    time.sleep(0.25)
    assert check() is True and len(reads) == 2
    time.sleep(0.25)
    assert check() is True and len(reads) == 2  # 한 번 취소면 다시 읽지 않고 계속 True
