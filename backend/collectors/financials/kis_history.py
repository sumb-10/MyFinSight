"""한국 2015년 전 재무 보충 (KIS 연간 재무, 2004년부터). OpenDART 재무 API 는 2015 사업연도부터만 준다.

KIS 국내주식 재무(손익계산서·대차대조표·재무비율, 연간)에서 until_year 까지의 사업연도만 받아
financials_source 에 출처 KIS_FIN 으로 넣는다 (2015년부터는 DART 그대로).
- 지표: 매출액·영업이익·당기순이익·자산총계·부채총계·자본총계 (억원 → 원),
  EPS(연간·현재기준)·BPS(현재기준) (원, KIS 가 지금까지의 액면분할을 반영해 준 값: 지금 종가와 바로 나눔)
- 공시일(disclosed_at, 선견 금지): KIS 값에는 공시일이 없어 공시 테이블(DART)에서 그 사업연도
  사업보고서의 최초 접수일을 쓴다. 2010 사업연도까지는 법정 주재무제표가 개별이고 연결재무제표는 뒤에
  따로 냈으므로(KIS 값은 연결) "최초 접수일과 기말 + LATE_CONSOLIDATED_DAYS 중 늦은 날".
  사업보고서를 못 찾으면 기말 + NO_REPORT_DAYS.
- 한계: KIS 값이 처음 공시된 숫자인지 뒤에 정정된 숫자인지는 알 수 없다 (공시 시점은 보수적으로 잡음).
- 이어 받기: fetch_log target kis_fin:<6자리> (성공하면 다시 안 받음).
"""

from __future__ import annotations

import calendar
from collections.abc import Callable
from datetime import UTC, date, datetime, timedelta
from typing import Any

from backend.collectors.common import JobResult, JobSettings, Progress, log_row
from backend.collectors.disclosures.update import targets
from backend.db.base import ExtendedRepository
from backend.pipeline.normalizer import default_asset
from backend.schemas.market_ext import FinancialRow

SOURCE = "KIS_FIN"
PREFIX = "kis_fin:"
UNTIL_YEAR = 2014
"""이 사업연도까지만 넣는다 (2015년부터는 DART)."""
CONSOLIDATED_FROM_YEAR = 2011
"""K-IFRS 연결재무제표가 사업보고서의 주재무제표가 된 첫 사업연도."""
LATE_CONSOLIDATED_DAYS = 150
NO_REPORT_DAYS = 180
EPS_CUR, BPS_CUR = "EPS(연간·현재기준)", "BPS(현재기준)"
EOK = 100_000_000
AMOUNTS = {
    "sale_account": "매출액",
    "bsop_prti": "영업이익",
    "thtr_ntin": "당기순이익",
    "total_aset": "자산총계",
    "total_lblt": "부채총계",
    "total_cptl": "자본총계",
}
"""KIS 칸 → 지표 (억원)."""
PER_SHARE = {"eps": EPS_CUR, "bps": BPS_CUR}
"""KIS 칸 → 지표 (원, 현재 주식 기준)."""
FinFetch = Callable[[str], dict[str, dict[str, str]]]


def _num(v: str | None) -> float | None:
    if v is None or str(v).strip() in ("", "99.99"):
        return None
    try:
        return float(str(v).replace(",", ""))
    except ValueError:
        return None


def period_end(yyyymm: str) -> date:
    y, m = int(yyyymm[:4]), int(yyyymm[4:6])
    return date(y, m, calendar.monthrange(y, m)[1])


def disclosed_on(pend: date, report_date: date | None) -> date:
    """KIS 연간 값을 쓸 수 있는 날 (모듈 설명의 규칙)."""
    if report_date is None:
        return pend + timedelta(days=NO_REPORT_DAYS)
    if pend.year < CONSOLIDATED_FROM_YEAR:
        return max(report_date, pend + timedelta(days=LATE_CONSOLIDATED_DAYS))
    return report_date


def kis_rows(
    symbol: str,
    data: dict[str, dict[str, str]],
    report_dates: dict[str, date],
    at: datetime,
    until_year: int = UNTIL_YEAR,
) -> list[FinancialRow]:
    """KIS 연간 재무 → financials_source 행. report_dates: 결산년월 YYYYMM → 사업보고서 최초 접수일."""
    out = []
    aid = default_asset(symbol).asset_id
    for ym, row in sorted(data.items()):
        if len(ym) != 6 or not ym.isdigit():
            continue
        pend = period_end(ym)
        if pend.year > until_year:
            continue
        disc = disclosed_on(pend, report_dates.get(ym))
        values = [(metric, _num(row.get(k)), EOK, "원") for k, metric in AMOUNTS.items()]
        values += [(metric, _num(row.get(k)), 1, "원") for k, metric in PER_SHARE.items()]
        for metric, v, mult, unit in values:
            if v is None:
                continue
            out.append(
                FinancialRow(
                    asset_id=aid,
                    source=SOURCE,
                    period=f"FY{ym}",
                    metric=metric,
                    value=v * mult,
                    unit=unit,
                    fiscal_year=pend.year,
                    report_code="KIS_FY",
                    period_end=pend,
                    disclosed_at=disc,
                    fetched_at=at,
                )
            )
    return out


def kis_fetch_real(code: str) -> dict[str, dict[str, str]]:
    from backend.adapters.crawlers import kis_client

    return kis_client.fetch_annual_financials(code)


def kis_financial_backfill(
    repo: ExtendedRepository,
    settings: JobSettings,
    *,
    fetch: FinFetch,
    deadline: Any,
    until_year: int = UNTIL_YEAR,
    progress: Progress | None = None,
) -> JobResult:
    res = JobResult("financials_backfill:KIS_FIN")
    keys = targets(repo, settings, "KR")  # 6자리 → 티커 (ETF 제외)
    done = repo.fetch_targets_done(SOURCE, PREFIX)
    reports = repo.annual_report_dates([default_asset(t).asset_id for t in keys.values()])
    for n, (code, symbol) in enumerate(keys.items(), start=1):
        target = f"{PREFIX}{code}"
        if target in done:
            continue
        if deadline.over():
            res.done = False
            break
        at = datetime.now(UTC)
        aid = default_asset(symbol).asset_id
        try:
            data = fetch(code)
            rows = kis_rows(symbol, data, reports.get(aid, {}), at, until_year)
            err = None
        except Exception as exc:  # noqa: BLE001 - 한 종목 실패는 기록하고 다음 종목
            rows, err = [], f"{type(exc).__name__}: {exc}"
            res.failed[target] = err
        stored = repo.upsert_financials(rows) if rows else 0
        repo.log_fetches(SOURCE, [log_row(target, date(2004, 1, 1), date(until_year, 12, 31),
                                          at, err, len(rows))])  # fmt: skip
        res.counts["requests"] += 1
        res.counts["rows"] += stored
        if progress and n % 20 == 0:
            progress(f"[financials KIS_FIN] {n}/{len(keys)}종목, 저장 {res.counts['rows']:,}행")
    return res
