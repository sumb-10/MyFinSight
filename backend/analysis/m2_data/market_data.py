"""Repository 위의 시장 자료 파사드 (M2-02).

MarketData   실행 하나가 공유하는 캐시. `ceiling` = 분석 기준일(두 시장 자료가 모두 완료된 최신 거래일).
MarketDataView(as_of)  기준일로 자른 조회. end > as_of 를 요청하면 LookaheadError (요구 15).

혼합 시장 규칙 (K16, 1차):
  달력 = 요청 시장들의 비교지수 거래일 합집합. 휴장일은 직전 종가 유지(ffill). 한국 가격은 그 거래일 환율로 USD 환산.
정보 마감·체결 (D4):
  구성일 d 의 추정(`adj_close(strict_before=True)`)은 d 이전 자료만, 체결(`panel`)은 d 종가까지.
"""

from __future__ import annotations

import datetime as dt
import logging
import threading
from collections.abc import Iterable, Sequence
from dataclasses import dataclass, field
from typing import Any

import numpy as np
import pandas as pd

from backend.analysis.errors import DataMissing, LookaheadError
from backend.analysis.m2_data.news import EvidenceWindow, build_window
from backend.analysis.m2_data.quality import assess
from backend.analysis.settings import AnalysisSettings
from backend.pipeline.normalizer import currency_of_symbol, normalize_ticker
from backend.schemas.market import DataQualityReport, FxRate, IndexCode

MARKET_BENCH = {"US": "primary_benchmark_default", "KR": "kr_benchmark"}
# 창 첫날이 어느 시장의 휴장일이면 "직전 종가"가 창 안에 없다. 이만큼 앞서 읽어 채운 뒤 잘라낸다.
log = logging.getLogger(__name__)
HOLIDAY_LOOKBACK_DAYS = 14
UNIVERSE_INDEX = {"SP500": IndexCode.SP500, "NASDAQ100": IndexCode.NDX, "KOSPI200": IndexCode.KOSPI200}


def _d(x: Any) -> dt.date:
    """pd.Timestamp 도 datetime.date 의 하위 타입이므로 항상 date 로 바꾼다."""
    return pd.Timestamp(x).date()


@dataclass
class _Cache:
    bars: pd.DataFrame | None = None  # long: ticker, date, close, adj_close, volume, currency
    bars_range: tuple[dt.date, dt.date] | None = None
    tickers_loaded: set[str] = field(default_factory=set)  # 요청해서 적재한 종목 (자료가 없는 신규 상장 종목도 포함 → 재적재 방지)
    first_date: dict[str, dt.date] = field(default_factory=dict)  # 적재 범위 안 종목별 첫 가격 날짜
    n_loads: int = 0
    fx: pd.Series | None = None  # index date, value KRW per USD (daily, 원본만)
    fx_range: tuple[dt.date, dt.date] | None = None
    valuation: dict[tuple[dt.date, frozenset[str]], pd.DataFrame] = field(default_factory=dict)
    news: dict[tuple, EvidenceWindow] = field(default_factory=dict)


class MarketData:
    def __init__(self, repo: Any, settings: AnalysisSettings, *, ceiling: dt.date | None = None) -> None:
        self.repo = repo
        self.s = settings
        self.assets: dict[str, dict[str, Any]] = repo.asset_map()  # yfinance 표기 → 마스터
        self._c = _Cache()
        self._lock = threading.RLock()  # 병렬 단계가 동시에 적재를 요청해도 한 번만 (라운드 4)
        self.ceiling = ceiling or self.latest_trading_day(self.s.market.markets)
        if ceiling is not None and ceiling > self.latest_trading_day(self.s.market.markets):
            raise DataMissing(f"기준일 {ceiling} 의 자료가 아직 없음", details={"latest": str(self.latest_trading_day())})

    # ───────────────────────── 종목 메타 ─────────────────────────
    def benchmark_of(self, market: str) -> str:
        return getattr(self.s.market, MARKET_BENCH[market])

    def benchmarks(self, markets: Iterable[str] | None = None) -> list[str]:
        return [self.benchmark_of(m) for m in (markets or self.s.market.markets)]

    def asset_id(self, ticker: str) -> str:
        t = normalize_ticker(ticker)
        if t in self.assets:
            return self.assets[t]["asset_id"]
        return ("KR-" + t[:-3]) if t.endswith((".KS", ".KQ")) else "US-" + t

    def market_of(self, ticker: str) -> str:
        t = normalize_ticker(ticker)
        return self.assets.get(t, {}).get("market") or ("KR" if currency_of_symbol(t) == "KRW" else "US")

    def currency_of(self, ticker: str) -> str:
        t = normalize_ticker(ticker)
        return self.assets.get(t, {}).get("currency") or currency_of_symbol(t)

    def name_of(self, ticker: str) -> str:
        return self.assets.get(normalize_ticker(ticker), {}).get("name") or ticker

    # ───────────────────────── 기준일·범위 ─────────────────────────
    def latest_trading_day(self, markets: Iterable[str] | None = None) -> dt.date:
        """요청 시장들의 비교지수가 모두 자료를 가진 마지막 날짜 (혼합 시장: 둘 다 완료된 날)."""
        benches = self.benchmarks(markets)
        last = self.repo.price_last_dates([self.asset_id(b) for b in benches])
        missing = [b for b in benches if self.asset_id(b) not in last]
        if missing:
            raise DataMissing(f"비교지수 가격이 없음: {missing}", details={"tickers": missing})
        return min(last.values())

    def common_trading_day_on_or_before(self, d: dt.date, markets: Iterable[str] | None = None) -> dt.date:
        """d 이하에서 요청 시장들이 모두 거래한 마지막 날 (한쪽만 휴장인 날은 건너뜀)."""
        benches = self.benchmarks(markets)
        b = self.bars(benches, d - dt.timedelta(days=HOLIDAY_LOOKBACK_DAYS * 3), d)
        if b.empty:
            raise DataMissing(f"{d} 이전 {HOLIDAY_LOOKBACK_DAYS * 3}일 안에 비교지수 가격이 없음", details={"tickers": benches})
        common = None
        for t in benches:
            days = set(b.loc[b["ticker"] == normalize_ticker(t), "date"])
            common = days if common is None else common & days
        if not common:
            raise DataMissing(f"{d} 이전에 {benches} 가 모두 거래한 날이 없음", details={"tickers": benches})
        return _d(max(common))

    def data_range(self, markets: Iterable[str] | None = None) -> tuple[dt.date, dt.date]:
        benches = self.benchmarks(markets)
        starts = []
        for b in benches:
            r = self.repo.covered_range(b)
            if r is None:
                raise DataMissing(f"비교지수 가격이 없음: {b}", details={"tickers": [b]})
            starts.append(r[0])
        return max(starts), self.ceiling

    # ───────────────────────── 캐시 적재 ─────────────────────────
    def prefetch(self, tickers: Iterable[str], start: dt.date, end: dt.date | None = None) -> None:
        """가격(종목 + 모든 비교지수)과 환율을 [start, end≤ceiling] 로 한 번 적재한다. 다시 부르면 범위·종목을 합친다."""
        with self._lock:
            self._prefetch(tickers, start, end)

    def _prefetch(self, tickers: Iterable[str], start: dt.date, end: dt.date | None = None) -> None:
        end = min(end or self.ceiling, self.ceiling)
        want = {normalize_ticker(t) for t in tickers} | set(self.benchmarks()) | set(self.s.market.extra_benchmarks)
        c = self._c
        if c.bars is not None and c.bars_range:
            lo, hi = c.bars_range
            if start >= lo and end <= hi and want <= c.tickers_loaded:
                return
            start, end = min(start, lo), max(end, hi)
            want = want | c.tickers_loaded
            log.warning("[md] price reload #%d: +%d tickers, %s~%s (이미 적재한 범위 밖 요청)", c.n_loads + 1, len(want - c.tickers_loaded), start, end)
        bars = self.repo.get_price_bars(sorted(want), start, end)
        c.bars, c.bars_range = bars, (start, end)
        c.tickers_loaded = set(want)  # 자료가 없는 종목도 "요청함" 으로 기억한다 (예전에는 빠져서 매번 전체 재적재)
        c.first_date = {t: _d(d) for t, d in bars.groupby("ticker")["date"].min().items()} if len(bars) else {}
        c.n_loads += 1
        fx = self.repo.get_fx_range(start - dt.timedelta(days=14), end)
        if not fx:
            raise DataMissing("환율(USDKRW) 자료가 없음", details={"start": str(start), "end": str(end)})
        c.fx = pd.Series({pd.Timestamp(r.date): float(r.rate) for r in fx}).sort_index()
        c.fx_range = (start, end)

    def _ensure(self, tickers: Iterable[str], start: dt.date, end: dt.date) -> None:
        c = self._c
        want = {normalize_ticker(t) for t in tickers}
        if c.bars is not None and c.bars_range is not None and c.bars_range[0] <= start and end <= c.bars_range[1] and want <= c.tickers_loaded:
            return  # 빠른 길: 잠금 없이 (적재 뒤에는 캐시가 바뀌지 않는다)
        with self._lock:
            if c.bars is None or c.bars_range is None:
                self._prefetch(want, start, end)
                return
            lo, hi = c.bars_range
            if start < lo or end > hi or not want <= c.tickers_loaded:
                self._prefetch(want, min(start, lo), max(end, hi))

    def bars(self, tickers: Sequence[str], start: dt.date, end: dt.date) -> pd.DataFrame:
        self._ensure(tickers, start, end)
        b = self._c.bars
        assert b is not None
        want = [normalize_ticker(t) for t in tickers]
        m = b["ticker"].isin(want) & (b["date"] >= pd.Timestamp(start)) & (b["date"] <= pd.Timestamp(end))
        return b.loc[m]

    def fx_series(self, start: dt.date, end: dt.date) -> pd.Series:
        """[start, end] 일별 환율 (KRW per USD). 비어 있는 날은 직전값."""
        self._ensure([], start, end)
        fx = self._c.fx
        assert fx is not None
        idx = pd.date_range(pd.Timestamp(start), pd.Timestamp(end), freq="D")
        s = fx.reindex(fx.index.union(idx)).sort_index().ffill().reindex(idx)
        first = fx.index.min()
        if s[s.index >= first].isna().any():
            raise DataMissing(f"환율이 없는 날이 있음: {s[(s.index >= first) & s.isna()].index[0].date()}")
        # 자료 시작 전 구간(요청 창이 DB 범위보다 앞설 때)은 첫 환율로 채운다. 그 구간의 가격 자료도 없으므로 결과에 영향 없음.
        return s.bfill()

    def view(self, as_of: dt.date) -> MarketDataView:
        if as_of > self.ceiling:
            raise LookaheadError(f"기준일 {as_of} 이 자료 상한 {self.ceiling} 을 넘음")
        return MarketDataView(self, as_of)


class MarketDataView:
    """기준일(as_of)로 자른 조회. 모든 메서드는 end > as_of 면 LookaheadError."""

    def __init__(self, md: MarketData, as_of: dt.date) -> None:
        self.md = md
        self.s = md.s
        self.as_of = as_of

    # ───────────────────────── 보호 ─────────────────────────
    def _check(self, end: dt.date, *, strict: bool = False) -> dt.date:
        limit = self.as_of - dt.timedelta(days=1) if strict else self.as_of
        if end > limit:
            raise LookaheadError(
                f"{end} 자료 요청: 기준일 {self.as_of} {'이전' if strict else '이하'}만 허용",
                details={"as_of": str(self.as_of), "requested_end": str(end), "strict": strict},
            )
        return end

    def _end(self, end: dt.date | None, strict_before: bool | None) -> dt.date:
        strict = self.s.portfolio.estimation_strict_before if strict_before is None else strict_before
        if end is None:
            end = self.as_of - dt.timedelta(days=1) if strict else self.as_of
        return self._check(end, strict=strict)

    def _markets(self, tickers: Iterable[str]) -> list[str]:
        ms = {self.md.market_of(t) for t in tickers} or set(self.s.market.markets)
        return sorted(ms)

    # ───────────────────────── 달력 ─────────────────────────
    def trading_days(
        self, start: dt.date, end: dt.date | None = None, *, markets: Iterable[str] | None = None, bench: str | None = None
    ) -> pd.DatetimeIndex:
        """거래일 합집합 (요청 시장들의 비교지수 날짜). bench 를 주면 그 종목의 날짜."""
        end = self._check(end or self.as_of)
        tickers = [bench] if bench else self.md.benchmarks(markets or self.s.market.markets)
        b = self.md.bars(tickers, start, end)
        return pd.DatetimeIndex(sorted(b["date"].unique()), name="date")

    # ───────────────────────── 가격 ─────────────────────────
    def adj_close(
        self,
        tickers: Sequence[str],
        start: dt.date,
        end: dt.date | None = None,
        *,
        strict_before: bool | None = None,
        usd: bool = True,
        fill: bool = True,
    ) -> pd.DataFrame:
        """date × ticker 수정종가. 기본은 추정용(as_of 이전까지). usd=True 면 한국 종목을 거래일 환율로 환산.

        행 = 종목 시장들의 거래일 합집합, 휴장일은 직전값(fill=True). 첫 자료 이전은 NaN.
        """
        end = self._end(end, strict_before)
        tickers = [normalize_ticker(t) for t in tickers]
        load_start = start - dt.timedelta(days=HOLIDAY_LOOKBACK_DAYS) if fill else start
        b = self.md.bars(tickers, load_start, end)
        wide = b.pivot(index="date", columns="ticker", values="adj_close") if len(b) else pd.DataFrame()
        cal = self.trading_days(load_start, end, markets=self._markets(tickers))
        wide = wide.reindex(index=cal, columns=tickers).astype("float64")
        if usd:
            wide = self._to_usd(wide, load_start, end)
        if fill:
            wide = wide.ffill()
            wide = wide.loc[wide.index >= pd.Timestamp(start)]
        wide.index.name = "date"
        wide.columns.name = None
        return wide

    def _to_usd(self, wide: pd.DataFrame, start: dt.date, end: dt.date) -> pd.DataFrame:
        kr = [t for t in wide.columns if self.md.currency_of(t) == "KRW"]
        if not kr or wide.empty:
            return wide
        fx = self.md.fx_series(start, end).reindex(wide.index).ffill()
        out = wide.copy()
        out[kr] = wide[kr].div(fx.to_numpy()[:, None])
        return out

    def close_volume(self, tickers: Sequence[str], start: dt.date, end: dt.date | None = None, *, strict_before: bool | None = None) -> pd.DataFrame:
        """long: ticker, date, close, volume, currency, close_usd, dollar_volume_usd (거래대금·시총 필터용)."""
        end = self._end(end, strict_before)
        b = self.md.bars(tickers, start, end).copy()
        if b.empty:
            return b.assign(close_usd=pd.Series(dtype=float), dollar_volume_usd=pd.Series(dtype=float))
        fx = self.md.fx_series(start, end)
        rate = b["date"].map(fx).to_numpy()
        is_krw = (b["currency"] == "KRW").to_numpy()
        b["close_usd"] = np.where(is_krw, b["close"] / rate, b["close"])
        b["dollar_volume_usd"] = b["close_usd"] * b["volume"]
        return b

    def first_dates(self, tickers: Sequence[str]) -> dict[str, dt.date]:
        """종목별 캐시 안 첫 가격 날짜 (≤ as_of)."""
        want = [normalize_ticker(t) for t in tickers]
        self.md._ensure(want, self.md._c.bars_range[0] if self.md._c.bars_range else self.as_of, self.as_of)
        fd = self.md._c.first_date
        return {t: fd[t] for t in want if t in fd and fd[t] <= self.as_of}

    def panel(
        self,
        tickers: Sequence[str],
        start: dt.date,
        end: dt.date | None = None,
        *,
        required: Iterable[str] = (),
        benchmarks: Iterable[str] = (),
    ) -> tuple[pd.DataFrame, DataQualityReport]:
        """체결용 가격 패널 (as_of 종가까지) + 품질 판정. 결측 없는 USD 수정종가 (사용 가능 종목만)."""
        end = self._check(end or self.as_of)
        all_t = list(dict.fromkeys([*tickers, *benchmarks]))
        load_start = start - dt.timedelta(days=HOLIDAY_LOOKBACK_DAYS)
        raw = self.adj_close(all_t, load_start, end, strict_before=False, usd=True, fill=False)
        raw = self._carry_market_holidays(raw, load_start, end)
        raw = raw.loc[raw.index >= pd.Timestamp(start)]
        report, clean = assess(raw, [*required, *benchmarks], raw.index, self.s.market)
        return clean, report

    def _carry_market_holidays(self, wide: pd.DataFrame, start: dt.date, end: dt.date) -> pd.DataFrame:
        """합집합 달력에서 그 종목 시장의 휴장일인 행은 결측이 아니라 '직전 종가 유지'(K16). 그 행만 채워
        품질 판정이 진짜 결측(자기 시장 거래일에 값이 없는 날)만 보게 한다."""
        if wide.empty:
            return wide
        out = wide.copy()
        for m in self._markets(list(wide.columns)):
            cols = [t for t in wide.columns if self.md.market_of(t) == m]
            if not cols:
                continue
            cal = self.trading_days(start, end, markets=[m])
            holiday = ~out.index.isin(cal)
            if holiday.any():
                filled = out[cols].ffill()
                out.loc[holiday, cols] = filled.loc[holiday, cols]
        return out

    # ───────────────────────── 환율 ─────────────────────────
    def fx_on_or_before(self, d: dt.date | None = None) -> FxRate:
        d = self._check(d or self.as_of)
        r = self.md.repo.get_fx_on_or_before(d)
        if r is None:
            raise DataMissing(f"{d} 이전 환율이 없음")
        return r

    def fx_series(self, start: dt.date, end: dt.date | None = None) -> pd.Series:
        return self.md.fx_series(start, self._check(end or self.as_of))

    # ───────────────────────── 가치평가 ─────────────────────────
    def valuation(self, tickers: Sequence[str], *, strict_before: bool | None = None) -> pd.DataFrame:
        """종목별 기준일 가치평가 (index=ticker): per, pbr, roe_ttm, dividend_yield, market_cap_usd, shares_outstanding, date.

        valuation_daily 는 그날 종가·그날까지 공시된 재무만 쓰므로, 추정용(strict)에는 as_of−1 행을 쓴다.
        """
        d = self._end(None, strict_before)
        tickers = [normalize_ticker(t) for t in tickers]
        key = (d, frozenset(tickers))
        if key in self.md._c.valuation:
            return self.md._c.valuation[key]
        ids = {self.md.asset_id(t): t for t in tickers}
        rows = self.md.repo.get_valuation_asof(list(ids), d, max_staleness_days=self.s.market.valuation_max_staleness_days)
        fx = self.fx_on_or_before(d).rate
        recs = []
        for aid, r in rows.items():
            t = ids[aid]
            krw = (r.get("currency") or self.md.currency_of(t)) == "KRW"
            mcap = r.get("market_cap")
            recs.append(
                {
                    "ticker": t,
                    "asset_id": aid,
                    "date": r["date"],
                    "currency": r.get("currency"),
                    "per": r.get("per"),
                    "pbr": r.get("pbr"),
                    "roe_ttm": r.get("roe_ttm"),
                    "dividend_yield": r.get("dividend_yield"),
                    "eps_ttm": r.get("eps_ttm"),
                    "shares_outstanding": r.get("shares_outstanding"),
                    "market_cap_usd": (mcap / fx if krw else mcap) if mcap is not None else None,
                    "fin_disclosed_at": r.get("fin_disclosed_at"),
                }
            )
        cols = ["ticker", "asset_id", "date", "currency", "per", "pbr", "roe_ttm", "dividend_yield", "eps_ttm",
                "shares_outstanding", "market_cap_usd", "fin_disclosed_at"]  # fmt: skip
        df = pd.DataFrame(recs, columns=cols).set_index("ticker").reindex(tickers)
        self.md._c.valuation[key] = df
        return df

    def shares_outstanding(self, tickers: Sequence[str]) -> dict[str, float]:
        v = self.valuation(tickers)["shares_outstanding"]
        return {t: float(x) for t, x in v.items() if pd.notna(x)}

    def market_cap_usd(self, tickers: Sequence[str]) -> dict[str, float]:
        v = self.valuation(tickers)["market_cap_usd"]
        return {t: float(x) for t, x in v.items() if pd.notna(x)}

    # ───────────────────────── 뉴스 ─────────────────────────
    def news_window(
        self, tickers: Sequence[str], *, days: int | None = None, per_ticker: int | None = None, languages: Sequence[str] | None = None,
        dc_days: int | None = None, dc_event_types: Sequence[str] | None = None,
    ) -> EvidenceWindow:  # fmt: skip
        """구성일 직전 근거 창: 뉴스 [as_of − days, as_of) + 공시 [as_of − dc_days, as_of) (M2-04). dc_days=0 이면 공시 없음."""
        n = self.s.news
        ds = getattr(self.s, "disclosures", None)
        days = days or n.window_days
        langs = tuple(languages or n.languages)
        dcd = dc_days if dc_days is not None else ((ds.window_days if ds and ds.enabled else 0))
        types = tuple(dc_event_types) if dc_event_types is not None else (tuple(ds.event_types) if ds else ())
        key = (self.as_of, days, frozenset(normalize_ticker(t) for t in tickers), langs, dcd, types)
        if key not in self.md._c.news:
            self.md._c.news[key] = build_window(
                self.md, [normalize_ticker(t) for t in tickers], self.as_of, days=days,
                per_ticker=per_ticker or n.per_ticker, languages=langs, min_tickers=n.min_tickers,
                dc_days=dcd, dc_per_ticker=(ds.per_ticker if ds else 8), dc_event_types=list(types) or None,
                count_disclosures=(ds.count_toward_min_tickers if ds else True), include_amendments=(ds.include_amendments if ds else False),
            )  # fmt: skip
        return self.md._c.news[key]

    # ───────────────────────── 구성종목 ─────────────────────────
    def constituents(self, universe: str) -> tuple[dt.date | None, list[str], list[str]]:
        """유니버스(SP500·NASDAQ100·KOSPI200)의 기준일 구성종목 (yfinance 표기) + 경고."""
        snap, rows, warns = self.md.repo.constituents_at(UNIVERSE_INDEX[universe], self.as_of)
        return snap, [r.ticker for r in rows], warns
