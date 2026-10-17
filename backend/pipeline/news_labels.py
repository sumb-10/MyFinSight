"""뉴스 사실 표시 (news 의 is_press_release · title_has_name · story_id · is_first_report · available_on).

전략과 상관없이 누가 봐도 같은 결과인 표시만 붙인다 (쓸모 판단·감성은 전략 쪽). 규칙이 바뀌면
RULE_VERSION 을 올리고 backend/scripts/label_news.py --all 로 다시 채운다.

- is_press_release: 회사 자체 발표. 언론사 이름이 보도자료 배포처(PR Newswire·Business Wire·
  GlobeNewswire·뉴스와이어 등)나 회사 뉴스룸("… Newsroom")이거나, 언론사가 회사 도메인
  (samsung.com 등)이거나, 주소가 그런 도메인.
- title_has_name: 제목에 종목 이름(법인 꼬리 Inc.·Corp.·(주) 등을 뗀 것)·검색어가 들어 있거나,
  미국 티커가 (AAPL)·$AAPL·NASDAQ:AAPL 꼴 또는 3글자 이상 대문자 단어로 들어 있음.
- story_id: 같은 종목·같은 날(시장 현지 날짜)·제목 앞부분(정규화 40글자)이 같은 기사 묶음.
  매체마다 제목을 조금씩 바꾸는 기사는 못 묶음 (전재·같은 보도자료 묶기 수준).
- is_first_report: 그 묶음에서 가장 먼저 발행된 기사 (DB 에서 계산, sql.py).
- available_on: 쓸 수 있는 첫 거래일. 평일이고 장 시작(KR 09:00, US 09:30 현지) 전이면 그날,
  아니면 다음 평일. 휴장일은 따로 보지 않음 (공시 available_on 과 같은 규칙).
  시각 없이 날짜만 오는 기사(Google RSS: 태평양 자정, FNSPID 일부: UTC 자정)는 그날 마지막 순간에
  나왔다고 보고 계산 (보수적, 선견 방지).
"""

from __future__ import annotations

import hashlib
import re
import unicodedata
from dataclasses import dataclass
from datetime import date, datetime, time, timedelta
from urllib.parse import urlparse
from zoneinfo import ZoneInfo

RULE_VERSION = "news-v1"
TZ = {"KR": ZoneInfo("Asia/Seoul"), "US": ZoneInfo("America/New_York")}
OPEN = {"KR": time(9, 0), "US": time(9, 30)}
STORY_CHARS = 40

PR_PUBLISHER = re.compile(
    r"newsroom|newswire|news wire|business ?wire|press release|accesswire|"
    r"뉴스와이어|보도자료",
    re.IGNORECASE,
)
PR_DOMAINS = (
    "prnewswire.com", "businesswire.com", "globenewswire.com", "accesswire.com",
    "newswire.co.kr", "newsfilecorp.com", "einpresswire.com",
)  # fmt: skip
PR_HOST = re.compile(r"^(newsroom|news|press|ir|investors?)\.", re.IGNORECASE)
LEGAL_SUFFIX = re.compile(
    r"[,.]?\s+(inc|incorporated|corp|corporation|company|co|ltd|limited|plc|holdings?|group|"
    r"n\.?v|s\.?a|ag|se|class [abc]|the)\.?$",
    re.IGNORECASE,
)
KR_SUFFIX = re.compile(r"\(주\)|㈜|주식회사|보통주|우선주")
COMMON_WORDS = {
    "american", "general", "united", "first", "national", "international", "global", "new",
    "southern", "northern", "western", "eastern", "public", "service", "digital", "capital",
}  # fmt: skip
KR_DOMAIN_ALIASES = {
    # 한국 종목 이름은 한글이라 회사 도메인(samsung.com)과 못 맞춤: 큰 종목만 도메인 이름표
    "005930": ("samsung",), "006400": ("samsungsdi",), "207940": ("samsungbiologics",),
    "028260": ("samsungcnt",), "009150": ("samsungsem",), "000660": ("skhynix",),
    "034730": ("sk",), "096770": ("skinnovation",), "017670": ("sktelecom",),
    "005380": ("hyundai",), "000270": ("kia",), "012330": ("mobis",), "373220": ("lgensol",),
    "051910": ("lgchem",), "066570": ("lge", "lgnewsroom"), "003550": ("lgcorp",),
    "005490": ("posco",), "035420": ("navercorp",), "035720": ("kakaocorp",),
    "068270": ("celltrion",), "105560": ("kbfg",), "055550": ("shinhangroup",),
}  # fmt: skip
KR_NAME_ALIASES = {
    # 기사 제목에 자주 쓰는 다른 이름 (영문 등록명·줄임말)
    "005930": ("삼전",), "035420": ("네이버",), "000660": ("하이닉스",), "005380": ("현대차",),
    "373220": ("엔솔",), "207940": ("삼바", "삼성바이오"), "005490": ("포스코",),
    "003550": ("lg",), "066570": ("lg전자",), "034730": ("sk(주)", "sk㈜"),
}  # fmt: skip
DATE_ONLY_TZ = {"GOOGLE_RSS": ZoneInfo("America/Los_Angeles")}
"""시각 없이 날짜만 주는 출처의 날짜 기준 (Google RSS 는 태평양 자정 = UTC 07:00·08:00 으로 옴)."""
BARE_DOMAIN = re.compile(r"^[a-z0-9-]+(\.[a-z0-9-]+)*\.(com|co\.kr|kr|net)$")
TICKER_WORDS = {
    "ALL", "ARE", "KEY", "NOW", "LOW", "CAT", "MAR", "MAS", "HAS", "HAL", "ICE", "LIN", "MET",
    "FAST", "COST", "CARR", "WELL", "TECH", "PEAK", "CEO", "CFO", "USA", "NYSE", "IPO", "ETF",
}  # fmt: skip


@dataclass(frozen=True)
class AssetNames:
    asset_id: str
    market: str  # US / KR
    ticker: str  # 시장 안 코드 (AAPL, 005930)
    name: str | None


def _host(url: str | None) -> str:
    try:
        return (urlparse(url or "").hostname or "").lower().removeprefix("www.")
    except ValueError:
        return ""


def _labels(host: str) -> list[str]:
    """도메인 앞부분 이름들 (news.samsung.com → [news, samsung])."""
    return host.split(".")[:-1]


def core_name(name: str | None) -> str:
    """법인 꼬리를 뗀 이름 (Apple Inc. → Apple, (주)삼성전자 → 삼성전자)."""
    s = KR_SUFFIX.sub("", name or "").strip()
    while True:
        t = LEGAL_SUFFIX.sub("", s).strip(" ,.")
        if t == s:
            return s
        s = t


def name_variants(a: AssetNames, query: str | None = None) -> list[str]:
    """제목에서 찾을 이름들 (소문자). 너무 짧거나 흔한 단어는 뺌."""
    out = set()
    core = core_name(a.name)
    for v in (core, core_name(query) if query and query.upper() != a.ticker.upper() else ""):
        if v and len(v) >= 2:
            out.add(v.lower())
    if a.market == "US" and core:
        first = core.split()[0].strip(",.").lower()
        if len(first) >= 5 and first not in COMMON_WORDS:
            out.add(first)
    out.update(KR_NAME_ALIASES.get(a.ticker, ()) if a.market == "KR" else ())
    return sorted(out)


def is_press_release(publisher: str | None, url: str | None, a: AssetNames | None = None) -> bool:
    pub = (publisher or "").strip()
    if pub and PR_PUBLISHER.search(pub):
        return True
    host = _host(url)
    if any(host == d or host.endswith("." + d) for d in PR_DOMAINS):
        return True
    if a is None:
        return False
    core = core_name(a.name).lower().replace(" ", "").replace(".", "")
    marks = list(KR_DOMAIN_ALIASES.get(a.ticker, ()))
    if core.isascii() and len(core) >= 3:
        marks.append(core)
    # 언론사 칸이 회사 도메인 (samsung.com) 이거나, 주소가 회사 뉴스룸·IR (news.samsung.com)
    if BARE_DOMAIN.match(pub.lower()) and any(m in _labels(pub.lower()) for m in marks):
        return True
    return bool(PR_HOST.match(host)) and any(m in _labels(host) for m in marks)


def title_has_name(title: str, a: AssetNames, query: str | None = None) -> bool:
    low = title.lower()
    if any(v in low for v in name_variants(a, query)):
        return True
    if a.market != "US":
        return a.ticker in title  # 6자리 코드
    t = re.escape(a.ticker.upper().replace("-", "."))
    if re.search(rf"(\(|\$|:\s?){t}\b", title):
        return True
    return len(a.ticker) >= 3 and a.ticker.upper() not in TICKER_WORDS and bool(
        re.search(rf"(?<![A-Za-z]){t}(?![A-Za-z])", title)
    )


def normalize_title(title: str, publisher: str | None = None) -> str:
    """묶음 비교용 제목: 끝의 " - 언론사" 떼고, [단독] 같은 머리표·말줄임 떼고, 글자·숫자만 소문자로."""
    s = unicodedata.normalize("NFKC", title)
    if publisher:
        for sep in (" - ", " | ", " : "):
            if s.endswith(sep + publisher):
                s = s[: -len(sep + publisher)]
    s = re.sub(r"\s[-|]\s[^-|]{1,40}$", "", s)  # 남은 " - 언론사" 꼬리
    s = re.sub(r"^\s*([\[【(<][^\]】)>]{1,12}[\]】)>]\s*)+", "", s)
    s = re.sub(r"(\.\.\.|…)\s*$", "", s)
    return "".join(ch for ch in s.lower() if ch.isalnum())


def local_date(published_at: datetime, market: str) -> date:
    return published_at.astimezone(TZ.get(market, TZ["US"])).date()


def date_only(published_at: datetime, source: str | None) -> ZoneInfo | None:
    """시각 없이 날짜만 있는 기사면 그 날짜의 기준 시간대 (아니면 None).
    Google RSS 는 태평양 자정(UTC 07:00·08:00:00), 다른 출처는 UTC 00:00:00 정각으로 옴."""
    utc = published_at.astimezone(ZoneInfo("UTC"))
    if utc.second or utc.microsecond or utc.minute:
        return None
    tz = DATE_ONLY_TZ.get(source or "")
    if tz is not None:
        return tz if published_at.astimezone(tz).time() == time(0, 0) else None
    return ZoneInfo("UTC") if utc.hour == 0 else None


def available_on(published_at: datetime, market: str, source: str | None = None) -> date:
    """쓸 수 있는 첫 거래일. 날짜만 있는 기사는 그날 마지막 순간에 나왔다고 보고 계산 (보수적)."""
    tz = date_only(published_at, source)
    if tz is not None:
        published_at = datetime.combine(published_at.astimezone(tz).date(), time(23, 59), tz)
    local = published_at.astimezone(TZ.get(market, TZ["US"]))
    d = local.date()
    if d.weekday() < 5 and local.time() < OPEN.get(market, OPEN["US"]):
        return d
    d += timedelta(days=1)
    while d.weekday() >= 5:
        d += timedelta(days=1)
    return d


def story_id(asset_id: str, title: str, publisher: str | None, published_at: datetime,
             market: str) -> str:  # fmt: skip
    key = normalize_title(title, publisher)[:STORY_CHARS] or title.strip().lower()
    raw = f"{asset_id}|{local_date(published_at, market).isoformat()}|{key}"
    return hashlib.sha1(raw.encode("utf-8")).hexdigest()[:24]


def labels(
    a: AssetNames,
    *,
    title: str,
    url: str | None,
    publisher: str | None,
    published_at: datetime,
    query: str | None = None,
    source: str | None = None,
) -> dict[str, object]:
    """한 기사의 표시 (is_first_report 는 묶음 전체를 봐야 해서 DB 에서)."""
    return {
        "is_press_release": is_press_release(publisher, url, a),
        "title_has_name": title_has_name(title, a, query),
        "story_id": story_id(a.asset_id, title, publisher, published_at, a.market),
        "available_on": available_on(published_at, a.market, source),
    }
