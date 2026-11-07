"""2026-11 시나리오 QA 라운드 20 (066~070) 회귀 테스트."""

from __future__ import annotations

import datetime as dt
from types import SimpleNamespace

from backend.analysis.m5_backtest_report import report_blocks as B


def test_rebalance_label_names_the_real_months():
    """068: 6개월 × 2 를 '매년 첫 거래일' 이라 했는데 시작이 10월이라 실제로는 매년 7월 1일. 067: 분기 × 2 는 4·10월."""
    from backend.analysis.m1_request.derive import rebalance_label_ko as f

    tail = " 첫 거래일에 목표 비중으로 리밸런싱"
    assert f(2, "6m", dt.date(2023, 10, 9)) == "매년 7월" + tail
    assert f(2, "1q", dt.date(2023, 5, 8)) == "반기마다(4·10월)" + tail
    assert f(1, "1q", dt.date(2023, 5, 8)) == "분기마다(1·4·7·10월)" + tail
    assert f(1, "1m", dt.date(2023, 3, 3)) == "매월" + tail
    assert f(2, "1y", dt.date(2023, 3, 3)) == "2년마다 1월" + tail
    assert f(3, "1q", dt.date(2023, 3, 3)) == "9개월마다" + tail  # 해마다 달이 바뀌면 달을 적지 않는다
    assert f(2, "6m") == "매년" + tail  # 시작일을 모르면 예전 문구


def test_rebalance_label_follows_the_actual_backtest_start():
    """07 에서 시작일을 옮기면 리밸런싱하는 달도 바뀐다 — 실제 시작일로 다시 쓴다."""
    from backend.analysis.m4_portfolio.spec import _rebalance_rule_at

    rule = {"count": 2, "unit": "6m", "enabled": True, "calendar": "half_year_start", "description_ko": "매년 1월 첫 거래일에 목표 비중으로 리밸런싱"}
    assert _rebalance_rule_at(rule, dt.date(2023, 10, 9))["description_ko"].startswith("매년 7월")
    off = {"count": 0, "unit": "6m", "enabled": False, "description_ko": "리밸런싱 없음"}
    assert _rebalance_rule_at(off, dt.date(2023, 10, 9)) == off


def test_min_market_cap_fix_only_when_the_dropped_names_could_add_capacity():
    """070: 시작일에 최소 시가총액으로 빠진 6개가 모두 정보기술인데 정보기술은 섹터 상한 45% 가 차 있어 '최소 시가총액 낮추기' 가 도움이 안 됐다."""
    from backend.analysis.m4_portfolio.spec import _mcap_would_help

    sec = {"CIEN": "Information Technology", "COHR": "Information Technology", "NEE": "Utilities"}
    desc = SimpleNamespace(by_ticker=lambda t: {"gics": {"sector": {"name_en": sec[t]}}})
    inf = {"sector_counts": {"Information Technology": 18, "Communication Services": 2}}
    cons = {"max_weight_per_stock": 0.15, "max_weight_per_sector": 0.45}
    assert not _mcap_would_help(inf, ["CIEN", "COHR"], desc, cons)
    assert _mcap_would_help(inf, ["CIEN", "NEE"], desc, cons)  # 새 섹터 종목이면 투자 비율이 오른다


def test_sector_cap_question_says_what_happens_at_the_backtest_start():
    """070: '섹터 상한을 45% 로 올려 투자 비율 90% 를 모두 배분' 을 골랐는데 2023 시작일 목록(정보기술 18개)은 75% 만 투자됐다 — 60% 가 필요했다."""
    from backend.analysis.m1_request.dialog import DialogService

    req = {"constraints": {"max_weight_per_sector": 0.30, "max_weight_per_stock": 0.15, "min_cash_ratio": 0.10}}
    pre = {"basis": "after_classification", "short_now": False,
           "as_of": {"capacity": 0.60, "cap_needed": 0.45, "n_selected": 20, "sector_counts": {"Information Technology": 10, "Communication Services": 10}},
           "start": {"capacity": 0.60, "cap_needed": 0.60, "sector_counts": {"Information Technology": 18, "Communication Services": 2}}}  # fmt: skip
    q = DialogService._sector_cap_proposals(None, req, {}, None, pre)[0]
    labels = [o.label_ko for o in q.options]
    assert labels[0] == "이번 분석에서는 섹터 상한을 45%로 올려 투자 비율 90%를 모두 배분 (백테스트 시작일 구성은 75%까지만)"
    assert labels[1] == "섹터 상한을 60%로 올려 백테스트 시작일 구성까지 투자 비율 90%를 모두 배분" and q.options[1].value == 0.60
    assert labels[2].startswith("섹터 상한 30% 유지")
    pre["start"] = {"capacity": 0.90, "cap_needed": None, "sector_counts": {"Information Technology": 3, "Communication Services": 3, "Utilities": 3}}
    assert DialogService._sector_cap_proposals(None, req, {}, None, pre)[0].options[0].label_ko.endswith("모두 배분")  # 시작일도 다 담으면 예전 문구


def test_tiny_drawdown_excess_is_not_rounded_to_zero():
    """070: 0.03%p 초과를 '허용보다 0.0%p 큼' 이라고 적었다."""
    from backend.analysis.m5_backtest_report.validate import gap_pp

    assert gap_pp(0.000271) == "0.03%p" and gap_pp(0.087) == "8.7%p" and gap_pp(0.0) == "0.0%p" and gap_pp(-0.01) == "0.0%p"


def test_set_deltas_mark_moves_of_names_without_a_view():
    """068: 시작일 세트 bl_01 의 BMY +1.7%p 는 섹터 상한 재배분인데 뷰 효과처럼 읽혔다."""
    p = {"views_applied": [{"long": ["MRK"], "short": []}, {"long": ["BIIB"], "short": ["AMGN"]}],
         "delta_vs_baseline": {"MRK": 0.033333, "AMGN": -0.028, "BMY": 0.016766, "JNJ": 0.0001}}  # fmt: skip
    assert B.set_deltas(p, 3) == ["MRK +3.3%p", "AMGN -2.8%p", "BMY +1.7%p (뷰 없음, 재배분)"]
    assert B.set_deltas({"views_applied": [], "delta_vs_baseline": {"A": 0.0001}}, 3) == ["변화 없음"]


def test_stuck_note_names_each_stocks_limit_when_causes_differ():
    """066: DIS 는 '뷰 방향 유지', EBAY 는 최소 비중 1% 에 묶였는데 하나라도 다른 이유가 섞이면 모두 '상한·섹터 예산' 이라고 썼다."""
    R = {"request": {"constraints": {"max_weight_per_stock": 0.25}}, "parameters": {"portfolio": {"min_weight": 0.01}},
         "selection": {"table": [{"ticker": "DIS", "name": "Walt Disney"}, {"ticker": "EBAY", "name": "eBay"}]}}  # fmt: skip
    p = {"views_applied": [{"type": "absolute", "direction": "up", "long": ["DIS"], "short": []},
                           {"type": "absolute", "direction": "down", "long": ["EBAY"], "short": []}],
         "weights": {"DIS": 0.0845, "EBAY": 0.01, "X": 0.2}, "delta_vs_baseline": {"DIS": 0.0, "EBAY": 0.0, "X": 0.0},
         "active_constraints": ["view_direction_hold:DIS"]}  # fmt: skip
    note = B.view_stuck_note(R, p)
    assert "Walt Disney: 뷰 방향 유지" in note and "eBay: 최소 비중 1%" in note and "상한·섹터 예산" not in note


def test_start_date_capacity_fact_says_when_and_what_now_holds():
    """070: 시작일 목록의 75% 한도를 '분석 기준일 선정 종목은 섹터 상한 때문에 투자 비율이 제한됐다' 고 써서 다 담는 지금 구성에 상한을 올리라고 권했다."""
    from backend.analysis.m5_backtest_report.report import _infeasibility_fact

    R = {"request": {"constraints": {"min_cash_ratio": 0.10}},
         "selection": {"backtest_as_of": {"as_of": "2023-05-26", "infeasibility": {"cause_ko": "섹터 상한 45% 때문에 75%까지만"}},
                       "as_of_now": {"as_of": "2026-05-26", "summary": {"weight_capacity": 0.9}}}}  # fmt: skip
    f = _infeasibility_fact(R)
    assert f["when_ko"] == "백테스트 시작일(2023-05-26) 선정 종목의 배분 한도" and f["now_ko"].startswith("분석 기준일(2026-05-26) 구성은 투자 비율 90%를 모두 담음")
    R["selection"]["as_of_now"]["summary"]["weight_capacity"] = 0.6
    assert _infeasibility_fact(R)["now_ko"] == "분석 기준일(2026-05-26) 구성도 60%까지만 담음"
    R["selection"]["backtest_as_of"]["infeasibility"] = None
    assert _infeasibility_fact(R) is None


def test_numbers_inside_code_check_text_count_as_known():
    """067: R2 의 '과거 1년 구간 517개' 를 서술이 옮겼는데 숫자 칸에 없어 '결과에 없는 숫자' 메모가 화면에 보였다."""
    from backend.analysis.m5_backtest_report.report_check import _string_numbers

    acc: set[float] = set()
    _string_numbers([{"results": [{"checks": [{"message_ko": "과거 1년 구간 517개 중 6.0%가 목표 달성, 최저 -13.5%, 평가액 1,234.5 USD"}]}]}, None], acc)
    assert {517, 6.0, 13.5, 1234.5} <= acc


def test_too_few_notice_does_not_carry_the_label_condition():
    """066: '최소 종목 수에 못 미치면 결론 라벨에 종목 수 부족' 이라는 조건 문장을 기업 설명이 '결론 라벨은 종목 수 부족' 으로 옮겼다 (9 ≥ 최소 7)."""
    from backend.analysis.common.warnings import from_text

    w = from_text("05_selection", "only 9 tickers have return_12m_1m; target 12 -> selecting 9")
    assert w.code == "too_few_with_metric" and "결론 라벨" not in w.message_ko and w.message_ko.endswith("9개만 선정했습니다.")


def test_keyword_match_ignores_hyphens():
    """066: 키워드 'ecommerce platform' 이 소개 'e-commerce platform' 을 못 찾아 Carvana 가 '테마 키워드 약함' 으로 빠졌다."""
    from backend.pipeline.descriptor import Descriptor

    d = Descriptor({"stocks": [{"ticker": "CVNA", "yfinance_symbol": "CVNA", "name": "Carvana Co.", "keywords": [],
                                "intro": "operates an e-commerce platform for buying and selling used cars"}], "gics": []})  # fmt: skip
    hits = d.search_keywords(["e-commerce", "ecommerce platform", "e commerce"], min_distinct=2)
    assert len(hits) == 1 and sorted(hits[0].matched) == ["e commerce", "e-commerce", "ecommerce platform"]


def test_every_deep_drawdown_episode_keeps_its_trough_in_the_chart():
    """069: 두 번째로 깊은 −23.9%(2026-03-04)가 차트 표본에서 빠져 −16.9% 로 보였다 (시리즈마다 최저점 하나만 고정했다)."""
    n = 1300
    dd = [0.0] * n
    dd[101], dd[700], dd[701], dd[702] = -0.30, -0.10, -0.239, -0.16  # 701 은 표본 간격(3)에 안 걸리는 날
    dates = [f"d{i}" for i in range(n)]
    ds, ser, info = B.sample_series(dates, {"a": {"drawdown": dd}}, max_points=600)
    assert "d701" in ds and min(ser["a"]["drawdown"]) == -0.30 and -0.239 in ser["a"]["drawdown"]


def test_subtitle_is_marked_as_the_request_when_holdings_fall_short(monkeypatch):
    """069: 머리말 'ROE 순위에 따라 15개를 선정' 인데 선정은 11개."""
    from backend.analysis.m5_backtest_report import report as RP

    R = {"request": {"constraints": {"min_cash_ratio": 0.10, "num_holdings": {"target": 15, "min": 10}}, "horizon": {"target_years": 3}},
         "intent": {"interpretation": {"summary_ko": "국내 전력 인프라 종목을 ROE 순위에 따라 15개를 선정합니다."}}}  # fmt: skip
    monkeypatch.setattr(RP.B, "current_composition", lambda R, chosen: ({f"T{i}": 0.9 / 11 for i in range(11)}, 0.10, "동일비중"))
    assert RP._subtitle_ko(R, "equal_weight").startswith("요청: ")
    monkeypatch.setattr(RP.B, "current_composition", lambda R, chosen: ({f"T{i}": 0.06 for i in range(15)}, 0.10, "동일비중"))
    assert not RP._subtitle_ko(R, "equal_weight").startswith("요청: ")


def test_korean_title_check_skips_longer_names_of_other_companies():
    """069: 한전기술 기사 '한국전력기술, AI 리더십…' 이 한국전력 뉴스로 들어갔다 (한국전력 ⊂ 한국전력기술, 한전 ⊂ 한전기술·한전KPS·대한전선)."""
    from backend.db.analysis_readers import _title_mentions

    names = ["한국전력", "015760", "한전", "!한국전력기술", "!한전기술", "!한전KPS", "!대한전선"]
    assert not _title_mentions("한국전력기술, AI 리더십 강화하고 협력사와 노하우 나눈다", names)
    assert not _title_mentions("한전기술, '2026년 AX시대 리더십 교육' 실시", names)
    assert not _title_mentions("대한전선, 해저 케이블 수주", names)
    assert _title_mentions("한전, 전기요금 인상 검토", names) and _title_mentions("한국전력과 한전KPS 협력", names)


def test_news_off_label_does_not_say_only_the_baseline(monkeypatch):
    """069: 추천이 동일비중인데 '뉴스 뷰 반영: 꺼짐 (기준 비중만)' — 기준 비중(시가총액비중)만 쓴 것처럼 읽혔다."""
    monkeypatch.setattr(B, "_tolerance_note", lambda R: "25.0%")
    R = {"intent": {"risk_params": {"volatility_preference": "low", "notes_ko": ""}, "news_tilt": {"enabled": False}}}
    row = next(r for r in B.soft_table(R)["rows"] if r["k"] == "뉴스 뷰 반영")
    assert row["v"] == "꺼짐 (뉴스 뷰 없이 비중 규칙만)"
