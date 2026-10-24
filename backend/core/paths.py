"""backend 폴더 기준 경로 (작업 폴더와 상관없이 같은 파일을 찾음)."""

from pathlib import Path

BACKEND_DIR = Path(__file__).resolve().parents[1]
"""backend/ 폴더."""
DATA_DIR = BACKEND_DIR / "data"
"""저장소에 넣는 참조 자료: data/config (구성종목·분류 CSV), data/reference (GICS 분류표)."""
