"""분석 패키지가 DB 에 붙는 한 가지 방법.

읽기(가격·환율·재무·뉴스·구성종목)는 팀 DB, 쓰기(run_step·run_artifact·report)는 기본적으로 로컬 SQLite 파일에 한다.
- 주소: DATABASE_URL → NEWS_DB_URL → NEWS_DB_HOST/USER/PASSWORD 조합 → 없으면 backend.db 기본값(로컬 SQLite).
- 결과 저장 위치: ANALYSIS_RESULTS_DB. 비우면 팀 DB 가 PostgreSQL 일 때 data/analysis_results.db, SQLite 일 때는 같은 파일.
  "main" 이라고 적으면 팀 DB 에 바로 쓴다(쓰기 계정 필요).
- 여는 길이 둘이다. 사람이 화면 앞에서 기다리는 쪽(화면 서버 = default_repo, 연결 확인)은 먼저 한 번 두드려 보고(knock) 닿지 않으면
  바로 알린다. 사람이 기다리지 않는 쪽(일꾼·터미널 명령 = open_analysis_repository)은 저장소의 재시도 규칙대로 오래 기다린다.
"""

from __future__ import annotations

import time
from functools import lru_cache
from typing import Any
from urllib.parse import quote_plus

from sqlalchemy import create_engine

from backend.adapters.crawlers import config
from backend.db import normalize_db_url, open_repository
from backend.schemas.errors import RepositoryError

DEFAULT_RESULTS_DB = "sqlite:///data/analysis_results.db"
CONNECT_TIMEOUT_S = 8  # 접속 한 번에 기다리는 시간. 주소에 적지 않으면 드라이버 기본값(130초)을 기다린다
FAILURE_MEMO_S = 30  # 닿지 않은 것을 기억해 두는 시간 (화면은 15초마다 상태를 묻는다 — 그때마다 다시 두드려 8초씩 붙들리지 않게)

# 결과 저장소로 보내는 메서드. 나머지는 모두 시장 자료 저장소로.
RESULT_METHODS = frozenset({
    "save_step", "get_steps", "save_run_artifact", "get_run_artifact",
    "save_report", "get_report", "list_reports", "report_titles", "job_lock",
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


# ───────────────────────── 닿는지 먼저 본다 (사람이 기다리는 길) ─────────────────────────
def with_timeout(url: str) -> str:
    """접속 제한 시간을 붙인다 (SQLite 이거나 주소에 이미 적혀 있으면 그대로)."""
    if url.startswith("sqlite") or "connect_timeout=" in url:
        return url
    return f"{url}{'&' if '?' in url else '?'}connect_timeout={CONNECT_TIMEOUT_S}"


_unreachable: tuple[str, float, BaseException] | None = None  # 마지막으로 닿지 않은 것: (주소, 언제, 오류)


def knock(url: str) -> None:
    """한 번만 접속해 본다 (CONNECT_TIMEOUT_S 안에). 안 되면 그 오류를 그대로 낸다. SQLite 파일은 두드릴 것이 없다.

    저장소(open_repository)는 연결이 끊기면 5·20·60초 쉬고 다시 해 본다 — 밤새 도는 수집 작업에는 맞지만, 화면 앞에서 기다리는
    사람에게는 닿지 않는 주소 하나가 10분이다 (2026-11-23 측정: 접속 130초 × 4번 + 쉬는 85초). 그래서 저장소를 열기 전에 이것부터 부른다.
    """
    global _unreachable  # noqa: PLW0603
    if url.startswith("sqlite"):
        return
    target, connect_args = normalize_db_url(with_timeout(url))
    engine = create_engine(target, connect_args=connect_args)
    try:
        engine.connect().close()
    except Exception as exc:
        _unreachable = (url, time.monotonic(), exc)
        raise
    finally:
        engine.dispose()
    _unreachable = None


def _why_unreachable(url: str) -> BaseException | None:
    """닿지 않으면 그 오류, 닿으면 None. 방금(FAILURE_MEMO_S 안에) 닿지 않았으면 다시 두드리지 않고 그때의 오류를 돌려준다."""
    if _unreachable and _unreachable[0] == url and time.monotonic() - _unreachable[1] < FAILURE_MEMO_S:
        return _unreachable[2]
    try:
        knock(url)
    except Exception as exc:  # noqa: BLE001 — 어떤 실패든 "닿지 않음"
        return exc
    return None


@lru_cache(maxsize=1)
def default_repo() -> Any:
    """화면 서버가 쓰는 저장소. 프로세스 안에서 한 번만 연다 (열지 못하면 다음에 부를 때 다시 해 본다).

    팀 DB 가 닿지 않으면 오래 기다리지 않는다: 한 번 두드려 보고 바로 RepositoryError 를 낸다 (받는 쪽은 그대로 — /health 는 db.ok=false,
    그 밖의 요청은 503). 열린 뒤의 접속에도 같은 제한 시간이 붙는다.
    """
    url = database_url()
    if url:
        failed = _why_unreachable(url)
        if failed is not None:
            raise RepositoryError(f"팀 DB 에 연결하지 못함: {str(failed).splitlines()[0]}", code="REPO_READ_FAILED") from failed
        url = with_timeout(url)
    return open_analysis_repository(url)


def _kind(url: str) -> str:
    """화면용 저장소 이름: PostgreSQL 은 종류만(호스트·계정을 숨김), SQLite 는 로컬 파일 경로만."""
    if url.startswith("sqlite"):
        return "SQLite " + (url.split("///", 1)[1] if "///" in url else "(메모리)")
    return "PostgreSQL"


def describe() -> str:
    """/health 에 싣는 저장소 설명. DB 호스트·계정·비밀번호는 보여 주지 않는다 (2026-11 평가: 호스트가 응답에 그대로 나왔다)."""
    url = database_url()
    market = _kind(url) if url else "로컬 SQLite (data/myfinsight.db)"
    rurl = results_url(url)
    return market if not rurl else f"읽기 {market} / 결과 {_kind(rurl)}"
