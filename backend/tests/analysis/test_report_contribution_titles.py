"""성과 해석의 수익 기여 문장과 「다음 분석에서 바꿔 볼 조건」 카드 제목 (2026-11-19 사용자 요청)."""

from backend.analysis.m5_backtest_report import report as RP


def _R(monkeypatch, contrib, total=0.275):
    p = {"id": "c", "ticker_contribution": contrib, "metrics": {"return": {"total_return": total}}}
    monkeypatch.setattr(RP.B, "find", lambda R, pid: p)
    return {"selection": {"table": [{"ticker": "MU", "name": "Micron Technology"}, {"ticker": "TXN", "name": "Texas Instruments"}]}}


def test_contribution_sentence_names_top_two_positive(monkeypatch):
    R = _R(monkeypatch, {"MU": 0.179, "TXN": 0.084, "X": -0.02})
    assert RP.contribution_sentence(R, "c") == "전체 수익률 27.5% 가운데 **Micron Technology가 17.9%p**를 벌어 가장 많이 보탰고, Texas Instruments가 8.4%p로 뒤를 이었습니다."
    R = _R(monkeypatch, {"MU": 0.179, "X": -0.02})
    assert RP.contribution_sentence(R, "c") == "전체 수익률 27.5% 가운데 **Micron Technology가 17.9%p**를 벌어 가장 많이 보탰습니다."
    R = _R(monkeypatch, {"X": -0.02})
    assert RP.contribution_sentence(R, "c") is None


def test_ensure_contribution_sentence_replaces_old_wording(monkeypatch):
    R = _R(monkeypatch, {"MU": 0.179, "TXN": 0.084})
    interp = {"performance_ko": ["수익률은 27.5%였습니다. 수익 기여도는 Micron Technology가 +17.9%p, Texas Instruments가 +8.4%p였습니다. 최대낙폭은 20%였습니다."]}
    assert RP.ensure_contribution_sentence(interp, R, "c") is True
    t = interp["performance_ko"][0]
    assert "수익 기여도는" not in t and "**Micron Technology가 17.9%p**를 벌어 가장 많이 보탰고" in t
    assert t.startswith("수익률은 27.5%였습니다.") and t.endswith("최대낙폭은 20%였습니다.")
    assert RP.ensure_contribution_sentence(interp, R, "c") is False  # 이미 있으면 그대로
    none = {"performance_ko": ["수익률은 27.5%였습니다."]}
    assert RP.ensure_contribution_sentence(none, R, "c") is True  # 모델이 기여를 쓰지 않았으면 마지막 문단으로
    assert none["performance_ko"][0] == "수익률은 27.5%였습니다." and none["performance_ko"][1].startswith("전체 수익률 27.5% 가운데 **Micron Technology가")
    assert RP.ensure_contribution_sentence({"performance_ko": []}, R, "c") is False  # 성과 해석이 없으면 그대로


def test_next_action_cards_use_titles_only_when_aligned():
    interp = {"next_actions_ko": ["a", "b"], "next_action_titles_ko": ["**기간을 3년으로 늘려 보기**", "업종 상한 낮춰 보기"]}
    assert [c["title_ko"] for c in RP.next_action_cards(interp)] == ["기간을 3년으로 늘려 보기", "업종 상한 낮춰 보기"]
    interp["next_action_titles_ko"] = ["하나뿐"]
    assert [c["title_ko"] for c in RP.next_action_cards(interp)] == ["선택지 1", "선택지 2"]
    assert [c["text_ko"] for c in RP.next_action_cards(interp)] == ["a", "b"]
