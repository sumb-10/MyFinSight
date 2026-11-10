"""GET /health, GET /meta/options, GET /strategy/recommendation."""

from __future__ import annotations

from typing import Any, get_args

from fastapi import APIRouter, Request

from backend.analysis.api.routers import services
from backend.analysis.common.dbconn import describe
from backend.analysis.errors import public_message
from backend.analysis.executor.queue import pid_alive
from backend.analysis.m1_request.strategy_recommendation import Tendency, recommend
from backend.analysis.schemas import request as R

router = APIRouter(tags=["meta"])


@router.get("/health")
def health(request: Request) -> dict[str, Any]:
    sv = services(request)
    out: dict[str, Any] = {"ok": True, "api_version": "1", "llm_mode": sv.settings.llm.mode}
    try:
        md = sv.market_data()
        out["db"] = {"ok": True, "latest_trading_day": str(md.ceiling), "data_start": str(md.data_range()[0]), "where": describe()}
    except Exception as e:  # noqa: BLE001
        out["ok"] = False
        out["db"] = {"ok": False, "error": f"{type(e).__name__}: {public_message(e)}"[:200]}
    runs = sv.queue.list()
    running = [r for r in runs if r.status == "running"]
    lock = sv.store.path("worker.lock")
    pid = None
    if lock.exists():
        try:
            pid = int(lock.read_text().strip() or 0) or None
        except ValueError:
            pid = None
    if not pid and running:  # 잠금 파일이 비어 있으면 실행 중인 건의 worker_pid 로 본다
        pid = running[0].worker_pid
    out["worker"] = {"alive": pid_alive(pid) if pid else False, "running_run_id": running[0].run_id if running else None}
    out["queue_length"] = sv.queue.length()
    return out


@router.get("/meta/options")
def options(request: Request) -> dict[str, Any]:
    sv = services(request)
    s = sv.settings
    opts: dict[str, Any] = {
        "universes": list(get_args(R.Universe)), "templates": list(get_args(R.Template)), "weightings": list(get_args(R.Weighting)),
        "risk_tolerance": list(get_args(R.RiskTolerance)), "rebalance_units": list(get_args(R.RebalanceUnit)),
        "age_band": ["20s", "30s", "40s", "50s", "60s+"], "investment_experience": ["none", "beginner", "intermediate", "advanced"],
        "financial_knowledge": ["basic", "intermediate", "expert"], "purpose": ["wealth_growth", "income", "capital_preservation", "retirement"],
        "loss_reaction": ["sell", "hold", "buy_more"], "benchmarks": [s.market.primary_benchmark_default, *s.market.extra_benchmarks, s.market.kr_benchmark],
        "max_questions": s.dialog.max_questions, "default_backtest_years": s.backtest.default_backtest_years, "markets": list(s.market.markets),
        "labels_ko": {"universes": {"SP500": "S&P 500", "NASDAQ100": "NASDAQ-100", "KOSPI200": "KOSPI 200"},
                      "templates": {"low_per": "저PER", "quality": "퀄리티(ROE)", "momentum": "모멘텀", "low_volatility": "저변동성", "high_dividend": "고배당"},
                      "weightings": {"equal_weight": "동일비중", "market_cap": "시가총액비중", "inverse_volatility": "역변동성", "min_variance": "최소분산"}},
    }  # fmt: skip
    try:
        md = sv.market_data()
        opts["data_range"] = [str(md.data_range()[0]), str(md.ceiling)]
        opts["latest_trading_day"] = str(md.ceiling)
    except Exception as e:  # noqa: BLE001
        opts["data_range"] = None
        opts["data_error"] = f"{type(e).__name__}: {public_message(e)}"[:200]
    return opts


@router.get("/strategy/recommendation")
def strategy_recommendation(tendency: Tendency) -> dict[str, Any]:
    """투자성향(안정형~공격투자형)에 맞춘 추천 전략·이유·다른 전략 2개. 성향마다 정해 둔 고정 규칙 (m1_request/strategy_recommendation.py)."""
    return recommend(tendency)
