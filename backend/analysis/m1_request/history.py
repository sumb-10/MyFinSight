"""M1-03 실행 이력·컨텍스트. 이전 실행 요약을 LLM 프롬프트의 {{context}} 로 (비밀값·원문 전체 제외)."""

from __future__ import annotations

from typing import Any

from backend.analysis.common.store import JsonStore, RequestStore, RunIndex


def recent_runs(store: JsonStore, repo: Any, *, limit: int = 3) -> list[dict[str, Any]]:
    idx = RunIndex(store)
    reqs = RequestStore(store)
    out = []
    for r in sorted(idx.load(), key=lambda x: x.queued_at, reverse=True):
        if r.status not in ("success", "partial"):
            continue
        try:
            doc = reqs.load(r.request_id)
        except Exception:  # noqa: BLE001
            continue
        row: dict[str, Any] = {"run_id": r.run_id, "finished_at": r.finished_at, "idea": doc.idea[:200], "mode": doc.mode}
        try:
            art = repo.get_run_artifact(r.run_id)
        except Exception:  # noqa: BLE001
            art = None
        if art:
            res = art["results"]
            val = res.get("validation", {})
            chosen = val.get("chosen_id")
            p = next((x for x in res["backtest"]["portfolios"] if x["id"] == chosen), None) or (res["backtest"]["portfolios"][0] if res["backtest"]["portfolios"] else None)
            if p:
                h = p["headline"]
                row.update({"chosen": p.get("name_ko"), "cagr": h.get("cagr"), "max_drawdown": h.get("max_drawdown"), "recommended": bool(val.get("recommended")),
                            "template": res["intent"]["screen"]["template"], "tickers": list(p["target_weights"])[:12]})  # fmt: skip
        out.append(row)
        if len(out) >= limit:
            break
    return out


def context_package(store: JsonStore, repo: Any, *, limit: int = 3) -> str:
    rows = recent_runs(store, repo, limit=limit)
    if not rows:
        return "(이전 실행 없음)"
    lines = []
    for r in rows:
        perf = f", 선택안 {r.get('chosen')} CAGR {r['cagr']:+.1%} / 최대낙폭 {r['max_drawdown']:.1%}, 추천 {'있음' if r.get('recommended') else '없음'}" if r.get("cagr") is not None else ""
        lines.append(f"- {r['finished_at'] or ''} [{r['mode']}] \"{r['idea']}\" (템플릿 {r.get('template', '-')}){perf}")
    return "\n".join(lines)
