"""
MVP scenario report (markdown) from one run's outputs.

  python scripts/mvp_report.py --run-id run_x --scenario docs/mvp/parts/x.scenario.md [--analysis docs/mvp/parts/x.analysis.md] --out docs/mvp/x.md

Numbers come only from output/<run_id>/{13_results.json,14_report.json,run_meta.json,llm_cost_report.json};
the scenario description and the interpretation are hand-written markdown parts that are pasted in verbatim.
"""
import argparse, json, os, sys
from pathlib import Path

if "--run-id" in sys.argv:
    os.environ["MYFINSIGHT_RUN_ID"] = sys.argv[sys.argv.index("--run-id") + 1]
from common import ROOT, OUTPUT, RUN_ID, load_json


def pct(x, d=1, sign=False):
    if x is None: return "–"
    return f"{x:+.{d}%}" if sign else f"{x:.{d}%}"


def usd(x): return "–" if x is None else f"${x:,.0f}"
def krw(x): return "–" if x is None else f"{x:,.0f}원"
def num(x, d=2): return "–" if x is None else f"{x:.{d}f}"
def opt(p): return load_json(p) if Path(p).exists() else None


def table(headers, rows):
    out = ["| " + " | ".join(headers) + " |", "| " + " | ".join("---" for _ in headers) + " |"]
    out += ["| " + " | ".join("" if c is None else str(c) for c in r) + " |" for r in rows]
    return "\n".join(out)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--run-id", required=True); ap.add_argument("--scenario", required=True); ap.add_argument("--analysis", default=None); ap.add_argument("--out", required=True)
    a = ap.parse_args()
    R = load_json(OUTPUT / "13_results.json"); D = opt(OUTPUT / "14_report.json"); meta = opt(OUTPUT / "run_meta.json") or {}; cost = opt(OUTPUT / "llm_cost_report.json") or {}
    L = []; w = L.append
    w(Path(a.scenario).read_text(encoding="utf-8").rstrip() + "\n")

    # ── 실행 정보 ──
    ds = R["parameters"].get("data_source") or {}
    pr = ds.get("prices") or {}
    w("## 실행 정보\n")
    rows = [("run id", f"`{RUN_ID}`"), ("실행 시각", f"{meta.get('started_at', '–')} → {meta.get('finished_at', '–')} ({meta.get('status', '–')})"),
            ("입력", f"`{meta.get('request_file', '–')}`, `{meta.get('backtest_file', '–')}`"),
            ("LLM", f"{R['llm_usage'].get('model', '–')} · 호출 {cost.get('total', {}).get('calls', '–')}회 · 비용 ${cost.get('total', {}).get('cost_usd', 0):.4f}"),
            ("데이터 원천", f"{ds.get('db', '–')} · 가격 {pr.get('n_tickers', '–')}종목 {pr.get('date_min', '–')}~{pr.get('date_max', '–')} ({pr.get('rows', 0):,}행, 소스 {pr.get('rows_by_source', {})}) · 환율 {ds.get('fx', {}).get('date_min', '–')}~{ds.get('fx', {}).get('date_max', '–')} · 발행주식수 DB {ds.get('shares', {}).get('from_db', '–')} / 캐시 {ds.get('shares', {}).get('from_yfinance_cache', '–')} · 비교지수 {ds.get('benchmarks', {}).get('source', '–')}"),
            ("산출물", f"`module_mockup/output/{RUN_ID}/` (단계 JSON, inputs/, prompts/, llm_raw/) · 노트북 `module_mockup/notebooks/{RUN_ID}.ipynb`"),
            ("코드", f"git `{meta.get('git_commit', '–')}` · 파이프라인 {R.get('pipeline_version', '–')}")]
    w(table(["항목", "값"], rows) + "\n")

    # ── 1. 의도 해석 ──
    I = R["intent"]; it = I["interpretation"]
    w("## 1. 의도 해석 (LLM #1)\n"); w(f"> {it['summary_ko']}\n")
    w(table(["테마", "GICS 코드", "키워드(일부)", "예시 종목"], [(f"**{t['label_ko']}** (`{t['id']}`)", ", ".join(t["gics_codes"]) or "–", ", ".join(t["keywords"][:6]), ", ".join(t.get("example_tickers", [])[:6]) or "–") for t in it["themes"]]) + "\n")
    sc, rp, nt, vc = I["screen"], I["risk_params"], I["news_tilt"], I["validation_criteria"]
    w(f"- 스크린: 템플릿 `{sc['template']}` → 지표 `{sc['metric']}` ({'낮은 순' if sc['direction']=='asc' else '높은 순'}), 기준일 {sc['as_of']}, 선정 {sc['select_top_n']}개, 테마 신뢰도 하한 {sc['theme_filter'].get('min_confidence')}")
    w(f"- 위험 파라미터: 성향 `{rp['risk_tolerance']}`, 실효 허용 낙폭 {pct(rp['effective_max_drawdown'], 0)}, 변동성 선호 `{rp['volatility_preference']}`" + (f" — {rp['notes_ko']}" if rp.get("notes_ko") else ""))
    w(f"- 뉴스 틸트: {'사용' if nt['enabled'] else '미사용'}, 뷰 신뢰도 상한 {nt['max_view_confidence']}, 종목당 최대 조정폭 {pct(nt['max_tilt_per_stock'], 1)}")
    w(f"- 검증 기준: 비교지수 {vc['benchmark']}, 허용 낙폭 {pct(vc['max_drawdown'], 0)}, 목표 연수익률 {pct(vc['target_annual_return'], 0)}, 기간 {vc['horizon_years']}년")
    if I.get("exclude_theme_rules"): w("- 제외 테마 규칙: " + "; ".join(f"`{r['theme']}` (코드 {len(r.get('gics_codes', []))}개, 키워드 {len(r.get('keywords', []))}개)" for r in I["exclude_theme_rules"]))
    if it.get("conflicts"): w("- 상충 항목: " + "; ".join(f"{c['field']}: {c['issue_ko']} → {c['resolution_ko']}" for c in it["conflicts"]))
    if it.get("style_hints"): w("- 스타일 힌트: " + ", ".join(it["style_hints"]))
    w("")

    # ── 2. 종목 선정 ──
    S = R["selection"]
    w("## 2. 종목 선정\n")
    w(table(["단계", "종목 수"], [(f["label_ko"], f["count"]) for f in S["funnel"]]) + "\n")
    cs = S.get("candidates_summary", {})
    w(f"- 후보 매칭 규칙: {cs.get('by_rule', {})} · 제외 사유: {cs.get('by_filter', {})} · 분류 통과 {S.get('tagging_summary', {}).get('n_passed', '–')}/{S.get('tagging_summary', {}).get('n_tagged', '–')}\n")
    cur = S["as_of_2026"]
    w(f"**기준일 {cur['as_of']} 선정 (현재 구성용)** — 지표 `{S['metric']}` {'낮은 순' if S['direction']=='asc' else '높은 순'}\n")
    w(table(["#", "티커", "회사", "섹터", "지표값", "테마 신뢰도"], [(s["rank"], s["ticker"], s["name"], s["sector"], num(s["metric_value"], 3), num(s.get("theme_confidence"), 2)) for s in cur["selected"]]) + "\n")
    bt_sel = S.get("backtest_as_of")
    if bt_sel:
        w(f"**백테스트 시작일 {bt_sel['as_of']} 재선정** ({bt_sel['source']})\n")
        w(table(["#", "티커", "회사", "섹터", "지표값"], [(s["rank"], s["ticker"], s["name"], s["sector"], num(s["metric_value"], 3)) for s in bt_sel["table"]]) + "\n")
        dv = bt_sel.get("diff_vs_original") or {}
        w("- 기준일 선정과의 차이: " + "; ".join(f"{k} {', '.join(v) if v else '없음'}" for k, v in dv.items()) + "\n")
    for key, lab in (("infeasibility", "실현 불가 사유"), ("sector_overflow", "섹터 상한 초과")):
        if cur.get(key): w(f"- {lab}: {json.dumps(cur[key], ensure_ascii=False)[:400]}")
        if bt_sel and bt_sel.get(key): w(f"- 재선정 {lab}: {json.dumps(bt_sel[key], ensure_ascii=False)[:400]}")
    if cur.get("warnings"): w("- 선정 경고: " + "; ".join(cur["warnings"]))
    w("")

    # ── 3. 구성 ──
    P = R["portfolio"]; mm = P["market_model"]; base = P["baselines"]; tg = P["targets"]
    w(f"## 3. 포트폴리오 구성 (백테스트 시작일 {mm['as_of']} 기준)\n")
    lb = mm.get("lookback", {}); sh = mm.get("shrinkage", {})
    w(f"- 시장모형: 추정 창 {lb.get('start', '–')}~{lb.get('end', '–')} ({lb.get('days', '–')}거래일), 수축 {sh.get('method', '–')} α={num(sh.get('alpha'), 3)}, 위험회피 δ={mm['delta']}, τ={mm['tau']}, 기준 비중 `{mm['baseline_id']}`")
    for n in mm.get("notes", []): w(f"  - {n}")
    tmpl = {p["id"]: p for p in base["portfolios"]}
    tk = mm["tickers"]; ids = [i for i in ("equal_weight", "market_cap", "inverse_volatility", "min_variance") if i in tmpl]
    w("\n**템플릿 비중** (연변동성은 추정 창 기준)\n")
    w(table(["티커", "연변동성", *[tmpl[i]["name_ko"] for i in ids]], [(t, pct(mm["ann_vol"].get(t), 1), *[pct(tmpl[i]["weights"].get(t, 0), 1) for i in ids]) for t in tk]) + "\n")
    w(table(["템플릿", "기대수익(사전)", "변동성(사전)", "유효 종목 수", "적용 제약"], [(tmpl[i]["name_ko"], pct(tmpl[i]["ex_ante"]["exp_return"], 1), pct(tmpl[i]["ex_ante"]["vol"], 1), num(tmpl[i]["ex_ante"]["effective_n"], 1), ", ".join(tmpl[i].get("constraints_applied", [])) or "–") for i in ids]) + "\n")
    w(f"**Black-Litterman 시나리오** (뷰는 LLM #4, 정적: 뉴스 미연결 `hindsight_risk={P['views'].get('hindsight_risk')}`, 신뢰도 상한 {P['views'].get('max_view_confidence')})\n")
    for p in tg["portfolios"]:
        dv = p.get("delta_vs_baseline", {}); top = sorted(dv.items(), key=lambda x: -abs(x[1]))[:4]
        w(f"- **{p['name_ko']}** — 최대 조정 {pct(max((abs(v) for v in dv.values()), default=0), 1)}p ({', '.join(f'{t} {v:+.1%}' for t, v in top)}); 사전 기대수익 {pct(p['ex_ante']['exp_return'], 1)}, 변동성 {pct(p['ex_ante']['vol'], 1)}")
        for v in p.get("views_applied", []): w(f"  - {v['summary_ko']}")
    w("")

    # ── 4. 백테스트 ──
    B = R["backtest"]; per, eng = B["period"], B["engine"]
    pf_all = [*B.get("benchmarks", [B["benchmark"]]), *B["portfolios"], *R["validation"].get("alternatives", [])]
    n_rb = B["portfolios"][0]["metrics"]["trading"]["n_rebalances"]
    w("## 4. 백테스트\n")
    w(f"- 기간 {per['start']} ~ {per['end']} ({per['trading_days']}거래일, 연환산 {'신뢰' if per.get('annualized_reliable') else '참고용(1년 미만)'}), 리밸런싱 {eng['rebalance_rule']['description_ko']} → {n_rb}회, 적립 {eng.get('n_contributions', 0)}회 × {usd(eng.get('contribution_usd'))}, 수수료 {eng['commission_bps']}bp, 무위험수익률 {pct(eng['risk_free_rate'], 0)}, 비교지수 {', '.join(eng.get('benchmarks', []))}")
    cfx = eng.get("capital_fx") or {}
    w(f"- 초기자본 {usd(B['portfolios'][0]['money']['initial_usd'])} (요청 {krw(R['money_krw'].get('initial_amount_krw'))}, 시작일 환율 1 USD = {cfx.get('fx_rate', 0):,.2f} KRW)" if cfx.get("currency") == "KRW" else f"- 초기자본 {usd(B['portfolios'][0]['money']['initial_usd'])}")
    w("")
    def row(p):
        h, m = p["headline"], p["metrics"]
        return (p.get("name_ko") or p["id"], p.get("kind", ""), pct(h["cagr"]), pct(h["period_return"]), pct(m["risk"]["ann_vol"]), num(h["sharpe"]), pct(h["max_drawdown"]), pct(h.get("excess_cagr"), 1, True), usd(h["final_value_usd"]), pct(p["money"].get("irr_annual")))
    w(table(["포트폴리오", "종류", "CAGR", "기간 수익률", "변동성", "Sharpe", "최대낙폭", "SPY 대비", "최종 평가액", "XIRR"], [row(p) for p in pf_all]) + "\n")
    chosen = (D or {}).get("header", {}).get("chosen_portfolio_id") or (R["validation"].get("recommended") or {}).get("id") or tg["baseline"]["id"]
    cp = next((p for p in B["portfolios"] if p["id"] == chosen), B["portfolios"][0]); spy = B["benchmark"]
    m = cp["metrics"]; mi = m["risk"]["mdd"]; mo = cp["money"]
    w(f"**선택 포트폴리오 `{cp['id']}` ({cp.get('name_ko')}) 상세**\n")
    years = sorted(set(cp["yearly_returns"]) | set(spy["yearly_returns"]))
    w(table(["연도", *years], [("포트폴리오", *[pct(cp["yearly_returns"].get(y), 1, True) for y in years]), (f"{spy['id']}", *[pct(spy["yearly_returns"].get(y), 1, True) for y in years])]) + "\n")
    w(f"- 최대낙폭 {pct(m['risk']['max_drawdown'])}: 고점 {mi.get('peak_date')} → 저점 {mi.get('trough_date')} → 회복 {mi.get('recovery_date') or '기간 내 미회복'}; 최악의 달 {pct(m['return']['worst_month'])}, 최고의 달 {pct(m['return']['best_month'])}; Sortino {num(m['risk_adjusted'].get('sortino'))}, Calmar {num(m['risk_adjusted'].get('calmar'))}, 베타 {num(m['vs_benchmark'].get('beta'))}")
    kr = R["money_krw"]["by_portfolio"].get(cp["id"], {})
    w(f"- 자금: 납입 원금 {usd(mo['net_invested_usd'])} (초기 {usd(mo['initial_usd'])} + 적립 {usd(mo['contributions_usd'])}) → 최종 {usd(mo['final_value_usd'])}, 이익 {usd(mo['profit_usd'])}, XIRR {pct(mo.get('irr_annual'))}; 원화 환산(요청일 환율) 최종 {krw(kr.get('final_value_krw'))}, 이익 {krw(kr.get('profit_krw'))}; 최대 평가손실 {usd(mo.get('max_loss_usd'))}")
    tc = {k: v for k, v in cp.get("ticker_contribution", {}).items() if v is not None}
    if tc:
        top = sorted(tc.items(), key=lambda x: -x[1])[:3]; bot = sorted(tc.items(), key=lambda x: x[1])[:3]
        w(f"- 종목별 기여: 상위 {', '.join(f'{t} {v:+.1%}' for t, v in top)} / 하위 {', '.join(f'{t} {v:+.1%}' for t, v in bot)}")
    comp = m.get("composition", {}); trd = m.get("trading", {})
    w(f"- 구성·거래: 유효 종목 수 {num(comp.get('effective_n'), 1)}, 최대 비중 드리프트 {pct(comp.get('max_weight_drift'))}, 평균 회전율 {pct(trd.get('turnover_avg'))}, 수수료 합계 {usd(trd.get('commissions_usd'))}")
    hits = [(p["name_ko"], p["headline"].get("view_hit_ratio")) for p in B["portfolios"] if p["kind"] == "black_litterman" and p["headline"].get("view_hit_ratio") is not None]
    if hits: w("- 시나리오 뷰 적중률(12개월 실현 vs 기대 방향): " + ", ".join(f"{n} {pct(h, 0)}" for n, h in hits))
    w("")

    # ── 5. 검증 ──
    V = R["validation"]; cr = V["criteria"]
    w("## 5. 검증\n")
    w(f"- 기준: 최대낙폭 ≤ {pct(cr['max_drawdown'], 0)}, 목표 CAGR ≥ {pct(cr['target_annual_return'], 0)}, 비교지수 {cr['benchmark']}, 변동성 밴드 ≤ {pct(cr['vol_band'], 0)} ({cr['volatility_preference']}), 종목 상한 {pct(cr['max_weight_per_stock'], 0)}, 섹터 상한 {pct(cr['max_weight_per_sector'], 0)}, 최소 종목 {cr['min_holdings']}개")
    res = next((r for r in V["results"] if r["id"] == chosen), V["results"][0])
    w(f"\n**`{res['id']}` 규칙 판정** (전체 {V['summary']})\n")
    lv = {"hard": "필수", "soft": "권장", "info": "참고"}; st = {"pass": "통과", "warn": "주의", "fail": "미통과", "info": "참고"}
    w(table(["규칙", "항목", "수준", "판정", "측정"], [(c["rule"], c["name_ko"], lv.get(c["level"], c["level"]), st.get(c["status"], c["status"]), c["message_ko"]) for c in res["checks"]]) + "\n")
    w("- 포트폴리오별 판정: " + ", ".join(f"{r['id']} {st.get(r['status'], r['status'])}" + (f"({'·'.join(c['rule'] for c in r['checks'] if c['status'] in ('fail', 'warn'))})" if r['status'] != 'pass' else "") for r in V["results"]))
    rec = V.get("recommended")
    w(f"- 추천: **{rec['id']}** — {rec['reason_ko']}" if rec else "- 추천: **없음** (필수 규칙을 통과한 포트폴리오가 없음)")
    for alt in V.get("alternatives", []):
        w(f"- 대안 **{alt['name_ko']}**: 현금 {pct(alt['cash_ratio'], 0)} 혼합 → CAGR {pct(alt['headline']['cagr'])}, 최대낙폭 {pct(alt['headline']['max_drawdown'])}, 최종 {usd(alt['headline']['final_value_usd'])}, 판정 {st.get(alt['status'], alt['status'])} ({', '.join(c['rule'] + ':' + c['status'] for c in alt['checks'] if c['status'] != 'pass') or '전부 통과'}) — {alt.get('reason_ko', '')}")
    w("")

    # ── 6. 뉴스 반영 ──
    ne, wf, fw = P.get("news_evidence"), P.get("walkforward"), P.get("forward")
    w("## 6. 뉴스 반영 (walk-forward · 현재 구성)\n")
    if ne:
        wins = ne["windows"]; wf_w = {d: x for d, x in wins.items() if x.get("kind") == "walkforward"}; ok = {d: x for d, x in wf_w.items() if x.get("enough")}
        w(f"- 근거 창: 리밸런싱 {len(wf_w)}개 시점 중 뉴스가 충분한 시점 {len(ok)}개" + (" — " + "; ".join(f"{d}: 기사 {x['n_articles']}건, 종목 {x['n_tickers_with_news']}/{len(x['tickers'])}" for d, x in ok.items()) if ok else "") + f"; 근거 레코드 {len(ne.get('all_evidence', {}))}건 (DB 헤드라인)")
    if wf:
        bl = next((p for p in wf["portfolios"] if p["kind"] == "black_litterman"), None)
        if bl:
            vb = {d: v for d, v in bl["views_by_date"].items() if v}
            w(f"- walk-forward BL: 리밸런싱 {len(wf['dates'])}회 중 뉴스 뷰 적용 {len(vb)}회, 기준 비중 fallback {len(bl['fallback_dates'])}회 (뉴스 부족 시 플레이스홀더 뷰 없음)")
            for d, views in vb.items():
                w(f"  - {d} 뷰 {len(views)}개:"); [w(f"    - {v.get('summary_ko') or v.get('rationale_ko', '')} 근거 {', '.join(v.get('evidence_ids', []))}") for v in views]
            wb = next((p for p in B["portfolios"] if p["id"] == bl["id"]), None); wt = next((p for p in B["portfolios"] if p["id"] == "wf_" + mm["baseline_id"]), None)
            if wb and wt: w(f"- 성과: `{wb['id']}` CAGR {pct(wb['headline']['cagr'])} / MDD {pct(wb['headline']['max_drawdown'])} vs 날짜별 재추정 기준 `{wt['id']}` {pct(wt['headline']['cagr'])} / {pct(wt['headline']['max_drawdown'])} vs 정적 기준 `{mm['baseline_id']}` {pct(next(p for p in B['portfolios'] if p['id'] == mm['baseline_id'])['headline']['cagr'])}")
    else:
        w("- walk-forward: 사용하지 않음")
    if fw:
        fwin = (ne or {}).get("windows", {}).get(fw["as_of"], {})
        nw = fw.get("news_window") or {}; nwin = nw.get("window") if isinstance(nw, dict) else nw
        w(f"\n**현재 구성 ({fw['as_of']} 기준, 백테스트 없음)** — 뉴스 창 {' ~ '.join(nwin) if isinstance(nwin, list) else nwin}, 기사 {fwin.get('n_articles', '–')}건, 뉴스 있는 종목 {fwin.get('n_tickers_with_news', '–')}/{len(fwin.get('tickers', {})) or '–'}\n")
        for p in fw["portfolios"]:
            if p.get("kind") != "black_litterman": continue
            top = sorted(p["weights"].items(), key=lambda x: -x[1])[:5]; dv = p.get("delta_vs_baseline", {})
            w(f"- **{p['name_ko']}** — 상위 비중 {', '.join(f'{t} {v:.1%}' for t, v in top)}; 최대 조정 {pct(max((abs(v) for v in dv.values()), default=0), 1)}p")
            for v in p.get("views_applied", []): w(f"  - {v['summary_ko']} 근거 {', '.join(v.get('evidence_ids', []))}")
    w("")

    # ── 7. 리포트 ──
    if D:
        h, asmt = D["header"], D["assessment"]
        w("## 7. 리포트 문서 (LLM #5a 해석 · #5b 서술)\n")
        w(f"- 제목: {h['title_ko']}\n- 선택 포트폴리오: `{h['chosen_portfolio_id']}` ({h['chosen_label_ko']}) — {h['chosen_note_ko']}\n- 섹션 {len(D['sections'])}개: {', '.join(s['title_ko'] for s in D['sections'])}\n- 해석기 자체 평가: 의도 적합 {asmt.get('intent_fit')}, 논리 일관성 {asmt.get('logic_consistency')}")
        for c in asmt.get("comments_ko", []): w(f"  - {c}")
        w(f"- 숫자 대조·금지 표현 경고: {len(D.get('warnings', []))}건" + (" — " + "; ".join(D["warnings"][:5]) if D.get("warnings") else ""))
        w("")

    # ── 8. 해석 ──
    if a.analysis and Path(a.analysis).exists():
        w(Path(a.analysis).read_text(encoding="utf-8").rstrip() + "\n")

    # ── 9. 경고 ──
    w("## 경고 목록 (파이프라인)\n")
    w(table(["단계", "내용"], [(x["stage"], x["message"]) for x in R.get("warnings", [])]) + "\n" if R.get("warnings") else "- 없음\n")
    out = Path(a.out); out.parent.mkdir(parents=True, exist_ok=True); out.write_text("\n".join(L), encoding="utf-8")
    print(f"[mvp_report] {out} ({len(L)} blocks)")


if __name__ == "__main__":
    main()
