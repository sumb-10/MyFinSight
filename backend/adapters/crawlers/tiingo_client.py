"""[정량·해외 보정] Tiingo 일봉 (https://api.tiingo.com/tiingo/daily/{ticker}/prices).

- close  : 분할만 반영한 종가 (yfinance Close와 같은 기준). Tiingo 원본 close는 무보정이므로
           splitFactor 누적곱으로 직접 분할 보정한다.
- adj_close : Tiingo adjClose (분할 + 배당 반영)
"""

import csv
import io
import json
import zipfile
from datetime import date, timedelta

from backend.adapters.crawlers import config
from backend.adapters.crawlers.common import http_session

SOURCE = "TIINGO"
BASE = "https://api.tiingo.com/tiingo/daily"
SUPPORTED_URL = "https://apimedia.tiingo.com/docs/tiingo/daily/supported_tickers.zip"
_session = http_session()


def _symbol(ticker: str) -> str:
    return ticker.replace(".", "-").lower()  # BRK.B → brk-b


def fetch_prices(ticker: str, start, end) -> list[dict]:
    config.require(TIINGO_API_KEY=config.TIINGO_API_KEY)
    res = _session.get(
        f"{BASE}/{_symbol(ticker)}/prices",
        timeout=30,
        headers={
            "Authorization": f"Token {config.TIINGO_API_KEY}",
            "Content-Type": "application/json",
        },
        params={
            "startDate": start.isoformat(),
            "endDate": end.isoformat(),
            "resampleFreq": "daily",
        },
    )
    if res.status_code == 404:
        raise RuntimeError(f"Tiingo에 {ticker} 티커가 없음")
    if not res.ok:
        raise RuntimeError(f"Tiingo 오류 status={res.status_code} body={res.text[:200]}")
    return res.json()


def split_adjusted(rows: list[dict]) -> list[dict]:
    """무보정 close를 이후 분할 누적곱으로 나눠 분할 보정 종가로 변환."""
    rows = sorted(rows, key=lambda r: r["date"])
    factor, out = 1.0, []
    for r in reversed(rows):
        adj = {
            k: (r.get(k) / factor if r.get(k) is not None else None)
            for k in ("open", "high", "low", "close")
        }
        out.append(
            {
                **r,
                **{f"split_{k}": v for k, v in adj.items()},
                "split_volume": int(r["volume"] * factor) if r.get("volume") is not None else None,
            }
        )
        sf = r.get("splitFactor") or 1.0
        if sf and sf != 1.0:  # 이 날 분할이 있었으면 그 이전 날짜들은 factor만큼 나눠야 함
            factor *= sf
    return list(reversed(out))


def price_rows(ticker: str, start, end) -> list[dict]:
    """명세 payload 행 목록. 원본 collect() 의 행 만들기 부분 (DB 저장은 뺐다)."""
    return [
        {
            "date": r["date"][:10],
            "open": r["split_open"],
            "high": r["split_high"],
            "low": r["split_low"],
            "close": r["split_close"],
            "adj_close": r.get("adjClose"),
            "volume": r["split_volume"],
            "currency": "USD",
        }
        for r in split_adjusted(fetch_prices(ticker, start, end))
        if r.get("close") is not None
    ]


def _types_cache():
    return config.CACHE_DIR / "tiingo_asset_types.json"


def supported_types() -> dict[str, str]:
    """Tiingo 공식 지원 종목표 {티커(Tiingo 표기): assetType(Stock·ETF·Mutual Fund)}.
    키 없이 받는 공개 파일, 7일 캐시. 같은 티커가 여럿이면 endDate 가 가장 늦은 줄."""
    cache = _types_cache()
    if cache.exists():
        data = json.loads(cache.read_text(encoding="utf-8"))
        if date.fromisoformat(data["saved"]) > date.today() - timedelta(days=7):
            return data["types"]
    res = _session.get(SUPPORTED_URL, timeout=(5, 60))
    res.raise_for_status()
    with zipfile.ZipFile(io.BytesIO(res.content)) as z:
        text = z.read(z.namelist()[0]).decode("utf-8")
    types, last = {}, {}
    for row in csv.DictReader(io.StringIO(text)):
        t, end = (row.get("ticker") or "").lower(), row.get("endDate") or ""
        if t and end >= last.get(t, ""):
            types[t], last[t] = row.get("assetType") or "", end
    cache.write_text(json.dumps({"saved": date.today().isoformat(), "types": types}), "utf-8")
    return types


def asset_type(ticker: str) -> str | None:
    return supported_types().get(_symbol(ticker))
