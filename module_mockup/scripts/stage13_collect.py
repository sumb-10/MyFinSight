"""
Stage 13: consolidate every stage output into one results file (no LLM, no value changes).

in : output/01..12 json, output/llm_usage.jsonl (optional), config modules
out: output/13_results.json   -> the only input of the report stage (14) and of future DB storage / comparisons
"""
import argparse, datetime as dt, json
from collections import defaultdict
from common import OUTPUT, load_json, dump_json
from descriptor import load_descriptor
import portfolio_config as PC, backtest_config as BC, llm_config as LC
from schemas import ResultsBundle

PIPELINE_VERSION = "mockup-2026.10"
SOURCES = [
    {"id": "src_prices", "name": "Yahoo Finance (yfinance)", "what": "일별 주가·수정주가·거래량 (2011-10 ~ 2026-10), 벤치마크 SPY", "url": "https://finance.yahoo.com"},
    {"id": "src_company", "name": "Yahoo Finance (yfinance) 기업 개요", "what": "회사 한 줄 소개(영문 사업 설명 첫 문장), 발행주식수, 재무제표 스냅샷", "url": "https://finance.yahoo.com"},
    {"id": "src_universe", "name": "Wikipedia", "what": "S&P 500 · NASDAQ-100 구성 종목과 GICS 세부산업", "url": "https://en.wikipedia.org/wiki/List_of_S%26P_500_companies"},
    {"id": "src_gics", "name": "Wikipedia GICS", "what": "GICS 11 섹터 / 25 산업그룹 / 74 산업 / 163 세부산업 분류표", "url": "https://en.wikipedia.org/wiki/Global_Industry_Classification_Standard"},
    {"id": "src_fx", "name": "Yahoo Finance KRW=X", "what": "원/달러 환율 (투자금 환산 기준일 종가)", "url": "https://finance.yahoo.com/quote/KRW=X"},
    {"id": "src_pipeline", "name": "MyFinSight 파이프라인 계산", "what": "후보 검색·정량 스크린·비중 계산·Black-Litterman·백테스트(bt)·검증 규칙", "url": None},
    {"id": "src_llm", "name": "분석 모델 (gpt-6-luna)", "what": "의도 해석, 테마 분류, 시나리오 뷰(뉴스 미연결 가정), 리포트 서술", "url": None},
]


def opt(path):
    return load_json(path) if path.exists() else None


def llm_usage_summary():
    p = OUTPUT / "llm_usage.jsonl"
    if not p.exists():
        return {"available": False}
    rows = [json.loads(l) for l in open(p, encoding="utf-8") if l.strip()]
    per = defaultdict(lambda: {"calls": 0, "prompt_tokens": 0, "completion_tokens": 0, "cost_usd": 0.0})
    for r in rows:
        s = per[r["stage"]]; s["calls"] += 1; s["prompt_tokens"] += r["prompt_tokens"]; s["completion_tokens"] += r["completion_tokens"]; s["cost_usd"] += r["cost_usd"] or 0
    for s in per.values(): s["cost_usd"] = round(s["cost_usd"], 6)
    return {"available": True, "model": rows[-1]["model"], "by_stage": dict(per), "total_cost_usd": round(sum(s["cost_usd"] for s in per.values()), 6),
            "note": "누적 로그 기준(여러 실행 포함)"}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default=str(OUTPUT / "13_results.json"))
    a = ap.parse_args()
    req, intent = load_json(OUTPUT / "01_request.json"), load_json(OUTPUT / "02_intent.json")
    cand, tag, sel = load_json(OUTPUT / "03_candidates.json"), load_json(OUTPUT / "04_tagging.json"), load_json(OUTPUT / "05_selection.json")
    expl = opt(OUTPUT / "06_selection_explained.json")
    spec, mm, base = load_json(OUTPUT / "07_backtest_spec.json"), load_json(OUTPUT / "08_market_model.json"), load_json(OUTPUT / "08_baseline_portfolios.json")
    views, targets = load_json(OUTPUT / "09_views.json"), load_json(OUTPUT / "10_target_portfolios.json")
    bt, val = load_json(OUTPUT / "11_backtest_results.json"), load_json(OUTPUT / "12_validation.json")
    news_ev, wf, fwd = opt(OUTPUT / "09a_news_evidence.json"), opt(OUTPUT / "10w_target_paths.json"), opt(OUTPUT / "10f_forward_portfolios.json")
    same = lambda x: x if x and x.get("request_id") == req["request_id"] else None
    news_ev, wf, fwd = same(news_ev), same(wf), same(fwd)
    desc = load_descriptor()
    warnings = []
    for name, obj in [("01", req), ("02", intent), ("03", cand), ("04", tag), ("05", sel), ("07", spec), ("09", views), ("10", targets), ("11", bt), ("12", val)]:
        for w in obj.get("warnings", []) or []:
            warnings.append({"stage": name, "message": w})

    # ── selection table: descriptor facts + tagging reason + metric/rank at both dates ──
    reason = {r["ticker"]: r for r in tag["tagged"]}
    rank26 = {s["ticker"]: s for s in sel["selected"]}
    rank_bt = {s["ticker"]: s for s in spec["selection"]["table"]}
    tickers = sorted(set(rank26) | set(rank_bt), key=lambda t: (t not in rank_bt, rank_bt.get(t, rank26.get(t, {})).get("rank", 99)))
    table = []
    for t in tickers:
        c = desc["companies"][t]; r = reason.get(t, {})
        table.append({"ticker": t, "name": c["name"], "sector": c["gics"]["sector"]["name"], "sub_industry": c["gics"]["sub_industry"]["name"],
                      "summary": c["company_summary"], "summary_source": c["sources"]["summary"],
                      "themes": r.get("themes", []), "theme_confidence": r.get("confidence"), "theme_reason_ko": r.get("reason_ko"),
                      "in_selection_2026": t in rank26, "rank_2026": rank26.get(t, {}).get("rank"), "metric_2026": rank26.get(t, {}).get("metric_value"),
                      "in_backtest": t in rank_bt, "rank_backtest": rank_bt.get(t, {}).get("rank"), "metric_backtest": rank_bt.get(t, {}).get("metric_value")})
    excluded = [{"ticker": r["ticker"], "name": desc["companies"][r["ticker"]]["name"], "reason": r["reason"], "metric_value": r.get("metric_value")}
                for r in sel["rejected"][:8]]
    funnel = [
        {"stage": "universe", "label_ko": "투자 가능 종목 (S&P 500 ∪ NASDAQ-100)", "count": desc["meta"]["n_companies"]},
        {"stage": "candidates", "label_ko": "테마 관련 후보 (GICS·키워드·예시 종목 검색)", "count": cand["stats"]["n_candidates"]},
        {"stage": "theme_passed", "label_ko": f"테마 해당 판정 (분석 모델, 신뢰도 ≥ {tag['min_confidence']})", "count": len(tag["passed_tickers"])},
        {"stage": "with_metric", "label_ko": f"선정 지표({sel['summary']['metric']}) 계산 가능", "count": sel["summary"]["n_with_metric"]},
        {"stage": "selected_2026", "label_ko": f"최종 선정 ({sel['summary']['as_of']}, 섹터 상한 적용)", "count": sel["summary"]["n_selected"]},
        {"stage": "selected_backtest", "label_ko": f"백테스트용 재선정 ({spec['period']['as_of']})", "count": len(spec["selection"]["tickers"])},
    ]
    selection = {"funnel": funnel, "metric": sel["summary"]["metric"], "direction": sel["summary"]["direction"],
                 "candidates_summary": cand["stats"], "tagging_summary": {"n_tagged": len(tag["tagged"]), "n_passed": len(tag["passed_tickers"]),
                 "n_excluded_by_theme": len(tag["excluded_by_theme"]), "min_confidence": tag["min_confidence"]},
                 "as_of_2026": {"as_of": sel["summary"]["as_of"], "selected": sel["selected"], "rejected_examples": excluded, "summary": sel["summary"], "warnings": sel["warnings"],
                                "infeasibility": sel.get("infeasibility"), "sector_overflow": sel["summary"].get("sector_overflow")},
                 "explained": expl, "backtest_as_of": {"as_of": spec["period"]["as_of"], "source": spec["selection"]["source"], "table": spec["selection"]["table"],
                 "diff_vs_original": spec["selection"]["diff_vs_original"], "infeasibility": spec["selection"].get("infeasibility"),
                 "sector_overflow": spec["selection"].get("sector_overflow")}, "table": table}

    # ── portfolio block (market model without the full covariance) ──
    mm_small = {k: mm[k] for k in ["as_of", "lookback", "tickers", "ann_vol", "cap_weights", "delta", "tau", "baseline_id", "implied_returns", "shrinkage", "notes"]}
    portfolio = {"backtest_spec": {k: spec[k] for k in ["period", "capital", "rebalance_rule", "benchmark"]}, "market_model": mm_small,
                 "baselines": base, "views": views, "targets": targets,
                 "news_evidence": news_ev, "walkforward": wf, "forward": fwd}

    # ── KRW conversion ──
    fx = req["derived"]["fx_rate"]                       # request-date FX (what the user saw when asking)
    fx_bt = spec["capital"].get("fx_rate") or fx          # backtest-start FX (what the backtest capital used)
    by_pf = {}
    for p in [*bt.get("benchmarks", [bt["benchmark"]]), *bt["portfolios"], *val.get("alternatives", [])]:
        m = p["money"]
        by_pf[p["id"]] = {"final_value_krw": round(m["final_value_usd"] * fx), "net_invested_krw": round(m["net_invested_usd"] * fx),
                          "profit_krw": round(m["profit_usd"] * fx), "contributions_krw": round(m["contributions_usd"] * fx),
                          "final_value_krw_at_backtest_fx": round(m["final_value_usd"] * fx_bt)}
    money_krw = {"fx_rate": fx, "fx_date": req["derived"]["fx_date"], "fx_source": req["derived"].get("fx_source"), "direction": f"1 USD = {fx:,.2f} KRW",
                 "backtest_fx": {"fx_rate": fx_bt, "fx_date": spec["capital"].get("fx_date"), "fx_source": spec["capital"].get("fx_source"), "direction": f"1 USD = {fx_bt:,.2f} KRW",
                                 "note": "백테스트 초기자본·적립은 구성일 환율로 환산; 평가금액 원화 표시는 요청 시점 환율 기준(괄호: 구성일 환율 기준)"},
                 "initial_amount_krw": req["capital"]["initial_amount"], "monthly_contribution_krw": req["capital"]["monthly_contribution"], "by_portfolio": by_pf}

    parameters = {"portfolio": {k: getattr(PC, k) for k in ["LOOKBACK_DAYS", "SHRINKAGE", "TAU", "RISK_AVERSION", "OMEGA_METHOD", "CONFIDENCE_FLOOR", "ABS_RETURN_RANGE", "REL_RETURN_RANGE", "TEMPLATES"]},
                  "backtest": {k: getattr(BC, k) for k in ["COMMISSION_BPS", "INTEGER_POSITIONS", "RISK_FREE_RATE", "TRADING_DAYS", "DRIFT_TOLERANCE", "CHECKPOINT_FREQ", "VOL_BANDS"]},
                  "llm": {"model": LC.MODEL, "provider": LC.PROVIDER, "reasoning_effort": LC.REASONING_EFFORT}}

    for name, obj in [("09a", news_ev), ("10w", wf), ("10f", fwd)]:
        for w in (obj or {}).get("warnings", []) or []:
            warnings.append({"stage": name, "message": w})
    bundle = ResultsBundle(request_id=req["request_id"], generated_at=dt.datetime.now().isoformat(timespec="seconds"), pipeline_version=PIPELINE_VERSION,
                           request=req, intent=intent, selection=selection, portfolio=portfolio, backtest=bt, validation=val, money_krw=money_krw,
                           llm_usage=llm_usage_summary(), sources=SOURCES, parameters=parameters, warnings=warnings)
    path = dump_json(bundle.model_dump(mode="json"), a.out)
    print(f"[stage13] ok -> {path} ({path.stat().st_size / 1e6:.2f} MB) news={'yes' if news_ev else 'no'} walkforward={'yes' if wf else 'no'} forward={'yes' if fwd else 'no'}\n         selection table={len(table)} funnel={[f['count'] for f in funnel]} "
          f"portfolios={len(bt['portfolios'])} series={len(bt['series_dates'])} validation={val['summary']} warnings={len(warnings)} fx={money_krw['direction']}")


if __name__ == "__main__":
    main()
