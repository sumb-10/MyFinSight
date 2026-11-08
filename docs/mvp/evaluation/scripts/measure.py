"""프로토타입 평가 지표 (시나리오 100개의 QA 마지막 실행 기준).

항목 1 자료 수집 성공률, 항목 2 사용자 조건 반영률, 항목 4 전략 생성 유효성, 항목 7 완료율·응답 시간,
요구사항 근거(R2 질문, R7 리포트 12항목, R8 인용, R9 단계 기록, R15 선견) 를 한 번에 계산한다.

  PYTHONPATH=. python docs/mvp/evaluation/scripts/measure.py <qa_final_runs.txt> <audit_dir> <out.json>
"""

from __future__ import annotations

import json
import os
import re
import statistics
import sys
from collections import Counter, defaultdict
from pathlib import Path

sys.path.insert(0, str(Path.cwd()))
from backend.analysis.eval.grade import conditions_metrics, evidence_metrics, execution_metrics, load_run, report_metrics  # noqa: E402
from backend.analysis.schemas.request import TEMPLATE_METRICS  # noqa: E402
from backend.analysis.settings import AnalysisSettings  # noqa: E402

ROOT = Path.cwd()
STORE = ROOT / "data" / "analysis_store" / "requests"
RUNS_DIR = Path(os.environ.get("EVAL_RUNS_DIR") or ROOT / "docs" / "mvp" / "scenario_qa" / "runs")  # 다시 돌린 실행은 EVAL_RUNS_DIR 로 가리킨다
SET = AnalysisSettings.load()
EPS = 1e-6


def jload(p: Path):
    return json.loads(p.read_text(encoding="utf-8")) if p.exists() else None


def get(d, path, default=None):
    cur = d
    for k in path.split("."):
        if not isinstance(cur, dict) or k not in cur:
            return default
        cur = cur[k]
    return cur


def norm(v):
    """조건 값 비교용: 정수·실수를 같은 값으로, None 은 False 로 (allow_* 플래그)."""
    if v is None or isinstance(v, bool):
        return bool(v)
    if isinstance(v, (int, float)):
        return round(float(v), 9)
    if isinstance(v, list):
        return [norm(x) for x in v]
    if isinstance(v, dict):
        return {k: norm(x) for k, x in sorted(v.items())}
    return v


THEME_KEYS = {"weapons": ["weapon", "defense", "무기", "방산"], "alcohol": ["alcohol", "주류"], "tobacco": ["tobacco", "담배"],
              "gambling": ["gambl", "casino", "도박", "카지노"], "adult_entertainment": ["adult", "성인"], "fossil_fuels": ["fossil", "화석", "석유", "석탄"]}


def theme_rules_ok(requested: list[str], rules: list[dict]) -> bool:
    """요청한 제외 테마마다 규칙이 하나 이상 (LLM 이 붙인 이름이 'weapons_and_defense'·'무기·방산' 처럼 달라도 같은 테마로 본다)."""
    texts = [(str(r.get("theme", "")) + " " + " ".join(r.get("keywords") or [])).lower() for r in rules if r.get("gics_codes") or r.get("keywords")]
    return all(any(any(k in tx for k in THEME_KEYS.get(t, [t.lower()])) for tx in texts) for t in requested)


def audit_checks(audit_dir: Path, name: str) -> dict[str, bool]:
    md = (audit_dir / f"{name}.md").read_text(encoding="utf-8")
    sec = md.split("## 규칙 검사", 1)[1] if "## 규칙 검사" in md else ""
    out = {}
    for ln in sec.splitlines():
        m = re.match(r"- (✅|❌) (.+?)(?: — .*)?$", ln.strip())
        if m:
            out[m.group(2).strip()] = m.group(1) == "✅"
    return out


def audit_has(checks: dict[str, bool], prefix: str) -> bool | None:
    hits = [v for k, v in checks.items() if k.startswith(prefix)]
    return all(hits) if hits else None


def answered_fields(doc: dict) -> set[str]:
    out: set[str] = set()
    for q in doc.get("questions") or []:
        if not q.get("answered_at"):
            continue
        out.add(q["field"])
        opt = next((o for o in q.get("options") or [] if o.get("label_ko") == q.get("answer")), None)
        for k in (opt or {}).get("patch") or {}:
            if not str(k).startswith("_"):
                out.add(k)
    return out


def all_weight_sets(run: dict) -> list[tuple[str, dict[str, float]]]:
    """사용자에게 쓰이는 모든 목표 비중: 시작일 규칙·BL(10), 날짜별(10w), 분석 기준일 현재 구성(10f)."""
    sets = []
    t = run["10_target_portfolios"] or {}
    for p in (t.get("templates") or []) + (t.get("portfolios") or []):
        sets.append((f"10:{p['id']}", p["weights"]))
    w = run["10w_target_paths"] or {}
    for p in w.get("portfolios") or []:
        for d, ws in (p.get("weights_by_date") or {}).items():
            sets.append((f"10w:{p['id']}@{d}", ws))
    f = run["10f_forward_portfolios"] or {}
    for p in (f.get("templates") or []) + (f.get("portfolios") or []):
        sets.append((f"10f:{p['id']}", p["weights"]))
    return sets


def sector_map(run: dict) -> dict[str, str]:
    m = {}
    for row in get(run["13_results"] or {}, "selection.table", []) or []:
        if row.get("sector"):
            m[row["ticker"]] = row["sector"]
    for s in (run["05_selection"] or {}).get("selected", []):
        if s.get("sector"):
            m.setdefault(s["ticker"], s["sector"])
    for row in get(run["07_backtest_spec"] or {}, "selection.table", []) or []:
        if row.get("sector"):
            m.setdefault(row["ticker"], row["sector"])
    return m


def weight_checks(run: dict, cons: dict) -> dict[str, list[str]]:
    secs = sector_map(run)
    cap_s = float(cons.get("max_weight_per_stock") or 1.0)
    cap_g = float(cons.get("max_weight_per_sector") or 1.0)
    min_cash = float(cons.get("min_cash_ratio") or 0.0)
    excl = set(cons.get("exclude_tickers") or [])
    bad = defaultdict(list)
    for label, ws in all_weight_sets(run):
        ws = {k: float(v) for k, v in ws.items() if abs(float(v)) > 0}
        tot = sum(ws.values())
        if any(v < -EPS for v in ws.values()) or tot > 1 + 1e-4:
            bad["no_leverage_short"].append(label)
        if ws and max(ws.values()) > cap_s + 1e-4:
            bad["max_weight_per_stock"].append(f"{label} {max(ws.values()):.4f}>{cap_s}")
        by = defaultdict(float)
        for k, v in ws.items():
            by[secs.get(k, "?" + k)] += v
        if by and max(by.values()) > cap_g + 1e-4:
            bad["max_weight_per_sector"].append(f"{label} {max(by.values()):.4f}>{cap_g}")
        if 1 - tot < min_cash - 1e-4:
            bad["min_cash_ratio"].append(f"{label} cash {1 - tot:.4f}<{min_cash}")
        if excl & set(ws):
            bad["exclude_tickers"].append(f"{label} {sorted(excl & set(ws))}")
    return bad


def conditions(name: str, run: dict, scen: dict, doc: dict, checks: dict[str, bool]) -> list[dict]:
    """시나리오에 미리 적힌 사용자 조건마다: 시나리오 값, 확정 값, 실제 결과 반영 여부, 대화 답으로 바뀌었는지."""
    eff = run["01_request"] or {}
    sc, ec = scen["constraints"], eff.get("constraints", {})
    ans = answered_fields(doc or {})
    cm = conditions_metrics(run, scen)
    val = run["12_validation"] or {}
    crit = val.get("criteria") or {}
    bt = run["11_backtest_results"] or {}
    spec = run["07_backtest_spec"] or {}
    mm = run["08_market_model"] or {}
    sel = run["05_selection"] or {}
    tg = run["10_target_portfolios"] or {}
    der = eff.get("derived") or {}
    wbad = weight_checks(run, ec)
    out = []

    def add(cid, label, scen_v, eff_v, ok, field, note=""):
        changed = json.dumps(norm(scen_v), sort_keys=True, default=str) != json.dumps(norm(eff_v), sort_keys=True, default=str)
        consent = changed and (field in ans or any(a.startswith(field) for a in ans))
        out.append({"id": cid, "label": label, "scenario": scen_v, "effective": eff_v, "reflected": bool(ok), "changed": changed, "consented": consent, "note": note})

    add("universe", "시장(유니버스)", sc["universe"], ec.get("universe"), cm["universe"]["ok"], "constraints.universe")
    if sc.get("exclude_tickers"):
        add("exclude_tickers", "제외 종목", sc["exclude_tickers"], ec.get("exclude_tickers"),
            cm["exclude_tickers"]["ok"] and not wbad.get("exclude_tickers") and audit_has(checks, "제외 종목") is not False, "constraints.exclude_tickers")
    if sc.get("exclude_sectors"):
        add("exclude_sectors", "제외 섹터", sc["exclude_sectors"], ec.get("exclude_sectors"),
            audit_has(checks, "제외 섹터 종목 없음") is not False and audit_has(checks, "제외 섹터 이름") is not False, "constraints.exclude_sectors")
    if sc.get("exclude_themes"):
        add("exclude_themes", "제외 테마", sc["exclude_themes"], ec.get("exclude_themes"),
            theme_rules_ok(ec.get("exclude_themes") or [], (run["02_intent"] or {}).get("exclude_theme_rules") or []), "constraints.exclude_themes")
    if sc.get("must_include_tickers"):
        add("must_include", "필수 포함 종목", sc["must_include_tickers"], ec.get("must_include_tickers"), audit_has(checks, "필수 포함") is not False, "constraints.must_include_tickers")
    nh = ec.get("num_holdings") or {}
    n_sel = len(sel.get("selected", []))
    add("num_holdings", "종목 수", sc["num_holdings"], nh, (nh.get("min", 0) or 0) <= n_sel <= (nh.get("max") or 10**9) and audit_has(checks, "종목 수 최소~최대") is not False,
        "constraints.num_holdings", f"선정 {n_sel}")
    add("max_weight_per_stock", "종목당 상한", sc["max_weight_per_stock"], ec.get("max_weight_per_stock"), not wbad.get("max_weight_per_stock"), "constraints.max_weight_per_stock",
        "; ".join(wbad.get("max_weight_per_stock", [])[:2]))
    add("max_weight_per_sector", "섹터당 상한", sc["max_weight_per_sector"], ec.get("max_weight_per_sector"), not wbad.get("max_weight_per_sector"), "constraints.max_weight_per_sector",
        "; ".join(wbad.get("max_weight_per_sector", [])[:2]))
    add("min_cash_ratio", "최소 현금", sc["min_cash_ratio"], ec.get("min_cash_ratio"), not wbad.get("min_cash_ratio"), "constraints.min_cash_ratio",
        "; ".join(wbad.get("min_cash_ratio", [])[:2]))
    add("no_leverage_short", "레버리지·공매도 금지", [bool(sc.get("allow_leverage")), bool(sc.get("allow_short"))], [bool(ec.get("allow_leverage")), bool(ec.get("allow_short"))],
        not wbad.get("no_leverage_short"), "constraints.allow_leverage")
    rr = spec.get("rebalance_rule") or {}
    want = ec.get("rebalance") or {}
    add("rebalance", "리밸런싱 주기", sc["rebalance"], want, rr.get("unit") == want.get("unit") and int(rr.get("count") or 0) == int(want.get("count") or 0), "constraints.rebalance",
        rr.get("description_ko", ""))
    if sc.get("min_market_cap_usd"):
        add("min_market_cap", "최소 시가총액", sc["min_market_cap_usd"], ec.get("min_market_cap_usd"), audit_has(checks, "최소 시가총액") is not False, "constraints.min_market_cap_usd")
    r_s, r_e = scen["risk"], eff.get("risk", {})
    bench_id = get(bt, "benchmark.id") or ""
    add("benchmark", "비교지수", r_s["benchmark"], r_e.get("benchmark"), bench_id == f"benchmark_{r_e.get('benchmark')}", "risk.benchmark", bench_id)
    add("max_drawdown_tolerance", "허용 낙폭", r_s["max_drawdown_tolerance"], r_e.get("max_drawdown_tolerance"),
        abs(float(crit.get("input_max_drawdown") or -1) - float(r_e.get("max_drawdown_tolerance") or -2)) < EPS and audit_has(checks, "낙폭 초과면 라벨에 주의") is not False,
        "risk.max_drawdown_tolerance")
    add("target_annual_return", "목표 수익률", r_s["target_annual_return"], r_e.get("target_annual_return"),
        abs(float(crit.get("target_annual_return") or -1) - float(r_e.get("target_annual_return") or -2)) < EPS, "risk.target_annual_return")
    mult_want = SET.portfolio.risk_aversion_mult.get(r_e.get("risk_tolerance"))
    add("risk_tolerance", "위험 성향", r_s["risk_tolerance"], r_e.get("risk_tolerance"),
        mm.get("delta_multiplier") is not None and mult_want is not None and abs(float(mm["delta_multiplier"]) - float(mult_want)) < EPS and audit_has(checks, "성향 문구") is not False,
        "risk.risk_tolerance", f"δ 배수 {mm.get('delta_multiplier')} (기대 {mult_want})")
    h_s, h_e = scen["horizon"], eff.get("horizon", {})
    add("target_years", "투자기간", h_s["target_years"], h_e.get("target_years"), abs(float(crit.get("horizon_years") or -1) - float(h_e.get("target_years") or -2)) < EPS, "horizon.target_years")
    as_of = str(der.get("as_of") or "")
    want_d = str(h_s.get("start_date") or "")[:10]
    add("as_of", "분석 기준일", want_d, str(h_e.get("start_date") or "")[:10], bool(as_of) and as_of <= want_d and cm["as_of"]["ok"], "horizon.start_date", f"사용 {as_of}")
    sp_s, sp_e = scen["strategy_preference"], eff.get("strategy_preference", {})
    metric_want = TEMPLATE_METRICS.get(sp_e.get("template"), (None,))[0]
    add("template", "선정 기준(전략)", sp_s["template"], sp_e.get("template"), (sel.get("summary") or {}).get("metric") == metric_want, "strategy_preference.template",
        f"지표 {(sel.get('summary') or {}).get('metric')}")
    add("baseline_weighting", "기준 비중 방식", sp_s["baseline_weighting"], sp_e.get("baseline_weighting"),
        get(tg, "baseline.id") == sp_e.get("baseline_weighting") and audit_has(checks, "기준 비중") is not False, "strategy_preference.baseline_weighting")
    news_on = bool(sp_e.get("use_news_tilt"))
    has_bl = bool(tg.get("portfolios")) or any(p.get("kind") == "black_litterman" for p in (run["10w_target_paths"] or {}).get("portfolios", [])) or bool((run["10f_forward_portfolios"] or {}).get("portfolios"))
    omitted = get(run["10w_target_paths"] or {}, "bl_omitted.reason_ko") or (run["10f_forward_portfolios"] or {}).get("fallback_reason_ko")
    news_ok = (not has_bl and audit_has(checks, "뉴스 끔이면 BL 없음") is not False) if not news_on else (has_bl or bool(omitted))
    add("use_news_tilt", "뉴스 반영 여부", sp_s["use_news_tilt"], sp_e.get("use_news_tilt"), news_ok, "strategy_preference.use_news_tilt",
        ("" if has_bl or not news_on else f"자료 부족 공지: {omitted}") if news_ok else "뉴스 켬인데 BL 구성 없음")
    cap_s, cap_e = scen["capital"], eff.get("capital", {})
    money = (bt.get("portfolios") or [{}])[0].get("money") or {}
    cfx = get(bt, "engine.capital_fx") or {}
    rate = float(cfx.get("fx_rate") or 0) if cap_e.get("currency") == "KRW" else 1.0
    want_init = (float(cap_e.get("initial_amount") or 0) / rate) if rate else None
    ok_init = want_init is not None and abs(float(money.get("initial_usd") or 0) - float(want_init)) <= max(1.0, 0.005 * float(want_init))
    add("initial_amount", "초기 투자금·통화", [cap_s["initial_amount"], cap_s["currency"]], [cap_e.get("initial_amount"), cap_e.get("currency")], ok_init, "capital.initial_amount",
        f"백테스트 {money.get('initial_usd')} USD vs 기대 {want_init} (환율 {cfx.get('fx_rate')} @ {cfx.get('fx_date')})")
    eng = bt.get("engine") or {}
    want_c = (float(cap_e.get("monthly_contribution") or 0) / rate) if rate else 0.0
    if float(cap_s.get("monthly_contribution") or 0) > 0:
        ok_c = int(eng.get("n_contributions") or 0) > 0 and abs(float(eng.get("contribution_usd") or 0) - float(want_c)) <= max(1.0, 0.005 * float(want_c))
    else:
        ok_c = int(eng.get("n_contributions") or 0) == 0
    add("monthly_contribution", "월 적립", cap_s["monthly_contribution"], cap_e.get("monthly_contribution"), ok_c, "capital.monthly_contribution",
        f"적립 {eng.get('n_contributions')}회 × {eng.get('contribution_usd')} USD (기대 {want_c})")
    return out


def data_items(run: dict, rec: dict) -> dict:
    """항목 1: 필수 자료 단위별 (필요, 수집) — 가격·비교지수·환율·선정 지표·시가총액·뉴스."""
    out = {}
    R = run["13_results"] or {}
    dq = R.get("data_quality") or {}
    usable = int(dq.get("usable") or 0)
    excluded = dq.get("excluded") or {}
    out["price"] = (usable + len(excluded), usable, sorted(excluded)[:5])
    bt = run["11_backtest_results"] or {}
    td = get(bt, "period.trading_days")
    benches = bt.get("benchmarks") or []
    out["benchmark"] = (len(benches), sum(1 for b in benches if len(get(b, "series.index", []) or []) == td), [])
    eff = run["01_request"] or {}
    der = eff.get("derived") or {}
    if (eff.get("capital") or {}).get("currency") == "KRW" or any(str(t).endswith(".KS") for t in get(run["07_backtest_spec"] or {}, "selection.tickers", []) or []):
        need = 2
        got = int(bool(der.get("fx_rate"))) + int(bool(der.get("backtest_fx_rate")))
        out["fx"] = (need, got, [])
    sel = run["05_selection"] or {}
    n_tag = int(get(sel, "summary.n_tagged") or 0)
    miss = [r for r in sel.get("rejected", []) if str(r.get("reason", "")).startswith("metric_missing")]
    out["metric"] = (n_tag, n_tag - len(miss), [r["ticker"] for r in miss][:5])
    st = (run["03_candidates"] or {}).get("stats") or {}
    mcap_missing = int((st.get("by_filter") or {}).get("market_cap_missing", 0))
    n_match = int(st.get("n_matched") or 0)
    if (eff.get("constraints") or {}).get("min_market_cap_usd"):
        out["market_cap"] = (n_match, n_match - mcap_missing, [])
    if get(eff, "strategy_preference.use_news_tilt"):
        ns = (run["10w_target_paths"] or {}).get("news_summary") or {}
        out["news"] = (len(ns), sum(1 for x in ns.values() if (x.get("n_articles") or 0) + (x.get("n_disclosures") or 0) > 0), [])
        out["news_enough"] = (len(ns), sum(1 for x in ns.values() if x.get("enough")), [])
    return out


def validity(run: dict, rec: dict) -> dict:
    """항목 4: 유효하고 실행 가능한 전략인가."""
    spec = run["07_backtest_spec"] or {}
    tg = run["10_target_portfolios"] or {}
    par = tg.get("parameters") or {}
    eff = run["01_request"] or {}
    bt = run["11_backtest_results"] or {}
    val = run["12_validation"] or {}
    crit = val.get("criteria") or {}
    cap_stock = par.get("max_weight_per_stock", crit.get("max_weight_per_stock"))
    cap_sector = par.get("max_weight_per_sector", crit.get("max_weight_per_sector"))
    min_cash = par.get("min_cash_ratio", crit.get("min_cash_ratio"))
    spec9 = {
        "기간": bool(get(spec, "period.start")) and bool(get(spec, "period.end")),
        "자본": bool(spec.get("capital")),
        "리밸런싱": bool(get(spec, "rebalance_rule.unit")),
        "비교지수": bool(spec.get("benchmark")),
        "선정 종목": bool(get(spec, "selection.tickers")),
        "체결 규칙": bool(spec.get("execution_rule")),
        "상한": cap_stock is not None and cap_sector is not None,
        "현금": min_cash is not None,
        "뉴스 반영": get(eff, "strategy_preference.use_news_tilt") is not None,
    }
    integ = [c["status"] for r in val.get("results", []) + val.get("alternatives", []) for c in r.get("integrity", [])]
    cands = [p for p in bt.get("portfolios", [])]
    checks = {
        "실행 완료(리포트 있음)": rec.get("status") in ("success", "partial") and bool(rec.get("report")),
        "명세 9항목": all(spec9.values()),
        "후보 3개 이상 백테스트": len(cands) >= 3,
        "모든 후보 무결성 통과": bool(integ) and all(s == "pass" for s in integ),
        "추천 구성 있음": bool(val.get("chosen_id")),
    }
    return {"ok": all(checks.values()), "checks": checks, "spec9": spec9, "n_candidates": len(cands), "n_integrity": len(integ)}


def first_run(name: str) -> dict | None:
    hist = sorted((RUNS_DIR / "history").glob(f"{name}__*.json"))
    recs = [jload(h) for h in hist] + [jload(RUNS_DIR / f"{name}.json")]
    recs = [r for r in recs if r and r.get("status") not in (None, "skipped")]
    firsts = [r for r in recs if not r.get("replay_of")]
    if not firsts:
        return None
    firsts.sort(key=lambda r: str(r.get("run_id") or r.get("request_id") or ""))
    return firsts[0]


def main() -> int:
    runs_txt, audit_dir, out_p = sys.argv[1], Path(sys.argv[2]), Path(sys.argv[3])
    pairs = [ln.split() for ln in Path(runs_txt).read_text().splitlines() if ln.strip()]
    per = []
    for name, rid in pairs:
        rec = jload(RUNS_DIR / f"{name}.json")
        scen = jload(Path(rec["scenario_file"]))
        run = load_run(rid)
        run["08_market_model"] = jload(ROOT / "output" / rid / "08_market_model.json")
        doc = run["request_doc"] or jload(STORE / f"{rec['request_id']}.json") or {}
        checks = audit_checks(audit_dir, name)
        conds = conditions(name, run, scen, doc, checks)
        ev = evidence_metrics(run)
        rp = report_metrics(run)
        ex = execution_metrics(run)
        fr = first_run(name)
        per.append({
            "name": name, "run_id": rid, "status": rec.get("status"), "replay_of": rec.get("replay_of"),
            "audit": {"n": len(checks), "fail": [k for k, v in checks.items() if not v]},
            "conditions": conds, "data": data_items(run, rec), "validity": validity(run, rec),
            "dialog": {"n_q": len(rec.get("qa") or []), "fields": [q.get("field") for q in rec.get("qa") or []], "max": doc.get("max_questions"),
                       "turn_seconds": [q.get("turn_seconds") for q in rec.get("qa") or [] if q.get("turn_seconds") is not None],
                       "dialog_seconds": rec.get("dialog_seconds")},
            "evidence": {k: ev[k] for k in ("after_as_of", "cited_unique", "missing_citations", "window_records_after_end", "price_series_within_as_of", "index_by_kind")},
            "report": {"present": rp.get("present"), "items_12_ok": rp.get("items_12_ok"), "seven_ok": rp.get("seven_ok"), "gate_errors": rp.get("gate_errors"),
                       "number_notes": rp.get("number_notes"), "dev_term_notes": rp.get("dev_term_notes")},
            "execution": {"steps_fully_recorded": ex["steps_fully_recorded"], "elapsed_s": ex["elapsed_s"], "llm_cost_usd": ex["llm_cost_usd"], "sources": ex["sources"]},
            "first_run": {"run_id": fr.get("run_id"), "status": fr.get("status"), "error": json.dumps(fr.get("error"), ensure_ascii=False)[:200] if fr.get("error") else "", "run_seconds": fr.get("run_seconds"),
                          "dialog_seconds": fr.get("dialog_seconds"), "cost": fr.get("cost_total_usd")} if fr else None,
        })
    # ── 집계
    agg: dict = {}
    allc = [c for p in per for c in p["conditions"]]
    agg["conditions"] = {
        "n": len(allc), "reflected": sum(c["reflected"] for c in allc),
        "strict_same_and_reflected": sum(c["reflected"] and not c["changed"] for c in allc),
        "changed": sum(c["changed"] for c in allc), "changed_consented": sum(c["changed"] and c["consented"] for c in allc),
        "by_id": {k: {"n": sum(1 for c in allc if c["id"] == k), "reflected": sum(1 for c in allc if c["id"] == k and c["reflected"]),
                      "changed": sum(1 for c in allc if c["id"] == k and c["changed"]), "consented": sum(1 for c in allc if c["id"] == k and c["changed"] and c["consented"])}
                  for k in dict.fromkeys(c["id"] for c in allc)},
        "not_reflected": [(p["name"], c["id"], c["note"]) for p in per for c in p["conditions"] if not c["reflected"]],
        "changed_no_consent": [(p["name"], c["id"], c["scenario"], c["effective"]) for p in per for c in p["conditions"] if c["changed"] and not c["consented"]],
        "scenarios_all_reflected": sum(1 for p in per if all(c["reflected"] for c in p["conditions"])),
    }
    data = defaultdict(lambda: [0, 0, 0, []])
    for p in per:
        for k, (need, got, ex_) in p["data"].items():
            data[k][0] += need
            data[k][1] += got
            data[k][2] += int(got == need)
            if got < need and len(data[k][3]) < 12:
                data[k][3].append((p["name"], need - got, ex_))
    agg["data"] = {k: {"need": v[0], "got": v[1], "rate": round(v[1] / v[0], 6) if v[0] else None, "runs_complete": v[2],
                       "runs": sum(1 for p in per if k in p["data"]), "examples": v[3]} for k, v in data.items()}
    agg["validity"] = {"ok": sum(p["validity"]["ok"] for p in per), "n": len(per),
                       "by_check": {k: sum(p["validity"]["checks"][k] for p in per) for k in per[0]["validity"]["checks"]},
                       "failed": [(p["name"], [k for k, v in p["validity"]["checks"].items() if not v]) for p in per if not p["validity"]["ok"]]}
    st = Counter(p["status"] for p in per)
    fr_st = Counter((p["first_run"] or {}).get("status") for p in per)
    agg["completion"] = {"final": dict(st), "first": dict(fr_st),
                         "first_failed": [(p["name"], p["first_run"]["status"], p["first_run"]["error"]) for p in per if p["first_run"] and p["first_run"]["status"] not in ("success", "partial")]}
    turns = [t for p in per for t in p["dialog"]["turn_seconds"]]
    fr_runs = [p["first_run"]["run_seconds"] for p in per if p["first_run"] and p["first_run"].get("run_seconds")]
    fr_dlg = [p["first_run"]["dialog_seconds"] for p in per if p["first_run"] and p["first_run"].get("dialog_seconds")]
    q = lambda xs, f: round(sorted(xs)[min(len(xs) - 1, int(f * len(xs)))], 1) if xs else None
    agg["timing"] = {"turn_seconds": {"n": len(turns), "median": q(turns, .5), "p90": q(turns, .9), "max": max(turns) if turns else None},
                     "first_run_seconds": {"n": len(fr_runs), "median": q(fr_runs, .5), "p90": q(fr_runs, .9), "max": max(fr_runs) if fr_runs else None},
                     "first_dialog_seconds": {"n": len(fr_dlg), "median": q(fr_dlg, .5), "p90": q(fr_dlg, .9), "max": max(fr_dlg) if fr_dlg else None},
                     "first_cost": round(sum(float(p["first_run"].get("cost") or 0) for p in per if p["first_run"]), 3)}
    nq = [p["dialog"]["n_q"] for p in per]
    agg["dialog"] = {"n_q_dist": dict(Counter(nq)), "max_q": max(nq), "over_5": sum(1 for x in nq if x > 5),
                     "repeat_field": [(p["name"], f) for p in per for f, c in Counter(p["dialog"]["fields"]).items() if c > 1],
                     "fields": dict(Counter(f for p in per for f in p["dialog"]["fields"]).most_common())}
    agg["report"] = {"present": sum(1 for p in per if p["report"]["present"]), "items12_full": sum(1 for p in per if p["report"]["items_12_ok"] == 12),
                     "seven_ok": sum(1 for p in per if p["report"]["seven_ok"]), "gate_errors": sum(len(p["report"]["gate_errors"] or []) for p in per),
                     "number_notes": sum(p["report"]["number_notes"] or 0 for p in per), "dev_term_notes": sum(p["report"]["dev_term_notes"] or 0 for p in per)}
    agg["evidence"] = {"after_as_of": sum(len(p["evidence"]["after_as_of"]) for p in per), "missing_citations": sum(len(p["evidence"]["missing_citations"]) for p in per),
                       "cited_unique": sum(p["evidence"]["cited_unique"] for p in per), "window_after_end": sum(p["evidence"]["window_records_after_end"] for p in per),
                       "price_within_as_of": sum(1 for p in per if p["evidence"]["price_series_within_as_of"])}
    agg["steps"] = {"fully_recorded_runs": sum(1 for p in per if p["execution"]["steps_fully_recorded"].split("/")[0] == p["execution"]["steps_fully_recorded"].split("/")[1]),
                    "examples": [p["execution"]["steps_fully_recorded"] for p in per][:3]}
    agg["audit"] = {"checks": sum(p["audit"]["n"] for p in per), "fail": sum(len(p["audit"]["fail"]) for p in per)}
    out_p.write_text(json.dumps({"agg": agg, "per": per}, ensure_ascii=False, indent=1, default=str), encoding="utf-8")
    print(json.dumps(agg, ensure_ascii=False, indent=1, default=str)[:6000])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
