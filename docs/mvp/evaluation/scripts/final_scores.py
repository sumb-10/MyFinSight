"""최종 점수 집계: 5번 = 다시 돌리지 않은 54개(ruleG) + 다시 돌린 46개(ruleI, 자료 고친 재심사), 3번 = 리포트 30개(judgeG + judgeH).
결과를 final_scores.json 과 final_judge/ (부록 생성용) 에 쓴다."""

import glob
import json
import statistics
from collections import Counter
from pathlib import Path

S = Path("/private/tmp/claude-501/-Users-apple-dev-MyFinSight/ece881b1-6cba-4c95-8cf9-b3ca20ef0052/scratchpad/eval")
els = ["E1", "E2", "E3", "E4", "E5"]


def load(pattern):
    return {x["scenario"]: x for f in sorted(glob.glob(str(S / pattern))) for x in json.load(open(f))}


def val(x, e):
    return None if e in (x.get("out_of_scope") or []) else x.get(e)


def score(rows):
    p = sum(val(x, e) for x in rows for e in els if val(x, e) is not None)
    a = sum(2 for x in rows for e in els if val(x, e) is not None)
    per = {e: {"n": sum(1 for x in rows if val(x, e) is not None), **{str(k): sum(1 for x in rows if val(x, e) == k) for k in (2, 1, 0)}} for e in els}
    for e in els:
        per[e]["rate"] = round(sum(val(x, e) for x in rows if val(x, e) is not None) / (2 * max(1, per[e]["n"])), 4)
    return {"points": p, "applicable": a, "rate": round(p / a, 4), "per_element": per,
            "full": sum(1 for x in rows if all(val(x, e) in (2, None) for e in els)), "any0": [x["scenario"] for x in rows if any(val(x, e) == 0 for e in els)]}


old = load("ruleG/rule_result_*.json")
rerun = load("ruleI_*/rule_result_01.json")
pre = load("ruleH_*/rule_result_01.json")
assert len(old) == 100 and len(rerun) == 46 and len(pre) == 46 and set(rerun) == set(pre)
final = dict(old); final.update(rerun)
precorr = dict(old); precorr.update(pre)
out = {"item5": score(list(final.values())), "item5_before_packet_fix": score(list(precorr.values())), "item5_ruleG": score(list(old.values())),
       "rerun_before": score([old[k] for k in rerun]), "rerun_after": score(list(rerun.values())), "rerun_list": sorted(rerun)}
cr = ["근거성", "논리적 일관성", "위험 고려", "데이터 연계"]
rep = load("judgeG/report_result_*.json"); rep.update(load("judgeH/report_result_*.json"))
assert len(rep) == 30
per = {k: statistics.mean(x[c] for c in cr) for k, x in rep.items()}
out["item3"] = {"n": len(rep), "means": {c: round(statistics.mean(x[c] for x in rep.values()), 3) for c in cr}, "overall": round(statistics.mean(per.values()), 3),
                "dist": {c: dict(Counter(x[c] for x in rep.values())) for c in cr}, "share_ge_4": round(sum(1 for v in per.values() if v >= 4) / len(per), 3),
                "lowest": sorted((round(v, 2), k) for k, v in per.items())[:5]}
out["rule_issues"] = [(k, e, (final[k].get("reasons") or {}).get(e)) for k in sorted(final) for e in els if val(final[k], e) in (0, 1)]
(S / "final_scores.json").write_text(json.dumps(out, ensure_ascii=False, indent=1), encoding="utf-8")
(S / "final_judge" / "judge").mkdir(parents=True, exist_ok=True)
(S / "final_judge" / "judge2").mkdir(parents=True, exist_ok=True)
(S / "final_judge" / "judge" / "rule_result_01.json").write_text(json.dumps(list(final.values()), ensure_ascii=False, indent=1), encoding="utf-8")
(S / "final_judge" / "judge2" / "report_result_01.json").write_text(json.dumps(list(rep.values()), ensure_ascii=False, indent=1), encoding="utf-8")
i5, b5 = out["item5"], out["item5_before_packet_fix"]
print(f"item5 final {i5['points']}/{i5['applicable']} = {i5['rate']:.4f} (before packet fix {b5['points']}/{b5['applicable']} = {b5['rate']:.4f}); "
      f"re-run 46: {out['rerun_before']['rate']:.4f} -> {out['rerun_after']['rate']:.4f}")
for e in els:
    print(" ", e, i5["per_element"][e])
print("full", i5["full"], "any0", i5["any0"])
print("item3", out["item3"]["overall"], out["item3"]["means"], "share>=4", out["item3"]["share_ge_4"], out["item3"]["lowest"])
