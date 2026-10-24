"""일별 가치평가 (valuation_daily): 거래일마다 그날까지 공시된 재무만으로 PER·PBR·ROE·배당수익률.

입력은 계약 테이블만 읽는다: price_daily (close·fetched_at), financials (item·period_end·value·
report_date·period). 재무 값은 report_date(공시일) 이후에만 쓴다 (선견 없음).

계산 (종목 통화 그대로, 미국 USD·한국 KRW. 달러 환산은 분석 쪽에서 fx_daily 로)
- 주식 분할: 가격 출처의 종가(close)는 받은 시점까지의 분할이 반영된 값이고, 공시된 주식 수·주당
  값은 공시 당시 기준이다. 둘을 맞추려고 financials 의 "주식분할" (yfinance 분할 이력,
  권리락일·비율)로 누적 분할 계수 C(d) = d 까지 분할 비율의 곱을 만든다.
  - split_factor = C(close 받은 날) ÷ C(그날). 실제 그날 종가 = close × split_factor
  - 그날 주식 수 = 공시 주식 수 × C(그날) ÷ C(주식 수 기준일)
- 순이익 TTM: 최근 4개 분기 "(분기)" 값의 합 (지배주주순이익(분기) 우선, 없으면 당기순이익(분기)).
  분기 끝 날짜가 80~100일 간격으로 이어져야 함. 안 되거나 사업연도 값이 더 최근이면 사업연도 값
  (method NI=FY). 한국 주요계정에는 보통 지배주주 순이익이 없어 비지배지분이 포함된 당기순이익을 씀
- 주식 수: 유통주식수 (발행 − 자기주식), 없으면 발행주식수 − 자기주식수, 없으면 발행주식수.
  공시 출처(SEC_EDGAR·DART)가 아닌 보충 출처 값이면 method 에 출처를 붙임 (SH=유통주식수@YFINANCE_SHARES)
- market_cap = 실제 종가 × 그날 주식 수
- per = market_cap ÷ 순이익 TTM (= close ÷ eps_ttm), 순이익 ≤ 0 이면 NULL.
  주식 수가 없고 미국 보고 EPS(희석·분기) 4개가 있으면 실제 종가 ÷ EPS 합 (method PER=EPS)
- 주식 수도 보고 EPS 도 없고 KIS 연간 EPS·BPS(현재 주식 기준, 한국 2015년 전 보충 KIS_FIN)가 있으면
  per = close ÷ EPS(연간·현재기준), pbr = close ÷ BPS(현재기준) (method PER=EPS@KIS_FIN·PBR=BPS@KIS_FIN).
  KIS 값은 지금까지의 분할을 반영한 주당 값이라 close(받은 시점까지 분할 반영)와 바로 나눈다
- eps_ttm·bps·dps_ttm 은 close 와 같은 기준(분할 반영)의 주당 값 (close ÷ eps_ttm = per)
- pbr = market_cap ÷ 최근 자본총계 (자본 ≤ 0 이면 NULL)
- roe_ttm = 순이익 TTM ÷ 평균 자본 (최근 분기말 자본과 1년 전(±20일) 자본의 평균, 1년 전이 없으면
  최근 자본). 한국 자본총계는 비지배지분 포함
- dps_ttm: 미국 최근 4분기 주당배당금(분기) 합 (없으면 사업연도 주당배당금), 한국 최근 사업연도
  주당배당금 (사업보고서 「배당에 관한 사항」, 보통주). 배당 기록이 아예 없으면 NULL
  (무배당과 구분 못함)
- dividend_yield = 실제 주당배당금 ÷ 실제 종가 (비율, 0.012 = 1.2%)
- 오래된 값: 기준일(분기 끝·주식 수 기준일)이 STALE_DAYS(550일) 넘게 지난 값은 쓰지 않음 (상장폐지·
  공시 중단 종목에 옛 값이 계속 붙지 않게)

갱신 (valuation_step)
- 증분: 종목마다 ① 마지막 계산일 뒤의 새 가격 ② 지난 성공 실행 뒤 값이 바뀐 price_daily 행의 날짜
  ③ 지난 성공 실행 뒤 바뀐 financials 행의 공시일 (주식분할이 바뀌면 처음부터) 중 가장 이른 날부터
  다시 계산하고, 값이 바뀐 행만 쓴다 (_upsert). 실행 기록은 fetch_log (source VALUATION,
  target valuation_daily)
- 전체 다시 계산 (full=True): 모든 종목을 처음부터 (값이 같으면 쓰지 않음)
"""

from __future__ import annotations

import logging
import math
from collections.abc import Callable, Iterable, Sequence
from dataclasses import dataclass, field
from datetime import UTC, date, datetime, timedelta
from typing import Any

import numpy as np
import pandas as pd

logger = logging.getLogger(__name__)

NI_Q_ITEMS = ("지배주주순이익(분기)", "당기순이익(분기)")
NI_FY_ITEMS = ("지배주주순이익", "당기순이익", "당기순이익(손실)")
"""사업연도 순이익 (앞 항목 우선). DART 주요계정 사업보고서 값은 "당기순이익(손실)" 이름으로 온다."""
EQUITY_ITEM = "자본총계"
SHARES_OUT, SHARES_ISSUED, SHARES_TREASURY = "유통주식수", "발행주식수", "자기주식수"
DPS_Q, DPS_FY = "주당배당금(분기)", "주당배당금"
EPS_Q = "EPS(희석·분기)"
EPS_CUR, BPS_CUR = "EPS(연간·현재기준)", "BPS(현재기준)"
"""현재 주식 기준 주당 값 (KIS_FIN, 한국 2015년 전). close 와 바로 나눈다."""
SPLIT_ITEM = "주식분할"
VALUATION_ITEMS = (
    *NI_Q_ITEMS,
    *NI_FY_ITEMS,
    EQUITY_ITEM,
    SHARES_OUT,
    SHARES_ISSUED,
    SHARES_TREASURY,
    DPS_Q,
    DPS_FY,
    EPS_Q,
    EPS_CUR,
    BPS_CUR,
    SPLIT_ITEM,
)
"""valuation_daily 계산에 읽는 financials.item."""
STALE_DAYS = 550
FILING_SOURCES = ("SEC_EDGAR", "DART")
"""공시 원천 출처. 이 밖의 출처(보충) 값으로 주식 수를 쓰면 method 에 @출처 를 적는다."""
QUARTER_GAP = (80, 100)
VALUE_COLS = (
    "ticker",
    "currency",
    "close",
    "split_factor",
    "shares_outstanding",
    "market_cap",
    "net_income_ttm",
    "eps_ttm",
    "per",
    "bps",
    "pbr",
    "roe_ttm",
    "dps_ttm",
    "dividend_yield",
    "fin_period_end",
    "fin_disclosed_at",
    "shares_as_of",
    "method",
)
"""valuation_daily 값 칸 (키·updated_at 제외). 이 칸들이 그대로면 행을 다시 쓰지 않는다."""


def is_annual_period(period: str | None) -> bool:
    """financials.period 가 사업연도 값인가 (SEC FY2025, DART 2025_11011)."""
    p = period or ""
    return p.startswith("FY") or p.endswith("_11011")


# ---------------------------------------------------------------- 분할 계수
class SplitFactor:
    """누적 분할 계수 C(d) = d 이전(포함) 권리락일의 분할 비율 곱."""

    def __init__(self, splits: Iterable[tuple[date, float]]) -> None:
        items = sorted((d, r) for d, r in splits if r and r > 0)
        self.dates = np.array([np.datetime64(d, "D") for d, _ in items], dtype="datetime64[D]")
        self.cum = np.concatenate([[1.0], np.cumprod([r for _, r in items])])

    def at(self, days: Any) -> np.ndarray:
        """날짜 배열(datetime64[D]) → C(d) 배열."""
        idx = np.searchsorted(self.dates, np.asarray(days, dtype="datetime64[D]"), side="right")
        return self.cum[idx]

    def one(self, d: date) -> float:
        return float(self.at(np.array([np.datetime64(d, "D")]))[0])


# ---------------------------------------------------------------- 공시 시점별 상태
def _contiguous_last4(ends: Sequence[date]) -> list[date] | None:
    """정렬된 분기 끝 날짜에서 마지막 4개가 이어진 분기면 그 4개."""
    if len(ends) < 4:
        return None
    last = list(ends[-4:])
    for a, b in zip(last, last[1:], strict=False):
        if not QUARTER_GAP[0] <= (b - a).days <= QUARTER_GAP[1]:
            return None
    return last


@dataclass
class _Snapshot:
    at: date
    ni: float | None = None
    ni_end: date | None = None
    ni_method: str = "-"
    disclosed: date | None = None
    eq: float | None = None
    eq_avg: float | None = None
    eq_end: date | None = None
    shares: float | None = None
    shares_date: date | None = None
    shares_item: str = "-"
    dps: float | None = None  # dps_end 기준 주식 수 기준의 주당배당금
    dps_end: date | None = None
    dps_method: str = "-"
    eps: float | None = None  # eps_end 기준 보고 EPS 합
    eps_end: date | None = None
    eps_cur: float | None = None  # 현재 주식 기준 연간 EPS (KIS_FIN)
    eps_cur_end: date | None = None
    bps_cur: float | None = None
    bps_cur_end: date | None = None
    extra: dict[str, Any] = field(default_factory=dict)


def _series(rows: pd.DataFrame, items: Sequence[str], *, annual: bool | None = None) -> dict:
    """{기간 끝: (값, 공시일)} items 순서대로 앞 항목 우선."""
    out: dict[date, tuple[float, date]] = {}
    for item in items:
        sub = rows[rows["item"] == item]
        if annual is not None:
            sub = sub[sub["period"].map(is_annual_period) == annual]
        for pend, val, rep in zip(sub["period_end"], sub["value"], sub["report_date"], strict=True):
            out.setdefault(pend, (float(val), rep))
    return out


def _source_tag(rows: pd.DataFrame, item: str, pend: date) -> str:
    """보충 출처(FILING_SOURCES 밖) 값이면 "@출처", 아니면 "" (source 칸이 없는 입력도 "")."""
    if "source" not in rows:
        return ""
    src = rows.loc[(rows["item"] == item) & (rows["period_end"] == pend), "source"]
    if src.empty or pd.isna(src.iloc[0]) or src.iloc[0] in FILING_SOURCES:
        return ""
    return f"@{src.iloc[0]}"


def _per_share_ttm(
    q: dict[date, tuple[float, date]], cf: SplitFactor
) -> tuple[float, date, date] | None:
    """분기 주당 값 4개 합 (마지막 분기 끝 기준 주식 수로 맞춤). (값, 마지막 분기 끝, 공시일)."""
    last4 = _contiguous_last4(sorted(q))
    if not last4:
        return None
    base = cf.one(last4[-1])
    total = sum(q[d][0] * cf.one(d) / base for d in last4)
    return total, last4[-1], max(q[d][1] for d in last4)


def snapshot(rows: pd.DataFrame, at: date, cf: SplitFactor) -> _Snapshot:
    """at 까지 공시된(report_date ≤ at) 값으로 만든 상태."""
    vis = rows[rows["report_date"] <= at]
    s = _Snapshot(at=at)
    used: list[date] = []
    # 순이익 TTM
    q = _series(vis, NI_Q_ITEMS)
    fy = _series(vis, NI_FY_ITEMS, annual=True)
    last4 = _contiguous_last4(sorted(q))
    fy_end = max(fy) if fy else None
    if last4 and (fy_end is None or last4[-1] >= fy_end):
        s.ni = sum(q[d][0] for d in last4)
        s.ni_end, s.ni_method = last4[-1], "4Q"
        used += [q[d][1] for d in last4]
    elif fy_end is not None:
        s.ni, s.ni_end, s.ni_method = fy[fy_end][0], fy_end, "FY"
        used.append(fy[fy_end][1])
    # 자본
    eq = _series(vis, (EQUITY_ITEM,))
    if eq:
        end = max(eq)
        s.eq, s.eq_end = eq[end][0], end
        used.append(eq[end][1])
        prev = [d for d in eq if abs((end - d).days - 365) <= 20]
        s.eq_avg = (s.eq + eq[max(prev)][0]) / 2 if prev else s.eq
    s.disclosed = max(used) if used else None
    # 주식 수
    out = _series(vis, (SHARES_OUT,))
    if out:
        d = max(out)
        s.shares, s.shares_date, s.shares_item = out[d][0], d, SHARES_OUT
        s.shares_item += _source_tag(vis, SHARES_OUT, d)
    else:
        issued = _series(vis, (SHARES_ISSUED,))
        treasury = _series(vis, (SHARES_TREASURY,))
        if issued:
            d = max(issued)
            s.shares, s.shares_date, s.shares_item = issued[d][0], d, SHARES_ISSUED
            if d in treasury:
                s.shares -= treasury[d][0]
                s.shares_item = "발행-자기"
    # 주당배당금
    dq = _per_share_ttm(_series(vis, (DPS_Q,)), cf)
    dfy = _series(vis, (DPS_FY,), annual=True)
    dfy_end = max(dfy) if dfy else None
    if dq and (dfy_end is None or dq[1] >= dfy_end):
        s.dps, s.dps_end, s.dps_method = dq[0], dq[1], "4Q"
    elif dfy_end is not None:
        s.dps, s.dps_end, s.dps_method = dfy[dfy_end][0], dfy_end, "FY"
    # 보고 EPS (주식 수가 없을 때 PER 대안)
    eq4 = _per_share_ttm(_series(vis, (EPS_Q,)), cf)
    if eq4:
        s.eps, s.eps_end = eq4[0], eq4[1]
    # 현재 주식 기준 연간 EPS·BPS (KIS_FIN)
    ec = _series(vis, (EPS_CUR,), annual=True)
    if ec:
        d = max(ec)
        s.eps_cur, s.eps_cur_end = ec[d][0], d
    bc = _series(vis, (BPS_CUR,))
    if bc:
        d = max(bc)
        s.bps_cur, s.bps_cur_end = bc[d][0], d
    return s


# ---------------------------------------------------------------- 종목 하나 계산
def _days(values: Iterable[Any]) -> np.ndarray:
    return np.array([np.datetime64(v, "D") if v is not None else "NaT" for v in values],
                    dtype="datetime64[D]")  # fmt: skip


def _fresh(t: np.ndarray, end: np.ndarray) -> np.ndarray:
    age = (t - end).astype("timedelta64[D]").astype("float64")
    return ~np.isnan(age) & (age <= STALE_DAYS)


def _clean(v: Any) -> Any:
    if v is None:
        return None
    if isinstance(v, (float, np.floating)):
        f = float(v)
        return None if math.isnan(f) or math.isinf(f) else f
    if isinstance(v, np.datetime64):
        return None if np.isnat(v) else pd.Timestamp(v).date()
    if isinstance(v, pd.Timestamp):
        return v.date()
    return v


def compute_asset(
    prices: pd.DataFrame,
    fins: pd.DataFrame,
    *,
    asset_id: str,
    ticker: str,
    currency: str,
    start: date | None = None,
) -> list[dict[str, Any]]:
    """종목 하나의 valuation_daily 행 (updated_at 제외).

    prices: date·close·fetched_at (계약 price_daily). fins: item·period_end·period·value·report_date
    (계약 financials, VALUATION_ITEMS 만). start 를 주면 그날 이후 행만.
    """
    if prices.empty:
        return []
    px = prices.sort_values("date")
    if start is not None:
        px = px[px["date"] >= start]
    px = px[px["close"].notna() & (px["close"] > 0)]
    if px.empty:
        return []
    fins = fins.copy() if not fins.empty else fins
    splits = fins[fins["item"] == SPLIT_ITEM] if not fins.empty else fins
    cf = SplitFactor(zip(splits.get("period_end", []), splits.get("value", []), strict=False))
    data = fins[fins["item"] != SPLIT_ITEM] if not fins.empty else fins

    t = _days(px["date"])
    fetched = _days(pd.to_datetime(px["fetched_at"], utc=True).dt.date)
    close = px["close"].astype("float64").to_numpy()
    sf = cf.at(fetched) / cf.at(t)
    raw_close = close * sf
    n = len(px)

    def col(default: float = np.nan) -> np.ndarray:
        return np.full(n, default, dtype="float64")

    ni, eqv, eq_avg, sh, dps, eps = col(), col(), col(), col(), col(), col()
    epsc, bpsc = col(), col()
    ni_end = np.full(n, np.datetime64("NaT", "D"), dtype="datetime64[D]")
    eq_end, sh_date, dps_end, eps_end, discl = (ni_end.copy() for _ in range(5))
    epsc_end, bpsc_end = ni_end.copy(), ni_end.copy()
    methods = np.full(n, "", dtype=object)
    if not data.empty:
        events = sorted(set(data["report_date"]))
        snaps = [snapshot(data, e, cf) for e in events]
        ev_days = _days(events)
        # 각 날짜에 쓸 상태 = 공시일이 그날 이전(포함)인 가장 늦은 상태 (as-of)
        idx = np.searchsorted(ev_days, t, side="right") - 1
        has = idx >= 0
        for k, s in enumerate(snaps):
            m = has & (idx == k)
            if not m.any():
                continue
            ni[m] = np.nan if s.ni is None else s.ni
            ni_end[m] = np.datetime64(s.ni_end, "D") if s.ni_end else np.datetime64("NaT", "D")
            discl[m] = np.datetime64(s.disclosed, "D") if s.disclosed else np.datetime64("NaT", "D")
            eqv[m] = np.nan if s.eq is None else s.eq
            eq_avg[m] = np.nan if s.eq_avg is None else s.eq_avg
            eq_end[m] = np.datetime64(s.eq_end, "D") if s.eq_end else np.datetime64("NaT", "D")
            sh[m] = np.nan if s.shares is None else s.shares
            sh_date[m] = (
                np.datetime64(s.shares_date, "D") if s.shares_date else np.datetime64("NaT", "D")
            )
            dps[m] = np.nan if s.dps is None else s.dps
            dps_end[m] = np.datetime64(s.dps_end, "D") if s.dps_end else np.datetime64("NaT", "D")
            eps[m] = np.nan if s.eps is None else s.eps
            eps_end[m] = np.datetime64(s.eps_end, "D") if s.eps_end else np.datetime64("NaT", "D")
            epsc[m] = np.nan if s.eps_cur is None else s.eps_cur
            epsc_end[m] = (
                np.datetime64(s.eps_cur_end, "D") if s.eps_cur_end else np.datetime64("NaT", "D")
            )
            bpsc[m] = np.nan if s.bps_cur is None else s.bps_cur
            bpsc_end[m] = (
                np.datetime64(s.bps_cur_end, "D") if s.bps_cur_end else np.datetime64("NaT", "D")
            )
            methods[m] = f"NI={s.ni_method};SH={s.shares_item};DPS={s.dps_method}"

    with np.errstate(divide="ignore", invalid="ignore"):
        ni = np.where(_fresh(t, ni_end), ni, np.nan)
        eq_ok = _fresh(t, eq_end)
        eqv = np.where(eq_ok, eqv, np.nan)
        eq_avg = np.where(eq_ok, eq_avg, np.nan)
        sh_ok = _fresh(t, sh_date)
        cf_t = cf.at(t)
        shares_t = np.where(sh_ok, sh * cf_t / cf.at(np.where(sh_ok, sh_date, t)), np.nan)
        mcap = raw_close * shares_t
        eps_raw = ni / shares_t
        per = np.where(ni > 0, mcap / ni, np.nan)
        # 주식 수가 없을 때: 보고 EPS 4분기 합 (미국)
        eps_ok = _fresh(t, eps_end) & np.isnan(shares_t)
        eps_rep = eps * cf.at(np.where(eps_ok, eps_end, t)) / cf_t
        use_rep = eps_ok & ~np.isnan(eps_rep)
        eps_raw = np.where(use_rep, eps_rep, eps_raw)
        per = np.where(use_rep, np.where(eps_rep > 0, raw_close / eps_rep, np.nan), per)
        eps_ttm = eps_raw / sf
        bps = eqv / shares_t / sf
        pbr = np.where(eqv > 0, mcap / eqv, np.nan)
        # 주식 수도 보고 EPS 도 없을 때: 현재 주식 기준 연간 EPS·BPS (KIS_FIN, 한국 2015년 전)
        no_sh = np.isnan(shares_t)
        use_cur = no_sh & ~use_rep & _fresh(t, epsc_end) & ~np.isnan(epsc)
        per = np.where(use_cur, np.where(epsc > 0, close / epsc, np.nan), per)
        eps_ttm = np.where(use_cur, epsc, eps_ttm)
        use_bcur = no_sh & _fresh(t, bpsc_end) & ~np.isnan(bpsc)
        pbr = np.where(use_bcur, np.where(bpsc > 0, close / bpsc, np.nan), pbr)
        bps = np.where(use_bcur, bpsc, bps)
        roe = np.where(eq_avg > 0, ni / eq_avg, np.nan)
        dps_ok = _fresh(t, dps_end)
        dps_raw = np.where(dps_ok, dps * cf.at(np.where(dps_ok, dps_end, t)) / cf_t, np.nan)
        dps_ttm = dps_raw / sf
        yld = dps_raw / raw_close
    out = []
    dates = px["date"].tolist()
    for i in range(n):
        method = methods[i] or "NI=-;SH=-;DPS=-"
        if use_rep[i]:
            method += ";PER=EPS"
        if use_cur[i]:
            method += ";PER=EPS@KIS_FIN"
        if use_bcur[i]:
            method += ";PBR=BPS@KIS_FIN"
        out.append(
            {
                "asset_id": asset_id,
                "date": dates[i],
                "ticker": ticker,
                "currency": currency,
                "close": float(close[i]),
                "split_factor": float(sf[i]),
                "shares_outstanding": _clean(shares_t[i]),
                "market_cap": _clean(mcap[i]),
                "net_income_ttm": _clean(ni[i]),
                "eps_ttm": _clean(eps_ttm[i]),
                "per": _clean(per[i]),
                "bps": _clean(bps[i]),
                "pbr": _clean(pbr[i]),
                "roe_ttm": _clean(roe[i]),
                "dps_ttm": _clean(dps_ttm[i]),
                "dividend_yield": _clean(yld[i]),
                "fin_period_end": _clean(ni_end[i]) if not np.isnan(ni[i]) else None,
                "fin_disclosed_at": _clean(discl[i]) if not np.isnan(ni[i]) else None,
                "shares_as_of": _clean(sh_date[i]) if sh_ok[i] else None,
                "method": method,
            }
        )
    return out


# ---------------------------------------------------------------- 작업
@dataclass
class ValuationResult:
    done: bool = True
    assets: int = 0
    rows: int = 0
    written: int = 0
    notes: list[str] = field(default_factory=list)


def _years_before(d: date, years: int) -> date:
    try:
        return d.replace(year=d.year - years)
    except ValueError:
        return d.replace(year=d.year - years, day=28)


def plan_from_dates(
    assets: Sequence[str],
    *,
    start: date,
    last_valued: dict[str, date],
    last_price: dict[str, date],
    changes: dict[str, date],
    full: bool = False,
) -> dict[str, date]:
    """종목 → 다시 계산할 첫 날. 할 일이 없는 종목은 빠진다.

    full 이면 모두 start 부터. 아니면 마지막 계산일 다음 날과 changes(바뀐 입력의 첫 날) 중 이른 날
    (계산한 적이 없는 종목은 start 부터).
    """
    out: dict[str, date] = {}
    for a in assets:
        if a not in last_price:
            continue
        if full or a not in last_valued:
            out[a] = start
            continue
        frm = last_valued[a] + timedelta(days=1)
        if a in changes:
            frm = min(frm, changes[a])
        frm = max(frm, start)
        if frm <= last_price[a]:
            out[a] = frm
    return out


TARGET = "valuation_daily"


def _change_baseline(repo: Any) -> tuple[datetime | None, datetime | None]:
    """(지난 SUCCESS 의 기준 시각, 그 뒤 끝나지 못한(PARTIAL) 실행 중 가장 이른 시작 시각).

    여러 실행에 걸쳐 끝난 한 바퀴의 기준 시각은 그 바퀴의 첫 실행 시작 시각이어야 그 사이에 바뀐
    입력을 놓치지 않는다.
    """
    since: datetime | None = None
    partial: datetime | None = None
    for r in repo.fetch_history(TARGET):
        if r["source"] != "VALUATION":
            continue
        if r["status"] == "SUCCESS":
            since, partial = r["fetched_at"], None
        elif r["status"] == "PARTIAL" and partial is None:
            partial = r["fetched_at"]
    return since, partial


def valuation_step(
    repo: Any,
    *,
    today: date,
    years: int = 10,
    full: bool = False,
    markets: Sequence[str] | None = None,
    deadline: Any = None,
    chunk: int = 20,
    progress: Callable[[str], None] | None = None,
    now: datetime | None = None,
) -> ValuationResult:
    """valuation_daily 증분(기본) 또는 전체 다시 계산 (full). 값이 바뀐 행만 쓴다.

    fetch_log (source VALUATION, target valuation_daily): 끝까지 하면 SUCCESS, 시간 예산(deadline)
    이 끝나 멈추면 PARTIAL. SUCCESS 의 시각 = 그 바퀴를 시작한 시각 (PARTIAL 로 이어진 경우 첫 실행)
    이고, 다음 증분은 그 뒤에 바뀐 price_daily·financials 행만 다시 계산한다.
    """
    run_at = now or datetime.now(UTC)
    res = ValuationResult()
    start = _years_before(today, years)
    assets = repo.valuation_assets(markets)
    meta = {a["asset_id"]: a for a in assets}
    ids = sorted(meta)
    since, partial = _change_baseline(repo)
    baseline = min(x for x in (run_at, partial) if x is not None)
    changes = repo.valuation_changes(since) if since is not None and not full else {}
    plan = plan_from_dates(
        ids,
        start=start,
        last_valued={} if full else repo.valuation_last_dates(ids),
        last_price=repo.price_last_dates(ids),
        changes=changes,
        full=full,
    )
    todo = sorted(plan)
    for i in range(0, len(todo), chunk):
        if deadline is not None and deadline.over():
            res.done = False
            res.notes.append(
                f"valuation_daily: 시간 예산 끝 ({i}/{len(todo)}종목), 다음 실행이 이어 받음"
            )
            break
        part = todo[i : i + chunk]
        lo = min(plan[a] for a in part)
        prices, fins = repo.valuation_inputs(part, lo)
        rows: list[dict[str, Any]] = []
        for a in part:
            px = prices[prices["asset_id"] == a]
            fx = fins[fins["asset_id"] == a]
            m = meta[a]
            rows += compute_asset(
                px, fx, asset_id=a, ticker=m["ticker"], currency=m["currency"], start=plan[a]
            )
        res.rows += len(rows)
        res.written += repo.upsert_valuation(rows) if rows else 0
        res.assets += len(part)
        if progress:
            progress(
                f"[valuation] {min(i + chunk, len(todo))}/{len(todo)}종목, "
                f"계산 {res.rows:,}행, 바뀐 행 {res.written:,}"
            )
    repo.log_fetch(
        "VALUATION",
        TARGET,
        start,
        today,
        "SUCCESS" if res.done else "PARTIAL",
        baseline if res.done else run_at,
        None if res.done else "시간 예산 끝",
        fetched_count=res.rows,
        inserted_count=res.written,
    )
    return res
