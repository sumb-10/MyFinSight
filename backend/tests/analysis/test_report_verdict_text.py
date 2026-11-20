"""「선택 근거 자세히 보기」 본문(14a risk_fit_ko · 14b overview_ko)에 넘기는 사실 (2026-11-16 사용자 검토).

판정 보류(짧은 창의 R2·R7 info)를 미달과 구분하고, 두 날짜·평가 기간·운용 방식을 이름 붙여 넘기며, 같은 규칙의 다른 운용 방식은
기간 수익률·최대낙폭까지 같은 지표로 넘기는지 본다. LLM 문장은 보지 않는다 (stub).
"""

from __future__ import annotations

import copy

from backend.analysis.m5_backtest_report import report_blocks as B
from backend.analysis.m5_backtest_report.report import facts_for_interpret, facts_for_narrate


def _set_status(R, pid: str, rule: str, status: str, threshold: object = "keep") -> None:
    for r in R["validation"]["results"]:
        if r["id"] == pid:
            for c in r["checks"]:
                if c["rule"] == rule:
                    c["status"] = status
                    if threshold != "keep":
                        c["threshold"] = threshold


def _all_status(R, rule: str, status: str) -> None:
    for r in R["validation"]["results"]:
        _set_status(R, r["id"], rule, status)


def test_short_window_target_is_not_judged_not_missed(e2e_results):
    """미국 AI 리포트: R2·R7 이 판정 보류(info)인데 '목표보다 1.2%p 낮음'·'목표를 맞춘 후보 없음' 으로 썼다."""
    R0, _ = e2e_results
    chosen = B.chosen_portfolio_id(R0)[0]
    R = copy.deepcopy(R0)
    _all_status(R, "R2", "info")
    _set_status(R, chosen, "R7", "info", threshold=0.2)
    cc = B.condition_check(R, chosen)
    assert cc["judgements"]["target_return"] == "not_judged" and cc["judgements"]["volatility"] == "not_judged"
    assert cc["target_return_met"] is None and cc["target_gap_pp"] is None
    assert "best_meeting_target" not in cc  # 판정하지 않은 조건에 '맞춘 포트폴리오 없음' 을 넘기지 않는다
    assert cc["n_target_judged_r2"] == 0
    ref = cc["annualized_return_reference"]
    assert ref["value"].endswith("%") and "1년 기준으로 환산" in ref["note_ko"]


def test_missed_target_is_not_met_with_gap(e2e_results):
    """실제 미달(R2 warn)은 판정 보류와 다르게: 미달 표시와 맞춘 포트폴리오(없으면 None)를 넘긴다."""
    R0, _ = e2e_results
    chosen = B.chosen_portfolio_id(R0)[0]
    R = copy.deepcopy(R0)
    _set_status(R, chosen, "R2", "warn")
    cc = B.condition_check(R, chosen)
    assert cc["judgements"]["target_return"] == "not_met"
    assert "best_meeting_target" in cc and "annualized_return_reference" not in cc
    assert cc["n_target_judged_r2"] >= 1


def test_volatility_without_criterion_is_not_called_pending(e2e_results):
    """적극 성향은 R7 이 기준값 없이 info — 판정 보류가 아니라 '기준 없음'."""
    R0, _ = e2e_results
    chosen = B.chosen_portfolio_id(R0)[0]
    R = copy.deepcopy(R0)
    _set_status(R, chosen, "R7", "info", threshold=None)
    assert B.judgements(R, chosen)["volatility"] == "no_criterion"


def test_dates_and_mode_are_named_for_both_prompts(e2e_results):
    R, _ = e2e_results
    chosen = B.chosen_portfolio_id(R)[0]
    for facts in (facts_for_interpret(R, chosen), facts_for_narrate(R, chosen, {})):
        dm = facts["dates_and_mode"]
        ep = dm["evaluation_period"]
        assert ep["start"] and ep["end"] and ep["total_return"].endswith("%")
        assert dm["backtest_selection_date"] and dm["as_of_now"] and isinstance(dm["backtest_reselected"], bool)
        assert dm["operation"]["chosen_mode_ko"] in (B.STATIC_MODE_KO, B.WF_MODE_KO) and dm["operation"]["rebalance_ko"]


def test_other_mode_compares_same_metrics(e2e_results):
    """두 운용 방식은 기간 수익률·최대낙폭까지 (19.2% CAGR 만 넘겨 기간 수익률 19.1% 를 못 썼다), 차이가 작아도 넘긴다."""
    R, _ = e2e_results
    for p in R["backtest"]["portfolios"]:
        twin = f"wf_{p['id']}"
        if p.get("kind") == "template" and p.get("mode") != "walkforward" and any(x["id"] == twin for x in R["backtest"]["portfolios"]):
            so = B.condition_check(R, p["id"])["same_rule_other_mode"]
            assert so["id"] == twin and so["mode_ko"] == B.WF_MODE_KO and so["chosen_mode_ko"] == B.STATIC_MODE_KO
            assert so["total_return"].endswith("%") and so["chosen_total_return"].endswith("%") and so["chosen_max_drawdown"].endswith("%")
            assert so["rebalance_ko"]
            return
    raise AssertionError("시작일 비율 방식과 walk-forward 쌍이 있는 템플릿이 없음")


def test_momentum_scope_names_the_window():
    measures, not_measured = B.METRIC_SCOPE_KO["return_12m_1m"]
    assert "약 12개월 전" in measures and "약 1개월 전" in measures
    assert "수익성" in not_measured and "부채" in not_measured


def test_text_override_replaces_only_the_two_verdict_paragraph_blocks(tmp_path):
    """저장된 리포트는 그대로 두고, 읽을 때 종합 판단의 14b·14a 문단만 바꾼다. 파일이 없거나 비면 원래 문서."""
    from backend.analysis.common.store import JsonStore
    from backend.analysis.m5_backtest_report import text_overrides as T

    doc = {"sections": [{"id": "verdict", "blocks": [{"type": "paragraphs", "src": "14b", "tone": "lead", "items": ["옛 결론"]}, {"type": "kpis", "ids": []},
                                                     {"type": "paragraphs", "src": "14a", "items": ["옛 해석"]}]},
                        {"id": "performance", "blocks": [{"type": "paragraphs", "src": "14a", "items": ["성과 그대로"]}]}]}
    store = JsonStore(tmp_path)
    assert T.apply(doc, T.load(store, "r1")) is doc
    T.save(store, "r1", {"overview_ko": ["새 결론"], "risk_fit_ko": ["새 해석", "둘째"]})
    out = T.apply(doc, T.load(store, "r1"))
    v = out["sections"][0]["blocks"]
    assert v[0]["items"] == ["새 결론"] and v[2]["items"] == ["새 해석", "둘째"] and v[0]["tone"] == "lead"
    assert out["sections"][1]["blocks"][0]["items"] == ["성과 그대로"] and doc["sections"][0]["blocks"][0]["items"] == ["옛 결론"]
    T.save(store, "r2", {"overview_ko": [], "risk_fit_ko": ["x"]})
    assert T.load(store, "r2") is None


def test_other_mode_carries_sharpe_and_the_rule_that_decided(e2e_results):
    """두 방식 중 무엇이 왜 앞섰는지 — 모델이 수익률만 보고 짐작하지 않게 샤프 비율과 순위 규칙의 단계를 넘긴다."""
    R, _ = e2e_results
    for p in R["backtest"]["portfolios"]:
        twin = f"wf_{p['id']}"
        if p.get("kind") == "template" and p.get("mode") != "walkforward" and any(x["id"] == twin for x in R["backtest"]["portfolios"]):
            so = B.condition_check(R, p["id"])["same_rule_other_mode"]
            assert "워크포워드(walk-forward)" in so["mode_ko"] and "시작일" in so["chosen_mode_ko"]
            assert "sharpe" in so and "chosen_sharpe" in so and so["judgements"] and so["chosen_judgements"]
            assert "_lost_on_by_id" not in B.condition_check(R, p["id"])
            return
    raise AssertionError("시작일 비율 방식과 walk-forward 쌍이 있는 템플릿이 없음")


def test_sharpe_pair_shows_a_third_digit_when_two_digits_tie():
    assert B._sharpe_pair(0.594, 0.483) == (0.59, 0.48)
    assert B._sharpe_pair(1.4412, 1.4381) == (1.441, 1.438)


def test_selection_changes_are_dated_paragraphs():
    """미국 AI 리포트 모양의 최소 결과 (2026-11-16 사용자 요청): ① 날짜별 종목 수·필수 포함·순위 기준 ② 분석 기준일에 빠진 종목
    ③ 백테스트 시작일에 뽑히지 않은 종목. 후보를 추리는 단계와 순위로 고르는 단계가 문장에서 구분되고, 순위·비교 수치는 기록이 있을 때만."""
    from backend.analysis.m5_backtest_report.report import (
        ensure_selection_changes,
        selection_changes_paragraphs,
    )

    row = lambda t, **k: {"ticker": t, "name": t, "forced": False, "in_selection_now": False, "metric_now": None, "in_backtest": False, "metric_backtest": None, **k}  # noqa: E731
    table = [row("GOOGL", forced=True, in_selection_now=True, in_backtest=True), row("DELL", in_selection_now=True, metric_now=2.966),
             row("MRNA", in_selection_now=True, metric_now=8.2), row("SNDK", in_selection_now=True, metric_now=6.6),
             row("ECHO", in_backtest=True, metric_backtest=2.108), row("HOOD", in_backtest=True, metric_backtest=5.1), row("APP", in_backtest=True, metric_backtest=2.6)]
    table = [{**t, "name": {"DELL": "Dell Technologies", "MRNA": "Moderna", "SNDK": "Sandisk", "ECHO": "EchoStar", "HOOD": "Robinhood Markets", "APP": "AppLovin"}.get(t["ticker"], t["ticker"])} for t in table]
    R = {"request": {"constraints": {"must_include_tickers": ["GOOGL"]}},
         "selection": {"metric": "return_12m_1m", "direction": "desc", "backtest_reselected": True, "table": table,
                       "as_of_now": {"as_of": "2026-11-10", "summary": {"n_candidates": 120}, "rejected_examples": [{"ticker": "ECHO", "reason": "순위 밖", "metric_value": 0.343}]},
                       "backtest_as_of": {"as_of": "2025-11-10",
                                          "backtest_only_reasons_ko": [{"ticker": "HOOD", "name": "Robinhood Markets", "reason_ko": "후보 상한 밖(선정 지표 순)"},
                                                                       {"ticker": "APP", "name": "AppLovin", "reason_ko": "후보 상한 밖(선정 지표 순)"},
                                                                       {"ticker": "ECHO", "name": "EchoStar", "reason_ko": "분석 기준일(2026-11-10) 순위 밖 (모멘텀 +34.3%)"}],
                                          "removed_reasons_ko": [{"ticker": "DELL", "name": "Dell Technologies", "reason_ko": "순위 밖"}, {"ticker": "MRNA", "name": "Moderna", "reason_ko": "자격선 밖"},
                                                                 {"ticker": "SNDK", "name": "Sandisk", "reason_ko": "가격 이력 부족"}],
                                          "diff_vs_original": {"removed_reasons": {"DELL": "rank_beyond_n", "MRNA": "metric_out_of_range(return_12m_1m=-0.4834, 범위 >0)", "SNDK": "insufficient_price_history"}}}}}
    p = selection_changes_paragraphs(R)
    assert len(p) == 3
    assert p[0] == ("백테스트 시작일과 분석 기준일에 각각 **4종목**을 골랐습니다. 두 날짜 모두 1종목은 필수 포함으로 처리했고, "
                    "나머지 3종목은 각 날짜를 기준으로 약 12개월 전부터 약 1개월 전까지 주가가 많이 오른 순으로 골랐습니다.")
    assert p[1].startswith("2026년 11월 10일 분석 기준일에 빠진 종목\n")
    assert "Robinhood Markets, AppLovin는" not in p[1] and "Robinhood Markets와 AppLovin은 주가 상승률을 기준으로 처음 검토할 종목을 120개로 추리는 단계에서 빠졌습니다." in p[1]
    assert "EchoStar는 이 단계를 통과했지만 순위로 뽑는 3자리에 들지 못했습니다. EchoStar의 상승률은 34.3%였고, 그 3종목 중 상승률이 가장 낮은 Dell Technologies는 296.6%였습니다." in p[1]
    assert p[2].startswith("2025년 11월 10일 백테스트 시작일에 뽑히지 않은 종목\n")
    assert "Dell Technologies는 순위로 뽑힌 3종목 중 상승률이 가장 낮은 EchoStar(210.8%)보다 낮았습니다." in p[2]
    assert "Moderna는 해당 기간에 주가가 48.3% 내려 선정 조건을 충족하지 못했습니다." in p[2]
    assert "Sandisk는 당시 주가 상승률을 계산하는 데 필요한 과거 가격 기록이 부족했습니다." in p[2]
    # 다른 지표: 그 지표로 설명 (배당수익률)
    R2 = {**R, "selection": {**R["selection"], "metric": "dividend_yield_ttm"}}
    p2 = selection_changes_paragraphs(R2)
    assert "최근 12개월 배당수익률이 높은 순으로 골랐습니다" in p2[0] and "배당수익률을 기준으로 처음 검토할 종목을" in p2[1] and "주가 상승률" not in " ".join(p2)
    # 2026-11-19: 종합 판단에는 날짜별 종목 수 문단(p[0])만. 빠진 종목·뽑히지 않은 종목·겹친 비중·빠진 종목의 수익 기여 문단은 뺀다
    narr = {"overview_ko": ["결론", "선정 방법", *p,
                            "분석 기준일 구성에서 백테스트에도 담았던 종목의 비중 합은 89%입니다. 과거 수익률에 6.1%p를 보탠 EchoStar는 이번 분석 기준일 구성에서 빠졌으며, 그 기여도는 백테스트 기간에 계산된 값입니다.",
                            "백테스트 수익을 이끈 EchoStar(+7.1%p)은 백테스트 기간에는 기여했지만 분석 기준일 구성에는 없습니다.",
                            "이번 분석의 필수 포함 목록을 과거 계산에도 넣었습니다. 이 조건으로 담은 GOOGL 은 기여분 중 54%를 차지했습니다."]}  # fmt: skip
    assert ensure_selection_changes(narr, R)
    assert narr["overview_ko"] == ["결론", "선정 방법", p[0], "이번 분석의 필수 포함 목록을 과거 계산에도 넣었습니다. 이 조건으로 담은 GOOGL 은 기여분 중 54%를 차지했습니다."]
    assert ensure_selection_changes(narr, R) is False  # 이미 정리됐으면 그대로
    # 모델이 날짜별 종목 수 문단을 빠뜨렸으면 셋째 자리에 넣는다
    narr = {"overview_ko": ["결론", "선정 방법", "필수 포함 문단"]}
    assert ensure_selection_changes(narr, R) and narr["overview_ko"] == ["결론", "선정 방법", p[0], "필수 포함 문단"]


def test_modes_paragraph_starts_with_two_rebalancing_methods(monkeypatch):
    """2026-11-19 사용자 요청: 운용 방식 문단이 '시작일 비중으로 되돌리는 방식은 …' 으로 갑자기 시작했다 → '리밸런싱에는 두 가지 방식이 있습니다' 부터."""
    from backend.analysis.m5_backtest_report import report_blocks as B
    from backend.analysis.m5_backtest_report.report import ensure_modes_intro

    R = {"backtest": {"portfolios": [{"id": "equal_weight", "kind": "template"}, {"id": "wf_equal_weight", "kind": "template"}]}}
    old = ("시작일 비중으로 되돌리는 방식은 비중을 조정하는 날마다 백테스트 시작일에 정한 투자 비율로 다시 맞춥니다. "
           "워크포워드(walk-forward) 방식은 같은 종목을 담고, 비중을 조정하는 날마다 그때까지의 자료로 투자 비율을 새로 계산합니다. "
           "이번 분석은 매월 첫 거래일에 비중을 맞췄습니다. 성과가 같아 시작일 비중 방식이 선택됐습니다.")
    interp = {"risk_fit_ko": ["평가 기간 문단", old]}
    assert ensure_modes_intro(interp, R, "equal_weight")
    assert interp["risk_fit_ko"][0] == "평가 기간 문단"
    assert interp["risk_fit_ko"][1] == B.MODES_INTRO_KO + " 이번 분석은 매월 첫 거래일에 비중을 맞췄습니다. 성과가 같아 시작일 비중 방식이 선택됐습니다."
    assert B.MODES_INTRO_KO.startswith("리밸런싱(포트폴리오 비중을 다시 맞추는 일)에는 두 가지 방식이 있습니다.")
    assert "**시작일 비중으로 되돌리는 방식**" in B.MODES_INTRO_KO and "**워크포워드(walk-forward) 방식**" in B.MODES_INTRO_KO  # 두 방식 이름은 굵게 (2026-11-19)
    assert ensure_modes_intro(interp, R, "equal_weight") is False  # 이미 첫머리가 있으면 그대로
    assert ensure_modes_intro({"risk_fit_ko": [old]}, {"backtest": {"portfolios": [{"id": "equal_weight", "kind": "template"}]}}, "equal_weight") is False  # 비교할 방식이 없으면 손대지 않음


def test_korean_particles_follow_the_name_sound():
    from backend.analysis.m5_backtest_report.report import _josa

    assert [_josa(n, "은는") for n in ("Lumentum", "Teradyne", "Intel", "Moderna", "EchoStar", "Sandisk", "삼성전자", "SK하이닉스")] == [
        "Lumentum은", "Teradyne은", "Intel은", "Moderna는", "EchoStar는", "Sandisk는", "삼성전자는", "SK하이닉스는"]


def test_construction_facts_dates_estimation_and_three_volatilities(e2e_results):
    """「비중 결정 설명」: 두 날짜 한국어 표기 · 시작일 추정에 쓴 거래일 수 · 같은 전략의 변동성 세 값을 이름 붙여, 워크포워드 뉴스 구성은 선택됐을 때만."""
    from backend.analysis.m5_backtest_report.report import facts_for_narrate

    R, _ = e2e_results
    chosen = B.chosen_portfolio_id(R)[0]
    c = facts_for_narrate(R, chosen, {})["construction"]
    dv = c["dates_and_vol"]
    assert "년" in dv["backtest_start_ko"] and "년" in dv["as_of_now_ko"]
    assert dv["start_estimation"]["trading_days"] == R["portfolio"]["market_model"]["lookback"]["days"]
    v = dv["chosen_volatility"]
    assert v["realized_in_backtest"].endswith("%") and "섞지 않는다" in v["note_ko"]
    assert c["walkforward_news_chosen"] is (chosen == "wf_bl_news")
    if chosen != "wf_bl_news":
        assert not c["walkforward"]


def test_text_override_can_also_replace_the_construction_explanation(tmp_path):
    from backend.analysis.common.store import JsonStore
    from backend.analysis.m5_backtest_report import text_overrides as T

    doc = {"sections": [{"id": "verdict", "blocks": [{"type": "paragraphs", "src": "14b", "items": ["옛 결론"]}, {"type": "paragraphs", "src": "14a", "items": ["옛 해석"]}]},
                        {"id": "construction", "blocks": [{"type": "paragraphs", "src": "14b", "items": ["옛 비중 설명"]},
                                                          {"type": "paragraphs", "src": "14b", "group_ko": "분석 기준일의 현재 구성", "items": ["기준일 글 그대로"]}]}]}
    store = JsonStore(tmp_path)
    T.save(store, "r", {"overview_ko": ["새 결론"], "risk_fit_ko": ["새 해석"], "construction_ko": ["새 비중 설명"]})
    out = T.apply(doc, T.load(store, "r"))
    cb = out["sections"][1]["blocks"]
    assert cb[0]["items"] == ["새 비중 설명"] and cb[1]["items"] == ["기준일 글 그대로"] and out["text_override"]["sections"] == ["verdict", "construction"]


def test_drawdown_story_separates_max_drop_and_last_day(e2e_results):
    """「성과 해석」: 기간 중 가장 큰 하락(고점→저점)과 마지막 날 고점 대비 위치를 날짜와 함께 구분하고 허용 낙폭과 비교한다 (2026-11-16)."""
    from backend.analysis.m5_backtest_report.report import drawdown_story, ensure_drawdown_story

    R, _ = e2e_results
    chosen = B.chosen_portfolio_id(R)[0]
    st = drawdown_story(R, chosen)
    if st is None:
        return
    s = st["sentence_ko"]
    assert "고점에서" in s and "저점까지" in s and "백테스트 마지막 날인" in s and "허용한" in s
    interp = {"performance_ko": ["요약 문단입니다.", "가장 큰 하락은 컸고 기간 말에도 고점보다 20.3% 아래였습니다.", "적립 문단입니다."]}
    assert ensure_drawdown_story(interp, R, chosen)
    assert interp["performance_ko"][1].startswith(s) and "기간 말에도" not in interp["performance_ko"][1]
    assert ensure_drawdown_story(interp, R, chosen) is False


def test_text_override_can_replace_performance_interpretation(tmp_path):
    from backend.analysis.common.store import JsonStore
    from backend.analysis.m5_backtest_report import text_overrides as T

    doc = {"sections": [{"id": "verdict", "blocks": [{"type": "paragraphs", "src": "14b", "items": ["결론"]}, {"type": "paragraphs", "src": "14a", "items": ["해석"]}]},
                        {"id": "performance", "blocks": [{"type": "paragraphs", "src": "14a", "items": ["옛 성과 해석"]},
                                                         {"type": "paragraphs", "src": "14a", "group_ko": "검증 상세", "items": ["검증 글 그대로"]}]}]}
    store = JsonStore(tmp_path)
    T.save(store, "r", {"overview_ko": ["새 결론"], "risk_fit_ko": ["새 해석"], "performance_ko": ["새 성과 해석"]})
    out = T.apply(doc, T.load(store, "r"))
    pb = out["sections"][1]["blocks"]
    assert pb[0]["items"] == ["새 성과 해석"] and pb[1]["items"] == ["검증 글 그대로"] and "performance" in out["text_override"]["sections"]


def test_forward_text_window_sentence_and_redistribution_before_after():
    """「종목·비중을 정한 근거」: '뉴스 창·공시 창' 대신 기간·건수 문장, 의견 없이 바뀐 종목은 같은 날짜 기준 비중 → 뉴스 반영 비중 (2026-11-16)."""
    from backend.analysis.m5_backtest_report.report import (
        _forward_window_sentence,
        _redistributed,
        ensure_forward_text,
    )

    f = {"news_window": {"window": ["2026-10-27", "2026-11-10"], "disclosure_window": ["2026-09-26", "2026-11-10"], "n_articles": 80, "n_disclosures": 10},
         "baseline": {"id": "market_cap", "weights": {"NOW": 0.0691, "MRNA": 0.0705, "NVDA": 0.2}},
         "portfolios": [{"id": "fwd_bl_01", "weights": {"NOW": 0.0712, "MRNA": 0.0758, "NVDA": 0.1915}, "delta_vs_baseline": {"NVDA": -0.0085, "MRNA": 0.0053, "NOW": 0.0021},
                         "views_applied": [{"long": ["MRNA"], "short": []}, {"long": ["GOOGL"], "short": ["NVDA"]}]}]}
    assert _forward_window_sentence(f) == "2026년 10월 27일부터 11월 9일까지 나온 기사 제목 80건과, 9월 26일부터 11월 9일까지 나온 공시 10건을 모았습니다."
    rd = _redistributed(f, f["portfolios"][0], {"NOW": "ServiceNow"})
    assert [r["sentence_ko"] for r in rd] == ["다른 종목의 비중을 조정하면서 전체 투자금을 다시 나눴고, 그 과정에서 ServiceNow 비중도 뉴스 반영 전 6.9%에서 반영 후 7.1%로 바뀌었습니다."]
    f2 = {**f, "baseline": {}}  # 전후 값이 없으면 변화량만
    assert "+0.2%p 바뀌었습니다" in _redistributed(f2, f["portfolios"][0], {"NOW": "ServiceNow"})[0]["sentence_ko"]
    R = {"portfolio": {"forward": f}, "selection": {"table": [{"ticker": "NOW", "name": "ServiceNow"}]}}
    narr = {"forward_ko": ["2026-11-10 기준 뉴스 창은 2026-10-27부터 2026-11-09까지입니다. 모더나에 약한 상승 의견을 냈습니다.", "NOW 는 '(뷰 없음, 재배분)' 표시가 있습니다. 끝 문장입니다."]}
    assert ensure_forward_text(narr, R)
    text = " ".join(narr["forward_ko"])
    assert narr["forward_ko"][0].startswith("2026년 10월 27일부터") and "뉴스 창" not in text and "재배분)" not in text and "6.9%에서 반영 후 7.1%" in text
    assert ensure_forward_text(narr, R) is False


def test_text_override_can_replace_forward_explanation(tmp_path):
    from backend.analysis.common.store import JsonStore
    from backend.analysis.m5_backtest_report import text_overrides as T

    doc = {"sections": [{"id": "verdict", "blocks": [{"type": "paragraphs", "src": "14b", "items": ["결론"]}, {"type": "paragraphs", "src": "14a", "items": ["해석"]}]},
                        {"id": "construction", "blocks": [{"type": "paragraphs", "src": "14b", "items": ["비중 설명 그대로"]},
                                                          {"type": "paragraphs", "src": "14b", "group_ko": "분석 기준일의 현재 구성", "items": ["옛 뉴스 설명"]}]}]}
    store = JsonStore(tmp_path)
    T.save(store, "r", {"overview_ko": ["새 결론"], "risk_fit_ko": ["새 해석"], "forward_ko": ["새 뉴스 설명"]})
    out = T.apply(doc, T.load(store, "r"))
    cb = out["sections"][1]["blocks"]
    assert cb[0]["items"] == ["비중 설명 그대로"] and cb[1]["items"] == ["새 뉴스 설명"] and "forward" in out["text_override"]["sections"]


def test_market_sentences_and_fallback(e2e_results):
    """「주요 뉴스와 공시」: 기사 기간·종목당 상한, 연도별 수익률을 계산한 날짜, 목표 판정을 코드 문장으로 — 옛 표현은 빼고 빠지면 넣는다 (2026-11-16)."""
    from backend.analysis.m5_backtest_report.report import _market_sentences, ensure_market_text

    R, _ = e2e_results
    chosen = B.chosen_portfolio_id(R)[0]
    s = _market_sentences(R, chosen, None)
    if "yearly_returns" in s:
        assert "전략의 수익률은" in s["yearly_returns"] and "부분 기간" not in s["yearly_returns"]
    assert "목표 수익률" in s.get("target", "목표 수익률")
    m = {"market_ko": ["두 연도 수익률은 모두 기간 일부 기준이다. 시장은 강세였다.", "뉴스의 실제 수록 날짜는 뉴스 창보다 짧다. 종목마다 최근 최대 10건만 담았다. 제목만으로 판단했다."]}
    ensure_market_text(m, R)
    t = " ".join(m["market_ko"])
    assert "기간 일부 기준" not in t and "뉴스 창" not in t and "최근 최대 10건" not in t and "제목만으로 판단했다" in t


def test_hindsight_note_names_the_rule_and_dates():
    """'지금 고른' 대신 '이번 분석의 필수 포함 조건을 백테스트에도 적용' — 두 날짜와 비율이 무엇의 몫인지 (2026-11-16)."""
    R = {"request": {"constraints": {"must_include_tickers": ["MU", "GOOGL"]}},
         "selection": {"table": [{"ticker": "MU", "name": "Micron Technology"}, {"ticker": "GOOGL", "name": "Alphabet"}], "as_of_now": {"as_of": "2026-11-10"}},
         "portfolio": {"backtest_spec": {"period": {"as_of": "2025-11-10"}}},
         "backtest": {"portfolios": [{"id": "x", "ticker_contribution": {"MU": 0.309, "GOOGL": 0.011, "ECHO": 0.071}}], "benchmark": {"id": "bench"}, "benchmarks": []}, "validation": {"alternatives": []}}
    n = B.hindsight_note(R, "x")
    assert n.startswith("2026년 11월 10일 분석에 적용한 필수 포함 조건을 2025년 11월 10일에 시작한 백테스트에도 적용했습니다.")
    assert "그 결과 이 조건으로 담은 Micron Technology, Alphabet 종목이 백테스트에서 수익에 플러스로 기여한 종목들의 기여분 중 **82%**를 차지했습니다" in n and "지금" not in n

    from backend.analysis.m5_backtest_report.report import ensure_hindsight

    interp = {"performance_ko": ["요약.", "EchoStar 가 기여했습니다. 지금 고른 종목이 82%를 냈으므로 사후 선택 효과가 있습니다. 끝."]}
    assert ensure_hindsight(interp, R, "x")
    assert "지금 고른" not in interp["performance_ko"][1] and "필수 포함 조건을 2025년 11월 10일에 시작한" in interp["performance_ko"][1]


# ── 7. 「확인한 한계」 쉬운 문장 (2026-11-16 사용자 요청) ──
def _lim_R(**kw):
    R = {"parameters": {"descriptor": {"snapshot_date": "2026-10-04"}}, "request": {"derived": {"as_of": "2026-11-10"}},
         "portfolio": {"views": {"2026-11-10": {}}}, "notices": [], "selection": {}}
    R.update(kw)
    return R


def test_limitation_items_plain_four_cards(monkeypatch):
    from backend.analysis.m5_backtest_report import report_blocks as B

    monkeypatch.setattr(B, "_has_kr", lambda R: False)
    items = B.limitation_items(_lim_R())
    assert [x["title_ko"] for x in items] == ["과거 종목 목록", "뉴스와 공시에 사용한 자료", "기업 규모를 추정한 방법", "계산에서 빠진 비용"]
    assert items[0]["text_ko"].startswith("백테스트에서 살펴볼 종목은 2026년 10월 4일 기준 지수 구성 목록에서 골랐습니다.")
    assert items[3]["text_ko"] == "세금, 환전 수수료, 호가 차이는 계산에 반영하지 않았습니다."
    text = " ".join(x["text_ko"] for x in items)
    for w in ("생존 편향", "선견 편향", "뉴스 뷰", "슬리피지", "스냅샷", "구성종목 사전", "유통주식수", "t−1", "회사 소개", "("):
        assert w not in text
    assert B.limitations(_lim_R()) == [x["text_ko"] for x in items]


def test_limitation_items_follow_report_conditions(monkeypatch):
    from backend.analysis.m5_backtest_report import report_blocks as B

    monkeypatch.setattr(B, "_has_kr", lambda R: True)
    R = _lim_R(request={"derived": {"as_of": "2022-10-11"}}, portfolio={}, notices=[{"code": "min_mcap_missing"}])
    items = {x["title_ko"]: x["text_ko"] for x in B.limitation_items(R)}
    assert "뉴스와 공시에 사용한 자료" not in items  # 뉴스로 투자 의견을 만들지 않은 리포트
    assert "이 목록은 2022년 10월 11일보다 뒤의 것이라" in items["과거 종목 목록"]
    assert "최소 시가총액 조건을 확인할 수 없어 후보에서 뺐습니다" in items["기업 규모를 추정한 방법"]
    assert "증권거래세" in items["계산에서 빠진 비용"] and "원화로 본 결과" in items


def test_override_replaces_only_limitation_cards():
    from backend.analysis.m5_backtest_report import text_overrides as T

    doc = {"sections": [{"id": "verdict", "blocks": [{"type": "paragraphs", "src": "14b", "items": ["원래 종합"]}, {"type": "paragraphs", "src": "14a", "items": ["원래 위험"]}]},
                        {"id": "assumptions", "blocks": [{"type": "cards", "title_ko": "다음에 검토할 수 있는 선택지", "items": [{"title_ko": "선택지 1", "text_ko": "그대로", "meta": []}]},
                                                         {"type": "cards", "title_ko": "확인한 한계", "items": [{"title_ko": "한계 1", "text_ko": "생존 편향", "meta": []}]}]}]}  # fmt: skip
    out = T.apply(doc, {"limitations": [{"title_ko": "과거 종목 목록", "text_ko": "새 글"}]})
    blocks = out["sections"][1]["blocks"]
    assert blocks[1]["items"] == [{"title_ko": "과거 종목 목록", "text_ko": "새 글", "meta": []}]
    assert blocks[0]["items"][0]["text_ko"] == "그대로" and out["sections"][0]["blocks"][0]["items"] == ["원래 종합"]
    assert out["text_override"]["sections"] == ["limitations"]
    assert doc["sections"][1]["blocks"][1]["items"][0]["text_ko"] == "생존 편향"  # 원본은 그대로
    both = T.apply(doc, {"overview_ko": ["새 종합"], "risk_fit_ko": ["새 위험"], "limitations": [{"title_ko": "a", "text_ko": "b"}]})
    assert both["text_override"]["sections"] == ["verdict", "limitations"]


def test_rewrite_limitations_keeps_other_override_texts(tmp_path, monkeypatch):
    import json
    import sqlite3

    from backend.analysis.common.store import JsonStore
    from backend.analysis.m5_backtest_report import rewrite_verdict_text as W
    from backend.analysis.m5_backtest_report import text_overrides as T

    doc = {"sections": [{"id": "assumptions", "blocks": [{"type": "cards", "title_ko": "확인한 한계", "items": [{"title_ko": "한계 1", "text_ko": "옛 글", "meta": []}]}]}]}
    db = tmp_path / "r.db"
    con = sqlite3.connect(db)
    con.execute("create table report (report_id text, doc_json text, created_at text)")
    con.execute("insert into report values ('run_x', ?, '1')", (json.dumps(doc),))
    con.commit()
    con.close()
    (tmp_path / "out" / "run_x").mkdir(parents=True)
    (tmp_path / "out" / "run_x" / "13_results.json").write_text(json.dumps(_lim_R()))
    monkeypatch.setattr(W, "output_root", lambda: tmp_path / "out")
    monkeypatch.setattr(W.B, "_has_kr", lambda R: False)
    store = JsonStore(tmp_path / "store")
    T.save(store, "run_x", {"overview_ko": ["다시 쓴 종합"], "risk_fit_ko": ["다시 쓴 위험"]})
    assert W.rewrite_limitations("run_x", db=db, store=store)["status"] == "saved"
    ov = T.load(store, "run_x")
    assert ov["overview_ko"] == ["다시 쓴 종합"] and ov["limitations"][0]["title_ko"] == "과거 종목 목록"
    assert ov["original"]["limitations"][0]["text_ko"] == "옛 글"


# ── 7. 중요한 주의 사항·참고 쉬운 문장 (caution_text, 2026-11-16 사용자 요청) ──
def _ct_R(*, checks=(), comp=None, n_rebal=12, crit=None, bench_vol=0.136, bench_mdd=-0.089):
    p = {"id": "mv", "metrics": {"risk": {"ann_vol": 0.333, "max_drawdown": -0.232}, "return": {"total_return": 0.238, "cagr": 0.238},
                                 "trading": {"n_rebalances": n_rebal}, "composition": comp or {}}}
    R = {"backtest": {"period": {"start": "2025-11-10", "end": "2026-11-10"}, "portfolios": [p],
                      "benchmark": {"name_ko": "SPY 매수보유 (동일 적립)", "metrics": {"risk": {"ann_vol": bench_vol, "max_drawdown": bench_mdd}}}},
         "selection": {"as_of_now": {"as_of": "2026-11-10"}, "table": [{"ticker": "MU", "name": "Micron Technology"}]},
         "portfolio": {"backtest_spec": {"period": {"as_of": "2025-11-10"}}},
         "validation": {"criteria": {"target_annual_return": 0.25, "volatility_preference": "medium", "max_weight_per_stock": 0.2, "drift_tolerance": 0.25,
                                     "max_drawdown": 0.3, **(crit or {})},
                        "results": [{"id": "mv", "checks": list(checks)}]}}  # fmt: skip
    return R, p


def _ct_find(monkeypatch, p):
    from backend.analysis.m5_backtest_report import report_blocks as B

    monkeypatch.setattr(B, "find", lambda R, pid: p)


def test_plain_info_names_the_withheld_verdicts_and_the_volatility_band(monkeypatch):
    from backend.analysis.m5_backtest_report import caution_text as C

    R, p = _ct_R(checks=[{"rule": "R2", "status": "info", "threshold": 0.25}, {"rule": "R7", "status": "info", "threshold": 0.177}])
    _ct_find(monkeypatch, p)
    info = C.plain_info(R, "mv")
    # 2026-11-19: 간결하게 — 판정 보류 이유 한 문장 + 숫자 한 문장, 핵심 판정·수익률은 굵게
    assert info[0] == ("평가 기간(2025년 11월 10일~2026년 11월 10일)이 짧아 연 25% 목표 수익률과 변동성 기준의 충족 여부는 **판정하지 않았습니다**. "
                       "이 기간 수익률 **23.8%**, 변동성 33.3%(기준: 17.7% = SPY 13.6% × 1.3)였습니다.")  # fmt: skip
    joined = " ".join(info)
    for w in ("전체 CAGR", "창이 짧아", "백테스트 창", "중립 성향"):
        assert w not in joined


def test_plain_drift_rebalance_and_buy_and_hold(monkeypatch):
    from backend.analysis.m5_backtest_report import caution_text as C

    comp = {"max_stock_weight": 0.289, "max_stock_weight_ticker": "MU", "days_above_stock_cap": 216, "n_days": 252, "days_above_stock_tol": 16, "breaches": ["stock_cap:MU"]}
    R, p = _ct_R(checks=[{"rule": "R4b", "ok": False}], comp=comp)
    _ct_find(monkeypatch, p)
    t = C.plain_info(R, "mv")[0]
    # 2026-11-19: 간결하게 — 무엇이 커질 수 있는지 / 이번 최대 비중 / 넘은 날 수 / 고치는 법, 네 문장
    assert t == ("정해진 날 포트폴리오 비중을 맞춰도, 다음 조정일까지 주가가 움직이면 한 종목의 비중이 커질 수 있습니다. "
                 "이번에는 **Micron Technology**의 비중이 한때 **28.9%**까지 올랐습니다. "
                 "종목당 상한 20%를 넘은 날은 252거래일 중 216일, 별도 점검 기준 25.0%를 넘은 날은 16일이었습니다. "
                 "비중을 맞추는 간격을 줄이면 목표 비중에 더 자주 맞출 수 있습니다.")  # fmt: skip
    assert "리밸런싱 주기를 줄이면" not in t
    # 비중 조정 없이 보유한 리포트: 조정일·주기 이야기 대신 보유 방식에 맞는 말
    R, p = _ct_R(checks=[{"rule": "R4b", "ok": False}], comp=comp, n_rebal=1)
    _ct_find(monkeypatch, p)
    t = C.plain_info(R, "mv")[0]
    assert t.startswith("처음 정한 비중으로 산 뒤 다시 맞추지 않아, 한 종목의 포트폴리오 비중이 커질 수 있습니다.")
    assert "간격을 줄이면" not in t and t.endswith("정해진 날마다 비중을 다시 맞추면(리밸런싱) 목표 비중에 더 가깝게 유지할 수 있습니다.")


def test_plain_drawdown_exceeded_rule_and_caution_share_one_sentence(monkeypatch):
    from backend.analysis.m5_backtest_report import caution_text as C

    R, p = _ct_R(checks=[{"rule": "R1", "ok": False, "status": "flag", "threshold": 0.2}])
    _ct_find(monkeypatch, p)
    r1 = C.plain_rules(R, "mv")["R1"]
    assert r1 == ("2025년 11월 10일부터 2026년 11월 10일까지 최대낙폭은 **23.2%**로, 허용한 20%보다 **3.2%p 컸습니다**(같은 기간 SPY 8.9%). "
                  "비슷한 하락이 오면 감내하기로 한 손실보다 더 떨어질 수 있습니다.")  # fmt: skip
    cs = C.plain_cautions(R, "mv", ["허용 낙폭 초과 (3.2%p)", "현금 비중 문장"])
    assert cs[0] == {"key": "허용 낙폭 초과 (3.2%p)", "text": r1}  # 화면은 key 로 R1 과 겹치는 주의를 한 번만 보인다
    assert cs[1]["text"] == "현금 비중 문장."


def test_plain_period_notices_for_moved_start_dates():
    from backend.analysis.m5_backtest_report import caution_text as C

    assert C.plain_notice("backtest start_date 2020-01-02 clamped to data start 2021-03-01") == "가격 자료가 2021년 3월 1일부터 있어, 백테스트 시작일을 2020년 1월 2일에서 2021년 3월 1일로 옮겼습니다."
    assert C.plain_notice("최소 시가총액 조건에 쓰는 시가총액 자료가 2019-06-03 부터 있어 백테스트 시작을 2018-01-02 → 2019-06-03 로 옮김") == (
        "최소 시가총액 조건에 쓰는 시가총액 자료가 2019년 6월 3일부터 있어, 백테스트 시작일을 2018년 1월 2일에서 2019년 6월 3일로 옮겼습니다.")
    assert C.plain_notice("알 수 없는 틀") == "알 수 없는 틀"


def test_holdings_gap_note_separates_total_and_stock_share_when_cash(monkeypatch):
    from backend.analysis.m5_backtest_report import report_blocks as B

    p = {"id": "c", "target_weights": {"A": 0.3, "B": 0.3, "E": 0.4}, "ticker_contribution": {"E": 0.071, "A": 0.05}, "metrics": {"return": {"total_return": 0.238}}}
    R = {"selection": {"as_of_now": {"as_of": "2026-10-30"}, "table": [{"ticker": "E", "name": "EchoStar"}]}}
    monkeypatch.setattr(B, "find", lambda R, pid: p)
    monkeypatch.setattr(B, "current_composition", lambda R, c: ({"A": 0.16, "B": 0.16, "N": 0.24}, 0.44, "x"))  # 현금 44%
    s = B.holdings_gap_note(R, "c")
    assert s.startswith("2026년 10월 30일 추천 구성에서는 투자금의 약 **32%**를 백테스트에도 담았던 종목에 배정합니다(주식에 배정한 금액 중에서는 57%).")
    assert "하지만 과거 수익률에 7.1%p를 보탠 EchoStar는 이번 추천 구성에서 빠졌습니다." in s
    assert s.endswith("그래서 이번 구성의 투자 결과는 당시 종목으로 계산한 백테스트 수익률 23.8%와 **달라질 수 있습니다**.")
    monkeypatch.setattr(B, "current_composition", lambda R, c: ({"A": 0.34, "B": 0.34, "N": 0.32}, 0.0, "x"))  # 현금 없음 → 한 번만
    s = B.holdings_gap_note(R, "c")
    assert "투자금의 약 **68%**를 백테스트에도 담았던 종목에 배정합니다. " in s and "주식에 배정한 금액 중" not in s


def test_override_section7_texts_and_summary_patch():
    from backend.analysis.m5_backtest_report import text_overrides as T

    doc = {"summary": {"verdict": {"cautions_ko": ["옛 주의"], "label_ko": "추천"}, "validation": {"info_notes_ko": ["옛 참고"]}, "next_actions_ko": ["옛 조건"]},
           "sections": [{"id": "assumptions", "blocks": [{"type": "paragraphs", "src": "14b", "items": ["옛 전제"]},
                                                         {"type": "cards", "title_ko": "다음에 검토할 수 있는 선택지", "src": "14a", "items": [{"title_ko": "선택지 1", "text_ko": "옛 조건", "meta": []}]}]}]}  # fmt: skip
    ov = {"assumptions_ko": ["새 전제"], "reconsideration_ko": ["새 재검토"], "next_actions_ko": ["새 조건 1", "새 조건 2"],
          "summary_patch": {"verdict": {"cautions_plain": [{"key": "옛 주의", "text": "쉬운 주의."}]}, "validation": {"info_plain_ko": ["쉬운 참고."]}}}
    assert T.load.__name__ and T._texts(ov["assumptions_ko"])
    out = T.apply(doc, ov)
    sec = out["sections"][0]["blocks"]
    assert sec[0]["items"] == ["새 전제", "새 재검토"]
    assert [c["text_ko"] for c in sec[1]["items"]] == ["새 조건 1", "새 조건 2"] and sec[1]["items"][1]["title_ko"] == "선택지 2"
    assert out["summary"]["next_actions_ko"] == ["새 조건 1", "새 조건 2"]
    assert out["summary"]["verdict"]["cautions_plain"][0]["text"] == "쉬운 주의." and out["summary"]["verdict"]["cautions_ko"] == ["옛 주의"]
    assert out["summary"]["validation"]["info_plain_ko"] == ["쉬운 참고."]
    assert out["text_override"]["sections"] == ["assumptions", "next_actions", "cautions"]
    assert doc["summary"]["next_actions_ko"] == ["옛 조건"]  # 원본은 그대로


# ── 반영되지 않은 종목 요청 → 「다음 분석에서 바꿔 볼 조건」 (2026-11-16 사용자 요청) ──
def _req_R(idea: str, must=("NOW", "GOOGL", "MU", "NVDA"), excl=("TSLA",)):
    table = [{"ticker": t, "name": n, "in_selection_now": True} for t, n in [("NOW", "ServiceNow"), ("MU", "Micron Technology"), ("GOOGL", "Alphabet Inc. (Class A)"), ("NVDA", "Nvidia"), ("DELL", "Dell Technologies")]]
    return {"request": {"natural_language": {"idea": idea}, "constraints": {"must_include_tickers": list(must), "exclude_tickers": list(excl)}}, "selection": {"table": table}}


def test_request_followups_tell_drop_from_must_include_from_exclusion():
    from backend.analysis.m5_backtest_report import report_blocks as B

    R = _req_R("AI 기업\n\n[보충 답변]\n- [추가 요청] 필수 포함 종목에서 NOW와 MU는 빼주세요\n- [추가 요청] 필수 포함 종목에서 NOW와 MU는 빼주세요")
    assert [f["text"] for f in B.request_followups_ko(R)] == [
        "ServiceNow와 Micron Technology를 필수 포함 목록에서 빼고, 다른 종목과 같은 기준으로 다시 골라볼 수 있습니다. "
        "이렇게 고른 종목으로 같은 과거 기간을 다시 계산하면, 수익률과 가장 크게 떨어진 폭이 어떻게 달라지는지 확인할 수 있습니다."]
    assert B.request_followups_ko(_req_R("- [추가 요청] 필수 포함 종목에서 NOW와 MU는 빼주세요", must=("GOOGL",))) == []  # 이미 반영됨
    ex = B.request_followups_ko(_req_R("- [추가 요청] Dell은 빼 주세요"))
    assert ex[0]["kind"] == "exclude" and ex[0]["text"].startswith("Dell Technologies를 투자 대상에서 제외하고, 나머지 후보에서 같은 기준으로 다시 골라볼 수 있습니다.")
    assert B.request_followups_ko(_req_R("- [추가 요청] Dell은 빼 주세요", excl=("DELL",))) == []
    assert B.request_followups_ko(_req_R("한국 종목은 빼 주세요")) == []  # 종목이 아닌 조건


def test_ensure_request_followups_replaces_the_mixed_item_only():
    from backend.analysis.m5_backtest_report.report import ensure_request_followups

    R = _req_R("- [추가 요청] 필수 포함 종목에서 NOW와 MU는 빼주세요")
    interp = {"next_actions_ko": ["다음 분석에서 비중을 맞추는 주기를 바꿔 보면 …", "다음 분석에서 ServiceNow와 Micron Technology의 필수 포함·제외 조건을 요청에 맞게 정리해 보면 …", "세 번째"]}
    assert ensure_request_followups(interp, R)
    assert interp["next_actions_ko"][0] == "다음 분석에서 비중을 맞추는 주기를 바꿔 보면 …" and interp["next_actions_ko"][2] == "세 번째"
    assert interp["next_actions_ko"][1].startswith("ServiceNow와 Micron Technology를 필수 포함 목록에서 빼고")
    assert not ensure_request_followups(interp, R)  # 이미 있으면 그대로


# ── 4. 「조건별 근거 보기」 두 표·선택 이유 (validation_text, 2026-11-16 사용자 요청) ──
def _vt_R():
    def pf(pid, sharpe, tr, mdd, mode="static"):
        return {"id": pid, "mode": mode, "metrics": {"risk": {"ann_vol": 0.333, "max_drawdown": -mdd}, "return": {"total_return": tr, "cagr": tr},
                                                     "risk_adjusted": {"sharpe": sharpe}, "trading": {"n_rebalances": 12},
                                                     "composition": {"max_stock_weight": 0.289, "max_stock_weight_ticker": "MU", "days_above_stock_cap": 216, "n_days": 252, "days_above_stock_tol": 16}}}
    ports = [pf("min_variance", 0.59, 0.238, 0.232), pf("wf_min_variance", 0.48, 0.191, 0.212, "walkforward"), pf("equal_weight", 0.2, 0.089, 0.25), pf("market_cap", 0.3, 0.12, 0.2)]
    ok = [{"rule": "R4", "status": "pass", "value": 0.125, "threshold": 0.2}, {"rule": "R8", "status": "pass", "value": 252.0, "threshold": 252.0}]
    base = [{"rule": "R1", "status": "pass", "ok": True, "threshold": 0.3}, {"rule": "R2", "status": "info", "threshold": 0.25, "message_ko": "CAGR … (창이 짧아 참고만)"},
            {"rule": "R3", "status": "pass", "ok": True}, {"rule": "R7", "status": "info", "threshold": 0.177}, {"rule": "R4b", "status": "info", "ok": False},
            {"rule": "R9", "status": "info", "value": 1.0, "message_ko": "투자 100%, 현금 0%"}]  # fmt: skip
    warn = [dict(c, status="warn") if c["rule"] == "R3" else c for c in base]
    res = [{"id": "min_variance", "status": "pass", "checks": base, "integrity": ok}, {"id": "wf_min_variance", "status": "pass", "checks": base, "integrity": ok},
           {"id": "equal_weight", "status": "warn", "checks": warn, "integrity": ok},
           {"id": "market_cap", "status": "fail", "checks": base, "integrity": [{"rule": "R4", "status": "fail", "value": 0.263, "threshold": 0.2}, {"rule": "R8", "status": "fail", "value": 180.0, "threshold": 252.0}]}]  # fmt: skip
    R = {"backtest": {"period": {"start": "2025-11-10", "end": "2026-11-10", "annualized_reliable": False}, "portfolios": ports,
                      "benchmark": {"name_ko": "SPY 매수보유 (동일 적립)", "metrics": {"risk": {"ann_vol": 0.136, "max_drawdown": -0.089}, "return": {"total_return": 0.112, "cagr": 0.112}}}},
         "selection": {"as_of_now": {"as_of": "2026-11-10"}, "table": [{"ticker": "MU", "name": "Micron Technology"}]},
         "portfolio": {"backtest_spec": {"period": {"as_of": "2025-11-10"}, "rebalance_rule": {"description_ko": "매월 첫 거래일에 목표 비중으로 리밸런싱"}}},
         "validation": {"criteria": {"target_annual_return": 0.25, "volatility_preference": "medium", "max_weight_per_stock": 0.2, "drift_tolerance": 0.25, "max_drawdown": 0.3},
                        "results": res}}  # fmt: skip
    return R, {p["id"]: p for p in ports}


def _vt_patch(monkeypatch, ports):
    from backend.analysis.m5_backtest_report import report_blocks as B

    names = {"min_variance": "최소분산", "wf_min_variance": "최소분산 (walk-forward)", "equal_weight": "동일비중", "market_cap": "시가총액비중"}
    monkeypatch.setattr(B, "find", lambda R, pid: ports[pid])
    monkeypatch.setattr(B, "pf_label", lambda p: names[p["id"]])


def test_selection_sentence_and_chosen_rows(monkeypatch):
    from backend.analysis.m5_backtest_report import validation_text as VT

    R, ports = _vt_R()
    _vt_patch(monkeypatch, ports)
    assert VT.selection_sentence_ko(R, "min_variance") == "SPY보다 높은 수익률, 최대낙폭 허용 범위(30%) 이내 조건을 모두 맞춘 전략 가운데 샤프 비율이 가장 높은 **최소분산 전략**을 골랐습니다."
    rows = {r["rule"]: r for r in VT.chosen_rows(R, "min_variance")}
    assert [rows[k]["name"] for k in ("R1", "R2", "R3", "R7", "R4b", "R9")] == ["최대낙폭과 허용 한도", "목표 수익률 달성 여부", "비교지수와 수익률 비교", "변동성 기준 충족 여부", "조정일 사이 종목 비중 변화", "주식과 현금 비중"]
    assert [rows[k]["status"] for k in ("R1", "R2", "R3", "R7", "R4b", "R9")] == ["충족", "판정 보류", "충족", "판정 보류", "참고(판정 없음)", "참고(판정 없음)"]
    assert rows["R2"]["msg"] == "기준: 연 25% 목표 수익률. 측정값: 이 기간 수익률 23.8%. 평가 기간이 짧아 판정 보류."
    assert "전체 CAGR" not in rows["R2"]["msg"] and "중립 성향" not in rows["R7"]["msg"]
    assert rows["R7"]["msg"].startswith("기준: 이번 분석에 적용한 중간 변동성 기준 — SPY의 연변동성 13.6%에 1.3을 곱한 17.7% 이하. 측정값: 이 전략의 백테스트 연변동성 33.3%.")
    assert ("포트폴리오 비중을 맞추는 날의 종목당 목표 비중 한도 20%, 조정일 사이에 비중이 크게 벗어났는지 보는 별도 점검 기준 25.0%" in rows["R4b"]["msg"]
            and "20%를 넘은 종목이 하나라도 있던 날 252거래일 중 216일, 25.0%를 넘은 날 16일." in rows["R4b"]["msg"])  # fmt: skip


def test_strategy_rows_tell_selection_pass_warn_and_fail_reasons(monkeypatch):
    from backend.analysis.m5_backtest_report import validation_text as VT

    R, ports = _vt_R()
    _vt_patch(monkeypatch, ports)
    rows = {r["name"]: r for r in VT.strategy_rows(R, "min_variance")}
    assert rows["최소분산"]["status"] == "통과 · 최종 선택"
    assert rows["최소분산"]["reason"] == ("포트폴리오 비중을 맞추는 날마다 백테스트 시작일에 정한 목표 비중으로 되돌리는 방식입니다. "
                                      "SPY보다 높은 수익률, 최대낙폭 허용 범위(30%) 이내 조건을 모두 맞춘 전략 가운데 샤프 비율이 가장 높아 골랐습니다.")  # fmt: skip
    assert rows["최소분산 (walk-forward)"]["status"] == "통과"
    assert rows["최소분산 (walk-forward)"]["reason"] == ("포트폴리오 비중을 맞추는 날마다(매월) 그때까지의 자료로 목표 비중을 새로 계산하는 방식입니다. "
                                                      "샤프 비율 0.48이 최소분산의 0.59보다 낮아 선택하지 않았습니다.")  # fmt: skip
    assert rows["동일비중"] == {"name": "동일비중", "status": "주의", "reason": "동일비중 전략의 같은 기간 수익률은 8.9%로 SPY의 11.2%보다 낮았습니다."}
    assert rows["시가총액비중"]["status"] == "미통과"
    assert rows["시가총액비중"]["reason"] == "포트폴리오 비중을 맞추는 날 한 종목의 포트폴리오 비중이 최대 26.3%로, 종목당 한도 20%를 넘었습니다. 가격 자료가 180일치로, 백테스트 기간에 필요한 252일보다 짧았습니다."


def test_ensure_validation_text_drops_screen_caution_and_table_repeats(monkeypatch):
    from backend.analysis.m5_backtest_report.report import ensure_validation_text

    R, ports = _vt_R()
    _vt_patch(monkeypatch, ports)
    interp = {"validation_ko": ["검증은 추천: 최소분산으로 표시됐습니다. 추천은 후보들 사이의 순위에 따른 선택이며, 목표 달성이나 미래 성과를 뜻하지 않습니다. 평가 기간이 짧아 목표 수익률은 판정을 보류했습니다.",
                                "화면 주의는 EchoStar(+7.1%p)가 현재 구성에 없고 비중 합이 68%라는 뜻입니다. 검증에서는 연변동성 33.3%가 중립 성향 기준보다 높았습니다."]}  # fmt: skip
    assert ensure_validation_text(interp, R, "min_variance")
    assert interp["validation_ko"] == ["SPY보다 높은 수익률, 최대낙폭 허용 범위(30%) 이내 조건을 모두 맞춘 전략 가운데 샤프 비율이 가장 높은 **최소분산 전략**을 골랐습니다. 평가 기간이 짧아 목표 수익률은 판정을 보류했습니다."]
    assert not ensure_validation_text(interp, R, "min_variance")


def test_override_replaces_validation_text_and_tables():
    from backend.analysis.m5_backtest_report import text_overrides as T

    old = lambda t: {"type": "table", "title_ko": t, "group_ko": "검증 상세", "group_open": True, "columns": [], "rows": []}  # noqa: E731
    doc = {"sections": [{"id": "performance", "blocks": [{"type": "paragraphs", "src": "14a", "items": ["성과 해석"]},
                                                         {"type": "paragraphs", "src": "14a", "group_ko": "검증 상세", "group_open": True, "items": ["옛 문단"]},
                                                         old("검증 규칙 (최소분산)"), old("전체 포트폴리오 검증 요약"), {"type": "callout", "group_ko": "검증 상세"}]}]}  # fmt: skip
    new = [{"type": "table", "title_ko": "선택 전략의 조건별 결과 (최소분산)", "columns": [], "rows": []}, {"type": "table", "title_ko": "전략별 점검 결과", "columns": [], "rows": []}]
    out = T.apply(doc, {"validation_ko": ["새 문단"], "validation_tables": new})
    bl = out["sections"][0]["blocks"]
    assert bl[0]["items"] == ["성과 해석"] and bl[1]["items"] == ["새 문단"]
    assert [bl[2]["title_ko"], bl[3]["title_ko"]] == ["선택 전략의 조건별 결과 (최소분산)", "전략별 점검 결과"] and bl[2]["group_ko"] == "검증 상세"
    assert bl[4]["type"] == "callout" and out["text_override"]["sections"] == ["validation", "validation_tables"]


def test_plain_cash_capacity_reason_ends_with_period(monkeypatch):
    """검증 메시지에서 꺼낸 '…투자 비율이 올라갑니다' 뒤에 마침표가 없어 다음 문장과 붙던 것 (2026-11-19 검증에서 발견)."""
    from backend.analysis.m5_backtest_report import caution_text as C

    msg = "투자 80%, 현금 20% — 백테스트 시작일 구성은 섹터 상한 80% 때문에 80%까지만 담겨 20%를 더 넣지 못했습니다. 섹터 상한을 올리거나 테마를 넓히면 투자 비율이 올라갑니다"
    R, p = _ct_R(checks=[{"rule": "R9", "ok": False, "status": "info", "value": 0.8, "message_ko": msg}])
    _ct_find(monkeypatch, p)
    t = " ".join(C.plain_info(R, "mv"))
    assert "투자 비율이 올라갑니다. 현금은 이자 없이 계산해" in t
