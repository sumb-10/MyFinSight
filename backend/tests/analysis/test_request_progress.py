"""새 요청 첫 해석의 진행 단계 (m1_request/progress.py) 와 분류 묶음 알림 (classify on_batch)."""

from __future__ import annotations

from backend.analysis.common.llm import StubLlm
from backend.analysis.m1_request.progress import Progress, screen_ko, themes_ko
from backend.analysis.m3_selection.classify import classify
from backend.analysis.schemas.selection import Candidates


def test_progress_step_and_close():
    saved: list[list[str]] = []
    pg = Progress(lambda steps: saved.append([s.status for s in steps]))
    pg.step("conditions", "running")
    pg.step("intent", "running")  # 다음 단계를 시작하면 앞에서 진행 중이던 단계는 끝난 것
    assert [s.status for s in pg.steps[:2]] == ["done", "running"]
    pg.step("intent", "done", "테마 반도체")
    pg.close(("retrieve", "classify", "screen"), "점검하지 못해 건너뜀")
    assert [(s.key, s.status) for s in pg.steps] == [("conditions", "done"), ("intent", "done"), ("retrieve", "skipped"), ("classify", "skipped"),
                                                    ("screen", "skipped"), ("question", "waiting")]  # fmt: skip
    assert pg.steps[1].detail_ko == "테마 반도체" and pg.steps[2].detail_ko == "점검하지 못해 건너뜀" and len(saved) == 4
    pg.close(("retrieve",))  # 바뀐 것이 없으면 저장하지 않는다
    assert len(saved) == 4
    Progress().step("conditions", "running")  # 기록기 없이도 (답·말로 보태기 턴)


def test_progress_texts():
    assert themes_ko({"interpretation": {"themes": [{"id": "a", "label_ko": "반도체"}, {"id": "b", "label_ko": "메모리"}]}}) == "테마 반도체, 메모리"
    assert themes_ko({"interpretation": {"themes": []}}) == "테마 없음"
    pre = {"as_of": {"date": "2025-12-31", "n_selected": 18}, "start": {"date": "2023-01-03", "n_selected": 15}}
    assert screen_ko(pre) == "기준일 2025-12-31 18개 · 시작일 2023-01-03 15개"
    assert screen_ko({**pre, "start": None}) == "기준일 2025-12-31 18개" and screen_ko(None) is None


def _cands(n: int) -> Candidates:
    def c(t):
        g = {"sector": {"code": "45", "name": "x"}, "industry_group": {"code": "4510", "name": "x"}, "industry": {"code": "451010", "name": "x"},
             "sub_industry": {"code": "45101010", "name": "x"}}  # fmt: skip
        return {"ticker": t, "name": t, "market": "US", "gics": g, "company_summary": "s", "matched_by": ["gics"], "matched_themes": ["t"], "forced": False}

    return Candidates.model_validate({"request_id": "r", "as_of": "2025-06-25", "candidates": [c(f"T{i}") for i in range(n)], "filtered_out": [], "stats": {}, "warnings": []})


def test_classify_on_batch():
    """묶음을 받을 때마다 (끝난 수, 전체) 를 알린다. 시작할 때 (0, n). 동시에 보내도 순서대로 센다."""
    intent = {"interpretation": {"themes": [{"id": "t", "label_ko": "테마", "description_ko": "d"}]}, "screen": {"theme_filter": {"min_confidence": 0.5}}}

    def ans(messages):
        tickers = [ln.split(" | ")[0] for ln in messages[-1]["content"].splitlines() if " | " in ln]
        return {"results": [{"ticker": t, "in_theme": True, "themes": ["t"], "confidence": 0.9, "reason_ko": "", "excluded_theme": None} for t in tickers]}

    for workers in (1, 2):
        calls: list[tuple[int, int]] = []
        tag = classify(_cands(5), intent, StubLlm({"04_classify": ans}), batch_size=2, max_workers=workers, on_batch=lambda i, n: calls.append((i, n)))
        assert calls == [(0, 3), (1, 3), (2, 3), (3, 3)] and len(tag.passed_tickers) == 5
