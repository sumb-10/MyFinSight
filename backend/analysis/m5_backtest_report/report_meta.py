"""리포트 이름·숨김 기록. 리포트 문서는 불변이므로 로컬 저장소의 파일 하나(report_meta.json)에 따로 둔다 (DB 스키마 변경 없음).

삭제는 숨김이다: 목록과 리포트 조회에서만 빠지고 리포트·결과·실행 기록·모의투자는 그대로 남는다.
"""

from __future__ import annotations

import datetime as dt
from typing import Any

from backend.analysis.common.store import JsonStore

NAME_MAX = 40


def _now() -> str:
    return dt.datetime.now(dt.UTC).isoformat(timespec="seconds")


def one_line(text: str | None) -> str:
    """첫 줄만, 연속 공백은 하나로."""
    return " ".join((text or "").split("\n")[0].split())


def auto_name(*, idea: str | None, request_summary: str | None, strategy_name: str | None, run_id: str) -> str:
    """자동 이름: 투자 아이디어 → 요청 요약 → 선택 전략 → 실행 ID (프런트 lib/reportName 과 같은 순서)."""
    return one_line(idea) or one_line(request_summary) or one_line(strategy_name) or run_id


def name_view(report_id: str, auto: str, meta: dict[str, Any] | None) -> dict[str, Any]:
    """프런트 제안 계약 ProposedReportName 모양."""
    custom = (meta or {}).get("custom_name")
    return {"report_id": report_id, "auto_ko": auto, "custom_ko": custom, "display_ko": custom or auto, "updated_at": (meta or {}).get("renamed_at")}


class ReportMetaStore:
    REL = "report_meta.json"

    def __init__(self, store: JsonStore) -> None:
        self.store = store

    def all(self) -> dict[str, dict[str, Any]]:
        return self.store.read(self.REL, {}) or {}

    def get(self, report_id: str) -> dict[str, Any]:
        return self.all().get(report_id) or {}

    def is_deleted(self, report_id: str) -> bool:
        return bool(self.get(report_id).get("deleted_at"))

    def _update(self, report_id: str, **changes: Any) -> dict[str, Any]:
        with self.store.locked("report_meta"):
            data = self.all()
            entry = {**(data.get(report_id) or {}), **changes}
            entry = {k: v for k, v in entry.items() if v is not None}
            if entry:
                data[report_id] = entry
            else:
                data.pop(report_id, None)
            self.store.write(self.REL, data)
            return entry

    def rename(self, report_id: str, custom_name: str | None) -> dict[str, Any]:
        """custom_name=None 이면 자동 이름으로 되돌린다."""
        return self._update(report_id, custom_name=custom_name, renamed_at=_now())

    def delete(self, report_id: str) -> dict[str, Any]:
        return self._update(report_id, deleted_at=_now())

    def restore(self, report_id: str) -> dict[str, Any]:
        """숨김 해제 (API 없음, 관리·복구용)."""
        return self._update(report_id, deleted_at=None)
