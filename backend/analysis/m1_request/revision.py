"""M1-05 수정 요청: 기준 리포트 + 자연어 수정 → LLM 이 변경 필드를 제안 → 코드가 검증·적용 → revision 모드 대화로 이어간다.

- 바꿀 수 있는 필드(REVISABLE)만 반영한다. 평가 조건(FROZEN: 기간·자본·적립·비교지수·리밸런싱·유니버스)은 원안 값으로 고정해
  수정안 비교가 공정하게 되도록 한다 (Module1 §수정 요청, Module5 §6).
- 적용 결과는 HARD 규칙(validate.hard_errors)을 통과해야 한다. 통과하지 못하면 그 변경은 unsupported 로 돌린다.
- 숫자·목록 값은 LLM 이 낸 값을 코드가 형 변환·범위 확인만 하고, 지어낸 값은 받지 않는다 (원안과 같은 값은 변경이 아니다).
"""

from __future__ import annotations

import copy
import json
from typing import Any

from backend.analysis.common.llm import LlmClient
from backend.analysis.common.prompts import load_prompts
from backend.analysis.m1_request.assemble import get_path, set_path
from backend.analysis.m1_request.validate import hard_errors, label
from backend.analysis.schemas.dialog import RevisionChange, RevisionDraft

STAGE = "15_revision"

REVISABLE: dict[str, type | tuple[type, ...]] = {
    "constraints.exclude_tickers": list, "constraints.must_include_tickers": list, "constraints.exclude_sectors": list, "constraints.exclude_themes": list,
    "constraints.num_holdings": dict, "constraints.max_weight_per_stock": (int, float), "constraints.max_weight_per_sector": (int, float), "constraints.min_cash_ratio": (int, float),
    "strategy_preference.template": str, "strategy_preference.baseline_weighting": str, "strategy_preference.use_news_tilt": bool,
    "risk.max_drawdown_tolerance": (int, float), "risk.target_annual_return": (int, float), "risk.risk_tolerance": str, "risk.loss_reaction": str,
}  # fmt: skip
# 원안과 같게 고정하는 평가 조건 (바꾸면 비교가 공정하지 않다)
FROZEN = ("capital.initial_amount", "capital.currency", "capital.monthly_contribution", "capital.contribution_day", "horizon.start_date", "horizon.backtest_years",
          "horizon.target_years", "risk.benchmark", "constraints.rebalance", "constraints.universe", "constraints.asset_types", "constraints.min_market_cap_usd",
          "constraints.min_avg_daily_volume_usd")  # fmt: skip
FROZEN_NOTE = "수정안 비교에서는 원안과 같은 조건(기간·자본·적립·비교지수·리밸런싱·종목 범위)을 유지합니다. 조건 자체를 바꾸려면 새 분석을 시작해 주세요"


def _check(ans: dict[str, Any]) -> None:
    if not isinstance(ans.get("changes", []), list):
        raise ValueError("changes must be a list")
    if not isinstance(ans.get("unsupported_ko", []), list):
        raise ValueError("unsupported_ko must be a list")


def frozen_overrides(base_request: dict[str, Any]) -> dict[str, Any]:
    """원안의 평가 조건을 그대로 덮어쓰기로 만든다 (프로필이 그 사이 바뀌어도 원안과 같게)."""
    out: dict[str, Any] = {}
    for f in FROZEN:
        v = get_path(base_request, f)
        if v is not None:
            out[f] = copy.deepcopy(v)
    as_of = (base_request.get("derived") or {}).get("as_of") or (base_request.get("horizon") or {}).get("start_date")
    if as_of:
        out["horizon.start_date"] = str(as_of)  # 기준일(=백테스트 끝)을 원안과 같게
    return out


def _coerce(field: str, value: Any) -> Any:
    want = REVISABLE[field]
    if want is list:
        if isinstance(value, str):
            value = [x.strip() for x in value.replace(",", " ").split() if x.strip()]
        if not isinstance(value, list):
            raise ValueError("목록이어야 합니다")
        return [str(x).strip().upper() if field.endswith("tickers") else str(x).strip() for x in value]
    if want is bool:
        if isinstance(value, str):
            return value.strip().lower() in ("true", "yes", "예", "켜기", "on", "1")
        return bool(value)
    if want is dict:
        if not isinstance(value, dict):
            raise ValueError("객체여야 합니다")
        return {k: int(v) for k, v in value.items() if k in ("target", "min", "max")}
    if want is str:
        return str(value).strip()
    v = float(value)
    if field.startswith(("constraints.max_weight", "constraints.min_cash", "risk.max_drawdown", "risk.target_annual")) and v > 1:
        v = v / 100.0  # 15 → 0.15 (퍼센트로 적은 경우)
    return round(v, 6)


def propose(base_request: dict[str, Any], base_intent: dict[str, Any], holdings: list[tuple[str, str]], text: str, llm: LlmClient) -> RevisionDraft:
    """LLM 제안 → 코드 검증. 돌려주는 초안의 changes 중 supported 만 overrides 로 쓴다."""
    body = {k: base_request[k] for k in ("capital", "horizon", "risk", "constraints", "strategy_preference", "natural_language") if k in base_request}
    themes = ", ".join(t.get("label_ko") or t.get("id", "") for t in base_intent.get("interpretation", {}).get("themes", []))
    system, user = load_prompts(STAGE, base_request=json.dumps(body, ensure_ascii=False, indent=1, default=str), themes=themes or "(없음)",
                                holdings=", ".join(f"{t} · {n}" for t, n in holdings) or "(없음)", text=text.strip())  # fmt: skip
    ans = llm.complete_json(STAGE, [{"role": "system", "content": system}, {"role": "user", "content": user}], validator=_check)
    draft = RevisionDraft(text=text.strip(), summary_ko=ans.get("summary_ko"), idea_update_ko=(ans.get("idea_update_ko") or None),
                          unsupported_ko=[str(x) for x in ans.get("unsupported_ko", [])], frozen_fields=list(FROZEN))  # fmt: skip
    trial = copy.deepcopy(base_request)
    for ch in ans.get("changes", []):
        if not isinstance(ch, dict) or not ch.get("field"):
            continue
        field = str(ch["field"]).strip()
        reason = ch.get("reason_ko")
        if field in FROZEN or any(field.startswith(f + ".") for f in FROZEN):
            draft.changes.append(RevisionChange(field=field, value=ch.get("value"), base_value=get_path(base_request, field), label_ko=label(field), reason_ko=reason, supported=False, note_ko=FROZEN_NOTE))
            continue
        if field not in REVISABLE:
            draft.changes.append(RevisionChange(field=field, value=ch.get("value"), base_value=get_path(base_request, field), label_ko=label(field), reason_ko=reason, supported=False,
                                                note_ko="이 항목은 수정 요청으로 바꿀 수 없습니다"))  # fmt: skip
            continue
        try:
            value = _coerce(field, ch.get("value"))
        except (TypeError, ValueError) as e:
            draft.changes.append(RevisionChange(field=field, value=ch.get("value"), base_value=get_path(base_request, field), label_ko=label(field), reason_ko=reason, supported=False, note_ko=f"값을 읽을 수 없습니다: {e}"))
            continue
        base_v = get_path(base_request, field)
        if field == "constraints.num_holdings" and isinstance(value, dict) and isinstance(base_v, dict):
            value = _rescale_holdings(value, base_v)  # '종목 20개로' 가 20~20 으로 굳지 않게 최소·최대를 원안 비율로 (라운드 5)
        if value == base_v:
            draft.changes.append(RevisionChange(field=field, value=value, base_value=base_v, label_ko=label(field), reason_ko=reason, supported=False, note_ko="원안과 같은 값이라 바꿀 것이 없습니다"))
            continue
        attempt = copy.deepcopy(trial)
        set_path(attempt, field, value)
        errs = hard_errors(attempt)
        if errs:
            draft.changes.append(RevisionChange(field=field, value=value, base_value=base_v, label_ko=label(field), reason_ko=reason, supported=False,
                                                note_ko="; ".join(e.message_ko for e in errs[:2])))  # fmt: skip
            continue
        trial = attempt
        draft.changes.append(RevisionChange(field=field, value=value, base_value=base_v, label_ko=label(field), reason_ko=reason, supported=True))
    if not any(c.supported for c in draft.changes) and not draft.idea_update_ko:
        draft.unsupported_ko.append("반영할 수 있는 변경을 찾지 못했습니다. 빼거나 넣을 종목, 종목 수, 비중 상한, 선정 기준처럼 바꿀 항목을 적어 주세요")
    return draft


def _rescale_holdings(value: dict[str, Any], base: dict[str, Any]) -> dict[str, Any]:
    """목표만 바뀐(또는 최소=목표=최대로 굳은) 종목 수를 원안의 최소/목표·최대/목표 비율로 다시 벌린다. 2 ≤ min ≤ target ≤ max ≤ 50."""
    try:
        t = int(value.get("target") or base.get("target"))
        bt, bmin, bmax = int(base.get("target") or t), int(base.get("min") or t), int(base.get("max") or t)
    except (TypeError, ValueError):
        return value
    only_target = set(k for k in value if value.get(k) is not None) <= {"target"} or (value.get("min") == value.get("max") == t and bmin != bmax)
    if not only_target or bt <= 0:
        return value
    lo = max(2, min(t, round(t * bmin / bt)))
    hi = min(50, max(t, round(t * bmax / bt)))
    return {"target": t, "min": lo, "max": hi}


def overrides_from(draft: RevisionDraft, base_request: dict[str, Any]) -> dict[str, Any]:
    """revision 모드 대화에 넘길 덮어쓰기: 평가 조건 고정 + 지원되는 변경."""
    out = frozen_overrides(base_request)
    for c in draft.changes:
        if c.supported:
            out[c.field] = c.value
    return out
