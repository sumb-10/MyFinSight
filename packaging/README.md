# 배포판 만들기

MyFinSight 를 저장소 없이 켤 수 있게 묶는다. 세 가지로 건넨다.

| 배포판 | 받는 사람에게 필요한 것 | 만드는 명령 | 나오는 파일 (`packaging/dist/<판>/`) |
|---|---|---|---|
| 실행 파일 | 없음 | `python packaging/build.py --all` | `MyFinSight-<판>-<운영체제>.exe`, `…-folder.zip` |
| 스크립트 | 파이썬 3.11 이상 | `python packaging/release.py` | `MyFinSight-<판>-source.zip` 안의 `run.bat` · `run.sh` |
| Docker Compose | Docker | (위와 같은 묶음) | `MyFinSight-<판>-source.zip` 안의 `compose.yaml` |

- 스크립트와 Docker 는 묶음 하나(`source.zip`)를 같이 쓴다. 깃에 없는 화면 빌드 결과를 그 안에 넣어 주므로, 받는 사람은 Node 가 필요 없다
- 실행 파일은 만든 운영체제용만 나온다. 리눅스용은 `python packaging/release.py --linux` 가 Docker 안에서 만들어 준다. 맥용은 맥에서 `build.py` 를 돌려야 한다
- 판 번호는 깃 태그가 정한다. 손으로 적는 곳이 없다 (`pyproject.toml` 의 `version` 은 배포판 번호가 아니니 고치지 않는다)
  - `v0.1.1` 태그의 커밋 그대로에서 만들면 `0.1.1` → `dist/v0.1.1/MyFinSight-0.1.1-…`
  - 그 밖(태그가 없는 커밋, 커밋하지 않은 수정이 있을 때)에는 `dev` → `dist/dev/MyFinSight-dev-…`
  - 그래서 낸 판과 같은 이름의 파일은 그 판의 코드에서만 나온다. 지금 붙을 번호 보기: `python packaging/build.py --print-version`
- 묶음에 들어가는 파일의 원본은 `packaging/source-zip/` (받는 사람용 안내문 `README.md` 포함)
- 결과는 `packaging/dist/<판>/` 에 건넬 이름으로 나온다. 판마다 폴더가 달라 다른 판의 파일을 건드리지 않는다. `release.py` 는 그 판의 릴리스 노트 사본(`RELEASE_NOTES.md`)도 같이 넣는다. 만드는 동안 `packaging/build/` 가 잠깐 생겼다가 끝나면 지워진다 (둘 다 깃에 올라가지 않는다)

한 번에 다 만들기 (Windows 에서):

```
python packaging/build.py --all          # Windows 실행 파일 (화면 빌드 포함)
python packaging/release.py --linux      # 묶음 + 리눅스 실행 파일
```

## 실행 파일 만들기

```
pip install -e ".[analysis,packaging]"      # + Node 22 (화면 빌드)
python packaging/build.py          # 한 파일형 (기본)
python packaging/build.py --folder # 폴더형
python packaging/build.py --all    # 둘 다
```

- 순서: 화면 빌드(`Front/dist`) → 자료 확인 → 묶기(PyInstaller) → 내용 확인 → 켜 보기
- 만든 운영체제용만 나온다. 맥용은 맥에서, Windows 용은 Windows 에서 돌린다
- 깃에 있는 것만으로 빌드된다. 종목 사전은 넣지 않는다 — 켠 뒤 팀 DB 에 연결되면 서버가 자료 폴더의 `descriptor/` 에 만든다
- 화면만 그대로일 때는 `--skip-web` 으로 화면 빌드를 건너뛴다
- 처음 받은 저장소에서도 된다: `Front/node_modules` 가 없으면 잠금 파일(`pnpm-lock.yaml`)대로 받는다. pnpm 이 없으면 `npx` 로 불러 쓴다
- `release.py` 는 빌드한 화면이 없거나 소스보다 오래됐으면 스스로 빌드한다 (`build.py` 를 먼저 돌렸으면 그 결과를 쓴다). 둘을 동시에 돌리지는 말 것 — 화면 빌드가 겹친다
- 묶인 내용을 들여다보려면 `--keep-work` 를 준다. 중간 파일이 `packaging/build/` 에 남는다 (풀어 놓은 폴더형은 `build/app/MyFinSight/`)

## 두 가지 모양

| | 한 파일형 (기본) | 폴더형 (`--folder`) |
|---|---|---|
| 결과 (Windows) | `MyFinSight-<판>-windows.exe` 하나 (137MB) | `MyFinSight-<판>-windows-folder.zip` (137MB, 풀면 310MB) |
| 쓰는 법 | 받아서 누른다 | 압축을 풀고 폴더 안의 `MyFinSight.exe` 를 누른다 |
| 켜지는 시간 (2026-11-23 측정) | 6초 | 3초 |
| 켤 때 | 임시 폴더에 272MB 를 풀고 실행, 창을 닫으면 지운다 | 그대로 실행 |
| 강제 종료·전원 꺼짐 뒤 | 임시 폴더(`%TEMP%\_MEI…`)가 남는다 | 남는 것 없음 |
| 주의 | — | `MyFinSight.exe` 만 떼어 내면 안 켜진다 (`_internal` 이 옆에 있어야 한다) |

누구에게 어느 쪽을 권할지: 보통은 한 파일형. 매일 켜 두고 쓰는 사람, 디스크 여유가 적은 PC, 켜지는 것이 느린 PC 에는 폴더형.
기능과 자료 폴더는 두 모양이 같아서, 쓰다가 다른 쪽으로 바꿔도 리포트와 연결 설정이 그대로다.

## 판 내기 (자동)

`.github/workflows/release.yml` 이 GitHub 의 Windows · macOS · Linux 서버에서 위 명령들을 돌리고 Release 까지 만든다.

1. `packaging/RELEASE_NOTES.md` 맨 위에 `## v0.1.1 — 날짜` 절을 적는다. 이 절이 그대로 Release 의 설명이 된다
2. main 에 병합한다
3. 태그를 올린다: `git switch main && git pull && git tag v0.1.1 && git push origin v0.1.1`

- 태그는 브랜치가 아니라 커밋 하나에 붙는 이름표다. `git tag` 는 지금 서 있는 커밋에 붙이므로, main 으로 가서 최신을 받은 뒤에 붙인다
- 릴리스 노트에 그 판의 절이 없으면 빌드 전에 멈춘다
- 세 운영체제 중 하나라도 빌드에 실패하면 Release 는 만들어지지 않는다. 고친 것을 main 에 넣은 뒤 태그를 지우고(`git push origin :v0.1.1`, `git tag -d v0.1.1`) 다시 올린다
- 이미 Release 가 나간 태그는 옮기지 않는다. 고칠 것이 있으면 다음 번호로 낸다
- `0.x` 판과 `-beta` 같은 꼬리가 붙은 판은 pre-release 로 올라간다
- 웹에서 Release 를 직접 만들지 말 것 (새 태그로 만들면 그것도 태그를 올린 것이라 자동 빌드가 돌고, 이미 있는 Release 를 또 만들려다 실패한다)
- 빌드만 해 보기: `packaging/` 를 고친 PR 에서는 저절로 돌고, Actions 탭의 **Run workflow** 버튼으로도 돌릴 수 있다. 이름이 `dev` 인 파일이 그 실행 기록의 Artifacts 에 14일 남는다

## GitHub Release 에 손으로 올리기

자동 빌드를 쓸 수 없을 때. 태그를 먼저 붙이고 만들어야 판 번호가 붙는다.

```
git switch main && git pull && git tag v0.1.1      # 아직 올리지 않는다
python packaging/build.py --all                     # → packaging/dist/v0.1.1/
python packaging/release.py --linux
```

```
packaging/dist/v0.1.1/
  MyFinSight-0.1.1-windows.exe            실행 파일 (Windows, 한 파일형)
  MyFinSight-0.1.1-windows-folder.zip     실행 파일 (Windows, 폴더형)
  MyFinSight-0.1.1-linux                  실행 파일 (Linux x86_64, 한 파일형)
  MyFinSight-0.1.1-linux-folder.tar.gz    실행 파일 (Linux x86_64, 폴더형)
  MyFinSight-0.1.1-macos.zip              실행 파일 (macOS, 한 파일형 — 안에 MyFinSight.command. 맥에서 만들 때만)
  MyFinSight-0.1.1-macos-folder.tar.gz    실행 파일 (macOS, 폴더형 — 맥에서 만들 때만)
  MyFinSight-0.1.1-source.zip             스크립트 버전 + Docker Compose 버전
  RELEASE_NOTES.md                        이 판의 릴리스 노트 (설명 칸에 붙여 넣을 글 — 파일로 올리지는 않는다)
```

1. 저장소 → 오른쪽 **Releases** → **Draft a new release**
2. **Choose a tag** 에 같은 이름(`v0.1.1`)을 적는다. **Target** 은 main
3. 제목을 적고, 설명에는 그 폴더의 `RELEASE_NOTES.md` 를 붙여 넣고, 아래 상자에 나머지 파일들을 끌어다 놓는다 (파일 하나에 2GB 까지)
4. 시험판이면 pre-release 로 표시한다 → 목록에 `Pre-release` 표시가 붙고 "최신 판"으로는 잡히지 않는다
5. **Publish release**. 그 Release 의 주소가 내려받는 곳이 된다

공개 저장소의 Release 는 누구나 내려받을 수 있다. 올리기 전에 볼 것: 실행 파일에는 코드와 프롬프트가 들어 있고,
`.env` 와 내 리포트는 들어 있지 않다 (빌드의 "내용 확인"이 막는다). 팀 DB 주소와 API 키도 들어 있지 않다 — 받는 사람이 화면에서 넣는다.

받는 사람에게 같이 알릴 것
- 처음 켤 때 "Windows 의 PC 보호" 창이 뜨면 「추가 정보」 → 「실행」 (서명이 없는 프로그램이라 뜬다)
- 검은 창이 뜨고 몇 초 뒤 브라우저가 열린다. 끄려면 검은 창을 닫는다
- 팀 DB 주소와 OpenAI 키는 처음 화면에서 넣는다

## 들어가는 것 · 안 들어가는 것

| 들어감 | 안 들어감 |
|---|---|
| 서버·일꾼 코드와 라이브러리 | `.env`, `.env.*` (비밀 값) |
| 화면(`Front/dist`) | `data/`, `output/` (내 리포트·실행 기록) |
| 프롬프트, 연습 모드 답 | 수집기용 키 (DART·KIS 등) |
| | 종목 사전 (팀 DB 에 연결되면 자료 폴더에 만든다) |

팀 DB 주소와 OpenAI 키는 받는 사람이 화면(연결 설정)에서 넣는다. 그 값은 운영체제 보관함
(Windows 자격 증명 관리자 · macOS 키체인)에 저장되고 파일로는 남지 않는다.

## 켜면 생기는 것

프로그램이 있는 곳에는 아무것도 쓰지 않는다. 자료는 사용자 폴더에 쌓인다.

| 운영체제 | 자료 폴더 |
|---|---|
| Windows | `%LOCALAPPDATA%\MyFinSight` |
| macOS | `~/Library/Application Support/MyFinSight` |
| Linux | `~/.local/share/MyFinSight` |

- `store/` 투자조건·요청·모의투자, `output/` 실행별 결과, `analysis_results.db` 리포트, `logs/` 로그
- `descriptor/` 종목 사전. 서버가 팀 DB 를 열 때마다 DB 기준으로 맞춘다 (지워도 다음에 켜면 다시 생긴다)
- 새 판으로 바꿀 때는 실행 파일(또는 프로그램 폴더)만 갈아 끼우면 된다. 자료 폴더는 그대로다
- 지울 때는 실행 파일과 자료 폴더를 지우고, 그 전에 연결 설정에서 「지우기」를 눌러 보관함의 값도 지운다

## 옵션

```
MyFinSight --port 9000        # 포트 바꾸기 (기본 8765)
MyFinSight --home D:\mfs      # 자료 폴더 바꾸기 (환경변수 MYFINSIGHT_HOME 도 같다)
MyFinSight --no-browser       # 브라우저를 열지 않기
```

- 포트는 고정이다. 화면이 브라우저에 남기는 기록이 `주소:포트`마다 따로라서, 포트가 바뀌면 처음 켠 것처럼 보인다
- 고급: 자료 폴더에 `settings.env` 를 두면 `.env` 처럼 읽는다 (예: `ANALYSIS_LLM_MODEL`). 앱은 이 파일을 만들거나 고치지 않는다

## 파일

- `launcher.py` 시작점. 사용자 폴더를 정하고, 서버에 화면을 얹고, 자기 자신을 `--worker` 로 한 번 더 켠다. 세 배포판이 모두 이것으로 켜진다
- `myfinsight.spec` 실행 파일에 무엇을 묶을지 (PyInstaller). 두 모양이 같은 내용을 쓰고 마지막 몇 줄만 다르다
- `build.py` 실행 파일 만들기 (화면 빌드 → 묶기 → 켜 보기 → `dist/<판>/` 에 내놓기). 판 번호를 정하는 곳이기도 하다 (`version`)
- `release.py` 묶음(`source.zip`) 만들기, `--linux` 로 리눅스 실행 파일까지
- `source-zip/` 묶음(`source.zip`)에만 들어가는 파일: `run.bat` · `run.sh` · `Dockerfile` · `compose.yaml` · `env.example` · `dockerignore` · `README.md`(받는 사람용)
- `linux-exe.Dockerfile` 리눅스 실행 파일을 만드는 곳 (오래된 배포판에서도 돌게 glibc 가 낮은 바탕)
- `.github/workflows/release.yml` (저장소 맨 위) 자동 빌드와 Release 만들기
- `RELEASE_NOTES.md` 판별 릴리스 노트. 판마다 절 하나, 새 판을 위에 적는다 (그 절이 GitHub Release 페이지의 설명이 된다)
- `dist/<판>/` 만든 결과 — 올릴 파일과 그 판의 릴리스 노트 (깃에 올라가지 않는다). 지난 판의 폴더는 지워도 된다 — 원본은 GitHub Release 에 있다

이 폴더에 `__init__.py` 를 두지 말 것. 같은 이름의 라이브러리(`packaging`)를 pip·pytest·PyInstaller 가 쓴다.
