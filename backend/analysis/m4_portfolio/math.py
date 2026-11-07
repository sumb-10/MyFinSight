"""포트폴리오 수학 (module_mockup/scripts/portfolio.py 에서 데이터 로더를 뗀 순수 numpy/scipy 부분).

입력은 모두 가격 표(date × ticker, USD)나 배열이다. 자료 접근은 MarketDataView 가 한다.
"""

from __future__ import annotations

from typing import Any

import numpy as np
import pandas as pd
from scipy.optimize import minimize

from backend.analysis.errors import DataMissing


# ───────────────────────── market model ─────────────────────────
def estimate_market_model(px: pd.DataFrame, tickers: list[str], *, lookback_days: int, min_history_days: int, shrinkage: str) -> dict[str, Any]:
    """일별 로그수익률(최근 lookback_days 거래일)로 연율 공분산. px 는 as_of 이전 자료만 담고 있어야 한다."""
    px = px.tail(lookback_days + 1)
    r = np.log(px).diff().dropna(how="all")
    keep = [t for t in tickers if t in r.columns and r[t].notna().sum() >= min_history_days]
    dropped = [t for t in tickers if t not in keep]
    r = r[keep].dropna()
    if len(keep) < 1 or len(r) < min_history_days:  # 1종목도 받는다 (F2: 시작일 선정이 1종목이면 10 단계 전체가 멈췄다)
        raise DataMissing(f"시장모형을 만들 수 있는 종목이 없습니다 (추정 창 수익률이 {min_history_days}일 이상인 종목 {len(keep)}개, 공통 {len(r)}일)",
                          details={"tickers": len(keep), "days": len(r), "need": min_history_days})
    window = {"start": str(r.index.min().date()), "end": str(r.index.max().date()), "days": int(len(r))}
    if len(r) < lookback_days:  # 공통 창을 줄인 늦게 상장한 종목 (023: 카카오뱅크 때문에 756일이 아니라 487일이었는데 표에는 756일로 나왔다)
        ra = np.log(px).diff().iloc[1:][keep]
        first = {t: ra[t].first_valid_index() for t in keep}
        latest = max(first.values())
        if latest > ra.index[0]:
            window["limited_by"] = sorted(t for t, d0 in first.items() if d0 == latest)
    X = r.to_numpy()
    if shrinkage == "ledoit_wolf":
        from sklearn.covariance import LedoitWolf

        lw = LedoitWolf().fit(X)
        cov_d, alpha = lw.covariance_, float(lw.shrinkage_)
    else:
        cov_d, alpha = np.atleast_2d(np.cov(X, rowvar=False)), 0.0  # 1종목이면 np.cov 가 0차원 배열을 돌려준다
    cov = cov_d * 252
    vol = np.sqrt(np.diag(cov))
    corr = cov / np.outer(vol, vol)
    return {
        "tickers": keep,
        "dropped": dropped,
        "cov": cov,
        "corr": corr,
        "ann_vol": vol,
        "window": window,
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
def _pl_root(knots, vals, target):
    """오름차순 knots 위의 비감소 꺾은선 vals 가 target 이 되는 점. 꺾이는 점 사이는 일차식이라 직선 보간이 정확한 답이다."""
    vals = np.maximum.accumulate(vals)  # 반올림으로 생긴 아주 작은 역전 제거
    j = int(np.searchsorted(vals, target, side="left"))
    if j == 0 or j == len(knots):
        return float(knots[min(j, len(knots) - 1)])
    t = (target - vals[j - 1]) / (vals[j] - vals[j - 1])
    return float(knots[j - 1] + t * (knots[j] - knots[j - 1]))


def _capped_fill(a, lo, hi, sec, cap, total):
    """w_i = clip(f_s·a_i, lo, hi), f_s = min(λ, μ_s). μ_s: 섹터 s 합이 cap[s] 가 되는 수준 (바닥만으로 cap 이상이면 0, 끝까지 안 넘으면 ∞).
    λ: 합계가 total 이 되는 수준 (바닥 합이 이미 넘으면 0, 상한 안에서 다 못 채우면 모든 꺾이는 점 너머 = 모두 최대치).
    (w, 자르기 전 값 f·a, 섹터 상한이 누른 섹터)."""
    pos = a > 0
    mu = np.full(len(cap), np.inf)
    for s in range(len(cap)):
        aa = a[sec == s]
        p = aa > 0
        if len(aa) * lo >= cap[s]:
            mu[s] = 0.0
        elif np.where(p, hi, lo).sum() > cap[s]:
            k = np.unique(np.concatenate([[0.0], lo / aa[p], hi / aa[p]]))
            mu[s] = _pl_root(k, np.clip(k[:, None] * aa, lo, hi).sum(axis=1), cap[s])
    k = np.unique(np.concatenate([[0.0], lo / a[pos], hi / a[pos], mu[np.isfinite(mu)]]))
    F = np.clip(np.minimum(k[:, None], mu[sec]) * a, lo, hi).sum(axis=1)
    # 딱 채울 수 있는 경우는 반올림 1ulp 차이로 '못 채움' 쪽에 빠지지 않게 (검토: 섹터 상한 100% · 전액 투자면 섹터 상한이 걸린 것처럼 라벨이 붙었다)
    lam = 2 * k[-1] + 1 if total > F[-1] + 1e-12 else _pl_root(k, F, min(total, F[-1]))
    x = np.minimum(lam, mu[sec]) * a
    over = np.bincount(sec, weights=np.clip(lam * a, lo, hi), minlength=len(cap)) > cap + 1e-12
    return np.clip(x, lo, hi), x, over


def apply_constraints(w, max_stock, max_sector, sectors, total=1.0, *, max_iter=50, min_weight=0.01):
    """w 에 비례하게 total 을 나누되 min_weight ≤ 비중 ≤ max_stock, 섹터 합 ≤ max_sector (상한에 걸린 몫은 나머지에 비례해 다시 나눔). (비중, 적용된 제약 라벨).

    비중_i = clip(f_s × w_i, min_weight, max_stock). f_s 는 섹터 상한에 안 걸린 섹터면 모두 같은 λ, 걸린 섹터면 섹터 합이 딱 상한이 되는 μ_s ≤ λ.
    예전 반복(바닥 → 종목 상한 → 넘친 섹터를 통째로 축소 → 남는 몫 비례 배분)은 종목 상한에 걸린 종목까지 섹터째 줄여 섹터 안 비례가
    깨졌다 (030: 시가총액 AAPL 0.84 · PLTR 0.06 인데 15.4% · 15.3%, 시작일에는 AAPL 20.8% 인데 열 배 작은 ABBV 25%). 시가총액 0(자료 없음)
    종목은 최소 비중만 받고, 다른 종목이 모두 최대치인데도 남는 몫이 있을 때만 그 몫을 똑같이 나눠 받는다. 상한 안에서 total 을 다 못
    채우면 나머지는 현금, 바닥만으로 섹터 상한을 넘는 섹터는 바닥을 그대로 둔다. 라벨은 최종 비중을 실제로 누른 제약. max_iter 는 예전 호출과 맞추려고 받기만 한다."""
    w = np.nan_to_num(np.asarray(w, float), nan=0.0, posinf=0.0, neginf=0.0)  # 자료 없음(NaN)은 시가총액 0 과 같게
    w[w < w.max(initial=0.0) * 1e-12] = 0.0  # 아주 작은 값은 0 으로 (1e-310 같은 값에서 경계 계산이 넘쳤다 — 검토)
    s = w.sum()
    w = w / s * total if s > 0 else np.full(len(w), total / max(len(w), 1))  # 합이 0 이하(모두 0)면 동일비중으로
    codes, sec = np.unique(np.asarray(sectors), return_inverse=True)
    lo, hi = min(min_weight, max_stock), max_stock  # 바닥이 종목 상한보다 크면 상한이 이긴다
    if (w >= lo - 1e-12).all() and (w <= hi + 1e-12).all() and (np.bincount(sec, weights=w, minlength=len(codes)) <= max_sector + 1e-12).all():
        return w, []  # 어느 제약도 안 묶이면 비례 그대로
    cap = np.full(len(codes), float(max_sector))
    out, x, over = _capped_fill(w, lo, hi, sec, cap, total)
    zero = ~(w > 0)
    if total - out.sum() > 1e-12 and zero.any():  # 다른 종목이 모두 최대치인데도 남는 몫 → 시가총액 0 종목에 똑같이 (상한 안에서)
        room = cap - np.bincount(sec[~zero], weights=out[~zero], minlength=len(codes))
        w2, x2, over2 = _capped_fill(np.ones(int(zero.sum())), lo, hi, sec[zero], room, total - out[~zero].sum())
        out[zero], x[zero], over = w2, np.where(w2 > lo + 1e-12, x2, 0.0), over | over2
    applied = {f"min_weight:{i}" for i in np.where(x < lo - 1e-12)[0]} | {f"stock_cap:{i}" for i in np.where(x > hi + 1e-12)[0]}
    applied |= {f"sector_cap:{codes[j]}" for j in np.where(over)[0]}
    return out, sorted(applied)


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


def view_directions(views, tickers) -> np.ndarray:
    """종목별 뷰 방향: 그 종목에 걸린 뷰가 모두 '오름'(절대 up·상대 long)이면 +1, 모두 '내림'(절대 down·상대 short)이면 −1, 엇갈리거나 없으면 0."""
    idx = {t: i for i, t in enumerate(tickers)}
    up, dn = np.zeros(len(tickers), bool), np.zeros(len(tickers), bool)
    for v in views:
        if v["type"] == "absolute":
            (dn if v.get("direction") == "down" else up)[idx[v["long"][0]]] = True
        else:
            up[[idx[t] for t in v["long"]]] = True
            dn[[idx[t] for t in v.get("short", [])]] = True
    return np.where(up & ~dn, 1, np.where(dn & ~up, -1, 0))


def optimize_utility(mu, cov, delta, w_base, max_stock, max_sector, sectors, max_tilt, total=1.0, *, min_weight=0.01, view_dir=None):
    """max w'μ − δ/2 w'Σw  s.t. Σw = total, min_weight ≤ w ≤ max_stock, |w − w_base| ≤ max_tilt, 섹터 상한.

    view_dir(종목별 +1/−1/0, view_directions)를 주면 '오름' 뷰 종목은 기준 비중 아래로, '내림' 뷰 종목은 위로 가지 않게 한다.
    예산(합계·섹터 상한)이 묶이면 한 종목의 오름 뷰가 (e_i − 최소분산 비중) 방향으로 퍼져, 최소분산 비중이 1 을 넘는 종목은 오히려 줄었다
    (026: 정보기술 4종목이 섹터 상한 65% 를 나눠 갖는데 'AVGO 오름(약)' 날 AVGO 가 −11.5%p). 기준 비중은 이 경계를 늘 지키므로 풀 수 없게 되지 않는다;
    그래도 실패하면 경계 없이 한 번 더 푼다."""
    n = len(mu)
    w_base = np.asarray(w_base, float)
    w_base = w_base / w_base.sum() * total
    lo0 = np.maximum(min_weight, w_base - max_tilt)
    hi0 = np.maximum(lo0 + 1e-9, np.minimum(max_stock, w_base + max_tilt))
    lo, hi, held = lo0, hi0, np.zeros(n, bool)
    if view_dir is not None:
        d = np.asarray(view_dir)
        held = d != 0
        lo = np.where(d > 0, np.maximum(lo0, w_base), lo0)
        hi = np.maximum(lo + 1e-9, np.where(d < 0, np.minimum(hi0, w_base), hi0))
    # 섹터 상한에 반올림 크기의 여유를 둔다 — 저장 비중(소수 6자리 버림)을 합계에 다시 맞추면 상한에 닿은 섹터가 2e-7 넘게 되고,
    # 그 섹터 종목이 모두 오름 뷰(하한 = 기준 비중)면 풀 수 없는 문제가 돼 방향 경계 없이 다시 풀었다 (093 2025-11-03: LGES 오름 뷰인데 −7.35%p)
    cons = [{"type": "eq", "fun": lambda w: w.sum() - total}] + _sector_constraints(sectors, max_sector + 1e-6, total)

    def obj(w):
        return -(w @ mu - delta / 2 * w @ cov @ w)

    def solve(x0):
        return minimize(obj, x0, method="SLSQP", bounds=list(zip(lo, hi, strict=True)), constraints=cons, options={"maxiter": 500, "ftol": 1e-12})

    def ok(r) -> bool:
        if not getattr(r, "success", False):
            return False
        x = r.x
        # 허용오차는 저장 비중의 반올림(소수 6자리) 수준 — 더 빡빡하면 기준 비중을 합계에 다시 맞출 때 생기는 2e-7 초과(섹터 0.399999 → 0.4000002)
        # 때문에 맞는 해를 모두 버리고 방향 경계 없이 다시 풀어 뷰를 거스르는 비중이 나왔다 (093 2025-11-03: LGES 오름 뷰인데 −7.35%p)
        return bool(abs(x.sum() - total) <= 1e-6 and np.all(x >= lo - 1e-6) and np.all(x <= hi + 1e-6) and all(c["fun"](x) >= -1e-6 for c in cons[1:]))

    res = solve(w_base)
    # 시작점(기준 비중)에서 경계·섹터 상한·합계가 한꺼번에 걸리면 SLSQP 가 더 나은 방향이 있어도 시작점에서 '성공' 으로 멈춘다
    # (080: 정보기술·커뮤니케이션 둘 다 섹터 상한 50% 에 닿은 날, GOOGL→META 로 옮기면 목적값이 오르는데 기준 비중 그대로 — 뷰 76일 중 5일).
    # 볼록 QP 라 다른 시작점(경계의 가운데, 기울기 쪽)에서 다시 풀어 목적값이 가장 좋은 해를 쓴다 (정확한 풀이 trust-constr 와 같은 해, 시험)
    best = res if ok(res) else None
    grad = mu - delta * cov @ w_base
    for x0 in ((lo + hi) / 2, np.clip(w_base + 0.5 * (hi - lo) * np.sign(grad), lo, hi)):
        r = solve(x0)
        if ok(r) and (best is None or r.fun < best.fun - 1e-12):
            best = r
    if best is not None:
        res = best
    active = []
    if best is None:
        if view_dir is not None:
            return optimize_utility(mu, cov, delta, w_base, max_stock, max_sector, sectors, max_tilt, total, min_weight=min_weight)
        # 최적화 실패: 뷰를 반영하지 않고 기준 비중 유지 (값을 지어내지 않음)
        return w_base.copy(), [f"optimizer_failed_no_tilt({res.message})"]
    w = np.clip(res.x, lo, hi)
    for i in range(n):
        if abs(w[i] - hi0[i]) < 1e-6:
            active.append(f"upper:{i}")
        elif abs(w[i] - lo0[i]) < 1e-6 and lo0[i] > 0:
            active.append(f"lower:{i}")
        elif held[i] and abs(w[i] - w_base[i]) < 1e-6:
            active.append(f"view_hold:{i}")  # 뷰 방향을 거스르지 않으려고 기준 비중에 머묾
    for s in np.unique(sectors):
        m = np.asarray(sectors) == s
        if abs(w[m].sum() - max_sector) < 1e-6:
            active.append(f"sector_cap:{s}")
    return w, active


def ex_ante_stats(w, mu, cov) -> dict[str, float]:
    er = float(w @ mu)
    vol = float(np.sqrt(w @ cov @ w))
    inv = float(np.sum(w))
    ss = float(np.sum((w / inv) ** 2)) if inv > 0 else 0.0  # 실효 종목 수는 투자 비중 안에서: 현금이 있으면 1/Σw² 가 실제 종목 수보다 커졌다 (F20)
    return {"exp_return": round(er, 6), "vol": round(vol, 6), "sharpe": round(er / vol, 4) if vol > 0 else 0.0,
            "effective_n": round(1 / ss, 3) if ss > 0 else 0.0}  # fmt: skip


def weights_out(tickers, w) -> tuple[dict[str, float], float]:
    """저장하는 비중(소수 6자리 내림)과 그 합으로 센 현금. 반올림하면 종목마다의 올림이 쌓여 합이 투자 가능 비율을 넘었다
    (041 최종 재실행: 25종목 합 0.85001 → 현금 14.999% < 최소 현금 15%). 내림은 현금을 많아야 종목 수 × 0.0001%p 늘린다."""
    out = {t: max(0.0, float(np.floor(float(x) * 1e6 + 1e-6)) / 1e6) for t, x in zip(tickers, w, strict=True)}
    return out, round(1.0 - sum(out.values()), 6)


def sector_weights(w, sector_names) -> dict[str, float]:
    out: dict[str, float] = {}
    for wi, s in zip(w, sector_names, strict=True):
        out[s] = out.get(s, 0.0) + float(wi)
    return {k: round(v, 6) for k, v in out.items()}
