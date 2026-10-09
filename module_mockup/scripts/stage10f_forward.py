"""
Stage 10f: "if we built the portfolio today" — market model + news-evidence views + Black-Litterman at the latest price date.

in : 01_request.json, 02_intent.json, 05_selection.json (current selection), 09a_news_evidence.json, input/02_backtest_request*.jsonc
out: output/10f_forward_portfolios.json  (no backtest)
"""
import argparse, datetime as dt
from common import INPUT, OUTPUT, load_json, load_jsonc, dump_json
from stage8_baseline import build_market_model
from stage9_views import generate_views
from stage10_black_litterman import build_bl
import portfolio_config as PC


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--backtest-request", default=str(INPUT / "02_backtest_request.jsonc"))
    ap.add_argument("--news", default=str(OUTPUT / "09a_news_evidence.json"))
    ap.add_argument("--out", default=str(OUTPUT / "10f_forward_portfolios.json"))
    a = ap.parse_args()
    bt_req = load_jsonc(a.backtest_request)
    req, intent, sel = load_json(OUTPUT / "01_request.json"), load_json(OUTPUT / "02_intent.json"), load_json(OUTPUT / "05_selection.json")
    ev = load_json(a.news)
    fwd = bt_req.get("forward_construction", {})
    as_of = dt.date.fromisoformat(str(fwd.get("as_of") or req["derived"]["price_data_end"]))
    tickers = [s["ticker"] for s in sel["selected"]]
    warnings = []
    model, base = build_market_model(tickers, as_of, req)
    tk = model["tickers"]
    wb = next(p for p in base["portfolios"] if p["id"] == base["chosen_baseline"])["weights"]
    win = ev["windows"].get(str(as_of))
    sets = []
    if not win:
        warnings.append(f"no news window for {as_of} in {a.news}; forward portfolios = templates only")
    elif not win["enough"]:
        warnings.append(f"news covers only {win['n_tickers_with_news']} tickers (< {ev['min_tickers']}); forward BL skipped")
    else:
        evidence = {t: [ev["all_evidence"][i] for i in ids] for t, ids in win["tickers"].items() if t in tk}
        sets, w = generate_views(tk, as_of, model, wb, intent, bt_req["views"]["n_sets"], bt_req["views"]["views_per_set"],
                                 intent["news_tilt"]["max_view_confidence"], evidence=evidence, stage_tag="09n_forward", news_window_days=ev["window_days"])
        warnings += w
    ports, w2, params = build_bl(model, base, sets, req, intent, id_prefix="fwd_bl", name_prefix="현재 구성 BL") if sets else ([], [], None)
    warnings += w2
    init, fx = req["derived"]["initial_amount_usd"], req["derived"]["fx_rate"]
    for p in [*base["portfolios"], *ports]:
        p["allocation"] = [{"ticker": t, "weight": w_, "usd": round(init * w_, 2), "krw": round(init * w_ * fx)} for t, w_ in sorted(p["weights"].items(), key=lambda x: -x[1])]
    out = {"request_id": req["request_id"], "stage": "10f_forward_portfolios", "as_of": str(as_of),
           "news_window": win and {"window": win["window"], "n_articles": win["n_articles"], "n_tickers_with_news": win["n_tickers_with_news"], "origin_counts": win["origin_counts"]},
           "evidence": {i: ev["all_evidence"][i] for t, ids in (win or {}).get("tickers", {}).items() for i in ids},
           "market_model": {k: model[k] for k in ["as_of", "lookback", "tickers", "ann_vol", "cap_weights", "delta", "delta_source", "tau", "implied_returns"]},
           "baseline": {"id": base["chosen_baseline"], "weights": wb}, "templates": base["portfolios"], "views_sets": sets, "portfolios": ports,
           "parameters": params, "capital": {"initial_amount_usd": init, "fx_rate": fx, "fx_date": req["derived"]["fx_date"]}, "warnings": warnings}
    dump_json(out, a.out)
    print(f"[stage10f] ok -> {a.out}\n         as_of={as_of} tickers={len(tk)} news={out['news_window']} sets={len(sets)} bl={len(ports)}")
    for p in ports:
        top = sorted(((t, p['weights'][t] - wb[t]) for t in p['weights']), key=lambda x: -abs(x[1]))[:4]
        print(f"         {p['id']} {p['title_ko']:<18} max|Δ|={max(abs(p['weights'][t] - wb[t]) for t in p['weights']):.3f} top Δ: " + ", ".join(f"{t}{v:+.3f}" for t, v in top))
    for w in warnings: print("         !", w)


if __name__ == "__main__":
    main()
