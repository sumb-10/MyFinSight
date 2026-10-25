"""M5-06 수정안 비교: 원안·수정안 결과 묶음(13_results) 두 개 → 조건·종목·비중·규칙·성과 비교 (docs/Module5.md §6).

- 평가 조건(기간·초기자본·적립·비교지수·리밸런싱)이 같을 때만 성과표를 만든다. 다르면 same_window=False 와 이유만 남긴다.
- 숫자는 두 결과 묶음의 값을 옮겨 적기만 한다 (다시 계산하지 않음). 장점·불리한 점 문장도 표의 값으로 코드가 만든다 (LLM 없음).
"""

from __future__ import annotations

import datetime as dt
from typing import Any

from backend.analysis.m1_request.assemble import diff_fields, get_path
from backend.analysis.m1_request.validate import label

SCHEMA_VERSION = 1
BLOCKS = ("capital", "horizon", "risk", "constraints", "strategy_preference", "natural_language")
EVAL_FIELDS = ("derived.backtest_start", "derived.backtest_end", "capital.initial_amount", "capital.currency", "capital.monthly_contribution",
               "capital.contribution_day", "risk.benchmark", "constraints.rebalance", "constraints.universe")  # fmt: skip
PERF_ROWS = (("cagr", "연평균 수익률 (CAGR)", "pct"), ("period_return", "기간 수익률", "pct"), ("max_drawdown", "최대 낙폭", "pct"), ("ann_vol", "연 변동성", "pct"),
             ("sharpe", "샤프 비율", "num"), ("excess_cagr", "비교지수 대비 초과 CAGR", "pct"), ("final_value_usd", "최종 평가금액 (USD)", "usd"),
             ("profit_usd", "순이익 (USD)", "usd"), ("irr_annual", "연 IRR (적립 반영)", "pct"))  # fmt: skip
RULE_KO = {"R1": "최대낙폭", "R1b": "비교지수 대비 낙폭", "R2": "목표수익", "R3": "비교지수 대비", "R4": "종목 상한", "R4b": "종목 비중 드리프트", "R5": "섹터 상한", "R5b": "섹터 비중 드리프트", "R6": "종목 수", "R7": "변동성 적합", "R8": "자료 무결성", "R9": "투자 비율"}


def _revision_text_from(revised: dict[str, Any]) -> str:
    """수정안 결과의 아이디어 보충에서 '[수정 요청] …' 문장을 찾는다 (호출자가 revision_text 를 주지 않았을 때)."""
    nl = (revised.get("request") or {}).get("natural_language") or {}
    for c in nl.get("clarifications") or []:
        if str(c).startswith("[수정 요청]"):
            return str(c)[len("[수정 요청]"):].strip()
    return ""


def _chosen(results: dict[str, Any]) -> tuple[str | None, dict[str, Any] | None]:
    v = results.get("validation", {})
    cid = v.get("chosen_id") or (v.get("recommended") or {}).get("id")
    port = next((p for p in results.get("backtest", {}).get("portfolios", []) if p.get("id") == cid), None)
    if port is None and cid and cid.startswith("cash_blend_"):
        alt = next((a for a in v.get("alternatives", []) if a.get("id") == cid), None)
        port = alt
    return cid, port


def _perf(port: dict[str, Any] | None) -> dict[str, Any]:
    if not port:
        return {}
    h = port.get("headline") or {}
    m = port.get("metrics") or {}
    money = port.get("money") or {}
    risk = m.get("risk") or {}
    return {"cagr": h.get("cagr"), "period_return": h.get("period_return"), "max_drawdown": h.get("max_drawdown"), "ann_vol": risk.get("ann_vol") or risk.get("volatility"),
            "sharpe": h.get("sharpe"), "excess_cagr": h.get("excess_cagr"), "final_value_usd": h.get("final_value_usd"), "profit_usd": money.get("profit_usd"), "irr_annual": money.get("irr_annual")}  # fmt: skip


def _weights(port: dict[str, Any] | None) -> dict[str, float]:
    if not port:
        return {}
    w = port.get("target_weights") or {}
    if not w and port.get("weights_by_date"):
        wb = port["weights_by_date"]
        last = sorted(wb)[-1] if isinstance(wb, dict) and wb else None
        w = wb[last] if last else {}
    return {k: float(v) for k, v in (w or {}).items()}


def _tickers(results: dict[str, Any]) -> list[str]:
    sel = results.get("selection", {})
    now = (sel.get("as_of_now") or {}).get("selected") or []
    return [s["ticker"] if isinstance(s, dict) else str(s) for s in now]


def _rules(results: dict[str, Any], cid: str | None) -> dict[str, str]:
    v = results.get("validation", {})
    r = next((x for x in [*v.get("results", []), *v.get("alternatives", [])] if x.get("id") == cid), None)
    return {c["rule"]: c["status"] for c in (r or {}).get("checks", [])}


def _f(v: Any, kind: str) -> str:
    if v is None:
        return "–"
    if kind == "pct":
        return f"{float(v):+.1%}" if kind == "pct" and abs(float(v)) < 10 else f"{float(v):.1%}"
    if kind == "usd":
        return f"{float(v):,.0f} USD"
    return f"{float(v):.2f}"


def compare(base: dict[str, Any], revised: dict[str, Any], *, base_report_id: str, revised_report_id: str, comparison_id: str | None = None,
            now: dt.datetime | None = None, revision_text: str | None = None) -> dict[str, Any]:  # fmt: skip
    """두 결과 묶음을 비교한 문서 (store/data/comparisons/<id>.json)."""
    breq, rreq = base["request"], revised["request"]
    warnings: list[str] = []
    cond = []
    for f in diff_fields({k: breq.get(k) for k in BLOCKS}, {k: rreq.get(k) for k in BLOCKS}):
        if f.startswith("natural_language.idea"):
            cond.append({"field": f, "label_ko": label("natural_language.idea"), "base": breq["natural_language"]["idea"][:200], "revised": rreq["natural_language"]["idea"][:200]})
            continue
        cond.append({"field": f, "label_ko": label(f), "base": get_path(breq, f), "revised": get_path(rreq, f)})
    diffs_eval = [f for f in EVAL_FIELDS if get_path(breq, f) != get_path(rreq, f)]
    same_window = not diffs_eval
    if not same_window:
        warnings.append("평가 조건이 달라 성과를 공정하게 비교할 수 없습니다: " + ", ".join(label(f) if not f.startswith("derived") else f for f in diffs_eval))
    bt, rt = _tickers(base), _tickers(revised)
    ticker_changes = {"added": sorted(set(rt) - set(bt)), "removed": sorted(set(bt) - set(rt)), "kept": sorted(set(bt) & set(rt))}
    bcid, bport = _chosen(base)
    rcid, rport = _chosen(revised)
    bw, rw = _weights(bport), _weights(rport)
    weight_changes = [{"ticker": t, "base": round(bw.get(t, 0.0), 4), "revised": round(rw.get(t, 0.0), 4), "delta": round(rw.get(t, 0.0) - bw.get(t, 0.0), 4)}
                      for t in sorted(set(bw) | set(rw), key=lambda t: -(rw.get(t, 0.0) + bw.get(t, 0.0)))]  # fmt: skip
    br, rr = _rules(base, bcid), _rules(revised, rcid)
    rule_changes = [{"rule": r, "label_ko": RULE_KO.get(r, r), "base": br.get(r), "revised": rr.get(r), "changed": br.get(r) != rr.get(r)} for r in sorted(set(br) | set(rr))]
    bsum, rsum = base.get("validation", {}).get("summary", {}), revised.get("validation", {}).get("summary", {})
    perf_table: list[dict[str, Any]] = []
    pros: list[str] = []
    cons: list[str] = []
    bench = (base.get("backtest", {}).get("benchmarks") or [{}])[0]
    if same_window:
        bp, rp, bm = _perf(bport), _perf(rport), _perf(bench)
        for key, lab, kind in PERF_ROWS:
            perf_table.append({"metric": key, "label_ko": lab, "base": bp.get(key), "revised": rp.get(key), "benchmark": bm.get(key) if key not in ("profit_usd", "irr_annual") else bm.get(key), "format": kind})
        def _say(key: str, lab: str, kind: str, higher_better: bool) -> None:
            a, b = bp.get(key), rp.get(key)
            if a is None or b is None:
                return
            better = (b > a) if higher_better else (b < a)
            if abs(b - a) < (1e-4 if kind == "pct" else 1e-3):
                return
            (pros if better else cons).append(f"{lab}: 수정안 {_f(b, kind)} vs 원안 {_f(a, kind)}")
        _say("cagr", "연평균 수익률", "pct", True)
        _say("max_drawdown", "최대 낙폭", "pct", False)
        _say("sharpe", "샤프 비율", "num", True)
        _say("ann_vol", "연 변동성", "pct", False)
        if rsum and bsum:
            if rsum.get("n_fail", 0) < bsum.get("n_fail", 0):
                pros.append(f"미통과 포트폴리오 {bsum.get('n_fail')} → {rsum.get('n_fail')}개로 줄었습니다")
            elif rsum.get("n_fail", 0) > bsum.get("n_fail", 0):
                cons.append(f"미통과 포트폴리오 {bsum.get('n_fail')} → {rsum.get('n_fail')}개로 늘었습니다")
    if ticker_changes["added"] or ticker_changes["removed"]:
        pros.append(f"종목 변화: 추가 {len(ticker_changes['added'])}개, 제외 {len(ticker_changes['removed'])}개, 유지 {len(ticker_changes['kept'])}개")
    pros_cons = {"pros_ko": pros, "cons_ko": cons,
                 "note_ko": "표의 값으로만 만든 문장입니다. 과거 백테스트 차이이며 앞으로의 성과 차이를 뜻하지 않습니다." if same_window else "평가 조건이 달라 성과 문장은 만들지 않았습니다."}  # fmt: skip
    rid = comparison_id or f"cmp_{revised_report_id}"
    return {"schema_version": SCHEMA_VERSION, "comparison_id": rid, "base_run_id": base.get("run_id") or base_report_id, "revised_run_id": revised.get("run_id") or revised_report_id,
            "base_report_id": base_report_id, "revised_report_id": revised_report_id, "created_at": (now or dt.datetime.now(dt.UTC)).astimezone().isoformat(timespec="seconds"),
            "same_window": same_window, "window": {"start": str(get_path(rreq, "derived.backtest_start")), "end": str(get_path(rreq, "derived.backtest_end"))},
            "base_chosen_id": bcid, "revised_chosen_id": rcid, "base_chosen_label_ko": (bport or {}).get("name_ko"), "revised_chosen_label_ko": (rport or {}).get("name_ko"),
            "base_validation": bsum, "revised_validation": rsum, "condition_changes": cond, "ticker_changes": ticker_changes, "weight_changes": weight_changes,
            "rule_changes": rule_changes, "performance_table": perf_table, "pros_cons_ko": pros_cons, "revision_text": revision_text or _revision_text_from(revised),
            "warnings": warnings}  # fmt: skip
