# 팀원용 DB 사용 가이드

공용 DB(AWS Lightsail PostgreSQL, 서울)를 팀원이 읽어 쓰는 방법.
수집·저장은 역할 A 의 정기 실행(GitHub Actions)이 함. 팀원은 읽기만 함.

## 1. 받을 것

| 항목 | 내용 |
|---|---|
| 접속 주소 | `postgresql://reader:비밀번호@엔드포인트:5432/myfinsight?sslmode=require` |
| 받는 방법 | 역할 A 가 개인 메시지로 줌 |
| 보관 | 자기 PC 의 `.env` 에만 둠. 코드·깃허브·단톡방에 올리지 않음 |

`.env` 예:

```
DATABASE_URL=postgresql://reader:비밀번호@엔드포인트:5432/myfinsight?sslmode=require
```

## 2. reader 계정 제한

| 제한 | 내용 | 걸리면 |
|---|---|---|
| 읽기만 | SELECT 만 됨. INSERT·UPDATE·DELETE·CREATE 는 막힘 | `cannot execute ... in a read-only transaction` / `permission denied` |
| 쿼리 하나 5분 | 5분 넘는 쿼리는 끊김 | `canceling statement due to statement timeout` |
| 동시 연결 10개 | 팀 전체가 같이 씀 | `too many connections for role "reader"` |

- 연결 풀은 작게 (`pool_size=2, max_overflow=0`). 다 쓰면 `engine.dispose()`.
- 수백만 행을 통째로 받지 않음. 기간·종목을 WHERE 로 좁혀서 받음.
- 쓰기가 필요한 결과(백테스트 결과 등)는 각자 로컬 DB·파일에 저장.

## 3. 연결

### 3-1. pandas + SQLAlchemy (어느 코드에서나)

```
pip install pandas sqlalchemy psycopg2-binary python-dotenv
```

```python
import os

import pandas as pd
from dotenv import load_dotenv
from sqlalchemy import create_engine, text

load_dotenv()
url = os.environ["DATABASE_URL"].replace("postgresql://", "postgresql+psycopg2://", 1)
engine = create_engine(url, pool_size=2, max_overflow=0)

print(pd.read_sql(text("SELECT count(*) AS n FROM assets"), engine))
```

### 3-2. role-a-server 패키지 (같은 저장소 안에서)

`.env` 에 위 `DATABASE_URL` 을 넣고:

```
pip install -e .[postgres]
```

```python
from datetime import date

from backend.db import open_repository

repo = open_repository()  # .env 의 DATABASE_URL
prices, meta = repo.get_prices(["AAPL", "MSFT"], date(2025, 1, 1), date(2026, 9, 30))
fin = repo.get_financials_as_of("US-AAPL", date(2026, 9, 30))
```

- `get_prices` 는 출처 고르기·PriceFrame 모양(날짜 × 티커)까지 해 줌.
- 한 번에 한 통화만 됨. 미국·한국 종목은 나눠서 부름.
- 메서드 목록은 `DB_설계.md` 6절.

### 3-3. DBeaver (화면으로 보기)

새 연결 → PostgreSQL:

| 칸 | 값 |
|---|---|
| Host | 주소의 `@` 와 `:5432` 사이 (엔드포인트) |
| Port | 5432 |
| Database | myfinsight |
| Username / Password | reader / 받은 비밀번호 |
| SSL 탭 | Use SSL 체크, SSL mode = require |

## 4. 테이블

팀원이 주로 쓰는 6개 (새 데이터 계약의 읽기 테이블) + 공시 `disclosures`. 전체 18개와 칸 설명은 `DB_설계.md`, 관계도는 `DB_ERD.md`.

| 테이블 | 내용 | 키 |
|---|---|---|
| `assets` | 종목 마스터. `asset_id`(`US-AAPL`, `KR-005930`), `yfinance_symbol`(= 가격 티커), `market`(US·KR), `exchange`(거래소), `asset_type`(STOCK·ETF·INDEX), `currency`, 이름 | `asset_id` |
| `price_daily` | 일별 가격, **종목·날짜당 한 행** (출처 우선순위로 고른 값). `open`·`high`·`low`·`close`, `adj_close`(수정종가), `volume`, `currency`, `source`(종가 출처), `adj_close_source`(수정종가 출처), `verify_status` | `(asset_id, date)` |
| `fx_daily` | USD/KRW 환율 (`pair = 'USDKRW'`) | `(pair, date)` |
| `index_constituent` | 지수 구성종목 스냅샷 (SP500·NDX·KOSPI200), 섹터·산업. KOSPI200 `ticker` 는 6자리 코드(`005930`) | `(index_code, snapshot_date, ticker)` |
| `financials` | 재무 항목, 기간말·재무제표(`statement` IS·BS·CF·ETC)·항목(`item`)당 한 값. `report_date` = 공시일 | `(asset_id, period_end, statement, item)` |
| `news` | 종목별 기사. 사실 표시 `is_press_release`(보도자료)·`title_has_name`(제목에 종목명)·`story_id`·`is_first_report`(같은 기사 묶음의 첫 보도)·`available_on`(쓸 수 있는 첫 거래일) | `(asset_id, url_hash)` |
| `disclosures` | 공시 목록 (미국 SEC EDGAR, 한국 DART, 2000년~). `form`·`items`(8-K Item)·`title`·`event_type`(유형)·`filed_at`·`available_on`·`is_amendment`·`url` | `(source, filing_id, asset_id)` |

가격 티커(`price_daily.ticker`) 표기는 yfinance 기준: `AAPL`, `BRK-B`, `005930.KS`. 출처별 원본 행(`price_daily_source`)·원본 재무(`financials_source`)는 역할 A 내부용.

## 5. 자주 쓰는 쿼리

아래는 3-1 의 `engine` 기준. 리스트 인자는 `bindparam(..., expanding=True)` 로 넘김.

### 5-1. 지수 구성종목 (최신 스냅샷, ETF 제외)

```python
sql = text("""
SELECT c.ticker, c.name, c.sector, c.industry
FROM index_constituent c
JOIN assets a ON a.asset_id = c.asset_id
WHERE c.index_code = :idx
  AND c.snapshot_date = (SELECT max(snapshot_date) FROM index_constituent WHERE index_code = :idx)
  AND a.asset_type = 'STOCK'
ORDER BY c.ticker
""")
sp500 = pd.read_sql(sql, engine, params={"idx": "SP500"})  # SP500 / NDX / KOSPI200
```

### 5-2. 가격 (종목·날짜당 한 행)

출처 고르기는 수집기가 미리 해서 `price_daily` 는 종목·날짜당 한 행. `get_prices` 와 같은 값.
(고르는 순서: 미국 ALPACA → TIINGO → YFINANCE. 한국은 종가·OHLCV 가 KIS → YFINANCE, 수정종가가 YFINANCE → KIS 로 칸마다 다름 (`source`·`adj_close_source`). `verify_status` 는 교차검증 결과)

```python
from sqlalchemy import bindparam

sql = text("""
SELECT ticker, date, adj_close
FROM price_daily
WHERE ticker IN :tickers AND date BETWEEN :start AND :end
ORDER BY ticker, date
""").bindparams(bindparam("tickers", expanding=True))

df = pd.read_sql(sql, engine, params={
    "tickers": ["AAPL", "MSFT", "SPY"], "start": "2021-01-01", "end": "2026-09-30",
})
wide = df.pivot(index="date", columns="ticker", values="adj_close")  # 날짜 × 티커
```

- 백테스트·수익률은 `adj_close`(배당·분할 반영) 사용.
- 미국은 USD, 한국은 KRW. 섞어 계산할 때는 5-3 환율로 맞춤.
- 벤치마크 `SPY`, `QQQ`, `069500.KS` 는 `asset_type = 'ETF'` 로 들어 있음.

### 5-3. 환율

```python
fx = pd.read_sql(text("""
SELECT date, rate
FROM fx_daily
WHERE pair = 'USDKRW' AND date BETWEEN :start AND :end
ORDER BY date
"""), engine, params={"start": "2021-01-01", "end": "2026-09-30"})
```

### 5-4. 재무 (기준일까지 공시된 값만)

`report_date <= 기준일` 조건이 선견 금지. 빼면 미래 공시가 섞임.

```python
fin = pd.read_sql(text("""
SELECT DISTINCT ON (statement, item)
       statement, item, value, unit, period_end, report_date, source
FROM financials
WHERE asset_id = :aid AND report_date <= :as_of
ORDER BY statement, item, period_end DESC
"""), engine, params={"aid": "US-AAPL", "as_of": "2026-09-30"})
```

- 항목 이름은 한글 (`매출액`, `영업이익`, `당기순이익`, `자산총계`, `부채총계`, `자본총계` …). 있는 이름 보기: `SELECT DISTINCT statement, item FROM financials`.
- 한 값은 출처 우선순위(한국 DART, 미국 SEC)와 연결 우선(DART 는 연결 CFS → 별도 OFS)으로 고름. 고른 근거는 `source`·`fs_div`·`period` 칸.
- 정정 공시는 같은 칸의 값과 `report_date` 를 함께 덮어씀: 선견은 없지만 정정 전 값은 남지 않음 (열린 항목).

### 5-5. 뉴스

```python
news = pd.read_sql(text("""
SELECT published_at, title, publisher, url, source
FROM news
WHERE asset_id = :aid AND published_at >= now() - interval '30 days'
ORDER BY published_at DESC
"""), engine, params={"aid": "KR-005930"})
```

백테스트용 (기준일까지 쓸 수 있는 기사만, 관련 기사·첫 보도만, 보도자료 빼고):

```python
news = pd.read_sql(text("""
SELECT available_on, published_at, title, publisher, source
FROM news
WHERE asset_id = :aid AND available_on <= :asof
  AND title_has_name AND is_first_report AND NOT is_press_release
ORDER BY published_at
"""), engine, params={"aid": "US-AAPL", "asof": "2024-12-31"})
```

뉴스 기간: 한국 Google RSS 2005-10~, 미국 Google RSS 2016-10~·Alpaca 2015-12~ (FNSPID 로 미국 2009~2015 보충),
네이버는 종목마다 최신 1,000건이라 대부분 2026년, NewsAPI 는 최근 한 달. 연도별 건수는 `데이터_현황.md` 5절.
Google RSS 는 종목·달마다 100건 안팎이 상한이라 대형주는 표본임.

### 5-5b. 공시

```python
disc = pd.read_sql(text("""
SELECT available_on, filed_at, form, items, event_type, title, url
FROM disclosures
WHERE asset_id = :aid AND available_on <= :asof AND NOT is_amendment
ORDER BY filed_at
"""), engine, params={"aid": "KR-005930", "asof": "2024-12-31"})
```

`event_type` 예: `earnings`(실적), `material_agreement`(주요 계약), `executive_change`(임원), `buyback`(자사주),
`acquisition_disposition`(인수·처분), `rumor_response`(조회공시 답변), `major_holder`(지분 보고). 전체 목록은
`backend/collectors/disclosures/categories.py`. DART 는 접수 날짜만 있어 `available_on` 이 다음 평일임.

### 5-6. 데이터가 어디까지 들어왔는지

```python
pd.read_sql(text("""
SELECT a.market, max(p.date) AS last_date, count(DISTINCT p.ticker) AS tickers
FROM price_daily p JOIN assets a ON a.asset_id = p.asset_id
WHERE p.date >= current_date - 10
GROUP BY a.market
"""), engine)
```

## 6. 갱신 시각 (한국 시간)

| 시각 | 내용 |
|---|---|
| 평일 16:37 | 한국 가격 (KIS·yfinance), 그날 종가까지 |
| 화~토 07:37 | 미국 가격 (Alpaca, 환율) |
| 토 10:13 | 미국 보조 출처(yfinance·Tiingo) 한 주치 갱신, 교차검증 |
| 매일 06:13 | 구성종목·재무 |
| 매일 06:47 | 공시 (SEC EDGAR·DART, 종목마다 최근 14일) |
| 매일 07:23 | 뉴스 |

- 공휴일은 따로 안 거름. 휴장일엔 새 행이 없음.
- 실행이 밀리거나 빠질 수 있음 (GitHub 예약 실행 특성). 2026-10 에는 한국 가격 실행이 5시간쯤 늦게(21:40 KST 무렵) 돌았음.

## 7. 주의

- `price_daily` 는 종목·날짜당 한 행. 출처별 원본 비교가 필요하면 역할 A 에 요청.
- 한국 종목이 KIS 한 곳에만 있는 날은 `adj_close` 가 배당 미반영일 수 있음 (KIS 수정주가 기준). 보통 yfinance 와 함께 있어 교차검증됨 (`verify_status`).
- 전략 대상은 `asset_type = 'STOCK'`. ETF·지수는 벤치마크로만.
- 지수 밖 종목이 필요하면 역할 A 에 요청. 직접 넣을 수 없음.
- 비밀번호가 새면 역할 A 가 `python backend/scripts/make_reader.py` 로 바꾸고 새 주소를 다시 줌.

## 8. 문제 해결

| 오류 | 원인 · 해결 |
|---|---|
| `password authentication failed` | 비밀번호 오타, 또는 바뀐 비밀번호. 역할 A 에 확인 |
| `could not connect` / 시간 초과 | 엔드포인트 오타, 학교·회사 망에서 5432 포트 막힘. 다른 망에서 다시 시도 |
| `SSL` 관련 오류 | 주소 끝 `?sslmode=require` 확인 |
| `too many connections for role "reader"` | 팀 전체 연결 10개 초과. 안 쓰는 노트북·DBeaver 연결 닫기 |
| `statement timeout` | 5분 초과. 기간·종목을 좁히거나 나눠서 조회 |
| `read-only transaction` / `permission denied` | 쓰기 시도. reader 는 읽기만 됨 |
