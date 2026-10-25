"""결과·리포트 DB 저장 (M5-04 / M0-05). 계약 쓰기 테이블 세 개만 쓴다: run_step, run_artifact, report.

- 13_results → run_artifact(results_json, params_json, llm_usage_json). 같은 run_id 면 덮어씀.
- 14_report → report(doc_json). run_artifact 가 먼저 있어야 하고 불변 (이미 있으면 거부).
- run_step 은 러너의 단계 콜백이 쓴다 (`db_step_hook`).
"""

from __future__ import annotations

import datetime as dt
from collections.abc import Callable
from typing import Any

from backend.analysis.schemas.run import BUCKETS
from backend.schemas.runlog import StepRecord, StepStatus

BUCKET_TITLE = dict(BUCKETS)


def _ts(s: str | None) -> dt.datetime | None:
    return dt.datetime.fromisoformat(s) if s else None


def db_step_hook(repo: Any, run_id: str) -> Callable[[str, str, dict[str, Any]], None]:
    """러너의 on_step 콜백: 단계 상태를 run_step 에 upsert. 저장 실패는 로그만 (실행을 멈추지 않음)."""
    import logging

    log = logging.getLogger(__name__)

    def hook(step: str, status: str, info: dict[str, Any]) -> None:
        rec = StepRecord(run_id=run_id, step=step, status=StepStatus(status), started_at=_ts(info.get("started_at")), ended_at=_ts(info.get("ended_at")),
                         summary=(info.get("summary") or info.get("label_ko") or "")[:500] or None, error_code=info.get("error_code"),
                         error_message=(info.get("error_message") or None))  # fmt: skip
        try:
            repo.save_step(rec)
        except Exception as e:  # noqa: BLE001
            log.warning("run_step not saved (%s %s): %r", step, status, e)

    return hook


def save_results(repo: Any, run_id: str, request_id: str, results: dict[str, Any], params: dict[str, Any], llm_usage: dict[str, Any] | None) -> None:
    repo.save_run_artifact(run_id, request_id, results, params, llm_usage=llm_usage)


def save_report(repo: Any, run_id: str, doc: dict[str, Any], *, strategy_name: str | None, request_summary: str | None, as_of: dt.date) -> None:
    repo.save_report(run_id, doc, strategy_name=strategy_name, request_summary=request_summary, as_of=as_of)


def steps_for_api(repo: Any, run_id: str, labels: dict[str, tuple[str, str]]) -> list[dict[str, Any]]:
    """run_step 행 → API RunStep dict (label_ko·bucket 은 레지스트리에서)."""
    out = []
    for r in repo.get_steps(run_id):
        label, bucket = labels.get(r.step, (r.step, "report"))
        out.append({"step": r.step, "label_ko": label, "bucket": bucket, "status": r.status.value,
                    "started_at": r.started_at.isoformat() if r.started_at else None, "ended_at": r.ended_at.isoformat() if r.ended_at else None,
                    "summary": r.summary, "error_code": r.error_code, "error_message": r.error_message})  # fmt: skip
    return out


def bucket_status(steps: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """다섯 묶음의 상태: FAILED > STARTED > CANCELLED > (모두 끝났으면 PARTIAL/SUCCESS) > QUEUED."""
    out = []
    for bid, title in BUCKETS:
        st = [s["status"] for s in steps if s["bucket"] == bid]
        if not st:
            continue
        if "FAILED" in st:
            status = "FAILED"
        elif "STARTED" in st:
            status = "STARTED"
        elif "CANCELLED" in st and "SUCCESS" not in st and "PARTIAL" not in st:
            status = "CANCELLED"
        elif all(x in ("SUCCESS", "PARTIAL") for x in st):
            status = "PARTIAL" if "PARTIAL" in st else "SUCCESS"
        elif any(x in ("SUCCESS", "PARTIAL") for x in st) and "CANCELLED" in st:
            status = "CANCELLED"
        else:
            status = "QUEUED"
        out.append({"id": bid, "title_ko": title, "status": status})
    return out
