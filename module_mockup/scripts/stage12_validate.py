"""
Stage 12: rule-based validation of backtest results against the user's criteria, a recommendation,
and a risk-fit alternative (cash blend that meets the drawdown tolerance).

in : output/11_backtest_results.json, 10_target_portfolios.json, 02_intent.json, 01_request.json
out: output/12_validation.json
Rules R1-R8 (hard -> fail, soft -> warn). Recommendation: no-fail portfolio with the highest Sharpe (tie: lower MDD).
"""
import argparse
import numpy as np, pandas as pd
from common import OUTPUT, load_json, dump_json
from descriptor import load_descriptor
import backtest_config as BC
import backtest_metrics as M
from schemas import Validation

STATUS_KO = {"pass": "통과", "warn": "주의", "fail": "미통과", "info": "참고"}


def check(rule, name, level, ok, value, threshold, msg):
    status = "info" if level == "info" else ("pass" if ok else ("fail" if level == "hard" else "warn"))
    return {"rule": rule, "name_ko": name, "level": level, "status": status, "value": value, "threshold": threshold, "message_ko": msg}


def evaluate_checks(p, crit, n_days, expected_rb, sector_of, short_window=False):
    """short_window: annualized-return / volatility rules become informational (level 'info')."""
    m, h = p["metrics"], p["headline"]; cks = []
    soft = "info" if short_window else "soft"
    mdd = abs(m["risk"]["max_drawdown"])
    cks.append(check("R1", "최대낙폭", "hard", mdd <= crit["max_drawdown"], mdd, crit["max_drawdown"], f"최대낙폭 {mdd:.1%} {'≤' if mdd <= crit['max_drawdown'] else '>'} 허용 {crit['max_drawdown']:.0%}"))
    cks.append(check("R2", "목표수익", soft, m["return"]["cagr"] >= crit["target_annual_return"], m["return"]["cagr"], crit["target_annual_return"],
                     f"CAGR {m['return']['cagr']:.1%} vs 목표 {crit['target_annual_return']:.0%}" + (f" (기간 수익률 {m['return']['total_return']:+.1%}; 창이 1년 미만이라 참고만)" if short_window else "")))
    ex = m["vs_benchmark"]["excess_cagr"] or 0.0
    cks.append(check("R3", "비교지수 대비", "soft", ex > 0, ex, 0.0, f"{crit['benchmark']} 대비 초과 CAGR {ex:+.1%}"))
    rb_cps = [cp for cp in p["checkpoints"] if cp["kind"] == "rebalance"] or p["checkpoints"][:1]
    rb_max = max(max(cp["weights"]["after"].values()) for cp in rb_cps)
    cks.append(check("R4", "종목 상한(리밸런싱일)", "hard", rb_max <= crit["max_weight_per_stock"] + 1e-3, rb_max, crit["max_weight_per_stock"], f"리밸런싱일 최대 종목 비중 {rb_max:.1%} vs 상한 {crit['max_weight_per_stock']:.0%}"))
    drift_ok = not any(b.startswith("stock_cap") for b in m["composition"]["breaches"])
    cks.append(check("R4b", "종목 상한(드리프트)", "soft", drift_ok, m["composition"]["max_weight_drift"], crit["max_weight_per_stock"] * (1 + BC.DRIFT_TOLERANCE),
                     "리밸런싱 사이 종목 비중 드리프트 " + ("허용 범위 안" if drift_ok else f"초과: {[b for b in m['composition']['breaches'] if b.startswith('stock_cap')]}")))
    sec_rb_max = 0.0
    for cp in rb_cps:
        sums = {}
        for t, w in cp["weights"]["after"].items(): sums[sector_of(t)] = sums.get(sector_of(t), 0.0) + w
        sec_rb_max = max(sec_rb_max, max(sums.values()))
    cks.append(check("R5", "섹터 상한(리밸런싱일)", "hard", sec_rb_max <= crit["max_weight_per_sector"] + 1e-3, sec_rb_max, crit["max_weight_per_sector"], f"리밸런싱일 최대 섹터 비중 {sec_rb_max:.1%} vs 상한 {crit['max_weight_per_sector']:.0%}"))
    sdrift_ok = not any(b.startswith("sector_cap") for b in m["composition"]["breaches"])
    cks.append(check("R5b", "섹터 상한(드리프트)", "soft", sdrift_ok, m["composition"]["max_sector_drift"], crit["max_weight_per_sector"] * (1 + BC.DRIFT_TOLERANCE), "리밸런싱 사이 섹터 드리프트 " + ("허용 범위 안" if sdrift_ok else "초과")))
    n_hold = sum(1 for w in p["target_weights"].values() if w > 1e-6)
    cks.append(check("R6", "종목 수", "hard", n_hold >= crit["min_holdings"], n_hold, crit["min_holdings"], f"보유 종목 {n_hold}개 vs 최소 {crit['min_holdings']}개"))
    vol = m["risk"]["ann_vol"]
    cks.append(check("R7", "변동성 적합", soft, vol <= crit["vol_band"], vol, crit["vol_band"], f"연변동성 {vol:.1%} vs 성향({crit['volatility_preference']}) 상한 {crit['vol_band']:.0%}" + (" (창이 1년 미만이라 참고만)" if short_window else "")))
    ok8 = all(len(v) == n_days for v in p["series"].values()) and m["trading"]["n_rebalances"] == expected_rb
    cks.append(check("R8", "데이터 무결성", "hard", ok8, float(len(p["series"]["index"])), float(n_days), f"시계열 {len(p['series']['index'])}일, 리밸런싱 {m['trading']['n_rebalances']}회"))
    n_fail = sum(c["status"] == "fail" for c in cks); n_warn = sum(c["status"] == "warn" for c in cks)
    return cks, ("fail" if n_fail else ("warn" if n_warn else "pass")), n_fail, n_warn


def row_of(p, status, extra=None):
    m, h = p["metrics"], p["headline"]
    return {"id": p["id"], "name_ko": p.get("name_ko", p["id"]), "kind": p["kind"], "cagr": m["return"]["cagr"], "ann_vol": m["risk"]["ann_vol"], "sharpe": h["sharpe"],
            "max_drawdown": m["risk"]["max_drawdown"], "final_value_usd": h["final_value_usd"], "irr_annual": p["money"]["irr_annual"],
            "excess_cagr": m["vs_benchmark"]["excess_cagr"] if p["kind"] != "benchmark" else 0.0, "view_hit_ratio": h["view_hit_ratio"], "status": status, **(extra or {})}


def cash_blend_ratio(index_values, tolerance):
    """Smallest cash ratio c in [0, 0.95] such that the max drawdown of (1-c)*r blended daily returns is within tolerance."""
    idx = pd.Series(index_values, dtype=float); r = idx.pct_change().fillna(0.0)
    def mdd(c): return float(M.drawdown_series((1 + (1 - c) * r).cumprod()).min())
    if mdd(0.0) >= -tolerance: return 0.0
    lo, hi = 0.0, 0.95
    for _ in range(40):
        mid = (lo + hi) / 2
        if mdd(mid) >= -tolerance: hi = mid
        else: lo = mid
    return round(hi + 0.005, 2)      # round up to a half-percent


def build_alternative(res, targets, chosen, crit, n_days, expected_rb, sector_of):
    import stage11_backtest as S11
    p = next(x for x in res["portfolios"] if x["id"] == chosen)
    c = cash_blend_ratio(p["series"]["index"], crit["max_drawdown"])
    if c <= 0: return None, "chosen portfolio already within the drawdown tolerance"
    ctx = S11.prepare(targets)
    bench_raw = S11.run_raw(ctx, f"benchmark_{ctx['bench']}", {ctx["bench"]: 1.0})
    base_raw = S11.run_raw(ctx, ctx["baseline_id"], next(t for t in targets["portfolios"] + targets["templates"] if t["id"] == ctx["baseline_id"])["weights"])
    weights = {t: round(w * (1 - c), 6) for t, w in p["target_weights"].items()}
    alt = {"id": f"cash_blend_{chosen}", "name_ko": f"현금 혼합안: {p.get('name_ko', chosen)} × {1 - c:.0%} + 현금 {c:.0%}", "weights": weights}
    raw = S11.run_raw(ctx, alt["id"], weights)
    block = S11.evaluate(ctx, alt, raw, "alternative", bench_raw, base_raw["index"])
    cks, status, n_fail, n_warn = evaluate_checks(block, crit, n_days, expected_rb, sector_of, not res["period"].get("annualized_reliable", True))
    block.update({"cash_ratio": c, "base_id": chosen, "checks": cks, "status": status, "n_fail": n_fail, "n_warn": n_warn,
                  "reason_ko": f"{p.get('name_ko', chosen)}의 과거 최대낙폭이 허용 {crit['max_drawdown']:.0%}를 넘어, 같은 종목 비중을 {1 - c:.0%}로 줄이고 {c:.0%}를 현금(수익 0 가정)으로 두었을 때의 결과입니다. "
                               f"실제 백테스트 최대낙폭 {block['headline']['max_drawdown']:.1%}, CAGR {block['headline']['cagr']:.1%}."})
    return block, None


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--results", default=str(OUTPUT / "11_backtest_results.json"))
    ap.add_argument("--targets", default=str(OUTPUT / "10_target_portfolios.json"))
    ap.add_argument("--out", default=str(OUTPUT / "12_validation.json"))
    ap.add_argument("--max-drawdown", type=float, default=None, help="override criteria (for testing the fail path)")
    ap.add_argument("--no-alternatives", action="store_true")
    a = ap.parse_args()
    res, intent, req, targets = load_json(a.results), load_json(OUTPUT / "02_intent.json"), load_json(OUTPUT / "01_request.json"), load_json(a.targets)
    vc, cons = intent["validation_criteria"], req["constraints"]
    crit = {"max_drawdown": a.max_drawdown if a.max_drawdown is not None else intent["risk_params"]["effective_max_drawdown"],
            "target_annual_return": vc["target_annual_return"], "benchmark": vc["benchmark"], "volatility_preference": intent["risk_params"]["volatility_preference"],
            "vol_band": BC.VOL_BANDS[intent["risk_params"]["volatility_preference"]], "max_weight_per_stock": cons["max_weight_per_stock"],
            "max_weight_per_sector": cons["max_weight_per_sector"], "min_holdings": cons["num_holdings"]["min"], "drift_tolerance": BC.DRIFT_TOLERANCE}
    n_days = res["period"]["trading_days"]; expected_rb = res["portfolios"][0]["metrics"]["trading"]["n_rebalances"]
    desc = load_descriptor(); sector_of = lambda t: desc["companies"][t]["gics"]["sector"]["name"] if t in desc["companies"] else t
    results, table, warnings = [], [], []
    short_window = not res["period"].get("annualized_reliable", True)
    if short_window: warnings.append(f"window of {n_days} trading days < 252: R2/R7 are informational only (annualized figures unreliable)")
    for p in res["portfolios"]:
        cks, status, n_fail, n_warn = evaluate_checks(p, crit, n_days, expected_rb, sector_of, short_window)
        results.append({"id": p["id"], "kind": p["kind"], "status": status, "checks": cks, "n_fail": n_fail, "n_warn": n_warn})
        table.append(row_of(p, status, {"n_fail": n_fail, "n_warn": n_warn}))
    for b in res.get("benchmarks", [res["benchmark"]]):
        table.append(row_of(b, "n/a", {"n_fail": 0, "n_warn": 0}))

    eligible = [t for t in table if t["status"] in ("pass", "warn")]
    base = next(t for t in table if t["id"] == targets["baseline"]["id"])
    recommended = None
    if eligible:
        best = sorted(eligible, key=lambda t: (-(t["sharpe"] or -9), -t["max_drawdown"]))[0]
        recommended = {"id": best["id"], "status": best["status"],
                       "reason_ko": f"검증 실패 없는 포트폴리오 중 Sharpe 최고({best['sharpe']:.2f}). CAGR {best['cagr']:.1%}, 최대낙폭 {best['max_drawdown']:.1%}, 최종 평가금액 {best['final_value_usd']:,.0f} USD.",
                       "vs_baseline": {"cagr_diff": round(best["cagr"] - base["cagr"], 6), "mdd_diff": round(best["max_drawdown"] - base["max_drawdown"], 6), "sharpe_diff": round((best["sharpe"] or 0) - (base["sharpe"] or 0), 6)}}
    else:
        fails = {}
        for r in results:
            for c in r["checks"]:
                if c["status"] == "fail": fails[c["rule"]] = fails.get(c["rule"], 0) + 1
        warnings.append(f"no portfolio passed the hard rules (fail counts by rule: {fails}); recommended=null")

    # ── risk-fit alternative: cash blend of the chosen portfolio ──
    alternatives = []
    chosen = recommended["id"] if recommended else targets["baseline"]["id"]
    if not a.no_alternatives:
        alt, note = build_alternative(res, targets, chosen, crit, n_days, expected_rb, sector_of)
        if alt:
            alternatives.append(alt); table.append(row_of(alt, alt["status"], {"n_fail": alt["n_fail"], "n_warn": alt["n_warn"], "cash_ratio": alt["cash_ratio"]}))
        elif note: warnings.append(f"alternative skipped: {note}")
    infeas = targets["backtest_spec"]["selection"].get("infeasibility")
    summary = {"n_pass": sum(r["status"] == "pass" for r in results), "n_warn": sum(r["status"] == "warn" for r in results), "n_fail": sum(r["status"] == "fail" for r in results)}
    out = Validation(request_id=res["request_id"], criteria={**crit, "chosen_for_alternative": chosen, "selection_infeasibility": infeas}, results=results, comparison_table=table,
                     recommended=recommended, alternatives=alternatives, summary=summary, warnings=warnings)
    dump_json(out.model_dump(mode="json"), a.out)
    print(f"[stage12] ok -> {a.out}\n         criteria: MDD≤{crit['max_drawdown']:.0%} CAGR≥{crit['target_annual_return']:.0%} vol≤{crit['vol_band']:.0%} | summary={summary}")
    for r in results:
        bad = [f"{c['rule']}:{c['status']}" for c in r["checks"] if c["status"] != "pass"]
        print(f"         {r['id']:<20} {r['status']:<5} {bad}")
    print("         recommended:", recommended["id"] if recommended else None, "|", (recommended or {}).get("reason_ko", warnings))
    for alt in alternatives:
        print(f"         alternative {alt['id']}: cash {alt['cash_ratio']:.0%} -> MDD {alt['headline']['max_drawdown']:.1%} CAGR {alt['headline']['cagr']:.1%} status={alt['status']}")
    if infeas: print(f"         selection infeasibility: target {infeas['target']} -> max feasible {infeas['max_feasible_n']} (cap needed {infeas['cap_needed_for_target']})")


if __name__ == "__main__":
    main()
