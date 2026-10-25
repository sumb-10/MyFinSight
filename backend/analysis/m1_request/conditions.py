"""조건 확인 화면의 표 (ConditionRow). 서버가 라벨·표시값·변경 여부를 만들어 Front 가 필드 사전을 갖지 않게 한다 (Module7 §3)."""

from __future__ import annotations

from typing import Any

from backend.analysis.m1_request.assemble import get_path
from backend.analysis.m1_request.validate import LABELS
from backend.analysis.schemas.dialog import ConditionRow

GROUPS = [
    ("자금", ["capital.initial_amount", "capital.currency", "capital.monthly_contribution", "capital.contribution_day"]),
    ("기간·목적", ["horizon.target_years", "horizon.purpose", "horizon.backtest_years"]),
    ("위험", ["risk.risk_tolerance", "risk.max_drawdown_tolerance", "risk.loss_reaction", "risk.target_annual_return", "risk.benchmark"]),
    ("종목 범위·제약", ["constraints.universe", "constraints.asset_types", "constraints.num_holdings", "constraints.max_weight_per_stock",
                  "constraints.max_weight_per_sector", "constraints.min_cash_ratio", "constraints.exclude_tickers", "constraints.exclude_sectors",
                  "constraints.exclude_themes", "constraints.must_include_tickers", "constraints.min_market_cap_usd", "constraints.min_avg_daily_volume_usd",
                  "constraints.rebalance"]),
    ("전략 선호", ["strategy_preference.template", "strategy_preference.baseline_weighting", "strategy_preference.use_news_tilt"]),
    ("아이디어", ["natural_language.idea"]),
]  # fmt: skip

KO = {
    "KRW": "원", "USD": "달러", "wealth_growth": "자산 증식", "income": "현금흐름(배당)", "capital_preservation": "원금 보존", "retirement": "은퇴 대비",
    "conservative": "안정 추구", "moderate": "중립", "aggressive": "적극", "sell": "매도", "hold": "보유", "buy_more": "추가 매수",
    "low_per": "저PER", "quality": "퀄리티(ROE)", "momentum": "모멘텀", "low_volatility": "저변동성", "high_dividend": "고배당",
    "equal_weight": "동일비중", "market_cap": "시가총액비중", "inverse_volatility": "역변동성", "min_variance": "최소분산",
    "SP500": "S&P 500", "NASDAQ100": "NASDAQ-100", "KOSPI200": "KOSPI 200", "stock": "주식", "etf": "ETF",
    "2w": "2주", "1m": "1개월", "1q": "분기", "6m": "반기", "1y": "1년",
}  # fmt: skip


def fmt(field: str, v: Any, req: dict[str, Any]) -> str:
    if v is None:
        return "—"
    if field == "capital.initial_amount":
        cur = get_path(req, "capital.currency") or "KRW"
        return f"{v:,.0f} {KO.get(cur, cur)}"
    if field == "capital.monthly_contribution":
        cur = get_path(req, "capital.currency") or "KRW"
        return f"{v:,.0f} {KO.get(cur, cur)}" if v else "없음"
    if field == "capital.contribution_day":
        return f"매월 {v}일"
    if field in ("horizon.target_years", "horizon.backtest_years"):
        return f"{v:g}년"
    if field in ("risk.max_drawdown_tolerance", "risk.target_annual_return"):
        return f"{float(v):.1%}"
    if field in ("constraints.max_weight_per_stock", "constraints.max_weight_per_sector", "constraints.min_cash_ratio"):
        return f"{float(v):.0%}"
    if field == "constraints.min_market_cap_usd":
        return "제한 없음" if not v else f"{float(v) / 1e9:,.1f}B USD 이상"
    if field == "constraints.min_avg_daily_volume_usd":
        return "제한 없음" if not v else f"일 {float(v) / 1e6:,.0f}M USD 이상"
    if field == "constraints.num_holdings":
        return f"목표 {v.get('target')}개 (최소 {v.get('min')} ~ 최대 {v.get('max')})"
    if field == "constraints.rebalance":
        return "없음 (매수 후 보유)" if int(v.get("count", 0)) == 0 else f"{v.get('count')}×{KO.get(v.get('unit'), v.get('unit'))}마다"
    if isinstance(v, bool):
        return "예" if v else "아니오"
    if isinstance(v, list):
        return ", ".join(KO.get(str(x), str(x)) for x in v) if v else "없음"
    return KO.get(str(v), str(v))


def condition_rows(req: dict[str, Any], profile_req: dict[str, Any], *, answered_fields: dict[str, int] | None = None,
                   derived: dict[str, Any] | None = None) -> list[ConditionRow]:  # fmt: skip
    """req = 이번 요청, profile_req = 프로필 기본값으로만 만든 요청. answered_fields = {필드: 질문 seq}."""
    answered = answered_fields or {}
    rows: list[ConditionRow] = []
    for group, fields in GROUPS:
        for f in fields:
            v, pv = get_path(req, f), get_path(profile_req, f)
            changed = v != pv
            if f == "natural_language.idea":
                changed = False
            src = "answer" if f in answered or any(k.startswith(f + ".") or f.startswith(k + ".") for k in answered) else ("idea" if changed and f == "natural_language.idea" else ("profile" if not changed else "answer"))
            supported, note = True, None
            if f == "constraints.asset_types" and v and "etf" in v:
                note = "ETF 는 아직 후보에 넣지 않습니다 (주식만 선정). 분석은 그대로 진행됩니다"
            rows.append(ConditionRow(field=f, group_ko=group, label_ko=LABELS.get(f, f), value_ko=fmt(f, v, req), profile_value_ko=fmt(f, pv, profile_req) if changed else None,
                                     changed=changed, source=src, supported=supported, note_ko=note))  # fmt: skip
    try:  # 낙폭 맞춤안 목표가 입력과 다르면(손실 시 매도 ×0.8, 경험 없음 ×0.9) 미리 보여 준다. 검증·표시의 허용 낙폭은 입력값 그대로 (라운드 5)
        from backend.analysis.m3_selection.intent import effective_max_drawdown

        eff, inp = effective_max_drawdown(req), float(get_path(req, "risk.max_drawdown_tolerance") or 0)
        if inp and abs(eff - inp) > 1e-6:
            why = ("손실 시 매도 성향이라 0.8배" if get_path(req, "risk.loss_reaction") == "sell" else "") + (", " if get_path(req, "risk.loss_reaction") == "sell" and get_path(req, "profile.investment_experience") == "none" else "") + ("투자 경험이 없어 0.9배" if get_path(req, "profile.investment_experience") == "none" else "")
            rows.append(ConditionRow(field="derived.effective_max_drawdown", group_ko="위험", label_ko="낙폭 맞춤안 목표", value_ko=f"{eff:.1%} (입력 {inp:.1%} → {why})", source="derived",
                                     note_ko="낙폭 맞춤안(현금을 섞어 과거 최대낙폭을 이 값 안에 맞춘 구성)의 목표입니다. 허용 낙폭 판정과 표시는 입력값 그대로 씁니다"))  # fmt: skip
    except Exception:  # noqa: BLE001
        pass
    if derived:
        rows.append(ConditionRow(field="derived.as_of", group_ko="계산 조건", label_ko="분석 기준일", value_ko=str(derived["as_of"]), source="derived"))
        rows.append(ConditionRow(field="derived.fx_rate", group_ko="계산 조건", label_ko="환율", value_ko=f"1 USD = {derived['fx_rate']:,.2f} KRW ({derived['fx_date']})", source="derived"))
        bt_fx = derived.get("backtest_fx_rate")
        if bt_fx and derived.get("initial_amount_usd_at_backtest_start") is not None and abs(float(bt_fx) - float(derived["fx_rate"])) > 1e-9:
            rows.append(ConditionRow(field="derived.initial_amount_usd", group_ko="계산 조건", label_ko="투자금(USD 환산)",
                                     value_ko=f"백테스트 시작 {derived['initial_amount_usd_at_backtest_start']:,.2f} USD (시작일 {derived['backtest_fx_date']} 환율 {float(bt_fx):,.2f}) · 현재 구성 {derived['initial_amount_usd']:,.2f} USD (기준일 환율)",
                                     source="derived", note_ko="백테스트는 시작일 환율로, 분석 기준일의 현재 구성은 기준일 환율로 환산합니다"))  # fmt: skip
        else:
            rows.append(ConditionRow(field="derived.initial_amount_usd", group_ko="계산 조건", label_ko="투자금(USD 환산)", value_ko=f"{derived['initial_amount_usd']:,.2f} USD", source="derived"))
        rows.append(ConditionRow(field="derived.backtest_window", group_ko="계산 조건", label_ko="백테스트 창", value_ko=f"{derived['backtest_start']} ~ {derived['backtest_end']}", source="derived"))
        rows.append(ConditionRow(field="derived.rebalance_rule", group_ko="계산 조건", label_ko="리밸런싱 규칙", value_ko=derived["rebalance_rule"]["description_ko"], source="derived"))
    return rows
