"""[정량] 한국투자증권 Open API — 국내주식 일봉 + 현재가(PER/PBR 스냅샷).

- 토큰은 하루 유효·발급 횟수 제한 → .cache에 저장해 재사용
- 일봉은 1회 최대 100거래일 → 기간을 거꾸로 나눠 반복 조회
- FID_ORG_ADJ_PRC=0 → 수정주가 기준이므로 close와 adj_close에 같은 값 저장
"""

import json
import time
from datetime import date, datetime, timedelta

from myfinsight.data.crawlers import config
from myfinsight.data.crawlers.common import http_session, num, to_date

SOURCE = "KIS"
_session = http_session()


def base_url() -> str:
    return {
        "prod": "https://openapi.koreainvestment.com:9443",
        "vts": "https://openapivts.koreainvestment.com:29443",
    }.get(config.KIS_ENV, "https://openapi.koreainvestment.com:9443")


def token_file():
    return config.CACHE_DIR / f"kis_token_{config.KIS_ENV}.json"


def get_access_token() -> str:
    config.require(KIS_APP_KEY=config.KIS_APP_KEY, KIS_APP_SECRET=config.KIS_APP_SECRET)
    if token_file().exists():
        cached = json.loads(token_file().read_text(encoding="utf-8"))
        if cached.get("app_key") == config.KIS_APP_KEY and datetime.fromisoformat(
            cached["expires_at"]
        ) > datetime.now() + timedelta(minutes=10):
            return cached["access_token"]
    res = _session.post(
        f"{base_url()}/oauth2/tokenP",
        timeout=(5, 15),
        json={
            "grant_type": "client_credentials",
            "appkey": config.KIS_APP_KEY,
            "appsecret": config.KIS_APP_SECRET,
        },
    )
    payload = res.json()
    token = payload.get("access_token")
    if not token:
        raise RuntimeError(f"KIS 토큰 발급 실패: {payload.get('error_description') or payload}")
    exp = payload.get("access_token_token_expired")  # "2026-10-01 10:00:00"
    expires_at = (
        datetime.strptime(exp, "%Y-%m-%d %H:%M:%S") if exp else datetime.now() + timedelta(hours=23)
    )
    token_file().write_text(
        json.dumps(
            {
                "access_token": token,
                "expires_at": expires_at.isoformat(),
                "app_key": config.KIS_APP_KEY,
            }
        ),
        encoding="utf-8",
    )
    return token


def _headers(tr_id: str) -> dict:
    return {
        "content-type": "application/json; charset=utf-8",
        "authorization": f"Bearer {get_access_token()}",
        "appkey": config.KIS_APP_KEY,
        "appsecret": config.KIS_APP_SECRET,
        "tr_id": tr_id,
        "custtype": "P",
    }


def _get(path: str, tr_id: str, params: dict) -> dict:
    res = _session.get(
        f"{base_url()}{path}", headers=_headers(tr_id), params=params, timeout=(5, 15)
    )
    payload = res.json()
    if payload.get("rt_cd") != "0":
        raise RuntimeError(f"KIS 오류 [{payload.get('msg_cd')}] {payload.get('msg1')}")
    return payload


def fetch_daily(ticker: str, start: date, end: date, pause: float = 0.2) -> list[dict]:
    out, cursor_end = {}, end
    while cursor_end >= start:
        payload = _get(
            "/uapi/domestic-stock/v1/quotations/inquire-daily-itemchartprice",
            "FHKST03010100",
            {
                "FID_COND_MRKT_DIV_CODE": "J",
                "FID_INPUT_ISCD": ticker,
                "FID_INPUT_DATE_1": start.strftime("%Y%m%d"),
                "FID_INPUT_DATE_2": cursor_end.strftime("%Y%m%d"),
                "FID_PERIOD_DIV_CODE": "D",
                "FID_ORG_ADJ_PRC": "0",
            },
        )
        rows = [r for r in payload.get("output2") or [] if r.get("stck_bsop_date")]
        if not rows:
            break
        for r in rows:
            out[r["stck_bsop_date"]] = r
        oldest = min(to_date(r["stck_bsop_date"]) for r in rows)
        if oldest <= start or len(rows) < 100:
            break
        cursor_end = oldest - timedelta(days=1)
        time.sleep(pause)  # 초당 호출 제한
    return list(out.values())


def fetch_current(ticker: str) -> dict:
    return _get(
        "/uapi/domestic-stock/v1/quotations/inquire-price",
        "FHKST01010100",
        {"FID_COND_MRKT_DIV_CODE": "J", "FID_INPUT_ISCD": ticker},
    ).get("output", {})


def price_rows(ticker: str, start: date, end: date) -> list[dict]:
    """명세 payload 행 목록. 원본 collect() 의 일봉 부분 (DB 저장은 뺐다)."""
    if not (len(ticker) == 6 and ticker.isalnum()):
        raise ValueError(f"KIS 국내주식 시세는 6자리 국내 종목코드만 지원 (받은 값: {ticker})")
    prices = []
    for r in fetch_daily(ticker, start, end):
        close = num(r.get("stck_clpr"))
        if close is None:  # 필수 필드 누락 → 저장 제외
            continue
        prices.append(
            {
                "date": to_date(r["stck_bsop_date"]).isoformat(),
                "open": num(r.get("stck_oprc")),
                "high": num(r.get("stck_hgpr")),
                "low": num(r.get("stck_lwpr")),
                "close": close,
                "adj_close": close,
                "volume": int(num(r.get("acml_vol")) or 0),
                "currency": "KRW",
            }
        )
    return sorted(prices, key=lambda p: p["date"])


def snapshot(ticker: str) -> dict[str, tuple[float, str]]:
    """현재가 화면의 지표 스냅샷 {지표: (값, 단위)}. 원본 collect() 의 snap 부분."""
    cur = fetch_current(ticker)
    return {
        metric: (num(cur.get(key)), unit)
        for metric, key, unit in (
            ("PER", "per", "배"),
            ("PBR", "pbr", "배"),
            ("EPS", "eps", "KRW"),
            ("BPS", "bps", "KRW"),
            ("시가총액(억원)", "hts_avls", "억원"),
        )
        if num(cur.get(key)) is not None
    }


def stock_info(code: str) -> dict:
    """국내 상품 기본정보 (search-stock-info, CTPF1002R). 종류는 scty_grp_id_cd
    (ST 주권, EF ETF, EN ETN, RT 리츠 ...), 이름은 prdt_abrv_name."""
    payload = _get(
        "/uapi/domestic-stock/v1/quotations/search-stock-info",
        "CTPF1002R",
        {"PRDT_TYPE_CD": "300", "PDNO": code},
    )
    return payload.get("output") or {}
