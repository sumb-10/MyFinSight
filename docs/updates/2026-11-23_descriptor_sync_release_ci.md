# 종목 사전 자동 생성, 판 번호는 깃 태그, 릴리스 자동 빌드 (2026-11-23)

종목 사전을 서버가 팀 DB 에서 스스로 만들게 했고, 판 번호를 깃 태그가 정하게 했고, 태그를 올리면 GitHub 이 세 운영체제에서 빌드해 Release 를 만들게 했다.
브랜치 `feature/descriptor-sync`, 커밋 `8751bac`(종목 사전) · `dd1cfb4`(깨끗한 저장소에서 빌드) · `f25ea93`(판 번호) · `5309944`(워크플로), PR 35.
각 항목은 "무엇을 / 왜 / 어디를(파일) / 어떻게 확인했나"를 적는다.

## 1. 문제

- 종목 사전은 `backend/scripts/build_descriptor.py` 를 손으로 돌려야 생겼다. 서버는 그 파일을 읽기만 했다. 실행 파일로 받은 사람은 만들 방법이 없어서 사전을 프로그램 안에 넣어 보냈다.
- 그 파일은 깃에 없다(`backend/data/processed/`). 그래서 깃에 있는 것만 받는 자동 빌드 서버에서는 빌드할 수 없었다.
- 판 번호를 `pyproject.toml` 에 손으로 적었다. 번호를 올리지 않고 다시 빌드하면 이미 올린 v0.1.0 과 이름은 같고 내용은 다른 파일이 나왔다.
- 깨끗한 저장소에서는 화면 빌드가 실패했다. `build.py` 가 `npm ci` 를 불렀는데 `Front` 의 잠금 파일은 pnpm 것(`pnpm-lock.yaml`)뿐이다.

## 2. 결정

- **종목 사전은 팀 DB 의 사본으로 본다.** 화면 서버가 시장 자료를 열 때 DB 기준으로 맞춘다: 처음 쓸 때, 화면에서 DB 주소를 저장한 직후, 새 거래일 자료가 들어왔을 때.
  - 스크립트가 쓰던 세 함수(`descriptor_inputs` → `build_descriptors` → `write_descriptors`)를 그대로 부른다.
  - 버전 파일은 내용이 같으면 다시 쓰지 않는다. DB 가 그대로면 예전 실행이 고른 버전 파일도 그대로다.
  - 맞추지 못해도 서버를 멈추지 않는다. 있던 파일을 쓰고 이유를 로그에 남긴다.
  - 일꾼은 맞추지 않는다. 일꾼은 서버가 요청을 받은 뒤에 일하므로 그때는 파일이 있다. 둘이 같이 쓰면 켜질 때 같은 파일을 동시에 쓰게 된다.
- **판 번호는 깃 태그가 정한다** (사용자 결정). 지금 코드가 `v0.1.1` 태그의 커밋 그대로이고 고친 것이 없으면 `0.1.1`, 그 밖에는 `dev`. 낸 판과 같은 이름의 파일은 그 판의 코드에서만 나온다.
  - `pyproject.toml` 의 `version` 은 배포판 번호가 아니다. `0.0.0` 으로 두고 고치지 않는다.
  - 결과는 판마다 폴더 하나: `packaging/dist/v0.1.1/`, `packaging/dist/dev/`. 그 폴더에 그 판의 릴리스 노트 사본도 넣는다.
- **자동 빌드는 태그를 올릴 때만 Release 를 만든다** (사용자 결정). main 이 바뀐다고 돌지 않는다.
  - `v*` 태그 → 빌드 + Release. `packaging/` 을 고친 PR 과 Actions 탭의 버튼 → 빌드만.
  - 워크플로에는 빌드 방법을 적지 않는다. `build.py` · `release.py` 를 부르기만 한다.

## 3. 수정

### 서버

- **`m2_data/descriptor.py`**: `sync(repo, market)` 추가. 사전이 없을 때의 오류를 `DataMissing`("팀 DB 에 연결하면 자동으로 만들어집니다")으로.
- **`api/services.py`**: 시장 자료를 여는 곳을 `_open_market_data` 로 모으고 거기서 `sync`. 테스트가 꽂은 저장소로는 부르지 않는다.
- **`settings.py`**: `market.descriptor_sync`. 환경변수 `ANALYSIS_DESCRIPTOR_SYNC=0` 으로 끈다.
- `README.md`, `backend/analysis/README.md`: 빠른 시작에서 사전 만들기 단계를 "직접 만들 때만"으로.

### 패키징

- **`launcher.py`**: 사전 자리를 사용자 폴더의 `descriptor/` 로 (`ANALYSIS_DESCRIPTOR_DIR`).
- **`myfinsight.spec`, `build.py`, `release.py`**: 사전을 넣지 않고, 있는지도 보지 않는다.
- **`build.py`**: `version()`(깃 태그에서, 묶음 안에서는 `packaging/VERSION`), `out_dir()`, `--print-version`. 화면 라이브러리는 `pnpm install --frozen-lockfile`(pnpm 이 없으면 `npx` 로 pnpm 9).
- **`release.py`**: 빌드한 화면이 없거나 오래됐으면 스스로 빌드. `--notes <태그>` 는 `RELEASE_NOTES.md` 에서 그 판의 절을 찍는다. 묶음에 `packaging/VERSION` 을 적어 넣는다.
- **`.github/workflows/release.yml`(신규)**: 버전 번호 · 릴리스 노트 확인(태그일 때: 이 커밋의 판 번호가 그 태그인가, 릴리스 노트에 그 판의 절이 있는가) → Windows · macOS 실행 파일 + Linux 실행 파일 · `source.zip` → Release.

## 4. 알아 둘 것

- **개발 환경에도 적용된다.** 저장소에서 서버를 켜면 `backend/data/processed/` 의 사전이 팀 DB 기준으로 갱신된다. 사전을 고정해 두고 여러 번 돌릴 때는 `ANALYSIS_DESCRIPTOR_SYNC=0`.
- 서버 없이 CLI 로만 돌릴 때는 예전처럼 스크립트로 사전을 만든다.
- 팀 DB 가 없으면 사전도 없다. 그 경우 요청은 사전을 읽기 전에 "비교지수 가격이 없음"으로 멈추므로, 사전을 프로그램에서 빼서 잃는 기능은 없다.
- **판을 내는 순서**: `packaging/RELEASE_NOTES.md` 에 `## v0.1.1 — 날짜` 절을 적어 main 에 병합 → `git switch main && git pull && git tag v0.1.1 && git push origin v0.1.1`. 태그는 지금 서 있는 커밋에 붙으므로 main 에서 붙인다.
- 웹에서 새 태그로 Release 를 직접 만들면 그것도 태그를 올린 것이라 자동 빌드가 돌고, 이미 있는 Release 를 또 만들려다 실패한다.
- 자동 빌드의 macOS 는 Apple Silicon 용이다. 인텔 맥용은 만들지 않는다.
- `build.py` 와 `release.py` 를 동시에 돌리지 않는다. 빌드한 화면이 없으면 둘 다 화면을 빌드하려 한다.

## 5. 확인

- 분석 테스트 645 통과 (사전 맞춤 7개 포함, 원래 불안정한 1개 제외) + 판 번호 · 릴리스 노트 테스트 6개. 테스트가 개발자의 `backend/data/processed/` 를 건드리지 않는 것도 확인.
- 빈 자료 폴더로 켜기 → 사전 생성 → 연습 모드 분석 한 건: Windows 실행 파일, Ubuntu 20.04 의 Linux 실행 파일, Docker Compose. DB 없이 켠 뒤 화면에서 주소를 저장하는 흐름도 같다.
- 실제 크기(719종목)의 조립 · 저장은 0.1초 미만. 팀 DB 에서 읽는 시간은 재지 못했다 (`docs/TODO.md` 에 실제 DB 로 사전 생성 1.7초 기록).
- 깃에 올라간 파일만 넣은 Node 22 컨테이너에서: `source.zip` 빌드, 태그 없음 → `dev` · 태그 → 그 번호 · 태그 뒤 수정 → `dev`, 판 폴더와 릴리스 노트 사본.
- 워크플로 첫 실행(PR 35, 커밋 `5309944`): Windows · macOS · Linux 세 빌드가 모두 통과했다. 각각 약 7분. 빌드에 든 켜 보기(서버 · 일꾼 · 화면, Windows · macOS 는 보관함 저장 가능 여부까지)도 통과. 만든 파일은 Artifacts 에 `dev` 이름으로 남았다 (Windows 267MB · macOS 230MB · Linux + `source.zip` 359MB). 태그가 없어 Release 단계는 건너뛰었다.
- 확인하지 못한 것: 실제 팀 DB 로 사전 생성, 자동 빌드가 만든 macOS 실행 파일을 실제 맥에서 켜 보기, 태그를 올려 Release 가 게시되는 마지막 단계.
