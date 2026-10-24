# 인스턴스에 데이터 API 올리기 (3단계)

프론트는 DB 에 직접 붙지 않음. 모든 요청은 인스턴스의 데이터 API 를 거침 (DB 비밀번호는 인스턴스 `.env` 에만 있음).
정기 수집은 GitHub Actions 그대로 둠. 인스턴스는 API 와 "없는 종목 즉시 수집" 만 맡음.

```
프론트 ──HTTPS──▶ 인스턴스 (Caddy → uvicorn → backend.api.app) ──▶ Lightsail PostgreSQL
                                     │ 없는 종목: yfinance 로 즉시 받아 저장
                                     └ extra_ticker 에 올림 → 다음 Actions 실행부터 모든 출처로 10년치 채움
GitHub Actions (collect.yml) ─────────────────────────────────────▶ 같은 DB (정기 수집)
```

코드: `backend/api/app.py`. 실행 파일: `backend/deploy/myfinsight-api.service`, `backend/deploy/Caddyfile`.

## 0. API 목록

| 요청 | 하는 일 |
|---|---|
| `GET /health` | DB 연결, 출처별 최근 성공·실패 시각 |
| `GET /assets?type=STOCK&index=SP500` | 종목 목록. `type` = STOCK / ETF, `index` = SP500 / NDX / KOSPI200 (둘 다 선택) |
| `GET /prices?tickers=AAPL,005930.KS&start=2025-01-01&end=2026-09-30` | 수정종가 `[{ticker, date, adj_close}]`. DB 에 없는 종목은 바로 받아 저장하고 `new_tickers` 에 적음. 못 받은 종목은 `failed` |
| `GET /fx?start=2026-01-01&end=2026-09-30` | USD/KRW 환율 |
| `GET /financials/AAPL?as_of=2026-09-30` | `as_of` 까지 공시된 재무 지표 최신 값 (선견 금지) |
| `GET /news/AAPL?days=30` | 최근 기사 (최신순) |
| `GET /docs` | 위 API 를 브라우저에서 눌러 보는 화면 (FastAPI 자동 문서) |

- 한 번에 50종목까지.
- 새 종목은 하루 `ON_DEMAND_DAILY_LIMIT`(기본 10)개까지. 넘으면 429.
- 새 종목의 `asset_type`(STOCK·ETF·INDEX)과 이름은 공식 API 로 먼저 판단, 모르면 yfinance 로 보완 (`asset_kind.py`).
  - 한국: DART 상장사 코드표에 있으면 STOCK → KIS 상품 기본정보(ETF·ETN 등) → yfinance
  - 미국: `^` 로 시작하면 INDEX → Tiingo 공식 지원 종목표(Stock·ETF) → yfinance (이름은 yfinance)
  - 다 모르면 기본 STOCK. 그때는 `.env` 의 `ETF_TICKERS` 에 적어 둠.

## 1. 인스턴스 만들기

1. Lightsail 홈 → **Create instance**.
2. 위치: **Seoul, Zone A** (DB 와 같은 곳).
3. 플랫폼: **Linux/Unix** → **Linux operating system** → **Ubuntu 24.04 LTS**. (Linux apps 탭의 OpenClaw 등은 고르지 않음)
4. 플랜: **General purpose**, **Dual-stack**, **$7 (1GB, 40GB SSD)**.
5. 이름: `myfinsight-api` (나중에 못 바꿈). Automatic snapshots 끔.
6. **Create instance**. Running 이 되면:
   - **Networking → Attach static IP** (붙어 있는 동안 무료, 다시 켜도 주소 그대로).
   - **Networking → IPv4 Firewall**: `HTTP 80`, `HTTPS 443` 추가. 처음 시험용으로 `Custom TCP 8000` 도 추가 (5절 끝나면 지움).

## 2. 서버 준비

인스턴스 화면 **Connect using SSH** (브라우저 터미널) 에서:

```bash
sudo apt update && sudo apt install -y python3-venv python3-pip git
```

코드 받기 (비공개 저장소라 토큰이 필요함):

1. GitHub → Settings → Developer settings → **Fine-grained tokens** → Generate. Repository access 는 그 저장소 하나, Permissions 는 **Contents: Read-only**.
2. 인스턴스에서:

```bash
git clone https://github.com/계정/저장소.git ~/role-a-server
# Username: GitHub 아이디, Password: 방금 만든 토큰
cd ~/role-a-server          # 팀 레포 안 하위 폴더면 그 폴더로 (예: cd ~/role-a-server/data-collector)
python3 -m venv venv
venv/bin/pip install -e ".[real,postgres,api]"
```

`.env` 만들기: `nano .env` 로 열어 PC 의 `.env.server` 내용을 붙여 넣고 아래를 더함 (Ctrl+O 저장, Ctrl+X 닫기).

```
DATABASE_URL=postgresql://myfinsight:비밀번호@엔드포인트:5432/myfinsight?sslmode=require
# 프론트 주소 (여러 개면 쉼표). 비우면 모두 허용
CORS_ORIGINS=
ON_DEMAND_DAILY_LIMIT=10
# 값이 있으면 모든 요청에 Authorization: Bearer <값> 필요. 브라우저 프론트가 직접 부르면 비워 둠 (6절)
API_TOKEN=
```

```bash
chmod 600 .env
venv/bin/python backend/scripts/check_db.py      # 테이블 18개, 행 수가 나오면 됨
```

## 3. 띄워 보기 (시험)

```bash
venv/bin/uvicorn backend.api.app:app --host 0.0.0.0 --port 8000
```

브라우저에서 `http://고정IP:8000/health`, `http://고정IP:8000/docs`. `{"ok": true, ...}` 가 나오면 됨. Ctrl+C 로 끔.

## 4. 항상 켜 두기 (systemd)

```bash
sudo cp backend/deploy/myfinsight-api.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable --now myfinsight-api
systemctl status myfinsight-api          # active (running)
curl http://127.0.0.1:8000/health
```

- 폴더가 `/home/ubuntu/role-a-server` 가 아니면 서비스 파일의 `WorkingDirectory`·`ExecStart` 경로를 고침.
- 로그: `journalctl -u myfinsight-api -f`.
- 이 서비스는 인스턴스 안(127.0.0.1)에서만 받음. 밖에서는 5절 HTTPS 로 들어옴.

## 5. HTTPS 주소 (Caddy)

프론트가 `https://` 로 열리면 브라우저가 `http://` API 를 막음. Caddy 가 인증서를 자동으로 받아 HTTPS 로 받아 줌.

```bash
sudo apt install -y caddy
nano backend/deploy/Caddyfile      # 주소를 바꿈: 고정 IP 3.35.12.34 → 3-35-12-34.sslip.io (도메인 있으면 그 주소)
sudo cp backend/deploy/Caddyfile /etc/caddy/Caddyfile
sudo systemctl reload caddy
```

- 브라우저에서 `https://3-35-12-34.sslip.io/health`.
- sslip.io 는 IP 를 이름으로 바꿔 주는 무료 주소. 인증서 발급이 막히면(발급 한도) DuckDNS 같은 무료 도메인을 만들어 그 주소로 바꿈.
- 끝나면 방화벽의 `8000` 규칙 지움.

## 6. 프론트에서 부르기

```js
const API = "https://3-35-12-34.sslip.io";
const res = await fetch(`${API}/prices?tickers=AAPL,MSFT&start=2025-01-01&end=2026-09-30`);
const { prices, new_tickers, failed } = await res.json();
// prices: [{ticker: "AAPL", date: "2025-01-02", adj_close: 243.26}, ...]
```

- 새 종목은 받는 데 몇 초~수십 초 걸림. 프론트에 "불러오는 중" 표시.
- 한국·미국 종목을 한 번에 요청해도 됨 (통화는 종목별로 다름: `.KS`·`.KQ` 는 원, 나머지는 달러).
- `CORS_ORIGINS` 에 프론트 주소(예: `https://myfinsight.vercel.app`)를 적으면 다른 사이트에서는 못 부름.
- 브라우저 코드에 넣은 값은 누구나 볼 수 있음. 그래서 브라우저가 직접 부를 때는 `API_TOKEN` 을 비워 두고, 남용은 하루 새 종목 한도로 막음. 프론트에 자체 서버가 있으면 그 서버만 토큰을 들고 부름.

## 7. 코드 갱신

```bash
cd ~/role-a-server
git pull
venv/bin/pip install -e ".[real,postgres,api]"
sudo systemctl restart myfinsight-api
```

## 8. 비용·종료

- 인스턴스 $7/월 + DB $15/월 = $22/월. 크레딧 $100 안 (3달 약 $66).
- 만든 순간부터 요금이 붙음 (꺼 둬도 붙음). 안 쓰면 **Delete**. 고정 IP 는 인스턴스에서 떼어 두면 요금이 붙으니 같이 지움.
- 프로젝트 끝나면 인스턴스·고정 IP·DB·스냅샷 모두 지움.

## 9. 문제 해결

| 증상 | 확인 |
|---|---|
| `/health` 가 503 | `.env` 의 `DATABASE_URL`, DB 가 Available 인지, `check_db.py` |
| `http://IP:8000` 이 안 열림 | 방화벽에 8000 이 있는지 (시험 때만), uvicorn 이 `0.0.0.0` 으로 떴는지 |
| `https://` 가 안 열림 | 방화벽 80·443, `sudo journalctl -u caddy -n 50` (인증서 발급 오류) |
| 프론트에서 CORS 오류 | `CORS_ORIGINS` 에 프론트 주소가 정확히 있는지 (`https://`, 끝 `/` 없이) |
| 429 | 오늘 새 종목 한도 다 씀. `ON_DEMAND_DAILY_LIMIT` 를 늘리고 `sudo systemctl restart myfinsight-api` |
| 메모리 부족으로 죽음 | 서비스 파일의 `--workers 2` 를 1 로, 또는 $12 (2GB) 플랜으로 |
