"""Performance / risk analytics for stage 11. Pure pandas; no bt dependency.

compute_all() is used both for the full period and for every checkpoint (sliced inputs), so every
"to_date" number has exactly the same definition as the final metrics.
"""
import numpy as np
import pandas as pd
import backtest_config as BC

TD = BC.TRADING_DAYS


def _r(x, n=6):
    return None if x is None or (isinstance(x, float) and not np.isfinite(x)) else round(float(x), n)


# ───────────────────────── return ─────────────────────────
def daily_returns(idx: pd.Series) -> pd.Series:
    return idx.pct_change().dropna()


def total_return(idx):
    return idx.iloc[-1] / idx.iloc[0] - 1


def cagr(idx):
    n = len(idx) - 1
    return (idx.iloc[-1] / idx.iloc[0]) ** (TD / n) - 1 if n > 0 else float("nan")


def monthly_returns(idx: pd.Series) -> pd.Series:
    m = idx.resample("ME").last()
    r = m.pct_change()
    r.iloc[0] = m.iloc[0] / idx.iloc[0] - 1
    return r


def yearly_returns(idx: pd.Series) -> dict:
    y = idx.resample("YE").last(); r = y.pct_change(); r.iloc[0] = y.iloc[0] / idx.iloc[0] - 1
    return {str(d.year): _r(v) for d, v in r.items()}


def rolling_12m(idx, target):
    r = idx.pct_change(TD).dropna()
    if len(r) == 0:
        return {"min": None, "median": None, "max": None, "pct_above_target": None}
    return {"min": _r(r.min()), "median": _r(r.median()), "max": _r(r.max()), "pct_above_target": _r((r >= target).mean())}


# ───────────────────────── risk ─────────────────────────
def ann_vol(r):
    return r.std(ddof=1) * np.sqrt(TD) if len(r) > 1 else float("nan")


def downside_deviation(r, rf):
    d = np.minimum(r - rf / TD, 0)
    return float(np.sqrt(np.mean(d ** 2)) * np.sqrt(TD)) if len(r) else float("nan")


def drawdown_series(idx):
    return idx / idx.cummax() - 1


def mdd_info(idx):
    dd = drawdown_series(idx)
    if (dd == 0).all():
        return {"peak_date": None, "trough_date": None, "recovery_date": None, "duration_days": 0, "underwater_days": 0}
    trough = dd.idxmin(); peak = idx[:trough].idxmax()
    after = idx[trough:]; rec = after[after >= idx[peak]]
    recovery = rec.index[0] if len(rec) else None
    return {"peak_date": str(peak.date()), "trough_date": str(trough.date()), "recovery_date": str(recovery.date()) if recovery is not None else None,
            "duration_days": int((trough - peak).days), "underwater_days": int(((recovery if recovery is not None else idx.index[-1]) - peak).days)}


def drawdown_episodes(idx, min_depth=-0.05, top=3):
    dd = drawdown_series(idx); eps = []; in_dd = False
    for d, v in dd.items():
        if v < 0 and not in_dd:
            in_dd, start = True, d
        elif v == 0 and in_dd:
            seg = dd[start:d]; eps.append((seg.min(), start, seg.idxmin(), d)); in_dd = False
    if in_dd:
        seg = dd[start:]; eps.append((seg.min(), start, seg.idxmin(), None))
    eps = [e for e in eps if e[0] <= min_depth]; eps.sort(key=lambda e: e[0])
    return [{"depth": _r(e[0]), "peak_date": str((idx[:e[1]].idxmax()).date()), "trough_date": str(e[2].date()),
             "recovery_date": str(e[3].date()) if e[3] is not None else None} for e in eps[:top]]


def var_cvar(mr, q=0.05):
    if len(mr) < 3:
        return None, None
    v = mr.quantile(q); return _r(v), _r(mr[mr <= v].mean())


# ───────────────────────── relative ─────────────────────────
def relative_to(idx, bench_idx, rf):
    rp, rb = daily_returns(idx), daily_returns(bench_idx)
    rp, rb = rp.align(rb, join="inner")
    if len(rp) < 5:
        return {k: None for k in ["excess_cagr", "beta", "alpha_ann", "correlation", "tracking_error", "information_ratio", "up_capture", "down_capture", "months_outperformed_ratio"]}
    bi = bench_idx.reindex(idx.index).ffill()
    beta = np.cov(rp, rb, ddof=1)[0, 1] / rb.var(ddof=1)
    alpha = ((rp - rf / TD).mean() - beta * (rb - rf / TD).mean()) * TD
    te = (rp - rb).std(ddof=1) * np.sqrt(TD)
    ex = cagr(idx) - cagr(bi)
    mp, mb = monthly_returns(idx), monthly_returns(bi)
    up, down = mb > 0, mb < 0
    return {"excess_cagr": _r(ex), "beta": _r(beta), "alpha_ann": _r(alpha), "correlation": _r(rp.corr(rb)), "tracking_error": _r(te),
            "information_ratio": _r(ex / te) if te > 0 else None,
            "up_capture": _r(mp[up].mean() / mb[up].mean()) if up.sum() > 0 else None,
            "down_capture": _r(mp[down].mean() / mb[down].mean()) if down.sum() > 0 else None,
            "months_outperformed_ratio": _r((mp > mb).mean())}


# ───────────────────────── money ─────────────────────────
def money_metrics(values: pd.Series, flows: pd.Series, xirr_fn):
    f = flows.reindex(values.index).fillna(0.0)
    initial = float(f.iloc[0]); contributions = float(f.iloc[1:].sum()); net = float(f.sum()); final = float(values.iloc[-1])
    cum = f.cumsum(); profit_path = values - cum
    cf_dates = [d for d, a in f.items() if a != 0] + [values.index[-1]]
    cf_amts = [-a for d, a in f.items() if a != 0] + [final]
    irr = xirr_fn(cf_dates, cf_amts) if len(values) > 1 else float("nan")
    w12 = (values - values.shift(TD) - (cum - cum.shift(TD))).dropna()
    return {"initial_usd": _r(initial, 2), "contributions_usd": _r(contributions, 2), "net_invested_usd": _r(net, 2),
            "final_value_usd": _r(final, 2), "profit_usd": _r(final - net, 2), "irr_annual": _r(irr),
            "max_loss_usd": _r(min(profit_path.min(), 0.0), 2), "worst_12m_loss_usd": _r(min(w12.min(), 0.0), 2) if len(w12) else None}


# ───────────────────────── composition / trading ─────────────────────────
def composition_metrics(sec_w: pd.DataFrame, asset_px: pd.DataFrame, targets: dict, sectors: dict, max_stock, max_sector):
    cols = [c for c in targets if c in sec_w.columns]
    w = sec_w[cols].fillna(0.0)
    r = asset_px[cols].pct_change().reindex(w.index).fillna(0.0)
    contrib = (w.shift(1) * r).sum()
    avg = w.mean()
    sec_w_t = pd.DataFrame({s: w[[c for c in cols if sectors[c] == s]].sum(axis=1) for s in set(sectors[c] for c in cols)})
    tgt = pd.Series(targets)[cols]
    drift = (w - tgt).abs().max().max()
    sec_tgt = pd.Series({s: tgt[[c for c in cols if sectors[c] == s]].sum() for s in sec_w_t.columns})
    sdrift = (sec_w_t - sec_tgt).abs().max().max()
    ac = contrib.abs().sort_values(ascending=False)
    return {"effective_n": _r(1 / (avg ** 2).sum(), 3), "hhi": _r((avg ** 2).sum()),
            "top3_contribution_share": _r(ac.head(3).sum() / ac.sum()) if ac.sum() > 0 else None,
            "sector_weights_avg": {s: _r(v) for s, v in sec_w_t.mean().items()},
            "max_weight_drift": _r(drift), "max_sector_drift": _r(sdrift),
            "ticker_contribution": {c: _r(contrib[c]) for c in cols},
            "ticker_total_return": {c: _r(asset_px[c].iloc[-1] / asset_px[c].iloc[0] - 1) for c in cols},
            "breaches": sorted({f"stock_cap:{c}" for c in cols if (w[c] > max_stock * (1 + BC.DRIFT_TOLERANCE)).any()}
                               | {f"sector_cap:{s}" for s in sec_w_t.columns if (sec_w_t[s] > max_sector * (1 + BC.DRIFT_TOLERANCE)).any()})}


def trading_metrics(tx: pd.DataFrame, turnover: pd.Series, rebal_dates, values: pd.Series):
    rb = [d for d in rebal_dates if d in turnover.index]
    comm = float((tx["quantity"].abs() * tx["price"]).sum() * BC.COMMISSION_BPS / 1e4) if len(tx) else 0.0
    years = max((values.index[-1] - values.index[0]).days / 365.0, 1e-9)
    return {"n_rebalances": len(rb), "turnover_avg": _r(turnover.loc[rb].mean()) if rb else None, "commissions_usd": _r(comm, 2),
            "commission_drag_annual": _r(comm / values.mean() / years)}


def rolling_metrics(idx, rf):
    r = daily_returns(idx)
    if len(r) < TD + 5:
        return {"rolling_sharpe_12m": {"min": None, "median": None}, "rolling_vol_12m": {"min": None, "max": None}}
    vol = r.rolling(TD).std(ddof=1) * np.sqrt(TD)
    ret = idx.pct_change(TD).reindex(r.index)
    sh = ((ret - rf) / vol).dropna()
    return {"rolling_sharpe_12m": {"min": _r(sh.min()), "median": _r(sh.median())},
            "rolling_vol_12m": {"min": _r(vol.min()), "max": _r(vol.max())}}


# ───────────────────────── views ─────────────────────────
def view_diagnostics(views, asset_px: pd.DataFrame, as_of, end, implied: dict):
    """Realized return over [as_of, min(as_of+horizon, end)] vs each view. hit = direction agrees."""
    if not views:
        return []
    stop = min(pd.Timestamp(as_of) + pd.Timedelta(days=BC.VIEW_HORIZON_DAYS), pd.Timestamp(end))
    px = asset_px.loc[pd.Timestamp(as_of):stop]
    real = (px.iloc[-1] / px.iloc[0] - 1)
    out = []
    for v in views:
        if v["type"] == "absolute":
            t = v["long"][0]; realized = float(real[t]); prior = implied.get(t, 0.0)
            hit = (realized - prior) * (v["expected_return_annual"] - prior) > 0
        else:
            realized = float(real[v["long"]].mean() - real[v["short"]].mean()); hit = realized > 0
        out.append({"summary_ko": v.get("summary_ko", ""), "type": v["type"], "expected_return_annual": v["expected_return_annual"],
                    "realized": _r(realized), "error": _r(realized - v["expected_return_annual"]), "hit": bool(hit),
                    "window_end": str(px.index[-1].date())})
    return out


# ───────────────────────── all ─────────────────────────
def compute_all(raw, bench_idx, asset_px, targets, sectors, rebal_dates, rf, target_return, max_stock, max_sector,
                xirr_fn, baseline_idx=None, views=None, implied=None, as_of=None, end=None):
    idx, values, flows = raw["index"], raw["values"], raw["flows"]
    r = daily_returns(idx); mr = monthly_returns(idx)
    cg, vol, mdd = cagr(idx), ann_vol(r), drawdown_series(idx).min()
    dd_ = downside_deviation(r, rf)
    var, cvar = var_cvar(mr)
    comp = composition_metrics(raw["security_weights"], asset_px, targets, sectors, max_stock, max_sector)
    m = {
        "return": {"total_return": _r(total_return(idx)), "cagr": _r(cg), "best_month": _r(mr.max()), "worst_month": _r(mr.min()),
                   "positive_months_ratio": _r((mr > 0).mean()), "rolling_12m": rolling_12m(idx, target_return)},
        "risk": {"ann_vol": _r(vol), "downside_deviation": _r(dd_), "max_drawdown": _r(mdd), "mdd": mdd_info(idx),
                 "drawdown_episodes": drawdown_episodes(idx), "var_95_monthly": var, "cvar_95_monthly": cvar,
                 "worst_day": _r(r.min()) if len(r) else None, "skew": _r(r.skew()) if len(r) > 2 else None, "kurtosis": _r(r.kurt()) if len(r) > 3 else None},
        "risk_adjusted": {"sharpe": _r((cg - rf) / vol) if vol > 0 else None, "sortino": _r((cg - rf) / dd_) if dd_ > 0 else None,
                          "calmar": _r(cg / abs(mdd)) if mdd < 0 else None},
        "vs_benchmark": relative_to(idx, bench_idx, rf),
        "vs_baseline": None,
        "composition": {k: comp[k] for k in ["effective_n", "hhi", "top3_contribution_share", "sector_weights_avg", "max_weight_drift", "max_sector_drift", "breaches"]},
        "trading": trading_metrics(raw["transactions"], raw["turnover"], rebal_dates, values),
        "stability": rolling_metrics(idx, rf),
    }
    if baseline_idx is not None:
        rel = relative_to(idx, baseline_idx, rf)
        m["vs_baseline"] = {"active_return": rel["excess_cagr"], "active_risk": rel["tracking_error"], "information_ratio": rel["information_ratio"]}
    money = money_metrics(values, flows, xirr_fn)
    vd = view_diagnostics(views, asset_px, as_of or idx.index[0], end or idx.index[-1], implied or {}) if views else []
    return {"metrics": m, "money": money, "monthly_returns": [{"year": d.year, "month": d.month, "return": _r(v)} for d, v in mr.items()],
            "yearly_returns": yearly_returns(idx), "ticker_contribution": comp["ticker_contribution"],
            "ticker_total_return": comp["ticker_total_return"], "view_diagnostics": vd}


# ───────────────────────── self test ─────────────────────────
def _selftest():
    from backtest_engine import xirr
    dates = pd.bdate_range("2023-01-02", periods=504)
    lvl = np.full(504, 100.0)
    for i in range(1, 504): lvl[i] = lvl[i - 1] * 1.001
    lvl[200:260] = lvl[199] * np.linspace(1, 0.8, 60)          # -20% drawdown
    lvl[260:] = lvl[259] * np.cumprod(np.full(504 - 260, 1.002))
    idx = pd.Series(lvl, index=dates)
    assert abs(drawdown_series(idx).min() + 0.2) < 1e-9
    info = mdd_info(idx); assert info["peak_date"] == str(dates[199].date()) and info["trough_date"] == str(dates[259].date()) and info["recovery_date"] is not None
    assert abs(cagr(idx) - ((idx.iloc[-1] / idx.iloc[0]) ** (252 / 503) - 1)) < 1e-12
    mr = monthly_returns(idx); v, cv = var_cvar(mr); assert cv <= v
    rel = relative_to(idx, idx, 0.04); assert abs(rel["beta"] - 1) < 1e-9 and rel["tracking_error"] < 1e-12 and abs(rel["up_capture"] - 1) < 1e-9
    assert abs(xirr([dates[0], dates[-1]], [-100, float(idx.iloc[-1])]) - ((idx.iloc[-1] / 100) ** (365 / (dates[-1] - dates[0]).days) - 1)) < 1e-6
    vals = idx.copy(); flows = pd.Series(0.0, index=dates); flows.iloc[0] = 100.0
    mm = money_metrics(vals, flows, xirr)
    assert abs(mm["profit_usd"] - (idx.iloc[-1] - 100)) < 0.01, mm       # values are rounded to cents
    assert abs(mm["max_loss_usd"] - min((idx - 100).min(), 0.0)) < 0.01, mm
    eps = drawdown_episodes(idx); assert eps and abs(eps[0]["depth"] + 0.2) < 1e-6
    print(f"metrics selftest OK  cagr={cagr(idx):.4f} mdd={drawdown_series(idx).min():.3f} recovery={info['recovery_date']} var95={v} cvar95={cv} irr={mm['irr_annual']}")


if __name__ == "__main__":
    _selftest()
