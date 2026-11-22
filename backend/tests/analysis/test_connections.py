"""연결 설정 (팀 DB 주소 · 분석 모델 키): 값의 출처(환경변수는 읽기만 · 화면 저장은 운영체제 보관함), 가린 표시, 오류 분류,
API (조회·확인 후 저장·지우기), 켤 때 보관함에서 읽기, 일꾼이 바뀐 값을 알아채는 것."""

from __future__ import annotations

import datetime as dt
import json
import os

import keyring
import pytest
from fastapi.testclient import TestClient
from keyring.backend import KeyringBackend
from keyring.errors import PasswordDeleteError

from backend.analysis import connections as C
from backend.analysis import secret_store
from backend.analysis.api.app import API_PREFIX, create_analysis_app
from backend.analysis.common.llm import StubLlm
from backend.analysis.common.store import JsonStore
from backend.analysis.settings import AnalysisSettings, replace_settings
from backend.db import open_repository
from backend.tests.analysis.conftest import seed_repository

P = API_PREFIX
GOOD_KEY = "sk-example-0000000000000000a3F9"
TEAM_URL = "postgresql://reader:example-pw@db.example.com:5432/myfinsight?sslmode=require"
ENV_TEXT = "# 내 개발용 설정\nDART_API_KEY=abc\nMYFINSIGHT_LLM_CACHE=0\n"


class MemoryKeyring(KeyringBackend):
    """테스트용 가짜 보관함 (실제 자격 증명 관리자·키체인을 건드리지 않는다)."""

    priority = 1  # type: ignore[assignment]

    def __init__(self) -> None:
        super().__init__()
        self.data: dict[tuple[str, str], str] = {}

    def get_password(self, service: str, username: str) -> str | None:
        return self.data.get((service, username))

    def set_password(self, service: str, username: str, password: str) -> None:
        self.data[(service, username)] = password

    def delete_password(self, service: str, username: str) -> None:
        if (service, username) not in self.data:
            raise PasswordDeleteError("not found")
        del self.data[(service, username)]

    def values(self) -> dict[str, str]:
        return {name: v for (service, name), v in self.data.items() if service == secret_store.SERVICE}


@pytest.fixture
def env_file(tmp_path, monkeypatch):
    """내 PC 의 실제 설정이 테스트에 섞이지 않게: 연결 키(예전 방식 NEWS_DB_* 포함)를 비우고, 끝나면 원래대로 돌린다.
    설정 파일은 테스트용으로 하나 두고, 앱이 그것을 고치지 않는지 본다."""
    p = tmp_path / ".env"
    p.write_text(ENV_TEXT, encoding="utf-8")
    monkeypatch.setenv("MYFINSIGHT_ENV_FILE", str(p))
    monkeypatch.setenv("ANALYSIS_OUTPUT_DIR", str(tmp_path / "out"))
    for k in (*C.KEYS.values(), C.LLM_MODE_KEY, "NEWS_DB_URL", "NEWS_DB_HOST", "NEWS_DB_USER", "NEWS_DB_PASSWORD", "ANALYSIS_RESULTS_DB"):
        monkeypatch.setenv(k, "")
        monkeypatch.delenv(k)
    C._from_store.clear()
    yield p
    C._from_store.clear()
    assert p.read_text(encoding="utf-8") == ENV_TEXT  # 어떤 테스트에서도 앱은 .env 를 고치지 않는다


@pytest.fixture
def vault(env_file, monkeypatch):
    """가짜 보관함을 꽂는다 (실행 파일로 쓰는 사람의 환경)."""
    original = keyring.get_keyring()
    mem = MemoryKeyring()
    keyring.set_keyring(mem)
    monkeypatch.setenv("MYFINSIGHT_SECRET_STORE", "keyring")
    yield mem
    keyring.set_keyring(original)


@pytest.fixture
def api(env_file, descriptor_dir, tmp_path):
    """시장 자료가 든 SQLite 를 저장소로 꽂은 서버. 연습 모드(키 없음)에서 시작한다. 보관함은 vault 를 같이 쓸 때만 있다."""
    db = tmp_path / "market.db"
    repo = open_repository(f"sqlite:///{db}", clock=lambda: dt.datetime(2026, 1, 5, tzinfo=dt.UTC))
    seed_repository(repo)
    s = AnalysisSettings()
    s = replace_settings(s, market=replace_settings(s.market, valuation_max_staleness_days=10, descriptor_dir=str(descriptor_dir)))
    app = create_analysis_app(lambda: repo, store_dir=tmp_path / "store", settings=s, llm=lambda: StubLlm(), cors_origins=["http://localhost:5173"])
    return TestClient(app, raise_server_exceptions=False), db


def _health(client) -> dict:
    return client.get(f"{P}/health").json()


# ───────────────────────── 가린 표시 · 오류 분류 ─────────────────────────
def test_masks_hide_password_and_key_body():
    assert C.mask_database(TEAM_URL) == "postgresql://reader:••••••••@db.example.com:5432/myfinsight"
    assert C.mask_database("postgresql+psycopg://reader:pw@10.0.0.7/market") == "postgresql://reader:••••••••@10.0.0.7/market"
    assert C.mask_database("sqlite:///data/myfinsight.db") == "sqlite:///data/myfinsight.db"
    assert C.mask_key(GOOD_KEY) == "sk-••••••••••••a3F9"
    assert "example-pw" not in C.mask_database(TEAM_URL) and "0000" not in C.mask_key(GOOD_KEY)


@pytest.mark.parametrize(
    ("text", "code"),
    [
        ('could not translate host name "db.exampel.com" to address: Name or service not known', "host_not_found"),
        ("[Errno 11001] getaddrinfo failed", "host_not_found"),
        ('connection to server at "db.example.com", port 5432 failed: FATAL:  password authentication failed for user "reader"', "auth_failed"),
        ('FATAL:  role "nobody" does not exist', "auth_failed"),
        ('connection failed: FATAL:  database "nope" does not exist', "database_not_found"),
        ('connection to server at "10.0.0.7", port 5432 failed: Connection refused', "no_response"),
        ("connection timeout expired", "no_response"),
        ("something else entirely", "unknown"),
    ],
)
def test_classify_db_error(text, code):
    assert C.classify_db_error(text) == code


def test_raw_error_line_never_carries_secrets():
    try:
        try:
            raise ValueError("connection failed for postgresql://reader:example-pw@db.example.com using key sk-example-0000000000000000a3F9\n둘째 줄")
        except ValueError as inner:
            raise RuntimeError("겉 오류") from inner
    except RuntimeError as exc:
        raw = C._raw(exc, "example-pw", GOOD_KEY)
    assert raw.startswith("ValueError: connection failed") and "둘째 줄" not in raw  # 가장 안쪽 원인의 첫 줄
    assert "example-pw" not in raw and "0000000000000000" not in raw


# ───────────────────────── 화면에서 저장 → 운영체제 보관함 ─────────────────────────
def test_status_before_anything_is_saved(api, vault):
    client, _ = api
    r = client.get(f"{P}/connections")
    assert r.status_code == 200
    assert r.json() == {
        "can_save": True, "store_label_ko": "시스템 키링",
        "database": {"kind": "database", "connected": False, "source": None, "masked": None, "latest_trading_day": None, "data_start": None, "data_start_by_market": None, "error": None},
        "llm": {"kind": "llm", "connected": False, "source": None, "masked": None, "cost_per_run_usd": 0.1, "stub_pinned": False},  # 실행 기록이 없으면 기본값
    }  # fmt: skip
    assert _health(client)["llm_mode"] == "stub"


def test_save_llm_key_checks_first_then_goes_to_the_vault_not_to_env_file(api, vault, monkeypatch):
    client, _ = api
    seen: list[str] = []
    monkeypatch.setattr(C, "check_llm", lambda key, settings: (seen.append(key), C._error("invalid_key", None, "AuthenticationError: Incorrect API key provided"))[1])
    r = client.put(f"{P}/connections/llm", json={"value": "sk-wrong"}).json()
    assert r["ok"] is False and r["error"] == {"code": "invalid_key", "value": None, "raw": "AuthenticationError: Incorrect API key provided"}
    assert r["connections"]["llm"]["connected"] is False and vault.values() == {}  # 안 되면 아무것도 저장하지 않는다
    assert "OPENAI_API_KEY" not in os.environ and seen == ["sk-wrong"]

    monkeypatch.setattr(C, "check_llm", lambda key, settings: {"ok": True})
    r = client.put(f"{P}/connections/llm", json={"value": f"  {GOOD_KEY}\n"})  # 앞뒤 공백·줄바꿈은 떼고 저장
    body = r.json()
    assert r.status_code == 200 and body["ok"] is True and body["error"] is None
    assert body["connections"]["llm"] == {"kind": "llm", "connected": True, "source": "saved", "masked": "sk-••••••••••••a3F9", "cost_per_run_usd": 0.1, "stub_pinned": False}
    assert GOOD_KEY not in r.text  # 저장한 값은 응답에 다시 싣지 않는다
    assert vault.values() == {"OPENAI_API_KEY": GOOD_KEY} and os.environ["OPENAI_API_KEY"] == GOOD_KEY
    assert _health(client)["llm_mode"] == "api"  # 서버를 다시 켜지 않아도 연습 모드가 풀린다
    assert GOOD_KEY not in client.get(f"{P}/connections").text
    # .env 를 고치지 않았다는 것은 env_file 고정물이 끝날 때 확인한다


def test_clear_removes_value_from_vault_and_returns_to_practice_mode(api, vault, monkeypatch):
    client, _ = api
    monkeypatch.setattr(C, "check_llm", lambda key, settings: {"ok": True})
    client.put(f"{P}/connections/llm", json={"value": GOOD_KEY})
    r = client.delete(f"{P}/connections/llm")
    assert r.status_code == 200 and r.json()["llm"] == {"kind": "llm", "connected": False, "source": None, "masked": None, "cost_per_run_usd": 0.1, "stub_pinned": False}
    assert vault.values() == {} and "OPENAI_API_KEY" not in os.environ and _health(client)["llm_mode"] == "stub"
    assert client.delete(f"{P}/connections/llm").status_code == 200  # 없는 것을 지워도 문제없다


def test_save_database_really_connects_and_reads_data_range(api, vault):
    """실제로 열어 본다: 시장 자료가 든 SQLite 파일은 되고, 없는 파일은 안 된다 (새로 만들지도 않는다)."""
    client, db = api
    missing = db.with_name("nope.db")
    r = client.put(f"{P}/connections/database", json={"value": f"sqlite:///{missing}"}).json()
    assert r["ok"] is False and r["error"]["code"] == "database_not_found" and r["error"]["value"] == str(missing)
    assert not missing.exists() and vault.values() == {}

    url = f"sqlite:///{db}"
    body = client.put(f"{P}/connections/database", json={"value": url}).json()
    assert body["ok"] is True
    got = body["connections"]["database"]
    assert got == {"kind": "database", "connected": True, "source": "saved", "masked": url, "latest_trading_day": "2025-12-31", "data_start": got["data_start"], "data_start_by_market": got["data_start_by_market"], "error": None}
    assert got["data_start"] < "2025-12-31"
    by_market = got["data_start_by_market"]  # 시장마다 따로, 합친 시작일은 그중 가장 늦은 날
    assert list(by_market) == ["US", "KR"] and got["data_start"] == max(by_market.values())
    assert vault.values() == {"DATABASE_URL": url} and os.environ["DATABASE_URL"] == url

    r = client.delete(f"{P}/connections/database").json()
    assert r["database"]["connected"] is False and "DATABASE_URL" not in os.environ and vault.values() == {}


def test_unreachable_address_fails_after_one_try_without_the_repository_retries(env_file, monkeypatch):
    """닿지 않는 주소는 한 번 두드려 보고 바로 알린다. 저장소의 "5·20·60초 쉬고 다시"까지 가면 화면이 2분 동안 「확인 중」에 머문다."""
    from backend.db import sql

    def no_waiting(seconds):
        raise AssertionError(f"저장소의 재시도 대기({seconds}초)까지 갔다 — 닿는지 먼저 봤어야 한다")

    monkeypatch.setattr(sql, "_sleep", no_waiting)
    r = C.check_database("postgresql://reader:pw@127.0.0.1:1/myfinsight?connect_timeout=2", AnalysisSettings())
    assert r["ok"] is False and r["error"]["code"] == "no_response" and r["error"]["value"] == "127.0.0.1:1"
    assert "pw" not in (r["error"]["raw"] or "")


def test_database_failure_reports_cause_and_part_without_password(api, vault, monkeypatch):
    client, _ = api

    def boom(url):
        raise RuntimeError('connection failed: could not translate host name "db.exampel.com" to address (password=example-pw)')

    monkeypatch.setattr("backend.analysis.common.dbconn.knock", boom)  # 처음 닿는 곳에서 실패하게 한다 (테스트가 실제로 그 이름을 찾으러 나가지 않게)
    r = client.put(f"{P}/connections/database", json={"value": TEAM_URL.replace("example.com", "exampel.com")})
    body = r.json()
    assert body["ok"] is False and body["error"]["code"] == "host_not_found" and body["error"]["value"] == "db.exampel.com"
    assert "could not translate host name" in body["error"]["raw"] and "example-pw" not in r.text
    assert vault.values() == {}


# ───────────────────────── 환경변수(.env · Compose)로 들어온 연결은 읽기만 ─────────────────────────
def test_connection_given_by_environment_is_shown_but_cannot_be_changed(api, vault, monkeypatch):
    """개발 PC 의 .env, Docker Compose 가 넣어 준 값: 연결된 것으로 보여 주되 화면에서 바꾸거나 지울 수 없다."""
    client, _ = api
    monkeypatch.setattr(C, "check_llm", lambda key, settings: {"ok": True})
    monkeypatch.setenv("OPENAI_API_KEY", GOOD_KEY)
    monkeypatch.setenv("DATABASE_URL", TEAM_URL)
    client.app.state.services.reload_connections()  # 서버가 이 환경변수로 켜진 상태
    got = client.get(f"{P}/connections").json()
    assert got["llm"]["source"] == "env" and got["llm"]["connected"] is True and got["llm"]["masked"] == "sk-••••••••••••a3F9"
    assert got["database"]["source"] == "env" and got["database"]["masked"] == "postgresql://reader:••••••••@db.example.com:5432/myfinsight"

    for call in (lambda: client.put(f"{P}/connections/llm", json={"value": "sk-other-0000000000000000zzzz"}), lambda: client.delete(f"{P}/connections/llm"), lambda: client.delete(f"{P}/connections/database")):
        r = call()
        assert r.status_code == 409 and r.json()["error"]["code"] == "CONNECTION_FROM_ENV"
    assert os.environ["OPENAI_API_KEY"] == GOOD_KEY and os.environ["DATABASE_URL"] == TEAM_URL and vault.values() == {}


def test_legacy_database_keys_count_as_given_by_environment(api, vault, monkeypatch):
    """DATABASE_URL 이 없으면 예전 방식 키(NEWS_DB_*)로도 주소가 만들어진다 → 그것도 환경변수로 들어온 연결이다."""
    client, _ = api
    for k, v in {"NEWS_DB_HOST": "db.example.com", "NEWS_DB_USER": "reader", "NEWS_DB_PASSWORD": "example-pw", "NEWS_DB_NAME": "myfinsight"}.items():
        monkeypatch.setenv(k, v)
    r = client.get(f"{P}/connections")
    assert r.json()["database"]["source"] == "env" and r.json()["database"]["masked"] == "postgresql://reader:••••••••@db.example.com:5432/myfinsight"
    assert "example-pw" not in r.text
    assert client.delete(f"{P}/connections/database").status_code == 409 and os.environ["NEWS_DB_HOST"] == "db.example.com"


def test_environment_wins_over_a_value_left_in_the_vault(api, vault, monkeypatch):
    vault.set_password(secret_store.SERVICE, "OPENAI_API_KEY", "sk-stored-0000000000000000zzzz")
    monkeypatch.setenv("OPENAI_API_KEY", GOOD_KEY)
    assert C.load_stored() is False and os.environ["OPENAI_API_KEY"] == GOOD_KEY and C.source("llm") == "env"


def test_stub_mode_pinned_by_environment_is_reported_instead_of_saving(api, vault, monkeypatch):
    client, _ = api
    monkeypatch.setattr(C, "check_llm", lambda key, settings: {"ok": True})
    monkeypatch.setenv("MYFINSIGHT_LLM", "stub")  # 개발용 .env 예시에 있는 줄
    body = client.put(f"{P}/connections/llm", json={"value": GOOD_KEY}).json()
    assert body["ok"] is False and body["error"] == {"code": "stub_pinned", "value": None, "raw": "MYFINSIGHT_LLM=stub"}
    assert vault.values() == {} and "OPENAI_API_KEY" not in os.environ and _health(client)["llm_mode"] == "stub"


# ───────────────────────── 보관함을 쓸 수 없는 곳 (Docker 등) ─────────────────────────
def test_without_a_vault_nothing_can_be_saved_from_the_screen(api, monkeypatch):
    """Docker 컨테이너처럼 운영체제 보관함이 없는 곳: 화면에서 저장할 수 없다고 알리고, 값은 환경변수로만 받는다."""
    client, _ = api  # 보관함 없음 (공통 고정물이 MYFINSIGHT_SECRET_STORE=none 으로 둔다)
    got = client.get(f"{P}/connections").json()
    assert got["can_save"] is False and got["store_label_ko"] is None and got["llm"]["source"] is None
    r = client.put(f"{P}/connections/llm", json={"value": GOOD_KEY})
    assert r.status_code == 409 and r.json()["error"]["code"] == "SECRET_STORE_UNAVAILABLE" and "OPENAI_API_KEY" not in os.environ

    monkeypatch.setenv("OPENAI_API_KEY", GOOD_KEY)  # Compose 가 넣어 준 값
    client.app.state.services.reload_connections()
    got = client.get(f"{P}/connections").json()
    assert got["llm"] == {"kind": "llm", "connected": True, "source": "env", "masked": "sk-••••••••••••a3F9", "cost_per_run_usd": 0.1, "stub_pinned": False} and _health(client)["llm_mode"] == "api"


def test_other_computers_may_look_but_not_see_values_or_change_anything(api, vault, monkeypatch):
    """컨테이너 안에서는 모든 요청이 바깥 주소에서 온 것으로 보인다: 조회는 되지만 가린 값도 싣지 않고, 저장·지우기는 거절한다."""
    client, _ = api
    monkeypatch.setenv("OPENAI_API_KEY", GOOD_KEY)
    monkeypatch.setenv("DATABASE_URL", TEAM_URL)
    client.app.state.services.reload_connections()
    outside = TestClient(client.app, raise_server_exceptions=False, client=("203.0.113.9", 50000))
    r = outside.get(f"{P}/connections")
    assert r.status_code == 200 and r.json()["llm"]["connected"] is True and r.json()["llm"]["source"] == "env"
    assert r.json()["llm"]["masked"] is None and r.json()["database"]["masked"] is None and "db.example.com" not in r.text and "a3F9" not in r.text
    for call in (lambda: outside.put(f"{P}/connections/llm", json={"value": GOOD_KEY}), lambda: outside.delete(f"{P}/connections/llm")):
        r = call()
        assert r.status_code == 403 and r.json()["error"]["code"] == "FORBIDDEN"


def test_bad_requests(api, vault):
    client, _ = api
    assert client.put(f"{P}/connections/other", json={"value": "x"}).status_code == 422
    assert client.put(f"{P}/connections/llm", json={"value": ""}).status_code == 422
    assert client.put(f"{P}/connections/llm", json={}).status_code == 422


# ───────────────────────── 사용료 어림 ─────────────────────────
def test_cost_per_run_uses_default_until_enough_runs_then_median(env_file, tmp_path):
    out = tmp_path / "out"

    def run(name: str, cost: float | None) -> None:
        d = out / name
        d.mkdir(parents=True)
        (d / "run_meta.json").write_text(json.dumps({"llm_usage": {"cost_usd": cost}} if cost is not None else {}), encoding="utf-8")

    assert C.cost_per_run_usd() == 0.1  # 폴더조차 없음
    for i, cost in enumerate([0.02, 0.09, 0.46, 0.0]):  # 0 = 연습 모드 실행 → 세지 않는다
        run(f"r{i}", cost)
    run("broken", None)
    (out / "broken" / "run_meta.json").write_text("{깨진 파일", encoding="utf-8")
    assert C.cost_per_run_usd() == 0.1  # 쓸 수 있는 기록 3건 < 5건
    run("r5", 0.05)
    run("r6", 0.11)
    assert C.cost_per_run_usd() == 0.09  # 0.02 0.05 0.09 0.11 0.46 의 중앙값


# ───────────────────────── 켤 때 · 다른 프로세스 ─────────────────────────
def test_server_start_loads_what_was_saved_earlier(api, vault):
    """실행 파일을 다시 켰을 때: 보관함에 넣어 둔 키로 바로 연결된 상태가 된다."""
    client, _ = api
    vault.set_password(secret_store.SERVICE, "OPENAI_API_KEY", GOOD_KEY)
    assert _health(client)["llm_mode"] == "stub"  # 아직 켜는 절차(lifespan)를 거치지 않았다
    with client:  # 서버가 켜진다
        assert _health(client)["llm_mode"] == "api"
        got = client.get(f"{P}/connections").json()["llm"]
        assert got["connected"] is True and got["source"] == "saved" and got["masked"] == "sk-••••••••••••a3F9"


def test_worker_notices_what_the_server_changed(env_file, vault, tmp_path):
    """분석 일꾼은 따로 도는 프로세스다: 서버가 저장·지우기를 하면 변경 표시 파일을 보고 보관함을 다시 읽는다."""
    store = JsonStore(tmp_path / "store")
    w = C.StoreWatcher(store)
    assert w.changed() is False

    vault.set_password(secret_store.SERVICE, "OPENAI_API_KEY", GOOD_KEY)  # 서버 프로세스가 저장했다
    assert w.changed() is False  # 표시가 없으면 보관함을 읽지 않는다 (실행 사이마다 보관함을 두드리지 않는다)
    C.touch_stamp(store)
    os.utime(store.path(C.STAMP), (1_900_000_000, 1_900_000_000))  # 수정 시각이 달라졌다고 확실히 알린다
    assert w.changed() is True and os.environ["OPENAI_API_KEY"] == GOOD_KEY and C.llm_mode() == "api" and C.source("llm") == "saved"
    assert w.changed() is False
    assert "sk-" not in store.path(C.STAMP).read_text(encoding="utf-8")  # 표시 파일에는 시각만 있다

    vault.delete_password(secret_store.SERVICE, "OPENAI_API_KEY")  # 서버가 지웠다
    C.touch_stamp(store)
    os.utime(store.path(C.STAMP), (1_900_000_100, 1_900_000_100))
    assert w.changed() is True and "OPENAI_API_KEY" not in os.environ and C.llm_mode() == "stub"


# ───────────────────────── .env.example 을 그대로 복사한 경우 · 닿지 않는 주소 ─────────────────────────
def test_example_values_copied_from_env_example_count_as_not_given(api, vault, monkeypatch):
    """`.env.example` 을 그대로 복사해 켠 경우: 예시 글자는 넣지 않은 것으로 보아, 화면에서 넣을 수 있어야 한다."""
    client, _ = api
    for k, v in {"OPENAI_API_KEY": "sk-...", "NEWS_DB_HOST": "your-endpoint.rds.amazonaws.com", "NEWS_DB_USER": "reader", "NEWS_DB_PASSWORD": "change-me", "NEWS_DB_NAME": "dbname"}.items():
        monkeypatch.setenv(k, v)
    assert C.source("llm") == "env" and C.source("database") == "env"  # 걸러 내기 전: 예시 값이 환경변수로 들어온 연결처럼 보인다
    assert C.load_stored() is True
    assert "OPENAI_API_KEY" not in os.environ and "NEWS_DB_HOST" not in os.environ and os.environ["NEWS_DB_USER"] == "reader"
    got = client.get(f"{P}/connections").json()
    assert got["database"]["source"] is None and got["database"]["connected"] is False and got["llm"]["source"] is None
    assert "your-endpoint" not in json.dumps(got)

    monkeypatch.setenv("NEWS_DB_URL", "postgresql://reader:PASSWORD@your-endpoint.rds.amazonaws.com:5432/DBNAME?sslmode=require")
    assert C.drop_examples() is True and "NEWS_DB_URL" not in os.environ
    monkeypatch.setenv("OPENAI_API_KEY", GOOD_KEY)  # 진짜 값은 그대로 둔다
    monkeypatch.setenv("DATABASE_URL", TEAM_URL)
    assert C.drop_examples() is False and os.environ["OPENAI_API_KEY"] == GOOD_KEY and os.environ["DATABASE_URL"] == TEAM_URL


def test_address_that_cannot_be_reached_is_not_connected_and_says_why(env_file, vault, tmp_path, monkeypatch):
    """주소가 있어도 자료를 읽지 못하면 연결됨이 아니다. 환경변수로 들어온 주소는 화면에서 못 고치니 원인을 알려야 한다."""

    def unreachable():
        raise RuntimeError('connection failed: could not translate host name "db.exampel.com" to address (password=example-pw)')

    monkeypatch.setenv("DATABASE_URL", TEAM_URL.replace("example.com", "exampel.com"))
    app = create_analysis_app(unreachable, store_dir=tmp_path / "store", settings=AnalysisSettings(), llm=lambda: StubLlm(), cors_origins=[])
    client = TestClient(app, raise_server_exceptions=False)
    r = client.get(f"{P}/connections")
    db = r.json()["database"]
    assert db["connected"] is False and db["source"] == "env" and db["masked"] == "postgresql://reader:••••••••@db.exampel.com:5432/myfinsight"
    assert db["error"]["code"] == "host_not_found" and db["error"]["value"] == "db.exampel.com" and "could not translate host name" in db["error"]["raw"]
    assert "example-pw" not in r.text

    outside = TestClient(app, raise_server_exceptions=False, client=("203.0.113.9", 50000)).get(f"{P}/connections")
    assert outside.json()["database"]["error"] == {"code": "host_not_found", "value": None, "raw": None} and "exampel" not in outside.text


def test_stub_mode_pinned_by_environment_is_part_of_the_status(api, vault, monkeypatch):
    client, _ = api
    assert client.get(f"{P}/connections").json()["llm"]["stub_pinned"] is False
    monkeypatch.setenv("MYFINSIGHT_LLM", "stub")
    monkeypatch.setenv("OPENAI_API_KEY", GOOD_KEY)
    client.app.state.services.reload_connections()
    llm = client.get(f"{P}/connections").json()["llm"]
    assert llm["stub_pinned"] is True and llm["connected"] is False and llm["source"] == "env"  # 키가 있어도 연습 모드로 고정이면 연결됨이 아니다
