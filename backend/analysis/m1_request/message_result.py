"""「말로 보태기」 결과 판정 (이슈 #14 7번). 말을 보낸 턴의 전후 모습을 비교해 반영됨 / 반영 안 됨 / 확인 필요를 정한다.

말은 조건 값을 직접 바꾸지 않는다 (DialogService.message): 아이디어 보충으로 붙어 의도 해석(테마)을 바꾸거나,
값을 바꿔야 하면 LLM 이 확인 질문을 제안한다. 그래서 판정은 '무엇이 실제로 달라졌나' 만 본다 — 문장을 따로 해석하지 않는다.
- 이 턴에 새 질문이 생김 → needs_confirmation (그 질문에 답해야 조건이 바뀐다)
- 해석한 테마나 조건 표시값이 달라짐 → applied
- 둘 다 아님 → not_applied (보탠 말은 아이디어 보충으로 남는다)
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from backend.analysis.schemas.dialog import ConditionRow, MessageChange, MessageResult, Question

THEMES_FIELD = "intent.themes"
THEMES_LABEL_KO = "해석한 테마"


@dataclass(frozen=True)
class Snapshot:
    """한 시점의 비교 대상: 조건 행의 표시값 {field: (라벨, 값)} 과 해석한 테마 이름들."""

    rows: dict[str, tuple[str, str]] = field(default_factory=dict)
    themes: str = ""


def snapshot(rows: list[ConditionRow], intent: dict[str, Any] | None) -> Snapshot:
    """아이디어 행은 뺀다 (보탠 말이 아이디어 끝에 붙어 늘 달라 보인다 — 화면의 전후 비교 diffRows 와 같은 규칙)."""
    themes = [str(t.get("label_ko") or t.get("id") or "") for t in ((intent or {}).get("interpretation") or {}).get("themes") or []]
    return Snapshot(rows={r.field: (r.label_ko, r.value_ko) for r in rows if r.group_ko != "아이디어"}, themes=", ".join(t for t in themes if t))


def _names(qs: list[Question]) -> str:
    return "·".join(f"「{q.field_label_ko or q.field}」" for q in qs)


def judge(text: str, at: str, before: Snapshot, after: Snapshot, *, asked: list[Question], closed: list[Question], capped: bool) -> MessageResult:
    """asked = 이 턴에 새로 생긴 질문들, closed = 말을 보내며 답하지 않은 채 닫힌 질문들, capped = 질문 상한에 닿아 더 묻지 못함."""
    changes = [MessageChange(field=f, label_ko=lab, before_ko=before.rows[f][1], after_ko=val)
               for f, (lab, val) in after.rows.items() if f in before.rows and before.rows[f][1] != val]  # fmt: skip
    if after.themes and before.themes != after.themes:
        changes.append(MessageChange(field=THEMES_FIELD, label_ko=THEMES_LABEL_KO, before_ko=before.themes or "—", after_ko=after.themes))
    tail = f" 답하지 않은 {_names(closed)} 질문은 건너뛰고 지금 조건 그대로 둡니다." if closed else ""
    seqs = {"question_seqs": [q.seq for q in asked], "closed_seqs": [q.seq for q in closed]}
    if asked:
        return MessageResult(text=text, at=at, outcome="needs_confirmation", changes=changes, **seqs,
                             note_ko=f"{_names(asked)} 항목을 확인하는 질문이 생겼습니다. 질문에 답하면 조건에 반영됩니다.{tail}")  # fmt: skip
    if changes:
        what = "조건에 반영했습니다." if any(c.field != THEMES_FIELD for c in changes) else "아이디어 해석(테마)에 반영했습니다. 조건 값은 그대로입니다."
        return MessageResult(text=text, at=at, outcome="applied", changes=changes, note_ko=what + tail, **seqs)
    note = "해석한 테마도 그대로입니다. 보탠 말은 아이디어 보충으로 남아 리포트 요약에 들어갑니다."
    if capped:
        note += " 추가 질문을 모두 써서 더 묻지 않았습니다."
    note += " 종목·숫자 조건은 「조건 바꾸기」로 직접 바꿔 주세요." + tail
    return MessageResult(text=text, at=at, outcome="not_applied", note_ko=note, **seqs)
