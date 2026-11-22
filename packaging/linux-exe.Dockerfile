# 리눅스용 실행 파일을 만드는 곳. 직접 쓰지 말고  python packaging/release.py --linux  를 쓴다 (묶음 폴더를 재료로 준다).
#
# 실행 파일은 만든 곳의 C 라이브러리(glibc)보다 오래된 배포판에서 돌지 않는다. 그래서 일부러 오래된 바탕에서 만든다:
# bullseye 는 glibc 2.31 → Ubuntu 20.04 · Debian 11 이후에서 돈다.
FROM python:3.12-slim-bullseye

RUN apt-get update && apt-get install -y --no-install-recommends binutils && rm -rf /var/lib/apt/lists/*
ENV PIP_NO_CACHE_DIR=1 PIP_DISABLE_PIP_VERSION_CHECK=1 PYTHONIOENCODING=utf-8
WORKDIR /src

COPY requirements.txt .
RUN pip install -r requirements.txt "pyinstaller>=6.10"

COPY . .
# 한 파일형 + 폴더형을 만들고 각각 켜 본다. 결과는 /src/packaging/dist/<판>/ 에 나온다 (판 번호는 묶음의 packaging/VERSION)
RUN python packaging/build.py --all
