"""요구사항 R10 실증: 저장된 리포트에 자연어 수정 요청 → 대화(첫 보기로 답) → 확정 → 실행 → 원안 대비 비교 문서.

  PYTHONPATH=. python docs/mvp/evaluation/scripts/revision_e2e.py <base_run_id> "<수정 요청 문장>" <out.json>
"""

from __future__ import annotations

import json
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path.cwd()))
from backend.analysis.eval.run_scenarios import Api, answer_questions  # noqa: E402

TERMINAL = ("success", "partial", "failed", "cancelled")


def main() -> int:
    base_run, text, out_p = sys.argv[1], sys.argv[2], Path(sys.argv[3])
    api = Api("http://127.0.0.1:8001/api/v1")
    base = api.ok("GET", f"/runs/{base_run}")
    report_id = base["report_id"]
    t0 = time.time()
    state = api.ok("POST", f"/reports/{report_id}/revisions", {"text": text})
    rid = state["request_id"]
    qa: list[dict] = []
    state = answer_questions(api, rid, state, "all", qa)
    rec = {"base_run": base_run, "base_report": report_id, "text": text, "request_id": rid, "dialog_state": state.get("state"), "qa": qa,
           "revision": state.get("revision"), "dialog_seconds": round(time.time() - t0, 1)}
    if state.get("state") != "ready":
        rec["blocked"] = state.get("blocked_reason_ko") or state.get("hard_errors")
        out_p.write_text(json.dumps(rec, ensure_ascii=False, indent=1), encoding="utf-8")
        print(json.dumps(rec, ensure_ascii=False)[:1500])
        return 1
    conf = api.ok("POST", f"/requests/{rid}/confirm")
    run_id = conf["run_id"]
    rec["run_id"] = run_id
    t1 = time.time()
    run = {}
    while time.time() - t1 < 1800:
        run = api.ok("GET", f"/runs/{run_id}")
        if run.get("status") in TERMINAL:
            break
        time.sleep(5)
    rec.update({"status": run.get("status"), "run_seconds": round(time.time() - t1, 1), "error": run.get("error"), "new_report": run.get("report_id")})
    if run.get("report_id"):
        try:
            rec["comparison"] = api.ok("GET", f"/reports/{run['report_id']}/comparison")
        except Exception as e:  # noqa: BLE001
            rec["comparison_error"] = f"{type(e).__name__}: {e}"[:300]
    out_p.write_text(json.dumps(rec, ensure_ascii=False, indent=1, default=str), encoding="utf-8")
    cmp = rec.get("comparison") or {}
    print(json.dumps({k: rec.get(k) for k in ("base_report", "request_id", "dialog_state", "run_id", "status", "run_seconds", "new_report", "comparison_error")}, ensure_ascii=False))
    print("comparison keys:", list(cmp.keys())[:30])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
