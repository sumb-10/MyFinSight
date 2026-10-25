"""채점 도구 (2026-10-26): 실행 결과에서 자동 지표를 뽑아 채점 기록의 뼈대를 만든다.

  python -m backend.analysis.eval.grade --from docs/mvp/grading/2026-10-26            # run_scenarios 결과 JSON(run_id·scenario_file)을 읽어 전부
  python -m backend.analysis.eval.grade --run run_x --scenario backend/test_scenarios/scenario_000.json --out <dir>
  python -m backend.analysis.eval.grade --compare run_a run_b                          # 결정론(요구 14): 종목·비중·지표 일치율

읽는 것: output/<run_id>/{01_request,02_intent,03_candidates,05_selection,07_backtest_spec,10_target_portfolios,10w_target_paths,
11_backtest_results,12_validation,13_results,14_report,run_meta}.json, data/analysis_store/requests/<request_id>.json, 시나리오 파일.
자동 지표만 계산한다. 문장 품질·해석 적합성 같은 사람 판독 칸은 비워 둔다 (채점자가 채운다).
"""

from __future__ import annotations

import argparse
import datetime as dt
import json
import math
from pathlib import Path
from typing import Any

import numpy as np

ROOT = Path(__file__).resolve().parents[3]
OUT = ROOT / "output"
STORE = ROOT / "data" / "analysis_store"

# 개념설계보고서 요구 7 "리포트 12항목" ↔ 문서 v2 블록 대응 (제목 또는 타입으로 찾는다)
REPORT_ITEMS_12: list[tuple[str, str, Any]] = [
    ("요약", "summary 대시보드(판단·KPI) 또는 종합 판단 문단", lambda doc: bool(doc.get("summary")) or _has(doc, "verdict", "paragraphs")),
    ("투자조건", "요청 내용·지켜야 하는 조건 표", lambda doc: _has(doc, "market", "table", "요청 내용") and _has(doc, "market", "table", "지켜야 하는 조건")),
    ("구성", "비중 규칙별 구성·배분 금액", lambda doc: _has(doc, "construction", "weights_compare") and _has(doc, "construction", "table", "배분 금액")),
    ("전략 규칙", "선정 지표 안내·비중 규칙·리밸런싱(백테스트 가정)", lambda doc: _has(doc, "companies", "callout", "선정 지표") and _has(doc, "performance", "callout", "백테스트 가정")),
    ("구성 근거", "기업별 근거 문단(companies) + 뉴스 뷰 카드", lambda doc: _has(doc, "companies", "companies")),
    ("기업·시장 정보", "산업과 시장 분석 문단 + 섹터 노출", lambda doc: _has(doc, "market", "paragraphs") and _has(doc, "market", "bar")),
    ("성과", "누적 수익률·평가금액 차트, 비교표, 연도·월별", lambda doc: _has(doc, "performance", "line") and _has(doc, "performance", "table", "포트폴리오 비교")),
    ("위험", "낙폭 차트, 최대낙폭 KPI, 검증 규칙 표", lambda doc: _has(doc, "performance", "area") and _has(doc, "performance", "table", "검증 규칙")),
    ("해석", "성과 해석·검증 해석 문단(14a)", lambda doc: any(b.get("src") == "14a" for s in doc["sections"] for b in s["blocks"])),
    ("계산 조건", "계산 조건 표", lambda doc: _has(doc, "references", "table", "계산 조건")),
    ("한계", "확인한 한계 카드 + 전제·재검토 문단", lambda doc: _has(doc, "assumptions", "cards", "확인한 한계") and _has(doc, "assumptions", "paragraphs")),
    ("분석 과정", "선정 과정 깔때기 + 실행 기록 표", lambda doc: _has(doc, "companies", "funnel") and _has(doc, "references", "table", "실행 기록")),
]
SEVEN = ["verdict", "market", "companies", "construction", "performance", "assumptions", "references"]


def _has(doc: dict[str, Any], sid: str, btype: str, title_prefix: str | None = None) -> bool:
    for s in doc.get("sections", []):
        if s["id"] != sid:
            continue
        for b in s["blocks"]:
            if b["type"] == btype and (title_prefix is None or str(b.get("title_ko") or "").startswith(title_prefix)):
                return True
    return False


def _load(p: Path) -> Any:
    return json.loads(p.read_text(encoding="utf-8")) if p.exists() else None


def load_run(run_id: str) -> dict[str, Any]:
    d = OUT / run_id
    if not d.exists():
        raise SystemExit(f"실행 폴더가 없습니다: {d}")
    names = ["01_request", "02_intent", "03_candidates", "04_tagging", "05_selection", "07_backtest_spec", "10_target_portfolios", "10w_target_paths",
             "10f_forward_portfolios", "11_backtest_results", "12_validation", "13_results", "14_report", "run_meta"]  # fmt: skip
    out = {n: _load(d / f"{n}.json") for n in names}
    out["run_id"] = run_id
    req_id = (out["run_meta"] or {}).get("request_id") or (out["01_request"] or {}).get("request_id")
    out["request_doc"] = _load(STORE / "requests" / f"{req_id}.json") if req_id else None
    out["llm_usage_rows"] = [json.loads(l) for l in (d / "llm_usage.jsonl").read_text(encoding="utf-8").splitlines() if l.strip()] if (d / "llm_usage.jsonl").exists() else []
    return out


# ───────────────────────── 지표 ─────────────────────────
def independent_cagr_mdd(index: list[float], td: int = 252) -> tuple[float, float]:
    """라이브러리와 무관하게 시계열에서 다시 계산한 CAGR·최대낙폭 (요구 6 '수기 계산값과 비교')."""
    idx = np.asarray(index, dtype=float)
    n = len(idx) - 1
    cagr = float((idx[-1] / idx[0]) ** (td / n) - 1.0) if n > 0 and idx[0] > 0 else float("nan")
    mdd = float((idx / np.maximum.accumulate(idx) - 1.0).min())
    return cagr, mdd


def conditions_metrics(run: dict[str, Any], scenario: dict[str, Any] | None) -> dict[str, Any]:
    """요구 1·2·4: 시나리오(또는 요청)의 조건이 선정·구성·백테스트에 반영됐는지."""
    req = run["01_request"] or {}
    cons = req.get("constraints", {})
    src = (scenario or req)
    scons = src.get("constraints", {})
    sel = run["05_selection"] or {}
    spec = run["07_backtest_spec"] or {}
    selected_now = [s["ticker"] for s in sel.get("selected", [])]
    bt_tickers = list((spec.get("selection") or {}).get("tickers", []))
    must = list(scons.get("must_include_tickers", []))
    excl = list(scons.get("exclude_tickers", []))
    universe = list(scons.get("universe", []))
    markets_ok = {"SP500": "US", "NASDAQ100": "US", "KOSPI200": "KR"}
    allowed_markets = {markets_ok[u] for u in universe if u in markets_ok}
    table = ((run["13_results"] or {}).get("selection") or {}).get("table", [])
    market_of = {t["ticker"]: t.get("market") for t in table}
    bad_market = [t for t in selected_now + bt_tickers if market_of.get(t) and market_of[t] not in allowed_markets]
    it = run["02_intent"] or {}
    rules = {r["theme"]: r for r in it.get("exclude_theme_rules", [])}
    cand = run["03_candidates"] or {}
    by_filter = (cand.get("stats") or {}).get("by_filter", {})
    base = (run["10_target_portfolios"] or {})
    templates = base.get("templates", [])
    min_cash = float(scons.get("min_cash_ratio", 0) or 0)
    invested = {p["id"]: round(sum(p["weights"].values()), 4) for p in templates}
    cash_ok = all(v <= 1 - min_cash + 1e-6 for v in invested.values()) if templates else None
    derived = req.get("derived", {})
    want_as_of = str((src.get("horizon") or {}).get("start_date") or "")[:10]
    bt = run["11_backtest_results"] or {}
    n_reb = (bt.get("portfolios") or [{}])[0].get("metrics", {}).get("trading", {}).get("n_rebalances")
    return {
        "must_include": {"requested": must, "in_selection_now": [t for t in must if t in selected_now], "in_backtest": [t for t in must if t in bt_tickers], "ok": all(t in selected_now for t in must) and all(t in bt_tickers for t in must)},
        "exclude_tickers": {"requested": excl, "leaked": [t for t in excl if t in selected_now or t in bt_tickers], "ok": not any(t in selected_now or t in bt_tickers for t in excl)},
        "exclude_themes": {"requested": list(scons.get("exclude_themes", [])), "rules_made": {k: {"gics": v.get("gics_codes", []), "keywords": v.get("keywords", [])[:5]} for k, v in rules.items()},
                           "ok": all(t in rules for t in scons.get("exclude_themes", [])), "filtered_by_theme": {k: v for k, v in by_filter.items() if "theme" in k or "exclude" in k}},
        "universe": {"requested": universe, "selected_markets": sorted({market_of.get(t) for t in selected_now if market_of.get(t)}), "leaked_other_market": bad_market, "ok": not bad_market},
        "min_cash_ratio": {"requested": min_cash, "invested_by_template": invested, "ok": cash_ok},
        "caps": {"stock": cons.get("max_weight_per_stock"), "sector": cons.get("max_weight_per_sector"), "integrity_all_pass": all(c["status"] == "pass" for r in (run["12_validation"] or {}).get("results", []) for c in r.get("integrity", []))},
        "rebalance": {"rule": (spec.get("rebalance_rule") or {}).get("description_ko"), "n_rebalances": n_reb},
        "as_of": {"requested": want_as_of or None, "used": str(derived.get("as_of")), "ok": (not want_as_of) or str(derived.get("as_of")) <= want_as_of, "derive_warnings": derived.get("warnings", [])},
        "backtest_window": {"start": str(derived.get("backtest_start")), "end": str(derived.get("backtest_end")), "years_requested": (src.get("horizon") or {}).get("backtest_years"), "trading_days": (bt.get("period") or {}).get("trading_days")},
        "template": {"requested": (src.get("strategy_preference") or {}).get("template"), "metric_used": (sel.get("summary") or {}).get("metric")},
        "n_selected": {"target": (scons.get("num_holdings") or {}).get("target"), "min": (scons.get("num_holdings") or {}).get("min"), "selected_now": len(selected_now), "backtest": len(bt_tickers)},
    }


def dialog_metrics(run: dict[str, Any]) -> dict[str, Any]:
    doc = run["request_doc"] or {}
    qs = doc.get("questions", [])
    it = run["02_intent"] or {}
    return {"n_questions": len(qs), "max_questions": doc.get("max_questions"),
            "questions": [{"seq": q["seq"], "field": q["field"], "kind": q["kind"], "question_ko": q["question_ko"], "options": [o.get("label_ko") for o in q.get("options", [])], "answer": q.get("answer"), "skipped": q.get("skipped", False)} for q in qs],
            "overrides": {k: v for k, v in (doc.get("overrides") or {}).items() if not str(k).startswith("_")}, "clarifications": doc.get("idea_clarifications", []),
            "conflicts": it.get("interpretation", {}).get("conflicts", []), "summary_ko": it.get("interpretation", {}).get("summary_ko"),
            "themes": [{"id": t["id"], "label_ko": t["label_ko"], "gics": t.get("gics_codes", []), "keywords": t.get("keywords", [])[:8]} for t in it.get("interpretation", {}).get("themes", [])],
            "explanation_level": (it.get("report_settings") or {}).get("explanation_level"), "effective_max_drawdown": (it.get("risk_params") or {}).get("effective_max_drawdown")}  # fmt: skip


def selection_metrics(run: dict[str, Any]) -> dict[str, Any]:
    cand, tag, sel = run["03_candidates"] or {}, run["04_tagging"] or {}, run["05_selection"] or {}
    return {"n_matched": (cand.get("stats") or {}).get("n_matched"), "n_candidates": (cand.get("stats") or {}).get("n_candidates"), "by_rule": (cand.get("stats") or {}).get("by_rule"),
            "n_tag_passed": len(tag.get("passed_tickers", [])), "n_with_metric": (sel.get("summary") or {}).get("n_with_metric"), "n_selected": (sel.get("summary") or {}).get("n_selected"),
            "selected": [{"ticker": s["ticker"], "name": s.get("name"), "sector": s.get("sector"), "rank": s.get("rank"), "metric": s.get("metric_value"), "theme_conf": s.get("theme_confidence")} for s in sel.get("selected", [])],
            "sector_counts": (sel.get("summary") or {}).get("sector_counts"), "infeasibility": sel.get("infeasibility"), "warnings": sel.get("warnings", [])}  # fmt: skip


def construction_metrics(run: dict[str, Any]) -> dict[str, Any]:
    wf = run["10w_target_paths"] or {}
    bl = next((p for p in wf.get("portfolios", []) if p.get("kind") == "black_litterman"), None)
    views = [v for d in sorted((bl or {}).get("views_by_date", {})) for v in bl["views_by_date"][d]] if bl else []
    kinds = {"news": 0, "disclosure": 0, "mixed": 0}
    for v in views:
        ks = {("disclosure" if i.startswith("dc") else "news") for i in v.get("evidence_ids", []) if i.startswith(("ev", "dc"))}
        kinds["mixed" if len(ks) > 1 else ("disclosure" if "disclosure" in ks else "news")] += 1
    ns = wf.get("news_summary", {})
    tg = run["10_target_portfolios"] or {}
    return {"n_rebalance_dates": len(wf.get("dates", [])), "fallback_dates": len((bl or {}).get("fallback_dates", [])), "dates_with_disclosures": sum(1 for x in ns.values() if (x.get("n_disclosures") or 0) > 0),
            "dates_with_news": sum(1 for x in ns.values() if (x.get("n_articles") or 0) > 0), "n_views": len(views), "views_by_evidence": kinds,
            "start_bl_portfolios": len(tg.get("portfolios", [])), "templates": [p["id"] for p in tg.get("templates", [])], "max_tilt": (tg.get("parameters") or {}).get("max_tilt_per_stock"),
            "forward_fallback": (run["10f_forward_portfolios"] or {}).get("fallback"), "forward_reason": (run["10f_forward_portfolios"] or {}).get("fallback_reason_ko")}  # fmt: skip


def backtest_metrics(run: dict[str, Any]) -> dict[str, Any]:
    bt = run["11_backtest_results"] or {}
    val = run["12_validation"] or {}
    chosen = val.get("chosen_id")
    rows = []
    for p in bt.get("portfolios", []):
        c, m = independent_cagr_mdd(p["series"]["index"])
        h = p["headline"]
        rows.append({"id": p["id"], "cagr": h["cagr"], "cagr_check": round(c, 6), "cagr_match": abs(c - h["cagr"]) < 2e-4, "mdd": h["max_drawdown"], "mdd_check": round(m, 6), "mdd_match": abs(m - h["max_drawdown"]) < 1e-4,  # 시계열이 소수 4자리로 저장돼 재계산 오차가 1e-6 쯤 생긴다
                     "sharpe": h["sharpe"], "final_value_usd": h["final_value_usd"]})
    bench = bt.get("benchmark", {})
    metric_names = ["total_return", "cagr", "ann_vol", "sharpe", "max_drawdown", "excess_cagr", "final_value_usd", "irr_annual"]
    p0 = (bt.get("portfolios") or [{}])[0]
    present = {k: (k in p0.get("headline", {}) or k in (p0.get("metrics") or {}).get("return", {}) or k in (p0.get("metrics") or {}).get("risk", {}) or k in p0.get("money", {}) or k in (p0.get("metrics") or {}).get("vs_benchmark", {})) for k in metric_names}
    return {"period": bt.get("period"), "engine": {k: bt.get("engine", {}).get(k) for k in ("commission_bps", "n_contributions", "contribution_usd", "risk_free_rate", "benchmarks")},
            "benchmark": {"id": bench.get("id"), "cagr": (bench.get("headline") or {}).get("cagr"), "mdd": (bench.get("headline") or {}).get("max_drawdown"), "final_value_usd": (bench.get("headline") or {}).get("final_value_usd"),
                          "same_contributions": (bench.get("money") or {}).get("contributions_usd") == p0.get("money", {}).get("contributions_usd")},
            "metrics_present": present, "portfolios": rows, "all_recomputed_match": all(r["cagr_match"] and r["mdd_match"] for r in rows),
            "validation": {"summary": val.get("summary"), "recommended": (val.get("recommended") or {}).get("id"), "verdict": (val.get("recommended") or {}).get("verdict"), "n_flag": (val.get("summary") or {}).get("n_flag"), "matched": [(p["id"], p.get("cash_ratio"), p["headline"].get("max_drawdown"), p.get("match_target")) for p in (run["11_backtest_results"] or {}).get("portfolios", []) if p.get("kind") == "matched"], "reason_ko": (val.get("recommended") or {}).get("reason_ko"), "chosen": chosen,
                           "alternatives": [(a["id"], a["status"]) for a in val.get("alternatives", [])], "criteria": {k: val.get("criteria", {}).get(k) for k in ("max_drawdown", "input_max_drawdown", "target_annual_return", "horizon_years", "volatility_preference")},
                           "chosen_checks": [(c["rule"], c["status"], c["message_ko"]) for r in val.get("results", []) + val.get("alternatives", []) if r["id"] == chosen for c in r.get("checks", [])]},
            "data_quality": {k: v for k, v in ((run["13_results"] or {}).get("data_quality") or {}).items() if k in ("expected_days", "usable", "excluded", "filled")}}  # fmt: skip


def evidence_metrics(run: dict[str, Any]) -> dict[str, Any]:
    """요구 3·8·15: 인용 실존, 기준일 이후 자료 0건 (뉴스 발행·공시 이용 가능일·지표 기준일·가격 날짜), 리밸런싱일별 창의 선견."""
    from backend.analysis.common.citations import CITE_RE

    R = run["13_results"] or {}
    doc = run["14_report"] or {}
    idx = R.get("evidence_index", {})
    as_of = str(R.get("request", {}).get("derived", {}).get("as_of"))
    kinds: dict[str, int] = {}
    late: list[str] = []
    for k, v in idx.items():
        kinds[v["kind"]] = kinds.get(v["kind"], 0) + 1
        d = str(v.get("available_on") or v.get("published_at") or v.get("data_as_of") or "")[:10]
        if v["kind"] in ("news", "disclosure", "financial") and d and d > as_of:
            late.append(k)
    cited: list[str] = []
    for s in doc.get("sections", []):
        for b in s["blocks"]:
            if b["type"] == "paragraphs":
                cited += [c for t in b["items"] for c in CITE_RE.findall(t)]
            elif b["type"] == "cards":
                cited += [c for it in b["items"] for c in CITE_RE.findall(it.get("text_ko", ""))]
            elif b["type"] == "companies":
                cited += [c for it in b["items"] for t in it.get("rationale_ko", []) for c in CITE_RE.findall(t)]
    missing = sorted({c for c in cited if c not in idx})
    # 리밸런싱일별 창: 창 끝 ≤ 그 리밸런싱일, 레코드 발행일 < 창 끝
    wins = (R.get("portfolio") or {}).get("news_windows") or []
    win_bad = 0
    for w in wins:
        end = str((w.get("window") or ["", ""])[1])
        for r in w.get("records", []) or []:
            if str(r.get("published_at", ""))[:10] >= end:
                win_bad += 1
        for r in w.get("disclosures", []) or []:
            if str(r.get("available_on", ""))[:10] >= end:
                win_bad += 1
    series_last = max((R.get("backtest") or {}).get("series_dates") or [""])
    comp = next((b for s in doc.get("sections", []) for b in s["blocks"] if b["type"] == "companies"), None)
    rat = [(it["ticker"], len(it.get("rationale_ko", [])), len(it.get("evidence_ids", []))) for it in (comp or {}).get("items", []) if it.get("in_selection_now")]
    return {"as_of": as_of, "index_by_kind": kinds, "after_as_of": late, "cited_unique": len(set(cited)), "cited_total": len(cited), "missing_citations": missing,
            "window_records_after_end": win_bad, "n_news_windows": len(wins), "price_series_last": series_last, "price_series_within_as_of": series_last <= as_of,
            "doc_evidence": len(doc.get("evidence", [])), "doc_bytes": len(json.dumps(doc, ensure_ascii=False).encode()) if doc else 0,
            "company_rationale": {"n": len(rat), "min_paragraphs": min((r[1] for r in rat), default=0), "all_cite": all(r[2] > 0 for r in rat) if rat else None, "detail": rat}}  # fmt: skip


def report_metrics(run: dict[str, Any]) -> dict[str, Any]:
    from backend.analysis.m5_backtest_report.report_check import check
    from backend.analysis.settings import AnalysisSettings

    doc, R = run["14_report"], run["13_results"]
    if not doc:
        return {"present": False}
    res = check(doc, R, AnalysisSettings())
    items = [{"item": name, "where": where, "ok": bool(fn(doc))} for name, where, fn in REPORT_ITEMS_12]
    paras = sum(len(b["items"]) for s in doc["sections"] for b in s["blocks"] if b["type"] == "paragraphs")
    sm = doc.get("summary") or {}
    return {"present": True, "doc_version": doc.get("doc_version"), "sections": [s["id"] for s in doc["sections"]], "seven_ok": [s["id"] for s in doc["sections"]] == SEVEN,
            "items_12": items, "items_12_ok": sum(1 for i in items if i["ok"]), "gate_errors": res.errors, "number_notes": len([w for w in res.warnings if "number" in w]), "dev_term_notes": len([w for w in res.warnings if "development" in w]),
            "n_paragraphs": paras, "headline_ko": (sm.get("verdict") or {}).get("headline_ko"), "verdict": (sm.get("verdict") or {}).get("label_ko"), "next_actions": len(sm.get("next_actions_ko", [])),
            "notices_user": [n.get("message_ko") for n in doc.get("notices", [])], "title_ko": doc.get("header", {}).get("title_ko"), "glossary": len(next((b["items"] for s in doc["sections"] for b in s["blocks"] if b["type"] == "glossary"), []))}  # fmt: skip


def execution_metrics(run: dict[str, Any]) -> dict[str, Any]:
    m = run["run_meta"] or {}
    steps = m.get("steps", [])
    t0 = min((s["started_at"] for s in steps if s.get("started_at")), default=None)
    t1 = max((s["ended_at"] for s in steps if s.get("ended_at")), default=None)
    elapsed = (dt.datetime.fromisoformat(t1) - dt.datetime.fromisoformat(t0)).total_seconds() if t0 and t1 else None
    u = m.get("llm_usage") or {}
    rows = run["llm_usage_rows"]
    by_stage: dict[str, int] = {}
    for r in rows:
        k = str(r.get("stage", "?")).split("_20")[0]
        by_stage[k] = by_stage.get(k, 0) + 1
    recorded = sum(1 for s in steps if s.get("status") and s.get("started_at") and (s.get("ended_at") or s["status"] in ("CANCELLED", "QUEUED")) and (s.get("summary") or s.get("error_message") or s["status"] == "CANCELLED"))
    return {"status": m.get("status"), "error": m.get("error"), "elapsed_s": round(elapsed) if elapsed else None, "steps": [(s["name"], s["status"], s.get("elapsed_s")) for s in steps],
            "steps_fully_recorded": f"{recorded}/{len(steps)}", "llm_calls": u.get("calls"), "llm_cost_usd": u.get("cost_usd"), "llm_cache_hits": u.get("cache_hits"), "llm_calls_by_stage": by_stage,
            "truncated_calls": sum(1 for r in rows if r.get("finish_reason") == "length"), "notices_user": [n.get("message_ko") for n in m.get("notices", []) if n.get("level") == "user"],
            "n_warnings_all": len(m.get("warnings", [])), "sources": [s["id"] for s in (run["13_results"] or {}).get("sources", [])]}  # fmt: skip


def grade_run(run_id: str, scenario_file: str | None) -> dict[str, Any]:
    run = load_run(run_id)
    scenario = _load(Path(scenario_file)) if scenario_file else None
    return {"run_id": run_id, "scenario_file": scenario_file, "idea": ((scenario or run["01_request"] or {}).get("natural_language") or {}).get("idea"),
            "conditions": conditions_metrics(run, scenario), "dialog": dialog_metrics(run), "selection": selection_metrics(run), "construction": construction_metrics(run),
            "backtest": backtest_metrics(run), "evidence": evidence_metrics(run), "report": report_metrics(run), "execution": execution_metrics(run)}  # fmt: skip


def compare_runs(a: str, b: str) -> dict[str, Any]:
    """요구 14 결정론: 두 실행의 선정 종목·목표 비중·헤드라인 지표가 같은가."""
    ra, rb = load_run(a), load_run(b)
    sa = [s["ticker"] for s in (ra["05_selection"] or {}).get("selected", [])]
    sb = [s["ticker"] for s in (rb["05_selection"] or {}).get("selected", [])]
    ta = {p["id"]: p["weights"] for p in (ra["10_target_portfolios"] or {}).get("templates", []) + (ra["10_target_portfolios"] or {}).get("portfolios", [])}
    tb = {p["id"]: p["weights"] for p in (rb["10_target_portfolios"] or {}).get("templates", []) + (rb["10_target_portfolios"] or {}).get("portfolios", [])}
    w_same = sum(1 for k in ta if k in tb and all(abs(ta[k].get(t, 0) - tb[k].get(t, 0)) < 1e-6 for t in set(ta[k]) | set(tb[k])))
    ha = {p["id"]: (p["headline"]["cagr"], p["headline"]["max_drawdown"], p["headline"]["final_value_usd"]) for p in (ra["11_backtest_results"] or {}).get("portfolios", [])}
    hb = {p["id"]: (p["headline"]["cagr"], p["headline"]["max_drawdown"], p["headline"]["final_value_usd"]) for p in (rb["11_backtest_results"] or {}).get("portfolios", [])}
    h_same = sum(1 for k in ha if k in hb and all(abs(x - y) < 1e-9 for x, y in zip(ha[k], hb[k], strict=True)))
    va, vb = (ra["12_validation"] or {}).get("chosen_id"), (rb["12_validation"] or {}).get("chosen_id")
    return {"a": a, "b": b, "selected_same": sa == sb, "selected_a": sa, "selected_b": sb, "weights_same": f"{w_same}/{len(ta)}", "headline_same": f"{h_same}/{len(ha)}",
            "chosen_same": va == vb, "llm_cache_hits_b": (rb["run_meta"] or {}).get("llm_usage", {}).get("cache_hits"), "llm_calls_b": (rb["run_meta"] or {}).get("llm_usage", {}).get("calls")}  # fmt: skip


# ───────────────────────── markdown 뼈대 ─────────────────────────
def _yn(v: Any) -> str:
    return "✅" if v is True else ("❌" if v is False else "–")


def skeleton_md(tag: str, g: dict[str, Any]) -> str:
    c, d, s, k, b, e, r, x = g["conditions"], g["dialog"], g["selection"], g["construction"], g["backtest"], g["evidence"], g["report"], g["execution"]
    L: list[str] = [f"# {tag} 채점 기록 — `{g['run_id']}`", "", f"시나리오 파일: `{g['scenario_file']}`", "", f"> 아이디어: {g['idea']}", "",
                    "## 1. 자동 지표 (grade.py)", "", "### 조건 반영 (요구 1·2·4)", "", "| 항목 | 요청 | 결과 | 판정 |", "| --- | --- | --- | --- |",
                    f"| 필수 포함 | {', '.join(c['must_include']['requested']) or '없음'} | 지금 {', '.join(c['must_include']['in_selection_now']) or '-'} · 백테스트 {', '.join(c['must_include']['in_backtest']) or '-'} | {_yn(c['must_include']['ok'] if c['must_include']['requested'] else None)} |",
                    f"| 제외 종목 | {', '.join(c['exclude_tickers']['requested']) or '없음'} | 새어 들어온 것 {', '.join(c['exclude_tickers']['leaked']) or '없음'} | {_yn(c['exclude_tickers']['ok'])} |",
                    f"| 제외 테마 | {', '.join(c['exclude_themes']['requested']) or '없음'} | 규칙 생성 {', '.join(c['exclude_themes']['rules_made']) or '없음'} · 후보에서 걸러진 수 {c['exclude_themes']['filtered_by_theme'] or 0} | {_yn(c['exclude_themes']['ok'] if c['exclude_themes']['requested'] else None)} |",
                    f"| 유니버스 | {', '.join(c['universe']['requested'])} | 선정 시장 {', '.join(c['universe']['selected_markets'])} | {_yn(c['universe']['ok'])} |",
                    f"| 최소 현금 | {c['min_cash_ratio']['requested']:.0%} | 규칙별 투자 비율 {c['min_cash_ratio']['invested_by_template']} | {_yn(c['min_cash_ratio']['ok'])} |",
                    f"| 상한 준수(내부 점검) | 종목 {c['caps']['stock']} · 섹터 {c['caps']['sector']} | 리밸런싱일 상한 점검 | {_yn(c['caps']['integrity_all_pass'])} |",
                    f"| 리밸런싱 | {c['rebalance']['rule']} | 실제 {c['rebalance']['n_rebalances']}회 | – |",
                    f"| 기준일 | {c['as_of']['requested']} | 사용 {c['as_of']['used']} | {_yn(c['as_of']['ok'])} |",
                    f"| 백테스트 창 | 기본 3년 | {c['backtest_window']['start']} ~ {c['backtest_window']['end']} ({c['backtest_window']['trading_days']}거래일) | – |",
                    f"| 선정 기준 | {c['template']['requested']} | 지표 {c['template']['metric_used']} | {_yn(c['template']['metric_used'] is not None)} |",
                    f"| 종목 수 | 목표 {c['n_selected']['target']} (최소 {c['n_selected']['min']}) | 지금 {c['n_selected']['selected_now']} · 백테스트 {c['n_selected']['backtest']} | {_yn((c['n_selected']['selected_now'] or 0) >= (c['n_selected']['min'] or 0))} |",
                    "", f"기준일 계산 안내: {'; '.join(c['as_of']['derive_warnings']) or '없음'}", "",
                    "### 보충 질문 (요구 2)", "", f"질문 {d['n_questions']}개 (상한 {d['max_questions']}), 덮어쓰기 {d['overrides']}, 보충 답변 {d['clarifications']}", ""]
    for q in d["questions"]:
        L.append(f"- Q{q['seq']} [{q['kind']}] `{q['field']}` — {q['question_ko']}  \n  보기: {q['options']}  \n  답: **{q['answer']}**{' (건너뜀)' if q['skipped'] else ''}")
    L += ["", f"해석 요약: {d['summary_ko']}", "", "테마: " + "; ".join(f"{t['label_ko']}({t['id']}) GICS {t['gics']} 키워드 {t['keywords']}" for t in d["themes"]), "",
          "충돌 기록: " + ("; ".join(f"{x.get('field')}: {x.get('issue_ko')} → {x.get('resolution_ko')} (idea_value={x.get('idea_value')})" for x in d["conflicts"]) or "없음"), "",
          f"설명 수준 {d['explanation_level']}, 검증에 쓰는 허용 낙폭 {d['effective_max_drawdown']}", "",
          "### 선정 (요구 4)", "", f"후보 검색 {s['n_matched']} → 필터 후 {s['n_candidates']} (규칙 {s['by_rule']}) → 테마 통과 {s['n_tag_passed']} → 지표 있음 {s['n_with_metric']} → 선정 {s['n_selected']}", "",
          "| 순위 | 종목 | 이름 | 섹터 | 지표 | 테마 신뢰도 |", "| --- | --- | --- | --- | --- | --- |"]
    L += [f"| {x['rank']} | {x['ticker']} | {x['name']} | {x['sector']} | {x['metric']:.4f} | {x['theme_conf']} |" for x in s["selected"]]
    L += ["", f"섹터 분포 {s['sector_counts']} · 배분 불능 {s['infeasibility']} · 선정 경고 {s['warnings']}", "",
          "### 구성 (요구 4)", "", f"리밸런싱 {k['n_rebalance_dates']}회 중 기준 비중 유지(근거 부족) {k['fallback_dates']}회 · 공시 있는 날 {k['dates_with_disclosures']} · 뉴스 있는 날 {k['dates_with_news']} · 뷰 {k['n_views']}개 (근거: {k['views_by_evidence']}) · 시작일 BL {k['start_bl_portfolios']}개 · 종목당 이동 한도 {k['max_tilt']} · 현재 구성 fallback {k['forward_fallback']} {k['forward_reason'] or ''}", "",
          "### 백테스트·검증 (요구 5·6)", "", f"창 {b['period']} · 엔진 {b['engine']} · 비교지수 {b['benchmark']}", "",
          f"7지표 존재 {b['metrics_present']} · **독립 재계산 일치(CAGR·MDD)**: {_yn(b['all_recomputed_match'])}", "",
          "| 포트폴리오 | CAGR | 재계산 | MDD | 재계산 | Sharpe | 최종 USD |", "| --- | --- | --- | --- | --- | --- | --- |"]
    L += [f"| {p['id']} | {p['cagr']:.4f} | {p['cagr_check']:.4f} {_yn(p['cagr_match'])} | {p['mdd']:.4f} | {p['mdd_check']:.4f} {_yn(p['mdd_match'])} | {p['sharpe']} | {p['final_value_usd']:,.0f} |" for p in b["portfolios"]]
    v = b["validation"]
    L += ["", f"검증 요약 {v['summary']} · 추천 {v['recommended']} {((v.get('verdict') or {}).get('label_ko') or '')} · 낙폭 맞춤안 {v.get('matched')} · 선택안 {v['chosen']} · 대안 {v['alternatives']} · 기준 {v['criteria']}", "", f"추천 사유: {v['reason_ko']}", "", "선택안 판정:"]
    L += [f"- {rule} {st}: {msg}" for rule, st, msg in v["chosen_checks"]]
    L += ["", f"자료 품질 {b['data_quality']}", "",
          "### 근거·선견 (요구 3·8·15)", "", f"색인 {e['index_by_kind']} · 본문 인용 {e['cited_total']}회/{e['cited_unique']}종 · 색인에 없는 인용 {e['missing_citations'] or '없음'} · **기준일 이후 자료 {len(e['after_as_of'])}건** {e['after_as_of'][:5]} · 리밸런싱 창 밖 레코드 {e['window_records_after_end']}건 ({e['n_news_windows']}창) · 가격 마지막 날짜 {e['price_series_last']} ≤ 기준일 {_yn(e['price_series_within_as_of'])} · 문서 근거 {e['doc_evidence']}건 · 문서 {e['doc_bytes'] / 1024:.0f}KB", "",
          f"기업별 근거: 종목 {e['company_rationale']['n']}개, 최소 문단 {e['company_rationale']['min_paragraphs']}, 모두 인용 {_yn(e['company_rationale']['all_cite'])}", ""]
    if r.get("present"):
        L += ["### 리포트 (요구 7·8·C-12)", "", f"문서 v{r['doc_version']} · 7섹션 {_yn(r['seven_ok'])} · 개념설계 12항목 {r['items_12_ok']}/12 · 게이트 오류 {r['gate_errors'] or '없음'} · 숫자 대조 메모 {r['number_notes']}건 · 개발 용어 {r['dev_term_notes']}건 · 문단 {r['n_paragraphs']}개 · 용어 {r['glossary']}개", "",
              "| 12항목 | 어디에 | 있음 |", "| --- | --- | --- |"]
        L += [f"| {i['item']} | {i['where']} | {_yn(i['ok'])} |" for i in r["items_12"]]
        L += ["", f"제목: {r['title_ko']} · 판단: {r['verdict']} · 한 줄 결론: {r['headline_ko']} · 다음 행동 {r['next_actions']}개", "", f"사용자 공지(§6): {r['notices_user'] or '없음'}", ""]
    else:
        L += ["### 리포트", "", "리포트 없음 (실행 실패)", ""]
    L += ["### 실행 (요구 9·12, C6)", "", f"상태 {x['status']} · 소요 {x['elapsed_s']}초 · LLM {x['llm_calls']}회 ${x['llm_cost_usd']} (캐시 {x['llm_cache_hits']}, 잘림 {x['truncated_calls']}) · 단계 기록 {x['steps_fully_recorded']} · 자료 출처 {x['sources']}", "",
          "단계: " + ", ".join(f"{n} {st}({el}s)" for n, st, el in x["steps"]), "", f"오류: {x['error']}", "",
          "## 2. 사람 판독 (채점자가 채움)", "",
          "| # | 항목 | 점수(0~2) | 근거 (파일·필드·인용문) |", "| --- | --- | --- | --- |",
          "| 1 | 조건 반영 |  |  |", "| 2 | 보충 질문의 적절성 |  |  |", "| 3 | 해석 적합성 |  |  |", "| 4 | 선정 타당성 |  |  |", "| 5 | 구성 |  |  |",
          "| 6 | 백테스트·검증 논리 |  |  |", "| 7 | 근거·선견 |  |  |", "| 8 | 리포트 서술 품질 |  |  |", "| 9 | 실행 |  |  |", "| 10 | 사용자에게 보이는 상태 |  |  |", "", "**합계: /20 → /100**", ""]
    return "\n".join(L)


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="backend.analysis.eval.grade")
    ap.add_argument("--from", dest="from_dir", help="run_scenarios 결과 폴더 (각 JSON 의 run_id·scenario_file 사용)")
    ap.add_argument("--run", help="run_id 하나")
    ap.add_argument("--scenario", help="시나리오 파일 (run 과 함께)")
    ap.add_argument("--out", help="출력 폴더 (기본: --from 폴더 또는 output/<run_id>)")
    ap.add_argument("--compare", nargs=2, metavar=("RUN_A", "RUN_B"), help="결정론 비교")
    a = ap.parse_args(argv)
    if a.compare:
        print(json.dumps(compare_runs(*a.compare), ensure_ascii=False, indent=1))
        return 0
    jobs: list[tuple[str, str, str | None]] = []
    if a.from_dir:
        for p in sorted(Path(a.from_dir).glob("*.json")):
            if p.name in ("metrics.json",):
                continue
            d = _load(p)
            if isinstance(d, dict) and d.get("run_id"):
                jobs.append((p.stem, d["run_id"], d.get("scenario_file")))
    elif a.run:
        jobs.append((a.run, a.run, a.scenario))
    else:
        ap.error("--from 또는 --run 이 필요합니다")
    out_dir = Path(a.out or a.from_dir or (OUT / jobs[0][1]))
    out_dir.mkdir(parents=True, exist_ok=True)
    allm: dict[str, Any] = {}
    for tag, run_id, sf in jobs:
        g = grade_run(run_id, sf)
        allm[tag] = g
        md = out_dir / f"{tag}.md"
        if not md.exists():  # 채점자가 채운 기록을 덮어쓰지 않는다
            md.write_text(skeleton_md(tag, g), encoding="utf-8")
        print(f"{tag}: {run_id} → {md.name}" + ("" if not md.exists() else ""), flush=True)
    (out_dir / "metrics.json").write_text(json.dumps(allm, ensure_ascii=False, indent=1, default=str), encoding="utf-8")
    print("written", out_dir / "metrics.json")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
