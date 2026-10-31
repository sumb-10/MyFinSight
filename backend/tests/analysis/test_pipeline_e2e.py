"""B2: 합성 DB(sqlite) + stub LLM 으로 파이프라인 01~13 end-to-end. module_mockup/tests/test_pipeline.py 의 불변식 이식."""

from __future__ import annotations

import datetime as dt
import json

import numpy as np
import pytest

from backend.analysis.common.llm import StubLlm
from backend.analysis.executor.context import RunContext
from backend.analysis.executor.runner import run
from backend.analysis.executor.stages import STAGES
from backend.analysis.m2_data.market_data import MarketData
from backend.analysis.schemas import ResultsBundle
from backend.analysis.settings import AnalysisSettings, replace_settings

REQUEST = {
    "request_id": "req_20251231_120000_e2e1",
    "created_at": "2025-12-31T12:00:00+09:00",
    "profile": {"user_id": "u", "age_band": "30s", "investment_experience": "beginner", "financial_knowledge": "basic", "investable_ratio_of_assets": 0.3},
    "capital": {"initial_amount": 20_000_000, "currency": "KRW", "monthly_contribution": 500_000, "contribution_day": 25},
    "horizon": {"target_years": 5, "purpose": "wealth_growth", "backtest_years": 2},
    "risk": {"risk_tolerance": "moderate", "max_drawdown_tolerance": 0.35, "loss_reaction": "hold", "target_annual_return": 0.08, "benchmark": "SPY"},
    "constraints": {"universe": ["SP500", "NASDAQ100", "KOSPI200"], "asset_types": ["stock"], "num_holdings": {"target": 6, "min": 4, "max": 8},
                    "max_weight_per_stock": 0.3, "max_weight_per_sector": 0.8, "min_cash_ratio": 0.0, "exclude_tickers": [], "exclude_sectors": [],
                    "exclude_themes": [], "must_include_tickers": [], "rebalance": {"count": 1, "unit": "1q"}, "allow_leverage": False, "allow_short": False,
                    "min_market_cap_usd": 0, "min_avg_daily_volume_usd": 0},
    "strategy_preference": {"template": "momentum", "baseline_weighting": "equal_weight", "use_news_tilt": True},
    "natural_language": {"idea": "미국과 한국의 반도체·메모리 기업에 분산 투자하고 싶다", "language": "ko"},
}  # fmt: skip

INTENT_STUB = {
    "request_id": REQUEST["request_id"], "spec_version": "2.0",
    "interpretation": {"summary_ko": "미국·한국 반도체 기업 분산 투자", "themes": [
        {"id": "semiconductor", "label_ko": "반도체", "description_ko": "반도체 설계·제조·장비·메모리 기업", "gics_codes": ["453010"],
         "keywords": ["semiconductor", "memory", "dram", "gpu", "반도체"], "example_tickers": ["NVDA", "005930.KS"]}],
        "style_hints": ["diversified"], "conflicts": []},
    "exclude_theme_rules": [],
    "screen": {"template": "momentum", "metric": "return_12m_1m", "direction": "desc", "as_of": "2025-12-31", "theme_filter": {"min_confidence": 0.5}, "select_top_n": 6},
    "risk_params": {"risk_tolerance": "moderate", "effective_max_drawdown": 0.35, "volatility_preference": "medium", "notes_ko": ""},
    "news_tilt": {"enabled": True, "max_view_confidence": 0.5, "max_tilt_per_stock": 0.1},
    "validation_criteria": {"benchmark": "SPY", "max_drawdown": 0.35, "target_annual_return": 0.08, "horizon_years": 5},
    "report_settings": {"language": "ko", "explanation_level": "beginner"},
    "questions": [{"field": "strategy_preference.use_news_tilt", "kind": "preference", "question_ko": "뉴스를 비중에 반영할까요?",
                   "options": [{"value": True, "label_ko": "예"}, {"value": False, "label_ko": "아니오"}], "priority": 3}],
}  # fmt: skip


@pytest.fixture(scope="module")
def e2e(seeded_repo, descriptor_dir, tmp_path_factory):
    s = AnalysisSettings()
    s = replace_settings(s, portfolio=replace_settings(s.portfolio, lookback_days=252, min_history_days_for_model=120),
                         market=replace_settings(s.market, valuation_max_staleness_days=10, descriptor_dir=str(descriptor_dir)))  # fmt: skip
    md = MarketData(seeded_repo, s)
    run_dir = tmp_path_factory.mktemp("run")
    llm = StubLlm({"02_intent": INTENT_STUB}, run_dir=run_dir)
    ctx = RunContext(run_id="run_e2e_test", request=dict(REQUEST), repo=seeded_repo, md=md, llm=llm, settings=s, run_dir=run_dir)
    outcome = run(ctx)
    return ctx, outcome


def test_run_completes(e2e):
    ctx, outcome = e2e
    assert outcome.status in ("success", "partial"), outcome.to_dict()
    names = [s.name for s in outcome.steps]
    assert names[:3] == ["01_request", "02_intent", "03_candidates"] and names[-1] == "14_report"
    assert all(s.status in ("SUCCESS", "PARTIAL") for s in outcome.steps)
    assert (ctx.run_dir / "13_results.json").exists() and (ctx.run_dir / "14_report.json").exists() and (ctx.run_dir / "run_meta.json").exists()


def test_report_seven_sections_and_citations(e2e):
    from backend.analysis.m5_backtest_report.report_check import CITE_RE, check
    from backend.analysis.schemas import ReportDoc

    ctx, _ = e2e
    doc = ReportDoc.model_validate(ctx.outputs["14_report"])
    assert [s.id for s in doc.sections] == ["verdict", "market", "companies", "construction", "performance", "assumptions", "references"]
    types = {b["type"] for s in doc.sections for b in s.blocks}
    assert {"paragraphs", "kpis", "table", "line", "area", "bar", "funnel", "callout", "cards", "glossary", "evidence_ref", "companies", "timeline", "weights_compare"} <= types
    ev_ids = {e.id for e in doc.evidence}
    cited = {c for s in doc.sections for b in s.blocks if b["type"] in ("paragraphs", "cards") for item in b.get("items", [])
             for c in CITE_RE.findall(item if isinstance(item, str) else item.get("text_ko", ""))}
    assert cited and cited <= ev_ids  # 인용된 모든 ID 가 근거 색인에 있다
    assert any(c.startswith("ev") for c in cited) and any(c.startswith("fin:") for c in cited)
    assert doc.header["chosen_portfolio_id"] == ctx.outputs["12_validation"]["chosen_id"]
    assert doc.kpis[0]["id"] == "final_value" and doc.execution and doc.tracking["eligible"]
    # 검증 게이트: 없는 인용 ID 를 넣으면 오류
    R = ctx.outputs["13_results"]
    bad = json.loads(json.dumps(ctx.outputs["14_report"]))
    bad["sections"][1]["blocks"][0]["items"].append("근거 없는 주장입니다 [ev999999].")
    res = check(bad, R, ctx.settings)
    assert any("unknown citation" in e for e in res.errors)
    bad2 = json.loads(json.dumps(ctx.outputs["14_report"]))
    bad2["sections"].pop()
    assert any("sections must be" in e for e in check(bad2, R, ctx.settings).errors)
    bad3 = json.loads(json.dumps(ctx.outputs["14_report"]))
    bad3["sections"][0]["blocks"][0]["items"].append("이 전략은 수익을 보장합니다.")
    assert any("banned" in e for e in check(bad3, R, ctx.settings).errors)


def test_request_derived_and_lookahead(e2e):
    ctx, _ = e2e
    d = ctx.outputs["01_request"]["derived"]
    assert d["as_of"] == "2025-12-31" and d["markets"] == ["KR", "US"] and d["fx_rate"] > 1000
    assert d["backtest_start"] < d["backtest_end"] == "2025-12-31"
    assert ctx.outputs["02_intent"]["questions"] == []  # 실행 단계에서는 질문 없음
    # 모든 가격 자료 날짜 ≤ 기준일
    assert max(ctx.outputs["11_backtest_results"]["series_dates"]) <= "2025-12-31"


def test_selection_mixed_market_and_facts(e2e):
    ctx, _ = e2e
    sel = ctx.outputs["05_selection"]
    tickers = [s["ticker"] for s in sel["selected"]]
    assert 4 <= len(tickers) <= 8 and any(t.endswith(".KS") for t in tickers) and any(not t.endswith(".KS") for t in tickers)
    assert all(s["metric_fact_id"] and s["metric_fact_id"].startswith("fin:") for s in sel["selected"])
    cand = ctx.outputs["03_candidates"]
    assert "GOOG" not in {c["ticker"] for c in cand["candidates"]} or "GOOGL" not in {c["ticker"] for c in cand["candidates"]}
    expl = ctx.outputs["06_selection_explained"]
    assert {r["ticker"] for r in expl["per_ticker"]} == set(tickers)


def test_targets_constraints(e2e):
    ctx, _ = e2e
    T = ctx.outputs["10_target_portfolios"]
    cons = ctx.request["constraints"]
    for p in T["portfolios"] + T["templates"]:
        w = p["weights"]
        assert abs(sum(w.values()) + p["cash_weight"] - 1) < 1e-4
        assert max(w.values()) <= cons["max_weight_per_stock"] + 1e-6 and min(w.values()) >= 0.01 - 1e-9
    base = T["baseline"]["weights"]
    for p in T["portfolios"]:
        assert max(abs(p["weights"][t] - base[t]) for t in base) <= T["parameters"]["max_tilt_per_stock"] + 1e-6
        assert all(v["evidence_ids"] for v in p["views_applied"])
    # 섹터 상한(0.8)에 후보가 모두 반도체 섹터 -> 20% 는 현금으로 남고 사유가 기록된다
    assert abs(sum(base.values()) - 0.8) < 1e-3 and any("caps allow" in w for w in T["warnings"])
    views = ctx.outputs["09_views"]
    # 합성 뉴스는 2025-12 에만 있어 백테스트 시작일(2024년) 에는 뷰가 없고 기준 비중 fallback 이 정상 (K6)
    assert views["fallback"] and "뉴스" in views["fallback_reason_ko"] and views["sets"] == []
    fwd = ctx.outputs["10f_forward_portfolios"]
    assert not fwd["fallback"] and fwd["portfolios"] and all(v["evidence_ids"] for v in fwd["portfolios"][0]["views_applied"])
    tilt = fwd["parameters"]["max_tilt_per_stock"]
    assert max(abs(fwd["portfolios"][0]["weights"][t] - fwd["baseline"]["weights"][t]) for t in fwd["baseline"]["weights"]) <= tilt + 1e-6


def test_backtest_invariants(e2e):
    ctx, _ = e2e
    bt = ctx.outputs["11_backtest_results"]
    n = len(bt["series_dates"])
    assert n > 200 and bt["period"]["annualized_reliable"]
    for p in [bt["benchmark"], *bt["benchmarks"], *bt["portfolios"]]:
        assert all(len(v) == n for v in p["series"].values())
        assert min(p["series"]["drawdown"]) <= 0
        cps = p["checkpoints"]
        assert sum(1 for c in cps if c["kind"] == "closing") == 1
        last = cps[-1]["to_date"]
        assert abs(last["total_return"] - p["metrics"]["return"]["total_return"]) < 1e-6
        if p["kind"] != "benchmark":
            for c in cps:
                if c["kind"] == "rebalance" and c["weights"]["target"]:
                    diff = max(abs(c["weights"]["after"][t] - c["weights"]["target"][t]) for t in c["weights"]["target"])
                    assert diff < 0.02, (p["id"], c["date"], diff)
    ids = {p["id"] for p in bt["portfolios"]}
    assert {"wf_bl_news", "wf_equal_weight", "equal_weight", "market_cap", "inverse_volatility", "min_variance"} <= ids
    assert any(p["mode"] == "walkforward" for p in bt["portfolios"])
    assert {b["id"] for b in bt["benchmarks"]} >= {"benchmark_SPY", "benchmark_069500.KS"}  # 한국 종목 포함 → 한국 지수 자동 추가


def test_validation_and_bundle(e2e):
    ctx, _ = e2e
    val, bt = ctx.outputs["12_validation"], ctx.outputs["11_backtest_results"]
    assert {r["id"] for r in val["results"]} == {p["id"] for p in bt["portfolios"]}
    assert val["chosen_id"] in {p["id"] for p in bt["portfolios"]} and val["alternatives"] == [] and val["recommended"]["id"] == val["chosen_id"]
    for a in [p for p in bt["portfolios"] if p["kind"] == "matched"]:  # 낙폭 맞춤안이 있으면 기준·비율·이름이 맞는다 (라운드 5)
        base = next(p for p in bt["portfolios"] if p["id"] == a["base_id"])
        base_total = sum(base["target_weights"].values())
        assert a["id"] == f"dd_match_{a['base_id']}" and 0 < a["cash_ratio"] < 1 and abs(sum(a["target_weights"].values()) - (1 - a["cash_ratio"]) * base_total) < 1e-3
        assert abs(a["cash_ratio_total"] - (1 - sum(a["target_weights"].values()))) < 1e-6 and a["name_ko"].startswith("낙폭 맞춤안 (주식 ")
        assert abs(a["headline"]["max_drawdown"]) <= a["match_target"] + 0.005
    for p in bt["portfolios"]:
        assert (p["headline"].get("view_hit_ratio_next_rb") is None) == (p["kind"] != "black_litterman") or p["kind"] == "black_litterman"
    bundle = ResultsBundle.model_validate(ctx.outputs["13_results"])
    assert bundle.run_id == "run_e2e_test"
    ev = bundle.evidence_index
    assert any(k.startswith("ev") for k in ev) and any(k.startswith("fin:") for k in ev) and any(k.startswith("calc:") for k in ev)
    assert bundle.data_quality and bundle.sources[0]["name"].startswith("팀 데이터베이스")
    json.dumps(ctx.outputs["13_results"])  # 직렬화 가능
    fwd = ctx.outputs["10f_forward_portfolios"]
    assert fwd["as_of"] == "2025-12-31" and 0.79 < sum(fwd["chosen_weights"].values()) <= 1.0001  # 상한 용량만큼만 투자 (나머지 현금)
    assert all(x["krw"] > 0 for x in fwd["templates"][0]["allocation"])
    wf = ctx.outputs["10w_target_paths"]
    assert len(wf["dates"]) >= 4 and set(wf["portfolios"][-1]["weights_by_date"]) == set(wf["dates"])
    meta = json.loads((ctx.run_dir / "run_meta.json").read_text(encoding="utf-8"))
    assert meta["status"] in ("success", "partial") and meta["llm_usage"]["calls"] >= 3
    assert np.isfinite(bt["portfolios"][0]["headline"]["cagr"])


# ───────────────────────── 공시 근거 (라운드 4) ─────────────────────────
def test_disclosures_flow_into_results_and_report(e2e):
    from backend.analysis.m5_backtest_report.report import facts_for_market
    from backend.analysis.m5_backtest_report.report_check import check
    from backend.analysis.schemas import ReportDoc

    ctx, _ = e2e
    R = ctx.outputs["13_results"]
    ev = R["evidence_index"]
    dcs = {k: v for k, v in ev.items() if k.startswith("dc")}
    assert dcs and all(v["kind"] == "disclosure" and v["event_label_ko"] and v["available_on"] <= "2025-12-31" for v in dcs.values())
    assert any(v["event_type"] == "earnings" for v in dcs.values()) and not any(v["event_type"] in ("major_holder", "derivative_offering") for v in dcs.values())
    assert any(s["id"] == "src_disclosures" for s in R["sources"]) and R["parameters"]["disclosures"]["window_days"] == ctx.settings.disclosures.window_days
    # 10w: 리밸런싱일 근거 요약에 공시 수가 들어가고, 최근 날짜에는 공시가 잡힌다
    wf = ctx.outputs["10w_target_paths"]
    ns = wf["news_summary"]
    assert all("n_disclosures" in v for v in ns.values()) and any(v["n_disclosures"] > 0 for v in ns.values())  # 2023-12 공시가 첫 리밸런싱 창에 잡힌다
    assert wf["parameters"]["disclosure_window_days"] == ctx.settings.disclosures.window_days
    # 리포트: 근거 색인에 공시 레코드, 14c 사실에 공시 목록·90일 사건 요약
    doc = ReportDoc.model_validate(ctx.outputs["14_report"])
    dc_docs = [e for e in doc.evidence if e.kind == "disclosure"]
    assert dc_docs and all(e.event_label_ko and e.available_on for e in dc_docs)
    facts = facts_for_market(R)
    assert facts["disclosures"] and facts["event_summary_90d"] and "[dc45]" in facts["citation_rule"]
    assert all(set(d) >= {"id", "ticker", "available_on", "event", "form"} for d in facts["disclosures"])
    # 검증: 기준일 이후에 이용 가능해진 공시를 인용하면 오류, 기준일 이전이면 통과
    dc_id = next(iter(dcs))
    ok = json.loads(json.dumps(ctx.outputs["14_report"]))
    ok["sections"][1]["blocks"][0]["items"].append(f"해당 기간에 실적 발표 공시가 있었습니다 [{dc_id}].")
    assert not [e for e in check(ok, R, ctx.settings).errors if dc_id in e]
    R2 = json.loads(json.dumps(R))
    R2["evidence_index"][dc_id]["available_on"] = "2026-01-05"
    errs = check(ok, R2, ctx.settings).errors
    assert any(dc_id in e and "after as_of" in e for e in errs)
    # 보유하지 않은 종목의 공시 인용은 오류
    R3 = json.loads(json.dumps(R))
    R3["evidence_index"][dc_id]["tickers"] = ["ZZZZ"]
    assert any(dc_id in e and "not held" in e for e in check(ok, R3, ctx.settings).errors)


def test_stub_views_parse_disclosure_lines():
    """스마트 stub 은 공시 줄(5번째 칸 ticker)만 있어도 뷰를 만든다 — 2009~2016 처럼 뉴스가 없는 구간의 시험용."""
    from backend.analysis.common.stub_answers import stub_views

    user = (
        "## 종목 (ticker | name | ...)\n\n```\nNVDA | NVIDIA | IT | 소개 | 0.1 | 0.3 | 0.5 | 0.5 | 0.08\nAMD | AMD | IT | 소개 | 0.1 | 0.3 | 0.5 | 0.5 | 0.08\nMU | Micron | IT | 소개 | 0.1 | 0.3 | 0.5 | 0.5 | 0.08\n```\n\n"
        "## 공시 사건 — 기준일 이전 45일 (id | ...)\n\n```\ndc7 | 2025-12-11 | SEC_EDGAR(en) | 8-K 2.02,9.01 | NVDA | 실적 발표 | 8-K\ndc9 | 2025-12-04 | DART(ko) | 주요사항보고서 | AMD | 자사주 매입 결정 | 주요사항보고서(자기주식취득결정)\n```\n\n"
        "## 뉴스 근거 — 기준일 이전 14일 헤드라인 (id | ...)\n\n```\n(없음)\n```\n"
    )
    out = stub_views([{"role": "system", "content": ""}, {"role": "user", "content": user}])
    views = out["sets"][0]["views"]
    assert views[0]["type"] == "absolute" and views[0]["long"] == ["NVDA"] and views[0]["evidence_ids"] == ["dc7"]
    assert views[1]["type"] == "relative" and views[1]["long"] == ["AMD"] and views[1]["short"] == ["MU"] and views[1]["evidence_ids"] == ["dc9"]


def test_sequential_run_gives_identical_results(e2e, seeded_repo, descriptor_dir, tmp_path):
    """결정론: 병렬(기본)과 순차(ANALYSIS_PARALLEL=0 과 같은 설정)의 13_results 가 같다 (생성 시각·LLM 사용량 제외)."""
    from backend.analysis.settings import ExecutorSettings

    ctx, _ = e2e
    s = replace_settings(ctx.settings, executor=ExecutorSettings(max_parallel_stages=1, walkforward_workers=1, classify_workers=1, parallel_report_calls=False))
    md = MarketData(seeded_repo, s)
    run_dir = tmp_path / "seq"
    llm = StubLlm({"02_intent": INTENT_STUB}, run_dir=run_dir)
    ctx2 = RunContext(run_id="run_e2e_test", request=dict(REQUEST), repo=seeded_repo, md=md, llm=llm, settings=s, run_dir=run_dir)
    out2 = run(ctx2)
    assert out2.status in ("success", "partial")

    def strip(R):
        R = json.loads(json.dumps(R))
        for k in ("generated_at", "llm_usage"):
            R.pop(k, None)
        R["parameters"].pop("executor", None)
        return R

    a, b = strip(ctx.outputs["13_results"]), strip(ctx2.outputs["13_results"])
    assert list(a["evidence_index"]) == list(b["evidence_index"])  # 근거 색인 순서까지 같다
    assert [w["stage"] + ":" + w["code"] for w in a["warnings"]] == [w["stage"] + ":" + w["code"] for w in b["warnings"]]
    assert a == b
    # 실행 기록(단계 요약)은 완료 순서가 아니라 단계 순서
    steps = [e["step"] for e in ctx.outputs["14_report"]["execution"]]
    assert steps == [st.name for st in STAGES if st.name in steps]
    # 10w 진행 표시가 러너 훅으로 나갔는지 (progress) — 리밸런싱 수만큼 completed 콜백
    assert ctx.settings.executor.max_parallel_stages > 1


def test_compute_to_date_matches_compute_all(e2e):
    """체크포인트 요약(compute_to_date)은 전체 지표(compute_all)와 같은 값이어야 한다 (라운드 4 S8)."""
    from backend.analysis.m5_backtest_report import backtest_metrics as M
    from backend.analysis.m5_backtest_report.backtest import flat_to_date, run_raw, slice_raw, xirr

    ctx, _ = e2e
    bt_ctx = ctx.out("_bt_ctx")
    bt = ctx.outputs["11_backtest_results"]
    p = bt["portfolios"][0]
    raw = run_raw(bt_ctx, p["id"], p["target_weights"])
    bench_raw = run_raw(bt_ctx, "bench", {bt_ctx["bench"]: 1.0})
    base_raw = run_raw(bt_ctx, "base", next(x for x in bt["portfolios"] if x["id"] == bt_ctx["baseline_id"])["target_weights"])
    s = ctx.settings.backtest
    cons = bt_ctx["cons"]
    for frac in (0.3, 0.6, 1.0):
        d = raw["index"].index[int((len(raw["index"]) - 1) * frac)]
        full = M.compute_all(slice_raw(raw, d), bench_raw["index"][:d], bt_ctx["panel"][:d], p["target_weights"], bt_ctx["sectors"], bt_ctx["rb"], bt_ctx["rf"],
                             bt_ctx["target_return"], cons["max_weight_per_stock"], cons["max_weight_per_sector"], xirr, s, baseline_idx=base_raw["index"][:d])  # fmt: skip
        want = flat_to_date(full, raw["index"].index.get_loc(d), s.trading_days)
        got = M.compute_to_date(raw["index"][:d], raw["values"][:d], raw["flows"][:d], bench_raw["index"][:d], bt_ctx["rf"], xirr, s, baseline_idx=base_raw["index"][:d])
        got["reliable"] = raw["index"].index.get_loc(d) >= s.trading_days
        assert got == want, (d, {k: (got[k], want[k]) for k in want if got[k] != want[k]})
    # walk-forward 뷰 진단은 날짜별 (as_of 필드) 이고, 체크포인트 뷰 진단은 기본 꺼짐
    wf = next((x for x in bt["portfolios"] if x["id"] == "wf_bl_news"), None)
    if wf and wf["view_diagnostics"]:
        assert all("as_of" in v for v in wf["view_diagnostics"])
    assert all(cp["view_diagnostics_to_date"] == [] for x in bt["portfolios"] for cp in x["checkpoints"])
