"""맥 한 파일형을 내놓는 모양 (packaging/build.py 의 publish · zip_mac_command).

맨 실행 파일을 올리면 내려받을 때 실행 권한이 빠져 Finder 가 「문서를 열도록 설정한 응용프로그램이 없습니다」를 띄운다
(v0.1.1). 그래서 맥은 MyFinSight.command 로 이름을 바꿔 실행 권한과 함께 zip 에 담는다.
실제로 맥에서 풀어 두 번 눌러 보는 것은 여기서 못 한다 — 권한이 zip 에 제대로 적히는지까지 본다.
"""

from __future__ import annotations

import importlib
import shutil
import stat
import subprocess
import sys
import zipfile
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[3]


@pytest.fixture
def build(monkeypatch, tmp_path):
    """build 모듈. 결과는 임시 폴더로 내놓고, 깃이 없는 자리로 둬서 판 번호는 dev 가 된다."""
    monkeypatch.syspath_prepend(str(ROOT / "packaging"))
    monkeypatch.setattr(sys, "dont_write_bytecode", True)  # packaging/ 에 __pycache__ 를 남기지 않는다
    monkeypatch.delitem(sys.modules, "build", raising=False)
    module = importlib.import_module("build")
    monkeypatch.setattr(module, "ROOT", tmp_path / "repo")
    monkeypatch.setattr(module, "DIST", tmp_path / "dist")
    monkeypatch.setattr(module, "VERSION_FILE", tmp_path / "repo" / "VERSION")
    module.version.cache_clear()
    yield module
    module.version.cache_clear()
    sys.modules.pop("build", None)  # 흔한 이름이라 다른 테스트에 남기지 않는다


def fake_exe(tmp_path: Path) -> Path:
    exe = tmp_path / "MyFinSight"
    exe.write_bytes(b"\xcf\xfa\xed\xfe" + b"x" * 5000)  # 내용은 상관없다. 만든 곳의 권한(실행 권한 없음)이 따라가지 않는지 본다
    return exe


def test_mac_onefile_goes_out_as_a_zip_with_an_executable_command_file(build, monkeypatch, tmp_path):
    monkeypatch.setattr(sys, "platform", "darwin")
    monkeypatch.setattr(build, "OS_NAME", "macos")
    exe = fake_exe(tmp_path)
    out = build.publish(exe, onefile=True)
    assert out == tmp_path / "dist" / "dev" / "MyFinSight-dev-macos.zip"
    with zipfile.ZipFile(out) as z:
        (item,) = z.infolist()
        assert item.filename == "MyFinSight.command"  # Finder 에서 두 번 누르면 터미널이 열려 실행된다
        mode = item.external_attr >> 16
        assert stat.S_ISREG(mode) and stat.S_IMODE(mode) == 0o755  # 풀면 실행 권한이 살아 있다
        assert item.create_system == 3  # 유닉스 항목이어야 맥의 압축 풀기가 위 권한을 읽는다
        assert z.read(item) == exe.read_bytes()


def test_other_onefile_builds_are_left_as_they_were(build, monkeypatch, tmp_path):
    monkeypatch.setattr(sys, "platform", "win32")
    monkeypatch.setattr(build, "OS_NAME", "windows")
    exe = fake_exe(tmp_path).rename(tmp_path / "MyFinSight.exe")
    out = build.publish(exe, onefile=True)
    assert out.name == "MyFinSight-dev-windows.exe" and out.read_bytes() == exe.read_bytes()


@pytest.mark.skipif(sys.platform == "win32" or not shutil.which("unzip"), reason="Windows 파일에는 실행 권한이 없다. 자동 빌드의 맥·리눅스 서버에서 돈다")
def test_unzip_brings_the_execute_permission_back(build, tmp_path):
    """맥의 압축 풀기처럼 zip 에 적힌 권한을 되살리는 도구로 풀어 본다 (파이썬의 zipfile 은 권한을 되살리지 않는다)."""
    out = build.zip_mac_command(fake_exe(tmp_path), tmp_path / "mac.zip")
    subprocess.run(["unzip", "-q", str(out), "-d", str(tmp_path / "unzipped")], check=True)  # noqa: S603, S607
    assert (tmp_path / "unzipped" / "MyFinSight.command").stat().st_mode & stat.S_IXUSR
