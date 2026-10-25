"""순서를 지키는 병렬 실행 도우미 (라운드 4, 결정 R2).

결과를 입력 순서대로 돌려주므로 순차 실행과 같은 산출물이 나온다. 첫 예외가 나면 아직 시작하지 않은 항목은 건너뛰고,
진행 중인 것은 끝나길 기다린 뒤 입력 순서상 가장 앞의 예외를 다시 던진다. 취소 요청은 항목 시작 전마다 확인한다.
"""

from __future__ import annotations

import threading
from collections.abc import Callable, Sequence
from concurrent.futures import FIRST_COMPLETED, CancelledError, ThreadPoolExecutor, wait
from typing import Any, TypeVar

from backend.analysis.errors import CancelRequested

T = TypeVar("T")
R = TypeVar("R")


class _Skipped(Exception):
    """앞선 예외·취소 때문에 시작하지 않은 항목."""


def map_ordered(
    items: Sequence[T],
    fn: Callable[[T], R],
    *,
    max_workers: int = 1,
    on_done: Callable[[int, int], None] | None = None,
    cancel_check: Callable[[], bool] | None = None,
) -> list[R]:
    """items 마다 fn 을 최대 max_workers 개 동시에 실행하고 결과를 입력 순서로 돌려준다. on_done(완료 수, 전체) 는 완료마다 한 번."""
    n = len(items)
    if n == 0:
        return []
    if max_workers <= 1 or n == 1:
        out: list[R] = []
        for i, it in enumerate(items):
            if cancel_check and cancel_check():
                raise CancelRequested("취소 요청")
            out.append(fn(it))
            if on_done:
                on_done(i + 1, n)
        return out
    stop = threading.Event()

    def _wrapped(it: T) -> R:
        if stop.is_set() or (cancel_check and cancel_check()):
            raise _Skipped()
        return fn(it)

    results: list[Any] = [None] * n
    errors: dict[int, BaseException] = {}
    done_n = 0
    with ThreadPoolExecutor(max_workers=min(max_workers, n), thread_name_prefix="mfs-par") as pool:
        futs = {pool.submit(_wrapped, it): i for i, it in enumerate(items)}
        pending = set(futs)
        while pending:
            done, pending = wait(pending, return_when=FIRST_COMPLETED)
            for f in done:
                i = futs[f]
                try:
                    results[i] = f.result()
                    done_n += 1
                    if on_done:
                        on_done(done_n, n)
                except (_Skipped, CancelledError):
                    errors.setdefault(i, _Skipped())
                except BaseException as e:  # noqa: BLE001 — 첫 예외: 나머지 중단
                    errors[i] = e
                    stop.set()
                    for q in pending:
                        q.cancel()
            if cancel_check and cancel_check() and not stop.is_set():
                stop.set()
                for q in pending:
                    q.cancel()
    if cancel_check and cancel_check():
        raise CancelRequested("취소 요청")
    real = sorted((i, e) for i, e in errors.items() if not isinstance(e, _Skipped))
    if real:
        raise real[0][1]
    if errors:  # 취소 없이 건너뛴 것만 있을 수는 없다 (방어)
        raise CancelRequested("취소 요청")
    return results


def run_ordered(ctx: Any, stage: str, items: Sequence[T], fn: Callable[[T], R], *, max_workers: int) -> list[R]:
    """RunContext 용: 진행 표시(ctx.progress)와 취소 확인(ctx.cancel_check)을 꽂은 map_ordered."""
    return map_ordered(items, fn, max_workers=max_workers, on_done=lambda i, n: ctx.progress(stage, i, n), cancel_check=ctx.cancel_check)
