"""리포트의 데이터 블록 (표·차트·KPI·체크포인트) — 13_results 에서 코드가 만든다. LLM 은 여기 없다.

블록 타입은 Front 렌더러(features/report/blocks)와 같다: paragraphs, kpis, table, donut, line, area, bar, funnel, callout, cards, checkpoints, glossary, evidence.
"""

from __future__ import annotations

from typing import Any

NAMES = {"equal_weight": "동일비중", "market_cap": "시가총액비중", "inverse_volatility": "역변동성비중", "min_variance": "최소분산"}
STATUS_KO = {"pass": "통과", "warn": "주의", "fail": "미통과", "info": "참고", "flag": "허용 초과", "n/a": "-"}
LEVEL_KO = {"hard": "필수", "soft": "권장", "info": "참고", "flag": "표시"}
KIND_KO = {"black_litterman": "뉴스 뷰(BL)", "template": "규칙", "benchmark": "비교지수", "alternative": "대안", "matched": "낙폭 맞춤"}
VERDICT_HEAD_KO = {"recommended": "추천", "recommended_warn": "추천(주의)", "insufficient": "구성 불충분"}


def pf_label(p: dict[str, Any]) -> str:
    if p.get("kind") in ("benchmark", "alternative", "matched"):
        return p.get("name_ko", p["id"])
    if p.get("title_ko"):
        return f"뉴스 뷰: {p['title_ko']}"
    return NAMES.get(p["id"], p.get("name_ko", p["id"]))


def all_blocks(R: dict[str, Any]) -> list[dict[str, Any]]:
    return [*R["backtest"]["portfolios"], *R["backtest"].get("benchmarks", [R["backtest"]["benchmark"]]), *R["validation"].get("alternatives", [])]


def find(R: dict[str, Any], pid: str) -> dict[str, Any]:
    return next(x for x in all_blocks(R) if x["id"] == pid)


def chosen_portfolio_id(R: dict[str, Any]) -> tuple[str, bool]:
    val = R["validation"]
    rec = val.get("recommended")
    cid = val.get("chosen_id") or (rec["id"] if rec else R["portfolio"]["targets"]["baseline"]["id"])
    return cid, bool(rec)


def table(title, columns, rows, note=None):
    b: dict[str, Any] = {"type": "table", "title_ko": title, "columns": [{"key": k, "label_ko": l, "format": f} for k, l, f in columns], "rows": rows}
    if note:
        b["note_ko"] = note
    return b


def kpis(R: dict[str, Any], chosen: str) -> list[dict[str, Any]]:
    p = find(R, chosen)
    h, krw = p["headline"], R["money_krw"]["by_portfolio"][chosen]
    bench = R["backtest"]["benchmark"]["id"].replace("benchmark_", "")
    short = not R["backtest"]["period"].get("annualized_reliable", True)
    days = R["backtest"]["period"].get("window_days", R["backtest"]["period"]["trading_days"])
    b = R["backtest"]["benchmark"]["metrics"]["return"]["total_return"]
    ret = ({"id": "cagr", "label_ko": f"기간 수익률 ({days}거래일)", "value": h.get("period_return"), "format": "pct", "note_ko": f"연 환산 {h['cagr']:+.1%} 는 1년 미만 창이라 참고만"}
           if short else {"id": "cagr", "label_ko": "연평균 수익률 (CAGR)", "value": h["cagr"], "format": "pct", "note_ko": "백테스트 기간 기준 연 환산"})  # fmt: skip
    ex = ({"id": "excess", "label_ko": f"비교지수({bench}) 대비 (기간)", "value": (p["metrics"]["return"]["total_return"] or 0) - b, "format": "pp", "note_ko": "같은 기간 누적 수익률 차이"}
          if short else {"id": "excess", "label_ko": f"비교지수({bench}) 대비", "value": h["excess_cagr"], "format": "pp", "note_ko": "같은 기간 CAGR 차이"})  # fmt: skip
    return [
        {"id": "final_value", "label_ko": "최종 평가금액", "value": h["final_value_usd"], "format": "usd",
         "note_ko": (f"약 {krw['final_value_krw']:,.0f}원 · " if R["request"]["capital"].get("currency", "KRW") == "KRW" else "") + f"투입 원금 {p['money']['net_invested_usd']:,.0f} USD"},
        ret, ex,
        {"id": "mdd", "label_ko": "최대낙폭 (MDD)", "value": h["max_drawdown"], "format": "pct", "note_ko": _tolerance_note(R)},
        {"id": "sharpe", "label_ko": "Sharpe 비율", "value": h["sharpe"], "format": "ratio", "note_ko": f"무위험수익률 {R['parameters']['backtest']['risk_free_rate']:.0%} 가정"},
        {"id": "view_hit", "label_ko": "뉴스 뷰 적중률", "value": h["view_hit_ratio"], "format": "pct",
         "note_ko": (f"구성 뒤 12개월 기준 · 다음 리밸런싱까지는 {h['view_hit_ratio_next_rb']:.0%}" if h.get("view_hit_ratio_next_rb") is not None else "구성 뒤 12개월 기준") if h["view_hit_ratio"] is not None else "이 포트폴리오에는 뷰가 없습니다"},
    ]  # fmt: skip


def _tolerance_note(R) -> str:
    """허용 낙폭 안내 (라운드 5: 입력값 그대로). 낙폭 맞춤안 목표가 다르면(손실 시 매도 ×0.8, 경험 없음 ×0.9) 그 이유를 함께."""
    eff = float(R["intent"]["risk_params"]["effective_max_drawdown"])
    inp = float(R["request"]["risk"].get("max_drawdown_tolerance", eff))
    if abs(eff - inp) < 1e-6:
        return f"손실 감내 수준 {inp:.1%}"
    why = []
    if R["request"]["risk"].get("loss_reaction") == "sell":
        why.append("손실 시 매도 성향 ×0.8")
    if R["request"].get("profile", {}).get("investment_experience") == "none":
        why.append("투자 경험 없음 ×0.9")
    return f"손실 감내 수준 {inp:.1%} · 낙폭 맞춤안 목표 {eff:.1%} ({', '.join(why) or '보정'})"


# ───────────────────────── 요청·의도 ─────────────────────────
def request_table(R):
    q, d, c, h, r = R["request"], R["request"]["derived"], R["request"]["capital"], R["request"]["horizon"], R["request"]["risk"]
    cur = "원" if c["currency"] == "KRW" else "USD"
    bfx = R["money_krw"].get("backtest_fx") or {}
    rows = [{"k": "투자금", "v": f"{c['initial_amount']:,.0f}{cur} → 백테스트 시작 {R['portfolio']['backtest_spec']['capital']['initial_amount_usd']:,.2f} USD (시작일 환율 {bfx.get('direction', '-')}, {bfx.get('fx_date', '-')}) · 현재 구성 {d['initial_amount_usd']:,.2f} USD (기준일 환율 {R['money_krw']['direction']}, {d['fx_date']})"},
            {"k": "월 적립", "v": f"{c.get('monthly_contribution', 0):,.0f}{cur} (매월 {c.get('contribution_day', 25)}일) → {d['monthly_contribution_usd']:,.2f} USD"},
            {"k": "투자기간", "v": f"{h['target_years']}년 (분석 기준일 {d['as_of']}, 백테스트 {h.get('backtest_years', 3)}년)"},
            {"k": "투자성향", "v": f"{r['risk_tolerance']} · 손실 감내 수준 {r['max_drawdown_tolerance']:.1%} · 손실 시 {r['loss_reaction']}"},
            {"k": "목표 수익률", "v": f"연 {r['target_annual_return']:.1%} · 비교지수 {r['benchmark']}"},
            {"k": "투자 유니버스", "v": ", ".join(R["request"]["constraints"]["universe"])},
            {"k": "투자 아이디어", "v": q["natural_language"]["idea"]}]  # fmt: skip
    return table("요청 내용", [("k", "항목", "text"), ("v", "내용", "text")], rows)


def themes_table(R):
    rows = [{"label": t["label_ko"], "desc": t["description_ko"], "codes": ", ".join(t["gics_codes"]), "kw": ", ".join(t["keywords"][:6])} for t in R["intent"]["interpretation"]["themes"]]
    return table("추출한 테마", [("label", "테마", "text"), ("desc", "어떤 기업이 해당하는가", "text"), ("codes", "GICS 코드", "text"), ("kw", "검색 키워드", "text")], rows)


def constraints_table(R):
    c = R["request"]["constraints"]
    rb = R["request"]["derived"]["rebalance_rule"]
    rows = [{"k": "종목 수", "v": f"목표 {c['num_holdings']['target']}개 (허용 {c['num_holdings']['min']}~{c['num_holdings']['max']})"},
            {"k": "종목당 상한", "v": f"{c['max_weight_per_stock']:.0%}"}, {"k": "섹터당 상한", "v": f"{c['max_weight_per_sector']:.0%}"},
            {"k": "최소 현금 비율", "v": f"{c.get('min_cash_ratio', 0):.0%}"},
            {"k": "리밸런싱", "v": rb["description_ko"]}, {"k": "제외", "v": ", ".join(c["exclude_themes"] + c["exclude_sectors"] + c["exclude_tickers"]) or "없음"},
            {"k": "필수 포함", "v": ", ".join(c.get("must_include_tickers", [])) or "없음"},
            {"k": "레버리지·공매도", "v": "모두 불허"},
            {"k": "최소 시가총액·거래대금", "v": f"{c.get('min_market_cap_usd', 0) / 1e9:.1f}B USD · 일 {c.get('min_avg_daily_volume_usd', 0) / 1e6:.0f}M USD"}]  # fmt: skip
    return table("지켜야 하는 조건 (하드 제약)", [("k", "항목", "text"), ("v", "값", "text")], rows)


def soft_table(R):
    rp, nt = R["intent"]["risk_params"], R["intent"]["news_tilt"]
    rows = [{"k": "변동성 선호", "v": rp["volatility_preference"]}, {"k": "허용 최대낙폭·낙폭 맞춤안 목표", "v": _tolerance_note(R).replace("손실 감내 수준 ", "")},
            {"k": "해석 메모", "v": rp.get("notes_ko", "")},
            {"k": "뉴스 뷰 반영", "v": (f"켜짐 · 종목당 최대 {nt['max_tilt_per_stock']:.0%}p, 뷰 신뢰도 상한 {nt['max_view_confidence']}" if nt["enabled"] else "꺼짐 (기준 비중만)")}]  # fmt: skip
    return table("성향 해석 (소프트 조건)", [("k", "항목", "text"), ("v", "해석", "text")], rows)


def conflicts_cards(R):
    cs = R["intent"]["interpretation"].get("conflicts", [])
    if not cs:
        return None
    return {"type": "cards", "title_ko": "입력 간에 확인한 점", "items": [{"title_ko": c["field"], "text_ko": c["issue_ko"] + " → " + c["resolution_ko"], "meta": []} for c in cs]}


# ───────────────────────── 선정 ─────────────────────────
def funnel(R):
    return {"type": "funnel", "items": [{"label_ko": f["label_ko"], "count": f["count"]} for f in R["selection"]["funnel"]]}


def selection_table(R):
    m = R["selection"]["metric"]
    now_as_of, bt_as_of = R["selection"]["as_of_now"]["as_of"], R["selection"]["backtest_as_of"]["as_of"]
    rows = [{"ticker": t["ticker"], "name": t["name"], "market": t.get("market", ""), "sector": t["sector"], "summary": t["summary"], "reason": t.get("theme_reason_ko") or "",
             "conf": t["theme_confidence"], "rank_bt": t["rank_backtest"], "metric_bt": t["metric_backtest"], "rank_now": t["rank_now"], "metric_now": t["metric_now"],
             "fact": t.get("metric_fact_id") or ""} for t in R["selection"]["table"]]  # fmt: skip
    return table(f"선정 종목 (백테스트 기준일 {bt_as_of} 순위 → 분석 기준일 {now_as_of} 순위)",
                 [("ticker", "티커", "text"), ("name", "회사", "text"), ("market", "시장", "text"), ("sector", "섹터", "text"), ("summary", "한 줄 소개", "text"),
                  ("reason", "테마 판정 사유", "text"), ("conf", "신뢰도", "num"), ("rank_bt", f"순위({bt_as_of})", "int"), ("metric_bt", m, "pct"),
                  ("rank_now", f"순위({now_as_of})", "int"), ("metric_now", m, "pct"), ("fact", "지표 근거 ID", "text")],
                 rows, note="순위가 비어 있으면 그 기준일에는 선정되지 않은 종목입니다. 지표 근거 ID 는 출처 패널에서 값·기준일을 확인할 수 있습니다.")  # fmt: skip


def excluded_table(R):
    ex = R["selection"]["as_of_now"]["rejected_examples"]
    if not ex:
        return None
    rows = [{"ticker": r["ticker"], "name": r["name"], "reason": r["reason"], "metric": r.get("metric_value")} for r in ex]
    return table(f"테마에는 해당하지만 최종 선정에서 빠진 예 ({R['selection']['as_of_now']['as_of']} 기준)",
                 [("ticker", "티커", "text"), ("name", "회사", "text"), ("reason", "제외 이유", "text"), ("metric", "지표값", "pct")], rows)  # fmt: skip


def diff_table(R):
    d = R["selection"]["backtest_as_of"]["diff_vs_original"]
    rows = [{"k": "백테스트용 재선정에서 추가된 종목", "v": ", ".join(d["added"]) or "없음"}, {"k": "빠진 종목", "v": ", ".join(d["removed"]) or "없음"}]
    return table("분석 기준일 선정 목록과 백테스트 시작일 재선정 목록의 차이", [("k", "구분", "text"), ("v", "종목", "text")], rows,
                 note="백테스트는 시작일 당시에 알 수 있던 정보만으로 같은 규칙을 다시 적용합니다. 그래서 목록이 달라질 수 있습니다.")  # fmt: skip


def company_cards(R):
    expl = R["selection"].get("explained")
    if not expl or not expl.get("per_ticker"):
        return None
    names = {t["ticker"]: t for t in R["selection"]["table"]}
    items = []
    for r in expl["per_ticker"]:
        t = names.get(r["ticker"], {})
        items.append({"title_ko": f"{r['ticker']} · {t.get('name', '')}", "text_ko": r.get("rationale_ko", ""),
                      "meta": [{"label_ko": "섹터", "value": t.get("sector", "")}, {"label_ko": "테마 신뢰도", "value": f"{t.get('theme_confidence') or 0:.2f}"}]})  # fmt: skip
    return {"type": "cards", "title_ko": "기업별 선정 근거 (인용 ID 는 출처 패널 참조)", "items": items}


def infeasibility_callout(R):
    bt_sel, now = R["selection"]["backtest_as_of"], R["selection"]["as_of_now"]
    inf = bt_sel.get("infeasibility") or now.get("infeasibility")
    if inf:
        txt = (f"선정된 종목의 섹터 구성으로는 종목당 {inf['stock_cap']:.0%}·섹터당 {inf['sector_cap']:.0%} 상한 안에서 투자금 전체를 배분할 수 없습니다(배분 가능 {inf['capacity']:.0%}). "
               f"섹터별 종목 수: " + ", ".join(f"{k} {v}" for k, v in inf["sector_counts"].items()) + ". 배분하지 못한 금액은 현금으로 둡니다. 선택지: " + " / ".join(inf["options_ko"]))  # fmt: skip
        return {"type": "callout", "tone": "caution", "title_ko": "상한 안에서 전액 배분할 수 없는 구성", "text_ko": txt}
    ov = bt_sel.get("sector_overflow") or now.get("sector_overflow")
    if ov:
        return {"type": "callout", "tone": "info", "title_ko": "섹터 상한이 비중을 누른 부분", "text_ko": ov["note_ko"] + f" (해당 종목: {', '.join(ov['tickers'])})"}
    return None


# ───────────────────────── 구성 ─────────────────────────
def baseline_table(R):
    bl = R["portfolio"]["baselines"]
    base = next(p for p in bl["portfolios"] if p["id"] == bl["chosen_baseline"])
    n = len(base["weights"])
    sec = {t["ticker"]: t["sector"] for t in R["selection"]["table"]}
    rows = [{"ticker": t, "sector": sec.get(t, ""), "raw": 1 / n, "final": w} for t, w in base["weights"].items()]
    return table(f"기준 포트폴리오({NAMES.get(base['id'], base['id'])}): 1/N 참고값 → 상한 적용 후 비중", [("ticker", "티커", "text"), ("sector", "섹터", "text"), ("raw", "1/N", "pct1"), ("final", "최종 비중", "pct1")], rows,
                 note=("적용된 제약: " + ", ".join(base["constraints_applied"])) if base["constraints_applied"] else "제약이 묶이지 않았습니다.")  # fmt: skip


def templates_table(R):
    rows = [{"name": NAMES.get(p["id"], p["id"]), "rule": p["rule_ko"], "vol": p["ex_ante"]["vol"], "neff": p["ex_ante"]["effective_n"], "top": max(p["weights"].values()), "cash": p.get("cash_weight", 0)}
            for p in R["portfolio"]["baselines"]["portfolios"]]  # fmt: skip
    return table("비중 규칙 4가지 비교 (구성일 기준 추정치)", [("name", "규칙", "text"), ("rule", "설명", "text"), ("vol", "예상 변동성", "pct"), ("neff", "유효 종목 수", "num"), ("top", "최대 비중", "pct1"), ("cash", "현금", "pct1")], rows)


def donut(title, weights, note=None):
    items = [{"label": t, "value": w} for t, w in sorted(weights.items(), key=lambda x: -x[1]) if w > 1e-6]
    b: dict[str, Any] = {"type": "donut", "title_ko": title, "items": items}
    if note:
        b["note_ko"] = note
    return b


def scenario_cards(R):
    ports = R["portfolio"]["targets"]["portfolios"]
    if not ports:
        return None
    items = []
    bt = {p["id"]: p for p in R["backtest"]["portfolios"]}
    for p in ports:
        top = sorted(p["delta_vs_baseline"].items(), key=lambda x: -abs(x[1]))[:3]
        views = "\n".join("· " + v["summary_ko"] for v in p["views_applied"])
        hit = bt.get(p["id"], {}).get("headline", {}).get("view_hit_ratio")
        items.append({"title_ko": p.get("title_ko") or p["name_ko"], "text_ko": (p.get("portfolio_view") or "").split("\n")[0] + "\n" + views,
                      "meta": [{"label_ko": "기준 대비 주요 변화", "value": ", ".join(f"{t} {x:+.1%}" for t, x in top)},
                               {"label_ko": "뷰 적중률(백테스트)", "value": f"{hit:.0%}" if hit is not None else "-"},
                               {"label_ko": "근거", "value": ", ".join(sorted({i for v in p["views_applied"] for i in v.get("evidence_ids", [])})) or "-"}]})  # fmt: skip
    return {"type": "cards", "title_ko": "시작일 뉴스 뷰 Black-Litterman 포트폴리오", "items": items}


def allocation_table(R, chosen):
    p = find(R, chosen)
    init = R["portfolio"]["backtest_spec"]["capital"]["initial_amount_usd"]
    fx = R["money_krw"]["fx_rate"]
    sec = {t["ticker"]: t["sector"] for t in R["selection"]["table"]}
    names = {t["ticker"]: t["name"] for t in R["selection"]["table"]}
    rows = [{"ticker": t, "name": names.get(t, t), "sector": sec.get(t, ""), "w": w, "usd": init * w, "krw": init * w * fx} for t, w in sorted(p["target_weights"].items(), key=lambda x: -x[1])]
    cash = 1 - sum(p["target_weights"].values())
    if cash > 1e-6:
        rows.append({"ticker": "현금", "name": "", "sector": "", "w": cash, "usd": init * cash, "krw": init * cash * fx})
    return table(f"배분 금액 ({pf_label(p)}, 백테스트 초기 투자금 {init:,.0f} USD 기준)", [("ticker", "티커", "text"), ("name", "회사", "text"), ("sector", "섹터", "text"), ("w", "비중", "pct1"), ("usd", "USD", "usd"), ("krw", "원화", "krw")], rows)


def delta_bar(R, pid):
    p = next((x for x in R["portfolio"]["targets"]["portfolios"] if x["id"] == pid), None)
    if not p:
        return None
    return {"type": "bar", "title_ko": f"{p.get('title_ko') or p['name_ko']}: 기준 비중 대비 변화", "items": [{"label": t, "value": v} for t, v in sorted(p["delta_vs_baseline"].items(), key=lambda x: -x[1])], "format": "pp"}


def sector_bar(R, chosen):
    p = find(R, chosen)
    sw = p["metrics"]["composition"]["sector_weights_avg"]
    return {"type": "bar", "title_ko": f"섹터 노출 (기간 평균 비중, {pf_label(p)})", "items": [{"label": k, "value": v} for k, v in sorted(sw.items(), key=lambda x: -x[1])], "format": "pct1"}


# ───────────────────────── 성과 ─────────────────────────
def assumptions_callout(R):
    e, s = R["backtest"]["engine"], R["portfolio"]["backtest_spec"]
    ex = (e.get("execution_rule") or {}).get("description_ko", "")
    txt = (f"기간 {s['period']['start']} ~ {s['period']['end']} ({R['backtest']['period']['trading_days']}거래일). 초기 투자금 {s['capital']['initial_amount_usd']:,.0f} USD, "
           f"매월 {e['contribution_usd']:,.0f} USD 적립 {e['n_contributions']}회. {s['rebalance_rule']['description_ko']}. {ex} 거래비용 거래대금의 {e['commission_bps'] / 100:.2f}%, "
           f"배당 재투자, 소수 주식 허용, 무위험수익률 연 {e['risk_free_rate']:.0%}. 한국 종목은 거래일 환율로 USD 환산. 과거 성과는 미래 성과를 보장하지 않습니다.")  # fmt: skip
    if _has_kr(R):
        txt += " 모든 성과·지표(수익률·변동성·낙폭·모멘텀)는 미국 달러 환산 가격 기준이라, 원화 종목에는 환율 변동이 섞여 있습니다. 원화로 보는 수익과 다를 수 있습니다."
    return {"type": "callout", "tone": "info", "title_ko": "백테스트 가정", "text_ko": txt}


def _has_kr(R) -> bool:
    tickers = [t.get("ticker") for t in (R.get("selection") or {}).get("table") or []]
    if not tickers:
        tickers = ((R.get("backtest") or {}).get("reproducibility") or {}).get("panel", {}).get("tickers") or []
    if not tickers:
        tickers = list(((R.get("portfolio") or {}).get("backtest_spec") or {}).get("selection", {}).get("tickers") or [])
    return any(str(t).endswith(".KS") for t in tickers)


def comparison_table(R):
    status = {r["id"]: r["status"] for r in R["validation"]["results"]}
    status.update({a["id"]: a["status"] for a in R["validation"].get("alternatives", [])})
    rows = []
    for p in all_blocks(R):
        h, m = p["headline"], p["metrics"]
        rows.append({"name": pf_label(p), "kind": KIND_KO[p["kind"]], "cagr": h["cagr"], "vol": m["risk"]["ann_vol"], "sharpe": h["sharpe"], "mdd": h["max_drawdown"],
                     "excess": h["excess_cagr"], "final": h["final_value_usd"], "irr": p["money"]["irr_annual"], "status": STATUS_KO.get(status.get(p["id"], "n/a"), "-")})  # fmt: skip
    return table("포트폴리오 비교 (같은 기간·같은 적립)", [("name", "포트폴리오", "text"), ("kind", "종류", "text"), ("cagr", "CAGR", "pct"), ("vol", "변동성", "pct"), ("sharpe", "Sharpe", "ratio"),
                 ("mdd", "최대낙폭", "pct"), ("excess", "비교지수 대비", "pp"), ("final", "최종 평가금액", "usd"), ("irr", "적립 기준 연수익(XIRR)", "pct"), ("status", "검증", "text")], rows,
                 note="비교지수 대비는 사용자가 지정한 비교지수(" + R["portfolio"]["backtest_spec"]["benchmark"] + ") 기준입니다. '낙폭 맞춤'은 기준 비중의 주식 비율을 줄여 과거 최대낙폭을 목표 안에 맞춘 후보입니다. 검증 '주의'에는 허용 낙폭 초과 표시도 들어갑니다.")  # fmt: skip


def yearly_table(R, chosen):
    p, b = find(R, chosen), R["backtest"]["benchmark"]
    years = sorted(p["yearly_returns"])
    rows = [{"name": pf_label(p), **{y: p["yearly_returns"][y] for y in years}}, {"name": b["name_ko"], **{y: b["yearly_returns"].get(y) for y in years}}]
    return table("연도별 수익률", [("name", "구분", "text")] + [(y, y, "pct") for y in years], rows, note="첫해와 마지막 해는 일부 기간입니다.")


def monthly_table(R, chosen):
    p = find(R, chosen)
    by: dict[int, dict[int, float]] = {}
    for m in p["monthly_returns"]:
        by.setdefault(m["year"], {})[m["month"]] = m["return"]
    rows = [{"year": str(y), **{f"m{k}": by[y].get(k) for k in range(1, 13)}} for y in sorted(by)]
    return table("월별 수익률", [("year", "연도", "text")] + [(f"m{k}", f"{k}월", "pct") for k in range(1, 13)], rows)


def contribution_bar(R, chosen):
    p = find(R, chosen)
    return {"type": "bar", "title_ko": "종목별 수익 기여 (기간 전체)", "items": [{"label": t, "value": v} for t, v in sorted(p["ticker_contribution"].items(), key=lambda x: -(x[1] or 0)) if v is not None], "format": "pp"}


def checkpoints_block(R, chosen):
    p = find(R, chosen)
    items = []
    for cp in p["checkpoints"]:
        items.append({"seq": cp["seq"], "date": cp["date"], "kind": cp["kind"], "n_trading_days_to_date": cp["n_trading_days_to_date"],
                      "weights_before": cp["weights"]["before"], "weights_after": cp["weights"]["after"], "weights_target": cp["weights"]["target"],
                      "holdings": cp["holdings"], "since_last": cp["since_last"], "to_date": cp["to_date"], "n_trades": len(cp["trades"]),
                      "commission_usd": cp["commission_usd"], "value_usd": cp["money"]["value_usd"], "benchmark_value_usd": cp["money"]["benchmark_value_usd"],
                      "net_invested_usd": cp["money"]["net_invested_usd"], "drift": cp["drift"]})  # fmt: skip
    return {"type": "checkpoints", "title_ko": f"리밸런싱 시점별 구성과 성과 ({pf_label(p)})", "portfolio_id": chosen, "items": items}


def view_table(R, chosen):
    p = find(R, chosen)
    if not p.get("view_diagnostics"):
        return None
    rows = [{"view": v["summary_ko"].split(" — ")[0], "exp": v["expected_return_annual"], "real": v["realized"], "hit": "적중" if v["hit"] else "빗나감",
             "ev": ", ".join(v.get("evidence_ids", []))} for v in p["view_diagnostics"]]  # fmt: skip
    return table("뉴스 뷰와 실제 결과 (구성 후 12개월)", [("view", "뷰", "text"), ("exp", "기대", "pct"), ("real", "실제", "pct"), ("hit", "방향", "text"), ("ev", "근거", "text")], rows)


def validation_tables(R, chosen):
    res = next((r for r in R["validation"]["results"] if r["id"] == chosen), None)
    alt = next((a for a in R["validation"].get("alternatives", []) if a["id"] == chosen), None)
    checks = res["checks"] if res else (alt["checks"] if alt else [])
    rows = [{"rule": c["rule"], "name": c["name_ko"], "level": LEVEL_KO.get(c["level"], c["level"]), "msg": c["message_ko"], "status": STATUS_KO[c["status"]]} for c in checks]
    integ = (res or alt or {}).get("integrity") or []
    n_int = sum(1 for c in integ if c["status"] == "pass")
    t1 = table(f"검증 규칙 ({pf_label(find(R, chosen))})", [("rule", "규칙", "text"), ("name", "항목", "text"), ("level", "수준", "text"), ("msg", "측정 결과", "text"), ("status", "판정", "text")], rows,
               note=(f"표시 = 추천 여부를 가르지 않고 순위에 반영(허용 낙폭 초과는 5%p 마다 한 단계 뒤로), 권장 = 주의로만 표시, 참고 = 판정에 넣지 않는 정보. 종목·섹터 상한 준수와 자료 무결성은 코드가 따로 점검했습니다 ({n_int}/{len(integ)} 통과, 실행 기록 참고)." if integ else None))  # fmt: skip
    rows2 = [{"name": pf_label(find(R, r["id"])), "status": STATUS_KO[r["status"]],
              "fails": ", ".join(f"{c['rule']} {c['name_ko']}" for c in r["checks"] if c["status"] == "fail") or "-",
              "warns": ", ".join(f"{c['rule']} {c['name_ko']}" + (" (허용 초과)" if c["status"] == "flag" else "") for c in r["checks"] if c["status"] in ("warn", "flag")) or "-"} for r in R["validation"]["results"]]  # fmt: skip
    t2 = table("전체 포트폴리오 검증 요약", [("name", "포트폴리오", "text"), ("status", "판정", "text"), ("fails", "미통과 항목", "text"), ("warns", "주의·표시 항목", "text")], rows2,
               note="추천은 순위(목표수익 → 비교지수 → 허용 낙폭 초과 폭 → Sharpe) 1위입니다. 미통과는 내부 점검(상한·자료 무결성)에 걸린 경우만 생깁니다.")  # fmt: skip
    return t1, t2


def recommendation_card(R):
    rec = R["validation"].get("recommended")
    s = R["validation"]["summary"]
    text = rec["reason_ko"] if rec else (next((n["message_ko"] for n in (R.get("notices") or []) if n.get("code") == "no_portfolio_passed"), None)
                                        or "모든 포트폴리오가 필수 검증 규칙을 통과하지 못했습니다.")  # 영어 검증 경고 대신 한국어 공지
    vd = (rec or {}).get("verdict")
    title = (f"{vd['head_ko']}: {pf_label(find(R, rec['id']))}" if vd else (f"추천: {pf_label(find(R, rec['id']))}" if rec else "조건을 통과한 포트폴리오 없음"))
    meta = ([{"label_ko": "비교 후보", "value": f"{s.get('n_candidates', len(R['validation']['results']))}개"}, {"label_ko": "주의·허용 초과 있는 후보", "value": f"{s['n_warn']}개"}]
            if vd else [{"label_ko": "통과/주의/미통과", "value": f"{s['n_pass']}/{s['n_warn']}/{s['n_fail']}"}])
    return {"type": "cards", "title_ko": "검증 결과", "items": [{"title_ko": title, "text_ko": text, "meta": meta}]}


def alternatives_cards(R):
    alts = R["validation"].get("alternatives", [])
    if not alts:
        return None
    items = []
    for a in alts:
        h = a["headline"]
        items.append({"title_ko": a["name_ko"], "text_ko": a["reason_ko"],
                      "meta": [{"label_ko": "검증", "value": STATUS_KO[a["status"]] + (" (" + ", ".join(c["rule"] for c in a["checks"] if c["status"] != "pass") + ")" if a["status"] != "pass" else "")},
                               {"label_ko": "CAGR / 최대낙폭 / Sharpe", "value": f"{h['cagr']:+.1%} / {h['max_drawdown']:.1%} / {(h['sharpe'] or 0):.2f}"},
                               {"label_ko": "최종 평가금액", "value": f"{h['final_value_usd']:,.0f} USD"}]})  # fmt: skip
    return {"type": "cards", "title_ko": "검토 가능한 대안 (검증 단계가 계산한 현금 혼합안)", "items": items}


# ───────────────────────── 뉴스·walk-forward·현재 구성 ─────────────────────────
def evidence_block(R, ids: list[str], title="인용된 근거"):
    idx = R["evidence_index"]
    items = []
    for i in ids:
        e = idx.get(i)
        if not e:
            continue
        items.append({"id": i, "kind": e["kind"], "title": e.get("title", ""), "source": e.get("source", ""), "url": e.get("url"), "published_at": e.get("published_at"),
                      "data_as_of": e.get("data_as_of"), "tickers": e.get("tickers", []), "value": e.get("value"), "unit": e.get("unit")})  # fmt: skip
    return {"type": "evidence", "title_ko": title, "items": items}


def news_used_ids(R) -> list[str]:
    out: set[str] = set()
    for p in R["portfolio"]["targets"]["portfolios"]:
        for v in p["views_applied"]:
            out.update(v.get("evidence_ids", []))
    wf = R["portfolio"].get("walkforward")
    if wf:
        for p in wf["portfolios"]:
            for d, views in (p.get("views_by_date") or {}).items():
                for v in views:
                    out.update(v.get("evidence_ids", []))
    f = R["portfolio"].get("forward")
    if f:
        for p in f["portfolios"]:
            for v in p["views_applied"]:
                out.update(v.get("evidence_ids", []))
    return sorted(out)


def walkforward_blocks(R):
    wf = R["portfolio"].get("walkforward")
    if not wf:
        return []
    bt_by = {p["id"]: p for p in R["backtest"]["portfolios"]}
    bl = next(p for p in wf["portfolios"] if p["kind"] == "black_litterman")
    base_id = "wf_" + R["portfolio"]["targets"]["baseline"]["id"]
    base_p = next((p for p in wf["portfolios"] if p["id"] == base_id), wf["portfolios"][0])
    rows = []
    for d in wf["dates"]:
        ns = wf["news_summary"].get(d, {})
        views = bl["views_by_date"].get(d, [])
        w, base = bl["weights_by_date"][d], base_p["weights_by_date"][d]
        top = sorted(((t, w[t] - base[t]) for t in w if t in base), key=lambda x: -abs(x[1]))[:3]
        rows.append({"date": d, "window": " ~ ".join(ns.get("window", ["", ""])), "articles": ns.get("n_articles", 0), "tickers": ns.get("n_tickers_with_news", 0),
                     "views": len(views), "delta": ", ".join(f"{t} {x:+.1%}" for t, x in top) if views else "기준 비중 유지 (뉴스 부족)"})  # fmt: skip
    blocks = [table("리밸런싱 시점별 뉴스와 비중 변화", [("date", "리밸런싱일", "text"), ("window", "뉴스 창", "text"), ("articles", "기사 수", "int"), ("tickers", "뉴스 있는 종목", "int"),
                    ("views", "뷰 수", "int"), ("delta", "기준 대비 주요 변화", "text")], rows)]  # fmt: skip
    cards = []
    for d in wf["dates"]:
        for v in bl["views_by_date"].get(d, []):
            cards.append({"title_ko": f"{d} · {v['summary_ko'].split(' — ')[0]}", "text_ko": v.get("rationale_ko", ""),
                          "meta": [{"label_ko": "근거", "value": ", ".join(v.get("evidence_ids", [])) or "-"}, {"label_ko": "신뢰도", "value": f"{v['confidence']:.2f}"}]})  # fmt: skip
    if cards:
        blocks.append({"type": "cards", "title_ko": "뉴스로 만든 뷰 (리밸런싱 시점별)", "items": cards})
    for pid in [bl["id"], base_id]:
        p = bt_by.get(pid)
        if p:
            h = p["headline"]
            blocks.append({"type": "callout", "tone": "info", "title_ko": p["name_ko"],
                           "text_ko": f"기간 수익률 {h['period_return']:+.2%}, 최대낙폭 {h['max_drawdown']:.2%}, 최종 평가금액 {h['final_value_usd']:,.0f} USD"
                                      + (f" · 뉴스 부족으로 기준 비중을 쓴 날짜: {', '.join(bl['fallback_dates'])}" if pid == bl["id"] and bl["fallback_dates"] else "")})  # fmt: skip
    return blocks


def forward_blocks(R):
    f = R["portfolio"].get("forward")
    if not f:
        return []
    blocks = []
    nw = f.get("news_window")
    blocks.append({"type": "callout", "tone": "info", "title_ko": f"현재 구성 (분석 기준일 {f['as_of']})",
                   "text_ko": ((f"뉴스 창 {nw['window'][0]} ~ {nw['window'][1]}, 기사 {nw['n_articles']}건, 뉴스 있는 종목 {nw['n_tickers_with_news']}개. " if nw else "")
                               + f"기준일 시장모형(δ={f['market_model']['delta']}, {f['market_model']['delta_source']})으로 규칙 4개"
                               + (f"와 뉴스 뷰 Black-Litterman {len(f['portfolios'])}개를 만들었습니다." if f["portfolios"] else f"를 만들었습니다 ({f.get('fallback_reason_ko') or '뉴스 뷰 없음'}).")
                               + " 이 구성은 분석 기준일의 제안이며 백테스트 결과가 아닙니다.")})  # fmt: skip
    for p in f["portfolios"]:
        blocks.append({"type": "cards", "title_ko": p["name_ko"], "items": [{"title_ko": p.get("title_ko") or p["name_ko"], "text_ko": p.get("portfolio_view", ""), "meta": [
            {"label_ko": "기준 비중 대비 주요 변화", "value": ", ".join(f"{t} {x:+.1%}" for t, x in sorted(p["delta_vs_baseline"].items(), key=lambda x: -abs(x[1]))[:4])},
            {"label_ko": "예상 수익·변동성", "value": f"{p['ex_ante']['exp_return']:.1%} / {p['ex_ante']['vol']:.1%}"},
            {"label_ko": "근거", "value": ", ".join(sorted({i for v in p["views_applied"] for i in v.get("evidence_ids", [])})) or "-"}]}]})  # fmt: skip
    chosen = f["portfolios"][0] if f["portfolios"] else next((t for t in f["templates"] if t["id"] == f["baseline"]["id"]), f["templates"][0])
    blocks.append(donut(f"{chosen.get('name_ko', chosen['id'])} 배분 비중 (현재 구성)", chosen["weights"]))
    rows = [{"ticker": x["ticker"], "w": x["weight"], "usd": x["usd"], "krw": x["krw"]} for x in chosen["allocation"]]
    blocks.append(table(f"배분 금액 ({chosen.get('name_ko', chosen['id'])}, 투자금 {f['capital']['initial_amount_usd']:,.0f} USD, 환율 1 USD = {f['capital']['fx_rate']:,.2f} KRW)",
                        [("ticker", "티커", "text"), ("w", "비중", "pct1"), ("usd", "USD", "usd"), ("krw", "원화", "krw")], rows))  # fmt: skip
    return blocks


# ───────────────────────── 참고자료 ─────────────────────────
def sources_table(R):
    return table("자료 출처", [("name", "출처", "text"), ("what", "사용한 내용", "text"), ("url", "링크", "text")], [{"name": s["name"], "what": s["what"], "url": s["url"] or ""} for s in R["sources"]])


def parameters_table(R):
    pp, pb, mm, d = R["parameters"]["portfolio"], R["parameters"]["backtest"], R["portfolio"]["market_model"], R["request"]["derived"]
    bfx = R["money_krw"].get("backtest_fx") or {}
    dsrc = mm.get("delta_source", "fixed")
    ddm = f" × 낙폭 배수 {mm['delta_dd_multiplier']} (허용 낙폭 {mm.get('delta_tolerance', 0):.0%} 기준 20% 대비)" if mm.get("delta_dd_multiplier") is not None else ""
    dtxt = (f"시장 내재 δ {mm.get('delta_market')} ({mm.get('delta_window', {}).get('start')}~{mm.get('delta_window', {}).get('end')}) × 성향 배수 {mm.get('delta_multiplier')}{ddm} = {mm['delta']} (하한 {pp['delta_floor']})"
            if dsrc == "market_implied" else f"성향별 상수{ddm} = {mm['delta']}")  # fmt: skip
    ex = R["parameters"].get("execution_rule") or {}
    desc = R["parameters"].get("descriptor") or {}
    rows = [{"k": "분석 기준일", "v": str(d["as_of"])},
            {"k": "환율(기준일)", "v": f"{R['money_krw']['direction']} ({d['fx_date']}, {d.get('fx_source', 'fx_daily')})"},
            {"k": "환율(백테스트 시작일)", "v": f"{bfx.get('direction', '-')} ({bfx.get('fx_date', '-')}) — 백테스트 초기자본·적립 환산에 사용"},
            {"k": "정보 마감·체결", "v": ex.get("description_ko", "t−1 정보, t 종가 체결")},
            {"k": "거래일 달력", "v": "요청 시장들의 거래일 합집합, 휴장일은 직전 종가 유지"},
            {"k": "공분산 추정", "v": f"구성일 이전 {pp['lookback_days']}거래일, {pp['shrinkage']} 수축 ({mm['lookback']['start']}~{mm['lookback']['end']})"},
            {"k": "Black-Litterman", "v": f"τ={pp['tau']}, 위험회피 δ: {dtxt}, 뷰 신뢰도 하한 {pp['confidence_floor']}, 뉴스 창 {R['parameters']['news']['window_days']}일"},
            {"k": "백테스트", "v": f"거래비용 {pb['commission_bps']}bp, 무위험수익률 {pb['risk_free_rate']:.0%}, 소수 주식 {'허용' if not pb['integer_positions'] else '불허'}, 체크포인트 {pb['checkpoint_freq']}"},
            {"k": "종목 사전", "v": f"{desc.get('file', '-')} (구성종목 스냅샷 {desc.get('snapshot_date', '-')}, {desc.get('n_stocks', '-')}종목)"},
            {"k": "분석 모델", "v": f"{R['parameters']['llm']['model']} ({R['parameters']['llm']['mode']} 모드; 의도 해석·보충 질문·테마 분류·뉴스 뷰·서술)"}]  # fmt: skip
    return table("계산 조건", [("k", "항목", "text"), ("v", "값", "text")], rows)


def execution_table(R, step_summaries: dict[str, str] | None):
    u = R.get("llm_usage") or {}
    rows = [{"stage": k, "what": v} for k, v in (step_summaries or {}).items()]
    integ = [c for r in R["validation"]["results"] for c in (r.get("integrity") or [])]
    if integ:
        n_ok = sum(1 for c in integ if c["status"] == "pass")
        rows.append({"stage": "내부 점검", "what": f"종목·섹터 상한 준수, 시계열 길이·리밸런싱 횟수 일치: 포트폴리오 {len(R['validation']['results'])}개 × 3항목 중 {n_ok}/{len(integ)} 통과" + ("" if n_ok == len(integ) else " — 실패 있음(경고 확인)")})
    note = f"LLM 호출 {u.get('calls', 0)}회 (캐시 적중 {u.get('cache_hits', 0)}), 비용 약 {u.get('cost_usd', 0):.4f} USD ({u.get('model')})" if u else None
    return table("실행 기록", [("stage", "단계", "text"), ("what", "처리 내용", "text")], rows, note=note)


def data_quality_table(R):
    q = R.get("data_quality") or {}
    rows = [{"k": "기대 거래일", "v": str(q.get("expected_days", "-"))}, {"k": "사용 가능 종목", "v": str(q.get("usable", "-"))},
            {"k": "제외 종목", "v": ", ".join(f"{t}: {r}" for t, r in (q.get("excluded") or {}).items()) or "없음"},
            {"k": "직전값으로 채운 종목(일수)", "v": ", ".join(f"{t} {n}" for t, n in (q.get("filled") or {}).items()) or "없음"}]  # fmt: skip
    return table("가격 자료 품질 판정 (커버리지 0.95, 1거래일 결측만 채움)", [("k", "항목", "text"), ("v", "값", "text")], rows)


def notices_table(R):
    """§6 '분석 중 확인한 점': 사용자가 조건을 바꾸거나 알아야 하는 경고만 (level=user). 없으면 None."""
    rows = []
    for n in R.get("notices") or []:
        when = (f"{n['count']}회" if n.get("count", 1) > 1 else "") + (f" {n['dates'][0]}~{n['dates'][-1]}" if len(n.get("dates") or []) > 1 else (f" {n['dates'][0]}" if n.get("dates") else ""))
        rows.append({"msg": n["message_ko"], "when": when.strip() or "-"})
    if not rows:
        return None
    return table("분석 중 확인한 점 (조건을 바꾸면 달라질 수 있는 것)", [("msg", "내용", "text"), ("when", "횟수·기간", "text")], rows)


def limitations(R):
    desc = R["parameters"].get("descriptor") or {}
    out = [f"구성종목 사전은 {desc.get('snapshot_date', '최근')} 스냅샷 하나를 모든 과거 기준일에 적용했습니다. 당시 지수에 없던 종목이나 이후 상장폐지된 종목을 반영하지 못하는 생존 편향이 있습니다.",
           "뉴스 뷰는 팀 데이터베이스의 공시 목록(사건 종류·제목·이용 가능일만, 본문 없음)과 뉴스 헤드라인(본문 없음)만 근거로 하며, 근거가 없는 날짜·종목은 기준 비중을 유지합니다. 공시는 사건의 존재만 알려 주고, 뉴스·공시가 성과의 원인이라고 단정하지 않습니다.",
           "시가총액비중은 valuation_daily 의 유통주식수 × 종가를 쓰며, 가치평가 항목이 비어 있는 종목은 0 으로 처리됩니다.",
           "세금, 환전 수수료, 호가 차이(슬리피지)는 반영하지 않았습니다. 한국 종목의 거래세·소수 주식 불가는 반영하지 않았습니다.",
           "리밸런싱일 t 의 비중은 t−1 까지 자료로 계산하고 t 종가로 체결했다고 가정합니다. 실제 체결 가격·시점은 다를 수 있습니다.",
           "회사 소개는 데이터베이스의 사업 설명 첫 문장이며, 이 리포트는 기업의 재무 상태나 경쟁력을 평가하지 않습니다."]  # fmt: skip
    if _has_kr(R):
        out.append("한국 종목의 가격·지표는 미국 달러로 환산해 계산했습니다. 환율이 오르내린 만큼 원화 기준 수익·변동성과 다를 수 있습니다.")
    for l in desc.get("limitations", []) or []:
        out.append(str(l))
    return out


# ───────────────────────── 문서 v2 블록 (라운드 4, 결정 R3: 요약 대시보드 + 접이식 7부분) ─────────────────────────
METRIC_SHORT_KO = {"return_12m_1m": "모멘텀", "vol_60d": "저변동성", "pe_ttm": "저PER", "roe_ttm": "퀄리티", "dividend_yield_ttm": "고배당"}
EVIDENCE_KIND_KO = {"news": "뉴스", "disclosure": "공시", "financial": "재무 지표", "calc": "계산값", "data_quality": "자료 품질"}


def evidence_ref(R, ids: list[str] | None, title: str) -> dict[str, Any]:
    """근거 색인을 본문에 복사하지 않고 참조만 둔다 (ids=None 이면 색인 전체). 화면은 출처 드로어에서 /evidence 로 연다."""
    idx = R["evidence_index"]
    chosen_ids = [i for i in ids if i in idx] if ids is not None else list(idx)
    kinds: dict[str, int] = {}
    for i in chosen_ids:
        k = idx[i]["kind"]
        kinds[k] = kinds.get(k, 0) + 1
    return {"type": "evidence_ref", "title_ko": title, "ids": chosen_ids if ids is not None else None, "count": len(chosen_ids), "kinds": kinds}


def weights_compare(R) -> dict[str, Any]:
    """규칙 4개 + 시작일 뉴스 뷰 BL 의 비중을 한 표로 (도넛 여러 개 대신)."""
    cols, rows_w, ex_ante = [], {}, {}
    sec = {t["ticker"]: t["sector"] for t in R["selection"]["table"]}
    names = {t["ticker"]: t["name"] for t in R["selection"]["table"]}
    for p in R["portfolio"]["baselines"]["portfolios"]:
        cols.append({"id": p["id"], "label_ko": NAMES.get(p["id"], p["id"]), "kind": "template", "rule_ko": p.get("rule_ko", "")})
        rows_w[p["id"]] = p["weights"]
        ex_ante[p["id"]] = {"vol": p.get("ex_ante", {}).get("vol"), "effective_n": p.get("ex_ante", {}).get("effective_n"), "cash": p.get("cash_weight", 0)}
    for p in R["portfolio"]["targets"]["portfolios"]:
        cols.append({"id": p["id"], "label_ko": f"뉴스 뷰: {p.get('title_ko') or p['name_ko']}", "kind": "black_litterman", "rule_ko": (p.get("portfolio_view") or "").split("\n")[0]})
        rows_w[p["id"]] = p["weights"]
        ex_ante[p["id"]] = {"vol": p.get("ex_ante", {}).get("vol"), "exp_return": p.get("ex_ante", {}).get("exp_return"), "cash": max(0.0, 1 - sum(p["weights"].values()))}
    tickers = sorted({t for w in rows_w.values() for t in w}, key=lambda t: -max(w.get(t, 0) for w in rows_w.values()))
    rows = [{"ticker": t, "name": names.get(t, t), "sector": sec.get(t, ""), "weights": {c["id"]: rows_w[c["id"]].get(t, 0.0) for c in cols}} for t in tickers]
    cash = {c["id"]: max(0.0, 1 - sum(rows_w[c["id"]].values())) for c in cols}
    base_id = R["portfolio"]["targets"]["baseline"]["id"]
    return {"type": "weights_compare", "title_ko": "비중 규칙별 구성 (백테스트 시작일)", "columns": cols, "rows": rows, "cash": cash, "ex_ante": ex_ante, "baseline_id": base_id,
            "note_ko": "규칙 4개는 기준 비중에 종목·섹터 상한을 적용한 값, 뉴스 뷰는 기준 비중을 Black-Litterman 으로 조정한 값입니다."}  # fmt: skip


def timeline(R, chosen) -> dict[str, Any] | None:
    """리밸런싱 시점별 한 줄: 평가금액·비교지수·구간 성과·거래 수 + (walk-forward 면) 그날의 뉴스·공시·뷰. 체크포인트 표·뷰 카드·walk-forward 표를 하나로."""
    p = find(R, chosen)
    cps = p.get("checkpoints") or []
    if not cps:
        return None
    wf = R["portfolio"].get("walkforward")
    base_id = p.get("base_id") or chosen
    bl = next((x for x in (wf or {}).get("portfolios", []) if x["id"] == base_id and x["kind"] == "black_litterman"), None)
    wf_base = None
    if wf:
        tmpl_id = "wf_" + R["portfolio"]["targets"]["baseline"]["id"]
        wf_base = next((x for x in wf["portfolios"] if x["id"] == tmpl_id), None)
    items = []
    for cp in cps:
        d = cp["date"]
        it = {"seq": cp["seq"], "date": d, "kind": cp["kind"], "n_trading_days_to_date": cp["n_trading_days_to_date"], "value_usd": cp["money"]["value_usd"],
              "benchmark_value_usd": cp["money"]["benchmark_value_usd"], "net_invested_usd": cp["money"]["net_invested_usd"],
              "since_last": ({k: cp["since_last"].get(k) for k in ("return", "benchmark_return", "excess", "max_drawdown")} if cp.get("since_last") else None),
              "n_trades": len(cp.get("trades") or []), "turnover": cp.get("turnover"), "commission_usd": cp.get("commission_usd"),
              "to_date": ({k: (cp["to_date"] or {}).get(k) for k in ("total_return", "cagr", "max_drawdown", "sharpe", "excess_cagr")} if cp.get("to_date") else None),
              "cash_after": cp["weights"].get("cash_after"), "news": None, "views": [], "top_delta": []}  # fmt: skip
        if bl is not None and d in (wf.get("news_summary") or {}):
            ns = wf["news_summary"][d]
            views = bl["views_by_date"].get(d, [])
            it["news"] = {"n_articles": ns.get("n_articles", 0), "n_disclosures": ns.get("n_disclosures", 0), "n_tickers_with_evidence": ns.get("n_tickers_with_evidence", ns.get("n_tickers_with_news", 0)),
                          "n_views": len(views), "fallback": d in (bl.get("fallback_dates") or []), "window": ns.get("window"), "disclosure_window": ns.get("disclosure_window")}  # fmt: skip
            it["views"] = [{"summary_ko": v.get("summary_ko", ""), "confidence": v.get("confidence"), "evidence_ids": v.get("evidence_ids", []), "evidence_type": v.get("evidence_type")} for v in views]
            if wf_base is not None and d in bl["weights_by_date"] and d in wf_base["weights_by_date"]:
                w, b = bl["weights_by_date"][d], wf_base["weights_by_date"][d]
                it["top_delta"] = [{"ticker": t, "delta": round(w[t] - b[t], 6)} for t in sorted((t for t in w if t in b), key=lambda t: -abs(w[t] - b[t]))[:3]]
        items.append(it)
    return {"type": "timeline", "title_ko": f"리밸런싱 타임라인 ({pf_label(p)})", "portfolio_id": chosen, "walkforward": bl is not None, "items": items,
            "note_ko": "시점을 고르면 그날의 보유 종목·거래·뷰를 자세히 볼 수 있습니다. 평가금액은 적립을 포함한 값입니다."}  # fmt: skip


def _paragraphs(text: str) -> list[str]:
    parts = [x.strip() for x in (text or "").split("\n\n") if x.strip()]
    return parts or ([text] if text else [])


def companies(R, chosen) -> dict[str, Any]:
    """선정 표 + 기업별 근거 카드를 하나로. 각 종목에 비중·순위·지표·근거 문단·인용 근거·뉴스/공시 수."""
    from backend.analysis.common.citations import CITE_RE

    p = find(R, chosen)
    weights = p.get("target_weights") or {}
    expl = {r["ticker"]: r for r in ((R["selection"].get("explained") or {}).get("per_ticker") or [])}
    idx = R["evidence_index"]
    by_ticker: dict[str, dict[str, int]] = {}
    for e in idx.values():
        if e["kind"] in ("news", "disclosure"):
            for t in e.get("tickers", []):
                by_ticker.setdefault(t, {"news": 0, "disclosure": 0})[e["kind"]] += 1
    items = []
    for t in R["selection"]["table"]:
        tk = t["ticker"]
        rat = (expl.get(tk) or {}).get("rationale_ko", "")
        cited = [c for c in CITE_RE.findall(rat) if c in idx]
        items.append({"ticker": tk, "name": t["name"], "market": t.get("market", ""), "sector": t["sector"], "sub_industry": t.get("sub_industry", ""), "summary": t.get("summary", ""),
                      "theme_reason_ko": t.get("theme_reason_ko") or "", "theme_confidence": t.get("theme_confidence"), "weight": weights.get(tk),
                      "in_selection_now": t["in_selection_now"], "rank_now": t["rank_now"], "metric_now": t["metric_now"], "in_backtest": t["in_backtest"],
                      "rank_bt": t["rank_backtest"], "metric_bt": t["metric_backtest"], "fact_id": t.get("metric_fact_id"),
                      "rationale_ko": _paragraphs(rat), "evidence_ids": list(dict.fromkeys(cited)),
                      "n_news": by_ticker.get(tk, {}).get("news", 0), "n_disclosures": by_ticker.get(tk, {}).get("disclosure", 0)})  # fmt: skip
    items.sort(key=lambda x: (x["weight"] is None, -(x["weight"] or 0), x["rank_now"] if x["rank_now"] is not None else 99))
    m = R["selection"]["metric"]
    return {"type": "companies", "title_ko": "선정 종목과 기업별 근거", "metric": m, "metric_ko": METRIC_SHORT_KO.get(m, m), "direction": R["selection"]["direction"],
            "as_of_now": R["selection"]["as_of_now"]["as_of"], "as_of_bt": R["selection"]["backtest_as_of"]["as_of"], "portfolio_id": chosen, "items": items,
            "note_ko": "비중은 선택안의 목표 비중입니다. 순위가 비어 있으면 그 기준일에는 선정되지 않은 종목입니다. 인용 ID 를 누르면 출처를 볼 수 있습니다."}  # fmt: skip


def build_summary(R, chosen: str, interp: dict[str, Any], narr: dict[str, Any]) -> dict[str, Any]:
    """'한눈에 보기' 대시보드 자료: 판단·KPI(비교지수 동반)·배분·미니 시계열·검증·다음 행동."""
    p = find(R, chosen)
    val = R["validation"]
    rec = val.get("recommended")
    res = next((r for r in val["results"] if r["id"] == chosen), None) or next((a for a in val.get("alternatives", []) if a["id"] == chosen), None)
    chosen_status = (res or {}).get("status", "n/a")
    failed = [f"{c['name_ko']}" for c in (res or {}).get("checks", []) if c["status"] == "fail"]
    warned = [f"{c['name_ko']}" for c in (res or {}).get("checks", []) if c["status"] == "warn"]
    info_notes = [c["message_ko"] for c in (res or {}).get("checks", []) if c["status"] == "info" and c.get("ok") is False]  # 투자 비율 낮음, 드리프트, 시장도 같이 빠진 낙폭 등
    rule_msgs = {c["rule"]: c["message_ko"] for c in (res or {}).get("checks", [])}
    vd = (rec or {}).get("verdict")
    if vd:  # 라운드 5: 추천은 항상 하나, 라벨은 주의 목록을 그대로 보여 준다
        status = vd["status"]
        label = f"{vd.get('head_ko') or VERDICT_HEAD_KO.get(status, '추천')}: {pf_label(p)}"
    elif rec and chosen_status == "pass":
        status, label = "recommended", f"추천: {pf_label(p)}"
    elif rec:
        status, label = "recommended_warn", f"추천 (주의 있음): {pf_label(p)}"
    elif p.get("kind") == "alternative":
        status, label = "none_cash_blend", f"추천 없음 · 현금 혼합안 ({pf_label(p)})"
    else:
        status, label = "none_baseline", f"추천 없음 · 기준 포트폴리오 ({pf_label(p)})"
    headline = (interp.get("headline_ko") or "").strip() or next((x for x in (narr.get("overview_ko") or []) if x.strip()), "")
    reason = rec["reason_ko"] if rec else next((n["message_ko"] for n in (R.get("notices") or []) if n.get("code") == "no_portfolio_passed"), None)
    bench = R["backtest"]["benchmark"]
    bh, bm = bench["headline"], bench["metrics"]
    r1c = next((c for c in (res or {}).get("checks", []) if c["rule"] == "R1"), None)
    r1 = ({"mdd": r1c["value"], "tolerance": r1c["threshold"], "benchmark_mdd": abs(bh["max_drawdown"] or 0.0), "excess": round(max(0.0, (r1c["value"] or 0) - (r1c["threshold"] or 0)), 6),
           "status": r1c["status"], "match_target": R["validation"]["criteria"].get("match_target")} if r1c else None)  # fmt: skip
    user_notices = [n["message_ko"] for n in (R.get("notices") or []) if n.get("level", "user") == "user"][:3]
    kp = kpis(R, chosen)
    bench_vals = {"final_value": bh["final_value_usd"], "cagr": (bm["return"]["total_return"] if not R["backtest"]["period"].get("annualized_reliable", True) else bh["cagr"]),
                  "excess": None, "mdd": bh["max_drawdown"], "sharpe": bh["sharpe"], "view_hit": None}  # fmt: skip
    kpi_items = [{**k, "benchmark_value": bench_vals.get(k["id"]), "benchmark_label_ko": bench["name_ko"] if bench_vals.get(k["id"]) is not None else None}
                 for k in kp if not (k["id"] == "view_hit" and k["value"] is None)]  # fmt: skip
    init = R["portfolio"]["backtest_spec"]["capital"]["initial_amount_usd"]
    names = {t["ticker"]: t["name"] for t in R["selection"]["table"]}
    sec = {t["ticker"]: t["sector"] for t in R["selection"]["table"]}
    f = R["portfolio"].get("forward")
    if f and (f.get("portfolios") or f.get("templates")):
        cur = f["portfolios"][0] if f["portfolios"] else next((t for t in f["templates"] if t["id"] == f["baseline"]["id"]), f["templates"][0])
        alloc_w, basis, basis_ko, a_init, fx = cur["weights"], "forward", f"분석 기준일 {f['as_of']} 구성 ({cur.get('name_ko', cur['id'])})", f["capital"]["initial_amount_usd"], f["capital"]["fx_rate"]
    else:
        alloc_w, basis, basis_ko, a_init, fx = p.get("target_weights") or {}, "backtest", f"백테스트 선택안 ({pf_label(p)})", init, R["money_krw"]["fx_rate"]
    items = [{"ticker": t, "name": names.get(t, t), "sector": sec.get(t, ""), "weight": w, "usd": round(a_init * w, 2), "krw": round(a_init * w * fx)} for t, w in sorted(alloc_w.items(), key=lambda x: -x[1]) if w > 1e-6]
    cash_w = max(0.0, 1 - sum(alloc_w.values()))
    return {"verdict": {"status": status, "label_ko": label, "headline_ko": headline, "reason_ko": reason, "chosen_portfolio_id": chosen, "chosen_label_ko": pf_label(p),
                        "cautions_ko": list((vd or {}).get("cautions_ko") or []), "period_note_ko": period_note(R), "notices_ko": user_notices,
                        "n_notices": len([n for n in (R.get("notices") or []) if n.get("level", "user") == "user"])},
            "validation": {"n_pass": val["summary"]["n_pass"], "n_warn": val["summary"]["n_warn"], "n_fail": val["summary"]["n_fail"], "n_candidates": val["summary"].get("n_candidates"),
                           "chosen_status": chosen_status, "failed_rules_ko": failed, "warned_rules_ko": warned, "info_notes_ko": info_notes,
                           "rules_ko": [{"rule": c["rule"], "name_ko": c["name_ko"], "level": c["level"], "status": c["status"], "message_ko": c["message_ko"]} for c in (res or {}).get("checks", []) if c["level"] != "info"],
                           "tolerance_note_ko": _tolerance_note(R), "r1_ko": rule_msgs.get("R1"), "r1": r1},
            "news_effect": news_effect(R),
            "kpis": kpi_items,
            "allocation": {"basis": basis, "basis_ko": basis_ko, "items": items, "cash_weight": cash_w, "initial_amount_usd": a_init, "fx_rate": fx, "fx_direction": f"1 USD = {fx:,.2f} KRW"},
            "mini_series": {"dataset": "index", "ids": list(dict.fromkeys([chosen, bench["id"]])), "label_ko": "누적 수익률 (시작 = 100)"},
            "period": R["backtest"]["period"], "next_actions_ko": list(interp.get("next_actions_ko") or [])}  # fmt: skip


def news_effect(R) -> dict[str, Any] | None:
    """뉴스 반영 효과 카드 재료 (라운드 5): wf_bl_news vs 같은 종목의 기준 비중(wf_<baseline>) — 추천이 다른 포트폴리오여도 보여 준다."""
    ports = {p["id"]: p for p in R["backtest"]["portfolios"]}
    bl = ports.get("wf_bl_news")
    if bl is None:
        enabled = bool((R["intent"].get("news_tilt") or {}).get("enabled"))
        return {"disabled": True, "reason_ko": "뉴스 반영 구성을 만들지 못했습니다" if enabled else "뉴스 반영을 끈 분석입니다 (프로필 설정)"}
    base_id = R["portfolio"]["targets"]["baseline"]["id"]
    base = ports.get(f"wf_{base_id}") or ports.get(base_id)
    views = bl.get("views_by_date") or {}
    n_views = sum(len(v or []) for v in views.values())
    n_dates = sum(1 for v in views.values() if v)
    bh = bl["headline"]
    return {"disabled": False, "bl_id": bl["id"], "bl_label_ko": pf_label(bl), "base_id": base["id"] if base else None, "base_label_ko": pf_label(base) if base else None,
            "bl_cagr": bh["cagr"], "base_cagr": base["headline"]["cagr"] if base else None, "diff_cagr": round((bh["cagr"] or 0) - (base["headline"]["cagr"] or 0), 6) if base else None,
            "bl_excess_cagr": bh["excess_cagr"], "base_excess_cagr": base["headline"]["excess_cagr"] if base else None,
            "bl_mdd": bh["max_drawdown"], "base_mdd": base["headline"]["max_drawdown"] if base else None,
            "hit_365": bh.get("view_hit_ratio"), "hit_next_rb": bh.get("view_hit_ratio_next_rb"), "n_views": n_views, "n_dates": n_dates,
            "n_rebalances": len(views), "n_fallback": len(bl.get("fallback_dates") or []), "annualized_reliable": R["backtest"]["period"].get("annualized_reliable", True)}  # fmt: skip


def period_note(R) -> str | None:
    """요청한 백테스트 기간과 실제 평가 창이 다르면(시작일 이동·자료 시작·시작 시 종목 부족) 결론 옆에 적는 한 줄 (라운드 5)."""
    import datetime as dt

    sp = R["portfolio"]["backtest_spec"]["period"]
    try:
        start, end = dt.date.fromisoformat(str(sp["start"])), dt.date.fromisoformat(str(sp["end"]))
    except (KeyError, ValueError):
        return None
    actual = (end - start).days / 365.25
    years_req = float(R["request"]["horizon"].get("backtest_years") or R["parameters"].get("backtest", {}).get("default_backtest_years") or 3.0)
    codes = ("backtest_start_shifted", "backtest_start_clamped", "fewer_holdings_at_start", "window_clamped")
    notes = [n["message_ko"] for n in (R.get("notices") or []) if n.get("code") in codes]
    if actual < years_req * 0.9 - 1e-9:
        return f"요청 {years_req:g}년 중 {actual:.1f}년만 평가했습니다 ({sp['start']} ~ {sp['end']})" + (f" — {notes[0]}" if notes else "")
    return notes[0] if notes else None


def sample_series(dates: list[str], series: dict[str, dict[str, Any]], max_points: int = 600, pin_id: str | None = None) -> tuple[list[str], dict[str, dict[str, Any]], dict[str, Any] | None]:
    """긴 시계열은 stride 로 줄이고 첫/끝 + 선택안 최대낙폭의 고점·저점은 고정한다. 전체 해상도는 /reports/{id}/series 로."""
    n = len(dates)
    if n <= max_points:
        return dates, series, None
    import math

    stride = math.ceil(n / max_points)
    keep = set(range(0, n, stride)) | {0, n - 1}
    pinned: list[str] = []
    s = series.get(pin_id or "", {})
    dd = s.get("drawdown")
    if dd and len(dd) == n:
        trough = min(range(n), key=lambda i: dd[i] if dd[i] is not None else 0)
        idx = s.get("index") or []
        peak = max(range(trough + 1), key=lambda i: idx[i] if i < len(idx) and idx[i] is not None else -1) if idx else 0
        keep |= {trough, peak}
        pinned = [dates[peak], dates[trough]]
    order = sorted(keep)
    out_series = {}
    for sid, ser in series.items():
        out_series[sid] = {k: ([v[i] for i in order] if isinstance(v, list) and len(v) == n else v) for k, v in ser.items()}
    return [dates[i] for i in order], out_series, {"method": "stride", "stride": stride, "full_points": n, "points": len(order), "pinned": pinned}
