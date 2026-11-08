"""적립일 수익률 처리(유입을 장 시작에 넣음)가 CAGR·최대낙폭에 주는 영향: 유입을 장 마감에 넣은 시간가중 지수로 다시 계산해 비교."""
import json, sys
from pathlib import Path
import numpy as np, pandas as pd
rows = []
for ln in open(sys.argv[1]):
    name, rid = ln.split()
    d = Path("output") / rid
    bt = json.load(open(d / "11_backtest_results.json"))
    panel = pd.read_parquet(d / "11_daily_panel.parquet")
    for p in bt.get("portfolios", []) + bt.get("benchmarks", []):
        led = {pd.Timestamp(str(x["date"])[:10]): float(x.get("amount_usd") or 0) for x in p.get("contribution_ledger") or []}
        if not led:
            continue
        g = panel[panel.portfolio_id == p["id"]].sort_values("date")
        if g.empty:
            continue
        dates = pd.to_datetime(g["date"]).to_numpy()
        V = g["value_usd"].to_numpy(float); I = g["index"].to_numpy(float)
        F = np.array([led.get(pd.Timestamp(x), 0.0) for x in dates])
        F[0] = 0.0
        r = np.empty(len(V)); r[0] = 0.0
        r[1:] = (V[1:] - F[1:]) / V[:-1] - 1
        J = 100 * np.cumprod(1 + r)
        yrs = (pd.Timestamp(dates[-1]) - pd.Timestamp(dates[0])).days / 365.25
        cg = lambda x: (x[-1] / x[0]) ** (1 / yrs) - 1
        mdd = lambda x: float(np.min(x / np.maximum.accumulate(x) - 1))
        rows.append({"name": name, "id": p["id"], "n_flows": int((F > 0).sum()), "d_cagr": cg(J) - cg(I), "d_mdd": mdd(J) - mdd(I), "d_total": J[-1] / J[0] - I[-1] / I[0]})
df = pd.DataFrame(rows)
print("portfolios with flows:", len(df), "scenarios:", df["name"].nunique())
for k in ("d_cagr", "d_mdd", "d_total"):
    a = df[k].abs()
    print(f"{k}: median |Δ| {a.median()*100:.3f}%p, 95% {a.quantile(.95)*100:.3f}%p, max {a.max()*100:.3f}%p, mean Δ {df[k].mean()*100:+.3f}%p")
print("share |Δcagr| < 0.1%p:", round((df.d_cagr.abs() < 0.001).mean(), 4), " share |Δmdd| < 0.5%p:", round((df.d_mdd.abs() < 0.005).mean(), 4))
df.to_csv(sys.argv[2], index=False)
