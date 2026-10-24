"""수집 공통: 설정(JobSettings·출처 줄), 시간 예산(Deadline), 이어받기 기록(fetch_log 한 줄),
대상 종목(universe), 출처 어댑터 만들기(키 확인).

진행 상황은 DB 가 기억한다 (저장 범위 = price_daily_source, 시도 기록 = fetch_log). 커서는 없다.
설정은 .env (crawlers/config.py): UNIVERSE_INDICES, EXTRA_TICKERS, BENCHMARK_TICKERS,
BACKFILL_YEARS, FIN_YEARS, FIN_REFRESH_DAYS, NEWS_PER_TICKER_DAY, NEWS_KEEP_DAYS,
NEWS_DAILY_LIMITS, VALUATION_YEARS.
"""

from __future__ import annotations

import time
from collections import defaultdict
from collections.abc import Callable, Iterable, Sequence
from dataclasses import dataclass, field
from datetime import date, datetime
from typing import Any

from backend.adapters.crawlers import config
from backend.adapters.crawlers.common import redact
from backend.db.base import ExtendedRepository
from backend.pipeline.normalizer import default_asset, normalize_ticker
from backend.schemas.market import IndexCode

Progress = Callable[[str], None]


MAX_FAILURES = 3
"""같은 대상이 이만큼 실패하면 (성공 기록 없이) 백필·재무 대상에서 뺀다. 상장폐지·ETF 등."""

NEWS_LANES: dict[str, dict[str, Any]] = {
    # 이름: (출처, 시장, 어댑터 인자)
    "NAVER_NEWS": {"source": "NAVER_NEWS", "market": "KR", "kwargs": {}},
    "GOOGLE_RSS_KR": {"source": "GOOGLE_RSS", "market": "KR", "kwargs": {}},
    "GOOGLE_RSS_US": {
        "source": "GOOGLE_RSS",
        "market": "US",
        "kwargs": {"lang": "en", "country": "US"},
    },
    "NEWSAPI": {"source": "NEWSAPI", "market": "US", "kwargs": {}},
    # Alpaca News (Benzinga): 검색어가 아니라 티커로 찾음. ALPACA 키가 있으면 씀, 한도 0 이면 끔
    "ALPACA_NEWS": {"source": "ALPACA_NEWS", "market": "US", "kwargs": {}, "query": "symbol"},
}
"""뉴스 수집 줄. 하루 한도는 NEWS_DAILY_LIMITS 로 줄마다 정한다 (0 이면 그 줄을 끔).
query: name(기본, 종목 이름으로 검색) 또는 symbol(티커)."""


PRICE_LANES: dict[str, dict[str, Any]] = {
    # 이름: 출처, 시장(KR·US·ALL), 역할. 순서 = 받는 순서 (primary 먼저)
    "KIS": {"market": "KR", "role": "primary"},
    "ALPACA": {"market": "US", "role": "primary"},
    "YFINANCE": {"market": "ALL", "role": "secondary"},  # 환율(KRW=X)도 이 줄에서
    "TIINGO": {"market": "US", "role": "sample"},  # 무료 한도 → 하루 N종목씩 돌아가며 최근분만
}
"""가격 수집 줄. primary = 공식 API, secondary = 전 종목 보완, sample = 표본 교차검증."""


# ---------------------------------------------------------------- 설정
def csv_list(text: str) -> list[str]:
    return [x.strip() for x in text.split(",") if x.strip()]


@dataclass
class JobSettings:
    """수집 작업 설정 (.env 에서 읽음, from_env)."""

    indices: list[IndexCode] = field(
        default_factory=lambda: [IndexCode.SP500, IndexCode.NDX, IndexCode.KOSPI200]
    )
    extra_tickers: dict[str, str | None] = field(default_factory=dict)  # 티커 → 이름
    benchmarks: list[str] = field(default_factory=lambda: ["SPY", "QQQ"])
    etf_tickers: list[str] = field(default_factory=list)  # 벤치마크 밖 ETF (EXTRA_TICKERS 등)
    backfill_years: int = 1
    fin_years: int = 12  # 10년치 일별 가치평가 + 직전 4분기(TTM)·1년 전 자본을 덮도록
    fin_refresh_days: int = 7
    fin_refresh_years: int = 1  # 전체를 한 번 받은 종목은 작년 1월 1일부터만 다시 받음
    news_per_ticker_day: int = 5  # 매일 수집에만 적용 (백필은 받은 기사를 모두 저장)
    news_keep_days: int = 4000  # 0 이하 = 지우지 않음 (영구 보관)
    news_daily_limits: dict[str, int] = field(
        default_factory=lambda: {
            "NAVER_NEWS": 200,
            "GOOGLE_RSS_KR": 200,
            "GOOGLE_RSS_US": 200,
            "NEWSAPI": 90,
            "ALPACA_NEWS": 200,
        }
    )
    valuation_years: int = 10
    increment_days: int = 10  # 매일 증분 때 다시 받는 최근 일수 (휴일·지연 반영 대비)
    price_lanes: list[str] = field(default_factory=lambda: list(PRICE_LANES))
    sample_daily: dict[str, int] = field(default_factory=lambda: {"TIINGO": 15})
    fx_symbol: str | None = "KRW=X"
    # SEC 에 최근 주식 수가 없는 종류주식 회사: yfinance 유통주식수로 보충 (YF_SHARES_TICKERS)
    yf_shares: list[str] = field(default_factory=lambda: ["BRK-B", "V", "STZ", "ERIE"])

    @classmethod
    def from_env(cls) -> JobSettings:
        s = cls()
        if v := config.get("UNIVERSE_INDICES"):
            s.indices = [IndexCode(x.upper()) for x in csv_list(v)]
        if v := config.get("EXTRA_TICKERS"):  # 005930.KS:삼성전자,000660.KS:SK하이닉스,TSLA
            s.extra_tickers = {}
            for item in csv_list(v):
                t, _, name = item.partition(":")
                s.extra_tickers[normalize_ticker(t)] = name.strip() or None
        if v := config.get("BENCHMARK_TICKERS"):
            s.benchmarks = [normalize_ticker(x) for x in csv_list(v)]
        if v := config.get("ETF_TICKERS"):
            s.etf_tickers = [normalize_ticker(x) for x in csv_list(v)]
        for name in (
            "backfill_years",
            "fin_years",
            "fin_refresh_days",
            "news_per_ticker_day",
            "news_keep_days",
            "valuation_years",
        ):
            if v := config.get(name.upper()):
                setattr(s, name, int(v))
        if v := config.get("PRICE_SOURCES"):  # KIS,ALPACA,YFINANCE,TIINGO
            s.price_lanes = [x.upper() for x in csv_list(v)]
        if v := config.get("TIINGO_DAILY_SYMBOLS"):
            s.sample_daily["TIINGO"] = int(v)
        if v := config.get("YF_SHARES_TICKERS"):  # BRK-B,V,STZ,ERIE ("-" 면 끔)
            s.yf_shares = [normalize_ticker(x) for x in csv_list(v) if x.strip() != "-"]
        if v := config.get("NEWS_DAILY_LIMITS"):  # NAVER_NEWS=200,NEWSAPI=90,...
            for item in csv_list(v):
                k, _, n = item.partition("=")
                s.news_daily_limits[k.strip().upper()] = int(n)
        return s

    @property
    def etfs(self) -> set[str]:
        """assets.asset_type = ETF 로 둘 종목: 벤치마크 + ETF_TICKERS. 재무·뉴스 대상에서 빠짐."""
        return set(self.benchmarks) | set(self.etf_tickers)


@dataclass
class JobResult:
    """작업 한 번의 결과. done=False 면 남은 일이 있어 다음 실행이 이어 받음."""

    name: str
    done: bool = True
    counts: dict[str, int] = field(default_factory=lambda: defaultdict(int))
    failed: dict[str, str] = field(default_factory=dict)
    notes: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "done": self.done,
            "counts": dict(self.counts),
            "failed": dict(list(self.failed.items())[:50]),
            "failed_total": len(self.failed),
            "notes": self.notes,
        }


class Deadline:
    """시간 예산. 함수 실행 제한(예: 9분) 전에 스스로 멈추기 위함."""

    def __init__(self, budget_sec: float, clock: Callable[[], float] = time.monotonic) -> None:
        self._clock = clock
        self._end = clock() + budget_sec

    def over(self) -> bool:
        return self._clock() >= self._end


class Forever:
    """시간 제한 없음 (Deadline 과 같은 모양)."""

    def over(self) -> bool:
        return False


def chunks(items: Sequence[Any], n: int) -> Iterable[list[Any]]:
    for i in range(0, len(items), n):
        yield list(items[i : i + n])


def years_before(d: date, years: int) -> date:
    try:
        return d.replace(year=d.year - years)
    except ValueError:  # 2월 29일
        return d.replace(year=d.year - years, day=28)


# ---------------------------------------------------------------- 대상 종목
def universe(repo: ExtendedRepository, settings: JobSettings) -> dict[str, str | None]:
    """수집 대상 티커 → 이름 (순서 유지).

    최신 구성종목 + EXTRA_TICKERS + 서비스 요청으로 늘어난 종목(extra_ticker)
    + 벤치마크 + ETF_TICKERS.
    """
    out: dict[str, str | None] = {}
    for index in settings.indices:
        for r in repo.latest_constituents(index):
            out.setdefault(normalize_ticker(r.ticker), r.name)
    for t, name in settings.extra_tickers.items():
        out.setdefault(t, name)
    asset_names = None
    for t in repo.extra_tickers():
        if t not in out:
            asset_names = asset_names or {a.yfinance_symbol: a.name for a in repo.get_assets()}
            out[t] = asset_names.get(t)
    for t in (*settings.benchmarks, *settings.etf_tickers):
        out.setdefault(t, None)
    return out


def ensure_assets(repo: ExtendedRepository, names: dict[str, str | None]) -> None:
    """assets 에 없는 종목만 기본 행으로 추가 (있는 행은 건드리지 않음)."""
    have = {a.yfinance_symbol for a in repo.get_assets(list(names))}
    missing = [default_asset(t, names[t]) for t in names if t not in have]
    if missing:
        repo.upsert_assets(missing)


def sync_asset_types(repo: ExtendedRepository, settings: JobSettings) -> int:
    """설정의 ETF 종목을 assets.asset_type = ETF 로 맞춤 (이미 STOCK 으로 저장된 행도 고침)."""
    etfs = sorted(settings.etfs)
    if not etfs:
        return 0
    ensure_assets(repo, dict.fromkeys(etfs))
    wrong = [a for a in repo.get_assets(etfs) if a.asset_type != "ETF"]
    if not wrong:
        return 0
    return repo.upsert_assets([a.model_copy(update={"asset_type": "ETF"}) for a in wrong])


# ---------------------------------------------------------------- 이어받기 기록
def log_row(
    target: str, start: date, end: date, at: datetime, error: str | None, count: int
) -> dict[str, Any]:
    """fetch_log 한 줄 (repo.log_fetches 입력)."""
    return {
        "target": target,
        "start_date": start,
        "end_date": end,
        "status": "FAILED" if error else "SUCCESS",
        "fetched_at": at,
        "error": redact(error),  # 요청 주소에 든 키 등을 가림
        "fetched_count": count,
    }


# ---------------------------------------------------------------- 출처 어댑터
def open_repo(repo: ExtendedRepository | None) -> ExtendedRepository:
    if repo is not None:
        return repo
    from backend.db import open_repository

    return open_repository()


def try_make(make: Callable[[], Any], what: str, notes: list[str]) -> Any:
    """키가 없는 출처는 건너뛴다 (MissingApiKeyError 등)."""
    try:
        return make()
    except Exception as exc:  # noqa: BLE001
        notes.append(f"{what} 건너뜀: {exc}")
        return None


NEEDS: dict[str, tuple[str, ...]] = {
    "KIS": ("KIS_APP_KEY", "KIS_APP_SECRET"),
    "ALPACA": ("ALPACA_API_KEY_ID", "ALPACA_API_SECRET_KEY"),
    "TIINGO": ("TIINGO_API_KEY",),
    "DART": ("DART_API_KEY",),
    "SEC_EDGAR": ("SEC_USER_AGENT",),
    "NAVER_NEWS": ("NAVER_CLIENT_ID", "NAVER_CLIENT_SECRET"),
    "NEWSAPI": ("NEWSAPI_KEY",),
    "ALPACA_NEWS": ("ALPACA_API_KEY_ID", "ALPACA_API_SECRET_KEY"),
}


def require_keys(source: str) -> None:
    """출처에 필요한 .env 키가 비었으면 MissingApiKeyError (어댑터 없이 함수로 받는 출처용)."""
    config.require(**{k: config.get(k) for k in NEEDS.get(source, ())})


def checked(adapter: Any) -> Any:
    """필요한 .env 키가 비었으면 미리 알림 (요청마다 실패 기록이 쌓이지 않게)."""
    need = NEEDS.get(adapter.source_name, ())
    config.require(**{k: config.get(k) for k in need})
    return adapter
