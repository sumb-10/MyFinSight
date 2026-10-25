"""포트폴리오 수학 (module_mockup/scripts/portfolio.py 에서 데이터 로더를 뗀 순수 numpy/scipy 부분).

입력은 모두 가격 표(date × ticker, USD)나 배열이다. 자료 접근은 MarketDataView 가 한다.
"""

from __future__ import annotations

from typing import Any

import numpy as np
import pandas as pd
from scipy.optimize import minimize


# ───────────────────────── market model ─────────────────────────
def estimate_market_model(px: pd.DataFrame, tickers: list[str], *, lookback_days: int, min_history_days: int, shrinkage: str) -> dict[str, Any]:
    """일별 로그수익률(최근 lookback_days 거래일)로 연율 공분산. px 는 as_of 이전 자료만 담고 있어야 한다."""
    px = px.tail(lookback_days + 1)
    r = np.log(px).diff().dropna(how="all")
    keep = [t for t in tickers if t in r.columns and r[t].notna().sum() >= min_history_days]
    dropped = [t for t in tickers if t not in keep]
    r = r[keep].dropna()
    if len(keep) < 2 or len(r) < min_history_days:
        raise ValueError(f"not enough return history: tickers={len(keep)} days={len(r)} (need >= {min_history_days})")
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
    return {
        "tickers": keep,
        "dropped": dropped,
        "cov": cov,
        "corr": corr,
        "ann_vol": vol,
        "window": {"start": str(r.index.min().date()), "end": str(r.index.max().date()), "days": int(len(r))},
        "shrinkage": {"method": shrinkage, "alpha": alpha},
        "mean_daily": r.mean().to_numpy(),
    }


def cap_weights(tickers: list[str], market_cap_usd: dict[str, float]) -> np.ndarray:
    mc = np.array([float(market_cap_usd.get(t) or 0.0) for t in tickers])
    mc = np.nan_to_num(mc, nan=0.0)
    return mc / mc.sum() if mc.sum() > 0 else np.full(len(tickers), 1 / len(tickers))


def implied_returns(cov: np.ndarray, w: np.ndarray, delta: float) -> np.ndarray:
    return delta * cov @ w


def market_implied_delta(bench_px: pd.Series, *, lookback_days: int, rf: float) -> tuple[float, dict[str, Any]]:
    """delta = E[r_m − rf] / Var(r_m), 비교지수 일별 수익률 (as_of 이전 창)."""
    px = bench_px.dropna().tail(lookback_days + 1)
    r = np.log(px).diff().dropna()
    if len(r) < 60:
        raise ValueError("benchmark history too short for market-implied delta")
    d = float((r.mean() - rf / 252) / r.var(ddof=1))
    return d, {"start": str(r.index.min().date()), "end": str(r.index.max().date()), "days": int(len(r))}


# ───────────────────────── constraints ─────────────────────────
def apply_constraints(w, max_stock, max_sector, sectors, total=1.0, *, max_iter=50, min_weight=0.01):
    """w 를 total 로 맞추고 min_weight ≤ w_i ≤ max_stock, 섹터 ≤ max_sector 를 반복 적용. (w, 적용된 제약 라벨)."""
    w = np.asarray(w, float).copy()
    w = w / w.sum() * total
    sectors = np.asarray(sectors)
    applied: set[str] = set()
    for _ in range(max_iter):
        low = w < min_weight - 1e-12
        if low.any():
            applied.update(f"min_weight:{i}" for i in np.where(low)[0])
            w[low] = min_weight
        over = w > max_stock + 1e-12
        if over.any():
            applied.update(f"stock_cap:{i}" for i in np.where(over)[0])
            w[over] = max_stock
        for s in np.unique(sectors):
            m = sectors == s
            if w[m].sum() > max_sector + 1e-12:
                applied.add(f"sector_cap:{s}")
                w[m] = np.maximum(w[m] * max_sector / w[m].sum(), min_weight)
        deficit = total - w.sum()
        if abs(deficit) < 1e-10:
            break
        free = (w < max_stock - 1e-12) & (w > min_weight + 1e-12) if deficit < 0 else (w < max_stock - 1e-12)
        for s in np.unique(sectors):
            m = sectors == s
            if deficit > 0 and w[m].sum() >= max_sector - 1e-12:
                free &= ~m
        if not free.any() or w[free].sum() <= 0:
            break
        w[free] += deficit * w[free] / w[free].sum()
    return w, sorted(applied)


def _sector_constraints(sectors, max_sector, total):
    """섹터 상한(절대 비중)을 부등식으로. 총액 이상이면 묶이지 않으므로 생략 (SLSQP 가 'incompatible' 을 내지 않게)."""
    cons = []
    if max_sector >= total - 1e-9:
        return cons
    for s in np.unique(sectors):
        m = (np.asarray(sectors) == s).astype(float)
        cons.append({"type": "ineq", "fun": (lambda w, m=m: max_sector - m @ w)})
    return cons


def weight_capacity(sectors, max_stock, max_sector) -> float:
    """종목·섹터 상한 안에서 둘 수 있는 최대 총비중 Σ_sector min(k × 종목 상한, 섹터 상한)."""
    sectors = np.asarray(sectors)
    return float(sum(min(int((sectors == s).sum()) * max_stock, max_sector) for s in np.unique(sectors)))


def min_variance(cov, max_stock, max_sector, sectors, total=1.0, *, min_weight=0.01):
    n = cov.shape[0]
    cons = [{"type": "eq", "fun": lambda w: w.sum() - total}] + _sector_constraints(sectors, max_sector, total)
    res = minimize(lambda w: w @ cov @ w, np.full(n, total / n), method="SLSQP", bounds=[(min_weight, max_stock)] * n,
                   constraints=cons, options={"maxiter": 500, "ftol": 1e-12})  # fmt: skip
    if res.success and abs(res.x.sum() - total) < 1e-6:
        return np.clip(res.x, min_weight, None), ["optimizer_constraints"]
    # 최적화 실패(상한이 빡빡하거나 선형탐색 실패): 1/σ² 비중에 제약을 적용한 근사로 대체
    w, applied = apply_constraints(1 / np.diag(cov), max_stock, max_sector, sectors, total, min_weight=min_weight)
    return w, ["min_variance_fallback(1/var)", *applied]


def template_weights(template, cov, ann_vol, capw, max_stock, max_sector, sectors, total=1.0, *, min_weight=0.01, max_iter=50):
    n = cov.shape[0]
    if template == "equal_weight":
        w0 = np.full(n, 1 / n)
    elif template == "market_cap":
        w0 = capw
    elif template == "inverse_volatility":
        w0 = 1 / ann_vol
    elif template == "min_variance":
        return min_variance(cov, max_stock, max_sector, sectors, total, min_weight=min_weight)
    else:
        raise ValueError(template)
    return apply_constraints(w0, max_stock, max_sector, sectors, total, max_iter=max_iter, min_weight=min_weight)


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
        P.append(p)
        Q.append(v["expected_return_annual"])
        C.append(v["confidence"])
    return np.array(P), np.array(Q), np.array(C)


def black_litterman(cov, pi, P, Q, conf, tau):
    """사후 평균·공분산. Ω_kk = (1/c_k − 1)·p_k(τΣ)p_k' (He-Litterman 신뢰도 변환)."""
    if len(P) == 0:
        return pi.copy(), cov.copy()
    tS = tau * cov
    omega = np.diag([(1 / max(min(c, 0.999), 1e-6) - 1) * float(p @ tS @ p) + 1e-12 for p, c in zip(P, conf, strict=True)])
    tS_inv = np.linalg.inv(tS)
    om_inv = np.linalg.inv(omega)
    M = np.linalg.inv(tS_inv + P.T @ om_inv @ P)
    mu = M @ (tS_inv @ pi + P.T @ om_inv @ Q)
    return mu, cov + M


def optimize_utility(mu, cov, delta, w_base, max_stock, max_sector, sectors, max_tilt, total=1.0, *, min_weight=0.01):
    """max w'μ − δ/2 w'Σw  s.t. Σw = total, min_weight ≤ w ≤ max_stock, |w − w_base| ≤ max_tilt, 섹터 상한."""
    n = len(mu)
    w_base = np.asarray(w_base, float)
    w_base = w_base / w_base.sum() * total
    lo = np.maximum(min_weight, w_base - max_tilt)
    hi = np.maximum(lo + 1e-9, np.minimum(max_stock, w_base + max_tilt))
    cons = [{"type": "eq", "fun": lambda w: w.sum() - total}] + _sector_constraints(sectors, max_sector, total)
    res = minimize(lambda w: -(w @ mu - delta / 2 * w @ cov @ w), w_base, method="SLSQP", bounds=list(zip(lo, hi, strict=True)),
                   constraints=cons, options={"maxiter": 500, "ftol": 1e-12})  # fmt: skip
    active = []
    if not res.success or abs(res.x.sum() - total) > 1e-6:
        # 최적화 실패: 뷰를 반영하지 않고 기준 비중 유지 (값을 지어내지 않음)
        return w_base.copy(), [f"optimizer_failed_no_tilt({res.message})"]
    w = np.clip(res.x, lo, hi)
    for i in range(n):
        if abs(w[i] - hi[i]) < 1e-6:
            active.append(f"upper:{i}")
        elif abs(w[i] - lo[i]) < 1e-6 and lo[i] > 0:
            active.append(f"lower:{i}")
    for s in np.unique(sectors):
        m = np.asarray(sectors) == s
        if abs(w[m].sum() - max_sector) < 1e-6:
            active.append(f"sector_cap:{s}")
    return w, active


def ex_ante_stats(w, mu, cov) -> dict[str, float]:
    er = float(w @ mu)
    vol = float(np.sqrt(w @ cov @ w))
    ss = float(np.sum(w**2))
    return {"exp_return": round(er, 6), "vol": round(vol, 6), "sharpe": round(er / vol, 4) if vol > 0 else 0.0,
            "effective_n": round(1 / ss, 3) if ss > 0 else 0.0}  # fmt: skip


def sector_weights(w, sector_names) -> dict[str, float]:
    out: dict[str, float] = {}
    for wi, s in zip(w, sector_names, strict=True):
        out[s] = out.get(s, 0.0) + float(wi)
    return {k: round(v, 6) for k, v in out.items()}
