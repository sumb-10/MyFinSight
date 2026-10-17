"""[정량] OpenDART 재무제표 (단일회사 주요계정 fnlttSinglAcnt) + 주식 총수·배당 (정기보고서 주요정보).

- 주요계정 (fnlttSinglAcnt.json): 보고서(11013 1분기, 11012 반기, 11014 3분기, 11011 사업)마다
  계정별 당기 금액. 손익 항목은 분기·반기 보고서에서 thstrm_amount = 그 3개월, thstrm_add_amount =
  당기 누적(1월~분기말)이고, 사업보고서는 1년 값이다 (thstrm_dt 의 기간으로 확인함: 기간이 100일을
  넘으면 thstrm_amount 를 누적으로 본다). 보고서에 나온 값은 metric = 계정 이름 그대로 두고
  (예전 행과 같음), 손익 주요 항목은 다음을 더 만든다
  - "<항목>(분기)": 진짜 3개월 값. 없으면 누적 차이로 (반기 누적 − 1분기, 3분기 누적 − 반기 누적),
    4분기 = 사업보고서 연간 − 3분기 누적 (없으면 연간 − 1·2·3분기 합)
  - "<항목>(누적)": 반기·3분기 보고서의 당기 누적
  항목: 매출액·영업이익·당기순이익 (계정 이름 변형은 FLOW_ALIASES), 지배기업 소유주지분 순이익이
  있으면 "지배주주순이익" (주요계정에는 보통 없음: 그때 가치평가는 당기순이익(비지배지분 포함)을 씀)
- 주식의 총수 현황 (stockTotqySttus.json, 2015년~): 보통주 행의 발행주식수(istc_totqy)·
  자기주식수(tesstk_co)·유통주식수(distb_stock_co), 기준일 = stlm_dt (없으면 보고서 분기말)
- 배당에 관한 사항 (alotMatter.json, 2015년~, 기본은 사업보고서만): 보통주 "주당 현금배당금(원)" →
  주당배당금, "현금배당금총액(백만원)" → 배당금총액(원)
- 오류 020(요청 한도 초과, 하루 2만 건)·010/011/012/901(키 문제)은 DartLimitError 로 바로 멈춘다
  (재시도해도 같으므로). 어댑터·수집 작업은 그 출처를 이번 실행에서 그만 받고 다음 실행이 이어 받음
- 종목코드 ↔ DART 고유번호(corp_code) ↔ 회사명 매핑: corpCode.xml을 받아 .cache에 7일간 보관
- rcept_no 앞 8자리 = 공시 접수일 → disclosed_at (백테스트 미래정보 차단)
- 회사 하나에 연도 × 보고서 종류만큼(기본 20번) 부르므로 호출 사이 간격(MIN_INTERVAL_SEC)을 두고,
  서버가 연결을 끊으면(RemoteDisconnected 등) 새 연결로 몇 번 다시 부른다
"""

import io
import json
import re
import time
import zipfile
from collections import defaultdict
from datetime import date, timedelta
from xml.etree import ElementTree

import requests

from backend.adapters.crawlers import config
from backend.adapters.crawlers.common import http_session, num, to_date
from backend.schemas.errors import DataSourceError

SOURCE = "DART"
API = "https://opendart.fss.or.kr/api"
REPORT_NAMES = {
    "11011": "사업보고서",
    "11012": "반기보고서",
    "11013": "1분기보고서",
    "11014": "3분기보고서",
}
_session = http_session()
MIN_INTERVAL_SEC = 0.4  # 호출 사이 최소 간격 (연달아 부르면 서버가 연결을 끊음)
CONNECT_RETRIES = 3  # 연결이 끊겼을 때 새 연결로 다시 부르는 횟수
_last_call = 0.0
STOP_STATUSES = {
    "010": "등록되지 않은 키",
    "011": "사용할 수 없는 키",
    "012": "접근할 수 없는 IP",
    "020": "요청 제한 초과 (하루 2만 건 안팎, 내일 다시)",
    "901": "개인정보 보유기간 만료 키",
}
QUARTER_END = {"11013": "03-31", "11012": "06-30", "11014": "09-30", "11011": "12-31"}
"""보고서 → 12월 결산 회사의 기준일 (응답에 기준일이 없을 때만 씀)."""
EXTRA_FROM_YEAR = 2015
"""정기보고서 주요정보(주식 총수·배당)를 주는 첫 사업연도."""
FINANCIALS_FROM_YEAR = 2015
"""단일회사 주요계정(fnlttSinglAcnt)을 주는 첫 사업연도. 그 전 해는 부르지 않는다 (늘 013 없음)."""


class DartLimitError(DataSourceError):
    """DART 요청 한도 초과·키 오류: 이번 실행에서 DART 를 더 부르지 않는다."""

    code = "DATA_SOURCE_QUOTA"


def _get(path: str, params: dict, timeout: int):
    """간격을 지켜 부르고, 연결이 끊기면 세션을 새로 만들어 2·4·8초 쉬고 다시 부른다."""
    global _session, _last_call
    for attempt in range(CONNECT_RETRIES + 1):
        wait = MIN_INTERVAL_SEC - (time.monotonic() - _last_call)
        if wait > 0:
            time.sleep(wait)
        try:
            _last_call = time.monotonic()
            return _session.get(f"{API}/{path}", params=params, timeout=timeout)
        except requests.ConnectionError:
            if attempt == CONNECT_RETRIES:
                raise
            _session.close()
            _session = http_session()
            time.sleep(2 ** (attempt + 1))
    raise AssertionError("도달하지 않음")


def corp_cache():
    return config.CACHE_DIR / "dart_corp_codes.json"


def load_corp_codes() -> dict:
    """{stock_code: {"corp_code", "corp_name"}} (상장사만)"""
    if corp_cache().exists():
        data = json.loads(corp_cache().read_text(encoding="utf-8"))
        if date.fromisoformat(data["saved"]) > date.today() - timedelta(days=7):
            return data["codes"]
    config.require(DART_API_KEY=config.DART_API_KEY)
    res = _get("corpCode.xml", {"crtfc_key": config.DART_API_KEY}, 60)
    res.raise_for_status()
    if not res.content.startswith(b"PK"):
        raise RuntimeError(f"DART corpCode 응답 오류: {res.text[:200]}")
    with zipfile.ZipFile(io.BytesIO(res.content)) as z:
        root = ElementTree.fromstring(z.read(z.namelist()[0]))
    codes = {}
    for item in root.iter("list"):
        stock = (item.findtext("stock_code") or "").strip()
        if stock:
            codes[stock] = {
                "corp_code": item.findtext("corp_code"),
                "corp_name": (item.findtext("corp_name") or "").strip(),
            }
    corp_cache().write_text(
        json.dumps({"saved": date.today().isoformat(), "codes": codes}, ensure_ascii=False),
        encoding="utf-8",
    )
    return codes


def find_by_stock_code(stock_code: str) -> dict | None:
    return load_corp_codes().get(stock_code)


def find_by_name(name: str) -> tuple[str, dict] | None:
    """회사명으로 종목코드 찾기 (정확히 일치 우선, 없으면 부분 일치 중 가장 짧은 이름)."""
    codes = load_corp_codes()
    exact = [(k, v) for k, v in codes.items() if v["corp_name"] == name]
    if exact:
        return exact[0]
    partial = sorted(
        ((k, v) for k, v in codes.items() if name in v["corp_name"]),
        key=lambda kv: len(kv[1]["corp_name"]),
    )
    return partial[0] if partial else None


def _report_list(path: str, corp_code: str, year: int, report_code: str) -> list[dict]:
    """정기보고서 API 한 번. 데이터 없음(013)은 빈 목록, 한도·키 오류는 DartLimitError."""
    config.require(DART_API_KEY=config.DART_API_KEY)
    res = _get(
        path,
        {
            "crtfc_key": config.DART_API_KEY,
            "corp_code": corp_code,
            "bsns_year": str(year),
            "reprt_code": report_code,
        },
        20,
    )
    payload = res.json()
    status = str(payload.get("status"))
    if status == "013":  # 조회된 데이터 없음 (아직 공시 전 등)
        return []
    if status in STOP_STATUSES:
        raise DartLimitError(
            f"DART [{status}] {STOP_STATUSES[status]}: {payload.get('message')}",
            details={"status": status},
        )
    if status != "000":
        raise RuntimeError(f"DART 오류 [{status}] {payload.get('message')}")
    return payload.get("list", [])


def fetch_disclosure_list(corp_code: str, start: date, end: date) -> list[dict]:
    """공시검색 (list.json): 회사 하나의 [start, end] 공시 목록 전부 (100건씩 쪽을 넘김).

    항목: rcept_no, rcept_dt(YYYYMMDD), report_nm, flr_nm, rm, corp_name, stock_code.
    고유번호를 주면 기간 제한이 없다 (고유번호 없이는 3개월). 2000년부터 응답함 (1999년은 사업보고서
    몇 건뿐). 없음(013)은 빈 목록, 한도·키 오류는 DartLimitError.
    """
    config.require(DART_API_KEY=config.DART_API_KEY)
    out: list[dict] = []
    page = 1
    while True:
        params = {
            "crtfc_key": config.DART_API_KEY,
            "corp_code": corp_code,
            "bgn_de": start.strftime("%Y%m%d"),
            "end_de": end.strftime("%Y%m%d"),
            "page_no": page,
            "page_count": 100,
        }
        payload = _get("list.json", params, 20).json()
        status = str(payload.get("status"))
        if status == "013":
            return out
        if status in STOP_STATUSES:
            raise DartLimitError(
                f"DART [{status}] {STOP_STATUSES[status]}: {payload.get('message')}",
                details={"status": status},
            )
        if status != "000":
            raise RuntimeError(f"DART 오류 [{status}] {payload.get('message')}")
        out += payload.get("list", [])
        if page >= int(payload.get("total_page") or 1):
            return out
        page += 1


def fetch_company(corp_code: str) -> dict:
    """기업개황 (company.json): corp_name, induty_code(KSIC 업종코드), est_dt, acc_mt 등.

    한도·키 오류는 DartLimitError, 그 밖의 오류는 RuntimeError.
    """
    config.require(DART_API_KEY=config.DART_API_KEY)
    res = _get("company.json", {"crtfc_key": config.DART_API_KEY, "corp_code": corp_code}, 20)
    payload = res.json()
    status = str(payload.get("status"))
    if status in STOP_STATUSES:
        raise DartLimitError(
            f"DART [{status}] {STOP_STATUSES[status]}: {payload.get('message')}",
            details={"status": status},
        )
    if status != "000":
        raise RuntimeError(f"DART 기업개황 오류 [{status}] {payload.get('message')}")
    return payload


def industry_code(stock_code: str) -> str | None:
    """종목코드(6자리) → DART 기업개황의 induty_code (KSIC 10차, 예: 264). 없으면 None.

    GICS 분류 대체(classification.py, backend/data/config/ksic_to_gics.csv)에 쓴다. 종목 하나에 요청 하나.
    """
    code = (fetch_company(resolve_corp_code(stock_code)).get("induty_code") or "").strip()
    return code or None


def fetch_financials(corp_code: str, year: int, report_code: str = "11011") -> list[dict]:
    """단일회사 주요계정."""
    return _report_list("fnlttSinglAcnt.json", corp_code, year, report_code)


def fetch_share_totals(corp_code: str, year: int, report_code: str = "11011") -> list[dict]:
    """주식의 총수 현황 (2015년~)."""
    return _report_list("stockTotqySttus.json", corp_code, year, report_code)


def fetch_dividends(corp_code: str, year: int, report_code: str = "11011") -> list[dict]:
    """배당에 관한 사항 (2015년~)."""
    return _report_list("alotMatter.json", corp_code, year, report_code)


def _dates(thstrm_dt: str | None) -> list[date]:
    return [
        to_date(d.replace(".", "")) for d in re.findall(r"\d{4}\.\d{2}\.\d{2}", thstrm_dt or "")
    ]


def _period_end(thstrm_dt: str | None):
    dates = _dates(thstrm_dt)
    return dates[-1] if dates else None


def _span_days(thstrm_dt: str | None) -> int | None:
    """'2024.07.01 ~ 2024.09.30' → 91. 기간이 아니면(시점) None."""
    dates = _dates(thstrm_dt)
    return (dates[-1] - dates[0]).days if len(dates) >= 2 else None


FLOW_ALIASES = {
    "매출액": "매출액",
    "수익(매출액)": "매출액",
    "영업수익": "매출액",
    "영업이익": "영업이익",
    "영업이익(손실)": "영업이익",
    "당기순이익": "당기순이익",
    "당기순이익(손실)": "당기순이익",
    "분기순이익": "당기순이익",
    "반기순이익": "당기순이익",
    "분기순이익(손실)": "당기순이익",
    "반기순이익(손실)": "당기순이익",
}
"""주요계정 손익 계정 이름(띄어쓰기 무시) → 분기 값을 만들 항목 이름."""
_OWNER_NI = re.compile(r"지배기업.*소유주|지배주주")


def flow_name(account_nm: str) -> str | None:
    """분기·누적 값을 만들 손익 항목 이름. 대상이 아니면 None."""
    key = account_nm.replace(" ", "")
    if key in FLOW_ALIASES:
        return FLOW_ALIASES[key]
    if _OWNER_NI.search(key) and "순이익" in key and "비지배" not in key:
        return "지배주주순이익"
    return None


def _available_from(year: int, report_code: str) -> date:
    """이 보고서가 나올 수 있는 가장 이른 날 (이보다 이르면 부르지 않음, 요청 수 절약)."""
    if report_code == "11011":
        return date(year + 1, 2, 1)
    month = {"11013": 4, "11012": 7, "11014": 10}[report_code]
    return date(year, month, 20)


def resolve_corp_code(key: str) -> str:
    """8자리 고유번호는 그대로, 6자리 종목코드는 corpCode 표에서 찾아 바꾼다."""
    if len(key) == 6:
        found = find_by_stock_code(key)
        if not found:
            raise RuntimeError(f"DART corp_code를 찾을 수 없음 (종목코드 {key})")
        return found["corp_code"]
    return key


def _row(year, rc, fs_div, metric, value, unit, pend, rcept_no) -> dict:  # noqa: ANN001
    return {
        "period": f"{year}_{rc}",
        "fs_div": fs_div,
        "metric": metric,
        "value": value,
        "unit": unit,
        "fiscal_year": year,
        "report_code": rc,
        "period_end": pend.isoformat() if pend else None,
        "disclosed_at": to_date(rcept_no[:8]).isoformat() if rcept_no else None,
        "rcept_no": rcept_no,
    }


def quarter_rows(flows: dict) -> list[dict]:
    """손익 항목의 보고서별 값 → "(분기)"·"(누적)" 행.

    flows[(year, fs_div, 항목)][보고서] = {"amount", "add", "span", "pend", "rcept_no", "unit"}
    """
    out: list[dict] = []
    for (year, fs_div, name), reps in sorted(flows.items()):
        three: dict[str, tuple[float, str]] = {}  # 보고서 → (3개월 값, 마지막 공시 접수번호)
        cum: dict[str, tuple[float, str]] = {}  # 보고서 → (누적 값, 접수번호)
        for rc in ("11013", "11012", "11014"):
            r = reps.get(rc)
            if not r or r["amount"] is None:
                continue
            if r["span"] is not None and r["span"] > 100:  # 당기 금액이 누적으로 온 경우
                cum[rc] = (r["amount"], r["rcept_no"])
            else:
                three[rc] = (r["amount"], r["rcept_no"])
                if r["add"] is not None:
                    cum[rc] = (r["add"], r["rcept_no"])
                elif rc == "11013":
                    cum[rc] = (r["amount"], r["rcept_no"])
        if "11013" in three and "11013" not in cum:
            cum["11013"] = three["11013"]
        for rc, prev in (("11012", "11013"), ("11014", "11012")):
            if rc not in three and rc in cum and prev in cum:
                three[rc] = (cum[rc][0] - cum[prev][0], max(cum[rc][1], cum[prev][1]))
        annual = reps.get("11011")
        if annual and annual["amount"] is not None:
            if "11014" in cum:
                three["11011"] = (annual["amount"] - cum["11014"][0], annual["rcept_no"])
            elif all(q in three for q in ("11013", "11012", "11014")):
                total = sum(three[q][0] for q in ("11013", "11012", "11014"))
                three["11011"] = (annual["amount"] - total, annual["rcept_no"])
        for rc, (val, rcept) in three.items():
            r = reps[rc]
            out.append(_row(year, rc, fs_div, f"{name}(분기)", val, r["unit"], r["pend"], rcept))
        for rc in ("11012", "11014"):
            if rc in cum:
                r = reps[rc]
                out.append(
                    _row(year, rc, fs_div, f"{name}(누적)", cum[rc][0], r["unit"], r["pend"],
                         cum[rc][1])
                )  # fmt: skip
    return out


def _default_end(year: int, rc: str) -> date:
    return to_date(f"{year}-{QUARTER_END[rc]}")


def share_rows(items: list[dict], year: int, rc: str) -> list[dict]:
    """주식의 총수 현황 → 발행주식수·자기주식수·유통주식수 (보통주, 없으면 합계 행)."""
    pick = next((i for i in items if "보통" in (i.get("se") or "")), None) or next(
        (i for i in items if "합계" in (i.get("se") or "")), None
    )
    if not pick or not pick.get("rcept_no"):
        return []
    pend = to_date(pick.get("stlm_dt")) if pick.get("stlm_dt") else _default_end(year, rc)
    out = []
    for field, metric in (
        ("istc_totqy", "발행주식수"),
        ("tesstk_co", "자기주식수"),
        ("distb_stock_co", "유통주식수"),
    ):
        v = num(pick.get(field))
        if v is not None:
            out.append(_row(year, rc, "-", metric, v, "주", pend, pick["rcept_no"]))
    return out


def dividend_rows(items: list[dict], year: int, rc: str) -> list[dict]:
    """배당에 관한 사항 → 주당배당금(보통주, 원)·배당금총액(원). 값이 '-' 면 건너뜀."""
    out = []
    seen: set[str] = set()
    for i in items:
        se = (i.get("se") or "").replace(" ", "")
        kind = (i.get("stock_knd") or "").strip()
        v = num(i.get("thstrm"))
        if v is None or not i.get("rcept_no"):
            continue
        pend = to_date(i.get("stlm_dt")) if i.get("stlm_dt") else _default_end(year, rc)
        if "주당현금배당금" in se and (not kind or "보통" in kind):
            metric, value, unit = "주당배당금", v, "KRW"
        elif "현금배당금총액" in se:
            metric, value, unit = "배당금총액", v * 1_000_000, "KRW"  # 백만원 단위
        else:
            continue
        if metric in seen:
            continue
        seen.add(metric)
        out.append(_row(year, rc, "-", metric, value, unit, pend, i["rcept_no"]))
    return out


def financial_rows(
    corp_code: str,
    years: list[int],
    report_codes=("11011", "11013", "11012", "11014"),
    *,
    share_codes=("11011", "11013", "11012", "11014"),
    dividend_codes=("11011",),
    today: date | None = None,
    annual_only_years: tuple[int, ...] = (),
) -> list[dict]:
    """명세 payload 행 목록 (주요계정 + 분기·누적 + 주식 총수 + 배당).

    아직 나올 수 없는 보고서(_available_from 이 today 뒤)는 부르지 않는다.
    annual_only_years: 사업보고서(11011)의 주요계정만 부를 해 (조회 시작 전 해, 요청 수 절약).
    """
    today = today or date.today()
    rows, seen = [], set()
    flows: dict = defaultdict(dict)
    for year in years:
        if year < FINANCIALS_FROM_YEAR:  # API 가 데이터를 주지 않는 해: 요청 수만 씀
            continue
        for rc in report_codes:
            if _available_from(year, rc) > today:
                continue
            if year in annual_only_years and rc != "11011":
                continue
            for r in fetch_financials(corp_code, year, rc):
                metric = (r.get("account_nm") or "").strip()
                fs_div = r.get("fs_div") or "CFS"
                key = (year, rc, fs_div, metric)
                if not metric or key in seen:  # 같은 계정이 중복되면 첫 번째만
                    continue
                seen.add(key)
                pend = _period_end(r.get("thstrm_dt"))
                fy = year  # 기간 이름·사업연도는 요청한 해 (예전 행과 같은 키)
                row = _row(fy, rc, fs_div, metric, num(r.get("thstrm_amount")),
                           r.get("currency") or "KRW", pend, r.get("rcept_no"))  # fmt: skip
                rows.append(row)
                name = flow_name(metric)
                if name and r.get("sj_div", "IS") != "BS":
                    slot = flows[(fy, fs_div, name)]
                    if rc not in slot:
                        slot[rc] = {
                            "amount": row["value"],
                            "add": num(r.get("thstrm_add_amount")),
                            "span": _span_days(r.get("thstrm_dt")),
                            "pend": pend,
                            "rcept_no": r.get("rcept_no"),
                            "unit": row["unit"],
                        }
        if year < EXTRA_FROM_YEAR or year in annual_only_years:
            continue
        for rc in share_codes:
            if _available_from(year, rc) <= today:
                rows += share_rows(fetch_share_totals(corp_code, year, rc), year, rc)
        for rc in dividend_codes:
            if _available_from(year, rc) <= today:
                rows += dividend_rows(fetch_dividends(corp_code, year, rc), year, rc)
    return rows + quarter_rows(flows)
