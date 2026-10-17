"""M02-04 테이블 정의 (SQLAlchemy Core). 이 패키지 밖에서 import 하지 않는다 (C-10).

새 데이터 계약(module_prototype2 2.2절)에 맞춘 v2 스키마. 자세한 내용은 DB_설계.md.

| 테이블 | 근거 |
|---|---|
| assets, index_constituent, price_daily, fx_daily, financials, news, fetch_log | 계약 읽기 테이블 |
| run_artifact, run_step, report | 계약 쓰기 테이블 (분석 쪽 쓰기 계정) |
| price_daily_source, financials_source, fx_daily_source | 수집기 내부: 출처별 원본 행·교차검증 |
| data_sources, extra_ticker | 수집기 내부: 출처 목록, 요청으로 늘어난 종목 |
| valuation_daily | 수집기 발행 (계약 밖 추가 읽기 테이블): 일별 PER·PBR·ROE·배당수익률 |
| gics_taxonomy | 참조 테이블 (계약 밖 추가 읽기): GICS 4단계 분류표 (Module2 §5) |
| disclosures | 수집기 발행 (계약 밖 추가 읽기 테이블): SEC EDGAR·DART 공시 목록과 유형 |

계약 테이블은 키와 최소 필드를 계약대로 두고, 필요한 칸만 더 붙인다 ("컬럼명은 DB 정의를 따름").
price_daily·financials 는 출처별 원본 테이블(*_source)에서 키마다 한 행을 골라 싣는 "발행"
테이블이다 (sql.py _publish_prices·_publish_financials). 예전 스키마(v1) DB 는
backend/scripts/migrate_v2.py 로 옮긴다.
PostgreSQL 기준으로 만들고 SQLite 에서도 같은 정의로 돈다 (방언별 타입은 with_variant).
시각은 UTC (C-05): PostgreSQL 은 timestamptz, SQLite 는 UTC 로 바꿔 저장하고 읽을 때 UTC 를 붙인다.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from sqlalchemy import (
    JSON,
    BigInteger,
    Boolean,
    CheckConstraint,
    Column,
    Date,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    MetaData,
    PrimaryKeyConstraint,
    String,
    Table,
    Text,
    TypeDecorator,
    UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.sql import false


class UtcDateTime(TypeDecorator[datetime]):
    """UTC 시각. PostgreSQL 은 timestamptz 그대로, SQLite 는 tz 없이 UTC 로 저장."""

    impl = DateTime(timezone=True)
    cache_ok = True

    def process_bind_param(self, value: datetime | None, dialect: Any) -> datetime | None:
        if value is None:
            return None
        if value.tzinfo is None:
            value = value.replace(tzinfo=UTC)
        value = value.astimezone(UTC)
        return value.replace(tzinfo=None) if dialect.name == "sqlite" else value

    def process_result_value(self, value: datetime | None, dialect: Any) -> datetime | None:
        if value is None:
            return None
        if value.tzinfo is None:
            return value.replace(tzinfo=UTC)
        return value.astimezone(UTC)


BigId = BigInteger().with_variant(Integer(), "sqlite")  # SQLite 는 INTEGER PK 라야 자동 증가
Json = JSON().with_variant(JSONB(), "postgresql")
Price = Float(precision=53)  # 배정밀도 (부록 B REAL, PostgreSQL double precision)

SOURCE_FK = "data_sources.source_name"

metadata = MetaData()

# ================================================================ 출처·종목 마스터 (assets = 계약)
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
    Column("market", String(10), nullable=False),  # US / KR (계약)
    Column("exchange", String(10)),  # KOSPI / KOSDAQ / NYSE / NASDAQ … (아는 경우만)
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
    # 추가 (v4): 종목 검색용 사전(Module2 §5)의 GICS 4단계 코드. 코드는 gics_taxonomy.code
    Column("gics_sector_code", String(2)),  # 45
    Column("gics_industry_group_code", String(4)),  # 4530
    Column("gics_industry_code", String(6)),  # 453010
    Column("gics_sub_industry_code", String(8)),  # 45301020
    Column("gics_sub_industry", String(100)),  # 세부산업 영문 이름 (읽기 편하게, 분류표와 같음)
    # 어디서 정했나: WIKIPEDIA_SP500 / OVERRIDE / NDX_FILE / KR_MAP_REVIEWED / KR_MAP_DRAFT /
    # KR_MAP_KSIC_AUTO / CONSTITUENT_<지수> / YAHOO_FALLBACK (섹터만)
    Column("gics_source", String(30)),
    Column("gics_updated_at", UtcDateTime),  # GICS 칸 값이 마지막으로 바뀐 시각
    Column("ksic_code", String(10)),  # 한국 종목: DART 기업개황 induty_code (KSIC 10차)
    Column("business_summary", Text),  # 사업 설명 (사전의 소개 문장 재료)
    Column("business_summary_source", String(30)),  # YFINANCE (longBusinessSummary) 등
    UniqueConstraint("market", "ticker", name="uq_assets_market_ticker"),
)

# ================================================================ 수집 이력·가격·환율·구성종목
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

price_daily_source = Table(
    # 출처별 원본 가격 (v1 의 price_daily). 교차검증 칸과 CONSENSUS 행(내부 검증 기록)도 여기 둔다
    "price_daily_source",
    metadata,
    Column("ticker", String(20), nullable=False),  # yfinance 표기 (MSFT, BRK-B, 005930.KS)
    Column("date", Date, nullable=False),
    Column("adj_close", Price, nullable=False),
    Column("volume", BigInteger),
    Column("currency", String(3), nullable=False, server_default="USD"),
    Column("source", String(40), ForeignKey(SOURCE_FK), nullable=False),
    Column("fetched_at", UtcDateTime, nullable=False),
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
    PrimaryKeyConstraint("ticker", "date", "source", name="price_daily_source_pkey"),
    CheckConstraint("adj_close > 0", name="ck_price_daily_source_adj_close"),
)
Index("idx_price_source_ticker_date", price_daily_source.c.ticker, price_daily_source.c.date)
Index(  # 교차검증 대기 행만 담는 부분 인덱스 (15분마다 찾음)
    "idx_price_source_unverified",
    price_daily_source.c.ticker,
    price_daily_source.c.date,
    postgresql_where=price_daily_source.c.verify_status.is_(None),
    sqlite_where=price_daily_source.c.verify_status.is_(None),
)

price_daily = Table(
    # 계약 가격 테이블: (asset_id, date) 마다 한 행. price_daily_source 에서 우선순위가 가장 높은
    # 출처의 원본 행을 그대로 싣는다 (값을 가공하지 않음, adj_close 는 출처 제공값)
    "price_daily",
    metadata,
    Column("asset_id", String(32), ForeignKey("assets.asset_id"), nullable=False),
    Column("date", Date, nullable=False),
    Column("ticker", String(20), nullable=False),  # yfinance 표기 (편의용 = yfinance_symbol)
    Column("open", Price),
    Column("high", Price),
    Column("low", Price),
    Column("close", Price),
    Column("adj_close", Price, nullable=False),
    Column("volume", BigInteger),
    Column("currency", String(3), nullable=False),  # 종목 통화 (US USD, KR KRW)
    Column("source", String(40), ForeignKey(SOURCE_FK), nullable=False),  # 실은 출처 행 (종가·OHLCV)
    # 추가 (v6): adj_close 를 가져온 출처 (한국은 종가 KIS, 배당까지 보정한 수정종가 yfinance)
    Column("adj_close_source", String(40)),
    Column("verify_status", String(10)),  # 교차검증 결과 (CONSENSUS 행 기준, 없으면 출처 행)
    Column("fetched_at", UtcDateTime, nullable=False),  # 실은 출처 행의 수집 시각
    Column("updated_at", UtcDateTime, nullable=False),  # 이 행의 값이 마지막으로 바뀐 시각
    PrimaryKeyConstraint("asset_id", "date", name="price_daily_pkey"),
    CheckConstraint("adj_close > 0", name="ck_price_daily_adj_close"),
)
Index("idx_price_daily_ticker_date", price_daily.c.ticker, price_daily.c.date)

fx_daily = Table(
    "fx_daily",
    metadata,
    Column("pair", String(6), nullable=False),  # USDKRW
    Column("date", Date, nullable=False),
    Column("rate", Price, nullable=False),  # 1 USD 당 KRW
    Column("source", String(40), ForeignKey(SOURCE_FK), nullable=False),
    Column("fetched_at", UtcDateTime, nullable=False),
    PrimaryKeyConstraint("pair", "date", name="fx_daily_pkey"),  # 계약 키 (v1 은 + source)
    CheckConstraint("rate > 0", name="ck_fx_daily_rate"),
)

fx_daily_source = Table(
    # 출처별 원본 환율 (YFINANCE KRW=X, FRED DEXKOUS). fx_daily 는 여기서 날짜마다 FX_PRIORITY 순으로
    # 한 출처를 골라 싣는다 (sql.py upsert_fx)
    "fx_daily_source",
    metadata,
    Column("pair", String(6), nullable=False),
    Column("date", Date, nullable=False),
    Column("source", String(40), ForeignKey(SOURCE_FK), nullable=False),
    Column("rate", Price, nullable=False),
    Column("fetched_at", UtcDateTime, nullable=False),
    PrimaryKeyConstraint("pair", "date", "source", name="fx_daily_source_pkey"),
    CheckConstraint("rate > 0", name="ck_fx_daily_source_rate"),
)

index_constituent = Table(
    "index_constituent",
    metadata,
    Column("index_code", String(10), nullable=False),
    Column("snapshot_date", Date, nullable=False),
    Column("ticker", String(20), nullable=False),  # 미국 yfinance 표기(BRK-B), 한국 6자리 코드
    Column("name", String(200)),
    Column("sector", String(60), nullable=False),
    Column("industry", String(100), nullable=False),
    Column("source", Text, nullable=False),  # 출처 이름 + URL (IndexConstituent.source)
    Column("fetched_at", UtcDateTime, nullable=False),
    # 추가: 종목 마스터 연결
    Column("asset_id", String(32), ForeignKey("assets.asset_id"), nullable=False),
    # 추가 (v4): 그 스냅샷 당시의 GICS 세부산업 코드 (industry 이름을 분류표로 정규화한 값)
    Column("gics_sub_industry_code", String(8)),
    PrimaryKeyConstraint("index_code", "snapshot_date", "ticker"),
)

# ================================================================ 계약 쓰기 테이블 (분석 쪽)
RUN_STATUSES = ("QUEUED", "STARTED", "SUCCESS", "PARTIAL", "FAILED", "CANCELLED")

run_artifact = Table(
    "run_artifact",
    metadata,
    Column("run_id", String(40), primary_key=True),
    Column("request_id", String(64), nullable=False),
    Column("created_at", UtcDateTime, nullable=False),
    Column("results_json", Json, nullable=False),  # 결과 통합 JSON
    Column("params_json", Json, nullable=False),  # 파라미터 스냅샷
    Column("llm_usage_json", Json),  # LLM 사용량
)

run_step = Table(
    "run_step",
    metadata,
    Column("run_id", String(40), nullable=False),
    Column("step", String(40), nullable=False),
    Column("status", String(10), nullable=False),
    Column("started_at", UtcDateTime),  # QUEUED 단계는 아직 시작 전
    Column("ended_at", UtcDateTime),
    Column("summary", Text),
    Column("error_code", String(60)),
    Column("error_message", Text),
    PrimaryKeyConstraint("run_id", "step", name="run_step_pkey"),
    CheckConstraint(
        "status IN (" + ", ".join(f"'{s}'" for s in RUN_STATUSES) + ")",
        name="ck_run_step_status",
    ),
)

report = Table(
    "report",
    metadata,
    Column(  # = run_id
        "report_id", String(40), ForeignKey("run_artifact.run_id"), primary_key=True
    ),
    Column("created_at", UtcDateTime, nullable=False),
    Column("doc_json", Json, nullable=False),  # 리포트 문서 JSON (한 번 쓰면 안 바꿈)
    Column("strategy_name", Text),
    Column("request_summary", Text),
    Column("as_of", Date, nullable=False),  # 분석 기준일
)

# ================================================================ 재무·뉴스
financials_source = Table(
    # 출처별 원본 재무 행 (v1 의 financials). 기간·연결구분·지표마다 한 행
    "financials_source",
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
        "asset_id", "source", "period", "fs_div", "metric", name="uq_financials_source_natural"
    ),
)
Index(
    "idx_financials_source_asset_disclosed",
    financials_source.c.asset_id,
    financials_source.c.disclosed_at,
)

FINANCIAL_STATEMENTS = ("IS", "BS", "CF", "ETC")

financials = Table(
    # 계약 재무 테이블: (asset_id, period_end, statement, item) 마다 한 행. financials_source 에서
    # 출처 우선순위 → 연결구분(CFS > OFS > -) → 가장 이른 공시일 순으로 한 행을 골라 싣는다
    "financials",
    metadata,
    Column("asset_id", String(32), ForeignKey("assets.asset_id"), nullable=False),
    Column("period_end", Date, nullable=False),  # 회계 기간 끝 날짜
    Column("statement", String(3), nullable=False),  # IS 손익 / BS 재무상태 / CF 현금흐름 / ETC
    Column("item", String(60), nullable=False),  # 지표 이름 (= financials_source.metric)
    Column("value", Price, nullable=False),
    Column("unit", String(10)),
    Column("report_date", Date, nullable=False),  # 보고일 (= 공시일 disclosed_at)
    Column("source", String(40), ForeignKey(SOURCE_FK), nullable=False),
    Column("fs_div", String(5), nullable=False, server_default="-"),  # CFS / OFS / -
    Column("period", String(20), nullable=False),  # 출처의 기간 이름 (2025_11011, FY2025)
    Column("updated_at", UtcDateTime, nullable=False),
    PrimaryKeyConstraint("asset_id", "period_end", "statement", "item", name="financials_pkey"),
    CheckConstraint(
        "statement IN (" + ", ".join(f"'{s}'" for s in FINANCIAL_STATEMENTS) + ")",
        name="ck_financials_statement",
    ),
)
Index("idx_financials_asset_report_date", financials.c.asset_id, financials.c.report_date)

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
    # 추가 (v5): 사실 태그 (collectors/news/labels.py 가 채움, 예전 행은 NULL)
    Column("is_press_release", Boolean),  # 회사 자체 발표 (보도자료·뉴스룸)
    Column("title_has_name", Boolean),  # 제목에 종목 이름·티커가 들어 있음
    Column("story_id", String(64)),  # 같은 사건을 다룬 기사 묶음
    Column("is_first_report", Boolean),  # 그 묶음에서 가장 먼저 나온 기사
    Column("available_on", Date),  # 이 기사를 쓸 수 있는 첫 거래일 (발행 시각·장 마감 기준)
    UniqueConstraint("asset_id", "url_hash", name="uq_news_natural"),
)
Index("idx_news_asset_published", news.c.asset_id, news.c.published_at)
Index("idx_news_asset_story", news.c.asset_id, news.c.story_id)  # is_first_report 계산용

disclosures = Table(
    # 추가 (v5): 공시 목록. 미국 SEC EDGAR (8-K·10-Q·10-K 등), 한국 DART. 한 공시가 여러 종목에
    # 걸리면 종목마다 한 행. available_on 이전에는 쓰지 않는다 (C-06 과 같은 규칙)
    "disclosures",
    metadata,
    Column("disclosure_id", BigId, primary_key=True, autoincrement=True),
    Column("asset_id", String(32), ForeignKey("assets.asset_id"), nullable=False),
    Column("source", String(40), ForeignKey(SOURCE_FK), nullable=False),  # SEC_EDGAR / DART
    Column("filing_id", String(30), nullable=False),  # SEC accession no. / DART rcept_no
    Column("form", String(30)),  # 8-K, 10-Q, 10-K / DART 보고서 종류
    Column("items", String(100)),  # 8-K item 번호 (2.02,9.01)
    Column("title", Text),  # 공시 제목 (DART report_nm, SEC 설명)
    Column("filed_at", UtcDateTime, nullable=False),  # 접수 시각
    Column("available_on", Date, nullable=False),  # 쓸 수 있는 첫 거래일
    # 정정 공시 (8-K/A, [기재정정])
    Column("is_amendment", Boolean, nullable=False, server_default=false()),
    Column("url", Text),
    Column("event_type", String(40)),  # 유형 규칙(collectors/disclosures/categories.py)의 결과
    Column("rule_version", String(20)),  # 그 규칙의 버전 (규칙을 바꾸면 다시 분류)
    Column("fetched_at", UtcDateTime, nullable=False),
    Column("fetch_log_id", BigInteger, ForeignKey("fetch_log.id")),
    UniqueConstraint("source", "filing_id", "asset_id", name="uq_disclosures_natural"),
)
Index("idx_disclosures_asset_available", disclosures.c.asset_id, disclosures.c.available_on)

# ========================================================= 추가: 일별 가치평가 (계약 밖 발행)
valuation_daily = Table(
    # 거래일마다 그날까지 공시된 재무만으로 계산한 가치평가 (선견 없음). 계약 price_daily·
    # financials 를 읽어 data/valuation.py 가 계산하고, 값이 바뀐 행만 다시 쓴다.
    # 값은 종목 통화 (US USD, KR KRW)
    "valuation_daily",
    metadata,
    Column("asset_id", String(32), ForeignKey("assets.asset_id"), nullable=False),
    Column("date", Date, nullable=False),
    Column("ticker", String(20), nullable=False),  # yfinance 표기
    Column("currency", String(3), nullable=False),
    Column("close", Price, nullable=False),  # 계약 price_daily.close 그대로 (분할 보정된 종가)
    # 분할 계수: 실제 그날 종가 = close × split_factor (close 를 받은 뒤 일어난 분할 반영)
    Column("split_factor", Price, nullable=False, server_default="1"),
    Column("shares_outstanding", Price),  # 그날 기준 유통주식수 (분할 반영, 실제 주식 수)
    Column("market_cap", Price),  # 실제 종가 × 유통주식수 (종목 통화)
    Column("net_income_ttm", Price),  # 최근 4분기 순이익 합 (지배주주 우선)
    Column("eps_ttm", Price),  # close 기준 주당순이익 = 순이익 TTM ÷ 주식수 ÷ split_factor
    Column("per", Price),  # = market_cap ÷ net_income_ttm (= close ÷ eps_ttm), 이익 ≤ 0 이면 NULL
    Column("bps", Price),  # close 기준 주당순자산
    Column("pbr", Price),  # = market_cap ÷ 자본총계, 자본 ≤ 0 이면 NULL
    Column("roe_ttm", Price),  # 순이익 TTM ÷ 평균 자본 (최근 분기말과 1년 전), 비율 (0.12 = 12%)
    Column("dps_ttm", Price),  # close 기준 주당배당금 (최근 4분기 또는 최근 사업연도)
    Column("dividend_yield", Price),  # 비율 (0.012 = 1.2%)
    Column("fin_period_end", Date),  # 순이익 TTM 의 마지막 분기 끝 날짜
    Column("fin_disclosed_at", Date),  # 그 값들을 쓸 수 있게 된 날 (공시일 중 가장 늦은 날)
    Column("shares_as_of", Date),  # 주식수 기준일
    Column("method", String(120)),  # 계산 방법 표시 (NI=4Q;SH=유통주식수;DPS=FY …)
    Column("updated_at", UtcDateTime, nullable=False),
    PrimaryKeyConstraint("asset_id", "date", name="valuation_daily_pkey"),
)
Index("idx_valuation_daily_date", valuation_daily.c.date)

# ======================================================= 추가: GICS 분류표 (참조 테이블, v4)
gics_taxonomy = Table(
    # backend/data/reference/gics_taxonomy.json 을 그대로 싣는 참조 자료 (서비스 저장 테이블이 아님, K1).
    # 분석 코드가 파일 없이 DB 만으로 코드·이름·상위 분류를 찾게 한다 (K3)
    "gics_taxonomy",
    metadata,
    Column("code", String(8), primary_key=True),  # 2/4/6/8자리
    Column("level", Integer, nullable=False),  # 1 섹터 / 2 산업그룹 / 3 산업 / 4 세부산업
    Column("name_en", String(100), nullable=False),  # GICS 공식 영문 이름
    Column("name_ko", String(100), nullable=False),  # 프로젝트 번역
    Column("parent_code", String(8)),  # 바로 위 단계 (섹터는 NULL)
    Column("updated_at", UtcDateTime, nullable=False),
    CheckConstraint("level BETWEEN 1 AND 4", name="ck_gics_taxonomy_level"),
)

# ================================================================ 추가: 요청으로 늘어난 종목
extra_ticker = Table(
    "extra_ticker",
    metadata,
    Column("ticker", String(20), primary_key=True),  # yfinance 표기 (= assets.yfinance_symbol)
    Column("asset_id", String(32), ForeignKey("assets.asset_id"), nullable=False),
    Column("added_by", String(20), nullable=False),  # API (서비스에서 처음 요청)
    Column("added_at", UtcDateTime, nullable=False),
)

SEED_SOURCES: list[tuple[str, str, str, str]] = [
    # (source_name, type, provides, description)
    ("YFINANCE", "QUANT", "price_daily, fx_daily", "Yahoo Finance (yfinance), 국내·해외 일봉·환율"),
    ("KIS", "QUANT", "price_daily", "한국투자증권 Open API, 국내 일봉"),
    ("DART", "QUANT", "financials", "OpenDART 재무제표"),
    ("TIINGO", "QUANT", "price_daily", "Tiingo 미국 일봉"),
    ("ALPACA", "QUANT", "price_daily", "Alpaca Markets 미국 일봉"),
    ("SEC_EDGAR", "QUANT", "financials", "SEC EDGAR companyfacts"),
    ("NAVER_NEWS", "QUAL", "news", "네이버 뉴스 검색"),
    ("GOOGLE_RSS", "QUAL", "news", "Google News RSS"),
    ("NEWSAPI", "QUAL", "news", "NewsAPI.org 영문 기사"),
    ("KIS_FIN", "QUANT", "financials", "KIS 국내주식 연간 재무 (2004~2014 사업연도 보충, DART 이전)"),
    ("FRED", "QUANT", "fx_daily", "FRED DEXKOUS 원/달러 환율 (미국 연준, 1981년~)"),
    ("ALPACA_NEWS", "QUAL", "news", "Alpaca News API (Benzinga) 미국 종목 기사, 2015년부터"),
    ("FNSPID", "QUAL", "news", "FNSPID 데이터셋 (Hugging Face) 미국 종목 기사 목록, 1999~2023"),
    (
        "VALUATION",
        "QUANT",
        "valuation_daily",
        "일별 가치평가 계산 (price_daily + financials, 내부)",
    ),
    ("CONSENSUS", "QUANT", "price_daily_source", "출처별 중앙값 교차검증 행 (내부 기록)"),
    ("WIKIPEDIA", "META", "index_constituent", "위키백과 S&P 500·Nasdaq-100 구성종목 표"),
    ("KRX", "META", "index_constituent", "한국거래소 KOSPI 200 구성종목"),
    (
        "GICS",
        "META",
        "assets, index_constituent, gics_taxonomy",
        "종목별 GICS 분류 (분류표·위키백과·kr_gics.csv·KSIC·Yahoo 대체, 내부)",
    ),
]
