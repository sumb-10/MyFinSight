"""위키백과 지수 구성종목 표 크롤러 (M02-05 진짜 출처).

- S&P 500 : https://en.wikipedia.org/wiki/List_of_S%26P_500_companies
            표 id="constituents", 열 Symbol, Security, GICS Sector, GICS Sub-Industry, …
- Nasdaq-100: https://en.wikipedia.org/wiki/Nasdaq-100
            열 Ticker, Company, ICB Industry, ICB Subsector
            (GICS 가 아니라 ICB 분류라서 GICS 는 S&P 500 표에서 티커로 찾아 붙인다)
- 표 id 가 없거나 바뀌면 머리글 열 이름으로 표를 찾는다 (parse_table 의 needs)

API 키는 필요 없다. 표 해석은 표준 라이브러리 HTMLParser 로 한다 (lxml 등 추가 설치 없음).
"""

from __future__ import annotations

import re
from html.parser import HTMLParser
from typing import Any

from myfinsight.data.crawlers.common import http_session

SP500_URL = "https://en.wikipedia.org/wiki/List_of_S%26P_500_companies"
NDX_URL = "https://en.wikipedia.org/wiki/Nasdaq-100"
TABLE_ID = "constituents"

_FOOTNOTE = re.compile(r"\[[^\]]*\]")
_SPACE = re.compile(r"\s+")


class _Table:
    def __init__(self, table_id: str | None) -> None:
        self.id = table_id
        self.rows: list[list[str]] = []
        self.row: list[str] | None = None
        self.cell: list[str] | None = None


class _TableParser(HTMLParser):
    """문서의 모든 <table> 을 (id, 행 목록) 으로 모은다. 표 안의 표(감싸는 레이아웃 표 등)도 따로 모음."""

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.tables: list[_Table] = []
        self._stack: list[_Table] = []
        self._skip = 0  # <sup>(각주) 안

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag == "table":
            t = _Table(dict(attrs).get("id"))
            self.tables.append(t)
            self._stack.append(t)
            return
        if not self._stack:
            return
        t = self._stack[-1]
        if tag == "tr":
            t.row = []
        elif tag in ("td", "th") and t.row is not None:
            t.cell = []
        elif tag == "sup":
            self._skip += 1
        elif tag == "br" and t.cell is not None:
            t.cell.append(" ")

    def handle_endtag(self, tag: str) -> None:
        if not self._stack:
            return
        t = self._stack[-1]
        if tag == "table":
            self._stack.pop()
        elif tag == "sup" and self._skip:
            self._skip -= 1
        elif tag in ("td", "th") and t.cell is not None and t.row is not None:
            text = _FOOTNOTE.sub("", "".join(t.cell))
            t.row.append(_SPACE.sub(" ", text).strip())
            t.cell = None
        elif tag == "tr" and t.row is not None:
            if t.row:
                t.rows.append(t.row)
            t.row = None

    def handle_data(self, data: str) -> None:
        if self._stack and self._stack[-1].cell is not None and not self._skip:
            self._stack[-1].cell.append(data)


def _has_columns(header: list[str], needs: tuple[str, ...]) -> bool:
    cols = {h.strip().lower() for h in header}
    return all(n.lower() in cols for n in needs)


def parse_table(
    html: str, table_id: str = TABLE_ID, *, needs: tuple[str, ...] = ()
) -> list[dict[str, str]]:
    """id=table_id 표를 찾아 첫 행을 머리글로 dict 목록을 만든다.

    그 id 의 표가 없거나 비었으면, 머리글에 needs 열이 모두 있는 표 중 행이 가장 많은 표를 쓴다
    (위키백과가 표 id 를 바꾸거나 지우거나 다른 표로 감싸도 읽히게. 열 이름은 대소문자 무시).
    둘 다 없으면 빈 목록.
    """
    p = _TableParser()
    p.feed(html)
    p.close()
    rows = next((t.rows for t in p.tables if t.id == table_id and t.rows), None)
    if rows is None and needs:
        found = [t.rows for t in p.tables if t.rows and _has_columns(t.rows[0], needs)]
        rows = max(found, key=len, default=None)
    if not rows:
        return []
    header, *body = rows
    return [dict(zip(header, r, strict=False)) for r in body if len(r) >= len(header)]


def describe_tables(url: str, session: Any | None = None) -> list[str]:
    """페이지의 표 요약 (id, 행 수, 머리글). 표를 못 찾을 때 원인 확인용."""
    p = _TableParser()
    p.feed(_get(url, session))
    p.close()
    return [
        f"id={t.id or '-'} 행={len(t.rows)} 머리글={t.rows[0][:6] if t.rows else []}"
        for t in p.tables
        if len(t.rows) > 5
    ]


def _get(url: str, session: Any | None) -> str:
    s = session or http_session()
    r = s.get(url, timeout=30)
    r.raise_for_status()
    return r.text


def sp500_rows(session: Any | None = None) -> list[dict[str, str]]:
    """S&P 500 구성종목: [{"ticker", "name", "sector", "sub_industry"}]. 티커는 표 표기 그대로."""
    out = []
    for r in parse_table(_get(SP500_URL, session), needs=("Symbol", "GICS Sector")):
        out.append(
            {
                "ticker": r.get("Symbol", ""),
                "name": r.get("Security", ""),
                "sector": r.get("GICS Sector", ""),
                "sub_industry": r.get("GICS Sub-Industry", ""),
            }
        )
    return out


def ndx_rows(session: Any | None = None) -> list[dict[str, str]]:
    """Nasdaq-100 구성종목: [{"ticker", "name", "icb_industry", "icb_subsector"}]."""
    out = []
    for r in parse_table(_get(NDX_URL, session), needs=("Ticker", "Company")):
        out.append(
            {
                "ticker": r.get("Ticker", r.get("Symbol", "")),
                "name": r.get("Company", r.get("Security", "")),
                "icb_industry": r.get("ICB Industry", ""),
                "icb_subsector": r.get("ICB Subsector", ""),
            }
        )
    return out
