"""리포트 「내 요청」 기록 (제안 계약 proposed.request_log, 이슈 #14 11번): 이 리포트를 만든 요청의 아이디어, 답한 질문, 말로 보탠 요청과 그 결과, 최종 조건.

요청 문서(requests/<id>.json)는 확정 뒤 바뀌지 않는다 → 실행이 끝날 때 리포트에 붙여 저장하고(worker), 이 기능 전 리포트는 읽을 때 같은 함수로 만든다.
말로 보탠 요청의 결과 기록(message_results)이 생기기 전 요청에 보탠 말이 있으면 그 결과를 알 수 없어 붙이지 않는다
(화면은 예전처럼 「보낸 문장은 불러올 수 있는 기록이 없다」 안내를 보여 준다).
"""

from __future__ import annotations

import logging
from typing import Any

from backend.analysis.common.store import JsonStore, ProfileStore, RequestStore
from backend.analysis.errors import NotFound
from backend.analysis.executor.queue import Queue
from backend.analysis.m1_request import assemble
from backend.analysis.m1_request.conditions import condition_rows, fmt
from backend.analysis.m1_request.validate import label
from backend.analysis.m5_backtest_report.execution_orders import PROPOSED_CONTRACT
from backend.analysis.schemas.dialog import AnalysisRequestDoc, ConditionRow, Question

log = logging.getLogger(__name__)
SENT_PREFIX = "[추가 요청]"  # DialogService.message 가 아이디어 보충에 붙이는 머리


def _base_doc(store: JsonStore, doc: AnalysisRequestDoc) -> AnalysisRequestDoc | None:
    """수정안이면 원안의 요청 문서 (비교 기준이자, 수정안이 앞에 물려받은 보충 문장의 출처)."""
    if doc.mode != "revision" or not doc.base_report_id:
        return None
    try:
        return RequestStore(store).load(Queue(store).get(doc.base_report_id).request_id)
    except NotFound:
        return None


def final_rows(store: JsonStore, doc: AnalysisRequestDoc, base_doc: AnalysisRequestDoc | None = None) -> list[ConditionRow]:
    """확정 조건 표 — 조건 확인 화면(DialogService.state 의 confirmation.rows)과 같은 비교 기준: 새 요청은 프로필 기본값, 수정안은 원안의 확정 요청."""
    req = doc.effective_request or doc.draft_request
    if not req:
        return []
    base = assemble.build(ProfileStore(store).version(doc.profile_version), doc.idea, request_id=doc.request_id, created_at=doc.created_at)
    if base_doc is not None and base_doc.effective_request:
        base = dict(base_doc.effective_request)
    return condition_rows(req, base, answered_fields={q.field: q.seq for q in doc.questions if q.applied}, derived=doc.derived)


def _value_ko(field: str, value: Any, req: dict[str, Any]) -> str:
    if isinstance(value, dict) and field in ("horizon",):  # 여러 하위 값을 한 질문으로 정한 경우
        return ", ".join(f"{label(f'{field}.{k}')} {fmt(f'{field}.{k}', v, req)}" for k, v in value.items())
    return fmt(field, value, req)


def applied_ko(q: Question, req: dict[str, Any]) -> str | None:
    """답이 조건에 어떻게 들어갔는지 한 줄 (건너뛴 질문은 None)."""
    if q.skipped:
        return None
    a = q.applied or {}
    if not a:
        return "아이디어 보충으로 전달" if (q.free_text or q.field == "natural_language.idea") else None
    parts = [f"{label(k)} → {_value_ko(k, v, req)}" for k, v in (a.get("patch") or {}).items() if not str(k).startswith("_")]
    if not parts and not a.get("clarification"):
        parts = [f"{label(a['field'])} → {_value_ko(a['field'], a.get('value'), req)}"]
    if a.get("clarification"):
        parts.append(f"아이디어 보충: {a['clarification']}")
    return "; ".join(parts)


def build(doc: AnalysisRequestDoc, rows: list[ConditionRow], *, inherited: int = 0) -> dict[str, Any] | None:
    """inherited = 앞에서부터 원안에게 물려받은 보충 문장 수 (수정안). 기록 없이 보낸 말이 있으면 None."""
    sent = sum(1 for c in doc.idea_clarifications[inherited:] if c.startswith(SENT_PREFIX))
    if sent > len(doc.message_results):
        return None
    req = doc.effective_request or doc.draft_request or {}
    return {
        "idea": doc.idea,
        "qa": [{"question_ko": q.question_ko, "answer_ko": q.answer or "", "at": q.answered_at, "applied_ko": applied_ko(q, req)} for q in doc.questions if q.answered_at],
        "messages": [{"text": m.text, "at": m.at, "outcome": m.outcome, "changes_ko": [f"{c.label_ko}: {c.before_ko} → {c.after_ko}" for c in m.changes],
                      "note_ko": m.note_ko or None} for m in doc.message_results],  # fmt: skip
        "final_conditions": [{"label_ko": r.label_ko, "value_ko": r.value_ko, "changed": r.changed} for r in rows if r.group_ko != "아이디어"],
    }


def for_request(store: JsonStore, doc: AnalysisRequestDoc) -> dict[str, Any] | None:
    """요청 문서 → request_log. 어떤 이유로든 만들지 못하면 None (리포트 저장·조회를 막지 않는다)."""
    try:
        base_doc = _base_doc(store, doc)
        return build(doc, final_rows(store, doc, base_doc), inherited=len(base_doc.idea_clarifications) if base_doc else 0)
    except Exception as e:  # noqa: BLE001
        log.warning("내 요청 기록을 만들지 못했습니다 (%s): %r", doc.request_id, e)
        return None


def with_request_log(doc: dict[str, Any], request_log: dict[str, Any] | None) -> dict[str, Any]:
    """문서 사본에 proposed.request_log 를 붙인다 (원본은 그대로, 다른 proposed 값은 유지). 없으면 문서 그대로."""
    if request_log is None:
        return doc
    return {**doc, "proposed": {"contract": PROPOSED_CONTRACT, **(doc.get("proposed") or {}), "request_log": request_log}}


def on_read(store: JsonStore, doc: dict[str, Any]) -> dict[str, Any]:
    """저장 문서에 기록이 없으면(이 기능 전 리포트) 요청 문서에서 만들어 응답에만 붙인다."""
    if (doc.get("proposed") or {}).get("request_log") is not None or not doc.get("request_id"):
        return doc
    try:
        req_doc = RequestStore(store).load(str(doc["request_id"]))
    except (NotFound, ValueError):
        return doc
    return with_request_log(doc, for_request(store, req_doc))
