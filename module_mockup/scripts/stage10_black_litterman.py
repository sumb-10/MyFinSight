"""
Stage 10: Black-Litterman target portfolios, one per view set. Output feeds the backtest stage.

in : output/08_market_model.json, 08_baseline_portfolios.json, 09_views.json, 07_backtest_spec.json, 01_request.json, 02_intent.json
out: output/10_target_portfolios.json
"""
import argparse, datetime as dt
import numpy as np
from common import OUTPUT, load_json, dump_json
from descriptor import load_descriptor
import portfolio as P
import portfolio_config as PC
from schemas import TargetPortfolios, Portfolio


def view_summary(v):
    legs = "+".join(v["long"]) + (f" > {'+'.join(v['short'])}" if v["short"] else "")
    kind = "상대" if v["type"] == "relative" else "절대"
    return f"[{kind}] {legs} {v['expected_return_annual']:+.0%}/년 (신뢰 {v['confidence']:.2f}) — {v['rationale_ko']}"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default=str(OUTPUT / "10_target_portfolios.json"))
    a = ap.parse_args()
    mm, base, views, spec, req, intent = (load_json(OUTPUT / f) for f in
        ["08_market_model.json", "08_baseline_portfolios.json", "09_views.json", "07_backtest_spec.json", "01_request.json", "02_intent.json"])
    desc = load_descriptor()
    tk = mm["tickers"]; n = len(tk)
    cov = np.array(mm["cov"]); pi = np.array([mm["implied_returns"][t] for t in tk])
    delta, tau = mm["delta"], mm["tau"]
    cons = req["constraints"]
    total = 1.0 - cons["min_cash_ratio"]
    max_stock, max_sector = cons["max_weight_per_stock"], cons["max_weight_per_sector"]
    max_tilt = intent["news_tilt"]["max_tilt_per_stock"]
    sec_code = [desc["companies"][t]["gics"]["sector"]["code"] for t in tk]
    sec_name = [desc["companies"][t]["gics"]["sector"]["name"] for t in tk]
    bp = next(p for p in base["portfolios"] if p["id"] == base["chosen_baseline"])
    wb = np.array([bp["weights"][t] for t in tk])
    warnings, notes = [], [
        "타겟 비중은 구성일(as_of) 기준 정적이며 리밸런싱마다 같은 비중으로 복귀한다. 실제 서비스에서는 리밸런싱 시점마다 뷰를 재생성해야 한다.",
        "뷰는 LLM 플레이스홀더(뉴스 데이터 미연결)이며 기준일 이후 정보가 섞였을 수 있다(hindsight_risk).",
        f"BL prior = 베이스라인({base['chosen_baseline']}) 비중의 역최적화 수익률. 뷰 신뢰도가 0 에 가까우면 베이스라인으로 수렴.",
        f"종목별 비중 이동 한도 |w - w_baseline| ≤ {max_tilt} (news_tilt.max_tilt_per_stock).",
    ]
    if not intent["news_tilt"]["enabled"]:
        warnings.append("news_tilt.enabled is false in the intent spec; BL targets computed anyway for comparison")

    sec_names = {c: nm for c, nm in zip(sec_code, sec_name)}

    def label(x):
        if ":" not in x: return x
        kind, val = x.split(":", 1)
        if kind == "upper": return f"tilt_or_stock_cap:{tk[int(val)]}"
        if kind == "lower": return f"tilt_floor:{tk[int(val)]}"
        if kind == "sector_cap": return f"sector_cap:{sec_names.get(val, val)}"
        return x

    ports = []
    for k, s in enumerate(views["sets"], 1):
        Pm, Q, C = P.build_PQ(s["views"], tk)
        mu, cov_bl = P.black_litterman(cov, pi, Pm, Q, C, tau)
        w, active = P.optimize_utility(mu, cov_bl, delta, wb, max_stock, max_sector, sec_code, max_tilt, total)
        active = [label(x) for x in active]
        d = w - wb
        pv = s["narrative_ko"] + "\n" + "\n".join("- " + view_summary(v) for v in s["views"])
        ports.append(Portfolio(
            id=f"bl_{k:02d}", kind="black_litterman", name_ko=f"BL 타겟 {k}: {s['title_ko']}", rule_ko="Black-Litterman (베이스라인 prior + 시나리오 뷰)",
            scenario_id=s["scenario_id"], title_ko=s["title_ko"], portfolio_view=pv,
            views_applied=[{"summary_ko": view_summary(v), "type": v["type"], "long": v["long"], "short": v["short"],
                            "expected_return_annual": v["expected_return_annual"], "confidence": v["confidence"]} for v in s["views"]],
            weights={t: round(float(x), 6) for t, x in zip(tk, w)}, cash_weight=round(1 - float(w.sum()), 6),
            delta_vs_baseline={t: round(float(x), 6) for t, x in zip(tk, d)},
            posterior_returns={t: round(float(x), 6) for t, x in zip(tk, mu)},
            ex_ante=P.ex_ante_stats(w, mu, cov_bl), sector_weights=P.sector_weights(w, sec_name), active_constraints=active))
        print(f"         {ports[-1].id} {s['title_ko']:<14} exp_ret={ports[-1].ex_ante.exp_return:+.3f} vol={ports[-1].ex_ante.vol:.3f} "
              f"max|Δ|={np.abs(d).max():.3f} top Δ: " + ", ".join(f"{tk[i]}{d[i]:+.3f}" for i in np.argsort(-np.abs(d))[:4]) + f" active={active[:4]}")

    templates = [Portfolio(**p) for p in base["portfolios"]]
    out = TargetPortfolios(request_id=spec["request_id"], as_of=dt.date.fromisoformat(mm["as_of"]),
                           backtest_spec={k: spec[k] for k in ["period", "capital", "rebalance_rule", "benchmark", "selection"]},
                           parameters={"tau": tau, "delta": delta, "omega_method": PC.OMEGA_METHOD, "lookback_days": PC.LOOKBACK_DAYS,
                                       "max_tilt_per_stock": max_tilt, "shrinkage": mm["shrinkage"], "max_weight_per_stock": max_stock,
                                       "max_weight_per_sector": max_sector, "min_cash_ratio": cons["min_cash_ratio"]},
                           baseline={"id": base["chosen_baseline"], "weights": bp["weights"]},
                           portfolios=ports, templates=templates, notes_ko=notes, warnings=warnings)
    dump_json(out.model_dump(mode="json"), a.out)
    print(f"[stage10] ok -> {a.out}\n         {len(ports)} BL portfolios + {len(templates)} templates; as_of={mm['as_of']} delta={delta} tau={tau} tilt={max_tilt}")
    for w in warnings: print("         !", w)


if __name__ == "__main__":
    main()
