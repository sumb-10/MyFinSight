"""[정량] 한국투자증권 Open API — 국내주식 일봉 + 현재가(PER/PBR 스냅샷).

- 토큰은 하루 유효·발급 횟수 제한 → .cache에 저장해 재사용
- 일봉은 1회 최대 100거래일 → 기간을 거꾸로 나눠 반복 조회
- FID_ORG_ADJ_PRC=0 → 수정주가 기준이므로 close와 adj_close에 같은 값 저장
"""

import json
import time
from datetime import date, datetime, timedelta

from backend.adapters.crawlers import config
from backend.adapters.crawlers.common import http_session, num, to_date

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


RATE_LIMIT_CODE = "EGW00201"
"""초당 거래건수 초과. 잠깐 쉬었다 다시 부르면 된다."""
RATE_LIMIT_WAITS = (1.0, 2.0, 4.0)


def _get(path: str, tr_id: str, params: dict) -> dict:
    for attempt in range(len(RATE_LIMIT_WAITS) + 1):
        res = _session.get(
            f"{base_url()}{path}", headers=_headers(tr_id), params=params, timeout=(5, 15)
        )
        payload = res.json()
        if payload.get("rt_cd") == "0":
            return payload
        if payload.get("msg_cd") == RATE_LIMIT_CODE and attempt < len(RATE_LIMIT_WAITS):
            time.sleep(RATE_LIMIT_WAITS[attempt])
            continue
        raise RuntimeError(f"KIS 오류 [{payload.get('msg_cd')}] {payload.get('msg1')}")
    raise AssertionError("도달하지 않음")


FIN_PATHS = {
    "income": ("/uapi/domestic-stock/v1/finance/income-statement", "FHKST66430200"),
    "balance": ("/uapi/domestic-stock/v1/finance/balance-sheet", "FHKST66430100"),
    "ratio": ("/uapi/domestic-stock/v1/finance/financial-ratio", "FHKST66430300"),
}
"""국내주식 재무 (연간은 2004년부터, 분기는 최근 30분기). 손익·재무상태 금액 단위는 억원."""
FIN_MISSING = "99.99"
"""KIS 재무 응답에서 값이 없는 칸."""


def fetch_annual_financials(code: str, pause: float = 0.1) -> dict[str, dict[str, str]]:
    """6자리 종목코드의 연간 재무: {결산년월 YYYYMM: {칸: 값}} (손익·재무상태·재무비율 합침).

    칸: sale_account 매출액·bsop_prti 영업이익·thtr_ntin 당기순이익 (억원), total_aset·total_lblt·
    total_cptl 자산·부채·자본총계 (억원), eps·bps (원, 지금까지의 액면분할을 반영한 값), roe_val 등.
    값이 없는 칸은 "99.99" 로 온다 (FIN_MISSING)."""
    out: dict[str, dict[str, str]] = {}
    for path, tr in FIN_PATHS.values():
        payload = _get(path, tr, {"FID_DIV_CLS_CODE": "0", "fid_cond_mrkt_div_code": "J",
                                  "fid_input_iscd": code})  # fmt: skip
        for row in payload.get("output") or []:
            ym = row.get("stac_yymm")
            if ym:
                out.setdefault(ym, {}).update({k: v for k, v in row.items() if k != "stac_yymm"})
        time.sleep(pause)
    return out


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
