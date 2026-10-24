"""첫 수집 묶음 (PC 에서 backend/scripts/backfill.py 로):
GICS → 가격(빈 곳만) → 재무 12년 → 가치평가 → 공시 → 뉴스. 각 단계는 backend/collectors/*/backfill.py.

몇 시간~며칠 걸리는 일을 나눠서 해도 되게 만든다.
- 끊어도 됨: --max-minutes 가 끝나거나 Ctrl+C 로 멈춰도, 다시 같은 명령을 돌리면 끝난 부분은
  건너뛴다. 진행 상황은 DB 가 기억한다 (fetch_log 의 target, 저장 범위). 따로 커서 파일은 없다.
- 정기 수집(GitHub Actions)과 같이 돌아도 됨: 저장은 모두 값이 바뀐 행만 쓰는 upsert 이고,
  PostgreSQL 에서는 테이블별 트랜잭션 잠금(sql._lock)으로 같은 키를 동시에 넣지 않는다.
  백필 두 개가 동시에 도는 것만 막는다 (SqlRepository.job_lock("backfill")).
"""

from __future__ import annotations

from collections.abc import Callable, Iterable, Sequence
from dataclasses import dataclass, field
from datetime import date
from typing import Any

from backend.adapters.crawlers.common import redact
from backend.collectors.common import NEWS_LANES, Forever, JobResult, JobSettings, Progress
from backend.collectors.financials.backfill import financial_backfill
from backend.collectors.financials.supplements import split_step
from backend.collectors.news.backfill import (
    NEWS_BACKFILL_ORDER,
    RSS_LANES,
    alpaca_news_backfill,
    naver_backfill,
    newsapi_backfill,
    rss_backfill,
)
from backend.collectors.prices.backfill import price_backfill
from backend.jobs.daily import valuation_job

WHAT = ("gics", "prices", "financials", "kis_financials", "valuation", "disclosures", "news")


@dataclass
class BackfillOptions:
    what: Sequence[str] = WHAT
    years: int = 10
    fin_years: int = 12
    markets: Sequence[str] = ("KR", "US")
    news_lanes: Sequence[str] | None = None  # None = 쓸 수 있는 줄 전부
    valuation_full: bool = False
    rss_interval: float = 1.5
    newsapi_daily_max: int = 100
    flush_every: int = 20  # 이만큼 요청하면 한 번에 저장 (원격 DB 왕복 줄이기)
    disclosure_from: int = 2000  # 공시 첫 해 (DART 공시검색은 2000년부터)
    rss_kr_years: int | None = None  # 국내 Google RSS 만 더 과거로 (None = years)


def _lane_ok(lane: str, markets: Iterable[str]) -> bool:
    return NEWS_LANES[lane]["market"] in {m.upper() for m in markets}


@dataclass
class BackfillReport:
    results: list[JobResult] = field(default_factory=list)
    stopped: bool = False  # 시간 제한으로 멈춤 (다시 돌리면 이어서)


def run_backfill(
    repo: Any,
    settings: JobSettings,
    opts: BackfillOptions,
    *,
    adapters: dict[str, dict[str, Any]],
    today: date,
    deadline: Any = None,
    progress: Progress | None = None,
    fetch_splits: Callable[[str], list[dict[str, Any]]] | None = None,
) -> BackfillReport:
    """opts.what 순서대로: GICS → 가격(빈 곳만) → 재무(+분할) → 가치평가 → 공시 → 뉴스.

    adapters = {"price": {줄: 어댑터}, "financial": {출처: 어댑터}, "news": {줄: 어댑터},
    "gics": {"ksic": 함수, "profile": 함수},
    "disclosures": {"SEC_EDGAR": 함수, "DART": 함수}, "fx": {"FRED": 함수}}
    (키가 없는 출처는 빠져 있음). 시간 제한(deadline)이 끝나면 그 자리에서 멈춘다.
    """
    deadline = deadline or Forever()
    say = progress or (lambda _m: None)
    out = BackfillReport()
    what = [w for w in WHAT if w in opts.what]
    markets = [m.upper() for m in opts.markets]
    settings.backfill_years = max(settings.backfill_years, opts.years)
    settings.fin_years = opts.fin_years
    settings.valuation_years = opts.years

    def step(r: JobResult) -> None:
        out.results.append(r)
        say(f"== {r.name}: done={r.done} {dict(r.counts)}")
        for n in r.notes[:10]:
            say(f"   - {n}")
        if r.failed:
            say(redact(f"   - 실패 {len(r.failed)}건 (예: {list(r.failed.items())[:3]})"))

    if "gics" in what and not deadline.over():
        from backend.pipeline.classification import gics_step

        g = adapters.get("gics", {})
        say("== GICS 분류 (분류표·kr_gics.csv·KSIC·사업 설명)")
        step(gics_step(repo, settings, today=today, ksic_fetch=g.get("ksic"),
                       profile_fetch=g.get("profile"), deadline=deadline,
                       progress=progress))  # fmt: skip
    if "prices" in what and not deadline.over():
        lanes = {k: v for k, v in adapters.get("price", {}).items() if k != "TIINGO"}
        market = markets[0] if len(markets) == 1 else "ALL"
        say(f"== 가격: 빈 곳만 채움 ({opts.years}년, {','.join(lanes) or '출처 없음'})")
        if lanes:
            step(price_backfill(repo, settings, adapters=lanes, today=today,
                                deadline=deadline, market=market,
                                fred=adapters.get("fx", {}).get("FRED")))  # fmt: skip
    if "financials" in what and not deadline.over():
        fin = {
            s: a
            for s, a in adapters.get("financial", {}).items()
            if (s == "DART" and "KR" in markets) or (s == "SEC_EDGAR" and "US" in markets)
        }
        say(f"== 재무: {opts.fin_years}년 ({','.join(fin) or '출처 없음'})")
        step(financial_backfill(repo, settings, adapters=fin, today=today,
                                deadline=deadline, progress=progress))  # fmt: skip
        if fetch_splits is not None and not deadline.over():
            say("== 주식 분할 이력 (yfinance)")
            from backend.adapters.crawlers import yfinance_client

            real = fetch_splits is yfinance_client.split_rows  # 테스트 스텁이면 주식 수는 안 받음
            shares = yfinance_client.shares_rows if real else None
            step(split_step(repo, settings, fetch_splits=fetch_splits, today=today,
                            limit=10**6, deadline=deadline, progress=progress,
                            markets=markets, fetch_shares=shares))  # fmt: skip
    if "kis_financials" in what and not deadline.over():
        from backend.collectors.financials.kis_history import kis_financial_backfill

        fetch = adapters.get("kis_financials", {}).get("KIS")
        say("== 한국 2015년 전 재무 보충 (KIS 연간 재무, 2004~2014)")
        if fetch is not None and "KR" in markets:
            step(kis_financial_backfill(repo, settings, fetch=fetch, deadline=deadline,
                                        progress=progress))  # fmt: skip
    if "valuation" in what and not deadline.over():
        say("== 가치평가 valuation_daily " + ("전체 다시 계산" if opts.valuation_full else "증분"))
        step(valuation_job(repo, settings, today=today, full=opts.valuation_full,
                           markets=markets, deadline=deadline, progress=progress))  # fmt: skip
    if "disclosures" in what and not deadline.over():
        from backend.collectors.disclosures.backfill import dart_backfill, sec_backfill

        d = adapters.get("disclosures", {})
        kw = {"today": today, "start_year": opts.disclosure_from, "deadline": deadline,
              "flush_every": opts.flush_every, "progress": progress}  # fmt: skip
        say(f"== 공시: {opts.disclosure_from}년부터 ({','.join(d) or '출처 없음'})")
        if "SEC_EDGAR" in d and "US" in markets:
            step(sec_backfill(repo, settings, fetch=d["SEC_EDGAR"], **kw))
        if "DART" in d and "KR" in markets and not deadline.over():
            step(dart_backfill(repo, settings, fetch=d["DART"], **kw))
    if "news" in what and not deadline.over():
        news = adapters.get("news", {})
        chosen = [x.upper() for x in opts.news_lanes] if opts.news_lanes else list(NEWS_LANES)
        lanes = [
            lane
            for lane in NEWS_BACKFILL_ORDER
            if lane in chosen and lane in news and _lane_ok(lane, markets)
        ]
        say(f"== 뉴스 백필: {', '.join(lanes) or '쓸 수 있는 줄 없음'}")
        kw = {"today": today, "deadline": deadline, "progress": progress,
              "flush_every": opts.flush_every}  # fmt: skip
        if "NAVER_NEWS" in lanes:
            step(naver_backfill(repo, settings, adapter=news["NAVER_NEWS"], **kw))
        if "NEWSAPI" in lanes and not deadline.over():
            step(newsapi_backfill(repo, settings, adapter=news["NEWSAPI"],
                                  daily_max=opts.newsapi_daily_max, **kw))  # fmt: skip
        if "ALPACA_NEWS" in lanes and not deadline.over():
            step(alpaca_news_backfill(repo, settings, adapter=news["ALPACA_NEWS"],
                                      years=opts.years, **kw))  # fmt: skip
        rss = {lane: news[lane] for lane in lanes if lane in RSS_LANES}
        if rss and not deadline.over():
            step(rss_backfill(repo, settings, adapters=rss, years=opts.years,
                              kr_years=opts.rss_kr_years, interval=opts.rss_interval,
                              **kw))  # fmt: skip
    out.stopped = deadline.over()
    return out
