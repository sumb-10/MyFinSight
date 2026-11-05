"""M3-04 정량 스크린·선정기 (코드). 테마 통과 종목에 템플릿 지표(상세설계 표 6)를 계산해 순위를 매기고 섹터 분산을 고려해 고른다.

- 지표가 없는 일반 후보는 제외(must_include 는 유지 + 사유). 지표마다 인용 ID(fin:*) 를 남긴다.
- 섹터당 선호 종목 수 = floor(섹터 상한 × n ÷ 투자 가능 비율) 로 우선 선발, 부족하면 미룬 후보로 채움 (비중 상한은 Module4 가 지킴).
- 전액 배분 용량 Σ min(k × 종목 상한, 섹터 상한) < 1 − 현금 비율이면 infeasibility 사유와 선택지를 반환한다.
"""

from __future__ import annotations

import math
from collections import Counter
from typing import Any

from backend.analysis.common.capacity import cap_cause_ko, cap_limits
from backend.analysis.common.labels import sector_ko
from backend.analysis.common.warnings import metric_value_ko
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
    lo, hi = M.ELIGIBLE_RANGE.get(metric, (None, None))
    for t in tickers:
        if t in values.index and math.isfinite(float(values[t])):
            v = float(values[t])
            if not M.eligible(metric, v):  # 자격선 밖: 후보가 모자라도 채우지 않는다 (예: 저PER 에 PER 734, 퀄리티에 ROE 음수)
                reason = f"metric_out_of_range({metric}={v:.4g}, 범위 {'' if lo is None else '>' + format(lo, 'g')}{'' if hi is None else ' ≤' + format(hi, 'g')})"
                if t.upper() in forced:
                    warnings.append(f"must_include {t}: {reason}, kept")
                    pool.append((t, v))
                else:
                    rejected.append(Rejected(ticker=t, reason=reason, metric_value=v))
                continue
            pool.append((t, v))
        else:
            reason = "metric_missing" + (" (eps<=0 or no financials)" if metric == "pe_ttm" else "")
            if t.upper() in forced:
                warnings.append(f"must_include {t}: {reason}, kept with metric=nan")
                pool.append((t, float("nan")))
            else:
                rejected.append(Rejected(ticker=t, reason=reason))

    n_pass = len(pool)
    n = nh["target"] if n_pass >= nh["target"] else max(nh["min"], n_pass)
    # '후보 조건·테마 판정을 통과하고 지표가 있는 종목' 수에는 필수 포함을 넣지 않는다: 그 검사를 건너뛰고(지표 없음·자격선 밖도 유지) 들어온다.
    # 018: 시작일 3개 중 2개가 필수 포함(105560.KS 배당 자료 없음, 033780.KS 시가총액 미달)인데 '자료가 있는 종목이 3개' 라고 했다 → 따로 센다
    n_forced = sum(1 for t, _ in pool if t.upper() in forced)
    fx = f" (+{n_forced} must_include)" if n_forced else ""
    out_of_range = [r for r in rejected if r.reason.startswith("metric_out_of_range")]
    if n_pass < nh["target"] and out_of_range:
        # 예시는 앞 5개 (나머지는 공지가 '외 N개'), 작은 값은 부호가 보이게 (019: AMD ROE −0.045% 가 '-0.0%')
        ex = ", ".join(f"{r.ticker} {metric_value_ko(metric, r.metric_value)}" for r in out_of_range[:5])
        warnings.append(f"only {n_pass - n_forced} tickers within eligibility for {metric}{fx}; target {nh['target']} (excluded {len(out_of_range)} out of range: {ex})")
    elif n_pass < nh["target"]:
        warnings.append(f"only {n_pass - n_forced} tickers have {metric}{fx}; target {nh['target']} -> selecting {min(n, n_pass)}")
    if n_pass < nh["min"]:
        warnings.append(f"below num_holdings.min={nh['min']} -> fewer holdings than requested (cash may remain; the report labels this)")
    max_stock, max_sector = cons["max_weight_per_stock"], cons["max_weight_per_sector"]
    investable = 1.0 - cons.get("min_cash_ratio", 0)
    # 섹터당 선호 종목 수 = 동일비중(투자 가능 비율 ÷ n)으로 섹터 상한 안에 드는 종목 수. 016: 최소 현금 15%·섹터 상한 85% 면 20종목 × 4.25% = 85% 로
    # 다 들어가는데 floor(0.85 × 20) = 17 로 세어 3종목을 '초과' 로 표시하고, 리포트가 '섹터 상한이 비중을 누른 부분' 을 거짓으로 띄웠다
    sector_pref = max(1, math.floor(max_sector * n / (investable if investable > 1e-9 else 1.0) + 1e-9))

    def capacity(counts: Counter) -> float:
        return sum(min(k * max_stock, max_sector) for k in counts.values())

    def sector_of(t: str) -> tuple[str, str]:
        e = desc.by_ticker(t) or {}
        g = D.gics_model(e) if e else None
        return (g.sector.code, g.sector.name) if g else ("", "")

    def is_forced(t: str) -> bool:
        return t.upper() in forced

    pool.sort(key=lambda x: (not is_forced(x[0]), (x[1] if direction == "asc" else -x[1]) if math.isfinite(x[1]) else float("inf")))
    # 섹터 선호는 섹터 상한 때문에 현금이 남지 않게 하려는 것 — 순위대로 고른 상위 n 개로도 상한 안에서 다 배분되면 쓰지 않는다
    # (043: 리츠 21 + 유틸리티 9 로 45% + 45% = 90% 를 다 담을 수 있었는데 섹터당 15개로 잘라 변동성 큰 ES·NRG·CEG 가 저변동성 요청에 들어왔다)
    if capacity(Counter(sector_of(t)[0] for t, _ in pool[:n])) >= investable - 1e-9:
        sector_pref = max(sector_pref, n)
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
    skipped_pref: list[str] = []
    pure = {t for t, _ in pool[:n]}  # 섹터 선호 없이 순위대로만 뽑았다면 들어갔을 종목
    for t, v in deferred:
        if len(selected) >= n:
            # 순위대로라면 뽑혔는데 섹터 선호 때문에 빠진 경우만 sector_preference (008: 어차피 순위 밖인 TER·LRCX·INTC 까지 '자리를 내줬다' 고 했다)
            displaced = t in pure
            rejected.append(Rejected(ticker=t, reason="sector_preference" if displaced else "rank_beyond_n", metric_value=v if math.isfinite(v) else None))
            if displaced:
                skipped_pref.append(t)
            continue
        overflow.append(t)
        add(t, v)
    if skipped_pref:
        by_sec: dict[str, list[str]] = {}
        for t in skipped_pref:
            by_sec.setdefault(sector_of(t)[1] or "?", []).append(t)
        sec_txt = "; ".join(f"{k}: {len(v)}" for k, v in by_sec.items())
        subs = [x.ticker for x in selected if x.ticker not in pure]  # 대신 들어간 순위가 더 낮은 다른 섹터 종목
        warnings.append(f"sector count preference ({sector_pref}/sector, sector cap {max_sector:.0%}) skipped higher-ranked {skipped_pref} ({sec_txt}) "
                        f"for lower-ranked names in other sectors {subs}")  # fmt: skip

    cap_now = capacity(sec_count)
    # 자격선 부족 경고에 배분 가능 비율을 붙인다 → 공지가 '남는 비중은 현금' 을 사실일 때만 말한다 (002: 9종목이 100% 를 다 담는데도 현금이 남는다고 했다)
    warnings[:] = [w + f" [capacity {cap_now:.2f} of {investable:.2f}]" if w.startswith("only ") and " within eligibility for " in w else w for w in warnings]
    infeasibility = None
    sector_overflow = None
    sec_names = {s.sector_code: s.sector for s in selected}
    if cap_now < investable - 1e-9:
        # 100% 는 늘 시도한다 (34%·66% 같은 상한이면 range 가 100 을 건너뛰었고, int(0.29*100)=28 처럼 내림도 있었다)
        needed = next((round(c / 100, 2) for c in [*range(int(round(max_sector * 100)), 100, 5), 100]
                       if sum(min(k * max_stock, c / 100) for k in sec_count.values()) >= investable - 1e-9), None)  # fmt: skip
        lim = cap_limits(dict(sec_count), max_stock, max_sector, investable)
        cause = cap_cause_ko(lim, max_stock, max_sector) or f"종목·섹터 상한으로 투자금의 {cap_now:.0%}까지만 담깁니다"
        infeasibility = {
            "reason": "weight_capacity", "target": nh["target"], "n_selected": len(selected), "capacity": round(cap_now, 4),
            "required": investable, "sector_cap": max_sector, "stock_cap": max_stock,
            "sector_counts": {sec_names.get(c, c): k for c, k in sec_count.items()}, "cap_needed_for_target": needed,
            # 원인 문장은 묶는 상한대로 (011: max_feasible_n=선정 수 를 넘겨 '종목당 상한 아래에서 배분 가능한 최대 종목 수는 2개' 라는 거꾸로 된 서술이 나왔다.
            # 첫 수정은 needed 로 갈라 섹터 상한이 묶을 때도 '2개뿐이라 50%까지' 라고 썼다 → common/capacity 로 R9·현금 설명과 같은 판단)
            "cause_ko": f"{as_of} 선정 종목은 {cause}" + (" (상한이 종목 수를 줄인 것이 아닙니다)" if lim["kind"] in ("stock", "both") else ""),
            # 섹터 상한을 100% 로 올려도 모자라면(종목 수 × 종목당 상한이 묶임) 그 보기는 빼고 이유를 따로 적는다 (예전에는 '섹터 상한 완화로도 해결 불가' 가 보기로 나왔다)
            "options_ko": ([f"섹터 상한을 {needed:.0%}로 올리기", "종목당 상한을 올리기", "테마를 넓혀 다른 섹터 후보를 늘리기"] if needed
                           else ["종목당 상한을 올리기", "테마를 넓혀 종목 수를 늘리기"]),
            "note_ko": None if needed else f"종목이 {len(selected)}개라 종목당 상한 {max_stock:.0%}로는 섹터 상한을 올려도 다 배분할 수 없습니다",
        }  # fmt: skip
        warnings.append(f"weight capacity {cap_now:.2f} < {investable:.2f}: caps cannot absorb the capital with these sectors (cap needed {needed}; "
                        f"stock {max_stock:.0%}, sector {max_sector:.0%}, {len(selected)} names)")  # fmt: skip
    if overflow:
        top_sec = Counter(sector_of(t)[1] for t in overflow).most_common(1)[0][0]
        k = sum(1 for s_ in selected if s_.sector == top_sec)
        sector_overflow = {"count_preference": sector_pref, "tickers": overflow, "sector": top_sec, "n_in_sector": k,
                           "note_ko": f"{sector_ko(top_sec)} 종목이 {k}개로 섹터 상한 {max_sector:.0%}를 나눠 갖습니다(동일비중 기준 약 {max_sector / k:.1%}씩). "
                                      "상위 순위 종목을 빼지 않기 위해 종목 수 대신 비중으로 상한을 지킵니다."}  # fmt: skip
        warnings.append(f"sector name preference ({sector_pref}/sector) exceeded for {len(overflow)} tickers {overflow}; sector cap is enforced by weights")
    if len(selected) < n:
        warnings.append(f"selected {len(selected)} < n={n}: not enough passed tickers")

    sel = Selection(
        request_id=request_id, as_of=as_of, selected=selected, rejected=rejected, infeasibility=infeasibility,
        summary={"as_of": str(as_of), "metric": metric, "direction": direction, "n_candidates": len(tagging.tagged), "n_tagged": len(tickers),
                 "n_with_metric": n_pass, "n_forced": n_forced, "n_target": nh["target"], "n_selected": len(selected), "sector_cap": sector_pref,  # n_with_metric 은 필수 포함 포함
                 "weight_capacity": round(cap_now, 4), "sector_overflow": sector_overflow,
                 "sector_counts": {sec_names.get(c, c): k for c, k in sec_count.items()},
                 "market_counts": dict(Counter(s.market for s in selected))},
        warnings=warnings,
    )  # fmt: skip
    return sel, [f.to_dict() for f in facts if f.ticker in {s.ticker for s in selected}]
