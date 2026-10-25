"""로컬 JSON 저장소 (M0-04, 부록 H). 팀 DB 에 없는 객체: 프로필, 분석 요청, run 색인(큐), 모의투자, 비교.

규칙: 스키마 검증 → 같은 폴더의 임시 파일에 쓰기 → 이름 바꾸기(원자적). JSONL 은 추가만.
여러 프로세스(API 워커 2개 + 분석 워커)가 같은 파일을 갱신하므로 `locked()` 로 직렬화한다.
"""

from __future__ import annotations

import datetime as dt
import fcntl
import json
import os
import secrets
import tempfile
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path
from typing import Any

from pydantic import BaseModel

from backend.analysis.common.jsonio import load_json, now_iso
from backend.analysis.errors import NotFound
from backend.analysis.paths import STORE_SCHEMAS, store_dir
from backend.analysis.schemas.dialog import AnalysisRequestDoc
from backend.analysis.schemas.run import RunIndexEntry

try:
    import jsonschema
except ImportError:  # 검증은 선택 (개발 환경)
    jsonschema = None


class JsonStore:
    def __init__(self, root: Path | None = None, *, schemas_dir: Path = STORE_SCHEMAS) -> None:
        self.root = Path(root or store_dir())
        self.schemas_dir = schemas_dir
        self.root.mkdir(parents=True, exist_ok=True)

    def path(self, rel: str) -> Path:
        return self.root / rel

    def read(self, rel: str, default: Any = None) -> Any:
        p = self.path(rel)
        if not p.exists():
            return default
        return load_json(p)

    def validate(self, obj: Any, schema_name: str) -> None:
        if jsonschema is None:
            return
        schema = load_json(self.schemas_dir / f"{schema_name}.schema.json")
        jsonschema.Draft202012Validator(schema).validate(obj)

    def write(self, rel: str, obj: Any, *, schema: str | None = None, model: type[BaseModel] | None = None) -> Path:
        if isinstance(obj, BaseModel):
            obj = obj.model_dump(mode="json")
        if model is not None:
            model.model_validate(obj)
        if schema:
            self.validate(obj, schema)
        p = self.path(rel)
        p.parent.mkdir(parents=True, exist_ok=True)
        fd, tmp = tempfile.mkstemp(dir=p.parent, prefix=p.name + ".", suffix=".tmp")
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(obj, f, ensure_ascii=False, indent=2, default=str)
        os.replace(tmp, p)
        return p

    def append_jsonl(self, rel: str, obj: Any) -> None:
        if isinstance(obj, BaseModel):
            obj = obj.model_dump(mode="json")
        p = self.path(rel)
        p.parent.mkdir(parents=True, exist_ok=True)
        with open(p, "a", encoding="utf-8") as f:
            f.write(json.dumps(obj, ensure_ascii=False, default=str) + "\n")

    def read_jsonl(self, rel: str) -> list[Any]:
        p = self.path(rel)
        if not p.exists():
            return []
        return [json.loads(line) for line in p.read_text(encoding="utf-8").splitlines() if line.strip()]

    @contextmanager
    def locked(self, name: str) -> Iterator[None]:
        """프로세스 간 배타 잠금 (fcntl.flock). 같은 이름은 한 번에 하나만."""
        d = self.root / ".locks"
        d.mkdir(parents=True, exist_ok=True)
        with open(d / f"{name}.lock", "w") as fh:
            fcntl.flock(fh, fcntl.LOCK_EX)
            try:
                yield
            finally:
                fcntl.flock(fh, fcntl.LOCK_UN)


# ───────────────────────── ID ─────────────────────────
def new_request_id(now: dt.datetime | None = None) -> str:
    now = now or dt.datetime.now()
    return f"req_{now:%Y%m%d_%H%M%S}_{secrets.token_hex(2)}"


def new_run_id(now: dt.datetime | None = None) -> str:
    now = now or dt.datetime.now()
    return f"run_{now:%Y%m%d_%H%M%S}_{secrets.token_hex(2)}"


def new_paper_id(now: dt.datetime | None = None) -> str:
    now = now or dt.datetime.now()
    return f"paper_{now:%Y%m%d}_{secrets.token_hex(2)}"


# ───────────────────────── 프로필 ─────────────────────────
class ProfileStore:
    """profile.json: 프로필 1개 + 버전 이력 (M1-01). 수정 = 새 버전 추가, 과거 리포트는 자기 버전을 참조."""

    REL = "profile.json"

    def __init__(self, store: JsonStore) -> None:
        self.store = store

    def load(self) -> dict[str, Any] | None:
        return self.store.read(self.REL)

    def current(self) -> dict[str, Any] | None:
        doc = self.load()
        if not doc:
            return None
        v = doc["current_version"]
        return next(x for x in doc["versions"] if x["version"] == v)

    def version(self, version: int) -> dict[str, Any]:
        doc = self.load()
        if not doc:
            raise NotFound("프로필이 없습니다")
        for x in doc["versions"]:
            if x["version"] == version:
                return x
        raise NotFound(f"프로필 버전 {version} 이 없습니다")

    def save(self, fields: dict[str, Any], *, note: str | None = None) -> dict[str, Any]:
        """새 버전을 추가하고 그 버전을 돌려준다. fields = profile/capital/horizon/risk/constraints/strategy_preference + 진단."""
        with self.store.locked("profile"):
            doc = self.load() or {"schema_version": 1, "profile_id": "default", "current_version": 0, "versions": []}
            ver = doc["current_version"] + 1
            entry = {"version": ver, "created_at": now_iso(), **({"note": note} if note else {}), **fields}
            doc["versions"].append(entry)
            doc["current_version"] = ver
            self.store.write(self.REL, doc, schema="profile")
            return entry


# ───────────────────────── 분석 요청 ─────────────────────────
class RequestStore:
    """requests/<request_id>.json (M1-02·03)."""

    def __init__(self, store: JsonStore) -> None:
        self.store = store

    def rel(self, request_id: str) -> str:
        return f"requests/{request_id}.json"

    def load(self, request_id: str) -> AnalysisRequestDoc:
        raw = self.store.read(self.rel(request_id))
        if raw is None:
            raise NotFound(f"요청 {request_id} 이 없습니다")
        return AnalysisRequestDoc.model_validate(raw)

    def save(self, doc: AnalysisRequestDoc) -> Path:
        return self.store.write(self.rel(doc.request_id), doc, model=AnalysisRequestDoc)

    def list(self) -> list[AnalysisRequestDoc]:
        d = self.store.path("requests")
        if not d.exists():
            return []
        out = [AnalysisRequestDoc.model_validate(load_json(p)) for p in sorted(d.glob("req_*.json"))]
        return sorted(out, key=lambda r: r.created_at)

    @contextmanager
    def locked(self, request_id: str) -> Iterator[None]:
        with self.store.locked(f"request_{request_id}"):
            yield


# ───────────────────────── run 색인 (큐 상태) ─────────────────────────
class RunIndex:
    """runs.json: 실행 목록과 큐 상태. 쓰기는 `locked("runs")` 안에서만."""

    REL = "runs.json"

    def __init__(self, store: JsonStore) -> None:
        self.store = store

    def load(self) -> list[RunIndexEntry]:
        raw = self.store.read(self.REL) or {"schema_version": 1, "runs": []}
        return [RunIndexEntry.model_validate(r) for r in raw["runs"]]

    def save(self, runs: list[RunIndexEntry]) -> None:
        runs = sorted(runs, key=lambda r: r.queued_at)
        self.store.write(self.REL, {"schema_version": 1, "runs": [r.model_dump(mode="json") for r in runs]})

    def get(self, run_id: str) -> RunIndexEntry:
        for r in self.load():
            if r.run_id == run_id:
                return r
        raise NotFound(f"실행 {run_id} 이 없습니다")

    def upsert(self, entry: RunIndexEntry) -> None:
        with self.store.locked("runs"):
            runs = [r for r in self.load() if r.run_id != entry.run_id]
            runs.append(entry)
            self.save(runs)

    def update(self, run_id: str, **changes: Any) -> RunIndexEntry:
        with self.store.locked("runs"):
            runs = self.load()
            for i, r in enumerate(runs):
                if r.run_id == run_id:
                    runs[i] = r.model_copy(update=changes)
                    self.save(runs)
                    return runs[i]
        raise NotFound(f"실행 {run_id} 이 없습니다")

    @contextmanager
    def locked(self) -> Iterator[None]:
        with self.store.locked("runs"):
            yield


# ───────────────────────── 모의투자 · 비교 ─────────────────────────
class PaperStore:
    def __init__(self, store: JsonStore) -> None:
        self.store = store

    def rel(self, paper_id: str, name: str = "portfolio.json") -> str:
        return f"paper/{paper_id}/{name}"

    def load(self, paper_id: str) -> dict[str, Any]:
        raw = self.store.read(self.rel(paper_id))
        if raw is None:
            raise NotFound(f"모의투자 {paper_id} 이 없습니다")
        return raw

    def save(self, doc: dict[str, Any]) -> Path:
        return self.store.write(self.rel(doc["paper_id"]), doc, schema="paper_portfolio")

    def list(self) -> list[dict[str, Any]]:
        d = self.store.path("paper")
        if not d.exists():
            return []
        return [load_json(p) for p in sorted(d.glob("paper_*/portfolio.json"))]

    def append_snapshot(self, paper_id: str, snap: dict[str, Any]) -> None:
        self.store.append_jsonl(self.rel(paper_id, "snapshots.jsonl"), snap)

    def snapshots(self, paper_id: str) -> list[dict[str, Any]]:
        return self.store.read_jsonl(self.rel(paper_id, "snapshots.jsonl"))

    def append_rebalance(self, paper_id: str, rec: dict[str, Any]) -> None:
        self.store.append_jsonl(self.rel(paper_id, "rebalances.jsonl"), rec)

    def rebalances(self, paper_id: str) -> list[dict[str, Any]]:
        return self.store.read_jsonl(self.rel(paper_id, "rebalances.jsonl"))


class ComparisonStore:
    def __init__(self, store: JsonStore) -> None:
        self.store = store

    def rel(self, comparison_id: str) -> str:
        return f"comparisons/{comparison_id}.json"

    def load(self, comparison_id: str) -> dict[str, Any]:
        raw = self.store.read(self.rel(comparison_id))
        if raw is None:
            raise NotFound(f"비교 {comparison_id} 이 없습니다")
        return raw

    def save(self, doc: dict[str, Any]) -> Path:
        return self.store.write(self.rel(doc["comparison_id"]), doc)
