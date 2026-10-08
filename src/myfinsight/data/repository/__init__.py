"""M02-04 시장 데이터 Repository (PostgreSQL 기본, SQLite 교체 가능).

    from myfinsight.data.repository import open_repository
    repo = open_repository()                     # .env 의 DATABASE_URL 을 따름
    repo = open_repository("postgresql+pg8000://postgres:pw@localhost:5432/myfinsight")
    repo = open_repository("sqlite://")          # 인메모리 (테스트용)

DB 고르기 (open_repository() 에 주소를 안 줄 때 .env 를 따름)
- DATABASE_URL : AWS Lightsail PostgreSQL 주소 (postgresql://…?sslmode=require 를 그대로 붙여 넣음,
                 normalize_db_url 이 pg8000 형식으로 바꿈).
                 비어 있으면 SQLite 파일 data/myfinsight.db
- DB_POOL_SIZE / DB_MAX_OVERFLOW : PostgreSQL 연결 풀 크기 (작은 DB·서버리스 함수는 작게)

다른 모듈은 MarketDataRepository 메서드만 쓴다 (C-10: SQL·테이블 이름을 모름).
"""

from __future__ import annotations

import ssl
from pathlib import Path
from typing import Any

from sqlalchemy import create_engine, event
from sqlalchemy.engine import URL, make_url
from sqlalchemy.exc import ArgumentError, SQLAlchemyError
from sqlalchemy.pool import StaticPool

from myfinsight.data.repository.base import ExtendedRepository, MarketDataRepository
from myfinsight.data.repository.sql import (
    SqliteRepository,
    SqlRepository,
    previous_weekday,
    source_key,
)
from myfinsight.schemas.errors import RepositoryError

__all__ = [
    "ExtendedRepository",
    "MarketDataRepository",
    "SqlRepository",
    "SqliteRepository",
    "default_db_url",
    "normalize_db_url",
    "open_repository",
    "previous_weekday",
    "source_key",
]

DEFAULT_SQLITE_URL = "sqlite:///data/myfinsight.db"
SUPPORTED_BACKENDS = ("postgresql", "sqlite")
# libpq(psql) 전용 주소 옵션. pg8000 은 모르므로 빼고, sslmode 는 ssl_context 로 바꾼다
_LIBPQ_ONLY = (
    "sslmode",
    "channel_binding",
    "sslrootcert",
    "target_session_attrs",
    "connect_timeout",
)
_SSL_VERIFY = ("verify-ca", "verify-full")
_SSL_ON = ("require", "prefer", "allow", *_SSL_VERIFY)


def _sqlite_fk_on(dbapi_conn: Any, _record: Any) -> None:
    cur = dbapi_conn.cursor()
    cur.execute("PRAGMA foreign_keys=ON")
    cur.close()


def default_db_url() -> str:
    """.env 기준 DB 주소 (DATABASE_URL, 비면 SQLite 파일)."""
    from myfinsight.data.crawlers import config

    return config.get("DATABASE_URL") or DEFAULT_SQLITE_URL


def normalize_db_url(url_text: str) -> tuple[URL, dict[str, Any]]:
    """DB 주소를 SQLAlchemy URL 과 드라이버 연결 인자로 바꾼다.

    - postgres:// · postgresql:// → postgresql+pg8000:// (드라이버를 적었으면 그대로)
    - ?sslmode=require 등 libpq 옵션은 주소에서 빼고 pg8000 의 ssl_context 로 바꿈
      (require·prefer: 암호화만, verify-ca·verify-full: 인증서 검증까지)
    Lightsail 콘솔이 주는 주소를 그대로 받기 위함.
    """
    text = url_text.strip()
    if text.startswith("postgres://"):
        text = "postgresql://" + text[len("postgres://") :]
    try:
        url = make_url(text)
    except ArgumentError as exc:
        raise RepositoryError(f"DB 주소 형식 오류: {url_text}", code="REPO_WRITE_FAILED") from exc
    if url.get_backend_name() != "postgresql":
        return url, {}
    if url.drivername == "postgresql":  # 드라이버를 안 적으면 pg8000 (순수 파이썬)
        url = url.set(drivername="postgresql+pg8000")
    connect_args: dict[str, Any] = {}
    if url.drivername == "postgresql+pg8000":
        mode = str(url.query.get("sslmode", "")).lower()
        url = url.difference_update_query(_LIBPQ_ONLY)
        if mode in _SSL_ON:
            ctx = ssl.create_default_context()
            if mode not in _SSL_VERIFY:
                ctx.check_hostname = False
                ctx.verify_mode = ssl.CERT_NONE
            connect_args["ssl_context"] = ctx
    return url, connect_args


def _pool_kwargs() -> dict[str, Any]:
    from myfinsight.data.crawlers import config

    return {
        "pool_pre_ping": True,
        "pool_size": int(config.get("DB_POOL_SIZE") or 5),
        "max_overflow": int(config.get("DB_MAX_OVERFLOW") or 2),
    }


def _price_priority_from_env() -> dict[str, list[str]] | None:
    """PRICE_PRIORITY_US / PRICE_PRIORITY_KR (예: ALPACA,TIINGO,YFINANCE). 없으면 기본값."""
    from myfinsight.data.crawlers import config
    from myfinsight.data.repository.sql import DEFAULT_PRICE_PRIORITY

    out = {k: list(v) for k, v in DEFAULT_PRICE_PRIORITY.items()}
    changed = False
    for cur, key in (("USD", "PRICE_PRIORITY_US"), ("KRW", "PRICE_PRIORITY_KR")):
        if v := config.get(key):
            out[cur] = [x.strip().upper() for x in v.split(",") if x.strip()]
            changed = True
    return out if changed else None


def open_repository(db_url: str | None = None, **kwargs: Any) -> SqlRepository:
    """저장소를 연다. 테이블이 없으면 만들고 data_sources 기본 행을 넣는다.

    db_url 이 None 이면 .env 를 따른다 (default_db_url). PostgreSQL 은 postgresql+pg8000://…
    (또는 +psycopg, Lightsail 주소 postgresql://…?sslmode=require 도 됨),
    SQLite 파일은 상위 폴더를 만들어 준다.
    "sqlite://" 는 인메모리.
    kwargs 는 SqlRepository 로 넘긴다 (cache_max_age_days, clock, price_priority).
    price_priority 를 안 주면 .env 의 PRICE_PRIORITY_US / PRICE_PRIORITY_KR, 없으면 기본값.
    """
    kwargs.setdefault("price_priority", _price_priority_from_env())
    url_text = db_url or default_db_url()
    url, connect_args = normalize_db_url(url_text)
    backend = url.get_backend_name()
    if backend not in SUPPORTED_BACKENDS:
        raise RepositoryError(
            f"지원하지 않는 DB: {backend} (postgresql, sqlite 만)", code="REPO_WRITE_FAILED"
        )
    try:
        if backend == "sqlite":
            db = url.database
            if not db or db == ":memory:":
                engine = create_engine(
                    "sqlite://",
                    poolclass=StaticPool,
                    connect_args={"check_same_thread": False},
                )
            else:
                Path(db).expanduser().resolve().parent.mkdir(parents=True, exist_ok=True)
                engine = create_engine(url)
            event.listen(engine, "connect", _sqlite_fk_on)
        else:
            engine = create_engine(url, connect_args=connect_args, **_pool_kwargs())
    except (SQLAlchemyError, OSError, ImportError) as exc:
        raise RepositoryError(f"DB 열기 실패: {exc}", code="REPO_WRITE_FAILED") from exc
    return SqlRepository(engine, **kwargs)
