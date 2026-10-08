"""크롤러 공용 도우미 (원본 app.collectors.base 중 크롤러가 쓰던 함수를 다시 만든 것)."""

from __future__ import annotations

import html
import re
from datetime import UTC, date, datetime
from email.utils import parsedate_to_datetime
from typing import Any

import requests

USER_AGENT = "MyFinSight/0.1 (+role-a crawler)"


def http_session() -> requests.Session:
    """공용 HTTP 세션. 재시도는 어댑터(RetryingFetcher)가 하므로 여기선 하지 않는다."""
    s = requests.Session()
    s.headers.update({"User-Agent": USER_AGENT})
    return s


def num(v: Any) -> float | None:
    """'1,234' · '-' · '' · None 같은 값을 숫자로. 못 바꾸면 None."""
    if v is None:
        return None
    if isinstance(v, (int, float)):
        return float(v)
    s = str(v).replace(",", "").strip()
    if s in ("", "-", "N/A", "None"):
        return None
    try:
        return float(s)
    except ValueError:
        return None


def to_date(v: Any) -> date | None:
    """date·datetime·'20260930'·'2026-09-30'·'2026-09-30T…' → date."""
    if v is None or v == "":
        return None
    if isinstance(v, datetime):
        return v.date()
    if isinstance(v, date):
        return v
    s = str(v).strip()
    if re.fullmatch(r"\d{8}", s):
        return date(int(s[:4]), int(s[4:6]), int(s[6:8]))
    return date.fromisoformat(s[:10])


def rfc822(v: str | None) -> datetime | None:
    """RSS 날짜('Tue, 29 Sep 2026 08:00:00 +0900') → UTC datetime. 실패하면 None."""
    if not v:
        return None
    try:
        dt = parsedate_to_datetime(v)
    except (TypeError, ValueError):
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=UTC)
    return dt.astimezone(UTC)


_TAG = re.compile(r"<[^>]+>")


def strip_html(v: str | None) -> str | None:
    """HTML 태그 제거 + &amp; 같은 엔티티 해제."""
    if v is None:
        return None
    return html.unescape(_TAG.sub("", v)).strip()
