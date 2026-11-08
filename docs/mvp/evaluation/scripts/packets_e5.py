"""E5(기간·운용) 다시 심사용 자료: 처음 규칙 심사 자료에 투자금·월 적립이 빠져 있어 E5 만 다시 매긴다.

  PYTHONPATH=. python packets_e5.py <runs.txt> <out.md>
"""

import json
import sys
from pathlib import Path

RUNS = Path("docs/mvp/scenario_qa/runs")
OUT = Path("output")


def j(p):
    return json.loads(Path(p).read_text(encoding="utf-8")) if Path(p).exists() else {}


parts = []
for ln in Path(sys.argv[1]).read_text().splitlines():
    if not ln.strip():
        continue
    name, rid = ln.split()
    rec = j(RUNS / f"{name}.json")
    scen = j(rec["scenario_file"])
    req, spec, bt, tg, wf = (j(OUT / rid / f"{n}.json") for n in ("01_request", "07_backtest_spec", "11_backtest_results", "10_target_portfolios", "10w_target_paths"))
    cap = req.get("capital") or {}
    eng = bt.get("engine") or {}
    rr = spec.get("rebalance_rule") or {}
    per = bt.get("period") or {}
    bl = [p["id"] for p in (wf.get("portfolios") or []) if p.get("kind") == "black_litterman"]
    omitted = (wf.get("bl_omitted") or {}).get("reason_ko")
    qa = [f"[{q.get('field')}] → {str(q.get('answer'))[:200]}" for q in rec.get("qa") or [] if q.get("field") in ("horizon.backtest_years", "horizon.target_years", "constraints.rebalance", "capital.monthly_contribution")]
    lines = [f"### {name}", f"아이디어(원문): {scen['natural_language']['idea']}",
             f"확정 조건: 투자기간 {(req.get('horizon') or {}).get('target_years')}년 · 초기 투자금 {cap.get('initial_amount')} {cap.get('currency')} · 월 적립 {cap.get('monthly_contribution')} {cap.get('currency')} (매월 {cap.get('contribution_day')}일 이후 첫 거래일) · 리밸런싱 {(req.get('constraints') or {}).get('rebalance')} · 뉴스 반영 {(req.get('strategy_preference') or {}).get('use_news_tilt')}",
             f"실제 실행: 백테스트 {per.get('start')}~{per.get('end')} ({per.get('trading_days')}거래일) · 리밸런싱 '{rr.get('description_ko')}' · 적립 {eng.get('n_contributions')}회 × {eng.get('contribution_usd')} USD · 뉴스 반영 구성 {bl or '없음'}{f' (못 만든 이유: {omitted})' if omitted else ''}",
             f"시험 정규화: {rec.get('normalized') or '없음'}"]
    if qa:
        lines.append("관련 대화 답: " + " / ".join(qa))
    parts.append("\n".join(lines))
Path(sys.argv[2]).write_text("\n\n---\n\n".join(parts), encoding="utf-8")
print(sys.argv[2], len(parts), sum(len(p) for p in parts))
