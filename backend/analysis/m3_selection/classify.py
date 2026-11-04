"""M3-03 후보 분류기 (LLM #2, 40개 배치, 배치 병렬). 후보마다 테마 해당 여부·신뢰도·사유. 응답에 없는 후보는 미통과 + 경고."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from backend.analysis.common.llm import LlmClient, messages_from_prompts
from backend.analysis.common.prompts import load_prompts
from backend.analysis.executor.parallel import map_ordered
from backend.analysis.schemas.intent import IntentSpec
from backend.analysis.schemas.selection import Candidates, Tagging, TagResult

STAGE = "04_classify"
BATCH = 40


def _themes_block(themes: list[dict[str, Any]]) -> str:
    return "\n".join(f"- `{t['id']}` **{t['label_ko']}**: {t['description_ko']}" for t in themes)


def _exclude_block(rules: list[dict[str, Any]]) -> str:
    return "\n".join(f"- `{r['theme']}`: 키워드 {', '.join(r.get('keywords', []))}" for r in rules) or "- 없음"


def is_broad_theme(themes: list[dict[str, Any]], min_sectors: int) -> bool:
    """넓은 테마 = 한 테마의 GICS 코드가 그 테마 안에서만 섹터(앞 2자리) min_sectors 개 이상에 걸침 (예: '고배당 기업' 이 11개 섹터 전부를
    2자리로 나열(000·014)하거나 4·6자리 코드 25개로 나열(013)). 03 검색과 같은 앞 2자리 기준이다.
    여러 테마를 합쳐야 섹터 수가 많아지는 좁은 테마(가치사슬 아이디어)는 테마마다 섹터가 적어 넓은 테마가 아니다 — 이때는 테마 판정으로 거른다.
    013: 2자리 코드만 세서 03(넓은 테마 → 배당수익률 순 상한)과 판단이 갈렸고, 04 가 배당 수준을 기억으로 다시 판정해 120개 중 30개를 떨어뜨렸다."""
    return any(len({str(c).strip()[:2] for c in th.get("gics_codes", []) if str(c).strip()}) >= min_sectors for th in themes)


def _check(a: dict[str, Any]) -> None:
    if not isinstance(a.get("results"), list):
        raise ValueError("results must be a list of {ticker, in_theme, themes, confidence, reason_ko, excluded_theme}")


def classify(cand: Candidates, intent: IntentSpec | dict[str, Any], llm: LlmClient, *, batch_size: int = BATCH, max_workers: int = 1,
             cancel_check: Callable[[], bool] | None = None, broad: bool = False) -> Tagging:  # fmt: skip
    """배치는 max_workers 개까지 동시에 LLM 에 보낸다 (라운드 4). 결과·경고는 배치 순서대로 모아 순차 실행과 같다.

    broad: 테마가 여러 섹터(설정 broad_theme_min_sectors 이상)에 걸친 넓은 테마. 이때 테마 = 선정 기준(예: '고배당 기업')이라
    LLM 이 '배당수익률이 낮은 편' 처럼 기준을 정성적으로 다시 판정해 후보 절반을 떨어뜨렸다(000: 118 → 55). 순위는 코드가 정하므로
    (Module3 §1) 넓은 테마에서는 제외 테마 판정만 쓰고 테마 해당 여부로는 거르지 않는다.
    """
    it = intent.model_dump(mode="json") if isinstance(intent, IntentSpec) else intent
    themes = it["interpretation"]["themes"]
    theme_ids = {t["id"] for t in themes}
    min_conf = it["screen"]["theme_filter"]["min_confidence"]
    rows = cand.candidates
    batches = [b for b in (rows[i : i + batch_size] for i in range(0, len(rows), batch_size)) if b]
    warnings: list[str] = []
    results: dict[str, dict[str, Any]] = {}

    def _one(item: tuple[int, list[Any]]) -> tuple[dict[str, dict[str, Any]], list[str]]:
        bi, batch = item
        block = "\n".join(f"{x.ticker} | {x.name} | {x.gics.sub_industry.name} | {x.company_summary}" for x in batch)
        system, user = load_prompts(STAGE, batch_index=bi, batch_total=len(batches), batch_size=len(batch),
                                    themes_block=_themes_block(themes), exclude_block=_exclude_block(it.get("exclude_theme_rules", [])),
                                    candidates_block=block)  # fmt: skip
        ans = llm.complete_json(STAGE, messages_from_prompts(system, user), validator=_check, batch=bi if len(batches) > 1 else None)
        want = {x.ticker for x in batch}
        got = {r["ticker"]: r for r in ans["results"] if isinstance(r, dict) and r.get("ticker") in want}
        extra = {r.get("ticker") for r in ans["results"] if isinstance(r, dict)} - want
        ws: list[str] = []
        if extra and len(batches) == 1:
            ws.append(f"batch {bi}: LLM returned tickers not in batch {sorted(str(x) for x in extra)}")
        for t in sorted(want - set(got)):
            ws.append(f"batch {bi}: no classification for {t} -> not passed (theme and exclude-theme judgement missing)")
            got[t] = {"ticker": t, "in_theme": False, "themes": [], "confidence": 0.0, "reason_ko": "LLM 응답 누락", "excluded_theme": None, "_missing": True}
        return got, ws

    for got, ws in map_ordered(list(enumerate(batches, 1)), _one, max_workers=max_workers, cancel_check=cancel_check):
        results.update(got)
        warnings += ws

    tagged: list[TagResult] = []
    excluded: list[TagResult] = []
    forced = {x.ticker for x in rows if x.forced}
    rule_names = {_norm_theme(r.get("theme", "")): r.get("theme") for r in it.get("exclude_theme_rules", []) or []}
    missing = {t for t, r in results.items() if r.get("_missing")}
    for x in rows:
        raw = {k: v for k, v in results[x.ticker].items() if k != "_missing"}
        raw["confidence"] = min(max(float(raw.get("confidence", 0) or 0), 0.0), 1.0)
        raw.setdefault("reason_ko", "")
        r = TagResult.model_validate(raw)
        bad = [t for t in r.themes if t not in theme_ids]
        if bad:
            warnings.append(f"{r.ticker}: unknown theme ids {bad} removed")
            r.themes = [t for t in r.themes if t in theme_ids]
        if r.excluded_theme and _norm_theme(r.excluded_theme) not in rule_names:  # '없음'·'none'·모르는 이름은 제외 사유가 아니다
            warnings.append(f"{r.ticker}: excluded_theme {r.excluded_theme!r} is not an exclude rule -> ignored")
            r.excluded_theme = None
        elif r.excluded_theme:
            r.excluded_theme = rule_names[_norm_theme(r.excluded_theme)]  # 규칙 이름 그대로 (공지·표가 같은 이름을 쓰게)
        if x.forced and not r.in_theme and not broad:  # 넓은 테마는 테마 판정으로 거르지 않으므로 '테마 불통과' 공지가 뜻이 없다
            warnings.append(f"{r.ticker}: must_include but not in theme -> kept (forced)")
        if x.forced and r.excluded_theme:  # 필수 포함이 제외 테마와 겹치면 조용히 빠지지 않게: 유지하고 알린다
            warnings.append(f"{r.ticker}: must_include matches excluded theme {r.excluded_theme} -> kept by request")
            tagged.append(r)
            continue
        (excluded if r.excluded_theme else tagged).append(r)
    if broad:
        # 응답이 빠진 종목은 제외 테마 판정도 없으므로 통과시키지 않는다 (강제 포함 제외)
        passed = [r.ticker for r in tagged if r.ticker not in missing or r.ticker in forced]
        off = [r for r in tagged if r.ticker not in missing and not ((r.in_theme and r.confidence >= min_conf) or r.ticker in forced)]
        for r in off:  # 넓은 테마에서는 테마 판정으로 거르지 않았다 → '테마 판정 사유·신뢰도' 로 보이지 않게
            r.reason_ko = "넓은 테마라 테마 판정으로 거르지 않고 선정 지표 순위로 고름"
        if off:
            warnings.append(f"broad theme: theme filter not applied ({len(off)} candidates kept that the classifier rated off-theme; ranking is by the selection metric)")
    else:
        passed = [r.ticker for r in tagged if (r.in_theme and r.confidence >= min_conf) or r.ticker in forced]
    return Tagging(request_id=cand.request_id, min_confidence=min_conf, tagged=tagged, excluded_by_theme=excluded,
                   passed_tickers=passed, batches=len(batches), warnings=warnings, theme_filter_applied=not broad)  # fmt: skip


def _norm_theme(x: Any) -> str:
    return str(x or "").strip().lower().replace("-", "_").replace(" ", "_")
