# Windows 호환 수정 (2026-10-31)

분석 서비스(서버·일꾼)가 Windows 에서도 켜지도록 고쳤다. 라운드(시나리오 실행 → 채점 → 수정) 와는 별개의 환경 수정이며,
맥·리눅스 쪽 동작은 바꾸지 않았다. 각 항목은 "무엇을 / 왜 / 어디를(파일) / 어떻게 확인했나"를 적는다.

## 1. 문제

- `backend/analysis/common/store.py`, `backend/analysis/executor/worker.py` 가 `fcntl.flock` 으로 파일을 잠근다. `fcntl` 은
  맥·리눅스 전용 모듈이라 Windows 에서는 서버(`uvicorn backend.analysis.api.app:app`)와 일꾼 둘 다
  `ModuleNotFoundError: fcntl` 로 시작하지 못했다. (`docs/구현보고서/common_구현보고서.md` 7절에 "플랫폼 의존" 으로 적혀 있던 한계)
- `backend/analysis/executor/queue.py` 의 `pid_alive()` 가 `os.kill(pid, 0)` 으로 생존을 확인한다. Windows 에서 신호 0 은
  `CTRL_C_EVENT` 라서 생존 확인이 아니라 Ctrl+C 전송이 된다. `/health` 와 `recover_stale()` 이 콘솔에 Ctrl+C 를 보내거나,
  살아 있는 일꾼을 죽은 것으로 판정할 수 있었다. (에러 없이 오작동하는 쪽이라 1번과 같이 고쳐야 했다)
- 테스트 세 곳이 `Path.read_text()` 를 인코딩 없이 불러 OS 기본 코덱으로 읽는다. 한국어 Windows 는 cp949 라 한글이 든
  JSON 에서 `UnicodeDecodeError`. (`test_pipeline_e2e.py::test_validation_and_bundle` 이 실제로 실패)

## 2. 수정 (`backend/analysis/common/filelock.py` 신설, `store.py`, `worker.py`, `queue.py`)

- **`common/filelock.py` (신규)**: `lock(fh, blocking=True)` / `unlock(fh)` 두 함수. 맥·리눅스는 기존과 같은 `fcntl.flock`,
  Windows 는 `msvcrt.locking`. 호출하는 쪽은 OS 를 모른다.
  - Windows 는 잠근 바이트를 다른 프로세스가 **읽지도 못한다**(flock 은 읽기를 막지 않음). `worker.lock` 은 잠금과 pid 기록을
    한 파일이 겸하므로, pid 가 적힌 앞부분을 피해 **파일 끝 너머 1바이트(`1 << 30`)** 만 잠근다. 그래서 `/health` 가 잠긴 동안에도
    pid 를 읽는다.
  - Windows 의 기다리는 잠금(`LK_LOCK`)은 1초 간격 10번 뒤 포기하므로, flock 처럼 끝까지 기다리도록 비차단 잠금을 50ms 간격으로
    다시 시도한다.
- **`common/store.py`**: `JsonStore.locked()` 가 `fcntl` 대신 `filelock.lock()/unlock()` 사용. `import fcntl` 제거.
  이 메서드를 쓰는 12곳(`m1_request/dialog.py`, `executor/queue.py`, `ProfileStore`, `RunIndex`)은 바뀌지 않는다.
- **`executor/worker.py`**: `main()` 의 `worker.lock` 단일 실행 잠금을 `filelock.lock(fh, blocking=False)` 로. `import fcntl` 제거.
  잠금 파일에 pid 를 적는 구조(`"a+"` 로 열고 잠근 뒤 truncate) 는 그대로.
- **`executor/queue.py`**: `pid_alive()` 에 Windows 분기. `_pid_alive_nt()` 가 `OpenProcess(PROCESS_QUERY_LIMITED_INFORMATION)` +
  `GetExitCodeProcess == STILL_ACTIVE` 로 확인(ctypes). 열 권한이 없으면(`ERROR_ACCESS_DENIED`) 살아 있는 것으로 본다(POSIX 의 EPERM 과 같은 취급).
- **테스트**: `backend/tests/analysis/test_pipeline_e2e.py`, `test_foundations.py`, `backend/tests/test_descriptor.py` 의
  `read_text()` 에 `encoding="utf-8"`. 쓰는 쪽(`jsonio`, `store`, `descriptor`, `llm`)은 이미 UTF-8.
- **문서**: `docs/구현보고서/common_구현보고서.md` 의 잠금 설명 2곳, `executor_구현보고서.md` 의 `pid_alive` 설명.

## 3. 바꾸지 않은 것 / 선택지

- 맥·리눅스 코드 경로는 `fcntl.flock`, `os.kill(pid, 0)` 호출이 글자 그대로 같다. 팀원 환경에서 다시 설치할 것도 없다(새 의존성 없음).
- `filelock` 라이브러리(virtualenv·huggingface_hub 가 쓰는 표준) 로 가는 길도 있다. 다만 그 라이브러리는 0번 바이트를 잠그고 해제 시
  파일을 지우므로 `worker.lock` 의 pid 를 `worker.pid` 로 분리하고 `/health`(`api/routers/meta.py`) 도 같이 고쳐야 한다.
  이번에는 범위를 "최소 수정으로 Windows 에서 켜지게" 로 잡아 직접 만든 얇은 모듈로 갔다. 나중에 바꾸더라도 `JsonStore.locked()`
  뒤에 숨어 있어 호출부는 그대로다.
- `howtouse.md`, `README.md` 의 실행 명령은 아직 맥 기준(`source ~/.venvs/...`). Windows(PowerShell) 절은 별도 작업.

## 4. 확인 (Windows 10, Python 3.13, 가상환경 `.venv`)

- `filelock.py` 단독 2프로세스 테스트: 잠긴 동안 다른 프로세스가 pid 읽기 OK / 비차단 잠금은 즉시 `OSError` / 차단 잠금은 상대가
  놓을 때까지(3초) 기다렸다 획득.
- `_pid_alive_nt`: 자기 자신 True, 실행 중 자식 True, 종료된 자식 False, 없는 pid False, 권한 없는 시스템 프로세스(pid 4) True.
- `python -m pytest backend/tests/analysis`: 수정 전 101 passed / 1 failed(인코딩) → 수정 후 전부 통과. `test_descriptor.py` 도 통과.
- 연습(stub) 모드로 서버 + 일꾼 기동(`howtouse.md` 6절의 가짜 DB): `/health` → `"ok": true, "worker": {"alive": true}`.
  일꾼을 하나 더 띄우면 `another worker holds the lock; exiting`(exit 2). `worker.lock` 내용은 일꾼 pid 그대로.
- API 로 분석 1건: 프로필 저장 → 아이디어 → 질문 답 → 확정 → `queued` → `running`(`/health` 에 `running_run_id`) → 10초 뒤 `success`,
  `/reports/{run_id}` 200, 7개 부분. 끝난 뒤 `.locks/runs.lock` 등 잠금 파일은 빈 파일로 남는다(정상).
- 맥·리눅스에서는 직접 돌리지 않았다. PR 리뷰 때 맥에서 `pytest backend/tests/analysis` 한 번 확인 필요.
