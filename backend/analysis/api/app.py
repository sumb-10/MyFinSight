"""분석 서비스 API (M0-06). `uvicorn backend.analysis.api.app:app --port 8001`. 경로 접두어 /api/v1.

- 프로필 조회·저장, 요청 생성·보충 질문 답·확정, 실행 상태(폴링), 리포트 목록·상세, 모의투자(/paper), (후순위) 수정 요청.
- 분석은 여기서 실행하지 않는다. confirm 이 큐에 넣고 `backend.analysis.executor.worker` 가 돈다.
- 단일 사용자·인증 없음 (K15). CORS 는 ANALYSIS_CORS_ORIGINS (기본 http://localhost:5173).
"""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path
from typing import Any

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.middleware.gzip import GZipMiddleware

from backend.adapters.crawlers import config
from backend.analysis.api import errors
from backend.analysis.api.routers import meta, paper, profile, reports, requests, runs
from backend.analysis.api.services import Services
from backend.analysis.common.dbconn import default_repo
from backend.analysis.common.llm import LlmClient
from backend.analysis.common.store import JsonStore
from backend.analysis.settings import AnalysisSettings

API_PREFIX = "/api/v1"


def create_analysis_app(
    repo: Callable[[], Any] | None = None,
    *,
    store_dir: Path | str | None = None,
    settings: AnalysisSettings | None = None,
    llm: Callable[[], LlmClient] | None = None,
    cors_origins: list[str] | None = None,
) -> FastAPI:
    settings = settings or AnalysisSettings.load()
    services = Services(repo_factory=repo or default_repo, store=JsonStore(store_dir), settings=settings, llm_factory=llm)
    app = FastAPI(title="MyFinSight 분석 서비스 API", version="1.0", docs_url=f"{API_PREFIX}/docs", openapi_url=f"{API_PREFIX}/openapi.json")
    origins = cors_origins if cors_origins is not None else [o.strip() for o in (config.get("ANALYSIS_CORS_ORIGINS") or "http://localhost:5173").split(",") if o.strip()]
    app.add_middleware(CORSMiddleware, allow_origins=origins, allow_methods=["*"], allow_headers=["*"])
    app.add_middleware(GZipMiddleware, minimum_size=1024)  # 리포트 문서(수백 KB~MB)는 압축해서 보낸다 (라운드 4)
    app.state.services = services
    errors.install(app)
    for r in (meta.router, profile.router, requests.router, runs.router, reports.router, paper.router):
        app.include_router(r, prefix=API_PREFIX)
    return app


app = create_analysis_app()
