"""라운드 4 경고 계약: 카탈로그 렌더, 영어 원문 → 코드 변환, 같은 종류 묶기, 수준별 노출."""

from __future__ import annotations

from backend.analysis.common.warnings import CATALOG, by_level, from_text, make, merge, render


def test_catalog_renders_every_code_in_korean():
    sample = {"tickers": ["NVDA"], "names": "Tech", "n": 3, "target": 10, "selected": 3, "metric": "PER", "cash": "15%", "text": "원문", "date": "2024-01-02",
              "days": 756, "rate": "1,300.00", "usd": "7,000", "usd0": "7,100", "min": 3, "rules": "최대낙폭(R1) 4개", "reason": "x"}  # fmt: skip
    for code in CATALOG:
        w = make("05_selection", code, **sample)
        assert w.code == code and w.message_ko and "{" not in w.message_ko, code
        assert any("가" <= ch <= "힣" for ch in w.message_ko), code  # 한글 포함


def test_from_text_maps_known_english_and_keeps_unknown_as_debug():
    w = from_text("05_selection", "weight capacity 0.85 < 1.00: caps cannot absorb the capital with these sectors (cap needed 0.55)")
    assert w.code == "weight_capacity" and w.level == "user" and "15%" in w.message_ko
    w2 = from_text("10_targets", "caps allow at most 85% invested (stock 15%, sector 40%, 15 names): 15% kept as cash; relax the caps")
    assert w2.code == "weight_capacity"
    w3 = from_text("07_backtest_spec", "screen@2009-12-31: only 4 tickers have pe_ttm; target 10 -> selecting 4")
    assert w3.code == "too_few_with_metric" and w3.dates == ["2009-12-31"] and "PER" in w3.message_ko
    w4 = from_text("12_validation", "no portfolio passed the hard rules (fail counts by rule: {'R6': 9, 'R1': 4}); recommended=null")
    assert w4.level == "user" and "종목 수(R6) 9개" in w4.message_ko and "최대낙폭(R1) 4개" in w4.message_ko
    w5 = from_text("03_candidates", "candidate cap 120 applied (ranked by matched rules, then liquidity)")
    assert w5.code == "legacy_note" and w5.level == "debug" and w5.details["text"].startswith("candidate cap")
    w6 = from_text("10w_paths", "2009-12-31: 2009-12-31: 뉴스가 있는 종목 0개 < 최소 3개: 뷰를 만들지 않고 기준 비중을 사용")
    assert w6.code == "news_thin_fallback" and w6.level == "info" and w6.dates == ["2009-12-31"]
    w7 = from_text("01_request", "2020-12-31 이전 사전 버전이 없어 2026-10-04 버전을 씀 (당시 구성종목 미확보, 생존 편향 가능)")
    assert w7.code == "descriptor_version_fallback" and w7.level == "info" and "생존 편향" in w7.message_ko


def test_merge_collapses_repeats_and_render_shows_count_and_span():
    ws = [from_text("10w_paths", f"{d}: 뉴스가 있는 종목 {i % 3}개 < 최소 3개: 뷰를 만들지 않고 기준 비중을 사용") for i, d in enumerate(["2009-12-31", "2010-02-01", "2010-03-01", "2015-10-01"])]
    ws += [from_text("05_selection", "weight capacity 0.85 < 1.00: caps cannot absorb the capital (cap needed 0.55)"), from_text("10_targets", "caps allow at most 85% invested (stock 15%, sector 40%, 15 names): 15% kept as cash")]
    m = merge(ws)
    assert len(m) == 2
    news = next(w for w in m if w.code == "news_thin_fallback")
    assert news.count == 4 and render(news).endswith("(4회, 2009-12-31~2015-10-01)")
    cap = next(w for w in m if w.code == "weight_capacity")
    assert cap.count == 2 and cap.stage == "05_selection"  # 첫 등장 단계 유지
    assert [w.code for w in by_level(m, "user")] == ["weight_capacity"]


def test_backtest_start_clamp_is_user_level_but_holiday_shift_is_info():
    """요청한 시작(2005)이 자료 시작(2010-04) 전이라 옮긴 것은 사용자가 알아야 할 일(user); 기준일 휴장일 이동은 참고(info)."""
    from backend.analysis.common.warnings import from_text

    w = from_text("01_request", "저PER 선정에 쓰는 재무 지표 자료가 2010-04-01 부터 있어 백테스트 시작을 2004-12-30 → 2010-04-01 로 옮김")
    assert w.code == "backtest_start_clamped" and w.level == "user" and "2010-04-01" in w.message_ko
    w2 = from_text("01_request", "기준일 2016-12-31 은 일부 시장(US)의 휴장일이라 모두 거래한 2016-12-30 로 옮김")
    assert w2.code == "derived_note" and w2.level == "info"
