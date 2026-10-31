"""프로세스 간 파일 잠금. POSIX(맥·리눅스)는 fcntl.flock, Windows 는 msvcrt.locking.

두 OS 에서 같은 모양으로 쓴다: lock(fh) 는 잠글 때까지 기다리고, lock(fh, blocking=False) 는 못 잠그면 바로
OSError 를 낸다. unlock(fh) 로 풀며, 풀지 않아도 프로세스가 끝나면 OS 가 회수한다 (worker.lock 이 이 성질에 기댄다).

Windows 는 잠근 바이트를 다른 프로세스가 읽지도 못하고(flock 은 읽기를 막지 않음), 잠금 위치가 파일 포인터에
붙어 있다. 그래서 파일 내용(worker.lock 의 pid)과 겹치지 않도록 파일 끝 너머의 1바이트만 잠그고, 파일 포인터는
잠그기 전 위치로 되돌린다. Windows 의 기다리는 잠금(LK_LOCK)은 10초 뒤 포기하므로, flock 처럼 끝까지 기다리도록
비차단 잠금을 짧은 간격으로 다시 시도한다.
"""

from __future__ import annotations

import os
import time
from typing import IO

if os.name == "nt":
    import msvcrt

    _OFFSET = 1 << 30  # 파일 내용과 절대 겹치지 않는 먼 위치. 파일 끝 너머도 잠글 수 있다
    _RETRY_SEC = 0.05

    def _locking(fh: IO, mode: int) -> None:
        fh.flush()
        fd = fh.fileno()
        pos = os.lseek(fd, 0, os.SEEK_CUR)
        os.lseek(fd, _OFFSET, os.SEEK_SET)
        try:
            msvcrt.locking(fd, mode, 1)
        finally:
            os.lseek(fd, pos, os.SEEK_SET)

    def lock(fh: IO, *, blocking: bool = True) -> None:
        if not blocking:
            _locking(fh, msvcrt.LK_NBLCK)
            return
        while True:
            try:
                _locking(fh, msvcrt.LK_NBLCK)
                return
            except OSError:
                time.sleep(_RETRY_SEC)

    def unlock(fh: IO) -> None:
        _locking(fh, msvcrt.LK_UNLCK)

else:
    import fcntl

    def lock(fh: IO, *, blocking: bool = True) -> None:
        fcntl.flock(fh, fcntl.LOCK_EX if blocking else fcntl.LOCK_EX | fcntl.LOCK_NB)

    def unlock(fh: IO) -> None:
        fcntl.flock(fh, fcntl.LOCK_UN)
