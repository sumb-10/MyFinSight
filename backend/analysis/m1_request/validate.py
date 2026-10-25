"""HARD 검증 (M1-02 ②). Pydantic 오류와 교차 규칙을 필드별 한국어 메시지로. 오류는 질문이 아니라 즉시 수정 대상이다."""

from __future__ import annotations

from typing import Any

import re

from pydantic import ValidationError

from backend.analysis.schemas.dialog import FieldError
from backend.analysis.schemas.request import UserRequest

_MSG = [
    ("min <= target <= max", "종목 수는 최소 ≤ 목표 ≤ 최대 순서여야 합니다"),
    ("cannot sum", "종목당 상한 × 최소 종목 수가 투자 비율(1 − 현금 비율)보다 작아 비중을 채울 수 없습니다. 상한을 올리거나 종목 수를 늘려 주세요"),
    ("max_weight_per_sector must be >=", "섹터당 상한은 종목당 상한 이상이어야 합니다"),
    ("more must_include_tickers", "필수 포함 종목 수가 최대 종목 수를 넘습니다"),
    ("included and excluded", "같은 종목이 필수 포함과 제외에 함께 있습니다"),
    ("not supported", "레버리지·공매도는 지원하지 않습니다"),
    ("Input should be greater than 0", "0 보다 커야 합니다"),
    ("Input should be", "허용되지 않는 값입니다"),
    ("Field required", "필수 항목입니다"),
    ("at least 1 item", "최소 1개 이상 골라야 합니다"),
    ("at least 5 characters", "아이디어를 5자 이상 적어 주세요"),
]

LABELS: dict[str, str] = {
    "capital.initial_amount": "투자금", "capital.currency": "투자금 통화", "capital.monthly_contribution": "월 적립금", "capital.contribution_day": "적립일",
    "horizon.target_years": "투자기간(년)", "horizon.purpose": "투자 목적", "horizon.backtest_years": "백테스트 기간(년)", "horizon.start_date": "분석 기준일",
    "risk.risk_tolerance": "위험 성향", "risk.max_drawdown_tolerance": "손실 감내 수준(최대낙폭)", "risk.loss_reaction": "손실 시 대응", "risk.target_annual_return": "목표 연수익률",
    "risk.benchmark": "비교지수", "constraints.universe": "투자 유니버스", "constraints.asset_types": "자산 유형", "constraints.num_holdings": "종목 수",
    "constraints.num_holdings.target": "목표 종목 수", "constraints.num_holdings.min": "최소 종목 수", "constraints.num_holdings.max": "최대 종목 수",
    "constraints.max_weight_per_stock": "종목당 상한", "constraints.max_weight_per_sector": "섹터당 상한", "constraints.min_cash_ratio": "최소 현금 비율",
    "constraints.exclude_tickers": "제외 종목", "constraints.exclude_sectors": "제외 섹터", "constraints.exclude_themes": "제외 테마",
    "constraints.must_include_tickers": "필수 포함 종목", "constraints.rebalance": "리밸런싱", "constraints.rebalance.count": "리밸런싱 간격(횟수)",
    "constraints.rebalance.unit": "리밸런싱 단위", "constraints.allow_leverage": "레버리지", "constraints.allow_short": "공매도",
    "constraints.min_market_cap_usd": "최소 시가총액(USD)", "constraints.min_avg_daily_volume_usd": "최소 일평균 거래대금(USD)",
    "strategy_preference.template": "선정 기준(템플릿)", "strategy_preference.baseline_weighting": "기준 비중 방식", "strategy_preference.use_news_tilt": "뉴스 반영",
    "natural_language.idea": "투자 아이디어", "profile.age_band": "연령대", "profile.investment_experience": "투자 경험", "profile.financial_knowledge": "금융 지식",
    "profile.investable_ratio_of_assets": "투자 가능 자산 비율",
}  # fmt: skip


_BOUND = re.compile(r"Input should be (less than or equal to|greater than or equal to|less than|greater than) (-?\d+(?:\.\d+)?)")
_RATIO_FIELDS = ("max_drawdown_tolerance", "target_annual_return", "max_weight_per_stock", "max_weight_per_sector", "min_cash_ratio", "investable_ratio_of_assets")
_YEAR_FIELDS = ("target_years", "backtest_years")


def _ko(msg: str, field: str = "") -> str:
    m = _BOUND.match(msg)
    if m:  # 숫자 경계는 필드 단위로 (예: 투자기간 10년 이하, 비율 100% 이하) — '1 이하'가 '10 이하'를 가로채던 문제 수정 (라운드 5)
        kind, num = m.group(1), m.group(2)
        n = float(num)
        if any(field.endswith(f) for f in _RATIO_FIELDS):
            shown = f"{n:.0%}" if n <= 1 else num
        elif any(field.endswith(f) for f in _YEAR_FIELDS):
            shown = f"{n:g}년"
        else:
            shown = f"{n:g}"
        return {"less than or equal to": f"{shown} 이하여야 합니다", "greater than or equal to": f"{shown} 이상이어야 합니다",
                "less than": f"{shown} 보다 작아야 합니다", "greater than": f"{shown} 보다 커야 합니다"}[kind]
    for key, ko in _MSG:
        if key in msg:
            return ko
    return msg


def hard_errors(req: dict[str, Any]) -> list[FieldError]:
    try:
        UserRequest.model_validate(req)
        return []
    except ValidationError as e:
        out: list[FieldError] = []
        seen: set[tuple[str, str]] = set()
        for err in e.errors():
            loc = [str(x) for x in err["loc"]]
            field = ".".join(loc) if loc else "request"
            msg = _ko(err["msg"].replace("Value error, ", ""), field)
            if (field, msg) in seen:
                continue
            seen.add((field, msg))
            out.append(FieldError(field=field, message_ko=f"{LABELS.get(field, field)}: {msg}"))
        return out


def label(field: str) -> str:
    return LABELS.get(field, field)
