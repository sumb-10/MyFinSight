"""요청 조립 (M1-02 ①): 프로필 버전 + 아이디어 + 이번 조건 덮어쓰기(필드 경로 → 값) + 자유 입력 보충 → UserRequest dict."""

from __future__ import annotations

import copy
from typing import Any

REQUEST_BLOCKS = ("profile", "capital", "horizon", "risk", "constraints", "strategy_preference")


def get_path(obj: dict[str, Any], path: str) -> Any:
    cur: Any = obj
    for k in path.split("."):
        if not isinstance(cur, dict) or k not in cur:
            return None
        cur = cur[k]
    return cur


def set_path(obj: dict[str, Any], path: str, value: Any) -> None:
    """경로에 값을 넣는다. 값과 기존 값이 둘 다 dict 이면 부분 갱신 (예: "horizon" 에 {start_date, backtest_years} 만 바꾸기)."""
    keys = path.split(".")
    cur = obj
    for k in keys[:-1]:
        cur = cur.setdefault(k, {})
    last = keys[-1]
    if isinstance(value, dict) and isinstance(cur.get(last), dict):
        cur[last] = {**cur[last], **value}
    else:
        cur[last] = value


def build(profile_version: dict[str, Any], idea: str, *, overrides: dict[str, Any] | None = None, clarifications: list[str] | None = None,
          request_id: str, created_at: str, language: str = "ko") -> dict[str, Any]:  # fmt: skip
    """프로필 기본값 위에 덮어쓰기를 적용한 요청 dict (검증 전)."""
    req: dict[str, Any] = {"request_id": request_id, "created_at": created_at}
    for b in REQUEST_BLOCKS:
        req[b] = copy.deepcopy(profile_version.get(b) or {})
    req.setdefault("profile", {}).setdefault("user_id", "default")
    text = idea.strip()
    if clarifications:
        text += "\n\n[보충 답변]\n" + "\n".join(f"- {c.strip()}" for c in clarifications if c.strip())
    req["natural_language"] = {"idea": text, "language": language}
    for path, value in (overrides or {}).items():
        if path.startswith("_"):  # 내부용 (예: _backtest_request)
            continue
        if path == "natural_language.idea":
            continue  # 아이디어는 clarifications 로 다룬다
        set_path(req, path, value)
    return req


def diff_fields(base: dict[str, Any], new: dict[str, Any], prefix: str = "") -> list[str]:
    """두 요청 dict 의 다른 필드 경로 목록 (리프 기준)."""
    out: list[str] = []
    keys = set(base) | set(new)
    for k in sorted(keys):
        p = f"{prefix}{k}"
        a, b = base.get(k), new.get(k)
        if isinstance(a, dict) and isinstance(b, dict):
            out += diff_fields(a, b, p + ".")
        elif a != b:
            out.append(p)
    return out
