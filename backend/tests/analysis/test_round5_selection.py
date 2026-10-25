"""라운드 5 선정: 넓은 테마에서 후보 상한을 자를 때 선정 지표 순으로 (거래대금 순이면 지표가 아무것도 거르지 못한다)."""

from __future__ import annotations

import json

from backend.analysis.m3_selection.retrieve import retrieve
from backend.tests.analysis.test_pipeline_e2e import REQUEST, e2e  # noqa: F401


def _broad_intent(intent):
    it = json.loads(json.dumps(intent))
    it["interpretation"]["themes"] = [{"id": "all", "label_ko": "전체", "description_ko": "", "gics_codes": ["10", "15", "20", "25", "30", "35", "40", "45", "50", "55", "60"],
                                       "keywords": [], "example_tickers": []}]  # fmt: skip
    return it


def test_broad_theme_cap_uses_selection_metric(e2e):
    ctx, _ = e2e
    view = ctx.md.view(ctx.out("_bt_ctx")["end"].date())
    cons = json.loads(json.dumps(REQUEST["constraints"]))
    it = _broad_intent(ctx.outputs["02_intent"])
    full = retrieve(view, ctx.desc, it, cons, request_id="t", max_candidates=None)
    assert len(full.candidates) > 5
    capped = retrieve(view, ctx.desc, it, cons, request_id="t", max_candidates=5, broad_min_sectors=6)
    assert len(capped.candidates) == 5 and capped.stats["by_filter"].get("candidate_cap_metric", 0) == len(full.candidates) - 5
    assert any("by selection metric" in w for w in capped.warnings)
    # 지표(모멘텀, desc) 순: 남은 후보의 지표 최소값 ≥ 잘린 후보의 지표 최대값
    from backend.analysis.m2_data import metrics as M

    vals, _ = M.METRICS[it["screen"]["metric"]](view, [c.ticker for c in full.candidates])
    kept = [float(vals[c.ticker]) for c in capped.candidates if c.ticker in vals.index]
    dropped = [float(vals[f.ticker]) for f in capped.filtered_out if f.reason == "candidate_cap_metric" and f.ticker in vals.index]
    assert kept and dropped and min(kept) >= max(dropped) - 1e-12
    # 좁은 테마(섹터 1개)는 예전처럼 거래대금 순
    narrow = retrieve(view, ctx.desc, ctx.outputs["02_intent"], cons, request_id="t", max_candidates=3)
    assert narrow.stats["by_filter"].get("candidate_cap", 0) >= 1 and not narrow.stats["by_filter"].get("candidate_cap_metric")
