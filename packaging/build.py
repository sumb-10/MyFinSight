"""실행 파일을 만든다 (Windows · macOS · Linux 공통). 만든 운영체제용만 나온다 — 맥용은 맥에서 돌려야 한다.

    python packaging/build.py            # 한 파일형 (기본): MyFinSight-<판>-<운영체제>.exe  (맥은 MyFinSight-<판>-macos.zip 안에 MyFinSight.command)
    python packaging/build.py --folder   # 폴더형: MyFinSight-<판>-<운영체제>-folder.zip  (켜지는 것이 더 빠르다, 풀어서 폴더째로 둔다)
    python packaging/build.py --all      # 둘 다
    python packaging/build.py --skip-web # 화면을 다시 빌드하지 않는다 (Front/dist 를 그대로 쓴다)

순서: 화면 빌드 → 자료 확인 → 묶기 → 내용 확인 → 켜 보기 → 내놓기.
결과는 packaging/dist/<판>/ 에 건넬 이름으로 나온다. 만드는 동안 쓰는 중간 파일은 packaging/build/ 에 두었다가 끝나면 지운다
(--keep-work 를 주면 남긴다 — 묶인 내용을 들여다볼 때).
판 번호는 깃 태그가 정한다: v0.1.1 태그의 커밋에서 만들면 dist/v0.1.1/MyFinSight-0.1.1-…, 그 밖에는 dist/dev/MyFinSight-dev-…
필요한 것: pip install -e ".[analysis,packaging]", Node (화면 빌드).
.env · data/ · output/ 은 들어가지 않는다.
"""

from __future__ import annotations

import argparse
import functools
import json
import os
import shutil
import signal
import stat
import subprocess
import sys
import tempfile
import time
import urllib.request
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
HERE = ROOT / "packaging"
DIST = HERE / "dist"  # 건넬 파일만 모이는 곳. 판마다 폴더 하나 (out_dir)
VERSION_FILE = HERE / "VERSION"  # 건네는 묶음 안에만 있다: 묶음을 만들 때의 판 번호 (저장소에는 없다 — 거기서는 깃 태그를 본다)
WORK = HERE / "build"  # 만드는 동안만 쓰는 곳. 끝나면 지운다
EXE_NAME = "MyFinSight.exe" if sys.platform == "win32" else "MyFinSight"
APP_OUT = WORK / "app"  # PyInstaller 가 묶은 것을 내놓는 곳
APP_DIR = APP_OUT / "MyFinSight"  # 폴더형의 결과 (한 파일형은 APP_OUT / "onefile" / EXE_NAME 하나)
OS_NAME = {"win32": "windows", "darwin": "macos"}.get(sys.platform, "linux")
MAC_COMMAND = "MyFinSight.command"  # 맥 한 파일형이 zip 안에서 갖는 이름 (zip_mac_command)
# 건네는 묶음(source.zip)에는 화면 소스가 없고 빌드해 둔 화면(Front/dist)만 있다 → 거기서는 화면을 다시 빌드하지 않는다
HAS_WEB_SOURCE = (ROOT / "Front" / "src").is_dir()
SMOKE_PORT = 8791  # 켜 보기에 쓰는 포트 (쓰고 있는 앱의 8765 와 겹치지 않게)
# 들어가면 안 되는 것 (비밀 값 · 사용자 자료). 묶은 뒤 폴더를 훑어 하나라도 있으면 실패로 본다
FORBIDDEN = (".env", ".env.local", ".env.backup", "settings.env", "analysis_results.db", "myfinsight.db")
# pnpm 이 깔려 있지 않을 때 npx 로 불러 쓰는 판. Front/pnpm-lock.yaml 의 형식(lockfileVersion 9.0)을 읽는 판이어야 한다
PNPM_FALLBACK = "pnpm@9"


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
        install_web_libraries(env)
    # 예전 결과를 여기서 지운다. vite 8 은 이미 있는 dist 를 비우다가, 저장소 경로에 한글이 있으면(Windows) 오류 글 없이
    # 죽는다 (종료 코드 0xC0000409) — 그러면 예전 화면이 그대로 묶인다 (2026-11-23 에 11-07 화면이 묶여 발견).
    dist = ROOT / "Front" / "dist"
    shutil.rmtree(dist, ignore_errors=True)
    run([npm, "run", "build"], ROOT / "Front", env)
    if not (dist / "index.html").exists():
        raise SystemExit("화면 빌드가 결과를 내지 못했습니다.")


def install_web_libraries(env: dict[str, str]) -> None:
    """화면 라이브러리를 잠금 파일(Front/pnpm-lock.yaml)에 적힌 판 그대로 받는다. node_modules 가 없을 때만 부른다
    (처음 받은 저장소, 자동 빌드 서버). 이 프로젝트의 잠금 파일은 pnpm 것이라 npm ci 로는 받을 수 없다."""
    pnpm = shutil.which("pnpm")
    if pnpm:
        cmd = [pnpm, "install", "--frozen-lockfile"]
    else:  # pnpm 을 따로 깔지 않은 PC: Node 에 딸려 오는 npx 로 한 번 불러 쓴다
        npx = shutil.which("npx")
        if not npx:
            raise SystemExit("pnpm 도 npx 도 찾지 못했습니다. Node 를 설치해 주세요.")
        cmd = [npx, "--yes", PNPM_FALLBACK, "install", "--frozen-lockfile"]
    run(cmd, ROOT / "Front", env)


def web_problem() -> str | None:
    """빌드한 화면(Front/dist)을 그대로 써도 되는가. 되면 None, 안 되면 그 이유."""
    web = ROOT / "Front" / "dist" / "index.html"
    if not web.exists():
        return f"화면 빌드 결과가 없습니다: {web}"
    if HAS_WEB_SOURCE:  # 예전 화면을 묶지 않게: 화면 소스가 빌드 결과보다 새것이면 안 된다
        sources = [p for p in (ROOT / "Front" / "src").rglob("*") if p.is_file()] + [ROOT / "Front" / "index.html", ROOT / "Front" / "package.json"]
        newest = max(sources, key=lambda p: p.stat().st_mtime)
        if newest.stat().st_mtime > web.stat().st_mtime:
            return f"화면 빌드 결과가 소스보다 오래됐습니다 ({newest.relative_to(ROOT)} 가 더 새것)"
    return None


def check_inputs() -> None:
    problem = web_problem()
    if problem:
        raise SystemExit(f"{problem}. --skip-web 없이 다시 돌려 주세요.")


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


def _git(*args: str) -> str | None:
    """깃에 물어본 답. 깃이 없거나 실패하면 None."""
    git = shutil.which("git")
    if not git:
        return None
    r = subprocess.run([git, *args], cwd=ROOT, capture_output=True, text=True, check=False, timeout=60)  # noqa: S603
    return r.stdout.strip() if r.returncode == 0 else None


@functools.lru_cache(maxsize=1)
def version() -> str:
    """배포판의 판 번호. 깃 태그가 정한다 — 손으로 적는 곳이 없다 (pyproject.toml 의 version 은 배포판 번호가 아니다).

    - 지금 코드가 v0.1.1 같은 태그의 커밋 그대로이고 고친 것이 없으면 "0.1.1"
    - 그 밖에는 "dev": 태그가 없는 커밋이거나 커밋하지 않은 수정이 있을 때.
      그래서 낸 판과 같은 이름의 파일은 그 판의 코드에서만 나온다 (다른 내용으로 덮어쓸 수 없다)
    - 깃이 없는 곳(건네는 묶음 안)에서는 묶음을 만들 때 적어 둔 packaging/VERSION
    """
    if not (ROOT / ".git").exists():
        return (VERSION_FILE.read_text(encoding="utf-8").strip() if VERSION_FILE.exists() else "") or "dev"
    tag = _git("describe", "--tags", "--exact-match", "--match", "v[0-9]*", "HEAD")
    if not tag or _git("status", "--porcelain", "--untracked-files=no"):
        return "dev"
    return tag.removeprefix("v")


def out_dir() -> Path:
    """이 판의 결과가 모이는 곳: dist/v0.1.1/ 또는 dist/dev/. 판마다 폴더가 달라 다른 판의 파일을 건드리지 않는다."""
    return DIST / ("dev" if version() == "dev" else f"v{version()}")


def publish(exe: Path, onefile: bool) -> Path:
    """만든 것을 dist/<판>/ 에 건넬 이름으로 내놓는다: 한 파일형은 그대로, 폴더형은 압축해서. 이름에 판 번호와 운영체제를 넣는다."""
    out = out_dir()
    out.mkdir(parents=True, exist_ok=True)  # 다른 운영체제용·묶음 파일은 그대로 두고 이번에 만든 것만 갈아 끼운다
    stem = f"MyFinSight-{version()}-{OS_NAME}"
    if onefile and sys.platform == "darwin":
        return zip_mac_command(exe, out / f"{stem}.zip")
    if onefile:
        return Path(shutil.copy2(exe, out / f"{stem}{exe.suffix}"))
    kind = "zip" if sys.platform == "win32" else "gztar"  # 맥·리눅스는 실행 권한이 그대로 남는 tar.gz
    return Path(shutil.make_archive(str(out / f"{stem}-folder"), kind, root_dir=APP_OUT, base_dir=APP_DIR.name))


def zip_mac_command(exe: Path, target: Path) -> Path:
    """맥 한 파일형: 실행 파일을 MyFinSight.command 라는 이름으로 zip 에 담는다.

    맨 실행 파일을 그대로 올리면 내려받을 때 실행 권한이 빠져서, Finder 가 「문서를 열도록 설정한 응용프로그램이 없습니다」를
    띄운다 (v0.1.1, 2026-11-23 실제 맥에서 발견 — 웹 다운로드는 내용만 오고 권한은 오지 않는다). zip 은 권한을 함께 적어 두고
    맥에서 두 번 눌러 풀면 그대로 살아난다. .command 는 Finder 에서 두 번 누르면 터미널 창이 열려 실행된다 —
    Windows 판의 검은 창처럼 그 창을 닫으면 꺼진다. 권한은 만드는 곳의 파일 상태에 기대지 않고 여기서 못 박는다."""
    info = zipfile.ZipInfo(MAC_COMMAND, date_time=time.localtime(exe.stat().st_mtime)[:6])
    info.external_attr = (stat.S_IFREG | 0o755) << 16  # 위 16비트 = 유닉스 파일 종류·권한 (rwxr-xr-x)
    info.create_system = 3  # 유닉스에서 만든 항목으로 적어야 풀 때 위의 권한을 읽는다
    info.compress_type = zipfile.ZIP_DEFLATED
    target.unlink(missing_ok=True)
    with zipfile.ZipFile(target, "w") as z, exe.open("rb") as src, z.open(info, "w", force_zip64=True) as dst:
        shutil.copyfileobj(src, dst, 1024 * 1024)
    with zipfile.ZipFile(target) as z:  # 다시 열어서 확인: 이름 하나, 실행 권한
        (item,) = z.infolist()
        if item.filename != MAC_COMMAND or not (item.external_attr >> 16) & 0o111:
            raise SystemExit(f"맥용 zip 에 실행 권한이 담기지 않았습니다: {item.filename} {oct(item.external_attr >> 16)}")
    return target


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
    ap.add_argument("--print-version", action="store_true", help="만들지 않고, 지금 만들면 붙을 판 번호만 찍는다")
    a = ap.parse_args()
    if a.print_version:
        print(version())
        return 0
    step(f"판: {version()}  → {out_dir()}")
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
