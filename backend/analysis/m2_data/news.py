"""근거 창 (M2-04). 구성일 d 직전의 DB 기사 [d − N일, d) (인용 ID `ev<news_id>`) + 공시 사건 [d − M일, d) (인용 ID `dc<disclosure_id>`).

- 라운드 4: 공시 사건이 뷰의 주 근거, 뉴스는 보조. 공시는 사건의 종류·시점만 알려 준다(본문 없음).
- 웹 검색 보충은 없다 (K3). 근거(뉴스 또는 공시)가 있는 종목이 min_tickers 미만이면 `enough=False` → 뷰를 만들지 않고 기준 비중 (K6).
- 기존 키(`window`, `n_articles`, `n_tickers_with_news`, `records`, `tickers`)는 그대로 둔다 (모의투자·리포트가 읽음).
"""

from __future__ import annotations

import datetime as dt
from collections.abc import Sequence
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from backend.analysis.m2_data.market_data import MarketData


@dataclass
class EvidenceWindow:
    as_of: dt.date
    start: dt.date
    end: dt.date  # 반개구간 끝 (= as_of)
    tickers: list[str]
    records: list[dict[str, Any]] = field(default_factory=list)  # 뉴스 (kind=news)
    by_ticker: dict[str, list[str]] = field(default_factory=dict)  # 뉴스 id
    min_tickers: int = 3
    disclosures: list[dict[str, Any]] = field(default_factory=list)  # 공시 (kind=disclosure)
    by_ticker_dc: dict[str, list[str]] = field(default_factory=dict)  # 공시 id
    dc_start: dt.date | None = None
    count_disclosures: bool = True  # 공시만 있는 종목도 "근거 있음" 으로 셈

    @property
    def n_articles(self) -> int:
        return len(self.records)

    @property
    def n_disclosures(self) -> int:
        return len(self.disclosures)

    @property
    def n_tickers_with_news(self) -> int:
        return sum(1 for t in self.tickers if self.by_ticker.get(t))

    @property
    def n_tickers_with_disclosures(self) -> int:
        return sum(1 for t in self.tickers if self.by_ticker_dc.get(t))

    @property
    def n_tickers_with_evidence(self) -> int:
        return sum(1 for t in self.tickers if self.has_evidence(t))

    def has_evidence(self, t: str) -> bool:
        return bool(self.by_ticker.get(t)) or (self.count_disclosures and bool(self.by_ticker_dc.get(t)))

    @property
    def enough(self) -> bool:
        n = self.n_tickers_with_evidence if self.count_disclosures else self.n_tickers_with_news
        return n >= self.min_tickers

    @property
    def ids(self) -> set[str]:
        return {r["evidence_id"] for r in self.records} | {r["evidence_id"] for r in self.disclosures}

    @property
    def all_records(self) -> list[dict[str, Any]]:
        return [*self.records, *self.disclosures]

    def summary(self) -> dict[str, Any]:
        return {
            "window": [str(self.start), str(self.end)],
            "disclosure_window": [str(self.dc_start), str(self.end)] if self.dc_start else None,
            "n_articles": self.n_articles,
            "n_disclosures": self.n_disclosures,
            "n_tickers_with_news": self.n_tickers_with_news,
            "n_tickers_with_disclosures": self.n_tickers_with_disclosures,
            "n_tickers_with_evidence": self.n_tickers_with_evidence,
            "n_tickers": len(self.tickers),
            "enough": self.enough,
            "by_language": _count(self.records, "language"),
            "by_source": _count(self.records, "source"),
            "by_event_type": _count(self.disclosures, "event_type"),
        }

    def prompt_lines(self, max_per_ticker: int | None = None) -> str:
        """LLM 뷰 프롬프트용: 종목별 헤드라인 목록 (근거 ID 포함)."""
        out = []
        for t in self.tickers:
            ids = self.by_ticker.get(t, [])[:max_per_ticker]
            if not ids:
                out.append(f"- {t}: (창 안 기사 없음)")
                continue
            out.append(f"- {t}:")
            for r in (x for x in self.records if x["evidence_id"] in set(ids)):
                out.append(f"  [{r['evidence_id']}] {r['published_at']} {r['publisher'] or r['source']}: {r['title']}")
        return "\n".join(out)

    def disclosure_lines(self, max_per_ticker: int | None = None) -> list[str]:
        """뷰 프롬프트의 공시 줄: `dc5 | 이용 가능일 | 출처(언어) | 양식·항목 | TICKER | 사건 종류 | 제목` (ticker 는 5번째 칸 — stub 파서와 약속)."""
        out = []
        for t in self.tickers:
            ids = set(self.by_ticker_dc.get(t, [])[:max_per_ticker])
            for r in self.disclosures:
                if r["evidence_id"] in ids:
                    out.append(f"{r['evidence_id']} | {r['available_on']} | {r['source']}({r.get('language', '')}) | {(r.get('form') or '')} {(r.get('items') or '')}".rstrip()
                               + f" | {t} | {r['event_label_ko']} | {r['title']}")
        return out

    def event_counts(self, t: str) -> dict[str, int]:
        """종목의 공시 사건 종류별 건수 (한국어 라벨)."""
        out: dict[str, int] = {}
        ids = set(self.by_ticker_dc.get(t, []))
        for r in self.disclosures:
            if r["evidence_id"] in ids:
                out[r["event_label_ko"]] = out.get(r["event_label_ko"], 0) + 1
        return out

    def to_dict(self) -> dict[str, Any]:
        return {**self.summary(), "as_of": str(self.as_of), "tickers": {t: self.by_ticker.get(t, []) for t in self.tickers},
                "tickers_dc": {t: self.by_ticker_dc.get(t, []) for t in self.tickers}, "records": self.records, "disclosures": self.disclosures}  # fmt: skip


def _count(records: list[dict[str, Any]], key: str) -> dict[str, int]:
    out: dict[str, int] = {}
    for r in records:
        k = str(r.get(key))
        out[k] = out.get(k, 0) + 1
    return out


def build_window(
    md: MarketData,
    tickers: Sequence[str],
    as_of: dt.date,
    *,
    days: int,
    per_ticker: int,
    languages: Sequence[str],
    min_tickers: int,
    dc_days: int = 0,
    dc_per_ticker: int = 8,
    dc_event_types: Sequence[str] | None = None,
    count_disclosures: bool = True,
    include_amendments: bool = False,
) -> EvidenceWindow:
    start = as_of - dt.timedelta(days=days)
    ids = {md.asset_id(t): t for t in tickers}
    rows = md.repo.get_news_batch(
        list(ids),
        dt.datetime(start.year, start.month, start.day, tzinfo=dt.UTC),
        dt.datetime(as_of.year, as_of.month, as_of.day, tzinfo=dt.UTC),
        languages=list(languages),
        per_asset=per_ticker,
    )
    win = EvidenceWindow(as_of=as_of, start=start, end=as_of, tickers=list(tickers), min_tickers=min_tickers, count_disclosures=count_disclosures)
    for r in rows:
        t = ids.get(r.asset_id)
        if t is None:
            continue
        rec = {
            "evidence_id": f"ev{r.news_id}",
            "kind": "news",
            "ticker": t,
            "asset_id": r.asset_id,
            "published_at": r.published_at.date().isoformat(),
            "published_at_utc": r.published_at.isoformat(),
            "source": r.source,
            "publisher": r.publisher or "",
            "title": r.title,
            "url": r.url,
            "language": r.language,
            "origin": "db",
        }
        win.records.append(rec)
        win.by_ticker.setdefault(t, []).append(rec["evidence_id"])
    if dc_days and dc_days > 0 and hasattr(md.repo, "get_disclosures_batch"):
        from backend.analysis.m2_data.disclosure_labels import display_title, label_ko

        win.dc_start = as_of - dt.timedelta(days=dc_days)
        drows = md.repo.get_disclosures_batch(list(ids), win.dc_start, as_of, event_types=dc_event_types, per_asset=dc_per_ticker, include_amendments=include_amendments)
        for r in drows:
            t = ids.get(r.asset_id)
            if t is None:
                continue
            base = {"source": r.source, "form": r.form, "items": r.items, "title": r.title, "event_type": r.event_type}
            rec = {
                "evidence_id": f"dc{r.disclosure_id}",
                "kind": "disclosure",
                "ticker": t,
                "asset_id": r.asset_id,
                "published_at": r.filed_at.date().isoformat(),  # 접수일 (날짜 열 호환)
                "filed_at": r.filed_at.date().isoformat(),
                "available_on": r.available_on.isoformat(),
                "source": r.source,
                "publisher": "SEC EDGAR" if r.source.upper().startswith("SEC") else "DART",
                "form": r.form,
                "items": r.items,
                "event_type": r.event_type,
                "event_label_ko": label_ko(r.event_type),
                "title": display_title(base),
                "url": r.url,
                "language": "en" if r.source.upper().startswith("SEC") else "ko",
                "origin": "db",
            }
            win.disclosures.append(rec)
            win.by_ticker_dc.setdefault(t, []).append(rec["evidence_id"])
    return win
