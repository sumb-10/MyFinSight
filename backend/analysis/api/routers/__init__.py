"""라우터 모음. 각 라우터는 `request.app.state.services` 로 서비스 객체를 얻는다."""

from fastapi import Request

from backend.analysis.api.services import Services


def services(request: Request) -> Services:
    return request.app.state.services
