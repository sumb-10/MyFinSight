"""테스트 전용 작은 데이터와 스텁 (C-11: 네트워크 없이 테스트). 실제 수집·저장 코드는 쓰지 않는다.

- price_rows(ticker, start, end)  : 평일마다 정해진 값을 내는 가격 행 (환율 KRW=X 는 주말 포함)
- StubPriceAdapter(...)           : RetryingPriceAdapter 를 상속한 가격 스텁. 재시도·배치 로직은
                                    실제 어댑터와 같은 부모 클래스를 그대로 탄다
- make_constituents(index, n)     : GICS 섹터가 채워진 구성종목 n개
- StubConstituentSource(...)      : 구성종목 출처 스텁
- fin_row / news_row / *_batch    : 재무·뉴스 원본 행과 묶음
- StubKeyedAdapter(...)           : 재무·뉴스 어댑터 스텁 (키별 행, 실패 주입)
"""

from __future__ import annotations

from collections.abc import Callable, Iterable, Mapping, Sequence
from datetime import UTC, date, datetime, timedelta

from myfinsight.data.adapters.base import (
    NO_DATA,
    BatchResult,
    PriceRecord,
    RetryingPriceAdapter,
)
from myfinsight.data.constituents import GICS_SECTORS
from myfinsight.schemas.errors import DataSourceError
from myfinsight.schemas.market import IndexCode, IndexConstituent
from myfinsight.schemas.market_ext import RawFinancialBatch, RawNewsBatch

AT = datetime(2026, 10, 1, tzinfo=UTC)
"""스텁이 쓰는 고정 수집 시각."""

FX = "KRW=X"
SECTORS = sorted(GICS_SECTORS)


def _days(start: date, end: date, *, weekends: bool) -> list[date]:
    out, d = [], start
    while d <= end:
        if weekends or d.weekday() < 5:
            out.append(d)
        d += timedelta(days=1)
    return out


def _base(ticker: str) -> float:
    if ticker == FX:
        return 1300.0
    seed = sum(ord(c) for c in ticker)
    if ticker.endswith((".KS", ".KQ")):
        return 10000.0 + seed * 100
    return 20.0 + seed % 400


def price_rows(ticker: str, start: date, end: date) -> list[PriceRecord]:
    """[start, end] 가격 행. 값은 티커·날짜로 정해짐 (결정론). 환율은 거래량 없음."""
    fx = ticker == FX
    base = _base(ticker)
    rows: list[PriceRecord] = []
    for d in _days(start, end, weekends=fx):
        k = d.toordinal() % 17
        rows.append(
            {
                "date": d.isoformat(),
                "adj_close": round(base * (1 + 0.004 * k), 4),
                "volume": None if fx else 1_000_000 + k * 1000,
            }
        )
    return rows


class StubPriceAdapter(RetryingPriceAdapter):
    """테스트용 가격 어댑터. 장애 주입 가능.

    - known: 이 티커만 아는 것으로 함 (None 이면 모든 티커에 값을 만들어 줌)
    - fail_plan={"NVDA": 2}: 처음 2번 실패 후 성공 (-1 이면 항상 실패)
    - batch_failures=1: 처음 1번의 배치 요청은 통째로 ConnectionError
    - missing={"AMD": [date]}: 그 날짜 행을 뺌
    - overrides={"KO": {date: None}}: 그 날짜 adj_close 를 바꿈
    sleep 을 안 넘기면 실제로 기다리지 않고 sleep_calls 에 기록만 한다.
    """

    def __init__(
        self,
        *,
        source: str = "TEST",
        known: Iterable[str] | None = None,
        fail_plan: Mapping[str, int] | None = None,
        batch_failures: int = 0,
        missing: Mapping[str, Sequence[date]] | None = None,
        overrides: Mapping[str, Mapping[date, float | None]] | None = None,
        retry_max: int = 3,
        retry_backoff_sec: float = 1.0,
        batch_size: int = 50,
        min_interval_sec: float = 0.0,
        sleep: Callable[[float], None] | None = None,
        clock: Callable[[], datetime] = lambda: AT,
    ) -> None:
        self.source_name = source
        self.sleep_calls: list[float] = []
        self.calls: list[tuple[str, ...]] = []
        super().__init__(
            retry_max=retry_max,
            retry_backoff_sec=retry_backoff_sec,
            batch_size=batch_size,
            min_interval_sec=min_interval_sec,
            sleep=sleep if sleep is not None else self.sleep_calls.append,
            clock=clock,
        )
        self._known = set(known) if known is not None else None
        self._fail_left = dict(fail_plan or {})
        self._batch_failures_left = batch_failures
        self._missing = {t: {d.isoformat() for d in ds} for t, ds in (missing or {}).items()}
        self._overrides = {
            t: {d.isoformat(): v for d, v in m.items()} for t, m in (overrides or {}).items()
        }

    def _fail(self, ticker: str) -> bool:
        left = self._fail_left.get(ticker, 0)
        if left == 0:
            return False
        if left > 0:
            self._fail_left[ticker] = left - 1
        return True

    def _fetch_batch_once(self, tickers: Sequence[str], start: date, end: date) -> BatchResult:
        self.calls.append(tuple(tickers))
        if self._batch_failures_left > 0:
            self._batch_failures_left -= 1
            raise ConnectionError("stub: 배치 요청 실패")
        ok: dict[str, list[PriceRecord]] = {}
        bad: dict[str, str] = {}
        for t in tickers:
            if self._fail(t):
                bad[t] = "stub: 요청 실패"
                continue
            if self._known is not None and t not in self._known:
                bad[t] = "stub: 알 수 없는 티커"
                continue
            skip = self._missing.get(t, set())
            over = self._overrides.get(t, {})
            rows = []
            for r in price_rows(t, start, end):
                if r["date"] in skip:
                    continue
                if r["date"] in over:
                    r["adj_close"] = over[r["date"]]
                rows.append(r)
            if not rows:
                bad[t] = f"stub: {NO_DATA}"
                continue
            ok[t] = rows
        return ok, bad


def make_constituents(
    index: IndexCode | str,
    n: int,
    *,
    snapshot_date: date = date(2026, 9, 18),
    fetched_at: datetime = AT,
    source: str = "TEST: 테스트 구성종목",
) -> list[IndexConstituent]:
    """구성종목 n개 (티커 오름차순). KOSPI200 은 000010.KS 형식, 나머지는 T0001 형식."""
    code = IndexCode(index)
    rows = []
    for i in range(1, n + 1):
        ticker = f"{i * 10:06d}.KS" if code == IndexCode.KOSPI200 else f"T{i:04d}"
        rows.append(
            IndexConstituent(
                index_code=code,
                ticker=ticker,
                name=f"종목 {i}",
                sector=SECTORS[i % len(SECTORS)],
                industry=f"산업 {i % 7}",
                snapshot_date=snapshot_date,
                source=source,
                fetched_at=fetched_at,
            )
        )
    return rows


class StubConstituentSource:
    """테스트용 구성종목 출처. sizes 의 지수마다 make_constituents 결과를 돌려준다."""

    source_name = "TEST"

    def __init__(
        self,
        sizes: Mapping[IndexCode | str, int] | None = None,
        *,
        fail_indices: Iterable[IndexCode | str] = (),
    ) -> None:
        self.sizes = {IndexCode(k): v for k, v in (sizes or {}).items()}
        self.fail_indices = {IndexCode(i) for i in fail_indices}
        self.calls: list[IndexCode] = []

    def fetch(self, index: IndexCode) -> list[IndexConstituent]:
        code = IndexCode(index)
        self.calls.append(code)
        if code in self.fail_indices:
            raise DataSourceError(f"stub: {code.value} 조회 실패", details={"index": code.value})
        return make_constituents(code, self.sizes.get(code, 0))


# ---------------------------------------------------------------- 재무·뉴스 원본 묶음
PRICE_ROW_KEYS = {"date", "open", "high", "low", "close", "adj_close", "volume", "currency"}
"""OHLC 를 주는 출처(KIS·Tiingo·Alpaca·yfinance)의 가격 행 키."""

FIN_ROW_KEYS = {
    "period",
    "fs_div",
    "metric",
    "value",
    "unit",
    "fiscal_year",
    "report_code",
    "period_end",
    "disclosed_at",
    "rcept_no",
}
"""재무 어댑터(DART·SEC EDGAR) 행 키."""

NEWS_ROW_KEYS = {"url", "title", "description", "publisher", "published_at", "language"}
"""뉴스 어댑터(네이버·NewsAPI·Google RSS) 행 키."""


def fin_row(period: str, metric: str, value: float, disclosed_at: str, **kw: object) -> dict:
    """재무 행 하나 (DART 모양)."""
    row = {
        "period": period,
        "fs_div": "CFS",
        "metric": metric,
        "value": value,
        "unit": "KRW",
        "fiscal_year": int(period[:4]),
        "report_code": "11011",
        "period_end": f"{period[:4]}-12-31",
        "disclosed_at": disclosed_at,
        "rcept_no": disclosed_at.replace("-", "") + "000001",
    }
    row.update(kw)
    return row


def news_row(n: int, published_at: str, *, lang: str = "ko") -> dict:
    """뉴스 행 하나."""
    return {
        "url": f"https://news.example.com/{n:04d}",
        "title": f"기사 {n}",
        "description": f"요약 {n}",
        "publisher": "예시신문",
        "published_at": published_at,
        "language": lang,
    }


def financial_batch(source: str, payload: dict[str, list[dict]]) -> RawFinancialBatch:
    return RawFinancialBatch(
        source=source,
        requested_keys=list(payload),
        start=date(2024, 1, 1),
        end=date(2026, 9, 30),
        fetched_at=AT,
        payload=payload,
    )


def news_batch(source: str, payload: dict[str, list[dict]]) -> RawNewsBatch:
    return RawNewsBatch(
        source=source,
        requested_keys=list(payload),
        start=date(2026, 1, 1),
        end=date(2026, 9, 30),
        fetched_at=AT,
        payload=payload,
    )


class StubKeyedAdapter:
    """재무·뉴스 어댑터 스텁. rows_for(key) 가 그 키의 원본 행을 돌려줌.

    fail 의 키는 요청 실패, empty 의 키는 빈 응답(NO_DATA) 으로 실패.
    """

    def __init__(
        self,
        source: str,
        rows_for: Callable[[str], list[dict]],
        *,
        kind: str = "financial",
        fail: Iterable[str] = (),
        empty: Iterable[str] = (),
    ) -> None:
        self.source_name = source
        self.empty = set(empty)
        self.rows_for = rows_for
        self.kind = kind
        self.fail = set(fail)
        self.calls: list[tuple[list[str], date, date]] = []

    def fetch(self, keys: list[str], start: date, end: date) -> RawFinancialBatch | RawNewsBatch:
        self.calls.append((list(keys), start, end))
        cls = RawFinancialBatch if self.kind == "financial" else RawNewsBatch
        return cls(
            source=self.source_name,
            requested_keys=list(keys),
            start=start,
            end=end,
            fetched_at=AT,
            payload={k: self.rows_for(k) for k in keys if k not in self.fail | self.empty},
            failed_keys={
                **{k: "stub: 요청 실패" for k in keys if k in self.fail},
                **{k: f"1회 시도 후 실패: stub: {NO_DATA}" for k in keys if k in self.empty},
            },
        )
