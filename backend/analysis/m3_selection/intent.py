"""M3-01 의도 해석기 (LLM #1). 요청 + GICS 트리 → IntentSpec (테마→GICS 코드·키워드, SOFT 해석, 보충 질문 제안).

LLM 은 종목을 고르지 않는다. 코드가 GICS 코드·예시 티커를 검증하고 screen/news_tilt 값을 강제한다.
대화 이력(messages)을 그대로 이어 보내므로 같은 프로필·아이디어·답이면 같은 결과가 나온다 (캐시 키 = 전체 대화).
"""

from __future__ import annotations

import json
from collections.abc import Sequence
from typing import Any

from backend.analysis.common.labels import THEME_KO
from backend.analysis.common.llm import LlmClient, Message
from backend.analysis.common.prompts import load_prompts
from backend.analysis.m2_data import descriptor as D
from backend.analysis.schemas.intent import IntentSpec
from backend.analysis.schemas.request import TEMPLATE_METRICS
from backend.analysis.settings import AnalysisSettings
from backend.pipeline.descriptor import Descriptor

STAGE = "02_intent"

# 요청 블록별 [HARD]/[SOFT] 표시 (프롬프트에 JSON 과 함께 보여 준다)
FIELD_TAGS: dict[str, str] = {
    "profile.age_band": "SOFT", "profile.investment_experience": "SOFT", "profile.financial_knowledge": "SOFT",
    "profile.investable_ratio_of_assets": "SOFT",
    "capital.initial_amount": "HARD", "capital.monthly_contribution": "HARD", "capital.contribution_day": "HARD",
    "horizon.start_date": "HARD (분석 기준일)", "horizon.target_years": "SOFT", "horizon.purpose": "SOFT", "horizon.backtest_years": "HARD",
    "risk.risk_tolerance": "SOFT", "risk.max_drawdown_tolerance": "HARD", "risk.loss_reaction": "SOFT",
    "risk.target_annual_return": "SOFT", "risk.benchmark": "HARD",
    "constraints.*": "HARD (모두)",
    "strategy_preference.template": "HARD", "strategy_preference.baseline_weighting": "HARD", "strategy_preference.use_news_tilt": "HARD",
    "natural_language.idea": "자연어 (해석 대상)",
}  # fmt: skip


# 프로필에서 온 값(이번 요청에서 사용자가 직접 바꾸지 않은 값)은 기본값이다: 아이디어와 다르면 질문해서 사용자가 고르게 한다.
PROFILE_DEFAULT_FIELDS = ("constraints.universe", "constraints.num_holdings.target", "constraints.exclude_sectors", "constraints.exclude_themes",
                          "constraints.exclude_tickers", "constraints.must_include_tickers", "constraints.rebalance", "constraints.max_weight_per_stock",
                          "constraints.max_weight_per_sector", "constraints.min_cash_ratio", "strategy_preference.template",
                          "strategy_preference.baseline_weighting", "strategy_preference.use_news_tilt", "risk.benchmark", "horizon.backtest_years")  # fmt: skip


# 제외 테마 → 테마와 정확히 같은 GICS 세부 업종. 03 은 GICS 코드로 그 업종 전체를 하드 제외하므로 이 밖의 코드는 버리고 키워드·04 판정으로만 거른다.
# 빈 튜플 = 맞는 세부 업종이 없어 키워드로만 (013: '성인 산업' 을 영화·엔터테인먼트(50202010)·인터랙티브 미디어(50203010) 전체로 옮겨 DIS·GOOGL·META·NFLX 가
# '성인 산업' 으로 빠졌다. 017 은 '도박' 에도 같은 두 업종을 붙였다). 표에 없는 테마(화석연료·에너지 등)는 LLM 코드를 그대로 쓴다.
EXCLUDE_THEME_GICS: dict[str, tuple[str, ...]] = {
    "adult_entertainment": (), "cannabis": (), "crypto": (), "animal_testing": (), "fur": (), "nuclear": (),
    "tobacco": ("30203010",), "gambling": ("25301010",), "alcohol": ("30201010", "30201020"), "weapons": ("20101010",), "defense": ("20101010",),
}  # fmt: skip
# 규칙 이름이 조금 달라도('adult content'·'성인 산업'·'tobacco_products'·'casinos') 같은 표를 쓴다: 이름 낱말 하나(표의 키 자체 포함) → 표의 키
_EXCLUDE_THEME_WORDS: dict[str, str] = {
    "adult": "adult_entertainment", "porn": "adult_entertainment", "pornography": "adult_entertainment", "성인": "adult_entertainment",
    "marijuana": "cannabis", "대마": "cannabis", "cryptocurrency": "crypto", "가상자산": "crypto", "암호화폐": "crypto", "모피": "fur", "원전": "nuclear",
    "원자력": "nuclear", "담배": "tobacco", "cigarette": "tobacco", "cigarettes": "tobacco", "casino": "gambling", "casinos": "gambling", "도박": "gambling",
    "alcoholic": "alcohol", "liquor": "alcohol", "주류": "alcohol", "무기": "weapons", "weapon": "weapons", "firearms": "weapons", "방산": "defense",
}  # fmt: skip


def exclude_theme_key(theme: Any) -> str | None:
    """제외 규칙 이름 → EXCLUDE_THEME_GICS 의 키 (id 그대로 → 한국어 이름(labels.THEME_KO) → 이름 낱말 순). 모르면 None = LLM 코드 그대로."""
    t = str(theme or "").strip().lower().replace("-", "_").replace(" ", "_")
    ko = {v.replace(" ", "_"): k for k, v in THEME_KO.items()}
    words = (w if w in EXCLUDE_THEME_GICS else _EXCLUDE_THEME_WORDS.get(w) for w in t.split("_"))
    return next((c for c in (t, ko.get(t), *words) if c in EXCLUDE_THEME_GICS), None)


def clean_exclude_rules(rules: list[dict[str, Any]]) -> list[str]:
    """제외 규칙의 GICS 코드를 테마와 정확히 같은 세부 업종만 남긴다 (제자리에서 고침, 바꾼 것을 돌려준다). 같은 규칙이면 다시 해도 그대로.
    해석(interpret)과 실행 단계가 같이 쓴다: 실행은 대화에서 확정된 의도를 다시 쓰므로, 예전 규칙으로 만든 의도도 여기서 정리된다 (013 다시 돌리기)."""
    warns: list[str] = []
    for r in rules or []:
        key, codes = exclude_theme_key(r.get("theme")), list(r.get("gics_codes") or [])
        out = [c for c in codes if key is not None and c not in EXCLUDE_THEME_GICS[key]]
        if out:  # 테마 업종을 덮는 상위 코드는 그 업종만 남긴다 (예: 도박 '253010' → '25301010'). 맞는 업종이 없으면 키워드로만
            allowed = EXCLUDE_THEME_GICS[key]
            r["gics_codes"] = sorted(a for a in allowed if any(a.startswith(c) for c in codes))
            warns.append(f"exclude theme {r.get('theme')}: GICS codes {out} dropped "
                         + (f"(only {list(allowed)} match the theme; kept {r['gics_codes']})" if allowed else "(no matching GICS sub-industry)"))  # fmt: skip
    return warns


def field_tags(explicit_fields: Sequence[str] = ()) -> dict[str, str]:
    """필드 태그: 사용자가 이번 요청에서 직접 정한 값은 [HARD(이번 입력)], 프로필에서 그대로 온 값은 [PROFILE 기본값]."""
    exp = set(explicit_fields)

    def is_explicit(f: str) -> bool:
        return any(e == f or e.startswith(f + ".") or f.startswith(e + ".") for e in exp)

    tags = dict(FIELD_TAGS)
    tags.pop("constraints.*", None)
    for f in PROFILE_DEFAULT_FIELDS:
        tags[f] = "HARD (이번 입력)" if is_explicit(f) else "PROFILE 기본값 — 아이디어와 다르면 conflict 질문"
    tags["constraints.(그 외)"] = "HARD (모두)"
    return tags


def request_text(req: dict[str, Any], explicit_fields: Sequence[str] = ()) -> str:
    """LLM 에 보여 줄 요청 본문: JSON + 필드 태그 범례."""
    body = {k: req[k] for k in ("profile", "capital", "horizon", "risk", "constraints", "strategy_preference", "natural_language") if k in req}
    legend = "\n".join(f"// {k}: [{v}]" for k, v in field_tags(explicit_fields).items())
    return legend + "\n" + json.dumps(body, ensure_ascii=False, indent=2, default=str)


def build_messages(req: dict[str, Any], desc: Descriptor, *, as_of: str, initial_amount_usd: float, context: str = "",
                   dialog_history: str = "", max_questions: int = 5, asked_fields: Sequence[str] = (), explicit_fields: Sequence[str] = ()) -> list[Message]:  # fmt: skip
    system, user = load_prompts(
        STAGE,
        user_request_jsonc=request_text(req, explicit_fields),
        as_of=as_of,
        initial_amount_usd=f"{initial_amount_usd:,.0f}",
        gics_tree=D.render_tree(desc),
        context=context or "(없음)",
        dialog_history=dialog_history or "(없음)",
        max_questions=max_questions,
        asked_fields=", ".join(asked_fields) or "없음",
    )
    return [{"role": "system", "content": system}, {"role": "user", "content": user}]


def effective_max_drawdown(req: dict[str, Any]) -> float:
    """낙폭 맞춤안 목표 (코드 규칙, 프롬프트 02_intent 와 같은 규칙): 요청값 × 0.8(loss_reaction=sell) × 0.9(investment_experience=none).
    라운드 5 부터 검증·표시의 허용 낙폭은 요청값 그대로이고, 이 값은 낙폭 맞춤안(dd_match_*)이 맞추는 목표에만 쓴다."""
    tol = float(req["risk"]["max_drawdown_tolerance"])
    if req["risk"].get("loss_reaction") == "sell":
        tol *= 0.8
    if req.get("profile", {}).get("investment_experience") == "none":
        tol *= 0.9
    return round(tol, 6)


def _check(ans: dict[str, Any]) -> None:
    th = ans.get("interpretation", {}).get("themes")
    if not (isinstance(th, list) and th):
        raise ValueError("interpretation.themes must be a non-empty list")
    for k in ("screen", "risk_params", "news_tilt", "validation_criteria", "report_settings"):
        if k not in ans:
            raise ValueError(f"missing key {k}")
    if "questions" in ans and not isinstance(ans["questions"], list):
        raise ValueError("questions must be a list")


def interpret(
    req: dict[str, Any],
    desc: Descriptor,
    llm: LlmClient,
    settings: AnalysisSettings,
    *,
    messages: Sequence[Message] | None = None,
    context: str = "",
    dialog_history: str = "",
    asked_fields: Sequence[str] = (),
) -> tuple[IntentSpec, list[str], list[Message]]:
    """(IntentSpec, warnings, 이번 호출의 메시지 목록). `messages` 를 주면 그 대화를 이어서 보낸다 (멀티턴)."""
    derived = req["derived"]
    msgs = list(messages) if messages else build_messages(
        req, desc, as_of=str(derived["as_of"]), initial_amount_usd=float(derived["initial_amount_usd"]), context=context,
        dialog_history=dialog_history, max_questions=settings.dialog.max_questions, asked_fields=asked_fields,
    )  # fmt: skip
    ans = llm.complete_json(STAGE, msgs, validator=_check)

    warnings: list[str] = []
    known = D.known_codes(desc)
    universe = set(D.tickers(desc))
    for th in ans["interpretation"]["themes"] + ans.get("exclude_theme_rules", []):
        codes = [str(c) for c in th.get("gics_codes", [])]
        bad = [c for c in codes if c not in known]
        if bad:
            warnings.append(f"theme {th.get('id', th.get('theme'))}: dropped unknown GICS codes {bad}")
        th["gics_codes"] = [c for c in codes if c in known]
        if "example_tickers" in th:
            out = [t for t in th["example_tickers"] if t not in universe]
            if out:
                warnings.append(f"theme {th['id']}: dropped tickers outside universe {out}")
            th["example_tickers"] = [t for t in th["example_tickers"] if t in universe]
    warnings += clean_exclude_rules(ans.get("exclude_theme_rules", []))
    ans["request_id"] = req["request_id"]
    sp, cons = req["strategy_preference"], req["constraints"]
    metric, direction = TEMPLATE_METRICS[sp["template"]]
    forced = {"template": sp["template"], "metric": metric, "direction": direction, "as_of": str(derived["as_of"]),
              "select_top_n": cons["num_holdings"]["target"]}  # fmt: skip
    ans.setdefault("screen", {})
    for k, v in forced.items():
        if str(ans["screen"].get(k)) != str(v):
            if ans["screen"].get(k) is not None:
                warnings.append(f"screen.{k}: LLM gave {ans['screen'].get(k)!r}, enforced {v!r}")
            ans["screen"][k] = v
    ans["news_tilt"]["enabled"] = bool(sp["use_news_tilt"])
    # 숫자는 코드가 정한다 (HARD 필드): 허용 낙폭·목표수익·비교지수·투자기간. LLM 값은 경고만 남기고 덮어쓴다.
    eff = effective_max_drawdown(req)
    rp = ans.setdefault("risk_params", {})
    if rp.get("effective_max_drawdown") is not None and abs(float(rp["effective_max_drawdown"]) - eff) > 1e-9:
        warnings.append(f"risk_params.effective_max_drawdown: LLM gave {rp['effective_max_drawdown']!r}, enforced {eff!r}")
    rp["effective_max_drawdown"] = eff
    vc = ans.setdefault("validation_criteria", {})
    # 검증·표시에 쓰는 허용 낙폭은 사용자 입력값 그대로 (라운드 5). 보정값(eff)은 낙폭 맞춤안의 목표로만 쓴다.
    # 투자기간도 확정된 요청값 (013: 요청 10년인데 LLM 이 아이디어의 '약 15년' 을 적어 R2 가 '투자기간 15년' 으로 판정하고, 리포트가 스스로 만든 불일치를 경고했다)
    hz = (req.get("horizon") or {}).get("target_years")
    for k, v in (("max_drawdown", float(req["risk"]["max_drawdown_tolerance"])), ("target_annual_return", float(req["risk"]["target_annual_return"])), ("benchmark", req["risk"]["benchmark"]),
                 *((("horizon_years", float(hz)),) if hz is not None else ())):  # fmt: skip
        cur = vc.get(k)
        same = (abs(float(cur) - v) < 1e-9) if isinstance(v, float) and cur is not None else (cur == v)
        if cur is not None and not same:
            warnings.append(f"validation_criteria.{k}: LLM gave {cur!r}, enforced {v!r}")
        vc[k] = v
    ans["warnings"] = warnings
    qs = []
    for q in ans.get("questions") or []:
        if isinstance(q, dict) and q.get("field") and q.get("question_ko"):
            q.setdefault("kind", "ambiguous")
            q.setdefault("options", [])
            q["options"] = [o if isinstance(o, dict) else {"value": o, "label_ko": str(o)} for o in q["options"]]
            qs.append(q)
    ans["questions"] = qs
    spec = IntentSpec.model_validate(ans)
    return spec, warnings, msgs
