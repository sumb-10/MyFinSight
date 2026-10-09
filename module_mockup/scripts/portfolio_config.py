"""Portfolio construction / Black-Litterman settings (stages 8-10)."""

LOOKBACK_DAYS = 756                 # trading days of daily returns before as_of used for the covariance
MIN_HISTORY_DAYS_FOR_MODEL = 252    # a ticker needs at least this many returns inside the window
SHRINKAGE = "ledoit_wolf"           # "ledoit_wolf" | "none"
TAU = 0.05                          # uncertainty scale of the prior (BL)
RISK_AVERSION = {"conservative": 4.0, "moderate": 2.5, "aggressive": 1.5}   # delta by risk_tolerance (mode "fixed")
RISK_AVERSION_MODE = "market_implied"   # "fixed": table above | "market_implied": delta = SPY excess mean / SPY variance x multiplier
RISK_AVERSION_MULT = {"conservative": 1.5, "moderate": 1.0, "aggressive": 0.7}
MIN_WEIGHT = 0.01                       # floor for every held stock in min_variance / Black-Litterman optimizations (keeps num_holdings)
OMEGA_METHOD = "he_litterman_confidence"   # Omega_kk = (1/c_k - 1) * p_k (tau Sigma) p_k'
CONFIDENCE_FLOOR = 0.1              # views below this confidence are raised to it (near-ignored anyway)
ABS_RETURN_RANGE = (-0.5, 1.0)      # allowed annual expected return for absolute views
REL_RETURN_RANGE = (0.0, 0.5)       # allowed annual outperformance for relative views
TEMPLATES = ["equal_weight", "market_cap", "inverse_volatility", "min_variance"]
TEMPLATE_NAMES_KO = {
    "equal_weight": ("동일비중", "모든 종목에 같은 비중 1/N"),
    "market_cap": ("시가총액비중", "시가총액에 비례한 비중 (지수 방식)"),
    "inverse_volatility": ("역변동성비중", "변동성이 낮은 종목에 더 큰 비중 (1/σ 정규화)"),
    "min_variance": ("최소분산", "포트폴리오 분산을 최소화하는 비중 (제약 포함 최적화)"),
}
MAX_ITER = 50                       # cap-and-redistribute iterations

# news evidence (stage 9a) — team DB + optional web-search records
NEWS_WINDOW_DAYS = 14               # evidence window before each construction date: [d - 14d, d)
NEWS_PER_TICKER = 10                # headlines kept per ticker per window (deduplicated, newest first)
MIN_NEWS_TICKERS = 3                # a window needs news for at least this many tickers to generate news views
NEWS_LANGS = ("en",)
