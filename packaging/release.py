"""GitHub Release 에 올릴 파일을 모은다. 결과는 모두 packaging/dist/ 에 쌓인다.

    python packaging/build.py --all        # 실행 파일 (이 운영체제용): 한 파일형 + 폴더형
    python packaging/release.py            # 묶음(source.zip): 스크립트 버전 + Docker Compose 버전
    python packaging/release.py --linux    # + 리눅스용 실행 파일 (Docker 안에서 만든다)

묶음(source.zip)에 들어가는 것: 서버·일꾼 코드, 미리 빌드한 화면(Front/dist), 켜는 스크립트(run.bat · run.sh),
Docker 파일(Dockerfile · compose.yaml), 안내문. 받는 사람은 Node 없이 파이썬이나 Docker 만 있으면 된다.
깃에 없는 화면 빌드 결과를 여기서 같이 넣어 주기 때문에, 저장소를 그대로 받는 것과 다르다.
"""

from __future__ import annotations

import argparse
import shutil
import subprocess
import sys
import tomllib
import zipfile
from pathlib import Path

sys.dont_write_bytecode = True  # 아래 import 가 packaging/ 에 __pycache__ 를 남기지 않게

from build import (  # noqa: E402
    DIST,
    FORBIDDEN,
    HAS_WEB_SOURCE,
    HERE,
    ROOT,
    WORK,
    build_web,
    check_inputs,
    clean_work,
    refuse_released_version,
    step,
    version,
    web_problem,
)

BUNDLE = HERE / "source-zip"  # 묶음(source.zip)에만 들어가는 파일의 원본
STAGE = WORK / "stage"  # 묶음을 차려 놓는 곳 (압축하기 전의 폴더). 끝나면 지운다
# 묶음에 넣지 않는 backend 의 부분: 테스트와 그 재료, 수집 서버용 배포 설정
SKIP_BACKEND = ("backend/tests/", "backend/test_scenarios/", "backend/test_scenarios.zip", "backend/deploy/")
# 깃에 없지만 넣어야 하는 것
EXTRA_DIRS = ("Front/dist",)
# 실행 파일을 직접 만들 사람(맥)을 위해 빌드 도구도 넣는다
PACKAGING_FILES = ("launcher.py", "build.py", "myfinsight.spec")
# 묶음 원본 → 묶음 안에서의 이름. 점으로 시작하는 이름은 원본에서는 점 없이 둔다 (저장소의 .gitignore · Docker 가 헷갈리지 않게)
BUNDLE_FILES = {"run.bat": "run.bat", "run.sh": "run.sh", "Dockerfile": "Dockerfile", "compose.yaml": "compose.yaml",
                "dockerignore": ".dockerignore", "env.example": ".env.example", "README.md": "README.md"}  # fmt: skip
EXECUTABLE = ("run.sh",)  # 압축을 풀었을 때 실행 권한이 붙어 있어야 하는 파일


def tracked_backend() -> list[str]:
    """깃에 올라가 있는 backend 파일 (작업 폴더에만 있는 파일이 딸려 들어가지 않게 깃에 물어본다)."""
    out = subprocess.run(["git", "-c", "core.quotepath=off", "ls-files", "backend"], cwd=ROOT, capture_output=True, text=True, encoding="utf-8", check=True)  # noqa: S603, S607
    return [f for f in out.stdout.splitlines() if f and not f.startswith(SKIP_BACKEND)]


def requirements() -> str:
    """pyproject.toml 의 기본 의존성 + analysis 묶음. 스크립트 버전과 Docker 가 이 파일로 라이브러리를 깐다."""
    project = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))["project"]
    lines = [*project["dependencies"], *project["optional-dependencies"]["analysis"]]
    return "# pyproject.toml 에서 만든 파일 (packaging/release.py). 직접 고치지 말 것.\n" + "\n".join(lines) + "\n"


def write_text(path: Path, text: str) -> None:
    """글 파일을 줄 끝을 맞춰 적는다: .bat 은 Windows 줄 끝(없으면 goto 가 깨진다), 나머지는 유닉스 줄 끝(.sh 가 깨지지 않게)."""
    text = text.replace("\r\n", "\n")
    path.write_bytes((text.replace("\n", "\r\n") if path.suffix == ".bat" else text).encode("utf-8"))


def stage() -> Path:
    """묶음 폴더를 차린다: packaging/build/stage/MyFinSight-<판>/"""
    check_inputs()  # 화면 빌드가 있고 최신인지
    top = STAGE / f"MyFinSight-{version()}"
    shutil.rmtree(STAGE, ignore_errors=True)
    top.mkdir(parents=True)
    for rel in tracked_backend():
        (top / rel).parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(ROOT / rel, top / rel)
    for rel in EXTRA_DIRS:
        shutil.copytree(ROOT / rel, top / rel, dirs_exist_ok=True)
    (top / "packaging").mkdir()
    for name in PACKAGING_FILES:
        shutil.copy2(HERE / name, top / "packaging" / name)
    shutil.copy2(ROOT / "pyproject.toml", top / "pyproject.toml")  # 판 번호와, 실행 파일을 직접 만들 때 쓴다
    write_text(top / "requirements.txt", requirements())
    for source, name in BUNDLE_FILES.items():
        write_text(top / name, (BUNDLE / source).read_text(encoding="utf-8").replace("{VERSION}", version()))
    found = [str(p.relative_to(top)) for p in top.rglob("*") if p.name in FORBIDDEN or p.name == "__pycache__"]
    if found:
        raise SystemExit(f"들어가면 안 되는 파일이 묶음에 들어갔습니다: {found}")
    return top


def archive(top: Path) -> Path:
    """묶음을 zip 하나로. 맨 위 폴더 하나(MyFinSight-<판>/)에 다 들어 있게 하고, run.sh 에는 실행 권한을 적어 둔다."""
    DIST.mkdir(parents=True, exist_ok=True)
    target = DIST / f"MyFinSight-{version()}-source.zip"
    target.unlink(missing_ok=True)
    with zipfile.ZipFile(target, "w", zipfile.ZIP_DEFLATED, compresslevel=9) as z:
        for p in sorted(top.rglob("*")):
            if not p.is_file():
                continue
            info = zipfile.ZipInfo.from_file(p, arcname=f"{top.name}/{p.relative_to(top).as_posix()}")
            info.compress_type = zipfile.ZIP_DEFLATED
            # Windows 에서 만들어도 맥·리눅스에서 권한이 맞게: 유닉스에서 만든 것으로 표시해야 unzip 이 권한 칸을 읽는다
            # (표시가 없으면 run.sh 가 실행 권한 없이 풀려 ./run.sh 가 거부된다 — 2026-11-23 리눅스 컨테이너에서 확인)
            info.create_system = 3
            info.external_attr = (0o100755 if p.name in EXECUTABLE else 0o100644) << 16
            z.writestr(info, p.read_bytes())
    return target


def linux_executables(top: Path) -> list[Path]:
    """리눅스용 실행 파일을 Docker 안에서 만든다 (묶음 폴더를 재료로). 만든 것을 dist/ 로 꺼내 온다."""
    if not shutil.which("docker"):
        raise SystemExit("docker 를 찾지 못했습니다. 리눅스용 실행 파일은 Docker 가 있어야 만들 수 있습니다.")
    image, box = "myfinsight-linux-exe", "myfinsight-linux-exe-out"

    def docker(*args: str, check: bool = True) -> None:
        print("  $ docker", " ".join(args), flush=True)
        subprocess.run(["docker", *args], check=check)  # noqa: S603, S607

    docker("build", "-f", str(HERE / "linux-exe.Dockerfile"), "-t", image, str(top))
    docker("rm", "-f", box, check=False)
    docker("create", "--name", box, image)
    try:
        docker("cp", f"{box}:/src/packaging/dist/.", str(DIST))
    finally:
        docker("rm", "-f", box, check=False)
    return sorted(DIST.glob(f"MyFinSight-{version()}-linux*"))


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--linux", action="store_true", help="리눅스용 실행 파일도 만든다 (Docker 필요, 10분쯤)")
    a = ap.parse_args()
    refuse_released_version()
    problem = web_problem()
    if HAS_WEB_SOURCE and problem:  # 처음 받은 저장소·자동 빌드 서버에는 빌드한 화면이 없다. build.py 를 먼저 돌렸으면 건너뛴다
        step(f"화면 빌드 ({problem})")
        build_web()
    step("묶음 차리기")
    top = stage()
    files = sum(1 for p in top.rglob("*") if p.is_file())
    print(f"  {top}  (파일 {files}개)")
    step("묶음 압축")
    made = [archive(top)]
    if a.linux:
        step("리눅스용 실행 파일 (Docker 안에서, 10분쯤 걸립니다)")
        made += linux_executables(top)
    clean_work("stage")
    step("dist/ 에 있는 파일")
    for f in sorted(DIST.iterdir()):
        mark = "*" if f in made else " "
        print(f"  {mark} {f.name}  ({f.stat().st_size / 1e6:.1f} MB)")
    print("\n끝. (* = 이번에 만든 것)  올리는 법: packaging/README.md 의 「GitHub Release 에 올리기」")
    return 0


if __name__ == "__main__":
    sys.exit(main())
