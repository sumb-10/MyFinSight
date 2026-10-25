"""GET/PUT /profile (M1-01). 저장 = 새 버전 추가. 검증은 요청 HARD 규칙과 같다 (아이디어 자리에는 임시 문구)."""

from __future__ import annotations

from typing import Any

import jsonschema
from fastapi import APIRouter, Request
from pydantic import BaseModel, Field

from backend.analysis.api.routers import services
from backend.analysis.errors import NotFound, RequestInvalid
from backend.analysis.m1_request.assemble import build
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
