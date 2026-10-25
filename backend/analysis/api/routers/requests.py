"""/requests: 요청 생성(의도 해석 + 첫 질문), 질문 답·건너뛰기, 확정(큐 등록), 취소 (M1-02)."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Request
from pydantic import BaseModel, Field

from backend.analysis.api.routers import services
from backend.analysis.schemas.dialog import DialogState

router = APIRouter(tags=["requests"])


class RequestIn(BaseModel):
    idea: str = Field(min_length=1)
    overrides: dict[str, Any] = Field(default_factory=dict)
    mode: str = "new"
    base_report_id: str | None = None
    language: str = "ko"


class AnswerIn(BaseModel):
    seq: int
    option_value: Any | None = None
    free_text: str | None = None


class SeqIn(BaseModel):
    seq: int


@router.post("/requests", response_model=DialogState)
def create(body: RequestIn, request: Request) -> DialogState:
    return services(request).dialog().start(body.idea, overrides=body.overrides, mode=body.mode, base_report_id=body.base_report_id, language=body.language)


@router.get("/requests", response_model=list[dict[str, Any]])
def list_requests(request: Request, limit: int = 50, include_cancelled: bool = False) -> list[dict[str, Any]]:
    docs = [d for d in services(request).requests.list() if include_cancelled or d.status != "cancelled"][-limit:]
    return [{"request_id": d.request_id, "created_at": d.created_at, "mode": d.mode, "idea": d.idea, "status": d.status, "state": d.dialog_state,
             "run_id": d.run_id, "turn": d.turn} for d in reversed(docs)]  # fmt: skip


@router.get("/requests/{request_id}", response_model=DialogState)
def get(request_id: str, request: Request) -> DialogState:
    return services(request).dialog().get(request_id)


@router.post("/requests/{request_id}/answer", response_model=DialogState)
def answer(request_id: str, body: AnswerIn, request: Request) -> DialogState:
    return services(request).dialog().answer(request_id, body.seq, option_value=body.option_value, free_text=body.free_text)


@router.post("/requests/{request_id}/skip", response_model=DialogState)
def skip(request_id: str, body: SeqIn, request: Request) -> DialogState:
    return services(request).dialog().skip(request_id, body.seq)


class OverridesIn(BaseModel):
    overrides: dict[str, Any]


class MessageIn(BaseModel):
    text: str = Field(min_length=1)


@router.post("/requests/{request_id}/overrides", response_model=DialogState)
def update_overrides(request_id: str, body: OverridesIn, request: Request) -> DialogState:
    """조건 확인 화면에서 폼·버튼으로 조건을 직접 바꿈 (값 None = 프로필 값으로 되돌림). 새 턴을 돈다."""
    return services(request).dialog().update_overrides(request_id, body.overrides)


@router.post("/requests/{request_id}/message", response_model=DialogState)
def message(request_id: str, body: MessageIn, request: Request) -> DialogState:
    """질문과 상관없이 말로 조건·아이디어를 보탬. 다음 턴에 해석한다."""
    return services(request).dialog().message(request_id, body.text)


@router.post("/requests/{request_id}/confirm")
def confirm(request_id: str, request: Request) -> dict[str, Any]:
    run_id, pos = services(request).dialog().confirm(request_id)
    return {"run_id": run_id, "queue_position": pos}


@router.post("/requests/{request_id}/cancel", response_model=DialogState)
def cancel(request_id: str, request: Request) -> DialogState:
    return services(request).dialog().cancel(request_id)
