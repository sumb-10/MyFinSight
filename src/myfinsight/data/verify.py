"""M02-06(추가) 출처 간 가격 교차검증.

같은 (종목, 날짜) 를 여러 출처가 저장했으면 값을 비교해 CONSENSUS 행을 만들고 출처별로 표시한다.
수집(jobs.py)·품질 판단(M02-03 quality.py)과 따로 두고, 저장소(M02-04) 메서드로만 DB 에 닿는다.

    from myfinsight.data.verify import verify_step, reverify
    verify_step(repo)                                   # 아직 검증 안 된 행만
    reverify(repo, date(2026, 1, 1), date(2026, 9, 30))  # 기간 다시 계산

비교 기준
- 종가(close, 분할만 보정·배당 미반영): 모든 출처가 같은 기준이라 주 비교 값. 허용 0.5%
- 수정종가(adj_close, 분할+배당 보정): 허용 1%. KIS 는 수정주가가 배당을 반영하지 않아 빠짐
- 기준값 = 출처들 값의 중앙값. 출처가 2개면 중앙값이 둘의 평균이라 편차가 반으로 보이므로,
  통화별 우선순위(repo.price_priority)에서 앞선 출처 값을 기준으로 삼음

결과
- 출처가 1개: 그 행 verify_status = SINGLE. CONSENSUS 행은 만들지 않음 (있으면 지움)
- 출처가 2개 이상: CONSENSUS 행 저장 (adj_close·close = 기준값, source_count, 최대 편차,
  verify_status = VERIFIED 또는 MISMATCH, outlier_sources = 허용을 넘은 출처).
  출처별 행에는 편차(dev_pct·adj_dev_pct, %)와 VERIFIED / MISMATCH
- 수집으로 값이 바뀐 행은 저장소가 표시를 비우므로 다음 실행에서 다시 검증됨
- get_prices 는 CONSENSUS 행을 먼저 고름 (DB_설계 6절)
"""

from __future__ import annotations

import statistics
from collections.abc import Iterable, Sequence
from dataclasses import dataclass, field
from datetime import date
from typing import Any, Protocol

from myfinsight.data.repository.base import ExtendedRepository

CLOSE_TOL_PCT = 0.5
ADJ_TOL_PCT = 1.0
ADJ_EXCLUDED = frozenset({"KIS"})
"""수정종가 비교에서 빼는 출처 (수정주가가 배당 미반영)."""

VERIFIED, MISMATCH, SINGLE = "VERIFIED", "MISMATCH", "SINGLE"


class _Deadline(Protocol):
    def over(self) -> bool: ...


@dataclass
class VerifyResult:
    """검증 결과 요약. counts 키: keys, consensus_rows, verified, mismatch, single."""

    done: bool = True
    counts: dict[str, int] = field(
        default_factory=lambda: dict.fromkeys(
            ("keys", "consensus_rows", "verified", "mismatch", "single"), 0
        )
    )
    mismatches: list[str] = field(default_factory=list)  # "티커 날짜: 출처들" (앞 20개)

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": "verify",
            "done": self.done,
            "counts": self.counts,
            "mismatches": self.mismatches,
        }


def _dev(value: float | None, ref: float | None) -> float | None:
    if value is None or not ref:
        return None
    return round((value - ref) / ref * 100, 6)


def _reference(
    values: dict[str, float], tol: float, priority: Sequence[str]
) -> tuple[float | None, dict[str, float]]:
    """기준값과 출처별 편차(%). 비교할 값이 2개 미만이면 편차 없음."""
    if not values:
        return None, {}
    ref = statistics.median(values.values())
    if len(values) < 2:
        return ref, {}
    if len(values) == 2:  # 둘이면 중앙값=평균이라 편차가 반으로 보임 → 앞선 출처를 기준으로
        order = {s: i for i, s in enumerate(priority)}
        top = min(values, key=lambda s: (order.get(s, len(order)), s))
        ref = values[top]
    return ref, {s: _dev(v, ref) or 0.0 for s, v in values.items()}


def judge(
    rows: Sequence[dict[str, Any]],
    *,
    priority: Sequence[str] = (),
    close_tol: float = CLOSE_TOL_PCT,
    adj_tol: float = ADJ_TOL_PCT,
) -> tuple[dict[str, Any] | None, list[dict[str, Any]]]:
    """한 (종목, 날짜) 의 출처별 행 → (CONSENSUS 행 또는 None, 출처별 표시). 순수 함수."""
    first = rows[0]
    key = {"ticker": first["ticker"], "date": first["date"]}
    if len(rows) == 1:
        mark = {"source": first["source"], "dev_pct": None, "adj_dev_pct": None}
        return None, [{**key, **mark, "verify_status": SINGLE}]

    closes = {r["source"]: r["close"] for r in rows if r.get("close")}
    adjs = {r["source"]: r["adj_close"] for r in rows if r["source"] not in ADJ_EXCLUDED}
    close_ref, close_dev = _reference(closes, close_tol, priority)
    if adjs:
        adj_ref, adj_dev = _reference(adjs, adj_tol, priority)
    else:  # 비교할 수정종가가 없으면 편차 없이 기준값만 (KIS 끼리 등)
        adj_ref, _ = _reference({r["source"]: r["adj_close"] for r in rows}, adj_tol, priority)
        adj_dev = {}

    outliers = sorted(
        {s for s, d in close_dev.items() if abs(d) > close_tol}
        | {s for s, d in adj_dev.items() if abs(d) > adj_tol}
    )
    marks = [
        {
            **key,
            "source": r["source"],
            "dev_pct": close_dev.get(r["source"]),
            "adj_dev_pct": adj_dev.get(r["source"]),
            "verify_status": MISMATCH if r["source"] in outliers else VERIFIED,
        }
        for r in rows
    ]
    volumes = [r["volume"] for r in rows if r.get("volume") is not None]
    consensus = {
        **key,
        "adj_close": adj_ref,
        "close": close_ref,
        "volume": int(statistics.median(volumes)) if volumes else None,
        "currency": first["currency"],
        "asset_id": first["asset_id"],
        "fetched_at": max(r["fetched_at"] for r in rows),
        "source_count": len(rows),
        "dev_pct": max((abs(d) for d in close_dev.values()), default=None),
        "adj_dev_pct": max((abs(d) for d in adj_dev.values()), default=None),
        "verify_status": MISMATCH if outliers else VERIFIED,
        "outlier_sources": outliers,
    }
    return consensus, marks


def _group(rows: Iterable[dict[str, Any]]) -> dict[tuple[str, date], list[dict[str, Any]]]:
    out: dict[tuple[str, date], list[dict[str, Any]]] = {}
    for r in rows:
        out.setdefault((r["ticker"], r["date"]), []).append(r)
    return out


def verify_step(
    repo: ExtendedRepository,
    *,
    deadline: _Deadline | None = None,
    batch: int = 2000,
    close_tol: float = CLOSE_TOL_PCT,
    adj_tol: float = ADJ_TOL_PCT,
    result: VerifyResult | None = None,
) -> VerifyResult:
    """검증 안 된 (종목, 날짜) 를 batch 개씩 처리. 시간 예산이 다 되면 멈추고 done=False."""
    res = result or VerifyResult()
    res.done = False
    while deadline is None or not deadline.over():
        keys = repo.pending_verification(limit=batch)
        if not keys:
            res.done = True
            break
        consensus: list[dict[str, Any]] = []
        marks: list[dict[str, Any]] = []
        drop: list[tuple[str, date]] = []
        for (ticker, d), rows in sorted(_group(repo.price_rows(keys)).items()):
            rows = sorted(rows, key=lambda r: r["source"])
            prio = repo.price_priority.get(rows[0]["currency"], ())  # type: ignore[attr-defined]
            c, m = judge(rows, priority=prio, close_tol=close_tol, adj_tol=adj_tol)
            marks.extend(m)
            if c is None:
                drop.append((ticker, d))
                res.counts["single"] += 1
                continue
            consensus.append(c)
            if c["verify_status"] == MISMATCH:
                res.counts["mismatch"] += 1
                if len(res.mismatches) < 20:
                    res.mismatches.append(f"{ticker} {d}: {','.join(c['outlier_sources'])}")
            else:
                res.counts["verified"] += 1
        res.counts["keys"] += len(keys)
        res.counts["consensus_rows"] += repo.save_verification(
            consensus, marks, drop_consensus=drop
        )
    return res


def reverify(
    repo: ExtendedRepository,
    start: date,
    end: date,
    *,
    tickers: Sequence[str] | None = None,
    deadline: _Deadline | None = None,
    **kw: Any,
) -> VerifyResult:
    """기간(과 종목)의 검증 표시를 지우고 다시 계산 (허용 오차를 바꿨을 때 등)."""
    repo.reset_verification(start, end, tickers=tickers)
    return verify_step(repo, deadline=deadline, **kw)
