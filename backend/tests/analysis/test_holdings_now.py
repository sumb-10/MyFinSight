"""분석 기준일 구성 = 백테스트에서 꺼낸 보유 종목·비중 (2026-11-19 사용자 결정): 시작일 종목 유지 · 직전 리밸런싱 목표 비중."""

from backend.analysis.m4_portfolio.holdings_now import holdings_now, target_on


def test_static_keeps_start_target_and_walkforward_uses_last_rebalance_on_or_before_as_of():
    ports = [
        {"id": "equal_weight", "kind": "template", "name_ko": "동일비중", "target_weights": {"A": 0.5, "B": 0.5}},
        {"id": "wf_min_variance", "kind": "template", "weights_by_date": {"2025-11-18": {"A": 0.6, "B": 0.4}, "2026-11-02": {"A": 0.7, "B": 0.3}, "2026-12-01": {"A": 0.1, "B": 0.9}}},
        {"id": "dd_match_equal_weight", "kind": "matched", "target_weights": {"A": 0.3, "B": 0.3}},
        {"id": "empty", "kind": "template", "target_weights": {}},
    ]
    hn = holdings_now(ports, "2026-11-18", "2025-11-18")
    assert hn["equal_weight"] == {"weights": {"A": 0.5, "B": 0.5}, "cash_weight": 0.0, "rebalance_date": "2025-11-18", "mode": "static", "name_ko": "동일비중", "kind": "template"}
    assert hn["wf_min_variance"]["weights"] == {"A": 0.7, "B": 0.3} and hn["wf_min_variance"]["rebalance_date"] == "2026-11-02"  # 분석 기준일 뒤(12-01)는 쓰지 않는다
    assert hn["dd_match_equal_weight"]["cash_weight"] == 0.4  # 현금을 섞은 안은 주식 + 현금 그대로
    assert "empty" not in hn
    # 분석 기준일이 리밸런싱일이면 그날 비중
    assert target_on(ports[1], "2026-11-02") == ({"A": 0.7, "B": 0.3}, "2026-11-02")
