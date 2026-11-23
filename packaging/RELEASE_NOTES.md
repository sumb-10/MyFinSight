# 릴리스 노트

## v0.1.2 — 2026-11-23 (시험판)

### 바뀐 것

- macOS 실행 파일을 zip 으로 냅니다. 풀어서 `MyFinSight.command` 를 두 번 누르면 터미널 창이 열리며 켜집니다
  — v0.1.1 의 맥용 파일은 내려받으면서 실행 권한이 빠져 "문서를 열도록 설정한 응용프로그램이 없습니다"가 떴습니다
- 맥·리눅스에서 터미널 창을 닫아 끌 때도 분석 일꾼을 정리하고 끕니다

### 받을 파일

| 환경 | 파일 | 켜는 법 |
|---|---|---|
| Windows | `MyFinSight-0.1.2-windows.exe` | 두 번 누르기 |
| macOS (Apple Silicon) | `MyFinSight-0.1.2-macos.zip` | 두 번 눌러 풀고 `MyFinSight.command` 두 번 누르기 |
| Linux x86_64 | `MyFinSight-0.1.2-linux` | `chmod +x` 한 뒤 실행 |
| 파이썬 3.11 이상이 있는 PC | `MyFinSight-0.1.2-source.zip` | `bash run.sh` · `run.bat` |
| Docker | `MyFinSight-0.1.2-source.zip` | `docker compose up -d --build` |

켜지면 브라우저가 <http://localhost:8765> 로 열립니다. 끄려면 함께 뜬 검은 창(맥은 터미널 창)을 닫습니다.
이름에 `-folder` 가 붙은 파일은 같은 실행 파일의 폴더형으로, 압축을 풀어 쓰고 조금 더 빨리 켜집니다.
자세한 안내: [README](https://github.com/sumb-10/MyFinSight/blob/v0.1.2/packaging/source-zip/README.md)

### 주의사항

- macOS 에서 처음 켤 때 "열 수 없음" 창이 뜹니다 (서명이 없는 프로그램). 창을 닫고 시스템 설정 → 개인정보 보호 및 보안 → 「그래도 열기」를 누른 뒤 다시 엽니다.
- Windows 에서 처음 켤 때 "Windows의 PC 보호" 창이 뜹니다. 「추가 정보」 → 「실행」을 누릅니다.
- Linux 실행 파일은 Ubuntu 20.04 · Debian 11 이후에서 돕니다. 데스크톱 키링이 없는 환경에서는 화면에서 주소·키를 저장할 수 없습니다.
- 한 파일형 실행 파일을 강제로 종료하면 임시 폴더(약 270MB)가 남습니다.

## v0.1.1 — 2026-11-23 (시험판)

### 바뀐 것

- 종목 목록(종목 사전)을 팀 DB에 연결할 때 스스로 만듭니다 — 지수 구성종목이 바뀌어도 새 버전을 받을 필요가 없음
- macOS(Apple Silicon)용 실행 파일 추가

### 받을 파일

| 환경 | 파일 | 켜는 법 |
|---|---|---|
| Windows | `MyFinSight-0.1.1-windows.exe` | 두 번 누르기 |
| Linux x86_64 | `MyFinSight-0.1.1-linux` | `chmod +x` 한 뒤 실행 |
| macOS (Apple Silicon) | `MyFinSight-0.1.1-macos` | `chmod +x` 한 뒤 실행 |
| 파이썬 3.11 이상이 있는 PC | `MyFinSight-0.1.1-source.zip` | `bash run.sh` · `run.bat` |
| Docker | `MyFinSight-0.1.1-source.zip` | `docker compose up -d --build` |

켜지면 브라우저가 <http://localhost:8765> 로 열립니다. 끄려면 함께 뜬 검은 창을 닫습니다.
이름에 `-folder` 가 붙은 파일은 같은 실행 파일의 폴더형으로, 압축을 풀어 쓰고 조금 더 빨리 켜집니다.
자세한 안내: [README](https://github.com/sumb-10/MyFinSight/blob/v0.1.1/packaging/source-zip/README.md)

### 주의사항

- macOS 실행 파일은 자동 빌드로 만든 것이고, 실제 맥에서는 아직 켜 보지 못했습니다. 서명이 없어 처음 열 때 경고가 뜹니다.
- v0.1.0 을 쓰던 PC 에서도 리포트와 투자조건, 연결 설정은 그대로 이어집니다.
- Windows 에서 처음 켤 때 "Windows의 PC 보호" 창이 뜹니다. 「추가 정보」 → 「실행」을 누릅니다 (서명이 없는 프로그램이라 뜹니다).
- Linux 실행 파일은 Ubuntu 20.04 · Debian 11 이후에서 돕니다. 데스크톱 키링이 없는 환경에서는 화면에서 주소·키를 저장할 수 없습니다.
- 한 파일형 실행 파일을 강제로 종료하면 임시 폴더(약 270MB)가 남습니다.

## v0.1.0 — 2026-11-23 (시험판)

저장소를 받지 않고 켤 수 있는 첫 판입니다. 시험판이라 동작이 바뀔 수 있습니다.

### 들어 있는 것

- 실행 파일(Windows · Linux), 스크립트, Docker Compose 세 가지 방법으로 실행
- 팀 DB 주소와 OpenAI 키를 처음 화면에서 입력 — 운영체제 보관함에 저장되고 파일로는 남지 않음
- 주소와 키를 넣지 않아도 연습 모드로 둘러볼 수 있음
- 리포트와 실행 기록은 사용자 폴더에 저장 — 새 판으로 바꿔도 그대로 남음

### 받을 파일

| 환경 | 파일 | 켜는 법 |
|---|---|---|
| Windows | `MyFinSight-0.1.0-windows.exe` | 두 번 누르기 |
| Linux x86_64 | `MyFinSight-0.1.0-linux` | `chmod +x` 한 뒤 실행 |
| macOS, 또는 파이썬 3.11 이상이 있는 PC | `MyFinSight-0.1.0-source.zip` | `bash run.sh` · `run.bat` |
| Docker | `MyFinSight-0.1.0-source.zip` | `docker compose up -d --build` |

켜지면 브라우저가 <http://localhost:8765> 로 열립니다. 끄려면 함께 뜬 검은 창을 닫습니다.
이름에 `-folder` 가 붙은 파일은 같은 실행 파일의 폴더형으로, 압축을 풀어 쓰고 조금 더 빨리 켜집니다.
자세한 안내: [README](https://github.com/sumb-10/MyFinSight/blob/v0.1.0/packaging/source-zip/README.md)

### 주의사항

- macOS 용 실행 파일은 없습니다. 스크립트나 Docker 로 쓸 수 있지만 맥에서는 아직 켜 보지 못했습니다.
- Windows 에서 처음 켤 때 "Windows의 PC 보호" 창이 뜹니다. 「추가 정보」 → 「실행」을 누릅니다 (서명이 없는 프로그램이라 뜹니다).
- Linux 실행 파일은 Ubuntu 20.04 · Debian 11 이후에서 돕니다. 데스크톱 키링이 없는 환경에서는 화면에서 주소·키를 저장할 수 없습니다.
- 한 파일형 실행 파일을 강제로 종료하면 임시 폴더(약 270MB)가 남습니다.
