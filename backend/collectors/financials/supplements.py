"""재무 보충: 주식 분할 이력(yfinance)과 SEC 에 최근 주식 수가 없는 종목의 yfinance 유통주식수.
가치평가(valuation_daily)가 분할 보정된 종가와 공시 주식 수를 맞출 때 쓴다."""

from __future__ import annotations

from collections.abc import Callable, Sequence
from datetime import UTC, date, datetime, timedelta
from typing import Any

from backend.collectors.common import (
    MAX_FAILURES,
    Deadline,
    JobResult,
    JobSettings,
    chunks,
    ensure_assets,
    log_row,
    universe,
)
from backend.db.base import ExtendedRepository
from backend.pipeline.normalizer import default_asset, is_kr_symbol
from backend.schemas.market_ext import FinancialRow

SPLIT_SOURCE = "YFINANCE"
YF_SHARES_SOURCE = "YFINANCE_SHARES"
"""yfinance 유통주식수 보충 출처 (분할 이력 YFINANCE 와 구분해 읽는 쪽에서 출처가 보이게)."""


def yf_share_rows(ticker: str, shares: list[dict[str, Any]], at: datetime) -> list[FinancialRow]:
    """yfinance 유통주식수 이력 → financials_source 행 (source YFINANCE_SHARES, report_code YF_SHARES).

    공시일은 기록일 그대로 (그날 이후 쓸 수 있는 값으로 봄). 계약 financials 에서는 SEC 값이
    우선이고, 날짜가 다른 키라 SEC 에 없는 최근 날짜를 이 값이 채운다."""
    out = []
    for r in shares:
        d = date.fromisoformat(str(r["date"])[:10])
        out.append(
            FinancialRow(
                asset_id=default_asset(ticker).asset_id,
                source=YF_SHARES_SOURCE,
                period=f"S{d.isoformat()}",
                metric="유통주식수",
                value=float(r["shares"]),
                unit="주",
                fiscal_year=d.year,
                report_code="YF_SHARES",
                period_end=d,
                disclosed_at=d,
                fetched_at=at,
            )
        )
    return out


def split_step(
    repo: ExtendedRepository,
    settings: JobSettings,
    *,
    fetch_splits: Callable[[str], list[dict[str, Any]]],
    today: date,
    limit: int = 200,
    deadline: Deadline | None = None,
    progress: Callable[[str], None] | None = None,
    markets: Sequence[str] | None = None,
    fetch_shares: Callable[[str], list[dict[str, Any]]] | None = None,
) -> JobResult:
    """주식 분할 이력 (yfinance) → financials_source (metric 주식분할, source YFINANCE).

    가치평가(valuation_daily)가 분할 보정된 종가와 공시 주식 수를 맞출 때 쓴다. 종목마다
    FIN_REFRESH_DAYS 에 한 번 (fetch_log target splits:<티커>). 분할이 없으면 0건 성공.
    fetch_shares 를 주면 settings.yf_shares 종목은 유통주식수 이력도 같이 받는다 (yf_share_rows).
    """
    res = JobResult("splits")
    deadline = deadline or Deadline(480)
    names = universe(repo, settings)
    tickers = [
        t
        for t in names
        if t not in settings.etfs
        and (markets is None or ("KR" if is_kr_symbol(t) else "US") in markets)
    ]
    targets = {f"splits:{t}": t for t in tickers}
    att = repo.fetch_attempts(SPLIT_SOURCE, list(targets))
    day0 = datetime(today.year, today.month, today.day, tzinfo=UTC)
    fresh_after = day0 - timedelta(days=settings.fin_refresh_days)

    def due(k: str) -> bool:
        a = att.get(k)
        if a is None:
            return True
        if a["last_success_at"] is None:
            return a["failures"] < MAX_FAILURES
        return a["last_success_at"] < fresh_after

    keys = [k for k in targets if due(k)]
    res.counts["pending"] = len(keys)
    if len(keys) > limit:
        res.done = False
    for n, part in enumerate(chunks(keys[:limit], 20), start=1):
        if deadline.over():
            res.done = False
            break
        ensure_assets(repo, {targets[k]: names[targets[k]] for k in part})
        rows: list[FinancialRow] = []
        logs = []
        at = datetime.now(UTC)
        for k in part:
            t = targets[k]
            try:
                splits = fetch_splits(t)
                err = None
            except Exception as exc:  # noqa: BLE001 - 한 종목 실패는 기록하고 다음 종목
                splits, err = [], f"{type(exc).__name__}: {exc}"
                res.failed[k] = err
            if fetch_shares is not None and t in settings.yf_shares and err is None:
                try:
                    rows += yf_share_rows(t, fetch_shares(t), at)
                except Exception as exc:  # noqa: BLE001 - 주식 수 보충 실패는 분할 저장을 막지 않음
                    res.notes.append(f"{t} 유통주식수(yfinance) 실패: {type(exc).__name__}: {exc}")
            for sp in splits:
                d = date.fromisoformat(str(sp["date"])[:10])
                rows.append(
                    FinancialRow(
                        asset_id=default_asset(t).asset_id,
                        source=SPLIT_SOURCE,
                        period=f"SPLIT{d.isoformat()}",
                        metric="주식분할",
                        value=float(sp["ratio"]),
                        unit="배",
                        fiscal_year=d.year,
                        report_code="SPLIT",
                        period_end=d,
                        disclosed_at=d,
                        fetched_at=at,
                    )
                )
            logs.append(log_row(k, today, today, at, err, len(splits)))
        res.counts["rows"] += repo.upsert_financials(rows) if rows else 0
        repo.log_fetches(SPLIT_SOURCE, logs)
        res.counts["tickers"] += len(part)
        if progress and n % 5 == 0:
            progress(f"[splits] {res.counts['tickers']}/{min(len(keys), limit)}종목")
    return res
