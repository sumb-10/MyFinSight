"""2026-11 시나리오 QA 라운드 21 (071~075) 회귀 테스트."""

from __future__ import annotations

import pandas as pd

from backend.analysis.m5_backtest_report import report_blocks as B


def _R(cap: float = 0.25) -> dict:
    return {"request": {"constraints": {"max_weight_per_stock": cap}}, "parameters": {"portfolio": {"min_weight": 0.01}},
            "selection": {"table": [{"ticker": "GDDY", "name": "GoDaddy"}, {"ticker": "GOOGL", "name": "Alphabet"}, {"ticker": "RDDT", "name": "Reddit"}]}}  # fmt: skip


def test_each_stuck_stock_gets_the_limit_of_its_own_leg():
    """071·075: 'GOOGL > GDDY' 처럼 상대 뷰 하나의 이유('both')를 두 종목 모두에 붙여 GoDaddy(1%)에 '종목당 상한 25%', Alphabet(25%)에 '최소 비중 1%' 를 적고
    같은 이유를 두 번 적었다. 오른 쪽은 상한, 내린 쪽은 최소 비중을 본다."""
    p = {"views_applied": [{"type": "absolute", "direction": "down", "long": ["GDDY"], "short": []},
                           {"type": "relative", "long": ["GOOGL"], "short": ["GDDY"]},
                           {"type": "absolute", "direction": "up", "long": ["GOOGL"], "short": []},
                           {"type": "absolute", "direction": "up", "long": ["X"], "short": []}],
         "weights": {"GDDY": 0.01, "GOOGL": 0.25, "X": 0.2}, "delta_vs_baseline": {"GDDY": 0.0, "GOOGL": 0.0, "X": 0.05}, "active_constraints": []}  # fmt: skip
    note = B.view_stuck_note(_R(), p)
    assert note.endswith("(GoDaddy: 최소 비중 1%, Alphabet: 종목당 상한 25%) (기준 비중과 같음)") or note.endswith("(Alphabet: 종목당 상한 25%, GoDaddy: 최소 비중 1%) (기준 비중과 같음)")
    assert note.count("종목당 상한 25%") == 1


def test_drift_days_are_given_per_stock_and_tolerance_breaches_ignore_noise():
    """071·073: '상한 15%를 넘은 종목이 있던 날 57일' 을 서술이 APP 의 날로 옮겼다(APP 36일·NVDA 21일). 071: META 는 허용 폭을 0.049%p 만 넘었는데
    '허용 폭을 넘은 종목(GOOGL, META)' — 같은 잡음 기준(0.05%p)으로 거른다."""
    from backend.analysis.m5_backtest_report.backtest_metrics import composition_metrics
    from backend.analysis.m5_backtest_report.validate import _drift_msg_ko

    idx = pd.bdate_range("2024-01-01", periods=4)
    w = pd.DataFrame({"APP": [0.10, 0.17, 0.19, 0.10], "NVDA": [0.16, 0.10, 0.10, 0.10], "META": [0.10, 0.10, 0.1254, 0.10]}, index=idx)
    sectors = {"APP": "Information Technology", "NVDA": "Information Technology", "META": "Communication Services"}
    comp = composition_metrics(w, pd.DataFrame(1.0, index=idx, columns=w.columns), dict(w.iloc[0]), sectors, 0.10, 1.0, 0.25, pd.Series(1.0, index=idx))
    assert comp["days_above_stock_cap_by"] == {"APP": 2, "NVDA": 1, "META": 1} and comp["days_above_stock_cap"] == 3
    assert comp["breaches"] == ["stock_cap:APP", "stock_cap:NVDA"]  # META 0.1254 는 허용 폭 12.5% 를 잡음 기준 안에서만 넘음
    from backend.analysis.m5_backtest_report.backtest_metrics import COMPOSITION_KEYS

    assert {"days_above_stock_cap_by", "days_above_sector_cap_by"} <= set(COMPOSITION_KEYS) <= set(comp)  # 결과에 남는다 (처음에는 목록에 없어 버려졌다)
    msg = _drift_msg_ko("stock", comp, 0.10, 0.25, ["APP", "NVDA"])
    assert "상한 10%를 넘은 종목이 있던 날이 4거래일 중 3일 (APP 2일, NVDA 1일, META 1일)" in msg


def test_walkforward_stuck_note_reads_view_direction_holds_from_10w():
    """073·075: 날짜별 '뷰 방향 유지' 경계는 10w 구성에만 있고 백테스트 결과에는 없어 Q-272 가 실제 실행에서 한 번도 보이지 않았다."""
    views = {"2023-07-21": [{"type": "absolute", "direction": "up", "long": ["AVGO"], "short": []}]}
    bw = {"2023-07-21": {"AVGO": 0.0996, "B": 0.5}}
    sw = {"2023-07-21": {"AVGO": 0.0996, "B": 0.5}}
    head = {"cagr": 0.1, "excess_cagr": 0.0, "max_drawdown": -0.1}
    R = {"backtest": {"portfolios": [{"id": "wf_bl_news", "kind": "black_litterman", "views_by_date": views, "weights_by_date": bw, "headline": head},
                                     {"id": "wf_market_cap", "kind": "template", "weights_by_date": sw, "headline": head}], "period": {}},
         "portfolio": {"targets": {"baseline": {"id": "market_cap"}},
                       "walkforward": {"portfolios": [{"id": "wf_bl_news", "holds_by_date": {"2023-07-21": ["AVGO"]}}]}},
         "request": {"constraints": {"max_weight_per_stock": 0.15}}, "intent": {"news_tilt": {"enabled": True}},
         "selection": {"table": [{"ticker": "AVGO", "name": "Broadcom"}]}}  # fmt: skip
    assert "뷰 방향 유지" in B.news_effect(R)["capped_note_ko"]


def test_company_card_counts_include_evidence_the_card_cites(monkeypatch):
    """073: INTC 카드가 공시 [dc151826](기업 설명용 90일 창)을 인용했는데 건수는 뉴스 뷰 창 기준이라 '0건 공시' 였다."""
    idx = {"ev1": {"kind": "news", "tickers": ["INTC"], "window_as_of": "2026-07-21"}, "dc151826": {"kind": "disclosure", "tickers": ["INTC"], "window_as_of": "2026-07-21"}}
    fw = {"window": ["2026-07-07", "2026-07-21"], "disclosure_window": ["2026-06-06", "2026-07-21"]}
    R = {"evidence_index": idx,
         "portfolio": {"forward": {"news_window": fw}, "news_windows": [{"as_of": "2026-07-21", **fw, "tickers": {"INTC": ["ev1"]}, "tickers_dc": {"INTC": []}}]},
         "selection": {"table": [{"ticker": "INTC", "name": "Intel", "sector": "Information Technology", "in_selection_now": True, "rank_now": 1, "metric_now": 0.1,
                                  "in_backtest": True, "rank_backtest": 1, "metric_backtest": 0.1}],
                       "as_of_now": {"as_of": "2026-07-21"}, "backtest_as_of": {"as_of": "2023-07-21"}, "metric": "return_12m_1m", "direction": "desc",
                       "explained": {"per_ticker": [{"ticker": "INTC", "rationale_ko": "실적 발표 공시가 있었다 [dc151826]"}]}, "tagging_summary": {"theme_filter_applied": True}}}  # fmt: skip
    monkeypatch.setattr(B, "find", lambda R, pid: {"id": pid, "target_weights": {"INTC": 0.1}})
    monkeypatch.setattr(B, "current_composition", lambda R, chosen: ({"INTC": 0.1}, 0.9, "x"))
    item = B.companies(R, "x")["items"][0]
    assert (item["n_news"], item["n_disclosures"]) == (1, 1)


def test_market_section_filings_come_from_the_view_window():
    """074: 시장 분석이 기업 설명용 90일 공시(73건)를 써서 같은 리포트의 '공시 창 07-04~08-17, 52건' 과 달랐다."""
    from backend.analysis.m5_backtest_report.report import _asof_news

    idx = {"dc1": {"kind": "disclosure", "tickers": ["A"], "window_as_of": "2026-08-18"}, "dc2": {"kind": "disclosure", "tickers": ["A"], "window_as_of": "2026-08-18"},
           "ev1": {"kind": "news", "tickers": ["A"], "window_as_of": "2026-08-18"}}  # fmt: skip
    fw = {"window": ["2026-08-04", "2026-08-18"], "disclosure_window": ["2026-07-04", "2026-08-18"]}
    R = {"evidence_index": idx, "selection": {"as_of_now": {"as_of": "2026-08-18"}},
         "portfolio": {"forward": {"news_window": fw}, "news_windows": [{"as_of": "2026-08-18", **fw, "tickers": {"A": ["ev1"]}, "tickers_dc": {"A": ["dc2"]}}]}}  # fmt: skip
    _w, news, discl = _asof_news(R)
    assert [d["id"] for d in discl] == ["dc2"] and [n["id"] for n in news] == ["ev1"]
    del R["portfolio"]["forward"]  # 창을 모르면 예전처럼 기준일 창 전체
    assert len(_asof_news(R)[2]) == 2


def test_sector_cap_squeeze_is_explained_without_sector_preference(monkeypatch):
    """072: '동일비중' 인데 산업재 10종목만 3.5%(다른 종목 6.0%) — 섹터 선호를 건너뛰면(Q-189) 설명 상자도 사라졌다."""
    R = {"request": {"constraints": {"max_weight_per_sector": 0.35}},
         "portfolio": {"forward": {"templates": [{"id": "equal_weight", "constraints_applied": ["sector_cap:Industrials"]}]}},
         "selection": {"backtest_as_of": {"as_of": "2022-05-27"}, "as_of_now": {"as_of": "2025-05-27", "summary": {"sector_counts": {"Industrials": 10, "Financials": 2}}}}}  # fmt: skip
    monkeypatch.setattr(B, "chosen_portfolio_id", lambda R: ("dd_match_equal_weight", True))
    monkeypatch.setattr(B, "find", lambda R, pid: {"id": pid, "kind": "matched", "base_id": "equal_weight"})
    c = B.infeasibility_callout(R)
    assert c["title_ko"] == "섹터 상한이 비중을 누른 부분" and c["text_ko"].startswith("분석 기준일(2025-05-27) 구성(동일비중): 산업재 종목이 10개라 섹터 상한 35%를 나눠 가져(종목당 약 3.5%)")
    assert c["text_ko"].endswith("낙폭 맞춤안은 이 비중을 주식 비율만큼 함께 줄입니다.")


def test_parameters_table_omits_delta_when_no_news_view_bl_was_built():
    """072: 뉴스 끔·규칙 4개만 만든 실행의 계산 조건 표에 '위험회피 δ: 시장 내재 δ 0.3741 …'."""
    assert not B._any_bl({"portfolio": {"targets": {"portfolios": [{"kind": "template"}]}, "walkforward": {"portfolios": [{"kind": "template"}]}, "forward": {"portfolios": []}}})
    assert B._any_bl({"portfolio": {"forward": {"portfolios": [{"id": "fwd_bl_01"}]}}})


def test_contribution_residual_bar_shows_when_it_changes_the_rounded_total(monkeypatch):
    """072: 잔차 −0.046%p 를 빼 막대 합이 −6.1% 인데 '막대를 모두 더하면 기간 수익률 −6.2% 와 같습니다'."""
    p = {"ticker_contribution": {"A": -0.04, "B": -0.02106}, "metrics": {"composition": {"ticker_contribution_residual": -0.000459}}, "headline": {"period_return": -0.061519}}
    monkeypatch.setattr(B, "find", lambda R, pid: p)
    labels = [x["label"] for x in B.contribution_bar({}, "x")["items"]]
    assert labels[-1] == "거래비용 등"
    p["headline"]["period_return"] = -0.0611
    assert "거래비용 등" not in [x["label"] for x in B.contribution_bar({}, "x")["items"]]  # 합이 그대로면 예전처럼 숨김


def test_filtered_candidates_are_listed_with_their_own_reasons():
    """073: 'Walmart와 같은 회사의 다른 주식인 Alphabet Class C' — 사유가 다른 두 종목을 한 구절로 이었다."""
    from backend.analysis.m5_backtest_report.report import _filtered_names_ko

    R = {"selection": {"candidates_filtered": [{"reason_ko": "테마 키워드가 약하게만 일치 (후보 검색 단계, 분석 모델 판정 전)", "count": 1, "examples": ["Walmart"]},
                                               {"reason_ko": "같은 회사의 다른 주식", "count": 1, "examples": ["Alphabet Inc. (Class C)"]}]}}  # fmt: skip
    assert _filtered_names_ko(R) == "Walmart: 테마 키워드가 약하게만 일치 / Alphabet Inc. (Class C): 같은 회사의 다른 주식"


def test_renamed_korean_companies_keep_their_former_names_for_headlines():
    """072: LIG디펜스앤에어로스페이스의 'LIG넥스원' 기사(2025-05)가 옛 이름이라 0건으로 셌다."""
    from backend.analysis.m2_data.news import KR_TITLE_ALIASES

    assert "LIG넥스원" in KR_TITLE_ALIASES["079550"] and "STX엔진" in KR_TITLE_ALIASES["071970"]


def test_holdings_shrink_option_says_what_happens_at_the_backtest_start():
    """074: '종목 수를 9개로 줄이고 섹터당 상한 85%로 올려 투자 비율 85%를 모두 배분' 을 골랐는데 시작일 7종목 × 10% = 70% 만 투자됐다 (Q-278 과 같은 문제)."""
    from backend.analysis.m1_request.dialog import DialogService

    req = {"constraints": {"max_weight_per_stock": 0.10, "max_weight_per_sector": 0.30, "min_cash_ratio": 0.15, "num_holdings": {"target": 20, "min": 15, "max": 20}}}
    pre = {"basis": "after_classification", "short_now": True, "min": 15, "target": 20,
           "as_of": {"n_with_metric": 9, "n_candidates": 9, "capacity": 0.3, "sector_counts": {"Financials": 9}, "by_filter": {}, "n_matched": 17},
           "start": {"n_with_metric": 7, "n_candidates": 7, "capacity": 0.3, "sector_counts": {"Financials": 7}}}  # fmt: skip
    q = DialogService._feasibility_proposals(None, req, pre, {})[0]
    assert q.options[0].label_ko == "종목 수를 9개로 줄이고 섹터당 상한 85%로 올려 투자 비율 85%를 모두 배분 (백테스트 시작일 구성은 70%까지만)"
    pre["start"]["sector_counts"] = {"Financials": 9}  # 시작일도 다 담기면 예전 문구
    assert DialogService._feasibility_proposals(None, req, pre, {})[0].options[0].label_ko.endswith("모두 배분")
