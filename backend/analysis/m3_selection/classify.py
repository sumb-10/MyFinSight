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


def _check(a: dict[str, Any]) -> None:
    if not isinstance(a.get("results"), list):
        raise ValueError("results must be a list of {ticker, in_theme, themes, confidence, reason_ko, excluded_theme}")


def classify(cand: Candidates, intent: IntentSpec | dict[str, Any], llm: LlmClient, *, batch_size: int = BATCH, max_workers: int = 1,
             cancel_check: Callable[[], bool] | None = None) -> Tagging:  # fmt: skip
    """배치는 max_workers 개까지 동시에 LLM 에 보낸다 (라운드 4). 결과·경고는 배치 순서대로 모아 순차 실행과 같다."""
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
            ws.append(f"batch {bi}: no classification for {t} -> treated as not in theme")
            got[t] = {"ticker": t, "in_theme": False, "themes": [], "confidence": 0.0, "reason_ko": "LLM 응답 누락", "excluded_theme": None}
        return got, ws

    for got, ws in map_ordered(list(enumerate(batches, 1)), _one, max_workers=max_workers, cancel_check=cancel_check):
        results.update(got)
        warnings += ws

    tagged: list[TagResult] = []
    excluded: list[TagResult] = []
    forced = {x.ticker for x in rows if x.forced}
    for x in rows:
        raw = dict(results[x.ticker])
        raw["confidence"] = min(max(float(raw.get("confidence", 0) or 0), 0.0), 1.0)
        raw.setdefault("reason_ko", "")
        r = TagResult.model_validate(raw)
        bad = [t for t in r.themes if t not in theme_ids]
        if bad:
            warnings.append(f"{r.ticker}: unknown theme ids {bad} removed")
            r.themes = [t for t in r.themes if t in theme_ids]
        if x.forced and not r.in_theme:
            warnings.append(f"{r.ticker}: must_include but not in theme -> kept (forced)")
        (excluded if r.excluded_theme else tagged).append(r)
    passed = [r.ticker for r in tagged if (r.in_theme and r.confidence >= min_conf) or r.ticker in forced]
    return Tagging(request_id=cand.request_id, min_confidence=min_conf, tagged=tagged, excluded_by_theme=excluded,
                   passed_tickers=passed, batches=len(batches), warnings=warnings)  # fmt: skip
