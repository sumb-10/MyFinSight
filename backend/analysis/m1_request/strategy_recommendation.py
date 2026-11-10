"""투자성향 → 추천 전략 (GET /strategy/recommendation, 이슈 #14 의 4번).

성향(안정형~공격투자형) 5개마다 정해 둔 고정 규칙이다. 시장 상황·과거 성과는 보지 않는다.
표는 프런트 목업 `Front/src/mocks/data/strategy.ts` 와 같다 — 바꾸면 둘 다 바꾼다 (test_strategy_recommendation 이 확인).
성향은 서버의 3단계 risk_tolerance 가 아니라 프런트 진단의 5단계 값(profile.diagnosis.final_tendency)이다.
"""

from __future__ import annotations

from typing import Any, Literal

Tendency = Literal["안정형", "안정추구형", "위험중립형", "적극투자형", "공격투자형"]

NOTE_KO = "투자성향마다 정해 둔 고정 규칙에 따른 추천입니다. 지금 시장 상황이나 과거 성과를 보고 고른 것은 아닙니다."


def _s(template: str, weighting: str, news: bool, diff_ko: str | None = None) -> dict[str, Any]:
    out: dict[str, Any] = {"template": template, "baseline_weighting": weighting, "use_news_tilt": news}
    if diff_ko is not None:
        out["diff_ko"] = diff_ko
    return out


_TABLE: dict[str, dict[str, Any]] = {
    "안정형": {
        "rec": _s("high_dividend", "min_variance", False),
        "reasons": [
            "손실을 가장 피하고 싶은 성향이라, 배당처럼 꾸준한 현금 흐름이 있는 기업(고배당)을 먼저 고릅니다.",
            "포트폴리오 전체의 오르내림이 가장 작아지도록 투자금을 나눕니다(최소분산).",
            "뉴스로 비중을 바꾸면 변동이 커질 수 있어 반영하지 않습니다.",
        ],
        "alts": [
            _s("low_volatility", "inverse_volatility", False, "배당 대신 주가 변동이 작은 기업을 고릅니다. 배당 수입은 줄 수 있지만 하락장 방어는 비슷합니다."),
            _s("quality", "equal_weight", False, "수익성 좋은 기업에 똑같이 나눕니다. 상승 여력은 크지만 추천안보다 변동이 커집니다."),
        ],
    },
    "안정추구형": {
        "rec": _s("low_volatility", "inverse_volatility", False),
        "reasons": [
            "손실을 줄이는 것을 먼저 보는 성향이라, 주가 변동이 작은 기업(저변동성)을 고릅니다.",
            "변동이 작은 기업에 더 많이 담아(역변동성) 전체 흔들림을 줄입니다.",
            "뉴스 반영은 끄고 기준 비중을 그대로 씁니다.",
        ],
        "alts": [
            _s("high_dividend", "min_variance", False, "배당 많은 기업을 최소분산으로 나눕니다. 더 보수적이지만 기대 수익도 낮아집니다."),
            _s("quality", "equal_weight", True, "수익성 좋은 기업에 똑같이 나누고 뉴스도 반영합니다. 수익 기대는 크지만 낙폭이 커질 수 있습니다."),
        ],
    },
    "위험중립형": {
        "rec": _s("quality", "equal_weight", True),
        "reasons": [
            "수익과 위험을 함께 보는 성향이라, 돈을 잘 버는 기업(퀄리티)을 고릅니다.",
            "한 기업에 쏠리지 않도록 똑같이 나눕니다(동일비중).",
            "뉴스·공시 근거가 있으면 비중을 조금 조정합니다.",
        ],
        "alts": [
            _s("low_volatility", "inverse_volatility", False, "변동이 작은 기업 위주라 덜 흔들리지만, 상승장에서 덜 오를 수 있습니다."),
            _s("momentum", "market_cap", True, "최근 많이 오른 큰 기업 위주라 수익 기대는 크지만 낙폭도 커질 수 있습니다."),
        ],
    },
    "적극투자형": {
        "rec": _s("momentum", "market_cap", True),
        "reasons": [
            "수익을 더 중시하는 성향이라, 최근 주가 상승세가 좋은 기업(모멘텀)을 고릅니다.",
            "규모가 큰 기업에 더 많이 담아(시가총액비중) 지수와 비슷하게 움직이게 합니다.",
            "뉴스·공시 근거로 비중을 조정합니다.",
        ],
        "alts": [
            _s("quality", "equal_weight", True, "수익성 좋은 기업에 똑같이 나눕니다. 추천안보다 덜 흔들리지만 상승 흐름을 덜 따라갑니다."),
            _s("momentum", "equal_weight", True, "같은 기업을 똑같이 나눕니다. 작은 기업 비중이 커져 변동이 더 커질 수 있습니다."),
        ],
    },
    "공격투자형": {
        "rec": _s("momentum", "equal_weight", True),
        "reasons": [
            "높은 수익을 위해 큰 변동도 감수하는 성향이라, 최근 주가 상승세가 좋은 기업(모멘텀)을 고릅니다.",
            "큰 기업에만 쏠리지 않게 똑같이 나눕니다(동일비중).",
            "뉴스·공시 근거로 비중을 조정합니다.",
        ],
        "alts": [
            _s("momentum", "market_cap", True, "같은 기업을 규모에 비례해 나눕니다. 큰 기업 비중이 커져 변동이 조금 줄어듭니다."),
            _s("quality", "equal_weight", True, "수익성 좋은 기업으로 바꿉니다. 상승 흐름은 덜 따라가지만 낙폭이 줄 수 있습니다."),
        ],
    },
}


def recommend(tendency: Tendency) -> dict[str, Any]:
    """프런트 ProposedStrategyRecommendation 모양. 호출한 쪽이 고쳐도 표가 바뀌지 않게 새 dict 로 돌려준다."""
    t = _TABLE[tendency]
    return {
        "tendency": tendency,
        "recommended": dict(t["rec"]),
        "reasons_ko": list(t["reasons"]),
        "alternatives": [dict(a) for a in t["alts"]],
        "note_ko": NOTE_KO,
    }
