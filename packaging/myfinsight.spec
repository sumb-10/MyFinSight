# -*- mode: python ; coding: utf-8 -*-
# MyFinSight 실행 파일. 직접 돌리지 말고 packaging/build.py 를 쓴다 (화면 빌드 · 자료 확인 · 켜 보기까지 해 준다).
# 폴더형과 한 파일형 두 모양으로 만들 수 있다 (맨 아래).
import os
from pathlib import Path

from PyInstaller.utils.hooks import collect_dynamic_libs, collect_submodules, copy_metadata

ROOT = Path(SPECPATH).parent  # noqa: F821 — SPECPATH 는 PyInstaller 가 넣어 준다 (이 파일이 있는 폴더)

# 프로그램에 같이 넣는 읽기 전용 자료: (원본, 실행 파일 안에서의 자리). 자리는 저장소와 같게 둔다 —
# backend/analysis/paths.py 가 "이 파일에서 두 칸 위"를 저장소 뿌리로 보고 찾기 때문이다.
datas = [
    (str(ROOT / "backend" / "analysis" / "prompts"), "backend/analysis/prompts"),
    (str(ROOT / "backend" / "analysis" / "stubs"), "backend/analysis/stubs"),  # 연습 모드의 미리 만든 답
    (str(ROOT / "backend" / "analysis" / "examples"), "backend/analysis/examples"),
    (str(ROOT / "backend" / "analysis" / "common" / "store_schemas"), "backend/analysis/common/store_schemas"),
    (str(ROOT / "backend" / "data" / "reference"), "backend/data/reference"),
    (str(ROOT / "backend" / "data" / "config"), "backend/data/config"),
    (str(ROOT / "Front" / "dist"), "web"),  # 화면 (npm run build)
]
datas += copy_metadata("keyring")  # keyring 은 설치 정보(entry points)로 운영체제별 보관함을 찾는다

# 이름을 글자로 적어 불러오는 모듈은 PyInstaller 가 스스로 찾지 못한다
hiddenimports = [
    *collect_submodules("keyring.backends"),  # Windows 자격 증명 관리자 · macOS 키체인 · Linux 키링
    *collect_submodules("uvicorn"),
    "sqlalchemy.dialects.postgresql.psycopg",
    # 시간대 자료 (Asia/Seoul · America/New_York). Windows 는 PyInstaller 가 알아서 넣지만 리눅스·맥은 시스템의 것을 쓴다고 보고 넣지 않는다
    # → 시스템에 시간대 자료가 없는 최소 설치 리눅스에서 켜지지 않았다 (2026-11-23, 깨끗한 Ubuntu 20.04). 어디서나 넣는다
    "tzdata",
    "sqlalchemy.dialects.sqlite",
]
# PostgreSQL 드라이버(psycopg_binary)의 모듈은 PyInstaller 가 스스로 찾는다 (collect_submodules 는 이 패키지를 혼자 불러오지 못해 빈손으로 돌아온다).
# 접속 라이브러리(libpq) DLL 만 따로 넣어 준다
binaries = collect_dynamic_libs("psycopg_binary")

a = Analysis(  # noqa: F821
    [str(ROOT / "packaging" / "launcher.py")],
    pathex=[str(ROOT)],
    binaries=binaries,
    datas=datas,
    hiddenimports=hiddenimports,
    # 실행에 필요 없는 것: 테스트 도구, 창 도구(그림은 파일로만 그린다), 수집기 전용 라이브러리
    excludes=["pytest", "ruff", "tkinter", "IPython", "notebook", "PyQt5", "PyQt6", "PySide2", "PySide6", "backend.tests"],
    noarchive=False,
)
pyz = PYZ(a.pure)  # noqa: F821
# 두 가지 모양. packaging/build.py 가 MYFINSIGHT_ONEFILE 로 고른다 (기본은 한 파일형, --folder 면 0)
#   한 파일형 (기본)  MyFinSight.exe 하나                      — 켤 때마다 임시 폴더에 풀고 시작한다 (창을 닫으면 지운다)
#   폴더형            MyFinSight/MyFinSight.exe + _internal/   — 풀지 않아 더 빨리 켜진다. 폴더째로 옮겨야 한다
ONEFILE = os.environ.get("MYFINSIGHT_ONEFILE", "1") == "1"
common = dict(
    name="MyFinSight",
    console=True,  # 검은 창을 둔다: 켜지는 동안의 안내를 보여 주고, 창을 닫으면 서버와 일꾼이 같이 꺼진다
    upx=False,  # 압축하면 백신이 오탐하기 쉽고 켜지는 시간도 늘어난다
)
if ONEFILE:
    exe = EXE(pyz, a.scripts, a.binaries, a.datas, [], **common)  # noqa: F821
else:
    exe = EXE(pyz, a.scripts, [], exclude_binaries=True, **common)  # noqa: F821
    coll = COLLECT(exe, a.binaries, a.datas, name="MyFinSight", upx=False)  # noqa: F821
