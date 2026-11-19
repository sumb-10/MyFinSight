"""2026-11-18 리포트 문체(사용자 요청: 리포트 글의 AI 티를 빼고 애널리스트가 설명하듯 쉽게)의 회귀 테스트.

- 리포트 글을 쓰는 프롬프트(06·14a·14b·14c·14d)가 같은 문체 지침(`prompts/_report_style.md`)을 `{{include:…}}` 로 나눠 쓴다.
- 화면 코드가 읽어 들이는 서버 문장 틀은 바꾸지 않는다: 뉴스 투자 의견 한 줄(ViewCard.tsx 의 parseViewLine 이 읽는다).
- 옛 실행 결과(13단계에 저장된 깔때기 이름·공지)의 내부 말은 리포트를 만들 때 지금 말로 바꾼다.
- 쉬운 말 서술이 빠진 이유를 숫자로 옮겨도('부채비율 1,712%') '결과에 없는 숫자' 로 세지 않는다.
"""

from __future__ import annotations

import re

from backend.analysis.common.prompts import load_prompts
from backend.analysis.m4_portfolio.black_litterman import view_summary
from backend.analysis.m5_backtest_report import report_blocks as B
from backend.analysis.paths import PROMPTS


def test_report_prompts_share_the_style_guide():
    style = (PROMPTS / "_report_style.md").read_text(encoding="utf-8").strip()
    for stage in ("06_explain", "14a_interpret", "14b_narrate", "14c_market", "14d_header"):
        system, _ = load_prompts(stage)
        assert "{{include:" not in system and style in system, stage
    assert "투자 의견" in style and "분석 모델이 뉴스를 읽고 제안한 투자 의견" in style  # 뉴스 뷰의 뜻 (사용자, 2026-11-18)


def test_view_line_keeps_the_format_the_screen_reads():
    """ViewCard.tsx 의 parseViewLine 정규식과 같은 틀. 틀이 바뀌면 화면 카드가 원문 그대로 그려진다."""
    up = {"type": "absolute", "long": ["NVDA"], "short": [], "direction": "up", "strength": "medium", "prior_return": 0.12,
          "expected_return_annual": 0.18, "confidence": 0.5, "rationale_ko": "수주 소식"}  # fmt: skip
    abs_re = r"^\[(절대)\] (\S+) (오름|내림)\((약|중|강)\) — 사전 기대 ([+\-−]?[\d.]+%) → 뷰 ([+\-−]?[\d.]+%)\/년 \(신뢰 ([\d.]+)\) — ([\s\S]+)$"
    assert re.match(abs_re, view_summary(up)), view_summary(up)
    rel = {"type": "relative", "long": ["AMD"], "short": ["INTC"], "direction": "up", "strength": "weak", "prior_return": -0.10,
           "expected_return_annual": -0.06, "confidence": 0.25, "rationale_ko": "r"}  # fmt: skip
    assert view_summary(rel).startswith("[상대] AMD > INTC (약) — 기대 차이를 AMD 쪽으로 +4.0%p (사전 차이 -10.0% → 뷰 반영 차이 -6.0%/년")


def test_old_results_get_plain_words():
    R = {"selection": {"funnel": [{"label_ko": "투자 가능 종목 (SP500 ∪ NASDAQ100)"}, {"label_ko": "후보 조건 통과 (빠짐: 시가총액 1개)"},
                                  {"label_ko": "테마 해당 판정 (분석 모델, 신뢰도 ≥ 0.5) · 테마에 해당하지 않는다고 판정된 3개: A, B, C"},
                                  {"label_ko": "선정 지표(ROE) 계산 가능·자격선 안 7개 + 필수 포함 3개(그중 지표 없음·자격선 밖 1개: ASML(지표 없음))"},
                                  {"label_ko": "백테스트용 재선정 (2022-11-07)"}],
                       "explained": {"portfolio_summary_ko": "자격선 (LLM 문장)"}},
         "notices": [{"code": "too_few_eligible", "message_ko": "선정 지표가 자격선 안에 드는 종목이 2개라 (자격선 밖 1개 제외: X -1.0%)"}]}  # fmt: skip
    out = B.plain_old_results(R)
    assert [f["label_ko"] for f in out["selection"]["funnel"]] == [
        "투자 가능 종목 (SP500·NASDAQ100)", "기본 조건 통과 (빠짐: 시가총액 1개)",
        "테마에 맞는 종목 (분석 모델이 따져 봄, 확신도 0.5 이상) · 테마에 맞지 않는다고 본 3개: A, B, C",
        "선정 지표(ROE)를 계산할 수 있고 기준 안인 7개 + 필수 포함 3개(그중 지표가 없거나 기준 밖인 1개: ASML(지표 없음))",
        "백테스트 시작일에 다시 고른 종목 (2022-11-07)"]  # fmt: skip
    assert out["notices"][0]["message_ko"] == "선정 지표가 기준 안에 드는 종목이 2개라 (기준 밖 1개 제외: X -1.0%)" and out["notices"][0]["code"] == "too_few_eligible"
    assert out["selection"]["explained"]["portfolio_summary_ko"] == "자격선 (LLM 문장)" and R["selection"]["funnel"][1]["label_ko"].startswith("후보 조건")  # 원본은 그대로


def test_numbers_in_selection_reasons_are_known():
    from backend.analysis.m5_backtest_report.report_check import _code_strings, _string_numbers

    R = {"selection": {"backtest_as_of": {"removed_reasons_ko": [{"ticker": "LII", "reason_ko": "부채비율 1,712%로 상한 300% 초과 (재무 건전성 조건)"}]},
                       "explained": {"portfolio_summary_ko": "LLM 문장 4,321%"}}}  # fmt: skip
    acc: set[float] = set()
    _string_numbers(_code_strings(R), acc)
    assert 1712 in acc and 4321 not in acc
