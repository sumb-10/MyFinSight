"""서버용 설정: DB 주소 변환(Lightsail 주소 그대로), MYFINSIGHT_ENV, 여러 티커 한 번에 캐시 판단."""

from __future__ import annotations

import ssl
from datetime import date

import pytest
from helpers import AT, StubPriceAdapter

from backend.adapters.crawlers import config
from backend.pipeline.price_loader import load_prices
from backend.db import normalize_db_url, open_repository


@pytest.mark.parametrize(
    ("text", "driver", "query"),
    [
        ("postgres://u:p@db.example.com:5432/app", "postgresql+psycopg", {}),
        (
            "postgresql://u:p@h/app?sslmode=require&channel_binding=require",
            "postgresql+psycopg",
            {"sslmode": "require", "channel_binding": "require"},
        ),
        (
            "postgresql+psycopg://u:p@h/app?sslmode=require",
            "postgresql+psycopg",
            {"sslmode": "require"},
        ),
        ("postgresql+pg8000://u:p@h/app?sslmode=require", "postgresql+pg8000", {}),
        (
            "postgresql://u:p@h/app?application_name=x",
            "postgresql+psycopg",
            {"application_name": "x"},
        ),
    ],
)
def test_normalize_db_url(text: str, driver: str, query: dict) -> None:
    url, _ = normalize_db_url(text)
    assert url.drivername == driver
    assert dict(url.query) == query
    assert (url.host, url.database, url.password) == (url.host, "app", "p")


def test_sslmode_kept_for_psycopg_and_mapped_for_pg8000() -> None:
    """psycopg(libpq)는 sslmode 를 그대로 알아듣고, 예전 pg8000 주소만 ssl_context 로 바꿈."""
    url, args = normalize_db_url("postgres://u:p@h/app?sslmode=require")
    assert url.query["sslmode"] == "require" and args == {}
    _, args = normalize_db_url("postgresql+pg8000://u:p@h/app?sslmode=require")
    ctx = args["ssl_context"]
    assert ctx.verify_mode == ssl.CERT_NONE and not ctx.check_hostname
    _, args = normalize_db_url("postgresql+pg8000://u:p@h/app?sslmode=verify-full")
    assert args["ssl_context"].verify_mode == ssl.CERT_REQUIRED
    _, args = normalize_db_url("postgresql+pg8000://u:p@h/app?sslmode=disable")
    assert "ssl_context" not in args
    _, args = normalize_db_url("sqlite://")
    assert args == {}


def test_pool_size_from_env(monkeypatch: pytest.MonkeyPatch) -> None:
    pytest.importorskip("psycopg")
    monkeypatch.setenv("DB_POOL_SIZE", "2")
    monkeypatch.setenv("DB_MAX_OVERFLOW", "0")
    from backend.db import _pool_kwargs

    assert _pool_kwargs() == {"pool_pre_ping": True, "pool_size": 2, "max_overflow": 0}


def test_inline_env_block(monkeypatch: pytest.MonkeyPatch, tmp_path) -> None:  # noqa: ANN001
    monkeypatch.setattr(config, "_loaded", False)
    monkeypatch.setenv("MYFINSIGHT_ENV_FILE", str(tmp_path / "없음.env"))
    monkeypatch.setenv("MYFINSIGHT_ENV", "# 서버 비밀값\nDART_API_KEY=abc\nDB_POOL_SIZE=9\n")
    monkeypatch.setenv("DB_POOL_SIZE", "3")  # 개별 환경변수가 이김
    assert config.get("DART_API_KEY") == "abc"
    assert config.get("DB_POOL_SIZE") == "3"


def test_inline_env_beats_env_file(monkeypatch: pytest.MonkeyPatch, tmp_path) -> None:  # noqa: ANN001
    f = tmp_path / ".env"
    f.write_text("NEWSAPI_KEY=file\nTIINGO_API_KEY=file\n", encoding="utf-8")
    monkeypatch.setattr(config, "_loaded", False)
    monkeypatch.setenv("MYFINSIGHT_ENV_FILE", str(f))
    monkeypatch.setenv("MYFINSIGHT_ENV", "NEWSAPI_KEY=inline")
    assert config.get("NEWSAPI_KEY") == "inline"
    assert config.get("TIINGO_API_KEY") == "file"


def test_tickers_needing_fetch_matches_needs_fetch() -> None:
    repo = open_repository("sqlite://", clock=lambda: AT)
    load_prices(
        ["MSFT", "SPY"],
        date(2026, 6, 1),
        date(2026, 9, 30),
        adapter=StubPriceAdapter(),
        repository=repo,
        today=date(2026, 10, 1),
    )
    tickers = ["MSFT", "SPY", "NVDA"]
    for start, today in [
        (date(2026, 6, 1), date(2026, 10, 1)),
        (date(2026, 1, 1), date(2026, 10, 1)),
        (date(2026, 6, 1), date(2026, 10, 9)),
    ]:
        end = date(2026, 9, 30) if today.day == 1 else date(2026, 10, 8)
        expected = [t for t in tickers if repo.needs_fetch(t, start, end, today=today)]
        assert repo.tickers_needing_fetch(tickers, start, end, today=today) == expected


def test_price_priority_from_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("PRICE_PRIORITY_US", "tiingo, alpaca")
    repo = open_repository("sqlite://", clock=lambda: AT)
    assert repo.price_priority["USD"] == ("TIINGO", "ALPACA")
    assert repo.price_priority["KRW"] == ("YFINANCE", "KIS")
