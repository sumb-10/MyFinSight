"""라운드 4: 리포트 문서 v2 — 요약 대시보드, 접이식 묶음, 근거 참조, 인용된 근거만 evidence, 타임라인·기업·비중 표, 시계열 표본, 옛 문서 정규화."""

from __future__ import annotations

import json

from backend.analysis.common.citations import CITE_RE
from backend.analysis.m5_backtest_report import report_blocks as B
from backend.analysis.m5_backtest_report.report import cited_ids, present_doc
from backend.analysis.m5_backtest_report.report_check import check
from backend.analysis.schemas import ReportDoc
from backend.tests.analysis.test_pipeline_e2e import e2e  # noqa: F401 — 모듈 범위 픽스처 재사용


def test_doc_v2_structure(e2e):
    ctx, _ = e2e
    raw = ctx.outputs["14_report"]
    doc = ReportDoc.model_validate(raw)
    R = ctx.outputs["13_results"]
    assert doc.doc_version == 2 and doc.summary and doc.evidence_summary["total"] == len(R["evidence_index"])
    types = {b["type"] for s in doc.sections for b in s.blocks}
    assert {"evidence_ref", "weights_compare", "timeline", "companies"} <= types and "evidence" not in types and "checkpoints" not in types
    # 근거는 인용된 것만, 참조 ID 는 모두 포함
    ev_ids = {e.id for e in doc.evidence}
    used = set(cited_ids(raw["sections"], R["evidence_index"]))
    assert ev_ids == used and doc.evidence_summary["cited"] == len(ev_ids) and len(ev_ids) < len(R["evidence_index"])
    cited_text = {c for s in doc.sections for b in s.blocks if b["type"] in ("paragraphs", "cards") for it in b.get("items", [])
                  for c in CITE_RE.findall(it if isinstance(it, str) else it.get("text_ko", ""))}
    assert cited_text <= ev_ids
    # 요약 대시보드
    sm = doc.summary
    assert sm["verdict"]["status"] in ("recommended", "recommended_warn", "insufficient") and sm["verdict"]["headline_ko"]
    assert sm["validation"]["r1"] and {"mdd", "tolerance", "benchmark_mdd"} <= set(sm["validation"]["r1"]) and "news_effect" in sm
    assert sm["validation"] == {**sm["validation"], "n_pass": R["validation"]["summary"]["n_pass"], "n_fail": R["validation"]["summary"]["n_fail"]}
    assert {k["id"] for k in sm["kpis"]} <= {"final_value", "cagr", "excess", "mdd", "sharpe", "view_hit"} and all("benchmark_value" in k for k in sm["kpis"])
    assert sm["allocation"]["items"] and abs(sum(i["weight"] for i in sm["allocation"]["items"]) + sm["allocation"]["cash_weight"] - 1) < 1e-6
    assert sm["mini_series"]["ids"][0] == doc.header["chosen_portfolio_id"] and sm["next_actions_ko"]
    # 제목은 짧게, 상세 제목 따로; 개발 문구는 header.mode 가 아니라 backtest_mode
    assert "전략" in doc.header["title_ko"] and R["selection"]["metric"] not in doc.header["title_ko"] and doc.header["title_detail_ko"] and "mode" not in doc.header
    # 묶음: 참고자료의 출처·계산 조건·실행 기록은 한 묶음, '계산 조건' 표 제목 유지 (CalculationPanel 의존)
    refs = next(s for s in doc.sections if s.id == "references")
    grouped = [b for b in refs.blocks if b.get("group_ko") == "자료 출처·계산 조건·실행 기록"]
    assert len(grouped) == 3 and any(b.get("title_ko") == "계산 조건" for b in grouped)
    assert any(b.get("group_open") for s in doc.sections for b in s.blocks)
    # 타임라인 = 체크포인트 수, 기업 = 선정 표 행 수, 비중 표 열 = 규칙 4 + BL
    chosen = doc.header["chosen_portfolio_id"]
    tl = next(b for s in doc.sections for b in s.blocks if b["type"] == "timeline")
    assert len(tl["items"]) == len(B.find(R, chosen)["checkpoints"]) and tl["portfolio_id"] == chosen
    if tl["walkforward"]:
        assert all(it["news"] is not None for it in tl["items"] if it["kind"] == "rebalance")
    comp = next(b for s in doc.sections for b in s.blocks if b["type"] == "companies")
    assert len(comp["items"]) == len(R["selection"]["table"]) and all(it["rationale_ko"] for it in comp["items"] if it["in_selection_now"])
    assert comp["metric_ko"] == "모멘텀" and all(isinstance(it["evidence_ids"], list) for it in comp["items"])
    wc = next(b for s in doc.sections for b in s.blocks if b["type"] == "weights_compare")
    assert len(wc["columns"]) == len(R["portfolio"]["baselines"]["portfolios"]) + len(R["portfolio"]["targets"]["portfolios"]) and wc["rows"]
    for r in wc["rows"]:
        assert set(r["weights"]) == {c["id"] for c in wc["columns"]}
    # 검증 게이트 통과, 기업 근거 문단도 검사 대상
    res = check(raw, R, ctx.settings)
    assert not res.errors
    bad = json.loads(json.dumps(raw))
    bad_comp = next(b for s in bad["sections"] for b in s["blocks"] if b["type"] == "companies")
    bad_comp["items"][0]["rationale_ko"].append("이 종목은 수익을 보장합니다 [ev999999].")
    errs = check(bad, R, ctx.settings).errors
    assert any("banned" in e for e in errs) and any("unknown citation" in e for e in errs)
    bad2 = json.loads(json.dumps(raw))
    ref = next(b for s in bad2["sections"] for b in s["blocks"] if b["type"] == "evidence_ref" and b.get("ids"))
    ref["ids"].append("dc424242")
    assert any("evidence_ref" in e for e in check(bad2, R, ctx.settings).errors)
    # 문단 블록에는 출처 태그
    assert all(b.get("src") in ("14a", "14b", "14c") for s in doc.sections for b in s.blocks if b["type"] == "paragraphs")


def test_sample_series_pins_endpoints_and_drawdown():
    n = 1500
    dates = [f"d{i:04d}" for i in range(n)]
    idx = [100 + (i if i < 900 else 900 - (i - 900) * 2) for i in range(n)]  # 900 에 고점, 끝에 저점
    peak = [max(idx[: i + 1]) for i in range(n)]
    dd = [v / p_ - 1 for v, p_ in zip(idx, peak, strict=True)]
    series = {"a": {"label_ko": "a", "index": idx, "drawdown": dd, "value_usd": idx}, "b": {"label_ko": "b", "index": idx[::-1]}}
    d2, s2, meta = B.sample_series(dates, series, max_points=600, pin_id="a")
    assert meta["method"] == "stride" and meta["full_points"] == n and len(d2) == meta["points"] <= 600 + 4
    assert d2[0] == dates[0] and d2[-1] == dates[-1] and set(meta["pinned"]) <= set(d2) and "d0900" in meta["pinned"]
    assert all(len(v) == len(d2) for ser in s2.values() for v in ser.values() if isinstance(v, list))
    assert s2["b"]["label_ko"] == "b"
    d3, s3, meta3 = B.sample_series(dates[:500], {"a": {"index": idx[:500]}}, max_points=600)
    assert meta3 is None and d3 == dates[:500] and s3["a"]["index"] == idx[:500]


def test_present_doc_normalizes_v1(e2e):
    """옛 문서(v1: 근거 색인 전체를 evidence 블록·doc.evidence 에 복사)를 읽을 때 근거 참조 + 인용된 근거만 + summary 보강."""
    ctx, _ = e2e
    R = ctx.outputs["13_results"]
    v2 = ctx.outputs["14_report"]
    idx = R["evidence_index"]
    # v1 흉내: 전체 색인을 evidence 로, 참조 블록을 evidence 블록으로
    v1 = json.loads(json.dumps(v2))
    v1.pop("doc_version"); v1.pop("summary"); v1.pop("evidence_summary")
    v1["evidence"] = [{"id": k, "kind": v["kind"], "title": v.get("title", ""), "source": v.get("source", ""), "tickers": v.get("tickers", []), "published_at": v.get("published_at")} for k, v in idx.items()]
    for sec in v1["sections"]:
        sec["blocks"] = [({"type": "evidence", "title_ko": b["title_ko"], "items": [{"id": i, "kind": idx[i]["kind"], "title": idx[i].get("title", "")} for i in (b["ids"] if b["ids"] is not None else list(idx))]}
                          if b["type"] == "evidence_ref" else b) for b in sec["blocks"]]
    out = present_doc(v1, R)
    assert out.get("presented_from_version") == 1 and "evidence" not in {b["type"] for s in out["sections"] for b in s["blocks"]}
    refs = [b for s in out["sections"] for b in s["blocks"] if b["type"] == "evidence_ref"]
    assert refs and any(b["ids"] is None and b["count"] == len(idx) for b in refs)
    assert len(out["evidence"]) < len(idx) and out["evidence_summary"]["total"] == len(idx) and out["summary"] and out["summary"]["verdict"]["label_ko"]
    assert present_doc(v2) is v2  # v2 는 그대로
    assert v1["evidence"] and len(v1["evidence"]) == len(idx)  # 원본은 바뀌지 않음
