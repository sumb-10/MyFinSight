# MyFinSight {VERSION}

투자 아이디어를 넣으면 종목을 고르고 과거 성과를 검증해 리포트로 보여 주는 프로그램입니다.
이 폴더로는 두 가지 방법으로 켤 수 있습니다. 설치 없이 쓰려면 이 폴더 대신 **실행 파일**을 받으세요.

| 방법 | 필요한 것 | 켜는 법 |
|---|---|---|
| 실행 파일 | 없음 | Release 에서 운영체제에 맞는 파일을 받아 실행 |
| 스크립트 | 파이썬 3.11 이상 | `run.bat` (Windows) · `bash run.sh` (macOS · Linux) |
| Docker Compose | Docker | `.env` 를 만들고 `docker compose up -d --build` |

켜지면 브라우저에서 <http://localhost:8765> 로 엽니다.

## 스크립트로 켜기

**Windows** — `run.bat` 을 두 번 누릅니다.
**macOS · Linux** — 터미널에서 이 폴더로 와서 `bash run.sh` 를 칩니다.

- 처음 한 번은 필요한 라이브러리를 이 폴더의 `.venv` 에 받느라 몇 분 걸립니다. 다음부터는 바로 켜집니다.
- 켜지면 브라우저가 열립니다. 끄려면 창을 닫거나 `Ctrl+C` 를 누릅니다.
- 팀 DB 주소와 OpenAI 키는 처음 뜨는 화면(연결 설정)에서 넣습니다. 넣지 않아도 연습 모드로 둘러볼 수 있습니다.
- 넣은 값은 운영체제 보관함(Windows 자격 증명 관리자 · macOS 키체인)에 저장됩니다. 파일로는 남지 않습니다.

## Docker Compose 로 켜기

1. `.env.example` 을 `.env` 로 복사하고 `DATABASE_URL` 과 `OPENAI_API_KEY` 를 채웁니다.
2. `docker compose up -d --build` (처음에는 몇 분 걸립니다)
3. 브라우저에서 <http://localhost:8765>

- 컨테이너에는 운영체제 보관함이 없어서, 주소와 키는 `.env` 로만 넣습니다. 화면의 연결 설정에는 「환경변수(.env)로 설정됨」으로 보이고 거기서 바꿀 수 없습니다. 바꾸려면 `.env` 를 고치고 `docker compose up -d` 를 다시 칩니다.
- `.env` 없이 켜도 됩니다 (연습 모드).
- 끄기 `docker compose down` · 로그 `docker compose logs -f` · 리포트까지 지우기 `docker compose down -v`
- 기본으로는 이 컴퓨터에서만 열립니다. 다른 컴퓨터에서 열게 하려면 `compose.yaml` 의 `ports` 주석을 보세요. 로그인 기능이 없으니 믿을 수 있는 망에서만 여세요.

## 자료가 쌓이는 곳

리포트·투자조건·실행 기록은 이 폴더가 아니라 아래에 쌓입니다. 새 판으로 바꿔도 그대로 남습니다.

| 방법 | 자료 폴더 |
|---|---|
| 스크립트 · 실행 파일 (Windows) | `%LOCALAPPDATA%\MyFinSight` |
| 스크립트 · 실행 파일 (macOS) | `~/Library/Application Support/MyFinSight` |
| 스크립트 · 실행 파일 (Linux) | `~/.local/share/MyFinSight` |
| Docker Compose | 볼륨 `myfinsight_myfinsight-data` |

스크립트 버전과 실행 파일 버전은 같은 자료 폴더를 씁니다. 번갈아 써도 리포트와 연결 설정이 이어집니다.

## 옵션

```
run.bat --port 9000          포트 바꾸기 (기본 8765)
run.bat --home D:\mfs        자료 폴더 바꾸기
run.bat --no-browser         브라우저를 열지 않기
```

`run.sh` 도 같습니다. Docker 는 `.env` 에 `MYFINSIGHT_PORT=9000` 을 적습니다.

## 잘 안 될 때

- **파이썬을 찾지 못했다고 나온다** — <https://www.python.org/downloads/> 에서 3.11 이상을 설치합니다. Windows 는 설치 화면에서 "Add python.exe to PATH" 를 체크합니다.
- **8765 포트를 다른 프로그램이 쓰고 있다** — 다음 번호로 자동으로 켜지고 그 주소를 알려 줍니다. `--port` 로 직접 정할 수도 있습니다.
- **Linux 에서 주소·키를 화면에서 저장할 수 없다고 나온다** — 데스크톱 키링(GNOME Keyring 등)이 없는 환경입니다. 자료 폴더에 `settings.env` 를 만들어 `DATABASE_URL=…`, `OPENAI_API_KEY=…` 두 줄을 적으면 됩니다.
- **맥에서 「'MyFinSight.command'을(를) 열 수 없음」이 뜬다** — 서명이 없는 프로그램이라 처음 한 번 뜹니다. 그 창을 닫고 시스템 설정 → 개인정보 보호 및 보안 → 아래쪽의 「그래도 열기」를 누른 뒤 다시 두 번 누릅니다.
- **맥에서 「문서를 열도록 설정한 응용프로그램이 없습니다」가 뜬다** — v0.1.1 의 `-macos` 파일입니다 (내려받으면서 실행 권한이 빠짐). v0.1.2 이후의 `-macos.zip` 을 받거나, 터미널에서 `chmod +x MyFinSight-0.1.1-macos` 를 한 뒤 엽니다.
- **로그** — 자료 폴더의 `logs/` 에 있습니다.

## 맥용 실행 파일을 직접 만들기

Releases 에 있는 맥용 실행 파일(`-macos.zip`)은 Apple Silicon 용입니다. 인텔 맥이거나 직접 만들고 싶으면 맥에서 이 폴더로 만들 수 있습니다.

```
bash run.sh --help                       # 먼저 한 번 켜서 .venv 에 라이브러리를 받는다
.venv/bin/python -m pip install "pyinstaller>=6.10"
.venv/bin/python packaging/build.py      # packaging/dist/ 아래에 MyFinSight-{VERSION}-macos.zip 이 나온다
```
