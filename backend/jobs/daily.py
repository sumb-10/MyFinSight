"""매일 갱신 묶음: 정해진 주기마다 실제 데이터를 받아 DB 에 채운다 (역할 A, M02-01~05 를 묶음).
각 단계는 backend/collectors/ (가격·재무·뉴스·구성종목), 가공은 backend/pipeline/.

    python -m backend.jobs.daily prices      # 가격: 매일 증분 + 처음 N년치 백필 (나눠서)
    python -m backend.jobs.daily meta        # 구성종목 갱신 + GICS 분류 + 재무
    python -m backend.jobs.daily news        # 뉴스 (출처별 하루 한도 안) + 오래된 기사 삭제
    python -m backend.jobs.daily disclosures # 새 공시 (SEC EDGAR·DART, 종목마다 최근 14일)
    python -m backend.jobs.daily verify      # 교차검증만 (prices 도 끝에 이어서 함)
    python -m backend.jobs.daily verify --start 2026-01-01 --end 2026-09-30   # 기간 다시 계산
    python -m backend.jobs.daily valuation   # 일별 가치평가 증분 (--full 은 전체 다시 계산)
    python -m backend.jobs.daily all

긴 백필(10년치 가격·12년치 재무·가치평가·뉴스)은 PC 에서 backend/scripts/backfill.py
(jobs/backfill.py) 로.

- 어디서 돌든 같음: PC, GitHub Actions (.github/workflows/collect.yml).
  DB 는 .env 의 DATABASE_URL 로만 정해진다 (open_repository).
- 한 번 실행은 시간 예산(budget_sec, 기본 480초) 안에서 끝나고, 남은 일은 다음 실행이 이어 받는다.
  진행 상황은 DB 가 기억한다 (저장 범위 = price_daily_source, 시도 기록 = fetch_log). 커서는 없다.
- 설정은 .env (crawlers/config.py): UNIVERSE_INDICES, EXTRA_TICKERS, BENCHMARK_TICKERS,
  BACKFILL_YEARS, FIN_YEARS, FIN_REFRESH_DAYS, NEWS_PER_TICKER_DAY, NEWS_KEEP_DAYS,
  NEWS_DAILY_LIMITS, VALUATION_YEARS.
- 재무: 종목마다 처음 한 번은 FIN_YEARS(기본 12)년치 전체를 받고, 그 뒤로는 FIN_REFRESH_DAYS 마다
  최근 2년(작년 1월 1일부터)만 다시 받는다 (DART 요청 수 절약, fetch_log 의 start_date 로 판단).
"""

from __future__ import annotations

import argparse
import json
import logging
from collections.abc import Callable, Sequence
from datetime import UTC, date, datetime

from backend.collectors.common import (
    NEWS_LANES,
    PRICE_LANES,
    Deadline,
    JobResult,
    JobSettings,
    checked,
    csv_list,
    open_repo,
    try_make,
)
from backend.collectors.constituents.update import refresh_constituents
from backend.collectors.financials.supplements import split_step
from backend.collectors.financials.update import financial_step
from backend.collectors.news.update import news_step
from backend.collectors.prices.update import price_step
from backend.db.base import ExtendedRepository


def run_prices(
    repo: ExtendedRepository | None = None,
    *,
    budget_sec: float = 480,
    limit: int = 100,
    market: str = "ALL",
    lanes: Sequence[str] | None = None,
    sample: int | None = None,
) -> JobResult:
    from backend.adapters.crawlers import fred_client
    from backend.adapters.factory import price_adapter

    repo = open_repo(repo)
    settings = JobSettings.from_env()
    if sample is not None:  # 표본 줄(Tiingo) 이번 실행 종목 수 (주간 실행에서 한 번에)
        settings.sample_daily = {k: sample for k in settings.sample_daily}
    now = datetime.now(UTC)
    today = now.date()
    notes: list[str] = []
    if not any(repo.latest_constituents(i) for i in settings.indices):
        # 처음 실행: 구성종목이 아직 없으면 먼저 받음 (meta 작업보다 먼저 돌았을 때)
        from backend.collectors.constituents.source import default_constituent_source

        cons = refresh_constituents(
            repo, settings, source=default_constituent_source(), today=today
        )
        notes.append(f"구성종목 먼저 받음: {cons.to_dict()['counts']}")
    adapters = {
        lane: a
        for lane in settings.price_lanes
        if lane in PRICE_LANES
        and (a := try_make(lambda s=lane: checked(price_adapter(s)), lane, notes)) is not None
    }
    deadline = Deadline(budget_sec)
    res = price_step(
        repo,
        settings,
        adapters=adapters,
        today=today,
        limit=limit,
        deadline=deadline,
        market=market,
        lanes=lanes,
        fred=fred_client.fetch_fx,
        now=now,  # 시장마다 장이 끝난 날까지 (한국 16:37 KST 실행이면 그날 종가까지)
    )
    res.notes.extend(notes)
    # 남은 시간에 교차검증 (예약 함수를 늘리지 않음). 못 끝낸 몫은 다음 실행이 이어 받음
    ver = verify_job(repo, deadline=deadline)
    res.counts.update({f"verify_{k}": n for k, n in ver.counts.items()})
    if not ver.done:
        res.notes.append("교차검증 남음: 다음 실행에서 이어감")
    _valuation_tail(repo, settings, res, deadline, today=today)
    return res


def _valuation_tail(
    repo: ExtendedRepository,
    settings: JobSettings,
    res: JobResult,
    deadline: Deadline,
    *,
    today: date,
) -> None:
    """남은 시간에 valuation_daily 증분 (새 가격·재무가 들어온 종목만). 실패는 기록만."""
    if deadline.over() or not hasattr(repo, "valuation_assets"):
        return
    try:
        v = valuation_job(repo, settings, today=today, deadline=deadline)
    except Exception as exc:  # noqa: BLE001 - 가치평가는 덤: 오류는 기록만
        res.notes.append(f"valuation_daily 건너뜀: {type(exc).__name__}: {exc}")
        return
    res.counts["valuation_assets"] = v.counts["assets"]
    res.counts["valuation_written"] = v.counts["written"]
    res.notes.extend(v.notes)


def valuation_job(
    repo: ExtendedRepository,
    settings: JobSettings,
    *,
    today: date,
    full: bool = False,
    markets: Sequence[str] | None = None,
    deadline: Deadline | None = None,
    progress: Callable[[str], None] | None = None,
) -> JobResult:
    """valuation_daily 증분(기본) 또는 전체 다시 계산 (data/valuation.py)."""
    from backend.pipeline.valuation import valuation_step

    v = valuation_step(
        repo,
        today=today,
        years=settings.valuation_years,
        full=full,
        markets=markets,
        deadline=deadline,
        progress=progress,
    )
    res = JobResult("valuation", done=v.done, notes=v.notes)
    res.counts.update({"assets": v.assets, "rows": v.rows, "written": v.written})
    return res


def run_valuation(
    repo: ExtendedRepository | None = None, *, budget_sec: float = 480, full: bool = False
) -> JobResult:
    return valuation_job(
        open_repo(repo),
        JobSettings.from_env(),
        today=datetime.now(UTC).date(),
        full=full,
        deadline=Deadline(budget_sec),
    )


def verify_job(
    repo: ExtendedRepository,
    *,
    deadline: Deadline | None = None,
    start: date | None = None,
    end: date | None = None,
) -> JobResult:
    """출처 간 교차검증 (verify.py). start·end 를 주면 그 기간 표시를 지우고 다시 계산."""
    from backend.pipeline.verify import reverify, verify_step

    if start is not None or end is not None:
        v = reverify(repo, start or date(1900, 1, 1), end or date(2999, 12, 31), deadline=deadline)
    else:
        v = verify_step(repo, deadline=deadline)
    res = JobResult("verify", done=v.done, notes=[f"MISMATCH {m}" for m in v.mismatches])
    res.counts.update(v.counts)
    return res


def run_verify(
    repo: ExtendedRepository | None = None,
    *,
    budget_sec: float = 480,
    start: date | None = None,
    end: date | None = None,
) -> JobResult:
    return verify_job(open_repo(repo), deadline=Deadline(budget_sec), start=start, end=end)


def run_meta(
    repo: ExtendedRepository | None = None, *, budget_sec: float = 480, limit: int = 120
) -> list[JobResult]:
    from backend.adapters.factory import financial_adapter
    from backend.collectors.constituents.source import default_constituent_source

    repo = open_repo(repo)
    settings = JobSettings.from_env()
    today = datetime.now(UTC).date()
    deadline = Deadline(budget_sec)
    cons = refresh_constituents(repo, settings, source=default_constituent_source(), today=today)
    gics = run_gics(repo, settings, today=today, deadline=deadline)
    notes: list[str] = []
    adapters = {
        s: a
        for s in ("DART", "SEC_EDGAR")
        if (a := try_make(lambda s=s: checked(financial_adapter(s)), s, notes)) is not None
    }
    fin = financial_step(
        repo, settings, adapters=adapters, today=today, limit=limit, deadline=deadline
    )
    fin.notes.extend(notes)
    out = [cons, gics, fin]
    if not deadline.over():  # 주식 분할 이력 (가치평가용, 종목마다 FIN_REFRESH_DAYS 에 한 번)
        from backend.adapters.crawlers import yfinance_client

        out.append(
            split_step(
                repo,
                settings,
                fetch_splits=yfinance_client.split_rows,
                today=today,
                limit=limit,
                deadline=deadline,
                fetch_shares=yfinance_client.shares_rows,
            )
        )
    _valuation_tail(repo, settings, fin, deadline, today=today)
    return out


def run_gics(
    repo: ExtendedRepository,
    settings: JobSettings,
    *,
    today: date,
    deadline: Deadline,
    ksic_limit: int = 60,
    profile_limit: int = 30,
) -> JobResult:
    """구성종목 갱신 뒤 GICS 채우기 (classification.gics_step). 매번 KSIC·사업 설명은 조금씩만
    받고(한 번 받은 종목은 다시 안 받음), 분류 자체는 인터넷 없이 모든 종목에 다시 맞춘다."""
    from backend.pipeline.classification import default_fetchers, gics_step

    notes: list[str] = []
    ksic_fetch, profile_fetch = default_fetchers(notes)
    res = gics_step(
        repo,
        settings,
        today=today,
        ksic_fetch=ksic_fetch,
        profile_fetch=profile_fetch,
        ksic_limit=ksic_limit,
        profile_limit=profile_limit,
        deadline=deadline,
    )
    res.notes.extend(notes)
    return res


def run_disclosures(
    repo: ExtendedRepository | None = None, *, budget_sec: float = 480
) -> JobResult:
    """새 공시 (SEC EDGAR·DART, 종목마다 최근 14일). 키가 없는 출처는 건너뜀."""
    from backend.collectors.common import require_keys
    from backend.collectors.disclosures.update import (
        dart_fetch_real,
        disclosure_update,
        sec_fetch_real,
    )

    notes: list[str] = []
    sec = try_make(lambda: require_keys("SEC_EDGAR") or sec_fetch_real, "SEC_EDGAR 공시", notes)
    dart = try_make(lambda: require_keys("DART") or dart_fetch_real, "DART 공시", notes)
    res = disclosure_update(
        open_repo(repo),
        JobSettings.from_env(),
        sec_fetch=sec,
        dart_fetch=dart,
        today=datetime.now(UTC).date(),
        deadline=Deadline(budget_sec),
    )
    res.notes.extend(notes)
    return res


def run_news(repo: ExtendedRepository | None = None, *, budget_sec: float = 480) -> JobResult:
    from backend.adapters.factory import news_adapter

    repo = open_repo(repo)
    notes: list[str] = []
    adapters = {
        lane: a
        for lane, spec in NEWS_LANES.items()
        if (
            a := try_make(
                lambda s=spec: checked(news_adapter(s["source"], **s["kwargs"])), lane, notes
            )
        )
        is not None
    }
    res = news_step(
        repo,
        JobSettings.from_env(),
        adapters=adapters,
        today=datetime.now(UTC).date(),
        deadline=Deadline(budget_sec),
    )
    res.notes.extend(notes)
    return res


def main(argv: Sequence[str] | None = None) -> int:
    p = argparse.ArgumentParser(description="역할 A 서버 수집 작업")
    p.add_argument(
        "job", choices=["prices", "meta", "news", "disclosures", "verify", "valuation", "all"]
    )
    p.add_argument("--budget", type=float, default=480, help="시간 예산(초)")
    p.add_argument("--limit", type=int, default=None, help="한 번에 처리할 종목 수")
    p.add_argument("--start", type=date.fromisoformat, help="verify: 다시 계산할 시작일")
    p.add_argument("--end", type=date.fromisoformat, help="verify: 다시 계산할 종료일")
    p.add_argument(
        "--market", choices=["KR", "US", "ALL"], default="ALL", help="prices: 이 시장 종목만"
    )
    p.add_argument("--lanes", help="prices: 받을 출처 줄만 (예: ALPACA 또는 YFINANCE,TIINGO)")
    p.add_argument("--sample", type=int, help="prices: 표본 줄(Tiingo) 이번 실행 종목 수")
    p.add_argument("--full", action="store_true", help="valuation: 전체 다시 계산")
    a = p.parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
    results: list[JobResult] = []
    if a.job in ("prices", "all"):
        results.append(
            run_prices(
                budget_sec=a.budget,
                limit=a.limit or 100,
                market=a.market,
                lanes=csv_list(a.lanes) if a.lanes else None,
                sample=a.sample,
            )
        )
    if a.job in ("meta", "all"):
        results.extend(run_meta(budget_sec=a.budget, limit=a.limit or 100))
    if a.job in ("disclosures", "all"):
        results.append(run_disclosures(budget_sec=a.budget))
    if a.job in ("news", "all"):
        results.append(run_news(budget_sec=a.budget))
    if a.job == "verify":
        results.append(run_verify(budget_sec=a.budget, start=a.start, end=a.end))
    if a.job == "valuation":
        results.append(run_valuation(budget_sec=a.budget, full=a.full))
    print(json.dumps([r.to_dict() for r in results], ensure_ascii=False, indent=2, default=str))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
