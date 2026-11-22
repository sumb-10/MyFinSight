"""분석 서비스가 팀 DB 로 나가는 입구(common/dbconn.py): 사람이 기다리는 길은 한 번 두드려 보고 바로 알린다.

배경 (2026-11-23 측정): 저장된 주소의 서버가 응답하지 않으면 저장소를 여는 데 10분이 걸렸다 (접속 130초 × 4번 + 쉬는 85초).
그동안 /health 가 답하지 못해 앱 전체가 멈춘 것처럼 보였다. 여기서는 실제 접속 없이 그 규칙만 본다.
"""

from __future__ import annotations

import pytest

from backend.analysis.common import dbconn
from backend.schemas.errors import RepositoryError

URL = "postgresql://reader:example-pw@db.example.com:5432/myfinsight"


class FakeEngine:
    """접속을 흉내 낸다: up 이 False 면 접속이 실패한다. 몇 번 접속하려 했는지 센다."""

    up = False
    tries = 0
    urls: list[str] = []

    def __init__(self, url, **_kw):
        FakeEngine.urls.append(url.render_as_string(hide_password=False))

    def connect(self):
        FakeEngine.tries += 1
        if not FakeEngine.up:
            raise RuntimeError("connection timeout expired")
        return self

    def close(self):
        pass

    def dispose(self):
        pass


@pytest.fixture
def db(monkeypatch):
    """접속은 FakeEngine 이, 시각은 clock 이 맡는다. 저장소를 여는 것은 주소만 적어 두는 가짜."""
    FakeEngine.up, FakeEngine.tries, FakeEngine.urls = False, 0, []
    clock = {"now": 1000.0}
    opened: list[str | None] = []
    monkeypatch.setattr(dbconn, "create_engine", FakeEngine)
    monkeypatch.setattr(dbconn.time, "monotonic", lambda: clock["now"])
    monkeypatch.setattr(dbconn, "database_url", lambda: URL)
    monkeypatch.setattr(dbconn, "open_analysis_repository", lambda url=None: opened.append(url) or "repo")
    monkeypatch.setattr(dbconn, "_unreachable", None)
    dbconn.default_repo.cache_clear()
    yield clock, opened
    dbconn.default_repo.cache_clear()


def test_server_gives_up_after_one_knock_and_does_not_open_the_repository(db):
    _clock, opened = db
    with pytest.raises(RepositoryError) as e:
        dbconn.default_repo()
    assert e.value.code == "REPO_READ_FAILED" and "connection timeout expired" in str(e.value)
    assert isinstance(e.value.__cause__, RuntimeError)  # 원래 오류가 달려 있다 (연결 설정 화면이 이걸로 원인을 가린다)
    assert FakeEngine.tries == 1 and opened == []  # 저장소(재시도 규칙이 있는 곳)까지 가지 않았다
    assert "connect_timeout=8" in FakeEngine.urls[0]  # 두드릴 때도 제한 시간 안에


def test_a_recent_failure_is_remembered_so_every_status_poll_does_not_knock_again(db):
    clock, _opened = db
    for _ in range(3):  # 화면이 15초마다 묻는다
        with pytest.raises(RepositoryError):
            dbconn.default_repo()
        clock["now"] += 10
    assert FakeEngine.tries == 1  # 30초 안에는 다시 두드리지 않았다 (1000 → 1010 → 1020)
    clock["now"] += 11  # 30초가 지났다
    with pytest.raises(RepositoryError):
        dbconn.default_repo()
    assert FakeEngine.tries == 2


def test_once_reachable_the_repository_opens_with_the_time_limit_and_is_kept(db):
    _clock, opened = db
    FakeEngine.up = True
    assert dbconn.default_repo() == "repo" and dbconn.default_repo() == "repo"
    assert FakeEngine.tries == 1 and opened == [URL + "?connect_timeout=8"]  # 한 번만 열고, 열린 뒤의 접속에도 제한 시간


def test_a_successful_knock_forgets_the_failure_right_away(db):
    """닿지 않던 주소를 연결 설정에서 다시 확인해 통과했으면, 서버가 30초를 더 기다리지 않고 바로 연다."""
    _clock, opened = db
    with pytest.raises(RepositoryError):
        dbconn.default_repo()
    FakeEngine.up = True
    dbconn.knock(URL)  # 연결 확인(connections.check_database)이 부르는 것
    assert dbconn.default_repo() == "repo" and opened == [URL + "?connect_timeout=8"]


def test_a_different_address_is_knocked_even_right_after_a_failure(db, monkeypatch):
    with pytest.raises(RepositoryError):
        dbconn.default_repo()
    monkeypatch.setattr(dbconn, "database_url", lambda: URL.replace("example.com", "example.org"))  # 주소를 바꿨다
    with pytest.raises(RepositoryError):
        dbconn.default_repo()
    assert FakeEngine.tries == 2


def test_worker_path_does_not_knock(monkeypatch):
    """일꾼·터미널 명령은 open_analysis_repository 를 바로 부른다: 두드리지 않고, 저장소의 재시도 규칙대로 오래 기다린다."""

    def no_knock(url):
        raise AssertionError("일꾼이 여는 길에서는 두드리지 않는다")

    opened = []
    monkeypatch.setattr(dbconn, "knock", no_knock)
    monkeypatch.setattr(dbconn, "open_repository", lambda url: opened.append(url) or "repo")
    monkeypatch.setattr(dbconn, "results_url", lambda _u: None)
    assert dbconn.open_analysis_repository(URL) == "repo" and opened == [URL]  # 주소도 그대로 (제한 시간을 붙이지 않는다)


def test_sqlite_and_no_address_are_opened_without_knocking(db, monkeypatch):
    _clock, opened = db
    dbconn.knock("sqlite:///data/myfinsight.db")  # 파일은 두드릴 것이 없다 (없는 파일을 만들지도 않는다)
    assert FakeEngine.tries == 0
    monkeypatch.setattr(dbconn, "database_url", lambda: None)  # 주소를 넣지 않은 처음 사용자
    assert dbconn.default_repo() == "repo" and opened == [None] and FakeEngine.tries == 0


@pytest.mark.parametrize(("url", "expected"), [
    ("postgresql://u:p@h:5432/d", "postgresql://u:p@h:5432/d?connect_timeout=8"),
    ("postgresql://u:p@h:5432/d?sslmode=require", "postgresql://u:p@h:5432/d?sslmode=require&connect_timeout=8"),
    ("postgresql://u:p@h:5432/d?connect_timeout=3", "postgresql://u:p@h:5432/d?connect_timeout=3"),  # 적혀 있으면 그대로
    ("sqlite:///data/myfinsight.db", "sqlite:///data/myfinsight.db"),
])  # fmt: skip
def test_with_timeout(url, expected):
    assert dbconn.with_timeout(url) == expected
