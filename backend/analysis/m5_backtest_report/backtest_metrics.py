"""성과·위험 지표 (M5-02). 순수 pandas. compute_all() 이 전체 기간과 체크포인트(to_date) 모두에 쓰여 정의가 하나다."""

from __future__ import annotations

import numpy as np
import pandas as pd

from backend.analysis.settings import BacktestSettings


def _r(x, n=6):
    return None if x is None or (isinstance(x, float) and not np.isfinite(x)) else round(float(x), n)


# ───────────────────────── return ─────────────────────────
def daily_returns(idx: pd.Series) -> pd.Series:
    return idx.pct_change().dropna()


def total_return(idx):
    return idx.iloc[-1] / idx.iloc[0] - 1


def _years(idx) -> float | None:
    """지수의 실제 경과 기간(년). 날짜 색인이 아니면 None."""
    if isinstance(getattr(idx, "index", None), pd.DatetimeIndex) and len(idx) > 1:
        days = (idx.index[-1] - idx.index[0]).days
        return days / 365.25 if days > 0 else None
    return None


def td_eff(idx, td: int) -> float:
    """1년에 해당하는 행 수. 한국 종목 + 미국 보조 비교지수처럼 시장 합집합 달력이면 1년 ≈ 259행이라 252 로 연환산하면 틀어진다 (2026-11 QA)."""
    y = _years(idx)
    return (len(idx) - 1) / y if y else float(td)


def cagr(idx, td: int):
    """연환산 = 실제 경과 기간 기준 (행 수 / 252 가 아니라). 날짜 색인이 없으면 예전처럼 행 수 기준."""
    n = len(idx) - 1
    if n <= 0:
        return float("nan")
    y = _years(idx)
    return (idx.iloc[-1] / idx.iloc[0]) ** (1 / y) - 1 if y else (idx.iloc[-1] / idx.iloc[0]) ** (td / n) - 1


def monthly_returns(idx: pd.Series) -> pd.Series:
    m = idx.resample("ME").last()
    r = m.pct_change()
    r.iloc[0] = m.iloc[0] / idx.iloc[0] - 1
    return r


def yearly_returns(idx: pd.Series) -> dict:
    y = idx.resample("YE").last()
    r = y.pct_change()
    r.iloc[0] = y.iloc[0] / idx.iloc[0] - 1
    return {str(d.year): _r(v) for d, v in r.items()}


def rolling_12m(idx, target, td: int):
    r = idx.pct_change(td).dropna()
    if len(r) == 0:
        return {"min": None, "median": None, "max": None, "pct_above_target": None}
    return {"min": _r(r.min()), "median": _r(r.median()), "max": _r(r.max()), "pct_above_target": _r((r >= target).mean())}


# ───────────────────────── risk ─────────────────────────
def ann_vol(r, td: int):
    return r.std(ddof=1) * np.sqrt(td) if len(r) > 1 else float("nan")


def downside_deviation(r, rf, td: int):
    d = np.minimum(r - rf / td, 0)
    return float(np.sqrt(np.mean(d**2)) * np.sqrt(td)) if len(r) else float("nan")


def drawdown_series(idx):
    return idx / idx.cummax() - 1


def mdd_info(idx):
    dd = drawdown_series(idx)
    if (dd == 0).all():
        return {"peak_date": None, "trough_date": None, "recovery_date": None, "duration_days": 0, "underwater_days": 0}
    trough = dd.idxmin()
    peak = idx[:trough].idxmax()
    after = idx[trough:]
    rec = after[after >= idx[peak]]
    recovery = rec.index[0] if len(rec) else None
    return {"peak_date": str(peak.date()), "trough_date": str(trough.date()), "recovery_date": str(recovery.date()) if recovery is not None else None,
            "duration_days": int((trough - peak).days), "underwater_days": int(((recovery if recovery is not None else idx.index[-1]) - peak).days)}  # fmt: skip


def drawdown_episodes(idx, min_depth=-0.05, top=3):
    dd = drawdown_series(idx)
    eps = []
    in_dd = False
    start = None
    for d, v in dd.items():
        if v < 0 and not in_dd:
            in_dd, start = True, d
        elif v == 0 and in_dd:
            seg = dd[start:d]
            eps.append((seg.min(), start, seg.idxmin(), d))
            in_dd = False
    if in_dd:
        seg = dd[start:]
        eps.append((seg.min(), start, seg.idxmin(), None))
    eps = [e for e in eps if e[0] <= min_depth]
    eps.sort(key=lambda e: e[0])
    return [{"depth": _r(e[0]), "peak_date": str((idx[: e[1]].idxmax()).date()), "trough_date": str(e[2].date()),
             "recovery_date": str(e[3].date()) if e[3] is not None else None} for e in eps[:top]]  # fmt: skip


def var_cvar(mr, q=0.05):
    if len(mr) < 3:
        return None, None
    v = mr.quantile(q)
    return _r(v), _r(mr[mr <= v].mean())


# ───────────────────────── relative ─────────────────────────
def relative_to(idx, bench_idx, rf, td: int):
    rp, rb = daily_returns(idx), daily_returns(bench_idx)
    rp, rb = rp.align(rb, join="inner")
    keys = ["excess_cagr", "beta", "alpha_ann", "correlation", "tracking_error", "information_ratio", "up_capture", "down_capture", "months_outperformed_ratio"]
    if len(rp) < 5:
        return dict.fromkeys(keys)
    bi = bench_idx.reindex(idx.index).ffill()
    td = td_eff(idx, td)  # 합집합 달력이면 1년 행 수가 252 가 아니다
    beta = np.cov(rp, rb, ddof=1)[0, 1] / rb.var(ddof=1)
    alpha = ((rp - rf / td).mean() - beta * (rb - rf / td).mean()) * td
    te = (rp - rb).std(ddof=1) * np.sqrt(td)
    ex = cagr(idx, td) - cagr(bi, td)
    mp, mb = monthly_returns(idx), monthly_returns(bi)
    up, down = mb > 0, mb < 0
    return {"excess_cagr": _r(ex), "beta": _r(beta), "alpha_ann": _r(alpha), "correlation": _r(rp.corr(rb)), "tracking_error": _r(te),
            "information_ratio": _r(ex / te) if te > 0 else None,
            "up_capture": _r(mp[up].mean() / mb[up].mean()) if up.sum() > 0 else None,
            "down_capture": _r(mp[down].mean() / mb[down].mean()) if down.sum() > 0 else None,
            "months_outperformed_ratio": _r((mp > mb).mean())}  # fmt: skip


# ───────────────────────── money ─────────────────────────
def irr_annual(values: pd.Series, flows: pd.Series, xirr_fn):
    """적립 흐름(음수)과 마지막 평가금액(양수)의 연 IRR. money_metrics 와 체크포인트(compute_to_date)가 같은 식을 쓴다."""
    f = flows.reindex(values.index).fillna(0.0)
    final = float(values.iloc[-1])
    cf_dates = [d for d, a in f.items() if a != 0] + [values.index[-1]]
    cf_amts = [-a for d, a in f.items() if a != 0] + [final]
    return xirr_fn(cf_dates, cf_amts) if len(values) > 1 else float("nan")


def money_metrics(values: pd.Series, flows: pd.Series, xirr_fn, td: int):
    f = flows.reindex(values.index).fillna(0.0)
    initial = float(f.iloc[0])
    contributions = float(f.iloc[1:].sum())
    net = float(f.sum())
    final = float(values.iloc[-1])
    cum = f.cumsum()
    profit_path = values - cum
    irr = irr_annual(values, flows, xirr_fn)
    w12 = (values - values.shift(td) - (cum - cum.shift(td))).dropna()
    return {"initial_usd": _r(initial, 2), "contributions_usd": _r(contributions, 2), "net_invested_usd": _r(net, 2),
            "final_value_usd": _r(final, 2), "profit_usd": _r(final - net, 2), "irr_annual": _r(irr),
            "max_loss_usd": _r(min(profit_path.min(), 0.0), 2), "worst_12m_loss_usd": _r(min(w12.min(), 0.0), 2) if len(w12) else None}  # fmt: skip


# ───────────────────────── composition / trading ─────────────────────────
def linked_contribution(w: pd.DataFrame, r: pd.DataFrame, idx: pd.Series, values: pd.Series | None = None,
                        flows: pd.Series | None = None) -> tuple[pd.Series, float]:  # fmt: skip
    """종목별 기간 수익 기여 (Carino 로그 연결)와 잔차. Σ 기여 + 잔차 = 지수 기간 수익률 (헤드라인 period_return 과 같은 지수).

    일별 기여 w_i(t−1)·r_i(t) 를 그냥 더하면 복리로 불어난 기간 수익률과 합이 맞지 않는다 (시나리오 002: 80.9%p + 44.5%p 인데 기간 수익률 205.4%).
    날마다 k_t/K 를 곱하면 (k_t = ln(1+R_t)/R_t, K = ln(1+R)/R) Σ_t k_t·R_t = ln(1+R) 이라 합이 R 이 된다. 현금은 수익 0 이라 기여도 0.
    적립일에는 bt 가 그날 적립금을 분모에 넣어(R_t = V(t−1)·Σw·r / (V(t−1)+F(t))) 지수 수익이 희석된다 → values·flows 를 주면 같은 비율로 비중을 줄여,
    남는 잔차가 거래비용만 되게 한다 (검토: 적립이 큰 실행에서 수수료 0 인데도 잔차가 −3.4%p 였다).
    """
    rp = daily_returns(idx).reindex(w.index).fillna(0.0)
    R = total_return(idx)
    k = (np.log1p(rp) / rp).where(rp.abs() > 1e-12, 1.0)  # R_t≈0 이면 극한값 1 (0/0 방지)
    K = np.log1p(R) / R if abs(R) > 1e-12 else 1.0
    wl = w.shift(1)
    if values is not None and flows is not None:
        f = flows.reindex(w.index).fillna(0.0)
        f.iloc[0] = 0.0  # 첫날 흐름 = 초기 투자금 (수익 계산과 무관)
        v0 = values.reindex(w.index).shift(1)
        wl = wl.mul((v0 / (v0 + f)).where((v0 + f) > 0).fillna(1.0), axis=0)
    contrib = (wl * r).mul(k / K, axis=0).sum()
    return contrib, float(R - contrib.sum())


def cash_floor(sec_w: pd.DataFrame, min_cash: float = 0.0, noise: float = 5e-4) -> dict:
    """현금 비중(1 − Σ 종목 비중)의 최저값·그날과, 사용자가 정한 최소 현금보다 낮았던 날 수. min_cash 가 0 이면 날 수는 세지 않는다(None).

    bt 의 security_weights 는 현금까지 합친 평가액 대비라 1 − Σ 가 그날 현금 몫이다 (적립일에도: 적립금 중 목표 밖 몫은 현금으로 남는다).
    031: 모두 에너지 종목이라 섹터 비중이 90% 를 넘은 날은 현금이 최소 10% 아래였는데(754거래일 중 565일, 최저 7.56%) 리밸런싱일 목표만 보고 '현금 10%' 라고 썼다.
    noise(0.05%p) 안은 리밸런싱일 체결·반올림 잡음이라 세지 않는다."""
    cash = 1.0 - sec_w.fillna(0.0).sum(axis=1)
    if not len(cash):
        return {"min_cash_weight": None, "min_cash_date": None, "days_cash_below_min": None}
    low, mc = cash.idxmin(), float(min_cash or 0.0)
    return {"min_cash_weight": _r(cash.min()), "min_cash_date": str(low.date()) if isinstance(low, pd.Timestamp) else str(low),
            "days_cash_below_min": int((cash < mc - noise).sum()) if mc > 1e-9 else None}  # fmt: skip


def composition_metrics(sec_w: pd.DataFrame, asset_px: pd.DataFrame, targets: dict, sectors: dict, max_stock, max_sector, drift_tol: float, idx: pd.Series,
                        values: pd.Series | None = None, flows: pd.Series | None = None, targets_by_date: dict | None = None, min_cash: float = 0.0):  # fmt: skip
    names = list(targets) + [c for v in (targets_by_date or {}).values() for c in v if c not in targets]
    cols = [c for c in dict.fromkeys(names) if c in sec_w.columns]
    w = sec_w[cols].fillna(0.0)
    r = asset_px[cols].pct_change().reindex(w.index).fillna(0.0)
    contrib, resid = linked_contribution(w, r, idx, values, flows)  # 연결 안 한 단순합은 기간 수익률과 합이 안 맞아 보고서 막대가 틀렸다 (시나리오 002·003)
    avg = w.mean()
    sec_set = {sectors[c] for c in cols}
    sec_w_t = pd.DataFrame({s: w[[c for c in cols if sectors[c] == s]].sum(axis=1) for s in sec_set})
    if targets_by_date:  # walk-forward: 그날 적용 중인 목표와 비교 (예전에는 마지막 목표 하나와 비교해 드리프트가 두 배로 보였다, 008)
        tb = pd.DataFrame({pd.Timestamp(k): pd.Series(v, dtype=float) for k, v in targets_by_date.items()}).T.sort_index()
        tgt = tb.reindex(columns=cols).fillna(0.0).reindex(w.index, method="ffill").bfill().fillna(0.0)
        sec_tgt = pd.DataFrame({s: tgt[[c for c in cols if sectors[c] == s]].sum(axis=1) for s in sec_w_t.columns})
    else:
        tgt = pd.Series(targets, dtype=float).reindex(cols).fillna(0.0)
        sec_tgt = pd.Series({s: tgt[[c for c in cols if sectors[c] == s]].sum() for s in sec_w_t.columns})
    drift = (w - tgt).abs().max().max()
    sdrift = (sec_w_t - sec_tgt).abs().max().max()
    # 드리프트(|w − 목표|)가 아니라 비중 자체의 최댓값과 상한을 넘은 날 수 — 검증 R4b/R5b 문구가 실제로 본 것을 말하게 (019: 정보기술 63.1% 로 상한 55% 를 넘었는데 '상한 안에 머묾')
    st_max, sec_max = w.max(), sec_w_t.max()
    noise = 5e-4  # 0.05%p 안은 체결·반올림 잡음 (리밸런싱일에 상한과 같게 맞춘 비중이 1e-6 만큼 넘는 것을 세지 않게)
    ac = contrib.abs().sort_values(ascending=False)
    tot = float(avg.sum())
    avg_n = avg / tot if tot > 0 else avg  # 현금 제외 투자 비중으로 정규화 (F20: 현금 15% 면 4종목이 5.5종목으로 보였다)
    return {"effective_n": _r(1 / (avg_n**2).sum(), 3) if tot > 0 else None, "hhi": _r((avg_n**2).sum()),
            "top3_contribution_share": _r(ac.head(3).sum() / ac.sum()) if ac.sum() > 0 else None,
            "sector_weights_avg": {s: _r(v) for s, v in sec_w_t.mean().items()},
            "max_weight_drift": _r(drift), "max_sector_drift": _r(sdrift),
            "max_stock_weight": _r(st_max.max()) if len(st_max) else None, "max_stock_weight_ticker": str(st_max.idxmax()) if len(st_max) else None,
            "max_sector_weight": _r(sec_max.max()) if len(sec_max) else None, "max_sector_weight_sector": str(sec_max.idxmax()) if len(sec_max) else None,
            "days_above_stock_cap": int((w > max_stock + noise).any(axis=1).sum()), "days_above_sector_cap": int((sec_w_t > max_sector + noise).any(axis=1).sum()) if len(sec_max) else 0,
            # 허용 폭(상한 × (1 + drift_tol))을 넘은 날도 따로 (031: 상한 10% 를 넘은 747일과 허용 폭 12.5% 를 넘은 90일을 한 문장에 묶어 서술이 '12.5% 를 747일 넘었다' 고 읽었다)
            "days_above_stock_tol": int((w > max_stock * (1 + drift_tol) + noise).any(axis=1).sum()),
            "days_above_sector_tol": int((sec_w_t > max_sector * (1 + drift_tol) + noise).any(axis=1).sum()) if len(sec_max) else 0,
            "n_days": int(len(w)), **cash_floor(sec_w, min_cash, noise),
            "ticker_contribution": {c: _r(contrib[c]) for c in cols}, "ticker_contribution_residual": _r(resid),
            "ticker_total_return": {c: _r(asset_px[c].iloc[-1] / asset_px[c].iloc[0] - 1) for c in cols},
            "breaches": sorted({f"stock_cap:{c}" for c in cols if (w[c] > max_stock * (1 + drift_tol)).any()}
                               | {f"sector_cap:{s}" for s in sec_w_t.columns if (sec_w_t[s] > max_sector * (1 + drift_tol)).any()})}  # fmt: skip


def trading_metrics(tx: pd.DataFrame, turnover: pd.Series, rebal_dates, values: pd.Series, commission_bps: float):
    rb = [d for d in rebal_dates if d in turnover.index]
    comm = float((tx["quantity"].abs() * tx["price"]).sum() * commission_bps / 1e4) if len(tx) else 0.0
    years = max((values.index[-1] - values.index[0]).days / 365.0, 1e-9)
    return {"n_rebalances": len(rb), "turnover_avg": _r(turnover.loc[rb].mean()) if rb else None, "commissions_usd": _r(comm, 2),
            "commission_drag_annual": _r(comm / values.mean() / years)}  # fmt: skip


def rolling_metrics(idx, rf, td: int):
    r = daily_returns(idx)
    if len(r) < td + 5:
        return {"rolling_sharpe_12m": {"min": None, "median": None}, "rolling_vol_12m": {"min": None, "max": None}}
    vol = r.rolling(td).std(ddof=1) * np.sqrt(td)
    ret = idx.pct_change(td).reindex(r.index)
    sh = ((ret - rf) / vol).dropna()
    return {"rolling_sharpe_12m": {"min": _r(sh.min()), "median": _r(sh.median())}, "rolling_vol_12m": {"min": _r(vol.min()), "max": _r(vol.max())}}


# ───────────────────────── views ─────────────────────────
def _view_prior(v, implied: dict) -> float:
    """뷰의 사전 기대수익: 뷰에 적힌 prior_return(새 뷰) 또는 그날 시장모형의 implied (옛 뷰)."""
    if v.get("prior_return") is not None:
        return float(v["prior_return"])
    if v["type"] == "absolute":
        return float(implied.get(v["long"][0], 0.0))
    return 0.0


def _view_hit(v, realized: float, prior_scaled: float, prior_annual: float) -> bool:
    """방향 적중. 절대 뷰: 실현 수익이 사전 기대(기간 비례)보다 뷰 방향으로 움직였나. 상대 뷰: long−short 실현 차이가 사전 기대 차이보다 컸나
    (상대 뷰 Q = 사전 차이 + k·σ 라서 '사전보다 long 쪽' 이 뜻이다). 사전 차이가 없는 옛 상대 뷰는 0 → 'long 이 이겼나'.

    방향이 없는 옛 절대 뷰는 예전 정의(숫자가 사전 기대보다 높았나 낮았나)를 쓴다.
    """
    if v["type"] != "absolute":
        return realized - prior_scaled > 0
    d = v.get("direction")
    if d in ("up", "down"):
        return (realized - prior_scaled) * (1 if d == "up" else -1) > 0
    return (realized - prior_scaled) * (float(v["expected_return_annual"]) - prior_annual) > 0


def view_diagnostics(views, asset_px: pd.DataFrame, as_of, end, implied: dict, horizon_days: int, *, require_full: bool = True):
    """[as_of, min(as_of+horizon, end)] 실현 수익률 vs 각 뷰. hit = 방향 일치 (_view_hit).

    require_full: 지평(보통 12개월)이 끝나지 않은 창은 판정하지 않는다(hit=None, pending=True) — 몇십 일짜리 창을 '12개월 기준'
    적중률에 섞지 않기 위해. 체크포인트의 '지금까지' 진단은 False 로 부르고, 사전 기대를 기간에 비례해 비교한다(partial=True).
    """
    if not views:
        return []
    full_stop = pd.Timestamp(as_of) + pd.Timedelta(days=horizon_days)
    stop = min(full_stop, pd.Timestamp(end))
    px = asset_px.loc[pd.Timestamp(as_of) : stop]
    if len(px) < 2:
        return []  # 구성일이 창의 끝이면 실현 수익률이 없다 (walk-forward 마지막 리밸런싱일)
    incomplete = full_stop > pd.Timestamp(end)
    real = px.iloc[-1] / px.iloc[0] - 1
    days = max(1, (px.index[-1] - px.index[0]).days)
    out = []
    for v in views:
        if any(t not in real.index for t in [*v.get("long", []), *v.get("short", [])]):
            continue  # 자료 품질로 패널에서 빠진 종목의 뷰
        if v["type"] == "absolute":
            realized = float(real[v["long"][0]])
        else:
            realized = float(real[v["long"]].mean() - real[v["short"]].mean())
        prior = _view_prior(v, implied)
        scale = min(1.0, days / 365.0)
        hit = None if (incomplete and require_full) else bool(_view_hit(v, realized, prior * scale, prior))
        out.append({"summary_ko": v.get("summary_ko", ""), "type": v["type"], "direction": v.get("direction"), "prior_return": _r(prior),
                    "expected_return_annual": v["expected_return_annual"], "realized": _r(realized), "error": _r(realized - v["expected_return_annual"]),
                    "hit": hit, "pending": bool(incomplete and require_full), "partial": bool(incomplete and not require_full),
                    "window_end": str(px.index[-1].date()), "evidence_ids": v.get("evidence_ids", [])})  # fmt: skip
    return out



NEXT_RB_MIN_TAIL_ROWS = 20  # 거래일 ≈ 1개월. 마지막 리밸런싱일 뷰의 '다음 리밸런싱까지' 창이 종료일에서 잘려 이보다 짧으면 판정 보류


def view_diagnostics_next_window(views_by_date, asset_px: pd.DataFrame, rb_dates, end, implied_by_date, implied_start, *,
                                 min_tail_rows: int = NEXT_RB_MIN_TAIL_ROWS):  # fmt: skip
    """뷰를 세운 리밸런싱일 d 부터 다음 리밸런싱일(없으면 종료일)까지의 실현 수익 vs 뷰 방향 (라운드 5).

    365일 지평(`view_diagnostics`)과 달리 '그 뷰로 비중을 바꾼 기간' 안에서 맞았는지를 본다.
    absolute 뷰는 기간에 비례한 내재 수익 대비, relative 뷰는 long−short 가 기간에 비례한 사전 차이보다 컸나.

    다음 리밸런싱일이 창 안에 없는 마지막 창은 종료일에서 잘린 것이다. 그 창이 min(min_tail_rows, 리밸런싱 간격 중앙값) 거래일보다 짧으면
    판정하지 않는다(hit=None, pending=True) — 적중률에서 빠진다. 020: 연 1회 리밸런싱의 마지막 뷰 4개를 종료일까지 8거래일로 채점해
    '다음 리밸런싱까지 43.8%' 가 됐다 (같은 뷰를 12개월 지표는 판정 보류로 뺐다). 간격이 1개월보다 짧은 규칙(2주)은 그 간격이 기준.
    """
    out = []
    rbs = sorted(pd.Timestamp(d) for d in (rb_dates or []))
    end_ts = pd.Timestamp(end)
    pos = sorted({int(asset_px.index.searchsorted(x)) for x in {*(pd.Timestamp(d) for d in (views_by_date or {})), *rbs} if x <= end_ts})
    gaps = [b - a for a, b in zip(pos, pos[1:], strict=False) if b > a]
    min_rows = min(min_tail_rows, float(np.median(gaps))) if gaps else min_tail_rows
    for d in sorted(views_by_date or {}):
        vs = views_by_date[d] or []
        if not vs:
            continue
        d0 = pd.Timestamp(d)
        nxt = next((x for x in rbs if x > d0), end_ts)
        px = asset_px.loc[d0:min(nxt, end_ts)]
        if len(px) < 2:
            continue
        pending = not any(x > d0 for x in rbs) and len(px) - 1 < min_rows  # 종료일에서 잘린 짧은 마지막 창
        real = px.iloc[-1] / px.iloc[0] - 1
        days = max(1, (px.index[-1] - px.index[0]).days)
        implied = (implied_by_date or {}).get(d) or implied_start or {}
        for v in vs:
            if any(t not in real.index for t in [*v.get("long", []), *v.get("short", [])]):
                continue
            prior_annual = _view_prior(v, implied)
            if v["type"] == "absolute":
                realized = float(real[v["long"][0]])
            else:
                realized = float(real[v["long"]].mean() - real[v["short"]].mean())
            hit = None if pending else bool(_view_hit(v, realized, prior_annual * days / 365.0, prior_annual))
            out.append({"as_of": str(d0.date()), "window_end": str(px.index[-1].date()), "horizon": "next_rebalance", "type": v["type"],
                        "summary_ko": v.get("summary_ko", ""), "expected_return_annual": v["expected_return_annual"], "realized": _r(realized), "hit": hit,
                        "pending": pending, "evidence_ids": v.get("evidence_ids", [])})  # fmt: skip
    return out


# ───────────────────────── all ─────────────────────────
def compute_all(raw, bench_idx, asset_px, targets, sectors, rebal_dates, rf, target_return, max_stock, max_sector, xirr_fn,
                settings: BacktestSettings, baseline_idx=None, views=None, implied=None, as_of=None, end=None, targets_by_date=None, min_cash: float = 0.0):  # fmt: skip
    """min_cash = 요청한 최소 현금 비율 (0 이면 '최소 현금보다 낮았던 날' 을 세지 않는다)."""
    td = settings.trading_days
    idx, values, flows = raw["index"], raw["values"], raw["flows"]
    r = daily_returns(idx)
    mr = monthly_returns(idx)
    te_ = td_eff(idx, td)
    cg, vol, mdd = cagr(idx, td), ann_vol(r, te_), drawdown_series(idx).min()
    dd_ = downside_deviation(r, rf, te_)
    var, cvar = var_cvar(mr)
    comp = composition_metrics(raw["security_weights"], asset_px, targets, sectors, max_stock, max_sector, settings.drift_tolerance, idx,
                               values=raw.get("values"), flows=raw.get("flows"), targets_by_date=targets_by_date, min_cash=min_cash)  # fmt: skip
    m = {
        "return": {"total_return": _r(total_return(idx)), "cagr": _r(cg), "best_month": _r(mr.max()), "worst_month": _r(mr.min()),
                   "positive_months_ratio": _r((mr > 0).mean()), "rolling_12m": rolling_12m(idx, target_return, td)},
        "risk": {"ann_vol": _r(vol), "downside_deviation": _r(dd_), "max_drawdown": _r(mdd), "mdd": mdd_info(idx),
                 "drawdown_episodes": drawdown_episodes(idx), "var_95_monthly": var, "cvar_95_monthly": cvar,
                 "worst_day": _r(r.min()) if len(r) else None, "skew": _r(r.skew()) if len(r) > 2 else None, "kurtosis": _r(r.kurt()) if len(r) > 3 else None},
        "risk_adjusted": {"sharpe": _r((cg - rf) / vol) if vol > 0 else None, "sortino": _r((cg - rf) / dd_) if dd_ > 0 else None,
                          "calmar": _r(cg / abs(mdd)) if mdd < 0 else None},
        "vs_benchmark": relative_to(idx, bench_idx, rf, td),
        "vs_baseline": None,
        # ticker_contribution_residual = 기간 수익률 − Σ 종목 기여 (수수료·적립일 처리). 종목→값 dict 에 가짜 종목으로 넣으면 보고서·해석이 종목으로 읽어서 여기 둔다
        "composition": {k: comp[k] for k in ["effective_n", "hhi", "top3_contribution_share", "sector_weights_avg", "max_weight_drift", "max_sector_drift", "breaches", "ticker_contribution_residual",
                                             "max_stock_weight", "max_stock_weight_ticker", "max_sector_weight", "max_sector_weight_sector", "days_above_stock_cap",
                                             "days_above_sector_cap", "days_above_stock_tol", "days_above_sector_tol", "n_days",
                                             "min_cash_weight", "min_cash_date", "days_cash_below_min"]},
        "trading": trading_metrics(raw["transactions"], raw["turnover"], rebal_dates, values, settings.commission_bps),
        "stability": rolling_metrics(idx, rf, td),
    }  # fmt: skip
    if baseline_idx is not None:
        rel = relative_to(idx, baseline_idx, rf, td)
        m["vs_baseline"] = {"active_return": rel["excess_cagr"], "active_risk": rel["tracking_error"], "information_ratio": rel["information_ratio"]}
    money = money_metrics(values, flows, xirr_fn, td)
    vd = view_diagnostics(views, asset_px, as_of or idx.index[0], end or idx.index[-1], implied or {}, settings.view_horizon_days) if views else []
    return {"metrics": m, "money": money, "monthly_returns": [{"year": d.year, "month": d.month, "return": _r(v)} for d, v in mr.items()],
            "yearly_returns": yearly_returns(idx), "ticker_contribution": comp["ticker_contribution"],
            "ticker_total_return": comp["ticker_total_return"], "view_diagnostics": vd}  # fmt: skip


def compute_to_date(idx: pd.Series, values: pd.Series, flows: pd.Series, bench_idx: pd.Series, rf, xirr_fn, settings: BacktestSettings, baseline_idx=None):
    """체크포인트의 '시작부터 이날까지' 요약 13개 값. compute_all 과 같은 식을 쓰되 필요한 것만 계산한다 (라운드 4 S8).

    flat_to_date(compute_all(...)) 과 값이 같아야 한다 — test_compute_to_date_matches_compute_all 이 확인.
    """
    td = settings.trading_days
    r = daily_returns(idx)
    mr = monthly_returns(idx)
    te_ = td_eff(idx, td)
    cg, vol, mdd = cagr(idx, td), ann_vol(r, te_), drawdown_series(idx).min()
    dd_ = downside_deviation(r, rf, te_)
    rel = relative_to(idx, bench_idx, rf, td)
    base = relative_to(idx, baseline_idx, rf, td) if baseline_idx is not None else None
    n_days = len(idx) - 1
    return {"total_return": _r(total_return(idx)), "cagr": _r(cg), "ann_vol": _r(vol),
            "sharpe": _r((cg - rf) / vol) if vol > 0 else None, "sortino": _r((cg - rf) / dd_) if dd_ > 0 else None, "max_drawdown": _r(mdd),
            "calmar": _r(cg / abs(mdd)) if mdd < 0 else None, "excess_cagr": rel["excess_cagr"], "beta": rel["beta"],
            "information_ratio": rel["information_ratio"], "irr_annual": _r(irr_annual(values, flows, xirr_fn)),
            "positive_months_ratio": _r((mr > 0).mean()), "active_return_vs_baseline": base["excess_cagr"] if base else None, "reliable": n_days >= td}  # fmt: skip
