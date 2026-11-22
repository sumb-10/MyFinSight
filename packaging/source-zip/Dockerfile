# MyFinSight (Docker Compose 버전). 이 묶음에는 화면이 이미 빌드돼 들어 있어 Node 가 필요 없다.
# 직접 돌리지 말고 compose.yaml 로 켠다:  docker compose up -d --build
FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 PIP_NO_CACHE_DIR=1 PIP_DISABLE_PIP_VERSION_CHECK=1
WORKDIR /app

# 라이브러리를 먼저 깐다 (코드만 바뀌면 이 층은 다시 받지 않는다)
COPY requirements.txt .
RUN pip install -r requirements.txt

COPY backend backend
COPY packaging/launcher.py packaging/launcher.py
COPY Front/dist Front/dist

# 자료(리포트·실행 기록·로그)는 /data 에 쌓인다 → compose 가 볼륨으로 빼 둔다.
# 컨테이너에는 운영체제 보관함이 없다 → 팀 DB 주소와 API 키는 환경변수(.env)로만 받는다 (화면에서는 읽기 전용으로 보인다).
ENV MYFINSIGHT_HOME=/data MYFINSIGHT_SECRET_STORE=none
RUN useradd --create-home --uid 1000 app && mkdir /data && chown app:app /data
USER app
VOLUME /data
EXPOSE 8765

# 서버가 답하는지만 본다 (팀 DB 가 연결 전이어도 서버는 떠 있다)
HEALTHCHECK --interval=30s --timeout=5s --start-period=40s \
  CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8765/api/v1/health', timeout=4)" || exit 1

# 컨테이너 밖에서 들어오는 요청을 받으려면 0.0.0.0 으로 들어야 한다. 밖으로 여는 범위는 compose.yaml 의 ports 가 정한다 (기본: 이 컴퓨터만)
CMD ["python", "packaging/launcher.py", "--host", "0.0.0.0", "--no-browser"]
