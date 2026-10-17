"""M02-02 데이터 정규화기: RawPriceBatch → PriceBar·FxRate 목록 → PriceFrame.

순수 함수만 있다 (I/O 없음). 보간·제외 판단은 하지 않는다 (M02-03 몫).

    from backend.pipeline.normalizer import normalize, to_price_frame
    result = normalize(batch, fx_symbol="KRW=X")
    us, us_meta = to_price_frame(result.bars, currency="USD")
    kr, kr_meta = to_price_frame(result.bars, currency="KRW")   # 한국 종목 (원)
    result.dropped          # 제거된 행 수 (사유별은 result.dropped_by_reason)

통화: 미국 종목 USD, 한국 종목(.KS·.KQ) KRW. 행에 currency 값이 있으면 그것을 따른다.
한 PriceFrame 에는 한 통화만 담는다 (섞이면 DATA_MIXED_CURRENCY).

행을 버리는 경우 (사유 키)
- invalid_price        : adj_close 가 None·NaN·숫자 아님·0 이하
  (open·high·low·close 는 선택 값: 잘못된 값이면 행은 두고 그 칸만 None)
- invalid_date         : 날짜를 읽을 수 없음
- unsupported_currency : 통화가 USD·KRW 가 아님
- duplicate            : 같은 (티커, 날짜) 가 이미 있음 (BRK.B 와 BRK-B 를 둘 다 요청한 경우 등).
                         원본 티커 이름 오름차순으로 먼저 온 행을 남김

환율 행(fx_symbol)은 PriceBar 가 아니라 FxRate(USDKRW) 로 따로 바꾼다.
재무·뉴스 원본은 normalize_financials / normalize_news 로 DB 행(FinancialRow·NewsRow)으로 바꾼다.
"""

from __future__ import annotations

import math
from collections import Counter
from collections.abc import Iterable, Mapping
from datetime import date
from typing import Any

import pandas as pd
from pydantic import BaseModel, ConfigDict

from backend.schemas.errors import DataQualityError
from backend.schemas.market import FxRate, PriceBar, PriceMeta, RawPriceBatch
from backend.schemas.market_ext import (
    AssetInfo,
    FinancialRow,
    NewsRow,
    RawFinancialBatch,
    RawNewsBatch,
)

KR_SUFFIXES: Mapping[str, str] = {".KS": "KOSPI", ".KQ": "KOSDAQ"}
"""한국 종목 yfinance 접미사 → 거래소 (assets.exchange). 통화 표시가 없는 행은 이 접미사면 KRW."""

MARKETS = ("US", "KR")
"""assets.market 값 (데이터 계약: US·KR). 거래소 구분은 assets.exchange 에 둔다."""

SUPPORTED_CURRENCIES = ("USD", "KRW")
DROP_REASONS = ("invalid_price", "invalid_date", "unsupported_currency", "duplicate")


class NormalizeResult(BaseModel):
    """normalize() 결과. dropped = 버린 행 수 합계 (가격·환율 모두)."""

    model_config = ConfigDict(extra="forbid")

    bars: list[PriceBar]
    fx: list[FxRate]
    dropped: int
    dropped_by_reason: dict[str, int]
    dropped_by_ticker: dict[str, int]


def normalize_ticker(ticker: str) -> str:
    """티커를 yfinance 표기로: 앞뒤 공백 제거, 대문자, '.' → '-' (BRK.B → BRK-B).

    거래소 접미사(.KS, .KQ)는 그대로 둔다 (005930.KS).
    """
    t = ticker.strip().upper()
    for suffix in KR_SUFFIXES:
        if t.endswith(suffix):
            return t[: -len(suffix)].replace(".", "-") + suffix
    return t.replace(".", "-")


def is_kr_symbol(symbol: str) -> bool:
    """yfinance 표기가 한국 종목(.KS·.KQ)이면 True."""
    return symbol.upper().endswith(tuple(KR_SUFFIXES))


def currency_of_symbol(symbol: str) -> str:
    """yfinance 표기로 본 통화: 한국 종목 KRW, 나머지 USD."""
    return "KRW" if is_kr_symbol(symbol) else "USD"


def asset_id_for(symbol: str) -> str:
    """yfinance 표기 → 종목 마스터 ID. 005930.KS → KR-005930, BRK-B → US-BRK-B."""
    t = normalize_ticker(symbol)
    if is_kr_symbol(t):
        return "KR-" + t[:-3]
    return "US-" + t


def constituent_ticker(symbol: str) -> str:
    """index_constituent.ticker 계약 표기: 미국 yfinance 표기(BRK-B), 한국 6자리 코드(005930)."""
    t = normalize_ticker(symbol)
    return t[:-3] if is_kr_symbol(t) else t


def default_asset(symbol: str, name: str | None = None) -> AssetInfo:
    """종목 마스터에 없는 종목을 처음 저장할 때 쓰는 기본 행 (출처별 코드는 아는 것만 채움).

    market 은 US·KR (계약), exchange 는 한국 종목만 접미사로 채움 (.KS KOSPI, .KQ KOSDAQ).
    미국 종목의 거래소는 출처마다 표기가 달라 비워 둔다.
    """
    t = normalize_ticker(symbol)
    if is_kr_symbol(t):
        code = t[:-3]
        return AssetInfo(
            asset_id="KR-" + code,
            ticker=code,
            name=name,
            market="KR",
            exchange=KR_SUFFIXES[t[-3:]],
            currency="KRW",
            yfinance_symbol=t,
            kis_ticker=code,
        )
    return AssetInfo(
        asset_id="US-" + t,
        ticker=t,
        name=name,
        market="US",
        currency="USD",
        yfinance_symbol=t,
        tiingo_symbol=t,
        alpaca_symbol=t.replace("-", "."),
    )


def _currency_of(ticker: str, row: Mapping[str, Any]) -> str:
    cur = row.get("currency")
    if cur:
        return str(cur).strip().upper()
    return currency_of_symbol(ticker)


_OHLC = ("open", "high", "low", "close")  # 있으면 담고, 없거나 잘못된 값이면 None


def _positive_float(v: Any) -> float | None:
    if v is None or isinstance(v, bool):
        return None
    try:
        x = float(v)
    except (TypeError, ValueError):
        return None
    if math.isnan(x) or math.isinf(x) or x <= 0:
        return None
    return x


def _volume(v: Any) -> int | None:
    if v is None or isinstance(v, bool):
        return None
    try:
        x = float(v)
    except (TypeError, ValueError):
        return None
    if math.isnan(x) or math.isinf(x) or x < 0:
        return None
    return int(x)


def _to_date(v: Any) -> date | None:
    if isinstance(v, date):
        return v
    try:
        return date.fromisoformat(str(v).strip()[:10])
    except ValueError:
        return None


def normalize(batch: RawPriceBatch, *, fx_symbol: str = "KRW=X") -> NormalizeResult:
    """원본 묶음을 PriceBar·FxRate 목록으로 바꾼다. 같은 원본이면 항상 같은 결과.

    결과 bars 는 (티커, 날짜), fx 는 날짜 오름차순. source·fetched_at 은 batch 값을 복사한다.
    fx_symbol 은 AppConfig.data.fx_symbol 을 넘긴다.
    """
    fx_key = normalize_ticker(fx_symbol)
    reasons: Counter[str] = Counter()
    per_ticker: Counter[str] = Counter()
    bars: dict[tuple[str, date], PriceBar] = {}
    fx: dict[date, FxRate] = {}

    for raw_ticker in sorted(batch.payload):
        rows = batch.payload[raw_ticker] or []
        ticker = normalize_ticker(raw_ticker)
        is_fx = ticker == fx_key
        for row in rows:
            why = None
            d = _to_date(row.get("date"))
            price = _positive_float(row.get("adj_close"))
            if d is None:
                why = "invalid_date"
            elif price is None:
                why = "invalid_price"
            elif is_fx:
                if d in fx:
                    why = "duplicate"
                else:
                    fx[d] = FxRate(
                        date=d, rate=price, source=batch.source, fetched_at=batch.fetched_at
                    )
            elif (cur := _currency_of(ticker, row)) not in SUPPORTED_CURRENCIES:
                why = "unsupported_currency"
            elif (ticker, d) in bars:
                why = "duplicate"
            else:
                bars[(ticker, d)] = PriceBar(
                    ticker=ticker,
                    date=d,
                    adj_close=price,
                    volume=_volume(row.get("volume")),
                    currency=cur,  # type: ignore[arg-type]
                    source=batch.source,
                    fetched_at=batch.fetched_at,
                    **{k: _positive_float(row.get(k)) for k in _OHLC},
                )
            if why:
                reasons[why] += 1
                per_ticker[ticker] += 1

    return NormalizeResult(
        bars=[bars[k] for k in sorted(bars)],
        fx=[fx[k] for k in sorted(fx)],
        dropped=sum(reasons.values()),
        dropped_by_reason={k: reasons[k] for k in DROP_REASONS if reasons[k]},
        dropped_by_ticker=dict(sorted(per_ticker.items())),
    )


def to_price_frame(
    bars: Iterable[PriceBar], *, as_of: date | None = None, currency: str | None = None
) -> tuple[pd.DataFrame, PriceMeta]:
    """PriceBar 목록 → (PriceFrame, PriceMeta). 결측 칸은 NaN 으로 둔다.

    currency 를 주면 그 통화 행만 쓴다. 안 주면 모든 행이 한 통화여야 한다
    (섞이면 DataQualityError(DATA_MIXED_CURRENCY)).
    PriceMeta: source = 출처 이름들('+' 로 이음), as_of = 지정값 또는 마지막 날짜,
    fetched_at = 가장 오래된 수집 시각 (데이터가 언제 것인지 보수적으로 표시),
    tickers = 열 순서와 같음, currency = 값의 통화.
    빈 목록이거나 같은 (티커, 날짜) 가 두 번 있으면 DataQualityError(DATA_INVALID_BARS).
    """
    items = list(bars)
    if currency is not None:
        items = [b for b in items if b.currency == currency]
    currencies = sorted({b.currency for b in items})
    if len(currencies) > 1:
        raise DataQualityError(
            f"통화가 섞여 있음: {currencies} (currency= 로 하나를 고를 것)",
            code="DATA_MIXED_CURRENCY",
            details={"currencies": currencies},
        )
    if not items:
        raise DataQualityError("PriceBar 가 하나도 없음", code="DATA_INVALID_BARS")
    seen: set[tuple[str, date]] = set()
    dups: list[str] = []
    for b in items:
        key = (b.ticker, b.date)
        if key in seen:
            dups.append(f"{b.ticker} {b.date}")
        seen.add(key)
    if dups:
        raise DataQualityError(
            f"같은 (티커, 날짜) 가격이 두 번 이상 있음: {dups[:5]}",
            code="DATA_INVALID_BARS",
            details={"duplicates": dups},
        )
    long = pd.DataFrame(
        {
            "date": pd.to_datetime([b.date for b in items]),
            "ticker": [b.ticker for b in items],
            "adj_close": [b.adj_close for b in items],
        }
    )
    frame = long.pivot(index="date", columns="ticker", values="adj_close").astype("float64")
    frame = frame.sort_index().sort_index(axis=1)
    frame.index.name = "date"
    frame.columns.name = None
    meta = PriceMeta(
        source="+".join(sorted({b.source for b in items})),
        as_of=as_of or max(b.date for b in items),
        fetched_at=min(b.fetched_at for b in items),
        tickers=list(frame.columns),
        currency=currencies[0],  # type: ignore[arg-type]
    )
    return frame, meta


def normalize_to_frame(
    batch: RawPriceBatch, *, fx_symbol: str = "KRW=X", currency: str | None = None
) -> tuple[pd.DataFrame, PriceMeta, NormalizeResult]:
    """normalize() + to_price_frame() 를 한 번에. 환율은 결과의 fx 에 있다."""
    result = normalize(batch, fx_symbol=fx_symbol)
    frame, meta = to_price_frame(result.bars, currency=currency)
    return frame, meta, result


def _opt_str(v: Any) -> str | None:
    if v is None:
        return None
    s = str(v).strip()
    return s or None


def normalize_financials(
    batch: RawFinancialBatch, key_to_asset: Mapping[str, str]
) -> tuple[list[FinancialRow], dict[str, int]]:
    """재무 원본 → FinancialRow 목록. key_to_asset = 고유번호·CIK → asset_id.

    asset 을 모르는 키, 값·공시일이 없는 행은 버리고 사유별 개수를 돌려준다.
    """
    rows: list[FinancialRow] = []
    dropped: Counter[str] = Counter()
    for key in sorted(batch.payload):
        asset_id = key_to_asset.get(key)
        for r in batch.payload[key] or []:
            if asset_id is None:
                dropped["unknown_asset"] += 1
                continue
            value = r.get("value")
            disclosed = _to_date(r.get("disclosed_at"))
            if value is None or disclosed is None:
                dropped["missing_value_or_date"] += 1
                continue
            try:
                num = float(value)
            except (TypeError, ValueError):
                dropped["missing_value_or_date"] += 1
                continue
            if math.isnan(num):
                dropped["missing_value_or_date"] += 1
                continue
            fy = r.get("fiscal_year")
            rows.append(
                FinancialRow(
                    asset_id=asset_id,
                    source=batch.source,
                    period=str(r.get("period") or ""),
                    fs_div=_opt_str(r.get("fs_div")) or "-",
                    metric=str(r.get("metric") or ""),
                    value=num,
                    unit=_opt_str(r.get("unit")),
                    fiscal_year=int(fy) if fy not in (None, "") else None,
                    report_code=_opt_str(r.get("report_code")),
                    period_end=_to_date(r.get("period_end")) if r.get("period_end") else None,
                    disclosed_at=disclosed,
                    rcept_no=_opt_str(r.get("rcept_no")),
                    fetched_at=batch.fetched_at,
                )
            )
    return rows, dict(dropped)


def normalize_news(
    batch: RawNewsBatch, query_to_asset: Mapping[str, str]
) -> tuple[list[NewsRow], dict[str, int]]:
    """뉴스 원본 → NewsRow 목록. query_to_asset = 검색어 → asset_id.

    같은 (종목, url) 은 한 건만 남긴다. 제목·주소·발행 시각이 없는 기사는 버린다.
    """
    rows: dict[tuple[str, str], NewsRow] = {}
    dropped: Counter[str] = Counter()
    for query in sorted(batch.payload):
        asset_id = query_to_asset.get(query)
        for r in batch.payload[query] or []:
            if asset_id is None:
                dropped["unknown_asset"] += 1
                continue
            url, title = _opt_str(r.get("url")), _opt_str(r.get("title"))
            try:
                published = pd.Timestamp(r.get("published_at"))
            except (TypeError, ValueError):
                published = pd.NaT
            if not url or not title or pd.isna(published):
                dropped["missing_field"] += 1
                continue
            if published.tzinfo is None:
                published = published.tz_localize("UTC")
            if (asset_id, url) in rows:
                dropped["duplicate"] += 1
                continue
            rows[(asset_id, url)] = NewsRow(
                asset_id=asset_id,
                source=batch.source,
                url=url,
                title=title,
                content=_opt_str(r.get("description") or r.get("content")),
                publisher=_opt_str(r.get("publisher")),
                published_at=published.tz_convert("UTC").to_pydatetime(),
                language=_opt_str(r.get("language")),
                query=query,
                fetched_at=batch.fetched_at,
            )
    return [rows[k] for k in sorted(rows)], dict(dropped)
