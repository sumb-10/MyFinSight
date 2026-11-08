"""적립일 수익률을 고친 엔진으로 항목 6 다시 채점.

실행마다 저장된 백테스트 입력으로 run_backtest 를 두 번(A, B) 돌려
  - 재현성: A = B (헤드라인 6개·일별 지수·리밸런싱 횟수)
  - 명세: A 의 지수 = 평가액·적립금으로 따로 계산한 거래일 끝 시간가중 지수
  - 계산 확인: A 의 일별 지수로 헤드라인 지표 재계산, 보유 비중 × DB 가격 수익률과 일별 대조(적립일 포함)
  - 영향: 저장된(고치기 전) 결과와 CAGR·최대낙폭 차이, 검증을 다시 돌려 추천 구성·라벨이 바뀌는지

  PYTHONPATH=. python bt_regrade.py <runs.txt> <out.jsonl>
"""

from __future__ import annotations

import copy
import datetime as dt
import json
import sys
import traceback
from pathlib import Path

import numpy as np
import pandas as pd

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(Path.cwd()))
from bt_repro import blocks, diff, load  # noqa: E402
from engine_check import daily_check, headline_check  # noqa: E402

from backend.analysis.common.dbconn import open_analysis_repository  # noqa: E402
from backend.analysis.m2_data import descriptor as D  # noqa: E402
from backend.analysis.m2_data.market_data import MarketData  # noqa: E402
from backend.analysis.m5_backtest_report.backtest import run_backtest  # noqa: E402
from backend.analysis.m5_backtest_report.validate import validate  # noqa: E402
from backend.analysis.settings import AnalysisSettings  # noqa: E402


def rerun(md, settings, run_id):
    req, targets, intent, mm, wf = (load(run_id, n) for n in ("01_request", "10_target_portfolios", "02_intent", "08_market_model", "10w_target_paths"))
    ms = settings.market
    as_of = dt.date.fromisoformat(str(req["derived"]["as_of"]))
    desc, _i, _w = D.load_for(as_of, req["constraints"]["universe"], ms.markets, processed_dir=ms.descriptor_dir or D.PROCESSED, universe_file=ms.descriptor_universe)
    tg = copy.deepcopy(targets)
    bt, ctx, daily = run_backtest(md, tg, copy.deepcopy(req), intent, mm, desc, settings, walkforward=copy.deepcopy(wf))
    val = validate(bt, tg, intent, copy.deepcopy(req), ctx, lambda t: ctx["sectors"].get(t, t), settings)
    return bt, daily, val, req


def spec_check(daily: pd.DataFrame, bt: dict) -> dict:
    """지수 = 100 × Π(1 + (V_t − C_t)/V_(t−1) − 1), C_t = 그날 적립금 (적립 원장)."""
    worst, n = 0.0, 0
    ports = {p["id"]: p for p in bt.get("portfolios", []) + bt.get("benchmarks", [])}
    for pid, g in daily.groupby("portfolio_id", sort=False):
        p = ports.get(pid)
        if p is None:
            continue
        g = g.sort_values("date")
        V = g["value_usd"].to_numpy(float)
        led = {str(x["date"])[:10]: float(x.get("amount_usd") or 0.0) for x in p.get("contribution_ledger") or []}
        F = np.array([led.get(str(pd.Timestamp(d).date()), 0.0) for d in g["date"]])
        F[0] = 0.0
        r = np.r_[0.0, (V[1:] - F[1:]) / V[:-1] - 1]
        J = 100 * np.cumprod(1 + r)
        I = g["index"].to_numpy(float)
        worst = max(worst, float(np.max(np.abs(J / I - 1))))
        n += 1
    return {"n": n, "max_rel_diff": worst}


def main() -> int:
    runs_txt, out_p = sys.argv[1], Path(sys.argv[2])
    settings = AnalysisSettings.load()
    repo = open_analysis_repository(None)
    pairs = [ln.split() for ln in Path(runs_txt).read_text().splitlines() if ln.strip()]
    done = {json.loads(ln)["run_id"] for ln in out_p.read_text().splitlines() if ln.strip()} if out_p.exists() else set()
    for name, run_id in pairs:
        if run_id in done:
            continue
        rec = {"name": name, "run_id": run_id}
        try:
            stored = load(run_id, "11_backtest_results")
            stored_val = load(run_id, "12_validation") or {}
            bt_a, daily_a, val_a, req = rerun(MarketData(repo, settings), settings, run_id)
            bt_b, _daily_b, val_b, _ = rerun(MarketData(repo, settings), settings, run_id)
            A, B, S = blocks(bt_a), blocks(bt_b), blocks(stored)
            rf = float((bt_a.get("engine") or {}).get("risk_free_rate") or 0.0)
            hl = headline_check(daily_a, bt_a, rf)
            as_of = dt.date.fromisoformat(str(req["derived"]["as_of"]))
            tickers = sorted({c[2:] for c in daily_a.columns if c.startswith("w_")})
            start = pd.to_datetime(daily_a["date"]).min().date()
            end = pd.to_datetime(daily_a["date"]).max().date()
            px = MarketData(repo, settings).view(as_of).adj_close(tickers, start - dt.timedelta(days=10), end, strict_before=False, usd=True, fill=True)
            dl = daily_check(daily_a, px, bt_a)
            flows = bool((bt_a.get("engine") or {}).get("n_contributions"))
            impact = []
            for pid, s in S.items():
                a = A.get(pid)
                if a and s["head"].get("cagr") is not None and a["head"].get("cagr") is not None:
                    impact.append({"id": pid, "d_cagr": a["head"]["cagr"] - s["head"]["cagr"], "d_mdd": a["head"]["max_drawdown"] - s["head"]["max_drawdown"]})
            lab = lambda v: str(((v.get("recommended") or {}).get("verdict") or {}).get("label_ko") or "")
            rec.update({"flows": flows, "a_vs_b": diff(A, B), "spec": spec_check(daily_a, bt_a),
                        "headline": {"n": len(hl), "ok": sum(1 for h in hl if h["ok"]), "checks": sum(h["n_checked"] for h in hl), "max_diff": max((h["max_diff"] for h in hl), default=0.0)},
                        "daily": [{k: x.get(k) for k in ("id", "n_days", "n_trade_days", "within_1bp_nontrade", "n_nontrade", "within_10bp_all", "max_diff_nontrade", "max_diff_trade")} for x in dl],
                        "impact": impact, "val_same_ab": val_a.get("chosen_id") == val_b.get("chosen_id") and lab(val_a) == lab(val_b),
                        "chosen": [stored_val.get("chosen_id"), val_a.get("chosen_id")], "label": [lab(stored_val), lab(val_a)]})
        except Exception as e:  # noqa: BLE001
            rec["error"] = f"{type(e).__name__}: {e}"[:300]
            rec["trace"] = traceback.format_exc()[-1500:]
        with out_p.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(rec, ensure_ascii=False) + "\n")
        ab = rec.get("a_vs_b", {})
        print(f"{name}: A=B {ab.get('identical')}/{ab.get('n')} · 명세 차이 {rec.get('spec', {}).get('max_rel_diff')} · 추천 {rec.get('chosen')} {rec.get('error', '')}", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
