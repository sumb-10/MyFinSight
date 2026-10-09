"""
Stage 8: market model (covariance, cap weights, implied returns) + baseline template portfolios.

in : output/07_backtest_spec.json, 01_request.json, 02_intent.json, descriptor, prices + info caches
out: output/08_market_model.json, output/08_baseline_portfolios.json
"""
import argparse, datetime as dt
import numpy as np
from common import OUTPUT, RAW, load_json, dump_json
from descriptor import load_descriptor
import portfolio as P
import portfolio_config as PC
from schemas import MarketModel, BaselinePortfolios


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--spec", default=str(OUTPUT / "07_backtest_spec.json"))
    a = ap.parse_args()
    spec, req = load_json(a.spec), load_json(OUTPUT / "01_request.json")
    desc = load_descriptor()
    as_of = dt.date.fromisoformat(spec["period"]["as_of"])
    cons = req["constraints"]
    notes, warnings = [], []

    mm = P.estimate_market_model(spec["selection"]["tickers"], as_of)
    tk = mm["tickers"]
    if mm["dropped"]:
        warnings.append(f"dropped from model (insufficient returns in window): {mm['dropped']}")
    sec_code = [desc["companies"][t]["gics"]["sector"]["code"] for t in tk]
    sec_name = [desc["companies"][t]["gics"]["sector"]["name"] for t in tk]
    shares = {r["ticker"]: r.get("sharesOutstanding") for r in load_json(RAW / "info_snapshot.json")}
    capw = P.cap_weights(tk, as_of, shares)
    notes.append("cap_weights use CURRENT sharesOutstanding x close(as_of): approximation for past dates")
    tol = req["risk"]["risk_tolerance"]
    if PC.RISK_AVERSION_MODE == "market_implied":
        d_mkt, d_win = P.market_implied_delta(as_of, PC.LOOKBACK_DAYS, rf=0.04)
        mult = PC.RISK_AVERSION_MULT[tol]; delta = round(max(0.5, min(d_mkt * mult, 8.0)), 4)
        delta_meta = {"delta_source": "market_implied", "delta_market": round(d_mkt, 4), "delta_multiplier": mult, "delta_window": d_win}
        notes.append(f"delta = market-implied {d_mkt:.2f} (SPY, {d_win['start']}~{d_win['end']}) x {mult} ({tol}) = {delta} (clipped to [0.5, 8])")
    else:
        delta = PC.RISK_AVERSION[tol]; delta_meta = {"delta_source": "fixed"}
    total = 1.0 - cons["min_cash_ratio"]
    max_stock, max_sector = cons["max_weight_per_stock"], cons["max_weight_per_sector"]
    baseline_id = req["strategy_preference"]["baseline_weighting"]

    sec_names = {desc["companies"][t]["gics"]["sector"]["code"]: desc["companies"][t]["gics"]["sector"]["name"] for t in tk}

    def label(c):
        if ":" not in c: return c
        kind, val = c.split(":", 1)
        if kind == "stock_cap": return f"stock_cap:{tk[int(val)]}"
        if kind == "sector_cap": return f"sector_cap:{sec_names.get(val, val)}"
        return c

    ports, weights = [], {}
    for tpl in PC.TEMPLATES:
        w, applied = P.template_weights(tpl, mm["cov"], mm["ann_vol"], capw, max_stock, max_sector, sec_code, total)
        weights[tpl] = w
    pi = P.implied_returns(mm["cov"], weights[baseline_id], delta)
    for tpl in PC.TEMPLATES:
        w = weights[tpl]
        name_ko, rule_ko = PC.TEMPLATE_NAMES_KO[tpl]
        _, applied = P.template_weights(tpl, mm["cov"], mm["ann_vol"], capw, max_stock, max_sector, sec_code, total)
        ports.append({"id": tpl, "kind": "template", "name_ko": name_ko, "rule_ko": rule_ko,
                      "weights": {t: round(float(x), 6) for t, x in zip(tk, w)}, "cash_weight": round(1 - float(w.sum()), 6),
                      "ex_ante": P.ex_ante_stats(w, pi, mm["cov"]), "sector_weights": P.sector_weights(w, sec_name),
                      "constraints_applied": [label(c) for c in applied]})

    model = MarketModel(request_id=req["request_id"], as_of=as_of, lookback={**mm["window"], "requested_days": PC.LOOKBACK_DAYS},
                        tickers=tk, ann_vol={t: round(float(v), 6) for t, v in zip(tk, mm["ann_vol"])},
                        corr=np.round(mm["corr"], 6).tolist(), cov=np.round(mm["cov"], 8).tolist(),
                        cap_weights={t: round(float(x), 6) for t, x in zip(tk, capw)}, delta=delta, tau=PC.TAU, **delta_meta,
                        baseline_id=baseline_id, implied_returns={t: round(float(x), 6) for t, x in zip(tk, pi)},
                        shrinkage=mm["shrinkage"], notes=notes + warnings)
    dump_json(model.model_dump(mode="json"), OUTPUT / "08_market_model.json")
    base = BaselinePortfolios(request_id=req["request_id"], as_of=as_of, chosen_baseline=baseline_id, portfolios=ports)
    dump_json(base.model_dump(mode="json"), OUTPUT / "08_baseline_portfolios.json")

    print(f"[stage8] ok -> 08_market_model.json, 08_baseline_portfolios.json\n         as_of={as_of} window={mm['window']} "
          f"shrink alpha={mm['shrinkage']['alpha']:.3f} delta={delta} tau={PC.TAU} baseline={baseline_id}")
    print(f"         {'ticker':<7}{'vol':>7}{'capw':>7}{'pi':>7} | " + " ".join(f"{t[:9]:>10}" for t in PC.TEMPLATES))
    for i, t in enumerate(tk):
        print(f"         {t:<7}{mm['ann_vol'][i]:>7.3f}{capw[i]:>7.3f}{pi[i]:>7.3f} | " + " ".join(f"{weights[tp][i]:>10.4f}" for tp in PC.TEMPLATES))
    for p in ports:
        print(f"         {p['id']:<20} exp_ret={p['ex_ante']['exp_return']:.3f} vol={p['ex_ante']['vol']:.3f} n_eff={p['ex_ante']['effective_n']:.1f} sectors={p['sector_weights']} applied={p['constraints_applied']}")
    for w in warnings: print("         !", w)


if __name__ == "__main__":
    main()
