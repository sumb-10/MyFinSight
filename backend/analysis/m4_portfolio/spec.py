"""M4-01 구성 사양·기준일 확정 (stage7 포팅). 백테스트 창·달력·초기자본 환율·시작일 재선정(코드 단계 3·5 직접 호출).

- 창: [derived.backtest_start, derived.backtest_end]. 시작일 as_of_bt = 창 첫 거래일 (합집합 달력).
- 재선정: 시작일 기준 view 로 후보 검색·정량 선정을 다시 하되, LLM 분류(04)는 날짜와 무관하므로 재사용한다.
- 비교지수: 요청의 benchmark + 설정의 보조 지수 + (한국 종목이 있으면) 한국 지수.
"""

from __future__ import annotations

import datetime as dt
from typing import Any

import pandas as pd

from backend.analysis.m2_data.market_data import MarketData
from backend.analysis.m3_selection.retrieve import retrieve
from backend.analysis.m3_selection.screen import screen
from backend.analysis.schemas.backtest import BacktestRequest, BacktestSpec
from backend.analysis.schemas.selection import Selection, Tagging
from backend.analysis.settings import AnalysisSettings
from backend.pipeline.descriptor import Descriptor

MIN_HISTORY_DAYS = 400


MAX_START_SHIFTS = 36  # 선정 지표 자료가 드문 초기 구간: 시작일을 최대 36개월까지 뒤로 옮겨 본다


def benchmarks_for(req: dict[str, Any], tickers: list[str], md: MarketData, settings: AnalysisSettings) -> tuple[str, list[str]]:
    primary = req["risk"].get("benchmark") or settings.market.primary_benchmark_default
    extras = [b for b in settings.market.extra_benchmarks if b != primary]
    if any(md.market_of(t) == "KR" for t in tickers) and settings.market.kr_benchmark not in (primary, *extras):
        extras.append(settings.market.kr_benchmark)
    return primary, extras


def build_backtest_spec(
    md: MarketData,
    req: dict[str, Any],
    intent: dict[str, Any],
    tagging: Tagging,
    selection: Selection,
    desc: Descriptor,
    settings: AnalysisSettings,
    *,
    bt_req: BacktestRequest | None = None,
    allow_fewer_at_start: bool = False,
) -> tuple[dict[str, Any], dict[str, Any]]:
    """(BacktestSpec dict, extras). extras = {"candidates_bt", "tagging_bt", "selection_bt", "facts_bt"} (재선정 시).

    시작일 이동 정책 (라운드 5): 시작일 재선정이 최소 종목 수에 못 미치면 한 달씩 옮겨 보되,
    ① 기준일에도 최소 미달이면(옮겨도 소용없음) ② 사용자가 기간 유지를 골랐으면(allow_fewer_at_start) ③ 남는 창이 요청 창의 절반 미만이 되면 옮기지 않고,
    그 시작일에 선정 가능한 종목으로 시작한다는 사용자 공지를 낸다 (fewer_holdings_at_start)."""
    d = req["derived"]
    bt_req = bt_req or BacktestRequest(request_id=req["request_id"],
                                       backtest={"start_date": d["backtest_start"], "end_date": d["backtest_end"]})  # fmt: skip
    warnings: list[str] = []
    if bt_req.request_id != req["request_id"]:
        warnings.append(f"request_id mismatch: {bt_req.request_id} vs {req['request_id']}")
    d0, d1 = dt.date.fromisoformat(str(d["price_data_start"])), dt.date.fromisoformat(str(d["price_data_end"]))
    bw = bt_req.backtest
    if bw.end_date > d1:
        warnings.append(f"backtest end_date {bw.end_date} clamped to data end {d1}")
        bw = bw.model_copy(update={"end_date": d1})
    if bw.start_date < d0:
        warnings.append(f"backtest start_date {bw.start_date} clamped to data start {d0}")
        bw = bw.model_copy(update={"start_date": d0})
    end_view = md.view(bw.end_date)
    markets = sorted({md.market_of(s.ticker) for s in selection.selected} or set(settings.market.markets))
    cal = end_view.trading_days(bw.start_date, bw.end_date, markets=markets)
    if len(cal) < 2:
        raise ValueError(f"backtest window {bw.start_date}..{bw.end_date} has no trading days")
    as_of = cal[0].date()
    lookback_days = settings.portfolio.lookback_days
    if (as_of - d0).days < lookback_days * 1.45:
        warnings.append(f"less than {lookback_days} trading days of history before {as_of} for the covariance window")

    orig = [s.ticker for s in selection.selected]
    added = [t for t in bt_req.confirmation.added_tickers if desc.by_ticker(t)]
    bad = sorted(set(bt_req.confirmation.added_tickers) - set(added))
    if bad:
        warnings.append(f"added_tickers not in universe ignored: {bad}")
    removed = set(bt_req.confirmation.removed_tickers)
    extras: dict[str, Any] = {}
    sel_bt_obj: Selection | None = None
    if bw.reselect_at_start:
        nh_min = int((req["constraints"].get("num_holdings") or {}).get("min", 1) or 1)
        first_try, tries = as_of, 0
        n_now = len(selection.selected)
        total_days = max(1, (bw.end_date - first_try).days)
        shift_allowed = (not allow_fewer_at_start) and n_now >= nh_min
        while True:
            view_bt = md.view(as_of)
            cons_bt = dict(req["constraints"])
            cons_bt["must_include_tickers"] = sorted(set(cons_bt.get("must_include_tickers", [])) | set(added))
            cons_bt["exclude_tickers"] = sorted(set(cons_bt.get("exclude_tickers", [])) | removed)
            cand_bt = retrieve(view_bt, desc, intent, cons_bt, request_id=req["request_id"], max_candidates=None)  # 04 통과 집합과의 교집합이 최종이라 상한을 두지 않는다
            cset = {c.ticker for c in cand_bt.candidates}
            passed_bt = sorted((set(tagging.passed_tickers) & cset | set(added)) - removed)
            tag_bt = tagging.model_copy(update={"passed_tickers": passed_bt,
                                                "warnings": [*tagging.warnings, f"re-selection at {as_of}: passed ∩ candidates_bt = {len(passed_bt)}"]})  # fmt: skip
            sel_bt_obj, facts_bt = screen(view_bt, desc, tag_bt, intent, cons_bt, request_id=req["request_id"])
            if len(sel_bt_obj.selected) >= nh_min or tries >= MAX_START_SHIFTS or not shift_allowed:
                break
            # 시작일에 선정 가능한 종목(테마 후보 ∩ 분류 통과, 지표 있음)이 최소 종목 수보다 적다 → 한 달 뒤 첫 거래일로 옮겨 다시 선정
            later = cal[cal > pd.Timestamp(as_of) + pd.Timedelta(days=28)]
            if len(later) == 0 or (bw.end_date - later[0].date()).days < max(365, int(total_days * 0.5)):
                break
            as_of = later[0].date()
            tries += 1
        n_sel = len(sel_bt_obj.selected)
        if tries:
            warnings.append(f"백테스트 시작일 {first_try} 에는 테마 후보 중 선정 가능한 종목이 최소 종목 수({nh_min})보다 적어 시작을 {as_of} 로 옮김 ({tries}개월 뒤, 선정 {n_sel}종목)")
            cal = cal[cal >= pd.Timestamp(as_of)]
            bw = bw.model_copy(update={"start_date": as_of})
        if n_sel < nh_min:
            why = ("기준일에도 최소 종목 수에 못 미쳐 시작일을 옮기지 않고" if n_now < nh_min else
                   ("요청대로 백테스트 기간을 유지해" if allow_fewer_at_start else "시작일을 더 옮기면 평가 기간이 너무 짧아져"))
            warnings.append(f"백테스트 시작일 {as_of} 에는 선정 가능한 종목이 {n_sel}개(최소 {nh_min}개)입니다. {why} 그 종목으로 시작합니다")
        source = "reselected_at_start"
        rows = [s.model_dump(mode="json") for s in sel_bt_obj.selected]
        warnings += [f"screen@{as_of}: {w}" for w in sel_bt_obj.warnings]
        extras = {"candidates_bt": cand_bt.model_dump(mode="json"), "tagging_bt": tag_bt.model_dump(mode="json"),
                  "selection_bt": sel_bt_obj.model_dump(mode="json"), "facts_bt": facts_bt}  # fmt: skip
    else:
        source = "original"
        view_bt = md.view(as_of)
        fd = view_bt.first_dates(orig)
        rows = []
        for s in selection.selected:
            if s.ticker in removed:
                continue
            first = fd.get(s.ticker)
            if first is None or (as_of - first).days < MIN_HISTORY_DAYS:
                warnings.append(f"{s.ticker} dropped: insufficient history before {as_of}")
                continue
            rows.append(s.model_dump(mode="json"))
        for t in added:
            e = desc.by_ticker(t)
            rows.append({"ticker": t, "name": e["name"], "sector": (e.get("gics") or {}).get("sector", {}).get("name_en", ""), "rank": len(rows) + 1,
                         "metric_value": float("nan")})  # fmt: skip
        warnings.append("original selection used at an earlier date: selection look-ahead bias present")
    tickers = [r["ticker"] for r in rows]
    if not tickers:
        raise ValueError("no tickers left for the backtest after re-selection")

    # 초기자본·적립을 백테스트 시작일 환율로 환산
    c = req["capital"]
    if c["currency"] == "USD":
        rate, fx_date, fx_src = 1.0, as_of, "none"
    else:
        fx = view_bt.fx_on_or_before(as_of)
        rate, fx_date, fx_src = float(fx.rate), fx.date, f"fx_daily:{fx.source}"
    init_usd, monthly_usd = round(c["initial_amount"] / rate, 2), round(c.get("monthly_contribution", 0) / rate, 2)
    if abs(init_usd - d["initial_amount_usd"]) / max(init_usd, 1e-9) > 0.02:
        warnings.append(f"capital re-converted at {fx_date} FX {rate:.2f}: {init_usd:,.0f} USD vs request-date {d['initial_amount_usd']:,.0f} USD")
    bench, extra_b = benchmarks_for(req, tickers, md, settings)
    if bw.benchmark:
        bench = bw.benchmark
    sel_src = sel_bt_obj if sel_bt_obj is not None else selection
    spec = BacktestSpec(
        request_id=req["request_id"],
        period={"start": bw.start_date, "end": bw.end_date, "as_of": as_of, "trading_days": int(len(cal))},
        capital={"initial_amount_usd": init_usd, "monthly_contribution_usd": monthly_usd if bw.include_contributions else 0.0,
                 "contribution_day": c.get("contribution_day", 25), "include_contributions": bw.include_contributions,
                 "currency": c["currency"], "initial_amount_krw": c["initial_amount"] if c["currency"] == "KRW" else None,
                 "monthly_contribution_krw": c.get("monthly_contribution", 0) if c["currency"] == "KRW" else None,
                 "fx_rate": rate, "fx_date": fx_date, "fx_source": fx_src},
        rebalance_rule=d["rebalance_rule"], benchmark=bench, extra_benchmarks=extra_b,
        selection={"source": source, "metric": selection.summary["metric"], "tickers": tickers,
                   "table": [{"ticker": r["ticker"], "name": r["name"], "sector": r["sector"], "rank": r["rank"], "metric_value": r["metric_value"]} for r in rows],
                   "diff_vs_original": {"added": sorted(set(tickers) - set(orig)), "removed": sorted(set(orig) - set(tickers))},
                   "infeasibility": sel_src.infeasibility, "sector_overflow": sel_src.summary.get("sector_overflow")},
        warnings=warnings,
    )  # fmt: skip
    return spec.model_dump(mode="json"), extras
