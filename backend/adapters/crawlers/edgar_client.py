"""[정량·해외 보정] SEC EDGAR XBRL companyfacts (https://data.sec.gov/api/xbrl/companyfacts/CIK##########.json).

키는 없지만 SEC 정책상 "이름 이메일" 형식의 User-Agent가 필수이고, 초당 10회 이하로 호출해야 한다.

만드는 행 (값은 모두 '가장 먼저 제출된 값' = 처음 공시된 값, disclosed_at = 그 보고서의 filed 날짜.
같은 기간 값이 이후 보고서에 비교수치·정정값으로 다시 나와도 처음 값을 쓴다: 공시 시점 기준, 선견 없음)
1) 연간 주요 계정 (period="FY2025", report_code="10-K"): 매출액·영업이익·당기순이익·EPS(희석)·
   주당배당금 (1년 기간), 자산총계·부채총계·자본총계 (회계연도 말)
2) 분기 (period="Q2025-03-29", 기간 끝 날짜): 흐름 항목은 진짜 3개월 값
   (매출액(분기)·영업이익(분기)·당기순이익(분기)·EPS(희석·분기)·주당배당금(분기))
   - 10-Q 의 3개월 기간 값이 있으면 그대로
   - 없으면 같은 시작일의 누적값 차이 (6개월 − 3개월, 9개월 − 6개월, 연간 − 9개월 = 4분기)
   - 9개월 누적도 없으면 4분기 = 연간 − (1·2·3분기 합)
   - disclosed_at = 쓴 값들의 제출일 중 가장 늦은 날 (4분기는 보통 10-K 제출일)
   재무상태 항목(자산총계·부채총계·자본총계)은 분기말 값 그대로
3) 유통주식수 (period="S2025-04-20"): dei:EntityCommonStockSharesOutstanding (표지 기준일),
   없으면 us-gaap CommonStockSharesOutstanding (분기말). 둘을 섞지 않음 (종류주식 회사는 dei 가
   빠지는 일이 있어 합계가 다르게 나올 수 있음).
   둘 다 없거나 마지막 값이 오래됐으면 (종류주식 회사: companyfacts 는 주식 종류별로 나눈 값을
   안 줌. 예전 값만 남는 일이 있음) 가중평균 주식수
   (희석, 없으면 기본)를 기간 끝 날짜 기준으로 씀 (report_code="WADS", 기간 중 평균이라 근사값).
   가중평균이 다른 종류주식 환산인 회사는 CLASS_SHARE_RATIO 로 맞춤 (BRK-B: A주 1주 = B주 1500주)
4) 지표 계산용 최신 입력값 스냅샷 (report_code="SNAPSHOT", period=오늘)
   EPS(TTM), 순이익(TTM), 자본총계(최근), 발행주식수, BPS

US GAAP 을 달러가 아닌 통화로 낸 회사 (ASML: EUR)는 그 통화를 그대로 읽고 unit 에 적는다.
IFRS 로 신고하는 외국 기업 (20-F·40-F: CCEP 등)은 us-gaap 이 없고 ifrs-full 만 있다.
us-gaap 순이익 개념이 없으면 IFRS_TO_US_GAAP 로 개념 이름을 바꿔 같은 방법으로 읽고, 금액 단위는
보고 통화 그대로 둔다 (unit=EUR 등. 달러로 바꾸지 않음)
"""

import json
import time
from collections import defaultdict
from datetime import date, timedelta

from backend.adapters.crawlers import config
from backend.adapters.crawlers.common import http_session, to_date

SOURCE = "SEC_EDGAR"
_session = http_session()

REVENUE = [
    "RevenueFromContractWithCustomerExcludingAssessedTax",
    "Revenues",
    "SalesRevenueNet",
    "RevenueFromContractWithCustomerIncludingAssessedTax",
]
EQUITY = [
    "StockholdersEquity",
    "StockholdersEquityIncludingPortionAttributableToNoncontrollingInterest",
]
# (표시 이름, 후보 개념들, 단위, 흐름(기간)값 여부)
ANNUAL_METRICS = [
    ("매출액", REVENUE, "USD", True),
    ("영업이익", ["OperatingIncomeLoss"], "USD", True),
    ("당기순이익", ["NetIncomeLoss", "ProfitLoss"], "USD", True),
    ("자산총계", ["Assets"], "USD", False),
    ("부채총계", ["Liabilities"], "USD", False),
    ("자본총계", EQUITY, "USD", False),
    ("EPS(희석)", ["EarningsPerShareDiluted", "EarningsPerShareBasic"], "USD/shares", True),
]
ANNUAL_FORMS = ("10-K", "10-K/A", "20-F", "40-F")
QUARTER_FORMS = ("10-Q", "10-Q/A")
PERIODIC_FORMS = (
    *ANNUAL_FORMS, "10-KT", "10-KT/A", "20-F/A", "40-F/A", *QUARTER_FORMS,
)  # fmt: skip
"""분기·연간 값으로 쓰는 보고서 (등록신고서 S-1 등의 과거 수치는 쓰지 않음)."""
DPS = ["CommonStockDividendsPerShareDeclared", "CommonStockDividendsPerShareCashPaid"]
# (연간 이름, 분기 이름, 후보 개념들(앞이 우선), 단위)
FLOW_METRICS = [
    ("매출액", "매출액(분기)", REVENUE, "USD"),
    ("영업이익", "영업이익(분기)", ["OperatingIncomeLoss"], "USD"),
    ("당기순이익", "당기순이익(분기)", ["NetIncomeLoss", "ProfitLoss"], "USD"),
    (
        "EPS(희석)",
        "EPS(희석·분기)",
        ["EarningsPerShareDiluted", "EarningsPerShareBasic"],
        "USD/shares",
    ),
    ("주당배당금", "주당배당금(분기)", DPS, "USD/shares"),
]
INSTANT_METRICS = [
    ("자산총계", ["Assets"], "USD"),
    ("부채총계", ["Liabilities"], "USD"),
    ("자본총계", EQUITY, "USD"),
]
QUARTER_DAYS = (80, 100)  # 3개월 기간 (52·53주 회계연도의 14주 분기 98일 포함)
YEAR_DAYS = (340, 380)
WEIGHTED_SHARES = [
    "WeightedAverageNumberOfDilutedSharesOutstanding",
    "WeightedAverageNumberOfSharesOutstandingBasic",
]
"""유통주식수가 없을 때 쓰는 가중평균 주식수 (앞이 우선)."""
SHARES_STALE_DAYS = 550
"""주식수 출처의 마지막 값이 다른 출처보다 이만큼 넘게 오래되면 다음 출처를 씀."""
CLASS_SHARE_RATIO = {"BRK-B": 1500.0}
"""가중평균 주식수가 다른 종류주식 기준인 티커: 그 값 × 비율 = 이 티커 기준 주식 수."""
IFRS_TO_US_GAAP = {
    # ifrs-full 개념 → 같은 뜻의 us-gaap 개념 (앞이 우선: 같은 us-gaap 이름이면 먼저 나온 것)
    "Revenue": "Revenues",
    "RevenueFromContractsWithCustomers": "RevenueFromContractWithCustomerExcludingAssessedTax",
    "ProfitLossFromOperatingActivities": "OperatingIncomeLoss",
    "ProfitLossAttributableToOwnersOfParent": "NetIncomeLoss",
    "ProfitLoss": "ProfitLoss",
    "Assets": "Assets",
    "Liabilities": "Liabilities",
    "EquityAttributableToOwnersOfParent": "StockholdersEquity",
    "Equity": "StockholdersEquityIncludingPortionAttributableToNoncontrollingInterest",
    "DilutedEarningsPerShare": "EarningsPerShareDiluted",
    "BasicEarningsPerShare": "EarningsPerShareBasic",
    "DividendsRecognisedAsDistributionsToOwnersPerShare": "CommonStockDividendsPerShareDeclared",
    "AdjustedWeightedAverageShares": "WeightedAverageNumberOfDilutedSharesOutstanding",
    "WeightedAverageShares": "WeightedAverageNumberOfSharesOutstandingBasic",
}


def ticker_cache():
    return config.CACHE_DIR / "sec_company_tickers.json"


def _headers() -> dict:
    config.require(SEC_USER_AGENT=config.SEC_USER_AGENT)
    return {"User-Agent": config.SEC_USER_AGENT, "Accept-Encoding": "gzip, deflate"}


def load_ticker_map() -> dict:
    """{ticker: {"cik": int, "title": str}} — 7일간 캐시"""
    if ticker_cache().exists():
        data = json.loads(ticker_cache().read_text(encoding="utf-8"))
        if date.fromisoformat(data["saved"]) > date.today() - timedelta(days=7):
            return data["map"]
    res = _session.get(
        "https://www.sec.gov/files/company_tickers.json", headers=_headers(), timeout=30
    )
    if not res.ok:
        raise RuntimeError(
            f"SEC 티커 목록 오류 status={res.status_code} (SEC_USER_AGENT 형식 확인)"
        )
    mp = {
        v["ticker"].upper(): {"cik": int(v["cik_str"]), "title": v["title"]}
        for v in res.json().values()
    }
    ticker_cache().write_text(
        json.dumps({"saved": date.today().isoformat(), "map": mp}), encoding="utf-8"
    )
    return mp


def resolve_cik(key: str) -> int:
    """숫자면 CIK 그대로, 아니면 티커로 보고 SEC 티커 목록에서 찾는다."""
    if key.isdigit():
        return int(key)
    mp = load_ticker_map()
    info = mp.get(key.upper().replace(".", "-")) or mp.get(key.upper())
    if not info:
        raise RuntimeError(f"SEC 티커 목록에 {key}가 없음 (ETF·외국기업 등)")
    return info["cik"]


def fetch_company_facts(cik: int) -> dict:
    res = _session.get(
        f"https://data.sec.gov/api/xbrl/companyfacts/CIK{cik:010d}.json",
        headers=_headers(),
        timeout=60,
    )
    if not res.ok:
        raise RuntimeError(f"SEC companyfacts 오류 status={res.status_code}")
    return res.json()


SUBMISSIONS = "https://data.sec.gov/submissions"
FILING_FIELDS = ("accessionNumber", "filingDate", "acceptanceDateTime", "form", "items",
                 "primaryDocument", "primaryDocDescription")  # fmt: skip
_last_sub = 0.0


def _get_json(url: str) -> dict:
    """SEC 요청 (초당 10건 한도 안: 0.15초 간격)."""
    global _last_sub
    gap = 0.15 - (time.monotonic() - _last_sub)
    if gap > 0:
        time.sleep(gap)
    _last_sub = time.monotonic()
    res = _session.get(url, headers=_headers(), timeout=60)
    if not res.ok:
        raise RuntimeError(f"SEC submissions 오류 status={res.status_code} ({url.rsplit('/', 1)[-1]})")
    return res.json()


def _columns(block: dict) -> list[dict]:
    """submissions 의 열 모양(필드마다 목록) → 공시마다 dict."""
    n = len(block.get("accessionNumber") or [])
    return [{f: (block.get(f) or [None] * n)[i] for f in FILING_FIELDS} for i in range(n)]


def fetch_filings(cik: int, since: date | None = None) -> list[dict]:
    """회사의 공시 목록 (submissions API): 최근 묶음 + 예전 쪽 파일들. since 를 주면 그 날 이후만
    (예전 쪽 파일은 그보다 오래된 것만 담고 있으면 받지 않음). 항목은 FILING_FIELDS.

    acceptanceDateTime 은 끝에 Z 가 붙어 있지만 실제로는 미국 동부 시각이다 (EDGAR 관례)."""
    data = _get_json(f"{SUBMISSIONS}/CIK{cik:010d}.json")
    filings = data.get("filings") or {}
    out = _columns(filings.get("recent") or {})
    for f in filings.get("files") or []:
        if since is not None and f.get("filingTo") and f["filingTo"] < since.isoformat():
            continue
        out += _columns(_get_json(f"{SUBMISSIONS}/{f['name']}"))
    if since is not None:
        out = [r for r in out if (r["filingDate"] or "") >= since.isoformat()]
    return out


# ---------------- companyfacts 해석 ----------------
def _entries(facts: dict, concept: str, unit: str, taxonomy: str = "us-gaap") -> list[dict]:
    return facts.get("facts", {}).get(taxonomy, {}).get(concept, {}).get("units", {}).get(unit, [])


def _days(e: dict) -> int | None:
    return (to_date(e["end"]) - to_date(e["start"])).days if e.get("start") else None


def _pick(entries: list[dict], prefer: str) -> dict:
    return sorted(entries, key=lambda e: e["filed"], reverse=(prefer == "latest"))[0]


def annual_values(
    facts: dict, concept: str, unit: str, flow: bool, prefer: str = "earliest"
) -> dict[str, dict]:
    """{기말일: entry} — 연간 보고서 기준. flow면 기간이 1년인 값만."""
    groups: dict[str, list] = {}
    for e in _entries(facts, concept, unit):
        if e.get("form") not in ANNUAL_FORMS:
            continue
        if flow and not (340 <= (_days(e) or 0) <= 380):
            continue
        if not flow and e.get("start"):
            continue
        groups.setdefault(e["end"], []).append(e)
    return {end: _pick(es, prefer) for end, es in groups.items()}


def first_concept(facts: dict, candidates: list[str], unit: str, flow: bool) -> str | None:
    """후보 중 가장 최근 연도 값이 있는 개념."""
    best, best_end = None, ""
    for c in candidates:
        vals = annual_values(facts, c, unit, flow)
        if vals and max(vals) > best_end:
            best, best_end = c, max(vals)
    return best


def ttm_value(facts: dict, concept: str, unit: str) -> tuple[float, str, str] | None:
    """최근 12개월 값 = 최근 연간 + 이후 누적분기 − 전년 같은 누적분기. (값, 기준일, 최신 제출일)"""
    annual = annual_values(facts, concept, unit, True, prefer="latest")
    if not annual:
        return None
    fy = annual[max(annual)]
    ytd = [
        e
        for e in _entries(facts, concept, unit)
        if e.get("form") in QUARTER_FORMS and 60 <= (_days(e) or 0) <= 300 and e["end"] > fy["end"]
    ]
    if ytd:
        cur = _pick([e for e in ytd if e["end"] == max(x["end"] for x in ytd)], "latest")
        target = to_date(cur["end"]) - timedelta(days=365)
        prior = [
            e
            for e in _entries(facts, concept, unit)
            if e.get("start")
            and abs((to_date(e["end"]) - target).days) <= 15
            and abs((_days(e) or 0) - _days(cur)) <= 15
        ]
        if prior:
            p = _pick(prior, "latest")
            return fy["val"] + cur["val"] - p["val"], cur["end"], max(cur["filed"], fy["filed"])
    return fy["val"], fy["end"], fy["filed"]


def latest_instant(
    facts: dict, concepts: list[str], unit: str, taxonomy: str = "us-gaap"
) -> tuple[float, str, str] | None:
    cands = [e for c in concepts for e in _entries(facts, c, unit, taxonomy) if not e.get("start")]
    if not cands:
        return None
    last_end = max(e["end"] for e in cands)
    e = _pick([x for x in cands if x["end"] == last_end], "latest")
    return e["val"], e["end"], e["filed"]


# ---------------- 분기 값 만들기 (처음 공시된 값 기준) ----------------
def _first_filed(entries: list[dict]) -> dict:
    """같은 기간 값 중 가장 먼저 제출된 것 (같은 날이면 정정(/A)이 아닌 것, 접수번호 순)."""
    return min(
        entries,
        key=lambda e: (e["filed"], str(e.get("form", "")).endswith("/A"), str(e.get("accn"))),
    )


def first_filed_durations(facts: dict, concept: str, unit: str) -> dict[tuple[str, str], dict]:
    """{(시작일, 끝날): entry} 정기보고서의 기간 값, 기간마다 처음 제출된 값."""
    groups: dict[tuple[str, str], list[dict]] = defaultdict(list)
    for e in _entries(facts, concept, unit):
        if e.get("start") and e.get("form") in PERIODIC_FORMS and e.get("val") is not None:
            groups[(e["start"], e["end"])].append(e)
    return {k: _first_filed(v) for k, v in groups.items()}


def first_filed_instants(
    facts: dict, concept: str, unit: str, taxonomy: str = "us-gaap", forms=PERIODIC_FORMS
) -> dict[str, dict]:
    """{기준일: entry} 시점 값, 기준일마다 처음 제출된 값."""
    groups: dict[str, list[dict]] = defaultdict(list)
    for e in _entries(facts, concept, unit, taxonomy):
        if not e.get("start") and e.get("form") in forms and e.get("val") is not None:
            groups[e["end"]].append(e)
    return {k: _first_filed(v) for k, v in groups.items()}


def _span(a: str, b: str) -> int:
    return (to_date(b) - to_date(a)).days


def _in(days: int, bounds: tuple[int, int]) -> bool:
    return bounds[0] <= days <= bounds[1]


def quarter_values(durations: dict[tuple[str, str], dict]) -> dict[str, dict]:
    """기간 값들 → {분기 끝날: {"val", "filed", "accn", "how", "form"}} (3개월 값).

    how: 3M (3개월 값 그대로), YTD (같은 시작일 누적값의 차이, 연간 − 9개월 = 4분기 포함),
    FY-3Q (연간 − 세 분기 합). 3M 이 있으면 그것을 쓴다.
    """
    out: dict[str, dict] = {}

    def put(end: str, val: float, parts: list[dict], how: str) -> None:
        last = max(parts, key=lambda e: e["filed"])
        out[end] = {
            "val": val,
            "filed": last["filed"],
            "accn": last.get("accn"),
            "form": last.get("form"),
            "how": how,
        }

    for (s, e), x in durations.items():
        if _in(_span(s, e), QUARTER_DAYS):
            put(e, x["val"], [x], "3M")
    by_start: dict[str, list[tuple[str, dict]]] = defaultdict(list)
    for (s, e), x in durations.items():
        if _span(s, e) <= YEAR_DAYS[1]:
            by_start[s].append((e, x))
    for _s, chain in by_start.items():
        chain.sort(key=lambda t: t[0])
        for (e0, x0), (e1, x1) in zip(chain, chain[1:], strict=False):
            if e1 not in out and _in(_span(e0, e1), QUARTER_DAYS):
                put(e1, x1["val"] - x0["val"], [x0, x1], "YTD")
    # 연간 − 세 분기 (9개월 누적 없이 분기 값만 낸 회사)
    for (s, e), x in durations.items():
        if e in out or not _in(_span(s, e), YEAR_DAYS):
            continue
        ends = sorted(q for q in out if s < q < e)
        if len(ends) < 3:
            continue
        q1, q2, q3 = ends[-3:]
        if (
            _in(_span(s, q1), QUARTER_DAYS)
            and _in(_span(q1, q2), QUARTER_DAYS)
            and _in(_span(q2, q3), QUARTER_DAYS)
            and _in(_span(q3, e), QUARTER_DAYS)
        ):
            parts = [out[q1], out[q2], out[q3]]
            put(e, x["val"] - sum(p["val"] for p in parts), [*parts, x], "FY-3Q")
    return out


def annual_flow_values(durations: dict[tuple[str, str], dict]) -> dict[str, dict]:
    """{회계연도 끝날: entry} 1년 기간 값 (처음 제출된 값)."""
    out: dict[str, dict] = {}
    for (s, e), x in durations.items():
        if _in(_span(s, e), YEAR_DAYS) and (e not in out or x["filed"] < out[e]["filed"]):
            out[e] = x
    return out


def _merge(candidates: list[str], make) -> dict:  # noqa: ANN001
    """후보 개념마다 값을 만들고, 기간마다 앞 순위 개념의 값을 쓴다 (개념을 바꾼 회사 대비)."""
    out: dict = {}
    for c in candidates:
        for k, v in make(c).items():
            out.setdefault(k, {**v, "concept": c})
    return out


def _unit_name(unit: str) -> str:
    return "USD" if unit == "USD/shares" else unit


def as_us_gaap(facts: dict) -> tuple[dict, str]:
    """IFRS 신고 회사면 ifrs-full 을 us-gaap 이름으로 바꾼 facts 와 보고 통화, 아니면 (facts, "USD").

    금액은 통화 단위(EUR 등)를 "USD" 키로, 주당 값은 "EUR/shares" 를 "USD/shares" 키로 옮긴다
    (계산 코드를 그대로 쓰려고. 값은 바꾸지 않고, 행의 unit 은 build_rows 가 실제 통화로 적음)."""
    gaap = facts.get("facts", {}).get("us-gaap", {})
    ifrs = facts.get("facts", {}).get("ifrs-full", {})
    if any(c in gaap for c in ("NetIncomeLoss", "ProfitLoss")):
        return _gaap_currency(facts, gaap)
    if not ifrs:
        return facts, "USD"
    currency = "USD"
    for c in ("ProfitLossAttributableToOwnersOfParent", "ProfitLoss", "Revenue", "Assets"):
        units = [u for u in ifrs.get(c, {}).get("units", {}) if "/" not in u]
        if units:
            currency = max(units, key=lambda u: max(e["end"] for e in ifrs[c]["units"][u]))
            break
    mapped: dict[str, dict] = {}
    for src, dst in IFRS_TO_US_GAAP.items():
        units = ifrs.get(src, {}).get("units", {})
        out = {}
        if currency in units:
            out["USD"] = units[currency]
        if f"{currency}/shares" in units:
            out["USD/shares"] = units[f"{currency}/shares"]
        if "shares" in units:
            out["shares"] = units["shares"]
        if out and dst not in mapped:
            mapped[dst] = {"units": out}
    return {**facts, "facts": {**facts.get("facts", {}), "us-gaap": mapped}}, currency


def _gaap_currency(facts: dict, gaap: dict) -> tuple[dict, str]:
    """us-gaap 을 달러가 아닌 통화로 낸 회사 (예: ASML 은 US GAAP·EUR): 그 통화를 "USD" 키로 옮김."""
    for c in ("NetIncomeLoss", "ProfitLoss", "StockholdersEquity"):
        units = gaap.get(c, {}).get("units", {})
        money = [u for u in units if "/" not in u]
        if "USD" in money:
            return facts, "USD"
        if money:
            currency = max(money, key=lambda u: max(e["end"] for e in units[u]))
            break
    else:
        return facts, "USD"
    rename = {currency: "USD", f"{currency}/shares": "USD/shares"}
    mapped = {}
    for name, body in gaap.items():
        units = {}
        for u, es in body.get("units", {}).items():
            if u in rename:
                units[rename[u]] = es
            elif u not in ("USD", "USD/shares"):  # 보고 통화가 아닌 달러 값은 섞지 않음
                units[u] = es
        mapped[name] = {**body, "units": units}
    return {**facts, "facts": {**facts.get("facts", {}), "us-gaap": mapped}}, currency


def pick_shares(facts: dict, ratio: float = 1.0) -> tuple[dict[str, dict], str]:
    """유통주식수 이력과 출처 코드. dei → us-gaap 시점값 → 가중평균 순으로, 가장 최근 값이
    셋 중 가장 최근 값보다 SHARES_STALE_DAYS 넘게 오래되지 않은 첫 출처 (예: ACN 은 dei 가 2010년에
    멈춰 있어 가중평균을 씀)."""
    cands = [
        (first_filed_instants(facts, "EntityCommonStockSharesOutstanding", "shares", "dei"), "DEI"),
        (first_filed_instants(facts, "CommonStockSharesOutstanding", "shares"), "10-Q"),
        (weighted_shares(facts, ratio), "WADS"),
    ]
    have = [(sh, code) for sh, code in cands if sh]
    if not have:
        return {}, "DEI"
    newest = max(max(sh) for sh, _ in have)
    for sh, code in have:
        if _span(max(sh), newest) <= SHARES_STALE_DAYS:
            return sh, code
    return have[0]


def weighted_shares(facts: dict, ratio: float = 1.0) -> dict[str, dict]:
    """{기간 끝: entry} 가중평균 주식수 (기간마다 처음 제출된 값, 같은 끝날이면 짧은 기간 우선).
    entry["val"] 은 ratio 를 곱한 값."""
    out: dict[str, tuple[int, dict]] = {}
    for c in WEIGHTED_SHARES:
        for (s, e), x in first_filed_durations(facts, c, "shares").items():
            days = _span(s, e)
            if not (_in(days, QUARTER_DAYS) or _in(days, YEAR_DAYS)):
                continue
            if e not in out or days < out[e][0]:
                out[e] = (days, {**x, "val": x["val"] * ratio})
        if out:
            break
    return {e: x for e, (_d, x) in out.items()}


def build_rows(
    facts: dict, years: int = 3, today: date | None = None, ticker: str | None = None
) -> list[dict]:
    """명세 payload 행 목록 (연간·분기·주식수·스냅샷). period_end 가 years 년 전 1월 1일 이후인 것만.
    ticker 는 CLASS_SHARE_RATIO 를 찾을 때만 씀."""
    today = today or date.today()
    facts, currency = as_us_gaap(facts)
    ratio = CLASS_SHARE_RATIO.get((ticker or "").upper().replace(".", "-"), 1.0)
    cutoff = date(today.year - years, 1, 1).isoformat()
    rows: list[dict] = []

    def add(period, metric, value, unit, end, filed, report_code, accn) -> None:  # noqa: ANN001
        if end < cutoff:
            return
        rows.append(
            {
                "period": period,
                "fs_div": "-",
                "metric": metric,
                "value": value,
                "unit": unit,
                "fiscal_year": int(end[:4]),
                "report_code": report_code,
                "period_end": end,
                "disclosed_at": filed,
                "rcept_no": accn,
            }
        )

    fy_ends: set[str] = set()
    # 1·2) 흐름 항목: 연간 + 분기
    for name, qname, candidates, unit in FLOW_METRICS:
        annual = _merge(
            candidates, lambda c, u=unit: annual_flow_values(first_filed_durations(facts, c, u))
        )
        quarters = _merge(
            candidates, lambda c, u=unit: quarter_values(first_filed_durations(facts, c, u))
        )
        for end, e in sorted(annual.items()):
            fy_ends.add(end)
            add(f"FY{end[:4]}", name, e["val"], _unit_name(unit), end, e["filed"], "10-K",
                e.get("accn"))  # fmt: skip
        for end, q in sorted(quarters.items()):
            code = "10-K" if q["how"] != "3M" and end in annual else (q.get("form") or "10-Q")
            add(f"Q{end}", qname, q["val"], _unit_name(unit), end, q["filed"], code, q.get("accn"))
    # 재무상태 항목: 분기말 + 회계연도 말 (FY 이름, 예전 행과 같은 모양)
    for name, candidates, unit in INSTANT_METRICS:
        inst = _merge(candidates, lambda c, u=unit: first_filed_instants(facts, c, u))
        for end, e in sorted(inst.items()):
            code = e.get("form") or "10-Q"
            add(f"Q{end}", name, e["val"], unit, end, e["filed"], code, e.get("accn"))
            if end in fy_ends:
                add(f"FY{end[:4]}", name, e["val"], unit, end, e["filed"], "10-K", e.get("accn"))
    # 3) 유통주식수 이력
    shares, code = pick_shares(facts, ratio)
    for end, e in sorted(shares.items()):
        add(f"S{end}", "유통주식수", e["val"], "주", end, e["filed"], code, e.get("accn"))

    # 4) 지표 계산용 최신 입력값
    inputs = {}
    eps_c = first_concept(
        facts, ["EarningsPerShareDiluted", "EarningsPerShareBasic"], "USD/shares", True
    )
    if eps_c and (v := ttm_value(facts, eps_c, "USD/shares")):
        inputs["EPS(TTM)"] = (v, "USD")
    ni_c = first_concept(facts, ["NetIncomeLoss", "ProfitLoss"], "USD", True)
    if ni_c and (v := ttm_value(facts, ni_c, "USD")):
        inputs["순이익(TTM)"] = (v, "USD")
    if v := latest_instant(facts, EQUITY, "USD"):
        inputs["자본총계(최근)"] = (v, "USD")
    if code == "DEI":
        snap_shares = latest_instant(facts, ["EntityCommonStockSharesOutstanding"], "shares", "dei")
    elif code == "10-Q":
        snap_shares = latest_instant(facts, ["CommonStockSharesOutstanding"], "shares")
    else:
        e = shares[max(shares)] if shares else None
        snap_shares = (e["val"], e["end"], e["filed"]) if e else None
    if snap_shares:
        inputs["발행주식수"] = (snap_shares, "주")
    if "자본총계(최근)" in inputs and snap_shares and snap_shares[0]:
        eq = inputs["자본총계(최근)"][0]
        inputs["BPS"] = ((eq[0] / snap_shares[0], eq[1], max(eq[2], snap_shares[2])), "USD")
    for metric, ((val, as_of, filed), unit) in inputs.items():
        rows.append(
            {
                "period": today.isoformat(),
                "fs_div": "-",
                "metric": metric,
                "value": val,
                "unit": unit,
                "fiscal_year": None,
                "report_code": "SNAPSHOT",
                "period_end": as_of,
                "disclosed_at": filed,
                "rcept_no": None,
            }
        )
    if currency != "USD":
        for r in rows:
            if r["unit"] == "USD":
                r["unit"] = currency
    return rows
