"""분석 패키지 오류. 모두 backend.schemas.errors.MyFinSightError 의 하위 (code·recoverable·details).

API 는 code 를 그대로 오류 봉투에 싣고, 실행기는 code 를 run_step.error_code 에 기록한다 (부록 D).
"""

from __future__ import annotations

import re

from backend.schemas.errors import MyFinSightError, RepositoryError


class RequestInvalid(MyFinSightError):
    """요청 HARD 검증 실패. details["fields"] = {필드경로: 한국어 메시지}. 질문이 아니라 즉시 수정 대상."""

    code = "REQUEST_INVALID"
    recoverable = True


class DialogBlocked(MyFinSightError):
    """질문 상한 뒤에도 미확정 항목이 남아 분석을 시작할 수 없음."""

    code = "DIALOG_BLOCKED"
    recoverable = True


class DialogNotReady(MyFinSightError):
    """확정(confirm) 요청이 왔지만 대화 상태가 ready 가 아님."""

    code = "DIALOG_NOT_READY"
    recoverable = True


class LookaheadError(MyFinSightError):
    """기준일(as_of) 이후 자료를 요청함 (요구 15 선견 금지)."""

    code = "DATA_LOOKAHEAD"


class DataMissing(MyFinSightError):
    """필수 자료(환율·가격 범위·비교지수) 없음."""

    code = "DATA_REQUIRED_MISSING"


class StageFailed(MyFinSightError):
    """단계 실행 실패 (원인 예외는 __cause__)."""

    code = "STAGE_FAILED"


class LlmOutputError(MyFinSightError):
    """LLM 응답이 재시도 후에도 형식·검증을 통과하지 못함."""

    code = "LLM_OUTPUT_INVALID"


class ReportCheckError(MyFinSightError):
    """리포트 문서 검증 실패 (인용 실존·7섹션·금지 표현). 공개 리포트를 만들지 않는다."""

    code = "REPORT_CHECK_FAILED"


class QueueError(MyFinSightError):
    code = "QUEUE_ERROR"


class CancelRequested(MyFinSightError):
    """단계 경계에서 취소 요청을 발견함."""

    code = "RUN_CANCELLED"
    recoverable = True


class NotFound(MyFinSightError):
    code = "NOT_FOUND"
    recoverable = True


class Conflict(MyFinSightError):
    """이미 존재하거나 상태가 맞지 않음 (예: 중복 모의투자, 이미 확정된 요청)."""

    code = "CONFLICT"
    recoverable = True


# ───────────────────────── 사용자에게 돌려줄 오류 문장 ─────────────────────────
_URL = re.compile(r"(?i)\b[a-z][a-z0-9+.\-]*://[^\s'\"<>()]+")
_HOST = re.compile(r"(?i)\b(?:[a-z0-9](?:[a-z0-9-]*[a-z0-9])?\.)+(?:com|net|org|io|cloud|internal|local)\b(?::\d+)?")
_IP = re.compile(r"\b\d{1,3}(?:\.\d{1,3}){3}(?::\d+)?\b")
_SQLA_LINK = re.compile(r"\s*\(Background on this error at:[^)]*\)")


def redact(text: str | None) -> str | None:
    """사용자 응답에 실을 문장에서 DB·서비스 주소, 호스트 이름, IP, SQLAlchemy 안내 링크를 지운다. 원문은 서버 로그에만 남긴다.
    (2026-11 평가: /health 와 DB 연결 오류 메시지에 팀 DB 호스트가 그대로 나왔다)"""
    if not text:
        return text
    text = _SQLA_LINK.sub("", text)
    for rx in (_URL, _HOST, _IP):
        text = rx.sub("(주소 숨김)", text)
    return text


def public_message(exc: BaseException) -> str:
    """사용자 응답용 오류 문장. DB 드라이버 예외가 원인인 RepositoryError 는 원문 대신 무엇이 실패했는지와 한국어 안내만,
    나머지는 redact() 한 원문."""
    text = str(exc)
    if isinstance(exc, RepositoryError) and exc.__cause__ is not None:
        head = text.split(":", 1)[0].strip() or "데이터베이스 작업 실패"
        tail = "팀 DB 에 저장하지 못했습니다" if exc.code == "REPO_WRITE_FAILED" else "팀 DB 에서 자료를 읽지 못했습니다"
        return f"{head}: {tail}. 잠시 뒤 다시 시도해 주세요."
    return redact(text) or ""
