"""LLM 심사 결과 모으기: 항목 5(규칙 일치율)와 항목 3(5점 루브릭 평균).

  python score_judges.py <규칙 심사 폴더> <리포트 심사 폴더> [E5 다시 심사 파일]

E5 다시 심사 파일이 있으면 규칙 심사의 E5 를 그 값으로 바꾼다 (처음 규칙 심사 자료에 투자금·월 적립이 빠져 있었다).
out_of_scope(서비스 입력 범위 밖이라 시험 도구가 바꾼 값만 어긋남)는 항목 2 와 같이 채점에서 뺀다(null).
"""

import glob
import json
import statistics
import sys
from collections import Counter
from pathlib import Path

RULE, REPORT = Path(sys.argv[1]), Path(sys.argv[2])
E5 = Path(sys.argv[3]) if len(sys.argv) > 3 else None
out = {}

rule = [x for f in sorted(glob.glob(str(RULE / "rule_result_*.json"))) for x in json.load(open(f))]
if E5 and E5.exists():
    e5 = {x["scenario"]: x for x in json.load(open(E5))}
    for x in rule:
        y = e5.get(x["scenario"])
        if y is not None:
            x["E5_first"] = x.get("E5")
            x["E5"] = None if y.get("out_of_scope") else y.get("E5")
            x.setdefault("reasons", {})["E5"] = y.get("reason")
    out["e5_rejudged"] = {"n": len(e5), "out_of_scope": [k for k, v in e5.items() if v.get("out_of_scope")],
                          "first": dict(Counter(x.get("E5_first") for x in rule)), "second": dict(Counter(x.get("E5") for x in rule))}
els = ["E1", "E2", "E3", "E4", "E5"]
for x in rule:  # 심사자가 '시험 정규화 때문에만 어긋남' 으로 표시한 요소는 채점에서 뺀다 (항목 2 와 같은 규칙)
    for e in x.get("out_of_scope") or []:
        if e in els:
            x[e] = None
pts = sum(x[e] for x in rule for e in els if x.get(e) is not None)
app = sum(1 for x in rule for e in els if x.get(e) is not None)
per_el = {e: {"n": sum(1 for x in rule if x.get(e) is not None),
              "2": sum(1 for x in rule if x.get(e) == 2), "1": sum(1 for x in rule if x.get(e) == 1), "0": sum(1 for x in rule if x.get(e) == 0),
              "rate": round(sum(x[e] for x in rule if x.get(e) is not None) / (2 * max(1, sum(1 for x in rule if x.get(e) is not None))), 4)} for e in els}
full = sum(1 for x in rule if all(x.get(e) in (2, None) for e in els))
any0 = [x["scenario"] for x in rule if any(x.get(e) == 0 for e in els)]
out["rule"] = {"n_scenarios": len(rule), "points": pts, "applicable": app, "match_rate": round(pts / (2 * app), 4) if app else None,
               "strict_full_match_scenarios": full, "scenarios_with_any_0": any0, "per_element": per_el}
out["rule_issues"] = [(x["scenario"], e, (x.get("reasons") or {}).get(e)) for x in rule for e in els if x.get(e) in (0, 1)]

rep = [x for f in sorted(glob.glob(str(REPORT / "report_result_*.json"))) for x in json.load(open(f))]
cr = ["근거성", "논리적 일관성", "위험 고려", "데이터 연계"]
if rep:
    means = {c: round(statistics.mean(x[c] for x in rep), 3) for c in cr}
    per = [(x["scenario"], round(statistics.mean(x[c] for c in cr), 2)) for x in rep]
    out["report"] = {"n": len(rep), "means": means, "overall": round(statistics.mean(v for _, v in per), 3),
                     "dist": {c: dict(Counter(x[c] for x in rep)) for c in cr}, "share_ge_4": round(sum(1 for _, v in per if v >= 4.0) / len(per), 3),
                     "lowest": sorted(per, key=lambda t: t[1])[:6], "per": per}
    out["report_issues"] = [(x["scenario"], i) for x in rep for i in x.get("issues", [])]
(REPORT / "judge_summary.json").write_text(json.dumps(out, ensure_ascii=False, indent=1), encoding="utf-8")
print(json.dumps({k: v for k, v in out.items() if not k.endswith("issues")}, ensure_ascii=False, indent=1))
