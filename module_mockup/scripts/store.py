"""Local JSON store (spec M0-04 / appendix H): atomic writes + JSON Schema validation. First use: the run index."""
import datetime as dt, json, os, tempfile
from pathlib import Path
from common import STORE_SCHEMAS, STORE_DATA, load_json

try:
    import jsonschema
except ImportError:                    # validation is optional in dev environments
    jsonschema = None


def validate(obj, schema_name):
    if jsonschema is None:
        return
    schema = load_json(STORE_SCHEMAS / f"{schema_name}.schema.json")
    jsonschema.Draft202012Validator(schema).validate(obj)


def save_atomic(path, obj, schema_name=None):
    if schema_name:
        validate(obj, schema_name)
    path = Path(path); path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=path.parent, prefix=path.name + ".", suffix=".tmp")
    with os.fdopen(fd, "w", encoding="utf-8") as f:
        json.dump(obj, f, ensure_ascii=False, indent=2, default=str)
    os.replace(tmp, path)
    return path


def now():
    return dt.datetime.now().astimezone().isoformat(timespec="seconds")


def update_run_index(run):
    """Insert or update one run entry in store/data/runs.json (schema run_index)."""
    path = STORE_DATA / "runs.json"
    idx = load_json(path) if path.exists() else {"schema_version": 1, "runs": []}
    runs = [r for r in idx["runs"] if r["run_id"] != run["run_id"]]
    cur = next((r for r in idx["runs"] if r["run_id"] == run["run_id"]), {})
    runs.append({**cur, **run})
    idx["runs"] = sorted(runs, key=lambda r: r["queued_at"])
    save_atomic(path, idx, "run_index")
    return path
