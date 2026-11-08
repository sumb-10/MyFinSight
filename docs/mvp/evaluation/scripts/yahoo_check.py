"""정량값 일치: 백테스트에 쓴 종목·비교지수의 DB 가격을 원 출처(yfinance)의 지금 값과 일별 수익률로 대조한다.

- 수정종가(adj_close): DB 의 수정종가는 yfinance 에서 수집했다 → 수집 결과가 출처와 같은가 (수집 정확성).
- 종가(close): DB 종가는 한국 KIS, 미국 Alpaca 가 주 출처 → yfinance 종가와 다른 출처끼리 대조 (교차 검증). 분할일은 제외.
수익률로 비교하는 이유: 수정종가는 새 배당이 생기면 과거 값이 한꺼번에 비례 조정되므로 수준 값은 달라도 수익률은 같다.

  PYTHONPATH=. python docs/mvp/evaluation/scripts/yahoo_check.py qa_final_runs.txt out.json
"""

from __future__ import annotations

import datetime as dt
import json
import sys
import time
from collections import defaultdict
from pathlib import Path

import numpy as np
import pandas as pd
import yfinance as yf

sys.path.insert(0, str(Path.cwd()))
from backend.analysis.common.dbconn import open_analysis_repository  # noqa: E402
from backend.analysis.m2_data.market_data import MarketData  # noqa: E402
from backend.analysis.settings import AnalysisSettings  # noqa: E402


def windows(runs_txt: str) -> dict[str, list[dt.date]]:
    win: dict[str, list[dt.date]] = {}
    for ln in Path(runs_txt).read_text().splitlines():
        if not ln.strip():
            continue
        _name, rid = ln.split()
        bt = json.loads((Path("output") / rid / "11_backtest_results.json").read_text(encoding="utf-8"))
        panel = pd.read_parquet(Path("output") / rid / "11_daily_panel.parquet", columns=None)
        s = pd.to_datetime(panel["date"]).min().date()
        e = pd.to_datetime(panel["date"]).max().date()
        ticks = {c[2:] for c in panel.columns if c.startswith("w_")}
        for t in ticks:
            w = win.setdefault(t, [s, e])
            w[0], w[1] = min(w[0], s), max(w[1], e)
    return win


def yahoo(tickers: list[str], start: dt.date, end: dt.date) -> dict[str, pd.DataFrame]:
    out = {}
    for i in range(0, len(tickers), 40):
        chunk = tickers[i : i + 40]
        for attempt in range(3):
            try:
                df = yf.download(chunk, start=str(start), end=str(end + dt.timedelta(days=3)), auto_adjust=False, actions=False, progress=False, group_by="ticker", threads=True)
                break
            except Exception:  # noqa: BLE001
                time.sleep(5 * (attempt + 1))
        else:
            continue
        for t in chunk:
            try:
                sub = df[t] if isinstance(df.columns, pd.MultiIndex) else df
                sub = sub[["Close", "Adj Close"]].dropna(how="all")
                if len(sub):
                    sub.index = pd.to_datetime(sub.index).tz_localize(None).normalize()
                    out[t] = sub
            except KeyError:
                pass
        time.sleep(1.0)
    return out


def main() -> int:
    runs_txt, out_p = sys.argv[1], Path(sys.argv[2])
    win = windows(runs_txt)
    tickers = sorted(win)
    s = AnalysisSettings.load()
    repo = open_analysis_repository(None)
    md = MarketData(repo, s)
    start = min(w[0] for w in win.values())
    end = max(w[1] for w in win.values())
    db = md.bars(tickers, start - dt.timedelta(days=7), end)
    yf_data = yahoo(tickers, start - dt.timedelta(days=7), end)
    res = {}
    agg = defaultdict(int)
    for t in tickers:
        w0, w1 = win[t]
        g = db[db["ticker"] == t].copy()
        if g.empty or t not in yf_data:
            res[t] = {"status": "no_db" if g.empty else "no_yahoo"}
            agg["no_db" if g.empty else "no_yahoo"] += 1
            continue
        g["date"] = pd.to_datetime(g["date"]).dt.normalize()
        g = g.set_index("date").sort_index()
        y = yf_data[t]
        common = g.index.intersection(y.index)
        common = common[(common >= pd.Timestamp(w0)) & (common <= pd.Timestamp(w1))]
        if len(common) < 20:
            res[t] = {"status": "few_common", "n": int(len(common))}
            agg["few_common"] += 1
            continue
        one = {"status": "ok", "n_days": int(len(common)) - 1, "db_days_in_window": int(((g.index >= pd.Timestamp(w0)) & (g.index <= pd.Timestamp(w1))).sum()),
               "yahoo_days_in_window": int(((y.index >= pd.Timestamp(w0)) & (y.index <= pd.Timestamp(w1))).sum())}
        for col_db, col_y, key in (("adj_close", "Adj Close", "adj"), ("close", "Close", "close")):
            a = g.loc[common, col_db].astype(float)
            b = y.loc[common, col_y].astype(float)
            ra, rb = a.pct_change().iloc[1:], b.pct_change().iloc[1:]
            d = (ra - rb).abs()
            if key == "close":
                # 분할·액면 변경일: 두 출처 중 하나만 분할 반영 → 비율이 정수배에 가까운 날은 제외
                ratio = (1 + ra) / (1 + rb)
                split = (ratio.round(2).isin([0.5, 2.0, 0.33, 3.0, 0.25, 4.0, 0.2, 5.0, 0.1, 10.0])) | (ratio > 1.8) | (ratio < 0.55)
                d = d[~split]
                one["close_split_days_skipped"] = int(split.sum())
            one[f"{key}_n"] = int(d.notna().sum())
            one[f"{key}_within_10bp"] = int((d <= 0.001).sum())
            one[f"{key}_within_50bp"] = int((d <= 0.005).sum())
            one[f"{key}_max"] = float(d.max()) if len(d) else 0.0
            one[f"{key}_worst"] = str(d.idxmax().date()) if len(d) and d.notna().any() else None
            agg[f"{key}_n"] += one[f"{key}_n"]
            agg[f"{key}_within_10bp"] += one[f"{key}_within_10bp"]
            agg[f"{key}_within_50bp"] += one[f"{key}_within_50bp"]
        res[t] = one
        agg["tickers_ok"] += 1
    summary = {"tickers": len(tickers), "window": [str(start), str(end)], **agg}
    for key in ("adj", "close"):
        if agg[f"{key}_n"]:
            summary[f"{key}_rate_10bp"] = round(agg[f"{key}_within_10bp"] / agg[f"{key}_n"], 6)
            summary[f"{key}_rate_50bp"] = round(agg[f"{key}_within_50bp"] / agg[f"{key}_n"], 6)
    worst = sorted(((t, r.get("adj_max", 0), r.get("adj_worst")) for t, r in res.items() if r.get("status") == "ok"), key=lambda x: -x[1])[:15]
    summary["worst_adj"] = worst
    summary["worst_close"] = sorted(((t, r.get("close_max", 0), r.get("close_worst")) for t, r in res.items() if r.get("status") == "ok"), key=lambda x: -x[1])[:15]
    out_p.write_text(json.dumps({"summary": summary, "per_ticker": res}, ensure_ascii=False, indent=1, default=str), encoding="utf-8")
    print(json.dumps(summary, ensure_ascii=False, indent=1, default=str))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
