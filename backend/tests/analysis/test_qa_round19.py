"""2026-11 시나리오 QA 라운드 19 (061~065) 회귀 테스트."""

from __future__ import annotations

import datetime as dt
from types import SimpleNamespace

import pandas as pd

from backend.analysis.m5_backtest_report import report_blocks as B


def _R(cap: float = 0.10, floor: float = 0.01) -> dict:
    return {"request": {"constraints": {"max_weight_per_stock": cap}}, "parameters": {"portfolio": {"min_weight": floor}},
            "selection": {"table": [{"ticker": t, "name": t} for t in ("A", "B", "C", "SNDK")]}}  # fmt: skip


def test_stuck_view_uses_display_noise_and_bl_weight_for_the_floor():
    """063: SNDK 내림 뷰가 1.0153% → 최소 비중 1.00% 로 0.015%p 만 움직여 표에는 '변화 없음' 인데 1e-4 기준으로는 움직인 뷰라 최소 비중 설명이 없었다."""
    v = {"type": "absolute", "direction": "down", "long": ["SNDK"], "short": []}
    n, stuck, kinds = B._stuck_views([v], {"SNDK": 0.0100}, {"SNDK": 0.010153}, 0.10, 0.01)
    assert (n, stuck, kinds) == (1, {"SNDK": 1}, {"floor"})
    assert B._stuck_views([v], {"SNDK": 0.0090}, {"SNDK": 0.010153}, 0.10, 0.0)[0] == 0  # 0.1%p 움직였으면 바꾼 뷰


def test_stuck_note_says_all_names_sit_at_the_stock_cap():
    """062: 6종목 × 10% 라 시작일 BL 다섯 개가 뷰를 하나도 반영하지 못했는데 '상한·섹터 예산 같은 제약 때문' 이라고 썼다 (섹터는 30% 로 상한 50% 와 멂)."""
    w = {t: 0.10 for t in ("A", "B", "C")}
    p = {"weights": w, "delta_vs_baseline": {t: 0.0 for t in w}, "active_constraints": [],
         "views_applied": [{"type": "absolute", "direction": "down", "long": ["A"], "short": []},
                           {"type": "relative", "direction": None, "long": ["B"], "short": ["C"]}]}  # fmt: skip
    assert B.view_stuck_note(_R(), p) == "모든 종목이 종목당 상한(10%)에 걸려 있어 뉴스 뷰 2개가 비중을 바꿀 수 없었습니다 (기준 비중과 같음)"
    p2 = {**p, "weights": {"A": 0.10, "B": 0.08, "C": 0.10}, "delta_vs_baseline": {"A": 0.0, "B": 0.0, "C": 0.0}}  # 한 종목이라도 상한 아래면 예전 문구
    assert not B.view_stuck_note(_R(), p2).startswith("모든 종목이")


def test_soft_table_hides_an_empty_memo_row(monkeypatch):
    """061·062: '해석 메모' 줄이 빈 칸으로 보였다."""
    monkeypatch.setattr(B, "_tolerance_note", lambda R: "12.0%")
    R = {"intent": {"risk_params": {"volatility_preference": "low", "notes_ko": ""}, "news_tilt": {"enabled": False}}}
    assert [r["k"] for r in B.soft_table(R)["rows"]] == ["변동성 선호", "허용 최대낙폭·낙폭 맞춤안 목표", "뉴스 뷰 반영"]
    R["intent"]["risk_params"]["notes_ko"] = "손실 회피 성향이 강합니다."
    assert any(r["k"] == "해석 메모" and r["v"] for r in B.soft_table(R)["rows"])


def test_recommendation_reason_reaches_the_narrative_as_prose():
    """063·064: 14a 가 추천 사유 코드 문자열을 그대로 옮겨 ' · '·'vs' 가 서술에 남았고 '… USD.입니다' 로 끝났다."""
    from backend.analysis.m5_backtest_report.report import _plain_llm, reason_prose_ko

    r = "후보 16개 중 1위 · 목표수익(연 10.0%) 충족 · 최대낙폭 21.5% vs 허용 20.0% (1.5%p 초과) · Sharpe 1.26로 가장 높음 · CAGR 30.7%, 최종 평가금액 166,109 USD."
    assert reason_prose_ko(r) == ("후보 16개 중 1위, 목표수익(연 10.0%) 충족, 최대낙폭 21.5%(허용 20.0%보다 1.5%p 큼), Sharpe 1.26로 가장 높음, "
                                  "CAGR 30.7%, 최종 평가금액 166,109 USD")  # fmt: skip
    assert "여유 2.0%p" in reason_prose_ko("최대낙폭 10.0% vs 허용 12.0% (여유 2.0%p) · CAGR 5.0%, 최종 평가금액 1 USD.")
    assert _plain_llm("최종 평가금액 525,170 USD.입니다. 초과 1.5%p.") == "최종 평가금액 525,170 USD입니다. 초과 1.5%p."


def test_next_rebalance_hit_note_gives_the_true_reason():
    """061: 매수 후 보유라 리밸런싱이 시작일 하루뿐이었고 그날 뷰는 비중을 바꿨는데 '뷰가 비중을 바꾼 날이 없어' 라고 했다."""
    from backend.analysis.m5_backtest_report.report import _news_effect_display

    base = {"disabled": False, "hit_next_rb": None, "bl_cagr": None, "base_cagr": None}
    assert _news_effect_display({**base, "n_rebalances": 1, "n_dates": 1})["hit_next_rb_note"].startswith("시작 뒤 리밸런싱이 없어")
    assert _news_effect_display({**base, "n_rebalances": 12, "n_dates": 0})["hit_next_rb_note"].startswith("뷰가 비중을 바꾼 날이 없어")
    assert _news_effect_display({**base, "n_rebalances": 12, "n_dates": 3})["hit_next_rb_note"].startswith("다음 리밸런싱까지의 구간이")


def test_broad_dividend_theme_drops_names_without_dividends(monkeypatch):
    """061: '배당을 꾸준히 늘려 온 기업 중 덜 흔들리는 종목' 을 저변동성 순으로만 골라 배당이 없는 BRK-B·WBD 가 들어갔는데 리포트는 '배당 기업' 이라고 불렀다.
    넓은 배당 테마이고 선정 지표가 배당이 아니면 배당을 확인한 종목만 고른다 — 팀 DB 배당 자료(> 0)가 있으면 그것으로, 없으면 기준일 테마 판정으로
    (자료만 보면 AME·TRV 같은 배당 기업이 빠졌다). 자료가 0 이면 판정보다 앞선다. 필수 포함은 유지."""
    from backend.analysis.common.warnings import from_text
    from backend.analysis.m2_data import metrics as Mx
    from backend.analysis.m3_selection.screen import screen

    vol = {"JNJ": 0.10, "BRK-B": 0.11, "WBD": 0.12, "TRV": 0.13, "DAL": 0.14, "PG": 0.15, "ABT": 0.16}
    div = {"JNJ": 0.03, "PG": 0.025, "DAL": 0.0}  # BRK-B·WBD·TRV·ABT 는 배당 자료 없음, DAL 은 그날 배당 0
    monkeypatch.setitem(Mx.METRICS, "vol_60d", lambda view, tks: (pd.Series({t: vol[t] for t in tks}, dtype=float), []))
    monkeypatch.setitem(Mx.METRICS, "dividend_yield_ttm", lambda view, tks: (pd.Series({t: div[t] for t in tks if t in div}, dtype=float), []))
    monkeypatch.setattr("backend.analysis.m3_selection.screen.D.gics_model",
                        lambda e: SimpleNamespace(sector=SimpleNamespace(code=e["ticker"], name=e["ticker"])))  # fmt: skip
    desc = SimpleNamespace(by_ticker=lambda t: {"ticker": t, "name": t, "market": "US", "gics": {}})
    intent = {"screen": {"metric": "vol_60d", "direction": "asc"},
              "interpretation": {"themes": [{"id": "us_dividend_companies", "label_ko": "업종 제한 없는 미국 배당 기업"}]}}  # fmt: skip
    cons = {"num_holdings": {"min": 1, "target": 7, "max": 7}, "max_weight_per_stock": 1.0, "max_weight_per_sector": 1.0, "min_cash_ratio": 0.0,
            "must_include_tickers": ["WBD"]}  # fmt: skip
    judged = {"JNJ": (True, 0.9), "BRK-B": (False, 0.0), "WBD": (False, 0.15), "TRV": (True, 0.95), "DAL": (True, 0.9), "PG": (True, 0.9)}  # ABT 는 판정 없음
    tag = SimpleNamespace(tagged=[SimpleNamespace(ticker=t, in_theme=a, confidence=c) for t, (a, c) in judged.items()], passed_tickers=list(vol),
                          theme_filter_applied=False, min_confidence=0.5)  # fmt: skip
    day = SimpleNamespace(as_of=dt.date(2026, 6, 22))
    sel, _ = screen(day, desc, tag, intent, cons, request_id="r")
    # BRK-B(자료 없음·판정 아님)·DAL(그날 배당 0)·ABT(자료 없음·판정 없음)는 빠지고, TRV(자료 없음·판정 배당 기업)·필수 포함 WBD 는 남는다
    assert sorted(s.ticker for s in sel.selected) == ["JNJ", "PG", "TRV", "WBD"]
    assert {r.ticker: r.reason for r in sel.rejected} == {"BRK-B": "no_dividend", "DAL": "no_dividend", "ABT": "no_dividend"}
    assert sel.summary["n_no_dividend"] == 3
    w = from_text("05_selection", next(x for x in sel.warnings if x.startswith("dividend theme:")))
    assert w.code == "no_dividend_dropped" and "3개(BRK-B, DAL, ABT)" in w.message_ko
    # 시작일 재선정: 그날 판정이 없어도 기준일 판정(theme_ok)으로 배당 기업을 확인한다
    bare = SimpleNamespace(tagged=[], passed_tickers=list(vol), theme_filter_applied=False, min_confidence=0.0)
    sel_bt, _ = screen(day, desc, bare, intent, cons, request_id="r", theme_ok=["TRV", "ABT", "DAL"])
    assert sorted(s.ticker for s in sel_bt.selected) == ["ABT", "JNJ", "PG", "TRV", "WBD"]  # DAL 은 그날 배당 0 이라 판정보다 자료가 앞선다
    # 좁은 테마(테마 판정이 거른다)·배당과 무관한 넓은 테마는 그대로
    for t2, it2 in ((SimpleNamespace(**{**tag.__dict__, "theme_filter_applied": True}), intent),
                    (tag, {**intent, "interpretation": {"themes": [{"id": "broad_us", "label_ko": "미국 대형주"}]}})):
        sel2, _ = screen(day, desc, t2, it2, cons, request_id="r")
        assert "BRK-B" in {s.ticker for s in sel2.selected}


def test_partial_first_and_last_years_are_named():
    """063: 1~10월만인 2026년 19.5% 를 한 해 수익률처럼 썼다."""
    from backend.analysis.m5_backtest_report.report import _partial_years_note

    def note(start, end, years):
        return _partial_years_note({"backtest": {"period": {"start": start, "end": end}}}, {"yearly_returns": {y: 0.1 for y in years}})

    assert note("2023-10-09", "2026-10-09", ["2023", "2024", "2025", "2026"]) == "2023년은 2023-10-09부터 · 2026년은 2026-10-09까지의 일부 기간 수익률 (한 해 전체가 아님)"
    assert note("2024-03-01", "2024-11-01", ["2024"]) == "2024년은 2024-03-01~2024-11-01의 일부 기간 수익률 (한 해 전체가 아님)"
    assert note("2021-01-04", "2023-12-29", ["2021", "2022", "2023"]) is None


def test_equal_top_weights_are_named_for_the_narrative():
    """061·065: 시작일 최대 비중이 15.0% 로 같은 규칙이 둘인데 14b 가 '서로 다릅니다' 라고 썼다."""
    from backend.analysis.m5_backtest_report.report import _same_top_note

    rows = [{"name": "동일비중", "top": 0.0667}, {"name": "시가총액비중", "top": 0.15}, {"name": "역변동성비중", "top": 0.083}, {"name": "최소분산", "top": 0.15}]
    assert _same_top_note(rows) == {"top_weight_same_ko": "시가총액비중·최소분산는 둘 다 15.0% — 같은 값이 있으니 '서로 다르다' 고 쓰지 않음"}
    assert _same_top_note(rows[:3]) == {}


def test_company_card_column_name_does_not_leak():
    """062: 기업 카드가 입력 표의 칸 이름을 옮겨 '판정 테마인 미국 유틸리티에 해당합니다' 라고 썼다."""
    from backend.analysis.m3_selection.explain import _no_column_name

    assert _no_column_name("Sempra는 판정 테마인 미국 유틸리티에 해당합니다.") == "Sempra는 미국 유틸리티 테마에 해당합니다."
    assert _no_column_name("판정 테마는 미국 유틸리티입니다.") == "테마는 미국 유틸리티입니다."


def test_invested_gap_note_when_backtest_held_much_more_cash(monkeypatch):
    """062: 시작일 6종목 × 상한 10% 라 백테스트는 주식 60%·현금 40% 였는데 지금 구성은 주식 90% — '손실 감내 수준에 맞다' 고만 했다."""
    p = {"id": "market_cap", "target_weights": {t: 0.10 for t in "ABCDEF"}}
    monkeypatch.setattr(B, "find", lambda R, pid: p)
    monkeypatch.setattr(B, "current_composition", lambda R, chosen: ({t: 0.09 for t in "ABCDEFGHIJ"}, 0.10, "시가총액비중"))
    assert B.invested_gap_note({}, "market_cap") == ("백테스트는 주식 60%·현금 40%로 시작해 최대낙폭·변동성이 그 현금만큼 낮게 나왔습니다. "
                                                     "지금 구성은 주식 90%라 같은 흐름이면 손실 폭이 백테스트보다 클 수 있습니다")  # fmt: skip
    monkeypatch.setattr(B, "current_composition", lambda R, chosen: ({t: 0.065 for t in "ABCDEFGHIJ"}, 0.35, "시가총액비중"))
    assert B.invested_gap_note({}, "market_cap") is None  # 5%p 차이는 말하지 않는다


def test_company_news_counts_use_the_analysis_date_window_only(monkeypatch):
    """062: 백테스트 종목은 walk-forward 날짜마다 근거 창이 있어 NEE '140건 뉴스' vs WELL 10건 — 기준일 창만 보면 NEE 도 10건."""
    idx = {"ev1": {"kind": "news", "tickers": ["NEE"], "window_as_of": "2026-05-06"},
           "ev2": {"kind": "news", "tickers": ["NEE"], "window_as_of": "2024-05-06"},
           "dc1": {"kind": "disclosure", "tickers": ["NEE"], "window_as_of": "2026-05-06"}}  # fmt: skip
    table = [{"ticker": "NEE", "name": "NextEra", "sector": "Utilities", "in_selection_now": True, "rank_now": 1, "metric_now": 0.1, "in_backtest": True,
              "rank_backtest": 1, "metric_backtest": 0.1}]  # fmt: skip
    R = {"evidence_index": idx, "selection": {"table": table, "as_of_now": {"as_of": "2026-05-06"}, "backtest_as_of": {"as_of": "2023-05-08"},
                                              "metric": "vol_60d", "direction": "asc", "explained": {}, "tagging_summary": {"theme_filter_applied": True}}}  # fmt: skip
    monkeypatch.setattr(B, "find", lambda R, pid: {"id": pid, "target_weights": {"NEE": 0.1}})
    monkeypatch.setattr(B, "current_composition", lambda R, chosen: ({"NEE": 0.1}, 0.9, "x"))
    item = B.companies(R, "x")["items"][0]
    assert (item["n_news"], item["n_disclosures"]) == (1, 1)
