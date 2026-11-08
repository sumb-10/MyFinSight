"""리포트 머리말(14d): 짧은 제목 + '요청 → 어떻게·왜 처리했는지' 요약. 사실 묶음, 검사, 실패하면 코드 제목으로, 확인 질문 기록 (2026-11-08)."""

from __future__ import annotations

import copy
from types import SimpleNamespace

from backend.analysis.common.llm import StubLlm
from backend.analysis.executor.worker import _dialog_log
from backend.analysis.m5_backtest_report import report_blocks as B
from backend.analysis.m5_backtest_report.report import call_header, facts_for_header
from backend.analysis.m5_backtest_report.report_check import check_header
from backend.analysis.settings import AnalysisSettings
from backend.tests.analysis.test_pipeline_e2e import e2e  # noqa: F401 — 모듈 범위 픽스처 재사용

GOOD = {"title_ko": "미국 반도체 모멘텀 투자", "summary_ko": "미국 반도체 기업에 3년 투자하고 싶다는 요청입니다. 답하신 대로 종목 수를 줄였습니다."}


def test_check_header_rules():
    s = AnalysisSettings()
    facts = {"conditions": {"max_weight_per_stock": "34%"}}
    assert check_header(GOOD, facts, s) == []
    assert check_header({**GOOD, "summary_ko": GOOD["summary_ko"].replace("줄였습니다.", "종목당 상한을 34%로 올렸습니다.")}, facts, s) == []
    assert check_header({**GOOD, "title_ko": "미국 반도체 기업 가운데 최근 주가 흐름이 좋은 곳에 투자"}, facts, s)  # 제목이 길다
    assert check_header({**GOOD, "title_ko": "미국 반도체 투자."}, facts, s)  # 마침표
    assert check_header({**GOOD, "summary_ko": "미국 반도체 기업에 3년 투자하고 싶다는 요청입니다."}, facts, s)  # 한 문장
    errs = check_header({**GOOD, "summary_ko": GOOD["summary_ko"].replace("줄였습니다.", "종목당 상한을 40%로 올렸습니다.")}, facts, s)
    assert errs == ["number 40% not found in facts"]
    assert any("banned phrase" in e for e in check_header({**GOOD, "summary_ko": GOOD["summary_ko"] + " 수익이 보장됩니다."}, facts, s))


def test_dialog_log_keeps_answered_questions_and_revision():
    doc = SimpleNamespace(mode="revision", revision=SimpleNamespace(text="종목을 5개로 줄여 주세요"),
                          questions=[SimpleNamespace(question_ko="후보가 3개뿐입니다. 어떻게 할까요?", answer="종목 수를 3개로", answered_at="2026-11-08T10:00:00"),
                                     SimpleNamespace(question_ko="건너뛴 질문", answer=None, answered_at=None)])
    assert _dialog_log(doc) == [{"question_ko": "후보가 3개뿐입니다. 어떻게 할까요?", "answer_ko": "종목 수를 3개로"},
                                {"question_ko": "조건 수정 요청", "answer_ko": "종목을 5개로 줄여 주세요"}]


def test_facts_split_idea_and_answers(e2e):
    ctx, _ = e2e
    R = copy.deepcopy(ctx.outputs["13_results"])
    assert R["dialog"] == []  # 개발 CLI 실행은 대화가 없다
    R["request"]["natural_language"]["idea"] = "반도체에 3년 투자하고 싶어요.\n\n[보충 답변]\n- [테마 넓히기] 인접 산업까지 넓혀 주세요"
    R["dialog"] = [{"question_ko": "후보가 0개입니다", "answer_ko": "테마를 넓혀 다시 해석"}]
    chosen, _ = B.chosen_portfolio_id(R)
    f = facts_for_header(R, chosen)
    assert f["idea_ko"] == "반도체에 3년 투자하고 싶어요." and f["clarifications_ko"] == ["[테마 넓히기] 인접 산업까지 넓혀 주세요"]
    assert f["answers"] == R["dialog"] and f["conditions"]["max_weight_per_stock"].endswith("%")
    assert "backtest" not in f and "performance" not in str(f)  # 성과는 머리말 몫이 아니다


def test_header_call_falls_back_when_answer_fails_checks(e2e):
    ctx, _ = e2e
    R = ctx.outputs["13_results"]
    chosen, _ = B.chosen_portfolio_id(R)
    s = AnalysisSettings()
    assert call_header(R, chosen, StubLlm({"14d_header": GOOD}), s) == GOOD
    bad = {"title_ko": "아주 긴 제목이 들어와서 스물네 글자를 훌쩍 넘기는 경우입니다", "summary_ko": "한 문장뿐입니다."}
    assert call_header(R, chosen, StubLlm({"14d_header": [bad, bad]}), s) is None


def test_theme_gap_reason_when_every_eligible_stock_was_taken(e2e):
    ctx, _ = e2e
    R = copy.deepcopy(ctx.outputs["13_results"])
    th = R["intent"]["interpretation"]["themes"]
    R["intent"]["interpretation"]["themes"] = [th[0], {**th[0], "id": "games", "label_ko": "게임"}]
    sm = R["selection"]["as_of_now"].setdefault("summary", {})
    sm.update({"n_with_metric": 3, "n_selected": 3, "n_forced": 0})
    assert "선정 기준을 넘은 종목이 없음" in B.selection_notes(R)["theme_gap_note_ko"]
    sm.update({"n_with_metric": 9})
    assert "순위에서 앞섬" in B.selection_notes(R)["theme_gap_note_ko"]
