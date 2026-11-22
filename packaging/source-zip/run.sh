#!/usr/bin/env bash
# MyFinSight 스크립트 버전 (macOS · Linux). 파이썬 3.11 이상이 깔려 있어야 한다.
# 처음 한 번만 이 폴더의 .venv 에 라이브러리를 받고, 그다음부터는 바로 켠다.
#   bash run.sh                # 켜기 (브라우저가 열린다)
#   bash run.sh --no-browser   # 옵션은 그대로 넘어간다 (--port, --home)
#   PYTHON=python3.12 bash run.sh   # 쓸 파이썬을 직접 고르기
set -euo pipefail
cd "$(dirname "$0")"

if [ ! -f .venv/installed.txt ]; then
  PY=""
  for candidate in "${PYTHON:-}" python3.13 python3.12 python3.11 python3; do
    if [ -n "$candidate" ] && command -v "$candidate" >/dev/null 2>&1 \
      && "$candidate" -c 'import sys; sys.exit(0 if sys.version_info >= (3, 11) else 1)'; then
      PY="$candidate"
      break
    fi
  done
  if [ -z "$PY" ]; then
    echo "[MyFinSight] 파이썬 3.11 이상을 찾지 못했습니다. 설치한 뒤 다시 실행해 주세요. (https://www.python.org/downloads/)"
    exit 1
  fi
  echo "[MyFinSight] 처음 실행입니다. 필요한 라이브러리를 받습니다. 몇 분 걸립니다. ($("$PY" --version))"
  "$PY" -m venv .venv
  .venv/bin/python -m pip install --upgrade pip --quiet
  .venv/bin/python -m pip install -r requirements.txt
  echo ok > .venv/installed.txt
fi

exec .venv/bin/python packaging/launcher.py "$@"
