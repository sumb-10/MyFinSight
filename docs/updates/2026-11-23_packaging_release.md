# 배포판 세 가지와 v0.1.0, 팀 DB 접속 시간제한 (2026-11-23)

저장소를 받지 않고 MyFinSight 를 켤 수 있게 실행 파일 · 스크립트 · Docker Compose 세 가지로 묶었고, 첫 시험판 v0.1.0 을 GitHub Release 에 올렸다.
브랜치 `feature/packaging-exe`, 커밋 `58f297a`(접속 시간제한) · `ec8e5f7`(패키징) · `2570c47`(릴리스 노트), PR 34. Release `v0.1.0` = main `76af6bf`.
만드는 법은 `packaging/README.md`, 받는 사람용 안내는 `packaging/source-zip/README.md`.
각 항목은 "무엇을 / 왜 / 어디를(파일) / 어떻게 확인했나"를 적는다.

## 1. 문제

- 쓰려면 저장소를 받고 파이썬 · Node 를 깔고 서버 · 일꾼 · 화면을 창 세 개로 켜야 했다.
- 리포트와 실행 기록이 저장소 폴더(`data/`, `output/`)에 쌓여서, 프로그램을 다른 곳에 두면 따라가지 않았다.
- 저장된 팀 DB 주소의 서버가 응답하지 않으면 약 10분 동안 앱 전체가 멈췄다. 접속 한 번에 130초를 기다리고 네 번 시도했고, 그동안 `/health` 가 잠금을 쥐고 있었다.

## 2. 결정

- **시작점 하나**(`packaging/launcher.py`)를 세 배포판이 같이 쓴다. 서버에 빌드한 화면을 얹고, 자기 자신을 `--worker` 로 한 번 더 켜고, 브라우저를 연다.
- **자료는 사용자 폴더에**: Windows `%LOCALAPPDATA%\MyFinSight`, macOS `~/Library/Application Support/MyFinSight`, Linux `~/.local/share/MyFinSight`. 프로그램이 있는 곳에는 쓰지 않는다. 새 판으로 바꿔도 리포트가 남는다.
- **주소는 `http://localhost:8765` 고정**. 화면이 브라우저에 남기는 기록이 `주소:포트`마다 따로라서다. 이미 켜져 있으면 그 주소만 연다.
- **실행 파일은 한 파일형이 기본** (사용자 결정: 받는 사람이 쓰기 쉬워야 한다). 폴더형도 같이 올린다 — 켤 때 임시 폴더에 푸는 과정이 없어 몇 초 빠르다.
- **Linux 실행 파일은 Docker 안에서 만든다** (glibc 2.31 바탕 → Ubuntu 20.04 · Debian 11 이후에서 돈다).
- **스크립트와 Docker 는 묶음 하나**(`source.zip`): 서버 코드 + 빌드한 화면 + `run.bat` · `run.sh` + `Dockerfile` · `compose.yaml`. 받는 사람은 Node 가 필요 없다.
- **비밀 값은 넣지 않는다**: `.env`, 내 리포트, 수집기용 키. 빌드가 묶은 내용을 훑어 있으면 멈춘다. 주소와 키는 받는 사람이 화면에서 넣는다 (`2026-11-23_connection_setup.md`).
- **접속 시간제한은 화면 서버에만**: 공용 `backend/db` 는 건드리지 않고 분석 쪽 입구(`common/dbconn.py`)에서 한 번 두드려 본다. 일꾼 · CLI 의 긴 재시도는 그대로 둔다 (실행 도중 잠깐 끊긴 것은 기다리는 편이 낫다).

## 3. 수정

### 패키징 (`packaging/`, 신규)

- **`launcher.py`**: 사용자 폴더 정하기, 환경변수 맞추기, 화면 얹기, 일꾼 켜고 죽으면 다시 켜기, 한 번만 켜지게, 종료 신호에 뒷정리.
- **`myfinsight.spec`**: 실행 파일에 넣을 것 (프롬프트, 연습 모드 답, 참조 자료, 화면, 보관함 · DB 드라이버, 시간대 자료).
- **`build.py`**: 화면 빌드 → 묶기 → 내용 확인 → 켜 보기. `--all` 로 두 모양.
- **`release.py`**: `source.zip` 만들기, `--linux` 로 Linux 실행 파일.
- **`source-zip/`**: 묶음에만 들어가는 파일 (`run.bat`, `run.sh`, `Dockerfile`, `compose.yaml`, 안내문).
- **`RELEASE_NOTES.md`**: 판마다 절 하나. 그 절이 GitHub Release 의 설명이 된다.
- `pyproject.toml` 에 `packaging` 묶음(`pyinstaller`), `.gitignore` 에 `packaging/dist/` · `packaging/build/`.

### 서버

- **`common/dbconn.py`**: `with_timeout`(접속 8초), `knock`(한 번 접속해 보기), 실패를 30초 기억. `default_repo`(화면 서버만 씀)가 먼저 거친다.
- **`connections.py`**: 연결 설정의 접속 확인도 같은 `knock` 을 쓴다.

## 4. 알아 둘 것

- 기존 실행 방식(`uvicorn` + 일꾼 + `pnpm dev`)에는 영향이 없다.
- `packaging/` 에 `__init__.py` 를 두면 안 된다. 같은 이름의 라이브러리를 pip · pytest · PyInstaller 가 쓴다.
- macOS 실행 파일은 없다. 맥에서만 만들 수 있다. 맥에서는 스크립트나 Docker 로 쓸 수 있지만 켜 본 적은 없다.
- 서명이 없어서 Windows 에서 처음 켤 때 "PC 보호" 창이 뜬다.
- 한 파일형은 켤 때마다 임시 폴더에 약 270MB 를 풀고 끌 때 지운다. 강제 종료하면 그 폴더가 남는다.
- Linux · macOS 는 서버가 꺼진 뒤 1분쯤 그 포트를 붙들고 있다. 런처는 uvicorn 과 같은 조건으로 포트를 봐서, 껐다 바로 켜도 주소가 밀리지 않는다.
- Windows 에서 저장소 경로에 한글이 있으면 vite 가 이미 있는 `Front/dist` 를 비우다 오류 글 없이 죽는다. `build.py` 는 먼저 지우고 빌드한다.

## 5. 확인

- 각 환경에서 연습 모드로 분석 한 건을 끝까지 돌려 리포트가 나오는 것을 봤다: Windows 10(실행 파일 두 모양, `run.bat`), 파이썬 없는 Ubuntu 20.04 컨테이너(Linux 실행 파일 두 모양), Debian 파이썬 3.12 컨테이너(`run.sh`), Docker Compose.
- 응답 없는 DB 주소: 10분 → 처음 8초, 그 뒤 30초 동안은 즉시. 화면은 3초 안에 "팀 DB에 연결하지 못했습니다".
- 게시된 v0.1.0 의 Windows 실행 파일을 내려받아 분석 한 건 실행.
- 분석 테스트 638 통과 (원래 불안정한 `test_waves_and_parallel_stage_failure` 1개 제외).
- 확인하지 못한 것: macOS 전부, 데스크톱이 있는 실제 Linux PC(브라우저 열기 · 키링), 실제 팀 DB · OpenAI 키를 넣은 분석.
