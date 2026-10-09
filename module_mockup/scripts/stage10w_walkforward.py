"""
Stage 10w: walk-forward targets — at every rebalance date re-estimate the market model, build the 4 templates,
generate news-evidence views (when the window has enough news) and the Black-Litterman portfolio.

in : 07_backtest_spec.json, 01_request.json, 02_intent.json, 09a_news_evidence.json, input/02_backtest_request*.jsonc
out: output/10w_target_paths.json  {dates, portfolios: [{id, kind, name_ko, weights_by_date, views_by_date, fallback_dates}], ...}
"""
import argparse, datetime as dt
from common import INPUT, OUTPUT, load_json, load_jsonc, dump_json
from stage8_baseline import build_market_model
from stage9_views import generate_views
from stage10_black_litterman import build_bl
import portfolio_config as PC
from portfolio_config import TEMPLATE_NAMES_KO


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--backtest-request", default=str(INPUT / "02_backtest_request.jsonc"))
    ap.add_argument("--news", default=str(OUTPUT / "09a_news_evidence.json"))
    ap.add_argument("--out", default=str(OUTPUT / "10w_target_paths.json"))
    a = ap.parse_args()
    bt_req = load_jsonc(a.backtest_request); wf = bt_req.get("walkforward", {})
    if not wf.get("enabled"):
        print("[stage10w] walkforward disabled in the backtest request; nothing to do"); return
    spec, req, intent = load_json(OUTPUT / "07_backtest_spec.json"), load_json(OUTPUT / "01_request.json"), load_json(OUTPUT / "02_intent.json")
    ev = load_json(a.news)
    tickers = spec["selection"]["tickers"]
    dates = sorted(d for d, w in ev["windows"].items() if w["kind"] == "walkforward")
    if not dates:
        raise SystemExit("[stage10w] no walkforward windows in the news evidence file (run stage9a with the same backtest request)")
    tmpl = {t: {"id": f"wf_{t}", "kind": "template", "name_ko": f"{TEMPLATE_NAMES_KO[t][0]} (walk-forward)", "rule_ko": TEMPLATE_NAMES_KO[t][1], "weights_by_date": {}} for t in PC.TEMPLATES}
    bl = {"id": "wf_bl_news", "kind": "black_litterman", "name_ko": "뉴스 뷰 Black-Litterman (walk-forward)", "title_ko": "뉴스 근거 뷰",
          "rule_ko": "리밸런싱마다 직전 2주 뉴스 헤드라인으로 뷰를 새로 만들어 기준 비중을 조정", "weights_by_date": {}, "views_by_date": {}, "fallback_dates": [], "delta_by_date": {}}
    models, warnings = {}, []
    for d in dates:
        as_of = dt.date.fromisoformat(d)
        model, base = build_market_model(tickers, as_of, req)
        tk = model["tickers"]; wb = next(p for p in base["portfolios"] if p["id"] == base["chosen_baseline"])["weights"]
        models[d] = {"delta": model["delta"], "delta_source": model["delta_source"], "lookback": model["lookback"], "implied_returns": model["implied_returns"]}
        for p in base["portfolios"]: tmpl[p["id"]]["weights_by_date"][d] = p["weights"]
        win = ev["windows"][d]
        if win["enough"]:
            evidence = {t: [ev["all_evidence"][i] for i in ids] for t, ids in win["tickers"].items() if t in tk}
            sets, w = generate_views(tk, as_of, model, wb, intent, wf.get("view_sets", 1), wf.get("views_per_set", 4), intent["news_tilt"]["max_view_confidence"],
                                     evidence=evidence, stage_tag=f"09n_wf_{d}", news_window_days=ev["window_days"])
            warnings += [f"{d}: {x}" for x in w]
            if sets:
                ports, w2, params = build_bl(model, base, sets[:1], req, intent, id_prefix=f"wf_bl_{d}", name_prefix="뉴스 뷰 BL")
                warnings += [f"{d}: {x}" for x in w2]
                bl["weights_by_date"][d] = ports[0]["weights"]
                bl["views_by_date"][d] = [{**v, "summary_ko": s["summary_ko"]} for v, s in zip(sets[0]["views"], ports[0]["views_applied"])]
                bl["narrative_by_date"] = {**bl.get("narrative_by_date", {}), d: sets[0]["narrative_ko"]}
                print(f"[stage10w] {d}: news views {len(sets[0]['views'])} (articles {win['n_articles']}, tickers {win['n_tickers_with_news']}) -> BL max|Δ|={max(abs(ports[0]['weights'][t] - wb[t]) for t in tk):.3f}")
                continue
        bl["weights_by_date"][d] = wb; bl["fallback_dates"].append(d)
        bl["views_by_date"][d] = []
        print(f"[stage10w] {d}: no usable news (articles {win['n_articles']}, tickers {win['n_tickers_with_news']}, enough={win['enough']}) -> baseline weights")
    out = {"request_id": spec["request_id"], "stage": "10w_target_paths", "dates": dates, "tickers": tickers, "portfolios": [*tmpl.values(), bl],
           "market_models_by_date": models, "news_summary": {d: {k: ev["windows"][d][k] for k in ["window", "n_articles", "n_tickers_with_news", "enough", "origin_counts"]} for d in dates},
           "parameters": {"view_sets": wf.get("view_sets", 1), "views_per_set": wf.get("views_per_set", 4), "news_window_days": ev["window_days"], "min_news_tickers": ev["min_tickers"]},
           "warnings": warnings}
    dump_json(out, a.out)
    print(f"[stage10w] ok -> {a.out}\n         dates={dates} portfolios={[p['id'] for p in out['portfolios']]} fallback={bl['fallback_dates']}")
    for w in warnings: print("         !", w)


if __name__ == "__main__":
    main()
