"""FIFO 큐 (K11). runs.json 한 파일이 큐 상태다. 모든 갱신은 RunIndex 잠금 안에서.

상태: queued → running → success | partial | failed | cancelled. 취소 요청은 cancel_requested_at 으로 표시하고
워커가 단계 경계에서 확인한다 (대기 중이면 즉시 cancelled). 죽은 워커의 running 은 recover_stale 이 failed 로.
"""

from __future__ import annotations

import os
from typing import Any

from backend.analysis.common.jsonio import now_iso
from backend.analysis.common.store import JsonStore, RunIndex
from backend.analysis.errors import Conflict, NotFound
from backend.analysis.paths import run_dir
from backend.analysis.schemas.run import RunIndexEntry

TERMINAL = ("success", "partial", "failed", "cancelled")


class Queue:
    def __init__(self, store: JsonStore) -> None:
        self.store = store
        self.index = RunIndex(store)

    # ───────────────────────── 등록·조회 ─────────────────────────
    def enqueue(self, run_id: str, request_id: str, *, llm_mode: str | None = None, scenario: str | None = None) -> int:
        with self.index.locked():
            runs = self.index.load()
            if any(r.run_id == run_id for r in runs):
                raise Conflict(f"실행 {run_id} 이 이미 큐에 있습니다")
            runs.append(RunIndexEntry(run_id=run_id, request_id=request_id, status="queued", queued_at=now_iso(), output_dir=str(run_dir(run_id)),
                                      llm_mode=llm_mode, scenario=scenario))  # fmt: skip
            self.index.save(runs)
        return self.position(run_id)

    def position(self, run_id: str) -> int | None:
        """대기 순번 (1 = 다음 차례). running 이 있으면 +1. 대기 중이 아니면 None."""
        runs = self.index.load()
        me = next((r for r in runs if r.run_id == run_id), None)
        if me is None:
            raise NotFound(f"실행 {run_id} 이 없습니다")
        if me.status != "queued":
            return None
        queued = [r.run_id for r in runs if r.status == "queued"]  # 저장 순서 = 등록 순서 (안정 정렬)
        running = any(r.status == "running" for r in runs)
        return queued.index(run_id) + 1 + (1 if running else 0)

    def get(self, run_id: str) -> RunIndexEntry:
        return self.index.get(run_id)

    def remove(self, run_id: str) -> bool:
        """끝난(실패·취소) 실행 기록을 목록에서 지운다 (실행 중·대기 중은 지우지 않음). 지웠으면 True."""
        with self.index.locked():
            runs = self.index.load()
            victim = next((r for r in runs if r.run_id == run_id), None)
            if victim is None or victim.status in ("queued", "running"):
                return False
            self.index.save([r for r in runs if r.run_id != run_id])
            return True

    def list(self, limit: int | None = None) -> list[RunIndexEntry]:
        runs = sorted(self.index.load(), key=lambda r: r.queued_at, reverse=True)
        return runs[:limit] if limit else runs

    def length(self) -> int:
        return sum(1 for r in self.index.load() if r.status == "queued")

    # ───────────────────────── 워커 ─────────────────────────
    def claim_next(self, worker_pid: int | None = None) -> RunIndexEntry | None:
        """가장 오래된 queued 를 running 으로 바꿔 돌려준다. 이미 running 이 있으면 None (단일 워커)."""
        with self.index.locked():
            runs = self.index.load()
            if any(r.status == "running" for r in runs):
                return None
            queued = sorted((r for r in runs if r.status == "queued"), key=lambda r: r.queued_at)
            if not queued:
                return None
            nxt = queued[0]
            upd = nxt.model_copy(update={"status": "running", "started_at": now_iso(), "worker_pid": worker_pid or os.getpid()})
            self.index.save([upd if r.run_id == nxt.run_id else r for r in runs])
            return upd

    def finish(self, run_id: str, status: str, *, report_id: str | None = None, error_code: str | None = None, error_message: str | None = None) -> RunIndexEntry:
        if status not in TERMINAL:
            raise ValueError(status)
        return self.index.update(run_id, status=status, finished_at=now_iso(), report_id=report_id, error_code=error_code, error_message=error_message)

    def request_cancel(self, run_id: str) -> RunIndexEntry:
        with self.index.locked():
            runs = self.index.load()
            me = next((r for r in runs if r.run_id == run_id), None)
            if me is None:
                raise NotFound(f"실행 {run_id} 이 없습니다")
            if me.status in TERMINAL:
                return me
            if me.status == "queued":
                upd = me.model_copy(update={"status": "cancelled", "finished_at": now_iso(), "cancel_requested_at": now_iso()})
            else:
                upd = me.model_copy(update={"cancel_requested_at": now_iso()})
            self.index.save([upd if r.run_id == run_id else r for r in runs])
            return upd

    def is_cancel_requested(self, run_id: str) -> bool:
        try:
            return self.index.get(run_id).cancel_requested_at is not None
        except NotFound:
            return False

    def recover_stale(self, pid_alive) -> list[str]:
        """죽은 워커(pid 없음)의 running 을 failed 로. 자동 재개는 하지 않는다 (부록 D)."""
        fixed = []
        with self.index.locked():
            runs = self.index.load()
            out = []
            for r in runs:
                if r.status == "running" and not pid_alive(r.worker_pid):
                    r = r.model_copy(update={"status": "failed", "finished_at": now_iso(), "error_code": "WORKER_DIED",
                                             "error_message": "작업자가 중단되어 실행이 끊겼습니다. 다시 분석을 시작해 주세요."})  # fmt: skip
                    fixed.append(r.run_id)
                out.append(r)
            if fixed:
                self.index.save(out)
        return fixed


def pid_alive(pid: int | None) -> bool:
    if not pid:
        return False
    try:
        os.kill(pid, 0)
        return True
    except OSError:
        return False
    except Exception:  # noqa: BLE001
        return False


def entry_to_dict(e: RunIndexEntry) -> dict[str, Any]:
    return e.model_dump(mode="json")
