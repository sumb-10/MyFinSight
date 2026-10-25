"""M3-04 정량 스크린·선정기 (코드). 테마 통과 종목에 템플릿 지표(상세설계 표 6)를 계산해 순위를 매기고 섹터 분산을 고려해 고른다.

- 지표가 없는 일반 후보는 제외(must_include 는 유지 + 사유). 지표마다 인용 ID(fin:*) 를 남긴다.
- 섹터당 선호 종목 수 = floor(섹터 상한 × n) 로 우선 선발, 부족하면 미룬 후보로 채움 (비중 상한은 Module4 가 지킴).
- 전액 배분 용량 Σ min(k × 종목 상한, 섹터 상한) < 1 − 현금 비율이면 infeasibility 사유와 선택지를 반환한다.
"""

from __future__ import annotations

import math
from collections import Counter
from typing import Any

from backend.analysis.m2_data import descriptor as D
from backend.analysis.m2_data import metrics as M
from backend.analysis.m2_data.market_data import MarketDataView
from backend.analysis.schemas.intent import IntentSpec
from backend.analysis.schemas.selection import Rejected, Selected, Selection, Tagging
from backend.pipeline.descriptor import Descriptor


def screen(
    view: MarketDataView,
    desc: Descriptor,
    tagging: Tagging,
    intent: IntentSpec | dict[str, Any],
    constraints: dict[str, Any],
    *,
    request_id: str,
) -> tuple[Selection, list[dict[str, Any]]]:
    """(Selection, facts). facts = 지표 인용 레코드 (evidence_index 에 들어감)."""
    it = intent.model_dump(mode="json") if isinstance(intent, IntentSpec) else intent
    cons = constraints
    scr = it["screen"]
    as_of = view.as_of
    metric, direction = scr["metric"], scr["direction"]
    nh = cons["num_holdings"]
    forced = {str(x).upper() for x in cons.get("must_include_tickers", [])}
    conf = {r.ticker: r.confidence for r in tagging.tagged}
    tickers = list(tagging.passed_tickers)
    warnings: list[str] = []
    rejected: list[Rejected] = []

    values, facts = M.METRICS[metric](view, tickers) if tickers else (M.pd.Series(dtype=float), [])
    fact_by_ticker = {f.ticker: f for f in facts}
    pool: list[tuple[str, float]] = []
    for t in tickers:
        if t in values.index and math.isfinite(float(values[t])):
            pool.append((t, float(values[t])))
        else:
            reason = "metric_missing" + (" (eps<=0 or no financials)" if metric == "pe_ttm" else "")
            if t.upper() in forced:
                warnings.append(f"must_include {t}: {reason}, kept with metric=nan")
                pool.append((t, float("nan")))
            else:
                rejected.append(Rejected(ticker=t, reason=reason))

    n_pass = len(pool)
    n = nh["target"] if n_pass >= nh["target"] else max(nh["min"], n_pass)
    if n_pass < nh["target"]:
        warnings.append(f"only {n_pass} tickers have {metric}; target {nh['target']} -> selecting {min(n, n_pass)}")
    if n_pass < nh["min"]:
        warnings.append(f"below num_holdings.min={nh['min']} -> fewer holdings than requested (cash may remain; the report labels this)")
    max_stock, max_sector = cons["max_weight_per_stock"], cons["max_weight_per_sector"]
    investable = 1.0 - cons.get("min_cash_ratio", 0)
    sector_pref = max(1, math.floor(max_sector * n))

    def capacity(counts: Counter) -> float:
        return sum(min(k * max_stock, max_sector) for k in counts.values())

    def sector_of(t: str) -> tuple[str, str]:
        e = desc.by_ticker(t) or {}
        g = D.gics_model(e) if e else None
        return (g.sector.code, g.sector.name) if g else ("", "")

    def is_forced(t: str) -> bool:
        return t.upper() in forced

    pool.sort(key=lambda x: (not is_forced(x[0]), (x[1] if direction == "asc" else -x[1]) if math.isfinite(x[1]) else float("inf")))
    selected: list[Selected] = []
    sec_count: Counter = Counter()
    deferred: list[tuple[str, float]] = []
    overflow: list[str] = []

    def add(t: str, v: float) -> None:
        sc, sn = sector_of(t)
        e = desc.by_ticker(t) or {}
        sec_count[sc] += 1
        f = fact_by_ticker.get(t)
        selected.append(Selected(
            ticker=t, name=e.get("name", t), sector=sn, sector_code=sc, market=e.get("market", "US"), rank=len(selected) + 1,
            metric_name=metric, metric_value=v if math.isfinite(v) else float("nan"), metric_fact_id=f.id if f else None,
            theme_confidence=conf.get(t), forced=is_forced(t),
        ))  # fmt: skip

    for t, v in pool:
        sc, _ = sector_of(t)
        if len(selected) >= n:
            rejected.append(Rejected(ticker=t, reason="rank_beyond_n", metric_value=v if math.isfinite(v) else None))
            continue
        if sec_count[sc] >= sector_pref and not is_forced(t):
            deferred.append((t, v))
            continue
        add(t, v)
    for t, v in deferred:
        if len(selected) >= n:
            rejected.append(Rejected(ticker=t, reason="rank_beyond_n", metric_value=v if math.isfinite(v) else None))
            continue
        overflow.append(t)
        add(t, v)

    cap_now = capacity(sec_count)
    infeasibility = None
    sector_overflow = None
    sec_names = {s.sector_code: s.sector for s in selected}
    if cap_now < investable - 1e-9:
        needed = next((round(c / 100, 2) for c in range(int(max_sector * 100), 101, 5)
                       if sum(min(k * max_stock, c / 100) for k in sec_count.values()) >= investable), None)  # fmt: skip
        infeasibility = {
            "reason": "weight_capacity", "target": nh["target"], "n_selected": len(selected), "capacity": round(cap_now, 4),
            "required": investable, "sector_cap": max_sector, "stock_cap": max_stock,
            "sector_counts": {sec_names.get(c, c): k for c, k in sec_count.items()}, "cap_needed_for_target": needed,
            "max_feasible_n": len(selected),
            "options_ko": [f"섹터 상한을 {needed:.0%} 로 올리기" if needed else "섹터 상한 완화로도 해결 불가", "종목당 상한을 올리기",
                           "테마를 넓혀 다른 섹터 후보를 늘리기"],
        }  # fmt: skip
        warnings.append(f"weight capacity {cap_now:.2f} < {investable:.2f}: caps cannot absorb the capital with these sectors (cap needed {needed})")
    if overflow:
        top_sec = Counter(sector_of(t)[1] for t in overflow).most_common(1)[0][0]
        k = sum(1 for s_ in selected if s_.sector == top_sec)
        sector_overflow = {"count_preference": sector_pref, "tickers": overflow, "sector": top_sec, "n_in_sector": k,
                           "note_ko": f"{top_sec} 종목이 {k}개로 섹터 상한 {max_sector:.0%}를 나눠 갖습니다(동일비중 기준 약 {max_sector / k:.1%}씩). "
                                      "상위 순위 종목을 빼지 않기 위해 종목 수 대신 비중으로 상한을 지킵니다."}  # fmt: skip
        warnings.append(f"sector name preference ({sector_pref}/sector) exceeded for {len(overflow)} tickers {overflow}; sector cap is enforced by weights")
    if len(selected) < n:
        warnings.append(f"selected {len(selected)} < n={n}: not enough passed tickers")

    sel = Selection(
        request_id=request_id, as_of=as_of, selected=selected, rejected=rejected, infeasibility=infeasibility,
        summary={"as_of": str(as_of), "metric": metric, "direction": direction, "n_candidates": len(tagging.tagged), "n_tagged": len(tickers),
                 "n_with_metric": n_pass, "n_target": nh["target"], "n_selected": len(selected), "sector_cap": sector_pref,
                 "weight_capacity": round(cap_now, 4), "sector_overflow": sector_overflow,
                 "sector_counts": {sec_names.get(c, c): k for c, k in sec_count.items()},
                 "market_counts": dict(Counter(s.market for s in selected))},
        warnings=warnings,
    )  # fmt: skip
    return sel, [f.to_dict() for f in facts if f.ticker in {s.ticker for s in selected}]
