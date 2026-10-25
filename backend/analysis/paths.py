"""패키지 안·밖 경로. 사용자 데이터(store/data, output)는 git 밖 폴더이며 환경변수로 옮길 수 있다."""

from __future__ import annotations

import os
from pathlib import Path

PKG = Path(__file__).resolve().parent  # backend/analysis
REPO_ROOT = PKG.parents[1]  # MyFinSight/
PROMPTS = PKG / "prompts"
STUBS = PKG / "stubs"
STORE_SCHEMAS = PKG / "common" / "store_schemas"
PROCESSED = REPO_ROOT / "backend" / "data" / "processed"  # 디스크립터 (backend/scripts/build_descriptor.py)
REFERENCE = REPO_ROOT / "backend" / "data" / "reference"


def store_dir() -> Path:
    """로컬 JSON 저장소 (프로필·요청·runs.json·모의투자·비교). 기본 <repo>/data/analysis_store."""
    return Path(os.environ.get("ANALYSIS_STORE_DIR") or REPO_ROOT / "data" / "analysis_store")


def output_root() -> Path:
    """실행별 산출물 폴더의 부모. 기본 <repo>/output."""
    return Path(os.environ.get("ANALYSIS_OUTPUT_DIR") or REPO_ROOT / "output")


def run_dir(run_id: str) -> Path:
    return output_root() / run_id


def llm_cache_dir() -> Path:
    return output_root() / "llm_cache"
