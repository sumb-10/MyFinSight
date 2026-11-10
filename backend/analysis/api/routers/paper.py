"""/paper: 모의투자 미리보기·등록·목록·상세·갱신·중지·재개 (M6)."""

from __future__ import annotations

import datetime as dt
from typing import Any, Literal

from fastapi import APIRouter, Request
from pydantic import BaseModel, Field

from backend.analysis.api.routers import services
from backend.analysis.api.routers.report_names import display_names, with_report_name

router = APIRouter(tags=["paper"])


def _named_detail(request: Request, d: dict[str, Any]) -> dict[str, Any]:
    """상세 응답의 모의투자 이름을 원본 리포트의 지금 이름으로."""
    names = display_names(services(request))
    return {**d, "portfolio": with_report_name(names, d["portfolio"]), "summary": with_report_name(names, d["summary"])}


class PaperIn(BaseModel):
    report_id: str
    strategy_id: str | None = None
    start_date: dt.date | None = None
    initial_amount: float | None = Field(default=None, ge=0)  # 0 이면 매월 적립금이 있어야 한다 (PaperService._plan)
    currency: Literal["KRW", "USD"] | None = None
    monthly_contribution: float | None = Field(default=None, ge=0)

    def kwargs(self) -> dict[str, Any]:
        return {"strategy_id": self.strategy_id, "start_date": self.start_date, "initial_amount": self.initial_amount, "currency": self.currency,
                "monthly_contribution": self.monthly_contribution}  # fmt: skip


@router.post("/paper/preview")
def preview(body: PaperIn, request: Request) -> dict[str, Any]:
    return services(request).paper().preview(body.report_id, **body.kwargs())


@router.post("/paper", status_code=201)
def create(body: PaperIn, request: Request) -> dict[str, Any]:
    return _named_detail(request, services(request).paper().create(body.report_id, **body.kwargs()))


@router.get("/paper")
def list_papers(request: Request) -> list[dict[str, Any]]:
    sv = services(request)
    names = display_names(sv)
    return [with_report_name(names, s) for s in sv.paper().list()]


@router.get("/paper/{paper_id}")
def detail(paper_id: str, request: Request) -> dict[str, Any]:
    return _named_detail(request, services(request).paper().detail(paper_id))


@router.post("/paper/{paper_id}/refresh")
def refresh(paper_id: str, request: Request) -> dict[str, Any]:
    return _named_detail(request, services(request).paper().refresh(paper_id))


@router.post("/paper/{paper_id}/stop")
def stop(paper_id: str, request: Request) -> dict[str, Any]:
    return _named_detail(request, services(request).paper().stop(paper_id))


@router.post("/paper/{paper_id}/resume")
def resume(paper_id: str, request: Request) -> dict[str, Any]:
    return _named_detail(request, services(request).paper().resume(paper_id))
