"""홈 '요즘엔 뭐가 좋아요?' 상자: 최근 한 달 성과가 좋았던 GICS 섹터와 투자성향별 추천 섹터 (2026-11-11).

판별 규칙 (사용자 결정, docs/update_hojin_11.11.md):
- 대상: 분석 유니버스 종목 전체. 미국 = S&P 500 + NASDAQ-100, 한국 = KOSPI 200. 섹터는 종목 사전의 GICS 섹터(11개).
- 기간: 기준일(두 시장이 모두 거래를 마친 마지막 날 = MarketData.ceiling)과 그 한 달 전 같은 날의 수정종가.
  그날이 휴장이면 그 전 거래일. 거래일은 시장마다 비교지수(SPY·KODEX 200) 날짜로 맞추고, 각 시장 통화 그대로 잰다.
- 섹터 수익률 = 섹터 안 종목 한 달 수익률의 단순 평균 (종목마다 같은 비중).
- 좋았던 섹터 = 종목 5개 이상 · 평균 > 0 · 평균 > 그 시장 전체 종목 평균 · 오른 종목 절반 이상. 평균 순으로 최대 3개.
- 성향별 추천 (상자에 보이는 좋았던 섹터 중에서): 안정형·안정추구형 = 최근 3개월(63거래일) 변동성이 가장 작은 섹터,
  위험중립형 = 한 달 수익률 ÷ 변동성이 가장 큰 섹터, 적극투자형·공격투자형 = 한 달 수익률 1위.
  변동성 = 섹터 단순 평균 지수의 일간 수익률 표준편차 × √252.
- 새 거래일 자료가 들어올 때마다 한 번 계산해 저장소(home/sector_trends.json)에 두고 쓴다. 계산 중에는 진행률(0~1)을 알려 준다.
"""

from __future__ import annotations

import datetime as dt
import logging
import math
import threading
import time
from collections.abc import Callable, Iterable
from typing import Any

import pandas as pd

from backend.analysis.errors import public_message
from backend.analysis.m2_data import descriptor as D
from backend.analysis.m2_data.market_data import repair_adj_spikes
from backend.pipeline.normalizer import normalize_ticker

log = logging.getLogger(__name__)

RULE_VERSION = "sector-trends-v1"
MIN_STOCKS = 5  # 이보다 종목이 적은 섹터는 한두 종목 때문에 1위가 될 수 있어 뺀다 (예: 한국 부동산 = 한진칼 1개)
MIN_UP_SHARE = 0.5  # 섹터 안 종목의 절반 이상이 올라야 한다
MAX_SHOWN = 3
VOL_DAYS = 63  # 변동성: 최근 약 3개월 거래일
MIN_VOL_DAYS = 20  # 일간 수익률이 이보다 적으면 변동성을 재지 않는다
LOOKBACK_DAYS = 130  # 가격을 받는 달력 일수 (한 달 + 63거래일 + 여유)
FFILL_LIMIT = 5  # 거래 정지 등으로 빈 날은 5거래일까지 직전 값
CHUNK = 80  # 진행률을 알리는 단위 (종목 수)
LEADERS = 3
UNIVERSES = ("SP500", "NASDAQ100", "KOSPI200")
MARKET_KO = {"US": "미국", "KR": "한국"}
BENCH_KO = {"SPY": "S&P 500", "069500.KS": "코스피 200"}
TENDENCIES = ("안정형", "안정추구형", "위험중립형", "적극투자형", "공격투자형")
RULE_OF = {"안정형": "low_vol", "안정추구형": "low_vol", "위험중립형": "ratio", "적극투자형": "top", "공격투자형": "top"}
SCOPES = ("US", "KR", "ALL")  # 내 투자 대상이 미국만 / 한국만 / 둘 다
STORE_REL = "home/sector_trends.json"

Progress = Callable[[float], None]


def one_month_before(d: dt.date) -> dt.date:
    """한 달 전 같은 날 (3월 31일 → 2월 28·29일처럼 없는 날은 그달 마지막 날)."""
    return (pd.Timestamp(d) - pd.DateOffset(months=1)).date()


def pct_text(x: float) -> str:
    return f"{x * 100:+.2f}%"  # 화면 표시 규칙과 같게 (수익률 소수 둘째 자리)


def prompt_for(market: str, sector_ko: str) -> str:
    return f"요즘 많이 오른 {MARKET_KO.get(market, market)} {sector_ko} 기업에 나눠 투자하고 싶어요."


def _r(x: float | None, nd: int = 6) -> float | None:
    return None if x is None or not math.isfinite(x) else round(float(x), nd)


def summarize_market(market: str, px: pd.DataFrame, bench: pd.Series | None, stocks: Iterable[dict[str, Any]], end: dt.date) -> dict[str, Any]:
    """한 시장의 섹터 성과.

    px: 날짜 × 종목 수정종가 (그 시장 종목, 그 시장 통화). bench: 비교지수 수정종가 (거래일 기준). stocks: {ticker, name, sector_code, sector_ko}.
    """
    rows = {s["ticker"]: s for s in stocks}
    px = px.sort_index()
    cal = bench.dropna().index if bench is not None and bench.notna().any() else px.index[px.notna().sum(axis=1) >= max(1, px.shape[1] // 2)]
    cal = cal[cal <= pd.Timestamp(end)]
    if len(cal) == 0:
        raise ValueError(f"{market}: {end} 이전 거래일 가격이 없습니다")
    end_day = cal[-1]
    base_cal = pd.Timestamp(one_month_before(end_day.date()))
    before = cal[cal <= base_cal]
    if len(before) == 0:
        raise ValueError(f"{market}: 한 달 전({base_cal.date()}) 가격이 없습니다")
    base_day = before[-1]
    wide = px.reindex(cal).ffill(limit=FFILL_LIMIT)
    ret = (wide.loc[end_day] / wide.loc[base_day] - 1).dropna()
    ret = ret[[t for t in ret.index if t in rows]]
    daily = wide.loc[:end_day].pct_change(fill_method=None).iloc[-VOL_DAYS:]
    mkt_avg = float(ret.mean()) if len(ret) else float("nan")

    sectors: list[dict[str, Any]] = []
    by_sector: dict[tuple[str, str], list[str]] = {}
    for t in ret.index:
        s = rows[t]
        by_sector.setdefault((s["sector_code"], s["sector_ko"]), []).append(t)
    for (code, name_ko), members in by_sector.items():
        r = ret[members]
        idx = daily[members].mean(axis=1, skipna=True).dropna()
        vol = float(idx.std(ddof=1) * math.sqrt(252)) if len(idx) >= MIN_VOL_DAYS else None
        avg, up = float(r.mean()), int((r > 0).sum())
        good = len(members) >= MIN_STOCKS and avg > 0 and avg > mkt_avg and up / len(members) >= MIN_UP_SHARE
        top = r.sort_values(ascending=False).head(LEADERS)
        sectors.append({
            "code": code, "name_ko": name_ko, "n": len(members), "up": up, "avg_return": _r(avg), "vol_3m": _r(vol), "good": good,
            "leaders": [{"ticker": t, "name": rows[t]["name"], "return": _r(float(x))} for t, x in top.items()],
            "prompt_ko": prompt_for(market, name_ko),
        })  # fmt: skip
    sectors.sort(key=lambda s: (-(s["avg_return"] or 0), s["code"]))
    b_ret = None
    if bench is not None and bench.notna().any():
        b = bench.reindex(cal).ffill()
        b_ret = _r(float(b.loc[end_day] / b.loc[base_day] - 1))
    return {
        "code": market, "label_ko": MARKET_KO.get(market, market), "base_date": str(base_day.date()), "end_date": str(end_day.date()),
        "n": int(len(ret)), "avg_return": _r(mkt_avg),
        "benchmark": None if bench is None else {"ticker": str(bench.name), "label_ko": BENCH_KO.get(str(bench.name), str(bench.name)), "return": b_ret},
        "sectors": sectors, "top": [s["code"] for s in sectors if s["good"]][:MAX_SHOWN],
    }  # fmt: skip


def pick_sector(tendency: str, markets: list[dict[str, Any]]) -> dict[str, Any]:
    """투자성향에 맞춘 섹터 하나 (상자에 보이는 좋았던 섹터 중에서) + 한 줄 설명."""
    rule = RULE_OF[tendency]
    cands = [(m, s) for m in markets for s in m["sectors"] if s["code"] in m["top"]]
    if rule in ("low_vol", "ratio"):
        cands = [c for c in cands if c[1]["vol_3m"]]
    best = None
    if cands:
        if rule == "low_vol":
            best = min(cands, key=lambda c: (c[1]["vol_3m"], -c[1]["avg_return"]))
        elif rule == "ratio":
            best = max(cands, key=lambda c: c[1]["avg_return"] / c[1]["vol_3m"])
        else:
            best = max(cands, key=lambda c: c[1]["avg_return"])
    if best is None:
        return {"tendency": tendency, "rule": rule, "market": None, "code": None, "name_ko": None, "avg_return": None,
                "text_ko": "최근 한 달은 시장 평균보다 많이 오른 섹터가 없습니다."}  # fmt: skip
    m, s = best
    head = f"{tendency}에 맞는 섹터는 {m['label_ko']} {s['name_ko']}입니다. 최근 한 달 {pct_text(s['avg_return'])} 올랐고, "
    tail = {"low_vol": "성과가 좋았던 섹터 중 최근 3개월 주가 오르내림이 가장 작았습니다.",
            "ratio": "주가 오르내림에 비해 오른 폭이 가장 컸습니다.",
            "top": "성과가 좋았던 섹터 중 가장 많이 올랐습니다."}[rule]  # fmt: skip
    return {"tendency": tendency, "rule": rule, "market": m["code"], "code": s["code"], "name_ko": s["name_ko"], "avg_return": s["avg_return"], "text_ko": head + tail}


def picks_for(markets: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    return {scope: {t: pick_sector(t, [m for m in markets if scope == "ALL" or m["code"] == scope]) for t in TENDENCIES} for scope in SCOPES}


def _wide(bars: pd.DataFrame) -> pd.DataFrame:
    if bars is None or bars.empty:
        return pd.DataFrame()
    w = bars.pivot_table(index="date", columns="ticker", values="adj_close", aggfunc="last")
    w.index = pd.DatetimeIndex(w.index)
    w.columns.name = None
    return w.astype("float64")


def compute_sector_trends(md: Any, settings: Any, *, progress: Progress | None = None, now: Callable[[], dt.datetime] | None = None) -> dict[str, Any]:
    """기준일 = md.ceiling. 가격은 md.repo(가격 캐시를 거치는 저장소)에서 종목 묶음별로 받아 진행률을 알린다."""
    tell = progress or (lambda _p: None)
    end: dt.date = md.ceiling
    ms = settings.market
    desc, _info, _w = D.load_for(end, UNIVERSES, ms.markets, processed_dir=ms.descriptor_dir or D.PROCESSED, universe_file=ms.descriptor_universe)
    tell(0.05)
    by_market: dict[str, list[dict[str, Any]]] = {m: [] for m in ms.markets}
    for s in desc.stocks:
        sec = (s.get("gics") or {}).get("sector") or {}
        if not sec.get("code"):
            continue
        t = normalize_ticker(s.get("yfinance_symbol") or s["ticker"])
        by_market.setdefault(s.get("market", "US"), []).append({"ticker": t, "name": s.get("name") or t, "sector_code": str(sec["code"]), "sector_ko": sec.get("name_ko") or sec.get("name_en") or str(sec["code"])})
    start = end - dt.timedelta(days=LOOKBACK_DAYS)
    jobs: list[tuple[str, list[str]]] = []
    for m, rows in by_market.items():
        ticks = [r["ticker"] for r in rows]
        jobs.append((m, [normalize_ticker(md.benchmark_of(m))]))
        jobs += [(m, ticks[i : i + CHUNK]) for i in range(0, len(ticks), CHUNK)]
    frames: dict[str, list[pd.DataFrame]] = {m: [] for m in by_market}
    for k, (m, chunk) in enumerate(jobs):
        bars, _fixed = repair_adj_spikes(md.repo.get_price_bars(chunk, start, end))
        frames[m].append(bars)
        tell(0.05 + 0.9 * (k + 1) / len(jobs))
    markets: list[dict[str, Any]] = []
    for m, rows in by_market.items():
        if not rows:
            continue
        wide = _wide(pd.concat(frames[m], ignore_index=True) if frames[m] else pd.DataFrame())
        bench_t = normalize_ticker(md.benchmark_of(m))
        bench = wide.pop(bench_t).rename(bench_t) if bench_t in wide.columns else None
        markets.append(summarize_market(m, wide, bench, rows, end))
    out = {
        "rule_version": RULE_VERSION, "as_of": str(end), "computed_at": (now or (lambda: dt.datetime.now().astimezone()))().isoformat(timespec="seconds"),
        "rule": {"min_stocks": MIN_STOCKS, "min_up_share": MIN_UP_SHARE, "max_shown": MAX_SHOWN, "vol_days": VOL_DAYS},
        "markets": markets, "picks": picks_for(markets),
    }  # fmt: skip
    tell(1.0)
    return out


class SectorTrendsJob:
    """저장해 둔 결과가 기준일(최신 거래일)과 같으면 그대로, 아니면 뒤에서 다시 계산한다 (그동안 진행률·지난 결과를 돌려준다).

    compute(progress) 는 결과 dict 를 돌려준다. 실패하면 retry_after_s 동안은 다시 시작하지 않는다 (화면이 0.4초마다 묻는다).
    최신 거래일은 저장해 둔 결과가 있을 때만, latest_ttl_s 에 한 번만 DB 에 묻는다 (계산 중 진행률 응답은 DB 를 건드리지 않는다).
    """

    def __init__(self, store: Any, compute: Callable[[Progress], dict[str, Any]], *, retry_after_s: float = 30.0, latest_ttl_s: float = 60.0,
                 clock: Callable[[], float] = time.monotonic) -> None:  # fmt: skip
        self.store, self._compute, self.retry_after_s, self.latest_ttl_s, self._clock = store, compute, retry_after_s, latest_ttl_s, clock
        self._lock = threading.Lock()
        self._thread: threading.Thread | None = None
        self._progress = 0.0
        self._error: str | None = None
        self._failed_at: float | None = None
        self._latest: tuple[float, dt.date | None] | None = None  # (물어본 때, 최신 거래일)

    def cached(self) -> dict[str, Any] | None:
        doc = self.store.read(STORE_REL)
        return doc if isinstance(doc, dict) and doc.get("rule_version") == RULE_VERSION else None

    def _latest_day(self, latest: dt.date | Callable[[], dt.date | None] | None) -> dt.date | None:
        if not callable(latest):
            return latest
        now = self._clock()
        if self._latest is None or now - self._latest[0] >= self.latest_ttl_s:
            try:
                day = latest()
            except Exception:  # noqa: BLE001 — DB 에 닿지 못하면 저장해 둔 결과를 그대로 쓴다
                log.warning("[home] 최신 거래일을 확인하지 못함", exc_info=True)
                day = None
            self._latest = (now, day)
        return self._latest[1]

    def status(self, latest: dt.date | Callable[[], dt.date | None] | None) -> dict[str, Any]:
        """latest = 지금 DB 의 최신 거래일 또는 그것을 묻는 함수 (모르면 None → 저장해 둔 결과를 그대로 쓴다)."""
        doc = self.cached()
        if doc is not None and not self.running():
            day = self._latest_day(latest)
            if day is None or str(doc.get("as_of")) >= str(day):  # 계산한 뒤에 물어본 날짜가 더 이르면 그대로 최신
                return {"status": "ready", "progress": 1.0, "data": doc, "error": None}
        with self._lock:
            running = self.running()
            if not running and (self._failed_at is None or self._clock() - self._failed_at >= self.retry_after_s):
                self._start()
                running = True
            if running:
                return {"status": "loading", "progress": round(self._progress, 3), "data": doc, "error": None}
            return {"status": "error", "progress": round(self._progress, 3), "data": doc, "error": self._error}

    def running(self) -> bool:
        return self._thread is not None and self._thread.is_alive()

    def _start(self) -> None:
        self._progress, self._error, self._failed_at = 0.0, None, None
        self._thread = threading.Thread(target=self._run, name="sector-trends", daemon=True)
        self._thread.start()

    def _set_progress(self, p: float) -> None:
        self._progress = max(self._progress, min(1.0, float(p)))

    def _run(self) -> None:
        try:
            doc = self._compute(self._set_progress)
            self.store.write(STORE_REL, doc)
            self._progress = 1.0
        except Exception as e:  # noqa: BLE001 — 화면에는 이유만, 서버 로그에 전체
            log.exception("[home] 섹터 성과 계산 실패")
            self._error = f"섹터 성과를 계산하지 못했습니다: {public_message(e)}"[:300]
            self._failed_at = self._clock()

    def wait(self, timeout: float = 30.0) -> None:
        """테스트용: 돌고 있는 계산이 끝날 때까지 기다린다."""
        t = self._thread
        if t is not None:
            t.join(timeout)
