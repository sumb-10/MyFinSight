""".env 설정 읽기 (원본 app.config 대체).

- 프로젝트 폴더(현재 작업 폴더)의 `.env` 를 처음 쓸 때 한 번 읽는다. 다른 위치는 환경변수
  MYFINSIGHT_ENV_FILE 로 지정한다. 이미 환경변수에 있는 값은 덮어쓰지 않는다.
- 서버(GitHub Actions·인스턴스)에서는 `.env` 내용 전체를 환경변수 MYFINSIGHT_ENV 하나로
  넣을 수 있다.
  우선순위: 개별 환경변수 > MYFINSIGHT_ENV > `.env` 파일.
- 값은 `config.DART_API_KEY` 처럼 읽을 때마다 환경변수에서 가져온다 (테스트에서 바꾸기 쉬움).
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any

from backend.schemas.errors import DataSourceError

_DEFAULTS = {
    "KIS_ENV": "prod",  # prod(실전) | vts(모의투자)
    "ALPACA_FEED": "sip",  # sip | iex
    "NAVER_API": "hub",  # hub(NAVER API HUB) | developers(developers.naver.com)
    "DB_POOL_SIZE": "5",
    "DB_MAX_OVERFLOW": "2",
    "NEWS_RSS_INTERVAL_SEC": "1.5",  # Google News RSS 백필 요청 간격 (초)
}
_KEYS = (
    "DART_API_KEY",
    "KIS_APP_KEY",
    "KIS_APP_SECRET",
    "KIS_ENV",
    "SEC_USER_AGENT",
    "ALPACA_API_KEY_ID",
    "ALPACA_API_SECRET_KEY",
    "ALPACA_FEED",
    "TIINGO_API_KEY",
    "NAVER_CLIENT_ID",
    "NAVER_CLIENT_SECRET",
    "NAVER_API",
    "NEWSAPI_KEY",
    # DB (M02-04)
    "DATABASE_URL",
    "DB_POOL_SIZE",
    "DB_MAX_OVERFLOW",
    # 서버 수집 작업 (collectors/, jobs/daily.py)
    "UNIVERSE_INDICES",
    "EXTRA_TICKERS",
    "BENCHMARK_TICKERS",
    "PRICE_SOURCES",
    "TIINGO_DAILY_SYMBOLS",
    "PRICE_PRIORITY_US",
    "PRICE_PRIORITY_KR",
    "BACKFILL_YEARS",
    "FIN_YEARS",
    "FIN_REFRESH_DAYS",
    "NEWS_PER_TICKER_DAY",
    "NEWS_KEEP_DAYS",
    "NEWS_DAILY_LIMITS",
    "NEWS_RSS_INTERVAL_SEC",
    "NEWSAPI_DAILY_MAX",
    "VALUATION_YEARS",
    "DART_SHARE_REPORTS",
    "DART_DIVIDEND_REPORTS",
    "API_TOKEN",
)
_loaded = False


class MissingApiKeyError(DataSourceError):
    """.env 에 필요한 키가 없음. 재시도해도 소용없으므로 어댑터가 바로 멈춘다."""

    code = "DATA_SOURCE_CONFIG"


def env_file() -> Path:
    """읽을 .env 경로."""
    return Path(os.environ.get("MYFINSIGHT_ENV_FILE", ".env"))


def parse_env(text: str) -> dict[str, str]:
    """KEY=VALUE 줄을 읽는다. 빈 줄·# 주석·export 접두어·따옴표를 처리한다."""
    out: dict[str, str] = {}
    for raw in text.splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        if line.startswith("export "):
            line = line[len("export ") :]
        key, value = line.split("=", 1)
        value = value.strip()
        if len(value) >= 2 and value[0] == value[-1] and value[0] in "\"'":
            value = value[1:-1]
        elif " #" in value:
            value = value.split(" #", 1)[0].rstrip()
        out[key.strip()] = value
    return out


def load_env(path: Path | None = None, *, force: bool = False) -> None:
    """.env 를 환경변수로 올린다 (이미 있는 환경변수는 그대로)."""
    global _loaded
    if _loaded and not force:
        return
    _loaded = True
    inline = os.environ.get("MYFINSIGHT_ENV", "")
    if inline.strip():
        for k, v in parse_env(inline).items():
            os.environ.setdefault(k, v)
    p = path or env_file()
    if p.exists():
        for k, v in parse_env(p.read_text(encoding="utf-8-sig")).items():
            os.environ.setdefault(k, v)


def get(name: str) -> str:
    """설정값. 없으면 기본값, 기본값도 없으면 빈 문자열."""
    load_env()
    return os.environ.get(name, _DEFAULTS.get(name, "")).strip()


def require(**values: str) -> None:
    """비어 있는 키가 있으면 MissingApiKeyError."""
    missing = [k for k, v in values.items() if not v]
    if missing:
        raise MissingApiKeyError(
            f".env 에 {', '.join(missing)} 값이 없음 (.env.example 참고)",
            details={"missing": missing, "env_file": str(env_file().resolve())},
        )


def cache_dir() -> Path:
    """토큰·코드표 캐시 폴더 (MYFINSIGHT_CACHE_DIR, 기본 ./.cache)."""
    load_env()
    p = Path(os.environ.get("MYFINSIGHT_CACHE_DIR", ".cache"))
    p.mkdir(parents=True, exist_ok=True)
    return p


def __getattr__(name: str) -> Any:
    # config.DART_API_KEY 처럼 원본 크롤러 코드가 쓰던 방식 그대로 읽게 한다.
    if name in _KEYS:
        return get(name)
    if name == "CACHE_DIR":
        return cache_dir()
    raise AttributeError(name)
