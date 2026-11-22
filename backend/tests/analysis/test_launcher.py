"""실행 파일의 시작점(packaging/launcher.py): 사용자 폴더 · 환경변수 · 포트 · 이미 켜져 있나.

packaging/ 은 파이썬 패키지가 아니라서(같은 이름의 라이브러리를 가리지 않게) 파일 경로로 불러온다.
서버와 일꾼을 실제로 켜 보는 것은 packaging/build.py 의 "켜 보기"가 맡는다.
"""

from __future__ import annotations

import importlib.util
import json
import os
import socket
import sys
from pathlib import Path
from unittest import mock

import pytest

ROOT = Path(__file__).resolve().parents[3]


@pytest.fixture
def launcher(tmp_path, monkeypatch):
    """런처 모듈. prepare() 가 바꾸는 환경변수와 작업 폴더는 테스트가 끝나면 되돌린다."""
    spec = importlib.util.spec_from_file_location("myfinsight_launcher", ROOT / "packaging" / "launcher.py")
    module = importlib.util.module_from_spec(spec)
    monkeypatch.setattr(sys, "dont_write_bytecode", True)  # packaging/ 에 __pycache__ 를 남기지 않는다
    spec.loader.exec_module(module)
    monkeypatch.chdir(tmp_path)
    with mock.patch.dict(os.environ):
        for key in ("MYFINSIGHT_HOME", "MYFINSIGHT_ENV_FILE", "ANALYSIS_STORE_DIR", "ANALYSIS_OUTPUT_DIR", "ANALYSIS_RESULTS_DB", "MYFINSIGHT_WEB_DIR"):
            os.environ.pop(key, None)
        yield module


def test_home_follows_the_operating_system_and_can_be_overridden(launcher, monkeypatch, tmp_path):
    monkeypatch.setattr(sys, "platform", "win32")
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path / "Local"))
    assert launcher.default_home() == tmp_path / "Local" / "MyFinSight"
    monkeypatch.setattr(sys, "platform", "darwin")
    assert launcher.default_home() == Path.home() / "Library" / "Application Support" / "MyFinSight"
    monkeypatch.setattr(sys, "platform", "linux")
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path / "xdg"))
    assert launcher.default_home() == tmp_path / "xdg" / "MyFinSight"
    monkeypatch.setenv("MYFINSIGHT_HOME", str(tmp_path / "usb"))  # 직접 정하면 운영체제와 상관없이 그곳
    assert launcher.default_home() == tmp_path / "usb"


def test_prepare_points_everything_the_app_writes_at_the_home_folder(launcher, tmp_path):
    home = tmp_path / "home"
    launcher.prepare(home)
    assert (home / "store").is_dir() and (home / "output").is_dir() and (home / "logs").is_dir()
    assert os.environ["ANALYSIS_STORE_DIR"] == str(home / "store")
    assert os.environ["ANALYSIS_OUTPUT_DIR"] == str(home / "output")
    assert os.environ["ANALYSIS_RESULTS_DB"] == "sqlite:///" + (home / "analysis_results.db").as_posix()
    # 설정 파일 자리를 못 박는다 (실행한 폴더의 .env 를 읽지 않게). 파일은 만들지 않는다 — 앱은 .env 를 쓰지 않는다
    assert os.environ["MYFINSIGHT_ENV_FILE"] == str(home / "settings.env") and not (home / "settings.env").exists()
    assert Path.cwd() == home  # 남은 상대 경로(data/…)도 사용자 폴더 아래로


def test_prepare_keeps_values_that_were_already_given(launcher, tmp_path, monkeypatch):
    monkeypatch.setenv("ANALYSIS_OUTPUT_DIR", str(tmp_path / "elsewhere"))  # 예: Docker 가 볼륨 자리를 정해 준 경우
    launcher.prepare(tmp_path / "home")
    assert os.environ["ANALYSIS_OUTPUT_DIR"] == str(tmp_path / "elsewhere")


def test_pick_port_moves_on_when_the_preferred_port_is_taken(launcher):
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as busy:
        busy.bind(("127.0.0.1", 0))
        taken = busy.getsockname()[1]
        assert launcher.pick_port("127.0.0.1", taken) != taken
    assert launcher.pick_port("127.0.0.1", taken) == taken  # 비면 그 포트 그대로 (포트가 같아야 브라우저 기록이 이어진다)


def test_pick_port_keeps_the_port_right_after_the_server_stopped(launcher):
    """서버가 연결을 먼저 끊고 꺼진 직후에도 같은 포트를 고른다 (리눅스·맥은 그 포트를 1분쯤 '정리 중'으로 둔다)."""
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as server:
        if sys.platform != "win32":
            server.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)  # uvicorn 이 포트를 잡는 방식
        server.bind(("127.0.0.1", 0))
        server.listen()
        port = server.getsockname()[1]
        assert launcher.pick_port("127.0.0.1", port) != port  # 켜져 있는 동안은 쓰이는 포트로 본다
        with socket.create_connection(("127.0.0.1", port)) as client:
            conn, _ = server.accept()
            conn.close()  # 서버 쪽이 먼저 끊는다 (프로그램을 끌 때와 같다)
            client.recv(1)
    assert launcher.pick_port("127.0.0.1", port) == port


def test_a_leftover_server_file_does_not_count_as_running(launcher, tmp_path):
    assert launcher.running_instance(tmp_path) is None  # 기록 없음
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("127.0.0.1", 0))
        dead = s.getsockname()[1]
    (tmp_path / launcher.SERVER_FILE).write_text(json.dumps({"pid": 1, "url": f"http://127.0.0.1:{dead}"}), encoding="utf-8")
    assert launcher.running_instance(tmp_path) is None  # 기록은 있는데 그 주소에서 아무도 답하지 않음 (강제로 꺼진 뒤)
    (tmp_path / launcher.SERVER_FILE).write_text("깨진 내용", encoding="utf-8")
    assert launcher.running_instance(tmp_path) is None


def test_worker_is_the_same_program_started_again(launcher, monkeypatch):
    cmd = launcher.worker_command()  # 소스로 켰을 때: 파이썬 + 이 파일
    assert cmd[:2] == [sys.executable, str(ROOT / "packaging" / "launcher.py")]
    assert cmd[2:] == ["--worker", "--parent", str(os.getpid())]
    monkeypatch.setattr(launcher, "FROZEN", True)  # 실행 파일일 때: 그 실행 파일 하나
    assert launcher.worker_command() == [sys.executable, "--worker", "--parent", str(os.getpid())]


def test_web_folder_is_inside_the_bundle_when_frozen(launcher, monkeypatch, tmp_path):
    assert launcher.web_dir() == ROOT / "Front" / "dist"
    monkeypatch.setattr(launcher, "FROZEN", True)
    monkeypatch.setattr(sys, "_MEIPASS", str(tmp_path / "_internal"), raising=False)
    assert launcher.web_dir() == tmp_path / "_internal" / "web"
