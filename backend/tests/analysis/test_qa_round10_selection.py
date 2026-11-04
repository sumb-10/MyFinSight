"""시나리오 QA 라운드 10 (018~022): 필수 포함을 '지표가 있는 종목' 수와 따로 세고 건너뛴 후보 조건을 알림, 자격선 밖 예시 '외 N개'·작은 값 부호,
06 행을 지표 순위 순으로, 종료일에서 잘린 마지막 뷰 창은 판정 보류, R4b/R5b 문구 = 실제 최대 비중, walk-forward 뉴스 BL 라벨, 10f δ 구성 값."""

from __future__ import annotations

import datetime as dt
from types import SimpleNamespace

import numpy as np
import pandas as pd
import pytest

from backend.analysis.common.warnings import from_text
from backend.analysis.settings import AnalysisSettings


def _screen(monkeypatch, metric: str, vals: dict[str, float], cons: dict, direction: str = "desc"):
    from backend.analysis.m2_data import metrics as Mx
    from backend.analysis.m3_selection.screen import screen

    monkeypatch.setitem(Mx.METRICS, metric, lambda view, tks: (pd.Series({t: vals[t] for t in tks}, dtype=float), []))
    desc = SimpleNamespace(by_ticker=lambda t: {"ticker": t, "name": t, "market": "US", "gics": {}})
    tagging = SimpleNamespace(tagged=[SimpleNamespace(ticker=t, confidence=0.9) for t in vals], passed_tickers=list(vals))
    sel, _ = screen(SimpleNamespace(as_of=dt.date(2023, 7, 17)), desc, tagging, {"screen": {"metric": metric, "direction": direction}}, cons, request_id="r")
    return sel


def test_too_few_with_metric_counts_must_include_separately(monkeypatch):
    """018: 시작일 선정 3개 중 2개가 필수 포함(105560.KS 배당 자료 없음, 033780.KS 시가총액 미달로 후보 조건 건너뜀)인데
    '후보 조건과 테마 판정을 통과하고 지표 자료가 있는 종목이 3개' 라고 했다 → 일반 종목 1개 + 필수 포함 2개 별도."""
    vals = {"033780.KS": 0.0604, "105560.KS": float("nan"), "055550.KS": 0.0606, "032830.KS": float("nan")}
    cons = {"num_holdings": {"min": 7, "target": 7, "max": 7}, "max_weight_per_stock": 0.14, "max_weight_per_sector": 0.67, "min_cash_ratio": 0.05,
            "must_include_tickers": ["033780.KS", "105560.KS"]}  # fmt: skip
    sel = _screen(monkeypatch, "dividend_yield_ttm", vals, cons)
    assert sorted(s.ticker for s in sel.selected) == ["033780.KS", "055550.KS", "105560.KS"]
    raw = next(w for w in sel.warnings if w.startswith("only "))
    assert raw == "only 1 tickers have dividend_yield_ttm (+2 must_include); target 7 -> selecting 3"
    w = from_text("07_backtest_spec", f"screen@2023-07-17: {raw}")
    assert w.code == "too_few_with_metric" and w.message_ko.startswith(
        "백테스트 시작일(2023-07-17) 기준: 후보 조건(시가총액·거래대금 등)과 테마 판정을 통과하고 선정 지표(배당수익률) 자료가 있는 종목이 1개(필수 포함 2개 별도)로 "
        "목표 7개보다 적어 3개만 선정했습니다.")  # fmt: skip
    assert sel.summary["n_forced"] == 2 and sel.summary["n_with_metric"] == 3  # 선정 깔때기 수(n_with_metric)는 예전 그대로
    # 필수 포함이 없으면 예전 문장 그대로 (예전 원문도 읽는다)
    old = from_text("05_selection", "only 4 tickers have pe_ttm; target 10 -> selecting 4")
    assert "자료가 있는 종목이 4개로 목표 10개보다 적어 4개만 선정했습니다" in old.message_ko and "필수 포함" not in old.message_ko


ROE_019 = {"AMD": -0.0004533, "DDOG": -0.058, "INTC": -0.009118, "MRVL": -0.02448, "MU": -0.06149, "PLTR": -0.01812, "WDAY": -0.02133, "AAPL": 1.488, "NVDA": 1.172}


def test_too_few_eligible_lists_five_with_more_count_and_visible_tiny_values(monkeypatch):
    """019: 자격선 밖 7개 중 4개만 적고 '외 N개' 가 없었고, AMD ROE −0.045% 가 '-0.0%' 로 보였다."""
    cons = {"num_holdings": {"min": 1, "target": 3, "max": 3}, "max_weight_per_stock": 1.0, "max_weight_per_sector": 1.0, "min_cash_ratio": 0.0}
    sel = _screen(monkeypatch, "roe_ttm", dict(ROE_019), cons)
    raw = next(w for w in sel.warnings if w.startswith("only "))
    assert "excluded 7 out of range: AMD -0.045%, DDOG -5.8%, INTC -0.9%, MRVL -2.4%, MU -6.1%)" in raw
    w = from_text("07_backtest_spec", f"screen@2023-09-15: {raw}")
    assert w.message_ko == ("백테스트 시작일(2023-09-15) 기준: 선정 지표가 자격선 안에 드는 종목이 2개라 목표 3개를 다 채우지 못했습니다 "
                            "(자격선 밖 7개 제외: AMD -0.045%, DDOG -5.8%, INTC -0.9%, MRVL -2.4%, MU -6.1% 외 2개). 선정한 2종목에 투자금을 나눠 담습니다.")  # fmt: skip
    # 예전 원문(예시 4개)도 '외 N개' 를 붙인다
    old = from_text("05_selection", "only 19 tickers within eligibility for roe_ttm; target 20 (excluded 7 out of range: AMD -0.0%, DDOG -5.8%, INTC -0.9%, MRVL -2.4%) [capacity 1.00 of 1.00]")
    assert "MRVL -2.4% 외 3개)" in old.message_ko
    # 필수 포함 AMD 는 자격선 밖이어도 남고(앞의 수에 넣지 않음), 그 공지도 부호가 보인다
    sel2 = _screen(monkeypatch, "roe_ttm", dict(ROE_019), {**cons, "num_holdings": {"min": 1, "target": 4, "max": 4}, "must_include_tickers": ["AMD"]})
    msgs = [from_text("05_selection", x).message_ko for x in sel2.warnings]
    assert any(m.startswith("선정 지표가 자격선 안에 드는 종목이 2개(필수 포함 1개 별도)라 목표 4개를") and "자격선 밖 6개 제외: DDOG -5.8%" in m
               and "PLTR -1.8% 외 1개)" in m and m.endswith("선정한 3종목에 투자금을 나눠 담습니다.") for m in msgs)  # fmt: skip
    assert any("선정 지표가 자격선 밖(ROE -0.045%, 자격선 0% 초과" in m for m in msgs)


def test_metric_value_ko_keeps_sign_of_tiny_values():
    from backend.analysis.common.warnings import metric_value_ko

    assert metric_value_ko("roe_ttm", -0.0004533) == "-0.045%" and metric_value_ko("roe_ttm", -0.058) == "-5.8%"
    assert metric_value_ko("return_12m_1m", 0.0004) == "+0.04%" and metric_value_ko("dividend_yield_ttm", 0.00004) == "0.004%"
    assert metric_value_ko("roe_ttm", 0.0) == "0.0%" and metric_value_ko("pe_ttm", float("nan")) == "자료 없음" and metric_value_ko("pe_ttm", 734.0) == "734.0배"


def test_forced_names_below_candidate_filters_get_a_notice():
    """018: 필수 포함은 최소 시가총액·거래대금 필터를 건너뛰는데(정책) 알리지 않았다 — 시작일 033780.KS 시가총액 76억 달러 < 최소 100억 달러."""
    from backend.analysis.executor.stages import _forced_filter_notes

    cand = {"candidates": [{"ticker": "033780.KS", "forced": True, "market_cap_usd": 7600055223.18, "adv_usd": 19303441.0},
                           {"ticker": "105560.KS", "forced": True, "market_cap_usd": 14993862231.0, "adv_usd": 43093949.0},
                           {"ticker": "055550.KS", "forced": False, "market_cap_usd": 13596126078.6, "adv_usd": 29657600.0},
                           {"ticker": "X", "forced": True, "market_cap_usd": None, "adv_usd": 5e6},
                           {"ticker": "Y", "forced": True, "market_cap_usd": 1e9, "adv_usd": 1e6}]}  # fmt: skip  (Y: 선정되지 않음 → 알리지 않는다)
    cons = {"min_market_cap_usd": 1e10, "min_avg_daily_volume_usd": 1e7}
    notes = _forced_filter_notes(cand, cons, {"033780.KS", "105560.KS", "055550.KS", "X"})
    assert notes == ["must_include 033780.KS: below candidate filters (market cap 7600055223 < 10000000000 USD), kept",
                     "must_include X: below candidate filters (market cap n/a < 10000000000 USD; avg daily volume 5000000 < 10000000 USD), kept"]  # fmt: skip
    w = from_text("07_backtest_spec", f"screen@2023-07-17: {notes[0]}")
    assert w.code == "must_include_below_filters" and w.level == "user" and w.details["key"] == "033780.KS"
    assert w.message_ko == "백테스트 시작일(2023-07-17) 기준: 필수 포함 종목 033780.KS은(는) 후보 조건을 채우지 못했지만(시가총액 76억 달러, 최소 100억 달러) 요청에 따라 포함했습니다."
    assert "(시가총액 자료 없음, 최소 100억 달러 · 하루 평균 거래대금 500만 달러, 최소 1,000만 달러)" in from_text("05_selection", notes[1]).message_ko
    assert _forced_filter_notes(cand, {}, {"033780.KS", "X"}) == []  # 조건을 정하지 않았으면 알릴 것도 없다


def test_selection_and_start_spec_stages_emit_forced_filter_notices(monkeypatch, tmp_path):
    """05(기준일 후보 값)·07(시작일 재선정 후보 값) 모두 선정된 필수 포함만 알리고, 07 은 시작일을 붙인다."""
    from backend.analysis.executor import stages
    from backend.analysis.executor.context import RunContext
    from backend.analysis.schemas.selection import Selected, Selection

    req = {"request_id": "r", "derived": {"as_of": "2026-07-16"}, "constraints": {"min_market_cap_usd": 1e10, "min_avg_daily_volume_usd": 1e7}}
    sel = Selection(request_id="r", as_of=dt.date(2026, 7, 16), summary={"metric": "dividend_yield_ttm"},
                    selected=[Selected(ticker="F", name="F", sector="Financials", sector_code="40", rank=1, metric_name="dividend_yield_ttm", metric_value=0.03, forced=True)])  # fmt: skip
    monkeypatch.setattr(stages, "screen", lambda *a, **k: (sel, []))
    ctx = RunContext("run_t", req, None, SimpleNamespace(view=lambda d: SimpleNamespace(as_of=d)), None, AnalysisSettings(), tmp_path)
    ctx.outputs.update({"02_intent": {}, "03_candidates": {"candidates": [{"ticker": "F", "forced": True, "market_cap_usd": 9e9, "adv_usd": 5e7}]},
                        "04_tagging": {"request_id": "r", "min_confidence": 0.5, "tagged": [], "excluded_by_theme": [], "passed_tickers": ["F"], "batches": 0}})  # fmt: skip
    stages.st_selection(ctx)
    assert ctx.out("05_selection")["warnings"] == ["must_include F: below candidate filters (market cap 9000000000 < 10000000000 USD), kept"]
    w5 = next(w for w in ctx.warnings if w.code == "must_include_below_filters")
    assert w5.stage == "05_selection" and w5.message_ko.startswith("필수 포함 종목 F은(는) 후보 조건을 채우지 못했지만(시가총액 90억 달러, 최소 100억 달러)")

    spec = {"period": {"start": "2023-07-17", "end": "2026-07-16", "as_of": "2023-07-17"}, "selection": {"tickers": ["F"]}, "benchmark": "SPY", "warnings": []}
    extras = {"candidates_bt": {"candidates": [{"ticker": "F", "forced": True, "market_cap_usd": 7.6e9, "adv_usd": 5e6}]}}
    monkeypatch.setattr(stages, "build_backtest_spec", lambda *a, **k: (spec, extras))
    stages.st_backtest_spec(ctx)
    w7 = [w for w in ctx.warnings if w.stage == "07_backtest_spec"]
    assert [w.code for w in w7] == ["must_include_below_filters"] and w7[0].message_ko == (
        "백테스트 시작일(2023-07-17) 기준: 필수 포함 종목 F은(는) 후보 조건을 채우지 못했지만(시가총액 76억 달러, 최소 100억 달러 · 하루 평균 거래대금 500만 달러, "
        "최소 1,000만 달러) 요청에 따라 포함했습니다.")  # fmt: skip
    assert ctx.out("07_backtest_spec")["warnings"][0].startswith("screen@2023-07-17: must_include F: below candidate filters")


def test_explain_rows_follow_metric_rank_with_unranked_forced_last():
    """019: 06 행을 선정 순서(필수 포함 → 섹터 선호)로 넘겨 LLM 이 첫 칸 대신 줄을 세어 20종목 중 13개 ROE 순위를 틀렸다('21위')."""
    from backend.analysis.m3_selection.explain import explain
    from backend.analysis.schemas.selection import Selected

    def row(t, rank, v, forced=False):
        return Selected(ticker=t, name=t, sector="Information Technology", sector_code="45", rank=rank, metric_name="roe_ttm", metric_value=v, forced=forced)

    sel = SimpleNamespace(request_id="r", summary={"metric": "roe_ttm", "direction": "desc", "as_of": "2023-09-15"},
                          selected=[row("MUST", 1, float("nan"), True), row("MSFT", 2, 0.34, True), row("AAPL", 3, 1.488), row("TXN", 4, 0.352),
                                    row("AMZN", 5, 0.306), row("NVDA", 6, 1.172)])  # fmt: skip
    seen = {}

    class Llm:
        def complete_json(self, stage, messages, validator=None):
            seen["user"] = messages[-1]["content"]
            return {"portfolio_summary_ko": "s", "per_ticker": []}

    explain(sel, SimpleNamespace(tagged=[]), {"interpretation": {"summary_ko": "s"}, "report_settings": {"explanation_level": "beginner"}}, Llm(), facts=[])
    rows = [ln.split(" | ")[:2] for ln in seen["user"].splitlines() if " | " in ln and not ln.startswith("##")]
    assert rows == [["1", "AAPL"], ["2", "NVDA"], ["3", "TXN"], ["4 (필수 포함)", "MSFT"], ["5", "AMZN"], ["– (필수 포함)", "MUST"]]


def test_next_rebalance_hit_leaves_short_final_window_pending():
    """020: 연 1회 리밸런싱의 마지막 뷰 4개를 종료일까지 8거래일로 채점해 '다음 리밸런싱까지 43.8%' (12개월 지표는 같은 뷰를 판정 보류).
    다음 리밸런싱일이 창 안에 없는 마지막 창이 min(20거래일, 리밸런싱 간격) 보다 짧으면 판정 보류."""
    from backend.analysis.m5_backtest_report.backtest_metrics import view_diagnostics_next_window

    dates = pd.bdate_range("2024-01-01", periods=61)
    px = pd.DataFrame({"A": np.linspace(100, 130, 61), "B": np.linspace(100, 90, 61)}, index=dates)

    def vs():
        return [{"type": "relative", "long": ["A"], "short": ["B"], "expected_return_annual": 0.1, "summary_ko": "A>B"}]

    def run(rb_idx: list[int], view_idx: list[int]):
        return view_diagnostics_next_window({str(dates[i].date()): vs() for i in view_idx}, px, [dates[i] for i in rb_idx], dates[-1], {}, {})

    out = run([25, 53], [0, 25, 53])  # 간격 25·28 → 기준 20거래일, 마지막 창 7거래일
    assert [o["hit"] for o in out] == [True, True, None] and [o["pending"] for o in out] == [False, False, True]
    assert out[-1]["window_end"] == str(dates[-1].date()) and out[-1]["realized"] is not None
    hits = [o["hit"] for o in out if o["hit"] is not None]
    assert np.mean(hits) == 1.0  # backtest.evaluate 의 view_hit_ratio_next_rb 도 판정 보류를 뺀다
    assert [o["hit"] for o in run([25], [0, 25])] == [True, True]  # 마지막 창 35거래일 ≥ 20 → 판정
    two_weeks = list(range(10, 61, 10))  # 2주 간격(10거래일): 기준이 간격으로 내려가 10거래일 마지막 창은 판정, 9거래일이면 보류
    assert run(two_weeks, [0, *two_weeks[:-1]])[-1]["pending"] is False
    assert run([10, 20, 30, 40, 51], [0, 10, 20, 30, 40, 51])[-1]["pending"] is True


def _comp_and_checks(w: pd.DataFrame, stock_cap: float, sector_cap: float):
    from backend.analysis.m5_backtest_report.backtest_metrics import composition_metrics
    from backend.analysis.m5_backtest_report.validate import evaluate_checks

    sectors = {"A": "Information Technology", "B": "Information Technology", "C": "Health Care"}
    idx = w.index
    tgt = dict(w.iloc[0])
    comp = composition_metrics(w, pd.DataFrame(1.0, index=idx, columns=w.columns), tgt, sectors, stock_cap, sector_cap, 0.25, pd.Series(1.0, index=idx))
    p = {"id": "x", "kind": "template", "target_weights": tgt,
         "metrics": {"risk": {"max_drawdown": -0.1, "ann_vol": 0.1}, "return": {"cagr": 0.1, "total_return": 0.2}, "vs_benchmark": {"excess_cagr": 0.01},
                     "composition": comp, "trading": {"n_rebalances": 2}},  # 시작일 매수 + 리밸런싱 1회 (1 이면 매수 후 보유 문구, 037)
         "series": {"index": [100.0] * len(idx)}, "checkpoints": [{"kind": "rebalance", "weights": {"after": tgt}}]}  # fmt: skip
    crit = {"max_drawdown": 0.2, "benchmark": "SPY", "target_annual_return": 0.05, "volatility_preference": "high", "vol_band": 9.99,
            "max_weight_per_stock": stock_cap, "max_weight_per_sector": sector_cap}  # fmt: skip
    cks, *_ = evaluate_checks(p, crit, len(idx), 1, lambda t: sectors[t], 0.25, settings=AnalysisSettings())
    return comp, {c["rule"]: c for c in cks}


def test_drift_rules_state_the_real_max_weight_against_cap_and_tolerance():
    """019·020·021·022: 정보기술 63.1%(상한 55%), 금융 778거래일 중 501일 73% 초과인데 '리밸런싱 사이 섹터 비중이 상한 안에 머묾' — 허용 폭(상한의 1.25배)만 봤다.
    판정은 그대로(허용 폭을 넘었나), 문구와 값은 실제 최대 비중으로."""
    idx = pd.bdate_range("2024-01-01", periods=5)
    w = pd.DataFrame({"A": [0.30, 0.33, 0.36, 0.30, 0.31], "B": [0.30] * 5, "C": [0.40, 0.37, 0.34, 0.40, 0.39]}, index=idx)
    comp, ck = _comp_and_checks(w, 0.35, 0.60)
    assert comp["max_sector_weight"] == pytest.approx(0.66) and comp["max_sector_weight_sector"] == "Information Technology" and comp["days_above_sector_cap"] == 3
    assert comp["max_stock_weight"] == pytest.approx(0.40) and comp["max_stock_weight_ticker"] == "C" and comp["days_above_stock_cap"] == 5 and comp["n_days"] == 5
    r5b, r4b = ck["R5b"], ck["R4b"]
    assert r5b["status"] == "info" and r5b["ok"] and r5b["value"] == pytest.approx(0.66) and r5b["threshold"] == pytest.approx(0.75)
    assert r5b["message_ko"] == "리밸런싱 사이 최대 섹터 비중 66.0%(정보기술) — 상한 60%를 넘은 섹터가 있던 날이 5거래일 중 3일 있었지만 허용 폭(상한의 1.25배, 75.0%) 안"
    assert r4b["message_ko"] == "리밸런싱 사이 최대 종목 비중 40.0%(C) — 상한 35%를 넘은 종목이 있던 날이 5거래일 중 5일 있었지만 허용 폭(상한의 1.25배, 43.8%) 안"
    # 허용 폭을 넘으면 예전처럼 ok=False (정보 규칙) + 넘은 종목
    w2 = w.copy()
    w2.loc[idx[2], "A"] = 0.45
    _, ck2 = _comp_and_checks(w2, 0.35, 0.80)
    assert not ck2["R4b"]["ok"] and ck2["R4b"]["status"] == "info" and ck2["R4b"]["message_ko"] == (
        # 031: 상한을 넘은 날과 허용 폭을 넘은 날을 따로 센다 (예전 문구 '…5일이고 허용 폭도 넘음' 을 서술이 '허용 폭을 넘은 날 5일' 로 읽었다)
        "리밸런싱 사이 최대 종목 비중 45.0%(A) — 상한 35%를 넘은 종목이 있던 날이 5거래일 중 5일, 허용 폭(상한의 1.25배, 43.8%)을 넘은 종목이 있던 날은 1일 (A). 리밸런싱 주기를 줄이면 완화됩니다")
    assert ck2["R5b"]["message_ko"] == "리밸런싱 사이 최대 섹터 비중 75.0%(정보기술) — 상한 80% 안에 머묾"
    # 최대 비중이 없는 예전 결과는 예전 문구
    from backend.analysis.m5_backtest_report.validate import _drift_msg_ko

    assert _drift_msg_ko("sector", {"breaches": [], "max_sector_drift": 0.01}, 0.6, 0.25, []) == "리밸런싱 사이 섹터 비중이 상한 안에 머묾"


def test_walkforward_news_bl_label_says_walkforward(monkeypatch, tmp_path):
    """021: wf_bl_news 의 title_ko '뉴스 근거 뷰' 때문에 표 라벨이 '뉴스 뷰: 뉴스 근거 뷰' 라 시작일 시나리오처럼 읽혔다 → 다른 wf_ 안처럼 '(walk-forward)'."""
    from backend.analysis.executor import stages
    from backend.analysis.executor.context import RunContext
    from backend.analysis.m5_backtest_report.report_blocks import pf_label

    d = dt.date(2024, 1, 2)
    applied = {"id": "wf_bl_2024-01-02_1", "weights": {"A": 0.6, "B": 0.4}, "active_constraints": [],
               "views_applied": [{"type": "absolute", "long": ["A"], "short": [], "expected_return_annual": 0.1, "summary_ko": "A 상승"}]}  # fmt: skip
    res = SimpleNamespace(market_model={"delta": 2.5, "delta_source": "fixed", "lookback": {}, "implied_returns": {}}, baselines={"portfolios": []},
                          evidence_summary=lambda: None, evidence=None, warnings=[], bl_portfolios=[applied], view_sets=[{"narrative_ko": "n"}],
                          baseline_weights={"A": 0.5, "B": 0.5}, applied_bl=[applied], fallback=False, fallback_reason_ko="")  # fmt: skip
    monkeypatch.setattr(stages, "construct", lambda *a, **k: res)
    monkeypatch.setattr(stages, "trade_schedule", lambda md, spec, settings: {"rb": [pd.Timestamp(d)]})
    ctx = RunContext("run_t", {"request_id": "r"}, None, SimpleNamespace(view=lambda x: SimpleNamespace(as_of=x)), None, AnalysisSettings(), tmp_path)
    ctx.outputs.update({"02_intent": {"news_tilt": {"enabled": True}}, "07_backtest_spec": {"selection": {"tickers": ["A", "B"]}}})
    stages.st_walkforward(ctx)
    ports = {p["id"]: p for p in ctx.out("10w_target_paths")["portfolios"]}
    assert pf_label(ports["wf_bl_news"]) == "뉴스 뷰 Black-Litterman (walk-forward)" and pf_label(ports["wf_equal_weight"]).endswith("(walk-forward)")


def test_forward_market_model_exports_how_delta_was_set(monkeypatch, tmp_path):
    """020: 기준일(10f) δ=3.375 는 시장 추정치가 음수라 하한 1.5 × 성향 1.5 × 낙폭 1.5 였는데, 10f 가 delta_market·delta_base 를 빼서 리포트가 설명할 수 없었다."""
    from backend.analysis.executor import stages
    from backend.analysis.executor.context import RunContext

    mm = {"as_of": "2025-01-14", "lookback": {}, "tickers": ["A"], "ann_vol": {"A": 0.2}, "cap_weights": {"A": 1.0}, "delta": 3.375, "delta_source": "market_implied",
          "tau": 0.05, "implied_returns": {"A": 0.05}, "delta_capped": False, "delta_market": -0.4213, "delta_base": 1.5, "delta_multiplier": 1.5, "delta_dd_multiplier": 1.5}  # fmt: skip
    res = SimpleNamespace(market_model=mm, evidence=None, baselines={"chosen_baseline": "equal_weight", "portfolios": []}, applied_bl=[], baseline_weights={"A": 1.0},
                          view_sets=[], chosen_weights={"A": 1.0}, fallback=True, fallback_reason_ko="", params=None, warnings=[], bl_portfolios=[])  # fmt: skip
    monkeypatch.setattr(stages, "construct", lambda *a, **k: res)
    req = {"request_id": "r", "derived": {"as_of": "2025-01-14", "initial_amount_usd": 10_000, "fx_rate": 1.0, "fx_date": "2025-01-14"}}
    ctx = RunContext("run_t", req, None, SimpleNamespace(view=lambda x: SimpleNamespace(as_of=x)), None, AnalysisSettings(), tmp_path)
    ctx.outputs.update({"05_selection": {"selected": [{"ticker": "A"}]}, "02_intent": {}})
    stages.st_forward(ctx)
    out = ctx.out("10f_forward_portfolios")["market_model"]
    assert {k: out[k] for k in ("delta", "delta_market", "delta_base", "delta_multiplier", "delta_dd_multiplier", "delta_capped")} == {
        "delta": 3.375, "delta_market": -0.4213, "delta_base": 1.5, "delta_multiplier": 1.5, "delta_dd_multiplier": 1.5, "delta_capped": False}
