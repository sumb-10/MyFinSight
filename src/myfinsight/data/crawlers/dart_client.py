"""[정량] OpenDART 재무제표 (단일회사 주요계정 fnlttSinglAcnt).

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
from datetime import date, timedelta
from xml.etree import ElementTree

import requests

from myfinsight.data.crawlers import config
from myfinsight.data.crawlers.common import http_session, num, to_date

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


def fetch_financials(corp_code: str, year: int, report_code: str = "11011") -> list[dict]:
    config.require(DART_API_KEY=config.DART_API_KEY)
    res = _get(
        "fnlttSinglAcnt.json",
        {
            "crtfc_key": config.DART_API_KEY,
            "corp_code": corp_code,
            "bsns_year": str(year),
            "reprt_code": report_code,
        },
        20,
    )
    payload = res.json()
    if payload.get("status") == "013":  # 조회된 데이터 없음 (아직 공시 전 등)
        return []
    if payload.get("status") != "000":
        raise RuntimeError(f"DART 오류 [{payload.get('status')}] {payload.get('message')}")
    return payload.get("list", [])


def _period_end(thstrm_dt: str | None):
    dates = re.findall(r"\d{4}\.\d{2}\.\d{2}", thstrm_dt or "")
    return to_date(dates[-1].replace(".", "")) if dates else None


def resolve_corp_code(key: str) -> str:
    """8자리 고유번호는 그대로, 6자리 종목코드는 corpCode 표에서 찾아 바꾼다."""
    if len(key) == 6:
        found = find_by_stock_code(key)
        if not found:
            raise RuntimeError(f"DART corp_code를 찾을 수 없음 (종목코드 {key})")
        return found["corp_code"]
    return key


def financial_rows(
    corp_code: str, years: list[int], report_codes=("11011", "11013", "11012", "11014")
) -> list[dict]:
    """명세 payload 행 목록. 원본 collect() 의 행 만들기 부분 (DB 저장은 뺐다)."""
    rows, seen = [], set()
    for year in years:
        for rc in report_codes:
            for r in fetch_financials(corp_code, year, rc):
                metric = (r.get("account_nm") or "").strip()
                fs_div = r.get("fs_div") or "CFS"
                key = (year, rc, fs_div, metric)
                if not metric or key in seen:  # 같은 계정이 중복되면 첫 번째만
                    continue
                seen.add(key)
                pend = _period_end(r.get("thstrm_dt"))
                disclosed = to_date(r["rcept_no"][:8]) if r.get("rcept_no") else None
                rows.append(
                    {
                        "period": f"{year}_{rc}",
                        "fs_div": fs_div,
                        "metric": metric,
                        "value": num(r.get("thstrm_amount")),
                        "unit": r.get("currency") or "KRW",
                        "fiscal_year": int(r.get("bsns_year") or year),
                        "report_code": rc,
                        "period_end": pend.isoformat() if pend else None,
                        "disclosed_at": disclosed.isoformat() if disclosed else None,
                        "rcept_no": r.get("rcept_no"),
                    }
                )
    return rows
