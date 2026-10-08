"""M02-04 SqlRepository: MarketDataRepository 의 SQLAlchemy Core 구현 (PostgreSQL·SQLite 공용).

같은 코드가 PostgreSQL(기본, AWS Lightsail)과 SQLite(테스트·혼자 개발)에서 돈다. upsert 는 방언
전용 문법(ON CONFLICT 등) 없이 "읽어서 비교 → 새 행 INSERT / 값이 다른 행 UPDATE" 로 한다.

다른 모듈과의 약속 (C-10)
- 종목은 yfinance 표기(005930.KS, BRK-B)로 주고받고, price_daily.ticker 에도 그대로 저장한다.
  추가 칸 asset_id(KR-005930, US-BRK-B) 로 종목 마스터(assets)와 잇는다. 처음 보는 종목은
  assets 에 기본 행을 만든다.
- 출처(source)는 이름 문자열. 대문자로 맞춘다 ("yfinance" → YFINANCE). 처음 보는 출처는
  data_sources 에 추가한다.

값 비교 기준 (부록 B 규칙: 같은 키로 다시 받으면 값이 다를 때만 갱신, 수집 시각은 비교 안 함)
- price_daily : adj_close, volume, currency
- fx_daily    : rate
- financials  : value, unit, fiscal_year, report_code, period_end, disclosed_at, rcept_no
- news        : title, content, publisher, published_at, language
"""

from __future__ import annotations

import hashlib
import logging
import math
from collections import defaultdict
from collections.abc import Callable, Iterable, Sequence
from datetime import UTC, date, datetime, timedelta
from typing import Any

import pandas as pd
from pydantic import BaseModel, ValidationError
from sqlalchemy import (
    Engine,
    and_,
    bindparam,
    delete,
    func,
    insert,
    inspect,
    select,
    text,
    tuple_,
    update,
)
from sqlalchemy.exc import SQLAlchemyError

from myfinsight.data.normalizer import currency_of_symbol, default_asset, normalize_ticker
from myfinsight.data.repository import tables as T
from myfinsight.schemas.errors import RepositoryError
from myfinsight.schemas.market import (
    FxRate,
    IndexCode,
    IndexConstituent,
    PriceBar,
    PriceMeta,
    UniverseResult,
)
from myfinsight.schemas.market_ext import AssetInfo, FinancialRow, NewsRow
from myfinsight.schemas.profile import UserProfile
from myfinsight.schemas.report import Report, ReportData
from myfinsight.schemas.runlog import StepRecord
from myfinsight.schemas.spec import StrategySpec

logger = logging.getLogger(__name__)

EPOCH = datetime(1970, 1, 1, tzinfo=UTC)
CONSENSUS = "CONSENSUS"
START_GRACE_DAYS = 4
"""요청 시작일이 휴장일(주말·공휴일)이어도 매번 재수집하지 않도록, 첫 저장일이 시작일 뒤
이 일수 안이면 시작 쪽은 덮인 것으로 본다."""
_CHUNK = 500  # IN (...) 에 넣는 키 개수 상한
DEFAULT_PRICE_PRIORITY: dict[str, tuple[str, ...]] = {
    # 미국: 공식 API(Alpaca) → Tiingo → yfinance (모두 분할+배당 보정 수정종가)
    "USD": ("ALPACA", "TIINGO", "YFINANCE"),
    # 한국: KIS 수정주가는 배당을 반영하지 않으므로 수정종가는 yfinance 먼저, 빈 날은 KIS
    "KRW": ("YFINANCE", "KIS"),
}
"""get_prices 가 같은 (종목, 날짜) 에서 고르는 출처 순서 (CONSENSUS 는 항상 맨 앞)."""

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
_ASSET_VALUE_COLS = (
    "ticker",
    "name",
    "market",
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


class SqlRepository:
    """PostgreSQL·SQLite 저장소. 보통 `open_repository()` 로 만든다.

    cache_max_age_days: needs_fetch 가 요구하는 마지막 저장일 = 오늘 기준 n 번째 이전 평일
    (AppConfig.data.cache_max_age_days, 기본 1 = 직전 거래일).
    clock: created_at·updated_at 에 쓸 현재 시각 (테스트에서 고정 가능).
    price_priority: 통화별 출처 우선순위 (기본 DEFAULT_PRICE_PRIORITY).
    """

    def __init__(
        self,
        engine: Engine,
        *,
        cache_max_age_days: int = 1,
        clock: Callable[[], datetime] = lambda: datetime.now(UTC),
        create_tables: bool = True,
        price_priority: dict[str, Sequence[str]] | None = None,
    ) -> None:
        self.engine = engine
        self.cache_max_age_days = max(1, cache_max_age_days)
        self.price_priority = {
            cur: tuple(source_key(x) for x in names)
            for cur, names in (price_priority or DEFAULT_PRICE_PRIORITY).items()
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
        T.metadata.create_all(conn)
        _migrate_news_url_hash(conn)
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
        try:
            with self.engine.begin() as conn:
                return fn(conn)
        except RepositoryError:
            raise
        except (SQLAlchemyError, ValueError, TypeError) as exc:
            raise RepositoryError(
                f"{what} 저장 실패: {exc}", code="REPO_WRITE_FAILED", details={"what": what}
            ) from exc

    def _read(self, what: str, fn: Callable[[Any], Any]) -> Any:
        try:
            with self.engine.connect() as conn:
                return fn(conn)
        except RepositoryError:
            raise
        except (SQLAlchemyError, ValidationError, ValueError, TypeError) as exc:
            raise RepositoryError(
                f"{what} 조회 실패: {exc}", code="REPO_READ_FAILED", details={"what": what}
            ) from exc

    @staticmethod
    def _upsert(
        conn: Any,
        table: Any,
        key_cols: Sequence[str],
        value_cols: Sequence[str],
        rows: list[dict[str, Any]],
    ) -> int:
        """자연키로 기존 행을 읽어 비교한 뒤 새 행은 INSERT, 값이 다른 행만 UPDATE. 반영 행 수."""
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
        return len(to_insert) + len(changed)

    @staticmethod
    def _insert_many(conn: Any, table: Any, rows: Sequence[dict[str, Any]]) -> None:
        """여러 행 INSERT. PostgreSQL 은 INSERT ... VALUES (...), (...) 한 문장씩 묶어 보냄
        (pg8000 의 executemany 는 행마다 원격 DB 왕복). 칸 구성이 같은 행끼리 묶는다."""
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
        원격 DB 왕복을 줄인다 (pg8000 의 executemany 는 행마다 왕복). rows 는 칸 이름 그대로."""
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
        """가격 저장. 자연키(티커, 날짜, 출처)가 같고 값도 같으면 건너뜀. 반영 행 수."""

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
            return self._upsert(
                conn,
                T.price_daily,
                ("ticker", "date", "source"),
                ("adj_close", "volume", "currency", "open", "high", "low", "close"),
                rows,
            )

        n = self._write("가격", run)
        logger.info("price_daily: %d/%d행 반영", n, len(bars))
        return n

    def get_prices(
        self, tickers: list[str], start: date, end: date
    ) -> tuple[pd.DataFrame, PriceMeta]:
        """[start, end] 수정종가를 PriceFrame 계약(0-4) 모양으로 돌려준다.

        열 = 요청 티커 전부(오름차순, 저장된 값이 없으면 전부 NaN). 행 = 저장된 날짜의 합집합.
        같은 (종목, 날짜) 에 출처가 여럿이면 CONSENSUS 행 → 통화별 출처 우선순위(price_priority)
        → 수집 시각이 가장 늦은 행 → 출처 이름 오름차순.
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

        rows = self._read("가격", run)

        cur = currencies[0] if currencies else "USD"
        order = {s: i for i, s in enumerate(self.price_priority.get(cur, ()))}

        def rank(r: Any) -> tuple[Any, ...]:
            prio = -1 if r.source == CONSENSUS else order.get(r.source, len(order))
            return (r.ticker, r.date, prio, -r.fetched_at.timestamp(), r.source)

        picked: dict[tuple[str, date], Any] = {}
        for r in sorted(rows, key=rank):
            picked.setdefault((r.ticker, r.date), r)
        chosen = list(picked.values())
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
        """저장된 첫 날짜·마지막 날짜 (출처 무관). 없으면 None."""
        p = T.price_daily
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
        """여러 티커의 저장 범위를 한 번에. source 를 주면 그 출처 행만, 없으면 출처 무관.

        저장된 게 없는 티커는 빠짐.
        """
        p = T.price_daily
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
        p = T.price_daily
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
        p = T.price_daily
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

    def save_verification(
        self,
        consensus: list[dict[str, Any]],
        marks: list[dict[str, Any]],
        *,
        drop_consensus: Sequence[tuple[str, date]] = (),
    ) -> int:
        """교차검증 결과 저장 (한 트랜잭션).

        consensus: CONSENSUS 행 (price_daily 칸 이름 그대로). 같은 키면 값이 다를 때만 갱신.
        marks: 출처별 행에 적을 ticker·date·source·dev_pct·adj_dev_pct·verify_status.
        drop_consensus: 출처가 하나만 남아 지울 CONSENSUS 행.
        반영한 CONSENSUS 행 수.
        """
        p = T.price_daily

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
            if not consensus:
                return 0
            self._source(conn, CONSENSUS)
            return self._upsert(
                conn,
                p,
                ("ticker", "date", "source"),
                _CONSENSUS_VALUE_COLS,
                [{**r, "source": CONSENSUS} for r in consensus],
            )

        return self._write("교차검증", run)

    def mismatch_days(self, tickers: Sequence[str], start: date, end: date) -> dict[str, int]:
        """[start, end] 에 CONSENSUS 가 MISMATCH 인 거래일 수 (품질 경고용). 0 인 티커는 빠짐."""
        p = T.price_daily
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
        """[start, end] 출처별 행의 검증 표시를 지워 다시 계산하게 함. 지운 행 수."""
        p = T.price_daily
        cond = [p.c.source != CONSENSUS, p.c.date >= start, p.c.date <= end]
        parts: list[Any] = [None]
        if tickers is not None:
            parts = list(_chunks(sorted({normalize_ticker(t) for t in tickers})))

        def run(conn: Any) -> int:
            n = 0
            for part in parts:
                where = [*cond] if part is None else [*cond, p.c.ticker.in_(part)]
                n += conn.execute(update(p).where(*where).values(**_UNVERIFIED)).rowcount
            return n

        return self._write("검증 초기화", run)

    # ------------------------------------------------------------------ 환율
    def upsert_fx(self, rates: list[FxRate]) -> int:
        """환율 저장. 자연키(통화쌍, 날짜, 출처)가 같고 값도 같으면 건너뜀. 반영 행 수."""

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
            return self._upsert(conn, T.fx_daily, ("pair", "date", "source"), ("rate",), rows)

        return self._write("환율", run)

    def get_fx_on_or_before(self, d: date) -> FxRate | None:
        """d 이전(포함) 가장 최근 USD/KRW. 같은 날 출처가 여럿이면 수집 시각이 늦은 것."""
        f = T.fx_daily
        q = (
            select(f.c.pair, f.c.date, f.c.rate, f.c.source, f.c.fetched_at)
            .where(f.c.pair == "USDKRW", f.c.date <= d)
            .order_by(f.c.date.desc(), f.c.fetched_at.desc(), f.c.source)
            .limit(1)
        )

        def run(conn: Any) -> FxRate | None:
            row = conn.execute(q).first()
            return FxRate(**row._asdict()) if row else None

        return self._read("환율", run)

    # ------------------------------------------------------------------ 재현용 입력
    def save_run_artifact(
        self,
        run_id: str,
        profile: UserProfile,
        spec: StrategySpec,
        universe: UniverseResult,
        config: BaseModel,
    ) -> None:
        """실행 입력을 JSON 으로 저장. 같은 run_id 면 바꿈."""
        row = {
            "run_id": run_id,
            "created_at": self._clock(),
            "profile_json": profile.model_dump(mode="json"),
            "spec_json": spec.model_dump(mode="json"),
            "spec_hash": spec.spec_hash(),
            "universe_json": universe.model_dump(mode="json"),
            "config_json": config.model_dump(mode="json"),
        }

        def run(conn: Any) -> None:
            a = T.run_artifact
            if conn.execute(select(a.c.run_id).where(a.c.run_id == run_id)).first():
                conn.execute(update(a).where(a.c.run_id == run_id).values(**row))
            else:
                conn.execute(insert(a).values(**row))

        self._write("실행 입력", run)

    def get_run_artifact(self, run_id: str) -> dict[str, Any] | None:
        """저장된 실행 입력 (JSON 칸은 dict). 재현·디버그용."""
        a = T.run_artifact

        def run(conn: Any) -> dict[str, Any] | None:
            row = conn.execute(select(a).where(a.c.run_id == run_id)).first()
            if row is None:
                return None
            out = row._asdict()
            for k in ("profile_json", "spec_json", "universe_json", "config_json"):
                out[k.removesuffix("_json")] = out.pop(k)
            return out

        return self._read("실행 입력", run)

    # ------------------------------------------------------------------ 구성종목
    def save_constituents(self, rows: list[IndexConstituent]) -> None:
        """구성종목 저장. 같은 (지수, 스냅샷 날짜) 는 지우고 새로 넣는다."""
        if not rows:
            return
        ic = T.index_constituent

        def run(conn: Any) -> None:
            names = {normalize_ticker(r.ticker): r.name for r in rows}
            ids = self._ensure_assets(conn, names, names)
            groups: dict[tuple[str, date], list[dict[str, Any]]] = {}
            for r in rows:
                code = IndexCode(r.index_code).value
                groups.setdefault((code, r.snapshot_date), []).append(
                    {
                        "index_code": code,
                        "snapshot_date": r.snapshot_date,
                        "ticker": normalize_ticker(r.ticker),
                        "name": r.name,
                        "sector": r.sector,
                        "industry": r.industry,
                        "source": r.source,
                        "fetched_at": r.fetched_at,
                        "asset_id": ids[normalize_ticker(r.ticker)],
                    }
                )
            for (code, snap), items in groups.items():
                conn.execute(delete(ic).where(ic.c.index_code == code, ic.c.snapshot_date == snap))
                self._insert_many(conn, ic, items)

        self._write("구성종목", run)

    def latest_constituents(self, index: IndexCode) -> list[IndexConstituent]:
        """가장 최근 스냅샷 (티커 오름차순). 없으면 빈 목록."""
        code = IndexCode(index).value
        ic = T.index_constituent

        def run(conn: Any) -> list[IndexConstituent]:
            snap = conn.execute(
                select(func.max(ic.c.snapshot_date)).where(ic.c.index_code == code)
            ).scalar()
            if snap is None:
                return []
            q = (
                select(
                    ic.c.index_code,
                    ic.c.ticker,
                    ic.c.name,
                    ic.c.sector,
                    ic.c.industry,
                    ic.c.snapshot_date,
                    ic.c.source,
                    ic.c.fetched_at,
                )
                .where(ic.c.index_code == code, ic.c.snapshot_date == snap)
                .order_by(ic.c.ticker)
            )
            return [IndexConstituent(**r._asdict()) for r in conn.execute(q)]

        return self._read("구성종목", run)

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
        """재무 지표 저장 (종목·출처·기간·연결구분·지표 기준). 종목은 assets 에 먼저 있어야 함."""

        def run(conn: Any) -> int:
            self._require_assets(conn, {r.asset_id for r in rows})
            data = [{**r.model_dump(), "source": self._source(conn, r.source)} for r in rows]
            return self._upsert(
                conn,
                T.financials,
                ("asset_id", "source", "period", "fs_div", "metric"),
                (
                    "value",
                    "unit",
                    "fiscal_year",
                    "report_code",
                    "period_end",
                    "disclosed_at",
                    "rcept_no",
                ),
                data,
            )

        return self._write("재무", run)

    def get_financials_as_of(
        self, asset_id: str, as_of: date, metrics: list[str] | None = None
    ) -> list[FinancialRow]:
        """as_of 까지 공시된 지표 중 (출처, 연결구분, 지표) 별 가장 최근 기간 값 (선견 금지).

        결과는 (지표, 출처, 연결구분) 순.
        """
        f = T.financials
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
        """뉴스 저장 (종목·url 기준, url 은 해시로 비교). 종목은 assets 에 먼저 있어야 함."""

        def run(conn: Any) -> int:
            self._require_assets(conn, {r.asset_id for r in rows})
            data = [
                {
                    **r.model_dump(),
                    "source": self._source(conn, r.source, kind="QUAL"),
                    "url_hash": url_hash(r.url),
                    "content_hash": hashlib.sha256(f"{r.url}\n{r.title}".encode()).hexdigest(),
                }
                for r in rows
            ]
            return self._upsert(
                conn,
                T.news,
                ("asset_id", "url_hash"),
                ("title", "content", "publisher", "published_at", "language"),
                data,
            )

        return self._write("뉴스", run)

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

    # ------------------------------------------------------------------ 실행 기록
    def save_step(self, rec: StepRecord) -> None:
        """단계 기록 저장. 같은 (run_id, step) 이면 최신 상태로 바꿈 (STARTED → SUCCESS)."""
        row = {
            "run_id": rec.run_id,
            "step": rec.step,
            "status": rec.status.value,
            "started_at": rec.started_at,
            "ended_at": rec.ended_at,
            "summary": rec.summary,
            "sources_json": list(rec.sources),
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
        """실행의 단계 기록 (시작 시각, 같으면 단계 이름 순)."""
        s = T.run_step
        q = select(s).where(s.c.run_id == run_id).order_by(s.c.started_at, s.c.step)

        def run(conn: Any) -> list[StepRecord]:
            out = []
            for r in conn.execute(q):
                d = r._asdict()
                d["sources"] = d.pop("sources_json") or []
                out.append(StepRecord(**d))
            return out

        return self._read("실행 단계", run)

    # ------------------------------------------------------------------ Report
    def save_report(self, report: Report) -> None:
        """Report 저장 (같은 run_id 면 바꿈). 그 run_id 의 save_run_artifact 가 먼저 있어야 함."""
        run_id = report.data.run_id
        row = {
            "run_id": run_id,
            "created_at": report.data.created_at,
            "data_json": report.data.model_dump(mode="json"),
            "text_markdown": report.text_markdown,
            "display_values_json": dict(report.display_values),
        }
        rp, a = T.report, T.run_artifact

        def run(conn: Any) -> None:
            if not conn.execute(select(a.c.run_id).where(a.c.run_id == run_id)).first():
                raise RepositoryError(
                    f"run_artifact 가 없는 run_id: {run_id} (save_run_artifact 먼저)",
                    code="REPO_WRITE_FAILED",
                    details={"run_id": run_id},
                )
            conn.execute(delete(rp).where(rp.c.run_id == run_id))
            conn.execute(insert(rp).values(**row))

        self._write("Report", run)

    def get_report(self, run_id: str) -> Report | None:
        """저장된 Report. 없으면 None."""
        rp = T.report

        def run(conn: Any) -> Report | None:
            row = conn.execute(select(rp).where(rp.c.run_id == run_id)).first()
            if row is None:
                return None
            return Report(
                data=ReportData.model_validate(row.data_json),
                text_markdown=row.text_markdown,
                display_values=row.display_values_json or {},
            )

        return self._read("Report", run)


SqliteRepository = SqlRepository
"""예전 이름 (SQLite 전용이던 때). 새 코드는 SqlRepository 를 쓴다."""
