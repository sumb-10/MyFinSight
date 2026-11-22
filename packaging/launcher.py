"""MyFinSight 를 한 번에 켜는 시작점: 서버(API + 화면) 하나와 분석 일꾼 하나를 띄우고 브라우저를 연다.

쓰는 곳
- 실행 파일 (PyInstaller, packaging/myfinsight.spec): MyFinSight 를 누르면 이 파일의 main() 이 돈다
- 개발 PC 에서 그대로: python packaging/launcher.py --home <폴더>   (화면은 Front/dist — 먼저 npm run build)

하는 일
1. 사용자 폴더(home)를 정한다 — 리포트·실행 기록·로그가 여기에 쌓인다. 프로그램 폴더에는 아무것도 쓰지 않는다
2. 서버·일꾼이 읽는 환경변수를 그 폴더로 맞춘다 (이미 정해져 있으면 그대로 둔다)
3. 이미 켜져 있으면 그 주소로 브라우저만 열고 끝낸다
4. 일꾼을 "같은 프로그램 + --worker" 로 한 번 더 켠다 (죽으면 다시 켠다)
5. 서버에 화면 파일을 얹어 127.0.0.1 의 정해진 포트에서 켠다

이 폴더(packaging/)에 __init__.py 를 두지 말 것: 같은 이름의 라이브러리(packaging)를 pip · pytest · PyInstaller 가 쓴다.
backend 의 모듈은 환경변수를 맞춘 뒤에 불러와야 해서, 이 파일 맨 위에서는 표준 라이브러리만 불러온다.
"""

from __future__ import annotations

import argparse
import json
import logging
import logging.handlers
import multiprocessing
import os
import signal
import socket
import subprocess
import sys
import threading
import time
import urllib.request
import webbrowser
from pathlib import Path

APP = "MyFinSight"
DEFAULT_PORT = 8765  # 고정한다: 화면이 브라우저에 남기는 기록은 주소:포트마다 따로라, 포트가 바뀌면 처음 켠 것처럼 보인다
PORT_TRIES = 20  # 그 포트를 다른 프로그램이 쓰고 있으면 다음 번호로
SERVER_FILE = "server.json"  # 켜져 있는 서버의 pid·주소 (두 번 눌렀을 때 새로 켜지 않게)
WORKER_RESTARTS = 5
WORKER_LOCKED = 2  # 일꾼이 "다른 일꾼이 이미 돌고 있음"으로 끝낼 때의 종료 코드 (executor/worker.py)
FROZEN = bool(getattr(sys, "frozen", False))
HERE = Path(__file__).resolve()  # 지금 구해 둔다: 뒤에서 작업 폴더를 사용자 폴더로 옮기면 상대 경로가 달라진다


# ───────────────────────── 폴더 ─────────────────────────
def default_home() -> Path:
    """사용자 폴더. MYFINSIGHT_HOME 으로 바꿀 수 있다 (USB 에 담아 쓰기 · 시험)."""
    given = os.environ.get("MYFINSIGHT_HOME")
    if given:
        return Path(given).expanduser()
    if sys.platform == "win32":
        return Path(os.environ.get("LOCALAPPDATA") or Path.home() / "AppData" / "Local") / APP
    if sys.platform == "darwin":
        return Path.home() / "Library" / "Application Support" / APP
    return Path(os.environ.get("XDG_DATA_HOME") or Path.home() / ".local" / "share") / APP


def resource_root() -> Path:
    """프로그램에 든 읽기 전용 자료의 뿌리. 실행 파일이면 풀린 폴더(_internal), 아니면 저장소 폴더."""
    return Path(getattr(sys, "_MEIPASS", HERE.parents[1]))


def web_dir() -> Path:
    """화면 파일(vite build 결과). 실행 파일에는 web/ 로 들어 있다."""
    given = os.environ.get("MYFINSIGHT_WEB_DIR")
    if given:
        return Path(given)
    return resource_root() / "web" if FROZEN else resource_root() / "Front" / "dist"


def prepare(home: Path) -> None:
    """사용자 폴더를 만들고, 서버·일꾼이 그 폴더를 쓰게 환경변수를 맞춘다. 이미 정해진 값은 건드리지 않는다.

    .env 는 여기서도 읽기 전용이다: home/settings.env 가 있으면 읽고(없어도 된다), 앱이 만들거나 고치지 않는다.
    팀 DB 주소와 API 키는 화면에서 넣어 운영체제 보관함에 둔다 (backend/analysis/secret_store.py).
    """
    for sub in ("store", "output", "logs"):
        (home / sub).mkdir(parents=True, exist_ok=True)
    defaults = {
        "MYFINSIGHT_ENV_FILE": str(home / "settings.env"),  # 실행한 폴더에 우연히 있는 .env 를 읽지 않게 자리를 못 박는다
        "ANALYSIS_STORE_DIR": str(home / "store"),
        "ANALYSIS_OUTPUT_DIR": str(home / "output"),
        "ANALYSIS_RESULTS_DB": "sqlite:///" + (home / "analysis_results.db").as_posix(),
    }
    for key, value in defaults.items():
        os.environ.setdefault(key, value)
    os.chdir(home)  # 남아 있는 상대 경로(data/…)가 프로그램 폴더가 아니라 사용자 폴더를 가리키게


# ───────────────────────── 이미 켜져 있나 · 포트 ─────────────────────────
def healthy(url: str, timeout: float = 1.5) -> bool:
    """그 주소에서 이 앱의 서버가 답하는가. 팀 DB 가 연결 전이면 응답의 ok 는 false 이므로 ok 를 보지 않는다 (서버는 떠 있다)."""
    try:
        with urllib.request.urlopen(f"{url}/api/v1/health", timeout=timeout) as r:  # noqa: S310 — 이 컴퓨터의 주소만 부른다
            return r.status == 200 and "api_version" in json.loads(r.read())
    except Exception:  # noqa: BLE001 — 안 켜져 있으면 어떤 오류든 "없음"
        return False


def running_instance(home: Path) -> str | None:
    """이 사용자 폴더로 이미 켜져 있는 서버의 주소. 없으면 None (기록만 남고 죽은 경우도 None)."""
    try:
        url = json.loads((home / SERVER_FILE).read_text(encoding="utf-8"))["url"]
    except (OSError, ValueError, KeyError):
        return None
    return url if healthy(url) else None


def pick_port(host: str, preferred: int) -> int:
    """preferred 부터 차례로, 비어 있는 첫 포트."""
    for port in range(preferred, preferred + PORT_TRIES):
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            # 리눅스·맥은 서버가 꺼진 뒤 1분쯤 그 포트를 '정리 중'으로 잡아 둔다. uvicorn 은 이 옵션으로 그걸 무시하고 잡으므로
            # 여기서도 같은 조건으로 본다 (안 그러면 껐다 바로 켤 때 주소가 다음 포트로 밀린다 — 2026-11-23 리눅스 빌드에서 확인).
            # Windows 에서는 같은 옵션이 '쓰이는 포트도 겹쳐 잡기'라서 켜면 안 된다
            if sys.platform != "win32":
                s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            try:
                s.bind((host, port))
            except OSError:
                continue
            return port
    raise SystemExit(f"{preferred}~{preferred + PORT_TRIES - 1} 포트가 모두 쓰이고 있어 켤 수 없습니다.")


# ───────────────────────── 알림 · 로그 ─────────────────────────
def say(text: str) -> None:
    """검은 창에 보이는 안내. 창 없이 켠 경우(stdout 없음)에는 로그에만 남긴다."""
    logging.getLogger("launcher").info(text)
    if sys.stdout is not None:
        try:
            print(text, flush=True)
        except (OSError, UnicodeError):
            pass


def setup_logging(home: Path, name: str) -> None:
    handler = logging.handlers.RotatingFileHandler(home / "logs" / f"{name}.log", maxBytes=5_000_000, backupCount=3, encoding="utf-8")
    handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(name)s: %(message)s"))
    logging.basicConfig(level=logging.INFO, handlers=[handler], force=True)


# ───────────────────────── 일꾼 ─────────────────────────
def worker_command() -> list[str]:
    """자기 자신을 일꾼으로 다시 켜는 명령. 실행 파일이면 그 파일, 아니면 파이썬 + 이 파일."""
    base = [sys.executable] if FROZEN else [sys.executable, str(HERE)]
    return [*base, "--worker", "--parent", str(os.getpid())]


def keep_worker(home: Path, stop: threading.Event, holder: dict[str, subprocess.Popen]) -> None:
    """일꾼을 켜 두고, 죽으면 다시 켠다. 다른 일꾼이 이미 돌고 있어서 끝난 것(코드 2)이면 다시 켜지 않는다."""
    log = logging.getLogger("launcher")
    restarts = 0
    while not stop.is_set():
        with open(home / "logs" / "worker.out", "ab") as out:
            proc = subprocess.Popen(worker_command(), stdout=out, stderr=subprocess.STDOUT, stdin=subprocess.DEVNULL)  # noqa: S603
            holder["proc"] = proc
            log.info("worker started pid=%s", proc.pid)
            while proc.poll() is None and not stop.is_set():
                time.sleep(0.5)
        if stop.is_set():
            return
        code = proc.returncode
        log.warning("worker exited code=%s", code)
        if code == WORKER_LOCKED or restarts >= WORKER_RESTARTS:
            say("분석 일꾼이 꺼졌습니다. 분석을 실행하려면 프로그램을 다시 켜 주세요. (logs/worker.log)")
            return
        restarts += 1
        stop.wait(3)


def watch_parent(pid: int) -> None:
    """서버가 사라지면 일꾼도 끝낸다 (작업 관리자에서 서버만 끈 경우에 일꾼이 혼자 남지 않게)."""
    from backend.analysis.executor.queue import pid_alive

    while pid_alive(pid):
        time.sleep(2)
    os._exit(0)


def run_worker(home: Path, parent: int | None) -> int:
    setup_logging(home, "worker")
    from backend.analysis.executor import worker

    if parent:
        threading.Thread(target=watch_parent, args=(parent,), name="watch-parent", daemon=True).start()
    return worker.main([])


# ───────────────────────── 서버 ─────────────────────────
def build_app():  # noqa: ANN201 — FastAPI 는 환경변수를 맞춘 뒤에 불러온다
    """API 앱에 화면 파일을 얹는다. 화면은 주소 뒤 #/… 로 길을 찾으므로 "/" 하나만 내주면 된다."""
    from starlette.staticfiles import StaticFiles

    from backend.analysis.api.app import app

    class Web(StaticFiles):
        async def get_response(self, path: str, scope):  # noqa: ANN001, ANN202
            response = await super().get_response(path, scope)
            if not path.startswith("assets"):  # index.html 은 매번 새로 확인 (새 판을 깔았는데 옛 화면이 뜨지 않게). assets/ 는 파일 이름에 내용 해시가 들어 있다
                response.headers["Cache-Control"] = "no-cache"
            return response

    web = web_dir()
    if not (web / "index.html").exists():
        raise SystemExit(f"화면 파일이 없습니다: {web}  (Front 에서 npm run build 를 먼저 돌려 주세요)")
    app.mount("/", Web(directory=web, html=True), name="web")
    return app


def announce(url: str, open_browser: bool) -> None:
    """서버가 답하기 시작하면 주소를 알리고 브라우저를 연다."""
    for _ in range(240):
        if healthy(url, timeout=1):
            break
        time.sleep(0.5)
    say(f"\n{APP} 을(를) 켰습니다.  주소: {url}")
    say("끄려면 이 창을 닫으세요.\n")
    if open_browser:
        webbrowser.open(url)


def _stop(_signum: int, _frame: object) -> None:
    raise SystemExit(0)


def run_server(home: Path, host: str, port: int, open_browser: bool) -> int:
    setup_logging(home, "server")
    existing = running_instance(home)
    if existing:
        say(f"{APP} 이(가) 이미 켜져 있습니다: {existing}")
        if open_browser:
            webbrowser.open(existing)
        return 0

    import uvicorn

    wanted, port = port, pick_port(host, port)
    if port != wanted:
        say(f"{wanted} 포트를 다른 프로그램이 쓰고 있어 {port} 포트로 켭니다. (화면의 '처음 본 것' 기록은 포트마다 따로입니다)")
    url = f"http://{'127.0.0.1' if host in ('0.0.0.0', '::') else host}:{port}"  # noqa: S104
    say(f"{APP} 을(를) 켜는 중입니다…  (자료 폴더: {home})")
    app = build_app()

    stop = threading.Event()
    holder: dict[str, subprocess.Popen] = {}
    threading.Thread(target=keep_worker, args=(home, stop, holder), name="keep-worker", daemon=True).start()
    threading.Thread(target=announce, args=(url, open_browser), name="announce", daemon=True).start()
    server_file = home / SERVER_FILE
    server_file.write_text(json.dumps({"pid": os.getpid(), "url": url}), encoding="utf-8")
    # kill · docker stop 이 보내는 종료 신호를 Ctrl+C 처럼 다룬다 (아래 finally 가 돌아 일꾼을 끄고 기록을 지운다).
    # uvicorn 은 스스로 정리한 뒤 받은 신호를 원래 처리기에 다시 넘기는데, 기본 처리기는 그 자리에서 프로세스를 끝내 finally 가 돌지 않는다
    signal.signal(signal.SIGTERM, _stop)
    try:
        # 접속 기록은 남기지 않는다: 화면이 상태를 몇 초마다 물어서 로그가 그 줄로 가득 찬다 (오류는 그대로 남는다)
        uvicorn.run(app, host=host, port=port, log_config=None, access_log=False)
    finally:
        stop.set()
        proc = holder.get("proc")
        if proc and proc.poll() is None:
            proc.terminate()
            try:
                proc.wait(timeout=10)
            except subprocess.TimeoutExpired:
                proc.kill()
        server_file.unlink(missing_ok=True)
    return 0


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog=APP)
    ap.add_argument("--home", default=None, help="자료 폴더 (기본: 운영체제의 사용자 폴더 아래 MyFinSight)")
    ap.add_argument("--host", default="127.0.0.1", help="듣는 주소. 기본은 이 컴퓨터에서만 (127.0.0.1)")
    ap.add_argument("--port", type=int, default=DEFAULT_PORT)
    ap.add_argument("--no-browser", action="store_true", help="브라우저를 열지 않는다")
    ap.add_argument("--worker", action="store_true", help=argparse.SUPPRESS)  # 런처가 자기 자신을 일꾼으로 켤 때만 쓴다
    ap.add_argument("--parent", type=int, default=None, help=argparse.SUPPRESS)
    a = ap.parse_args(argv)
    home = Path(a.home).expanduser().resolve() if a.home else default_home().resolve()
    os.environ["MYFINSIGHT_HOME"] = str(home)  # 일꾼도 같은 폴더를 쓴다
    prepare(home)
    if not FROZEN and str(resource_root()) not in sys.path:
        sys.path.insert(0, str(resource_root()))  # python packaging/launcher.py 로 켰을 때 backend 를 찾게
    if a.worker:
        return run_worker(home, a.parent)
    return run_server(home, a.host, a.port, not a.no_browser)


if __name__ == "__main__":
    multiprocessing.freeze_support()  # 실행 파일에서 라이브러리가 자식 프로세스를 띄울 때 런처가 다시 켜지지 않게
    if sys.stdout is not None and hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(errors="replace")  # 한글 코드 페이지가 아닌 창에서도 글자 때문에 죽지 않게
    sys.exit(main())
