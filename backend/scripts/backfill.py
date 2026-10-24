"""긴 백필 한 번에: GICS 분류 → 가격(빈 곳만) → 재무 12년 → 주식 분할 → valuation_daily → 공시 → 뉴스.

python backend/scripts/backfill.py                              # 전부 (10년, KR·US, 뉴스 줄 전부)
python backend/scripts/backfill.py --what gics                  # GICS 분류만 (KSIC·사업 설명 포함, 10~15분)
python backend/scripts/backfill.py --what gics --no-profiles    # 사업 설명 없이 분류만 (1~2분)
python backend/scripts/backfill.py --what financials,valuation      # 일부만
python backend/scripts/backfill.py --what news --lanes NAVER_NEWS,GOOGLE_RSS_KR --markets KR
python backend/scripts/backfill.py --what news --lanes GOOGLE_RSS_KR,GOOGLE_RSS_US --rss-kr-years 21
                                    # 국내 RSS 만 2005년까지 (옛 사명·분기 묶음, 미국은 --years 그대로)
python backend/scripts/backfill.py --what disclosures --markets KR --max-minutes 300   # 공시 2000년~
python backend/scripts/backfill.py --what kis_financials --markets KR   # 한국 2004~2014 재무 (KIS)
python backend/scripts/backfill.py --max-minutes 120                # 2시간 하고 멈춤 (다시 돌리면 이어서)
python backend/scripts/backfill.py --what valuation --valuation-full    # 가치평가 전체 다시 계산

- .env 의 DATABASE_URL(Lightsail) 과 출처 키를 쓴다. 키가 없는 출처는 건너뛰고 알려 준다.
- 언제 멈춰도 된다 (Ctrl+C 또는 --max-minutes). 같은 명령을 다시 돌리면 끝난 부분은 건너뛴다.
- GitHub Actions 정기 수집과 같이 돌아도 된다. 백필 두 개를 동시에 돌리는 것만 막는다.
- 화면에는 진행 상황만 찍는다 (키·비밀번호는 찍지 않음, DB 주소는 비밀번호를 가림).
예상 시간·요청 수는 수집작업.md 「긴 백필」.
"""

from __future__ import annotations

import argparse
import logging
import sys
import time
from datetime import UTC, datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from backend.adapters.crawlers import config  # noqa: E402
from backend.collectors.common import (  # noqa: E402
    NEWS_LANES,
    PRICE_LANES,
    Deadline,
    Forever,
    JobSettings,
    checked,
    require_keys,
    try_make,
)
from backend.db import default_db_url, open_repository  # noqa: E402
from backend.jobs.backfill import WHAT, BackfillOptions, run_backfill  # noqa: E402


def _mask(url: str) -> str:
    if "@" not in url or "://" not in url:
        return url
    head, tail = url.split("://", 1)
    return f"{head}://***@{tail.split('@', 1)[1]}"


def _csv(v: str | None) -> list[str]:
    return [x.strip().upper() for x in (v or "").split(",") if x.strip()]


def make_adapters(
    settings: JobSettings, what: list[str], notes: list[str], *, no_profiles: bool = False
) -> dict:
    """키가 있는 출처의 어댑터 (없는 출처는 notes 에 이유를 적고 뺌)."""
    from backend.adapters.factory import financial_adapter, news_adapter, price_adapter

    out: dict[str, dict] = {"price": {}, "financial": {}, "news": {}, "gics": {}, "disclosures": {},
                            "kis_financials": {}, "fx": {}}  # fmt: skip
    if "gics" in what:
        from backend.pipeline.classification import default_fetchers

        ksic, profile = default_fetchers(notes, profiles=not no_profiles)
        out["gics"] = {k: v for k, v in (("ksic", ksic), ("profile", profile)) if v}
    if "prices" in what:
        from backend.adapters.crawlers import fred_client

        out["fx"]["FRED"] = fred_client.fetch_fx  # 키 필요 없음
        for lane in settings.price_lanes:
            if lane in PRICE_LANES and (
                a := try_make(lambda s=lane: checked(price_adapter(s)), lane, notes)
            ):
                out["price"][lane] = a
    if "financials" in what:
        for s in ("DART", "SEC_EDGAR"):
            if a := try_make(lambda s=s: checked(financial_adapter(s)), s, notes):
                out["financial"][s] = a
    if "kis_financials" in what:
        from backend.collectors.financials.kis_history import kis_fetch_real

        if try_make(lambda: require_keys("KIS") or True, "KIS 재무", notes):
            out["kis_financials"]["KIS"] = kis_fetch_real
    if "disclosures" in what:
        from backend.collectors.disclosures.update import dart_fetch_real, sec_fetch_real

        for s, fn in (("SEC_EDGAR", sec_fetch_real), ("DART", dart_fetch_real)):
            if try_make(lambda s=s: require_keys(s) or True, f"{s} 공시", notes):
                out["disclosures"][s] = fn
    if "news" in what:
        for lane, spec in NEWS_LANES.items():
            make = lambda s=spec: checked(news_adapter(s["source"], **s["kwargs"]))  # noqa: E731
            if a := try_make(make, lane, notes):
                out["news"][lane] = a
    return out


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument("--what", default=",".join(WHAT), help=",".join(WHAT))
    p.add_argument(
        "--no-profiles", action="store_true", help="gics: 사업 설명(yfinance)을 받지 않음"
    )
    p.add_argument("--years", type=int, default=10, help="가격·가치평가·뉴스 기간 (년)")
    p.add_argument("--fin-years", type=int, default=12, help="재무 기간 (년, TTM 계산에 1~2년 더)")
    p.add_argument("--markets", default="KR,US", help="KR,US")
    p.add_argument(
        "--lanes", help="뉴스 줄 (예: NAVER_NEWS,GOOGLE_RSS_KR,GOOGLE_RSS_US,ALPACA_NEWS)"
    )
    p.add_argument(
        "--max-minutes", type=float, default=0, help="이 시간이 지나면 멈춤 (0 = 끝까지)"
    )
    p.add_argument("--valuation-full", action="store_true", help="가치평가 전체 다시 계산")
    p.add_argument("--rss-interval", type=float, default=None, help="Google RSS 요청 간격(초)")
    p.add_argument("--disclosure-from", type=int, default=2000, help="공시 첫 해")
    p.add_argument(
        "--rss-kr-years", type=int, default=None,
        help="국내 Google RSS 만 이만큼 과거로 (예: 21 = 2005년부터, 없으면 --years)",
    )  # fmt: skip
    p.add_argument("--db", help="DB 주소 (없으면 .env 의 DATABASE_URL)")
    p.add_argument("-v", "--verbose", action="store_true", help="자세한 로그")
    a = p.parse_args(argv)
    logging.basicConfig(
        level=logging.INFO if a.verbose else logging.WARNING,
        format="%(levelname)s %(name)s: %(message)s",
    )
    what = [w.lower() for w in _csv(a.what)]
    bad = [w for w in what if w not in WHAT]
    if bad:
        p.error(f"--what 에 모르는 값: {bad} (가능: {','.join(WHAT)})")
    url = a.db or default_db_url()
    t0 = time.monotonic()

    def say(msg: str) -> None:
        m, s = divmod(int(time.monotonic() - t0), 60)
        print(f"[{m // 60:02d}:{m % 60:02d}:{s:02d}] {msg}", flush=True)

    say(f"DB: {_mask(url)}")
    settings = JobSettings.from_env()
    opts = BackfillOptions(
        what=what,
        years=a.years,
        fin_years=a.fin_years,
        markets=_csv(a.markets) or ["KR", "US"],
        news_lanes=_csv(a.lanes) or None,
        valuation_full=a.valuation_full,
        rss_interval=a.rss_interval
        if a.rss_interval is not None
        else float(config.get("NEWS_RSS_INTERVAL_SEC") or 1.5),
        newsapi_daily_max=int(config.get("NEWSAPI_DAILY_MAX") or 100),
        disclosure_from=a.disclosure_from,
        rss_kr_years=a.rss_kr_years,
    )
    notes: list[str] = []
    adapters = make_adapters(settings, what, notes, no_profiles=a.no_profiles)
    for n in notes:
        say(f"건너뜀: {n}")
    repo = open_repository(url)
    deadline = Deadline(a.max_minutes * 60) if a.max_minutes > 0 else Forever()
    with repo.job_lock("backfill") as ok:
        if not ok:
            say("다른 백필이 이미 돌고 있음 (같은 DB). 그쪽이 끝난 뒤 다시 실행")
            return 2
        from backend.adapters.crawlers import yfinance_client

        try:
            report = run_backfill(
                repo,
                settings,
                opts,
                adapters=adapters,
                today=datetime.now(UTC).date(),
                deadline=deadline,
                progress=say,
                fetch_splits=yfinance_client.split_rows if "financials" in what else None,
            )
        except KeyboardInterrupt:
            say("Ctrl+C 로 멈춤. 같은 명령을 다시 돌리면 이어서 함")
            return 130
    if report.stopped:
        say(f"시간 제한({a.max_minutes:g}분)으로 멈춤. 같은 명령을 다시 돌리면 이어서 함")
        return 0
    left = [r.name for r in report.results if not r.done]
    if left:
        say(f"끝났지만 남은 일이 있음: {', '.join(left)} (한도·차단 등, 나중에 다시 실행)")
    else:
        say("끝. 결과 확인: python backend/scripts/coverage_report.py")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
