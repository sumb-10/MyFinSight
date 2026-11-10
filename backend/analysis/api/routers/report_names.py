"""/reports 이름 조회·변경, 삭제(숨김). 프런트 제안 계약 getReportName·renameReport·deleteReport 와 같은 모양."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Request
from pydantic import BaseModel

from backend.analysis.api.routers import services
from backend.analysis.errors import NotFound, RequestInvalid
from backend.analysis.m5_backtest_report.report_meta import (
    NAME_MAX,
    ReportMetaStore,
    auto_name,
    name_view,
)

router = APIRouter(tags=["reports"])


class NameIn(BaseModel):
    name: str | None = None  # null 이면 자동 이름으로 되돌린다


def _auto(sv: Any, report_id: str) -> str:
    """저장된 리포트의 자동 이름. 없거나 삭제(숨김)된 리포트면 404."""
    row = sv.repo.get_report(report_id)
    if not row or ReportMetaStore(sv.store).is_deleted(report_id):
        raise NotFound(f"리포트 {report_id} 이 없습니다")
    idea = None
    try:
        idea = sv.requests.load(sv.queue.get(report_id).request_id).idea
    except NotFound:
        pass  # 실행 기록이 없는 리포트는 저장된 요약·전략 이름으로
    return auto_name(idea=idea, request_summary=row.get("request_summary"), strategy_name=row.get("strategy_name"), run_id=report_id)


def display_names(sv: Any) -> dict[str, str]:
    """리포트 ID → 지금 표시 이름 (삭제해 숨긴 리포트 포함: 그 리포트로 만든 모의투자는 계속 이름이 필요하다)."""
    meta = ReportMetaStore(sv.store).all()
    rows = {r["report_id"]: r for r in sv.repo.list_reports(1000)}
    reqs = {d.request_id: d for d in sv.requests.list()}
    out = {}
    for e in sv.queue.list():
        row = rows.get(e.report_id or "")
        if not row:
            continue
        d = reqs.get(e.request_id)
        auto = auto_name(idea=d.idea if d else None, request_summary=row.get("request_summary"), strategy_name=row.get("strategy_name"), run_id=e.run_id)
        out[e.report_id] = name_view(e.report_id, auto, meta.get(e.report_id))["display_ko"]
    return out


@router.get("/reports/{report_id}/name")
def get_name(report_id: str, request: Request) -> dict[str, Any]:
    sv = services(request)
    auto = _auto(sv, report_id)
    return name_view(report_id, auto, ReportMetaStore(sv.store).get(report_id))


@router.put("/reports/{report_id}/name")
def put_name(report_id: str, body: NameIn, request: Request) -> dict[str, Any]:
    sv = services(request)
    auto = _auto(sv, report_id)
    name = " ".join((body.name or "").split()) or None
    if name and len(name) > NAME_MAX:
        raise RequestInvalid(f"리포트 이름은 {NAME_MAX}자 이하여야 합니다", details={"fields": {"name": f"{NAME_MAX}자 이하"}})
    meta = ReportMetaStore(sv.store).rename(report_id, None if name == auto else name)
    return name_view(report_id, auto, meta)


@router.delete("/reports/{report_id}")
def delete_report(report_id: str, request: Request) -> dict[str, Any]:
    """목록과 조회에서 숨긴다. 리포트·결과·실행 기록·이 리포트로 만든 모의투자는 지우지 않는다."""
    sv = services(request)
    _auto(sv, report_id)
    ReportMetaStore(sv.store).delete(report_id)
    return {"report_id": report_id, "deleted": True}
