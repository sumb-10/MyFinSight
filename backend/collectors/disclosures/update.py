"""공시 매일 갱신: 종목마다 최근 days(14)일 공시만 다시 받아 새 공시를 더한다 (SEC EDGAR·DART).

공시 → DisclosureRow 변환과 available_on(쓸 수 있는 첫 거래일) 규칙도 여기 둔다 (backfill.py 도 씀).
- SEC: 접수 시각(acceptanceDateTime, 미국 동부)이 평일 09:30 전이면 그날, 아니면 다음 평일.
- DART: 목록에 접수 날짜만 있어 장중 공시인지 모르므로 보수적으로 다음 평일.
휴장일은 따로 보지 않는다 (휴장일이면 실제로는 그 뒤 첫 거래일부터 쓰게 됨).
"""

from __future__ import annotations

from collections.abc import Callable
from datetime import UTC, date, datetime, time, timedelta
from typing import Any
from zoneinfo import ZoneInfo

from backend.collectors.common import (
    Deadline,
    JobResult,
    JobSettings,
    Progress,
    ensure_assets,
    log_row,
    universe,
)
from backend.collectors.disclosures import categories as cat
from backend.db.base import ExtendedRepository
from backend.pipeline.normalizer import default_asset, is_kr_symbol
from backend.schemas.market_ext import DisclosureRow

NY = ZoneInfo("America/New_York")
SEOUL = ZoneInfo("Asia/Seoul")
US_OPEN = time(9, 30)
SecFetch = Callable[[str, date | None], tuple[int, list[dict[str, Any]]]]
"""(티커, 이 날 이후만 | None) → (CIK, 공시 목록)."""
DartFetch = Callable[[str, date, date], list[dict[str, Any]]]
"""(6자리 종목코드, 시작일, 끝일) → 공시 목록."""


def next_weekday(d: date) -> date:
    d += timedelta(days=1)
    while d.weekday() >= 5:
        d += timedelta(days=1)
    return d


def sec_times(filing: dict[str, Any]) -> tuple[datetime, date]:
    """(접수 시각 UTC, available_on). 접수 시각이 없으면 접수일 17:30 동부로 보고 다음 평일."""
    filed = date.fromisoformat(filing["filingDate"])
    raw = (filing.get("acceptanceDateTime") or "").rstrip("Z").split(".")[0]
    if not raw:
        at = datetime.combine(filed, time(17, 30), tzinfo=NY)
        return at.astimezone(UTC), next_weekday(filed)
    local = datetime.fromisoformat(raw).replace(tzinfo=NY)  # Z 가 붙어 있어도 동부 시각
    day = local.date()
    usable = day if day.weekday() < 5 and local.time() < US_OPEN else next_weekday(day)
    return local.astimezone(UTC), usable


def sec_rows(
    symbol: str, cik: int, filings: list[dict[str, Any]], at: datetime
) -> list[DisclosureRow]:
    """SEC submissions 공시 → 행 (SEC_FORMS·8-K 만)."""
    out = []
    for f in filings:
        if not f.get("accessionNumber") or not f.get("filingDate") or not cat.sec_keep(f["form"]):
            continue
        filed_at, usable = sec_times(f)
        _, amended = cat.sec_base_form(f["form"])
        event, rule = cat.sec_event(f["form"], f.get("items"), filed_at.astimezone(NY).date())
        acc = f["accessionNumber"]
        doc = f.get("primaryDocument")
        url = f"https://www.sec.gov/Archives/edgar/data/{cik}/{acc.replace('-', '')}/" + (
            doc or f"{acc}-index.htm"
        )
        out.append(
            DisclosureRow(
                asset_id=default_asset(symbol).asset_id,
                source="SEC_EDGAR",
                filing_id=acc,
                form=f["form"],
                items=(f.get("items") or None),
                title=(f.get("primaryDocDescription") or None),
                filed_at=filed_at,
                available_on=usable,
                is_amendment=amended,
                url=url,
                event_type=event,
                rule_version=rule,
                fetched_at=at,
            )
        )
    return out


def dart_rows(symbol: str, items: list[dict[str, Any]], at: datetime) -> list[DisclosureRow]:
    """DART 공시검색 목록 → 행 (임원·주요주주 소유상황보고서는 뺌)."""
    out = []
    for it in items:
        name = it.get("report_nm") or ""
        if not it.get("rcept_no") or not cat.dart_keep(name):
            continue
        day = datetime.strptime(it["rcept_dt"], "%Y%m%d").date()
        form, amended = cat.dart_form(name)
        event, rule = cat.dart_event(name)
        out.append(
            DisclosureRow(
                asset_id=default_asset(symbol).asset_id,
                source="DART",
                filing_id=it["rcept_no"],
                form=form[:30],
                title=name.strip(),
                filed_at=datetime.combine(day, time(0), tzinfo=SEOUL).astimezone(UTC),
                available_on=next_weekday(day),
                is_amendment=amended,
                url=f"https://dart.fss.or.kr/dsaf001/main.do?rcpNo={it['rcept_no']}",
                event_type=event,
                rule_version=rule,
                fetched_at=at,
            )
        )
    return out


class DisclosureSink:
    """받은 공시를 모아 한 번에 저장하고 fetch_log 를 남김 (저장한 뒤에만 기록 → 끊겨도 안전)."""

    def __init__(self, repo: Any, source: str, flush_every: int = 20) -> None:
        self.repo, self.source, self.flush_every = repo, source, flush_every
        self.rows: list[DisclosureRow] = []
        self.logs: list[dict[str, Any]] = []
        self.stored = 0
        self.fetched = 0

    def add(
        self, rows: list[DisclosureRow], *, target: str, start: date, end: date, at: datetime,
        error: str | None = None, fetched: int = 0,
    ) -> None:  # fmt: skip
        self.rows += rows
        self.fetched += len(rows)
        self.logs.append(log_row(target, start, end, at, error, fetched))
        if len(self.logs) >= self.flush_every:
            self.flush()

    def flush(self) -> None:
        if self.rows:
            self.stored += self.repo.upsert_disclosures(self.rows)
        if self.logs:
            self.repo.log_fetches(self.source, self.logs)
        self.rows, self.logs = [], []


def targets(repo: ExtendedRepository, settings: JobSettings, market: str) -> dict[str, str]:
    """시장(KR·US)의 공시 대상: 요청 키(미국 티커, 한국 6자리 코드) → 티커. ETF 제외."""
    names = universe(repo, settings)
    skip = settings.etfs
    out = {}
    for t in names:
        if t in skip or is_kr_symbol(t) != (market == "KR"):
            continue
        out[default_asset(t).ticker if market == "KR" else t] = t
    ensure_assets(repo, {t: names[t] for t in out.values()})
    return out


def sec_fetch_real(ticker: str, since: date | None) -> tuple[int, list[dict[str, Any]]]:
    from backend.adapters.crawlers import edgar_client

    cik = edgar_client.resolve_cik(ticker)
    return cik, edgar_client.fetch_filings(cik, since)


def dart_fetch_real(code: str, start: date, end: date) -> list[dict[str, Any]]:
    from backend.adapters.crawlers import dart_client

    info = dart_client.find_by_stock_code(code)
    if not info:
        raise LookupError(f"DART 고유번호 목록에 {code} 없음")
    return dart_client.fetch_disclosure_list(info["corp_code"], start, end)


def _stop_error(exc: Exception) -> bool:
    """출처 전체를 이번 실행에서 멈출 오류 (DART 한도·키)."""
    from backend.schemas.errors import DataSourceError

    return isinstance(exc, DataSourceError)


def disclosure_update(
    repo: ExtendedRepository,
    settings: JobSettings,
    *,
    sec_fetch: SecFetch | None,
    dart_fetch: DartFetch | None,
    today: date,
    days: int = 14,
    deadline: Deadline | None = None,
    progress: Progress | None = None,
) -> JobResult:
    """종목마다 최근 days 일 공시 (오래 안 받은 종목부터). 하루에 한 번만 (오늘 성공한 종목은 건너뜀)."""
    res = JobResult("disclosures")
    deadline = deadline or Deadline(480)
    since = today - timedelta(days=days)
    day0 = datetime(today.year, today.month, today.day, tzinfo=UTC)
    for source, market, fetch in (("SEC_EDGAR", "US", sec_fetch), ("DART", "KR", dart_fetch)):
        if fetch is None:
            continue
        keys = targets(repo, settings, market)
        tmap = {f"disclosures_update:{k}": k for k in keys}
        att = repo.fetch_attempts(source, list(tmap))

        def last(t: str, att: dict = att) -> datetime:
            return (att.get(t) or {}).get("last_success_at") or datetime.min.replace(tzinfo=UTC)

        due = sorted((t for t in tmap if last(t) < day0), key=lambda t: (last(t), t))
        res.counts[f"{source}_pending"] = len(due)
        sink = DisclosureSink(repo, source)
        try:
            for target in due:
                if deadline.over():
                    res.done = False
                    break
                key = tmap[target]
                at = datetime.now(UTC)
                try:
                    if source == "SEC_EDGAR":
                        cik, got = fetch(key, since)
                        rows = sec_rows(keys[key], cik, got, at)
                    else:
                        got = fetch(key, since, today)
                        rows = dart_rows(keys[key], got, at)
                    err = None
                except Exception as exc:  # noqa: BLE001 - 한 종목 실패는 기록하고 다음 종목
                    if _stop_error(exc):
                        res.done = False
                        res.notes.append(f"{source} 멈춤: {exc}")
                        break
                    got, rows, err = [], [], f"{type(exc).__name__}: {exc}"
                    res.failed[f"{source}:{key}"] = err
                sink.add(rows, target=target, start=since, end=today, at=at, error=err,
                         fetched=len(got))  # fmt: skip
                res.counts[f"{source}_requests"] += 1
        finally:
            sink.flush()
            res.counts[f"{source}_rows"] = sink.stored
        if progress:
            progress(f"[disclosures {source}] 요청 {res.counts[f'{source}_requests']}, "
                     f"새로 저장 {sink.stored:,}")  # fmt: skip
    return res
