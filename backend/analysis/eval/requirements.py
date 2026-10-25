"""E1 요구사항 평가표: 자동으로 확인할 수 있는 항목을 테스트·저장된 결과로 점검해 markdown 표를 만든다.

  python -m backend.analysis.eval.requirements [--out docs/mvp/requirements_check.md] [--skip-tests]

- 요구사항 번호는 docs/module_prototype2.md §1.4 (R1~R12) 를 따른다. 자동 점검 = 해당 pytest 통과 + 저장된 실행(data/analysis_store, 결과 DB)에서 확인한 사실.
- 사람이 봐야 하는 항목(문장 품질, 화면 사용성)은 '수동' 으로 표시만 한다.
"""

from __future__ import annotations

import argparse
import datetime as dt
import json
import re
import subprocess
import sys
from pathlib import Path
from typing import Any

from backend.analysis.m5_backtest_report.report_check import _find_all

ROOT = Path(__file__).resolve().parents[3]
TESTS = ROOT / "backend" / "tests" / "analysis"

# 요구사항 → (설명, 자동 점검에 쓰는 테스트 표현식(-k), 결과 점검 함수 이름)
REQS: list[tuple[str, str, str, str | None]] = [
    ("R1", "프로필 관리: 1개 프로필, 입력 검증, 버전 보존", "test_profile_validation_and_versions or test_start_requires_profile_and_idea", "profile_versions"),
    ("R2", "아이디어 통합: 부족·충돌 항목을 한 번에 하나씩 질문, 조건 확인", "test_three_turns_converge_and_confirm_is_idempotent or test_hard_error_gives_fix_not_question or test_free_text_and_unaskable_field or test_limit_blocks_and_skip", "dialog_questions"),
    ("R3", "실제 자료 근거: 모든 인용이 DB 자료(뉴스·재무·계산값)에 실존, 기준일 이후 자료 금지", "test_lookahead_is_blocked_everywhere or test_report_seven_sections_and_citations or test_request_derived_and_lookahead", "evidence_index"),
    ("R4", "실행 가능한 전략: 선정·비중·제약·리밸런싱 규칙이 리포트에 설명", "test_targets_constraints or test_selection_mixed_market_and_facts", "construction_section"),
    ("R5", "검증 결과만 제공: 비중·조건·숫자 대조, 실패 시 리포트 차단", "test_validation_and_bundle or test_report_seven_sections_and_citations", "report_gate"),
    ("R6", "과거 평가: 수익·위험·비교지수·계산 조건", "test_backtest_invariants", "performance_section"),
    ("R7/R8", "리포트 본문과 근거·출처 연결 (인용 번호 → 출처 패널)", "test_report_seven_sections_and_citations", "citations_in_text"),
    ("R9", "실행 기록: 단계별 상태와 결과 요약", "test_runner_failure_cancels_remaining_and_records_steps or test_worker_runs_confirmed_request_and_persists", "run_steps"),
    ("R10", "수정 요청: 기준 전략, 변경 확인, 별도 수정안·비교", "test_propose_filters_frozen_unknown_and_hard_errors or test_revision_dialog_confirm_run_and_compare or test_revision_api", "comparisons"),
    ("R11", "모의투자: 명시적 활성화(미리보기→등록), 가상 성과·추적 상태", "test_preview_defaults_and_rules or test_create_equals_preview_and_first_snapshot or test_refresh_incremental_idempotent_contribution_rebalance or test_stop_resume_skips_rebalances_and_leaves_gap or test_refresh_marks_delayed_when_required_price_missing", "papers"),
    ("R12", "진행 상태 표시: 다섯 묶음·단계 상태 폴링", "test_queue_fifo_position_cancel_and_stale or test_health_and_options", "run_steps"),
    ("C-04", "결정론: 같은 입력 → 같은 요청 지문·LLM 캐시", "test_same_inputs_same_fingerprint_and_cache", None),
    ("C-06", "선견 금지: 기준일 이후 자료 요청은 예외, 창 첫날 휴장일 처리", "test_lookahead_is_blocked_everywhere or test_panel_starting_on_one_markets_holiday or test_derive_moves_as_of_off_a_holiday", None),
    ("C-12", "금지 표현: '보장'·'확실' 등 단정 표현 없음 (부정형 제외)", "test_report_seven_sections_and_citations", "banned_phrases"),
]
BANNED = ("보장", "확실한 수익", "무위험", "반드시 오른다", "손실 없음")
ALLOWED = ("무위험수익률", "무위험 수익률", "무위험 이자율", "무위험 금리")  # 샤프 비율 설명에 쓰는 전문 용어
NEGATION = ("않", "아니", "없", "못", "안 ", "아닌", "말고")


def run_tests(expr: str) -> tuple[bool, str]:
    cmd = [sys.executable, "-m", "pytest", str(TESTS), "-q", "-p", "no:cacheprovider", "-k", expr]
    r = subprocess.run(cmd, cwd=ROOT, capture_output=True, text=True, timeout=1800)
    last = (r.stdout.strip().splitlines() or [""])[-1]
    return r.returncode == 0 and "passed" in last, last


def _results_db() -> Any:
    from backend.analysis.common.dbconn import open_analysis_repository

    repo = open_analysis_repository()
    return getattr(repo, "results", repo)


def _store() -> Any:
    from backend.analysis.common.store import JsonStore

    return JsonStore()


def _reports(repo: Any, limit: int = 50) -> list[tuple[str, dict[str, Any], dict[str, Any]]]:
    out = []
    for row in repo.list_reports(limit):
        rid = row["report_id"]
        rep, art = repo.get_report(rid), repo.get_run_artifact(rid)
        if rep and art:
            out.append((rid, rep["doc"] if "doc" in rep else rep, art["results"]))
    return out


# ───────────────────────── 저장된 결과 점검 ─────────────────────────
def profile_versions() -> str:
    doc = _store().read("profile.json")
    if not doc:
        return "프로필 없음"
    return f"프로필 1개, 버전 {len(doc.get('versions', []))}개 (현재 v{doc.get('current_version')})"


def dialog_questions() -> str:
    from backend.analysis.common.store import RequestStore

    docs = RequestStore(_store()).list()
    asked = [len(d.questions) for d in docs]
    multi = sum(1 for n in asked if n > 1)
    return f"요청 {len(docs)}건, 질문 {sum(asked)}개 (한 요청 최대 {max(asked) if asked else 0}개, 상한 {max((d.max_questions for d in docs), default=0)})" + (f", 2개 이상 질문 {multi}건" if multi else "")


def evidence_index() -> str:
    repo = _results_db()
    n_rep, n_ev, bad = 0, 0, 0
    for _rid, doc, res in _reports(repo):
        n_rep += 1
        idx = res.get("evidence_index", {})
        n_ev += len(idx)
        as_of = str(res["request"]["derived"]["as_of"])
        bad += sum(1 for e in idx.values() if (e.get("published_at") or "") > as_of)
    return f"리포트 {n_rep}건, 근거 {n_ev}건, 기준일 이후 뉴스 {bad}건"


def construction_section() -> str:
    repo = _results_db()
    ok = sum(1 for _r, doc, _res in _reports(repo) if any(s["id"] == "construction" and s["blocks"] for s in doc.get("sections", [])))
    return f"구성·운용 섹션 있음 {ok}건"


def report_gate() -> str:
    from backend.analysis.common.store import JsonStore
    from backend.analysis.executor.queue import Queue

    q = Queue(JsonStore())
    runs = q.list()
    fails = [r for r in runs if r.status == "failed"]
    gate = [r for r in fails if (r.error_code or "") in ("REPORT_CHECK_FAILED", "REPORT_INVALID") or "리포트 검증" in (r.error_message or "")]
    return f"실행 {len(runs)}건 중 실패 {len(fails)}건 (리포트 검증 실패로 차단 {len(gate)}건)"


def performance_section() -> str:
    repo = _results_db()
    n = 0
    for _r, doc, res in _reports(repo):
        perf = next((s for s in doc.get("sections", []) if s["id"] == "performance"), None)
        if perf and res.get("backtest", {}).get("benchmarks"):
            n += 1
    return f"과거 성과 섹션 + 비교지수 {n}건"


def citations_in_text() -> str:
    repo = _results_db()
    from backend.analysis.common.citations import CITE_RE as cite
    n_cite, n_unknown, n_rep = 0, 0, 0
    for _r, doc, res in _reports(repo):
        n_rep += 1
        idx = res.get("evidence_index", {})
        for s in doc.get("sections", []):
            for b in s.get("blocks", []):
                for t in (b.get("items", []) if b.get("type") == "paragraphs" else []) or []:
                    for m in cite.finditer(t if isinstance(t, str) else t.get("text_ko", "")):
                        n_cite += 1
                        n_unknown += m.group(1) not in idx
    return f"리포트 {n_rep}건, 인용 {n_cite}개, 색인에 없는 인용 {n_unknown}개"


def run_steps() -> str:
    repo = _results_db()
    rows = repo.list_reports(50)
    n_runs, n_steps = 0, 0
    for row in rows:
        steps = repo.get_steps(row["report_id"])
        if steps:
            n_runs += 1
            n_steps += len(steps)
    return f"실행 {n_runs}건에 단계 기록 {n_steps}행 (평균 {n_steps / n_runs:.1f})" if n_runs else "단계 기록 없음"


def comparisons() -> str:
    d = _store().path("comparisons")
    files = sorted(d.glob("*.json")) if d.exists() else []
    same = sum(1 for f in files if json.loads(f.read_text(encoding="utf-8")).get("same_window"))
    return f"비교 문서 {len(files)}건 (같은 평가 조건 {same}건)"


def papers() -> str:
    from backend.analysis.common.store import PaperStore

    docs = PaperStore(_store()).list()
    active = sum(1 for d in docs if d["status"] == "active")
    return f"모의투자 {len(docs)}건 (진행 {active}, 중지 {len(docs) - active})"


def banned_phrases() -> str:
    repo = _results_db()
    hits = 0
    n = 0
    for _r, doc, _res in _reports(repo):
        n += 1
        paras = [t for s_ in doc.get("sections", []) for b in s_.get("blocks", []) if b.get("type") == "paragraphs" for t in b.get("items", [])]
        for t in paras:
            for a_ in ALLOWED:
                t = t.replace(a_, "")
            for w in BANNED:
                for i in _find_all(t, w):
                    tail = t[i + len(w): i + len(w) + 18]
                    if not any(m in tail for m in NEGATION):
                        hits += 1
    return f"리포트 {n}건의 본문 문단에서 단정 표현 {hits}건 (부정형·'무위험수익률' 용어 제외)"


CHECKS = {f.__name__: f for f in (profile_versions, dialog_questions, evidence_index, construction_section, report_gate, performance_section, citations_in_text, run_steps, comparisons, papers, banned_phrases)}


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="backend.analysis.eval.requirements")
    ap.add_argument("--out", default=str(ROOT / "docs" / "mvp" / "requirements_check.md"))
    ap.add_argument("--skip-tests", action="store_true")
    a = ap.parse_args(argv)
    rows = []
    for rid, desc, expr, check in REQS:
        if a.skip_tests:
            t_ok, t_msg = None, "(생략)"
        else:
            t_ok, t_msg = run_tests(expr)
        fact = ""
        if check:
            try:
                fact = CHECKS[check]()
            except Exception as e:  # noqa: BLE001
                fact = f"점검 실패: {type(e).__name__}: {e}"[:160]
        rows.append((rid, desc, t_ok, t_msg, fact))
        print(f"{rid:<6} tests={'통과' if t_ok else ('생략' if t_ok is None else '실패')} | {fact}", flush=True)
    lines = [f"# 요구사항 자동 점검 ({dt.date.today()})", "", "자동 점검 = 해당 pytest 통과 여부 + 저장된 실행(로컬 저장소·결과 DB)에서 확인한 사실. 문장 품질·화면 사용성은 사람이 봅니다.", "",
             "| 요구 | 내용 | 테스트 | 저장된 결과에서 확인한 것 |", "| --- | --- | --- | --- |"]  # fmt: skip
    for rid, desc, t_ok, t_msg, fact in rows:
        lines.append(f"| {rid} | {desc} | {'✅ ' if t_ok else ('– ' if t_ok is None else '❌ ')}{t_msg} | {fact} |")
    lines += ["", "수동 확인 항목: 리포트 문장의 자연스러움(R4·R7), 화면 흐름(R2·R12), 모의투자 화면(R11)."]
    out = Path(a.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text("\n".join(lines) + "\n", encoding="utf-8")
    print("written", out)
    return 0 if all(r[2] in (True, None) for r in rows) else 1


if __name__ == "__main__":
    sys.exit(main())
