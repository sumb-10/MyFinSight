"""종목 찾기·이름 (투자조건 화면의 회사 이름 검색, 「회사명 (티커)」 표시). 프런트 제안 계약 searchStocks·getStocks 와 같은 모양.

원본: 지원 유니버스(S&P 500·NASDAQ-100·KOSPI 200)의 최신 구성종목 스냅샷 (이름·섹터). 분석이 고를 수 있는 종목만 찾는다.
이름: 한국 종목은 한국어. 미국 종목은 한국어 이름 자료가 없어 영어 이름을 그대로 쓴다 (name_ko 자리에도 영어, 화면 표시 이름).
name_en 은 영어 이름 (한국 종목은 자료가 없어 None).
"""

from __future__ import annotations

import datetime as dt
import re
from typing import Any

from backend.analysis.common.labels import sector_ko
from backend.analysis.m2_data.market_data import UNIVERSE_INDEX
from backend.analysis.schemas.request import UNIVERSE_MARKET
from backend.pipeline.normalizer import normalize_ticker

SEARCH_LIMIT_MAX = 20
LOOKUP_MAX = 100

_NOT_WORD = re.compile(r"[^0-9a-z가-힣]")


def _flat(s: str | None) -> str:
    """비교용: 소문자, 글자·숫자만 (공백·쉼표·점·하이픈 무시: 'brk.b' = 'BRK-B', 'micron tech' = 'Micron Technology, Inc.')."""
    return _NOT_WORD.sub("", (s or "").lower())


def _code(ticker: str) -> str:
    """한국 종목의 6자리 코드 (005930.KS → 005930). 미국 종목은 티커 그대로."""
    return ticker.split(".")[0] if ticker.endswith((".KS", ".KQ")) else ticker


def load_stocks(repo: Any, as_of: dt.date) -> list[dict[str, Any]]:
    """유니버스 구성종목을 합쳐 티커 하나에 한 줄 (S&P 500 과 NASDAQ-100 에 함께 있으면 한 번만). 이름순."""
    out: dict[str, dict[str, Any]] = {}
    for universe, index in UNIVERSE_INDEX.items():
        _snap, rows, _warns = repo.constituents_at(index, as_of)
        market = UNIVERSE_MARKET[universe]
        for r in rows:
            t = normalize_ticker(r.ticker)
            if t in out:
                continue
            name = " ".join((r.name or "").split()) or t
            out[t] = {"ticker": t, "name_ko": name, "name_en": None if market == "KR" else name, "market": market, "sector_ko": sector_ko(r.sector)}
    return sorted(out.values(), key=lambda s: (s["name_ko"], s["ticker"]))


def _rank(s: dict[str, Any], k: str) -> int | None:
    """0 = 티커(한국은 6자리 코드도) 앞부분, 1 = 회사 이름 앞부분, 2 = 어디든 포함, None = 안 맞음."""
    tick, code = _flat(s["ticker"]), _flat(_code(s["ticker"]))
    names = [_flat(s["name_ko"]), _flat(s["name_en"])]
    if tick.startswith(k) or code.startswith(k):
        return 0
    if any(n and n.startswith(k) for n in names):
        return 1
    if k in tick or any(n and k in n for n in names):
        return 2
    return None


def _order(r: int, s: dict[str, Any], k: str) -> tuple[Any, ...]:
    """같은 순위 안: 티커로 맞으면 티커가 똑같은 것 → 짧은 티커, 이름으로 맞으면 짧은 이름. 마지막은 이름순."""
    if r == 0:
        exact = k in (_flat(s["ticker"]), _flat(_code(s["ticker"])))
        return (r, not exact, len(s["ticker"]), s["name_ko"])
    return (r, False, len(s["name_ko"]), s["name_ko"])


def search(stocks: list[dict[str, Any]], q: str, limit: int = 8) -> list[dict[str, Any]]:
    """회사 이름(한국 종목 한국어, 미국 종목 영어)·티커로 찾기. 티커 앞부분 → 이름 앞부분 → 포함 순 (같은 순위 안은 _order)."""
    k = _flat(q)
    if not k:
        return []
    hits = [(r, s) for s in stocks if (r := _rank(s, k)) is not None]
    hits.sort(key=lambda x: _order(x[0], x[1], k))
    return [s for _r, s in hits[: max(1, min(limit, SEARCH_LIMIT_MAX))]]


def lookup(stocks: list[dict[str, Any]], tickers: list[str]) -> list[dict[str, Any]]:
    """티커 → 종목. 응답의 ticker 는 요청한 표기 그대로 (화면이 그 표기로 찾는다). BRK.B·brk-b, 005930·005930.KS 도 찾는다.
    목록(유니버스)에 없는 티커는 빠진다."""
    by_ticker = {s["ticker"]: s for s in stocks}
    by_code = {_code(s["ticker"]): s for s in stocks if s["market"] == "KR"}
    out = []
    for t in dict.fromkeys(x.strip() for x in tickers if x and x.strip()):
        key = normalize_ticker(t)
        s = by_ticker.get(key) or by_code.get(key)
        if s:
            out.append({**s, "ticker": t})
    return out
