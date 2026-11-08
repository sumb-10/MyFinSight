"""부록 A 표: 시나리오별 결과 (조건·상태·점검·질문·LLM 규칙 심사 점수·리포트 심사 점수·추천 라벨)."""

import glob
import json
import statistics
import sys
from pathlib import Path

S = Path(sys.argv[1])
m = json.load(open(S / "measure_qa100.json"))
rule = {x["scenario"]: x for f in glob.glob(str(S / "judge" / "rule_result_*.json")) for x in json.load(open(f))}
e5p = S / "judge" / "e5_result.json"  # E5 는 투자금·적립을 넣어 다시 심사한 값 (범위 밖은 채점 제외)
if e5p.exists():
    for y in json.load(open(e5p)):
        if y["scenario"] in rule:
            rule[y["scenario"]]["E5"] = None if y.get("out_of_scope") else y.get("E5")
rep_dir = S / "judge2" if list((S / "judge2").glob("report_result_*.json")) else S / "judge"  # 리포트는 자르지 않은 자료로 다시 심사한 값
rep = {x["scenario"]: x for f in glob.glob(str(rep_dir / "report_result_*.json")) for x in json.load(open(f))}
cr = ["근거성", "논리적 일관성", "위험 고려", "데이터 연계"]
MK = {"SP500": "S&P500", "NASDAQ100": "NDX", "KOSPI200": "K200"}
TP = {"quality": "퀄리티", "high_dividend": "고배당", "momentum": "모멘텀", "low_per": "저PER", "low_volatility": "저변동성"}
rows = ["| 시나리오 | 시장·선정 | 뉴스 | 첫 실행 → 최종 | 조건(반영/전체, 대화로 바뀜) | 자동 점검 | 질문 | 규칙 심사 | 리포트 심사 | 추천 |", "| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |"]
for p in m["per"]:
    name = p["name"]
    scen = json.load(open(Path("backend/test_scenarios") / f"{name}.json"))
    c = scen["constraints"]
    mk = "+".join(MK.get(u, u) for u in c["universe"])
    tp = TP.get(scen["strategy_preference"]["template"], scen["strategy_preference"]["template"])
    news = "켬" if scen["strategy_preference"]["use_news_tilt"] else "끔"
    conds = p["conditions"]
    inscope = [x for x in conds if not (x["changed"] and not x["consented"] and x["id"] in ("no_leverage_short", "target_years"))]
    refl = sum(1 for x in inscope if x["reflected"])
    chg = sum(1 for x in inscope if x["changed"] and x["consented"])
    fr = (p["first_run"] or {}).get("status") or "-"
    r = rule.get(name)
    if r:
        app = [r[e] for e in ("E1", "E2", "E3", "E4", "E5") if r.get(e) is not None]
        rs = f"{sum(app)}/{2 * len(app)}"
    else:
        rs = "-"
    q = rep.get(name)
    qs = f"{statistics.mean(q[c_] for c_ in cr):.2f}" if q else "-"
    val = json.load(open(Path("output") / p["run_id"] / "12_validation.json"))
    full = str(((val.get("recommended") or {}).get("verdict") or {}).get("label_ko") or "-")
    kind = "구성 불충분" if full.startswith("구성 불충분") else ("추천(주의)" if "주의" in full else "추천")
    plan = full.split(":")[-1].strip() if ":" in full else ""
    lab = f"{kind} · {plan}" if plan else kind
    rows.append(f"| {name[-3:]} | {mk}·{tp} | {news} | {fr} → {p['status']} | {refl}/{len(inscope)}{f' ({chg})' if chg else ''} | {p['audit']['n'] - len(p['audit']['fail'])}/{p['audit']['n']} | {p['dialog']['n_q']} | {rs} | {qs} | {lab} |")
(S / "appendix_a.md").write_text("\n".join(rows), encoding="utf-8")
print("\n".join(rows[:6]))
