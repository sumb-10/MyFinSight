"""bt 기반 실행 (M5-01). 정적 비중·날짜별 비중 포트폴리오, 월 적립, 리밸런싱 일정.

체결 규칙 (D4): 리밸런싱일 t 의 목표 비중은 t−1 까지 자료로 계산된 값이고(Module4), 여기서는 t 종가로 체결한다.
가격 패널은 MarketDataView.panel() 이 만든다 (USD 수정종가, 품질 판정 통과 종목만).
"""

from __future__ import annotations

import numpy as np
import pandas as pd
from scipy.optimize import brentq

import bt

from backend.analysis.settings import BacktestSettings


# ───────────────────────── schedules ─────────────────────────
def _period_key(ts: pd.Timestamp, unit: str):
    return {"1m": (ts.year, ts.month), "1q": (ts.year, (ts.month - 1) // 3), "6m": (ts.year, (ts.month - 1) // 6), "1y": (ts.year,)}[unit]


def rebalance_dates(rule: dict, calendar: pd.DatetimeIndex, as_of, settings: BacktestSettings) -> list:
    cal = calendar[calendar >= pd.Timestamp(as_of)]
    if not rule.get("enabled", True) or rule["count"] == 0:
        return [cal[0]]  # buy and hold: 시작일 1회만
    if rule["unit"] == "2w":
        out = list(cal[:: settings.rebalance_trading_days["2w"] * rule["count"]])
    else:
        firsts, seen = [], set()
        for ts in cal:
            k = _period_key(ts, rule["unit"])
            if k not in seen:
                seen.add(k)
                firsts.append(ts)
        out = firsts[:: rule["count"]]
    if len(out) > 1 and out[-1] == cal[-1]:
        out = out[:-1]  # 마지막 날에는 리밸런싱하지 않음 (종료 체크포인트만)
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
    """정해진 날짜에 amount 를 자본 유입으로 넣고 목표 비중대로 즉시 투자 (기존 보유는 건드리지 않음)."""

    def __init__(self, dates, amount, weights):
        super().__init__()
        self.dates, self.amount, self.weights = {pd.Timestamp(d) for d in dates}, float(amount), weights

    def __call__(self, target):
        if target.now in self.dates and self.amount > 0:
            target.adjust(self.amount, flow=True)
            w_now = self.weights(target.now) if callable(self.weights) else self.weights
            for t, w in w_now.items():
                if t in target.children and w > 0:
                    target.allocate(self.amount * w, child=t)
        return True


# ───────────────────────── run ─────────────────────────
def _commission(settings: BacktestSettings):
    bps = settings.commission_bps
    return lambda q, p: abs(q) * p * bps / 1e4


def run_static_portfolio(pid, weights: dict, data: pd.DataFrame, initial_capital, rebal_dates, contrib_dates, contrib_amount, settings: BacktestSettings):
    algos = [ContributeOnDates(contrib_dates, contrib_amount, weights), bt.algos.RunOnDate(*rebal_dates), bt.algos.SelectAll(),
             bt.algos.WeighSpecified(**weights), bt.algos.Rebalance()]  # fmt: skip
    strat = bt.Strategy(pid, algos)
    b = bt.Backtest(strat, data[list(weights)].copy(), name=pid, initial_capital=float(initial_capital), commissions=_commission(settings),
                    integer_positions=settings.integer_positions, progress_bar=False)  # fmt: skip
    return b, bt.run(b)


def run_dynamic_portfolio(pid, weights_by_date: dict, data: pd.DataFrame, initial_capital, contrib_dates, contrib_amount, settings: BacktestSettings):
    """날짜마다 바뀌는 목표 비중 (walk-forward). weights_by_date: {date: {ticker: w}}."""
    wdf = pd.DataFrame({pd.Timestamp(d): w for d, w in weights_by_date.items()}).T.sort_index().fillna(0.0)
    cols = list(wdf.columns)
    dates = list(wdf.index)

    def latest(now):
        past = wdf[wdf.index <= now]
        return (past.iloc[-1] if len(past) else wdf.iloc[0]).to_dict()

    algos = [ContributeOnDates(contrib_dates, contrib_amount, latest), bt.algos.RunOnDate(*dates), bt.algos.SelectAll(),
             bt.algos.WeighTarget(wdf), bt.algos.Rebalance()]  # fmt: skip
    strat = bt.Strategy(pid, algos)
    b = bt.Backtest(strat, data[cols].copy(), name=pid, initial_capital=float(initial_capital), commissions=_commission(settings),
                    integer_positions=settings.integer_positions, progress_bar=False)  # fmt: skip
    return b, bt.run(b)


def extract_raw(b, res, first_date) -> dict:
    """지표 계층용 원시 시계열. bt 가 앞에 붙이는 전액 현금 행(자료 시작 하루 전)은 버리고 초기자본 유입을 첫 거래일로 옮긴다."""
    first = pd.Timestamp(first_date)

    def cut(x):
        return x[x.index >= first]

    flows = b.strategy.flows.astype(float)
    initial = float(flows[flows.index < first].sum())
    flows = cut(flows).copy()
    flows.iloc[0] += initial
    idx = cut(res.prices[b.name].astype(float))
    idx = idx / idx.iloc[0] * 100.0
    tx = res.get_transactions()
    tx = tx.reset_index() if tx is not None and len(tx) else pd.DataFrame(columns=["Date", "Security", "price", "quantity"])
    return {"id": b.name, "index": idx, "values": cut(b.strategy.values.astype(float)), "flows": flows,
            "security_weights": cut(b.security_weights.astype(float)), "positions": cut(b.positions.astype(float)),
            "turnover": cut(b.turnover.astype(float)), "transactions": tx}  # fmt: skip


def xirr(dates, amounts) -> float:
    """현금흐름의 연환산 금액가중수익률 (음수 = 투입, 양수 = 회수)."""
    d0 = pd.Timestamp(dates[0])
    t = np.array([(pd.Timestamp(d) - d0).days / 365.0 for d in dates])
    a = np.array(amounts, float)
    try:
        return float(brentq(lambda r: np.sum(a / (1 + r) ** t), -0.9999, 10.0, maxiter=500))
    except ValueError:
        return float("nan")
