"""bt-based execution of static-weight portfolios with monthly contributions (stage 11).

Produces raw materials only (index, values, flows, weights, transactions); all analytics live in
backtest_metrics.py so that final metrics and per-checkpoint "to_date" metrics share one definition.
"""
import datetime as dt
import numpy as np
import pandas as pd
import pyarrow.parquet as pq
import bt
from scipy.optimize import brentq
from common import RAW
from portfolio import load_adj_close, trading_days
import backtest_config as BC


# ───────────────────────── data ─────────────────────────
def load_price_panel(tickers, bench, start, end) -> pd.DataFrame:
    """adj_close panel of the tickers plus one or more benchmark tickers (aligned on the first benchmark's trading days)."""
    benches = [bench] if isinstance(bench, str) else list(bench)
    px = load_adj_close(tickers, start, end)
    t = pq.read_table(RAW / "benchmarks.parquet", columns=["date", "ticker", "adj_close"],
                      filters=[("ticker", "in", benches), ("date", ">=", pd.Timestamp(start)), ("date", "<=", pd.Timestamp(end))]).to_pandas()
    b = t.pivot(index="date", columns="ticker", values="adj_close").sort_index()[benches]
    panel = px.join(b, how="inner").sort_index()
    if panel.iloc[0].isna().any():
        raise ValueError(f"missing prices on first day for {list(panel.columns[panel.iloc[0].isna()])}")
    return panel.ffill()


# ───────────────────────── schedules ─────────────────────────
def _period_key(ts: pd.Timestamp, unit: str):
    return {"1m": (ts.year, ts.month), "1q": (ts.year, (ts.month - 1) // 3), "6m": (ts.year, (ts.month - 1) // 6),
            "1y": (ts.year,)}[unit]


def rebalance_dates(rule: dict, calendar: pd.DatetimeIndex, as_of) -> list:
    cal = calendar[calendar >= pd.Timestamp(as_of)]
    if not rule.get("enabled", True) or rule["count"] == 0:
        return [cal[0]]
    if rule["unit"] == "2w":
        out = list(cal[::BC.REBALANCE_TRADING_DAYS["2w"] * rule["count"]])
    else:
        firsts, seen = [], set()
        for ts in cal:
            k = _period_key(ts, rule["unit"])
            if k not in seen:
                seen.add(k); firsts.append(ts)
        out = firsts[::rule["count"]]
    if len(out) > 1 and out[-1] == cal[-1]:
        out = out[:-1]            # never rebalance on the last day of the window (closing checkpoint only)
    return out


def contribution_dates(calendar: pd.DatetimeIndex, as_of, end, day: int) -> list:
    out, cur = [], (pd.Timestamp(as_of) + pd.offsets.MonthBegin(1))
    while cur <= pd.Timestamp(end):
        target = pd.Timestamp(cur.year, cur.month, min(day, cur.days_in_month))
        nxt = calendar[(calendar >= target) & (calendar <= pd.Timestamp(end))]
        if len(nxt):
            out.append(nxt[0])
        cur = cur + pd.offsets.MonthBegin(1)
    return out


class ContributeOnDates(bt.Algo):
    """Inject `amount` as a capital flow on the given dates and invest it immediately at the target
    weights (existing holdings are not rebalanced). Flows do not affect the TWR price index."""
    def __init__(self, dates, amount, weights):
        super().__init__()
        self.dates, self.amount, self.weights = set(pd.Timestamp(d) for d in dates), float(amount), dict(weights)

    def __call__(self, target):
        if target.now in self.dates and self.amount > 0:
            target.adjust(self.amount, flow=True)
            for t, w in self.weights.items():
                if t in target.children and w > 0:
                    target.allocate(self.amount * w, child=t)
        return True


# ───────────────────────── run ─────────────────────────
def run_static_portfolio(pid, weights: dict, data: pd.DataFrame, initial_capital, rebal_dates, contrib_dates, contrib_amount):
    algos = [ContributeOnDates(contrib_dates, contrib_amount, weights),
             bt.algos.RunOnDate(*rebal_dates), bt.algos.SelectAll(), bt.algos.WeighSpecified(**weights), bt.algos.Rebalance()]
    strat = bt.Strategy(pid, algos)
    b = bt.Backtest(strat, data[list(weights)].copy(), name=pid, initial_capital=float(initial_capital),
                    commissions=lambda q, p: abs(q) * p * BC.COMMISSION_BPS / 1e4,
                    integer_positions=BC.INTEGER_POSITIONS, progress_bar=False)
    res = bt.run(b)
    return b, res


def extract_raw(b, res, first_date) -> dict:
    """Raw series for the metrics layer. bt prepends a synthetic all-cash row one day before the data
    starts; it is dropped here and the initial-capital flow is moved to the first real trading day."""
    first = pd.Timestamp(first_date)
    cut = lambda x: x[x.index >= first]
    flows = b.strategy.flows.astype(float)
    initial = float(flows[flows.index < first].sum())
    flows = cut(flows).copy(); flows.iloc[0] += initial
    idx = cut(res.prices[b.name].astype(float)); idx = idx / idx.iloc[0] * 100.0
    tx = res.get_transactions()
    tx = tx.reset_index() if tx is not None and len(tx) else pd.DataFrame(columns=["Date", "Security", "price", "quantity"])
    return {"id": b.name, "index": idx, "values": cut(b.strategy.values.astype(float)), "flows": flows,
            "security_weights": cut(b.security_weights.astype(float)), "positions": cut(b.positions.astype(float)),
            "turnover": cut(b.turnover.astype(float)), "transactions": tx}


# ───────────────────────── helpers ─────────────────────────
def xirr(dates, amounts) -> float:
    """Annualized money-weighted return of dated cash flows (negative = invested, positive = received)."""
    d0 = pd.Timestamp(dates[0])
    t = np.array([(pd.Timestamp(d) - d0).days / 365.0 for d in dates]); a = np.array(amounts, float)
    f = lambda r: np.sum(a / (1 + r) ** t)
    try:
        return float(brentq(f, -0.9999, 10.0, maxiter=500))
    except ValueError:
        return float("nan")


# ───────────────────────── self test ─────────────────────────
def _selftest():
    as_of, end = dt.date(2023, 4, 3), dt.date(2024, 4, 1)
    cal = trading_days(as_of, end)
    tk = ["AVGO", "ORCL", "ETN"]
    data = load_price_panel(tk, "SPY", as_of, end)
    rb = rebalance_dates({"count": 1, "unit": "1q", "enabled": True}, cal, as_of)
    cd = contribution_dates(cal, as_of, end, 25)
    assert len(rb) == 4 and rb[0] == cal[0] and rb[-1] != cal[-1], rb   # Apr/Jul/Oct 2023, Jan 2024 (2024-04-01 = last day, excluded)
    assert len(cd) == 11, len(cd)   # May 2023 .. Mar 2024
    # (1) single asset: contributions invested immediately -> TWR index equals the no-contribution index (commission-level tolerance)
    s1, r1 = run_static_portfolio("spy_c", {"SPY": 1.0}, data, 10000, rb, cd, 300.0)
    s0, r0 = run_static_portfolio("spy_0", {"SPY": 1.0}, data, 10000, rb, [], 0.0)
    i1, i0 = extract_raw(s1, r1, as_of)["index"], extract_raw(s0, r0, as_of)["index"]
    assert np.abs(i1.values / i0.values - 1).max() < 2e-3, "flows leaked into the TWR index"
    spy_tr = data["SPY"].iloc[-1] / data["SPY"].iloc[0] - 1
    assert abs(spy_tr - (i0.iloc[-1] / 100 - 1)) < 0.003, (spy_tr, i0.iloc[-1])
    # (2) multi asset with contributions: flows sum, weights at rebalance = target, contributions invested (cash stays ~0)
    w = {t: 1 / 3 for t in tk}
    b1, res1 = run_static_portfolio("eq", w, data, 10000, rb, cd, 300.0)
    raw1 = extract_raw(b1, res1, as_of)
    assert abs(raw1["flows"].sum() - (10000 + 300 * len(cd))) < 1e-6, raw1["flows"].sum()
    for d in rb:
        sw = raw1["security_weights"].loc[d]
        assert np.abs(sw[tk].values - 1 / 3).max() < 2e-3, (d, sw.to_dict())
    cash_w = 1 - raw1["security_weights"][tk].sum(axis=1)
    assert cash_w.max() < 0.01, f"contributions left as cash: max cash weight {cash_w.max():.3f}"
    irr = xirr([as_of, end], [-100, 110]); assert abs(irr - 0.10) < 0.002, irr
    print(f"engine selftest OK  rebalances={len(rb)} contributions={len(cd)} spy_tr={spy_tr:.4f} "
          f"idx_dev={np.abs(i1.values / i0.values - 1).max():.2e} final_value={raw1['values'].iloc[-1]:,.0f} max_cash_w={cash_w.max():.4f} tx_rows={len(raw1['transactions'])}")


if __name__ == "__main__":
    _selftest()
