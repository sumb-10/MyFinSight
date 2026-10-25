"""M5-05 리포트 문서 생성기. 일곱 섹션 (상세설계 4장 '바'):

  verdict 종합 투자 판단 · market 산업과 시장 분석 · companies 기업별 투자 근거 · construction 포트폴리오 구성과 운용 ·
  performance 과거 성과와 해석 · assumptions 판단의 전제와 재검토 조건 · references 참고자료와 분석 조건

표·차트·KPI 는 코드(report_blocks), 해석·서술 문단은 LLM (14a 해석 · 14b 서술 · 14c 시장 분석). 문단의 숫자·인용은 report_check 가 대조하고
실패하면 ReportCheckError (리포트를 내지 않음).
"""

from __future__ import annotations

import datetime as dt
import json
from typing import Any

from backend.analysis.common.jsonio import now_iso
from backend.analysis.common.llm import LlmClient, messages_from_prompts
from backend.analysis.common.prompts import load_prompts
from backend.analysis.errors import ReportCheckError
from backend.analysis.m5_backtest_report import report_blocks as B
from backend.analysis.m5_backtest_report.report_check import check
from backend.analysis.schemas.report import ReportDoc
from backend.analysis.settings import AnalysisSettings


def _need(ans: dict[str, Any], key: str, min_n: int = 1) -> None:
    v = ans.get(key)
    if not isinstance(v, list) or len(v) < min_n:
        raise ValueError(f"'{key}' must be a list with >= {min_n} items")


def facts_for_interpret(R: dict[str, Any], chosen: str) -> dict[str, Any]:
    bt = R["backtest"]
    p, b = B.find(R, chosen), bt["benchmark"]
    base = next(x for x in bt["portfolios"] if x["id"] == R["portfolio"]["targets"]["baseline"]["id"])
    val = R["validation"]
    quarters = [{"date": c["date"], "return": c["since_last"]["return"], "benchmark_return": c["since_last"]["benchmark_return"], "best": c["since_last"]["best"], "worst": c["since_last"]["worst"]}
                for c in p["checkpoints"] if c["since_last"]]  # fmt: skip
    contrib = sorted(((t, v) for t, v in p["ticker_contribution"].items() if v is not None), key=lambda x: -x[1])
    calc_ids = {k: v["id"] for k, v in R["evidence_index"].items() if k.startswith("calc:") and k.endswith(":" + chosen)}
    return {"citation_rule": "숫자를 쓸 때 가능한 곳마다 [calc:<metric>:<portfolio_id>] 형식의 근거 ID 를 붙인다 (아래 calc_ids 에 있는 것만).",
            "calc_ids": sorted(calc_ids), "all_calc_ids": sorted(k for k in R["evidence_index"] if k.startswith("calc:")),
            "user": {"max_drawdown_tolerance": float(R["request"]["risk"]["max_drawdown_tolerance"]), "matched_target": R["intent"]["risk_params"].get("effective_max_drawdown"),
                     "target_annual_return": R["intent"]["validation_criteria"]["target_annual_return"],
                     "volatility_preference": R["intent"]["risk_params"]["volatility_preference"], "risk_tolerance": R["request"]["risk"]["risk_tolerance"],
                     "horizon_years": R["request"]["horizon"]["target_years"], "benchmark": R["portfolio"]["backtest_spec"]["benchmark"]},
            "assumptions": {**bt["engine"], "period": bt["period"]},
            "chosen": {"id": chosen, "label": B.pf_label(p), "kind": p["kind"], "is_recommended": bool(val.get("recommended")), "verdict": (val.get("recommended") or {}).get("verdict"),
                       "base_id": p.get("base_id"), "cash_ratio": p.get("cash_ratio"), "match_target": p.get("match_target"), "headline": p["headline"], "return": p["metrics"]["return"],
                       "risk": p["metrics"]["risk"], "risk_adjusted": p["metrics"]["risk_adjusted"], "vs_benchmark": p["metrics"]["vs_benchmark"], "vs_baseline": p["metrics"]["vs_baseline"],
                       "composition": {k: p["metrics"]["composition"][k] for k in ["effective_n", "top3_contribution_share", "sector_weights_avg"]}, "trading": p["metrics"]["trading"],
                       "money": {**p["money"], **R["money_krw"]["by_portfolio"][chosen]}, "yearly_returns": p["yearly_returns"], "quarters": quarters,
                       "ticker_contribution_top": contrib[:3], "ticker_contribution_bottom": contrib[-3:], "view_diagnostics": p["view_diagnostics"],
                       "cash_weight": round(1 - sum(p["target_weights"].values()), 4)},
            "benchmark": {"label": b["name_ko"], "headline": b["headline"], "yearly_returns": b["yearly_returns"], "money": b["money"]},
            "other_benchmarks": [{"label": x["name_ko"], "headline": x["headline"]} for x in bt.get("benchmarks", []) if x["id"] != b["id"]],
            "matched": [{"id": x["id"], "label": x["name_ko"], "base_id": x.get("base_id"), "cash_ratio": x.get("cash_ratio"), "cash_ratio_total": x.get("cash_ratio_total"),
                         "match_target": x.get("match_target"), "headline": x["headline"], "status": next((r["status"] for r in val["results"] if r["id"] == x["id"]), None)}
                        for x in bt["portfolios"] if x.get("kind") == "matched"],
            "news_effect": B.news_effect(R),
            "window": {"trading_days": bt["period"]["trading_days"], "annualized_reliable": bt["period"].get("annualized_reliable", True),
                       "note": "창이 1.5년 미만이면(annualized_reliable=false) CAGR·Sharpe·XIRR 같은 연환산 값은 참고용이며 기간 수익률(total_return)로 말해야 함",
                       "period_note_ko": B.period_note(R)},
            "walkforward": ({"dates": R["portfolio"]["walkforward"]["dates"], "news_summary": R["portfolio"]["walkforward"]["news_summary"],
                             "fallback_dates": next(p for p in R["portfolio"]["walkforward"]["portfolios"] if p["kind"] == "black_litterman")["fallback_dates"],
                             "results": [{"id": x["id"], "label": x["name_ko"], "headline": x["headline"]} for x in bt["portfolios"] if x.get("mode") == "walkforward"]}
                            if R["portfolio"].get("walkforward") else None),
            "selection_infeasibility": R["selection"]["backtest_as_of"].get("infeasibility"), "sector_overflow": R["selection"]["backtest_as_of"].get("sector_overflow"),
            "baseline": {"id": base["id"], "headline": base["headline"], "money": base["money"]}, "comparison": B.comparison_table(R)["rows"],
            "validation": {"criteria": val["criteria"], "chosen_checks": (next((r for r in val["results"] if r["id"] == chosen), None) or next((a for a in val.get("alternatives", []) if a["id"] == chosen), {})).get("checks"),
                           "summary": val["summary"], "per_portfolio_status": {r["id"]: r["status"] for r in val["results"]}, "recommended": val.get("recommended"),
                           "chosen_id": val.get("chosen_id"), "warnings": [n["message_ko"] for n in (R.get("notices") or []) if n.get("stage") == "12_validation"]},
            "fx": R["money_krw"]["direction"]}  # fmt: skip


def _chosen_note(R: dict[str, Any], p: dict[str, Any], is_rec: bool) -> str:
    vd = (R["validation"].get("recommended") or {}).get("verdict")
    if vd:
        if vd["status"] == "insufficient":
            return "후보 종목이 모자라 투자 비율이 낮습니다. 순위 1위 구성을 중심으로 설명하지만 그대로 투자하기에는 부족합니다."
        if vd.get("cautions_ko"):
            return "후보 중 순위 1위 구성입니다. 주의: " + " · ".join(vd["cautions_ko"]) + "."
        return "후보 중 순위 1위로 추천된 구성입니다."
    if is_rec:
        return "검증 결과 추천된 포트폴리오입니다."
    if p["kind"] == "alternative":
        return "조건을 통과한 포트폴리오가 없어 검증 단계가 계산한 현금 혼합안을 중심으로 설명합니다."
    return "조건을 통과한 포트폴리오가 없어 기준 포트폴리오를 중심으로 설명합니다."


def facts_for_market(R: dict[str, Any]) -> dict[str, Any]:
    idx = R["evidence_index"]
    news = [{"id": k, "ticker": (v.get("tickers") or [""])[0], "published_at": v.get("published_at"), "title": v.get("title"), "source": v.get("source"), "language": v.get("language")}
            for k, v in idx.items() if v["kind"] == "news"]  # fmt: skip
    news.sort(key=lambda x: (x["published_at"] or ""), reverse=True)
    discl = [{"id": k, "ticker": (v.get("tickers") or [""])[0], "available_on": v.get("available_on"), "filed_at": v.get("filed_at"), "event": v.get("event_label_ko"),
              "form": v.get("form"), "items": v.get("items"), "title": v.get("title"), "source": v.get("source")} for k, v in idx.items() if v["kind"] == "disclosure"]  # fmt: skip
    discl.sort(key=lambda x: (x["available_on"] or ""), reverse=True)
    event_summary: dict[str, dict[str, int]] = {}
    for d_ in discl:
        event_summary.setdefault(d_["ticker"], {})
        event_summary[d_["ticker"]][d_["event"] or "기타"] = event_summary[d_["ticker"]].get(d_["event"] or "기타", 0) + 1
    chosen, _ = B.chosen_portfolio_id(R)
    p = B.find(R, chosen)
    bench = R["backtest"]["benchmark"]
    f = R["portfolio"].get("forward") or {}
    return {"citation_rule": "모든 사실 문장은 [ev123](뉴스) 또는 [dc45](공시) 처럼 아래 목록의 id 를 인용한다. 목록에 없는 id·숫자·사건을 만들지 않는다. 헤드라인과 공시는 사건의 존재·종류·시점만 알려 준다 (실적 발표 공시 ≠ 좋은 실적).",
            "as_of": R["request"]["derived"]["as_of"], "summary_ko": R["intent"]["interpretation"]["summary_ko"],
            "themes": [{"id": t["id"], "label": t["label_ko"], "description": t["description_ko"]} for t in R["intent"]["interpretation"]["themes"]],
            "universe": R["request"]["constraints"]["universe"], "holdings": [{"ticker": t["ticker"], "name": t["name"], "sector": t["sector"], "market": t.get("market")} for t in R["selection"]["table"] if t["in_selection_now"]],
            "sector_exposure": p["metrics"]["composition"]["sector_weights_avg"],
            "benchmark": {"label": bench["name_ko"], "cagr": bench["headline"]["cagr"], "max_drawdown": bench["headline"]["max_drawdown"]},
            "news": news[:60], "disclosures": discl[:40], "event_summary_90d": event_summary, "news_window": f.get("news_window"),
            "forward_views": [v["summary_ko"] for pp in f.get("portfolios", []) for v in pp["views_applied"]]}  # fmt: skip


def facts_for_narrate(R: dict[str, Any], chosen: str, interp: dict[str, Any]) -> dict[str, Any]:
    p = B.find(R, chosen)
    bl = R["portfolio"]["baselines"]
    base = next(x for x in bl["portfolios"] if x["id"] == bl["chosen_baseline"])
    f = R["portfolio"].get("forward")
    return {"citation_rule": "선정·구성 설명에서 지표 값을 말할 때는 [fin:...] 근거 ID(선정 표의 fact id), 성과 숫자는 [calc:...] 를 인용한다. 목록에 없는 id 는 쓰지 않는다.",
            "fact_ids": [t.get("metric_fact_id") for t in R["selection"]["table"] if t.get("metric_fact_id")],
            "calc_ids": sorted(k for k in R["evidence_index"] if k.startswith("calc:") and k.endswith(":" + chosen)),
            "request": {r["k"]: r["v"] for r in B.request_table(R)["rows"]},
            "intent": {"summary": R["intent"]["interpretation"]["summary_ko"], "themes": [{"label": t["label_ko"], "description": t["description_ko"]} for t in R["intent"]["interpretation"]["themes"]],
                       "conflicts": R["intent"]["interpretation"].get("conflicts", []), "risk_params": R["intent"]["risk_params"], "constraints": {r["k"]: r["v"] for r in B.constraints_table(R)["rows"]}},
            "selection": {"metric": R["selection"]["metric"], "funnel": R["selection"]["funnel"], "table": R["selection"]["table"], "excluded_examples": R["selection"]["as_of_now"]["rejected_examples"],
                          "diff": R["selection"]["backtest_as_of"]["diff_vs_original"], "warnings": [n["message_ko"] for n in (R.get("notices") or []) if n.get("stage") in ("05_selection", "07_backtest_spec")], "explained": R["selection"].get("explained")},
            "construction": {"baseline": {"id": base["id"], "rule": base["rule_ko"], "n": len(base["weights"]), "weights": base["weights"], "cash_weight": base.get("cash_weight", 0),
                                          "constraints_applied": base["constraints_applied"], "sector_weights": base["sector_weights"]},
                             "templates": B.templates_table(R)["rows"], "max_tilt": R["portfolio"]["targets"]["parameters"].get("max_tilt_per_stock"),
                             "news_tilt_enabled": R["intent"]["news_tilt"]["enabled"], "start_views": R["portfolio"]["views"],
                             "scenarios": [{"title": s.get("title_ko"), "narrative": (s.get("portfolio_view") or "").split("\n")[0], "views": [v["summary_ko"] for v in s["views_applied"]],
                                            "top_delta": sorted(s["delta_vs_baseline"].items(), key=lambda x: -abs(x[1]))[:3]} for s in R["portfolio"]["targets"]["portfolios"]],
                             "chosen": {"id": chosen, "label": B.pf_label(p), "allocation": B.allocation_table(R, chosen)["rows"]},
                             "walkforward": R["portfolio"].get("walkforward") and {"dates": R["portfolio"]["walkforward"]["dates"], "news_summary": R["portfolio"]["walkforward"]["news_summary"]}},
            "interpretation": {**interp, "window": R["backtest"]["period"]},
            "forward": ({"as_of": f["as_of"], "news_window": f.get("news_window"), "fallback_reason": f.get("fallback_reason_ko"),
                         "portfolios": [{"id": x["id"], "title": x.get("title_ko"), "narrative": (x.get("portfolio_view") or "").split("\n")[0], "views": [v["summary_ko"] for v in x["views_applied"]],
                                         "evidence_ids": sorted({i for v in x["views_applied"] for i in v.get("evidence_ids", [])}), "top_delta": sorted(x["delta_vs_baseline"].items(), key=lambda y: -abs(y[1]))[:3]} for x in f["portfolios"]],
                         "evidence": {i: {"date": e["published_at"], "publisher": e.get("publisher"), "title": e["title"]} for i, e in f["evidence"].items()}} if f else None),
            "data_quality": R.get("data_quality"), "limitations": B.limitations(R), "parameters": {r["k"]: r["v"] for r in B.parameters_table(R)["rows"]}}  # fmt: skip


def call_interpret(R, chosen, llm):
    system, user = load_prompts("14a_interpret", facts_json=json.dumps(facts_for_interpret(R, chosen), ensure_ascii=False, indent=1, default=str))

    def _check(a):
        for k, n in [("performance_ko", 2), ("risk_fit_ko", 1), ("validation_ko", 1), ("next_actions_ko", 2)]:
            _need(a, k, n)

    ans = llm.complete_json("14a_interpret", messages_from_prompts(system, user), validator=_check)
    ans.setdefault("headline_ko", "")
    ans.setdefault("view_review_ko", [])
    ans.setdefault("news_ko", [])
    ans.setdefault("assessment", {"intent_fit": None, "logic_consistency": None, "comments_ko": []})
    return ans


def call_market(R, llm):
    system, user = load_prompts("14c_market", facts_json=json.dumps(facts_for_market(R), ensure_ascii=False, indent=1, default=str))
    ans = llm.complete_json("14c_market", messages_from_prompts(system, user), validator=lambda a: _need(a, "market_ko", 1))
    return ans


def call_narrate(R, chosen, interp, llm):
    system, user = load_prompts("14b_narrate", facts_json=json.dumps(facts_for_narrate(R, chosen, interp), ensure_ascii=False, indent=1, default=str),
                                interpretation_json=json.dumps(interp, ensure_ascii=False, indent=1))  # fmt: skip

    def _check(a):
        for k, n in [("overview_ko", 2), ("request_interpretation_ko", 1), ("selection_ko", 1), ("construction_ko", 1), ("assumptions_ko", 1), ("reconsideration_ko", 1), ("glossary", 5)]:
            _need(a, k, n)

    ans = llm.complete_json("14b_narrate", messages_from_prompts(system, user), validator=_check)
    ans.setdefault("forward_ko", [])
    return ans


def _group(blocks: list[dict[str, Any] | None], group_ko: str, *, open_: bool = False) -> list[dict[str, Any]]:
    """연속 블록을 접힘 묶음으로 (Front 가 group_ko 가 같은 연속 블록을 하나의 접이식 묶음으로 그린다)."""
    out = []
    for b in blocks:
        if b:
            out.append({**b, "group_ko": group_ko, **({"group_open": True} if open_ else {})})
    return out


def cited_ids(sections: list[dict[str, Any]], idx: dict[str, Any]) -> list[str]:
    """문서가 실제로 인용한 근거 ID (문단·카드 인용, 기업 근거, 지표 근거, 근거 참조 블록, 뷰의 근거). 색인 순서로."""
    from backend.analysis.common.citations import CITE_RE

    used: set[str] = set()
    for sec in sections:
        for b in sec["blocks"]:
            t = b["type"]
            if t == "paragraphs":
                for x in b["items"]:
                    used.update(CITE_RE.findall(x))
            elif t == "cards":
                for it in b["items"]:
                    used.update(CITE_RE.findall(it.get("text_ko", "")))
                    for m in it.get("meta", []):
                        used.update(c for c in str(m.get("value", "")).replace(",", " ").split() if c in idx)
            elif t == "companies":
                for it in b["items"]:
                    used.update(it.get("evidence_ids", []))
                    if it.get("fact_id"):
                        used.add(it["fact_id"])
            elif t == "evidence_ref" and b.get("ids"):
                used.update(b["ids"])
            elif t == "timeline":
                for it in b["items"]:
                    for v in it.get("views", []):
                        used.update(v.get("evidence_ids", []))
            elif t == "table":
                for r in b.get("rows", []):
                    for v in r.values():
                        if isinstance(v, str) and v in idx:
                            used.add(v)
    return [k for k in idx if k in used]


def build_doc(R: dict[str, Any], *, interp: dict[str, Any], narr: dict[str, Any], market: dict[str, Any], step_summaries: dict[str, str] | None,
              settings: AnalysisSettings) -> dict[str, Any]:  # fmt: skip
    """문서 v2: 요약 대시보드(summary) + 7부분. 무거운 표는 묶음(group_ko)으로 접고, 근거 색인은 인용된 것만 evidence 에 싣는다 (나머지는 /evidence)."""
    chosen, is_rec = B.chosen_portfolio_id(R)
    p = B.find(R, chosen)
    bt = R["backtest"]
    dates = bt["series_dates"]
    series = {x["id"]: {"label_ko": B.pf_label(x), "kind": x["kind"], **x["series"]} for x in B.all_blocks(R)}
    led = {l["date"]: l["amount_usd"] for l in p["contribution_ledger"]}
    inv, cum = [], p["money"]["initial_usd"]
    for d in dates:
        cum += led.get(d, 0.0)
        inv.append(round(cum, 2))
    series["net_invested"] = {"label_ko": "투입 원금(누적)", "kind": "reference", "value_usd": inv}
    all_ids = [x["id"] for x in B.all_blocks(R)]
    base_id = R["portfolio"]["targets"]["baseline"]["id"]
    default_on = list(dict.fromkeys([chosen, bt["benchmark"]["id"], base_id]))[:3]
    label = B.pf_label(p)
    themes = R["intent"]["interpretation"]["themes"]
    metric = R["selection"]["metric"]
    title_short = f"{themes[0]['label_ko']}" + (f" 외 {len(themes) - 1}" if len(themes) > 1 else "") + f" · {B.METRIC_SHORT_KO.get(metric, metric)} 전략"
    header = {"title_ko": title_short,
              "title_detail_ko": f"{themes[0]['label_ko']}" + (f" 외 {len(themes) - 1}개 테마" if len(themes) > 1 else "") + f" · {metric} 선정 · {label}",
              "subtitle_ko": R["intent"]["interpretation"]["summary_ko"], "created_at": dt.date.today().isoformat(),
              "selection_as_of": R["selection"]["as_of_now"]["as_of"], "backtest_period": R["portfolio"]["backtest_spec"]["period"],
              "data_as_of": str(R["request"]["derived"]["as_of"]), "chosen_portfolio_id": chosen, "chosen_label_ko": label,
              "chosen_note_ko": _chosen_note(R, p, is_rec),
              "disclaimer_ko": "이 리포트는 투자 판단을 돕기 위한 자료이며 특정 종목의 매수·매도를 지시하지 않습니다. 과거 성과는 미래 성과를 보장하지 않습니다.",
              "run_id": R["run_id"], "backtest_mode": bt.get("mode")}  # fmt: skip
    kp = B.kpis(R, chosen)
    bl_ids = [x["id"] for x in R["portfolio"]["targets"]["portfolios"]]
    bl_for_bar = chosen if chosen in bl_ids else (bl_ids[0] if bl_ids else None)
    v_tab = B.view_table(R, chosen)
    t1, t2 = B.validation_tables(R, chosen)
    news_ids = B.news_used_ids(R)
    inf = B.infeasibility_callout(R)
    alt = B.alternatives_cards(R)
    conf = B.conflicts_cards(R)
    wf_tl = B.timeline(R, chosen)
    wf_notes = [b for b in B.walkforward_blocks(R) if b["type"] == "callout"]  # walk-forward 요약 콜아웃만 (표·뷰 카드는 타임라인으로)
    fwd = B.forward_blocks(R)

    def nz(*blocks):
        return [b for b in blocks if b]

    sections = [
        {"id": "verdict", "title_ko": "종합 투자 판단", "blocks": nz(
            {"type": "paragraphs", "items": narr["overview_ko"], "tone": "lead", "src": "14b"}, {"type": "kpis", "ids": [k["id"] for k in kp]},
            {"type": "paragraphs", "items": interp["risk_fit_ko"], "src": "14a"})},
        {"id": "market", "title_ko": "산업과 시장 분석", "blocks": nz(
            {"type": "paragraphs", "items": narr["request_interpretation_ko"], "src": "14b"},
            *_group([B.themes_table(R), conf, B.request_table(R), B.constraints_table(R), B.soft_table(R)], "요청 조건 확인"),
            {"type": "paragraphs", "items": market["market_ko"], "src": "14c"}, B.sector_bar(R, chosen),
            B.evidence_ref(R, sorted(set(news_ids) | set(market.get("evidence_ids_used", []))), "시장 분석·뷰에 인용된 뉴스·공시 근거") if (news_ids or market.get("evidence_ids_used")) else None)},
        {"id": "companies", "title_ko": "기업별 투자 근거", "blocks": nz(
            {"type": "paragraphs", "items": narr["selection_ko"], "src": "14b"}, B.funnel(R), inf,
            {"type": "callout", "tone": "info", "title_ko": "선정 지표", "text_ko": _metric_note(metric)},
            B.companies(R, chosen), *_group([B.excluded_table(R), B.diff_table(R)], "제외된 종목과 재선정 차이"))},
        {"id": "construction", "title_ko": "포트폴리오 구성과 운용", "blocks": nz(
            {"type": "paragraphs", "items": narr["construction_ko"], "src": "14b"}, B.weights_compare(R), B.scenario_cards(R),
            B.delta_bar(R, bl_for_bar) if bl_for_bar else None, B.allocation_table(R, chosen),
            *([{"type": "paragraphs", "items": interp.get("news_ko") or [], "src": "14a"}] if interp.get("news_ko") else []),
            wf_tl, *wf_notes,
            *_group([*([{"type": "paragraphs", "items": narr.get("forward_ko") or [], "src": "14b"}] if narr.get("forward_ko") else []), *fwd], "분석 기준일의 현재 구성", open_=True))},
        {"id": "performance", "title_ko": "과거 성과와 해석", "blocks": nz(
            B.assumptions_callout(R),
            {"type": "line", "title_ko": "누적 수익률 (시작 = 100)", "dataset": "index", "series_ids": all_ids, "default_on": default_on, "y_format": "index"},
            {"type": "paragraphs", "items": interp["performance_ko"], "src": "14a"},
            {"type": "line", "title_ko": "평가금액과 투입 원금 (USD)", "dataset": "value_usd", "series_ids": [chosen, bt["benchmark"]["id"], "net_invested"], "default_on": [chosen, bt["benchmark"]["id"], "net_invested"], "y_format": "usd"},
            {"type": "area", "title_ko": "고점 대비 낙폭", "dataset": "drawdown", "series_ids": default_on, "default_on": default_on, "y_format": "pct"},
            B.comparison_table(R), *_group([B.yearly_table(R, chosen), B.monthly_table(R, chosen)], "연도별·월별 수익률"), B.contribution_bar(R, chosen),
            *_group([*([v_tab, {"type": "paragraphs", "items": interp["view_review_ko"], "src": "14a"}] if v_tab and interp.get("view_review_ko") else []),
                     {"type": "paragraphs", "items": interp["validation_ko"], "src": "14a"}, t1, t2, alt], "검증 상세", open_=True))},
        {"id": "assumptions", "title_ko": "판단의 전제와 재검토 조건", "blocks": nz(
            {"type": "paragraphs", "items": narr["assumptions_ko"] + narr["reconsideration_ko"], "src": "14b"}, B.data_quality_table(R), B.notices_table(R),
            {"type": "cards", "title_ko": "다음에 검토할 수 있는 선택지", "src": "14a", "items": [{"title_ko": f"선택지 {i + 1}", "text_ko": s, "meta": []} for i, s in enumerate(interp["next_actions_ko"])]},
            {"type": "cards", "title_ko": "확인한 한계", "items": [{"title_ko": f"한계 {i + 1}", "text_ko": s, "meta": []} for i, s in enumerate(B.limitations(R))]})},
        {"id": "references", "title_ko": "참고자료와 분석 조건", "blocks": nz(
            *_group([B.sources_table(R), B.parameters_table(R), B.execution_table(R, step_summaries)], "자료 출처·계산 조건·실행 기록"),
            {"type": "glossary", "items": narr["glossary"]},
            B.evidence_ref(R, None, "근거 색인 (뉴스·공시·재무 지표·계산값)"))},
    ]  # fmt: skip
    idx = R["evidence_index"]
    used = cited_ids(sections, idx)
    evidence = [{"id": k, "kind": v["kind"], "title": v.get("title", ""), "source": v.get("source", ""), "url": v.get("url"), "published_at": v.get("published_at"),
                 "data_as_of": v.get("data_as_of"), "tickers": v.get("tickers", []), "value": v.get("value"), "unit": v.get("unit"), "language": v.get("language"),
                 **({"event_type": v.get("event_type"), "event_label_ko": v.get("event_label_ko"), "form": v.get("form"), "items": v.get("items"),
                     "filed_at": v.get("filed_at"), "available_on": v.get("available_on")} if v["kind"] == "disclosure" else {})}
                for k, v in ((k, idx[k]) for k in used)]  # fmt: skip
    by_kind: dict[str, int] = {}
    for v in idx.values():
        by_kind[v["kind"]] = by_kind.get(v["kind"], 0) + 1
    dates_s, series_s, sampling = B.sample_series(dates, series, max_points=settings.report.max_series_points, pin_id=chosen)
    datasets = {"dates": dates_s, "series": series_s, **({"sampling": sampling} if sampling else {})}
    execution = [{"step": k, "summary": v} for k, v in (step_summaries or {}).items()]
    summary = B.build_summary(R, chosen, interp, narr)
    doc = ReportDoc(request_id=R["request_id"], run_id=R["run_id"], generated_at=now_iso(), source="13_results", header=header, kpis=kp,
                    nav=[{"id": s["id"], "title_ko": s["title_ko"]} for s in sections], sections=sections, datasets=datasets,
                    assessment=interp["assessment"], evidence=evidence, execution=execution, tracking={"eligible": True, "reason_ko": None},
                    sources=R["sources"], parameters=R["parameters"], warnings=[], notices=list(R.get("notices") or []),
                    doc_version=2, summary=summary, evidence_summary={"total": len(idx), "cited": len(used), "by_kind": by_kind})  # fmt: skip
    return doc.model_dump(mode="json")


def present_doc(doc: dict[str, Any], R: dict[str, Any] | None = None) -> dict[str, Any]:
    """저장된 문서를 화면용으로 (읽기 시 정규화). v2 는 그대로. v1(라운드 3 이전) 은 근거 색인을 인용된 것만 남기고 evidence 블록을 evidence_ref 로 바꾼다.

    R(13_results) 이 있으면 v1 에도 summary 를 보강한다. 저장 문서는 바꾸지 않는다.
    """
    if doc.get("doc_version", 1) >= 2:
        return doc
    out = json.loads(json.dumps(doc))
    idx = {e["id"]: e for e in out.get("evidence", [])}
    for sec in out["sections"]:
        blocks = []
        for b in sec["blocks"]:
            if b["type"] == "evidence":
                ids = [it["id"] for it in b.get("items", [])]
                full = len(ids) >= max(1, len(idx)) - 2  # 색인 전체를 복사한 블록(참고자료)
                blocks.append({"type": "evidence_ref", "title_ko": b.get("title_ko", "근거"), "ids": None if full else ids, "count": len(ids),
                               "kinds": {k: sum(1 for i in ids if idx.get(i, {}).get("kind") == k) for k in {idx.get(i, {}).get("kind") for i in ids if i in idx}}})  # fmt: skip
            else:
                blocks.append(b)
        sec["blocks"] = blocks
    used = cited_ids(out["sections"], idx)
    by_kind: dict[str, int] = {}
    for v in idx.values():
        by_kind[v["kind"]] = by_kind.get(v["kind"], 0) + 1
    out["evidence"] = [idx[k] for k in used]
    out["evidence_summary"] = {"total": len(idx), "cited": len(used), "by_kind": by_kind}
    out["presented_from_version"] = 1
    out["doc_version"] = 1  # 저장 문서의 형식은 그대로 1 (화면은 이 값으로 변환 여부를 안다)
    if R is not None and out.get("summary") is None:
        try:
            chosen = out["header"].get("chosen_portfolio_id") or B.chosen_portfolio_id(R)[0]
            next_actions = next((b for s_ in out["sections"] for b in s_["blocks"] if b["type"] == "cards" and b.get("title_ko", "").startswith("다음에 검토")), None)
            interp_like = {"next_actions_ko": [it["text_ko"] for it in (next_actions or {}).get("items", [])]}
            narr_like = {"overview_ko": next((b["items"] for s_ in out["sections"] if s_["id"] == "verdict" for b in s_["blocks"] if b["type"] == "paragraphs"), [])}
            out["summary"] = B.build_summary(R, chosen, interp_like, narr_like)
        except Exception:  # noqa: BLE001 — 옛 문서 보강은 실패해도 문서 자체는 보여 준다
            out["summary"] = None
    return out


def _metric_note(metric: str) -> str:
    return {"return_12m_1m": "모멘텀(return_12m_1m)은 최근 12개월 주가 수익률에서 가장 최근 1개월을 뺀 값입니다. 단기 반전 효과를 피하려 최근 1개월을 빼며, 값이 높은 순서로 뽑습니다.",
            "vol_60d": "저변동성(vol_60d)은 최근 60거래일 일수익률의 연환산 표준편차입니다. 값이 낮은 순서로 뽑습니다.",
            "pe_ttm": "저PER(pe_ttm)은 기준일 종가를 그날까지 공시된 최근 4분기 주당순이익으로 나눈 값입니다. 적자 기업은 제외하고 낮은 순서로 뽑습니다.",
            "roe_ttm": "퀄리티(roe_ttm)는 최근 4분기 순이익을 평균 자본으로 나눈 자기자본이익률입니다. 높은 순서로 뽑습니다.",
            "dividend_yield_ttm": "고배당(dividend_yield_ttm)은 최근 1년 주당배당금을 기준일 종가로 나눈 값입니다. 높은 순서로 뽑습니다."}.get(metric, metric)  # fmt: skip


def _retry_feedback(errors: list[str]) -> dict[str, str]:
    return {"role": "user", "content": ("직전 리포트 문단 검증에서 다음 문제가 있었습니다. 고쳐서 같은 스키마로 다시 출력하세요.\n"
                                       "- banned phrase 는 그 단어를 문장에서 빼고 다른 말로 바꾸라는 뜻입니다 (예: '보장' → '장담할 수 없습니다', '달라질 수 있습니다').\n"
                                       "- unknown citation 은 근거 목록에 없는 인용 ID 를 썼다는 뜻입니다. 목록에 있는 ID 만 쓰거나 인용을 빼세요.\n"
                                       "- missing section 은 일곱 부분 중 빠진 것이 있다는 뜻입니다.\n문제 목록:\n- " + "\n- ".join(errors[:12]))}


def _both(a, b, parallel: bool):
    """두 LLM 호출을 동시에 (14a ∥ 14c). 둘 다 서로의 결과를 쓰지 않는다."""
    if not parallel:
        return a(), b()
    from concurrent.futures import ThreadPoolExecutor

    with ThreadPoolExecutor(max_workers=2, thread_name_prefix="mfs-report") as pool:
        fa, fb = pool.submit(a), pool.submit(b)
        return fa.result(), fb.result()


def generate_report(R: dict[str, Any], llm: LlmClient, settings: AnalysisSettings, *, step_summaries: dict[str, str] | None = None) -> tuple[dict[str, Any], list[str]]:
    """LLM 세 번(14a ∥ 14c → 14b) → 문서 → 검증. 검증 오류가 있으면 오류를 낸 호출만 피드백으로 1회 다시 받고, 그래도 실패면 ReportCheckError."""
    chosen, _ = B.chosen_portfolio_id(R)
    parallel = settings.executor.parallel_report_calls
    interp, market = _both(lambda: call_interpret(R, chosen, llm), lambda: call_market(R, llm), parallel)
    narr = call_narrate(R, chosen, interp, llm)
    doc = build_doc(R, interp=interp, narr=narr, market=market, step_summaries=step_summaries, settings=settings)
    res = check(doc, R, settings)
    if res.errors:
        srcs = res.sources_to_retry() or {"14b", "14c"}  # 어디서 났는지 모르면 예전처럼 서술 둘을 다시
        by = res.errors_by_src

        def _errs(*keys: str) -> list[str]:
            got = [e for k in keys for e in by.get(k, [])]
            return got or res.errors

        def _redo_interp():
            system, user = load_prompts("14a_interpret", facts_json=json.dumps(facts_for_interpret(R, chosen), ensure_ascii=False, indent=1, default=str))
            a = llm.complete_json("14a_interpret", [*messages_from_prompts(system, user), {"role": "assistant", "content": json.dumps(interp, ensure_ascii=False)}, _retry_feedback(_errs("14a"))])
            for k, v in [("view_review_ko", []), ("news_ko", []), ("assessment", interp.get("assessment"))]:
                a.setdefault(k, v)
            return a

        def _redo_market():
            system, user = load_prompts("14c_market", facts_json=json.dumps(facts_for_market(R), ensure_ascii=False, indent=1, default=str))
            return llm.complete_json("14c_market", [*messages_from_prompts(system, user), {"role": "assistant", "content": json.dumps(market, ensure_ascii=False)}, _retry_feedback(_errs("14c", "doc"))],
                                     validator=lambda a: _need(a, "market_ko", 1))  # fmt: skip

        if "14a" in srcs and "14c" in srcs:
            interp, market = _both(_redo_interp, _redo_market, parallel)
        elif "14a" in srcs:
            interp = _redo_interp()
        elif "14c" in srcs:
            market = _redo_market()
        if "14b" in srcs or "14a" in srcs:  # 서술(14b)은 해석(14a)을 입력으로 쓰므로 14a 가 바뀌면 함께
            system, user = load_prompts("14b_narrate", facts_json=json.dumps(facts_for_narrate(R, chosen, interp), ensure_ascii=False, indent=1, default=str),
                                        interpretation_json=json.dumps(interp, ensure_ascii=False, indent=1))  # fmt: skip
            narr = llm.complete_json("14b_narrate", [*messages_from_prompts(system, user), {"role": "assistant", "content": json.dumps(narr, ensure_ascii=False)}, _retry_feedback(_errs("14b", "doc"))])
            narr.setdefault("forward_ko", [])
        doc = build_doc(R, interp=interp, narr=narr, market=market, step_summaries=step_summaries, settings=settings)
        res = check(doc, R, settings)
        if res.errors:
            raise ReportCheckError("리포트 검증 실패: " + "; ".join(res.errors[:5]), details={"errors": res.errors, "warnings": res.warnings, "by_src": res.errors_by_src})
    doc["warnings"] = [w for w in res.warnings if "development term" not in w]  # 숫자 대조 메모만 문서에 (개발 용어 메모는 실행 기록 파일로)
    return doc, res.warnings
