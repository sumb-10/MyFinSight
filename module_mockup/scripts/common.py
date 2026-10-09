"""Shared helpers and paths for the mock-up pipeline.

Data caches (prices, fundamentals) live OUTSIDE the Google Drive folder because Drive
file streaming stalls Python reads. Override with env MYFINSIGHT_DATA.
"""
import json, os, re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
INPUT = ROOT / "input"
OUTPUT = ROOT / "output"
PROMPTS = ROOT / "prompts"
STUBS = ROOT / "stubs"
REFERENCE = ROOT / "data" / "reference"      # small, reproducible, committed
PROCESSED = ROOT / "data" / "processed"      # descriptor etc., committed

DATA_HOME = Path(os.environ.get("MYFINSIGHT_DATA", Path.home() / ".myfinsight" / "data"))
RAW = DATA_HOME / "raw"                      # yfinance caches, NOT committed, NOT on Drive

UNIVERSE_NAME = "sp500_nasdaq100"
DESCRIPTOR_PATH = PROCESSED / f"{UNIVERSE_NAME}_descriptor.json"
TAXONOMY_PATH = REFERENCE / "gics_taxonomy.json"

_COMMENT_RE = re.compile(r'("(?:\\.|[^"\\])*")|//[^\n]*|/\*.*?\*/', re.DOTALL)


def load_jsonc(path):
    """Load JSON that may contain // or /* */ comments and trailing commas."""
    text = Path(path).read_text(encoding="utf-8")
    stripped = _COMMENT_RE.sub(lambda m: m.group(1) or "", text)
    stripped = re.sub(r",(\s*[}\]])", r"\1", stripped)
    return json.loads(stripped)


def load_json(path):
    return json.loads(Path(path).read_text(encoding="utf-8"))


def dump_json(obj, path):
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    Path(path).write_text(json.dumps(obj, indent=2, ensure_ascii=False, default=str), encoding="utf-8")
    return Path(path)


def render_template(template: str, **vars_) -> str:
    """Replace {{name}} placeholders. Unknown placeholders are left as-is."""
    for k, v in vars_.items():
        template = template.replace("{{" + k + "}}", str(v))
    return template


def stage_meta(request_id: str, stage: str, **extra) -> dict:
    import datetime as _dt
    return {"request_id": request_id, "stage": stage,
            "generated_at": _dt.datetime.now().isoformat(timespec="seconds"), **extra}
