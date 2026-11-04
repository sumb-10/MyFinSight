"""근거 창 (M2-04). 구성일 d 직전의 DB 기사 [d − N일, d) (인용 ID `ev<news_id>`) + 공시 사건 [d − M일, d) (인용 ID `dc<disclosure_id>`).

- 라운드 4: 공시 사건이 뷰의 주 근거, 뉴스는 보조. 공시는 사건의 종류·시점만 알려 준다(본문 없음).
- 웹 검색 보충은 없다 (K3). 근거(뉴스 또는 공시)가 있는 종목이 min_tickers 미만이면 `enough=False` → 뷰를 만들지 않고 기준 비중 (K6).
- 기존 키(`window`, `n_articles`, `n_tickers_with_news`, `records`, `tickers`)는 그대로 둔다 (모의투자·리포트가 읽음).
- 시나리오 003: 블로그 등 이용자 글은 늘 빼고, 한국어 기사는 제목에 회사 이름이 있는 것만 (news.require_title_mention). 공시 날짜는 시장 현지 날짜.
"""

from __future__ import annotations

import datetime as dt
import re
from collections.abc import Sequence
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any
from zoneinfo import ZoneInfo

if TYPE_CHECKING:
    from backend.analysis.m2_data.market_data import MarketData

# 제목 검사용 잘 알려진 다른 이름 (6자리 코드 → 이름). pipeline/news_labels.KR_NAME_ALIASES(삼전·하이닉스·포스코 …)에 더한다.
# 제목에서 긴 사명을 줄여 쓰는 것(한화에어로·가스공사)도 여기에 둔다
KR_TITLE_ALIASES: dict[str, tuple[str, ...]] = {
    "035420": ("네이버", "NAVER"), "010120": ("LS ELECTRIC", "LS일렉트릭"), "005380": ("현대차", "현대자동차"), "015760": ("한국전력", "한전"),
    "055550": ("신한금융",), "010950": ("에쓰오일",), "012450": ("한화에어로",), "036460": ("가스공사",), "161390": ("한국타이어",),
    "034020": ("두산에너빌",), "047810": ("KAI",),
    # 검토에서 빠지던 흔한 제목 표기 (최근 60일 기준 빠진 행 수: SKT 814, DB손보 277, 포스코인터 184, SK이노 141, 카뱅 126 …)
    "017670": ("SKT",), "005830": ("DB손보",), "047050": ("포스코인터",), "096770": ("SK이노",), "323410": ("카뱅",), "064400": ("LG CNS",),
    "361610": ("SKIET",), "018260": ("삼성SDS",), "081660": ("휠라",), "036570": ("엔씨소프트", "엔씨"), "137310": ("SD바이오센서",),
    "112610": ("CS윈드",), "011780": ("금호석유",),
}  # fmt: skip
_GROUP_PREFIX = re.compile(r"^(HD|SK|LG|LS|CJ|GS)(?![A-Za-z])\s*")  # HDC·SKC 처럼 이어지는 영문은 그룹 접두어가 아님
_HOLDING_SUFFIX = re.compile(r"\s*(지주|홀딩스)$")  # 하나금융지주 → 하나금융, POSCO홀딩스 → POSCO
_FILING_TZ = {"SEC": ZoneInfo("America/New_York"), "DART": ZoneInfo("Asia/Seoul")}


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


def title_aliases(md: MarketData, tickers: Sequence[str]) -> dict[str, list[str]]:
    """한국 종목의 제목 검사용 이름 (asset_id → 이름들): 종목명, 6자리 코드, 그룹 접두어(HD·SK·LG·LS·CJ·GS)나
    지주·홀딩스 꼬리를 뗀 이름(3글자 이상), 잘 알려진 별칭. DB 종목 마스터에는 한국 종목의 영문명이 따로 없어 별칭 표로 채운다.
    이름을 모르는 종목·미국 종목은 넣지 않는다 (= 검사하지 않음)."""
    from backend.pipeline.news_labels import KR_NAME_ALIASES, core_name

    out: dict[str, list[str]] = {}
    for t in tickers:
        a = md.assets.get(t) or {}
        name = core_name(a.get("name"))
        if not name or md.market_of(t) != "KR":
            continue
        code = str(a.get("ticker") or t.split(".")[0])
        names = [name, code, *KR_TITLE_ALIASES.get(code, ()), *KR_NAME_ALIASES.get(code, ())]
        names += [s for s in (_GROUP_PREFIX.sub("", name), _HOLDING_SUFFIX.sub("", name)) if s != name and len(s) >= 3]
        out[a.get("asset_id") or md.asset_id(t)] = list(dict.fromkeys(names))
    return out


def _filed_date(ts: dt.datetime, source: str) -> dt.date:
    """접수일 = 공시한 시장의 현지 날짜. DB 의 filed_at 은 UTC 라 그대로 .date() 하면 DART(그날 0시 KST = 전날 15시 UTC)가
    하루 이르게 보인다 (rcpNo 20260821… 이 2026-08-20). tz 없는 값은 그대로 둔다."""
    if ts.tzinfo is None:
        return ts.date()
    return ts.astimezone(_FILING_TZ["SEC" if source.upper().startswith("SEC") else "DART"]).date()


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
        aliases=title_aliases(md, tickers) if md.s.news.require_title_mention else None,  # 한국어 기사 제목 검사 (시나리오 003)
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
        from backend.analysis.m2_data.disclosure_labels import display_title, event_type_of, label_ko

        win.dc_start = as_of - dt.timedelta(days=dc_days)
        # 넉넉히 받아 고친 종류로 거른 뒤 종목별로 자른다 (예전 규칙으로 '상장폐지 통지' 로 저장된 매매거래 정지가 자리를 차지했다가 빠져 8건이 안 되던 문제, 검토)
        drows = md.repo.get_disclosures_batch(list(ids), win.dc_start, as_of, event_types=dc_event_types, per_asset=dc_per_ticker + 4 if dc_per_ticker else None,
                                              include_amendments=include_amendments)  # fmt: skip
        allowed = set(dc_event_types) if dc_event_types else None
        dc_count: dict[str, int] = {}
        for r in drows:
            t = ids.get(r.asset_id)
            if t is None:
                continue
            base = {"source": r.source, "form": r.form, "items": r.items, "title": r.title, "event_type": r.event_type}
            et = base["event_type"] = event_type_of(base)  # 예전 규칙으로 '상장폐지 통지' 로 저장된 매매거래 정지를 고침
            if allowed is not None and et not in allowed:
                continue  # 고친 종류가 허용 목록 밖 (trading_halt: 절차상 정지라 뷰·요약 근거가 아님 — 새 규칙으로 저장된 행과 같게)
            if dc_per_ticker and dc_count.get(t, 0) >= dc_per_ticker:
                continue
            dc_count[t] = dc_count.get(t, 0) + 1
            filed = _filed_date(r.filed_at, r.source).isoformat()
            rec = {
                "evidence_id": f"dc{r.disclosure_id}",
                "kind": "disclosure",
                "ticker": t,
                "asset_id": r.asset_id,
                "published_at": filed,  # 접수일 (날짜 열 호환)
                "filed_at": filed,  # 공시한 시장의 현지 날짜 (DART 서울, SEC 뉴욕)
                "available_on": r.available_on.isoformat(),
                "source": r.source,
                "publisher": "SEC EDGAR" if r.source.upper().startswith("SEC") else "DART",
                "form": r.form,
                "items": r.items,
                "event_type": et,
                "event_label_ko": label_ko(et),
                "title": display_title(base),
                "url": r.url,
                "language": "en" if r.source.upper().startswith("SEC") else "ko",
                "origin": "db",
            }
            win.disclosures.append(rec)
            win.by_ticker_dc.setdefault(t, []).append(rec["evidence_id"])
    return win
