"""JSON·JSONC 입출력과 정규화 직렬화 (캐시 키·fingerprint 용)."""

from __future__ import annotations

import datetime as dt
import hashlib
import json
import re
from pathlib import Path
from typing import Any

_COMMENT_RE = re.compile(r'("(?:\\.|[^"\\])*")|//[^\n]*|/\*.*?\*/', re.DOTALL)


def load_jsonc(path: str | Path) -> Any:
    """// 와 /* */ 주석, 끝 쉼표가 있는 JSON 을 읽는다 (module_mockup/input/*.jsonc)."""
    text = Path(path).read_text(encoding="utf-8")
    stripped = _COMMENT_RE.sub(lambda m: m.group(1) or "", text)
    stripped = re.sub(r",(\s*[}\]])", r"\1", stripped)
    return json.loads(stripped)


def load_json(path: str | Path) -> Any:
    return json.loads(Path(path).read_text(encoding="utf-8"))


def _default(o: Any) -> Any:
    if isinstance(o, dt.datetime | dt.date):
        return o.isoformat()
    if hasattr(o, "model_dump"):
        return o.model_dump(mode="json")
    if hasattr(o, "tolist"):
        return o.tolist()
    if hasattr(o, "item"):
        return o.item()
    return str(o)


def dump_json(obj: Any, path: str | Path) -> Path:
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(obj, indent=2, ensure_ascii=False, default=_default), encoding="utf-8")
    return p


def canonical_json(obj: Any) -> str:
    """키 정렬·공백 제거. 같은 내용이면 같은 문자열 (캐시 키, request_fingerprint)."""
    return json.dumps(obj, sort_keys=True, ensure_ascii=False, separators=(",", ":"), default=_default)


def sha256_hex(text: str, n: int | None = None) -> str:
    h = hashlib.sha256(text.encode("utf-8")).hexdigest()
    return h[:n] if n else h


def now_iso() -> str:
    return dt.datetime.now().astimezone().isoformat(timespec="seconds")
