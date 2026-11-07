"""2026-11 시나리오 QA 라운드 12 (028~032 + 023 재실행) — 리포트 쪽 회귀 테스트."""

from __future__ import annotations

import pytest

from backend.analysis.m5_backtest_report import report as RP
from backend.analysis.m5_backtest_report import report_blocks as RB


def test_korean_sector_and_sub_industry_names():
    """028: 문장은 '금융 87.4%' 인데 막대·표·기업 카드는 'Financials'·'Transaction & Payment Processing Services'."""
    from backend.analysis.common.labels import sector_ko, sub_industry_ko

    assert sector_ko("Financials") == "금융" and sector_ko("금융") == "금융"
    assert sub_industry_ko("Transaction & Payment Processing Services") == "결제·거래 처리 서비스" and sub_industry_ko("모르는 이름") == "모르는 이름"
    R = {"backtest": {"portfolios": [{"id": "bl_04", "kind": "black_litterman", "title_ko": "t",
                                      "metrics": {"composition": {"sector_weights_avg": {"Financials": 0.87, "Information Technology": 0.08}}}}],
                      "benchmark": {"id": "SPY"}}, "validation": {}}  # fmt: skip
    assert [x["label"] for x in RB.sector_bar(R, "bl_04")["items"]] == ["금융", "정보기술"]


def test_template_conflict_card_states_what_was_applied():
    """032: '저평가 선호는 … 보조적으로 반영합니다' 라 했지만 선정·비중 어디에도 쓰이지 않았다. 023: '…종목 수 필드는 없습니다'."""
    R = {"request": {"strategy_preference": {"template": "high_dividend"}},
         "intent": {"interpretation": {"conflicts": [
             {"field": "strategy_preference.template", "issue_ko": "아이디어는 고배당과 저평가를 함께 말합니다.", "resolution_ko": "저평가 선호는 보조적으로 반영합니다."},
             {"field": "constraints.num_holdings", "issue_ko": "이를 표현할 백테스트 종목 수 필드는 없습니다.", "resolution_ko": "참고사항으로 전달합니다."}]}}}  # fmt: skip
    items = RB.conflicts_cards(R)["items"]
    assert items[0]["text_ko"].endswith("선정 순위는 고배당 기준 하나로 매깁니다 (다른 기준은 종목 선정·비중에 쓰지 않습니다).")
    assert "보조적으로" not in items[0]["text_ko"] and "필드" not in items[1]["text_ko"] and "종목 수 조건은 없습니다" in items[1]["text_ko"]


def test_forward_news_note_does_not_claim_moves_when_every_set_equals_baseline(monkeypatch):
    """029: 9종목이 모두 상한 10% 라 다섯 세트 모두 기준과 같았는데 '뷰는 그 대안의 비중만 바꿨습니다'."""
    monkeypatch.setattr(RP.B, "current_composition", lambda R, c: ({"A": 0.5}, 0.5, "낙폭 맞춤안"))
    flat = {"portfolio": {"forward": {"portfolios": [{"id": "fwd_bl_01", "weights": {"A": 0.1}, "delta_vs_baseline": {"A": 1e-6}}]}}}
    note = RP._chosen_news_use(flat, "dd_match_equal_weight", {"id": "dd_match_equal_weight", "kind": "matched", "base_id": "equal_weight"})["chosen_news_note_ko"]
    assert "비중만 바꿨습니다" not in note and "뷰가 비중을 바꾸지 못해 기준 비중과 같습니다" in note
    moved = {"portfolio": {"forward": {"portfolios": [{"id": "fwd_bl_01", "weights": {"A": 0.15}, "delta_vs_baseline": {"A": 0.05}}]}}}
    assert "뷰는 그 대안의 비중만 바꿨습니다." in RP._chosen_news_use(moved, "equal_weight", {"id": "equal_weight", "kind": "template"})["chosen_news_note_ko"]


def test_display_strings_for_matched_and_benchmark_gaps():
    """031: 맞춤안 최대낙폭 7.8955% 를 '8.0%' 로 썼다. 032: SPY 대비 CAGR 20.2% vs 18.5% 를 '1.8%p', 최대낙폭 19.1% vs 18.7% 를 '0.3%p'."""
    assert RP._headline_display({"max_drawdown": -0.078955, "cagr": 0.0733, "final_value_usd": 91817.4}) == {"cagr": "7.3%", "max_drawdown": "7.9%", "final_value_usd": "91,817"}
    R = {"backtest": {"benchmark": {"id": "SPY", "name_ko": "SPY", "headline": {"cagr": 0.184704, "max_drawdown": -0.18743}}}}
    d = RP._vs_benchmark_display(R, {"headline": {"cagr": 0.202283, "max_drawdown": -0.190893}})
    assert (d["chosen_cagr"], d["benchmark_cagr"], d["cagr_diff"]) == ("20.2%", "18.5%", "+1.7%p")
    assert (d["chosen_mdd"], d["benchmark_mdd"], d["mdd_diff"]) == ("19.1%", "18.7%", "+0.4%p")


def test_evidence_labels_are_readable():
    """028: 출처 창에 'IBKR pe_ttm'·'valuation_daily', 029: 출처가 'NAVER_NEWS'."""
    from backend.analysis.common.labels import FACT_SOURCE_KO, NEWS_SOURCE_KO
    from backend.analysis.m5_backtest_report import collect as C

    assert NEWS_SOURCE_KO["NAVER_NEWS"] == "네이버 뉴스" and FACT_SOURCE_KO["valuation_daily"].startswith("팀 데이터베이스")
    bt = {"portfolios": [{"id": "market_cap", "name_ko": "시가총액비중", "headline": {"cagr": 0.1, "max_drawdown": -0.2}, "metrics": {"risk": {"ann_vol": 0.15}}}],
          "period": {"end": "2026-01-02"}}  # fmt: skip
    calc = C._calc_facts(bt, {})
    assert calc["calc:cagr:market_cap"]["title"] == "시가총액비중 연환산 수익률(CAGR)" and calc["calc:ann_vol:market_cap"]["title"] == "시가총액비중 연변동성"
    assert calc["calc:max_drawdown:market_cap"]["source"] == "백테스트 계산"
    assert "valuation_daily" not in RB._mcap_limitation({"parameters": {"market": {"mcap_fallback_max_days": 730}}})
