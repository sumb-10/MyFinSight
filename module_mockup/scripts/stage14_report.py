"""
Stage 14: build the render-ready report document from 13_results.json.

  code  : tables / charts / KPIs / checkpoints (report_blocks.py)
  LLM#5a: result interpreter  (prompts/14a_interpret)  -> performance / risk fit / validation / next actions / assessment
  LLM#5b: narrative generator (prompts/14b_narrate)    -> overview / interpretation / selection / construction / assumptions / glossary
out: output/14_report.json ; in api mode the raw answers are also saved as stubs/14a_*.example.json, 14b_*.example.json
"""
import argparse, datetime as dt, json, os, re, shutil
from common import OUTPUT, STUBS, load_json, dump_json
from llm import load_prompts, call_llm
import report_blocks as B
from schemas import ReportDoc

BANNED = ["샘플", "stub", "mock", "JSON", "보장합니다", "보장됩니다", "확실히"]


def facts_for_interpret(R, chosen):
    bt = R["backtest"]; p = next(x for x in bt["portfolios"] if x["id"] == chosen); b = bt["benchmark"]
    base = next(x for x in bt["portfolios"] if x["id"] == R["portfolio"]["targets"]["baseline"]["id"])
    comp = B.comparison_table(R)["rows"]
    quarters = [{"date": c["date"], "return": c["since_last"]["return"], "benchmark_return": c["since_last"]["benchmark_return"],
                 "best": c["since_last"]["best"], "worst": c["since_last"]["worst"]} for c in p["checkpoints"] if c["since_last"]]
    contrib = sorted(p["ticker_contribution"].items(), key=lambda x: -x[1])
    val = R["validation"]
    return {"user": {"max_drawdown_tolerance": R["intent"]["risk_params"]["effective_max_drawdown"], "target_annual_return": R["intent"]["validation_criteria"]["target_annual_return"],
                     "volatility_preference": R["intent"]["risk_params"]["volatility_preference"], "risk_tolerance": R["request"]["risk"]["risk_tolerance"],
                     "horizon_years": R["request"]["horizon"]["target_years"], "benchmark": R["portfolio"]["backtest_spec"]["benchmark"]},
            "assumptions": {**bt["engine"], "period": bt["period"]},
            "chosen": {"id": chosen, "label": B.pf_label(p), "is_recommended": bool(val.get("recommended")), "headline": p["headline"],
                       "return": p["metrics"]["return"], "risk": p["metrics"]["risk"], "risk_adjusted": p["metrics"]["risk_adjusted"],
                       "vs_benchmark": p["metrics"]["vs_benchmark"], "vs_baseline": p["metrics"]["vs_baseline"],
                       "composition": {k: p["metrics"]["composition"][k] for k in ["effective_n", "top3_contribution_share", "sector_weights_avg"]},
                       "trading": p["metrics"]["trading"], "money": {**p["money"], **R["money_krw"]["by_portfolio"][chosen]}, "yearly_returns": p["yearly_returns"],
                       "quarters": quarters, "ticker_contribution_top": contrib[:3], "ticker_contribution_bottom": contrib[-3:], "view_diagnostics": p["view_diagnostics"]},
            "benchmark": {"label": b["name_ko"], "headline": b["headline"], "yearly_returns": b["yearly_returns"], "money": b["money"]},
            "baseline_equal_weight": {"headline": base["headline"], "money": base["money"]},
            "comparison": comp,
            "validation": {"criteria": val["criteria"], "chosen_checks": next(r for r in val["results"] if r["id"] == chosen)["checks"],
                           "summary_note": "summary counts PORTFOLIOS by overall status (not individual checks)", "summary": val["summary"],
                           "per_portfolio_status": {r["id"]: r["status"] for r in val["results"]},
                           "recommended": val.get("recommended"), "warnings": val["warnings"]},
            "fx": R["money_krw"]["direction"]}


def facts_for_narrate(R, chosen, interp):
    p = next(x for x in R["backtest"]["portfolios"] if x["id"] == chosen)
    base = next(x for x in R["portfolio"]["baselines"]["portfolios"] if x["id"] == R["portfolio"]["baselines"]["chosen_baseline"])
    return {"request": {r["k"]: r["v"] for r in B.request_table(R)["rows"]},
            "intent": {"summary": R["intent"]["interpretation"]["summary_ko"], "themes": [{"label": t["label_ko"], "description": t["description_ko"]} for t in R["intent"]["interpretation"]["themes"]],
                       "conflicts": R["intent"]["interpretation"]["conflicts"], "risk_params": R["intent"]["risk_params"], "constraints": {r["k"]: r["v"] for r in B.constraints_table(R)["rows"]}},
            "selection": {"metric": R["selection"]["metric"], "funnel": R["selection"]["funnel"], "table": R["selection"]["table"],
                          "excluded_examples": R["selection"]["as_of_2026"]["rejected_examples"], "diff": R["selection"]["backtest_as_of"]["diff_vs_original"],
                          "warnings": R["selection"]["as_of_2026"]["warnings"]},
            "construction": {"baseline": {"rule": "1/N 동일비중", "n": len(base["weights"]), "weights": base["weights"], "constraints_applied": base["constraints_applied"], "sector_weights": base["sector_weights"]},
                             "templates": B.templates_table(R)["rows"], "max_tilt": R["portfolio"]["targets"]["parameters"]["max_tilt_per_stock"],
                             "scenarios": [{"title": s["title_ko"], "narrative": s["portfolio_view"].split("\n")[0], "views": [v["summary_ko"] for v in s["views_applied"]],
                                            "top_delta": sorted(s["delta_vs_baseline"].items(), key=lambda x: -abs(x[1]))[:3]} for s in R["portfolio"]["targets"]["portfolios"]],
                             "chosen": {"id": chosen, "label": B.pf_label(p), "allocation": B.allocation_table(R, chosen)["rows"]}},
            "interpretation": interp, "limitations": B.limitations(R),
            "parameters": {r["k"]: r["v"] for r in B.parameters_table(R)["rows"]}}


def known_numbers(obj, acc):
    if isinstance(obj, dict):
        for v in obj.values(): known_numbers(v, acc)
    elif isinstance(obj, list):
        for v in obj: known_numbers(v, acc)
    elif isinstance(obj, bool):
        return
    elif isinstance(obj, (int, float)):
        v = abs(float(obj))
        if v <= 20: acc.add(round(v * 100, 1)); acc.add(round(v * 100))
        acc.add(round(v, 1)); acc.add(round(v))


def audit(paragraphs, known, label):
    warns = []
    for para in paragraphs:
        for m in re.finditer(r"(-?\d+(?:\.\d+)?)\s*%", para):
            v = abs(float(m.group(1)))
            if round(v, 1) not in known and round(v) not in known:
                warns.append(f"{label}: number {m.group(0)} not found in facts")
        for w in BANNED:
            if w in para: warns.append(f"{label}: banned word '{w}'")
    return warns


def need(ans, key, min_n=1):
    v = ans.get(key)
    if not isinstance(v, list) or len(v) < min_n:
        raise RuntimeError(f"LLM answer missing '{key}' (need >= {min_n} items)")
    return v


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--results", default=str(OUTPUT / "13_results.json"))
    ap.add_argument("--out", default=str(OUTPUT / "14_report.json"))
    a = ap.parse_args()
    R = load_json(a.results)
    chosen, is_rec = B.chosen_portfolio_id(R)
    p = next(x for x in R["backtest"]["portfolios"] if x["id"] == chosen)
    warnings = []

    # ── LLM #5a interpret ──
    f1 = facts_for_interpret(R, chosen)
    system, user = load_prompts("14a_interpret", facts_json=json.dumps(f1, ensure_ascii=False, indent=1))
    interp = call_llm("14a_interpret", system, user)
    for k, n in [("performance_ko", 2), ("risk_fit_ko", 1), ("validation_ko", 1), ("next_actions_ko", 2)]: need(interp, k, n)
    interp.setdefault("view_review_ko", []); interp.setdefault("assessment", {"intent_fit": None, "logic_consistency": None, "comments_ko": []})
    # ── LLM #5b narrate ──
    f2 = facts_for_narrate(R, chosen, interp)
    system, user = load_prompts("14b_narrate", facts_json=json.dumps(f2, ensure_ascii=False, indent=1), interpretation_json=json.dumps(interp, ensure_ascii=False, indent=1))
    narr = call_llm("14b_narrate", system, user)
    for k, n in [("overview_ko", 2), ("request_interpretation_ko", 1), ("selection_ko", 1), ("construction_ko", 1), ("assumptions_ko", 1), ("reconsideration_ko", 1), ("glossary", 5)]: need(narr, k, n)
    if os.environ.get("MYFINSIGHT_LLM") == "api":
        for stage in ["14a_interpret", "14b_narrate"]:
            src = OUTPUT / "llm_raw" / f"{stage}.json"
            if src.exists(): shutil.copy(src, STUBS / f"{stage}.example.json")
        warnings.append("stubs/14a,14b updated from this API run")
    known = set(); known_numbers({k: v for k, v in R.items() if k != "backtest"}, known); known_numbers({k: v for k, v in R["backtest"].items() if k != "series_dates"}, known)
    for key in ["performance_ko", "risk_fit_ko", "validation_ko", "view_review_ko", "next_actions_ko"]: warnings += audit(interp[key], known, f"14a.{key}")
    for key in ["overview_ko", "request_interpretation_ko", "selection_ko", "construction_ko", "assumptions_ko", "reconsideration_ko"]: warnings += audit(narr[key], known, f"14b.{key}")

    # ── datasets ──
    bt = R["backtest"]; dates = bt["series_dates"]
    series = {}
    for x in [*bt["portfolios"], bt["benchmark"]]:
        series[x["id"]] = {"label_ko": B.pf_label(x) if x["kind"] != "benchmark" else x["name_ko"], "kind": x["kind"], **x["series"]}
    led = {l["date"]: l["amount_usd"] for l in p["contribution_ledger"]}; inv, cum = [], p["money"]["initial_usd"]
    for d in dates:
        cum += led.get(d, 0.0); inv.append(round(cum, 2))
    series["net_invested"] = {"label_ko": "투입 원금(누적)", "kind": "reference", "value_usd": inv}
    all_ids = [x["id"] for x in bt["portfolios"]] + [bt["benchmark"]["id"]]
    default_on = [chosen, R["portfolio"]["targets"]["baseline"]["id"], bt["benchmark"]["id"]]

    label = B.pf_label(p)
    header = {"title_ko": f"{R['intent']['interpretation']['themes'][0]['label_ko']} 외 {len(R['intent']['interpretation']['themes']) - 1}개 테마 · {R['selection']['metric']} 선정 · {label}",
              "subtitle_ko": R["intent"]["interpretation"]["summary_ko"], "created_at": dt.date.today().isoformat(),
              "selection_as_of": R["selection"]["as_of_2026"]["as_of"], "backtest_period": R["portfolio"]["backtest_spec"]["period"],
              "data_as_of": bt["reproducibility"]["prices_file"]["last_date"], "chosen_portfolio_id": chosen, "chosen_label_ko": label,
              "chosen_note_ko": "검증을 통과한 포트폴리오가 없어 기준 포트폴리오(동일비중)를 중심으로 설명합니다." if not is_rec else "검증 결과 추천된 포트폴리오입니다.",
              "disclaimer_ko": "이 리포트는 투자 판단을 돕기 위한 자료이며 특정 종목의 매수·매도를 지시하지 않습니다. 과거 성과는 미래 성과를 보장하지 않습니다."}
    kp = B.kpis(R, chosen)
    bl_for_bar = chosen if p["kind"] == "black_litterman" else R["portfolio"]["targets"]["portfolios"][0]["id"]
    v_tab = B.view_table(R, chosen); t1, t2 = B.validation_tables(R, chosen)
    rec = R["validation"].get("recommended")
    rec_card = {"type": "cards", "title_ko": "추천 결과", "items": [{"title_ko": f"추천: {B.pf_label(next(x for x in bt['portfolios'] if x['id'] == rec['id']))}" if rec else "추천 포트폴리오 없음",
                "text_ko": rec["reason_ko"] if rec else "; ".join(R["validation"]["warnings"]) or "모든 포트폴리오가 필수 검증 규칙을 통과하지 못했습니다.",
                "meta": [{"label_ko": "통과/주의/미통과", "value": f"{R['validation']['summary']['n_pass']}/{R['validation']['summary']['n_warn']}/{R['validation']['summary']['n_fail']}"}]}]}
    sections = [
        {"id": "overview", "title_ko": "한눈에 보기", "blocks": [{"type": "paragraphs", "items": narr["overview_ko"], "tone": "lead"}, {"type": "kpis", "ids": [k["id"] for k in kp]},
                                                        B.request_table(R), {"type": "callout", "tone": "info", "title_ko": "읽기 전에", "text_ko": header["disclaimer_ko"] + " " + header["chosen_note_ko"]}]},
        {"id": "interpretation", "title_ko": "요청을 이렇게 이해했습니다", "blocks": [{"type": "paragraphs", "items": narr["request_interpretation_ko"]}, B.themes_table(R), B.constraints_table(R), B.soft_table(R)]
            + ([{"type": "cards", "title_ko": "입력 간에 확인한 점", "items": [{"title_ko": c["field"], "text_ko": c["issue_ko"] + " → " + c["resolution_ko"], "meta": []} for c in R["intent"]["interpretation"]["conflicts"]]}] if R["intent"]["interpretation"]["conflicts"] else [])},
        {"id": "selection", "title_ko": "종목을 고른 과정", "blocks": [{"type": "paragraphs", "items": narr["selection_ko"]}, B.funnel(R),
                                                           {"type": "callout", "tone": "info", "title_ko": "선정 지표", "text_ko": "모멘텀(return_12m_1m)은 최근 12개월 주가 수익률에서 가장 최근 1개월을 뺀 값입니다. 최근 1개월을 빼는 이유는 단기 반전 효과를 피하기 위해서이며, 값이 높은 순서로 뽑습니다."},
                                                           B.selection_table(R), B.excluded_table(R), B.diff_table(R)]},
        {"id": "construction", "title_ko": "포트폴리오를 이렇게 나눴습니다", "blocks": [{"type": "paragraphs", "items": narr["construction_ko"]}, B.baseline_table(R), B.templates_table(R)]
            + [B.donut(f"{B.NAMES.get(t['id'], t['id'])}", t["weights"]) for t in R["portfolio"]["baselines"]["portfolios"]]
            + [B.scenario_cards(R)] + [B.donut(f"시나리오: {s['title_ko']}", s["weights"]) for s in R["portfolio"]["targets"]["portfolios"]]
            + [B.delta_bar(R, bl_for_bar), B.allocation_table(R, chosen)]},
        {"id": "performance", "title_ko": "과거에 적용해 보니", "blocks": [B.assumptions_callout(R),
            {"type": "line", "title_ko": "누적 수익률 (시작 = 100)", "dataset": "index", "series_ids": all_ids, "default_on": default_on, "y_format": "index"},
            {"type": "paragraphs", "items": interp["performance_ko"]},
            {"type": "line", "title_ko": "평가금액과 투입 원금 (USD)", "dataset": "value_usd", "series_ids": [chosen, bt["benchmark"]["id"], "net_invested"], "default_on": [chosen, bt["benchmark"]["id"], "net_invested"], "y_format": "usd"},
            {"type": "area", "title_ko": "고점 대비 낙폭", "dataset": "drawdown", "series_ids": default_on, "default_on": default_on, "y_format": "pct"},
            {"type": "paragraphs", "items": interp["risk_fit_ko"]}, B.comparison_table(R), B.yearly_table(R, chosen), B.monthly_table(R, chosen), B.contribution_bar(R, chosen),
            B.checkpoints_block(R, chosen)] + ([v_tab, {"type": "paragraphs", "items": interp["view_review_ko"]}] if v_tab and interp["view_review_ko"] else [])},
        {"id": "validation", "title_ko": "검증 결과와 추천", "blocks": [{"type": "paragraphs", "items": interp["validation_ko"]}, t1, t2, rec_card,
                                                             {"type": "cards", "title_ko": "다음에 검토할 수 있는 선택지", "items": [{"title_ko": f"선택지 {i + 1}", "text_ko": s, "meta": []} for i, s in enumerate(interp["next_actions_ko"])]}]},
        {"id": "assumptions", "title_ko": "전제와 한계", "blocks": [{"type": "paragraphs", "items": narr["assumptions_ko"] + narr["reconsideration_ko"]},
                                                        {"type": "cards", "title_ko": "확인한 한계", "items": [{"title_ko": f"한계 {i + 1}", "text_ko": s, "meta": []} for i, s in enumerate(B.limitations(R))]}]},
        {"id": "references", "title_ko": "참고자료와 분석 조건", "blocks": [B.sources_table(R), B.parameters_table(R), B.execution_table(R), {"type": "glossary", "items": narr["glossary"]}]},
    ]
    doc = ReportDoc(request_id=R["request_id"], generated_at=dt.datetime.now().isoformat(timespec="seconds"), source="13_results.json", header=header, kpis=kp,
                    nav=[{"id": s["id"], "title_ko": s["title_ko"]} for s in sections], sections=sections, datasets={"dates": dates, "series": series},
                    assessment=interp["assessment"], sources=R["sources"], parameters=R["parameters"], warnings=warnings)
    path = dump_json(doc.model_dump(mode="json"), a.out)
    types = sorted({b["type"] for s in sections for b in s["blocks"]})
    print(f"[stage14] ok -> {path} ({path.stat().st_size / 1e6:.2f} MB)\n         chosen={chosen} ({'recommended' if is_rec else 'baseline fallback'}) sections={len(sections)} kpis={len(kp)} block_types={types}")
    print(f"         assessment={interp['assessment']}")
    for w in warnings: print("         !", w)


if __name__ == "__main__":
    main()
