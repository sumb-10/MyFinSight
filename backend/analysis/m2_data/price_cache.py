"""가격 원자료 캐시 (2026-11 속도 개선). 한 프로세스(일꾼·API 서버) 안에서 실행·대화끼리 price_daily 행을 나눠 쓴다.

미국 유니버스(약 520종목 × 6.5년, 83만 행)를 DB 에서 받는 데만 55초가 걸렸다. 일꾼은 실행마다 처음부터 다시 받았고, 서버는 범위·종목이
조금만 늘어도 그동안 받은 전체(최대 720종목 × 8년)를 다시 받았다(서버 로그의 'price reload'). 여기서는 종목별로 받아 둔 날짜 범위를
기억하고 모자란 앞·뒤 구간만 DB 에서 받는다.

- 돌려주는 표는 DB 를 바로 부른 것과 같다(같은 행·같은 순서·같은 형식). 수정 계수 보정 등은 MarketData 가 요청 범위로 그대로 한다.
- 최근 `recent_days` 일은 캐시하지 않고 늘 DB 에서 받는다 (늦게 들어오는 그날 가격·며칠 안의 수정).
- 다른 저장소(repo)가 오거나, `max_age_s` 가 지나거나, 행이 `max_rows` 를 넘으면 비운다 (오래된 과거 수정도 결국 반영).
"""

from __future__ import annotations

import datetime as dt
import threading
import time
from collections.abc import Sequence
from typing import Any

import pandas as pd

from backend.db.analysis_readers import PRICE_BAR_COLS
from backend.pipeline.normalizer import normalize_ticker

_DAY = dt.timedelta(days=1)


class PriceBarCache:
    def __init__(self, *, recent_days: int = 14, max_age_s: float = 6 * 3600, max_rows: int = 5_000_000) -> None:
        self.recent_days, self.max_age_s, self.max_rows = recent_days, max_age_s, max_rows
        self._lock = threading.Lock()
        self._repo: Any = None
        self._clear()

    def _clear(self) -> None:
        self._rows: dict[str, pd.DataFrame] = {}  # 종목 → 날짜순 행 (행이 없으면 키 없음)
        self._range: dict[str, tuple[dt.date, dt.date]] = {}  # 종목 → DB 에서 받아 둔 [시작, 끝] (행이 없어도 기억 → 다시 묻지 않음)
        self._n = 0
        self._born = time.monotonic()
        self.db_calls = 0  # 시험·로그용

    def wrap(self, repo: Any) -> CachedPriceRepo:
        return CachedPriceRepo(repo, self)

    def get_price_bars(self, repo: Any, tickers: Sequence[str], start: dt.date, end: dt.date, *, today: dt.date | None = None) -> pd.DataFrame:
        want = sorted({normalize_ticker(t) for t in tickers})
        boundary = (today or dt.date.today()) - dt.timedelta(days=self.recent_days)  # 이 날 이후는 늘 DB 에서
        stable_end = min(end, boundary)
        parts: list[pd.DataFrame] = []
        with self._lock:
            if repo is not self._repo or time.monotonic() - self._born > self.max_age_s or self._n > self.max_rows:
                self._repo = repo
                self._clear()
            if want and start <= stable_end:
                need: dict[tuple[dt.date, dt.date], list[str]] = {}
                for t in want:
                    r = self._range.get(t)
                    segs = [(start, stable_end)] if r is None else [(start, r[0] - _DAY), (r[1] + _DAY, stable_end)]
                    for a, b in segs:
                        if a <= b:
                            need.setdefault((a, b), []).append(t)
                for (a, b), ts in sorted(need.items()):
                    self.db_calls += 1
                    self._add(ts, a, b, repo.get_price_bars(ts, a, b))
                lo, hi = pd.Timestamp(start), pd.Timestamp(stable_end)
                for t in want:
                    df = self._rows.get(t)
                    if df is not None:
                        parts.append(df.loc[(df["date"] >= lo) & (df["date"] <= hi)])
        if want and end > boundary:
            self.db_calls += 1
            parts.append(repo.get_price_bars(want, max(start, boundary + _DAY), end))
        parts = [p for p in parts if len(p)]
        if not parts:
            return pd.DataFrame([], columns=list(PRICE_BAR_COLS))
        return pd.concat(parts, ignore_index=True).sort_values(["ticker", "date"]).reset_index(drop=True)  # 읽기 함수와 같은 순서

    def _add(self, tickers: list[str], a: dt.date, b: dt.date, df: pd.DataFrame) -> None:
        got = dict(tuple(df.groupby("ticker", sort=False))) if len(df) else {}
        for t in tickers:
            new, old = got.get(t), self._rows.get(t)
            if new is not None and len(new):
                self._rows[t] = new if old is None else pd.concat([old, new], ignore_index=True).sort_values("date").reset_index(drop=True)
            lo, hi = self._range.get(t, (a, b))
            self._range[t] = (min(lo, a), max(hi, b))  # 앞·뒤 구간을 붙여 받으므로 범위는 늘 이어져 있다
        self._n = sum(len(x) for x in self._rows.values())


class CachedPriceRepo:
    """저장소를 감싸 가격 조회(get_price_bars)만 캐시를 거친다. 나머지 조회는 그대로 저장소로."""

    def __init__(self, repo: Any, cache: PriceBarCache) -> None:
        self._repo, self._cache = repo, cache

    def get_price_bars(self, tickers: Sequence[str], start: dt.date, end: dt.date) -> pd.DataFrame:
        return self._cache.get_price_bars(self._repo, tickers, start, end)

    def __getattr__(self, name: str) -> Any:
        return getattr(self._repo, name)
