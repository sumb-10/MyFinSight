"""M02-01 진짜 어댑터: 역할 A 크롤러(backend.adapters.crawlers)를 명세 형식으로 감싼다.

크롤러 = API 를 부르고 응답을 해석한다 (출처마다 다름).
어댑터 = 크롤러를 불러 명세 형식(RawPriceBatch·RawFinancialBatch·RawNewsBatch)으로 돌려주고,
         재시도·요청 간격·실패 기록은 RetryingFetcher 가 맡는다.

| 어댑터 | 키(fetch 의 tickers) | 크롤러 |
|---|---|---|
| YFinancePriceAdapter | yfinance 표기: MSFT, BRK-B, 005930.KS, KRW=X | yfinance_client |
| KisPriceAdapter | 6자리 국내 종목코드: 005930 | kis_client |
| TiingoPriceAdapter | 미국 티커: MSFT, BRK-B | tiingo_client |
| AlpacaPriceAdapter | 미국 티커: MSFT, BRK.B (BRK-B 도 됨) | alpaca_client |
| DartFinancialAdapter | DART 고유번호 8자리 (6자리 종목코드도 됨) | dart_client |
| SecFinancialAdapter | CIK 숫자 (티커도 됨) | edgar_client |
| NaverNewsAdapter | 한국어 검색어 | naver_news_client |
| NewsApiAdapter | 영어 검색어 | newsapi_client |
| GoogleNewsRssAdapter | 검색어 (lang·country 로 언어 선택) | google_news_rss_client |
| AlpacaNewsAdapter | 미국 티커: AAPL, BRK-B | alpaca_news_client |

뉴스 어댑터의 백필용 메서드 (collectors/news/backfill.py 가 씀, 재시도는 크롤러가 함):
GoogleNewsRssAdapter.fetch_window (한 달 기간), NaverNewsAdapter.fetch_all (최신 1000건),
NewsApiAdapter.fetch_max (최근 29일 100건), AlpacaNewsAdapter.fetch_range (기간 전부).

진짜 어댑터는 기본 batch_size=1 이라 키 하나가 요청 한 번이다. 그래서 재시도와 요청 간격
(min_interval_sec)이 키마다 적용된다. API 키가 .env 에 없으면 MissingApiKeyError 로 바로 멈춘다
(재시도하지 않음). 그 밖의 오류는 그 키만 실패 목록에 사유와 함께 남는다.
"""

from __future__ import annotations

import logging
from collections.abc import Callable, Sequence
from datetime import UTC, date, datetime, timedelta
from typing import Any

from backend.adapters.base import (
    NO_DATA,
    BatchResult,
    RetryingFetcher,
    RetryingPriceAdapter,
)
from backend.adapters.crawlers import (
    alpaca_client,
    alpaca_news_client,
    dart_client,
    edgar_client,
    google_news_rss_client,
    kis_client,
    naver_news_client,
    newsapi_client,
    tiingo_client,
    yfinance_client,
)
from backend.schemas.errors import DataSourceError
from backend.schemas.market_ext import RawFinancialBatch, RawNewsBatch

Rows = list[dict[str, Any]]
logger = logging.getLogger(__name__)


class _PerKeyCrawl:
    """키마다 크롤러를 불러 기간으로 거르는 공통 동작."""

    source_name: str
    _date_field: str = "date"

    def _rows(self, key: str, start: date, end: date) -> Rows:
        raise NotImplementedError

    def _keep(
        self, key: str, rows: Rows, start: date, end: date, ok: dict[str, Rows], bad: dict[str, str]
    ) -> None:
        """기간 안의 행만 남겨 ok 에, 하나도 없으면 bad 에 적는다."""
        lo, hi = start.isoformat(), end.isoformat()
        field = self._date_field
        rows = [r for r in rows if r.get(field) and lo <= r[field][:10] <= hi]
        if not rows:
            bad[key] = f"{self.source_name}: {NO_DATA}"
            return
        ok[key] = sorted(rows, key=lambda r: r[field])

    def _fetch_batch_once(self, tickers: Sequence[str], start: date, end: date) -> BatchResult:
        ok: dict[str, Rows] = {}
        bad: dict[str, str] = {}
        for key in tickers:
            try:
                rows = self._rows(key, start, end)
            except DataSourceError:
                raise  # .env 키 없음 등 설정 오류는 재시도해도 같으므로 바로 알린다
            except Exception as exc:  # noqa: BLE001 - 키 하나의 실패는 기록하고 다음 키로
                bad[key] = f"{type(exc).__name__}: {exc}"
                continue
            self._keep(key, rows, start, end, ok, bad)
        return ok, bad


class _ManyKeyCrawl(_PerKeyCrawl):
    """여러 키를 한 요청으로 받는 출처. 묶음 요청에서 빠진 키만 한 개씩 다시 받는다."""

    def _rows_many(self, keys: list[str], start: date, end: date) -> dict[str, Rows]:
        raise NotImplementedError

    def _fetch_batch_once(self, tickers: Sequence[str], start: date, end: date) -> BatchResult:
        ok: dict[str, Rows] = {}
        bad: dict[str, str] = {}
        if len(tickers) > 1:
            try:
                many = self._rows_many(list(tickers), start, end)
            except DataSourceError:
                raise
            except Exception as exc:  # noqa: BLE001 - 묶음이 실패하면 한 개씩으로 넘어감
                logger.info("%s: 묶음 요청 실패, 한 종목씩 받음: %s", self.source_name, exc)
                many = {}
            for key, rows in many.items():
                self._keep(key, rows, start, end, ok, bad)
            bad.clear()  # 묶음에서 비었던 키도 한 개씩 다시 확인
        for i, key in enumerate(t for t in tickers if t not in ok):
            if i:
                self._throttle()  # type: ignore[attr-defined]  # 한 개씩 받을 때도 요청 간격 지킴
            more_ok, more_bad = super()._fetch_batch_once([key], start, end)
            ok.update(more_ok)
            bad.update(more_bad)
        return ok, bad


def _init_kwargs(
    retry_max: int,
    retry_backoff_sec: float,
    batch_size: int,
    min_interval_sec: float,
    sleep: Callable[[float], None] | None,
    clock: Callable[[], datetime] | None,
) -> dict[str, Any]:
    kw: dict[str, Any] = {
        "retry_max": retry_max,
        "retry_backoff_sec": retry_backoff_sec,
        "batch_size": batch_size,
        "min_interval_sec": min_interval_sec,
    }
    if sleep is not None:
        kw["sleep"] = sleep
    if clock is not None:
        kw["clock"] = clock
    return kw


# ---------------------------------------------------------------- 가격


class _RealPriceAdapter(_PerKeyCrawl, RetryingPriceAdapter):
    default_interval: float = 0.0
    default_batch_size: int = 1

    def __init__(
        self,
        *,
        retry_max: int = 3,
        retry_backoff_sec: float = 1.0,
        batch_size: int | None = None,
        min_interval_sec: float | None = None,
        sleep: Callable[[float], None] | None = None,
        clock: Callable[[], datetime] | None = None,
    ) -> None:
        interval = self.default_interval if min_interval_sec is None else min_interval_sec
        super().__init__(
            **_init_kwargs(
                retry_max,
                retry_backoff_sec,
                self.default_batch_size if batch_size is None else batch_size,
                interval,
                sleep,
                clock,
            )
        )

    @classmethod
    def from_settings(cls, data_settings: Any, **kwargs: Any) -> _RealPriceAdapter:
        """AppConfig.data (DataSettings) 의 retry_max·retry_backoff_sec 를 그대로 쓴다."""
        kwargs.setdefault("retry_max", data_settings.retry_max)
        kwargs.setdefault("retry_backoff_sec", data_settings.retry_backoff_sec)
        return cls(**kwargs)


class YFinancePriceAdapter(_ManyKeyCrawl, _RealPriceAdapter):
    """yfinance 일봉. 미국·국내(.KS/.KQ)·환율(KRW=X). 키 불필요, yfinance 패키지 필요.

    여러 종목은 yf.download 한 번으로 (안에서 동시 요청). 빠진 종목만 한 개씩 다시.
    """

    source_name = "YFINANCE"
    default_interval = 0.5
    default_batch_size = 20

    def _rows(self, key: str, start: date, end: date) -> Rows:
        return yfinance_client.price_rows(key, start, end)

    def _rows_many(self, keys: list[str], start: date, end: date) -> dict[str, Rows]:
        return yfinance_client.price_rows_many(keys, start, end)


class KisPriceAdapter(_RealPriceAdapter):
    """한국투자증권 국내주식 일봉. close = adj_close (KIS 수정주가)."""

    source_name = "KIS"
    default_interval = 0.1

    def _rows(self, key: str, start: date, end: date) -> Rows:
        return kis_client.price_rows(key, start, end)


class TiingoPriceAdapter(_RealPriceAdapter):
    """Tiingo 미국 일봉. close = 분할만 보정, adj_close = 분할+배당 보정."""

    source_name = "TIINGO"

    def _rows(self, key: str, start: date, end: date) -> Rows:
        return tiingo_client.price_rows(key, start, end)


class AlpacaPriceAdapter(_ManyKeyCrawl, _RealPriceAdapter):
    """Alpaca 미국 일봉. close = 분할만 보정, adj_close = 분할+배당 보정. 종료일은 어제까지.

    여러 종목은 /v2/stocks/bars?symbols=… 로 한 번에 (분할·전체 보정 두 요청).
    """

    source_name = "ALPACA"
    default_interval = 0.3
    default_batch_size = 50

    def _rows(self, key: str, start: date, end: date) -> Rows:
        return alpaca_client.price_rows(key, start, end)

    def _rows_many(self, keys: list[str], start: date, end: date) -> dict[str, Rows]:
        return alpaca_client.price_rows_many(keys, start, end)


# ---------------------------------------------------------------- 재무·뉴스 공통


class _RealKeyedAdapter(_PerKeyCrawl, RetryingFetcher):
    default_interval: float = 0.0
    _batch_cls: type[RawFinancialBatch] | type[RawNewsBatch]

    def __init__(
        self,
        *,
        retry_max: int = 3,
        retry_backoff_sec: float = 1.0,
        batch_size: int = 1,
        min_interval_sec: float | None = None,
        sleep: Callable[[float], None] | None = None,
        clock: Callable[[], datetime] | None = None,
    ) -> None:
        interval = self.default_interval if min_interval_sec is None else min_interval_sec
        super().__init__(
            **_init_kwargs(retry_max, retry_backoff_sec, batch_size, interval, sleep, clock)
        )

    def _make_batch(
        self,
        requested: list[str],
        start: date,
        end: date,
        fetched_at: datetime,
        payload: dict[str, Any],
        failed: dict[str, str],
    ) -> Any:
        return self._batch_cls(
            source=self.source_name,
            requested_keys=requested,
            start=start,
            end=end,
            fetched_at=fetched_at,
            payload=payload,
            failed_keys=failed,
        )


# ---------------------------------------------------------------- 재무


class DartFinancialAdapter(_RealKeyedAdapter):
    """OpenDART 주요계정 + 분기·누적 + 주식 총수 + 배당. 공시일이 [start, end] 인 행만 돌려준다.

    요청 한도 초과(020)·키 오류는 DartLimitError(DataSourceError) 로 바로 멈춘다.
    """

    source_name = "DART"
    _date_field = "disclosed_at"
    _batch_cls = RawFinancialBatch

    def __init__(
        self,
        *,
        report_codes: Sequence[str] = ("11011", "11013", "11012", "11014"),
        share_codes: Sequence[str] | None = None,
        dividend_codes: Sequence[str] | None = None,
        **kw: Any,
    ) -> None:
        """report_codes: 11011 사업, 11013 1분기, 11012 반기, 11014 3분기 보고서 (주요계정).

        share_codes: 주식 총수를 받을 보고서 (기본 .env DART_SHARE_REPORTS, 없으면 네 개 모두).
        dividend_codes: 배당을 받을 보고서 (기본 .env DART_DIVIDEND_REPORTS, 없으면 사업보고서만).
        빈 목록이면 받지 않는다.
        """
        super().__init__(**kw)
        self.report_codes = tuple(report_codes)
        self.share_codes = tuple(
            share_codes if share_codes is not None else _codes("DART_SHARE_REPORTS", report_codes)
        )
        self.dividend_codes = tuple(
            dividend_codes
            if dividend_codes is not None
            else _codes("DART_DIVIDEND_REPORTS", ("11011",))
        )

    def _rows(self, key: str, start: date, end: date) -> Rows:
        corp = dart_client.resolve_corp_code(key)
        # 사업연도 Y 의 사업보고서는 Y+1 년 3월쯤 공시되므로 한 해 앞부터 본다
        # (그 해는 사업보고서 주요계정만: 분기 보고서는 조회 시작 전에 공시돼 어차피 걸러짐)
        years = list(range(start.year - 1, end.year + 1))
        return dart_client.financial_rows(
            corp,
            years,
            self.report_codes,
            share_codes=self.share_codes,
            dividend_codes=self.dividend_codes,
            today=end,
            annual_only_years=(start.year - 1,),
        )

    def fetch(self, tickers: list[str], start: date, end: date) -> RawFinancialBatch:
        """키(고유번호·종목코드)별 재무 원본. 실패한 키는 failed_keys 에 기록."""
        return super().fetch(tickers, start, end)


def _codes(env: str, default: Sequence[str]) -> list[str]:
    from backend.adapters.crawlers import config

    v = config.get(env)
    if not v:
        return list(default)
    return [x.strip() for x in v.split(",") if x.strip() and x.strip() != "-"]


class SecFinancialAdapter(_RealKeyedAdapter):
    """SEC EDGAR companyfacts. 연간·분기 계정, 유통주식수 이력, 최신 스냅샷 (공시일로 거름)."""

    source_name = "SEC_EDGAR"
    _date_field = "disclosed_at"
    _batch_cls = RawFinancialBatch
    default_interval = 0.15  # SEC 정책: 초당 10회 이하

    def __init__(self, *, include_snapshot: bool = True, **kw: Any) -> None:
        """include_snapshot=False 면 SNAPSHOT(EPS TTM 등 오늘 기준 값) 행을 뺀다."""
        super().__init__(**kw)
        self.include_snapshot = include_snapshot

    def _rows(self, key: str, start: date, end: date) -> Rows:
        facts = edgar_client.fetch_company_facts(edgar_client.resolve_cik(key))
        rows = edgar_client.build_rows(
            facts, years=end.year - start.year + 2, today=end, ticker=key
        )
        if not self.include_snapshot:
            rows = [r for r in rows if r["report_code"] != "SNAPSHOT"]
        return rows

    def fetch(self, tickers: list[str], start: date, end: date) -> RawFinancialBatch:
        """키(CIK·티커)별 재무 원본. 실패한 키는 failed_keys 에 기록."""
        return super().fetch(tickers, start, end)


# ---------------------------------------------------------------- 뉴스


def _days_back(start: date, today: date | None = None) -> int:
    """start 부터 오늘까지 며칠인지 (검색 API 의 '최근 N일' 인자용)."""
    today = today or datetime.now(UTC).date()
    return max(1, (today - start).days + 1)


class NaverNewsAdapter(_RealKeyedAdapter):
    """네이버 뉴스 검색 (최신순 100건). 발행일(UTC)이 [start, end] 인 기사만."""

    source_name = "NAVER_NEWS"
    _date_field = "published_at"
    _batch_cls = RawNewsBatch

    def _rows(self, key: str, start: date, end: date) -> Rows:
        return naver_news_client.news_rows(key)

    def fetch_all(self, query: str) -> Rows:
        """백필: 최신순으로 API 한계(start ≤ 1000, 100건씩)까지 모두."""
        return naver_news_client.news_rows_all(query)

    def fetch(self, tickers: list[str], start: date, end: date) -> RawNewsBatch:
        """검색어별 기사 원본."""
        return super().fetch(tickers, start, end)


class NewsApiAdapter(_RealKeyedAdapter):
    """NewsAPI everything 검색. 무료 플랜은 최근 1개월만 된다."""

    source_name = "NEWSAPI"
    _date_field = "published_at"
    _batch_cls = RawNewsBatch

    def __init__(self, *, language: str = "en", **kw: Any) -> None:
        super().__init__(**kw)
        self.language = language

    def _rows(self, key: str, start: date, end: date) -> Rows:
        return newsapi_client.news_rows(key, days=_days_back(start), language=self.language)

    def fetch_max(self, query: str, days: int = 29) -> Rows:
        """백필: 무료 플랜이 허용하는 최대 (최근 29일, 100건 한 쪽)."""
        return newsapi_client.news_rows(query, days=days, language=self.language, page_size=100)

    def fetch(self, tickers: list[str], start: date, end: date) -> RawNewsBatch:
        """검색어별 기사 원본."""
        return super().fetch(tickers, start, end)


class GoogleNewsRssAdapter(_RealKeyedAdapter):
    """Google News RSS 검색. 국내 종목은 lang="ko", country="KR", 미국 종목은 "en", "US"."""

    source_name = "GOOGLE_RSS"
    _date_field = "published_at"
    _batch_cls = RawNewsBatch

    def __init__(self, *, lang: str = "ko", country: str = "KR", **kw: Any) -> None:
        super().__init__(**kw)
        self.lang, self.country = lang, country

    def _rows(self, key: str, start: date, end: date) -> Rows:
        return google_news_rss_client.news_rows(
            key, self.lang, self.country, days=_days_back(start)
        )

    def fetch_window(self, query: str, after: date, before: date, *, interval: float = 1.5) -> Rows:
        """백필: [after, before) 기간 검색 결과 전부 (요청 간격·429 대기는 크롤러가 함)."""
        return google_news_rss_client.window_rows(
            query, after, before, self.lang, self.country, interval=interval
        )

    def fetch(self, tickers: list[str], start: date, end: date) -> RawNewsBatch:
        """검색어별 기사 원본."""
        return super().fetch(tickers, start, end)


class AlpacaNewsAdapter(_RealKeyedAdapter):
    """Alpaca News (Benzinga). 키 = 미국 티커. 발행일(UTC)이 [start, end] 인 기사."""

    source_name = "ALPACA_NEWS"
    _date_field = "published_at"
    _batch_cls = RawNewsBatch

    def _rows(self, key: str, start: date, end: date) -> Rows:
        return alpaca_news_client.news_rows(key, start, end + timedelta(days=1), max_pages=4)

    def fetch_range(self, symbol: str, start: date, end: date) -> Rows:
        """백필: [start, end) 기사 전부 (쪽 끝까지)."""
        return alpaca_news_client.news_rows(symbol, start, end)

    def fetch(self, tickers: list[str], start: date, end: date) -> RawNewsBatch:
        """티커별 기사 원본."""
        return super().fetch(tickers, start, end)


PRICE_ADAPTERS: dict[str, type[_RealPriceAdapter]] = {
    "YFINANCE": YFinancePriceAdapter,
    "KIS": KisPriceAdapter,
    "TIINGO": TiingoPriceAdapter,
    "ALPACA": AlpacaPriceAdapter,
}
FINANCIAL_ADAPTERS: dict[str, type[_RealKeyedAdapter]] = {
    "DART": DartFinancialAdapter,
    "SEC_EDGAR": SecFinancialAdapter,
}
NEWS_ADAPTERS: dict[str, type[_RealKeyedAdapter]] = {
    "NAVER_NEWS": NaverNewsAdapter,
    "NEWSAPI": NewsApiAdapter,
    "GOOGLE_RSS": GoogleNewsRssAdapter,
    "ALPACA_NEWS": AlpacaNewsAdapter,
}
