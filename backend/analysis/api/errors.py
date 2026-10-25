"""오류 봉투: {"error": {"code", "message_ko", "fields"?, "details"?}} (Module7 §4: 안정된 코드 + 한국어 메시지 + 필드별 오류)."""

from __future__ import annotations

from typing import Any

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse

from backend.analysis.errors import (
    CancelRequested,
    Conflict,
    DataMissing,
    DialogBlocked,
    DialogNotReady,
    LlmOutputError,
    LookaheadError,
    NotFound,
    QueueError,
    RequestInvalid,
)
from backend.schemas.errors import DataQualityError, MyFinSightError, RepositoryError

STATUS = {
    NotFound: 404, Conflict: 409, DialogBlocked: 409, DialogNotReady: 409, RequestInvalid: 422, LookaheadError: 422, DataMissing: 422,
    DataQualityError: 422, QueueError: 500, LlmOutputError: 502, RepositoryError: 503, CancelRequested: 409,
}  # fmt: skip

MESSAGE_KO = {
    "NOT_FOUND": "찾을 수 없습니다", "CONFLICT": "요청 상태가 맞지 않습니다", "DIALOG_BLOCKED": "보충 질문 상한을 넘어 분석을 시작할 수 없습니다",
    "DIALOG_NOT_READY": "조건 확인이 끝나지 않았습니다", "REQUEST_INVALID": "입력 조건에 오류가 있습니다", "DATA_LOOKAHEAD": "기준일 이후 자료는 쓸 수 없습니다",
    "DATA_REQUIRED_MISSING": "필수 자료가 없습니다", "LLM_OUTPUT_INVALID": "분석 모델 응답을 처리할 수 없습니다", "REPO_READ_FAILED": "데이터베이스 읽기에 실패했습니다",
    "REPO_WRITE_FAILED": "데이터베이스 쓰기에 실패했습니다", "VALIDATION_ERROR": "요청 형식이 올바르지 않습니다",
}  # fmt: skip


def envelope(code: str, message_ko: str, *, fields: dict[str, str] | None = None, details: dict[str, Any] | None = None) -> dict[str, Any]:
    body: dict[str, Any] = {"error": {"code": code, "message_ko": message_ko}}
    if fields:
        body["error"]["fields"] = fields
    if details:
        body["error"]["details"] = details
    return body


def install(app: FastAPI) -> None:
    @app.exception_handler(MyFinSightError)
    async def _mfs(_: Request, exc: MyFinSightError) -> JSONResponse:
        status = next((s for cls, s in STATUS.items() if isinstance(exc, cls)), 500)
        details = dict(exc.details or {})
        fields = details.pop("fields", None)
        msg = str(exc) or MESSAGE_KO.get(exc.code, exc.code)
        safe = {k: v for k, v in details.items() if k not in ("report",)}
        return JSONResponse(status_code=status, content=envelope(exc.code, msg, fields=fields, details=safe or None))

    @app.exception_handler(RequestValidationError)
    async def _val(_: Request, exc: RequestValidationError) -> JSONResponse:
        from backend.analysis.m1_request.validate import LABELS, _ko  # 요청 검증과 같은 한국어 문구 (라운드 5, P2-24)

        fields: dict[str, str] = {}
        for e in exc.errors():
            loc = ".".join(str(x) for x in e["loc"] if x not in ("body", "query", "path"))
            msg = _ko(str(e["msg"]).replace("Value error, ", ""), loc)
            fields[loc or "body"] = f"{LABELS[loc]}: {msg}" if loc in LABELS else msg
        return JSONResponse(status_code=422, content=envelope("VALIDATION_ERROR", MESSAGE_KO["VALIDATION_ERROR"], fields=fields))

    @app.exception_handler(Exception)
    async def _any(_: Request, exc: Exception) -> JSONResponse:
        return JSONResponse(status_code=500, content=envelope("INTERNAL_ERROR", "서버 내부 오류가 발생했습니다", details={"type": type(exc).__name__}))
