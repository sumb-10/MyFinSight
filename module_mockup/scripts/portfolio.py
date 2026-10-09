"""Portfolio math shared by stages 8 and 10 (and later the backtest/report).

All estimation uses data strictly before `as_of` (no look-ahead).
"""
import datetime as dt
import numpy as np
import pandas as pd
import pyarrow.parquet as pq
from scipy.optimize import minimize
from common import RAW
import portfolio_config as PC


# ───────────────────────── data ─────────────────────────
def load_adj_close(tickers, start, end) -> pd.DataFrame:
    t = pq.read_table(RAW / "prices.parquet", columns=["date", "ticker", "adj_close", "close"],
                      filters=[("ticker", "in", list(tickers)), ("date", ">=", pd.Timestamp(start)),
                               ("date", "<=", pd.Timestamp(end))]).to_pandas()
    return t.pivot(index="date", columns="ticker", values="adj_close").sort_index()


def last_close(tickers, as_of) -> pd.Series:
    t = pq.read_table(RAW / "prices.parquet", columns=["date", "ticker", "close"],
                      filters=[("ticker", "in", list(tickers)), ("date", ">", pd.Timestamp(as_of) - pd.Timedelta(days=10)),
                               ("date", "<=", pd.Timestamp(as_of))]).to_pandas()
    return t.sort_values("date").groupby("ticker")["close"].last()


def trading_days(start, end, bench="SPY") -> pd.DatetimeIndex:
    t = pq.read_table(RAW / "benchmarks.parquet", columns=["date", "ticker"],
                      filters=[("ticker", "==", bench), ("date", ">=", pd.Timestamp(start)), ("date", "<=", pd.Timestamp(end))]).to_pandas()
    return pd.DatetimeIndex(sorted(t["date"].unique()))


# ───────────────────────── market model ─────────────────────────
def estimate_market_model(tickers, as_of, lookback_days=PC.LOOKBACK_DAYS, shrinkage=PC.SHRINKAGE):
    """Annualized covariance from daily log returns on the `lookback_days` trading days before as_of."""
    px = load_adj_close(tickers, pd.Timestamp(as_of) - pd.Timedelta(days=int(lookback_days * 1.6) + 30), as_of)
    px = px[px.index < pd.Timestamp(as_of)].tail(lookback_days)
    r = np.log(px).diff().dropna(how="all")
    keep = [t for t in tickers if t in r.columns and r[t].notna().sum() >= PC.MIN_HISTORY_DAYS_FOR_MODEL]
    dropped = [t for t in tickers if t not in keep]
    r = r[keep].dropna()
    X = r.to_numpy()
    if shrinkage == "ledoit_wolf":
        from sklearn.covariance import LedoitWolf
        lw = LedoitWolf().fit(X)
        cov_d, alpha = lw.covariance_, float(lw.shrinkage_)
    else:
        cov_d, alpha = np.cov(X, rowvar=False), 0.0
    cov = cov_d * 252
    vol = np.sqrt(np.diag(cov))
    corr = cov / np.outer(vol, vol)
    return {"tickers": keep, "dropped": dropped, "cov": cov, "corr": corr, "ann_vol": vol,
            "window": {"start": str(r.index.min().date()), "end": str(r.index.max().date()), "days": int(len(r))},
            "shrinkage": {"method": shrinkage, "alpha": alpha}, "mean_daily": r.mean().to_numpy()}


def cap_weights(tickers, as_of, shares: dict) -> np.ndarray:
    px = last_close(tickers, as_of)
    mc = np.array([float(shares.get(t) or 0) * float(px.get(t, np.nan)) for t in tickers])
    mc = np.nan_to_num(mc, nan=0.0)
    return mc / mc.sum() if mc.sum() > 0 else np.full(len(tickers), 1 / len(tickers))


def implied_returns(cov, w, delta):
    return delta * cov @ w


# ───────────────────────── constraints ─────────────────────────
def apply_constraints(w, max_stock, max_sector, sectors, total=1.0, max_iter=PC.MAX_ITER):
    """Scale w to `total`, then iteratively cap per-stock and per-sector weights, redistributing the
    excess to uncapped names in proportion to their weight. Returns (w, applied_constraint_labels)."""
    w = np.asarray(w, float).copy()
    w = w / w.sum() * total
    sectors = np.asarray(sectors)
    applied = set()
    for _ in range(max_iter):
        over = w > max_stock + 1e-12
        if over.any():
            applied.update(f"stock_cap:{i}" for i in np.where(over)[0])
            w[over] = max_stock
        for s in np.unique(sectors):
            m = sectors == s
            if w[m].sum() > max_sector * total / 1.0 + 1e-12:
                applied.add(f"sector_cap:{s}")
                w[m] *= (max_sector * total) / w[m].sum()
        deficit = total - w.sum()
        if abs(deficit) < 1e-10:
            break
        free = (w < max_stock - 1e-12)
        for s in np.unique(sectors):
            m = sectors == s
            if w[m].sum() >= max_sector * total - 1e-12:
                free &= ~m
        if not free.any() or w[free].sum() <= 0:
            break
        w[free] += deficit * w[free] / w[free].sum()
    return w, sorted(applied)


def _sector_constraints(sectors, max_sector, total):
    cons = []
    for s in np.unique(sectors):
        m = (np.asarray(sectors) == s).astype(float)
        cons.append({"type": "ineq", "fun": (lambda w, m=m: max_sector * total - m @ w)})
    return cons


def min_variance(cov, max_stock, max_sector, sectors, total=1.0):
    n = cov.shape[0]
    cons = [{"type": "eq", "fun": lambda w: w.sum() - total}] + _sector_constraints(sectors, max_sector, total)
    res = minimize(lambda w: w @ cov @ w, np.full(n, total / n), method="SLSQP",
                   bounds=[(0, max_stock)] * n, constraints=cons, options={"maxiter": 500, "ftol": 1e-12})
    if not res.success:
        raise RuntimeError(f"min_variance failed: {res.message}")
    return np.clip(res.x, 0, None)


def template_weights(template, cov, ann_vol, capw, max_stock, max_sector, sectors, total=1.0):
    n = cov.shape[0]
    if template == "equal_weight":
        w0 = np.full(n, 1 / n)
    elif template == "market_cap":
        w0 = capw
    elif template == "inverse_volatility":
        w0 = 1 / ann_vol
    elif template == "min_variance":
        return min_variance(cov, max_stock, max_sector, sectors, total), ["optimizer_constraints"]
    else:
        raise ValueError(template)
    return apply_constraints(w0, max_stock, max_sector, sectors, total)


# ───────────────────────── black-litterman ─────────────────────────
def build_PQ(views, tickers):
    idx = {t: i for i, t in enumerate(tickers)}
    P, Q, C = [], [], []
    for v in views:
        p = np.zeros(len(tickers))
        for t in v["long"]:
            p[idx[t]] += 1 / len(v["long"])
        for t in v.get("short", []):
            p[idx[t]] -= 1 / len(v["short"])
        P.append(p); Q.append(v["expected_return_annual"]); C.append(v["confidence"])
    return np.array(P), np.array(Q), np.array(C)


def black_litterman(cov, pi, P, Q, conf, tau=PC.TAU):
    """Posterior mean/cov. Omega_kk = (1/c_k - 1) * p_k (tau Sigma) p_k'  (c=1 -> near-certain view)."""
    if len(P) == 0:
        return pi.copy(), cov.copy()
    tS = tau * cov
    omega = np.diag([(1 / max(min(c, 0.999), 1e-6) - 1) * float(p @ tS @ p) + 1e-12 for p, c in zip(P, conf)])
    tS_inv = np.linalg.inv(tS)
    om_inv = np.linalg.inv(omega)
    M = np.linalg.inv(tS_inv + P.T @ om_inv @ P)
    mu = M @ (tS_inv @ pi + P.T @ om_inv @ Q)
    return mu, cov + M


def optimize_utility(mu, cov, delta, w_base, max_stock, max_sector, sectors, max_tilt, total=1.0):
    """max w'mu - delta/2 w'Σw  s.t. sum=total, 0<=w<=max_stock, |w-w_base|<=max_tilt, sector caps."""
    n = len(mu)
    lo = np.maximum(0, w_base - max_tilt); hi = np.minimum(max_stock, w_base + max_tilt)
    cons = [{"type": "eq", "fun": lambda w: w.sum() - total}] + _sector_constraints(sectors, max_sector, total)
    res = minimize(lambda w: -(w @ mu - delta / 2 * w @ cov @ w), w_base, method="SLSQP",
                   bounds=list(zip(lo, hi)), constraints=cons, options={"maxiter": 500, "ftol": 1e-12})
    if not res.success:
        raise RuntimeError(f"optimize_utility failed: {res.message}")
    w = np.clip(res.x, lo, hi)
    active = []
    for i in range(n):
        if abs(w[i] - hi[i]) < 1e-6: active.append(f"upper:{i}")
        elif abs(w[i] - lo[i]) < 1e-6 and lo[i] > 0: active.append(f"lower:{i}")
    for s in np.unique(sectors):
        m = np.asarray(sectors) == s
        if abs(w[m].sum() - max_sector * total) < 1e-6: active.append(f"sector_cap:{s}")
    return w, active


def ex_ante_stats(w, mu, cov):
    er = float(w @ mu); vol = float(np.sqrt(w @ cov @ w))
    return {"exp_return": round(er, 6), "vol": round(vol, 6), "sharpe": round(er / vol, 4) if vol > 0 else 0.0,
            "effective_n": round(float(1 / np.sum(w ** 2)), 3) if np.sum(w ** 2) > 0 else 0.0}


def sector_weights(w, sector_names):
    out = {}
    for wi, s in zip(w, sector_names):
        out[s] = out.get(s, 0.0) + float(wi)
    return {k: round(v, 6) for k, v in out.items()}


# ───────────────────────── self test ─────────────────────────
def _selftest():
    import json
    tickers = ["MU", "WDC", "STX", "GOOGL", "AMZN", "DLR", "EQIX", "ETN", "VRT", "CIEN"]
    sectors = ["IT", "IT", "IT", "COM", "CD", "RE", "RE", "IND", "IND", "IT"]
    mm = estimate_market_model(tickers, dt.date(2026, 4, 1))
    cov, tk = mm["cov"], mm["tickers"]; n = len(tk)
    assert np.all(np.linalg.eigvalsh(cov) > 0), "cov not PD"
    assert mm["window"]["end"] < "2026-04-01", "look-ahead in window"
    wb, _ = template_weights("equal_weight", cov, mm["ann_vol"], None, 0.15, 0.4, sectors)
    pi = implied_returns(cov, wb, 2.5)
    # (a) no views -> baseline
    mu0, cov0 = black_litterman(cov, pi, np.zeros((0, n)), np.zeros(0), np.zeros(0))
    w0, _ = optimize_utility(mu0, cov0, 2.5, wb, 0.15, 0.4, sectors, 0.05)
    assert np.max(np.abs(w0 - wb)) < 1e-3, f"no-view BL != baseline (max diff {np.max(np.abs(w0-wb)):.4f})"
    # (b) absolute view "MU = prior + 10%p" conf 0.5 -> posterior up, weight up
    i = tk.index("MU")
    P, Q, C = build_PQ([{"long": ["MU"], "short": [], "expected_return_annual": float(pi[i]) + 0.10, "confidence": 0.5}], tk)
    mu1, cov1 = black_litterman(cov, pi, P, Q, C)
    assert mu1[i] > pi[i], "absolute view did not raise MU posterior"
    w1, act = optimize_utility(mu1, cov1, 2.5, wb, 0.15, 0.4, sectors, 0.05)
    assert w1[i] - wb[i] > 1e-4, "MU weight did not increase"
    assert np.max(np.abs(w1 - wb)) <= 0.05 + 1e-6, "tilt cap violated"
    # (c) relative view DLR/EQIX over WDC/STX +10%
    P, Q, C = build_PQ([{"long": ["DLR", "EQIX"], "short": ["WDC", "STX"], "expected_return_annual": 0.1, "confidence": 0.4}], tk)
    mu2, cov2 = black_litterman(cov, pi, P, Q, C)
    w2, _ = optimize_utility(mu2, cov2, 2.5, wb, 0.15, 0.4, sectors, 0.05)
    d = w2 - wb
    assert d[tk.index("DLR")] + d[tk.index("EQIX")] > 0 and d[tk.index("WDC")] + d[tk.index("STX")] < 0, "relative view direction wrong"
    # min variance <= equal weight vol
    wmv, _ = template_weights("min_variance", cov, mm["ann_vol"], None, 0.15, 0.4, sectors)
    assert np.sqrt(wmv @ cov @ wmv) <= np.sqrt(wb @ cov @ wb) + 1e-9
    # cap-and-redistribute respects caps
    wc, applied = apply_constraints(np.array([0.5, 0.3] + [0.2 / (n - 2)] * (n - 2)), 0.15, 0.4, sectors)
    assert wc.max() <= 0.15 + 1e-9 and abs(wc.sum() - 1) < 1e-9, "caps violated"
    print("implied returns (equal-weight prior, delta=2.5):", {t: round(float(x), 3) for t, x in zip(tk, pi)})
    print(f"selftest OK  (window {mm['window']}, shrink alpha={mm['shrinkage']['alpha']:.3f}, MU Δ={w1[i]-wb[i]:+.4f}, "
          f"minvar vol={np.sqrt(wmv@cov@wmv):.3f} vs eq {np.sqrt(wb@cov@wb):.3f}, caps applied={applied})")


if __name__ == "__main__":
    _selftest()
