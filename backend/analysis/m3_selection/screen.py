"""M3-04 정량 스크린·선정기 (코드). 테마 통과 종목에 템플릿 지표(상세설계 표 6)를 계산해 순위를 매기고 섹터 분산을 고려해 고른다.

- 지표가 없는 일반 후보는 제외(must_include 는 유지 + 사유). 지표마다 인용 ID(fin:*) 를 남긴다.
- 섹터당 선호 종목 수 = floor(섹터 상한 × n ÷ 투자 가능 비율) 로 우선 선발, 부족하면 미룬 후보로 채움 (비중 상한은 Module4 가 지킴).
- 전액 배분 용량 Σ min(k × 종목 상한, 섹터 상한) < 1 − 현금 비율이면 infeasibility 사유와 선택지를 반환한다.
"""

from __future__ import annotations

import math
import re
from collections import Counter
from collections.abc import Iterable
from typing import Any

from backend.analysis.common.capacity import cap_cause_ko, cap_limits
from backend.analysis.common.labels import sector_ko
from backend.analysis.common.warnings import metric_value_ko
from backend.analysis.m2_data import descriptor as D
from backend.analysis.m2_data import metrics as M
from backend.analysis.m2_data.market_data import MarketDataView
from backend.analysis.m3_selection.retrieve import _share_class_key
from backend.analysis.schemas.intent import IntentSpec
from backend.analysis.schemas.selection import Rejected, Selected, Selection, Tagging
from backend.pipeline.descriptor import Descriptor
from backend.pipeline.normalizer import normalize_ticker


def screen(
    view: MarketDataView,
    desc: Descriptor,
    tagging: Tagging,
    intent: IntentSpec | dict[str, Any],
    constraints: dict[str, Any],
    *,
    request_id: str,
    theme_ok: Iterable[str] = (),
) -> tuple[Selection, list[dict[str, Any]]]:
    """(Selection, facts). facts = 지표 인용 레코드 (evidence_index 에 들어감).
    theme_ok: 분석 기준일 테마 판정을 통과한 종목 — 시작일 재선정(07)이 넘긴다 (넓은 배당 테마의 배당 확인에 쓴다)."""
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
    # 넓은 '배당' 테마인데 선정 지표가 배당이 아니면 배당을 주는 회사인지만 따로 본다 (061: '배당을 꾸준히 늘려 온 기업 중 덜 흔들리는 종목' 을
    # 저변동성 순으로만 골라 배당이 없는 BRK-B·WBD 가 들어갔는데 리포트는 '배당 기업' 이라고 불렀다)
    no_div = _no_dividend(view, it, tagging, metric, tickers, forced, theme_ok)
    if no_div:
        rejected += [Rejected(ticker=t, reason="no_dividend") for t in no_div]
        warnings.append(f"dividend theme: dropped {len(no_div)} candidates without a confirmed dividend in the last 12 months {no_div}")
    ranked = [t for t in tickers if t not in set(no_div)]
    g_rej, g_warn = _idea_guards(view, desc, scr, ranked, forced)
    if g_rej:
        rejected += g_rej
        ranked = [t for t in ranked if t not in {r.ticker for r in g_rej}]
    warnings += g_warn

    values, facts = M.METRICS[metric](view, ranked) if ranked else (M.pd.Series(dtype=float), [])
    fact_by_ticker = {f.ticker: f for f in facts}
    pool: list[tuple[str, float]] = []
    lo, hi = M.ELIGIBLE_RANGE.get(metric, (None, None))
    for t in ranked:
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

    if metric == "vol_60d":
        pool = _low_vol_half(pool, forced, rejected)
    elif metric in ("dividend_yield_ttm", "pe_ttm") and getattr(getattr(getattr(view, "s", None), "selection", None), "style_floor_median", False):
        pool = _style_floor(view, desc, metric, pool, forced, rejected, warnings)
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
    pos = {t: i for i, (t, _) in enumerate(pool)}
    for t, v in deferred:
        if len(selected) >= n:
            # 순위대로라면 뽑혔는데 섹터 선호 때문에 빠진 경우만 sector_preference (008: 어차피 순위 밖인 TER·LRCX·INTC 까지 '자리를 내줬다' 고 했다).
            # 상위 n 개 밖이어도 순위가 더 낮은 다른 섹터 종목이 뽑혔으면 '순위 밖' 이 아니다 (063: 22위 NXPI 를 '순위 밖' 이라 했는데 23·24위 MELI·PDD 가 선정됨)
            displaced = t in pure
            lower_in = not displaced and any(pos.get(x.ticker, -1) > pos[t] for x in selected if not x.forced)
            rejected.append(Rejected(ticker=t, reason="sector_preference" if displaced else "sector_preference_lower" if lower_in else "rank_beyond_n",
                                     metric_value=v if math.isfinite(v) else None))  # fmt: skip
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
            # 실제로 묶는 상한만 해결 방법으로 (065: 금융 9종목 × 15% = 135% 라 섹터 상한 60% 만 묶는데 '종목당 상한을 올리기' 도 권했다)
            "options_ko": ([f"섹터 상한을 {needed:.0%}로 올리기", *(["종목당 상한을 올리기"] if lim["kind"] in ("stock", "both") else []),
                            "테마를 넓혀 다른 섹터 후보를 늘리기"] if needed
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
                 "n_with_metric": n_pass, "n_no_dividend": len(no_div), "n_forced": n_forced, "n_target": nh["target"], "n_selected": len(selected), "sector_cap": sector_pref,  # n_with_metric 은 필수 포함 포함
                 "weight_capacity": round(cap_now, 4), "sector_overflow": sector_overflow,
                 "sector_counts": {sec_names.get(c, c): k for c, k in sec_count.items()},
                 "market_counts": dict(Counter(s.market for s in selected))},
        warnings=warnings,
    )  # fmt: skip
    return sel, [f.to_dict() for f in facts if f.ticker in {s.ticker for s in selected}]


def dividend_theme(it: dict[str, Any]) -> bool:
    """테마가 '배당 기업' 인가 (id·이름에 dividend·배당)."""
    themes = (it.get("interpretation") or {}).get("themes") or []
    return any("dividend" in str(th.get("id") or "").lower() or "배당" in str(th.get("label_ko") or "") for th in themes)


def _idea_guards(view: MarketDataView, desc: Descriptor, scr: dict[str, Any], tickers: list[str], forced: set[str]) -> tuple[list[Rejected], list[str]]:
    """아이디어가 템플릿 지표 하나로 못 담는 뜻을 거른다 (intent.screen 의 보조 조건, 값은 m3_selection.intent.idea_screen_guards).
    - dividend_growth_years = N: 최근 N년 주당배당(최근 12개월) 이력. 해마다 허용 폭보다 더 줄면 뺀다. dividend_require_growth 면 N년 전보다 많고
      해마다 거의 빠짐없이(한 해만 쉬어도 됨) 늘어야 한다. 중간 해 자료가 비면 그 해는 건너뛴다.
    - max_debt_to_equity: 부채비율이 상한을 넘거나 자본이 0 이하인 종목을 뺀다. 금융 섹터(GICS 40)는 부채(예금·보험부채)가 사업 자체라 재지 않고, 자료가 없으면 남긴다.
    - mega_cap_rank = K: 선정일 시가총액 순위(같은 시장 전체 주식 기준)가 K 위 밖이거나 시가총액 자료가 없는 종목을 뺀다. 가장 넓은 조건이라 먼저 본다.
    - high_margin: 영업이익률(최근 4개 분기)이 같은 유니버스(같은 시장) 비금융 종목의 중앙값 이상인 종목만. 금융 섹터는 재지 않고, 자료가 없으면 남긴다.
      (예전에는 테마 후보 중 위쪽 절반이라 빅테크끼리 비교해 이익률 33% 인 GOOGL·AAPL 이 빠졌다, 2026-11 평가 019·063)
    - us_hq_only: '미국 기업' 아이디어에서 법인 소재지가 미국 밖인 기업(회사 소개 첫 문장의 정식 이름이 plc·N.V.·Ltd 등)을 뺀다.
      분류(04)가 테마 경계 문장('본사가 미국이 아닌 기업은 넣지 않음')을 놓쳐 MDT·ACN·AMCR·LIN·STE 가 들어갔다 (2026-11 평가 7건).
    필수 포함은 빼지 않고 알린다 (자격선과 같은 규칙)."""
    rej: list[Rejected] = []
    warns: list[str] = []
    if scr.get("us_hq_only") and tickers:
        exc = set(view.s.selection.us_domicile_exceptions)
        abroad = []
        for t in tickers:
            if view.md.market_of(t) != "US" or normalize_ticker(t) in exc:
                continue
            form = foreign_domicile(str((desc.by_ticker(t) or {}).get("intro") or ""))
            if form is None:
                continue
            if t.upper() in forced:
                warns.append(f"must_include {t}: foreign_domicile({form}), kept")
                continue
            abroad.append(t)
            rej.append(Rejected(ticker=t, reason=f"foreign_domicile({form})"))
        if abroad:
            warns.append(f"us headquarters: dropped {len(abroad)} with a legal domicile outside the US [{', '.join(abroad)}]")
        tickers = [t for t in tickers if t not in {r.ticker for r in rej}]
    k = int(scr.get("mega_cap_rank") or 0)
    if k > 0 and tickers:
        rank = _market_cap_rank(view, tickers)
        small = []
        for t in tickers:
            r = rank.get(t)
            if r is not None and r <= k:
                continue
            why = f"market_cap_rank({r}>{k})" if r is not None else "market_cap_rank(unknown)"
            if t.upper() in forced:
                warns.append(f"must_include {t}: {why}, kept")
                continue
            small.append(f"{t} {r}위" if r is not None else f"{t} 자료 없음")
            rej.append(Rejected(ticker=t, reason=why))
        if small:
            warns.append(f"mega cap: dropped {len(small)} outside market-cap rank {k} [{', '.join(small)}]")
        tickers = [t for t in tickers if t not in {r.ticker for r in rej}]
    years = int(scr.get("dividend_growth_years") or 0)
    growth = scr.get("dividend_require_growth", True) is not False
    if years > 0 and tickers:
        tol, raise_min = view.s.selection.dividend_cut_tolerance, view.s.selection.dividend_raise_min
        hist = view.dps_history(tickers, years)
        cut, short = [], []
        for t in tickers:
            h = hist.get(t) or []
            first, last = (h[0] if h else None), (h[-1] if len(h) > years else None)
            pts = [x for x in h if x is not None]
            steps = list(zip(pts, pts[1:]))  # (최근 값, 1년 전 값) … pts[0] = 기준일, 뒤로 갈수록 과거
            if first is None or last is None or first <= 0 or last <= 0:
                why = f"dividend_history_short({years}y)"
            elif any(b < a * (1 - tol) for b, a in steps):
                why = f"dividend_cut({years}y)"
            elif growth and (first <= last or sum(1 for b, a in steps if b > a * (1 + raise_min)) < max(1, len(steps) - 1)):
                why = f"dividend_not_growing({years}y)"  # 해마다 거의 빠짐없이 인상 (한 해만 쉬어도 됨) — 동결이 이어지면 성장이 아니다
            else:
                continue
            if t.upper() in forced:
                warns.append(f"must_include {t}: {why}, kept")
                continue
            (short if why.startswith("dividend_history") else cut).append(t)
            rej.append(Rejected(ticker=t, reason=why))
        if cut:
            warns.append(f"dividend growth ({years}y): dropped {len(cut)} without steady growth [{', '.join(cut)}]" if growth
                         else f"dividend steady ({years}y): dropped {len(cut)} with a dividend cut [{', '.join(cut)}]")
        if short:
            warns.append(f"dividend history ({years}y): dropped {len(short)} without dividend history [{', '.join(short)}]")
    lim = scr.get("max_debt_to_equity")
    done = {r.ticker for r in rej}
    if lim and tickers:
        de = view.debt_to_equity([t for t in tickers if t not in done])
        high, unknown = [], []
        for t, v in de.items():
            e = desc.by_ticker(t) or {}
            g = D.gics_model(e) if e else None
            if g is not None and g.sector.code == "40":
                continue
            if v is None:
                unknown.append(t)
            elif v > float(lim):
                if t.upper() in forced:
                    warns.append(f"must_include {t}: debt_to_equity({'inf' if math.isinf(v) else format(v, '.2f')}>{float(lim):g}), kept")
                    continue
                high.append(f"{t} {'자본 0 이하' if math.isinf(v) else format(v, '.2f')}")
                rej.append(Rejected(ticker=t, reason=f"debt_to_equity({'inf' if math.isinf(v) else format(v, '.2f')}>{float(lim):g})", metric_value=None if math.isinf(v) else v))
        if high:
            warns.append(f"balance sheet: dropped {len(high)} with debt/equity above {float(lim):g} [{', '.join(high)}]")
        if unknown:
            warns.append(f"balance sheet: debt/equity unknown for {len(unknown)} kept [{', '.join(unknown)}]")
    if scr.get("high_margin") and tickers:
        rej_t = {r.ticker for r in rej}
        nonfin = [t for t in tickers if t not in rej_t and ((g := (D.gics_model(e) if (e := desc.by_ticker(t) or {}) else None)) is None or g.sector.code != "40")]
        mg = view.operating_margin_ttm(nonfin) if nonfin else {}
        meds = {m: _universe_median(view, desc, "operating_margin", m) for m in {view.md.market_of(t) for t in nonfin}}
        low = []
        for t, v in mg.items():
            med = meds.get(view.md.market_of(t))
            if v is None or med is None or v >= med - 1e-12:  # 중앙값 이상 통과 (모자라도 채우지 않는다 — 자격선과 같은 규칙)
                continue
            if t.upper() in forced:
                warns.append(f"must_include {t}: operating_margin({v:.4f}<{med:.4f}), kept")
                continue
            low.append(f"{t} {v:.1%}")
            rej.append(Rejected(ticker=t, reason=f"operating_margin({v:.4f}<{med:.4f})", metric_value=None))
        if low:
            med_txt = ";".join(f"{m}:{v:.4f}" for m, v in sorted(meds.items()) if v is not None) if len(meds) > 1 else f"{next(iter(meds.values())):.4f}"
            warns.append(f"profit margin: dropped {len(low)} below the universe median operating margin {med_txt} [{', '.join(low)}]")
        unknown_m = [t for t in nonfin if mg.get(t) is None and t.upper() not in forced]
        if unknown_m:
            warns.append(f"profit margin: operating margin unknown for {len(unknown_m)} kept [{', '.join(unknown_m)}]")
    return rej, warns


# 회사 소개(yfinance 요약) 첫 문장은 정식 이름으로 시작한다: 'Medtronic plc develops …', 'Amcor plc, through its subsidiaries, …'
_LEGAL_NAME = re.compile(r"^(?P<name>.{1,80}?)\s+(?:is|was|operates|provides|designs|develops|engages|manufactures|offers|together|through|a|an|and|focuses|produces|owns|researches)\b", re.S)
_FOREIGN_FORM = re.compile(r"(?:^|[\s,])(plc|Plc|PLC|N\.V\.|NV|Ltd\.?|LTD\.?|Limited|AG|S\.A\.|SA|SE|B\.V\.|S\.p\.A\.|A/S|ASA|Oyj)(?=$|[\s,.])")


def foreign_domicile(intro: str) -> str | None:
    """회사 소개 첫 문장의 정식 이름에 미국 밖 법인 형태(plc·N.V.·Ltd·AG·SA 등)가 있으면 그 형태, 없으면 None.
    법인 소재지 기준이라 운영 본사가 미국인 버뮤다·아일랜드 법인(IVZ·RCL 등)도 미국 밖으로 본다 — 심사도 법인 소재지로 판정했다."""
    m = _LEGAL_NAME.match(intro or "")
    name = m.group("name") if m else (intro or "")[:60]
    f = _FOREIGN_FORM.search(name)
    return f.group(1) if f else None


def _universe_median(view: MarketDataView, desc: Descriptor, what: str, market: str) -> float | None:
    """같은 유니버스(요청한 종목 사전)에서 같은 시장 종목의 중앙값: 'dividend_yield_ttm'(자료가 있는 종목), 'pe_ttm'(양수만),
    'operating_margin'(금융 섹터 제외). 값이 5개 미만이면 None (거르지 않는다)."""
    tks = [t for t in D.tickers(desc) if view.md.market_of(t) == market]
    if what == "operating_margin":
        tks = [t for t in tks if (g := (D.gics_model(e) if (e := desc.by_ticker(t) or {}) else None)) is None or g.sector.code != "40"]
        vals = [v for v in view.operating_margin_ttm(tks).values() if v is not None and math.isfinite(v)]
    else:
        s, _ = M.METRICS[what](view, tks)
        vals = [float(v) for v in s.values if math.isfinite(float(v))]
    if len(vals) < 5:
        return None
    vals.sort()
    n = len(vals)
    return vals[n // 2] if n % 2 else (vals[n // 2 - 1] + vals[n // 2]) / 2


def _style_floor(view: MarketDataView, desc: Descriptor, metric: str, pool: list[tuple[str, float]], forced: set[str], rejected: list[Rejected],
                 warnings: list[str]) -> list[tuple[str, float]]:
    """고배당은 배당수익률이 같은 유니버스(같은 시장) 종목의 중앙값 이상, 저PER 은 PER 이 중앙값 이하인 종목에서만 고른다 (2026-11 평가 사용자 결정).
    후보가 목표보다 적어 모두 담을 때 '배당을 많이 주는'·'실적 대비 싼' 과 반대인 종목이 들어갔다 (062 CEG 배당 0.12%, 079 카카오뱅크 PER 25.5).
    자격선과 같은 규칙: 모자라도 채우지 않고, 필수 포함은 남기고 알린다.
    단 테마 후보가 모두 기준선 밖이면(인터넷·게임처럼 업종 전체가 PER 이 높을 때, 003) 분석할 종목이 없어지므로 그 시장 후보 중 나은 절반을 고르고 알린다."""
    meds = {m: _universe_median(view, desc, metric, m) for m in {view.md.market_of(t) for t, _ in pool}}
    worse = (lambda v, ref: v < ref - 1e-12) if metric == "dividend_yield_ttm" else (lambda v, ref: v > ref + 1e-12)
    for m, med in list(meds.items()):
        own = [(t, v) for t, v in pool if view.md.market_of(t) == m and t.upper() not in forced and math.isfinite(v)]
        if med is None or not own or any(not worse(v, med) for _, v in own):
            continue
        vals = sorted(v for _, v in own)
        half = vals[len(vals) // 2] if metric == "dividend_yield_ttm" else vals[(len(vals) - 1) // 2]  # 배당은 위쪽, PER 은 아래쪽 절반
        meds[m] = half
        kept = [t for t, v in own if not worse(v, half)]
        warnings.append(f"style floor: all {len(own)} candidates beyond the universe median {med:.4g} for {metric}; kept the better half of theme candidates (median {half:.4g}) [{', '.join(kept)}]")
    keep = []
    for t, v in pool:
        med = meds.get(view.md.market_of(t))
        bad = med is not None and math.isfinite(v) and worse(v, med)
        if not bad:
            keep.append((t, v))
            continue
        reason = f"metric_out_of_range({metric}={v:.4g}, 시장 중앙값 {med:.4g} {'미만' if metric == 'dividend_yield_ttm' else '초과'})"  # 대체 기준이면 후보 중앙값
        if t.upper() in forced:
            warnings.append(f"must_include {t}: {reason}, kept")
            keep.append((t, v))
        else:
            rejected.append(Rejected(ticker=t, reason=reason, metric_value=v))
    return keep


def _market_cap_rank(view: MarketDataView, tickers: list[str]) -> dict[str, int]:
    """선정일 시가총액 순위 — 같은 시장의 팀 DB 전체 주식(미국 = S&P 500 ∪ 나스닥 100) 기준이라 요청 유니버스(나스닥 100 만 등)에 따라 달라지지 않는다.
    같은 회사의 주식 클래스(GOOGL·GOOG)는 한 회사로 센다. 시가총액 자료가 없는 종목은 결과에 없다."""
    assets = view.md.assets
    out: dict[str, int] = {}
    for m in {view.md.market_of(t) for t in tickers}:
        mc = view.market_cap_usd([s for s, a in assets.items() if a.get("market") == m and a.get("asset_type") == "STOCK"])
        best: dict[str, float] = {}
        for s, v in mc.items():
            key = _share_class_key(assets.get(s) or {"ticker": s})
            best[key] = max(best.get(key, 0.0), v)
        order = {key: i + 1 for i, key in enumerate(sorted(best, key=lambda x: -best[x]))}
        for t in tickers:
            s = normalize_ticker(t)
            if view.md.market_of(t) == m and s in mc:
                out[t] = order[_share_class_key(assets.get(s) or {"ticker": s})]
    return out


def _low_vol_half(pool: list[tuple[str, float]], forced: set[str], rejected: list[Rejected]) -> list[tuple[str, float]]:
    """저변동성은 테마 후보 중 변동성이 낮은 절반(중앙값 이하)에서만 고른다 — 자격선과 같은 규칙: 모자라도 채우지 않는다.
    (2026-11 평가 010: 목표 30개에 후보 25개라 변동성 0.49 인 BSX 까지 다 담아 '크게 흔들리지 않는 종목 위주' 가 뜻을 잃었다.
    후보가 목표의 두 배 이상이면 위쪽 절반은 어차피 뽑히지 않아 결과가 같다)"""
    vals = sorted(v for t, v in pool if t.upper() not in forced and math.isfinite(v))
    if len(vals) < 2:
        return pool
    med = vals[(len(vals) - 1) // 2]
    keep = []
    for t, v in pool:
        if t.upper() in forced or not math.isfinite(v) or v <= med:
            keep.append((t, v))
        else:
            rejected.append(Rejected(ticker=t, reason=f"metric_out_of_range(vol_60d={v:.4g}, 후보 중앙값 {med:.4g} 초과)", metric_value=v))
    return keep


def _no_dividend(view: MarketDataView, it: dict[str, Any], tagging: Tagging, metric: str, tickers: list[str], forced: set[str],
                 theme_ok: Iterable[str] = ()) -> list[str]:
    """넓은 배당 테마에서 최근 12개월 배당을 확인할 수 없는 종목 (필수 포함 제외). 좁은 테마는 테마 판정이, 배당 지표 순위는 자격선이 이미 거른다.
    팀 DB 배당 자료가 있으면 그 값(> 0)으로, 없으면 분석 기준일 테마 판정(배당 기업인가)으로 본다 — 배당 자료는 빈 곳이 많다
    (061 재실행: 자료만 보면 기준일에 AME·AMP·DLR·TRV 같은 배당 기업 7개, 시작일에 ABT·COST·MA·UPS 등이 '배당 없음' 으로 빠졌다).
    자료가 0 이면 그날은 배당이 없던 것이라 테마 판정보다 앞선다."""
    if getattr(tagging, "theme_filter_applied", True) or metric == "dividend_yield_ttm" or not tickers or not dividend_theme(it):
        return []
    min_conf = float(getattr(tagging, "min_confidence", 0.5) or 0.0)
    ok = set(theme_ok) | {r.ticker for r in getattr(tagging, "tagged", None) or [] if getattr(r, "in_theme", False) and float(r.confidence or 0) >= min_conf}
    dv, _ = M.METRICS["dividend_yield_ttm"](view, tickers)
    out = []
    for t in tickers:
        v = float(dv[t]) if t in dv.index else float("nan")
        paid = v > 0 if math.isfinite(v) else t in ok
        if not paid and t.upper() not in forced:
            out.append(t)
    return out
