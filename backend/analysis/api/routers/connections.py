"""/connections: 연결 설정 (팀 DB 접속 주소 · OpenAI API 키). 프런트 제안 계약 getConnections·saveConnection·clearConnection 과 같은 모양.

- 조회는 어디서든 된다 (Docker 에서는 모든 요청이 컨테이너 밖 주소에서 온 것으로 보인다). 다만 가린 값(DB 서버 이름·키 끝자리)은 이 컴퓨터에서 물었을 때만 싣는다.
- 저장·지우기는 이 컴퓨터에서 온 요청만 받는다 (화면의 「이 컴퓨터에만 저장」과 맞춘다). 값은 응답에 다시 싣지 않는다.
- 환경변수(.env · Compose)로 들어온 연결은 바꿀 수 없다 → 409.
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field

from backend.analysis import connections
from backend.analysis.api.errors import envelope
from backend.analysis.api.routers import services

router = APIRouter(tags=["connections"])

LOCAL_HOSTS = {"127.0.0.1", "::1", "localhost", "testclient"}  # testclient = 테스트용 클라이언트가 쓰는 이름


class ConnectionIn(BaseModel):
    value: str = Field(min_length=1, max_length=4000)


def _local(request: Request) -> bool:
    return (request.client.host if request.client else "") in LOCAL_HOSTS


def _forbidden() -> JSONResponse:
    return JSONResponse(status_code=403, content=envelope("FORBIDDEN", "연결은 이 프로그램을 켠 컴퓨터에서만 바꿀 수 있습니다"))


def _refused(exc: connections.Refused) -> JSONResponse:
    return JSONResponse(status_code=409, content=envelope(exc.code, exc.message_ko))


@router.get("/connections")
def get_connections(request: Request) -> dict[str, Any]:
    """지금 연결 상태. 분석 한 번의 사용료 어림(cost_per_run_usd)은 연결 전에도 준다."""
    return connections.status(services(request), reveal=_local(request))


@router.put("/connections/{kind}", response_model=None)
def save_connection(kind: connections.Kind, body: ConnectionIn, request: Request) -> Any:
    """실제로 접속해 보고 되면 운영체제 보관함에 저장한다. 안 되면 저장하지 않고 ok=false 와 원인 코드를 준다
    (응답 코드는 200 — 입력이 틀린 것이지 요청이 틀린 것이 아니다)."""
    if not _local(request):
        return _forbidden()
    try:
        return connections.save(services(request), kind, body.value)
    except connections.Refused as exc:
        return _refused(exc)


@router.delete("/connections/{kind}", response_model=None)
def clear_connection(kind: connections.Kind, request: Request) -> Any:
    """저장한 값을 지운다."""
    if not _local(request):
        return _forbidden()
    try:
        return connections.clear(services(request), kind)
    except connections.Refused as exc:
        return _refused(exc)
