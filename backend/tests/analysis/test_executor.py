"""B3: 큐(FIFO·순번·취소·stale 복구), 러너 상태 전이(실패 → 남은 단계 CANCELLED, 단계 경계 취소), DB 저장(run_step·run_artifact·report), 워커 1회."""

from __future__ import annotations

import datetime as dt
from pathlib import Path

import pytest

from backend.analysis.common.llm import StubLlm
from backend.analysis.common.store import JsonStore, RequestStore
from backend.analysis.errors import CancelRequested, Conflict
from backend.analysis.executor import worker
from backend.analysis.executor.context import RunContext
from backend.analysis.executor.queue import Queue
from backend.analysis.executor.runner import run
from backend.analysis.executor.stages import Stage
from backend.analysis.m2_data.market_data import MarketData
from backend.analysis.m5_backtest_report.persist import bucket_status, db_step_hook, steps_for_api
from backend.analysis.schemas.dialog import AnalysisRequestDoc
from backend.analysis.settings import AnalysisSettings, replace_settings
from backend.db import open_repository
from backend.tests.analysis.test_pipeline_e2e import INTENT_STUB, REQUEST


def _ctx(tmp_path: Path, repo, settings) -> RunContext:
    md = MarketData(repo, settings)
    return RunContext(run_id="run_x", request=dict(REQUEST), repo=repo, md=md, llm=StubLlm(), settings=settings, run_dir=tmp_path / "run_x")


def test_queue_fifo_position_cancel_and_stale(tmp_path):
    store = JsonStore(tmp_path)
    q = Queue(store)
    assert q.enqueue("run_a", "req_a") == 1
    assert q.enqueue("run_b", "req_b") == 2
    with pytest.raises(Conflict):
        q.enqueue("run_a", "req_a")
    a = q.claim_next(worker_pid=99999999)
    assert a.run_id == "run_a" and a.status == "running"
    assert q.claim_next() is None  # 단일 워커: running 이 있으면 다음을 집지 않음
    assert q.position("run_b") == 2 and q.position("run_a") is None and q.length() == 1
    # 대기 중 취소는 즉시, 실행 중 취소는 요청만
    q.enqueue("run_c", "req_c")
    assert q.request_cancel("run_c").status == "cancelled"
    assert q.request_cancel("run_a").status == "running" and q.is_cancel_requested("run_a")
    # 죽은 pid 의 running -> failed
    assert q.recover_stale(lambda pid: False) == ["run_a"]
    assert q.get("run_a").status == "failed" and q.get("run_a").error_code == "WORKER_DIED"
    b = q.claim_next()
    assert b.run_id == "run_b"
    q.finish("run_b", "success", report_id="run_b")
    assert q.get("run_b").report_id == "run_b" and [r.run_id for r in q.list()][0] in ("run_c", "run_b", "run_a")


def test_runner_failure_cancels_remaining_and_records_steps(tmp_path, seeded_repo, settings):
    ctx = _ctx(tmp_path, seeded_repo, settings)
    events: list[tuple[str, str]] = []

    def ok(c):
        return "fine"

    def boom(c):
        raise ValueError("kaput")

    stages = [Stage("s1", "하나", "conditions", ok), Stage("s2", "둘", "candidates", boom), Stage("s3", "셋", "backtest", ok)]
    out = run(ctx, stages=stages, on_step=lambda step, st, info: events.append((step, st)), dump=False)
    assert out.status == "failed" and out.error["step"] == "s2" and out.error["code"] == "STAGE_FAILED"
    assert [s.status for s in out.steps] == ["SUCCESS", "FAILED", "CANCELLED"]
    assert events[:3] == [("s1", "QUEUED"), ("s2", "QUEUED"), ("s3", "QUEUED")] and ("s3", "CANCELLED") in events
    # 단계 경계 취소
    ctx2 = _ctx(tmp_path, seeded_repo, settings)
    flag = {"cancel": False}

    def set_cancel(c):
        flag["cancel"] = True
        return "set"

    ctx2.cancel_check = lambda: flag["cancel"]
    out2 = run(ctx2, stages=[Stage("a", "a", "conditions", set_cancel), Stage("b", "b", "conditions", ok)], dump=False)
    assert out2.status == "cancelled" and [s.status for s in out2.steps] == ["SUCCESS", "CANCELLED"]
    # 단계 안에서 CancelRequested
    ctx3 = _ctx(tmp_path, seeded_repo, settings)
    out3 = run(ctx3, stages=[Stage("a", "a", "conditions", lambda c: (_ for _ in ()).throw(CancelRequested("stop")))], dump=False)
    assert out3.status == "cancelled" and out3.steps[0].status == "CANCELLED"


def test_db_step_hook_and_bucket_status():
    repo = open_repository("sqlite://")
    hook = db_step_hook(repo, "run_h")
    hook("01_request", "QUEUED", {"label_ko": "요청", "bucket": "conditions"})
    hook("01_request", "STARTED", {"label_ko": "요청", "bucket": "conditions", "started_at": "2026-01-01T09:00:00+09:00"})
    hook("01_request", "SUCCESS", {"label_ko": "요청", "bucket": "conditions", "started_at": "2026-01-01T09:00:00+09:00",
                                   "ended_at": "2026-01-01T09:00:05+09:00", "summary": "ok"})  # fmt: skip
    hook("11_backtest", "QUEUED", {"label_ko": "백테스트", "bucket": "backtest"})
    labels = {"01_request": ("요청", "conditions"), "11_backtest": ("백테스트", "backtest")}
    steps = steps_for_api(repo, "run_h", labels)
    assert {s["step"]: s["status"] for s in steps} == {"01_request": "SUCCESS", "11_backtest": "QUEUED"}
    b = {x["id"]: x["status"] for x in bucket_status(steps)}
    assert b == {"conditions": "SUCCESS", "backtest": "QUEUED"}


@pytest.mark.slow
def test_worker_runs_confirmed_request_and_persists(tmp_path, descriptor_dir):
    """큐 → 워커 1회 → run_step·run_artifact 저장 (리포트 단계는 B6 에서). 합성 DB 는 함수 범위 sqlite 로 새로 만든다."""
    from backend.tests.analysis.conftest import seed_repository

    repo = open_repository("sqlite://", clock=lambda: dt.datetime(2026, 1, 5, tzinfo=dt.UTC))
    seed_repository(repo)
    s = AnalysisSettings()
    s = replace_settings(s, portfolio=replace_settings(s.portfolio, lookback_days=252, min_history_days_for_model=120),
                         market=replace_settings(s.market, valuation_max_staleness_days=10, descriptor_dir=str(descriptor_dir)))  # fmt: skip
    store = JsonStore(tmp_path / "store")
    import os

    os.environ["ANALYSIS_OUTPUT_DIR"] = str(tmp_path / "out")
    try:
        doc = AnalysisRequestDoc(request_id="req_20251231_120000_wrk1", created_at="2025-12-31T12:00:00+09:00", profile_version=1, idea=REQUEST["natural_language"]["idea"],
                                 status="confirmed", dialog_state="confirmed", effective_request={**REQUEST, "request_id": "req_20251231_120000_wrk1"},
                                 intent={**INTENT_STUB, "request_id": "req_20251231_120000_wrk1", "questions": []}, confirmed_at="2025-12-31T12:05:00+09:00")  # fmt: skip
        RequestStore(store).save(doc)
        q = Queue(store)
        q.enqueue("run_wrk1", doc.request_id)
        status = worker.run_once(repo=repo, store=store, settings=s, llm=StubLlm(run_dir=tmp_path / "out" / "run_wrk1"))
        assert status in ("success", "partial"), q.get("run_wrk1")
        entry = q.get("run_wrk1")
        assert entry.status == status and entry.finished_at
        steps = repo.get_steps("run_wrk1")
        assert {s_.step for s_ in steps} >= {"01_request", "11_backtest", "13_results"} and all(s_.status.value in ("SUCCESS", "PARTIAL") for s_ in steps)
        art = repo.get_run_artifact("run_wrk1")
        assert art and art["results"]["run_id"] == "run_wrk1" and art["params"]["backtest"]["commission_bps"] == 5
        rep = repo.get_report("run_wrk1")
        assert rep and (rep["doc"] if "doc" in rep else rep)["run_id"] == "run_wrk1" and entry.report_id == "run_wrk1"
        assert RequestStore(store).load(doc.request_id).run_id == "run_wrk1"
        assert worker.run_once(repo=repo, store=store, settings=s) is None  # 큐 비었음
    finally:
        os.environ.pop("ANALYSIS_OUTPUT_DIR", None)


# ───────────────────────── 병렬 실행 (라운드 4) ─────────────────────────
def test_map_ordered_keeps_order_cancels_and_propagates_first_error():
    import threading
    import time

    from backend.analysis.executor.parallel import map_ordered

    seen: list[int] = []
    lock = threading.Lock()

    def slow_sq(i: int) -> int:
        time.sleep(0.01 * (5 - i % 5))  # 뒤 항목이 먼저 끝나도
        with lock:
            seen.append(i)
        return i * i

    prog: list[tuple[int, int]] = []
    out = map_ordered(list(range(12)), slow_sq, max_workers=4, on_done=lambda i, n: prog.append((i, n)))
    assert out == [i * i for i in range(12)] and sorted(seen) == list(range(12)) and prog[-1] == (12, 12) and len(prog) == 12
    assert map_ordered([], slow_sq, max_workers=4) == [] and map_ordered([3], slow_sq, max_workers=4) == [9]

    # 첫 예외(입력 순서상 가장 앞)가 올라오고, 아직 시작하지 않은 항목은 돌지 않는다
    ran: list[int] = []

    def boom(i: int) -> int:
        time.sleep(0.02 if i != 2 else 0.0)
        with lock:
            ran.append(i)
        if i in (2, 7):
            raise ValueError(f"bad {i}")
        return i

    with pytest.raises(ValueError, match="bad 2"):
        map_ordered(list(range(40)), boom, max_workers=3)
    assert len(ran) < 40
    # 취소 요청: 시작 전 항목은 건너뛰고 CancelRequested
    flag = {"c": False}

    def cancel_after(i: int) -> int:
        if i == 1:
            flag["c"] = True
        time.sleep(0.01)
        return i

    with pytest.raises(CancelRequested):
        map_ordered(list(range(30)), cancel_after, max_workers=2, cancel_check=lambda: flag["c"])
    # 순차 모드도 같은 계약
    assert map_ordered([1, 2, 3], lambda x: x + 1, max_workers=1) == [2, 3, 4]
    with pytest.raises(ZeroDivisionError):
        map_ordered([1, 0], lambda x: 1 // x, max_workers=1)


def test_waves_and_parallel_stage_failure(tmp_path, seeded_repo, settings):
    """의존이 끝난 단계는 한 웨이브로 동시에, 웨이브 안 실패는 그 웨이브의 다른 단계를 끝까지 돌리고 다음 웨이브부터 CANCELLED."""
    import threading
    import time

    from backend.analysis.executor.runner import waves

    def mk(name, fn, deps):
        return Stage(name, name, "candidates", fn, deps=deps)

    running: set[str] = set()
    peak = {"n": 0}
    lock = threading.Lock()

    def slow(name):
        def f(c):
            with lock:
                running.add(name)
                peak["n"] = max(peak["n"], len(running))
            time.sleep(0.05)
            with lock:
                running.discard(name)
            c.outputs[name] = {"ok": True}
            return name

        return f

    stages = [mk("a", slow("a"), ()), mk("b", slow("b"), ("a",)), mk("c", slow("c"), ("a",)), mk("d", slow("d"), ("a",)), mk("e", slow("e"), ("b", "c", "d"))]
    assert [[s.name for s in w] for w in waves(stages)] == [["a"], ["b", "c", "d"], ["e"]]
    # deps=None 은 "바로 앞 단계" (순차) — 기존 테스트 단계들
    legacy = [Stage("s1", "1", "conditions", slow("s1")), Stage("s2", "2", "conditions", slow("s2"))]
    assert [[s.name for s in w] for w in waves(legacy)] == [["s1"], ["s2"]]
    ctx = _ctx(tmp_path, seeded_repo, settings)
    out = run(ctx, stages=stages, dump=False)
    assert out.status == "success" and [s.status for s in out.steps] == ["SUCCESS"] * 5 and peak["n"] >= 2
    assert list(ctx.step_summaries) == ["a", "b", "c", "d", "e"] or set(ctx.step_summaries) == {"a", "b", "c", "d", "e"}
    # 순차 설정이면 동시 실행 없음
    seq = replace_settings(settings, executor=replace_settings(settings.executor, max_parallel_stages=1))
    peak["n"] = 0
    out1 = run(_ctx(tmp_path, seeded_repo, seq), stages=stages, dump=False)
    assert out1.status == "success" and peak["n"] == 1
    # 웨이브 안 실패: c 가 터져도 b·d 는 끝나고(SUCCESS), e 는 CANCELLED
    def boom(c):
        raise ValueError("kaput")

    stages2 = [mk("a", slow("a"), ()), mk("b", slow("b"), ("a",)), mk("c", boom, ("a",)), mk("d", slow("d"), ("a",)), mk("e", slow("e"), ("b", "c", "d"))]
    events: list[tuple[str, str]] = []
    out2 = run(_ctx(tmp_path, seeded_repo, settings), stages=stages2, on_step=lambda st, s, i: events.append((st, s)), dump=False)
    assert out2.status == "failed" and out2.error["step"] == "c"
    assert {s.name: s.status for s in out2.steps} == {"a": "SUCCESS", "b": "SUCCESS", "c": "FAILED", "d": "SUCCESS", "e": "CANCELLED"}
    assert ("e", "CANCELLED") in events
    # 경고는 단계 순서로 정렬된다 (동시 실행이어도 결과 파일 순서가 같게)
    def warn_stage(name):
        def f(c):
            time.sleep(0.03 if name == "b" else 0.0)
            c.warn(name, "weight_capacity", capacity=0.9)
            return name

        return f

    stages3 = [mk("a", slow("a"), ()), mk("b", warn_stage("b"), ("a",)), mk("c", warn_stage("c"), ("a",)), mk("d", warn_stage("d"), ("a",))]
    ctx3 = _ctx(tmp_path, seeded_repo, settings)
    run(ctx3, stages=stages3, dump=False)
    assert [w.stage for w in ctx3.warnings] == ["b", "c", "d"]
