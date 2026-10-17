"""[정량·환율] FRED (미국 연준 세인트루이스) DEXKOUS: 원/달러 환율 (뉴욕 정오 매입률, 1981년~, 키 불필요).

https://fred.stlouisfed.org/graph/fredgraph.csv?id=DEXKOUS → observation_date,DEXKOUS (값이 없는 날은 ".")
미국 공휴일에는 값이 없다. yfinance(KRW=X, 2003-12~)와 출처별로 따로 저장해 비교하고, yfinance 가
없는 날(2000~2003-11 등)을 채운다 (fx_daily_source → fx_daily).
"""

from __future__ import annotations

import csv
import io
from datetime import UTC, date, datetime

from backend.adapters.crawlers.common import http_session
from backend.schemas.market import FxRate

SOURCE = "FRED"
URL = "https://fred.stlouisfed.org/graph/fredgraph.csv"
SERIES = {"USDKRW": "DEXKOUS"}
_session = http_session()


def parse(text: str, pair: str, at: datetime) -> list[FxRate]:
    out = []
    reader = csv.reader(io.StringIO(text))
    next(reader, None)  # observation_date,DEXKOUS
    for row in reader:
        if len(row) < 2 or row[1].strip() in ("", "."):
            continue
        out.append(
            FxRate(
                pair=pair,
                date=date.fromisoformat(row[0]),
                rate=float(row[1]),
                source=SOURCE,
                fetched_at=at,
            )  # fmt: skip
        )
    return out


def fetch_fx(start: date, end: date, pair: str = "USDKRW") -> list[FxRate]:
    """[start, end] 의 환율 (값이 있는 날만)."""
    params = {"id": SERIES[pair], "cosd": start.isoformat(), "coed": end.isoformat()}
    res = _session.get(URL, params=params, timeout=60)
    if not res.ok:
        raise RuntimeError(f"FRED 오류 status={res.status_code}")
    return parse(res.text, pair, datetime.now(UTC))
