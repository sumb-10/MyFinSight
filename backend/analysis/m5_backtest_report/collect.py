"""M5-04 결과 통합 (stage13 포팅). 모든 단계 산출물을 하나의 ResultsBundle 로 (값 변경 없음).

추가: evidence_index (인용 ID → 근거: 뉴스 ev*, 재무 fin:*, 계산값 calc:*), 자료 출처 = DB 테이블, 설정 스냅샷.
"""

from __future__ import annotations

from typing import Any

from backend.analysis.common.jsonio import now_iso
from backend.analysis.m2_data import descriptor as D
from backend.analysis.schemas.results import ResultsBundle
from backend.analysis.settings import AnalysisSettings
from backend.pipeline.descriptor import Descriptor

DB_SOURCES = [
    {"id": "src_prices", "name": "팀 데이터베이스 price_daily", "what": "일별 종가·수정종가·거래량 (출처 우선순위로 고른 1종목·1일 1행, 한국 종목은 거래일 환율로 USD 환산)", "url": None},
    {"id": "src_fx", "name": "팀 데이터베이스 fx_daily", "what": "원/달러 환율 USDKRW (투자금 환산·한국 종목 USD 환산)", "url": None},
    {"id": "src_valuation", "name": "팀 데이터베이스 valuation_daily", "what": "PER·PBR·ROE·배당수익률·시가총액·유통주식수 (그날까지 공시된 재무만으로 계산)", "url": None},
    {"id": "src_universe", "name": "팀 데이터베이스 index_constituent · assets", "what": "S&P 500 · NASDAQ-100 · KOSPI200 구성종목 스냅샷과 GICS 분류, 사업 설명", "url": None},
    {"id": "src_news", "name": "팀 데이터베이스 news", "what": "종목 뉴스 헤드라인 (영문·한국어), 구성일 직전 창의 기사만 근거로 사용", "url": None},
    {"id": "src_pipeline", "name": "MyFinSight 분석 계산", "what": "후보 검색·정량 스크린·비중 계산·Black-Litterman·백테스트(bt)·검증 규칙", "url": None},
    {"id": "src_llm", "name": "분석 모델 (LLM)", "what": "의도 해석·보충 질문, 테마 분류, 뉴스 근거 뷰, 선정 근거·리포트 서술 (숫자 계산은 하지 않음)", "url": None},
    {"id": "src_disclosures", "name": "팀 데이터베이스 disclosures", "what": "SEC EDGAR 8-K·10-Q·10-K, DART 공시 목록 — 사건 종류·접수일·이용 가능일(본문 없음). 이용 가능일이 구성일 이전인 것만 씀", "url": None},
]  # fmt: skip


def _calc_facts(bt: dict[str, Any], val: dict[str, Any]) -> dict[str, dict[str, Any]]:
    """리포트 문단이 인용할 수 있는 계산값 ID: calc:<metric>:<portfolio_id>."""
    out: dict[str, dict[str, Any]] = {}
    for p in [*bt["portfolios"], *bt.get("benchmarks", []), *val.get("alternatives", [])]:
        h = p["headline"]
        for k in ("cagr", "period_return", "max_drawdown", "sharpe", "excess_cagr", "final_value_usd"):
            if h.get(k) is not None:
                out[f"calc:{k}:{p['id']}"] = {"id": f"calc:{k}:{p['id']}", "kind": "calc", "title": f"{p.get('name_ko', p['id'])} {k}", "source": "backtest",
                                              "value": h[k], "unit": "usd" if k == "final_value_usd" else "ratio", "tickers": [], "data_as_of": bt["period"]["end"]}  # fmt: skip
        out[f"calc:ann_vol:{p['id']}"] = {"id": f"calc:ann_vol:{p['id']}", "kind": "calc", "title": f"{p.get('name_ko', p['id'])} ann_vol", "source": "backtest",
                                          "value": p["metrics"]["risk"]["ann_vol"], "unit": "ratio", "tickers": [], "data_as_of": bt["period"]["end"]}  # fmt: skip
    return out


def build_results(
    *,
    run_id: str,
    req: dict[str, Any],
    intent: dict[str, Any],
    cand: dict[str, Any],
    tag: dict[str, Any],
    sel: dict[str, Any],
    expl: dict[str, Any] | None,
    spec: dict[str, Any],
    mm: dict[str, Any],
    base: dict[str, Any],
    views: dict[str, Any],
    targets: dict[str, Any],
    bt: dict[str, Any],
    val: dict[str, Any],
    desc: Descriptor,
    descriptor_info: dict[str, Any],
    settings: AnalysisSettings,
    facts: list[dict[str, Any]],
    news_windows: list[dict[str, Any]],
    walkforward: dict[str, Any] | None = None,
    forward: dict[str, Any] | None = None,
    llm_usage: dict[str, Any] | None = None,
    extra_warnings: list[Any] | None = None,
) -> dict[str, Any]:
    # 경고는 단계가 ctx.warn 으로 한 번만 기록한 것(구조화)만 쓴다. 단계 산출물의 warnings 목록은 각 파일에 원문으로 남아 있어 다시 모으지 않는다.
    from backend.analysis.common.warnings import Warning as _W, merge, render

    structured = [w if isinstance(w, _W) else _W(**w) for w in (extra_warnings or [])]
    merged = merge(structured)
    warnings = [w.to_dict() for w in merged]  # 전 수준 (파일용)
    notices = [w.to_dict() for w in merged if w.level == "user"]  # 사용자에게 보이는 것 (행동 필요)
    notices_ko = [render(w) for w in merged if w.level == "user"]
    warnings_summary = [render(w) for w in merged if w.level in ("user", "info")]

    reason = {r["ticker"]: r for r in tag["tagged"]}
    rank_now = {s["ticker"]: s for s in sel["selected"]}
    rank_bt = {s["ticker"]: s for s in spec["selection"]["table"]}
    tickers = sorted(set(rank_now) | set(rank_bt), key=lambda t: (t not in rank_bt, rank_bt.get(t, rank_now.get(t, {})).get("rank", 99)))
    table = []
    for t in tickers:
        e = desc.by_ticker(t) or {}
        g = D.gics_model(e) if e else None
        r = reason.get(t, {})
        table.append({"ticker": t, "asset_id": e.get("asset_id"), "name": e.get("name", t), "market": e.get("market", "US"),
                      "sector": g.sector.name if g else "", "sub_industry": g.sub_industry.name if g else "",
                      "summary": e.get("intro", ""), "summary_source": e.get("intro_source"),
                      "themes": r.get("themes", []), "theme_confidence": r.get("confidence"), "theme_reason_ko": r.get("reason_ko"),
                      "in_selection_now": t in rank_now, "rank_now": rank_now.get(t, {}).get("rank"), "metric_now": rank_now.get(t, {}).get("metric_value"),
                      "metric_fact_id": rank_now.get(t, {}).get("metric_fact_id"),
                      "in_backtest": t in rank_bt, "rank_backtest": rank_bt.get(t, {}).get("rank"), "metric_backtest": rank_bt.get(t, {}).get("metric_value")})  # fmt: skip
    excluded = [{"ticker": r["ticker"], "name": (desc.by_ticker(r["ticker"]) or {}).get("name", r["ticker"]), "reason": r["reason"], "metric_value": r.get("metric_value")}
                for r in sel["rejected"][:8]]  # fmt: skip
    funnel = [
        {"stage": "universe", "label_ko": "투자 가능 종목 (" + " ∪ ".join(req["constraints"]["universe"]) + ")", "count": descriptor_info.get("n_stocks", len(D.tickers(desc)))},
        {"stage": "candidates", "label_ko": "테마 관련 후보 (GICS·키워드·예시 종목 검색)", "count": cand["stats"]["n_candidates"]},
        {"stage": "theme_passed", "label_ko": f"테마 해당 판정 (분석 모델, 신뢰도 ≥ {tag['min_confidence']})", "count": len(tag["passed_tickers"])},
        {"stage": "with_metric", "label_ko": f"선정 지표({sel['summary']['metric']}) 계산 가능", "count": sel["summary"]["n_with_metric"]},
        {"stage": "selected_now", "label_ko": f"최종 선정 ({sel['summary']['as_of']}, 섹터 분산 적용)", "count": sel["summary"]["n_selected"]},
        {"stage": "selected_backtest", "label_ko": f"백테스트용 재선정 ({spec['period']['as_of']})", "count": len(spec["selection"]["tickers"])},
    ]  # fmt: skip
    selection = {"funnel": funnel, "metric": sel["summary"]["metric"], "direction": sel["summary"]["direction"], "candidates_summary": cand["stats"],
                 "tagging_summary": {"n_tagged": len(tag["tagged"]), "n_passed": len(tag["passed_tickers"]), "n_excluded_by_theme": len(tag["excluded_by_theme"]),
                                     "min_confidence": tag["min_confidence"]},
                 "as_of_now": {"as_of": sel["summary"]["as_of"], "selected": sel["selected"], "rejected_examples": excluded, "summary": sel["summary"],
                               "warnings": sel["warnings"], "infeasibility": sel.get("infeasibility"), "sector_overflow": sel["summary"].get("sector_overflow")},
                 "explained": expl,
                 "backtest_as_of": {"as_of": spec["period"]["as_of"], "source": spec["selection"]["source"], "table": spec["selection"]["table"],
                                    "diff_vs_original": spec["selection"]["diff_vs_original"], "infeasibility": spec["selection"].get("infeasibility"),
                                    "sector_overflow": spec["selection"].get("sector_overflow")},
                 "table": table}  # fmt: skip
    mm_small = {k: mm[k] for k in ["as_of", "lookback", "tickers", "ann_vol", "cap_weights", "delta", "delta_source", "delta_market", "delta_multiplier",
                                    "delta_dd_multiplier", "delta_tolerance", "delta_window", "tau", "baseline_id", "implied_returns", "shrinkage", "notes"] if k in mm}  # fmt: skip
    portfolio = {"backtest_spec": {k: spec[k] for k in ["period", "capital", "rebalance_rule", "benchmark", "extra_benchmarks", "execution_rule"] if k in spec},
                 "market_model": mm_small, "baselines": base, "views": views, "targets": targets,
                 "news_windows": news_windows, "walkforward": walkforward, "forward": forward}  # fmt: skip

    fx = req["derived"]["fx_rate"]
    fx_bt = spec["capital"].get("fx_rate") or fx
    by_pf = {}
    for p in [*bt.get("benchmarks", [bt["benchmark"]]), *bt["portfolios"], *val.get("alternatives", [])]:
        m = p["money"]
        by_pf[p["id"]] = {"final_value_krw": round(m["final_value_usd"] * fx), "net_invested_krw": round(m["net_invested_usd"] * fx),
                          "profit_krw": round(m["profit_usd"] * fx), "contributions_krw": round(m["contributions_usd"] * fx),
                          "final_value_krw_at_backtest_fx": round(m["final_value_usd"] * fx_bt)}  # fmt: skip
    money_krw = {"fx_rate": fx, "fx_date": str(req["derived"]["fx_date"]), "fx_source": req["derived"].get("fx_source"), "direction": f"1 USD = {fx:,.2f} KRW",
                 "backtest_fx": {"fx_rate": fx_bt, "fx_date": str(spec["capital"].get("fx_date")), "fx_source": spec["capital"].get("fx_source"),
                                 "direction": f"1 USD = {fx_bt:,.2f} KRW",
                                 "note": "백테스트 초기자본·적립은 구성일 환율로 환산; 평가금액 원화 표시는 분석 기준일 환율 기준(괄호: 구성일 환율 기준)"},
                 "initial_amount_krw": req["capital"]["initial_amount"] if req["capital"]["currency"] == "KRW" else None,
                 "monthly_contribution_krw": req["capital"].get("monthly_contribution") if req["capital"]["currency"] == "KRW" else None, "by_portfolio": by_pf}  # fmt: skip

    # 인용 색인: 뉴스(ev*) + 재무·가격 지표(fin:*) + 계산값(calc:*)
    evidence_index: dict[str, dict[str, Any]] = {}
    for w in news_windows:
        for r in w.get("records", []):
            evidence_index[r["evidence_id"]] = {"id": r["evidence_id"], "kind": "news", "title": r["title"], "source": r.get("publisher") or r.get("source", ""),
                                                "url": r.get("url"), "published_at": r.get("published_at"), "tickers": [r["ticker"]], "language": r.get("language"),
                                                "window_as_of": w.get("as_of")}  # fmt: skip
    for w in news_windows:
        for r in w.get("disclosures", []) or []:
            evidence_index[r["evidence_id"]] = {"id": r["evidence_id"], "kind": "disclosure", "title": r["title"], "source": r.get("publisher") or r.get("source", ""),
                                                "url": r.get("url"), "published_at": r.get("filed_at") or r.get("published_at"), "data_as_of": r.get("available_on"),
                                                "tickers": [r["ticker"]], "language": r.get("language"), "event_type": r.get("event_type"), "event_label_ko": r.get("event_label_ko"),
                                                "form": r.get("form"), "items": r.get("items"), "filed_at": r.get("filed_at"), "available_on": r.get("available_on"),
                                                "window_as_of": w.get("as_of")}  # fmt: skip
    for f in facts:
        evidence_index[f["id"]] = {"id": f["id"], "kind": "financial", "title": f"{f['ticker']} {f['metric']}", "source": f["source"], "value": f["value"],
                                   "unit": f["unit"], "data_as_of": f["as_of"], "tickers": [f["ticker"]]}  # fmt: skip
    evidence_index.update(_calc_facts(bt, val))

    snap = settings.snapshot()
    parameters = {"portfolio": snap["portfolio"], "backtest": snap["backtest"], "news": snap["news"], "disclosures": snap.get("disclosures"), "llm": {"model": snap["llm"]["model"], "provider": snap["llm"]["provider"],
                  "mode": snap["llm"]["mode"]}, "market": snap["market"], "descriptor": descriptor_info, "execution_rule": spec.get("execution_rule")}  # fmt: skip
    bundle = ResultsBundle(request_id=req["request_id"], run_id=run_id, generated_at=now_iso(), pipeline_version=settings.pipeline_version,
                           request=req, intent=intent, selection=selection, portfolio=portfolio, backtest=bt, validation=val, money_krw=money_krw,
                           evidence_index=evidence_index, data_quality=bt.get("data_quality"), llm_usage=llm_usage or {"available": False},
                           sources=DB_SOURCES, parameters=parameters, warnings=warnings, warnings_summary=warnings_summary, notices=notices, notices_ko=notices_ko)  # fmt: skip
    return bundle.model_dump(mode="json")
