"""분석 패키지(backend/analysis)가 쓰는 읽기 전용 Repository 메서드 (SqlRepository 에 섞어 넣음).

계약 읽기 테이블만 읽는다: price_daily, fx_daily, valuation_daily, index_constituent, news, assets.
모든 조회는 기준일(as_of) 이하로 자른 결과만 돌려주며, 호출자는 MarketDataView 가 선견 금지를 강제한다.
"""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Iterable, Sequence
from datetime import date, datetime, timedelta
from typing import Any

import pandas as pd
from sqlalchemy import func, select

from backend.db import tables as T
from backend.pipeline.normalizer import normalize_ticker
from backend.schemas.market import FxRate, IndexCode, IndexConstituent
from backend.schemas.market_ext import DisclosureRecord, NewsRecord

_CHUNK = 500


def _chunks(items: Sequence[Any], size: int = _CHUNK) -> Iterable[Sequence[Any]]:
    for i in range(0, len(items), size):
        yield items[i : i + size]


PRICE_BAR_COLS = ("ticker", "date", "close", "adj_close", "volume", "currency")  # 분석이 쓰는 열만 (open/high/low/source 는 읽지 않음)

# 공시 사건 중요도 (작을수록 먼저). 종목당 상한(per_asset)을 자를 때 쓴다. 목록에 없는 종류는 9.
_EVENT_PRIORITY: dict[str, int] = {
    "earnings": 0, "buyback": 1, "dividend": 1, "merger_split": 1, "acquisition_disposition": 1, "tender_offer": 1, "control_change": 1,
    "material_agreement": 2, "agreement_termination": 2, "capex": 2, "securities_offering": 2, "capital_change": 2, "restructuring": 2,
    "bankruptcy": 2, "debt_acceleration": 2, "delisting_notice": 2, "restatement": 2, "impairment": 2, "litigation": 3, "executive_change": 3,
    "auditor_change": 3, "production_change": 3, "rumor_response": 3, "cybersecurity": 3, "merger_registration": 3, "fair_disclosure": 4,
    "quarterly_report": 5, "annual_report": 5, "semiannual_report": 5, "investor_relations": 6, "reg_fd": 6, "voluntary_disclosure": 6, "other_event": 7,
}  # fmt: skip


def _ordinal(d: Any) -> int:
    """date / datetime / 'YYYY-MM-DD' 문자열(sqlite) 모두 정수로."""
    if isinstance(d, datetime):
        return d.date().toordinal()
    if isinstance(d, date):
        return d.toordinal()
    return date.fromisoformat(str(d)[:10]).toordinal()
VALUATION_COLS = (
    "asset_id", "ticker", "date", "currency", "close", "split_factor", "shares_outstanding", "market_cap",
    "eps_ttm", "per", "bps", "pbr", "roe_ttm", "dps_ttm", "dividend_yield", "fin_period_end", "fin_disclosed_at",
)  # fmt: skip


class AnalysisReadersMixin:
    """SqlRepository 가 상속. `self._read(what, fn)` 과 `self._asset_ids` 를 쓴다."""

    def get_price_bars(self, tickers: Sequence[str], start: date, end: date) -> pd.DataFrame:
        """[start, end] 의 계약 price_daily 행 (long 형식). 통화가 섞여도 된다 (currency 칸으로 구분).

        열: ticker, date(datetime64), close, adj_close, volume, currency.
        """
        wanted = sorted({normalize_ticker(t) for t in tickers})
        p = T.price_daily

        def run(conn: Any) -> list[Any]:
            out: list[Any] = []
            for part in _chunks(wanted):
                q = select(*(p.c[c] for c in PRICE_BAR_COLS)).where(
                    p.c.ticker.in_(part), p.c.date >= start, p.c.date <= end
                )
                out.extend(conn.execute(q).all())
            return out

        rows = self._read("가격(bars)", run)  # type: ignore[attr-defined]
        df = pd.DataFrame(rows, columns=list(PRICE_BAR_COLS))
        if len(df):
            df["date"] = pd.to_datetime(df["date"])
            for c in ("close", "adj_close", "volume"):
                df[c] = pd.to_numeric(df[c], errors="coerce").astype("float64")
            df = df.sort_values(["ticker", "date"]).reset_index(drop=True)
        return df

    def get_fx_range(self, start: date, end: date, pair: str = "USDKRW") -> list[FxRate]:
        """[start, end] 환율 (날짜 순)."""
        f = T.fx_daily
        q = (
            select(f.c.pair, f.c.date, f.c.rate, f.c.source, f.c.fetched_at)
            .where(f.c.pair == pair, f.c.date >= start, f.c.date <= end)
            .order_by(f.c.date)
        )
        return self._read("환율(범위)", lambda c: [FxRate(**r._asdict()) for r in c.execute(q)])  # type: ignore[attr-defined]

    def get_valuation_asof(
        self, asset_ids: Sequence[str], d: date, *, max_staleness_days: int = 10
    ) -> dict[str, dict[str, Any]]:
        """종목별 d 이하 가장 최근 valuation_daily 행 (d − max_staleness_days 보다 오래된 것은 제외).

        값은 종목 통화. 돌려주는 dict 키 = asset_id.
        """
        v = T.valuation_daily
        lo = d - timedelta(days=max_staleness_days)
        ids = sorted(set(asset_ids))

        def run(conn: Any) -> dict[str, dict[str, Any]]:
            out: dict[str, dict[str, Any]] = {}
            for part in _chunks(ids):
                sub = (
                    select(v.c.asset_id, func.max(v.c.date).label("d"))
                    .where(v.c.asset_id.in_(part), v.c.date <= d, v.c.date >= lo)
                    .group_by(v.c.asset_id)
                    .subquery()
                )
                q = select(*(v.c[c] for c in VALUATION_COLS)).join(
                    sub, (sub.c.asset_id == v.c.asset_id) & (sub.c.d == v.c.date)
                )
                for r in conn.execute(q):
                    row = dict(r._mapping)
                    for k, val in row.items():
                        if k not in ("asset_id", "ticker", "currency", "date", "fin_period_end", "fin_disclosed_at"):
                            row[k] = None if val is None else float(val)
                    out[row["asset_id"]] = row
            return out

        return self._read("가치평가(기준일)", run)  # type: ignore[attr-defined]

    def constituents_at(
        self, index: IndexCode | str, d: date
    ) -> tuple[date | None, list[IndexConstituent], list[str]]:
        """d 이하 가장 최근 스냅샷. 없으면 가장 오래된 스냅샷 + 경고 (K4 생존 편향). 스냅샷이 전혀 없으면 (None, [], [경고])."""
        code = IndexCode(index).value
        ic, a = T.index_constituent, T.assets

        def run(conn: Any) -> tuple[date | None, list[IndexConstituent], list[str]]:
            dates = sorted(
                conn.execute(select(ic.c.snapshot_date).where(ic.c.index_code == code).distinct()).scalars()
            )
            if not dates:
                return None, [], [f"{code}: 저장된 구성종목 스냅샷 없음"]
            before = [x for x in dates if x <= d]
            warnings: list[str] = []
            if before:
                snap = before[-1]
            else:
                snap = dates[0]
                warnings.append(f"{code}: {d} 이전 스냅샷이 없어 {snap} 스냅샷을 씀 (당시 구성종목 미확보, 생존 편향 가능)")
            q = (
                select(
                    ic.c.index_code,
                    func.coalesce(a.c.yfinance_symbol, ic.c.ticker).label("ticker"),
                    ic.c.name, ic.c.sector, ic.c.industry, ic.c.snapshot_date, ic.c.source, ic.c.fetched_at,
                    ic.c.gics_sub_industry_code,
                )
                .select_from(ic.outerjoin(a, a.c.asset_id == ic.c.asset_id))
                .where(ic.c.index_code == code, ic.c.snapshot_date == snap)
            )  # fmt: skip
            rows = sorted((IndexConstituent(**r._asdict()) for r in conn.execute(q)), key=lambda r: r.ticker)
            return snap, rows, warnings

        return self._read("구성종목(기준일)", run)  # type: ignore[attr-defined]

    def get_news_batch(
        self,
        asset_ids: Sequence[str],
        start: datetime,
        end: datetime,
        *,
        languages: Sequence[str] | None = None,
        per_asset: int | None = None,
    ) -> list[NewsRecord]:
        """여러 종목의 기사, 발행 시각 [start, end) 반개구간. 종목별 최신순, per_asset 개까지.

        인덱스 idx_news_asset_published 를 탄다. 제목이 같은 중복은 종목 안에서 하나만 남긴다.
        """
        n = T.news
        ids = sorted(set(asset_ids))
        fields = set(NewsRecord.model_fields)

        def run(conn: Any) -> list[NewsRecord]:
            out: list[NewsRecord] = []
            for part in _chunks(ids, 100):
                q = (
                    select(n)
                    .where(n.c.asset_id.in_(part), n.c.published_at >= start, n.c.published_at < end)
                    .order_by(n.c.asset_id, n.c.published_at.desc(), n.c.news_id)
                )
                if languages:
                    q = q.where(n.c.language.in_(list(languages)))
                seen: dict[str, set[str]] = defaultdict(set)
                count: dict[str, int] = defaultdict(int)
                for r in conn.execute(q):
                    row = r._asdict()
                    key = " ".join(str(row["title"]).lower().split())
                    if key in seen[row["asset_id"]]:
                        continue
                    if per_asset is not None and count[row["asset_id"]] >= per_asset:
                        continue
                    seen[row["asset_id"]].add(key)
                    count[row["asset_id"]] += 1
                    out.append(NewsRecord(**{k: v for k, v in row.items() if k in fields}))
            return out

        return self._read("뉴스(묶음)", run)  # type: ignore[attr-defined]

    def get_disclosures_batch(
        self,
        asset_ids: Sequence[str],
        start: date,
        end: date,
        *,
        event_types: Sequence[str] | None = None,
        per_asset: int | None = None,
        include_amendments: bool = False,
    ) -> list[DisclosureRecord]:
        """여러 종목의 공시, 이용 가능일(available_on) [start, end) 반개구간. 종목별로 사건 중요도 → 최신순, per_asset 개까지.

        수정 공시(is_amendment)는 기본 제외. 같은 (source, filing_id) 는 종목 안에서 한 번만. 인덱스 idx_disclosures_asset_available 사용.
        """
        d = T.disclosures
        ids = sorted(set(asset_ids))
        fields = set(DisclosureRecord.model_fields)
        types = list(event_types) if event_types else None

        def run(conn: Any) -> list[DisclosureRecord]:
            out: list[DisclosureRecord] = []
            for part in _chunks(ids, 100):
                q = select(d).where(d.c.asset_id.in_(part), d.c.available_on >= start, d.c.available_on < end)
                if not include_amendments:
                    q = q.where(d.c.is_amendment.is_(False))
                if types:
                    q = q.where(d.c.event_type.in_(types))
                q = q.order_by(d.c.asset_id, d.c.available_on.desc(), d.c.disclosure_id.desc())
                by_asset: dict[str, list[dict[str, Any]]] = defaultdict(list)
                seen: set[tuple[str, str, str]] = set()
                for r in conn.execute(q):
                    row = r._asdict()
                    key = (row["asset_id"], row["source"], row["filing_id"])
                    if key in seen:
                        continue
                    seen.add(key)
                    by_asset[row["asset_id"]].append(row)
                for aid in part:
                    rows = sorted(by_asset.get(aid, []), key=lambda x: (_EVENT_PRIORITY.get(x.get("event_type") or "", 9), -_ordinal(x["available_on"]), -int(x["disclosure_id"])))
                    if per_asset is not None:
                        rows = rows[:per_asset]
                    out.extend(DisclosureRecord(**{k: v for k, v in r.items() if k in fields}) for r in rows)
            return out

        return self._read("공시(묶음)", run)  # type: ignore[attr-defined]

    def list_reports(self, limit: int = 100) -> list[dict[str, Any]]:
        """report 메타(doc_json 제외): report_id, strategy_name, request_summary, as_of, created_at. 최신순."""
        rp = T.report
        cols = [c for c in ("report_id", "strategy_name", "request_summary", "as_of", "created_at") if c in rp.c]
        q = select(*(rp.c[c] for c in cols)).order_by(rp.c.created_at.desc()).limit(limit)
        return self._read("리포트 목록", lambda c: [dict(r._mapping) for r in c.execute(q)])  # type: ignore[attr-defined]

    def asset_map(self, symbols: Sequence[str] | None = None) -> dict[str, dict[str, Any]]:
        """yfinance 표기 → {asset_id, market, currency, asset_type, name}. symbols=None 이면 전부."""
        a = T.assets
        cols = (a.c.yfinance_symbol, a.c.asset_id, a.c.market, a.c.currency, a.c.asset_type, a.c.name, a.c.ticker)

        def run(conn: Any) -> dict[str, dict[str, Any]]:
            if symbols is None:
                rows = conn.execute(select(*cols)).all()
            else:
                rows = []
                for part in _chunks(sorted({normalize_ticker(s) for s in symbols})):
                    rows += conn.execute(select(*cols).where(a.c.yfinance_symbol.in_(part))).all()
            return {r.yfinance_symbol: dict(r._mapping) for r in rows}

        return self._read("종목 매핑", run)  # type: ignore[attr-defined]
