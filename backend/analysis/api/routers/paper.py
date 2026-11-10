"""/paper: 모의투자 미리보기·등록·목록·상세·갱신·중지·재개 (M6), 이름 보기·바꾸기."""

from __future__ import annotations

import datetime as dt
from collections.abc import Callable
from typing import Any, Literal

from fastapi import APIRouter, Request
from pydantic import BaseModel, Field

from backend.analysis.api.routers import services
from backend.analysis.api.routers.report_names import display_names
from backend.analysis.common.store import PaperStore
from backend.analysis.m6_tracking.paper_meta import PaperMetaStore, clean_name

router = APIRouter(tags=["paper"])


class NameIn(BaseModel):
    """linked = 원본 리포트 이름을 따라감, custom = name_ko 그대로 (프런트 제안 계약 setPaperName 과 같은 모양)."""

    mode: Literal["linked", "custom"]
    name_ko: str | None = None


def _namer(sv: Any) -> Callable[[dict[str, Any]], dict[str, Any]]:
    """모의투자 요약·포트폴리오의 name_ko: 직접 정한 이름 → 원본 리포트의 지금 이름 → 저장된 이름(전략 이름, 리포트를 못 찾을 때)."""
    reports = display_names(sv)
    custom = PaperMetaStore(sv.store).custom_names()
    return lambda d: {**d, "name_ko": custom.get(d["paper_id"]) or reports.get(d["report_id"], d["name_ko"])}


def _named_detail(sv: Any, d: dict[str, Any]) -> dict[str, Any]:
    name = _namer(sv)
    return {**d, "portfolio": name(d["portfolio"]), "summary": name(d["summary"])}


def _name_view(sv: Any, paper_id: str) -> dict[str, Any]:
    """프런트 제안 계약 ProposedPaperName 모양. 없는 모의투자면 404."""
    doc = PaperStore(sv.store).load(paper_id)
    report = display_names(sv).get(doc["report_id"], doc["name_ko"])
    custom = PaperMetaStore(sv.store).custom_names().get(paper_id)
    return {"name_ko": custom or report, "mode": "custom" if custom else "linked", "report_name_ko": report}


class PaperIn(BaseModel):
    report_id: str
    strategy_id: str | None = None
    start_date: dt.date | None = None
    initial_amount: float | None = Field(default=None, gt=0)
    currency: Literal["KRW", "USD"] | None = None
    monthly_contribution: float | None = Field(default=None, ge=0)
    name: NameIn | None = None  # 등록 때만 쓴다 (없으면 linked, 미리보기는 무시)

    def kwargs(self) -> dict[str, Any]:
        return {"strategy_id": self.strategy_id, "start_date": self.start_date, "initial_amount": self.initial_amount, "currency": self.currency,
                "monthly_contribution": self.monthly_contribution}  # fmt: skip


@router.post("/paper/preview")
def preview(body: PaperIn, request: Request) -> dict[str, Any]:
    return services(request).paper().preview(body.report_id, **body.kwargs())


@router.post("/paper", status_code=201)
def create(body: PaperIn, request: Request) -> dict[str, Any]:
    sv = services(request)
    custom = clean_name(body.name.name_ko) if body.name and body.name.mode == "custom" else None  # 이름이 틀리면 모의투자를 만들지 않는다
    d = sv.paper().create(body.report_id, **body.kwargs())
    if custom:
        PaperMetaStore(sv.store).set_custom(d["portfolio"]["paper_id"], custom)
    return _named_detail(sv, d)


@router.get("/paper")
def list_papers(request: Request) -> list[dict[str, Any]]:
    sv = services(request)
    name = _namer(sv)
    return [name(s) for s in sv.paper().list()]


@router.get("/paper/{paper_id}")
def detail(paper_id: str, request: Request) -> dict[str, Any]:
    sv = services(request)
    return _named_detail(sv, sv.paper().detail(paper_id))


@router.post("/paper/{paper_id}/refresh")
def refresh(paper_id: str, request: Request) -> dict[str, Any]:
    sv = services(request)
    return _named_detail(sv, sv.paper().refresh(paper_id))


@router.post("/paper/{paper_id}/stop")
def stop(paper_id: str, request: Request) -> dict[str, Any]:
    sv = services(request)
    return _named_detail(sv, sv.paper().stop(paper_id))


@router.post("/paper/{paper_id}/resume")
def resume(paper_id: str, request: Request) -> dict[str, Any]:
    sv = services(request)
    return _named_detail(sv, sv.paper().resume(paper_id))


@router.get("/paper/{paper_id}/name")
def get_name(paper_id: str, request: Request) -> dict[str, Any]:
    return _name_view(services(request), paper_id)


@router.put("/paper/{paper_id}/name")
def put_name(paper_id: str, body: NameIn, request: Request) -> dict[str, Any]:
    """이름만 바꾼다 (모의투자 기록·설정은 그대로). custom 은 공백 정리 뒤 1~40자."""
    sv = services(request)
    PaperStore(sv.store).load(paper_id)  # 없으면 404
    meta = PaperMetaStore(sv.store)
    if body.mode == "custom":
        meta.set_custom(paper_id, clean_name(body.name_ko))
    else:
        meta.link(paper_id)
    return _name_view(sv, paper_id)
