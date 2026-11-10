"""GET/PUT /profile (M1-01). 저장 = 새 버전 추가. 검증은 요청 HARD 규칙과 같다 (아이디어 자리에는 임시 문구)."""

from __future__ import annotations

from typing import Any

import jsonschema
from fastapi import APIRouter, Request
from pydantic import BaseModel, Field

from backend.analysis.api.routers import services
from backend.analysis.errors import Conflict, NotFound, RequestInvalid
from backend.analysis.m1_request.assemble import build
from backend.analysis.m1_request.profile_chat import (
    QUESTION_IDS,
    ProfileChatStore,
    answer_chat,
    chat_view,
    current_question,
    rewind_chat,
)
from backend.analysis.m1_request.validate import hard_errors

router = APIRouter(tags=["profile"])


class ProfileIn(BaseModel):
    profile: dict[str, Any] = Field(default_factory=dict)
    capital: dict[str, Any]
    horizon: dict[str, Any]
    risk: dict[str, Any]
    constraints: dict[str, Any]
    strategy_preference: dict[str, Any]
    diagnosis: dict[str, Any] | None = None
    risk_type_computed: str = "moderate"
    risk_type_overridden: bool = False
    note: str | None = None


def _view(doc: dict[str, Any]) -> dict[str, Any]:
    cur = next(v for v in doc["versions"] if v["version"] == doc["current_version"])
    return {"profile_id": doc["profile_id"], "current_version": doc["current_version"], "profile": cur,
            "versions": [{"version": v["version"], "created_at": v["created_at"], "note": v.get("note")} for v in doc["versions"]]}  # fmt: skip


@router.get("/profile")
def get_profile(request: Request) -> dict[str, Any]:
    doc = services(request).profiles.load()
    if not doc:
        raise NotFound("프로필이 없습니다. 먼저 등록해 주세요")
    return _view(doc)


@router.put("/profile")
def put_profile(body: ProfileIn, request: Request) -> dict[str, Any]:
    sv = services(request)
    fields = body.model_dump(exclude_none=True)
    note = fields.pop("note", None)
    fields.setdefault("profile", {}).setdefault("user_id", "default")
    fields["horizon"].pop("start_date", None)  # 기준일은 프로필이 아니라 요청마다 정해진다
    trial = build(fields, "프로필 검증용 임시 아이디어입니다", request_id="req_profile_check", created_at="2000-01-01T00:00:00+00:00")
    errs = hard_errors(trial)
    if errs:
        raise RequestInvalid("프로필 값에 오류가 있습니다", code="PROFILE_INVALID", details={"fields": {e.field: e.message_ko for e in errs}})
    try:
        sv.profiles.save(fields, note=note)
    except jsonschema.ValidationError as e:
        path = ".".join(str(x) for x in e.absolute_path if x not in ("versions",) and not isinstance(x, int))
        raise RequestInvalid("프로필 값에 오류가 있습니다", code="PROFILE_INVALID", details={"fields": {path or "profile": e.message}}) from e
    return _view(sv.profiles.load())


# ───────────────────────── 대화형 초기 투자조건 (POST /profile/chat …) ─────────────────────────
# 규칙은 m1_request/profile_chat.py (프런트 목업 대화를 그대로 옮긴 고정 11문항, LLM 없음). 대화는 초안만 만들고 저장은 위의 PUT /profile.


class ChatAnswerIn(BaseModel):
    """프런트 ProposedChatAnswer. 값의 형식·범위는 여기서 막지 않는다 — 맞지 않으면 422 가 아니라 봇이 다시 묻는다 (목업과 같음)."""

    question_id: str
    option_value: Any = None  # 보기 값 (multi 는 배열)
    number: Any = None  # 금액·숫자 직접 입력
    skip: bool = False


class ChatRewindIn(BaseModel):
    question_id: str


def _draft_errors(sv: Any, draft: dict[str, Any]) -> list[str]:
    """PUT /profile 과 같은 검사 (ProfileIn → build → hard_errors → 저장 스키마). 오류 문장 목록 (없으면 [])."""
    fields = ProfileIn.model_validate(draft).model_dump(exclude_none=True)
    fields.pop("note", None)
    fields.setdefault("profile", {}).setdefault("user_id", "default")
    fields["horizon"].pop("start_date", None)
    trial = build(fields, "프로필 검증용 임시 아이디어입니다", request_id="req_profile_check", created_at="2000-01-01T00:00:00+00:00")
    errs = [e.message_ko for e in hard_errors(trial)]
    if errs:
        return errs
    try:
        sv.store.validate({"schema_version": 1, "profile_id": "default", "current_version": 1,
                           "versions": [{"version": 1, "created_at": "2000-01-01T00:00:00+00:00", **fields}]}, "profile")  # fmt: skip
    except jsonschema.ValidationError as e:
        return [e.message]
    return []


@router.post("/profile/chat")
def start_profile_chat(request: Request) -> dict[str, Any]:
    """새 대화 (기본값 초안 + 첫 질문). 이미 투자조건이 있어도 쓸 수 있다 (저장하면 새 버전). 마지막으로 답한 지 7일이 지난 대화는 이때 지운다."""
    return chat_view(ProfileChatStore(services(request).store).start())


@router.post("/profile/chat/{chat_id}/answers")
def answer_profile_chat(chat_id: str, body: ChatAnswerIn, request: Request) -> dict[str, Any]:
    """지금 질문에 답한다. 맞지 않는 답(범위 밖·없는 보기·필수 건너뛰기)은 200 + 봇의 다시 묻는 말풍선, 지금 차례가 아닌 질문은 409.
    마지막 답으로 요약(review)이 되기 전에 PUT /profile 과 같은 검사를 하고, 통과하지 못하면 그 답을 받지 않고 다시 묻는다."""
    sv = services(request)
    chats = ProfileChatStore(sv.store)
    with chats.locked():
        st = chats.load(chat_id)
        q = current_question(st)
        if q is None or q.id != body.question_id:
            now = f"지금 질문은 '{q.id}'" if q else "모든 질문에 답한 대화"
            raise Conflict(f"지금 답할 질문이 아닙니다 ({now})", details={"current_question_id": q.id if q else None})
        st = chats.save(answer_chat(st, body.model_dump(), check=lambda d: _draft_errors(sv, d)))
    return chat_view(st)


@router.post("/profile/chat/{chat_id}/rewind")
def rewind_profile_chat(chat_id: str, body: ChatRewindIn, request: Request) -> dict[str, Any]:
    """그 질문만 다시 묻는다 (뒤의 답은 남기고, 성향 진단을 고치면 「성향 확인」도 다시 묻는다). 없는 질문 id 는 422."""
    if body.question_id not in QUESTION_IDS:
        raise RequestInvalid("없는 질문입니다", details={"fields": {"question_id": f"{', '.join(QUESTION_IDS)} 중 하나"}})
    chats = ProfileChatStore(services(request).store)
    with chats.locked():
        st = chats.save(rewind_chat(chats.load(chat_id), body.question_id))
    return chat_view(st)
