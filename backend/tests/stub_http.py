"""크롤러 테스트용 HTTP 세션 스텁 (requests.Session 대신 끼운다)."""

from __future__ import annotations

import json
from collections.abc import Callable
from typing import Any


class StubResponse:
    def __init__(self, status_code: int = 200, data: Any = None, content: bytes | None = None):
        self.status_code = status_code
        self._data = data
        if content is None:
            content = json.dumps(data).encode() if data is not None else b""
        self.content = content
        self.text = content.decode("utf-8", errors="replace")

    @property
    def ok(self) -> bool:
        return self.status_code < 400

    def json(self) -> Any:
        return self._data if self._data is not None else json.loads(self.text)

    def raise_for_status(self) -> None:
        if not self.ok:
            raise RuntimeError(f"HTTP {self.status_code}")


Handler = Callable[[str, dict[str, Any]], StubResponse]


class StubSession:
    """handler(url, kwargs) 가 응답을 만든다. 호출은 calls 에 남는다."""

    def __init__(self, handler: Handler):
        self.handler = handler
        self.calls: list[tuple[str, str, dict[str, Any]]] = []

    def get(self, url: str, **kw: Any) -> StubResponse:
        self.calls.append(("GET", url, kw))
        return self.handler(url, kw)

    def post(self, url: str, **kw: Any) -> StubResponse:
        self.calls.append(("POST", url, kw))
        return self.handler(url, kw)

    def close(self) -> None:
        """requests.Session.close 자리 (할 일 없음)."""
