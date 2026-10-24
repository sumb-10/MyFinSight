"""M02-01 어댑터 공통 부모(RetryingFetcher) 테스트: 재시도·대기·배치·요청 간격 (네트워크 없음)."""

from __future__ import annotations

import json
from datetime import UTC, date

import pytest
from helpers import StubPriceAdapter, price_rows

from backend.adapters import PriceSourceAdapter
from backend.schemas.errors import DataSourceError

START, END = date(2026, 9, 1), date(2026, 9, 30)


def test_implements_interface() -> None:
    assert isinstance(StubPriceAdapter(), PriceSourceAdapter)


def test_basic_fetch_shape() -> None:
    batch = StubPriceAdapter().fetch(["MSFT", "SPY"], START, END)
    assert batch.source == "TEST"
    assert batch.requested_tickers == ["MSFT", "SPY"]
    assert batch.failed_tickers == {}
    assert batch.fetched_at.utcoffset() == UTC.utcoffset(None)
    rows = batch.payload["MSFT"]
    assert rows[0]["date"] >= "2026-09-01" and rows[-1]["date"] <= "2026-09-30"
    assert set(rows[0]) == {"date", "adj_close", "volume"}
    json.dumps(batch.model_dump(mode="json"))  # 원본 payload 는 JSON 직렬화 가능


def test_unknown_ticker_recorded_not_raised() -> None:
    ad = StubPriceAdapter(known={"MSFT"})
    batch = ad.fetch(["MSFT", "ZZZZ"], START, END)
    assert "MSFT" in batch.payload
    assert "알 수 없는 티커" in batch.failed_tickers["ZZZZ"]
    assert ad.sleep_calls == [1.0, 2.0, 4.0]  # 실패 티커는 retry_max(3)회 재시도


def test_retry_then_success_waits_exponential() -> None:
    ad = StubPriceAdapter(fail_plan={"NVDA": 2}, retry_backoff_sec=1.0)
    batch = ad.fetch(["NVDA", "MSFT"], START, END)
    assert batch.failed_tickers == {}
    assert ad.sleep_calls == [1.0, 2.0]
    assert ad.calls == [("NVDA", "MSFT"), ("NVDA",), ("NVDA",)]  # 실패한 티커만 다시 요청


def test_retry_exhausted_records_reason() -> None:
    ad = StubPriceAdapter(fail_plan={"NVDA": -1}, retry_max=2, retry_backoff_sec=0.5)
    batch = ad.fetch(["NVDA"], START, END)
    assert batch.payload == {}
    assert batch.failed_tickers["NVDA"].startswith("3회 시도 후 실패")
    assert ad.sleep_calls == [0.5, 1.0]


def test_all_fail_still_returns_batch() -> None:
    ad = StubPriceAdapter(batch_failures=99, retry_max=3)
    batch = ad.fetch(["MSFT", "AMD"], START, END)
    assert batch.payload == {}
    assert set(batch.failed_tickers) == {"MSFT", "AMD"}
    assert "ConnectionError" in batch.failed_tickers["MSFT"]
    assert len(ad.calls) == 4


def test_whole_batch_failure_retried() -> None:
    ad = StubPriceAdapter(batch_failures=1)
    batch = ad.fetch(["MSFT"], START, END)
    assert batch.failed_tickers == {} and ad.sleep_calls == [1.0]


def test_retry_max_zero_means_single_attempt() -> None:
    ad = StubPriceAdapter(fail_plan={"MSFT": 1}, retry_max=0)
    batch = ad.fetch(["MSFT"], START, END)
    assert "MSFT" in batch.failed_tickers and ad.sleep_calls == []


def test_batching() -> None:
    ad = StubPriceAdapter(batch_size=3)
    batch = ad.fetch(["AMD", "AVGO", "INTC", "MSFT", "NVDA", "AMD"], START, END)
    assert batch.requested_tickers == ["AMD", "AVGO", "INTC", "MSFT", "NVDA"]  # 중복은 한 번만
    assert ad.calls == [("AMD", "AVGO", "INTC"), ("MSFT", "NVDA")]


def test_min_interval_throttle() -> None:
    ad = StubPriceAdapter(batch_size=1, min_interval_sec=0.5)
    ad._monotonic = lambda: 100.0  # 시계가 멈춰 있으면 매번 전체 간격만큼 기다림
    ad.fetch(["MSFT", "KO", "IBM"], START, END)
    assert ad.sleep_calls == [0.5, 0.5]


def test_bad_args_raise_data_source_error() -> None:
    with pytest.raises(DataSourceError) as e:
        StubPriceAdapter().fetch(["MSFT"], END, START)
    assert e.value.code == "DATA_SOURCE_UNAVAILABLE"
    with pytest.raises(DataSourceError):
        StubPriceAdapter(retry_max=-1)
    with pytest.raises(DataSourceError):
        StubPriceAdapter(batch_size=0)


def test_empty_response_not_retried() -> None:
    days = {date.fromisoformat(r["date"]) for r in price_rows("NVDA", START, END)}
    ad = StubPriceAdapter(missing={"NVDA": days}, retry_backoff_sec=1.0)
    batch = ad.fetch(["NVDA", "MSFT"], START, END)
    assert batch.failed_tickers["NVDA"].startswith("1회 시도 후 실패")
    assert "요청 기간에 데이터 없음" in batch.failed_tickers["NVDA"]
    assert ad.calls == [("NVDA", "MSFT")] and ad.sleep_calls == []  # 빈 응답은 다시 요청 안 함
