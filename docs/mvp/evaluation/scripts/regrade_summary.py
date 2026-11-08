"""bt_regrade 결과 모으기 (항목 6 재채점)."""

import glob
import json
import statistics
import sys

rows = [json.loads(l) for f in sorted(glob.glob(sys.argv[1] + "/chunk_0?.jsonl")) for l in open(f) if l.strip()]
ok = [r for r in rows if "error" not in r]
out = {"runs": len(rows), "errors": [(r["name"], r["error"]) for r in rows if "error" in r]}
out["repro"] = {"portfolios": sum(r["a_vs_b"]["n"] for r in ok), "identical": sum(r["a_vs_b"]["identical"] for r in ok),
                "runs_identical": sum(1 for r in ok if r["a_vs_b"]["identical"] == r["a_vs_b"]["n"] and not r["a_vs_b"]["missing"]),
                "validation_same_ab": sum(1 for r in ok if r["val_same_ab"])}
out["spec"] = {"portfolios": sum(r["spec"]["n"] for r in ok), "max_rel_diff": max(r["spec"]["max_rel_diff"] for r in ok)}
out["headline"] = {"portfolios": sum(r["headline"]["n"] for r in ok), "ok": sum(r["headline"]["ok"] for r in ok),
                   "checks": sum(r["headline"]["checks"] for r in ok), "max_diff": max(r["headline"]["max_diff"] for r in ok)}
dl = [x for r in ok for x in r["daily"] if x.get("n_days")]
nt = sum(x["n_nontrade"] for x in dl)
out["daily"] = {"portfolio_series": len(dl), "nontrade_days": nt, "nontrade_within_1bp": sum(x["within_1bp_nontrade"] for x in dl),
                "all_days": sum(x["n_days"] for x in dl), "all_within_10bp": sum(x["within_10bp_all"] for x in dl),
                "trade_days": sum(x["n_trade_days"] for x in dl), "max_diff_nontrade": max(x["max_diff_nontrade"] for x in dl),
                "trade_max_median": statistics.median([x["max_diff_trade"] for x in dl if x["n_trade_days"]]),
                "trade_max_max": max(x["max_diff_trade"] for x in dl if x["n_trade_days"])}
flow = [r for r in ok if r["flows"]]
imp = [x for r in flow for x in r["impact"]]
nof = [x for r in ok if not r["flows"] for x in r["impact"]]
q = lambda xs, f: sorted(xs)[min(len(xs) - 1, int(f * len(xs)))]
out["impact_flow_runs"] = {"runs": len(flow), "portfolios": len(imp),
                           "d_cagr_abs": {"median": q([abs(x["d_cagr"]) for x in imp], .5), "p95": q([abs(x["d_cagr"]) for x in imp], .95), "max": max(abs(x["d_cagr"]) for x in imp)},
                           "d_mdd_abs": {"median": q([abs(x["d_mdd"]) for x in imp], .5), "p95": q([abs(x["d_mdd"]) for x in imp], .95), "max": max(abs(x["d_mdd"]) for x in imp)}}
out["impact_noflow_runs"] = {"runs": len(ok) - len(flow), "portfolios": len(nof), "max_abs_d_cagr": max((abs(x["d_cagr"]) for x in nof), default=0.0),
                             "max_abs_d_mdd": max((abs(x["d_mdd"]) for x in nof), default=0.0)}
out["recommendation_changed"] = [(r["name"], r["chosen"], r["label"]) for r in ok if r["chosen"][0] != r["chosen"][1] or r["label"][0] != r["label"][1]]
out["label_kind_changed"] = []
for r in ok:
    k = lambda s: "구성 불충분" if s.startswith("구성 불충분") else ("추천(주의)" if "주의" in s else "추천")
    if k(r["label"][0]) != k(r["label"][1]):
        out["label_kind_changed"].append((r["name"], r["label"]))
print(json.dumps(out, ensure_ascii=False, indent=1, default=str))
