"""Backtest settings (stage 11) and validation knobs (stage 12)."""

COMMISSION_BPS = 5             # commission = traded value x 0.05%
INTEGER_POSITIONS = False      # fractional shares (small account, high-priced stocks)
RISK_FREE_RATE = 0.04          # annual constant; Sharpe / Sortino / alpha
TRADING_DAYS = 252
SERIES_FREQ = "daily"
DRIFT_TOLERANCE = 0.25         # between rebalances a weight may drift up to cap x (1 + tol) before a soft breach
REBALANCE_TRADING_DAYS = {"2w": 10}
CHECKPOINT_FREQ = "rebalance"  # "rebalance" (every rebalance date + closing) | "monthly" (adds month-end checkpoints)
EVENT_DRAWDOWN_LEVELS = [-0.10, -0.20]
SAVE_DAILY_PANEL = True
VIEW_HORIZON_DAYS = 365        # realized-return window for view diagnostics
VOL_BANDS = {"low": 0.15, "medium": 0.30, "high": 9.99}   # stage 12 R7 upper bounds on ann_vol
