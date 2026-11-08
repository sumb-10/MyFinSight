"""백테스트 정확성 시험 (엔진과 따로 계산):
1) 헤드라인 지표 재계산 — 일별 지수(11_daily_panel)에서 기간 수익률·CAGR·연변동성·최대낙폭·Sharpe 를 다시 계산해 저장값과 비교.
2) 일별 수익률 재계산 — 전날 종가 기준 보유 비중(w_종목) × 그날 종목 수익률(DB 수정종가, 달러 환산)의 합을 엔진 지수의 그날 수익률과 비교.
   거래(리밸런싱·적립)가 있는 날은 수수료(5bp × 회전율) 만큼 차이가 날 수 있어 따로 센다.

  PYTHONPATH=. python docs/mvp/evaluation/scripts/engine_check.py --runs qa_final_runs.txt --out engine_check.jsonl
"""

from __future__ import annotations

import argparse
import datetime as dt
import json
import sys
import traceback
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path.cwd()))
from backend.analysis.common.dbconn import open_analysis_repository  # noqa: E402
from backend.analysis.m2_data.market_data import MarketData  # noqa: E402
from backend.analysis.settings import AnalysisSettings  # noqa: E402

OUT = Path("output")


def headline_check(panel: pd.DataFrame, bt: dict, rf: float) -> list[dict]:
    rows = []
    stored = {p["id"]: p for p in bt.get("portfolios", []) + bt.get("benchmarks", [])}
    for pid, g in panel.groupby("portfolio_id", sort=False):
        p = stored.get(pid)
        if p is None:
            continue
        g = g.sort_values("date")
        idx = g["index"].to_numpy(dtype=float)
        dates = pd.to_datetime(g["date"])
        years = (dates.iloc[-1] - dates.iloc[0]).days / 365.25
        tr = idx[-1] / idx[0] - 1
        cg = (idx[-1] / idx[0]) ** (1 / years) - 1
        r = idx[1:] / idx[:-1] - 1
        per_year = (len(idx) - 1) / years
        vol = float(np.std(r, ddof=1) * np.sqrt(per_year))
        mdd = float(np.min(idx / np.maximum.accumulate(idx) - 1))
        sh = (cg - rf) / vol if vol > 0 else None
        h = p["headline"]
        risk = (p.get("metrics") or {}).get("risk") or {}
        mine = {"period_return": tr, "cagr": cg, "max_drawdown": mdd, "sharpe": sh, "ann_vol": vol}
        theirs = {"period_return": h.get("period_return"), "cagr": h.get("cagr"), "max_drawdown": h.get("max_drawdown"), "sharpe": h.get("sharpe"), "ann_vol": risk.get("ann_vol")}
        diffs = {k: (None if theirs[k] is None or mine[k] is None else abs(float(mine[k]) - float(theirs[k]))) for k in mine}
        tol = {"period_return": 1e-5, "cagr": 1e-5, "max_drawdown": 1e-5, "sharpe": 1e-4, "ann_vol": 1e-5}
        ok = {k: (d is not None and d <= tol[k]) for k, d in diffs.items() if theirs[k] is not None}
        rows.append({"id": pid, "ok": all(ok.values()), "n_checked": len(ok), "max_diff": max((d for d in diffs.values() if d is not None), default=0.0), "diffs": diffs})
    return rows


def daily_check(panel: pd.DataFrame, px: pd.DataFrame, bt: dict) -> list[dict]:
    rows = []
    trade_days_by_pid = {}
    for p in bt.get("portfolios", []) + bt.get("benchmarks", []):
        days = set()
        for c in p.get("checkpoints") or []:
            if c.get("date"):
                days.add(str(c["date"])[:10])
        for c in p.get("contribution_ledger") or []:
            if c.get("date"):
                days.add(str(c["date"])[:10])
        trade_days_by_pid[p["id"]] = days
    wcols = [c for c in panel.columns if c.startswith("w_")]
    for pid, g in panel.groupby("portfolio_id", sort=False):
        g = g.sort_values("date").set_index(pd.to_datetime(g.sort_values("date")["date"]))
        idx = g["index"].astype(float)
        w = g[wcols].astype(float).fillna(0.0)
        w.columns = [c[2:] for c in wcols]
        held = [t for t in w.columns if (w[t].abs() > 0).any()]
        if not held:
            continue
        miss = [t for t in held if t not in px.columns]
        if miss:
            rows.append({"id": pid, "error": f"가격 없음 {miss[:5]}"})
            continue
        p = px[held].reindex(g.index).ffill()
        ret = p.pct_change()
        model = (w[held].shift(1) * ret).sum(axis=1)
        eng = idx.pct_change()
        d = (eng - model).iloc[1:].abs()
        trade = {pd.Timestamp(x) for x in trade_days_by_pid.get(pid, set())}
        is_trade = pd.Series([ts in trade for ts in d.index], index=d.index)
        rows.append({"id": pid, "n_days": int(len(d)), "n_trade_days": int(is_trade.sum()),
                     "within_1bp_nontrade": int(((d <= 1e-4) & ~is_trade).sum()), "n_nontrade": int((~is_trade).sum()),
                     "within_10bp_all": int((d <= 1e-3).sum()), "max_diff_nontrade": float(d[~is_trade].max()) if (~is_trade).any() else 0.0,
                     "max_diff_trade": float(d[is_trade].max()) if is_trade.any() else 0.0,
                     "worst_day": str(d.idxmax().date()) if len(d) else None})
    return rows


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--runs", required=True)
    ap.add_argument("--out", required=True)
    a = ap.parse_args()
    settings = AnalysisSettings.load()
    repo = open_analysis_repository(None)
    pairs = [ln.split() for ln in Path(a.runs).read_text().splitlines() if ln.strip()]
    outp = Path(a.out)
    done = {json.loads(ln)["run_id"] for ln in outp.read_text().splitlines() if ln.strip()} if outp.exists() else set()
    for name, run_id in pairs:
        if run_id in done:
            continue
        rec = {"name": name, "run_id": run_id}
        try:
            d = OUT / run_id
            bt = json.loads((d / "11_backtest_results.json").read_text(encoding="utf-8"))
            panel = pd.read_parquet(d / "11_daily_panel.parquet")
            rf = float((bt.get("engine") or {}).get("risk_free_rate") or 0.0)
            rec["headline"] = headline_check(panel, bt, rf)
            req = json.loads((d / "01_request.json").read_text(encoding="utf-8"))
            as_of = dt.date.fromisoformat(str(req["derived"]["as_of"]))
            tickers = sorted({c[2:] for c in panel.columns if c.startswith("w_")})
            start = pd.to_datetime(panel["date"]).min().date()
            end = pd.to_datetime(panel["date"]).max().date()
            view = MarketData(repo, settings).view(as_of)
            px = view.adj_close(tickers, start - dt.timedelta(days=10), end, strict_before=False, usd=True, fill=True)
            rec["daily"] = daily_check(panel, px, bt)
        except Exception as e:  # noqa: BLE001
            rec["error"] = f"{type(e).__name__}: {e}"[:300]
            rec["trace"] = traceback.format_exc()[-1500:]
        with outp.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(rec, ensure_ascii=False) + "\n")
        hl = rec.get("headline") or []
        dl = [x for x in rec.get("daily") or [] if "n_days" in x]
        nt = sum(x["n_nontrade"] for x in dl)
        ok1 = sum(x["within_1bp_nontrade"] for x in dl)
        print(f"{name}: 지표 {sum(1 for x in hl if x['ok'])}/{len(hl)} · 일별(거래 없는 날 1bp 안) {ok1}/{nt} {rec.get('error', '')}", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
