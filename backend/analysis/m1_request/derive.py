"""요청의 파생값 (stage1 포팅): 기준일, 환율·USD 환산, 리밸런싱 규칙, 자료 범위, 백테스트 창.

기준일 as_of = DB 에서 쓸 수 있는 최신 완료 거래일 (혼합 시장이면 두 시장 모두 완료된 날). 요청에 start_date 가 있으면
그 날짜(≤ 상한)를 쓴다 (과거 기준일 재현). 환율은 DB fx_daily (외부 호출 없음).
"""

from __future__ import annotations

import datetime as dt
from typing import Any

from backend.analysis.errors import DataMissing, RequestInvalid
from backend.analysis.m2_data.market_data import MarketData
from backend.analysis.schemas.request import UNIVERSE_MARKET, Derived, NormalizedRequest, RebalanceRule, UserRequest
from backend.analysis.settings import AnalysisSettings

TEMPLATE_KO = {"low_per": "저PER", "quality": "퀄리티(ROE)", "momentum": "모멘텀", "low_volatility": "저변동성", "high_dividend": "고배당"}

UNIT_MONTHS = {"1m": 1, "1q": 3, "6m": 6, "1y": 12}
CALENDAR = {"1m": "month_start", "1q": "quarter_start", "6m": "half_year_start", "1y": "year_start"}


def rebalance_rule(rb: dict[str, Any], settings: AnalysisSettings) -> RebalanceRule:
    count, unit = int(rb["count"]), rb["unit"]
    if count == 0:
        return RebalanceRule(count=0, unit=unit, enabled=False, description_ko="리밸런싱 없음 (매수 후 보유, 적립금은 목표 비중대로 투자)")
    if unit == "2w":
        td = settings.backtest.rebalance_trading_days["2w"] * count
        return RebalanceRule(count=count, unit=unit, enabled=True, trading_days=td, description_ko=f"{td}거래일(약 {2 * count}주)마다 리밸런싱")
    months = UNIT_MONTHS[unit] * count
    label = {1: "매월", 3: "분기마다", 6: "반기마다", 12: "매년"}.get(months, f"{months}개월마다")
    return RebalanceRule(count=count, unit=unit, enabled=True, calendar=CALENDAR[unit], description_ko=f"{label} 첫 거래일에 목표 비중으로 리밸런싱")


def derive(req: UserRequest | dict[str, Any], md: MarketData, settings: AnalysisSettings, *, as_of: dt.date | None = None) -> NormalizedRequest:
    r = UserRequest.model_validate(req) if not isinstance(req, UserRequest) else req
    markets = sorted({UNIVERSE_MARKET[u] for u in r.constraints.universe})
    ceiling = md.latest_trading_day(markets)
    as_of = as_of or r.horizon.start_date or ceiling
    if as_of > ceiling:
        raise RequestInvalid(f"기준일 {as_of} 의 자료가 아직 없습니다 (최신 완료 거래일 {ceiling})",
                             details={"fields": {"horizon.start_date": f"최신 완료 거래일 {ceiling} 이하여야 합니다"}})  # fmt: skip
    data_start, _data_end = md.data_range(markets)
    warnings: list[str] = []
    common = md.common_trading_day_on_or_before(as_of, markets)
    if common != as_of:
        warnings.append(f"기준일 {as_of} 은 일부 시장({', '.join(markets)})의 휴장일이라 모두 거래한 {common} 로 옮김")
        as_of = common
    view = md.view(as_of)
    fx = view.fx_on_or_before(as_of)
    if r.capital.currency == "USD":
        rate, fx_date, fx_src = 1.0, as_of, "none"
    else:
        rate, fx_date, fx_src = float(fx.rate), fx.date, f"fx_daily:{fx.source}"
    bt_start = as_of - dt.timedelta(days=int(round(r.horizon.backtest_years * 365.25)))
    min_start = data_start + dt.timedelta(days=int(settings.portfolio.lookback_days * 1.45))
    if bt_start < min_start:
        warnings.append(f"백테스트 시작일 {bt_start} 을 자료 범위에 맞춰 {min_start} 로 줄임 (공분산 추정 창 {settings.portfolio.lookback_days}거래일 필요)")
        bt_start = min_start
    tpl = r.strategy_preference.template
    req_start, vmsg = bt_start, None  # 두 규칙(재무 지표·시가총액 자료)이 다 옮기면 공지는 마지막 규칙 하나로 (기간 메모가 앞 규칙을 이유로 보였다)
    if tpl in settings.market.valuation_templates:
        starts = [dt.date.fromisoformat(settings.market.valuation_data_start[m]) for m in markets if m in settings.market.valuation_data_start]
        vstart = max(starts) if starts else None
        if vstart and as_of < vstart:
            raise RequestInvalid(f"{TEMPLATE_KO.get(tpl, tpl)} 선정에 쓰는 재무 지표 자료가 {vstart} 부터 있어 기준일 {as_of} 로는 분석할 수 없습니다",
                                 details={"fields": {"horizon.start_date": f"{vstart} 이후 날짜"}})  # fmt: skip
        if vstart and bt_start < vstart:
            vmsg = f"{TEMPLATE_KO.get(tpl, tpl)} 선정에 쓰는 재무 지표 자료가 {vstart} 부터 있어 백테스트 시작을 {bt_start} → {vstart} 로 옮김"
            warnings.append(vmsg)
            bt_start = vstart
    # 최소 시가총액은 하드 조건이라(정책 결정 7) 시가총액 자료가 없는 날에는 모든 종목이 빠진다 → 재무 지표 자료와 같은 규칙으로 시작을 옮긴다
    if (r.constraints.min_market_cap_usd or 0) > 0:
        mstarts = [dt.date.fromisoformat(settings.market.mcap_data_start[m]) for m in markets if m in settings.market.mcap_data_start]
        mstart = max(mstarts) if mstarts else None
        if mstart and as_of < mstart:
            raise RequestInvalid(f"최소 시가총액 조건에 쓰는 시가총액 자료가 {mstart} 부터 있어 기준일 {as_of} 로는 분석할 수 없습니다",
                                 details={"fields": {"horizon.start_date": f"{mstart} 이후 날짜"}})  # fmt: skip
        if mstart and bt_start < mstart:
            if vmsg:
                warnings.remove(vmsg)
            warnings.append(f"최소 시가총액 조건에 쓰는 시가총액 자료가 {mstart} 부터 있어 백테스트 시작을 {req_start} → {mstart} 로 옮김")
            bt_start = mstart
    if bt_start >= as_of:
        raise DataMissing(f"백테스트 창을 만들 수 없음: 시작 {bt_start} ≥ 기준일 {as_of}")
    # 백테스트 시작일 환율: 과거 시점의 투자금은 그날 환율로 환산한다 (07 단계가 실제로 쓰는 값과 같은 규칙)
    bt_rate, bt_fx_date = 1.0, bt_start
    if r.capital.currency != "USD":
        # 07 과 같은 날: 창의 첫 거래일(bt_start 이후). 예전에는 bt_start 가 주말·휴장일이면 '직전 거래일 시점' 에서 bt_start 환율을
        # 찾다가 선견 금지 오류가 나고, 조용히 기준일 환율로 떨어져 조건 확인 화면·01_request 의 USD 환산액이 실제 백테스트와 달랐다.
        try:
            cal = view.trading_days(bt_start, as_of, markets=markets)
            d0 = cal[0].date() if len(cal) else bt_start
            bfx = md.view(d0).fx_on_or_before(d0)
            bt_rate, bt_fx_date = float(bfx.rate), bfx.date
        except Exception:  # noqa: BLE001 — 환율 자료가 없으면 화면 환산만 기준일 환율로 (07 단계가 시작일 환율로 다시 환산하거나 멈춘다)
            warnings.append(f"백테스트 시작일({bt_start}) 환율 자료가 없어 화면의 USD 환산은 기준일 환율로 보여 줍니다. 이 기간은 백테스트를 할 수 없을 수 있습니다")
            bt_rate, bt_fx_date = rate, fx_date
    derived = Derived(
        as_of=as_of, fx_rate=rate, fx_date=fx_date, fx_source=fx_src,
        initial_amount_usd=round(r.capital.initial_amount / rate, 2), monthly_contribution_usd=round(r.capital.monthly_contribution / rate, 2),
        rebalance_rule=rebalance_rule(r.constraints.rebalance.model_dump(), settings),
        price_data_start=data_start, price_data_end=ceiling, backtest_start=bt_start, backtest_end=as_of, markets=markets, warnings=warnings,
        backtest_fx_rate=bt_rate, backtest_fx_date=bt_fx_date,
        initial_amount_usd_at_backtest_start=round(r.capital.initial_amount / bt_rate, 2),
        monthly_contribution_usd_at_backtest_start=round(r.capital.monthly_contribution / bt_rate, 2),
    )  # fmt: skip
    body = r.model_dump(mode="json")
    body["horizon"]["start_date"] = as_of.isoformat()
    return NormalizedRequest.model_validate({**body, "derived": derived.model_dump(mode="json")})
