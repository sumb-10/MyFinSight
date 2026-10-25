"""개발용 CLI: 요청 JSON 하나로 파이프라인을 인프로세스 실행 (큐 없이). module_mockup/scripts/run_pipeline.py 의 후속.

  python -m backend.analysis.executor.cli run --request path/to/request.json [--stub|--api] [--run-id run_x] [--db sqlite:///data/myfinsight.db]
  python -m backend.analysis.executor.cli run --request module_mockup/input/01_user_request.ai.jsonc --stub   # jsonc 도 됨
"""

from __future__ import annotations

import argparse
import datetime as dt
import logging
import sys
from pathlib import Path

from backend.analysis.common.dbconn import open_analysis_repository
from backend.analysis.common.jsonio import load_json, load_jsonc
from backend.analysis.common.llm import make_llm
from backend.analysis.common.store import new_run_id
from backend.analysis.executor.context import RunContext
from backend.analysis.executor.runner import run
from backend.analysis.m2_data.market_data import MarketData
from backend.analysis.paths import run_dir
from backend.analysis.schemas.backtest import BacktestRequest
from backend.analysis.settings import AnalysisSettings, replace_settings


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="backend.analysis.executor.cli")
    sub = ap.add_subparsers(dest="cmd", required=True)
    r = sub.add_parser("run", help="요청 파일로 전체 파이프라인 실행")
    r.add_argument("--request", required=True, help="UserRequest JSON/JSONC (derived 가 있으면 그대로, 없으면 계산)")
    r.add_argument("--backtest-request", default=None, help="BacktestRequest JSON/JSONC (선택)")
    r.add_argument("--run-id", default=None)
    r.add_argument("--db", default=None, help="DATABASE_URL 대신 쓸 주소 (예: sqlite:///data/myfinsight.db)")
    mode = r.add_mutually_exclusive_group()
    mode.add_argument("--stub", action="store_true", help="LLM stub 모드 (기본: 설정/환경변수)")
    mode.add_argument("--api", action="store_true", help="LLM api 모드")
    r.add_argument("--as-of", default=None, help="분석 기준일 YYYY-MM-DD (기본: DB 최신 완료 거래일)")
    r.add_argument("-v", "--verbose", action="store_true")
    a = ap.parse_args(argv)
    logging.basicConfig(level=logging.DEBUG if a.verbose else logging.INFO, format="%(levelname)s %(name)s: %(message)s")

    settings = AnalysisSettings.load()
    if a.stub or a.api:
        settings = replace_settings(settings, llm=replace_settings(settings.llm, mode="api" if a.api else "stub"))
    repo = open_analysis_repository(a.db)
    md = MarketData(repo, settings)
    req = load_jsonc(a.request) if a.request.endswith(".jsonc") else load_json(a.request)
    if a.as_of and "derived" not in req:
        req.setdefault("horizon", {})["start_date"] = a.as_of
    bt_req = None
    if a.backtest_request:
        raw = load_jsonc(a.backtest_request) if a.backtest_request.endswith(".jsonc") else load_json(a.backtest_request)
        bt_req = BacktestRequest.model_validate(raw)
    rid = a.run_id or new_run_id(dt.datetime.now())
    rdir = run_dir(rid)
    llm = make_llm(settings.llm, run_dir=rdir, run_id=rid)
    ctx = RunContext(run_id=rid, request=req, repo=repo, md=md, llm=llm, settings=settings, run_dir=rdir, bt_req=bt_req)
    outcome = run(ctx)
    print(f"[{rid}] {outcome.status}  -> {rdir}")
    for s in outcome.steps:
        print(f"  {s.name:<20} {s.status:<9} {s.elapsed_s or '':>6}  {s.summary or s.error_message or ''}")
    return 0 if outcome.status in ("success", "partial") else 1


if __name__ == "__main__":
    sys.exit(main())
