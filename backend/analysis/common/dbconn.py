"""분석 패키지가 DB 에 붙는 한 가지 방법.

읽기(가격·환율·재무·뉴스·구성종목)는 팀 DB, 쓰기(run_step·run_artifact·report)는 기본적으로 로컬 SQLite 파일에 한다.
- 주소: DATABASE_URL → NEWS_DB_URL → NEWS_DB_HOST/USER/PASSWORD 조합 → 없으면 backend.db 기본값(로컬 SQLite).
- 결과 저장 위치: ANALYSIS_RESULTS_DB. 비우면 팀 DB 가 PostgreSQL 일 때 data/analysis_results.db, SQLite 일 때는 같은 파일.
  "main" 이라고 적으면 팀 DB 에 바로 쓴다(쓰기 계정 필요).
"""

from __future__ import annotations

from functools import lru_cache
from typing import Any
from urllib.parse import quote_plus

from backend.adapters.crawlers import config
from backend.db import open_repository

DEFAULT_RESULTS_DB = "sqlite:///data/analysis_results.db"

# 결과 저장소로 보내는 메서드. 나머지는 모두 시장 자료 저장소로.
RESULT_METHODS = frozenset({
    "save_step", "get_steps", "save_run_artifact", "get_run_artifact",
    "save_report", "get_report", "list_reports", "job_lock",
})


def database_url() -> str | None:
    url = config.get("DATABASE_URL") or config.get("NEWS_DB_URL")
    if url:
        return url
    host, user, pw = config.get("NEWS_DB_HOST"), config.get("NEWS_DB_USER"), config.get("NEWS_DB_PASSWORD")
    if host and user and pw:
        port = config.get("NEWS_DB_PORT") or "5432"
        name = config.get("NEWS_DB_NAME") or "myfinsight"
        ssl = config.get("NEWS_DB_SSL") or "require"
        return f"postgresql://{quote_plus(user)}:{quote_plus(pw)}@{host}:{port}/{name}?sslmode={ssl}"
    return None


def results_url(market_url: str | None) -> str | None:
    """결과 저장소 주소. None 이면 시장 저장소를 그대로 쓴다."""
    v = (config.get("ANALYSIS_RESULTS_DB") or "").strip()
    if v.lower() == "main":
        return None
    if v:
        return v
    if market_url and not market_url.startswith("sqlite"):
        return DEFAULT_RESULTS_DB
    return None


class SplitRepository:
    """시장 자료는 market 에서 읽고, 실행 기록·결과·리포트는 results 에 쓴다. 나머지 속성은 market 으로 넘긴다."""

    def __init__(self, market: Any, results: Any) -> None:
        self._market = market
        self._results = results

    @property
    def market(self) -> Any:
        return self._market

    @property
    def results(self) -> Any:
        return self._results

    def __getattr__(self, name: str) -> Any:
        target = self._results if name in RESULT_METHODS else self._market
        return getattr(target, name)

    def __repr__(self) -> str:
        return f"SplitRepository(market={self._market!r}, results={self._results!r})"


def open_analysis_repository(market_url: str | None = None) -> Any:
    murl = market_url or database_url()
    market = open_repository(murl)
    rurl = results_url(murl)
    if not rurl:
        return market
    return SplitRepository(market, open_repository(rurl))


@lru_cache(maxsize=1)
def default_repo() -> Any:
    """프로세스 안에서 한 번만 연다."""
    return open_analysis_repository()


def _host(url: str) -> str:
    if url.startswith("sqlite"):
        return url
    return "PostgreSQL " + url.split("@")[-1].split("/")[0]


def describe() -> str:
    """로그·화면용. 비밀번호는 보여 주지 않는다."""
    url = database_url()
    market = _host(url) if url else "로컬 SQLite (data/myfinsight.db)"
    rurl = results_url(url)
    return market if not rurl else f"읽기 {market} / 결과 {rurl}"
