"""백테스트 재현성 시험: 저장된 실행의 백테스트 입력(07 명세가 든 10_target_portfolios, 10w 경로, 요청, 의도, 시장모형)을
그대로 넣어 run_backtest 를 두 번 돌리고 (A, B), 저장된 11_backtest_results 와도 비교한다. LLM 은 쓰지 않는다.

  PYTHONPATH=. python docs/mvp/evaluation/scripts/bt_repro.py --runs runs.txt --out bt_repro.jsonl

비교하는 핵심 결과값 (포트폴리오·비교지수마다):
  headline 6개 (최종 평가액, CAGR, 기간 수익률, 비교지수 대비 초과 CAGR, 최대낙폭, Sharpe) + 일별 지수 시계열 + 리밸런싱 횟수.
"""

from __future__ import annotations

import argparse
import copy
import datetime as dt
import json
import math
import sys
import time
import traceback
from pathlib import Path

ROOT = Path(__file__).resolve().parents[0]
sys.path.insert(0, str(Path.cwd()))

from backend.analysis.common.dbconn import open_analysis_repository  # noqa: E402
from backend.analysis.m2_data import descriptor as D  # noqa: E402
from backend.analysis.m2_data.market_data import MarketData  # noqa: E402
from backend.analysis.m5_backtest_report.backtest import run_backtest  # noqa: E402
from backend.analysis.settings import AnalysisSettings  # noqa: E402

OUT = Path("output")
HEAD = ("final_value_usd", "cagr", "period_return", "excess_cagr", "max_drawdown", "sharpe")


def load(run_id: str, name: str):
    p = OUT / run_id / f"{name}.json"
    return json.loads(p.read_text(encoding="utf-8")) if p.exists() else None


def blocks(bt: dict) -> dict[str, dict]:
    out = {}
    for p in bt.get("portfolios", []) + bt.get("benchmarks", []):
        out[p["id"]] = {
            "head": {k: (p.get("headline") or {}).get(k) for k in HEAD},
            "index": list(((p.get("series") or {}).get("index")) or []),
            "n_reb": (((p.get("metrics") or {}).get("trading") or {}).get("n_rebalances")),
        }
    return out


def diff(a: dict[str, dict], b: dict[str, dict]) -> dict:
    """같은 id 끼리 비교. 값이 완전히 같으면 identical, 아니면 가장 큰 차이."""
    ids = sorted(set(a) | set(b))
    res = {"n": len(ids), "missing": [i for i in ids if i not in a or i not in b], "identical": 0, "head_max_abs": 0.0, "index_max_rel": 0.0, "differs": []}
    for i in ids:
        if i not in a or i not in b:
            continue
        x, y = a[i], b[i]
        hd = 0.0
        for k in HEAD:
            u, v = x["head"].get(k), y["head"].get(k)
            if u is None and v is None:
                continue
            if u is None or v is None:
                hd = math.inf
                continue
            if k == "final_value_usd":
                hd = max(hd, abs(u - v) / max(abs(u), 1e-9))
            else:
                hd = max(hd, abs(u - v))
        if len(x["index"]) != len(y["index"]):
            idd = math.inf
        else:
            idd = max((abs(p - q) / max(abs(p), 1e-12) for p, q in zip(x["index"], y["index"])), default=0.0)
        same = hd == 0.0 and idd == 0.0 and x["n_reb"] == y["n_reb"]
        res["identical"] += int(same)
        res["head_max_abs"] = max(res["head_max_abs"], hd)
        res["index_max_rel"] = max(res["index_max_rel"], idd)
        if not same:
            res["differs"].append({"id": i, "head_max": hd, "index_max_rel": idd, "n_reb": [x["n_reb"], y["n_reb"]]})
    return res


def rerun(md: MarketData, settings: AnalysisSettings, run_id: str) -> dict:
    req = load(run_id, "01_request")
    targets = load(run_id, "10_target_portfolios")
    intent = load(run_id, "02_intent")
    mm = load(run_id, "08_market_model")
    wf = load(run_id, "10w_target_paths")
    ms = settings.market
    as_of = dt.date.fromisoformat(str(req["derived"]["as_of"]))
    desc, _info, _w = D.load_for(as_of, req["constraints"]["universe"], ms.markets, processed_dir=ms.descriptor_dir or D.PROCESSED, universe_file=ms.descriptor_universe)
    bt, _ctx, _daily = run_backtest(md, copy.deepcopy(targets), copy.deepcopy(req), intent, mm, desc, settings, walkforward=copy.deepcopy(wf))
    return bt


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--runs", required=True, help="한 줄에 '시나리오 run_id'")
    ap.add_argument("--out", required=True)
    a = ap.parse_args()
    settings = AnalysisSettings.load()
    repo = open_analysis_repository(None)
    pairs = [ln.split() for ln in Path(a.runs).read_text().splitlines() if ln.strip()]
    done = set()
    outp = Path(a.out)
    if outp.exists():
        done = {json.loads(ln)["run_id"] for ln in outp.read_text().splitlines() if ln.strip()}
    for name, run_id in pairs:
        if run_id in done:
            continue
        rec = {"name": name, "run_id": run_id}
        try:
            stored = load(run_id, "11_backtest_results")
            if stored is None:
                raise FileNotFoundError("11_backtest_results 없음")
            t0 = time.time()
            bt_a = rerun(MarketData(repo, settings), settings, run_id)  # 실행마다 새 MarketData → 가격을 DB 에서 다시 읽음
            t1 = time.time()
            bt_b = rerun(MarketData(repo, settings), settings, run_id)
            t2 = time.time()
            A, B, S = blocks(bt_a), blocks(bt_b), blocks(stored)
            rec.update({"seconds": [round(t1 - t0, 1), round(t2 - t1, 1)], "a_vs_b": diff(A, B), "stored_vs_a": diff(S, A),
                        "trading_days": [stored["period"]["trading_days"], bt_a["period"]["trading_days"], bt_b["period"]["trading_days"]]})
        except Exception as e:  # noqa: BLE001
            rec["error"] = f"{type(e).__name__}: {e}"[:300]
            rec["trace"] = traceback.format_exc()[-1200:]
        with outp.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(rec, ensure_ascii=False) + "\n")
        ab = rec.get("a_vs_b", {})
        sa = rec.get("stored_vs_a", {})
        print(f"{name} {run_id}: A=B {ab.get('identical')}/{ab.get('n')} · 저장=A {sa.get('identical')}/{sa.get('n')} {rec.get('error', '')}", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
