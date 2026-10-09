"""Build the data-driven blocks of 14_report.json from 13_results.json (no LLM here)."""
import math

NAMES = {"equal_weight": "동일비중", "market_cap": "시가총액비중", "inverse_volatility": "역변동성비중", "min_variance": "최소분산"}


def pf_label(p):
    return p.get("title_ko") and f"시나리오: {p['title_ko']}" or NAMES.get(p["id"], p.get("name_ko", p["id"]))


def chosen_portfolio_id(R):
    rec = R["validation"].get("recommended")
    return (rec["id"] if rec else R["portfolio"]["targets"]["baseline"]["id"]), bool(rec)


def kpis(R, chosen):
    p = next(x for x in R["backtest"]["portfolios"] if x["id"] == chosen)
    h, krw = p["headline"], R["money_krw"]["by_portfolio"][chosen]
    bench = R["backtest"]["benchmark"]["id"].replace("benchmark_", "")
    return [
        {"id": "final_value", "label_ko": "최종 평가금액", "value": h["final_value_usd"], "format": "usd", "note_ko": f"약 {krw['final_value_krw']:,.0f}원 · 투입 원금 {p['money']['net_invested_usd']:,.0f} USD"},
        {"id": "cagr", "label_ko": "연평균 수익률 (CAGR)", "value": h["cagr"], "format": "pct", "note_ko": "백테스트 기간 기준 연 환산"},
        {"id": "excess", "label_ko": f"비교지수({bench}) 대비", "value": h["excess_cagr"], "format": "pp", "note_ko": "같은 기간 CAGR 차이"},
        {"id": "mdd", "label_ko": "최대낙폭 (MDD)", "value": h["max_drawdown"], "format": "pct", "note_ko": f"손실 감내 수준 {R['intent']['risk_params']['effective_max_drawdown']:.0%}"},
        {"id": "sharpe", "label_ko": "Sharpe 비율", "value": h["sharpe"], "format": "ratio", "note_ko": f"무위험수익률 {R['parameters']['backtest']['RISK_FREE_RATE']:.0%} 가정"},
        {"id": "view_hit", "label_ko": "시나리오 뷰 적중률", "value": h["view_hit_ratio"], "format": "pct", "note_ko": "Black-Litterman 뷰의 방향이 맞은 비율" if h["view_hit_ratio"] is not None else "기준 포트폴리오에는 뷰가 없습니다"},
    ]


def table(title, columns, rows, note=None):
    b = {"type": "table", "title_ko": title, "columns": [{"key": k, "label_ko": l, "format": f} for k, l, f in columns], "rows": rows}
    if note: b["note_ko"] = note
    return b


def request_table(R):
    q, d, c, h, r = R["request"], R["request"]["derived"], R["request"]["capital"], R["request"]["horizon"], R["request"]["risk"]
    rows = [{"k": "투자금", "v": f"{c['initial_amount']:,.0f}원 → {d['initial_amount_usd']:,.2f} USD (환율 {R['money_krw']['direction']}, {d['fx_date']})"},
            {"k": "월 적립", "v": f"{c['monthly_contribution']:,.0f}원 (매월 {c['contribution_day']}일) → {d['monthly_contribution_usd']:,.2f} USD"},
            {"k": "투자기간", "v": f"{h['target_years']}년 (시작 희망일 {h['start_date']})"},
            {"k": "투자성향", "v": f"{r['risk_tolerance']} · 손실 감내 수준 {r['max_drawdown_tolerance']:.0%} · 손실 시 {r['loss_reaction']}"},
            {"k": "목표 수익률", "v": f"연 {r['target_annual_return']:.0%} · 비교지수 {r['benchmark']}"},
            {"k": "투자 아이디어", "v": q["natural_language"]["idea"]}]
    return table("요청 내용", [("k", "항목", "text"), ("v", "내용", "text")], rows)


def themes_table(R):
    rows = [{"label": t["label_ko"], "desc": t["description_ko"], "codes": ", ".join(t["gics_codes"]), "kw": ", ".join(t["keywords"][:6])} for t in R["intent"]["interpretation"]["themes"]]
    return table("추출한 테마", [("label", "테마", "text"), ("desc", "어떤 기업이 해당하는가", "text"), ("codes", "GICS 코드", "text"), ("kw", "검색 키워드", "text")], rows)


def constraints_table(R):
    c = R["request"]["constraints"]; rb = R["request"]["derived"]["rebalance_rule"]
    rows = [{"k": "종목 수", "v": f"목표 {c['num_holdings']['target']}개 (허용 {c['num_holdings']['min']}~{c['num_holdings']['max']})"},
            {"k": "종목당 상한", "v": f"{c['max_weight_per_stock']:.0%}"}, {"k": "섹터당 상한", "v": f"{c['max_weight_per_sector']:.0%}"},
            {"k": "리밸런싱", "v": rb["description_ko"]}, {"k": "제외", "v": ", ".join(c["exclude_themes"] + c["exclude_sectors"] + c["exclude_tickers"]) or "없음"},
            {"k": "레버리지·공매도", "v": "모두 불허" if not c["allow_leverage"] and not c["allow_short"] else "일부 허용"},
            {"k": "최소 시가총액·거래대금", "v": f"{c['min_market_cap_usd'] / 1e9:.0f}B USD · 일 {c['min_avg_daily_volume_usd'] / 1e6:.0f}M USD"}]
    return table("지켜야 하는 조건 (하드 제약)", [("k", "항목", "text"), ("v", "값", "text")], rows)


def soft_table(R):
    rp, nt = R["intent"]["risk_params"], R["intent"]["news_tilt"]
    rows = [{"k": "변동성 선호", "v": rp["volatility_preference"]}, {"k": "허용 최대낙폭(검증 기준)", "v": f"{rp['effective_max_drawdown']:.0%}"},
            {"k": "해석 메모", "v": rp["notes_ko"]}, {"k": "시나리오 뷰 반영 한도", "v": f"종목당 최대 {nt['max_tilt_per_stock']:.0%}p, 뷰 신뢰도 상한 {nt['max_view_confidence']}"}]
    return table("성향 해석 (소프트 조건)", [("k", "항목", "text"), ("v", "해석", "text")], rows)


def funnel(R):
    return {"type": "funnel", "items": [{"label_ko": f["label_ko"], "count": f["count"]} for f in R["selection"]["funnel"]]}


def selection_table(R):
    rows = [{"ticker": t["ticker"], "name": t["name"], "sector": t["sector"], "summary": t["summary"], "reason": t["theme_reason_ko"] or "",
             "conf": t["theme_confidence"], "rank_bt": t["rank_backtest"], "metric_bt": t["metric_backtest"], "rank_26": t["rank_2026"], "metric_26": t["metric_2026"]}
            for t in R["selection"]["table"]]
    m = R["selection"]["metric"]
    return table("선정 종목 (백테스트 기준일 순위 → 2026-04 순위)",
                 [("ticker", "티커", "text"), ("name", "회사", "text"), ("sector", "섹터", "text"), ("summary", "한 줄 소개", "text"),
                  ("reason", "테마 판정 사유", "text"), ("conf", "신뢰도", "num"), ("rank_bt", f"순위({R['selection']['backtest_as_of']['as_of']})", "int"),
                  ("metric_bt", f"{m}", "pct"), ("rank_26", f"순위({R['selection']['as_of_2026']['as_of']})", "int"), ("metric_26", f"{m}", "pct")],
                 rows, note="순위가 비어 있으면 그 기준일에는 선정되지 않은 종목입니다.")


def excluded_table(R):
    rows = [{"ticker": r["ticker"], "name": r["name"], "reason": r["reason"], "metric": r["metric_value"]} for r in R["selection"]["as_of_2026"]["rejected_examples"]]
    return table("테마에는 해당하지만 최종 선정에서 빠진 예 (2026-04 기준)", [("ticker", "티커", "text"), ("name", "회사", "text"), ("reason", "제외 이유", "text"), ("metric", "지표값", "pct")], rows)


def diff_table(R):
    d = R["selection"]["backtest_as_of"]["diff_vs_original"]
    rows = [{"k": "백테스트용 재선정에서 추가된 종목", "v": ", ".join(d["added"]) or "없음"}, {"k": "빠진 종목", "v": ", ".join(d["removed"]) or "없음"}]
    return table("2026-04 선정 목록과 백테스트 기준일 재선정 목록의 차이", [("k", "구분", "text"), ("v", "종목", "text")], rows,
                 note="백테스트는 기준일 당시에 알 수 있던 정보만으로 같은 규칙을 다시 적용합니다. 그래서 목록이 달라질 수 있습니다.")


def baseline_table(R):
    base = next(p for p in R["portfolio"]["baselines"]["portfolios"] if p["id"] == R["portfolio"]["baselines"]["chosen_baseline"])
    n = len(base["weights"]); sec = {t["ticker"]: t["sector"] for t in R["selection"]["table"]}
    rows = [{"ticker": t, "sector": sec.get(t, ""), "raw": 1 / n, "final": w} for t, w in base["weights"].items()]
    return table("기준 포트폴리오: 단순 1/N 비중 → 상한 적용 후 비중", [("ticker", "티커", "text"), ("sector", "섹터", "text"), ("raw", "1/N", "pct1"), ("final", "최종 비중", "pct1")], rows,
                 note="섹터당 40% 상한 때문에 정보기술 종목 비중이 줄고, 그만큼이 다른 섹터 종목에 나눠졌습니다. " + ", ".join(base["constraints_applied"]))


def templates_table(R):
    rows = [{"name": NAMES.get(p["id"], p["id"]), "rule": p["rule_ko"], "vol": p["ex_ante"]["vol"], "neff": p["ex_ante"]["effective_n"], "top": max(p["weights"].values())}
            for p in R["portfolio"]["baselines"]["portfolios"]]
    return table("비중 규칙 4가지 비교 (구성일 기준 추정치)", [("name", "규칙", "text"), ("rule", "설명", "text"), ("vol", "예상 변동성", "pct"), ("neff", "유효 종목 수", "num"), ("top", "최대 비중", "pct1")], rows)


def donut(title, weights, note=None):
    items = [{"label": t, "value": w} for t, w in sorted(weights.items(), key=lambda x: -x[1]) if w > 1e-6]
    b = {"type": "donut", "title_ko": title, "items": items}
    if note: b["note_ko"] = note
    return b


def scenario_cards(R):
    items = []
    bt = {p["id"]: p for p in R["backtest"]["portfolios"]}
    for p in R["portfolio"]["targets"]["portfolios"]:
        d = p["delta_vs_baseline"]; top = sorted(d.items(), key=lambda x: -abs(x[1]))[:3]
        views = "\n".join("· " + v["summary_ko"] for v in p["views_applied"])
        items.append({"title_ko": p["title_ko"], "text_ko": p["portfolio_view"].split("\n")[0] + "\n" + views,
                      "meta": [{"label_ko": "베이스라인 대비 주요 변화", "value": ", ".join(f"{t} {x:+.1%}" for t, x in top)},
                               {"label_ko": "뷰 적중률(백테스트)", "value": f"{bt[p['id']]['headline']['view_hit_ratio']:.0%}" if bt[p["id"]]["headline"]["view_hit_ratio"] is not None else "-"},
                               {"label_ko": "예상 수익·변동성", "value": f"{p['ex_ante']['exp_return']:.1%} / {p['ex_ante']['vol']:.1%}"}]})
    return {"type": "cards", "title_ko": "시나리오별 타겟 포트폴리오", "items": items}


def allocation_table(R, chosen):
    p = next(x for x in R["backtest"]["portfolios"] if x["id"] == chosen)
    init = R["portfolio"]["backtest_spec"]["capital"]["initial_amount_usd"]; fx = R["money_krw"]["fx_rate"]
    sec = {t["ticker"]: t["sector"] for t in R["selection"]["table"]}; names = {t["ticker"]: t["name"] for t in R["selection"]["table"]}
    rows = [{"ticker": t, "name": names.get(t, t), "sector": sec.get(t, ""), "w": w, "usd": init * w, "krw": init * w * fx} for t, w in sorted(p["target_weights"].items(), key=lambda x: -x[1])]
    return table(f"배분 금액 ({pf_label(p)}, 초기 투자금 {init:,.0f} USD 기준)", [("ticker", "티커", "text"), ("name", "회사", "text"), ("sector", "섹터", "text"), ("w", "비중", "pct1"), ("usd", "USD", "usd"), ("krw", "원화", "krw")], rows)


def delta_bar(R, pid):
    p = next(x for x in R["portfolio"]["targets"]["portfolios"] if x["id"] == pid)
    return {"type": "bar", "title_ko": f"{p['title_ko']}: 베이스라인 대비 비중 변화", "items": [{"label": t, "value": v} for t, v in sorted(p["delta_vs_baseline"].items(), key=lambda x: -x[1])], "format": "pp"}


def assumptions_callout(R):
    e, s = R["backtest"]["engine"], R["portfolio"]["backtest_spec"]
    txt = (f"기간 {s['period']['start']} ~ {s['period']['end']} ({R['backtest']['period']['trading_days']}거래일). 초기 투자금 {s['capital']['initial_amount_usd']:,.0f} USD, "
           f"매월 {e['contribution_usd']:,.0f} USD 적립 {e['n_contributions']}회. {s['rebalance_rule']['description_ko']}. 거래비용 거래대금의 {e['commission_bps'] / 100:.2f}%, "
           f"배당 재투자, 소수 주식 허용, 무위험수익률 연 {e['risk_free_rate']:.0%}. 과거 성과는 미래 성과를 보장하지 않습니다.")
    return {"type": "callout", "tone": "info", "title_ko": "백테스트 가정", "text_ko": txt}


def all_blocks(R):
    """portfolios + every benchmark + validation alternatives (same block shape)."""
    return [*R["backtest"]["portfolios"], *R["backtest"].get("benchmarks", [R["backtest"]["benchmark"]]), *R["validation"].get("alternatives", [])]


def comparison_table(R):
    rows = []
    status = {r["id"]: r["status"] for r in R["validation"]["results"]}
    status.update({a["id"]: a["status"] for a in R["validation"].get("alternatives", [])})
    for p in all_blocks(R):
        h, m = p["headline"], p["metrics"]
        rows.append({"name": pf_label(p) if p["kind"] not in ("benchmark", "alternative") else p["name_ko"], "kind": {"black_litterman": "시나리오", "template": "규칙", "benchmark": "비교지수", "alternative": "대안"}[p["kind"]],
                     "cagr": h["cagr"], "vol": m["risk"]["ann_vol"], "sharpe": h["sharpe"], "mdd": h["max_drawdown"], "excess": h["excess_cagr"],
                     "final": h["final_value_usd"], "irr": p["money"]["irr_annual"], "status": {"pass": "통과", "warn": "주의", "fail": "미통과"}.get(status.get(p["id"]), "-")})
    return table("포트폴리오 비교 (같은 기간·같은 적립)", [("name", "포트폴리오", "text"), ("kind", "종류", "text"), ("cagr", "CAGR", "pct"), ("vol", "변동성", "pct"), ("sharpe", "Sharpe", "ratio"),
                 ("mdd", "최대낙폭", "pct"), ("excess", "비교지수 대비", "pp"), ("final", "최종 평가금액", "usd"), ("irr", "적립 기준 연수익(XIRR)", "pct"), ("status", "검증", "text")], rows,
                 note="비교지수 대비는 사용자가 지정한 비교지수(" + R["portfolio"]["backtest_spec"]["benchmark"] + ") 기준입니다. 대안은 검증 단계가 만든 현금 혼합 변형입니다.")


def infeasibility_callout(R):
    bt_sel, sel26 = R["selection"]["backtest_as_of"], R["selection"]["as_of_2026"]
    inf = bt_sel.get("infeasibility") or sel26.get("infeasibility")
    if inf:
        txt = (f"선정된 종목의 섹터 구성으로는 종목당 {inf['stock_cap']:.0%}·섹터당 {inf['sector_cap']:.0%} 상한 안에서 투자금 전체를 배분할 수 없습니다(배분 가능 {inf['capacity']:.0%}). "
               f"섹터별 종목 수: " + ", ".join(f"{k} {v}" for k, v in inf["sector_counts"].items()) + ". 선택지: " + " / ".join(inf["options_ko"]))
        return {"type": "callout", "tone": "caution", "title_ko": "상한 안에서 배분할 수 없는 구성", "text_ko": txt}
    ov = bt_sel.get("sector_overflow") or sel26.get("sector_overflow")
    if ov:
        return {"type": "callout", "tone": "info", "title_ko": "섹터 상한이 비중을 누른 부분", "text_ko": ov["note_ko"] + f" (해당 종목: {', '.join(ov['tickers'])})"}
    return None


def alternatives_cards(R):
    alts = R["validation"].get("alternatives", [])
    if not alts: return None
    items = []
    for a in alts:
        h = a["headline"]
        items.append({"title_ko": a["name_ko"], "text_ko": a["reason_ko"],
                      "meta": [{"label_ko": "검증", "value": {"pass": "통과", "warn": "주의", "fail": "미통과"}[a["status"]] + (" (" + ", ".join(c["rule"] for c in a["checks"] if c["status"] != "pass") + ")" if a["status"] != "pass" else "")},
                               {"label_ko": "CAGR / 최대낙폭 / Sharpe", "value": f"{h['cagr']:+.1%} / {h['max_drawdown']:.1%} / {h['sharpe']:.2f}"},
                               {"label_ko": "최종 평가금액", "value": f"{h['final_value_usd']:,.0f} USD"}]})
    return {"type": "cards", "title_ko": "검토 가능한 대안 (검증 단계가 계산)", "items": items}


def yearly_table(R, chosen):
    p = next(x for x in R["backtest"]["portfolios"] if x["id"] == chosen); b = R["backtest"]["benchmark"]
    years = sorted(p["yearly_returns"])
    rows = [{"name": pf_label(p), **{y: p["yearly_returns"][y] for y in years}}, {"name": b["name_ko"], **{y: b["yearly_returns"].get(y) for y in years}}]
    return table("연도별 수익률", [("name", "구분", "text")] + [(y, y, "pct") for y in years], rows, note="첫해와 마지막 해는 일부 기간입니다.")


def monthly_table(R, chosen):
    p = next(x for x in R["backtest"]["portfolios"] if x["id"] == chosen)
    by = {}
    for m in p["monthly_returns"]: by.setdefault(m["year"], {})[m["month"]] = m["return"]
    rows = [{"year": str(y), **{f"m{k}": by[y].get(k) for k in range(1, 13)}} for y in sorted(by)]
    return table("월별 수익률", [("year", "연도", "text")] + [(f"m{k}", f"{k}월", "pct") for k in range(1, 13)], rows)


def contribution_bar(R, chosen):
    p = next(x for x in R["backtest"]["portfolios"] if x["id"] == chosen)
    return {"type": "bar", "title_ko": "종목별 수익 기여 (기간 전체)", "items": [{"label": t, "value": v} for t, v in sorted(p["ticker_contribution"].items(), key=lambda x: -x[1])], "format": "pp"}


def checkpoints_block(R, chosen):
    p = next(x for x in R["backtest"]["portfolios"] if x["id"] == chosen)
    items = []
    for cp in p["checkpoints"]:
        items.append({"seq": cp["seq"], "date": cp["date"], "kind": cp["kind"], "n_trading_days_to_date": cp["n_trading_days_to_date"],
                      "weights_before": cp["weights"]["before"], "weights_after": cp["weights"]["after"], "weights_target": cp["weights"]["target"],
                      "holdings": cp["holdings"], "since_last": cp["since_last"], "to_date": cp["to_date"], "n_trades": len(cp["trades"]),
                      "commission_usd": cp["commission_usd"], "value_usd": cp["money"]["value_usd"], "benchmark_value_usd": cp["money"]["benchmark_value_usd"],
                      "net_invested_usd": cp["money"]["net_invested_usd"], "drift": cp["drift"]})
    return {"type": "checkpoints", "title_ko": f"리밸런싱 시점별 구성과 성과 ({pf_label(p)})", "portfolio_id": chosen, "items": items}


def view_table(R, chosen):
    p = next(x for x in R["backtest"]["portfolios"] if x["id"] == chosen)
    if not p["view_diagnostics"]: return None
    rows = [{"view": v["summary_ko"].split(" — ")[0], "exp": v["expected_return_annual"], "real": v["realized"], "hit": "적중" if v["hit"] else "빗나감"} for v in p["view_diagnostics"]]
    return table("시나리오 뷰와 실제 결과 (구성 후 12개월)", [("view", "뷰", "text"), ("exp", "기대", "pct"), ("real", "실제", "pct"), ("hit", "방향", "text")], rows)


def validation_tables(R, chosen):
    res = next(r for r in R["validation"]["results"] if r["id"] == chosen)
    rows = [{"rule": c["rule"], "name": c["name_ko"], "level": "필수" if c["level"] == "hard" else "권장", "msg": c["message_ko"], "status": {"pass": "통과", "warn": "주의", "fail": "미통과"}[c["status"]]} for c in res["checks"]]
    t1 = table(f"검증 규칙 ({pf_label(next(x for x in R['backtest']['portfolios'] if x['id'] == chosen))})", [("rule", "규칙", "text"), ("name", "항목", "text"), ("level", "수준", "text"), ("msg", "측정 결과", "text"), ("status", "판정", "text")], rows)
    rows2 = [{"name": pf_label(next(x for x in R["backtest"]["portfolios"] if x["id"] == r["id"])), "status": {"pass": "통과", "warn": "주의", "fail": "미통과"}[r["status"]],
              "fails": ", ".join(f"{c['rule']} {c['name_ko']}" for c in r["checks"] if c["status"] == "fail") or "-", "warns": ", ".join(f"{c['rule']} {c['name_ko']}" for c in r["checks"] if c["status"] == "warn") or "-"}
             for r in R["validation"]["results"]]
    t2 = table("전체 포트폴리오 검증 요약", [("name", "포트폴리오", "text"), ("status", "판정", "text"), ("fails", "미통과 항목", "text"), ("warns", "주의 항목", "text")], rows2)
    return t1, t2


def sources_table(R):
    return table("자료 출처", [("name", "출처", "text"), ("what", "사용한 내용", "text"), ("url", "링크", "text")], [{"name": s["name"], "what": s["what"], "url": s["url"] or ""} for s in R["sources"]])


def parameters_table(R):
    pp, pb, mm, d = R["parameters"]["portfolio"], R["parameters"]["backtest"], R["portfolio"]["market_model"], R["request"]["derived"]
    bfx = R["money_krw"].get("backtest_fx") or {}
    dsrc = mm.get("delta_source", "fixed")
    dtxt = (f"시장 내재 δ {mm.get('delta_market')} (SPY {mm.get('delta_window', {}).get('start')}~{mm.get('delta_window', {}).get('end')}) × 성향 배수 {mm.get('delta_multiplier')} = {mm['delta']}"
            if dsrc == "market_implied" else f"성향별 상수 {mm['delta']}")
    rows = [{"k": "환율(요청 시점)", "v": f"{R['money_krw']['direction']} ({d['fx_date']})"},
            {"k": "환율(백테스트 구성일)", "v": f"{bfx.get('direction', '-')} ({bfx.get('fx_date', '-')}, {bfx.get('fx_source', '-')}) — 백테스트 초기자본·적립 환산에 사용"},
            {"k": "공분산 추정", "v": f"구성일 이전 {pp['LOOKBACK_DAYS']}거래일, {pp['SHRINKAGE']} 수축 ({mm['lookback']['start']}~{mm['lookback']['end']})"},
            {"k": "Black-Litterman", "v": f"τ={pp['TAU']}, 위험회피 δ: {dtxt}, 뷰 신뢰도 하한 {pp['CONFIDENCE_FLOOR']}"},
            {"k": "백테스트", "v": f"거래비용 {pb['COMMISSION_BPS']}bp, 무위험수익률 {pb['RISK_FREE_RATE']:.0%}, 소수 주식 {'허용' if not pb['INTEGER_POSITIONS'] else '불허'}, 체크포인트 {pb['CHECKPOINT_FREQ']}"},
            {"k": "분석 모델", "v": f"{R['parameters']['llm']['model']} (의도 해석·테마 분류·시나리오 뷰·리포트 서술)"}]
    return table("계산 조건", [("k", "항목", "text"), ("v", "값", "text")], rows)


def execution_table(R):
    u = R["llm_usage"]
    rows = [{"stage": "데이터 수집", "what": "가격 15년(518종목), 기업 개요, 재무제표, 배당", "llm": "-"},
            {"stage": "의도 해석", "what": "테마·GICS 코드·키워드 추출, 성향 해석", "llm": "1회"},
            {"stage": "후보 검색·분류", "what": f"후보 {R['selection']['candidates_summary']['n_candidates']}개 → 테마 해당 {R['selection']['tagging_summary']['n_passed']}개", "llm": "2회(배치)"},
            {"stage": "정량 스크린", "what": f"{R['selection']['metric']} 상위 선정, 섹터 상한", "llm": "-"},
            {"stage": "포트폴리오 구성", "what": "규칙 4개 + 시나리오 뷰 5세트 → Black-Litterman 5개", "llm": "1회"},
            {"stage": "백테스트·검증", "what": f"bt 백테스트 {len(R['backtest']['portfolios'])}개 + 비교지수, 규칙 8개 검증", "llm": "-"},
            {"stage": "리포트", "what": "결과 해석 + 서술 생성", "llm": "2회"}]
    note = f"누적 LLM 비용 약 {u['total_cost_usd']:.4f} USD ({u.get('model')})" if u.get("available") else None
    return table("실행 기록", [("stage", "단계", "text"), ("what", "처리 내용", "text"), ("llm", "분석 모델 호출", "text")], rows, note=note)


def limitations(R):
    return ["현재 시점의 S&P 500·NASDAQ-100 구성 종목을 과거에 적용했습니다. 당시 지수에 없던 종목이나 이후 상장폐지된 종목을 반영하지 못하는 생존 편향이 있습니다.",
            "시나리오 뷰는 뉴스·공시 자료 없이 분석 모델이 기준일 상황을 가정해 만든 것이며, 기준일 이후 정보가 섞였을 가능성을 배제할 수 없습니다.",
            "시가총액비중 규칙은 현재 발행주식수에 과거 주가를 곱한 근사치를 사용했습니다.",
            "세금, 환전 수수료, 호가 차이(슬리피지)는 반영하지 않았습니다. 원화 금액은 투자 시작 기준일 환율 하나로 환산했습니다.",
            "회사 소개는 Yahoo Finance 기업 개요의 첫 문장이며, 이 리포트는 기업의 재무 상태나 경쟁력을 평가하지 않습니다."]
