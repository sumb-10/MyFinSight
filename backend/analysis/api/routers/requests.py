"""/requests: 요청 생성(번호를 바로 돌려주고 의도 해석 + 첫 질문은 응답 뒤에), 질문 답·건너뛰기, 확정(큐 등록), 취소 (M1-02)."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, BackgroundTasks, Request
from pydantic import BaseModel, Field

from backend.analysis.api.routers import services
from backend.analysis.schemas.dialog import DialogState, MessageResult

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
def create(body: RequestIn, request: Request, background: BackgroundTasks) -> DialogState:
    """요청을 '해석 중'으로 저장해 번호를 바로 돌려주고, 해석(LLM)·첫 질문은 응답 뒤에 돌린다 (sync 함수라 스레드풀).
    화면은 받은 번호의 주소로 가서 GET /requests/{id} 로 끝났는지 본다 — 해석 중 새로고침해도 요청을 잃지 않는다."""
    sv = services(request)
    st = sv.dialog().create(body.idea, overrides=body.overrides, mode=body.mode, base_report_id=body.base_report_id, language=body.language)
    background.add_task(sv.dialog().run_first_turn, st.request_id)
    return st


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


class BatchOption(BaseModel):
    value: Any = None
    label_ko: str


class BatchQuestion(BaseModel):
    seq: int
    field: str
    field_label_ko: str
    question_ko: str
    why_ko: str | None = None
    required: bool = False  # 지금처럼 모든 질문은 「답하지 않음 (기본값 사용)」 으로 넘길 수 있다
    options: list[BatchOption] = []
    allow_free_text: bool = True


class QuestionBatch(BaseModel):
    request_id: str
    questions: list[BatchQuestion] = []


class BatchAnswerIn(BaseModel):
    seq: int
    option_value: Any | None = None
    free_text: str | None = None
    skip: bool = False


@router.get("/requests/{request_id}/questions", response_model=QuestionBatch)
def question_batch(request_id: str, request: Request) -> QuestionBatch:
    """지금 답을 기다리는 질문들 — 한 턴에 함께 물은 묶음 (서로 영향 없는 항목만 최대 3개). 고칠 조건 오류가 있거나 질문 중이 아니면 빈 목록."""
    doc = services(request).requests.load(request_id)
    qs = [q for q in doc.questions if not q.answered_at] if doc.dialog_state == "asking" and not doc.hard_errors else []
    return QuestionBatch(request_id=request_id, questions=[BatchQuestion(seq=q.seq, field=q.field, field_label_ko=q.field_label_ko or q.field, question_ko=q.question_ko,
                                                                        why_ko=q.why_ko or None, options=[BatchOption(value=o.value, label_ko=o.label_ko) for o in q.options],
                                                                        allow_free_text=q.allow_free_text) for q in qs])  # fmt: skip


@router.post("/requests/{request_id}/answers", response_model=DialogState)
def answer_batch(request_id: str, body: list[BatchAnswerIn], request: Request) -> DialogState:
    """함께 물은 질문들에 한 번에 답한다. 빠진 질문·빈 답은 답하지 않음(기본값). 함께 고른 답이 서로 부딪히면 422 (details.seqs). 턴은 한 번만 돈다."""
    return services(request).dialog().answer_batch(request_id, [a.model_dump() for a in body])


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


@router.get("/requests/{request_id}/messages", response_model=list[MessageResult])
def message_results(request_id: str, request: Request) -> list[MessageResult]:
    """「말로 보태기」 처리 결과, 보낸 순서 (반영됨·반영 안 됨·확인 필요와 바뀐 것). 이 기능 전에 보낸 말은 기록이 없다."""
    return services(request).requests.load(request_id).message_results


@router.post("/requests/{request_id}/confirm")
def confirm(request_id: str, request: Request) -> dict[str, Any]:
    run_id, pos = services(request).dialog().confirm(request_id)
    return {"run_id": run_id, "queue_position": pos}


@router.post("/requests/{request_id}/cancel", response_model=DialogState)
def cancel(request_id: str, request: Request) -> DialogState:
    return services(request).dialog().cancel(request_id)
