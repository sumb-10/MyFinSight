"""M02-01 가격 수집 어댑터 인터페이스와 공통 재시도 로직.

payload 형식 (M02-01 → M02-02 약속, 역할 A 제안):

    {
        "<티커>": [
            {"date": "2026-09-30", "adj_close": 123.45, "volume": 1000000},
            ...
        ],
        ...
    }

- 티커 키는 요청한 표기 그대로 (환율은 fx_symbol, 예 "KRW=X").
- adj_close 가 비었거나 0 이하인 행도 원본 그대로 둔다 (제거는 M02-02 몫). 빈 값은 None.
- 성공한 티커만 payload 에 들어가고, 실패한 티커는 failed_tickers 에 사유와 함께 들어간다.
- 출처가 시가·고가·저가·종가·통화를 주면 같은 행에 open/high/low/close/currency 키를 더 둔다
  (KIS·Tiingo·Alpaca·yfinance 다중 출처 교차검증용). M02-02 는 모르는 키를 무시하면 된다.

재무·뉴스 어댑터도 같은 재시도 부모(RetryingFetcher)를 쓰고, 출력만 RawFinancialBatch /
RawNewsBatch (schemas/market_ext.py) 로 다르다.
"""

from __future__ import annotations

import logging
import time
from abc import ABC, abstractmethod
from collections.abc import Callable, Sequence
from datetime import UTC, date, datetime
from typing import Any, Protocol, runtime_checkable

from myfinsight.schemas.errors import DataSourceError
from myfinsight.schemas.market import RawPriceBatch
from myfinsight.schemas.market_ext import RawFinancialBatch, RawNewsBatch

NO_DATA = "요청 기간에 데이터 없음"
"""빈 응답 사유. 출처가 정상 응답했으나 데이터가 없는 경우라 다시 요청하지 않는다."""

logger = logging.getLogger(__name__)

PriceRecord = dict[str, Any]
BatchResult = tuple[dict[str, list[PriceRecord]], dict[str, str]]


@runtime_checkable
class PriceSourceAdapter(Protocol):
    """가격 수집 어댑터 인터페이스 (명세 M02-01)."""

    source_name: str

    def fetch(self, tickers: list[str], start: date, end: date) -> RawPriceBatch:
        """tickers 의 [start, end] 수정종가·거래량 원본을 가져온다."""
        ...


@runtime_checkable
class FinancialSourceAdapter(Protocol):
    """재무 어댑터 인터페이스 (확장: DART, SEC EDGAR). 키 = 공시 고유번호 / CIK."""

    source_name: str

    def fetch(self, tickers: list[str], start: date, end: date) -> RawFinancialBatch:
        """공시일이 [start, end] 인 재무 원본을 가져온다."""
        ...


@runtime_checkable
class NewsSourceAdapter(Protocol):
    """뉴스 어댑터 인터페이스 (확장: 네이버 뉴스, NewsAPI, Google News RSS). 키 = 검색어."""

    source_name: str

    def fetch(self, tickers: list[str], start: date, end: date) -> RawNewsBatch:
        """발행일이 [start, end] 인 기사 원본을 검색어별로 가져온다."""
        ...


def utc_now() -> datetime:
    """현재 UTC 시각."""
    return datetime.now(UTC)


class RetryingFetcher(ABC):
    """배치 분할·재시도·요청 간격을 처리하는 공통 부모 (가격·재무·뉴스 어댑터 공용).

    구현체는 `_fetch_batch_once`(한 번 요청)와 `_make_batch`(결과 모델 만들기)만 구현한다.
    모든 어댑터(YFinance, KIS, DART …)가 이 클래스를 상속해 재시도 동작이 같다.

    재시도 규칙: 첫 시도 후 실패한 티커만 최대 retry_max 회 다시 요청한다.
    k 번째 재시도 전 대기 = retry_backoff_sec × 2^(k-1) (1, 2, 4초…).
    """

    source_name: str = "unknown"

    def __init__(
        self,
        *,
        retry_max: int = 3,
        retry_backoff_sec: float = 1.0,
        batch_size: int = 50,
        min_interval_sec: float = 0.0,
        sleep: Callable[[float], None] = time.sleep,
        clock: Callable[[], datetime] = utc_now,
        monotonic: Callable[[], float] = time.monotonic,
    ) -> None:
        if retry_max < 0:
            raise DataSourceError("retry_max 는 0 이상이어야 함", details={"retry_max": retry_max})
        if retry_backoff_sec < 0 or min_interval_sec < 0:
            raise DataSourceError("대기 시간은 0 이상이어야 함")
        if batch_size < 1:
            raise DataSourceError(
                "batch_size 는 1 이상이어야 함", details={"batch_size": batch_size}
            )
        self.retry_max = retry_max
        self.retry_backoff_sec = retry_backoff_sec
        self.batch_size = batch_size
        self.min_interval_sec = min_interval_sec
        self._sleep = sleep
        self._clock = clock
        self._monotonic = monotonic
        self._last_request_at: float | None = None

    @abstractmethod
    def _fetch_batch_once(self, tickers: Sequence[str], start: date, end: date) -> BatchResult:
        """한 배치를 한 번 요청한다.

        반환: (성공 티커 → 행 목록, 실패 티커 → 사유). 배치 전체가 실패하면 예외를 던져도 된다
        (DataSourceError 가 아닌 예외는 배치 전체 실패로 보고 재시도한다).
        """

    @abstractmethod
    def _make_batch(
        self,
        requested: list[str],
        start: date,
        end: date,
        fetched_at: datetime,
        payload: dict[str, list[PriceRecord]],
        failed: dict[str, str],
    ) -> Any:
        """수집 결과를 출력 모델(RawPriceBatch 등)로 묶는다."""

    def fetch(self, tickers: list[str], start: date, end: date) -> Any:
        """키(티커·고유번호·검색어)를 배치로 나눠 요청하고, 실패한 키는 재시도한 뒤 묶는다.

        재시도 후에도 실패한 키는 예외 대신 실패 목록에 사유와 함께 기록한다 (전부 실패해도 반환).
        """
        if start > end:
            raise DataSourceError(
                "start 가 end 보다 늦음", details={"start": str(start), "end": str(end)}
            )
        requested = list(dict.fromkeys(tickers))  # 순서 유지 중복 제거
        fetched_at = self._clock()
        payload: dict[str, list[PriceRecord]] = {}
        failed: dict[str, str] = {}
        for i in range(0, len(requested), self.batch_size):
            batch = requested[i : i + self.batch_size]
            got, bad = self._fetch_with_retry(batch, start, end)
            payload.update(got)
            failed.update(bad)
        if failed:
            logger.warning(
                "%s: %d/%d 티커 수집 실패", self.source_name, len(failed), len(requested)
            )
        return self._make_batch(requested, start, end, fetched_at, payload, failed)

    def _fetch_with_retry(self, batch: list[str], start: date, end: date) -> BatchResult:
        pending = list(batch)
        got: dict[str, list[PriceRecord]] = {}
        failed: dict[str, str] = {}
        for attempt in range(self.retry_max + 1):
            if attempt > 0:
                self._sleep(self.retry_backoff_sec * 2 ** (attempt - 1))
            self._throttle()
            try:
                ok, bad = self._fetch_batch_once(pending, start, end)
            except DataSourceError:
                raise  # 설정 오류 등은 재시도하지 않음
            except Exception as exc:  # noqa: BLE001 - 배치 전체 실패는 재시도 대상
                logger.info("%s: 배치 요청 실패 (시도 %d): %s", self.source_name, attempt + 1, exc)
                ok, bad = {}, {t: f"{type(exc).__name__}: {exc}" for t in pending}
            got.update({t: rows for t, rows in ok.items() if t in pending})
            pending = [t for t in pending if t not in ok]
            last = attempt == self.retry_max
            for t in list(pending):
                reason = bad.get(t, "응답에 티커 없음")
                if last or NO_DATA in reason:  # 빈 응답은 다시 요청해도 같음
                    failed[t] = f"{attempt + 1}회 시도 후 실패: {reason}"
                    pending.remove(t)
            if not pending:
                break
        return got, failed

    def _throttle(self) -> None:
        if self.min_interval_sec <= 0:
            return
        now = self._monotonic()
        if self._last_request_at is not None:
            wait = self.min_interval_sec - (now - self._last_request_at)
            if wait > 0:
                self._sleep(wait)
                now = self._monotonic()
        self._last_request_at = now


class RetryingPriceAdapter(RetryingFetcher):
    """가격 어댑터 공통 부모. 출력은 RawPriceBatch (명세 M02-01)."""

    def _make_batch(
        self,
        requested: list[str],
        start: date,
        end: date,
        fetched_at: datetime,
        payload: dict[str, list[PriceRecord]],
        failed: dict[str, str],
    ) -> RawPriceBatch:
        return RawPriceBatch(
            source=self.source_name,
            requested_tickers=requested,
            start=start,
            end=end,
            fetched_at=fetched_at,
            payload=payload,
            failed_tickers=failed,
        )

    def fetch(self, tickers: list[str], start: date, end: date) -> RawPriceBatch:
        """tickers 의 [start, end] 가격 원본을 가져온다. 실패 티커는 failed_tickers 에 기록."""
        return super().fetch(tickers, start, end)
