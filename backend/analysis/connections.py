"""연결 설정 (팀 DB 접속 주소 · OpenAI API 키): 지금 상태, 확인하고 저장, 지우기. 프런트 제안 계약의 getConnections·saveConnection·clearConnection.

값을 찾는 순서 (개발 · Docker Compose · 실행 파일을 한 코드로 받는다):
  1. 환경변수 — `.env`, Compose 가 넣어 준 값. 앱은 읽기만 하고, 화면에서는 「환경변수로 설정됨」으로 보여 주며 바꾸지 못한다.
  2. 운영체제 보관함 (secret_store) — 화면에서 저장한 값. 실행 파일로 쓰는 사람의 길.
  3. 없음 — 연습 모드.

- 앱은 `.env` 를 고치지 않고, 어떤 파일에도 비밀 값을 쓰지 않는다.
- 저장한 값은 다시 돌려주지 않는다 — 응답에는 가린 표시만 싣는다 (비밀번호·키 본문은 오류 문장에도 넣지 않는다).
- 실제로 접속해 보고 될 때만 저장한다. 안 되면 원인 코드를 돌려준다 (문구는 화면이 고른다: Front/src/features/connect/copy.ts).
- 보관함에서 꺼낸 값은 이 프로세스의 환경변수에 올려 쓴다 (나머지 코드는 지금처럼 환경변수에서 읽는다).
  API 는 저장 직후 Services.reload_connections() 로 다시 읽고, 따로 도는 분석 일꾼은 StoreWatcher 로 변경 표시 파일을 보고 다음 실행 전에 다시 읽는다.
"""

from __future__ import annotations

import datetime as dt
import json
import logging
import os
import re
import statistics
from pathlib import Path
from typing import Any, Literal
from urllib.parse import unquote, urlsplit

from backend.adapters.crawlers import config
from backend.analysis import secret_store
from backend.analysis.paths import output_root

log = logging.getLogger(__name__)

Kind = Literal["database", "llm"]
KEYS: dict[str, str] = {"database": "DATABASE_URL", "llm": "OPENAI_API_KEY"}
LLM_MODE_KEY = "MYFINSIGHT_LLM"
STAMP = "connections.stamp"  # 저장소 폴더의 변경 표시 파일 (바뀐 시각만 적는다, 비밀 값 없음)

MASK = "••••••••"
DEFAULT_COST_PER_RUN_USD = 0.1  # 실행 기록이 모자랄 때의 사용료 어림 (2026-11-03 시나리오 96건의 중앙값 0.09 를 어림, 2026-11-23 합의)
MIN_RUNS_FOR_COST = 5  # 이만큼 기록이 쌓인 뒤에 실제 값으로 바꾼다 (한두 건으로는 0.02~0.46달러로 크게 흔들린다)
COST_SAMPLE = 100  # 최근 이만큼의 실행만 본다
CONNECT_TIMEOUT_S = 8

_from_store: set[str] = set()  # 이 프로세스에서 보관함에서 꺼내 환경변수에 올린 키 (환경변수로 직접 들어온 것과 구분한다)


class Refused(Exception):
    """화면에서 바꿀 수 없는 상황 (환경변수로 설정됨 · 보관함 없음). 라우터가 409 로 답한다."""

    def __init__(self, code: str, message_ko: str) -> None:
        super().__init__(message_ko)
        self.code, self.message_ko = code, message_ko


# ───────────────────────── 값의 출처 ─────────────────────────
def _env_provides(kind: str) -> bool:
    """환경변수(.env · Compose)가 이 연결을 주고 있나. 팀 DB 는 예전 방식 키(NEWS_DB_*)로 만들어지는 주소도 환경변수로 본다."""
    key = KEYS[kind]
    if key in _from_store:
        return False
    if kind == "database":
        from backend.analysis.common.dbconn import database_url

        return bool(database_url())
    return bool(config.get(key))


def source(kind: str) -> str | None:
    """env = 환경변수로 들어옴 (화면에서 못 바꾼다) · saved = 화면에서 저장해 보관함에 있음 · None = 없음."""
    if KEYS[kind] in _from_store:
        return "saved"
    return "env" if _env_provides(kind) else None


EXAMPLE_KEYS = ("sk-...", "sk-…")  # .env.example 의 OPENAI_API_KEY 자리 글자
EXAMPLE_DB_SIGNS = ("your-endpoint", "PASSWORD@")  # .env.example 의 DB 주소 예시에 든 글자


def drop_examples() -> bool:
    """`.env.example` 을 그대로 복사해 둔 값(예시 글자)은 「넣지 않은 것」으로 본다: 이 프로세스의 환경변수에서 뺀다 (파일은 그대로). 뺀 것이 있으면 True.

    안 그러면 예시 값이 「환경변수로 설정된 연결」이 되어 화면에서 고칠 수 없고, 서버는 없는 주소·가짜 키로 접속하려 한다
    (2026-11-23: 예시 파일을 복사해 켰더니 팀 DB 가 your-endpoint… 주소로 「연결됨」이라고 나왔다)."""
    config.get(KEYS["llm"])  # .env 를 아직 읽지 않았으면 먼저 읽는다
    dropped: list[str] = []
    if os.environ.get(KEYS["llm"], "").strip() in EXAMPLE_KEYS:
        dropped.append(KEYS["llm"])
    for key in (KEYS["database"], "NEWS_DB_URL"):
        if any(sign in os.environ.get(key, "") for sign in EXAMPLE_DB_SIGNS):
            dropped.append(key)
    host = os.environ.get("NEWS_DB_HOST", "")
    if host and (host.startswith("your-endpoint") or os.environ.get("NEWS_DB_PASSWORD", "").strip() == "change-me"):
        dropped.append("NEWS_DB_HOST")  # HOST 만 빼도 예전 방식 조합(HOST+USER+PASSWORD)이 성립하지 않는다
    for key in dropped:
        os.environ.pop(key, None)
    if dropped:
        log.info("[connections] .env 의 예시 값은 쓰지 않음: %s", ", ".join(dropped))
    return bool(dropped)


def load_stored() -> bool:
    """보관함의 값을 환경변수에 올린다 — 환경변수가 이미 주는 연결은 건드리지 않는다 (환경변수가 이긴다). 달라진 것이 있으면 True.
    프로세스를 켤 때와, 다른 프로세스가 값을 바꿨을 때(StoreWatcher) 부른다. 켤 때 `.env.example` 의 예시 값도 걸러 낸다."""
    changed = drop_examples()
    for kind, key in KEYS.items():
        if _env_provides(kind):
            continue
        before = os.environ.get(key) if key in _from_store else None
        value = secret_store.get(key)
        if value:
            os.environ[key] = value
            _from_store.add(key)
        elif key in _from_store:
            os.environ.pop(key, None)
            _from_store.discard(key)
        changed = changed or value != before
    return changed


def llm_mode() -> str:
    """AnalysisSettings.load 와 같은 규칙: MYFINSIGHT_LLM 을 적었으면 그 값, 아니면 키가 있을 때 api, 없으면 stub(연습)."""
    mode = config.get(LLM_MODE_KEY)
    if mode in ("stub", "api"):
        return mode
    return "api" if config.get(KEYS["llm"]) else "stub"


# ───────────────────────── 다른 프로세스에 알리기 ─────────────────────────
def touch_stamp(store: Any) -> None:
    """연결을 바꿨다고 표시한다. 따로 도는 분석 일꾼이 이 파일의 수정 시각을 본다."""
    try:
        Path(store.path(STAMP)).write_text(dt.datetime.now(dt.UTC).isoformat(), encoding="utf-8")
    except OSError:
        log.warning("[connections] stamp not written", exc_info=True)


class StoreWatcher:
    """분석 일꾼용: 서버가 연결을 바꾼 것을 변경 표시 파일로 알아채고 보관함을 다시 읽는다."""

    def __init__(self, store: Any) -> None:
        self.path = Path(store.path(STAMP))
        self._stamp = self._mtime()

    def _mtime(self) -> float | None:
        try:
            return self.path.stat().st_mtime
        except OSError:
            return None

    def changed(self) -> bool:
        """지난번 본 뒤로 연결이 바뀌었으면 환경변수에 반영하고 True."""
        stamp = self._mtime()
        if stamp == self._stamp:
            return False
        self._stamp = stamp
        return load_stored()


# ───────────────────────── 가린 표시 ─────────────────────────
def mask_database(url: str) -> str:
    """접속 주소에서 비밀번호를 가리고 접속 옵션(?sslmode=…)은 뺀다. SQLite 는 파일 경로 그대로."""
    text = url.strip()
    if text.startswith("sqlite"):
        return text
    try:
        u = urlsplit(text)
        host = u.hostname or ""
        if not host:
            return MASK
        auth = f"{unquote(u.username)}:{MASK}@" if u.username else ""
        port = f":{u.port}" if u.port else ""
        return f"{u.scheme.split('+', 1)[0]}://{auth}{host}{port}{u.path}"
    except ValueError:
        return MASK


def mask_key(key: str) -> str:
    """끝 4자리만 남긴다."""
    key = key.strip()
    return f"sk-••••••••••••{key[-4:]}" if len(key) >= 8 else MASK


def _scrub(text: str, *secrets: str) -> str:
    """오류 문장에서 비밀 값과 키처럼 보이는 것을 지운다."""
    for s in secrets:
        if s:
            text = text.replace(s, MASK)
    return re.sub(r"sk-[A-Za-z0-9_\-*]{4,}", "sk-" + MASK, text)


def _raw(exc: BaseException, *secrets: str) -> str:
    """「자세한 오류 보기」에 실을 한 줄: 가장 안쪽 원인의 종류와 첫 줄."""
    while exc.__cause__ is not None:
        exc = exc.__cause__
    line = (str(exc).strip().splitlines() or [""])[0]
    return _scrub(f"{type(exc).__name__}: {line}", *secrets)[:300]


def _error(code: str, value: str | None, raw: str | None) -> dict[str, Any]:
    return {"ok": False, "error": {"code": code, "value": value, "raw": raw}}


# ───────────────────────── 확인 ─────────────────────────
_HOST_SIGNS = ("could not translate host name", "name or service not known", "getaddrinfo failed", "failed to resolve host", "nodename nor servname", "temporary failure in name resolution", "no address associated")  # fmt: skip
_AUTH_SIGNS = ("password authentication failed", "no password supplied", "no pg_hba.conf entry")
_SILENT_SIGNS = ("connection refused", "timeout expired", "timed out", "connection timeout", "could not connect to server", "network is unreachable", "no route to host", "server closed the connection", "connection reset")  # fmt: skip


def classify_db_error(text: str) -> str:
    """DB 드라이버의 오류 문장 → 원인 코드. 주소 → 계정 → DB 이름 → 응답 없음 순으로 본다 (계정 오류 문장에도 database 가 나오므로 계정을 먼저)."""
    low = text.lower()

    def has(*signs: str) -> bool:
        return any(s in low for s in signs)

    missing = "does not exist" in low
    if has(*_HOST_SIGNS):
        return "host_not_found"
    if has(*_AUTH_SIGNS) or ('role "' in low and missing):
        return "auth_failed"
    if ('database "' in low and missing) or has("unable to open database file"):
        return "database_not_found"
    if has(*_SILENT_SIGNS):
        return "no_response"
    return "unknown"


def _parts(url: str) -> tuple[str | None, int | None, str | None, str | None]:
    try:
        u = urlsplit(url.strip())
        return u.hostname, u.port, unquote(u.path.lstrip("/")) or None, unquote(u.password) if u.password else None
    except ValueError:
        return None, None, None, None


def _with_timeout(url: str) -> str:
    """확인할 때만: 닿지 않는 서버에서 몇 분씩 멈추지 않게 접속 제한 시간을 붙인다 (주소에 이미 적혀 있으면 그대로)."""
    if url.startswith("sqlite") or "connect_timeout=" in url:
        return url
    return f"{url}{'&' if '?' in url else '?'}connect_timeout={CONNECT_TIMEOUT_S}"


def _coverage(md: Any) -> dict[str, Any]:
    """자료가 있는 구간. data_start 는 모든 시장이 자료를 가진 첫날(가장 늦게 시작한 시장), data_start_by_market 은 시장별 첫날."""
    starts = md.data_starts()
    return {"latest_trading_day": str(md.ceiling), "data_start": str(max(starts.values())), "data_start_by_market": {m: str(d) for m, d in starts.items()}}


def check_database(url: str, settings: Any) -> dict[str, Any]:
    """접속해서 시장 자료의 범위를 읽어 본다. 되면 {"ok": True, latest_trading_day, data_start, data_start_by_market}."""
    from backend.analysis.m2_data.market_data import MarketData
    from backend.db import open_repository

    url = url.strip()
    host, port, name, password = _parts(url)
    if url.startswith("sqlite:///") and not Path(url[len("sqlite:///") :]).exists():  # 없는 파일을 새로 만들지 않는다
        return _error("database_not_found", url[len("sqlite:///") :], "FileNotFoundError: SQLite 파일이 없습니다")
    repo = None
    try:
        repo = open_repository(_with_timeout(url))
        md = MarketData(repo, settings)
        return {"ok": True, **_coverage(md)}
    except Exception as exc:  # noqa: BLE001 — 어떤 실패든 원인 코드로 바꿔 돌려준다
        chain, e = [], exc
        while e is not None:
            chain.append(str(e))
            e = e.__cause__
        code = classify_db_error(" | ".join(chain))
        value = {"host_not_found": host, "no_response": f"{host}:{port or 5432}" if host else None, "database_not_found": name}.get(code)
        log.info("[connections] database check failed: %s", code)
        return _error(code, value, _raw(exc, password or ""))
    finally:
        engine = getattr(repo, "engine", None)
        if engine is not None:
            engine.dispose()


def check_llm(key: str, settings: Any) -> dict[str, Any]:
    """키로 OpenAI 에 한 번 물어본다 (모델 목록 — 사용료가 들지 않는다)."""
    import openai

    try:
        openai.OpenAI(api_key=key, timeout=15, max_retries=0).models.list()
        return {"ok": True}
    except (openai.AuthenticationError, openai.PermissionDeniedError) as exc:
        return _error("invalid_key", None, _raw(exc, key))
    except openai.RateLimitError as exc:
        return _error("quota", None, _raw(exc, key))
    except Exception as exc:  # noqa: BLE001
        return _error("unknown", None, _raw(exc, key))


# ───────────────────────── 상태 · 저장 · 지우기 ─────────────────────────
def cost_per_run_usd() -> float:
    """분석 한 번의 사용료 어림 (USD). 실행 기록(run_meta.json 의 llm_usage.cost_usd)이 충분히 쌓였으면 그 중앙값, 아니면 기본값."""
    try:
        metas = sorted(output_root().glob("*/run_meta.json"), key=lambda p: p.stat().st_mtime, reverse=True)[:COST_SAMPLE]
    except OSError:
        return DEFAULT_COST_PER_RUN_USD
    costs: list[float] = []
    for p in metas:
        try:
            cost = (json.loads(p.read_text(encoding="utf-8")).get("llm_usage") or {}).get("cost_usd")
        except (OSError, ValueError):
            continue
        if isinstance(cost, int | float) and cost > 0:  # 연습 모드 실행(비용 0)은 뺀다
            costs.append(float(cost))
    if len(costs) < MIN_RUNS_FOR_COST:
        return DEFAULT_COST_PER_RUN_USD
    return round(statistics.median(costs), 4)


def status(services: Any, *, reveal: bool = True) -> dict[str, Any]:
    """지금 연결 상태. 팀 DB 는 주소가 있고 실제로 자료를 읽을 수 있어야 연결됨이다 — 주소만 있고 닿지 않으면 연결 전 + 원인(error).
    분석 모델은 키가 있고 연습 모드가 아니어야 연결됨이다 — 환경변수가 연습 모드로 못 박아 두었으면 stub_pinned.
    reveal=False (이 컴퓨터가 아닌 곳에서 물었을 때): 가린 값과 오류의 주소도 싣지 않는다 (DB 서버 이름·키 끝자리를 밖에 보이지 않게)."""
    from backend.analysis.common.dbconn import database_url

    url = database_url()
    covered: dict[str, Any] = {"latest_trading_day": None, "data_start": None, "data_start_by_market": None}
    error = None
    if url:
        try:
            covered = _coverage(services.market_data())
        except Exception as exc:  # noqa: BLE001 — 닿지 않는 이유를 화면에 알린다 (환경변수로 들어온 주소는 화면에서 고칠 수 없으니 더 필요하다)
            host, port, name, password = _parts(url)
            chain, e = [], exc
            while e is not None:
                chain.append(str(e))
                e = e.__cause__
            code = classify_db_error(" | ".join(chain))
            value = {"host_not_found": host, "no_response": f"{host}:{port or 5432}" if host else None, "database_not_found": name}.get(code)
            error = {"code": code, "value": value if reveal else None, "raw": _raw(exc, password or "") if reveal else None}
    key = config.get(KEYS["llm"])
    return {
        "can_save": secret_store.available(),  # 화면에서 저장할 수 있나 (운영체제 보관함을 쓸 수 있나)
        "store_label_ko": secret_store.label(),
        "database": {"kind": "database", "connected": bool(url) and error is None, "source": source("database"), "masked": mask_database(url) if url and reveal else None, **covered, "error": error},
        "llm": {"kind": "llm", "connected": bool(key) and services.settings.llm.mode == "api", "source": source("llm"), "masked": mask_key(key) if key and reveal else None, "cost_per_run_usd": cost_per_run_usd(), "stub_pinned": config.get(LLM_MODE_KEY) == "stub"},
    }  # fmt: skip


def _editable(kind: str) -> None:
    if source(kind) == "env":
        raise Refused("CONNECTION_FROM_ENV", "환경변수(.env)로 설정된 연결은 화면에서 바꿀 수 없습니다. 그 파일에서 고쳐 주세요.")
    if not secret_store.available():
        raise Refused("SECRET_STORE_UNAVAILABLE", "이 환경에서는 화면에서 저장할 수 없습니다. 환경변수(.env)로 넣어 주세요.")


def save(services: Any, kind: Kind, value: str) -> dict[str, Any]:
    """확인하고, 되면 운영체제 보관함에 넣고 이 프로세스에 바로 반영한다. 안 되면 아무것도 바꾸지 않는다."""
    _editable(kind)
    value = value.strip()
    if kind == "llm" and config.get(LLM_MODE_KEY) == "stub":  # 환경변수가 연습 모드를 못 박아 두면 키를 넣어도 쓰이지 않는다 → 저장하지 않고 알린다
        return {"ok": False, "connections": status(services), "error": {"code": "stub_pinned", "value": None, "raw": f"{LLM_MODE_KEY}=stub"}}
    checked = check_database(value, services.settings) if kind == "database" else check_llm(value, services.settings.llm)
    if not checked.get("ok"):
        return {"ok": False, "connections": status(services), "error": checked["error"]}
    key = KEYS[kind]
    try:
        secret_store.put(key, value)
    except secret_store.SecretStoreError as exc:
        raise Refused("SECRET_STORE_FAILED", str(exc)) from exc
    os.environ[key] = value
    _from_store.add(key)
    touch_stamp(services.store)
    services.reload_connections()
    log.info("[connections] %s saved", kind)
    return {"ok": True, "connections": status(services), "error": None}


def clear(services: Any, kind: Kind) -> dict[str, Any]:
    """보관함과 이 프로세스에서 값을 지운다."""
    _editable(kind)
    key = KEYS[kind]
    secret_store.delete(key)
    os.environ.pop(key, None)
    _from_store.discard(key)
    touch_stamp(services.store)
    services.reload_connections()
    log.info("[connections] %s cleared", kind)
    return status(services)
