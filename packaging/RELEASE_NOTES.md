MyFinSight 첫 시험판입니다. 저장소를 받지 않고도 켤 수 있게 세 가지 형태로 올립니다.
시험판이라 동작이 바뀔 수 있고, 아래 「알려진 점」을 먼저 읽어 주세요.

## 무엇을 받으면 되나

| 쓰는 환경 | 받을 파일 | 필요한 것 |
|---|---|---|
| Windows, 설치 없이 | `MyFinSight-0.1.0-windows.exe` | 없음 |
| Linux (x86_64), 설치 없이 | `MyFinSight-0.1.0-linux` | 없음 |
| macOS, 또는 파이썬이 있는 PC | `MyFinSight-0.1.0-source.zip` → `run.sh` · `run.bat` | 파이썬 3.11 이상 |
| Docker | `MyFinSight-0.1.0-source.zip` → `docker compose up -d --build` | Docker |

`…-windows-folder.zip` 과 `…-linux-folder.tar.gz` 는 같은 실행 파일의 폴더형입니다. 켤 때마다 임시 폴더에 푸는 과정이 없어 몇 초 더 빨리 켜집니다.
압축을 풀고 안의 `MyFinSight` 를 실행하며, 폴더째로 두어야 합니다.

## 켜는 법

**실행 파일**
- Windows: 받은 `.exe` 를 두 번 누릅니다. "Windows의 PC 보호" 창이 뜨면 「추가 정보」 → 「실행」을 누릅니다(서명이 없는 프로그램이라 뜹니다).
- Linux: `chmod +x MyFinSight-0.1.0-linux && ./MyFinSight-0.1.0-linux`
- 검은 창(터미널)이 뜨고 몇 초 뒤 브라우저가 <http://localhost:8765> 로 열립니다. 끄려면 그 창을 닫습니다.

**스크립트** — `source.zip` 을 풀고 Windows 는 `run.bat` 을 두 번 누르고, macOS · Linux 는 터미널에서 `bash run.sh` 를 칩니다.
처음 한 번은 라이브러리를 받느라 몇 분 걸립니다.

**Docker Compose** — `source.zip` 을 풀고 `.env.example` 을 `.env` 로 복사해 두 값을 채운 뒤 `docker compose up -d --build`.

자세한 내용은 `source.zip` 안의 `README.md` 에 있습니다.

## 처음 켜면

팀 DB 주소와 OpenAI API 키를 넣는 화면이 먼저 뜹니다. 넣지 않고 「나중에 하기」로 넘기면 연습 모드로 둘러볼 수 있습니다.

- 실행 파일 · 스크립트: 넣은 값은 운영체제 보관함(Windows 자격 증명 관리자 · macOS 키체인)에 저장됩니다. 파일로는 남지 않습니다.
- Docker: 화면에서 넣지 않고 `.env` 에 적습니다.
- 리포트와 실행 기록은 프로그램 옆이 아니라 사용자 폴더(Windows 는 `%LOCALAPPDATA%\MyFinSight`)에 쌓여서, 새 판으로 바꿔도 남습니다.

이 파일들에는 팀 DB 주소나 API 키가 들어 있지 않습니다.

## 알려진 점

- **macOS 용 실행 파일은 없습니다.** 스크립트나 Docker 로 쓰거나, `source.zip` 의 안내대로 맥에서 직접 만들 수 있습니다. 맥에서는 아직 켜 보지 못했습니다.
- **Linux 실행 파일**은 Ubuntu 20.04 · Debian 11 이후(glibc 2.31 이상)에서 돕니다. 데스크톱 키링이 없는 환경에서는 화면에서 주소·키를 저장할 수 없어, 자료 폴더의 `settings.env` 에 적어야 합니다.
- **한 파일형 실행 파일**은 켤 때마다 임시 폴더에 풀고 끌 때 지웁니다. 작업 관리자로 강제 종료하거나 전원이 꺼지면 임시 폴더(약 270MB)가 남습니다.
- 팀 DB 서버가 응답하지 않으면 8초 뒤 "팀 DB에 연결하지 못했습니다"로 알리고 연습 모드로 넘어갑니다.
- 분석 실행 중에 프로그램을 끄면 그 실행은 중단됩니다.

## 확인한 환경

아래 각각에서 연습 모드로 분석 한 건을 끝까지 돌려 리포트가 나오는 것을 확인했습니다.

- Windows 10: 실행 파일(한 파일형 · 폴더형), 스크립트(`run.bat`)
- Linux x86_64 (컨테이너 안에서): 실행 파일(한 파일형 · 폴더형)은 파이썬이 없는 Ubuntu 20.04, 스크립트(`run.sh`)는 Debian 계열 파이썬 3.12, Docker Compose

확인하지 못한 것: macOS 전부, 데스크톱 화면이 있는 실제 Linux PC(브라우저 자동 열기 · 키링 저장), 실제 팀 DB · OpenAI 키를 넣은 상태의 분석.
