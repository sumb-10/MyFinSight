"""[정량·해외 보정] SEC EDGAR XBRL companyfacts (https://data.sec.gov/api/xbrl/companyfacts/CIK##########.json).

키는 없지만 SEC 정책상 "이름 이메일" 형식의 User-Agent가 필수이고, 초당 10회 이하로 호출해야 한다.

만드는 행
1) 연간(10-K) 주요 계정 (period="FY2025", report_code="10-K", disclosed_at=최초 제출일)
   같은 기간 값이 이후 보고서에 비교수치로 다시 나오면 '가장 먼저 제출된 값'을 쓴다 (공시 시점 기준).
2) 지표 계산용 최신 입력값 스냅샷 (report_code="SNAPSHOT", period=오늘)
   EPS(TTM), 순이익(TTM), 자본총계(최근), 발행주식수, BPS
"""

import json
from datetime import date, timedelta

from myfinsight.data.crawlers import config
from myfinsight.data.crawlers.common import http_session, to_date

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


def build_rows(facts: dict, years: int = 3, today: date | None = None) -> list[dict]:
    """명세 payload 행 목록. 원본 build_rows 에서 asset·source_id·run_id 만 뺐다."""
    rows = []
    # 1) 연간 계정
    for label, candidates, unit, flow in ANNUAL_METRICS:
        concept = first_concept(facts, candidates, unit, flow)
        if not concept:
            continue
        vals = annual_values(facts, concept, unit, flow)
        for end in sorted(vals)[-years:]:
            e = vals[end]
            rows.append(
                {
                    "period": f"FY{end[:4]}",
                    "fs_div": "-",
                    "metric": label,
                    "value": e["val"],
                    "unit": "USD" if unit == "USD/shares" else unit,
                    "fiscal_year": int(end[:4]),
                    "report_code": "10-K",
                    "period_end": end,
                    "disclosed_at": e["filed"],
                    "rcept_no": e.get("accn"),
                }
            )

    # 2) 지표 계산용 최신 입력값
    today = today or date.today()
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
    shares = latest_instant(
        facts, ["EntityCommonStockSharesOutstanding"], "shares", "dei"
    ) or latest_instant(facts, ["CommonStockSharesOutstanding"], "shares")
    if shares:
        inputs["발행주식수"] = (shares, "주")
    if "자본총계(최근)" in inputs and shares and shares[0]:
        eq = inputs["자본총계(최근)"][0]
        inputs["BPS"] = ((eq[0] / shares[0], eq[1], max(eq[2], shares[2])), "USD")
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
    return rows
