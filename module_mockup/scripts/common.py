"""Shared helpers and paths for the mock-up pipeline.

Data caches (prices, fundamentals) live OUTSIDE the Google Drive folder because Drive
file streaming stalls Python reads. Override with env MYFINSIGHT_DATA.
"""
import json, os, re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
INPUT = ROOT / "input"
OUTPUT_ROOT = ROOT / "output"               # shared: llm_cache/, llm_usage.jsonl, latest -> <run_id>


def _resolve_output():
    """Per-run output dir: $MYFINSIGHT_RUN_ID -> output/<run_id>; else output/latest (symlink) if present; else output/ (legacy flat)."""
    rid = os.environ.get("MYFINSIGHT_RUN_ID")
    if rid:
        return OUTPUT_ROOT / rid
    latest = OUTPUT_ROOT / "latest"
    return latest if latest.exists() else OUTPUT_ROOT


OUTPUT = _resolve_output()
RUN_ID = os.environ.get("MYFINSIGHT_RUN_ID") or (OUTPUT.resolve().name if OUTPUT != OUTPUT_ROOT else None)
PROMPTS = ROOT / "prompts"
STUBS = ROOT / "stubs"
REFERENCE = ROOT / "data" / "reference"      # small, reproducible, committed
PROCESSED = ROOT / "data" / "processed"      # descriptor etc., committed
STORE = ROOT / "store"                       # local JSON store (docs/module_prototype.md 부록 H)
STORE_SCHEMAS = STORE / "schemas"            # JSON Schema, committed
STORE_DATA = STORE / "data"                  # user data, git-ignored

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


def load_dotenv(path=None) -> dict:
    """Parse KEY=VALUE lines of a .env file (quotes and trailing ' # comments' stripped). Env vars override."""
    p = Path(path) if path else ROOT.parent / ".env"
    kv = {}
    if p.exists():
        for line in p.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line: continue
            k, v = line.split("=", 1); k = k.strip(); v = v.strip()
            if v[:1] in ("'", '"') and v[-1:] == v[:1]: v = v[1:-1]
            else: v = re.split(r"\s+#", v, 1)[0].strip()
            kv[k] = v
    return kv


def stage_meta(request_id: str, stage: str, **extra) -> dict:
    import datetime as _dt
    return {"request_id": request_id, "stage": stage,
            "generated_at": _dt.datetime.now().isoformat(timespec="seconds"), **extra}
