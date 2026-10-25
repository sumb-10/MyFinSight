"""M02-04 SqlRepository: MarketDataRepository 의 SQLAlchemy Core 구현 (PostgreSQL·SQLite 공용).

같은 코드가 PostgreSQL(기본, AWS Lightsail)과 SQLite(테스트·혼자 개발)에서 돈다. upsert 는 방언
전용 문법(ON CONFLICT 등) 없이 "읽어서 비교 → 새 행 INSERT / 값이 다른 행 UPDATE" 로 한다.

다른 모듈과의 약속 (C-10)
- 종목은 yfinance 표기(005930.KS, BRK-B)로 주고받는다. DB 의 종목 키는 asset_id(KR-005930,
  US-BRK-B) 이고 종목 마스터(assets)와 잇는다. 처음 보는 종목은 assets 에 기본 행을 만든다.
- 출처(source)는 이름 문자열. 대문자로 맞춘다 ("yfinance" → YFINANCE). 처음 보는 출처는
  data_sources 에 추가한다.

원본과 발행 (데이터 계약 module_prototype2 2.2절)
- 수집한 행은 출처별 원본 테이블(price_daily_source, financials_source)에 쌓는다.
- 같은 트랜잭션 안에서 바뀐 키만 다시 골라 계약 테이블(price_daily, financials)에 싣는다
  (_publish_prices, _publish_financials). 고른 값이 그대로면 계약 테이블 행도 다시 쓰지 않는다.
- 분석 쪽은 계약 테이블만 읽고, 한 번의 저장(트랜잭션)이 끝나야 함께 보인다 (날짜 단위 일관성).

값 비교 기준 (같은 키로 다시 받으면 값이 다를 때만 갱신, 수집 시각은 비교 안 함)
- price_daily_source : adj_close, volume, currency, open, high, low, close
- price_daily        : 위 값 + ticker, source, verify_status
- fx_daily           : rate, source
- financials_source  : value, unit, fiscal_year, report_code, period_end, disclosed_at, rcept_no
- financials         : value, unit, report_date, source, fs_div, period
- news               : title, content, publisher, published_at, language
- valuation_daily    : 키(asset_id, date) 를 뺀 모든 계산 칸 (updated_at 제외)

동시 실행 (PC 백필 + GitHub Actions 정기 수집): PostgreSQL 에서는 쓰는 트랜잭션마다
pg_advisory_xact_lock 으로 같은 테이블(가격 원본은 같은 출처)을 한 번에 하나씩 쓴다 (_lock).
읽어서 비교하는 upsert 가 같은 키를 동시에 INSERT 해 키 중복으로 실패하지 않게 하기 위함.
"""

from __future__ import annotations

import hashlib
import logging
import math
import re
import threading
import time
import zlib
from collections import defaultdict
from collections.abc import Callable, Iterable, Iterator, Sequence
from contextlib import contextmanager, nullcontext
from datetime import UTC, date, datetime, timedelta
from typing import Any

import pandas as pd
from pydantic import ValidationError
from sqlalchemy import (
    Engine,
    and_,
    bindparam,
    delete,
    func,
    insert,
    inspect,
    or_,
    select,
    text,
    tuple_,
    update,
)
from sqlalchemy.exc import DBAPIError, OperationalError, SQLAlchemyError

from backend.db import tables as T
from backend.db.analysis_readers import AnalysisReadersMixin
from backend.pipeline import news_labels
from backend.pipeline.normalizer import (
    constituent_ticker,
    currency_of_symbol,
    default_asset,
    normalize_ticker,
)
from backend.schemas.errors import RepositoryError
from backend.schemas.market import (
    FxRate,
    IndexCode,
    IndexConstituent,
    PriceBar,
    PriceMeta,
)
from backend.schemas.market_ext import AssetInfo, DisclosureRow, FinancialRow, NewsRow
from backend.schemas.runlog import StepRecord

logger = logging.getLogger(__name__)

EPOCH = datetime(1970, 1, 1, tzinfo=UTC)
CONSENSUS = "CONSENSUS"
START_GRACE_DAYS = 4
"""요청 시작일이 휴장일(주말·공휴일)이어도 매번 재수집하지 않도록, 첫 저장일이 시작일 뒤
이 일수 안이면 시작 쪽은 덮인 것으로 본다."""
_CHUNK = 500  # IN (...) 에 넣는 키 개수 상한
DEFAULT_CLOSE_PRIORITY: dict[str, tuple[str, ...]] = {
    # 한국: 종가·OHLCV·거래량은 거래소 공식 API(KIS) 먼저 (yfinance 는 빈 날만)
    "KRW": ("KIS", "YFINANCE"),
}
"""계약 price_daily 의 종가·OHLCV·거래량(source 칸)을 가져올 출처 순서. 통화가 없으면 price_priority 와 같음.
adj_close 는 price_priority(DEFAULT_PRICE_PRIORITY, .env PRICE_PRIORITY_*) 순서로 따로 고른다."""

DEFAULT_PRICE_PRIORITY: dict[str, tuple[str, ...]] = {
    # 미국: 공식 API(Alpaca) → Tiingo → yfinance (모두 분할+배당 보정 수정종가)
    "USD": ("ALPACA", "TIINGO", "YFINANCE"),
    # 한국: KIS 수정주가는 배당을 반영하지 않으므로 수정종가는 yfinance 먼저, 빈 날은 KIS
    "KRW": ("YFINANCE", "KIS"),
}
"""계약 price_daily 의 adj_close(분할+배당 보정 수정종가) 출처 순서 (같은 (종목, 날짜) 에서 앞선 출처).
CONSENSUS(교차검증 중앙값)는 가공한 값이라 싣지 않고 verify_status 만 가져온다."""

FIN_SOURCE_PRIORITY: dict[str, tuple[str, ...]] = {
    "KR": ("DART",),
    "US": ("SEC_EDGAR",),
}
"""계약 financials 에 싣는 재무 출처 순서 (시장별). 목록 밖 출처는 뒤에 이름 순."""
FS_DIV_ORDER = ("CFS", "OFS", "-")
"""연결구분 순서: 연결(CFS) → 별도(OFS) → 구분 없음."""

STATEMENT_OF_ITEM: dict[str, str] = {
    # 손익계산서 (DART 주요계정 · SEC EDGAR 연간·TTM)
    **dict.fromkeys(
        (
            "매출액",
            "수익(매출액)",
            "영업수익",
            "영업이익",
            "영업이익(손실)",
            "법인세차감전순이익",
            "법인세차감전순이익(손실)",
            "당기순이익",
            "당기순이익(손실)",
            "총포괄손익",
            "EPS(희석)",
            "EPS(희석·분기)",
            "EPS(TTM)",
            "EPS(연간·현재기준)",
            "순이익(TTM)",
            "지배주주순이익",
        ),
        "IS",
    ),
    # 재무상태표
    **dict.fromkeys(
        (
            "유동자산",
            "비유동자산",
            "자산총계",
            "유동부채",
            "비유동부채",
            "부채총계",
            "자본금",
            "이익잉여금",
            "이익잉여금(결손금)",
            "자본총계",
            "자본총계(최근)",
        ),
        "BS",
    ),
    # 현금흐름표 (지금 수집기는 만들지 않지만 들어오면 CF 로)
    **dict.fromkeys(
        ("영업활동현금흐름", "투자활동현금흐름", "재무활동현금흐름", "현금및현금성자산의증가"),
        "CF",
    ),
}
"""지표 이름(financials_source.metric = financials.item) → 재무제표 구분. 띄어쓰기는 무시.
"<항목>(분기)"(3개월 값)·"<항목>(누적)"(당기 누적)은 <항목> 과 같은 구분.
발행주식수·유통주식수·자기주식수·주당배당금·배당금총액·주식분할·BPS 처럼 어느 표에도 속하지 않거나
모르는 지표는 ETC."""
_STATEMENT_KEYS = {k.replace(" ", ""): v for k, v in STATEMENT_OF_ITEM.items()}
_PERIOD_SUFFIX = re.compile(r"\((분기|누적)\)$")


def statement_of(item: str) -> str:
    """지표 이름 → IS / BS / CF / ETC (STATEMENT_OF_ITEM, 띄어쓰기·(분기)·(누적) 무시)."""
    key = item.replace(" ", "")
    return _STATEMENT_KEYS.get(key) or _STATEMENT_KEYS.get(_PERIOD_SUFFIX.sub("", key), "ETC")


_UNVERIFIED = {"verify_status": None, "dev_pct": None, "adj_dev_pct": None}
_CONSENSUS_VALUE_COLS = (
    "adj_close",
    "close",
    "volume",
    "currency",
    "source_count",
    "dev_pct",
    "adj_dev_pct",
    "verify_status",
    "outlier_sources",
)
_PRICE_SOURCE_VALUE_COLS = ("adj_close", "volume", "currency", "open", "high", "low", "close")
_PRICE_PUBLISH_VALUE_COLS = (
    "ticker",
    "open",
    "high",
    "low",
    "close",
    "adj_close",
    "adj_close_source",
    "volume",
    "currency",
    "source",
    "verify_status",
)
_FIN_SOURCE_VALUE_COLS = (
    "value",
    "unit",
    "fiscal_year",
    "report_code",
    "period_end",
    "disclosed_at",
    "rcept_no",
)
_FIN_PUBLISH_VALUE_COLS = ("value", "unit", "report_date", "source", "fs_div", "period")
_GICS_TAXONOMY_COLS = ("level", "name_en", "name_ko", "parent_code")
GICS_COLS = (
    "gics_sector_code",
    "gics_industry_group_code",
    "gics_industry_code",
    "gics_sub_industry_code",
    "gics_sub_industry",
    "gics_source",
)
"""assets 의 GICS 칸 (값이 하나라도 바뀌면 gics_updated_at 을 새로 씀)."""
PROFILE_COLS = (*GICS_COLS, "ksic_code", "business_summary", "business_summary_source")
"""update_asset_profiles 가 바꿀 수 있는 assets 칸 (upsert_assets 는 이 칸을 건드리지 않음)."""
_ASSET_VALUE_COLS = (
    "ticker",
    "name",
    "market",
    "exchange",
    "asset_type",
    "currency",
    "yfinance_symbol",
    "dart_corp_code",
    "sec_cik",
    "kis_ticker",
    "tiingo_symbol",
    "alpaca_symbol",
)


def previous_weekday(d: date, n: int = 1) -> date:
    """d 이전 n 번째 평일 (공휴일은 고려하지 않음)."""
    out = d
    left = n
    while left > 0:
        out -= timedelta(days=1)
        if out.weekday() < 5:
            left -= 1
    return out


def source_key(name: str) -> str:
    """출처 문자열 → data_sources.source_name. "wikipedia:S&P 500 https://…" → WIKIPEDIA."""
    return name.split(":", 1)[0].strip().upper() or "UNKNOWN"


def _same(old: Any, new: Any) -> bool:
    """저장값과 새 값이 같은가. 실수는 상대오차 1e-9 안이면 같음 (계산 순서에 따른 끝자리 차이)."""
    if isinstance(old, float) and isinstance(new, (int, float)) and not isinstance(new, bool):
        return math.isclose(old, float(new), rel_tol=1e-9, abs_tol=1e-12)
    return old == new


def _chunks(items: Sequence[Any], size: int = _CHUNK) -> Iterable[Sequence[Any]]:
    for i in range(0, len(items), size):
        yield items[i : i + size]


def url_hash(url: str) -> str:
    """news.url_hash: 기사 주소의 SHA-256 (중복 판단 키)."""
    return hashlib.sha256(url.encode("utf-8")).hexdigest()


def _migrate_news_url_hash(conn: Any) -> None:
    """url_hash 칸이 없던 예전 news 테이블을 고침: 칸 추가 → 기존 행 채움 → 중복 키 교체."""
    if "url_hash" in {c["name"] for c in inspect(conn).get_columns("news")}:
        return
    conn.execute(text("ALTER TABLE news ADD COLUMN url_hash VARCHAR(64)"))
    rows = conn.execute(text("SELECT news_id, url FROM news")).all()
    if rows:
        conn.execute(
            text("UPDATE news SET url_hash = :h WHERE news_id = :i"),
            [{"h": url_hash(u), "i": i} for i, u in rows],
        )
    if conn.dialect.name == "postgresql":
        conn.execute(text("ALTER TABLE news DROP CONSTRAINT IF EXISTS uq_news_natural"))
        conn.execute(text("ALTER TABLE news ALTER COLUMN url_hash SET NOT NULL"))
        conn.execute(
            text("ALTER TABLE news ADD CONSTRAINT uq_news_natural UNIQUE (asset_id, url_hash)")
        )
    else:  # SQLite 는 표 제약을 못 지워서 새 고유 인덱스를 더함 (예전 제약은 남음)
        conn.execute(
            text("CREATE UNIQUE INDEX IF NOT EXISTS uq_news_url_hash ON news (asset_id, url_hash)")
        )


_REPORT_PERIOD = re.compile(r"\((\d{4})\.(\d{2})\)")
"""DART 정기보고서 제목의 결산년월: 사업보고서 (2008.12)."""

DISCLOSURE_KEY = ("asset_id", "source", "filing_id")
"""disclosures 자연키 (uq_disclosures_natural). 종목이 앞: 기존 행을 종목 단위로 읽음."""

RECONNECT_WAITS = (5.0, 20.0, 60.0)
"""DB 연결이 끊겼을 때(서버 재시작·유지보수 등) 다시 시도하기 전에 쉬는 시간(초). 다 쓰면 오류."""
_sleep = time.sleep


def _disconnected(exc: BaseException) -> bool:
    """서버가 연결을 끊은 오류인가 (다시 연결하면 될 수 있는 것만, SQL 오류는 아님)."""
    if isinstance(exc, DBAPIError) and exc.connection_invalidated:
        return True
    if not isinstance(exc, OperationalError):
        return False
    text_ = str(exc).lower()
    return any(
        s in text_
        for s in ("server closed the connection", "connection", "terminating", "ssl syscall")
    )


def _retry_later(what: str, attempt: int, exc: BaseException) -> None:
    wait = RECONNECT_WAITS[attempt]
    logger.warning("%s: DB 연결 끊김, %.0f초 뒤 다시 (%d번째): %s", what, wait, attempt + 1,
                   str(exc).splitlines()[0])  # fmt: skip
    _sleep(wait)


FX_PRIORITY = ("YFINANCE", "FRED")
"""fx_daily 에 실을 환율 출처 순서 (그날 값이 있는 첫 출처)."""


def _publish_fx(conn: Any, keys: list[tuple[str, date]]) -> int:
    """(통화쌍, 날짜)마다 fx_daily_source 에서 FX_PRIORITY 순으로 한 행을 골라 fx_daily 에 싣는다."""
    s = T.fx_daily_source
    order = {name: i for i, name in enumerate(FX_PRIORITY)}
    best: dict[tuple[str, date], dict[str, Any]] = {}
    for pair in sorted({k[0] for k in keys}):
        dates = sorted(d for p, d in keys if p == pair)
        for part in _chunks(dates):
            q = select(s.c.pair, s.c.date, s.c.source, s.c.rate, s.c.fetched_at).where(
                s.c.pair == pair, s.c.date.in_(part)
            )
            for r in conn.execute(q):
                key = (r.pair, r.date)
                rank = (order.get(r.source, len(order)), r.source)
                old = best.get(key)
                if old is None or rank < old["_rank"]:
                    best[key] = {**r._asdict(), "_rank": rank}
    rows = [{k: v for k, v in r.items() if k != "_rank"} for r in best.values()]
    return SqlRepository._upsert(conn, T.fx_daily, ("pair", "date"), ("rate", "source"), rows)


def _copy_fx_to_source(conn: Any) -> None:
    """fx_daily_source 가 새로 생겨 비어 있으면 기존 fx_daily 행을 원본으로 옮겨 둔다 (한 번만)."""
    if conn.execute(select(T.fx_daily_source.c.pair).limit(1)).first() is not None:
        return
    f = T.fx_daily
    conn.execute(
        T.fx_daily_source.insert().from_select(
            ["pair", "date", "source", "rate", "fetched_at"],
            select(f.c.pair, f.c.date, f.c.source, f.c.rate, f.c.fetched_at),
        )
    )


_PUBLISH_LOCKS = {"price_daily": 0x6D7966_01, "financials": 0x6D7966_02}
"""발행 단계에서 잡는 PostgreSQL 트랜잭션 잠금 번호 (pg_advisory_xact_lock)."""


def lock_key(name: str) -> int:
    """잠금 이름 → PostgreSQL advisory lock 번호 (발행 잠금과 겹치지 않는 범위)."""
    return 0x6D79_0000_0000 + zlib.crc32(name.encode("utf-8"))


def _lock(conn: Any, name: str) -> None:
    """PostgreSQL 이면 이 트랜잭션이 끝날 때까지 name 으로 잠금 (같은 이름끼리 한 번에 하나).

    PC 백필과 GitHub Actions 가 같은 테이블을 동시에 upsert 해도 키 중복이 나지 않게 한다.
    """
    if conn.dialect.name == "postgresql":
        conn.execute(text("SELECT pg_advisory_xact_lock(:k)"), {"k": lock_key(name)})


def _lock_publish(conn: Any, table: str) -> None:
    """PostgreSQL 이면 발행 단계를 트랜잭션 끝까지 한 번에 하나만 돌게 잠근다.

    가격은 출처 줄마다 스레드가 동시에 저장한다 (jobs.price_step). 잠그지 않으면 두 트랜잭션이
    서로의 미확정 원본 행을 못 본 채 같은 (종목, 날짜) 를 동시에 넣거나(키 중복) 순위가 낮은 출처
    값을 나중에 덮어쓸 수 있다. 잠금을 기다린 쪽은 앞 트랜잭션이 확정한 행까지 다시 읽고 고른다
    (READ COMMITTED). 원본 저장은 잠그지 않으므로 출처별 저장은 계속 겹친다. SQLite 는 쓰기가 원래
    하나씩이라 할 일 없음.
    """
    if conn.dialect.name == "postgresql":
        conn.execute(text("SELECT pg_advisory_xact_lock(:k)"), {"k": _PUBLISH_LOCKS[table]})


NEWS_VALUE_COLS = (
    "title", "content", "publisher", "published_at", "language",
    "is_press_release", "title_has_name", "story_id", "available_on",
)  # fmt: skip
"""뉴스 upsert 에서 값이 바뀌면 고치는 칸 (사실 표시 포함)."""


def news_asset_names(conn: Any, asset_ids: Iterable[str]) -> dict[str, news_labels.AssetNames]:
    """사실 표시 계산에 쓰는 종목 이름·시장·코드."""
    a = T.assets
    q = select(a.c.asset_id, a.c.market, a.c.ticker, a.c.name).where(
        a.c.asset_id.in_(sorted(set(asset_ids)))
    )
    return {r.asset_id: news_labels.AssetNames(*r) for r in conn.execute(q)}


def mark_first_reports(conn: Any, groups: Iterable[tuple[str, str | None]]) -> int:
    """(종목, 묶음) 마다 가장 먼저 발행된 기사만 is_first_report = TRUE (같은 시각이면 news_id 순).
    값이 바뀐 행 수."""
    n = T.news
    by_asset: dict[str, set[str]] = defaultdict(set)
    for aid, sid in groups:
        if sid:
            by_asset[aid].add(sid)
    changed: list[dict[str, Any]] = []
    for aid, sids in by_asset.items():
        for part in _chunks(sorted(sids)):
            q = (
                select(n.c.news_id, n.c.story_id, n.c.is_first_report)
                .where(n.c.asset_id == aid, n.c.story_id.in_(part))
                .order_by(n.c.story_id, n.c.published_at, n.c.news_id)
            )
            seen: set[str] = set()
            for r in conn.execute(q):
                first = r.story_id not in seen
                seen.add(r.story_id)
                if r.is_first_report is not first:
                    changed.append({"nid": r.news_id, "v": first})
    if changed:
        conn.execute(
            n.update()
            .where(n.c.news_id == bindparam("nid"))
            .values(is_first_report=bindparam("v")),
            changed,
        )
    return len(changed)


def missing_columns(conn: Any) -> dict[str, list[str]]:
    """코드(tables.py)에는 있는데 DB 의 기존 테이블에 없는 칸 {테이블: [칸]} (없는 테이블은 뺌).

    v3 DB 에 v4 칸(assets.gics_* 등)을 더할 때 backend/scripts/migrate_v2.py 가 쓰고, 저장소는 열 때 이것이
    비어 있지 않으면 멈춘다 (옮기지 않은 DB 에 새 코드가 쓰지 않게).
    """
    insp = inspect(conn)
    have = set(insp.get_table_names())
    out: dict[str, list[str]] = {}
    for name, table in T.metadata.tables.items():
        if name not in have:
            continue
        cols = {c["name"] for c in insp.get_columns(name)}
        miss = [c.name for c in table.columns if c.name not in cols]
        if miss:
            out[name] = miss
    return out


def seed_gics_taxonomy(conn: Any, now: datetime, *, only_if_empty: bool = True) -> int:
    """gics_taxonomy 를 backend/data/reference/gics_taxonomy.json 으로 채움. 바뀐 행 수.

    only_if_empty 면 비어 있을 때만 (저장소를 열 때마다 읽지 않게). 파일이 없으면 0.
    """
    from backend.pipeline.gics import TAXONOMY_FILE, reference_file, taxonomy_from_file

    g = T.gics_taxonomy
    if only_if_empty and conn.execute(select(g.c.code).limit(1)).first() is not None:
        return 0
    path = reference_file(TAXONOMY_FILE)
    if not path.exists():
        logger.warning("GICS 분류표 파일 없음: %s (gics_taxonomy 를 채우지 않음)", path)
        return 0
    rows = [{**r, "updated_at": now} for r in taxonomy_from_file(path).rows()]
    return SqlRepository._upsert(conn, g, ("code",), _GICS_TAXONOMY_COLS, rows)


def is_v1_schema(conn: Any) -> bool:
    """예전(v1) 스키마 DB 인가: price_daily 가 출처별 원본 모양(source_count 칸)이면 v1.

    v1 DB 는 backend/scripts/migrate_v2.py 로 옮긴 뒤 연다 (그대로 열면 새 테이블과 섞임).
    """
    insp = inspect(conn)
    if not insp.has_table("price_daily"):
        return False
    return "source_count" in {c["name"] for c in insp.get_columns("price_daily")}


class SqlRepository(AnalysisReadersMixin):
    """PostgreSQL·SQLite 저장소. 보통 `open_repository()` 로 만든다.

    cache_max_age_days: needs_fetch 가 요구하는 마지막 저장일 = 오늘 기준 n 번째 이전 평일
    (AppConfig.data.cache_max_age_days, 기본 1 = 직전 거래일).
    clock: created_at·updated_at 에 쓸 현재 시각 (테스트에서 고정 가능).
    price_priority: 통화별 adj_close 출처 우선순위 (기본 DEFAULT_PRICE_PRIORITY).
    close_priority: 통화별 종가·OHLCV 출처 우선순위 (기본 DEFAULT_CLOSE_PRIORITY, 없는 통화는 price_priority).
    """

    def __init__(
        self,
        engine: Engine,
        *,
        cache_max_age_days: int = 1,
        clock: Callable[[], datetime] = lambda: datetime.now(UTC),
        create_tables: bool = True,
        price_priority: dict[str, Sequence[str]] | None = None,
        close_priority: dict[str, Sequence[str]] | None = None,
    ) -> None:
        self.engine = engine
        # SQLite 는 연결 하나를 여러 스레드가 함께 쓰면(메모리 DB 의 StaticPool) 행이 섞인다 → 접근을 한 번에 하나로.
        # PostgreSQL 은 연결 풀이 있어 잠그지 않는다 (분석 러너가 단계·리밸런싱일을 병렬로 돈다, 라운드 4).
        self._io_lock: Any = threading.RLock() if engine.dialect.name == "sqlite" else nullcontext()
        self.cache_max_age_days = max(1, cache_max_age_days)
        self.price_priority = {
            cur: tuple(source_key(x) for x in names)
            for cur, names in (price_priority or DEFAULT_PRICE_PRIORITY).items()
        }
        close = {**self.price_priority, **(close_priority or DEFAULT_CLOSE_PRIORITY)}
        self.close_priority = {
            cur: tuple(source_key(x) for x in names) for cur, names in close.items()
        }
        self._clock = clock
        self._known_sources: set[str] = set()
        if create_tables:
            self._write("테이블 생성", self._create)

    @property
    def dialect(self) -> str:
        """DB 종류 (postgresql / sqlite)."""
        return self.engine.dialect.name

    def _create(self, conn: Any) -> None:
        if is_v1_schema(conn):
            raise RepositoryError(
                "예전(v1) 스키마 DB 임: python backend/scripts/migrate_v2.py 로 확인한 뒤 --apply 로 옮김"
                " (DB_설계.md)",
                code="REPO_WRITE_FAILED",
                details={"schema": "v1"},
            )
        # 테이블을 만들기 전에 검사 (SQLite 는 DDL 을 되돌리지 못하므로 거절할 DB 는 건드리지 않음).
        # news.url_hash 는 아래 _migrate_news_url_hash 가 채운다.
        missing = missing_columns(conn)
        if "url_hash" in missing.get("news", []):
            missing["news"].remove("url_hash")
        missing = {t: c for t, c in missing.items() if c}
        if missing:
            raise RepositoryError(
                "DB 에 새 칸이 없음 (v4 GICS 칸 등): python backend/scripts/migrate_v2.py 로 확인한 뒤"
                f" --apply 로 더함 (DB_설계.md). 없는 칸: {missing}",
                code="REPO_WRITE_FAILED",
                details={"missing_columns": missing},
            )
        T.metadata.create_all(conn)
        _migrate_news_url_hash(conn)
        _copy_fx_to_source(conn)
        seed_gics_taxonomy(conn, self._clock())
        have = set(conn.execute(select(T.data_sources.c.source_name)).scalars())
        rows = [
            {"source_name": n, "type": t, "provides": p, "description": d}
            for n, t, p, d in T.SEED_SOURCES
            if n not in have
        ]
        if rows:
            self._insert_many(conn, T.data_sources, rows)

    # ------------------------------------------------------------------ 공통
    def _write(self, what: str, fn: Callable[[Any], Any]) -> Any:
        for attempt in range(len(RECONNECT_WAITS) + 1):
            try:
                with self._io_lock, self.engine.begin() as conn:
                    return fn(conn)
            except RepositoryError:
                raise
            except (SQLAlchemyError, ValueError, TypeError) as exc:
                if _disconnected(exc) and attempt < len(RECONNECT_WAITS):
                    _retry_later(what, attempt, exc)  # 트랜잭션은 되돌려졌으니 통째로 다시
                    continue
                raise RepositoryError(
                    f"{what} 저장 실패: {exc}", code="REPO_WRITE_FAILED", details={"what": what}
                ) from exc
        raise AssertionError("도달하지 않음")

    def _read(self, what: str, fn: Callable[[Any], Any]) -> Any:
        for attempt in range(len(RECONNECT_WAITS) + 1):
            try:
                with self._io_lock, self.engine.connect() as conn:
                    return fn(conn)
            except RepositoryError:
                raise
            except (SQLAlchemyError, ValidationError, ValueError, TypeError) as exc:
                if _disconnected(exc) and attempt < len(RECONNECT_WAITS):
                    _retry_later(what, attempt, exc)
                    continue
                raise RepositoryError(
                    f"{what} 조회 실패: {exc}", code="REPO_READ_FAILED", details={"what": what}
                ) from exc
        raise AssertionError("도달하지 않음")

    @staticmethod
    def _upsert(
        conn: Any,
        table: Any,
        key_cols: Sequence[str],
        value_cols: Sequence[str],
        rows: list[dict[str, Any]],
        *,
        changed_keys: list[tuple[Any, ...]] | None = None,
    ) -> int:
        """자연키로 기존 행을 읽어 비교한 뒤 새 행은 INSERT, 값이 다른 행만 UPDATE. 반영 행 수.

        changed_keys 에 목록을 주면 새로 넣거나 바꾼 행의 키를 덧붙인다 (발행 테이블 갱신용).
        """
        if not rows:
            return 0
        latest: dict[tuple[Any, ...], dict[str, Any]] = {}
        for r in rows:  # 입력 안에서 같은 키가 겹치면 뒤의 값이 이긴다
            latest[tuple(r[k] for k in key_cols)] = r
        first = key_cols[0]
        existing: dict[tuple[Any, ...], tuple[Any, ...]] = {}
        firsts = sorted({k[0] for k in latest})
        cols = [table.c[c] for c in (*key_cols, *value_cols)]
        # 기존 행은 입력과 같은 날짜 범위·출처만 읽음 (종목 전체 이력을 원격 DB 에서 끌어오지 않게)
        narrow = []
        for i, c in enumerate(key_cols[1:], start=1):
            vals = {k[i] for k in latest}
            if c == "date":
                narrow.append(table.c[c].between(min(vals), max(vals)))
            elif c == "source":
                narrow.append(table.c[c].in_(sorted(vals)))
        for part in _chunks(firsts):
            q = select(*cols).where(table.c[first].in_(part), *narrow)
            for row in conn.execute(q):
                existing[tuple(row[: len(key_cols)])] = tuple(row[len(key_cols) :])
        to_insert: list[dict[str, Any]] = []
        changed: list[dict[str, Any]] = []
        diff_cols: dict[str, int] = defaultdict(int)
        for key, r in latest.items():
            vals = tuple(r[c] for c in value_cols)
            if key not in existing:
                to_insert.append(r)
                continue
            diffs = [
                c
                for c, old, new in zip(value_cols, existing[key], vals, strict=True)
                if not _same(old, new)
            ]
            if diffs:
                changed.append(r)
                for c in diffs:
                    diff_cols[c] += 1
        if changed:  # 다시 받은 값이 바뀐 칸 (원인 확인용)
            logger.info("%s: 값이 바뀐 행 %d (칸별 %s)", table.name, len(changed), dict(diff_cols))
        if changed:  # 키 칸을 뺀 나머지 칸 전부를 새 값으로 (행 단위 UPDATE 와 같은 결과)
            rest = [c for c in changed[0] if c not in key_cols]
            same = [r for r in changed if list(r) == list(changed[0])]
            other = [r for r in changed if list(r) != list(changed[0])]
            SqlRepository._bulk_update(conn, table, key_cols, rest, same)
            for r in other:
                cond = and_(*(table.c[k] == r[k] for k in key_cols))
                conn.execute(update(table).where(cond).values(**r))
        if to_insert:
            SqlRepository._insert_many(conn, table, to_insert)
        if changed_keys is not None:
            changed_keys.extend(tuple(r[k] for k in key_cols) for r in (*to_insert, *changed))
        return len(to_insert) + len(changed)

    @staticmethod
    def _insert_many(conn: Any, table: Any, rows: Sequence[dict[str, Any]]) -> None:
        """여러 행 INSERT. PostgreSQL 은 INSERT ... VALUES (...), (...) 한 문장씩 묶어 보냄
        (드라이버와 상관없이 원격 DB 왕복·문장 수가 적음). 칸 구성이 같은 행끼리 묶는다."""
        if not rows:
            return
        if conn.dialect.name != "postgresql":
            conn.execute(insert(table), list(rows))
            return
        groups: dict[tuple[str, ...], list[dict[str, Any]]] = defaultdict(list)
        for r in rows:
            groups[tuple(r)].append(r)
        for cols, group in groups.items():
            for part in _chunks(group, max(1, 30000 // max(1, len(cols)))):
                conn.execute(insert(table).values(list(part)))

    @staticmethod
    def _bulk_update(
        conn: Any,
        table: Any,
        key_cols: Sequence[str],
        value_cols: Sequence[str],
        rows: list[dict[str, Any]],
    ) -> None:
        """자연키로 여러 행을 갱신. PostgreSQL 은 UPDATE ... FROM (VALUES ...) 한 문장에 묶어
        원격 DB 왕복·문장 수를 줄인다 (executemany 는 행마다 UPDATE 문장). rows 는 칸 이름대로."""
        if not rows:
            return
        cols = [*key_cols, *value_cols]
        if conn.dialect.name != "postgresql":
            stmt = (
                update(table)
                .where(*(table.c[k] == bindparam(f"k_{k}") for k in key_cols))
                .values({c: bindparam(f"v_{c}") for c in value_cols})
            )
            conn.execute(
                stmt,
                [
                    {**{f"k_{k}": r[k] for k in key_cols}, **{f"v_{c}": r[c] for c in value_cols}}
                    for r in rows
                ],
            )
            return
        types = {c: table.c[c].type.compile(dialect=conn.dialect) for c in cols}
        size = max(1, 20000 // len(cols))  # 문장 하나의 바인드 값 수 제한(65535) 안
        name = table.name
        set_sql = ", ".join(f"{c} = v.{c}" for c in value_cols)
        where_sql = " AND ".join(f"t.{k} = v.{k}" for k in key_cols)
        for i in range(0, len(rows), size):
            part = rows[i : i + size]
            params: dict[str, Any] = {}
            binds: list[Any] = []
            values: list[str] = []
            for j, r in enumerate(part):
                cells = []
                for n, c in enumerate(cols):
                    params[f"p{j}_{n}"] = r[c]
                    # 칸 타입을 붙여 JSON 등 값 변환이 일반 INSERT·UPDATE 와 같게 되도록
                    binds.append(bindparam(f"p{j}_{n}", type_=table.c[c].type))
                    cells.append(f"CAST(:p{j}_{n} AS {types[c]})")
                values.append(f"({', '.join(cells)})")
            stmt = text(
                f"UPDATE {name} AS t SET {set_sql} "
                f"FROM (VALUES {', '.join(values)}) AS v({', '.join(cols)}) WHERE {where_sql}"
            ).bindparams(*binds)
            conn.execute(stmt, params)

    def _source(self, conn: Any, name: str, *, kind: str = "QUANT") -> str:
        """출처 이름을 data_sources 이름으로 맞추고, 없으면 추가한다."""
        key = source_key(name)
        if key in self._known_sources:
            return key
        ds = T.data_sources
        if conn.execute(select(ds.c.source_name).where(ds.c.source_name == key)).first() is None:
            conn.execute(insert(ds).values(source_name=key, type=kind, description="자동 등록"))
        self._known_sources.add(key)
        return key

    def _asset_ids(self, conn: Any, symbols: Iterable[str]) -> dict[str, str]:
        """yfinance 표기 → asset_id (없는 종목은 빈칸)."""
        wanted = sorted({normalize_ticker(s) for s in symbols})
        a = T.assets
        out: dict[str, str] = {}
        for part in _chunks(wanted):
            q = select(a.c.yfinance_symbol, a.c.asset_id).where(a.c.yfinance_symbol.in_(part))
            out.update({r.yfinance_symbol: r.asset_id for r in conn.execute(q)})
        return out

    def _ensure_assets(
        self, conn: Any, symbols: Iterable[str], names: dict[str, str] | None = None
    ) -> dict[str, str]:
        """종목 마스터에 없는 종목을 기본 행으로 만들고 yfinance 표기 → asset_id 를 돌려준다."""
        syms = sorted({normalize_ticker(s) for s in symbols})
        known = self._asset_ids(conn, syms)
        missing = [s for s in syms if s not in known]
        if missing and conn.dialect.name == "postgresql":
            # 출처 줄(스레드)·백필이 같은 새 종목을 동시에 넣지 않게: 잠근 뒤 다시 확인
            _lock(conn, "assets")
            known = self._asset_ids(conn, syms)
            missing = [s for s in syms if s not in known]
        if missing:
            now = self._clock()
            rows = []
            for s in missing:
                info = default_asset(s, (names or {}).get(s))
                rows.append({**info.model_dump(), "created_at": now, "updated_at": now})
                known[s] = info.asset_id
            self._insert_many(conn, T.assets, rows)
        return known

    # ------------------------------------------------------------------ 종목 마스터
    def upsert_assets(self, assets: list[AssetInfo]) -> int:
        """종목 마스터 저장 (asset_id 기준, 값이 다를 때만 갱신). 반영 행 수."""
        now = self._clock()
        rows = [{**a.model_dump(), "created_at": now, "updated_at": now} for a in assets]

        def run(conn: Any) -> int:
            _lock(conn, "assets")
            existing = {
                r.asset_id: r.created_at
                for r in conn.execute(select(T.assets.c.asset_id, T.assets.c.created_at))
            }
            for r in rows:  # 갱신할 때 처음 만든 시각은 그대로 둔다
                r["created_at"] = existing.get(r["asset_id"], now)
            return self._upsert(conn, T.assets, ("asset_id",), _ASSET_VALUE_COLS, rows)

        return self._write("종목 마스터", run)

    def get_assets(self, symbols: list[str] | None = None) -> list[AssetInfo]:
        """종목 마스터 (asset_id 순). symbols(yfinance 표기)를 주면 그 종목만."""
        a = T.assets
        q = select(*(a.c[c] for c in ("asset_id", *_ASSET_VALUE_COLS))).order_by(a.c.asset_id)
        if symbols is not None:
            q = q.where(a.c.yfinance_symbol.in_(sorted({normalize_ticker(s) for s in symbols})))
        return self._read("종목 마스터", lambda c: [AssetInfo(**r._asdict()) for r in c.execute(q)])

    def asset_key_map(self, column: str) -> dict[str, str]:
        """출처 코드 → asset_id. column 은 dart_corp_code·sec_cik·kis_ticker 등."""
        a = T.assets
        if column not in _ASSET_VALUE_COLS:
            raise RepositoryError(f"assets 에 없는 칸: {column}", code="REPO_READ_FAILED")
        q = select(a.c[column], a.c.asset_id).where(a.c[column].is_not(None))
        return self._read("종목 마스터", lambda c: {r[0]: r[1] for r in c.execute(q)})

    # ------------------------------------------------------------------ 가격
    def upsert_prices(self, bars: list[PriceBar]) -> int:
        """가격 저장. 자연키(티커, 날짜, 출처)가 같고 값도 같으면 건너뜀. 반영 행 수.

        원본은 price_daily_source 에 넣고, 같은 트랜잭션에서 바뀐 (종목, 날짜) 만 계약
        price_daily 에 다시 싣는다 (_publish_prices).
        """

        def run(conn: Any) -> int:
            ids = self._ensure_assets(conn, [b.ticker for b in bars])
            rows = [
                {
                    "ticker": normalize_ticker(b.ticker),
                    "date": b.date,
                    "adj_close": float(b.adj_close),
                    "volume": b.volume,
                    "currency": b.currency,
                    "source": self._source(conn, b.source),
                    "fetched_at": b.fetched_at,
                    "asset_id": ids[normalize_ticker(b.ticker)],
                    "open": b.open,
                    "high": b.high,
                    "low": b.low,
                    "close": b.close,
                    # 새 행·값이 바뀐 행은 교차검증을 다시 받도록 비움
                    **_UNVERIFIED,
                }
                for b in bars
            ]
            changed: list[tuple[Any, ...]] = []
            for src in sorted({r["source"] for r in rows}):
                _lock(conn, f"price_daily_source:{src}")
            n = self._upsert(
                conn,
                T.price_daily_source,
                ("ticker", "date", "source"),
                _PRICE_SOURCE_VALUE_COLS,
                rows,
                changed_keys=changed,
            )
            self._publish_prices(conn, [(t, d) for t, d, _ in changed])
            return n

        n = self._write("가격", run)
        logger.info("price_daily_source: %d/%d행 반영", n, len(bars))
        return n

    def _pick_price(self, rows: Sequence[Any], *, adj: bool = False) -> Any | None:
        """한 (종목, 날짜) 의 출처별 행 중 계약 price_daily 에 실을 행 (CONSENSUS 제외).

        통화별 출처 우선순위(종가·OHLCV 는 close_priority, adj=True 면 price_priority) → 수집 시각이
        가장 늦은 행 → 출처 이름 오름차순.
        """
        raw = [r for r in rows if r.source != CONSENSUS]
        if not raw:
            return None
        prio = self.price_priority if adj else self.close_priority
        order = {s: i for i, s in enumerate(prio.get(raw[0].currency, ()))}
        return min(
            raw,
            key=lambda r: (order.get(r.source, len(order)), -r.fetched_at.timestamp(), r.source),
        )

    def _publish_prices(self, conn: Any, keys: Iterable[tuple[str, date]]) -> int:
        """(티커, 날짜) 들의 계약 price_daily 행을 원본에서 다시 골라 저장. 반영 행 수.

        실을 행 = 종가·OHLCV 는 close_priority 가 가장 앞선 출처의 원본 행, adj_close 는 price_priority 가
        가장 앞선 출처의 원본 값 (값 가공 없음, 출처는 source·adj_close_source 칸).
        verify_status = 그 키의 CONSENSUS 행 상태, 없으면 고른 행의 상태.
        _upsert 로 써서 고른 값이 그대로면 다시 쓰지 않는다 (updated_at 도 그대로).
        """
        wanted = set(keys)
        if not wanted:
            return 0
        _lock_publish(conn, "price_daily")
        p = T.price_daily_source
        by_ticker: dict[str, list[date]] = defaultdict(list)
        for t, d in wanted:
            by_ticker[t].append(d)
        now = self._clock()
        out: list[dict[str, Any]] = []
        for part in _chunks(sorted(by_ticker)):
            lo = min(min(by_ticker[t]) for t in part)
            hi = max(max(by_ticker[t]) for t in part)
            q = select(
                p.c.ticker,
                p.c.date,
                p.c.source,
                p.c.asset_id,
                p.c.open,
                p.c.high,
                p.c.low,
                p.c.close,
                p.c.adj_close,
                p.c.volume,
                p.c.currency,
                p.c.verify_status,
                p.c.fetched_at,
            ).where(p.c.ticker.in_(part), p.c.date >= lo, p.c.date <= hi)
            groups: dict[tuple[str, date], list[Any]] = defaultdict(list)
            for r in conn.execute(q):
                if (r.ticker, r.date) in wanted:
                    groups[(r.ticker, r.date)].append(r)
            for rows in groups.values():
                chosen = self._pick_price(rows)
                if chosen is None:
                    continue
                adj = self._pick_price(rows, adj=True) or chosen
                cons = next((r for r in rows if r.source == CONSENSUS), None)
                out.append(
                    {
                        "asset_id": chosen.asset_id,
                        "date": chosen.date,
                        "ticker": chosen.ticker,
                        "open": chosen.open,
                        "high": chosen.high,
                        "low": chosen.low,
                        "close": chosen.close,
                        "adj_close": adj.adj_close,
                        "adj_close_source": adj.source,
                        "volume": chosen.volume,
                        "currency": chosen.currency,
                        "source": chosen.source,
                        "verify_status": (cons or chosen).verify_status,
                        "fetched_at": chosen.fetched_at,
                        "updated_at": now,
                    }
                )
        return self._upsert(
            conn, T.price_daily, ("asset_id", "date"), _PRICE_PUBLISH_VALUE_COLS, out
        )

    def publish_all(
        self, conn: Any, *, chunk: int = 20, log: Callable[[str], None] | None = None
    ) -> dict[str, int]:
        """원본 테이블 전체로 계약 price_daily·financials 를 채움 (migrate_v2 백필용).

        conn 의 트랜잭션 안에서 종목 chunk 개씩 처리한다. 반영 행 수 {"price_daily", "financials"}.
        """
        p, f = T.price_daily_source, T.financials_source
        out = {"price_daily": 0, "financials": 0}
        tickers = sorted(conn.execute(select(p.c.ticker).distinct()).scalars())
        for i, part in enumerate(_chunks(tickers, chunk)):
            keys = conn.execute(
                select(p.c.ticker, p.c.date)
                .where(p.c.ticker.in_(part), p.c.source != CONSENSUS)
                .distinct()
            ).all()
            out["price_daily"] += self._publish_prices(conn, [tuple(k) for k in keys])
            if log:
                log(f"  price_daily {min((i + 1) * chunk, len(tickers))}/{len(tickers)}종목")
        assets = sorted(conn.execute(select(f.c.asset_id).distinct()).scalars())
        for part in _chunks(assets, chunk):
            out["financials"] += self._publish_financials(conn, part)
        if log:
            log(f"  financials {len(assets)}종목")
        return out

    def get_prices(
        self, tickers: list[str], start: date, end: date
    ) -> tuple[pd.DataFrame, PriceMeta]:
        """[start, end] 수정종가를 PriceFrame 계약(0-4) 모양으로 (계약 price_daily 를 읽음).

        열 = 요청 티커 전부(오름차순, 저장된 값이 없으면 전부 NaN). 행 = 저장된 날짜의 합집합.
        값은 (종목, 날짜) 마다 출처 우선순위로 고른 원본 행 (_publish_prices).
        통화가 다른 종목을 섞어 요청하면 RepositoryError.
        저장된 값이 하나도 없으면 행이 0개인 표와 source="none" 메타.
        """
        wanted = sorted({normalize_ticker(t) for t in tickers})
        currencies = sorted({currency_of_symbol(t) for t in wanted})
        if len(currencies) > 1:
            raise RepositoryError(
                f"통화가 다른 종목을 한 PriceFrame 으로 요청함: {currencies} (시장별로 나눠 요청)",
                code="REPO_READ_FAILED",
                details={"tickers": wanted},
            )
        p = T.price_daily

        def run(conn: Any) -> list[Any]:
            out: list[Any] = []
            for part in _chunks(wanted):
                q = select(p.c.ticker, p.c.date, p.c.adj_close, p.c.source, p.c.fetched_at).where(
                    p.c.ticker.in_(part), p.c.date >= start, p.c.date <= end
                )
                out.extend(conn.execute(q).all())
            return out

        chosen = self._read("가격", run)
        if chosen:
            long = pd.DataFrame(
                {
                    "date": pd.to_datetime([r.date for r in chosen]),
                    "ticker": [r.ticker for r in chosen],
                    "adj_close": [float(r.adj_close) for r in chosen],
                }
            )
            frame = long.pivot(index="date", columns="ticker", values="adj_close")
        else:
            frame = pd.DataFrame(index=pd.DatetimeIndex([], name="date"))
        frame = frame.reindex(columns=wanted).astype("float64").sort_index()
        frame.index.name = "date"
        frame.columns.name = None
        meta = PriceMeta(
            source="+".join(sorted({r.source for r in chosen})) or "none",
            as_of=max(r.date for r in chosen) if chosen else end,
            fetched_at=min(r.fetched_at for r in chosen) if chosen else EPOCH,
            tickers=wanted,
            currency=currencies[0] if currencies else "USD",  # type: ignore[arg-type]
        )
        return frame, meta

    def covered_range(self, ticker: str) -> tuple[date, date] | None:
        """원본(price_daily_source)에 저장된 첫 날짜·마지막 날짜 (출처 무관). 없으면 None."""
        p = T.price_daily_source
        q = select(func.min(p.c.date), func.max(p.c.date)).where(
            p.c.ticker == normalize_ticker(ticker)
        )
        row = self._read("저장 범위", lambda c: c.execute(q).one())
        if row[0] is None:
            return None
        return row[0], row[1]

    def needs_fetch(
        self, ticker: str, start: date, end: date, *, today: date | None = None
    ) -> bool:
        """캐시 판단. 저장 범위가 요청 범위를 덮고 마지막 저장일 ≥ 직전 거래일이면 False.

        직전 거래일 = today 기준 cache_max_age_days 번째 이전 평일. end 가 그보다 이르면 end 까지만
        있으면 된다. 시작 쪽은 START_GRACE_DAYS 만큼 여유를 둔다 (시작일이 휴장일인 경우).
        """
        covered = self.covered_range(ticker)
        if covered is None:
            return True
        lo, hi = covered
        today = today or datetime.now(UTC).date()
        need_until = min(end, previous_weekday(today, self.cache_max_age_days))
        start_ok = lo <= start + timedelta(days=START_GRACE_DAYS)
        return not (start_ok and hi >= need_until)

    def covered_ranges(
        self, tickers: Sequence[str], *, source: str | None = None
    ) -> dict[str, tuple[date, date]]:
        """여러 티커의 원본 저장 범위를 한 번에. source 를 주면 그 출처 행만, 없으면 출처 무관.

        저장된 게 없는 티커는 빠짐.
        """
        p = T.price_daily_source
        wanted = sorted({normalize_ticker(t) for t in tickers})
        out: dict[str, tuple[date, date]] = {}
        for i in range(0, len(wanted), _CHUNK):
            part = wanted[i : i + _CHUNK]
            q = (
                select(p.c.ticker, func.min(p.c.date), func.max(p.c.date))
                .where(p.c.ticker.in_(part))
                .group_by(p.c.ticker)
            )
            if source is not None:
                q = q.where(p.c.source == source_key(source))
            for t, lo, hi in self._read("저장 범위", lambda c, q=q: c.execute(q).all()):
                out[t] = (lo, hi)
        return out

    def tickers_needing_fetch(
        self, tickers: Sequence[str], start: date, end: date, *, today: date | None = None
    ) -> list[str]:
        """needs_fetch 가 참인 티커들 (입력 순서 유지, 쿼리 한 번). 수집 작업용."""
        today = today or datetime.now(UTC).date()
        need_until = min(end, previous_weekday(today, self.cache_max_age_days))
        ranges = self.covered_ranges(tickers)
        out: list[str] = []
        for t in dict.fromkeys(normalize_ticker(x) for x in tickers):
            r = ranges.get(t)
            if r is None or not (
                r[0] <= start + timedelta(days=START_GRACE_DAYS) and r[1] >= need_until
            ):
                out.append(t)
        return out

    # ------------------------------------------------------------------ 교차검증 (확장)
    def pending_verification(self, *, limit: int = 2000) -> list[tuple[str, date]]:
        """교차검증을 아직 안 받은 (티커, 날짜). 출처별 행 중 verify_status 가 빈 것 기준."""
        p = T.price_daily_source
        q = (
            select(p.c.ticker, p.c.date)
            .where(p.c.source != CONSENSUS, p.c.verify_status.is_(None))
            .group_by(p.c.ticker, p.c.date)
            .order_by(p.c.ticker, p.c.date)
            .limit(limit)
        )
        return [(r[0], r[1]) for r in self._read("검증 대상", lambda c: c.execute(q).all())]

    def price_rows(self, keys: Sequence[tuple[str, date]]) -> list[dict[str, Any]]:
        """(티커, 날짜) 들의 출처별 행 (CONSENSUS 제외). 교차검증 입력."""
        p = T.price_daily_source
        cols = (
            p.c.ticker,
            p.c.date,
            p.c.source,
            p.c.adj_close,
            p.c.close,
            p.c.volume,
            p.c.currency,
            p.c.asset_id,
            p.c.fetched_at,
        )
        wanted = set(keys)
        by_ticker: dict[str, list[date]] = {}
        for t, d in wanted:
            by_ticker.setdefault(t, []).append(d)
        out: list[dict[str, Any]] = []
        for part in _chunks(sorted(by_ticker)):
            lo = min(min(by_ticker[t]) for t in part)
            hi = max(max(by_ticker[t]) for t in part)
            q = select(*cols).where(
                p.c.ticker.in_(part), p.c.date >= lo, p.c.date <= hi, p.c.source != CONSENSUS
            )
            rows = self._read("출처별 가격", lambda c, q=q: c.execute(q).all())
            out.extend(r._asdict() for r in rows if (r.ticker, r.date) in wanted)
        return out

    def previous_prices(
        self, keys: Sequence[tuple[str, date]], lookback_days: int = 14
    ) -> dict[tuple[str, str, date], tuple[float | None, float]]:
        """(티커, 출처, 날짜) → 그 출처의 바로 전 거래일 (종가, 수정종가). 교차검증의 수익률 비교용.

        keys 날짜보다 lookback_days 앞까지만 찾는다 (그 안에 전 거래일이 없으면 빠짐)."""
        p = T.price_daily_source
        by_ticker: dict[str, list[date]] = {}
        for t, d in set(keys):
            by_ticker.setdefault(t, []).append(d)
        out: dict[tuple[str, str, date], tuple[float | None, float]] = {}
        for part in _chunks(sorted(by_ticker)):
            lo = min(min(by_ticker[t]) for t in part) - timedelta(days=lookback_days)
            hi = max(max(by_ticker[t]) for t in part)
            q = (
                select(p.c.ticker, p.c.source, p.c.date, p.c.close, p.c.adj_close)
                .where(p.c.ticker.in_(part), p.c.date >= lo, p.c.date <= hi,
                       p.c.source != CONSENSUS)
                .order_by(p.c.ticker, p.c.source, p.c.date)
            )  # fmt: skip
            rows = self._read("출처별 가격", lambda c, q=q: c.execute(q).all())
            prev: dict[tuple[str, str], tuple[date, float | None, float]] = {}
            for r in rows:
                k = (r.ticker, r.source)
                if k in prev and (r.date - prev[k][0]).days <= lookback_days:
                    out[(r.ticker, r.source, r.date)] = (prev[k][1], prev[k][2])
                prev[k] = (r.date, r.close, r.adj_close)
        return out

    def save_verification(
        self,
        consensus: list[dict[str, Any]],
        marks: list[dict[str, Any]],
        *,
        drop_consensus: Sequence[tuple[str, date]] = (),
    ) -> int:
        """교차검증 결과 저장 (한 트랜잭션).

        consensus: CONSENSUS 행 (price_daily_source 칸 이름 그대로). 같은 키면 값이 다를 때만 갱신.
        marks: 출처별 행에 적을 ticker·date·source·dev_pct·adj_dev_pct·verify_status.
        drop_consensus: 출처가 하나만 남아 지울 CONSENSUS 행.
        끝에 해당 키의 계약 price_daily.verify_status 를 다시 맞춘다 (값은 그대로).
        반영한 CONSENSUS 행 수.
        """
        p = T.price_daily_source

        def run(conn: Any) -> int:
            for part in _chunks(list(drop_consensus)):
                conn.execute(
                    delete(p).where(tuple_(p.c.ticker, p.c.date).in_(part), p.c.source == CONSENSUS)
                )
            self._bulk_update(
                conn,
                p,
                ("ticker", "date", "source"),
                ("dev_pct", "adj_dev_pct", "verify_status"),
                list(marks),
            )
            n = 0
            if consensus:
                self._source(conn, CONSENSUS)
                n = self._upsert(
                    conn,
                    p,
                    ("ticker", "date", "source"),
                    _CONSENSUS_VALUE_COLS,
                    [{**r, "source": CONSENSUS} for r in consensus],
                )
            keys = {(r["ticker"], r["date"]) for r in (*consensus, *marks)}
            self._publish_prices(conn, keys | set(drop_consensus))
            return n

        return self._write("교차검증", run)

    def mismatch_days(self, tickers: Sequence[str], start: date, end: date) -> dict[str, int]:
        """[start, end] 에 CONSENSUS 가 MISMATCH 인 거래일 수 (품질 경고용). 0 인 티커는 빠짐."""
        p = T.price_daily_source
        wanted = sorted({normalize_ticker(t) for t in tickers})
        out: dict[str, int] = {}
        for part in _chunks(wanted):
            q = (
                select(p.c.ticker, func.count())
                .where(
                    p.c.ticker.in_(part),
                    p.c.date >= start,
                    p.c.date <= end,
                    p.c.source == CONSENSUS,
                    p.c.verify_status == "MISMATCH",
                )
                .group_by(p.c.ticker)
            )
            out.update(dict(self._read("검증 결과", lambda c, q=q: c.execute(q).all())))
        return out

    def reset_verification(
        self, start: date, end: date, *, tickers: Sequence[str] | None = None
    ) -> int:
        """[start, end] 출처별 행의 검증 표시를 지워 다시 계산하게 함. 지운 행 수.

        CONSENSUS 행은 남으므로 계약 price_daily.verify_status 는 다시 검증할 때까지 그대로다
        (CONSENSUS 가 없는 키만 비워짐, 같은 트랜잭션에서 맞춤).
        """
        p = T.price_daily_source
        cond = [p.c.source != CONSENSUS, p.c.date >= start, p.c.date <= end]
        parts: list[Any] = [None]
        if tickers is not None:
            parts = list(_chunks(sorted({normalize_ticker(t) for t in tickers})))

        def run(conn: Any) -> int:
            n = 0
            for part in parts:
                where = [*cond] if part is None else [*cond, p.c.ticker.in_(part)]
                keys = conn.execute(select(p.c.ticker, p.c.date).where(*where).distinct()).all()
                n += conn.execute(update(p).where(*where).values(**_UNVERIFIED)).rowcount
                self._publish_prices(conn, [tuple(k) for k in keys])
            return n

        return self._write("검증 초기화", run)

    # ------------------------------------------------------------------ 환율
    def upsert_fx(self, rates: list[FxRate]) -> int:
        """환율 저장: 출처별 원본(fx_daily_source)에 넣고, 바뀐 날짜만 계약 fx_daily 에 다시 싣는다.

        fx_daily 는 (통화쌍, 날짜)마다 한 행: FX_PRIORITY 순(YFINANCE → FRED → 그 밖)으로 그날 값이
        있는 출처 하나. 반영 행 수 = 원본에서 새로 넣거나 바뀐 행 수.
        """

        def run(conn: Any) -> int:
            rows = [
                {
                    "pair": r.pair,
                    "date": r.date,
                    "rate": float(r.rate),
                    "source": self._source(conn, r.source),
                    "fetched_at": r.fetched_at,
                }
                for r in rates
            ]
            changed: list[tuple[Any, ...]] = []
            n = self._upsert(
                conn,
                T.fx_daily_source,
                ("pair", "date", "source"),
                ("rate",),
                rows,
                changed_keys=changed,
            )
            if changed:
                _publish_fx(conn, sorted({(k[0], k[1]) for k in changed}))
            return n

        return self._write("환율", run)

    def get_fx_on_or_before(self, d: date) -> FxRate | None:
        """d 이전(포함) 가장 최근 USD/KRW (1 USD 당 KRW)."""
        f = T.fx_daily
        q = (
            select(f.c.pair, f.c.date, f.c.rate, f.c.source, f.c.fetched_at)
            .where(f.c.pair == "USDKRW", f.c.date <= d)
            .order_by(f.c.date.desc())
            .limit(1)
        )

        def run(conn: Any) -> FxRate | None:
            row = conn.execute(q).first()
            return FxRate(**row._asdict()) if row else None

        return self._read("환율", run)

    # ------------------------------------------------------------------ 구성종목
    def save_constituents(self, rows: list[IndexConstituent]) -> None:
        """구성종목 저장. 같은 (지수, 스냅샷 날짜) 는 지우고 새로 넣는다.

        rows 의 티커는 yfinance 표기. DB 에는 계약 표기로 저장한다: 미국은 yfinance 표기(BRK-B),
        한국은 6자리 종목코드(005930, = assets.ticker). asset_id 로 종목 마스터와 잇는다.
        """
        if not rows:
            return
        ic = T.index_constituent

        def run(conn: Any) -> None:
            names = {normalize_ticker(r.ticker): r.name for r in rows}
            ids = self._ensure_assets(conn, names, names)
            groups: dict[tuple[str, date], list[dict[str, Any]]] = {}
            for r in rows:
                code = IndexCode(r.index_code).value
                sym = normalize_ticker(r.ticker)
                groups.setdefault((code, r.snapshot_date), []).append(
                    {
                        "index_code": code,
                        "snapshot_date": r.snapshot_date,
                        "ticker": constituent_ticker(sym),
                        "name": r.name,
                        "sector": r.sector,
                        "industry": r.industry,
                        "source": r.source,
                        "fetched_at": r.fetched_at,
                        "asset_id": ids[sym],
                        "gics_sub_industry_code": r.gics_sub_industry_code,
                    }
                )
            for (code, snap), items in groups.items():
                conn.execute(delete(ic).where(ic.c.index_code == code, ic.c.snapshot_date == snap))
                self._insert_many(conn, ic, items)

        self._write("구성종목", run)

    def latest_constituents(self, index: IndexCode) -> list[IndexConstituent]:
        """가장 최근 스냅샷 (티커 오름차순). 없으면 빈 목록.

        돌려주는 티커는 yfinance 표기 (assets.yfinance_symbol, 005930.KS): 수집 작업이 그대로 쓴다.
        """
        code = IndexCode(index).value
        ic, a = T.index_constituent, T.assets

        def run(conn: Any) -> list[IndexConstituent]:
            snap = conn.execute(
                select(func.max(ic.c.snapshot_date)).where(ic.c.index_code == code)
            ).scalar()
            if snap is None:
                return []
            q = (
                select(
                    ic.c.index_code,
                    func.coalesce(a.c.yfinance_symbol, ic.c.ticker).label("ticker"),
                    ic.c.name,
                    ic.c.sector,
                    ic.c.industry,
                    ic.c.snapshot_date,
                    ic.c.source,
                    ic.c.fetched_at,
                    ic.c.gics_sub_industry_code,
                )
                .select_from(ic.outerjoin(a, a.c.asset_id == ic.c.asset_id))
                .where(ic.c.index_code == code, ic.c.snapshot_date == snap)
            )
            out = [IndexConstituent(**r._asdict()) for r in conn.execute(q)]
            return sorted(out, key=lambda r: r.ticker)

        return self._read("구성종목", run)

    def constituent_snapshots(self, index: IndexCode | str) -> list[date]:
        """그 지수의 스냅샷 날짜들 (오래된 순)."""
        ic = T.index_constituent
        q = (
            select(ic.c.snapshot_date)
            .where(ic.c.index_code == IndexCode(index).value)
            .distinct()
            .order_by(ic.c.snapshot_date)
        )
        return self._read("구성종목", lambda c: list(c.execute(q).scalars()))

    # ------------------------------------------------------------------ GICS (v4, Module2 §5)
    def sync_gics_taxonomy(self, rows: list[dict[str, Any]]) -> int:
        """gics_taxonomy 를 rows(GicsTaxonomy.rows())와 같게 (값이 다른 행만 갱신). 반영 행 수.

        분류표에서 빠진 코드는 지우지 않는다 (예전 스냅샷이 참조할 수 있음).
        """
        now = self._clock()
        data = [{**r, "updated_at": now} for r in rows]

        def run(conn: Any) -> int:
            _lock(conn, "gics_taxonomy")
            return self._upsert(conn, T.gics_taxonomy, ("code",), _GICS_TAXONOMY_COLS, data)

        return self._write("GICS 분류표", run)

    def gics_taxonomy_rows(self) -> list[dict[str, Any]]:
        """gics_taxonomy 전체 (코드 순)."""
        g = T.gics_taxonomy
        q = select(g.c.code, g.c.level, g.c.name_en, g.c.name_ko, g.c.parent_code).order_by(
            g.c.code
        )
        return self._read("GICS 분류표", lambda c: [dict(r._mapping) for r in c.execute(q)])

    def asset_profiles(self, symbols: Sequence[str] | None = None) -> list[dict[str, Any]]:
        """종목 마스터 + GICS·KSIC·사업 설명 칸 (asset_id 순). symbols = yfinance 표기."""
        a = T.assets
        cols = (
            "asset_id",
            "ticker",
            "name",
            "market",
            "asset_type",
            "currency",
            "yfinance_symbol",
            "dart_corp_code",
            *PROFILE_COLS,
            "gics_updated_at",
        )
        q = select(*(a.c[c] for c in cols)).order_by(a.c.asset_id)

        def run(conn: Any) -> list[dict[str, Any]]:
            if symbols is None:
                return [dict(r._mapping) for r in conn.execute(q)]
            out: list[dict[str, Any]] = []
            wanted = sorted({normalize_ticker(s) for s in symbols})
            for part in _chunks(wanted):
                out += [
                    dict(r._mapping) for r in conn.execute(q.where(a.c.yfinance_symbol.in_(part)))
                ]
            return sorted(out, key=lambda r: r["asset_id"])

        return self._read("종목 마스터", run)

    def update_asset_profiles(self, rows: list[dict[str, Any]]) -> int:
        """assets 의 GICS·KSIC·사업 설명 칸만 바꿈 (값이 다를 때만). 바뀐 행 수.

        rows: {"asset_id": ..., 칸: 값} (PROFILE_COLS 중 일부). 준 칸만 바꾸고, GICS 칸이 하나라도
        바뀐 행은 gics_updated_at 을 지금으로. 없는 asset_id 는 RepositoryError.
        """
        if not rows:
            return 0
        bad = sorted({k for r in rows for k in r if k != "asset_id" and k not in PROFILE_COLS})
        if bad:
            raise RepositoryError(f"바꿀 수 없는 assets 칸: {bad}", code="REPO_WRITE_FAILED")
        now = self._clock()
        a = T.assets

        def run(conn: Any) -> int:
            _lock(conn, "assets")
            ids = sorted({r["asset_id"] for r in rows})
            cols = [a.c.asset_id, *(a.c[c] for c in PROFILE_COLS), a.c.gics_updated_at]
            existing: dict[str, dict[str, Any]] = {}
            for part in _chunks(ids):
                for r in conn.execute(select(*cols).where(a.c.asset_id.in_(part))):
                    existing[r.asset_id] = dict(r._mapping)
            missing = [i for i in ids if i not in existing]
            if missing:
                raise RepositoryError(
                    f"assets 에 없는 종목: {missing[:10]}", code="REPO_WRITE_FAILED"
                )
            n = 0
            for r in rows:
                old = existing[r["asset_id"]]
                diff = {k: v for k, v in r.items() if k != "asset_id" and not _same(old[k], v)}
                if not diff:
                    continue
                if any(k in GICS_COLS for k in diff):
                    diff["gics_updated_at"] = now
                conn.execute(update(a).where(a.c.asset_id == r["asset_id"]).values(**diff))
                old.update(diff)
                n += 1
            return n

        return self._write("종목 GICS·사업 설명", run)

    def constituent_gics_gaps(self) -> list[dict[str, Any]]:
        """GICS 세부산업 코드가 비어 있는 구성종목 행 (예전 스냅샷, 못 찾은 이름)."""
        ic = T.index_constituent
        q = (
            select(
                ic.c.index_code,
                ic.c.snapshot_date,
                ic.c.ticker,
                ic.c.asset_id,
                ic.c.name,
                ic.c.sector,
                ic.c.industry,
            )
            .where(ic.c.gics_sub_industry_code.is_(None))
            .order_by(ic.c.index_code, ic.c.snapshot_date, ic.c.ticker)
        )
        return self._read("구성종목", lambda c: [dict(r._mapping) for r in c.execute(q)])

    def update_constituent_gics(self, rows: list[dict[str, Any]]) -> int:
        """구성종목 행의 gics_sub_industry_code (와 sector·industry 이름) 를 채움. 바뀐 행 수.

        rows: {index_code, snapshot_date, ticker, gics_sub_industry_code[, sector, industry]}.
        """
        if not rows:
            return 0
        ic = T.index_constituent
        allowed = {"gics_sub_industry_code", "sector", "industry"}

        def run(conn: Any) -> int:
            n = 0
            for r in rows:
                values = {k: v for k, v in r.items() if k in allowed}
                n += conn.execute(
                    update(ic)
                    .where(
                        ic.c.index_code == r["index_code"],
                        ic.c.snapshot_date == r["snapshot_date"],
                        ic.c.ticker == r["ticker"],
                    )
                    .values(**values)
                ).rowcount
            return n

        return self._write("구성종목 GICS", run)

    # ------------------------------------------------------------------ 수집 이력
    def log_fetch(
        self,
        source: str,
        target: str,
        start: date | None,
        end: date | None,
        status: str,
        fetched_at: datetime,
        error: str | None,
        *,
        fetched_count: int | None = None,
        inserted_count: int | None = None,
    ) -> None:
        """수집 이력 한 줄 추가 (누적). data_sources 의 최근 성공·실패 시각도 갱신."""
        self.log_fetches(
            source,
            [
                {
                    "target": target,
                    "start_date": start,
                    "end_date": end,
                    "status": status,
                    "fetched_at": fetched_at,
                    "error": error,
                    "fetched_count": fetched_count,
                    "inserted_count": inserted_count,
                }
            ],
        )

    def log_fetches(self, source: str, rows: Sequence[dict[str, Any]]) -> None:
        """한 출처의 수집 이력 여러 줄을 한 트랜잭션으로 추가 (원격 DB 왕복을 줄임).

        rows: target·start_date·end_date·status·fetched_at·error (+ fetched_count 등 선택).
        """
        if not rows:
            return

        def run(conn: Any) -> None:
            key = self._source(conn, source)
            self._insert_many(
                conn,
                T.fetch_log,
                [
                    {
                        "fetched_count": None,
                        "inserted_count": None,
                        **r,
                        "source": key,
                    }
                    for r in rows
                ],
            )
            ds = T.data_sources
            for status, col in (("SUCCESS", "last_success_at"), (None, "last_failure_at")):
                times = [
                    r["fetched_at"]
                    for r in rows
                    if (r["status"] == "SUCCESS") == (status == "SUCCESS")
                ]
                if times:
                    conn.execute(
                        update(ds).where(ds.c.source_name == key).values({col: max(times)})
                    )

        self._write("수집 이력", run)

    def fetch_history(self, target: str | None = None) -> list[dict[str, Any]]:
        """수집 이력 (오래된 순). 디버그용."""
        r = T.fetch_log
        q = select(r).order_by(r.c.id)
        if target is not None:
            q = q.where(r.c.target == target)
        return self._read("수집 이력", lambda c: [x._asdict() for x in c.execute(q)])

    def fetch_attempts(
        self,
        source: str,
        targets: Sequence[str],
        *,
        start_on_or_before: date | None = None,
        end_on_or_after: date | None = None,
    ) -> dict[str, dict[str, Any]]:
        """출처·대상별 수집 시도 요약: 최근 성공 시각, 실패 횟수 (수집 작업이 다음 대상을 고를 때).

        start_on_or_before 를 주면 시작일이 그 날 이전인 시도만 센다 (백필 범위를 덮은 시도).
        end_on_or_after 를 주면 종료일이 그 날 이후인 시도만 센다 (그 날까지 요청한 시도).
        """
        r = T.fetch_log
        key = source_key(source)
        out: dict[str, dict[str, Any]] = {}
        uniq = sorted(set(targets))
        for i in range(0, len(uniq), _CHUNK):
            part = uniq[i : i + _CHUNK]
            q = (
                select(r.c.target, r.c.status, func.count(), func.max(r.c.fetched_at))
                .where(r.c.source == key, r.c.target.in_(part))
                .group_by(r.c.target, r.c.status)
            )
            if start_on_or_before is not None:
                q = q.where(r.c.start_date <= start_on_or_before)
            if end_on_or_after is not None:
                q = q.where(r.c.end_date >= end_on_or_after)
            for target, status, n, last in self._read(
                "수집 이력", lambda c, q=q: c.execute(q).all()
            ):
                d = out.setdefault(target, {"last_success_at": None, "failures": 0})
                if status == "SUCCESS":
                    d["last_success_at"] = last
                else:
                    d["failures"] += n
        return out

    def fetch_targets_done(self, source: str, prefix: str) -> set[str]:
        """target 이 prefix 로 시작하고 성공(SUCCESS)한 적이 있는 대상들 (백필 이어 받기용)."""
        r = T.fetch_log
        q = (
            select(r.c.target)
            .where(
                r.c.source == source_key(source),
                r.c.status == "SUCCESS",
                r.c.target.like(prefix.replace("%", "").replace("_", "\\_") + "%", escape="\\"),
            )
            .distinct()
        )
        return self._read("수집 이력", lambda c: set(c.execute(q).scalars()))

    def news_monthly_average(
        self, source: str, asset_ids: Iterable[str], start: date, end: date
    ) -> dict[str, float]:
        """[start, end) 동안 출처의 종목별 월평균 기사 수 (기사가 없는 종목은 빠짐)."""
        n = T.news
        months = max(1, (end.year - start.year) * 12 + end.month - start.month)
        lo = datetime(start.year, start.month, start.day, tzinfo=UTC)
        hi = datetime(end.year, end.month, end.day, tzinfo=UTC)

        def run(conn: Any) -> dict[str, float]:
            out: dict[str, float] = {}
            for part in _chunks(sorted(set(asset_ids))):
                q = (
                    select(n.c.asset_id, func.count())
                    .where(
                        n.c.source == source_key(source),
                        n.c.asset_id.in_(part),
                        n.c.published_at >= lo,
                        n.c.published_at < hi,
                    )  # fmt: skip
                    .group_by(n.c.asset_id)
                )
                out.update({aid: cnt / months for aid, cnt in conn.execute(q)})
            return out

        return self._read("뉴스 월평균", run)

    def count_fetches(self, source: str, since: datetime) -> int:
        """since 뒤의 수집 시도 수 (출처의 하루 요청 한도를 나눠 쓰기 위함)."""
        r = T.fetch_log
        q = select(func.count()).where(r.c.source == source_key(source), r.c.fetched_at >= since)
        return int(self._read("수집 이력", lambda c: c.execute(q).scalar_one()))

    @contextmanager
    def job_lock(self, name: str) -> Iterator[bool]:
        """같은 이름의 긴 작업(PC 백필)이 동시에 두 번 돌지 않게 하는 세션 잠금.

        PostgreSQL: pg_try_advisory_lock 을 잡은 연결을 작업 내내 들고 있다. 다른 곳이 잡고 있으면
        False 를 내준다 (기다리지 않음). SQLite 는 늘 True.
        """
        if self.dialect != "postgresql":
            yield True
            return
        key = lock_key(f"job:{name}")
        with self.engine.connect() as conn:
            ok = bool(conn.execute(text("SELECT pg_try_advisory_lock(:k)"), {"k": key}).scalar())
            conn.commit()
            try:
                yield ok
            finally:
                if ok:
                    try:
                        conn.execute(text("SELECT pg_advisory_unlock(:k)"), {"k": key})
                        conn.commit()
                    except SQLAlchemyError:  # 연결이 이미 끊겼으면 세션 잠금도 이미 풀림
                        logger.warning("작업 잠금 %s: 연결이 끊겨 풀 필요 없음", name)

    def prune_news(self, published_before: datetime) -> int:
        """발행 시각이 published_before 보다 이른 기사 삭제 (보관 기간 관리). 지운 행 수."""
        n = T.news
        return self._write(
            "뉴스 삭제",
            lambda c: c.execute(delete(n).where(n.c.published_at < published_before)).rowcount,
        )

    # ------------------------------------------------------------------ 요청으로 늘어난 종목
    def add_extra_tickers(self, tickers: Iterable[str], *, added_by: str = "API") -> int:
        """서비스 요청으로 처음 받은 종목을 정기 수집 대상에 올림 (이미 있으면 건너뜀). 추가 수."""
        syms = sorted({normalize_ticker(t) for t in tickers})
        if not syms:
            return 0
        et = T.extra_ticker

        def run(conn: Any) -> int:
            ids = self._ensure_assets(conn, syms)
            have = set(conn.execute(select(et.c.ticker).where(et.c.ticker.in_(syms))).scalars())
            now = self._clock()
            rows = [
                {"ticker": s, "asset_id": ids[s], "added_by": added_by, "added_at": now}
                for s in syms
                if s not in have
            ]
            if rows:
                self._insert_many(conn, et, rows)
            return len(rows)

        return self._write("추가 종목", run)

    def extra_tickers(self, *, since: datetime | None = None) -> list[str]:
        """요청으로 늘어난 종목 (추가 순서). since 를 주면 그 뒤에 추가된 것만."""
        et = T.extra_ticker
        q = select(et.c.ticker).order_by(et.c.added_at, et.c.ticker)
        if since is not None:
            q = q.where(et.c.added_at >= since)
        return self._read("추가 종목", lambda c: list(c.execute(q).scalars()))

    def source_status(self) -> dict[str, dict[str, Any]]:
        """출처별 최근 성공·실패 시각."""
        ds = T.data_sources
        q = select(ds.c.source_name, ds.c.last_success_at, ds.c.last_failure_at)
        return self._read(
            "출처",
            lambda c: {
                r.source_name: {
                    "last_success_at": r.last_success_at,
                    "last_failure_at": r.last_failure_at,
                }
                for r in c.execute(q)
            },
        )

    # ------------------------------------------------------------------ 재무·뉴스 (확장)
    def upsert_financials(self, rows: list[FinancialRow]) -> int:
        """재무 지표 저장 (종목·출처·기간·연결구분·지표 기준). 종목은 assets 에 먼저 있어야 함.

        원본은 financials_source 에 넣고, 같은 트랜잭션에서 그 종목들의 계약 financials 를 다시
        고른다 (_publish_financials). 반영 행 수는 원본 기준.
        """

        def run(conn: Any) -> int:
            assets = {r.asset_id for r in rows}
            self._require_assets(conn, assets)
            _lock(conn, "financials_source")
            data = [{**r.model_dump(), "source": self._source(conn, r.source)} for r in rows]
            n = self._upsert(
                conn,
                T.financials_source,
                ("asset_id", "source", "period", "fs_div", "metric"),
                _FIN_SOURCE_VALUE_COLS,
                data,
            )
            if n:
                self._publish_financials(conn, sorted(assets))
            return n

        return self._write("재무", run)

    def _publish_financials(self, conn: Any, asset_ids: Sequence[str]) -> int:
        """종목들의 계약 financials 를 원본에서 다시 골라 저장. 반영 행 수.

        키 (asset_id, period_end, statement, item): item = 지표 이름, statement = statement_of.
        period_end 가 없는 원본 행은 키를 만들 수 없어 싣지 않는다.
        같은 키 후보가 여럿이면 ① 시장별 출처 우선순위(FIN_SOURCE_PRIORITY) ② 연결구분
        CFS > OFS > - ③ 가장 이른 공시일(disclosed_at) ④ 기간·출처 이름 순.
        ③ 은 같은 키 값이 여러 원본 행에 있을 때(SEC 스냅샷을 여러 번 받은 경우 등) 처음 공시된
        값을 고르기 위함 (report_date 이전에는 그 값이 보이지 않아야 하므로).
        한계: 원본 키(출처·기간·연결구분·지표)가 같은 정정 공시는 원본 행을 덮어써 값과 공시일이
        함께 바뀐다. 선견은 없지만 정정 전 값은 남지 않는다 (F2_문제점.md 열린 항목).
        """
        if not asset_ids:
            return 0
        _lock_publish(conn, "financials")
        f, a = T.financials_source, T.assets
        markets = {
            r.asset_id: r.market
            for r in conn.execute(
                select(a.c.asset_id, a.c.market).where(a.c.asset_id.in_(asset_ids))
            )
        }
        q = select(
            f.c.asset_id,
            f.c.source,
            f.c.period,
            f.c.fs_div,
            f.c.metric,
            f.c.value,
            f.c.unit,
            f.c.period_end,
            f.c.disclosed_at,
        ).where(f.c.asset_id.in_(asset_ids), f.c.period_end.is_not(None))

        def rank(r: Any) -> tuple[Any, ...]:
            order = FIN_SOURCE_PRIORITY.get(markets.get(r.asset_id, ""), ())
            prio = order.index(r.source) if r.source in order else len(order)
            div = FS_DIV_ORDER.index(r.fs_div) if r.fs_div in FS_DIV_ORDER else len(FS_DIV_ORDER)
            return (prio, r.source, div, r.disclosed_at, r.period)

        best: dict[tuple[str, date, str, str], Any] = {}
        for r in sorted(conn.execute(q), key=rank):
            item = r.metric
            best.setdefault((r.asset_id, r.period_end, statement_of(item), item), r)
        now = self._clock()
        out = [
            {
                "asset_id": aid,
                "period_end": pend,
                "statement": stmt,
                "item": item,
                "value": r.value,
                "unit": r.unit,
                "report_date": r.disclosed_at,
                "source": r.source,
                "fs_div": r.fs_div,
                "period": r.period,
                "updated_at": now,
            }
            for (aid, pend, stmt, item), r in best.items()
        ]
        return self._upsert(
            conn,
            T.financials,
            ("asset_id", "period_end", "statement", "item"),
            _FIN_PUBLISH_VALUE_COLS,
            out,
        )

    def get_financials_as_of(
        self, asset_id: str, as_of: date, metrics: list[str] | None = None
    ) -> list[FinancialRow]:
        """as_of 까지 공시된 지표 중 (출처, 연결구분, 지표) 별 가장 최근 기간 값 (선견 금지).

        출처별 원본(financials_source)을 읽는다 (출처·연결구분마다 따로 돌려줌, API·디버그용).
        분석 쪽 계약 테이블은 financials (_publish_financials). 결과는 (지표, 출처, 연결구분) 순.
        """
        f = T.financials_source
        q = select(f).where(f.c.asset_id == asset_id, f.c.disclosed_at <= as_of)
        if metrics:
            q = q.where(f.c.metric.in_(metrics))
        rows = self._read("재무", lambda c: c.execute(q).all())
        best: dict[tuple[str, str, str], Any] = {}
        for r in sorted(
            rows,
            key=lambda r: (r.period_end or date.min, r.disclosed_at, r.period),
            reverse=True,
        ):
            best.setdefault((r.metric, r.source, r.fs_div), r)
        fields = set(FinancialRow.model_fields)
        return [
            FinancialRow(**{k: v for k, v in r._asdict().items() if k in fields})
            for _, r in sorted(best.items())
        ]

    def upsert_news(self, rows: list[NewsRow]) -> int:
        """뉴스 저장 (종목·url 기준, url 은 해시로 비교). 종목은 assets 에 먼저 있어야 함.

        사실 표시(news_labels)가 비어 있으면 채우고, 건드린 기사 묶음의 is_first_report 를 다시 정함.
        """

        def run(conn: Any) -> int:
            self._require_assets(conn, {r.asset_id for r in rows})
            _lock(conn, "news")
            names = news_asset_names(conn, {r.asset_id for r in rows})
            data = []
            for r in rows:
                d = {
                    **r.model_dump(),
                    "source": self._source(conn, r.source, kind="QUAL"),
                    "url_hash": url_hash(r.url),
                    "content_hash": hashlib.sha256(f"{r.url}\n{r.title}".encode()).hexdigest(),
                }
                if r.story_id is None:
                    d.update(news_labels.labels(
                        names[r.asset_id], title=r.title, url=r.url, publisher=r.publisher,
                        published_at=r.published_at, query=r.query, source=r.source,
                    ))  # fmt: skip
                data.append(d)
            n = self._upsert(conn, T.news, ("asset_id", "url_hash"), NEWS_VALUE_COLS, data)
            mark_first_reports(conn, {(d["asset_id"], d["story_id"]) for d in data})
            return n

        return self._write("뉴스", run)

    def upsert_disclosures(self, rows: list[DisclosureRow]) -> int:
        """공시 저장 (출처·공시 번호·종목 기준, 값이 바뀐 행만). 종목은 assets 에 먼저 있어야 함."""

        def run(conn: Any) -> int:
            self._require_assets(conn, {r.asset_id for r in rows})
            _lock(conn, "disclosures")
            data = [{**r.model_dump(), "source": self._source(conn, r.source)} for r in rows]
            cols = [
                c for c in DisclosureRow.model_fields if c not in (*DISCLOSURE_KEY, "fetched_at")
            ]
            return self._upsert(conn, T.disclosures, DISCLOSURE_KEY, cols, data)

        return self._write("공시", run)

    def annual_report_dates(self, asset_ids: Sequence[str]) -> dict[str, dict[str, date]]:
        """asset_id → {결산년월 YYYYMM: DART 사업보고서 최초 접수일(한국 날짜)} (disclosures 에서, 정정 제외).

        제목 끝의 "(2008.12)" 로 결산년월을 읽는다. 보충 재무(KIS_FIN)의 공시일에 쓴다."""
        if not asset_ids or not inspect(self.engine).has_table("disclosures"):
            return {}
        d = T.disclosures
        q = (
            select(d.c.asset_id, d.c.title, func.min(d.c.filed_at))
            .where(d.c.asset_id.in_(sorted(set(asset_ids))), d.c.source == "DART",
                   d.c.form.like("사업보고서%"), d.c.is_amendment.is_(False))
            .group_by(d.c.asset_id, d.c.title)
        )  # fmt: skip
        out: dict[str, dict[str, date]] = defaultdict(dict)
        kst = timedelta(hours=9)
        for aid, title, filed in self._read("공시", lambda c: c.execute(q).all()):
            m = _REPORT_PERIOD.search(title or "")
            if not m:
                continue
            ym, day = m.group(1) + m.group(2), (filed + kst).date()
            if ym not in out[aid] or day < out[aid][ym]:
                out[aid][ym] = day
        return dict(out)

    def get_news(self, asset_id: str, start: datetime, end: datetime) -> list[NewsRow]:
        """[start, end] 에 발행된 기사 (발행 시각 순)."""
        n = T.news
        q = (
            select(n)
            .where(n.c.asset_id == asset_id, n.c.published_at >= start, n.c.published_at <= end)
            .order_by(n.c.published_at, n.c.url)
        )
        fields = set(NewsRow.model_fields)
        return self._read(
            "뉴스",
            lambda c: [
                NewsRow(**{k: v for k, v in r._asdict().items() if k in fields})
                for r in c.execute(q)
            ],
        )

    def _require_assets(self, conn: Any, asset_ids: set[str]) -> None:
        a = T.assets
        have = set(
            conn.execute(select(a.c.asset_id).where(a.c.asset_id.in_(sorted(asset_ids)))).scalars()
        )
        missing = sorted(asset_ids - have)
        if missing:
            raise RepositoryError(
                f"assets 에 없는 종목: {missing[:10]} (upsert_assets 먼저)",
                code="REPO_WRITE_FAILED",
                details={"missing": missing},
            )

    # ------------------------------------------------------------ 일별 가치평가 (valuation_daily)
    def valuation_assets(self, markets: Sequence[str] | None = None) -> list[dict[str, Any]]:
        """가치평가 대상 종목 (asset_type STOCK): asset_id·ticker(yfinance 표기)·currency·market."""
        a = T.assets
        q = select(a.c.asset_id, a.c.yfinance_symbol, a.c.currency, a.c.market).where(
            a.c.asset_type == "STOCK"
        )
        if markets:
            q = q.where(a.c.market.in_([m.upper() for m in markets]))
        return self._read(
            "종목 마스터",
            lambda c: [
                {"asset_id": r[0], "ticker": r[1], "currency": r[2], "market": r[3]}
                for r in c.execute(q.order_by(a.c.asset_id))
            ],
        )

    def _max_dates(self, table: Any, asset_ids: Sequence[str] | None) -> dict[str, date]:
        q = select(table.c.asset_id, func.max(table.c.date)).group_by(table.c.asset_id)

        def run(conn: Any) -> dict[str, date]:
            if asset_ids is None:
                return {r[0]: r[1] for r in conn.execute(q)}
            out: dict[str, date] = {}
            for part in _chunks(sorted(set(asset_ids))):
                out.update({r[0]: r[1] for r in conn.execute(q.where(table.c.asset_id.in_(part)))})
            return out

        return self._read("마지막 날짜", run)

    def price_last_dates(self, asset_ids: Sequence[str] | None = None) -> dict[str, date]:
        """종목별 계약 price_daily 마지막 날짜."""
        return self._max_dates(T.price_daily, asset_ids)

    def valuation_last_dates(self, asset_ids: Sequence[str] | None = None) -> dict[str, date]:
        """종목별 valuation_daily 마지막 날짜."""
        return self._max_dates(T.valuation_daily, asset_ids)

    def valuation_changes(self, since: datetime) -> dict[str, date]:
        """since 뒤에 바뀐 입력 → 종목별 다시 계산할 첫 날.

        price_daily: 바뀐 행의 가장 이른 날짜. financials: 바뀐 행의 가장 이른 공시일
        (주식분할 행이 바뀌면 그 종목 전체 = date.min).
        """
        p, f = T.price_daily, T.financials
        from backend.pipeline.valuation import SPLIT_ITEM, VALUATION_ITEMS

        def run(conn: Any) -> dict[str, date]:
            out: dict[str, date] = {}

            def put(a: str, d: date) -> None:
                out[a] = min(out.get(a, d), d)

            q1 = (
                select(p.c.asset_id, func.min(p.c.date))
                .where(p.c.updated_at > since)
                .group_by(p.c.asset_id)
            )
            for a, d in conn.execute(q1):
                put(a, d)
            q2 = (
                select(f.c.asset_id, f.c.item, func.min(f.c.report_date))
                .where(f.c.updated_at > since, f.c.item.in_(VALUATION_ITEMS))
                .group_by(f.c.asset_id, f.c.item)
            )
            for a, item, d in conn.execute(q2):
                put(a, date.min if item == SPLIT_ITEM else d)
            return out

        return self._read("가치평가 변경", run)

    def valuation_inputs(
        self, asset_ids: Sequence[str], start: date
    ) -> tuple[pd.DataFrame, pd.DataFrame]:
        """가치평가 입력: (가격 asset_id·date·close·fetched_at [start 부터],
        재무 asset_id·item·period_end·period·value·report_date·source [VALUATION_ITEMS 전부]).
        재무 단위가 통화 코드(3글자)인데 종목 통화와 다르면 뺀다 (예: 미국 상장 IFRS 기업의 EUR 값을
        USD 가격과 섞지 않게)."""
        from backend.pipeline.valuation import VALUATION_ITEMS

        p, f = T.price_daily, T.financials
        cur = select(T.assets.c.currency).where(T.assets.c.asset_id == f.c.asset_id)
        ids = sorted(set(asset_ids))

        def run(conn: Any) -> tuple[pd.DataFrame, pd.DataFrame]:
            prices: list[Any] = []
            fins: list[Any] = []
            for part in _chunks(ids):
                prices += conn.execute(
                    select(p.c.asset_id, p.c.date, p.c.close, p.c.fetched_at).where(
                        p.c.asset_id.in_(part), p.c.date >= start
                    )
                ).all()
                fins += conn.execute(
                    select(
                        f.c.asset_id, f.c.item, f.c.period_end, f.c.period, f.c.value,
                        f.c.report_date, f.c.source,
                    ).where(
                        f.c.asset_id.in_(part), f.c.item.in_(VALUATION_ITEMS),
                        or_(f.c.unit.is_(None), func.length(f.c.unit) != 3,
                            f.c.unit == cur.scalar_subquery()),
                    )
                ).all()  # fmt: skip
            pcols = ["asset_id", "date", "close", "fetched_at"]
            fcols = ["asset_id", "item", "period_end", "period", "value", "report_date", "source"]
            return (
                pd.DataFrame([tuple(r) for r in prices], columns=pcols),
                pd.DataFrame([tuple(r) for r in fins], columns=fcols),
            )

        return self._read("가치평가 입력", run)

    def upsert_valuation(self, rows: list[dict[str, Any]]) -> int:
        """valuation_daily 저장 (asset_id, date 기준, 값이 다를 때만 갱신). 반영 행 수."""
        from backend.pipeline.valuation import VALUE_COLS

        now = self._clock()
        data = [{**r, "updated_at": now} for r in rows]

        def run(conn: Any) -> int:
            _lock(conn, "valuation_daily")
            n = 0
            by_asset: dict[str, list[dict[str, Any]]] = defaultdict(list)
            for r in data:
                by_asset[r["asset_id"]].append(r)
            for part in by_asset.values():  # 종목마다 날짜 범위로 기존 행을 읽어 비교
                n += self._upsert(conn, T.valuation_daily, ("asset_id", "date"), VALUE_COLS, part)
            return n

        return self._write("가치평가", run)

    # ------------------------------------------------------------ 실행 기록 (계약 쓰기 테이블)
    def save_run_artifact(
        self,
        run_id: str,
        request_id: str,
        results: dict[str, Any],
        params: dict[str, Any],
        llm_usage: dict[str, Any] | None = None,
    ) -> None:
        """실행 산출물 저장: 결과 통합 JSON, 파라미터 스냅샷, LLM 사용량.

        같은 run_id 면 내용을 바꾼다 (실행 중 결과를 채워 가는 경우). created_at 은 처음 값 유지.
        """
        row = {
            "run_id": run_id,
            "request_id": request_id,
            "results_json": dict(results),
            "params_json": dict(params),
            "llm_usage_json": None if llm_usage is None else dict(llm_usage),
        }

        def run(conn: Any) -> None:
            a = T.run_artifact
            if conn.execute(select(a.c.run_id).where(a.c.run_id == run_id)).first():
                conn.execute(update(a).where(a.c.run_id == run_id).values(**row))
            else:
                conn.execute(insert(a).values(**row, created_at=self._clock()))

        self._write("실행 산출물", run)

    def get_run_artifact(self, run_id: str) -> dict[str, Any] | None:
        """저장된 실행 산출물 (run_id, request_id, created_at, results, params, llm_usage)."""
        a = T.run_artifact

        def run(conn: Any) -> dict[str, Any] | None:
            row = conn.execute(select(a).where(a.c.run_id == run_id)).first()
            if row is None:
                return None
            out = row._asdict()
            for k in ("results_json", "params_json", "llm_usage_json"):
                out[k.removesuffix("_json")] = out.pop(k)
            return out

        return self._read("실행 산출물", run)

    def save_step(self, rec: StepRecord) -> None:
        """단계 기록 저장. 같은 (run_id, step) 이면 최신 상태로 바꿈 (QUEUED→STARTED→SUCCESS)."""
        row = {
            "run_id": rec.run_id,
            "step": rec.step,
            "status": rec.status.value,
            "started_at": rec.started_at,
            "ended_at": rec.ended_at,
            "summary": rec.summary,
            "error_code": rec.error_code,
            "error_message": rec.error_message,
        }
        s = T.run_step

        def run(conn: Any) -> None:
            cond = and_(s.c.run_id == rec.run_id, s.c.step == rec.step)
            if conn.execute(select(s.c.run_id).where(cond)).first():
                conn.execute(update(s).where(cond).values(**row))
            else:
                conn.execute(insert(s).values(**row))

        self._write("실행 단계", run)

    def get_steps(self, run_id: str) -> list[StepRecord]:
        """실행의 단계 기록 (시작 시각 순, 아직 시작 안 한 단계는 뒤, 같으면 단계 이름 순)."""
        s = T.run_step
        q = (
            select(s)
            .where(s.c.run_id == run_id)
            .order_by(s.c.started_at.is_(None), s.c.started_at, s.c.step)
        )
        return self._read("실행 단계", lambda c: [StepRecord(**r._asdict()) for r in c.execute(q)])

    def save_report(
        self,
        report_id: str,
        doc: dict[str, Any],
        *,
        strategy_name: str | None,
        request_summary: str | None,
        as_of: date,
    ) -> None:
        """리포트 저장 (report_id = run_id). 한 번 저장한 리포트는 바꾸지 않는다 (계약: 불변).

        같은 report_id 가 이미 있거나 run_artifact 가 없으면 RepositoryError(REPO_WRITE_FAILED).
        """
        rp, a = T.report, T.run_artifact
        row = {
            "report_id": report_id,
            "created_at": self._clock(),
            "doc_json": dict(doc),
            "strategy_name": strategy_name,
            "request_summary": request_summary,
            "as_of": as_of,
        }

        def run(conn: Any) -> None:
            if not conn.execute(select(a.c.run_id).where(a.c.run_id == report_id)).first():
                raise RepositoryError(
                    f"run_artifact 가 없는 report_id: {report_id} (save_run_artifact 먼저)",
                    code="REPO_WRITE_FAILED",
                    details={"report_id": report_id},
                )
            if conn.execute(select(rp.c.report_id).where(rp.c.report_id == report_id)).first():
                raise RepositoryError(
                    f"이미 저장된 리포트: {report_id} (리포트는 바꾸지 않음, 새 run 으로 저장)",
                    code="REPO_WRITE_FAILED",
                    details={"report_id": report_id, "reason": "immutable"},
                )
            conn.execute(insert(rp).values(**row))

        self._write("리포트", run)

    def get_report(self, report_id: str) -> dict[str, Any] | None:
        """저장된 리포트 (report_id, created_at, doc, strategy_name, request_summary, as_of)."""
        rp = T.report

        def run(conn: Any) -> dict[str, Any] | None:
            row = conn.execute(select(rp).where(rp.c.report_id == report_id)).first()
            if row is None:
                return None
            out = row._asdict()
            out["doc"] = out.pop("doc_json")
            return out

        return self._read("리포트", run)


SqliteRepository = SqlRepository
"""예전 이름 (SQLite 전용이던 때). 새 코드는 SqlRepository 를 쓴다."""
