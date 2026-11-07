"""실행 전 점검 (라운드 5 → 2026-11 시나리오 QA): 요청한 종목 수를 실제로 채울 수 있는지, 백테스트 시작일에도 채울 수 있는지,
섹터 상한 때문에 현금이 남는지를 대화 단계에서 미리 센다. 결과는 '후보 부족' · '창 축소 예상' · '섹터 상한' 질문의 재료가 된다.

실행과 같은 길로 센다 (예전에는 테마 판정 전·후보 상한 전 숫자라 실제보다 4~6배 컸다, F22):
03 후보 검색(같은 상한) → 04 테마 분류(대화 LLM, 프롬프트가 같아 실행의 04 가 캐시를 재사용) → 05 정량 선정(자격선 포함)
→ 07 시작일 재선정(기준일 테마 통과 ∩ 그날 후보, `spec.selectable_at`) · 시작일 이동 규칙(`spec.next_shift_day`).
LLM 이 없으면(llm=None) 04 를 건너뛰고 상한(upper bound)으로 센다 (basis='before_classification').
"""

from __future__ import annotations

import datetime as dt
from typing import Any

import pandas as pd

from backend.analysis.common.jsonio import canonical_json, sha256_hex
from backend.analysis.m2_data import descriptor as D
from backend.analysis.m2_data.market_data import MarketData
from backend.analysis.m3_selection.classify import classify, is_broad_theme
from backend.analysis.m3_selection.retrieve import retrieve
from backend.analysis.m3_selection.screen import screen
from backend.analysis.m4_portfolio.spec import MAX_START_SHIFTS, dropped_by, next_shift_day, selectable_at, shift_window_ok, theme_passed
from backend.analysis.schemas.selection import Tagging
from backend.analysis.settings import AnalysisSettings
from backend.pipeline.descriptor import Descriptor


def signature(normalized: dict[str, Any], intent: dict[str, Any], *, reselect: bool = True, classified: bool = True) -> str:
    d = normalized["derived"]
    c = normalized["constraints"]
    # v3: 최소 시가총액 자료가 없으면 제외(정책 결정 7) — 예전 규칙으로 센 점검 결과를 다시 쓰지 않게. v4: 시작일에 빠지는 사유(dropped_by). v5: start_impossible
    src = {"v": 5, "as_of": str(d["as_of"]), "bt_start": str(d["backtest_start"]), "metric": (intent.get("screen") or {}).get("metric"),
           "themes": [{k: t.get(k) for k in ("gics_codes", "keywords", "example_tickers", "label_ko", "description_ko")} for t in (intent.get("interpretation") or {}).get("themes", [])],
           "rules": intent.get("exclude_theme_rules"), "reselect": reselect, "classified": classified,
           "cons": {k: c.get(k) for k in ("universe", "num_holdings", "exclude_tickers", "exclude_sectors", "exclude_themes", "must_include_tickers",
                                          "min_market_cap_usd", "min_avg_daily_volume_usd", "asset_types", "max_weight_per_stock",
                                          "max_weight_per_sector", "min_cash_ratio")}}  # fmt: skip
    return sha256_hex(canonical_json(src), 16)


def _summary(day: Any, cand: Any, tag: Any, sel: Any, invest: float) -> dict[str, Any]:
    sm = sel.summary
    return {"date": str(day), "n_matched": int(cand.stats.get("n_matched", 0)), "n_candidates": len(cand.candidates),
            "n_passed": len(tag.passed_tickers) if tag is not None else None, "n_selected": len(sel.selected),
            "n_with_metric": len(sel.selected),  # 예전 키 (대화가 쓰는 숫자 = 실제로 고를 종목 수)
            "tickers": [s.ticker for s in sel.selected], "capacity": sm.get("weight_capacity"), "invest": round(invest, 4),
            "sector_counts": sm.get("sector_counts") or {}, "cap_needed": (sel.infeasibility or {}).get("cap_needed_for_target"),
            "by_filter": dict(cand.stats.get("by_filter") or {}), "metric": sm.get("metric")}  # fmt: skip


def precheck(normalized: dict[str, Any], intent: dict[str, Any], desc: Descriptor, md: MarketData, settings: AnalysisSettings,
             *, previous: dict[str, Any] | None = None, llm: Any = None, reselect: bool = True) -> dict[str, Any]:  # fmt: skip
    """기준일·백테스트 시작일에 실제로 고를 수 있는 종목과 배분 가능 비율. 입력 서명이 같으면 previous 를 그대로 돌려준다.

    reselect=False: 시작일 재선정을 끈 요청(_backtest_request.reselect_at_start=false) — 시작일 부족을 묻지 않는다 (F24).
    """
    sig = signature(normalized, intent, reselect=reselect, classified=llm is not None)
    if previous and previous.get("signature") == sig:
        return previous
    d = normalized["derived"]
    rid = normalized["request_id"]
    cons = normalized["constraints"]
    as_of = dt.date.fromisoformat(str(d["as_of"]))
    bt_start = dt.date.fromisoformat(str(d["backtest_start"]))
    nh = cons["num_holdings"]
    nh_min = int(nh["min"])
    invest = 1.0 - float(cons.get("min_cash_ratio", 0) or 0)
    ss = settings.selection
    md.prefetch(D.tickers(desc), bt_start - dt.timedelta(days=int(settings.portfolio.lookback_days * 1.6) + 60), as_of)  # 01 단계와 같은 선적재
    view = md.view(as_of)
    cand = retrieve(view, desc, intent, cons, request_id=rid, max_candidates=ss.max_candidates, broad_min_sectors=ss.broad_theme_min_sectors,
                    metric_prefilter=ss.metric_prefilter)  # fmt: skip  (03 단계와 같은 인자 → 04 배치가 같아 캐시 재사용)
    if llm is not None and cand.candidates:
        tag = classify(cand, intent, llm, broad=is_broad_theme(intent["interpretation"]["themes"], ss.broad_theme_min_sectors))
        basis = "after_classification"
    else:
        tag = Tagging(request_id=rid, min_confidence=0.0, tagged=[], excluded_by_theme=[], passed_tickers=[c.ticker for c in cand.candidates], batches=0)
        basis = "before_classification"
    sel, _facts = screen(view, desc, tag, intent, cons, request_id=rid)
    now = _summary(as_of, cand, tag, sel, invest)
    out: dict[str, Any] = {"signature": sig, "computed_at": str(pd.Timestamp.now().date()), "basis": basis, "min": nh_min, "target": int(nh["target"]),
                           "as_of": now, "start": None, "feasible_start": None, "short_now": now["n_selected"] < nh_min, "short_at_start": False,
                           "capacity_short": (now["capacity"] is not None and now["capacity"] < invest - 0.005)}  # fmt: skip
    if not reselect:
        return out
    markets = sorted({md.market_of(t) for t in now["tickers"]} or set(d.get("markets") or settings.market.markets))
    cal = view.trading_days(bt_start, as_of, markets=markets)
    if len(cal) < 2:
        return out
    day0 = cal[0].date()
    passed = list(tag.passed_tickers)
    bx = {"broad": not getattr(tag, "theme_filter_applied", True), "excluded": [r.ticker for r in tag.excluded_by_theme],
          "theme_ok": theme_passed(tag)}  # 07 과 같은 규칙 (넓은 테마는 그날 후보 전체, 배당 테마는 기준일 판정으로 배당 확인)
    c0, t0, s0, _f0 = selectable_at(md, day0, desc, intent, cons, passed, rid, **bx)
    out["start"] = {**_summary(day0, c0, t0, s0, invest), "dropped_by": dropped_by(now["tickers"], c0, s0)}
    n_start = len(s0.selected)
    out["short_at_start"] = n_start < nh_min
    first2: dict[str, Any] | None = None  # 1종목 이하일 때 07 이 자동으로 옮겨 갈 날 (2종목 이상이 되는 첫 날)
    if n_start < nh_min and now["n_selected"] >= nh_min:  # 07 과 같은 이동 규칙으로 최소 종목 수를 채우는 첫 날
        total_days, day = max(1, (as_of - day0).days), day0
        for _ in range(MAX_START_SHIFTS):
            nxt = next_shift_day(cal, day)
            if nxt is None or not shift_window_ok(as_of, nxt, total_days):
                break
            day = nxt
            _c, _t, s1, _f = selectable_at(md, day, desc, intent, cons, passed, rid, **bx)
            if first2 is None and len(s1.selected) >= 2:
                first2 = {"date": str(day), "n_selected": len(s1.selected)}
            if len(s1.selected) >= nh_min:
                years = int((as_of - day).days / 365.25 * 10) / 10  # 내림: 반올림하면 새 시작일이 이 날보다 앞서 다시 부족할 수 있다
                # 내림한 기간이 실제로 만드는 시작일(derive 와 같은 식)에서 다시 센다 (040: '2024-03-04 로 옮겨 2.5년' 인데 2.5년을 고르면 2024-04-09 부터였다)
                start2 = as_of - dt.timedelta(days=int(round(years * 365.25)))
                later = [d.date() for d in cal if d.date() >= start2]
                if later and later[0] != day:
                    _c2, _t2, s2, _f2 = selectable_at(md, later[0], desc, intent, cons, passed, rid, **bx)
                    if len(s2.selected) >= nh_min:
                        day, s1 = later[0], s2
                out["feasible_start"] = {"date": str(day), "n_with_metric": len(s1.selected), "n_selected": len(s1.selected), "years": years}
                break
    # 시작일 종목이 1개 이하인데 창 안에서 2종목 이상이 되는 날도 없으면 07 이 멈춘다 → 대화가 미리 대안을 묻는다 (054: 질문 없이 실행해 07 에서 실패)
    out["start_impossible"] = n_start <= 1 and first2 is None and out["feasible_start"] is None and now["n_selected"] >= nh_min
    return out
