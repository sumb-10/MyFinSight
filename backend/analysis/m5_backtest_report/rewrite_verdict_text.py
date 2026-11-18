"""저장된 리포트의 「종합 판단 → 선택 근거 자세히 보기」 본문을 새 작성 규칙으로 다시 쓴다 (2026-11-16 사용자 요청).

    .venv/bin/python -m backend.analysis.m5_backtest_report.rewrite_verdict_text run_20261111_144205_f16d [다른 id ...]
    .venv/bin/python -m backend.analysis.m5_backtest_report.rewrite_verdict_text --all
    .venv/bin/python -m backend.analysis.m5_backtest_report.rewrite_verdict_text --limitations-only run_20261111_144205_f16d
      → 「확인한 한계」 카드만 기존 분석 결과로 다시 만든다 (모델 호출 없음, 다른 덧씌운 글은 그대로)
    .venv/bin/python -m backend.analysis.m5_backtest_report.rewrite_verdict_text --section7 run_20261111_144205_f16d
      → 7. 주의 사항과 전제 전체: 중요한 주의 사항·참고 문장(코드), 확인한 한계(코드), 분석의 전제(14b)·다음 분석에서 바꿔 볼 조건(14a)(모델)
        — 다른 섹션의 덧씌운 글은 그대로

- 리포트 문서는 결과 DB 에서 읽기만 한다(sqlite 읽기 전용). 분석 결과는 output/<id>/13_results.json.
- 14a(해석) → 14b(서술)를 실제 모델로 다시 부르고, 종합 판단 섹션의 두 문단만 바꾼 문서로 기존 리포트 검사(check)를 돌린다.
  종합 판단 문단에 오류가 있으면 한 번 피드백을 주고 다시 받는다. 그래도 오류면 저장하지 않는다(원래 글 그대로).
- 통과하면 text_overrides 파일(<store>/report_text_overrides/<id>.json)에 두 문단 묶음만 저장한다. 화면은 읽을 때 덧씌운다.
- 모델 사용량은 그 폴더의 _usage.jsonl 에 남긴다(실행 폴더 output/<id>/ 의 파일은 건드리지 않는다).
"""

from __future__ import annotations

import argparse
import datetime as dt
import json
import sqlite3
import sys
from pathlib import Path
from typing import Any

from backend.analysis.common.citations import split_grouped_in
from backend.analysis.common.llm import make_llm, messages_from_prompts
from backend.analysis.common.prompts import load_prompts
from backend.analysis.common.store import JsonStore
from backend.analysis.m5_backtest_report import caution_text as C
from backend.analysis.m5_backtest_report import report_blocks as B
from backend.analysis.m5_backtest_report import text_overrides as T
from backend.analysis.m5_backtest_report.report import (
    _drop_matched_suggestions,
    _retry_feedback,
    call_interpret,
    call_market,
    call_narrate,
    ensure_drawdown_story,
    ensure_forward_text,
    ensure_hindsight,
    ensure_request_followups,
    ensure_selection_changes,
    ensure_validation_text,
    facts_for_interpret,
    facts_for_narrate,
    selection_change_gaps,
)
from backend.analysis.m5_backtest_report.report_check import check
from backend.analysis.paths import output_root
from backend.analysis.settings import AnalysisSettings

DEFAULT_DB = Path("data/analysis_results.db")


def _doc(db: Path, report_id: str) -> dict[str, Any] | None:
    con = sqlite3.connect(f"file:{db}?mode=ro", uri=True)  # 읽기 전용
    try:
        row = con.execute("select doc_json from report where report_id = ?", (report_id,)).fetchone()
    finally:
        con.close()
    return json.loads(row[0]) if row else None


def _ids(db: Path) -> list[str]:
    con = sqlite3.connect(f"file:{db}?mode=ro", uri=True)
    try:
        return [r[0] for r in con.execute("select report_id from report order by created_at")]
    finally:
        con.close()


def _verdict_errors(doc: dict[str, Any], R: dict[str, Any], settings: AnalysisSettings) -> tuple[list[str], list[str]]:
    """덧씌우는 문단(종합 판단·비중 결정 설명)에서 난 오류·메모만 (다른 섹션은 저장된 글 그대로라 여기서 고칠 수 없다).
    종목이 빠진 이유를 날짜·사유와 함께 쓰지 않았으면 그것도 다시 받을 오류로 본다 (2026-11-16)."""
    res = check(doc, R, settings)
    texts = next((b["items"] for s in doc["sections"] if s["id"] == "verdict" for b in s["blocks"] if b.get("src") == "14b"), [])
    mine = ("verdict:", "construction:", "performance:", "market:")
    return [e for e in res.errors if e.startswith(mine)] + selection_change_gaps(texts, R), [w for w in res.warnings if w.startswith(mine)]


def rewrite_one(report_id: str, *, db: Path, store: JsonStore, settings: AnalysisSettings, llm: Any, log=print) -> dict[str, Any]:
    doc = _doc(db, report_id)
    if doc is None:
        return {"report_id": report_id, "status": "skipped", "reason": "결과 DB 에 리포트가 없음"}
    rp = output_root() / report_id / "13_results.json"
    if not rp.exists():
        return {"report_id": report_id, "status": "skipped", "reason": "13_results.json 없음"}
    R = json.loads(rp.read_text())
    chosen = (doc.get("header") or {}).get("chosen_portfolio_id") or B.chosen_portfolio_id(R)[0]
    no_matched = not any(x.get("kind") == "matched" for x in R["backtest"]["portfolios"])
    try:
        interp = call_interpret(R, chosen, llm)
        narr = call_narrate(R, chosen, interp, llm)
        market = split_grouped_in(call_market(R, llm))  # 「주요 뉴스와 공시」 (2026-11-16)
    except Exception as e:  # noqa: BLE001 — 예전 결과에 새 사실이 없거나 모델 호출 실패: 원래 글 그대로 둔다
        return {"report_id": report_id, "status": "failed", "reason": f"{type(e).__name__}: {str(e)[:300]}"}
    interp, narr = split_grouped_in(interp), split_grouped_in(narr)
    trial = T.apply(doc, {"overview_ko": narr["overview_ko"], "risk_fit_ko": interp["risk_fit_ko"], "construction_ko": narr.get("construction_ko"), "performance_ko": interp.get("performance_ko"), "forward_ko": narr.get("forward_ko"), "market_ko": market.get("market_ko")})
    errs, warns = _verdict_errors(trial, R, settings)
    tries = 1
    if errs:  # 한 번 다시: 해석(14a)과 서술(14b) 모두 오류 목록을 피드백으로
        log(f"  {report_id}: 검사 오류 {len(errs)}건 → 다시 받음: {errs[:3]}")
        tries = 2
        system, user = load_prompts("14a_interpret", facts_json=json.dumps(facts_for_interpret(R, chosen), ensure_ascii=False, indent=1, default=str))
        a = llm.complete_json("14a_interpret", [*messages_from_prompts(system, user), {"role": "assistant", "content": json.dumps(interp, ensure_ascii=False)}, _retry_feedback(errs)])
        for k, v in interp.items():
            a.setdefault(k, v)
        if no_matched:
            _drop_matched_suggestions(a, ("performance_ko", "risk_fit_ko", "validation_ko", "next_actions_ko"))
        ensure_drawdown_story(a, R, chosen)
        ensure_hindsight(a, R, chosen)
        ensure_request_followups(a, R)
        interp = split_grouped_in(a)
        system, user = load_prompts("14b_narrate", facts_json=json.dumps(facts_for_narrate(R, chosen, interp), ensure_ascii=False, indent=1, default=str),
                                    interpretation_json=json.dumps(interp, ensure_ascii=False, indent=1))  # fmt: skip
        n = llm.complete_json("14b_narrate", [*messages_from_prompts(system, user), {"role": "assistant", "content": json.dumps(narr, ensure_ascii=False)}, _retry_feedback(errs)])
        if no_matched:
            _drop_matched_suggestions(n, ("overview_ko", "reconsideration_ko"))
        ensure_selection_changes(n, R)
        ensure_forward_text(n, R)
        narr = split_grouped_in(n)
        trial = T.apply(doc, {"overview_ko": narr.get("overview_ko"), "risk_fit_ko": interp.get("risk_fit_ko"), "construction_ko": narr.get("construction_ko"), "performance_ko": interp.get("performance_ko"), "forward_ko": narr.get("forward_ko"), "market_ko": market.get("market_ko")})
        errs, warns = _verdict_errors(trial, R, settings)
    if errs or "text_override" not in trial:
        return {"report_id": report_id, "status": "failed", "reason": "검사 오류: " + "; ".join(errs[:5]) if errs else "문서 모양이 달라 덧씌울 수 없음"}
    T.save(store, report_id, {"created_at": dt.datetime.now().isoformat(timespec="seconds"), "chosen_portfolio_id": chosen, "tries": tries,
                              "limitations": B.limitation_items(R),  # 「확인한 한계」 (코드로 만든 글)
                              "summary_patch": C.summary_patch(R, chosen), "assumptions_ko": narr.get("assumptions_ko") or [], "reconsideration_ko": narr.get("reconsideration_ko") or [],
                              "next_actions_ko": interp.get("next_actions_ko") or [],  # 7. 주의 사항과 전제 (2026-11-16)
                              "overview_ko": narr["overview_ko"], "risk_fit_ko": interp["risk_fit_ko"], "construction_ko": narr.get("construction_ko") or [], "performance_ko": interp.get("performance_ko") or [], "forward_ko": narr.get("forward_ko") or [], "market_ko": market.get("market_ko") or [], "check_warnings": warns,
                              # 다시 쓰기 전 글 (비교·되돌리기용 기록 — 화면은 원본 DB 문서를 쓰므로 파일을 지우면 원래 글)
                              "original": {"overview_ko": next(b["items"] for s in doc["sections"] if s["id"] == "verdict" for b in s["blocks"] if b.get("src") == "14b"),
                                           "risk_fit_ko": next(b["items"] for s in doc["sections"] if s["id"] == "verdict" for b in s["blocks"] if b.get("src") == "14a")}})  # fmt: skip
    return {"report_id": report_id, "status": "saved", "tries": tries, "warnings": warns}


def rewrite_limitations(report_id: str, *, db: Path, store: JsonStore, with_cautions: bool = False) -> dict[str, Any]:
    """「확인한 한계」 카드만 13_results.json 으로 다시 만든다 (모델 호출·백테스트 없음). 이미 덧씌운 다른 글은 그대로 두고 이 항목만 더한다.
    with_cautions: 「중요한 주의 사항」·「참고」 쉬운 문장(summary_patch)도 코드로 다시 만든다 (--code-only)."""
    doc = _doc(db, report_id)
    if doc is None:
        return {"report_id": report_id, "status": "skipped", "reason": "결과 DB 에 리포트가 없음"}
    rp = output_root() / report_id / "13_results.json"
    if not rp.exists():
        return {"report_id": report_id, "status": "skipped", "reason": "13_results.json 없음"}
    R = json.loads(rp.read_text())
    items = B.limitation_items(R)
    extra = {"summary_patch": C.summary_patch(R, (doc.get("header") or {}).get("chosen_portfolio_id") or B.chosen_portfolio_id(R)[0])} if with_cautions else {}
    if with_cautions:  # 4. 「조건별 근거 보기」 두 표 (코드로 만든 표, 2026-11-16)
        chosen0 = (doc.get("header") or {}).get("chosen_portfolio_id") or B.chosen_portfolio_id(R)[0]
        extra["validation_tables"] = list(B.validation_tables(R, chosen0))
    if with_cautions:  # 「다음 분석에서 바꿔 볼 조건」 중 반영되지 않은 종목 요청 문장만 코드 문장으로 (다른 항목은 그대로, 2026-11-16)
        prev0 = store.read(T.rel(report_id), None) or {}
        na = {"next_actions_ko": list(prev0.get("next_actions_ko") or (doc.get("summary") or {}).get("next_actions_ko") or [])}
        if na["next_actions_ko"] and ensure_request_followups(na, R):
            extra["next_actions_ko"] = na["next_actions_ko"]
    if "limitations" not in (T.apply(doc, {"limitations": items}).get("text_override") or {}).get("sections", []):
        return {"report_id": report_id, "status": "failed", "reason": "문서에 「확인한 한계」 카드가 없음"}
    prev = store.read(T.rel(report_id), None)
    prev = prev if isinstance(prev, dict) else {}
    prev.pop("report_id", None)
    prev.pop("version", None)
    original = prev.get("original") if isinstance(prev.get("original"), dict) else {}
    if "limitations" not in original:  # 처음 덮을 때의 원래 카드 (되돌리기·비교용)
        original = {**original, "limitations": next((b["items"] for s in doc["sections"] if s["id"] == "assumptions" for b in s["blocks"] if b.get("type") == "cards" and b.get("title_ko") == "확인한 한계"), [])}
    T.save(store, report_id, {**prev, **extra, "created_at": prev.get("created_at") or dt.datetime.now().isoformat(timespec="seconds"),
                              "limitations_updated_at": dt.datetime.now().isoformat(timespec="seconds"), "limitations": items, "original": original})  # fmt: skip
    return {"report_id": report_id, "status": "saved", "cards": len(items)}


def _s7_errors(doc: dict[str, Any], R: dict[str, Any], settings: AnalysisSettings) -> tuple[list[str], list[str]]:
    res = check(doc, R, settings)
    return [e for e in res.errors if e.startswith("assumptions:")], [w for w in res.warnings if w.startswith("assumptions:")]


def _s7_original(doc: dict[str, Any]) -> dict[str, Any]:
    sec = next((s for s in doc["sections"] if s["id"] == "assumptions"), {"blocks": []})
    sm = doc.get("summary") or {}
    return {"assumptions_ko": next((b["items"] for b in sec["blocks"] if b.get("type") == "paragraphs" and b.get("src") == "14b"), []),
            "next_actions_ko": list(sm.get("next_actions_ko") or []),
            "summary": {"verdict": {k: (sm.get("verdict") or {}).get(k) for k in ("period_note_ko", "cautions_ko", "label_ko")},
                        "validation": {k: (sm.get("validation") or {}).get(k) for k in ("info_notes_ko", "rules_ko")}}}  # fmt: skip


def rewrite_section7(report_id: str, *, db: Path, store: JsonStore, settings: AnalysisSettings, llm: Any, log=print) -> dict[str, Any]:
    """7. 주의 사항과 전제만 다시 쓴다 (2026-11-16 사용자 요청). 주의·참고·한계는 코드로, 분석의 전제(14b)·다음 조건(14a)은 모델로.
    검사(check)의 assumptions 오류가 있으면 한 번 피드백을 주고 다시 받고, 그래도 오류면 저장하지 않는다. 이미 덧씌운 다른 섹션 글은 그대로 둔다."""
    doc = _doc(db, report_id)
    if doc is None:
        return {"report_id": report_id, "status": "skipped", "reason": "결과 DB 에 리포트가 없음"}
    rp = output_root() / report_id / "13_results.json"
    if not rp.exists():
        return {"report_id": report_id, "status": "skipped", "reason": "13_results.json 없음"}
    R = json.loads(rp.read_text())
    chosen = (doc.get("header") or {}).get("chosen_portfolio_id") or B.chosen_portfolio_id(R)[0]
    prev = store.read(T.rel(report_id), None)
    prev = prev if isinstance(prev, dict) else {}
    base = T.apply(doc, prev)  # 지금 화면에 보이는 문서 위에서 검사
    code_part = {"summary_patch": C.summary_patch(R, chosen), "limitations": B.limitation_items(R)}
    try:
        interp = split_grouped_in(call_interpret(R, chosen, llm))
        narr = split_grouped_in(call_narrate(R, chosen, interp, llm))
    except Exception as e:  # noqa: BLE001
        return {"report_id": report_id, "status": "failed", "reason": f"{type(e).__name__}: {str(e)[:300]}"}

    def part() -> dict[str, Any]:
        return {"assumptions_ko": narr.get("assumptions_ko") or [], "reconsideration_ko": narr.get("reconsideration_ko") or [], "next_actions_ko": interp.get("next_actions_ko") or []}

    errs, warns = _s7_errors(T.apply(base, {**code_part, **part()}), R, settings)
    tries = 1
    if errs:
        log(f"  {report_id}: 7번 검사 오류 {len(errs)}건 → 다시 받음: {errs[:3]}")
        tries = 2
        system, user = load_prompts("14a_interpret", facts_json=json.dumps(facts_for_interpret(R, chosen), ensure_ascii=False, indent=1, default=str))
        a = llm.complete_json("14a_interpret", [*messages_from_prompts(system, user), {"role": "assistant", "content": json.dumps(interp, ensure_ascii=False)}, _retry_feedback(errs)])
        interp = {**interp, **{k: v for k, v in a.items() if v}}
        ensure_request_followups(interp, R)
        interp = split_grouped_in(interp)
        system, user = load_prompts("14b_narrate", facts_json=json.dumps(facts_for_narrate(R, chosen, interp), ensure_ascii=False, indent=1, default=str),
                                    interpretation_json=json.dumps(interp, ensure_ascii=False, indent=1))  # fmt: skip
        n = llm.complete_json("14b_narrate", [*messages_from_prompts(system, user), {"role": "assistant", "content": json.dumps(narr, ensure_ascii=False)}, _retry_feedback(errs)])
        narr = split_grouped_in({**narr, **{k: v for k, v in n.items() if v}})
        errs, warns = _s7_errors(T.apply(base, {**code_part, **part()}), R, settings)
    if errs:
        return {"report_id": report_id, "status": "failed", "reason": "검사 오류: " + "; ".join(errs[:5])}
    if not part()["assumptions_ko"] or not part()["next_actions_ko"]:
        return {"report_id": report_id, "status": "failed", "reason": "분석의 전제 또는 다음 조건 글이 비어 있음"}
    prev.pop("report_id", None)
    prev.pop("version", None)
    original = prev.get("original") if isinstance(prev.get("original"), dict) else {}
    if "section7" not in original:
        original = {**original, "section7": _s7_original(doc)}
    T.save(store, report_id, {**prev, **code_part, **part(), "created_at": prev.get("created_at") or dt.datetime.now().isoformat(timespec="seconds"),
                              "section7_updated_at": dt.datetime.now().isoformat(timespec="seconds"), "section7_tries": tries, "section7_check_warnings": warns, "original": original})  # fmt: skip
    return {"report_id": report_id, "status": "saved", "tries": tries, "warnings": warns}


def rewrite_validation(report_id: str, *, db: Path, store: JsonStore, settings: AnalysisSettings, llm: Any, log=print) -> dict[str, Any]:
    """4. 「조건별 근거 보기」만: 두 표는 코드로, 문단(validation_ko)은 14a 로 다시 쓰고 코드 문장(선택 이유)을 첫머리에. 다른 덧씌운 글은 그대로 (2026-11-16)."""
    doc = _doc(db, report_id)
    if doc is None:
        return {"report_id": report_id, "status": "skipped", "reason": "결과 DB 에 리포트가 없음"}
    rp = output_root() / report_id / "13_results.json"
    if not rp.exists():
        return {"report_id": report_id, "status": "skipped", "reason": "13_results.json 없음"}
    R = json.loads(rp.read_text())
    chosen = (doc.get("header") or {}).get("chosen_portfolio_id") or B.chosen_portfolio_id(R)[0]
    prev = store.read(T.rel(report_id), None)
    prev = prev if isinstance(prev, dict) else {}
    base = T.apply(doc, prev)
    tables = list(B.validation_tables(R, chosen))
    try:
        interp = call_interpret(R, chosen, llm)
    except Exception as e:  # noqa: BLE001
        return {"report_id": report_id, "status": "failed", "reason": f"{type(e).__name__}: {str(e)[:300]}"}
    ensure_validation_text(interp, R, chosen)
    val = split_grouped_in(interp).get("validation_ko") or []
    res = check(T.apply(base, {"validation_ko": val, "validation_tables": tables}), R, settings)
    errs = [e for e in res.errors if e.startswith("performance:")]
    if errs or not val:
        return {"report_id": report_id, "status": "failed", "reason": "검사 오류: " + "; ".join(errs[:5]) if errs else "문단이 비어 있음"}
    original = prev.get("original") if isinstance(prev.get("original"), dict) else {}
    if "validation" not in original:
        sec = next((s for s in doc["sections"] if s["id"] == "performance"), {"blocks": []})
        original = {**original, "validation": [b for b in sec["blocks"] if b.get("group_ko") == "검증 상세" and b.get("type") in ("paragraphs", "table")]}
    prev.pop("report_id", None)
    prev.pop("version", None)
    T.save(store, report_id, {**prev, "validation_ko": val, "validation_tables": tables, "original": original,
                              "created_at": prev.get("created_at") or dt.datetime.now().isoformat(timespec="seconds"),
                              "validation_updated_at": dt.datetime.now().isoformat(timespec="seconds"),
                              "validation_check_warnings": [w for w in res.warnings if w.startswith("performance:")]})  # fmt: skip
    return {"report_id": report_id, "status": "saved"}


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("ids", nargs="*")
    ap.add_argument("--all", action="store_true")
    ap.add_argument("--db", type=Path, default=DEFAULT_DB)
    ap.add_argument("--limitations-only", action="store_true", help="「확인한 한계」 카드만 코드로 다시 만든다 (모델 호출 없음)")
    ap.add_argument("--code-only", action="store_true", help="코드로 만드는 7번 글(확인한 한계·중요한 주의 사항·참고)만 다시 만든다 (모델 호출 없음)")
    ap.add_argument("--validation", action="store_true", help="4. 조건별 근거 보기만 다시 쓴다 (두 표는 코드, 문단은 모델)")
    ap.add_argument("--section7", action="store_true", help="7. 주의 사항과 전제만 다시 쓴다 (주의·한계는 코드, 전제·다음 조건은 모델)")
    a = ap.parse_args(argv)
    if a.limitations_only or a.code_only:
        store = JsonStore()
        res = [rewrite_limitations(rid, db=a.db, store=store, with_cautions=a.code_only) for rid in (_ids(a.db) if a.all else a.ids)]
        print(json.dumps(res, ensure_ascii=False, indent=1))
        return 0 if all(r["status"] != "failed" for r in res) else 1
    settings = AnalysisSettings.load()
    store = JsonStore()
    usage = store.path(f"{T.DIR}/_usage.jsonl")
    usage.parent.mkdir(parents=True, exist_ok=True)
    llm = make_llm(settings.llm, usage_log=usage)
    ids = _ids(a.db) if a.all else a.ids
    out = []
    for rid in ids:
        print(f"→ {rid}", flush=True)
        r = (rewrite_validation if a.validation else rewrite_section7 if a.section7 else rewrite_one)(rid, db=a.db, store=store, settings=settings, llm=llm)
        print(f"  {r['status']}" + (f" ({r.get('reason')})" if r.get("reason") else "") + (f" tries={r.get('tries')}" if r.get("tries") else ""), flush=True)
        out.append(r)
    print(json.dumps(out, ensure_ascii=False, indent=1))
    return 0 if all(r["status"] != "failed" for r in out) else 1


if __name__ == "__main__":
    sys.exit(main())
