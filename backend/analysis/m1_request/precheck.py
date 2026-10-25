"""실행 전 점검 (라운드 5, LLM 없음): 테마 후보가 요청한 종목 수를 채울 수 있는지, 백테스트 시작일에도 채울 수 있는지를
대화 단계에서 미리 센다. 결과는 '후보 부족' · '창 축소 예상' 질문의 재료가 된다 (dialog._feasibility_proposals).

03 후보 검색(`retrieve`, GICS·키워드 매칭 + 가격 필터)과 05 의 지표 계산(`metrics.METRICS`)만 쓰므로 LLM 분류(04)는 반영하지 않는다.
→ 여기서 세는 수는 상한(upper bound)이다: 여기서도 부족하면 실행에서는 더 부족하다.
"""

from __future__ import annotations

import datetime as dt
import math
from typing import Any

import pandas as pd

from backend.analysis.common.jsonio import canonical_json, sha256_hex
from backend.analysis.m2_data import descriptor as D
from backend.analysis.m2_data import metrics as M
from backend.analysis.m2_data.market_data import MarketData
from backend.analysis.m3_selection.retrieve import retrieve
from backend.analysis.settings import AnalysisSettings
from backend.pipeline.descriptor import Descriptor

MAX_FEASIBLE_TRIES = 24  # 시작일을 약 한 달씩 최대 2년 뒤까지 옮겨 본다 (spec.py 의 07 단계와 같은 규칙)
MIN_REMAINING_DAYS = 365


def signature(normalized: dict[str, Any], intent: dict[str, Any]) -> str:
    d = normalized["derived"]
    c = normalized["constraints"]
    src = {"as_of": str(d["as_of"]), "bt_start": str(d["backtest_start"]), "metric": (intent.get("screen") or {}).get("metric"),
           "themes": [{k: t.get(k) for k in ("gics_codes", "keywords", "example_tickers")} for t in (intent.get("interpretation") or {}).get("themes", [])],
           "rules": intent.get("exclude_theme_rules"),
           "cons": {k: c.get(k) for k in ("universe", "num_holdings", "exclude_tickers", "exclude_sectors", "exclude_themes", "must_include_tickers",
                                          "min_market_cap_usd", "min_avg_daily_volume_usd", "asset_types")}}  # fmt: skip
    return sha256_hex(canonical_json(src), 16)


def _count_at(day: dt.date, normalized: dict[str, Any], intent: dict[str, Any], desc: Descriptor, md: MarketData) -> dict[str, Any]:
    view = md.view(day)
    cons = normalized["constraints"]
    c = retrieve(view, desc, intent, cons, request_id=normalized["request_id"], max_candidates=None)
    tickers = [x.ticker for x in c.candidates]
    metric = intent["screen"]["metric"]
    if tickers:
        vals, _facts = M.METRICS[metric](view, tickers)
        n_metric = int(sum(1 for t in tickers if t in vals.index and math.isfinite(float(vals[t]))))
    else:
        n_metric = 0
    return {"date": str(day), "n_matched": int(c.stats.get("n_matched", 0)), "n_candidates": len(tickers), "n_with_metric": n_metric,
            "by_filter": dict(c.stats.get("by_filter") or {}), "metric": metric}  # fmt: skip


def precheck(normalized: dict[str, Any], intent: dict[str, Any], desc: Descriptor, md: MarketData, settings: AnalysisSettings,
             *, previous: dict[str, Any] | None = None) -> dict[str, Any]:  # fmt: skip
    """기준일·백테스트 시작일의 후보 수와 선정 지표 보유 수. 입력 서명이 같으면 previous 를 그대로 돌려준다."""
    sig = signature(normalized, intent)
    if previous and previous.get("signature") == sig:
        return previous
    d = normalized["derived"]
    as_of = dt.date.fromisoformat(str(d["as_of"]))
    bt_start = dt.date.fromisoformat(str(d["backtest_start"]))
    nh = normalized["constraints"]["num_holdings"]
    start = bt_start - dt.timedelta(days=int(settings.portfolio.lookback_days * 1.6) + 60)
    md.prefetch(D.tickers(desc), start, as_of)  # 01 단계와 같은 선적재 (가격 이력 필터가 캐시 범위를 본다)
    now = _count_at(as_of, normalized, intent, desc, md)
    at_start = _count_at(bt_start, normalized, intent, desc, md)
    feasible = None
    if at_start["n_with_metric"] < int(nh["min"]) and now["n_with_metric"] >= int(nh["min"]):
        day = bt_start
        for _ in range(MAX_FEASIBLE_TRIES):
            day = day + dt.timedelta(days=30)
            if (as_of - day).days < MIN_REMAINING_DAYS:
                break
            cnt = _count_at(day, normalized, intent, desc, md)
            if cnt["n_with_metric"] >= int(nh["min"]):
                feasible = {**cnt, "years": round((as_of - day).days / 365.25, 1)}
                break
    return {"signature": sig, "computed_at": str(pd.Timestamp.now().date()), "min": int(nh["min"]), "target": int(nh["target"]),
            "as_of": now, "start": at_start, "feasible_start": feasible,
            "short_now": now["n_with_metric"] < int(nh["min"]), "short_at_start": at_start["n_with_metric"] < int(nh["min"])}  # fmt: skip
