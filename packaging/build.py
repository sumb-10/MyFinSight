"""실행 파일을 만든다 (Windows · macOS · Linux 공통). 만든 운영체제용만 나온다 — 맥용은 맥에서 돌려야 한다.

    python packaging/build.py            # 한 파일형 (기본): MyFinSight-<판>-<운영체제>.exe
    python packaging/build.py --folder   # 폴더형: MyFinSight-<판>-<운영체제>-folder.zip  (켜지는 것이 더 빠르다, 풀어서 폴더째로 둔다)
    python packaging/build.py --all      # 둘 다
    python packaging/build.py --skip-web # 화면을 다시 빌드하지 않는다 (Front/dist 를 그대로 쓴다)

순서: 화면 빌드 → 자료 확인 → 묶기 → 내용 확인 → 켜 보기 → 내놓기.
결과는 packaging/dist/ 에 건넬 이름으로 나온다. 만드는 동안 쓰는 중간 파일은 packaging/build/ 에 두었다가 끝나면 지운다
(--keep-work 를 주면 남긴다 — 묶인 내용을 들여다볼 때).
필요한 것: pip install -e ".[analysis,packaging]", Node (화면 빌드), backend/data/processed 의 종목 사전.
.env · data/ · output/ 은 들어가지 않는다.
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
import signal
import subprocess
import sys
import tempfile
import time
import tomllib
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
HERE = ROOT / "packaging"
DIST = HERE / "dist"  # 건넬 파일만 모이는 곳 (GitHub Release 에 올리는 파일)
WORK = HERE / "build"  # 만드는 동안만 쓰는 곳. 끝나면 지운다
EXE_NAME = "MyFinSight.exe" if sys.platform == "win32" else "MyFinSight"
APP_OUT = WORK / "app"  # PyInstaller 가 묶은 것을 내놓는 곳
APP_DIR = APP_OUT / "MyFinSight"  # 폴더형의 결과 (한 파일형은 APP_OUT / "onefile" / EXE_NAME 하나)
OS_NAME = {"win32": "windows", "darwin": "macos"}.get(sys.platform, "linux")
# 건네는 묶음(source.zip)에는 화면 소스가 없고 빌드해 둔 화면(Front/dist)만 있다 → 거기서는 화면을 다시 빌드하지 않는다
HAS_WEB_SOURCE = (ROOT / "Front" / "src").is_dir()
SMOKE_PORT = 8791  # 켜 보기에 쓰는 포트 (쓰고 있는 앱의 8765 와 겹치지 않게)
# 들어가면 안 되는 것 (비밀 값 · 사용자 자료). 묶은 뒤 폴더를 훑어 하나라도 있으면 실패로 본다
FORBIDDEN = (".env", ".env.local", ".env.backup", "settings.env", "analysis_results.db", "myfinsight.db")


def step(text: str) -> None:
    print(f"\n== {text}", flush=True)


def run(cmd: list[str], cwd: Path, env: dict[str, str] | None = None) -> None:
    print("  $", " ".join(cmd), flush=True)
    subprocess.run(cmd, cwd=cwd, env=env, check=True)  # noqa: S603


def build_web() -> None:
    """화면을 운영용으로 빌드한다. 목업 모드(VITE_ENABLE_MOCK)는 넣지 않는다."""
    npm = shutil.which("npm")
    if not npm:
        raise SystemExit("npm 을 찾지 못했습니다. Node 를 설치하거나, 이미 빌드해 둔 것이 있으면 --skip-web 을 주세요.")
    env = {k: v for k, v in os.environ.items() if k != "VITE_ENABLE_MOCK"}
    if not (ROOT / "Front" / "node_modules").exists():
        run([npm, "ci"], ROOT / "Front", env)
    # 예전 결과를 여기서 지운다. vite 8 은 이미 있는 dist 를 비우다가, 저장소 경로에 한글이 있으면(Windows) 오류 글 없이
    # 죽는다 (종료 코드 0xC0000409) — 그러면 예전 화면이 그대로 묶인다 (2026-11-23 에 11-07 화면이 묶여 발견).
    dist = ROOT / "Front" / "dist"
    shutil.rmtree(dist, ignore_errors=True)
    run([npm, "run", "build"], ROOT / "Front", env)
    if not (dist / "index.html").exists():
        raise SystemExit("화면 빌드가 결과를 내지 못했습니다.")


def check_inputs() -> None:
    web = ROOT / "Front" / "dist" / "index.html"
    if not web.exists():
        raise SystemExit(f"화면 빌드 결과가 없습니다: {web}")
    if HAS_WEB_SOURCE:  # --skip-web 으로 예전 화면을 묶지 않게: 화면 소스가 빌드 결과보다 새것이면 멈춘다
        sources = [p for p in (ROOT / "Front" / "src").rglob("*") if p.is_file()] + [ROOT / "Front" / "index.html", ROOT / "Front" / "package.json"]
        newest = max(sources, key=lambda p: p.stat().st_mtime)
        if newest.stat().st_mtime > web.stat().st_mtime:
            raise SystemExit(f"화면 빌드 결과가 소스보다 오래됐습니다 ({newest.relative_to(ROOT)} 가 더 새것). --skip-web 없이 다시 돌려 주세요.")
    descriptor = ROOT / "backend" / "data" / "processed" / "all_descriptor.json"
    if not descriptor.exists():
        raise SystemExit(f"종목 사전이 없습니다: {descriptor}\n  backend/scripts/build_descriptor.py 로 만들거나 팀에서 받아 넣어 주세요.")


def bundle(onefile: bool) -> Path:
    """묶는다. 돌려주는 값은 켜는 파일의 경로."""
    env = {**os.environ, "MYFINSIGHT_ONEFILE": "1" if onefile else "0"}
    work = WORK / "pyinstaller" / ("onefile" if onefile else "onedir")  # 두 모양의 중간 파일이 섞이지 않게
    out = APP_OUT / "onefile" if onefile else APP_OUT  # 맥·리눅스에서는 폴더(MyFinSight)와 파일(MyFinSight) 이름이 같아 한곳에 둘 수 없다
    run([sys.executable, "-m", "PyInstaller", str(HERE / "myfinsight.spec"), "--noconfirm", "--distpath", str(out), "--workpath", str(work)], ROOT, env)
    return out / EXE_NAME if onefile else APP_DIR / EXE_NAME


def check_contents(exe: Path) -> None:
    """비밀 값이나 사용자 자료가 딸려 들어가지 않았는지 본다. 한 파일형은 안을 훑을 수 없어 크기만 적는다
    (무엇이 들어가는지는 두 모양이 같은 spec 을 쓰므로 폴더형으로 확인한 것과 같다)."""
    if exe.parent != APP_DIR:
        print(f"  {exe}  ({exe.stat().st_size / 1e6:.0f} MB)")
        return
    found = [str(p.relative_to(APP_DIR)) for p in APP_DIR.rglob("*") if p.name in FORBIDDEN]
    if found:
        raise SystemExit(f"들어가면 안 되는 파일이 묶였습니다: {found}")
    size = sum(p.stat().st_size for p in APP_DIR.rglob("*") if p.is_file())
    print(f"  {APP_DIR}  ({size / 1e6:.0f} MB)")


def smoke(exe: Path) -> None:
    """만든 것을 빈 사용자 폴더로 켜서 서버 · 화면 · 일꾼 · 보관함이 되는지 본다. 실제 사용자 폴더와 보관함은 건드리지 않는다."""
    home = Path(tempfile.mkdtemp(prefix="myfinsight-smoke-"))
    env = {**os.environ, "MYFINSIGHT_HOME": str(home), "MYFINSIGHT_SECRET_SERVICE": "MyFinSight-build-check"}
    for key in ("DATABASE_URL", "OPENAI_API_KEY", "MYFINSIGHT_ENV_FILE", "MYFINSIGHT_LLM"):
        env.pop(key, None)
    url = f"http://127.0.0.1:{SMOKE_PORT}"
    proc = subprocess.Popen([str(exe), "--port", str(SMOKE_PORT), "--no-browser"], env=env, cwd=home, start_new_session=sys.platform != "win32")  # noqa: S603
    started = time.time()
    try:
        health = None
        for _ in range(180):  # 처음 켤 때는 백신 검사 때문에 오래 걸릴 수 있다
            if proc.poll() is not None:
                raise SystemExit(f"켜자마자 꺼졌습니다 (코드 {proc.returncode}). 로그: {home / 'logs'}")
            try:
                url = json.loads((home / "server.json").read_text(encoding="utf-8"))["url"]  # 그 포트가 쓰이고 있으면 런처가 다음 번호로 옮긴다
                health = json.loads(urllib.request.urlopen(f"{url}/api/v1/health", timeout=2).read())  # noqa: S310
                if health["worker"]["alive"]:
                    break
            except Exception:  # noqa: BLE001 — 아직 안 켜짐
                pass
            time.sleep(1)
        if not health or not health["worker"]["alive"]:
            raise SystemExit(f"서버 또는 일꾼이 켜지지 않았습니다. 로그: {home / 'logs'}")
        page = urllib.request.urlopen(url, timeout=5).read().decode("utf-8")  # noqa: S310
        if "<title>MyFinSight</title>" not in page:
            raise SystemExit("화면(index.html)이 나오지 않습니다.")
        conns = json.loads(urllib.request.urlopen(f"{url}/api/v1/connections", timeout=20).read())  # noqa: S310
        print(f"  서버 켜짐 · 일꾼 켜짐 · 화면 나옴 · 보관함: {conns['store_label_ko'] or '없음'} (저장 가능: {conns['can_save']}) · 켜지는 데 {time.time() - started:.0f}초")
        if not conns["can_save"] and sys.platform in ("win32", "darwin"):
            raise SystemExit("운영체제 보관함을 쓸 수 없습니다 — 화면에서 주소·키를 저장하지 못합니다 (keyring 이 제대로 묶였는지 확인).")
    finally:
        stop_tree(proc, started)
        time.sleep(3)  # 일꾼은 서버가 사라진 것을 보고 스스로 끝낸다
        shutil.rmtree(home, ignore_errors=True)


def stop_tree(proc: subprocess.Popen, started: float) -> None:
    """켜 본 프로그램을 자식까지 끈다. 한 파일형은 "푸는 프로세스 → 실제 서버 → 일꾼" 세 겹이라, 맨 위만 죽이면
    서버와 일꾼이 남는다 (Windows 는 부모가 죽어도 자식이 따라 죽지 않는다). 풀어 둔 임시 폴더도 여기서 지운다."""
    # 한 파일형이 푸는 곳은 Windows 의 임시 폴더(TMP → TEMP)다. 파이썬의 tempfile 은 TMPDIR 을 먼저 봐서 다른 곳일 수 있어 다 훑는다
    temp_dirs = {Path(d) for d in (os.environ.get("TMP"), os.environ.get("TEMP"), tempfile.gettempdir()) if d}
    unpacked = [p for d in temp_dirs for p in d.glob("_MEI*") if p.stat().st_mtime >= started - 5]  # 이번에 켜면서 생긴 것만
    if sys.platform == "win32":
        subprocess.run(["taskkill", "/PID", str(proc.pid), "/T", "/F"], capture_output=True, check=False)  # noqa: S603, S607
    else:  # 리눅스·맥: 켤 때 따로 묶어 둔 무리(서버·일꾼·푸는 프로세스)에 한꺼번에 보낸다
        for sig in (signal.SIGTERM, signal.SIGKILL):
            try:
                os.killpg(proc.pid, sig)
            except ProcessLookupError:
                break
            try:
                proc.wait(timeout=10)
                break
            except subprocess.TimeoutExpired:
                continue
    try:
        proc.wait(timeout=15)
    except subprocess.TimeoutExpired:
        proc.kill()
    for _ in range(10):  # 강제로 껐기 때문에 한 파일형이 스스로 지우지 못한 것. 막 꺼진 프로세스가 파일을 잠깐 더 붙들고 있어 몇 번 해 본다
        time.sleep(1)
        for folder in unpacked:
            shutil.rmtree(folder, ignore_errors=True)
        if not any(folder.exists() for folder in unpacked):
            break


def version() -> str:
    """판 번호 (pyproject.toml 의 version). 건네는 파일 이름에 넣는다."""
    return tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))["project"]["version"]


def publish(exe: Path, onefile: bool) -> Path:
    """만든 것을 dist/ 에 건넬 이름으로 내놓는다: 한 파일형은 그대로, 폴더형은 압축해서. 이름에 판 번호와 운영체제를 넣는다."""
    DIST.mkdir(parents=True, exist_ok=True)  # 다른 운영체제용·묶음 파일은 그대로 두고 이번에 만든 것만 갈아 끼운다
    stem = f"MyFinSight-{version()}-{OS_NAME}"
    if onefile:
        return Path(shutil.copy2(exe, DIST / f"{stem}{exe.suffix}"))
    kind = "zip" if sys.platform == "win32" else "gztar"  # 맥·리눅스는 실행 권한이 그대로 남는 tar.gz
    return Path(shutil.make_archive(str(DIST / f"{stem}-folder"), kind, root_dir=APP_OUT, base_dir=APP_DIR.name))


def clean_work(*parts: str) -> None:
    """중간 파일을 지운다 (build/ 아래의 parts 만 — build.py 와 release.py 를 같이 돌려도 서로의 것을 건드리지 않게)."""
    for _ in range(5):  # 막 꺼진 프로그램이 파일을 잠깐 더 붙들고 있을 수 있어 몇 번 해 본다
        for part in parts:
            shutil.rmtree(WORK / part, ignore_errors=True)
        if not any((WORK / part).exists() for part in parts):
            break
        time.sleep(1)
    if WORK.is_dir() and not any(WORK.iterdir()):
        WORK.rmdir()


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--skip-web", action="store_true", help="화면을 다시 빌드하지 않는다")
    ap.add_argument("--skip-smoke", action="store_true", help="만든 뒤 켜 보지 않는다")
    shape = ap.add_mutually_exclusive_group()
    shape.add_argument("--folder", action="store_true", help="파일 하나 대신 폴더로 만든다")
    shape.add_argument("--all", action="store_true", help="두 모양을 다 만든다")
    ap.add_argument("--keep-work", action="store_true", help="중간 파일(packaging/build/)을 지우지 않는다")
    a = ap.parse_args()
    if HAS_WEB_SOURCE and not a.skip_web:
        step("화면 빌드")
        build_web()
    step("자료 확인")
    check_inputs()
    built: dict[bool, Path] = {}
    for onefile in ([True, False] if a.all else [not a.folder]):
        name = "한 파일형" if onefile else "폴더형"
        step(f"묶기: {name} (몇 분 걸립니다)")
        exe = built[onefile] = bundle(onefile)
        step(f"내용 확인: {name}")
        check_contents(exe)
        if not a.skip_smoke:
            step(f"켜 보기: {name}")
            smoke(exe)
    step("내놓기")  # 모두 켜 본 뒤에 내놓는다 (도중에 실패하면 dist/ 의 예전 파일이 그대로 남는다)
    for onefile, exe in built.items():
        f = publish(exe, onefile)
        print(f"  {f}  ({f.stat().st_size / 1e6:.0f} MB)")
    if not a.keep_work:
        clean_work("pyinstaller", "app")
    print("\n끝. 위 파일을 건네면 됩니다 (GitHub Release 에 올리는 법: packaging/README.md).")
    return 0


if __name__ == "__main__":
    sys.exit(main())
