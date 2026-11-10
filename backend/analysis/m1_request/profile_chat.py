"""대화형 초기 투자조건 (POST /profile/chat …, 이슈 #14 묶음 B 의 1번).

프런트 목업 `Front/src/mocks/data/profileChat.ts` 를 그대로 옮긴 고정 11문항 대화다. 보기·숫자만 받고 자유 문장은 해석하지 않는다 (LLM 없음).
상태는 질문별 답만 저장하고, 말풍선·초안(draft)·다음 질문은 매번 답에서 다시 만든다 → 「고치기」는 그 답(과 그 답에 기대는 답)만 지우면 끝.
응답은 프런트 `ProposedProfileChat` 모양이고, 같은 말풍선은 늘 같은 id 를 가진다 (프런트가 React key 로 쓴다).

묻지 않는 항목의 기본값(DEFAULT_FORM), 성향 진단 문항(DIAGNOSIS), 질문 순서·입력 범위는 프런트
`features/profile/defaults.ts`·`features/profile/diagnosis.ts`·목업 대화와 같다 — 바꾸면 함께 바꾼다 (test_profile_chat 이 확인).
대화는 초안만 만든다. 저장은 기존 PUT /profile 이고, 요약(review)으로 넘어가기 전에 같은 검사를 거친다 (routers/profile.py).
"""

from __future__ import annotations

import copy
import datetime as dt
import math
import re
import secrets
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from typing import Any, Literal, get_args

from backend.analysis.common.store import JsonStore
from backend.analysis.errors import NotFound
from backend.analysis.m1_request.strategy_recommendation import Tendency, recommend

Kind = Literal["choice", "multi", "money", "number"]
TENDENCIES: tuple[str, ...] = get_args(Tendency)

# ───────────────────────── 프런트와 같은 표 ─────────────────────────
# 처음 설정할 때 채워 두는 기본 투자조건 (프런트 features/profile/defaults.ts DEFAULT_FORM).
DEFAULT_FORM: dict[str, Any] = {
    "profile": {"user_id": "default", "age_band": "30s", "investment_experience": "beginner", "financial_knowledge": "basic", "investable_ratio_of_assets": 0.3},
    "capital": {"initial_amount": 10_000_000, "currency": "KRW", "trading_currency": "USD", "monthly_contribution": 0, "contribution_day": 25},
    "horizon": {"target_years": 5, "purpose": "wealth_growth", "backtest_years": 3},
    "risk": {"risk_tolerance": "moderate", "max_drawdown_tolerance": 0.2, "loss_reaction": "hold", "target_annual_return": 0.08, "benchmark": "SPY"},
    "constraints": {
        "universe": ["SP500", "NASDAQ100"], "asset_types": ["stock"], "num_holdings": {"target": 10, "min": 8, "max": 12},
        "max_weight_per_stock": 0.15, "max_weight_per_sector": 0.4, "min_cash_ratio": 0, "exclude_tickers": [], "exclude_sectors": [],
        "exclude_themes": [], "must_include_tickers": [], "rebalance": {"count": 1, "unit": "1q"}, "allow_leverage": False, "allow_short": False,
        "min_market_cap_usd": 0, "min_avg_daily_volume_usd": 0,
    },
    "strategy_preference": {"template": "momentum", "baseline_weighting": "equal_weight", "use_news_tilt": True},
    "diagnosis": {"answers": {}, "computed_tendency": "위험중립형", "final_tendency": "위험중립형", "memo": ""},
    "risk_type_computed": "moderate",
    "risk_type_overridden": False,
}  # fmt: skip

# 성향 진단 3문항 (프런트 features/profile/diagnosis.ts QUESTIONS). loss·reaction 은 손실 감내 수준·손실 시 대응도 함께 정한다.
DIAGNOSIS: list[dict[str, Any]] = [
    {"id": "loss", "question": "과거에 투자금이 일시적으로 하락했을 때 어느 수준까지 감수할 수 있나요?", "options": [
        {"label": "약 5% 하락도 크게 부담됩니다", "score": 0, "loss": 0.05}, {"label": "약 10% 하락까지 감수할 수 있습니다", "score": 1, "loss": 0.1},
        {"label": "약 20% 하락까지 감수할 수 있습니다", "score": 2, "loss": 0.2}, {"label": "약 30% 이상 하락도 장기 관점에서 감수할 수 있습니다", "score": 4, "loss": 0.3}]},
    {"id": "reaction", "question": "시장 급락 시 가장 가까운 행동은 무엇인가요?", "options": [
        {"label": "즉시 대부분 매도합니다", "score": 0, "reaction": "sell"}, {"label": "일부를 줄이고 상황을 지켜봅니다", "score": 1, "reaction": "hold"},
        {"label": "계획을 유지합니다", "score": 2, "reaction": "hold"}, {"label": "추가 매수를 검토합니다", "score": 4, "reaction": "buy_more"}]},
    {"id": "priority", "question": "수익과 안정성 중 더 중요한 것은 무엇인가요?", "options": [
        {"label": "원금 변동 최소화", "score": 0}, {"label": "안정성을 조금 더 중시", "score": 1}, {"label": "균형", "score": 2}, {"label": "높은 변동을 감수한 장기 성장", "score": 4}]},
]  # fmt: skip

TENDENCY_HELP: dict[str, str] = {
    "안정형": "원금 변동을 최소화하려는 성향입니다. 손실 감내 수준과 변동성 기준을 낮게 둡니다.",
    "안정추구형": "작은 손실은 감수하되 안정적인 결과를 선호합니다.",
    "위험중립형": "수익과 안정성의 균형을 추구합니다.",
    "적극투자형": "더 높은 수익을 위해 변동성을 감수합니다.",
    "공격투자형": "큰 변동성과 손실 가능성을 감수하고 장기 성장을 노립니다.",
}

# 화면 문구 (프런트 lib/format.ts KO·features/profile/format.ts UNIVERSE_HELP·features/profile/strategyInfo.ts 와 같은 글).
PURPOSE_KO = {"wealth_growth": "자산 증식", "income": "현금흐름(배당)", "capital_preservation": "원금 보존", "retirement": "은퇴 대비"}
UNIVERSE_KO = {"SP500": "S&P 500", "NASDAQ100": "NASDAQ-100", "KOSPI200": "KOSPI 200"}
UNIVERSE_HELP = {"SP500": "미국 대표 대형주 약 500개", "NASDAQ100": "나스닥 상장 대형 비금융 기업 약 100개 (기술주 비중이 큼)", "KOSPI200": "한국 유가증권시장 대표 기업 200개"}
TEMPLATE_INFO: dict[str, tuple[str, str, str]] = {  # 쉬운 이름, 전문용어, 설명
    "low_per": ("가격이 상대적으로 저평가된 기업", "저PER", "벌어들이는 이익에 비해 주가가 낮은 기업을 고릅니다."),
    "quality": ("수익성이 좋은 기업", "퀄리티", "자기 돈(자기자본)으로 이익을 많이 내는 기업을 고릅니다."),
    "momentum": ("최근 주가 상승세가 좋은 기업", "모멘텀", "최근 1년(가장 최근 한 달 제외) 동안 주가가 상대적으로 많이 오른 기업을 고릅니다."),
    "low_volatility": ("주가 변동이 작은 기업", "저변동성", "최근 주가의 오르내림이 작은 기업을 고릅니다."),
    "high_dividend": ("배당을 많이 주는 기업", "고배당", "주가에 비해 배당을 많이 주는 기업을 고릅니다."),
}
WEIGHTING_INFO: dict[str, tuple[str, str]] = {
    "equal_weight": ("모든 기업에 비슷하게 투자", "동일비중"),
    "market_cap": ("규모가 큰 기업에 더 많이 투자", "시가총액비중"),
    "inverse_volatility": ("주가 변동이 작은 기업에 더 많이 투자", "역변동성"),
    "min_variance": ("전체 투자 위험을 줄이도록 비중 계산", "최소분산"),
}
TEMPLATE_ORDER = ("low_per", "quality", "momentum", "low_volatility", "high_dividend")


def template_label(t: str) -> str:
    i = TEMPLATE_INFO.get(t)
    return f"{i[0]}({i[1]})" if i else t


def weighting_label(w: str) -> str:
    i = WEIGHTING_INFO.get(w)
    return f"{i[0]}({i[1]})" if i else w


def compute_tendency(answers: dict[str, float]) -> str:
    """진단 점수 합 → 5단계 성향 (프런트 computeTendency 와 같은 계산)."""
    return TENDENCIES[min(4, math.floor(sum(answers.values()) / 2.3))]


def to_risk_tolerance(t: str) -> str:
    """5단계 성향 → 서버 3단계 risk_tolerance."""
    if t in ("안정형", "안정추구형"):
        return "conservative"
    return "moderate" if t == "위험중립형" else "aggressive"


# ───────────────────────── 숫자 표시 (프런트 koUnits·money 와 같음) ─────────────────────────
def _num(x: Any) -> bool:
    return isinstance(x, (int, float)) and not isinstance(x, bool)


def _plain(v: float) -> int | float:
    """정수인 실수(5.0)는 정수로 — 말풍선이 「5.0년」이 되지 않게."""
    return int(v) if isinstance(v, float) and v.is_integer() else v


def ko_units(v: float) -> str:
    """억·만 단위로 나눠 쓴다: 123,456,789 → "1억 2,345만 6,789". 정수가 아니면 소수 둘째 자리까지 그대로."""
    if not math.isfinite(v):
        return "–"
    v = _plain(v)
    if isinstance(v, float):
        return f"{v:,.2f}".rstrip("0").rstrip(".")
    n = abs(v)
    eok, man, rest = n // 100_000_000, (n % 100_000_000) // 10_000, n % 10_000
    parts = [f"{eok:,}억" if eok else "", f"{man:,}만" if man else "", f"{rest:,}" if rest else ""]
    return ("-" if v < 0 else "") + (" ".join(p for p in parts if p) or "0")


def won(v: float) -> str:
    return f"{ko_units(v)}원"


def holdings_for(n: int, base: dict[str, Any] | None = None) -> dict[str, Any]:
    """종목 수에 맞춰 범위(±20%)와 종목당 상한을 같이 정한다: 상한 × 최소 종목 수 ≥ 투자 비율이어야 비중을 다 채울 수 있다 (HARD 규칙)."""
    base = base or DEFAULT_FORM["constraints"]
    pad = max(1, math.floor(n * 0.2 + 0.5))  # JS Math.round 와 같게 (0.5 는 올림)
    lo, hi = max(2, n - pad), n + pad
    per_stock = max(base["max_weight_per_stock"], math.ceil((1 - base["min_cash_ratio"]) / lo * 100) / 100)
    return {"num_holdings": {"target": n, "min": lo, "max": hi}, "max_weight_per_stock": per_stock,
            "max_weight_per_sector": max(base["max_weight_per_sector"], per_stock)}  # fmt: skip


# ───────────────────────── 질문 표 ─────────────────────────
@dataclass(frozen=True)
class Question:
    id: str
    label: str  # field_label_ko
    kind: Kind
    fields: Callable[[Any], list[str]]  # 이 답이 정하는 항목 = 요약표 행 키 (프런트 features/profile/compare.tsx profileRows)
    ask: Callable[[dict[str, Any]], str]  # 봇 질문 (그때까지의 답이 반영된 초안을 보고 만든다)
    options: Callable[[dict[str, Any]], list[dict[str, Any]]]
    apply: Callable[[dict[str, Any], Any], None]
    say: Callable[[Any, dict[str, Any]], str]  # 사용자 답 말풍선
    input: dict[str, Any] | None = None  # money·number 의 직접 입력 범위
    allow_skip: bool = False
    # 보기·범위 밖의 규칙: 맞지 않으면 다시 묻는 말. 앞 답을 고쳐 이 답이 맞지 않게 되면 이 답을 지우고 다시 묻는다 (answer_chat)
    check: Callable[[Any, dict[str, Any]], str | None] | None = None


def _fixed(*fields: str) -> Callable[[Any], list[str]]:
    return lambda _v: list(fields)


def _diagnose(d: dict[str, Any]) -> None:
    """성향 진단 점수로 계산한 성향을 초안에 넣는다 (최종 성향은 「성향 확인」 질문에서 정한다)."""
    dg = d["diagnosis"]
    t = compute_tendency(dg["answers"])
    dg["computed_tendency"] = dg["final_tendency"] = t
    d["risk_type_computed"] = d["risk"]["risk_tolerance"] = to_risk_tolerance(t)
    d["risk_type_overridden"] = False


def _diag_question(i: int) -> Question:
    q = DIAGNOSIS[i]

    def apply(d: dict[str, Any], v: Any) -> None:
        o = q["options"][v]
        d["diagnosis"]["answers"][q["id"]] = o["score"]
        if "loss" in o:
            d["risk"]["max_drawdown_tolerance"] = o["loss"]
        if "reaction" in o:
            d["risk"]["loss_reaction"] = o["reaction"]
        _diagnose(d)

    head = f"이제 투자성향을 알아볼게요. 질문 {len(DIAGNOSIS)}개만 답해 주세요.\n" if i == 0 else ""
    fields = {"loss": ["risk.max_drawdown_tolerance"], "reaction": ["risk.loss_reaction"]}.get(q["id"], [])
    return Question(
        id=q["id"], label="투자성향 진단", kind="choice", fields=_fixed(*fields),
        ask=lambda _d: head + q["question"],
        options=lambda _d: [{"value": idx, "label_ko": o["label"]} for idx, o in enumerate(q["options"])],
        apply=apply, say=lambda v, _d: q["options"][v]["label"],
    )  # fmt: skip


def _apply_tendency(d: dict[str, Any], t: Any) -> None:
    dg = d["diagnosis"]
    dg["final_tendency"] = t
    d["risk"]["risk_tolerance"] = to_risk_tolerance(t)
    d["risk_type_overridden"] = t != dg["computed_tendency"]


def _strategy_options(d: dict[str, Any]) -> list[dict[str, Any]]:
    """첫 보기 = 최종 성향의 추천 묶음 (GET /strategy/recommendation 과 같은 고정 규칙), 그다음 기업 고르는 기준 5개."""
    r = recommend(d["diagnosis"]["final_tendency"])
    rec = r["recommended"]
    return [
        {"value": "recommended", "label_ko": f"추천: {template_label(rec['template'])} · {weighting_label(rec['baseline_weighting'])}", "help_ko": r["reasons_ko"][0], "recommended": True},
        *({"value": t, "label_ko": template_label(t), "help_ko": TEMPLATE_INFO[t][2]} for t in TEMPLATE_ORDER),
    ]  # fmt: skip


def _apply_strategy(d: dict[str, Any], v: Any) -> None:
    if v == "recommended":
        rec = recommend(d["diagnosis"]["final_tendency"])["recommended"]
        d["strategy_preference"] = {"template": rec["template"], "baseline_weighting": rec["baseline_weighting"], "use_news_tilt": rec["use_news_tilt"]}
    else:
        d["strategy_preference"] = {**d["strategy_preference"], "template": v}


def _set(block: str, key: str) -> Callable[[dict[str, Any], Any], None]:
    def apply(d: dict[str, Any], v: Any) -> None:
        d[block][key] = v

    return apply


# 처음 투자금 0원 (이슈 #14 의 3번: 첫 적립일에 처음 매수, /meta/options proposed_rules). 목업 profileChat.ts 와 같은 문장
ZERO_START_LABEL = "0원 · 매월 적립으로 시작"
ZERO_START_HELP = "처음 투자금 없이 첫 적립일에 처음 사요. 다음 질문에서 매월 투자금을 꼭 정해 주세요."
ZERO_START_SAY = "0원으로, 매월 적립으로만 시작할게요"
ZERO_MONTHLY_ASK = "처음 투자금 없이 시작하니 매월 추가 투자금이 꼭 있어야 해요."
ZERO_NEEDS_MONTHLY = "처음 투자금이 0원이라 매월 추가 투자금이 꼭 있어야 해요. 0원보다 큰 금액을 골라 주세요."


def _amount_options(_d: dict[str, Any]) -> list[dict[str, Any]]:
    return [{"value": v, "label_ko": won(v)} if v else {"value": 0, "label_ko": ZERO_START_LABEL, "help_ko": ZERO_START_HELP}
            for v in (5_000_000, 10_000_000, 30_000_000, 50_000_000, 0)]  # fmt: skip


def _monthly_ask(d: dict[str, Any]) -> str:
    day = d["capital"]["contribution_day"]
    if d["capital"]["initial_amount"] == 0:
        return f"{ZERO_MONTHLY_ASK} 매월 {day}일에 얼마씩 넣을까요?"
    return f"매월 추가로 투자할 금액이 있나요? 있다면 매월 {day}일에 넣는 것으로 계산해요."


def _monthly_check(v: Any, d: dict[str, Any]) -> str | None:
    return ZERO_NEEDS_MONTHLY if d["capital"]["initial_amount"] == 0 and not (_num(v) and v > 0) else None


def _apply_amount(d: dict[str, Any], v: Any) -> None:
    d["capital"]["initial_amount"] = v
    d["capital"]["currency"] = "KRW"


def _apply_holdings(d: dict[str, Any], v: Any) -> None:
    d["constraints"].update(holdings_for(v, d["constraints"]))


CHAT_QUESTIONS: list[Question] = [
    Question(
        id="purpose", label="투자 목적", kind="choice", fields=_fixed("horizon.purpose"),
        ask=lambda _d: "이번 투자의 목적은 무엇인가요?",
        options=lambda _d: [{"value": v, "label_ko": PURPOSE_KO[v]} for v in PURPOSE_KO],
        apply=_set("horizon", "purpose"), say=lambda v, _d: PURPOSE_KO[v],
    ),
    Question(
        # 직접 입력은 10만원부터 (목업과 같음). 0원(매월 적립으로 시작)은 보기로만 고른다
        id="amount", label="처음 투자할 금액", kind="money", fields=_fixed("capital.initial_amount"),
        ask=lambda _d: "처음에 얼마로 시작할까요? 원화 기준으로 알려 주세요.",
        options=_amount_options,
        input={"min": 100_000, "max": 10_000_000_000, "step": 100_000, "unit_ko": "원"},
        apply=_apply_amount, say=lambda v, _d: won(v) if v else ZERO_START_SAY,
    ),
    Question(
        id="monthly", label="매월 추가 투자금", kind="money", fields=_fixed("capital.monthly"),
        ask=_monthly_ask,
        # 처음 투자금이 0원이면 「추가 투자 없음」 보기를 숨기고, 0원을 보내면 다시 묻는다
        options=lambda d: [{"value": v, "label_ko": f"매월 {won(v)}" if v else "추가 투자 없음"}
                           for v in (0, 300_000, 500_000, 1_000_000) if v > 0 or d["capital"]["initial_amount"] > 0],  # fmt: skip
        input={"min": 0, "max": 100_000_000, "step": 10_000, "unit_ko": "원"},
        apply=_set("capital", "monthly_contribution"), say=lambda v, _d: f"매월 {won(v)}" if v else "추가 투자는 없어요",
        check=_monthly_check,
    ),
    Question(
        id="years", label="투자 기간", kind="number", fields=_fixed("horizon.target_years"),
        ask=lambda _d: "앞으로 몇 년 동안 투자할 계획인가요?",
        options=lambda _d: [{"value": v, "label_ko": f"{v}년"} for v in (1, 3, 5, 10)],
        input={"min": 1, "max": 10, "step": 1, "unit_ko": "년"},
        apply=_set("horizon", "target_years"), say=lambda v, _d: f"{v}년",
    ),
    _diag_question(0), _diag_question(1), _diag_question(2),
    Question(
        id="tendency", label="투자성향", kind="choice", fields=_fixed("tendency"),
        ask=lambda d: (f"답변을 보면 ‘{d['diagnosis']['computed_tendency']}’에 가까워요. {TENDENCY_HELP[d['diagnosis']['computed_tendency']]}\n"
                       "이 성향으로 정할까요? 다른 성향을 고를 수도 있어요."),
        options=lambda d: [{"value": t, "label_ko": f"{t} (진단 결과)" if t == d["diagnosis"]["computed_tendency"] else t, "help_ko": TENDENCY_HELP[t],
                            "recommended": t == d["diagnosis"]["computed_tendency"]} for t in TENDENCIES],
        apply=_apply_tendency, say=lambda v, d: f"좋아요, {v}으로 할게요" if v == d["diagnosis"]["computed_tendency"] else f"{v}으로 할게요",
    ),
    Question(
        id="universe", label="투자 대상 지수", kind="multi", fields=_fixed("constraints.universe"),
        ask=lambda _d: "어느 시장의 종목에서 고를까요? 여러 개 골라도 돼요.",
        options=lambda _d: [{"value": u, "label_ko": UNIVERSE_KO[u], "help_ko": UNIVERSE_HELP[u]} for u in UNIVERSE_KO],
        apply=lambda d, v: d["constraints"].__setitem__("universe", list(v)), say=lambda v, _d: ", ".join(UNIVERSE_KO[u] for u in v),
    ),
    Question(
        id="holdings", label="종목 수", kind="number", fields=_fixed("constraints.num_holdings", "constraints.max_weight"),
        ask=lambda _d: "몇 종목 정도에 나눠 담을까요? 종목이 많을수록 한 종목에 덜 쏠려요.",
        options=lambda _d: [{"value": v, "label_ko": f"{v}개"} for v in (5, 10, 15, 20)],
        input={"min": 3, "max": 30, "step": 1, "unit_ko": "개"},
        apply=_apply_holdings, say=lambda v, _d: f"{v}개 정도요",
    ),
    Question(
        id="strategy", label="종목을 고르는 기준", kind="choice",
        fields=lambda v: ["strategy.template", "strategy.weighting", "strategy.news"] if v == "recommended" else ["strategy.template"],
        ask=lambda d: f"마지막으로 종목을 고르는 기준을 정해요. ‘{d['diagnosis']['final_tendency']}’ 성향이면 첫 번째 추천을 먼저 권해요.",
        options=_strategy_options, apply=_apply_strategy,
        say=lambda v, d: f"추천대로 할게요 ({template_label(d['strategy_preference']['template'])})" if v == "recommended" else template_label(v),
    ),
]  # fmt: skip

QUESTION_IDS = tuple(q.id for q in CHAT_QUESTIONS)
_BY_ID = {q.id: q for q in CHAT_QUESTIONS}

# 고친 답에 기대는 질문: 성향 진단 답이 바뀌면 진단 결과가 바뀌므로 「성향 확인」도 다시 묻는다.
# (종목 기준의 「추천」은 성향에서 매번 다시 계산하므로 지우지 않는다.)
DEPENDENTS: dict[str, list[str]] = {q["id"]: ["tendency"] for q in DIAGNOSIS}

GREETING = "안녕하세요! 몇 가지만 여쭤보고 기본 투자조건을 만들어 드릴게요. 답하신 내용은 마지막에 한 번에 확인하고 저장해요."
DONE_TEXT = "필요한 내용을 모두 들었어요. 아래 요약을 확인하고 저장해 주세요. 나머지 조건은 기본값으로 두었고, 저장한 뒤 언제든 바꿀 수 있어요."


# ───────────────────────── 대화 규칙 ─────────────────────────
# 상태 = {"chat_id", "answers": {질문 id: {"v": 값} | {"skip": True}}, "error": {"question_id", "text_ko"} | None, ...저장 정보}


def current_question(st: dict[str, Any]) -> Question | None:
    """지금 답할 질문 (다 답했으면 None)."""
    return next((q for q in CHAT_QUESTIONS if q.id not in st["answers"]), None)


def chat_view(st: dict[str, Any]) -> dict[str, Any]:
    """답에서 말풍선·초안·다음 질문을 만든다 (프런트 ProposedProfileChat).

    말풍선은 처음으로 답이 비어 있는 질문까지만 보인다. 그 뒤에 이미 답한 질문(「고치기」로 앞 답만 지운 경우)은
    말풍선은 숨기되 초안에는 반영해 두고, 지금 질문에 답하면 다시 나타난다 → 고친 뒤 나머지를 다시 답할 필요가 없다."""
    answers = st["answers"]
    draft = copy.deepcopy(DEFAULT_FORM)
    messages: list[dict[str, Any]] = [{"id": "hello", "role": "bot", "text_ko": GREETING}]
    asked: dict[str, None] = {}  # 순서 있는 집합
    current: Question | None = None
    question: dict[str, Any] | None = None
    for q in CHAT_QUESTIONS:
        a = answers.get(q.id)
        if current is None:
            messages.append({"id": f"{q.id}:q", "role": "bot", "text_ko": q.ask(draft), "question_id": q.id})
        if a is None:
            if current is None:
                current = q
                question = {"id": q.id, "field_label_ko": q.label, "kind": q.kind, "options": q.options(draft),
                            "input": dict(q.input) if q.input else None, "allow_skip": q.allow_skip}  # fmt: skip
            continue
        skipped = bool(a.get("skip"))
        if not skipped:
            q.apply(draft, a["v"])
            asked.update(dict.fromkeys(q.fields(a["v"])))
        if current is None:
            text = "건너뛸게요 (기본값 사용)" if skipped else q.say(a["v"], draft)
            messages.append({"id": f"{q.id}:a", "role": "user", "text_ko": text, "question_id": q.id, "editable": True})
    if current is not None:
        later = sum(1 for q in CHAT_QUESTIONS[CHAT_QUESTIONS.index(current) + 1 :] if q.id in answers)
        if later:
            messages.append({"id": f"{current.id}:keep", "role": "bot", "question_id": current.id,
                             "text_ko": f"이 질문만 다시 답해 주세요. 뒤에 답한 {later}개는 그대로 두었다가 답하시면 다시 보여 드릴게요."})  # fmt: skip
        err = st.get("error")
        if err and err.get("question_id") == current.id:
            messages.append({"id": f"{current.id}:retry", "role": "bot", "text_ko": err["text_ko"], "question_id": current.id})
    else:
        messages.append({"id": "done", "role": "bot", "text_ko": DONE_TEXT})
    done = sum(1 for q in CHAT_QUESTIONS if q.id in answers)
    return {"chat_id": st["chat_id"], "state": "asking" if current else "review", "messages": messages, "question": question,
            "progress": {"done": done, "total": len(CHAT_QUESTIONS)}, "draft": draft, "asked_fields": list(asked)}  # fmt: skip


def _same(a: Any, b: Any) -> bool:
    """보기 값 비교 (JS === 처럼: 1 과 True 는 다르고, 1 과 1.0 은 같다)."""
    if _num(a) and _num(b):
        return a == b
    return type(a) is type(b) and a == b


def _pick(v: Any, values: list[Any]) -> tuple[bool, Any]:
    for x in values:
        if _same(v, x):
            return True, x
    return False, None


def answer_chat(st: dict[str, Any], answer: dict[str, Any], *, check: Callable[[dict[str, Any]], list[str]] | None = None) -> dict[str, Any]:
    """지금 질문에 답한 새 상태. 맞지 않는 값이면 답을 저장하지 않고 다시 묻는 안내(error)를 남긴다 (400 이 아니라 봇 말풍선).
    질문 ID 확인(지금 질문이 아니면 409)은 부르는 쪽이 한다.

    check: 마지막 질문까지 답해 요약(review)으로 넘어가기 전에 초안을 검사하는 함수 (PUT /profile 과 같은 검사, 오류 문장 목록).
    오류가 있으면 이 답을 저장하지 않고 오류를 말풍선으로 보여 준다 → 대화로 만든 초안이 저장 때 거절되지 않는다."""
    q = current_question(st)
    assert q is not None, "답할 질문이 없다 (부르는 쪽이 409 로 막는다)"
    nxt = copy.deepcopy(st)

    def retry(text_ko: str) -> dict[str, Any]:
        return {**nxt, "error": {"question_id": q.id, "text_ko": text_ko}}

    def accept(stored: dict[str, Any]) -> dict[str, Any]:
        return {**nxt, "answers": {**nxt["answers"], q.id: stored}, "error": None}

    if answer.get("skip"):
        return accept({"skip": True}) if q.allow_skip else retry("이 질문은 꼭 답해 주셔야 해요. 아래에서 골라 주세요.")
    v = answer.get("number") if answer.get("number") is not None else answer.get("option_value")
    values = [o["value"] for o in chat_view(st)["question"]["options"]]  # 그 질문 시점의 보기 (앞 답으로 정해진다)
    if q.kind == "choice":
        ok, v = _pick(v, values)
        if not ok:
            return retry("아래 보기 중에서 골라 주세요.")
    if q.kind == "multi":
        picked = [_pick(x, values) for x in v] if isinstance(v, list) else []
        if not picked or not all(ok for ok, _ in picked):
            return retry("하나 이상 골라 주세요.")
        v = list(dict.fromkeys(x for _, x in picked))  # 같은 보기를 두 번 보내도 한 번만 (저장 스키마는 중복을 받지 않는다)
    if q.kind in ("money", "number") and q.input and not _pick(v, values)[0]:  # 보기로 고른 값은 범위 검사 없이 (금액의 0원 보기)
        lo, hi, unit = q.input["min"], q.input["max"], q.input["unit_ko"]

        def fmt(n: float) -> str:
            return won(n) if unit == "원" else f"{n}{unit}"

        if not _num(v) or not math.isfinite(v) or v < lo or v > hi:
            return retry(f"{fmt(lo)} 이상 {fmt(hi)} 이하로 알려 주세요.")
        if unit != "원" and not float(v).is_integer():
            return retry("정수로 알려 주세요.")
        v = _plain(v)
    bad = q.check(v, chat_view(st)["draft"]) if q.check else None
    if bad:
        return retry(bad)
    out = accept({"v": v})
    # 고친 답 때문에 뒤에 이미 답한 값이 규칙에 맞지 않게 되면(금액을 0원으로 고쳤는데 월 적립이 0원) 그 답만 지워 다시 묻는다
    draft = chat_view(out)["draft"]
    for q2 in CHAT_QUESTIONS:
        a2 = out["answers"].get(q2.id)
        if q2.check and a2 and "skip" not in a2 and q2.check(a2["v"], draft):
            del out["answers"][q2.id]
    if check is not None and current_question(out) is None:
        errs = check(chat_view(out)["draft"])
        if errs:
            return retry(f"이 답으로는 투자조건을 저장할 수 없어요. {' / '.join(errs)}. 다른 값을 고르거나 앞의 답을 고쳐 주세요.")
    return out


def rewind_chat(st: dict[str, Any], question_id: str) -> dict[str, Any]:
    """그 질문만 다시 묻는다 (그 답과 그 답에 기대는 답만 지우고, 나머지 답은 그대로 둔다)."""
    drop = {question_id, *DEPENDENTS.get(question_id, [])}
    return {**st, "answers": {k: v for k, v in st["answers"].items() if k not in drop}, "error": None}


# ───────────────────────── 보관 (로컬 저장소) ─────────────────────────
KEEP_DAYS = 7
_ID = re.compile(r"chat_\d{8}_\d{6}_[0-9a-f]{6}")


def _now() -> dt.datetime:
    return dt.datetime.now(dt.UTC)


class ProfileChatStore:
    """profile_chats/<chat_id>.json — 대화마다 답만 저장한다. 단일 사용자("default").

    대화 API 는 저장(PUT /profile)을 모르므로 대화는 늘 초안이다. 새 대화를 시작할 때 마지막으로 답한 지 7일이 지난 대화를 지운다.
    여러 대화를 동시에 둘 수 있다 (다른 탭·「처음부터 다시」). 쓰기는 `locked()` 안에서만."""

    DIR = "profile_chats"

    def __init__(self, store: JsonStore) -> None:
        self.store = store

    def rel(self, chat_id: str) -> str:
        return f"{self.DIR}/{chat_id}.json"

    @contextmanager
    def locked(self) -> Iterator[None]:
        with self.store.locked("profile_chats"):
            yield

    def load(self, chat_id: str) -> dict[str, Any]:
        raw = self.store.read(self.rel(chat_id)) if _ID.fullmatch(chat_id) else None  # 형식이 다른 id 로 다른 파일을 읽지 않게
        if raw is None:
            raise NotFound(f"대화 {chat_id} 이 없습니다. 오래된 대화는 {KEEP_DAYS}일 뒤 지웁니다")
        return raw

    def save(self, st: dict[str, Any], *, now: dt.datetime | None = None) -> dict[str, Any]:
        st = {**st, "updated_at": (now or _now()).isoformat(timespec="seconds")}
        self.store.write(self.rel(st["chat_id"]), st)
        return st

    def start(self, *, now: dt.datetime | None = None) -> dict[str, Any]:
        """새 대화 (오래된 대화를 먼저 지운다)."""
        now = now or _now()
        with self.locked():
            self.prune(now)
            while True:
                chat_id = f"chat_{now:%Y%m%d_%H%M%S}_{secrets.token_hex(3)}"
                if not self.store.path(self.rel(chat_id)).exists():
                    break
            st = {"schema_version": 1, "chat_id": chat_id, "user_id": "default", "created_at": now.isoformat(timespec="seconds"), "answers": {}, "error": None}
            return self.save(st, now=now)

    def prune(self, now: dt.datetime) -> list[str]:
        """마지막으로 답한 지 KEEP_DAYS 일이 지난 대화를 지운다 (지운 id 목록). 읽을 수 없는 파일은 건드리지 않는다."""
        d = self.store.path(self.DIR)
        if not d.exists():
            return []
        cutoff, gone = now - dt.timedelta(days=KEEP_DAYS), []
        for p in sorted(d.glob("chat_*.json")):
            try:
                updated = dt.datetime.fromisoformat(self.store.read(f"{self.DIR}/{p.name}")["updated_at"])
            except Exception:  # noqa: BLE001
                continue
            if updated < cutoff:
                p.unlink(missing_ok=True)
                gone.append(p.stem)
        return gone
