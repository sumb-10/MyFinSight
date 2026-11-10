"""모의투자 이름 방식 기록. portfolio.json 은 스키마 검증을 받는 원본이라, 이름은 로컬 저장소의 파일 하나(paper_meta.json)에 따로 둔다
(리포트 이름 report_meta.json 과 같은 방식, 스키마 변경 없음).

이름 방식: linked(기본, 기록 없음) = 원본 리포트의 지금 이름을 따라감 / custom = 직접 정한 이름 그대로 (리포트 이름을 바꿔도 안 바뀜).
"""

from __future__ import annotations

import datetime as dt
from typing import Any

from backend.analysis.common.store import JsonStore
from backend.analysis.errors import RequestInvalid
from backend.analysis.m5_backtest_report.report_meta import NAME_MAX


def _now() -> str:
    return dt.datetime.now(dt.UTC).isoformat(timespec="seconds")


def clean_name(name: str | None) -> str:
    """직접 정한 이름 검사: 연속 공백은 하나로, 비었거나 NAME_MAX 자를 넘으면 REQUEST_INVALID (화면 입력칸과 같은 한도)."""
    out = " ".join((name or "").split())
    if not out:
        raise RequestInvalid("모의투자 이름을 입력해 주세요", details={"fields": {"name_ko": "비어 있음"}})
    if len(out) > NAME_MAX:
        raise RequestInvalid(f"모의투자 이름은 {NAME_MAX}자 이하여야 합니다", details={"fields": {"name_ko": f"{NAME_MAX}자 이하"}})
    return out


class PaperMetaStore:
    REL = "paper_meta.json"

    def __init__(self, store: JsonStore) -> None:
        self.store = store

    def all(self) -> dict[str, dict[str, Any]]:
        return self.store.read(self.REL, {}) or {}

    def custom_names(self) -> dict[str, str]:
        """모의투자 ID → 직접 정한 이름 (linked 는 빠짐)."""
        return {pid: e["custom_name"] for pid, e in self.all().items() if e.get("custom_name")}

    def set_custom(self, paper_id: str, name: str) -> None:
        """이미 검사한 이름(clean_name)을 받는다."""
        self._update(paper_id, {"custom_name": name, "renamed_at": _now()})

    def link(self, paper_id: str) -> None:
        """리포트 이름 따라가기로 되돌린다 (기록을 지움)."""
        self._update(paper_id, None)

    def _update(self, paper_id: str, entry: dict[str, Any] | None) -> None:
        with self.store.locked("paper_meta"):
            data = self.all()
            if entry:
                data[paper_id] = entry
            elif paper_id in data:
                data.pop(paper_id)
            else:
                return
            self.store.write(self.REL, data)
