"""분석 워커 (단일 프로세스). 큐에서 확정된 요청을 꺼내 파이프라인을 돌리고 run_step·run_artifact·report 를 DB 에 쓴다.

  python -m backend.analysis.executor.worker [--once] [--poll-sec 2]

API 프로세스(uvicorn 워커 여럿)는 분석을 실행하지 않는다. 워커는 DB advisory lock + 파일 잠금으로 하나만 돈다.
큐가 비어 있으면 한 시간에 한 번 진행 중인 모의투자를 최신 거래일까지 갱신한다 (settings.tracking).
"""

from __future__ import annotations

import argparse
import datetime as dt
import fcntl
import logging
import os
import sys
import time
from pathlib import Path
from typing import Any

from backend.analysis.common.llm import make_llm
from backend.analysis.common.store import ComparisonStore, JsonStore, RequestStore
from backend.analysis.executor.context import RunContext
from backend.analysis.executor.queue import Queue, pid_alive
from backend.analysis.executor.runner import run
from backend.analysis.m2_data.market_data import MarketData
from backend.analysis.m5_backtest_report.compare import compare
from backend.analysis.m5_backtest_report.persist import db_step_hook, save_report, save_results
from backend.analysis.m6_tracking.paper import refresh_all_papers
from backend.analysis.paths import run_dir
from backend.analysis.schemas.backtest import BacktestRequest
from backend.analysis.common.dbconn import open_analysis_repository
from backend.analysis.settings import AnalysisSettings

log = logging.getLogger(__name__)


def execute_run(entry_run_id: str, *, repo: Any, store: JsonStore, settings: AnalysisSettings, queue: Queue, llm=None) -> str:
    """큐에서 claim 된 실행 하나를 끝까지. 돌려주는 값 = 최종 상태."""
    reqs = RequestStore(store)
    q = queue.get(entry_run_id)
    doc = reqs.load(q.request_id)
    if doc.status != "confirmed" or not doc.effective_request:
        queue.finish(entry_run_id, "failed", error_code="REQUEST_NOT_CONFIRMED", error_message="확정되지 않은 요청입니다")
        return "failed"
    rdir = run_dir(entry_run_id)
    llm = llm or make_llm(settings.llm, run_dir=rdir, run_id=entry_run_id)
    md = MarketData(repo, settings)
    req = dict(doc.effective_request)
    bt_req = None
    if doc.overrides.get("_backtest_request"):
        bt_req = BacktestRequest.model_validate(doc.overrides["_backtest_request"])
    ctx = RunContext(run_id=entry_run_id, request=req, repo=repo, md=md, llm=llm, settings=settings, run_dir=rdir, intent=doc.intent,
                     bt_req=bt_req, allow_fewer_at_start=bool(doc.overrides.get("_allow_fewer_at_start")),
                     cancel_check=lambda: queue.is_cancel_requested(entry_run_id))  # fmt: skip
    outcome = run(ctx, on_step=db_step_hook(repo, entry_run_id))
    status = outcome.status
    report_id = None
    if status in ("success", "partial"):
        try:
            results = ctx.outputs["13_results"]
            params = {**settings.snapshot(), "descriptor": ctx.desc_info, "stages": [s.__dict__ for s in outcome.steps]}
            save_results(repo, entry_run_id, ctx.request_id, results, params, llm.usage_summary())
            if "14_report" in ctx.outputs:
                doc14 = ctx.outputs["14_report"]
                save_report(repo, entry_run_id, doc14, strategy_name=doc14["header"].get("chosen_label_ko"),
                            request_summary=doc14["header"].get("subtitle_ko"), as_of=dt.date.fromisoformat(str(ctx.request["derived"]["as_of"])))  # fmt: skip
                report_id = entry_run_id
        except Exception as e:  # noqa: BLE001
            log.exception("persist failed")
            status = "failed"
            queue.finish(entry_run_id, status, error_code="PERSIST_FAILED", error_message=f"{type(e).__name__}: {e}"[:500])
            return status
    if report_id and doc.mode == "revision" and doc.base_report_id:
        try:
            base_art = repo.get_run_artifact(doc.base_report_id)
            if base_art:
                cmp_doc = compare(base_art["results"], ctx.outputs["13_results"], base_report_id=doc.base_report_id, revised_report_id=entry_run_id,
                                  revision_text=(doc.revision.text if doc.revision else None))  # fmt: skip
                cmp_doc["revision_text"] = (doc.revision.text if doc.revision else "")
                cmp_doc["revision_changes"] = [c.model_dump() for c in (doc.revision.changes if doc.revision else [])]
                ComparisonStore(store).save(cmp_doc)
                log.info("[worker] comparison saved: %s", cmp_doc["comparison_id"])
            else:
                log.warning("[worker] base results %s not found; comparison skipped", doc.base_report_id)
        except Exception:  # noqa: BLE001
            log.exception("[worker] comparison failed")
    queue.finish(entry_run_id, status, report_id=report_id, error_code=(outcome.error or {}).get("code"), error_message=(outcome.error or {}).get("message"))
    reqs_doc = reqs.load(q.request_id)
    if reqs_doc.run_id != entry_run_id:
        reqs_doc.run_id = entry_run_id
        reqs.save(reqs_doc)
    return status


def run_once(*, repo: Any, store: JsonStore, settings: AnalysisSettings, llm=None) -> str | None:
    """큐에 대기 건이 있으면 하나 실행하고 상태를 돌려준다. 없으면 None."""
    queue = Queue(store)
    queue.recover_stale(pid_alive)
    entry = queue.claim_next()
    if entry is None:
        return None
    log.info("[worker] run %s (request %s)", entry.run_id, entry.request_id)
    try:
        return execute_run(entry.run_id, repo=repo, store=store, settings=settings, queue=queue, llm=llm)
    except Exception as e:  # noqa: BLE001
        log.exception("[worker] run %s crashed", entry.run_id)
        queue.finish(entry.run_id, "failed", error_code="WORKER_ERROR", error_message=f"{type(e).__name__}: {e}"[:500])
        return "failed"


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="backend.analysis.executor.worker")
    ap.add_argument("--once", action="store_true", help="대기 건 하나만 처리하고 종료")
    ap.add_argument("--poll-sec", type=float, default=2.0)
    ap.add_argument("--db", default=None)
    ap.add_argument("-v", "--verbose", action="store_true")
    a = ap.parse_args(argv)
    logging.basicConfig(level=logging.DEBUG if a.verbose else logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    settings = AnalysisSettings.load()
    repo = open_analysis_repository(a.db)
    store = JsonStore()
    lock_path = Path(store.root) / "worker.lock"
    # "a+" 로 열어야 한다: "w" 는 잠금을 얻기 전에 파일을 비우므로, 두 번째 일꾼이 잠금에 실패하고 나가더라도 살아 있는 일꾼의 pid 가 지워져
    # /health 가 '일꾼 꺼짐'으로 잘못 보인다 (라운드 5 재실행에서 발견). 잠금을 얻은 뒤에만 pid 를 다시 쓴다.
    with open(lock_path, "a+") as fh:
        try:
            fcntl.flock(fh, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError:
            print("another worker holds the lock; exiting", file=sys.stderr)
            return 2
        fh.seek(0)
        fh.truncate()
        fh.write(str(os.getpid()))
        fh.flush()
        with repo.job_lock("analysis_worker") as ok:
            if not ok:
                print("another worker holds the DB lock; exiting", file=sys.stderr)
                return 2
            log.info("[worker] pid %s store=%s llm=%s", os.getpid(), store.root, settings.llm.mode)
            last_paper = 0.0
            while True:
                status = run_once(repo=repo, store=store, settings=settings)
                if a.once:
                    return 0
                if status is None:
                    if settings.tracking.refresh_on_worker_idle and time.time() - last_paper >= settings.tracking.refresh_interval_s:
                        last_paper = time.time()
                        try:
                            done = refresh_all_papers(repo, store, settings)
                            if done:
                                log.info("[worker] paper refreshed: %s", done)
                        except Exception:  # noqa: BLE001
                            log.exception("[worker] paper refresh failed")
                    time.sleep(a.poll_sec)
    return 0


if __name__ == "__main__":
    sys.exit(main())
