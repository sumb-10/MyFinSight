"""v1 스키마 고정본 (migrate_v2 테스트용). 새 데이터 계약 이전 tables.py 의 테이블 정의 그대로.

바꾸지 말 것: 운영 DB 에 남아 있을 수 있는 예전 모양을 재현하기 위한 사본이다.
"""

from __future__ import annotations

from sqlalchemy import (
    BigInteger,
    CheckConstraint,
    Column,
    Date,
    Float,
    ForeignKey,
    Index,
    Integer,
    MetaData,
    PrimaryKeyConstraint,
    String,
    Table,
    Text,
    UniqueConstraint,
)

from backend.db.tables import BigId, Json, UtcDateTime

Price = Float(precision=53)
SOURCE_FK = "data_sources.source_name"

metadata = MetaData()

# ================================================================ 추가: 출처·종목 마스터
data_sources = Table(
    "data_sources",
    metadata,
    Column("source_id", Integer, primary_key=True, autoincrement=True),
    Column("source_name", String(40), nullable=False, unique=True),  # 다른 테이블의 source
    Column("type", String(10), nullable=False),  # QUANT / QUAL / META
    Column("provides", String(80)),  # 저장 테이블
    Column("description", Text),
    Column("last_success_at", UtcDateTime),
    Column("last_failure_at", UtcDateTime),
)

assets = Table(
    "assets",
    metadata,
    Column("asset_id", String(32), primary_key=True),  # KR-005930, US-AAPL
    Column("ticker", String(20), nullable=False),  # 시장 안 코드 (005930, AAPL)
    Column("name", String(200)),
    Column("market", String(10), nullable=False),  # KOSPI / KOSDAQ / US
    Column("asset_type", String(10), nullable=False, server_default="STOCK"),
    Column("currency", String(3), nullable=False),
    Column("yfinance_symbol", String(20), nullable=False, unique=True),  # = price_daily.ticker
    Column("dart_corp_code", String(8)),
    Column("sec_cik", String(10)),
    Column("kis_ticker", String(10)),
    Column("tiingo_symbol", String(20)),
    Column("alpaca_symbol", String(20)),
    Column("created_at", UtcDateTime, nullable=False),
    Column("updated_at", UtcDateTime, nullable=False),
    UniqueConstraint("market", "ticker", name="uq_assets_market_ticker"),
)

# ================================================================ 부록 B
fetch_log = Table(
    "fetch_log",
    metadata,
    Column("id", BigId, primary_key=True, autoincrement=True),
    Column("source", String(40), ForeignKey(SOURCE_FK), nullable=False),
    Column("target", String(100), nullable=False),  # 티커·검색어·constituents:SP500
    Column("start_date", Date),
    Column("end_date", Date),
    Column("status", String(10), nullable=False),  # SUCCESS / FAILED / PARTIAL
    Column("fetched_at", UtcDateTime, nullable=False),
    Column("error", Text),
    # 추가
    Column("fetched_count", Integer),  # 받은 행 수
    Column("inserted_count", Integer),  # 새로 저장·갱신한 행 수
)
Index("idx_fetch_log_target", fetch_log.c.target, fetch_log.c.fetched_at)

price_daily = Table(
    "price_daily",
    metadata,
    Column("ticker", String(20), nullable=False),  # yfinance 표기 (MSFT, BRK-B, 005930.KS)
    Column("date", Date, nullable=False),
    Column("adj_close", Price, nullable=False),
    Column("volume", BigInteger),
    Column("currency", String(3), nullable=False, server_default="USD"),
    Column("source", String(40), ForeignKey(SOURCE_FK), nullable=False),
    Column("fetched_at", UtcDateTime, nullable=False),
    # 추가: 종목 마스터 연결, 시가·고가·저가·종가, 교차검증 칸, 수집 이력 연결
    Column("asset_id", String(32), ForeignKey("assets.asset_id"), nullable=False),
    Column("open", Price),
    Column("high", Price),
    Column("low", Price),
    Column("close", Price),
    Column("source_count", Integer),  # CONSENSUS 행: 비교한 출처 수
    Column("dev_pct", Price),  # 보정 가격 대비 종가 편차(%)
    Column("adj_dev_pct", Price),  # 수정종가 편차(%)
    Column("verify_status", String(10)),  # VERIFIED / MISMATCH / SINGLE
    Column("outlier_sources", Json),  # CONSENSUS 행: 허용오차를 넘은 출처
    Column("fetch_log_id", BigInteger, ForeignKey("fetch_log.id")),
    PrimaryKeyConstraint("ticker", "date", "source"),
    CheckConstraint("adj_close > 0", name="ck_price_daily_adj_close"),
)
Index("idx_price_ticker_date", price_daily.c.ticker, price_daily.c.date)
Index(  # 교차검증 대기 행만 담는 부분 인덱스 (15분마다 찾음)
    "idx_price_unverified",
    price_daily.c.ticker,
    price_daily.c.date,
    postgresql_where=price_daily.c.verify_status.is_(None),
    sqlite_where=price_daily.c.verify_status.is_(None),
)

fx_daily = Table(
    "fx_daily",
    metadata,
    Column("pair", String(6), nullable=False),
    Column("date", Date, nullable=False),
    Column("rate", Price, nullable=False),
    Column("source", String(40), ForeignKey(SOURCE_FK), nullable=False),
    Column("fetched_at", UtcDateTime, nullable=False),
    PrimaryKeyConstraint("pair", "date", "source"),
    CheckConstraint("rate > 0", name="ck_fx_daily_rate"),
)

index_constituent = Table(
    "index_constituent",
    metadata,
    Column("index_code", String(10), nullable=False),
    Column("snapshot_date", Date, nullable=False),
    Column("ticker", String(20), nullable=False),
    Column("name", String(200)),
    Column("sector", String(60), nullable=False),
    Column("industry", String(100), nullable=False),
    Column("source", Text, nullable=False),  # 출처 이름 + URL (IndexConstituent.source)
    Column("fetched_at", UtcDateTime, nullable=False),
    # 추가: 종목 마스터 연결
    Column("asset_id", String(32), ForeignKey("assets.asset_id"), nullable=False),
    PrimaryKeyConstraint("index_code", "snapshot_date", "ticker"),
)

run_step = Table(
    "run_step",
    metadata,
    Column("run_id", String(40), nullable=False),
    Column("step", String(40), nullable=False),
    Column("status", String(10), nullable=False),
    Column("started_at", UtcDateTime, nullable=False),
    Column("ended_at", UtcDateTime),
    Column("summary", Text),
    Column("sources_json", Json),
    Column("error_code", String(60)),
    Column("error_message", Text),
    PrimaryKeyConstraint("run_id", "step"),
)

run_artifact = Table(
    "run_artifact",
    metadata,
    Column("run_id", String(40), primary_key=True),
    Column("created_at", UtcDateTime, nullable=False),
    Column("profile_json", Json, nullable=False),
    Column("spec_json", Json, nullable=False),
    Column("spec_hash", String(64), nullable=False),
    Column("universe_json", Json, nullable=False),
    Column("config_json", Json, nullable=False),
)

report = Table(
    "report",
    metadata,
    Column("run_id", String(40), ForeignKey("run_artifact.run_id"), primary_key=True),
    Column("created_at", UtcDateTime, nullable=False),
    Column("data_json", Json, nullable=False),
    Column("text_markdown", Text, nullable=False),
    # 추가: Report.display_values (M04-03 일치성 검사에 쓴 표시 문자열)
    Column("display_values_json", Json, nullable=False),
)

# ================================================================ 추가: 재무·뉴스
financials = Table(
    "financials",
    metadata,
    Column("financial_id", BigId, primary_key=True, autoincrement=True),
    Column("asset_id", String(32), ForeignKey("assets.asset_id"), nullable=False),
    Column("source", String(40), ForeignKey(SOURCE_FK), nullable=False),
    Column("period", String(20), nullable=False),  # 2025_11011, FY2025, 수집일
    Column("fs_div", String(5), nullable=False, server_default="-"),  # CFS / OFS / -
    Column("metric", String(60), nullable=False),
    Column("value", Price, nullable=False),
    Column("unit", String(10)),
    Column("fiscal_year", Integer),
    Column("report_code", String(20)),
    Column("period_end", Date),
    Column("disclosed_at", Date, nullable=False),  # 공시일: 이날 이후만 백테스트에 씀 (C-06)
    Column("rcept_no", String(30)),
    Column("verification_status", String(12)),  # VERIFIED / MISMATCH / UNVERIFIED
    Column("metadata_json", Json),
    Column("fetched_at", UtcDateTime, nullable=False),
    Column("fetch_log_id", BigInteger, ForeignKey("fetch_log.id")),
    UniqueConstraint(
        "asset_id", "source", "period", "fs_div", "metric", name="uq_financials_natural"
    ),
)
Index("idx_financials_asset_disclosed", financials.c.asset_id, financials.c.disclosed_at)

news = Table(
    "news",
    metadata,
    Column("news_id", BigId, primary_key=True, autoincrement=True),
    Column("asset_id", String(32), ForeignKey("assets.asset_id"), nullable=False),
    Column("source", String(40), ForeignKey(SOURCE_FK), nullable=False),
    Column("url", Text, nullable=False),
    # url SHA-256, 중복 판단 키 (Google RSS 주소는 수 KB 라 PostgreSQL 인덱스에 안 들어감)
    Column("url_hash", String(64), nullable=False),
    Column("title", Text, nullable=False),
    Column("content", Text),
    Column("publisher", String(200)),
    Column("published_at", UtcDateTime, nullable=False),
    Column("language", String(5)),
    Column("query", String(200)),
    Column("content_hash", String(64), nullable=False),  # url + 제목 SHA-256
    Column("metadata_json", Json),
    Column("fetched_at", UtcDateTime, nullable=False),
    Column("fetch_log_id", BigInteger, ForeignKey("fetch_log.id")),
    UniqueConstraint("asset_id", "url_hash", name="uq_news_natural"),
)
Index("idx_news_asset_published", news.c.asset_id, news.c.published_at)

# ================================================================ 추가: 요청으로 늘어난 종목
extra_ticker = Table(
    "extra_ticker",
    metadata,
    Column("ticker", String(20), primary_key=True),  # yfinance 표기 (= price_daily.ticker)
    Column("asset_id", String(32), ForeignKey("assets.asset_id"), nullable=False),
    Column("added_by", String(20), nullable=False),  # API (서비스에서 처음 요청)
    Column("added_at", UtcDateTime, nullable=False),
)
