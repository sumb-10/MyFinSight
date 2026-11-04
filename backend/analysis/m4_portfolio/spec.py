"""M4-01 구성 사양·기준일 확정 (stage7 포팅). 백테스트 창·달력·초기자본 환율·시작일 재선정(코드 단계 3·5 직접 호출).

- 창: [derived.backtest_start, derived.backtest_end]. 시작일 as_of_bt = 창 첫 거래일 (합집합 달력).
- 재선정: 시작일 기준 view 로 후보 검색·정량 선정을 다시 하되, LLM 분류(04)는 날짜와 무관하므로 재사용한다.
- 비교지수: 요청의 benchmark + 설정의 보조 지수 + (한국 종목이 있으면) 한국 지수.
"""

from __future__ import annotations

import datetime as dt
from typing import Any

import pandas as pd

from backend.analysis.errors import DataMissing
from backend.analysis.m2_data.market_data import MarketData
from backend.analysis.m3_selection.retrieve import retrieve
from backend.analysis.m3_selection.screen import screen
from backend.analysis.schemas.backtest import BacktestRequest, BacktestSpec
from backend.analysis.schemas.selection import Selection, Tagging
from backend.analysis.settings import AnalysisSettings
from backend.pipeline.descriptor import Descriptor

MIN_HISTORY_DAYS = 400


MAX_START_SHIFTS = 36  # 선정 지표 자료가 드문 초기 구간: 시작일을 최대 36개월까지 뒤로 옮겨 본다
SHIFT_STEP_DAYS = 28  # 한 번에 '28일 뒤 첫 거래일' 로
MIN_REMAINING_DAYS = 365  # 옮긴 뒤 남는 창: max(1년, 요청 창의 절반)


def next_shift_day(cal: pd.DatetimeIndex, day: dt.date) -> dt.date | None:
    """시작일 이동의 다음 후보: day + 28일 뒤 첫 거래일 (07 과 실행 전 점검이 같은 규칙을 쓴다)."""
    later = cal[cal > pd.Timestamp(day) + pd.Timedelta(days=SHIFT_STEP_DAYS)]
    return later[0].date() if len(later) else None


def shift_window_ok(end: dt.date, day: dt.date, total_days: int) -> bool:
    return (end - day).days >= max(MIN_REMAINING_DAYS, int(total_days * 0.5))


def selectable_at(md: MarketData, day: dt.date, desc: Descriptor, intent: dict[str, Any], cons: dict[str, Any], passed: list[str], request_id: str,
                  *, added: tuple[str, ...] = (), removed: frozenset[str] | set[str] = frozenset()) -> tuple[Any, Tagging | None, Selection, list[dict[str, Any]]]:  # fmt: skip
    """그날 선정 가능한 종목: 그날 후보 검색(상한 없음) ∩ 기준일 테마 판정 통과 → 정량 선정. 07 재선정과 실행 전 점검이 같이 쓴다."""
    view_bt = md.view(day)
    cand = retrieve(view_bt, desc, intent, cons, request_id=request_id, max_candidates=None)  # 04 통과 집합과의 교집합이 최종이라 상한을 두지 않는다
    cset = {c.ticker for c in cand.candidates}
    passed_bt = sorted((set(passed) & cset | set(added)) - set(removed))
    tag = Tagging(request_id=request_id, min_confidence=0.0, tagged=[], excluded_by_theme=[], passed_tickers=passed_bt, batches=0,
                  warnings=[f"re-selection at {day}: passed ∩ candidates_bt = {len(passed_bt)}"])  # fmt: skip
    sel, facts = screen(view_bt, desc, tag, intent, cons, request_id=request_id)
    return cand, tag, sel, facts


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
    start_shift_ok: bool = True,
) -> tuple[dict[str, Any], dict[str, Any]]:
    """(BacktestSpec dict, extras). extras = {"candidates_bt", "tagging_bt", "selection_bt", "facts_bt"} (재선정 시).

    시작일 이동 정책 (2026-11 사용자 정책 결정 4): 시작일 재선정이 최소 종목 수에 못 미치면
    - 사용자가 동의했을 때만(start_shift_ok: 시작일 질문을 건너뛰었거나 '옮기기' 를 고름 · 개발 CLI 기본값) 최소 종목 수를 채우는 날로 옮긴다.
      기준일에도 최소 미달이거나 '기간 유지' 를 골랐으면 동의로 보지 않는다.
    - 동의가 없어도 시작일 종목이 1개 이하면 2종목 이상이 되는 날로 자동으로 옮기고 알린다 (F2: 1종목 시작에서 실행이 멈췄다).
    - 옮겨도 목표를 못 채우면 원래 시작일로 되돌린다 (창만 줄고 종목은 그대로인 결과를 피함). 0종목이면 한국어 오류로 멈춘다.
    이동 규칙(28일 뒤 첫 거래일, 남는 창 max(1년, 절반), 최대 36회)은 실행 전 점검(precheck)과 같다."""
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

    def canon(t: Any) -> str | None:  # 확인 단계 종목은 표기를 디스크립터 기준으로 맞춘다 ('105560', '105560.ks' → '105560.KS')
        e = desc.by_ticker(str(t).strip())
        return e["yfinance_symbol"] if e else None

    raw_added = list(bt_req.confirmation.added_tickers)
    added = list(dict.fromkeys(c for c in map(canon, raw_added) if c))  # 중복 제거 (F1: 이미 있는 종목을 다시 넣으면 같은 열 두 개로 실행이 멈췄다)
    bad = sorted(str(t) for t in raw_added if not canon(t))
    if bad:
        warnings.append(f"added_tickers not in universe ignored: {bad}")
    removed = {canon(t) or str(t).strip().upper() for t in bt_req.confirmation.removed_tickers}
    extras: dict[str, Any] = {}
    sel_bt_obj: Selection | None = None
    if bw.reselect_at_start:
        nh_min = int((req["constraints"].get("num_holdings") or {}).get("min", 1) or 1)
        n_now = len(selection.selected)
        first_try, total_days = as_of, max(1, (bw.end_date - as_of).days)
        cons_bt = dict(req["constraints"])
        cons_bt["must_include_tickers"] = sorted(set(cons_bt.get("must_include_tickers", [])) | set(added))
        cons_bt["exclude_tickers"] = sorted(set(cons_bt.get("exclude_tickers", [])) | removed)

        def at(day: dt.date):
            return selectable_at(md, day, desc, intent, cons_bt, list(tagging.passed_tickers), req["request_id"], added=tuple(added), removed=removed)

        first = at(first_try)
        n_first = len(first[2].selected)
        consent = start_shift_ok and not allow_fewer_at_start and n_now >= nh_min
        goal = nh_min if consent else (2 if n_first <= 1 else None)  # 동의 없으면 1종목 이하일 때만 '2종목 이상' 을 목표로 자동 이동
        chosen, chosen_day, tries, best = first, first_try, 0, (n_first, first_try, first, 0)
        if goal is not None and n_first < goal:
            day, found, first_ge2 = first_try, None, None
            while tries < MAX_START_SHIFTS:
                nxt = next_shift_day(cal, day)
                if nxt is None or not shift_window_ok(bw.end_date, nxt, total_days):
                    break
                day, tries = nxt, tries + 1
                res = at(day)
                n = len(res[2].selected)
                if n > best[0]:
                    best = (n, day, res, tries)
                if n >= 2 and first_ge2 is None:
                    first_ge2 = (day, res, tries)
                if n >= goal:
                    found = (day, res, tries)
                    break
            if found:
                chosen_day, chosen, tries = found
            elif n_first <= 1 and first_ge2:  # 목표는 못 채웠어도 1종목 이하로 시작하지는 않는다 (정책 결정 4)
                chosen_day, chosen, tries = first_ge2
            elif n_first == 0 and best[0] >= 1:  # 끝까지 0종목보다는 가장 많이 고를 수 있던 날
                _n, chosen_day, chosen, tries = best
            else:
                tries = 0  # 원래 시작일로 되돌림 (창만 줄고 종목은 그대로인 결과를 피함)
        cand_bt, tag_bt, sel_bt_obj, facts_bt = chosen
        as_of = chosen_day
        view_bt = md.view(as_of)  # 아래 초기자본 환율 환산이 쓴다
        n_sel = len(sel_bt_obj.selected)
        if n_sel == 0:
            raise DataMissing(f"백테스트 시작일 {first_try} 이후 {MAX_START_SHIFTS}회 옮겨 봐도 선정 가능한 종목이 없습니다. 테마를 넓히거나 백테스트 기간·시가총액·거래대금 조건을 바꿔 보세요.",
                              details={"code": "SELECTION_EMPTY_AT_START", "start": str(first_try)})  # fmt: skip
        if as_of != first_try:
            if consent:
                warnings.append(f"백테스트 시작일 {first_try} 에는 테마 후보 중 선정 가능한 종목이 최소 종목 수({nh_min})보다 적어 시작을 {as_of} 로 옮김 ({tries}개월 뒤, 선정 {n_sel}종목)")
            else:
                warnings.append(f"백테스트 시작일 {first_try} 에는 선정 가능한 종목이 {n_first}개뿐이라 시작을 {as_of} 로 자동으로 옮김 ({tries}개월 뒤, 선정 {n_sel}종목)")
            cal = cal[cal >= pd.Timestamp(as_of)]
            bw = bw.model_copy(update={"start_date": as_of})
        if n_sel < nh_min:
            if n_now < nh_min:
                why = "기준일에도 최소 종목 수에 못 미쳐 시작일을 옮기지 않고"
            elif allow_fewer_at_start:
                why = "요청대로 백테스트 기간을 유지해"
            elif not start_shift_ok:
                why = "시작일을 옮기는 데 동의하지 않아 기간을 유지하고"
            else:
                why = "시작일을 옮겨도 최소 종목 수를 채울 수 없어 기간을 유지하고"
            warnings.append(f"백테스트 시작일 {as_of} 에는 선정 가능한 종목이 {n_sel}개(최소 {nh_min}개)입니다. {why} 그 종목으로 시작합니다")
        source = "reselected_at_start"
        rows = [s.model_dump(mode="json") for s in sel_bt_obj.selected]
        warnings += [f"screen@{as_of}: {w}" for w in sel_bt_obj.warnings]
        tag_bt = tagging.model_copy(update={"passed_tickers": tag_bt.passed_tickers, "warnings": [*tagging.warnings, *tag_bt.warnings]})
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
        present = {r["ticker"] for r in rows}
        fd_added = view_bt.first_dates(added) if added else {}
        for t in added:
            if t in present:  # 이미 선정된 종목을 다시 넣으면 그대로 둔다 (F1)
                continue
            first = fd_added.get(t)
            if first is None or (as_of - first).days < MIN_HISTORY_DAYS:
                warnings.append(f"{t} dropped: insufficient history before {as_of}")
                continue
            e = desc.by_ticker(t)
            rows.append({"ticker": t, "name": e["name"], "sector": (e.get("gics") or {}).get("sector", {}).get("name_en", ""), "rank": len(rows) + 1,
                         "metric_value": float("nan")})  # fmt: skip
        warnings.append("original selection used at an earlier date: selection look-ahead bias present")
    tickers = list(dict.fromkeys(r["ticker"] for r in rows))
    if not tickers:
        raise DataMissing("백테스트에 쓸 종목이 남지 않았습니다. 테마를 넓히거나 조건을 바꿔 보세요.", details={"code": "SELECTION_EMPTY_AT_START"})

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
