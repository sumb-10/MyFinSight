"""판 번호와 릴리스 노트 (packaging/build.py 의 version · packaging/release.py 의 노트).

판 번호는 깃 태그가 정한다 — 손으로 적는 곳이 없다. 자동 빌드는 태그를 받으면 그 판의 릴리스 노트 절을 Release 의 설명으로 쓴다.

build.py · release.py 는 스크립트라 패키지로 불러올 수 없다 (packaging/ 은 같은 이름의 라이브러리와 겹쳐 패키지로 두지 않는다).
그래서 경로를 잠깐 더해 불러온다.
"""

from __future__ import annotations

import importlib
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[3]

NOTES = """# 릴리스 노트

## v0.1.10 — 2027-01-05

- 열 번째 수정

## v0.1.1 — 2026-12-01 (시험판)

- 종목 사전을 스스로 만든다

### 주의사항

- 맥은 아직

## v0.1.0 — 2026-11-23 (시험판)

- 첫 판

## v0.0.9
"""


@pytest.fixture
def scripts(monkeypatch, tmp_path):
    """(build, release) 모듈. 저장소 자리는 빈 임시 폴더로, 릴리스 노트는 위의 글로 바꿔 둔다."""
    monkeypatch.syspath_prepend(str(ROOT / "packaging"))
    monkeypatch.setattr(sys, "dont_write_bytecode", True)  # packaging/ 에 __pycache__ 를 남기지 않는다
    for name in ("release", "build"):
        monkeypatch.delitem(sys.modules, name, raising=False)
    release = importlib.import_module("release")
    build = sys.modules["build"]
    repo = tmp_path / "repo"
    (repo / "packaging").mkdir(parents=True)
    notes = repo / "packaging" / "RELEASE_NOTES.md"
    notes.write_text(NOTES, encoding="utf-8")
    monkeypatch.setattr(build, "ROOT", repo)
    monkeypatch.setattr(build, "DIST", repo / "packaging" / "dist")
    monkeypatch.setattr(build, "VERSION_FILE", repo / "packaging" / "VERSION")
    monkeypatch.setattr(release, "NOTES", notes)
    build.version.cache_clear()
    yield build, release
    build.version.cache_clear()
    for name in ("release", "build"):  # 흔한 이름이라 다른 테스트에 남기지 않는다
        sys.modules.pop(name, None)


def git(repo: Path, *args: str) -> None:
    subprocess.run(["git", "-c", "user.name=t", "-c", "user.email=t@example.com", *args], cwd=repo, check=True, capture_output=True)  # noqa: S603, S607


def commit(repo: Path, text: str) -> None:
    (repo / "code.txt").write_text(text, encoding="utf-8")
    git(repo, "add", "-A")
    git(repo, "commit", "-qm", text)


def version_now(build) -> str:
    build.version.cache_clear()  # 한 번 돌 때는 처음 정한 번호를 끝까지 쓴다 → 테스트에서는 매번 다시 묻는다
    return build.version()


# ───────────────────────── 판 번호 ─────────────────────────
def test_the_version_is_the_tag_only_on_exactly_that_commit_without_changes(scripts):
    build, _release = scripts
    repo = build.ROOT
    git(repo, "init", "-q")
    commit(repo, "first")
    assert version_now(build) == "dev"  # 태그가 없는 커밋
    git(repo, "tag", "v0.1.1")
    assert version_now(build) == "0.1.1" and build.out_dir() == build.DIST / "v0.1.1"
    (repo / "code.txt").write_text("edited, not committed", encoding="utf-8")
    assert version_now(build) == "dev"  # 낸 판과 이름은 같고 내용이 다른 파일이 나오지 않게
    commit(repo, "second")
    assert version_now(build) == "dev" and build.out_dir() == build.DIST / "dev"  # 태그 뒤의 커밋
    git(repo, "tag", "nightly")
    assert version_now(build) == "dev"  # v 로 시작하는 번호 태그만 판 번호다


def test_inside_the_bundle_the_version_comes_from_the_file_written_into_it(scripts):
    """건네는 묶음(source.zip) 안에는 깃이 없다. 묶음을 만들 때 적어 넣은 번호를 쓴다."""
    build, _release = scripts
    assert version_now(build) == "dev"  # 깃도 파일도 없으면
    build.VERSION_FILE.write_text("0.1.1\n", encoding="utf-8")
    assert version_now(build) == "0.1.1"


# ───────────────────────── 릴리스 노트 ─────────────────────────
def test_notes_are_that_version_section_up_to_the_next_version(scripts):
    _build, release = scripts
    text = release.notes_for("v0.1.1")
    assert text.startswith("## v0.1.1 — 2026-12-01 (시험판)\n")  # 절의 제목 줄부터
    assert "종목 사전을 스스로 만든다" in text and "### 주의사항" in text and "맥은 아직" in text  # 작은 제목은 그 판의 것
    assert "첫 판" not in text and "열 번째 수정" not in text and "# 릴리스 노트" not in text  # 다른 판 · 문서 제목은 들어가지 않는다


def test_a_longer_version_number_is_not_mistaken_for_this_one(scripts):
    _build, release = scripts
    assert "열 번째 수정" in release.notes_for("v0.1.10")
    assert release.find_notes("v0.1") is None  # v0.1.0 · v0.1.1 의 앞부분과 같다고 그 절을 쓰지 않는다


def test_a_missing_or_empty_section_stops_the_release(scripts):
    _build, release = scripts
    for tag in ("v0.2.0", "v0.0.9"):  # 절이 없음 · 제목만 있고 비어 있음
        with pytest.raises(SystemExit, match=f"'## {tag}' 절이 없거나 비어 있습니다"):
            release.notes_for(tag)


def test_the_notes_are_copied_next_to_the_files_of_that_version(scripts):
    build, release = scripts
    assert release.copy_notes() is None  # 판 번호가 없는 빌드(dev)에는 넣지 않는다
    build.VERSION_FILE.write_text("0.1.1\n", encoding="utf-8")
    build.version.cache_clear()
    build.out_dir().mkdir(parents=True)
    copied = release.copy_notes()
    assert copied == build.DIST / "v0.1.1" / "RELEASE_NOTES.md"
    assert copied.read_text(encoding="utf-8").startswith("## v0.1.1 — 2026-12-01")
    build.VERSION_FILE.write_text("0.2.0\n", encoding="utf-8")  # 아직 절을 적지 않은 판: 빌드는 되고 사본만 건너뛴다
    build.version.cache_clear()
    assert release.copy_notes() is None
