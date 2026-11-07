"""2026-11 시나리오 QA 라운드 22 (076~080) 회귀 테스트."""

from __future__ import annotations


def test_bl_optimizer_does_not_stop_at_a_degenerate_start():
    """080 (라운드 22): 정보기술·커뮤니케이션 둘 다 섹터 상한 50% 에 닿고 합계 100% 인 날, 오름 뷰 종목은 '뷰 방향 유지' 하한·GOOGL 은 상한에 닿아
    SLSQP 가 기준 비중에서 '성공' 으로 멈췄다 — GOOGL(상대 뷰의 약한 쪽)→META(뷰 없음)로 옮기면 목적값이 오르는데 뷰가 하나도 반영되지 않았다(76일 중 5일).
    다른 시작점에서도 풀어 가장 좋은 해를 쓴다."""
    import numpy as np

    from backend.analysis.m4_portfolio import math as P

    cov = np.array([[0.126223, 0.109979, 0.06623, 0.082206, 0.072388], [0.109979, 0.125625, 0.066598, 0.086676, 0.075352],
                    [0.06623, 0.066598, 0.103049, 0.09841, 0.054371], [0.082206, 0.086676, 0.09841, 0.241295, 0.06624],
                    [0.072388, 0.075352, 0.054371, 0.06624, 0.153471]])  # fmt: skip
    mu = np.array([0.098215, 0.099788, 0.075889, 0.110927, 0.116712])
    wb = np.array([0.171864, 0.172273, 0.302388, 0.197611, 0.155862])
    sec = ["45", "45", "50", "50", "45"]  # CDNS·SNPS·PANW = 정보기술, GOOGL·META = 커뮤니케이션 (각 50%)
    w, active = P.optimize_utility(mu, cov, 0.8176, wb, 0.35, 0.5, sec, 0.1166666667, 1.0, min_weight=0.01, view_dir=[1, 1, -1, 0, 1])
    d = w - wb / wb.sum()
    assert d[2] < -0.01 and d[3] > 0.01  # GOOGL 줄고 META 늘어남 (뷰 방향 그대로)
    assert np.all(d[[0, 1, 4]] >= -1e-8)  # 오름 뷰 종목은 기준 아래로 가지 않음
    obj = lambda x: x @ mu - 0.8176 / 2 * x @ cov @ x  # noqa: E731
    assert obj(w) > obj(wb / wb.sum()) + 1e-4


def test_views_ask_again_for_unknown_evidence_ids_and_note_dropped_views():
    """076: GEN 뷰가 근거 ev1536614 를 ev1536611 로 잘못 적어 말없이 빠졌는데 세트 설명에는 GEN 이야기가 남았다.
    처음 답에 목록에 없는 id 가 있으면 한 번 다시 받고(두 번째 답이 맞으면 그대로 쓴다), 그래도 근거가 없는 뷰는 빼며 설명에 밝힌다."""
    import datetime as dt
    from types import SimpleNamespace

    import pandas as pd

    from backend.analysis.common.llm import StubLlm
    from backend.analysis.m4_portfolio.views import generate_views
    from backend.analysis.settings import AnalysisSettings

    date = dt.date(2024, 1, 2)
    view = SimpleNamespace(as_of=date, adj_close=lambda *a, **kw: pd.DataFrame({"A": [100, 110], "B": [100, 105]}))
    evidence = SimpleNamespace(start=date - dt.timedelta(days=30), end=date, dc_start=None, disclosures=[],
                               by_ticker={"A": ["ev123"], "B": ["ev456"]}, has_evidence=lambda t: True, ids={"ev123", "ev456"},
                               records=[{"ticker": "A", "evidence_id": "ev123", "published_at": "2024-01-01", "title": "a"},
                                        {"ticker": "B", "evidence_id": "ev456", "published_at": "2024-01-01", "title": "b"}])  # fmt: skip
    mm = {key: {"A": 0.1, "B": 0.1} for key in ["ann_vol", "cap_weights", "implied_returns"]}
    intent = {"news_tilt": {"max_view_confidence": 0.5}, "interpretation": {"themes": [], "summary_ko": "테마"}}

    def ans(ids_a):
        return {"sets": [{"scenario_id": "s", "narrative_ko": "A 소식과 B 소식.", "views": [
            {"type": "absolute", "long": ["A"], "short": [], "direction": "up", "strength": "weak", "confidence": 0.4, "evidence_ids": ids_a},
            {"type": "absolute", "long": ["B"], "short": [], "direction": "up", "strength": "weak", "confidence": 0.4, "evidence_ids": ["ev456"]}]}]}

    args = (view, ["A", "B"], mm, {"A": 0.5, "B": 0.5}, intent, SimpleNamespace(by_ticker=lambda t: {}), AnalysisSettings())
    # 다시 받은 답이 맞으면 그 답을 쓴다
    sets, _ = generate_views(*args, StubLlm({"09_views_news": [ans(["ev121"]), ans(["ev123"])]}), evidence, n_sets=1, views_per_set=4)
    assert [v["long"] for v in sets[0]["views"]] == [["A"], ["B"]]
    # 두 번 다 틀리면 그 뷰는 빼고 설명에 밝힌다
    sets, warns = generate_views(*args, StubLlm({"09_views_news": ans(["ev121"])}), evidence, n_sets=1, views_per_set=4)
    assert [v["long"] for v in sets[0]["views"]] == [["B"]] and "근거 기사를 확인할 수 없는 뷰(A)는 반영하지 않았습니다." in sets[0]["narrative_ko"]


def test_stuck_note_says_conflicting_views_cancel_out():
    """076: 같은 세트의 'CRWD 내림' 과 'CRWD > MSFT' 가 서로 상쇄돼 CRWD 가 기준 비중에 머물렀는데 '상한·섹터 예산 같은 제약 때문' 이라고 썼다."""
    from backend.analysis.m5_backtest_report import report_blocks as B

    R = {"request": {"constraints": {"max_weight_per_stock": 0.25}}, "parameters": {"portfolio": {"min_weight": 0.01}},
         "selection": {"table": [{"ticker": "CRWD", "name": "CrowdStrike"}]}}  # fmt: skip
    p = {"views_applied": [{"type": "absolute", "direction": "down", "long": ["CRWD"], "short": []}, {"type": "relative", "long": ["CRWD"], "short": ["MSFT"]},
                           {"type": "absolute", "direction": "up", "long": ["IBM"], "short": []}],
         "weights": {"CRWD": 0.0682, "MSFT": 0.20, "IBM": 0.30}, "delta_vs_baseline": {"CRWD": -0.00049, "MSFT": -0.0249, "IBM": 0.0448}, "active_constraints": []}  # fmt: skip
    assert "방향이 엇갈린 뷰(오름·내림)가 함께 있어 서로 상쇄되어" in B.view_stuck_note(R, p)


def test_baseline_conflict_is_not_asked_when_caps_force_equal_weights():
    """079: 5종목 × 종목당 상한 18% = 투자 비율 90% 라 네 비중 규칙이 모두 18% 인데 '동일비중 vs 역변동성' 을 물었고 답이 기준 비중을 바꿨다."""
    from backend.analysis.m1_request.dialog import _rules_collapse_to_caps

    assert _rules_collapse_to_caps({"constraints": {"num_holdings": {"target": 5}, "max_weight_per_stock": 0.18, "min_cash_ratio": 0.10}})
    assert not _rules_collapse_to_caps({"constraints": {"num_holdings": {"target": 10}, "max_weight_per_stock": 0.18, "min_cash_ratio": 0.10}})


def test_korean_titles_of_unlisted_sibling_companies_do_not_count():
    """077: 셀트리온 뉴스 10건 중 9건이 셀트리온제약 기사(유니버스 밖 계열사)였고 그 기사가 '셀트리온 오름' 뷰의 근거가 됐다."""
    from backend.db.analysis_readers import _title_mentions

    names = ["셀트리온", "068270"]
    assert not _title_mentions("셀트리온제약, 벡톤디킨슨과 프리필드시린지 위탁생산 협력", names)
    assert not _title_mentions("셀트리온헬스케어 합병 완료", names)
    assert _title_mentions("셀트리온 바이오시밀러 미국 승인", names)  # 띄어 쓰면 같은 회사 이야기
    assert _title_mentions("셀트리온, 셀트리온제약 지분 매각", names)
    assert not _title_mentions("녹십자홀딩스 배당", ["녹십자", "006280"]) and not _title_mentions("미래에셋생명 배당", ["미래에셋증권", "미래에셋"])
    assert _title_mentions("미래에셋증권 1분기 실적", ["미래에셋증권", "미래에셋"])


def test_news_of_a_reused_ticker_before_the_switch_is_dropped():
    """078: Physicians Realty(2024-03 전 DOC)의 배당 기사가 Healthpeak(지금 DOC)의 'DOC 오름' 뷰 근거가 돼 추천안 DOC 비중이 1.0% → 4.75%."""
    import datetime as dt
    from types import SimpleNamespace

    from backend.analysis.m2_data import news as N
    from backend.analysis.settings import AnalysisSettings

    assert N.TICKER_REUSE["DOC"] == "2024-03-04"
    rows = [SimpleNamespace(news_id=1, asset_id="US-DOC", published_at=dt.datetime(2023, 12, 28, tzinfo=dt.UTC), source="ALPACA_NEWS", publisher="benzinga",
                            title="Last Chance To Buy Physicians Realty Trust", url="u", language="en"),
            SimpleNamespace(news_id=2, asset_id="US-DOC", published_at=dt.datetime(2024, 3, 6, tzinfo=dt.UTC), source="ALPACA_NEWS", publisher="benzinga",
                            title="Healthpeak raises guidance", url="u", language="en")]  # fmt: skip
    repo = SimpleNamespace(get_news_batch=lambda *a, **kw: rows)
    md = SimpleNamespace(repo=repo, s=AnalysisSettings(), asset_id=lambda t: f"US-{t}", assets={}, market_of=lambda t: "US")
    win = N.build_window(md, ["DOC"], dt.date(2024, 3, 10), days=90, per_ticker=10, languages=["en"], min_tickers=1)
    assert [r["evidence_id"] for r in win.records] == ["ev2"]


def test_removed_last_evidence_id_leaves_no_dangling_comma():
    """078: 없는 id 를 지우자 '(ev1546230, )' 가 남았다."""
    from backend.analysis.m4_portfolio.views import _strip_unlisted_ids

    assert _strip_unlisted_ids("UPS 전망 약화 보도(ev1546230, ev1554595)를 부담으로", {"ev1546230"}) == "UPS 전망 약화 보도(ev1546230)를 부담으로"
    assert _strip_unlisted_ids("보도(ev1554595)", {"ev1546230"}) == "보도"


def test_risk_gap_caution_when_current_holdings_are_much_riskier(monkeypatch):
    """080: 지금 구성의 예상 변동성 41.9% (RDDT·PLTR) 인데 백테스트 바구니의 실현 변동성은 28.0% — 결론 주의가 없었다 (Q-291 의 남은 부분)."""
    from backend.analysis.m5_backtest_report import report_blocks as B

    monkeypatch.setattr(B, "find", lambda R, pid: {"id": pid, "kind": "template", "metrics": {"risk": {"ann_vol": 0.2795}}})
    R = {"portfolio": {"forward": {"templates": [{"id": "equal_weight", "weights": {"A": 0.5, "B": 0.5}, "ex_ante": {"vol": 0.4185}}]}}}
    assert B.risk_gap_note(R, "equal_weight").startswith("지금 구성의 예상 연변동성(최근 자료로 추정) 41.9%가 백테스트 실현 변동성 28.0%보다 크게 높습니다")
    R["portfolio"]["forward"]["templates"][0]["ex_ante"]["vol"] = 0.33  # 1.18배는 말하지 않는다
    assert B.risk_gap_note(R, "equal_weight") is None


def test_parameter_table_shows_the_walkforward_delta_range_and_mode_in_korean():
    """078: 계산 조건 표가 시작일 δ 1.9999 만 적어 날짜별 δ 2.0~8.0(상한 8) 이 안 보였다. 079: '백테스트 방식: static_weights + walkforward'."""
    from backend.analysis.m5_backtest_report import report_blocks as B
    from backend.analysis.m5_backtest_report.report import _mode_ko

    R = {"portfolio": {"walkforward": {"market_models_by_date": {"2023-03-13": {"delta": 1.9999}, "2024-01-02": {"delta": 2.4306}, "2026-01-02": {"delta": 8.0}}}}}
    assert B._wf_delta_ko(R) == " · 날짜별(walk-forward) δ 1.9999~8 (상한 8 적용 날짜 포함)"
    assert B._wf_delta_ko({"portfolio": {}}) == ""
    assert _mode_ko("static_weights + walkforward") == "정적 구성(시작일 비중으로 리밸런싱) + 날짜별 재계산(walk-forward)"
