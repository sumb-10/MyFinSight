"""/runs: 실행 상태(폴링용), 목록, 취소·취소 결과, 단계별 경고 전체 (M0-05). 단계 상태는 DB run_step, 큐 상태는 runs.json."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Request

from backend.analysis.api.routers import services
from backend.analysis.errors import redact
from backend.analysis.executor import step_warnings
from backend.analysis.executor.stages import STAGES
from backend.analysis.m5_backtest_report.persist import bucket_status, steps_for_api
from backend.analysis.schemas.run import BUCKETS, RunStatus

router = APIRouter(tags=["runs"])
LABELS = {s.name: (s.label_ko, s.bucket) for s in STAGES}
LABELS["14_report"] = ("리포트 문서 생성·검증", "report")
ORDER = [*(s.name for s in STAGES), "14_report"]


def cancel_view(e: Any, steps: list[dict[str, Any]]) -> dict[str, Any] | None:
    """취소 결과 (프런트 제안 계약 ProposedRunCancel). 취소를 요청했고 아직 진행 중(cancelling)이거나 취소로 끝난 실행만.
    멈춘 단계: 취소 중이면 지금 도는 단계, 취소로 끝났으면 도중에 멈춘 단계(시작했는데 CANCELLED) → 없으면 다음에 돌 차례였던 단계.
    immediate=False: 서버는 단계 사이·LLM 묶음 사이에서만 멈추고 도는 계산을 바로 끊지 않는다."""
    if not e.cancel_requested_at or e.status not in ("running", "cancelled"):
        return None
    rank = {name: i for i, name in enumerate(ORDER)}
    by_order = sorted(steps, key=lambda s: rank.get(s["step"], len(rank)))
    if e.status == "running":
        stopped = next((s for s in by_order if s["status"] == "STARTED"), None)
    else:
        cancelled = [s for s in by_order if s["status"] == "CANCELLED"]
        stopped = next((s for s in cancelled if s.get("started_at")), None) or (cancelled[0] if cancelled else None)
    return {"requested_at": e.cancel_requested_at, "completed_at": e.finished_at if e.status == "cancelled" else None,
            "stopped_step": stopped["step"] if stopped else None, "stopped_step_label_ko": stopped["label_ko"] if stopped else None,
            "done_steps": sum(s["status"] in step_warnings.DONE for s in steps), "immediate": False}  # fmt: skip


def run_status(sv, run_id: str) -> RunStatus:
    e = sv.queue.get(run_id)
    steps = steps_for_api(sv.repo, run_id, LABELS)
    for st in steps:  # 예전 실행의 오류 문장에 남은 DB 주소 등은 내보내기 전에 지운다 (2026-11 평가)
        if st.get("error_message"):
            st["error_message"] = redact(st["error_message"])
    if not steps:  # 아직 시작 전: 레지스트리 전체를 QUEUED 로 보여 준다
        steps = [{"step": s.name, "label_ko": s.label_ko, "bucket": s.bucket, "status": "QUEUED"} for s in STAGES]
    buckets = bucket_status(steps)
    present = {b["id"] for b in buckets}
    buckets += [{"id": bid, "title_ko": title, "status": "QUEUED"} for bid, title in BUCKETS if bid not in present]
    buckets.sort(key=lambda b: [x[0] for x in BUCKETS].index(b["id"]))
    status = e.status
    if status == "running" and e.cancel_requested_at:
        status = "cancelling"
    error = None
    if e.status == "failed":
        failed = next((s for s in steps if s["status"] == "FAILED"), None)
        error = {"code": e.error_code or (failed or {}).get("error_code") or "STAGE_FAILED", "message_ko": redact(e.error_message) or (failed or {}).get("error_message") or "실행에 실패했습니다",
                 "step": (failed or {}).get("step"), "actions": ["edit_conditions", "retry", "home"]}  # fmt: skip
    return RunStatus(run_id=e.run_id, request_id=e.request_id, status=status, queue_position=sv.queue.position(run_id) if e.status == "queued" else None,
                     queued_at=e.queued_at, started_at=e.started_at, finished_at=e.finished_at, buckets=buckets, steps=steps, report_id=e.report_id, error=error,
                     cancel=cancel_view(e, steps))  # fmt: skip


@router.get("/runs", response_model=list[dict[str, Any]])
def list_runs(request: Request, limit: int = 50) -> list[dict[str, Any]]:
    return [{**d, "error_message": redact(d.get("error_message"))} for d in (e.model_dump(mode="json") for e in services(request).queue.list(limit))]


@router.get("/runs/{run_id}", response_model=RunStatus)
def get_run(run_id: str, request: Request) -> RunStatus:
    return run_status(services(request), run_id)


@router.post("/runs/{run_id}/cancel", response_model=RunStatus)
def cancel_run(run_id: str, request: Request) -> RunStatus:
    sv = services(request)
    sv.queue.request_cancel(run_id)
    return run_status(sv, run_id)


@router.get("/runs/{run_id}/warnings")
def warnings(run_id: str, request: Request) -> list[dict[str, Any]]:
    """끝난 단계의 사용자 경고 전체, 단계 순서대로 [{step, step_label_ko, message_ko, count}].
    단계 요약은 「확인 필요 N건」 을 2건까지만 적는다. 같은 경고는 count 로 묶여 있고 단계별 줄 수 = 요약의 N."""
    from backend.analysis.paths import run_dir

    services(request).queue.get(run_id)  # 없는 실행이면 NotFound
    return step_warnings.api_rows(step_warnings.load(run_dir(run_id)), {k: v[0] for k, v in LABELS.items()}, ORDER)


@router.get("/runs/{run_id}/partial")
def partial(run_id: str, request: Request) -> dict[str, Any]:
    """실행 중 중간 결과 (라운드 5): 해석 요약(02)·선정 종목 표(05)가 디스크에 있으면 돌려준다. 백테스트가 끝나기 전에도 볼 수 있다."""
    import json

    from backend.analysis.paths import run_dir

    sv = services(request)
    sv.queue.get(run_id)  # 없는 실행이면 NotFound
    d = run_dir(run_id)
    out: dict[str, Any] = {"run_id": run_id, "intent": None, "selection": None}
    f = d / "02_intent.json"
    if f.exists():
        it = json.loads(f.read_text(encoding="utf-8"))
        interp = it.get("interpretation") or {}
        out["intent"] = {"summary_ko": interp.get("summary_ko"), "themes": [{"id": t.get("id"), "label_ko": t.get("label_ko")} for t in interp.get("themes", [])],
                         "template": (it.get("screen") or {}).get("template"), "metric": (it.get("screen") or {}).get("metric")}  # fmt: skip
    f = d / "05_selection.json"
    if f.exists():
        sel = json.loads(f.read_text(encoding="utf-8"))
        rows = [{"rank": x.get("rank"), "ticker": x.get("ticker"), "name": x.get("name"), "sector": x.get("sector"), "metric_value": x.get("metric_value")} for x in sel.get("selected", [])]
        out["selection"] = {"as_of": sel.get("as_of"), "metric": (sel.get("summary") or {}).get("metric"), "n_selected": len(rows), "n_target": (sel.get("summary") or {}).get("n_target"),
                            "n_candidates": (sel.get("summary") or {}).get("n_candidates"), "n_tagged": (sel.get("summary") or {}).get("n_tagged"), "rows": rows}  # fmt: skip
    return out


@router.post("/runs/{run_id}/retry", response_model=RunStatus)
def retry_run(run_id: str, request: Request) -> RunStatus:
    """실패·취소된 실행을 같은 확정 요청으로 다시 큐에 넣는다 (라운드 5, P1-9). 새 run_id 를 받는다."""
    import datetime as dt

    from backend.analysis.common.store import new_run_id
    from backend.analysis.errors import Conflict

    sv = services(request)
    e = sv.queue.get(run_id)
    if e.status not in ("failed", "cancelled"):
        raise Conflict(f"실행이 {e.status} 상태라 다시 돌릴 수 없습니다 (실패·취소된 실행만)")
    doc = sv.requests.load(e.request_id)
    if doc.status != "confirmed" or not doc.effective_request:
        raise Conflict("확정된 요청이 아니어서 다시 돌릴 수 없습니다")
    new_id = new_run_id(dt.datetime.now())
    doc.run_id = new_id
    sv.requests.save(doc)
    sv.queue.enqueue(new_id, doc.request_id, llm_mode=e.llm_mode)
    return run_status(sv, new_id)
