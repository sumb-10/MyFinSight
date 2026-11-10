"""분석 진행 화면 (이슈 #14 묶음 D): 단계별 경고 전체(GET /runs/{id}/warnings)."""

from __future__ import annotations

import json
from pathlib import Path

from fastapi.testclient import TestClient

from backend.analysis.api.app import API_PREFIX as P
from backend.analysis.api.app import create_analysis_app
from backend.analysis.common.llm import StubLlm
from backend.analysis.common.store import JsonStore
from backend.analysis.common.warnings import make
from backend.analysis.executor import step_warnings
from backend.analysis.executor.queue import Queue
from backend.analysis.executor.runner import run
from backend.analysis.executor.stages import Stage
from backend.analysis.settings import AnalysisSettings
from backend.tests.analysis.test_executor import _ctx

FEW = {"n": 3, "target": 10}


def test_runner_writes_user_warnings_after_each_stage(tmp_path, seeded_repo, settings):
    ctx = _ctx(tmp_path, seeded_repo, settings)
    seen_by_s2: dict = {}

    def s1(c):
        c.warn("s1", "too_few_candidates", **FEW)
        c.warn("s1", "too_few_candidates", **FEW)  # 같은 경고 → count 2 로 묶임
        c.warn("s1", "leverage_unknown", n=2, tickers="A, B")  # info: 화면 목록에는 없음
        c.warn("s1", "must_include_not_in_universe", tickers="ZZZ")
        return "s1 끝"

    def s2(c):
        seen_by_s2.update(json.loads((c.run_dir / step_warnings.FILE).read_text(encoding="utf-8")))  # 실행 중에도 끝난 단계의 경고가 파일에 있다
        c.warn("s2", "too_few_candidates", n=1, target=5)
        return "s2 끝"

    def s3(c):
        c.warn("s3", "too_few_candidates", **FEW)
        raise ValueError("kaput")  # 실패한 단계의 경고는 목록에 없다 (요약에도 없음)

    out = run(ctx, stages=[Stage("s1", "하나", "conditions", s1), Stage("s2", "둘", "candidates", s2, deps=("s1",)),
                           Stage("s3", "셋", "backtest", s3, deps=("s2",))])  # fmt: skip
    assert out.status == "failed"
    assert list(seen_by_s2) == ["s1"]
    rows = step_warnings.api_rows(step_warnings.load(ctx.run_dir), {"s1": "하나", "s2": "둘", "s3": "셋"}, ["s1", "s2", "s3"])
    assert [(r["step"], r["count"]) for r in rows] == [("s1", 2), ("s1", 1), ("s2", 1)]
    assert rows[0]["step_label_ko"] == "하나" and rows[0]["message_ko"].startswith("테마 후보가 3개로")
    summary = {s.name: s.summary for s in out.steps}
    assert "확인 필요 2건" in summary["s1"] and "확인 필요 1건" in summary["s2"]  # 단계별 줄 수 = 요약의 N


def test_load_rebuilds_from_run_meta_for_older_runs(tmp_path):
    w = [make("s1", "too_few_candidates", **FEW), make("s1", "too_few_candidates", **FEW), make("s1", "leverage_unknown", n=1, tickers="A"),
         make("s2", "too_few_candidates", **FEW)]  # fmt: skip
    meta = {"warnings": [x.to_dict() for x in w], "steps": [{"name": "s1", "status": "PARTIAL"}, {"name": "s2", "status": "FAILED"}]}
    (tmp_path / "run_meta.json").write_text(json.dumps(meta, ensure_ascii=False), encoding="utf-8")
    by = step_warnings.load(tmp_path)
    assert list(by) == ["s1"] and [(x["code"], x["count"]) for x in by["s1"]] == [("too_few_candidates", 2)]
    assert step_warnings.load(tmp_path / "nope") == {}


def test_warnings_api(tmp_path, monkeypatch):
    monkeypatch.setenv("ANALYSIS_OUTPUT_DIR", str(tmp_path / "out"))
    store = JsonStore(tmp_path / "store")
    Queue(store).enqueue("run_w", "req_w")
    c = TestClient(create_analysis_app(lambda: None, store_dir=store.root, settings=AnalysisSettings(), llm=lambda: StubLlm()))
    assert c.get(f"{P}/runs/run_w/warnings").json() == []  # 아직 끝난 단계가 없음
    d = Path(tmp_path / "out" / "run_w")
    step_warnings.save(d, {"05_selection": [make("05_selection", "too_few_candidates", **FEW)], "03_candidates": [make("03_candidates", "must_include_not_in_universe", tickers="ZZZ")]})
    rows = c.get(f"{P}/runs/run_w/warnings").json()
    assert [r["step"] for r in rows] == ["03_candidates", "05_selection"]  # 저장 순서와 상관없이 단계 순서대로
    assert all(r["step_label_ko"] != r["step"] and r["message_ko"] and r["count"] == 1 for r in rows)  # 단계 이름은 레지스트리의 한국어
    assert c.get(f"{P}/runs/nope/warnings").status_code == 404

