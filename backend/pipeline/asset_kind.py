"""종목 종류(assets.asset_type: STOCK·ETF·INDEX)와 이름 판단. 공식 API 먼저, yfinance 는 보완.

- 한국 (.KS·.KQ): DART 상장사 코드표에 있으면 STOCK → KIS 상품 기본정보 → yfinance
- 미국: ^ 로 시작하면 INDEX → Tiingo 공식 지원 종목표 → yfinance
- 한 곳이 실패하거나 모르면 다음 곳으로. 다 모르면 (None, None) (가격 저장은 기본 STOCK 그대로)
"""

from __future__ import annotations

import logging
from collections.abc import Callable

from backend.pipeline.normalizer import is_kr_symbol

log = logging.getLogger(__name__)

Kind = tuple[str | None, str | None]

# KIS scty_grp_id_cd → asset_type. ETN·펀드류는 개별 주식이 아니므로 ETF 로 묶음
_KIS_KINDS = {
    "ST": "STOCK", "RT": "STOCK", "DR": "STOCK", "FS": "STOCK",
    "EF": "ETF", "EN": "ETF", "FE": "ETF", "MF": "ETF", "IF": "ETF", "BC": "ETF",
}  # fmt: skip
_TIINGO_KINDS = {"stock": "STOCK", "etf": "ETF", "mutual fund": "ETF"}


def _dart(symbol: str) -> Kind:
    from backend.adapters.crawlers import dart_client

    hit = dart_client.find_by_stock_code(symbol.split(".")[0])
    return ("STOCK", hit["corp_name"] or None) if hit else (None, None)


def _kis(symbol: str) -> Kind:
    from backend.adapters.crawlers import kis_client

    out = kis_client.stock_info(symbol.split(".")[0])
    name = (out.get("prdt_abrv_name") or out.get("prdt_name") or "").strip()
    return _KIS_KINDS.get(str(out.get("scty_grp_id_cd") or "").upper()), name or None


def _tiingo(symbol: str) -> Kind:
    from backend.adapters.crawlers import tiingo_client

    return _TIINGO_KINDS.get((tiingo_client.asset_type(symbol) or "").lower()), None


def _yahoo(symbol: str) -> Kind:
    from backend.adapters.crawlers import yfinance_client

    return yfinance_client.asset_kind(symbol)


KR_STEPS: list[tuple[str, Callable[[str], Kind]]] = [
    ("DART", _dart), ("KIS", _kis), ("YFINANCE", _yahoo),
]  # fmt: skip
US_STEPS: list[tuple[str, Callable[[str], Kind]]] = [("TIINGO", _tiingo), ("YFINANCE", _yahoo)]


def classify(symbol: str) -> Kind:
    """(asset_type, 이름). 종류를 정한 곳이 이름을 못 주면 뒤 단계 이름으로 채움."""
    if symbol.startswith("^"):
        return "INDEX", None
    kind = name = None
    for source, step in KR_STEPS if is_kr_symbol(symbol) else US_STEPS:
        try:
            k, n = step(symbol)
        except Exception as e:  # noqa: BLE001 - 한 곳 실패는 다음 곳으로
            log.info("%s 종류 조회 실패 (%s): %s", symbol, source, e)
            continue
        name = name or n
        if kind is None and k:
            kind = k
            log.info("%s 종류 %s (%s)", symbol, k, source)
        if kind and name:
            break
    return kind, name
