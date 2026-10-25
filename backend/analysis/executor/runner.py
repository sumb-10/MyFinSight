"""러너 (M0-05): 단계를 의존 순서대로 실행하며 상태를 기록한다. 의존이 끝난 단계는 묶어서(웨이브) 동시에 돈다 (라운드 4).

- 시작 시 모든 단계 QUEUED → 단계마다 STARTED → SUCCESS/PARTIAL(행동 필요 경고 있음) → 예외면 FAILED, 남은 단계 CANCELLED.
- 취소는 단계 시작 전(웨이브 안 포함)과 긴 단계 내부(10w 날짜 풀)에서 확인한다. 실패한 실행은 자동으로 다시 돌리지 않는다.
- 같은 웨이브의 다른 단계가 실패해도 진행 중인 단계는 끝까지 돈다(스레드는 중단할 수 없음). 그 뒤 웨이브부터 CANCELLED.
- 상태 기록 콜백(`on_step`)은 B3 에서 Repository.save_step 으로 연결한다. 산출물은 run_dir/NN_*.json 으로 덤프한다.
"""

from __future__ import annotations

import logging
import threading
import time
import traceback
from concurrent.futures import ThreadPoolExecutor
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from typing import Any

from backend.analysis.common.jsonio import dump_json, now_iso
from backend.analysis.common.warnings import merge, render
from backend.analysis.errors import CancelRequested, StageFailed
from backend.analysis.executor.context import RunContext
from backend.analysis.executor.stages import OUTPUT_FILES, STAGES, Stage
from backend.schemas.errors import MyFinSightError

log = logging.getLogger(__name__)

StepHook = Callable[[str, str, dict[str, Any]], None]  # (step, status, info)


@dataclass
class StepResult:
    name: str
    status: str
    started_at: str | None = None
    ended_at: str | None = None
    summary: str | None = None
    error_code: str | None = None
    error_message: str | None = None
    elapsed_s: float | None = None


@dataclass
class RunOutcome:
    run_id: str
    status: str  # success | partial | failed | cancelled
    steps: list[StepResult] = field(default_factory=list)
    error: dict[str, Any] | None = None
    notices: list[dict[str, Any]] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {"run_id": self.run_id, "status": self.status, "error": self.error,
                "steps": [s.__dict__ for s in self.steps]}  # fmt: skip




def _dump_outputs(ctx: RunContext) -> None:
    for key, obj in list(ctx.outputs.items()):  # 다른 단계가 동시에 키를 더해도 안전하게
        fname = OUTPUT_FILES.get(key)
        if fname and not (ctx.run_dir / fname).exists():
            dump_json(obj, ctx.run_dir / fname)
    panel = ctx.outputs.get("_daily_panel")
    if panel is not None and ctx.settings.backtest.save_daily_panel and not (ctx.run_dir / "11_daily_panel.parquet").exists():
        try:
            panel.to_parquet(ctx.run_dir / "11_daily_panel.parquet", index=False)
        except Exception as e:  # pyarrow 없음 등: 산출물 저장 실패가 실행을 멈추지 않게
            log.warning("daily panel not saved: %r", e)


def waves(stages: Sequence[Stage]) -> list[list[Stage]]:
    """의존이 모두 끝난 단계를 한 묶음(웨이브)으로. deps=None 인 단계는 목록상 바로 앞 단계에 의존한다(순차)."""
    names = [s.name for s in stages]
    deps: dict[str, set[str]] = {}
    for i, s in enumerate(stages):
        d = set(s.deps) if s.deps is not None else ({names[i - 1]} if i > 0 else set())
        deps[s.name] = {x for x in d if x in names}  # when() 으로 빠진 선행 단계는 무시
    done: set[str] = set()
    remaining = list(stages)
    out: list[list[Stage]] = []
    while remaining:
        ready = [s for s in remaining if deps[s.name] <= done]
        if not ready:
            raise ValueError(f"stage dependency cycle among {[s.name for s in remaining]}")
        out.append(ready)
        done |= {s.name for s in ready}
        remaining = [s for s in remaining if s not in ready]
    return out


def run(ctx: RunContext, *, stages: Sequence[Stage] | None = None, on_step: StepHook | None = None, dump: bool = True) -> RunOutcome:
    stages = [s for s in (stages or STAGES) if s.when(ctx)]
    order = {s.name: i for i, s in enumerate(stages)}
    outcome = RunOutcome(run_id=ctx.run_id, status="running")
    results = {s.name: StepResult(name=s.name, status="QUEUED") for s in stages}
    by_name = {s.name: s for s in stages}
    io_lock = threading.Lock()  # 상태 콜백·파일 덤프는 한 번에 하나씩 (병렬 웨이브)
    _hook = on_step or (lambda *_: None)

    def hook(step: str, status: str, info: dict[str, Any]) -> None:
        with io_lock:
            _hook(step, status, info)

    for s in stages:
        hook(s.name, "QUEUED", {"label_ko": s.label_ko, "bucket": s.bucket})
    ctx.run_dir.mkdir(parents=True, exist_ok=True)
    dump_json({"run_id": ctx.run_id, "request_id": ctx.request_id, "started_at": now_iso(), "status": "running",
               "stages": [s.name for s in stages], "settings": ctx.settings.snapshot()}, ctx.run_dir / "run_meta.json")  # fmt: skip
    state: dict[str, Any] = {"failed": None, "cancelled": False}
    last_prog: dict[str, float] = {}
    min_gap = ctx.settings.executor.progress_min_interval_s

    def _progress(stage: str, i: int, n: int) -> None:  # 긴 단계(10w·04 등)의 "i/n" 진행 표시
        st, r = by_name.get(stage), results.get(stage)
        if st is None or r is None:
            return
        now = time.time()
        if i < n and now - last_prog.get(stage, 0.0) < min_gap:
            return
        last_prog[stage] = now
        hook(stage, "STARTED", {"label_ko": st.label_ko, "bucket": st.bucket, "started_at": r.started_at, "summary": f"{st.label_ko} {i}/{n}"})

    ctx.progress = _progress

    def _run_stage(s: Stage) -> None:
        r = results[s.name]
        if ctx.cancel_check():
            state["cancelled"] = True
        if state["cancelled"] or state["failed"]:
            r.status = "CANCELLED"
            hook(s.name, "CANCELLED", {"label_ko": s.label_ko, "bucket": s.bucket})
            return
        r.started_at = now_iso()
        r.status = "STARTED"
        hook(s.name, "STARTED", {"label_ko": s.label_ko, "bucket": s.bucket, "started_at": r.started_at})
        t0 = time.time()
        try:
            summary = s.fn(ctx)
            r.ended_at, r.elapsed_s = now_iso(), round(time.time() - t0, 2)
            mine = merge(ctx.warnings_of(s.name))
            user = [w for w in mine if w.level == "user"]
            info = [w for w in mine if w.level == "info"]
            r.status = "PARTIAL" if user else "SUCCESS"  # 행동이 필요한 경고가 있을 때만 "경고 있음"
            r.summary = (summary or "") + (f" · 확인 필요 {len(user)}건: " + "; ".join(render(w) for w in user[:2])[:400] if user else "") + (f" · 참고 {len(info)}건" if info and not user else "")
            ctx.step_summaries[s.name] = r.summary
            log.info("[%s] %s %s (%.1fs)", ctx.run_id, s.name, r.status, r.elapsed_s)
        except CancelRequested as e:
            r.ended_at, r.status, r.error_code, r.error_message = now_iso(), "CANCELLED", e.code, str(e)
            state["cancelled"] = True
        except Exception as e:
            r.ended_at, r.elapsed_s = now_iso(), round(time.time() - t0, 2)
            r.status = "FAILED"
            r.error_code = e.code if isinstance(e, MyFinSightError) else StageFailed.code
            r.error_message = f"{type(e).__name__}: {e}"[:1000]
            log.error("[%s] %s FAILED: %s\n%s", ctx.run_id, s.name, r.error_message, traceback.format_exc())
            if state["failed"] is None or order[s.name] < order[state["failed"].name]:
                state["failed"] = r
        hook(s.name, r.status, {"label_ko": s.label_ko, "bucket": s.bucket, "started_at": r.started_at, "ended_at": r.ended_at,
                                "summary": r.summary, "error_code": r.error_code, "error_message": r.error_message})  # fmt: skip
        if dump:
            with io_lock:
                _dump_outputs(ctx)

    max_par = max(1, ctx.settings.executor.max_parallel_stages)
    for wave in waves(stages):
        if len(wave) > 1 and max_par > 1 and not (state["cancelled"] or state["failed"]):
            with ThreadPoolExecutor(max_workers=min(max_par, len(wave)), thread_name_prefix="mfs-stage") as pool:
                list(pool.map(_run_stage, wave))
        else:
            for s in wave:
                _run_stage(s)
        ctx.warnings.sort(key=lambda w: order.get(w.stage, len(order)))  # 안정 정렬: 단계 순서로 (동시 실행이어도 결과 파일의 순서가 같게)
    outcome.steps = list(results.values())
    failed = state["failed"]
    if failed:
        outcome.status = "failed"
        outcome.error = {"step": failed.name, "code": failed.error_code, "message": failed.error_message}
    elif state["cancelled"]:
        outcome.status = "cancelled"
    else:
        outcome.status = "partial" if any(r.status == "PARTIAL" for r in outcome.steps) else "success"
    outcome.notices = [w.to_dict() for w in merge(ctx.warnings) if w.level != "debug"]  # run_meta 용 (user+info)
    meta = {"run_id": ctx.run_id, "request_id": ctx.request_id, "finished_at": now_iso(), "status": outcome.status, "error": outcome.error,
            "steps": [r.__dict__ for r in outcome.steps], "notices": outcome.notices, "warnings": [w.to_dict() for w in ctx.warnings],
            "llm_usage": ctx.llm.usage_summary(), "settings": ctx.settings.snapshot()}  # fmt: skip
    dump_json(meta, ctx.run_dir / "run_meta.json")
    return outcome
